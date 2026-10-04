"""Held-out sample of Cour de cassation decisions with Judilibre `zones` (section-level ground truth).

    python scripts/fetch_judilibre_sample.py [cour_de_cassation_XXXX.parquet] [--n 300]

Source: Hugging Face `antoinejeannot/jurisprudence` (Etalab 2.0), parquet shard 0001 (2014-2025).
Stratified by chamber, decisions from 2020 on, never used during development.
Each decision gets a fixed split (dev / test) from a hash of its id: thresholds are tuned on dev only.
"""

import argparse
import gzip
import hashlib
import json
import random
import urllib.request
from pathlib import Path

import pyarrow.compute as pc
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent.parent
URL = "https://huggingface.co/datasets/antoinejeannot/jurisprudence/resolve/refs%2Fconvert%2Fparquet/cour_de_cassation/train/0001.parquet"
OUT = ROOT / "eval" / "data" / "judilibre_sample.jsonl.gz"
COLUMNS = ["id", "decision_date", "chamber", "solution", "type", "number", "ecli", "zones", "text"]


def split_of(decision_id: str) -> str:
    return "test" if int(hashlib.sha256(decision_id.encode()).hexdigest(), 16) % 2 else "dev"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("parquet", nargs="?", default=str(ROOT / "data" / "hf" / "cass_0001.parquet"))
    parser.add_argument("--n", type=int, default=300)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    path = Path(args.parquet)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        print(f"downloading {URL} → {path} (~760 MB)")
        urllib.request.urlretrieve(URL, path)

    table = pq.read_table(path, columns=COLUMNS)
    keep = pc.and_(pc.greater_equal(table["decision_date"], "2020-01-01"), pc.is_valid(table["zones"]))
    keep = pc.and_(keep, pc.invert(pc.match_substring(table["chamber"], "présidence")))
    keep = pc.and_(keep, pc.greater(pc.utf8_length(table["text"]), 1500))
    rows = table.filter(keep).to_pylist()
    rows = [r for r in rows if r["zones"].get("moyens") and r["zones"].get("motivations") and r["zones"].get("dispositif")]

    rng = random.Random(args.seed)
    by_chamber: dict[str, list[dict]] = {}
    for r in rows:
        by_chamber.setdefault(r["chamber"], []).append(r)
    picked: list[dict] = []
    per = -(-args.n // len(by_chamber))
    for chamber in sorted(by_chamber):
        picked += rng.sample(by_chamber[chamber], min(per, len(by_chamber[chamber])))
    picked = sorted(picked, key=lambda r: r["id"])[: args.n]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUT, "wt", encoding="utf-8") as f:
        for r in picked:
            zones = {k: sorted(v, key=lambda z: z["start"]) for k, v in r["zones"].items() if v}
            f.write(json.dumps({**r, "zones": zones, "split": split_of(r["id"])}, ensure_ascii=False) + "\n")
    print(f"{len(picked)} decisions ({sum(split_of(r['id']) == 'test' for r in picked)} test) → {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
