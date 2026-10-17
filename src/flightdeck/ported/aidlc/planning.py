# Ported from ai-dlc (https://github.com/Sean-Koval/ai-dlc), src/ai_dlc/verification/evaluation/planning.py
# (and `tree_digest` from run.py) at f5be4f4206a8469f17d4b54296e41e06a2d1a41e, the handoff commit
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

"""Offline checks on a suite before anything runs: no process, socket or credential value is touched here.

Changes for flightdeck: only the suite checks are kept, for `flightdeck task import-aidlc`: the credential tripwire
(`refuse_secrets`, ai-dlc's `_refuse_secrets`), model validation that names fields (`validated`), duplicate ids
(`unique`) and the fixture digest (`tree_digest`, from ai-dlc's `run.py`). `plan()`, the profile checks and the
scenario x arm x attempt matrix are dropped: a flightdeck suite file (`TrialPlan`) expands trials, and variants
replace profiles. ai-dlc's rule that both arms run and that workflow assertions judge only the treatment arm is kept
by the importer (`flightdeck.tasks.aidlc`).
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from pydantic import ValidationError

SECRET_KEY = re.compile(r"secret|token|password|passwd|api[_-]?key|credential", re.IGNORECASE)
# Recognizable credential shapes only; this is a tripwire, not proof of absence.
SECRET_VALUE = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|\bgh[pousr]_[A-Za-z0-9]{36,}|\bgithub_pat_[A-Za-z0-9_]{20,}"
    r"|\bsk-[A-Za-z0-9_-]{20,}|\bxox[abprs]-[A-Za-z0-9-]{10,}|\bAKIA[0-9A-Z]{16}\b"
    r"|\bATATT[A-Za-z0-9_=-]{20,}"
)


def refuse_secrets(value: object, path: str) -> None:
    """Name the field, never the value."""
    if isinstance(value, dict):
        for key, item in value.items():
            if SECRET_KEY.search(str(key)):
                raise ValueError(f"Scenarios must not carry credentials: {path}.{key}")
            refuse_secrets(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            refuse_secrets(item, f"{path}[{index}]")
    elif isinstance(value, str) and SECRET_VALUE.search(value):
        raise ValueError(f"Scenarios must not carry credentials: {path}")


def validated(model, raw: object, label: str):
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors(include_input=False)
        )
        raise ValueError(f"Invalid evaluation {label}: {problems}") from None


def unique(values: list[str], label: str) -> None:
    repeated = sorted({v for v in values if values.count(v) > 1})
    if repeated:
        raise ValueError(f"Duplicate {label}: {', '.join(repeated)}")


def tree_digest(root: Path) -> str:
    """Content identity of a directory: relative paths and file bytes, never timestamps."""
    total = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
        total.update(path.relative_to(root).as_posix().encode() + b"\0")
        total.update(hashlib.sha256(path.read_bytes()).digest())
    return total.hexdigest()
