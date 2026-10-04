"""Answer a question about a decision from the annotated text, then guard the answer with Jev."""
import json, os, re

from .gateway import chat, jev
from .render import SPEAKER_FR, STANCE_FR, render
from .segment import segment
from .solution import Solution, detect_solution
from .tag import tag

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.environ.get("LEGIBLE_CACHE", os.path.join(ROOT, ".cache", "decisions"))

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


_SAYS_CASSE = re.compile(r"\bla Cour[^.;]{0,60}\b(casse|a cassé|annule|a annulé|censure|a censuré)\b", re.I)
_SAYS_REJET = re.compile(r"\bla Cour[^.;]{0,60}\b(rejette|a rejeté)\s+(le|les)\s+pourvois?\b", re.I)
_NEGATION = re.compile(r"\bn['’e]\s?\w+ (pas|point)\b|\bne (pas|point)\b", re.I)


def contradicts_outcome(answer_text, segs):
    """Outcome check (from the team's first prototype): the answer states an outcome the dispositif does not have.
    Only applied to whole rejections and whole cassations, where one outcome excludes the other."""
    solution = detect_solution("\n".join(s["text"] for s in segs if s["section"] == "dispositif"))
    for sentence in re.split(r"(?<=[.!?])\s+", answer_text):
        if _NEGATION.search(sentence):
            continue
        if solution is Solution.REJET and _SAYS_CASSE.search(sentence):
            return "La Cour rejette le pourvoi : elle ne casse pas l'arrêt."
        if solution is Solution.CASSATION and _SAYS_REJET.search(sentence):
            return "La Cour casse l'arrêt en toutes ses dispositions : elle ne rejette pas le pourvoi."
    return None


def references(answer_text, segs):
    """Paragraphs cited in the answer (§ n or s n), with their speaker and the Court's stance, for linking in the UI."""
    by_ref = {}
    for s in segs:
        m = re.match(r"^(\d{1,3})\. ", s["text"])
        by_ref[f"§{m.group(1)}" if m else f"s{s['id']}"] = s
    cited = re.findall(r"§\s?(\d{1,3})|\bs(\d{1,3})\b", answer_text)
    out, seen = [], set()
    for para, seg_id in cited:
        key = f"§{para}" if para else f"s{seg_id}"
        if key in by_ref and key not in seen:
            seen.add(key)
            s = by_ref[key]
            out.append({"ref": key, "id": s["id"], "speaker": s["speaker"], "stance": s.get("stance")})
    return out


def answer(text, question, model, key=None, guard_threshold=0.5):
    segs, outcomes = analyse(text, key)
    user = render(segs, outcomes) + f"\n\nQuestion : {question}"
    out = chat(model, SYSTEM, user)
    p, wrong_outcome = guard(out, segs), contradicts_outcome(out, segs)
    first = {"answer": out, "guard_p": p, "outcome_error": wrong_outcome}
    regenerated = False
    if p >= guard_threshold or wrong_outcome:
        reason = ("elle prêtait à la Cour de cassation un passage qui n'est pas sa position" if p >= guard_threshold
                  else f"elle contredit le dispositif ({wrong_outcome})")
        feedback = (f"\n\nTa réponse précédente a été rejetée par le contrôle : {reason}. "
                    "Réécris-la en respectant strictement les règles.\nRéponse rejetée :\n" + out)
        out = chat(model, SYSTEM, user + feedback)
        p, wrong_outcome = guard(out, segs), contradicts_outcome(out, segs)
        regenerated = True
    return {"answer": out, "guard_p": round(p, 3), "outcome_error": wrong_outcome, "regenerated": regenerated,
            "references": references(out, segs), "first_attempt": first if regenerated else None}
