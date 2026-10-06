import discord
from discord.ext import commands
import asyncio
import subprocess
import json
from datetime import datetime, timedelta
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
import string
import secrets
from dotenv import load_dotenv
import re
import paramiko
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS

# Load environment variables from .env file
load_dotenv()

# Load environment variables
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
BOT_NAME = os.getenv('BOT_NAME', 'UnixNodes')
PREFIX = os.getenv('PREFIX', '!')
YOUR_SERVER_IP = os.getenv('YOUR_SERVER_IP', '127.0.0.1')
MAIN_ADMIN_ID = int(os.getenv('MAIN_ADMIN_ID', '1210291131301101618'))
VPS_USER_ROLE_ID = int(os.getenv('VPS_USER_ROLE_ID', '1210291131301101618'))
DEFAULT_STORAGE_POOL = os.getenv('DEFAULT_STORAGE_POOL', 'default')
HOST_MOTD = os.getenv('HOST_MOTD', 'bash <(curl -fsSL https://raw.githubusercontent.com/hopingboyz/linux/main/atyro-water-mark.sh)')
BOT_VERSION = os.getenv('BOT_VERSION', '8.0-PRO')
BOT_DEVELOPER = os.getenv('BOT_DEVELOPER', 'Minecloud')
BOT_THUMBNAIL_URL = os.getenv('BOT_THUMBNAIL_URL', 'https://i.imgur.com/Tv3clt0.jpeg')
BOT_ICON_URL = os.getenv('BOT_ICON_URL', 'https://i.imgur.com/Tv3clt0.jpeg')

# VPS Expiration Settings
DEFAULT_VPS_EXPIRATION_DAYS = int(os.getenv('DEFAULT_VPS_EXPIRATION_DAYS', '30'))
EXPIRATION_WARNING_DAYS = int(os.getenv('EXPIRATION_WARNING_DAYS', '1'))

# Public VPS Creation Settings
PUBLIC_VPS_ENABLED = os.getenv('PUBLIC_VPS_ENABLED', 'true').lower() == 'true'
PUBLIC_VPS_MAX_RAM = int(os.getenv('PUBLIC_VPS_MAX_RAM', '4'))
PUBLIC_VPS_MAX_CPU = int(os.getenv('PUBLIC_VPS_MAX_CPU', '2'))
PUBLIC_VPS_MAX_DISK = int(os.getenv('PUBLIC_VPS_MAX_DISK', '50'))
PUBLIC_VPS_EXPIRY_DAYS = int(os.getenv('PUBLIC_VPS_EXPIRY_DAYS', '30'))
PUBLIC_VPS_MAX_PER_USER = int(os.getenv('PUBLIC_VPS_MAX_PER_USER', '1'))
PUBLIC_VPS_MAX_PER_IP = int(os.getenv('PUBLIC_VPS_MAX_PER_IP', '3'))
PUBLIC_VPS_REQUIRE_VERIFICATION = os.getenv('PUBLIC_VPS_REQUIRE_VERIFICATION', 'false').lower() == 'true'

# Public VPS Renewal Settings
PUBLIC_VPS_RENEWAL_ENABLED = os.getenv('PUBLIC_VPS_RENEWAL_ENABLED', 'true').lower() == 'true'
PUBLIC_VPS_RENEWAL_DAYS = int(os.getenv('PUBLIC_VPS_RENEWAL_DAYS', '30'))

# Web SSH Terminal Settings
WEBSSH_ENABLED = os.getenv('WEBSSH_ENABLED', 'true').lower() == 'true'
WEBSSH_PORT = int(os.getenv('WEBSSH_PORT', '5000'))
WEBSSH_SERVER_IP = os.getenv('WEBSSH_SERVER_IP', '127.0.0.1')
WEBSSH_URL_FORMAT = os.getenv('WEBSSH_URL_FORMAT', 'http://{SERVER_IP}:{PORT}')

# SSH Configuration
SSH_FIX_SCRIPT = """#!/bin/bash
cat > /etc/ssh/sshd_config << 'SSHEOF'
Port 22
AddressFamily any
ListenAddress 0.0.0.0
ListenAddress ::
PasswordAuthentication yes
PubkeyAuthentication yes
PermitRootLogin yes
PermitEmptyPasswords no
ChallengeResponseAuthentication no
UsePAM yes
MaxAuthTries 6
MaxSessions 10
SyslogFacility AUTH
LogLevel INFO
X11Forwarding yes
X11DisplayOffset 10
PrintMotd no
PrintLastLog yes
TCPKeepAlive yes
PermitUserEnvironment no
Subsystem sftp /usr/lib/openssh/sftp-server
SSHEOF
systemctl restart ssh 2>/dev/null || service ssh restart 2>/dev/null || /etc/init.d/ssh restart 2>/dev/null || true
"""

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

# Configure logging to file and console
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(f'{BOT_NAME.lower()}_vps_bot')

# ═══════════════════════════════════════════════════════════════════════════
# ROBUST SQLITE DATABASE SYSTEM - PERSISTENT + CRASH SAFE + SILENT SAVES
# ═══════════════════════════════════════════════════════════════════════════

import atexit
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_FILE = str(BASE_DIR / "vps.db")
DB_BACKUP_DIR = BASE_DIR / "db_backups"
DB_LOCK = threading.RLock()

DB_BACKUP_DIR.mkdir(parents=True, exist_ok=True)

def get_db():
    conn = sqlite3.connect(DB_FILE, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA wal_autocheckpoint=1000")
    return conn

def backup_database():
    try:
        if not os.path.exists(DB_FILE):
            return
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = DB_BACKUP_DIR / f"vps_backup_{timestamp}.db"
        with DB_LOCK:
            source = get_db()
            try:
                destination = sqlite3.connect(str(backup_path))
                try:
                    source.backup(destination)
                finally:
                    destination.close()
            finally:
                source.close()
        backups = sorted(DB_BACKUP_DIR.glob("vps_backup_*.db"))
        for old_backup in backups[:-10]:
            try:
                old_backup.unlink()
            except OSError:
                pass
    except Exception as e:
        logger.error(f"Database backup failed: {e}")

def init_db():
    with DB_LOCK:
        conn = get_db()
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("PRAGMA foreign_keys=ON")
            cur = conn.cursor()

            cur.execute("""
                CREATE TABLE IF NOT EXISTS admins (
                    user_id TEXT PRIMARY KEY,
                    added_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cur.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (str(MAIN_ADMIN_ID),))

            cur.execute("""
                CREATE TABLE IF NOT EXISTS nodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    location TEXT,
                    total_vps INTEGER,
                    tags TEXT DEFAULT '[]',
                    api_key TEXT,
                    url TEXT,
                    is_local INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    last_updated TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cur.execute("SELECT id FROM nodes WHERE is_local = 1 ORDER BY id LIMIT 1")
            if cur.fetchone() is None:
                cur.execute("""
                    INSERT INTO nodes (name, location, total_vps, tags, api_key, url, is_local)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, ("Local Node", "Local", 100, "[]", None, None, 1))

            cur.execute("""
                CREATE TABLE IF NOT EXISTS vps (
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
                    expiration_date TEXT DEFAULT NULL,
                    root_password TEXT DEFAULT NULL,
                    last_modified TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (node_id) REFERENCES nodes(id)
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    last_modified TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            for key, value in (("cpu_threshold", "90"), ("ram_threshold", "90")):
                cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))

            cur.execute("""
                CREATE TABLE IF NOT EXISTS port_allocations (
                    user_id TEXT PRIMARY KEY,
                    allocated_ports INTEGER DEFAULT 0,
                    last_modified TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS port_forwards (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    vps_container TEXT NOT NULL,
                    vps_port INTEGER NOT NULL,
                    host_port INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    last_modified TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_device_tracking (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    ip_address TEXT,
                    device_fingerprint TEXT,
                    username TEXT,
                    avatar_hash TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    last_seen TEXT DEFAULT CURRENT_TIMESTAMP,
                    vps_created INTEGER DEFAULT 0
                )
            """)
            
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

def get_setting(key: str, default: Any = None):
    with DB_LOCK:
        conn = get_db()
        try:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            return row[0] if row else default
        finally:
            conn.close()

def set_setting(key: str, value: str):
    with DB_LOCK:
        conn = get_db()
        try:
            conn.execute("""
                INSERT INTO settings (key, value, last_modified)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, last_modified = CURRENT_TIMESTAMP
            """, (key, value))
            conn.commit()
        finally:
            conn.close()

def get_nodes() -> List[Dict]:
    with DB_LOCK:
        conn = get_db()
        try:
            rows = conn.execute("SELECT * FROM nodes ORDER BY id").fetchall()
            nodes = []
            for row in rows:
                node = dict(row)
                try:
                    node["tags"] = json.loads(node.get("tags") or "[]")
                except:
                    node["tags"] = []
                node["is_local"] = int(node.get("is_local", 1)) == 1
                nodes.append(node)
            return nodes
        finally:
            conn.close()

def get_node(node_id: int) -> Optional[Dict]:
    with DB_LOCK:
        conn = get_db()
        try:
            row = conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
            if not row:
                return None
            node = dict(row)
            try:
                node["tags"] = json.loads(node.get("tags") or "[]")
            except:
                node["tags"] = []
            node["is_local"] = int(node.get("is_local", 1)) == 1
            return node
        finally:
            conn.close()

def _decode_vps_row(row) -> Dict[str, Any]:
    vps = dict(row)
    try:
        vps["shared_with"] = json.loads(vps.get("shared_with") or "[]")
    except:
        vps["shared_with"] = []
    try:
        vps["suspension_history"] = json.loads(vps.get("suspension_history") or "[]")
    except:
        vps["suspension_history"] = []
    vps["suspended"] = bool(vps.get("suspended", 0))
    vps["whitelisted"] = bool(vps.get("whitelisted", 0))
    vps["os_version"] = vps.get("os_version") or "ubuntu:22.04"
    return vps

def get_vps_data() -> Dict[str, List[Dict[str, Any]]]:
    with DB_LOCK:
        conn = get_db()
        try:
            rows = conn.execute("SELECT * FROM vps ORDER BY id").fetchall()
            data: Dict[str, List[Dict[str, Any]]] = {}
            for row in rows:
                vps = _decode_vps_row(row)
                data.setdefault(str(vps["user_id"]), []).append(vps)
            return data
        finally:
            conn.close()

def get_admins() -> List[str]:
    with DB_LOCK:
        conn = get_db()
        try:
            rows = conn.execute("SELECT user_id FROM admins ORDER BY user_id").fetchall()
            return [str(row["user_id"]) for row in rows]
        finally:
            conn.close()

def save_vps_data():
    with DB_LOCK:
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN IMMEDIATE")
            for user_id, vps_list in list(vps_data.items()):
                for vps in list(vps_list):
                    container_name = str(vps.get("container_name") or "").strip()
                    if not container_name:
                        continue
                    cur.execute("""
                        INSERT INTO vps (
                            user_id, node_id, container_name, ram, cpu, storage,
                            config, os_version, status, suspended, whitelisted,
                            created_at, shared_with, suspension_history,
                            expiration_date, root_password, last_modified
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                        ON CONFLICT(container_name) DO UPDATE SET
                            user_id = excluded.user_id,
                            node_id = excluded.node_id,
                            ram = excluded.ram,
                            cpu = excluded.cpu,
                            storage = excluded.storage,
                            config = excluded.config,
                            os_version = excluded.os_version,
                            status = excluded.status,
                            suspended = excluded.suspended,
                            whitelisted = excluded.whitelisted,
                            created_at = excluded.created_at,
                            shared_with = excluded.shared_with,
                            suspension_history = excluded.suspension_history,
                            expiration_date = excluded.expiration_date,
                            root_password = excluded.root_password,
                            last_modified = CURRENT_TIMESTAMP
                    """, (
                        str(user_id), int(vps.get("node_id", 1)), container_name,
                        str(vps.get("ram", "0GB")), str(vps.get("cpu", "0")), str(vps.get("storage", "0GB")),
                        str(vps.get("config", "Custom")), str(vps.get("os_version", "ubuntu:22.04")),
                        str(vps.get("status", "stopped")), 1 if vps.get("suspended", False) else 0,
                        1 if vps.get("whitelisted", False) else 0, str(vps.get("created_at") or datetime.now().isoformat()),
                        json.dumps(vps.get("shared_with", [])), json.dumps(vps.get("suspension_history", [])),
                        vps.get("expiration_date"), vps.get("root_password")
                    ))
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Error saving VPS data: {e}")
        finally:
            conn.close()

def save_vps_data_immediate():
    try:
        save_vps_data()
    except Exception as e:
        logger.error(f"Immediate save failed: {e}")

def save_admin_data():
    with DB_LOCK:
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN IMMEDIATE")
            admin_ids = {str(x) for x in admin_data.get("admins", [])}
            admin_ids.add(str(MAIN_ADMIN_ID))
            cur.execute("DELETE FROM admins")
            cur.executemany("INSERT INTO admins (user_id) VALUES (?)", [(aid,) for aid in admin_ids])
            conn.commit()
            admin_data["admins"] = sorted(admin_ids)
        finally:
            conn.close()

def find_node_id_for_container(container_name: str) -> int:
    with DB_LOCK:
        conn = get_db()
        try:
            row = conn.execute("SELECT node_id FROM vps WHERE container_name = ?", (container_name,)).fetchone()
            return int(row[0]) if row else 1
        finally:
            conn.close()

# Initialize DB & Load States
try:
    init_db()
except Exception as e:
    logger.error(f"Fatal DB init error: {e}")
    raise

vps_data = get_vps_data()
admin_data = {"admins": get_admins()}

async def auto_save_task():
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            await asyncio.sleep(15)
            save_vps_data()
            save_admin_data()
        except asyncio.CancelledError:
            raise
        except Exception:
            pass

atexit.register(lambda: (save_vps_data(), save_admin_data()))

# Global Thresholds & Bot Setup
CPU_THRESHOLD = int(get_setting('cpu_threshold', 90))
RAM_THRESHOLD = int(get_setting('ram_threshold', 90))

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

# ═══════════════════════════════════════════════════════════════════════════
# FLASK WEB SSH SERVER
# ═══════════════════════════════════════════════════════════════════════════

app = Flask(__name__)
CORS(app)
ssh_sessions = {}

@app.route('/')
def index():
    return '''
    <html>
        <head><title>Web SSH Terminal</title></head>
        <body style="background: #1e1e1e; color: #fff; font-family: monospace; display: flex; justify-content: center; align-items: center; height: 100vh;">
            <h1>🚀 UnixNodes WebSSH Server Active</h1>
        </body>
    </html>
    '''

@app.route('/api/ssh/connect', methods=['POST'])
def ssh_connect():
    try:
        data = request.json
        host = data.get('host')
        port = int(data.get('port', 22))
        username = data.get('username')
        password = data.get('password')

        if not all([host, port, username, password]):
            return jsonify({'success': False, 'error': 'Missing connection details'}), 400

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(host, port=port, username=username, password=password, timeout=15)

        transport = ssh.get_transport()
        transport.set_keepalive(30)
        channel = transport.open_session()
        channel.get_pty(term='xterm-256color', width=120, height=30)
        channel.invoke_shell()

        session_id = secrets.token_hex(16)
        ssh_sessions[session_id] = {
            'ssh': ssh, 'transport': transport, 'channel': channel,
            'host': host, 'port': port, 'username': username,
            'buffer': '', 'closed': False, 'lock': threading.Lock(), 'last_activity': datetime.now()
        }

        session = ssh_sessions[session_id]
        def reader():
            chan = session['channel']
            try:
                while True:
                    if chan.recv_ready():
                        chunk = chan.recv(65536)
                        if not chunk:
                            break
                        text = chunk.decode('utf-8', errors='replace')
                        with session['lock']:
                            session['buffer'] += text
                    elif chan.exit_status_ready() and not chan.recv_ready():
                        break
                    else:
                        time.sleep(0.02)
            except:
                pass
            finally:
                session['closed'] = True

        threading.Thread(target=reader, daemon=True).start()
        return jsonify({'success': True, 'session_id': session_id})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/ssh/read', methods=['POST'])
def ssh_read():
    data = request.json
    session_id = data.get('session_id')
    last_index = int(data.get('last_index', 0))
    session = ssh_sessions.get(session_id)
    if not session:
        return jsonify({'success': False, 'error': 'Invalid session'}), 401
    with session['lock']:
        buf = session['buffer']
        if last_index > len(buf):
            last_index = 0
        new_data = buf[last_index:]
        new_index = len(buf)
        closed = session.get('closed', False)
    return jsonify({'success': True, 'data': new_data, 'last_index': new_index, 'closed': closed})

@app.route('/api/ssh/write', methods=['POST'])
def ssh_write():
    data = request.json
    session = ssh_sessions.get(data.get('session_id'))
    if not session or session['channel'].closed:
        return jsonify({'success': False, 'error': 'Invalid session'}), 401
    session['channel'].send(data.get('data', ''))
    return jsonify({'success': True})

@app.route('/api/ssh/disconnect', methods=['POST'])
def ssh_disconnect():
    session = ssh_sessions.pop(request.json.get('session_id'), None)
    if session:
        try:
            session['ssh'].close()
        except:
            pass
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'Not found'}), 404

# ═══════════════════════════════════════════════════════════════════════════
# DESIGN & EMBEDS UI SYSTEM
# ═══════════════════════════════════════════════════════════════════════════

COLOR_PRIMARY = 0x2c3e50
COLOR_SUCCESS = 0x27ae60
COLOR_ERROR = 0xe74c3c
COLOR_WARNING = 0xf39c12
COLOR_INFO = 0x3498db

def truncate_text(text, max_length=1024):
    if not text:
        return text
    return text if len(text) <= max_length else text[:max_length-3] + "..."

def create_embed(title, description="", color=COLOR_PRIMARY):
    embed = discord.Embed(title=f"🌟 {title}", description=truncate_text(description, 4096), color=color)
    embed.set_thumbnail(url=BOT_THUMBNAIL_URL)
    embed.set_footer(text=f"Made by Hopingboyz • v{BOT_VERSION}", icon_url=BOT_ICON_URL)
    embed.timestamp = datetime.now()
    return embed

def add_field(embed, name, value, inline=False):
    embed.add_field(name=f"➤ {name}", value=truncate_text(value, 1024), inline=inline)
    return embed

def create_success_embed(title, description=""):
    return create_embed(title, description, COLOR_SUCCESS)

def create_error_embed(title, description=""):
    return create_embed(title, description, COLOR_ERROR)

def create_info_embed(title, description=""):
    return create_embed(title, description, COLOR_INFO)

def create_warning_embed(title, description=""):
    return create_embed(title, description, COLOR_WARNING)

def generate_strong_password(length=16):
    charset = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(secrets.choice(charset) for _ in range(length))

def is_admin():
    async def predicate(ctx):
        if str(ctx.author.id) == str(MAIN_ADMIN_ID) or str(ctx.author.id) in admin_data.get("admins", []):
            return True
        raise commands.CheckFailure("You need admin permissions for this command.")
    return commands.check(predicate)

# ═══════════════════════════════════════════════════════════════════════════
# LXC EXECUTION SYSTEM
# ═══════════════════════════════════════════════════════════════════════════

async def execute_lxc(container_name: str, command: str, timeout=120, node_id: Optional[int] = None):
    if node_id is None:
        node_id = find_node_id_for_container(container_name)
    node = get_node(node_id)
    if not node:
        raise Exception(f"Node {node_id} not found")
    
    full_command = f"lxc {command}"
    if node['is_local']:
        try:
            cmd = shlex.split(full_command)
            proc = await asyncio.create_subprocess_exec(*cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            if proc.returncode != 0:
                raise Exception(stderr.decode().strip() or "LXC execution failed")
            return stdout.decode().strip() if stdout else True
        except Exception as e:
            raise Exception(f"LXC Error: {e}")
    else:
        url = f"{node['url']}/api/execute"
        response = requests.post(url, json={"command": full_command}, params={"api_key": node["api_key"]}, timeout=timeout)
        if response.status_code != 200:
            raise Exception(f"Remote error: {response.text}")
        res = response.json()
        if res.get("returncode", 1) != 0:
            raise Exception(res.get("stderr", "Remote command failed"))
        return res.get("stdout", True)

# ═══════════════════════════════════════════════════════════════════════════
# BOT COMMANDS (Ping, Uptime, MyVPS & Admin Controls)
# ═══════════════════════════════════════════════════════════════════════════

@bot.event
async def on_ready():
    logger.info(f'{bot.user} connected successfully!')
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=f"{BOT_NAME} VPS Manager"))
    
    if not hasattr(bot, 'flask_started'):
        threading.Thread(target=lambda: app.run(host='0.0.0.0', port=WEBSSH_PORT, debug=False, use_reloader=False), daemon=True).start()
        bot.flask_started = True
    
    if not any(task.get_name() == 'auto_save_task' for task in asyncio.all_tasks()):
        bot.loop.create_task(auto_save_task())

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    elif isinstance(error, commands.CheckFailure):
        await ctx.send(embed=create_error_embed("Access Denied", str(error)))
    else:
        logger.error(f"Error: {error}")
        await ctx.send(embed=create_error_embed("Error", "An unexpected error occurred."))

@bot.command(name='ping')
async def ping(ctx):
    latency = round(bot.latency * 1000)
    embed = create_success_embed("🏓 Pong!", f"Bot latency is `{latency}ms`.")
    await ctx.send(embed=embed)

@bot.command(name='uptime')
async def uptime(ctx):
    try:
        up = subprocess.run(['uptime', '-p'], capture_output=True, text=True).stdout.strip()
    except:
        up = "Active"
    embed = create_info_embed("Host Uptime", up)
    await ctx.send(embed=embed)

@bot.command(name="myvps")
async def my_vps(ctx):
    user_id = str(ctx.author.id)
    vps_list = vps_data.get(user_id, [])

    if not vps_list:
        embed = create_error_embed("❌ No VPS Found", f"You don’t have any active **{BOT_NAME} VPS**.")
        await ctx.send(embed=embed)
        return

    embed = create_info_embed("🖥️ My VPS Dashboard", f"You have **{len(vps_list)}** active VPS instance(s).")
    for i, vps in enumerate(vps_list, start=1):
        status = "🟢 RUNNING" if vps.get('status') == 'running' and not vps.get('suspended') else "🔴 STOPPED/SUSPENDED"
        embed.add_field(
            name=f"#{i} Container: `{vps['container_name']}`",
            value=f"**Status:** {status}\n**Specs:** RAM: {vps['ram']} | CPU: {vps['cpu']} | Disk: {vps['storage']}\n**OS:** {vps.get('os_version', 'N/A')}",
            inline=False
        )
    await ctx.send(embed=embed)

@bot.command(name='create-vps')
@is_admin()
async def create_vps(ctx, member: discord.Member, container_name: str, ram: str = "2GB", cpu: str = "2", storage: str = "20GB", os_ver: str = "ubuntu:22.04"):
    """Admin command to create a VPS container for a user"""
    user_id = str(member.id)
    node_id = 1
    
    msg = await ctx.send(embed=create_info_embed("⏳ Creating VPS...", f"Deploying container `{container_name}` for {member.mention}..."))
    
    try:
        await execute_lxc(container_name, f"launch {os_ver} {container_name}", timeout=180, node_id=node_id)
        
        # Apply limits
        ram_mb = int(ram.lower().replace('gb', '')) * 1024 if 'gb' in ram.lower() else int(ram.lower().replace('mb', ''))
        await execute_lxc(container_name, f"config set {container_name} limits.memory {ram_mb}MB", node_id=node_id)
        await execute_lxc(container_name, f"config set {container_name} limits.cpu {cpu}", node_id=node_id)
        
        # Start container
        await execute_lxc(container_name, f"start {container_name}", node_id=node_id)
        
        password = generate_strong_password()
        
        # Save to database structure
        vps_entry = {
            "user_id": user_id,
            "node_id": node_id,
            "container_name": container_name,
            "ram": ram,
            "cpu": cpu,
            "storage": storage,
            "config": "Custom",
            "os_version": os_ver,
            "status": "running",
            "suspended": False,
            "whitelisted": False,
            "created_at": datetime.now().isoformat(),
            "shared_with": [],
            "suspension_history": [],
            "expiration_date": (datetime.now() + timedelta(days=DEFAULT_VPS_EXPIRATION_DAYS)).isoformat(),
            "root_password": password
        }
        
        vps_data.setdefault(user_id, []).append(vps_entry)
        save_vps_data_immediate()
        
        success_embed = create_success_embed("✅ VPS Created Successfully!", f"Container **{container_name}** deployed for {member.mention}.")
        add_field(success_embed, "Root Password", f"`{password}`", inline=True)
        add_field(success_embed, "Specs", f"RAM: {ram} | CPU: {cpu} Cores", inline=True)
        await msg.edit(embed=success_embed)
        
    except Exception as e:
        await msg.edit(embed=create_error_embed("Creation Failed", str(e)))

# Run Bot
if __name__ == '__main__':
    if not DISCORD_TOKEN:
        logger.error("DISCORD_TOKEN is missing in environment variables or .env file!")
    else:
        bot.run(DISCORD_TOKEN)
