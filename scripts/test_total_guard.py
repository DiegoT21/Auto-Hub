"""Guardrail: total_factura vs estimado Sage (+/- 0.03)."""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.invoice_lines import (
    estimated_sage_total,
    pre_sage_block_reason,
    total_mismatch_reason,
)


def _row(**kwargs):
    base = {
        "factura_id": "000002:001:FAC:*0008051",
        "documento": "*0008051",
        "numero_factura": "FE1",
        "fecha_emision": "2026-09-08",
        "subtotal": "100.00",
        "itbms_factura": "7.00",
        "total_factura": "107.00",
        "cliente_codigo": "X",
        "cliente_nombre": "X",
        "descripcion": "ITEM",
        "cantidad": "1",
        "precio_unitario": "100",
        "tasa_itbms": "0.07",
        "total_linea": "100",
        "dsctounit": "0",
        "dsctoprc": "0",
        "item_codigo": "SKU1",
        "codigo": "SKU1",
        "linea": "1",
    }
    base.update({k: str(v) for k, v in kwargs.items()})
    return base


def main() -> None:
    ok = [_row()]
    assert estimated_sage_total(ok) == Decimal("107.00")
    assert total_mismatch_reason(ok) == ""
    assert pre_sage_block_reason(ok) == ""

    # Total PsKloud mucho menor que lo que Sage calcularia (caso Montreal-like).
    inflated = [
        _row(total_factura="50.00", itbms_factura="3.50", subtotal="46.50"),
    ]
    reason = total_mismatch_reason(inflated)
    assert "Total no cuadra" in reason, reason
    assert "50.00" in reason
    blocked = pre_sage_block_reason(inflated)
    assert "Total no cuadra" in blocked or "ITBMS no cuadra" in blocked, blocked

    # Dentro de 3 centavos pasa.
    near = [_row(total_factura="107.02", itbms_factura="7.00", subtotal="100.00")]
    assert total_mismatch_reason(near) == ""

    print("OK: total guard blocks mismatches and allows +/- 0.03.")


if __name__ == "__main__":
    main()
