from lawhack.schema import Zone
from lawhack.zoning import zone_blocks


def _by_paragraph(blocks):
    return {b.paragraph: b for b in blocks if b.paragraph}


def test_judilibre_paragraphs_land_in_expected_zones(judilibre_doc):
    doc, _ = judilibre_doc
    paras = _by_paragraph(zone_blocks(doc))
    assert sorted(paras) == list(range(1, 15))
    assert paras[1].zone is Zone.EXPOSE
    assert paras[7].zone is Zone.MOYENS and paras[7].heading == "Enoncé du moyen"
    assert paras[10].zone is Zone.MOTIVATIONS and paras[10].heading == "Réponse de la Cour"


def test_judilibre_zoning_matches_ground_truth_zones(judilibre_doc):
    doc, row = judilibre_doc
    truth = {z: spans for z, spans in row["zones"].items() if spans}

    def true_zone(offset):
        return next((z for z, spans in truth.items() for s in spans if s["start"] <= offset < s["end"]), None)

    # Judilibre files admissibility ("Recevabilité…") under exposé; we keep it as the Cour's reasoning.
    numbered = [b for b in zone_blocks(doc) if b.paragraph and not (b.heading or "").startswith("Recevabilité")]
    agree = sum(true_zone(b.start) == b.zone.value for b in numbered)
    assert agree / len(numbered) >= 0.9


def test_legifrance_pdf_zones_and_annexe(legifrance_doc):
    blocks = zone_blocks(legifrance_doc)
    paras = _by_paragraph(blocks)
    assert paras[7].zone is Zone.MOYENS
    assert all(paras[n].zone is Zone.MOTIVATIONS for n in (8, 9, 10, 11))
    assert any(b.zone is Zone.DISPOSITIF and b.text.startswith("REJETTE") for b in blocks)
    annexe = [b for b in blocks if b.heading and b.heading.upper().startswith("MOYEN ANNEXE")]
    assert annexe and all(b.zone in (Zone.MOYENS, Zone.METADONNEES) for b in annexe)
    assert "legifrance.gouv.fr" not in legifrance_doc.text
