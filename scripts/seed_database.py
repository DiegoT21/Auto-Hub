"""Inicializa la base de datos local SQLite (PsKloud)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "pskloud_demo.db"


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS facturas_detalle;
        DROP TABLE IF EXISTS facturas;
        DROP TABLE IF EXISTS clientes;

        CREATE TABLE clientes (
            id INTEGER PRIMARY KEY,
            codigo TEXT NOT NULL UNIQUE,
            nombre TEXT NOT NULL,
            ruc TEXT
        );

        CREATE TABLE facturas (
            id INTEGER PRIMARY KEY,
            numero_factura TEXT NOT NULL UNIQUE,
            fecha_emision TEXT NOT NULL,
            cliente_id INTEGER NOT NULL,
            subtotal REAL NOT NULL,
            itbms REAL NOT NULL,
            total REAL NOT NULL,
            exportado INTEGER DEFAULT 0,
            FOREIGN KEY (cliente_id) REFERENCES clientes(id)
        );

        CREATE TABLE facturas_detalle (
            id INTEGER PRIMARY KEY,
            factura_id INTEGER NOT NULL,
            linea INTEGER NOT NULL,
            descripcion TEXT NOT NULL,
            cantidad REAL NOT NULL,
            precio_unitario REAL NOT NULL,
            tasa_itbms REAL NOT NULL,
            total_linea REAL NOT NULL,
            FOREIGN KEY (factura_id) REFERENCES facturas(id)
        );
        """
    )


def seed_data(conn: sqlite3.Connection) -> None:
    clientes = [
        (1, "CLI001", "Supermercados El Valle S.A.", "8-123-45678"),
        (2, "CLI002", "Farmacia Central", "4-567-89123"),
        (3, "CLI003", "Consumidor Final", "CF"),
    ]
    conn.executemany(
        "INSERT INTO clientes (id, codigo, nombre, ruc) VALUES (?, ?, ?, ?)",
        clientes,
    )

    facturas = [
        (1, "FE-000101", "2026-06-01", 1, 100.00, 7.00, 107.00, 0),
        (2, "FE-000102", "2026-06-02", 2, 250.00, 17.50, 267.50, 0),
        (3, "FE-000103", "2026-06-03", 3, 50.00, 3.50, 53.50, 0),
        (4, "FE-000104", "2026-06-10", 1, 80.00, 5.60, 85.60, 0),
        (5, "FE-000105", "2026-06-15", 2, 0.00, 0.00, 0.00, 0),
    ]
    conn.executemany(
        """
        INSERT INTO facturas
        (id, numero_factura, fecha_emision, cliente_id, subtotal, itbms, total, exportado)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        facturas,
    )

    detalle = [
        (1, 1, 1, "Licencia software mensual", 1, 100.00, 0.07, 100.00),
        (2, 2, 1, "Soporte técnico", 5, 50.00, 0.07, 250.00),
        (3, 3, 1, "Producto varios", 2, 25.00, 0.07, 50.00),
        (4, 4, 1, "Consultoría", 2, 40.00, 0.07, 80.00),
        (5, 5, 1, "Servicio con error de total", 1, 0.00, 0.07, 0.00),
    ]
    conn.executemany(
        """
        INSERT INTO facturas_detalle
        (id, factura_id, linea, descripcion, cantidad, precio_unitario, tasa_itbms, total_linea)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        detalle,
    )


def main() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        create_schema(conn)
        seed_data(conn)
        conn.commit()
        print(f"Base de datos local creada en: {DB_PATH}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
