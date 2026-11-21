"""KAN-280: the data plane needs no download. A connection sets `TimeZone = 'UTC'`, which needs DuckDB's icu
extension; where icu isn't built in, DuckDB fetches it from extensions.duckdb.org on connect, and a laptop or CI
runner that can't reach that host fails every command. The duckdb wheels flightdeck locks link icu (and parquet and
json) in, on every platform they ship, so these tests fail on a bump that would need the network again."""

from __future__ import annotations

from typing import Any

import duckdb

from flightdeck.dataplane import duck

NO_DOWNLOAD: dict[str, Any] = {"autoinstall_known_extensions": False, "autoload_known_extensions": False}


def test_the_extensions_the_data_plane_uses_are_built_in():
    rows = duckdb.connect(config=NO_DOWNLOAD).execute(
        "select extension_name from duckdb_extensions() where install_mode = 'STATICALLY_LINKED'").fetchall()
    assert {"icu", "parquet", "json"} <= {r[0] for r in rows}


def test_a_connection_and_a_utc_week_need_no_extension_download(tmp_path, monkeypatch):
    real = duckdb.connect
    monkeypatch.setattr(duckdb, "connect", lambda *a, **k: real(*a, **{**k, "config": {**k.get("config", {}),
                                                                                      **NO_DOWNLOAD}}))
    con = duck.connect(str(tmp_path))  # an empty data plane: every table an empty view
    assert con.execute("select current_setting('TimeZone')").fetchone() == ("UTC",)
    week = con.execute("select date_trunc('week', timestamptz '2026-11-15 23:30:00-05')::varchar").fetchone()
    assert week == ("2026-11-16 00:00:00+00",)  # Sunday 23:30 in New York is Monday in UTC
    assert con.execute("select count(*) from runs").fetchone() == (0,)
