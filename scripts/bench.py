"""Benchmark LawHack (Jev registry + Mistral + verification) against a model answering alone.

    python scripts/bench.py                       # LawHack vs Mistral seul (ANSWER_MODEL)
    OPENROUTER_API_KEY=… python scripts/bench.py  # + Astra seul (BASELINE_MODEL via OpenRouter)

Every system gets the same decision and question. Answers are graded without any LLM judge:
  solution       the answer states the Judilibre solution (casse / rejette) and verify finds no CONTREDIT
  hors_sujet     the answer abstains
  moyen_decision / fait_cour
                 attribution hallucination = verify (lawhack/verify.py) marks a sentence MAL_ATTRIBUE or CONTREDIT;
                 abstaining is counted separately (honest but unhelpful)
Badges are stripped before grading so LawHack is judged on its prose like the baselines.
Caveat: verify is LawHack's own deterministic checker (lexical support + speaker cues), applied identically to all systems.
Results → bench/results.json and a Markdown table on stdout.
"""

import asyncio
import json
import os
import re
import sys
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from lawhack import verify as verifier  # noqa: E402
from lawhack.answer import NOT_ADDRESSED, _complete, ask  # noqa: E402
from lawhack.ingest import load_text  # noqa: E402
from lawhack.pipeline import analyse_async, default_client  # noqa: E402

DECISIONS = ROOT / "bench" / "decisions"
QUESTIONS = ROOT / "bench" / "questions.jsonl"
RESULTS = ROOT / "bench" / "results.json"

ALONE_PROMPT = """Tu es un assistant juridique. Réponds à la question à partir de l'arrêt de la Cour de cassation ci-dessous.
Si l'arrêt ne permet pas de répondre, réponds exactement : « L'arrêt ne traite pas cette question. »
Réponse en français, concise (au plus 5 phrases)."""

_ABSTAIN = re.compile(r"ne traite pas|n'aborde pas|ne mentionne pas|ne contient aucune|ne permet pas de répondre|aucune information", re.I)
_CASSE = re.compile(r"\bcass(e|é|ée|ent|ation)\b|\bannul", re.I)
_REJET = re.compile(r"\brejet(te|é|ée|ant)?\b", re.I)
_BADGE = re.compile(r"\s*\[[^\]]*·[^\]]*\]|\s*\[non sourcé ⚠\]")  # LawHack badges only, not « M. [X] »


def openrouter(model: str, messages: list[dict]) -> str:
    body = json.dumps({"model": model, "messages": messages, "temperature": 0}).encode()
    req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=body, headers={
        "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as response:
        return json.loads(response.read())["choices"][0]["message"]["content"].strip()


def alone(text: str, question: str, model: str, via_openrouter: bool) -> str:
    messages = [{"role": "system", "content": ALONE_PROMPT},
                {"role": "user", "content": f"Arrêt :\n\n{text}\n\nQuestion : {question}"}]
    return openrouter(model, messages) if via_openrouter else _complete(messages, model)


def grade(q: dict, answer: str, registry, solution) -> dict:
    prose = _BADGE.sub("", answer).strip()
    abstained = prose.startswith(NOT_ADDRESSED) or bool(_ABSTAIN.search(prose))
    checks = verifier.check(registry, prose, solution=solution) if prose and not abstained else []
    bad = [c["sentence"] for c in checks if c["verdict"] in ("MAL_ATTRIBUE", "CONTREDIT")]
    if q["kind"] == "hors_sujet":
        correct = abstained
    elif q["kind"] == "solution":
        cassation = q["expected"].startswith("CASSATION")
        says = bool(_CASSE.search(prose)) if cassation else bool(_REJET.search(prose))
        correct = says and not abstained and not any(c["verdict"] == "CONTREDIT" for c in checks)
    else:
        correct = not abstained and not bad
    return {"answer": prose, "abstained": abstained, "hallucinated": bad, "correct": correct,
            "verdicts": [c["verdict"] for c in checks]}


async def main() -> None:
    questions = [json.loads(line) for line in QUESTIONS.read_text().splitlines() if line.strip()]
    systems = {"LawHack": None, f"Mistral seul ({os.environ.get('ANSWER_MODEL', 'mistral-medium-latest')})":
               (os.environ.get("ANSWER_MODEL", "mistral-medium-latest"), False)}
    if os.environ.get("OPENROUTER_API_KEY"):
        systems[f"Astra seul ({os.environ.get('BASELINE_MODEL', 'openai/gpt-6-astra')})"] = (
            os.environ.get("BASELINE_MODEL", "openai/gpt-6-astra"), True)
    client = default_client()
    rows = []
    for name in sorted({q["decision"] for q in questions}):
        data = json.loads((DECISIONS / f"{name}.json").read_text())
        registry, solution = await analyse_async(load_text(data["text"]), client)
        for q in (q for q in questions if q["decision"] == name):
            for system, spec in systems.items():
                started = time.perf_counter()
                try:
                    if spec is None:
                        answer = (await ask(registry, q["question"], client, solution=solution)).render()
                    else:
                        answer = await asyncio.to_thread(alone, data["text"], q["question"], *spec)
                except Exception as error:  # one failed call must not sink the run
                    rows.append({**q, "system": system, "error": str(error)})
                    continue
                rows.append({**q, "system": system, "seconds": round(time.perf_counter() - started, 2),
                             **grade(q, answer, registry, solution)})
        print(name, "done", file=sys.stderr)
    RESULTS.write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    print(table(rows))


def table(rows: list[dict]) -> str:
    kinds = ["solution", "hors_sujet", "moyen_decision", "fait_cour"]
    by = defaultdict(list)
    for r in rows:
        by[r["system"]].append(r)
    head = "| Système | " + " | ".join(kinds) + " | hallucination d'attribution | abstention (pièges d'attribution) | erreurs | s/question |"
    out = [head, "|" + "---|" * (len(kinds) + 5)]
    for system, rs in by.items():
        ok = [r for r in rs if "error" not in r]
        cells = []
        for k in kinds:
            ks = [r for r in ok if r["kind"] == k]
            cells.append(f"{sum(r['correct'] for r in ks)}/{len(ks)}")
        traps = [r for r in ok if r["kind"] in ("moyen_decision", "fait_cour", "solution")]
        halluc = sum(bool(r["hallucinated"]) for r in traps)
        attribution = [r for r in ok if r["kind"] in ("moyen_decision", "fait_cour")]
        abst = sum(r["abstained"] for r in attribution)
        secs = sum(r["seconds"] for r in ok) / max(len(ok), 1)
        out.append(f"| {system} | " + " | ".join(cells) + f" | {halluc}/{len(traps)} | {abst}/{len(attribution)} | {len(rs) - len(ok)} | {secs:.1f} |")
    return "\n".join(out)


if __name__ == "__main__":
    asyncio.run(main())
