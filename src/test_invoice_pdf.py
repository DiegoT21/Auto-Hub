from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from fpdf import FPDF
except ImportError:
    FPDF = None  # type: ignore[misc, assignment]


def _fmt_date(value: str) -> str:
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(value[:10], fmt).strftime("%d/%m/%Y")
        except ValueError:
            continue
    return value[:10]


def _fmt_money(value: float) -> str:
    return f"{value:,.2f}"


def generate_invoice_pdf(invoice: dict[str, Any], output_path: Path) -> None:
    if FPDF is None:
        raise RuntimeError("Falta fpdf2. Ejecuta: pip install fpdf2")

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)

    header = invoice["header"]
    lines = invoice["lines"]

    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "FACTURA ELECTRONICA", ln=1)
    pdf.set_font("Helvetica", size=11)
    pdf.cell(0, 8, f"No. {header['invoice_number']}", ln=1)
    pdf.cell(0, 8, f"Fecha de emision: {_fmt_date(header['date'])}", ln=1)
    pdf.ln(4)

    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 8, f"Cliente: {header['customer_name']}", ln=1)
    pdf.set_font("Helvetica", size=11)
    if header.get("ruc"):
        pdf.cell(0, 8, f"RUC: {header['ruc']}", ln=1)
    pdf.ln(6)

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(20, 8, "Cant.", border=1)
    pdf.cell(90, 8, "Descripcion", border=1)
    pdf.cell(35, 8, "Precio Unit.", border=1, align="R")
    pdf.cell(35, 8, "Total", border=1, align="R", ln=1)
    pdf.set_font("Helvetica", size=10)

    for line in lines:
        qty = float(line["quantity"])
        desc = str(line["description"])[:55]
        unit = float(line["unit_price"])
        amount = float(line["line_amount"])
        pdf.cell(20, 8, _fmt_money(qty), border=1)
        pdf.cell(90, 8, desc, border=1)
        pdf.cell(35, 8, _fmt_money(unit), border=1, align="R")
        pdf.cell(35, 8, _fmt_money(amount), border=1, align="R", ln=1)

    pdf.ln(6)
    subtotal = float(header.get("subtotal") or 0)
    itbms = float(header.get("itbms") or 0)
    total = float(header.get("total") or 0)
    pdf.cell(0, 8, f"Subtotal: {_fmt_money(subtotal)}", ln=1, align="R")
    pdf.cell(0, 8, f"ITBMS (7%): {_fmt_money(itbms)}", ln=1, align="R")
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 8, f"Total: {_fmt_money(total)}", ln=1, align="R")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(output_path))
