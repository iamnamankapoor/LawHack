from fastapi.testclient import TestClient

from app import server
from lawhack import feedback
from lawhack.answer import Answer, AnswerSentence, Pill
from lawhack.schema import Decision, Registry, RegistryEntry, Speaker, StatementType, Status, Zone
from lawhack.solution import Solution


def _entry():
    return RegistryEntry(
        id="S-001",
        text="La Cour statue.",
        start=0,
        end=16,
        block=0,
        zone=Zone.MOTIVATIONS,
        paragraph=4,
        speaker=Decision(value=Speaker.DEMANDEUR.value, probabilities={Speaker.DEMANDEUR.value: 0.8}, confidence=0.8),
        type=Decision(value=StatementType.MOTIF.value),
        status=Decision(value=Status.DECIDE.value),
        source="jev",
    )


def _answer():
    pill = Pill(
        segment_id="S-001",
        speaker=Speaker.DEMANDEUR.value,
        label="Demandeur",
        paragraph=4,
        zone_label="Réponse de la Cour",
        confidence=0.8,
        level="warn",
        source_text="La Cour statue.",
        probabilities={Speaker.DEMANDEUR.value: 0.8},
    )
    return Answer(
        question="Que décide la Cour ?",
        sentences=[AnswerSentence(text="Le demandeur soutient cela.", pills=[pill], supported=0.85)],
        context=["S-001"],
    )


def _client(monkeypatch):
    monkeypatch.setattr(server, "_answers", {})
    monkeypatch.setattr(server, "_registries", {
        "doc": (Registry(document_id="doc", entries=[_entry()]), Solution.REJET)
    })
    answer = _answer()

    async def fake_ask(registry, question, client, solution=None):
        return answer

    monkeypatch.setattr(server, "ask", fake_ask)
    return TestClient(server.app), answer


def test_ask_returns_answer_id_and_wrong_speaker_updates_registry(monkeypatch):
    client, _ = _client(monkeypatch)
    response = client.post("/api/documents/doc/ask", json={"question": "Que décide la Cour ?"})

    assert response.status_code == 200
    body = response.json()
    answer_id = body["answer_id"]
    assert len(answer_id) == 12
    assert server._answers[answer_id][0] == "doc"

    feedback_response = client.post("/api/feedback", json={
        "answer_id": answer_id,
        "verdict": "wrong_speaker",
        "sentence_index": 0,
        "segment_id": "S-001",
        "speaker": "COUR_CASSATION",
    })

    assert feedback_response.status_code == 200
    updated = feedback_response.json()["entry"]
    assert updated == {
        "id": "S-001",
        "paragraph": 4,
        "zone": "Réponse de la Cour",
        "speaker": "COUR_CASSATION",
        "label": "Cour",
        "confidence": 1.0,
        "text": "La Cour statue.",
    }
    registry, solution = server._registries["doc"]
    assert solution is Solution.REJET
    assert registry.by_id("S-001").source == "lawyer"
    assert registry.by_id("S-001").speaker.confidence == 1.0


def test_feedback_endpoint_rejects_unknown_answers_and_invalid_pills(monkeypatch):
    client, answer = _client(monkeypatch)
    server._answers["known"] = ("doc", answer)

    assert client.post("/api/feedback", json={"answer_id": "missing", "verdict": "up"}).status_code == 404
    missing = client.post("/api/feedback", json={"answer_id": "known", "verdict": "correct"})
    assert missing.status_code == 422
    bad_index = client.post("/api/feedback", json={
        "answer_id": "known", "verdict": "correct", "sentence_index": 5, "segment_id": "S-001"
    })
    assert bad_index.status_code == 422
    bad_segment = client.post("/api/feedback", json={
        "answer_id": "known", "verdict": "correct", "sentence_index": 0, "segment_id": "S-999"
    })
    assert bad_segment.status_code == 422
    bad_speaker = client.post("/api/feedback", json={
        "answer_id": "known",
        "verdict": "wrong_speaker",
        "sentence_index": 0,
        "segment_id": "S-001",
        "speaker": "UNKNOWN",
    })
    assert bad_speaker.status_code == 422
    assert client.post("/api/feedback", json={"answer_id": "known", "verdict": "maybe"}).status_code == 422


def test_correct_feedback_overrides_to_shown_speaker_and_answer_vote_is_recorded(monkeypatch):
    client, _ = _client(monkeypatch)
    server._answers["known"] = ("doc", _answer())

    correct = client.post("/api/feedback", json={
        "answer_id": "known",
        "verdict": "correct",
        "sentence_index": 0,
        "segment_id": "S-001",
    })
    assert correct.status_code == 200
    registry, _ = server._registries["doc"]
    assert registry.by_id("S-001").speaker.value == Speaker.DEMANDEUR.value
    assert registry.by_id("S-001").source == "lawyer"

    up = client.post("/api/feedback", json={"answer_id": "known", "verdict": "up"})
    assert up.status_code == 200
    assert up.json()["entry"] is None
    assert up.json()["learning"]["validated_answers"] == 1
    down = client.post("/api/feedback", json={"answer_id": "known", "verdict": "down"})
    assert down.status_code == 200
    assert down.json()["learning"]["validated_answers"] == 1
    assert client.get("/api/learning").json()["validated_answers"] == 1
    assert [event.verdict for event in feedback.events()] == ["correct", "up", "down"]


def test_unsupported_feedback_does_not_override_registry(monkeypatch):
    client, _ = _client(monkeypatch)
    server._answers["known"] = ("doc", _answer())

    response = client.post("/api/feedback", json={
        "answer_id": "known",
        "verdict": "unsupported",
        "sentence_index": 0,
        "segment_id": "S-001",
    })

    assert response.status_code == 200
    assert response.json()["entry"] is None
    registry, _ = server._registries["doc"]
    assert registry.by_id("S-001").speaker.value == Speaker.DEMANDEUR.value
    assert feedback.overrides("doc") == {}
