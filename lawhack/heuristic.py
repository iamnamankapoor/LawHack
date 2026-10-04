"""Offline System 1 fallback: zone + lexical cues, deliberately low confidence.

Used when no Jev/OpenJev key is configured so the pipeline (and the MCP connector) still
runs end to end. Its confidences stay below the 0.8 threshold so answers are flagged
« à vérifier ».
"""

import re
from typing import Any

from lawhack.schema import Decision, Speaker, StatementType, Status, Zone
from lawhack.system_one import SystemOneResult

_LOWER_COURT = re.compile(
    r"l'arr[êe]t (attaqu[ée]|retient|relève|énonce|constate|juge|rejette|condamne|dit)"
    r"|la cour d'appel|les juges du fond|pour (dire|rejeter|condamner|accueillir|débouter|déclarer)",
    re.I,
)
_PETITIONER = re.compile(r"fait grief|reproche|alors que|le moyen|soutient|fait valoir", re.I)
_LAW = re.compile(r"^(aux termes|selon) (de |l'|les? )?(article|ce texte|ces textes)|il résulte (de ce|des) texte", re.I)


def _speaker(zone: str, text: str) -> tuple[Speaker, float]:
    if zone == Zone.MOYENS.value:
        return Speaker.DEMANDEUR, 0.75 if _PETITIONER.search(text) else 0.65
    if _LAW.search(text):
        return Speaker.LOI, 0.6
    if _LOWER_COURT.search(text):
        return Speaker.JURIDICTION_FOND, 0.7
    if zone == Zone.EXPOSE.value:
        return Speaker.JURIDICTION_FOND, 0.5
    return Speaker.COUR_CASSATION, 0.6


def _decision(value: str, confidence: float) -> Decision:
    return Decision(value=value, probabilities={value: confidence, Speaker.INDETERMINE.value: round(1 - confidence, 4)}, confidence=confidence)


class HeuristicSystemOne:
    model = "heuristic"

    async def decide(self, state: Any, questions: dict) -> SystemOneResult:
        zone = state.get("zone", "")
        sentences = state.get("sentences", {})
        decisions: dict[str, Decision] = {}
        for key in questions:
            kind, sid = key.split(":", 1)
            speaker, conf = _speaker(zone, sentences.get(sid, ""))
            if kind == "speaker":
                decisions[key] = _decision(speaker.value, conf)
            elif kind == "type":
                kind_value = {Zone.MOYENS.value: StatementType.MOYEN, Zone.EXPOSE.value: StatementType.FAIT}.get(zone, StatementType.MOTIF)
                decisions[key] = _decision(kind_value.value, conf)
            else:
                if speaker is Speaker.DEMANDEUR:
                    status = Status.ALLEGUE
                elif speaker is Speaker.COUR_CASSATION:
                    status = Status.DECIDE
                else:
                    status = Status.CONSTATE
                decisions[key] = _decision(status.value, conf)
        return SystemOneResult(decisions=decisions, model=self.model)
