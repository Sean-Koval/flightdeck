"""DuckDB views over a `flightdeck.parquet/v1` directory: a local path or a `gs://` URI."""

from __future__ import annotations

import duckdb

from flightdeck.dataplane.schema import DERIVED, TABLES


def connect(uri: str) -> duckdb.DuckDBPyConnection:
    """An in-memory DuckDB with one view per table that has data under `<uri>/<table>/dt=*/*.parquet`.

    `gs://` URIs read through DuckDB's httpfs with a GCS secret (HMAC keys or credential chain) the caller has set up;
    flightdeck itself holds no credentials (ADR-0001).
    """
    con = duckdb.connect()
    base = uri.rstrip("/")
    if base.startswith(("gs://", "s3://")):
        con.execute("INSTALL httpfs; LOAD httpfs;")
    for name in {**TABLES, **DERIVED}:
        glob = f"{base}/{name}/dt=*/*.parquet"
        if con.execute("select count(*) from glob(?)", [glob]).fetchone() == (0,):
            continue
        con.execute(
            f"create view {name} as select * from read_parquet('{glob}', hive_partitioning=true, union_by_name=true)"
        )
    return con
