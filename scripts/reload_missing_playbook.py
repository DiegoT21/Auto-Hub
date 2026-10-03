"""Playbook operativo: recargar lo que el cruce marcar como faltante.

No escribe en Sage. Lista pasos y documentos a partir del query PSK + Invoice Register.

  python scripts/reload_missing_playbook.py
  python scripts/reload_missing_playbook.py --out state/reload_playbook.txt
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cross_match_report import cross_match, load_psk, load_sage  # noqa: E402


STEPS = """
Pasos en la PC de Sage (despues de actualizar Auto-Hub)
=======================================================
1. Cerrar Auto-Hub viejo. Copiar update ZIP / carpeta nueva a C:\\AutoHub.
2. Abrir Sage en LYL CONSTRUCTIONS SUPPLY INC 2025-2026.
3. Abrir Auto-Hub -> Conectar Sage (Always Allow si pide).
4. Automatico OFF. Pulsar "Consultar ahora" una vez.
   - Debe bajar la cola 19-23 sep (Electrisa, Montreal, Carbone, ADI 11226+).
5. Revisar Fallidas / "Enviar fallidas" para las del 5-18 que queden bloqueadas.
   Prioridad: *0008036 TROPIC STAR LODGE (4,900.15).
6. NO borrar las 26 facturas con monto inflado hasta ver dumps de linea.
7. ADI ya en Sage (11222-11225) se quedan con A-00002; las nuevas usan A-11226+.
8. Exportar Invoice Register + query PSK y correr:
     python scripts/cross_match_report.py
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sage", type=Path, default=ROOT / "Invoice Register 09232026.pdf")
    parser.add_argument("--psk", type=Path, default=ROOT / "Resultado del Query.txt")
    parser.add_argument("--out", type=Path, default=ROOT / "state" / "reload_playbook.txt")
    args = parser.parse_args()

    if not args.sage.is_file() or not args.psk.is_file():
        print("Faltan archivos de cruce (Invoice Register PDF y Resultado del Query.txt).")
        return 1

    result = cross_match(load_psk(args.psk), load_sage(args.sage))
    lines = [STEPS.strip(), "", "Faltantes hasta " + result["last_sage_day"] + " (Sage ya tenia movimiento)", "-" * 60]
    for row in result["missing_inside"]:
        lines.append(
            f"{row['fecha']}  {row['doc']:12}  {row['ref']:22}  ${row['total']:,.2f}  {row['name']}"
        )
    lines.extend(["", "Faltantes despues de " + result["last_sage_day"] + " (cola / Consultar ahora)", "-" * 60])
    for row in result["missing_after"]:
        lines.append(
            f"{row['fecha']}  {row['doc']:12}  {row['ref']:22}  ${row['total']:,.2f}  {row['name']}"
        )
    if result["duplicated"]:
        lines.extend(["", "Numeros AH que colisionan (documento PsKloud distinto)", "-" * 60])
        for ref, group in sorted(result["duplicated"].items()):
            for row in group:
                lines.append(f"{ref}  {row['documento']}  ${row['total']:,.2f}  {row['cliente_nombre']}")

    text = "\n".join(lines) + "\n"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    sys.stdout.buffer.write((text + "\nEscrito: " + str(args.out) + "\n").encode("utf-8", errors="replace"))
    print(
        f"Resumen: inside={len(result['missing_inside'])} after={len(result['missing_after'])} "
        f"amt_diff={len(result['amount_diff'])} dups={len(result['duplicated'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
