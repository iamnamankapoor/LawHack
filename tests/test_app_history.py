import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import server
from lawhack.answer import Answer
from lawhack.schema import Decision, Document, Registry, RegistryEntry, Speaker, StatementType, Status, Zone
from lawhack.solution import Solution


def _registry(document_id):
    return Registry(
        document_id=document_id,
        entries=[
            RegistryEntry(
                id=f"{document_id}-S1",
                text="La Cour statue.",
                start=0,
                end=16,
                block=0,
                zone=Zone.DISPOSITIF,
                paragraph=4,
                speaker=Decision(
                    value=Speaker.COUR_CASSATION.value,
                    probabilities={Speaker.COUR_CASSATION.value: 1.0},
                    confidence=1.0,
                ),
                type=Decision(value=StatementType.DISPOSITIF.value),
                status=Decision(value=Status.DECIDE.value),
                source="rule",
            )
        ],
    )


@pytest.fixture
def history_client(monkeypatch, tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setattr(server, "ROOT", root)
    monkeypatch.setattr(server, "HISTORY", root / "data" / "history.json")
    monkeypatch.setattr(server, "UPLOADS", root / "data" / "raw")
    monkeypatch.setattr(server, "_registries", {})
    monkeypatch.setattr(server, "_answers", {})

    def fake_load(path):
        text = Path(path).read_text(encoding="utf-8")
        document_id = hashlib.sha256(text.encode()).hexdigest()[:16]
        return Document(id=document_id, text=text)

    monkeypatch.setattr(server, "load", fake_load)
    monkeypatch.setattr(server, "analyse", lambda doc: (_registry(doc.id), Solution.REJET))
    return TestClient(server.app)


def _upload(client, filename, text):
    return client.post(
        "/api/documents",
        files={"file": (filename, text.encode("utf-8"), "text/plain")},
    )


def test_reupload_deduplicates_history_and_uses_original_filename_title(history_client):
    text = "Arrêt relatif au pourvoi n° 21-24.539."

    first = _upload(history_client, "arret.txt", text)
    second = _upload(history_client, "arret.txt", text)

    assert first.status_code == second.status_code == 200
    assert first.json()["title"] == "arret · n° 21-24.539"
    assert second.json()["title"] == first.json()["title"]
    documents = history_client.get("/api/documents").json()["documents"]
    assert len(documents) == 1
    assert documents[0]["document_id"] == first.json()["document_id"]


def test_demo_uses_fixed_title(history_client, monkeypatch, tmp_path):
    demo_path = tmp_path / "demo.pdf"
    demo_path.write_text("Décision de démonstration.", encoding="utf-8")
    monkeypatch.setattr(server, "DEMO_PDF", demo_path)

    response = history_client.post("/api/documents/demo")

    assert response.status_code == 200
    assert response.json()["title"] == "Civ. 3, 14 déc. 2022"


def test_documents_are_newest_first_and_hide_internal_paths(history_client):
    older = _upload(history_client, "premier.txt", "Premier arrêt.")
    newer = _upload(history_client, "second.txt", "Deuxième arrêt.")

    assert older.status_code == newer.status_code == 200
    listed = history_client.get("/api/documents").json()["documents"]

    assert [item["document_id"] for item in listed] == [
        newer.json()["document_id"],
        older.json()["document_id"],
    ]
    assert all("path" not in item for item in listed)


def test_reopen_restores_registry_for_asking(history_client, monkeypatch):
    uploaded = _upload(history_client, "arret.txt", "Arrêt relatif au pourvoi n° 21-24.539.")
    document_id = uploaded.json()["document_id"]
    server._registries.clear()

    reopened = history_client.get(f"/api/documents/{document_id}")

    assert reopened.status_code == 200
    assert reopened.json()["title"] == uploaded.json()["title"]
    assert reopened.json()["entries"][0]["id"] == f"{document_id}-S1"
    assert document_id in server._registries

    async def fake_ask(registry, question, client, solution=None):
        assert registry.document_id == document_id
        return Answer(question=question, sentences=[])

    monkeypatch.setattr(server, "ask", fake_ask)
    monkeypatch.setattr(server, "TypeSafeSystemOne", lambda: object())
    answer = history_client.post(
        f"/api/documents/{document_id}/ask",
        json={"question": "Que décide la Cour ?"},
    )
    assert answer.status_code == 200


def test_reopen_unknown_document_returns_404(history_client):
    response = history_client.get("/api/documents/inconnu")

    assert response.status_code == 404
    assert response.json()["detail"] == "Arrêt introuvable : déposez-le à nouveau."


def test_missing_or_corrupt_history_lists_no_documents(history_client):
    assert history_client.get("/api/documents").json() == {"documents": []}
    server.HISTORY.parent.mkdir(parents=True, exist_ok=True)
    server.HISTORY.write_text("{corrupt", encoding="utf-8")

    assert history_client.get("/api/documents").json() == {"documents": []}


def test_deleted_history_file_is_hidden_and_cannot_be_reopened(history_client):
    uploaded = _upload(history_client, "arret.txt", "Arrêt conservé dans l'historique.")
    document_id = uploaded.json()["document_id"]
    entry = server._history_entries()[0]
    (server.ROOT / entry["path"]).unlink()

    assert history_client.get("/api/documents").json()["documents"] == []
    response = history_client.get(f"/api/documents/{document_id}")
    assert response.status_code == 404
    assert response.json()["detail"] == "Arrêt introuvable : déposez-le à nouveau."
