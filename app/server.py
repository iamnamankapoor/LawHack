"""Demo web app: upload a decision (PDF or .txt), watch the System 1 reading, then chat with cited answers."""

import time
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel

from lawhack.answer import SPEAKER_LABELS, ZONE_LABELS, ask
from lawhack.ingest import NoTextError
from lawhack.pipeline import analyse, load
from lawhack.schema import Registry
from lawhack.system_one import TypeSafeSystemOne
from lawhack.answer import speaker_label

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

ROOT = Path(__file__).resolve().parent.parent
UPLOADS = ROOT / "data" / "raw"
DEMO_PDF = ROOT / "data" / "samples" / "cass_civ3_2022-12-14_21-24539.pdf"
STATIC = Path(__file__).resolve().parent / "static"

app = FastAPI(title="LawHack")
_registries: dict[str, Registry] = {}


class Question(BaseModel):
    question: str


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
    _registries[registry.document_id] = registry
    return {
        "document_id": registry.document_id,
        "solution": solution.value,
        "model": registry.model,
        "seconds": round(registry.seconds or time.perf_counter() - started, 2),
        "input_tokens": registry.input_tokens,
        "entries": [
            {
                "id": e.id,
                "paragraph": e.paragraph,
                "zone": ZONE_LABELS[e.zone],
                "speaker": e.speaker.value,
                "label": speaker_label(e),
                "confidence": round(e.speaker.confidence, 3),
                "text": e.text,
            }
            for e in registry.entries
        ],
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
    registry = _registries.get(document_id)
    if registry is None:
        raise HTTPException(404, "Document inconnu : déposez-le à nouveau.")
    started = time.perf_counter()
    try:
        answer = await ask(registry, body.question, TypeSafeSystemOne())
    except Exception as error:  # surfaced in the chat instead of a blank failure
        status = getattr(error, "status_code", None)
        detail = "Mistral a refusé la requête (quota ou limite de débit atteint)." if status == 429 else f"Erreur : {error}"
        raise HTTPException(502, detail) from error
    return {**answer.model_dump(), "seconds": round(time.perf_counter() - started, 2)}
