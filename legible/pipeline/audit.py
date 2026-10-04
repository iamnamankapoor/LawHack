"""Check written text (a draft, our summary, the LLM-alone summary) against the fact map, sentence by sentence.

System 1 extracts, rules decide: Jev reads one sentence and says what it claims (each party's position on
the fact, and how it presents the fact's status); code compares that claim with the fact map.
"""
import pathlib
import re
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import jevkit  # noqa: E402
from pipeline.segment import split_sentences  # noqa: E402
from pipeline.status import short_labels  # noqa: E402

STANCE_FR = {"affirms": "affirme", "admits": "reconnaît", "denies": "conteste", "silent": "ne se prononce pas"}
POS = {"affirms", "admits"}
DOUBT_BELOW = 0.6


def polarity(stance):
    return "pos" if stance in POS else ("neg" if stance == "denies" else None)


def record(row, label):
    """Compact French view of one fact row (shown to the lawyer and to the rewriting model)."""
    rec = {"fait": row["statement"], "statut": row["status_label"]}
    for party, info in row["by_party"].items():
        hist = [f"{STANCE_FR.get(e['stance'], e['stance'])} ({e['doc']}, {e['date']})" for e in info["history"]]
        if hist:
            rec[label[party]] = " puis ".join(hist)
        elif info.get("reported"):
            rec[label[party]] = f"{STANCE_FR.get(info['stance'])} (selon l'adversaire)"
        else:
            rec[label[party]] = "ne se prononce pas"
    for e in row["expert"]:
        rec[label.get(e.get("who"), "expert")] = STANCE_FR.get(e["stance"], e["stance"])
    if row["witnesses"]:
        rec["témoins et pièces"] = "; ".join(f"{label.get(w['who'], w['who'])} {STANCE_FR.get(w['stance'])}"
                                             for w in row["witnesses"])
    return rec


def is_claim(sentence):
    a = jevkit.ask({"language": "French", "sentence": sentence},
                   {"claim": {"type": "noul", "instructions":
                              "Is `sentence` (French) a full sentence that states, attributes or qualifies a fact of "
                              "a dispute (who did, said, admitted or denied what, a date, a number, an event), rather "
                              "than a heading, a label, a legal argument, a request to the court or a transition?"}},
                   label="audit_claim")
    return a["claim"]["noul"]


def link(sentence, facts):
    """Facts the sentence talks about: a Choice to rank them, then one Noul per top candidate."""
    criteria = {f["id"]: f["statement"] for f in facts}
    criteria["none"] = "None of these facts"
    a = jevkit.ask({"language": "French", "sentence": sentence},
                   {"link": {"type": "choice", "criteria": criteria,
                             "instructions": "Which fact of the dispute does `sentence` (French) talk about? "
                                             "Pick the closest, or none."}}, label="audit_link")["link"]
    probs = a.get("probabilities") or {}
    statement = {f["id"]: f["statement"] for f in facts}
    top = [f for f, p in sorted(probs.items(), key=lambda kv: -kv[1]) if f != "none" and p >= 0.05][:3]
    if not top:
        return [], 0.0
    qs = {f"about_{f}": {"type": "noul", "instructions": f"Does `sentence` (French) state, admit, deny or report "
                                                         f"this fact, even partly: «{statement[f]}»?"} for f in top}
    ans = jevkit.ask({"language": "French", "sentence": sentence}, qs, label="audit_about")
    picked = [(f, ans[f"about_{f}"]["noul"]) for f in top if ans[f"about_{f}"]["noul"] >= 0.5]
    return [f for f, _ in picked], max((p for _, p in picked), default=0.0)


def _claim_questions(sentence_fact_parties, label):
    """Questions on what the sentence claims about one fact (its parties' positions, its status)."""
    qs = {}
    for p in sentence_fact_parties:
        who = label[p]
        qs[f"party_{p}"] = {"type": "choice", "instructions":
                            f"According to `sentence` (French), what is the position of {who} on `fact`?",
                            "criteria": {
                                "affirms": f"The sentence says {who} affirms or maintains the fact",
                                "admits": f"The sentence says {who} admits, concedes or confirms the fact",
                                "denies": f"The sentence says {who} denies, disputes or challenges the fact",
                                "silent": f"The sentence says {who} does not take a position, does not contest it "
                                          f"or did not answer",
                                "not_said": f"The sentence says nothing about the position of {who}"}}
    qs["status"] = {"type": "choice", "instructions": "How does `sentence` (French) present `fact`?",
                    "criteria": {
                        "established": "As established, admitted by everyone, or simply as true, without any doubt "
                                       "or dispute mentioned",
                        "disputed": "As disputed between the parties",
                        "one_side": "As the claim or version of one side only",
                        "found": "As found by the expert or decided by the court",
                        "not_said": "It does not present the fact's status"}}
    return qs


def check_sentence(sentence, fact_ids, rows_by_id, label):
    verdicts = []
    for fid in fact_ids:
        row = rows_by_id.get(fid)
        if not row:
            continue
        parties = list(row["by_party"])
        ans = jevkit.ask({"language": "French", "sentence": sentence, "fact": row["statement"]},
                         _claim_questions(parties, label), label="audit_claimcheck")
        problems, doubts = [], []
        for p in parties:
            a = ans[f"party_{p}"]
            claimed, conf = a["choice"], a.get("confidence") or 0
            info = row["by_party"][p]
            actual = polarity(info["stance"])
            said_before = {polarity(e["stance"]) for e in info["history"][:-1]}
            if claimed in ("affirms", "admits", "denies"):
                if polarity(claimed) == actual:
                    continue
                msg = (f"la phrase dit que {label[p]} {STANCE_FR[claimed]} ; dans le dossier, {label[p]} "
                       f"{STANCE_FR.get(info['stance'], 'ne se prononce pas')}")
                if polarity(claimed) in said_before:
                    doubts.append(msg + " (position antérieure, abandonnée depuis)")
                elif conf < DOUBT_BELOW:
                    doubts.append(msg)
                else:
                    problems.append(("misattributed", msg))
            elif claimed == "silent" and actual == "neg":
                msg = f"la phrase dit que {label[p]} ne conteste pas ; dans le dossier, {label[p]} conteste"
                if conf >= DOUBT_BELOW:
                    problems.append(("misattributed", msg))
                else:
                    doubts.append(msg)
        st, st_conf = ans["status"]["choice"], ans["status"].get("confidence") or 0
        if st == "established" and row["status"] in ("disputed", "version_change", "denied"):
            msg = f"présenté comme acquis ; dans le dossier : {row['status_label']}"
            if st_conf >= DOUBT_BELOW:
                problems.append(("overstated", msg))
            else:
                doubts.append(msg)
        elif st == "established" and row["status"] == "alleged":
            doubts.append(f"présenté comme acquis ; dans le dossier : {row['status_label']}")
        elif st == "disputed" and row["status"] in ("constant", "admitted"):
            doubts.append(f"présenté comme contesté ; dans le dossier : {row['status_label']}")
        kind = problems[0][0] if problems else None
        verdicts.append({
            "fact": fid, "error": bool(problems), "doubt": bool(doubts) and not problems,
            "why": {"misattributed": "fait mal attribué", "overstated": "fait contesté présenté comme admis"}.get(kind, ""),
            "details": [m for _, m in problems] + doubts,
            "claimed": {p: ans[f"party_{p}"]["choice"] for p in parties} | {"status": st},
        })
    return verdicts


def check_summary(sentences, rows, facts, case, linked=None):
    """sentences: list of str. linked: optional list of fact-id lists (our synthesis already cites facts)."""
    rows_by_id = {r["id"]: r for r in rows}
    label = short_labels(case)

    def one(i):
        s = sentences[i]
        if not linked and is_claim(s) < 0.5:
            return {"text": s, "facts": [], "verdicts": [], "claim": False}
        ids = linked[i] if linked else link(s, facts)[0]
        return {"text": s, "facts": ids, "verdicts": check_sentence(s, ids, rows_by_id, label), "claim": True}

    with ThreadPoolExecutor(max_workers=6) as pool:
        out = list(pool.map(one, range(len(sentences))))
    for o in out:
        o["error"] = any(v["error"] for v in o["verdicts"])
        o["doubt"] = not o["error"] and any(v["doubt"] for v in o["verdicts"])
    return out


MD = re.compile(r"(\*\*|__|\*|`|^#+\s*|^\s*[-•]\s+|^\s*\d+[.)]\s+)", re.M)


def split_summary(text):
    """Split a written text into sentences, dropping markdown markup and headings."""
    paras = [" ".join(MD.sub("", p).split()) for p in text.split("\n") if p.strip()]
    return [s for p in paras for _, _, s in split_sentences(p) if len(s) > 3]
