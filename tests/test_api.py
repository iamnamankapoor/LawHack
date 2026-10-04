from fastapi.testclient import TestClient

from legible.api import app

client = TestClient(app)
RED = "C2_soc_2026-09-11_24-21242"


def test_index_is_utf8_french():
    r = client.get("/")
    assert "charset=utf-8" in r.headers["content-type"]
    assert "Qui parle dans cette décision" in r.text


def test_samples_and_analyze():
    assert any(s["id"] == RED for s in client.get("/api/samples").json())
    d = client.post("/api/analyze", data={"sample": RED}).json()
    p8 = next(s for s in d["segments"] if s["ref"] == "§8")
    assert (p8["speaker"], p8["stance"]) == ("cour_appel", "not_ruled")
    assert d["holdings"]["solution"] == "CASSATION_PARTIELLE"


def test_analyze_rejects_short_text():
    assert client.post("/api/analyze", data={"text": "trop court"}).status_code == 422


def test_ask_returns_checked_answer_with_references():
    client.post("/api/analyze", data={"sample": RED})
    r = client.post("/api/ask", json={"id": RED, "question": "Selon la Cour, … ?"}).json()
    assert r["references"][0]["ref"] == "§8"
    assert r["guard_p"] < 0.5 and r["outcome_error"] is None


def test_check_flags_misattributed_sentence():
    draft = "Selon la Cour de cassation, l'absence de management ne suffit pas à rendre l'offre déloyale. La Cour casse l'arrêt."
    out = client.post("/api/check", json={"id": RED, "draft": draft}).json()["sentences"]
    assert out[0]["verdict"] == "a_corriger" and out[0]["rewrite"]
