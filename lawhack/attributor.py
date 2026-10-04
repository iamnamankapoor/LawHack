"""Build the attribution registry: deterministic rules first, Jev for ambiguous passages."""

import asyncio
import re
import time

from typesafe_sdk import Choice

from lawhack.schema import Decision, Registry, RegistryEntry, Segment, Speaker, StatementType, Status, Zone
from lawhack.system_one import SystemOneClient

RECHECK_BELOW = 0.8
VERSION = "3"  # bump when rules or prompts change: cached registries are recomputed

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

# Phrases by which the Cour endorses the lower court: the Cour decides, the cour d'appel's reasoning is approved.
ENDORSEMENT_MARKERS = re.compile(r"à bon droit|exactement (déduit|retenu)|justement (retenu|déduit)|légalement justifié", re.I)
# The Cour's verdict on a ground of appeal: its own ruling, no endorsed voice.
_VERDICT = re.compile(r"^(\d+\.\s*)?(le|ce|ces) (moyen|grief)s?,?( pris en sa \w+ branche,)? (n'est|ne sont|est|sont|ne peu(t|vent)) ", re.I)
_VISA = re.compile(r"^vu (les?|l')\s*(articles?|principe)", re.I)
# « Il en déduit… » / « Elle retient… » continues the previous sentence's voice.
_ANAPHORA = re.compile(r"^(il|elle)s? (en )?(a |ont )?(déduit|dédui|retient|retenu|relève|relevé|ajoute|énonce|constate|estime|considère|conclut|juge)", re.I)

# Codified formulas of Cour de cassation drafting (motivation enrichie): no model call needed.
_N = r"^(\d+\.\s*)?"
_LOWER_COURT_FORMULA = re.compile(
    _N + r"(pour [^.]{0,500}?, )?(l'arr[êe]t|la cour d'appel|les juges du fond|le jugement)( attaqu[ée])? "
    r"(retient|relève|énonce|constate|considère|estime|juge|ajoute|observe)\b", re.I)
_CENSURE = re.compile(_N + r"en (statuant|se déterminant|se prononçant) (ainsi|de la sorte|par ces motifs)", re.I)
_COURT_PROCEDURE = re.compile(
    _N + r"(après avis donné aux parties|en application de l'article (1014|1015|624|627)|l'intérêt d'une bonne administration"
    r"|la cassation (est|n'est) |il (y a lieu|n'y a pas lieu))", re.I)

GROUP_SIZE = 6  # sentences per Jev call: shared context, fewer calls
EXPOSE_PRIOR = 0.9  # « Faits et procédure » recites the arrêt attaqué


def _rule(segment: Segment) -> tuple[Speaker, StatementType, Status, float] | None:
    if segment.zone is Zone.INTRODUCTION:
        return Speaker.COUR_CASSATION, StatementType.PROCEDURE, Status.CONSTATE, 1.0
    if segment.zone is Zone.DISPOSITIF:
        return Speaker.COUR_CASSATION, StatementType.DISPOSITIF, Status.DECIDE, 1.0
    if segment.zone is Zone.METADONNEES:
        return Speaker.INDETERMINE, StatementType.PROCEDURE, Status.CONSTATE, 1.0
    if segment.zone is Zone.MOYENS:
        return Speaker.DEMANDEUR, StatementType.MOYEN, Status.ALLEGUE, 0.95
    if _VISA.match(segment.text):
        return Speaker.COUR_CASSATION, StatementType.VISA, Status.DECIDE, 1.0
    if segment.zone is Zone.MOTIVATIONS:
        if _VERDICT.match(segment.text) and len(segment.text) < 200:
            return Speaker.COUR_CASSATION, StatementType.MOTIF, Status.DECIDE, 1.0
        if _CENSURE.match(segment.text):
            return Speaker.COUR_CASSATION, StatementType.MOTIF, Status.DECIDE, 0.97
        if _COURT_PROCEDURE.match(segment.text):
            return Speaker.COUR_CASSATION, StatementType.PROCEDURE, Status.DECIDE, 0.97
        if _LOWER_COURT_FORMULA.match(segment.text) and not ENDORSEMENT_MARKERS.search(segment.text):
            return Speaker.JURIDICTION_FOND, StatementType.MOTIF, Status.CONSTATE, 0.97
    return None


def _certain(value: str, confidence: float = 1.0) -> Decision:
    return Decision(value=value, probabilities={value: confidence}, confidence=confidence)


def _chain(speaker: Speaker) -> list[Speaker]:
    return [Speaker.COUR_CASSATION] if speaker is Speaker.COUR_CASSATION else [Speaker.COUR_CASSATION, speaker]


def _state(segments: list[Segment]) -> dict:
    return {
        "document": "French Cour de cassation decision",
        "zone": segments[0].zone.value,
        "section_heading": segments[0].heading,
        "sentences": {s.id: s.text for s in segments},
        "paragraph_of": {s.id: s.paragraph for s in segments},
    }


def _types_for(zone: Zone) -> dict[str, str]:
    excluded = {StatementType.DISPOSITIF.value, StatementType.VISA.value}
    return {k: v for k, v in TYPE_CRITERIA.items() if k not in excluded}


def _questions(segments: list[Segment], reverse: bool = False, ask_speaker: bool = True) -> dict[str, Choice]:
    def ordered(criteria: dict[str, str]) -> dict[str, str]:
        items = list(criteria.items())
        return dict(reversed(items)) if reverse else dict(items)

    questions: dict[str, Choice] = {}
    for s in segments:
        ref = f"`sentences.{s.id}`"
        if ask_speaker:
            questions[f"speaker:{s.id}"] = Choice(
                instructions=f"Who is the primary speaker of sentence {ref}? Neighbouring sentences and the zone give context.",
                criteria=ordered(SPEAKER_CRITERIA),
            )
        if reverse:
            continue
        questions[f"type:{s.id}"] = Choice(instructions=f"What kind of statement is sentence {ref}?", criteria=_types_for(s.zone))
        questions[f"status:{s.id}"] = Choice(
            instructions=f"What is the epistemic status of sentence {ref} in this decision?", criteria=STATUS_CRITERIA
        )
    return questions


def _average(a: Decision, b: Decision) -> Decision:
    keys = set(a.probabilities) | set(b.probabilities)
    probs = {k: (a.probabilities.get(k, 0.0) + b.probabilities.get(k, 0.0)) / 2 for k in keys}
    best = max(probs, key=probs.get)
    return Decision(value=best, probabilities=probs, confidence=min(a.confidence, b.confidence) if a.value != b.value else max(a.confidence, b.confidence))


def _groups(segments: list[Segment]) -> list[list[Segment]]:
    """Consecutive sentences of the same zone, at most GROUP_SIZE per call."""
    groups: list[list[Segment]] = []
    for s in segments:
        if groups and groups[-1][-1].zone is s.zone and len(groups[-1]) < GROUP_SIZE and int(groups[-1][-1].id[2:]) + 1 == int(s.id[2:]):
            groups[-1].append(s)
        else:
            groups.append([s])
    return groups


async def build_registry(document_id: str, segments: list[Segment], client: SystemOneClient, concurrency: int = 16) -> Registry:
    started = time.perf_counter()
    entries: dict[str, RegistryEntry] = {}
    pending: list[Segment] = []
    for s in segments:
        ruled = _rule(s)
        if ruled:
            speaker, kind, status, confidence = ruled
            entries[s.id] = RegistryEntry(
                **s.model_dump(), speaker=_certain(speaker.value, confidence), type=_certain(kind.value),
                status=_certain(status.value, confidence), chain=_chain(speaker), source="rule",
            )
        else:
            pending.append(s)

    semaphore = asyncio.Semaphore(concurrency)
    usage = {"tokens": 0, "model": None}

    async def call(group: list[Segment], **kwargs):
        async with semaphore:
            result = await client.decide(_state(group), _questions(group, **kwargs))
        usage["tokens"] += result.input_tokens
        usage["model"] = result.model
        return result.decisions

    async def attribute(group: list[Segment]):
        expose = group[0].zone is Zone.EXPOSE
        decisions = await call(group, ask_speaker=not expose)
        if expose:
            for s in group:
                decisions[f"speaker:{s.id}"] = _certain(Speaker.JURIDICTION_FOND.value, EXPOSE_PRIOR)
        doubtful = [s for s in group if not expose and decisions[f"speaker:{s.id}"].confidence < RECHECK_BELOW]
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
            if s.zone is Zone.MOTIVATIONS and ENDORSEMENT_MARKERS.search(s.text):
                status = _certain(Status.DECIDE.value)
                endorsed = Speaker(speaker.value)
                chain = [Speaker.COUR_CASSATION, Speaker.JURIDICTION_FOND if endorsed is Speaker.COUR_CASSATION else endorsed]
                speaker = _certain(Speaker.COUR_CASSATION.value)
            entries[s.id] = RegistryEntry(
                **s.model_dump(), speaker=speaker, type=decisions[f"type:{s.id}"], status=status,
                chain=chain, source="jev",
            )

    await asyncio.gather(*(attribute(g) for g in _groups(pending)))
    _propagate_anaphora(segments, entries)
    return Registry(
        document_id=document_id,
        model=usage["model"],
        version=VERSION,
        entries=[entries[s.id] for s in segments],
        input_tokens=usage["tokens"],
        seconds=round(time.perf_counter() - started, 2),
    )


def _propagate_anaphora(segments: list[Segment], entries: dict[str, RegistryEntry]) -> None:
    for prev, s in zip(segments, segments[1:]):
        before, entry = entries[prev.id], entries[s.id]
        if (entry.source == "jev" and prev.zone is s.zone and _ANAPHORA.match(s.text)
                and not ENDORSEMENT_MARKERS.search(s.text) and before.speaker.value == Speaker.JURIDICTION_FOND.value):
            confidence = max(entry.speaker.confidence if entry.speaker.value == before.speaker.value else 0.0,
                             min(before.speaker.confidence, 0.9))
            entries[s.id] = entry.model_copy(update={
                "speaker": _certain(before.speaker.value, confidence), "chain": list(before.chain),
                "status": _certain(Status.CONSTATE.value, confidence), "source": "jev+anaphora",
            })
        elif entry.speaker.value == Speaker.LOI.value and entry.status.value == Status.DECIDE.value:
            entries[s.id] = entry.model_copy(update={"status": _certain(Status.CONSTATE.value, entry.status.confidence)})
