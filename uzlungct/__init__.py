"""UzLungMSKT — MSKT tasvirlari asosida o'pka va o'pka o'smalarini segmentatsiyalash,
tugunlarni tasniflash va radiologga ko'maklashuvchi intellektual dasturiy ta'minot.

Dissertatsiya: "Tibbiy tasvirlar asosida o'pka saratonini tashxislashning chuqur
o'qitishga asoslangan intellektual usul va algoritmlari" (05.01.11), III–IV boblar.

Modullar dissertatsiya paragraflariga mos:
  3.1  uzlungct.models.unet3d        — bazaviy 3D U-Net
  3.2  uzlungct.models.r2u3d         — R²U3D statik (RRCU) va dinamik (DRRCU + SE)
  3.3  uzlungct.models.res2unet3d    — 3D-Res2UNet
  3.4  uzlungct.models.transformers  — UNETR / Swin UNETR (MONAI o'rami)
  4.1  uzlungct.models.classifier, uzlungct.ssl — o'z-o'zini nazorat qiluvchi tasniflagich
  4.2  uzlungct.losses               — adaptiv yo'qotish funksiyalari
  4.3  uzlungct.app                  — radiolog interfeysi va hisobot
  4.4  uzlungct.metrics, uzlungct.evaluate — matematik-statistik baholash
"""
__version__ = "0.2.0"
