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
    recalculate_customer_balance,
    recalculate_day_summary,
    get_now,
    TASHKENT_TZ
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

CURRENT_WEB_APP_URL = WEB_APP_URL.rstrip('/') if WEB_APP_URL else ""

def is_admin(user_id: int) -> bool:
    if not ADMIN_IDS:
        return True
    return user_id in ADMIN_IDS

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
        admin_webapp_url = f"{CURRENT_WEB_APP_URL}?uid=6656667725"
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
        admin_webapp_url = f"{CURRENT_WEB_APP_URL}?uid=6656667725"
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

        # Telegram xabarining haqiqiy yuborilgan sana va vaqti (Toshkent vaqti UTC+5):
        msg_timestamp = message.date or int(time.time())
        msg_dt = datetime.fromtimestamp(msg_timestamp, tz=timezone.utc).astimezone(TASHKENT_TZ)
        msg_date_str = msg_dt.strftime("%Y-%m-%d")
        msg_time_str = msg_dt.strftime("%H:%M:%S")

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
                message_id=message.message_id,
                date_str=msg_date_str,
                time_str=msg_time_str
            )

        logger.info(f"Guruhdan {len(result['records'])} ta yozuv saqlandi ({sender_name}, vaqt: {msg_time_str}). Guruhga xabar yozilmaydi.")

        # Guruhga yozilmaydi (jim rejim), lekin ADMINGA shaxsiy chatida (lichkada) darhol xabar boradi:
        if ADMIN_IDS:
            summary_lines = []
            for r in result["records"]:
                cat = r.get("category", "")
                if cat == "naqd":
                    cat_badge = "🟢 Naqd"
                elif cat == "nasiya":
                    cat_badge = "🔴 Nasiya"
                elif cat == "pul_keldi":
                    cat_badge = "💰 Pul Keldi"
                else:
                    cat_badge = "📦 Kelim"

                p_str = f"👤 <b>{r.get('partner_name')}</b>: " if r.get('partner_name') else ""
                item_str = f"{r.get('quantity', '')} {r.get('unit', '') or ''} {r.get('item_name', '')}".strip()
                tot_val = format_number(r.get('total_amount'))
                tot_str = f" — <b>{tot_val} so'm</b>" if tot_val else ""
                
                usd_extra = ""
                if r.get('currency') == "USD" and r.get('amount_usd'):
                    usd_extra = f" (${format_number(r.get('amount_usd'))})"

                summary_lines.append(f"{cat_badge}: {p_str}{item_str}{tot_str}{usd_extra}")

            notif_text = (
                f"📥 <b>Guruhdan yangi ma'lumot qabul qilindi:</b>\n"
                f"🕒 <i>Telegram vaqti: {msg_time_str} ({msg_date_str})</i>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                + "\n".join(summary_lines) +
                f"\n━━━━━━━━━━━━━━━━━━━━\n"
                f"✍️ <i>Yozuvchi: {sender_name}</i>\n"
                f"💬 <i>Xabar: \"{text}\"</i>"
            )
            for admin_id in ADMIN_IDS:
                try:
                    bot.send_message(admin_id, notif_text)
                except Exception as notify_err:
                    logger.warning(f"Adminga bildirishnoma yuborishda: {notify_err}")

    except Exception as e:
        logger.error(f"Guruh xabarini tahlil qilishda xatolik: {e}")

# ----------------- GURUHDA TAHRIRLANGAN XABARLAR (EDITED MESSAGES) -----------------

@bot.edited_message_handler(func=lambda m: m.chat.type in ['group', 'supergroup'], content_types=['text', 'photo', 'document'])
def handle_edited_group_message(message):
    text = (message.text or message.caption or "").strip()
    if not text:
        return

    if ALLOWED_GROUP_IDS and message.chat.id not in ALLOWED_GROUP_IDS:
        return

    sender_name = message.from_user.full_name if message.from_user else "Noma'lum"

    try:
        # 1. Eski yozuvlarni topib o'chirish va mijoz balansini to'g'rilash
        affected_partners = delete_records_by_message(message.chat.id, message.message_id)
        for p in affected_partners:
            recalculate_customer_balance(p)

        # 2. Yangi tahrirlangan matnni qayta tahlil qilish
        result = analyze_message(text)
        if not result.get("is_relevant") or not result.get("records"):
            if ADMIN_IDS:
                for admin_id in ADMIN_IDS:
                    try:
                        bot.send_message(
                            admin_id,
                            f"✏️ <b>Guruhdagi xabar tahrirlandi (Savdo bekor qilindi):</b>\n"
                            f"Eski yozuvlar bekor qilindi va mijoz balansi to'g'rilandi.\n"
                            f"Yangi matn: <i>\"{text}\"</i>"
                        )
                    except Exception:
                        pass
            return

        # Telegram tahrirlangan xabarining haqiqiy sana va vaqti (Toshkent vaqti UTC+5):
        msg_timestamp = message.edit_date or message.date or int(time.time())
        msg_dt = datetime.fromtimestamp(msg_timestamp, tz=timezone.utc).astimezone(TASHKENT_TZ)
        msg_date_str = msg_dt.strftime("%Y-%m-%d")
        msg_time_str = msg_dt.strftime("%H:%M:%S")

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
                message_id=message.message_id,
                date_str=msg_date_str,
                time_str=msg_time_str
            )

        logger.info(f"Guruhdagi tahrirlangan xabar qayta ishlandi ({sender_name}, vaqt: {msg_time_str}): {len(result['records'])} ta yozuv yangilandi.")

        if ADMIN_IDS:
            summary_lines = []
            for r in result["records"]:
                cat = r.get("category", "")
                cat_badge = "🟢 Naqd" if cat == "naqd" else ("🔴 Nasiya" if cat == "nasiya" else "💰 Pul Keldi")
                p_str = f"👤 <b>{r.get('partner_name')}</b>: " if r.get('partner_name') else ""
                item_str = f"{r.get('quantity', '')} {r.get('unit', '') or ''} {r.get('item_name', '')}".strip()
                tot_val = format_number(r.get('total_amount'))
                summary_lines.append(f"{cat_badge}: {p_str}{item_str} — <b>{tot_val} so'm</b>")

            edit_notif = (
                f"✏️ <b>Guruhdagi xabar tahrirlandi va hisobot darhol yangilandi:</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                + "\n".join(summary_lines) +
                f"\n━━━━━━━━━━━━━━━━━━━━\n"
                f"✍️ <i>Yozuvchi: {sender_name}</i>\n"
                f"💬 <i>Yangi xabar: \"{text}\"</i>"
            )
            for admin_id in ADMIN_IDS:
                try:
                    bot.send_message(admin_id, edit_notif)
                except Exception:
                    pass

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
            bot.set_webhook(url=webhook_endpoint, allowed_updates=["message", "callback_query"])
            logger.info(f"Telegram Webhook muvaffaqiyatli o'rnatildi: {webhook_endpoint}")
        run_server(port=PORT)

    else:
        logger.info(f"Bot POLLING rejimida ishlamoqda. Port: {PORT}")
        web_thread = threading.Thread(target=lambda: run_server(port=PORT), daemon=True)
        web_thread.start()

        bot.delete_webhook(drop_pending_updates=True)
        bot.infinity_polling(timeout=20, long_polling_timeout=20)

if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, SystemExit):
        logger.info("MMM Analytics Bot to'xtatildi.")
