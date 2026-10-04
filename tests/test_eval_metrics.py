import importlib.util
from pathlib import Path

from lawhack.ingest import load_text
from lawhack.schema import Zone
from lawhack.zoning import zone_blocks

_spec = importlib.util.spec_from_file_location(
    "eval_zones", Path(__file__).resolve().parent.parent / "scripts" / "eval_zones.py")
ez = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ez)


def test_gold_zone_majority_overlap_and_alias():
    zones = {"moyens": [{"start": 0, "end": 100}], "annexes": [{"start": 100, "end": 200}]}
    assert ez.gold_zone(zones, 10, 50) == "moyens"
    assert ez.gold_zone(zones, 150, 190) == "moyens"  # annexes are the parties' grounds
    assert ez.gold_zone(zones, 90, 400) is None  # mostly outside any zone


def test_bootstrap_resamples_decisions():
    low, high = ez.bootstrap([(1, 10)] * 50)
    assert low == high == 0.1
    low, high = ez.bootstrap([(0, 10)] * 25 + [(10, 10)] * 25)
    assert 0.3 < low < 0.5 < high < 0.7


def test_calibration_ece():
    perfect = ez.calibration([[0.95, 1]] * 19 + [[0.95, 0]])
    assert perfect["ece"] < 0.01 and perfect["n"] == 20
    overconfident = ez.calibration([[0.99, 0]] * 10)
    assert overconfident["ece"] > 0.9


def test_glued_moyens_annexes_split_off():
    text = ("REJETTE le pourvoi ;\n\nCondamne M. X aux dépens. MOYENS ANNEXES au présent arrêt\n\n"
            "Moyen produit par la SCP Y pour M. X.\n\nIl est fait grief à l'arrêt attaqué d'avoir débouté M. X.")
    zones = [b.zone for b in zone_blocks(load_text(text, doc_id="t")) if b.text.strip()]
    assert zones[-1] is Zone.MOYENS
