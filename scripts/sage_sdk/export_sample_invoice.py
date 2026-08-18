# Regenera sample_invoice.json desde adminposper.autohub_v_facturas (outbox shape).
# Uso: python export_sample_invoice.py [factura_id]
# Default: 3117 (2 lineas reales de PsKloud).
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

MYSQL = r"C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe"
OUT = Path(__file__).resolve().parent / "sample_invoice.json"


def main() -> int:
    factura_id = sys.argv[1] if len(sys.argv) > 1 else "3117"
    cols = (
        "factura_id,numero_factura,fecha_emision,subtotal,itbms_factura,total_factura,"
        "cliente_codigo,cliente_nombre,ruc,linea,descripcion,cantidad,precio_unitario,"
        "tasa_itbms,total_linea"
    )
    sql = (
        f"SELECT {cols} FROM autohub_v_facturas "
        f"WHERE factura_id={int(factura_id)} ORDER BY linea;"
    )
    proc = subprocess.run(
        [
            MYSQL,
            "--user=root",
            "--password=1234",
            "--host=127.0.0.1",
            "--port=3306",
            "--database=adminposper",
            "--batch",
            "--raw",
            f"--execute={sql}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        print(proc.stderr or proc.stdout, file=sys.stderr)
        return proc.returncode or 1

    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    if len(lines) < 2:
        print(f"Sin filas para factura_id={factura_id}", file=sys.stderr)
        return 2

    headers = lines[0].split("\t")
    sent_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    out = []
    for ln in lines[1:]:
        row = dict(zip(headers, ln.split("\t")))
        out.append({"sentAt": sent_at, "record": row})

    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {OUT} ({len(out)} lineas, factura_id={factura_id})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
