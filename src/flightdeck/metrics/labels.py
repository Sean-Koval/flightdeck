"""`flightdeck metrics labels`: how often `step_labels` agrees with a hand-labelled gold set (docs/label-gold-sets.md).

A gold file is JSON lines, one per tool call: `run_id`, `seq`, the hand `label` (the call's main label) and, optionally,
every `labels` it should carry. Real gold sets are team data and stay in the private data repo (ADR-0002).
"""

from __future__ import annotations

import os

import duckdb
import typer

from flightdeck.dataplane.duck import connect

SQL = """select g.run_id, g.seq, g.label, coalesce(g.labels, [g.label]), s.label, s.labels, s.tool_input
from read_json(?, format = 'newline_delimited',
               columns = {run_id: 'varchar', seq: 'bigint', label: 'varchar', labels: 'varchar[]'}) g
left join step_labels s using (run_id, seq) order by g.run_id, g.seq"""


def score(con: duckdb.DuckDBPyConnection, gold: str) -> dict:
    """Accuracy of the first label, and precision and recall of each label over the calls' label sets."""
    rows = con.execute(SQL, [gold]).fetchall()
    found = [r for r in rows if r[4] is not None]
    per: dict[str, list[int]] = {}  # label: [true positives, false positives, false negatives]
    for _, _, _, want, _, got, _ in found:
        for lab in set(want) | set(got):
            n = per.setdefault(lab, [0, 0, 0])
            n[0 if lab in want and lab in got else 1 if lab in got else 2] += 1
    return {"calls": len(rows), "unmatched": len(rows) - len(found),
            "accuracy": sum(r[2] == r[4] for r in found) / len(found) if found else None,
            "labels": {k: {"precision": tp / (tp + fp) if tp + fp else None,
                           "recall": tp / (tp + fn) if tp + fn else None, "support": tp + fn}
                       for k, (tp, fp, fn) in sorted(per.items())},
            "misses": [{"run_id": r[0], "seq": r[1], "want": r[2], "got": r[4], "labels": r[5],
                        "input": (r[6] or "")[:80]} for r in found if r[2] != r[4]]}


def labels(
    gold: str = typer.Option(..., help="Gold file: JSON lines of run_id, seq, label and optional labels."),
    data: str = typer.Option(..., "--data", envvar="FLIGHTDECK_DATA_URI", help="Data plane root."),
    min_accuracy: float = typer.Option(0.0, help="Exit 1 when first-label accuracy is below this."),
) -> None:
    """Score step labels against a hand-labelled gold set: accuracy, per-label precision and recall, the misses."""
    out = score(connect(os.path.expanduser(data)), os.path.expanduser(gold))
    pct = (lambda x: "-" if x is None else f"{x:.0%}")  # noqa: E731
    typer.echo(f"{out['calls']} gold calls, {out['unmatched']} not in the data plane; accuracy {pct(out['accuracy'])}")
    typer.echo("label\tprecision\trecall\tsupport")
    for k, v in out["labels"].items():
        typer.echo(f"{k}\t{pct(v['precision'])}\t{pct(v['recall'])}\t{v['support']}")
    for m in out["misses"]:
        typer.echo(f"miss\t{m['run_id']}\t{m['seq']}\twant {m['want']}\tgot {m['got']}\t{m['input']!r}")
    if out["accuracy"] is None or out["accuracy"] < min_accuracy:
        raise typer.Exit(1)
