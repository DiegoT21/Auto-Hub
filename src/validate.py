from __future__ import annotations

import re
from typing import Any


def _is_consumidor_final(ruc: str | None, config: dict[str, Any]) -> bool:
    if not ruc:
        return False
    normalized = ruc.strip().upper()
    allowed = {value.upper() for value in config["validation"]["consumidor_final_values"]}
    return normalized in allowed


def validate_ruc(ruc: str | None, config: dict[str, Any]) -> str | None:
    if not ruc or not str(ruc).strip():
        return "RUC vacío"

    if _is_consumidor_final(ruc, config):
        return None

    pattern = config["validation"]["ruc_pattern"]
    if not re.match(pattern, str(ruc).strip()):
        return f"RUC con formato inválido: {ruc}"

    return None


def validate_itbms_line(
    cantidad: float,
    precio: float,
    tasa: float,
    total_linea: float,
    config: dict[str, Any],
) -> str | None:
    tolerance = config["validation"]["amount_tolerance"]
    allowed_rates = config["validation"]["itbms_rates"]

    if tasa not in allowed_rates:
        return f"Tasa ITBMS no permitida: {tasa}"

    expected = round(cantidad * precio, 2)
    if abs(expected - total_linea) > tolerance:
        return f"Total línea no cuadra: esperado {expected}, recibido {total_linea}"

    return None


def validate_invoice_totals(
    subtotal: float,
    itbms: float,
    total: float,
    line_totals: list[float],
    config: dict[str, Any],
) -> list[str]:
    tolerance = config["validation"]["amount_tolerance"]
    errors: list[str] = []

    sum_lines = round(sum(line_totals), 2)
    if abs(sum_lines - subtotal) > tolerance:
        errors.append(f"Subtotal no cuadra con líneas: {subtotal} vs {sum_lines}")

    expected_total = round(subtotal + itbms, 2)
    if abs(expected_total - total) > tolerance:
        errors.append(f"Total factura no cuadra: {subtotal}+{itbms} != {total}")

    if total <= 0:
        errors.append("Total de factura debe ser mayor a cero")

    return errors


def validate_rows(rows: list[dict[str, Any]], config: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    valid: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["factura_id"], []).append(row)

    for factura_id, invoice_rows in grouped.items():
        header = invoice_rows[0]
        invoice_errors: list[str] = []

        ruc_error = validate_ruc(header.get("ruc"), config)
        if ruc_error:
            invoice_errors.append(ruc_error)

        line_totals: list[float] = []
        for line in invoice_rows:
            line_error = validate_itbms_line(
                float(line["cantidad"]),
                float(line["precio_unitario"]),
                float(line["tasa_itbms"]),
                float(line["total_linea"]),
                config,
            )
            if line_error:
                invoice_errors.append(f"Línea {line['linea']}: {line_error}")
            line_totals.append(float(line["total_linea"]))

        invoice_errors.extend(
            validate_invoice_totals(
                float(header["subtotal"]),
                float(header["itbms_factura"]),
                float(header["total_factura"]),
                line_totals,
                config,
            )
        )

        if invoice_errors:
            for line in invoice_rows:
                rejected.append({**line, "error_reason": "; ".join(invoice_errors)})
        else:
            valid.extend(invoice_rows)

    return valid, rejected
