import logging
import re
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
import libsql_client
from config import TURSO_DATABASE_URL, TURSO_AUTH_TOKEN, DB_PATH
from currency import get_usd_rate

logger = logging.getLogger(__name__)

# Toshkent vaqt mintaqasi (UTC+5)
TASHKENT_TZ = timezone(timedelta(hours=5))

def get_now() -> datetime:
    """Toshkent vaqti (UTC+5)"""
    return datetime.now(TASHKENT_TZ)

try:
    from cloud_sync import download_db_from_cloud, trigger_cloud_sync_async
except Exception:
    def download_db_from_cloud(): pass
    def trigger_cloud_sync_async(): pass

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

def normalize_partner_name(name: str) -> str:
    """Mijoz ismini tozalash va standartlashtirish"""
    if not name:
        return ""
    cleaned = name.strip()
    for suffix in ["ga", "dan", "ning", "ni"]:
        if cleaned.lower().endswith(suffix) and len(cleaned) > len(suffix) + 3:
            cleaned = cleaned[:-len(suffix)].strip()
    return cleaned

def rebuild_all_customers(client=None):
    """Barcha yozuvlardan mijozlar balansi va qarz daftarini to'liq qayta hisoblash"""
    should_close = False
    if client is None:
        client = get_client()
        should_close = True
    try:
        res = client.execute("""
            SELECT partner_name, category, total_amount, currency, amount_usd 
            FROM records 
            WHERE partner_name IS NOT NULL AND TRIM(partner_name) != ''
        """)
        cust_map = {}
        for row in res.rows:
            p_name = row[0]
            cat = row[1]
            tot = float(row[2]) if row[2] else 0.0
            
            clean_display = normalize_partner_name(p_name)
            if not clean_display:
                continue
            clean_key = clean_display.lower()
            
            if clean_key not in cust_map:
                cust_map[clean_key] = {"display": clean_display, "total_credit": 0.0, "total_paid": 0.0}
            
            if cat == "nasiya":
                cust_map[clean_key]["total_credit"] += tot
            elif cat == "qaytarish":
                # Qaytarilgan tovar mijozning nasiyasini kamaytiradi
                cust_map[clean_key]["total_credit"] -= tot
            elif cat in ("pul_keldi", "to'lov", "tolov"):
                cust_map[clean_key]["total_paid"] += tot

        client.execute("DELETE FROM customers")
        for key, c in cust_map.items():
            balance = c["total_credit"] - c["total_paid"]
            client.execute("""
                INSERT INTO customers (name, display_name, total_credit, total_paid, current_balance, last_updated)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, [key, c["display"], c["total_credit"], c["total_paid"], balance])
            
        logger.info(f"Mijozlar bazasi (CRM) muvaffaqiyatli yangilandi: {len(cust_map)} ta mijoz.")
    except Exception as e:
        logger.error(f"rebuild_all_customers xatolik: {e}")
    finally:
        if should_close:
            client.close()

def _auto_migrate_legacy_data(client):
    """Eski ma'lumotlarni (ketim/ostatka) naqd/nasiya/pul_keldiga va 3 nol qoidasiga avtomatik o'tkazish"""
    try:
        usd_rate = get_usd_rate()
        res = client.execute("SELECT id, category, item_name, quantity, price, total_amount, partner_name, raw_message, currency, amount_usd FROM records")
        records = res.rows
        
        need_update = False
        for r in records:
            rec_id, old_cat, item, qty, price, tot, partner, raw, curr, usd_amt = r
            raw = (raw or "").strip()
            lower_raw = raw.lower()
            
            new_cat = old_cat
            if old_cat == "qaytarish":
                new_cat = "qaytarish"
            elif old_cat == "kelim" or "kelim" in lower_raw or "kirdi" in lower_raw or "fura" in lower_raw:
                new_cat = "kelim"
            elif old_cat in ("ostatka", "pul_keldi") or any(k in lower_raw for k in ["berdi", "to'ladi", "toladi", "yopdi", "pul keldi", "pul berdi", "oplata"]):
                new_cat = "pul_keldi"
            elif "nasiya" in lower_raw or partner:
                new_cat = "nasiya"
            elif "naxt" in lower_raw or "naqd" in lower_raw or not partner:
                new_cat = "naqd"
                
            new_price = price
            if new_price is not None and 0 < new_price < 1000:
                new_price = new_price * 1000
                
            new_tot = tot or 0
            if new_tot is not None and 0 < new_tot < 1000 and new_cat in ("naqd", "nasiya", "kelim"):
                new_tot = new_tot * 1000
                
            if (not new_tot or new_tot == 0) and new_price and qty:
                new_tot = new_price * qty
                
            new_curr = curr or "UZS"
            new_usd_amt = usd_amt
            if "$" in raw or "dollar" in lower_raw:
                new_curr = "USD"
                usd_match = re.search(r'(\d+[\d\s.,]*)\s*(\$|dollar)', lower_raw)
                if usd_match:
                    try:
                        v_str = usd_match.group(1).replace(" ", "").replace(",", "")
                        new_usd_amt = float(v_str)
                        new_tot = round(new_usd_amt * usd_rate, 2)
                    except Exception:
                        pass
                        
            clean_display = normalize_partner_name(partner) if partner else None
            if not clean_display and new_cat in ("nasiya", "pul_keldi"):
                words = raw.split()
                pot = [w for w in words if re.match(r'^[A-ZА-ЯЁ][a-zа-яё]+', w)]
                if pot:
                    clean_display = normalize_partner_name(" ".join(pot[:3]))
                    
            if (new_cat != old_cat or new_price != price or new_tot != tot or clean_display != partner or new_curr != curr or new_usd_amt != usd_amt):
                client.execute("""
                    UPDATE records 
                    SET category = ?, partner_name = ?, price = ?, total_amount = ?, currency = ?, amount_usd = ?
                    WHERE id = ?
                """, [new_cat, clean_display, new_price, new_tot, new_curr, new_usd_amt, rec_id])
                need_update = True
                
        if need_update:
            logger.info("Eski yozuvlar avtomatik to'g'rilandi. Mijozlar qayta hisoblanmoqda...")
            rebuild_all_customers(client)
    except Exception as e:
        logger.warning(f"Avtomatik ma'lumotlarni normalizatsiyalashda ogohlantirish: {e}")

def init_db():
    """Baza jadvallarini yaratish, bulut bilan sinxronlash va yangilash"""
    # 1. Bulutdan oxirgi bazani yuklab olish
    try:
        download_db_from_cloud()
    except Exception as e:
        logger.warning(f"Cloud download ogohlantirish: {e}")

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
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

        # Avtomatik tekshiruv: eski yozuvlar bormi yoki mijozlar bazasi bo'sh qolganmi?
        try:
            legacy_res = client.execute("SELECT COUNT(*) FROM records WHERE category IN ('ketim', 'ostatka') OR (price > 0 AND price < 1000)")
            cust_res = client.execute("SELECT COUNT(*) FROM customers")
            has_legacy = legacy_res.rows and legacy_res.rows[0][0] > 0
            cust_empty = not cust_res.rows or cust_res.rows[0][0] == 0
            
            if has_legacy or cust_empty:
                logger.info("Baza yozuvlarini va mijozlar balansini tekshirish/normalizatsiya qilish boshlandi...")
                _auto_migrate_legacy_data(client)
                rebuild_all_customers(client)
        except Exception as check_err:
            logger.warning(f"Baza tekshiruvida ogohlantirish: {check_err}")

        logger.info("Ma'lumotlar bazasi jadvallari va mijozlar bazasi 100% tayyor holatda.")
    except Exception as e:
        logger.error(f"init_db xatoligi: {e}")
        raise
    finally:
        client.close()

# ----------------- SOZLAMALAR VA MODULLAR (FEATURE TOGGLES) -----------------

DEFAULT_SETTINGS = {
    "module_nasiya": "true",
    "module_voice": "true",
    "module_usd": "true",
    "module_kelim": "true",
    "module_backup": "true",
    "module_returns": "true",
    "auto_debt_reminder": "true"
}

def get_setting(key: str, default: Optional[str] = None) -> str:
    """Sozlamani bazadan olish"""
    client = get_client()
    try:
        res = client.execute("SELECT value FROM settings WHERE key = ? LIMIT 1", [key])
        if res.rows:
            return str(res.rows[0][0])
        return default if default is not None else DEFAULT_SETTINGS.get(key, "false")
    except Exception as e:
        logger.warning(f"get_setting xatolik ({key}): {e}")
        return default if default is not None else DEFAULT_SETTINGS.get(key, "false")
    finally:
        client.close()

def set_setting(key: str, value: str):
    """Sozlamani bazada yangilash"""
    client = get_client()
    try:
        client.execute("""
            INSERT INTO settings (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
        """, [key, str(value)])
    finally:
        client.close()

def get_all_settings() -> Dict[str, str]:
    """Barcha yoqilgan/o'chirilgan modullar holati"""
    out = dict(DEFAULT_SETTINGS)
    client = get_client()
    try:
        res = client.execute("SELECT key, value FROM settings")
        for row in res.rows:
            out[row[0]] = str(row[1])
        return out
    except Exception as e:
        logger.warning(f"get_all_settings xatolik: {e}")
        return out
    finally:
        client.close()

def is_module_enabled(module_name: str) -> bool:
    """Modul yoqilganligini tekshirish (true/false)"""
    val = get_setting(f"module_{module_name}", DEFAULT_SETTINGS.get(f"module_{module_name}", "true"))
    return str(val).strip().lower() in ("true", "1", "yes", "on")

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
        elif category == "qaytarish":
            client.execute("""
                UPDATE customers 
                SET total_credit = total_credit - ?,
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
                COALESCE(SUM(CASE WHEN category = 'nasiya' THEN total_amount
                                  WHEN category = 'qaytarish' THEN -total_amount ELSE 0 END), 0) as total_credit,
                COALESCE(SUM(CASE WHEN category IN ('pul_keldi', 'to''lov', 'tolov') THEN total_amount ELSE 0 END), 0) as total_paid
            FROM records
            WHERE LOWER(TRIM(partner_name)) = ?
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

def get_message_datetime(chat_id: int, message_id: int) -> Optional[tuple]:
    """Xabarga tegishli mavjud yozuvning ASL sana va vaqtini qaytaradi (tuzatishda saqlab qolish uchun)"""
    client = get_client()
    try:
        res = client.execute(
            "SELECT date_str, time_str FROM records WHERE chat_id = ? AND message_id = ? ORDER BY id LIMIT 1",
            [chat_id, message_id]
        )
        if res.rows:
            return (res.rows[0][0], res.rows[0][1])
        return None
    finally:
        client.close()

def get_records_by_message(chat_id: int, message_id: int) -> List[Dict[str, Any]]:
    client = get_client()
    try:
        res = client.execute("SELECT * FROM records WHERE chat_id = ? AND message_id = ? ORDER BY id", [chat_id, message_id])
        return rows_to_dicts(res)
    finally:
        client.close()

def customer_exists(partner_name: str) -> bool:
    if not partner_name:
        return False
    key = normalize_partner_name(partner_name).lower()
    client = get_client()
    try:
        res = client.execute("SELECT 1 FROM customers WHERE name = ? LIMIT 1", [key])
        return bool(res.rows)
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
        
        try:
            trigger_cloud_sync_async()
        except Exception:
            pass

        return list(affected_partners)
    except Exception as e:
        logger.error(f"delete_records_by_message xatolik: {e}")
        return []
    finally:
        client.close()

def recalculate_day_summary(target_date: Optional[str] = None) -> Dict[str, Any]:
    """1 kunlik barcha ma'lumotlarni ko'rib chiqish va statistikani to'liq yangilash"""
    if not target_date:
        target_date = get_now().strftime("%Y-%m-%d")

    client = get_client()
    try:
        partners_res = client.execute(
            "SELECT DISTINCT partner_name FROM records WHERE date_str = ? AND partner_name IS NOT NULL",
            [target_date]
        )
        for p in partners_res.rows:
            if p[0]:
                recalculate_customer_balance(p[0])
        
        rebuild_all_customers(client)
    except Exception as e:
        logger.error(f"recalculate_day_summary xatolik: {e}")
    finally:
        client.close()

    try:
        trigger_cloud_sync_async()
    except Exception:
        pass

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
    now = get_now()
    if not date_str:
        date_str = now.strftime("%Y-%m-%d")
    if not time_str:
        time_str = now.strftime("%H:%M:%S")

    # 1. Narxlardagi 3 ta nol qoidasi (masalan 170 -> 170000)
    if price is not None and 0 < price < 1000:
        price = price * 1000

    # 2. Jami summa: soni va narxi ma'lum bo'lsa, summa HAR DOIM kod orqali hisoblanadi
    #    (AI ning arifmetikasiga ishonilmaydi).
    if price is not None and quantity is not None and quantity > 0:
        total_amount = round(float(price) * float(quantity), 2)
    elif total_amount is not None and 0 < total_amount < 1000 and category in ("naqd", "nasiya", "pul_keldi", "qaytarish", "rasxod", "uyga") and currency != "USD":
        # Faqat 1000 dan kichik summalar mingda deb hisoblanadi (masalan "500 berdi" -> 500 000).
        # Avval bu chegara 100 000 edi va 50 000 so'mlik savdo 50 mln bo'lib qolishi mumkin edi.
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
    if partner_name_cleaned and category in ("nasiya", "pul_keldi", "qaytarish") and total_amount:
        update_customer_ledger(partner_name_cleaned, category, total_amount)

    try:
        trigger_cloud_sync_async()
    except Exception:
        pass

    return record_id

def get_all_customer_names() -> List[str]:
    """Aqlli ism solishtirish uchun barcha mavjud mijozlarning kanonik ismlari ro'yxati"""
    client = get_client()
    try:
        res = client.execute("SELECT display_name FROM customers ORDER BY id ASC")
        return [row[0] for row in res.rows if row[0]]
    except Exception:
        return []
    finally:
        client.close()

def get_customer_by_id(cust_id: int) -> Optional[str]:
    client = get_client()
    try:
        res = client.execute("SELECT display_name FROM customers WHERE id = ? LIMIT 1", [cust_id])
        return res.rows[0][0] if res.rows else None
    finally:
        client.close()

def get_customer_id_by_name(display_name: str) -> Optional[int]:
    client = get_client()
    try:
        res = client.execute("SELECT id FROM customers WHERE LOWER(display_name) = ? LIMIT 1", [display_name.lower()])
        return res.rows[0][0] if res.rows else None
    finally:
        client.close()

def reassign_message_partner(chat_id: int, message_id: int, new_partner: str):
    """Xabardagi mijoz ismini boshqa aniq mijozga o'tkazish va ikkala mijoz balansini qayta hisoblash"""
    client = get_client()
    old_partners = set()
    try:
        res = client.execute("SELECT partner_name FROM records WHERE chat_id = ? AND message_id = ?", [chat_id, message_id])
        for r in res.rows:
            if r[0]:
                old_partners.add(r[0])
        client.execute(
            "UPDATE records SET partner_name = ? WHERE chat_id = ? AND message_id = ?",
            [new_partner, chat_id, message_id]
        )
    finally:
        client.close()
    for p in old_partners:
        recalculate_customer_balance(p)
    recalculate_customer_balance(new_partner)

def _query_day_metrics(client, date_str: str) -> Dict[str, Any]:
    """Bir kunlik barcha toifalar (so'm va dollar ajratilgan holda)"""
    res = client.execute("""
        SELECT
            category,
            COUNT(*) as cnt,
            COALESCE(SUM(total_amount), 0) as tot_uzs_equiv,
            COALESCE(SUM(quantity), 0) as qty,
            COALESCE(SUM(CASE WHEN currency = 'USD' THEN COALESCE(amount_usd, 0) ELSE 0 END), 0) as usd_sum,
            COALESCE(SUM(CASE WHEN currency != 'USD' OR currency IS NULL THEN COALESCE(total_amount, 0) ELSE 0 END), 0) as uzs_only
        FROM records
        WHERE date_str = ?
        GROUP BY category
    """, [date_str])
    out = {}
    for cat in ("kelim", "naqd", "nasiya", "pul_keldi", "qaytarish", "rasxod", "uyga"):
        out[cat] = {"count": 0, "total_sum": 0.0, "qty": 0.0, "usd_sum": 0.0, "uzs_sum": 0.0}
    for row in res.rows:
        cat = row[0]
        if cat in out:
            out[cat] = {
                "count": int(row[1] or 0),
                "total_sum": float(row[2] or 0),
                "qty": float(row[3] or 0),
                "usd_sum": float(row[4] or 0),
                "uzs_sum": float(row[5] or 0),
            }
    return out

def compute_cash_reconciliation(client, target_date: str) -> Dict[str, Any]:
    """Kunlik kassa mantiqi:
    (Bugungi Naqd + Bugungi Pul Keldi + Kechagi savdodan qolgan pul - Bugungi Rasxod) vs (Uyga ketyapti) -> Farq"""
    dt = datetime.strptime(target_date, "%Y-%m-%d")
    yesterday_str = (dt - timedelta(days=1)).strftime("%Y-%m-%d")

    t = _query_day_metrics(client, target_date)
    y = _query_day_metrics(client, yesterday_str)

    # Kechagi kunning sof naqd qoldig'i (agar kecha uyga ketmagan bo'lsa bugunga qo'shiladi)
    y_in_uzs = y["naqd"]["uzs_sum"] + y["pul_keldi"]["uzs_sum"]
    y_out_uzs = y["rasxod"]["uzs_sum"] + y["uyga"]["uzs_sum"]
    y_carry_uzs = max(0.0, round(y_in_uzs - y_out_uzs, 2))

    y_in_usd = y["naqd"]["usd_sum"] + y["pul_keldi"]["usd_sum"]
    y_out_usd = y["rasxod"]["usd_sum"] + y["uyga"]["usd_sum"]
    y_carry_usd = max(0.0, round(y_in_usd - y_out_usd, 2))

    t_in_uzs = t["naqd"]["uzs_sum"] + t["pul_keldi"]["uzs_sum"]
    t_rasxod_uzs = t["rasxod"]["uzs_sum"]
    t_uyga_uzs = t["uyga"]["uzs_sum"]
    expected_uzs = round(t_in_uzs + y_carry_uzs - t_rasxod_uzs, 2)
    diff_uzs = round(expected_uzs - t_uyga_uzs, 2)

    t_in_usd = t["naqd"]["usd_sum"] + t["pul_keldi"]["usd_sum"]
    t_rasxod_usd = t["rasxod"]["usd_sum"]
    t_uyga_usd = t["uyga"]["usd_sum"]
    expected_usd = round(t_in_usd + y_carry_usd - t_rasxod_usd, 2)
    diff_usd = round(expected_usd - t_uyga_usd, 2)

    return {
        "date": target_date,
        "yesterday_date": yesterday_str,
        "today_naqd_uzs": t["naqd"]["uzs_sum"],
        "today_naqd_usd": t["naqd"]["usd_sum"],
        "today_pul_uzs": t["pul_keldi"]["uzs_sum"],
        "today_pul_usd": t["pul_keldi"]["usd_sum"],
        "yesterday_naqd_total_uzs": y_in_uzs,
        "yesterday_naqd_total_usd": y_in_usd,
        "yesterday_carry_uzs": y_carry_uzs,
        "yesterday_carry_usd": y_carry_usd,
        "yesterday_net_uzs": y_carry_uzs,
        "yesterday_net_usd": y_carry_usd,
        "today_in_uzs": t_in_uzs,
        "today_in_usd": t_in_usd,
        "today_rasxod_uzs": t_rasxod_uzs,
        "today_rasxod_usd": t_rasxod_usd,
        "expected_uzs": expected_uzs,
        "expected_usd": expected_usd,
        "uyga_uzs": t_uyga_uzs,
        "uyga_usd": t_uyga_usd,
        "today_uyga_uzs": t_uyga_uzs,
        "today_uyga_usd": t_uyga_usd,
        "diff_uzs": diff_uzs,
        "diff_usd": diff_usd,
    }

def get_daily_summary(target_date: Optional[str] = None) -> Dict[str, Any]:
    """Kunlik to'liq tahliliy hisobot va mijozlar holati"""
    if not target_date:
        target_date = get_now().strftime("%Y-%m-%d")

    client = get_client()
    try:
        m = _query_day_metrics(client, target_date)
        dt = datetime.strptime(target_date, "%Y-%m-%d")
        yesterday_str = (dt - timedelta(days=1)).strftime("%Y-%m-%d")
        y_m = _query_day_metrics(client, yesterday_str)
        reconciliation = compute_cash_reconciliation(client, target_date)

        # Jami qarzlar va mijozlar statistikasi
        r_debt = client.execute("SELECT COALESCE(SUM(current_balance), 0) FROM customers WHERE current_balance > 0").rows[0]
        r_cust_count = client.execute("SELECT COUNT(*) FROM customers").rows[0][0]
        r_debtors_count = client.execute("SELECT COUNT(*) FROM customers WHERE current_balance > 0").rows[0][0]

        # Top 3 qarzdor
        top_res = client.execute("""
            SELECT display_name, current_balance 
            FROM customers 
            WHERE current_balance > 0 
            ORDER BY current_balance DESC 
            LIMIT 3
        """)
        top_debtors = [{"name": row[0], "balance": row[1]} for row in top_res.rows]

        # Oxirgi faol savdo kuni (agar bugun hali savdo bo'lmagan bo'lsa)
        latest_summary = None
        latest_date_res = client.execute("""
            SELECT date_str FROM records 
            WHERE date_str <= ? AND category IN ('naqd', 'nasiya', 'pul_keldi')
            ORDER BY date_str DESC LIMIT 1
        """, [target_date])
        if latest_date_res.rows:
            l_date = latest_date_res.rows[0][0]
            if l_date != target_date:
                lm = _query_day_metrics(client, l_date)
                latest_summary = {
                    "date": l_date,
                    "naqd_count": lm["naqd"]["count"], "naqd_sum": lm["naqd"]["total_sum"],
                    "naqd_usd": lm["naqd"]["usd_sum"],
                    "nasiya_count": lm["nasiya"]["count"], "nasiya_sum": lm["nasiya"]["total_sum"],
                    "pul_count": lm["pul_keldi"]["count"], "pul_sum": lm["pul_keldi"]["total_sum"]
                }

        return {
            "date": target_date,
            "kelim": m["kelim"],
            "naqd": m["naqd"],
            "nasiya": m["nasiya"],
            "pul_keldi": m["pul_keldi"],
            "qaytarish": m["qaytarish"],
            "rasxod": m["rasxod"],
            "uyga": m["uyga"],
            "yesterday": {"date": yesterday_str, **y_m},
            "reconciliation": reconciliation,
            "total_customer_debts": r_debt[0],
            "total_customers_count": r_cust_count,
            "debtors_count": r_debtors_count,
            "top_debtors": top_debtors,
            "latest_active_summary": latest_summary
        }
    finally:
        client.close()

def get_advanced_stats(period: str = "7days") -> Dict[str, Any]:
    """Mini App uchun tahliliy statistika va diagrammalar"""
    now = get_now()
    today_str = now.strftime("%Y-%m-%d")
    yesterday_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    if period == "today":
        start_date = today_str
        end_date = today_str
        date_list = [today_str]
    elif period == "yesterday":
        start_date = yesterday_str
        end_date = yesterday_str
        date_list = [yesterday_str]
    elif period == "month":
        start_date = (now - timedelta(days=30)).strftime("%Y-%m-%d")
        end_date = today_str
        date_list = [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(29, -1, -1)]
    elif period == "all":
        start_date = "2000-01-01"
        end_date = today_str
        date_list = [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(29, -1, -1)]
    else:  # 7days
        start_date = (now - timedelta(days=6)).strftime("%Y-%m-%d")
        end_date = today_str
        date_list = [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6, -1, -1)]

    client = get_client()
    try:
        # Asosiy KPI (UZS + USD + Rasxod + Uyga)
        kpi_res = client.execute("""
            SELECT 
                COALESCE(SUM(CASE WHEN category = 'naqd' AND COALESCE(currency, 'UZS') != 'USD' THEN total_amount ELSE 0 END), 0) as total_naqd_sum,
                COALESCE(SUM(CASE WHEN category = 'naqd' AND currency = 'USD' THEN total_amount ELSE 0 END), 0) as total_naqd_usd,
                COUNT(CASE WHEN category = 'naqd' THEN 1 END) as count_naqd,
                COALESCE(SUM(CASE WHEN category = 'nasiya' AND COALESCE(currency, 'UZS') != 'USD' THEN total_amount ELSE 0 END), 0) as total_nasiya_sum,
                COUNT(CASE WHEN category = 'nasiya' THEN 1 END) as count_nasiya,
                COALESCE(SUM(CASE WHEN category = 'pul_keldi' AND COALESCE(currency, 'UZS') != 'USD' THEN total_amount ELSE 0 END), 0) as total_paid_sum,
                COALESCE(SUM(CASE WHEN category = 'pul_keldi' AND currency = 'USD' THEN total_amount ELSE 0 END), 0) as total_paid_usd,
                COUNT(CASE WHEN category = 'pul_keldi' THEN 1 END) as count_paid,
                COALESCE(SUM(CASE WHEN category = 'kelim' AND COALESCE(currency, 'UZS') != 'USD' THEN total_amount ELSE 0 END), 0) as total_kelim_sum,
                COUNT(CASE WHEN category = 'kelim' THEN 1 END) as count_kelim,
                COALESCE(SUM(CASE WHEN category = 'rasxod' AND COALESCE(currency, 'UZS') != 'USD' THEN total_amount ELSE 0 END), 0) as total_rasxod_sum,
                COALESCE(SUM(CASE WHEN category = 'rasxod' AND currency = 'USD' THEN total_amount ELSE 0 END), 0) as total_rasxod_usd,
                COALESCE(SUM(CASE WHEN category = 'uyga' AND COALESCE(currency, 'UZS') != 'USD' THEN total_amount ELSE 0 END), 0) as total_uyga_sum,
                COALESCE(SUM(CASE WHEN category = 'uyga' AND currency = 'USD' THEN total_amount ELSE 0 END), 0) as total_uyga_usd
            FROM records
            WHERE date_str BETWEEN ? AND ?
        """, [start_date, end_date])
        kpi = row_to_dict(kpi_res.columns, kpi_res.rows[0])
        kpi["total_sales"] = kpi["total_naqd_sum"] + kpi["total_nasiya_sum"]

        # Jami qoldiq qarzlar
        debt_res = client.execute("SELECT COALESCE(SUM(current_balance), 0) FROM customers WHERE current_balance > 0")
        kpi["total_debtors_balance"] = debt_res.rows[0][0]

        # Kassa va Uyga Ketyapti solishtiruvi (tanlangan oxirgi kun bo'yicha)
        reconciliation = compute_cash_reconciliation(client, end_date)

        # Grafik: Kunlar bo'yicha Naqd vs Nasiya
        daily_res = client.execute("""
            SELECT 
                date_str,
                COALESCE(SUM(CASE WHEN category = 'naqd' AND COALESCE(currency, 'UZS') != 'USD' THEN total_amount ELSE 0 END), 0) as naqd_sum,
                COALESCE(SUM(CASE WHEN category = 'nasiya' AND COALESCE(currency, 'UZS') != 'USD' THEN total_amount ELSE 0 END), 0) as nasiya_sum,
                COALESCE(SUM(CASE WHEN category = 'pul_keldi' AND COALESCE(currency, 'UZS') != 'USD' THEN total_amount ELSE 0 END), 0) as paid_sum
            FROM records
            WHERE date_str BETWEEN ? AND ?
            GROUP BY date_str
        """, [start_date, end_date])
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
            "reconciliation": reconciliation,
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

def get_all_customers(search: Optional[str] = None, limit: int = 100, order_by: str = "alphabetical") -> List[Dict[str, Any]]:
    """Mijozlar bazasi ro'yxati (Alifbo yoki Qarz bo'yicha saralash)"""
    client = get_client()
    try:
        order_clause = "ORDER BY LOWER(display_name) ASC" if order_by == "alphabetical" else "ORDER BY current_balance DESC"
        if search and search.strip():
            s = f"%{search.strip().lower()}%"
            query = f"""
                SELECT * FROM customers 
                WHERE LOWER(display_name) LIKE ? OR LOWER(name) LIKE ?
                {order_clause}
                LIMIT ?
            """
            res = client.execute(query, [s, s, limit])
        else:
            query = f"""
                SELECT * FROM customers 
                {order_clause}
                LIMIT ?
            """
            res = client.execute(query, [limit])
        return rows_to_dicts(res)
    finally:
        client.close()

def get_customer_detail(partner_name: str) -> Optional[Dict[str, Any]]:
    """Mijozning to'liq profili va unga tegishli barcha savdo/pul berdi yozuvlari tarixi"""
    if not partner_name:
        return None
    clean_display = normalize_partner_name(partner_name)
    clean_key = clean_display.lower()
    client = get_client()
    try:
        # 1. Mijozning umumiy ma'lumoti
        c_res = client.execute(
            "SELECT * FROM customers WHERE name = ? OR LOWER(display_name) = ? LIMIT 1",
            [clean_key, clean_key]
        )
        c_list = rows_to_dicts(c_res)
        if c_list:
            customer_data = c_list[0]
        else:
            customer_data = {
                "name": clean_key,
                "display_name": clean_display,
                "total_credit": 0.0,
                "total_paid": 0.0,
                "current_balance": 0.0
            }

        # 2. Faqat AYNAN shu mijozga tegishli yozuvlar (Telegram sanasi va vaqti bilan).
        # Eslatma: avval LIKE '%ism%' ishlatilgan edi - "Ali" kartochkasiga "Alisher" ham
        # tushib qolardi. Endi faqat to'liq mos ism olinadi.
        r_res = client.execute("""
            SELECT * FROM records 
            WHERE LOWER(TRIM(partner_name)) = ?
            ORDER BY date_str DESC, time_str DESC, id DESC
        """, [clean_key])
        records = rows_to_dicts(r_res)

        return {
            "customer": customer_data,
            "records": records,
            "total_records": len(records)
        }
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
