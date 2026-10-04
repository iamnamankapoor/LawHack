import pytest

from lawhack.solution import Solution, detect_solution


@pytest.mark.parametrize(
    "dispositif, expected",
    [
        ("REJETTE le pourvoi ;", Solution.REJET),
        ("CASSE ET ANNULE, en toutes ses dispositions, l'arrêt rendu…", Solution.CASSATION),
        ("CASSE ET ANNULE, mais seulement en ce qu'il condamne…", Solution.CASSATION_PARTIELLE),
        ("CASSE ET ANNULE, mais seulement en ce qu'il… DIT n'y avoir lieu à renvoi ;", Solution.CASSATION_PARTIELLE_SANS_RENVOI),
        ("CASSE ET ANNULE l'arrêt ; DIT n'y avoir lieu à renvoi", Solution.CASSATION_SANS_RENVOI),
        ("DIT N'Y AVOIR LIEU DE RENVOYER au Conseil constitutionnel", Solution.NON_RENVOI_QPC),
        ("RENVOIE au Conseil constitutionnel", Solution.RENVOI_QPC),
        ("REJETTE la requête de Mme X... ;", Solution.REJET),
    ],
)
def test_detect_solution(dispositif, expected):
    assert detect_solution(dispositif) is expected
