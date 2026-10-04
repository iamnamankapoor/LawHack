import hashlib
import re
from pathlib import Path

import pymupdf

from lawhack.schema import Document


def load_pdf(path: str | Path) -> Document:
    """Extract plain text from a clean (non-scanned) PDF, keeping page offsets."""
    path = Path(path)
    parts: list[str] = []
    pages: list[tuple[int, int]] = []
    offset = 0
    with pymupdf.open(path) as pdf:
        for page in pdf:
            text = strip_page_furniture(page.get_text("text"))
            if not text.endswith("\n"):
                text += "\n"
            parts.append(text)
            pages.append((offset, offset + len(text)))
            offset += len(text)
    text = "".join(parts)
    return Document(id=_digest(text), text=text, pages=pages)


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
    re.compile(r"^https?://\S+$"),
    re.compile(r"^\d+/\d+$"),
    re.compile(r"- Légifrance$"),
]


def strip_page_furniture(text: str) -> str:
    text = re.sub(r"[ \t]+(ECLI:FR:)", r"\n\n\1", text)
    return "".join(
        line for line in text.splitlines(keepends=True) if not any(p.search(line.strip()) for p in _FURNITURE)
    )
