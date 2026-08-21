from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import mysql.connector
from mysql.connector import MySQLConnection

try:
    import mysql.connector.locales.eng.client_error
    import mysql.connector.plugins.mysql_native_password
except Exception:
    pass


def load_config(config_path: Path) -> dict[str, Any]:
    with config_path.open(encoding="utf-8") as handle:
        return json.load(handle)


def connect(config: dict[str, Any], root: Path) -> Any:
    db = config["database"]
    driver = db.get("driver", "sqlite")

    if driver == "sqlite":
        db_path = root / db["sqlite_path"]
        db_path.parent.mkdir(parents=True, exist_ok=True)
        if not db_path.exists():
            raise FileNotFoundError(
                "No hay base SQLite local.\n"
                "Elige 'Produccion — admin000002' y pulsa Usar conexion, luego Buscar."
            )
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    if driver == "mysql":
        host = str(db.get("host") or "").strip()
        try:
            port = int(db.get("port") or 3306)
        except (TypeError, ValueError):
            port = 3306
        try:
            return mysql.connector.connect(
                host=host,
                port=port,
                database=db["database"],
                user=db["user"],
                password=db["password"],
                charset=db.get("charset", "utf8mb4"),
                connection_timeout=8,
                autocommit=True,
                use_pure=True,
                auth_plugin="mysql_native_password",
            )
        except Exception as exc:
            raise ConnectionError(
                f"No se pudo conectar a MySQL {host}:{port}. "
                "Revisa host/puerto, que el PC tenga red, y pulsa Usar conexion. "
                f"Detalle: {exc}"
            ) from exc

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
