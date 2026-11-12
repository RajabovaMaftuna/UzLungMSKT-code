"""Kirish/hisob oqimlarining HTTP'dan mustaqil qismi (testlanadigan). server.py faqat shularni chaqiradi."""
from __future__ import annotations

from . import auth as A

LOGIN_STATUS = {"bad_credentials": 401, "locked": 429, "too_many_attempts": 429, "disabled": 403}


def login_error_response(res: dict):
    """login_ex natijasi xato bo'lsa (status, body, headers), aks holda None."""
    err = res.get("error")
    if not err:
        return None
    body = {"detail": err}
    if res.get("remaining") is not None:
        body["remaining"] = res["remaining"]
    headers = {}
    if res.get("retry_after"):
        body["retry_after"] = int(res["retry_after"])
        headers["Retry-After"] = str(int(res["retry_after"]))
    return LOGIN_STATUS.get(err, 401), body, headers


def redeem(db: A.AuthDB, body, ip):
    """(status, json). Kod + yangi parol; xatolar kod bilan."""
    if not isinstance(body, dict) or not all(isinstance(body.get(k), str) for k in ("username", "code", "new_password")):
        return 400, {"detail": "bad_params"}
    try:
        db.redeem_token(body["username"], body["code"], body["new_password"], ip)
    except ValueError as e:
        code = str(e)
        return (429 if code == "too_many_attempts" else 400), {"detail": code}
    return 200, {"ok": True}


def create_user(db: A.AuthDB, body, actor):
    """Admin foydalanuvchi yaratadi. Parol berilmasa — taklif kodi (admin parolni bilmaydi). ValueError(kod) ko'taradi."""
    if not isinstance(body, dict) or not all(isinstance(body.get(k, ""), str) for k in ("username", "full_name", "role")) \
            or not isinstance(body.get("password") or "", str):
        raise ValueError("bad_params")
    username = body.get("username", "").strip().lower()
    password = body.get("password") or None                    # eski usul (admin parol yozadi) — moslik uchun saqlangan
    db.create_user(username, body.get("full_name", ""), body.get("role", "radiologist"), password, must_change=True)
    if password:
        return {"ok": True, "temporary_password": password}
    code = db.create_token(username, "invite", by=actor)
    db.audit(actor, "-", "token_issue", f"{username}:invite", True)
    return {"ok": True, "username": username, "invite_code": code, "expires_hours": A.TOKEN_TTL["invite"] // 3600}


def reset_code(db: A.AuthDB, username, actor):
    """Parol unutilgan bo'lsa — 30 daqiqalik kod; hisob hali parolsiz (taklif kutilmoqda) bo'lsa — taklif kodi."""
    u = db.get_user((username or "").strip().lower())
    purpose = "invite" if u and u["pw"] == A.UNSET else "reset"
    code = db.create_token(username, purpose, by=actor)
    db.audit(actor, "-", "token_issue", f"{username}:{purpose}", True)
    return {"ok": True, "reset_code": code, "expires_minutes": A.TOKEN_TTL[purpose] // 60}
