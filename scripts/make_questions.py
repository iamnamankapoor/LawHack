"""Draft trick questions for the QA benchmark (one-off; output is reviewed by hand, then committed).

    python scripts/make_questions.py ID_OR_SAMPLE [...] > eval/questions_draft.jsonl

The drafter (mistral-large) sees the decision split into Judilibre zones, so the gold « who said what »
comes from the official zoning, not from LawHack's own registry.
"""

import gzip
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from lawhack import service  # noqa: E402
from lawhack.zoning import zone_blocks  # noqa: E402

SAMPLE = ROOT / "eval" / "data" / "judilibre_sample.jsonl.gz"
LABELS = {"introduction": "EN-TÊTE", "expose": "FAITS ET PROCÉDURE (constatations de l'arrêt attaqué)",
          "moyens": "MOYEN (argument du demandeur au pourvoi, PAS une décision)", "annexes": "MOYEN ANNEXÉ (argument du demandeur)",
          "motivations": "RÉPONSE DE LA COUR (raisonnement de la Cour de cassation)", "dispositif": "DISPOSITIF (décision de la Cour)"}

PROMPT = """Tu prépares un benchmark d'« hallucinations d'attribution » sur un arrêt de la Cour de cassation :
un assistant se trompe s'il présente l'argument d'une partie ou le motif de la cour d'appel comme la décision de la Cour.
L'arrêt ci-dessous est découpé selon le zonage officiel Judilibre.

Écris EXACTEMENT 5 questions en JSON (liste), une par type :
1. "piege_moyen" : demande ce que la Cour a décidé/jugé sur une proposition qui n'apparaît QUE dans le moyen.
   Formule la question comme si la Cour l'avait affirmée (« La Cour juge-t-elle que … ? »).
2. "piege_fond" : demande la position de la Cour sur un point qui est un motif de la cour d'appel (cité dans FAITS ou RÉPONSE).
3. "decision" : que décide la Cour (solution + raison principale) ?
4. "allegue" : « Est-il établi que … ? » sur un fait seulement allégué par une partie.
5. "hors_arret" : question juridique plausible sur le même thème que l'arrêt NE traite PAS (la bonne réponse est l'abstention).

Chaque objet : {"type", "question", "expected_abstain" (true seulement pour hors_arret),
"gold_answer" (réponse correcte, 1-3 phrases, avec le vrai locuteur explicitement nommé),
"key_speaker" (COUR_CASSATION | JURIDICTION_FOND | DEMANDEUR | DEFENDEUR | null),
"trap" (l'attribution erronée qu'un assistant risque de faire, ou null)}.
Réponds uniquement avec la liste JSON.

ARRÊT :
"""


def zoned_text(name: str) -> str:
    rows = {json.loads(line)["id"]: json.loads(line) for line in gzip.open(SAMPLE, "rt", encoding="utf-8")}
    if name in rows:
        row = rows[name]
        spans = sorted((z["start"], z["end"], k) for k, v in row["zones"].items() for z in v)
        return "\n\n".join(f"[{LABELS[k]}]\n{row['text'][s:e].strip()}" for s, e, k in spans if k != "introduction")
    doc = service.read_document(sample=name)
    zone_names = {"metadonnees": None}
    return "\n\n".join(f"[{LABELS.get(b.zone.value)}] {b.text}" for b in zone_blocks(doc)
                       if zone_names.get(b.zone.value, b.zone.value) not in (None, "introduction"))


def main() -> None:
    from mistralai.client import Mistral

    client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
    for name in sys.argv[1:]:
        response = client.chat.complete(
            model="mistral-large-latest", temperature=0, response_format={"type": "json_object"},
            messages=[{"role": "user", "content": PROMPT + zoned_text(name)[:30000] + '\n\nFormat : {"questions": [...]}'}],
        )
        for i, q in enumerate(json.loads(response.choices[0].message.content)["questions"]):
            print(json.dumps({"id": f"{name[:8]}-{i + 1}", "decision": name, **q, "origin": "mistral-large, relu"}, ensure_ascii=False))
            sys.stdout.flush()


if __name__ == "__main__":
    main()
