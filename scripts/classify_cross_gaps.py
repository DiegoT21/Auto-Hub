"""Clasificacion provisional del cruce PSK vs Sage (3-23 sep 2026).

Sin logs de C:\\AutoHub no se puede distinguir ITBMS/SKU/incompleta.
Cuando lleguen state/sage_failed.json y logs, re-correr:

  python scripts/classify_cross_gaps.py --failed path/to/sage_failed.json --logs path/to/logs
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Del PDF de cruce: en PSK y no en Sage hasta el 18 sep (Sage si tenia movimiento).
MISSING_INSIDE = [
    ("2026-09-05", "*0008030", 33.77, "ESTRUCTURA INTERAMERICANA"),
    ("2026-09-07", "*0008036", 4900.15, "TROPIC STAR LODGE"),
    ("2026-09-10", "C0003374", 159.30, "RICHARD KELLYN GALVEZ"),
    ("2026-09-10", "C0003378", 132.72, "INVERSIONES EL ESTABLO"),
    ("2026-09-10", "*0008078", 181.69, "ROSA CHEN"),
    ("2026-09-11", "*0008089", 139.05, "GILBERTO DE LEON"),
    ("2026-09-11", "*0008094", 41.83, "ACCCION VERDE"),
    ("2026-09-14", "*0008112", 26.17, "GILBERTO DE LEON"),
    ("2026-09-14", "*0008114", 84.04, "COMERCIALIZADORA ANCAR"),
    ("2026-09-14", "*0008118", 86.77, "RUBEN GOMEZ"),
    ("2026-09-15", "*0008121", 137.89, "PINTURAS BALMAR"),
    ("2026-09-16", "*0008142", 22.45, "MARISOL SANCHEZ"),
    ("2026-09-16", "*0008143", 8.82, "ALEACIONES PANAMA"),
    ("2026-09-18", "C0003431", 20.09, "ALBERTO LICONA"),
    ("2026-09-18", "C0003432", 160.70, "HAL HIRVING ZAPATA"),
    ("2026-09-18", "*0008166", 102.36, "RF GUTIERREZ"),
    ("2026-09-18", "*0008167", 314.22, "VICSONS CONSTRUCTION"),
    ("2026-09-18", "*0008168", 314.22, "VICSONS CONSTRUCTION (otra)"),
]

# Top montos inflados (Sage - PSK) del cruce.
AMOUNT_DIFF_TOP = [
    ("*0008051", "MONTREAL INT", 2328.11, 3361.60, 1033.49),
    ("00011224", "SEMFYL ADI", 397.15, 748.09, 350.94),
    ("*0008045", "CADPRO PACIFICO", 3471.30, 3714.29, 242.99),
    ("*0008019", "ISTMO BUILDERS", 184.67, 303.75, 119.08),
    ("*0008119", "CADPRO PACIFICO", 426.00, 531.90, 105.90),
]


def _load_failed(path: Path) -> dict[str, dict]:
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    invoices = data.get("invoices") if isinstance(data, dict) else None
    if not isinstance(invoices, dict):
        return {}
    return {str(k).upper(): v for k, v in invoices.items()}


def _scan_logs(folder: Path) -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {}
    if not folder.is_dir():
        return hits
    patterns = (
        "ITBMS",
        "Faltan items",
        "codigo 16",
        "no existe en sage",
        "incompleta",
        "duplicad",
        "TROPIC",
        "8036",
        "Montreal",
        "8051",
    )
    for path in sorted(folder.glob("*.txt")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            low = line.lower()
            if not any(p.lower() in low for p in patterns):
                continue
            for token in re.findall(r"([C*]\d{7,}|\d{8})", line):
                hits.setdefault(token.upper(), []).append(path.name + ": " + line.strip()[:160])
    return hits


def classify(failed: dict[str, dict], log_hits: dict[str, list[str]]) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for fecha, doc, amt, name in MISSING_INSIDE:
        key = doc.upper()
        reason = "sin evidencia local (pedir logs Sage)"
        if key in failed or key.lstrip("C*") in failed:
            entry = failed.get(key) or failed.get(key.lstrip("C*")) or {}
            err = str(entry.get("error") or entry.get("detail") or "en sage_failed")
            reason = "cola fallidas: " + err[:120]
        elif key in log_hits:
            reason = "log: " + log_hits[key][0][:120]
        elif "VICSONS" in name and doc.endswith("8167"):
            reason = "posible doble (mismo monto que *0008168) — confirmar en PSK"
        elif doc == "*0008036":
            reason = "prioridad: USD 4900 — revisar dump ITBMS/SKU en logs"
        rows.append((fecha + " " + doc, name + " $" + f"{amt:.2f}", reason))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--failed", type=Path, default=ROOT / "state" / "sage_failed.json")
    parser.add_argument("--logs", type=Path, default=ROOT / "logs")
    parser.add_argument("--out", type=Path, default=ROOT / "state" / "cross_gap_classification.txt")
    args = parser.parse_args()

    failed = _load_failed(args.failed)
    log_hits = _scan_logs(args.logs)
    rows = classify(failed, log_hits)

    lines = [
        "Clasificacion provisional — faltantes 5-18 sep (18 facturas)",
        "============================================================",
        "Fuentes locales: sage_failed=" + ("si" if failed else "no") + "  logs=" + ("si" if log_hits else "no"),
        "",
    ]
    for key, who, reason in rows:
        lines.append(key + "  |  " + who)
        lines.append("  -> " + reason)
        lines.append("")

    lines.extend(
        [
            "Montos inflados (top) — no borrar hasta ver dumps de linea",
            "=======================================================",
        ]
    )
    for doc, name, psk, sage, delta in AMOUNT_DIFF_TOP:
        note = "posible colision ADI A-00002" if doc.startswith("000112") else "revisar lineas/ITBMS/descuento"
        lines.append(
            f"{doc}  {name}  PSK {psk:.2f}  Sage {sage:.2f}  delta +{delta:.2f}  -> {note}"
        )

    lines.extend(
        [
            "",
            "Faltantes 19-23 sep (47): Sage en cero esos dias -> cola sin consultar.",
            "Accion: Actualizar app (Fases 1-3) + Consultar ahora.",
            "",
            "Para clasificar de verdad, copiar de la PC Sage:",
            "  C:\\AutoHub\\state\\sage_failed.json",
            "  C:\\AutoHub\\state\\sage_sent.json",
            "  C:\\AutoHub\\state\\invoices_incompletas.json",
            "  C:\\AutoHub\\logs\\autohub-2026-09-*.txt",
        ]
    )

    text = "\n".join(lines) + "\n"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    sys.stdout.buffer.write((text + "Escrito: " + str(args.out) + "\n").encode("utf-8", errors="replace"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
