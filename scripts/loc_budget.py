#!/usr/bin/env python3
"""Fail when flightdeck's v0 analysis code grows past its line budget.

Counts non-blank lines that are not `#` comments in every `*.py` file under `src/flightdeck/`, except `ported/`
(code moved in from ai-dlc and hangar, reported separately and outside the budget). Standard library only, so CI
can run it without installing the package.

    python scripts/loc_budget.py [--root src/flightdeck] [--limit N]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

LIMIT = 3416  # docs/decisions/0005-post-v0-budget.md (0004 set 2,800, 0003 2,500)
EXCLUDED = ("ported",)


def count_lines(path: Path) -> int:
    """Non-blank, non-comment lines of one file."""
    lines = path.read_text(encoding="utf-8").splitlines()
    return sum(1 for line in lines if line.strip() and not line.strip().startswith("#"))


def tally(root: Path) -> tuple[dict[str, int], dict[str, int]]:
    """Lines per top-level area under root: (counted, excluded). Files directly under root count as '.'."""
    counted: dict[str, int] = {}
    excluded: dict[str, int] = {}
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root)
        area = rel.parts[0] if len(rel.parts) > 1 else "."
        bucket = excluded if area in EXCLUDED else counted
        bucket[area] = bucket.get(area, 0) + count_lines(path)
    return counted, excluded


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail when flightdeck's v0 code grows past its line budget.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent / "src" / "flightdeck")
    parser.add_argument("--limit", type=int, default=LIMIT)
    args = parser.parse_args(argv)
    if not args.root.is_dir():
        print(f"loc-budget: {args.root} is not a directory", file=sys.stderr)
        return 2
    counted, excluded = tally(args.root)
    total = sum(counted.values())
    print(f"loc-budget: counted under {args.root}")
    for area, n in sorted(counted.items()):
        print(f"  {area + '/' if area != '.' else '(top level)':<16} {n:>6}")
    for area, n in sorted(excluded.items()):
        print(f"  {area + '/':<16} {n:>6}  (excluded)")
    print(f"  {'total':<16} {total:>6} / {args.limit}")
    if total > args.limit:
        print(f"loc-budget: FAIL, {total - args.limit} lines over the v0 budget of {args.limit}", file=sys.stderr)
        return 1
    print(f"loc-budget: ok, {args.limit - total} lines left")
    return 0


if __name__ == "__main__":
    sys.exit(main())
