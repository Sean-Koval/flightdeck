"""ai-dlc's evaluation contracts, ported (#17), and `flightdeck task import-aidlc` (docs/tasks.md)."""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from flightdeck.cli import app
from flightdeck.ported.aidlc import contracts
from flightdeck.runners.hangar import load_plan
from flightdeck.specs import lang
from flightdeck.tasks.aidlc import import_suite
from flightdeck.tasks.format import load_task

ROOT = Path(__file__).resolve().parent.parent
SUITES = ROOT / "tests" / "fixtures" / "aidlc" / "suites"
CSV = ROOT / "tasks" / "fixtures" / "csv-validator"


def test_published_schemas_match_the_models() -> None:
    """ai-dlc's test, ported: schemas/aidlc/ are the models' JSON Schemas."""
    for name, model in contracts.SCHEMAS.items():
        assert json.loads((ROOT / "schemas" / "aidlc" / f"{name}.schema.json").read_text()) == model.model_json_schema()


@pytest.mark.parametrize(("fields", "ok"), [
    ({"kind": "commit-present", "path": "a"}, True), ({"kind": "commit-present", "before": "a"}, False),
    ({"kind": "path-committed"}, False), ({"kind": "path-committed", "path": "a", "after": "b"}, False),
    ({"kind": "ordering", "before": "a", "after": "b"}, True), ({"kind": "ordering", "before": "a"}, False),
])
def test_git_assertion_selectors(fields: dict, ok: bool) -> None:
    raw = {"id": "x", "dimension": "workflow", **fields}
    if ok:
        contracts.Assertion.model_validate(raw)
    else:
        with pytest.raises(ValueError):
            contracts.Assertion.model_validate(raw)


def _suite(tmp: Path, name: str = "real-client", **change) -> Path:
    raw = json.loads((SUITES / f"{name}.json").read_text())
    raw["scenarios"][0].update(change)
    p = SUITES / f".tmp-{tmp.name}.json"  # beside the originals, so their relative fixture paths resolve
    p.write_text(json.dumps(raw))
    return p


@pytest.fixture
def suite_file(tmp_path: Path):
    made: list[Path] = []

    def make(**kw) -> Path:
        made.append(_suite(tmp_path, **kw))
        return made[-1]

    yield make
    for p in made:
        p.unlink()


def test_both_ai_dlc_suites_import_with_every_assertion_mapped(tmp_path: Path) -> None:
    for name in ("smoke", "real-client"):
        out = tmp_path / name
        rows = import_suite(SUITES / f"{name}.json", out)
        raw = json.loads((SUITES / f"{name}.json").read_text())
        assert [(r[0], r[1]) for r in rows] == [(s["id"], a["id"]) for s in raw["scenarios"] for a in s["assertions"]]
        task = load_task(out / "csv-duplicate-rows")  # validates layout and files_digest
        assert task.id == "csv-duplicate-rows" and task.instruction.strip() == raw["scenarios"][0]["goal"]
        assert task.tests["test_acceptance.py"] == (CSV / "tests" / "test_acceptance.py").read_bytes()
        assert task.flightdeck["agent"]["answers"] == raw["scenarios"][0]["answers"]
        assert task.config["agent"]["timeout_sec"] == 1800 and task.flightdeck["max_turns"] == 20
        specs = lang.load((out / "specs" / "csv-duplicate-rows.yaml").read_text())
        assert {s["id"].split(".")[1] for s in specs} == {r[1] for r in rows if r[3] != "grader (tests/)"}
        assert all(s["applies_when"].get("variant") == "treatment" for s in specs if s["dimension"] == "workflow")
        quality = [s for s in specs if s["dimension"] == "quality"]
        assert quality and all("assert" not in s and s["note"].startswith("pending") for s in quality)
        plan = load_plan(out / "suite.yaml")
        assert set(plan.variants) == {"treatment", "baseline"} and [t.id for t in plan.tasks] == [task.id]


def test_imported_grader_passes_the_reference_and_fails_the_fixture(tmp_path: Path) -> None:
    import_suite(SUITES / "smoke.json", tmp_path / "out")
    task = tmp_path / "out" / "csv-duplicate-rows"
    for name, want in (("fixture", 0), ("reference", 1)):
        work = tmp_path / name
        shutil.copytree(task / "environment" / "workspace", work)
        if name == "reference":
            shutil.copy(CSV / "solution" / "validate.py", work / "csvcheck" / "validate.py")
        reward = tmp_path / f"reward-{name}"
        done = subprocess.run(["bash", str(task / "tests" / "test.sh")], capture_output=True, text=True,
                              env={"PATH": "/usr/bin:/bin", "FLIGHTDECK_WORKDIR": str(work),
                                   "FLIGHTDECK_REWARD_DIR": str(reward)})
        assert json.loads((reward / "reward.json").read_text())["reward"] == want, done.stdout[-2000:]
        assert (done.returncode == 0) == bool(want)


def test_workflow_specs_judge_only_the_treatment_arm_of_their_task(tmp_path: Path) -> None:
    import_suite(SUITES / "real-client.json", tmp_path / "out")
    specs = {s["id"].split(".")[1]: s for s in lang.load((tmp_path / "out/specs/csv-duplicate-rows.yaml").read_text())}
    run = {"source": "local", "dt": "2026-10-17", "task_id": "csv-duplicate-rows"}
    tables = {"runs": [{**run, "run_id": "t", "job_id": "t", "variant": "treatment",
                        "diff_files": [".ai-dlc/work/x.toml", "csvcheck/validate.py"]},
                       {**run, "run_id": "b", "job_id": "b", "variant": "baseline", "diff_files": ["README.md"]},
                       {**run, "run_id": "o", "job_id": "o", "variant": "treatment", "task_id": "other"}],
              "spans": [{"run_id": "t", "source": "local", "dt": "2026-10-17", "trace_id": "x", "span_id": "s",
                         "kind": "job", "job_id": "t", "start_ns": 0, "end_ns": 2}],
              "events": [{"run_id": "t", "source": "local", "dt": "2026-10-17", "trace_id": "x", "name": "git.commit",
                          "seq": 1, "time_ns": 1}]}
    con = lang.connect_tables(tables)
    for sid, want in (("process-commit", "pass"), ("work-record-committed", "pass"),
                      ("implementation-committed", "pass"), ("work-before-code", "not_applicable"),
                      ("handoff-rubric", "unknown")):
        res = lang.evaluate(specs[sid], tables)
        assert res == lang.evaluate_sql(specs[sid], con), sid
        baseline = "unknown" if sid == "handoff-rubric" else "not_applicable"  # quality judges both arms
        assert res == {"t": want, "b": baseline, "o": "not_applicable"}, sid


@pytest.mark.parametrize(("change", "message"), [
    ({"goal": "Push with ghp_" + "A" * 36}, "goal"),
    ({"api_token": "x"}, "api_token"),
    ({"arms": ["treatment"]}, "both arms"),
    ({"fixture": {"path": "../../../../tasks/fixtures/csv-validator/environment/workspace", "digest": "0" * 64}},
     "digest"),
    ({"assertions": [{"id": "a", "dimension": "workflow", "kind": "telepathy"}]}, "telepathy"),
    ({"assertions": [{"id": "a", "dimension": "workflow", "kind": "artifact-present"}]}, "expect"),
    ({"assertions": [{"id": "a", "dimension": "correctness", "kind": "hidden-tests"}] * 2}, "Duplicate"),
])
def test_refusals_name_the_field_never_the_secret(tmp_path: Path, suite_file, change: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message) as e:
        import_suite(suite_file(**copy.deepcopy(change)), tmp_path / "out")
    assert "ghp_" not in str(e.value)
    assert not (tmp_path / "out").exists()  # refused before writing anything


def test_cli_prints_the_mapping(tmp_path: Path) -> None:
    res = CliRunner().invoke(app, ["task", "import-aidlc", str(SUITES / "real-client.json"), "--out",
                                   str(tmp_path / "o")])
    assert res.exit_code == 0, res.output
    assert "| csv-duplicate-rows | work-before-code | ordering | spec: first edit" in res.output
    again = CliRunner().invoke(app, ["task", "import-aidlc", str(SUITES / "smoke.json"), "--out", str(tmp_path / "o")])
    assert again.exit_code == 1 and "isn't empty" in again.output
