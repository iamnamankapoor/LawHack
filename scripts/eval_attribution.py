"""Speaker and chain accuracy, cost and latency on the hand-labelled samples (eval/gold_speakers.json).

    python scripts/eval_attribution.py            # Jev if TYPESAFE_API_KEY is set, else heuristic
"""

import asyncio
import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from lawhack import service  # noqa: E402
from lawhack.attributor import build_registry  # noqa: E402
from lawhack.pipeline import default_client  # noqa: E402
from lawhack.segmenter import segment  # noqa: E402
from lawhack.zoning import zone_blocks  # noqa: E402

GOLD = json.loads((Path(__file__).resolve().parent.parent / "eval" / "gold_speakers.json").read_text())


class Counting:
    def __init__(self, inner):
        self.inner, self.calls, self.model = inner, 0, getattr(inner, "model", None)

    async def decide(self, state, questions):
        self.calls += 1
        return await self.inner.decide(state, questions)


async def main() -> None:
    total = correct = 0
    for name, gold in GOLD.items():
        if name.startswith("_"):
            continue
        doc = service.read_document(sample=name)
        client = Counting(default_client())
        started = time.perf_counter()
        registry = await build_registry(doc.id, segment(zone_blocks(doc)), client)
        seconds = time.perf_counter() - started
        by_id = {e.text[:60]: e for e in registry.entries}
        errors = [f"{sid}: {by_id[sid].speaker.value} ({by_id[sid].speaker.confidence:.2f}) ≠ {ok}"
                  for sid, ok in gold.items() if by_id[sid].speaker.value not in ok]
        for sid, chain in GOLD["_chains"].get(name, {}).items():
            if [s.value for s in by_id[sid].chain] != chain:
                errors.append(f"{sid}: chain {[s.value for s in by_id[sid].chain]} ≠ {chain}")
        total += len(gold) + len(GOLD["_chains"].get(name, {}))
        correct += len(gold) + len(GOLD["_chains"].get(name, {})) - len(errors)
        print(f"{name}: {registry.model} calls={client.calls} input_tokens={registry.input_tokens} {seconds:.1f}s errors={len(errors)}")
        for e in errors:
            print("   ", e)
    print(f"accuracy {correct}/{total} = {correct / total:.0%}")


if __name__ == "__main__":
    asyncio.run(main())
