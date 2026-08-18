"""Prueba el parser de PDF con texto de ejemplo (sin archivo PDF real)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.extract_pdf import load_pdf_config, parse_invoice_document
from src.transform import transform_rows
from src.validate import validate_rows
from src.db import load_config


def main() -> None:
    sample = ROOT / "assets" / "samples" / "invoice_pdf_text_sample.txt"
    text = sample.read_text(encoding="utf-8")
    pdf_config = load_pdf_config(ROOT)
    rows = parse_invoice_document(text, [], pdf_config, source_name=sample.name)
    app_config = load_config(ROOT / "config" / "config.json")
    valid, rejected = validate_rows(rows, app_config)
    frame = transform_rows(valid, app_config)
    print(f"Lineas parseadas: {len(rows)}")
    print(f"Validas: {len(valid)} | Rechazadas: {len(rejected)}")
    print(frame.to_string(index=False))


if __name__ == "__main__":
    main()
