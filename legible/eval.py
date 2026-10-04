"""Score the fact map and the LLM-alone baseline against the planted traps.

Ground truth: eval/traps_ai.json (planted while drafting) and eval/traps_tommy.json (planted blind by Tommy,
same format). Writes out/eval.json for the UI.
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import jevkit  # noqa: E402

POS = {"affirms", "admits", "attests", "finds", "true"}
WITNESS_OF = {"michael": "mspc"}  # Michael Scott's own words count as the MSPC side
STANCE_FR = {"affirms": "affirme", "admits": "reconnaît", "denies": "conteste", "finds": "constate",
             "attests": "atteste"}
ALERTS = {"version_change", "expert_contradicts", "witnesses_disagree", "uncertain"}


def polarity(s):
    return None if s is None else ("pos" if s in POS else "neg" if s in ("denies", "false") else None)


def load_traps():
    traps = []
    for name, source in (("traps_ai.json", "ai"), ("traps_tommy.json", "tommy")):
        p = ROOT / "eval" / name
        if p.exists():
            traps += [{**t, "source": source} for t in json.loads(p.read_text(encoding="utf-8"))]
    return traps


def rows_for_trap(trap, R):
    """Rows our pipeline linked to the sentences at the trap's locations, most mentioned first."""
    votes = {}
    for d in R["docs"]:
        for s in d["sentences"]:
            for loc in trap.get("locations", []):
                if s["doc"] == loc["doc"] and s["page"] == loc.get("page", s["page"]) and \
                        (loc.get("para") is None or s["para"] == loc["para"]):
                    for f in s["facts"]:
                        votes[f] = votes.get(f, 0) + 1
    by_id = {r["id"]: r for r in R["facts"]}
    return [by_id[f] for f, _ in sorted(votes.items(), key=lambda kv: -kv[1]) if f in by_id]


def best_row(trap, candidates, R):
    """Among candidate rows (or all rows), let Jev pick the one stating the trap's fact."""
    pool = candidates or R["facts"]
    if len(pool) == 1:
        return pool[0]
    criteria = {r["id"]: r["statement"] for r in pool}
    criteria["none"] = "None of these"
    a = jevkit.ask({"language": "French", "fact": trap["fact"]},
                   {"m": {"type": "choice", "criteria": criteria,
                          "instructions": "Which of these statements describes the same fact as `fact` (French)?"}},
                   label="eval_match")["m"]
    return next((r for r in pool if r["id"] == a["choice"]), None)


def stance_in_row(row, who):
    if who in row["by_party"]:
        return row["by_party"][who]["stance"]
    if who in ("expert", "court"):
        found = [e for e in row["expert"] if e.get("who", "expert") == who]
        return found[-1]["stance"] if found else None
    ws = [w for w in row["witnesses"] if w["who"] == who]
    if ws:
        return ws[-1]["stance"]
    party = WITNESS_OF.get(who)
    if party:  # a person quoted inside someone else's document, e.g. Michael in Pam's attestation
        rep = row["by_party"][party]["reported"]
        return rep[-1]["stance"] if rep else row["by_party"][party]["stance"]
    return None


def judge_ours(trap, row):
    if row is None:
        return False, "fait non retrouvé dans la carte"
    misses = []
    for who, exp in trap.get("expected", {}).items():
        got = stance_in_row(row, who)
        if polarity(got) != polarity(exp):
            misses.append(f"{who}: attendu {STANCE_FR.get(exp, exp)}, trouvé {STANCE_FR.get(got, got or 'rien')}")
    st, want = row["status"], trap.get("expected_status")
    flags = {f["type"] for f in row["flags"]}
    status_ok = (want is None or st == want or (want == "version_change" and "version_change" in flags)
                 or (want == "disputed" and st in ("disputed", "version_change"))
                 or (want == "found_by_expert" and bool(row["expert"])))
    if not status_ok:
        misses.append(f"statut attendu {want}, trouvé {st}")
    if want == "constant" and flags & ALERTS - {"uncertain"}:
        misses.append("fausse alerte sur un fait constant")
    return not misses, ("; ".join(misses) if misses else f"{row['id']} · {row['status_label']}")


def judge_baseline(trap, summary):
    expected = ", ".join(f"{w} {STANCE_FR.get(s, s)}" for w, s in trap.get("expected", {}).items())
    qs = {
        "mentioned": {"type": "noul", "instructions": f"Does `summary` (French) mention this fact: «{trap['fact']}»?"},
        "correct": {"type": "noul", "instructions": f"Does `summary` (French) report who affirms, admits or denies "
                                                    f"the fact «{trap['fact']}» in agreement with this ground "
                                                    f"truth: {expected} (status: {trap.get('expected_status')})?"},
        "error": {"type": "noul", "instructions": f"Does `summary` (French) make this mistake: "
                                                  f"{trap.get('llm_error_to_expect', 'a wrong attribution')}?"},
    }
    a = jevkit.ask({"language": "French", "summary": summary}, qs, label="eval_baseline")
    m, c, e = a["mentioned"]["noul"], a["correct"]["noul"], a["error"]["noul"]
    if trap.get("expected_status") == "constant":
        ok = e < 0.5
    else:
        ok = m >= 0.5 and c >= 0.5 and e < 0.5
    detail = "non mentionné" if m < 0.5 else ("erreur : " + trap.get("llm_error_to_expect", "") if e >= 0.5
                                              else "correct" if c >= 0.5 else "restitué de façon inexacte")
    return ok, detail, {"mentioned": m, "correct": c, "error": e}


MATCH_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["answers"],
    "properties": {"answers": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["id", "positions"],
        "properties": {"id": {"type": "string"}, "positions": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["who", "stance"],
            "properties": {"who": {"type": "string"},
                           "stance": {"type": "string", "enum": ["affirms", "admits", "denies", "silent"]}}}}}}}},
}


def match(R, traps, rows_by_trap):
    """Same questions to the best LLM alone (whole file in context) and to our map: who affirms / denies what."""
    from pipeline import llm
    sys.path.insert(0, str(ROOT))
    names = R["case"]["speakers"]
    questions = [{"id": t["id"], "fact": t["fact"],
                  "answer_for": {w: names.get(w, names.get(WITNESS_OF.get(w, ""), w)) for w in t.get("expected", {})}}
                 for t in traps]
    docs = [{"meta": d["meta"], "pages": d["pages"]} for d in R["docs"]]
    prompt = ("Voici le dossier complet d'un contentieux. Pour chaque fait de la liste, indique la position de chaque "
              "personne demandée telle qu'elle ressort de ses propres écritures ou déclarations, dans leur dernier état : "
              "affirms (affirme), admits (reconnaît), denies (conteste) ou silent (ne se prononce pas).\n\n"
              f"FAITS (JSON) :\n{json.dumps(questions, ensure_ascii=False, indent=1)}\n\nDOSSIER\n{llm.dossier_text(docs)}")
    answers = llm.call("Tu es un avocat rigoureux.", prompt, schema=MATCH_SCHEMA, effort="medium",
                       label="match")["answers"]
    by_id = {a["id"]: {p["who"]: p["stance"] for p in a["positions"]} for a in answers}
    res = {"llm": {"wrong": 0, "abstain": 0}, "ours": {"wrong": 0, "abstain": 0}, "total": 0, "items": []}
    for t in traps:
        row = rows_by_trap.get(t["id"])
        for who, exp in t.get("expected", {}).items():
            res["total"] += 1
            llm_st = by_id.get(t["id"], {}).get(who, "silent")
            ours_st = stance_in_row(row, who) if row else None
            uncertain = row is not None and any(f["type"] == "uncertain" for f in row["flags"])
            item = {"trap": t["id"], "who": who, "expected": exp, "llm": llm_st, "ours": ours_st,
                    "ours_uncertain": uncertain}
            for side, got in (("llm", None if llm_st == "silent" else llm_st), ("ours", ours_st)):
                if got is None or (side == "ours" and uncertain and polarity(got) != polarity(exp)):
                    res[side]["abstain"] += 1
                elif polarity(got) != polarity(exp):
                    res[side]["wrong"] += 1
            res["items"].append(item)
    for side in ("llm", "ours"):
        res[side]["error_rate"] = round(100 * res[side]["wrong"] / res["total"], 1) if res["total"] else None
    return res


def main():
    R = json.loads((ROOT / "out" / "result.json").read_text(encoding="utf-8"))
    traps = load_traps()
    summary = R["baseline"]["text"]
    out, linked_rows, rows_by_trap = [], set(), {}
    for t in traps:
        row = best_row(t, rows_for_trap(t, R), R)
        if row:
            linked_rows.add(row["id"])
            rows_by_trap[t["id"]] = row
        ok, detail = judge_ours(t, row)
        b_ok, b_detail, b_raw = judge_baseline(t, summary)
        out.append({"id": t["id"], "source": t["source"], "type": t["type"], "fact": t["fact"],
                    "row": row["id"] if row else None, "ours": ok, "ours_detail": detail,
                    "baseline_ok": b_ok, "baseline_detail": b_detail, "baseline_raw": b_raw})
        print(f"{t['id']:<4} {t['type']:<22} ours={'OK ' if ok else 'MISS'} baseline={'OK ' if b_ok else 'MISS'}  {detail[:70]}")
    shown = [r for r in R["facts"] if r["mentions"]]
    alerts = [r for r in shown if r["status"] == "version_change" or {f["type"] for f in r["flags"]} & ALERTS]
    E = {"total": len(out), "facts": len(shown), "review": len(alerts),
         "ours": {"caught": sum(o["ours"] for o in out),
                  "false_alarms": sum(1 for o in out if not o["ours"] and "fausse alerte" in o["ours_detail"]),
                  "unplanned_alerts": sum(1 for r in alerts if r["id"] not in linked_rows)},
         "baseline": {"missed": sum(not o["baseline_ok"] for o in out)},
         "by_source": {s: {"total": sum(o["source"] == s for o in out),
                           "ours": sum(o["ours"] for o in out if o["source"] == s),
                           "baseline_ok": sum(o["baseline_ok"] for o in out if o["source"] == s)}
                       for s in {o["source"] for o in out}},
         "traps": out}
    E["match"] = match(R, traps, rows_by_trap)
    m = E["match"]
    print(f"match ({m['total']} attributions): LLM alone wrong {m['llm']['wrong']} ({m['llm']['error_rate']} %), "
          f"ours wrong {m['ours']['wrong']} ({m['ours']['error_rate']} %), ours 'à vérifier' {m['ours']['abstain']}")
    (ROOT / "out" / "eval.json").write_text(json.dumps(E, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nours: {E['ours']['caught']}/{E['total']} caught, false alarms {E['ours']['false_alarms']}, "
          f"unplanned alerts {E['ours']['unplanned_alerts']}")
    print(f"LLM alone: {E['baseline']['missed']}/{E['total']} missed")
    print(f"to review: {E['review']} facts out of {E['facts']}")


if __name__ == "__main__":
    main()
