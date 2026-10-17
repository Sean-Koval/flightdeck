"""Normalized tool kinds and shell ops: ported from hangar `src/hangar/traces.py` (2662805, `tool_kind` and
`shell_ops`, unchanged), so the local runner's spans carry the same `tool_kind` and `shell_ops` as hangar's traces
(hangar docs/api/traces.md, "Normalized tool kinds" and "What a shell command does") and specs run unchanged.
"""

from __future__ import annotations

import re

_KINDS: dict[str, set[str]] = {
    "shell": {"Bash", "BashOutput", "KillShell", "bash", "shell", "run_command", "command_status"},
    "edit": {"Write", "Edit", "MultiEdit", "NotebookEdit", "write", "edit", "apply_patch", "write_to_file",
             "replace_file_content", "multi_replace_file_content", "sed_file", "notebook_edit"},
    "read": {"Read", "NotebookRead", "LS", "read", "ls", "view_file", "view_file_outline", "view_code_item",
             "list_dir", "read_file"},
    "search": {"Grep", "Glob", "grep", "find", "grep_search", "find_by_name", "codebase_search"},
    "web": {"WebFetch", "WebSearch", "web_search", "read_url_content", "search_web", "browser_preview"},
    "skill": {"Skill"},
    # --- review(#114): `plan`, not `todo`: the agent writing down or presenting its plan, for every harness
    "plan": {"TodoWrite", "ExitPlanMode", "todo_write", "update_plan"},
}
_BY_NAME = {n: k for k, names in _KINDS.items() for n in names}

_TEST_PROGRAMS = {"pytest", "py.test", "tox", "nox", "jest", "vitest", "mocha", "ava", "rspec", "phpunit", "ctest",
                  "gotestsum", "playwright"}
_TEST_SUBCOMMANDS = {"go": {"test"}, "cargo": {"test", "nextest"}, "npm": {"test", "t"}, "pnpm": {"test", "t"},
                     "yarn": {"test"}, "bun": {"test"}, "mvn": {"test", "verify"}, "gradle": {"test", "check"},
                     "./gradlew": {"test", "check"}, "make": {"test", "check"}, "dotnet": {"test"},
                     "bazel": {"test"}, "deno": {"test"}, "mix": {"test"}, "swift": {"test"}}
_WRAPPERS = {"uv": "run", "poetry": "run", "pipenv": "run", "hatch": "run", "pdm": "run", "bundle": "exec",
             "pnpm": "exec", "npx": None, "bunx": None, "sudo": None, "time": None, "env": None, "nice": None,
             "timeout": None, "xvfb-run": None}
_SEGMENT = re.compile(r"&&|\|\||[;|\n]")


def _words(segment: str) -> list[str]:
    import shlex

    try:
        words = shlex.split(segment)
    except ValueError:
        words = segment.split()
    while words and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", words[0]):  # FOO=bar cmd
        words = words[1:]
    return words


def _op(words: list[str]) -> str | None:
    for _ in range(4):  # uv run pytest, sudo -E npx jest, timeout 60 make test
        if not words:
            return None
        head = words[0].rsplit("/", 1)[-1] if words[0] != "./gradlew" else words[0]
        if head in _WRAPPERS and len(words) > 1 and not (head == "pnpm" and words[1] in _TEST_SUBCOMMANDS["pnpm"]):
            sub = _WRAPPERS[head]
            rest = words[1:]
            if sub is not None:
                if rest[0] != sub:
                    break
                rest = rest[1:]
            while rest and (rest[0].startswith("-") or re.fullmatch(r"\d+[smh]?|[A-Za-z_]\w*=.*", rest[0])):
                rest = rest[1:]  # the wrapper's own flags, a timeout's duration, env's assignments
            words = rest
            continue
        break
    if not words:
        return None
    head = words[0].rsplit("/", 1)[-1] if words[0] != "./gradlew" else words[0]
    args = [w for w in words[1:] if not w.startswith("-")]
    if head == "git":
        sub = next((w for i, w in enumerate(words[1:], 1) if not w.startswith("-")
                    and words[i - 1] not in ("-c", "-C")), None)
        return {"commit": "git.commit", "push": "git.push", "rm": "delete"}.get(sub or "")
    if head == "gh" and args[:2] == ["pr", "create"]:
        return "pr.open"
    if head in ("rm", "rmdir", "unlink", "shred") or (head == "find" and "-delete" in words):
        return "delete"
    if head in _TEST_PROGRAMS or (head.startswith("python") and words[1:3] in (["-m", "pytest"], ["-m", "unittest"])):
        return "test"
    if head in _TEST_SUBCOMMANDS and args and (args[0] in _TEST_SUBCOMMANDS[head] or (
            head in ("npm", "pnpm", "yarn", "bun") and args[0] == "run" and len(args) > 1
            and args[1].split(":")[0] in ("test", "tests"))):
        return "test"
    return None



def shell_ops(command: str | None) -> list[str]:
    """What a shell command does, in order: `test`, `git.commit`, `git.push`, `pr.open`, `delete`."""
    out: list[str] = []
    for seg in _SEGMENT.split(command or ""):
        if (op := _op(_words(seg.strip().lstrip("(").rstrip(")")))) and op not in out:
            out.append(op)
    return out



def tool_kind(name: str | None) -> str:
    """The normalized kind of a tool, by the name its harness gives it."""
    n = name or ""
    if n in _BY_NAME:
        return _BY_NAME[n]
    if n.startswith(("mcp__", "mcp_")) or re.fullmatch(r"[\w-]+\.[\w-]+", n):  # Claude / agy; Codex server.tool
        return "mcp"
    return "other"
