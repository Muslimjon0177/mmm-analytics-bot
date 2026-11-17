import io
import os
import hmac
import json
import time
import hashlib
import logging
import threading
from collections import defaultdict
from typing import Optional
from urllib.parse import parse_qsl
from datetime import datetime, timedelta, timezone
from flask import Flask, jsonify, request, send_from_directory, send_file, redirect, make_response
import telebot
from config import WEB_APP_PORT, BOT_MODE, WEBHOOK_SECRET, ENVIRONMENT, ADMIN_IDS, BOT_TOKEN
from database import (
    get_advanced_stats,
    get_daily_summary,
    get_filtered_records,
    get_all_customers,
    get_customer_detail,
    save_record,
    delete_record_by_id,
    update_record_by_id,
    get_all_records_for_export,
    get_all_settings,
    set_setting,
    is_module_enabled,
    get_now,
    health_check as db_health_check
)
from ai_parser import answer_business_question, answer_business_audio_question, synthesize_uzbek_speech_b64
from excel_export import create_excel_report
from currency import get_usd_rate

logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder="static")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_SAMESITE="Lax",
)

# Xavfsiz Rate Limiter (har bir IP uchun /api/* ga daqiqasiga 90 ta so'rov)
_RATE_LOCK = threading.Lock()
_RATE_BUCKETS = defaultdict(list)
_RATE_LIMIT = 90
_RATE_WINDOW = 60.0

@app.before_request
def check_api_rate_limit():
    if not request.path.startswith("/api/"):
        return None
    ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "unknown").split(",")[0].strip()
    now = time.time()
    with _RATE_LOCK:
        hits = [ts for ts in _RATE_BUCKETS[ip] if now - ts < _RATE_WINDOW]
        if len(hits) >= _RATE_LIMIT:
            _RATE_BUCKETS[ip] = hits
            return jsonify({"error": "Juda ko'p so'rov yuborildi. Bir daqiqadan so'ng qayta urinib ko'ring."}), 429
        hits.append(now)
        _RATE_BUCKETS[ip] = hits
    return None

_bot_instance: telebot.TeleBot = None

def set_bot_instance(bot: telebot.TeleBot):
    """Telegram bot nusxasini webhook qabul qiluvchi uchun ro'yxatdan o'tkazish"""
    global _bot_instance
    _bot_instance = bot

@app.route("/")
def index():
    """Telegram Mini App asosiy sahifasi"""
    return send_from_directory("static", "index.html")

@app.route("/manifest.json")
def pwa_manifest():
    """PWA Manifest (Chrome / Android ilova sifatida o'rnatish uchun)"""
    return send_from_directory("static", "manifest.json", mimetype="application/manifest+json")

@app.route("/sw.js")
def pwa_service_worker():
    """PWA Service Worker (keshlash va offline barqarorlik)"""
    resp = make_response(send_from_directory("static", "sw.js", mimetype="application/javascript"))
    resp.headers["Service-Worker-Allowed"] = "/"
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp

@app.route("/.well-known/assetlinks.json")
def android_assetlinks():
    """Google Play TWA (Trusted Web Activity) uchun domen tasdiqlash fayli"""
    pkg = os.getenv("ANDROID_PACKAGE_NAME", "uz.barakahisobchi.app").strip()
    fp = os.getenv("ANDROID_SHA256_FINGERPRINT", "").strip()
    if not fp:
        return jsonify([])
    return jsonify([{
        "relation": ["delegate_permission/common.handle_all_urls"],
        "target": {
            "namespace": "android_app",
            "package_name": pkg,
            "sha256_cert_fingerprints": [fp]
        }
    }])

@app.route("/health")
def health():
    """Koyeb / Cloudflare / Uptime monitoring uchun Health Check endpointi"""
    is_db_ok = db_health_check()
    status_code = 200 if is_db_ok else 503
    return jsonify({
        "status": "healthy" if is_db_ok else "unhealthy",
        "database": "connected" if is_db_ok else "disconnected",
        "mode": BOT_MODE,
        "environment": ENVIRONMENT,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }), status_code

@app.route("/webhook", methods=["POST"])
@app.route("/webhook/<secret>", methods=["POST"])
def webhook(secret=None):
    """Telegram Webhook qabul qiluvchi endpoint (qattiq secret tekshiruvi bilan)"""
    if WEBHOOK_SECRET:
        hdr_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        url_ok = bool(secret and hmac.compare_digest(secret, WEBHOOK_SECRET))
        hdr_ok = bool(hdr_secret and hmac.compare_digest(hdr_secret, WEBHOOK_SECRET))
        if not (url_ok or hdr_ok):
            return jsonify({"error": "unauthorized"}), 403

    if not _bot_instance:
        return jsonify({"error": "bot_not_initialized"}), 503

    if request.headers.get("content-type") == "application/json":
        json_string = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(json_string)
        _bot_instance.process_new_updates([update])
        return "ok", 200
    return "unsupported media", 400

INIT_DATA_MAX_AGE = 7 * 24 * 3600  # initData 7 kun amal qiladi

def verify_init_data(init_data: str) -> Optional[dict]:
    """Telegram WebApp initData imzosini (HMAC-SHA256) tekshirish.
    To'g'ri bo'lsa foydalanuvchi ma'lumotini qaytaradi, aks holda None.
    https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app"""
    if not init_data or not BOT_TOKEN:
        return None
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
    except ValueError:
        return None
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        return None
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    calc_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc_hash, received_hash):
        return None
    try:
        auth_date = int(pairs.get("auth_date", "0"))
    except ValueError:
        return None
    if time.time() - auth_date > INIT_DATA_MAX_AGE:
        return None
    try:
        return json.loads(pairs.get("user", "{}"))
    except ValueError:
        return None

def make_app_login_token() -> str:
    """Admin uchun Chrome/PWA ilovasiga kirishning imzolangan kalitini yaratadi"""
    secret = (BOT_TOKEN or "mmm-pwa-secret").encode("utf-8")
    return hmac.new(secret, b"mmm_pwa_admin_v1", hashlib.sha256).hexdigest()[:24]

def verify_app_cookie(req) -> bool:
    tok = req.cookies.get("mmm_admin_session", "")
    if not tok or not BOT_TOKEN:
        return False
    return hmac.compare_digest(tok, make_app_login_token())

def get_request_user(req) -> Optional[dict]:
    init_data = req.headers.get("X-Telegram-Init-Data") or req.args.get("init_data") or ""
    return verify_init_data(init_data)

def is_admin_request(req) -> bool:
    """Admin Telegram imzoli initData YOKI imzolangan HttpOnly PWA cookie orqali aniqlanadi."""
    if verify_app_cookie(req):
        return True
    user = get_request_user(req)
    if not user:
        return False
    try:
        return int(user.get("id", 0)) in ADMIN_IDS
    except (TypeError, ValueError):
        return False

@app.route("/install")
def pwa_install_login():
    """Admin botdan olgan /ilova havolasi orqali brauzerda kirganda xavfsiz HttpOnly cookie o'rnatadi"""
    k = (request.args.get("k") or "").strip()
    if not k or not hmac.compare_digest(k, make_app_login_token()):
        return "Noto'g'ri yoki eskirgan havola.", 403
    resp = make_response(redirect("/"))
    resp.set_cookie(
        "mmm_admin_session",
        make_app_login_token(),
        max_age=30 * 24 * 3600,
        httponly=True,
        secure=(ENVIRONMENT == "production" or request.is_secure),
        samesite="Lax",
    )
    return resp

@app.route("/api/me")
def api_me():
    """Mini App foydalanuvchining rolini serverdan bilib oladi"""
    user = get_request_user(request)
    cookie_ok = verify_app_cookie(request)
    return jsonify({
        "authenticated": bool(user) or cookie_ok,
        "is_admin": is_admin_request(request),
        "first_name": (user or {}).get("first_name") or ("Muslimjon" if cookie_ok else None)
    })

@app.route("/api/stats")
def api_stats():
    """Grafiklar va KPI ko'rsatkichlari (Admin uchun haqiqiy, mehmonlar uchun demo vitrina)"""
    period = request.args.get("period", "7days")
    is_admin = is_admin_request(request)

    if not is_admin:
        # Mehmonlar / Xaridorlar uchun xavfsiz DEMO namuna (biznes sirlari to'liq yopiq)
        demo_data = {
            "is_demo": True,
            "period": period,
            "current_usd_rate": get_usd_rate(),
            "kpi": {
                "total_naqd_sum": 5240000,
                "count_naqd": 6,
                "total_nasiya_sum": 8900000,
                "count_nasiya": 3,
                "total_paid_sum": 4500000,
                "count_paid": 2,
                "total_debtors_balance": 4400000,
                "total_sales": 14140000
            },
            "chart": {
                "labels": ["05.11", "06.11", "07.11", "08.11", "09.11", "10.11", "11.11"],
                "naqd": [800000, 1200000, 950000, 1400000, 0, 0, 890000],
                "nasiya": [1500000, 2200000, 1800000, 3400000, 0, 0, 0],
                "paid": [500000, 1000000, 800000, 2200000, 0, 0, 0]
            },
            "top_debtors": [
                {"partner_name": "Namuna Xaridor 1", "balance": 2500000},
                {"partner_name": "Namuna Do'kon 2", "balance": 1900000}
            ],
            "recent_records": [
                {"category": "naqd", "item_name": "Olma (Namuna)", "quantity": 10, "unit": "yashik", "total_amount": 1700000, "date_str": "Bugun", "time_str": "12:30", "partner_name": None},
                {"category": "nasiya", "item_name": "Nok (Namuna)", "quantity": 15, "unit": "yashik", "total_amount": 2550000, "date_str": "Bugun", "time_str": "11:15", "partner_name": "Namuna Xaridor 1"}
            ]
        }
        return jsonify(demo_data)

    try:
        data = get_advanced_stats(period)
        data["current_usd_rate"] = get_usd_rate()
        data["is_admin"] = True
        return jsonify(data)
    except Exception as e:
        logger.error(f"Statistika olishda xatolik: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/records")
def api_records():
    """Filtrlangan yozuvlar ro'yxati (Faqat admin uchun haqiqiy, begonalarga demo)"""
    if not is_admin_request(request):
        return jsonify({
            "is_demo": True,
            "records": [
                {"id": 1, "category": "naqd", "item_name": "Olma (Namuna)", "quantity": 10, "unit": "yashik", "total_amount": 1700000, "date_str": "Bugun", "time_str": "12:30", "partner_name": None},
                {"id": 2, "category": "nasiya", "item_name": "Nok (Namuna)", "quantity": 15, "unit": "yashik", "total_amount": 2550000, "date_str": "Bugun", "time_str": "11:15", "partner_name": "Namuna Xaridor 1"}
            ],
            "message": "Haqiqiy yozuvlar biznes egasi uchun maxfiy saqlanadi."
        })

    category = request.args.get("category", "").strip()
    search = request.args.get("search", "").strip()
    try:
        limit = min(max(1, int(request.args.get("limit", 100))), 200)
    except (TypeError, ValueError):
        limit = 100

    try:
        valid_cats = ("kelim", "naqd", "nasiya", "pul_keldi", "qaytarish", "rasxod", "uyga", "ostatka")
        records = get_filtered_records(
            category=category if category in valid_cats else None,
            search=search if search else None,
            limit=limit
        )
        return jsonify({"records": records, "is_admin": True})
    except Exception as e:
        logger.error(f"Yozuvlarni olishda xatolik: {e}")
        return jsonify({"error": str(e), "records": []}), 500

@app.route("/api/customers")
def api_customers():
    """Mijozlar bazasi (CRM): Alifbo yoki Qarz bo'yicha saralangan"""
    if not is_admin_request(request):
        return jsonify({
            "is_demo": True,
            "customers": [
                {"id": 1, "name": "namuna_1", "display_name": "Namuna Xaridor 1 (Toshkent)", "total_credit": 5000000, "total_paid": 2500000, "current_balance": 2500000},
                {"id": 2, "name": "namuna_2", "display_name": "Namuna Do'kon 2 (Samarqand)", "total_credit": 3500000, "total_paid": 1600000, "current_balance": 1900000}
            ],
            "message": "Mijozlar bazasi faqat biznes egasiga ko'rinadi. O'z guruhingizga ulash: 777 000 so'm/oy (@fbr_a)"
        })

    search = request.args.get("search", "").strip()
    limit = int(request.args.get("limit", 150))
    order = request.args.get("order", "alphabetical").strip().lower()

    try:
        customers = get_all_customers(search=search if search else None, limit=limit, order_by=order)
        return jsonify({"customers": customers, "is_admin": True})
    except Exception as e:
        logger.error(f"Mijozlarni olishda xatolik: {e}")
        return jsonify({"error": str(e), "customers": []}), 500

@app.route("/api/customer-details")
def api_customer_details():
    """Mijozning to'liq kartochkasi va unga tegishli savdo/to'lovlar tarixi"""
    name = request.args.get("name", "").strip()
    if not name:
        return jsonify({"error": "Mijoz ismi talab qilinadi"}), 400

    if not is_admin_request(request):
        # Mehmonlar uchun namunaviy demo kartochka
        return jsonify({
            "is_demo": True,
            "customer": {
                "name": "namuna",
                "display_name": name,
                "total_credit": 3500000,
                "total_paid": 2000000,
                "current_balance": 1500000
            },
            "records": [
                {
                    "category": "nasiya",
                    "item_name": "Olma (Namuna)",
                    "quantity": 10,
                    "unit": "yashik",
                    "price": 170000,
                    "total_amount": 1700000,
                    "date_str": "Bugun",
                    "time_str": "11:20:15",
                    "raw_message": f"{name} 10ta olma 170dan nasiya"
                },
                {
                    "category": "pul_keldi",
                    "item_name": None,
                    "quantity": None,
                    "unit": None,
                    "price": None,
                    "total_amount": 2000000,
                    "date_str": "Kechagi kun",
                    "time_str": "16:45:00",
                    "raw_message": f"{name} 2 mln pul berdi"
                }
            ],
            "total_records": 2,
            "message": "Haqiqiy mijoz daftari faqat tizim egasi uchun maxfiy saqlanadi."
        })

    try:
        detail = get_customer_detail(name)
        if not detail:
            return jsonify({"error": "Mijoz topilmadi"}), 404
        detail["is_admin"] = True
        return jsonify(detail)
    except Exception as e:
        logger.error(f"Mijoz tafsilotlarini olishda xatolik ({name}): {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    """Modullar va sozlamalar (Feature Toggles)"""
    if not is_admin_request(request):
        return jsonify({"settings": get_all_settings(), "is_admin": False})

    if request.method == "POST":
        payload = request.get_json() or {}
        for k, v in payload.items():
            if isinstance(v, bool):
                v_str = "true" if v else "false"
            else:
                v_str = str(v)
            set_setting(k, v_str)
        return jsonify({"success": True, "settings": get_all_settings()})

    return jsonify({"settings": get_all_settings(), "is_admin": True})

@app.route("/api/import-sheets", methods=["POST"])
def api_import_sheets():
    """Google Sheets dan mijozlar bazasini import/sinxron qilish (faqat admin)"""
    if not is_admin_request(request):
        return jsonify({"error": "Ruxsat etilmagan"}), 403
    payload = request.get_json() or {}
    url = (payload.get("url") or "").strip() or None
    try:
        from sheets_sync import fetch_and_import_google_sheet
        res = fetch_and_import_google_sheet(url)
        status = 200 if res.get("success") else 400
        return jsonify(res), status
    except Exception as e:
        logger.error(f"Google Sheets import xatoligi: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/rate")
def api_rate():
    """Hozirgi dollar kursi"""
    return jsonify({"usd_rate": get_usd_rate()})

@app.route("/api/add-record", methods=["POST"])
def api_add_record():
    """Mini App orqali yozuv kiritish (faqat admin)"""
    if not is_admin_request(request):
        return jsonify({"error": "Ruxsat etilmagan"}), 403

    payload = request.get_json() or {}
    category = payload.get("category", "naqd")
    item_name = payload.get("item_name", "").strip()
    
    qty = payload.get("quantity")
    quantity = float(qty) if qty not in (None, "") else None
    unit = payload.get("unit", "").strip()
    
    pr = payload.get("price")
    price = float(pr) if pr not in (None, "") else None
    
    tot = payload.get("total_amount")
    total_amount = float(tot) if tot not in (None, "") else None
    
    partner_name = payload.get("partner_name", "").strip()
    currency = payload.get("currency", "UZS")
    
    usd_val = payload.get("amount_usd")
    amount_usd = float(usd_val) if usd_val not in (None, "") else None

    try:
        row_id = save_record(
            category=category,
            item_name=item_name or None,
            quantity=quantity,
            unit=unit or None,
            price=price,
            total_amount=total_amount,
            partner_name=partner_name or None,
            currency=currency,
            amount_usd=amount_usd,
            raw_message="Mini App interfeysi orqali kiritildi",
            sender_name="Mini App Admin"
        )
        return jsonify({"success": True, "id": row_id})
    except Exception as e:
        logger.error(f"Yozuv qo'shishda xatolik: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/export-excel")
def api_export_excel():
    """Excel hisobotini yuklab olish (Faqat admin uchun!)"""
    if not is_admin_request(request):
        return jsonify({
            "error": "Ruxsat etilmagan. Excel hisobot faqat tizim egasi uchun ochiq.",
            "contact": "@fbr_a",
            "subscription_price": "777 000 so'm / oyiga"
        }), 403

    try:
        records = get_all_records_for_export()
        buffer = create_excel_report(records)
        filename = f"MMM_Analytics_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

        # Mini App ichida fayl yuklab olish ko'p telefonlarda ishlamaydi,
        # shuning uchun Excel to'g'ridan-to'g'ri adminning Telegram chatiga yuboriladi.
        user = get_request_user(request)
        if request.args.get("via") == "telegram" and _bot_instance and user:
            _bot_instance.send_document(
                int(user["id"]),
                (filename, buffer.getvalue()),
                caption="📊 <b>Excel hisobot</b> (Mini App orqali so'raldi)"
            )
            return jsonify({"success": True, "sent_to_chat": True})

        return send_file(
            buffer,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        logger.error(f"Excel eksportda xatolik: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/privacy")
def privacy_policy():
    """Maxfiylik siyosati (Privacy Policy) sahifasi"""
    html_doc = """<!DOCTYPE html><html lang="uz"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Maxfiylik Siyosati — Baraka Hisobchi</title>
    <style>body{font-family:system-ui,sans-serif;background:#06090F;color:#E2E8F0;max-width:720px;margin:0 auto;padding:24px;line-height:1.6}
    h1,h2{color:#00F2FE}a{color:#00F5A0}.card{background:#0F172A;border:1px solid rgba(255,255,255,0.1);border-radius:14px;padding:18px;margin-top:16px}</style></head>
    <body><h1>🔒 Maxfiylik Siyosati (Privacy Policy)</h1><p><b>Baraka Hisobchi</b> savdo va ombor boshqaruvi tizimi foydalanuvchilarning tijoriy ma'lumotlarini qat'iy maxfiy saqlaydi.</p>
    <div class="card"><h2>1. Yig'iladigan ma'lumotlar</h2><p>Tizim faqat siz ruxsat bergan Telegram guruhidagi savdo, kirim-chiqim, to'lov yozuvlari hamda mijozlar ro'yxatini qayta ishlaydi. Telegram Mini App autentifikatsiyasi kriptografik <code>initData</code> imzosi orqali tekshiriladi va uchinchi shaxslar cookie fayllaridan foydalanmaydi.</p>
    <h2>2. Ma'lumotlarni saqlash va himoya</h2><p>Barcha yozuvlar shifrlangan HTTPS aloqasi orqali bulutli ma'lumotlar bazasida (Turso) saqlanadi va boshqa do'kon yoki uchinchi shaxslarga berilmaydi.</p>
    <h2>3. Foydalanuvchi huquqlari</h2><p>Siz istalgan vaqtda o'z ma'lumotlaringizni Excel formatida yuklab olishingiz yoki to'liq o'chirtirishingiz mumkin. Murojaat uchun: <a href="https://t.me/fbr_a">@fbr_a</a></p></div></body></html>"""
    return html_doc, 200, {"Content-Type": "text/html; charset=utf-8"}

@app.route("/terms")
def terms_of_service():
    """Ommaviy Oferta (Xizmat ko'rsatish shartlari) sahifasi"""
    html_doc = """<!DOCTYPE html><html lang="uz"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Ommaviy Oferta — Baraka Hisobchi</title>
    <style>body{font-family:system-ui,sans-serif;background:#06090F;color:#E2E8F0;max-width:720px;margin:0 auto;padding:24px;line-height:1.6}
    h1,h2{color:#00F2FE}a{color:#00F5A0}.card{background:#0F172A;border:1px solid rgba(255,255,255,0.1);border-radius:14px;padding:18px;margin-top:16px}</style></head>
    <body><h1>📄 Ommaviy Oferta (Foydalanish shartlari)</h1><p>Ushbu hujjat <b>Baraka Hisobchi</b> SaaS platformasidan foydalanish tartibini belgilaydi.</p>
    <div class="card"><h2>1. Xizmat tavsifi</h2><p>Platforma Telegram guruhlaridagi savdo, nasiya, kassa va ombor hisob-kitoblarini avtomatlashtirish hamda Mini App orqali tahlil qilish xizmatini taqdim etadi.</p>
    <h2>2. Obuna va to'lov</h2><p>Xizmat oylik obuna asosida taqdim etiladi. Zaxira nusxalari har kuni avtomatik shakllantiriladi.</p>
    <h2>3. Aloqa</h2><p>Texnik yordam va ulanish masalalari bo'yicha: <a href="https://t.me/fbr_a">@fbr_a</a></p></div></body></html>"""
    return html_doc, 200, {"Content-Type": "text/html; charset=utf-8"}

@app.route("/api/ai-ask", methods=["POST"])
def api_ai_ask():
    """Mini App ichidagi ovozli va matnli AI biznes yordamchi (faqat admin)"""
    if not is_admin_request(request):
        return jsonify({"error": "Ushbu funksiya faqat biznes egasi (admin) uchun."}), 403
    try:
        now = get_now()
        today_str = now.strftime("%Y-%m-%d")
        yest_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        context = {
            "today": get_daily_summary(today_str),
            "yesterday": get_daily_summary(yest_str),
            "stats_7days": (get_advanced_stats("7days") or {}).get("kpi"),
            "stats_30days": (get_advanced_stats("month") or {}).get("kpi"),
            "customers": get_all_customers(order_by="debt")[:60],
            "recent_records": get_filtered_records(limit=20),
        }
        if "audio" in request.files:
            audio_file = request.files["audio"]
            audio_bytes = audio_file.read()
            mime = audio_file.mimetype or "audio/webm"
            try:
                history = json.loads(request.form.get("history") or "[]")
            except Exception:
                history = []
            want_voice = request.form.get("want_voice", "true").lower() == "true"
            ai_res = answer_business_audio_question(audio_bytes, mime, context, history=history)
        else:
            payload = request.get_json(silent=True) or {}
            question = (payload.get("question") or "").strip()
            if not question:
                return jsonify({"error": "Savol kiritilmadi"}), 400
            history = payload.get("history") if isinstance(payload.get("history"), list) else []
            want_voice = bool(payload.get("want_voice", True))
            ai_res = answer_business_question(question, context, history=history)

        action = ai_res.get("action") or "answer"
        rec_id = ai_res.get("record_id")
        mutated = False
        answer = ai_res.get("answer") or ""

        if action == "add_record" and ai_res.get("text"):
            from ai_parser import analyze_message
            from database import get_all_customer_names
            from customer_matcher import resolve_customer_name
            parsed_new = analyze_message(ai_res["text"])
            if parsed_new.get("is_relevant") and parsed_new.get("records"):
                existing = get_all_customer_names()
                for rec in parsed_new["records"]:
                    p_name = rec.get("partner_name")
                    if p_name and rec.get("category") in ("nasiya", "pul_keldi", "qaytarish"):
                        p_name = resolve_customer_name(p_name, existing)["resolved"]
                    save_record(
                        category=rec.get("category", "naqd"),
                        item_name=rec.get("item_name"),
                        quantity=rec.get("quantity"),
                        unit=rec.get("unit"),
                        price=rec.get("price"),
                        total_amount=rec.get("total_amount"),
                        partner_name=p_name,
                        currency=rec.get("currency", "UZS"),
                        amount_usd=rec.get("amount_usd"),
                        raw_message=ai_res["text"],
                        sender_name="AI Assistant",
                        payment_method=rec.get("payment_method", "cash"),
                    )
                mutated = True
                answer = answer or f"✅ Bazaga {len(parsed_new['records'])} ta yozuv qo'shildi va balans yangilandi."
        elif action == "delete_record" and rec_id:
            deleted = delete_record_by_id(int(rec_id))
            if deleted:
                mutated = True
                answer = f"🗑 #{rec_id}-yozuv ({deleted.get('partner_name') or deleted.get('item_name') or deleted.get('category')}) bazadan o'chirildi va balans qayta hisoblandi."
            else:
                answer = f"⚠️ #{rec_id}-yozuv topilmadi."
        elif action == "edit_record" and rec_id and ai_res.get("updates"):
            updated = update_record_by_id(int(rec_id), ai_res["updates"])
            if updated:
                mutated = True
                answer = f"✏️ #{rec_id}-yozuv muvaffaqiyatli tahrirlandi va balans yangilandi."
            else:
                answer = f"⚠️ #{rec_id}-yozuvni tahrirlab bo'lmadi."

        final_answer = answer or "Bajarildi."

        return jsonify({
            "success": True,
            "question": ai_res.get("question") or "",
            "action": action,
            "mutated": mutated,
            "answer": final_answer,
        })
    except Exception as e:
        logger.error(f"AI ask xatoligi: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/ai-tts", methods=["POST"])
def api_ai_tts():
    """Matnni tabiiy o'zbek ovoziga aylantirish (asinxron, chatni qotirmaydi)"""
    if not is_admin_request(request):
        return jsonify({"error": "Ruxsat etilmagan"}), 403
    payload = request.get_json(silent=True) or {}
    text = (payload.get("text") or "").strip()
    if not text:
        return jsonify({"audio_b64": None})
    audio_b64 = synthesize_uzbek_speech_b64(text)
    return jsonify({"audio_b64": audio_b64})

@app.errorhandler(500)
def handle_internal_error(err):
    logger.error(f"Kutilmagan server xatoligi: {err}")
    return jsonify({"error": "Ichki server xatoligi"}), 500

@app.after_request
def add_cache_headers(response):
    if request.path.startswith("/static") or request.path == "/":
        response.headers["Cache-Control"] = "public, max-age=120"
    elif request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    # Xavfsizlik sarlavhalari (Security Headers)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(self), camera=()"
    response.headers["Content-Security-Policy"] = "frame-ancestors 'self' https://web.telegram.org https://*.telegram.org;"
    if ENVIRONMENT == "production" or request.is_secure:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

def run_server(port=WEB_APP_PORT):
    """Flask WSGI serverini ishga tushirish (multi-threaded, tezkor va qotmaydigan)"""
    import werkzeug.serving
    app.logger.setLevel(logging.WARNING)
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)

if __name__ == "__main__":
    run_server()
