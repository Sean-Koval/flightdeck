"""The nightly spec runner: specs and accepted ADRs' `checks:` over a day's Parquet, change-point alerts on violation
rates, and the tightened/loosened/removed label for check edits (docs/behavior-specs.md 'ADR checks').

It needs no hangar endpoint: the data plane for traces and git for ADRs.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any

import duckdb
import yaml

from flightdeck.specs import lang
from flightdeck.stats.core import wilson

FRONT = re.compile(r"\A---\n(.*?)\n---\n", re.S)
FENCE = re.compile(r"```ya?ml\n(.*?)```", re.S)
LABELS = ("unchanged", "tightened", "loosened", "removed")  # in rising order of review needed


def parse_adr(text: str) -> tuple[str, list[dict]]:
    """An ADR's status (lower case) and its checks, from YAML frontmatter (ai-dlc#207) or `Status:` plus fenced YAML."""
    m = FRONT.match(text)
    meta = (yaml.safe_load(m.group(1)) if m else None) or {}
    line = re.search(r"^Status:\s*(\w+)", text, re.M)
    checks = list(meta.get("checks") or [])
    for block in FENCE.findall(text):
        d = yaml.safe_load(block)
        checks += d.get("checks") or [] if isinstance(d, dict) else []
    return str(meta.get("status") or (line.group(1) if line else "")).lower(), checks


def _files(source: str) -> list[tuple[str, str]]:
    """(name, text) of each `*.md` in `<git checkout>:<dir>` (its committed HEAD) or a plain directory."""
    repo, _, sub = source.rpartition(":")
    if not repo:
        return [(p.name, p.read_text()) for p in sorted(Path(sub).glob("*.md"))]
    git = lambda *a: subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True, check=True).stdout  # noqa: E731
    names = git("ls-tree", "--name-only", "HEAD", sub.rstrip("/") + "/").split()
    return [(Path(n).name, git("show", f"HEAD:{n}")) for n in names if n.endswith(".md")]


def adr_specs(source: str, accepted_only: bool = True) -> list[lang.Spec]:
    """Every check of the accepted ADRs under a source, as specs with `spec_source = adr:<repo>/<adr>`."""
    repo = Path(source.rpartition(":")[0] or source).resolve().name
    out = []
    for name, text in _files(source):
        status, checks = parse_adr(text)
        if accepted_only and status != "accepted":
            continue
        for c in checks:
            spec = {"schema": lang.SCHEMA, "harness": "*", **c, "spec_source": f"adr:{repo}/{Path(name).stem}"}
            lang.plan(spec)
            out.append(spec)
    return out


def run(con: duckdb.DuckDBPyConnection, specs: list[lang.Spec], dt: str) -> list[dict]:
    """`spec_results` rows for one day: every spec over that day's partition."""
    lang.prepare(con, dt)
    rows = []
    for scope, col in lang.SCOPES.items():
        mine = [s for s in specs if s.get("scope", "turn") == scope]
        if not mine:
            continue
        meta = {r[0]: r[1:] for r in con.execute(f"""select r.{col}, any_value(r.source), any_value(r.repo),
            any_value(coalesce(r.harness_digest, m.harness_digest)), any_value(m.knowledge_snapshot)
            from _runs r left join _manifests m on r.manifest_digest = m.digest where r.{col} is not null
            group by 1""").fetchall()}
        for s in mine:
            for unit, result in lang.evaluate_sql(s, con).items():
                src, repo, digest, snap = meta[unit]
                rows.append({"run_id": unit, "source": src, "dt": dt, "spec_id": s["id"], "result": result,
                             "spec_source": s.get("spec_source", "spec"), "scope": scope, "repo": repo,
                             "harness_digest": digest, "knowledge_snapshot": snap})
    return rows


def _ll(k: int, n: int) -> float:
    return sum(x * math.log(x / n) for x in (k, n - k) if x)


def alerts(rows: list[dict], examples: int = 5) -> list[dict]:
    """At most one alert per (check, repo): the split of the daily series into before/after that best explains the
    violation counts (binomial likelihood ratio), kept only when the violation rate rose and the two Wilson intervals
    do not overlap. It names the harness digests and knowledge snapshots first seen on the change day."""
    days: dict[tuple, dict[str, list]] = defaultdict(lambda: defaultdict(lambda: [0, 0, set(), []]))
    for r in rows:
        if r["result"] in (lang.PASS, lang.FAIL):
            d = days[(r["spec_source"], r["spec_id"], r.get("repo"))][str(r["dt"])]
            d[0] += r["result"] == lang.FAIL
            d[1] += 1
            d[2] |= {f"{k}={r[k]}" for k in ("harness_digest", "knowledge_snapshot") if r.get(k)}
            d[3] += [r["run_id"]] if r["result"] == lang.FAIL else []
    out = []
    for (src, sid, repo), series in sorted(days.items(), key=lambda kv: tuple(map(str, kv[0]))):
        ds = sorted(series)
        best = None
        for j in range(1, len(ds)):
            k1, n1 = (sum(series[d][i] for d in ds[:j]) for i in (0, 1))
            k2, n2 = (sum(series[d][i] for d in ds[j:]) for i in (0, 1))
            gain = _ll(k1, n1) + _ll(k2, n2) - _ll(k1 + k2, n1 + n2)
            if wilson(k2, n2)[0] > wilson(k1, n1)[1] and (best is None or gain > best[0]):
                best = (gain, j, k1 / n1, k2 / n2)
        if best:
            _, j, before, after = best
            seen = set().union(*(series[d][2] for d in ds[:j]))
            out.append({"check": sid, "spec_source": src, "repo": repo, "day": ds[j], "before": before, "after": after,
                        "changed": sorted(series[ds[j]][2] - seen),
                        "examples": [x for d in ds[j:] for x in series[d][3]][:examples]})
    return out


def file_alerts(found: list[dict], repo: str, gh: Any = subprocess.run) -> None:
    """Open or update one issue per check, labelled `flightdeck:violation`, through the operator's `gh` login."""
    api = lambda *a: gh(["gh", "api", *a], capture_output=True, text=True, check=True).stdout  # noqa: E731
    open_ = json.loads(api(f"repos/{repo}/issues?labels=flightdeck:violation&state=open&per_page=100") or "[]")
    for a in found:
        title = f"flightdeck: {a['check']} violations rose ({a['repo'] or 'all repos'})"
        body = (f"`{a['spec_source']}` `{a['check']}`: violation rate {a['before']:.0%} before {a['day']}, "
                f"{a['after']:.0%} from then.\n\nChanged that day: {', '.join(a['changed']) or 'nothing recorded'}.\n\n"
                f"Example runs: {', '.join(a['examples'])}")
        num = next((i["number"] for i in open_ if i["title"] == title), None)
        if num:
            api(f"repos/{repo}/issues/{num}/comments", "-f", f"body={body}")
        else:
            api(f"repos/{repo}/issues", "-f", f"title={title}", "-f", f"body={body}",
                "-f", "labels[]=flightdeck:violation")


def load_checks(path: Path) -> list[lang.Spec]:
    """Checks from a spec file or an ADR (any status), for `check diff`."""
    if not path.exists():
        return []
    if path.suffix == ".md":
        return [{"schema": lang.SCHEMA, **c} for c in parse_adr(path.read_text())[1]]
    return lang.load(path.read_text())


def diff(old: list[lang.Spec], new: list[lang.Spec]) -> dict[str, str]:
    """Per check id: removed, tightened (added), unchanged, or loosened. Any edit to an existing check counts as
    loosened: whether a new regex or window admits more is undecidable in general, so a second reviewer looks."""
    o, n = {s["id"]: s for s in old}, {s["id"]: s for s in new}
    return {k: "removed" if k not in n else "tightened" if k not in o else "unchanged" if o[k] == n[k] else "loosened"
            for k in sorted(o.keys() | n.keys())}
