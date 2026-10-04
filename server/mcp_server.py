"""LawHack MCP connector (Claude, ChatGPT, Le Chat, Legora, Claude Desktop/Code…).

    python -m server.mcp_server            # stdio (Claude Desktop, Claude Code, Cursor)
    python -m server.mcp_server --http     # Streamable HTTP on :8000/mcp (remote connectors)

For the combined MCP + REST app, run `uvicorn server.app:app`.
"""

import sys
from typing import Annotated

from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from lawhack import service

load_dotenv()

INSTRUCTIONS = """LawHack tells you WHO says what in a French Cour de cassation decision (Cour de cassation, cour d'appel, demandeur, défendeur, loi) with a calibrated confidence.
Workflow: 1) lawhack_load_decision once per decision → decision_id. 2) lawhack_read_decision for a summary or an open question (whole decision, annotated, a few thousand tokens), or lawhack_who_said for a targeted question. 3) lawhack_verify on your draft before sending it, citing segments as [S-xx]; fix every MAL_ATTRIBUE / NON_SOURCE sentence.
Rules: answer only from returned passages; never present a party's argument (moyen) as the Court's ruling; cite `citation` and append `badge`; flag a_verifier passages; if answer_status is not answered, say the Cour de cassation does not decide the point."""

mcp = FastMCP("LawHack", instructions=INSTRUCTIONS, website_url="https://github.com/talal95c/LawHack")

READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except (KeyError, ValueError) as e:
        raise ToolError(str(e.args[0] if e.args else e)) from e


@mcp.tool(annotations=ToolAnnotations(title="Charger un arrêt", readOnlyHint=True, idempotentHint=True, openWorldHint=True))
async def lawhack_load_decision(
    text: Annotated[str | None, Field(description="Full text of the decision (e.g. the content of a PDF the user uploaded, copied verbatim).")] = None,
    url: Annotated[str | None, Field(description="Public URL of the decision: PDF, HTML or Judilibre JSON.")] = None,
    pdf_base64: Annotated[str | None, Field(description="Base64-encoded PDF (for hosts that transfer files, e.g. Legora).")] = None,
    sample: Annotated[str | None, Field(description="Name of a bundled demo decision (see the lawhack://samples resource).")] = None,
) -> service.DecisionSummary:
    """Use this first, once per decision. Analyses a Cour de cassation decision and builds its attribution registry
    (who speaks in every sentence). Provide exactly one of text, url, pdf_base64, sample. Returns the decision_id needed
    by every other LawHack tool, the outcome (solution) and the operative part (dispositif)."""
    try:
        return await service.load_decision(text=text, url=url, pdf_base64=pdf_base64, sample=sample)
    except (KeyError, ValueError) as e:
        raise ToolError(str(e)) from e


@mcp.tool(annotations=ToolAnnotations(title="Qui dit quoi ?", **READ_ONLY.model_dump(exclude={"title"}, exclude_none=True)))
def lawhack_who_said(
    decision_id: Annotated[str, Field(description="Returned by lawhack_load_decision.")],
    question: Annotated[str, Field(description="The user's question or the claim you are about to make, in French.")],
    k: Annotated[int, Field(ge=1, le=15, description="Number of passages to return.")] = 6,
) -> service.WhoSaidResult:
    """Use this before answering any question about a loaded decision. Returns the relevant passages, each with its
    speaker (Cour de cassation, cour d'appel, demandeur…), epistemic status (DECIDE / CONSTATE / ALLEGUE), confidence,
    citation and badge, plus answer_status: answered (the Court decides it), only_alleged (only the parties argue it),
    not_decided_by_court (only the lower court / parties mention it) or not_in_decision."""
    return _call(service.who_said, decision_id, question, k)


@mcp.tool(annotations=ToolAnnotations(title="Lire l'arrêt annoté", **READ_ONLY.model_dump(exclude={"title"}, exclude_none=True)))
def lawhack_read_decision(
    decision_id: Annotated[str, Field(description="Returned by lawhack_load_decision.")],
    zones: Annotated[list[str] | None, Field(description="Restrict to zones: expose, moyens, motivations, dispositif, introduction. Default: all.")] = None,
) -> service.DecisionText:
    """Use this to summarise a decision or answer open questions. Returns the whole decision, one line per sentence,
    each prefixed with its segment id, paragraph, speaker, confidence and status (⚠ = to verify). Cite segments as [S-xx]."""
    return _call(service.read_decision, decision_id, zones)


@mcp.tool(annotations=ToolAnnotations(title="Vérifier les attributions", **READ_ONLY.model_dump(exclude={"title"}, exclude_none=True)))
def lawhack_verify(
    decision_id: Annotated[str, Field(description="Returned by lawhack_load_decision.")],
    text: Annotated[str, Field(description="A drafted answer, memo or any text about the decision (yours, a colleague's, another AI's).")],
) -> service.VerifyResult:
    """Use this on a draft before sending it. Sentences citing [S-xx] or §n are checked against exactly those segments.
    Checks sentence by sentence who the text says is speaking against the
    registry. Verdicts: OK, A_VERIFIER (low confidence), MAL_ATTRIBUE (e.g. a party's argument presented as the Court's
    ruling), NON_SOURCE (not supported by the decision), SANS_ATTRIBUTION (no speaker named)."""
    return _call(service.verify_text, decision_id, text)


@mcp.tool(annotations=ToolAnnotations(title="Lire un passage", **READ_ONLY.model_dump(exclude={"title"}, exclude_none=True)))
def lawhack_get_passage(
    decision_id: Annotated[str, Field(description="Returned by lawhack_load_decision.")],
    segment_id: Annotated[str, Field(description="Segment id such as S-017, from another LawHack result.")],
    context: Annotated[int, Field(ge=0, le=5, description="Neighbouring segments to include on each side.")] = 1,
) -> list[service.Passage]:
    """Use this to quote the exact text of a passage (with its neighbours) before citing it verbatim."""
    return _call(service.get_passage, decision_id, segment_id, context)


@mcp.resource("lawhack://samples", mime_type="application/json")
def samples() -> list[str]:
    """Demo decisions bundled with LawHack, usable as `sample` in lawhack_load_decision."""
    return service.list_samples()


@mcp.prompt(name="lawhack_answer")
def answer_with_attribution(question: str) -> str:
    """Answer a question about the loaded decision with explicit, verified attribution."""
    return (
        f"Question de l'avocat : {question}\n\n"
        "1. Appelle lawhack_who_said avec cette question.\n"
        "2. Rédige la réponse uniquement à partir des passages : distingue « la Cour décide », « la cour d'appel avait "
        "retenu », « le demandeur soutient » ; termine chaque phrase par le `badge` du passage.\n"
        "3. Si answer_status = only_alleged, dis que la Cour ne tranche pas ce point. Si not_in_decision, dis que l'arrêt "
        "ne traite pas la question.\n"
        "4. Passe ton brouillon dans lawhack_verify et corrige toute phrase MAL_ATTRIBUE ou NON_SOURCE.\n"
        "5. Ne promets jamais l'absence d'erreur ; signale les passages à vérifier."
    )


if __name__ == "__main__":
    if "--http" in sys.argv:
        mcp.run(transport="http", host="0.0.0.0", port=8000)
    else:
        mcp.run()
