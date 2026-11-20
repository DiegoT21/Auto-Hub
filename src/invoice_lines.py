"""Control de que una factura traiga todas sus lineas antes de escribirla en Sage."""
from __future__ import annotations

import json
import re
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


def _fixed_amount(row: dict[str, Any]) -> Decimal | None:
    """Importe exacto de una parte de kit; el resto de lineas usa cantidad x precio."""
    value = row.get("importe_linea")
    if value in (None, ""):
        return None
    return _dec(value)


def line_net(row: dict[str, Any]) -> Decimal:
    """Lo maximo que puede aportar la linea: sin descuento, con descuento o el total que vino."""
    fixed = _fixed_amount(row)
    if fixed is not None:
        return fixed
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
        tax += _round_money(_line_amount(row) * rate)
    disc_amt, _ = invoice_discount(rows)
    if tax_discount_line and disc_amt > 0:
        tax += _round_money(-disc_amt * rate)
    return _round_money(tax)


def _line_amount(row: dict[str, Any]) -> Decimal:
    """Importe que RunSageHost escribe en la linea."""
    fixed = _fixed_amount(row)
    if fixed is not None:
        return _round_money(fixed)
    qty = _dec(row.get("cantidad"))
    price = _round_money(_dec(row.get("precio_unitario")))
    return _round_money(qty * price)


def lines_gross_total(rows: list[dict[str, Any]]) -> Decimal:
    """Suma cantidad * precio_unitario (como escribe RunSageHost por linea)."""
    return _round_money(sum((_line_amount(row) for row in rows), Decimal("0")))


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
    reason = incomplete_reason(rows) or itbms_mismatch_reason(rows) or total_mismatch_reason(rows)
    if not reason:
        return ""
    rec = rows[0] if rows else {}
    doc = str(rec.get("documento") or rec.get("numero_factura") or rec.get("factura_id") or "").strip()
    return (doc + ": " + reason) if doc else reason


PRICE_TOLERANCE = Decimal("0.005")
SUBSET_TOLERANCE = Decimal("0.02")
MAX_SUBSET_LINES = 16


def _net_unit_price(row: dict[str, Any]) -> Decimal | None:
    for key in ("preciofin", "precio_final", "precioFin"):
        if row.get(key) not in (None, ""):
            return _dec(row.get(key))
    for key in ("montoneto", "monto_neto", "montoNeto"):
        if row.get(key) not in (None, ""):
            qty = _dec(row.get("cantidad"))
            return _dec(row.get(key)) / qty if qty else None
    return None


def _flags_from_subtotal(rows: list[dict[str, Any]]) -> list[bool] | None:
    """G Core no trae preciofin: el subtotal dice que descuentos ya estaban restados."""
    subtotal = header_subtotal(rows)
    if subtotal <= 0:
        return None
    gross = sum((_dec(r.get("cantidad")) * _dec(r.get("precio_unitario")) for r in rows), Decimal("0"))
    discounts = [
        (i, _dec(r.get("cantidad")) * _dec(r.get("dsctounit")))
        for i, r in enumerate(rows)
        if _dec(r.get("dsctounit")) > 0
    ]
    if not discounts or len(discounts) > MAX_SUBSET_LINES:
        return None
    pending = gross - subtotal
    n = len(discounts)
    # Primero las combinaciones con mas descuentos pendientes: la forma normal es la comun.
    for mask in sorted(range(1 << n), key=lambda m: -bin(m).count("1")):
        applied = sum((d for bit, (_i, d) in enumerate(discounts) if mask >> bit & 1), Decimal("0"))
        if abs(applied - pending) <= SUBSET_TOLERANCE:
            in_price = {i for bit, (i, _d) in enumerate(discounts) if not mask >> bit & 1}
            return [i in in_price for i in range(len(rows))]
    return None


def discount_in_price_flags(rows: list[dict[str, Any]]) -> list[bool]:
    """Por linea: True si precio_unitario ya trae el descuento y dsctounit solo lo informa."""
    flags: list[bool] = []
    for row in rows:
        if _dec(row.get("dsctounit")) <= 0:
            flags.append(False)
            continue
        net = _net_unit_price(row)
        if net is None:
            return _flags_from_subtotal(rows) or [False] * len(rows)
        flags.append(abs(_dec(row.get("precio_unitario")) - net) <= PRICE_TOLERANCE)
    return flags


def normalize_discounts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Quita dsctounit de las lineas con el precio ya rebajado para no restarlo dos veces."""
    out = []
    for row, in_price in zip(rows, discount_in_price_flags(rows)):
        if in_price:
            row = dict(row, dsctounit=0, descuento_en_precio=True)
        out.append(row)
    return out


KIT_MAP_NAME = "kit_map.json"


def _kit_key(code: Any) -> str:
    return re.sub(r"[\s\-_.]", "", str(code or "").upper())


def load_kit_map(root: Path | None) -> dict[str, list[dict[str, Any]]]:
    """config/kit_map.json: {"kits": {"GEP-9010": [{"sku", "cantidad", "porcentaje"}, ...]}}."""
    if root is None:
        return {}
    path = Path(root) / "config" / KIT_MAP_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    kits: dict[str, list[dict[str, Any]]] = {}
    for code, parts in ((data or {}).get("kits") or {}).items():
        parts = [p for p in (parts or []) if isinstance(p, dict) and str(p.get("sku") or "").strip()]
        share = sum((_dec(p.get("porcentaje")) for p in parts), Decimal("0"))
        if parts and abs(share - 100) <= Decimal("0.01"):
            kits[_kit_key(code)] = parts
    return kits


def expand_kits(rows: list[dict[str, Any]], kits: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Cambia cada linea de kit por una linea por componente de Sage con su parte del neto."""
    if not kits:
        return rows
    out: list[dict[str, Any]] = []
    for row in rows:
        code = row.get("item_codigo") or row.get("codigo")
        parts = kits.get(_kit_key(code))
        if not parts:
            out.append(row)
            continue
        qty = _dec(row.get("cantidad")) or Decimal("1")
        if row.get("montoneto") not in (None, ""):
            net = _round_money(_dec(row.get("montoneto")))
        else:
            net = _round_money(qty * (_dec(row.get("precio_unitario")) - _dec(row.get("dsctounit"))))
        given = Decimal("0")
        for n, part in enumerate(parts, start=1):
            amount = net - given if n == len(parts) else _round_money(net * _dec(part.get("porcentaje")) / 100)
            given += amount
            part_qty = qty * (_dec(part.get("cantidad")) or Decimal("1"))
            sku = str(part.get("sku")).strip()
            out.append(
                dict(
                    row,
                    item_codigo=sku,
                    codigo=sku,
                    cantidad=float(part_qty),
                    precio_unitario=float((amount / part_qty).quantize(Decimal("0.00001"))),
                    importe_linea=float(amount),
                    montoneto=float(amount),
                    total_linea=float(amount),
                    dsctounit=0,
                    descripcion=str(part.get("descripcion") or row.get("descripcion") or sku)
                    + " (kit " + str(code) + ")",
                    kit_origen=str(code),
                )
            )
    return out


def prepare_invoice(rows: list[dict[str, Any]], root: Path | None = None) -> list[dict[str, Any]]:
    """Lineas listas para Sage: descuentos sin duplicar y kits partidos en componentes."""
    return expand_kits(normalize_discounts(rows), load_kit_map(root))


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
