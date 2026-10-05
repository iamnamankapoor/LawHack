"""Second-pass review of drafted questions against the Judilibre-zoned text (mistral-large as legal reviewer).

    python scripts/review_questions.py DRAFT [DONE] >> REVIEW   # DONE: already-reviewed file, skipped (resume)

Only questions with valid=true are kept in the benchmark; invalid ones are dropped, never silently fixed.
"""

import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
load_dotenv(ROOT / ".env")

from make_questions import zoned_text  # noqa: E402

PROMPT = """Tu es juriste relecteur. Voici un arrêt (zonage officiel Judilibre) et une question de benchmark avec sa réponse de référence.
Vérifie STRICTEMENT contre le texte : (a) la référence est-elle exacte (qui dit quoi, ce que la Cour décide, approuve ou censure) ?
(b) pour "allegue" : le fait est-il bien seulement allégué (pas constaté par la cour d'appel) ? (c) pour "hors_arret" : l'arrêt ne traite-t-il vraiment pas la question ?
(d) pour "piege_moyen" : la proposition n'apparaît-elle QUE dans le moyen (si la Cour la reprend elle-même, c'est invalide) ?
Réponds en JSON {"valid": bool, "problem": "…ou null", "fixed_gold_answer": "référence corrigée ou null", "fixed_key_speaker": "… ou null"}"""


def review(client, q: dict, text: str) -> dict:
    from mistralai.client.errors import SDKError

    fields = {k: q.get(k) for k in ("type", "question", "gold_answer", "key_speaker", "trap")}
    messages = [{"role": "user", "content": f"{PROMPT}\n\nARRÊT :\n{text}\n\nQUESTION : {json.dumps(fields, ensure_ascii=False)}"}]
    for attempt in range(12):
        try:
            response = client.chat.complete(model="mistral-large-latest", temperature=0, messages=messages,
                                            response_format={"type": "json_object"})
            return {"id": q["id"], "decision": q["decision"], **json.loads(response.choices[0].message.content)}
        except SDKError:
            if attempt == 11:
                raise
            time.sleep(min(60, 5 * 2 ** attempt))


def main() -> None:
    from concurrent.futures import ThreadPoolExecutor

    from mistralai.client import Mistral

    client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
    done = set()
    if len(sys.argv) > 2 and os.path.exists(sys.argv[2]):
        done = {(v["id"], v["decision"]) for v in map(json.loads, open(sys.argv[2])) if v}
    questions = [q for q in map(json.loads, filter(str.strip, open(sys.argv[1]))) if (q["id"], q["decision"]) not in done]
    texts = {d: zoned_text(d)[:30000] for d in dict.fromkeys(q["decision"] for q in questions)}
    with ThreadPoolExecutor(int(os.environ.get("REVIEW_CONCURRENCY", "2"))) as pool:
        for verdict in pool.map(lambda q: review(client, q, texts[q["decision"]]), questions):
            print(json.dumps(verdict, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
