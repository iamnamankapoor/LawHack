import pytest
from fastapi.testclient import TestClient

from app import server
from lawhack import pipeline
from lawhack.ingest import load_pdf


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setattr(pipeline, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(server, "ROOT", tmp_path)
    monkeypatch.setattr(server, "HISTORY", tmp_path / "history.json")
    monkeypatch.setattr(server, "UPLOADS", tmp_path / "raw")


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "cp1252"])
def test_upload_txt_decision(encoding):
    text = load_pdf(server.DEMO_PDF).text.replace("\n", "\r\n")
    response = TestClient(server.app).post("/api/documents", files={"file": ("arret.txt", text.encode(encoding), "text/plain")})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["entries"]
    assert any("cassation" in e["text"].lower() for e in body["entries"])
    assert not any("\ufffd" in e["text"] or "\r" in e["text"] for e in body["entries"])


def test_upload_rejects_other_formats():
    response = TestClient(server.app).post("/api/documents", files={"file": ("arret.docx", b"x", "application/octet-stream")})
    assert response.status_code == 400
