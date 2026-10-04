import json
from pathlib import Path

import pytest

from lawhack.ingest import load_pdf, load_text

SAMPLES = Path(__file__).resolve().parent.parent / "data" / "samples"


@pytest.fixture
def judilibre_doc():
    row = json.loads((SAMPLES / "cass_civ2_2025-03-13_23-13219.json").read_text())
    return load_text(row["text"]), row


@pytest.fixture
def legifrance_doc():
    return load_pdf(SAMPLES / "cass_civ3_2022-12-14_21-24539.pdf")


@pytest.fixture(autouse=True)
def _isolate_answer_cache(tmp_path, monkeypatch):
    from lawhack import answer, feedback

    monkeypatch.setattr(answer, "ANSWER_CACHE_DIR", tmp_path / "answers")
    monkeypatch.setenv("ANSWER_CACHE", "0")
    monkeypatch.setattr(feedback, "FEEDBACK_DIR", tmp_path / "feedback")
