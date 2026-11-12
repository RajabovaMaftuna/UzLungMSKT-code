# SenGuard-3D — model kartasi va nomlar reestri (v1.0, 2026-11-02)

## 1. Identifikatsiya
| Maydon | Qiymat |
|---|---|
| Nashr nomi | SenGuard-3D |
| To'liq nomi | SenGuard-3D: ko'krak qafasi KT tasvirida o'pka o'choqlarini aniqlash uchun bemor darajasidagi sezgirligi statistik kafolatlangan geterogen segmentatsiya–detektsiya ansambli |
| Ichki (ishchi) identifikator | N8 — tadqiqot jurnallari, kod va muzlatilgan fayllarda |
| Versiya | 1.0, muzlatilgan |
| Komponent va fayl xeshlari | `docs\senguard3d_registry.json` (sha256, birinchi 16 belgi) |

Qoida: "SenGuard-3D" va "N8" bitta, aynan bir xil tizimdir. Nashrlarda faqat SenGuard-3D ishlatiladi; ichki identifikator faqat izlanuvchanlik (audit) uchun saqlanadi. Ichki fayl nomlari ataylab o'zgartirilmagan: ular muzlatilgan xeshlar bilan bog'langan va o'zgartirish natijalarning qayta tekshirilishini buzadi.

## 2. Tarkib
1. M2 — nnU-Net v2 3D full-res, 5 fold (MSD Task06 + NLSTseg-T), voksel ehtimoli ≥ 0.05.
2. K1 — nnU-Net v2 3D full-res, 5 fold (MSD Task06).
3. TotalSegmentator 2.18 `lung_nodules`.
4. MONAI 3D RetinaNet (LUNA16), ball ≥ 0.9.
Birlashtirish: niqob va qutilar bo'yicha UNION (OR). Platformada triaj: ASOSIY = ≥2 manba yoki M2 ehtimoli ≥0.5 yoki detektor ≥0.99; qolganlari QO'SHIMCHA (topish niqobi o'zgarmaydi).

## 3. Mo'ljallangan foydalanish va chegaralar
Past dozali skrining KT (NLSTseg ga o'xshash) da o'pka o'choqlarini radiolog uchun belgilash; ikkinchi o'quvchi. Klinik tashxis vositasi emas. Diagnostik KT, PET/KT va mahalliy ma'lumotlar uchun sertifikat yo'q.

## 4. Natijalar (docs\17)
| To'plam | n | O'tkazilgan bemorlar | Bayonot |
|---|---|---|---|
| NLSTseg C∪X (o'pka o'choqlari) | 236 | 3 (1.3%), 95% yuqori chegara 3.3% | sezgirlik ≥90%, 95% ishonch — o'tdi |
| S2 toifa, ≥95% | 135 | 3 | o'tmadi (p=0.09) |
| FDG-C | 81 | 27 (33.3%) | sertifikat yo'q |
FP: ~4.3/bemor (asosiy darajada ~2.4).

## 5. Nomlar mosligi jadvali (dissertatsiya uchun)
| Hujjat/jurnaldagi atama | Dissertatsiyadagi atama |
|---|---|
| N8 | SenGuard-3D |
| N5 | SenGuard-3D ning detektorsiz varianti |
| M2 | nnU-Net (MSD+NLSTseg, 500 epoch) |
| K1 | nnU-Net (MSD) |
| TS | TotalSegmentator lung_nodules |
| H1/H2/H3 | 1/2/3-bayonot (LTT) |
Asos: model kartasi tamoyili (Mitchell va b., 2019) va TRIPOD+AI talabi — model nomi, versiyasi va komponentlari hisobotda aniq identifikatsiyalanishi kerak.
