import json

from lawhack import feedback, pipeline
from lawhack.answer import Answer, AnswerSentence, Pill, draft_user_message
from lawhack.schema import Decision, Registry, RegistryEntry, Speaker, StatementType, Status, Zone
from scripts import export_training


def _registry():
    entry = RegistryEntry(
        id="S-001",
        text="Le demandeur soutient sa thèse.",
        start=0,
        end=33,
        block=0,
        zone=Zone.MOYENS,
        paragraph=2,
        speaker=Decision(value=Speaker.DEMANDEUR.value, probabilities={Speaker.DEMANDEUR.value: 1.0}, confidence=1.0),
        type=Decision(value=StatementType.MOYEN.value),
        status=Decision(value=Status.ALLEGUE.value),
        source="jev",
    )
    return Registry(document_id="doc", entries=[entry])


def test_export_training_writes_sft_preferences_and_attribution_gold(tmp_path, monkeypatch):
    registry = _registry()
    monkeypatch.setattr(pipeline, "CACHE_DIR", tmp_path / "cache")
    pipeline.CACHE_DIR.mkdir()
    (pipeline.CACHE_DIR / "doc.json").write_text(registry.model_dump_json(), encoding="utf-8")
    feedback.set_override("doc", "S-001", Speaker.COUR_CASSATION)
    answer = Answer(
        question="Que soutient le demandeur ?",
        context=["S-001"],
        sentences=[
            AnswerSentence(
                text="Le demandeur avance cet argument.",
                revised_from="Cet argument est établi.",
                supported=0.9,
                pills=[
                    Pill(
                        segment_id="S-001",
                        speaker=Speaker.COUR_CASSATION.value,
                        label="Cour",
                        paragraph=2,
                        zone_label="Énoncé du moyen",
                        confidence=0.9,
                        level="ok",
                        source_text=registry.entries[0].text,
                        probabilities={Speaker.COUR_CASSATION.value: 1.0},
                    )
                ],
            )
        ],
    )
    feedback.record(feedback.FeedbackEvent(
        ts=1.0,
        document_id="doc",
        question=answer.question,
        verdict="up",
        answer=answer.model_dump(),
    ))
    feedback.record(feedback.FeedbackEvent(
        ts=2.0,
        document_id="doc",
        question="No context",
        verdict="up",
        answer=Answer(question="No context", sentences=[], context=[]).model_dump(),
    ))
    feedback.record(feedback.FeedbackEvent(
        ts=3.0,
        document_id="missing",
        question="No registry",
        verdict="up",
        answer=answer.model_dump(),
    ))
    out = tmp_path / "export"

    counts = export_training.export(out)

    assert counts == {"sft": 1, "preferences": 1, "attribution_gold": 1}
    sft = json.loads((out / "sft.jsonl").read_text(encoding="utf-8"))
    assert sft["messages"][0] == {"role": "system", "content": export_training.SYSTEM_PROMPT}
    assert sft["messages"][1] == {
        "role": "user",
        "content": draft_user_message(answer.question, feedback.apply_overrides(registry).entries),
    }
    assert sft["messages"][2]["content"] == "Le demandeur avance cet argument. [S-001]"
    preferences = [
        json.loads(line)
        for line in (out / "preferences.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert preferences == [{
        "prompt": sft["messages"][1]["content"],
        "chosen": "Le demandeur avance cet argument.",
        "rejected": "Cet argument est établi.",
    }]
    gold = [
        json.loads(line)
        for line in (out / "attribution_gold.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert gold == [{
        "document_id": "doc",
        "segment_id": "S-001",
        "text": registry.entries[0].text,
        "zone": Zone.MOYENS.value,
        "speaker": Speaker.COUR_CASSATION.value,
    }]
