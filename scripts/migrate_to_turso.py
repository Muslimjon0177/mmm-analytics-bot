#!/usr/bin/env python3
"""
MMM Analytics Bot — Turso Cloud Database Migration Script
Safely migrates local SQLite data (records, customers) to a Turso Cloud Database.
"""

import os
import sys
import io
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

# Add project root to path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

import sqlite3
import libsql_client
from config import TURSO_DATABASE_URL, TURSO_AUTH_TOKEN, DB_PATH

def migrate():
    print("=" * 60)
    print("  MMM Analytics Bot — Turso Database Migration Tool")
    print("=" * 60)

    # 1. Manbalarni tekshirish
    if not os.path.exists(DB_PATH):
        print(f"[XATO] Lokal SQLite fayli topilmadi: {DB_PATH}")
        sys.exit(1)

    turso_url = os.getenv("TURSO_DATABASE_URL", TURSO_DATABASE_URL).strip()
    turso_token = os.getenv("TURSO_AUTH_TOKEN", TURSO_AUTH_TOKEN).strip()

    if not turso_url:
        print("[OGOHLANTIRISH] TURSO_DATABASE_URL ko'rsatilmagan!")
        print("Iltimos, .env faylida yoki buyruq satrida Turso ma'lumotlarini kiriting:")
        turso_url = input("Turso Database URL (masalan: libsql://db-name-org.turso.io):\n> ").strip()
        turso_token = input("Turso Auth Token:\n> ").strip()

    if not turso_url:
        print("[XATO] Turso URL kiritilmadi. Migratsiya to'xtatildi.")
        sys.exit(1)

    print(f"\n1. Lokal SQLite bazasiga ulanmoqda: {DB_PATH}")
    local_conn = sqlite3.connect(DB_PATH)
    local_conn.row_factory = sqlite3.Row
    local_cur = local_conn.cursor()

    local_cur.execute("SELECT count(*) FROM records")
    total_local_records = local_cur.fetchone()[0]

    local_cur.execute("SELECT count(*) FROM customers")
    total_local_customers = local_cur.fetchone()[0]

    print(f"   -> Topilgan ma'lumotlar: {total_local_records} ta yozuv, {total_local_customers} ta mijoz.")

    # 2. Turso Cloud bazasiga ulanish
    print(f"\n2. Turso Cloud bazasiga ulanmoqda: {turso_url}")
    try:
        turso_client = libsql_client.create_client_sync(
            url=turso_url,
            auth_token=turso_token if turso_token else None
        )
        turso_client.execute("SELECT 1;")
        print("   -> Turso Cloud bilan aloqa muvaffaqiyatli o'rnatildi! ✅")
    except Exception as e:
        print(f"[XATO] Turso Cloud bazasiga ulanib bo'lmadi: {e}")
        sys.exit(1)

    # 3. Turso'da sxemalarni yaratish
    print("\n3. Turso bazasida sxemalar va indekslarni tekshirish...")
    turso_client.batch([
        """
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            date_str TEXT NOT NULL,
            time_str TEXT NOT NULL,
            category TEXT NOT NULL,
            item_name TEXT,
            quantity REAL,
            unit TEXT,
            price REAL,
            total_amount REAL,
            partner_name TEXT,
            currency TEXT DEFAULT 'UZS',
            amount_usd REAL,
            exchange_rate REAL,
            balance REAL,
            raw_message TEXT,
            sender_name TEXT,
            chat_id INTEGER,
            message_id INTEGER
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            phone TEXT,
            total_credit REAL DEFAULT 0,
            total_paid REAL DEFAULT 0,
            current_balance REAL DEFAULT 0,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_category ON records(category);",
        "CREATE INDEX IF NOT EXISTS idx_date ON records(date_str);",
        "CREATE INDEX IF NOT EXISTS idx_partner ON records(partner_name);",
        "CREATE INDEX IF NOT EXISTS idx_cust_name ON customers(name);"
    ])
    print("   -> Sxemalar tayyor. ✅")

    # 4. Yozuvlarni migratsiya qilish
    print("\n4. Records jadvali ma'lumotlarini o'tkazish...")
    local_cur.execute("SELECT * FROM records ORDER BY id ASC")
    records = local_cur.fetchall()

    migrated_records = 0
    for r in records:
        turso_client.execute("""
            INSERT OR IGNORE INTO records (
                id, created_at, date_str, time_str, category, item_name,
                quantity, unit, price, total_amount, partner_name, currency,
                amount_usd, exchange_rate, balance, raw_message, sender_name,
                chat_id, message_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            r["id"], r["created_at"], r["date_str"], r["time_str"], r["category"],
            r["item_name"], r["quantity"], r["unit"], r["price"], r["total_amount"],
            r["partner_name"], r["currency"] if "currency" in r.keys() else "UZS",
            r["amount_usd"] if "amount_usd" in r.keys() else None,
            r["exchange_rate"] if "exchange_rate" in r.keys() else None,
            r["balance"], r["raw_message"], r["sender_name"],
            r["chat_id"], r["message_id"]
        ])
        migrated_records += 1

    print(f"   -> {migrated_records} ta yozuv Turso bazasiga yuklandi. ✅")

    # 5. Mijozlarni migratsiya qilish
    print("\n5. Customers jadvali ma'lumotlarini o'tkazish...")
    local_cur.execute("SELECT * FROM customers ORDER BY id ASC")
    customers = local_cur.fetchall()

    migrated_cust = 0
    for c in customers:
        turso_client.execute("""
            INSERT OR REPLACE INTO customers (
                id, name, display_name, phone, total_credit, total_paid, current_balance, last_updated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            c["id"], c["name"], c["display_name"], c["phone"],
            c["total_credit"], c["total_paid"], c["current_balance"], c["last_updated"]
        ])
        migrated_cust += 1

    print(f"   -> {migrated_cust} ta mijoz Turso bazasiga yuklandi. ✅")

    # 6. Tekshirish
    turso_count = turso_client.execute("SELECT count(*) FROM records").rows[0][0]
    print("\n" + "=" * 60)
    print("  MIGRATSIYA MUVAFFAQIYATLI YAKUNLANDI! 🎉")
    print(f"  Lokal yozuvlar: {total_local_records}")
    print(f"  Turso yozuvlar: {turso_count}")
    print("=" * 60)

    local_conn.close()
    turso_client.close()

if __name__ == "__main__":
    migrate()
