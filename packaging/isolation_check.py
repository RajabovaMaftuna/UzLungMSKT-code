# O'rnatilgan nusxa izolyatsiyasi: barcha kerakli modullarni yuklaydi va o'rnatma papkasidan TASHQARIDAN yuklangan .py/.pyd/.dll larni sanaydi.
import sys, os
root = os.path.dirname(os.path.dirname(os.path.abspath(sys.executable)))
import uzlungct.web.server, uzlungct.n8fusion, nnunetv2, totalsegmentator, monai, torch, torchvision, nibabel, SimpleITK
from totalsegmentator.python_api import totalsegmentator as _t
from nnunetv2.inference.predict_from_raw_data import nnUNetPredictor
out = sorted({getattr(m, "__file__", None) for m in list(sys.modules.values())} - {None})
bad = [f for f in out if not os.path.abspath(f).lower().startswith(root.lower())]
print("ildiz", root, "modullar", len(out), "TASHQI", len(bad))
for b in bad[:20]:
    print("  ", b)
print("sys.path tashqi:", [p for p in sys.path if p and not os.path.abspath(p).lower().startswith(root.lower())])
print("cuda", torch.cuda.is_available())
sys.exit(1 if bad else 0)
