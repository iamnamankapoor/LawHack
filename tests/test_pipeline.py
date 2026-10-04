import pytest

from legible.answer import contradicts_outcome, references
from legible.holdings import holdings
from legible.ingest import from_text_bytes
from legible.render import ref
from legible.segment import segment
from legible.solution import Solution, detect_solution
from legible.tag import tag

from .conftest import decision


def by_ref(segs):
    return {ref(s): s for s in segs}


def test_red_test_paragraph_8_sits_under_reponse_de_la_cour():
    """The trap: the cour d'appel's reasoning is printed under the Court's own heading."""
    segs = {ref(s): s for s in segment(decision("C2"))}
    assert segs["§8"]["heading"] == "Réponse de la Cour"
    assert segs["§8"]["text"].startswith("8. Il retient, enfin")


def test_red_test_labels():
    segs, outcomes = tag(segment(decision("C2")))
    s = by_ref(segs)
    assert s["§8"]["speaker"] == "cour_appel" and s["§8"]["stance"] == "not_ruled"
    assert s["§9"]["stance"] == "quashed"  # "En statuant ainsi" censures the passage just before it
    assert s["§10"]["speaker"] == "court"
    assert set(outcomes.values()) == {"cassation"}


def test_holdings_quote_the_court_verbatim_and_list_unruled_passages():
    segs, outcomes = tag(segment(decision("C2")))
    h = holdings(segs, outcomes)
    first = h["grounds"][0]
    assert h["solution"] == "CASSATION_PARTIELLE"
    assert any(q["ref"] == "§10" for q in first["quotes"])
    assert "§8" in first["not_ruled"]


def test_overruled_case_law_and_approval_by_deduction():
    """U08: the Court quotes its own 2021 rule to abandon it, and approves the cour d'appel by "a exactement déduit"."""
    segs, _ = tag(segment(decision("U08")))
    s = by_ref(segs)
    assert s["§8"]["speaker"] == "jurisprudence_anterieure" and s["§8"]["stance"] == "overruled"
    assert all(s[f"§{n}"]["stance"] == "approved" for n in (16, 17, 18))


def test_pre_2019_style_par_ce_seul_motif_and_unruled_branch():
    segs, outcomes = tag(segment(decision("C4")))
    assert outcomes == {"premier": "rejet", "second": "cassation"}
    approved = [x for x in segs if x["section"] == "body" and x["speaker"] == "cour_appel" and x["text"].startswith("Mais attendu")]
    assert approved and approved[0]["stance"] == "approved_restated_only"
    branch2 = [x for x in segs if x["section"] == "annexe" and x["text"].startswith("2° - ALORS en tout état de cause")]
    assert branch2 and branch2[0]["stance"] == "not_ruled"  # "sans qu'il y ait lieu de statuer sur la seconde branche"


def test_excerpt_without_the_courts_answer():
    excerpt = "\n".join(l for l in decision("C2").split("\n") if l[:3] in ("5. ", "6. ", "7. ", "8. ", "9. "))
    segs, _ = tag(segment(excerpt))
    assert {s["stance"] for s in segs} == {"no_court_answer_in_text"}


@pytest.mark.parametrize("dispositif, expected", [
    ("REJETTE le pourvoi ;", Solution.REJET),
    ("CASSE ET ANNULE, en toutes ses dispositions, l'arrêt rendu…", Solution.CASSATION),
    ("CASSE ET ANNULE, mais seulement en ce qu'il condamne…", Solution.CASSATION_PARTIELLE),
    ("CASSE ET ANNULE l'arrêt ; DIT n'y avoir lieu à renvoi", Solution.CASSATION_SANS_RENVOI),
    ("DIT N'Y AVOIR LIEU DE RENVOYER au Conseil constitutionnel", Solution.NON_RENVOI_QPC),
])
def test_detect_solution(dispositif, expected):
    assert detect_solution(dispositif) is expected


def test_outcome_guard_only_on_whole_outcomes():
    rejet = [{"section": "dispositif", "text": "REJETTE le pourvoi ;"}]
    assert contradicts_outcome("La Cour casse l'arrêt de la cour d'appel.", rejet)
    assert contradicts_outcome("La Cour ne casse pas l'arrêt.", rejet) is None
    partial = [{"section": "dispositif", "text": "REJETTE le pourvoi incident ; CASSE ET ANNULE, sauf en ce qu'il…"}]
    assert contradicts_outcome("La Cour rejette le pourvoi incident et casse l'arrêt.", partial) is None


def test_references_link_cited_paragraphs():
    segs, _ = tag(segment(decision("C2")))
    refs = references("Motif de la cour d'appel (§ 8), censuré au §10.", segs)
    assert [r["ref"] for r in refs] == ["§8", "§10"]
    assert refs[0]["speaker"] == "cour_appel"


def test_text_upload_decoding():
    assert from_text_bytes("Arrêt du 4 mai\r\n".encode("utf-8-sig")) == "Arrêt du 4 mai\n"
    assert from_text_bytes("Arrêt".encode("cp1252")) == "Arrêt"
