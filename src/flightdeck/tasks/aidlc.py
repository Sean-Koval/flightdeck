"""`flightdeck task import-aidlc`: ai-dlc evaluation suites as tasks, specs and a suite file (docs/tasks.md).

Each `Scenario` becomes a task directory: `goal` the instruction, `fixture.path` the environment's workspace (its
digest checked), the hidden fixture's `test_*.py` the grader's tests (ai-dlc's controller-side `hidden-tests`),
`answers` bounded replies under `[flightdeck.agent]`, `limits` the timeouts and turn cap. Every assertion maps to the
grader, a `flightdeck.spec/v1` spec or a `pending` spec, or the import fails: nothing is dropped silently. `arms`
become the suite's variants, and workflow specs judge only the treatment arm, as ai-dlc's planning did.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml

from flightdeck.ported.aidlc import contracts, planning
from flightdeck.specs.lang import SCHEMA
from flightdeck.tasks.format import load_task

BASE = "python@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de"  # ai-dlc's pinned base
PENDING = "pending: a person records it against the versioned rubric; a judge only after calibration (#27)"


def spec_for(sid: str, a: contracts.Assertion) -> tuple[dict[str, Any] | None, str]:
    """One assertion as a spec (None: the task's grader) and what it became, for the mapping table."""
    aw = {"task_id": sid, **({"variant": "treatment"} if a.dimension == "workflow" else {})}
    s: dict[str, Any] = {"schema": SCHEMA, "id": f"{sid}.{a.id}", "harness": "*", "scope": "job", "applies_when": aw,
                         "dimension": a.dimension, "mandatory": a.mandatory, "note": None}
    diff = lambda glob: {"any": {"paths": {"from": ["diff.files"]}, "match": glob}}  # noqa: E731
    if a.dimension == "quality":
        return {**s, "note": PENDING}, "pending spec (human review)"
    if a.kind == "hidden-tests":
        return None, "grader (tests/)"
    if a.kind == "commit-present":
        s["assert"] = diff(a.path) if a.path else {"eventually": {"event": "git.commit"}}
        return s, "spec: a delivered file matches the path" if a.path else "spec: a git.commit event"
    if a.kind == "path-committed":
        return {**s, "assert": diff(a.path)}, "spec: a delivered file matches the path (diff.files)"
    if a.kind == "ordering":
        s.update({"assert": {"before": {"first": {"path": a.before}, "then": {"path": a.after}}},
                  "note": "approximate: edit order of the two paths, not commit order (git.commit has no paths)"})
        return s, "spec: first edit of `before` precedes `after` (approximate)"
    if a.kind == "artifact-present" and a.expect:
        return {**s, "assert": {"any": {"paths": {"from": ["file.change", "diff.files"]}, "match": a.expect}}}, \
            "spec: a changed or delivered file matches"
    raise ValueError(f"{sid}.{a.id}: no flightdeck equivalent for kind {a.kind!r}" + (" without `expect`" if
                     a.kind == "artifact-present" else "") + "; map it by hand or drop it from the suite")


def _toml(v: Any) -> str:
    if isinstance(v, list):
        return "[" + ", ".join(map(_toml, v)) + "]"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{k} = {_toml(x)}" for k, x in v.items()) + "}"
    return json.dumps(v)  # strings, numbers and booleans read the same in TOML


def sources(sc: contracts.Scenario, base: Path) -> tuple[Path, list[Path]]:
    """The scenario's fixture (digest checked) and hidden tests, resolved beside the suite file."""
    fixture = (base / sc.fixture.path).resolve()
    if not fixture.is_dir() or planning.tree_digest(fixture) != sc.fixture.digest:
        raise ValueError(f"{sc.id}: fixture {fixture} is missing or does not match its digest")
    hidden = sorted((base / sc.fixture.hidden).resolve().glob("test_*.py")) if sc.fixture.hidden else []
    if any(a.kind == "hidden-tests" for a in sc.assertions) and not hidden:
        raise ValueError(f"{sc.id}: a hidden-tests assertion needs fixture.hidden with test_*.py files")
    return fixture, hidden


def write_task(sc: contracts.Scenario, fixture: Path, hidden: list[Path], d: Path, suite: str) -> None:
    work = f"/workspace/{sc.id}"
    shutil.copytree(fixture, d / "environment" / "workspace", ignore=shutil.ignore_patterns("__pycache__", ".git"))
    (d / "environment" / "Dockerfile").write_text(f"# Imported from ai-dlc suite {suite}, scenario {sc.id}.\n"
                                                  f"FROM {BASE}\nRUN apt-get update && apt-get install -y --no-"
                                                  "install-recommends git && rm -rf /var/lib/apt/lists/*\n"
                                                  f"COPY workspace/ {work}/\nWORKDIR {work}\n")
    (d / "tests").mkdir()
    (d / "tests" / "test.sh").write_bytes((files("flightdeck.tasks") / "aidlc_test.sh").read_bytes())
    for t in hidden:
        shutil.copy(t, d / "tests" / t.name)
    (d / "instruction.md").write_text(sc.goal.strip() + "\n")
    rows = [("schema_version", "1.4"), "[task]", ("name", f"aidlc/{sc.id}"), ("version", "1.0.0"),
            ("description", sc.goal[:200]), "[agent]", ("timeout_sec", sc.limits.timeout_minutes * 60.0),
            "[verifier]", ("timeout_sec", 600.0), ("network_mode", "no-network"), "[environment]", ("workdir", work),
            "[flightdeck]", ("tags", ["aidlc"]), ("sealed", False), ("environment", "bare"),
            ("max_turns", sc.limits.max_turns), ("imported_from", f"ai-dlc:{suite}/{sc.id}"), "[flightdeck.agent]",
            ("answers", [a.model_dump() for a in sc.answers]), "[flightdeck.grader]",
            ("command", "bash tests/test.sh"), ("files_digest", "")]
    text = "\n".join(r if isinstance(r, str) else f"{r[0]} = {_toml(r[1])}" for r in rows) + "\n"
    (d / "task.toml").write_text(text)
    (d / "task.toml").write_text(text.replace('files_digest = ""', f'files_digest = "{load_task(d).files_digest}"'))


def import_suite(path: Path, out: Path) -> list[tuple[str, str, str, str]]:
    """Write `<out>/<scenario>/` task dirs, `<out>/specs/<scenario>.yaml` and `<out>/suite.yaml`; return the mapping
    as (scenario, assertion, kind, maps to) rows. Refuses secrets, bad digests, one-armed scenarios and unmapped
    assertions before writing anything."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    planning.refuse_secrets(raw, "suite")
    suite = planning.validated(contracts.Suite, raw, "suite")
    planning.unique([s.id for s in suite.scenarios], "scenario identifier")
    plan = []
    for sc in suite.scenarios:
        planning.unique([a.id for a in sc.assertions], f"assertion identifier in {sc.id}")
        if set(sc.arms) != set(contracts.ARMS):
            raise ValueError(f"{sc.id}: both arms (treatment and baseline) must run, so the result can be compared")
        plan.append((sc, sources(sc, path.parent), [(a, *spec_for(sc.id, a)) for a in sc.assertions]))
    if out.exists() and any(out.iterdir()):
        raise ValueError(f"{out} exists and isn't empty")
    (out / "specs").mkdir(parents=True)
    mapping = []
    for sc, (fixture, hidden), mapped in plan:
        write_task(sc, fixture, hidden, out / sc.id, suite.id)
        specs = [s for _, s, _ in mapped if s]
        if specs:
            (out / "specs" / f"{sc.id}.yaml").write_text(yaml.safe_dump_all(specs, sort_keys=False))
        mapping += [(sc.id, a.id, a.kind, what) for a, _, what in mapped]
        mapping += [(sc.id, "(checkpoints)", ",".join(sc.checkpoints), "dropped: ai-dlc never observed them")] * bool(
            sc.checkpoints)
    spend = [s.limits.max_spend_usd for s in suite.scenarios if s.limits.max_spend_usd is not None]
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    (out / "suite.yaml").write_text(
        f"# Imported from ai-dlc suite {suite.id} ({path.name}, sha256 {digest}) by `flightdeck task import-aidlc`.\n"
        "# Arms are variants: give each the hangar overlay that makes it what ai-dlc meant (treatment: with ai-dlc,\n"
        "# e.g. its plugin in `skills`; baseline: without), and a concrete `model`. specs/ judges the workflow.\n"
        + yaml.safe_dump({"suite": f"aidlc-{suite.id}", "tasks": [s.id for s in suite.scenarios],
                          "environment": "bare", "n": 1, "variants": {a: {} for a in contracts.ARMS},
                          **({"trial_budget_usd": max(spend)} if spend else {})}, sort_keys=False))
    return mapping
