from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable

from src.sage_excel import build_field_sequence, load_simulator_config

try:
    import win32com.client as win32
except ImportError:
    win32 = None  # type: ignore[assignment]


def _log(message: str, on_step: Callable[[str], None] | None) -> None:
    if on_step:
        on_step(message)


def _get_excel_app():
    if win32 is None:
        raise RuntimeError("Falta pywin32. Ejecuta: pip install pywin32")
    try:
        return win32.GetActiveObject("Excel.Application")
    except Exception:
        app = win32.Dispatch("Excel.Application")
        app.Visible = True
        return app


def _find_or_open_workbook(excel, workbook_path: Path):
    target = str(workbook_path.resolve()).lower()
    for wb in excel.Workbooks:
        try:
            if wb.FullName.lower() == target:
                return wb
        except Exception:
            continue
    return excel.Workbooks.Open(str(workbook_path.resolve()))


def _coerce_value(raw: str):
    if raw == "":
        return ""
    try:
        if "." in raw:
            return float(raw)
        return int(raw)
    except ValueError:
        return raw


def _fill_cell_com(
    excel,
    ws,
    cell: str,
    value: str,
    delay: float,
    type_visible: bool,
    interval: float,
    max_visible: int,
) -> None:
    rng = ws.Range(cell)
    rng.Select()
    excel.ScreenUpdating = True

    text = str(value)
    if type_visible and 0 < len(text) <= max_visible:
        rng.Value = ""
        built = ""
        for ch in text:
            built += ch
            rng.Value = built
            time.sleep(interval)
    else:
        rng.Value = _coerce_value(text)

    time.sleep(delay)


def open_excel_file(path: Path, delay: float = 4.0) -> None:
    os.startfile(str(path))
    time.sleep(delay)


def run_excel_automation(
    workbook_path: Path,
    invoice: dict,
    root: Path,
    on_step: Callable[[str], None] | None = None,
    on_field: Callable[[dict[str, str]], None] | None = None,
) -> None:
    config = load_simulator_config(root)
    auto = config["automation"]
    delay = auto.get("delay_between_fields", 0.55)
    visible = auto.get("use_visible_typing", True)
    interval = auto.get("typing_interval", 0.04)
    max_visible = auto.get("max_chars_visible_type", 30)
    layout = config["excel_layout"]
    sheet_name = layout["sheet_name"]

    sequence = build_field_sequence(invoice, config)
    _log(f">> Automatizacion COM -- {len(sequence)} campos en {workbook_path.name}", on_step)

    excel = _get_excel_app()
    excel.Visible = True
    excel.ScreenUpdating = True

    wb = _find_or_open_workbook(excel, workbook_path)
    ws = wb.Worksheets(sheet_name)
    ws.Activate()

    _log("Esperando Excel conectado. Iniciando llenado celda por celda...", on_step)
    time.sleep(1.0)

    current_section = ""
    for step in sequence:
        section = step["section"]
        if section != current_section:
            current_section = section
            _log(f"--- {section.upper()} ---", on_step)

        cell = step["cell"]
        value = step["value"]
        label = step["label"]

        _log(f"  -> {cell} ({label}): {value[:70]}", on_step)
        if on_field:
            on_field(step)

        _fill_cell_com(excel, ws, cell, value, delay, visible, interval, max_visible)

    _log("OK -- Automatizacion Excel completada.", on_step)


def run_excel_automation_dry(
    invoice: dict,
    root: Path,
    on_step: Callable[[str], None] | None = None,
) -> None:
    config = load_simulator_config(root)
    sequence = build_field_sequence(invoice, config)
    _log(f"[DRY RUN] Se llenarían {len(sequence)} campos:", on_step)
    for step in sequence:
        _log(f"  {step['cell']} ({step['label']}) = {step['value']}", on_step)
