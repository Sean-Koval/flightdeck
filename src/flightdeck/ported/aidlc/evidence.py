# Ported from ai-dlc (https://github.com/Sean-Koval/ai-dlc), src/ai_dlc/verification/evaluation/run.py (`_redact`)
# and report.py (`manifest_of`)
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

"""Sealing an attempt's evidence: credential redaction and the evidence manifest.

Changes from ai-dlc: `redact` is run.py's `_redact` and `manifest_of` is report.py's, moved here unchanged; ai-dlc's
report rebuild, which re-checks the manifest, is not ported (flightdeck's report reads the data plane).
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

MANIFEST = "manifest.json"


def manifest_of(run_dir: Path) -> dict[str, str]:
    return {
        p.relative_to(run_dir).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(run_dir.rglob("*"))
        if p.is_file() and p.name != MANIFEST
    }


def redact(run_dir: Path, result: dict, names: list[str]) -> None:
    """Remove profile-named credential values from retained evidence and fail the attempt.

    Values shorter than eight characters are ignored to avoid shredding ordinary text.
    """
    found = []
    for name in names:
        value = os.environ.get(name, "").encode()
        if len(value) < 8:
            continue
        for path in sorted(p for p in run_dir.rglob("*") if p.is_file()):
            data = path.read_bytes()
            if value in data:
                path.write_bytes(data.replace(value, f"[REDACTED:{name}]".encode()))
                found.append(f"{name} in {path.relative_to(run_dir).as_posix()}")
    if found:
        result.update(
            outcome="incomplete",
            stage="redaction",
            detail="credential value found in evidence and redacted: " + ", ".join(found),
        )
