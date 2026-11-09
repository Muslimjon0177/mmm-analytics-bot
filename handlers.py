import os
import logging
from datetime import datetime
from aiogram import Router, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.enums import ChatType

from config import ADMIN_IDS, ALLOWED_GROUP_IDS, NOTIFY_IN_GROUP
from database import (
    save_record,
    get_daily_summary,
    get_records_by_category,
    get_customer_balances,
    get_all_records_for_export
)
from ai_parser import analyze_message
from keyboards import get_main_menu, get_back_button
from excel_export import create_excel_report

logger = logging.getLogger(__name__)
router = Router()

def format_number(val) -> str:
    if val is None:
        return "-"
    try:
        val_float = float(val)
        if val_float.is_integer():
            return f"{int(val_float):,}".replace(",", " ")
        return f"{val_float:,.2f}".replace(",", " ")
    except Exception:
        return str(val)

def is_admin(user_id: int) -> bool:
    if not ADMIN_IDS:
        return True # Agar admin ko'rsatilmagan bo'lsa, hammaga ruxsat
    return user_id in ADMIN_IDS

# ----------------- GURUH XABARLARINI TUTISH -----------------
@router.message(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def handle_group_message(message: Message):
    text = (message.text or message.caption or "").strip()
    if not text:
        return

    # Guruh ID filteri mavjud bo'lsa tekshiramiz
    if ALLOWED_GROUP_IDS and message.chat.id not in ALLOWED_GROUP_IDS:
        return
    sender_name = message.from_user.full_name if message.from_user else "Noma'lum"

    try:
        result = analyze_message(text)
        if not result.get("is_relevant") or not result.get("records"):
            return

        saved_items = []
        for rec in result["records"]:
            category = rec.get("category", "kelim")
            item_name = rec.get("item_name")
            quantity = rec.get("quantity")
            unit = rec.get("unit")
            price = rec.get("price")
            total_amount = rec.get("total_amount")
            partner_name = rec.get("partner_name")
            balance = rec.get("balance")

            save_record(
                category=category,
                item_name=item_name,
                quantity=quantity,
                unit=unit,
                price=price,
                total_amount=total_amount,
                partner_name=partner_name,
                balance=balance,
                raw_message=text,
                sender_name=sender_name,
                chat_id=message.chat.id,
                message_id=message.message_id
            )

            # Qisqa tavsif yozib borish
            badge = "🟢 Kelim" if category == "kelim" else ("🔴 Ketim" if category == "ketim" else "🟡 Ostatka")
            name_part = item_name or partner_name or "Tovar"
            qty_part = f"{format_number(quantity)} {unit or ''}".strip() if quantity else ""
            saved_items.append(f"{badge}: {name_part} {qty_part}".strip())

        # Guruhga qisqa tasdiqlash xabari (agar yoqilgan bo'lsa)
        if NOTIFY_IN_GROUP and saved_items:
            confirm_text = "✅ <b>Qabul qilindi va bazaga saqlandi:</b>\n" + "\n".join([f"• {i}" for i in saved_items])
            await message.reply(confirm_text, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Xabarni tahlil qilishda xatolik: {e}")

# ----------------- SHAXSIY CHAT (BOT BILAN DIALOG) -----------------

@router.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
async def cmd_start(message: Message):
    if not is_admin(message.from_user.id):
        await message.reply("Kechirasiz, siz ushbu botdan hisobotlarni ko'rish huquqiga ega emassiz.")
        return

    welcome_text = (
        "👋 <b>Assalomu alaykum!</b>\n\n"
        "Men ombor kelim-ketimi va mijozlar qoldig'ini (ostatka) tartibga soluvchi AI agentman.\n\n"
        "Men guruhdagi barcha xabarlarni o'qib, ulardan kerakli ma'lumotlarni saralab olaman "
        "va sizga bu yerda hisobot sifatida taqdim etaman.\n\n"
        "Quyidagi tugmalardan birini tanlang:"
    )
    await message.answer(welcome_text, parse_mode="HTML", reply_markup=get_main_menu())

@router.message(Command("id"), F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP, ChatType.PRIVATE}))
async def cmd_get_id(message: Message):
    """Foydalanuvchi yoki guruh ID sini bilish uchun qulay buyruq"""
    await message.reply(
        f"🆔 Ushbu chat ID raqami: <code>{message.chat.id}</code>\n"
        f"👤 Sizning ID raqamingiz: <code>{message.from_user.id}</code>",
        parse_mode="HTML"
    )

@router.message(Command("hisobot"), F.chat.type == ChatType.PRIVATE)
@router.message(Command("bugun"), F.chat.type == ChatType.PRIVATE)
async def cmd_hisobot(message: Message):
    if not is_admin(message.from_user.id):
        return
    text = generate_today_summary_text()
    await message.answer(text, parse_mode="HTML", reply_markup=get_main_menu())

def generate_today_summary_text() -> str:
    today_str = datetime.now().strftime("%Y-%m-%d")
    data = get_daily_summary(today_str)

    kelim = data["kelim"]
    ketim = data["ketim"]
    ostatka = data["ostatka"]

    text = (
        f"📊 <b>BUGUNGI HISOBOT ({today_str})</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🟢 <b>OMBOR KELIMI (Kirim):</b>\n"
        f"• Yozuvlar soni: <b>{kelim['count']} ta</b>\n"
        f"• Jami tovar miqdori: <b>{format_number(kelim['qty'])}</b>\n"
        f"• Jami summa: <b>{format_number(kelim['total_sum'])} so'm</b>\n\n"
        f"🔴 <b>OMBOR KETIMI (Chiqim):</b>\n"
        f"• Yozuvlar soni: <b>{ketim['count']} ta</b>\n"
        f"• Jami tovar miqdori: <b>{format_number(ketim['qty'])}</b>\n"
        f"• Jami summa: <b>{format_number(ketim['total_sum'])} so'm</b>\n\n"
        f"🟡 <b>MIJOZLAR QOLDIG'I (Ostatka):</b>\n"
        f"• Bugungi yangilanishlar: <b>{ostatka['count']} ta</b>\n"
        f"• Jami qayd etilgan qoldiq: <b>{format_number(ostatka['total_balance'])}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>Batafsil ro'yxatni ko'rish uchun quyidagi tugmalardan foydalaning.</i>"
    )
    return text

# ----------------- CALLBACK TUGMALAR ISHLOVCHILARI -----------------

@router.callback_query(F.data == "report_today")
async def cb_report_today(call: CallbackQuery):
    text = generate_today_summary_text()
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=get_main_menu())
    await call.answer()

@router.callback_query(F.data == "refresh_menu")
@router.callback_query(F.data == "back_to_main")
async def cb_back_to_main(call: CallbackQuery):
    await call.message.edit_text(
        "📋 <b>Asosiy boshqaruv menyusi:</b>\nQuyidagi bo'limlardan birini tanlang:",
        parse_mode="HTML",
        reply_markup=get_main_menu()
    )
    await call.answer()

@router.callback_query(F.data == "report_kelim")
async def cb_report_kelim(call: CallbackQuery):
    records = get_records_by_category("kelim", limit=15)
    if not records:
        text = "🟢 <b>Ombor Kelimi (Kirim):</b>\n\nHozircha ma'lumotlar mavjud emas."
    else:
        text = "🟢 <b>Oxirgi Ombor Kelimlari:</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        for i, r in enumerate(records, 1):
            item = r.get('item_name') or "Tovar"
            qty = f"{format_number(r.get('quantity'))} {r.get('unit') or ''}".strip()
            total = f" ({format_number(r.get('total_amount'))} so'm)" if r.get('total_amount') else ""
            partner = f" | Kimdan: {r.get('partner_name')}" if r.get('partner_name') else ""
            text += f"{i}. <b>{item}</b> - {qty}{total}{partner} <i>({r.get('date_str')} {r.get('time_str')})</i>\n"

    await call.message.edit_text(text, parse_mode="HTML", reply_markup=get_back_button())
    await call.answer()

@router.callback_query(F.data == "report_ketim")
async def cb_report_ketim(call: CallbackQuery):
    records = get_records_by_category("ketim", limit=15)
    if not records:
        text = "🔴 <b>Ombor Ketimi (Chiqim):</b>\n\nHozircha ma'lumotlar mavjud emas."
    else:
        text = "🔴 <b>Oxirgi Ombor Ketimlari:</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        for i, r in enumerate(records, 1):
            item = r.get('item_name') or "Tovar"
            qty = f"{format_number(r.get('quantity'))} {r.get('unit') or ''}".strip()
            total = f" ({format_number(r.get('total_amount'))} so'm)" if r.get('total_amount') else ""
            partner = f" | Kimga: {r.get('partner_name')}" if r.get('partner_name') else ""
            text += f"{i}. <b>{item}</b> - {qty}{total}{partner} <i>({r.get('date_str')} {r.get('time_str')})</i>\n"

    await call.message.edit_text(text, parse_mode="HTML", reply_markup=get_back_button())
    await call.answer()

@router.callback_query(F.data == "report_ostatka")
async def cb_report_ostatka(call: CallbackQuery):
    customers = get_customer_balances(limit=25)
    if not customers:
        text = "🟡 <b>Mijozlar Qoldig'i (Ostatka):</b>\n\nHozircha qoldiqlar qayd etilmagan."
    else:
        text = "🟡 <b>Mijozlar Qoldig'i (Ostatka / Balans):</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        for i, c in enumerate(customers, 1):
            name = c.get('partner_name') or "Noma'lum mijoz"
            bal = format_number(c.get('balance'))
            date_info = f"({c.get('date_str')})"
            text += f"{i}. <b>{name}</b>: <code>{bal}</code> {date_info}\n"

    await call.message.edit_text(text, parse_mode="HTML", reply_markup=get_back_button())
    await call.answer()

@router.callback_query(F.data == "export_excel")
async def cb_export_excel(call: CallbackQuery):
    await call.answer("Fayl tayyorlanmoqda, kuting...")
    records = get_all_records_for_export()
    if not records:
        await call.message.answer("Eksport qilish uchun hech qanday ma'lumot topilmadi.")
        return

    export_dir = os.path.join(os.path.dirname(__file__), "exports")
    os.makedirs(export_dir, exist_ok=True)
    filename = f"Hisobot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    filepath = os.path.join(export_dir, filename)

    try:
        create_excel_report(records, filepath)
        doc = FSInputFile(filepath, filename=filename)
        await call.message.answer_document(
            document=doc,
            caption="📊 <b>Barcha kelim, ketim va ostatka ma'lumotlari jamlangan Excel jadvali.</b>",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Excel yaratishda xatolik: {e}")
        await call.message.answer(f"Excel faylini yaratishda xatolik yuz berdi: {e}")
