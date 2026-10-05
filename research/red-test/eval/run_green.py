"""Red → green: baseline (raw decision) vs pipeline (annotated + guard), same models, same grader.

Usage: python3 eval/run_green.py [model ...] [--summary NAME]
       -> runs/green/out/<mode>/<model>/<qid>__run<N>.json (+ .verdict.json), runs/green/<NAME>.md (default: summary)
"""
import json, os, sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "runs", "cli")]
from engine.answer import answer  # noqa: E402
from engine.gateway import chat  # noqa: E402
import judge  # noqa: E402

OUT = os.path.join(ROOT, "runs", "green", "out")
MODELS = ["anthropic/claude-haiku-4.5", "anthropic/claude-sonnet-4.6", "anthropic/claude-opus-4.6"]
JOBS = [("C2-Q1", 3), ("C2-CHUNK", 1), ("C4-Q3", 1), ("C2-Q3", 1), ("C3-Q1", 1), ("C4-Q1", 1), ("C4-Q2", 1)]
QS = json.load(open(os.path.join(ROOT, "cases", "questions.json"), encoding="utf-8"))


def inputs(qid):
    """(decision text, question) for the pipeline; the baseline uses the exact red-test prompt file."""
    q = next(x for x in QS["questions"] if x["id"] == qid)
    text = open(os.path.join(ROOT, "cases", QS["cases"][q["case"]]["file"]), encoding="utf-8").read()
    if q["type"] == "chunk_only":
        a, b = q["chunk_lines"]
        return "\n".join(text.split("\n")[a - 1:b]).strip(), q["prompt_fr"].split("\n")[0].split(". ", 1)[1]
    return text, q["prompt_fr"]


def run(mode, model, qid, n):
    path = os.path.join(OUT, mode, model.split("/")[1], f"{qid}__run{n}.json")
    if os.path.exists(path):
        return path
    if mode == "baseline":
        prompt = open(os.path.join(ROOT, "runs", "prompts", f"{qid}.txt"), encoding="utf-8").read()
        res = {"answer": chat(model, "Tu es un assistant juridique.", prompt)}
    else:
        text, question = inputs(qid)
        key = qid.split("-")[0] + ("-chunk" if qid.endswith("CHUNK") else "")
        res = answer(text, question, model, key=key)
    rec = dict(res, model=model, prompt_id=qid, run=n, mode=mode)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(rec, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return path


if __name__ == "__main__":
    args = sys.argv[1:]
    name = "summary"
    if "--summary" in args:
        i = args.index("--summary"); name = args[i + 1]; del args[i:i + 2]
    MODELS = args or MODELS
    tasks = [(mode, m, q, n) for mode in ("baseline", "pipeline") for m in MODELS for q, k in JOBS for n in range(1, k + 1)]
    # Annotate each decision once before the parallel run so all models share the same cached analysis.
    for qid in ("C2-Q1", "C2-CHUNK", "C4-Q3", "C3-Q1"):
        run("pipeline", MODELS[0], qid, 1)
    with ThreadPoolExecutor(6) as ex:
        paths = list(ex.map(lambda t: run(*t), tasks))
    with ThreadPoolExecutor(6) as ex:
        verdicts = list(ex.map(judge.judge, paths))
    table = defaultdict(lambda: defaultdict(list))
    for p, v in zip(paths, verdicts):
        rec = json.load(open(p, encoding="utf-8"))
        table[(rec["mode"], rec["model"])][rec["prompt_id"]].append(v["verdict"])
    short = {"PASS": "P", "SOFT_FAIL": "s", "FAIL": "F"}
    head = "| Model | Mode | " + " | ".join(q for q, _ in JOBS) + " |"
    lines = [head, "|" + "---|" * (len(JOBS) + 2)]
    for m in MODELS:
        for mode in ("baseline", "pipeline"):
            row = table[(mode, m)]
            lines.append(f"| {m.split('/')[1]} | {mode} | " + " | ".join(" ".join(short.get(x, x) for x in row[q]) for q, _ in JOBS) + " |")
    open(os.path.join(ROOT, "runs", "green", f"{name}.md"), "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))
