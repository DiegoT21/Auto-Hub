"""TMP / Recibida no van a Sage; sin item_codigo no se abre el writer."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.ledger_bridge import missing_item_sku, pending_jobs, skip_not_sales_invoice
from src.sage_sdk_write import _coerce_row


def _row(**kwargs):
    base = {
        "factura_id": "000002:001:FAC:C0003389",
        "numero_factura": "FE1",
        "fecha_emision": "2026-09-14",
        "cliente_codigo": "X",
        "cliente_nombre": "X",
        "descripcion": "SIKAFLEX",
        "cantidad": 1,
        "precio_unitario": 1,
        "linea": 1,
        "item_codigo": "C0003355",
    }
    base.update(kwargs)
    return _coerce_row(base)


def main() -> None:
    tmp = [_row(factura_id="000002:001:FAC:TMP001", numero_factura="0 Recibida", item_codigo="")]
    assert skip_not_sales_invoice(tmp), tmp
    rec = [_row(factura_id="000002:001:FAC:C0001", numero_factura="0 Recibida")]
    assert skip_not_sales_invoice(rec)
    ok = [_row()]
    assert skip_not_sales_invoice(ok) == ""
    assert missing_item_sku(ok) == ""
    empty = [_row(item_codigo="", codigo="")]
    err = missing_item_sku(empty)
    assert "sin item_codigo" in err, err
    camel = _coerce_row({"factura_id": "C0003389", "itemCodigo": "ABC", "descripcion": "x", "cantidad": 1})
    assert camel["item_codigo"] == "ABC"
    pending = pending_jobs(
        {
            "invoices": [
                {
                    "branchId": "b",
                    "facturaId": "000002:001:FAC:C0003389",
                    "numeroFactura": "FE1",
                    "clienteCodigo": "X",
                    "clienteNombre": "ALPHA",
                    "fechaEmision": "2026-09-14",
                    "lines": [
                        {
                            "linea": 1,
                            "itemCodigo": "750748",
                            "descripcion": "SIKAFLEX 1A PURFORM - BLANCO",
                            "cantidad": "12",
                            "precioUnitario": "8.76",
                            "dsctoUnit": "0.438",
                            "dsctoPrc": "5",
                            "sucursal": "Coronado",
                            "documento": "C0003389",
                            "tasaItbms": "0.07",
                            "totalLinea": "99.864",
                        }
                    ],
                }
            ]
        }
    )
    row = pending[0]["rows"][0]
    assert row["item_codigo"] == "750748", row
    assert abs(row["dsctounit"] - 0.438) < 0.0001, row
    assert abs(row["dsctoprc"] - 5) < 0.0001, row
    assert row["sucursal"] == "CORONADO", row
    assert missing_item_sku(pending[0]["rows"]) == ""
    print("test_skip_tmp_sku ok")


if __name__ == "__main__":
    main()
