"""Unseen-decision test: baseline vs pipeline on decisions the pipeline was never tuned on.

Usage: python3 eval/run_unseen.py [model ...]
       -> runs/unseen/out/<mode>/<model>/<qid>.json (+ .verdict.json), runs/unseen/summary.md
"""
import json, os, re, sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "runs", "cli")]
from engine.answer import analyse, answer  # noqa: E402
from engine.gateway import chat  # noqa: E402
import judge  # noqa: E402

OUT = os.path.join(ROOT, "runs", "unseen", "out")
MODELS = ["anthropic/claude-haiku-4.5", "anthropic/claude-sonnet-4.6", "mistral/mistral-large-3", "mistral/mistral-small"]
QS = json.load(open(os.path.join(ROOT, "cases", "unseen", "questions.json"), encoding="utf-8"))["questions"]


def chunk(text, paras):
    """The decision's own numbered paragraphs paras[0]..paras[-1], continuation lines included."""
    a, b = paras[0], paras[-1]
    out, keep = [], False
    for line in text.split("\n"):
        m = re.match(r"^(\d{1,3})\. ", line)
        if m:
            keep = a <= int(m.group(1)) <= b
        elif line.startswith(("PAR CES MOTIFS", "Réponse de la Cour", "Enoncé", "Énoncé", "Sur le", "Mais sur", "Et sur", "Vu ")):
            keep = False
        if keep:
            out.append(line)
    return "\n".join(out).strip()


def inputs(q):
    text = open(os.path.join(ROOT, q["file"]), encoding="utf-8").read()
    if q["type"] == "chunk":
        excerpt = chunk(text, q["paragraphs"])
        prompt = f"Voici un extrait d'une décision de la Cour de cassation. {q['prompt_fr']}\n\n{excerpt}"
        return excerpt, q["prompt_fr"], prompt, q["case"] + "-chunk"
    return text, q["prompt_fr"], f"Voici une décision de la Cour de cassation :\n\n{text}\n\nQuestion : {q['prompt_fr']}", q["case"]


def run(mode, model, q):
    path = os.path.join(OUT, mode, model.split("/")[1], f"{q['id']}.json")
    if os.path.exists(path):
        return path
    text, question, prompt, key = inputs(q)
    res = {"answer": chat(model, "Tu es un assistant juridique.", prompt)} if mode == "baseline" else answer(text, question, model, key=key)
    rec = dict(res, model=model, prompt_id=q["id"], run=1, mode=mode, q=q)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(rec, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return path


if __name__ == "__main__":
    models = sys.argv[1:] or MODELS
    # Annotate every decision / excerpt once, so all models share one analysis.
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(lambda q: analyse(*[inputs(q)[i] for i in (0, 3)]), {q["case"] + q["type"]: q for q in QS}.values()))
    tasks = [(mode, m, q) for mode in ("baseline", "pipeline") for m in models for q in QS]
    with ThreadPoolExecutor(8) as ex:
        paths = list(ex.map(lambda t: run(*t), tasks))
    with ThreadPoolExecutor(6) as ex:
        verdicts = list(ex.map(judge.judge, paths))
    score = defaultdict(lambda: defaultdict(int))
    for p, v in zip(paths, verdicts):
        rec = json.load(open(p, encoding="utf-8"))
        kind = "chunk" if rec["q"]["type"] == "chunk" else "trap"
        score[(rec["model"], rec["mode"])][(kind, v["verdict"])] += 1
    lines = ["| Model | Mode | Traps pass (of 20) | Excerpts pass (of 9) | Total pass | Hard fails |", "|---|---|---|---|---|---|"]
    for m in models:
        for mode in ("baseline", "pipeline"):
            s = score[(m, mode)]
            t, c = s[("trap", "PASS")], s[("chunk", "PASS")]
            lines.append(f"| {m.split('/')[1]} | {mode} | {t} | {c} | {t + c}/{len(QS)} | {s[('trap', 'FAIL')] + s[('chunk', 'FAIL')]} |")
    os.makedirs(os.path.join(ROOT, "runs", "unseen"), exist_ok=True)
    open(os.path.join(ROOT, "runs", "unseen", "summary.md"), "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))
