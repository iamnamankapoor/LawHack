import asyncio
import importlib
from types import SimpleNamespace

import pytest

from lawhack import answer as answer_module
from lawhack.answer import ask, draft as answer_draft, revise as answer_revise
from lawhack.attributor import build_registry
from lawhack.schema import Decision, Speaker, Zone
from lawhack.segmenter import segment
from lawhack.solution import Solution
from lawhack.system_one import SystemOneResult
from lawhack.zoning import zone_blocks

from tests.test_attributor import FakeSystemOne


@pytest.fixture(autouse=True)
def _no_live_rewrite(monkeypatch):
    """Rewrites hit Mistral: tests opt in by patching `revise`; by default it fails and the draft is kept."""
    def offline(*a, **k):
        raise RuntimeError("offline")
    monkeypatch.setattr(answer_module, "revise", offline)


class FakeRetrieval(FakeSystemOne):
    """`relevant` = segment ids whose paragraphs Jev should pick; `supported` = verification probability."""

    def __init__(self, relevant=(), supported=0.9, target="ANY", target_p=0.9):
        super().__init__()
        self.relevant, self.supported = set(relevant), supported
        self.target, self.target_p = target, target_p
        self.decide_calls = 0

    async def decide(self, state, questions):
        self.decide_calls += 1
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


class FakeMistral:
    def __init__(self, response):
        self.response = response
        self.models = []
        self.chat = self

    def complete(self, **kwargs):
        self.models.append(kwargs["model"])
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.response))])


def _fake_mistral(monkeypatch, response):
    mistral_client = importlib.import_module("mistralai.client")
    fake = FakeMistral(response)
    monkeypatch.setattr(mistral_client, "Mistral", lambda api_key: fake)
    monkeypatch.setenv("MISTRAL_API_KEY", "fake-key")
    return fake


def _enable_answer_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(answer_module, "ANSWER_CACHE_DIR", tmp_path / "answers")
    monkeypatch.setenv("ANSWER_CACHE", "1")
    monkeypatch.setenv("ANSWER_MODEL", "draft-model")
    monkeypatch.delenv("REVISE_MODEL", raising=False)


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


def _verified_pill(registry, entry, claim, supported, **updates):
    entry = entry.model_copy(update=updates)
    registry = registry.model_copy(update={
        "entries": [entry if current.id == entry.id else current for current in registry.entries]
    })
    result = asyncio.run(
        answer_module.verify(f"{claim} [{entry.id}].", registry, _fake(registry, supported=supported))
    )
    return result[0].pills[0]


def test_abstains_when_nothing_relevant(legifrance_doc, monkeypatch):
    registry = _registry(legifrance_doc)
    monkeypatch.setattr(answer_module, "draft", lambda *a: (_ for _ in ()).throw(AssertionError("no LLM call")))
    result = asyncio.run(ask(registry, "Montant du préjudice moral ?", _fake(registry)))
    assert result.abstained and result.render() == answer_module.NOT_ADDRESSED


def test_answer_cache_hits_for_normalized_question(legifrance_doc, monkeypatch, tmp_path):
    _enable_answer_cache(monkeypatch, tmp_path)
    registry = _registry(legifrance_doc)
    s9 = _para(registry, 9).id
    client = _fake(registry, relevant={s9})
    mistral = _fake_mistral(monkeypatch, f"La Cour confirme l'arrêt [{s9}].")

    first = asyncio.run(ask(registry, "Que décide la Cour ?", client))
    decide_calls = client.decide_calls
    second_question = "  QUE   DÉCIDE LA COUR ?  "
    second = asyncio.run(ask(registry, second_question, client))

    assert client.decide_calls == decide_calls
    assert mistral.models == ["draft-model"]
    assert first.sentences == second.sentences
    assert second.question == second_question


def test_answer_cache_misses_for_different_question(legifrance_doc, monkeypatch, tmp_path):
    _enable_answer_cache(monkeypatch, tmp_path)
    registry = _registry(legifrance_doc)
    s9 = _para(registry, 9).id
    client = _fake(registry, relevant={s9})
    mistral = _fake_mistral(monkeypatch, f"La Cour confirme l'arrêt [{s9}].")

    asyncio.run(ask(registry, "Que décide la Cour ?", client))
    calls_after_first = client.decide_calls
    asyncio.run(ask(registry, "Quelle est la décision ?", client))

    assert client.decide_calls > calls_after_first
    assert mistral.models == ["draft-model", "draft-model"]


def test_answer_cache_misses_when_registry_changes(legifrance_doc, monkeypatch, tmp_path):
    _enable_answer_cache(monkeypatch, tmp_path)
    registry = _registry(legifrance_doc)
    s9 = _para(registry, 9).id
    first_client = _fake(registry, relevant={s9})
    mistral = _fake_mistral(monkeypatch, f"La Cour confirme l'arrêt [{s9}].")

    asyncio.run(ask(registry, "Que décide la Cour ?", first_client))
    modified = registry.model_copy(deep=True)
    modified.entries[0] = modified.entries[0].model_copy(update={"text": modified.entries[0].text + " modifié"})
    second_client = _fake(modified, relevant={s9})
    asyncio.run(ask(modified, "Que décide la Cour ?", second_client))

    assert first_client.decide_calls > 0 and second_client.decide_calls > 0
    assert mistral.models == ["draft-model", "draft-model"]


def test_answer_cache_misses_when_solution_changes(legifrance_doc, monkeypatch, tmp_path):
    _enable_answer_cache(monkeypatch, tmp_path)
    registry = _registry(legifrance_doc)
    s9 = _para(registry, 9).id
    client = _fake(registry, relevant={s9})
    monkeypatch.setattr(answer_module, "draft", lambda q, context, model=None: f"Les parties sont en désaccord [{s9}].")

    asyncio.run(ask(registry, "Que décide la Cour ?", client, solution=Solution.REJET))
    calls_after_first = client.decide_calls
    asyncio.run(ask(registry, "Que décide la Cour ?", client, solution=Solution.CASSATION))

    assert client.decide_calls > calls_after_first


def test_answer_cache_key_includes_threshold_and_registry_overrides(legifrance_doc, monkeypatch):
    registry = _registry(legifrance_doc)
    monkeypatch.setattr(answer_module.feedback, "ok_threshold", lambda: 0.8)
    original_key = answer_module._answer_cache_key(registry, "Question ?", None)

    monkeypatch.setattr(answer_module.feedback, "ok_threshold", lambda: 0.7)
    threshold_key = answer_module._answer_cache_key(registry, "Question ?", None)
    answer_module.feedback.set_override("doc", registry.entries[0].id, answer_module.Speaker.COUR_CASSATION)
    overridden = answer_module.feedback.apply_overrides(registry)
    override_key = answer_module._answer_cache_key(overridden, "Question ?", None)

    assert original_key != threshold_key
    assert threshold_key != override_key


def test_answer_cache_can_be_disabled(legifrance_doc, monkeypatch, tmp_path):
    _enable_answer_cache(monkeypatch, tmp_path)
    monkeypatch.setenv("ANSWER_CACHE", "0")
    registry = _registry(legifrance_doc)
    s9 = _para(registry, 9).id
    client = _fake(registry, relevant={s9})
    mistral = _fake_mistral(monkeypatch, f"La Cour confirme l'arrêt [{s9}].")

    asyncio.run(ask(registry, "Que décide la Cour ?", client))
    calls_after_first = client.decide_calls
    asyncio.run(ask(registry, "Que décide la Cour ?", client))

    assert client.decide_calls > calls_after_first
    assert mistral.models == ["draft-model", "draft-model"]


def test_answer_cache_stores_abstentions(legifrance_doc, monkeypatch, tmp_path):
    _enable_answer_cache(monkeypatch, tmp_path)
    registry = _registry(legifrance_doc)
    client = _fake(registry)
    mistral = _fake_mistral(monkeypatch, "Unused")

    first = asyncio.run(ask(registry, "Question hors sujet ?", client))
    calls_after_first = client.decide_calls
    second = asyncio.run(ask(registry, "Question hors sujet ?", client))

    assert first.abstained and second.abstained
    assert client.decide_calls == calls_after_first
    assert mistral.models == []


def test_corrupt_answer_cache_is_recomputed_and_overwritten(legifrance_doc, monkeypatch, tmp_path):
    _enable_answer_cache(monkeypatch, tmp_path)
    registry = _registry(legifrance_doc)
    s9 = _para(registry, 9).id
    client = _fake(registry, relevant={s9})
    mistral = _fake_mistral(monkeypatch, f"La Cour confirme l'arrêt [{s9}].")

    asyncio.run(ask(registry, "Que décide la Cour ?", client))
    cache_file = next((tmp_path / "answers").rglob("*.json"))
    cache_file.write_text("{broken", encoding="utf-8")
    calls_after_first = client.decide_calls
    asyncio.run(ask(registry, "Que décide la Cour ?", client))

    assert client.decide_calls > calls_after_first
    assert len(mistral.models) == 2
    answer_module.Answer.model_validate_json(cache_file.read_text(encoding="utf-8"))
    assert not list(cache_file.parent.glob(".*.tmp"))


def test_draft_exception_does_not_write_answer_cache(legifrance_doc, monkeypatch, tmp_path):
    _enable_answer_cache(monkeypatch, tmp_path)
    registry = _registry(legifrance_doc)
    s9 = _para(registry, 9).id
    client = _fake(registry, relevant={s9})

    def fail_draft(*args, **kwargs):
        raise RuntimeError("draft failed")

    monkeypatch.setattr(answer_module, "draft", fail_draft)
    with pytest.raises(RuntimeError, match="draft failed"):
        asyncio.run(ask(registry, "Que décide la Cour ?", client))

    assert not (tmp_path / "answers").exists()


def test_revise_model_defaults_to_revise_env_while_draft_uses_answer_env(monkeypatch):
    monkeypatch.setenv("ANSWER_MODEL", "draft-model")
    monkeypatch.setenv("REVISE_MODEL", "revise-model")
    fake = _fake_mistral(monkeypatch, "Phrase.")

    answer_draft("Question ?", [], model=None)
    answer_revise("Phrase à corriger.", [], model=None)
    answer_revise("Phrase à corriger.", [], model="explicit-model")

    assert fake.models == ["draft-model", "revise-model", "explicit-model"]


def test_verify_uses_learned_ok_threshold(legifrance_doc, monkeypatch):
    registry = _registry(legifrance_doc)
    s9 = _para(registry, 9).id
    calls = []

    def learned_threshold():
        calls.append(None)
        return 0.7

    monkeypatch.setattr(answer_module.feedback, "ok_threshold", learned_threshold)
    result = asyncio.run(
        answer_module.verify(f"La Cour confirme l'arrêt [{s9}].", registry, _fake(registry, supported=0.75))
    )

    assert calls == [None]
    assert result[0].pills[0].level == "ok"


def test_answer_context_contains_sorted_retrieved_ids(legifrance_doc, monkeypatch):
    registry = _registry(legifrance_doc)
    selected = registry.entries[:2]
    monkeypatch.setattr(answer_module, "retrieve", lambda *args: asyncio.sleep(0, result=list(reversed(selected))))
    monkeypatch.setattr(answer_module, "draft", lambda *args: answer_module.NOT_ADDRESSED)

    result = asyncio.run(ask(registry, "Question ?", _fake(registry)))

    assert result.abstained
    assert result.context == sorted(entry.id for entry in selected)


def test_pills_carry_speaker_paragraph_and_confidence(legifrance_doc, monkeypatch):
    registry = _registry(legifrance_doc)
    s9, s7 = _para(registry, 9).id, _para(registry, 7).id
    monkeypatch.setattr(answer_module, "draft", lambda q, ctx, m=None: (
        f"La Cour approuve la cour d'appel [{s9}]. Le vendeur soutenait l'inverse [{s7}]. Une phrase sans source."
    ))
    result = asyncio.run(ask(registry, "Que décide la Cour ?", _fake(registry, relevant={s9, s7})))
    first, second, third = result.sentences
    assert first.pills[0].label == "Cour, approuvant la cour d'appel" and first.pills[0].paragraph == 9 and first.pills[0].level == "ok"
    assert first.pills[0].tier == "sur" and first.pills[0].tier_label == "Sûr"
    assert any("dit bien" in reason for reason in first.pills[0].reasons)
    assert second.pills[0].paragraph == 7
    assert third.pills == [] and third.supported == 0.0
    assert "[Cour, approuvant la cour d'appel · §9 · " in result.render() and "[non sourcé ⚠]" in result.render()


def test_low_verification_downgrades_pill(legifrance_doc, monkeypatch):
    registry = _registry(legifrance_doc)
    s9 = _para(registry, 9).id
    monkeypatch.setattr(answer_module, "draft", lambda q, ctx, m=None: f"La Cour casse l'arrêt [{s9}].")
    result = asyncio.run(ask(registry, "Que décide la Cour ?", _fake(registry, relevant={s9}, supported=0.2)))
    assert result.sentences[0].pills[0].level == "unsupported"


def test_jev_runner_up_is_named_in_pill_reasons(legifrance_doc):
    registry = _registry(legifrance_doc)
    entry = _para(registry, 7)
    pill = _verified_pill(
        registry,
        entry,
        "Le demandeur soutient sa thèse",
        0.9,
        source="jev",
        speaker=Decision(
            value=Speaker.DEMANDEUR.value,
            probabilities={"DEMANDEUR": 0.6, "JURIDICTION_FOND": 0.4},
            confidence=0.6,
        ),
    )

    assert pill.tier == "probable"
    assert "Jev hésite entre Demandeur et Cour d'appel." in pill.reasons
    assert {speaker.value for speaker in Speaker} <= answer_module.SPEAKER_LABELS.keys()


def test_low_support_sets_uncertain_or_false_tier_and_weakest_reason_first(legifrance_doc):
    registry = _registry(legifrance_doc)
    entry = _para(registry, 9)

    uncertain = _verified_pill(registry, entry, "La Cour confirme cet élément", 0.3)
    false = _verified_pill(registry, entry, "La Cour confirme cet élément", 0.1)

    assert uncertain.tier == "incertain"
    assert uncertain.reasons[0] == "Le passage cité ne permet pas de confirmer la phrase."
    assert false.tier == "faux"
    assert any("contredit" in reason for reason in false.reasons)


def test_lawyer_source_is_explained_as_human_confirmed(legifrance_doc):
    registry = _registry(legifrance_doc)
    entry = _para(registry, 9)
    pill = _verified_pill(registry, entry, "La Cour confirme cet élément", 0.9, source="lawyer")

    assert "Locuteur confirmé par un avocat." in pill.reasons


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


def test_lexical_match_is_added_alongside_jev_picks(legifrance_doc):
    from lawhack.answer import retrieve

    registry = _registry(legifrance_doc)
    s8, s10 = _para(registry, 8).id, _para(registry, 10).id
    question = "La Cour de cassation a-t-elle constaté que la banque avait refusé le prêt des acquéreurs ?"
    picked = asyncio.run(retrieve(registry, question, _fake(registry, relevant={s10})))

    assert {s8, s10} <= {e.id for e in picked}


def test_flagged_sentence_is_rewritten_when_reverification_improves(legifrance_doc, monkeypatch):
    registry = _registry(legifrance_doc)
    s8 = _para(registry, 8).id
    fake = _fake(registry, relevant={s8}, supported=0.2)
    monkeypatch.setattr(answer_module, "draft", lambda q, ctx, m=None: f"Les acquéreurs ont obtenu leur prêt [{s8}].")

    def revise(sentence, cited, model=None):
        assert [c.id for c in cited] == [s8] and "obtenu" in sentence
        fake.supported = 0.95
        return f"La cour d'appel a relevé que la banque avait refusé le prêt [{s8}]."

    monkeypatch.setattr(answer_module, "revise", revise)
    result = asyncio.run(ask(registry, "Les acquéreurs ont-ils obtenu leur prêt ?", fake))
    (only,) = result.sentences
    assert only.text.startswith("La cour d'appel a relevé") and only.revised_from == "Les acquéreurs ont obtenu leur prêt."
    assert only.pills[0].level == "ok"


def test_rewrite_is_dropped_or_ignored(legifrance_doc, monkeypatch):
    registry = _registry(legifrance_doc)
    s8, s9 = _para(registry, 8).id, _para(registry, 9).id
    monkeypatch.setattr(answer_module, "draft", lambda q, ctx, m=None: f"Phrase inventée [{s8}]. Autre phrase [{s9}].")
    calls = []
    monkeypatch.setattr(answer_module, "revise", lambda s, c, m=None: calls.append(s) or ("SUPPRIMER" if len(calls) == 1 else f"Toujours faux [{s9}]."))
    result = asyncio.run(ask(registry, "Que décide la Cour ?", _fake(registry, relevant={s8, s9}, supported=0.2)))
    assert len(calls) == 2
    (kept,) = result.sentences
    assert kept.text == "Autre phrase." and kept.revised_from is None and kept.pills[0].level == "unsupported"


def test_rewrite_citing_other_passage_is_rejected(legifrance_doc, monkeypatch):
    registry = _registry(legifrance_doc)
    s8, s9 = _para(registry, 8).id, _para(registry, 9).id
    fake = _fake(registry, relevant={s8}, supported=0.2)
    monkeypatch.setattr(answer_module, "draft", lambda q, ctx, m=None: f"Phrase douteuse [{s8}].")

    def revise(sentence, cited, model=None):
        fake.supported = 0.95
        return f"Autre affirmation [{s9}]."

    monkeypatch.setattr(answer_module, "revise", revise)
    (only,) = asyncio.run(ask(registry, "?", fake)).sentences
    assert only.text == "Phrase douteuse." and only.revised_from is None


def test_recheck_failure_keeps_draft_and_removing_everything_abstains(legifrance_doc, monkeypatch):
    registry = _registry(legifrance_doc)
    s8 = _para(registry, 8).id
    fake = _fake(registry, relevant={s8}, supported=0.2)
    monkeypatch.setattr(answer_module, "draft", lambda q, ctx, m=None: f"Phrase douteuse [{s8}].")
    real_verify = answer_module.verify
    calls = []

    async def flaky_verify(text, reg, client):
        calls.append(text)
        if len(calls) > 1:
            raise RuntimeError("Jev timeout")
        return await real_verify(text, reg, client)

    monkeypatch.setattr(answer_module, "verify", flaky_verify)
    monkeypatch.setattr(answer_module, "revise", lambda s, c, m=None: f"Réécrite [{s8}].")
    (only,) = asyncio.run(ask(registry, "?", fake)).sentences
    assert only.text == "Phrase douteuse." and only.pills[0].level == "unsupported"

    monkeypatch.setattr(answer_module, "verify", real_verify)
    monkeypatch.setattr(answer_module, "revise", lambda s, c, m=None: "SUPPRIMER")
    result = asyncio.run(ask(registry, "?", fake))
    assert result.abstained and result.sentences == []


def test_contradicted_sentence_is_dropped_when_rewrite_fails(legifrance_doc, monkeypatch):
    registry = _registry(legifrance_doc)
    s9 = _para(registry, 9).id
    monkeypatch.setattr(
        answer_module,
        "draft",
        lambda q, ctx, m=None: f"La Cour de cassation a partiellement cassé cet arrêt [{s9}].",
    )

    result = asyncio.run(
        ask(registry, "Que décide la Cour ?", _fake(registry, relevant={s9}), solution=Solution.REJET)
    )

    assert result.abstained and result.sentences == []


def test_contradicted_sentence_can_be_rewritten_to_match_solution(legifrance_doc, monkeypatch):
    registry = _registry(legifrance_doc)
    s9 = _para(registry, 9).id
    fake = _fake(registry, relevant={s9}, supported=0.2)
    monkeypatch.setattr(
        answer_module,
        "draft",
        lambda q, ctx, m=None: f"La Cour de cassation a partiellement cassé cet arrêt [{s9}].",
    )

    def revise(sentence, cited, model=None):
        assert "Problème : Contredit par le dispositif" in sentence
        fake.supported = 0.95
        return f"La Cour de cassation a rejeté le pourvoi [{s9}]."

    monkeypatch.setattr(answer_module, "revise", revise)
    result = asyncio.run(
        ask(registry, "Que décide la Cour ?", fake, solution=Solution.REJET)
    )

    (only,) = result.sentences
    assert only.text == "La Cour de cassation a rejeté le pourvoi."
    assert only.revised_from == "La Cour de cassation a partiellement cassé cet arrêt."


def test_lower_court_reported_in_a_moyen_is_a_warning(legifrance_doc, monkeypatch):
    registry = _registry(legifrance_doc)
    s7 = next(e for e in registry.entries if e.paragraph == 7 and e.speaker.value == "DEMANDEUR")
    monkeypatch.setattr(answer_module, "draft", lambda q, ctx, m=None: f"La cour d'appel a statué [{s7.id}]. Elle a déclaré la promesse caduque [{s7.id}]. Le vendeur soutient que la cour d'appel a violé la loi [{s7.id}].")
    result = asyncio.run(ask(registry, "Qu'a décidé la cour d'appel ?", _fake(registry, relevant={s7.id}, supported=0.1)))
    first, pronoun, party = (s.pills[0] for s in result.sentences)
    assert first.level == pronoun.level == "warn"
    assert pronoun.tier == "probable"
    assert pronoun.note.startswith("Rapporté par le demandeur (§7)")
    assert pronoun.note in pronoun.reasons
    assert party.note is None
