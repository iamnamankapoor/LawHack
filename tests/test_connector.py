import asyncio
import base64

import pytest
from fastapi.testclient import TestClient
from fastmcp import Client

from lawhack import service
from server.mcp_server import mcp

SAMPLE = "cass_civ3_2022-12-14_21-24539"
TRAP = (
    "La Cour de cassation juge que le vendeur a droit à l'indemnité d'immobilisation car la demande de prêt n'était pas conforme. "
    "La Cour condamne le notaire à des dommages-intérêts pour faute lourde. "
    "Le pourvoi est rejeté par la Cour. "
    "La cour d'appel a retenu à bon droit que le montant maximal du prêt ne contraignait pas les acquéreurs."
)


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setattr(service, "CACHE_DIR", tmp_path, raising=False)
    service._STORE.clear()


@pytest.fixture
def decision_id():
    return asyncio.run(service.load_decision(sample=SAMPLE)).decision_id


def test_load_sample():
    summary = asyncio.run(service.load_decision(sample=SAMPLE))
    assert summary.solution == "REJET"
    assert summary.heuristic_mode
    assert any("REJETTE" in p.text for p in summary.dispositif)


def test_load_requires_exactly_one_source():
    with pytest.raises(ValueError):
        asyncio.run(service.load_decision())
    with pytest.raises(ValueError):
        asyncio.run(service.load_decision(text="a", sample=SAMPLE))


def test_load_pdf_base64():
    data = base64.b64encode((service.SAMPLES_DIR / f"{SAMPLE}.pdf").read_bytes()).decode()
    assert asyncio.run(service.load_decision(pdf_base64=data)).solution == "REJET"


def test_verify_catches_attribution_errors(decision_id):
    verdicts = [s.verdict for s in service.verify_text(decision_id, TRAP).sentences]
    assert verdicts == ["MAL_ATTRIBUE", "NON_SOURCE", "OK", "OK"]


def test_who_said_returns_voices(decision_id):
    result = service.who_said(decision_id, "La cour d'appel a-t-elle retenu que la demande de prêt était conforme ?")
    assert result.answer_status == "answered"
    assert {"JURIDICTION_FOND", "COUR_CASSATION"} & {p.speaker for p in result.passages}


def test_unknown_decision():
    with pytest.raises(KeyError):
        service.who_said("nope", "question")


def test_mcp_tools_end_to_end():
    async def run():
        async with Client(mcp) as client:
            names = {t.name for t in await client.list_tools()}
            assert names == {"lawhack_load_decision", "lawhack_who_said", "lawhack_verify", "lawhack_get_passage"}
            loaded = await client.call_tool("lawhack_load_decision", {"sample": SAMPLE})
            did = loaded.structured_content["decision_id"]
            verified = await client.call_tool("lawhack_verify", {"decision_id": did, "text": TRAP})
            assert verified.structured_content["summary"]["MAL_ATTRIBUE"] == 1
            passages = await client.call_tool("lawhack_get_passage", {"decision_id": did, "segment_id": "S-013", "context": 0})
            assert "fait grief" in passages.content[0].text
            bad = await client.call_tool("lawhack_who_said", {"decision_id": "nope", "question": "x"}, raise_on_error=False)
            assert bad.is_error

    asyncio.run(run())


def test_rest_and_auth(monkeypatch):
    from server import app as app_module

    with TestClient(app_module.app) as http:
        assert http.get("/health").json()["status"] == "ok"
        did = http.post("/api/decisions", json={"sample": SAMPLE}).json()["decision_id"]
        r = http.post(f"/api/decisions/{did}/verify", json={"text": TRAP})
        assert r.json()["summary"]["MAL_ATTRIBUE"] == 1
        assert http.get(f"/api/decisions/{did}/segments/S-999").status_code == 404

    guarded = app_module.TokenGuard(app_module.api, "secret")
    with TestClient(guarded) as http:
        assert http.get("/api/samples").status_code == 401
        assert http.get("/api/samples", headers={"Authorization": "Bearer secret"}).status_code == 200
        assert http.get("/api/samples?key=secret").status_code == 200
