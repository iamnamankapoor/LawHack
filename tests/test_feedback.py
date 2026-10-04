import asyncio
import json

from lawhack import feedback
from lawhack.pipeline import analyse_async
from lawhack.schema import Decision, Document, Registry, RegistryEntry, Speaker, StatementType, Status, Zone


def _event(verdict, confidence=None, **kwargs):
    return feedback.FeedbackEvent(
        ts=1.0,
        document_id="doc",
        question="Question ?",
        verdict=verdict,
        confidence=confidence,
        **kwargs,
    )


def _registry():
    entry = RegistryEntry(
        id="S-001",
        text="La Cour statue.",
        start=0,
        end=16,
        block=0,
        zone=Zone.MOTIVATIONS,
        speaker=Decision(value=Speaker.DEMANDEUR.value, probabilities={Speaker.DEMANDEUR.value: 0.8}, confidence=0.8),
        type=Decision(value=StatementType.MOTIF.value),
        status=Decision(value=Status.DECIDE.value),
        source="jev",
    )
    return Registry(document_id="doc", entries=[entry])


def test_threshold_defaults_below_minimum_labels():
    assert feedback.ok_threshold() == 0.8
    assert feedback.stats()["default_threshold"] == 0.8


def test_threshold_learns_smallest_threshold_with_target_precision():
    for confidence in [0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 0.99]:
        feedback.record(_event("correct", confidence))
    for confidence in [0.5, 0.55, 0.6, 0.65, 0.69] * 3:
        feedback.record(_event("wrong_speaker", confidence))

    assert feedback.ok_threshold() == 0.7


def test_threshold_uses_upper_bound_when_precision_is_not_reached():
    for confidence in [0.55, 0.6, 0.7, 0.8, 0.9] * 4:
        feedback.record(_event("unsupported", confidence))

    assert feedback.ok_threshold() == 0.95


def test_overrides_are_persisted_and_applied():
    registry = _registry()
    feedback.set_override("doc", "S-001", Speaker.COUR_CASSATION)

    updated = feedback.apply_overrides(registry)
    entry = updated.by_id("S-001")

    assert feedback.overrides("doc") == {"S-001": Speaker.COUR_CASSATION}
    assert entry.speaker.value == Speaker.COUR_CASSATION.value
    assert entry.speaker.confidence == 1.0 and entry.speaker.probabilities == {"COUR_CASSATION": 1.0}
    assert entry.chain == [Speaker.COUR_CASSATION]
    assert entry.source == "lawyer"
    assert registry.by_id("S-001").speaker.value == Speaker.DEMANDEUR.value
    assert json.loads((feedback.FEEDBACK_DIR / "overrides" / "doc.json").read_text()) == {
        "S-001": "COUR_CASSATION"
    }


def test_apply_overrides_returns_copy_without_changes():
    registry = _registry()
    updated = feedback.apply_overrides(registry)

    assert updated is not registry
    assert updated.model_dump() == registry.model_dump()


def test_stats_counts_pill_and_answer_feedback():
    feedback.record(_event("correct", 0.9))
    feedback.record(_event("wrong_speaker", 0.7))
    feedback.record(_event("unsupported", 0.6))
    feedback.record(_event("up"))
    feedback.record(_event("down"))

    assert feedback.stats() == {
        "labels": 3,
        "correct": 1,
        "ok_threshold": 0.8,
        "default_threshold": 0.8,
        "min_labels": feedback.MIN_LABELS,
        "corrections": 1,
        "validated_answers": 1,
    }


def test_events_skip_unreadable_lines():
    event = _event("correct", 0.9)
    event_file = feedback.FEEDBACK_DIR / "events.jsonl"
    event_file.parent.mkdir(parents=True)
    event_file.write_bytes(event.model_dump_json().encode("utf-8") + b"\n\xff\n")

    assert feedback.events() == [event]


def test_pipeline_applies_overrides_to_cached_registry(tmp_path, monkeypatch):
    from lawhack import pipeline

    registry = _registry()
    monkeypatch.setattr(pipeline, "CACHE_DIR", tmp_path / "cache")
    pipeline.CACHE_DIR.mkdir()
    cache_file = pipeline.CACHE_DIR / "doc.json"
    cache_file.write_text(registry.model_dump_json())
    monkeypatch.setattr(pipeline, "is_current", lambda cached, client: True)
    feedback.set_override("doc", "S-001", Speaker.COUR_CASSATION)

    analyzed, _ = asyncio.run(analyse_async(Document(id="doc", text="Faits et procédure"), use_cache=True))

    assert analyzed.by_id("S-001").speaker.value == Speaker.COUR_CASSATION.value
    assert Registry.model_validate_json(cache_file.read_text()).by_id("S-001").source == "jev"


def test_pipeline_applies_overrides_to_fresh_registry(tmp_path, monkeypatch):
    from lawhack import pipeline

    registry = _registry()
    monkeypatch.setattr(pipeline, "CACHE_DIR", tmp_path / "cache")

    async def fake_build_registry(document_id, segments, client):
        return registry

    monkeypatch.setattr(pipeline, "build_registry", fake_build_registry)
    feedback.set_override("doc", "S-001", Speaker.COUR_CASSATION)

    analyzed, _ = asyncio.run(
        analyse_async(Document(id="doc", text="Faits et procédure"), use_cache=False)
    )

    assert analyzed.by_id("S-001").speaker.value == Speaker.COUR_CASSATION.value
    assert Registry.model_validate_json((pipeline.CACHE_DIR / "doc.json").read_text()).by_id("S-001").source == "jev"
