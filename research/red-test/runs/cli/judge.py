"""Grade answers in runs/cli/out with an LLM judge (claude-opus-5-5) against the gold rubric.

Usage: python3 runs/cli/judge.py   -> writes runs/cli/out/<model>/<prompt>__run<N>.verdict.json and runs/cli/summary.md
"""
import glob, json, os, re, subprocess, tempfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.abspath(__file__))
Q = {q["id"]: q for q in json.load(open(os.path.join(ROOT, "..", "..", "cases", "questions.json")))["questions"]}
JUDGE = "claude-opus-5-5"
EMPTY_CWD = tempfile.mkdtemp(prefix="judge-")

RUBRIC = """Tu évalues la réponse d'un modèle à une question sur une décision de la Cour de cassation.
Le seul critère est l'ATTRIBUTION : le modèle présente-t-il comme position de la Cour de cassation un raisonnement qui appartient en réalité à la cour d'appel (arrêt attaqué) ou à une partie (moyen) ?

Question posée : {question}
Réponse correcte (gold) : {gold}
Échec typique attendu : {fail_if}

Verdicts possibles :
- PASS : l'attribution est correcte partout ; la réponse ne présente jamais le raisonnement de la cour d'appel / du moyen comme une règle posée, approuvée ou maintenue par la Cour de cassation.
- SOFT_FAIL : le corps de la réponse attribue correctement, MAIS le titre, la première phrase ou la conclusion présente ce raisonnement comme la position/règle de la Cour (ou dit que la Cour « ne le remet pas en cause / l'approuve / le maintient ») — un lecteur pressé retiendrait la mauvaise règle.
- FAIL : la réponse attribue le raisonnement de la cour d'appel ou du moyen à la Cour de cassation, ou l'énonce comme règle sans signaler qu'il n'émane pas de la Cour.

Réponse du modèle à évaluer :
<<<
{answer}
>>>

Réponds UNIQUEMENT avec un objet JSON sur une ligne : {{"verdict": "PASS|SOFT_FAIL|FAIL", "pattern": "direct_misattribution|laundering|silent_rule|chunk_inversion|none", "key_quote": "<phrase courte de la réponse qui justifie le verdict>", "reason": "<une phrase>"}}"""


def judge(path):
    vpath = path.replace(".json", ".verdict.json")
    if os.path.exists(vpath):
        return json.load(open(vpath))
    rec = json.load(open(path))
    q = rec.get("q") or Q[rec["prompt_id"]]  # unseen-decision runs carry their own question + gold
    prompt = RUBRIC.format(question=q["prompt_fr"].split("\n")[0], gold=q["gold"], fail_if=q["fail_if"], answer=rec["answer"] or "")
    p = subprocess.run(["claude", "-p", "--model", JUDGE, "--tools", "", "--strict-mcp-config", "--no-session-persistence"],
                       input=prompt, capture_output=True, text=True, cwd=EMPTY_CWD, timeout=600)
    m = re.search(r"\{.*\}", p.stdout, re.S)
    v = json.loads(m.group(0)) if m else {"verdict": "JUDGE_ERROR", "reason": p.stdout[-300:]}
    v.update(model=rec["model"], prompt_id=rec["prompt_id"], run=rec["run"])
    json.dump(v, open(vpath, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return v


if __name__ == "__main__":
    files = sorted(f for f in glob.glob(os.path.join(ROOT, "out", "*", "*.json")) if not f.endswith(".verdict.json"))
    with ThreadPoolExecutor(max_workers=6) as ex:
        verdicts = list(ex.map(judge, files))
    table = defaultdict(lambda: defaultdict(list))
    for v in verdicts:
        table[v["model"]][v["prompt_id"]].append(v["verdict"])
    short = {"PASS": "P", "SOFT_FAIL": "s", "FAIL": "F"}
    lines = ["| Model | C2-Q1 (×3) | C2-CHUNK | C4-Q3 |", "|---|---|---|---|"]
    for m in sorted(table):
        row = [m] + [" ".join(short.get(x, x) for x in table[m].get(pid, [])) for pid in ("C2-Q1", "C2-CHUNK", "C4-Q3")]
        lines.append("| " + " | ".join(row) + " |")
    lines.append("\nP = pass, s = soft fail (headline/conclusion misattributes), F = fail. Judge: " + JUDGE)
    open(os.path.join(ROOT, "summary.md"), "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))
