import asyncio
import base64

import pytest
from fastapi.testclient import TestClient
from fastmcp import Client

from lawhack import pipeline, service
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
    monkeypatch.setattr(pipeline, "CACHE_DIR", tmp_path)
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
            assert names == {"lawhack_load_decision", "lawhack_read_decision", "lawhack_who_said", "lawhack_verify", "lawhack_get_passage"}
            loaded = await client.call_tool("lawhack_load_decision", {"sample": SAMPLE})
            did = loaded.structured_content["decision_id"]
            verified = await client.call_tool("lawhack_verify", {"decision_id": did, "text": TRAP})
            assert verified.structured_content["summary"]["MAL_ATTRIBUE"] == 1
            moyen = next(p for p in loaded.structured_content["zones"] if p == "moyens")
            assert moyen
            found = await client.call_tool("lawhack_who_said", {"decision_id": did, "question": "Que reproche le vendeur à l'arrêt ?"})
            sid = next(p["segment_id"] for p in found.structured_content["passages"] if p["zone"] == "moyens")
            passages = await client.call_tool("lawhack_get_passage", {"decision_id": did, "segment_id": sid, "context": 0})
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


def test_who_said_not_in_decision(decision_id):
    assert service.who_said(decision_id, "Quel est le régime fiscal des cryptomonnaies ?").answer_status == "not_in_decision"


def test_read_decision_is_compact_and_annotated(decision_id):
    text = service.read_decision(decision_id).text
    assert "## Énoncé du moyen" in text and "[Demandeur" in text and len(text) < 20_000
    assert "## Dispositif" not in service.read_decision(decision_id, ["moyens"]).text
    with pytest.raises(ValueError):
        service.read_decision(decision_id, ["nope"])


def test_verify_uses_explicit_citations(decision_id):
    moyen = next(e for e in service._get(decision_id).registry.entries if e.zone.value == "moyens")
    result = service.verify_text(decision_id, f"La Cour juge que le vendeur a droit à l'indemnité d'immobilisation [{moyen.id}].")
    assert result.sentences[0].verdict == "MAL_ATTRIBUE"
    assert result.sentences[0].source.segment_id == moyen.id


@pytest.mark.parametrize("url", ["http://127.0.0.1/x.pdf", "http://169.254.169.254/latest", "file:///etc/passwd", "http://localhost:8000/"])
def test_url_loading_refuses_private_hosts(url, monkeypatch):
    monkeypatch.delenv("LAWHACK_ALLOW_PRIVATE_URLS", raising=False)
    with pytest.raises(ValueError):
        service.read_document(url=url)
