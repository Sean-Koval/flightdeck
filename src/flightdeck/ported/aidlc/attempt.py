# Ported from ai-dlc (https://github.com/Sean-Koval/ai-dlc), src/ai_dlc/verification/evaluation/attempt.py
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

"""One isolated evaluation attempt: provision, install, drive, collect, then clean up.

The controller stays on the host. The attempt's project lives in a per-attempt volume
so a separate collector can read it after the agent's container is stopped, and nothing
from the host is mounted into the attempt. There is no host fallback.

Changes from ai-dlc, for flightdeck's task model (docs/local.md):
- The project is the task image's working directory (`planned["workdir"]`): with no host fixture the stager copies it
  from the image into the volume (dropping any `.git`), and the volume is mounted at that path in the agent's
  container. A host fixture directory is still staged as before. The collector reads the volume root.
- Every attempt gets the controller's Git anchor (not only real-client ones), so the backend can turn commits into
  `git.commit` events; the anchor commit may be empty. The image needs `git`.
- Each step's record carries its start and end (`time_ns`) and the post-anchor commits seen after it (`commits`, read
  by the controller), which place commits between steps.
- The install stage runs in every variant (ai-dlc skipped it in the baseline arm); names, the anchor ref and the Git
  identity are flightdeck's.
- Egress is gone (KAN-93): only the real client used the allow-listing proxy, and that path was removed, so every
  attempt runs with `--network=none`.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import subprocess
import tarfile
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from flightdeck.ported.aidlc.drivers import Driver

PINNED = re.compile(r"([^\s@]+@)?sha256:[0-9a-f]{64}")
AGENT = "1000:1000"
GIT_OBJECT = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
GIT_ANCHOR_REF = "refs/flightdeck/anchor"
GIT_AUTHOR = "flightdeck"
GIT_EMAIL = "local@flightdeck.invalid"
GIT_DATE = "2000-01-01T00:00:00Z"
WORKDIR = "/work/project"
ISOLATION = [
    "--read-only",
    "--cap-drop=ALL",
    "--security-opt=no-new-privileges",
]


class Stopped(Exception):
    """A limit or cancellation ended the attempt; `limit` names which."""

    def __init__(self, limit: str, *, stdout: bytes = b"", stderr: bytes = b""):
        super().__init__(limit)
        self.limit, self.stdout, self.stderr = limit, stdout, stderr


class StageFailed(Exception):
    def __init__(self, stage: str, outcome: str, detail: str):
        super().__init__(detail)
        self.stage, self.outcome, self.detail = stage, outcome, detail


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _docker(args, *, timeout: float, input: bytes | None = None, cancel=None):
    """Run the docker CLI, polling so a deadline or cancellation interrupts a long exec."""
    process = subprocess.Popen(
        ["docker", *args],
        stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    result: dict = {}

    def communicate():
        result["out"], result["err"] = process.communicate(input)

    reader = threading.Thread(target=communicate, daemon=True)
    reader.start()
    deadline = time.monotonic() + timeout
    while reader.is_alive():
        reader.join(0.2)
        limit = (
            "cancelled"
            if cancel is not None and cancel.is_set()
            else "timeout_minutes"
            if time.monotonic() > deadline
            else None
        )
        if limit and reader.is_alive():
            process.kill()
            reader.join(5)
            raise Stopped(limit, stdout=result.get("out", b""), stderr=result.get("err", b""))
    return subprocess.CompletedProcess(
        args, process.returncode, result.get("out", b""), result.get("err", b"")
    )


def _fixture_archive(fixture: Path) -> bytes:
    fixture = fixture.resolve()
    if not fixture.is_dir():
        raise ValueError(f"Evaluation fixture is not a directory: {fixture}")
    if any(".git" in path.relative_to(fixture).parts for path in fixture.rglob("*")):
        raise ValueError("Evaluation fixtures cannot include Git metadata")
    if any(p.is_symlink() for p in fixture.rglob("*")):
        raise ValueError("Evaluation fixtures cannot include a symlink")
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        tar.add(fixture, arcname=".", recursive=True)
    return buffer.getvalue()


def _extract(data: bytes, destination: Path) -> dict[str, str]:
    """Unpack collected evidence with the data filter, which refuses traversal and links."""
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        tar.extractall(destination, filter="data")
    return {
        p.relative_to(destination).as_posix(): sha256(p.read_bytes())
        for p in sorted(destination.rglob("*"))
        if p.is_file()
    }


class _Attempt:
    def __init__(
        self,
        planned,
        run_dir,
        fixture,
        install,
        steps,
        timeout,
        cancel,
        memory,
        pids,
        driver,
    ):
        self.planned, self.run_dir = planned, run_dir
        self.driver, self.client = driver, None
        self.git_anchor: str | None = None
        self.fixture, self.install, self.steps = fixture, install, steps
        self.cancel, self.memory, self.pids = cancel, memory, pids
        self.deadline = time.monotonic() + timeout
        self.workdir = planned.get("workdir") or WORKDIR
        uid = "flightdeck-local-" + uuid.uuid4().hex[:12]
        self.container, self.volume = uid, uid + "-work"
        self.created: list[tuple[str, str]] = []

    def event(self, kind: str, **fields) -> None:
        record = {
            "schema": 1,
            "source": "controller",
            "at": datetime.now(UTC).isoformat(),
            "kind": kind,
            **fields,
        }
        with (self.run_dir / "events.jsonl").open("a") as log:
            log.write(json.dumps(record, sort_keys=True) + "\n")

    def docker(self, *args, input=None, bounded=True, floor=30.0):
        remaining = self.deadline - time.monotonic()
        if bounded and remaining <= 0:
            raise Stopped("timeout_minutes")
        # Controller-owned collection and cleanup keep a floor so a spent deadline
        # cannot discard evidence.
        timeout = remaining if bounded else max(remaining, floor)
        return _docker(
            list(args), timeout=timeout, input=input, cancel=self.cancel if bounded else None
        )

    def must(self, stage: str, outcome: str, *args, input=None):
        done = self.docker(*args, input=input)
        if done.returncode:
            raise StageFailed(stage, outcome, done.stderr.decode(errors="replace").strip())
        return done

    def provision(self) -> None:
        if not shutil.which("docker"):
            raise StageFailed("provision", "infrastructure", "Docker is required; no host fallback")
        self.must("provision", "infrastructure", "volume", "create", self.volume)
        self.created.append(("volume", self.volume))
        self.must(
            "provision",
            "infrastructure",
            "create",
            "--name",
            self.container,
            "--network=none",
            *ISOLATION,
            f"--user={AGENT}",
            f"--memory={self.memory}",
            f"--pids-limit={self.pids}",
            "--tmpfs=/tmp:rw,nosuid,size=256m",
            "--tmpfs=/home/agent:rw,nosuid,exec,uid=1000,gid=1000,size=512m",
            "--env=HOME=/home/agent",
            f"--workdir={self.workdir}",
            "--mount",
            f"type=volume,src={self.volume},dst={self.workdir}",
            self.planned["image"],
            "sleep",
            "infinity",
        )
        self.created.append(("container", self.container))
        self.event("provision", container=self.container, volume=self.volume)

    def stage_fixture(self) -> None:
        # Controller-owned stager: the only root process, gone before the agent starts.
        if self.fixture is None:  # the image's own working directory, without its Git metadata
            copy = 'if [ -d "$1" ]; then cp -a "$1"/. /w/ || exit 1; fi; rm -rf /w/.git && chown -R '
            script, archive = copy + AGENT + " /w", None
        else:
            script, archive = f"tar -x -C /w && chown -R {AGENT} /w", _fixture_archive(self.fixture)
        self.must(
            "stage-fixture",
            "infrastructure",
            "run",
            "--rm",
            "-i",
            "--network=none",
            "--cap-drop=ALL",
            "--cap-add=CHOWN",
            "--cap-add=DAC_OVERRIDE",
            "--cap-add=FOWNER",
            "--security-opt=no-new-privileges",
            "--user=0:0",
            "--mount",
            f"type=volume,src={self.volume},dst=/w",
            self.planned["image"],
            "sh",
            "-c",
            script,
            "sh",
            self.workdir,
            input=archive,
        )
        self.must("stage-fixture", "infrastructure", "start", self.container)
        self.event("stage-fixture", sha256=sha256(archive) if archive else None, workdir=self.workdir)

    def run_install(self) -> None:
        for command in self.install:
            self.must("install", "infrastructure", "exec", self.container, *command)
        self.event("install", commands=len(self.install))

    def initialize_repository(self) -> None:
        """Create the same controller-owned Git root before either arm diverges."""

        common = [
            "--env=GIT_CONFIG_NOSYSTEM=1",
            "--env=GIT_CONFIG_GLOBAL=/dev/null",
        ]

        def git(*args: str, environment: tuple[str, ...] = ()):
            return self.must(
                "git-anchor",
                "infrastructure",
                "exec",
                *common,
                *[f"--env={entry}" for entry in environment],
                self.container,
                "git",
                *args,
            )

        git("init", "--quiet", "--initial-branch=main", "--template=")
        git("config", "--local", "user.name", GIT_AUTHOR)
        git("config", "--local", "user.email", GIT_EMAIL)
        git("add", "--all", "--", ".")
        git(
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.hooksPath=/dev/null",
            "commit",
            "--quiet",
            "--no-verify",
            "--allow-empty",
            "-m",
            "chore: stage evaluation fixture",
            environment=(f"GIT_AUTHOR_DATE={GIT_DATE}", f"GIT_COMMITTER_DATE={GIT_DATE}"),
        )
        anchor = git("rev-parse", "--verify", "HEAD^{commit}").stdout.decode().strip()
        if not GIT_OBJECT.fullmatch(anchor):
            raise StageFailed("git-anchor", "infrastructure", "Git returned an invalid anchor")
        git("update-ref", GIT_ANCHOR_REF, anchor)
        self.git_anchor = anchor
        self.event("git-anchor", commit=anchor, ref=GIT_ANCHOR_REF)

    def drive(self) -> None:
        (self.run_dir / "steps").mkdir(exist_ok=True)
        for index, command in enumerate(self.steps, start=1):
            environment = self.driver.environment(index) if self.driver else []
            interrupted, started = None, time.time_ns()
            try:
                done = self.docker(
                    "exec", *[f"--env={entry}" for entry in environment], self.container, *command
                )
            except Stopped as stop:
                interrupted = stop
                done = subprocess.CompletedProcess(command, -1, stop.stdout, stop.stderr)
            record = {
                "command": command,
                "exit_code": done.returncode,
                "stdout": done.stdout.decode(errors="replace"),
                "stderr": done.stderr.decode(errors="replace"),
                "start_ns": started,
                "end_ns": time.time_ns(),
                "commits": None if interrupted else self.commits(),
            }
            (self.run_dir / "steps" / f"{index:02d}.json").write_text(
                json.dumps(record, indent=2, sort_keys=True) + "\n"
            )
            self.event("step", index=index, exit_code=done.returncode)
            problem = None
            if self.driver:
                try:
                    self.client = self.driver.observe(
                        self.planned, index, done.stdout, self.run_dir
                    )
                except ValueError as exc:
                    problem = str(exc)
            if interrupted:
                raise interrupted
            # Observation retains raw bytes first, but a broken stream must not
            # hide a controller-observed process/resource failure.
            if done.returncode:
                killed = self.docker(
                    "inspect", "--format", "{{.State.OOMKilled}}", self.container, bounded=False
                )
                if killed.stdout.decode().strip() == "true" or done.returncode == 137:
                    raise StageFailed("step", "infrastructure", "memory limit reached")
            if self.client and not self.client["complete"]:
                if self.client["limit"]:
                    raise Stopped(self.client["limit"])
                raise StageFailed("driver", "incomplete", "Claude Code returned a terminal error")
            if done.returncode:
                raise StageFailed("step", "incomplete", f"step {index} exited {done.returncode}")
            if problem:
                raise StageFailed("driver", "incomplete", problem)

    def commits(self) -> list[str] | None:
        """Post-anchor commits now in the project, oldest first; None when Git can't say (the observer decides)."""
        if not self.git_anchor:
            return None
        done = self.docker(
            "exec", "--env=GIT_CONFIG_NOSYSTEM=1", "--env=GIT_CONFIG_GLOBAL=/dev/null", self.container,
            "git", "rev-list", "--reverse", "--max-count=512", f"{GIT_ANCHOR_REF}..HEAD", bounded=False,
        )  # fmt: skip
        return done.stdout.decode(errors="replace").split() if done.returncode == 0 else None

    def collect(self) -> dict:
        """Stop the agent, then read its project through a separate read-only collector."""
        self.docker("kill", self.container, bounded=False)
        done = self.docker(
            "run",
            "--rm",
            "--network=none",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--mount",
            f"type=volume,src={self.volume},dst=/w,readonly",
            self.planned["image"],
            "tar",
            "-c",
            "-C",
            "/w",
            ".",
            bounded=False,
            floor=120.0,
        )
        if done.returncode:
            raise StageFailed("collect", "incomplete", done.stderr.decode(errors="replace").strip())
        try:
            tree = _extract(done.stdout, self.run_dir / "tree" / "project")
        except (tarfile.TarError, OSError) as exc:
            shutil.rmtree(self.run_dir / "tree", ignore_errors=True)
            raise StageFailed(
                "collect", "incomplete", f"unsafe or unreadable evidence: {exc}"
            ) from exc
        self.event("collect", files=len(tree))
        return {"tree": tree}

    def cleanup(self) -> dict:
        failed = []
        for kind, name in reversed(self.created):
            args = {
                "container": ("rm", "-f", name),
                "volume": ("volume", "rm", "-f", name),
                "network": ("network", "rm", name),
            }[kind]
            try:
                done = self.docker(*args, bounded=False)
                error = done.stderr.decode(errors="replace").strip() if done.returncode else None
            except (Stopped, OSError) as exc:
                error = str(exc)
            if error:
                failed.append({"kind": kind, "id": name, "error": error})
        if failed:
            with (self.run_dir / "cleanup-ledger.jsonl").open("a") as ledger:
                for item in failed:
                    ledger.write(json.dumps(item, sort_keys=True) + "\n")
        self.event("cleanup", clean=not failed)
        return {"clean": not failed, "failed": failed}


def run_attempt(
    planned: dict,
    *,
    run_dir: Path,
    fixture: Path | None,
    steps: list[list[str]],
    install: list[list[str]] | None = None,
    timeout_seconds: float | None = None,
    cancel: threading.Event | None = None,
    memory: str = "1g",
    pids: int = 256,
    driver: Driver | None = None,
) -> dict:
    """Run one planned attempt and return its driver-level outcome with evidence references."""
    if not PINNED.fullmatch(planned.get("image", "")):
        raise ValueError("Evaluation image must be pinned by digest")
    if fixture is not None:
        _fixture_archive(fixture)  # refuse an unsafe fixture before anything is created
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "inputs.json").write_text(
        json.dumps({"planned": planned, "steps": steps, "install": install or []}, indent=2)
    )
    timeout = timeout_seconds or planned["limits"]["timeout_minutes"] * 60
    state = _Attempt(
        planned,
        run_dir,
        fixture,
        install or [],
        steps,
        timeout,
        cancel,
        memory,
        pids,
        driver,
    )
    result: dict = {
        "scenario": planned["scenario"],
        "arm": planned["arm"],
        "attempt": planned["attempt"],
        "outcome": "completed",
        "stage": None,
        "limit": None,
        "detail": None,
        "resources": {"container": state.container, "volume": state.volume},
        # Disk is metered by collection size only; the local volume driver enforces no quota.
        "enforced": ["timeout_minutes", "memory", "pids", "network"],
    }
    try:
        state.provision()
        state.stage_fixture()
        state.initialize_repository()
        state.run_install()
        state.drive()
    except Stopped as stop:
        result.update(outcome="incomplete", stage="step", limit=stop.limit)
    except StageFailed as failure:
        result.update(outcome=failure.outcome, stage=failure.stage, detail=failure.detail)
        if failure.detail == "memory limit reached":
            result["limit"] = "memory"
    if driver:
        result["client"] = state.client
    result["git_anchor"] = state.git_anchor
    try:
        evidence: dict = state.collect() if state.created else {"tree": {}}
        result["evidence"] = evidence
    except (Stopped, StageFailed) as failure:
        result.setdefault("evidence", {"tree": {}})  # a collected tree survives a lost log
        if result["outcome"] == "completed":
            result.update(outcome="incomplete", stage="collect", detail=str(failure))
    result["cleanup"] = state.cleanup() if state.created else {"clean": True, "failed": []}
    (run_dir / "attempt.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def run_isolated(image: str, archive: bytes, command: str, *, timeout: float) -> dict:
    """Run a controller-owned command over an unpacked archive; no network, nothing mounted."""
    if not PINNED.fullmatch(image):
        raise ValueError("Evaluation image must be pinned by digest")
    done = _docker(
        [
            "run",
            "--rm",
            "-i",
            "--network=none",
            *ISOLATION,
            f"--user={AGENT}",
            "--memory=512m",
            "--pids-limit=128",
            "--tmpfs=/tmp:rw,nosuid,size=64m",
            "--tmpfs=/g:rw,nosuid,exec,uid=1000,gid=1000,size=256m",
            "--env=HOME=/tmp",
            "--env=PYTHONDONTWRITEBYTECODE=1",
            image,
            "sh",
            "-c",
            f"tar -x -C /g && cd /g && {command}",
        ],
        timeout=timeout,
        input=archive,
    )
    return {
        "exit_code": done.returncode,
        "stdout": done.stdout.decode(errors="replace"),
        "stderr": done.stderr.decode(errors="replace"),
    }
