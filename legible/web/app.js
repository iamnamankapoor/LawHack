"use strict";
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const ICON = {
  ok: '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M2 6.5l2.5 2.5L10 3.5" fill="none" stroke="currentColor" stroke-width="1.6"/></svg>',
  no: '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M3 3l6 6M9 3l-6 6" stroke="currentColor" stroke-width="1.6"/></svg>',
  open: '<svg viewBox="0 0 12 12" aria-hidden="true"><circle cx="6" cy="6" r="4.2" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M3 9L9 3" stroke="currentColor" stroke-width="1.4"/></svg>',
  back: '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M9.5 4.5A3.8 3.8 0 1 0 9.6 8" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M9.8 2v3h-3" fill="none" stroke="currentColor" stroke-width="1.4"/></svg>',
  warn: '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M6 1.5l4.8 8.5H1.2z" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M6 5v2.4M6 8.6v.1" stroke="currentColor" stroke-width="1.3"/></svg>',
};
const SPEAKER = { court: "Cour de cassation", cour_appel: "Cour d'appel", partie: "Partie", faits: "Faits et procédure", jurisprudence_anterieure: "Jurisprudence antérieure" };
const STANCE = {
  quashed: ["Censuré", "s-no", ICON.no], approved: ["Approuvé", "s-ok", ICON.ok],
  approved_restated_only: ["Approuvé (motif repris seulement)", "s-ok", ICON.ok], not_ruled: ["Non tranché", "s-open", ICON.open],
  argument_rejected: ["Argument écarté", "s-no", ICON.no], argument_accepted: ["Argument accueilli", "s-ok", ICON.ok],
  overruled: ["Jurisprudence abandonnée", "t-jurisprudence_anterieure", ICON.back], cited_precedent: ["Jurisprudence citée", "t-jurisprudence_anterieure", ICON.back],
  no_court_answer_in_text: ["Réponse de la Cour absente du texte", "s-open", ICON.open],
};
const SOLUTION = { REJET: "Rejet du pourvoi", CASSATION: "Cassation", CASSATION_PARTIELLE: "Cassation partielle", CASSATION_SANS_RENVOI: "Cassation sans renvoi",
  CASSATION_PARTIELLE_SANS_RENVOI: "Cassation partielle sans renvoi", RENVOI_QPC: "Renvoi de la QPC", NON_RENVOI_QPC: "Non-renvoi de la QPC", AUTRE: "Autre issue" };
const OUTCOME = { cassation: ["Cassation sur ce moyen", "s-no", ICON.no], rejet: ["Moyen rejeté", "s-ok", ICON.ok], non_examine: ["Moyen non examiné", "s-open", ICON.open] };
const RED_TEST = "C2_soc_2026-09-11_24-21242";
const DRAFT_EXAMPLE = "Selon la Cour de cassation, le seul fait que le poste de reclassement proposé soit dépourvu de responsabilité managériale ne suffit pas à considérer que la proposition n'est pas loyale et sérieuse. La Cour casse l'arrêt de la cour d'appel de Versailles sur l'obligation de reclassement. Elle retient que le refus du seul poste proposé ne suffisait pas à démontrer une recherche sérieuse et loyale de reclassement.";

let D = null; // current decision payload
// "Cour de cassation, civile, Chambre sociale, 11 septembre 2026, 24-21.242, Inédit" -> "Cass. soc., 11 sept. 2026, n° 24-21.242"
const CHAMBER = { "Chambre sociale": "soc.", "Chambre civile 1": "1re civ.", "Chambre civile 2": "2e civ.", "Chambre civile 3": "3e civ.",
  "Chambre commerciale": "com.", "Chambre criminelle": "crim.", "Assemblée plénière": "ass. plén.", "Chambre mixte": "ch. mixte" };
const MONTH = { janvier: "janv.", février: "févr.", septembre: "sept.", octobre: "oct.", novembre: "nov.", décembre: "déc.", juillet: "juill." };
function cite(title) {
  const m = title.match(/Chambre [^,]+|Assemblée plénière|Chambre mixte/);
  const d = title.match(/(\d{1,2}) (\w+) (\d{4})/u);
  const n = title.match(/\d{2}-\d{2}\.\d{3}/);
  if (!m || !d || !n) return title;
  return `Cass. ${CHAMBER[m[0]] || m[0]}, ${d[1]} ${MONTH[d[2]] || d[2]} ${d[3]}, n° ${n[0]}`;
}
const pub = (title) => (/Publié au bulletin/.test(title) ? "Publié" : /Inédit/.test(title) ? "Inédit" : "");
const tag = (cls, label, icon = "") => `<span class="tag ${cls}">${icon}${esc(label)}</span>`;
const speakerTag = (s) => tag(`t-${s}`, SPEAKER[s] || s);
const stanceTag = (k) => (k && STANCE[k] ? tag(STANCE[k][1], STANCE[k][0], STANCE[k][2]) : "");
const show = (id) => ["#landing", "#loading", "#work"].forEach((x) => ($(x).hidden = x !== id));
const normRef = (r) => r.replace(/\s/g, "");

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `Erreur ${res.status}`);
  return res.json();
}

/* ---------- landing ---------- */
async function loadSamples() {
  const list = await api("/api/samples");
  list.sort((a, b) => (a.id === RED_TEST ? -1 : b.id === RED_TEST ? 1 : 0));
  $("#samples").innerHTML = list.map((s) => {
    const kind = s.id === RED_TEST ? "Test rouge : l'erreur de Legora" : s.id.startsWith("U") ? "Test sur décision inédite" : "Corpus de test";
    return `<button type="button" data-id="${esc(s.id)}"><span class="t">${esc(cite(s.title))} <span class="k">· ${pub(s.title)}</span></span><span class="k">${kind}</span></button>`;
  }).join("");
  $("#samples").onclick = (e) => { const b = e.target.closest("button[data-id]"); if (b) analyze({ sample: b.dataset.id }); };
}

async function analyze({ file, text, sample }) {
  $("#err").hidden = true;
  show("#loading");
  const fd = new FormData();
  if (file) fd.append("file", file); else if (sample) fd.append("sample", sample); else fd.append("text", text);
  const t0 = performance.now();
  try {
    D = await api("/api/analyze", { method: "POST", body: fd });
    D.seconds = ((performance.now() - t0) / 1000).toFixed(1);
    D.sample = sample || null;
    renderWork();
  } catch (e) {
    show("#landing");
    $("#err").textContent = e.message;
    $("#err").hidden = false;
  }
}

/* ---------- decision reader ---------- */
function sectionTitle(s) {
  if (s.section === "dispositif") return "Dispositif";
  if (s.section === "sommaire") return "Titrages et résumés";
  return s.heading || "";
}

function paraHTML(s) {
  const uncertain = s.p != null && s.p < 0.6 && s.section === "body" ? tag("s-open", "À vérifier", ICON.warn) : "";
  const cls = s.section === "dispositif" ? "court disp" : s.speaker;
  return `<div class="para ${cls}" id="seg-${s.id}" data-speaker="${s.speaker}"><span class="n">${esc(s.ref.startsWith("§") ? s.ref.replace("§", "§ ") : "")}</span>
    <span class="txt">${esc(s.text.replace(/^\d{1,3}\. /, ""))}</span>
    ${s.section === "dispositif" ? "" : `<span class="meta">${speakerTag(s.speaker)}${stanceTag(s.stance)}${uncertain}</span>`}</div>`;
}

function renderDoc() {
  let html = "", lastHead = null, lastGround = null;
  const body = D.segments.filter((s) => s.section !== "annexe");
  for (const s of body) {
    const head = sectionTitle(s);
    if (s.ground && s.ground !== lastGround && s.section === "body") { html += `<div class="sec">${esc(s.ground)}</div>`; lastGround = s.ground; lastHead = null; }
    if (head && head !== lastHead) { html += s.ground && s.section === "body" ? `<div class="sub">${esc(head)}</div>` : `<div class="sec">${esc(head)}</div>`; lastHead = head; }
    html += paraHTML(s);
  }
  const annex = D.segments.filter((s) => s.section === "annexe");
  if (annex.length) html += `<details class="annex"><summary>Moyens annexés (${annex.length} passages)</summary>${annex.map(paraHTML).join("")}</details>`;
  $("#doc").innerHTML = html;

  const counts = {};
  D.segments.forEach((s) => { if (s.section === "body") counts[s.speaker] = (counts[s.speaker] || 0) + 1; });
  $("#filters").innerHTML = Object.keys(SPEAKER).filter((k) => counts[k]).map((k) =>
    `<button type="button" class="tag t-${k}" data-speaker="${k}" aria-pressed="true" title="Afficher ou masquer">${esc(SPEAKER[k])} ${counts[k]}</button>`).join("");
  $("#filters").onclick = (e) => {
    const b = e.target.closest("button[data-speaker]"); if (!b) return;
    const on = b.getAttribute("aria-pressed") !== "true";
    b.setAttribute("aria-pressed", on);
    document.querySelectorAll(`.para[data-speaker="${b.dataset.speaker}"]`).forEach((p) => p.classList.toggle("filtered", !on));
  };
}

function setCourtOnly(on) {
  $("#doc").classList.toggle("courtonly", on);
  $("#b-court").setAttribute("aria-pressed", on);
  $("#b-all").setAttribute("aria-pressed", !on);
}

function goTo(ref) {
  const seg = D.segments.find((s) => normRef(s.ref) === normRef(ref));
  if (!seg) return;
  const el = document.getElementById(`seg-${seg.id}`);
  if (seg.speaker !== "court") setCourtOnly(false);
  el.closest("details")?.setAttribute("open", "");
  el.classList.remove("filtered");
  document.querySelectorAll(".para.focus").forEach((p) => p.classList.remove("focus"));
  el.classList.add("focus");
  el.scrollIntoView({ block: "center", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
}
const refBtn = (r) => `<button type="button" class="ref" data-ref="${esc(normRef(r))}">${esc(r.replace(/^§(\d)/, "§ $1"))}</button>`;

/* ---------- Ce que la Cour a jugé ---------- */
function renderHoldings() {
  const h = D.holdings;
  let html = `<div class="outcome">${esc(SOLUTION[h.solution] || h.solution)}</div>
    <p class="muted">Les phrases ci-dessous sont celles de la Cour, citées mot pour mot. Aucune n'est reformulée.</p>`;
  for (const g of h.grounds) {
    const o = OUTCOME[g.outcome] || [g.outcome, "s-open", ""];
    html += `<div class="tile"><h3>${esc(g.ground.replace(/^(Mais |Et )?[Ss]ur /, "").replace(/^./, (c) => c.toUpperCase()))}</h3>
      <div>${tag(o[1], o[0], o[2])}</div>
      ${g.quotes.map((q) => `<p class="quote">« ${esc(q.text)} »</p><span class="cite">${refBtn(q.ref)} · texte de la Cour</span>`).join("")}</div>`;
    if (g.not_ruled.length) html += `<div class="notice" role="note">${ICON.open}<span><strong>Non tranché par la Cour&nbsp;:</strong> ${g.not_ruled.map(refBtn).join(", ")}. Ces passages ne sont pas sa position ; s'ils figurent dans un arrêt cassé, ils tombent avec lui sans être approuvés.</span></div>`;
  }
  const over = [...new Set(h.grounds.flatMap((g) => g.overruled))];
  if (over.length) html += `<div class="notice prior" role="note">${ICON.back}<span><strong>Jurisprudence abandonnée&nbsp;:</strong> ${over.map(refBtn).join(", ")}. La Cour cite sa position antérieure pour s'en écarter.</span></div>`;
  html += `<details><summary class="label" style="cursor:pointer">Dispositif complet</summary><p class="quote" style="margin-top:8px">${esc(h.dispositif)}</p></details>`;
  $("#v1").innerHTML = html;
}

/* ---------- Poser une question ---------- */
function mdLite(text) {
  return esc(text).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").split(/\n{2,}/).map((p) => `<p>${p.replace(/\n/g, "<br>")}</p>`).join("")
    .replace(/§\s?(\d{1,3})|\bs(\d{1,3})\b/g, (m, a, b) => refBtn(a ? `§${a}` : `s${b}`));
}

async function ask(question) {
  if (!question.trim()) return;
  const box = document.createElement("div");
  box.className = "qa";
  box.innerHTML = `<div class="q">${esc(question)}</div><div class="a"><span class="spin"></span> <span class="muted">Rédaction puis vérification…</span></div>`;
  $("#answers").prepend(box);
  try {
    const r = await api("/api/ask", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: D.id, question, model: $("#model").value }) });
    const ok = r.guard_p < 0.5 && !r.outcome_error;
    box.querySelector(".a").innerHTML = mdLite(r.answer);
    box.insertAdjacentHTML("beforeend",
      (r.references.length ? `<div class="cited"><span class="label">Sources citées</span>${r.references.map((x) => `${refBtn(x.ref)}${speakerTag(x.speaker)}${stanceTag(x.stance)}`).join(" ")}</div>` : "") +
      (ok ? `<div class="notice ok" role="note">${ICON.ok}<span>Vérifiée : aucune phrase n'attribue à la Cour un passage qui n'est pas le sien${r.regenerated ? " (réponse corrigée après un premier contrôle)" : ""}.</span></div>`
          : `<div class="notice no" role="alert">${ICON.warn}<span>${esc(r.outcome_error || "Le contrôle d'attribution n'est pas satisfait : relisez les paragraphes cités avant de réutiliser cette réponse.")}</span></div>`));
  } catch (e) {
    box.querySelector(".a").innerHTML = `<div class="notice no">${ICON.warn}<span>${esc(e.message)}</span></div>`;
  }
}

function renderSuggestions() {
  const qs = ["Que décide la Cour de cassation, moyen par moyen ?", "Quels motifs de la cour d'appel la Cour n'a-t-elle pas tranchés ?"];
  if (D.sample === RED_TEST) qs.unshift("Selon la Cour de cassation, le seul fait que le poste de reclassement proposé soit dépourvu de responsabilité managériale suffit-il à considérer que la proposition n'est pas loyale et sérieuse ?");
  $("#suggest").innerHTML = qs.map((q) => `<button type="button">${esc(q)}</button>`).join("");
}

/* ---------- Vérifier un brouillon ---------- */
const VERDICT = { conforme: ["Conforme", "s-ok", ICON.ok], a_verifier: ["À vérifier", "s-open", ICON.warn], a_corriger: ["À corriger", "s-no", ICON.no] };

async function checkDraft() {
  const draft = $("#draft").value;
  if (!draft.trim()) return;
  $("#results").innerHTML = `<p><span class="spin"></span> <span class="muted">Vérification phrase par phrase…</span></p>`;
  $("#checksum").textContent = "";
  try {
    const r = await api("/api/check", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: D.id, draft, model: $("#model").value }) });
    const n = r.sentences.filter((s) => s.verdict === "a_corriger").length;
    $("#checksum").textContent = n ? `${n} phrase${n > 1 ? "s" : ""} à corriger avant envoi` : "Aucune erreur d'attribution détectée";
    $("#copyb").hidden = false;
    $("#results").innerHTML = r.sentences.map((s, i) => {
      const v = VERDICT[s.verdict];
      return `<div class="sentence ${s.verdict}">
        <div class="row">${tag(v[1], v[0], v[2])}<span class="muted">${esc(s.reason)}</span></div>
        <div class="s">« ${esc(s.sentence)} »</div>
        <div class="row"><span class="label">Source</span>${refBtn(s.source.ref)}${speakerTag(s.source.speaker)}${stanceTag(s.source.stance)}</div>
        ${s.rewrite ? `<div class="rewrite">${esc(s.rewrite)}</div><div class="row"><button class="btn tertiary" type="button" data-fix="${i}">Remplacer dans le brouillon</button></div>` : ""}
      </div>`;
    }).join("");
    $("#results").onclick = (e) => {
      const b = e.target.closest("[data-fix]"); if (!b) return;
      const s = r.sentences[+b.dataset.fix];
      $("#draft").value = $("#draft").value.replace(s.sentence, s.rewrite);
      b.textContent = "Remplacée"; b.disabled = true;
    };
  } catch (e) {
    $("#results").innerHTML = `<div class="notice no">${ICON.warn}<span>${esc(e.message)}</span></div>`;
  }
}

/* ---------- workspace ---------- */
function renderWork() {
  $("#crumb").textContent = `${cite(D.title)} · ${SOLUTION[D.holdings.solution] || ""} · ${pub(D.title)}`;
  const n = D.segments.filter((s) => s.section === "body").length;
  $("#stats").textContent = `${n} paragraphes · ${D.seconds < 0.5 ? "déjà analysée" : `analysée en ${D.seconds} s`}`;
  $("#stats").hidden = false;
  $("#new").hidden = false;
  renderDoc();
  setCourtOnly(true);
  renderHoldings();
  renderSuggestions();
  $("#answers").innerHTML = "";
  $("#results").innerHTML = "";
  $("#checksum").textContent = "";
  $("#copyb").hidden = true;
  $("#draft").value = D.sample === RED_TEST ? DRAFT_EXAMPLE : "";
  $("#draft").placeholder = "Collez ici la note ou la réponse à vérifier.";
  selectTab("t1");
  show("#work");
  document.querySelector(".reader").scrollTop = 0;
  document.querySelector(".side").scrollTop = 0;
}

function selectTab(id) {
  document.querySelectorAll("[role=tab]").forEach((t) => {
    const on = t.id === id;
    t.setAttribute("aria-selected", on);
    document.getElementById(t.getAttribute("aria-controls")).hidden = !on;
  });
}

/* ---------- wiring ---------- */
document.addEventListener("click", (e) => { const r = e.target.closest(".ref[data-ref]"); if (r) goTo(r.dataset.ref); });
document.querySelectorAll("[role=tab]").forEach((t) => t.addEventListener("click", () => selectTab(t.id)));
$("#b-court").onclick = () => setCourtOnly(true);
$("#b-all").onclick = () => setCourtOnly(false);
$("#askb").onclick = () => ask($("#q").value);
$("#q").addEventListener("keydown", (e) => { if (e.key === "Enter") ask($("#q").value); });
$("#suggest").onclick = (e) => { const b = e.target.closest("button"); if (b) { $("#q").value = b.textContent; ask(b.textContent); } };
$("#checkb").onclick = checkDraft;
$("#copyb").onclick = async () => {
  try { await navigator.clipboard.writeText($("#draft").value); $("#copyb").textContent = "Copié"; }
  catch { $("#draft").select(); }
};
$("#new").onclick = () => { D = null; $("#crumb").textContent = ""; $("#stats").hidden = true; $("#new").hidden = true; show("#landing"); };
$("#go").onclick = () => { const t = $("#paste").value; if (t.trim()) analyze({ text: t }); };
$("#file").onchange = (e) => { if (e.target.files[0]) analyze({ file: e.target.files[0] }); };
const drop = $("#drop");
["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", (e) => { const f = e.dataTransfer.files[0]; if (f) analyze({ file: f }); });
loadSamples().catch((e) => { $("#samples").innerHTML = `<p class="muted">${esc(e.message)}</p>`; });
