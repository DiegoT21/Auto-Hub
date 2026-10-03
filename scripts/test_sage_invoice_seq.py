"""Regression: secuencia Sage AH no usa el id de empresa 000002 en ADI."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from cross_match_report import expected_ref, invoice_seq, store_letter


def _row(**kwargs):
    base = {
        "factura_id": "",
        "numero_factura": "",
        "documento": "",
        "fecha_emision": "2026-09-07",
        "sucursal": "",
    }
    base.update(kwargs)
    return base


def main() -> None:
    assert invoice_seq("000002:001:FAC:00011222", "FE012...", "00011222") == "11222"
    assert invoice_seq("000002:001:FAC:00011222", "FE012...", "") == "11222"
    assert invoice_seq("000002:001:FAC:C0003342", "", "C0003342") == "03342"
    assert invoice_seq("000002:001:FAC:*0008011", "", "*0008011") == "08011"
    # Sin documento: la cola despues de FAC: gana sobre 000002 de la empresa.
    assert invoice_seq("000002:001:FAC:00011226", "FE012...", "") == "11226"

    adi = _row(
        factura_id="000002:001:FAC:00011222",
        documento="00011222",
        fecha_emision="2026-09-07",
        sucursal="ADI SUPPLY",
    )
    assert store_letter(adi["sucursal"]) == "A"
    assert expected_ref(adi) == "AH070926-A-11222"
    assert expected_ref(adi) != "AH070926-A-00002"

    rio = _row(
        factura_id="000002:001:FAC:*0008011",
        documento="*0008011",
        fecha_emision="2026-09-03",
        sucursal="Sika Center Rio Abajo",
    )
    assert expected_ref(rio) == "AH030926-R-08011"

    cor = _row(
        factura_id="000002:001:FAC:C0003342",
        documento="C0003342",
        fecha_emision="2026-09-03",
        sucursal="Coronado",
    )
    assert expected_ref(cor) == "AH030926-C-03342"

    from cross_match_report import legacy_adi_ref

    assert legacy_adi_ref(adi) == "AH070926-A-00002"
    assert legacy_adi_ref(rio) is None

    print("OK: ADI 11222, Rio *8011, Coronado C3342 sequences.")


if __name__ == "__main__":
    main()
