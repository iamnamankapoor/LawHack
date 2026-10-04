"""Provider-agnostic System 1 client (Jev on TypeSafe, OpenJev on Codiv: same API)."""

import os
from dataclasses import dataclass, field
from typing import Any, Protocol

from typesafe_sdk import AsyncTypeSafeClient, Choice, Noul

from lawhack.schema import Decision


@dataclass
class SystemOneResult:
    decisions: dict[str, Decision]
    model: str | None = None
    input_tokens: int = 0
    raw: Any = field(default=None, repr=False)


class SystemOneClient(Protocol):
    async def decide(self, state: Any, questions: dict[str, Choice | Noul]) -> SystemOneResult: ...


class TypeSafeSystemOne:
    """Calls `POST /v1/systemone`. Base URL and model come from the environment."""

    def __init__(self, model: str | None = None, base_url: str | None = None, api_key: str | None = None):
        self.model = model or os.environ.get("SYSTEM_ONE_MODEL", "jev-latest")
        kwargs: dict[str, Any] = {}
        base_url = base_url or os.environ.get("TYPESAFE_BASE_URL") or None
        if base_url:
            kwargs["base_url"] = base_url
        if api_key:
            kwargs["api_key"] = api_key
        self._client = AsyncTypeSafeClient(**kwargs)

    async def decide(self, state: Any, questions: dict[str, Choice | Noul]) -> SystemOneResult:
        response = await self._client.system_one(state, questions, model=self.model)
        decisions: dict[str, Decision] = {}
        for key, answer in response.answers.items():
            if answer.type == "choice":
                decisions[key] = Decision(
                    value=answer.choice,
                    probabilities={k: float(v) for k, v in answer.probabilities.items()},
                    confidence=float(answer.confidence),
                )
            else:
                noul = answer.noul
                decisions[key] = Decision(
                    value=noul.choice if hasattr(noul, "choice") else str(noul),
                    probabilities={k: float(v) for k, v in getattr(noul, "probabilities", {}).items()},
                    confidence=float(getattr(noul, "confidence", 1.0)),
                )
        usage = getattr(response, "usage", None)
        return SystemOneResult(
            decisions=decisions,
            model=getattr(response, "model", self.model),
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            raw=response,
        )
