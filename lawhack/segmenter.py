"""Sentence segmentation that keeps quoted passages («…») intact."""

import re

from lawhack.schema import Block, Segment

_ABBREVIATIONS = {"m", "mme", "mmes", "mm", "me", "mes", "dr", "art", "n°", "no", "al", "cf", "p", "pp", "s", "ss", "etc"}
_UPPER_START = re.compile(r"[A-ZÀ-ÖØ-Þ«\"0-9]")


def split_sentences(text: str) -> list[tuple[int, int]]:
    """Return (start, end) spans of sentences inside `text`."""
    spans: list[tuple[int, int]] = []
    depth = 0
    start = 0
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "«":
            depth += 1
        elif ch == "»":
            depth = max(0, depth - 1)
            if depth == 0 and text[:i].rstrip().endswith((".", "!", "?")):
                k = i + 1
                while k < n and text[k].isspace():
                    k += 1
                if k > i + 1 and k < n and _UPPER_START.match(text[k]):
                    spans.append((start, i + 1))
                    start = k
                    i = k
                    continue
        elif ch in ".!?" and depth == 0:
            j = i + 1
            while j < n and text[j] in ".!?":
                j += 1
            if j < n and text[j].isspace():
                k = j
                while k < n and text[k].isspace():
                    k += 1
                if k < n and _UPPER_START.match(text[k]) and not _is_abbreviation(text, i):
                    spans.append((start, j))
                    start = k
                    i = k
                    continue
        i += 1
    if start < n and text[start:].strip():
        spans.append((start, n))
    return spans


def _is_abbreviation(text: str, dot: int) -> bool:
    k = dot
    while k > 0 and not text[k - 1].isspace() and text[k - 1] not in "(«":
        k -= 1
    word = text[k:dot].lower()
    if word in _ABBREVIATIONS or (len(word) == 1 and word.isalpha()):
        return True
    # Paragraph numbers such as "8." at the start of a block.
    return word.isdigit() and k == 0


def segment(blocks: list[Block]) -> list[Segment]:
    segments: list[Segment] = []
    for block in blocks:
        for s, e in split_sentences(block.text):
            segments.append(
                Segment(
                    id=f"S-{len(segments) + 1:03d}",
                    text=block.text[s:e].strip(),
                    start=block.start + s,
                    end=block.start + e,
                    block=block.index,
                    zone=block.zone,
                    heading=block.heading,
                    paragraph=block.paragraph,
                    page=block.page,
                )
            )
    return segments
