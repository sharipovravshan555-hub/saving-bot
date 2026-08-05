import os
import shutil
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0") or 0)

MAX_CONCURRENT_DOWNLOADS = int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "2") or 2)
DOWNLOAD_TIMEOUT = int(os.getenv("DOWNLOAD_TIMEOUT", "900") or 900)
STATE_TTL = int(os.getenv("STATE_TTL", "3600") or 3600)
AUDIT_RETENTION_DAYS = int(os.getenv("AUDIT_RETENTION_DAYS", "90") or 90)
BOT_API_BASE_URL = os.getenv("BOT_API_BASE_URL", "").strip().rstrip("/")
BOT_API_BASE_FILE_URL = os.getenv("BOT_API_BASE_FILE_URL", "").strip().rstrip("/")
BOT_API_LOCAL_MODE = os.getenv("BOT_API_LOCAL_MODE", "0").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
TELEGRAM_UPLOAD_LIMIT_MB = int(
    os.getenv("TELEGRAM_UPLOAD_LIMIT_MB", "2000" if BOT_API_LOCAL_MODE else "50")
)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR)))
TMP_ROOT = BASE_DIR / "tmp"
STATS_FILE = DATA_DIR / "stats.json"
MEDIA_CACHE_FILE = DATA_DIR / "media_cache.json"
AUDIT_DB_FILE = DATA_DIR / "audit.db"
STATE_DB_FILE = DATA_DIR / "state.db"
COOKIES_FILE = Path(os.getenv("COOKIES_FILE", str(BASE_DIR / "cookies.txt")))
POT_SERVER_HOME = Path(
    os.getenv(
        "YTDLP_POT_SERVER_HOME",
        str(BASE_DIR / "vendor" / "bgutil-ytdlp-pot-provider" / "server"),
    )
)
NODE_EXECUTABLE = os.getenv("YTDLP_NODE_EXECUTABLE", shutil.which("node") or "node")

DATA_DIR.mkdir(parents=True, exist_ok=True)
TMP_ROOT.mkdir(exist_ok=True)
