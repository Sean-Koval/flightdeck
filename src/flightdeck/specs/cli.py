"""`flightdeck spec lint|test`: behavior specs against one trace export (docs/behavior-specs.md)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from flightdeck.specs import lang

spec_app = typer.Typer(help="Behavior specs over traces: lint them, test them on an export.",
                       no_args_is_help=True)


@spec_app.command("lint")
def lint(paths: list[Path]) -> None:
    """Load specs and print warnings; exit 1 when one does not load."""
    bad = 0
    for p in paths:
        try:
            for s in lang.load(p.read_text()):
                for w in lang.lint(s):
                    typer.echo(f"{p}: warning: {w}")
        except (lang.SpecError, ValueError) as e:
            typer.echo(f"{p}: error: {e}")
            bad = 1
    raise typer.Exit(bad)


@spec_app.command("test")
def test(
    spec: Path,
    trace: Annotated[Path, typer.Option(help="A hangar.trace/v1 OTLP/JSON export.")],
    engine: Annotated[str, typer.Option(help="python (the reference evaluator) or sql (the nightly one).")] = "python",
) -> None:
    """Evaluate specs on one export: `spec<TAB>unit<TAB>result` lines; exit 1 on any fail or unknown."""
    from flightdeck.dataplane.flatten import flatten_trace

    tables = flatten_trace(json.loads(trace.read_text()))
    con = lang.connect_tables(tables) if engine == "sql" else None
    worst = False
    for s in lang.load(spec.read_text()):
        res = lang.evaluate_sql(s, con) if con else lang.evaluate(s, tables)
        for unit, r in sorted(res.items()):
            typer.echo(f"{s['id']}\t{unit}\t{r}")
            worst |= r in (lang.FAIL, lang.UNKNOWN)
    raise typer.Exit(int(worst))


check_app = typer.Typer(help="Run the behavior specs and ADR checks over the data plane; label edits to them.",
                        no_args_is_help=True)


@check_app.command("run")
def run(
    data: Annotated[str, typer.Option(envvar="FLIGHTDECK_DATA_URI", help="Data plane root: a directory or gs:// URI.")],
    date: Annotated[str, typer.Option(help="The dt partition to judge (default: yesterday, UTC).")] = "",
    specs: Annotated[list[Path] | None, typer.Option(help="Spec files, or directories of *.yaml.")] = None,
    adrs: Annotated[list[str] | None, typer.Option(help="<git checkout>:<dir> of ADRs (HEAD), or a dir.")] = None,
    out: Annotated[str, typer.Option(help="Local plane root to write spec_results to (default: --data).")] = "",
    window: Annotated[int, typer.Option(help="Days of spec_results history for change-point alerts.")] = 14,
    alerts_repo: Annotated[str, typer.Option(help="owner/repo to open flightdeck:violation issues in (via gh).")] = "",
) -> None:
    """Evaluate every spec and accepted ADR check over one day, write spec_results, and flag violation jumps."""
    import os
    from datetime import UTC, datetime, timedelta

    from flightdeck.dataplane.duck import connect
    from flightdeck.dataplane.schema import write_partitioned
    from flightdeck.specs import checks
    from flightdeck.stats.compare import plain

    out = os.path.expanduser(out or data)
    if out.startswith(("gs://", "s3://")):
        raise typer.BadParameter("spec_results are written to a local plane root (--out); sync it to the bucket")
    day = date or (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")
    files = [f for p in specs or [] for f in (sorted(p.glob("*.yaml")) if p.is_dir() else [p])]
    todo = [s for f in files for s in lang.load(f.read_text())] + [s for a in adrs or [] for s in checks.adr_specs(a)]
    con = connect(os.path.expanduser(data))
    rows = checks.run(con, todo, day)
    write_partitioned("spec_results", rows, out, part=f"check-{day}")  # one part per day: reruns replace only that day
    by: dict[tuple, list[dict]] = {}
    for r in rows:
        by.setdefault((r["spec_source"], r["spec_id"]), []).append(r)
    table, failed, unknown = ["| spec | applied | passed | failed | unknown | |", "| --- |"], 0, 0
    for (src, sid), rs in sorted(by.items()):  # a spec that applied to no unit reads as such, never as passed
        n = {k: sum(r["result"] == k for r in rs) for k in (lang.PASS, lang.FAIL, lang.UNKNOWN)}
        fails = [r["run_id"] for r in rs if r["result"] == lang.FAIL][:3]
        applied = n[lang.PASS] + n[lang.FAIL]
        cells = [applied, n[lang.PASS], n[lang.FAIL], n[lang.UNKNOWN]] if applied else ["—"] * 3 + [n[lang.UNKNOWN]]
        note = f"e.g. {' '.join(fails)}" if fails else "" if applied else "not applied"
        table.append(f"| {sid if src == 'spec' else f'{sid} ({src})'} | {' | '.join(map(str, cells))} | {note} |")
        failed, unknown = failed + n[lang.FAIL], unknown + n[lang.UNKNOWN]
    typer.echo(plain("\n".join(table)))
    typer.secho(f"{len(by)} specs over {max(map(len, by.values()), default=0)} units: {failed} failed, {unknown} "
                "unknown", fg="red" if failed else None)
    since = (datetime.strptime(day, "%Y-%m-%d") - timedelta(days=window)).strftime("%Y-%m-%d")
    hist = []
    tables = {r[0] for r in con.execute("select table_name from information_schema.tables").fetchall()}
    if "spec_results" in tables:
        cur = con.execute("select * from spec_results where cast(dt as varchar) >= ? and cast(dt as varchar) < ?",
                          [since, day])
        hist = [dict(zip([d[0] for d in cur.description], row, strict=True)) for row in cur.fetchall()]
    found = checks.alerts(hist + rows)
    for a in found:
        typer.echo(f"ALERT\t{a['spec_source']}\t{a['check']}\t{a['repo']}\t{a['day']}\t{a['before']:.0%} -> "
                   f"{a['after']:.0%}\tchanged: {', '.join(a['changed']) or '-'}")
    if found and alerts_repo:
        checks.file_alerts(found, alerts_repo)


@check_app.command("diff")
def diff(old: Path, new: Path) -> None:
    """Label an edit to checks (spec files or ADRs): tightened, loosened or removed. A missing file has no checks."""
    from flightdeck.specs import checks

    res = checks.diff(checks.load_checks(old), checks.load_checks(new))
    for k, v in res.items():
        typer.echo(f"{k}\t{v}")
    typer.echo(f"label: checks:{max(res.values(), key=checks.LABELS.index, default='unchanged')}")
