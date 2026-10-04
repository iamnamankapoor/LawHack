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
import csv
import gzip
import hashlib
import json
import math
import os
import random
import sys
import time
from collections import Counter
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
from eval_zones import Throttled, bootstrap as cluster_bootstrap  # noqa: E402

QUESTIONS = ROOT / "eval" / "questions.jsonl"
SAMPLE = ROOT / "eval" / "data" / "judilibre_sample.jsonl.gz"
RESULTS = ROOT / "eval" / "results"
CACHE = ROOT / "eval" / "cache"
HUMAN_LABELS = ROOT / "eval" / "human_labels.csv"
HUMAN_LABELS_KEY = ROOT / "eval" / "human_labels_key.json"
ANSWER_MODEL = os.environ.get("ANSWER_MODEL", "mistral-medium-latest")
JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "mistral-large-latest")
_LABELS = {"correct", "incomplete", "misgrounded", "incorrect"}

BASELINE_PROMPT = ("Tu es un assistant juridique. Réponds à la question en t'appuyant sur l'arrêt de la Cour de cassation "
                   "fourni. Réponse en français, concise (au plus 5 phrases).")

JUDGE_PROMPT = """Tu évalues, à l'aveugle, la réponse d'un assistant juridique à une question sur un arrêt de la Cour de
cassation. Tu ne sais pas quel système l'a produite ; la longueur et le style ne comptent pas.
Tu disposes de la réponse de référence (validée contre le texte de l'arrêt) et du piège d'attribution à éviter.

Définitions (une réponse peut cumuler plusieurs drapeaux) :
- attribution_error : la réponse attribue un énoncé au mauvais locuteur. Typiquement : présenter l'argument d'une
  partie (le moyen) ou le motif de la cour d'appel comme ce que la Cour de cassation décide/juge ; affirmer comme
  établi un fait seulement allégué ; attribuer à la Cour une position qu'elle n'a pas prise. Rapporter correctement
  qu'une partie soutient X, ou que la cour d'appel a retenu X, n'est PAS une erreur. Une abstention n'a pas
  d'erreur d'attribution.
- abstained : la réponse dit que l'arrêt ne traite pas la question / ne permet pas de répondre, sans répondre au fond.
- invented : la réponse affirme un élément absent de la référence et de l'arrêt (connaissance extérieure, article,
  date, nom ou montant inventé) présenté comme le contenu de l'arrêt.
- label (typologie de Magesh et al., 2024, « Hallucination-Free? ») — exactement une valeur :
  * "correct" : substantiellement conforme à la référence, locuteurs justes (hors arrêt : abstention) ;
  * "incomplete" : rien de faux, mais il manque l'élément essentiel de la référence, ou abstention à tort ;
  * "misgrounded" : le contenu est vrai quelque part dans l'arrêt mais rattaché au mauvais locuteur ou à la mauvaise
    partie de l'arrêt (c'est le cas typique d'attribution_error) ;
  * "incorrect" : contredit la référence, ou invente, ou répond au fond à une question hors arrêt.
- correct : true si et seulement si label == "correct".

Réponds en JSON : {"label": "...", "attribution_error": bool, "abstained": bool, "correct": bool, "invented": bool,
"rationale": "1 phrase"}"""


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


def hash_key(*parts: str) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def cache_file(kind: str, key: str) -> Path:
    return CACHE / kind / f"{key}.json"


def read_cache(kind: str, key: str):
    path = cache_file(kind, key)
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def write_cache(kind: str, key: str, value) -> None:
    path = cache_file(kind, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.{time.monotonic_ns()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False))
    temporary.replace(path)


def wilson(num: int, den: int, z: float = 1.959963984540054) -> list[float]:
    if den == 0:
        return [0.0, 0.0]
    p = num / den
    z2 = z * z
    factor = 1 + z2 / den
    center = (p + z2 / (2 * den)) / factor
    margin = z * math.sqrt(p * (1 - p) / den + z2 / (4 * den * den)) / factor
    return [max(0.0, center - margin), min(1.0, center + margin)]


def cohen_kappa(a: list[int], b: list[int]) -> float:
    if not a or len(a) != len(b):
        return 0.0
    observed = sum(x == y for x, y in zip(a, b)) / len(a)
    p_a = sum(a) / len(a)
    p_b = sum(b) / len(b)
    expected = p_a * p_b + (1 - p_a) * (1 - p_b)
    return (observed - expected) / (1 - expected) if expected < 1 else (1.0 if observed == 1 else 0.0)


def mcnemar(b: int, c: int) -> float:
    discordant = b + c
    if not discordant:
        return 1.0
    tail = sum(math.comb(discordant, k) for k in range(min(b, c) + 1)) / (2 ** discordant)
    return min(1.0, 2 * tail)


def _quantile_ci(values: list[float], iterations: int = 2000) -> list[float]:
    if not values:
        return [0.0, 0.0]
    values.sort()
    return [values[int(0.025 * iterations)], values[min(int(0.975 * iterations), iterations - 1)]]


def rate(values: list[int], decisions: list[str] | None = None) -> dict:
    decisions = decisions if decisions is not None else [str(i) for i in range(len(values))]
    grouped: dict[str, list[int]] = {}
    for decision, value in zip(decisions, values):
        counts = grouped.setdefault(decision, [0, 0])
        counts[0] += int(value)
        counts[1] += 1
    per_decision = list(grouped.values())
    num, den = sum(values), len(values)
    low, high = cluster_bootstrap(per_decision)
    return {"num": num, "den": den, "rate": num / den if den else 0.0, "ci95": [low, high]}


def _row_rate(rows: list[dict], predicate) -> dict:
    return rate([int(predicate(row)) for row in rows], [row["decision"] for row in rows])


def _wilson_rate(rows: list[dict], predicate) -> dict:
    num, den = sum(int(predicate(row)) for row in rows), len(rows)
    return {"num": num, "den": den, "rate": num / den if den else 0.0, "ci95": wilson(num, den)}


def summarise(rows: list[dict], system: str) -> dict:
    graded = [r for r in rows if r["system"] == system and "grade" in r]
    answerable = [r for r in graded if not r["expected_abstain"]]
    out_of_scope = [r for r in graded if r["expected_abstain"]]
    labels = Counter(r["grade"]["label"] for r in graded if r["grade"].get("label") in _LABELS)
    summary = {
        "questions": len(graded),
        "attribution_hallucination": _row_rate(answerable, lambda r: r["grade"]["attribution_error"]),
        "invented": _row_rate(graded, lambda r: r["grade"]["invented"]),
        "correct": _row_rate(graded, lambda r: r["grade"]["correct"]),
        "correct_abstention": _row_rate(out_of_scope, lambda r: r["grade"]["abstained"]),
        "false_abstention": _row_rate(answerable, lambda r: r["grade"]["abstained"]),
        "hallucination": _row_rate(graded, lambda r: r["grade"].get("label") in {"misgrounded", "incorrect"}),
        "labels": dict(labels),
        "seconds_mean": sum(r["seconds"] for r in graded) / max(len(graded), 1),
        "by_type": {},
    }
    for kind in sorted({r["type"] for r in graded}):
        of_kind = [r for r in graded if r["type"] == kind]
        summary["by_type"][kind] = {
            "n": len(of_kind),
            "attribution_error": _wilson_rate(of_kind, lambda r: r["grade"]["attribution_error"]),
            "correct": _wilson_rate(of_kind, lambda r: r["grade"]["correct"]),
        }
    if system == "lawhack":
        with_answers = [r for r in answerable if "lawhack" in r and not r["lawhack"]["abstained"]]
        sentences = [(r, sentence) for r in with_answers for sentence in r["lawhack"]["sentences"]]
        pills = [(r, pill) for r, sentence in sentences for pill in sentence["pills"]]
        summary["citation_coverage"] = rate(
            [int(bool(sentence["pills"])) for _, sentence in sentences],
            [r["decision"] for r, _ in sentences],
        )
        summary["invalid_citations"] = rate(
            [int(pill["segment_id"] not in set(r.get("registry_ids", []))) for r, pill in pills],
            [r["decision"] for r, _ in pills],
        )
        summary["unsupported_pills"] = rate(
            [int(pill["level"] != "ok") for _, pill in pills],
            [r["decision"] for r, _ in pills],
        )
        summary["supported_mean"] = (
            sum(sentence["supported"] for _, sentence in sentences) / len(sentences) if sentences else 0.0
        )
    if system == "baseline":
        errors = [r for r in answerable if r["grade"]["attribution_error"]]
        summary["verifier_flags_baseline_errors"] = _row_rate(errors, lambda r: r["verifier_flagged"])
        clean = [r for r in answerable if not r["grade"]["attribution_error"] and r["grade"]["correct"]]
        summary["verifier_false_alarms"] = _row_rate(clean, lambda r: r["verifier_flagged"])
    return summary


def _paired_values(rows: list[dict], metric: str) -> list[tuple[dict, dict, int, int]]:
    systems: dict[tuple[str, str], dict[str, dict]] = {}
    for row in rows:
        if "grade" in row:
            systems.setdefault((row["id"], row["decision"]), {})[row["system"]] = row
    pairs = []
    for systems_by_question in systems.values():
        if "lawhack" not in systems_by_question or "baseline" not in systems_by_question:
            continue
        law, base = systems_by_question["lawhack"], systems_by_question["baseline"]
        if metric == "attribution_error" and law["expected_abstain"]:
            continue
        if metric == "correct":
            a, b = int(law["grade"]["correct"]), int(base["grade"]["correct"])
        elif metric == "attribution_error":
            a, b = int(law["grade"]["attribution_error"]), int(base["grade"]["attribution_error"])
        else:
            a = int(law["grade"].get("label") in {"misgrounded", "incorrect"})
            b = int(base["grade"].get("label") in {"misgrounded", "incorrect"})
        pairs.append((law, base, a, b))
    return pairs


def paired_comparison(rows: list[dict], metric: str, iterations: int = 2000) -> dict:
    pairs = _paired_values(rows, metric)
    if metric == "correct":
        b = sum(law_value == 0 and base_value == 1 for _, _, law_value, base_value in pairs)
        c = sum(law_value == 1 and base_value == 0 for _, _, law_value, base_value in pairs)
    else:
        b = sum(law_value == 1 and base_value == 0 for _, _, law_value, base_value in pairs)
        c = sum(law_value == 0 and base_value == 1 for _, _, law_value, base_value in pairs)
    law_rate = sum(pair[2] for pair in pairs) / len(pairs) if pairs else 0.0
    baseline_rate = sum(pair[3] for pair in pairs) / len(pairs) if pairs else 0.0
    decisions: dict[str, list[tuple[dict, dict, int, int]]] = {}
    for pair in pairs:
        decisions.setdefault(pair[0]["decision"], []).append(pair)
    rng = random.Random(0)
    diffs = []
    decision_ids = list(decisions)
    for _ in range(iterations):
        sampled = [pair for _ in decision_ids for pair in decisions[rng.choice(decision_ids)]] if decision_ids else []
        if sampled:
            diffs.append(sum(p[2] - p[3] for p in sampled) / len(sampled))
        else:
            diffs.append(0.0)
    return {"n": len(pairs), "b": b, "c": c, "p": mcnemar(b, c),
            "diff": law_rate - baseline_rate, "ci95": _quantile_ci(diffs, iterations)}


def paired_summary(rows: list[dict]) -> dict:
    return {metric: paired_comparison(rows, metric) for metric in ("attribution_error", "correct", "hallucination")}


def ppi_estimate(judge_all: list[int], judge_labeled: list[int], human_labeled: list[int]) -> float:
    if not judge_all:
        return 0.0
    correction = (sum(h - j for h, j in zip(human_labeled, judge_labeled)) / len(human_labeled)
                  if human_labeled else 0.0)
    return sum(judge_all) / len(judge_all) + correction


def _ppi_rate(rows: list[dict], human_labels: dict[str, int], field: str, iterations: int = 2000) -> dict:
    eligible = [r for r in rows if field != "attribution_error" or not r["expected_abstain"]]
    key_map = {qa_key(r): human_labels[qa_key(r)] for r in eligible if qa_key(r) in human_labels}
    judge = [int(r["grade"][field]) for r in eligible]
    labeled = [(int(r["grade"][field]), key_map[qa_key(r)]) for r in eligible if qa_key(r) in key_map]
    estimate = ppi_estimate(judge, [j for j, _ in labeled], [h for _, h in labeled])
    unlabeled_judge = [int(r["grade"][field]) for r in eligible if qa_key(r) not in key_map]
    rng = random.Random(0)
    bootstrapped = []
    for _ in range(iterations):
        sample_labeled = [labeled[rng.randrange(len(labeled))] for _ in labeled] if labeled else []
        sample_unlabeled = [unlabeled_judge[rng.randrange(len(unlabeled_judge))]
                            for _ in unlabeled_judge] if unlabeled_judge else []
        sample_judge = [j for j, _ in sample_labeled] + sample_unlabeled
        bootstrapped.append(ppi_estimate(sample_judge, [j for j, _ in sample_labeled],
                                         [h for _, h in sample_labeled]))
    return {"num": sum(judge), "den": len(judge), "rate": estimate,
            "ci95": _quantile_ci(bootstrapped, iterations), "n_labeled": len(labeled)}


def qa_key(row: dict) -> str:
    return hash_key(row["system"], row["id"], row["decision"])


def _confusion(judge: list[int], human: list[int]) -> dict:
    return {
        "tn": sum(j == 0 and h == 0 for j, h in zip(judge, human)),
        "fp": sum(j == 1 and h == 0 for j, h in zip(judge, human)),
        "fn": sum(j == 0 and h == 1 for j, h in zip(judge, human)),
        "tp": sum(j == 1 and h == 1 for j, h in zip(judge, human)),
    }


def export_labels(count: int) -> None:
    data = json.loads((RESULTS / "qa.json").read_text())
    rows = data["rows"]
    if count < 0 or count > len(rows):
        raise ValueError(f"Cannot sample {count} rows from {len(rows)} QA rows")
    question_by_id = {q["id"]: q for q in (json.loads(line) for line in QUESTIONS.read_text().splitlines() if line)}
    rng = random.Random(0)
    selected = rng.sample(rows, count)
    rng.shuffle(selected)
    fieldnames = ["key", "decision", "type", "question", "gold_answer", "trap", "answer",
                  "human_attribution_error", "human_correct"]
    HUMAN_LABELS.parent.mkdir(parents=True, exist_ok=True)
    key_map = {}
    with HUMAN_LABELS.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for row in selected:
            q = question_by_id.get(row["id"], {})
            key = qa_key(row)
            key_map[key] = [row["system"], row["id"], row["decision"]]
            writer.writerow({
                "key": key, "decision": row["decision"], "type": row.get("type", q.get("type", "")),
                "question": q.get("question", row.get("question", "")),
                "gold_answer": q.get("gold_answer", row.get("gold_answer", "")),
                "trap": q.get("trap", row.get("trap", "")), "answer": row.get("answer", ""),
                "human_attribution_error": "", "human_correct": "",
            })
    HUMAN_LABELS_KEY.write_text(json.dumps(key_map, ensure_ascii=False, indent=2))
    print(f"Exported {count} rows to {HUMAN_LABELS.relative_to(ROOT)} and {HUMAN_LABELS_KEY.relative_to(ROOT)}")


def import_labels() -> dict:
    data = json.loads((RESULTS / "qa.json").read_text())
    rows = data["rows"]
    key_map = json.loads(HUMAN_LABELS_KEY.read_text())
    row_by_key = {qa_key(row): row for row in rows}
    labels: dict[str, dict[str, int]] = {}
    for csv_row in csv.DictReader(HUMAN_LABELS.open(encoding="utf-8", newline="")):
        key = csv_row.get("key", "").strip()
        if not key or key not in key_map or key not in row_by_key:
            continue
        for field, column in (("attribution_error", "human_attribution_error"), ("correct", "human_correct")):
            value = csv_row.get(column, "").strip()
            if not value:
                continue
            if value not in {"0", "1"}:
                raise ValueError(f"{column} must be 0, 1, or blank; got {value!r}")
            labels.setdefault(field, {})[key] = int(value)
    validation = {}
    for field in ("attribution_error", "correct"):
        human = labels.get(field, {})
        eligible = [r for r in rows if "grade" in r and
                    (field != "attribution_error" or not r["expected_abstain"])]
        labeled_rows = [r for r in eligible if qa_key(r) in human]
        judge_values = [int(r["grade"][field]) for r in labeled_rows]
        human_values = [human[qa_key(r)] for r in labeled_rows]
        validation[field] = {
            "n_labeled": len(labeled_rows),
            "agreement": (sum(j == h for j, h in zip(judge_values, human_values)) / len(labeled_rows)
                          if labeled_rows else 0.0),
            "cohen_kappa": cohen_kappa(judge_values, human_values),
            "confusion": _confusion(judge_values, human_values),
            "by_system": {},
        }
        for system in sorted({r["system"] for r in eligible}):
            system_rows = [r for r in eligible if r["system"] == system]
            system_labels = {qa_key(r): human[qa_key(r)] for r in system_rows if qa_key(r) in human}
            validation[field]["by_system"][system] = _ppi_rate(system_rows, system_labels, field)
    data["summary"]["_judge_validation"] = validation
    (RESULTS / "qa.json").write_text(json.dumps(data, ensure_ascii=False, indent=1))
    for field, result in validation.items():
        print(f"{field}: agreement={result['agreement']:.3f}, kappa={result['cohen_kappa']:.3f}, "
              f"confusion={result['confusion']}")
        for system, ppi in result["by_system"].items():
            print(f"  {system}: PPI={ppi['rate']:.3f} CI95=[{ppi['ci95'][0]:.3f}, {ppi['ci95'][1]:.3f}] "
                  f"({ppi['n_labeled']}/{ppi['den']} labeled)")
    return validation


async def evaluate_one(q: dict, system: str, registry, text: str, client, semaphore: asyncio.Semaphore,
                       use_cache: bool) -> dict:
    row = {
        "id": q["id"], "decision": q["decision"], "system": system, "type": q["type"],
        "question": q["question"], "gold_answer": q["gold_answer"], "trap": q.get("trap"),
        "expected_abstain": q["expected_abstain"], "registry_ids": [entry.id for entry in registry.entries],
    }
    started = time.perf_counter()
    try:
        answer_key = hash_key(system, ANSWER_MODEL, q["decision"], q["question"],
                              *( [BASELINE_PROMPT] if system == "baseline" else []))
        cached_answer = read_cache("answer", answer_key) if use_cache else None
        if system == "lawhack" and cached_answer is not None and "lawhack" not in cached_answer:
            cached_answer = None
        if cached_answer is not None:
            answer = cached_answer["answer"]
            if system == "lawhack":
                row["lawhack"] = cached_answer["lawhack"]
        elif system == "lawhack":
            async with semaphore:
                result = await ask(registry, q["question"], client=client, model=ANSWER_MODEL)
            answer = result.render()
            row["lawhack"] = {
                "abstained": result.abstained,
                "sentences": [
                    {
                        "supported": sentence.supported,
                        "pills": [
                            {"segment_id": pill.segment_id, "speaker": pill.speaker, "level": pill.level}
                            for pill in sentence.pills
                        ],
                    }
                    for sentence in result.sentences
                ],
            }
            if use_cache:
                write_cache("answer", answer_key, {"answer": answer, "lawhack": row["lawhack"]})
        else:
            async with semaphore:
                answer = await asyncio.to_thread(chat, [
                    {"role": "system", "content": BASELINE_PROMPT},
                    {"role": "user", "content": f"Arrêt :\n\n{text}\n\nQuestion : {q['question']}"}], ANSWER_MODEL)
            if use_cache:
                write_cache("answer", answer_key, {"answer": answer})
        row["answer"] = answer
        if system == "baseline":
            flags = [c["verdict"] for c in check(registry, answer)]
            row["verifier"] = flags
            row["verifier_flagged"] = any(v in ("MAL_ATTRIBUE", "NON_SOURCE") for v in flags)
        judge_key = hash_key(JUDGE_MODEL, JUDGE_PROMPT, q["id"], q["decision"], answer)
        cached_grade = read_cache("judge", judge_key) if use_cache else None
        if cached_grade is not None:
            row["grade"] = cached_grade
        else:
            async with semaphore:
                row["grade"] = await asyncio.to_thread(judge, q, answer)
            if use_cache:
                write_cache("judge", judge_key, row["grade"])
    except Exception as error:
        row["error"] = repr(error)[:300]
    row["seconds"] = time.perf_counter() - started
    return row


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int)
    parser.add_argument("--systems", default="lawhack,baseline")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--no-cache", action="store_true")
    labels = parser.add_mutually_exclusive_group()
    labels.add_argument("--export-labels", type=int, metavar="N")
    labels.add_argument("--import-labels", action="store_true")
    args = parser.parse_args()
    if args.export_labels is not None:
        export_labels(args.export_labels)
        return
    if args.import_labels:
        import_labels()
        return
    if args.concurrency < 1:
        parser.error("--concurrency must be at least 1")
    systems = [system.strip() for system in args.systems.split(",") if system.strip()]
    questions = [json.loads(line) for line in QUESTIONS.read_text().splitlines() if line.strip()][: args.limit]
    client = Throttled(TypeSafeSystemOne())
    model = str(client.model)
    registries: dict[str, tuple[object, str]] = {}
    for decision in dict.fromkeys(q["decision"] for q in questions):
        key = hash_key(decision, model)
        registry = None
        cached = read_cache("registry", key) if not args.no_cache else None
        if cached is not None:
            try:
                from lawhack.schema import Registry
                registry = Registry.model_validate(cached)
            except Exception:
                registry = None
        text = decision_text(decision)
        if registry is None:
            registry = (await analyse_async(load_text(text), client, use_cache=False))[0]
            if not args.no_cache:
                write_cache("registry", key, json.loads(registry.model_dump_json()))
        registries[decision] = (registry, text)

    semaphore = asyncio.Semaphore(args.concurrency)
    completed = 0

    async def process_question(index: int, q: dict) -> list[dict]:
        nonlocal completed
        registry, text = registries[q["decision"]]
        result = await asyncio.gather(
            *(evaluate_one(q, system, registry, text, client, semaphore, not args.no_cache) for system in systems))
        completed += 1
        grades = " ".join(f"{r['system']}:{'ERR' if 'error' in r else ('✗' if r['grade']['attribution_error'] else '✓')}"
                          for r in result)
        print(f"[{completed}/{len(questions)}] {q['id']} {q['type']:<11} {grades}", file=sys.stderr)
        return result

    question_results = await asyncio.gather(*(process_question(i, q) for i, q in enumerate(questions, 1)))
    rows = [row for group in question_results for row in group]
    summary = {system: summarise(rows, system) for system in systems}
    if "lawhack" in systems and "baseline" in systems:
        summary["_paired"] = paired_summary(rows)
    summary["_config"] = {
        "answer_model": ANSWER_MODEL, "judge_model": JUDGE_MODEL, "system_one": model,
        "questions": len(questions), "decisions": len(registries),
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "qa.json").write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1))
    for system in systems:
        metrics = summary[system]
        print(f"{system:<9} hallucination d'attribution {metrics['attribution_hallucination']['rate']:.0%} "
              f"({metrics['attribution_hallucination']['num']}/{metrics['attribution_hallucination']['den']}) · "
              f"correct {metrics['correct']['rate']:.0%} · abstention juste {metrics['correct_abstention']['rate']:.0%} · "
              f"abstention à tort {metrics['false_abstention']['rate']:.0%} · invention {metrics['invented']['rate']:.0%} · "
              f"{metrics['seconds_mean']:.1f}s")
    if "baseline" in summary:
        print(f"vérificateur LawHack sur la baseline : "
              f"{summary['baseline']['verifier_flags_baseline_errors']['rate']:.0%} des hallucinations signalées, "
              f"{summary['baseline']['verifier_false_alarms']['rate']:.0%} de fausses alertes")
    if "_paired" in summary:
        for metric, result in summary["_paired"].items():
            print(f"paired {metric}: diff={result['diff']:+.3f} "
                  f"CI95=[{result['ci95'][0]:+.3f}, {result['ci95'][1]:+.3f}] p={result['p']:.5f} "
                  f"(b={result['b']}, c={result['c']})")


if __name__ == "__main__":
    asyncio.run(main())
