import io
import os
import logging
from datetime import datetime, timezone
from flask import Flask, jsonify, request, send_from_directory, send_file
import telebot
from config import WEB_APP_PORT, BOT_MODE, WEBHOOK_SECRET, ENVIRONMENT
from database import (
    get_advanced_stats,
    get_filtered_records,
    get_all_customers,
    save_record,
    get_all_records_for_export,
    health_check as db_health_check
)
from excel_export import create_excel_report
from currency import get_usd_rate

logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder="static")

_bot_instance: telebot.TeleBot = None

def set_bot_instance(bot: telebot.TeleBot):
    """Telegram bot nusxasini webhook qabul qiluvchi uchun ro'yxatdan o'tkazish"""
    global _bot_instance
    _bot_instance = bot

@app.route("/")
def index():
    """Telegram Mini App asosiy sahifasi"""
    return send_from_directory("static", "index.html")

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
    """Telegram Webhook qabul qiluvchi endpoint (serverless & production scale uchun)"""
    if secret and secret != WEBHOOK_SECRET:
        return jsonify({"error": "unauthorized"}), 403

    if not _bot_instance:
        return jsonify({"error": "bot_not_initialized"}), 503

    if request.headers.get("content-type") == "application/json":
        json_string = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(json_string)
        _bot_instance.process_new_updates([update])
        return "ok", 200
    return "unsupported media", 400

@app.route("/api/stats")
def api_stats():
    """Grafiklar va KPI ko'rsatkichlari (Naqd, Nasiya, To'lovlar)"""
    period = request.args.get("period", "7days")
    try:
        data = get_advanced_stats(period)
        data["current_usd_rate"] = get_usd_rate()
        return jsonify(data)
    except Exception as e:
        logger.error(f"Statistika olishda xatolik: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/records")
def api_records():
    """Filtrlangan va qidirilgan yozuvlar ro'yxati (naqd, nasiya, pul_keldi, kelim)"""
    category = request.args.get("category", "").strip()
    search = request.args.get("search", "").strip()
    limit = int(request.args.get("limit", 100))

    try:
        valid_cats = ("kelim", "naqd", "nasiya", "pul_keldi", "ostatka")
        records = get_filtered_records(
            category=category if category in valid_cats else None,
            search=search if search else None,
            limit=limit
        )
        return jsonify({"records": records})
    except Exception as e:
        logger.error(f"Yozuvlarni olishda xatolik: {e}")
        return jsonify({"error": str(e), "records": []}), 500

@app.route("/api/customers")
def api_customers():
    """Mijozlar bazasi (CRM): qarzlar, to'lovlar, qoldiqlar"""
    search = request.args.get("search", "").strip()
    limit = int(request.args.get("limit", 100))

    try:
        customers = get_all_customers(search=search if search else None, limit=limit)
        return jsonify({"customers": customers})
    except Exception as e:
        logger.error(f"Mijozlarni olishda xatolik: {e}")
        return jsonify({"error": str(e), "customers": []}), 500

@app.route("/api/rate")
def api_rate():
    """Hozirgi dollar kursi"""
    return jsonify({"usd_rate": get_usd_rate()})

@app.route("/api/add-record", methods=["POST"])
def api_add_record():
    """Mini App orqali to'g'ridan-to'g'ri yangi yozuv kiritish"""
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
    """Excel hisobotini xotiradan (RAM) to'g'ridan-to'g'ri yuklab olish"""
    try:
        records = get_all_records_for_export()
        buffer = create_excel_report(records)
        filename = f"MMM_Analytics_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        
        return send_file(
            buffer,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        logger.error(f"Excel eksportda xatolik: {e}")
        return jsonify({"error": str(e)}), 500

@app.after_request
def add_cache_headers(response):
    if request.path.startswith("/static") or request.path == "/":
        response.headers["Cache-Control"] = "public, max-age=120"
    elif request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response

def run_server(port=WEB_APP_PORT):
    """Flask WSGI serverini ishga tushirish"""
    import werkzeug.serving
    app.logger.setLevel(logging.WARNING)
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

if __name__ == "__main__":
    run_server()
