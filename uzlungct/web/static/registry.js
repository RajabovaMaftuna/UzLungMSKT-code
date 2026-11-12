// Bemor reyestri (PM-3): MSKT yuklashdan oldin «Bemor» oynasi (qidirish / ro‘yxatga olish → fayl tanlash → tahlil),
// «Tahlil vazifalari» da bemor bo‘yicha qidiruv va guruhlash, bemor kartasi.
// Shaxsiy ma’lumotlar faqat POST tanasi / javob tanasida; URL, localStorage, sessionStorage ga yozilmaydi.
// app.js dagi api, post, esc, toast, fail, openCase, refreshAnJobs funksiyalaridan foydalanadi (chaqirilganda mavjud).
const Registry = (() => {
  const ACCEPT = ".dcm,.dicom,.ima,.zip,.nii,.gz,.mha,.nrrd,.jpg,.jpeg,.png,.bmp,.tif,.tiff,.pdf,.mp4,.avi,.mov,.mkv,.wmv";
  // bayroq emojisi Windows brauzerlarida ko'rinmaydi — mamlakat kodi harflar bilan
  const COUNTRIES = [["UZ", "UZ +998"], ["KZ", "KZ +7"], ["RU", "RU +7"], ["KG", "KG +996"], ["TJ", "TJ +992"], ["TM", "TM +993"],
    ["AF", "AF +93"], ["TR", "TR +90"], ["DE", "DE +49"], ["US", "US +1"], ["INT", "+ …"]];
  let current = null;                 // joriy (oxirgi tanlangan) bemor — faqat sahifa xotirasida
  const pad = n => String(n).padStart(2, "0");
  const dmy = iso => { const [y, m, d] = iso.split("-"); return `${d}.${m}.${y}`; };

  const CSS = `.rgdlg{max-width:620px}.rgdlg .sec{border-top:1px solid var(--line,#dde3ea);margin-top:12px;padding-top:10px}
.rgdlg .res{list-style:none;margin:6px 0 0;padding:0;max-height:210px;overflow:auto}.rgdlg .res li{display:flex;gap:8px;align-items:center;justify-content:space-between;padding:6px 8px;border:1px solid var(--line,#dde3ea);border-radius:6px;margin-bottom:5px}
.rgdlg .res small{color:var(--mute,#53616f);display:block}.rgdlg .ph{display:grid;grid-template-columns:118px 1fr;gap:6px}
.rgdlg .sel{background:var(--ok-soft,#e3f4e6);color:var(--ok,#1b5e20);border-radius:6px;padding:8px 10px;font-weight:600;display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap}
.rgdlg .sel a{color:var(--acc,#0b6bcb);font-weight:400;cursor:pointer}.rgdlg .fb{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}
.rgdlg .fl{list-style:none;margin:4px 0;padding:0;font-size:13px;max-height:140px;overflow:auto}.rgdlg .fl li{display:flex;justify-content:space-between;border-bottom:1px dashed var(--line,#dde3ea);padding:2px 0}
.rgdlg .dup{background:var(--amber-soft,#fff4e5);border:1px solid var(--amber,#f0b46c);border-radius:6px;padding:8px 10px;margin-top:10px}
.rgdlg .drop2{border:2px dashed var(--line,#b8c3cf);border-radius:8px;padding:10px;text-align:center;color:var(--mute,#53616f);font-size:13px}.rgdlg .drop2.over{border-color:var(--acc,#0b6bcb);background:var(--acc-soft,#eef5fd)}`;

  function shell(title) {
    PatientDialog.ensureCss();                     // umumiy oyna uslublari (patient.js)
    if (!document.getElementById("rgCss")) { const st = document.createElement("style"); st.id = "rgCss"; st.textContent = CSS; document.head.appendChild(st); }
    const bg = document.createElement("div"); bg.className = "ptdlg-bg";
    bg.innerHTML = `<div class="ptdlg rgdlg" role="dialog" aria-modal="true" aria-labelledby="rgT"><h3 id="rgT"></h3><div id="rgBody"></div></div>`;
    bg.querySelector("#rgT").textContent = title;
    const prevFocus = document.activeElement;
    let onClose = () => {};
    function close(v) { bg.remove(); document.removeEventListener("keydown", onKey, true); if (prevFocus && prevFocus.focus) prevFocus.focus(); onClose(v); }
    function onKey(e) {
      if (e.key === "Escape") { e.preventDefault(); close(null); }
      if (e.key === "Tab") {
        const f = [...bg.querySelectorAll("input,select,button,a[href],a[data-act],textarea")].filter(x => !x.disabled && x.offsetParent !== null);
        if (!f.length) return;
        if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
        else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
      }
    }
    document.addEventListener("keydown", onKey, true);
    bg.addEventListener("mousedown", e => { if (e.target === bg) close(null); });
    document.body.appendChild(bg);
    return { bg, body: bg.querySelector("#rgBody"), close, setOnClose: f => { onClose = f; } };
  }

  // --- bemor shakli (ro‘yxatga olish / tahrirlash)
  function formHtml(withConsent) {
    const months = Array.from({ length: 12 }, (_, i) => `<option value="${i + 1}">${esc(t("pt.m" + (i + 1)))}</option>`).join("");
    const cc = COUNTRIES.map(([v, l]) => `<option value="${v}">${esc(l)}</option>`).join("");
    return `<label for="rgLast">${esc(t("pt.last"))}</label><input id="rgLast" maxlength="60" autocomplete="off" spellcheck="false"><div class="e" id="rgLastE" aria-live="polite"></div>
<label for="rgFirst">${esc(t("pt.first"))}</label><input id="rgFirst" maxlength="60" autocomplete="off" spellcheck="false"><div class="e" id="rgFirstE" aria-live="polite"></div>
<label for="rgMid">${esc(t("pt.middle"))}</label><input id="rgMid" maxlength="60" autocomplete="off" spellcheck="false">
<label class="chk"><input type="checkbox" id="rgNoMid"><span>${esc(t("pt.noMiddle"))}</span></label><div class="e" id="rgMidE" aria-live="polite"></div>
<label id="rgBL">${esc(t("pt.birth"))}</label><div class="bd" role="group" aria-labelledby="rgBL">
<input id="rgD" inputmode="numeric" maxlength="2" autocomplete="off" placeholder="${esc(t("pt.day"))}" aria-label="${esc(t("pt.day"))}">
<select id="rgM" aria-label="${esc(t("pt.month"))}"><option value="">${esc(t("pt.month"))}</option>${months}</select>
<input id="rgY" inputmode="numeric" maxlength="4" autocomplete="off" placeholder="${esc(t("pt.year"))}" aria-label="${esc(t("pt.year"))}"></div><div class="e" id="rgBE" aria-live="polite"></div>
<label for="rgPh">${esc(t("pr2.phone"))}</label><div class="ph"><select id="rgCc" aria-label="${esc(t("pr2.country"))}">${cc}</select>
<input id="rgPh" inputmode="tel" maxlength="24" autocomplete="off" placeholder="${esc(t("pr2.phonePh"))}"></div>
<label class="chk"><input type="checkbox" id="rgNoPh"><span>${esc(t("pr2.noPhone"))}</span></label><div class="e" id="rgPhE" aria-live="polite"></div>
${withConsent ? `<label class="chk"><input type="checkbox" id="rgConsent"><span>${esc(t("pr2.consent"))}</span></label><div class="e" id="rgConsentE"></div>` : ""}`;
  }

  function bindForm(root, btn, withConsent, preset) {
    const q = s => root.querySelector(s), touched = new Set();
    if (preset) {
      q("#rgLast").value = preset.last; q("#rgFirst").value = preset.first;
      if (preset.middle) q("#rgMid").value = preset.middle; else q("#rgNoMid").checked = true;
      const [y, m, d] = preset.birth.split("-"); q("#rgD").value = String(+d); q("#rgM").value = String(+m); q("#rgY").value = y;
      if (preset.phone) { q("#rgCc").value = "INT"; q("#rgPh").value = preset.phone; } else q("#rgNoPh").checked = true;
    }
    function check() {
      const r = {}, err = {};
      for (const [id, key] of [["#rgLast", "last"], ["#rgFirst", "first"]]) {
        const v = PatientDialog.normName(q(id).value); r[key] = v;
        err[key] = !v ? "pt.errReq" : (PatientDialog.validName(v) ? "" : "pt.errName");
      }
      const noMid = q("#rgNoMid").checked; q("#rgMid").disabled = noMid;
      const mv = PatientDialog.normName(q("#rgMid").value); r.middle = noMid ? null : mv;
      err.middle = noMid ? "" : (!mv ? "pt.errReq" : (PatientDialog.validName(mv) ? "" : "pt.errName"));
      const b = PatientDialog.birthCheck(q("#rgD").value.trim(), q("#rgM").value, q("#rgY").value.trim());
      err.birth = b.err || ""; r.birth = b.iso;
      const noPh = q("#rgNoPh").checked; q("#rgPh").disabled = q("#rgCc").disabled = noPh;
      const ph = q("#rgPh").value.trim(), cc = q("#rgCc").value, digits = ph.replace(/\D/g, "");
      if (noPh) { r.phone = null; err.phone = ""; }
      else if (!ph) err.phone = "pt.errReq";
      else if (!/^\+?[\d\s()\-]{5,24}$/.test(ph) || digits.length < 5 || digits.length > 15 || (cc === "INT" && !ph.startsWith("+"))) err.phone = "pr2.errPhone";
      else { err.phone = ""; r.phone = ph; r.region = cc === "INT" ? null : cc; }
      if (withConsent) { r.consent = q("#rgConsent").checked; err.consent = r.consent ? "" : "pr2.errConsent"; }
      const show = (inputs, eid, k, keys) => {
        const vis = keys.some(x => touched.has(x)) ? err[k] : "";
        q(eid).textContent = vis ? t(vis) : ""; inputs.forEach(i => i.classList.toggle("bad", !!vis));
      };
      show([q("#rgLast")], "#rgLastE", "last", ["rgLast"]); show([q("#rgFirst")], "#rgFirstE", "first", ["rgFirst"]);
      show([q("#rgMid")], "#rgMidE", "middle", ["rgMid"]); show([q("#rgD"), q("#rgM"), q("#rgY")], "#rgBE", "birth", ["rgD", "rgM", "rgY"]);
      show([q("#rgPh")], "#rgPhE", "phone", ["rgPh"]);
      if (withConsent) show([], "#rgConsentE", "consent", ["rgConsent"]);
      const ok = !Object.values(err).some(Boolean); btn.disabled = !ok;
      return ok ? r : null;
    }
    ["input", "change"].forEach(ev => root.addEventListener(ev, e => { if (e.target.id) touched.add(e.target.id); check(); }));
    root.addEventListener("focusout", e => { if (e.target.id && e.target.value) touched.add(e.target.id); check(); });
    check();
    return { check, touchAll: () => { ["rgLast", "rgFirst", "rgMid", "rgD", "rgM", "rgY", "rgPh", "rgConsent"].forEach(x => touched.add(x)); return check(); },
             phoneError: msg => { q("#rgPhE").textContent = msg; q("#rgPh").classList.add("bad"); } };
  }

  async function postJson(url, body) {
    const r = await fetch(url, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json", "X-UzLungCT": "1" }, body: JSON.stringify(body) });
    let j = null; try { j = await r.json(); } catch (e) {}
    if (r.status === 401) { showLogin(); throw new Error(t("au.expired")); }
    return { status: r.status, ok: r.ok, data: j };
  }
  const errMsg = d => d && I18N.uz["err." + d] ? t("err." + d) : t("c.error");

  // --- tahlil oqimi: 1-qadam (bemor) → 2-qadam (fayllar) → tahlil
  // onPicked berilsa — faqat bemor tanlanadi (fayl bosqichi yo'q): avvalgi tahlilni bemorga biriktirish uchun
  function openUpload(dropped, onPicked) {
    const D = shell(t(onPicked ? "pr2.attachTitle" : "pr2.title"));
    let patient = null, files = dropped ? [...dropped] : [];   // bemor har safar ongli tanlanadi (noto‘g‘ri bemorga biriktirmaslik uchun)
    D.setOnClose(() => { files = []; });
    const pick = () => { if (onPicked) { const p = patient; D.close(true); onPicked(p); } else renderStep2(); };
    const renderStep1 = () => {
      D.body.innerHTML = `<p class="n">${esc(t("pr2.note"))}</p>
<label for="rgQ">${esc(t("pr2.search"))}</label><input id="rgQ" type="search" autocomplete="off" placeholder="${esc(t("pr2.searchPh"))}">
<ul class="res" id="rgRes"></ul>${current ? `<button type="button" id="rgLastBtn">${esc(t("pr2.lastPatient"))}: ${esc(current.fio)} · ${esc(current.id)}</button>` : ""}
<div class="sec"><h3 style="font-size:16px">${esc(t("pr2.newTitle"))}</h3><form id="rgForm" novalidate autocomplete="off">${formHtml(true)}
<div id="rgDup"></div><div class="act"><button type="button" id="rgCancel">${esc(t("au.cancel"))}</button><button type="submit" class="p" id="rgReg" disabled>${esc(t("pr2.register"))}</button></div></form></div>`;
      const q = s => D.body.querySelector(s);
      q("#rgCancel").onclick = () => D.close(null);
      if (q("#rgLastBtn")) q("#rgLastBtn").onclick = () => { patient = current; pick(); };
      const F = bindForm(q("#rgForm"), q("#rgReg"), true);
      let timer = null;
      q("#rgQ").oninput = () => {
        clearTimeout(timer);
        timer = setTimeout(async () => {
          const v = q("#rgQ").value.trim();
          if (v.length < 2) { q("#rgRes").innerHTML = ""; return; }
          const r = await postJson("/api/patients/search", { q: v });
          if (!r.ok) { q("#rgRes").innerHTML = `<li>${esc(errMsg(r.data?.detail))}</li>`; return; }
          q("#rgRes").innerHTML = r.data.length ? r.data.map(p => `<li><span><b>${esc(p.fio)}</b> · ID ${esc(p.id)}<small>${esc(dmy(p.birth))} · ${esc(p.phone || p.phone_masked || "—")} · ${esc(t("pr2.jobsN").replace("{n}", p.jobs.length))}</small></span>
<button type="button" data-pid="${esc(p.id)}">${esc(t("pr2.select"))}</button></li>`).join("") : `<li>${esc(t("pr2.none"))}</li>`;
          q("#rgRes").querySelectorAll("button[data-pid]").forEach(b => b.onclick = async () => {
            const u = await postJson(`/api/patients/${b.dataset.pid}/use`, {});
            if (!u.ok) return toast(errMsg(u.data?.detail));
            patient = current = u.data.patient; pick();
          });
        }, 300);
      };
      q("#rgForm").onsubmit = async e => {
        e.preventDefault();
        const r = F.touchAll(); if (!r) return;
        q("#rgReg").disabled = true;
        try {
          const res = await postJson("/api/patients", r);
          if (res.status === 409 && res.data?.detail === "possible_duplicate") return showDup(r, res.data.candidates);
          if (!res.ok) { if (res.data?.detail === "bad_phone") F.phoneError(t("err.bad_phone")); else toast(errMsg(res.data?.detail)); return; }
          patient = current = res.data.patient;
          toast(t(res.data.existing ? "pr2.existing" : "pr2.registered").replace("{id}", patient.id));
          pick();
        } finally { if (q("#rgReg")) F.check(); }
      };
      const showDup = (r, cands) => {
        q("#rgDup").innerHTML = `<div class="dup"><b>${esc(t("pr2.dupTitle"))}</b><p class="n">${esc(t("pr2.dupText"))}</p><ul class="res">${cands.map(c =>
          `<li><span>ID ${esc(c.id)}<small>${esc(c.phone_masked || "—")}${c.n_jobs != null ? " · " + esc(t("pr2.jobsN").replace("{n}", c.n_jobs)) : ""}</small></span>
<button type="button" data-same="${esc(c.id)}">${esc(t("pr2.same"))}</button></li>`).join("")}</ul>
<button type="button" id="rgForce">${esc(t("pr2.newAnyway"))}</button></div>`;
        q("#rgDup").querySelectorAll("button[data-same]").forEach(b => b.onclick = async () => {
          const u = await postJson(`/api/patients/${b.dataset.same}/use`, { last: r.last, first: r.first, middle: r.middle, birth: r.birth });
          if (!u.ok) return toast(errMsg(u.data?.detail));
          patient = current = u.data.patient; pick();
        });
        q("#rgForce").onclick = async () => {
          const res = await postJson("/api/patients", { ...r, force_new: true });
          if (!res.ok) return toast(errMsg(res.data?.detail));
          patient = current = res.data.patient; toast(t("pr2.registered").replace("{id}", patient.id)); pick();
        };
      };
      (q("#rgQ")).focus();
    };
    const renderStep2 = () => {
      D.body.innerHTML = `<div class="sel"><span>${esc(t("pr2.selected"))}: ${esc(patient.fio)} · ID ${esc(patient.id)} · ${esc(dmy(patient.birth))}</span><a data-act="chg" tabindex="0" role="button">${esc(t("pr2.change"))}</a></div>
<p class="n" style="margin-top:8px">${esc(t("pr2.step2"))}</p>
<div class="fb"><button type="button" id="rgPickF">${esc(t("pr2.pickFile"))}</button><button type="button" id="rgPickD">${esc(t("an.folder"))}</button></div>
<input type="file" id="rgFile" multiple accept="${ACCEPT}" hidden><input type="file" id="rgDir" webkitdirectory directory multiple hidden>
<div class="drop2" id="rgDrop">${esc(t("an.drop"))}</div>
<label>${esc(t("pr2.files"))}</label><ul class="fl" id="rgFl"></ul>
<label for="rgModel">${esc(t("an.model"))}</label><select id="rgModel">${$("#upModel").innerHTML}</select>
<div class="act"><button type="button" id="rgCancel2">${esc(t("au.cancel"))}</button><button type="button" class="p" id="rgOk" disabled>${esc(t("an.run"))}</button></div>`;
      const q = s => D.body.querySelector(s);
      q("#rgModel").value = $("#upModel").value;
      const list = () => {
        q("#rgFl").innerHTML = files.length ? files.slice(0, 8).map(f => `<li>${esc(f.webkitRelativePath || f.name)}<span>${fsize(f.size)}</span></li>`).join("") +
          (files.length > 8 ? `<li>… +${files.length - 8}<span>${fsize(files.reduce((a, f) => a + f.size, 0))}</span></li>` : "") : `<li>${esc(t("pr2.noFiles"))}</li>`;
        q("#rgOk").disabled = !files.length || !q("#rgModel").value;
      };
      q("[data-act=chg]").onclick = () => renderStep1();
      q("[data-act=chg]").onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); renderStep1(); } };
      q("#rgPickF").onclick = () => q("#rgFile").click();
      q("#rgPickD").onclick = () => q("#rgDir").click();
      q("#rgFile").onchange = () => { files = [...q("#rgFile").files]; list(); };
      q("#rgDir").onchange = () => { files = [...q("#rgDir").files]; list(); };
      ["dragenter", "dragover"].forEach(ev => q("#rgDrop").addEventListener(ev, e => { e.preventDefault(); q("#rgDrop").classList.add("over"); }));
      ["dragleave", "drop"].forEach(ev => q("#rgDrop").addEventListener(ev, e => { e.preventDefault(); q("#rgDrop").classList.remove("over"); }));
      q("#rgDrop").addEventListener("drop", e => { if (e.dataTransfer.files.length) { files = [...e.dataTransfer.files]; list(); } });
      q("#rgModel").onchange = list;
      q("#rgCancel2").onclick = () => D.close(null);
      q("#rgOk").onclick = async () => {
        if (!files.length) return toast(t("an.noFile"));
        const fd = new FormData(); files.forEach(f => fd.append("files", f)); fd.append("ckpt", q("#rgModel").value); fd.append("patient_id", patient.id);
        q("#rgOk").disabled = true;
        try {
          await api("/api/analyze", { method: "POST", body: fd });
          $("#upModel").value = q("#rgModel").value;
          D.close(true); toast(t("an.started")); showCurrent(); refreshAnJobs();
        } catch (e) { fail(e); list(); }
      };
      list(); q("#rgPickF").focus();
    };
    renderStep1();
  }

  function showCurrent() {
    const el = $("#upPatient"); if (!el) return;
    el.hidden = !current;
    el.textContent = current ? `${t("pr2.current")}: ${current.fio} · ID ${current.id}` : "";
  }

  // --- «Tahlil vazifalari»: bemor bo‘yicha qidiruv va guruhlash
  const aic = a => a ? `<span class="aic-${esc(a)}">${esc(t("aic." + a))}</span>` : "—";
  const when = ts => ts ? new Date(ts * 1000).toLocaleString(LOCALE(), { dateStyle: "short", timeStyle: "short" }) : "";
  function groupHtml(p) {
    const rows = p.jobs.map(j => `<tr><td>${esc(when(j.created))}</td><td>${status(j.status)}${j.shared_with_me ? ` <span class="badge cst-new">${esc(t("j.shared"))}</span>` : ""}</td>
<td>${esc(j.lung_rads || "—")}</td><td>${aic(j.ai_conclusion)}</td><td>${j.report_status ? esc(t("status." + j.report_status)) : "—"}</td>
<td class="acts">${j.status === "done" ? `<a href="#" data-open="${esc(j.jid)}">${esc(t("v.open"))}</a> <a href="/api/case/${esc(j.jid)}/report?lang=${LANG}" target="_blank" rel="noopener">${esc(t("v.report"))}</a>` : ""}</td></tr>`).join("");
    return `<div class="pgroup"><div class="phead"><a href="#" data-card="${esc(p.id)}"><b>${esc(p.fio)}</b></a> · ID ${esc(p.id)} · ${esc(dmy(p.birth))} · ${esc(p.phone || p.phone_masked || "—")}
 · <span class="badge">${esc(t("pr2.jobsN").replace("{n}", p.jobs.length))}</span>${p.similar.length ? ` <span class="badge b-error" title="${esc(p.similar.join(", "))}">${esc(t("pr2.similar"))}: ${esc(p.similar.join(", "))}</span>` : ""}</div>
${p.jobs.length ? `<table><tr><th>${esc(t("j.when"))}</th><th>${esc(t("cs.state"))}</th><th>Lung-RADS</th><th>${esc(t("pr2.aic"))}</th><th>${esc(t("pr2.reportSt"))}</th><th></th></tr>${rows}</table>` : `<p class="hint">${esc(t("c.none"))}</p>`}</div>`;
  }
  function bindGroups(root) {
    root.querySelectorAll("[data-open]").forEach(a => a.onclick = e => { e.preventDefault(); openCase(a.dataset.open); });
    root.querySelectorAll("[data-card]").forEach(a => a.onclick = e => { e.preventDefault(); openCard(a.dataset.card); });
  }
  let sTimer = null, lastQ = "";
  async function runSearch(force) {
    const v = $("#anSearch").value.trim();
    if (!force && v === lastQ) return; lastQ = v;
    if (v.length < 2) { $("#anSearchRes").hidden = true; $("#anJobs").hidden = false; return; }
    const r = await postJson("/api/patients/search", { q: v });
    $("#anJobs").hidden = true; $("#anSearchRes").hidden = false;
    if (!r.ok) { $("#anSearchRes").textContent = errMsg(r.data?.detail); return; }
    $("#anSearchRes").innerHTML = r.data.length ? r.data.map(groupHtml).join("") : `<p class="hint">${esc(t("pr2.none"))}</p>`;
    bindGroups($("#anSearchRes"));
  }

  // --- bemor kartasi: ma’lumot, tahlillar, tahrirlash / o‘chirish / birlashtirish
  async function openCard(pid) {
    let p;
    try { p = await api(`/api/patients/${pid}`); } catch (e) { return fail(e); }
    const D = shell(t("pr2.card"));
    const render = () => {
      D.body.innerHTML = `<div class="sel"><span>${esc(p.fio)} · ID ${esc(p.id)}</span></div>
<p>${esc(t("pt.birth"))}: <b>${esc(dmy(p.birth))}</b> · ${esc(t("pr2.phone"))}: <b>${esc(p.phone || p.phone_masked || "—")}</b></p>
${groupHtml(p)}
${p.similar.length && p.can_delete ? `<div class="dup">${esc(t("pr2.similar"))}: ${p.similar.map(x => `<button type="button" data-merge="${esc(x)}">${esc(t("pr2.merge"))} ${esc(x)} → ${esc(p.id)}</button>`).join(" ")}</div>` : ""}
<div class="act">${p.can_delete ? `<button type="button" id="rgDel" class="danger">${esc(t("pr2.del"))}</button>` : ""}${p.can_edit ? `<button type="button" id="rgEdit">${esc(t("pr2.edit"))}</button>` : ""}<button type="button" class="p" id="rgClose">${esc(t("pr2.close"))}</button></div>`;
      bindGroups(D.body);
      D.body.querySelectorAll("[data-open]").forEach(a => a.addEventListener("click", () => D.close(null)));
      D.body.querySelector("#rgClose").onclick = () => D.close(null);
      if (D.body.querySelector("#rgDel")) D.body.querySelector("#rgDel").onclick = async () => {
        if (!confirm(t("pr2.delConfirm"))) return;
        try { await api(`/api/patients/${p.id}`, { method: "DELETE" }); toast(t("pr2.deleted")); D.close(null); runSearch(true); } catch (e) { fail(e); }
      };
      D.body.querySelectorAll("[data-merge]").forEach(b => b.onclick = async () => {
        if (!confirm(t("pr2.mergeConfirm").replace("{a}", b.dataset.merge).replace("{b}", p.id))) return;
        try { await post(`/api/patients/${b.dataset.merge}/merge`, { into: p.id }); p = await api(`/api/patients/${p.id}`); render(); runSearch(true); } catch (e) { fail(e); }
      });
      if (D.body.querySelector("#rgEdit")) D.body.querySelector("#rgEdit").onclick = () => {
        D.body.innerHTML = `<form id="rgEf" novalidate autocomplete="off">${formHtml(false)}<div class="act"><button type="button" id="rgBack">${esc(t("au.cancel"))}</button><button type="submit" class="p" id="rgSave">${esc(t("st.save"))}</button></div></form>`;
        const F = bindForm(D.body.querySelector("#rgEf"), D.body.querySelector("#rgSave"), false, p);
        D.body.querySelector("#rgBack").onclick = render;
        D.body.querySelector("#rgEf").onsubmit = async e => {
          e.preventDefault(); const r = F.touchAll(); if (!r) return;
          const res = await postJson(`/api/patients/${p.id}`, r);
          if (!res.ok) { if (res.data?.detail === "bad_phone") F.phoneError(t("err.bad_phone")); else toast(errMsg(res.data?.detail)); return; }
          p = await api(`/api/patients/${p.id}`); if (current && current.id === p.id) { current = p; showCurrent(); }
          toast(t("pr2.saved")); render(); runSearch(true);
        };
      };
    };
    render();
  }

  // avvalgi (bemor biriktirilmagan) tahlilni bemorga biriktirish — egasi yoki administrator
  function attachJob(jid, after) {
    openUpload(null, async p => {
      const r = await postJson(`/api/jobs/${jid}/patient`, { patient_id: p.id });
      if (!r.ok) return toast(errMsg(r.data?.detail));
      toast(t("pr2.attached").replace("{id}", p.id));
      if (after) after(p);
    });
  }

  function init() {
    const openIt = e => { e.preventDefault(); openUpload(null); };
    $("#drop").addEventListener("click", openIt);
    $("#drop").onkeydown = e => { if (e.key === "Enter" || e.key === " ") openIt(e); };
    $("#upFolderBtn").addEventListener("click", openIt);
    ["dragenter", "dragover"].forEach(ev => $("#drop").addEventListener(ev, e => { e.preventDefault(); $("#drop").classList.add("over"); }));
    ["dragleave", "drop"].forEach(ev => $("#drop").addEventListener(ev, e => { e.preventDefault(); $("#drop").classList.remove("over"); }));
    $("#drop").addEventListener("drop", e => { if (e.dataTransfer.files.length) openUpload(e.dataTransfer.files); });
    $("#anSearch").addEventListener("input", () => { clearTimeout(sTimer); sTimer = setTimeout(() => runSearch(false), 300); });
    showCurrent();
  }
  return { init, openUpload, openCard, attachJob, runSearch, showCurrent, get current() { return current; } };
})();
