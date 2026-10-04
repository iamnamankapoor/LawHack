"""The team's System 1 (the `lawhack` package at the repo root) as Legible's registry source.

Their entries carry speaker / type / status as {value, probabilities, confidence}. Legible keeps their
speaker and type and recomputes its own statuses (CENSURE, APPROUVE, CITE…) with `legible.add_statuses`,
so the verdict rules are unchanged. With `rules=True`, Legible's drafting rules (citations of former case
law, « l'arrêt retient », moyens) override the model where they apply, as they do for the placeholder.
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent
REPO = ROOT.parent if (ROOT.parent / "lawhack").is_dir() else ROOT / "LawHack"
sys.path.insert(0, str(REPO))

import legible  # noqa: E402  (loads .env: TYPESAFE_API_KEY for Jev)
from lawhack import pipeline  # noqa: E402
from lawhack.ingest import load_text  # noqa: E402

pipeline.CACHE_DIR = ROOT / "cache" / "team"
CANONICAL = {"expose": "Faits et procédure", "moyens": "Énoncé du moyen", "motivations": "Réponse de la Cour"}
SECTION = {"introduction": "En-tête", **CANONICAL, "dispositif": "Dispositif", "metadonnees": "Métadonnées"}


def plain_text(md):
    """Legible's Markdown decision → the plain Légifrance layout the team's zoning expects."""
    body = md.split("\n---", 2)[-1] if md.startswith("---") else md
    out = []
    for line in body.splitlines():
        if line.startswith("<!--"):
            continue
        if line.startswith("#"):
            heading = line.lstrip("#").strip()
            if heading.lower().startswith("portée"):
                out.append(heading)
            elif legible.zone_of(heading) in CANONICAL:
                out.append(CANONICAL[legible.zone_of(heading)])
            continue  # Préambule, Entête, Dispositif: the text itself carries the zone
        out.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip() + "\n"


def registry(text, doc_id=None, rules=False):
    reg, _ = pipeline.analyse(load_text(text, doc_id))
    entries = []
    for e in reg.entries:
        entry = {"id": e.id, "sid": e.id, "paragraph": e.paragraph, "block": e.block, "zone": e.zone.value,
                 "section": e.heading or SECTION[e.zone.value], "page": e.page, "text": e.text,
                 "speaker": e.speaker.value, "probabilities": e.speaker.probabilities, "confidence": e.speaker.confidence,
                 "type": e.type.value, "type_confidence": e.type.confidence, "team_status": e.status.value,
                 "source": "team:" + e.source, "chain": [c.value for c in e.chain]}
        if rules:
            rule = legible.rule_label({"text": e.text}, e.zone.value)
            if rule and (rule["speaker"], rule["type"]) != (entry["speaker"], entry["type"]):
                entry.update(rule, team_speaker=entry["speaker"], source="rule over team",
                             confidence=max(entry["confidence"], 0.95))
        entries.append(entry)
    return legible.add_statuses(entries)
