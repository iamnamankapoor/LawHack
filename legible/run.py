"""Run the whole pipeline on dossier/ and write out/result.json for the UI.

    .venv/Scripts/python run.py            # uses the caches, calls Jev/Claude only on cache misses
    JEV_OFFLINE=1 LLM_OFFLINE=1 ...        # demo mode: fail instead of calling any API
"""
import json
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import jevkit  # noqa: E402
from pipeline import audit, label, llm, segment, status  # noqa: E402

FACT_MIN = 0.5


def main():
    t0 = time.time()
    timings = {}

    def lap(name):
        timings[name] = round(time.time() - t0 - sum(timings.values()), 1)
        print(f"  {name:<12} {timings[name]:>6}s", flush=True)

    case, docs = segment.load_dossier()
    sentences = {s["id"]: s for d in docs for s in d["sentences"]}
    print(f"{len(docs)} documents, {len(sentences)} sentences")
    p_fact = label.is_fact(case, docs)
    fact_sids = {sid for sid, p in p_fact.items() if p >= FACT_MIN}
    lap("is_fact")
    facts = llm.propose_facts(case, docs, fact_sids)
    lap("facts(LLM)")
    assignments = label.assign(case, docs, facts, fact_sids)
    lap("assign")
    labels = label.positions(case, docs, facts, assignments)
    lap("positions")
    rows = status.build_rows(case, docs, facts, labels, sentences)
    lap("rules")
    synth = llm.synthesize(rows)
    lap("synth(LLM)")
    synth_audit = audit.check_summary([s["text"] for s in synth], rows, facts, case,
                                      linked=[s["facts"] for s in synth])
    lap("synth_check")
    base_text = llm.baseline(docs)
    lap("baseline")
    base_audit = audit.check_summary(audit.split_summary(base_text), rows, facts, case)
    lap("base_check")

    out = {
        "case": case,
        "docs": [{"meta": d["meta"], "pages": d["pages"],
                  "sentences": [{**s, "p_fact": round(p_fact.get(s["id"], 0), 3),
                                 "facts": assignments.get(s["id"], {}).get("facts", [])} for s in d["sentences"]]}
                 for d in docs],
        "facts": rows,
        "labels": labels,
        "synthesis": synth_audit,
        "baseline": {"text": base_text, "sentences": base_audit},
        "usage": {"jev": jevkit.usage_summary(), "timings_s": timings},
    }
    out_dir = pathlib.Path(os.environ.get("OUT_DIR", ROOT / "out"))
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "result.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    counts = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print(f"facts: {len(rows)}  statuses: {counts}")
    print(f"flags: {sum(len(r['flags']) for r in rows)}  "
          f"(version changes: {sum(1 for r in rows for f in r['flags'] if f['type'] == 'version_change')})")
    print(f"baseline sentences flagged: {sum(1 for s in base_audit if s['error'])}/{len(base_audit)}  "
          f"ours flagged: {sum(1 for s in synth_audit if s['error'])}/{len(synth_audit)}")
    print("jev usage:", jevkit.usage_summary())
    print(f"total {round(time.time() - t0, 1)}s -> {out_dir / 'result.json'}")


if __name__ == "__main__":
    main()
