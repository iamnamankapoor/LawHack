from lawhack.retrieval import BM25, coverage, tokens
from lawhack.schema import Speaker
from lawhack.verify import claimed_speaker


def test_tokens_normalise_accents_and_inflections():
    assert tokens("REJETTE le pourvoi") == tokens("rejeté pourvois")


def test_bm25_ranks_relevant_first():
    index = BM25(["la promesse de vente est caduque", "le notaire a commis une faute", "rejette le pourvoi"])
    assert index.top("faute du notaire", k=1)[0][0] == 1
    assert coverage("faute notaire", "le notaire a commis une faute") == 1.0


def test_claimed_speaker():
    assert claimed_speaker("La cour d'appel a retenu que…") is Speaker.JURIDICTION_FOND
    assert claimed_speaker("La Cour de cassation juge que…") is Speaker.COUR_CASSATION
    assert claimed_speaker("Le demandeur soutient que…") is Speaker.DEMANDEUR
    assert claimed_speaker("Le pourvoi est rejeté par la Cour.") is Speaker.COUR_CASSATION
    assert claimed_speaker("La promesse est caduque.") is None
