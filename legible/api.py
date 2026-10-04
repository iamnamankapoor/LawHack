"""Legible web API + UI.   uvicorn legible.api:app --port 8766"""
import glob
import hashlib
import os
import time

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import ingest
from .answer import analyse, answer
from .check import check
from .holdings import holdings
from .render import ref

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
DEFAULT_MODEL = os.environ.get("LEGIBLE_ANSWER_MODEL", "mistral/mistral-large-3")

app = FastAPI(title="Legible")
app.mount("/static", StaticFiles(directory=WEB), name="static")
DECISIONS: dict[str, str] = {}  # id -> text (labels are cached on disk by analyse())


def _samples():
    out = []
    for path in sorted(glob.glob(os.path.join(ROOT, "data", "decisions", "*.txt"))):
        title = open(path, encoding="utf-8").readline().strip()
        out.append({"id": os.path.basename(path)[:-4], "title": title})
    return out


def _payload(doc_id, text, seconds=None):
    segs, outcomes = analyse(text, key=doc_id)
    title = text.strip().split("\n", 1)[0] if text.lstrip().startswith("Cour de cassation") else "Décision de la Cour de cassation"
    return {
        "id": doc_id, "title": title, "seconds": seconds,
        "segments": [{"id": s["id"], "ref": ref(s), "section": s["section"], "heading": s.get("heading"),
                      "ground": s.get("ground"), "speaker": s["speaker"], "p": s.get("p"), "stance": s.get("stance"),
                      "text": s["text"]} for s in segs],
        "holdings": holdings(segs, outcomes),
    }


def _load(doc_id):
    if doc_id not in DECISIONS:
        path = os.path.join(ROOT, "data", "decisions", f"{doc_id}.txt")
        if not os.path.exists(path):
            raise HTTPException(404, "Décision inconnue : rechargez-la.")
        DECISIONS[doc_id] = open(path, encoding="utf-8").read()
    return DECISIONS[doc_id]


@app.get("/")
def index():
    return FileResponse(os.path.join(WEB, "index.html"), media_type="text/html; charset=utf-8")


@app.get("/api/samples")
def samples():
    return _samples()


@app.post("/api/analyze")
async def analyze(file: UploadFile | None = File(None), text: str | None = Form(None), sample: str | None = Form(None)):
    if sample:
        doc_id, body = sample, _load(sample)
    else:
        try:
            body = ingest.from_upload(file.filename, await file.read()) if file else (text or "")
        except ingest.NoTextError as e:
            raise HTTPException(422, str(e)) from e
        if len(body.strip()) < 200:
            raise HTTPException(422, "Texte trop court : collez la décision complète (Légifrance ou Judilibre).")
        doc_id = "d" + hashlib.sha256(body.encode()).hexdigest()[:12]
        DECISIONS[doc_id] = body
    t = time.time()
    return _payload(doc_id, body, round(time.time() - t, 1))


class Ask(BaseModel):
    id: str
    question: str
    model: str | None = None


@app.post("/api/ask")
def ask(body: Ask):
    return answer(_load(body.id), body.question, body.model or DEFAULT_MODEL, key=body.id)


class Draft(BaseModel):
    id: str
    draft: str
    model: str | None = None


@app.post("/api/check")
def check_draft(body: Draft):
    segs, outcomes = analyse(_load(body.id), key=body.id)
    return {"sentences": check(body.draft, segs, outcomes, body.model or DEFAULT_MODEL)}
