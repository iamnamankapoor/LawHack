"""Demo web app: upload a decision (PDF or .txt), watch the System 1 reading, then chat with cited answers."""

import time
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel

from lawhack import feedback
from lawhack.answer import Answer, ZONE_LABELS, ask, speaker_label
from lawhack.ingest import NoTextError
from lawhack.pipeline import analyse, load
from lawhack.schema import Registry, Speaker
from lawhack.solution import Solution
from lawhack.system_one import TypeSafeSystemOne

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

ROOT = Path(__file__).resolve().parent.parent
UPLOADS = ROOT / "data" / "raw"
DEMO_PDF = ROOT / "data" / "samples" / "cass_civ3_2022-12-14_21-24539.pdf"
STATIC = Path(__file__).resolve().parent / "static"

app = FastAPI(title="LawHack")
_registries: dict[str, tuple[Registry, Solution]] = {}
_answers: dict[str, tuple[str, Answer]] = {}


class Question(BaseModel):
    question: str


class FeedbackRequest(BaseModel):
    answer_id: str
    verdict: str
    sentence_index: int | None = None
    segment_id: str | None = None
    speaker: str | None = None


def _entry_dict(entry) -> dict:
    return {
        "id": entry.id,
        "paragraph": entry.paragraph,
        "zone": ZONE_LABELS[entry.zone],
        "speaker": entry.speaker.value,
        "label": speaker_label(entry),
        "confidence": round(entry.speaker.confidence, 3),
        "text": entry.text,
    }


def _analyse(path: Path) -> dict:
    started = time.perf_counter()
    try:
        doc = load(path)
    except NoTextError as error:
        raise HTTPException(422, str(error)) from error
    if not doc.text.strip():
        raise HTTPException(422, "Aucun texte lisible dans ce document.")
    registry, solution = analyse(doc)
    if not registry.entries:
        raise HTTPException(422, "Aucun paragraphe d'arrêt reconnu dans ce document.")
    _registries[registry.document_id] = (registry, solution)
    return {
        "document_id": registry.document_id,
        "solution": solution.value,
        "model": registry.model,
        "seconds": round(registry.seconds or time.perf_counter() - started, 2),
        "input_tokens": registry.input_tokens,
        "entries": [_entry_dict(entry) for entry in registry.entries],
    }


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.post("/api/documents")
async def upload(file: UploadFile) -> dict:
    if Path(file.filename or "").suffix.lower() not in {".pdf", ".txt"}:
        raise HTTPException(400, "Déposez un arrêt en PDF ou en .txt (Légifrance ou Judilibre).")
    UPLOADS.mkdir(parents=True, exist_ok=True)
    path = UPLOADS / f"{uuid.uuid4().hex[:8]}_{Path(file.filename).name}"
    path.write_bytes(await file.read())
    return await run_in_threadpool(_analyse, path)


@app.post("/api/documents/demo")
async def demo() -> dict:
    return await run_in_threadpool(_analyse, DEMO_PDF)


@app.post("/api/documents/{document_id}/ask")
async def question(document_id: str, body: Question) -> dict:
    analyzed = _registries.get(document_id)
    if analyzed is None:
        raise HTTPException(404, "Document inconnu : déposez-le à nouveau.")
    registry, solution = analyzed
    started = time.perf_counter()
    try:
        answer = await ask(registry, body.question, TypeSafeSystemOne(), solution=solution)
    except Exception as error:  # surfaced in the chat instead of a blank failure
        status = getattr(error, "status_code", None)
        detail = "Mistral a refusé la requête (quota ou limite de débit atteint)." if status == 429 else f"Erreur : {error}"
        raise HTTPException(502, detail) from error
    answer_id = uuid.uuid4().hex[:12]
    _answers[answer_id] = (document_id, answer)
    return {**answer.model_dump(), "answer_id": answer_id, "seconds": round(time.perf_counter() - started, 2)}


@app.post("/api/feedback")
def submit_feedback(body: FeedbackRequest) -> dict:
    stored = _answers.get(body.answer_id)
    if stored is None:
        raise HTTPException(404, "Réponse inconnue.")
    document_id, answer = stored

    if body.verdict in ("correct", "wrong_speaker", "unsupported"):
        if body.sentence_index is None or body.segment_id is None:
            raise HTTPException(422, "sentence_index et segment_id sont requis pour une pastille.")
        if body.sentence_index < 0 or body.sentence_index >= len(answer.sentences):
            raise HTTPException(422, "Phrase inconnue dans cette réponse.")
        sentence = answer.sentences[body.sentence_index]
        pill = next((item for item in sentence.pills if item.segment_id == body.segment_id), None)
        if pill is None:
            raise HTTPException(422, "Pastille inconnue dans cette phrase.")

        corrected: Speaker | None = None
        if body.verdict == "wrong_speaker":
            try:
                corrected = Speaker(body.speaker)
            except (TypeError, ValueError) as error:
                raise HTTPException(422, "Locuteur corrigé invalide.") from error
        elif body.verdict == "correct":
            try:
                corrected = Speaker(pill.speaker)
            except ValueError as error:
                raise HTTPException(422, "Locuteur de la pastille invalide.") from error

        feedback.record(feedback.FeedbackEvent(
            ts=time.time(),
            document_id=document_id,
            question=answer.question,
            verdict=body.verdict,
            sentence_index=body.sentence_index,
            sentence=sentence.text,
            segment_id=body.segment_id,
            shown_speaker=pill.speaker,
            corrected_speaker=corrected.value if corrected else None,
            confidence=pill.confidence,
            level=pill.level,
            supported=sentence.supported,
        ))

        entry = None
        if corrected is not None:
            feedback.set_override(document_id, body.segment_id, corrected)
            analyzed = _registries.get(document_id)
            if analyzed is not None:
                registry, solution = analyzed
                registry = feedback.apply_overrides(registry)
                _registries[document_id] = (registry, solution)
                updated_entry = registry.by_id(body.segment_id)
                entry = _entry_dict(updated_entry) if updated_entry is not None else None
        return {"learning": feedback.stats(), "entry": entry}

    if body.verdict in ("up", "down"):
        feedback.record(feedback.FeedbackEvent(
            ts=time.time(),
            document_id=document_id,
            question=answer.question,
            verdict=body.verdict,
            answer=answer.model_dump(),
        ))
        return {"learning": feedback.stats(), "entry": None}

    raise HTTPException(422, "Verdict invalide.")


@app.get("/api/learning")
def learning_stats() -> dict:
    return feedback.stats()
