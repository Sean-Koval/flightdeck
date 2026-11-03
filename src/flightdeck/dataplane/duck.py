"""DuckDB views over a `flightdeck.parquet/v1` directory: a local path or a `gs://` URI."""

from __future__ import annotations

from importlib import import_module, resources, util

import duckdb

from flightdeck.dataplane.schema import ALL, DERIVED, to_table


def connect(uri: str) -> duckdb.DuckDBPyConnection:
    """An in-memory DuckDB with one view per table over `<uri>/<table>/dt=*/*.parquet`; a table without files is an
    empty view of its schema, so queries need not check which tables exist. Plus metrics/process.sql's views.

    `gs://` URIs read through gcsfs when the `gcs` extra is installed (`pip install 'flightdeck[gcs]'`; it uses the
    caller's Google application-default credentials), else through DuckDB's httpfs with a GCS secret (HMAC keys) the
    caller has set up. Flightdeck itself holds no credentials (ADR-0001).
    """
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    base = uri.rstrip("/")
    if base.startswith("gs://") and util.find_spec("gcsfs"):
        con.register_filesystem(import_module("gcsfs").GCSFileSystem())
    elif base.startswith(("gs://", "s3://")):
        con.execute("INSTALL httpfs; LOAD httpfs;")
    for name in ALL:
        glob = f"{base}/{name}/dt=*/*.parquet"
        if con.execute("select count(*) from glob(?)", [glob]).fetchone() == (0,):
            if name not in DERIVED:  # derived tables (spec_results) stay absent until written, so readers can tell
                con.register(name, to_table(name, []))
            continue
        con.execute(
            f"create view {name} as select * from read_parquet('{glob}', hive_partitioning=true, union_by_name=true)"
        )
    con.execute(resources.files("flightdeck.metrics").joinpath("process.sql").read_text(encoding="utf-8"))
    return con
