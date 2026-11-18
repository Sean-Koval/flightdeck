"""Normalized tool kinds and shell ops: ported from hangar `src/hangar/traces.py` (`tool_kind` at 2662805,
`shell_ops` at 3095545 (hangar#491, KAN-279), both unchanged), so the local runner's spans carry the same `tool_kind`
and `shell_ops` as hangar's traces (hangar docs/api/traces.md, "Normalized tool kinds" and "What a shell command
does") and specs run unchanged.
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
# The wrapper flags that take a value as the next word (`uv run --project svc pytest`): that value isn't the program.
_WRAPPER_VALUE_FLAGS = {
    "uv": {"--project", "--directory", "--with", "--with-requirements", "--with-editable", "--python", "-p",
           "--package", "--extra", "--group", "--only-group", "--no-group", "--env-file", "--index", "--from",
           "--config-file", "--cache-dir", "--index-url", "--extra-index-url", "--default-index", "--find-links",
           "-P", "--upgrade-package", "--index-strategy", "--keyring-provider"},
    "poetry": {"-C", "--directory", "-P", "--project"}, "pdm": {"-p", "--project"}, "hatch": {"-e", "--env"},
    "pipenv": set(), "bundle": {"--gemfile"}, "pnpm": {"-C", "--dir", "-F", "--filter"},
    "npx": {"-p", "--package"}, "bunx": {"-p", "--package"}, "sudo": {"-u", "-g", "-C", "-D", "-h", "-p", "-U"},
    "time": {"-f", "--format", "-o", "--output"}, "env": {"-u", "--unset", "-C", "--chdir"},
    "nice": {"-n", "--adjustment"}, "timeout": {"-s", "--signal", "-k", "--kill-after"},
    "xvfb-run": {"-n", "--server-num", "-s", "--server-args", "-e", "--error-file", "-f", "--auth-file", "-w",
                 "--wait", "-p", "--xauth-protocol"},
    "sh": {"-o", "-O", "--rcfile", "--init-file"}}
for _shell in ("bash", "zsh", "dash"):
    _WRAPPER_VALUE_FLAGS[_shell] = _WRAPPER_VALUE_FLAGS["sh"]
# A runner's flags that take a value before its subcommand (`make -C svc test`, `pnpm --filter web test`).
_RUNNER_VALUE_FLAGS = {
    "npm": {"--prefix", "-w", "--workspace"}, "pnpm": {"-C", "--dir", "-F", "--filter"}, "yarn": {"--cwd"},
    "bun": {"--cwd", "--filter"}, "go": {"-C"}, "cargo": {"--manifest-path", "--config", "-Z"},
    "make": {"-C", "--directory", "-f", "--file", "-j", "-l", "-I", "-o", "-W"},
    "mvn": {"-pl", "--projects", "-f", "--file", "-P", "-s", "-gs", "-T", "-rf"},
    "gradle": {"-p", "--project-dir", "-b", "-c", "-x", "--exclude-task"}}
_RUNNER_VALUE_FLAGS["./gradlew"] = _RUNNER_VALUE_FLAGS["gradle"]
_COUNTS = {"-j", "-l"}  # make's job and load counts are optional: `make -j test` runs the tests
# Shell words that open a segment before its command: `for f in a; do pytest $f; done`, `if pytest; then ...`.
_KEYWORDS = {"do", "then", "else", "elif", "if", "while", "until", "!", "{"}
_SHELLS = {"sh", "bash", "zsh", "dash"}
# A test or CI script, run by a shell or by its path: scripts/ci/verify.sh, ./run_tests.sh, unit-tests.sh. A deploy
# or release script named after CI (ci-deploy.sh, ci_publish.sh) is not one.
_SCRIPT_KIND = r"(?:all|unit|units|e2e|integration|integ|smoke|local|suite|py|python|go|js)"
_TEST_SCRIPT = re.compile(rf"(?:run[_-]?)?(?:{_SCRIPT_KIND}[_-])?(?:tests?|verify|checks?|ci)(?:[_-]{_SCRIPT_KIND})?"
                          r"\.(?:sh|bash)")
# A runner asked only to describe itself or list its tests runs none: pytest --version, jest --listTests.
_PROBE_FLAGS = {"--version", "--help", "-h", "--collect-only", "--co", "--listTests", "--list", "--list-tests",
                "-list", "--dry-run"}
_PROBE_BY_RUNNER = {"tox": {"-l", "-a", "--listenvs", "--listenvs-all"}, "nox": {"-l", "--list-sessions"}}
_SEGMENT = re.compile(r"&&|\|\||[;|\n]")
_HEREDOC = re.compile(r"<<(-?)[ \t]*(['\"]?)([A-Za-z_\\][\w.\\-]*)\2")
_LONG = 20_000  # characters: a longer segment (a script in `python -c`) is split on spaces, not by shlex, which is slow


def _segments(command: str) -> list[str]:
    """The command's `&&`, `||`, `;`, `|`, `&` and newline segments, read as a shell reads them: a separator inside
    quotes or `$(...)` is text, a here-document's body and a comment are skipped (a commit message saying "then pytest
    passes" is not a test run), and a backslash-newline joins lines. An unclosed quote runs to the end, as in a
    clipped command."""
    command = re.sub(r"\\\r?\n", "", command)
    out: list[str] = []
    cur: list[str] = []
    pending: list[tuple[str, bool]] = []  # here-documents whose bodies start after this line
    stack: list[str] = []  # open quotes ("'", '"', "$'"), substitutions ("(") and arithmetic ("A")
    i, n = 0, len(command)
    while i < n:
        c, top = command[i], stack[-1] if stack else ""
        if top in ("'", '"', "$'"):
            if c == "\\" and top != "'" and i + 1 < n:
                cur.append(command[i:i + 2])
                i += 2
                continue
            if c == top[-1]:
                stack.pop()
            elif top == '"' and command.startswith("$(", i):
                stack.append("A" if command.startswith("$((", i) else "(")
                cur.append(command[i:i + 2])
                i += 2
                continue
            cur.append(c)
            i += 1
            continue
        if top == "A":  # $(( 1 << y )): only parentheses count
            if c == "(":
                stack.append("A")
            elif c == ")":
                stack.pop()
            cur.append(c)
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            cur.append(command[i:i + 2])
            i += 2
            continue
        if command.startswith("$((", i):
            stack += ["A", "A"]
            cur.append("$((")
            i += 3
            continue
        if command.startswith("$(", i) or (c == "(" and top == "("):
            stack.append("(")
        elif c == ")" and top == "(":
            stack.pop()
        elif command.startswith("$'", i):
            stack.append("$'")
            cur.append("$'")
            i += 2
            continue
        elif c in "'\"":
            stack.append(c)
        elif c == "#" and (not cur or cur[-1] in (" ", "\t", "\n", "\r")):
            j = command.find("\n", i)
            i = n if j < 0 else j
            continue
        elif command.startswith("<<<", i):
            cur.append("<<<")
            i += 3
            continue
        elif command.startswith("<<", i) and (m := _HEREDOC.match(command, i)):
            pending.append((m.group(3).replace("\\", ""), m.group(1) == "-"))
            cur.append(m.group(0))
            i = m.end()
            continue
        if c == "\n" and pending:  # the bodies follow this line, each up to its delimiter line
            k = i
            for delim, tabs in pending:
                while k < n:
                    j = command.find("\n", k + 1)
                    line = command[k + 1:n if j < 0 else j].rstrip("\r")
                    k = n if j < 0 else j
                    if (line.lstrip("\t") if tabs else line) == delim:
                        break
            pending = []
            if stack:
                cur.append("\n")
            else:
                out.append("".join(cur))
                cur = []
            i = k + 1
            continue
        sep = None if stack else next((x for x in ("&&", "||", ";;", ";", "|", "\n") if command.startswith(x, i)),
                                      None)
        if not sep and not stack and c == "&" and command[i - 1:i] not in ("<", ">") and command[i + 1:i + 2] != ">":
            sep = "&"  # sleep 1 & pytest; not 2>&1 or &>log
        if sep:
            out.append("".join(cur))
            cur = []
            i += len(sep)
            continue
        cur.append(c)
        i += 1
    out.append("".join(cur))
    return out


def _words(segment: str) -> list[str]:
    import shlex

    try:
        if len(segment) > _LONG:
            raise ValueError("too long for shlex")
        words = shlex.split(segment)
    except ValueError:
        words = segment.split()
    while words and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", words[0]):  # FOO=bar cmd
        words = words[1:]
    return words


def _takes_value(flag: str, values: set[str], cluster: bool = True) -> bool:
    """Whether `flag` takes the next word as its value; in a cluster (`sudo -iu ci`, `bash -euo pipefail`) the
    last letter decides. A runner's own flags aren't read as clusters: mvn's `-ff` is one flag, and make's `-sj`
    takes no value."""
    return flag in values or cluster and bool(re.fullmatch(r"-[A-Za-z]{2,}", flag)) and f"-{flag[-1]}" in values


def _skip_flags(words: list[str], takes_value: set[str]) -> list[str]:
    """`words` past the leading flags, a flag's value with it when the flag takes one (`--project svc`), a timeout's
    duration and env's assignments."""
    while words and (words[0].startswith("-") or re.fullmatch(r"\d+(\.\d+)?[smhd]?|[A-Za-z_]\w*=.*", words[0])):
        words = words[2:] if _takes_value(words[0], takes_value) else words[1:]
    return words


def _positional(words: list[str], values: set[str]) -> list[str]:
    """A runner's arguments that aren't flags or a flag's value (`make -C svc test` -> ["test"])."""
    out: list[str] = []
    i = 0
    while i < len(words):
        w = words[i]
        if not w.startswith("-") or w == "-":
            out.append(w)
        elif (_takes_value(w, values, cluster=False) and i + 1 < len(words)
              and not (w in _COUNTS and not words[i + 1].isdigit())):
            i += 1
        i += 1
    return out


def _op(words: list[str], depth: int = 0) -> list[str]:
    while words and words[0] in _KEYWORDS:
        words = words[1:]
    for _ in range(4):  # uv run pytest, sudo -E npx jest, timeout 60 make test
        if not words:
            return []
        head = words[0].rsplit("/", 1)[-1] if words[0] != "./gradlew" else words[0]
        if head in _WRAPPERS and len(words) > 1 and not (head == "pnpm" and words[1] in _TEST_SUBCOMMANDS["pnpm"]):
            sub, values = _WRAPPERS[head], _WRAPPER_VALUE_FLAGS.get(head, set())
            rest = words[1:]
            if sub is not None:
                rest = _skip_flags(rest, values)  # uv --project svc run pytest
                if not rest or rest[0] != sub:
                    break
                rest = rest[1:]
            words = _skip_flags(rest, values)
            continue
        break
    if not words:
        return []
    head = words[0].rsplit("/", 1)[-1] if words[0] != "./gradlew" else words[0]
    args = _positional(words[1:], _RUNNER_VALUE_FLAGS.get(head, set()))
    if head == "git":
        sub = next((w for i, w in enumerate(words[1:], 1) if not w.startswith("-")
                    and words[i - 1] not in ("-c", "-C")), None)
        op = {"commit": "git.commit", "push": "git.push", "rm": "delete"}.get(sub or "")
        return [op] if op else []
    if head == "gh" and args[:2] == ["pr", "create"]:
        return ["pr.open"]
    if head in ("rm", "rmdir", "unlink", "shred") or (head == "find" and "-delete" in words):
        return ["delete"]
    probe = bool((_PROBE_FLAGS | _PROBE_BY_RUNNER.get(head, set())).intersection(words[1:]))
    test: list[str] = [] if probe else ["test"]
    module = words[1:]
    if head == "coverage" and module[:1] == ["run"]:
        module = module[1:]  # coverage run -m pytest
    while module and module[0].startswith("-") and module[0] != "-m":  # python -u -m pytest
        module = module[2:] if module[0] in ("-W", "-X", "--source", "--rcfile", "--omit", "--include",
                                             "--data-file", "--context", "--concurrency") else module[1:]
    if head == "vitest" and args[:1] == ["list"]:
        return []
    if head in _TEST_PROGRAMS or (head.startswith("python") or head == "coverage") and module[:2] in (
            ["-m", "pytest"], ["-m", "unittest"]):
        return test
    if head in _TEST_SUBCOMMANDS and args and (args[0] in _TEST_SUBCOMMANDS[head] or (
            head in ("npm", "pnpm", "yarn", "bun") and args[0] == "run" and len(args) > 1
            and args[1].split(":")[0] in ("test", "tests"))):
        return test
    if head in _SHELLS:
        rest = _skip_flags(words[1:], _WRAPPER_VALUE_FLAGS[head])
        if any(re.fullmatch(r"-[A-Za-z]*c[A-Za-z]*", o) for o in words[1:len(words) - len(rest)]):
            return shell_ops(rest[0], depth + 1) if rest and depth < 3 else []  # bash -ec './ci.sh'
        script = rest[:1]
    else:
        script = words[:1] if "/" in words[0] else []
    if script and _TEST_SCRIPT.fullmatch(script[0].rsplit("/", 1)[-1]):
        return test
    return []


def shell_ops(command: str | None, depth: int = 0) -> list[str]:
    """What a shell command does, in order: `test`, `git.commit`, `git.push`, `pr.open`, `delete`."""
    out: list[str] = []
    for seg in _segments(command or ""):
        for op in _op(_words(seg.strip().lstrip("(").rstrip(")")), depth):
            if op not in out:
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
