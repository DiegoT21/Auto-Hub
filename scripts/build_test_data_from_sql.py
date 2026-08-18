from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.sql_dump_parser import read_schema_and_tables
from src.test_invoice_pdf import generate_invoice_pdf

DEFAULT_SQL = Path.home() / "Downloads" / "EjemploFacturaSage" / "EjemploFacturaSage.sql"
OUTPUT_ROOT = ROOT / "assets" / "test_data"
SAGE_COLUMNS = [
    "Invoice Number",
    "Date",
    "Customer ID",
    "Customer Name",
    "RUC",
    "Item",
    "GL Account",
    "Description",
    "Quantity",
    "Unit Price",
    "Line Amount",
    "Tax Code",
    "Tax Amount",
    "Invoice Total",
]


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_ruc(value: str) -> str:
    value = _clean(value)
    if not value or value.upper() in {"CF", "CONSUMIDOR FINAL"}:
        return "CF"
    value = re.sub(r"\s+", "", value)
    if re.match(r"^\d{1,2}-\d{3,4}-\d{4,6}$", value):
        return value
    digits = re.sub(r"\D", "", value)
    if len(digits) >= 9:
        return f"{digits[0]}-{digits[1:4]}-{digits[4:]}"
    return value


def _invoice_number(header: dict[str, Any]) -> str:
    fiscal = _clean(header.get("documentofiscal"))
    if fiscal and fiscal not in {"0", "-"}:
        return fiscal.replace(" ", "-")
    doc = _clean(header.get("documento")).lstrip("0") or "0"
    return f"FAC-{doc.zfill(8)}"


def _tax_rate(line: dict[str, Any]) -> float:
    rate = float(line.get("timpueprc") or 0)
    if rate >= 1:
        return round(rate / 100, 4)
    return rate


def _header_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        _clean(row["id_empresa"]),
        _clean(row["agencia"]),
        _clean(row["tipodoc"]),
        _clean(row["documento"]),
    )


def _is_valid_fac(header: dict[str, Any], lines: list[dict[str, Any]]) -> bool:
    if _clean(header.get("tipodoc")) != "FAC":
        return False
    if float(header.get("totalfinal") or 0) <= 0:
        return False
    if not lines:
        return False
    if _clean(header.get("estatusdoc")) not in {"2", "0"}:
        return False
    return True


def _build_invoice(header: dict[str, Any], lines: list[dict[str, Any]]) -> dict[str, Any]:
    inv_no = _invoice_number(header)
    date_raw = _clean(header.get("emision"))[:10]
    customer_id = _clean(header.get("codcliente"))
    customer_name = _clean(header.get("nombrecli"))
    ruc = _normalize_ruc(_clean(header.get("rif")) or _clean(header.get("nit")))
    subtotal = round(float(header.get("totneto") or 0), 2)
    itbms = round(float(header.get("totimpuest") or 0), 2)
    total = round(float(header.get("totalfinal") or 0), 2)

    sage_lines: list[dict[str, Any]] = []
    for line in lines:
        qty = float(line.get("cantidad") or 0)
        if qty <= 0:
            continue
        unit = round(float(line.get("preciounit") or 0), 2)
        amount = round(float(line.get("montoneto") or 0), 2)
        if amount <= 0:
            amount = round(qty * unit, 2)
        rate = _tax_rate(line)
        tax_code = "EXENTO" if rate == 0 else "ITBMS7"
        tax_amount = round(amount * rate, 2)
        desc = _clean(line.get("nombre")) or _clean(line.get("codigo")) or "Servicio"
        item = _clean(line.get("codigo"))[:12] or desc[:12].replace(" ", "-")
        gl = _clean(line.get("cuentacont")) or "4100"

        sage_lines.append(
            {
                "Invoice Number": inv_no,
                "Date": date_raw,
                "Customer ID": customer_id,
                "Customer Name": customer_name,
                "RUC": ruc,
                "Item": item,
                "GL Account": gl,
                "Description": desc,
                "Quantity": qty,
                "Unit Price": unit,
                "Line Amount": amount,
                "Tax Code": tax_code,
                "Tax Amount": tax_amount,
                "Invoice Total": total,
            }
        )

    return {
        "key": _header_key(header),
        "header": {
            "invoice_number": inv_no,
            "date": date_raw,
            "customer_id": customer_id,
            "customer_name": customer_name,
            "ruc": ruc,
            "subtotal": subtotal,
            "itbms": itbms,
            "total": total,
            "documento": _clean(header.get("documento")),
            "documentofiscal": _clean(header.get("documentofiscal")),
        },
        "lines": sage_lines,
        "raw_header": header,
        "raw_lines": lines,
    }


def _select_invoices(invoices: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    valid = [inv for inv in invoices if inv["lines"]]
    valid.sort(key=lambda inv: (inv["header"]["date"], inv["header"]["invoice_number"]), reverse=True)

    selected: list[dict[str, Any]] = []
    seen_customers: set[str] = set()

    for inv in valid:
        customer = inv["header"]["customer_id"]
        if customer in seen_customers and len(selected) >= max(3, limit // 2):
            continue
        selected.append(inv)
        seen_customers.add(customer)
        if len(selected) >= limit:
            break

    if len(selected) < limit:
        for inv in valid:
            if inv in selected:
                continue
            selected.append(inv)
            if len(selected) >= limit:
                break
    return selected


def _invoice_dataframe(invoice: dict[str, Any]) -> pd.DataFrame:
    return pd.DataFrame(invoice["lines"], columns=SAGE_COLUMNS)


def _write_csvs(invoices: list[dict[str, Any]], output_root: Path) -> dict[str, Any]:
    csv_root = output_root / "csv"
    single_dir = csv_root / "sage_single"
    raw_dir = csv_root / "pskloud_raw"
    single_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    batch_frames = []
    single_files: list[str] = []
    raw_headers = []
    raw_lines = []

    for invoice in invoices:
        frame = _invoice_dataframe(invoice)
        batch_frames.append(frame)
        safe_name = re.sub(r"[^\w\-]+", "_", invoice["header"]["invoice_number"])
        single_path = single_dir / f"{safe_name}.csv"
        frame.to_csv(single_path, index=False, encoding="utf-8-sig")
        single_files.append(str(single_path.relative_to(ROOT)))

        raw_headers.append(invoice["raw_header"])
        raw_lines.extend(invoice["raw_lines"])

    batch_path = csv_root / "sage_batch_all.csv"
    pd.concat(batch_frames, ignore_index=True).to_csv(batch_path, index=False, encoding="utf-8-sig")

    pd.DataFrame(raw_headers).to_csv(raw_dir / "operti_fac_sample.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(raw_lines).to_csv(raw_dir / "opermv_fac_sample.csv", index=False, encoding="utf-8-sig")

    return {
        "batch_csv": str(batch_path.relative_to(ROOT)),
        "single_csv_dir": str(single_dir.relative_to(ROOT)),
        "single_csv_files": single_files,
        "raw_operti_csv": str((raw_dir / "operti_fac_sample.csv").relative_to(ROOT)),
        "raw_opermv_csv": str((raw_dir / "opermv_fac_sample.csv").relative_to(ROOT)),
    }


def _write_pdfs(invoices: list[dict[str, Any]], output_root: Path) -> list[str]:
    pdf_dir = output_root / "pdf"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    files: list[str] = []

    for invoice in invoices:
        safe_name = re.sub(r"[^\w\-]+", "_", invoice["header"]["invoice_number"])
        pdf_path = pdf_dir / f"{safe_name}.pdf"
        pdf_invoice = {
            "header": invoice["header"],
            "lines": [
                {
                    "quantity": row["Quantity"],
                    "description": row["Description"],
                    "unit_price": row["Unit Price"],
                    "line_amount": row["Line Amount"],
                }
                for row in invoice["lines"]
            ],
        }
        generate_invoice_pdf(pdf_invoice, pdf_path)
        files.append(str(pdf_path.relative_to(ROOT)))
    return files


def _load_sqlite(invoices: list[dict[str, Any]], db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            DROP TABLE IF EXISTS facturas_detalle;
            DROP TABLE IF EXISTS facturas;
            DROP TABLE IF EXISTS clientes;

            CREATE TABLE clientes (
                id INTEGER PRIMARY KEY,
                codigo TEXT NOT NULL UNIQUE,
                nombre TEXT NOT NULL,
                ruc TEXT
            );

            CREATE TABLE facturas (
                id INTEGER PRIMARY KEY,
                numero_factura TEXT NOT NULL UNIQUE,
                fecha_emision TEXT NOT NULL,
                cliente_id INTEGER NOT NULL,
                subtotal REAL NOT NULL,
                itbms REAL NOT NULL,
                total REAL NOT NULL,
                exportado INTEGER DEFAULT 0,
                FOREIGN KEY (cliente_id) REFERENCES clientes(id)
            );

            CREATE TABLE facturas_detalle (
                id INTEGER PRIMARY KEY,
                factura_id INTEGER NOT NULL,
                linea INTEGER NOT NULL,
                descripcion TEXT NOT NULL,
                cantidad REAL NOT NULL,
                precio_unitario REAL NOT NULL,
                tasa_itbms REAL NOT NULL,
                total_linea REAL NOT NULL,
                FOREIGN KEY (factura_id) REFERENCES facturas(id)
            );
            """
        )

        client_map: dict[str, int] = {}
        next_client_id = 1
        next_factura_id = 1
        next_detalle_id = 1

        for invoice in invoices:
            header = invoice["header"]
            customer_code = header["customer_id"] or f"CLI{next_client_id:04d}"
            if customer_code not in client_map:
                conn.execute(
                    "INSERT INTO clientes (id, codigo, nombre, ruc) VALUES (?, ?, ?, ?)",
                    (next_client_id, customer_code, header["customer_name"], header["ruc"]),
                )
                client_map[customer_code] = next_client_id
                next_client_id += 1

            cliente_id = client_map[customer_code]
            conn.execute(
                """
                INSERT INTO facturas
                (id, numero_factura, fecha_emision, cliente_id, subtotal, itbms, total, exportado)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    next_factura_id,
                    header["invoice_number"],
                    header["date"],
                    cliente_id,
                    header["subtotal"],
                    header["itbms"],
                    header["total"],
                ),
            )

            for line_no, row in enumerate(invoice["lines"], start=1):
                rate = 0.0 if row["Tax Code"] == "EXENTO" else 0.07
                conn.execute(
                    """
                    INSERT INTO facturas_detalle
                    (id, factura_id, linea, descripcion, cantidad, precio_unitario, tasa_itbms, total_linea)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        next_detalle_id,
                        next_factura_id,
                        line_no,
                        row["Description"],
                        row["Quantity"],
                        row["Unit Price"],
                        rate,
                        row["Line Amount"],
                    ),
                )
                next_detalle_id += 1

            next_factura_id += 1

        conn.commit()
    finally:
        conn.close()


def build_test_data(
    sql_path: Path,
    *,
    limit: int = 12,
    output_root: Path = OUTPUT_ROOT,
    load_db: bool = False,
    db_path: Path = ROOT / "data" / "pskloud_demo.db",
) -> dict[str, Any]:
    if not sql_path.exists():
        raise FileNotFoundError(f"No se encontro el backup SQL: {sql_path}")

    print(f"Leyendo backup: {sql_path}")
    _operti_cols, _opermv_cols, operti_rows, opermv_rows = read_schema_and_tables(sql_path)
    print(f"  operti: {len(operti_rows):,} registros")
    print(f"  opermv: {len(opermv_rows):,} registros")

    headers = [row for row in operti_rows if _clean(row.get("tipodoc")) == "FAC"]
    lines_by_key: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for row in opermv_rows:
        if _clean(row.get("tipodoc")) != "FAC":
            continue
        key = _header_key(row)
        lines_by_key.setdefault(key, []).append(row)

    invoices: list[dict[str, Any]] = []
    for header in headers:
        key = _header_key(header)
        lines = lines_by_key.get(key, [])
        if not _is_valid_fac(header, lines):
            continue
        invoices.append(_build_invoice(header, lines))

    selected = _select_invoices(invoices, limit)
    if not selected:
        raise RuntimeError("No se encontraron facturas FAC validas para exportar.")

    output_root.mkdir(parents=True, exist_ok=True)
    csv_info = _write_csvs(selected, output_root)
    pdf_files = _write_pdfs(selected, output_root)

    manifest = {
        "source_sql": str(sql_path),
        "invoice_count": len(selected),
        "invoices": [
            {
                "invoice_number": inv["header"]["invoice_number"],
                "date": inv["header"]["date"],
                "customer": inv["header"]["customer_name"],
                "ruc": inv["header"]["ruc"],
                "total": inv["header"]["total"],
                "line_count": len(inv["lines"]),
            }
            for inv in selected
        ],
        **csv_info,
        "pdf_files": pdf_files,
    }

    if load_db:
        _load_sqlite(selected, db_path)
        manifest["sqlite_db"] = str(db_path.relative_to(ROOT))
        print(f"Base local cargada: {db_path}")

    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    manifest["manifest"] = str(manifest_path.relative_to(ROOT))
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convierte EjemploFacturaSage.sql en CSV y PDF de prueba para Auto-Hub."
    )
    parser.add_argument("--sql", type=Path, default=DEFAULT_SQL, help="Ruta al dump MySQL")
    parser.add_argument("--limit", type=int, default=12, help="Cantidad de facturas a exportar")
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT, help="Carpeta de salida")
    parser.add_argument(
        "--load-db",
        action="store_true",
        help="Cargar las facturas seleccionadas en data/pskloud_demo.db",
    )
    args = parser.parse_args()

    manifest = build_test_data(
        args.sql,
        limit=args.limit,
        output_root=args.output,
        load_db=args.load_db,
    )

    print(f"\nListo: {manifest['invoice_count']} facturas exportadas")
    print(f"  Lote CSV: {manifest['batch_csv']}")
    print(f"  PDFs: {len(manifest['pdf_files'])} archivos en assets/test_data/pdf/")
    print(f"  Manifest: {manifest['manifest']}")


if __name__ == "__main__":
    main()
