from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import mysql.connector
from mysql.connector import MySQLConnection


def load_config(config_path: Path) -> dict[str, Any]:
    with config_path.open(encoding="utf-8") as handle:
        return json.load(handle)


def connect(config: dict[str, Any], root: Path) -> Any:
    db = config["database"]
    driver = db.get("driver", "sqlite")

    if driver == "sqlite":
        db_path = root / db["sqlite_path"]
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    if driver == "mysql":
        return mysql.connector.connect(
            host=db["host"],
            port=db.get("port", 3306),
            database=db["database"],
            user=db["user"],
            password=db["password"],
            charset=db.get("charset", "utf8mb4"),
            connection_timeout=8,
            autocommit=True,
        )

    raise ValueError(f"Driver no soportado: {driver}")


def _adapt_query_for_connection(conn: Any, query: str) -> str:
    if isinstance(conn, MySQLConnection):
        return query.replace("?", "%s")
    return query


def fetch_all(conn: Any, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    if isinstance(conn, sqlite3.Connection):
        cursor = conn.execute(_adapt_query_for_connection(conn, query), params)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    if isinstance(conn, MySQLConnection):
        cursor = conn.cursor(dictionary=True)
        cursor.execute(_adapt_query_for_connection(conn, query), params)
        rows = cursor.fetchall()
        cursor.close()
        return list(rows)

    raise TypeError("Conexión no soportada")
