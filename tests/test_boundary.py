"""ADR-0001: no sandbox-provider or credential code in flightdeck, apart from ported/ and the local runner."""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "flightdeck"
FORBIDDEN = {"docker", "kubernetes", "e2b", "google.cloud.container"}
ALLOWED = ("ported", "runners/local")


def test_no_sandbox_sdk_imports() -> None:
    offenders = []
    for path in SRC.rglob("*.py"):
        rel = path.relative_to(SRC).as_posix()
        if rel.startswith(ALLOWED):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else ([node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            )
            offenders += [f"{rel}: {n}" for n in names if any(n == f or n.startswith(f + ".") for f in FORBIDDEN)]
    assert not offenders, offenders
