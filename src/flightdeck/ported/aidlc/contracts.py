# Ported from ai-dlc (https://github.com/Sean-Koval/ai-dlc), src/ai_dlc/verification/evaluation/contracts.py
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


"""Versioned evaluation contracts; scenarios never carry secret values.

`flightdeck task import-aidlc` (`flightdeck.tasks.aidlc`) validates ai-dlc suites with `Suite` and maps each `Scenario`
onto a task directory; `schemas/aidlc/scenario.schema.json` is the scenario's published JSON Schema
(`tests/test_aidlc_import.py` checks it still matches).

Changes from ai-dlc: the models no flightdeck path reads are gone (KAN-93): `Profile` with its `Engine`, `Driver`,
`Budgets` and `Egress`; `Event`; `Report` with `ArmReport` and `AssertionResult`; `BaseImage` with `Client` and `Mise`.
They described ai-dlc's runner, release qualification and report, none of which flightdeck uses. `Scenario`, `Suite`
and their parts are unchanged.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Identifier = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]*$")]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Text = Annotated[str, StringConstraints(min_length=1)]
Dimension = Literal["workflow", "correctness", "quality"]
ARMS = ("treatment", "baseline")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Fixture(Strict):
    """Paths resolve beside the suite file. `hidden` stays with the controller."""

    path: Text
    digest: Sha256
    hidden: Text | None = None


class Answer(Strict):
    """A bounded reply; a question matching no answer becomes needs-input."""

    match: Text
    reply: Text


class Assertion(Strict):
    id: Identifier
    dimension: Dimension
    kind: Identifier
    expect: Text | None = None
    path: Text | None = None
    before: Text | None = None
    after: Text | None = None
    mandatory: bool = True

    @model_validator(mode="after")
    def git_selectors(self):
        if self.kind == "commit-present":
            if self.before is not None or self.after is not None:
                raise ValueError("commit-present accepts only the optional path selector")
        elif self.kind == "path-committed":
            if self.path is None or self.before is not None or self.after is not None:
                raise ValueError("path-committed requires path and no ordering selectors")
        elif self.kind == "ordering" and (
            self.before is None or self.after is None or self.path is not None
        ):
            raise ValueError("ordering requires before and after selectors")
        return self


class Limits(Strict):
    timeout_minutes: Annotated[int, Field(ge=1)] = 30
    max_turns: Annotated[int, Field(ge=1)] = 20
    max_spend_usd: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None


class Scenario(Strict):
    id: Identifier
    goal: Text
    fixture: Fixture
    answers: list[Answer] = []
    checkpoints: list[Identifier] = []
    assertions: Annotated[list[Assertion], Field(min_length=1)]
    limits: Limits = Limits()
    # Names only: an arm cannot override the goal, fixture, answers or limits.
    arms: Annotated[list[Literal["treatment", "baseline"]], Field(min_length=1)]


class Suite(Strict):
    schema_version: Literal[1] = Field(alias="schema")
    id: Identifier
    scenarios: Annotated[list[Scenario], Field(min_length=1)]


SCHEMAS = {"scenario": Scenario}
