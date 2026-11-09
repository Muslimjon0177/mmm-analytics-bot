import os
from pathlib import Path

env_path = Path(__file__).resolve().parent / ".env"

print("=" * 55)
print("   TELEGRAM OMBOR BOTI - SOZLAMALARNI KIRITISH")
print("=" * 55)
print()

bot_token = input("1. Telegram Bot Tokenini kiriting (BotFather dan olingan):\n> ").strip()
gemini_key = input("\n2. Gemini API kalitini kiriting (aistudio.google.com):\n> ").strip()
admin_id = input("\n3. Sizning Telegram ID raqamingiz (ixtiyoriy, Enter bosish mumkin):\n> ").strip()

content = f"""# Telegram Bot Token (@BotFather dan olinadi)
BOT_TOKEN={bot_token}

# Gemini API kaliti (Google AI Studio - https://aistudio.google.com)
GEMINI_API_KEY={gemini_key}

# Admin Telegram ID raqamingiz
ADMIN_IDS={admin_id}

# Faqat bitta guruhdan o'qish uchun guruh ID raqami (ixtiyoriy)
ALLOWED_GROUP_IDS=

# Guruhda xabar saqlanganda qisqa tasdiq berilsinmi (true / false)
NOTIFY_IN_GROUP=true
"""

with open(env_path, "w", encoding="utf-8") as f:
    f.write(content)

print("\n" + "=" * 55)
print("✅ Sozlamalar muvaffaqiyatli .env fayliga saqlandi!")
print("Endi botni ishga tushirishingiz mumkin: python main.py yoki start_bot.bat")
print("=" * 55)
