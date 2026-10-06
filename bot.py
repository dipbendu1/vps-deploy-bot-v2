import discord
from discord.ext import commands
import asyncio
import subprocess
import json
from datetime import datetime
import shlex
import logging
import shutil
import os
from typing import Optional, List, Dict, Any
import threading
import time
import sqlite3
import random
import requests
import secrets
import string
import re

# Load environment variables
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN', '')
BOT_NAME = os.getenv('BOT_NAME', 'DB-v2')
PREFIX = os.getenv('PREFIX', '!')
YOUR_SERVER_IP = os.getenv('YOUR_SERVER_IP', '127.0.0.1')

# ---- Public IP detection ----
_cached_public_ip = None

def get_public_ip() -> str:
    global _cached_public_ip
    if _cached_public_ip:
        return _cached_public_ip
    try:
        resp = requests.get("https://ifconfig.me/ip", timeout=5)
        ip = resp.text.strip()
        if ip:
            _cached_public_ip = ip
            return ip
    except Exception as e:
        logger.warning(f"Failed to fetch public IP from ifconfig.me: {e}")
    return YOUR_SERVER_IP

_raw_main_admin_ids = os.getenv('MAIN_ADMIN_ID', '1405866008127864852')
MAIN_ADMIN_IDS_ENV = [uid.strip() for uid in _raw_main_admin_ids.split(',') if uid.strip()]
MAIN_ADMIN_ID = int(MAIN_ADMIN_IDS_ENV[0])
VPS_USER_ROLE_ID = int(os.getenv('VPS_USER_ROLE_ID', '1210291131301101618'))
DEFAULT_STORAGE_POOL = os.getenv('DEFAULT_STORAGE_POOL', 'default')
BOT_VERSION = os.getenv('BOT_VERSION', '9.0-PRO')

# Developer Name aur Photo/Thumbnail URL
BOT_DEVELOPER = os.getenv('BOT_DEVELOPER', 'DB GAMING')
DEVELOPER_AVATAR_URL = os.getenv('DEVELOPER_AVATAR_URL', 'https://example.com/your-photo.jpg')

# OS Options for VPS Creation and Reinstall
OS_OPTIONS = [
    {"label": "Ubuntu 20.04 LTS", "value": "ubuntu:20.04"},
    {"label": "Ubuntu 22.04 LTS", "value": "ubuntu:22.04"},
    {"label": "Ubuntu 24.04 LTS", "value": "ubuntu:24.04"},
    {"label": "Debian 10 (Buster)", "value": "images:debian/10"},
    {"label": "Debian 11 (Bullseye)", "value": "images:debian/11"},
    {"label": "Debian 12 (Bookworm)", "value": "images:debian/12"},
    {"label": "Debian 13 (Trixie)", "value": "images:debian/13"},
]

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(f'{BOT_NAME.lower()}_vps_bot')

def get_db():
    conn = sqlite3.connect('vps.db')
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS admins (user_id TEXT PRIMARY KEY)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS main_admins (user_id TEXT PRIMARY KEY)''')
    for uid in MAIN_ADMIN_IDS_ENV:
        cur.execute('INSERT OR IGNORE INTO main_admins (user_id) VALUES (?)', (uid,))
    cur.execute('''CREATE TABLE IF NOT EXISTS nodes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        location TEXT,
        total_vps INTEGER,
        tags TEXT DEFAULT '[]',
        api_key TEXT,
        url TEXT,
        is_local INTEGER DEFAULT 0
    )''')
    cur.execute('SELECT COUNT(*) FROM nodes WHERE is_local = 1')
    if cur.fetchone()[0] == 0:
        cur.execute('INSERT INTO nodes (name, location, total_vps, tags, api_key, url, is_local) VALUES (?, ?, ?, ?, ?, ?, ?)',
                    ('Node', 'Local', 100, '[]', None, None, 1))
    cur.execute('''CREATE TABLE IF NOT EXISTS vps (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        node_id INTEGER NOT NULL DEFAULT 1,
        container_name TEXT UNIQUE NOT NULL,
        ram TEXT NOT NULL,
        cpu TEXT NOT NULL,
        storage TEXT NOT NULL,
        config TEXT NOT NULL,
        os_version TEXT DEFAULT 'ubuntu:22.04',
        status TEXT DEFAULT 'stopped',
        suspended INTEGER DEFAULT 0,
        whitelisted INTEGER DEFAULT 0,
        created_at TEXT NOT NULL,
        shared_with TEXT DEFAULT '[]',
        suspension_history TEXT DEFAULT '[]',
        root_password TEXT DEFAULT '',
        sshx_url TEXT DEFAULT ''
    )''')
    conn.commit()
    conn.close()

init_db()

vps_data = {}
admin_data = {'admins': []}
main_admin_ids = set(MAIN_ADMIN_IDS_ENV)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

def create_embed(title, description="", color=0x1a1a1a):
    embed = discord.Embed(
        title=f"🌟 {BOT_NAME} - {title}",
        description=description,
        color=color
    )
    embed.set_thumbnail(url=DEVELOPER_AVATAR_URL)
    embed.set_footer(text=f"Developer: {BOT_DEVELOPER} | {BOT_NAME} VPS v{BOT_VERSION}", icon_url=DEVELOPER_AVATAR_URL)
    return embed

def create_success_embed(title, description=""):
    return create_embed(title, description, color=0x00ff88)

def create_error_embed(title, description=""):
    return create_embed(title, description, color=0xff3366)

def create_info_embed(title, description=""):
    return create_embed(title, description, color=0x00ccff)

async def execute_lxc(container_name: str, command: str, timeout=120, node_id: int = 1):
    full_command = f"lxc {command}"
    cmd = shlex.split(full_command)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    if proc.returncode != 0:
        raise Exception(f"LXC failed: {stderr.decode().strip()}")
    return stdout.decode().strip() if stdout else True

async def setup_ssh_and_sshx(container_name: str, node_id: int) -> tuple[str, str]:
    password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(16))
    
    cmds = [
        "apt-get update -y && apt-get install -y openssh-server curl",
        f"echo 'root:{password}' | chpasswd",
        "sed -i 's/#PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config",
        "sed -i 's/PermitRootLogin prohibit-password/PermitRootLogin yes/' /etc/ssh/sshd_config",
        "sed -i 's/#PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config",
        "mkdir -p /run/sshd",
        "systemctl restart ssh || service ssh restart"
    ]
    for c in cmds:
        try:
            await execute_lxc(container_name, f"exec {container_name} -- bash -c \"{c}\"", node_id=node_id, timeout=120)
        except Exception as e:
            logger.warning(f"SSH setup warning: {e}")

    sshx_url = ""
    try:
        sshx_install_cmd = "curl -shttps://sshx.io/get | sh"
        await execute_lxc(container_name, f"exec {container_name} -- bash -c \"{sshx_install_cmd}\"", node_id=node_id, timeout=60)
        
        sshx_run_cmd = "nohup sshx > /root/sshx.log 2>&1 &"
        await execute_lxc(container_name, f"exec {container_name} -- bash -c \"{sshx_run_cmd}\"", node_id=node_id, timeout=10)
        await asyncio.sleep(3)
        
        log_output = await execute_lxc(container_name, f"exec {container_name} -- cat /root/sshx.log", node_id=node_id, timeout=10)
        match = re.search(r'https://sshx\.io/s/[^\s]+', log_output)
        if match:
            sshx_url = match.group(0)
    except Exception as e:
        logger.error(f"Failed to setup sshx: {e}")

    return password, sshx_url

@bot.event
async def on_ready():
    logger.print(f'{bot.user.name} online ho gaya hai aur successfully connected hai!')

if __name__ == '__main__':
    if DISCORD_TOKEN:
        bot.run(DISCORD_TOKEN)
    else:
        print("Error: DISCORD_TOKEN environment variable set nahi hai!")
