// UzLungMSKT brauzer ilovasi (framework'siz, oflayn ishlaydi).
const $ = s => document.querySelector(s);
let ME = null;
const api = async (url, opt = {}) => {
  opt.headers = { ...(opt.headers || {}), "X-UzLungCT": "1" };
  opt.credentials = "same-origin";
  const r = await fetch(url, opt);
  if (r.status === 401 && !url.startsWith("/api/auth/")) { showLogin(); throw new Error(t("au.expired")); }
  if (r.status === 403) { let d = ""; try { d = (await r.clone().json()).detail; } catch (e) {} if (d === "password_change_required") { showPw(true); throw new Error(t("au.pwForced")); } }
  if (!r.ok) { let d = "", rid = ""; try { const j = await r.json(); d = j.detail; rid = j.request_id || ""; } catch (e) {} throw new Error((d && I18N.uz["err." + d] ? t("err." + d) : String(r.status)) + (rid ? " — " + rid : "")); }
  return r.headers.get("content-type")?.includes("json") ? r.json() : r.text();
};
const post = (url, body) => api(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
// AI natijasi uchun ogohlantirishlar: model holati, filtr bilan olib tashlangan o‘choqlar, Lung-RADS cheklovlari (v5)
function aiCaveats(pt, m) {
  const w = [], f = m.filters || {};
  if (pt.model_status === "unavailable" || pt.model_status === "error") w.push(t("rel.nomodel"));
  if ((f.outside_lung || 0) > 0 || (f.over_limit || 0) > 0)
    w.push(t("rel.filtered").replace("{a}", f.outside_lung || 0).replace("{b}", f.over_limit || 0));
  (pt.rads_notes || []).filter(c => c === "mass_ge_30mm" || c === "part_solid_total_diameter").forEach(c => w.push(t("rads.note." + c)));
  if (pt.rads_x_candidate) w.push(t("rads.xcand"));
  return w.map(x => `<p class="warn">${esc(x)}</p>`).join("");
}
const rng = r => !r ? "—" : (r[1] >= 100 ? "> " + r[0] : (r[0] <= 0 ? "< " + r[1] : r[0] + "–" + r[1]));
const fmt = (v, d = 3) => (v === null || v === undefined || Number.isNaN(+v)) ? "—" : (+v).toFixed(d);
function toast(msg) { const el = $("#toast"); el.textContent = msg; el.style.display = "block"; clearTimeout(el._t); el._t = setTimeout(() => el.style.display = "none", 3500); }
const fail = e => { console.error(e); toast(t("c.error") + " (" + e.message + ")"); };
const status = s => `<span class="badge b-${esc(s)}">${esc(t("st." + s))}</span>`;
const splitName = s => t({ train: "c.train", val: "c.val", test: "c.test" }[s] || "") || s;
const mlabel = m => m.pretrain ? `${t("mdl.msd")} · ${m.model}` : t(m.label || m.name);
// klinik model ro'yxatda birinchi turadi (tahlilda standart tanlov)
const mrank = m => m.label === "mdl.clinical" ? 0 : m.pretrain ? 3 : m.label === "mdl.pilot" ? 2 : 1;
const usable = ms => ms.filter(m => !m.pretrain);       // MSD vaznlari faqat «O'qitish» da boshlang'ich vazn sifatida
const byClinical = ms => [...ms].sort((a, b) => mrank(a) - mrank(b) || mlabel(a).localeCompare(mlabel(b)));

// ---------------- tablar va til
document.querySelectorAll("nav button").forEach(b => b.onclick = () => showTab(b.dataset.tab));
function showTab(id) {
  const btn = document.querySelector(`nav button[data-tab="${id}"]`);
  if (btn && btn.style.display === "none") id = "home";
  document.querySelectorAll("nav button").forEach(b => b.classList.toggle("active", b.dataset.tab === id));
  document.querySelectorAll(".tab").forEach(s => s.classList.toggle("active", s.id === id));
  $("#pgTitle").textContent = t("tab." + id); document.title = t("tab." + id) + " · UzLungMSKT";
  if (!ME) return;
  if (id === "users") loadUsers();
  if (id === "home") loadHome(); if (id === "analyze") loadAnalyze(); if (id === "train") loadTrain(); if (id === "eval") loadEval(); if (id === "settings") loadSettings();
  if (id === "stats") loadStats(); if (id === "consult") loadConsult();
}
document.querySelectorAll(".lang button").forEach(b => b.onclick = () => setLang(b.dataset.lang));
window.onLangChange = () => {
  document.querySelectorAll(".lang button").forEach(b => b.classList.toggle("active", b.dataset.lang === LANG));
  if (ME) { $("#uRole").textContent = t("role." + ME.role); const active = document.querySelector(".tab.active")?.id || "home"; showTab(active); }
  if (V.jid) renderCase();
};

// ---------------- bosh sahifa
async function loadHome() {
  try {
    const s = await api("/api/system");
    const gb = v => (v || v === 0) ? v + " " + t("sys.gb") : null;
    // har bir qator mustaqil: torch yuklanmasa ham CPU/RAM/videokarta ko'rsatiladi (PM-9)
    const rows = [["sys.cpuName", s.cpu], ["sys.cpu", s.cpu_threads], ["sys.avx2", s.avx2 === undefined ? null : (s.avx2 ? "✓" : "✗")],
      ["sys.ram", s.ram_gb ? gb(s.ram_gb) + (s.ram_free_gb ? ` (${t("sys.ramFree")} ${gb(s.ram_free_gb)})` : "") : null],
      ["sys.gpu", s.gpu || "—"], ["sys.driver", s.gpu_driver], ["sys.vram", gb(s.vram_gb)], ["sys.vramfree", gb(s.vram_free_gb)],
      ["sys.device", s.device], ["sys.patch", s.seg_profile ? s.seg_profile.patch.join("×") + " / " + s.seg_profile.batch : null],
      ["sys.disk", gb(s.disk_free_gb)], ["sys.torch", s.torch], ["sys.home", s.home]].filter(([, v]) => v !== undefined && v !== null && v !== "");
    let warn = "";
    if (!s.torch) {
      const hint = t("sys.hint." + (s.torch_hint === "dll_missing" ? "dll_missing" : "other"));
      warn = `<p class="warn">${esc(t("sys.torchErr"))} ${esc(hint)}${(s.torch_missing || []).length ? `<br>${esc(t("sys.missing"))}: ${esc(s.torch_missing.join(", "))}` : ""}${s.torch_hint === "dll_missing" ? `<br><a href="https://aka.ms/vs/17/release/vc_redist.x64.exe" target="_blank" rel="noopener noreferrer">${esc(t("sys.vcLink"))}</a>` : ""}${s.errors?.torch ? `<br><small>${esc(s.errors.torch)}</small>` : ""}</p>`;
    } else if (s.gpu_note && I18N.uz["sys.gpuNote." + s.gpu_note]) {
      warn = `<p class="warn">${esc(t("sys.gpuNote." + s.gpu_note))}</p>`;
    }
    const diag = ME?.role === "admin" ? `<p><a href="/api/admin/diagnostics" download>${esc(t("sys.diag"))}</a><br><small>${esc(t("sys.diagHint"))}</small></p>` : "";
    const bar = (label, used, total, unit) => {
      if (!total) return "";
      const p = Math.max(0, Math.min(100, Math.round(used / total * 100))), lvl = p >= 90 ? "hi" : p >= 70 ? "mid" : "ok";
      return `<div class="meter ${lvl}"><div class="mtop"><b>${esc(label)}</b><span>${esc((+used).toFixed(1))} / ${esc((+total).toFixed(1))} ${unit} · ${p}%</span></div><div class="mbar" role="progressbar" aria-valuenow="${p}" aria-valuemin="0" aria-valuemax="100"><i style="width:${p}%"></i></div></div>`;
    };
    const gpuOk = s.device === "cuda";
    const chips = `<div class="schips"><span class="sc ${gpuOk ? "ok" : "bad"}">${gpuOk ? "✓" : "!"} ${esc(t(gpuOk ? "sys2.gpuOn" : "sys2.gpuOff"))}</span>`
      + (s.cpu_threads ? `<span class="sc">${esc(t("sys.cpu"))}: ${esc(s.cpu_threads)}</span>` : "")
      + (s.disk_free_gb !== undefined ? `<span class="sc ${s.disk_free_gb < 30 ? "bad" : ""}">${esc(t("sys.disk"))}: ${esc(s.disk_free_gb)} ${esc(t("sys.gb"))}</span>` : "") + `</div>`;
    const dev = `<div class="sdev"><div><small>${esc(t("sys.gpu"))}</small><b>${esc(s.gpu || "—")}</b></div><div><small>${esc(t("sys.cpuName"))}</small><b>${esc(s.cpu || "—")}</b></div></div>`;
    const meters = bar(t("sys.ram"), s.ram_gb - (s.ram_free_gb || 0), s.ram_gb, t("sys.gb")) + bar(t("sys.vram"), s.vram_gb - (s.vram_free_gb || 0), s.vram_gb, t("sys.gb"));
    $("#sys").innerHTML = warn + chips + dev + meters + `<details class="sdet"><summary>${esc(t("sys2.more"))}</summary><div class="kv">${rows.map(([k, v]) => `<b>${esc(t(k))}</b><span>${esc(v)}</span>`).join("")}</div></details>` + diag;
  } catch (e) { fail(e); }
  const ms = usable(await api("/api/models").catch(() => []));
  $("#modelsList").innerHTML = ms.length ? `<table>${byClinical(ms).map(m => `<tr><td>${esc(mlabel(m))}</td><td>${esc(m.model)}</td><td>${m.certified ? esc(t("hero.cert")) : t("c.bestDice") + ": " + fmt(m.best_val_dice)}</td></tr>`).join("")}</table>` : esc(t("c.none"));
  const cs = ["admin", "researcher"].includes(ME?.role) ? await api("/api/caches").catch(() => []) : [];
  $("#cachesList").innerHTML = cs.length ? `<table>${cs.map(c => `<tr><td>${esc(c.name)}</td><td>${Object.entries(c.splits).map(([k, v]) => esc(splitName(k)) + ": " + v).join(", ")}</td></tr>`).join("")}</table>` : esc(t("c.none"));
  const js = await api("/api/jobs").catch(() => []);
  $("#jobsList").innerHTML = jobsTable(js.slice(0, 12));
  loadQuick();
}
function jobsTable(js) {
  if (!js.length) return esc(t("c.none"));
  const what = j => j.params?.case || j.params?.name || (j.params?.files || [])[0] || "—";
  const when = j => j.created ? new Date(j.created * 1000).toLocaleString(LOCALE(), { dateStyle: "short", timeStyle: "short" }) : "";
  const who = j => j.patient ? `${j.patient.fio || "—"} · ID ${j.patient.id}` : "—";
  const anyPt = js.some(j => j.kind === "analyze");
  return `<table><tr><th>${esc(t("j.when"))}</th>${anyPt ? `<th>${esc(t("pr2.col"))}</th>` : ""}<th>${esc(t("j.what"))}</th><th>${esc(t("j.kind"))}</th><th>${esc(t("cs.state"))}</th><th></th></tr>${js.map(j => `<tr><td>${esc(when(j))}</td>${anyPt ? `<td>${j.patient ? `<a href="#" onclick="Registry.openCard('${esc(j.patient.id)}');return false">${esc(who(j))}</a>` : (j.kind === "analyze" && j.status === "done" && (ME?.role === "admin" || j.owner === ME?.username) ? `<a href="#" onclick="Registry.attachJob('${esc(j.id)}', () => { refreshAnJobs(); loadHome && loadHome(); });return false">${esc(t("pr2.attach"))}</a>` : "—")}</td>` : ""}<td><span class="trunc" title="${esc(j.id)}">${esc(what(j))}</span>${j.shared_with_me ? ` <span class="badge cst-new">${esc(t("j.shared"))}</span>` : ""}</td><td>${esc(t("job." + j.kind))}</td><td>${status(j.status)}${j.status === "error" && j.error ? `<small class="errwhy">${esc(I18N.uz["err." + j.error] ? t("err." + j.error) : t("err.internal"))}</small>` : ""}</td>
    <td>${j.kind === "analyze" && j.status === "done" ? `<a href="#" onclick="openCase('${esc(j.id)}');return false">${esc(t("v.open"))}</a>` : ""}</td></tr>`).join("")}</table>`;
}

// ---------------- tahlil
async function fillModels(...sels) {
  const ms = byClinical(usable(await api("/api/models").catch(() => [])));
  sels.forEach(sel => { $(sel).innerHTML = ms.map(m => `<option value="${esc(m.ckpt)}">${esc(mlabel(m))}</option>`).join(""); });
  return ms;
}
async function loadAnalyze() {
  await fillModels("#upModel", "#dsModel");
  // DATASET faqat administrator va tadqiqotchi uchun (radiologda bu karta yashirin — so'rov yuborilmaydi)
  let dsErr = "";
  const ds = ["admin", "researcher"].includes(ME?.role) ? await api("/api/dataset").catch(e => { dsErr = e.message; return []; }) : [];
  $("#dsCase").innerHTML = ds.length ? ds.map(c => `<option value="${esc(c.id)}">${esc(c.id)} — ${esc(splitName(c.split))}${c.gt ? " ★" : ""}</option>`).join("")
    : `<option value="">${esc(dsErr || t("err.dataset_missing"))}</option>`;
  $("#dsCase").disabled = $("#dsBtn").disabled = !ds.length;
  refreshAnJobs();
}
async function refreshAnJobs() {
  const js = await api("/api/jobs?kind=analyze").catch(() => []);
  $("#anJobs").innerHTML = jobsTable(js);
  if (js.some(j => j.status === "running" || j.status === "queued")) setTimeout(refreshAnJobs, 3000);
}
// fayl tashlash maydoni: sichqoncha bilan tashlash, bosish yoki Enter/Probel tugmasi
const fsize = b => b > 2 ** 30 ? (b / 2 ** 30).toFixed(2) + " GB" : b > 2 ** 20 ? (b / 2 ** 20).toFixed(1) + " MB" : Math.max(1, Math.round(b / 1024)) + " KB";
Registry.init();       // «Bemor» oynasi: fayl tanlashdan oldin bemor ro'yxatga olinadi yoki tanlanadi (registry.js)
$("#dsBtn").onclick = async () => {
  if (!$("#dsModel").value) return toast(t("an.noModel"));
  try { await post("/api/analyze_dataset", { case_id: $("#dsCase").value, ckpt: $("#dsModel").value }); toast(t("an.started")); refreshAnJobs(); } catch (e) { fail(e); }
};

// ---------------- ko'ruvchi
const V = { jid: null, meta: null, idx: { axial: 0, coronal: 0, sagittal: 0 } };
async function openCase(jid) {
  try { V.meta = await api(`/api/case/${jid}/meta`); } catch (e) { return toast(t("c.notReady")); }
  V.jid = jid; const sh = V.meta.shape;
  V.idx = { axial: Math.floor(sh[0] / 2), coronal: Math.floor(sh[1] / 2), sagittal: Math.floor(sh[2] / 2) };
  if (V.meta.lesions.length) V.idx.axial = Math.round(V.meta.lesions[0].centroid_zyx_vox[0]);
  showTab("viewer"); renderCase();
}
function axisLen() { const sh = V.meta.shape; return sh[{ axial: 0, coronal: 1, sagittal: 2 }[$("#vAxis").value]]; }
function renderCase() {
  if (!V.meta) return;
  const m = V.meta, pt = m.patient || {};
  $("#vTitle").textContent = m.patient_reg ? `${m.patient_reg.fio} · ID ${m.patient_reg.id} · ${V.jid}` : (m.case ? `${m.case} · ${V.jid}` : V.jid);
  $("#vStatus").innerHTML = `<span class="badge st-${esc(m.status)}">${esc(t("status." + (m.status || "pending_review")))}</span>`;
  const gt = m.vs_ground_truth ? `<p><b>${esc(t("v.vsgt"))}:</b> Dice ${fmt(m.vs_ground_truth.dice)}, HD95 ${fmt(m.vs_ground_truth.hd95_mm, 1)}</p>` : "";
  const inp = m.input || {};
  $("#vInfo").innerHTML = `<div class="kv"><b>${esc(t("ai.input"))}</b><span>${esc(t("src." + (inp.source || "volume")))}${inp.n_slices ? " · " + inp.n_slices : ""}</span>
    <b>${esc(t("v.model"))}</b><span>${esc(m.model)}</span><b>${esc(t("v.time"))}</b><span>${esc(m.seconds)} ${esc(t("v.sec"))}</span>
    <b>${esc(t("c.lesionsFound"))}</b><span>${m.n_lesions}</span></div>${gt}`;
  const prob = pt.model_prob_pct != null ? `${fmt(pt.model_prob_pct, 1)} %` : (pt.rads_risk_pct ? rng(pt.rads_risk_pct) + " %" : "—");
  const src = pt.model_prob_pct != null ? t("ai.srcModel") : t("ai.srcRads");
  const warn = (inp.warnings || []).map(w => esc(t("warn." + w))).join("; ");
  $("#vAI").innerHTML = pt.ai_conclusion ? `<h4>${esc(t("ai.title"))}</h4>
    <div class="aibig aic-${esc(pt.ai_conclusion)}">${esc(t("aic." + pt.ai_conclusion))}</div>
    <div class="kv"><b>${esc(t("ai.prob"))}</b><span>${esc(prob)}</span><b>${esc(t("ai.rads"))}</b><span>${esc(pt.lung_rads || "—")}</span></div>
    <p class="hint">${esc(src)}. ${esc(t("ai.notDx"))}</p>
    ${pt.reliability === "low" ? `<p class="warn">${esc(t("rel.low"))}${warn ? " (" + warn + ")" : ""}</p>` : ""}${aiCaveats(pt, m)}` : "";
  const rv = {}; (m.review?.lesions || []).forEach(l => rv[l.id] = l);
  const opts = ["none", "tumor", "node", "uncertain", "reject"];
  $("#vLes tbody").innerHTML = m.lesions.map(l => {
    const risk = l.model_prob_pct != null ? fmt(l.model_prob_pct, 1) : rng(l.rads_risk_pct);
    return `<tr data-z="${Math.round(l.centroid_zyx_vox[0])}" data-y="${Math.round(l.centroid_zyx_vox[1])}" data-x="${Math.round(l.centroid_zyx_vox[2])}" title="${esc(t("nt." + (l.nodule_type || "unknown")))}">
    <td>${l.id}</td><td>${fmt(l.volume_ml, 2)}</td><td>${fmt(l.eq_diameter_mm, 1)}</td><td>${esc(l.lung_rads || "—")}</td><td>${esc(risk)}</td>
    <td><select data-id="${l.id}">${opts.map(o => `<option value="${o}" ${(rv[l.id]?.decision || "none") === o ? "selected" : ""}>${esc(t("dec." + o))}</option>`).join("")}</select></td></tr>`; }).join("");
  $("#vLes tbody").querySelectorAll("tr").forEach(tr => tr.onclick = ev => {
    if (ev.target.tagName === "SELECT") return;
    V.idx = { axial: +tr.dataset.z, coronal: +tr.dataset.y, sagittal: +tr.dataset.x }; drawSlice();
  });
  $("#rvName").value = m.review?.radiologist || ME?.full_name || ""; $("#rvConc").value = m.review?.conclusion || "";
  $("#fnDx").value = m.review?.final_diagnosis || ""; $("#fnRads").value = m.review?.final_lung_rads || ""; $("#fnRec").value = m.review?.recommendation || "";
  $("#vGt").disabled = !m.has_gt;
  // konsultatsiya orqali kelgan holat: «Ikkinchi fikr» va qabul qilinmagan «Topshirish» — faqat ko'rish
  const acc = m.access || { mode: "owner" }, viewOnly = ["consult", "handover_pending"].includes(acc.mode);
  $("#vAccess").classList.toggle("hidden", acc.mode === "owner");
  $("#vAccess").textContent = acc.mode === "owner" ? "" : t("acc." + acc.mode).replace("{from}", acc.from || "—").replace("{until}", dtf(acc.expires));
  // yakunlangan hisobotni faqat administrator o'zgartira oladi
  const locked = (m.status === "final" && ME?.role !== "admin") || viewOnly;
  document.querySelectorAll(".final select, .final textarea, #vLes select").forEach(el => el.disabled = locked);
  $("#rvDraft").style.display = $("#rvSave").style.display = locked ? "none" : "";
  $("#fnLock").textContent = m.status === "final" && ME?.role !== "admin" ? t("err.already_final") : "";
  $("#vLinks").innerHTML = `<a href="/api/case/${V.jid}/report?lang=${LANG}" target="_blank">${esc(t("v.report"))}</a>
    <button type="button" id="vPdf" class="pdf">${esc(t("v.savePdf"))}</button>
    ${viewOnly ? "" : `<a href="/api/case/${V.jid}/download/mask.nii.gz">${esc(t("v.downloadMask"))}</a>`}<a href="/api/case/${V.jid}/download/report.json">${esc(t("v.downloadJson"))}</a>`;
  $("#vPdf").onclick = async e => {      // bemor F.I.Sh. va tug'ilgan sanasi so'raladi (saqlanmaydi), keyin PDF
    const btn = e.currentTarget, jid = V.jid, p = await PatientDialog.open("pdf", V.meta.patient_reg); if (!p) return;
    try { await PatientDialog.downloadPdf(jid, LANG, p, btn); } catch (err) { fail(err); }
  };
  // bemor biriktirilmagan avvalgi tahlil: egasi yoki administrator bemorga biriktiradi
  $("#vAttach").classList.toggle("hidden", !!m.patient_reg || acc.mode !== "owner");
  $("#vShare").classList.toggle("hidden", !acc.can_share);
  $("#vShared").innerHTML = (acc.sent || []).length ? `<b>${esc(t("sh.sentList"))}:</b> ` + acc.sent.map(s =>
    `${esc(s.to)} (${esc(t("ck." + s.kind))}) ${cstate(s.state)}`).join(" · ") : "";
  drawSlice();
}
function drawSlice() {
  if (!V.jid) return;
  const ax = $("#vAxis").value, n = axisLen();
  V.idx[ax] = Math.max(0, Math.min(n - 1, V.idx[ax]));
  $("#vSlider").max = n - 1; $("#vSlider").value = V.idx[ax];
  $("#vIdx").textContent = `${t("v.slice")} ${V.idx[ax] + 1} / ${n}`;
  $("#vImg").src = `/api/case/${V.jid}/slice?axis=${ax}&i=${V.idx[ax]}&win=${$("#vWin").value}&overlay=${$("#vOv").checked ? 1 : 0}&gt=${$("#vGt").checked ? 1 : 0}`;
}
["#vAxis", "#vWin", "#vOv", "#vGt"].forEach(s => $(s).onchange = drawSlice);
$("#vSlider").oninput = e => { V.idx[$("#vAxis").value] = +e.target.value; drawSlice(); };
$("#vImg").onwheel = e => { e.preventDefault(); V.idx[$("#vAxis").value] += e.deltaY > 0 ? 1 : -1; drawSlice(); };
document.addEventListener("keydown", e => {
  if (!$("#viewer").classList.contains("active") || ["INPUT", "TEXTAREA", "SELECT"].includes(e.target.tagName)) return;
  if (e.key === "ArrowUp") { V.idx[$("#vAxis").value]--; drawSlice(); } if (e.key === "ArrowDown") { V.idx[$("#vAxis").value]++; drawSlice(); }
});
async function saveReview(final) {
  const lesions = [...document.querySelectorAll("#vLes select")].map(s => ({ id: +s.dataset.id, decision: s.value === "none" ? null : s.value }));
  const body = { lesions, radiologist: ME?.full_name || "", conclusion: $("#rvConc").value, recommendation: $("#fnRec").value,
    final_lung_rads: $("#fnRads").value || null, final_diagnosis: final ? $("#fnDx").value : null };
  if (final && !body.radiologist) return toast(t("fin.needRad"));
  if (final && !body.final_diagnosis) return toast(t("fin.needDx"));
  try {
    await post(`/api/case/${V.jid}/review`, body);
    toast(final ? t("fin.done") : t("v.saved"));
    V.meta = await api(`/api/case/${V.jid}/meta`); renderCase();
    if (final) window.open(`/api/case/${V.jid}/report?lang=${LANG}`, "_blank");
  } catch (e) { fail(e); }
}
$("#rvSave").onclick = () => saveReview(true);
$("#rvDraft").onclick = () => saveReview(false);
$("#heroAnalyze")?.addEventListener("click", () => document.querySelector('nav button[data-tab="analyze"]')?.click());
$("#heroViewer")?.addEventListener("click", () => document.querySelector('nav button[data-tab="viewer"]')?.click());
$("#rvDelete").onclick = () => deleteCase();
function deleteCase() {
  if (!V.jid) return;
  const d = document.createElement("div"); d.className = "modal";
  d.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,.5);display:flex;align-items:center;justify-content:center;z-index:9999";
  d.innerHTML = `<form class="lbox" style="background:var(--bg,#fff);padding:18px;border-radius:8px;max-width:360px">
    <p><b>${t("del.title")}</b></p><p>${t("del.warn")}</p>
    <input name="u" autocomplete="username" placeholder="${t("del.user")}" style="width:100%;margin:4px 0">
    <input name="p" type="password" autocomplete="current-password" placeholder="${t("del.pass")}" style="width:100%;margin:4px 0">
    <div class="actions"><button type="button" data-x="0">${t("del.cancel")}</button><button type="submit" class="danger">${t("del.btn")}</button></div></form>`;
  document.body.appendChild(d);
  const f = d.querySelector("form"); f.u.focus();
  d.querySelector('[data-x="0"]').onclick = () => d.remove();
  f.onsubmit = async ev => {
    ev.preventDefault();
    try {
      await post(`/api/case/${V.jid}/delete`, { username: f.u.value, password: f.p.value });
      f.p.value = ""; d.remove(); toast(t("del.done")); V.jid = null; location.hash = ""; location.reload();
    } catch (e) { f.p.value = ""; toast(t("del.fail")); }
  };
}

// ---------------- o'qitish
async function loadTrain() {
  const cs = ["admin", "researcher"].includes(ME?.role) ? await api("/api/caches").catch(() => []) : [];
  $("#trCache").innerHTML = cs.map(c => `<option value="${esc(c.path)}">${esc(c.name)}</option>`).join("");
  const ms = await api("/api/models").catch(() => []);
  $("#trInit").innerHTML = `<option value="">${esc(t("tr.scratch"))}</option>` + byClinical(ms).map(m => `<option value="${esc(m.ckpt)}">${esc(mlabel(m))}</option>`).join("");
  const best = ms.find(m => m.pretrain && m.name === "M5_res2unet3d_msd");     // eng yaxshi konfiguratsiya: 3D-Res2UNet, MSD dan fine-tune
  if (best && !$("#trInit").dataset.touched) $("#trInit").value = best.ckpt;
  const st =await api("/api/settings").catch(() => ({}));
  if (!$("#prRoot").value) $("#prRoot").value = st.dataset_root || "";
  const js = await api("/api/jobs?kind=train").catch(() => []);
  const cur = $("#trJobSel").value;
  $("#trJobSel").innerHTML = js.map(j => `<option value="${esc(j.id)}">${esc(j.params.name)} — ${esc(t("st." + j.status))}</option>`).join("");
  if (cur) $("#trJobSel").value = cur;
  pollTrain();
}
$("#prBtn").onclick = async () => {
  try { await post("/api/prepare", { source: $("#prSrc").value, root: $("#prRoot").value, task: $("#prTask").value, name: $("#prName").value }); toast(t("c.started")); } catch (e) { fail(e); }
};
$("#trBtn").onclick = async () => {
  const body = { name: $("#trName").value, cache: $("#trCache").value, model: $("#trModel").value, loss: $("#trLoss").value,
    epochs: +$("#trEp").value, init: $("#trInit").value || null, fold: $("#trFold").value === "" ? null : +$("#trFold").value };
  try { const r = await post("/api/train", body); toast(t("c.started")); await loadTrain(); $("#trJobSel").value = r.job; pollTrain(); } catch (e) { fail(e); }
};
$("#trJobSel").onchange = pollTrain;
$("#trInit").onchange = () => { $("#trInit").dataset.touched = "1"; };
$("#trStop").onclick = async () => { const j = $("#trJobSel").value; if (j) { try { await post(`/api/jobs/${j}/stop`, {}); loadTrain(); } catch (e) { fail(e); } } };
let trTimer = null;
async function pollTrain() {
  clearTimeout(trTimer); const jid = $("#trJobSel").value; if (!jid) return;
  const [job, curve] = await Promise.all([api(`/api/jobs/${jid}`), api(`/api/train/${jid}/curve`)]).catch(() => [null, []]);
  if (!job) return;
  $("#trLog").textContent = job.log || ""; $("#trLog").scrollTop = 1e9;
  drawChart(curve);
  if (job.status === "running" || job.status === "queued") trTimer = setTimeout(pollTrain, 5000);
}
function drawChart(rows) {
  const svg = $("#trChart"), W = 700, H = 240, P = 36;
  if (!rows.length) { svg.innerHTML = ""; return; }
  const ep = rows.map(r => +r.epoch), loss = rows.map(r => +r.loss), dice = rows.map(r => r.val_dice === "nan" || r.val_dice === "" ? null : +r.val_dice);
  const xmax = Math.max(...ep, 1), lmax = Math.max(...loss, 1e-6);
  const X = e => P + (W - 2 * P) * (e - 1) / Math.max(1, xmax - 1), Yl = v => H - P - (H - 2 * P) * v / lmax, Yd = v => H - P - (H - 2 * P) * v;
  const path = (arr, Y) => arr.map((v, i) => v === null ? null : `${X(ep[i]).toFixed(1)},${Y(v).toFixed(1)}`).filter(Boolean).join(" ");
  svg.innerHTML = `<line x1="${P}" y1="${H - P}" x2="${W - P}" y2="${H - P}" stroke="currentColor" opacity=".3"/>
    <polyline fill="none" stroke="#e8710a" stroke-width="2" points="${path(loss, Yl)}"/>
    <polyline fill="none" stroke="#1f6feb" stroke-width="2" points="${path(dice, Yd)}"/>
    <text x="${P}" y="16" font-size="12" fill="#e8710a">${esc(t("tr.loss_curve"))}</text>
    <text x="${P + 110}" y="16" font-size="12" fill="#1f6feb">${esc(t("tr.dice_curve"))}: ${fmt(Math.max(...dice.filter(v => v !== null), 0))}</text>
    <text x="${W - P}" y="${H - 10}" font-size="11" text-anchor="end" fill="currentColor">${xmax} ${esc(t("tr.epoch"))}</text>`;
}

// ---------------- baholash
async function loadEval() {
  const cs = ["admin", "researcher"].includes(ME?.role) ? await api("/api/caches").catch(() => []) : [];
  $("#evCache").innerHTML = cs.map(c => `<option value="${esc(c.path)}">${esc(c.name)}</option>`).join("");
  const ms = usable(await api("/api/models").catch(() => []));
  $("#evModels").innerHTML = byClinical(ms.filter(m => !m.certified)).map(m => `<label><input type="checkbox" value="${esc(m.ckpt)}"> ${esc(mlabel(m))}</label>`).join("") || esc(t("c.none"));
  const rs = await api("/api/results").catch(() => []);
  $("#evRes").innerHTML = rs.length ? rs.map(r => `<h4>${esc(r.name)} — ${esc(splitName(r.split))}</h4><table><tr><th>${esc(t("ev.model"))}</th><th>${esc(t("ev.n"))}</th><th>${esc(t("ev.dice"))}</th><th>${esc(t("ev.hd"))}</th><th>${esc(t("ev.sens"))}</th><th>${esc(t("ev.fp"))}</th></tr>
    ${Object.entries(r.models).map(([n, s]) => `<tr><td>${esc(n)}</td><td>${s.n_cases}</td><td>${s.dice ? fmt(s.dice[0]) + (s.dice[1] === s.dice[1] && s.dice[1] !== null ? ` [${fmt(s.dice[1])}–${fmt(s.dice[2])}]` : "") : "—"}</td>
    <td>${s.hd95_mm ? fmt(s.hd95_mm[0], 1) : "—"}</td><td>${fmt(s.lesion_sensitivity, 2)}</td><td>${fmt(s.fp_per_scan, 2)}</td></tr>`).join("")}</table>
    ${Object.keys(r.pairwise || {}).length ? `<p class="hint">${esc(t("ev.pair"))}: ${Object.entries(r.pairwise).map(([k, v]) => esc(k) + (v.p_wilcoxon !== undefined ? " p=" + fmt(v.p_wilcoxon, 4) : " (n=" + v.n + ")")).join("; ")}</p>` : ""}`).join("") : esc(t("c.none"));
}
$("#evBtn").onclick = async () => {
  const ckpts = [...document.querySelectorAll("#evModels input:checked")].map(i => i.value);
  if (!ckpts.length) return toast(t("ev.noModel"));
  const split = $("#evSplit").value;
  if (split === "test" && !confirm(t("ev.testWarn"))) return;
  try { await post("/api/evaluate", { ckpts, cache: $("#evCache").value, split, confirm_test: split === "test" }); toast(t("c.started")); } catch (e) { fail(e); }
};

// ---------------- statistika va monitoring (grafiklar — kutubxonasiz inline SVG)
const LOCALE = () => LANG === "en" ? "en-GB" : LANG === "ru" ? "ru-RU" : "uz-UZ";
const PAL = ["var(--acc)", "var(--ok)", "var(--red)", "var(--amber)", "#7c4dff", "#00897b"];
const isoLocal = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const dtf = ts => ts ? new Date(ts * 1000).toLocaleString(LOCALE(), { dateStyle: "short", timeStyle: "short" }) : "—";
const S = { gran: "month", from: "", to: "", data: null };
try { const s0 = JSON.parse(localStorage.getItem("uzlungct.stats") || "{}"); ["gran", "from", "to"].forEach(k => { if (typeof s0[k] === "string") S[k] = s0[k]; }); } catch (e) {}
function saveS() { try { localStorage.setItem("uzlungct.stats", JSON.stringify({ gran: S.gran, from: S.from, to: S.to })); } catch (e) {} }
const UZ_MON = ["yan", "fev", "mar", "apr", "may", "iyun", "iyul", "avg", "sen", "okt", "noy", "dek"];   // brauzerlarda uz-UZ oy nomlari to'liq emas
function fmtLabel(l) {
  const p = l.split("-").map(Number);
  if (LANG === "uz" && p.length === 3) return `${String(p[2]).padStart(2, "0")} ${UZ_MON[p[1] - 1]}`;
  if (LANG === "uz" && p.length === 2) return `${UZ_MON[p[1] - 1]} ${p[0]}`;
  try {
    if (p.length === 3) return new Date(p[0], p[1] - 1, p[2]).toLocaleDateString(LOCALE(), { day: "2-digit", month: "short" });
    if (p.length === 2) return new Date(p[0], p[1] - 1, 1).toLocaleDateString(LOCALE(), { month: "short", year: "numeric" });
  } catch (e) {}
  return l;
}
const kpi = (label, val) => `<div class="kpi"><b>${esc(val ?? "—")}</b><span>${esc(label)}</span></div>`;
const legend = items => `<div class="legend">${items.map(([n, c]) => `<span><i style="background:${c}"></i>${esc(n)}</span>`).join("")}</div>`;
const noData = () => `<p class="empty">${esc(t("s.noData"))}</p>`;
function niceMax(v) { const m = Math.max(1, ...v); const st = Math.max(1, Math.ceil(m / 4)); return st * 4; }

function lineChart(labels, series) {
  const all = series.flatMap(s => s.values);
  if (!all.some(v => v > 0)) return noData();
  const W = 760, H = 260, L = 40, R = 14, T = 14, B = 34, n = labels.length, ymax = niceMax(all);
  const X = i => n === 1 ? (L + W - R) / 2 : L + (W - L - R) * i / (n - 1), Y = v => H - B - (H - T - B) * v / ymax;
  const step = Math.ceil(n / 10);
  let g = "";
  for (let k = 0; k <= 4; k++) { const v = ymax * k / 4; g += `<line class="ax" x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}"/><text x="${L - 6}" y="${Y(v) + 4}" text-anchor="end">${v}</text>`; }
  labels.forEach((l, i) => { if (i % step === 0 || i === n - 1) g += `<text x="${X(i)}" y="${H - 12}" text-anchor="middle">${esc(fmtLabel(l))}</text>`; });
  series.forEach(s => {
    g += `<polyline fill="none" stroke="${s.color}" stroke-width="2.2" points="${s.values.map((v, i) => `${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(" ")}"/>`;
    s.values.forEach((v, i) => { g += `<circle cx="${X(i).toFixed(1)}" cy="${Y(v).toFixed(1)}" r="${n > 60 ? 2 : 3.5}" fill="${s.color}"><title>${esc(fmtLabel(labels[i]))} — ${esc(s.name)}: ${v}</title></circle>`; });
  });
  return legend(series.map(s => [s.name, s.color])) + `<svg viewBox="0 0 ${W} ${H}" role="img">${g}</svg>`;
}
function stackedBars(labels, series) {
  const tot = labels.map((_, i) => series.reduce((a, s) => a + s.values[i], 0));
  if (!tot.some(v => v > 0)) return "";
  const W = 760, H = 200, L = 40, R = 14, T = 12, B = 30, n = labels.length, ymax = niceMax(tot);
  const bw = Math.max(2, (W - L - R) / n * 0.7), X = i => L + (W - L - R) * (i + 0.5) / n, Y = v => (H - T - B) * v / ymax;
  const step = Math.ceil(n / 10);
  let g = `<line class="ax" x1="${L}" x2="${W - R}" y1="${H - B}" y2="${H - B}"/><text x="${L - 6}" y="${T + 8}" text-anchor="end">${ymax}</text>`;
  labels.forEach((l, i) => {
    let y0 = H - B;
    series.forEach(s => { const h = Y(s.values[i]); if (h > 0) { y0 -= h; g += `<rect x="${(X(i) - bw / 2).toFixed(1)}" y="${y0.toFixed(1)}" width="${bw.toFixed(1)}" height="${h.toFixed(1)}" fill="${s.color}"><title>${esc(fmtLabel(l))} — ${esc(s.name)}: ${s.values[i]}</title></rect>`; } });
    if (i % step === 0 || i === n - 1) g += `<text x="${X(i)}" y="${H - 10}" text-anchor="middle">${esc(fmtLabel(l))}</text>`;
  });
  return `<svg viewBox="0 0 ${W} ${H}" role="img">${g}</svg>`;
}
function donut(items) {
  const tot = items.reduce((a, x) => a + x.value, 0);
  if (!tot) return noData();
  const R = 80, r = 50, C = 100; let a0 = -Math.PI / 2, g = "";
  items.filter(x => x.value > 0).forEach(x => {
    const a1 = a0 + 2 * Math.PI * x.value / tot, big = a1 - a0 > Math.PI ? 1 : 0;
    const p = (rad, a) => `${(C + rad * Math.cos(a)).toFixed(2)},${(C + rad * Math.sin(a)).toFixed(2)}`;
    const d = x.value === tot ? `M${C},${C - R}A${R},${R} 0 1 1 ${C - 0.01},${C - R}L${C - 0.01},${C - r}A${r},${r} 0 1 0 ${C},${C - r}Z`
      : `M${p(R, a0)}A${R},${R} 0 ${big} 1 ${p(R, a1)}L${p(r, a1)}A${r},${r} 0 ${big} 0 ${p(r, a0)}Z`;
    g += `<path d="${d}" fill="${x.color}"><title>${esc(x.label)}: ${x.value} (${(100 * x.value / tot).toFixed(1)} %)</title></path>`; a0 = a1;
  });
  g += `<text x="${C}" y="${C + 7}" text-anchor="middle" style="font-size:22px;font-weight:700;fill:var(--ink)">${tot}</text>`;
  return `<div class="row" style="align-items:center;flex-wrap:wrap"><svg viewBox="0 0 200 200" style="max-width:200px" role="img">${g}</svg>
    <div class="legend" style="flex-direction:column">${items.map(x => `<span><i style="background:${x.color}"></i>${esc(x.label)}: <b>${x.value}</b> (${(100 * x.value / tot).toFixed(1)} %)</span>`).join("")}</div></div>`;
}
function hbars(items) {
  // HTML ustunlar: telefonda ham yozuvlar o'qiladigan o'lchamda qoladi
  const m = Math.max(0, ...items.map(x => x.value));
  if (!m) return noData();
  return `<div class="hbars">${items.map(x => `<div class="hb" title="${esc(x.label)}: ${x.value}"><span>${esc(x.label)}</span>
    <div class="hbt"><i style="width:${(100 * x.value / m).toFixed(1)}%;background:${x.color || PAL[0]}"></i></div><b>${x.value}</b></div>`).join("")}</div>`;
}
function pairBars(cats, a, b, na, nb) {
  const all = [...cats.map(c => a[c] || 0), ...cats.map(c => b[c] || 0)];
  if (!all.some(v => v > 0)) return noData();
  const W = 760, H = 230, L = 40, R = 14, T = 12, B = 30, n = cats.length, ymax = niceMax(all), gw = (W - L - R) / n, bw = gw * 0.32;
  const Y = v => (H - T - B) * v / ymax;
  let g = `<line class="ax" x1="${L}" x2="${W - R}" y1="${H - B}" y2="${H - B}"/><text x="${L - 6}" y="${T + 8}" text-anchor="end">${ymax}</text>`;
  cats.forEach((c, i) => {
    const x0 = L + gw * i + gw / 2;
    [[a[c] || 0, PAL[0], na], [b[c] || 0, PAL[1], nb]].forEach(([v, col, nm], k) => {
      const h = Y(v), x = x0 - bw + k * bw;
      g += `<rect x="${x.toFixed(1)}" y="${(H - B - h).toFixed(1)}" width="${(bw - 3).toFixed(1)}" height="${h.toFixed(1)}" rx="3" fill="${col}"><title>${esc(c)} — ${esc(nm)}: ${v}</title></rect>`;
      if (v) g += `<text x="${(x + bw / 2 - 1.5).toFixed(1)}" y="${(H - B - h - 4).toFixed(1)}" text-anchor="middle">${v}</text>`;
    });
    g += `<text x="${x0}" y="${H - 10}" text-anchor="middle" style="font-size:13px;fill:var(--ink)">${esc(c)}</text>`;
  });
  return legend([[na, PAL[0]], [nb, PAL[1]]]) + `<svg viewBox="0 0 ${W} ${H}" role="img">${g}</svg>`;
}

async function loadStats() {
  $("#sFrom").value = S.from; $("#sTo").value = S.to;
  document.querySelectorAll("#sGran button").forEach(b => b.classList.toggle("active", b.dataset.g === S.gran));
  $("#sScope").classList.toggle("hidden", ME?.role !== "radiologist");
  const q = new URLSearchParams({ granularity: S.gran }); if (S.from) q.set("from", S.from); if (S.to) q.set("to", S.to);
  try { S.data = await api("/api/stats?" + q.toString()); renderStats(); } catch (e) { fail(e); }
}
function renderStats() {
  const a = S.data; if (!a) return;
  const sm = a.summary, staff = ["admin", "researcher"].includes(ME?.role);
  $("#sKpi").innerHTML = [kpi(t("k.analyses"), sm.analyses), kpi(t("k.finalized"), sm.finalized), kpi(t("k.pending"), sm.pending),
    kpi(t("k.avgSec"), sm.avg_analysis_sec != null ? sm.avg_analysis_sec + " " + t("v.sec") : "—"),
    kpi(t("k.avgDelay"), sm.avg_review_delay_h != null ? sm.avg_review_delay_h + " " + t("s.hours") : "—"),
    kpi(t("k.consultsSent"), sm.consults_sent), kpi(t("k.errors"), sm.errors), kpi(t("k.activeUsers"), sm.active_users),
    ...(staff ? [kpi(t("k.train"), sm.train), kpi(t("k.evaluate"), sm.evaluate)] : []),
    ...(a.skipped ? [kpi(t("s.skipped"), a.skipped)] : [])].join("");
  $("#chDyn").innerHTML = lineChart(a.labels, [["analyses", PAL[0]], ["finalized", PAL[1]], ["errors", PAL[2]], ["consults_sent", PAL[4]]]
    .map(([k, c]) => ({ name: t("ser." + k), color: c, values: a.series[k] })));
  const dxKeys = Object.keys(a.diagnoses.total);
  $("#chDx").innerHTML = donut(dxKeys.map((k, i) => ({ label: t("dx." + k), value: a.diagnoses.total[k], color: PAL[i % PAL.length] }))) +
    (a.labels.length > 1 ? stackedBars(a.labels, dxKeys.map((k, i) => ({ name: t("dx." + k), color: PAL[i % PAL.length], values: a.diagnoses.series[k] }))) : "");
  const aicCol = { faqat_qoshimcha: "var(--amber)", no_lesion: "var(--mute)", probably_benign: "var(--ok)", suspicious: "var(--amber)", high_suspicion: "var(--red)" };
  $("#chAic").innerHTML = hbars(Object.entries(a.ai_conclusions).map(([k, v]) => ({ label: t("aic." + k), value: v, color: aicCol[k] })));
  $("#chRads").innerHTML = pairBars(Object.keys(a.lung_rads.ai), a.lung_rads.ai, a.lung_rads.final, t("ch.radsAI"), t("ch.radsFinal"));
  const ag = a.agreement;
  $("#chAgree").textContent = ag.n ? `${t("ch.agree")}: ${ag.agree} / ${ag.n} (${(100 * ag.rate).toFixed(0)} %)${ag.descriptive ? " — " + t("ch.descriptive") : ""}` : "";
  $("#chSrc").innerHTML = hbars(Object.entries(a.sources).map(([k, v], i) => ({ label: t("src." + k), value: v, color: PAL[i % PAL.length] })));
  if (a.by_user) {
    const us = Object.entries(a.by_user).sort((x, y) => y[1].analyses - x[1].analyses);
    $("#chUsers").innerHTML = us.length ? `<table><tr><th>${esc(t("s.user"))}</th><th>${esc(t("k.analyses"))}</th><th>${esc(t("k.finalized"))}</th><th>${esc(t("k.consultsSent"))}</th></tr>` +
      us.map(([u, v]) => `<tr><td>${esc(u)}</td><td>${v.analyses}</td><td>${v.finalized}</td><td>${v.consults_sent}</td></tr>`).join("") + "</table>" : noData();
  }
}
document.querySelectorAll("#sGran button").forEach(b => b.onclick = () => { S.gran = b.dataset.g; saveS(); loadStats(); });
document.querySelectorAll(".presets button").forEach(b => b.onclick = () => {
  const now = new Date(), p = b.dataset.p;
  S.to = p === "all" ? "" : isoLocal(now);
  S.from = p === "all" ? "" : p === "year" ? `${now.getFullYear()}-01-01` : isoLocal(new Date(now.getFullYear(), now.getMonth(), now.getDate() - (+p - 1)));
  if (p === "all" && S.gran === "day") S.gran = "month";
  if (p === "year" && S.gran === "year") S.gran = "month";
  saveS(); loadStats();
});
$("#sFrom").onchange = () => { S.from = $("#sFrom").value; saveS(); };
$("#sTo").onchange = () => { S.to = $("#sTo").value; saveS(); };
$("#sRefresh").onclick = () => {
  if ($("#sFrom").value && $("#sTo").value && $("#sFrom").value > $("#sTo").value) return toast(t("s.badRange"));
  S.from = $("#sFrom").value; S.to = $("#sTo").value; saveS(); loadStats();
};
$("#sCsv").onclick = () => {
  const q = new URLSearchParams({ granularity: S.gran }); if (S.from) q.set("from", S.from); if (S.to) q.set("to", S.to);
  window.location.href = "/api/stats.csv?" + q.toString();
};
async function loadQuick() {
  const now = new Date(), f = isoLocal(new Date(now.getFullYear(), now.getMonth(), 1)), to = isoLocal(now);
  try {
    const a = await api(`/api/stats?granularity=day&from=${f}&to=${to}`), i = a.labels.length - 1;
    $("#quickBody").innerHTML = kpi(t("s.today") + " · " + t("k.analyses"), a.series.analyses[i]) + kpi(t("s.today") + " · " + t("k.finalized"), a.series.finalized[i]) +
      kpi(t("s.thisMonth") + " · " + t("k.analyses"), a.summary.analyses) + kpi(t("s.thisMonth") + " · " + t("k.finalized"), a.summary.finalized);
  } catch (e) { $("#quickBody").textContent = "—"; }
}
$("#homeQuick").onclick = () => showTab("stats");
$("#homeQuick").onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); showTab("stats"); } };

// ---------------- konsultatsiyalar: hisobotni hamkasbga yuborish va qabul qilish
const C = { box: "inbox", items: { inbox: [], sent: [] }, sel: null, users: [] };
const ARCH = ["revoked", "declined", "expired"];
const ptLabel = x => x.patient ? `${x.patient.fio || "—"} · ID ${x.patient.id}` : (x.case || x.job_id);   // konsultatsiyada bemor
const cstate = s => `<span class="badge cst-${esc(s)}">${esc(t("cst." + s))}</span>`;
const prioB = p => `<span class="badge b-${esc(p)}">${esc(t("pr." + p))}</span>`;
const aicB = a => a ? `<span class="aic-${esc(a)}">${esc(t("aic." + a))}</span>` : "—";
const sentState = x => x.state !== "active" ? x.state : (x.recipients.every(r => r.state === "declined") ? "declined" : "active");
const isArch = x => ARCH.includes(x.dir === "in" ? x.state : sentState(x));
let csLast = null;
function setBadge(n) { const b = $("#csBadge"); b.textContent = n > 99 ? "99+" : String(n); b.classList.toggle("hidden", !n); }
async function pollUnread() {
  if (!ME || !["admin", "radiologist"].includes(ME.role) || document.hidden) return;
  try {
    const r = await api("/api/consult/unread_count"); setBadge(r.n);
    if (csLast !== null && r.n > csLast) { toast(t("cs.newToast")); if ($("#consult").classList.contains("active")) loadConsult(); }
    csLast = r.n;
  } catch (e) {}
}
setInterval(pollUnread, 30000);
document.addEventListener("visibilitychange", () => { if (!document.hidden) pollUnread(); });

async function loadConsult() {
  try {
    const [inb, sent] = await Promise.all([api("/api/consult/inbox"), api("/api/consult/sent")]);
    C.items = { inbox: inb.map(x => ({ ...x, dir: "in" })), sent: sent.map(x => ({ ...x, dir: "out" })) };
  } catch (e) { return fail(e); }
  const nIn = C.items.inbox.filter(x => x.unread && !isArch(x)).length, nOut = C.items.sent.filter(x => x.unread).length;
  $("#cInN").textContent = nIn; $("#cInN").classList.toggle("hidden", !nIn);
  $("#cSentN").textContent = nOut; $("#cSentN").classList.toggle("hidden", !nOut);
  setBadge(nIn + nOut); csLast = nIn + nOut;
  const states = C.box === "archive" ? ARCH : C.box === "inbox" ? ["new", "opened", "replied", "accepted"] : ["new", "opened", "replied", "accepted", "declined"];
  const cur = $("#cfState").value;
  $("#cfState").innerHTML = `<option value="">${esc(t("cs.all"))}</option>` + states.map(s => `<option value="${s}">${esc(t("cst." + s))}</option>`).join("");
  if (states.includes(cur)) $("#cfState").value = cur;
  document.querySelectorAll("#cBox button").forEach(b => { b.classList.toggle("active", b.dataset.box === C.box); b.setAttribute("aria-selected", b.dataset.box === C.box); });
  renderConsultList();
  if (C.sel) openConsult(C.sel, true);
}
function consultRows() {
  let rows = C.box === "archive" ? [...C.items.inbox, ...C.items.sent].filter(isArch) : C.items[C.box].filter(x => !isArch(x));
  const st = $("#cfState").value, kd = $("#cfKind").value, pr = $("#cfPrio").value, q = $("#cfQ").value.trim().toLowerCase();
  if (st) rows = rows.filter(x => x.dir === "in" ? x.state === st : (x.state === st || x.recipients.some(r => r.state === st)));
  if (kd) rows = rows.filter(x => x.kind === kd);
  if (pr) rows = rows.filter(x => x.priority === pr);
  if (q) rows = rows.filter(x => [ptLabel(x), x.job_id, x.sender_name, ...x.recipients.map(r => r.full_name)].join(" ").toLowerCase().includes(q));
  return rows.sort((a, b) => (b.unread - a.unread) || ((b.priority === "urgent") - (a.priority === "urgent")) || b.created - a.created);
}
function renderConsultList() {
  const rows = consultRows();
  if (!rows.length) { $("#cList").innerHTML = `<p class="empty">${esc(t("cs.empty"))}</p>`; return; }
  $("#cList").innerHTML = `<table><tr><th>${esc(t("cs.prio"))}</th><th>${esc(t("cs.case"))}</th><th>${esc(t("cs.ai"))}</th><th>L-RADS</th>
    <th>${esc(t(C.box === "sent" ? "cs.to" : "cs.from"))}</th><th>${esc(t("cs.kind"))}</th><th>${esc(t("cs.state"))}</th><th>${esc(t("cs.date"))}</th></tr>` +
    rows.map(x => {
      const who = x.dir === "in" ? x.sender_name : x.recipients.map(r => r.full_name).join(", ");
      const st = x.dir === "in" ? x.state : sentState(x);
      return `<tr tabindex="0" data-id="${x.id}" class="${x.unread ? "unread" : ""} ${x.priority === "urgent" ? "urgent" : ""} ${C.sel === x.id ? "sel" : ""}">
        <td>${prioB(x.priority)}</td><td><span class="trunc" title="${esc(x.job_id)}">${esc(ptLabel(x))}</span></td><td>${aicB(x.ai_conclusion)}</td>
        <td>${esc(x.lung_rads || "—")}</td><td><span class="trunc" title="${esc(who)}">${x.dir === "out" && C.box === "archive" ? "→ " : ""}${esc(who)}</span></td>
        <td>${esc(t("ck." + x.kind))}</td><td>${cstate(st)}</td><td>${esc(dtf(x.created))}</td></tr>`;
    }).join("") + "</table>";
  $("#cList").querySelectorAll("tr[data-id]").forEach(tr => {
    tr.onclick = () => openConsult(+tr.dataset.id);
    tr.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openConsult(+tr.dataset.id); } };
  });
}
async function openConsult(id, quiet) {
  const item = [...C.items.inbox, ...C.items.sent].find(x => x.id === id);
  C.sel = id;
  document.querySelectorAll("#cList tr[data-id]").forEach(tr => tr.classList.toggle("sel", +tr.dataset.id === id));
  if (!item) { $("#cDetail").innerHTML = `<p class="hint">${esc(t("cs.pick"))}</p>`; return; }
  if (item.dir === "in" && ARCH.includes(item.state)) { renderConsultDetail({ ...item, messages: [] }, item); return; }
  try {
    const d = await api(`/api/consult/${id}`);
    renderConsultDetail(d, item);
    if (!quiet && item.unread) { item.unread = false; renderConsultList(); pollUnread(); }
  } catch (e) { if (!quiet) fail(e); }
}
function renderConsultDetail(d, item) {
  const mine = item.dir === "out", st = mine ? sentState(d) : d.state, open = !ARCH.includes(st);
  const recips = d.recipients.map(r => `${esc(r.full_name)} ${cstate(r.state)}`).join("<br>");
  const thread = (d.messages || []).map(m => `<div class="msg ${m.author === ME?.username ? "me" : ""}"><small>${esc(m.author_name)} · ${esc(dtf(m.created))}</small>${esc(m.text)}</div>`).join("");
  const canAnswer = !mine && d.kind === "handover" && ["new", "opened", "replied"].includes(d.state);
  $("#cDetail").innerHTML = `<h3>${esc(ptLabel(d))}</h3>
    <p>${prioB(d.priority)} <span class="badge">${esc(t("ck." + d.kind))}</span> ${cstate(st)}</p>
    <div class="kv"><b>${esc(t("cs.from"))}</b><span>${esc(d.sender_name)}</span><b>${esc(t("cs.to"))}</b><span>${recips}</span>
      <b>${esc(t("cs.created"))}</b><span>${esc(dtf(d.created))}</span><b>${esc(t("cs.until"))}</b><span>${esc(dtf(d.expires))}</span>
      <b>${esc(t("cs.ai"))}</b><span>${aicB(d.ai_conclusion)}</span><b>Lung-RADS</b><span>${esc(d.lung_rads || "—")}</span>
      <b>${esc(t("cs.reportStatus"))}</b><span>${d.report_status ? `<span class="badge st-${esc(d.report_status)}">${esc(t("status." + d.report_status))}</span>` : "—"}</span></div>
    ${d.message ? `<h4>${esc(t("cs.message"))}</h4><div class="msg">${esc(d.message)}</div>` : ""}
    <h4>${esc(t("cs.thread"))}</h4><div class="thread" id="cThread">${thread || `<p class="hint">${esc(t("cs.noMsg"))}</p>`}</div>
    ${open ? `<label><span>${esc(t("cs.reply"))}</span><textarea id="cReply" rows="3" maxlength="2000"></textarea></label><button id="cSend" class="primary">${esc(t("cs.send"))}</button>` : ""}
    <div class="links">${open ? `<button id="cOpen">${esc(t("cs.openCase"))}</button>` : ""}
      ${canAnswer ? `<button id="cAccept" class="primary">${esc(t("cs.accept"))}</button><button id="cDecline" class="danger">${esc(t("cs.decline"))}</button>` : ""}
      ${mine && st === "active" ? `<button id="cRevoke" class="danger">${esc(t("cs.revoke"))}</button>` : ""}</div>`;
  const th = $("#cThread"); if (th) th.scrollTop = 1e9;
  const act = async (url, body, msg) => { try { await post(url, body || {}); toast(msg || t("cs.done")); await loadConsult(); } catch (e) { fail(e); } };
  if ($("#cSend")) {
    $("#cSend").onclick = () => { const v = $("#cReply").value.trim(); if (v) act(`/api/consult/${d.id}/reply`, { text: v }, t("cs.replied")); };
    $("#cReply").onkeydown = e => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) $("#cSend").click(); };
  }
  if ($("#cOpen")) $("#cOpen").onclick = () => openCase(d.job_id);
  if ($("#cAccept")) $("#cAccept").onclick = () => act(`/api/consult/${d.id}/accept`);
  if ($("#cDecline")) $("#cDecline").onclick = () => { if (confirm(t("cs.declineConfirm"))) act(`/api/consult/${d.id}/decline`); };
  if ($("#cRevoke")) $("#cRevoke").onclick = () => { if (confirm(t("cs.revokeConfirm"))) act(`/api/consult/${d.id}/revoke`); };
}
document.querySelectorAll("#cBox button").forEach(b => b.onclick = () => { C.box = b.dataset.box; C.sel = null; $("#cDetail").innerHTML = `<p class="hint">${esc(t("cs.pick"))}</p>`; loadConsult(); });
["#cfState", "#cfKind", "#cfPrio"].forEach(s => $(s).onchange = renderConsultList);
$("#cfQ").oninput = renderConsultList;

// «Hamkasbga yuborish» oynasi (Ko'ruvchi)
const SH = { kind: "consult", sel: new Set(), back: null };
function renderShUsers() {
  const q = $("#shFind").value.trim().toLowerCase();
  const us = C.users.filter(u => !q || (u.full_name + " " + u.username).toLowerCase().includes(q));
  $("#shUsers").innerHTML = us.length ? us.map(u => `<label><input type="checkbox" value="${esc(u.username)}" ${SH.sel.has(u.username) ? "checked" : ""}>${esc(u.full_name)}<small>${esc(u.username)} · ${esc(t("role." + u.role))}</small></label>`).join("")
    : `<p class="hint">${esc(t(C.users.length ? "c.none" : "sh.noUsers"))}</p>`;
  $("#shUsers").querySelectorAll("input").forEach(i => i.onchange = () => {
    if (i.checked && SH.kind === "handover") { SH.sel.clear(); $("#shUsers").querySelectorAll("input").forEach(o => { if (o !== i) o.checked = false; }); }
    i.checked ? SH.sel.add(i.value) : SH.sel.delete(i.value);
  });
}
function renderShKind() {
  document.querySelectorAll("#shKind button").forEach(b => { b.classList.toggle("active", b.dataset.v === SH.kind); b.setAttribute("aria-pressed", b.dataset.v === SH.kind); });
  $("#shKindHint").textContent = t(SH.kind === "handover" ? "ck.handoverHint" : "ck.consultHint");
}
const shCount = () => { $("#shCount").textContent = `${$("#shMsg").value.length} / 1000 ${t("sh.chars")}`; };
async function openShare() {
  if (!V.jid) return;
  try { C.users = await api("/api/consult/recipients"); } catch (e) { return fail(e); }
  SH.kind = "consult"; SH.sel = new Set(); SH.back = document.activeElement;
  $("#shFind").value = ""; $("#shMsg").value = ""; $("#shPrio").value = "normal"; $("#shDays").value = "30"; $("#shErr").textContent = "";
  renderShUsers(); renderShKind(); shCount();
  $("#shareBox").classList.remove("hidden"); setTimeout(() => $("#shFind").focus(), 50);
}
function closeShare() { $("#shareBox").classList.add("hidden"); if (SH.back) SH.back.focus(); }
$("#vShare").onclick = openShare;
$("#vAttach").onclick = () => { const jid = V.jid; Registry.attachJob(jid, async () => { if (V.jid === jid) { V.meta = await api(`/api/case/${jid}/meta`); renderCase(); } refreshAnJobs(); }); };
$("#shCancel").onclick = closeShare;
$("#shFind").oninput = renderShUsers;
$("#shMsg").oninput = shCount;
document.querySelectorAll("#shKind button").forEach(b => b.onclick = () => {
  SH.kind = b.dataset.v;
  if (SH.kind === "handover" && SH.sel.size > 1) SH.sel = new Set([...SH.sel].slice(0, 1));
  renderShKind(); renderShUsers();
});
$("#shareBox").addEventListener("keydown", e => {
  if (e.key === "Escape") { e.preventDefault(); closeShare(); }
  if (e.key === "Tab") {                                   // fokus oyna ichida qoladi
    const f = [...$("#shareBox").querySelectorAll("input,select,textarea,button")].filter(el => !el.disabled && el.offsetParent);
    if (!f.length) return;
    if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
    else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
  }
});
$("#shForm").onsubmit = async e => {
  e.preventDefault(); $("#shErr").textContent = "";
  if (!SH.sel.size) { $("#shErr").textContent = t("sh.needTo"); return; }
  if (SH.kind === "handover" && SH.sel.size !== 1) { $("#shErr").textContent = t("sh.oneHandover"); return; }
  try {
    await post("/api/consult", { job_id: V.jid, recipients: [...SH.sel], kind: SH.kind, priority: $("#shPrio").value,
      expires_days: +$("#shDays").value, message: $("#shMsg").value });
    closeShare(); toast(t("sh.done"));
    V.meta = await api(`/api/case/${V.jid}/meta`); renderCase();
  } catch (e2) { $("#shErr").textContent = e2.message; }
};

// ---------------- sozlamalar
async function loadSettings() {
  const s = await api("/api/settings"); $("#stRoot").value = s.dataset_root || ""; $("#stInst").value = s.institution || "";
}
$("#stSave").onclick = async () => {
  try { await post("/api/settings", { dataset_root: $("#stRoot").value, institution: $("#stInst").value }); toast(t("st.saved")); } catch (e) { fail(e); }
};

// ---------------- kirish, foydalanuvchi va ruxsatlar
function showLogin() {
  ME = null; $("#login").classList.remove("hidden"); $("#pwBox").classList.add("hidden"); $("#rdBox").classList.add("hidden");
  document.body.classList.add("locked"); setTimeout(() => $("#lgUser").focus(), 50);
}
function setUser(u) {
  ME = u; $("#login").classList.add("hidden"); document.body.classList.remove("locked");
  $("#uName").textContent = u.full_name; $("#uRole").textContent = t("role." + u.role);
  $("#uAv").textContent = (u.full_name || u.username).split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0]).join("").toUpperCase();
  document.querySelectorAll("nav button[data-roles]").forEach(b => b.style.display = b.dataset.roles.split(" ").includes(u.role) ? "" : "none");
  document.querySelectorAll("[data-roles-el]").forEach(el => el.style.display = el.dataset.rolesEl.split(" ").includes(u.role) ? "" : "none");
  if (u.must_change) showPw(true); else showTab(document.querySelector(".tab.active")?.id || "home");
  csLast = null; pollUnread();
}
// parol maydonlari: ko‘rsatish/yashirish, Caps Lock, jonli talablar (v5)
document.querySelectorAll("[data-eye]").forEach(b => b.onclick = () => {
  const inp = $("#" + b.dataset.eye), show = inp.type === "password";
  inp.type = show ? "text" : "password"; b.setAttribute("aria-pressed", String(show));
  const k = show ? "au.hide" : "au.show"; b.dataset.i18nTitle = k; b.dataset.i18nAria = k; b.title = t(k); b.setAttribute("aria-label", t(k));
});
document.querySelectorAll("[data-caps]").forEach(w => {
  const inp = $("#" + w.dataset.caps), upd = ev => { const on = !!(ev.getModifierState && ev.getModifierState("CapsLock")); w.classList.toggle("hidden", !on); };
  inp.addEventListener("keydown", upd); inp.addEventListener("keyup", upd); inp.addEventListener("blur", () => w.classList.add("hidden"));
});
const PW_MIN = 10, PW_MAX = 128;
function pwChecks(pw, login) {
  const p = (pw || "").normalize("NFKC");
  return [
    [t("au.rule.len"), p.length >= PW_MIN && p.length <= PW_MAX],
    [t("au.rule.letter"), /\p{L}/u.test(p)],
    [t("au.rule.varied"), new Set(p).size > 2],
    [t("au.rule.login"), !login || login.length < 3 || !p.toLowerCase().includes(login.toLowerCase())],
  ];
}
function renderRules(list) {
  const inp = $("#" + list.dataset.rulesFor), login = list.dataset.rulesFor === "rdNew" ? ($("#rdUser").value || "").trim() : (ME?.username || "");
  list.innerHTML = pwChecks(inp.value, login).map(([txt, ok]) => `<li class="${ok ? "ok" : ""}">${esc(txt)}</li>`).join("");
}
document.querySelectorAll("[data-rules-for]").forEach(l => { $("#" + l.dataset.rulesFor).addEventListener("input", () => renderRules(l)); renderRules(l); });
window.onLangChange = ((prev) => () => { if (prev) prev(); document.querySelectorAll("[data-rules-for]").forEach(renderRules); })(window.onLangChange);

function loginErrText(j) {
  const d = j && j.detail, mins = Math.max(1, Math.ceil(((j && j.retry_after) || 0) / 60));
  if (d === "bad_credentials") return t("au.err.bad_credentials") + (j.remaining != null ? ". " + t("au.err.remaining").replace("{n}", j.remaining) : "");
  if (d === "locked") return t("au.err.locked").replace("{m}", mins);
  if (d === "too_many_attempts") return t("au.err.too_many_attempts").replace("{m}", mins);
  if (d === "disabled") return t("au.err.disabled");
  return t("au.err." + d) !== "au.err." + d ? t("au.err." + d) : (t("err." + d) !== "err." + d ? t("err." + d) : t("c.error"));
}
$("#loginForm").onsubmit = async e => {
  e.preventDefault(); $("#lgErr").textContent = "";
  let r, j = null;
  try {
    r = await fetch("/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json", "X-UzLungCT": "1" },
      body: JSON.stringify({ username: $("#lgUser").value, password: $("#lgPass").value }), credentials: "same-origin" });
  } catch (e2) { $("#lgErr").textContent = t("au.err.network"); return; }     // server o‘chiq/tarmoq xatosi — parol xatosi emas
  try { j = await r.json(); } catch (e3) { $("#lgErr").textContent = t("au.err.server") + " (" + r.status + ")"; return; }
  if (!r.ok) { $("#lgErr").textContent = loginErrText(j); $("#lgPass").focus(); $("#lgPass").select(); return; }   // xatoda parol maydoni saqlanadi
  $("#lgPass").value = ""; $("#lgPass").type = "password"; setUser(j);
};
$("#lgRedeem").onclick = () => { $("#rdUser").value = $("#lgUser").value.trim(); $("#rdErr").textContent = ""; $("#login").classList.add("hidden"); $("#rdBox").classList.remove("hidden"); setTimeout(() => { const a = document.activeElement; if (a && a.closest && a.closest("#rdBox") && a.tagName === "INPUT") return; ($("#rdUser").value ? $("#rdCode") : $("#rdUser")).focus(); }, 50); };
$("#rdBack").onclick = () => { $("#rdBox").classList.add("hidden"); $("#login").classList.remove("hidden"); $("#lgUser").value = $("#rdUser").value; setTimeout(() => $("#lgPass").focus(), 50); };
$("#rdForm").onsubmit = async e => {
  e.preventDefault(); $("#rdErr").textContent = "";
  if ($("#rdNew").value !== $("#rdNew2").value) { $("#rdErr").textContent = t("au.pwMismatch"); return; }
  try {
    await post("/api/auth/redeem", { username: $("#rdUser").value, code: $("#rdCode").value, new_password: $("#rdNew").value });
    ["#rdCode", "#rdNew", "#rdNew2"].forEach(s => $(s).value = ""); document.querySelectorAll("[data-rules-for]").forEach(renderRules);
    $("#rdBox").classList.add("hidden"); $("#login").classList.remove("hidden"); $("#lgUser").value = $("#rdUser").value; $("#lgPass").value = "";
    $("#lgErr").textContent = ""; toast(t("au.redeemDone")); setTimeout(() => $("#lgPass").focus(), 50);
  } catch (e2) { $("#rdErr").textContent = e2.message; }
};
function showPw(forced) {
  $("#pwBox").classList.remove("hidden"); $("#pwForced").style.display = forced ? "" : "none"; $("#pwCancel").style.display = forced ? "none" : "";
  $("#pwErr").textContent = ""; ["#pwCur", "#pwNew", "#pwNew2"].forEach(s => $(s).value = ""); setTimeout(() => $("#pwCur").focus(), 50);
}
$("#pwCancel").onclick = () => $("#pwBox").classList.add("hidden");
$("#uPw").onclick = () => showPw(false);
$("#pwForm").onsubmit = async e => {
  e.preventDefault();
  if ($("#pwNew").value !== $("#pwNew2").value) { $("#pwErr").textContent = t("au.pwMismatch"); return; }
  try { await post("/api/auth/password", { current: $("#pwCur").value, new: $("#pwNew").value }); $("#pwBox").classList.add("hidden"); toast(t("au.pwDone")); showLogin(); }
  catch (e2) { $("#pwErr").textContent = e2.message; }
};
$("#uOut").onclick = async () => { try { await post("/api/auth/logout", {}); } catch (e) {} showLogin(); };

// ---------------- foydalanuvchilar va audit (admin)
async function loadUsers() {
  try {
    const us = await api("/api/users");
    const roles = ["radiologist", "researcher", "admin"];
    $("#usList").innerHTML = `<table><tr><th>${esc(t("au.user"))}</th><th>${esc(t("us.fullname"))}</th><th>${esc(t("us.role"))}</th><th>${esc(t("us.state"))}</th><th></th></tr>` +
      us.map(u => `<tr><td>${esc(u.username)}</td><td>${esc(u.full_name)}</td>
        <td><select data-u="${esc(u.username)}" class="uRole">${roles.map(r => `<option value="${r}" ${r === u.role ? "selected" : ""}>${esc(t("role." + r))}</option>`).join("")}</select></td>
        <td>${u.pending ? esc(t("us.pending")) : (u.active ? esc(t("us.active")) : esc(t("us.disabled")))}${u.locked_until * 1000 > Date.now() ? " · " + esc(t("us.locked")) : ""}</td>
        <td><div class="uacts"><button data-u="${esc(u.username)}" class="uReset">${esc(t("us.reset"))}</button>
            <button data-u="${esc(u.username)}" data-a="${u.active ? 0 : 1}" class="uAct">${esc(u.active ? t("us.disable") : t("us.enable"))}</button></div></td></tr>`).join("") + "</table>";
    document.querySelectorAll(".uRole").forEach(s => s.onchange = () => post(`/api/users/${s.dataset.u}`, { role: s.value }).then(() => toast(t("us.saved"))).catch(fail));
    document.querySelectorAll(".uAct").forEach(b => b.onclick = () => post(`/api/users/${b.dataset.u}`, { active: +b.dataset.a }).then(loadUsers).catch(fail));
    document.querySelectorAll(".uReset").forEach(b => b.onclick = async () => {
      try { const r = await post(`/api/users/${b.dataset.u}`, { reset_password: true }); showCode(b.dataset.u, r.reset_code, r.expires_minutes); } catch (e) { fail(e); } });
    const au = await api("/api/audit?limit=300");
    $("#auList").innerHTML = `<table><tr><th>${esc(t("us.time"))}</th><th>${esc(t("au.user"))}</th><th>IP</th><th>${esc(t("us.action"))}</th><th>${esc(t("us.target"))}</th><th></th></tr>` +
      au.map(a => `<tr><td>${new Date(a.t * 1000).toLocaleString(LANG === "en" ? "en-GB" : LANG === "ru" ? "ru-RU" : "uz-UZ")}</td><td>${esc(a.username || "—")}</td><td>${esc(a.ip)}</td>
        <td>${esc(t("act." + a.action))}</td><td>${esc(a.target || "")}</td><td>${a.ok ? "✓" : "✗"}</td></tr>`).join("") + "</table>";
  } catch (e) { fail(e); }
}
function showCode(login, code, minutes) {      // bir martalik kod bir marta ko‘rsatiladi; parolni admin bilmaydi
  const el = $("#nuOut"); el.classList.remove("hidden");
  const when = minutes >= 120 ? Math.round(minutes / 60) + " " + t("us.hours") : minutes + " " + t("us.minutes");
  el.textContent = `${t("au.user")}: ${login}\n${t("us.code")}: ${code}\n${t("us.codeHint").replace("{when}", when)}`;
}
$("#nuBtn").onclick = async () => {
  try { const r = await post("/api/users", { username: $("#nuLogin").value, full_name: $("#nuName").value, role: $("#nuRole").value });
    showCode(r.username || $("#nuLogin").value.trim().toLowerCase(), r.invite_code, (r.expires_hours || 72) * 60);
    $("#nuLogin").value = ""; $("#nuName").value = ""; loadUsers(); } catch (e) { fail(e); }
};

applyI18n();
document.querySelectorAll(".lang button").forEach(b => b.classList.toggle("active", b.dataset.lang === LANG));
fetch("/api/auth/me", { credentials: "same-origin" }).then(r => r.ok ? r.json() : null).then(u => u ? setUser(u) : showLogin()).catch(showLogin);
