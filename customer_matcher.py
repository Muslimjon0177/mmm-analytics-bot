import re
import unicodedata
from difflib import SequenceMatcher
from typing import List, Tuple, Optional, Dict

CYRILLIC_TO_LATIN = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "j", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "x", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh",
    "ъ": "", "ы": "i", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    "ў": "o", "қ": "q", "ғ": "g", "ҳ": "h",
}

HONORIFICS = {"aka", "uka", "opa", "singil", "xoja", "xoji", "hoji", "dokon", "mijoz", "brat", "usta"}
CASE_SUFFIXES = ("ning", "dan", "tan", "lar", "ga", "ka", "qa", "da", "ta", "ni")

def cyrillic_to_latin(text: str) -> str:
    """Kirill yozuvini lotin yozuviga o'girish"""
    if not text:
        return ""
    out = []
    for ch in text:
        low = ch.lower()
        if low in CYRILLIC_TO_LATIN:
            rep = CYRILLIC_TO_LATIN[low]
            out.append(rep.capitalize() if ch.isupper() and rep else rep)
        else:
            out.append(ch)
    return "".join(out)

def _strip_apostrophes(s: str) -> str:
    # Barcha turdagi apostroflar va belgilarni tozalash (o', g', ʻ, ʼ, ’)
    return re.sub(r"[\'ʻʼ’`´\-.,/\\]", "", s)

def strip_uzbek_suffix(word: str) -> str:
    """So'z oxiridagi o'zbekcha kelishik qo'shimchalarini olib tashlash (Aliyevga -> Aliyev)"""
    w = word
    for suf in CASE_SUFFIXES:
        if w.endswith(suf) and len(w) > len(suf) + 2:
            return w[:-len(suf)]
    return w

def phonetic_token(token: str) -> str:
    """Fonetik normalizatsiya: x/h, q/k, takror harflar, apostroflar bir xil shaklga keltiriladi.
    Masalan: 'Suhrob' == 'Suxrob' == 'сухроб'"""
    t = cyrillic_to_latin(token).lower()
    t = _strip_apostrophes(t)
    t = unicodedata.normalize("NFKD", t)
    t = re.sub(r"[^a-z0-9]", "", t)
    if not t:
        return ""
    t = strip_uzbek_suffix(t)
    # Qattiq/yumshoq x va h ni birlashtirish
    t = t.replace("h", "x")
    # o' / u va q / k kabi kichik talaffuz/imlo farqlarini yumshatish
    t = t.replace("q", "k")
    # Ketma-ket bir xil harflarni bitta qilish (suhhrob -> suxrob)
    t = re.sub(r"(.)\1+", r"\1", t)
    return t

def extract_name_parts(name: str) -> Tuple[str, str, str]:
    """Ismdan (asosiy_ism, toliq_fonetik, qoshimcha_hudud_yoki_belgi) ajratib olish.
    Masalan: 'Suxrob aka Denovga' -> ('suxrob', 'suxrob denov', 'denov')"""
    lat = cyrillic_to_latin(name or "").strip()
    raw_tokens = re.findall(r"[A-Za-zА-Яа-яЁёЎўҚқҒғҲҳ0-9ʻʼ’'`]+", lat)
    tokens = []
    for rt in raw_tokens:
        pt = phonetic_token(rt)
        if not pt or pt in HONORIFICS:
            continue
        tokens.append(pt)
    if not tokens:
        return "", "", ""
    base = tokens[0]
    qualifier = " ".join(tokens[1:])
    full = " ".join(tokens)
    return base, full, qualifier

def similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()

def clean_display_name(name: str) -> str:
    """Agar kirillda kelsa lotinga o'tkazib, qo'shimchalarni tozalab chiroyli ko'rinishga keltirish"""
    if not name:
        return ""
    text = cyrillic_to_latin(name.strip())
    words = text.split()
    if words:
        last_low = _strip_apostrophes(words[-1].lower())
        for suf in CASE_SUFFIXES:
            if last_low.endswith(suf) and len(last_low) > len(suf) + 2:
                # Oxirgi so'zdan qo'shimchani olib tashlash
                words[-1] = words[-1][:len(words[-1]) - len(suf)]
                break
    return " ".join(words).strip()

def resolve_customer_name(raw_name: str, existing_customers: List[str]) -> Dict[str, object]:
    """Guruhda yozilgan ismni mavjud mijozlar bazasi bilan aqlli solishtirish.
    Qaytaradi:
      {
        "resolved": str,          # Bazaga yoziladigan aniq mijoz nomi
        "matched_existing": bool, # Mavjud mijozga tushdimi?
        "ambiguous": bool,        # Bir nechta bir xil ismli mijoz orasida ikkilanish bormi?
        "candidates": List[str]   # Agar ikkilanish bo'lsa, nomzodlar ro'yxati
      }
    """
    if not raw_name or not raw_name.strip():
        return {"resolved": "", "matched_existing": False, "ambiguous": False, "candidates": []}

    raw_base, raw_full, raw_qual = extract_name_parts(raw_name)
    if not raw_base:
        cleaned = clean_display_name(raw_name)
        return {"resolved": cleaned, "matched_existing": False, "ambiguous": False, "candidates": []}

    # 1. Asosiy ism (masalan 'suxrob') bo'yicha barcha o'xshash mijozlarni topish
    base_matches = []
    for cust in existing_customers:
        c_base, c_full, c_qual = extract_name_parts(cust)
        if not c_base:
            continue
        b_sim = similarity(raw_base, c_base)
        if raw_base == c_base or b_sim >= 0.84:
            f_sim = similarity(raw_full, c_full)
            q_sim = similarity(raw_qual, c_qual) if (raw_qual and c_qual) else 0.0
            base_matches.append({
                "name": cust,
                "b_sim": b_sim,
                "f_sim": f_sim,
                "q_sim": q_sim,
                "c_qual": c_qual,
            })

    # Holat A: Bazada shu ismli mijoz FAQAT BITTA bo'lsa — qo'shimchasi bor-yo'qligidan qat'i nazar o'shanga yoziladi!
    if len(base_matches) == 1:
        return {
            "resolved": base_matches[0]["name"],
            "matched_existing": True,
            "ambiguous": False,
            "candidates": []
        }

    # Holat B: Bazada shu ismli mijozlar BIR NECHTA bo'lsa (masalan: 'Suhrob Denov' va 'Suhrob Qarshi')
    if len(base_matches) > 1:
        if raw_qual:
            # Qo'shimchasiga qarab eng mosini tanlaymiz
            scored = sorted(
                base_matches,
                key=lambda x: (x["q_sim"] * 0.65 + x["f_sim"] * 0.35),
                reverse=True
            )
            best = scored[0]
            second = scored[1]
            best_score = best["q_sim"] * 0.65 + best["f_sim"] * 0.35
            second_score = second["q_sim"] * 0.65 + second["f_sim"] * 0.35
            if best["q_sim"] >= 0.72 and (best_score - second_score) >= 0.08:
                return {
                    "resolved": best["name"],
                    "matched_existing": True,
                    "ambiguous": False,
                    "candidates": []
                }

        # Qo'shimcha yozilmagan yoki aniq ajratib bo'lmadi — admin tanlashi uchun nomzodlarni qaytaramiz
        cand_names = [m["name"] for m in base_matches[:5]]
        return {
            "resolved": cand_names[0],
            "matched_existing": True,
            "ambiguous": True,
            "candidates": cand_names
        }

    # Holat C: Bazada base_matches topilmadi, lekin to'liq ism imlo xatosi bilan yozilgan bo'lishi mumkin
    best_overall = None
    best_overall_sim = 0.0
    for cust in existing_customers:
        _, c_full, _ = extract_name_parts(cust)
        s = similarity(raw_full, c_full)
        if s > best_overall_sim:
            best_overall_sim = s
            best_overall = cust

    if best_overall and best_overall_sim >= 0.85:
        return {
            "resolved": best_overall,
            "matched_existing": True,
            "ambiguous": False,
            "candidates": []
        }

    # Haqiqatan yangi mijoz
    return {
        "resolved": clean_display_name(raw_name),
        "matched_existing": False,
        "ambiguous": False,
        "candidates": []
    }
