"""Legible MCP connector (Claude Desktop/Code, ChatGPT, Le Chat, Legora…). Ported from the team's LawHack connector.

    python -m legible.mcp_server          # stdio
    python -m legible.mcp_server --http   # Streamable HTTP on :8000/mcp
"""
import base64
import hashlib
import sys
from typing import Annotated

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

from . import ingest
from .answer import analyse, answer
from .api import DEFAULT_MODEL, _load
from .check import check
from .holdings import holdings
from .render import render

INSTRUCTIONS = """Legible tells you WHO speaks in each paragraph of a French Cour de cassation decision (the Court, the cour d'appel,
a party, the Court's former case law) and WHAT THE COURT DID with it (approved, quashed, not ruled on, argument rejected/accepted, overruled).
Workflow: legible_load_decision once → decision_id; legible_read_decision for the labelled text; legible_ask for a checked answer;
legible_verify on any draft before sending it. Never present a passage that is not the Court's own as the Court's position."""

mcp = FastMCP("Legible", instructions=INSTRUCTIONS)
LOADED: dict[str, str] = {}


def _text(decision_id):
    if decision_id in LOADED:
        return LOADED[decision_id]
    try:
        return _load(decision_id)
    except Exception as e:  # HTTPException from the API helper
        raise ToolError(f"Unknown decision_id {decision_id}: load it first.") from e


@mcp.tool()
def legible_load_decision(
    text: Annotated[str | None, Field(description="Full text of the decision.")] = None,
    pdf_base64: Annotated[str | None, Field(description="Base64-encoded PDF of the decision.")] = None,
    sample: Annotated[str | None, Field(description="Name of a bundled decision, e.g. C2_soc_2026-09-11_24-21242.")] = None,
) -> dict:
    """Analyse a decision once; returns its decision_id, outcome and what the Court held (verbatim quotes per ground)."""
    if sample:
        decision_id, body = sample, _load(sample)
    elif pdf_base64:
        body = ingest.from_pdf(base64.b64decode(pdf_base64))
        decision_id = "d" + hashlib.sha256(body.encode()).hexdigest()[:12]
    elif text:
        body, decision_id = text, "d" + hashlib.sha256(text.encode()).hexdigest()[:12]
    else:
        raise ToolError("Provide text, pdf_base64 or sample.")
    LOADED[decision_id] = body
    segs, outcomes = analyse(body, key=decision_id)
    return {"decision_id": decision_id, "holdings": holdings(segs, outcomes)}


@mcp.tool()
def legible_read_decision(decision_id: str) -> str:
    """The decision with every paragraph labelled: speaker and the Court's stance, plus a verified summary of what the Court itself said."""
    return render(*analyse(_text(decision_id), key=decision_id))


@mcp.tool()
def legible_ask(decision_id: str, question: str) -> dict:
    """Answer a question about the decision; the answer is checked for misattribution before it is returned."""
    return answer(_text(decision_id), question, DEFAULT_MODEL, key=decision_id)


@mcp.tool()
def legible_verify(decision_id: str, draft: str) -> list[dict]:
    """Check a draft sentence by sentence: conforme / à vérifier / à corriger, with the source paragraph and a rewrite."""
    segs, outcomes = analyse(_text(decision_id), key=decision_id)
    return check(draft, segs, outcomes, DEFAULT_MODEL)


if __name__ == "__main__":
    mcp.run(transport="http", port=8000) if "--http" in sys.argv else mcp.run()
