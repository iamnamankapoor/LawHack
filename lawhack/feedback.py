import json
import os
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ValidationError

from lawhack.schema import Decision, Registry, Speaker

FEEDBACK_DIR = Path("data/feedback")
MIN_LABELS = 20
TARGET_PRECISION = 0.9
THRESHOLD_BOUNDS = (0.5, 0.95)

PillVerdict = Literal["correct", "wrong_speaker", "unsupported"]
AnswerVerdict = Literal["up", "down"]


class FeedbackEvent(BaseModel):
    ts: float
    document_id: str
    question: str
    verdict: Literal["correct", "wrong_speaker", "unsupported", "up", "down"]
    sentence_index: int | None = None
    sentence: str | None = None
    segment_id: str | None = None
    shown_speaker: str | None = None
    corrected_speaker: str | None = None
    confidence: float | None = None
    level: str | None = None
    supported: float | None = None
    answer: dict | None = None


def record(event: FeedbackEvent) -> None:
    FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
    with (FEEDBACK_DIR / "events.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(event.model_dump_json() + "\n")


def events() -> list[FeedbackEvent]:
    try:
        lines = (FEEDBACK_DIR / "events.jsonl").read_bytes().splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            out.append(FeedbackEvent.model_validate_json(line))
        except (ValueError, ValidationError):
            continue
    return out


def _default_threshold() -> float:
    from lawhack.answer import ANSWER_ABOVE

    return ANSWER_ABOVE


def ok_threshold() -> float:
    labels = [
        event
        for event in events()
        if event.verdict in ("correct", "wrong_speaker", "unsupported") and event.confidence is not None
    ]
    if len(labels) < MIN_LABELS:
        return _default_threshold()

    lower, upper = THRESHOLD_BOUNDS
    candidates = {lower, upper}
    candidates.update(min(max(event.confidence, lower), upper) for event in labels)
    for threshold in sorted(candidates):
        selected = [event for event in labels if event.confidence >= threshold]
        if len(selected) >= 5 and sum(event.verdict == "correct" for event in selected) / len(selected) >= TARGET_PRECISION:
            return round(threshold, 3)
    return round(upper, 3)


def _override_path(document_id: str) -> Path:
    return FEEDBACK_DIR / "overrides" / f"{document_id}.json"


def set_override(document_id: str, segment_id: str, speaker: Speaker) -> None:
    path = _override_path(document_id)
    current = {segment_id: value.value for segment_id, value in overrides(document_id).items()}
    current[segment_id] = speaker.value
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as stream:
            temporary = Path(stream.name)
            json.dump(current, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    except OSError:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        raise


def overrides(document_id: str) -> dict[str, Speaker]:
    try:
        raw = json.loads(_override_path(document_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Speaker] = {}
    for segment_id, value in raw.items():
        try:
            out[segment_id] = Speaker(value)
        except (TypeError, ValueError):
            continue
    return out


def apply_overrides(registry: Registry) -> Registry:
    corrections = overrides(registry.document_id)
    from lawhack.attributor import _chain

    entries = []
    for entry in registry.entries:
        speaker = corrections.get(entry.id)
        if speaker is None:
            entries.append(entry)
            continue
        value = speaker.value
        entries.append(entry.model_copy(update={
            "speaker": Decision(value=value, probabilities={value: 1.0}, confidence=1.0),
            "chain": _chain(speaker),
            "source": "lawyer",
        }))
    return registry.model_copy(update={"entries": entries})


def stats() -> dict:
    all_events = events()
    labels = [
        event
        for event in all_events
        if event.verdict in ("correct", "wrong_speaker", "unsupported") and event.confidence is not None
    ]
    return {
        "labels": len(labels),
        "correct": sum(event.verdict == "correct" for event in labels),
        "ok_threshold": ok_threshold(),
        "default_threshold": _default_threshold(),
        "min_labels": MIN_LABELS,
        "corrections": sum(event.verdict == "wrong_speaker" for event in all_events),
        "validated_answers": sum(event.verdict == "up" for event in all_events),
    }
