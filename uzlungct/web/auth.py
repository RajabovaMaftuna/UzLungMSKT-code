"""Foydalanuvchilar, sessiyalar va audit jurnali (ko'p foydalanuvchili rejim, 4.3-§). v5 (2026-10-25).

Xavfsizlik choralari:
  * parollar scrypt (hashlib, standart kutubxona) bilan xeshlanadi: ``scrypt$v1$N$r$p$tuz$xesh``; Unicode NFKC normalizatsiya;
    eski ``pbkdf2_sha256$…`` xeshlari kirishda tekshiriladi va avtomatik yangilanadi (parollarga tegilmaydi);
  * parol siyosati: kamida 10, ko'pi bilan 128 belgi; keng tarqalgan parollar, login bilan o'xshashlik va harfsiz/bir xil
    belgili parollar rad etiladi; harf+raqam majburiy EMAS (parol-ibora ruxsat; NIST SP 800-63B);
  * urinishlar bazada saqlanadi (qayta ishga tushganda yo'qolmaydi): login+IP juftligi bo'yicha 5 xato → 15 daqiqa blok
    (begona IP haqiqiy foydalanuvchini chiqarib qo'ya olmaydi), login bo'yicha umumiy chegara (tanish IP lar bundan mustasno),
    IP bo'yicha chegara; mavjud va mavjud bo'lmagan loginlar uchun javob bir xil;
  * hisob yaratish/tiklash: admin parolni bilmaydi — bir martalik, muddatli kod (taklif / tiklash); foydalanuvchi parolni o'zi o'rnatadi;
  * sessiya tokeni — 256 bitli tasodifiy qiymat; serverda faqat SHA-256 xeshi; 30 daqiqa harakatsizlik yoki 12 soatdan keyin tugaydi;
  * rollar: admin, radiologist, researcher; audit jurnali xesh-zanjirli (``verify_audit``).
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
import threading
import time
import unicodedata
from pathlib import Path

ROLES = ("admin", "radiologist", "researcher")
# scrypt parametrlari. DIQQAT: qiymatlar OWASP Password Storage Cheat Sheet ning joriy tavsiyasi bilan tekshirilishi kerak (docs/audit).
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 16, 8, 2
SCRYPT_MAXMEM = 256 * 1024 * 1024
_SCRYPT_SEM = threading.BoundedSemaphore(2)          # bir vaqtda ko'pi bilan 2 ta xeshlash (xotira ~64 MB dan)
PBKDF2_ITER = 600_000                                # faqat eski xeshlarni yaratish/tekshirish uchun
MAX_FAILS, LOCK_SEC = 5, 15 * 60                     # login+IP juftligi bo'yicha
USER_MAX = 30                                        # login bo'yicha umumiy (barcha IP lar) — tanish IP lar mustasno
IP_WINDOW, IP_MAX = 10 * 60, 30                      # IP bo'yicha: 10 daqiqada 30 ta muvaffaqiyatsiz urinish
TOKEN_MAX = 10                                       # kod tanlashga urinishlar (IP va login bo'yicha, LOCK_SEC ichida)
KNOWN_IP_SEC = 30 * 86400
IDLE_SEC, ABS_SEC = 30 * 60, 12 * 3600
TOKEN_TTL = {"invite": 72 * 3600, "reset": 30 * 60}
TOKEN_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # o'xshash belgilarsiz (0/O, 1/I)
UNSET = "!"                                          # parol hali o'rnatilmagan hisob (hech qachon mos kelmaydi)

COMMON = {w for w in """
password parol parole pass passw0rd p4ssword qwerty qwertyui qwertyuiop asdfgh asdfghjkl zxcvbn zxcvbnm 123456 1234567 12345678
123456789 1234567890 111111 000000 abc123 letmein welcome admin administrator root user test guest login master dragon monkey
football baseball iloveyou sunshine princess shadow superman michael trustno1 changeme default secret uzbekistan toshkent
tashkent samarqand radiolog radiologist doctor shifokor kasalxona clinic hospital uzlungct lungct parol123 salom salom123
""".split()}
_SEQ = ("qwertyuiop", "asdfghjkl", "zxcvbnm", "1234567890", "0123456789", "abcdefghijklmnop", "йцукенгшщзх", "фывапролдж")


def _norm(pw: str) -> str:
    return unicodedata.normalize("NFKC", pw)


def _scrypt(pw: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    with _SCRYPT_SEM:
        return hashlib.scrypt(_norm(pw).encode("utf-8"), salt=salt, n=n, r=r, p=p, maxmem=SCRYPT_MAXMEM, dklen=32)


def scrypt_available() -> bool:
    return hasattr(hashlib, "scrypt")


def hash_password(pw: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    if not scrypt_available():                       # OpenSSL scrypt'siz Python: xavfsiz zaxira — PBKDF2 (eski format)
        dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, PBKDF2_ITER)
        return f"pbkdf2_sha256${PBKDF2_ITER}${salt.hex()}${dk.hex()}"
    dk = _scrypt(pw, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
    return f"scrypt$v1${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${dk.hex()}"


def verify_password(pw: str, stored) -> bool:
    try:
        if not isinstance(stored, str) or not isinstance(pw, str):
            return False
        parts = stored.split("$")
        if parts[0] == "scrypt" and len(parts) == 7 and parts[1] == "v1":
            n, r, p = int(parts[2]), int(parts[3]), int(parts[4])
            if not (2 ** 10 <= n <= 2 ** 20 and n & (n - 1) == 0 and 1 <= r <= 16 and 1 <= p <= 8):
                return False                               # buzilgan/zararli parametrlar — xotira bombasiga yo'l qo'yilmaydi
            calc = _scrypt(pw, bytes.fromhex(parts[5]), n, r, p)
            return hmac.compare_digest(calc.hex(), parts[6])
        if parts[0] == "pbkdf2_sha256" and len(parts) == 4:
            it = int(parts[1])
            if not 1 <= it <= 5_000_000:
                return False
            calc = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), bytes.fromhex(parts[2]), it)
            return hmac.compare_digest(calc.hex(), parts[3])
    except Exception:
        return False
    return False


def needs_rehash(stored) -> bool:
    if not scrypt_available():
        return not (isinstance(stored, str) and stored.startswith(f"pbkdf2_sha256${PBKDF2_ITER}$"))
    return not (isinstance(stored, str) and stored.startswith(f"scrypt$v1${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}$"))


_DUMMY: dict = {}


def _dummy_verify(pw: str):
    """Mavjud bo'lmagan login uchun ham xuddi shuncha vaqt sarflanadi (vaqt bo'yicha farqlanmasin)."""
    key = (SCRYPT_N, SCRYPT_R, SCRYPT_P)
    if key not in _DUMMY:
        _DUMMY[key] = hash_password("dummy-parol-hech-kimniki-emas")
    verify_password(pw if isinstance(pw, str) else "", _DUMMY[key])


def password_problem(pw: str, username: str | None = None):
    """None — mos; aks holda xato kodi (interfeysda tarjima qilinadi)."""
    if not isinstance(pw, str):
        return "pw_short"
    p = _norm(pw)
    if len(p) < 10:
        return "pw_short"
    if len(p) > 128:
        return "pw_long"
    if not any(ch.isalpha() for ch in p) or len(set(p)) <= 2:
        return "pw_weak"
    low = p.lower()
    if username and len(username) >= 3 and username.lower() in low:
        return "pw_username"
    core = re.sub(r"[\W\d_]+$", "", low)
    if low in COMMON or core in COMMON or any(s in low for s in _SEQ if len(s) >= 8):
        return "pw_common"
    return None


def _th(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _norm_token(tok) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(tok or "").upper())


class AuthDB:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.lock = threading.Lock()
        self.clock = time.time
        with self._c() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS users(
              username TEXT PRIMARY KEY, full_name TEXT NOT NULL, role TEXT NOT NULL, pw TEXT NOT NULL,
              active INTEGER NOT NULL DEFAULT 1, must_change INTEGER NOT NULL DEFAULT 1,
              fails INTEGER NOT NULL DEFAULT 0, locked_until REAL NOT NULL DEFAULT 0,
              created REAL NOT NULL, last_login REAL);
            CREATE TABLE IF NOT EXISTS sessions(
              token_hash TEXT PRIMARY KEY, username TEXT NOT NULL, created REAL NOT NULL, last_seen REAL NOT NULL, ip TEXT);
            CREATE TABLE IF NOT EXISTS audit(
              id INTEGER PRIMARY KEY AUTOINCREMENT, t REAL NOT NULL, username TEXT, ip TEXT, action TEXT NOT NULL, target TEXT, ok INTEGER);
            CREATE INDEX IF NOT EXISTS audit_t ON audit(t);
            CREATE INDEX IF NOT EXISTS audit_u ON audit(username, action, ok);
            CREATE TABLE IF NOT EXISTS attempts(k TEXT NOT NULL, t REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS attempts_k ON attempts(k, t);
            CREATE TABLE IF NOT EXISTS tokens(
              th TEXT PRIMARY KEY, username TEXT NOT NULL, purpose TEXT NOT NULL, created REAL NOT NULL, expires REAL NOT NULL, made_by TEXT);
            CREATE INDEX IF NOT EXISTS tokens_u ON tokens(username);
            """)
            cols = {r[1] for r in c.execute("PRAGMA table_info(audit)")}
            for col in ("prev", "h"):                       # xesh-zanjir ustunlari (eski bazalar uchun migratsiya)
                if col not in cols:
                    c.execute(f"ALTER TABLE audit ADD COLUMN {col} TEXT")

    def _now(self) -> float:
        return float(self.clock())

    def _c(self):
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        return c

    # ---------------------------------------------------------------- foydalanuvchilar
    def count_users(self):
        with self._c() as c:
            return c.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    def create_user(self, username, full_name, role, password=None, must_change=True):
        """password=None — hisob parolsiz yaratiladi (taklif kodi bilan parol o'rnatiladi)."""
        username = (username or "").strip().lower()
        if not re.fullmatch(r"[a-z0-9._-]{3,32}", username):
            raise ValueError("bad_username")
        if role not in ROLES:
            raise ValueError("bad_role")
        if password is None:
            stored, must_change = UNSET, False
        else:
            prob = password_problem(password, username)
            if prob:
                raise ValueError(prob)
            stored = hash_password(password)
        with self.lock, self._c() as c:
            if c.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
                raise ValueError("user_exists")
            c.execute("INSERT INTO users(username, full_name, role, pw, must_change, created) VALUES(?,?,?,?,?,?)",
                      (username, (full_name or "").strip()[:120], role, stored, int(must_change), self._now()))

    def get_user(self, username):
        with self._c() as c:
            r = c.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
            return dict(r) if r else None

    def list_users(self):
        with self._c() as c:
            out = []
            for r in c.execute("SELECT * FROM users ORDER BY username"):
                d = {k: r[k] for k in ("username", "full_name", "role", "active", "must_change", "locked_until", "created", "last_login")}
                d["pending"] = r["pw"] == UNSET
                out.append(d)
            return out

    def update_user(self, username, **kw):
        allowed = {k: v for k, v in kw.items() if k in ("full_name", "role", "active")}
        if "role" in allowed and allowed["role"] not in ROLES:
            raise ValueError("bad_role")
        if not allowed:
            return
        with self.lock, self._c() as c:
            sets = ", ".join(f"{k}=?" for k in allowed)
            c.execute(f"UPDATE users SET {sets} WHERE username=?", (*allowed.values(), username))
            if allowed.get("active") == 0:
                c.execute("DELETE FROM sessions WHERE username=?", (username,))

    def _clear_attempts(self, c, username):
        c.execute("DELETE FROM attempts WHERE k=? OR k LIKE ?", ("u:" + username, "up:" + username + "|%"))
        c.execute("DELETE FROM attempts WHERE k=?", ("tokuser:" + username,))

    def set_password(self, username, password, must_change=False):
        prob = password_problem(password, username)
        if prob:
            raise ValueError(prob)
        h = hash_password(password)
        with self.lock, self._c() as c:
            c.execute("UPDATE users SET pw=?, must_change=?, fails=0, locked_until=0 WHERE username=?", (h, int(must_change), username))
            c.execute("DELETE FROM sessions WHERE username=?", (username,))
            self._clear_attempts(c, username)

    def admin_reset(self, username, password):
        """Serverda ``--reset-password`` uchun: OS darajasidagi kirish talab qiladi. Parol terminalda kiritiladi."""
        username = (username or "").strip().lower()
        if not self.get_user(username):
            raise ValueError("not_found")
        self.set_password(username, password, must_change=False)
        self.audit(username, "cli", "cli_reset_password", None, True)

    # ---------------------------------------------------------------- urinishlar (bazada)
    def _fails(self, c, key, window, now):
        return [r[0] for r in c.execute("SELECT t FROM attempts WHERE k=? AND t>? ORDER BY t", (key, now - window))]

    def _add_fail(self, c, keys, now):
        c.executemany("INSERT INTO attempts(k, t) VALUES(?,?)", [(k, now) for k in keys])
        if secrets.randbelow(50) == 0:
            c.execute("DELETE FROM attempts WHERE t<?", (now - 3600,))

    @staticmethod
    def _retry(times, limit, window, now):
        """Sirpanuvchi oyna: nechchi soniyadan keyin urinishlar soni chegaradan pasayadi."""
        return max(1, int(times[len(times) - limit] + window - now) + 1)

    def _known_ip(self, c, username, ip, now):
        return c.execute("SELECT 1 FROM audit WHERE action='login' AND ok=1 AND username=? AND ip=? AND t>? LIMIT 1",
                         (username, ip, now - KNOWN_IP_SEC)).fetchone() is not None

    # ---------------------------------------------------------------- kirish
    def login_ex(self, username, password, ip):
        """Qaytaradi: {"token", "error", "remaining", "retry_after"}.
        error: None | bad_credentials | locked | too_many_attempts | disabled."""
        username = (username or "").strip().lower()
        password = password if isinstance(password, str) else ""
        ip = ip or "?"
        now = self._now()
        res = {"token": None, "error": None, "remaining": None, "retry_after": 0}
        ipk, upk, uk = "ip:" + ip, f"up:{username}|{ip}", "u:" + username
        with self._c() as c:
            ipf = self._fails(c, ipk, IP_WINDOW, now)
            upf = self._fails(c, upk, LOCK_SEC, now)
            uf = self._fails(c, uk, LOCK_SEC, now)
            known = self._known_ip(c, username, ip, now) if len(uf) >= USER_MAX else False
        if len(ipf) >= IP_MAX:
            res.update(error="too_many_attempts", retry_after=self._retry(ipf, IP_MAX, IP_WINDOW, now))
        elif len(upf) >= MAX_FAILS:
            res.update(error="locked", retry_after=self._retry(upf, MAX_FAILS, LOCK_SEC, now))
        elif len(uf) >= USER_MAX and not known:
            res.update(error="locked", retry_after=self._retry(uf, USER_MAX, LOCK_SEC, now))
        if res["error"]:
            self.audit(username, ip, "login_locked", None, False)
            return res
        u = self.get_user(username)
        if u:
            ok = verify_password(password, u["pw"])
        else:
            _dummy_verify(password); ok = False
        if not ok:
            with self._c() as c:
                self._add_fail(c, (ipk, upk, uk), now)
                if u and len(upf) + 1 >= MAX_FAILS:
                    c.execute("UPDATE users SET locked_until=? WHERE username=?", (now + LOCK_SEC, username))
            left = MAX_FAILS - (len(upf) + 1)
            if left <= 0:
                res.update(error="locked", retry_after=LOCK_SEC)
                self.audit(username, ip, "login_locked", None, False)
            else:
                res.update(error="bad_credentials", remaining=left)
                self.audit(username, ip, "login", None, False)
            return res
        if not u["active"]:                                   # parol to'g'ri tasdiqlangandan keyingina aniq sabab aytiladi
            self.audit(username, ip, "login_disabled", None, False)
            res["error"] = "disabled"
            return res
        token = secrets.token_urlsafe(32)
        upgrade = hash_password(password) if needs_rehash(u["pw"]) else None
        with self.lock, self._c() as c:
            c.execute("UPDATE users SET fails=0, locked_until=0, last_login=? WHERE username=?", (now, username))
            if upgrade:
                c.execute("UPDATE users SET pw=? WHERE username=?", (upgrade, username))
            c.execute("INSERT INTO sessions VALUES(?,?,?,?,?)", (_th(token), username, now, now, ip))
            c.execute("DELETE FROM sessions WHERE created < ?", (now - ABS_SEC,))
            c.execute("DELETE FROM attempts WHERE k=? OR k=?", (upk, uk))
        self.audit(username, ip, "login", None, True)
        res["token"] = token
        return res

    def login(self, username, password, ip):
        """Eski interfeys: (token | None, xato_kodi | None)."""
        r = self.login_ex(username, password, ip)
        return r["token"], r["error"]

    def session_user(self, token):
        if not token:
            return None
        now = self._now()
        with self.lock, self._c() as c:
            s = c.execute("SELECT * FROM sessions WHERE token_hash=?", (_th(token),)).fetchone()
            if not s:
                return None
            if now - s["last_seen"] > IDLE_SEC or now - s["created"] > ABS_SEC:
                c.execute("DELETE FROM sessions WHERE token_hash=?", (_th(token),))
                return None
            u = c.execute("SELECT * FROM users WHERE username=?", (s["username"],)).fetchone()
            if not u or not u["active"]:
                return None
            if now - s["last_seen"] > 30:
                c.execute("UPDATE sessions SET last_seen=? WHERE token_hash=?", (now, _th(token)))
            return {"username": u["username"], "full_name": u["full_name"], "role": u["role"], "must_change": bool(u["must_change"])}

    def logout(self, token):
        with self.lock, self._c() as c:
            c.execute("DELETE FROM sessions WHERE token_hash=?", (_th(token),))

    # ---------------------------------------------------------------- bir martalik kodlar (taklif / tiklash)
    def create_token(self, username, purpose, by=None, ttl=None):
        """Bir martalik kod qaytaradi (ochiq holda faqat shu yerda); bazada faqat xeshi. Eski kod bekor qilinadi."""
        if purpose not in TOKEN_TTL:
            raise ValueError("bad_params")
        username = (username or "").strip().lower()
        if not self.get_user(username):
            raise ValueError("not_found")
        raw = "".join(secrets.choice(TOKEN_ALPHABET) for _ in range(20))
        shown = "-".join(raw[i:i + 5] for i in range(0, 20, 5))
        now = self._now()
        with self.lock, self._c() as c:
            c.execute("DELETE FROM tokens WHERE username=?", (username,))
            c.execute("INSERT INTO tokens VALUES(?,?,?,?,?,?)",
                      (_th(raw), username, purpose, now, now + (ttl or TOKEN_TTL[purpose]), by))
        return shown

    def redeem_token(self, username, token, new_password, ip):
        """Kod bilan yangi parol o'rnatadi. ValueError(kod): bad_token | too_many_attempts | pw_*.
        Zaif parol kodni 'yoqmaydi' — foydalanuvchi qayta urinishi mumkin."""
        username = (username or "").strip().lower()
        ip = ip or "?"
        now = self._now()
        ipk, ukey = "tok:" + ip, "tokuser:" + username
        with self._c() as c:
            a, b = self._fails(c, ipk, LOCK_SEC, now), self._fails(c, ukey, LOCK_SEC, now)
        if len(a) >= TOKEN_MAX or len(b) >= TOKEN_MAX:
            self.audit(username, ip, "token_locked", None, False)
            raise ValueError("too_many_attempts")
        th = _th(_norm_token(token))
        with self._c() as c:
            row = c.execute("SELECT * FROM tokens WHERE th=? AND username=?", (th, username)).fetchone()
            valid = bool(row) and row["expires"] > now and self.get_user(username) is not None
            if not valid:
                self._add_fail(c, (ipk, ukey), now)
        if not valid:
            self.audit(username, ip, "token_redeem", None, False)
            raise ValueError("bad_token")
        prob = password_problem(new_password, username)
        if prob:
            raise ValueError(prob)
        h = hash_password(new_password)
        with self.lock, self._c() as c:
            gone = c.execute("DELETE FROM tokens WHERE th=?", (th,)).rowcount
            if not gone:                                      # poyga: boshqa so'rov kodni allaqachon ishlatgan
                raise ValueError("bad_token")
            c.execute("UPDATE users SET pw=?, must_change=0, fails=0, locked_until=0 WHERE username=?", (h, username))
            c.execute("DELETE FROM sessions WHERE username=?", (username,))
            self._clear_attempts(c, username)
            c.execute("DELETE FROM attempts WHERE k=?", (ipk,))
        self.audit(username, ip, "token_redeem", row["purpose"], True)

    # ---------------------------------------------------------------- audit (xesh-zanjir)
    @staticmethod
    def _row_hash(prev, t, username, ip, action, target, ok):
        return hashlib.sha256(f"{prev}|{t!r}|{username}|{ip}|{action}|{target}|{ok}".encode()).hexdigest()

    def audit(self, username, ip, action, target=None, ok=True):
        t, ok = self._now(), int(bool(ok))
        with self.lock:
            c = sqlite3.connect(self.path, timeout=10, isolation_level=None)
            try:
                c.execute("BEGIN IMMEDIATE")
                r = c.execute("SELECT h FROM audit WHERE h IS NOT NULL ORDER BY id DESC LIMIT 1").fetchone()
                prev = r[0] if r else "GENESIS"
                h = self._row_hash(prev, t, username, ip, action, target, ok)
                c.execute("INSERT INTO audit(t, username, ip, action, target, ok, prev, h) VALUES(?,?,?,?,?,?,?,?)",
                          (t, username, ip, action, target, ok, prev, h))
                c.execute("COMMIT")
            except Exception:
                c.execute("ROLLBACK") if c.in_transaction else None
                raise
            finally:
                c.close()

    def verify_audit(self):
        """Zanjir butunligini tekshiradi. Qaytaradi: {"ok", "checked", "first_bad"} (first_bad — buzilgan yozuv id si)."""
        prev, n = "GENESIS", 0
        with self._c() as c:
            for r in c.execute("SELECT * FROM audit WHERE h IS NOT NULL ORDER BY id"):
                n += 1
                calc = self._row_hash(r["prev"], r["t"], r["username"], r["ip"], r["action"], r["target"], r["ok"])
                if r["prev"] != prev or calc != r["h"]:
                    return {"ok": False, "checked": n, "first_bad": r["id"]}
                prev = r["h"]
        return {"ok": True, "checked": n, "first_bad": None}

    def audit_list(self, limit=300, username=None):
        q = "SELECT id, t, username, ip, action, target, ok FROM audit" + (" WHERE username=?" if username else "") + " ORDER BY id DESC LIMIT ?"
        with self._c() as c:
            return [dict(r) for r in c.execute(q, ((username, limit) if username else (limit,)))]


def bootstrap_admin(db: AuthDB, home: Path):
    """Birinchi ishga tushishda: parolsiz 'admin' hisobi va bir martalik taklif kodi (faylga). Parol faylga yozilmaydi."""
    if db.count_users():
        return None
    db.create_user("admin", "Administrator", "admin", None)
    code = db.create_token("admin", "invite", by="bootstrap", ttl=7 * 86400)
    f = home / "BOSHLANGICH_ADMIN_KODI.txt"
    f.write_text("UzLungMSKT birinchi kirish / first login / первый вход\n"
                 f"login: admin\nkod / code / код: {code}\n\n"
                 "Kirish oynasida «Kod bilan parol o‘rnatish» ni bosing, login va kodni kiriting, o‘z parolingizni tanlang. Kod 7 kun amal qiladi va bir marta ishlaydi.\n"
                 "On the sign-in screen click “Set password with a code”, enter the login and code, and choose your own password. The code is valid for 7 days and works once.\n"
                 "На экране входа нажмите «Задать пароль по коду», введите логин и код и выберите свой пароль. Код действует 7 дней и работает один раз.\n"
                 "Parol o‘rnatilgach ushbu faylni o‘chiring.\n", encoding="utf-8")
    return f
