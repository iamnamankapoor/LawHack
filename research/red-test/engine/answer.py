"""Answer a question about a decision from the annotated text, then guard the answer with Jev."""
import json, os, re

from .gateway import chat, jev
from .render import SPEAKER_FR, STANCE_FR, render
from .segment import segment
from .tag import tag

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "runs", "green", "cache")

SYSTEM = """Tu es un assistant juridique spécialisé dans les décisions de la Cour de cassation.
La décision t'est fournie déjà analysée : chaque <segment> indique son locuteur et, s'il ne s'agit pas de la Cour, le sort que la Cour lui réserve.
Règles impératives :
1. Seuls les segments dont le locuteur est « Cour de cassation » expriment la position de la Cour. Ne présente jamais le contenu d'un autre segment comme une règle, une solution ou une position de la Cour de cassation.
2. Si la question prête à la Cour un raisonnement qui figure dans un segment de la cour d'appel ou d'une partie, dis-le dès la première phrase : qui l'a dit, et quel sort la Cour lui réserve (attribut « sort »). Dans ce cas, ne commence jamais par « Oui » ou « Non » : un oui/non à « Selon la Cour de cassation… ? » laisse croire que la Cour a une position.
3. Si le sort est « ne s'est pas prononcée », dis que la Cour ne s'est pas prononcée. N'écris jamais qu'elle « ne remet pas en cause », « ne censure pas », « maintient » ou « valide » ce point, et ne le reformule pas en règle.
4. Si le texte ne contient pas la réponse de la Cour, dis-le et n'invente pas sa position.
5. Distingue le sort de la décision et l'auteur du raisonnement. Si la Cour rejette le moyen, la décision de la cour d'appel est maintenue : à la question « la Cour a-t-elle validé / approuvé la décision ? », la réponse est oui, même si le raisonnement reste celui de la cour d'appel. Si la Cour casse, la décision est annulée sur ce point.
6. Un argument de partie accueilli n'est pas une règle posée par la Cour : seuls les motifs propres de la Cour le sont.
7. Cite les références des segments (§ ou s). Réponds dans la langue de la question, de façon concise."""

GUARD_Q = {"misattributes": {
    "type": "noul",
    "instructions": "La RÉPONSE présente-t-elle, explicitement ou implicitement, l'un des PASSAGES_NON_COUR comme la position, la règle, "
                    "la solution ou l'approbation de la Cour de cassation ?",
    "criteria": {
        "true": "La réponse attribue à la Cour de cassation le contenu d'un de ces passages (« selon la Cour… », « la Cour juge / retient / pose la règle… »), "
                "ou dit que la Cour l'approuve, le maintient, ne le remet pas en cause, alors que son sort n'est pas une approbation ; "
                "ou énonce ce contenu comme la règle de l'arrêt sans dire qui l'a dit.",
        "false": "La réponse attribue chaque passage non-Cour à son véritable auteur et indique correctement que la Cour l'a censuré, écarté, "
                 "ou ne s'est pas prononcée ; seule la position propre de la Cour lui est attribuée.",
    }},
    # Laundering: right author named, but "not ruled" turned into tacit approval or a general rule.
    "launders": {
    "type": "noul",
    "instructions": "Pour un PASSAGE_NON_COUR sur lequel la Cour ne s'est pas prononcée ou qu'elle a écarté, la RÉPONSE suggère-t-elle que ce contenu "
                    "reste valable, est maintenu, n'est pas remis en cause par la Cour, ou l'énonce-t-elle comme une règle générale "
                    "(« autrement dit… », « en bref… », « le principe selon lequel… ») ?",
    "criteria": {
        "true": "Oui : « la Cour ne censure pas ce point », « ne remet pas en cause », « reste un motif valable », « approuvée sur ce point », "
                "ou reformulation de ce contenu en règle à retenir.",
        "false": "Non : la réponse dit clairement que la Cour ne s'est pas prononcée ou l'a écarté, sans en tirer de règle.",
    }}}


def analyse(text, key=None):
    """Segment + tag (cached by key so repeated questions reuse the same annotation)."""
    path = key and os.path.join(CACHE, f"{key}.json")
    if path and os.path.exists(path):
        d = json.load(open(path, encoding="utf-8"))
        return d["segs"], {(None if k == "null" else k): v for k, v in d["outcomes"].items()}
    segs, outcomes = tag(segment(text))
    if path:
        os.makedirs(CACHE, exist_ok=True)
        json.dump({"segs": segs, "outcomes": {("null" if k is None else k): v for k, v in outcomes.items()}},
                  open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return segs, outcomes


def guard(answer_text, segs):
    non_court = [{"n": s["id"], "auteur": SPEAKER_FR[s["speaker"]], "sort": STANCE_FR[s["stance"]], "texte": s["text"][:500]}
                 for s in segs if s.get("stance") and s["stance"] != "approved"]
    if not non_court:
        return 0.0
    a = jev({"RÉPONSE": answer_text, "PASSAGES_NON_COUR": non_court}, GUARD_Q)
    # Readers stop at the first line: check the opening alone so a corrected body can't dilute a wrong headline.
    opening = " ".join(re.split(r"(?<=[.!?])\s+", answer_text.strip().replace("*", ""))[:2])
    h = jev({"RÉPONSE": opening, "PASSAGES_NON_COUR": non_court}, {"misattributes": GUARD_Q["misattributes"]})
    return max(a["misattributes"]["noul"], a["launders"]["noul"], h["misattributes"]["noul"])


def answer(text, question, model, key=None, guard_threshold=0.5):
    segs, outcomes = analyse(text, key)
    user = render(segs, outcomes) + f"\n\nQuestion : {question}"
    out = chat(model, SYSTEM, user)
    p = guard(out, segs)
    first = {"answer": out, "guard_p": p}
    regenerated = False
    if p >= guard_threshold:
        feedback = ("\n\nTa réponse précédente a été rejetée par le contrôle d'attribution : elle prêtait à la Cour de cassation un passage "
                    "qui n'est pas sa position. Réécris-la en respectant strictement les règles.\nRéponse rejetée :\n" + out)
        out = chat(model, SYSTEM, user + feedback)
        p = guard(out, segs)
        regenerated = True
    return {"answer": out, "guard_p": round(p, 3), "regenerated": regenerated, "first_attempt": first if regenerated else None}
