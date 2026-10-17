"""Rubric judges and PPI (#27, docs/judges.md): versions, the kappa gate, prediction-powered inference."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import numpy as np
import pytest
import yaml
from typer.testing import CliRunner

from flightdeck import judges
from flightdeck.cli import app
from flightdeck.dataplane.ingest import write_unit
from flightdeck.report.markdown import render_report
from flightdeck.stats.ppi import ppi_mean, ppi_stratified

run = CliRunner().invoke
RUBRIC = {"id": "handoff-quality", "version": 1, "question": "Is the handoff note complete?", "scale": "binary",
          "criteria": ["names what changed", "names what is left"], "examples": [],
          "judge": {"model": "claude-opus-5-5", "prompt": "Rate the note against the criteria. Answer 0 or 1."}}


def _rubric(tmp: Path, **over) -> Path:
    p = tmp / "handoff.yaml"
    p.write_text(yaml.safe_dump({**RUBRIC, **over}))
    return p


def _labels(tmp: Path, agree: float, n: int = 120, seed: int = 0) -> tuple[Path, Path]:
    rng = np.random.default_rng(seed)
    truth = rng.integers(0, 2, n)
    j = [int(t) if rng.random() < agree else 1 - int(t) for t in truth]
    h, jp = tmp / "human.csv", tmp / "judge.jsonl"
    with h.open("w") as f:
        w = csv.writer(f)
        w.writerow(["item", "run_id", "rubric", "rater", "label"])
        for i, t in enumerate(truth):
            w.writerow([i, f"r{i}", "handoff-quality@1", "rater-1", t])
            if i < 30:  # the two raters' overlap
                w.writerow([i, f"r{i}", "handoff-quality@1", "rater-2", t if i % 10 else 1 - t])
    jp.write_text("".join(json.dumps({"run_id": f"r{i}", "label": x, "rationale": "secret team code"}) + "\n"
                          for i, x in enumerate(j)))
    return h, jp


def test_versions_and_concrete_judges(tmp_path: Path) -> None:
    p = _rubric(tmp_path)
    d = judges.digest(judges.load_rubric(p))
    assert judges.digest(judges.load_rubric(_rubric(tmp_path, criteria=["names what changed"]))) != d
    assert judges.digest(judges.load_rubric(_rubric(tmp_path, judge={**RUBRIC["judge"], "model": "gpt-6.1-sol"}))) != d
    with pytest.raises(ValueError, match="concrete"):
        judges.load_rubric(_rubric(tmp_path, judge={"model": "frontier", "prompt": "x"}))
    with pytest.raises(ValueError, match="levels"):
        judges.load_rubric(_rubric(tmp_path, scale="ordinal"))


def test_kappa_gate_and_recalibration_after_a_change(tmp_path: Path) -> None:
    p = _rubric(tmp_path)
    assert judges.status(p) == "uncalibrated"
    h, j = _labels(tmp_path, agree=0.97)
    r = run(app, ["judge", "calibrate", str(p), str(h), str(j)])
    assert r.exit_code == 0, r.output
    assert "; usable" in r.output and "raters' kappa 0.78" in r.output and "judge says 1.0" in r.output
    cal = json.loads(p.with_suffix(".calibration.json").read_text())
    assert cal["ci95"][0] >= 0.6 and cal["status"] == "usable" and judges.status(p) == "usable"
    p.write_text(p.read_text().replace("Is the handoff note complete?", "Is the note complete?"))
    assert judges.status(p) == "stale"  # new text: recalibrate
    _rubric(tmp_path)
    h, j = _labels(tmp_path, agree=0.72)
    assert "unusable" in run(app, ["judge", "calibrate", str(p), str(h), str(j)]).output
    assert judges.status(p) == "unusable"


def test_weighted_kappa_for_ordinal_scales() -> None:
    lv = [0.0, 1.0, 2.0, 3.0]
    assert judges.kappa([(x, x) for x in lv * 5], lv) == 1.0
    near = judges.kappa([(0, 1), (1, 2), (2, 3), (3, 3), (0, 0), (1, 1), (2, 2)], lv)
    far = judges.kappa([(0, 3), (1, 3), (2, 0), (3, 0), (0, 0), (1, 1), (2, 2)], lv)
    assert 0 < near < 1 and far < near


def test_an_unusable_rubric_cannot_decide(tmp_path: Path) -> None:
    p = _rubric(tmp_path)
    decision = tmp_path / "decision.yaml"
    decision.write_text(f"metric: resolved\ndirection: higher\nrubric: {p.name}\n")
    with pytest.raises(ValueError, match="uncalibrated"):
        render_report(None, "exp", decision=decision)


def test_ppi_covers_at_nominal_rate_and_beats_human_only() -> None:
    """The acceptance simulation: a biased judge, 100 human labels, 2,000 judge labels, true mean 0.6."""
    rng, cover, narrower, trials = np.random.default_rng(7), 0, 0, 400
    for _ in range(trials):
        y = rng.random(2100) < 0.6
        f = np.where(rng.random(2100) < 0.85, y, ~y).astype(float) * 0.9 + 0.05  # agrees 85%, shrunk towards 0.5
        p = ppi_mean(y[:100].astype(float).tolist(), f[:100].tolist(), f[100:].tolist())
        cover += p.low <= 0.6 <= p.high
        human = 1.96 * y[:100].std(ddof=1) / 10
        narrower += (p.high - p.low) < 2 * human
    assert 0.92 <= cover / trials <= 0.98 and narrower / trials > 0.95
    s = ppi_stratified({"a": ([1.0, 0.0, 1.0, 1.0], [1.0, 1.0, 1.0, 0.0], [1.0, 0.0] * 5),
                        "b": ([0.0, 0.0, 1.0, 0.0], [0.0, 1.0, 1.0, 0.0], [0.0, 1.0] * 10)})
    assert s.low < s.estimate < s.high and "2 strata" in s.note


def test_label_sheet_score_and_estimate_never_print_a_raw_mean_alone(tmp_path: Path) -> None:
    plane = str(tmp_path / "plane")
    write_unit({"runs": [{"run_id": f"r{i}", "source": "experiment", "dt": "2026-10-17", "variant": "ab"[i % 2]}
                         for i in range(120)]}, plane, "u")
    p = _rubric(tmp_path)
    sheet = run(app, ["judge", "label", str(p), "--data", plane, "--sample", "40", "--overlap", "10"])
    rows = list(csv.DictReader(io.StringIO(sheet.output)))
    assert len(rows) == 10 * 2 + 30 and len({r["run_id"] for r in rows}) == 40
    assert "variant" not in rows[0] and {r["rater"] for r in rows} == {"rater-1", "rater-2"}  # blind to variants
    h, j = _labels(tmp_path, agree=0.95)
    stored = run(app, ["judge", "score", str(p), str(j), "--data", plane])
    assert stored.exit_code == 0 and "not usable in a decision" in stored.output
    est = run(app, ["judge", "estimate", str(p), str(h), "--data", plane])
    assert est.exit_code == 0, est.output
    assert "PPI estimate" in est.output and est.output.index("PPI estimate") < est.output.index("raw judge mean")
    raw = [ln for ln in est.output.splitlines() if "raw judge mean" in ln]
    assert all("PPI estimate" in ln for ln in raw)  # the template rule
    assert "secret team code" not in Path(plane, "judge_labels").joinpath(
        next(Path(plane, "judge_labels").rglob("*.parquet")).relative_to(Path(plane, "judge_labels"))).read_bytes(
    ).decode("latin-1")
