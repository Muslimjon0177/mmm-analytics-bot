import os
from pathlib import Path
from dotenv import load_dotenv

# Base directory
BASE_DIR = Path(__file__).resolve().parent

# Load .env file
load_dotenv(BASE_DIR / ".env")

# Telegram Bot Credentials
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# Gemini AI API Key
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

# Admin Telegram IDs (comma-separated list of integers)
raw_admins = os.getenv("ADMIN_IDS", "").strip()
ADMIN_IDS = [int(x.strip()) for x in raw_admins.split(",") if x.strip().isdigit()]

# Allowed Telegram Group IDs (empty means all groups where bot is added)
raw_groups = os.getenv("ALLOWED_GROUP_IDS", "").strip()
ALLOWED_GROUP_IDS = [int(x.strip()) for x in raw_groups.split(",") if x.strip().lstrip("-").isdigit()]

# Whether to reply/notify in group (False = completely silent group recorder)
NOTIFY_IN_GROUP = os.getenv("NOTIFY_IN_GROUP", "false").lower() in ("true", "1", "yes")

# Optional Outbound Proxy (e.g. socks5://... or http://...)
PROXY_URL = os.getenv("PROXY_URL", "").strip()

# Web Server & Mini App Port (Koyeb and cloud PaaS provide $PORT)
PORT = int(os.getenv("PORT", os.getenv("WEB_APP_PORT", "8000")))
WEB_APP_PORT = PORT
WEB_APP_URL = os.getenv("WEB_APP_URL", "").strip()

# Database Configuration (Turso Cloud vs Local SQLite Fallback)
TURSO_DATABASE_URL = os.getenv("TURSO_DATABASE_URL", "").strip()
TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN", "").strip()
DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "warehouse.db")).strip()

# Bot Execution Mode: 'polling' (default) or 'webhook'
BOT_MODE = os.getenv("BOT_MODE", "polling").strip().lower()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "mmm_secret_token_12345").strip()

# Local tunnel toggle (only for local development on Windows if needed)
AUTO_TUNNEL = os.getenv("AUTO_TUNNEL", "false").lower() in ("true", "1", "yes")

# Environment: 'development' | 'production'
ENVIRONMENT = os.getenv("ENVIRONMENT", "production").strip().lower()
