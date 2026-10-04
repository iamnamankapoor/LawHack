"use strict";
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const ICON = {
  ok: '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M2.5 6.3l2.3 2.3 4.7-5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  no: '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M3.5 3.5l5 5M8.5 3.5l-5 5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
  open: '<svg viewBox="0 0 12 12" aria-hidden="true"><circle cx="6" cy="6" r="4" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M3.2 8.8l5.6-5.6" stroke="currentColor" stroke-width="1.4"/></svg>',
  back: '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M9.3 4.6A3.6 3.6 0 1 0 9.4 7.8" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/><path d="M9.6 2.2v2.6H7" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  warn: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 2l6.5 11.5h-13z" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/><path d="M8 6.5v3M8 11.6v.1" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>',
  info: '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6.2" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M8 7.2v4M8 4.9v.1" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
  shield: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1.8l5 2v4c0 3.1-2.1 5.4-5 6.4-2.9-1-5-3.3-5-6.4v-4z" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/><path d="M5.6 8.2l1.7 1.7 3.2-3.4" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>',
};
const VOICE = { court: "La Cour", cour_appel: "Cour d'appel", partie: "Partie", jurisprudence_anterieure: "Jurisprudence antérieure", faits: "Faits et procédure" };
const VOICE_COLOR = { court: "var(--court)", cour_appel: "var(--ca)", partie: "var(--party)", jurisprudence_anterieure: "var(--prior)", faits: "var(--facts)" };
const STANCE = {
  quashed: ["censuré par la Cour", "no", ICON.no], approved: ["approuvé par la Cour", "ok", ICON.ok],
  approved_restated_only: ["approuvé pour le seul motif repris", "ok", ICON.ok], not_ruled: ["non tranché par la Cour", "open", ICON.open],
  argument_rejected: ["argument écarté", "no", ICON.no], argument_accepted: ["argument accueilli", "ok", ICON.ok],
  overruled: ["abandonnée par la Cour", "prior", ICON.back], cited_precedent: ["citée par la Cour", "prior", ICON.back],
  no_court_answer_in_text: ["réponse de la Cour absente du texte", "open", ICON.open],
};
const SOLUTION = { REJET: "Rejet du pourvoi", CASSATION: "Cassation", CASSATION_PARTIELLE: "Cassation partielle", CASSATION_SANS_RENVOI: "Cassation sans renvoi",
  CASSATION_PARTIELLE_SANS_RENVOI: "Cassation partielle sans renvoi", RENVOI_QPC: "Renvoi de la QPC", NON_RENVOI_QPC: "Non-renvoi de la QPC", AUTRE: "Décision" };
const OUTCOME = { cassation: ["Cassé", "no", ICON.no], rejet: ["Rejeté", "ok", ICON.ok], non_examine: ["Non examiné", "open", ICON.open] };
const EXAMPLE = "C2_soc_2026-09-11_24-21242";
const EXAMPLE_QUESTION = "Selon la Cour de cassation, le seul fait que le poste de reclassement proposé soit dépourvu de responsabilité managériale suffit-il à considérer que la proposition n'est pas loyale et sérieuse ?";
const EXAMPLE_DRAFT = "Selon la Cour de cassation, le seul fait que le poste de reclassement proposé soit dépourvu de responsabilité managériale ne suffit pas à considérer que la proposition n'est pas loyale et sérieuse. La Cour casse l'arrêt de la cour d'appel de Versailles sur l'obligation de reclassement.";

// "Cour de cassation, civile, Chambre sociale, 11 septembre 2026, 24-21.242, Inédit" -> "Cass. soc., 11 sept. 2026, n° 24-21.242"
const CHAMBER = { "Chambre sociale": "soc.", "Chambre civile 1": "1re civ.", "Chambre civile 2": "2e civ.", "Chambre civile 3": "3e civ.",
  "Chambre commerciale": "com.", "Chambre criminelle": "crim.", "Assemblée plénière": "ass. plén.", "Chambre mixte": "ch. mixte" };
const MONTH = { janvier: "janv.", février: "févr.", juillet: "juill.", septembre: "sept.", octobre: "oct.", novembre: "nov.", décembre: "déc." };
function cite(title) {
  const m = title.match(/Chambre [^,]+|Assemblée plénière|Chambre mixte/), d = title.match(/(\d{1,2}) (\p{L}+) (\d{4})/u), n = title.match(/\d{2}-\d{2}\.\d{3}/);
  return m && d && n ? `Cass. ${CHAMBER[m[0]] || m[0]}, ${d[1]} ${MONTH[d[2]] || d[2]} ${d[3]}, n° ${n[0]}` : title;
}
const chip = (cls, label, icon = "") => `<span class="chip ${cls}">${icon}${esc(label)}</span>`;
const stanceChip = (k) => (k && STANCE[k] ? chip(STANCE[k][1], STANCE[k][0], STANCE[k][2]) : "");
const voiceChip = (v, stance) => (v === "court" ? chip("court", "La Cour") : `${chip(v, VOICE[v] || v)}${stanceChip(stance)}`);
const normRef = (r) => r.replace(/\s/g, "");
const showRef = (r) => r.replace(/^§(\d)/, "§ $1").replace(/^s(\d+)$/, "passage $1");
const refBtn = (r) => `<button type="button" class="ref" data-ref="${esc(normRef(r))}">${esc(showRef(normRef(r)))}</button>`;
const show = (id) => ["#landing", "#loading", "#work"].forEach((x) => ($(x).hidden = x !== id));
const json = (body) => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

let D = null; // current decision

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Une erreur est survenue. Réessayez.");
  return res.json();
}

/* ---------- intake ---------- */
async function analyze({ file, text, sample }) {
  $("#err").hidden = true;
  show("#loading");
  const fd = new FormData();
  if (file) fd.append("file", file); else if (sample) fd.append("sample", sample); else fd.append("text", text);
  const t0 = performance.now();
  try {
    D = await api("/api/analyze", { method: "POST", body: fd });
    D.seconds = (performance.now() - t0) / 1000;
    D.example = sample === EXAMPLE;
    renderWork();
  } catch (e) {
    show("#landing");
    $("#err").textContent = e.message;
    $("#err").hidden = false;
  }
}

/* ---------- reader ---------- */
function groundTitle(g) {
  if (!g) return "Moyen";
  if (/relevé d'office/i.test(g)) return "Moyen relevé d'office";
  const t = g.replace(/^(Mais |Et )?[Ss]ur (le |la |les )?/, "").replace(/,.*$/, "");
  return t.charAt(0).toUpperCase() + t.slice(1);
}

function paraHTML(s) {
  const disp = s.section === "dispositif";
  const unsure = s.p != null && s.p < 0.6 && s.section === "body" ? chip("open", "attribution à vérifier", ICON.warn) : "";
  const labelled = !disp && s.speaker !== "court" && s.speaker !== "faits";
  const who = labelled ? `<div class="who">${esc(VOICE[s.speaker])}${stanceChip(s.stance)}${unsure}</div>` : unsure ? `<div class="who">${unsure}</div>` : "";
  const n = s.ref.startsWith("§") ? s.ref.replace("§", "§ ") : "";
  return `<div class="para ${disp ? "court disp" : s.speaker}" id="seg-${s.id}"><span class="n">${n}</span>${who}<p>${esc(s.text.replace(/^\d{1,3}\. /, ""))}</p></div>`;
}

function collapsedHTML(group) {
  const voices = [...new Set(group.map((s) => s.speaker))];
  const nums = group.filter((s) => s.ref.startsWith("§")).map((s) => s.ref.slice(1));
  const span = nums.length ? ` · § ${nums[0]}${nums.length > 1 ? "–" + nums[nums.length - 1] : ""}` : "";
  const k = group.length;
  return `<button type="button" class="collapsed" data-ids="${group.map((s) => s.id).join(",")}">${voices.map((v) => `<i style="background:${VOICE_COLOR[v]}"></i>`).join("")}
    <span>${esc(voices.map((v) => VOICE[v]).join(", "))}${span} : ${k} paragraphe${k > 1 ? "s" : ""} masqué${k > 1 ? "s" : ""}</span></button>`;
}

function renderDoc() {
  let html = "", lastGround = null, lastHead = null, group = [];
  const flush = () => { if (group.length) html += collapsedHTML(group); group = []; };
  for (const s of D.segments.filter((x) => x.section !== "annexe")) {
    const head = s.section === "dispositif" ? "Dispositif" : s.section === "sommaire" ? "Titrages et résumés" : s.heading;
    if (s.section === "body" && s.ground && s.ground !== lastGround) { flush(); html += `<h2 class="ground">${esc(groundTitle(s.ground))}</h2>`; lastGround = s.ground; lastHead = null; }
    if (head && head !== lastHead) { flush(); html += `<div class="sec">${esc(head)}</div>`; lastHead = head; }
    if (s.speaker !== "court" && s.section === "body") group.push(s); else flush();
    html += paraHTML(s);
  }
  flush();
  const annex = D.segments.filter((s) => s.section === "annexe");
  if (annex.length) html += `<details class="annex"><summary>Moyens annexés (${annex.length} passages)</summary>${annex.map(paraHTML).join("")}</details>`;
  $("#doc").innerHTML = html;

  const present = new Set(D.segments.filter((s) => s.section === "body").map((s) => s.speaker));
  $("#legend").innerHTML = Object.keys(VOICE).filter((k) => present.has(k)).map((k) => `<span><i style="background:${VOICE_COLOR[k]}"></i>${esc(VOICE[k])}</span>`).join("");
}

function setCourtOnly(on) {
  const doc = $("#doc");
  doc.classList.toggle("only-court", on);
  $("#v-court").setAttribute("aria-pressed", on);
  $("#v-all").setAttribute("aria-pressed", !on);
  doc.querySelectorAll(".open-anyway").forEach((p) => p.classList.remove("open-anyway"));
  doc.querySelectorAll(".collapsed").forEach((c) => (c.hidden = false));
}

function goTo(ref) {
  const seg = D.segments.find((s) => normRef(s.ref) === normRef(ref));
  if (!seg) return;
  const el = document.getElementById(`seg-${seg.id}`);
  if (seg.speaker !== "court" && seg.section === "body") setCourtOnly(false);
  el.closest("details")?.setAttribute("open", "");
  document.querySelectorAll(".para.focus").forEach((p) => p.classList.remove("focus"));
  el.classList.add("focus");
  el.scrollIntoView({ block: "center", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  clearTimeout(goTo.t);
  goTo.t = setTimeout(() => el.classList.remove("focus"), 2600);
}

/* ---------- synthèse ---------- */
function renderHeld() {
  const h = D.holdings;
  let html = `<div><p class="sub-h">Ce que la Cour a jugé, dans ses propres mots</p><div class="outcome">${esc(SOLUTION[h.solution] || "Décision")}</div></div>`;
  for (const g of h.grounds) {
    const o = OUTCOME[g.outcome] || ["", "open", ""];
    html += `<div class="ground-card"><h3>${esc(groundTitle(g.ground))}${o[0] ? chip(o[1], o[0], o[2]) : ""}</h3>
      ${g.quotes.map((q) => `<blockquote>${esc(q.text)} ${refBtn(q.ref)}</blockquote>`).join("")}</div>`;
    if (g.not_ruled.length) html += `<div class="note open">${ICON.info}<span><strong>Non tranché par la Cour :</strong> ${g.not_ruled.map(refBtn).join(", ")}. Ces motifs de la cour d'appel ne sont ni approuvés ni censurés.</span></div>`;
  }
  const over = [...new Set(h.grounds.flatMap((g) => g.overruled))];
  if (over.length) html += `<div class="note prior">${ICON.info}<span><strong>Jurisprudence abandonnée :</strong> ${over.map(refBtn).join(", ")}. La Cour cite sa position antérieure pour s'en écarter.</span></div>`;
  html += `<details class="disp-all"><summary>Lire le dispositif</summary><p>${esc(h.dispositif)}</p></details>`;
  const qs = ["Que décide la Cour, moyen par moyen ?", "Quels motifs de la cour d'appel la Cour n'a-t-elle pas tranchés ?"];
  if (D.example) qs.unshift(EXAMPLE_QUESTION);
  html += `<div class="suggest" id="suggest">${qs.map((q) => `<button type="button">${esc(q)}</button>`).join("")}</div>`;
  $("#held").innerHTML = html;
}

function mdLite(text) {
  return esc(text).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/(^|[^*\w])\*([^*\n]+?)\*(?!\w)/g, "$1<em>$2</em>").replace(/^#+\s*/gm, "")
    .split(/\n{2,}/).map((p) => `<p>${p.replace(/\n/g, "<br>")}</p>`).join("")
    .replace(/§\s?(\d{1,3})|\bs(\d{1,3})\b/g, (m, a, b) => refBtn(a ? `§${a}` : `s${b}`));
}

async function ask(question) {
  question = question.trim();
  if (!question) return;
  $("#q").value = "";
  $("#suggest")?.remove();
  const turn = document.createElement("div");
  turn.className = "turn";
  turn.innerHTML = `<div class="q">${esc(question)}</div><div class="a hint"><span class="dots">Lecture de la décision et vérification</span></div>`;
  $("#thread").append(turn);
  turn.scrollIntoView({ block: "end", behavior: "smooth" });
  try {
    const r = await api("/api/ask", json({ id: D.id, question }));
    const ok = r.guard_p < 0.5 && !r.outcome_error;
    const a = turn.querySelector(".a");
    a.className = "a";
    a.innerHTML = mdLite(r.answer);
    const src = r.references.map((x) => `<span class="row">${refBtn(x.ref)}${voiceChip(x.speaker, x.stance)}</span>`).join("");
    turn.insertAdjacentHTML("beforeend",
      (src ? `<div class="src">${src}</div>` : "") +
      (ok ? `<span class="verified">${ICON.shield}Vérifiée : aucune phrase n'attribue à la Cour un passage qui n'est pas le sien</span>`
          : `<span class="verified bad">${ICON.warn}${esc(r.outcome_error || "Attribution incertaine : relisez les paragraphes cités avant de réutiliser cette réponse.")}</span>`));
  } catch (e) {
    turn.querySelector(".a").innerHTML = `<span class="verified bad">${ICON.warn}${esc(e.message)}</span>`;
  }
  turn.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

/* ---------- vérifier un texte ---------- */
const VERDICT = { conforme: ["Conforme", "ok", ICON.ok], a_verifier: ["À vérifier", "open", ICON.open], a_corriger: ["À corriger", "no", ICON.no] };

async function checkDraft() {
  const draft = $("#draft").value.trim();
  if (!draft) return;
  $("#checkb").disabled = true;
  $("#checksum").textContent = "";
  $("#results").innerHTML = `<p class="hint"><span class="dots">Vérification phrase par phrase</span></p>`;
  try {
    const r = await api("/api/check", json({ id: D.id, draft }));
    const n = r.sentences.filter((s) => s.verdict === "a_corriger").length;
    $("#checksum").textContent = n ? `${n} phrase${n > 1 ? "s" : ""} à corriger` : "Aucune erreur d'attribution";
    $("#results").innerHTML = r.sentences.map((s, i) => {
      const v = VERDICT[s.verdict];
      return `<div class="sent ${s.verdict}"><div class="row">${chip(v[1], v[0], v[2])}<span class="row">${refBtn(s.source.ref)}${voiceChip(s.source.speaker, s.source.stance)}</span></div>
        <div class="s">${esc(s.sentence)}</div>${s.verdict !== "conforme" ? `<div class="why">${esc(s.reason)}</div>` : ""}
        ${s.rewrite ? `<div class="rewrite">${esc(s.rewrite)}</div><div><button class="btn ghost small" type="button" data-fix="${i}">Remplacer dans le texte</button></div>` : ""}</div>`;
    }).join("");
    $("#results").onclick = (e) => {
      const b = e.target.closest("[data-fix]"); if (!b) return;
      const s = r.sentences[+b.dataset.fix];
      $("#draft").value = $("#draft").value.replace(s.sentence, s.rewrite);
      b.textContent = "Remplacée"; b.disabled = true;
    };
  } catch (e) {
    $("#results").innerHTML = `<span class="verified bad">${ICON.warn}${esc(e.message)}</span>`;
  } finally {
    $("#checkb").disabled = false;
  }
}

/* ---------- workspace ---------- */
function setMode(id) {
  ["m-summary", "m-check"].forEach((t) => {
    const on = t === id;
    $("#" + t).setAttribute("aria-selected", on);
    $("#" + $("#" + t).getAttribute("aria-controls")).hidden = !on;
  });
}

function renderWork() {
  $("#cite").textContent = cite(D.title);
  $("#solution").textContent = SOLUTION[D.holdings.solution] || "";
  $("#case").hidden = false;
  $("#new").hidden = false;
  renderDoc();
  setCourtOnly(false);
  renderHeld();
  $("#thread").innerHTML = "";
  $("#results").innerHTML = "";
  $("#checksum").textContent = "";
  $("#draft").value = D.example ? EXAMPLE_DRAFT : "";
  $("#draft").placeholder = "Collez ici le texte à vérifier…";
  const paras = D.segments.filter((s) => s.section === "body").length;
  $("#timing").textContent = `${paras} paragraphes${D.seconds >= 0.5 ? `, analysés en ${D.seconds.toFixed(1).replace(".", ",")} s` : ""}.`;
  setMode("m-summary");
  show("#work");
  $(".reader").scrollTop = 0;
  $("#summary").scrollTop = 0;
}

function reset() {
  D = null;
  $("#case").hidden = true;
  $("#new").hidden = true;
  $("#paste").value = "";
  $("#file").value = "";
  $("#go").disabled = true;
  $("#err").hidden = true;
  show("#landing");
}

/* ---------- wiring ---------- */
document.addEventListener("click", (e) => {
  const r = e.target.closest(".ref[data-ref]");
  if (r) return goTo(r.dataset.ref);
  const c = e.target.closest(".collapsed");
  if (c) { c.dataset.ids.split(",").forEach((id) => document.getElementById(`seg-${id}`).classList.add("open-anyway")); c.hidden = true; return; }
  const s = e.target.closest("#suggest button");
  if (s) ask(s.textContent);
});
$("#v-all").onclick = () => setCourtOnly(false);
$("#v-court").onclick = () => setCourtOnly(true);
$("#m-summary").onclick = () => setMode("m-summary");
$("#m-check").onclick = () => setMode("m-check");
$("#askform").onsubmit = (e) => { e.preventDefault(); ask($("#q").value); };
$("#checkb").onclick = checkDraft;
$("#new").onclick = reset;
$(".brand").onclick = (e) => { if (D) { e.preventDefault(); reset(); } };
$("#example").onclick = () => analyze({ sample: EXAMPLE });
$("#paste").addEventListener("input", () => ($("#go").disabled = $("#paste").value.trim().length < 200));
$("#paste").addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && !$("#go").disabled) $("#go").click(); });
$("#go").onclick = () => analyze({ text: $("#paste").value });
$("#file").onchange = (e) => { if (e.target.files[0]) analyze({ file: e.target.files[0] }); };
const intake = $("#intake");
["dragenter", "dragover"].forEach((ev) => intake.addEventListener(ev, (e) => { e.preventDefault(); intake.classList.add("over"); }));
["dragleave", "drop"].forEach((ev) => intake.addEventListener(ev, (e) => { e.preventDefault(); intake.classList.remove("over"); }));
intake.addEventListener("drop", (e) => { const f = e.dataTransfer.files[0]; if (f) analyze({ file: f }); });
