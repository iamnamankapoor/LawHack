"""LLM-alone baseline: ask an OpenAI model to check draft sentences about the arrêt, with the full arrêt in context.

    .venv/Scripts/python baseline_openai.py [--models] [--model NAME] [--runs N]
Writes out_arret/openai_baseline.json. Every call is cached in cache/openai/.
"""
import argparse
import hashlib
import json
import os
import pathlib
import ssl
import sys
import time
import urllib.request

import certifi

ROOT = pathlib.Path(__file__).resolve().parent
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
CTX = ssl.create_default_context(cafile=certifi.where())
CACHE = ROOT / "cache" / "openai"
RECIF_ENV = pathlib.Path("C:/Users/andre/recif-pipeline/.env")


def key():
    if os.environ.get("OPENAI_API_KEY"):
        return os.environ["OPENAI_API_KEY"]
    for line in RECIF_ENV.read_text(encoding="utf-8").splitlines():
        if line.startswith("OPENAI_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit("OPENAI_API_KEY not found")


def api(path, body=None):
    req = urllib.request.Request("https://api.openai.com/v1/" + path,
                                 data=json.dumps(body).encode() if body else None,
                                 headers={"Authorization": f"Bearer {key()}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180, context=CTX) as r:
        return json.loads(r.read().decode())


def ask(model, prompt, run=0):
    h = hashlib.sha256(json.dumps([model, prompt, run]).encode()).hexdigest()[:20]
    path = CACHE / f"{model}-{h}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    t0 = time.time()
    r = api("chat/completions", {"model": model, "messages": [
        {"role": "system", "content": "Tu es un assistant juridique pour un cabinet d'avocats français."},
        {"role": "user", "content": prompt}]})
    out = {"model": r.get("model"), "answer": r["choices"][0]["message"]["content"],
           "latency_s": round(time.time() - t0, 1), "usage": r.get("usage")}
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def arret_text():
    raw = (ROOT / "dossier_arret" / "arret.md").read_text(encoding="utf-8")
    body = raw.split("\n---", 2)[-1]
    return "\n".join(l for l in body.splitlines() if not l.startswith("<!-- page"))


PROMPT = ("Voici le texte intégral d'un arrêt de la Cour de cassation.\n\n{arret}\n\n"
          "Un collaborateur a écrit dans une note destinée au client : « {sentence} »\n\n"
          "Cette phrase est-elle exacte au regard de l'arrêt ? Commence ta réponse par EXACTE ou INEXACTE, "
          "puis explique en deux phrases au plus.")


QA_PROMPT = ("Voici le texte intégral d'un arrêt de la Cour de cassation.\n\n{arret}\n\n"
             "Question d'un avocat : {question}\n\nRéponds en trois phrases au plus, en citant les paragraphes.")


def qa(model, runs):
    questions = json.loads((ROOT / "eval" / "arret_questions.json").read_text(encoding="utf-8"))
    text, out = arret_text(), []
    for q in questions:
        for run in range(runs):
            r = ask(model, QA_PROMPT.format(arret=text, question=q["question"]), run)
            out.append({"id": q["id"], "run": run, "model": r["model"], "question": q["question"],
                        "answer": r["answer"], "correct_answer": q["correct_answer"], "trap": q["trap"]})
            print(f"\n{q['id']} run{run} [{r['model']}] {q['question']}\n  -> {r['answer']}\n  attendu: {q['correct_answer']}")
    (ROOT / "out_arret").mkdir(exist_ok=True)
    (ROOT / "out_arret" / f"qa_{model}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                                          encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", action="store_true")
    ap.add_argument("--qa", action="store_true")
    ap.add_argument("--model", default="gpt-4.1")
    ap.add_argument("--runs", type=int, default=1)
    a = ap.parse_args()
    if a.models:
        ids = sorted(m["id"] for m in api("models")["data"])
        print([i for i in ids if i.startswith(("gpt", "o"))])
        return
    if a.qa:
        return qa(a.model, a.runs)
    traps = json.loads((ROOT / "eval" / "arret_traps.json").read_text(encoding="utf-8"))
    text, results = arret_text(), []
    for t in traps:
        for run in range(a.runs):
            r = ask(a.model, PROMPT.format(arret=text, sentence=t["sentence"]), run)
            verdict = "EXACTE" if r["answer"].strip().upper().startswith("EXACTE") else (
                "INEXACTE" if r["answer"].strip().upper().startswith("INEXACTE") else "?")
            ok = (verdict == "EXACTE") == t["correct"]
            results.append({"id": t["id"], "run": run, "model": r["model"], "verdict": verdict, "ok": ok,
                            "answer": r["answer"]})
            print(f"{t['id']:<4} run{run} {r['model']:<22} {verdict:<9} {'OK ' if ok else 'FAIL'}  {r['answer'][:110]!r}")
    out = ROOT / "out_arret"
    out.mkdir(exist_ok=True)
    (out / f"openai_baseline_{a.model}.json").write_text(json.dumps(results, ensure_ascii=False, indent=1),
                                                         encoding="utf-8")
    print(f"\n{a.model}: {sum(not r['ok'] for r in results)}/{len(results)} wrong")


if __name__ == "__main__":
    main()
