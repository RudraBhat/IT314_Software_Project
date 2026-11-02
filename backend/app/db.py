"""PostgreSQL connection pool and transaction helper (psycopg 3)."""

import json
from collections.abc import Iterator
from contextlib import contextmanager

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import set_json_dumps
from psycopg_pool import ConnectionPool

from app.config import get_settings

# UUIDs, datetimes and Decimals inside JSONB payloads (audit before/after state).
set_json_dumps(lambda obj: json.dumps(obj, default=str))

_pool: ConnectionPool | None = None


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        conn_str = get_settings().require("database_url")
        if "connect_timeout" not in conn_str:
            sep = "&" if "?" in conn_str else "?"
            conn_str = f"{conn_str}{sep}connect_timeout=10"
        _pool = ConnectionPool(
            conn_str,
            min_size=1,
            max_size=10,
            kwargs={"row_factory": dict_row},
            open=True,
        )
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def transaction() -> Iterator[Connection]:
    """One connection, one transaction: commits on success, rolls back on any exception."""
    with get_pool().connection(timeout=10.0) as conn, conn.transaction():
        yield conn
