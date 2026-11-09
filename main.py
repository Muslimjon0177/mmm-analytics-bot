import io
import os
import sys
import logging
import threading
import signal
import atexit
from datetime import datetime
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, MenuButtonWebApp

# Fix UTF-8 stdout encoding for Windows console compatibility
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from config import (
    BOT_TOKEN, ADMIN_IDS, ALLOWED_GROUP_IDS, PROXY_URL,
    WEB_APP_URL, PORT, BOT_MODE, WEBHOOK_SECRET, AUTO_TUNNEL
)
from database import (
    init_db,
    save_record,
    get_daily_summary,
    get_records_by_category,
    get_all_customers,
    get_all_records_for_export
)
from ai_parser import analyze_message
from excel_export import create_excel_report
from webapp import run_server, set_bot_instance
from currency import get_usd_rate

# Structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("mmm_analytics")

if not BOT_TOKEN:
    logger.error("FATAL: BOT_TOKEN environment variable is missing!")
    sys.exit(1)

if PROXY_URL:
    telebot.apihelper.proxy = {'https': PROXY_URL}

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
set_bot_instance(bot)

CURRENT_WEB_APP_URL = WEB_APP_URL

def format_number(val) -> str:
    if val is None:
        return "0"
    try:
        val_float = float(val)
        if val_float.is_integer():
            return f"{int(val_float):,}".replace(",", " ")
        return f"{val_float:,.2f}".replace(",", " ")
    except Exception:
        return str(val)

def is_admin(user_id: int) -> bool:
    if not ADMIN_IDS:
        return True
    return user_id in ADMIN_IDS

def get_main_menu() -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup(row_width=2)
    if CURRENT_WEB_APP_URL:
        markup.add(
            InlineKeyboardButton("🚀 Smart Boshqaruv Paneli (Mini App)", web_app=WebAppInfo(url=CURRENT_WEB_APP_URL))
        )
    markup.add(
        InlineKeyboardButton("📊 Bugungi umumiy hisobot", callback_data="report_today")
    )
    markup.add(
        InlineKeyboardButton("💵 Naqd Savdo", callback_data="report_naqd"),
        InlineKeyboardButton("📑 Nasiya Savdo", callback_data="report_nasiya")
    )
    markup.add(
        InlineKeyboardButton("💰 Pul Keldi (To'lovlar)", callback_data="report_pul"),
        InlineKeyboardButton("👥 Mijozlar Qarzi (CRM)", callback_data="report_customers")
    )
    markup.add(
        InlineKeyboardButton("📥 Excel yuklab olish (.xlsx)", callback_data="export_excel")
    )
    return markup

def get_back_button() -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup()
    if CURRENT_WEB_APP_URL:
        markup.add(
            InlineKeyboardButton("🚀 Mini Appni Ochish", web_app=WebAppInfo(url=CURRENT_WEB_APP_URL))
        )
    markup.add(InlineKeyboardButton("⬅️ Asosiy menyuga qaytish", callback_data="back_to_main"))
    return markup

def generate_today_summary_text() -> str:
    today_str = datetime.now().strftime("%Y-%m-%d")
    data = get_daily_summary(today_str)
    usd_rate = get_usd_rate()

    naqd = data["naqd"]
    nasiya = data["nasiya"]
    pul = data["pul_keldi"]
    debts = data["total_customer_debts"]

    text = (
        f"📊 <b>BUGUNGI HISOBOT ({today_str})</b>\n"
        f"💵 <i>Dollar kursi: 1$ = {format_number(usd_rate)} so'm</i>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💵 <b>NAQD SAVDO:</b>\n"
        f"• Sotuvlar soni: <b>{naqd['count']} ta</b>\n"
        f"• Jami summa: <b>{format_number(naqd['total_sum'])} so'm</b>\n\n"
        f"📑 <b>NASIYA SAVDO (Qarzga):</b>\n"
        f"• Nasiyalar soni: <b>{nasiya['count']} ta</b>\n"
        f"• Jami summa: <b>{format_number(nasiya['total_sum'])} so'm</b>\n\n"
        f"💰 <b>KASSAGA PUL KELDI (To'lovlar):</b>\n"
        f"• To'lovlar soni: <b>{pul['count']} ta</b>\n"
        f"• Jami tushum: <b>{format_number(pul['total_sum'])} so'm</b>\n\n"
        f"👥 <b>MIJOZLARNING JAMI QARZI:</b>\n"
        f"• Qoldiq qarzlar: <b>{format_number(debts)} so'm</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>Batafsil grafiklar va mijozlar kartochkalarini Mini App orqali ko'ring!</i>"
    )
    return text

def generate_naqd_text() -> str:
    records = get_records_by_category("naqd", limit=15)
    if not records:
        return "💵 <b>Naqd Savdo:</b>\n\nHozircha ma'lumotlar mavjud emas."
    text = "💵 <b>Oxirgi Naqd Savdolar:</b>\n━━━━━━━━━━━━━━━━━━━━\n"
    for i, r in enumerate(records, 1):
        item = r.get('item_name') or "Tovar"
        qty = f"{format_number(r.get('quantity'))} {r.get('unit') or ''}".strip()
        total = f"{format_number(r.get('total_amount'))} so'm"
        text += f"{i}. <b>{item}</b> - {qty} ({total}) <i>({r.get('date_str')})</i>\n"
    return text

def generate_nasiya_text() -> str:
    records = get_records_by_category("nasiya", limit=15)
    if not records:
        return "📑 <b>Nasiya Savdo:</b>\n\nHozircha ma'lumotlar mavjud emas."
    text = "📑 <b>Oxirgi Nasiya Savdolar:</b>\n━━━━━━━━━━━━━━━━━━━━\n"
    for i, r in enumerate(records, 1):
        item = r.get('item_name') or "Tovar"
        partner = r.get('partner_name') or "Mijoz"
        qty = f"{format_number(r.get('quantity'))} {r.get('unit') or ''}".strip()
        total = f"{format_number(r.get('total_amount'))} so'm"
        text += f"{i}. 👤 <b>{partner}</b>: {item} - {qty} (<b>{total}</b>) <i>({r.get('date_str')})</i>\n"
    return text

def generate_pul_text() -> str:
    records = get_records_by_category("pul_keldi", limit=15)
    if not records:
        return "💰 <b>Pul Keldi (To'lovlar):</b>\n\nHozircha to'lovlar qayd etilmagan."
    text = "💰 <b>Oxirgi Qabul Qilingan To'lovlar:</b>\n━━━━━━━━━━━━━━━━━━━━\n"
    for i, r in enumerate(records, 1):
        partner = r.get('partner_name') or "Mijoz"
        total = f"{format_number(r.get('total_amount'))} so'm"
        usd_info = f" (${format_number(r.get('amount_usd'))})" if r.get('currency') == "USD" and r.get('amount_usd') else ""
        text += f"{i}. 👤 <b>{partner}</b>: <b>{total}</b>{usd_info} <i>({r.get('date_str')})</i>\n"
    return text

def generate_customers_text() -> str:
    customers = get_all_customers(limit=20)
    if not customers:
        return "👥 <b>Mijozlar Bazasi:</b>\n\nHozircha mijozlar mavjud emas."
    text = "👥 <b>Mijozlar Ro'yxati va Qarz Balansi:</b>\n━━━━━━━━━━━━━━━━━━━━\n"
    for i, c in enumerate(customers, 1):
        name = c.get('display_name') or "Mijoz"
        bal = c.get('current_balance') or 0
        status = f"🔴 Qarz: {format_number(bal)} so'm" if bal > 0 else "🟢 Hisob yopiq"
        text += f"{i}. <b>{name}</b> — {status}\n"
    return text

def send_excel_report(chat_id: int):
    records = get_all_records_for_export()
    if not records:
        bot.send_message(chat_id, "Eksport qilish uchun hali hech qanday ma'lumot yo'q.")
        return

    try:
        # In-memory RAM buffer generation
        buffer = create_excel_report(records)
        filename = f"MMM_Analytics_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        bot.send_document(
            chat_id,
            (filename, buffer.getvalue()),
            caption="📊 <b>Barcha Naqd, Nasiya, To'lovlar va Ombor ma'lumotlari jamlangan Excel jadvali.</b>"
        )
    except Exception as e:
        logger.error(f"Excel yaratishda xatolik: {e}")
        bot.send_message(chat_id, f"Excel faylini yaratishda xatolik yuz berdi: {e}")

# ----------------- GURUH XABARLARI (FAQAT JIMGINA O'QISH VA SAQLASH) -----------------

@bot.message_handler(func=lambda m: m.chat.type in ['group', 'supergroup'], content_types=['text', 'photo', 'document'])
def handle_group_message(message):
    text = (message.text or message.caption or "").strip()
    if not text:
        return

    if ALLOWED_GROUP_IDS and message.chat.id not in ALLOWED_GROUP_IDS:
        return

    sender_name = message.from_user.full_name if message.from_user else "Noma'lum"

    try:
        result = analyze_message(text)
        if not result.get("is_relevant") or not result.get("records"):
            return

        for rec in result["records"]:
            category = rec.get("category", "naqd")
            item_name = rec.get("item_name")
            quantity = rec.get("quantity")
            unit = rec.get("unit")
            price = rec.get("price")
            total_amount = rec.get("total_amount")
            partner_name = rec.get("partner_name")
            currency = rec.get("currency", "UZS")
            amount_usd = rec.get("amount_usd")

            save_record(
                category=category,
                item_name=item_name,
                quantity=quantity,
                unit=unit,
                price=price,
                total_amount=total_amount,
                partner_name=partner_name,
                currency=currency,
                amount_usd=amount_usd,
                raw_message=text,
                sender_name=sender_name,
                chat_id=message.chat.id,
                message_id=message.message_id
            )

        logger.info(f"Guruhdan {len(result['records'])} ta yozuv saqlandi ({sender_name}). Guruhga xabar yozilmaydi.")

    except Exception as e:
        logger.error(f"Guruh xabarini tahlil qilishda xatolik: {e}")

# ----------------- SHAXSIY CHAT (LICHKA) -----------------

@bot.message_handler(commands=['start', 'menu', 'app'], func=lambda m: m.chat.type == 'private')
def cmd_start(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "Kechirasiz, siz ushbu botdan hisobotlarni ko'rish huquqiga ega emassiz.")
        return

    if CURRENT_WEB_APP_URL:
        try:
            bot.set_chat_menu_button(
                chat_id=message.chat.id,
                menu_button=MenuButtonWebApp(type="web_app", text="📊 Smart Panel", web_app=WebAppInfo(url=CURRENT_WEB_APP_URL))
            )
        except Exception as e:
            logger.warning(f"MenuButton sozlashda: {e}")

    welcome_text = (
        "👋 <b>Assalomu alaykum!</b>\n\n"
        "Men <b>MMM Analytics Bot</b> — professional savdo va ombor hisobot tizimiman.\n\n"
        "✨ <b>Asosiy Imkoniyatlar:</b>\n"
        "• 💵 <b>Naqd va 📑 Nasiya</b> savdo alohida hisoblanadi.\n"
        "• 💰 <b>Pul keldi</b> to'lovlari (so'm va dollar) avtomatik qarzdan ayiriladi.\n"
        "• 👥 <b>Mijozlar bazasi (CRM)</b> har bir xaridorning balansini yuritadi.\n"
        "• 📊 <b>Telegram Mini App</b> orqali real-vaqt interaktiv diagrammalar mavjud.\n\n"
        "Quyidagi tugmalardan birini tanlang:"
    )
    bot.send_message(message.chat.id, welcome_text, reply_markup=get_main_menu())

@bot.message_handler(commands=['hisobot', 'bugun'], func=lambda m: m.chat.type == 'private')
def cmd_hisobot(message):
    if not is_admin(message.from_user.id): return
    bot.send_message(message.chat.id, generate_today_summary_text(), reply_markup=get_main_menu())

@bot.message_handler(commands=['naqd'], func=lambda m: m.chat.type == 'private')
def cmd_naqd(message):
    if not is_admin(message.from_user.id): return
    bot.send_message(message.chat.id, generate_naqd_text(), reply_markup=get_back_button())

@bot.message_handler(commands=['nasiya'], func=lambda m: m.chat.type == 'private')
def cmd_nasiya(message):
    if not is_admin(message.from_user.id): return
    bot.send_message(message.chat.id, generate_nasiya_text(), reply_markup=get_back_button())

@bot.message_handler(commands=['pul', 'tolov'], func=lambda m: m.chat.type == 'private')
def cmd_pul(message):
    if not is_admin(message.from_user.id): return
    bot.send_message(message.chat.id, generate_pul_text(), reply_markup=get_back_button())

@bot.message_handler(commands=['mijozlar', 'crm'], func=lambda m: m.chat.type == 'private')
def cmd_customers(message):
    if not is_admin(message.from_user.id): return
    bot.send_message(message.chat.id, generate_customers_text(), reply_markup=get_back_button())

@bot.message_handler(commands=['excel'], func=lambda m: m.chat.type == 'private')
def cmd_excel(message):
    if not is_admin(message.from_user.id): return
    bot.send_message(message.chat.id, "Excel fayli tayyorlanmoqda, kuting...")
    send_excel_report(message.chat.id)

# ----------------- CALLBACK TUGMALAR -----------------

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    chat_id = call.message.chat.id
    message_id = call.message.message_id

    if call.data == "report_today":
        bot.edit_message_text(generate_today_summary_text(), chat_id, message_id, reply_markup=get_main_menu())
        bot.answer_callback_query(call.id)
    elif call.data == "back_to_main":
        bot.edit_message_text(
            "📋 <b>Asosiy boshqaruv menyusi:</b>\nQuyidagi bo'limlardan birini tanlang:",
            chat_id,
            message_id,
            reply_markup=get_main_menu()
        )
        bot.answer_callback_query(call.id)
    elif call.data == "report_naqd":
        bot.edit_message_text(generate_naqd_text(), chat_id, message_id, reply_markup=get_back_button())
        bot.answer_callback_query(call.id)
    elif call.data == "report_nasiya":
        bot.edit_message_text(generate_nasiya_text(), chat_id, message_id, reply_markup=get_back_button())
        bot.answer_callback_query(call.id)
    elif call.data == "report_pul":
        bot.edit_message_text(generate_pul_text(), chat_id, message_id, reply_markup=get_back_button())
        bot.answer_callback_query(call.id)
    elif call.data == "report_customers":
        bot.edit_message_text(generate_customers_text(), chat_id, message_id, reply_markup=get_back_button())
        bot.answer_callback_query(call.id)
    elif call.data == "export_excel":
        bot.answer_callback_query(call.id, "Excel tayyorlanmoqda...")
        send_excel_report(chat_id)

# ----------------- MAIN RUNNER -----------------

def setup_signal_handlers():
    def handle_shutdown(signum, frame):
        logger.info(f"Signal {signum} qabul qilindi. Jarayon xavfsiz to'xtatilmoqda...")
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

def main():
    global CURRENT_WEB_APP_URL
    setup_signal_handlers()

    logger.info("Ma'lumotlar bazasi sxemasi tekshirilmoqda...")
    init_db()

    # Agar AUTO_TUNNEL yoqilgan bo'lsa (faqat lokal Windows rejimida):
    if AUTO_TUNNEL and ("localhost" in CURRENT_WEB_APP_URL or not CURRENT_WEB_APP_URL):
        try:
            from tunnel import start_tunnel, stop_tunnel
            tunnel_url = start_tunnel(port=PORT)
            if tunnel_url:
                CURRENT_WEB_APP_URL = tunnel_url
                logger.info(f"Lokal tunnel tayyor: {CURRENT_WEB_APP_URL}")
                atexit.register(stop_tunnel)
        except Exception as e:
            logger.warning(f"Lokal tunnelni ishga tushirishda ogohlantirish: {e}")

    # Mini App URL adminga bildirish
    if CURRENT_WEB_APP_URL and ADMIN_IDS:
        for admin_id in ADMIN_IDS:
            try:
                bot.set_chat_menu_button(
                    chat_id=admin_id,
                    menu_button=MenuButtonWebApp(type="web_app", text="📊 Smart Panel", web_app=WebAppInfo(url=CURRENT_WEB_APP_URL))
                )
            except Exception as e:
                logger.warning(f"Adminga MenuButton biriktirishda: {e}")

    if BOT_MODE == "webhook":
        logger.info(f"Bot WEBHOOK rejimida ishlamoqda. Webhook URL: {CURRENT_WEB_APP_URL}/webhook/{WEBHOOK_SECRET}")
        if CURRENT_WEB_APP_URL:
            webhook_endpoint = f"{CURRENT_WEB_APP_URL}/webhook/{WEBHOOK_SECRET}"
            bot.set_webhook(url=webhook_endpoint, allowed_updates=["message", "callback_query"])
            logger.info(f"Telegram Webhook muvaffaqiyatli o'rnatildi: {webhook_endpoint}")
        # Webhook rejimida Flask asosiy oqimda ishlaydi
        run_server(port=PORT)

    else:
        logger.info(f"Bot POLLING rejimida ishlamoqda. Port: {PORT}")
        # Polling rejimida Web server fon oqimida (thread) ishlaydi
        web_thread = threading.Thread(target=lambda: run_server(port=PORT), daemon=True)
        web_thread.start()

        bot.delete_webhook(drop_pending_updates=True)
        bot.infinity_polling(timeout=20, long_polling_timeout=20)

if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, SystemExit):
        logger.info("MMM Analytics Bot to'xtatildi.")
