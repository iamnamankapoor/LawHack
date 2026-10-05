"""Split a Cour de cassation decision into ordered segments with section and ground.

Handles the post-2019 numbered style ("1. …", headings like "Réponse de la Cour") and the pre-2019
"Attendu que" style. Also accepts an excerpt (no header / dispositif): everything becomes body.
"""
import re

BODY_START = re.compile(r"a rendu (le présent arrêt|la présente décision)|a rendu l'arrêt suivant", re.I)
DISPOSITIF = re.compile(r"^(PAR CES MOTIFS|EN CONSÉQUENCE, la Cour)")
END_DISPOSITIF = re.compile(r"(Ainsi (fait et jugé|décidé) par la Cour de cassation.*?)(?=MOYENS? ANNEXES?|$)", re.S)
ANNEX = re.compile(r"MOYENS? ANNEXES? (à la présente décision|au présent arrêt)")
SUMMARY = re.compile(r"^Analyse$")
GROUND = re.compile(r"^(Mais |Et )?[Ss]ur (le|la|les) (premier|deuxième|second|troisième|quatrième|cinquième|moyen|moyens|branche)")
HEADINGS = ("Faits et procédure", "Examen des moyens", "Enoncé du moyen", "Énoncé du moyen", "Réponse de la Cour",
            "Désistement partiel", "Mise hors de cause", "Recevabilité", "Examen du moyen")
NUMBERED = re.compile(r"^\d{1,3}\. ")
CONTINUATION = re.compile(r"^(- |« ?\d°|\d° ?[-/)]|[1-9]°/|ALORS|AUX MOTIFS|ET AUX MOTIFS|QUE |qu')")


def _is_heading(line):
    return (line in HEADINGS or GROUND.match(line)) and len(line) < 160 and not NUMBERED.match(line)


def segment(text):
    """Return list of dicts: {id, text, section, ground, heading}."""
    lines = [l.strip() for l in text.replace("\r", "").split("\n")]
    lines = [l for l in lines if l]
    start = next((i + 1 for i, l in enumerate(lines) if BODY_START.search(l)), 0)
    # For the Légifrance layout the formal header ("ARRÊT DE LA COUR…", parties, rapporteur…) follows the first
    # "a rendu" line; skip to the last "a rendu" occurrence when there are several.
    starts = [i + 1 for i, l in enumerate(lines) if BODY_START.search(l)]
    if len(starts) > 1:
        start = starts[-1]
    segs, section, ground, heading = [], "body", None, None
    numbered_style = any(NUMBERED.match(l) for l in lines[start:])

    def add(t, sec):
        segs.append({"id": len(segs) + 1, "text": t, "section": sec, "ground": ground, "heading": heading})

    for line in lines[start:]:
        if SUMMARY.match(line):
            section = "sommaire"
            continue
        if section == "sommaire":
            if line not in ("Titrages et résumés",):
                add(line, "sommaire")
            continue
        if DISPOSITIF.match(line):
            section, heading = "dispositif", None
        if section == "dispositif":
            m = ANNEX.search(line)
            if m:
                before, after = line[:m.start()].strip(), line[m.start():].strip()
                if before:
                    add(before, "dispositif")
                section, ground, heading = "annexe", None, None
                add(after, "annexe")
                continue
            add(line, "dispositif")
            continue
        if ANNEX.search(line) and section != "annexe":
            section, ground, heading = "annexe", None, None
        if section == "annexe":
            if re.match(r"^(PREMIER|SECOND|DEUXIÈME|TROISIÈME|QUATRIÈME) MOYEN DE CASSATION$", line):
                ground = line
            add(line, "annexe")
            continue
        if _is_heading(line):
            if GROUND.match(line):
                ground, heading = line.rstrip(" :"), None
            else:
                heading = line
            continue
        joins_previous = segs and segs[-1]["section"] == "body" and (
            CONTINUATION.match(line) or (numbered_style and not NUMBERED.match(line) and not line.startswith("Vu ")
                                         and not segs[-1]["text"].startswith("Vu ")))
        if joins_previous:
            segs[-1]["text"] += "\n" + line
        else:
            add(line, "body")
    return segs


if __name__ == "__main__":
    import sys
    from engine.fetch import fetch
    for s in segment(fetch(sys.argv[1])["text"]):
        print(f'{s["id"]:>3} [{s["section"]}|{s["heading"] or "-"}|{(s["ground"] or "-")[:30]}] {s["text"][:110]!r}')
