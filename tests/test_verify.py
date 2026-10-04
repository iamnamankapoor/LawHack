from lawhack.retrieval import BM25, coverage, tokens
from lawhack.schema import Decision, Registry, RegistryEntry, Speaker, StatementType, Status, Zone
from lawhack.verify import Verdict, check, claimed_speaker


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
    assert claimed_speaker("La Cour de cassation a jugé que …") is Speaker.COUR_CASSATION
    assert claimed_speaker("La cour d'appel a relevé…") is Speaker.JURIDICTION_FOND
    assert claimed_speaker("Le moyen soutient…") is Speaker.DEMANDEUR
    assert claimed_speaker("Le pourvoi est rejeté par la Cour.") is Speaker.COUR_CASSATION
    assert claimed_speaker("La promesse est caduque.") is None


def test_claimed_speaker_follows_reassignment_and_skips_denials():
    sentence = (
        "Non, la Cour de cassation, juge du droit, ne constate pas les faits: "
        "c'est la cour d'appel qui a constaté que M. [X] a interjeté appel le 21 avril 2023."
    )
    assert claimed_speaker(sentence) is Speaker.JURIDICTION_FOND
    assert claimed_speaker(
        "La Cour de cassation n'a pas jugé que la notion de poussières totales "
        "ne peut désigner que les poussières non sédimentables."
    ) is None
    assert claimed_speaker(
        "La Cour de cassation n'a pas jugé que le texte s'applique, la cour d'appel l'a relevé."
    ) is Speaker.JURIDICTION_FOND
    assert claimed_speaker("La Cour de cassation, juge du droit, ne constate pas les faits.") is None
    assert claimed_speaker("La Cour de cassation: ne constate pas les faits.") is Speaker.COUR_CASSATION


def test_check_attributes_reassigned_lower_court_statement_correctly():
    text = "C'est la cour d'appel qui a constaté que M. X a interjeté appel le 21 avril 2023."
    registry = Registry(
        document_id="doc",
        entries=[
            RegistryEntry(
                id="S-001",
                text=text,
                start=0,
                end=len(text),
                block=0,
                zone=Zone.EXPOSE,
                speaker=Decision(value=Speaker.JURIDICTION_FOND.value, probabilities={Speaker.JURIDICTION_FOND.value: 1.0}),
                type=Decision(value=StatementType.FAIT.value, probabilities={StatementType.FAIT.value: 1.0}),
                status=Decision(value=Status.CONSTATE.value, probabilities={Status.CONSTATE.value: 1.0}),
                source="rule",
            )
        ],
    )

    (result,) = check(registry, text)

    assert result["claimed_speaker"] == Speaker.JURIDICTION_FOND.value
    assert result["verdict"] == Verdict.OK.value


def test_claimed_speaker_tolerates_missing_or_curly_apostrophe():
    assert claimed_speaker("La cour d appel a retenu que…") is Speaker.JURIDICTION_FOND
    assert claimed_speaker("La cour d’appel a retenu que…") is Speaker.JURIDICTION_FOND


def test_contradiction_with_outcome():
    from lawhack.solution import Solution
    from lawhack.verify import contradiction

    assert contradiction("La cour d'appel a cassé l'arrêt.", Speaker.JURIDICTION_FOND, Solution.REJET)
    assert contradiction("La Cour casse l'arrêt.", Speaker.COUR_CASSATION, Solution.REJET)
    assert contradiction("La Cour rejette le pourvoi.", Speaker.COUR_CASSATION, Solution.CASSATION)
    assert contradiction("La Cour rejette le pourvoi.", Speaker.COUR_CASSATION, Solution.REJET) is None
    assert contradiction("La Cour ne casse pas l'arrêt.", Speaker.COUR_CASSATION, Solution.REJET) is None
    assert contradiction("Le demandeur forme un pourvoi en cassation.", Speaker.DEMANDEUR, Solution.REJET) is None
