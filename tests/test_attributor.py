import asyncio

from lawhack.attributor import build_registry
from lawhack.schema import Decision, Segment, Speaker, Status, Zone
from lawhack.segmenter import segment
from lawhack.system_one import SystemOneResult
from lawhack.zoning import zone_blocks


class FakeSystemOne:
    """Answers JURIDICTION_FOND with low confidence first, then high once options are reversed."""

    def __init__(self):
        self.calls = 0

    async def decide(self, state, questions):
        self.calls += 1
        reversed_pass = not any(k.startswith("type:") for k in questions)
        out = {}
        for key in questions:
            if key.startswith("speaker:"):
                conf = 0.95 if reversed_pass else 0.6
                out[key] = Decision(value="JURIDICTION_FOND", probabilities={"JURIDICTION_FOND": conf, "INDETERMINE": 1 - conf}, confidence=conf)
            elif key.startswith("type:"):
                out[key] = Decision(value="MOTIF", probabilities={"MOTIF": 1.0}, confidence=1.0)
            else:
                out[key] = Decision(value="CONSTATE", probabilities={"CONSTATE": 1.0}, confidence=1.0)
        return SystemOneResult(decisions=out, model="fake", input_tokens=10)


def test_rules_jev_and_approval_markers(legifrance_doc):
    segments = segment(zone_blocks(legifrance_doc))
    fake = FakeSystemOne()
    registry = asyncio.run(build_registry("doc", segments, fake))
    by_para = {e.paragraph: e for e in registry.entries if e.paragraph}

    dispositif = [e for e in registry.entries if e.zone.value == "dispositif"]
    assert dispositif and all(e.source == "rule" and e.speaker.value == "COUR_CASSATION" for e in dispositif)

    assert by_para[8].speaker.value == "JURIDICTION_FOND" and by_para[8].source == "jev"
    assert by_para[8].speaker.probabilities["JURIDICTION_FOND"] > 0.7  # averaged with the reversed pass

    approved = by_para[9]  # « Elle a retenu à bon droit… »
    assert approved.speaker.value == Speaker.COUR_CASSATION.value
    assert approved.status.value == Status.DECIDE.value
    assert approved.chain == [Speaker.COUR_CASSATION, Speaker.JURIDICTION_FOND]
    assert fake.calls > 0 and registry.input_tokens == 10 * fake.calls


def test_drafting_formulas_need_no_model_call():
    from lawhack.attributor import _rule

    def seg(text, zone=Zone.MOTIVATIONS):
        return Segment(id="S-001", text=text, start=0, end=len(text), block=0, zone=zone)

    assert _rule(seg("9. Pour rejeter la demande, l'arrêt retient que le bail est résilié."))[0] is Speaker.JURIDICTION_FOND
    assert _rule(seg("11. En statuant ainsi, la cour d'appel a violé le texte susvisé."))[0] is Speaker.COUR_CASSATION
    assert _rule(seg("12. Le moyen n'est donc pas fondé."))[:3] == (Speaker.COUR_CASSATION, _rule(seg("Le moyen n'est pas fondé."))[1], Status.DECIDE)
    assert _rule(seg("7. Le vendeur fait grief à l'arrêt de rejeter sa demande.", Zone.MOYENS))[0] is Speaker.DEMANDEUR
    assert _rule(seg("9. Elle a retenu à bon droit que la promesse était caduque.")) is None


def test_numbered_anaphora_propagates_and_cascades():
    texts = [
        "La cour d'appel a examiné les propositions.",
        "7. Il relève, encore, que le poste était adapté.",
        "Il ajoute que le salarié pouvait accepter.",
    ]
    segments = []
    start = 0
    for i, text in enumerate(texts, start=1):
        segments.append(Segment(
            id=f"S-{i:03}",
            text=text,
            start=start,
            end=start + len(text),
            block=0,
            zone=Zone.MOTIVATIONS,
        ))
        start += len(text) + 1
    registry = asyncio.run(build_registry("doc", segments, FakeSystemOne()))

    assert registry.entries[0].speaker.value == Speaker.JURIDICTION_FOND.value
    assert registry.entries[1].speaker.value == Speaker.JURIDICTION_FOND.value
    assert registry.entries[1].source == "jev+anaphora"
    assert registry.entries[2].speaker.value == Speaker.JURIDICTION_FOND.value
    assert registry.entries[2].source == "jev+anaphora"


def test_expose_is_lower_court_findings(legifrance_doc):
    registry = asyncio.run(build_registry("doc", segment(zone_blocks(legifrance_doc)), FakeSystemOne()))
    expose = [e for e in registry.entries if e.zone is Zone.EXPOSE]
    assert expose and all(e.speaker.value == "JURIDICTION_FOND" and e.status.value == "CONSTATE" for e in expose)
    assert all(e.type.value in ("FAIT", "PROCEDURE") for e in expose)


def test_analyse_falls_back_to_heuristic_when_jev_fails(tmp_path, monkeypatch, legifrance_doc):
    from lawhack import pipeline

    class Broken:
        model = "jev-latest"

        async def decide(self, state, questions):
            raise RuntimeError("401 Cannot authenticate")

    monkeypatch.setattr(pipeline, "CACHE_DIR", tmp_path)
    registry, _ = pipeline.analyse(legifrance_doc, Broken())
    assert registry.entries and registry.model == "heuristic"
