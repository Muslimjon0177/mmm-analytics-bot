#!/usr/bin/env python3
"""
MMM Analytics Bot — Tarixiy ma'lumotlarni to'liq tahlil qilish va mijozlar bazasini (CRM) shakllantirish.
"""

import sys
import io
import re
import sqlite3
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from config import DB_PATH
from currency import get_usd_rate
from database import normalize_partner_name

def normalize_database():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    usd_rate = get_usd_rate()
    cur.execute("SELECT * FROM records ORDER BY id ASC")
    records = cur.fetchall()

    updated_count = 0
    customers_data = {}

    for r in records:
        rec_id = r["id"]
        raw = (r["raw_message"] or "").strip()
        lower_raw = raw.lower()
        old_cat = r["category"]
        partner = r["partner_name"]
        item = r["item_name"]
        qty = r["quantity"]
        price = r["price"]
        tot = r["total_amount"] or 0
        currency = r["currency"] if "currency" in r.keys() else "UZS"
        amount_usd = r["amount_usd"] if "amount_usd" in r.keys() else None

        new_cat = old_cat

        if old_cat == "kelim" or "kelim" in lower_raw or "kirdi" in lower_raw or "fura" in lower_raw:
            new_cat = "kelim"
        elif old_cat in ("ostatka", "pul_keldi") or any(k in lower_raw for k in ["berdi", "to'ladi", "toladi", "yopdi", "pul keldi", "pul berdi", "oplata"]):
            new_cat = "pul_keldi"
        elif "nasiya" in lower_raw or partner:
            new_cat = "nasiya"
        elif "naxt" in lower_raw or "naqd" in lower_raw or not partner:
            new_cat = "naqd"

        if price is not None and 0 < price < 1000:
            price = price * 1000

        if tot is not None and 0 < tot < 100000 and new_cat in ("naqd", "nasiya", "kelim"):
            tot = tot * 1000

        if (not tot or tot == 0) and price and qty:
            tot = price * qty

        if "$" in raw or "dollar" in lower_raw:
            currency = "USD"
            usd_match = re.search(r'(\d+[\d\s.,]*)\s*(\$|dollar)', lower_raw)
            if usd_match:
                try:
                    val_str = usd_match.group(1).replace(" ", "").replace(",", "")
                    amount_usd = float(val_str)
                    tot = round(amount_usd * usd_rate, 2)
                except Exception:
                    pass

        clean_display = normalize_partner_name(partner) if partner else None
        if not clean_display and new_cat in ("nasiya", "pul_keldi"):
            words = raw.split()
            potential_name = []
            for w in words:
                if re.match(r'^[A-ZА-ЯЁ][a-zа-яё]+', w):
                    potential_name.append(w)
            if potential_name:
                clean_display = normalize_partner_name(" ".join(potential_name[:3]))

        clean_key = clean_display.lower() if clean_display else None

        cur.execute("""
            UPDATE records 
            SET category = ?, partner_name = ?, price = ?, total_amount = ?, currency = ?, amount_usd = ?
            WHERE id = ?
        """, [new_cat, clean_display, price, tot, currency, amount_usd, rec_id])
        updated_count += 1

        if clean_key and clean_display:
            if clean_key not in customers_data:
                customers_data[clean_key] = {
                    "display": clean_display,
                    "total_credit": 0.0,
                    "total_paid": 0.0
                }
            if new_cat == "nasiya":
                customers_data[clean_key]["total_credit"] += (tot or 0.0)
            elif new_cat == "pul_keldi":
                customers_data[clean_key]["total_paid"] += (tot or 0.0)

    cur.execute("DELETE FROM customers")
    for key, c in customers_data.items():
        balance = c["total_credit"] - c["total_paid"]
        cur.execute("""
            INSERT INTO customers (name, display_name, total_credit, total_paid, current_balance, last_updated)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, [key, c["display"], c["total_credit"], c["total_paid"], balance])

    conn.commit()
    conn.close()
    print("Normalizatsiya muvaffaqiyatli yakunlandi!")

if __name__ == "__main__":
    normalize_database()
