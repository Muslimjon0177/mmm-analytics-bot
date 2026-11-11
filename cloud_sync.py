import os
import sys
import time
import base64
import json
import logging
import threading
import urllib.request
import urllib.error
from pathlib import Path

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "warehouse.db"))
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
GITHUB_REPO = os.getenv("GITHUB_REPO", "Muslimjon0177/mmm-analytics-bot").strip()
BRANCH = "data"

_last_sync_time = 0
_sync_lock = threading.Lock()

def download_db_from_cloud():
    """Bot ishga tushganda oxirgi bazani GitHub 'data' tarmog'idan avtomatik yuklab olish"""
    token = os.getenv("GITHUB_TOKEN", GITHUB_TOKEN).strip()
    if not token or not GITHUB_REPO:
        return

    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/warehouse.db?ref={BRANCH}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "MMM-Analytics-CloudSync"
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            content_b64 = data.get("content", "")
            if content_b64:
                file_bytes = base64.b64decode(content_b64)
                if len(file_bytes) > 1024:
                    with open(DB_PATH, "wb") as f:
                        f.write(file_bytes)
                    logger.info(f"✅ Baza bulutdan (GitHub {BRANCH}) muvaffaqiyatli tiklandi ({len(file_bytes)} bayt).")
    except urllib.error.HTTPError as e:
        logger.warning(f"Bulutdan bazani yuklashda HTTP ogohlantirish ({e.code}): {e}")
    except Exception as e:
        logger.warning(f"Bulutdan bazani yuklashda xatolik: {e}")

def _do_upload():
    global _last_sync_time
    token = os.getenv("GITHUB_TOKEN", GITHUB_TOKEN).strip()
    with _sync_lock:
        if not token or not GITHUB_REPO or not os.path.exists(DB_PATH):
            return

        try:
            with open(DB_PATH, "rb") as f:
                file_bytes = f.read()

            b64_content = base64.b64encode(file_bytes).decode("utf-8")

            url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/warehouse.db?ref={BRANCH}"
            req_get = urllib.request.Request(
                url,
                headers={
                    "Authorization": f"token {token}",
                    "Accept": "application/vnd.github.v3+json",
                    "User-Agent": "MMM-Analytics-CloudSync"
                }
            )
            sha = None
            try:
                with urllib.request.urlopen(req_get, timeout=10) as resp:
                    cur_data = json.loads(resp.read().decode("utf-8"))
                    sha = cur_data.get("sha")
            except urllib.error.HTTPError as he:
                if he.code != 404:
                    logger.warning(f"SHA olishda xatolik: {he}")
                    return

            put_payload = {
                "message": f"Auto-sync database update [{time.strftime('%Y-%m-%d %H:%M:%S')}]",
                "content": b64_content,
                "branch": BRANCH
            }
            if sha:
                put_payload["sha"] = sha

            put_data = json.dumps(put_payload).encode("utf-8")
            put_req = urllib.request.Request(
                url,
                data=put_data,
                headers={
                    "Authorization": f"token {token}",
                    "Content-Type": "application/json",
                    "Accept": "application/vnd.github.v3+json",
                    "User-Agent": "MMM-Analytics-CloudSync"
                },
                method="PUT"
            )

            with urllib.request.urlopen(put_req, timeout=15) as put_resp:
                if put_resp.status in (200, 201):
                    logger.info("✅ Baza bulutga (GitHub data) muvaffaqiyatli saqlandi. Ma'lumotlar abadiy xavfsiz!")
                    _last_sync_time = time.time()

        except Exception as e:
            logger.warning(f"Bulutga bazani saqlashda ogohlantirish: {e}")

def trigger_cloud_sync_async():
    """Fon oqimida (asinxron) bazani bulutga yuklash"""
    t = threading.Thread(target=_do_upload, daemon=True)
    t.start()
