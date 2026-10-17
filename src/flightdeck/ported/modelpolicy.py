"""Whether a model id is concrete: ported from hangar `src/hangar/modelpolicy.py` (#167, `is_concrete` and
`concreteness`), so flightdeck's suites and ingest refuse exactly what hangar refuses in a pin set.

Keep it in step with hangar: `tests/fixtures/hangar/model_concreteness.json` is hangar's test table, and
`tests/test_modelpolicy.py` runs it against this module.
"""

from __future__ import annotations

import re
from typing import Any

POLICIES = ("frontier", "balanced")
VENDORS = ("anthropic", "openai", "google")
ANTHROPIC_LINES = {"fable": 4, "mythos": 4, "opus": 3, "sonnet": 2, "haiku": 1}


def parse(value: str | None) -> tuple[str, str | None] | None:
    """(policy, vendor) when `value` names a policy, else None (a pinned id)."""
    if not value:
        return None
    policy, _, vendor = value.strip().lower().partition("@")
    if policy not in POLICIES or (vendor and vendor not in VENDORS):
        return None
    return policy, vendor or None


def is_policy(value: str | None) -> bool:
    return parse(value) is not None


# A pin set is reproducible only if its model id is concrete: one the provider can't move between two trials. Floating
# aliases (`*-latest`, OpenRouter's `~vendor/...`, bare family names) never are, even when a provider lists them.
_LINES = "|".join(ANTHROPIC_LINES)
_BARE = re.compile(rf"(?:claude-)?(?:{_LINES})|claude|gpt|gemini|o\d+(?:-(?:mini|pro))?|gpt-\d+(?:\.\d+)?o?"
                   r"(?:-(?:mini|nano|pro|turbo))?|gemini-(?:\d+(?:\.\d+)?|pro|flash|flash-lite)|auto|default")
_DATED = re.compile(r".+-(?:\d{4}-\d{2}-\d{2}|20\d{6})")  # a snapshot: gpt-*-YYYY-MM-DD, claude-*-YYYYMMDD
_CONCRETE = (
    # Anthropic: a line with a major and minor version (claude-opus-5-5; OpenRouter's claude-opus-5.5), or dated
    re.compile(rf"claude-(?:{_LINES})-\d+[.-]\d+(?:-20\d{{6}})?"),
    re.compile(rf"claude-\d+(?:[.-]\d+)?-(?:{_LINES})-20\d{{6}}|claude-(?:{_LINES})-\d+-20\d{{6}}"),
    # OpenAI: gpt-<version>-<tier>, the ids hangar ranks (gpt-6-astra, gpt-6.1-sol)
    re.compile(r"gpt-\d+(?:\.\d+)?-(?:astra|sol|terra|luna)"),
    # Google: gemini-<version>-<tier>, optionally a preview or a numbered revision; agy adds a thinking level
    re.compile(r"gemini-\d+(?:\.\d+)?-(?:pro|flash|flash-lite)(?:-preview(?:-\d{2}-\d{2})?|-\d{3})?"
               r"(?:-(?:low|medium|high))?"),
)


def _bare_id(model: str) -> str:
    """The id without OpenRouter's `openrouter/` and `<vendor>/` prefixes or a `:variant` suffix."""
    mid = model.strip().removeprefix("openrouter/")
    return mid.rsplit("/", 1)[-1].partition(":")[0]


def _floating(model: str) -> bool:
    parts = model.strip().lower().split("/")
    if any(p.startswith("~") for p in parts) or parts[-1].partition(":")[2] == "latest":
        return True
    mid = _bare_id(model.lower())
    return mid == "latest" or mid.endswith("-latest") or "-latest-" in mid or bool(_BARE.fullmatch(mid))


def _listed(harness: str | None, model: str, models: list[dict[str, Any]]) -> bool:
    ids = {str(m.get("id") or "") for m in models}
    mid = model.strip()
    if harness == "pi" or mid.startswith("openrouter/"):
        mid = mid.removeprefix("openrouter/")
    if mid in ids:
        return True
    if harness == "antigravity":  # agy's id: the Gemini id without "-preview", plus a thinking level
        base = re.sub(r"-(?:low|medium|high)$", "", mid)
        return base in ids or f"{base}-preview" in ids
    return False


def concreteness(harness: str | None, model: str | None,
                 models: list[dict[str, Any]] | None = None) -> tuple[bool, str]:
    """(concrete, basis). basis: `list` (in the provider's cached model list), `pattern` (a known dated or versioned
    shape), or why not: `none` (no id: the harness's own default), `policy` (not resolved yet), `alias` (a floating
    alias: `*-latest`, `~vendor/...`, a bare family name such as `opus` or `gpt-5`) or `unknown` (neither listed nor
    of a known shape: never treated as concrete). `models`: the provider's list (None: no list cached)."""
    if not model or not model.strip():
        return False, "none"
    if is_policy(model):
        return False, "policy"
    if _floating(model):
        return False, "alias"
    if models and _listed(harness, model, models):
        return True, "list"
    mid = _bare_id(model)
    if _DATED.fullmatch(mid) or any(p.fullmatch(mid) for p in _CONCRETE):
        return True, "pattern"
    return False, "unknown"


def is_concrete(harness: str | None, model: str | None, models: list[dict[str, Any]] | None = None) -> bool:
    """Whether `model` is a concrete, dated id for `harness`: one a provider can't move between two trials."""
    return concreteness(harness, model, models)[0]
