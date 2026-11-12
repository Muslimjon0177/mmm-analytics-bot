import json
import re
import logging
import urllib.request
import urllib.error
from typing import List, Dict, Any, Optional
from config import GEMINI_API_KEY
from currency import get_usd_rate

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """
Sen savdo va ombor tizimlaridagi xabarlarni tahlil qiluvchi o'ta aniq AI tahlilchisan.
Guruhdagi xabarlardan quyidagi 4 toifani ajratib, JSON formatida qaytarishing kerak:

1. "naqd" - Naqd savdo:
   - Qoida: Agar tovar sotilgani yozilgan bo'lsa, lekin MIJOZ / ODAM ISMI YO'Q bo'lsa (masalan: "2ta olmanok 170 dan", "10 qop un 320 dan") -> bu "naqd" savdo!
   - partner_name: null bo'ladi.

2. "nasiya" - Nasiya (qarzga) savdo:
   - Qoida: Agar MIJOZ / ODAM / DO'KON ISMI YOZILIB tovar sotilgan bo'lsa (masalan: "Akmal aka 5 ta sement 65 dan", "Karvonga 50 ta profil 120 dan") -> bu "nasiya" savdo!
   - partner_name: mijoz ismi ("Akmal aka", "Karvon" va h.k.).

3. "pul_keldi" - Kassaga pul to'lash (qarz yopish):
   - Qoida: Agar ism yozilib pul berildi, pul keldi, qarz to'landi deb yozilsa (masalan: "Akmal aka 500000 berdi", "Jamshiddan (100$) pul keldi", "Olim aka 50$ berdi") -> bu "pul_keldi" toifasi!
   - Agar summa dollarda bo'lsa ($ belgisi, qavsda masalan (100$), yoki "dollar"): currency: "USD", amount_usd: 100 deb ajrating.
   - Agar so'mda bo'lsa: currency: "UZS", total_amount: 500000.

4. "kelim" - Omborga tovar kelishi (kirim):
   - Omborga fura keldi, tovar tushirildi, kirdi (masalan: "Bugun 200 qop sement keldi").

5. "qaytarish" - Mijoz tovarni QAYTARDI (vozvrat):
   - Qoida: "qaytardi", "qaytib keldi", "vozvrat", "qaytarildi" so'zlari bo'lsa (masalan: "Ali aka 2 yashik olmani qaytardi 170 dan").
   - partner_name: mijoz ismi (bo'lmasa null). Bu mijozning qarzini kamaytiradi.

MUHIM QOIDALAR:
- Narxlarni o'qishda: Agar narx "170, 175, 180, 65, 320" kabi 1000 dan kichik sonlarda yozilgan bo'lsa, ularning orqasiga 3 ta nol qo'shib yoz (masalan: 170 -> 170000, 65 -> 65000)!
- Umumiy summa (total_amount) = quantity * price (agar ikkalasi mavjud bo'lsa).
- "1.5 mln", "1,5 million" -> 1500000; "500 ming" -> 500000.
- Agar summa yoki ism aniq tushunarsiz bo'lsa, o'zingdan to'qima: noma'lum maydonni null qoldir.
- Agar xabar salom-alik yoki oddiy gap bo'lsa: is_relevant: false, records: [] qaytar.

Javobing FAQAT va FAQAT to'g'ri JSON formatida bo'lsin:
{
  "is_relevant": true,
  "records": [
    {
      "category": "naqd" | "nasiya" | "pul_keldi" | "kelim" | "qaytarish",
      "item_name": "olmanok",
      "quantity": 2,
      "unit": "ta",
      "price": 170000,
      "total_amount": 340000,
      "partner_name": null,
      "currency": "UZS",
      "amount_usd": null
    }
  ]
}
"""

def parse_with_gemini(text: str) -> Optional[Dict[str, Any]]:
    """Gemini REST API orqali matnni chuqur tahlil qilish"""
    if not GEMINI_API_KEY:
        return None

    models = ['gemini-flash-lite-latest', 'gemini-3.8-flash', 'gemini-flash-latest']
    payload = {
        "contents": [{"parts": [{"text": f"{SYSTEM_PROMPT}\n\nXabar matni:\n\"\"\"{text}\"\"\""}]}],
        "generationConfig": {"responseMimeType": "application/json"}
    }
    data = json.dumps(payload).encode("utf-8")

    for model_name in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=12) as response:
                result_json = json.loads(response.read().decode("utf-8"))
                candidates = result_json.get("candidates", [])
                if candidates:
                    raw_content = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip()
                    if raw_content.startswith("```json"):
                        raw_content = raw_content[7:]
                    if raw_content.startswith("```"):
                        raw_content = raw_content[3:]
                    if raw_content.endswith("```"):
                        raw_content = raw_content[:-3]
                    return json.loads(raw_content.strip())
        except Exception:
            continue

    return None

def fallback_regex_parser(text: str) -> Dict[str, Any]:
    """Zaxira tahlilchi (Regex)"""
    lower = text.lower()
    records = []

    # 0. Tovar qaytarish (vozvrat)
    if any(k in lower for k in ["qaytardi", "qaytarildi", "qaytib keldi", "vozvrat"]):
        qty_match = re.search(r'(\d+[\d\s.,]*)\s*(ta|dona|qop|kg|yashik|tonna|litr|metr|blok|pochka)', lower)
        price_match = re.search(r'(\d+[\d\s.,]*)\s*(dan|so\'m|som)', lower)
        qty = float(qty_match.group(1).replace(" ", "").replace(",", ".")) if qty_match else None
        price = float(price_match.group(1).replace(" ", "").replace(",", ".")) if price_match else None
        if price and price < 1000:
            price *= 1000
        first_word = text.strip().split()[0]
        partner = None if first_word[0].isdigit() else first_word
        return {"is_relevant": True, "records": [{
            "category": "qaytarish", "item_name": text[:40].strip(), "quantity": qty,
            "unit": qty_match.group(2) if qty_match else None, "price": price,
            "total_amount": (qty * price) if (qty and price) else None,
            "partner_name": partner, "currency": "UZS", "amount_usd": None
        }]}

    # 1. Pul keldi / Pul berildi tekshiruvi
    if any(k in lower for k in ["pul keldi", "pul berdi", "berdi", "to'ladi", "toladi", "yopdi", "oplata"]):
        usd_match = re.search(r'\(?\$?\s*(\d+[\d\s.,]*)\s*(\$|dollar|usd|\b)\)?', lower)
        is_usd = "$" in text or "dollar" in lower or "usd" in lower
        
        # Ismni topishga urinish (masalan "Akmal aka 100$ berdi")
        words = text.split()
        partner_name = "Mijoz"
        if len(words) > 2 and not words[0].isdigit():
            partner_name = f"{words[0]} {words[1]}" if len(words) > 2 and words[1].lower() in ["aka", "uka", "opa", "aka.", "do'kon"] else words[0]

        amt = float(usd_match.group(1).replace(" ", "").replace(",", ".")) if usd_match else 0
        if is_usd:
            records.append({
                "category": "pul_keldi",
                "item_name": None,
                "quantity": None,
                "unit": None,
                "price": None,
                "total_amount": None,
                "partner_name": partner_name,
                "currency": "USD",
                "amount_usd": amt
            })
        else:
            if amt < 1000 and amt > 0:
                amt = amt * 1000
            records.append({
                "category": "pul_keldi",
                "item_name": None,
                "quantity": None,
                "unit": None,
                "price": None,
                "total_amount": amt,
                "partner_name": partner_name,
                "currency": "UZS",
                "amount_usd": None
            })

    # 2. Kelim (Kirim)
    elif any(k in lower for k in ["kelim", "kirim", "keldi", "omborga kirdi", "tushdi", "fura"]):
        match = re.search(r'(\d+[\d\s.,]*)\s*(ta|dona|qop|kg|tonna|litr|metr|blok|pochka)?', lower)
        qty = float(match.group(1).replace(" ", "").replace(",", ".")) if match else None
        records.append({
            "category": "kelim",
            "item_name": text[:50].strip(),
            "quantity": qty,
            "unit": match.group(2) if match and match.group(2) else "dona",
            "price": None,
            "total_amount": None,
            "partner_name": None,
            "currency": "UZS",
            "amount_usd": None
        })

    # 3. Sotuv (Naqd yoki Nasiya)
    elif any(k in lower for k in ["dan", "sotildi", "ketdi", "berildi"]) or re.search(r'\d+\s*(ta|qop|dona|kg)\b', lower):
        # Ism bormi yo'qmi tekshiramiz
        # Agar ism bo'lsa -> nasiya, bo'lmasa -> naqd
        qty_match = re.search(r'(\d+[\d\s.,]*)\s*(ta|dona|qop|kg|tonna|litr|metr|blok|pochka)', lower)
        price_match = re.search(r'(\d+[\d\s.,]*)\s*(dan|so\'m|som)', lower)

        qty = float(qty_match.group(1).replace(" ", "").replace(",", ".")) if qty_match else 1
        unit = qty_match.group(2) if qty_match else "ta"
        
        price = float(price_match.group(1).replace(" ", "").replace(",", ".")) if price_match else None
        if price and price < 1000:
            price = price * 1000

        total = (qty * price) if (qty and price) else None

        # Agar xabar boshida ism kelsa (masalan "Akmal aka ...")
        first_word = text.strip().split()[0]
        has_name = not first_word[0].isdigit() and not first_word.lower() in ["kelim", "kirim", "chiqim", "sotildi"]

        category = "nasiya" if has_name else "naqd"
        partner = first_word if has_name else None

        records.append({
            "category": category,
            "item_name": text[:40].strip(),
            "quantity": qty,
            "unit": unit,
            "price": price,
            "total_amount": total,
            "partner_name": partner,
            "currency": "UZS",
            "amount_usd": None
        })

    return {"is_relevant": len(records) > 0, "records": records}

VALID_CATEGORIES = ("naqd", "nasiya", "pul_keldi", "kelim", "qaytarish")

def _to_number(v) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return None

def _sanitize_ai_result(res: Dict[str, Any]) -> Dict[str, Any]:
    """AI natijasini qat'iy tekshirish: noto'g'ri toifa/raqamlar tashlab yuboriladi,
    summa esa kod orqali qayta hisoblanadi."""
    clean = []
    for r in res.get("records", []) or []:
        if not isinstance(r, dict):
            continue
        cat = str(r.get("category") or "").strip().lower()
        if cat not in VALID_CATEGORIES:
            continue
        r["category"] = cat
        for k in ("quantity", "price", "total_amount", "amount_usd"):
            r[k] = _to_number(r.get(k))
        pr = r.get("price")
        if pr is not None and 0 < pr < 1000:
            r["price"] = pr * 1000
        if r.get("quantity") and r.get("price"):
            r["total_amount"] = round(r["quantity"] * r["price"], 2)
        if r.get("currency") not in ("UZS", "USD"):
            r["currency"] = "USD" if r.get("amount_usd") else "UZS"
        if isinstance(r.get("partner_name"), str):
            r["partner_name"] = r["partner_name"].strip() or None
        clean.append(r)
    return {"is_relevant": bool(clean), "records": clean, "source": "ai"}

def analyze_message(text: str) -> Dict[str, Any]:
    """Asosiy tahlil funksiyasi"""
    if not text or len(text.strip()) < 2:
        return {"is_relevant": False, "records": []}

    res = parse_with_gemini(text)
    if res and isinstance(res, dict) and "records" in res:
        return _sanitize_ai_result(res)

    fb = fallback_regex_parser(text)
    fb["source"] = "regex"
    return fb
