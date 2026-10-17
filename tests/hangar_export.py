"""Shared fixtures for the ingest, compare and report tests: the synthetic experiment export
(`scripts/fixture_export.py`) and a data plane ingested from it. Import the fixtures into a test module to use them."""

from __future__ import annotations

import importlib.util
import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

from flightdeck.dataplane import flatten, ingest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("fixture_export", ROOT / "scripts" / "fixture_export.py")
assert _spec and _spec.loader
fixture_export = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fixture_export)
EXP = fixture_export.EXP
CREATED = fixture_export.CREATED


@pytest.fixture(scope="module")
def export_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    d = tmp_path_factory.mktemp("export")
    fixture_export.build(d)
    return d


@pytest.fixture(scope="module")
def plane(export_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> str:
    out = str(tmp_path_factory.mktemp("plane"))
    ingest.write_unit(ingest.read_export(export_dir), out, f"experiment-{EXP}")
    return out


class Recorded:
    """A local stand-in for hangar's REST API serving recorded responses: `routes` maps a path (with its query) to a
    JSON file. Records each request's path and Authorization header."""

    def __init__(self, routes: dict[str, Path]):
        self.routes, self.requests = routes, []
        recorded = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                parts = urlsplit(self.path)
                path = unquote(parts.path) + (f"?{parts.query}" if parts.query else "")
                recorded.requests.append((path, self.headers.get("Authorization")))
                f = recorded.routes.get(path)
                body = f.read_bytes() if f else json.dumps({"error": "not found"}).encode()
                self.send_response(200 if f else 404)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def __enter__(self) -> Recorded:
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.server.shutdown()
        self.server.server_close()


def export_routes(d: Path) -> dict[str, Path]:
    """The REST paths `hangar experiment export` reads, mapped to the files it wrote."""
    index = json.loads((d / "index.json").read_text())
    routes = {f"/api/experiments/{index['id']}": d / "index.json"}
    for t in index["trials"]:
        for name, link in (t.get("links") or {}).items():
            if name in ("manifest", "trace") and link:
                routes[link] = d / "trials" / flatten.trial_ref(t).replace("/", "__") / f"{name}.json"
    return routes


@pytest.fixture
def no_proxy(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Reach the local recorded server directly, not through an HTTP(S) proxy from the environment."""
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("NO_PROXY", "*")
    yield
