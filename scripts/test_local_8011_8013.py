"""Pruebas 8011/8012/8013 contra Sage local (LYL 2025-2026).

8011: 1 linea, sin descuento (control).
8012: 2 lineas + dsctounit (debe salir Descuento en 4031, ITBMS sobre ambas).
8013: 1 linea CON item_codigo (antes fallaba por codigo vacio).

Invoice No. Sage: AH + DDMMAA + -R- + 98011/98012/98013
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.sage_sdk_write import (  # noqa: E402
    TEST_CUSTOMER_ID,
    delete_ah_invoices,
    find_sent_invoice,
    forget_sent_needles,
    run_test_company_write,
    sage_ui_running,
)

TODAY = date.today().isoformat()
SEQS = ["98011", "98012", "98013"]


def _base(doc: str, linea: int, desc: str, sku: str, qty: float, price: float, dscto: float = 0.0) -> dict:
    return {
        "factura_id": "000002:001:FAC:" + doc,
        "numero_factura": doc,
        "documento": doc,
        "fecha_emision": TODAY,
        "subtotal": 0,
        "itbms_factura": 0,
        "total_factura": 0,
        "cliente_codigo": TEST_CUSTOMER_ID,
        "cliente_nombre": TEST_CUSTOMER_ID,
        "ruc": "CF",
        "linea": linea,
        "descripcion": desc,
        "cantidad": qty,
        "precio_unitario": price,
        "tasa_itbms": 0.07,
        "total_linea": round(qty * price, 2),
        "sucursal": "Sika Center Rio Abajo",
        "item_codigo": sku,
        "codigo": sku,
        "dsctounit": dscto,
        "dsctoprc": 10 if dscto else 0,
    }


def _capture_write(rows: list[dict]) -> tuple[int, list[str]]:
    lines: list[str] = []

    def on_log(msg: str) -> None:
        text = str(msg)
        print(text)
        lines.append(text)

    code = run_test_company_write(ROOT, rows, on_log=on_log)
    return code, lines


def _ok(blob: str, *needles: str) -> None:
    low = blob.lower()
    missing = [n for n in needles if n.lower() not in low]
    if missing:
        raise RuntimeError("No aparecio en el log de Sage: " + ", ".join(missing))


def _sent_ref(rows: list[dict], seq: str) -> str:
    sent = find_sent_invoice(ROOT, rows)
    ref = str((sent or {}).get("sage_ref") or "")
    if seq not in ref.replace(" ", "").upper() and ("-R-" + seq) not in ref.upper():
        raise RuntimeError("sent-log sin Invoice No. -R-" + seq + ": " + repr(sent))
    return ref


def main() -> int:
    print("Fecha Sage:", TODAY)
    if not sage_ui_running():
        raise RuntimeError(
            "Abre Sage 50 en LYL CONSTRUCTIONS SUPPLY INC 2025-2026 y vuelve a correr este script."
        )
    print("Sage abierto. Limpiando pruebas *0098011-13 si existian...")
    forget_sent_needles(ROOT, SEQS + ["*0098011", "*0098012", "*0098013", "00098011", "00098012", "00098013"])
    try:
        stats = delete_ah_invoices(ROOT, on_log=print, only_seq=SEQS)
        print("Borrado previo:", stats)
    except Exception as exc:
        print("Aviso al borrar previo (sigue la prueba):", exc)

    print("\n=== 8011 control (1 linea, sin descuento) ===")
    rows1 = [_base("*0098011", 1, "C0003355 PLAYA BLANCA", "C0003355", 1, 10.0, 0)]
    code, log1 = _capture_write(rows1)
    blob1 = "\n".join(log1)
    ref1 = _sent_ref(rows1, "98011")
    print("Invoice Sage 8011:", ref1)
    _ok(blob1, "OK - Factura guardada", "-R-98011", "4001")
    if "descuento" in blob1.lower() and "gl=4031" in blob1.lower() and "linea 2:" in blob1.lower():
        raise RuntimeError("8011 no debia tener linea de descuento")
    print("8011 OK")

    print("\n=== 8012 dos lineas + descuento 4031 ===")
    rows2 = [
        _base("*0098012", 1, "C0003355 PLAYA BLANCA", "C0003355", 2, 10.0, 0.5),
        _base("*0098012", 2, "C0003355 PLAYA BLANCA L2", "C0003355", 1, 5.0, 1.0),
    ]
    code, log2 = _capture_write(rows2)
    blob2 = "\n".join(log2)
    ref2 = _sent_ref(rows2, "98012")
    print("Invoice Sage 8012:", ref2)
    _ok(blob2, "OK - Factura guardada", "-R-98012", "4001", "4031", "Linea 1:", "Linea 2:", "Descuento")
    if "sin item_codigo" in blob2.lower():
        raise RuntimeError("8012 fallo por item_codigo vacio")
    print("8012 OK (2 lineas + 4031)")

    print("\n=== 8013 con item_codigo (antes no subia) ===")
    rows3 = [_base("*0098013", 1, "C0003355 PLAYA BLANCA", "C0003355", 1, 12.0, 0)]
    code, log3 = _capture_write(rows3)
    blob3 = "\n".join(log3)
    ref3 = _sent_ref(rows3, "98013")
    print("Invoice Sage 8013:", ref3)
    _ok(blob3, "OK - Factura guardada", "-R-98013", "item=")
    if "sin item_codigo" in blob3.lower() or "fail 16" in blob3.lower():
        raise RuntimeError("8013 salio sin item_codigo o Fail 16")
    print("8013 OK")

    print("\nListo. En Sage busca AH" + TODAY[8:10] + TODAY[5:7] + TODAY[2:4] + "-R-98011 / 98012 / 98013")
    print("98012 debe tener 2 items + Descuento en 4031 + ITBMS. 8011 y 8013 de 1 linea.")
    print("No se uso Borrar AH global.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("FALLO:", exc)
        raise SystemExit(1)
