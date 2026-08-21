from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pandas as pd


def _format_date(value: Any, output_format: str) -> str:
    if isinstance(value, datetime):
        return value.strftime(output_format)
    if isinstance(value, date):
        return value.strftime(output_format)
    return datetime.strptime(str(value), "%Y-%m-%d").strftime(output_format)


def transform_rows(rows: list[dict[str, Any]], config: dict[str, Any]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=config["mapping"]["sage_columns"])

    defaults = config["mapping"].get("defaults", {})
    date_format = config["output"]["date_format"]
    sage_columns = config["mapping"]["sage_columns"]

    transformed: list[dict[str, Any]] = []
    for row in rows:
        fecha = _format_date(row["fecha_emision"], date_format)
        tasa = float(row["tasa_itbms"])
        tax_code = "EXENTO" if tasa == 0 else defaults.get("codigo_impuesto", "ITBMS7")
        itbms_linea = round(float(row["total_linea"]) * tasa, 2)

        transformed.append(
            {
                "Invoice Number": row["numero_factura"],
                "Date": fecha,
                "Customer ID": row["cliente_codigo"],
                "Customer Name": row["cliente_nombre"],
                "RUC": row["ruc"],
                "Item": str(row.get("descripcion", ""))[:12].replace(" ", "-"),
                "GL Account": defaults.get("cuenta_gl", "4100"),
                "Description": row["descripcion"],
                "Quantity": row["cantidad"],
                "Unit Price": row["precio_unitario"],
                "Line Amount": row["total_linea"],
                "Tax Code": tax_code,
                "Tax Amount": itbms_linea,
                "Invoice Total": row["total_factura"],
            }
        )

    frame = pd.DataFrame(transformed)
    for col in sage_columns:
        if col not in frame.columns:
            frame[col] = ""
    return frame[sage_columns]
