"""Vérifier un brouillon: check each sentence of a draft (e.g. a client note written by a legal AI) against the
labelled decision. Idea from the team's first Legible prototype, rebuilt on our speaker + stance labels."""
import re
from concurrent.futures import ThreadPoolExecutor

from .answer import SYSTEM, guard
from .gateway import chat, jev
from .render import SPEAKER_FR, ref, render

SUPPORT_Q = "Quel paragraphe de la décision cette PHRASE d'un brouillon reprend-elle ou résume-t-elle ?"


def sentences(draft):
    parts = re.split(r"(?<=[.!?»])\s+(?=[A-ZÀ-Ý«])", draft.strip())
    return [p.strip() for p in parts if len(p.strip()) >= 25]


def _support(sentence, segs):
    body = [s for s in segs if s["section"] in ("body", "annexe")][:250]
    criteria = {ref(s): s["text"][:400] for s in body}
    a = jev({"PHRASE": sentence}, {"support": {"type": "choice", "instructions": SUPPORT_Q, "criteria": criteria}})["support"]
    seg = next(s for s in body if ref(s) == a["choice"])
    return seg, a.get("probabilities", {}).get(a["choice"], 0)


def _rewrite(sentence, segs, outcomes, model):
    prompt = (render(segs, outcomes) + "\n\nPhrase d'un brouillon qui attribue mal un passage :\n« " + sentence + " »\n\n"
              "Réécris cette seule phrase pour qu'elle attribue chaque idée à son véritable auteur et indique le sort que la Cour "
              "lui réserve, avec la référence du paragraphe. Réponds uniquement par la phrase réécrite.")
    return chat(model, SYSTEM, prompt).strip().strip("«» ")


SHORT = {"quashed": "censuré par la Cour", "approved": "approuvé par la Cour", "approved_restated_only": "approuvé pour le seul motif repris par la Cour",
         "not_ruled": "non tranché par la Cour", "argument_rejected": "argument écarté par la Cour", "argument_accepted": "argument accueilli",
         "overruled": "jurisprudence abandonnée par la Cour", "cited_precedent": "jurisprudence citée", "no_court_answer_in_text": "réponse de la Cour absente"}


def check_sentence(sentence, segs, outcomes, model):
    seg, support_p = _support(sentence, segs)
    p = guard(sentence, segs)
    if seg["speaker"] == "court" and support_p >= 0.5:
        # The sentence rests on the Court's own words: wording shared with a party's argument is not a misattribution.
        verdict = "conforme" if p < 0.8 else "a_verifier"
    else:
        verdict = "a_corriger" if p >= 0.5 else ("a_verifier" if p >= 0.25 or support_p < 0.5 else "conforme")
    if verdict == "a_corriger":
        reason = f"Attribué à la Cour de cassation ; en réalité {SPEAKER_FR[seg['speaker']]}" + (
            f", {SHORT[seg['stance']]}" if seg.get("stance") else "") + f" ({ref(seg)})."
    elif verdict == "a_verifier":
        reason = "Attribution incertaine : à relire avec le paragraphe source."
    else:
        reason = "Conforme au texte de la décision."
    return {"sentence": sentence, "verdict": verdict, "risk": round(p, 2), "reason": reason,
            "source": {"ref": ref(seg), "id": seg["id"], "speaker": seg["speaker"], "stance": seg.get("stance"),
                       "text": seg["text"], "confidence": round(support_p, 2)},
            "rewrite": _rewrite(sentence, segs, outcomes, model) if verdict == "a_corriger" else None}


def check(draft, segs, outcomes, model="mistral/mistral-large-3", workers=6):
    with ThreadPoolExecutor(workers) as ex:
        return list(ex.map(lambda s: check_sentence(s, segs, outcomes, model), sentences(draft)))
