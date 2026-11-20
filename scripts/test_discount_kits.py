"""Descuento ya incluido en el precio (forma 2) y partir kits en componentes."""
from __future__ import annotations

import json
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.components import explain_failure
from src.invoice_lines import (
    estimated_sage_total,
    expand_kits,
    load_kit_map,
    normalize_discounts,
    pre_sage_block_reason,
    prepare_invoice,
)


def _row(**kwargs):
    base = {
        "factura_id": "000002:001:FAC:*0008670",
        "documento": "*0008670",
        "subtotal": 67.6,
        "itbms_factura": 4.73,
        "total_factura": 72.33,
        "tasa_itbms": 0.07,
        "dsctoprc": 8.0,
    }
    base.update(kwargs)
    return base


# *0008670 tal como lo manda G Core: la linea 1 ya trae el 8% en precio_unitario.
INVOICE_8670 = [
    _row(linea=1, item_codigo="409935", cantidad=1.0, precio_unitario=35.7, dsctounit=3.104),
    _row(linea=2, item_codigo="422042", cantidad=1.0, precio_unitario=25.07, dsctounit=2.0056),
    _row(linea=3, item_codigo="493133", cantidad=2.0, precio_unitario=4.8, dsctounit=0.384),
]


def test_inferred_from_subtotal() -> None:
    assert estimated_sage_total(INVOICE_8670) == Decimal("69.00")
    assert "*0008670: Total no cuadra" in pre_sage_block_reason(INVOICE_8670)
    fixed = normalize_discounts(INVOICE_8670)
    assert [r["dsctounit"] for r in fixed] == [0, 2.0056, 0.384]
    assert estimated_sage_total(fixed) == Decimal("72.33")
    assert pre_sage_block_reason(fixed) == ""
    assert normalize_discounts(fixed) == fixed


def test_montoneto_per_line() -> None:
    rows = [dict(r) for r in INVOICE_8670]
    for row, net in zip(rows, (35.7, 23.0644, 8.832)):
        row["montoneto"] = net
        row["subtotal"] = 0
    fixed = normalize_discounts(rows)
    assert [r["dsctounit"] for r in fixed] == [0, 2.0056, 0.384]


def test_normal_discount_untouched() -> None:
    rows = [_row(cantidad=2.0, precio_unitario=10.0, dsctounit=1.0, subtotal=18.0, itbms_factura=1.26, total_factura=19.26)]
    assert normalize_discounts(rows) == rows


def test_kit_split() -> None:
    kits = {"GEP9010": [
        {"sku": "A-1", "cantidad": 1, "porcentaje": 33.33},
        {"sku": "B-2", "cantidad": 2, "porcentaje": 33.33},
        {"sku": "C-3", "cantidad": 1, "porcentaje": 33.34},
    ]}
    row = _row(item_codigo="GEP-9010", codigo="GEP-9010", cantidad=3.0, precio_unitario=10.0, dsctounit=0,
               subtotal=30.0, itbms_factura=2.1, total_factura=32.1, descripcion="KIT")
    parts = expand_kits([row], kits)
    assert [p["item_codigo"] for p in parts] == ["A-1", "B-2", "C-3"]
    assert [p["cantidad"] for p in parts] == [3.0, 6.0, 3.0]
    assert [p["importe_linea"] for p in parts] == [10.0, 10.0, 10.0]
    assert sum(Decimal(str(p["importe_linea"])) for p in parts) == Decimal("30.00")
    assert all(p["tasa_itbms"] == 0.07 for p in parts)
    assert pre_sage_block_reason(parts) == ""

    odd = expand_kits([dict(row, precio_unitario=3.337, cantidad=1.0)], kits)
    assert sum(Decimal(str(p["importe_linea"])) for p in odd) == Decimal("3.34")


def test_kit_map_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "config").mkdir()
        (root / "config" / "kit_map.json").write_text(json.dumps({"kits": {
            "NO-004": [{"sku": "X", "cantidad": 1, "porcentaje": 100}],
            "MALO": [{"sku": "Y", "cantidad": 1, "porcentaje": 50}],
        }}), encoding="utf-8")
        kits = load_kit_map(root)
        assert set(kits) == {"NO004"}
        rows = prepare_invoice([_row(item_codigo="NO - 004", cantidad=1.0, precio_unitario=5.0, dsctounit=0)], root)
        assert rows[0]["item_codigo"] == "X"
    assert load_kit_map(ROOT / "no-existe") == {}


def test_missing_message() -> None:
    reason, action = explain_failure({"status": "err", "lines": [{"sku": "NO-004", "ok": False}]})
    assert reason == "Artículo NO-004 no existe en Sage ni en el listado de kits", reason
    assert "kit_map.json" in action


def main() -> None:
    test_inferred_from_subtotal()
    test_montoneto_per_line()
    test_normal_discount_untouched()
    test_kit_split()
    test_kit_map_file()
    test_missing_message()
    print("OK: descuento en precio y kits.")


if __name__ == "__main__":
    main()
