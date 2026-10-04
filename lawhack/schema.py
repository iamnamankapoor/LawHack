from enum import Enum

from pydantic import BaseModel, Field


class Speaker(str, Enum):
    COUR_CASSATION = "COUR_CASSATION"
    JURIDICTION_FOND = "JURIDICTION_FOND"
    DEMANDEUR = "DEMANDEUR"
    DEFENDEUR = "DEFENDEUR"
    MINISTERE_PUBLIC = "MINISTERE_PUBLIC"
    LOI = "LOI"
    INDETERMINE = "INDETERMINE"


class StatementType(str, Enum):
    FAIT = "FAIT"
    PROCEDURE = "PROCEDURE"
    MOYEN = "MOYEN"
    MOTIF = "MOTIF"
    VISA = "VISA"
    DISPOSITIF = "DISPOSITIF"
    CITATION = "CITATION"


class Status(str, Enum):
    CONSTATE = "CONSTATE"
    ALLEGUE = "ALLEGUE"
    CONTESTE = "CONTESTE"
    DECIDE = "DECIDE"


class Zone(str, Enum):
    INTRODUCTION = "introduction"
    EXPOSE = "expose"
    MOYENS = "moyens"
    MOTIVATIONS = "motivations"
    DISPOSITIF = "dispositif"
    METADONNEES = "metadonnees"  # Légifrance trailer: ECLI, titrages, textes appliqués


class Block(BaseModel):
    """A paragraph of the decision: numbered (§n) or not, with its zone and heading."""

    index: int
    text: str
    start: int
    end: int
    zone: Zone
    heading: str | None = None
    paragraph: int | None = None
    page: int | None = None


class Segment(BaseModel):
    id: str
    text: str
    start: int
    end: int
    block: int
    zone: Zone
    heading: str | None = None
    paragraph: int | None = None
    page: int | None = None


class Decision(BaseModel):
    """A probabilistic decision over one label set."""

    value: str
    probabilities: dict[str, float] = Field(default_factory=dict)
    confidence: float = 1.0


class RegistryEntry(Segment):
    speaker: Decision
    type: Decision
    status: Decision
    chain: list[Speaker] = Field(default_factory=list)
    source: str  # "rule" | "jev"


class Document(BaseModel):
    id: str
    text: str
    pages: list[tuple[int, int]] = Field(default_factory=list)  # (start, end) offsets per page


class Registry(BaseModel):
    document_id: str
    model: str | None = None
    version: str = "1"
    entries: list[RegistryEntry]
    input_tokens: int = 0
    seconds: float = 0.0

    def by_id(self, segment_id: str) -> RegistryEntry | None:
        return next((e for e in self.entries if e.id == segment_id), None)
