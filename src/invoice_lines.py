"""Control de que una factura traiga todas sus lineas antes de escribirla en Sage."""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

STATE_NAME = "invoices_incompletas.json"
# Centavos de tolerancia por redondeo de PsKloud.
ABS_TOLERANCE = Decimal("0.05")
# Ademas del absoluto, 0.5% del subtotal para documentos grandes.
REL_TOLERANCE = Decimal("0.005")


def _dec(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def line_net(row: dict[str, Any]) -> Decimal:
    """Lo maximo que puede aportar la linea: sin descuento, con descuento o el total que vino."""
    qty = _dec(row.get("cantidad"))
    price = _dec(row.get("precio_unitario"))
    discount = _dec(row.get("dsctounit"))
    gross = qty * price
    return max(gross, qty * (price - discount), _dec(row.get("total_linea")))


def lines_net_total(rows: list[dict[str, Any]]) -> Decimal:
    return sum((line_net(row) for row in rows), Decimal("0"))


def header_subtotal(rows: list[dict[str, Any]]) -> Decimal:
    return _dec((rows[0] if rows else {}).get("subtotal"))


def missing_amount(rows: list[dict[str, Any]]) -> Decimal:
    """Cuanto falta para llegar al subtotal del documento. 0 si esta completa."""
    subtotal = header_subtotal(rows)
    if subtotal <= 0 or not rows:
        return Decimal("0")
    gap = subtotal - lines_net_total(rows)
    tolerance = max(ABS_TOLERANCE, subtotal * REL_TOLERANCE)
    return gap if gap > tolerance else Decimal("0")


def _money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01")))


def _round_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _tax_rate(rows: list[dict[str, Any]]) -> Decimal:
    rec = rows[0] if rows else {}
    rate = _dec(rec.get("tasa_itbms"))
    if rate <= 0:
        return Decimal("0")
    if rate > 1:
        rate = rate / Decimal("100")
    return rate


def invoice_discount(rows: list[dict[str, Any]]) -> tuple[Decimal, Decimal]:
    """Mismo criterio que Get-InvoiceDiscount en RunSageHost.ps1."""
    total = Decimal("0")
    pct = Decimal("0")
    for row in rows:
        qty = _dec(row.get("cantidad"))
        du = _dec(row.get("dsctounit"))
        total += du * qty
        if pct == 0:
            p = _dec(row.get("dsctoprc"))
            if p == 0:
                p = _dec(row.get("desctoprc"))
            if p != 0:
                pct = p
    return _round_money(total), pct


def estimated_sage_itbms(rows: list[dict[str, Any]], *, tax_discount_line: bool = True) -> Decimal:
    """ITBMS que Sage calcula si aplica impuesto en cada linea y en el descuento."""
    rate = _tax_rate(rows)
    if rate <= 0:
        return Decimal("0")
    tax = Decimal("0")
    for row in rows:
        qty = _dec(row.get("cantidad"))
        price = _dec(row.get("precio_unitario"))
        amount = _round_money(qty * price)
        tax += _round_money(amount * rate)
    disc_amt, _ = invoice_discount(rows)
    if tax_discount_line and disc_amt > 0:
        tax += _round_money(-disc_amt * rate)
    return _round_money(tax)


def lines_gross_total(rows: list[dict[str, Any]]) -> Decimal:
    """Suma cantidad * precio_unitario (como escribe RunSageHost por linea)."""
    total = Decimal("0")
    for row in rows:
        qty = _dec(row.get("cantidad"))
        price = _dec(row.get("precio_unitario"))
        total += _round_money(qty * price)
    return _round_money(total)


def estimated_sage_total(rows: list[dict[str, Any]], *, tax_discount_line: bool = True) -> Decimal:
    """Total que Sage tendera a guardar: lineas - descuento + ITBMS."""
    gross = lines_gross_total(rows)
    disc_amt, _ = invoice_discount(rows)
    itbms = estimated_sage_itbms(rows, tax_discount_line=tax_discount_line)
    return _round_money(gross - disc_amt + itbms)


TOTAL_ABS_TOLERANCE = Decimal("0.03")


def total_mismatch_reason(rows: list[dict[str, Any]]) -> str:
    """Vacio si total_factura cuadra con lo que Sage va a calcular (+/- 3 centavos)."""
    if incomplete_reason(rows):
        return ""
    doc_total = _dec((rows[0] if rows else {}).get("total_factura"))
    if doc_total <= 0:
        return ""
    # Solo estimados desde lineas (qty*precio - descuento + ITBMS). No usar
    # subtotal+itbms del documento: eso es circular y deja pasar totales inflados.
    candidates = [
        estimated_sage_total(rows, tax_discount_line=True),
        estimated_sage_total(rows, tax_discount_line=False),
    ]
    if any(abs(doc_total - cand) <= TOTAL_ABS_TOLERANCE for cand in candidates):
        return ""
    nearest = min(candidates, key=lambda cand: abs(doc_total - cand))
    return (
        "Total no cuadra: factura "
        + _money(doc_total)
        + ", estimado Sage "
        + _money(nearest)
        + " (dif "
        + _money(abs(doc_total - nearest))
        + "). No se carga."
    )


def itbms_mismatch_reason(rows: list[dict[str, Any]]) -> str:
    """Vacío si el ITBMS del documento cuadra con lo que Sage va a calcular."""
    if incomplete_reason(rows):
        return ""
    doc_itbms = _dec((rows[0] if rows else {}).get("itbms_factura"))
    if doc_itbms <= 0:
        return ""
    rate = _tax_rate(rows)
    sage_full = estimated_sage_itbms(rows, tax_discount_line=True)
    sage_no_disc = estimated_sage_itbms(rows, tax_discount_line=False)
    subtotal = header_subtotal(rows)
    candidates = [sage_full, sage_no_disc]
    if subtotal > 0 and rate > 0:
        candidates.append(_round_money(subtotal * rate))
    tolerance = max(Decimal("0.03"), doc_itbms * Decimal("0.01"))
    if any(abs(doc_itbms - cand) <= tolerance for cand in candidates):
        return ""
    # Ningun modelo razonable coincide: evita cargar como el caso 8017 (4.97 vs 4.54).
    nearest = min(candidates, key=lambda cand: abs(doc_itbms - cand))
    return (
        "ITBMS no cuadra: factura "
        + _money(doc_itbms)
        + ", lo mas cercano en Sage "
        + _money(nearest)
        + " (dif "
        + _money(abs(doc_itbms - nearest))
        + ")."
    )


def pre_sage_block_reason(rows: list[dict[str, Any]]) -> str:
    """Motivo para no escribir en Sage antes de llamar al host."""
    missing = incomplete_reason(rows)
    if missing:
        return missing
    itbms = itbms_mismatch_reason(rows)
    if itbms:
        return itbms
    return total_mismatch_reason(rows)


def incomplete_reason(rows: list[dict[str, Any]]) -> str:
    """Texto para el usuario si faltan lineas; cadena vacia si la factura esta completa."""
    gap = missing_amount(rows)
    if gap <= 0:
        return ""
    n = len(rows)
    word = "linea" if n == 1 else "lineas"
    return (
        "Faltan items: llegaron "
        + str(n)
        + " "
        + word
        + " por "
        + _money(lines_net_total(rows))
        + ", el documento suma "
        + _money(header_subtotal(rows))
        + " (faltan "
        + _money(gap)
        + "). No se carga incompleta."
    )


def incomplete_card(rows: list[dict[str, Any]], reason: str) -> str:
    """Tarjeta de fallo para la pantalla, sin pasar por el host de Sage."""
    rec = rows[0] if rows else {}
    lines = [
        {
            "n": str(row.get("linea") or (i + 1)),
            "sku": str(row.get("item_codigo") or row.get("codigo") or ""),
            "qty": str(row.get("cantidad") or ""),
            "ok": True,
            "err": "",
        }
        for i, row in enumerate(rows)
    ]
    payload = {
        "ok": False,
        "ref": str(rec.get("documento") or rec.get("factura_id") or rec.get("numero_factura") or "Factura"),
        "date": str(rec.get("fecha_emision") or "")[:10],
        "customer_id": str(rec.get("cliente_codigo") or ""),
        "customer_name": str(rec.get("cliente_nombre") or ""),
        "total": str(rec.get("total_factura") or ""),
        "detail": reason,
        "lines": lines,
    }
    return "[CARD] " + json.dumps(payload, ensure_ascii=False)


def _state_path(root: Path) -> Path:
    path = root / "state" / STATE_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load(root: Path) -> dict[str, Any]:
    path = _state_path(root)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def invoice_key(rows: list[dict[str, Any]]) -> str:
    rec = rows[0] if rows else {}
    return str(rec.get("factura_id") or rec.get("numero_factura") or "").strip()


def is_known_incomplete(root: Path, rows: list[dict[str, Any]]) -> bool:
    """True si ya avisamos por esta factura con la misma cantidad de lineas."""
    key = invoice_key(rows)
    if not key:
        return False
    entry = _load(root).get(key)
    return bool(entry) and int(entry.get("lines") or 0) >= len(rows)


def remember_incomplete(root: Path, rows: list[dict[str, Any]], reason: str) -> None:
    key = invoice_key(rows)
    if not key:
        return
    data = _load(root)
    data[key] = {
        "documento": str((rows[0] if rows else {}).get("documento") or ""),
        "lines": len(rows),
        "reason": reason,
    }
    _state_path(root).write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def forget_incomplete(root: Path, rows: list[dict[str, Any]]) -> None:
    key = invoice_key(rows)
    if not key:
        return
    data = _load(root)
    if key in data:
        del data[key]
        _state_path(root).write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
