"""Render tagged segments as an annotated decision an LLM can't misread."""
import re
from html import escape

STANCE_FR = {
    "quashed": "La Cour de cassation a CENSURÉ ce raisonnement : la décision de la cour d'appel est annulée sur ce point.",
    "approved": "La Cour de cassation a APPROUVÉ la cour d'appel sur ce point : sa décision est MAINTENUE. "
                "Le raisonnement reste toutefois celui de la cour d'appel, la Cour n'en fait pas sa propre règle.",
    "approved_restated_only": "La Cour de cassation a maintenu la décision de la cour d'appel « par ce seul motif » : elle n'approuve QUE "
                              "le motif qu'elle reprend elle-même dans ses motifs propres. Les autres motifs de ce passage sont surabondants : "
                              "la Cour ne s'est PAS prononcée sur eux et ils ne sont pas sa position.",
    "not_ruled": "La Cour de cassation NE S'EST PAS PRONONCÉE sur ce point : ce n'est pas sa position. "
                 "S'il figure dans un arrêt cassé pour un autre motif, il tombe avec lui sans être ni approuvé ni désapprouvé.",
    "argument_rejected": "Argument d'une partie, ÉCARTÉ par la Cour de cassation.",
    "argument_accepted": "Argument d'une partie, ACCUEILLI : la cassation est prononcée sur ce moyen. Mais la formulation de cet argument "
                         "reste celle de la partie et n'est PAS une règle posée par la Cour ; seuls les motifs propres de la Cour expriment sa position.",
    "overruled": "Jurisprudence ANTÉRIEURE de la Cour, ABANDONNÉE par la présente décision : ce n'est plus la position de la Cour.",
    "cited_precedent": "Jurisprudence antérieure de la Cour, citée à l'appui de son raisonnement.",
    "no_court_answer_in_text":"Le texte fourni ne contient PAS la réponse de la Cour de cassation : aucune position ne peut lui être attribuée sur ce point.",
}
SPEAKER_FR = {"court": "Cour de cassation", "cour_appel": "cour d'appel (arrêt attaqué, cité par la Cour)",
              "partie": "une partie (moyen de cassation)", "faits": "exposé des faits et de la procédure",
              "jurisprudence_anterieure": "jurisprudence antérieure de la Cour de cassation"}
OUTCOME_FR = {"cassation": "moyen accueilli : la décision de la cour d'appel est CASSÉE sur ce point",
              "rejet": "moyen rejeté : la décision de la cour d'appel est MAINTENUE sur ce point",
              "non_examine": "moyen non examiné"}


def ref(s):
    """Citation label a lawyer recognises: the decision's own paragraph number, else a segment number."""
    m = re.match(r"^(\d{1,3})\. ", s["text"])
    return f"§{m.group(1)}" if m else f"s{s['id']}"


def render(segs, outcomes):
    without_reasons = any("1014" in s["text"] for s in segs if s["speaker"] == "court")
    lines = ["<decision>"]
    for s in segs:
        attrs = f'ref="{ref(s)}" locuteur="{SPEAKER_FR[s["speaker"]]}"'
        if s.get("ground"):
            attrs += f' moyen="{escape(s["ground"])}"'
        if s.get("stance"):
            note = STANCE_FR[s["stance"]]
            if s["stance"] == "argument_rejected" and without_reasons:
                note += " (rejet non spécialement motivé, art. 1014 CPC : la Cour ne pose aucune règle.)"
            attrs += f' sort="{escape(note)}"'
        lines.append(f"<segment {attrs}>\n{escape(s['text'])}\n</segment>")
    lines.append("</decision>")

    court = [s for s in segs if s["speaker"] == "court" and s["section"] != "dispositif"]
    disp = [s for s in segs if s["section"] == "dispositif"]
    others = [s for s in segs if s.get("stance")]
    sheet = ["<synthese_verifiee>",
             "Ce que la Cour de cassation dit elle-même (seuls ces passages expriment sa position) :"]
    sheet += [f"- [{ref(s)}] {s['text'][:600]}" for s in court] or ["- (aucun motif propre de la Cour dans le texte fourni)"]
    if outcomes:
        sheet.append("Sort des moyens : " + "; ".join(f"{k or 'moyen unique'} → {OUTCOME_FR.get(v, v)}" for k, v in outcomes.items()))
    if disp:
        sheet.append("Dispositif : " + " ".join(s["text"] for s in disp)[:1500])
    sheet.append("Passages qui NE sont PAS la position de la Cour :")
    sheet += [f"- [{ref(s)}] {SPEAKER_FR[s['speaker']]} — {STANCE_FR[s['stance']]} « {s['text'][:240]}… »" for s in others]
    sheet.append("</synthese_verifiee>")
    return "\n".join(lines) + "\n\n" + "\n".join(sheet)
