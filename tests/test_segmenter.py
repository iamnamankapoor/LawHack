from lawhack.segmenter import split_sentences


def _split(text):
    return [text[s:e] for s, e in split_sentences(text)]


def test_does_not_split_on_civility_abbreviations():
    assert len(_split("10. M. [R] a formé un pourvoi. Mme Martinel préside.")) == 2


def test_keeps_quoted_passages_intact():
    text = "7. Il fait grief à l'arrêt, alors « que la cour retient. Elle viole la loi. » Le moyen est rejeté."
    parts = _split(text)
    assert len(parts) == 2 and parts[0].endswith("»") and "Elle viole la loi" in parts[0]


def test_paragraph_number_is_not_a_sentence():
    assert _split("8. Aux termes du premier de ces textes, tout paiement suppose une dette.") == [
        "8. Aux termes du premier de ces textes, tout paiement suppose une dette."
    ]
