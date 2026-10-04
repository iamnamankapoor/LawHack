"""Turn an uploaded decision (PDF, .txt, pasted text) into plain text.

PDF extraction, the Légifrance print-furniture stripping and the Mistral OCR fallback come from the team's
first LawHack prototype.
"""
import base64
import json
import os
import re
import urllib.request

MIN_TEXT_CHARS = 200
OCR_MODEL = "mistral-ocr-latest"


class NoTextError(ValueError):
    pass


def from_upload(filename: str, data: bytes) -> str:
    if filename.lower().endswith(".pdf") or data[:5] == b"%PDF-":
        return from_pdf(data)
    return from_text_bytes(data)


def from_text_bytes(data: bytes) -> str:
    """A decision copied from Légifrance/Judilibre: UTF-8 (with or without BOM) or Windows-1252."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def from_pdf(data: bytes) -> str:
    import pymupdf  # optional dependency, only needed for PDF uploads

    try:
        with pymupdf.open(stream=data, filetype="pdf") as pdf:
            pages = [page.get_text("text") for page in pdf]
    except (pymupdf.FileDataError, RuntimeError) as error:
        raise NoTextError("Fichier PDF illisible ou corrompu.") from error
    if sum(len(p.strip()) for p in pages) < MIN_TEXT_CHARS:
        pages = ocr_pdf(data)  # e.g. "Microsoft Print to PDF" turns the text into drawn glyphs
    return "\n".join(strip_page_furniture(p) for p in pages)


def ocr_pdf(data: bytes) -> list[str]:
    """Pages of a PDF without a text layer, read by Mistral OCR (markdown, headings flattened)."""
    key = os.environ.get("MISTRAL_API_KEY")
    if not key:
        raise NoTextError("Ce PDF ne contient pas de texte (scan ou impression en image) et MISTRAL_API_KEY manque pour l'OCR.")
    body = {"model": os.environ.get("OCR_MODEL", OCR_MODEL),
            "document": {"type": "document_url", "document_url": "data:application/pdf;base64," + base64.b64encode(data).decode()}}
    base = os.environ.get("MISTRAL_BASE_URL", "https://api.mistral.ai/v1")
    req = urllib.request.Request(f"{base}/ocr", data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        pages = json.load(resp)["pages"]
    return [re.sub(r"(?m)^#+\s+", "", p["markdown"]) for p in pages]


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
    return "".join(line for line in text.splitlines(keepends=True) if not any(p.search(line.strip()) for p in _FURNITURE))
