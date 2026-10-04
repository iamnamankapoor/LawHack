"""Claude calls (System 2): propose the list of facts, write the summary from the fact table,
and the LLM-alone baseline. Every call is cached on disk."""
import hashlib
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import jevkit  # noqa: E402,F401  (loads the project .env)

MODEL = "claude-opus-5-5"
CACHE = ROOT / "cache" / "llm"
RECIF_ENV = pathlib.Path("C:/Users/andre/recif-pipeline/.env")
_client = None


def _api_key():
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"]
    for line in RECIF_ENV.read_text(encoding="utf-8").splitlines():
        if line.startswith("ANTHROPIC_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("ANTHROPIC_API_KEY not found")


def call(system, user, schema=None, effort="medium", max_tokens=16000, label="llm"):
    global _client
    blob = json.dumps([MODEL, system, user, schema, effort], ensure_ascii=False, sort_keys=True)
    key = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    path = CACHE / f"{label}-{key[:16]}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))["result"]
    if os.environ.get("LLM_OFFLINE") == "1":
        raise RuntimeError(f"LLM cache miss in offline mode ({label})")
    import anthropic
    if _client is None:
        _client = anthropic.Anthropic(api_key=_api_key())
    output_config = {"effort": effort}
    if schema:
        output_config["format"] = {"type": "json_schema", "schema": schema}
    params = dict(model=MODEL, max_tokens=max_tokens, system=system,
                  messages=[{"role": "user", "content": user}], output_config=output_config,
                  betas=["server-side-fallback-2026-07-01"])
    try:
        resp = _client.beta.messages.create(**params, fallbacks="default")
    except TypeError:  # older SDK without the typed parameter
        resp = _client.beta.messages.create(**params, extra_body={"fallbacks": "default"})
    if resp.stop_reason == "refusal":
        raise RuntimeError(f"{label}: refused ({getattr(resp, 'stop_details', None)})")
    if resp.stop_reason == "max_tokens":
        raise RuntimeError(f"{label}: hit max_tokens")
    text = next(b.text for b in resp.content if b.type == "text")
    result = json.loads(text) if schema else text
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"model": resp.model, "result": result,
                                "usage": {"input": resp.usage.input_tokens, "output": resp.usage.output_tokens}},
                               ensure_ascii=False, indent=1), encoding="utf-8")
    return result


FACTS_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["facts"],
    "properties": {"facts": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["id", "statement", "date", "topic"],
        "properties": {"id": {"type": "string"}, "statement": {"type": "string"},
                       "date": {"type": "string"}, "topic": {"type": "string"}}}}},
}

FACTS_PROMPT = """Below are the sentences of a French commercial litigation file that state or report facts, grouped by document, with who wrote each document. Produce the list of the distinct facts of the dispute these sentences talk about.

Rules:
- One fact = one atomic, checkable proposition about the world (an event, an act, a statement someone made, a date, a number), written in French, neutral, in the affirmative form, without legal qualification (no « faute », « déloyal », « abusif ») and without saying who claims it. Example: « Michael Scott a photocopié le fichier clients de Dunder Mifflin le 10 février 2026 ».
- When the parties give opposite versions of the same event, it is ONE fact: the parties will later be recorded as affirming or denying it. But keep apart facts that are about different things, for example « informer des clients de son départ » and « solliciter des clients ».
- When the figures differ (for example a number of clients), write one fact per figure that someone puts forward.
- Ids F01, F02, ... in chronological order of the events; date = the event date as YYYY-MM-DD, or "" when unknown; topic = 2 to 4 words.
- Cover every fact that at least one sentence mentions, including undisputed background facts. At most 45 facts.

Sentences:
"""


def propose_facts(case, docs, fact_sids):
    lines = []
    for doc in docs:
        m = doc["meta"]
        mine = [s for s in doc["sentences"] if s["id"] in fact_sids]
        if not mine:
            continue
        lines.append(f"\n[{m['id']} | {m.get('title')} | written by {case['speakers'].get(m.get('author'))} | {m.get('date')}]")
        lines += [f"- {s['text']}" for s in mine]
    result = call("You structure the facts of a French litigation file. You never decide who is right.",
                  FACTS_PROMPT + "\n".join(lines), schema=FACTS_SCHEMA, effort="high", label="facts")
    return result["facts"]


SYNTH_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["sentences"],
    "properties": {"sentences": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["text", "facts"],
        "properties": {"text": {"type": "string"}, "facts": {"type": "array", "items": {"type": "string"}}}}}},
}

SYNTH_PROMPT = """Write the « restitution des faits » a French litigator needs to prepare the hearing, in French, 250 to 400 words, in chronological order, using ONLY the fact table below.

Rules:
- Every sentence lists in `facts` the ids of the table rows it relies on.
- Always say who affirms, admits or denies each fact. Never present a disputed or merely alleged fact as established.
- Report version changes and the expert's findings when the table shows them.
- Add no fact that is not in the table.

Fact table (JSON):
"""


def synthesize(rows):
    table = [{k: r[k] for k in ("id", "statement", "date", "status", "status_label", "by_party", "expert", "witnesses")}
             for r in rows]
    return call("You write precise, neutral case summaries for litigators.",
                SYNTH_PROMPT + json.dumps(table, ensure_ascii=False, indent=1),
                schema=SYNTH_SCHEMA, effort="medium", label="synthesis")["sentences"]


BASELINE_PROMPT = """Tu es avocat collaborateur dans un cabinet parisien. Voici le dossier complet d'un contentieux. Rédige la restitution des faits pour préparer l'audience : qui affirme quoi, ce qui est admis par les deux parties et ce qui est contesté. 300 à 400 mots, en français, ordre chronologique.

DOSSIER
"""


def dossier_text(docs):
    parts = []
    for doc in docs:
        m = doc["meta"]
        parts.append(f"\n===== {m.get('title')} ({m['id']}, {m.get('date')}) =====")
        for p in doc["pages"]:
            parts.append(f"--- page {p['page']} ---\n{p['text']}")
    return "\n".join(parts)


def baseline(docs):
    return call("Tu es un avocat rigoureux.", BASELINE_PROMPT + dossier_text(docs), effort="medium",
                label="baseline")
