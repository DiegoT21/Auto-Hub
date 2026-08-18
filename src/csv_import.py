from __future__ import annotations

from typing import Any

import pandas as pd


def normalize_sage_columns(frame: pd.DataFrame, expected: list[str]) -> pd.DataFrame:
    result = frame.copy()
    for col in expected:
        if col not in result.columns:
            result[col] = ""
    extra = [c for c in result.columns if c not in expected]
    return result[expected + extra]


def detect_column_mapping(frame: pd.DataFrame, expected: list[str]) -> dict[str, str | None]:
    lower_map = {str(c).strip().lower(): c for c in frame.columns}
    aliases = {
        "Invoice Number": ["invoice number", "numero_factura", "factura", "invoice no", "no factura"],
        "Date": ["date", "fecha", "fecha_emision"],
        "Customer ID": ["customer id", "cliente_codigo", "codigo cliente"],
        "Customer Name": ["customer name", "cliente", "cliente_nombre", "nombre"],
        "RUC": ["ruc", "tax id"],
        "Item": ["item", "codigo", "sku"],
        "GL Account": ["gl account", "cuenta_gl", "cuenta"],
        "Description": ["description", "descripcion", "detalle"],
        "Quantity": ["quantity", "cantidad", "qty"],
        "Unit Price": ["unit price", "precio_unitario", "precio"],
        "Line Amount": ["line amount", "total_linea", "importe", "monto"],
        "Tax Code": ["tax code", "codigo_impuesto", "impuesto"],
        "Tax Amount": ["tax amount", "itbms_linea", "itbms"],
        "Invoice Total": ["invoice total", "total_factura", "total"],
    }
    mapping: dict[str, str | None] = {}
    for target in expected:
        if target in frame.columns:
            mapping[target] = target
            continue
        found = None
        for alias in aliases.get(target, [target.lower()]):
            if alias in lower_map:
                found = lower_map[alias]
                break
        mapping[target] = found
    return mapping


def apply_column_mapping(frame: pd.DataFrame, mapping: dict[str, str | None]) -> pd.DataFrame:
    result = pd.DataFrame()
    for target, source in mapping.items():
        if source and source in frame.columns:
            result[target] = frame[source]
        else:
            result[target] = ""
    return result


def sage_dataframe_to_raw_rows(frame: pd.DataFrame, config: dict[str, Any]) -> list[dict[str, Any]]:
    defaults = config["mapping"].get("defaults", {})
    rows: list[dict[str, Any]] = []
    id_by_invoice: dict[str, int] = {}

    for idx, row in frame.iterrows():
        inv = str(row.get("Invoice Number", "") or f"CSV-{idx}")
        if inv not in id_by_invoice:
            id_by_invoice[inv] = abs(hash(inv)) % 9_000_000 + 1_000_000

        tax_code = str(row.get("Tax Code", defaults.get("codigo_impuesto", "ITBMS7")))
        tasa = 0.0 if tax_code.upper() in {"EXENTO", "0", "0.0"} else 0.07
        line_amount = float(row.get("Line Amount", 0) or 0)
        tax_amount = float(row.get("Tax Amount", 0) or 0)
        if tax_amount == 0 and tasa > 0:
            tax_amount = round(line_amount * tasa, 2)

        invoice_total = float(row.get("Invoice Total", 0) or 0)
        subtotal = line_amount
        itbms_line = tax_amount

        rows.append(
            {
                "factura_id": id_by_invoice[inv],
                "numero_factura": inv,
                "fecha_emision": _normalize_date_raw(row.get("Date", "")),
                "subtotal": subtotal,
                "itbms_factura": itbms_line,
                "total_factura": invoice_total if invoice_total else round(subtotal + itbms_line, 2),
                "cliente_codigo": str(row.get("Customer ID", "") or inv[:12]),
                "cliente_nombre": str(row.get("Customer Name", "") or row.get("Customer ID", "")),
                "ruc": str(row.get("RUC", "") or "CF"),
                "linea": len([r for r in rows if r["numero_factura"] == inv]) + 1,
                "descripcion": str(row.get("Description", "")),
                "cantidad": float(row.get("Quantity", 1) or 1),
                "precio_unitario": float(row.get("Unit Price", 0) or 0),
                "tasa_itbms": tasa,
                "total_linea": line_amount,
            }
        )

    _fix_invoice_totals(rows)
    return rows


def _normalize_date_raw(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "1970-01-01"
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            from datetime import datetime

            return datetime.strptime(text[:10], fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return text[:10]


def _fix_invoice_totals(rows: list[dict[str, Any]]) -> None:
    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["factura_id"], []).append(row)

    for invoice_rows in grouped.values():
        subtotal = round(sum(float(r["total_linea"]) for r in invoice_rows), 2)
        itbms = round(sum(float(r["total_linea"]) * float(r["tasa_itbms"]) for r in invoice_rows), 2)
        header_total = float(invoice_rows[0].get("total_factura", 0) or 0)
        total = header_total if header_total > 0 else round(subtotal + itbms, 2)
        for row in invoice_rows:
            row["subtotal"] = subtotal
            row["itbms_factura"] = itbms
            row["total_factura"] = total
