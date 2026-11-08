"""`flightdeck metrics labels` on a synthetic gold set (tests/fixtures/labels/gold_calls.jsonl), hand-labelled one call
at a time. The set includes calls the rules get wrong, so CI shows the labeller's real limits: a rule change that lowers
accuracy below BASELINE fails here; one that raises it should raise BASELINE in the same PR.
"""

from __future__ import annotations

import json
from pathlib import Path

from test_process_metrics import build, plane
from typer.testing import CliRunner

from flightdeck.cli import app
from flightdeck.dataplane.duck import connect
from flightdeck.metrics.labels import score

GOLD = Path(__file__).parent / "fixtures" / "labels" / "gold_calls.jsonl"
BASELINE = 0.9  # first-label accuracy of the rules on this set; only goes up


def _setup(tmp_path: Path) -> tuple[Path, Path]:
    calls = [json.loads(line) for line in GOLD.read_text().splitlines()]
    data = plane(tmp_path / "plane", build([(c["tool"], c["input"], "", True) for c in calls], run="run-gold"))
    gold = tmp_path / "gold.jsonl"  # build() gives call n the hangar.seq 2n + 1
    gold.write_text("".join(json.dumps({"run_id": "run-gold", "seq": 2 * n + 1, "label": c["label"],
                                        "labels": c["labels"]}) + "\n" for n, c in enumerate(calls)))
    return data, gold


def test_every_gold_call_is_labelled_and_first_is_in_taxonomy_order() -> None:
    order = ["reference", "vcs", "test", "edit", "setup", "plan", "explore", "verify", "other"]
    for c in map(json.loads, GOLD.read_text().splitlines()):
        assert c["label"] == c["labels"][0] and c["labels"] == sorted(c["labels"], key=order.index), c


def test_rules_meet_the_baseline(tmp_path: Path) -> None:
    data, gold = _setup(tmp_path)
    got = score(connect(str(data)), str(gold))
    assert got["unmatched"] == 0 and got["accuracy"] >= BASELINE, got["misses"]
    assert got["labels"]["test"]["recall"] >= 0.8 and got["labels"]["edit"]["precision"] == 1.0


def test_cli_prints_scores_and_fails_under_min_accuracy(tmp_path: Path) -> None:
    data, gold = _setup(tmp_path)
    args = ["metrics", "labels", "--gold", str(gold), "--data", str(data)]
    ok = CliRunner().invoke(app, args)
    assert ok.exit_code == 0, ok.output
    assert ok.output.startswith("40 gold calls, 0 not in the data plane; accuracy ")
    assert "label\tprecision\trecall\tsupport" in ok.output and "miss\trun-gold\t" in ok.output
    low = CliRunner().invoke(app, [*args, "--min-accuracy", "1"])
    assert low.exit_code == 1


def test_gold_calls_missing_from_the_plane_are_counted(tmp_path: Path) -> None:
    data, _ = _setup(tmp_path)
    gold = tmp_path / "other.jsonl"
    gold.write_text(json.dumps({"run_id": "run-x", "seq": 1, "label": "edit"}) + "\n")
    assert score(connect(str(data)), str(gold))["unmatched"] == 1
