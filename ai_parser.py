import json
import re
import base64
import logging
import urllib.request
import urllib.error
from typing import List, Dict, Any, Optional
from config import GEMINI_API_KEY
from currency import get_usd_rate

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """
Sen savdo va ombor tizimlaridagi xabarlarni tahlil qiluvchi o'ta aniq AI tahlilchisan.
Guruhdagi xabarlardan quyidagi 7 toifani ajratib, JSON formatida qaytarishing kerak:

1. "naqd" - Naqd savdo:
   - Qoida: Agar tovar sotilgani yozilgan bo'lsa, lekin MIJOZ / ODAM ISMI YO'Q bo'lsa (masalan: "2ta olmanok 170 dan", "10 qop un 320 dan", "naqd 200$", "200 dollar naqd savdo", "5ta olma 170dan (100$)") -> bu "naqd" savdo!
   - Agar naqd savdoda qavs ichida yoki alohida dollar yozilgan bo'lsa (masalan: "(200$)", "($200)", "(150 dollar)", "200$"): bizga tushgan dollar sifatida currency: "USD", amount_usd: 200 deb ajrating!
   - Agar bitta xabarda ham so'm tovar, ham qavs ichida dollar bo'lsa (masalan: "5ta olma 170dan (100$)"), IKKITA alohida record qaytaring: 1) so'mdagi naqd savdo (currency: "UZS"), 2) tushgan dollar (category: "naqd", currency: "USD", amount_usd: 100).
   - partner_name: null bo'ladi.

2. "nasiya" - Nasiya (qarzga) savdo:
   - Qoida: Agar MIJOZ / ODAM / DO'KON ISMI YOZILIB tovar sotilgan bo'lsa (masalan: "Akmal aka 5 ta sement 65 dan", "Suxrob Denov 10 ta olma 170 dan") -> bu "nasiya" savdo!
   - partner_name: mijoz ismi ("Akmal aka", "Suxrob Denov" va h.k.).

3. "pul_keldi" - Kassaga pul to'lash (qarz yopish):
   - Qoida: Agar ism yozilib pul berildi, pul keldi, qarz to'landi deb yozilsa (masalan: "Akmal aka 500000 berdi", "Jamshiddan (100$) pul keldi", "Olim aka 50$ berdi", "Ali aka 1 mln (karta) berdi") -> bu "pul_keldi" toifasi!
   - Agar summa dollarda bo'lsa ($ belgisi, qavsda masalan (100$), yoki "dollar"): currency: "USD", amount_usd: 100 deb ajrating.
   - Agar to'lov karta/plastik/click/payme orqali bo'lsa (masalan: "(karta)", "(plastik)", "karta orqali"): payment_method: "card", aks holda "cash" deb belgilang!
   - Agar so'mda bo'lsa: currency: "UZS", total_amount: 500000.

4. "kelim" - Omborga tovar kelishi (kirim):
   - Omborga fura keldi, tovar tushirildi, kirdi (masalan: "Bugun 200 qop sement keldi").

5. "qaytarish" - Mijoz tovarni QAYTARDI (vozvrat):
   - Qoida: "qaytardi", "qaytib keldi", "vozvrat", "qaytarildi" so'zlari bo'lsa (masalan: "Ali aka 2 yashik olmani qaytardi 170 dan").
   - partner_name: mijoz ismi (bo'lmasa null). Bu mijozning qarzini kamaytiradi.

6. "rasxod" - Kunlik xarajat / chiqim:
   - Qoida: "rasxod", "rasxot", "xarajat", "chiqim", "abed", "yo'l kira", "benzin", "tushlik", "oylik" kabi do'kon/ombor xarajatlari (masalan: "rasxot 150 ming", "abedga rasxod 80", "rasxot 50$").
   - item_name: xarajat sababi (masalan: "abed", "yo'l kira", "rasxot"). partner_name: null.
   - Kassadagi naqd puldan ayriladi!

7. "uyga" - Uyga ketyapti / Inkassatsiya (egasi olib ketayotgan pul):
   - Qoida: "uyga", "uyga ketyapti", "uyga ketdi", "uyga olib ketildi", "kassadan olindi" kabi yozuvlar (masalan: "uyga ketyapti 5 mln", "uyga 1000$", "uyga 3 500 000").
   - Kassadagi sof naqd pul bilan solishtirish uchun alohida hisoblanadi!

MUHIM QOIDALAR:
- Narxlarni o'qishda: Agar valyuta UZS (so'm) bo'lsa va narx "170, 175, 180, 65, 320" kabi 1000 dan kichik sonlarda yozilgan bo'lsa, ularning orqasiga 3 ta nol qo'shib yoz (masalan: 170 -> 170000, 65 -> 65000)! Agar USD ($) bo'lsa 3 ta nol QO'SHMA (masalan: 50$ -> amount_usd: 50)!
- Umumiy summa (total_amount) = quantity * price (agar ikkalasi mavjud bo'lsa).
- "1.5 mln", "1,5 million" -> 1500000; "500 ming" -> 500000.
- Agar summa yoki ism aniq tushunarsiz bo'lsa, o'zingdan to'qima: noma'lum maydonni null qoldir.
- Agar xabar salom-alik yoki oddiy gap bo'lsa: is_relevant: false, records: [] qaytar.

Javobing FAQAT va FAQAT to'g'ri JSON formatida bo'lsin:
{
  "is_relevant": true,
  "records": [
    {
      "category": "naqd" | "nasiya" | "pul_keldi" | "kelim" | "qaytarish" | "rasxod" | "uyga",
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

def parse_audio_with_gemini(audio_bytes: bytes, mime_type: str = "audio/ogg") -> Optional[Dict[str, Any]]:
    """Ovozli xabarni (voice note) Gemini multimodal modeli orqali to'g'ridan-to'g'ri tahlil qilish"""
    if not GEMINI_API_KEY or not audio_bytes:
        return None

    try:
        encoded_audio = base64.b64encode(audio_bytes).decode("utf-8")
    except Exception as be:
        logger.error(f"Audio base64 kodlashda xatolik: {be}")
        return None

    models = ['gemini-2.0-flash', 'gemini-1.5-flash', 'gemini-flash-latest']
    payload = {
        "contents": [{
            "parts": [
                {
                    "inline_data": {
                        "mime_type": mime_type,
                        "data": encoded_audio
                    }
                },
                {
                    "text": (
                        f"{SYSTEM_PROMPT}\n\n"
                        "Vazifa: Ushbu audio yozuvdagi o'zbekcha nutqni diqqat bilan eshitib, "
                        "savdo va to'lov ma'lumotlarini qat'iy yuqoridagi JSON formatida ajrating. "
                        "Agar audio mavzuga aloqasiz bo'lsa, is_relevant: false qaytaring."
                    )
                }
            ]
        }],
        "generationConfig": {"responseMimeType": "application/json"}
    }
    data = json.dumps(payload).encode("utf-8")

    for model_name in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
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
                    parsed = json.loads(raw_content.strip())
                    return _sanitize_ai_result(parsed)
        except Exception as e:
            logger.warning(f"Gemini Audio ({model_name}) xatolik: {e}")
            continue

    return None

def analyze_audio_message(audio_bytes: bytes, mime_type: str = "audio/ogg") -> Dict[str, Any]:
    """Ovozli xabarni tahlil qilishning asosiy funksiyasi"""
    res = parse_audio_with_gemini(audio_bytes, mime_type)
    if res and res.get("records"):
        res["source"] = "voice_ai"
        return res
    return {"is_relevant": False, "records": [], "source": "voice_ai_empty"}

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

    # 0.1. Uyga ketyapti (Inkassatsiya)
    if any(k in lower for k in ["uyga ketyapti", "uyga ketdi", "uyga olib", "uyga"]):
        m = re.search(r'(\d+[\d\s.,]*)\s*(mln|million|ming|\$|dollar|usd)?', lower)
        is_usd = "$" in text or "dollar" in lower or "usd" in lower
        amt = float(m.group(1).replace(" ", "").replace(",", ".")) if m else 0
        unit_kw = (m.group(2) or "") if m else ""
        if not is_usd:
            if unit_kw in ("mln", "million"):
                amt *= 1_000_000
            elif unit_kw == "ming" or (0 < amt < 1000):
                amt *= 1000
        return {"is_relevant": amt > 0, "records": [{
            "category": "uyga", "item_name": "Uyga ketyapti", "quantity": None, "unit": None,
            "price": None, "total_amount": None if is_usd else amt, "partner_name": None,
            "currency": "USD" if is_usd else "UZS", "amount_usd": amt if is_usd else None
        }]}

    # 0.2. Rasxod (Xarajat / Chiqim)
    if any(k in lower for k in ["rasxod", "rasxot", "xarajat", "chiqim"]):
        m = re.search(r'(\d+[\d\s.,]*)\s*(mln|million|ming|\$|dollar|usd)?', lower)
        is_usd = "$" in text or "dollar" in lower or "usd" in lower
        amt = float(m.group(1).replace(" ", "").replace(",", ".")) if m else 0
        unit_kw = (m.group(2) or "") if m else ""
        if not is_usd:
            if unit_kw in ("mln", "million"):
                amt *= 1_000_000
            elif unit_kw == "ming" or (0 < amt < 1000):
                amt *= 1000
        return {"is_relevant": amt > 0, "records": [{
            "category": "rasxod", "item_name": text[:40].strip(), "quantity": None, "unit": None,
            "price": None, "total_amount": None if is_usd else amt, "partner_name": None,
            "currency": "USD" if is_usd else "UZS", "amount_usd": amt if is_usd else None
        }]}

    # 0.3. Naqd savdo (USD yoki UZS)
    if any(k in lower for k in ["naqd", "naxt"]) and not any(k in lower for k in ["nasiya", "qarzga"]):
        m = re.search(r'(\d+[\d\s.,]*)\s*(mln|million|ming|\$|dollar|usd)?', lower)
        is_usd = "$" in text or "dollar" in lower or "usd" in lower
        amt = float(m.group(1).replace(" ", "").replace(",", ".")) if m else 0
        unit_kw = (m.group(2) or "") if m else ""
        if not is_usd:
            if unit_kw in ("mln", "million"):
                amt *= 1_000_000
            elif unit_kw == "ming" or (0 < amt < 1000):
                amt *= 1000
        if amt > 0:
            return {"is_relevant": True, "records": [{
                "category": "naqd", "item_name": text[:40].strip(), "quantity": None, "unit": None,
                "price": None, "total_amount": None if is_usd else amt, "partner_name": None,
                "currency": "USD" if is_usd else "UZS", "amount_usd": amt if is_usd else None
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

    return _ensure_parenthesized_usd(records, text)

VALID_CATEGORIES = ("naqd", "nasiya", "pul_keldi", "kelim", "qaytarish", "rasxod", "uyga")

def _has_card_marker(text: str) -> bool:
    """Xabarda (karta), (plastik), (click), (payme), (uzcard), (humo) belgisi borligini aniqlaydi"""
    if not text:
        return False
    return bool(re.search(
        r'\(\s*(?:karta|plastik|click|payme|uzcard|humo|perevod|terminal)\s*\)|\b(?:karta|plastik|uzcard|humo)\b',
        text, flags=re.IGNORECASE
    ))

def _extract_parenthesized_usd(text: str) -> List[float]:
    """Xabardagi qavs ichiga yozilgan dollar summalarini topadi: (200$), ($200), (150 dollar)"""
    if not text:
        return []
    found = []
    patterns = [
        r'\(\s*\$?\s*(\d+(?:[\s.,]\d+)?)\s*(?:\$|dollar|usd)\s*\)',
        r'\(\s*\$\s*(\d+(?:[\s.,]\d+)?)\s*\)',
    ]
    spans = []
    for pat in patterns:
        for m in re.finditer(pat, text, flags=re.IGNORECASE):
            if any(not (m.end() <= s or m.start() >= e) for s, e in spans):
                continue
            spans.append((m.start(), m.end()))
            try:
                val = float(m.group(1).replace(" ", "").replace(",", "."))
                if val > 0:
                    found.append(val)
            except ValueError:
                pass
    return found

def _ensure_parenthesized_usd(records: List[Dict[str, Any]], text: str) -> Dict[str, Any]:
    """Agar xabarda qavs ichida ($...) bo'lib, yozuvlarda USD sifatida tushmay qolgan bo'lsa,
    bizga tushgan dollar (naqd yoki pul_keldi) sifatida qo'shadi."""
    paren_usds = _extract_parenthesized_usd(text)
    if not paren_usds:
        return {"is_relevant": len(records) > 0, "records": records}

    existing_usds = [
        round(float(r.get("amount_usd") or 0), 2)
        for r in records
        if r.get("currency") == "USD" and (r.get("amount_usd") or 0) > 0
    ]

    # Qaysi toifaga biriktiramiz: mijozdan pul kelgan bo'lsa pul_keldi, aks holda naqd
    lower = (text or "").lower()
    is_pul = any(r.get("category") == "pul_keldi" for r in records) or any(
        k in lower for k in ["pul keldi", "pul berdi", "berdi", "to'ladi", "toladi", "yopdi", "oplata"]
    )
    partner = next((r.get("partner_name") for r in records if r.get("partner_name")), None)
    target_cat = "pul_keldi" if is_pul else "naqd"

    for usd_val in paren_usds:
        rounded_val = round(usd_val, 2)
        if any(abs(ex - rounded_val) < 0.01 for ex in existing_usds):
            continue
        records.append({
            "category": target_cat,
            "item_name": "Dollar tushum ($)" if target_cat == "naqd" else None,
            "quantity": None,
            "unit": None,
            "price": None,
            "total_amount": None,
            "partner_name": partner if target_cat == "pul_keldi" else None,
            "currency": "USD",
            "amount_usd": rounded_val,
        })
        existing_usds.append(rounded_val)

    return {"is_relevant": len(records) > 0, "records": records}

def _to_number(v) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return None

def _sanitize_ai_result(res: Dict[str, Any], original_text: str = "") -> Dict[str, Any]:
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
        if r.get("currency") not in ("UZS", "USD"):
            r["currency"] = "USD" if r.get("amount_usd") else "UZS"
        is_usd = (r["currency"] == "USD")
        pr = r.get("price")
        if not is_usd and pr is not None and 0 < pr < 1000:
            r["price"] = pr * 1000
        if is_usd:
            if not r.get("amount_usd") and r.get("quantity") and r.get("price"):
                r["amount_usd"] = round(r["quantity"] * r["price"], 2)
            elif not r.get("amount_usd") and r.get("total_amount") and r["total_amount"] < 100000:
                r["amount_usd"] = r["total_amount"]
                r["total_amount"] = None
        else:
            if r.get("quantity") and r.get("price"):
                r["total_amount"] = round(r["quantity"] * r["price"], 2)
        if isinstance(r.get("partner_name"), str):
            r["partner_name"] = r["partner_name"].strip() or None
        clean.append(r)
    ensured = _ensure_parenthesized_usd(clean, original_text)
    is_card = _has_card_marker(original_text)
    for rec in ensured.get("records", []):
        pm = str(rec.get("payment_method") or "").strip().lower()
        if pm not in ("cash", "card"):
            pm = "card" if is_card else "cash"
        elif is_card and rec.get("category") in ("naqd", "pul_keldi") and rec.get("currency") != "USD":
            pm = "card"
        rec["payment_method"] = pm
    ensured["source"] = "ai"
    return ensured

def analyze_message(text: str) -> Dict[str, Any]:
    """Asosiy tahlil funksiyasi"""
    if not text or len(text.strip()) < 2:
        return {"is_relevant": False, "records": []}

    res = parse_with_gemini(text)
    if res and isinstance(res, dict) and "records" in res:
        return _sanitize_ai_result(res, text)

    fb = fallback_regex_parser(text)
    is_card = _has_card_marker(text)
    for rec in fb.get("records", []):
        if "payment_method" not in rec:
            rec["payment_method"] = "card" if (is_card and rec.get("category") in ("naqd", "pul_keldi") and rec.get("currency") != "USD") else "cash"
    fb["source"] = "regex"
    return fb
