import base64
import hashlib
import json
import os
import re
import urllib.request
from pathlib import Path

import pymupdf

from lawhack.schema import Document


def load_pdf(path: str | Path) -> Document:
    """Extract plain text from a clean (non-scanned) PDF, keeping page offsets."""
    path = Path(path)
    parts: list[str] = []
    pages: list[tuple[int, int]] = []
    offset = 0
    try:
        with pymupdf.open(path) as pdf:
            raw = [page.get_text("text") for page in pdf]
    except pymupdf.FileDataError as error:
        raise NoTextError("Fichier PDF illisible ou corrompu.") from error
    if sum(len(t.strip()) for t in raw) < MIN_TEXT_CHARS:
        raw = ocr_pdf(path)  # e.g. "Microsoft Print to PDF" turns the text into drawn glyphs
    for page_text in raw:
        text = strip_page_furniture(page_text)
        if not text.endswith("\n"):
            text += "\n"
        parts.append(text)
        pages.append((offset, offset + len(text)))
        offset += len(text)
    text = "".join(parts)
    return Document(id=_digest(text), text=text, pages=pages)


MIN_TEXT_CHARS = 200
OCR_MODEL = "mistral-ocr-latest"


class NoTextError(ValueError):
    pass


def ocr_pdf(path: str | Path) -> list[str]:
    """Pages of a PDF without a text layer, read by Mistral OCR (markdown, headings flattened)."""
    key = os.environ.get("MISTRAL_API_KEY")
    if not key:
        raise NoTextError("Ce PDF ne contient pas de texte (scan ou impression en image) et MISTRAL_API_KEY manque pour l'OCR.")
    data = base64.b64encode(Path(path).read_bytes()).decode()
    body = {"model": os.environ.get("OCR_MODEL", OCR_MODEL),
            "document": {"type": "document_url", "document_url": f"data:application/pdf;base64,{data}"}}
    base = os.environ.get("MISTRAL_BASE_URL", "https://api.mistral.ai/v1")
    req = urllib.request.Request(f"{base}/ocr", data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        pages = json.load(resp)["pages"]
    return [re.sub(r"(?m)^#+\s+", "", p["markdown"]) for p in pages]


def read_text_file(path: str | Path) -> Document:
    """A .txt decision copied from Légifrance/Judilibre: UTF-8 (with or without BOM) or Windows-1252."""
    data = Path(path).read_bytes()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")
    return load_text(text.replace("\r\n", "\n").replace("\r", "\n"))


def load_text(text: str, doc_id: str | None = None) -> Document:
    return Document(id=doc_id or _digest(text), text=text, pages=[(0, len(text))])


def page_of(doc: Document, offset: int) -> int | None:
    for i, (start, end) in enumerate(doc.pages, start=1):
        if start <= offset < end:
            return i
    return None


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


# Légifrance print headers/footers repeated on each page.
_FURNITURE = [
    re.compile(r"^\d{2}/\d{2}/\d{4} \d{2}:\d{2}$"),
    re.compile(r"^https?://"),
    re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4},? \d{1,2}:\d{2}(\s?[AP]M)?$", re.I),
    re.compile(r"^\d+/\d+$"),
    re.compile(r"- Légifrance$"),
]


def strip_page_furniture(text: str) -> str:
    text = re.sub(r"[ \t]+(ECLI:FR:)", r"\n\n\1", text)
    return "".join(
        line for line in text.splitlines(keepends=True) if not any(p.search(line.strip()) for p in _FURNITURE)
    )
