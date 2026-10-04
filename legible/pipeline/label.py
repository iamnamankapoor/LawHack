"""Jev passes over the case file. Every question embeds its own sentence; the state is the page.

Pass 1  is_fact      noul    does the sentence state a fact of the dispute?
Pass 2  assign       choice  which canonical fact does it talk about (or none)?
Pass 3  positions    choice  writer's position / someone else's reported version
"""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import jevkit  # noqa: E402

POSITION = {
    "affirms": "The writer states, in its own name, that the fact is true",
    "admits": "The writer concedes or acknowledges the fact (for example « reconnaît », « il n'est pas "
              "contesté que »), even if it does not help its case",
    "denies": "The writer denies or disputes the fact (for example « conteste », « dément », « c'est à tort "
              "que », « n'en rapporte aucune preuve »)",
    "reports_only": "The writer only reports what someone else says about the fact, without taking a "
                    "position in this sentence",
    "no_position": "The sentence does not show any position of the writer on the fact",
}
REPORTED_POSITION = {
    "true": "The version reported from someone else says the fact is true",
    "false": "The version reported from someone else says the fact is false",
    "none": "The sentence reports no one else's version of the fact",
}


def page_state(case, doc, page):
    m = doc["meta"]
    return {
        "language": "French",
        "case": case["case"],
        "document": {
            "title": m.get("title"),
            "type": m.get("type"),
            "date": m.get("date"),
            "written_by": case["speakers"].get(m.get("author"), m.get("author")),
            "filed_by": case["speakers"].get(m.get("produced_by"), m.get("produced_by")),
        },
        "page_text": page["text"],
        "reading_notes": "In French pleadings, « la concluante », « l'exposante », « la requérante » or « nous » "
                         "designate the party that wrote the document (`document.written_by`). « Il n'est pas "
                         "contesté que » introduces an admission. « X soutient / prétend / allègue que » reports "
                         "X's version, usually to dispute it.",
    }


def _by_page(doc, sentences):
    pages = {p["page"]: p for p in doc["pages"]}
    grouped = {}
    for s in sentences:
        grouped.setdefault(s["page"], []).append(s)
    return [(pages[n], group) for n, group in sorted(grouped.items())]


def _qid(sid, suffix):
    return "q_" + "".join(c if c.isalnum() else "_" for c in sid) + "__" + suffix


def is_fact(case, docs):
    """sid -> P(sentence states a fact of the dispute)."""
    out = {}
    for doc in docs:
        for page, sents in _by_page(doc, doc["sentences"]):
            qs = {_qid(s["id"], "fact"): {
                "type": "noul",
                "instructions": "This sentence comes from a French litigation document (see `page_text`). Does "
                                "it state or report a fact of the dispute (an event, an act, a statement made by "
                                "someone, a date, a number, a circumstance: who did what, when, how much), "
                                "rather than only a legal argument, a rule of law, a procedural request or a "
                                f"formality? Sentence (French): «{s['text']}»"} for s in sents}
            ans = jevkit.ask_many(page_state(case, doc, page), qs, label="is_fact")
            for s in sents:
                out[s["id"]] = ans[_qid(s["id"], "fact")]["noul"]
    return out


def assign(case, docs, facts, sids):
    """sid -> {"facts": [fact ids], "confidence", "probabilities"} for the given sentences."""
    criteria = {f["id"]: f["statement"] for f in facts}
    criteria["none"] = "None of these facts"
    out = {}
    for doc in docs:
        mine = [s for s in doc["sentences"] if s["id"] in sids]
        for page, sents in _by_page(doc, mine):
            qs = {_qid(s["id"], "assign"): {
                "type": "choice",
                "instructions": "Which fact of the dispute does this sentence (French) state, report, admit or "
                                "deny? Pick the closest fact, or none if it matches none of them. "
                                f"Sentence: «{s['text']}»",
                "criteria": criteria} for s in sents}
            state = page_state(case, doc, page)
            ans = jevkit.ask_many(state, qs, label="assign")
            # A sentence can speak about several facts ("aucun contact" covers "informer" and "solliciter"):
            # verify each top candidate with its own Noul.
            checks, tops = {}, {}
            for s in sents:
                a = ans[_qid(s["id"], "assign")]
                probs = a.get("probabilities") or {}
                tops[s["id"]] = [f for f, p in sorted(probs.items(), key=lambda kv: -kv[1])
                                 if f != "none" and p >= 0.05][:3]
                for f in tops[s["id"]]:
                    checks[_qid(f"{s['id']}_{f}", "about")] = {
                        "type": "noul",
                        "instructions": "Does this sentence (French) state, admit, deny or report this fact, even "
                                        f"partly: «{criteria[f]}»? Sentence: «{s['text']}»"}
            about = jevkit.ask_many(state, checks, label="assign_check") if checks else {}
            for s in sents:
                a = ans[_qid(s["id"], "assign")]
                picked = [f for f in tops[s["id"]] if about[_qid(f"{s['id']}_{f}", "about")]["noul"] >= 0.5]
                if not picked and a["choice"] != "none" and (a.get("confidence") or 0) >= 0.5:
                    picked = [a["choice"]]
                out[s["id"]] = {"facts": picked, "confidence": a.get("confidence"),
                                "probabilities": a.get("probabilities")}
    return out


def positions_http(case, docs, facts, assignments, url):
    """Same contract as positions(), answered by the team's own model (see docs/LABELER.md)."""
    import json
    import urllib.request
    statement = {f["id"]: f["statement"] for f in facts}
    items = []
    for doc in docs:
        m = doc["meta"]
        pages = {p["page"]: p["text"] for p in doc["pages"]}
        for s in doc["sentences"]:
            for fid in assignments.get(s["id"], {}).get("facts", []):
                items.append({"sid": s["id"], "fact": fid, "fact_statement": statement[fid], "sentence": s["text"],
                              "page_text": pages[s["page"]], "doc_type": m.get("type"), "doc_date": m.get("date"),
                              "writer": m.get("author"), "speakers": case["speakers"]})
    out = []
    for i in range(0, len(items), 50):
        req = urllib.request.Request(url, data=json.dumps({"items": items[i:i + 50]}).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            answers = json.loads(r.read().decode("utf-8"))["labels"]
        for item, a in zip(items[i:i + 50], answers):
            out.append({"sid": item["sid"], "fact": item["fact"], **a})
    return out


def positions(case, docs, facts, assignments):
    """One label per (sentence, fact): writer position, reported speaker, reported position."""
    if os.environ.get("LABELER_URL"):
        return positions_http(case, docs, facts, assignments, os.environ["LABELER_URL"])
    statement = {f["id"]: f["statement"] for f in facts}
    speakers = dict(case["speakers"])
    speakers["none"] = "No one other than the writer: the sentence reports no one else's version"
    out = []
    for doc in docs:
        mine = [s for s in doc["sentences"] if assignments.get(s["id"], {}).get("facts")]
        writer = case["speakers"].get(doc["meta"].get("author"), doc["meta"].get("author"))
        for page, sents in _by_page(doc, mine):
            qs, pairs = {}, []
            for s in sents:
                for fid in assignments[s["id"]]["facts"]:
                    f = statement[fid]
                    key = f"{s['id']}_{fid}"
                    pairs.append((s, fid, key))
                    qs[_qid(key, "pos")] = {
                        "type": "choice",
                        "instructions": f"The document was written by {writer}. In this sentence (French), what "
                                        f"position does the writer take on the fact «{f}»? Sentence: «{s['text']}»",
                        "criteria": POSITION}
                    qs[_qid(key, "who")] = {
                        "type": "choice",
                        "instructions": f"Besides the writer of the document ({writer}), does this sentence "
                                        f"(French) report someone else's version of the fact «{f}»? If so, whose "
                                        f"version? Sentence: «{s['text']}»",
                        "criteria": speakers}
                    qs[_qid(key, "rep")] = {
                        "type": "choice",
                        "instructions": "In this sentence (French), according to the version reported from "
                                        f"someone other than the writer, is the fact «{f}» true? "
                                        f"Sentence: «{s['text']}»",
                        "criteria": REPORTED_POSITION}
            ans = jevkit.ask_many(page_state(case, doc, page), qs, label="positions")
            for s, fid, key in pairs:
                pos, who, rep = (ans[_qid(key, k)] for k in ("pos", "who", "rep"))
                out.append({
                    "sid": s["id"], "fact": fid,
                    "position": pos["choice"], "position_conf": pos.get("confidence"),
                    "reported_speaker": who["choice"], "reported_conf": who.get("confidence"),
                    "reported_position": rep["choice"], "reported_position_conf": rep.get("confidence"),
                })
    return out
