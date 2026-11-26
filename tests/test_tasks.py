"""Task directories (docs/tasks.md): layout, digests, Harbor compatibility, hangar mapping, the semver smoke task."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest
from typer.testing import CliRunner

from flightdeck.cli import app
from flightdeck.tasks.format import MAX_GRADER_FILES, TaskError, hangar_id, load_task, to_hangar, to_hangar_task

ROOT = Path(__file__).resolve().parent.parent
SEMVER = ROOT / "tasks" / "smoke" / "semver"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
HELLO = FIXTURES / "harbor" / "hello-world"
SPEC_SCHEMA = json.loads((FIXTURES / "hangar" / "experiment-spec.schema.json").read_text())
# Pinned: the digest must come out the same on every machine. Update it when the task itself changes.
SEMVER_DIGEST = "sha256:66ed96e6fed51f8740f81fcf949b616b912ebf0db5e29a1a00e004dfd722f5ef"


def _spec(tasks: list[dict]) -> dict:
    return {"name": "smoke", "environment": "bare", "tasks": tasks, "variants": {"control": {}}}


def _minimal(root: Path, toml: str = 'schema_version = "1.4"\n[task]\nname = "org/t1"\n') -> Path:
    (root / "tests").mkdir(parents=True)
    (root / "environment").mkdir()
    (root / "task.toml").write_text(toml)
    (root / "instruction.md").write_text("Do the thing.\n")
    (root / "tests" / "test.sh").write_text("echo 1 > /logs/verifier/reward.txt\n")
    (root / "environment" / "Dockerfile").write_text("FROM python:3.12-slim\n")
    return root


def test_semver_checks_and_its_digest_is_pinned() -> None:
    r = CliRunner().invoke(app, ["task", "check", str(SEMVER)])
    assert r.exit_code == 0, r.output
    task = load_task(SEMVER)
    assert task.id == "semver" and not task.sealed
    assert task.digest == SEMVER_DIGEST
    assert task.config["flightdeck"]["grader"]["files_digest"] == task.files_digest


def test_digest_ignores_newlines_formatting_and_files_order(tmp_path: Path) -> None:
    copy = tmp_path / "semver"
    shutil.copytree(SEMVER, copy)
    for p in [copy / "instruction.md", copy / "tests" / "test.sh", copy / "tests" / "hidden_test_semver.py"]:
        p.write_bytes(p.read_bytes().replace(b"\n", b"\r\n"))
    toml = copy / "task.toml"
    toml.write_text("# reformatted\n" + toml.read_text().replace(" = ", "="))
    (copy / "tests" / "__pycache__").mkdir()
    (copy / "tests" / "__pycache__" / "x.pyc").write_bytes(b"\0")
    assert load_task(copy).digest == SEMVER_DIGEST


def test_digest_changes_with_tests_and_files_digest_catches_it(tmp_path: Path) -> None:
    copy = tmp_path / "semver"
    shutil.copytree(SEMVER, copy)
    (copy / "tests" / "extra.py").write_text("x = 1\n")
    with pytest.raises(TaskError, match="tests/ changed"):
        load_task(copy)
    r = CliRunner().invoke(app, ["task", "digest", "--write", str(copy)])
    assert r.exit_code == 0, r.output
    assert load_task(copy).digest != SEMVER_DIGEST


def test_to_hangar_task_validates_against_hangars_experiment_spec() -> None:
    task = to_hangar_task(load_task(SEMVER))
    jsonschema.validate(_spec([task]), SPEC_SCHEMA)
    assert task["id"] == "semver" and task["instructions"].startswith("You are in an empty git repository.")
    grader = task["grader"]  # KAN-192: the task's own, its tests at the root of $HANGAR_HIDDEN_TESTS
    assert set(grader["files"]) == {"tests/test.sh", "tests/hidden_test_semver.py"}
    assert grader["command"] == 'cd "$HANGAR_HIDDEN_TESTS" && bash tests/test.sh'
    assert grader["timeout_seconds"] == 600 and "workspace" not in task


def test_grader_files_over_hangars_limit_are_refused(tmp_path: Path) -> None:
    root = _minimal(tmp_path / "big")
    (root / "tests" / "data.txt").write_text("x" * MAX_GRADER_FILES)
    with pytest.raises(TaskError, match=r"at most 1 MB \(MAX_GRADER_FILES"):
        to_hangar_task(load_task(root))


def test_a_harbor_registry_task_loads_unchanged() -> None:
    task = load_task(HELLO)
    assert task.id == "hello-world" and "hello.txt" in task.instruction and "test_state.py" in task.tests
    jsonschema.validate(_spec([to_hangar_task(task)]), SPEC_SCHEMA)


def test_a_legacy_harbor_task_without_a_task_section_loads(tmp_path: Path) -> None:
    legacy = 'version = "1.0"\n[metadata]\ncategory = "x"\n[verifier]\ntimeout_sec = 900.0\n'
    root = _minimal(tmp_path / "regex-log", legacy)
    task = load_task(root)
    assert task.id == "regex-log"
    assert to_hangar_task(task)["grader"]["timeout_seconds"] == 900


@pytest.mark.parametrize(
    ("toml", "match"),
    [
        ('[task]\ndescription = "no name"\n', "needs `name`"),
        ('[[steps]]\nname = "s1"\n', "multi-step"),
        ('[flightdeck.source]\nbase_sha = "abc"\n', "40-character"),
        ("[task\n", "task.toml"),
    ],
)
def test_bad_task_toml_is_refused(tmp_path: Path, toml: str, match: str) -> None:
    with pytest.raises(TaskError, match=match):
        load_task(_minimal(tmp_path / "t", toml))


def test_layout_errors(tmp_path: Path) -> None:
    root = _minimal(tmp_path / "t")
    (root / "tests" / "link.py").symlink_to(root / "instruction.md")
    with pytest.raises(TaskError, match="symlink"):
        load_task(root)
    (root / "tests" / "link.py").unlink()
    (root / "tests" / "test.sh").unlink()
    with pytest.raises(TaskError, match="test.sh is missing"):
        load_task(root)
    shutil.rmtree(root / "environment")
    (root / "tests" / "test.sh").write_text("true\n")
    with pytest.raises(TaskError, match="no environment"):
        load_task(root)


def test_each_task_has_its_own_grader_and_ids_fit_hangars_rule(tmp_path: Path) -> None:
    a = load_task(_minimal(tmp_path / "a"))
    b = load_task(_minimal(tmp_path / "b", '[task]\nname = "org/' + "x" * 60 + '"\n'))
    assert len(hangar_id(b)) <= 40 and hangar_id(b) == hangar_id(b)
    tasks = to_hangar([a, b])
    jsonschema.validate(_spec(tasks), SPEC_SCHEMA)
    assert [t["id"] for t in tasks] == ["t1", hangar_id(b)] and all(t["grader"]["files"] for t in tasks)
    with pytest.raises(TaskError, match="unique"):
        to_hangar([a, a])


def _own_command(root: Path, name: str, command: str | None) -> Path:
    toml = f'schema_version = "1.4"\n[task]\nname = "org/{name}"\n'
    _minimal(root, toml + (f"[flightdeck.grader]\ncommand = {json.dumps(command)}\n" if command else ""))
    (root / "tests" / "test.sh").write_text(f"echo {name} ran its test.sh\n")
    return root


def test_tasks_with_their_own_grader_commands_each_run_theirs(tmp_path: Path) -> None:
    """KAN-192: hangar takes a grader per task, so each task's command runs as written, quotes and all."""
    odd = "printf '%s\\n' \"c;; esac $HANGAR_TASK\"; exit 3"  # quotes, `;;` and `esac` run as written
    names = {"a": None, "b": "echo b ran make-free", "c": odd}  # a keeps the default
    tasks = to_hangar([load_task(_own_command(tmp_path / n, n, c)) for n, c in names.items()])
    jsonschema.validate(_spec(tasks), SPEC_SCHEMA)
    want = {"a": (0, "a ran its test.sh"), "b": (0, "b ran make-free"), "c": (3, "c;; esac c")}
    for t in tasks:
        hidden = tmp_path / "hidden" / t["id"]
        for rel, text in t["grader"]["files"].items():
            (hidden / rel).parent.mkdir(parents=True, exist_ok=True)
            (hidden / rel).write_text(text)
        r = subprocess.run(["bash", "-c", t["grader"]["command"]], capture_output=True, text=True, timeout=30,
                           env={**os.environ, "HANGAR_HIDDEN_TESTS": str(hidden), "HANGAR_TASK": t["id"]})
        assert (r.returncode, r.stdout.strip()) == want[t["id"]], r.stderr


def test_a_task_with_its_workspace_inside_and_no_repo_carries_it_to_hangar(tmp_path: Path) -> None:
    """KAN-192: environment/workspace/ goes as the task's `workspace`, which hangar commits in place of a repo."""
    csv = to_hangar_task(load_task(ROOT / "tasks" / "fixtures" / "csv-validator"))
    jsonschema.validate(_spec([csv]), SPEC_SCHEMA)
    assert "repo" not in csv and {"csvcheck/validate.py", "tests/test_validate.py"} <= set(csv["workspace"])
    root = _minimal(tmp_path / "w", 'schema_version = "1.4"\n[task]\nname = "org/w"\n'
                    '[flightdeck.source]\nrepo = "https://example.invalid/r.git"\nbase_sha = "' + "a" * 40 + '"\n')
    (root / "environment" / "workspace").mkdir()
    (root / "environment" / "workspace" / "a.py").write_text("x = 1\n")
    assert "workspace" not in to_hangar_task(load_task(root))  # a source repo wins: its files are the repo's
    (root / "environment" / "workspace" / "b.bin").write_bytes(b"\xff\xfe")
    (root / "task.toml").write_text('schema_version = "1.4"\n[task]\nname = "org/w"\n')
    with pytest.raises(TaskError, match="a file in environment/workspace/ is binary"):
        to_hangar_task(load_task(root))
    (root / "environment" / "workspace" / "b.bin").unlink()
    head = 'schema_version = "1.4"\n[task]\nname = "org/w"\n[flightdeck.source]\n'
    for extra in ('issue = "o/r#1"', 'base_branch = "main"', 'base_sha = "' + "a" * 40 + '"'):  # no repo, no pin
        (root / "task.toml").write_text(head + extra + "\n")
        with pytest.raises(TaskError, match="environment/workspace/ is its repo"):
            to_hangar_task(load_task(root))
    (root / "task.toml").write_text('schema_version = "1.4"\n[task]\nname = "org/w"\n')
    for bad in (".git/HEAD", "sub/Git~1/x", "cafe\u0301.txt"):  # a `git init` left inside, an NFD name
        (root / "environment" / "workspace" / bad).parent.mkdir(parents=True, exist_ok=True)
        (root / "environment" / "workspace" / bad).write_text("x\n")
        with pytest.raises(TaskError, match="hangar takes no .git"):
            to_hangar_task(load_task(root))
        (root / "environment" / "workspace" / bad).unlink()


def test_workspaces_over_hangars_16_mb_per_experiment_are_a_cap(tmp_path: Path) -> None:
    tasks = []
    for i in range(17):  # about 1 MB of workspace each
        root = _minimal(tmp_path / f"w{i}", f'schema_version = "1.4"\n[task]\nname = "org/w{i}"\n')
        (root / "environment" / "workspace").mkdir()
        (root / "environment" / "workspace" / "big.txt").write_text("x" * 1_000_000)
        tasks.append(load_task(root))
    assert len(to_hangar(tasks[:16])) == 16
    with pytest.raises(TaskError, match="16 MB per experiment"):
        to_hangar(tasks)


def _grade(work: Path, out: Path, **env: str) -> subprocess.CompletedProcess:
    path = os.path.dirname(sys.executable) + os.pathsep + os.environ.get("PATH", "")
    return subprocess.run(["bash", str(SEMVER / "tests" / "test.sh")], capture_output=True, text=True, timeout=600,
                          env={**os.environ, "PATH": path, "FLIGHTDECK_WORKDIR": str(work),
                               "FLIGHTDECK_REWARD_DIR": str(out), **env})


def test_semver_test_sh_rewards_the_reference_solution(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    shutil.copy(SEMVER / "solution" / "semver.py", work)
    (work / "conftest.py").write_text("raise SystemExit('a conftest in the agent tree must never load')\n")
    r = _grade(work, tmp_path / "out", HANGAR_GRADE_OUT=str(tmp_path / "grade.json"))
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads((tmp_path / "out" / "reward.json").read_text()) == {"reward": 1, "passed": 116, "total": 116}
    result = json.loads(r.stdout.split("RESULT ", 1)[1])
    assert result["by_category"]["cli"] == [3, 3]
    assert json.loads((tmp_path / "grade.json").read_text()) == result


def test_semver_test_sh_gives_zero_without_a_working_solution(tmp_path: Path) -> None:
    (tmp_path / "work").mkdir()
    r = _grade(tmp_path / "work", tmp_path / "out")
    assert r.returncode == 1
    assert json.loads((tmp_path / "out" / "reward.json").read_text())["reward"] == 0
    (tmp_path / "work" / "semver.py").write_text("raise SystemExit('broken')\n")
    assert _grade(tmp_path / "work", tmp_path / "out").returncode == 1


def test_task_new_writes_a_task_that_checks_and_grades(tmp_path: Path) -> None:
    root = tmp_path / "fix-retry"
    r = CliRunner().invoke(app, ["task", "new", str(root)])
    assert r.exit_code == 0, r.output
    assert load_task(root).config["task"]["name"] == "local/fix-retry"
    (tmp_path / "work").mkdir()
    path = os.path.dirname(sys.executable) + os.pathsep + os.environ.get("PATH", "")
    g = subprocess.run(["bash", str(root / "tests" / "test.sh")], capture_output=True, text=True, timeout=300,
                       env={**os.environ, "PATH": path, "FLIGHTDECK_WORKDIR": str(tmp_path / "work"),
                            "FLIGHTDECK_REWARD_DIR": str(tmp_path / "out")})
    assert g.returncode != 0  # the template's placeholder test fails until it is written
    assert json.loads((tmp_path / "out" / "reward.json").read_text())["reward"] == 0
    assert CliRunner().invoke(app, ["task", "new", str(root)]).exit_code != 0  # not over an existing task
