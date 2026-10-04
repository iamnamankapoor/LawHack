"""REST façade over the same service (OpenAPI at /api/docs): our UI, GPT Actions, partner integrations."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from lawhack import service

router = APIRouter(prefix="/api")


class LoadRequest(BaseModel):
    text: str | None = None
    url: str | None = None
    pdf_base64: str | None = None
    sample: str | None = None


class QuestionRequest(BaseModel):
    question: str
    k: int = 6


class VerifyRequest(BaseModel):
    text: str


def _http(fn, *args):
    try:
        return fn(*args)
    except KeyError as e:
        raise HTTPException(404, str(e.args[0])) from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@router.post("/decisions", operation_id="load_decision")
async def load_decision(body: LoadRequest) -> service.DecisionSummary:
    try:
        return await service.load_decision(**body.model_dump())
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@router.post("/decisions/{decision_id}/who-said", operation_id="who_said")
def who_said(decision_id: str, body: QuestionRequest) -> service.WhoSaidResult:
    return _http(service.who_said, decision_id, body.question, body.k)


@router.get("/decisions/{decision_id}/text", operation_id="read_decision")
def read_decision(decision_id: str, zones: str | None = None) -> service.DecisionText:
    return _http(service.read_decision, decision_id, zones.split(",") if zones else None)


@router.post("/decisions/{decision_id}/verify", operation_id="verify")
def verify(decision_id: str, body: VerifyRequest) -> service.VerifyResult:
    return _http(service.verify_text, decision_id, body.text)


@router.get("/decisions/{decision_id}/segments/{segment_id}", operation_id="get_passage")
def get_passage(decision_id: str, segment_id: str, context: int = 1) -> list[service.Passage]:
    return _http(service.get_passage, decision_id, segment_id, context)


@router.get("/samples", operation_id="list_samples")
def samples() -> list[str]:
    return service.list_samples()
