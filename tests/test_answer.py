import asyncio

from lawhack import answer as answer_module
from lawhack.answer import ask
from lawhack.attributor import build_registry
from lawhack.schema import Decision, Zone
from lawhack.segmenter import segment
from lawhack.system_one import SystemOneResult
from lawhack.zoning import zone_blocks

from tests.test_attributor import FakeSystemOne


class FakeRetrieval(FakeSystemOne):
    """`relevant` = segment ids whose paragraphs Jev should pick; `supported` = verification probability."""

    def __init__(self, relevant=(), supported=0.9, target="ANY", target_p=0.9):
        super().__init__()
        self.relevant, self.supported = set(relevant), supported
        self.target, self.target_p = target, target_p

    async def decide(self, state, questions):
        if "target" in questions:
            keys = questions["target"].criteria
            other_p = (1 - self.target_p) / (len(keys) - 1)
            probs = {key: self.target_p if key == self.target else other_p for key in keys}
            return SystemOneResult(
                decisions={"target": Decision(value=self.target, probabilities=probs, confidence=self.target_p)},
                model="fake",
            )
        if "best" in questions:
            keys = [k for k in questions["best"].criteria if k != "NONE"]
            hits = [k for k in keys if any(sid in self.relevant for sid in self.paragraph_ids.get(k, ()))]
            probs = {k: (1 / len(hits) if k in hits else 0.0) for k in keys}
            probs["NONE"] = 0.0 if hits else 1.0
            best = max(probs, key=probs.get)
            return SystemOneResult(decisions={"best": Decision(value=best, probabilities=probs, confidence=1.0)}, model="fake")
        if not any(k == "ok" or k.startswith("ok:") for k in questions):
            return await super().decide(state, questions)
        p = self.supported
        out = {k: Decision(value="yes" if p >= 0.5 else "no", probabilities={"yes": p, "no": 1 - p}, confidence=max(p, 1 - p)) for k in questions}
        return SystemOneResult(decisions=out, model="fake")


def _fake(registry, **kwargs):
    fake = FakeRetrieval(**kwargs)
    fake.paragraph_ids = {}
    for e in registry.entries:
        fake.paragraph_ids.setdefault(f"P{e.block}", []).append(e.id)
    return fake


def _registry(doc):
    return asyncio.run(build_registry("doc", segment(zone_blocks(doc)), FakeSystemOne()))


def _para(registry, n):
    return next(e for e in registry.entries if e.paragraph == n)


def test_abstains_when_nothing_relevant(legifrance_doc, monkeypatch):
    registry = _registry(legifrance_doc)
    monkeypatch.setattr(answer_module, "draft", lambda *a: (_ for _ in ()).throw(AssertionError("no LLM call")))
    result = asyncio.run(ask(registry, "Montant du préjudice moral ?", _fake(registry)))
    assert result.abstained and result.render() == answer_module.NOT_ADDRESSED


def test_pills_carry_speaker_paragraph_and_confidence(legifrance_doc, monkeypatch):
    registry = _registry(legifrance_doc)
    s9, s7 = _para(registry, 9).id, _para(registry, 7).id
    monkeypatch.setattr(answer_module, "draft", lambda q, ctx, m=None: (
        f"La Cour approuve la cour d'appel [{s9}]. Le vendeur soutenait l'inverse [{s7}]. Une phrase sans source."
    ))
    result = asyncio.run(ask(registry, "Que décide la Cour ?", _fake(registry, relevant={s9, s7})))
    first, second, third = result.sentences
    assert first.pills[0].label == "Cour, approuvant la cour d'appel" and first.pills[0].paragraph == 9 and first.pills[0].level == "ok"
    assert second.pills[0].paragraph == 7
    assert third.pills == [] and third.supported == 0.0
    assert "[Cour, approuvant la cour d'appel · §9 · " in result.render() and "[non sourcé ⚠]" in result.render()


def test_low_verification_downgrades_pill(legifrance_doc, monkeypatch):
    registry = _registry(legifrance_doc)
    s9 = _para(registry, 9).id
    monkeypatch.setattr(answer_module, "draft", lambda q, ctx, m=None: f"La Cour casse l'arrêt [{s9}].")
    result = asyncio.run(ask(registry, "Que décide la Cour ?", _fake(registry, relevant={s9}, supported=0.2)))
    assert result.sentences[0].pills[0].level == "unsupported"


def test_retrieving_a_moyen_brings_the_cour_reply(legifrance_doc, monkeypatch):
    registry = _registry(legifrance_doc)
    s7 = _para(registry, 7).id
    seen = {}
    monkeypatch.setattr(answer_module, "draft", lambda q, ctx, m=None: seen.setdefault("ctx", ctx) and f"Le vendeur soutient [{s7}].")
    asyncio.run(ask(registry, "Que soutient le vendeur ?", _fake(registry, relevant={s7})))
    assert {e.paragraph for e in seen["ctx"]} >= {7, 8, 9, 10, 11}


def test_party_question_pins_the_moyen_even_when_jev_says_none(legifrance_doc, monkeypatch):
    registry = _registry(legifrance_doc)
    s7 = _para(registry, 7).id
    seen = {}
    monkeypatch.setattr(
        answer_module, "draft",
        lambda q, ctx, m=None: seen.setdefault("ctx", ctx) and f"Le vendeur soutient [{s7}].",
    )
    asyncio.run(ask(registry, "Que soutient le demandeur au pourvoi ?", _fake(registry, target="DEMANDEUR")))

    context = seen["ctx"]
    assert any(e.paragraph == 7 and e.zone is Zone.MOYENS and e.speaker.value == "DEMANDEUR" for e in context)
    assert {e.paragraph for e in context} >= {9, 10}
    assert 15 not in {e.paragraph for e in context}


def test_off_topic_still_abstains_with_any_target(legifrance_doc, monkeypatch):
    registry = _registry(legifrance_doc)
    fake = _fake(registry, target="ANY")
    assert asyncio.run(answer_module.retrieve(registry, "Montant du préjudice moral ?", fake)) == []
    monkeypatch.setattr(answer_module, "draft", lambda *a: (_ for _ in ()).throw(AssertionError("no LLM call")))

    result = asyncio.run(ask(registry, "Montant du préjudice moral ?", fake))

    assert result.abstained and result.sentences == []


def test_defendeur_target_without_defendeur_moyen_abstains(legifrance_doc):
    registry = _registry(legifrance_doc)
    assert not any(
        e.zone is Zone.MOYENS and e.speaker.value == "DEFENDEUR"
        for e in registry.entries
    )

    context = asyncio.run(
        answer_module.retrieve(registry, "Que soutient le défendeur au pourvoi ?", _fake(registry, target="DEFENDEUR"))
    )

    assert context == []


def test_low_confidence_target_does_not_pin(legifrance_doc):
    registry = _registry(legifrance_doc)

    context = asyncio.run(
        answer_module.retrieve(
            registry,
            "Que soutient le demandeur au pourvoi ?",
            _fake(registry, target="DEMANDEUR", target_p=0.5),
        )
    )

    assert context == []


def test_abstains_only_when_both_passes_say_none(legifrance_doc, monkeypatch):
    registry = _registry(legifrance_doc)
    s10 = _para(registry, 10).id
    fake = _fake(registry, relevant={s10})
    original = fake.decide
    calls = []

    async def flaky(state, questions):
        result = await original(state, questions)
        if "best" in questions:
            calls.append(1)
            if len(calls) == 1:  # first pass wrongly says NONE
                probs = {k: 0.0 for k in result.decisions["best"].probabilities} | {"NONE": 1.0}
                result.decisions["best"] = Decision(value="NONE", probabilities=probs, confidence=1.0)
        return result

    fake.decide = flaky
    context = asyncio.run(answer_module.retrieve(registry, "Les acquéreurs devaient-ils accepter le prêt ?", fake))
    assert len(calls) == 2 and 10 in {e.paragraph for e in context}


def test_speaker_label_shows_endorsement():
    from lawhack.answer import speaker_label
    from lawhack.schema import Decision, RegistryEntry, Speaker, StatementType, Status, Zone

    def entry(speaker, chain):
        d = lambda v: Decision(value=v, probabilities={v: 1.0}, confidence=1.0)
        return RegistryEntry(id="S-001", block=0, start=0, end=1, zone=Zone.MOTIVATIONS, text="x", source="rule", speaker=d(speaker),
                             type=d(StatementType.MOTIF.value), status=d(Status.DECIDE.value), chain=chain)

    assert speaker_label(entry("COUR_CASSATION", [Speaker.COUR_CASSATION, Speaker.JURIDICTION_FOND])) == "Cour, approuvant la cour d'appel"
    assert speaker_label(entry("COUR_CASSATION", [Speaker.COUR_CASSATION])) == "Cour"
    assert speaker_label(entry("JURIDICTION_FOND", [Speaker.COUR_CASSATION, Speaker.JURIDICTION_FOND])) == "Cour d'appel"


def test_false_premise_question_is_rescued_lexically(legifrance_doc):
    from lawhack.answer import retrieve

    registry = _registry(legifrance_doc)
    s8 = _para(registry, 8).id
    picked = asyncio.run(retrieve(registry, "La Cour de cassation a-t-elle constaté que la banque avait refusé le prêt des acquéreurs ?", _fake(registry)))
    assert s8 in {e.id for e in picked}


def test_lower_court_reported_in_a_moyen_is_a_warning(legifrance_doc, monkeypatch):
    registry = _registry(legifrance_doc)
    s7 = next(e for e in registry.entries if e.paragraph == 7 and e.speaker.value == "DEMANDEUR")
    monkeypatch.setattr(answer_module, "draft", lambda q, ctx, m=None: f"La cour d'appel a statué [{s7.id}]. Elle a déclaré la promesse caduque [{s7.id}]. Le vendeur soutient que la cour d'appel a violé la loi [{s7.id}].")
    result = asyncio.run(ask(registry, "Qu'a décidé la cour d'appel ?", _fake(registry, relevant={s7.id}, supported=0.1)))
    first, pronoun, party = (s.pills[0] for s in result.sentences)
    assert first.level == pronoun.level == "warn"
    assert pronoun.note.startswith("Rapporté par le demandeur (§7)")
    assert party.note is None
