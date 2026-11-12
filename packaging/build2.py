# UzLungMSKT yig'uvchisi v2: yuk <=1.7 GB li bir nechta oddiy ZIP (ZIP64 siz, FAT32/exFAT/eski .NET bilan mos) + parts.json (sha256, hajm).
import os, re, sys, shutil, zipfile, hashlib, json, time
S = r"C:\ZG\build_exe\stage"; OUTD = r"C:\ZG\build_exe\out2"; STUB = r"C:\ZG\build_exe\stub.exe"; LIM = int(1.7 * 2**30)
BAD = {"auth.db", "patients.db", "patients.db-wal", "patients.db-shm", ".patient_key", ".service_token", "consults.db", "settings.json", "BOSHLANGICH_ADMIN_KODI.txt", "BOSHLANGICH_ADMIN_PAROLI.txt"}
files = sorted(os.path.join(r, f) for r, _, fs in os.walk(S) for f in fs)
rel = lambda p: os.path.relpath(p, S).replace("\\", "/")
assert not [p for p in files if os.path.basename(p) in BAD], "taqiqlangan fayl"
assert all(rel(p).startswith(("workspace/runs/N8/", "workspace/runs/cls/")) for p in files if rel(p).startswith("workspace/"))
pat = re.compile(r"[CD]:\\\\?(ZS|ZG|nnUNet_m2|ext)\b|C:/ZG")
assert not [rel(p) for p in files if not rel(p).startswith("python/") and p.endswith((".py", ".pyw", ".json", ".yaml", ".js", ".html", ".txt")) and pat.search(open(p, encoding="utf-8", errors="ignore").read())], "mutlaq yo'l"
assert max(os.path.getsize(p) for p in files) < LIM, "bitta fayl juda katta"
shutil.rmtree(OUTD, ignore_errors=True); os.makedirs(OUTD)
parts, k, z, t = [], 0, None, time.time()
def newpart():
    global k, z
    if z: z.close()
    k += 1; name = f"UzLungMSKT_data_{k:02d}.zip"; parts.append(name)
    z = zipfile.ZipFile(os.path.join(OUTD, name), "w", allowZip64=False)
newpart()
for p in files:
    if os.path.getsize(os.path.join(OUTD, parts[-1])) + os.path.getsize(p) > LIM:
        z.close(); z = None; newpart()
    z.write(p, rel(p), compress_type=zipfile.ZIP_DEFLATED, compresslevel=6)
z.close()
man = {"versiya": open(os.path.join(S, "VERSION.txt")).read().strip(), "qismlar": []}
total = 0
for name in parts:
    f = os.path.join(OUTD, name)
    with zipfile.ZipFile(f) as q:
        assert q.testzip() is None; total += len(q.namelist())
    h = hashlib.sha256()
    with open(f, "rb") as r:
        for b in iter(lambda: r.read(1 << 22), b""):
            h.update(b)
    man["qismlar"].append({"fayl": name, "hajm": os.path.getsize(f), "sha256": h.hexdigest()})
assert total == len(files)
json.dump(man, open(os.path.join(OUTD, "UzLungMSKT_parts.json"), "w"), indent=1)
shutil.copy2(STUB, os.path.join(OUTD, "UzLungMSKT.exe"))
print("qismlar", len(parts), "fayllar", total, "GB", round(sum(q["hajm"] for q in man["qismlar"]) / 2**30, 2), "vaqt", round(time.time() - t))
