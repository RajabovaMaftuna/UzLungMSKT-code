"""Bemor rekvizitlari (F.I.Sh., tug'ilgan sana) — faqat bitta hujjat (PDF) uchun, SAQLANMAYDI.

Axloq qo'mitasi 26.05.2025 №58: platforma taxallusli kodlar (LC…) bilan ishlaydi. Shuning uchun bu qiymatlar
hech qayerga yozilmaydi (report.json, DB, audit, jurnal, fayl nomi, URL) — PDF xotirada yaratiladi va qaytariladi.
Tekshiruv qoidalari brauzerdagi static/patient.js bilan bir xil.
"""
from __future__ import annotations

import datetime as dt
import re
import unicodedata

# stats.py dagidek qat'iy UTC+5 (O'zbekistonda yozgi vaqt yo'q; Windows da tz bazasi bo'lmasligi mumkin)
TZ = dt.timezone(dt.timedelta(hours=5), "Asia/Tashkent")
MAX_AGE = 120
_L = r"[^\W\d_]"                                                    # har qanday alifbo harfi
NAME_RE = re.compile(rf"^{_L}(?:(?:{_L}|[‘ʼ\- ])*(?:{_L}|[‘ʼ]))?$")
BIRTH_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


def norm_name(s) -> str:
    """Bo'shliqlarni yig'ish; o‘/g‘ dan keyingi apostrof variantlari → ‘, qolganlari → ʼ (tutuq belgisi)."""
    s = re.sub(r"\s+", " ", unicodedata.normalize("NFC", str(s or ""))).strip()
    s = re.sub(r"([oOgG])[`'’ʻ‘ʼ]", r"\1‘", s)
    return re.sub(r"(?<![oOgG])[`'’ʻ]", "ʼ", s)


def valid_name(s: str) -> bool:
    return 2 <= len(s) <= 60 and bool(NAME_RE.match(s)) and not re.search(r"[‘ʼ\- ]{2,}", s)


def today() -> dt.date:
    return dt.datetime.now(TZ).date()


def age(birth: dt.date, on: dt.date | None = None) -> int:
    on = on or today()
    return on.year - birth.year - ((on.month, on.day) < (birth.month, birth.day))


def parse(p) -> dict | None:
    """So'rov tanasidagi {"last","first","middle","birth"} → tozalangan dict yoki None (noto'g'ri bo'lsa)."""
    if not isinstance(p, dict):
        return None
    last, first = norm_name(p.get("last")), norm_name(p.get("first"))
    middle = norm_name(p.get("middle")) if p.get("middle") not in (None, "") else None
    if not valid_name(last) or not valid_name(first) or (middle is not None and not valid_name(middle)):
        return None
    b = p.get("birth")
    if not isinstance(b, str) or not BIRTH_RE.match(b):
        return None
    try:
        birth = dt.date.fromisoformat(b)
    except ValueError:
        return None
    # brauzer boshqa vaqt mintaqasida bo'lishi mumkin — 1 kunlik farqqa ruxsat
    if birth > today() + dt.timedelta(days=1) or age(birth) > MAX_AGE:
        return None
    return {"last": last, "first": first, "middle": middle, "birth": birth}


def full_name(p: dict) -> str:
    return " ".join(x for x in (p["last"].upper(), p["first"], p.get("middle")) if x)
