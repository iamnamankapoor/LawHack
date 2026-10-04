"""Large-scale, label-free evaluation against Judilibre `zones` (held-out sample, see fetch_judilibre_sample.py).

    python scripts/eval_zones.py [--split test] [--limit N] [--client heuristic|jev]

Measures, per sentence (gold zone = Judilibre zone covering most of the sentence):
- zone accuracy of our rule-based zoning (confusion matrix);
- critical attribution errors of the registry, the hallucination LawHack exists to prevent:
  * « moyen → Cour » : a sentence of the parties' grounds of appeal attributed to the Cour de cassation
    or given the DECIDE status (an argument presented as the Cour's decision);
  * « dispositif perdu » : a sentence of the operative ruling not attributed to the Cour;
- latency, Jev calls and input tokens per decision.
95 % confidence intervals: bootstrap over decisions. Results → eval/results/zones_<client>_<split>.json
"""

import argparse
import asyncio
import gzip
import json
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

from lawhack.attributor import build_registry  # noqa: E402
from lawhack.heuristic import HeuristicSystemOne  # noqa: E402
from lawhack.ingest import load_text  # noqa: E402
from lawhack.schema import Speaker, Status  # noqa: E402
from lawhack.segmenter import segment  # noqa: E402
from lawhack.system_one import TypeSafeSystemOne  # noqa: E402
from lawhack.zoning import zone_blocks  # noqa: E402

SAMPLE = ROOT / "eval" / "data" / "judilibre_sample.jsonl.gz"
RESULTS = ROOT / "eval" / "results"
GOLD_ALIASES = {"annexes": "moyens"}  # « Moyen(s) annexé(s) » = the parties' full grounds of appeal


def load_sample(split: str | None = None) -> list[dict]:
    with gzip.open(SAMPLE, "rt", encoding="utf-8") as f:
        rows = [json.loads(line) for line in f]
    return [r for r in rows if split in (None, "all", r["split"])]


def gold_zone(zones: dict[str, list[dict]], start: int, end: int) -> str | None:
    best, overlap = None, 0
    for name, spans in zones.items():
        covered = sum(max(0, min(end, z["end"]) - max(start, z["start"])) for z in spans)
        if covered > overlap:
            best, overlap = name, covered
    if best is None or overlap < (end - start) / 2:
        return None
    return GOLD_ALIASES.get(best, best)


def bootstrap(per_doc: list[tuple[int, int]], iterations: int = 2000, seed: int = 0) -> tuple[float, float]:
    """95 % CI of sum(num)/sum(den), resampling decisions."""
    if not per_doc:
        return (0.0, 0.0)
    rng = random.Random(seed)
    stats = []
    for _ in range(iterations):
        draw = [per_doc[rng.randrange(len(per_doc))] for _ in per_doc]
        den = sum(d for _, d in draw)
        stats.append(sum(n for n, _ in draw) / den if den else 0.0)
    stats.sort()
    return (stats[int(0.025 * iterations)], stats[int(0.975 * iterations)])


def rate(per_doc: list[tuple[int, int]]) -> dict:
    num, den = sum(n for n, _ in per_doc), sum(d for _, d in per_doc)
    low, high = bootstrap(per_doc)
    return {"num": num, "den": den, "rate": num / den if den else 0.0, "ci95": [low, high]}


class Throttled:
    """Shared rate limit + retry on 429, so no decision is dropped. The Codiv key allows 60 requests/min and is
    shared with the live demo: stay well below (EVAL_JEV_RPM, default 25)."""

    def __init__(self, inner, per_minute: int | None = None):
        per_minute = per_minute or int(os.environ.get("EVAL_JEV_RPM", "25"))
        self.inner, self.model, self.interval, self.next_slot = inner, getattr(inner, "model", None), 60 / per_minute, 0.0
        self.lock = asyncio.Lock()

    async def decide(self, state, questions):
        for attempt in range(8):
            async with self.lock:
                now = time.monotonic()
                wait, self.next_slot = max(0.0, self.next_slot - now), max(now, self.next_slot) + self.interval
            await asyncio.sleep(wait)
            try:
                return await self.inner.decide(state, questions)
            except Exception as error:
                if "429" not in str(error) or attempt == 7:
                    raise
                await asyncio.sleep(5 * (attempt + 1))


class Counting:
    def __init__(self, inner):
        self.inner, self.calls = inner, 0

    async def decide(self, state, questions):
        self.calls += 1
        return await self.inner.decide(state, questions)


async def evaluate_one(row: dict, client) -> dict:
    doc = load_text(row["text"], doc_id=row["id"])
    segments = segment(zone_blocks(doc))
    counting = Counting(client)
    started = time.perf_counter()
    registry = await build_registry(doc.id, segments, counting)
    seconds = time.perf_counter() - started
    out = {"id": row["id"], "chamber": row["chamber"], "solution": row["solution"], "sentences": 0,
           "zone_ok": 0, "confusion": Counter(), "moyens": 0, "moyen_as_cour": 0, "dispositif": 0,
           "dispositif_lost": 0, "calls": counting.calls, "tokens": registry.input_tokens, "seconds": seconds,
           "examples": [], "calibration": []}
    for e in registry.entries:
        gold = gold_zone(row["zones"], e.start, e.end)
        if gold is None or gold == "introduction":
            continue
        out["sentences"] += 1
        out["zone_ok"] += e.zone.value == gold
        out["confusion"][f"{gold}→{e.zone.value}"] += 1
        if gold == "moyens":
            out["moyens"] += 1
            wrong = e.speaker.value == Speaker.COUR_CASSATION.value or e.status.value == Status.DECIDE.value
            out["moyen_as_cour"] += wrong
            if e.source.startswith("jev"):
                out["calibration"].append([round(e.speaker.confidence, 3), int(not wrong)])
            if wrong and len(out["examples"]) < 3:
                out["examples"].append({"kind": "moyen→Cour", "text": e.text[:200], "speaker": e.speaker.value,
                                        "status": e.status.value, "zone": e.zone.value})
        elif gold == "dispositif":
            out["dispositif"] += 1
            lost = e.speaker.value != Speaker.COUR_CASSATION.value
            out["dispositif_lost"] += lost
            if e.source.startswith("jev"):
                out["calibration"].append([round(e.speaker.confidence, 3), int(not lost)])
            if lost and len(out["examples"]) < 3:
                out["examples"].append({"kind": "dispositif perdu", "text": e.text[:200], "speaker": e.speaker.value})
    return out


async def run(rows: list[dict], client, concurrency: int) -> list[dict]:
    semaphore = asyncio.Semaphore(concurrency)
    done = 0

    async def guarded(row):
        nonlocal done
        async with semaphore:
            try:
                result = await evaluate_one(row, client)
            except Exception as error:  # one failing decision must not sink the benchmark
                result = {"id": row["id"], "error": repr(error)[:300]}
        done += 1
        if done % 10 == 0:
            print(f"  {done}/{len(rows)}", file=sys.stderr)
        return result

    return await asyncio.gather(*(guarded(r) for r in rows))


def summarise(results: list[dict], model: str) -> dict:
    ok = [r for r in results if "error" not in r]
    confusion = Counter()
    for r in ok:
        confusion.update(r["confusion"])
    seconds = sorted(r["seconds"] for r in ok)
    return {
        "model": model,
        "decisions": len(results),
        "errors": len(results) - len(ok),
        "sentences": sum(r["sentences"] for r in ok),
        "zone_accuracy": rate([(r["zone_ok"], r["sentences"]) for r in ok]),
        "moyen_as_cour": rate([(r["moyen_as_cour"], r["moyens"]) for r in ok]),
        "dispositif_lost": rate([(r["dispositif_lost"], r["dispositif"]) for r in ok]),
        "decisions_with_critical_error": rate([(int(r["moyen_as_cour"] + r["dispositif_lost"] > 0), 1) for r in ok]),
        "calls_per_decision": sum(r["calls"] for r in ok) / max(len(ok), 1),
        "tokens_per_decision": sum(r["tokens"] for r in ok) / max(len(ok), 1),
        "seconds_p50": seconds[len(seconds) // 2] if seconds else 0.0,
        "seconds_p90": seconds[int(len(seconds) * 0.9)] if seconds else 0.0,
        "calibration": calibration([c for r in ok for c in r["calibration"]]),
        "confusion": dict(confusion.most_common()),
        "examples": [dict(ex, id=r["id"]) for r in ok for ex in r["examples"]][:15],
        "failures": [r for r in results if "error" in r][:5],
    }


def calibration(points: list[list[float]], bins: int = 5) -> dict:
    """Reliability of System 1 confidence on Jev-decided sentences (correct = no critical error)."""
    table, ece = [], 0.0
    for b in range(bins):
        low, high = 0.5 + b * 0.5 / bins, 0.5 + (b + 1) * 0.5 / bins
        inside = [p for p in points if low <= p[0] < high or (b == bins - 1 and p[0] >= high)]
        if inside:
            conf = sum(p[0] for p in inside) / len(inside)
            acc = sum(p[1] for p in inside) / len(inside)
            ece += abs(acc - conf) * len(inside) / len(points)
            table.append({"bin": f"{low:.1f}-{high:.1f}", "n": len(inside), "confidence": round(conf, 3),
                          "accuracy": round(acc, 3)})
    return {"n": len(points), "ece": round(ece, 4), "bins": table,
            "below_0.5": sum(p[0] < 0.5 for p in points)}


def pct(m: dict) -> str:
    return f"{m['rate']:.1%} [{m['ci95'][0]:.1%}–{m['ci95'][1]:.1%}] ({m['num']}/{m['den']})"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", default="test", choices=["dev", "test", "all"])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--client", default="heuristic", choices=["heuristic", "jev"])
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args()
    rows = load_sample(args.split)[: args.limit]

    async def go():
        client = HeuristicSystemOne() if args.client == "heuristic" else Throttled(TypeSafeSystemOne())
        return await run(rows, client, args.concurrency), getattr(client, "model", args.client)

    results, model = asyncio.run(go())
    summary = summarise(results, model)
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / f"zones_{args.client}_{args.split}.json"
    out.write_text(json.dumps({"summary": summary, "per_decision": results}, ensure_ascii=False, indent=1, default=dict))
    print(f"{model} · {args.split} · {summary['decisions']} arrêts · {summary['sentences']} phrases · erreurs={summary['errors']}")
    print(f"  zonage exact               {pct(summary['zone_accuracy'])}")
    print(f"  moyen attribué à la Cour   {pct(summary['moyen_as_cour'])}")
    print(f"  dispositif hors Cour       {pct(summary['dispositif_lost'])}")
    print(f"  arrêts avec erreur critique {pct(summary['decisions_with_critical_error'])}")
    print(f"  {summary['calls_per_decision']:.1f} appels · {summary['tokens_per_decision']:.0f} tokens · "
          f"p50 {summary['seconds_p50']:.1f}s · p90 {summary['seconds_p90']:.1f}s par arrêt")
    cal = summary["calibration"]
    if cal["n"]:
        print(f"  calibration Jev n={cal['n']} ECE={cal['ece']:.3f}",
              [(c["bin"], c["n"], c["accuracy"]) for c in cal["bins"]])
    print("  confusions:", {k: v for k, v in summary["confusion"].items() if k.split("→")[0] != k.split("→")[1]})
    print(f"→ {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
