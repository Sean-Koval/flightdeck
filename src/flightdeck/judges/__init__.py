"""`flightdeck judge`: rubric judges, calibrated against people before anything uses them (docs/judges.md).

A rubric version (`rubric.yaml`: id, version, question, scale, criteria, examples and the judge: a concrete model id
and its prompt) is identified by a digest over all of it, so changing the text or the judge is a new version that needs
calibrating again. People label a stratified sample; `calibrate` compares the judge's labels on the same runs (Cohen's
kappa, weighted for ordinal scales, with a bootstrap interval) and marks the rubric `usable` only when the interval's
lower bound reaches 0.6. Flightdeck holds no model credentials (ADR-0001): the judge runs elsewhere (a hangar job, or
an operator's script with a capped API key) and `score` ingests its labels. Estimates combine human and judge labels by
prediction-powered inference; a raw judge average is never printed alone.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import random
import sys
from pathlib import Path
from typing import Annotated, Any

import numpy as np
import typer
import yaml

from flightdeck.stats.core import cohen_kappa

THRESHOLD = 0.6  # hangar 0007 §5.5's floor


def load_rubric(path: Path) -> dict[str, Any]:
    from flightdeck.runners.hangar import model_problem

    r = yaml.safe_load(path.read_text()) or {}
    missing = {"id", "version", "question", "scale", "criteria", "judge"} - set(r)
    if missing or r["scale"] not in ("binary", "ordinal") or (r["scale"] == "ordinal" and not r.get("levels")):
        raise ValueError(f"{path}: needs id, version, question, scale (binary, or ordinal with levels), criteria, "
                         f"judge {{model, prompt}}; missing {sorted(missing)}")
    if p := model_problem((r["judge"] or {}).get("model")):
        raise ValueError(f"{path}: judge.model: {p}; a judge is pinned to a concrete model id")
    return r


def digest(r: dict[str, Any]) -> str:
    keys = ("id", "version", "question", "scale", "levels", "criteria", "examples", "judge")
    return "sha256:" + hashlib.sha256(json.dumps({k: r.get(k) for k in keys}, sort_keys=True).encode()).hexdigest()


def status(path: Path) -> str:
    """usable, provisional, unusable, uncalibrated, or stale (the rubric or its judge changed since calibration)."""
    cal = path.with_suffix(".calibration.json")
    if not cal.is_file():
        return "uncalibrated"
    c = json.loads(cal.read_text())
    return c["status"] if c["digest"] == digest(load_rubric(path)) else "stale"


def kappa(pairs: list[tuple[float, float]], levels: list[float] | None = None) -> float:
    """Cohen's kappa for binary labels; quadratically weighted kappa over `levels` for ordinal ones."""
    if not levels:
        return cohen_kappa([(bool(a), bool(b)) for a, b in pairs])
    idx = {v: i for i, v in enumerate(levels)}
    m = np.zeros((len(levels), len(levels)))
    for a, b in pairs:
        m[idx[a], idx[b]] += 1
    w = np.array([[(i - j) ** 2 for j in range(len(levels))] for i in range(len(levels))], float)
    exp = np.outer(m.sum(1), m.sum(0)) / m.sum()
    return 1.0 if (w * exp).sum() == 0 else float(1 - (w * m).sum() / (w * exp).sum())


def calibrate(r: dict[str, Any], human: list[dict], judge: list[dict], b: int = 2000, seed: int = 0) -> dict:
    """The judge against the primary human label per run (the first rater by name), with the raters' own kappa."""
    by: dict[str, dict[str, float]] = {}
    human = [h for h in human if h.get("label") not in ("", None)]
    for h in human:
        by.setdefault(h["run_id"], {})[h["rater"]] = float(h["label"])
    raters = sorted({h["rater"] for h in human})
    primary = {rid: ls[min(ls)] for rid, ls in by.items()}
    lv = [float(x) for x in r.get("levels") or []] or None
    pairs = [(primary[j["run_id"]], float(j["label"])) for j in judge if j["run_id"] in primary]
    if len(pairs) < 10:
        raise ValueError(f"only {len(pairs)} runs carry a human and a judge label; label at least 10 (aim 100-200)")
    rng = np.random.default_rng(seed)
    boot = [kappa([pairs[i] for i in rng.integers(0, len(pairs), len(pairs))], lv) for _ in range(b)]
    k, (lo, hi) = kappa(pairs, lv), np.nanquantile(boot, [0.025, 0.975])
    both = [(ls[raters[0]], ls[raters[1]]) for ls in by.values() if len(raters) > 1 and set(raters[:2]) <= set(ls)]
    curve = {str(v): [sum(1 for _, j in pairs if j == v), float(np.mean([h for h, j in pairs if j == v]))]
             for v in sorted({j for _, j in pairs})}
    return {"rubric": f"{r['id']}@{r['version']}", "digest": digest(r), "judge": r["judge"]["model"], "kappa": k,
            "ci95": [float(lo), float(hi)], "n": len(pairs), "inter_rater": kappa(both, lv) if both else None,
            "status": "usable" if lo >= THRESHOLD else "provisional" if k >= THRESHOLD else "unusable",
            "curve": curve}


def estimate_line(human: dict[str, float], judge: dict[str, float]) -> str:
    """The PPI estimate with the raw judge mean beside it, never the raw mean alone (reports use this)."""
    from flightdeck.stats.ppi import ppi_mean

    lab = [rid for rid in human if rid in judge]
    p = ppi_mean([human[x] for x in lab], [judge[x] for x in lab], [v for k, v in judge.items() if k not in human])
    return (f"PPI estimate {p.estimate:.3f} [{p.low:.3f}, {p.high:.3f}] ({p.note}, {p.n_trials} runs); raw judge "
            f"mean {np.mean(list(judge.values())):.3f}, not an estimate")


app = typer.Typer(help="Rubric judges: label sheets, calibration, judge labels, PPI estimates.", no_args_is_help=True)
DATA = Annotated[str, typer.Option("--data", envvar="FLIGHTDECK_DATA_URI", help="Data plane root.")]


def _rows(p: Path) -> list[dict]:
    return list(csv.DictReader(p.open())) if p.suffix == ".csv" else [json.loads(x) for x in p.read_text().splitlines()
                                                                         if x.strip()]


@app.command()
def label(rubric: Path, data: DATA, sample: int = 150, stratify_by: str = "variant", raters: int = 2,
          overlap: int = 30, seed: int = 0) -> None:
    """A labelling sheet (CSV on stdout): a stratified sample of runs, the first `overlap` items for every rater and
    the rest shared out; variant names stay off the sheet (blind)."""
    from flightdeck.dataplane.duck import connect

    r, cols = load_rubric(rubric), [c for c in stratify_by.split(",") if c]
    con = connect(os.path.expanduser(data))
    rows = con.execute(f"select run_id, {', '.join(cols)} from runs order by 1").fetchall()
    strata: dict[tuple, list[str]] = {}
    for row in rows:
        strata.setdefault(tuple(row[1:]), []).append(row[0])
    rng, picked = random.Random(seed), []
    for ids in strata.values():
        picked += rng.sample(ids, min(len(ids), max(1, round(sample * len(ids) / max(1, len(rows))))))
    rng.shuffle(picked)
    out = csv.writer(sys.stdout)
    out.writerow(["item", "run_id", "rubric", "rater", "label"])
    for i, rid in enumerate(picked[:sample]):
        for k in range(raters) if i < overlap else [i % raters]:
            out.writerow([i + 1, rid, f"{r['id']}@{r['version']}", f"rater-{k + 1}", ""])


@app.command("calibrate")
def calibrate_cmd(rubric: Path, human: Path, judge: Path, seed: int = 0) -> None:
    """Kappa with its interval, the calibration curve and the status; writes <rubric>.calibration.json."""
    c = calibrate(load_rubric(rubric), _rows(human), _rows(judge), seed=seed)
    rubric.with_suffix(".calibration.json").write_text(json.dumps(c, indent=1) + "\n")
    ir = "-" if c["inter_rater"] is None else f"{c['inter_rater']:.2f}"
    typer.echo(f"{c['rubric']} judged by {c['judge']}: kappa {c['kappa']:.2f} [{c['ci95'][0]:.2f}, "
               f"{c['ci95'][1]:.2f}] on {c['n']} runs; raters' kappa {ir}; {c['status']}")
    for v, (n, h) in c["curve"].items():
        typer.echo(f"  judge says {v}: {n} runs, human mean {h:.2f}")


@app.command()
def score(rubric: Path, labels: Path, data: DATA) -> None:
    """Store a judge's labels (`run_id, label, rationale`) as judge_labels: rationale text stays out, its digest in."""
    from flightdeck.dataplane.schema import write_partitioned

    r, st = load_rubric(rubric), status(rubric)
    rows = [{"run_id": x["run_id"], "source": x.get("source") or "experiment", "dt": x.get("dt") or "unknown",
             "rubric": f"{r['id']}@{r['version']}", "rubric_digest": digest(r), "judge": r["judge"]["model"],
             "label": float(x["label"]), "rationale_digest": "sha256:" + hashlib.sha256(
                 str(x.get("rationale") or "").encode()).hexdigest(), "status": st} for x in _rows(labels)]
    write_partitioned("judge_labels", rows, os.path.expanduser(data), part=f"{r['id']}-{r['version']}")
    typer.echo(f"stored {len(rows)} labels for {r['id']}@{r['version']} ({st}" +
               ("" if st == "usable" else ": not usable in a decision") + ")")


@app.command()
def estimate(rubric: Path, human: Path, data: DATA) -> None:
    """The PPI estimate of the rubric's mean over the judge-labelled runs, from the human labels and the judge's."""
    from flightdeck.dataplane.duck import connect

    r = load_rubric(rubric)
    judge = dict(connect(os.path.expanduser(data)).execute(
        "select run_id, avg(label) from judge_labels where rubric_digest = ? group by 1", [digest(r)]).fetchall())
    hum = {h["run_id"]: float(h["label"]) for h in sorted(_rows(human), key=lambda h: h["rater"], reverse=True)
           if h.get("label") not in ("", None)}
    typer.echo(f"{r['id']}@{r['version']} ({status(rubric)}): " + estimate_line(hum, judge))
