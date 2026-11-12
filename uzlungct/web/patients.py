"""Bemor reyestri (klinik foydalanish): 6 xonali ID, F.I.Sh., tug'ilgan sana, telefon — SHIFRLANGAN holda.

Shaxsiy ma'lumotlar faqat shu bazada (HOME/patients.db) saqlanadi: AES-256-GCM, kalit HOME/.patient_key.
Ochiq holda faqat 6 xonali ID va xizmat maydonlari turadi. Tahlillar (job.json, report.json), audit, jurnal,
statistika va konsultatsiyalarga faqat ID yoziladi. Tadqiqot DATASET i (LC… kodlari) bu reyestrga bog'lanmaydi.
Tasdiq: workspace/docs/PM3_tasdiq.md (O‘RQ-547: rozilik, lokalizatsiya).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time
from pathlib import Path

import phonenumbers
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .patient import norm_name, parse

ID_MIN, ID_MAX = 100000, 999999
WARN_AT = 800_000


class PatientError(ValueError):
    """detail — API xato kodi (i18n: err.<kod>)."""


class KeyErrorPatient(RuntimeError):
    pass


def norm_phone(s, region="UZ"):
    """Xalqaro E.164 (+998901234567) yoki None. Noto'g'ri bo'lsa PatientError('bad_phone')."""
    if s in (None, ""):
        return None
    s = str(s).strip()
    if len(s) > 32:
        raise PatientError("bad_phone")
    try:
        n = phonenumbers.parse(s, region)
    except phonenumbers.NumberParseException:
        raise PatientError("bad_phone") from None
    if not phonenumbers.is_valid_number(n):
        raise PatientError("bad_phone")
    return phonenumbers.format_number(n, phonenumbers.PhoneNumberFormat.E164)


def fmt_phone(e164):
    if not e164:
        return None
    return phonenumbers.format_number(phonenumbers.parse(e164, None), phonenumbers.PhoneNumberFormat.INTERNATIONAL)


def mask_phone(e164):
    """+998 ** *** 45 67 — oxirgi 4 raqam ko'rinadi."""
    f = fmt_phone(e164)
    if not f:
        return None
    digits = sum(c.isdigit() for c in f); keep_from = digits - 4; i = 0; out = []
    cc_len = len(str(phonenumbers.parse(e164, None).country_code))
    for c in f:
        if c.isdigit():
            i += 1
            out.append(c if i <= cc_len or i > keep_from else "*")
        else:
            out.append(c)
    return "".join(out)


def clean(body: dict) -> dict:
    """So'rov tanasi → tozalangan bemor ma'lumoti. Xato bo'lsa PatientError."""
    if not isinstance(body, dict):
        raise PatientError("bad_patient")
    p = parse({k: body.get(k) for k in ("last", "first", "middle", "birth")})
    if p is None:
        raise PatientError("bad_patient")
    phone = norm_phone(body.get("phone"), body.get("region") or "UZ")
    return {"last": p["last"], "first": p["first"], "middle": p["middle"], "birth": p["birth"].isoformat(), "phone": phone}


def fio(p: dict) -> str:
    return " ".join(x for x in (p["last"].upper(), p["first"], p.get("middle")) if x)


def _fold(s):
    return norm_name(s or "").casefold()


class PatientDB:
    def __init__(self, path: Path, key_path: Path):
        self.path = Path(path); self.key_path = Path(key_path)
        self._lock = threading.Lock(); self._cache = None
        if not self.key_path.exists():
            self.key_path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(str(self.key_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(secrets.token_bytes(32))
        k = self.key_path.read_bytes()
        if len(k) != 32:
            raise KeyErrorPatient("patient_key_error")
        self._aes = AESGCM(hmac.new(k, b"uzlungct-patient-enc", hashlib.sha256).digest())
        self._mac = hmac.new(k, b"uzlungct-patient-idx", hashlib.sha256).digest()
        with self._c() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("""CREATE TABLE IF NOT EXISTS patients(id TEXT PRIMARY KEY CHECK(length(id)=6), enc BLOB,
                         match_key TEXT, fio_key TEXT, created REAL, created_by TEXT, updated REAL, updated_by TEXT,
                         deleted INTEGER DEFAULT 0, merged_into TEXT)""")
            c.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_match ON patients(match_key) WHERE deleted=0 AND merged_into IS NULL")
            c.execute("CREATE INDEX IF NOT EXISTS ix_fio ON patients(fio_key)")

    def _c(self):
        c = sqlite3.connect(self.path, timeout=30, isolation_level=None); c.row_factory = sqlite3.Row
        return c

    # --- shifrlash va indeks kalitlari
    def _enc(self, p: dict) -> bytes:
        n = secrets.token_bytes(12)
        return n + self._aes.encrypt(n, json.dumps(p, ensure_ascii=False).encode(), b"patient")

    def _dec(self, b: bytes) -> dict:
        try:
            return json.loads(self._aes.decrypt(b[:12], b[12:], b"patient"))
        except Exception:
            raise KeyErrorPatient("patient_key_error") from None

    def _h(self, *parts) -> str:
        return hmac.new(self._mac, "|".join(parts).encode(), hashlib.sha256).hexdigest()

    def _keys(self, p):
        f = [_fold(p["last"]), _fold(p["first"]), _fold(p.get("middle")), p["birth"]]
        return self._h(*f, p.get("phone") or ""), self._h(*f)

    # --- o'qish
    def _all(self) -> dict:
        """id → ma'lumot (deshifrlangan, xotirada keshlanadi; o'chirilgan/birlashtirilganlar kirmaydi)."""
        with self._lock:
            if self._cache is None:
                with self._c() as c:
                    rows = c.execute("SELECT id, enc, created FROM patients WHERE deleted=0 AND merged_into IS NULL").fetchall()
                self._cache = {r["id"]: {**self._dec(r["enc"]), "id": r["id"], "created": r["created"]} for r in rows}
            return self._cache

    def _invalidate(self):
        with self._lock:
            self._cache = None

    def get(self, pid: str):
        return self._all().get(pid) if isinstance(pid, str) else None

    def status(self, pid: str):
        """None (yo'q) | 'ok' | 'deleted' | ('merged', yangi_id)."""
        with self._c() as c:
            r = c.execute("SELECT deleted, merged_into FROM patients WHERE id=?", (pid,)).fetchone()
        if not r:
            return None
        if r["merged_into"]:
            return ("merged", r["merged_into"])
        return "deleted" if r["deleted"] else "ok"

    def count(self):
        return len(self._all())

    # --- yozish
    def _new_id(self, c) -> str:
        for _ in range(50):
            pid = str(ID_MIN + secrets.randbelow(ID_MAX - ID_MIN + 1))
            if not c.execute("SELECT 1 FROM patients WHERE id=?", (pid,)).fetchone():
                return pid
        raise PatientError("registry_full")

    def register(self, p: dict, by: str, force_new=False):
        """→ (id, existing: bool, candidates: list). candidates bo'sh bo'lmasa — ID yaratilmagan (409)."""
        mk, fk = self._keys(p)
        with self._c() as c:
            c.execute("BEGIN IMMEDIATE")
            try:
                r = c.execute("SELECT id FROM patients WHERE match_key=? AND deleted=0 AND merged_into IS NULL", (mk,)).fetchone()
                if r:
                    c.execute("COMMIT"); return r["id"], True, []
                if not force_new:
                    cand = [x["id"] for x in c.execute(
                        "SELECT id FROM patients WHERE fio_key=? AND deleted=0 AND merged_into IS NULL", (fk,)).fetchall()]
                    if cand:
                        c.execute("COMMIT"); return None, False, cand
                pid = self._new_id(c); now = time.time()
                c.execute("INSERT INTO patients(id, enc, match_key, fio_key, created, created_by, updated, updated_by) VALUES(?,?,?,?,?,?,?,?)",
                          (pid, self._enc(p), mk, fk, now, by, now, by))
                c.execute("COMMIT")
            except Exception:
                c.execute("ROLLBACK"); raise
        self._invalidate()
        return pid, False, []

    def update(self, pid: str, p: dict, by: str):
        mk, fk = self._keys(p)
        with self._c() as c:
            c.execute("BEGIN IMMEDIATE")
            try:
                o = c.execute("SELECT id FROM patients WHERE match_key=? AND id<>? AND deleted=0 AND merged_into IS NULL", (mk, pid)).fetchone()
                if o:
                    raise PatientError("patient_exists")
                n = c.execute("UPDATE patients SET enc=?, match_key=?, fio_key=?, updated=?, updated_by=? WHERE id=? AND deleted=0 AND merged_into IS NULL",
                              (self._enc(p), mk, fk, time.time(), by, pid)).rowcount
                c.execute("COMMIT")
            except Exception:
                c.execute("ROLLBACK"); raise
        self._invalidate()
        return n == 1

    def delete(self, pid: str, by: str):
        """Shaxsiy ma'lumot o'chiriladi (enc=NULL); ID qayta berilmaydi, tahlillar ID bilan qoladi."""
        with self._c() as c:
            n = c.execute("UPDATE patients SET enc=NULL, match_key=NULL, fio_key=NULL, deleted=1, updated=?, updated_by=? WHERE id=? AND deleted=0",
                          (time.time(), by, pid)).rowcount
        self._invalidate()
        return n == 1

    def merge(self, src: str, dst: str, by: str):
        """src → dst (admin): src ning shaxsiy ma'lumoti o'chiriladi, src ga murojaat dst ga yo'naltiriladi."""
        with self._c() as c:
            n = c.execute("UPDATE patients SET enc=NULL, match_key=NULL, fio_key=NULL, merged_into=?, updated=?, updated_by=? "
                          "WHERE id=? AND deleted=0 AND merged_into IS NULL", (dst, time.time(), by, src)).rowcount
        self._invalidate()
        return n == 1

    # --- qidiruv
    def search(self, q: str, allowed=None, limit=50):
        """q: 6 raqam — ID; aks holda F.I.Sh. qismi (kamida 2 belgi). allowed — ko'rish mumkin bo'lgan ID lar to'plami (None — hammasi)."""
        q = (q or "").strip()
        allp = self._all()
        if q.isdigit() and len(q) == 6:
            hits = [allp[q]] if q in allp else []
        else:
            words = [w for w in _fold(q).split(" ") if w]
            if not words or len(_fold(q)) < 2:
                return []
            hits = []
            for p in allp.values():
                hay = " ".join(_fold(x) for x in (p["last"], p["first"], p.get("middle")) if x)
                if all(w in hay for w in words):
                    hits.append(p)
        if allowed is not None:
            hits = [p for p in hits if p["id"] in allowed]
        hits.sort(key=lambda p: (_fold(p["last"]), _fold(p["first"]), p["id"]))
        return hits[:limit]

    def similar(self, pid: str):
        """Faqat telefon farq qiladigan boshqa yozuvlar («ehtimol bir xil bemor»)."""
        p = self.get(pid)
        if not p:
            return []
        _, fk = self._keys(p)
        with self._c() as c:
            return [r["id"] for r in c.execute("SELECT id FROM patients WHERE fio_key=? AND id<>? AND deleted=0 AND merged_into IS NULL",
                                               (fk, pid)).fetchall()]


def public(p: dict, full_phone=True) -> dict:
    """API uchun ko'rinish (faqat autentifikatsiyalangan javob tanasida)."""
    return {"id": p["id"], "fio": fio(p), "last": p["last"], "first": p["first"], "middle": p.get("middle"), "birth": p["birth"],
            "phone": fmt_phone(p.get("phone")) if full_phone else None, "phone_masked": mask_phone(p.get("phone"))}
