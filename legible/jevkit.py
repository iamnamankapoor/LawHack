"""jevkit: thin layer over the TypeSafe SDK (Jev, a "System One" decision model).

What it adds to the raw API:
- a disk cache keyed by (model, state, questions): re-runs are free and the demo works offline;
- chunking of many questions over one state, under the request budget;
- confidence gates (auto / review / uncertain);
- a usage log (tokens, latency) per pipeline stage.

Questions are plain dicts: {"type": "noul"|"choice"|"score", "instructions": str, "criteria": ...}.
Never point a question at `items[i]` in a long array: embed the item in its own question.
"""
import hashlib
import json
import os
import pathlib
import time

ROOT = pathlib.Path(__file__).resolve().parent
CACHE_DIR = ROOT / "cache" / "jev"
USAGE_LOG = ROOT / "cache" / "jev_usage.jsonl"
MODEL = "jev-latest"  # resolved to jev-1.13.0 on 2026-10-04; each cached answer records the version
MAX_REQUEST_TOKENS = 24000  # API budget is 32k tokens; our estimate is rough, keep a margin
MAX_QUESTIONS = int(os.environ.get("JEV_MAX_QUESTIONS", "60"))


def load_env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()  # the .env wins over a stale shell value


load_env()
_client = None


def _client_get():
    global _client
    if _client is None:
        from typesafe_sdk import TypeSafeClient
        _client = TypeSafeClient(timeout=90)
    return _client


def _sdk_question(q):
    from typesafe_sdk import Choice, Noul, Score
    if q["type"] == "noul":
        return Noul(instructions=q["instructions"])
    if q["type"] == "choice":
        return Choice(instructions=q["instructions"], criteria=q["criteria"])
    if q["type"] == "score":
        return Score(instructions=q["instructions"], criteria=q["criteria"])
    raise ValueError(f"unknown question type {q['type']}")


def estimate_tokens(obj):
    return len(json.dumps(obj, ensure_ascii=False)) // 3 + 1


def ask(state, questions, label="misc"):
    """One Jev request. Returns {question_id: answer_dict}."""
    blob = json.dumps({"model": MODEL, "state": state, "questions": questions},
                      sort_keys=True, ensure_ascii=False)
    key = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    path = CACHE_DIR / key[:2] / f"{key}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))["answers"]
    if os.environ.get("JEV_OFFLINE") == "1":
        raise RuntimeError(f"Jev cache miss in offline mode ({label})")
    t0 = time.time()
    r = _client_get().system_one(
        state=state, questions={k: _sdk_question(q) for k, q in questions.items()}, model=MODEL)
    latency = round(time.time() - t0, 3)
    answers = {k: a.model_dump() for k, a in r.answers.items()}
    usage = {"input_tokens": getattr(r.usage, "input_tokens", None),
             "output_tokens": getattr(r.usage, "output_tokens", None)}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"model": r.model, "answers": answers, "usage": usage,
                                "latency_s": latency}, ensure_ascii=False), encoding="utf-8")
    with USAGE_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": round(time.time()), "label": label, "model": r.model,
                            "questions": len(questions), **usage, "latency_s": latency}) + "\n")
    return answers


def ask_many(state, questions, label="misc"):
    """Many questions over one state, split into requests that fit the budget."""
    base = estimate_tokens(state)
    out, chunk, size = {}, {}, base
    for qid, q in questions.items():
        cost = estimate_tokens(q) + 10
        if chunk and (size + cost > MAX_REQUEST_TOKENS or len(chunk) >= MAX_QUESTIONS):
            out.update(ask(state, chunk, label))
            chunk, size = {}, base
        chunk[qid] = q
        size += cost
    if chunk:
        out.update(ask(state, chunk, label))
    return out


def confidence(answer):
    if answer["type"] == "noul":
        p = answer["noul"]
        return max(p, 1 - p)
    return answer.get("confidence") or 0.0


def gate(answer, auto=0.85, review=0.6):
    c = confidence(answer)
    return "auto" if c >= auto else ("review" if c >= review else "uncertain")


def usage_summary():
    if not USAGE_LOG.exists():
        return {"requests": 0, "input_tokens": 0}
    rows = [json.loads(line) for line in USAGE_LOG.read_text(encoding="utf-8").splitlines() if line]
    tokens = sum(r.get("input_tokens") or 0 for r in rows)
    return {"requests": len(rows), "input_tokens": tokens,
            "usd": round(tokens * 0.042 / 1_000_000, 4),
            "seconds": round(sum(r.get("latency_s") or 0 for r in rows), 1)}
