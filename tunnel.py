import os
import re
import time
import logging
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_tunnel_process: Optional[subprocess.Popen] = None
_tunnel_url: Optional[str] = None

def get_cloudflared_path() -> str:
    base_dir = Path(__file__).resolve().parent
    local_path = base_dir / "cloudflared.exe"
    if local_path.exists():
        return str(local_path)
    return "cloudflared"

def start_tunnel(port: int = 5000, timeout: int = 30) -> Optional[str]:
    """Cloudflare Tunnel orqali bepul va tezkor HTTPS manzil yaratish"""
    global _tunnel_process, _tunnel_url

    exe_path = get_cloudflared_path()
    if not os.path.exists(exe_path):
        logger.warning(f"cloudflared.exe topilmadi: {exe_path}")
        return None

    logger.info("Cloudflare Tunnel ishga tushirilmoqda (bepul HTTPS olinmoqda)...")
    try:
        _tunnel_process = subprocess.Popen(
            [exe_path, "tunnel", "--url", f"http://localhost:{port}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )

        start_time = time.time()
        while time.time() - start_time < timeout:
            line = _tunnel_process.stderr.readline()
            if not line:
                time.sleep(0.1)
                continue

            match = re.search(r'https://[a-zA-Z0-9-]+\.trycloudflare\.com', line)
            if match:
                _tunnel_url = match.group(0).strip()
                logger.info(f"✅ Cloudflare HTTPS Tunnel tayyor: {_tunnel_url}")
                return _tunnel_url

        logger.warning("Cloudflare tunnel manzili belgilangan vaqt ichida olinmadi.")
        return None

    except Exception as e:
        logger.error(f"Tunnel ochishda xatolik: {e}")
        return None

def stop_tunnel():
    global _tunnel_process
    if _tunnel_process:
        try:
            _tunnel_process.terminate()
            logger.info("Cloudflare Tunnel to'xtatildi.")
        except Exception:
            pass
        _tunnel_process = None
