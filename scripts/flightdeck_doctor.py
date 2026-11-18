#!/usr/bin/env python3
"""Check a laptop for flightdeck, and set it up (KAN-360). Sends nothing anywhere and prints no secret.

    uv run python scripts/flightdeck_doctor.py [doctor] [--data DIR]    # one line per check; exit 1 on a failure
    uv run python scripts/flightdeck_doctor.py setup [--data DIR]       # a private data plane and an env file

`doctor` prints `ok`, `warn`, `fail` or `skip` with the check's name, what it found and, when there is something to
do, `fix: <command>`. Only the required checks fail: DuckDB works offline, and the data plane is local, private
(mode 0700), outside any git checkout and outside any cloud-synced folder. Capture, GitHub and Docker only warn,
because a laptop can use flightdeck without them.

`setup` creates the data plane with mode 0700 (and tightens one that exists), writes `~/.flightdeck/env` for the
shell to source, and prints the next command. It lives here, not under `src/flightdeck/`, because the line budget
is spent (scripts/loc_budget.py).
"""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

DEFAULT_DATA = "~/.flightdeck/data"
ENV_FILE = "~/.flightdeck/env"
REMOTE = ("gs://", "s3://", "gcs://", "http://", "https://")
# Folders a sync client mirrors to the cloud: iCloud Drive, macOS File Provider (OneDrive, Dropbox, Google Drive,
# Box), and the clients' own default folders on Windows and Linux.
SYNCED_PARTS = ("Mobile Documents", "CloudStorage", "iCloudDrive", "iCloud Drive", "Dropbox", "Google Drive",
                "My Drive", "Box", "Box Sync")
SYNCED_PREFIXES = ("OneDrive",)
NO_DOWNLOAD: dict[str, Any] = {"autoinstall_known_extensions": False, "autoload_known_extensions": False}


@dataclass
class Check:
    name: str
    status: str  # ok, warn, fail, skip
    detail: str
    fix: str = ""

    def line(self) -> str:
        return f"{self.status:<5} {self.name:<16} {self.detail}" + (f"  fix: {self.fix}" if self.fix else "")


def data_root(arg: str | None, env: dict[str, str]) -> str:
    """The data plane as flightdeck resolves it: --data, else FLIGHTDECK_DATA_URI, else the default."""
    return arg or env.get("FLIGHTDECK_DATA_URI") or DEFAULT_DATA


def is_remote(uri: str) -> bool:
    return uri.startswith(REMOTE)


def git_checkout(path: Path) -> Path | None:
    """The git checkout `path` sits in, if any (a `.git` directory or file in it or a parent)."""
    for p in (path, *path.parents):
        if (p / ".git").exists():
            return p
    return None


def synced_folder(path: Path) -> str | None:
    """The part of `path` that a cloud sync client owns, if any."""
    for part in path.parts:
        if part in SYNCED_PARTS or part.startswith(SYNCED_PREFIXES):
            return part
    return None


# --- checks ------------------------------------------------------------------------------------------------------


def check_duckdb() -> Check:
    """DuckDB opens and sets a UTC time zone with no extension download (icu linked in or already installed)."""
    try:
        import duckdb
    except ImportError:
        return Check("duckdb", "fail", "duckdb is not installed", "uv sync --locked")
    try:
        con = duckdb.connect(config=NO_DOWNLOAD)
        row = con.execute("select install_mode, installed from duckdb_extensions() "
                          "where extension_name = 'icu'").fetchone()
        con.execute("SET TimeZone = 'UTC'")
    except duckdb.Error as e:
        return Check("duckdb", "fail", f"duckdb {duckdb.__version__} needs a download for icu ({type(e).__name__})",
                     "uv sync --locked (the locked wheels link icu in); or, once online: "
                     "python -c \"import duckdb; duckdb.connect().install_extension('icu')\"")
    how = "linked in" if row and row[0] == "STATICALLY_LINKED" else "installed locally"
    return Check("duckdb", "ok", f"duckdb {duckdb.__version__} works offline (icu {how})")


def check_data_uri(uri: str) -> Check:
    if is_remote(uri):
        return Check("data-location", "warn", f"{urlparse(uri).scheme}:// data plane: run data leaves this laptop",
                     f"export FLIGHTDECK_DATA_URI={DEFAULT_DATA}, unless your team approved that bucket")
    return Check("data-location", "ok", "local")


def check_data_plane(uri: str) -> list[Check]:
    """The local data plane exists, is mode 0700, and is outside git checkouts and cloud-synced folders."""
    if is_remote(uri):
        return [Check("data-plane", "skip", "not local")]
    path = Path(uri).expanduser().resolve()
    out = []
    if not path.is_dir():
        out.append(Check("data-plane", "fail", f"{path} does not exist", f"{_self()} setup --data {path}"))
    elif os.name == "nt":
        out.append(Check("data-plane", "warn", f"{path}: Windows, check that only you can read it by hand"))
    elif (mode := stat.S_IMODE(path.stat().st_mode)) & 0o077:
        out.append(Check("data-plane", "fail", f"{path} is mode {mode:04o}: others can read run data",
                         f"chmod -R go-rwx {path}"))
    else:
        out.append(Check("data-plane", "ok", f"{path} (mode 0700)"))
    if repo := git_checkout(path):
        out.append(Check("data-not-in-git", "fail", f"inside the git checkout {repo}",
                         f"{_self()} setup --data {DEFAULT_DATA}"))
    else:
        out.append(Check("data-not-in-git", "ok", "not inside a git checkout"))
    if part := synced_folder(path):
        out.append(Check("data-not-synced", "fail", f"inside a cloud-synced folder ({part})",
                         f"{_self()} setup --data {DEFAULT_DATA}"))
    else:
        out.append(Check("data-not-synced", "ok", "not inside a cloud-synced folder"))
    return out


def check_hangar(which: Callable[[str], str | None] = shutil.which) -> Check:
    """`hangar trace import` turns a Claude Code transcript into a trace flightdeck ingests."""
    exe = which("hangar")
    if not exe:
        return Check("capture-import", "warn", "hangar is not on PATH: Claude Code sessions can't be imported",
                     "install hangar (its README), then: hangar trace import --help")
    try:
        ok = subprocess.run([exe, "trace", "import", "--help"], capture_output=True, timeout=60).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        ok = False
    if not ok:
        return Check("capture-import", "warn", f"{exe} has no `trace import`", "upgrade hangar to main")
    return Check("capture-import", "ok", "hangar trace import")


def claude_projects(env: dict[str, str]) -> Path:
    return Path(env.get("CLAUDE_CONFIG_DIR") or "~/.claude").expanduser() / "projects"


def ingested_sessions(uri: str) -> set[str] | None:
    """Session ids in the data plane's `runs` table; None when it can't be read."""
    if is_remote(uri):
        return None
    runs = Path(uri).expanduser() / "runs"
    if not any(runs.glob("dt=*/*.parquet")):
        return set()
    try:
        import duckdb
        con = duckdb.connect(config=NO_DOWNLOAD)
        rows = con.execute("select distinct session_id from read_parquet(?, hive_partitioning=true, "
                           "union_by_name=true) where session_id is not null",
                           [str(runs / "dt=*" / "*.parquet")]).fetchall()
    except Exception:  # a doctor reports; it does not crash
        return None
    return {r[0] for r in rows}


def check_sessions(env: dict[str, str], uri: str) -> list[Check]:
    """Claude Code transcripts on this laptop, the newest, and how many the data plane doesn't hold yet."""
    root = claude_projects(env)
    if not root.is_dir():
        return [Check("capture-sessions", "warn", f"no {root}: no Claude Code sessions on this laptop",
                      "run Claude Code once, or set CLAUDE_CONFIG_DIR")]
    files = sorted(root.glob("*/*.jsonl"), key=lambda p: p.stat().st_mtime)
    if not files:
        return [Check("capture-sessions", "warn", f"{root} holds no session transcripts")]
    newest = datetime.fromtimestamp(files[-1].stat().st_mtime, UTC).date().isoformat()
    out = [Check("capture-sessions", "ok", f"{len(files)} session{'s' * (len(files) != 1)} in {root}, newest {newest}")]
    seen = ingested_sessions(uri)
    if seen is None:
        out.append(Check("capture-pending", "skip", "can't read the data plane's runs"))
    elif pending := [p for p in files if p.stem not in seen]:
        out.append(Check("capture-pending", "warn", f"{len(pending)} of {len(files)} sessions not yet ingested",
                         f"hangar trace import {pending[-1]} --out DIR && flightdeck ingest file DIR/trace.json"))
    else:
        out.append(Check("capture-pending", "ok", "every session is ingested"))
    return out


def remote_host(repo: Path) -> str | None:
    """The host of `origin` in the git checkout at `repo`, if any."""
    try:
        url = subprocess.run(["git", "-C", str(repo), "remote", "get-url", "origin"], capture_output=True,
                             text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None
    if not url:
        return None
    if "://" in url:
        return urlparse(url).hostname
    return url.split("@", 1)[-1].split(":", 1)[0]  # scp-like: git@host:owner/repo


def check_github(env: dict[str, str], host: str | None) -> list[Check]:
    """`ingest github` and `report --post` need a token, and GITHUB_API_URL for GitHub Enterprise (KAN-357)."""
    out = []
    if host is None:
        out.append(Check("github-host", "skip", "no git remote here"))
    elif host == "github.com" or env.get("GITHUB_API_URL"):
        out.append(Check("github-host", "ok", f"{host}" + (" via GITHUB_API_URL" if host != "github.com" else "")))
    else:
        out.append(Check("github-host", "warn", f"remote is {host}, not github.com, and GITHUB_API_URL is unset",
                         f"export GITHUB_API_URL=https://{host}/api/v3"))
    if env.get("GITHUB_TOKEN"):
        out.append(Check("github-token", "ok", "GITHUB_TOKEN is set (not shown)"))
    else:
        out.append(Check("github-token", "warn", "GITHUB_TOKEN is unset: `ingest github` can't read pull requests",
                         "export GITHUB_TOKEN=<read-only token: Pull requests, Metadata>"))
    return out


def check_docker(which: Callable[[str], str | None] = shutil.which) -> Check:
    """Optional: the local runner (`--backend local`) runs tasks in Docker."""
    exe = which("docker")
    if not exe:
        return Check("docker", "skip", "not installed (optional: the local runner needs it)")
    try:
        ok = subprocess.run([exe, "info"], capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        ok = False
    return Check("docker", "ok", "running") if ok else Check("docker", "warn", "installed but not running",
                                                             "start Docker (only for the local runner)")


def doctor(data: str | None = None, env: dict[str, str] | None = None, repo: Path | None = None) -> list[Check]:
    env = dict(os.environ) if env is None else env
    uri = data_root(data, env)
    return [check_duckdb(), check_data_uri(uri), *check_data_plane(uri), check_hangar(), *check_sessions(env, uri),
            *check_github(env, remote_host(repo or Path.cwd())), check_docker()]


# --- setup -------------------------------------------------------------------------------------------------------


def setup(data: str | None = None, env: dict[str, str] | None = None, env_file: str = ENV_FILE) -> int:
    """Create (or tighten) a private local data plane, write an env file, print the next command."""
    env = dict(os.environ) if env is None else env
    uri = data_root(data, env)
    if is_remote(uri):
        print(f"setup makes a local data plane; {uri} is remote. Pass --data {DEFAULT_DATA}.", file=sys.stderr)
        return 1
    path = Path(uri).expanduser().resolve()
    refused = (f"inside the git checkout {repo}" if (repo := git_checkout(path)) else
               f"inside a cloud-synced folder ({part})" if (part := synced_folder(path)) else "")
    if refused:
        print(f"refusing {path}: {refused}. Pass --data {DEFAULT_DATA} or another private folder.", file=sys.stderr)
        return 1
    home = Path("~/.flightdeck").expanduser()
    for d in (home, path):
        d.mkdir(mode=0o700, parents=True, exist_ok=True)
    for d in {home, path}:
        os.chmod(d, 0o700)
    for p in path.rglob("*"):  # earlier writes were 0644 / 0755 (the Nov 10 review)
        if not p.is_symlink():
            os.chmod(p, stat.S_IMODE(p.stat().st_mode) & ~0o077)
    envf = Path(env_file).expanduser()
    envf.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    envf.write_text(f"# written by flightdeck_doctor.py setup\nexport FLIGHTDECK_DATA_URI={path}\n",
                    encoding="utf-8")
    os.chmod(envf, 0o600)
    print(f"data plane: {path} (mode 0700)\nenv file:   {envf}")
    print(f"next: . {envf} && {_self()}")
    return 0


def _self() -> str:
    return "uv run python scripts/flightdeck_doctor.py"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    ap.add_argument("command", nargs="?", choices=("doctor", "setup"), default="doctor")
    ap.add_argument("--data", help=f"data plane directory (default: FLIGHTDECK_DATA_URI, else {DEFAULT_DATA})")
    ap.add_argument("--env-file", default=ENV_FILE, help=f"setup: where to write the env file (default {ENV_FILE})")
    args = ap.parse_args(argv)
    if args.command == "setup":
        return setup(args.data, env_file=args.env_file)
    checks = doctor(args.data)
    for c in checks:
        print(c.line())
    failed = [c.name for c in checks if c.status == "fail"]
    print(f"{len(failed)} failed: {', '.join(failed)}" if failed else "all required checks pass")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
