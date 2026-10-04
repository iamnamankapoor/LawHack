"""Benchmark: the same trap sentences checked by an LLM alone (full decision in context) and by Legible.

    .venv/Scripts/python bench.py gpt-6.1-sol gpt-6-astra mistral-medium-3-5
Writes out_arret/bench_<model>.json (read by legible.py for the site).
"""
import json
import pathlib
import re
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import baseline_openai as oa  # noqa: E402
import legible  # noqa: E402  (loads .env, mistral client)

SETS = [("dossier_arret", "eval/arret_traps.json", "Ass. plén., 22 déc. 2023"),
        ("dossier_arret_2018", "eval/arret2018_traps.json", "Civ. 2, 9 mai 2018")]
PROVIDER = {"gpt": "OpenAI", "mistral": "Mistral"}


def arret_text(folder):
    raw = (ROOT / folder / "arret.md").read_text(encoding="utf-8")
    return "\n".join(l for l in raw.split("\n---", 2)[-1].splitlines() if not l.startswith("<!-- page"))


def ask(model, prompt):
    t0 = time.time()
    if model.startswith("mistral"):
        return legible.mistral(prompt, model=model), time.time() - t0
    r = oa.ask(model, prompt)
    return r["answer"], r.get("latency_s") or (time.time() - t0)


EXCERPT_PROMPT = ("Voici des extraits d'un arrêt de la Cour de cassation, retrouvés par un moteur de recherche pour "
                  "vérifier une phrase.\n\n{arret}\n\nUn collaborateur a écrit dans une note destinée au client : "
                  "« {sentence} »\n\nCette phrase est-elle exacte au regard de l'arrêt ? Commence ta réponse par EXACTE "
                  "ou INEXACTE, puis explique en deux phrases au plus.")


def paragraphs(folder):
    """The decision split into its paragraphs (what a retrieval system indexes)."""
    raw = (ROOT / folder / "arret.md").read_text(encoding="utf-8").split("\n---", 2)[-1]
    return [p.strip() for p in raw.split("\n\n") if p.strip() and not p.startswith(("<!--", "##"))]


def excerpts(folder, sentence, k=2):
    """Top-k paragraphs by word overlap: a plain stand-in for the retrieval step of a legal assistant."""
    q = legible.tokens(sentence)
    ranked = sorted(paragraphs(folder), key=lambda p: -len(q & legible.tokens(p)) / (1 + len(legible.tokens(p))) ** 0.25)
    return "\n\n[…]\n\n".join(ranked[:k])


def run(model, mode="full"):
    rows, latencies = [], []
    for folder, traps_file, label in SETS:
        text = arret_text(folder)
        for t in json.loads((ROOT / traps_file).read_text(encoding="utf-8")):
            prompt = (oa.PROMPT.format(arret=text, sentence=t["sentence"]) if mode == "full"
                      else EXCERPT_PROMPT.format(arret=excerpts(folder, t["sentence"]), sentence=t["sentence"]))
            answer, lat = ask(model, prompt)
            head = answer.strip().upper()
            verdict = "EXACTE" if head.startswith("EXACTE") else ("INEXACTE" if head.startswith("INEXACTE") else "?")
            rows.append({"id": t["id"], "arret": label, "sentence": t["sentence"], "expected_correct": t["correct"],
                         "verdict": verdict, "ok": (verdict == "EXACTE") == t["correct"], "answer": answer,
                         "cites_paragraph": bool(re.search(r"§|paragraphe|\bpara\.", answer, re.I))})
            latencies.append(lat)
            print(f"{model:<20} {mode:<7} {t['id']:<3} {verdict:<9} {'OK ' if rows[-1]['ok'] else 'FAIL'}")
    out = {"model": model, "mode": mode, "provider": PROVIDER["mistral" if model.startswith("mistral") else "gpt"],
           "setup": ("LLM alone, full decision in context" if mode == "full" else
                     "LLM alone, given the 2 most relevant paragraphs (as a retrieval-based assistant would)"),
           "cites_paragraph": sum(r["cites_paragraph"] for r in rows),
           "total": len(rows), "errors": sum(not r["ok"] for r in rows),
           "missed_traps": sum(not r["ok"] and not r["expected_correct"] for r in rows),
           "false_alarms": sum(not r["ok"] and r["expected_correct"] for r in rows),
           "latency_avg_s": round(sum(latencies) / len(latencies), 1), "results": rows,
           "measured": time.strftime("%Y-%m-%d")}
    (ROOT / "out_arret").mkdir(exist_ok=True)
    suffix = "" if mode == "full" else "_excerpt"
    (ROOT / "out_arret" / f"bench_{model}{suffix}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{model} [{mode}]: {out['errors']}/{out['total']} errors, missed {out['missed_traps']}, "
          f"cites § {out['cites_paragraph']}/{out['total']}, avg {out['latency_avg_s']} s")


if __name__ == "__main__":
    args = sys.argv[1:]
    mode = "excerpt" if "--excerpt" in args else "full"
    for m in [a for a in args if not a.startswith("--")]:
        run(m, mode)
