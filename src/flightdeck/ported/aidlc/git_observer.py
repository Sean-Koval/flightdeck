# Ported from ai-dlc (https://github.com/Sean-Koval/ai-dlc), src/ai_dlc/verification/evaluation/git_observer.py
# at f5be4f4206a8469f17d4b54296e41e06a2d1a41e, the handoff commit
# (tag eval-handoff-2026-10). Changes for flightdeck are listed in the docstring.
#
# MIT License
#
# Copyright (c) 2024 AI DLC contributors
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""Read-only Git observation of an untrusted, already-collected project tree.

Changes from ai-dlc: the anchor ref is `refs/flightdeck/anchor` and the temporary directory prefix is flightdeck's.
The local backend turns the observation's post-anchor commits into `git.commit` events and its paths into
`runs.diff_files`; `evaluate_git_assertion` (ai-dlc's `commit-present`, `path-committed`, `ordering`) is kept for
the assertion mapping (#17).
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import threading
from pathlib import Path, PurePosixPath

ANCHOR_REF = "refs/flightdeck/anchor"
MAX_COMMITS = 512
MAX_GIT_ENTRIES = 100_000
MAX_OUTPUT_BYTES = 1_048_576
MAX_WORKTREE_BYTES = 268_435_456
MAX_WORKTREE_FILE_BYTES = 16_777_216
GIT_TIMEOUT_SECONDS = 10
OBJECT_ID = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
REF_NAME = re.compile(r"^refs/[A-Za-z0-9._/-]+$")
EVIDENCE = "grading/git.json"


class GitUnavailable(Exception):
    """The collected repository cannot provide a bounded, trustworthy observation."""


def _git(objects: Path, controller_git_dir: Path, *arguments: str) -> bytes:
    executable = shutil.which("git")
    if not executable:
        raise GitUnavailable("controller Git is unavailable")
    environment = {
        "PATH": os.defpath,
        "LC_ALL": "C",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_OBJECT_DIRECTORY": str(objects),
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_PROTOCOL_FROM_USER": "0",
    }
    command = [
        executable,
        "--no-pager",
        "--no-optional-locks",
        "--no-replace-objects",
        f"--git-dir={controller_git_dir}",
        *arguments,
    ]
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=environment,
        )
    except OSError as exc:
        raise GitUnavailable("controller Git could not inspect the repository") from exc
    output = bytearray()
    overflow = threading.Event()

    def read_output() -> None:
        assert process.stdout is not None
        while chunk := process.stdout.read(65_536):
            if len(output) + len(chunk) > MAX_OUTPUT_BYTES:
                overflow.set()
                try:
                    process.kill()
                except OSError:
                    pass
                return
            output.extend(chunk)

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    try:
        process.wait(timeout=GIT_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.wait()
        reader.join(2)
        raise GitUnavailable("controller Git exceeded its time limit") from exc
    reader.join(2)
    if reader.is_alive():
        process.kill()
        reader.join(2)
        raise GitUnavailable("controller Git output could not be collected")
    if process.returncode != 0 or overflow.is_set():
        raise GitUnavailable("collected Git history is unavailable or exceeds its limits")
    return bytes(output)


def _preflight(project: Path) -> Path:
    if not project.is_dir() or project.is_symlink():
        raise GitUnavailable("collected project is missing or unsafe")
    git_dir = project / ".git"
    if not git_dir.is_dir() or git_dir.is_symlink():
        raise GitUnavailable("collected project has no internal Git directory")
    forbidden = [
        git_dir / "commondir",
        git_dir / "shallow",
        git_dir / "objects/info/alternates",
        git_dir / "objects/info/http-alternates",
    ]
    if any(path.exists() or path.is_symlink() for path in forbidden):
        raise GitUnavailable("collected Git directory references incomplete or external history")
    replacement_refs = git_dir / "refs/replace"
    if replacement_refs.exists() or replacement_refs.is_symlink():
        raise GitUnavailable("collected Git directory contains replacement history")
    entries = 0
    for root, directories, files in os.walk(git_dir, followlinks=False):
        for name in [*directories, *files]:
            entries += 1
            if entries > MAX_GIT_ENTRIES:
                raise GitUnavailable("collected Git directory exceeds its entry limit")
            path = Path(root) / name
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode) or not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                raise GitUnavailable("collected Git directory contains an unsafe path")
    packed_refs = git_dir / "packed-refs"
    if packed_refs.exists():
        if not packed_refs.is_file():
            raise GitUnavailable("collected Git directory contains an unsafe reference path")
        if packed_refs.stat().st_size > MAX_OUTPUT_BYTES:
            raise GitUnavailable("collected Git references exceed their size limit")
        if "refs/replace/" in packed_refs.read_text(errors="replace"):
            raise GitUnavailable("collected Git directory contains replacement history")
    return git_dir


def _decode_path(value: bytes) -> str:
    return value.decode("utf-8", errors="surrogateescape")


def _read_ref_file(path: Path) -> str:
    if not path.is_file() or path.stat().st_size > 4_096:
        raise GitUnavailable("collected Git reference is missing or malformed")
    return path.read_text(errors="replace").strip()


def _valid_ref_name(name: str) -> bool:
    parts = PurePosixPath(name).parts
    return bool(
        REF_NAME.fullmatch(name)
        and parts
        and all(part not in ("", ".", "..") and not part.endswith(".lock") for part in parts)
    )


def _packed_refs(git_dir: Path) -> dict[str, str]:
    path = git_dir / "packed-refs"
    if not path.exists():
        return {}
    refs: dict[str, str] = {}
    for line in path.read_text(errors="replace").splitlines():
        if not line or line.startswith(("#", "^")):
            continue
        try:
            object_id, name = line.split(" ", 1)
        except ValueError as exc:
            raise GitUnavailable("collected packed references are malformed") from exc
        if not OBJECT_ID.fullmatch(object_id) or not _valid_ref_name(name) or name in refs:
            raise GitUnavailable("collected packed references are malformed")
        refs[name] = object_id
    return refs


def _resolve_ref(git_dir: Path, name: str, packed: dict[str, str], depth: int = 0) -> str:
    if depth > 4 or (name != "HEAD" and not _valid_ref_name(name)):
        raise GitUnavailable("collected Git reference is unsafe")
    path = git_dir / name
    value = _read_ref_file(path) if path.exists() else packed.get(name, "")
    if OBJECT_ID.fullmatch(value):
        return value
    if value.startswith("ref: "):
        return _resolve_ref(git_dir, value.removeprefix("ref: "), packed, depth + 1)
    raise GitUnavailable("collected Git reference is missing or malformed")


def _controller_git_dir(root: Path, object_id: str) -> Path:
    git_dir = root / "repository.git"
    git_dir.mkdir()
    (git_dir / "objects").mkdir()
    (git_dir / "refs").mkdir()
    if len(object_id) == 64:
        config = "[core]\n\trepositoryformatversion = 1\n\tbare = true\n[extensions]\n\tobjectformat = sha256\n"
    else:
        config = "[core]\n\trepositoryformatversion = 0\n\tbare = true\n"
    (git_dir / "config").write_text(config)
    (git_dir / "HEAD").write_text(object_id + "\n")
    return git_dir


def _paths(objects: Path, controller_git_dir: Path, commit: str) -> list[str]:
    raw = _git(
        objects,
        controller_git_dir,
        "diff-tree",
        "--root",
        "-m",
        "--no-commit-id",
        "--name-only",
        "--no-renames",
        "--no-ext-diff",
        "-r",
        "-z",
        commit,
    )
    return sorted({_decode_path(path) for path in raw.split(b"\0") if path})


def _tree_entries(objects: Path, controller_git_dir: Path, head: str) -> list[dict[str, str]]:
    raw = _git(objects, controller_git_dir, "ls-tree", "-r", "-z", "--full-tree", head)
    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for record in raw.split(b"\0"):
        if not record:
            continue
        try:
            metadata, encoded_path = record.split(b"\t", 1)
            mode, kind, object_id = metadata.decode("ascii").split(" ")
        except (ValueError, UnicodeError) as exc:
            raise GitUnavailable("collected Git tree is malformed") from exc
        path = _decode_path(encoded_path)
        parts = PurePosixPath(path).parts
        if (
            mode not in ("100644", "100755")
            or kind != "blob"
            or not OBJECT_ID.fullmatch(object_id)
            or not parts
            or PurePosixPath(path).is_absolute()
            or any(part in ("", ".", "..") for part in parts)
            or path in seen
        ):
            raise GitUnavailable("collected Git tree contains an unsafe entry")
        seen.add(path)
        entries.append({"path": path, "mode": mode, "object": object_id})
    return entries


def _worktree_files(project: Path) -> dict[str, tuple[Path, os.stat_result]]:
    files: dict[str, tuple[Path, os.stat_result]] = {}
    entries = 0
    total_bytes = 0
    for root, directories, names in os.walk(project, followlinks=False):
        if Path(root) == project and ".git" in directories:
            directories.remove(".git")
        for name in [*directories, *names]:
            entries += 1
            if entries > MAX_GIT_ENTRIES:
                raise GitUnavailable("collected worktree exceeds its entry limit")
            path = Path(root) / name
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or not (
                stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)
            ):
                raise GitUnavailable("collected worktree contains an unsafe path")
            if stat.S_ISREG(info.st_mode):
                if info.st_size > MAX_WORKTREE_FILE_BYTES:
                    raise GitUnavailable("collected worktree contains an oversized file")
                total_bytes += info.st_size
                if total_bytes > MAX_WORKTREE_BYTES:
                    raise GitUnavailable("collected worktree exceeds its byte limit")
                relative = path.relative_to(project).as_posix()
                files[relative] = (path, info)
    return files


def _blob_id(path: Path, expected: os.stat_result, object_id: str) -> str:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        actual = os.fstat(descriptor)
        identity = ("st_dev", "st_ino", "st_size", "st_mtime_ns")
        if not stat.S_ISREG(actual.st_mode) or any(
            getattr(actual, field) != getattr(expected, field) for field in identity
        ):
            raise GitUnavailable("collected worktree changed during observation")
        digest = hashlib.sha256() if len(object_id) == 64 else hashlib.sha1(usedforsecurity=False)
        digest.update(f"blob {actual.st_size}\0".encode())
        with os.fdopen(descriptor, "rb", closefd=False) as source:
            while chunk := source.read(65_536):
                digest.update(chunk)
        return digest.hexdigest()
    finally:
        os.close(descriptor)


def _dirty_paths(project: Path, tree: list[dict[str, str]]) -> list[str]:
    worktree = _worktree_files(project)
    tracked = {entry["path"] for entry in tree}
    dirty = set(worktree) - tracked
    for entry in tree:
        current = worktree.get(entry["path"])
        if current is None:
            dirty.add(entry["path"])
            continue
        path, info = current
        executable = bool(info.st_mode & 0o111)
        if (
            executable != (entry["mode"] == "100755")
            or _blob_id(path, info, entry["object"]) != entry["object"]
        ):
            dirty.add(entry["path"])
    return sorted(dirty)


def _observe(project: Path, expected_anchor: str | None) -> dict:
    git_dir = _preflight(project)
    if expected_anchor is None or not OBJECT_ID.fullmatch(expected_anchor):
        raise GitUnavailable("controller staging anchor is missing or malformed")
    packed = _packed_refs(git_dir)
    anchor = _resolve_ref(git_dir, ANCHOR_REF, packed)
    if anchor != expected_anchor:
        raise GitUnavailable("collected staging anchor differs from the controller record")
    head = _resolve_ref(git_dir, "HEAD", packed)
    if len(head) != len(anchor):
        raise GitUnavailable("collected Git references use inconsistent object identifiers")
    with tempfile.TemporaryDirectory(prefix="flightdeck-git-observer-") as temporary:
        controller_git_dir = _controller_git_dir(Path(temporary), head)
        objects = git_dir / "objects"
        history = _git(
            objects,
            controller_git_dir,
            "rev-list",
            "--parents",
            "--topo-order",
            "--reverse",
            f"--max-count={MAX_COMMITS + 1}",
            head,
        ).decode()
        lines = [line.split() for line in history.splitlines() if line]
        if not lines or len(lines) > MAX_COMMITS:
            raise GitUnavailable("collected Git history is empty or exceeds its commit limit")
        if any(
            not parts or any(not OBJECT_ID.fullmatch(value) for value in parts) for parts in lines
        ):
            raise GitUnavailable("collected Git history contains malformed object identifiers")
        hashes = {parts[0] for parts in lines}
        roots = [parts[0] for parts in lines if len(parts) == 1]
        if roots != [anchor] or any(
            parent not in hashes for parts in lines for parent in parts[1:]
        ):
            raise GitUnavailable("controller staging anchor is not the sole complete history root")

        commits = [
            {
                "hash": parts[0],
                "parents": parts[1:],
                "order": order,
                "anchor": parts[0] == anchor,
                "paths": _paths(objects, controller_git_dir, parts[0]),
            }
            for order, parts in enumerate(lines)
        ]
        tree = _tree_entries(objects, controller_git_dir, head)
    head_paths = sorted(entry["path"] for entry in tree)
    return {
        "schema": 1,
        "status": "available",
        "detail": None,
        "anchor_commit": anchor,
        "head_commit": head,
        "commits": commits,
        "head_paths": head_paths,
        "dirty_paths": _dirty_paths(project, tree),
    }


def retain_git_observation(run_dir: Path, *, expected_anchor: str | None) -> dict:
    """Retain a bounded observation; repository failures become evidence, never exceptions."""
    try:
        observation = _observe(run_dir / "tree/project", expected_anchor)
    except (GitUnavailable, OSError, UnicodeError, ValueError) as exc:
        observation = {
            "schema": 1,
            "status": "unavailable",
            "detail": str(exc) or "collected Git history is unavailable",
            "anchor_commit": expected_anchor
            if expected_anchor and OBJECT_ID.fullmatch(expected_anchor)
            else None,
            "head_commit": None,
            "commits": [],
            "head_paths": [],
            "dirty_paths": [],
        }
    grading = run_dir / "grading"
    grading.mkdir(exist_ok=True)
    (grading / "git.json").write_text(json.dumps(observation, indent=2, sort_keys=True) + "\n")
    return observation


def _validated_observation(run_dir: Path) -> dict:
    try:
        observation = json.loads((run_dir / EVIDENCE).read_text())
        if not isinstance(observation, dict) or observation.get("schema") != 1:
            raise ValueError
        if observation.get("status") == "unavailable":
            detail = observation.get("detail")
            if not isinstance(detail, str) or not detail:
                raise ValueError
            return observation
        commits = observation.get("commits")
        if observation.get("status") != "available" or not isinstance(commits, list) or not commits:
            raise ValueError
        if not all(
            isinstance(item, dict)
            and OBJECT_ID.fullmatch(str(item.get("hash", "")))
            and isinstance(item.get("parents"), list)
            and all(OBJECT_ID.fullmatch(str(parent)) for parent in item["parents"])
            and item.get("order") == index
            and isinstance(item.get("anchor"), bool)
            and isinstance(item.get("paths"), list)
            and all(isinstance(path, str) for path in item["paths"])
            for index, item in enumerate(commits)
        ):
            raise ValueError
        anchor = observation.get("anchor_commit")
        if [item["hash"] for item in commits if item["anchor"]] != [anchor]:
            raise ValueError
        seen: set[str] = set()
        for item in commits:
            if (item["hash"] == anchor) != (not item["parents"]):
                raise ValueError
            if any(parent not in seen for parent in item["parents"]):
                raise ValueError
            seen.add(item["hash"])
        if observation.get("head_commit") != commits[-1]["hash"]:
            raise ValueError
        for key in ("head_paths", "dirty_paths"):
            if not isinstance(observation.get(key), list) or not all(
                isinstance(path, str) for path in observation[key]
            ):
                raise ValueError
        return observation
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {"status": "unavailable", "detail": "Git observation missing or malformed"}


def _matching_commits(observation: dict, pattern: str | None) -> list[dict]:
    commits = [item for item in observation["commits"] if not item["anchor"]]
    if pattern is None:
        return commits
    return [
        item
        for item in commits
        if any(fnmatch.fnmatchcase(path, pattern) for path in item["paths"])
    ]


def _ancestors(commits: list[dict], commit: str) -> set[str]:
    parents = {item["hash"]: set(item["parents"]) for item in commits}
    found: set[str] = set()
    pending = list(parents.get(commit, set()))
    while pending:
        parent = pending.pop()
        if parent not in found:
            found.add(parent)
            pending.extend(parents.get(parent, set()))
    return found


def evaluate_git_assertion(
    run_dir: Path, kind: str, *, path: str | None, before: str | None, after: str | None
) -> tuple[str, str, list[str]]:
    observation = _validated_observation(run_dir)
    if observation["status"] != "available":
        return "unavailable", observation["detail"], [EVIDENCE]
    if kind == "commit-present":
        matches = _matching_commits(observation, path)
        target = f" changing {path}" if path else ""
        return (
            ("pass", f"{len(matches)} post-anchor commit(s){target}", [EVIDENCE])
            if matches
            else ("fail", f"no post-anchor commit{target}", [EVIDENCE])
        )
    if kind == "path-committed" and path:
        matches = _matching_commits(observation, path)
        head = [item for item in observation["head_paths"] if fnmatch.fnmatchcase(item, path)]
        dirty = [item for item in observation["dirty_paths"] if fnmatch.fnmatchcase(item, path)]
        if dirty:
            return "fail", f"matching path has uncommitted changes: {', '.join(dirty)}", [EVIDENCE]
        if not matches or not head:
            return "fail", f"no committed path at HEAD matches {path}", [EVIDENCE]
        return "pass", f"{len(head)} committed path(s) at HEAD match {path}", [EVIDENCE]
    if kind == "ordering" and before and after:
        before_commits = _matching_commits(observation, before)
        after_commits = _matching_commits(observation, after)
        before_hashes = {item["hash"] for item in before_commits}
        ordered = bool(before_commits and after_commits) and all(
            bool(before_hashes & _ancestors(observation["commits"], item["hash"]))
            for item in after_commits
        )
        if ordered:
            return "pass", f"{before} was committed before {after}", [EVIDENCE]
        return (
            "fail",
            f"collected history does not commit {before} before implementation matching {after}",
            [EVIDENCE],
        )
    return "unavailable", f"invalid selectors for {kind}", [EVIDENCE]
