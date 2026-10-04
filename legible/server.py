"""Legible: site + live API.

    .venv/Scripts/python -m uvicorn server:app --port 8766

GET  /                 the site (site/index.html, live mode)
GET  /api/health       {"ok": true} (the page switches to live mode when this answers)
POST /api/analyze      file (PDF / TXT) or text  -> registry (who speaks in each sentence)
POST /api/verify       {"doc_id", "text"}         -> one verdict per sentence, with proof and rewrite
POST /api/compare      {"doc_id", "text"}         -> the same sentences checked by GPT-6.1 alone
"""
import asyncio
import hashlib
import io
import json
import pathlib
import sys
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import baseline_openai as oa  # noqa: E402
import legible  # noqa: E402

app = FastAPI(title="Legible")
DOCS = {}  # doc_id -> {"registry": [...], "text": full decision text}
MAX_BYTES = 6_000_000


def _load_demo_docs():
    data = json.loads((ROOT / "site" / "data.json").read_text(encoding="utf-8"))
    for a in data["arrets"]:
        DOCS[a["id"]] = {"registry": a["registry"], "text": " ".join(e["text"] for e in a["registry"])}


_load_demo_docs()


class VerifyIn(BaseModel):
    doc_id: str
    text: str


@app.get("/", response_class=HTMLResponse)
def home():
    page = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
            'content="width=device-width, initial-scale=1, viewport-fit=cover"><base href="/site/"></head>'
            f"<body>{page}</body></html>")


@app.get("/api/health")
def health():
    return {"ok": True}


@app.post("/api/analyze")
async def analyze(file: UploadFile | None = File(None), text: str | None = Form(None), title: str | None = Form(None)):
    if file is not None:
        raw = await file.read()
        if len(raw) > MAX_BYTES:
            raise HTTPException(413, "File too large (6 MB max).")
        if file.filename.lower().endswith(".pdf") or raw[:4] == b"%PDF":
            from pypdf import PdfReader
            text = "\n\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(raw)).pages)
        else:
            text = raw.decode("utf-8", errors="replace")
        title = title or pathlib.Path(file.filename).stem
    if not text or len(text.strip()) < 200:
        raise HTTPException(400, "Paste or upload the full text of a decision (at least a few paragraphs).")
    doc_id = "u" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:10]
    team = legible.team_source()
    if team:  # their pipeline runs its own event loop: keep it off the server's
        reg = await asyncio.to_thread(team.registry, text[:400_000], doc_id, True)
    else:
        md = legible.text_to_markdown(text[:80_000], title or "Uploaded decision")
        doc, reg = legible.analyze_markdown(md, doc_id)
    DOCS[doc_id] = {"registry": reg, "text": text}
    return JSONResponse({"id": doc_id, "label": "Your decision", "title": title or "Uploaded decision",
                         "case": {"source_url": None, "ecli": None}, "registry": reg, "draft": []})


@app.post("/api/verify")
def verify(body: VerifyIn):
    doc = DOCS.get(body.doc_id)
    if not doc:
        raise HTTPException(404, "Unknown decision: analyze it first.")
    return {"draft": legible.verify_text(body.text, doc["registry"])}


@app.post("/api/compare")
def compare(body: VerifyIn, model: str = "gpt-6.1-sol"):
    doc = DOCS.get(body.doc_id)
    if not doc:
        raise HTTPException(404, "Unknown decision: analyze it first.")
    from pipeline.audit import split_summary

    def one(s):
        r = oa.ask(model, oa.PROMPT.format(arret=doc["text"], sentence=s))
        head = r["answer"].strip().upper()
        return {"text": s, "model": r.get("model") or model, "answer": r["answer"],
                "verdict": "EXACTE" if head.startswith("EXACTE") else ("INEXACTE" if head.startswith("INEXACTE") else "?")}

    with ThreadPoolExecutor(max_workers=6) as pool:
        return {"model": model, "results": list(pool.map(one, split_summary(body.text)))}


app.mount("/site", StaticFiles(directory=ROOT / "site"), name="site")
