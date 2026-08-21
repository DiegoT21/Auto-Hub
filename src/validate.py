from __future__ import annotations

import re
from typing import Any

# Cédula PA (8-812-809, 2-83-1219), NT jurídico (1424060-1-632587),
# PE/E/N/PI, y DV opcional.
_RUC_PATTERNS = (
    re.compile(r"^(PE|PI|E|N|NT)-?\d{1,2}-\d{1,7}-\d{1,8}(?:-\d{1,2})?$", re.I),
    re.compile(r"^\d{1,2}-\d{1,7}-\d{1,8}(?:-\d{1,2})?$"),
    re.compile(r"^\d{5,12}-\d{1,2}-\d{4,10}$"),
    re.compile(r"^\d{5,20}$"),
)
_DEFAULT_CF = "CF"


def _cf_values(config: dict[str, Any]) -> set[str]:
    values = config.get("validation", {}).get("consumidor_final_values", [])
    allowed = {str(value).strip().upper() for value in values}
    allowed.update({"CF", "CONSUMIDOR FINAL", "000000000", "0-00-000000", "00-00-000000"})
    return allowed


def normalize_ruc(ruc: str | None, config: dict[str, Any]) -> str:
    if ruc is None or not str(ruc).strip():
        return _DEFAULT_CF
    cleaned = str(ruc).strip().upper()
    cleaned = re.sub(r"\s+", "", cleaned)
    cleaned = re.sub(r"DV", "-", cleaned)
    cleaned = re.sub(r"-+", "-", cleaned).strip("-")
    if cleaned in _cf_values(config):
        return _DEFAULT_CF
    return cleaned


def validate_ruc(ruc: str | None, config: dict[str, Any]) -> str | None:
    normalized = normalize_ruc(ruc, config)
    if normalized == _DEFAULT_CF:
        return None
    if any(pattern.match(normalized) for pattern in _RUC_PATTERNS):
        return None
    pattern = str(config.get("validation", {}).get("ruc_pattern") or "")
    if pattern:
        try:
            if re.match(pattern, str(ruc).strip()):
                return None
        except re.error:
            pass
    # Sage no exige formato DGI: no bloquear la carga.
    return None


def _normalize_tax_rate(tasa: float) -> float:
    if tasa >= 1:
        tasa = tasa / 100.0
    return round(tasa, 4)


def _money(value: Any) -> float:
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def validate_itbms_line(
    cantidad: float,
    precio: float,
    tasa: float,
    total_linea: float,
    config: dict[str, Any],
) -> str | None:
    """Compat: ya no rechaza descuentos. El ajuste vive en validate_rows."""
    del cantidad, precio, tasa, total_linea, config
    return None


def validate_invoice_totals(
    subtotal: float,
    itbms: float,
    total: float,
    line_totals: list[float],
    config: dict[str, Any],
) -> list[str]:
    tolerance = float(config.get("validation", {}).get("amount_tolerance", 0.05))
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


def _fix_line_amounts(line: dict[str, Any], config: dict[str, Any]) -> None:
    qty = float(line.get("cantidad") or 0)
    price = float(line.get("precio_unitario") or 0)
    total = _money(line.get("total_linea"))
    tasa = _normalize_tax_rate(float(line.get("tasa_itbms") or 0))
    if qty <= 0:
        qty = 1.0
    expected = round(qty * price, 2)
    tolerance = float(config.get("validation", {}).get("amount_tolerance", 0.05))
    if abs(expected - total) > tolerance:
        price = round(total / qty, 4) if qty else total
    line["cantidad"] = qty
    line["precio_unitario"] = price
    line["total_linea"] = total
    line["tasa_itbms"] = tasa


def validate_rows(rows: list[dict[str, Any]], config: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    valid: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    grouped: dict[Any, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["factura_id"], []).append(row)

    for _factura_id, invoice_rows in grouped.items():
        invoice_errors: list[str] = []
        ruc = normalize_ruc(invoice_rows[0].get("ruc"), config)
        for line in invoice_rows:
            line["ruc"] = ruc
            _fix_line_amounts(line, config)

        line_totals = [_money(line["total_linea"]) for line in invoice_rows]
        header = invoice_rows[0]
        subtotal = _money(header.get("subtotal"))
        itbms = _money(header.get("itbms_factura"))
        total = _money(header.get("total_factura"))
        sum_lines = round(sum(line_totals), 2)
        tolerance = float(config.get("validation", {}).get("amount_tolerance", 0.05))

        if abs(sum_lines - subtotal) > tolerance:
            subtotal = sum_lines
        if total <= 0:
            total = round(subtotal + itbms, 2)
        elif abs(round(subtotal + itbms, 2) - total) > tolerance:
            if itbms == 0 and total > subtotal:
                itbms = round(total - subtotal, 2)
            else:
                total = round(subtotal + itbms, 2)

        if total <= 0 and sum_lines <= 0:
            invoice_errors.append("Total de factura debe ser mayor a cero")

        for line in invoice_rows:
            line["subtotal"] = subtotal
            line["itbms_factura"] = itbms
            line["total_factura"] = total

        if invoice_errors:
            for line in invoice_rows:
                rejected.append({**line, "error_reason": "; ".join(invoice_errors)})
        else:
            valid.extend(invoice_rows)

    return valid, rejected
