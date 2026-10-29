#!/usr/bin/env python3
"""Generate the docs' reference sections from the code, so they can't drift from it.

- `docs/cli.md`: every command group, command, argument and option of the `flightdeck` Typer app (`flightdeck.cli`);
- the `flightdeck.parquet/v1` column tables in `docs/contracts.md`, between the `generated:parquet` markers, from
  `src/flightdeck/dataplane/schema.py`.

`tests/test_docs_reference.py` fails when either is stale. Run it after changing a command, an option or a column:

    uv run python scripts/docs_reference.py [--check]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CLI_MD = ROOT / "docs" / "cli.md"
CONTRACTS_MD = ROOT / "docs" / "contracts.md"
BEGIN, END = "<!-- generated:parquet by scripts/docs_reference.py -->", "<!-- /generated:parquet -->"
KINDS = {"str": "text", "int": "integer", "float": "number", "path": "path", "file": "path", "boolean": "flag"}
ARROW = {"string": "", "int64": "int", "double": "float", "bool": "bool", "timestamp[ms, tz=UTC]": "timestamp",
         "list<item: string>": "list of strings"}
# Where each group (or top-level command) is explained; options without a description are described there.
GUIDES = {"compact": ("Data plane: compactor", "data-plane.md#compactor"),
          "query": ("Data plane: querying", "data-plane.md#querying"),
          "ingest": ("Data plane: ingest", "data-plane.md#ingest"),
          "stats": ("Statistics", "statistics.md#flightdeck-stats-compare"), "report": ("Reports", "reports.md"),
          "spec": ("Behavior specs", "behavior-specs.md"),
          "check": ("ADR checks and the nightly runner", "adr-checks.md"),
          "mutate": ("Mutation scoring", "mutation-scoring.md"),
          "task": ("Tasks", "tasks.md"), "holdout": ("Holdouts", "holdouts.md"),
          "knowledge": ("Knowledge evals", "knowledge-evals.md"), "experiment": ("Running experiments", "runners.md"),
          "cache": ("The trial cache", "cache.md"), "metrics": ("Weekly metrics", "metrics.md"),
          "judge": ("Judges", "judges.md")}


def guide(name: str) -> str:
    return "[{}]({})".format(*GUIDES[name]) if name in GUIDES else ""


# Read with os.environ rather than as an option's envvar (grep `os.environ` under src/flightdeck/).
ENVIRONMENT = [
    ("HANGAR_TOKEN", "Bearer token for hangar REST: `ingest experiment|job|session`, `experiment run|status|collect`."),
    ("GITHUB_TOKEN", "`report post` and `report experiment --post` (`issues:write` / `pull_requests:write`; `gist` "
     "for `--gist`), and `ingest github` (read-only)."),
    ("GITHUB_API_URL", "GitHub API root for posting reports (default `https://api.github.com`)."),
    ("FLIGHTDECK_AUTHOR", "Also read by `mutate run`, whose cost gate charges that author's sub-cap."),
]


def md(text: str | None) -> str:
    """One line of markdown: outside `code`, the characters HTML or a table would eat are escaped."""
    parts = " ".join((text or "").split()).split("`")
    esc = (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"), ("|", "&#124;"), ("*", "\\*"))
    for i in range(0, len(parts), 2):
        for a, b in esc:
            parts[i] = parts[i].replace(a, b)
    return "`".join(parts)


def panel(cmd: Any) -> str:
    return getattr(cmd, "rich_help_panel", None) or "Commands"


def in_help_order(subs: dict[str, Any]) -> list[tuple[str, Any]]:
    """The visible entries of a group as `--help` lists them: by panel (first appearance), then registration order."""
    panels = list(dict.fromkeys(panel(c) for c in subs.values()))
    return sorted(((n, c) for n, c in subs.items() if not c.hidden), key=lambda nc: panels.index(panel(nc[1])))


def walk(cmd: Any, path: tuple[str, ...]) -> list[tuple[tuple[str, ...], Any]]:
    """(path, command) for every visible command under `cmd`, groups expanded, in `--help` order."""
    subs = getattr(cmd, "commands", None)
    if subs is None:
        return [(path, cmd)]
    return [x for n, c in in_help_order(subs) for x in walk(c, path + (n,))]


def usage(path: tuple[str, ...], cmd: Any) -> str:
    args = []
    for p in cmd.params:
        if p.param_type_name == "argument":
            name = p.name.upper() + ("..." if p.nargs == -1 else "")
            args.append(name if p.required else f"[{name}]")
    opts = any(p.param_type_name == "option" and not p.hidden for p in cmd.params)
    return " ".join(["flightdeck", *path, *(["[OPTIONS]"] if opts else []), *args])


def row(p: Any) -> str:
    kind: str = KINDS.get(p.type.name) or str(p.type.name)
    if p.param_type_name == "argument":
        name = f"`{p.name.upper()}`"
        kind += ", one or more" if p.nargs == -1 else ""
    else:
        name = ", ".join(f"`{o}`" for o in p.opts) + "".join(f" / `{o}`" for o in p.secondary_opts)
        kind += ", repeatable" if p.multiple else ""
    if p.required:
        default = "required"
    elif p.default is None or p.default == "" or p.default == []:
        default = ""
    elif isinstance(p.default, bool):
        default = "on" if p.default else "off"
    else:
        default = f"`{p.default}`"
    envs = [p.envvar] if isinstance(p.envvar, str) else list(p.envvar or [])
    env = ", ".join(f"`{e}`" for e in envs)
    return f"| {name} | {kind} | {default} | {env} | {md(getattr(p, 'help', None))} |"


def cli_reference() -> str:
    import typer.main

    from flightdeck.cli import app

    root = typer.main.get_command(app)
    subs: dict[str, Any] = getattr(root, "commands", {})
    out = ["# CLI reference", "",
           "Every command, argument and option of `flightdeck`, generated from the code by `uv run python "
           "scripts/docs_reference.py` (`tests/test_docs_reference.py` fails when this page is stale). Every command "
           "also takes `--help`. Options with an environment variable read it when the option isn't given; an option "
           "without a description here is explained in its group's guide.", "",
           "| Command | What it does | Subcommands | Guide |", "| --- | --- | --- | --- |"]
    heading = None  # the table and the sections follow `flightdeck --help`: its panels, in its order
    for n, c in in_help_order(subs):
        if panel(c) != heading:
            heading = panel(c)
            out.append(f"| **{heading}** | | | |")
        cmds = ", ".join(f"[`{s}`](#flightdeck-{n}-{s})" for s in getattr(c, "commands", ()))
        out.append(f"| [`{n}`](#flightdeck-{n}) | {md(c.help)} | {cmds or '—'} | {guide(n) if n in GUIDES else '—'} |")
    group = None
    for path, cmd in walk(root, ()):
        if len(path) > 1 and path[0] != group:
            group = path[0]
            out += ["", f"## `flightdeck {group}`", "", md(subs[group].help) + f" Guide: {guide(group)}."]
        more = f" Guide: {guide(path[0])}." if len(path) == 1 and path[0] in GUIDES else ""
        head = f"{'##' if len(path) == 1 else '###'} `flightdeck {' '.join(path)}`"
        out += ["", head, "", md(cmd.help) + more, "", "```", usage(path, cmd), "```"]
        params = [p for p in cmd.params if not getattr(p, "hidden", False)]
        if params:
            out += ["", "| Argument or option | Type | Default | Environment | Description |",
                    "| --- | --- | --- | --- | --- |", *map(row, params)]
    out += ["", "## Environment", "",
            "Besides the options' environment variables above, flightdeck reads these directly:", "",
            "| Variable | Used for |", "| --- | --- |", *(f"| `{k}` | {v} |" for k, v in ENVIRONMENT)]
    return "\n".join(out) + "\n"


def parquet_columns() -> str:
    from flightdeck.dataplane import schema

    out = [BEGIN, "", f"Every table also has `run_id`, `source` and `dt` (`{schema.VERSION}`; `dt` is the partition, "
           "in the path). Columns are text unless a type is given.", ""]
    for title, tables in (("Flattened from hangar", schema.TABLES), ("From the outbox and GitHub", schema.OUTBOX),
                          ("Written by flightdeck", schema.DERIVED)):
        out += [f"| {title} | Columns |", "| --- | --- |"]
        for name, sch in tables.items():
            cols = [f"`{f.name}`" + (f" {ARROW[str(f.type)]}" if ARROW[str(f.type)] else "")
                    for f in sch if f.name not in ("run_id", "source", "dt")]
            out.append(f"| `{name}` | {', '.join(cols)} |")
        out.append("")
    return "\n".join(out + [END])


def contracts(text: str) -> str:
    head, sep, rest = text.partition(BEGIN)
    if not sep or END not in rest:
        raise SystemExit(f"{CONTRACTS_MD}: missing the {BEGIN} ... {END} markers")
    return head + parquet_columns() + rest.split(END, 1)[1]


def stale() -> list[str]:
    """The generated files that differ from what the code generates now."""
    out = []
    if not CLI_MD.is_file() or CLI_MD.read_text(encoding="utf-8") != cli_reference():
        out.append(str(CLI_MD.relative_to(ROOT)))
    text = CONTRACTS_MD.read_text(encoding="utf-8")
    if contracts(text) != text:
        out.append(str(CONTRACTS_MD.relative_to(ROOT)))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Generate the docs' CLI reference and Parquet columns.")
    ap.add_argument("--check", action="store_true", help="Exit 1 when a generated file is stale; write nothing.")
    args = ap.parse_args(argv)
    if args.check:
        bad = stale()
        print(f"stale: {', '.join(bad)} (run `uv run python scripts/docs_reference.py`)" if bad else "up to date")
        return 1 if bad else 0
    CLI_MD.write_text(cli_reference(), encoding="utf-8")
    CONTRACTS_MD.write_text(contracts(CONTRACTS_MD.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"wrote {CLI_MD.relative_to(ROOT)} and the columns in {CONTRACTS_MD.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
