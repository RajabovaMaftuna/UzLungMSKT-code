# 33-promt hisoboti: build 6 ni toza o‘rnatish sinovi (2026-11-04)
Paket: `D:\O'pka saratonini aniqlaydigan dastur va uning bazasi\UzLungCT_dastur 02.11.2026` → nusxa `C:\ZG\toza_sinov\transfer` → noldan o‘rnatish `C:\ZG\toza_sinov\inst`, port 8050. Jurnal: `C:\ZG\build_exe\toza_sinov_log.txt`.

| № | Talab | Natija |
|---|---|---|
| T1 | Paket butunligi | OK — 4 qism sha256 mos |
| T2 | Noldan o‘rnatish, birinchi kirish kodi | OK — 94 s, kod fayli yaratildi |
| T3 | Versiya va model | OK — build 6, n8_runner 1.0.1 (ba66c6fbbbfe9d4b) |
| T4 | Izolyatsiya | OK — 4712 modul, tashqi 0 |
| T5 | SenGuard-3D, Kirill nomli 7z arxiv | OK — 3250 voksel, 6 quti |
| T6 | 23 avtotest (funksional, xavfsizlik, rollar, i18n, PDF, o‘chirish himoyasi) | OK — 23/23 |
| T7 | Interfeys (nom, «Xavfli o‘simta ehtimoli», mobil CSS) | OK |
| T8 | Ishchi platforma buzilmagan | OK — 8000 javob 200 |

Kuzatuv: birinchi urinishda o‘rnatma `%LOCALAPPDATA%` ga qilinganda T4 xato berdi — sabab sinov muhiti (Claude ilovasining MSIX papka yo‘naltirishi), mahsulot emas; sinov yo‘naltirilmaydigan papkada qayta o‘tkazildi. Avtostart va yorliqlar reliz botining 9-sinovida tekshirilgan.
