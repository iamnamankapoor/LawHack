import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "eval_qa", Path(__file__).resolve().parent.parent / "scripts" / "eval_qa.py")
eqa = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(eqa)


def test_wilson_interval():
    low, high = eqa.wilson(0, 10)
    assert low == 0
    assert abs(high - 0.278) < 0.002
    low, high = eqa.wilson(5, 10)
    assert abs(low - 0.237) < 0.002
    assert abs(high - 0.763) < 0.002


def test_exact_mcnemar():
    assert eqa.mcnemar(0, 6) == 0.03125
    assert eqa.mcnemar(4, 4) == 1.0


def test_cohen_kappa():
    assert eqa.cohen_kappa([0, 1, 0, 1], [0, 1, 0, 1]) == 1.0
    assert abs(eqa.cohen_kappa([1, 1, 0, 0], [1, 0, 1, 0])) < 1e-12


def test_ppi_correction_removes_labeled_judge_bias():
    judge_all = [1, 1, 0, 0, 0]
    judge_labeled = [1, 1, 0, 0, 0]
    human_labeled = [1, 0, 0, 0, 0]
    estimate = eqa.ppi_estimate(judge_all, judge_labeled, human_labeled)
    assert abs(estimate - (sum(judge_all) / len(judge_all) - 0.2)) < 1e-12


def test_paired_comparison_on_synthetic_rows():
    rows = []
    outcomes = [
        ("q1", "d1", True, False, False, True),
        ("q2", "d1", False, True, True, False),
        ("q3", "d2", False, True, True, True),
    ]
    for question_id, decision, law_attr, base_attr, law_correct, base_correct in outcomes:
        for system, attr, correct, label in (
            ("lawhack", law_attr, law_correct, "misgrounded" if law_attr else "correct"),
            ("baseline", base_attr, base_correct, "incorrect" if base_attr else "correct"),
        ):
            rows.append({
                "id": question_id, "decision": decision, "system": system, "expected_abstain": False,
                "grade": {"attribution_error": attr, "correct": correct,
                          "label": label, "invented": False, "abstained": False},
            })
    attr = eqa.paired_comparison(rows, "attribution_error")
    assert (attr["n"], attr["b"], attr["c"], attr["p"], attr["diff"]) == (3, 1, 2, 1.0, -1 / 3)
    correct = eqa.paired_comparison(rows, "correct")
    assert correct["b"] == 1 and correct["c"] == 1
    assert correct["diff"] == 0


def test_parse_citations_matches_answer_render_format():
    assert eqa.parse_citations("La Cour statue [S-001], puis confirme [S-123]. [S-12] [S-1234]") == [
        "S-001", "S-123",
    ]
