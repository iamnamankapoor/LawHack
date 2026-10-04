"""Zoning agreement with Judilibre's reference zones on bench/decisions (character-weighted)."""

import glob
import json
from collections import Counter

from lawhack.ingest import load_text
from lawhack.zoning import zone_blocks


def main() -> None:
    ok = total = 0
    confusion: Counter = Counter()
    for path in sorted(glob.glob("bench/decisions/*.json")):
        decision = json.load(open(path))
        spans = [(z, s["start"], s["end"]) for z, ss in decision["zones"].items() if ss for s in ss]
        for block in zone_blocks(load_text(decision["text"])):
            mid = (block.start + block.end) // 2
            ref = [z for z, s, e in spans if s <= mid < e]
            if not ref:
                continue
            n = len(block.text)
            total += n
            ok += n * (block.zone.value == ref[0])
            if block.zone.value != ref[0]:
                confusion[(ref[0], block.zone.value)] += n
    print(f"zonage vs Judilibre : {ok / total:.1%} des caractères")
    for (ref, got), n in confusion.most_common(8):
        print(f"  {ref} → {got} : {n} car.")


if __name__ == "__main__":
    main()
