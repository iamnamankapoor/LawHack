"""Legible: build the site data for the arrêts (registry + statuses + guard verdicts + rewrites).

    .venv/Scripts/python legible.py            # writes site/data.json

System 1 (who speaks in each sentence) is the team's model (`team_system1.py`, the `lawhack` package);
REGISTRY_SOURCE=placeholder falls back to drafting rules + Jev. Statuses and verdicts are computed by
rules; Mistral only rewrites.
"""
import json
import os
import pathlib
import re
import ssl
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import jevkit  # noqa: E402
from pipeline.segment import load_document  # noqa: E402

ARRETS = [
    {"dir": "dossier_arret", "draft": "eval/arret_traps.json", "label": "Ass. plén., 22 déc. 2023"},
    {"dir": "dossier_arret_2018", "draft": "eval/arret2018_traps.json", "label": "Civ. 2, 9 mai 2018"},
]
SPEAKERS = {  # README §5 codes
    "COUR_CASSATION": "The Cour de cassation itself writes this sentence in its own voice: its reasoning, its "
                      "ruling, or the case law, European court rulings or doctrine it cites",
    "JURIDICTION_FOND": "The sentence reports the reasoning or findings of the lower court (cour d'appel, "
                        "tribunal), e.g. « l'arrêt retient que », « selon l'arrêt attaqué », « la cour d'appel retient »",
    "DEMANDEUR": "The sentence states the argument of the appellant (the moyen: « fait grief à l'arrêt », "
                 "« alors, selon le moyen », « alors que », numbered branches 1°/ 2°/)",
    "DEFENDEUR": "The sentence states the argument of the respondent",
    "MINISTERE_PUBLIC": "The advocate general / public prosecutor speaks",
    "LOI": "The sentence only quotes or cites a legal provision",
    "INDETERMINE": "The speaker cannot be determined from the text",
}
TYPES = {
    "FAIT": "Facts of the case", "PROCEDURE": "Procedural history or formalities", "MOYEN": "An argument of a party",
    "MOTIF": "Reasoning applied to decide this case", "VISA": "The legal texts the Court relies on (« Vu… »)",
    "DISPOSITIF": "The operative part (« PAR CES MOTIFS… casse… rejette… »)",
    "CITATION": "The Court reports a former case law, another court's position or doctrine, without making it "
                "its decision here",
}
ZONES = [("dispositif", "dispositif"), ("motivation", "motivations"), ("réponse de la cour", "motivations"),
         ("moyen", "moyens"), ("exposé", "expose"), ("faits et procédure", "expose"),
         ("examen des moyens", "motivations"), ("portée", "motivations"), ("préambule", "introduction"),
         ("entête", "introduction")]
CENSURE = re.compile(r"(a violé|privé sa décision de base légale|en statuant ainsi|qu'en se déterminant ainsi|"
                     r"a méconnu|a dénaturé)", re.I)
APPROVE = re.compile(r"(a pu déduire|légalement justifié|a exactement retenu|à bon droit|a pu retenir)", re.I)
NEW_RULE = re.compile(r"(il y a lieu de considérer désormais|désormais)", re.I)


def zone_of(section):
    s = (section or "").lower()
    return next((z for key, z in ZONES if key in s), "introduction")


# ---------------------------------------------------------------- System 1 placeholder (Jev)
def label_sentences(doc):
    """One Jev request per paragraph: speaker (README codes) + statement type, per sentence."""
    paras = {}
    for s in doc["sentences"]:
        paras.setdefault((s["page"], s["id"].split(".")[2]), []).append(s)
    out = {}

    def one(group):
        state = {"language": "French", "document": doc["meta"]["title"], "zone": zone_of(group[0]["section"]),
                 "section_heading": group[0]["section"], "paragraph": " ".join(x["text"] for x in group)}
        qs = {}
        for s in group:
            k = re.sub(r"\W", "_", s["id"])
            qs[f"sp_{k}"] = {"type": "choice", "criteria": SPEAKERS,
                             "instructions": f"Who is the primary speaker of this sentence of the paragraph? Sentence: «{s['text']}»"}
            qs[f"ty_{k}"] = {"type": "choice", "criteria": TYPES,
                             "instructions": f"What kind of statement is this sentence? Sentence: «{s['text']}»"}
        ans = jevkit.ask_many(state, qs, label="legible_speaker")
        res = {}
        for s in group:
            k = re.sub(r"\W", "_", s["id"])
            sp, ty = ans[f"sp_{k}"], ans[f"ty_{k}"]
            res[s["id"]] = {"speaker": sp["choice"], "probabilities": sp.get("probabilities"),
                            "confidence": sp.get("confidence") or 0, "type": ty["choice"],
                            "type_confidence": ty.get("confidence") or 0, "source": "jev"}
        return res

    with ThreadPoolExecutor(max_workers=6) as pool:
        for res in pool.map(one, paras.values()):
            out.update(res)
    return out


MOYEN_RE = re.compile(r"(fait grief à l'arrêt|alors, selon le moyen|alors «|^\d°\s?/|^\d° -)", re.I)
FOND_RE = re.compile(r"(l'arrêt retient|selon l'arrêt attaqué|la cour d'appel retient|l'arrêt attaqué retient|"
                     r"aux motifs que|il en déduit)", re.I)
CITE_RE = re.compile(r"(\((?:v\. notamment, )?(?:Com\.|Soc\.|Crim\.|Ass\. plén\.|[123]e Civ\.|CEDH)[^)]*\)|"
                     r"Cour européenne des droits de l'homme|une partie de la doctrine|^Elle (?:estime|ajoute|souligne))")


def rule_label(s, zone):
    """Deterministic speaker labels where the drafting conventions settle it (README: rules before Jev)."""
    t = s["text"]
    if zone == "dispositif":
        return {"speaker": "COUR_CASSATION", "type": "DISPOSITIF"}
    if t.startswith("Vu "):
        return {"speaker": "COUR_CASSATION", "type": "VISA"}
    if zone == "moyens" and MOYEN_RE.search(t):
        return {"speaker": "DEMANDEUR", "type": "MOYEN"}
    if FOND_RE.search(t):
        return {"speaker": "JURIDICTION_FOND", "type": "MOTIF" if zone == "motivations" else "FAIT"}
    if zone == "motivations" and CITE_RE.search(t) and not NEW_RULE.search(t):
        return {"speaker": "COUR_CASSATION", "type": "CITATION"}
    return None


def build_registry(doc, labels):
    """README §5 entries + statuses decided by rules."""
    for s in doc["sentences"]:
        rule = rule_label(s, zone_of(s["section"]))
        if rule:
            labels[s["id"]] = {**labels[s["id"]], **rule, "confidence": max(labels[s["id"]]["confidence"], 0.95),
                               "source": "rule", "jev_speaker": labels[s["id"]]["speaker"]}
    reg, n_para, last_key = [], 0, None
    for i, s in enumerate(doc["sentences"], 1):
        key = (s["page"], s["id"].split(".")[2])
        if key != last_key:
            n_para, last_key = n_para + 1, key
        lab = labels[s["id"]]
        reg.append({"id": f"S-{i:03d}", "sid": s["id"], "paragraph": s["para"] if s["para"] is not None else None,
                    "block": n_para, "zone": zone_of(s["section"]), "section": s["section"], "page": s["page"],
                    "text": s["text"], **lab, "chain": ["COUR_CASSATION"] if lab["speaker"] == "COUR_CASSATION"
                    else ["COUR_CASSATION", lab["speaker"]]})
    return add_statuses(reg)


def add_statuses(reg):
    """Statuses decided by rules from the speaker labels, whoever produced them (placeholder or team System 1)."""
    for i, e in enumerate(reg):
        sp = e["speaker"]
        if sp in ("DEMANDEUR", "DEFENDEUR"):
            e["status"] = "ALLEGUE"
        elif sp == "JURIDICTION_FOND":
            nxt = " ".join(x["text"] for x in reg[i + 1:i + 4] if x["section"] == e["section"])
            e["status"] = "CENSURE" if CENSURE.search(nxt) else ("APPROUVE" if APPROVE.search(nxt) else "CONSTATE")
            e["censured_by"] = next((x["id"] for x in reg[i + 1:i + 4] if CENSURE.search(x["text"])), None)
        elif sp == "COUR_CASSATION":
            e["status"] = "CITE" if e["type"] == "CITATION" and not NEW_RULE.search(e["text"]) else "DECIDE"
        else:
            e["status"] = "INDETERMINE"
        e["display"] = ("solid" if e["confidence"] >= 0.8 else "check" if e["confidence"] >= 0.5 else "unknown")
    return reg


# ---------------------------------------------------------------- guard (verifier)
STOP = set("le la les de des du un une et en à au aux que qui pour par sur dans ce cette ces son sa ses il elle "
           "est sont a ont ne pas plus se s l d qu n y été être avoir dont ou".split())
CLAIMED = {"COUR_CASSATION": "The sentence presents it as the Cour de cassation's own ruling or reasoning",
           "JURIDICTION_FOND": "The sentence attributes it to the lower court (cour d'appel)",
           "PARTIE": "The sentence attributes it to a party (its argument)",
           "AUTRE": "The sentence attributes it to someone else (former case law, another court, doctrine)",
           "AUCUN": "The sentence attributes it to no one"}


def tokens(t):
    return {w for w in re.findall(r"[a-zà-ÿ0-9]+", t.lower()) if w not in STOP and len(w) > 2}


def candidates(sentence, reg, k=8):
    q = tokens(sentence)
    scored = sorted(reg, key=lambda e: -len(q & tokens(e["text"])) / (1 + len(tokens(e["text"]))) ** 0.25)
    return [e for e in scored[:k] if q & tokens(e["text"])]


def window(text, sentence, size=420):
    """The part of a long passage that overlaps the draft sentence most (long moyens hide it at the end)."""
    if len(text) <= size:
        return text
    q, best, best_i = tokens(sentence), -1, 0
    for i in range(0, len(text) - size + 1, 60):
        score = len(q & tokens(text[i:i + size]))
        if score > best:
            best, best_i = score, i
    return ("…" if best_i else "") + text[best_i:best_i + size] + "…"


def paragraph_candidates(sentence, reg, k=8):
    """Whole paragraphs (all sentences of a block), best overlap first: a draft sentence relies on a paragraph,
    and a fine-grained segmentation must not let one long sentence outweigh a paragraph split in two."""
    blocks = {}
    for e in reg:
        blocks.setdefault(e["block"], []).append(e)
    q = tokens(sentence)
    paras = [{"id": f"P{b}", "text": " ".join(x["text"] for x in es), "entries": es} for b, es in blocks.items()]
    scored = sorted(paras, key=lambda p: -len(q & tokens(p["text"])) / (1 + len(tokens(p["text"]))) ** 0.25)
    return [p for p in scored[:k] if q & tokens(p["text"])]


def check(sentence, reg):
    paras = {p["id"]: p for p in paragraph_candidates(sentence, reg)}
    crit = {pid: window(p["text"], sentence) for pid, p in paras.items()}
    crit["none"] = "None of these passages"
    ans = jevkit.ask({"language": "French", "draft_sentence": sentence},
                     {"support": {"type": "choice", "criteria": crit, "instructions":
                                  "Which passage of the decision does `draft_sentence` restate or rely on?"},
                      "claimed": {"type": "choice", "criteria": CLAIMED, "instructions":
                                  "In `draft_sentence` (French), to whom is the statement attributed?"}},
                     label="legible_check")
    sup, claimed = ans["support"], ans["claimed"]
    para, q = paras.get(sup["choice"]), tokens(sentence)
    # within the paragraph, the sentence the draft restates (first one on ties)
    e = max(para["entries"], key=lambda x: len(q & tokens(x["text"]))) if para else None
    out = {"text": sentence, "support": e["id"] if e else None, "support_conf": sup.get("confidence"),
           "claimed": claimed["choice"], "claimed_conf": claimed.get("confidence")}
    if not e or (sup.get("confidence") or 0) < 0.4:
        return verdict(out, "review", "not_found", None)
    where = f"§ {e['paragraph']}" if e["paragraph"] is not None else f"¶ {e['block']}"
    if claimed["choice"] != "COUR_CASSATION":
        return verdict(out, "pass", "attribution_ok", where)
    sp, st = e["speaker"], e["status"]
    if e["display"] == "unknown":
        return verdict(out, "review", "uncertain", where)
    if sp == "COUR_CASSATION" and st == "DECIDE":
        return verdict(out, "pass", "court_decides", where)
    if sp == "COUR_CASSATION" and st == "CITE":
        return verdict(out, "block", "cited", where)
    if sp == "JURIDICTION_FOND" and st == "CENSURE":
        return verdict(out, "block", "censured", where)
    if sp == "JURIDICTION_FOND" and st == "APPROUVE":
        return verdict(out, "review", "approved", where)
    if sp in ("DEMANDEUR", "DEFENDEUR"):
        return verdict(out, "block", "party", where)
    return verdict(out, "review", "other", where)


REASON_EN = {
    "not_found": "Passage not found in the decision: needs review",
    "attribution_ok": "Attribution matches the decision",
    "uncertain": "Speaker uncertain at {w}: needs review",
    "court_decides": "Correct: the Court itself says this",
    "cited": "The Court only cites this position ({w}); it is not its ruling",
    "censured": "This is the court of appeal ({w}), and the Court quashes it",
    "approved": "The Court upholds the court of appeal ({w}) but does not make this finding itself",
    "party": "This is a party's argument ({w}), not the Court",
    "other": "Needs review ({w})",
}
REASON_FR = {  # problem statement given to the rewriting model (French document)
    "not_found": "Passage introuvable dans l'arrêt : à vérifier",
    "attribution_ok": "Attribution conforme à l'arrêt",
    "uncertain": "Locuteur incertain au {w} : à vérifier",
    "court_decides": "Conforme : c'est la Cour qui le dit",
    "cited": "Position citée par la Cour ({w}), pas sa décision",
    "censured": "C'est la cour d'appel ({w}), et la Cour la censure",
    "approved": "La Cour approuve la cour d'appel ({w}) sans le juger elle-même",
    "party": "C'est le moyen d'une partie ({w}), pas la Cour",
    "other": "À vérifier ({w})",
}


def verdict(out, v, kind, where):
    return {**out, "verdict": v, "kind": kind, "where": where,
            "reason": REASON_EN[kind].format(w=where), "reason_fr": REASON_FR[kind].format(w=where)}


# ---------------------------------------------------------------- System 2 (Mistral) rewrite
def mistral(prompt, model="mistral-medium-3-5"):
    import certifi
    cache = ROOT / "cache" / "mistral"
    cache.mkdir(parents=True, exist_ok=True)
    import hashlib
    path = cache / (hashlib.sha256((model + prompt).encode()).hexdigest()[:20] + ".json")
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))["text"]
    import time
    body = json.dumps({"model": model, "temperature": 0, "messages": [{"role": "user", "content": prompt}]}).encode()
    for attempt in range(2):
        req = urllib.request.Request("https://api.mistral.ai/v1/chat/completions", data=body, headers={
            "Authorization": f"Bearer {os.environ['MISTRAL_API_KEY']}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120,
                                        context=ssl.create_default_context(cafile=certifi.where())) as r:
                text = json.loads(r.read().decode())["choices"][0]["message"]["content"].strip().strip("«»\" ")
            break
        except urllib.error.HTTPError as err:
            if err.code != 429 or attempt == 1:
                raise
            time.sleep(min(2 ** attempt, 30))
    path.write_text(json.dumps({"model": model, "text": text}, ensure_ascii=False), encoding="utf-8")
    return text


def rewrite(v, reg):
    """Mistral first (System 2 in the pitch); Claude when the Mistral key is rate-limited."""
    e = next(x for x in reg if x["id"] == v["support"])
    prompt = ("Réécris cette phrase d'une note d'avocat pour qu'elle attribue correctement la position au bon auteur "
              "dans l'arrêt (Cour de cassation, cour d'appel ou partie), en une seule phrase, en gardant le style, et "
              f"en citant entre parenthèses le passage ({v['where']}). Réponds par la phrase seule.\n\n"
              f"Phrase : « {v['text']} »\nProblème : {v['reason_fr']}\nPassage de l'arrêt ({v['where']}) : « {e['text']} »\n"
              f"Locuteur du passage : {e['speaker']} ; statut : {e['status']}.")
    try:
        return mistral(prompt), "mistral-medium-3-5"
    except urllib.error.HTTPError as err:
        if err.code != 429:
            raise
    from pipeline import llm
    text = llm.call("Tu corriges des notes d'avocat.", prompt, effort="low", max_tokens=2000, label="legible_rewrite")
    return text.strip().strip("«»\" "), "claude-opus-5-5"


# ---------------------------------------------------------------- live analysis (uploaded decisions)
HEADINGS = re.compile(r"^(Faits et procédure|Exposé du litige|Examen d[eu]s? moyens?|É?Enoncé du moyen|Réponse de la Cour|"
                      r"Portée et conséquences de la cassation|Moyens annexés|Moyens|Motivation|Dispositif|"
                      r"(?:Mais |Et )?[Ss]ur le (?:premier|second|deuxième|troisième|moyen)[^:]{0,120}:?)\s*$")


def text_to_markdown(text, title="Décision importée"):
    """Raw decision text (PDF extraction or paste) -> the dossier markdown format (headings, numbered paragraphs)."""
    lines = [l.strip() for l in text.replace("\r", "").split("\n")]
    blocks, cur = [], []
    for l in lines:
        if not l:
            if cur:
                blocks.append(" ".join(cur))
                cur = []
            continue
        starts_new = bool(re.match(r"^(\d{1,3}\.\s|\d°\s?/|PAR CES MOTIFS|Attendu|Mais attendu|Vu |Que de ces)", l))
        if HEADINGS.match(l) or starts_new:
            if cur:
                blocks.append(" ".join(cur))
            cur = [l]
            if HEADINGS.match(l):
                blocks.append(" ".join(cur))
                cur = []
            continue
        if cur and re.search(r"[.;:»]$", cur[-1]) and l[:1].isupper():
            blocks.append(" ".join(cur))
            cur = []
        cur.append(l)
    if cur:
        blocks.append(" ".join(cur))
    out, section = [f"---\nid: upload\ntitle: {title}\ntype: arret\nauthor: cour\nproduced_by: court\n---\n<!-- page 1 -->"], None
    for b in blocks:
        if HEADINGS.match(b):
            out.append(f"## {b.rstrip(':').strip()}")
        elif b.startswith("PAR CES MOTIFS"):
            out.append("## Dispositif")
            out.append(b)
        else:
            out.append(b)
    return "\n\n".join(out) + "\n"


def analyze_markdown(md, doc_id="upload"):
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(md)
        path = pathlib.Path(f.name)
    doc = load_document(path)
    path.unlink(missing_ok=True)
    doc["meta"]["id"] = doc_id
    return doc, build_registry(doc, label_sentences(doc))


def verify_text(text, reg, rewrites=True):
    from pipeline.audit import split_summary
    sentences = split_summary(text)
    with ThreadPoolExecutor(max_workers=6) as pool:
        verdicts = list(pool.map(lambda s: check(s, reg), sentences))
    if rewrites:
        for v in verdicts:
            if v["verdict"] != "pass" and v.get("support"):
                v["rewrite"], v["rewrite_model"] = rewrite(v, reg)
    return verdicts


def load_benchmark():
    """Measured LLM-alone results (bench.py, full decision and excerpt modes) on the trap sentences."""
    rows = []
    for path in sorted((ROOT / "out_arret").glob("bench_*.json")):
        b = json.loads(path.read_text(encoding="utf-8"))
        b.pop("results", None)  # keep the page light; full answers stay in out_arret/
        rows.append(b)
    return rows


def legible_stats():
    """Measured latency and input size of Legible's sentence check (real Jev calls, from the usage log)."""
    import statistics
    log = ROOT / "cache" / "jev_usage.jsonl"
    rows = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines() if l.strip()] if log.exists() else []
    calls = [r for r in rows if r.get("label") == "legible_check" and r.get("latency_s")]
    if not calls:
        return None
    return {"calls": len(calls), "latency_mean_s": round(statistics.mean(r["latency_s"] for r in calls), 2),
            "tokens_mean": round(statistics.mean(r["input_tokens"] for r in calls))}


TEAM_SYSTEM1 = "Speaker labels: the team's System 1 (drafting rules, then Jev) + Legible's citation rule"
PLACEHOLDER_SYSTEM1 = "Speaker labels: drafting rules + Jev (placeholder System 1)"


def team_source():
    """The team's System 1 is the registry source unless REGISTRY_SOURCE=placeholder or the package is absent."""
    if os.environ.get("REGISTRY_SOURCE", "team") != "team":
        return None
    try:
        import team_system1
        return team_system1
    except ImportError as error:
        print(f"team System 1 unavailable ({error}): placeholder labels")
        return None


def main():
    team = team_source()
    site = {"arrets": [], "benchmark": load_benchmark(), "legible_stats": legible_stats(),
            "system1": TEAM_SYSTEM1 if team else PLACEHOLDER_SYSTEM1}
    for a in ARRETS:
        folder = ROOT / a["dir"]
        case = json.loads((folder / "case.json").read_text(encoding="utf-8"))
        doc = load_document(folder / "arret.md")
        ext = os.environ.get("REGISTRY_DIR")
        if team:
            md = (folder / "arret.md").read_text(encoding="utf-8")
            reg = team.registry(team.plain_text(md), doc_id=a["dir"], rules=True)
            print(f"{doc['meta']['id']}: team System 1 registry ({len(reg)} segments)")
        elif ext and (pathlib.Path(ext) / f"{doc['meta']['id']}.json").exists():
            reg = json.loads((pathlib.Path(ext) / f"{doc['meta']['id']}.json").read_text(encoding="utf-8"))
            print(f"{doc['meta']['id']}: team registry ({len(reg)} entries)")
        else:
            reg = build_registry(doc, label_sentences(doc))
            print(f"{doc['meta']['id']}: Jev placeholder registry ({len(reg)} sentences)")
        traps = json.loads((ROOT / a["draft"]).read_text(encoding="utf-8"))
        with ThreadPoolExecutor(max_workers=6) as pool:
            verdicts = list(pool.map(lambda t: check(t["sentence"], reg), traps))
        for t, v in zip(traps, verdicts):
            v["trap"] = {k: t[k] for k in ("id", "correct", "why")}
            if v["verdict"] != "pass" and v.get("support"):
                v["rewrite"], v["rewrite_model"] = rewrite(v, reg)
            print(f"  {t['id']} {v['verdict']:<6} expected={'ok' if t['correct'] else 'wrong'}  {v['reason']}")
        site["arrets"].append({"id": doc["meta"]["id"], "label": a["label"], "case": case, "title": doc["meta"]["title"],
                               "registry": reg, "draft": verdicts})
    site["usage"] = jevkit.usage_summary()
    (ROOT / "site").mkdir(exist_ok=True)
    (ROOT / "site" / "data.json").write_text(json.dumps(site, ensure_ascii=False), encoding="utf-8")
    print("-> site/data.json", site["usage"])


if __name__ == "__main__":
    main()
