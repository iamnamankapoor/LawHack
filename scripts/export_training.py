"""Export lawyer feedback as supervised and preference datasets."""

import argparse
import json
from pathlib import Path

from lawhack import feedback, pipeline
from lawhack.answer import Answer, SYSTEM_PROMPT, draft_user_message
from lawhack.schema import Registry


def _registry(document_id: str) -> Registry | None:
    if not document_id or Path(document_id).name != document_id:
        return None
    try:
        registry = Registry.model_validate_json((pipeline.CACHE_DIR / f"{document_id}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return feedback.apply_overrides(registry)


def _context(registry: Registry, context_ids: list[str]):
    if not context_ids:
        return None
    entries = [registry.by_id(segment_id) for segment_id in context_ids]
    return entries if all(entry is not None for entry in entries) else None


def export(out: Path) -> dict[str, int]:
    sft = []
    preferences = []
    loaded: dict[str, Registry | None] = {}

    def cached_registry(document_id: str) -> Registry | None:
        if document_id not in loaded:
            loaded[document_id] = _registry(document_id)
        return loaded[document_id]

    for event in feedback.events():
        if event.verdict != "up" or event.answer is None:
            continue
        registry = cached_registry(event.document_id)
        if registry is None:
            continue
        try:
            answer = Answer.model_validate(event.answer)
        except ValueError:
            continue
        context = _context(registry, answer.context)
        if context is None:
            continue
        prompt = draft_user_message(event.question, context)
        assistant = " ".join(
            f"{sentence.text} " + " ".join(f"[{pill.segment_id}]" for pill in sentence.pills)
            for sentence in answer.sentences
        )
        sft.append({
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": assistant},
            ]
        })
        preferences.extend(
            {"prompt": prompt, "chosen": sentence.text, "rejected": sentence.revised_from}
            for sentence in answer.sentences
            if sentence.revised_from is not None
        )

    attribution_gold = []
    overrides_dir = feedback.FEEDBACK_DIR / "overrides"
    for override_file in sorted(overrides_dir.glob("*.json")):
        document_id = override_file.stem
        registry = cached_registry(document_id)
        if registry is None:
            continue
        for segment_id, speaker in feedback.overrides(document_id).items():
            entry = registry.by_id(segment_id)
            if entry is not None:
                attribution_gold.append({
                    "document_id": document_id,
                    "segment_id": segment_id,
                    "text": entry.text,
                    "zone": entry.zone.value,
                    "speaker": speaker.value,
                })

    out.mkdir(parents=True, exist_ok=True)
    datasets = {
        "sft.jsonl": sft,
        "preferences.jsonl": preferences,
        "attribution_gold.jsonl": attribution_gold,
    }
    for filename, rows in datasets.items():
        (out / filename).write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8",
        )
    counts = {
        "sft": len(sft),
        "preferences": len(preferences),
        "attribution_gold": len(attribution_gold),
    }
    print(
        f"SFT: {counts['sft']} · préférences: {counts['preferences']} · "
        f"attributions: {counts['attribution_gold']}"
    )
    return counts


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("data/feedback/export"))
    args = parser.parse_args(argv)
    export(args.out)


if __name__ == "__main__":
    main()
