"""Reference solution (oracle) for the semver smoke task: Semantic Versioning 2.0.0 with node-semver range matching.

Never given to an agent. `solve.sh` copies it into the working directory, so the grader can be checked against a known
pass (and, through hangar's base check, a known fail without it)."""

from __future__ import annotations

import functools
import re
import sys

_ID = r"(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)"
_FULL = re.compile(rf"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-({_ID}(?:\.{_ID})*))?(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$")
_PART = r"(\d+|[xX*])"
_PARTIAL = re.compile(rf"^v?{_PART}?(?:\.{_PART})?(?:\.{_PART})?(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$")


def _ident(s: str) -> int | str:
    return int(s) if s.isdigit() else s


@functools.total_ordering
class Version:
    def __init__(self, major: int, minor: int, patch: int, prerelease: tuple = (), build: tuple = ()) -> None:
        self.major, self.minor, self.patch = major, minor, patch
        self.prerelease, self.build = tuple(prerelease), tuple(build)

    @classmethod
    def parse(cls, s: str) -> Version:
        m = _FULL.match(s.strip()) if isinstance(s, str) else None
        if not m:
            raise ValueError(f"invalid semantic version: {s!r}")
        pre = tuple(_ident(x) for x in m.group(4).split(".")) if m.group(4) else ()
        build = tuple(m.group(5).split(".")) if m.group(5) else ()
        return cls(int(m.group(1)), int(m.group(2)), int(m.group(3)), pre, build)

    def __str__(self) -> str:
        s = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            s += "-" + ".".join(str(x) for x in self.prerelease)
        if self.build:
            s += "+" + ".".join(self.build)
        return s

    def __repr__(self) -> str:
        return f"Version({str(self)!r})"

    def _key(self) -> tuple:
        # a release sorts after its prereleases; numeric identifiers sort before alphanumeric ones
        pre = tuple((0, x, "") if isinstance(x, int) else (1, 0, x) for x in self.prerelease)
        return (self.major, self.minor, self.patch, 0 if self.prerelease else 1, pre)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Version) and self._key() == other._key()

    def __lt__(self, other: Version) -> bool:
        return self._key() < other._key()

    def __hash__(self) -> int:
        return hash(self._key())

    def bump(self, part: str) -> Version:
        M, m, p, pre = self.major, self.minor, self.patch, self.prerelease
        if part == "major":
            return Version(M if (pre and m == 0 and p == 0) else M + 1, 0, 0)
        if part == "minor":
            return Version(M, m if (pre and p == 0) else m + 1, 0)
        if part == "patch":
            return Version(M, m, p if pre else p + 1)
        if part == "prerelease":
            if not pre:
                return Version(M, m, p + 1, (0,))
            ids = list(pre)
            for i in range(len(ids) - 1, -1, -1):
                if isinstance(ids[i], int):
                    ids[i] += 1
                    break
            else:
                ids.append(0)
            return Version(M, m, p, tuple(ids))
        raise ValueError(f"unknown part: {part!r}")


def _v(M: int, m: int, p: int, pre: tuple = ()) -> Version:
    return Version(M, m, p, pre)


_ZERO = (0,)  # node-semver's "-0": the lowest prerelease, so `<2.0.0-0` excludes 2.0.0's prereleases


def _partial(s: str) -> tuple[int | None, int | None, int | None, tuple]:
    m = _PARTIAL.match(s)
    if not m:
        raise ValueError(f"invalid range part: {s!r}")
    nums = [None if g is None or g in "xX*" else int(g) for g in m.groups()[:3]]
    for i in range(1, 3):  # anything after an x is an x
        if nums[i - 1] is None:
            nums[i] = None
    pre = tuple(_ident(x) for x in m.group(4).split(".")) if m.group(4) and nums[2] is not None else ()
    return nums[0], nums[1], nums[2], pre


def _comparators(tok: str) -> list[tuple[str, Version]]:
    op = re.match(r"^(<=|>=|<|>|=|~>?|\^)?", tok).group(0) or ""
    M, m, p, pre = _partial(tok[len(op):])
    if op in ("~", "~>"):
        if M is None:
            return []
        if m is None:
            return [(">=", _v(M, 0, 0)), ("<", _v(M + 1, 0, 0, _ZERO))]
        return [(">=", _v(M, m, p or 0, pre)), ("<", _v(M, m + 1, 0, _ZERO))]
    if op == "^":
        if M is None:
            return []
        if m is None:
            return [(">=", _v(M, 0, 0)), ("<", _v(M + 1, 0, 0, _ZERO))]
        if p is None:
            hi = _v(M + 1, 0, 0, _ZERO) if M else _v(0, m + 1, 0, _ZERO)
            return [(">=", _v(M, m, 0)), ("<", hi)]
        if M:
            hi = _v(M + 1, 0, 0, _ZERO)
        else:
            hi = _v(0, m + 1, 0, _ZERO) if m else _v(0, 0, p + 1, _ZERO)
        return [(">=", _v(M, m, p, pre)), ("<", hi)]
    if M is None:  # *, x, ""
        return [] if op in ("", "=", ">=", "<=") else [("<", _v(0, 0, 0, _ZERO))]
    if m is None or p is None:  # an x-range
        lo = _v(M, m or 0, 0)
        nxt = _v(M + 1, 0, 0, _ZERO) if m is None else _v(M, m + 1, 0, _ZERO)
        if op in ("", "="):
            return [(">=", lo), ("<", nxt)]
        if op == ">":
            return [(">=", _v(nxt.major, nxt.minor, 0))]
        if op == "<=":
            return [("<", nxt)]
        if op == "<":
            return [("<", _v(lo.major, lo.minor, 0, _ZERO))]
        return [(">=", lo)]
    return [(op or "=", _v(M, m, p, pre))]


def _hyphen(a: str, b: str) -> list[tuple[str, Version]]:
    M, m, p, pre = _partial(a)
    lo = [] if M is None else [(">=", _v(M, m or 0, p or 0, pre))]
    M, m, p, pre = _partial(b)
    if M is None:
        return lo
    if m is None:
        return lo + [("<", _v(M + 1, 0, 0, _ZERO))]
    if p is None:
        return lo + [("<", _v(M, m + 1, 0, _ZERO))]
    return lo + [("<=", _v(M, m, p, pre))]


def _sets(range_str: str) -> list[list[tuple[str, Version]]]:
    out = []
    for part in range_str.split("||"):
        part = re.sub(r"(<=|>=|<|>|=|~>?|\^)\s+", r"\1", part.strip())
        h = re.match(r"^(\S+)\s+-\s+(\S+)$", part)
        out.append(_hyphen(*h.groups()) if h else [c for tok in part.split() for c in _comparators(tok)])
    return out


_OPS = {"=": lambda a, b: a == b, "<": lambda a, b: a < b, ">": lambda a, b: a > b,
        "<=": lambda a, b: a <= b, ">=": lambda a, b: a >= b}


def satisfies(version: str | Version, range_str: str) -> bool:
    try:
        v = version if isinstance(version, Version) else Version.parse(version)
        sets = _sets(range_str)
    except ValueError:
        return False
    for cs in sets:
        if not all(_OPS[op](v, c) for op, c in cs):
            continue
        if not v.prerelease:
            return True
        # a prerelease matches only through a comparator on the same [major, minor, patch] that has a prerelease
        if any(c.prerelease and (c.major, c.minor, c.patch) == (v.major, v.minor, v.patch) for _, c in cs):
            return True
    return False


def main(argv: list[str]) -> int:
    if len(argv) >= 1 and argv[0] == "sort":
        for v in sorted(Version.parse(x) for x in argv[1:]):
            print(v)
        return 0
    if len(argv) == 3 and argv[0] == "satisfies":
        return 0 if satisfies(argv[1], argv[2]) else 1
    print("usage: semver.py sort V... | semver.py satisfies VERSION RANGE", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
