import io
import os
import sys
import time
import urllib.request
import logging
import threading
import signal
import atexit
from datetime import datetime, timedelta, timezone
from typing import Optional
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, MenuButtonWebApp

# Fix UTF-8 stdout encoding for Windows console compatibility
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from config import (
    BOT_TOKEN, ADMIN_IDS, ALLOWED_GROUP_IDS, PROXY_URL,
    WEB_APP_URL, DEFAULT_RENDER_URL, PORT, BOT_MODE, WEBHOOK_SECRET, AUTO_TUNNEL
)
from database import (
    init_db,
    save_record,
    get_daily_summary,
    get_records_by_category,
    get_all_customers,
    get_all_records_for_export,
    delete_records_by_message,
    get_records_by_message,
    get_message_datetime,
    customer_exists,
    recalculate_customer_balance,
    recalculate_day_summary,
    is_module_enabled,
    get_now,
    TASHKENT_TZ
)
from ai_parser import analyze_message, analyze_audio_message
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

CURRENT_WEB_APP_URL = WEB_APP_URL.rstrip('/') if WEB_APP_URL else ""

def is_admin(user_id: int) -> bool:
    # ADMIN_IDS bo'sh bo'lsa hech kim admin emas (xavfsiz standart)
    return bool(ADMIN_IDS) and user_id in ADMIN_IDS

def format_number(val: Optional[float]) -> str:
    if val is None:
        return "0"
    if isinstance(val, (int, float)):
        if val == int(val):
            return f"{int(val):,}".replace(",", " ")
        return f"{val:,.2f}".replace(",", " ")
    return str(val)

def safe_edit_message_text(text: str, chat_id: int, message_id: int, reply_markup=None):
    """Xabar o'zgarmagan bo'lsa xatolik bermasdan xavfsiz tahrirlash"""
    try:
        bot.edit_message_text(text, chat_id, message_id, reply_markup=reply_markup)
    except telebot.apihelper.ApiTelegramException as e:
        if "message is not modified" not in str(e).lower():
            logger.warning(f"edit_message_text ogohlantirish: {e}")
    except Exception as e:
        logger.warning(f"edit_message_text xatolik: {e}")

def get_main_menu() -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup(row_width=2)
    if CURRENT_WEB_APP_URL:
        admin_webapp_url = CURRENT_WEB_APP_URL
        markup.add(
            InlineKeyboardButton("🚀 Smart Boshqaruv Paneli (Mini App)", web_app=WebAppInfo(url=admin_webapp_url))
        )
    markup.add(
        InlineKeyboardButton("📊 Bugungi hisobot", callback_data="report_today"),
        InlineKeyboardButton("📅 Kechagi hisobot", callback_data="report_yesterday")
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
        InlineKeyboardButton("🔄 1 kunlik hisobotni yangilash", callback_data="refresh_today"),
        InlineKeyboardButton("📥 Excel yuklab olish (.xlsx)", callback_data="export_excel")
    )
    markup.add(
        InlineKeyboardButton("📦 Zaxira nusxa (Backup)", callback_data="make_backup"),
        InlineKeyboardButton("🎧 Texnik Yordam (Support)", callback_data="open_support")
    )
    return markup

def get_guest_menu() -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup(row_width=1)
    if CURRENT_WEB_APP_URL:
        markup.add(
            InlineKeyboardButton("🚀 Mini Appni Ochish (Demo & Imkoniyatlar)", web_app=WebAppInfo(url=CURRENT_WEB_APP_URL))
        )
    markup.add(
        InlineKeyboardButton("⚡ Botni Sotib Olish — 777 000 so'm/oy", url="https://t.me/fbr_a?text=men%20sotib%20olmoqchiman"),
        InlineKeyboardButton("💬 Muallif bilan bog'lanish (@fbr_a)", url="https://t.me/fbr_a")
    )
    return markup

def get_back_button() -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup()
    if CURRENT_WEB_APP_URL:
        admin_webapp_url = CURRENT_WEB_APP_URL
        markup.add(
            InlineKeyboardButton("🚀 Mini Appni Ochish", web_app=WebAppInfo(url=admin_webapp_url))
        )
    markup.add(InlineKeyboardButton("⬅️ Asosiy menyuga qaytish", callback_data="back_to_main"))
    return markup

def generate_today_summary_text(target_date: Optional[str] = None) -> str:
    now_tashkent = get_now()
    if not target_date:
        target_date = now_tashkent.strftime("%Y-%m-%d")
    current_time_str = now_tashkent.strftime("%H:%M:%S")

    data = get_daily_summary(target_date)
    usd_rate = get_usd_rate()

    naqd = data["naqd"]
    nasiya = data["nasiya"]
    pul = data["pul_keldi"]
    debts = data.get("total_customer_debts", 0)
    total_cust = data.get("total_customers_count", 0)
    debtors_cnt = data.get("debtors_count", 0)
    top_debtors = data.get("top_debtors", [])
    latest_active = data.get("latest_active_summary")

    has_today_sales = (naqd['count'] > 0 or nasiya['count'] > 0 or pul['count'] > 0)

    lines = [
        f"📊 <b>KUNLIK HISOBOT ({target_date})</b>",
        f"🕒 <i>Telegram vaqti: {current_time_str} (Toshkent UTC+5)</i>",
        f"💵 <i>Markaziy Bank kursi: 1$ = {format_number(usd_rate)} so'm</i>",
        "━━━━━━━━━━━━━━━━━━━━"
    ]

    if has_today_sales:
        lines.extend([
            f"💵 <b>NAQD SAVDO:</b>",
            f"• Sotuvlar soni: <b>{naqd['count']} ta</b>",
            f"• Jami summa: <b>{format_number(naqd['total_sum'])} so'm</b>\n",
            f"📑 <b>NASIYA SAVDO (Qarzga):</b>",
            f"• Nasiyalar soni: <b>{nasiya['count']} ta</b>",
            f"• Jami summa: <b>{format_number(nasiya['total_sum'])} so'm</b>\n",
            f"💰 <b>KASSAGA PUL KELDI (To'lovlar):</b>",
            f"• To'lovlar soni: <b>{pul['count']} ta</b>",
            f"• Jami tushum: <b>{format_number(pul['total_sum'])} so'm</b>"
        ])
    else:
        lines.append(f"🕒 <i>Bugun ({target_date}) guruhda hali yangi savdo xabari yozilmadi.</i>")
        if latest_active:
            l_date = latest_active.get("date", "")
            lines.extend([
                f"\n📅 <b>OXIRGI FAOL SAVDO KUNI ({l_date}):</b>",
                f"• 💵 Naqd: <b>{latest_active.get('naqd_count', 0)} ta</b> — <b>{format_number(latest_active.get('naqd_sum', 0))} so'm</b>",
                f"• 📑 Nasiya: <b>{latest_active.get('nasiya_count', 0)} ta</b> — <b>{format_number(latest_active.get('nasiya_sum', 0))} so'm</b>",
                f"• 💰 Pul tushumi: <b>{latest_active.get('pul_count', 0)} ta</b> — <b>{format_number(latest_active.get('pul_sum', 0))} so'm</b>"
            ])

    lines.extend([
        "━━━━━━━━━━━━━━━━━━━━",
        f"👥 <b>MIJOZLAR BAZASI VA QARZLAR (CRM):</b>",
        f"• Jami ro'yxatdagi mijozlar: <b>{total_cust} ta</b> (100% saqlangan)",
        f"• Hozirda qarzdor mijozlar: <b>{debtors_cnt} ta</b>",
        f"• Qoldiq umumiy qarz: <b>{format_number(debts)} so'm</b>"
    ])

    if top_debtors:
        lines.append("\n🏆 <b>Eng yirik qarzdorlar:</b>")
        for i, td in enumerate(top_debtors, 1):
            lines.append(f"{i}. <b>{td['name']}</b>: {format_number(td['balance'])} so'm")

    lines.extend([
        "━━━━━━━━━━━━━━━━━━━━",
        "<i>Barcha mijoz kartochkalari va grafiklar Mini Appda!</i>"
    ])

    return "\n".join(lines)

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
    customers = get_all_customers(limit=30)
    if not customers:
        return "👥 <b>Mijozlar Bazasi:</b>\n\nHozircha mijozlar mavjud emas."
    text = "👥 <b>Mijozlar Ro'yxati va Qarz Balansi (CRM):</b>\n━━━━━━━━━━━━━━━━━━━━\n"
    for i, c in enumerate(customers, 1):
        name = c.get('display_name') or "Mijoz"
        bal = c.get('current_balance') or 0
        status = f"🔴 Qarz: <b>{format_number(bal)} so'm</b>" if bal > 0 else "🟢 Hisob yopiq"
        text += f"{i}. <b>{name}</b> — {status}\n"
    return text

def send_excel_report(chat_id: int):
    records = get_all_records_for_export()
    if not records:
        bot.send_message(chat_id, "Eksport qilish uchun hali hech qanday ma'lumot yo'q.")
        return

    try:
        buffer = create_excel_report(records)
        filename = f"MMM_Analytics_{get_now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        bot.send_document(
            chat_id,
            (filename, buffer.getvalue()),
            caption="📊 <b>Barcha Naqd, Nasiya, To'lovlar va Ombor ma'lumotlari jamlangan Excel jadvali.</b>"
        )
    except Exception as e:
        logger.error(f"Excel yaratishda xatolik: {e}")
        bot.send_message(chat_id, f"Excel faylini yaratishda xatolik yuz berdi: {e}")

# ----------------- GURUH XABARLARI (JIM O'QISH, SAQLASH VA ADMINGA TASDIQQA YUBORISH) -----------------

CATEGORY_BADGES = {
    "naqd": "🟢 Naqd",
    "nasiya": "🔴 Nasiya",
    "pul_keldi": "💰 Pul Keldi",
    "kelim": "📦 Kelim",
    "qaytarish": "↩️ Qaytarish",
}

# Tekshiruv talab qiladigan chegaralar
REVIEW_LARGE_AMOUNT = 50_000_000  # 50 mln so'mdan katta summa - shubhali

# Admin "✏️ Tuzatish" ni bosganda keyingi yozgan matni shu xabar uchun tuzatish bo'ladi
PENDING_FIXES = {}  # admin_chat_id -> (group_chat_id, message_id)

def msg_datetime(ts: int):
    dt = datetime.fromtimestamp(ts or int(time.time()), tz=timezone.utc).astimezone(TASHKENT_TZ)
    return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M:%S")

def review_reasons(result: dict) -> list:
    """AI natijasida inson tekshiruvi kerak bo'lgan holatlarni aniqlash"""
    reasons = []
    if result.get("source") == "regex":
        reasons.append("AI ishlamadi, zaxira tahlilchi ishlatildi")
    for r in result.get("records", []):
        tot = r.get("total_amount")
        cat = r.get("category")
        if cat in ("naqd", "nasiya", "pul_keldi", "qaytarish") and not tot and not r.get("amount_usd"):
            reasons.append("summa aniqlanmadi")
        if tot and tot >= REVIEW_LARGE_AMOUNT:
            reasons.append(f"juda katta summa ({format_number(tot)} so'm)")
        p = r.get("partner_name")
        if cat in ("nasiya", "pul_keldi", "qaytarish") and not p:
            reasons.append("mijoz ismi aniqlanmadi")
        elif p and cat in ("nasiya", "pul_keldi", "qaytarish") and not customer_exists(p):
            reasons.append(f"yangi mijoz: «{p}»")
    # takrorlarni olib tashlash
    return list(dict.fromkeys(reasons))

def save_parsed_records(result: dict, text: str, sender_name: str, chat_id: int, message_id: int, date_str: str, time_str: str):
    for rec in result["records"]:
        save_record(
            category=rec.get("category", "naqd"),
            item_name=rec.get("item_name"),
            quantity=rec.get("quantity"),
            unit=rec.get("unit"),
            price=rec.get("price"),
            total_amount=rec.get("total_amount"),
            partner_name=rec.get("partner_name"),
            currency=rec.get("currency", "UZS"),
            amount_usd=rec.get("amount_usd"),
            raw_message=text,
            sender_name=sender_name,
            chat_id=chat_id,
            message_id=message_id,
            date_str=date_str,
            time_str=time_str
        )

def format_saved_lines(chat_id: int, message_id: int) -> list:
    """Bazaga AYNAN qanday saqlanganini ko'rsatadi (AI javobini emas)"""
    lines = []
    for r in get_records_by_message(chat_id, message_id):
        badge = CATEGORY_BADGES.get(r.get("category"), r.get("category"))
        p_str = f"👤 <b>{r.get('partner_name')}</b>: " if r.get("partner_name") else ""
        qty = format_number(r.get("quantity")) if r.get("quantity") else ""
        item_str = f"{qty} {r.get('unit') or ''} {r.get('item_name') or ''}".strip()
        tot_str = f" — <b>{format_number(r.get('total_amount'))} so'm</b>" if r.get("total_amount") else ""
        usd_extra = f" (${format_number(r.get('amount_usd'))})" if r.get("currency") == "USD" and r.get("amount_usd") else ""
        lines.append(f"{badge}: {p_str}{item_str}{tot_str}{usd_extra}")
    return lines

def review_keyboard(chat_id: int, message_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=3)
    kb.add(
        InlineKeyboardButton("✅ To'g'ri", callback_data=f"rv_ok:{chat_id}:{message_id}"),
        InlineKeyboardButton("✏️ Tuzatish", callback_data=f"rv_fix:{chat_id}:{message_id}"),
        InlineKeyboardButton("🗑 Bekor", callback_data=f"rv_del:{chat_id}:{message_id}"),
    )
    return kb

def notify_admins(header: str, chat_id: int, message_id: int, text: str, sender_name: str,
                  date_str: str, time_str: str, reasons: list):
    if not ADMIN_IDS:
        return
    lines = format_saved_lines(chat_id, message_id)
    warn = ""
    if reasons:
        warn = "⚠️ <b>Tekshiring:</b> " + "; ".join(reasons) + "\n"
    body = (
        f"{header}\n"
        f"🕒 <i>Telegram vaqti: {time_str} ({date_str})</i>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        + ("\n".join(lines) if lines else "<i>Yozuv saqlanmadi</i>") +
        f"\n━━━━━━━━━━━━━━━━━━━━\n"
        f"{warn}"
        f"✍️ <i>Yozuvchi: {sender_name}</i>\n"
        f"💬 <i>Xabar: \"{text}\"</i>"
    )
    kb = review_keyboard(chat_id, message_id) if lines else None
    for admin_id in ADMIN_IDS:
        try:
            bot.send_message(admin_id, body, reply_markup=kb)
        except Exception as notify_err:
            logger.warning(f"Adminga bildirishnoma yuborishda: {notify_err}")

def replace_message_records(chat_id: int, message_id: int, new_text: str, sender_name: str,
                            date_str: str, time_str: str) -> dict:
    """Xabarning eski yozuvlarini o'chirib, yangi matn asosida qayta yozadi.
    Mijoz balanslari to'liq qayta hisoblanadi."""
    affected = set(delete_records_by_message(chat_id, message_id))
    result = analyze_message(new_text)
    if result.get("is_relevant") and result.get("records"):
        save_parsed_records(result, new_text, sender_name, chat_id, message_id, date_str, time_str)
        for r in result["records"]:
            if r.get("partner_name"):
                affected.add(r["partner_name"])
    for p in affected:
        recalculate_customer_balance(p)
    return result

def group_allowed(message) -> bool:
    return not ALLOWED_GROUP_IDS or message.chat.id in ALLOWED_GROUP_IDS

@bot.message_handler(func=lambda m: m.chat.type in ['group', 'supergroup'], content_types=['text', 'photo', 'document'])
def handle_group_message(message):
    text = (message.text or message.caption or "").strip()
    if not text or not group_allowed(message):
        return
    sender_name = message.from_user.full_name if message.from_user else "Noma'lum"

    try:
        # Bir xil xabar ikki marta kelsa (qayta ulanishda), takror yozilmasin
        if get_records_by_message(message.chat.id, message.message_id):
            return

        result = analyze_message(text)
        if not result.get("is_relevant") or not result.get("records"):
            return

        date_str, time_str = msg_datetime(message.date)
        reasons = review_reasons(result)  # saqlashdan OLDIN (yangi mijozni aniqlash uchun)
        save_parsed_records(result, text, sender_name, message.chat.id, message.message_id, date_str, time_str)
        logger.info(f"Guruhdan {len(result['records'])} ta yozuv saqlandi ({sender_name}, {date_str} {time_str}).")

        notify_admins("📥 <b>Guruhdan yangi ma'lumot qabul qilindi:</b>",
                      message.chat.id, message.message_id, text, sender_name, date_str, time_str, reasons)
    except Exception as e:
        logger.error(f"Guruh xabarini tahlil qilishda xatolik: {e}")

@bot.message_handler(func=lambda m: m.chat.type in ['group', 'supergroup'], content_types=['voice', 'audio'])
def handle_group_voice_message(message):
    if not group_allowed(message):
        return
    # Agar ovozli modul o'chirilgan bo'lsa, o'tkazib yuboramiz
    if not is_module_enabled("voice"):
        return

    sender_name = message.from_user.full_name if message.from_user else "Noma'lum"

    try:
        if get_records_by_message(message.chat.id, message.message_id):
            return

        file_id = message.voice.file_id if message.voice else message.audio.file_id
        file_info = bot.get_file(file_id)
        audio_bytes = bot.download_file(file_info.file_path)
        mime_type = "audio/ogg" if message.voice else (message.audio.mime_type or "audio/ogg")

        result = analyze_audio_message(audio_bytes, mime_type)
        if not result.get("is_relevant") or not result.get("records"):
            return

        date_str, time_str = msg_datetime(message.date)
        reasons = review_reasons(result)
        reasons.insert(0, "🎙 Ovozli xabar (Audio AI)")

        voice_text = "🎙 [Guruhga yuborilgan ovozli xabar]"
        save_parsed_records(result, voice_text, sender_name, message.chat.id, message.message_id, date_str, time_str)
        logger.info(f"Guruhdan ovozli xabar tahlil qilindi ({sender_name}): {len(result['records'])} ta yozuv saqlandi.")

        notify_admins("🎙 <b>Guruhdan yangi ovozli xabar qabul qilindi:</b>",
                      message.chat.id, message.message_id, voice_text, sender_name, date_str, time_str, reasons)
    except Exception as e:
        logger.error(f"Guruhdagi ovozli xabarni tahlil qilishda xatolik: {e}")

# ----------------- GURUHDA TAHRIRLANGAN XABARLAR (EDITED MESSAGES) -----------------

@bot.edited_message_handler(func=lambda m: m.chat.type in ['group', 'supergroup'], content_types=['text', 'photo', 'document'])
def handle_edited_group_message(message):
    text = (message.text or message.caption or "").strip()
    if not text or not group_allowed(message):
        return
    sender_name = message.from_user.full_name if message.from_user else "Noma'lum"

    try:
        # MUHIM: savdo sanasi xabar YUBORILGAN vaqt bo'lib qoladi (tahrirlangan vaqt emas),
        # aks holda kechagi savdo tahrirlansa bugungi hisobotga o'tib ketardi.
        date_str, time_str = msg_datetime(message.date)

        result = replace_message_records(message.chat.id, message.message_id, text, sender_name, date_str, time_str)

        if not result.get("is_relevant") or not result.get("records"):
            for admin_id in ADMIN_IDS:
                try:
                    bot.send_message(
                        admin_id,
                        f"✏️ <b>Guruhdagi xabar tahrirlandi — savdo bekor qilindi.</b>\n"
                        f"Eski yozuvlar o'chirildi va mijoz balansi qayta hisoblandi.\n"
                        f"Yangi matn: <i>\"{text}\"</i>"
                    )
                except Exception:
                    pass
            return

        logger.info(f"Tahrirlangan xabar qayta ishlandi ({sender_name}): {len(result['records'])} ta yozuv.")
        notify_admins("✏️ <b>Guruhdagi xabar tahrirlandi va hisobot yangilandi:</b>",
                      message.chat.id, message.message_id, text, sender_name, date_str, time_str,
                      review_reasons(result))
    except Exception as e:
        logger.error(f"Tahrirlangan xabarni qayta ishlashda xatolik: {e}")

# ----------------- SHAXSIY BUYRUQLAR (ADMIN VA MEHMONLAR) -----------------

def check_admin_or_reply(message) -> bool:
    if is_admin(message.from_user.id):
        return True
    bot.send_message(
        message.chat.id,
        "🔒 <b>Ushbu hisobot faqat tizim egasi (admin) uchun ochiq.</b>\n\n"
        "O'z biznesingiz yoki guruhingizga ham shunday aqlli bot va Mini App o'rnatmoqchi bo'lsangiz:\n"
        "👑 Narxi: <b>777 000 so'm / oyiga</b>\n\n"
        "Pastdagi tugmalar orqali Mini Appni sinab ko'rishingiz yoki darhol ulanishingiz mumkin:",
        reply_markup=get_guest_menu()
    )
    return False

@bot.message_handler(commands=['start', 'menu', 'app'], func=lambda m: m.chat.type == 'private')
def cmd_start(message):
    user_id = message.from_user.id
    first_name = message.from_user.first_name or "Foydalanuvchi"

    # Har bir foydalanuvchi (admin yoki mehmon) uchun pastki chap MenuButton'ni faollashtirish
    if CURRENT_WEB_APP_URL:
        try:
            bot.set_chat_menu_button(
                chat_id=message.chat.id,
                menu_button=MenuButtonWebApp(type="web_app", text="📊 Smart Panel", web_app=WebAppInfo(url=CURRENT_WEB_APP_URL))
            )
        except Exception:
            pass

    if is_admin(user_id):
        welcome_text = (
            f"Assalomu alaykum, <b>{first_name}</b> (Admin)!\n\n"
            f"🤖 <b>MMM Analytics & Warehouse Bot</b> boshqaruv paneliga xush kelibsiz.\n"
            "Ushbu tizim guruhingizdagi savdolarni 24/7 avtomatlashtirib boradi:\n\n"
            "• 🟢 <b>Naqd savdolar</b> avtomatik jamlanadi.\n"
            "• 🔴 <b>Nasiya savdolar</b> qarz daftariga yoziladi.\n"
            "• 💰 <b>Kassaga pul tushumlari</b> mijoz qarzidan ayirib boriladi.\n"
            "• 👥 <b>Mijozlar bazasi (CRM)</b> barcha mijozlarning balansini yuritadi.\n"
            "• 📊 <b>Telegram Mini App</b> orqali real-vaqt interaktiv diagrammalar mavjud.\n\n"
            "Quyidagi tugmalardan birini tanlang:"
        )
        bot.send_message(message.chat.id, welcome_text, reply_markup=get_main_menu())
    else:
        # Barcha boshqa foydalanuvchilar (mijozlar, xaridorlar, obunachilar) uchun ochiq vitrina:
        guest_text = (
            f"Assalomu alaykum, <b>{first_name}</b>! 🚀\n\n"
            f"🤖 <b>MMM Analytics</b> — Telegram guruhlardagi savdo, ombor va nasiyalarni 24/7 avtomatlashtiruvchi aqlli AI tizim.\n\n"
            "✨ <b>Asosiy Imkoniyatlar:</b>\n"
            "• 🧠 <b>Gemini 2.0 AI</b> bilan xabarlarni avtomatik ajratish (Naqd, Nasiya, To'lov)\n"
            "• 🔕 <b>100% jim guruh rejimi</b> (guruhdagilarni bezovta qilmaydi)\n"
            "• 👥 <b>Avtomatik Nasiya Daftari (CRM)</b> va mijozlar qarz balansi\n"
            "• 📊 <b>Neon Dark interaktiv Mini App</b> mobil boshqaruv paneli\n"
            "• 📥 <b>1-tugma bilan Excel (.xlsx)</b> hisobot eksporti\n\n"
            "👑 <b>O'z guruhingizga ham ulamoqchimisiz?</b>\n"
            "Narxi: <b>oyiga 777 000 so'm</b> (bulutli server va sozlashlar ichida).\n\n"
            "Quyidagi <b>«🚀 Mini Appni Ochish»</b> tugmasi orqali tizimni hoziroq sinab ko'ring:"
        )
        bot.send_message(message.chat.id, guest_text, reply_markup=get_guest_menu())

@bot.message_handler(commands=['hisobot', 'bugun'], func=lambda m: m.chat.type == 'private')
def cmd_hisobot(message):
    if not check_admin_or_reply(message): return
    bot.send_message(message.chat.id, generate_today_summary_text(), reply_markup=get_main_menu())

@bot.message_handler(commands=['naqd'], func=lambda m: m.chat.type == 'private')
def cmd_naqd(message):
    if not check_admin_or_reply(message): return
    bot.send_message(message.chat.id, generate_naqd_text(), reply_markup=get_back_button())

@bot.message_handler(commands=['nasiya'], func=lambda m: m.chat.type == 'private')
def cmd_nasiya(message):
    if not check_admin_or_reply(message): return
    bot.send_message(message.chat.id, generate_nasiya_text(), reply_markup=get_back_button())

@bot.message_handler(commands=['pul', 'tolov'], func=lambda m: m.chat.type == 'private')
def cmd_pul(message):
    if not check_admin_or_reply(message): return
    bot.send_message(message.chat.id, generate_pul_text(), reply_markup=get_back_button())

@bot.message_handler(commands=['mijozlar', 'crm'], func=lambda m: m.chat.type == 'private')
def cmd_customers(message):
    if not check_admin_or_reply(message): return
    bot.send_message(message.chat.id, generate_customers_text(), reply_markup=get_back_button())

@bot.message_handler(commands=['excel'], func=lambda m: m.chat.type == 'private')
def cmd_excel(message):
    if not check_admin_or_reply(message): return
    bot.send_message(message.chat.id, "Excel fayli tayyorlanmoqda, kuting...")
    send_excel_report(message.chat.id)

@bot.message_handler(commands=['yangilash', 'refresh'], func=lambda m: m.chat.type == 'private')
def cmd_refresh(message):
    if not check_admin_or_reply(message): return
    bot.send_message(message.chat.id, "🔄 1 kunlik barcha ma'lumotlar qayta hisoblanmoqda...")
    recalculate_day_summary()
    summary_text = (
        "✅ <b>1 kunlik hisobot va barcha mijozlar balansi yangilandi!</b>\n\n"
        + generate_today_summary_text()
    )
    bot.send_message(message.chat.id, summary_text, reply_markup=get_main_menu())

@bot.message_handler(commands=['support', 'yordam', 'help'], func=lambda m: m.chat.type == 'private')
def cmd_support(message):
    support_text = (
        "🎧 <b>MMM Analytics Qo'llab-quvvatlash Xizmati (Support)</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Savollaringiz, takliflaringiz yoki texnik yordam kerak bo'lsa:\n\n"
        "👤 <b>Aloqa:</b> @fbr_a\n"
        "⚡ <b>Tezkor yordam:</b> 24/7 online\n"
        "💼 <b>Yangi guruhga ulash:</b> 777 000 so'm / oyiga\n\n"
        "Quyidagi havola orqali to'g'ridan-to'g'ri bog'lanishingiz mumkin:"
    )
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("💬 @fbr_a ga yozish", url="https://t.me/fbr_a"))
    if is_admin(message.from_user.id):
        markup.add(InlineKeyboardButton("⬅️ Asosiy menyu", callback_data="back_to_main"))
    bot.send_message(message.chat.id, support_text, reply_markup=markup)

@bot.message_handler(commands=['backup', 'zaxira'], func=lambda m: m.chat.type == 'private')
def cmd_backup(message):
    if not check_admin_or_reply(message): return
    bot.send_message(message.chat.id, "📦 To'liq zaxira nusxasi (Backup) tayyorlanmoqda...")
    send_excel_report(message.chat.id)

@bot.message_handler(commands=['bekor'], func=lambda m: m.chat.type == 'private')
def cmd_cancel_fix(message):
    if message.chat.id in PENDING_FIXES:
        del PENDING_FIXES[message.chat.id]
        bot.send_message(message.chat.id, "❌ Tuzatish bekor qilindi.")
    else:
        bot.send_message(message.chat.id, "Bekor qilinadigan amal yo'q.")

@bot.message_handler(func=lambda m: m.chat.type == 'private' and m.chat.id in PENDING_FIXES, content_types=['text'])
def handle_pending_fix_text(message):
    fix_info = PENDING_FIXES.pop(message.chat.id, None)
    if not fix_info:
        return
    g_chat, g_msg = fix_info
    new_text = message.text.strip()
    if new_text.lower() in ("/bekor", "bekor"):
        bot.send_message(message.chat.id, "❌ Tuzatish bekor qilindi.")
        return

    # Asl xabarning sana va vaqtini saqlab qolamiz
    orig_dt = get_message_datetime(g_chat, g_msg)
    if orig_dt:
        date_str, time_str = orig_dt
    else:
        date_str, time_str = msg_datetime(message.date)

    sender_name = message.from_user.full_name or "Admin"
    result = replace_message_records(g_chat, g_msg, new_text, sender_name, date_str, time_str)

    if result.get("is_relevant") and result.get("records"):
        lines = format_saved_lines(g_chat, g_msg)
        bot.send_message(
            message.chat.id,
            f"✅ <b>Yozuv muvaffaqiyatli tuzatildi!</b>\n"
            f"🕒 <i>Asl sanasi saqlandi: {date_str} • {time_str}</i>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            + "\n".join(lines) +
            f"\n━━━━━━━━━━━━━━━━━━━━\n"
            f"Mijozlar balansi va kunlik hisobot to'g'rilandi."
        )
    else:
        bot.send_message(
            message.chat.id,
            "⚠️ Kiritilgan matndan savdo ma'lumoti topilmadi. Agar bu savdoni butunlay bekor qilmoqchi bo'lsangiz, avvalgi xabardagi «🗑 Bekor» tugmasini bosing."
        )

# ----------------- CALLBACK TUGMALAR -----------------

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    user_id = call.from_user.id

    if not is_admin(user_id):
        bot.answer_callback_query(
            call.id,
            "Ushbu funksiya faqat admin uchun. Botni o'z guruhingizga ulash: @fbr_a (oyiga 777.000 so'm)",
            show_alert=True
        )
        return

    # --- Yozuvni tasdiqlash / tuzatish / bekor qilish ---
    if call.data.startswith(("rv_ok:", "rv_fix:", "rv_del:")):
        try:
            action, g_chat, g_msg = call.data.split(":")
            g_chat, g_msg = int(g_chat), int(g_msg)
        except ValueError:
            bot.answer_callback_query(call.id, "Noto'g'ri tugma")
            return

        if action == "rv_ok":
            try:
                bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
            except Exception:
                pass
            bot.answer_callback_query(call.id, "✅ Tasdiqlandi")
        elif action == "rv_del":
            affected = delete_records_by_message(g_chat, g_msg)
            for p in affected:
                recalculate_customer_balance(p)
            try:
                bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
            except Exception:
                pass
            bot.send_message(chat_id, "🗑 <b>Yozuv bekor qilindi</b> va mijoz balansi qayta hisoblandi.",
                             reply_to_message_id=message_id)
            bot.answer_callback_query(call.id, "Bekor qilindi")
        elif action == "rv_fix":
            PENDING_FIXES[chat_id] = (g_chat, g_msg)
            bot.send_message(
                chat_id,
                "✏️ <b>To'g'ri matnni yozib yuboring</b> — xuddi guruhga yozgandek.\n"
                "Masalan: <code>Ali aka 5 yashik olma 170 dan</code>\n\n"
                "Savdoning asl sanasi va vaqti saqlanib qoladi. Bekor qilish: /bekor",
                reply_to_message_id=message_id
            )
            bot.answer_callback_query(call.id)
        return

    if call.data == "report_today":
        safe_edit_message_text(generate_today_summary_text(), chat_id, message_id, reply_markup=get_main_menu())
        bot.answer_callback_query(call.id)
    elif call.data == "report_yesterday":
        yesterday_str = (get_now() - timedelta(days=1)).strftime("%Y-%m-%d")
        safe_edit_message_text(generate_today_summary_text(yesterday_str), chat_id, message_id, reply_markup=get_back_button())
        bot.answer_callback_query(call.id, f"Kechagi kun hisoboti ({yesterday_str})")
    elif call.data == "refresh_today":
        bot.answer_callback_query(call.id, "🔄 1 kunlik ma'lumotlar yangilanmoqda...")
        recalculate_day_summary()
        summary_text = (
            "✅ <b>Kunlik hisobot va barcha mijozlar balansi muvaffaqiyatli yangilandi!</b>\n\n"
            + generate_today_summary_text()
        )
        safe_edit_message_text(summary_text, chat_id, message_id, reply_markup=get_main_menu())
    elif call.data == "back_to_main":
        safe_edit_message_text(
            "📋 <b>Asosiy boshqaruv menyusi:</b>\nQuyidagi bo'limlardan birini tanlang:",
            chat_id,
            message_id,
            reply_markup=get_main_menu()
        )
        bot.answer_callback_query(call.id)
    elif call.data == "report_naqd":
        safe_edit_message_text(generate_naqd_text(), chat_id, message_id, reply_markup=get_back_button())
        bot.answer_callback_query(call.id)
    elif call.data == "report_nasiya":
        safe_edit_message_text(generate_nasiya_text(), chat_id, message_id, reply_markup=get_back_button())
        bot.answer_callback_query(call.id)
    elif call.data == "report_pul":
        safe_edit_message_text(generate_pul_text(), chat_id, message_id, reply_markup=get_back_button())
        bot.answer_callback_query(call.id)
    elif call.data == "report_customers":
        safe_edit_message_text(generate_customers_text(), chat_id, message_id, reply_markup=get_back_button())
        bot.answer_callback_query(call.id)
    elif call.data == "export_excel":
        bot.answer_callback_query(call.id, "Excel tayyorlanmoqda...")
        send_excel_report(chat_id)
    elif call.data == "make_backup":
        bot.answer_callback_query(call.id, "📦 Zaxira nusxa tayyorlanmoqda...")
        send_excel_report(chat_id)
    elif call.data == "open_support":
        support_text = (
            "🎧 <b>MMM Analytics Qo'llab-quvvatlash Xizmati (Support)</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Savollaringiz, takliflaringiz yoki texnik yordam kerak bo'lsa:\n\n"
            "👤 <b>Aloqa:</b> @fbr_a\n"
            "⚡ <b>Tezkor yordam:</b> 24/7 online\n"
            "💼 <b>Yangi guruhga ulash:</b> 777 000 so'm / oyiga\n\n"
            "Quyidagi havola orqali to'g'ridan-to'g'ri bog'lanishingiz mumkin:"
        )
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("💬 @fbr_a ga yozish", url="https://t.me/fbr_a"))
        markup.add(InlineKeyboardButton("⬅️ Ortga", callback_data="back_to_main"))
        safe_edit_message_text(support_text, chat_id, message_id, reply_markup=markup)
        bot.answer_callback_query(call.id)

# ----------------- MAIN RUNNER -----------------

def keep_alive_worker():
    """Render bepul serverini doimo uyg'oq va issiq saqlash (Anti-sleep keep-alive).
    Har 3 daqiqada (180s) tashqi domenga ping yuborib serverni 24/7 uyg'oq tutamiz!"""
    time.sleep(10)
    target_base = CURRENT_WEB_APP_URL if (CURRENT_WEB_APP_URL and "localhost" not in CURRENT_WEB_APP_URL) else DEFAULT_RENDER_URL
    health_url = f"{target_base.rstrip('/')}/health"
    while True:
        try:
            req = urllib.request.Request(
                health_url,
                headers={"User-Agent": "MMM-Analytics-AntiSleep/2.0"}
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                pass
            logger.info(f"Keep-alive ping muvaffaqiyatli: {health_url}")
        except Exception as e:
            logger.debug(f"Keep-alive ping ogohlantirish ({health_url}): {e}")
        time.sleep(180)  # Har 3 daqiqada (Render 15 daqiqada uxlaydi, 3 daqiqa uni doimo uyg'oq tutadi)

def backup_worker():
    """Har kuni soat 23:00 da (Toshkent vaqti) adminga avtomatik Excel zaxira nusxasini yuborish"""
    time.sleep(30)
    last_backup_date = None
    while True:
        try:
            now_tashkent = get_now()
            today_str = now_tashkent.strftime("%Y-%m-%d")
            # Har kuni kechqurun 23:00 dan keyin 1 marta avtomatik yuboriladi
            if now_tashkent.hour >= 23 and last_backup_date != today_str:
                if ADMIN_IDS:
                    records = get_all_records_for_export()
                    if records:
                        buffer = create_excel_report(records)
                        filename = f"MMM_Backup_{today_str}.xlsx"
                        caption = (
                            f"📦 <b>KUNLIK AVTOMATIK ZAXIRA NUSXASI (BACKUP)</b>\n"
                            f"📅 <i>Sana: {today_str} • {now_tashkent.strftime('%H:%M')}</i>\n"
                            f"Barcha yozuvlar va mijozlar qarz balansi xavfsiz saqlangan."
                        )
                        for admin_id in ADMIN_IDS:
                            try:
                                bot.send_document(admin_id, (filename, buffer.getvalue()), caption=caption)
                            except Exception as be:
                                logger.warning(f"Backup yuborishda: {be}")
                last_backup_date = today_str
        except Exception as e:
            logger.warning(f"backup_worker da xatolik: {e}")
        time.sleep(1800)  # Har 30 daqiqada bir marta tekshiradi

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

    # Render bulut serverini 24/7 uyg'oq tutish (Keep-Alive Anti-Sleep):
    keep_alive_thread = threading.Thread(target=keep_alive_worker, daemon=True)
    keep_alive_thread.start()

    # Har kecha adminga avtomatik zaxira nusxasi (Daily Backup):
    backup_thread = threading.Thread(target=backup_worker, daemon=True)
    backup_thread.start()

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

    # Mini App URL barcha foydalanuvchilar (butun dunyo) uchun pastki chap MenuButton'da ko'rinadigan qilish:
    if CURRENT_WEB_APP_URL:
        try:
            bot.set_chat_menu_button(
                chat_id=None,
                menu_button=MenuButtonWebApp(type="web_app", text="📊 Smart Panel", web_app=WebAppInfo(url=CURRENT_WEB_APP_URL))
            )
            logger.info("Global MenuButton (barcha foydalanuvchilar uchun) muvaffaqiyatli o'rnatildi.")
        except Exception as e:
            logger.warning(f"Global MenuButton o'rnatishda ogohlantirish: {e}")

        if ADMIN_IDS:
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
            bot.set_webhook(url=webhook_endpoint, allowed_updates=["message", "edited_message", "callback_query"])
            logger.info(f"Telegram Webhook muvaffaqiyatli o'rnatildi: {webhook_endpoint}")
        run_server(port=PORT)

    else:
        logger.info(f"Bot POLLING rejimida ishlamoqda. Port: {PORT}")
        web_thread = threading.Thread(target=lambda: run_server(port=PORT), daemon=True)
        web_thread.start()

        bot.delete_webhook(drop_pending_updates=False)  # qayta ishga tushganda kelgan xabarlar YO'QOLMASIN
        bot.infinity_polling(timeout=20, long_polling_timeout=20,
                             allowed_updates=["message", "edited_message", "callback_query"])

if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, SystemExit):
        logger.info("MMM Analytics Bot to'xtatildi.")
