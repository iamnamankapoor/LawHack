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


ATTENDU_STYLE = """LA COUR DE CASSATION, DEUXIÈME CHAMBRE CIVILE, a rendu l'arrêt suivant :

Attendu, selon l'arrêt attaqué, qu'à l'issue d'un contrôle, l'URSSAF a adressé à la société une lettre d'observations ;

Sur le premier moyen :

Attendu que l'URSSAF fait grief à l'arrêt d'annuler les redressements, alors, selon le moyen :

1°/ que les jugements doivent être motivés ;

Mais attendu que l'arrêt retient que les redressements sont tous fondés sur le même motif ;

Vu l'article R. 243-59 du code de la sécurité sociale ;

PAR CES MOTIFS :

CASSE ET ANNULE, mais seulement en ce qu'il annule les redressements ;

Moyens produits par la SCP Gatineau et Fattaccini, avocat aux Conseils, pour l'URSSAF.

Il est fait grief à l'arrêt attaqué d'avoir annulé les redressements.
"""


def test_pre_2019_attendu_style_zones():
    from lawhack.ingest import load_text
    from lawhack.zoning import zone_blocks

    zones = {b.text[:25]: b.zone.value for b in zone_blocks(load_text(ATTENDU_STYLE))}
    assert zones["Attendu, selon l'arrêt at"] == "expose"
    assert zones["Attendu que l'URSSAF fait"] == "moyens"
    assert zones["1°/ que les jugements doi"] == "moyens"
    assert zones["Mais attendu que l'arrêt "] == "motivations"
    assert zones["Vu l'article R. 243-59 du"] == "motivations"
    assert zones["CASSE ET ANNULE, mais seu"] == "dispositif"
    assert zones["Il est fait grief à l'arr"] == "moyens"


def test_pdf_without_text_layer_falls_back_to_ocr(tmp_path, monkeypatch):
    import pymupdf

    from lawhack import ingest

    path = tmp_path / "image.pdf"
    pdf = pymupdf.open()
    pdf.new_page()
    pdf.save(path)
    monkeypatch.setattr(ingest, "ocr_pdf", lambda p: ["10/4/26, 3:44 PM\nREJETTE le pourvoi ;\nhttps://www.legifrance.gouv.fr/x 1/1\n"])
    assert ingest.load_pdf(path).text.strip() == "REJETTE le pourvoi ;"


def test_corrupt_pdf_raises_no_text_error(tmp_path):
    import pytest

    from lawhack import ingest

    path = tmp_path / "x.pdf"
    path.write_text("hello")
    with pytest.raises(ingest.NoTextError):
        ingest.load_pdf(path)
