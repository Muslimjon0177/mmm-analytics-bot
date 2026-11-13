import csv
import io
import re
import logging
import urllib.request
from typing import Dict, Any, List, Optional, Tuple
from database import get_client, set_setting, get_setting, rows_to_dicts
from customer_matcher import clean_display_name

logger = logging.getLogger(__name__)

def extract_sheets_csv_url(url: str) -> Optional[str]:
    """Har qanday Google Sheets havolasidan to'g'ridan-to'g'ri CSV eksport URLini yasash"""
    if not url:
        return None
    url = url.strip()
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", url)
    if not m:
        return None
    sheet_id = m.group(1)
    gid_match = re.search(r"[#&?]gid=(\d+)", url)
    gid = gid_match.group(1) if gid_match else "0"
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"

def _parse_amount(val: str) -> float:
    if not val:
        return 0.0
    cleaned = re.sub(r"[^\d.\-]", "", str(val).replace(",", ".").replace(" ", ""))
    # Agar bir nechta nuqta bo'lsa (masalan 1.500.000), oxirgisidan tashqarisini olib tashlaymiz
    if cleaned.count(".") > 1:
        parts = cleaned.split(".")
        cleaned = "".join(parts[:-1]) + "." + parts[-1]
    try:
        return float(cleaned) if cleaned and cleaned != "-" else 0.0
    except ValueError:
        return 0.0

def _detect_columns(headers: List[str]) -> Tuple[int, Optional[int], Optional[int], Optional[int]]:
    """Jadval ustunlarini avtomatik aniqlash: (name_idx, phone_idx, debt_idx, region_idx)"""
    name_idx = None
    phone_idx = None
    debt_idx = None
    region_idx = None

    for idx, h in enumerate(headers):
        hl = (h or "").strip().lower()
        if name_idx is None and any(k in hl for k in ["ism", "mijoz", "name", "klient", "fio", "f.i.o", "hamkor", "partner", "имя", "клиент", "фио"]):
            name_idx = idx
        elif phone_idx is None and any(k in hl for k in ["tel", "phone", "nomer", "raqam", "телефон", "номер"]):
            phone_idx = idx
        elif debt_idx is None and any(k in hl for k in ["qarz", "qoldiq", "balans", "balance", "debt", "summa", "долг", "остаток", "сумма", "kredit"]):
            debt_idx = idx
        elif region_idx is None and any(k in hl for k in ["hudud", "shahar", "viloyat", "manzil", "region", "city", "адрес", "город"]):
            region_idx = idx

    if name_idx is None:
        name_idx = 0
        if len(headers) > 1 and debt_idx is None:
            # 2-ustun raqamli bo'lsa qarz deb taxmin qilamiz
            debt_idx = 1

    return name_idx, phone_idx, debt_idx, region_idx

def fetch_and_import_google_sheet(url: Optional[str] = None) -> Dict[str, Any]:
    """Google Sheets'dan original mijozlar bazasini o'qib, tizimdagi customers jadvaliga kiritish"""
    target_url = (url or "").strip() or get_setting("google_sheets_url", "")
    if not target_url:
        return {"success": False, "error": "Google Sheets havolasi kiritilmagan."}

    csv_url = extract_sheets_csv_url(target_url)
    if not csv_url:
        return {"success": False, "error": "Google Sheets havolasi noto'g'ri formatda. To'liq docs.google.com/spreadsheets/d/... havolasini yuboring."}

    try:
        req = urllib.request.Request(csv_url, headers={"User-Agent": "MMM-Analytics-SheetsSync/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            content_bytes = resp.read()
    except Exception as e:
        logger.error(f"Google Sheets yuklashda xatolik: {e}")
        return {
            "success": False,
            "error": (
                f"Jadvalni yuklab bo'lmadi ({e}). Google Sheets'da 'Share' -> 'Anyone with the link' "
                "(Havola orqali hamma ko'ra oladi) ruxsati yoqilganligini tekshiring."
            )
        }

    text = content_bytes.decode("utf-8-sig", errors="replace")
    if text.lstrip().startswith("<!DOCTYPE") or text.lstrip().startswith("<html"):
        return {
            "success": False,
            "error": "Jadval yopiq (Private). Google Sheets'da 'Share' -> 'Anyone with the link (Viewer)' qilib oching."
        }

    reader = csv.reader(io.StringIO(text))
    rows = [r for r in reader if any(cell.strip() for cell in r)]
    if not rows:
        return {"success": False, "error": "Google Sheets jadvali bo'sh."}

    first_row_lower = " ".join(c.lower() for c in rows[0])
    has_header = any(k in first_row_lower for k in ["ism", "mijoz", "name", "klient", "tel", "qarz", "имя", "клиент", "долг", "№"])
    headers = rows[0] if has_header else []
    data_rows = rows[1:] if has_header else rows

    name_idx, phone_idx, debt_idx, region_idx = _detect_columns(headers if has_header else rows[0])
    # Agar 1-ustun tartib raqami (№ / ID) bo'lsa va headerda nom topilgan bo'lsa allaqachon to'g'ri;
    # headersiz bo'lib 1-ustun faqat raqam bo'lsa, 2-ustunni ism deb olamiz:
    if not has_header and data_rows and data_rows[0][0].strip().isdigit() and len(data_rows[0]) > 1:
        name_idx = 1

    client = get_client()
    imported = 0
    updated = 0
    skipped = 0
    try:
        # Havolani eslab qolish
        set_setting("google_sheets_url", target_url)

        for row in data_rows:
            if name_idx >= len(row):
                skipped += 1
                continue
            raw_name = row[name_idx].strip()
            if not raw_name or raw_name.isdigit() or raw_name.lower() in ("jami", "итого", "total"):
                skipped += 1
                continue

            region = row[region_idx].strip() if (region_idx is not None and region_idx < len(row)) else ""
            if region and region.lower() not in raw_name.lower():
                raw_name = f"{raw_name} {region}"

            display = clean_display_name(raw_name)
            if not display:
                skipped += 1
                continue
            key = display.lower()

            phone = row[phone_idx].strip() if (phone_idx is not None and phone_idx < len(row)) else None
            debt = _parse_amount(row[debt_idx]) if (debt_idx is not None and debt_idx < len(row)) else 0.0

            existing = client.execute("SELECT id, total_credit, total_paid, current_balance, phone FROM customers WHERE name = ? LIMIT 1", [key])
            if existing.rows:
                c_id, old_cred, old_paid, old_bal, old_phone = existing.rows[0]
                new_phone = phone or old_phone
                # Agar jadvalda boshlang'ich qarz berilgan bo'lsa va mijozda hali qarz yozilmagan bo'lsa yangilaymiz
                if debt > 0 and (not old_cred or old_cred == 0):
                    client.execute("""
                        UPDATE customers
                        SET display_name = ?, phone = ?, total_credit = ?, current_balance = ? - total_paid, last_updated = CURRENT_TIMESTAMP
                        WHERE id = ?
                    """, [display, new_phone, debt, debt, c_id])
                else:
                    client.execute("""
                        UPDATE customers SET display_name = ?, phone = ?, last_updated = CURRENT_TIMESTAMP WHERE id = ?
                    """, [display, new_phone, c_id])
                updated += 1
            else:
                client.execute("""
                    INSERT INTO customers (name, display_name, phone, total_credit, total_paid, current_balance, last_updated)
                    VALUES (?, ?, ?, ?, 0, ?, CURRENT_TIMESTAMP)
                """, [key, display, phone, debt, debt])
                imported += 1

        return {
            "success": True,
            "imported": imported,
            "updated": updated,
            "skipped": skipped,
            "total": imported + updated
        }
    except Exception as e:
        logger.error(f"Google Sheets import SQL xatolik: {e}")
        return {"success": False, "error": str(e)}
    finally:
        client.close()
