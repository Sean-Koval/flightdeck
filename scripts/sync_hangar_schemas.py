#!/usr/bin/env python3
"""Refresh the vendored copies of hangar's interface schemas from a hangar checkout.

Copies `docs/api/{experiment,manifest,run}.schema.json` at a git ref into `src/flightdeck/dataplane/hangar_schemas/` and
records the hangar commit they came from in `SOURCE.json`, which `flightdeck ingest` prints when it warns about a
mismatch. Standard library and git only.

    python scripts/sync_hangar_schemas.py --hangar ../hangar [--ref origin/main]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

FILES = ("experiment.schema.json", "manifest.schema.json", "run.schema.json")
DEST = Path(__file__).resolve().parent.parent / "src" / "flightdeck" / "dataplane" / "hangar_schemas"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


def sync(repo: Path, ref: str, dest: Path = DEST) -> str:
    """Write the schemas at `ref` into `dest` and return the hangar commit."""
    commit = git(repo, "rev-parse", f"{ref}^{{commit}}").strip()
    dest.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        text = git(repo, "show", f"{commit}:docs/api/{name}")
        json.loads(text)  # refuse to vendor something that isn't JSON
        (dest / name).write_text(text, encoding="utf-8")
    source = {"repo": "https://github.com/Sean-Koval/hangar", "commit": commit,
              "files": [f"docs/api/{f}" for f in FILES]}
    (dest / "SOURCE.json").write_text(json.dumps(source, indent=1) + "\n", encoding="utf-8")
    return commit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh flightdeck's vendored hangar schemas.")
    parser.add_argument("--hangar", type=Path, required=True, help="A hangar git checkout")
    parser.add_argument("--ref", default="origin/main", help="Git ref to copy from (default origin/main)")
    args = parser.parse_args(argv)
    print(f"sync-hangar-schemas: {DEST} <- hangar {sync(args.hangar, args.ref)[:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
