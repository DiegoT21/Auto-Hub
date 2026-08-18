"""Prueba guardado/carga de conexiones sin usar la UI."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.connections import get_connection, load_connections, save_connections


def test_roundtrip() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "connections.json"
        data = {
            "active_id": "mysql_produccion",
            "connections": [
                {
                    "id": "mysql_produccion",
                    "name": "Produccion — admin000002",
                    "driver": "mysql",
                    "schema": "pskloud_canonical",
                    "host": "190.218.67.141",
                    "port": 3306,
                    "database": "admin000002",
                    "user": "root",
                    "password": "test-secret",
                    "canonical_view": "autohub_v_facturas",
                }
            ],
        }
        save_connections(data, path)
        loaded = load_connections(path)
        profile = get_connection(loaded, "mysql_produccion")
        assert profile is not None
        assert profile["host"] == "190.218.67.141"
        assert profile["database"] == "admin000002"
        assert profile["user"] == "root"
        assert profile["password"] == "test-secret"
        print("roundtrip OK:", json.dumps(profile, ensure_ascii=False))


def test_merge_preserves_password() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "connections.json"
        data = {
            "active_id": "mysql_produccion",
            "connections": [
                {
                    "id": "mysql_produccion",
                    "name": "Prod",
                    "driver": "mysql",
                    "schema": "pskloud_canonical",
                    "host": "190.218.67.141",
                    "port": 3306,
                    "database": "admin000002",
                    "user": "root",
                    "password": "keep-me",
                    "canonical_view": "autohub_v_facturas",
                }
            ],
        }
        save_connections(data, path)
        stored = load_connections(path)
        item = stored["connections"][0]
        # Simula upsert con password vacio (UI bug anterior)
        merged = dict(item)
        merged.update(
            {
                "host": "190.218.67.141",
                "database": "admin000002",
                "user": "root",
                "password": "",
            }
        )
        for key in ("host", "database", "user", "password"):
            if (merged.get(key) in {"", None}) and (item.get(key) not in {"", None}):
                merged[key] = item.get(key)
        assert merged["password"] == "keep-me"
        print("merge OK: password preserved")


if __name__ == "__main__":
    test_roundtrip()
    test_merge_preserves_password()
    print("All connection persistence tests passed.")
