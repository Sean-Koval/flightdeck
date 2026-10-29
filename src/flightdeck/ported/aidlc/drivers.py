# Ported from ai-dlc (https://github.com/Sean-Koval/ai-dlc), src/ai_dlc/verification/evaluation/drivers.py
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

"""Drivers decide what runs inside an attempt; the runner treats every kind the same way.

Changes from ai-dlc:
- `Deterministic` takes its script as data with a base directory, and runs one `steps` list (flightdeck has variants,
  not ai-dlc's baseline/treatment arms). The local backend builds the script from the task's `solution/`
  (`solution/deterministic.json`, else Harbor's oracle: copy `solution/` in and run `solve.sh`).
- `load_driver` is gone: the local backend picks the driver from the variant's `harness`.
- `ClaudeCode`, its stream parser and `retained_client` are gone (KAN-93): the real-client path never qualified
  against a live model, so model trials run on hangar only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

WRITER = "import pathlib,sys;p=pathlib.Path(sys.argv[1]);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(sys.argv[2])"  # noqa: E501


class Driver(Protocol):
    def environment(self, index: int) -> list[str]:
        """Docker exec environment entries, with credential names only (never values)."""
        ...

    def observe(self, item: dict, index: int, data: bytes, run_dir: Path) -> dict | None:
        """Validate a retained step before the next starts; return metering when available."""
        ...

    def retained(self) -> dict[str, object]:
        """Inputs a rerun needs, by name; each is written under the run's inputs."""
        ...

    def install(self, item: dict) -> list[list[str]]:
        """Commands of the install stage; skipped by the lifecycle in the baseline arm."""
        ...

    def steps(self, item: dict) -> list[list[str]]:
        """Commands of the planned attempt, one turn each."""
        ...


class Deterministic:
    """Fixed steps per arm from a script file. Exercises the runner; measures nothing."""

    def __init__(self, base: Path, script: dict):
        self.base, self.script = base, script

    def retained(self) -> dict[str, object]:
        return {"script": self.script}

    def install(self, item: dict) -> list[list[str]]:
        del item
        return self._argv(self.script.get("install", []))

    def steps(self, item: dict) -> list[list[str]]:
        del item
        return self._argv(self.script.get("steps", []))

    def environment(self, index: int) -> list[str]:
        return []

    def observe(self, item: dict, index: int, data: bytes, run_dir: Path) -> dict | None:
        return None

    def _argv(self, declared: list) -> list[list[str]]:
        """A step is an argv list, or {"write": path, "from": file} to place controller-held text."""
        steps = []
        for step in declared:
            if isinstance(step, dict):
                text = (self.base / step["from"]).read_text()
                steps.append(["python", "-c", WRITER, step["write"], text])
            else:
                steps.append([str(part) for part in step])
        return steps
