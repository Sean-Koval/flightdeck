"""DuckDB views over a `flightdeck.parquet/v1` directory: a local path or a `gs://` URI."""

from __future__ import annotations

import importlib
import importlib.util

import duckdb

from flightdeck.dataplane.schema import TABLES, to_table


def connect(uri: str) -> duckdb.DuckDBPyConnection:
    """An in-memory DuckDB with one view per table over `<uri>/<table>/dt=*/*.parquet`; a table without files is an
    empty view of its schema, so queries need not check which tables exist.

    `gs://` URIs read through gcsfs when the `gcs` extra is installed (`pip install 'flightdeck[gcs]'`; it uses the
    caller's Google application-default credentials), else through DuckDB's httpfs with a GCS secret (HMAC keys) the
    caller has set up. Flightdeck itself holds no credentials (ADR-0001).
    """
    con = duckdb.connect(config={"TimeZone": "UTC"})
    base = uri.rstrip("/")
    if base.startswith("gs://") and importlib.util.find_spec("gcsfs"):
        con.register_filesystem(importlib.import_module("gcsfs").GCSFileSystem())
    elif base.startswith(("gs://", "s3://")):
        con.execute("INSTALL httpfs; LOAD httpfs;")
    for name in TABLES:
        glob = f"{base}/{name}/dt=*/*.parquet"
        if con.execute("select count(*) from glob(?)", [glob]).fetchone() == (0,):
            con.register(name, to_table(name, []))
            continue
        con.execute(
            f"create view {name} as select * from read_parquet('{glob}', hive_partitioning=true, union_by_name=true)"
        )
    return con
