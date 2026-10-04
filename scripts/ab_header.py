"""A/B of HEADER_CONTEXT (off | lex | jev | always): simple caption questions + the trap bench, LawHack only.

    HEADER_CONTEXT=lex python scripts/ab_header.py   → bench/ab_header_<mode>.json + summary on stdout
"""

import asyncio
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")
os.environ.setdefault("ANSWER_CACHE", "0")

from lawhack.answer import ask, header_entries  # noqa: E402
from lawhack.ingest import load_text  # noqa: E402
from lawhack.pipeline import analyse_async, default_client, load  # noqa: E402
from scripts.bench import DECISIONS, QUESTIONS, grade  # noqa: E402

MONTHS = "janvier février mars avril mai juin juillet août septembre octobre novembre décembre".split()
ORDINALS = {"Première": ["premiere", "1re", "1ere"], "Deuxième": ["deuxieme", "2e", "2eme"], "Troisième": ["troisieme", "3e", "3eme"]}


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return " ".join("".join(c for c in text if not unicodedata.combining(c)).split())


def caption_questions(name: str, chamber: str | None, date: str | None, number: str | None, header: str) -> list[dict]:
    qs = []
    if chamber:
        first = chamber.split()[0]
        alts = ORDINALS.get(first) or [norm(first if first != "Chambre" else chamber.split()[1])]
        qs.append({"question": "Qui est l'auteur de cet arrêt ?", "any": alts})
    president = re.search(r"(?:M\.|Mme)\s+([A-ZÀ-Ÿ][\wÀ-ÿ'\-]+)[^\n]{0,80}?président", header) or re.search(
        r"Président\s*:?\s*(?:M\.|Mme)\s+([\wÀ-ÿ'\-]+)", header)
    if president:
        qs.append({"question": "Qui préside la formation qui a rendu l'arrêt ?", "any": [norm(president.group(1))]})
    rapporteur = re.search(r"Sur le rapport de (?:M\.|Mme)\s+([\wÀ-ÿ'\-]+)", header)
    if rapporteur:
        qs.append({"question": "Qui est le conseiller rapporteur ?", "any": [norm(rapporteur.group(1))]})
    if date:
        y, m, d = date.split("-")
        qs.append({"question": "De quand date cet arrêt ?", "any": [norm(f"{int(d)} {MONTHS[int(m) - 1]} {y}"), f"{d}/{m}/{y}",
                                                                      norm(f"{int(d)}er {MONTHS[int(m) - 1]} {y}")]})
    if number:
        qs.append({"question": "Quel est le numéro de pourvoi ?", "any": [number]})
    return [{**q, "decision": name, "kind": "entete"} for q in qs]


async def main() -> None:
    mode = os.environ.get("HEADER_CONTEXT", "lex")
    client = default_client()
    traps = [json.loads(line) for line in QUESTIONS.read_text().splitlines() if line.strip()]
    docs = [("sample_pdf", load(ROOT / "data/samples/cass_civ3_2022-12-14_21-24539.pdf"),
             {"chamber": "Troisième chambre civile", "decision_date": "2022-12-14", "number": "21-24.539"})]
    for f in sorted(DECISIONS.glob("*.json")):
        data = json.loads(f.read_text())
        docs.append((f.stem, load_text(data["text"]), data))
    rows = []
    for name, doc, meta in docs:
        registry, solution = await analyse_async(doc, client)
        header = "\n".join(e.text for e in header_entries(registry))
        qs = caption_questions(name, meta["chamber"], meta["decision_date"], meta["number"], header)
        qs += [q for q in traps if q["decision"] == name]
        for q in qs:
            try:
                answer = (await ask(registry, q["question"], client, solution=solution)).render()
            except Exception as error:
                rows.append({**q, "error": str(error)})
                continue
            if q["kind"] == "entete":
                prose = norm(answer)
                ok = "ne traite pas" not in prose and any(norm(a) in prose for a in q["any"])
                rows.append({**q, "answer": answer, "correct": ok})
            else:
                rows.append({**q, **grade(q, answer, registry, solution)})
            await asyncio.sleep(0.5)
        print(name, "done", file=sys.stderr, flush=True)
    (ROOT / "bench" / f"ab_header_{mode}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    by: dict[str, list] = {}
    for r in rows:
        by.setdefault(r["kind"], []).append(r)
    print(mode, {k: f"{sum(r.get('correct', False) for r in v)}/{len(v)}" for k, v in by.items()},
          "erreurs", sum("error" in r for r in rows))


if __name__ == "__main__":
    asyncio.run(main())
