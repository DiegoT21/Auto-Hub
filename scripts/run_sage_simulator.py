from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.db import load_config
from src.excel_automation import run_excel_automation, run_excel_automation_dry
from src.extract import extract_invoices
from src.sage_excel import (
    copy_empty_workbook,
    create_sage_template,
    dataframe_to_invoice,
    fill_sage_workbook,
    load_invoice_sample,
    load_simulator_config,
)
from src.transform import transform_rows
from src.validate import validate_rows


def _print(msg: str) -> None:
    print(msg)


def cmd_template() -> None:
    path = create_sage_template(ROOT)
    print(f"Plantilla creada: {path}")


def cmd_fill_sample() -> None:
    config = load_simulator_config(ROOT)
    invoice = load_invoice_sample(ROOT / "assets" / "samples" / "invoice_ejemplo_sage.json")
    template = ROOT / config["paths"]["template"]
    if not template.exists():
        create_sage_template(ROOT, config)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = ROOT / config["paths"]["output_dir"] / f"factura_{timestamp}.xlsx"
    fill_sage_workbook(template, invoice, config, output)
    print(f"Factura generada: {output}")


def cmd_fill_db() -> None:
    app_config = load_config(ROOT / "config" / "config.json")
    sim_config = load_simulator_config(ROOT)
    raw = extract_invoices(app_config, ROOT)
    valid, _rejected = validate_rows(raw, app_config)
    frame = transform_rows(valid, app_config)
    if frame.empty:
        print("No hay facturas validas en la base de datos.")
        return

    invoice = dataframe_to_invoice(frame, sim_config)
    template = ROOT / sim_config["paths"]["template"]
    if not template.exists():
        create_sage_template(ROOT, sim_config)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = ROOT / sim_config["paths"]["output_dir"] / f"desde_bd_{timestamp}.xlsx"
    fill_sage_workbook(template, invoice, sim_config, output)
    print(f"Factura desde BD generada: {output}")


def cmd_automate(sample: bool, dry_run: bool) -> None:
    config = load_simulator_config(ROOT)
    if sample:
        invoice = load_invoice_sample(ROOT / "assets" / "samples" / "invoice_ejemplo_sage.json")
    else:
        app_config = load_config(ROOT / "config" / "config.json")
        raw = extract_invoices(app_config, ROOT)
        valid, _ = validate_rows(raw, app_config)
        frame = transform_rows(valid, app_config)
        invoice = dataframe_to_invoice(frame, config)

    template = ROOT / config["paths"]["template"]
    if not template.exists():
        create_sage_template(ROOT, config)

    workbook = ROOT / config["paths"]["output_dir"] / "automation_target.xlsx"
    copy_empty_workbook(ROOT, config, workbook)

    if dry_run:
        run_excel_automation_dry(invoice, ROOT, on_step=_print)
        print(f"\nWorkbook preparado: {workbook}")
        print("Ejecuta sin --dry-run para iniciar la automatizacion en Excel.")
        return

    print("IMPORTANTE: Excel debe estar instalado. No escribas en el teclado durante START.")
    print("Se llenara celda por celda usando la API de Excel (COM).")
    time.sleep(3)
    run_excel_automation(workbook, invoice, ROOT, on_step=_print)


def main() -> None:
    parser = argparse.ArgumentParser(description="Automatizacion Sage en Excel")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("template", help="Crear plantilla Excel vacia tipo Sage")
    sub.add_parser("fill-sample", help="Llenar Excel con factura de referencia")
    sub.add_parser("fill-db", help="Llenar Excel con datos de la base de datos")

    auto = sub.add_parser("automate", help="Abrir Excel y llenar con COM (visible)")
    auto.add_argument("--sample", action="store_true", help="Usar factura de referencia")
    auto.add_argument("--dry-run", action="store_true", help="Solo mostrar campos sin escribir")

    args = parser.parse_args()

    if args.command == "template":
        cmd_template()
    elif args.command == "fill-sample":
        cmd_fill_sample()
    elif args.command == "fill-db":
        cmd_fill_db()
    elif args.command == "automate":
        cmd_automate(sample=args.sample, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
