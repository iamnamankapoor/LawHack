"""« Ce que la Cour a jugé » — the Court's own sentences, quoted verbatim per ground. No paraphrase, no LLM."""
import re

from .solution import detect_solution

# Sentences in which the Court states its rule or its ruling (as opposed to reciting texts or facts).
DECISIVE = re.compile(
    r"^(\d+\. )?(Il (résulte|en résulte|s'en déduit|se déduit)|En statuant ainsi|Qu'en (statuant|se déterminant) ainsi|"
    r"De ces constatations|C'est à tort|Le moyen (n'est|est)|Ainsi, le moyen|L'ensemble de ces considérations|"
    r"En application de l'article 1014|Le moyen de cassation annexé|.*juger désormais|.*n'encourt (cependant )?pas la censure)")
PARA = re.compile(r"^(\d{1,3})\. ")


def ref(seg):
    m = PARA.match(seg["text"])
    return f"§{m.group(1)}" if m else f"s{seg['id']}"


def holdings(segs, outcomes):
    """[{ground, outcome, quotes:[{ref, text}], not_ruled:[ref...], overruled:[ref...]}] + overall solution."""
    dispositif = "\n".join(s["text"] for s in segs if s["section"] == "dispositif")
    grounds = []
    for key, outcome in outcomes.items():
        mine = [s for s in segs if s["section"] == "body" and (key is None or _key(s["ground"]) == key)]
        court = [s for s in mine if s["speaker"] == "court"]
        quotes = [s for s in court if DECISIVE.match(s["text"])] or court[-2:]
        grounds.append({
            "ground": next((s["ground"] for s in mine if s["ground"]), None) or "Moyen",
            "outcome": outcome,
            "quotes": [{"ref": ref(s), "text": PARA.sub("", s["text"])} for s in quotes],
            "not_ruled": [ref(s) for s in mine if s.get("stance") == "not_ruled" and ref(s)],
            "overruled": [ref(s) for s in segs if s.get("stance") == "overruled" and ref(s)],
        })
    return {"solution": detect_solution(dispositif).value, "dispositif": dispositif, "grounds": grounds}


def _key(ground):
    from .tag import _ground_key
    return _ground_key(ground)
