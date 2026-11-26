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
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_GRADER_FILES = MAX_REFERENCE_PATCH = 1024 * 1024  # hangar experiments: a grader's files, all together; a patch
MAX_GRADER_COUNT, MAX_WORKSPACE_FILES = 64, 500  # hangar Grader.files; MAX_WORKSPACE_FILES (1 MB, as a grader's)
MAX_INSTRUCTIONS, MAX_COMMAND = 64_000, 4000  # hangar Task.instructions, Grader.command
GITDIR = re.compile(r"(^|/)(\.git|git~\d+)[. ]*(/|$)|[\x00-\x1f\x7f]", re.I)  # hangar workspaces.path_error
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$")  # hangar experiments.NAME: task ids
SHA = re.compile(r"^[0-9a-f]{40}$")
SKIP = {"__pycache__", ".DS_Store", ".pytest_cache"}
DEFAULT_COMMAND = "bash tests/test.sh"
DIGEST_LINE = re.compile(r'^(files_digest\s*=\s*)"[^"]*"', re.M)


class TaskError(ValueError):
    """The directory isn't a valid task, or hangar would refuse it."""


class CapError(TaskError):
    """Over one of hangar's caps on an experiment's grader: its files, their bytes or its command."""


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


def write_digest(path: str | Path) -> str:
    """Recompute tests/' files_digest, whatever the old value was, and write it into task.toml; returns it."""
    toml = Path(path) / "task.toml"
    text = toml.read_text(encoding="utf-8")
    if not DIGEST_LINE.search(text):
        raise TaskError(f"{toml}: no files_digest line under [flightdeck.grader] to write")
    toml.write_text(DIGEST_LINE.sub(r'\g<1>""', text, count=1), encoding="utf-8")
    try:
        digest = load_task(path).files_digest
    finally:
        toml.write_text(text, encoding="utf-8")
    toml.write_text(DIGEST_LINE.sub(rf'\g<1>"{digest}"', text, count=1), encoding="utf-8")
    return digest


def hangar_id(task: Task) -> str:
    """The task's id within hangar's naming rule; a longer or odd id gets a stable short form."""
    if NAME.match(task.id):
        return task.id
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", task.id).strip("-._")[:31] or "task"
    return f"{stem}-{hashlib.sha256(task.id.encode()).hexdigest()[:8]}"


def to_hangar(tasks: list[Task]) -> list[dict[str, Any]]:
    """`hangar.experiment/v1` tasks, each with its own grader (KAN-192): its tests under `tests/`, run from its pristine
    `$HANGAR_HIDDEN_TESTS`. Without a source repo, `environment/workspace/` goes as the `workspace` hangar commits."""
    out: list[dict[str, Any]] = []
    for t in tasks:
        hid, src = hangar_id(t), t.flightdeck.get("source") or {}
        if any(x["id"] == hid for x in out):
            raise TaskError(f"task ids must be unique in an experiment (hangar's rule): {hid} twice")
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
        files = _text(t, "tests/", {f"tests/{k}": v for k, v in t.tests.items()}, MAX_GRADER_COUNT, MAX_GRADER_FILES)
        if len(cmd := f'cd "$HANGAR_HIDDEN_TESTS" && {t.grader.get("command") or DEFAULT_COMMAND}') > MAX_COMMAND:
            raise CapError(f"task {t.id}: the grader command is {len(cmd):,} characters; hangar takes {MAX_COMMAND:,}")
        timeout = int((t.config.get("verifier") or {}).get("timeout_sec") or 600)
        item["grader"] = {"command": cmd, "timeout_seconds": min(max(timeout, 30), 3600), "files": files}
        if (ws := {k[10:]: v for k, v in t.environment.items() if k.startswith("workspace/")}) and not src.get("repo"):
            if bad := ", ".join(k for k in ("issue", "base_branch", "base_sha") if src.get(k)):
                raise TaskError(f"task {t.id}: environment/workspace/ is its repo; [flightdeck.source] also sets {bad}")
            if bad := next((k for k in ws if GITDIR.search(k) or unicodedata.normalize("NFC", k) != k), ""):
                raise TaskError(f"task {t.id}: environment/workspace/{bad}: hangar takes no .git, control or NFD name")
            item["workspace"] = _text(t, "environment/workspace/", ws, MAX_WORKSPACE_FILES, MAX_GRADER_FILES)
        out.append(item)
    graders = sum(len(v.encode()) for x in out for v in x["grader"]["files"].values())
    if max(graders, sum(len(v.encode()) for x in out for v in x.get("workspace", {}).values())) > 16 * MAX_GRADER_FILES:
        raise CapError("the tasks' grader files or workspaces are over hangar's 16 MB per experiment")
    return out


def _text(t: Task, where: str, files: dict[str, bytes], count: int, size: int) -> dict[str, str]:
    """Files as text, within hangar's caps on one task's grader or workspace (a CapError names which)."""
    try:
        text = {k: v.decode("utf-8") for k, v in files.items()}
    except UnicodeDecodeError:
        raise TaskError(f"task {t.id}: a file in {where} is binary; hangar takes text") from None
    if len(text) > count:
        raise CapError(f"task {t.id}: {where} has {len(text)} files; hangar takes at most {count}")
    if (n := sum(len(v.encode()) for v in text.values())) > size:
        raise CapError(f"task {t.id}: {where} totals {n:,} bytes; hangar takes at most 1 MB (MAX_GRADER_FILES)")
    return text


def to_hangar_task(task: Task) -> dict[str, Any]:
    """One task as hangar's `Task`, with its own `grader` and, without a repo, its `workspace` (experiments.py)."""
    return to_hangar([task])[0]
