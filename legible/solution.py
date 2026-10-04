"""Detect the outcome of a Cour de cassation decision from its dispositif."""

import re
from enum import Enum


class Solution(str, Enum):
    REJET = "REJET"
    CASSATION = "CASSATION"
    CASSATION_PARTIELLE = "CASSATION_PARTIELLE"
    CASSATION_PARTIELLE_SANS_RENVOI = "CASSATION_PARTIELLE_SANS_RENVOI"
    CASSATION_SANS_RENVOI = "CASSATION_SANS_RENVOI"
    RENVOI_QPC = "RENVOI_QPC"
    NON_RENVOI_QPC = "NON_RENVOI_QPC"
    AUTRE = "AUTRE"


_CASSE = re.compile(r"\bCASSE\b", re.I)
_PARTIAL = re.compile(r"\bmais seulement\b|\bpartiellement\b|\bsauf en ce qu", re.I)
_NO_REMAND = re.compile(r"sans renvoi|n'y avoir lieu à renvoi", re.I)
_NON_RENVOI_QPC = re.compile(r"DIT N'Y AVOIR LIEU (À|A|DE) RENVOYER au Conseil constitutionnel", re.I)
_RENVOI_QPC = re.compile(r"\bRENVOIE au Conseil constitutionnel\b", re.I)
_REJECT = re.compile(r"\bREJETTE\s+(le|les|la)\s+(pourvois?|requ[êe]tes?|demandes?)\b", re.I)


def detect_solution(dispositif: str) -> Solution:
    if _NON_RENVOI_QPC.search(dispositif):
        return Solution.NON_RENVOI_QPC
    if _RENVOI_QPC.search(dispositif):
        return Solution.RENVOI_QPC
    if _CASSE.search(dispositif):
        partial = bool(_PARTIAL.search(dispositif))
        no_remand = bool(_NO_REMAND.search(dispositif))
        if partial and no_remand:
            return Solution.CASSATION_PARTIELLE_SANS_RENVOI
        if partial:
            return Solution.CASSATION_PARTIELLE
        if no_remand:
            return Solution.CASSATION_SANS_RENVOI
        return Solution.CASSATION
    if _REJECT.search(dispositif):
        return Solution.REJET
    return Solution.AUTRE
