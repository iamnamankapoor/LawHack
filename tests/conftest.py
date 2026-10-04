"""Offline tests: Jev is replaced by a deterministic fake so the rules and plumbing run without any API key."""
import re
from pathlib import Path

import pytest

DECISIONS = Path(__file__).resolve().parent.parent / "data" / "decisions"


def decision(prefix):
    return next(DECISIONS.glob(f"{prefix}_*.txt")).read_text(encoding="utf-8")


def fake_jev(state, questions, fallback_model=None, confidence_below=0.6):
    """Keyword stand-in for Jev with the same response shapes (choice + probabilities, noul)."""
    out = {}
    for key, spec in questions.items():
        target = state.get("CIBLE") or state.get("RÉPONSE") or state.get("PHRASE") or ""
        if key == "speaker":
            if re.search(r"La Cour de cassation a (décidé|jugé)", target):
                choice = "jurisprudence_anterieure"
            elif re.search(r"l'arrêt (retient|relève|énonce)|^(\d+\. )?Il (retient|relève|énonce|ajoute|en déduit|en conclut)|"
                           r"la cour d'appel retient|AUX MOTIFS|^(\d+\. )?Attendu que, pour|^Mais attendu que l'arrêt", target):
                choice = "cour_appel"
            elif re.search(r"fait grief|ALORS|Moyens? produits?|MOYENS? ANNEXE|DE CASSATION$|^\d°", target):
                choice = "partie"
            elif re.search(r"Selon l'arrêt attaqué|Attendu, selon l'arrêt|Donne acte|désistement|^(\d+\. )?(Licenci|M\. \[|La société)", target):
                choice = "faits"
            else:
                choice = "court"
            out[key] = {"type": "choice", "choice": choice, "probabilities": {choice: 0.99}}
        elif key == "outcome":
            court = state.get("motifs_propres_de_la_Cour_sur_ce_moyen", "")
            choice = "cassation" if re.search(r"(En|Qu'en) (statuant|se déterminant) ainsi|a violé", court) else "rejet"
            out[key] = {"type": "choice", "choice": choice, "probabilities": {choice: 0.95}}
        elif key == "addressed":
            out[key] = {"type": "noul", "noul": 0.9 if target.startswith("Mais attendu") else 0.1}
        elif key in ("misattributes", "launders"):
            out[key] = {"type": "noul", "noul": 0.9 if re.search(r"^Selon la Cour de cassation", target) else 0.05}
        elif key == "support":
            first = next(iter(spec["criteria"]))
            out[key] = {"type": "choice", "choice": first, "probabilities": {first: 0.9}}
    return out


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    import legible.answer
    import legible.check
    import legible.tag
    for mod in (legible.tag, legible.answer, legible.check):
        monkeypatch.setattr(mod, "jev", fake_jev)
    monkeypatch.setattr(legible.answer, "CACHE", str(tmp_path / "cache"))
    monkeypatch.setattr(legible.answer, "chat", lambda model, system, user, temperature=None: "La Cour ne s'est pas prononcée (§ 8).")
    monkeypatch.setattr(legible.check, "chat", lambda model, system, user, temperature=None: "Phrase réécrite (§ 8).")
