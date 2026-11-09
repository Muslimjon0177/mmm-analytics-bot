from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_main_menu() -> InlineKeyboardMarkup:
    kb = [
        [
            InlineKeyboardButton(text="📊 Bugungi umumiy hisobot", callback_data="report_today")
        ],
        [
            InlineKeyboardButton(text="🟢 Kelimlar (Kirim)", callback_data="report_kelim"),
            InlineKeyboardButton(text="🔴 Ketimlar (Chiqim)", callback_data="report_ketim")
        ],
        [
            InlineKeyboardButton(text="🟡 Mijozlar qoldig'i (Ostatka)", callback_data="report_ostatka")
        ],
        [
            InlineKeyboardButton(text="📥 Excel yuklab olish (.xlsx)", callback_data="export_excel")
        ],
        [
            InlineKeyboardButton(text="🔄 Yangilash", callback_data="refresh_menu")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_back_button() -> InlineKeyboardMarkup:
    kb = [
        [
            InlineKeyboardButton(text="⬅️ Asosiy menyuga qaytish", callback_data="back_to_main")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)
