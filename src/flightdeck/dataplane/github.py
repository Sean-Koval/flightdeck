"""The `prs` table: the team repositories' closed pull requests from GitHub REST, for the weekly metrics hangar can't
give (the share of all merged PRs that are agent-authored, and reverts; docs/metrics.md). Runs after the compactor
with a read-only GitHub token (`GITHUB_TOKEN`, from Secret Manager on Cloud Run); it never calls hangar."""

from __future__ import annotations

import json
import os
import re
import urllib.request
from datetime import UTC, datetime, timedelta
from typing import Any

import fsspec
import typer

from flightdeck.dataplane.compact import write_partition

API = "https://api.github.com"
REVERTS = re.compile(r"\bReverts [\w.-]+/[\w.-]+#(\d+)|\bThis reverts commit ([0-9a-f]{7,40})")


def _get(path: str, token: str | None) -> Any:
    req = urllib.request.Request(API + path, headers={"Accept": "application/vnd.github+json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def _ts(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def pr_rows(repo: str, pulls: list[dict], since: datetime) -> list[dict]:
    """`prs` rows for the PRs closed since `since`; `reverts` resolved from GitHub's revert-button body
    (`Reverts o/r#N`), a `This reverts commit <sha>` line matching a merge commit, or a `Revert "<title>"` title."""
    by_sha = {p["merge_commit_sha"]: p["number"] for p in pulls if p.get("merge_commit_sha")}
    by_title = {p["title"]: p["number"] for p in pulls}
    rows = []
    for p in pulls:
        if not p.get("closed_at") or _ts(p["closed_at"]) < since:  # type: ignore[operator]
            continue
        m, title = REVERTS.search(p.get("body") or ""), p.get("title") or ""
        sha = m and m.group(2) and next((n for s, n in by_sha.items() if s.startswith(m.group(2))), None)
        quoted = by_title.get(title[8:-1]) if title.startswith('Revert "') and title.endswith('"') else None
        user = p.get("user") or {}
        rows.append({"run_id": None, "source": "github", "dt": p["closed_at"][:10], "repo": repo,
                     "number": p["number"], "url": p.get("html_url"), "title": title, "author": user.get("login"),
                     "author_bot": user.get("type") == "Bot", "created_at": _ts(p.get("created_at")),
                     "merged_at": _ts(p.get("merged_at")), "closed_at": _ts(p["closed_at"]),
                     "merge_sha": p.get("merge_commit_sha"),
                     "reverts": int(m.group(1)) if m and m.group(1) else sha or quoted})
    return rows


def fetch(repo: str, token: str | None, since: datetime) -> list[dict]:
    """Closed PRs updated since `since`, newest first, paged."""
    pulls: list[dict] = []
    for page in range(1, 100):
        batch = _get(f"/repos/{repo}/pulls?state=closed&sort=updated&direction=desc&per_page=100&page={page}", token)
        pulls += batch
        if len(batch) < 100 or (_ts(batch[-1]["updated_at"]) or since) < since:
            break
    return pulls


def prs(
    repos: str = typer.Option(..., "--repos", envvar="FLIGHTDECK_GITHUB_REPOS", help="Comma-separated owner/repo."),
    days: int = typer.Option(30, help="Rewrite the PRs closed in the last N days (revert detection looks back 14)."),
    out: str = typer.Option(..., "--out", envvar="FLIGHTDECK_DATA_URI", help="Data plane root."),
) -> None:
    """Fill the `prs` table from GitHub REST (token from GITHUB_TOKEN)."""
    since = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days)
    rows = [r for repo in repos.split(",") if repo.strip()
            for r in pr_rows(repo.strip(), fetch(repo.strip(), os.environ.get("GITHUB_TOKEN"), since), since)]
    fs, root = fsspec.core.url_to_fs(os.path.expanduser(out))
    for i in range(days + 1):
        day = (since + timedelta(days=i)).date().isoformat()
        write_partition(fs, root.rstrip("/"), "prs", day, [r for r in rows if r["dt"] == day])
    typer.echo(f"prs: {len(rows)} closed PRs since {since.date()} -> {out}")
