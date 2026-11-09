import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import libsql_client
from config import TURSO_DATABASE_URL, TURSO_AUTH_TOKEN, DB_PATH
from currency import get_usd_rate

logger = logging.getLogger(__name__)

def get_client() -> libsql_client.ClientSync:
    """Turso Cloud yoki lokal SQLite fayliga ulanish mijozini qaytaradi"""
    if TURSO_DATABASE_URL:
        # Turso Cloud (libsql:// yoki https://)
        return libsql_client.create_client_sync(
            url=TURSO_DATABASE_URL,
            auth_token=TURSO_AUTH_TOKEN if TURSO_AUTH_TOKEN else None
        )
    else:
        # Lokal SQLite fayli (zaxira va offline rejim)
        clean_path = DB_PATH.replace("\\", "/")
        return libsql_client.create_client_sync(f"file:{clean_path}")

def row_to_dict(cols: tuple, row: tuple) -> Dict[str, Any]:
    """libsql_client qatorini kalit-qiymatli lug'atga o'giradi"""
    return dict(zip(cols, row))

def rows_to_dicts(res: libsql_client.ResultSet) -> List[Dict[str, Any]]:
    """libsql_client natijalarini to'liq lug'atlar ro'yxatiga o'giradi"""
    cols = res.columns
    return [dict(zip(cols, row)) for row in res.rows]

def health_check() -> bool:
    """Ma'lumotlar bazasi aloqasini tekshirish (Health Check)"""
    client = None
    try:
        client = get_client()
        res = client.execute("SELECT 1;")
        return bool(res.rows and res.rows[0][0] == 1)
    except Exception as e:
        logger.error(f"Baza aloqasini tekshirishda xatolik: {e}")
        return False
    finally:
        if client:
            try: client.close()
            except Exception: pass

def init_db():
    """Baza jadvallarini yaratish va yangilash"""
    client = get_client()
    try:
        statements = [
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
            "CREATE INDEX IF NOT EXISTS idx_cust_name ON customers(name);",
            "CREATE INDEX IF NOT EXISTS idx_chat_msg ON records(chat_id, message_id);",
            "CREATE INDEX IF NOT EXISTS idx_date_cat ON records(date_str, category);"
        ]
        client.batch(statements)
        
        # Migratsiyalar: mavjud jadvallarda yetishmayotgan ustunlarni xavfsiz qo'shish
        try:
            info_res = client.execute("PRAGMA table_info(records);")
            existing_cols = {row[1] for row in info_res.rows}
            migrations = []
            if "currency" not in existing_cols:
                migrations.append("ALTER TABLE records ADD COLUMN currency TEXT DEFAULT 'UZS';")
            if "amount_usd" not in existing_cols:
                migrations.append("ALTER TABLE records ADD COLUMN amount_usd REAL;")
            if "exchange_rate" not in existing_cols:
                migrations.append("ALTER TABLE records ADD COLUMN exchange_rate REAL;")
            
            for mig in migrations:
                try:
                    client.execute(mig)
                    logger.info(f"Baza migratsiyasi muvaffaqiyatli bajarildi: {mig}")
                except Exception as m_err:
                    logger.warning(f"Migratsiya ogohlantirishi ({mig}): {m_err}")
        except Exception as mig_err:
            logger.warning(f"Ustunlar migratsiyasida xatolik: {mig_err}")

        logger.info("Ma'lumotlar bazasi jadvallari va indekslari muvaffaqiyatli tekshirildi.")
    except Exception as e:
        logger.error(f"init_db xatoligi: {e}")
        raise
    finally:
        client.close()

def normalize_partner_name(name: str) -> str:
    """Mijoz ismini tozalash va standartlashtirish"""
    if not name:
        return ""
    cleaned = name.strip()
    for suffix in ["ga", "dan", "ning", "ni"]:
        if cleaned.lower().endswith(suffix) and len(cleaned) > len(suffix) + 3:
            cleaned = cleaned[:-len(suffix)].strip()
    return cleaned

def update_customer_ledger(partner_name: str, category: str, amount: float):
    """Mijozlar balansi va qarz daftarini yangilash"""
    if not partner_name or not amount:
        return

    clean_display = normalize_partner_name(partner_name)
    clean_key = clean_display.lower()

    client = get_client()
    try:
        res = client.execute("SELECT id FROM customers WHERE name = ?", [clean_key])
        if not res.rows:
            client.execute(
                "INSERT INTO customers (name, display_name, total_credit, total_paid, current_balance) VALUES (?, ?, 0, 0, 0)",
                [clean_key, clean_display]
            )
            res = client.execute("SELECT id FROM customers WHERE name = ?", [clean_key])

        cust_id = res.rows[0][0]

        if category == "nasiya":
            client.execute("""
                UPDATE customers 
                SET total_credit = total_credit + ?,
                    current_balance = current_balance + ?,
                    last_updated = CURRENT_TIMESTAMP
                WHERE id = ?
            """, [amount, amount, cust_id])
        elif category in ("pul_keldi", "to'lov"):
            client.execute("""
                UPDATE customers 
                SET total_paid = total_paid + ?,
                    current_balance = current_balance - ?,
                    last_updated = CURRENT_TIMESTAMP
                WHERE id = ?
            """, [amount, amount, cust_id])

    except Exception as e:
        logger.error(f"Mijoz balansini yangilashda xatolik ({partner_name}): {e}")
    finally:
        client.close()

def recalculate_customer_balance(partner_name: str):
    """Mijozning haqiqiy yozuvlari asosida qarz balansini qayta aniq hisoblash"""
    if not partner_name:
        return
    clean_display = normalize_partner_name(partner_name)
    clean_key = clean_display.lower()
    client = get_client()
    try:
        res = client.execute("""
            SELECT 
                COALESCE(SUM(CASE WHEN category = 'nasiya' THEN total_amount ELSE 0 END), 0) as total_credit,
                COALESCE(SUM(CASE WHEN category IN ('pul_keldi', 'to\'lov') THEN total_amount ELSE 0 END), 0) as total_paid
            FROM records
            WHERE LOWER(partner_name) = ?
        """, [clean_key])
        
        tot_cred = float(res.rows[0][0]) if res.rows else 0.0
        tot_paid = float(res.rows[0][1]) if res.rows else 0.0
        balance = tot_cred - tot_paid
        
        c_res = client.execute("SELECT id FROM customers WHERE name = ?", [clean_key])
        if c_res.rows:
            client.execute("""
                UPDATE customers 
                SET total_credit = ?, total_paid = ?, current_balance = ?, last_updated = CURRENT_TIMESTAMP
                WHERE name = ?
            """, [tot_cred, tot_paid, balance, clean_key])
        else:
            client.execute("""
                INSERT INTO customers (name, display_name, total_credit, total_paid, current_balance, last_updated)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, [clean_key, clean_display, tot_cred, tot_paid, balance])
            
    except Exception as e:
        logger.error(f"recalculate_customer_balance xatolik: {e}")
    finally:
        client.close()

def delete_records_by_message(chat_id: int, message_id: int) -> List[str]:
    """Tahrirlangan yoki o'chirilgan xabarning eski yozuvlarini o'chirish va ta'sirlangan mijozlarni qaytarish"""
    affected_partners = set()
    client = get_client()
    try:
        res = client.execute("SELECT partner_name FROM records WHERE chat_id = ? AND message_id = ?", [chat_id, message_id])
        for row in res.rows:
            if row[0]:
                affected_partners.add(row[0])
        
        client.execute("DELETE FROM records WHERE chat_id = ? AND message_id = ?", [chat_id, message_id])
        return list(affected_partners)
    except Exception as e:
        logger.error(f"delete_records_by_message xatolik: {e}")
        return []
    finally:
        client.close()

def recalculate_day_summary(target_date: Optional[str] = None) -> Dict[str, Any]:
    """1 kunlik barcha ma'lumotlarni ko'rib chiqish va statistikani to'liq yangilash"""
    if not target_date:
        target_date = datetime.now().strftime("%Y-%m-%d")

    client = get_client()
    try:
        partners_res = client.execute(
            "SELECT DISTINCT partner_name FROM records WHERE date_str = ? AND partner_name IS NOT NULL",
            [target_date]
        )
        for p in partners_res.rows:
            if p[0]:
                recalculate_customer_balance(p[0])
    except Exception as e:
        logger.error(f"recalculate_day_summary xatolik: {e}")
    finally:
        client.close()

    return get_daily_summary(target_date)

def save_record(
    category: str,
    item_name: Optional[str] = None,
    quantity: Optional[float] = None,
    unit: Optional[str] = None,
    price: Optional[float] = None,
    total_amount: Optional[float] = None,
    partner_name: Optional[str] = None,
    currency: str = "UZS",
    amount_usd: Optional[float] = None,
    exchange_rate: Optional[float] = None,
    balance: Optional[float] = None,
    raw_message: str = "",
    sender_name: str = "",
    chat_id: int = 0,
    message_id: int = 0,
    date_str: Optional[str] = None,
    time_str: Optional[str] = None,
) -> int:
    now = datetime.now()
    if not date_str:
        date_str = now.strftime("%Y-%m-%d")
    if not time_str:
        time_str = now.strftime("%H:%M:%S")

    # 1. Narxlardagi 3 ta nol qoidasi (masalan 170 -> 170000)
    if price is not None and 0 < price < 1000:
        price = price * 1000

    # 2. Jami summani hisoblash
    if total_amount is None and price is not None and quantity is not None:
        total_amount = float(price) * float(quantity)
    elif total_amount is not None and 0 < total_amount < 1000 and category in ("naqd", "nasiya"):
        total_amount = total_amount * 1000

    # 3. Dollar kursi bo'yicha hisob-kitob
    if currency == "USD" or (amount_usd is not None and amount_usd > 0):
        if not exchange_rate or exchange_rate <= 0:
            exchange_rate = get_usd_rate()
        if not total_amount and amount_usd:
            total_amount = round(amount_usd * exchange_rate, 2)

    partner_name_cleaned = normalize_partner_name(partner_name) if partner_name else None

    client = get_client()
    try:
        res = client.execute("""
            INSERT INTO records (
                date_str, time_str, category, item_name, quantity, unit,
                price, total_amount, partner_name, currency, amount_usd,
                exchange_rate, balance, raw_message, sender_name, chat_id, message_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            date_str, time_str, category, item_name, quantity, unit,
            price, total_amount, partner_name_cleaned, currency, amount_usd,
            exchange_rate, balance, raw_message, sender_name, chat_id, message_id
        ])
        record_id = res.last_insert_rowid
    finally:
        client.close()

    # Mijoz balansini yangilash
    if partner_name_cleaned and category in ("nasiya", "pul_keldi") and total_amount:
        update_customer_ledger(partner_name_cleaned, category, total_amount)

    return record_id

def get_daily_summary(target_date: Optional[str] = None) -> Dict[str, Any]:
    """Kunlik to'liq tahliliy hisobot"""
    if not target_date:
        target_date = datetime.now().strftime("%Y-%m-%d")

    client = get_client()
    try:
        # Kelim
        r_kelim = client.execute(
            "SELECT COUNT(*), COALESCE(SUM(total_amount), 0), COALESCE(SUM(quantity), 0) FROM records WHERE date_str = ? AND category = 'kelim'",
            [target_date]
        ).rows[0]
        # Naqd
        r_naqd = client.execute(
            "SELECT COUNT(*), COALESCE(SUM(total_amount), 0), COALESCE(SUM(quantity), 0) FROM records WHERE date_str = ? AND category = 'naqd'",
            [target_date]
        ).rows[0]
        # Nasiya
        r_nasiya = client.execute(
            "SELECT COUNT(*), COALESCE(SUM(total_amount), 0), COALESCE(SUM(quantity), 0) FROM records WHERE date_str = ? AND category = 'nasiya'",
            [target_date]
        ).rows[0]
        # Pul keldi
        r_pul = client.execute(
            "SELECT COUNT(*), COALESCE(SUM(total_amount), 0) FROM records WHERE date_str = ? AND category = 'pul_keldi'",
            [target_date]
        ).rows[0]
        # Jami qarzlar
        r_debt = client.execute("SELECT COALESCE(SUM(current_balance), 0) FROM customers WHERE current_balance > 0").rows[0]

        return {
            "date": target_date,
            "kelim": {"count": r_kelim[0], "total_sum": r_kelim[1], "qty": r_kelim[2]},
            "naqd": {"count": r_naqd[0], "total_sum": r_naqd[1], "qty": r_naqd[2]},
            "nasiya": {"count": r_nasiya[0], "total_sum": r_nasiya[1], "qty": r_nasiya[2]},
            "pul_keldi": {"count": r_pul[0], "total_sum": r_pul[1]},
            "total_customer_debts": r_debt[0]
        }
    finally:
        client.close()

def get_advanced_stats(period: str = "7days") -> Dict[str, Any]:
    """Mini App uchun tahliliy statistika va diagrammalar"""
    now = datetime.now()
    if period == "today":
        start_date = now.strftime("%Y-%m-%d")
        days_count = 1
    elif period == "month":
        start_date = (now - timedelta(days=30)).strftime("%Y-%m-%d")
        days_count = 30
    elif period == "all":
        start_date = "2000-01-01"
        days_count = 30
    else:  # 7days
        start_date = (now - timedelta(days=6)).strftime("%Y-%m-%d")
        days_count = 7

    client = get_client()
    try:
        # Asosiy KPI
        kpi_res = client.execute("""
            SELECT 
                COALESCE(SUM(CASE WHEN category = 'naqd' THEN total_amount ELSE 0 END), 0) as total_naqd_sum,
                COUNT(CASE WHEN category = 'naqd' THEN 1 END) as count_naqd,
                COALESCE(SUM(CASE WHEN category = 'nasiya' THEN total_amount ELSE 0 END), 0) as total_nasiya_sum,
                COUNT(CASE WHEN category = 'nasiya' THEN 1 END) as count_nasiya,
                COALESCE(SUM(CASE WHEN category = 'pul_keldi' THEN total_amount ELSE 0 END), 0) as total_paid_sum,
                COUNT(CASE WHEN category = 'pul_keldi' THEN 1 END) as count_paid,
                COALESCE(SUM(CASE WHEN category = 'kelim' THEN total_amount ELSE 0 END), 0) as total_kelim_sum,
                COUNT(CASE WHEN category = 'kelim' THEN 1 END) as count_kelim
            FROM records
            WHERE date_str >= ?
        """, [start_date])
        kpi = row_to_dict(kpi_res.columns, kpi_res.rows[0])
        kpi["total_sales"] = kpi["total_naqd_sum"] + kpi["total_nasiya_sum"]

        # Jami qoldiq qarzlar
        debt_res = client.execute("SELECT COALESCE(SUM(current_balance), 0) FROM customers WHERE current_balance > 0")
        kpi["total_debtors_balance"] = debt_res.rows[0][0]

        # Grafik: Kunlar bo'yicha Naqd vs Nasiya
        date_list = [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days_count - 1, -1, -1)]
        daily_res = client.execute("""
            SELECT 
                date_str,
                COALESCE(SUM(CASE WHEN category = 'naqd' THEN total_amount ELSE 0 END), 0) as naqd_sum,
                COALESCE(SUM(CASE WHEN category = 'nasiya' THEN total_amount ELSE 0 END), 0) as nasiya_sum,
                COALESCE(SUM(CASE WHEN category = 'pul_keldi' THEN total_amount ELSE 0 END), 0) as paid_sum
            FROM records
            WHERE date_str >= ?
            GROUP BY date_str
        """, [start_date])
        daily_data = {row[0]: {"naqd_sum": row[1], "nasiya_sum": row[2], "paid_sum": row[3]} for row in daily_res.rows}

        chart_labels = []
        chart_naqd = []
        chart_nasiya = []
        chart_paid = []

        for d in date_list:
            parts = d.split("-")
            chart_labels.append(f"{parts[1]}.{parts[2]}" if len(parts) == 3 else d)
            row = daily_data.get(d, {})
            chart_naqd.append(row.get("naqd_sum", 0))
            chart_nasiya.append(row.get("nasiya_sum", 0))
            chart_paid.append(row.get("paid_sum", 0))

        # Top qarzdorlar
        debtors_res = client.execute("""
            SELECT display_name as partner_name, current_balance as balance, last_updated as date_str
            FROM customers
            WHERE current_balance > 0
            ORDER BY current_balance DESC
            LIMIT 5
        """)
        top_debtors = rows_to_dicts(debtors_res)

        # Oxirgi yozuvlar
        recent_res = client.execute("SELECT * FROM records ORDER BY id DESC LIMIT 15")
        recent_records = rows_to_dicts(recent_res)

        return {
            "period": period,
            "kpi": kpi,
            "chart": {
                "labels": chart_labels,
                "naqd": chart_naqd,
                "nasiya": chart_nasiya,
                "paid": chart_paid
            },
            "top_debtors": top_debtors,
            "recent_records": recent_records
        }
    finally:
        client.close()

def get_filtered_records(category: Optional[str] = None, search: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    """Filtrlangan va qidirilgan yozuvlar ro'yxati"""
    client = get_client()
    try:
        query = "SELECT * FROM records WHERE 1=1"
        params = []

        if category and category != "all":
            query += " AND category = ?"
            params.append(category)

        if search and search.strip():
            s = f"%{search.strip().lower()}%"
            query += " AND (LOWER(COALESCE(item_name, '')) LIKE ? OR LOWER(COALESCE(partner_name, '')) LIKE ? OR LOWER(COALESCE(raw_message, '')) LIKE ?)"
            params.extend([s, s, s])

        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        res = client.execute(query, params)
        return rows_to_dicts(res)
    finally:
        client.close()

def get_records_by_category(category: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Toifaga ko'ra yozuvlar"""
    return get_filtered_records(category=category, limit=limit)

def get_all_customers(search: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    """Mijozlar bazasi ro'yxati"""
    client = get_client()
    try:
        if search and search.strip():
            s = f"%{search.strip().lower()}%"
            res = client.execute("""
                SELECT * FROM customers 
                WHERE LOWER(display_name) LIKE ? OR LOWER(name) LIKE ?
                ORDER BY current_balance DESC
                LIMIT ?
            """, [s, s, limit])
        else:
            res = client.execute("""
                SELECT * FROM customers 
                ORDER BY current_balance DESC
                LIMIT ?
            """, [limit])
        return rows_to_dicts(res)
    finally:
        client.close()

def get_all_records_for_export(start_date: Optional[str] = None, end_date: Optional[str] = None) -> List[Dict[str, Any]]:
    """Excel hisoboti uchun barcha yozuvlar"""
    client = get_client()
    try:
        if start_date and end_date:
            res = client.execute(
                "SELECT * FROM records WHERE date_str BETWEEN ? AND ? ORDER BY date_str DESC, time_str DESC",
                [start_date, end_date]
            )
        else:
            res = client.execute("SELECT * FROM records ORDER BY date_str DESC, time_str DESC")
        return rows_to_dicts(res)
    finally:
        client.close()
