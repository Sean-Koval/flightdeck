"""Mine regression-v1 (flightdeck#12, KAN-88) from the labelled first failures, once KAN-25 has labelled them.

usage (in the private data repository, ADR 0002; never in this one):
  python scripts/mine_regression.py validate labels/first-failures.yaml --data ~/plane
  python scripts/mine_regression.py mine labels/first-failures.yaml --data ~/plane --out . [--image IMG] [--repo n=path]

`labels/first-failures.yaml` is a list, one row per failed job the Friday review labelled (flightdeck#12):

  - job_id: j-123                      # required; must be a job in the data plane's runs
    repo: OWNER/NAME                   # else runs.repo
    labelled_by: sean
    labelled_at: 2026-11-21
    first_failure_seq: 14              # required: hangar.seq of the first failing step
    category: scope-creep              # required: hangar 0007 section 5.5's taxonomy (TAXONOMY below)
    note: "..."
    fixed_by_pr: OWNER/NAME#45         # the human fix; without it the job is recorded as needs-tests
    fix_sha: <40 hex>                  # optional: the fix's merge commit, else resolved on GitHub (GITHUB_TOKEN)
    base_sha: <40 hex>                 # optional: else runs.base_sha
    instruction: "..."                 # the job's task text, as hangar fenced it; without it: needs-instruction

`mine` turns each row into a task directory under `<out>/tasks/regression-v1/`: the job's base commit as
[flightdeck.source], the instruction, and the test files the fix added or changed as the hidden tests. It checks
fail-to-pass `--runs` times (3): every run fails on the base and passes on the fix, else the row is unminable (a
varying outcome is flaky). With `--image`, the checks run in that image with no network (`docker run --network none`);
without it they run on this machine, which is for fixtures and CI only. Rows that can't be mined are recorded with
the reason. `<out>/suites/regression-v1.lock.json` records every task's digests and every reason.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from flightdeck.tasks.format import TaskError, load_task, to_hangar_task, write_digest

TAXONOMY = {"stuck-loop", "oracle-fixation", "scope-creep", "test-gaming", "premature-done", "unsafe-action",
            "dependency-fight", "env-fix", "other"}
REQUIRED = ("job_id", "first_failure_seq", "category")
SHA = re.compile(r"[0-9a-f]{40}")
PR = re.compile(r"([\w.-]+)/([\w.-]+)#(\d+)")
SUITE, WANT, MIN_MINED = "regression-v1", 20, 12
HIDDEN = re.compile(r"(^|/)tests/(.*/)?(test_[^/]*\.py|conftest\.py)$")

GRADER = r"""#!/bin/bash
# regression-v1 grader (flightdeck scripts/mine_regression.py, after team-harness's regression-v0 grader): run the
# fix's test files in this directory against the agent's tree, from a pristine copy.
#   the agent's tree   $FLIGHTDECK_WORKDIR, else $HANGAR_REPO (hangar's grader), else the current directory (Harbor)
#   the reward         $FLIGHTDECK_REWARD_DIR/reward.json, else /logs/verifier/reward.json; also $HANGAR_GRADE_OUT
# The image must already have the repository's dependencies and pytest: hangar's grader has no network.
set -u
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
WORK=${FLIGHTDECK_WORKDIR:-${HANGAR_REPO:-$PWD}}
OUT=${FLIGHTDECK_REWARD_DIR:-/logs/verifier}
G=$(mktemp -d "${TMPDIR:-/tmp}/grade.XXXXXX")
trap 'rm -rf "$G"' EXIT
mkdir -p "$OUT" 2>/dev/null && [ -w "$OUT" ] || OUT=$G/reward
mkdir -p "$OUT" "$G/hidden"
cp "$HERE"/*.py "$G/hidden/"
cp -R "$WORK" "$G/work" && rm -rf "$G/work/.git"
mkdir -p "$G/work/tests"
find "$G/work/tests" -name conftest.py -delete
cp "$G/hidden/"*.py "$G/work/tests/"
cd "$G/work" || exit 2
unset PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTEST_ADDOPTS PYTEST_PLUGINS
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 GRADE_WORK="$G/work"
tests=$(cd "$G/hidden" && ls test_*.py | sed "s|^|tests/|")
# shellcheck disable=SC2086
timeout 600 python3 -I -m pytest -p no:cacheprovider -c /dev/null --rootdir "$G/work" --confcutdir "$G/work/tests" \
  -o addopts= -o "pythonpath=$G/work/src $G/work" -q -W ignore::pytest.PytestConfigWarning $tests
code=$?
reward=0; [ "$code" -eq 0 ] && reward=1
echo "{\"reward\": $reward, \"exit_code\": $code}" > "$OUT/reward.json"
[ -n "${HANGAR_GRADE_OUT:-}" ] && cp "$OUT/reward.json" "$HANGAR_GRADE_OUT"
exit "$code"
"""

TOML = """# regression-v1 (flightdeck#12): mined by scripts/mine_regression.py from job {job_id}, labelled {category}
# at seq {seq}. Harbor task.toml schema 1.4, flightdeck's keys under [flightdeck] (docs/tasks.md).
schema_version = "1.4"

[task]
name = "regression-v1/{id}"
version = "1.0.0"
description = {desc}
keywords = ["regression-v1", {category_q}]

[metadata]

[agent]
timeout_sec = 1800.0

[verifier]
timeout_sec = 900.0
network_mode = "no-network"

[environment]
build_timeout_sec = 900.0

[flightdeck]
tags = ["regression-v1", {category_q}]
sealed = false
environment = {environment}
mined_after = {mined_after}
mined_from = {job_q}
category = {category_q}
first_failure_seq = {seq}

[flightdeck.source]
repo = {repo_url}
base_sha = "{base}"{issue}

[flightdeck.grader]
command = "bash tests/test.sh"
files_digest = ""
"""

DOCKERFILE = """# The local runner's environment (flightdeck docs/local.md): the repository at the job's base commit.
# Install its dependencies and pytest here: the grader has no network.
# hangar trials use the variant's environment instead.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
RUN git clone {repo_url} /workspace && git -C /workspace checkout -q --detach {base}
WORKDIR /workspace
"""

SOLVE = """#!/bin/bash
# Harbor's oracle: the human fix (without its hidden tests), applied in the working directory.
set -eu
git apply --whitespace=nowarn "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/reference.patch"
"""


def q(s: Any) -> str:
    return json.dumps(str(s))


def git(cwd: Path, *args: str, check: bool = True) -> str:
    r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout if r.returncode == 0 else ""


# ---------------------------------------------------------------------------------------------------- labels
def load_labels(path: Path) -> list[dict[str, Any]]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    if not isinstance(doc, list) or not all(isinstance(r, dict) for r in doc):
        raise ValueError(f"{path}: a list of label rows, one per failed job")
    return doc


def jobs(data: str | None) -> dict[str, dict[str, Any]]:
    """Each job's repo, base commit, environment and when it started, from the data plane's runs and manifests."""
    if not data:
        return {}
    from flightdeck.dataplane.duck import connect

    con = connect(os.path.expanduser(data))
    rows = con.sql("""select r.job_id, any_value(coalesce(r.repo, m.repo_url)), any_value(coalesce(r.base_sha,
                      m.base_sha)), any_value(r.environment), min(r.started_at) from runs r left join manifests m
                      on m.digest = r.manifest_digest where r.job_id is not null group by 1""").fetchall()
    return {j: {"repo": repo, "base_sha": base, "environment": env, "started_at": started}
            for j, repo, base, env, started in rows}


def validate(labels: list[dict[str, Any]], known: dict[str, dict[str, Any]] | None) -> list[str]:
    """Why the labelled set isn't ready to mine (empty: it is)."""
    problems, seen = [], set()
    for i, r in enumerate(labels, 1):
        at = f"row {i} ({r.get('job_id', '?')})"
        problems += [f"{at}: {k} is missing" for k in REQUIRED if r.get(k) in (None, "")]
        if r.get("category") not in TAXONOMY | {None, ""}:
            problems.append(f"{at}: category {r['category']!r} is not one of {', '.join(sorted(TAXONOMY))}")
        if r.get("first_failure_seq") not in (None, "") and not (isinstance(r["first_failure_seq"], int)
                                                                and r["first_failure_seq"] >= 0):
            problems.append(f"{at}: first_failure_seq must be a non-negative integer (hangar.seq)")
        if r.get("job_id") in seen:
            problems.append(f"{at}: job {r['job_id']} is labelled twice")
        seen.add(r.get("job_id"))
        if known is not None and r.get("job_id") and r["job_id"] not in known:
            problems.append(f"{at}: no job {r['job_id']} in the data plane's runs")
        for k in ("fix_sha", "base_sha"):
            if r.get(k) and not SHA.fullmatch(str(r[k])):
                problems.append(f"{at}: {k} must be a full 40-character commit sha")
        if r.get("fixed_by_pr") and not PR.fullmatch(str(r["fixed_by_pr"])):
            problems.append(f"{at}: fixed_by_pr must be OWNER/NAME#N")
    if len(labels) < WANT:
        problems.append(f"{len(labels)} labelled failures; flightdeck#12 needs {WANT} (KAN-25)")
    return problems


# ---------------------------------------------------------------------------------------------------- mining
def repo_source(repo: str, mapping: dict[str, str]) -> tuple[str, str]:
    """(where to clone from, the URL a task records) for a runs.repo value: OWNER/NAME, a URL or a mapped name."""
    name = repo.rstrip("/").removesuffix(".git").split("/")[-1]
    url = repo if "://" in repo or repo.startswith("git@") else f"https://github.com/{repo.removesuffix('.git')}.git"
    return mapping.get(repo) or mapping.get(name) or url, url


def merge_sha(pr: str) -> str | None:
    """The merge commit of OWNER/NAME#N on GitHub, or None when it isn't merged or can't be read."""
    m = PR.fullmatch(pr)
    if not m:
        return None
    api = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    req = urllib.request.Request(f"{api}/repos/{m[1]}/{m[2]}/pulls/{m[3]}", headers={"Accept": "application/json"})
    if token := os.environ.get("GITHUB_TOKEN"):
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            doc = json.load(resp)
    except (OSError, ValueError):
        return None
    return doc.get("merge_commit_sha") if doc.get("merged") else None


def checkout(src: str, cache: Path) -> Path:
    d = cache / re.sub(r"[^\w.-]", "_", src)
    if not (d / ".git").exists():
        cache.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(["git", "clone", "-q", src, str(d)], capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError(f"can't clone {src}: {r.stderr.strip()}")
    return d


def grade(task: Path, tree: Path, image: str | None) -> int:
    """test.sh's exit code on a tree; in `image` with no network when given."""
    with tempfile.TemporaryDirectory() as out:
        env = {"FLIGHTDECK_WORKDIR": str(tree), "FLIGHTDECK_REWARD_DIR": out}
        if image:
            cmd = ["docker", "run", "--rm", "--network", "none", "-v", f"{tree}:{tree}:ro", "-v", f"{task}:{task}:ro",
                   "-v", f"{out}:{out}", *[a for k, v in env.items() for a in ("-e", f"{k}={v}")], image,
                   "bash", f"{task}/tests/test.sh"]
            return subprocess.run(cmd, capture_output=True).returncode
        clean = {k: v for k, v in os.environ.items() if not k.startswith(("GITHUB_", "HANGAR_", "ANTHROPIC_"))}
        return subprocess.run(["bash", str(task / "tests" / "test.sh")], env=clean | env, capture_output=True,
                              cwd=tree).returncode


def fail_to_pass(task: Path, repo: Path, base: str, fix: str, runs: int, image: str | None) -> str | None:
    """None when every run fails on the base and passes on the fix; else why not."""
    with tempfile.TemporaryDirectory() as tmp:
        trees = {}
        for name, sha in (("base", base), ("fix", fix)):
            trees[name] = Path(tmp) / name
            git(repo, "worktree", "add", "-q", "--detach", str(trees[name]), sha)
        try:
            got = {k: [grade(task, t, image) == 0 for _ in range(runs)] for k, t in trees.items()}
        finally:
            for t in trees.values():
                git(repo, "worktree", "remove", "--force", str(t), check=False)
    if len(set(got["base"])) > 1 or len(set(got["fix"])) > 1:
        return f"flaky: base passed {sum(got['base'])}/{runs}, fix passed {sum(got['fix'])}/{runs}"
    if got["base"][0]:
        return "the fix's tests already pass on the base"
    if not got["fix"][0]:
        return "the fix's tests fail on the fix"
    return None


def mine_one(row: dict[str, Any], job: dict[str, Any], out: Path, cache: Path, mapping: dict[str, str], runs: int,
             image: str | None) -> tuple[str | None, str | None]:
    """(task id, None) when mined, else (None, the reason it couldn't be)."""
    if not row.get("instruction"):
        return None, "needs-instruction: the row has no instruction (the job's task text)"
    if not row.get("fixed_by_pr") and not row.get("fix_sha"):
        return None, "needs-tests: no fixed_by_pr (a reviewer-written test can replace it; flightdeck#12)"
    repo_name, base = row.get("repo") or job.get("repo"), row.get("base_sha") or job.get("base_sha")
    if not repo_name or not base:
        return None, "the job has no repo or base_sha in runs, and the row names none"
    src, url = repo_source(str(repo_name), mapping)
    try:
        repo = checkout(src, cache)
    except RuntimeError as e:
        return None, str(e)
    fix = row.get("fix_sha") or merge_sha(str(row["fixed_by_pr"]))
    if not fix:
        return None, f"{row['fixed_by_pr']}: not merged, or its merge commit can't be read (set fix_sha)"
    has = lambda sha: subprocess.run(["git", "-C", str(repo), "cat-file", "-e", f"{sha}^{{commit}}"],  # noqa: E731
                                     capture_output=True).returncode == 0
    for sha, what in ((base, "base_sha"), (fix, "fix")):
        if not has(sha):
            git(repo, "fetch", "-q", "origin", sha, check=False)
            if not has(sha):
                return None, f"{what} {sha[:12]} is not in {src} (force-pushed away?)"
    changed = git(repo, "diff", "--name-only", "--diff-filter=AM", base, fix).split()
    hidden = [f for f in changed if HIDDEN.search(f)]
    if not any(Path(f).name.startswith("test_") for f in hidden):
        return None, "the fix adds or changes no tests/**/test_*.py"
    if len({Path(f).name for f in hidden}) < len(hidden):
        return None, "two hidden test files share a name; the grader flattens them into tests/"
    tid = re.sub(r"[^a-z0-9-]+", "-", f"{Path(url).stem}-{row['job_id']}".lower()).strip("-")[:60]
    d = out / "tasks" / SUITE / tid
    if d.exists():
        shutil.rmtree(d)
    for sub in ("tests", "environment", "solution"):
        (d / sub).mkdir(parents=True)
    for f in hidden:
        (d / "tests" / Path(f).name).write_text(git(repo, "show", f"{fix}:{f}"), encoding="utf-8")
    (d / "tests" / "test.sh").write_text(GRADER, encoding="utf-8")
    (d / "instruction.md").write_text(str(row["instruction"]).strip() + "\n", encoding="utf-8")
    (d / "environment" / "Dockerfile").write_text(DOCKERFILE.format(repo_url=url, base=base), encoding="utf-8")
    patch = git(repo, "diff", "--binary", base, fix, "--", ".", *[f":(exclude){f}" for f in hidden])
    (d / "solution" / "reference.patch").write_text(patch, encoding="utf-8")
    (d / "solution" / "solve.sh").write_text(SOLVE, encoding="utf-8")
    merged = git(repo, "show", "-s", "--format=%cs", fix).strip() or date.today().isoformat()
    issue = f"\nissue = {q(row['fixed_by_pr'])}" if row.get("fixed_by_pr") else ""
    (d / "task.toml").write_text(TOML.format(
        id=tid, job_id=row["job_id"], job_q=q(row["job_id"]), category=row["category"], category_q=q(row["category"]),
        seq=int(row["first_failure_seq"]), desc=q(str(row["instruction"]).strip().splitlines()[0][:200]),
        environment=q(job.get("environment") or "bare"), mined_after=q(merged), repo_url=q(url), base=base,
        issue=issue), encoding="utf-8")
    write_digest(d)
    try:
        to_hangar_task(load_task(d))
    except TaskError as e:
        shutil.rmtree(d)
        return None, f"task check: {e}"
    if why := fail_to_pass(d, repo, base, fix, runs, image):
        shutil.rmtree(d)
        return None, why
    return tid, None


def mine(labels: list[dict[str, Any]], known: dict[str, dict[str, Any]], out: Path, mapping: dict[str, str],
         runs: int = 3, image: str | None = None, cache: Path | None = None) -> dict[str, Any]:
    """Mine every row; write and return the lock: each task's digests, and each unmined job's reason."""
    tasks, unmined = {}, []
    with tempfile.TemporaryDirectory() as tmp:
        for row in labels:
            tid, why = mine_one(row, known.get(row["job_id"], {}), out, cache or Path(tmp), mapping, runs, image)
            if tid:
                t = load_task(out / "tasks" / SUITE / tid)
                tasks[tid] = {"digest": t.digest, "files_digest": t.files_digest, "job_id": row["job_id"],
                              "category": row["category"], "first_failure_seq": row["first_failure_seq"],
                              "fixed_by_pr": row.get("fixed_by_pr")}
            else:
                unmined.append({"job_id": row["job_id"], "category": row.get("category"), "reason": why})
    lock = {"suite": SUITE, "mined_at": date.today().isoformat(), "fail_to_pass_runs": runs,
            "checked_in": image or "host", "tasks": tasks, "unmined": unmined}
    (out / "suites").mkdir(parents=True, exist_ok=True)
    (out / "suites" / f"{SUITE}.lock.json").write_text(json.dumps(lock, indent=1) + "\n", encoding="utf-8")
    return lock


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["validate", "mine"])
    ap.add_argument("labels", type=Path, help="labels/first-failures.yaml")
    ap.add_argument("--data", default=os.environ.get("FLIGHTDECK_DATA_URI"), help="Data plane directory.")
    ap.add_argument("--out", type=Path, default=Path("."), help="The private data repository's root.")
    ap.add_argument("--image", help="Run fail-to-pass checks in this image, with no network.")
    ap.add_argument("--runs", type=int, default=3, help="Fail-to-pass runs on each side (flaky tests are dropped).")
    ap.add_argument("--repo", action="append", default=[], help="NAME=PATH_OR_URL: clone NAME from here instead.")
    ap.add_argument("--cache", type=Path, help="Keep clones here between runs.")
    a = ap.parse_args(argv)
    labels, known = load_labels(a.labels), jobs(a.data)
    problems = validate(labels, known if a.data else None)
    for p in problems:
        print(f"label: {p}")
    if a.command == "validate":
        print(f"{len(labels)} labelled failures, {len(problems)} problem(s)" + ("" if a.data else
              "; pass --data to check the jobs exist"))
        return 1 if problems else 0
    if not a.data:
        ap.error("mine needs --data: each job's repo and base commit come from the data plane")
    if [p for p in problems if not p.endswith("(KAN-25)")]:
        return 1
    mapping = dict(m.split("=", 1) for m in a.repo)
    lock = mine(labels, known, a.out, mapping, a.runs, a.image, a.cache)
    for u in lock["unmined"]:
        print(f"unmined  {u['job_id']}: {u['reason']}")
    for tid in lock["tasks"]:
        print(f"mined    {tid}")
    n = len(lock["tasks"])
    print(f"{n} of {len(labels)} mined into {a.out / 'tasks' / SUITE}; lock {a.out / 'suites' / (SUITE + '.lock.json')}"
          + ("" if n >= MIN_MINED else f"; flightdeck#12 needs at least {MIN_MINED}") + "; " +
          ("checked in " + shlex.quote(a.image) if a.image else "checked on this machine (fixtures and CI only)"))
    return 0 if n >= MIN_MINED else 1


if __name__ == "__main__":
    sys.exit(main())
