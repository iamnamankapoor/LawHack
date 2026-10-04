"""Trick-question benchmark: attribution hallucinations and abstention, LawHack vs Mistral alone.

    python scripts/eval_qa.py [--limit N] [--systems lawhack,baseline]

- lawhack  : Jev registry → Jev retrieval → Mistral drafting with [S-xx] → Jev verification (lawhack.answer.ask).
- baseline : the same Mistral model, given the full decision text and the question, no registry.
- baseline+verify : the baseline answer passed through LawHack's verifier (lawhack.verify.check);
  counts how many of the baseline's hallucinations the verifier flags (MAL_ATTRIBUE / NON_SOURCE).
Each answer is graded blind by a judge model (mistral-large) against the reviewed gold answer of
eval/questions.jsonl. Results → eval/results/qa.json
"""

import argparse
import asyncio
import gzip
import json
import os
import random
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from lawhack import service  # noqa: E402
from lawhack.answer import ask  # noqa: E402
from lawhack.ingest import load_text  # noqa: E402
from lawhack.pipeline import analyse_async  # noqa: E402
from lawhack.system_one import TypeSafeSystemOne  # noqa: E402
from lawhack.verify import check  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
from eval_zones import Throttled  # noqa: E402

QUESTIONS = ROOT / "eval" / "questions.jsonl"
SAMPLE = ROOT / "eval" / "data" / "judilibre_sample.jsonl.gz"
RESULTS = ROOT / "eval" / "results"
ANSWER_MODEL = os.environ.get("ANSWER_MODEL", "mistral-medium-latest")
JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "mistral-large-latest")

BASELINE_PROMPT = ("Tu es un assistant juridique. Réponds à la question en t'appuyant sur l'arrêt de la Cour de cassation "
                   "fourni. Réponse en français, concise (au plus 5 phrases).")

JUDGE_PROMPT = """Tu évalues la réponse d'un assistant juridique à une question sur un arrêt de la Cour de cassation.
Tu disposes de la réponse de référence (relue par un juriste) et du piège d'attribution à éviter.

Définitions :
- attribution_error : la réponse attribue un énoncé au mauvais locuteur. Typiquement : présenter l'argument d'une
  partie (le moyen) ou le motif de la cour d'appel comme ce que la Cour de cassation décide/juge ; ou affirmer
  comme établi un fait seulement allégué ; ou attribuer à la Cour une position qu'elle n'a pas prise.
  Une réponse qui s'abstient n'a pas d'erreur d'attribution.
- abstained : la réponse dit que l'arrêt ne traite pas la question / ne permet pas de répondre, sans répondre au fond.
- correct : la réponse est substantiellement conforme à la référence (pour une question hors arrêt : correct = abstained).
- invented : la réponse affirme un élément absent de l'arrêt (connaissance extérieure présentée comme le contenu de l'arrêt).

Réponds en JSON : {"attribution_error": bool, "abstained": bool, "correct": bool, "invented": bool, "rationale": "1 phrase"}"""


def mistral():
    from mistralai.client import Mistral

    return Mistral(api_key=os.environ["MISTRAL_API_KEY"])


def chat(messages: list[dict], model: str, json_mode: bool = False) -> str:
    from mistralai.client.errors import SDKError

    client = mistral()
    for attempt in range(6):
        try:
            response = client.chat.complete(model=model, temperature=0, messages=messages,
                                            **({"response_format": {"type": "json_object"}} if json_mode else {}))
            return response.choices[0].message.content.strip()
        except SDKError as error:
            if error.status_code not in (429, 500, 502, 503) or attempt == 5:
                raise
            time.sleep(2 ** attempt)


def decision_text(name: str) -> str:
    for line in gzip.open(SAMPLE, "rt", encoding="utf-8"):
        row = json.loads(line)
        if row["id"] == name:
            return row["text"]
    return service.read_document(sample=name).text


def judge(q: dict, answer: str) -> dict:
    content = (f"Question : {q['question']}\nType : {q['type']}\nQuestion hors arrêt (abstention attendue) : "
               f"{q['expected_abstain']}\nRéponse de référence : {q['gold_answer']}\nPiège : {q.get('trap')}\n\n"
               f"Réponse à évaluer :\n{answer}")
    return json.loads(chat([{"role": "system", "content": JUDGE_PROMPT}, {"role": "user", "content": content}],
                           JUDGE_MODEL, json_mode=True))


def bootstrap(values: list[int], iterations: int = 2000) -> list[float]:
    if not values:
        return [0.0, 0.0]
    rng = random.Random(0)
    stats = sorted(sum(rng.choice(values) for _ in values) / len(values) for _ in range(iterations))
    return [stats[int(0.025 * iterations)], stats[int(0.975 * iterations)]]


def rate(values: list[int]) -> dict:
    return {"num": sum(values), "den": len(values), "rate": sum(values) / len(values) if values else 0.0,
            "ci95": bootstrap(values)}


def summarise(rows: list[dict], system: str) -> dict:
    graded = [r for r in rows if r["system"] == system and "grade" in r]
    answerable = [r for r in graded if not r["expected_abstain"]]
    out_of_scope = [r for r in graded if r["expected_abstain"]]
    summary = {
        "questions": len(graded),
        "attribution_hallucination": rate([int(r["grade"]["attribution_error"]) for r in answerable]),
        "invented": rate([int(r["grade"]["invented"]) for r in graded]),
        "correct": rate([int(r["grade"]["correct"]) for r in graded]),
        "correct_abstention": rate([int(r["grade"]["abstained"]) for r in out_of_scope]),
        "false_abstention": rate([int(r["grade"]["abstained"]) for r in answerable]),
        "seconds_mean": sum(r["seconds"] for r in graded) / max(len(graded), 1),
        "by_type": {},
    }
    for kind in sorted({r["type"] for r in graded}):
        of_kind = [r for r in graded if r["type"] == kind]
        summary["by_type"][kind] = {
            "n": len(of_kind),
            "attribution_error": sum(r["grade"]["attribution_error"] for r in of_kind),
            "correct": sum(r["grade"]["correct"] for r in of_kind),
        }
    if system == "baseline":
        errors = [r for r in answerable if r["grade"]["attribution_error"]]
        summary["verifier_flags_baseline_errors"] = rate([int(r["verifier_flagged"]) for r in errors])
        clean = [r for r in answerable if not r["grade"]["attribution_error"] and r["grade"]["correct"]]
        summary["verifier_false_alarms"] = rate([int(r["verifier_flagged"]) for r in clean])
    return summary


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int)
    parser.add_argument("--systems", default="lawhack,baseline")
    args = parser.parse_args()
    systems = args.systems.split(",")
    questions = [json.loads(line) for line in QUESTIONS.read_text().splitlines() if line.strip()][: args.limit]
    client = Throttled(TypeSafeSystemOne())
    registries = {}
    rows: list[dict] = []
    for n, q in enumerate(questions, 1):
        if q["decision"] not in registries:
            text = decision_text(q["decision"])
            registries[q["decision"]] = ((await analyse_async(load_text(text), client))[0], text)
        registry, text = registries[q["decision"]]
        for system in systems:
            started = time.perf_counter()
            row = {"id": q["id"], "system": system, "type": q["type"], "expected_abstain": q["expected_abstain"]}
            try:
                if system == "lawhack":
                    answer = (await ask(registry, q["question"], client, ANSWER_MODEL)).render()
                else:
                    answer = await asyncio.to_thread(chat, [
                        {"role": "system", "content": BASELINE_PROMPT},
                        {"role": "user", "content": f"Arrêt :\n\n{text}\n\nQuestion : {q['question']}"}], ANSWER_MODEL)
                    flags = [c["verdict"] for c in check(registry, answer)]
                    row["verifier"] = flags
                    row["verifier_flagged"] = any(v in ("MAL_ATTRIBUE", "NON_SOURCE") for v in flags)
                row["seconds"] = time.perf_counter() - started
                row["answer"] = answer
                row["grade"] = await asyncio.to_thread(judge, q, answer)
            except Exception as error:
                row["error"] = repr(error)[:300]
            rows.append(row)
        grades = " ".join(f"{r['system']}:{'ERR' if 'error' in r else ('✗' if r['grade']['attribution_error'] else '✓')}"
                          for r in rows[-len(systems):])
        print(f"[{n}/{len(questions)}] {q['id']} {q['type']:<11} {grades}", file=sys.stderr)

    summary = {s: summarise(rows, s) for s in systems}
    summary["_config"] = {"answer_model": ANSWER_MODEL, "judge_model": JUDGE_MODEL, "system_one": client.model,
                          "questions": len(questions), "decisions": len(registries)}
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "qa.json").write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1))
    for s in systems:
        m = summary[s]
        print(f"{s:<9} hallucination d'attribution {m['attribution_hallucination']['rate']:.0%} "
              f"({m['attribution_hallucination']['num']}/{m['attribution_hallucination']['den']}) · "
              f"correct {m['correct']['rate']:.0%} · abstention juste {m['correct_abstention']['rate']:.0%} · "
              f"abstention à tort {m['false_abstention']['rate']:.0%} · invention {m['invented']['rate']:.0%} · "
              f"{m['seconds_mean']:.1f}s")
    if "baseline" in summary:
        print(f"vérificateur LawHack sur la baseline : {summary['baseline']['verifier_flags_baseline_errors']['rate']:.0%} des "
              f"hallucinations signalées, {summary['baseline']['verifier_false_alarms']['rate']:.0%} de fausses alertes")


if __name__ == "__main__":
    asyncio.run(main())
