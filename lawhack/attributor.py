"""Build the attribution registry: deterministic rules first, Jev for ambiguous passages."""

import asyncio
import re
import time

from typesafe_sdk import Choice

from lawhack.schema import Decision, Registry, RegistryEntry, Segment, Speaker, StatementType, Status, Zone
from lawhack.system_one import SystemOneClient

RECHECK_BELOW = 0.8

SPEAKER_CRITERIA = {
    Speaker.COUR_CASSATION.value: "The Cour de cassation states its own reasoning, approval or ruling (judge of law, not of facts)",
    Speaker.JURIDICTION_FOND.value: "The lower court's (cour d'appel / « l'arrêt attaqué ») reasoning or findings are being reported",
    Speaker.DEMANDEUR.value: "The petitioner's argument is being reported (party contesting the lower court decision)",
    Speaker.DEFENDEUR.value: "The respondent's argument is being reported",
    Speaker.MINISTERE_PUBLIC.value: "The advocate general / public prosecutor speaks",
    Speaker.LOI.value: "A legal provision is quoted or paraphrased",
    Speaker.INDETERMINE.value: "The speaker cannot be determined from the text",
}

TYPE_CRITERIA = {
    StatementType.FAIT.value: "A fact of the dispute",
    StatementType.PROCEDURE.value: "A procedural step (who sued whom, appeals, admissibility)",
    StatementType.MOYEN.value: "A ground of appeal / argument raised against the decision",
    StatementType.MOTIF.value: "Legal reasoning",
    StatementType.VISA.value: "Statement of the legal provisions the court relies on (« Vu les articles… »)",
    StatementType.DISPOSITIF.value: "The operative ruling",
    StatementType.CITATION.value: "A verbatim quotation of another text",
}

STATUS_CRITERIA = {
    Status.CONSTATE.value: "Presented as established by a court",
    Status.ALLEGUE.value: "Presented as a party's claim, not established",
    Status.CONTESTE.value: "Presented as disputed by another party",
    Status.DECIDE.value: "Decided or approved by the Cour de cassation",
}

# Phrases by which the Cour endorses the lower court: the Cour itself decides.
APPROVAL_MARKERS = re.compile(
    r"à bon droit|exactement (déduit|retenu)|justement (retenu|déduit)|légalement justifié"
    r"|n'est (donc )?pas fondé|ne peut (donc )?être accueilli|est (donc )?fondé",
    re.I,
)
_VISA = re.compile(r"^vu (les?|l')\s*(articles?|principe)", re.I)


def _rule(segment: Segment) -> tuple[Speaker, StatementType, Status] | None:
    if segment.zone is Zone.INTRODUCTION:
        return Speaker.COUR_CASSATION, StatementType.PROCEDURE, Status.CONSTATE
    if segment.zone is Zone.DISPOSITIF:
        return Speaker.COUR_CASSATION, StatementType.DISPOSITIF, Status.DECIDE
    if segment.zone is Zone.METADONNEES:
        return Speaker.INDETERMINE, StatementType.PROCEDURE, Status.CONSTATE
    if _VISA.match(segment.text):
        return Speaker.COUR_CASSATION, StatementType.VISA, Status.DECIDE
    return None


def _certain(value: str) -> Decision:
    return Decision(value=value, probabilities={value: 1.0}, confidence=1.0)


def _chain(speaker: Speaker) -> list[Speaker]:
    return [Speaker.COUR_CASSATION] if speaker is Speaker.COUR_CASSATION else [Speaker.COUR_CASSATION, speaker]


def _state(segments: list[Segment]) -> dict:
    first = segments[0]
    return {
        "document": "French Cour de cassation decision",
        "section_heading": first.heading,
        "zone": first.zone.value,
        "paragraph": first.paragraph,
        "sentences": {s.id: s.text for s in segments},
    }


def _questions(segments: list[Segment], reverse: bool = False) -> dict[str, Choice]:
    def ordered(criteria: dict[str, str]) -> dict[str, str]:
        items = list(criteria.items())
        return dict(reversed(items)) if reverse else dict(items)

    questions: dict[str, Choice] = {}
    for s in segments:
        ref = f"`sentences.{s.id}`"
        questions[f"speaker:{s.id}"] = Choice(
            instructions=f"Who is the primary speaker of sentence {ref}? Use the section heading and zone as context.",
            criteria=ordered(SPEAKER_CRITERIA),
        )
        if reverse:
            continue
        questions[f"type:{s.id}"] = Choice(instructions=f"What kind of statement is sentence {ref}?", criteria=TYPE_CRITERIA)
        questions[f"status:{s.id}"] = Choice(
            instructions=f"What is the epistemic status of sentence {ref} in this decision?", criteria=STATUS_CRITERIA
        )
    return questions


def _average(a: Decision, b: Decision) -> Decision:
    keys = set(a.probabilities) | set(b.probabilities)
    probs = {k: (a.probabilities.get(k, 0.0) + b.probabilities.get(k, 0.0)) / 2 for k in keys}
    best = max(probs, key=probs.get)
    return Decision(value=best, probabilities=probs, confidence=min(a.confidence, b.confidence) if a.value != b.value else max(a.confidence, b.confidence))


async def build_registry(document_id: str, segments: list[Segment], client: SystemOneClient, concurrency: int = 16) -> Registry:
    started = time.perf_counter()
    entries: dict[str, RegistryEntry] = {}
    pending: dict[int, list[Segment]] = {}
    for s in segments:
        ruled = _rule(s)
        if ruled:
            speaker, kind, status = ruled
            entries[s.id] = RegistryEntry(
                **s.model_dump(), speaker=_certain(speaker.value), type=_certain(kind.value),
                status=_certain(status.value), chain=_chain(speaker), source="rule",
            )
        else:
            pending.setdefault(s.block, []).append(s)

    semaphore = asyncio.Semaphore(concurrency)
    usage = {"tokens": 0, "model": None}

    async def call(group: list[Segment], reverse: bool = False):
        async with semaphore:
            result = await client.decide(_state(group), _questions(group, reverse=reverse))
        usage["tokens"] += result.input_tokens
        usage["model"] = result.model
        return result.decisions

    async def attribute(group: list[Segment]):
        decisions = await call(group)
        doubtful = [s for s in group if decisions[f"speaker:{s.id}"].confidence < RECHECK_BELOW]
        if doubtful:
            # Jev favours the first option: ask again with options reversed and average.
            second = await call(doubtful, reverse=True)
            for s in doubtful:
                key = f"speaker:{s.id}"
                decisions[key] = _average(decisions[key], second[key])
        for s in group:
            speaker = decisions[f"speaker:{s.id}"]
            status = decisions[f"status:{s.id}"]
            chain = _chain(Speaker(speaker.value))
            kind = decisions[f"type:{s.id}"]
            if s.zone is Zone.EXPOSE:
                # « Faits et procédure » restates what the arrêt attaqué found: parties' claims there are
                # procedural history established by the lower court, not arguments addressed to the Cour.
                speaker = _certain(Speaker.JURIDICTION_FOND.value)
                status = _certain(Status.CONSTATE.value)
                chain = _chain(Speaker.JURIDICTION_FOND)
                if kind.value not in (StatementType.FAIT.value, StatementType.PROCEDURE.value):
                    kind = _certain(StatementType.PROCEDURE.value)
            elif s.zone is Zone.MOTIVATIONS and APPROVAL_MARKERS.search(s.text):
                status = _certain(Status.DECIDE.value)
                if speaker.value != Speaker.COUR_CASSATION.value:
                    chain = [Speaker.COUR_CASSATION, Speaker(speaker.value)]
                    speaker = _certain(Speaker.COUR_CASSATION.value)
            entries[s.id] = RegistryEntry(
                **s.model_dump(), speaker=speaker, type=kind, status=status,
                chain=chain, source="jev",
            )

    await asyncio.gather(*(attribute(g) for g in pending.values()))
    return Registry(
        document_id=document_id,
        model=usage["model"],
        entries=[entries[s.id] for s in segments],
        input_tokens=usage["tokens"],
        seconds=round(time.perf_counter() - started, 2),
    )
