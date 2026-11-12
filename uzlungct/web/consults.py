"""Konsultatsiyalar: shifokorlar o'rtasida tahlil natijasini (hisobotni) platforma ichida yuborish va qabul qilish.

Fayllar nusxalanmaydi — faqat mavjud tahlil vazifasiga (job id) vaqtinchalik kirish huquqi beriladi.
Turlar:
  consult  — «Ikkinchi fikr»: qabul qiluvchi faqat ko'radi va javob yozadi;
  handover — «Topshirish»: qabul qiluvchi qabul qilgach, yakuniy qarorni o'zi kiritadi.
Qabul qiluvchi holati: new → opened → replied | accepted | declined; yuborish darajasida: revoked, muddat (expires).
Alohida SQLite fayl (workspace/consults.db): parol va sessiyalar saqlanadigan auth.db dan ajratilgan.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

KINDS = ("consult", "handover")
PRIORITIES = ("normal", "urgent")
MAX_RECIPIENTS, MAX_MESSAGE, MAX_REPLY = 5, 1000, 2000
RATE_PER_HOUR = 60
DAY = 86400
ACTIVE = ("new", "opened", "replied", "accepted")


class ConsultDB:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.lock = threading.Lock()
        with self._c() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS consults(
              id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, sender TEXT NOT NULL, kind TEXT NOT NULL,
              message TEXT NOT NULL DEFAULT '', priority TEXT NOT NULL DEFAULT 'normal', created REAL NOT NULL,
              expires REAL NOT NULL, revoked REAL, sender_seen REAL);
            CREATE TABLE IF NOT EXISTS consult_recipients(
              consult_id INTEGER NOT NULL, recipient TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'new',
              opened_at REAL, answered_at REAL, seen_at REAL, PRIMARY KEY(consult_id, recipient));
            CREATE TABLE IF NOT EXISTS consult_messages(
              id INTEGER PRIMARY KEY AUTOINCREMENT, consult_id INTEGER NOT NULL, author TEXT NOT NULL,
              text TEXT NOT NULL, created REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS cons_job ON consults(job_id);
            CREATE INDEX IF NOT EXISTS cons_rcpt ON consult_recipients(recipient);
            """)

    def _c(self):
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        return c

    # ---------------------------------------------------------------- yaratish
    def sent_last_hour(self, sender, now=None):
        now = now or time.time()
        with self._c() as c:
            return c.execute("SELECT COUNT(*) FROM consults WHERE sender=? AND created>?", (sender, now - 3600)).fetchone()[0]

    def active_pairs(self, job_id, now=None):
        """Shu vazifa bo'yicha amal qilayotgan (qabul qiluvchi) ro'yxati."""
        now = now or time.time()
        with self._c() as c:
            return {r["recipient"] for r in c.execute(
                "SELECT r.recipient FROM consults c JOIN consult_recipients r ON r.consult_id=c.id "
                "WHERE c.job_id=? AND c.revoked IS NULL AND c.expires>? AND r.status IN (?,?,?,?)", (job_id, now, *ACTIVE))}

    def create(self, job_id, sender, recipients, kind, message, priority, expires_days, now=None):
        now = now or time.time()
        with self.lock, self._c() as c:
            cur = c.execute("INSERT INTO consults(job_id, sender, kind, message, priority, created, expires) VALUES(?,?,?,?,?,?,?)",
                            (job_id, sender, kind, message, priority, now, now + expires_days * DAY))
            cid = cur.lastrowid
            c.executemany("INSERT INTO consult_recipients(consult_id, recipient) VALUES(?,?)", [(cid, r) for r in recipients])
            return cid

    # ---------------------------------------------------------------- kirish huquqi
    def grant(self, job_id, username, now=None):
        """Foydalanuvchining shu vazifaga amal qilayotgan eng kuchli huquqi:
        None | {"kind": "consult"|"handover", "status", "consult_id", "sender", "expires"}. handover+accepted ustun."""
        now = now or time.time()
        with self._c() as c:
            rows = c.execute(
                "SELECT c.id, c.kind, c.sender, c.expires, r.status FROM consults c JOIN consult_recipients r ON r.consult_id=c.id "
                "WHERE c.job_id=? AND r.recipient=? AND c.revoked IS NULL AND c.expires>? AND r.status IN (?,?,?,?) "
                "ORDER BY c.id DESC", (job_id, username, now, *ACTIVE)).fetchall()
        if not rows:
            return None
        rank = lambda r: (r["kind"] == "handover" and r["status"] == "accepted", r["kind"] == "handover", r["id"])
        b = max(rows, key=rank)
        return {"kind": b["kind"], "status": b["status"], "consult_id": b["id"], "sender": b["sender"], "expires": b["expires"]}

    def had_expired(self, job_id, username, now=None):
        """Muddati o'tgan (qaytarib olinmagan, rad etilmagan) yuborish bormi — audit uchun."""
        now = now or time.time()
        with self._c() as c:
            return c.execute("SELECT 1 FROM consults c JOIN consult_recipients r ON r.consult_id=c.id WHERE c.job_id=? AND r.recipient=? "
                             "AND c.revoked IS NULL AND c.expires<=? AND r.status IN (?,?,?,?) LIMIT 1",
                             (job_id, username, now, *ACTIVE)).fetchone() is not None

    def shared_job_ids(self, username, now=None):
        now = now or time.time()
        with self._c() as c:
            return {r[0] for r in c.execute(
                "SELECT DISTINCT c.job_id FROM consults c JOIN consult_recipients r ON r.consult_id=c.id "
                "WHERE r.recipient=? AND c.revoked IS NULL AND c.expires>? AND r.status IN (?,?,?,?)", (username, now, *ACTIVE))}

    # ---------------------------------------------------------------- o'qish
    def get(self, cid):
        with self._c() as c:
            r = c.execute("SELECT * FROM consults WHERE id=?", (cid,)).fetchone()
            if not r:
                return None
            d = dict(r)
            d["recipients"] = [dict(x) for x in c.execute("SELECT * FROM consult_recipients WHERE consult_id=? ORDER BY recipient", (cid,))]
            d["messages"] = [dict(x) for x in c.execute("SELECT * FROM consult_messages WHERE consult_id=? ORDER BY id", (cid,))]
            return d

    def inbox(self, username):
        with self._c() as c:
            return [dict(r) for r in c.execute(
                "SELECT c.*, r.status AS my_status, r.opened_at, r.answered_at FROM consults c "
                "JOIN consult_recipients r ON r.consult_id=c.id WHERE r.recipient=? ORDER BY c.id DESC LIMIT 500", (username,))]

    def sent(self, username=None):
        q = "SELECT * FROM consults" + (" WHERE sender=?" if username else "") + " ORDER BY id DESC LIMIT 500"
        with self._c() as c:
            out = [dict(r) for r in c.execute(q, (username,) if username else ())]
            for d in out:
                d["recipients"] = [dict(x) for x in c.execute("SELECT * FROM consult_recipients WHERE consult_id=?", (d["id"],))]
            return out

    def last_message(self, cid):
        with self._c() as c:
            r = c.execute("SELECT author, text, created FROM consult_messages WHERE consult_id=? ORDER BY id DESC LIMIT 1", (cid,)).fetchone()
            return dict(r) if r else None

    def by_job(self, job_id):
        with self._c() as c:
            out = [dict(r) for r in c.execute("SELECT * FROM consults WHERE job_id=? ORDER BY id", (job_id,))]
            for d in out:
                d["recipients"] = [dict(x) for x in c.execute("SELECT * FROM consult_recipients WHERE consult_id=?", (d["id"],))]
                d["messages"] = [dict(x) for x in c.execute("SELECT * FROM consult_messages WHERE consult_id=? ORDER BY id", (d["id"],))]
            return out

    def unread_ids(self, username, now=None):
        """O'qilmagan konsultatsiyalar: qabul qiluvchi uchun — yangi yoki oxirgi ko'rgandan keyin boshqa kishi yozgan;
        yuboruvchi uchun — oxirgi ko'rgandan keyin qabul qiluvchi javob yozgan yoki holatni o'zgartirgan."""
        now = now or time.time()
        with self._c() as c:
            inbox = {r[0] for r in c.execute(
                "SELECT c.id FROM consults c JOIN consult_recipients r ON r.consult_id=c.id "
                "WHERE r.recipient=? AND c.revoked IS NULL AND c.expires>? AND r.status IN (?,?,?,?) AND (r.status='new' OR EXISTS("
                " SELECT 1 FROM consult_messages m WHERE m.consult_id=c.id AND m.author<>? AND m.created>COALESCE(r.seen_at,0)))",
                (username, now, *ACTIVE, username))}
            sent = {r[0] for r in c.execute(
                "SELECT c.id FROM consults c WHERE c.sender=? AND c.revoked IS NULL AND ("
                " EXISTS(SELECT 1 FROM consult_messages m WHERE m.consult_id=c.id AND m.author<>? AND m.created>COALESCE(c.sender_seen,0)) OR"
                " EXISTS(SELECT 1 FROM consult_recipients r WHERE r.consult_id=c.id AND r.status IN ('accepted','declined')"
                "        AND r.answered_at>COALESCE(c.sender_seen,0)))", (username, username))}
            return inbox, sent

    def unread_count(self, username, now=None):
        a, b = self.unread_ids(username, now)
        return len(a) + len(b)

    def events(self):
        """Statistika uchun: [{t, sender, n_recipients, job_id}]."""
        with self._c() as c:
            return [{"t": r["created"], "sender": r["sender"], "job_id": r["job_id"], "n_recipients": r["n"]} for r in c.execute(
                "SELECT c.created, c.sender, c.job_id, (SELECT COUNT(*) FROM consult_recipients r WHERE r.consult_id=c.id) AS n "
                "FROM consults c")]

    # ---------------------------------------------------------------- o'zgartirish
    def mark_opened(self, cid, username, now=None):
        """Qabul qiluvchi ochdi: birinchi marta bo'lsa holat 'opened'. Har safar seen_at yangilanadi. Qaytaradi: birinchi ochilishmi."""
        now = now or time.time()
        with self.lock, self._c() as c:
            n = c.execute("UPDATE consult_recipients SET status='opened', opened_at=? WHERE consult_id=? AND recipient=? AND status='new'",
                          (now, cid, username)).rowcount
            c.execute("UPDATE consult_recipients SET seen_at=? WHERE consult_id=? AND recipient=?", (now, cid, username))
            return n > 0

    def mark_sender_seen(self, cid, now=None):
        with self.lock, self._c() as c:
            c.execute("UPDATE consults SET sender_seen=? WHERE id=?", (now or time.time(), cid))

    def add_message(self, cid, author, text, now=None):
        now = now or time.time()
        with self.lock, self._c() as c:
            c.execute("INSERT INTO consult_messages(consult_id, author, text, created) VALUES(?,?,?,?)", (cid, author, text, now))
            c.execute("UPDATE consult_recipients SET status='replied', answered_at=?, opened_at=COALESCE(opened_at, ?) "
                      "WHERE consult_id=? AND recipient=? AND status IN ('new','opened')", (now, now, cid, author))

    def set_recipient_status(self, cid, username, status, now=None):
        now = now or time.time()
        with self.lock, self._c() as c:
            c.execute("UPDATE consult_recipients SET status=?, answered_at=?, opened_at=COALESCE(opened_at, ?) WHERE consult_id=? AND recipient=?",
                      (status, now, now, cid, username))

    def revoke(self, cid, now=None):
        with self.lock, self._c() as c:
            c.execute("UPDATE consults SET revoked=? WHERE id=? AND revoked IS NULL", (now or time.time(), cid))


def state(consult: dict, recipient_status: str | None = None, now=None):
    """Ko'rsatish uchun umumiy holat: revoked | expired | qabul qiluvchi holati."""
    now = now or time.time()
    if consult.get("revoked"):
        return "revoked"
    if consult["expires"] <= now and (recipient_status or "new") in ACTIVE:
        return "expired"
    return recipient_status or "new"
