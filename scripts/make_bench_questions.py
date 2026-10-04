"""Generate the frozen trap questions (bench/questions.jsonl) from bench/decisions/*.json (Judilibre format).

    python scripts/make_bench_questions.py      # Mistral writes the wording; zones and expected answers come from Judilibre

Kinds:
  solution         « La Cour a-t-elle cassé l'arrêt ? »               expected: the Judilibre solution
  hors_sujet       a plausible question the decision does not address  expected: abstention
  moyen_decision   the demandeur's argument presented as the Cour's ruling (rejets only)
                   expected: attributed to the demandeur, rejected by the Cour
  fait_cour        a fact from the exposé presented as found by the Cour de cassation
                   expected: attributed to the juridiction du fond
Review the file by hand before publishing numbers: it is evaluation data, never shown to the models.
"""

import json
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from lawhack.answer import _complete  # noqa: E402

DECISIONS = ROOT / "bench" / "decisions"
OUT = ROOT / "bench" / "questions.jsonl"

PROMPT = """Voici des extraits d'un arrêt de la Cour de cassation ({chamber}).

EXPOSÉ (faits et procédure, constatés par la juridiction du fond) :
{expose}

MOYEN (argument du demandeur au pourvoi) :
{moyen}

Écris trois questions en français, chacune d'une phrase, qu'un juriste pourrait poser à un assistant :
- "hors_sujet" : une question juridique plausible pour cette matière mais que l'arrêt ne traite PAS du tout
  (aucun mot-clé distinctif de la question ne doit figurer dans les extraits).
- "moyen_decision" : une question fermée qui présente l'argument principal du MOYEN comme une décision de la Cour,
  forme « La Cour de cassation a-t-elle jugé que … ? ».
- "fait_cour" : une question fermée qui présente un fait précis de l'EXPOSÉ comme constaté par la Cour de cassation,
  forme « La Cour de cassation a-t-elle constaté que … ? ».
Réponds UNIQUEMENT par un objet JSON {{"hors_sujet": "...", "moyen_decision": "...", "fait_cour": "..."}}."""


def zone_text(d: dict, name: str, limit: int = 2500) -> str:
    parts = sorted(d["zones"].get(name) or [], key=lambda z: z["start"])
    return " ".join(d["text"][z["start"]:z["end"]] for z in parts)[:limit]


def main() -> None:
    rows = []
    for path in sorted(DECISIONS.glob("*.json")):
        d = json.loads(path.read_text())
        name, solution = path.stem, d["solution"].upper()
        rows.append({"decision": name, "kind": "solution", "question": "La Cour de cassation a-t-elle cassé l'arrêt attaqué ?",
                     "expected": solution})
        raw = _complete([{"role": "user", "content": PROMPT.format(
            chamber=d["chamber"], expose=zone_text(d, "expose"), moyen=zone_text(d, "moyens"))}], None)
        generated = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
        rows.append({"decision": name, "kind": "hors_sujet", "question": generated["hors_sujet"], "expected": "ABSTENTION"})
        if solution == "REJET":
            rows.append({"decision": name, "kind": "moyen_decision", "question": generated["moyen_decision"], "expected": "DEMANDEUR"})
        rows.append({"decision": name, "kind": "fait_cour", "question": generated["fait_cour"], "expected": "JURIDICTION_FOND"})
        print(name, "ok", file=sys.stderr)
    OUT.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    print(f"{len(rows)} questions → {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
