from __future__ import annotations

import json
import sqlite3
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

SUCURSAL_LABELS = {
    "01": "ADI SUPPLY",
    "02": "CORONADO",
    "03": "RIO ABAJO",
}


def _label_sucursal(codigo: str) -> str:
    code = str(codigo or "").strip()
    return SUCURSAL_LABELS.get(code, "SIN SUCURSAL" if not code else code)


def _parse_factura_key(factura_id: Any) -> tuple[str, str, str, str] | None:
    parts = str(factura_id or "").split(":")
    if len(parts) != 4:
        return None
    return parts[0], parts[1], parts[2], parts[3]


def _attach_sucursal(conn: Any, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rellena sucursal con un lookup indexado a opermv (sin CONCAT sobre la vista)."""
    if not rows or isinstance(conn, sqlite3.Connection):
        for row in rows:
            row.setdefault("sucursal", str(row.get("sucursal") or ""))
            row.setdefault("sucursal_codigo", str(row.get("sucursal_codigo") or ""))
        return rows

    docs: dict[tuple[str, str, str, str], None] = {}
    parsed: list[tuple[dict[str, Any], tuple[str, str, str, str]]] = []
    for row in rows:
        key = _parse_factura_key(row.get("factura_id"))
        if key is None:
            row.setdefault("sucursal", str(row.get("sucursal") or "SIN SUCURSAL"))
            row.setdefault("sucursal_codigo", "")
            continue
        docs[key] = None
        parsed.append((row, key))
    if not docs:
        return rows

    placeholders = ",".join(["(?, ?, ?, ?)"] * len(docs))
    flat: list[str] = []
    for emp, agencia, tipo, documento in docs:
        flat.extend([emp, agencia, tipo, documento])
    lines = fetch_all(
        conn,
        f"""
            SELECT
                id_empresa,
                agencia,
                tipodoc,
                documento,
                origen,
                TRIM(almacen) AS sucursal_codigo
            FROM opermv
            WHERE (id_empresa, agencia, tipodoc, documento) IN ({placeholders})
        """,
        tuple(flat),
    )
    by_line: dict[tuple[tuple[str, str, str, str], Any], str] = {}
    by_doc: dict[tuple[str, str, str, str], set[str]] = {}
    for rec in lines:
        key = (str(rec["id_empresa"]), str(rec["agencia"]), str(rec["tipodoc"]), str(rec["documento"]))
        code = str(rec.get("sucursal_codigo") or "").strip()
        by_line[(key, rec.get("origen"))] = code
        by_doc.setdefault(key, set()).add(code)

    for row, key in parsed:
        linea = row.get("linea")
        if linea is not None and (key, linea) in by_line:
            codes = [by_line[(key, linea)]]
        else:
            codes = sorted(c for c in by_doc.get(key, set()) if c)
        if not codes:
            row["sucursal_codigo"] = ""
            row["sucursal"] = "SIN SUCURSAL"
            continue
        labels = []
        for code in codes:
            label = _label_sucursal(code)
            if label not in labels:
                labels.append(label)
        row["sucursal_codigo"] = ",".join(codes)
        row["sucursal"] = ", ".join(labels)
    return rows


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
            return _attach_sucursal(conn, fetch_all(conn, query, params))
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
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Lista encabezados de facturas pendientes para previsualizacion."""
    row_limit = limit if limit is not None else _preview_limit(config)
    row_offset = max(0, int(offset or 0))
    if _source_mode(config) == "canonical_view":
        query = """
            SELECT
                CONCAT(h.id_empresa, ':', h.agencia, ':', h.tipodoc, ':', h.documento) AS factura_id,
                COALESCE(
                    NULLIF(TRIM(h.documentofiscal), ''),
                    CONCAT('FAC-', LPAD(TRIM(TRIM(LEADING '0' FROM TRIM(h.documento))), 8, '0'))
                ) AS numero_factura,
                DATE(h.emision) AS fecha_emision,
                h.totneto AS subtotal,
                h.totimpuest AS itbms_factura,
                h.totalfinal AS total_factura,
                TRIM(h.codcliente) AS cliente_codigo,
                TRIM(h.nombrecli) AS cliente_nombre,
                TRIM(h.rif) AS ruc,
                COUNT(*) AS line_count
            FROM operti h
            JOIN opermv d
              ON h.id_empresa = d.id_empresa
             AND h.agencia = d.agencia
             AND h.tipodoc = d.tipodoc
             AND h.documento = d.documento
            WHERE h.tipodoc = 'FAC'
              AND h.totalfinal > 0
              AND TRIM(h.estatusdoc) IN ('0', '2')
              AND d.cantidad > 0
        """
        params: list[Any] = []
        if date_from:
            query += " AND h.emision >= ?"
            params.append(date_from)
        if customer_query:
            query += " AND (h.nombrecli LIKE ? OR h.codcliente LIKE ? OR h.documentofiscal LIKE ? OR h.documento LIKE ?)"
            like = f"%{customer_query}%"
            params.extend([like, like, like, like])
        query += """
            GROUP BY
                h.id_empresa,
                h.agencia,
                h.tipodoc,
                h.documento,
                h.documentofiscal,
                h.emision,
                h.totneto,
                h.totimpuest,
                h.totalfinal,
                h.codcliente,
                h.nombrecli,
                h.rif
            ORDER BY h.emision DESC, h.documento DESC
            LIMIT ? OFFSET ?
        """
        params.append(row_limit)
        params.append(row_offset)
        conn = connect(config, root)
        try:
            return _attach_sucursal(conn, fetch_all(conn, query, tuple(params)))
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
    query += " ORDER BY f.fecha_emision DESC, f.id DESC LIMIT ? OFFSET ?"
    params.append(row_limit)
    params.append(row_offset)

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
            return _attach_sucursal(conn, fetch_all(conn, query, tuple(invoice_ids)))
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
