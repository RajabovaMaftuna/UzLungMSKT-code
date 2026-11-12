// «Bemor ma’lumotlari» oynasi: hisobotni chop etish yoki PDF yuklab olishdan oldin F.I.Sh. va tug‘ilgan sanani so‘raydi.
// Qiymatlar faqat shu hujjat uchun ishlatiladi va hech qayerda saqlanmaydi (localStorage, cookie, URL — yo‘q).
// Tekshiruv qoidalari serverdagi uzlungct/web/patient.py bilan bir xil. i18n.js (t, LANG) dan keyin yuklanadi.
const PatientDialog = (() => {
  const MAX_AGE = 120;
  const NAME_RE = /^\p{L}(?:[\p{L}\p{M}‘ʼ\- ]*[\p{L}\p{M}‘ʼ])?$/u;
  const normName = s => String(s || "").normalize("NFC").replace(/\s+/g, " ").trim()
    .replace(/([oOgG])[`'’ʻ‘ʼ]/g, "$1‘").replace(/(^|[^oOgG])[`'’ʻ]/g, "$1ʼ");
  const validName = s => s.length >= 2 && s.length <= 60 && NAME_RE.test(s) && !/[‘ʼ\- ]{2,}/.test(s);
  const pad = n => String(n).padStart(2, "0");
  const todayD = () => { const d = new Date(); return new Date(d.getFullYear(), d.getMonth(), d.getDate()); };
  const ageOf = (b, on = todayD()) => on.getFullYear() - b.getFullYear() - ((on.getMonth() < b.getMonth() || (on.getMonth() === b.getMonth() && on.getDate() < b.getDate())) ? 1 : 0);

  function birthCheck(d, m, y) {
    if (!d || !m || !y) return { err: "pt.errReq" };
    if (!/^\d{1,2}$/.test(d) || !/^\d{4}$/.test(y)) return { err: "pt.errDate" };
    const dd = +d, mm = +m, yy = +y, b = new Date(yy, mm - 1, dd);
    if (yy < 1000 || b.getFullYear() !== yy || b.getMonth() !== mm - 1 || b.getDate() !== dd) return { err: "pt.errDate" };
    if (b > todayD()) return { err: "pt.errFuture" };
    if (ageOf(b) > MAX_AGE) return { err: "pt.errOld" };
    return { date: b, iso: `${yy}-${pad(mm)}-${pad(dd)}` };
  }

  const CSS = `.ptdlg-bg{position:fixed;inset:0;background:rgba(10,20,30,.55);display:flex;align-items:center;justify-content:center;z-index:9999;padding:16px}
.ptdlg{background:var(--card,#fff);color:var(--ink,#14202b);border-radius:10px;max-width:460px;width:100%;max-height:calc(100vh - 32px);overflow:auto;padding:18px 20px;
font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif;box-shadow:0 10px 40px rgba(0,0,0,.35);box-sizing:border-box}
.ptdlg h3{margin:0 0 6px;font-size:18px}.ptdlg .reg{margin:0 0 8px;padding:6px 9px;border-radius:6px;background:var(--ok-soft,#e3f4e6);color:var(--ok,#1b5e20);font-weight:600}.ptdlg p.n{margin:0 0 12px;color:var(--mute,#53616f);font-size:13px}
.ptdlg label{display:block;margin:8px 0 2px;font-weight:600}.ptdlg input,.ptdlg select{font:inherit;padding:7px 9px;border:1px solid var(--line,#b8c3cf);border-radius:6px;width:100%;box-sizing:border-box;background:var(--card,#fff);color:var(--ink,#14202b)}
.ptdlg .bd{display:grid;grid-template-columns:64px 1fr 84px;gap:6px}.ptdlg .chk{display:flex;gap:6px;align-items:center;font-weight:400;margin-top:4px}
.ptdlg .chk input{width:auto}.ptdlg .e{color:var(--red,#b3261e);font-size:12px;min-height:16px}.ptdlg input.bad,.ptdlg select.bad{border-color:var(--red,#b3261e)}
.ptdlg .act{display:flex;gap:8px;justify-content:flex-end;flex-wrap:wrap;margin-top:14px}
.ptdlg button{font:inherit;padding:8px 14px;border-radius:6px;border:1px solid var(--acc,#0b6bcb);background:var(--card,#fff);color:var(--acc,#0b6bcb);cursor:pointer}
.ptdlg button.p{background:var(--acc,#0b6bcb);color:var(--acc-ink,#fff)}.ptdlg button:disabled{opacity:.45;cursor:not-allowed}
@media print{.ptdlg-bg{display:none!important}}`;

  function ensureCss() {
    if (!document.getElementById("ptdlgCss")) {
      const st = document.createElement("style"); st.id = "ptdlgCss"; st.textContent = CSS; document.head.appendChild(st);
    }
  }

  // preset — reyestrdagi bemor ({id,last,first,middle,birth}): maydonlar to'ldirilib, o'zgartirib bo'lmaydigan qilinadi
  function open(mode, preset) {
    return new Promise(resolve => {
      ensureCss();
      const prevFocus = document.activeElement;
      const bg = document.createElement("div"); bg.className = "ptdlg-bg";
      const months = Array.from({ length: 12 }, (_, i) => `<option value="${i + 1}"></option>`).join("");
      bg.innerHTML = `<form class="ptdlg" role="dialog" aria-modal="true" aria-labelledby="ptT" novalidate autocomplete="off">
<h3 id="ptT"></h3><p class="n" id="ptN"></p><p class="reg" id="ptReg" hidden></p>
<label for="ptLast"></label><input id="ptLast" maxlength="60" autocomplete="off" spellcheck="false"><div class="e" id="ptLastE" aria-live="polite"></div>
<label for="ptFirst"></label><input id="ptFirst" maxlength="60" autocomplete="off" spellcheck="false"><div class="e" id="ptFirstE" aria-live="polite"></div>
<label for="ptMid"></label><input id="ptMid" maxlength="60" autocomplete="off" spellcheck="false">
<label class="chk"><input type="checkbox" id="ptNoMid"><span id="ptNoMidL"></span></label><div class="e" id="ptMidE" aria-live="polite"></div>
<label id="ptBL"></label><div class="bd" role="group" aria-labelledby="ptBL">
<input id="ptD" inputmode="numeric" maxlength="2" autocomplete="off"><select id="ptM"><option value=""></option>${months}</select>
<input id="ptY" inputmode="numeric" maxlength="4" autocomplete="off"></div><div class="e" id="ptBE" aria-live="polite"></div>
<div class="act"><button type="button" id="ptCancel"></button><button type="submit" class="p" id="ptOk" disabled></button></div></form>`;
      const q = s => bg.querySelector(s);
      q("#ptT").textContent = t("pt.title"); q("#ptN").textContent = t("pt.note");
      q("label[for=ptLast]").textContent = t("pt.last"); q("label[for=ptFirst]").textContent = t("pt.first");
      q("label[for=ptMid]").textContent = t("pt.middle"); q("#ptNoMidL").textContent = t("pt.noMiddle");
      q("#ptBL").textContent = t("pt.birth");
      q("#ptD").placeholder = t("pt.day"); q("#ptD").setAttribute("aria-label", t("pt.day"));
      q("#ptY").placeholder = t("pt.year"); q("#ptY").setAttribute("aria-label", t("pt.year"));
      q("#ptM").setAttribute("aria-label", t("pt.month"));
      q("#ptM").options[0].textContent = t("pt.month");
      for (let i = 1; i <= 12; i++) q("#ptM").options[i].textContent = t("pt.m" + i);
      q("#ptCancel").textContent = t("au.cancel");
      q("#ptOk").textContent = mode === "pdf" ? t("v.savePdf") : t("pt.print");
      const touched = new Set();
      function check() {
        const r = {}, err = {};
        for (const [id, key] of [["#ptLast", "last"], ["#ptFirst", "first"]]) {
          const v = normName(q(id).value); r[key] = v;
          err[key] = !v ? "pt.errReq" : (validName(v) ? "" : "pt.errName");
        }
        const noMid = q("#ptNoMid").checked; q("#ptMid").disabled = noMid || !!preset;
        const mv = normName(q("#ptMid").value); r.middle = noMid ? null : mv;
        err.middle = noMid ? "" : (!mv ? "pt.errReq" : (validName(mv) ? "" : "pt.errName"));
        const b = birthCheck(q("#ptD").value.trim(), q("#ptM").value, q("#ptY").value.trim());
        err.birth = b.err || ""; r.birth = b.iso; r.birthDate = b.date;
        const show = (inp, eid, k, keys) => {
          const vis = keys.some(x => touched.has(x)) ? err[k] : "";
          q(eid).textContent = vis ? t(vis) : ""; inp.forEach(i => i.classList.toggle("bad", !!vis));
        };
        show([q("#ptLast")], "#ptLastE", "last", ["ptLast"]); show([q("#ptFirst")], "#ptFirstE", "first", ["ptFirst"]);
        show([q("#ptMid")], "#ptMidE", "middle", ["ptMid"]);
        show([q("#ptD"), q("#ptM"), q("#ptY")], "#ptBE", "birth", ["ptD", "ptM", "ptY"]);
        const ok = !Object.values(err).some(Boolean);
        q("#ptOk").disabled = !ok;
        return ok ? r : null;
      }
      bg.addEventListener("input", e => { if (e.target.id) touched.add(e.target.id); check(); });
      bg.addEventListener("change", e => { if (e.target.id) touched.add(e.target.id); check(); });
      bg.addEventListener("focusout", e => { if (e.target.id && e.target.value) touched.add(e.target.id); check(); });
      function close(v) {
        bg.remove(); document.removeEventListener("keydown", onKey, true);
        if (prevFocus && prevFocus.focus) prevFocus.focus();
        resolve(v);
      }
      function onKey(e) {
        if (e.key === "Escape") { e.preventDefault(); close(null); }
        if (e.key === "Tab") {           // fokus oyna ichida aylanadi
          const f = [...bg.querySelectorAll("input,select,button")].filter(x => !x.disabled);
          if (!f.length) return;
          if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
          else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
        }
      }
      document.addEventListener("keydown", onKey, true);
      q("#ptCancel").onclick = () => close(null);
      bg.addEventListener("mousedown", e => { if (e.target === bg) close(null); });
      q("form").onsubmit = e => {
        e.preventDefault();
        ["ptLast", "ptFirst", "ptMid", "ptD", "ptM", "ptY"].forEach(x => touched.add(x));
        const r = check(); if (r) close(r);
      };
      if (preset) {
        q("#ptLast").value = preset.last; q("#ptFirst").value = preset.first;
        if (preset.middle) q("#ptMid").value = preset.middle; else q("#ptNoMid").checked = true;
        const [yy, mm, dd] = preset.birth.split("-");
        q("#ptD").value = String(+dd); q("#ptM").value = String(+mm); q("#ptY").value = yy;
        bg.querySelectorAll("input,select").forEach(x => { x.disabled = true; });
        q("#ptReg").hidden = false; q("#ptReg").textContent = t("pr2.fromReg").replace("{id}", preset.id);
        check();
      }
      document.body.appendChild(bg);
      (preset ? q("#ptOk") : q("#ptLast")).focus();
    });
  }

  // chop etiladigan blok matni: «FAMILIYA Ism Sharif», «KK.OO.YYYY (NN yosh)»
  const fullName = p => [p.last.toLocaleUpperCase(LANG === "ru" ? "ru" : "uz"), p.first, p.middle].filter(Boolean).join(" ");
  const birthText = p => {
    const b = p.birthDate;
    return `${pad(b.getDate())}.${pad(b.getMonth() + 1)}.${b.getFullYear()} (${t("pt.age").replace("{n}", ageOf(b))})`;
  };

  // PDF: shaxsiy ma’lumotlar faqat POST tanasida (URL da emas); fayl xotiradan yuklab olinadi
  async function downloadPdf(jid, lang, p, btn) {
    const old = btn ? btn.textContent : "";
    if (btn) { btn.disabled = true; btn.textContent = t("pt.busy"); }
    try {
      const r = await fetch(`/api/case/${encodeURIComponent(jid)}/report.pdf`, {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-UzLungCT": "1" },
        body: JSON.stringify({ lang, patient: { last: p.last, first: p.first, middle: p.middle, birth: p.birth } }) });
      if (!r.ok) {
        let d = ""; try { d = (await r.json()).detail; } catch (e) {}
        throw new Error(r.status === 401 ? t("au.expired") : (d && I18N.uz["err." + d] ? t("err." + d) : String(r.status)));
      }
      const cd = r.headers.get("content-disposition") || "", m = /filename="([^"]+)"/.exec(cd);
      const url = URL.createObjectURL(await r.blob());
      const a = document.createElement("a"); a.href = url; a.download = m ? m[1] : "UzLungMSKT_hisobot.pdf";
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = old; }
    }
  }

  return { open, ensureCss, downloadPdf, fullName, birthText, normName, validName, birthCheck };
})();
