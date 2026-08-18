"""Inspecciona tablas/columnas del backup MySQL para mapear la vista canonica."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.db import connect, fetch_all, load_config


def _print_rows(title: str, rows: list[dict[str, Any]]) -> None:
    print(f"\n== {title} ==")
    if not rows:
        print("(sin filas)")
        return
    for row in rows:
        print(row)


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspecciona el backup MySQL configurado.")
    parser.add_argument(
        "--config",
        default=str(ROOT / "config" / "config.mysql-backup.example.json"),
        help="Ruta al config MySQL.",
    )
    parser.add_argument(
        "--tables",
        default="opermv,operti",
        help="Tablas separadas por coma a inspeccionar.",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    config = load_config(config_path)
    db_name = config["database"]["database"]
    tables = [item.strip() for item in args.tables.split(",") if item.strip()]

    conn = connect(config, ROOT)
    try:
        for table in tables:
            columns = fetch_all(
                conn,
                """
                SELECT
                    COLUMN_NAME AS column_name,
                    DATA_TYPE AS data_type,
                    IS_NULLABLE AS is_nullable
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = ?
                  AND TABLE_NAME = ?
                ORDER BY ORDINAL_POSITION
                """,
                (db_name, table),
            )
            _print_rows(f"Columnas {db_name}.{table}", columns)

            sample = fetch_all(conn, f"SELECT * FROM {db_name}.{table} LIMIT 5")
            _print_rows(f"Muestra {db_name}.{table}", sample)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
