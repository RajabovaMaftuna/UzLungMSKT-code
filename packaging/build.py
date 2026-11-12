# UzLungMSKT.exe yig'uvchisi: tekshiruvlar -> stub + ZIP64 yuk -> sha256 -> hisobot ma'lumoti.
import os, re, sys, shutil, zipfile, hashlib, json, time
S = r"C:\ZG\build_exe\stage"; OUT = r"C:\ZG\build_exe\out\UzLungMSKT_data.zip"; EXE = r"C:\ZG\build_exe\out\UzLungMSKT.exe"; STUB = r"C:\ZG\build_exe\stub.exe"
BAD_NAMES = {"auth.db", "patients.db", "patients.db-wal", "patients.db-shm", ".patient_key", ".service_token", "consults.db", "settings.json", "BOSHLANGICH_ADMIN_KODI.txt", "BOSHLANGICH_ADMIN_PAROLI.txt"}
files = [os.path.join(r, f) for r, _, fs in os.walk(S) for f in fs]
rel = lambda p: os.path.relpath(p, S).replace("\\", "/")
# 1) bemor/foydalanuvchi ma'lumoti yo'qligi
bad = [rel(p) for p in files if os.path.basename(p) in BAD_NAMES or rel(p).startswith(("workspace/jobs", "workspace/cases", "workspace/uploads", "workspace/cache", "workspace/research", "workspace/deleted_jobs", "workspace/logs"))]
ws = sorted({rel(p) for p in files if rel(p).startswith("workspace/")})
assert not bad, ("TAQIQLANGAN FAYLLAR", bad[:10])
assert all(r.startswith(("workspace/runs/N8/", "workspace/runs/cls/")) for r in ws), ws
# 2) mutlaq yo'llar (kod va konfiguratsiya)
pat = re.compile(r"[CD]:\\\\?(ZS|ZG|nnUNet_m2|ext)\b|C:/ZG")
hits = []
for p in files:
    r = rel(p)
    if r.startswith("python/") or not p.endswith((".py", ".pyw", ".json", ".yaml", ".js", ".html", ".txt")):
        continue
    if pat.search(open(p, encoding="utf-8", errors="ignore").read()):
        hits.append(r)
assert not hits, ("MUTLAQ YO'L", hits)
# 3) yig'ish
os.makedirs(os.path.dirname(OUT), exist_ok=True); shutil.copy2(STUB, EXE)
t = time.time(); n = 0
with zipfile.ZipFile(OUT + ".part", "w", allowZip64=True) as z:
    for p in files:
        big = False   # Windows exe 4 GB dan oshmasligi uchun hammasi siqiladi
        z.write(p, rel(p), compress_type=zipfile.ZIP_STORED if big else zipfile.ZIP_DEFLATED, compresslevel=None if big else 6); n += 1
with zipfile.ZipFile(OUT + ".part") as z:
    assert len(z.namelist()) == n and z.testzip() is None
os.replace(OUT + ".part", OUT)
h = hashlib.sha256()
with open(OUT, "rb") as f:
    for b in iter(lambda: f.read(1 << 22), b""):
        h.update(b)
info = {"fayl": OUT, "hajm_GB": round(os.path.getsize(OUT) / 2**30, 2), "fayllar": n, "sha256": h.hexdigest(), "vaqt_s": round(time.time() - t), "sana": time.strftime("%Y-%m-%d %H:%M")}
json.dump(info, open(r"C:\ZG\build_exe\build_info.json", "w"), indent=1); print(info)
