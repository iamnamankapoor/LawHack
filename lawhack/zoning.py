"""Rule-based zoning of Cour de cassation decisions from their standard headings."""

import re

from lawhack.ingest import page_of
from lawhack.schema import Block, Document, Zone

_NUMBERED = re.compile(r"^(\d{1,3})\.\s+\S")

# Heading pattern → zone that starts at this heading. Order matters (first match wins).
_HEADINGS: list[tuple[re.Pattern[str], Zone]] = [
    (re.compile(r"^faits et proc[ée]dure\b", re.I), Zone.EXPOSE),
    (re.compile(r"^expos[ée] (du|des) griefs?\b", re.I), Zone.MOYENS),
    (re.compile(r"^[ée]nonc[ée] d(u|es) moyens?\b", re.I), Zone.MOYENS),
    (re.compile(r"^[ée]nonc[ée] de la demande d'avis\b", re.I), Zone.MOYENS),
    (re.compile(r"^r[ée]ponse de la cour\b", re.I), Zone.MOTIVATIONS),
    (re.compile(r"^examen de la demande d'avis\b", re.I), Zone.MOTIVATIONS),
    (re.compile(r"^port[ée]e et cons[ée]quences de la cassation\b", re.I), Zone.MOTIVATIONS),
    (re.compile(r"^recevabilit[ée]\b", re.I), Zone.MOTIVATIONS),
    (re.compile(r"^examen d(u|es) (moyens?|griefs?)\b", re.I), Zone.MOTIVATIONS),
    (re.compile(r"^(et |mais )?sur (le|les|la|l')\s?[^.;]{0,80}?\b(moyens?|branches?|pourvois?|griefs?)\b", re.I), Zone.MOTIVATIONS),
    (re.compile(r"^[ée]nonc[ée] de la question prioritaire\b", re.I), Zone.MOYENS),
    (re.compile(r"^examen de la question prioritaire\b", re.I), Zone.MOTIVATIONS),
    (re.compile(r"^en cons[ée]quence\s*:?$", re.I), Zone.DISPOSITIF),
    (re.compile(r"^(par|pour) ces motifs\b", re.I), Zone.DISPOSITIF),
    (re.compile(r"^en cons[ée]quence,? la cour\b|^est d'avis que\b", re.I), Zone.DISPOSITIF),  # demandes d'avis
    (re.compile(r"^moyens? annexes?\b", re.I), Zone.MOYENS),
    (re.compile(r"^ECLI\s*:", re.I), Zone.METADONNEES),
]

# Opening words that change the zone but are body text, not headings
# (pre-2019 "attendu" style decisions have no headings).
_OPENERS: list[tuple[re.Pattern[str], Zone]] = [
    (re.compile(r"^moyens? produits? par\b", re.I), Zone.MOYENS),
    (re.compile(r"^attendu,? selon (l'arr[êe]t attaqu[ée]|le jugement attaqu[ée])", re.I), Zone.EXPOSE),
    (re.compile(r"^attendu que .{0,200}?\bfai(t|sait|saient|t les mêmes) griefs?\b", re.I), Zone.MOYENS),
    (re.compile(r"^(?:\d{1,3}\.\s+)?(?=[^.]{1,120}\b(?:fait|font) grief à l'arr[êe]t\b)[^.]{1,120}?\b(?<!qui )(?:fait|font) grief à l'arr[êe]t\b", re.I), Zone.MOYENS),
    (re.compile(r"^mais attendu\b", re.I), Zone.MOTIVATIONS),
    (re.compile(r"^vu (l'article|les articles)\b", re.I), Zone.MOTIVATIONS),
    (re.compile(r"^(REJETTE|CASSE (ET|et) ANNULE|DÉCLARE|DECLARE|DIT N'Y AVOIR LIEU|RENVOIE)\b"), Zone.DISPOSITIF),
]


# « 1°) alors que… », « 2°/ qu'en statuant… »: a branch of the ground of appeal, i.e. the party speaking.
_BRANCH = re.compile(r"^\d{1,2}\s?°\s?[)/-]?\s*(alors|que |qu'|et |en |de |subsidiairement)", re.I)


def _heading_zone(line: str) -> Zone | None:
    for pattern, zone in _HEADINGS + _OPENERS:
        if pattern.search(line):
            return zone
    return None


def _is_heading(line: str) -> bool:
    if _NUMBERED.match(line) or _heading_zone(line) is None or any(p.search(line) for p, _ in _OPENERS):
        return False
    # "PAR CES MOTIFS, la Cour :" is both the heading and the first dispositif block.
    return len(line) < 120 and _heading_zone(line) is not Zone.DISPOSITIF


def zone_blocks(doc: Document) -> list[Block]:
    """Split the decision into paragraph blocks and assign each a zone using the headings."""
    blocks: list[Block] = []
    zone = Zone.INTRODUCTION
    heading: str | None = None
    annexed = False
    for start, end, line in _paragraphs(doc.text):
        detected = _heading_zone(line)
        if annexed and detected is not Zone.METADONNEES:
            detected = None  # annexed grounds quote the arrêt attaqué (« Mais attendu… »): still the party's text
        if zone is Zone.DISPOSITIF and detected is Zone.MOYENS:
            annexed = True
        if zone is Zone.DISPOSITIF and detected in (Zone.EXPOSE, Zone.MOTIVATIONS) and not _is_heading(line):
            detected = None  # "Vu l'article 700…" inside the dispositif
        if detected is None and zone is Zone.MOTIVATIONS and _BRANCH.match(line):
            detected = Zone.MOYENS
        if detected is not None:
            zone = detected
        if _is_heading(line):
            heading = line
            continue
        if detected is Zone.DISPOSITIF:
            heading = "Dispositif"
        if blocks and line[:1].islower() and blocks[-1].zone is zone and blocks[-1].heading == heading:
            # Paragraph cut by a page break (print header in between): glue it back.
            prev = blocks[-1]
            blocks[-1] = prev.model_copy(update={"text": f"{prev.text} {line}", "end": end})
            continue
        match = _NUMBERED.match(line)
        blocks.append(
            Block(
                index=len(blocks),
                text=line,
                start=start,
                end=end,
                zone=zone,
                heading=heading,
                paragraph=int(match.group(1)) if match else None,
                page=page_of(doc, start),
            )
        )
    return blocks


_GLUED_HEADING = re.compile(r"(?<=[.;]) +(?=MOYENS? ANNEXES?\b)")


def _split_glued(lines: list[str]) -> list[str]:
    """Judilibre texts glue « MOYENS ANNEXES » to the last line of the dispositif: split it off."""
    out = []
    for line in lines:
        parts = _GLUED_HEADING.split(line)
        out += [part + " " for part in parts[:-1]] + [parts[-1]]
    return out


def _paragraphs(text: str):
    """Yield (start, end, text) for blank-line separated paragraphs, whitespace-normalised.

    PDF extraction hard-wraps lines; consecutive non-empty lines are joined unless the next
    line starts a numbered paragraph or is a heading.
    """
    current: list[tuple[int, int, str]] = []

    def flush():
        if current:
            s, e = current[0][0], current[-1][1]
            joined = " ".join(t for _, _, t in current)
            current.clear()
            return s, e, joined
        return None

    pos = 0
    for raw in _split_glued(text.splitlines(keepends=True)):
        stripped = raw.strip()
        lead = len(raw) - len(raw.lstrip())
        if not stripped:
            out = flush()
            if out:
                yield out
        else:
            if current and (_NUMBERED.match(stripped) or _heading_zone(stripped) is not None):
                out = flush()
                if out:
                    yield out
            current.append((pos + lead, pos + lead + len(stripped), stripped))
            if _heading_zone(stripped) is not None and (_is_heading(stripped) or stripped.endswith(":")):
                out = flush()
                if out:
                    yield out
        pos += len(raw)
    out = flush()
    if out:
        yield out
