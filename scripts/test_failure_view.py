"""La misma factura de Sage y del origen comparten identidad."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.failure_view import invoice_identity

source = {"ref": "*0008142", "date": "2026-09-16", "ok": False}
sage = {"ref": "AH160926-R-08142", "date": "2026-09-16", "ok": True}
other_branch = {"ref": "AH160926-C-08142", "date": "2026-09-16", "ok": True}
other_day = {"ref": "*0008142", "date": "2026-09-17", "ok": False}

assert invoice_identity(source) == invoice_identity(sage)
assert invoice_identity(source) != invoice_identity(other_branch)
assert invoice_identity(source) != invoice_identity(other_day)
print("OK: identidad de factura por sucursal, numero y fecha.")
