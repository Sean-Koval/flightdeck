# Ported from ai-dlc (https://github.com/Sean-Koval/ai-dlc), src/ai_dlc/verification/evaluation/budgets.py
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

"""Conservative scheduling from observed usage, not a hard bound on future billing.

Unchanged from ai-dlc. The local backend keeps one ledger per run set for real-client (Claude Code) trials.
"""

from __future__ import annotations

from decimal import Decimal, localcontext

RECEIPT = "budget.json"


class RunBudget:
    """A sequential ledger shared by every scenario and arm of a real-client run."""

    def __init__(self, limits: dict):
        self.tokens = limits["max_tokens"]
        self.spend = Decimal(str(limits["max_spend_usd"]))
        self.worst_tokens = 0
        self.worst_spend = Decimal(0)
        self.unknown = False

    def decision(self, planned: dict) -> dict:
        limit, detail = None, None
        cap = min(self.spend, Decimal(str(planned["limits"]["max_spend_usd"])))
        if self.unknown:
            limit, detail = (
                "unknown-usage",
                "earlier client consumption is unavailable or untrusted",
            )
        elif self.tokens <= 0 or self.tokens < self.worst_tokens:
            limit, detail = "max_tokens", "remaining run tokens cannot cover worst observed usage"
        elif self.spend <= 0 or self.spend < self.worst_spend or cap <= 0:
            limit, detail = "max_spend_usd", "remaining spend cannot cover worst observed usage"
        return {
            "schema": 1,
            "scenario": planned["scenario"],
            "arm": planned["arm"],
            "attempt": planned["attempt"],
            "start": limit is None,
            "limit": limit,
            "detail": detail,
            # Decimal strings retain exact scheduling boundaries in portable JSON.
            "remaining_tokens": self.tokens,
            "remaining_spend_usd": str(self.spend),
            "worst_tokens": self.worst_tokens,
            "worst_spend_usd": str(self.worst_spend),
            "max_spend_usd": str(cap) if limit is None else None,
        }

    def observe(self, client: dict | None) -> None:
        if client is None:
            self.unknown = True
            return
        usage = client["usage"]  # callers pass only validated native metering
        tokens, spend = usage["total_tokens"], Decimal(str(usage["cost_usd"]))
        self.tokens -= tokens
        # Native costs are finite floats; preserve subtraction even at their extremes.
        with localcontext() as context:
            context.prec = 650
            self.spend -= spend
        self.worst_tokens = max(self.worst_tokens, tokens)
        self.worst_spend = max(self.worst_spend, spend)


def refused_attempt(decision: dict) -> dict:
    return {
        **{key: decision[key] for key in ("scenario", "arm", "attempt")},
        "outcome": "not-started",
        "stage": "budget",
        "limit": decision["limit"],
        "detail": decision["detail"],
        "cleanup": {"clean": True, "failed": []},
    }
