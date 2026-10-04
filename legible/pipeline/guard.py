"""Le garde-fou: check any draft (human or AI) against the fact map.

Verdict per sentence, decided by code from Jev's answers:
  pass    the sentence agrees with the record, or states no fact of the dispute
  review  fact not found in the file, low confidence, or the record itself is uncertain or changed version
  block   misattributed fact, or a disputed fact presented as admitted
"""
import pathlib
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from pipeline import audit, llm  # noqa: E402
from pipeline.status import short_labels  # noqa: E402

CLAIM_MIN = 0.5
LINK_MIN = 0.45


def _sources(row, R):
    """Best proof passages for a row: each party's latest own statement, then findings."""
    picks = []
    for party, info in row["by_party"].items():
        if info["history"]:
            picks.append(info["history"][-1]["sid"])
        elif info["reported"]:
            picks.append(info["reported"][-1]["sid"])
    picks += [e["sid"] for e in row["expert"][-1:]]
    return picks or row["mentions"][:2]


def check_sentence(text, R):
    rows_by_id = {r["id"]: r for r in R["facts"]}
    label = short_labels(R["case"])
    p_claim = audit.is_claim(text)
    if p_claim < CLAIM_MIN:
        return {"text": text, "verdict": "pass", "kind": "no_fact", "reason": "Ne mentionne pas de fait du dossier",
                "p_claim": p_claim}
    ids, link_conf = audit.link(text, R["facts"])
    if not ids or link_conf < LINK_MIN:
        return {"text": text, "verdict": "review", "kind": "unknown_fact",
                "reason": "Fait introuvable dans le dossier : à vérifier", "p_claim": p_claim, "link_conf": link_conf}
    verdicts = audit.check_sentence(text, ids, rows_by_id, label)
    if not verdicts:
        return {"text": text, "verdict": "review", "kind": "unknown_fact",
                "reason": "Fait introuvable dans le dossier : à vérifier", "p_claim": p_claim, "link_conf": link_conf}
    worst = (next((v for v in verdicts if v["error"]), None) or next((v for v in verdicts if v["doubt"]), None)
             or verdicts[0])
    row = rows_by_id[worst["fact"]]
    out = {"text": text, "fact": row["id"], "statement": row["statement"], "status_label": row["status_label"],
           "record": audit.record(row, label), "sources": _sources(row, R), "claimed": worst["claimed"],
           "details": worst["details"], "p_claim": p_claim, "link_conf": link_conf}
    flags = {f["type"] for f in row["flags"]}
    if worst["error"]:
        out.update(verdict="block", kind="misattributed" if worst["why"] == "fait mal attribué" else "overstated",
                   reason=worst["why"].capitalize())
    elif worst["doubt"]:
        out.update(verdict="review", kind="doubt", reason="À relire : " + worst["details"][0])
    elif "version_change" in flags:
        out.update(verdict="review", kind="version_change",
                   reason="Une partie a changé de version sur ce fait : vérifier quelle version citer")
    elif "uncertain" in flags or link_conf < 0.6:
        out.update(verdict="review", kind="uncertain", reason="L'outil doute : à relire")
    else:
        out.update(verdict="pass", kind="ok", reason="Conforme au dossier")
    return out


def check_draft(text, R):
    sentences = audit.split_summary(text)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda s: check_sentence(s, R), sentences))
    counts = {k: sum(r["verdict"] == k for r in results) for k in ("pass", "review", "block")}
    return {"sentences": results, "counts": counts}


REWRITE_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["rewrite"],
                  "properties": {"rewrite": {"type": "string"}}}


def rewrite(sentence, fact_id, R):
    """System 2: rewrite one blocked sentence so it matches the record, citing the act and page."""
    row = next(r for r in R["facts"] if r["id"] == fact_id)
    label = short_labels(R["case"])
    sents = {s["id"]: s for d in R["docs"] for s in d["sentences"]}
    metas = {d["meta"]["id"]: d["meta"] for d in R["docs"]}
    passages = []
    for sid in _sources(row, R):
        s = sents[sid]
        m = metas[s["doc"]]
        where = f"p. {s['page']}" + (f", § {s['para']}" if s.get("para") is not None else "")
        passages.append(f"- {m.get('title')} ({label.get(m.get('author'), m.get('author'))}, {m.get('date')}), "
                        f"{where} : « {s['text']} »")
    prompt = (
        "Réécris cette phrase d'un brouillon d'avocat pour qu'elle soit fidèle au dossier : dire qui affirme, qui "
        "reconnaît et qui conteste, ne rien présenter comme admis si ce n'est pas le cas, et citer entre "
        "parenthèses l'acte et la page (par exemple « (Concl. déf. n° 2, p. 14) »). Garde le style et la longueur "
        "de la phrase d'origine. Une seule phrase.\n\n"
        f"Phrase : « {sentence} »\n\nÉtat du dossier sur ce fait :\n{audit.record(row, label)}\n\n"
        "Passages sources :\n" + "\n".join(passages))
    return llm.call("Tu corriges des brouillons d'avocat pour qu'ils restent fidèles au dossier.", prompt,
                    schema=REWRITE_SCHEMA, effort="low", max_tokens=2000, label="rewrite")["rewrite"]
