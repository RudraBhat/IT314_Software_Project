"""PostgreSQL connection pool and transaction helper (psycopg 3)."""

import json
import logging
import time
import weakref
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import set_json_dumps
from psycopg_pool import ConnectionPool

from app.config import get_settings

# UUIDs, datetimes and Decimals inside JSONB payloads (audit before/after state).
set_json_dumps(lambda obj: json.dumps(obj, default=str))

_pool: ConnectionPool | None = None

# A pooled connection that sat idle may have been closed by the server (Neon suspends idle compute),
# so it is pinged before reuse. A connection used a moment ago is not: each ping is a full network
# round trip, which on a remote database costs as much as the query itself.
_IDLE_PING_SECONDS = 30.0
_last_used: "weakref.WeakKeyDictionary[Connection, float]" = weakref.WeakKeyDictionary()


def _check_if_idle(conn: Connection) -> None:
    last = _last_used.get(conn)
    if last is not None and time.monotonic() - last > _IDLE_PING_SECONDS:
        ConnectionPool.check_connection(conn)


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        conn_str = get_settings().require("database_url")
        if "connect_timeout" not in conn_str:
            sep = "&" if "?" in conn_str else "?"
            conn_str = f"{conn_str}{sep}connect_timeout=30"
        _pool = ConnectionPool(
            conn_str,
            min_size=2,
            max_size=10,
            kwargs={"row_factory": dict_row},
            open=True,
            check=_check_if_idle,
            max_idle=180.0,
            max_lifetime=1800.0,
        )
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


# Work that must only happen once a transaction has really committed (emails, for example),
# keyed by the connection that transaction() handed out.
_after_commit: dict[int, list[Callable[[], None]]] = {}


def after_commit(conn: Connection, callback: Callable[[], None]) -> None:
    """Run `callback` after the current transaction() on `conn` commits; drop it on rollback.

    A connection that did not come from transaction() (a test or CLI connection) runs it at once.
    """
    pending = _after_commit.get(id(conn))
    if pending is None:
        callback()
    else:
        pending.append(callback)


@contextmanager
def read_only() -> Iterator[Connection]:
    """A connection in autocommit mode for read-only work.

    Without BEGIN and COMMIT a single query costs one network round trip instead of three. Each
    statement is its own transaction, so use it only for SELECTs that need no shared snapshot and
    never for writes or locking reads (those must share `transaction()`).
    """
    with get_pool().connection(timeout=30.0) as conn:
        conn.autocommit = True
        try:
            yield conn
        finally:
            conn.autocommit = False
            _last_used[conn] = time.monotonic()


@contextmanager
def transaction() -> Iterator[Connection]:
    """One connection, one transaction: commits on success, rolls back on any exception."""
    with get_pool().connection(timeout=30.0) as conn:
        _after_commit[id(conn)] = []
        try:
            with conn.transaction():
                yield conn
            pending = _after_commit.pop(id(conn), [])
        except BaseException:
            _after_commit.pop(id(conn), None)
            raise
        finally:
            _last_used[conn] = time.monotonic()
    for callback in pending:
        try:
            callback()
        except Exception:  # after-commit work must never turn a committed request into an error
            logging.getLogger("drch.db").warning("An after-commit callback failed", exc_info=True)
