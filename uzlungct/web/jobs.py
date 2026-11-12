"""Fon vazifalari: tahlil (xulosa chiqarish) — oqimda; o'qitish/baholash/tayyorlash — alohida jarayonda.
Bir vaqtning o'zida videokartada bitta og'ir vazifa ishlaydi (8 GB xotira uchun navbat)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path

GPU_LOCK = threading.Lock()      # og'ir vazifalar (o'qitish, baholash, tayyorlash) — navbat bilan
INFER_LOCK = threading.Lock()    # tahlil — o'qitish bilan parallel ishlay oladi (8 GB da yetarli xotira)


def child_python():
    """Bola jarayon uchun interpretator: server pythonw (konsolsiz) bilan ishlasa ham python.exe olinadi
    (CREATE_NO_WINDOW bilan oyna ochilmaydi); -E/-s bayroqlari saqlanadi (portativ o'rnatma izolyatsiyasi)."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and exe.with_name("python.exe").exists():
        exe = exe.with_name("python.exe")
    flags = (["-E"] if sys.flags.ignore_environment else []) + (["-s"] if sys.flags.no_user_site else [])
    return [str(exe), *flags, "-X", "utf8"]


def _pid_alive(pid):
    try:
        if os.name == "nt":
            out = subprocess.run(["tasklist", "/FI", f"PID eq {int(pid)}", "/NH"], capture_output=True, text=True,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
            return str(int(pid)) in out
        os.kill(int(pid), 0); return True
    except Exception:
        return False


class JobStore:
    def __init__(self, root: Path):
        self.root = root / "jobs"; self.root.mkdir(parents=True, exist_ok=True)
        self.procs: dict[str, subprocess.Popen] = {}
        self._threads: dict[str, bool] = {}

    def _p(self, jid):
        return self.root / jid

    def create(self, kind, params, owner=None):
        jid = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        d = self._p(jid); d.mkdir()
        self.save(jid, {"id": jid, "kind": kind, "params": params, "owner": owner, "status": "queued", "created": time.time()})
        return jid

    def save(self, jid, meta):
        json.dump(meta, open(self._p(jid) / "job.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    def get(self, jid):
        p = self._p(jid) / "job.json"
        if not p.exists():
            return None
        m = json.load(open(p, encoding="utf-8"))
        if jid in self.procs and m["status"] == "running":
            rc = self.procs[jid].poll()
            if rc is not None:
                m["status"] = "done" if rc == 0 else "error"; m["returncode"] = rc; m["finished"] = time.time()
                self.save(jid, m); self.procs.pop(jid, None)
        elif m["status"] in ("running", "queued") and jid not in self.procs and not self._threads.get(jid):
            # server qayta ishga tushganidan keyin: jarayon tirikmi?
            if m.get("pid") and _pid_alive(m["pid"]):
                return m
            out = m.get("params", {}).get("out")
            ok = bool(out) and (Path(out) / ("summary.json" if m["kind"] in ("train", "evaluate") else "index.json")).exists()
            m["status"] = "done" if ok else "error"; m["finished"] = time.time(); m.setdefault("error", "server_restarted")
            self.save(jid, m)
        return m

    def update(self, jid, **kw):
        m = self.get(jid); m.update(kw); self.save(jid, m); return m

    def list(self, kind=None):
        out = []
        for d in sorted(self.root.iterdir(), reverse=True):
            m = self.get(d.name)
            if m and (kind is None or m["kind"] == kind):
                out.append(m)
        return out

    def log_tail(self, jid, n=80):
        p = self._p(jid) / "stdout.log"
        if not p.exists():
            return ""
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-n:])

    def run_thread(self, jid, fn):
        self._threads[jid] = True

        def wrap():
            with INFER_LOCK:
                self.update(jid, status="running", started=time.time())
                try:
                    res = fn(self._p(jid))
                    self.update(jid, status="done", finished=time.time(), result=res)
                except Exception as e:
                    (self._p(jid) / "stdout.log").write_text(traceback.format_exc(), encoding="utf-8")
                    self.update(jid, status="error", error=str(e), finished=time.time())
            self._threads.pop(jid, None)
        threading.Thread(target=wrap, daemon=True).start()

    def run_process(self, jid, args, cwd):
        """python -m ... ni alohida jarayonda ishga tushiradi (o'qitish soatlab davom etishi mumkin)."""
        self._threads[jid] = True

        def wrap():
            with GPU_LOCK:
                log = open(self._p(jid) / "stdout.log", "w", encoding="utf-8")
                env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
                p = subprocess.Popen([*child_python(), "-u", *args], cwd=cwd, stdout=log, stderr=subprocess.STDOUT, env=env,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                self.procs[jid] = p
                self.update(jid, status="running", started=time.time(), pid=p.pid, cmd=" ".join(args))
                p.wait(); log.close(); self.get(jid)
            self._threads.pop(jid, None)
        threading.Thread(target=wrap, daemon=True).start()

    def stop(self, jid):
        p = self.procs.get(jid)
        if p and p.poll() is None:
            p.terminate(); self.update(jid, status="stopped"); return True
        return False
