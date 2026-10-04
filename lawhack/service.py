"""Connector-facing service: one place for load / who_said / verify / passage.

Both the MCP server and the REST API are thin façades over these functions. Calls are
stateless: `load_decision` returns a server-minted `decision_id` that every other call
takes as an ordinary argument (the pattern recommended by MCP 2026-07-28, SEP-2567).
"""

import base64
import html
import json
import re
import tempfile
import urllib.request
from pathlib import Path

from pydantic import BaseModel, Field

from lawhack import verify as verifier
from lawhack.ingest import load_pdf, load_text
from lawhack.heuristic import HeuristicSystemOne
from lawhack.pipeline import CACHE_DIR, analyse_async, default_client
from lawhack.retrieval import BM25, coverage
from lawhack.schema import Document, Registry, RegistryEntry, Speaker, Status, Zone
from lawhack.solution import Solution

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "data" / "samples"
MAX_BYTES = 15_000_000
CONFIDENCE_OK = 0.8
CONFIDENCE_WARN = 0.5

SPEAKER_LABELS = {
    "COUR_CASSATION": "Cour de cassation", "JURIDICTION_FOND": "Cour d'appel", "DEMANDEUR": "Demandeur",
    "DEFENDEUR": "Défendeur", "MINISTERE_PUBLIC": "Ministère public", "LOI": "Loi", "INDETERMINE": "Indéterminé",
}
ZONE_LABELS = {
    "introduction": "En-tête", "expose": "Faits et procédure", "moyens": "Énoncé du moyen",
    "motivations": "Réponse de la Cour", "dispositif": "Dispositif", "metadonnees": "Métadonnées",
}


class Passage(BaseModel):
    segment_id: str
    citation: str = Field(description="Human citation to reproduce in the answer, e.g. « §8, Réponse de la Cour ».")
    badge: str = Field(description="Attribution badge to append to the sentence, e.g. [Cour d'appel · §5 · 91 %].")
    text: str
    speaker: str
    speaker_label: str
    chain: list[str]
    status: str
    type: str
    confidence: float
    probabilities: dict[str, float]
    flag: str = Field(description="ok (≥0.8) · a_verifier (0.5–0.8) · incertain (<0.5)")
    paragraph: int | None = None
    zone: str
    page: int | None = None


class DecisionSummary(BaseModel):
    decision_id: str
    solution: str
    segments: int
    zones: dict[str, int]
    attribution_model: str | None
    heuristic_mode: bool = Field(description="True when no Jev key is configured: attributions are rough and all flagged.")
    dispositif: list[Passage]


class WhoSaidResult(BaseModel):
    decision_id: str
    question: str
    answer_status: str = Field(description="answered · only_alleged (only the parties argue it) · not_decided_by_court · not_in_decision")
    guidance: str
    passages: list[Passage]


class VerifiedSentence(BaseModel):
    sentence: str
    claimed_speaker: str | None
    verdict: str = Field(description="OK · A_VERIFIER · MAL_ATTRIBUE · NON_SOURCE · SANS_ATTRIBUTION")
    explanation: str
    source: Passage | None


class VerifyResult(BaseModel):
    decision_id: str
    summary: dict[str, int]
    sentences: list[VerifiedSentence]


class _Record(BaseModel):
    document: Document
    registry: Registry
    solution: Solution


_STORE: dict[str, _Record] = {}


def _record_path(decision_id: str) -> Path:
    return CACHE_DIR / f"{decision_id}.decision.json"


def _get(decision_id: str) -> _Record:
    if decision_id in _STORE:
        return _STORE[decision_id]
    path = _record_path(decision_id)
    if not re.fullmatch(r"[0-9a-f]{16}", decision_id) or not path.exists():
        raise KeyError(f"Unknown decision_id {decision_id!r}: call lawhack_load_decision first.")
    _STORE[decision_id] = _Record.model_validate_json(path.read_text())
    return _STORE[decision_id]


def _flag(confidence: float) -> str:
    if confidence >= CONFIDENCE_OK:
        return "ok"
    return "a_verifier" if confidence >= CONFIDENCE_WARN else "incertain"


def passage(entry: RegistryEntry) -> Passage:
    zone = ZONE_LABELS[entry.zone.value]
    para = f"§{entry.paragraph}" if entry.paragraph else entry.id
    label = SPEAKER_LABELS[entry.speaker.value]
    flag = _flag(entry.speaker.confidence)
    warn = " ⚠" if flag != "ok" else ""
    top = dict(sorted(entry.speaker.probabilities.items(), key=lambda kv: kv[1], reverse=True)[:3])
    return Passage(
        segment_id=entry.id, citation=f"{para}, {zone}", badge=f"[{label} · {para} · {entry.speaker.confidence:.0%}{warn}]",
        text=entry.text, speaker=entry.speaker.value, speaker_label=label, chain=[s.value for s in entry.chain],
        status=entry.status.value, type=entry.type.value, confidence=round(entry.speaker.confidence, 3),
        probabilities={k: round(v, 3) for k, v in top.items()}, flag=flag, paragraph=entry.paragraph,
        zone=entry.zone.value, page=entry.page,
    )


# --- loading -----------------------------------------------------------------------------


def list_samples() -> list[str]:
    return sorted(p.stem for p in SAMPLES_DIR.glob("*") if p.suffix in {".pdf", ".json", ".txt"})


def _html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</h\d>", "\n\n", raw)
    return html.unescape(re.sub(r"<[^>]+>", " ", raw))


def _from_pdf_bytes(data: bytes) -> Document:
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(data)
        f.flush()
        return load_pdf(f.name)


def _from_json(data: dict) -> Document:
    if "text" not in data:
        raise ValueError("JSON input must contain a `text` field (Judilibre decision format).")
    return load_text(data["text"])


def _from_url(url: str) -> Document:
    if not url.startswith(("https://", "http://")):
        raise ValueError("url must be http(s).")
    request = urllib.request.Request(url, headers={"User-Agent": "LawHack/0.1 (+https://github.com/talal95c/LawHack)"})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read(MAX_BYTES + 1)
        kind = response.headers.get("Content-Type", "")
    if len(data) > MAX_BYTES:
        raise ValueError("Document too large.")
    if "pdf" in kind or data[:4] == b"%PDF":
        return _from_pdf_bytes(data)
    text = data.decode("utf-8", errors="replace")
    if "json" in kind:
        return _from_json(json.loads(text))
    return load_text(_html_to_text(text) if "html" in kind or "<html" in text[:500].lower() else text)


def _from_sample(name: str) -> Document:
    path = next((p for p in SAMPLES_DIR.glob(f"{name}.*")), None)
    if path is None or name not in list_samples():
        raise ValueError(f"Unknown sample {name!r}. Available: {', '.join(list_samples())}")
    if path.suffix == ".pdf":
        return load_pdf(path)
    if path.suffix == ".json":
        return _from_json(json.loads(path.read_text()))
    return load_text(path.read_text())


def read_document(text: str | None = None, url: str | None = None, pdf_base64: str | None = None, sample: str | None = None) -> Document:
    given = [v for v in (text, url, pdf_base64, sample) if v]
    if len(given) != 1:
        raise ValueError("Provide exactly one of: text, url, pdf_base64, sample.")
    if text:
        return load_text(text)
    if url:
        return _from_url(url)
    if pdf_base64:
        return _from_pdf_bytes(base64.b64decode(pdf_base64))
    return _from_sample(sample)


async def load_decision(text: str | None = None, url: str | None = None, pdf_base64: str | None = None, sample: str | None = None) -> DecisionSummary:
    doc = read_document(text, url, pdf_base64, sample)
    try:
        stale = _get(doc.id).registry.model == HeuristicSystemOne.model and not isinstance(default_client(), HeuristicSystemOne)
    except KeyError:
        stale = True
    if stale:
        registry, solution = await analyse_async(doc)
        record = _Record(document=doc, registry=registry, solution=solution)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _record_path(doc.id).write_text(record.model_dump_json())
        _STORE[doc.id] = record
    record = _get(doc.id)
    zones: dict[str, int] = {}
    for e in record.registry.entries:
        zones[e.zone.value] = zones.get(e.zone.value, 0) + 1
    return DecisionSummary(
        decision_id=doc.id, solution=record.solution.value, segments=len(record.registry.entries), zones=zones,
        attribution_model=record.registry.model, heuristic_mode=record.registry.model == "heuristic",
        dispositif=[passage(e) for e in record.registry.entries if e.zone is Zone.DISPOSITIF],
    )


# --- querying ----------------------------------------------------------------------------


def _searchable(record: _Record) -> list[RegistryEntry]:
    return [e for e in record.registry.entries if e.zone not in (Zone.METADONNEES, Zone.INTRODUCTION)]


RELEVANT_MIN = 0.3  # share of the question's content words a passage must contain
DECIDES_MIN = 0.5


def who_said(decision_id: str, question: str, k: int = 6) -> WhoSaidResult:
    record = _get(decision_id)
    entries = _searchable(record)
    query = verifier.strip_cues(question)
    scored = [(entries[i], coverage(query, entries[i].text)) for i, _ in BM25([e.text for e in entries]).top(query, k=k)]
    hits = [(e, c) for e, c in scored if c >= RELEVANT_MIN]
    if not hits:
        status, guidance = "not_in_decision", "Aucun passage de l'arrêt ne traite cette question : dites-le, sans répondre de mémoire."
    elif any(e.speaker.value == Speaker.COUR_CASSATION.value and e.status.value == Status.DECIDE.value and c >= DECIDES_MIN
             for e, c in hits):
        status = "answered"
        guidance = ("Répondez uniquement à partir de ces passages, en distinguant les voix (la Cour décide / la cour d'appel "
                    "avait retenu / le demandeur soutient), en citant `citation` et en ajoutant `badge`. Signalez les "
                    "passages `a_verifier` ou `incertain`.")
    elif all(e.status.value == Status.ALLEGUE.value for e, _ in hits):
        status = "only_alleged"
        guidance = "Seules les parties évoquent ce point : précisez que la Cour ne le tranche pas et attribuez l'argument à la partie."
    else:
        status = "not_decided_by_court"
        guidance = ("La Cour de cassation ne tranche pas ce point : il n'apparaît que dans les constatations de la cour d'appel "
                    "ou les arguments des parties. Attribuez chaque élément à sa voix réelle.")
    return WhoSaidResult(decision_id=decision_id, question=question, answer_status=status, guidance=guidance,
                         passages=[passage(e) for e, _ in hits])


def get_passage(decision_id: str, segment_id: str, context: int = 1) -> list[Passage]:
    entries = _get(decision_id).registry.entries
    index = next((i for i, e in enumerate(entries) if e.id == segment_id), None)
    if index is None:
        raise KeyError(f"Unknown segment_id {segment_id!r}.")
    return [passage(e) for e in entries[max(0, index - context): index + context + 1]]


_EXPLAIN = {
    "OK": "Attribution conforme au registre.",
    "A_VERIFIER": "Attribution plausible mais confiance faible : à vérifier dans le passage source.",
    "NON_SOURCE": "Aucun passage de l'arrêt ne soutient cette phrase.",
    "SANS_ATTRIBUTION": "La phrase ne nomme pas de locuteur ; le passage source est fourni.",
}


def verify_text(decision_id: str, text: str) -> VerifyResult:
    record = _get(decision_id)
    sentences = []
    for r in verifier.check(record.registry, text, threshold=CONFIDENCE_OK):
        entry = r["entry"]
        if r["verdict"] == "MAL_ATTRIBUE":
            actual = SPEAKER_LABELS[entry.speaker.value]
            claimed = SPEAKER_LABELS[r["claimed_speaker"]]
            para = f"§{entry.paragraph}" if entry.paragraph else entry.id
            explanation = f"Attribué à : {claimed} — en réalité : {actual} ({para}, {ZONE_LABELS[entry.zone.value]})."
        else:
            explanation = _EXPLAIN[r["verdict"]]
        sentences.append(VerifiedSentence(sentence=r["sentence"], claimed_speaker=r["claimed_speaker"], verdict=r["verdict"],
                                          explanation=explanation, source=passage(entry) if entry else None))
    summary: dict[str, int] = {}
    for s in sentences:
        summary[s.verdict] = summary.get(s.verdict, 0) + 1
    return VerifyResult(decision_id=decision_id, summary=summary, sentences=sentences)
