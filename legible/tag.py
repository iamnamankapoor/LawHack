"""Tag each segment with WHO is speaking and the Court's STANCE on it, using Jev typed questions."""
import re
from concurrent.futures import ThreadPoolExecutor

from .gateway import jev

import os

# Low confidence: ask Jev again with the options in reverse order and average (cancels first-option bias);
# only if still unsure does the gateway re-run the question on a cheap LLM.
CONFIDENT = 0.8
FALLBACK = os.environ.get("LEGIBLE_FALLBACK_MODEL", "mistral/mistral-small")

SPEAKER_Q = {"speaker": {
    "type": "choice",
    "instructions": "Dans le passage CIBLE d'une décision de la Cour de cassation, de qui est le raisonnement ou la position exprimée ?",
    "criteria": {
        "court": "La Cour de cassation parle en son nom : elle vise un texte, énonce une règle (« Il résulte de ce texte que »), "
                 "juge ou censure (« En statuant ainsi, la cour d'appel a violé », « a pu déduire », « a légalement justifié »), "
                 "ou constate qu'un moyen n'est pas de nature à entraîner la cassation.",
        "cour_appel": "La Cour de cassation rapporte le raisonnement de l'arrêt attaqué / de la cour d'appel : « Pour débouter…, l'arrêt retient que », "
                      "et les phrases de continuation « Il retient », « Il relève », « Il ajoute », « Il en déduit » où « Il » désigne l'arrêt ; "
                      "ou, dans un moyen annexé, les motifs cités après « AUX MOTIFS QUE ».",
        "partie": "Argumentation d'une partie (moyen de cassation) : « fait grief à l'arrêt », « alors que », « ALORS QUE », branches 1°/ 2°/, "
                  "ou tout passage d'un moyen annexé produit par l'avocat d'une partie.",
        "faits": "Exposé neutre des faits et de la procédure (« Selon l'arrêt attaqué, … », désistement, donner acte).",
        "jurisprudence_anterieure": "La Cour de cassation rappelle sa propre jurisprudence antérieure, avec une référence d'arrêt "
                                    "(« La Cour de cassation a décidé / jugé que … (2e Civ., …, pourvoi n° …) »), notamment pour la reconsidérer ou l'abandonner.",
    }}}

# Stance is derived from two atomic questions: how the Court disposed of the ground, and whether its own
# reasoning addresses this specific passage. A single "stance" choice confused "decision quashed" with
# "this sentence quashed" (C2 §8).
OUTCOME_Q = {"outcome": {
    "type": "choice",
    "instructions": "Comment la Cour de cassation statue-t-elle sur ce moyen, d'après ses motifs propres et le dispositif ?",
    "criteria": {
        "cassation": "La Cour accueille le moyen et casse l'arrêt sur ce point (« En statuant ainsi, la cour d'appel a violé / a privé sa décision de base légale »).",
        "rejet": "La Cour écarte le moyen : « Mais attendu que », « le moyen n'est pas fondé », « a pu déduire », « a légalement justifié », "
                 "ou moyen « manifestement pas de nature à entraîner la cassation » (art. 1014 CPC).",
        "non_examine": "La Cour ne statue pas sur ce moyen (« sans qu'il y ait lieu de statuer sur »).",
    }}}

ADDRESSED_Q = {"addressed": {
    "type": "noul",
    "instructions": "Les motifs propres de la Cour de cassation se prononcent-ils expressément sur le point précis affirmé dans le passage CIBLE "
                    "(le même argument ou la même conclusion), et pas seulement sur un autre aspect de l'affaire ?",
    "criteria": {
        "true": "La Cour reprend ce point précis et dit s'il est juste ou erroné (elle contredit ou valide exactement cette affirmation ou cette conclusion).",
        "false": "La Cour statue sur un autre point ; ce passage n'est ni repris ni discuté par la Cour, même si la décision qui le contient est cassée.",
    }}}

STANCE = {  # (speaker, ground outcome, addressed) -> stance
    ("cour_appel", "cassation", True): "quashed", ("cour_appel", "rejet", True): "approved",
    ("partie", "cassation", True): "argument_accepted", ("partie", "rejet", True): "argument_rejected",
    ("partie", "rejet", False): "argument_rejected",
}


def _reversed(questions, key):
    spec = dict(questions[key], criteria=dict(reversed(list(questions[key]["criteria"].items()))))
    return {key: spec}


def _choose(state, questions, key):
    """(choice, probability) — Jev, then Jev with options reversed, then a cheap LLM as last resort."""
    a = jev(state, questions)[key]
    probs = a.get("probabilities", {})
    if probs.get(a["choice"], 0) >= CONFIDENT:
        return a["choice"], probs[a["choice"]]
    b = jev(state, _reversed(questions, key))[key].get("probabilities", {})
    avg = {k: (probs.get(k, 0) + b.get(k, 0)) / 2 for k in questions[key]["criteria"]}
    best = max(avg, key=avg.get)
    if avg[best] >= 0.5:
        return best, avg[best]
    c = jev(state, questions, fallback_model=FALLBACK, confidence_below=1.0)[key]
    return c["choice"], avg.get(c["choice"], 0)


def _speaker(segs, i):
    s = segs[i]
    if s["section"] in ("dispositif", "sommaire"):
        return {"speaker": "court", "p": 1.0, "rule": True}
    # Only the Court censures: "En statuant ainsi, … la cour d'appel a violé" is its voice even when it restates an argument
    if re.match(r"^(\d+\. )?(En|Qu'en) (statuant|se déterminant) ainsi", s["text"]):
        return {"speaker": "court", "p": 1.0, "rule": True}
    before = "\n".join(x["text"] for x in segs[max(0, i - 4):i])[-2500:]
    state = {"section": s["section"], "titre": s["heading"] or "", "moyen": s["ground"] or "",
             "contexte_precedent": before, "CIBLE": s["text"]}
    choice, p = _choose(state, SPEAKER_Q, "speaker")
    return {"speaker": choice, "p": round(p, 3)}


def _outcome(court, dispositif):
    return _choose({"motifs_propres_de_la_Cour_sur_ce_moyen": court[-6000:], "dispositif": dispositif[-3000:]},
                   OUTCOME_Q, "outcome")[0]


def _stance(seg, court, outcome):
    if not court:
        return {"stance": "no_court_answer_in_text", "addressed_p": None}
    if seg.get("censured_by_ainsi") and outcome == "cassation":
        return {"stance": "quashed", "addressed_p": 1.0}
    if seg.get("approved_by_deduction") and outcome == "rejet":
        return {"stance": "approved", "addressed_p": 1.0}
    p = jev({"CIBLE": seg["text"], "motifs_propres_de_la_Cour": court[-6000:]}, ADDRESSED_Q)["addressed"]["noul"]
    return {"stance": STANCE.get((seg["speaker"], outcome, p >= 0.5), "not_ruled"), "addressed_p": round(p, 2)}


def _ground_key(ground):
    """Map body ground headings and annex headings onto a common key (premier/second/…)."""
    if not ground:
        return None
    g = ground.lower()
    for k in ("premier", "second", "deuxième", "troisième", "quatrième", "relevé d'office"):
        if k in g:
            return "second" if k == "deuxième" else k
    return g


def tag(segs, workers=8):
    with ThreadPoolExecutor(workers) as ex:
        for s, r in zip(segs, ex.map(lambda i: _speaker(segs, i), range(len(segs)))):
            s.update(r)
    court_by_ground, dispositif = {}, "\n".join(s["text"] for s in segs if s["section"] == "dispositif")
    for s in segs:
        if s["speaker"] == "court" and s["section"] == "body":
            k = _ground_key(s["ground"])
            court_by_ground[k] = court_by_ground.get(k, "") + s["text"] + "\n"
    # With a single ground (or none), the Court's reasoning answers every passage, wherever it sits.
    if len(court_by_ground) == 1:
        court_by_ground = {None: next(iter(court_by_ground.values()))}
    court_for = lambda s: court_by_ground.get(_ground_key(s["ground"])) or court_by_ground.get(None, "")
    with ThreadPoolExecutor(workers) as ex:
        outcomes = dict(zip(court_by_ground, ex.map(lambda k: _outcome(court_by_ground[k], dispositif), court_by_ground)))
    # Drafting convention: "En statuant ainsi" / "Qu'en se déterminant ainsi" censures the lower-court reasoning
    # recited immediately before it, so that passage is addressed by definition.
    for prev, s in zip(segs, segs[1:]):
        if s["speaker"] == "court" and re.match(r"^(\d+\. )?(En|Qu'en) (statuant|se déterminant) ainsi", s["text"]) \
                and prev["speaker"] == "cour_appel":
            prev["censured_by_ainsi"] = True
    # "De ces constatations (et énonciations), la cour d'appel a pu / a exactement déduit": approval of the lower-court
    # reasoning recited in the consecutive passages just before it.
    for i, s in enumerate(segs):
        if s["speaker"] == "court" and re.match(r"^(\d+\. )?De ces (constatations|énonciations)", s["text"]) \
                and re.search(r"a (pu|exactement|justement|souverainement) (déduire|déduit|retenir|retenu)|à bon droit", s["text"]):
            j = i - 1
            while j >= 0 and segs[j]["speaker"] == "cour_appel":
                segs[j]["approved_by_deduction"] = True
                j -= 1
    # The Court's own earlier case law: overruled if the decision announces a change, otherwise merely cited.
    overruling = any(re.search(r"reconsidérer|juger désormais|revient sur|abandonne", s["text"]) for s in segs if s["speaker"] == "court")
    for s in segs:
        if s["speaker"] == "jurisprudence_anterieure":
            s.update(stance="overruled" if overruling else "cited_precedent", addressed_p=None)
    todo = [s for s in segs if s["speaker"] in ("cour_appel", "partie")]
    with ThreadPoolExecutor(workers) as ex:
        for s, r in zip(todo, ex.map(lambda s: _stance(s, court_for(s), outcomes.get(
                _ground_key(s["ground"]) if _ground_key(s["ground"]) in outcomes else None)), todo)):
            s.update(r, ground_outcome=outcomes.get(_ground_key(s["ground"])) or outcomes.get(None))
    # "par ce seul motif": the Court approves only the reasoning it restates itself; the lower court's other
    # motifs on that ground become surplus (surabondants) and are not ruled on.
    for s in todo:
        if s.get("stance") == "approved" and re.search(r"par (ce seul motif|ces seuls motifs)", court_for(s)):
            s["stance"] = "approved_restated_only"
    # "sans qu'il y ait lieu de statuer sur la seconde branche du second moyen" / "… sur le premier moyen":
    # the Court expressly declines to rule, whatever the overall outcome.
    ordinals = {"première": 1, "premier": 1, "seconde": 2, "second": 2, "deuxième": 2, "troisième": 3, "quatrième": 4}
    for m in re.finditer(r"sans qu'il y ait lieu de statuer sur (?:la (\w+) branche du |le )(\w+) moyen", dispositif):
        branch, ground = ordinals.get(m.group(1)), _ground_key(m.group(2))
        for s in todo:
            if _ground_key(s["ground"]) == ground and s["speaker"] == "partie" and (
                    branch is None or re.match(rf"^{branch}°", s["text"])):
                s.update(stance="not_ruled", addressed_p=None)
    return segs, outcomes


if __name__ == "__main__":
    import sys
    from .fetch import fetch
    from .segment import segment
    segs, outcomes = tag(segment(fetch(sys.argv[1])["text"]))
    print("ground outcomes:", outcomes)
    for s in segs:
        print(f'{s["id"]:>3} {s["section"][:5]:5} {s["speaker"]:10} {s["p"]:.2f} {s.get("stance", ""):18} '
              f'{s.get("addressed_p") if s.get("addressed_p") is not None else "":<5} {s["text"][:70]!r}')
