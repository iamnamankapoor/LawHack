"""Write attribution-trap questions for the unseen decisions, independently of the pipeline.

Opus 5.5 reads only the raw decision text (never our annotations) and returns questions + gold answers.
Usage: python3 eval/make_unseen.py -> cases/unseen/questions.json
"""
import glob, json, os, re, sys
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from engine.gateway import chat  # noqa: E402

AUTHOR = "anthropic/claude-opus-5.5"
INSTRUCTIONS = """Tu es un juriste français expert de la Cour de cassation. On construit un test pour vérifier si un modèle confond la position de la Cour de cassation avec celle de la cour d'appel (arrêt attaqué), d'une partie (moyen), ou d'une jurisprudence antérieure abandonnée.

À partir de la décision ci-dessous, écris :
- exactement 2 questions « pièges » de la forme « Selon la Cour de cassation, … ? » qui prêtent à la Cour une proposition qui, dans le texte, émane en réalité de la cour d'appel, d'une partie, ou d'une jurisprudence que la Cour abandonne — ou sur laquelle la Cour ne se prononce pas. Choisis les pièges les plus trompeurs (propositions formulées comme des règles générales).
- 1 question « extrait » SI la décision contient un ou plusieurs paragraphes numérotés consécutifs rapportant le raisonnement de la cour d'appel (« l'arrêt retient », « Il relève »…) : indique ces numéros et la question « Quelle règle la Cour de cassation pose-t-elle sur [sujet] ? ». Sinon, omets-la.

Pour chaque question, donne la réponse correcte (« gold ») et l'erreur attendue (« fail_if »). Sois exact : si la Cour ne s'est pas prononcée, dis-le ; si elle a écarté l'argument, dis-le.

Réponds UNIQUEMENT en JSON : {"questions": [{"type": "trap"|"chunk", "prompt_fr": "...", "paragraphs": [n, m] (seulement pour chunk), "gold": "...", "fail_if": "..."}]}"""


def make(path):
    text = open(path, encoding="utf-8").read()
    out = chat(AUTHOR, INSTRUCTIONS, text)
    data = json.loads(re.search(r"\{.*\}", out, re.S).group(0))
    case = os.path.basename(path).split("_")[0]
    for i, q in enumerate(data["questions"], 1):
        q.update(id=f"{case}-{'CHUNK' if q['type'] == 'chunk' else 'Q' + str(i)}", case=case, file=os.path.relpath(path, ROOT))
    return data["questions"]


if __name__ == "__main__":
    files = sorted(glob.glob(os.path.join(ROOT, "cases", "raw", "U*.txt")))
    with ThreadPoolExecutor(5) as ex:
        qs = [q for batch in ex.map(make, files) for q in batch]
    out = os.path.join(ROOT, "cases", "unseen", "questions.json")
    json.dump({"author": AUTHOR, "questions": qs}, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for q in qs:
        print(q["id"], "|", q["prompt_fr"][:140])
