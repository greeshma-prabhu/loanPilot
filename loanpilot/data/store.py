"""Swappable storage interfaces and the local SQLite implementation."""

from abc import ABC, abstractmethod
from contextlib import contextmanager
import math
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Iterator, Mapping, Sequence

import pandas as pd

from loanpilot.config import DATA_DIR, PROJECT_ROOT

SqlParams = Sequence[Any] | Mapping[str, Any]


class DataStore(ABC):
    """Storage contract for queryable LoanPilot demo data."""

    @abstractmethod
    def query(self, sql: str, params: SqlParams | None = None) -> pd.DataFrame:
        """Return the SQL result as a DataFrame."""

    @abstractmethod
    def execute(self, sql: str, params: SqlParams | None = None) -> int:
        """Execute one statement and return its affected row count."""

    @abstractmethod
    def table_counts(self) -> dict[str, int]:
        """Return row counts for the store's tables."""


class SQLiteStore(DataStore):
    """SQLite-backed local demo store; paths default to the project data folder."""

    def __init__(self, path: str | Path | None = None) -> None:
        requested_path = Path(path) if path is not None else DATA_DIR / "loanpilot.db"
        self.path = (
            requested_path
            if requested_path.is_absolute()
            else PROJECT_ROOT / requested_path
        )

    def _connect(self) -> sqlite3.Connection:
        """Open a configured database connection, creating its parent directory."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.create_function("POWER", 2, math.pow, deterministic=True)
        return connection

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """Yield one transaction-scoped connection and always close it."""
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def query(self, sql: str, params: SqlParams | None = None) -> pd.DataFrame:
        """Return a parameterized SQL query as a DataFrame."""
        with self.connection() as connection:
            return pd.read_sql_query(sql, connection, params=params)

    def execute(self, sql: str, params: SqlParams | None = None) -> int:
        """Execute a parameterized statement and return its affected row count."""
        with self.connection() as connection:
            cursor = connection.execute(sql, params if params is not None else ())
            return cursor.rowcount

    def execute_many(self, sql: str, rows: Iterable[Sequence[Any]]) -> int:
        """Bulk insert or update rows in one transaction."""
        with self.connection() as connection:
            cursor = connection.executemany(sql, rows)
            return cursor.rowcount

    def table_counts(self) -> dict[str, int]:
        """Return row counts for all base tables, excluding SQLite internals."""
        with self.connection() as connection:
            tables = connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
            return {
                row["name"]: connection.execute(
                    f'SELECT COUNT(*) FROM "{row["name"]}"'
                ).fetchone()[0]
                for row in tables
            }
