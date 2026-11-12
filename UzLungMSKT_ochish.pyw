"""Ish stolidagi UzLungMSKT yorlig'i: bir bosishda platformani brauzerda ochadi.
Server ishlayotgan bo'lsa — darhol brauzer; ishlamasa — «ishga tushmoqda» sahifasi, serverni ishga tushirish, so'ng platforma.
Avtostart yozuvi (reyestr Run) yo'qolgan bo'lsa, qayta tiklanadi.  pythonw.exe -E -s UzLungMSKT_ochish.pyw [--port 8000]"""
import os
import sys
import time
import webbrowser

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
PORT = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8000
URL = f"http://localhost:{PORT}/"
LOGS = os.path.join(ROOT, "workspace", "logs")
os.makedirs(LOGS, exist_ok=True)


def log(m):
    with open(os.path.join(LOGS, "ochish.log"), "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {m}\n")


def msg(text):
    import ctypes
    ctypes.windll.user32.MessageBoxW(None, text, "UzLungMSKT", 0x10)


try:
    from uzlungct import autostart as a
    try:
        if not a.get("UzLungMSKT") and not os.environ.get("UZLUNGCT_NO_AUTOSTART"):
            a.enable("UzLungMSKT", PORT); log("avtostart yozuvi tiklandi")
    except Exception as e:
        log(f"avtostart tekshiruvi: {e}")
    if a.running(PORT):
        log("server ishlayapti -> brauzer"); webbrowser.open(URL); sys.exit(0)
    page = os.path.join(LOGS, "ochilmoqda.html")
    with open(page, "w", encoding="utf-8") as f:
        f.write(f"""<!doctype html><meta charset="utf-8"><title>UzLungMSKT</title>
<body style="font-family:Segoe UI,Arial;background:#0f172a;color:#e2e8f0;display:flex;align-items:center;justify-content:center;height:95vh">
<div style="text-align:center"><h2>UzLungMSKT ishga tushmoqda…</h2><p>Kompyuter yangi yoqilgan bo'lsa, 1–3 daqiqa davom etishi mumkin. Bu sahifa o'zi platformaga o'tadi.</p>
<p id="t">0 s</p></div><script>var s=0;setInterval(function(){{s+=2;document.getElementById('t').textContent=s+' s';
fetch('{URL}',{{mode:'no-cors',cache:'no-store'}}).then(function(){{location.replace('{URL}')}}).catch(function(){{}})}},2000);</script>""")
    webbrowser.open("file:///" + page.replace("\\", "/"))
    log("server ishlamayapti -> ishga tushirilmoqda")
    if a.start(PORT, wait=300):
        log("server ishga tushdi")
    else:
        log("XATO: server 300 s ichida ishga tushmadi")
        msg("UzLungMSKT serveri ishga tushmadi.\n\nJurnal: " + os.path.join(LOGS, "web_server.log") +
            "\n\nKompyuterni qayta yoqib, yana urinib ko'ring.")
except SystemExit:
    raise
except BaseException as e:
    import traceback
    log("XATO: " + traceback.format_exc())
    msg(f"UzLungMSKT ochilmadi: {e}\n\nJurnal: {os.path.join(LOGS, 'ochish.log')}")
