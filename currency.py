import time
import json
import logging
import urllib.request

logger = logging.getLogger(__name__)

_cached_rate = 12000.0
_last_fetch_time = 0
CACHE_DURATION = 3600 # 1 soat kesh

def get_usd_rate() -> float:
    """O'zbekiston Markaziy Banki (CBU) orqali rasmiy dollar kursini olish"""
    global _cached_rate, _last_fetch_time

    now = time.time()
    if now - _last_fetch_time < CACHE_DURATION and _cached_rate > 0:
        return _cached_rate

    url = "https://cbu.uz/uz/arkhiv-kursov-valyut/json/"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            usd_item = next((item for item in data if item.get("Ccy") == "USD"), None)
            if usd_item and "Rate" in usd_item:
                rate = float(usd_item["Rate"])
                _cached_rate = rate
                _last_fetch_time = now
                logger.info(f"Yangi dollar kursi yangilandi: 1 USD = {rate} UZS")
                return rate
    except Exception as e:
        logger.warning(f"Dollar kursini CBU dan olishda ogohlantirish: {e}. Zaxira kurs ishlatiladi: {_cached_rate}")

    return _cached_rate
