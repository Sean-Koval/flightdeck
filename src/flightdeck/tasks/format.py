"""Harbor-compatible task directories (docs/tasks.md): load and check one, digest it, map it onto hangar's experiment.

A task is a Harbor task directory (`task.toml`, `instruction.md`, `environment/`, hidden `tests/` with `test.sh`,
optional `solution/`). Flightdeck's own keys live under `[flightdeck]` in `task.toml`, which Harbor ignores, so a
flightdeck task runs on Harbor and a Harbor task loads here without changes.
"""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_GRADER_FILES = 1024 * 1024  # hangar experiments.MAX_GRADER_FILES: a grader's files, all together
MAX_GRADER_COUNT = 64  # hangar experiments.Grader.files: at most 64 files
MAX_INSTRUCTIONS = 64_000  # hangar experiments.Task.instructions
MAX_REFERENCE_PATCH = 1024 * 1024  # hangar experiments.MAX_REFERENCE_PATCH
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$")  # hangar experiments.NAME: task ids
SHA = re.compile(r"^[0-9a-f]{40}$")
SKIP = {"__pycache__", ".DS_Store", ".pytest_cache"}
DEFAULT_COMMAND = "bash tests/test.sh"


class TaskError(ValueError):
    """The directory isn't a valid task, or hangar would refuse it."""


@dataclass(frozen=True)
class Task:
    path: Path
    id: str
    config: dict[str, Any]  # task.toml as parsed
    instruction: str
    tests: dict[str, bytes]  # relative to tests/, newlines normalized
    environment: dict[str, bytes]
    digest: str  # task_digest: canonical task.toml + instruction + tests/* + environment/* (#24's cache key)
    files_digest: str  # tests/* alone: what the grader gets

    @property
    def flightdeck(self) -> dict[str, Any]:
        return self.config.get("flightdeck") or {}

    @property
    def sealed(self) -> bool:
        return bool(self.flightdeck.get("sealed"))

    @property
    def grader(self) -> dict[str, Any]:
        return self.flightdeck.get("grader") or {}


def _tree(root: Path, what: str) -> dict[str, bytes]:
    """Every file under root by relative POSIX path. Symlinks are refused; text files get LF newlines."""
    out: dict[str, bytes] = {}
    if not root.is_dir():
        return out
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        if SKIP & set(rel.split("/")) or p.suffix == ".pyc":
            continue
        if p.is_symlink():
            raise TaskError(f"{what}/{rel} is a symlink: tasks carry files, not links")
        if p.is_file():
            data = p.read_bytes()
            try:
                data = data.decode("utf-8").replace("\r\n", "\n").encode("utf-8")
            except UnicodeDecodeError:
                pass  # binary: hashed as is
            out[rel] = data
    return out


def _digest(parts: list[tuple[str, bytes]]) -> str:
    h = hashlib.sha256()
    for name, data in parts:
        h.update(f"{name}\0{len(data)}\0".encode() + data)
    return "sha256:" + h.hexdigest()


def canonical(config: dict[str, Any]) -> bytes:
    """task.toml's content, independent of formatting, comments and key order. `files_digest` is left out: it is
    derived from tests/, which the task digest covers anyway, and leaving it out lets it be written back."""
    cfg = json.loads(json.dumps(config, default=str))
    (cfg.get("flightdeck") or {}).get("grader", {}).pop("files_digest", None)
    return json.dumps(cfg, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def load_task(path: str | Path) -> Task:
    """Read and validate a task directory and compute its digests."""
    root = Path(path)
    if not (root / "task.toml").is_file():
        raise TaskError(f"{root}: no task.toml")
    try:
        config = tomllib.loads((root / "task.toml").read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise TaskError(f"{root}/task.toml: {e}") from None
    if config.get("steps"):
        raise TaskError(f"{root}: multi-step Harbor tasks ([[steps]]) aren't supported yet")
    info = config.get("task")
    if info is not None and not (isinstance(info, dict) and info.get("name")):
        raise TaskError(f"{root}/task.toml: [task] needs `name` (Harbor's org/name)")
    instr = root / "instruction.md"
    if not instr.is_file() or not instr.read_text(encoding="utf-8").strip():
        raise TaskError(f"{root}: instruction.md is missing or empty")
    if root.joinpath("tests").is_symlink() or root.joinpath("environment").is_symlink():
        raise TaskError(f"{root}: tests/ and environment/ must be directories, not symlinks")
    tests, env = _tree(root / "tests", "tests"), _tree(root / "environment", "environment")
    if "test.sh" not in tests:
        raise TaskError(f"{root}: tests/test.sh is missing (it writes the reward)")
    fd = config.get("flightdeck") or {}
    if not env and not fd.get("environment") and not (config.get("environment") or {}).get("docker_image"):
        raise TaskError(f"{root}: no environment/ directory, [environment] docker_image or [flightdeck] environment")
    sha = (fd.get("source") or {}).get("base_sha")
    if sha is not None and not SHA.match(str(sha)):
        raise TaskError(f"{root}/task.toml: [flightdeck.source] base_sha must be a full 40-character commit sha")
    instruction = instr.read_text(encoding="utf-8").replace("\r\n", "\n")
    files_digest = _digest([(k, v) for k, v in tests.items()])
    declared = (fd.get("grader") or {}).get("files_digest")
    if declared and declared != files_digest:
        raise TaskError(f"{root}: tests/ changed: files_digest is {declared}, the files hash to {files_digest} "
                        "(flightdeck task digest --write)")
    parts = [("task.toml", canonical(config)), ("instruction.md", instruction.encode())]
    parts += [(f"tests/{k}", v) for k, v in tests.items()] + [(f"environment/{k}", v) for k, v in env.items()]
    task_id = str(info["name"]).rsplit("/", 1)[-1] if info else root.resolve().name
    return Task(root, task_id, config, instruction, tests, env, _digest(parts), files_digest)


def hangar_id(task: Task) -> str:
    """The task's id within hangar's naming rule; a longer or odd id gets a stable short form."""
    if NAME.match(task.id):
        return task.id
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", task.id).strip("-._")[:31] or "task"
    return f"{stem}-{hashlib.sha256(task.id.encode()).hexdigest()[:8]}"


def to_hangar(tasks: list[Task]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """`hangar.experiment/v1` tasks and the one grader they share (hangar's experiment has a single grader).

    Each task's tests go to `<id>/tests/...` in `Grader.files`; the command runs the task's own command from
    `$HANGAR_HIDDEN_TESTS/<id>`, the task's pristine copy, chosen by `$HANGAR_TASK`."""
    out, files, commands, timeout = [], {}, set(), 30
    for t in tasks:
        hid, src = hangar_id(t), t.flightdeck.get("source") or {}
        if len(t.instruction) > MAX_INSTRUCTIONS:
            raise TaskError(f"task {t.id}: instruction.md is over hangar's {MAX_INSTRUCTIONS:,} characters")
        title = ((t.config.get("task") or {}).get("description") or t.id)[:200]
        item = {"id": hid, "instructions": t.instruction, "title": title,
                **{k: src[k] for k in ("repo", "base_sha", "base_branch", "issue", "verify") if src.get(k)}}
        ref = t.path / "solution" / "reference.patch"
        if ref.is_file():
            if ref.stat().st_size > MAX_REFERENCE_PATCH:
                raise TaskError(f"task {t.id}: solution/reference.patch is over hangar's 1 MB")
            item["reference_patch"] = ref.read_text(encoding="utf-8")
        out.append(item)
        for rel, data in t.tests.items():
            try:
                files[f"{hid}/tests/{rel}"] = data.decode("utf-8")
            except UnicodeDecodeError:
                raise TaskError(f"task {t.id}: tests/{rel} is binary; hangar's grader files are text") from None
        commands.add(t.grader.get("command") or DEFAULT_COMMAND)
        timeout = max(timeout, int((t.config.get("verifier") or {}).get("timeout_sec") or 600))
    if len(commands) > 1:
        raise TaskError(f"these tasks' grader commands differ ({sorted(commands)}); hangar runs one per experiment: "
                        "submit them as separate experiments")
    if len(files) > MAX_GRADER_COUNT:
        raise TaskError(f"the tests are {len(files)} files; hangar's grader takes at most {MAX_GRADER_COUNT}")
    size = sum(len(v.encode()) for v in files.values())
    if size > MAX_GRADER_FILES:
        raise TaskError(f"the tests total {size:,} bytes; hangar's grader takes at most 1 MB in all "
                        "(MAX_GRADER_FILES, hangar experiments.py)")
    command = f'cd "$HANGAR_HIDDEN_TESTS/$HANGAR_TASK" && {commands.pop() if commands else DEFAULT_COMMAND}'
    return out, {"command": command, "timeout_seconds": min(timeout, 3600), "files": files}


def to_hangar_task(task: Task) -> tuple[dict[str, Any], dict[str, Any]]:
    """One task as hangar's `Task` and `Grader` (experiments.py `Task{id, instructions, repo, base_sha, verify}`,
    `Grader{command, files}`)."""
    tasks, grader = to_hangar([task])
    return tasks[0], grader
