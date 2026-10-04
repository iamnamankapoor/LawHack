"""Juge externe : chaque phrase des réponses de bench/results.json est jugée par un panel Mistral
qui lit l'arrêt intégral, puis les verdicts sont confrontés au jeu annoté à la main (bench/gold.json).

    python scripts/judge.py run   [--results bench/results.json] [--out bench/judge_results.json]
    python scripts/judge.py score [--judged bench/judge_results.json] [--gold bench/gold.json]

`score` : une phrase annotée prend le label humain ; une phrase non annotée prend le verdict du panel
(les phrases non annotées sont celles où le panel est unanime). Les appels en échec (429…) sont signalés,
jamais comptés comme erreurs de réponse.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lawhack.segmenter import split_sentences  # noqa: E402

PANEL = ["mistral-medium-latest", "magistral-medium-latest", "mistral-large-latest"]
ERRORS = ("MAL_ATTRIBUE", "FAUX")

JUDGE_PROMPT = """Tu es un juriste qui vérifie une réponse rédigée à propos d'un arrêt de la Cour de cassation.
On te donne le texte intégral de l'arrêt, la question posée et UNE phrase de la réponse.
Juge la phrase uniquement d'après l'arrêt. Conventions de lecture d'un arrêt de cassation :
- L'exposé « Faits et procédure » (« Selon l'arrêt attaqué… », « Il résulte de l'arrêt attaqué et des pièces de la
  procédure… ») rapporte les faits tels que retenus par la juridiction du fond : « la cour d'appel a constaté / relevé X »
  est CORRECT pour un fait de l'exposé ; « la Cour de cassation a constaté X » est MAL_ATTRIBUE (elle ne constate pas les faits).
- Les passages « l'arrêt retient / énonce / relève que… », « pour rejeter…, l'arrêt… » sont le raisonnement de la cour d'appel.
  En revanche la critique que la Cour formule ensuite (« en statuant ainsi, sans vérifier… ») est celle de la Cour, pas de la cour d'appel.
- La Cour qui approuve la cour d'appel (« à bon droit », « exactement retenu/déduit », « a justifié sa décision ») peut être
  dite « la Cour approuve la cour d'appel qui a retenu… » ; c'est CORRECT.
- Une règle que la Cour énonce en interprétant un texte (« il résulte de ce texte que… », « il en résulte que… ») peut être
  dite « la Cour juge que… » ; c'est CORRECT. Le texte même d'une loi ou d'une convention (« aux termes de… ») présenté
  comme une décision de la Cour est MAL_ATTRIBUE.
- « Le demandeur soutient X » est CORRECT si X figure dans le moyen.
Verdicts :
- CORRECT : le contenu figure dans l'arrêt et est attribué au bon locuteur.
- MAL_ATTRIBUE : le contenu figure dans l'arrêt mais est prêté au mauvais locuteur.
- FAUX : la phrase affirme quelque chose que l'arrêt ne dit pas ou contredit (y compris sur la solution).
- NEUTRE : la phrase n'affirme rien de vérifiable.
Réponds en JSON strict : {"verdict": "...", "locuteur_reel": "...", "paragraphe": "...", "raison": "une phrase"}"""


def judge(model: str, decision_text: str, question: str, sentence: str) -> dict:
    from mistralai.client import Mistral

    client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
    messages = [
        {"role": "system", "content": JUDGE_PROMPT},
        {"role": "user", "content": f"Arrêt :\n\n{decision_text}\n\nQuestion : {question}\n\nPhrase à juger : {sentence}"},
    ]
    for attempt in range(7):
        try:
            r = client.chat.complete(model=model, temperature=0, messages=messages, response_format={"type": "json_object"})
            content = r.choices[0].message.content
            if isinstance(content, list):
                content = "".join(getattr(c, "text", "") or "" for c in content)
            return json.loads(re.search(r"\{.*\}", content, re.S).group(0))
        except Exception as error:
            if attempt == 6:
                return {"verdict": "ERREUR", "raison": str(error)[:200]}
            time.sleep(5 * 2**attempt)


def run(results: Path, out: Path) -> None:
    rows = json.loads(results.read_text())
    texts: dict[str, str] = {}
    jobs = []
    for i, r in enumerate(rows):
        if r.get("error") or r.get("abstained") or r["kind"] == "hors_sujet":
            continue
        texts.setdefault(r["decision"], json.loads((ROOT / "bench/decisions" / f"{r['decision']}.json").read_text())["text"])
        for s, e in split_sentences(r["answer"]):
            sentence = r["answer"][s:e].strip()
            if len(sentence) > 3:
                jobs.append((i, sentence))

    def one(job):
        i, sentence = job
        r = rows[i]
        return i, sentence, {m: judge(m, texts[r["decision"]], r["question"], sentence) for m in PANEL}

    judged = []
    with cf.ThreadPoolExecutor(3) as pool:
        for i, sentence, votes in pool.map(one, jobs):
            verdicts = [v.get("verdict") for v in votes.values()]
            judged.append({
                "row": i, "system": rows[i]["system"], "decision": rows[i]["decision"], "kind": rows[i]["kind"],
                "sentence": sentence, "votes": votes,
                "error": sum(v in ERRORS for v in verdicts) >= 2,
                "mal_attribue": sum(v == "MAL_ATTRIBUE" for v in verdicts) >= 2,
            })
    out.write_text(json.dumps(judged, ensure_ascii=False, indent=1))
    print("jugées :", len(judged), "phrases")


def score(judged_path: Path, gold_path: Path, results: Path) -> None:
    judged = json.loads(judged_path.read_text())
    gold = {(g["decision"], g["system"], g["sentence"]): g["label"] for g in json.loads(gold_path.read_text())}
    rows = json.loads(results.read_text())
    labels: dict[int, list[str]] = defaultdict(list)
    failed = 0
    for j in judged:
        failed += sum(v.get("verdict") == "ERREUR" for v in j["votes"].values())
        label = gold.get((j["decision"], j["system"], j["sentence"]))
        labels[j["row"]].append(label or ("ERREUR" if j["error"] else "CORRECT"))
    for system in sorted({r["system"] for r in rows}):
        idx = [i for i, r in enumerate(rows) if r["system"] == system]
        sentences = [lab for i in idx for lab in labels.get(i, [])]
        print(f"\n{system} : phrases fausses ou mal attribuées {sentences.count('ERREUR')}/{len(sentences)}"
              f" (+{sentences.count('INCERTAIN')} incertaines)")
        for kind in sorted({rows[i]["kind"] for i in idx}):
            k = [i for i in idx if rows[i]["kind"] == kind]
            if kind == "hors_sujet":
                ok = sum(bool(rows[i].get("abstained")) for i in k)
            else:
                ok = sum(not rows[i].get("abstained") and "ERREUR" not in labels.get(i, []) for i in k)
            print(f"  {kind:15} {ok}/{len(k)}")
    print(f"\nappels du juge en échec (429…) : {failed}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["run", "score"])
    p.add_argument("--results", type=Path, default=ROOT / "bench/results.json")
    p.add_argument("--out", "--judged", dest="judged", type=Path, default=ROOT / "bench/judge_results.json")
    p.add_argument("--gold", type=Path, default=ROOT / "bench/gold.json")
    a = p.parse_args()
    if a.cmd == "run":
        run(a.results, a.judged)
    else:
        score(a.judged, a.gold, a.results)


if __name__ == "__main__":
    main()
