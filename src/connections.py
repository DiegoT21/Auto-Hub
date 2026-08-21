from __future__ import annotations

import json
import sqlite3
from copy import deepcopy
from pathlib import Path
from typing import Any

import mysql.connector
from mysql.connector import MySQLConnection

try:
    import mysql.connector.locales.eng.client_error  # PyInstaller: mensajes de error MySQL
    import mysql.connector.plugins.mysql_native_password
except Exception:
    pass

from src.paths import app_root

ROOT = app_root()
DEFAULT_CONNECTIONS_PATH = ROOT / "config" / "connections.json"
VIEW_SQL_PATH = ROOT / "scripts" / "create_autohub_view.sql"
MYSQL_CONNECT_TIMEOUT = 8
MYSQL_READ_TIMEOUT = 20

SCHEMA_LABELS = {
    "normalized_tables": "Tablas demo (facturas)",
    "pskloud_canonical": "PsKloud MySQL (operti/opermv)",
}

SCHEMA_PRESETS: dict[str, dict[str, Any]] = {
    "normalized_tables": {
        "source": "normalized_tables",
        "tables": {
            "invoices": "facturas",
            "invoice_lines": "facturas_detalle",
            "customers": "clientes",
        },
        "filter_unexported": True,
        "exported_field": "exportado",
        "use_id_watermark": True,
    },
    "pskloud_canonical": {
        "source": "canonical_view",
        "canonical_view": "autohub_v_facturas",
        "filter_unexported": False,
        "use_id_watermark": False,
    },
}


def load_connections(path: Path = DEFAULT_CONNECTIONS_PATH) -> dict[str, Any]:
    if not path.exists():
        return {"active_id": "local_sqlite", "connections": []}
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def save_connections(data: dict[str, Any], path: Path = DEFAULT_CONNECTIONS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)


def save_config(config: dict[str, Any], config_path: Path) -> None:
    with config_path.open("w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=2, ensure_ascii=False)


def get_connection(data: dict[str, Any], conn_id: str | None = None) -> dict[str, Any] | None:
    target = conn_id or data.get("active_id")
    for item in data.get("connections", []):
        if item.get("id") == target:
            return item
    return None


def connection_summary(profile: dict[str, Any]) -> str:
    driver = profile.get("driver", "sqlite")
    if driver == "sqlite":
        return f"SQLite · {profile.get('sqlite_path', '')}"
    return f"MySQL · {profile.get('host', '127.0.0.1')}:{profile.get('port', 3306)} / {profile.get('database', '')}"


def apply_profile_to_config(config: dict[str, Any], profile: dict[str, Any], root: Path) -> dict[str, Any]:
    updated = deepcopy(config)
    db = updated.setdefault("database", {})
    extraction = updated.setdefault("extraction", {})

    driver = profile.get("driver", "sqlite")
    db["driver"] = driver

    if driver == "sqlite":
        db["sqlite_path"] = profile.get("sqlite_path", "data/pskloud_demo.db")
    else:
        db["host"] = profile.get("host", "127.0.0.1")
        db["port"] = int(profile.get("port", 3306))
        db["database"] = profile.get("database", "")
        db["user"] = profile.get("user", "")
        db["password"] = profile.get("password", "")
        db.setdefault("charset", "utf8mb4")

    schema = profile.get("schema", "normalized_tables")
    preset = deepcopy(SCHEMA_PRESETS.get(schema, SCHEMA_PRESETS["normalized_tables"]))
    if schema == "pskloud_canonical" and profile.get("canonical_view"):
        preset["canonical_view"] = profile["canonical_view"]

    for key, value in preset.items():
        extraction[key] = value

    return updated


def _connect_profile(profile: dict[str, Any], root: Path) -> Any:
    driver = profile.get("driver", "sqlite")
    if driver == "sqlite":
        db_path = root / profile.get("sqlite_path", "data/pskloud_demo.db")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    return mysql.connector.connect(
        host=profile.get("host", "127.0.0.1"),
        port=int(profile.get("port", 3306)),
        database=profile.get("database", ""),
        user=profile.get("user", ""),
        password=profile.get("password", ""),
        charset="utf8mb4",
        connection_timeout=MYSQL_CONNECT_TIMEOUT,
        autocommit=True,
        use_pure=True,
        auth_plugin="mysql_native_password",
    )


def _view_exists_mysql(conn: MySQLConnection, view_name: str) -> bool:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) FROM information_schema.views WHERE table_schema = DATABASE() AND table_name = %s",
        (view_name,),
    )
    count = cursor.fetchone()[0]
    cursor.close()
    return count > 0


def ensure_pskloud_view(profile: dict[str, Any], root: Path) -> tuple[bool, str]:
    if profile.get("driver") != "mysql":
        return False, "Solo aplica a conexiones MySQL."

    view_name = profile.get("canonical_view", "autohub_v_facturas")
    if not VIEW_SQL_PATH.exists():
        return False, f"No se encontro {VIEW_SQL_PATH.name}"

    conn = _connect_profile(profile, root)
    try:
        if not isinstance(conn, MySQLConnection):
            return False, "Conexion invalida."

        sql_text = VIEW_SQL_PATH.read_text(encoding="utf-8")
        statements = [part.strip() for part in sql_text.split(";") if part.strip()]
        cursor = conn.cursor()
        for statement in statements:
            if statement.upper().startswith("USE "):
                continue
            try:
                cursor.execute(statement)
            except Exception as exc:
                preview = statement.splitlines()[0][:80]
                raise RuntimeError(f"Error SQL ({preview}...): {exc}") from exc
        conn.commit()
        cursor.close()

        if not _view_exists_mysql(conn, view_name):
            return False, f"No se pudo verificar la vista {view_name} despues de crearla."
        return True, f"Vista {view_name} creada correctamente en {profile.get('database', '')}."
    except Exception as exc:
        return False, str(exc)
    finally:
        conn.close()


def _ping_mysql(conn: MySQLConnection) -> str:
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT DATABASE()")
        db_name = cursor.fetchone()[0] or ""
        cursor.execute("SELECT 1")
        cursor.fetchone()
        return db_name
    finally:
        cursor.close()


def _fast_fac_count_mysql(conn: MySQLConnection, view_name: str) -> int | None:
    """Cuenta rapida sin escanear toda la vista si operti existe."""
    if _table_exists_mysql(conn, "operti"):
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT COUNT(*) FROM operti WHERE tipodoc = %s AND totalfinal > 0",
                ("FAC",),
            )
            return int(cursor.fetchone()[0])
        finally:
            cursor.close()
    if not _view_exists_mysql(conn, view_name):
        return None
    cursor = conn.cursor()
    try:
        cursor.execute(f"SELECT COUNT(*) FROM (SELECT 1 FROM {view_name} LIMIT 50001) t")
        return int(cursor.fetchone()[0])
    finally:
        cursor.close()


def test_connection(profile: dict[str, Any], root: Path, *, quick: bool = True) -> tuple[bool, str]:
    driver = profile.get("driver", "sqlite")
    schema = profile.get("schema", "normalized_tables")

    try:
        conn = _connect_profile(profile, root)
    except Exception as exc:
        return False, f"No se pudo conectar: {exc}"

    try:
        if driver == "sqlite":
            db_path = root / profile.get("sqlite_path", "data/pskloud_demo.db")
            if not db_path.exists():
                return False, f"Archivo no encontrado: {db_path}"
            row = conn.execute("SELECT COUNT(*) AS n FROM facturas").fetchone()
            count = row["n"] if row else 0
            return True, f"Conexion OK · {count} factura(s) en tablas demo."

        if not isinstance(conn, MySQLConnection):
            return False, "Conexion MySQL invalida."

        db_name = _ping_mysql(conn)

        if schema == "pskloud_canonical":
            view_name = profile.get("canonical_view", "autohub_v_facturas")
            if not _view_exists_mysql(conn, view_name):
                if _table_exists_mysql(conn, "operti"):
                    return (
                        False,
                        f"Conectado a {db_name}, pero falta la vista {view_name}. "
                        "Usa 'Crear vista' en el dialogo de conexion.",
                    )
                return False, f"Conectado a {db_name}, pero no se encontraron tablas PsKloud (operti)."

            if quick:
                count = _fast_fac_count_mysql(conn, view_name)
                if count is None:
                    return True, f"Conexion OK a {db_name} · vista {view_name} disponible."
                suffix = "+" if count > 50000 else ""
                shown = min(count, 50000) if count > 50000 else count
                return True, f"Conexion OK · ~{shown}{suffix} factura(s) FAC en {db_name}."

            cursor = conn.cursor()
            cursor.execute(f"SELECT COUNT(DISTINCT factura_id) FROM {view_name}")
            count = cursor.fetchone()[0]
            cursor.close()
            return True, f"Conexion OK · {count} factura(s) FAC via {view_name}."

        if _table_exists_mysql(conn, "facturas"):
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM facturas")
            count = cursor.fetchone()[0]
            cursor.close()
            return True, f"Conexion OK · {count} factura(s) en tablas demo."

        if _table_exists_mysql(conn, "operti"):
            count = _fast_fac_count_mysql(conn, profile.get("canonical_view", "autohub_v_facturas"))
            count_txt = count if count is not None else "?"
            return (
                True,
                f"Conectado a {db_name} · {count_txt} facturas FAC en operti. "
                "Configura esquema PsKloud y crea la vista.",
            )

        return True, f"Conexion OK a {db_name}, pero no se detectaron tablas de facturas."
    except Exception as exc:
        return False, str(exc)
    finally:
        conn.close()


def _table_exists_mysql(conn: MySQLConnection, table_name: str) -> bool:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = DATABASE() AND table_name = %s",
        (table_name,),
    )
    exists = cursor.fetchone()[0] > 0
    cursor.close()
    return exists


def activate_connection(
    conn_id: str,
    *,
    connections_path: Path,
    config_path: Path,
    root: Path,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    data = load_connections(connections_path)
    profile = get_connection(data, conn_id)
    if not profile:
        raise ValueError(f"Conexion no encontrada: {conn_id}")

    data["active_id"] = conn_id
    save_connections(data, connections_path)

    from src.db import load_config

    config = load_config(config_path)
    config = apply_profile_to_config(config, profile, root)
    save_config(config, config_path)
    return data, config, connection_summary(profile)


def new_connection_id(existing: list[dict[str, Any]]) -> str:
    used = {item.get("id") for item in existing}
    index = 1
    while f"conn_{index}" in used:
        index += 1
    return f"conn_{index}"
