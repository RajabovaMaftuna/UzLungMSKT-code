"""Hisobotni PDF faylga aylantirish (server tomonida, internetsiz).

Mazmun HTML hisobot (report.py) bilan bir xil va o'sha matnlardan (TXT, CONS) foydalanadi:
holat, AI bahosi, o'choqlar jadvali, dastlabki 4 o'choq tasviri, yakuniy qaror, radiolog, konsultatsiyalar, ogohlantirish.
Shrift: Times New Roman (tizimdagi). Linux serverda Times New Roman bo'lmasa — u bilan bir xil o'lchamli Liberation Serif,
u ham bo'lmasa DejaVu Serif (uzlungct/web/fonts, erkin litsenziya). Times New Roman litsenziyasi uni dastur bilan tarqatishga
ruxsat bermaydi, shuning uchun u loyihaga qo'shilmagan. Barcha shriftlar o'zbek (‘ ’ « ») va kirill harflarini qamraydi.
"""
from __future__ import annotations

import io
import json
import os
import time
from pathlib import Path

from fpdf import FPDF
from fpdf.fonts import FontFace

from .report import CONS, TXT, _rng, _thumb_png, caveats

FONTS = Path(__file__).parent / "fonts"
_WIN = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
FONT_CANDIDATES = [   # (oddiy, qalin) — birinchi topilgani ishlatiladi
    (_WIN / "times.ttf", _WIN / "timesbd.ttf"),
    (Path("/usr/share/fonts/truetype/msttcorefonts/Times_New_Roman.ttf"), Path("/usr/share/fonts/truetype/msttcorefonts/Times_New_Roman_Bold.ttf")),
    (Path("/usr/share/fonts/truetype/msttcorefonts/times.ttf"), Path("/usr/share/fonts/truetype/msttcorefonts/timesbd.ttf")),
    (Path("/Library/Fonts/Times New Roman.ttf"), Path("/Library/Fonts/Times New Roman Bold.ttf")),
    (Path("/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf"), Path("/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf")),
    (Path("/usr/share/fonts/truetype/liberation2/LiberationSerif-Regular.ttf"), Path("/usr/share/fonts/truetype/liberation2/LiberationSerif-Bold.ttf")),
    (Path("/usr/share/fonts/liberation-serif/LiberationSerif-Regular.ttf"), Path("/usr/share/fonts/liberation-serif/LiberationSerif-Bold.ttf")),
    (FONTS / "DejaVuSerif.ttf", FONTS / "DejaVuSerif-Bold.ttf"),
]


def pdf_font():
    """Hisobot uchun shrift juftligi (oddiy, qalin): Times New Roman → Liberation Serif → DejaVu Serif."""
    for reg, bold in FONT_CANDIDATES:
        if reg.exists() and bold.exists():
            return reg, bold
    raise RuntimeError("PDF uchun shrift topilmadi")
ACC = (11, 107, 203)
INK = (20, 32, 43)
MUTE = (83, 97, 111)


class _PDF(FPDF):
    def __init__(self, footer_text):
        super().__init__(orientation="P", unit="mm", format="A4")
        self._ft = footer_text
        reg, bold = pdf_font()
        self.add_font("dv", "", str(reg))
        self.add_font("dv", "B", str(bold))
        self.set_margins(15, 14, 15); self.set_auto_page_break(True, margin=16)

    def multi_cell(self, *a, **k):                # matn chapga tekislanadi (kenglik bo'yicha cho'zilmaydi)
        k.setdefault("align", "L")
        return super().multi_cell(*a, **k)

    def footer(self):
        self.set_y(-11); self.set_font("dv", "", 9); self.set_text_color(*MUTE)
        self.cell(0, 5, f"{self._ft}   ·   {self.page_no()} / {{nb}}", align="C")


def _box(pdf: FPDF, title: str, lines: list[tuple[str, str]], fill=(244, 247, 250)):
    """Sarlavhali ramka: lines — (qalin yorliq, qiymat) juftliklari."""
    pdf.set_fill_color(*fill); pdf.set_draw_color(184, 195, 207)
    x0, y0 = pdf.get_x(), pdf.get_y()
    pdf.set_font("dv", "B", 12); pdf.set_text_color(*INK)
    pdf.multi_cell(0, 6, title, new_x="LMARGIN", new_y="NEXT", fill=True, padding=(1.5, 3, 0, 3))
    for lab, val in lines:
        pdf.set_font("dv", "", 11)
        pdf.multi_cell(0, 5.8, f"**{lab}:** {val}" if lab else val, markdown=True, new_x="LMARGIN", new_y="NEXT", fill=True,
                       padding=(0.5, 3, 0.5, 3))
    pdf.rect(x0, y0, pdf.w - pdf.l_margin - pdf.r_margin, pdf.get_y() - y0 + 1.5)
    pdf.ln(4)


def _md(s) -> str:
    """markdown=True da ** va __ belgilarini oddiy matn sifatida saqlash."""
    return str(s if s is not None else "").replace("**", "* *").replace("__", "_ _")


def render_report_pdf(case_dir: Path, job: dict, settings: dict, lang: str = "uz", consults=None, patient=None) -> bytes:
    """patient — patient.parse() natijasi (F.I.Sh., tug'ilgan sana): faqat PDF ga yoziladi, saqlanmaydi."""
    L = TXT[lang]
    rep = json.load(open(case_dir / "report.json", encoding="utf-8"))
    rv = json.load(open(case_dir / "review.json", encoding="utf-8")) if (case_dir / "review.json").exists() else {}
    dmap = {l["id"]: l for l in rv.get("lesions", [])}
    pt = rep.get("patient", {}); inp = rep.get("input", {})
    final = rep.get("status") == "final"
    src = job["params"].get("case") or job["params"].get("file") or ""
    pdf = _PDF(L["title"])
    pdf.set_title(L["title"]); pdf.set_author(rv.get("radiologist", "") or "UzLungMSKT"); pdf.set_creator("UzLungMSKT")
    pdf.add_page()

    # sarlavha va holat belgisi
    pdf.set_font("dv", "B", 16); pdf.set_text_color(*INK)
    pdf.multi_cell(0, 8, L["title"], new_x="LMARGIN", new_y="NEXT")
    if final:
        pdf.set_fill_color(215, 240, 217); pdf.set_draw_color(46, 125, 50); pdf.set_text_color(27, 94, 32)
    else:
        pdf.set_fill_color(253, 231, 200); pdf.set_draw_color(232, 113, 10); pdf.set_text_color(140, 60, 0)
    pdf.set_font("dv", "B", 12); pdf.set_line_width(0.5)
    pdf.multi_cell(0, 8, L["final"] if final else L["draft"], border=1, fill=True, new_x="LMARGIN", new_y="NEXT", padding=(0, 3, 0, 3))
    pdf.set_line_width(0.2); pdf.ln(2)
    if patient:
        from .patient import age, full_name
        b = patient["birth"]
        pdf.set_font("dv", "", 12); pdf.set_text_color(*INK)
        if patient.get("id"):
            pdf.multi_cell(0, 6.2, f"**{L['pid']}:** {patient['id']}", markdown=True, new_x="LMARGIN", new_y="NEXT")
        pdf.multi_cell(0, 6.2, f"**{L['pt']}:** {_md(full_name(patient))}", markdown=True, new_x="LMARGIN", new_y="NEXT")
        pdf.multi_cell(0, 6.2, f"**{L['born']}:** {b:%d.%m.%Y} ({L['age'].format(n=age(b))})", markdown=True, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1.5)

    pdf.set_font("dv", "", 10); pdf.set_text_color(*MUTE)
    pdf.multi_cell(0, 5.0, f"{L['inst']}: {settings.get('institution', '') or '—'}   |   {L['exam']}: {src or '—'}   |   "
                           f"{L['job']}: {job['id']}   |   {L['date']}: {time.strftime('%d.%m.%Y %H:%M')}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1.5)
    pdf.set_font("dv", "", 11); pdf.set_text_color(*INK)
    pdf.multi_cell(0, 5.8, f"{L['input']}: {L['src'].get(inp.get('source', 'volume'), '')}.  {L['model']}: **{_md(rep.get('model'))}**;  "
                           f"{L['n']}: **{rep['n_lesions']}**;  {L['time']}: {rep.get('seconds', '?')} {L['sec']}.", markdown=True,
                   new_x="LMARGIN", new_y="NEXT")
    gt = rep.get("vs_ground_truth")
    if gt:
        pdf.multi_cell(0, 5.8, f"**{L['gt']}:** Dice = {gt['dice']:.3f}, HD95 = {gt['hd95_mm']:.1f} {L['mm']}", markdown=True,
                       new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    # AI bahosi
    if pt:
        prob = f"{pt['model_prob_pct']:.1f} %" if pt.get("model_prob_pct") is not None else (_rng(pt.get("rads_risk_pct")) + " %" if pt.get("rads_risk_pct") else "—")
        lines = [(L["aic"], L["conc"].get(pt.get("ai_conclusion"), "—")),
                 (L["prob"], f"{prob} ({L['srcM'] if pt.get('model_prob_pct') is not None else L['srcR']})"),
                 (L["rads"], str(pt.get("lung_rads", "—")))]
        if pt.get("reliability") == "low":
            lines.append(("", L["low"]))
        for _w in caveats(L, pt, rep):
            lines.append(("", _w))
        _box(pdf, L["ai"], lines)

    # o'choqlar jadvali
    pdf.set_font("dv", "", 10); pdf.set_text_color(*INK); pdf.set_draw_color(184, 195, 207)
    head = FontFace(emphasis="BOLD", color=(255, 255, 255), fill_color=ACC, size_pt=9)
    with pdf.table(col_widths=(7, 15, 19, 19, 15, 18, 14, 33), text_align="CENTER", line_height=5.4, headings_style=head,
                   cell_fill_color=(244, 247, 250), cell_fill_mode="ROWS") as tbl:
        r0 = tbl.row()
        for c in L["cols"]:
            r0.cell(c)
        for l in rep["lesions"]:
            r = dmap.get(l["id"], {})
            risk = f"{l['model_prob_pct']:.1f}" if l.get("model_prob_pct") is not None else _rng(l.get("rads_risk_pct"))
            row = tbl.row()
            for v in (l["id"], f"{l['volume_ml']:.2f}", f"{l['eq_diameter_mm']:.1f}", f"{l.get('sphericity', float('nan')):.2f}",
                      f"{l.get('mean_hu', float('nan')):.0f}", l.get("lung_rads", "—"), risk, L["dec"].get(r.get("decision"))):
                row.cell(str(v))
    pdf.ln(4)

    # dastlabki 4 o'choq tasviri
    les = rep["lesions"][:4]
    if les and (case_dir / "ct_1mm.nii.gz").exists() and (case_dir / "mask_1mm.nii.gz").exists():
        w = (pdf.w - pdf.l_margin - pdf.r_margin - 3 * 4) / 4
        if pdf.get_y() + w + 10 > pdf.h - pdf.b_margin:
            pdf.add_page()
        y = pdf.get_y()
        for i, l in enumerate(les):
            x = pdf.l_margin + i * (w + 4)
            pdf.image(io.BytesIO(_thumb_png(case_dir, l["centroid_zyx_vox"][0])), x=x, y=y, w=w)
            pdf.set_xy(x, y + w + 0.8); pdf.set_font("dv", "", 9.5); pdf.set_text_color(*MUTE)
            pdf.cell(w, 4, f"{L['les']} #{l['id']}", align="C")
        pdf.set_xy(pdf.l_margin, y + w + 7)

    # yakuniy qaror, radiolog va xulosa
    _box(pdf, L["fin"], [(L["fdx"], L["dx"].get(rv.get("final_diagnosis"), "—")),
                         (L["frads"], _md(rv.get("final_lung_rads") or "—")),
                         (L["rec"], _md(rv.get("recommendation", "") or "—"))])
    pdf.set_font("dv", "", 11); pdf.set_text_color(*INK)
    pdf.multi_cell(0, 5.8, f"**{L['rad']}:** {_md(rv.get('radiologist', '') or settings.get('radiologist', '') or '—')}", markdown=True,
                   new_x="LMARGIN", new_y="NEXT")
    pdf.multi_cell(0, 5.8, f"**{L['concl']}:** {_md(rv.get('conclusion', '') or '—')}", markdown=True, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    # konsultatsiyalar (faqat ko'rishga huquqi bor foydalanuvchiga tegishlilari — server tanlaydi)
    if consults:
        C = CONS[lang]; ts = lambda t: time.strftime("%d.%m.%Y %H:%M", time.localtime(t))
        lines = []
        for c in consults:
            lines.append(("", f"**{C[c['kind']]}** — {ts(c['created'])}; {C['from']}: {_md(c['from'])}; {C['to']}: {_md(', '.join(c['to']))}"))
            for m in c["messages"]:
                lines.append(("", f"   • {_md(m['author'])} ({ts(m['created'])}): {_md(m['text'])}"))
        _box(pdf, C["title"], lines)

    pdf.set_font("dv", "", 9.5); pdf.set_text_color(*MUTE)
    pdf.multi_cell(0, 4.8, L["disc"], new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())
