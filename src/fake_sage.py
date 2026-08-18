from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pandas as pd


@dataclass
class AutomationStep:
    action: str
    detail: str
    delay_seconds: float = 0.8


DEFAULT_MACRO: list[AutomationStep] = [
    AutomationStep("focus", "Activar ventana 'Sage 50'"),
    AutomationStep("menu", "Archivo > Importar registros"),
    AutomationStep("file", "Seleccionar archivo CSV generado"),
    AutomationStep("map", "Confirmar mapeo de columnas"),
    AutomationStep("import", "Ejecutar importación"),
    AutomationStep("done", "Mostrar resumen de registros importados"),
]


def load_macro(path: Path | None) -> list[AutomationStep]:
    if path is None or not path.exists():
        return DEFAULT_MACRO

    with path.open(encoding="utf-8") as handle:
        raw = json.load(handle)

    return [AutomationStep(**step) for step in raw["steps"]]


def run_fake_sage_import(
    csv_path: Path,
    on_step: Callable[[str], None] | None = None,
    macro_path: Path | None = None,
) -> dict[str, int | str]:
    """Ejecuta la secuencia de importacion en Sage 50 (modo registro)."""
    frame = pd.read_csv(csv_path)
    steps = load_macro(macro_path)

    for step in steps:
        message = f"[Sage] {step.action}: {step.detail}"
        if on_step:
            on_step(message)
        time.sleep(step.delay_seconds)

    imported_lines = len(frame)
    invoices = frame["Invoice Number"].nunique() if "Invoice Number" in frame.columns else 0

    return {
        "status": "ok",
        "csv_path": str(csv_path),
        "imported_lines": imported_lines,
        "imported_invoices": int(invoices),
        "message": f"Importacion completada: {imported_lines} lineas, {invoices} facturas.",
    }
