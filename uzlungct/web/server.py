"""UzLungMSKT veb-platformasi (4.3-§): FastAPI backend + brauzer interfeysi.

Ishga tushirish:   python -m uzlungct.web            (brauzer avtomatik ochiladi: http://localhost:8000)
Klinika serveri:   python -m uzlungct.web --host 0.0.0.0 --https --no-browser
                   (HTTPS, ko'p foydalanuvchi; batafsil: deploy/SERVER_ORNATISH.md)

Bemor ma'lumotlari faqat shu kompyuterdagi ish papkasida saqlanadi (UZLUNGCT_HOME, standart:
<repo>/workspace). Hech narsa tashqi serverga yuborilmaydi.
"""
from __future__ import annotations

import argparse
import csv
import re
import secrets
import io
import json
import math
import os
import shutil
import sys
import time
import zipfile
from functools import lru_cache
from pathlib import Path

import numpy as np
from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import consults as consults_mod
from . import stats as stats_mod
from . import authflow
from .uploadform import UploadFormError, read_upload_form
from .auth import ROLES, AuthDB, bootstrap_admin
from .jobs import JobStore
from . import patients as patients_mod

REPO = Path(__file__).resolve().parents[2]
HOME = Path(os.environ.get("UZLUNGCT_HOME", REPO / "workspace")).resolve()
for sub in ("cases", "runs", "cache", "uploads", "results"):
    (HOME / sub).mkdir(parents=True, exist_ok=True)
SETTINGS = HOME / "settings.json"
# Ma'lumotlar to'plami yo'li kodda saqlanmaydi: UZLUNGCT_DATASET_ROOT yoki <HOME>/settings.json (Sozlamalar sahifasi)
DEFAULT_SETTINGS = {"dataset_root": os.environ.get("UZLUNGCT_DATASET_ROOT", ""), "institution": ""}
QUEUE_TOTAL, QUEUE_PER_USER = 12, 3            # bir vaqtda navbatdagi tahlillar (umumiy / har bir shifokor)
MAX_UPLOAD_BYTES = 4 * 2**30                     # bitta tahlil uchun yuklanadigan fayllar hajmi chegarasi
JID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{6}$")
NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
COOKIE = "uzl_session"

app = FastAPI(title="UzLungMSKT", version="0.3.0", docs_url=None, redoc_url=None, openapi_url=None)
jobs = JobStore(HOME)
auth = AuthDB(HOME / "auth.db")
consults = consults_mod.ConsultDB(HOME / "consults.db")
patients = patients_mod.PatientDB(HOME / "patients.db", HOME / ".patient_key")   # bemor reyestri (shifrlangan; PM-3)
_boot = bootstrap_admin(auth, HOME)
if _boot:
    print(f"Birinchi administrator kodi (parol emas) yozilgan fayl: {_boot}")
SERVICE_TOKEN_FILE = HOME / ".service_token"
if not SERVICE_TOKEN_FILE.exists():
    SERVICE_TOKEN_FILE.write_text(secrets.token_urlsafe(32))
SERVICE_TOKEN = SERVICE_TOKEN_FILE.read_text().strip()
SERVICE_USER = {"username": "_service", "full_name": "UzLungMSKT service", "role": "admin", "must_change": False}
PUBLIC_API = {"/api/auth/login", "/api/auth/me", "/api/auth/redeem"}
CHANGE_ALLOWED = {"/api/auth/me", "/api/auth/password", "/api/auth/logout"}


def _ip(request: Request):
    return request.client.host if request.client else "?"


@app.middleware("http")
async def security(request: Request, call_next):
    path = request.url.path
    request.state.user = None
    if path.startswith("/api/"):
        tok = request.headers.get("x-service-token")
        if tok and _ip(request) in ("127.0.0.1", "::1") and secrets.compare_digest(tok, SERVICE_TOKEN):
            request.state.user = SERVICE_USER
        else:
            request.state.user = auth.session_user(request.cookies.get(COOKIE))
        if path not in PUBLIC_API:
            if request.state.user is None:
                return JSONResponse({"detail": "auth_required"}, status_code=401)
            if request.method != "GET" and request.headers.get("x-uzlungct") != "1":     # CSRF himoyasi
                return JSONResponse({"detail": "csrf"}, status_code=403)
            if request.state.user.get("must_change") and path not in CHANGE_ALLOWED:
                return JSONResponse({"detail": "password_change_required"}, status_code=403)
    try:
        resp = await call_next(request)
    except Exception:                  # kutilmagan xato: foydalanuvchiga kod, to'liq stek — faqat jurnalga (PM-9)
        import traceback
        rid = secrets.token_hex(4)
        print(f"[xato {rid}] {request.method} {path}\n{traceback.format_exc()}", flush=True)
        resp = JSONResponse({"detail": "internal_error", "request_id": rid}, status_code=500)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Content-Security-Policy"] = ("default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
                                               "script-src 'self' 'unsafe-inline'; frame-ancestors 'none'; form-action 'self'")
    if path.startswith("/api/") and "Cache-Control" not in resp.headers:
        resp.headers["Cache-Control"] = "no-store"
    if request.url.scheme == "https":
        resp.headers["Strict-Transport-Security"] = "max-age=31536000"
    return resp


def user(request: Request, *roles):
    u = request.state.user
    if roles and u["role"] not in roles:
        raise HTTPException(403, "forbidden")
    return u


def audit(request: Request, action, target=None, ok=True):
    u = request.state.user or {}
    auth.audit(u.get("username"), _ip(request), action, target, ok)


VIEW_ACTIONS = ("view", "report", "download_report")      # konsultatsiya qabul qiluvchisiga ruxsat etilgan amallar
HANDOVER_ACTIONS = ("download_data", "review")            # faqat qabul qilingan «Topshirish» da


def access_job(request: Request, jid: str, action: str = "view"):
    """Vazifaga kirishni tekshiradi: egasi va admin — hammasi; konsultatsiya qabul qiluvchisi — faqat amal qilayotgan
    (qaytarib olinmagan, muddati o'tmagan) yuborish bo'yicha va faqat ruxsat etilgan amallar. Aks holda 404."""
    if not JID_RE.match(jid or ""):
        raise HTTPException(400, "bad_id")
    m = jobs.get(jid)
    if not m:
        raise HTTPException(404, "not_found")
    u = request.state.user
    if u["role"] == "admin" or m.get("owner") == u["username"]:
        return m
    if m["kind"] == "analyze" and u["role"] in ("radiologist", "admin"):
        g = consults.grant(jid, u["username"])
        if g and (action in VIEW_ACTIONS or (action in HANDOVER_ACTIONS and g["kind"] == "handover" and g["status"] == "accepted")):
            return m
        if not g and consults.had_expired(jid, u["username"]):
            audit(request, "consult_expired", jid, False)
    audit(request, "access_denied", jid, False)
    raise HTTPException(404, "not_found")             # mavjudligini ham oshkor qilmaymiz


def own_job(request: Request, jid: str):
    """Faqat egasi yoki admin ("owner" amali konsultatsiya qabul qiluvchisiga hech qachon ruxsat etilmaydi)."""
    return access_job(request, jid, "owner")


def _csv_safe(v):
    """Excel'da formula bo'lib bajarilmasligi uchun (CSV formula injection, OWASP): =, +, -, @, TAB, CR bilan
    boshlanuvchi matn oldiga apostrof qo'yiladi. Sonlar o'zgarmaydi."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        try:
            float(v)
            return v
        except ValueError:
            return "'" + v
    return v


def _under(path: str, base: Path) -> Path:
    p = Path(path).resolve()
    if base.resolve() not in (p, *p.parents):
        raise HTTPException(400, "bad_path")
    return p
STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def settings():
    s = dict(DEFAULT_SETTINGS)
    if SETTINGS.exists():
        s.update(json.load(open(SETTINGS, encoding="utf-8")))
    return s


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(STATIC / "favicon.svg", media_type="image/svg+xml", headers={"Cache-Control": "max-age=86400"})


@app.get("/", response_class=HTMLResponse)
def index():
    return (STATIC / "index.html").read_text(encoding="utf-8")


@app.get("/api/settings")
def get_settings(request: Request):
    u = user(request)
    s = settings()
    return s if u["role"] in ("admin", "researcher") else {"institution": s.get("institution", "")}


def resolve_dataset_root(raw: str) -> str:
    """Foydalanuvchi kiritgan DATASET yo'lini tozalab, dataset.json joylashgan papkani qaytaradi ('' — topilmadi).
    Explorer'ning «Копировать как путь» qo'shtirnoqlari, ortiqcha bo'shliq va oxirgi '\\' olib tashlanadi; muhit o'zgaruvchilari
    (%USERPROFILE% va h.k.) ochiladi; yuqori papka berilsa (masalan, «C:\\2024-2025 год» o'rniga «...\\DATASET»), dataset.json
    2 darajagacha ichkarida qidiriladi."""
    p = raw.strip().strip('"').strip("'").strip()
    if not p:
        return ""
    p = os.path.expandvars(os.path.expanduser(p))
    base = Path(p)
    if base.is_file() and base.name.lower() == "dataset.json":     # fayl yo'lining o'zi berilsa
        return str(base.parent)
    if (base / "dataset.json").is_file():
        return str(base)
    if base.is_dir():
        found = sorted(base.glob("*/dataset.json")) or sorted(base.glob("*/*/dataset.json"))
        if len(found) == 1:                                         # bir nechta topilsa — taxmin qilinmaydi
            return str(found[0].parent)
    return ""


@app.post("/api/settings")
def set_settings(request: Request, body: dict = Body(...)):
    user(request, "admin")
    raw = str(body.get("dataset_root") or "")
    root = resolve_dataset_root(raw) if raw.strip() else ""
    if raw.strip() and not root:                                   # mavjud bo'lmagan yoki noto'g'ri DATASET papkasi saqlanmaydi
        raise HTTPException(400, "dataset_missing")
    body = {**body, "dataset_root": root}
    s = settings(); s.update({k: str(v).strip()[:500] for k, v in body.items() if k in DEFAULT_SETTINGS})
    json.dump(s, open(SETTINGS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    audit(request, "settings_update")
    return s


# ------------------------------------------------------------------ kirish, foydalanuvchilar, audit

def _set_cookie(resp, request, token, max_age):
    resp.set_cookie(COOKIE, token, max_age=max_age, httponly=True, samesite="strict",
                    secure=request.url.scheme == "https", path="/")


@app.post("/api/auth/login")
def login(request: Request, body: dict = Body(...)):
    from .auth import ABS_SEC
    res = auth.login_ex(body.get("username", ""), body.get("password", ""), _ip(request))
    err = authflow.login_error_response(res)
    if err:
        status, payload, headers = err
        return JSONResponse(payload, status_code=status, headers=headers)
    u = auth.session_user(res["token"])
    resp = JSONResponse(u)
    _set_cookie(resp, request, res["token"], ABS_SEC)
    return resp


@app.post("/api/auth/redeem")
def redeem_code(request: Request, body: dict = Body(...)):
    """Bir martalik kod (taklif/tiklash) bilan parol o'rnatish. Ochiq endpoint: kod va urinishlar cheklovi auth.py da."""
    status, payload = authflow.redeem(auth, body, _ip(request))
    return JSONResponse(payload, status_code=status)


@app.get("/api/auth/me")
def me(request: Request):
    if not request.state.user:
        return JSONResponse({"detail": "auth_required"}, status_code=401)
    return request.state.user


@app.post("/api/auth/logout")
def logout(request: Request):
    tok = request.cookies.get(COOKIE)
    if tok:
        auth.logout(tok)
    audit(request, "logout")
    resp = JSONResponse({"ok": True}); resp.delete_cookie(COOKIE, path="/")
    return resp


@app.post("/api/auth/password")
def change_password(request: Request, body: dict = Body(...)):
    from .auth import verify_password
    u = user(request)
    if u["username"] == "_service":
        raise HTTPException(403, "forbidden")
    rec = auth.get_user(u["username"])
    if not verify_password(body.get("current", ""), rec["pw"]):
        audit(request, "password_change", u["username"], False)
        raise HTTPException(400, "bad_current_password")
    if body.get("new") == body.get("current"):
        raise HTTPException(400, "pw_same")
    try:
        auth.set_password(u["username"], body.get("new", ""), must_change=False)
    except ValueError as e:
        raise HTTPException(400, str(e))
    audit(request, "password_change", u["username"])
    return {"ok": True}                      # barcha sessiyalar bekor qilindi — qayta kirish kerak


@app.get("/api/users")
def users_list(request: Request):
    user(request, "admin")
    return auth.list_users()


@app.post("/api/users")
def users_create(request: Request, body: dict = Body(...)):
    me_ = user(request, "admin")
    try:
        out = authflow.create_user(auth, body, actor=me_["username"])
    except ValueError as e:
        raise HTTPException(400, str(e))
    audit(request, "user_create", out.get("username") or str(body.get("username", ""))[:32])
    return out


@app.post("/api/users/{username}")
def users_update(request: Request, username: str, body: dict = Body(...)):
    me_ = user(request, "admin")
    if not auth.get_user(username):
        raise HTTPException(404, "not_found")
    if username == me_["username"] and (body.get("active") == 0 or body.get("role", "admin") != "admin"):
        raise HTTPException(400, "cannot_demote_self")
    if not isinstance(body.get("full_name", ""), str) or not isinstance(body.get("role", ""), str)             or body.get("active", 1) not in (0, 1, True, False):
        raise HTTPException(400, "bad_params")
    out = {"ok": True}
    try:
        auth.update_user(username, **{k: body[k] for k in ("full_name", "role", "active") if k in body})
        if body.get("reset_password"):
            out.update(authflow.reset_code(auth, username, actor=me_["username"]))
    except ValueError as e:
        raise HTTPException(400, str(e))
    audit(request, "user_update", f"{username}:{','.join(sorted(body))}")
    return out


@app.get("/api/audit/verify")
def audit_verify(request: Request):
    user(request, "admin")
    return auth.verify_audit()


@app.get("/api/audit")
def audit_list(request: Request, limit: int = 300):
    user(request, "admin")
    return auth.audit_list(min(max(limit, 1), 2000))


# ------------------------------------------------------------------ tizim, modellar, keshlar

@app.get("/api/system")
def system(request: Request):
    u = user(request)
    from .. import sysinfo                # apparat ma'lumoti torch'siz; torch yuklanmasa — errors.torch (500 emas, PM-9)
    s = sysinfo.summary(HOME)
    s["home"] = str(HOME)
    if u["role"] != "admin":
        s.pop("home", None)
        s.get("errors", {}).pop("torch", None) if s.get("errors") else None    # texnik matn faqat administratorga
    return s


@app.get("/api/admin/diagnostics")
def diagnostics(request: Request):
    """Diagnostika paketi (jurnallar + apparat/torch/DLL hisoboti; maxfiy fayllar va bemor ma'lumotlarisiz)."""
    user(request, "admin")
    from .. import diagbundle
    data = diagbundle.build(HOME)
    audit(request, "diagnostics_bundle")
    name = f"UzLungMSKT_diagnostika_{time.strftime('%Y%m%d_%H%M')}.zip"
    return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{name}"'})


def _require_analysis():
    """Tahlil boshlanishidan oldin: PyTorch yuklangan va operativ xotira yetarli bo'lishi kerak (aks holda aniq xabar)."""
    from .. import sysinfo
    ts = sysinfo.torch_state()
    if not ts.get("ok"):
        raise HTTPException(503, "analysis_unavailable")
    free = sysinfo.ram().get("ram_free_gb")
    if free is not None and free < 1.5:
        raise HTTPException(503, "low_memory")


def _gpu_error(e: BaseException) -> bool:
    s = f"{type(e).__name__} {e}".lower()
    return any(k in s for k in ("cuda", "cudnn", "cublas", "outofmemoryerror", "no kernel image", "nvrtc"))


MODEL_LABELS = {  # yakuniy modellar (4.6-jadval): tarjima kalitlari (i18n.js, "mdl.*")
    "M1_unet3d_local": "mdl.M1", "M2_r2u3d_static_local": "mdl.M2", "dicece_s42": "mdl.M3", "adaptive_s42": "mdl.M4",
    "M5_res2unet3d_local": "mdl.M5", "M6_unetr_local": "mdl.M6", "M7_swin_unetr_local": "mdl.M7",
    "N8": "mdl.clinical", "UzLungCT_M5_val_best": "mdl.old", "tumor_local_r2u3d_v0": "mdl.pilot",
}


def _models():
    out = []
    # yakuniy modellar (4.6-jadval: M1–M7) — runs/seg/*_local va runs/abl/{dicece,adaptive}_s42 ham ko'rinadi
    cks = [*(HOME / "runs").glob("*/best.pt"), *(HOME / "runs" / "seg").glob("*_local/best.pt"),
           *(HOME / "runs" / "abl").glob("dicece_s42/best.pt"), *(HOME / "runs" / "abl").glob("adaptive_s42/best.pt"),
           *(HOME / "runs" / "seg").glob("*_msd/best.pt")]      # MSD Lung da oldindan o'qitilgan — faqat fine-tune boshlang'ich vazni
    for ck in sorted(cks):
        d = ck.parent
        cfg = {}
        if (d / "config.yaml").exists():
            import yaml
            cfg = yaml.safe_load(open(d / "config.yaml", encoding="utf-8")) or {}
        summ = json.load(open(d / "summary.json")) if (d / "summary.json").exists() else {}
        if (d / "n8.json").exists():        # SenGuard-3D: tashuvchi checkpoint ma'lumoti ko'rsatilmaydi
            cfg = {"model": "ansambl: nnU-Net×2 + TotalSegmentator + RetinaNet", "task": cfg.get("task")}; summ = {}
        out.append({"name": d.name, "label": MODEL_LABELS.get(d.name, d.name), "ckpt": str(ck), "model": cfg.get("model"), "task": cfg.get("task"),
                    "loss": cfg.get("loss"), "params": cfg.get("params"), "best_val_dice": summ.get("best_val_dice"),
                    "updated": ck.stat().st_mtime, "pretrain": d.parent.name == "seg" and d.name.endswith("_msd"), "certified": (d / "n8.json").exists()})
    return out


@app.get("/api/models")
def models(request: Request):
    user(request)
    return _models()


def _check_ckpt(ckpt):
    if ckpt not in {m["ckpt"] for m in _models()}:
        raise HTTPException(400, "bad_model")
    return ckpt


@app.get("/api/caches")
def caches(request: Request):
    user(request, "admin", "researcher")
    out = []
    for ix in sorted((HOME / "cache").glob("*/index.json")):
        j = json.load(open(ix, encoding="utf-8"))
        sp = {}
        for c in j["cases"]:
            sp[c["split"]] = sp.get(c["split"], 0) + 1
        out.append({"name": ix.parent.name, "path": str(ix.parent), "task": j.get("task"), "source": j.get("source"), "splits": sp})
    return out


@app.get("/api/dataset")
def dataset_cases_api(request: Request):
    user(request, "admin", "researcher")
    try:
        return dataset_cases()
    except HTTPException as e:                  # DATASET sozlanmagan (masalan, UzLungCT.exe o'rnatilgan kompyuter) — xato emas
        if e.detail == "dataset_missing":
            return []
        raise


def dataset_cases():
    saved = str(settings().get("dataset_root") or "")
    if not saved.strip():                          # Path("") — joriy papka; bo'sh sozlama alohida rad etiladi
        raise HTTPException(404, "dataset_missing")
    r = resolve_dataset_root(saved)                # eski sozlamadagi qo'shtirnoq/yuqori papka ham qabul qilinadi
    if not r:
        raise HTTPException(404, "dataset_missing")   # server yo'li oshkor qilinmaydi
    root = Path(r)
    try:
        ds = json.load(open(root / "dataset.json", encoding="utf-8"))
        splits = ds["splits"].items()
    except (ValueError, KeyError, AttributeError, TypeError, OSError):
        raise HTTPException(422, "dataset_invalid")   # buzilgan yoki boshqa formatdagi dataset.json — 500 emas
    out = []
    for split, items in splits:
        for it in items if isinstance(items, list) else []:
            if isinstance(it, dict) and it.get("image_1mm") and it.get("patient") and it.get("study"):
                out.append({"id": f"{it['patient']}_{it['study']}", "patient": it["patient"], "study": it["study"],
                            "split": split, "image": str(root / it["image_1mm"]),
                            "gt": str(root / it["lesion"]) if it.get("lesion") else None})
    return out


# ------------------------------------------------------------------ tahlil (xulosa chiqarish)

def _json_default(o):
    """numpy qiymatlari (bool_, float32, int64, massiv) ni oddiy Python turiga o'tkazadi — hisobotni yozishda xato bo'lmasin."""
    item = getattr(o, "item", None)
    if callable(item):
        try:
            return o.tolist() if getattr(o, "ndim", 0) else item()
        except Exception:
            pass
    raise TypeError(f"Object of type {o.__class__.__name__} is not JSON serializable")


def _ts_fn():
    from ..tsfusion import make_ts_fn
    return make_ts_fn()


def _n_slices(image):
    """Hajmdagi aksial kesimlar soni (fayl yo'li yoki SimpleITK tasviri); aniqlab bo'lmasa None."""
    import SimpleITK as sitk
    try:
        if isinstance(image, (str, Path)):
            r = sitk.ImageFileReader(); r.SetFileName(str(image)); r.ReadImageInformation(); sz = r.GetSize()
        else:
            sz = image.GetSize()
        return int(sz[2]) if len(sz) > 2 else 1
    except Exception:
        return None


def _analyze(case_dir: Path, image, ckpt: str, gt: str | None, input_meta: dict | None = None):
    import SimpleITK as sitk
    from ..sio import read_image, write_image
    from ..diagnosis import assess
    from ..infer import analyze_image, load_model
    t0 = time.time()
    input_meta = input_meta or {"source": "volume", "calibrated": True, "warnings": []}
    if (_n_slices(image) or 2) < 2:      # bitta kesim: SenGuard-3D (3D ansambl) uni qabul qilmaydi -> tushunarli xabar
        raise RuntimeError("single_slice")
    note = None
    try:
        try:
            model, cfg = load_model(ckpt)
            if os.environ.get("UZLUNGCT_TEST_FAIL_ANALYZE_CUDA") == "1":      # faqat sinov: birinchi urinishda GPU xatosi
                raise RuntimeError("CUDA error: no kernel image is available for execution on the device (sinov rejimi)")
            ext = None
            if (Path(ckpt).parent / "n8.json").exists():
                from ..n8fusion import run_n8
                ext = run_n8
            rep, ct, mask, prob = analyze_image(model, cfg, image, case_dir, ts_fn=_ts_fn(), external=ext)
        except Exception as e:
            if not _gpu_error(e):
                raise
            # videokarta xatosi (mos emas, drayver, xotira) — bir marta protsessorda qayta urinish
            import torch
            print(f"[tahlil] videokarta xatosi, protsessorda qayta urinilmoqda: {type(e).__name__}: {str(e)[:300]}", flush=True)
            model = None
            try:
                torch.cuda.empty_cache()
            except Exception:
                pass
            model, cfg = load_model(ckpt, torch.device("cpu"))
            rep, ct, mask, prob = analyze_image(model, cfg, image, case_dir, ts_fn=_ts_fn())
            note = "gpu_fallback_cpu"
    except MemoryError:
        raise RuntimeError("low_memory") from None
    if note:
        rep["device_note"] = note
    ref = read_image(case_dir / "ct_1mm.nii.gz")
    if gt:
        from ..data.prepare import to_ras_1mm
        from ..metrics import seg_report
        g = sitk.GetArrayFromImage(to_ras_1mm(read_image(gt), True))
        if g.shape == mask.shape:
            rep["vs_ground_truth"] = seg_report(mask > 0, g == 1, (1, 1, 1), g >= 2)
            gi = sitk.GetImageFromArray((g == 1).astype(np.uint8)); gi.CopyInformation(ref)
            write_image(gi, case_dir / "gt_1mm.nii.gz")
    mi = sitk.GetImageFromArray(mask.astype(np.uint8)); mi.CopyInformation(ref)
    write_image(mi, case_dir / "mask_1mm.nii.gz")
    _real = [l for l in rep["lesions"] if not l.get("approx") and l.get("tier", "asosiy") == "asosiy"]
    les_assess, patient = assess(_real, ct, input_meta.get("calibrated", True))      # detektor-yolg'iz (taxminiy) o'choqlar baholanmaydi
    for l in rep["lesions"]:
        if l.get("approx") or l.get("tier") == "qoshimcha":
            l.update({"lung_rads": None, "rads_applicable": False, "rads_notes": (["approx_detector_only"] if l.get("approx") else []) + ["qoshimcha_nomzod"]})
            if l.get("approx"):
                l["nodule_type"] = None
    if rep.get("model") in ("N8", "SenGuard-3D"):
        patient["model_prob_note"] = "sertifikatlanmagan klassifikator"
        patient["n_asosiy"] = len(_real); patient["n_qoshimcha"] = len(rep["lesions"]) - len(_real)
        if not _real and rep["lesions"]:
            patient.update({"lung_rads": None, "rads_risk_pct": None, "ai_conclusion": "faqat_qoshimcha", "worst_lesion": None,
                            "rads_notes": ["faqat_qoshimcha_nomzodlar_shifokor_korigi_shart"]})

    amap = {a["id"]: a for a in les_assess}
    for l in rep["lesions"]:
        l.update(amap.get(l["id"], {}))
    rep["patient"] = patient
    rep["input"] = input_meta
    rep["status"] = "pending_review"
    rep["seconds"] = round(time.time() - t0, 1); rep["ckpt"] = ckpt
    try:                                    # modelning o'qitish ma'lumoti hisobotda ko'rinsin (kam ma'lumotda o'qitilgan model haqida ogohlantirish uchun)
        if (Path(ckpt).parent / "n8.json").exists():
            raise ValueError("n8")
        _sm = json.loads((Path(ckpt).parent / "summary.json").read_text(encoding="utf-8"))
        rep["model_info"] = {"val_dice": float(_sm["best_val_dice"]), "n_train": int(_sm["n_train_cases"]), "n_val": int(_sm.get("n_val_cases", 0))}
    except Exception:
        pass
    with open(case_dir / "report.json", "w", encoding="utf-8") as _f:
        json.dump(rep, _f, ensure_ascii=False, indent=1, default=_json_default)
    return {"n_lesions": rep["n_lesions"], "seconds": rep["seconds"], "ai_conclusion": patient["ai_conclusion"]}


def _check_queue(u):
    """Apparatga mos navbat: tahlillar videokartada ketma-ket bajariladi (8 GB VRAM, 16 GB RAM).
    Navbat haddan oshsa server yangi so'rovni rad etadi — xotira to'lib qolmasligi uchun."""
    pend = [j for j in jobs.list("analyze") if j["status"] in ("queued", "running")]
    if len(pend) >= QUEUE_TOTAL or sum(j.get("owner") == u["username"] for j in pend) >= QUEUE_PER_USER:
        raise HTTPException(429, "busy")


@app.post("/api/analyze")
async def analyze_upload(request: Request):
    u = user(request, "admin", "radiologist", "researcher")
    try:                                   # forma qo'lda o'qiladi: Starlette standart chegarasi (1000 fayl) DICOM papkasiga yetmaydi
        files, ckpt, patient_id = await read_upload_form(request)
    except UploadFormError as e:
        raise HTTPException(400, str(e)) from None
    _check_ckpt(ckpt)
    _check_patient_for_upload(u, patient_id)
    _check_queue(u)
    _require_analysis()
    from ..io_formats import ALL_EXT
    def ok(n):
        low = Path(n.lower()).name
        return any(low.endswith(e) for e in ALL_EXT) or "." not in low     # kengaytmasiz DICOM fayllar ham
    files = [f for f in files if ok(f.filename)]                           # papkadagi begona fayllar o'tkaziladi
    if not files:
        raise HTTPException(400, "unsupported_format")
    if len(files) == 1 and files[0].filename.lower().endswith((".nii", ".nii.gz")):      # bo'sh/buzuq NIfTI darhol rad etiladi
        head = await files[0].read(4); await files[0].seek(0)
        if len(head) < 4 or (files[0].filename.lower().endswith(".gz") and head[:2] != b"\x1f\x8b"):
            raise HTTPException(400, "unsupported_format")
    names = [f.filename for f in files]
    jid = jobs.create("analyze", {"files": [Path(n).name for n in names[:20]], "n_files": len(names), "ckpt": ckpt,
                                  "patient_id": patient_id}, owner=u["username"])
    d = HOME / "jobs" / jid / "upload"; d.mkdir(parents=True)
    saved, total = [], 0
    for f in files:
        name = re.sub(r"[^\w.\-]", "_", Path(f.filename).name)[:120] or "file"
        dst = d / name
        k = 1
        while dst.exists():
            dst = d / f"{k}_{name}"; k += 1
        with open(dst, "wb") as fh:
            while True:
                chunk = await f.read(1 << 20)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    fh.close(); shutil.rmtree(HOME / "jobs" / jid, ignore_errors=True)
                    raise HTTPException(413, "too_large")
                fh.write(chunk)
        saved.append(dst)
    audit(request, "analyze_upload", jid)

    def work(case_dir):
        from ..io_formats import load_any
        img, meta = load_any(saved, case_dir / "decoded")
        res = _analyze(case_dir, img, ckpt, None, meta)
        shutil.rmtree(case_dir / "upload", ignore_errors=True)       # asl fayllar saqlanmaydi (maxfiylik)
        shutil.rmtree(case_dir / "decoded", ignore_errors=True)
        return res
    jobs.run_thread(jid, work)
    return {"job": jid}


@app.post("/api/analyze_dataset")
def analyze_dataset(request: Request, body: dict = Body(...)):
    u = user(request, "admin", "researcher")
    _check_ckpt(body.get("ckpt"))
    _check_queue(u)
    _require_analysis()
    case = next((c for c in dataset_cases() if c["id"] == body.get("case_id")), None)
    if not case:
        raise HTTPException(404, "not_found")
    if not Path(case["image"]).is_file():          # DATASET ichidagi papka qayta nomlangan/ko'chirilmagan
        raise HTTPException(409, "dataset_file_missing")
    if case["gt"] and not Path(case["gt"]).is_file():
        case = {**case, "gt": None}                # etalon yo'q bo'lsa tahlil davom etadi, faqat solishtirilmaydi
    jid = jobs.create("analyze", {"case": case["id"], "ckpt": body["ckpt"], "split": case["split"]}, owner=u["username"])
    audit(request, "analyze_dataset", jid)
    jobs.run_thread(jid, lambda d: _analyze(d, Path(case["image"]), body["ckpt"], case["gt"]))
    return {"job": jid}


# ------------------------------------------------------------------ ko'ruvchi (viewer)

@lru_cache(maxsize=3)
def _vol(path: str, mtime: float):
    import SimpleITK as sitk
    from ..sio import read_image as _ri
    return sitk.GetArrayFromImage(_ri(path))


def _load(jid, name):
    p = HOME / "jobs" / jid / name
    return _vol(str(p), p.stat().st_mtime) if p.exists() else None


WINDOWS = {"lung": (-600, 1500), "mediastinum": (40, 400), "bone": (400, 1800)}


@app.get("/api/case/{jid}/meta")
def case_meta(request: Request, jid: str):
    job_ = access_job(request, jid, "view")
    audit(request, "case_view", jid)
    p = HOME / "jobs" / jid / "report.json"
    if not p.exists():
        raise HTTPException(404, "not_ready")
    rep = json.load(open(p, encoding="utf-8"))
    ct = _load(jid, "ct_1mm.nii.gz")
    if ct is None:                                  # hisobot bor, lekin KT hajmi yo'q (o'chirilgan/buzilgan) — 500 emas
        raise HTTPException(404, "not_ready")
    rep["shape"] = list(ct.shape)
    rp = HOME / "jobs" / jid / "review.json"
    rep["review"] = json.load(open(rp, encoding="utf-8")) if rp.exists() else None
    rep["has_gt"] = (HOME / "jobs" / jid / "gt_1mm.nii.gz").exists()
    rep["owner"] = job_.get("owner")
    rep["case"] = (job_.get("params") or {}).get("case")             # taxallusli holat kodi (LC…), bo'lsa
    rep["access"] = _access_info(request.state.user, job_)
    rep["patient_reg"] = _job_patient(request.state.user, job_)
    rep.pop("ckpt", None); rep.pop("image", None)                 # server yo'llari oshkor qilinmaydi
    return rep


def _names():
    return {u["username"]: u["full_name"] for u in auth.list_users()}


def _access_info(u, job_):
    """Ko'ruvchi uchun: foydalanuvchi bu holatni qaysi huquq bilan ko'rmoqda va kimlarga yuborilgan."""
    names = _names()
    if u["role"] == "admin" or job_.get("owner") == u["username"]:
        sent = []
        for c in consults.by_job(job_["id"]):
            for r in c["recipients"]:
                sent.append({"consult_id": c["id"], "to": names.get(r["recipient"], r["recipient"]), "kind": c["kind"],
                             "state": consults_mod.state(c, r["status"]), "created": c["created"]})
        return {"mode": "owner", "can_share": True, "sent": sent}
    g = consults.grant(job_["id"], u["username"]) or {}
    mode = g.get("kind", "consult") + ("" if g.get("kind") != "handover" or g.get("status") == "accepted" else "_pending")
    return {"mode": mode, "can_share": False, "from": names.get(g.get("sender"), g.get("sender")),
            "expires": g.get("expires"), "consult_id": g.get("consult_id"), "can_review": mode == "handover"}


@app.get("/api/case/{jid}/slice")
def case_slice(request: Request, jid: str, i: int, axis: str = "axial", win: str = "lung", overlay: int = 1, gt: int = 0):
    from PIL import Image
    access_job(request, jid, "view")
    if axis not in ("axial", "coronal", "sagittal"):
        raise HTTPException(400, "bad_params")
    ct = _load(jid, "ct_1mm.nii.gz")
    if ct is None:
        raise HTTPException(404, "not_ready")
    m = _load(jid, "mask_1mm.nii.gz") if overlay else None
    g = _load(jid, "gt_1mm.nii.gz") if gt else None
    ax = {"axial": 0, "coronal": 1, "sagittal": 2}[axis]
    i = int(np.clip(i, 0, ct.shape[ax] - 1))
    take = lambda v: np.take(v, i, axis=ax)
    c, w = WINDOWS.get(win, WINDOWS["lung"])
    s = np.clip((take(ct).astype(np.float32) - (c - w / 2)) / w, 0, 1)
    rgb = np.stack([s, s, s], -1)
    if m is not None:
        mm = take(m) > 0
        rgb[mm] = rgb[mm] * 0.45 + np.array([1.0, 0.25, 0.2]) * 0.55
        edge = mm ^ _erode(mm)
        rgb[edge] = [1.0, 0.1, 0.1]
    if g is not None:
        gg = take(g) > 0
        rgb[gg ^ _erode(gg)] = [0.1, 0.9, 0.3]
    img = (rgb * 255).astype(np.uint8)
    if ax == 0:
        img = img[::-1]                      # RAS → radiologik ko'rinish (bemor oldi tepada)
    else:
        img = img[::-1]                      # yuqori (S) tepada
    buf = io.BytesIO(); Image.fromarray(img).save(buf, "PNG", optimize=False)
    return Response(buf.getvalue(), media_type="image/png", headers={"Cache-Control": "private, max-age=600"})


def _erode(m):
    from scipy import ndimage as nd
    return nd.binary_erosion(m)


FINAL_DX = ("lung_cancer_suspected", "benign_lesion", "follow_up", "no_pathology", "other")


PURGE_DAYS = 30


def purge_deleted(now=None):
    """deleted_jobs ichidagi o'chirilganiga PURGE_DAYS kundan oshgan tahlillarni butunlay o'chiradi. Nom: <jid>__<unix vaqt>."""
    root = HOME / "deleted_jobs"
    if not root.is_dir():
        return 0
    now = now or time.time(); n = 0
    for d in root.iterdir():
        m = re.fullmatch(r"(.+)__(\d{9,11})", d.name)
        if d.is_dir() and m and now - int(m.group(2)) > PURGE_DAYS * 86400 and (root in d.resolve().parents):
            shutil.rmtree(d, ignore_errors=True)
            if not d.exists():
                n += 1
                try:
                    auth.audit("system", "-", "case_purge", m.group(1), True)
                except Exception:
                    pass
    return n


def _purge_loop():
    import threading
    try:
        purge_deleted()
    except Exception as e:
        print(f"[tozalash] xato: {e}", flush=True)
    t = threading.Timer(86400, _purge_loop); t.daemon = True; t.start()


_purge_loop()


@app.post("/api/case/{jid}/delete")
def case_delete(request: Request, jid: str, body: dict = Body(...)):
    u = user(request, "admin", "radiologist", "researcher")
    m = access_job(request, jid, "delete")                 # faqat egasi yoki admin (konsultatsiya qabul qiluvchisi emas)
    if m.get("kind") != "analyze":
        raise HTTPException(400, "bad_kind")
    if (m.get("status") or m.get("state")) in ("running", "queued", "pending"):
        raise HTTPException(409, "job_running")
    if not isinstance(body, dict) or (body.get("username") or "").strip().lower() != u["username"] or not isinstance(body.get("password"), str):
        audit(request, "case_delete_reauth", jid, ok=False)
        raise HTTPException(403, "reauth_failed")
    res = auth.login_ex(u["username"], body["password"], _ip(request))
    if res.get("token"):
        auth.logout(res["token"])                          # tasdiq uchun yaratilgan sessiya darhol yopiladi
    if res.get("error") or not res.get("token"):
        audit(request, "case_delete_reauth", jid, ok=False)
        raise HTTPException(429 if res.get("error") in ("locked", "too_many_attempts") else 403, "reauth_failed")
    src = HOME / "jobs" / jid
    dst = HOME / "deleted_jobs" / f"{jid}__{int(time.time())}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    audit(request, "case_delete", jid)
    try:
        purge_deleted()
    except Exception:
        pass
    return {"ok": True}


@app.post("/api/case/{jid}/review")
def save_review(request: Request, jid: str, body: dict = Body(...)):
    """Radiologning yakuniy qarori. final_diagnosis berilsa, hisobot holati 'final' ga o'tadi.
    Radiolog ismi sessiyadan olinadi (qo'lda kiritib bo'lmaydi); yakuniy qarorni faqat radiolog yoki admin beradi."""
    u = user(request)
    access_job(request, jid, "review")
    d = HOME / "jobs" / jid
    if not (d / "report.json").exists():
        raise HTTPException(404, "not_ready")
    body = {k: body.get(k) for k in ("lesions", "conclusion", "final_diagnosis", "final_lung_rads", "recommendation")}
    les = body["lesions"] or []
    if not isinstance(les, list) or not all(isinstance(l, dict) and isinstance(l.get("id"), int) and not isinstance(l.get("id"), bool) for l in les)             or not all(body.get(k) is None or isinstance(body.get(k), str) for k in ("final_diagnosis", "final_lung_rads")):
        raise HTTPException(400, "bad_params")
    if body.get("final_lung_rads") not in (None, "", "1", "2", "3", "4A", "4B", "4X"):
        raise HTTPException(400, "bad_params")
    body["lesions"] = [{"id": int(l.get("id")), "decision": l.get("decision") if l.get("decision") in ("tumor", "node", "uncertain", "reject") else None,
                        "note": str(l.get("note") or "")[:500]} for l in (body["lesions"] or [])]
    for k in ("conclusion", "recommendation"):
        body[k] = str(body.get(k) or "")[:4000]
    body["saved"] = time.strftime("%Y-%m-%d %H:%M"); body["radiologist"] = u["full_name"]; body["radiologist_login"] = u["username"]
    final = body.get("final_diagnosis") in FINAL_DX
    if final and u["role"] not in ("radiologist", "admin"):
        raise HTTPException(403, "radiologist_required")
    rp0 = d / "report.json"
    if rp0.exists() and json.load(open(rp0, encoding="utf-8")).get("status") == "final" and u["role"] != "admin":
        raise HTTPException(409, "already_final")              # tasdiqlangan hisobotni faqat admin o'zgartira oladi
    json.dump(body, open(d / "review.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    rp = d / "report.json"
    rep = json.load(open(rp, encoding="utf-8")); rep["status"] = "final" if final else "pending_review"
    json.dump(rep, open(rp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    allp = HOME / "reviews.csv"; new = not allp.exists()
    with open(allp, "a", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, delimiter=";")
        if new:
            w.writerow(["job", "time", "radiologist", "lesion", "ai_lung_rads", "decision", "final_diagnosis", "final_lung_rads", "recommendation"])
        amap = {l["id"]: l for l in rep.get("lesions", [])}
        for l in body.get("lesions", []):
            w.writerow([_csv_safe(x) for x in (jid, body["saved"], body["radiologist"], l.get("id"), amap.get(l.get("id"), {}).get("lung_rads"),
                        l.get("decision"), body.get("final_diagnosis"), body.get("final_lung_rads"), body.get("recommendation"))])
    audit(request, "review_final" if final else "review_draft", jid)
    return {"ok": True, "status": rep["status"]}


@app.get("/api/case/{jid}/download/{name}")
def download(request: Request, jid: str, name: str):
    access_job(request, jid, "download_report" if name == "report.json" else "download_data")
    if name not in ("mask.nii.gz", "report.json", "ct_1mm.nii.gz", "mask_1mm.nii.gz"):
        raise HTTPException(400, "bad_params")
    f = HOME / "jobs" / jid / name
    if not f.is_file():
        raise HTTPException(404, "not_found")
    audit(request, "download", f"{jid}/{name}")
    return FileResponse(f, filename=f"{jid}_{name}")


def _report_consults(request: Request, m: dict, jid: str):
    """Hisobotga kiradigan konsultatsiyalar: faqat foydalanuvchi ko'rishga haqli bo'lganlari (qaytarib olinganlarsiz)."""
    u = request.state.user; names = _names()
    cons = []
    for c in consults.by_job(jid):
        mine = u["role"] == "admin" or m.get("owner") == u["username"] or any(r["recipient"] == u["username"] for r in c["recipients"])
        if c.get("revoked") or not mine:
            continue
        cons.append({"kind": c["kind"], "created": c["created"], "from": names.get(c["sender"], c["sender"]),
                     "to": [names.get(r["recipient"], r["recipient"]) for r in c["recipients"]],
                     "messages": [{"author": names.get(x["author"], x["author"]), "created": x["created"], "text": x["text"]}
                                  for x in c["messages"]]})
    return cons


@app.post("/api/case/{jid}/report.pdf")
def report_pdf(request: Request, jid: str, body: dict = Body(...)):
    """Hisobotni PDF fayl sifatida yuklab olish. Bemor F.I.Sh. va tug'ilgan sanasi faqat shu so'rov tanasida keladi,
    faqat PDF ga yoziladi va hech qayerda saqlanmaydi (DB, audit, jurnal, fayl nomi). GET yo'li yo'q (405)."""
    from .patient import parse
    from .report_pdf import render_report_pdf
    m = access_job(request, jid, "report")
    if not (HOME / "jobs" / jid / "report.json").exists():
        raise HTTPException(404, "not_found")
    lang = body.get("lang") if body.get("lang") in ("uz", "en", "ru") else "uz"
    reg = _job_patient(request.state.user, m)
    if reg:                                      # reyestrdagi bemor: ma'lumot serverdan olinadi, tanadagisi e'tiborga olinmaydi
        pt = parse({"last": reg["last"], "first": reg["first"], "middle": reg["middle"], "birth": reg["birth"]})
        pt["id"] = reg["id"]
    else:
        pt = parse(body.get("patient"))
    if pt is None:
        raise HTTPException(400, "bad_patient")
    fname = f"UzLungMSKT_hisobot_{reg['id']}_{jid}_{lang}.pdf" if reg else f"UzLungMSKT_hisobot_{jid}_{lang}.pdf"
    try:
        data = render_report_pdf(HOME / "jobs" / jid, jobs.get(jid), settings(), lang, _report_consults(request, m, jid), patient=pt)
    except Exception as e:      # istisno matni jurnalga yozilmaydi: unda bemor ma'lumoti bo'lishi mumkin
        print(f"report.pdf {jid}: {type(e).__name__}", flush=True)
        raise HTTPException(500, "pdf_failed") from None
    finally:
        del pt, body, reg
    audit(request, "download", f"{jid}/report.pdf")
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"', "Cache-Control": "no-store"})


@app.get("/api/case/{jid}/report", response_class=HTMLResponse)
def report_html(request: Request, jid: str, lang: str = "uz"):
    from .report import render_report
    m = access_job(request, jid, "report")
    audit(request, "report_view", jid)
    if not (HOME / "jobs" / jid / "report.json").exists():
        raise HTTPException(404, "not_found")
    return render_report(HOME / "jobs" / jid, jobs.get(jid), settings(), lang if lang in ("uz", "en", "ru") else "uz",
                         _report_consults(request, m, jid), patient=_job_patient(request.state.user, m))


# ------------------------------------------------------------------ vazifalar

def _public_job(m, u):
    m = dict(m)
    # xato sababi: faqat ma'lum kod (masalan «not_3d»); istisno matni (yo'llar, ichki tafsilotlar) oshkor qilinmaydi
    if m.get("error") is not None:
        e = str(m["error"])
        m["error"] = e if re.fullmatch(r"[a-z0-9_]{3,40}", e) else "internal"
    if u["role"] != "admin":
        m["params"] = {k: v for k, v in m.get("params", {}).items() if k in ("name", "case", "files", "n_files", "split", "model", "loss", "epochs", "task", "source", "patient_id")}
    return m


@app.get("/api/jobs")
def list_jobs(request: Request, kind: str | None = None):
    u = user(request)
    out = []
    shared = consults.shared_job_ids(u["username"]) if u["role"] in ("radiologist", "admin") else set()
    for m in jobs.list(kind):
        if u["role"] == "admin" or m.get("owner") == u["username"] or (u["role"] == "researcher" and m["kind"] != "analyze"):
            out.append(_public_job(m, u))
        elif m["id"] in shared and m["kind"] == "analyze":                # menga yuborilgan holat (konsultatsiya)
            pj = _public_job(m, u)
            pj["params"] = {k: v for k, v in pj["params"].items() if k in ("case", "split", "patient_id")}
            pj["shared_with_me"] = True
            out.append(pj)
    for pj in out:
        pid = (pj.get("params") or {}).get("patient_id")
        p = patients.get(pid) if pid else None
        if pid:
            pj["patient"] = {"id": pid, "fio": patients_mod.fio(p) if p else None}
    return out[:500]


@app.get("/api/jobs/{jid}")
def job(request: Request, jid: str):
    u = user(request)
    if not JID_RE.match(jid):
        raise HTTPException(400, "bad_id")
    m = jobs.get(jid)
    if not m or not (u["role"] == "admin" or m.get("owner") == u["username"] or (u["role"] == "researcher" and m["kind"] != "analyze")):
        raise HTTPException(404, "not_found")
    m = _public_job(m, u)
    m["log"] = jobs.log_tail(jid) if u["role"] in ("admin", "researcher") else ""
    return m


@app.post("/api/jobs/{jid}/stop")
def stop(request: Request, jid: str):
    user(request, "admin", "researcher")
    if not JID_RE.match(jid):
        raise HTTPException(400, "bad_id")
    audit(request, "job_stop", jid)
    return {"stopped": jobs.stop(jid)}


@app.post("/api/prepare")
def prepare(request: Request, body: dict = Body(...)):
    """body: {source: local|msd|pairs, root, task, name}"""
    u = user(request, "admin", "researcher")
    if not NAME_RE.match(body.get("name", "")) or body.get("source") not in ("local", "msd", "pairs") or body.get("task", "tumor") not in ("tumor", "lung"):
        raise HTTPException(400, "bad_params")
    root = str(body.get("root") or "").strip().strip('"').strip("'").strip()
    if not root or not Path(root).exists():          # Path("") — joriy papka («.»), shuning uchun bo'sh qiymat alohida rad etiladi
        raise HTTPException(400, "bad_path")
    if body.get("source") == "local":                # mahalliy DATASET: yuqori papka yoki dataset.json yo'li ham qabul qilinadi
        root = resolve_dataset_root(root)
        if not root:
            raise HTTPException(400, "dataset_missing")
    if not Path(root).is_dir():
        raise HTTPException(400, "bad_path")
    body["root"] = root
    out = HOME / "cache" / body["name"]
    jid = jobs.create("prepare", {**body, "out": str(out)}, owner=u["username"])
    audit(request, "prepare", jid)
    jobs.run_process(jid, ["-m", "uzlungct.data.prepare", "--source", body["source"], "--root", body["root"],
                           "--out", str(out), "--task", body.get("task", "tumor")], cwd=str(REPO))
    return {"job": jid}


@app.post("/api/train")
def train(request: Request, body: dict = Body(...)):
    """body: {name, cache, model, loss, epochs, init?, fold?, patch?, batch?, samples_per_epoch?, lr?}"""
    u = user(request, "admin", "researcher")
    if not NAME_RE.match(body.get("name", "")):
        raise HTTPException(400, "bad_params")
    if not str(body.get("cache") or "").strip():
        raise HTTPException(400, "cache_required")
    body["cache"] = str(_under(body.get("cache", ""), HOME / "cache"))
    if not Path(body["cache"]).is_dir():
        raise HTTPException(400, "cache_required")
    if body.get("init"):
        body["init"] = str(_under(body["init"], HOME / "runs"))
    if body.get("model") not in ("unet3d", "r2u3d_static", "r2u3d_dynamic", "res2unet3d", "unetr", "swin_unetr"):
        raise HTTPException(400, "bad_params")
    if body.get("loss", "dicece") not in ("dice", "dicece", "focal", "tversky", "focal_tversky", "ell", "unified_focal", "adaptive"):
        raise HTTPException(400, "bad_params")
    try:                                              # raqam bo'lmagan qiymat — 400 (500 emas)
        for k in ("epochs", "fold", "batch", "samples_per_epoch", "val_every", "patience"):
            if body.get(k) not in (None, ""):
                body[k] = int(body[k])
        if body.get("lr") not in (None, ""):
            body["lr"] = float(body["lr"])
        patch_ = [int(v) for v in body["patch"]] if body.get("patch") else None
    except (TypeError, ValueError):
        raise HTTPException(400, "bad_params") from None
    if not 1 <= (100 if body.get("epochs") in (None, "") else body["epochs"]) <= 5000:
        raise HTTPException(400, "bad_params")
    out = HOME / "runs" / body["name"]
    args = ["-m", "uzlungct.train_seg", "--cache", body["cache"], "--out", str(out), "--model", body["model"],
            "--loss", body.get("loss", "dicece"), "--epochs", str(body.get("epochs", 100)), "--task", body.get("task", "tumor")]
    for k in ("init", "fold", "batch", "samples_per_epoch", "lr", "val_every", "patience"):
        if body.get(k) not in (None, ""):
            args += [f"--{k}", str(body[k])]
    if patch_:
        args += ["--patch", *[str(v) for v in patch_]]
    jid = jobs.create("train", {**body, "out": str(out)}, owner=u["username"])
    audit(request, "train", jid)
    jobs.run_process(jid, args, cwd=str(REPO))
    return {"job": jid}


@app.get("/api/train/{jid}/curve")
def curve(request: Request, jid: str):
    user(request, "admin", "researcher")
    if not JID_RE.match(jid):
        raise HTTPException(400, "bad_id")
    m = jobs.get(jid)
    if not m or m.get("kind") != "train" or not (m.get("params") or {}).get("out"):
        raise HTTPException(404, "not_found")
    p = Path(m["params"]["out"]) / "log.csv"
    if not p.exists():
        return []
    return list(csv.DictReader(open(p, encoding="utf-8")))


@app.post("/api/evaluate")
def evaluate(request: Request, body: dict = Body(...)):
    """body: {ckpts: [...], cache, split, name}"""
    u = user(request, "admin", "researcher")
    body["ckpts"] = [_check_ckpt(c) for c in body.get("ckpts", [])]
    if any((Path(c).parent / "n8.json").exists() for c in body["ckpts"]):    # SenGuard-3D ansambl: bu modul uni baholay olmaydi (tashuvchi fayl baholanib qolardi)
        raise HTTPException(400, "ensemble_not_evaluable")
    body["cache"] = str(_under(body.get("cache", ""), HOME / "cache"))
    split = body.get("split", "val")
    if split not in ("test", "val", "train") or not body["ckpts"]:
        raise HTTPException(400, "bad_params")
    # sinov to'plami: faqat aniq tasdiq bilan; har bir ishlatilish alohida jurnalga yoziladi (EXPERIMENT_RULES)
    if split == "test" and body.get("confirm_test") is not True:
        raise HTTPException(400, "test_confirm_required")
    name = body.get("name") or time.strftime("eval_%Y%m%d_%H%M")
    if not NAME_RE.match(name):
        raise HTTPException(400, "bad_params")
    out = HOME / "results" / name
    jid = jobs.create("evaluate", {**body, "split": split, "out": str(out)}, owner=u["username"])
    if split == "test":
        logf = HOME / "results" / "test_usage_platform.json"
        log = json.load(open(logf, encoding="utf-8")) if logf.exists() else []
        log.append({"t": time.strftime("%Y-%m-%d %H:%M:%S"), "user": u["username"], "job": jid,
                    "models": [Path(c).parent.name for c in body["ckpts"]], "cache": Path(body["cache"]).name})
        logf.write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    audit(request, "evaluate", f"{jid} ({split})")
    jobs.run_process(jid, ["-m", "uzlungct.evaluate", "--ckpt", *body["ckpts"], "--cache", body["cache"],
                           "--split", split, "--out", str(out)], cwd=str(REPO))
    return {"job": jid}


# ------------------------------------------------------------------ statistika va monitoring

_STATS_CACHE = {"key": None, "t": 0.0, "val": None}


def _stats_rows():
    """collect() natijasi 30 soniya keshlanadi; jobs papkasi o'zgarsa (yangi vazifa) darhol yangilanadi."""
    root = HOME / "jobs"
    key = (root.stat().st_mtime, sum(1 for _ in root.iterdir())) if root.exists() else None
    now = time.time()
    if _STATS_CACHE["val"] is None or _STATS_CACHE["key"] != key or now - _STATS_CACHE["t"] > 30:
        _STATS_CACHE.update(key=key, t=now, val=stats_mod.collect(HOME))
    return _STATS_CACHE["val"]


def _stats(request: Request, granularity: str, from_: str | None, to: str | None):
    import datetime as _dt
    u = user(request)
    try:
        d0 = _dt.date.fromisoformat(from_) if from_ else None
        d1 = _dt.date.fromisoformat(to) if to else None
    except ValueError:
        raise HTTPException(400, "bad_params")
    rows, skipped = _stats_rows()
    ev = consults.events()
    if u["role"] == "radiologist":                         # radiolog — faqat o'zining va o'ziga yuborilgan holatlar
        mine = consults.shared_job_ids(u["username"])
        rows = [r for r in rows if r["owner"] == u["username"] or r["reviewer"] == u["username"] or r["id"] in mine]
        ev = [e for e in ev if e["sender"] == u["username"]]
    try:
        agg = stats_mod.aggregate(rows, granularity, d0, d1, ev, by_user=u["role"] == "admin")
    except ValueError:
        raise HTTPException(400, "bad_params")
    agg["skipped"] = skipped
    return agg


@app.get("/api/stats")
def stats_api(request: Request, granularity: str = "month", to: str | None = None):
    agg = _stats(request, granularity, request.query_params.get("from"), to)
    audit(request, "stats_view", f"{granularity}:{agg['from']}..{agg['to']}")
    return agg


@app.get("/api/stats.csv")
def stats_csv(request: Request, granularity: str = "month", to: str | None = None):
    user(request, "admin", "researcher")
    agg = _stats(request, granularity, request.query_params.get("from"), to)
    buf = io.StringIO(); w = csv.writer(buf, delimiter=";")
    for row in stats_mod.to_csv_rows(agg):
        w.writerow([_csv_safe(x) for x in row])
    audit(request, "download", "stats.csv")
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="uzlungct_stats_{granularity}.csv"'})


# ------------------------------------------------------------------ bemor reyestri (PM-3)
# Shaxsiy ma'lumot faqat patients.db da (shifrlangan) va faqat javob tanasida uzatiladi: URL, audit, jurnal, job.json ga
# faqat 6 xonali ID yoziladi. Qidiruv so'zi ham URL ga tushmasligi uchun qidiruv POST orqali.
_PT_RATE: dict = {}                 # foydalanuvchi → so'nggi qidiruv vaqtlari
_PT_GRANT: dict = {}                # foydalanuvchi → {patient_id: muddat} (ro'yxatga olgan / tanlagan bemorlar)
PT_GRANT_SEC = 12 * 3600
SEARCH_PER_MIN = 60


def _pt_grant(u, pid):
    g = _PT_GRANT.setdefault(u["username"], {}); now = time.time()
    for k in [k for k, v in g.items() if v < now]:
        g.pop(k, None)
    g[pid] = now + PT_GRANT_SEC


def _visible_jobs(u):
    """Foydalanuvchi ko'ra oladigan tahlillar: admin — hammasi; egasi; konsultatsiya grant."""
    shared = consults.shared_job_ids(u["username"]) if u["role"] in ("radiologist", "admin") else set()
    out = []
    for m in jobs.list("analyze"):
        if u["role"] == "admin" or m.get("owner") == u["username"]:
            out.append((m, "owner"))
        elif m["id"] in shared:
            out.append((m, "consult"))
    return out


def _pt_access(u):
    """patient_id → 'full' (to'liq telefon) yoki 'consult' (niqoblangan)."""
    acc = {}
    for m, how in _visible_jobs(u):
        pid = (m.get("params") or {}).get("patient_id")
        if pid and acc.get(pid) != "full":
            acc[pid] = "full" if how == "owner" else "consult"
    now = time.time()
    for pid, exp in _PT_GRANT.get(u["username"], {}).items():
        if exp > now:
            acc[pid] = "full"
    if u["role"] == "admin":
        acc = {pid: "full" for pid in patients._all()}
    return acc


def _job_patient(u, m):
    """Tahlilga biriktirilgan bemor (reyestrdan) — tahlilga kirish huquqi allaqachon tekshirilgan."""
    pid = (m.get("params") or {}).get("patient_id")
    p = patients.get(pid) if pid else None
    if not p:
        return None
    full = u["role"] == "admin" or m.get("owner") == u["username"]
    return patients_mod.public(p, full_phone=full)


def _check_patient_for_upload(u, pid):
    if not pid:
        raise HTTPException(400, "bad_patient_id")
    if not re.fullmatch(r"\d{6}", pid):
        raise HTTPException(400, "bad_patient_id")
    st = patients.status(pid)
    if st == "deleted":
        raise HTTPException(400, "patient_deleted")
    if st != "ok" or _pt_access(u).get(pid) != "full":       # ID ni terib begona bemorni biriktirib bo'lmaydi
        raise HTTPException(400, "bad_patient_id")


def _pt_body(body):
    try:
        return patients_mod.clean(body)
    except patients_mod.PatientError as e:
        raise HTTPException(400, str(e)) from None


def _pt_jobs(u, pid, acc_jobs=None):
    out = []
    for m, how in (acc_jobs if acc_jobs is not None else _visible_jobs(u)):
        if (m.get("params") or {}).get("patient_id") != pid:
            continue
        rep = {}
        rp = HOME / "jobs" / m["id"] / "report.json"
        if rp.exists():
            try:
                rep = json.load(open(rp, encoding="utf-8"))
            except Exception:
                rep = {}
        pt = rep.get("patient") or {}
        out.append({"jid": m["id"], "created": m.get("created"), "status": m["status"], "owner": m.get("owner"),
                    "shared_with_me": how == "consult", "report_status": rep.get("status"), "lung_rads": pt.get("lung_rads"),
                    "ai_conclusion": pt.get("ai_conclusion"), "n_lesions": rep.get("n_lesions")})
    out.sort(key=lambda j: j["created"] or 0, reverse=True)
    return out


def _pt_item(u, p, how, acc_jobs=None):
    d = patients_mod.public(p, full_phone=how == "full")
    d["jobs"] = _pt_jobs(u, p["id"], acc_jobs)
    d["similar"] = [x for x in patients.similar(p["id"]) if x in _pt_access(u)] if how == "full" else []
    d["can_edit"] = how == "full"; d["can_delete"] = u["role"] == "admin"
    return d


@app.post("/api/patients")
def patient_register(request: Request, body: dict = Body(...)):
    u = user(request, "admin", "radiologist", "researcher")
    if body.get("consent") is not True:
        raise HTTPException(400, "consent_required")
    p = _pt_body(body)
    try:
        pid, existing, cand = patients.register(p, u["username"], force_new=body.get("force_new") is True)
    except patients_mod.PatientError as e:
        raise HTTPException(400, str(e)) from None
    if cand:
        acc = _pt_access(u)
        items = []
        for c in cand:
            q = patients.get(c)
            it = {"id": c, "phone_masked": patients_mod.mask_phone(q.get("phone")) if q else None}
            if c in acc:
                it["n_jobs"] = len(_pt_jobs(u, c))
            items.append(it)
        audit(request, "patient_duplicate", None)
        return JSONResponse({"detail": "possible_duplicate", "candidates": items}, status_code=409)
    _pt_grant(u, pid)
    audit(request, "patient_use" if existing else "patient_register", pid)
    if patients.count() >= patients_mod.WARN_AT:
        print("DIQQAT: bemor reyestri to'lib bormoqda (6 xonali ID lar)", flush=True)
    return {"id": pid, "existing": existing, "patient": patients_mod.public(patients.get(pid))}


@app.post("/api/patients/{pid}/use")
def patient_use(request: Request, pid: str, body: dict = Body(default={})):
    """Mavjud bemorni tanlash: ko'rish huquqi bo'lsa — darhol; bo'lmasa F.I.Sh. va sana mos kelishi shart (dublikat oynasidan)."""
    u = user(request, "admin", "radiologist", "researcher")
    if not re.fullmatch(r"\d{6}", pid) or patients.status(pid) != "ok":
        raise HTTPException(404, "not_found")
    p = patients.get(pid)
    if _pt_access(u).get(pid) != "full":
        q = _pt_body({**body, "phone": None})
        if not (patients._keys({**q, "phone": None})[1] == patients._keys({**p, "phone": None})[1]):
            audit(request, "access_denied", pid, False)
            raise HTTPException(404, "not_found")
        if body.get("phone"):
            try:
                ph = patients_mod.norm_phone(body.get("phone"), body.get("region") or "UZ")
            except patients_mod.PatientError as e:
                raise HTTPException(400, str(e)) from None
            if body.get("update_phone") is True and ph:
                patients.update(pid, {**p, "phone": ph}, u["username"]); p = patients.get(pid)
    _pt_grant(u, pid)
    audit(request, "patient_use", pid)
    return {"id": pid, "existing": True, "patient": patients_mod.public(p)}


@app.post("/api/patients/search")
def patient_search(request: Request, body: dict = Body(...)):
    u = user(request, "admin", "radiologist", "researcher")
    now = time.time(); r = [t for t in _PT_RATE.get(u["username"], []) if t > now - 60]
    if len(r) >= SEARCH_PER_MIN:
        raise HTTPException(429, "too_many")
    r.append(now); _PT_RATE[u["username"]] = r
    q = str(body.get("q") or "")[:100]
    acc = _pt_access(u)
    st = patients.status(q.strip()) if re.fullmatch(r"\s*\d{6}\s*", q) else None
    if isinstance(st, tuple):                   # birlashtirilgan ID → yangi ID
        q = st[1]
    try:
        hits = patients.search(q, allowed=set(acc))
    except patients_mod.KeyErrorPatient:
        raise HTTPException(500, "patient_key_error") from None
    vj = _visible_jobs(u)
    res = [_pt_item(u, p, acc[p["id"]], vj) for p in hits]
    audit(request, "patient_search", f"n={len(res)}")
    return res


@app.get("/api/patients/{pid}")
def patient_card(request: Request, pid: str):
    u = user(request, "admin", "radiologist", "researcher")
    acc = _pt_access(u)
    p = patients.get(pid) if re.fullmatch(r"\d{6}", pid or "") else None
    if not p or pid not in acc:
        raise HTTPException(404, "not_found")
    audit(request, "patient_view", pid)
    return _pt_item(u, p, acc[pid])


@app.post("/api/patients/{pid}")
def patient_update(request: Request, pid: str, body: dict = Body(...)):
    u = user(request, "admin", "radiologist", "researcher")
    if not re.fullmatch(r"\d{6}", pid or "") or not patients.get(pid) or _pt_access(u).get(pid) != "full":
        raise HTTPException(404, "not_found")
    try:
        ok = patients.update(pid, _pt_body(body), u["username"])
    except patients_mod.PatientError as e:
        raise HTTPException(409 if str(e) == "patient_exists" else 400, str(e)) from None
    if not ok:
        raise HTTPException(404, "not_found")
    audit(request, "patient_update", pid)
    return patients_mod.public(patients.get(pid))


@app.delete("/api/patients/{pid}")
def patient_delete(request: Request, pid: str):
    user(request, "admin")
    if not re.fullmatch(r"\d{6}", pid or "") or not patients.delete(pid, request.state.user["username"]):
        raise HTTPException(404, "not_found")
    audit(request, "patient_delete", pid)
    return {"ok": True}


@app.post("/api/patients/{pid}/merge")
def patient_merge(request: Request, pid: str, body: dict = Body(...)):
    """Admin: «ehtimol bir xil bemor» yozuvlarini birlashtirish — pid ning tahlillari body.into ga o'tadi."""
    user(request, "admin")
    dst = str(body.get("into") or "")
    if pid == dst or not patients.get(pid) or not patients.get(dst):
        raise HTTPException(400, "bad_patient_id")
    for m in jobs.list("analyze"):
        if (m.get("params") or {}).get("patient_id") == pid:
            jobs.update(m["id"], params={**m["params"], "patient_id": dst})
    patients.merge(pid, dst, request.state.user["username"])
    audit(request, "patient_merge", f"{pid}->{dst}")
    return {"ok": True, "id": dst}


@app.post("/api/jobs/{jid}/patient")
def job_attach_patient(request: Request, jid: str, body: dict = Body(...)):
    """PM-3 dan oldingi tahlilni bemorga biriktirish (egasi yoki admin)."""
    m = own_job(request, jid)
    u = request.state.user
    if m["kind"] != "analyze":
        raise HTTPException(400, "bad_params")
    pid = str(body.get("patient_id") or "")
    old = (m.get("params") or {}).get("patient_id")
    if old and patients.status(old) == "ok" and u["role"] != "admin":
        raise HTTPException(409, "already_attached")         # biriktirilgan tahlilni faqat administrator boshqa bemorga o'tkazadi
    _check_patient_for_upload(u, pid)
    jobs.update(jid, params={**(m.get("params") or {}), "patient_id": pid})
    audit(request, "job_patient_attach", jid)
    return {"ok": True}


# ------------------------------------------------------------------ konsultatsiyalar (shifokorlar o'rtasida hisobot almashish)

def _consult_item(c, me, names, my_status=None, unread=False, with_messages=False):
    """API uchun bitta konsultatsiya yozuvi. Fayl yo'llari va yuklangan fayl nomlari qaytarilmaydi."""
    m = jobs.get(c["job_id"]) or {}
    rep = {}
    rp = HOME / "jobs" / c["job_id"] / "report.json"
    if rp.exists():
        try:
            rep = json.load(open(rp, encoding="utf-8"))
        except Exception:
            rep = {}
    pt = rep.get("patient") or {}
    last = consults.last_message(c["id"])
    recs = c.get("recipients") or []
    item = {"id": c["id"], "job_id": c["job_id"], "case": (m.get("params") or {}).get("case"), "kind": c["kind"],
            "priority": c["priority"], "created": c["created"], "expires": c["expires"], "message": c["message"],
            "sender": c["sender"], "sender_name": names.get(c["sender"], c["sender"]),
            "recipients": [{"username": r["recipient"], "full_name": names.get(r["recipient"], r["recipient"]),
                            "state": consults_mod.state(c, r["status"])} for r in recs],
            "state": consults_mod.state(c, my_status) if my_status is not None else
            ("revoked" if c.get("revoked") else ("expired" if c["expires"] <= time.time() else "active")),
            "ai_conclusion": pt.get("ai_conclusion"), "lung_rads": pt.get("lung_rads"), "report_status": rep.get("status"),
            "last_message": {"author": names.get(last["author"], last["author"]), "text": last["text"][:160], "created": last["created"]} if last else None,
            "unread": unread, "mine": c["sender"] == me}
    pid = (m.get("params") or {}).get("patient_id")
    if pid:                                         # reyestrdagi bemor: ID va F.I.Sh. (telefon yo'q) — faqat javob tanasida
        p = patients.get(pid)
        item["patient"] = {"id": pid, "fio": patients_mod.fio(p) if p else None}
    if with_messages:
        item["messages"] = [{"author": x["author"], "author_name": names.get(x["author"], x["author"]), "text": x["text"],
                             "created": x["created"]} for x in c.get("messages", [])]
    return item


def _consult_or_404(request, cid):
    c = consults.get(cid)
    u = request.state.user
    if not c:
        raise HTTPException(404, "not_found")
    rec = next((r for r in c["recipients"] if r["recipient"] == u["username"]), None)
    if not (c["sender"] == u["username"] or rec or u["role"] == "admin"):
        audit(request, "access_denied", f"consult:{cid}", False)
        raise HTTPException(404, "not_found")
    return c, rec


@app.get("/api/consult/recipients")
def consult_recipients(request: Request):
    u = user(request, "admin", "radiologist")
    return [{"username": x["username"], "full_name": x["full_name"], "role": x["role"]} for x in auth.list_users()
            if x["active"] and x["role"] in ("radiologist", "admin") and x["username"] != u["username"]]


@app.post("/api/consult")
def consult_send(request: Request, body: dict = Body(...)):
    u = user(request, "admin", "radiologist")
    jid = str(body.get("job_id") or "")
    m = own_job(request, jid)                                           # faqat egasi yoki admin yuboradi
    if m["kind"] != "analyze" or m["status"] != "done" or not (HOME / "jobs" / jid / "report.json").exists():
        raise HTTPException(400, "bad_params")
    kind, prio = body.get("kind", "consult"), body.get("priority", "normal")
    msg = body.get("message") or ""
    try:
        days = int(body.get("expires_days", 30))
    except (TypeError, ValueError):
        raise HTTPException(400, "bad_params")
    recs = body.get("recipients") or []
    if (kind not in consults_mod.KINDS or prio not in consults_mod.PRIORITIES or not isinstance(msg, str)
            or len(msg) > consults_mod.MAX_MESSAGE or not 1 <= days <= 90 or not isinstance(recs, list)):
        raise HTTPException(400, "bad_params")
    recs = list(dict.fromkeys(str(r).strip().lower() for r in recs))
    if not 1 <= len(recs) <= consults_mod.MAX_RECIPIENTS or (kind == "handover" and len(recs) != 1):
        raise HTTPException(400, "bad_recipients")
    for r in recs:
        x = auth.get_user(r)
        if r == u["username"] or not x or not x["active"] or x["role"] not in ("radiologist", "admin"):
            raise HTTPException(400, "bad_recipients")
    rep = json.load(open(HOME / "jobs" / jid / "report.json", encoding="utf-8"))
    if kind == "handover" and rep.get("status") == "final":
        raise HTTPException(409, "already_final")
    if consults.sent_last_hour(u["username"]) >= consults_mod.RATE_PER_HOUR:
        raise HTTPException(429, "too_many")
    if consults.active_pairs(jid) & set(recs):
        raise HTTPException(409, "already_shared")
    cid = consults.create(jid, u["username"], recs, kind, msg, prio, days)
    audit(request, "consult_send", f"{cid}:{jid}:{kind}:{','.join(recs)}")
    return {"id": cid}


@app.get("/api/consult/inbox")
def consult_inbox(request: Request):
    u = user(request, "admin", "radiologist")
    names = _names(); unread, _ = consults.unread_ids(u["username"])
    out = []
    for c in consults.inbox(u["username"]):
        c["recipients"] = (consults.get(c["id"]) or {}).get("recipients", [])
        out.append(_consult_item(c, u["username"], names, my_status=c["my_status"], unread=c["id"] in unread))
    return out


@app.get("/api/consult/sent")
def consult_sent(request: Request):
    u = user(request, "admin", "radiologist")
    names = _names(); _, unread = consults.unread_ids(u["username"])
    return [_consult_item(c, u["username"], names, unread=c["id"] in unread) for c in consults.sent(u["username"])]


@app.get("/api/consult/unread_count")
def consult_unread(request: Request):
    u = user(request)
    return {"n": consults.unread_count(u["username"]) if u["role"] in ("admin", "radiologist") else 0}


@app.get("/api/consult/{cid}")
def consult_detail(request: Request, cid: int):
    user(request, "admin", "radiologist")
    c, rec = _consult_or_404(request, cid)
    u = request.state.user
    if rec and c["sender"] != u["username"]:
        st = consults_mod.state(c, rec["status"])
        if st not in consults_mod.ACTIVE:                  # qaytarib olingan / muddati o'tgan / rad etilgan — yopiq
            if st == "expired":
                audit(request, "consult_expired", f"consult:{cid}", False)
            raise HTTPException(404, "not_found")
        if consults.mark_opened(cid, u["username"]):
            audit(request, "consult_open", f"consult:{cid}")
        c = consults.get(cid); rec = next(r for r in c["recipients"] if r["recipient"] == u["username"])
    elif c["sender"] == u["username"]:
        consults.mark_sender_seen(cid)
    return _consult_item(c, u["username"], _names(), my_status=rec["status"] if rec and c["sender"] != u["username"] else None,
                         with_messages=True)


def _active_participant(request, cid, need_recipient=False):
    c, rec = _consult_or_404(request, cid)
    u = request.state.user
    if c.get("revoked") or c["expires"] <= time.time():
        raise HTTPException(409, "consult_closed")
    is_rec = rec is not None and c["sender"] != u["username"]
    if is_rec and rec["status"] not in consults_mod.ACTIVE:
        raise HTTPException(409, "consult_closed")
    if need_recipient and not is_rec:
        raise HTTPException(403, "forbidden")
    if not is_rec and c["sender"] != u["username"]:
        raise HTTPException(403, "forbidden")                # admin faqat kuzatadi, yozishmada qatnashmaydi
    return c, rec


@app.post("/api/consult/{cid}/reply")
def consult_reply(request: Request, cid: int, body: dict = Body(...)):
    u = user(request, "admin", "radiologist")
    c, rec = _active_participant(request, cid)
    text = body.get("text")
    if not isinstance(text, str) or not text.strip() or len(text) > consults_mod.MAX_REPLY:
        raise HTTPException(400, "bad_params")
    consults.add_message(cid, u["username"], text.strip())
    if c["sender"] == u["username"]:
        consults.mark_sender_seen(cid)
    else:
        consults.mark_opened(cid, u["username"])
    audit(request, "consult_reply", f"consult:{cid}")
    return {"ok": True}


@app.post("/api/consult/{cid}/accept")
def consult_accept(request: Request, cid: int):
    u = user(request, "admin", "radiologist")
    c, rec = _active_participant(request, cid, need_recipient=True)
    if c["kind"] != "handover":
        raise HTTPException(400, "bad_params")
    rp = HOME / "jobs" / c["job_id"] / "report.json"
    if rp.exists() and json.load(open(rp, encoding="utf-8")).get("status") == "final":
        raise HTTPException(409, "already_final")
    consults.set_recipient_status(cid, u["username"], "accepted")
    audit(request, "consult_accept", f"consult:{cid}")
    return {"ok": True}


@app.post("/api/consult/{cid}/decline")
def consult_decline(request: Request, cid: int):
    u = user(request, "admin", "radiologist")
    c, rec = _active_participant(request, cid, need_recipient=True)
    if c["kind"] != "handover":
        raise HTTPException(400, "bad_params")
    consults.set_recipient_status(cid, u["username"], "declined")
    audit(request, "consult_decline", f"consult:{cid}")
    return {"ok": True}


@app.post("/api/consult/{cid}/revoke")
def consult_revoke(request: Request, cid: int):
    u = user(request, "admin", "radiologist")
    c, rec = _consult_or_404(request, cid)
    if not (c["sender"] == u["username"] or u["role"] == "admin"):
        raise HTTPException(403, "forbidden")
    if c.get("revoked"):
        raise HTTPException(409, "consult_closed")
    consults.revoke(cid)
    audit(request, "consult_revoke", f"consult:{cid}")
    return {"ok": True}


@app.get("/api/results")
def results(request: Request):
    user(request, "admin", "researcher")
    out = []
    def clean(o):  # NaN/inf (masalan, aniqlanmagan HD95) JSON da yo'q — null ga aylantiriladi
        if isinstance(o, float):
            return o if math.isfinite(o) else None
        if isinstance(o, dict):
            return {k: clean(v) for k, v in o.items()}
        if isinstance(o, list):
            return [clean(v) for v in o]
        return o
    for p in sorted((HOME / "results").glob("*/summary.json"), reverse=True):
        out.append({"name": p.parent.name, **clean(json.load(open(p)))})
    return out


def _self_signed(cert: Path, key: Path, hosts):
    """O'z-o'zini imzolagan TLS sertifikati (klinika ichki tarmog'i uchun). Ishonchli sertifikat bo'lsa --certfile/--keyfile bilan bering."""
    import datetime
    import ipaddress
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "UzLungMSKT")])
    alt = []
    for h in hosts:
        try:
            alt.append(x509.IPAddress(ipaddress.ip_address(h)))
        except ValueError:
            alt.append(x509.DNSName(h))
    now = datetime.datetime.now(datetime.timezone.utc)
    c = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(k.public_key())
         .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
         .not_valid_after(now + datetime.timedelta(days=825)).add_extension(x509.SubjectAlternativeName(alt), critical=False)
         .sign(k, hashes.SHA256()))
    key.write_bytes(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
    cert.write_bytes(c.public_bytes(serialization.Encoding.PEM))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["local", "clinic"], default="local",
                    help="local — faqat shu kompyuter (http://localhost); clinic — klinika tarmog'i (0.0.0.0, HTTPS)")
    ap.add_argument("--host"); ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--https", action="store_true", help="HTTPS (sertifikat bo'lmasa o'z-o'zini imzolagan sertifikat yaratiladi)")
    ap.add_argument("--certfile"); ap.add_argument("--keyfile")
    ap.add_argument("--create-admin", metavar="LOGIN", help="yangi administrator yaratish va chiqish")
    ap.add_argument("--reset-password", metavar="LOGIN", help="mavjud foydalanuvchi (masalan, admin) parolini tiklash va chiqish; faqat server kompyuteridan")
    ap.add_argument("--log", help="chiqishni faylga yozish (konsolsiz ishga tushirishda standart: <ish papkasi>/logs/web_server.log)")
    a = ap.parse_args()
    if a.log or sys.stdout is None:   # pythonw (konsolsiz): stdout yo'q — uvicorn jurnali faylga yo'naltiriladi
        lp = Path(a.log) if a.log else HOME / "logs" / "web_server.log"
        lp.parent.mkdir(parents=True, exist_ok=True)
        sys.stdout = sys.stderr = open(lp, "a", encoding="utf-8", buffering=1)
        print(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} server ishga tushdi (PID {os.getpid()}) ===")
    if a.create_admin or a.reset_password:
        import getpass
        login_ = a.create_admin or a.reset_password
        pw = getpass.getpass("Yangi parol / New password / Новый пароль: ")
        if pw != getpass.getpass("Takrorlang / Repeat / Повторите: "):
            print("Parollar mos kelmadi."); sys.exit(1)
        try:
            if a.reset_password:
                auth.admin_reset(a.reset_password, pw)
                print("ok: parol almashtirildi, barcha sessiyalar yopildi")
            else:
                auth.create_user(a.create_admin, a.create_admin, "admin", pw, must_change=False)
                print("ok")
        except ValueError as e:
            print(f"Xato: {e}"); sys.exit(1)
        return
    import uvicorn
    if a.mode == "clinic":
        a.host = a.host or "0.0.0.0"; a.https = True; a.no_browser = True
    a.host = a.host or "127.0.0.1"
    ssl = {}
    if a.https or a.certfile:
        cert, key = Path(a.certfile or HOME / "tls" / "cert.pem"), Path(a.keyfile or HOME / "tls" / "key.pem")
        if not cert.exists():
            cert.parent.mkdir(exist_ok=True)
            import socket
            hosts = ["localhost", "127.0.0.1", socket.gethostname()]
            try:
                hosts.append(socket.gethostbyname(socket.gethostname()))
            except OSError:
                pass
            _self_signed(cert, key, sorted(set(hosts)))
        ssl = {"ssl_certfile": str(cert), "ssl_keyfile": str(key)}
    if a.host not in ("127.0.0.1", "localhost") and not ssl:
        print("DIQQAT: tarmoqda HTTPS siz ishlash xavfli — --https bilan ishga tushiring.")
    scheme = "https" if ssl else "http"
    if not a.no_browser:
        import threading, webbrowser
        threading.Timer(1.5, lambda: webbrowser.open(f"{scheme}://localhost:{a.port}")).start()
    print(f"UzLungMSKT: {scheme}://localhost:{a.port}  (ish papkasi: {HOME})", flush=True)

    def _warm():   # torch ni fonda oldindan yuklash: birinchi tahlil tezlashadi, muammo bo'lsa jurnalda darhol ko'rinadi
        from .. import sysinfo
        ts = sysinfo.torch_state()           # GPU mosligi ham shu yerda tekshiriladi (mos bo'lmasa — protsessor)
        if ts.get("ok"):
            gpu = f"; videokarta: {ts.get('gpu')} ({ts.get('arch', '')})" if ts.get("gpu") else ""
            note = (f"; DIQQAT: videokarta ishlatilmaydi ({ts['gpu_note']}: {ts.get('gpu_error', '')[:200]}) — tahlil protsessorda"
                    if ts.get("gpu_note") and ts.get("cuda") else "")
            print(f"[torch] {ts['version']} yuklandi ({ts['seconds']} s); qurilma: {ts['device']}{gpu}{note}", flush=True)
        else:
            print("[torch] YUKLANMADI — tahlil ishlamaydi:\n" + ts.get("trace", ts.get("error", "")), flush=True)
            if ts.get("missing"):
                print("[torch] yetishmayotgan DLL: " + ", ".join(ts["missing"]) + " — UzLungCT.exe ning yangi versiyasini o'rnating "
                      "yoki Microsoft Visual C++ Redistributable 2015–2022 (x64) o'rnating", flush=True)
    import threading
    threading.Timer(1.0, _warm).start()
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning", proxy_headers=False, server_header=False,
                workers=1, limit_concurrency=64, timeout_keep_alive=10, **ssl)   # bitta jarayon: GPU navbati va sessiyalar umumiy


if __name__ == "__main__":
    main()
