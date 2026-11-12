"""UzLungCT serverini konsol oynasisiz ishga tushirish (Windows avtostarti va UzLungCT.exe fon rejimi uchun).
pythonw.exe UzLungCT_server.pyw [--port 8000]   — jurnal: <ish papkasi>/logs/web_server.log

Jurnal HAR QANDAY importdan oldin ochiladi: pythonw da stdout/stderr yo'q, shu sababli kutubxona yuklashdagi xato
(DLL, xotira, protsessor ko'rsatmalari) aks holda hech qayerga yozilmay, jarayon jim o'lardi. Xato bo'lsa, to'liq matn
logs/startup_error.txt ga ham yoziladi — UzLungCT.exe uni foydalanuvchiga ko'rsatadi.
"""
import faulthandler
import os
import sys
import time
import traceback

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
LOGS = os.path.join(os.environ.get("UZLUNGCT_HOME") or os.path.join(ROOT, "workspace"), "logs")
os.makedirs(LOGS, exist_ok=True)
ERR = os.path.join(LOGS, "startup_error.txt")
LOG = os.path.join(LOGS, "web_server.log")
try:                                   # jurnal aylanishi: 10 MB dan oshsa web_server.log.1 … .5 (eng eskisi o'chadi)
    if os.path.getsize(LOG) > 10 << 20:
        for i in range(4, 0, -1):
            if os.path.exists(f"{LOG}.{i}"):
                os.replace(f"{LOG}.{i}", f"{LOG}.{i + 1}")
        os.replace(LOG, f"{LOG}.1")
except OSError:                        # fayl yo'q yoki boshqa nusxa uni ochib turibdi — aylantirilmaydi
    pass
log = open(LOG, "a", encoding="utf-8", buffering=1)
if sys.stdout is None:
    sys.stdout = log
if sys.stderr is None:
    sys.stderr = log
faulthandler.enable(file=log)          # C darajasidagi qulash (masalan, DLL ichida) ham jurnalga yoziladi
if os.path.exists(ERR):
    os.remove(ERR)
print(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} python {sys.version.split()[0]} boshlandi (PID {os.getpid()}); "
      f"papka: {ROOT} ===", file=log, flush=True)
try:
    from uzlungct.autostart import serve
    serve(sys.argv[1:])
except SystemExit as e:              # masalan, uvicorn port band bo'lgani uchun to'xtasa
    if e.code not in (0, None):
        with open(ERR, "w", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\nServer to'xtadi (kod {e.code}). Batafsil: logs\\web_server.log\n")
    raise
except BaseException:
    tb = traceback.format_exc()
    print("ISHGA TUSHISH XATOSI:\n" + tb, file=log, flush=True)
    with open(ERR, "w", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\n{tb}")
    sys.exit(1)
