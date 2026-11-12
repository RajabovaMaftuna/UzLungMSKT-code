"""DLL bog'liqliklari tahlili (pefile'siz, PE import jadvali o'qiladi) — build vaqtida (deploy/exe/dll_deps.py, build_exe.py)
va ishlash vaqtida (sysinfo: torch «WinError 126» bo'lsa qaysi DLL yetishmayotganini aniqlash) ishlatiladi.
Har bir .dll/.pyd ning oddiy va kechiktirilgan importlari rekursiv yechiladi va manbasi bo'yicha guruhlanadi:
  bundle  — o'rnatma ichida (python/, torch/lib va h.k.);
  apiset  — api-ms-win-* / ext-ms-* (Windows API to'plamlari);
  base    — har qanday Windows 10/11 da bor tizim DLL'lari (ro'yxat pastda);
  SYSTEM  — faqat shu kompyuterning System32 ida topildi, lekin Windows tarkibiga KIRMAYDI (drayver, VC++ redist va h.k.) —
            boshqa kompyuterda yo'q bo'lishi mumkin;
  MISSING — hech qayerda topilmadi.
"""
from __future__ import annotations

import os
import struct
from pathlib import Path

SYS32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
# Windows 10 (1809+) / 11 toza o'rnatmasida mavjud DLL'lar (torch/python importlari uchun yetarli to'plam)
BASE = {
    "kernel32.dll", "kernelbase.dll", "ntdll.dll", "user32.dll", "gdi32.dll", "advapi32.dll", "shell32.dll", "ole32.dll",
    "oleaut32.dll", "ws2_32.dll", "shlwapi.dll", "version.dll", "psapi.dll", "dbghelp.dll", "setupapi.dll", "cfgmgr32.dll",
    "bcrypt.dll", "crypt32.dll", "secur32.dll", "rpcrt4.dll", "comdlg32.dll", "comctl32.dll", "winmm.dll", "iphlpapi.dll",
    "userenv.dll", "dnsapi.dll", "netapi32.dll", "imm32.dll", "msvcrt.dll", "ucrtbase.dll", "sechost.dll", "combase.dll",
    "powrprof.dll", "wintrust.dll", "normaliz.dll", "mswsock.dll", "nsi.dll", "winhttp.dll", "wininet.dll", "dwmapi.dll",
    "uxtheme.dll", "opengl32.dll", "glu32.dll", "d3d11.dll", "dxgi.dll", "d3d12.dll", "d3dcompiler_47.dll", "ncrypt.dll",
    "mfplat.dll", "mf.dll", "mfreadwrite.dll", "evr.dll", "ksuser.dll", "avrt.dll", "mmdevapi.dll", "propsys.dll",
    "shcore.dll", "wldap32.dll", "pdh.dll", "wtsapi32.dll", "cabinet.dll", "msimg32.dll", "usp10.dll", "gdiplus.dll",
    "winspool.drv", "oledlg.dll", "urlmon.dll", "mpr.dll", "msacm32.dll", "mfuuid.dll", "dxcore.dll", "wevtapi.dll",
    "tdh.dll", "credui.dll", "hid.dll", "winusb.dll", "ntmarta.dll", "authz.dll", "msv1_0.dll", "kerberos.dll",
    "api-ms-win-core-path-l1-1-0.dll", "ws2help.dll", "glu.dll", "mscms.dll", "dbgeng.dll", "dwrite.dll", "d2d1.dll",
    "windowscodecs.dll", "rstrtmgr.dll", "wsock32.dll", "fwpuclnt.dll", "winsta.dll", "mfcore.dll", "comsvcs.dll",
    "bcryptprimitives.dll", "imagehlp.dll",
}


def imports(path: Path) -> set[str]:
    data = path.read_bytes()
    try:
        pe = struct.unpack_from("<I", data, 0x3C)[0]
        if data[pe:pe + 4] != b"PE\0\0":
            return set()
        nsec = struct.unpack_from("<H", data, pe + 6)[0]
        optsz = struct.unpack_from("<H", data, pe + 20)[0]
        opt = pe + 24
        magic = struct.unpack_from("<H", data, opt)[0]
        dd = opt + (112 if magic == 0x20B else 96)
        secs = []
        for i in range(nsec):
            s = opt + optsz + i * 40
            vsz, va, rsz, raw = struct.unpack_from("<IIII", data, s + 8)
            secs.append((va, max(vsz, rsz), raw))

        def off(rva):
            for va, sz, raw in secs:
                if va <= rva < va + sz:
                    return rva - va + raw
            return None

        def cstr(o):
            return data[o:data.index(b"\0", o)].decode("ascii", "replace")

        out = set()
        for idx, step, name_at in ((1, 20, 12), (13, 32, 4)):        # import va delay-import kataloglari
            rva, size = struct.unpack_from("<II", data, dd + idx * 8)
            o = off(rva) if rva else None
            while o is not None and o + step <= len(data):
                nrva = struct.unpack_from("<I", data, o + name_at)[0]
                if nrva == 0:
                    break
                no = off(nrva)
                if no is not None:
                    out.add(cstr(no).lower())
                o += step
        return out
    except (struct.error, ValueError):
        return set()


def analyze(root: Path, starts: list[Path] | None = None) -> dict[str, list[str]]:
    """{toifa: ["dll  (kerak: ...)"]}; starts=None — o'rnatmadagi BARCHA .dll/.pyd/.exe tekshiriladi."""
    root = Path(root).resolve()
    index, every = {}, []
    for p in root.rglob("*"):
        if p.suffix.lower() in (".dll", ".pyd", ".exe") and p.is_file():
            index.setdefault(p.name.lower(), p); every.append(p)
    seen, todo, owner = {}, list(starts or every), {}
    while todo:
        f = todo.pop()
        key = str(f).lower()
        if key in seen:
            continue
        seen[key] = f
        for d in imports(f):
            if d.startswith(("api-ms-win-", "ext-ms-")):
                owner.setdefault(d, ("apiset", f.name)); continue
            if d in index:
                owner.setdefault(d, ("bundle", f.name)); todo.append(index[d]); continue
            if d in BASE:
                owner.setdefault(d, ("base", f.name)); continue
            if (SYS32 / d).exists():
                owner.setdefault(d, ("SYSTEM", f.name)); continue
            owner.setdefault(d, ("MISSING", f.name))
    res = {}
    for d, (kind, by) in sorted(owner.items()):
        res.setdefault(kind, []).append(f"{d}  (kerak: {by})")
    return res


def unresolved(dll: Path, pyroot: Path) -> list[str]:
    """dll va uning rekursiv bog'liqliklari orasida hech qayerda (o'rnatma, System32) topilmaganlari."""
    res = analyze(pyroot, [Path(dll)])
    return [s.split()[0] for s in res.get("MISSING", [])]
