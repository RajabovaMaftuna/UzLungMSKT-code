"""TotalSegmentator `lung_nodules` — ALOHA jarayonda ishga tushiriladi (alohida jarayonda, paket ichidagi python bilan).
Windows'da torch numpy/scipy'dan OLDIN import qilinishi va asosiy blok himoyasi shart.
Foydalanish:  python ts_runner.py <ct.nii.gz> <chiqish_papkasi>"""
import os
import sys
# uzlungct/ papkasida ssl.py (yo'qotish moduli) bor: skript papkasi sys.path[0] bo'lsa, stdlib `ssl` ni yopib qo'yadi
# (torch -> unittest.mock -> asyncio -> ssl zanjirida import xatosi). Shu sababli papkani yo'ldan olib tashlaymiz.
_here = os.path.dirname(os.path.abspath(__file__))
sys.path[:] = [p for p in sys.path if os.path.abspath(p or os.getcwd()) != _here]
import torch  # noqa: F401,E402  (birinchi bo'lishi shart)


def main(argv):
    from totalsegmentator.python_api import totalsegmentator
    inp, out = argv[1], argv[2]
    totalsegmentator(inp, out, task="lung_nodules", device="gpu" if torch.cuda.is_available() else "cpu", quiet=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
