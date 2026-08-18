from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from src.db import connect, fetch_all

CANONICAL_COLUMNS = """
    factura_id,
    numero_factura,
    fecha_emision,
    subtotal,
    itbms_factura,
    total_factura,
    cliente_codigo,
    cliente_nombre,
    ruc,
    linea,
    descripcion,
    cantidad,
    precio_unitario,
    tasa_itbms,
    total_linea
"""


def _source_mode(config: dict[str, Any]) -> str:
    return config["extraction"].get("source", "normalized_tables")


def _canonical_view(config: dict[str, Any]) -> str:
    view = config["extraction"].get("canonical_view")
    if not view:
        raise ValueError("Config extraction.canonical_view es requerido para source=canonical_view")
    return view


def _open_filter(config: dict[str, Any], alias: str = "f") -> str:
    field = config["extraction"].get("exported_field", "exportado")
    enabled = config["extraction"].get("filter_unexported", True)
    if not enabled:
        return "1 = 1"
    return f"{alias}.{field} = 0"


def _read_watermark(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"last_id": 0, "last_date": "1970-01-01"}
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def extract_invoices(config: dict[str, Any], root: Path) -> list[dict[str, Any]]:
    if _source_mode(config) == "canonical_view":
        watermark_cfg = config["extraction"]
        watermark_path = root / watermark_cfg["watermark_file"]
        watermark = _read_watermark(watermark_path)
        view = _canonical_view(config)
        use_id = config["extraction"].get("use_id_watermark", True)
        query = f"""
            SELECT
                {CANONICAL_COLUMNS}
            FROM {view}
            WHERE fecha_emision >= ?
        """
        params: tuple[Any, ...] = (watermark["last_date"],)
        if use_id:
            query = f"""
                SELECT
                    {CANONICAL_COLUMNS}
                FROM {view}
                WHERE factura_id > ?
                  AND fecha_emision >= ?
                ORDER BY factura_id, linea
            """
            params = (watermark["last_id"], watermark["last_date"])
        else:
            query += " ORDER BY fecha_emision, factura_id, linea"
        conn = connect(config, root)
        try:
            return fetch_all(conn, query, params)
        finally:
            conn.close()

    tables = config["extraction"]["tables"]
    watermark_cfg = config["extraction"]
    watermark_path = root / watermark_cfg["watermark_file"]
    watermark = _read_watermark(watermark_path)

    query = f"""
        SELECT
            f.id AS factura_id,
            f.numero_factura,
            f.fecha_emision,
            f.subtotal,
            f.itbms AS itbms_factura,
            f.total AS total_factura,
            c.codigo AS cliente_codigo,
            c.nombre AS cliente_nombre,
            c.ruc,
            d.linea,
            d.descripcion,
            d.cantidad,
            d.precio_unitario,
            d.tasa_itbms,
            d.total_linea
        FROM {tables['invoices']} f
        JOIN {tables['customers']} c ON c.id = f.cliente_id
        JOIN {tables['invoice_lines']} d ON d.factura_id = f.id
        WHERE {_open_filter(config, "f")}
          AND f.id > ?
          AND f.fecha_emision >= ?
        ORDER BY f.id, d.linea
    """

    conn = connect(config, root)
    try:
        rows = fetch_all(
            conn,
            query,
            (watermark["last_id"], watermark["last_date"]),
        )
    finally:
        conn.close()

    return rows


def _preview_limit(config: dict[str, Any]) -> int:
    return int(config.get("extraction", {}).get("preview_limit", 150))


def preview_invoice_headers(
    config: dict[str, Any],
    root: Path,
    *,
    date_from: str | None = None,
    customer_query: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Lista encabezados de facturas pendientes para previsualizacion."""
    row_limit = limit if limit is not None else _preview_limit(config)
    if _source_mode(config) == "canonical_view":
        view = _canonical_view(config)
        query = f"""
            SELECT
                factura_id,
                numero_factura,
                fecha_emision,
                subtotal,
                itbms_factura,
                total_factura,
                cliente_codigo,
                cliente_nombre,
                ruc,
                COUNT(*) AS line_count
            FROM {view}
            WHERE 1 = 1
        """
        params: list[Any] = []
        if date_from:
            query += " AND fecha_emision >= ?"
            params.append(date_from)
        if customer_query:
            query += " AND (cliente_nombre LIKE ? OR cliente_codigo LIKE ? OR numero_factura LIKE ?)"
            like = f"%{customer_query}%"
            params.extend([like, like, like])
        query += """
            GROUP BY
                factura_id,
                numero_factura,
                fecha_emision,
                subtotal,
                itbms_factura,
                total_factura,
                cliente_codigo,
                cliente_nombre,
                ruc
            ORDER BY fecha_emision DESC, factura_id DESC
            LIMIT ?
        """
        params.append(row_limit)
        conn = connect(config, root)
        try:
            return fetch_all(conn, query, tuple(params))
        finally:
            conn.close()

    tables = config["extraction"]["tables"]
    query = f"""
        SELECT
            f.id AS factura_id,
            f.numero_factura,
            f.fecha_emision,
            f.subtotal,
            f.itbms AS itbms_factura,
            f.total AS total_factura,
            c.codigo AS cliente_codigo,
            c.nombre AS cliente_nombre,
            c.ruc,
            (SELECT COUNT(*) FROM {tables['invoice_lines']} d WHERE d.factura_id = f.id) AS line_count
        FROM {tables['invoices']} f
        JOIN {tables['customers']} c ON c.id = f.cliente_id
        WHERE {_open_filter(config, "f")}
    """
    params: list[Any] = []
    if date_from:
        query += " AND f.fecha_emision >= ?"
        params.append(date_from)
    if customer_query:
        query += " AND (c.nombre LIKE ? OR c.codigo LIKE ? OR f.numero_factura LIKE ?)"
        like = f"%{customer_query}%"
        params.extend([like, like, like])
    query += " ORDER BY f.fecha_emision DESC, f.id DESC LIMIT ?"
    params.append(row_limit)

    conn = connect(config, root)
    try:
        return fetch_all(conn, query, tuple(params))
    finally:
        conn.close()


def extract_invoices_by_ids(
    config: dict[str, Any],
    root: Path,
    invoice_ids: list[Any],
) -> list[dict[str, Any]]:
    if not invoice_ids:
        return []

    if _source_mode(config) == "canonical_view":
        view = _canonical_view(config)
        placeholders = ",".join("?" for _ in invoice_ids)
        query = f"""
            SELECT
                {CANONICAL_COLUMNS}
            FROM {view}
            WHERE factura_id IN ({placeholders})
            ORDER BY factura_id, linea
        """
        conn = connect(config, root)
        try:
            return fetch_all(conn, query, tuple(invoice_ids))
        finally:
            conn.close()

    tables = config["extraction"]["tables"]
    placeholders = ",".join("?" for _ in invoice_ids)
    query = f"""
        SELECT
            f.id AS factura_id,
            f.numero_factura,
            f.fecha_emision,
            f.subtotal,
            f.itbms AS itbms_factura,
            f.total AS total_factura,
            c.codigo AS cliente_codigo,
            c.nombre AS cliente_nombre,
            c.ruc,
            d.linea,
            d.descripcion,
            d.cantidad,
            d.precio_unitario,
            d.tasa_itbms,
            d.total_linea
        FROM {tables['invoices']} f
        JOIN {tables['customers']} c ON c.id = f.cliente_id
        JOIN {tables['invoice_lines']} d ON d.factura_id = f.id
        WHERE f.id IN ({placeholders})
        ORDER BY f.id, d.linea
    """
    conn = connect(config, root)
    try:
        return fetch_all(conn, query, tuple(invoice_ids))
    finally:
        conn.close()


def save_watermark(config: dict[str, Any], root: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return

    watermark_path = root / config["extraction"]["watermark_file"]
    watermark_path.parent.mkdir(parents=True, exist_ok=True)

    max_id = max(row["factura_id"] for row in rows)
    max_date = max(row["fecha_emision"] for row in rows)

    payload = {
        "last_id": max_id,
        "last_date": max_date,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    with watermark_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
