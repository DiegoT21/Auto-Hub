"""Cruce PSK vs Sage: query autohub_v_facturas contra el Invoice Register en PDF.

Uso:
  python scripts/cross_match_report.py
  python scripts/cross_match_report.py --sage "Invoice Register.pdf" --psk "Query.txt"
"""
from __future__ import annotations

import argparse
import csv
import re
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import pdfplumber
from fpdf import FPDF

ROOT = Path(__file__).resolve().parent.parent
TOL = 0.02

SAGE_LINE = re.compile(
    r"^(AH\d{6}-[A-Z]-\d+)\s+(\d{1,2}/\d{1,2}/\d{2})(?:\s+(.*?))?\s+([\d,]+\.\d{2})\s*$"
)


def money(value: Any) -> float:
    return round(float(str(value).replace(",", "").replace('"', "").strip()), 2)


def fmt(value: float) -> str:
    return f"{value:,.2f}"


def store_letter(sucursal: str) -> str:
    text = (sucursal or "").upper()
    if "RIO ABAJO" in text:
        return "R"
    if "CORONADO" in text:
        return "C"
    if "ADI" in text:
        return "A"
    return "S"


def _seq_digits(text: str) -> str:
    if not text:
        return ""
    match = re.search(r"(C|\*)(\d{5,})", text) or re.search(r"(\d{5,})", text)
    return match.group(match.lastindex) if match else ""


def invoice_seq(factura_id: str, numero: str, documento: str) -> str:
    # Preferir documento / cola despues de FAC: — si se busca el primer \d{5,}
    # en factura_id (000002:001:FAC:00011222) se toma la empresa 000002.
    digits = _seq_digits(documento or "")
    if not digits and factura_id and ":" in factura_id:
        digits = _seq_digits(factura_id.rsplit(":", 1)[-1])
    if not digits:
        digits = _seq_digits(" ".join([factura_id or "", numero or ""]))
    if not digits:
        digits = "0"
    return digits[-5:].zfill(5)


def expected_ref(row: dict[str, str]) -> str:
    year, month, day = str(row["fecha_emision"])[:10].split("-")
    ref = (
        "AH"
        + day
        + month
        + year[2:]
        + "-"
        + store_letter(row["sucursal"])
        + "-"
        + invoice_seq(row["factura_id"], row["numero_factura"], row["documento"])
    )
    return ref[:20]


def legacy_adi_ref(row: dict[str, str]) -> str | None:
    """Antes del fix, todas las ADI usaban A-00002 (id empresa). Solo reconciliar historico."""
    if store_letter(row.get("sucursal") or "") != "A":
        return None
    year, month, day = str(row["fecha_emision"])[:10].split("-")
    return ("AH" + day + month + year[2:] + "-A-00002")[:20]


def find_sage_row(row: dict[str, Any], sage_by_ref: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    hit = sage_by_ref.get(row["ref"])
    if hit:
        return hit
    legacy = legacy_adi_ref(row)
    if legacy:
        return sage_by_ref.get(legacy)
    return None


def norm_name(value: str) -> str:
    text = unicodedata.normalize("NFKD", (value or "").upper())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9]+", " ", text)).strip()


def same_client(psk: str, sage: str) -> bool:
    """El Invoice Register recorta y abrevia nombres, asi que no exige igualdad.

    Basta que uno contenga al otro, que compartan prefijo, o que coincidan dos
    palabras largas (cubre "SERVICIO NACIONAL AERONAVAL" vs "SERVICIO NAL. AERONAVAL").
    """
    if not sage:
        return True
    if sage in psk or psk in sage or sage[:16] == psk[:16]:
        return True
    words_psk = {word for word in psk.split() if len(word) >= 4}
    words_sage = {word for word in sage.split() if len(word) >= 4}
    return len(words_psk & words_sage) >= 2


def load_psk(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            row = {
                key.strip().strip('"'): (value.strip().strip('"') if isinstance(value, str) else value)
                for key, value in raw.items()
            }
            row["ref"] = expected_ref(row)
            row["total"] = money(row["total_factura"])
            row["name_n"] = norm_name(row["cliente_nombre"])
            rows.append(row)
    return rows


def load_sage(path: Path) -> list[dict[str, Any]]:
    with pdfplumber.open(path) as pdf:
        text = "\n".join((page.extract_text() or "") for page in pdf.pages)
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        match = SAGE_LINE.match(line.strip())
        if not match:
            continue
        ref, date, name, amount = match.groups()
        rows.append(
            {
                "ref": ref,
                "date": date,
                "name": (name or "").strip(),
                "name_n": norm_name(name or ""),
                "total": money(amount),
            }
        )
    return rows


def cross_match(psk: list[dict[str, Any]], sage: list[dict[str, Any]]) -> dict[str, Any]:
    sage_by_ref = {row["ref"]: row for row in sage}

    full_ok: list[dict[str, Any]] = []
    amount_diff: list[dict[str, Any]] = []
    client_diff: list[dict[str, Any]] = []
    matched_sage_refs: set[str] = set()

    for source in psk:
        sage_row = find_sage_row(source, sage_by_ref)
        if not sage_row:
            continue
        matched_sage_refs.add(sage_row["ref"])
        delta = round(sage_row["total"] - source["total"], 2)
        entry = {
            "ref": source["ref"],
            "sage_ref": sage_row["ref"],
            "fecha": source["fecha_emision"],
            "doc": source["documento"],
            "sucursal": source["sucursal"],
            "psk_name": source["cliente_nombre"],
            "sage_name": sage_row["name"] or "(sin nombre en PDF)",
            "psk": source["total"],
            "sage": sage_row["total"],
            "delta": delta,
        }
        if abs(delta) >= TOL:
            amount_diff.append(entry)
        elif not same_client(source["name_n"], sage_row["name_n"]):
            client_diff.append(entry)
        else:
            full_ok.append(entry)

    last_sage_day = ""
    for row in sage:
        day, month, year = row["date"].split("/")
        stamp = f"20{year}-{int(month):02d}-{int(day):02d}"
        last_sage_day = max(last_sage_day, stamp)

    missing_inside: list[dict[str, Any]] = []
    missing_after: list[dict[str, Any]] = []
    for row in psk:
        if find_sage_row(row, sage_by_ref):
            continue
        entry = {
            "ref": row["ref"],
            "fecha": row["fecha_emision"],
            "doc": row["documento"],
            "sucursal": row["sucursal"],
            "name": row["cliente_nombre"],
            "total": row["total"],
        }
        target = missing_inside if row["fecha_emision"] <= last_sage_day else missing_after
        target.append(entry)

    only_sage = [row for row in sage if row["ref"] not in matched_sage_refs]

    per_day_psk: dict[str, int] = defaultdict(int)
    per_day_sage: dict[str, int] = defaultdict(int)
    for row in psk:
        per_day_psk[row["fecha_emision"]] += 1
    for row in sage:
        day, month, year = row["date"].split("/")
        per_day_sage[f"20{year}-{int(month):02d}-{int(day):02d}"] += 1
    days = sorted(set(per_day_psk) | set(per_day_sage))

    collisions: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in psk:
        collisions[row["ref"]].append(row)
    duplicated = {ref: rows for ref, rows in collisions.items() if len(rows) > 1}

    return {
        "psk": psk,
        "sage": sage,
        "full_ok": full_ok,
        "amount_diff": sorted(amount_diff, key=lambda item: -abs(item["delta"])),
        "client_diff": client_diff,
        "missing_inside": missing_inside,
        "missing_after": missing_after,
        "only_sage": only_sage,
        "last_sage_day": last_sage_day,
        "days": days,
        "per_day_psk": per_day_psk,
        "per_day_sage": per_day_sage,
        "duplicated": duplicated,
    }


class Report(FPDF):
    def __init__(self, period: str) -> None:
        super().__init__(orientation="P", unit="mm", format="A4")
        self.period = period
        self.set_auto_page_break(auto=True, margin=14)
        self.set_margins(12, 12, 12)

    def header(self) -> None:
        if self.page_no() == 1:
            return
        self.set_font("helvetica", "", 7)
        self.set_text_color(130)
        self.cell(0, 5, "Cruce PsKloud vs Sage 50  ·  " + self.period, align="L")
        self.ln(7)
        self.set_text_color(0)

    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("helvetica", "", 7)
        self.set_text_color(130)
        self.cell(0, 5, f"Pagina {self.page_no()}", align="C")
        self.set_text_color(0)


def latin(text: Any) -> str:
    return str(text).encode("latin-1", "replace").decode("latin-1")


def title(pdf: Report, text: str) -> None:
    if pdf.get_y() > 240:
        pdf.add_page()
    pdf.ln(3)
    pdf.set_font("helvetica", "B", 11)
    pdf.cell(0, 6, latin(text))
    pdf.ln(7)


def note(pdf: Report, text: str) -> None:
    pdf.set_font("helvetica", "", 8)
    pdf.set_text_color(90)
    pdf.multi_cell(0, 4, latin(text))
    pdf.set_text_color(0)
    pdf.ln(1)


def clip(pdf: Report, text: str, width: float) -> str:
    """Recorta al ancho de la celda; fpdf no corta y el texto invade la columna vecina."""
    text = latin(text)
    limit = width - 2
    if pdf.get_string_width(text) <= limit:
        return text
    while text and pdf.get_string_width(text + "...") > limit:
        text = text[:-1]
    return text.rstrip() + "..."


def table(
    pdf: Report,
    headers: list[str],
    widths: list[float],
    rows: list[list[str]],
    aligns: list[str] | None = None,
) -> None:
    aligns = aligns or ["L"] * len(headers)

    def draw_head() -> None:
        pdf.set_font("helvetica", "B", 7.5)
        pdf.set_fill_color(235, 235, 238)
        for header, width, align in zip(headers, widths, aligns):
            pdf.cell(width, 5.5, latin(header), border="B", align=align, fill=True)
        pdf.ln(5.5)

    draw_head()
    pdf.set_font("helvetica", "", 7.5)
    shade = False
    for row in rows:
        if pdf.get_y() > 262:
            pdf.add_page()
            draw_head()
            pdf.set_font("helvetica", "", 7.5)
        pdf.set_fill_color(248, 248, 250)
        for value, width, align in zip(row, widths, aligns):
            pdf.cell(width, 4.8, clip(pdf, value, width), border=0, align=align, fill=shade)
        pdf.ln(4.8)
        shade = not shade
    pdf.ln(2)


def kpi_row(pdf: Report, items: list[tuple[str, str]]) -> None:
    width = (pdf.w - pdf.l_margin - pdf.r_margin) / len(items)
    top = pdf.get_y()
    for index, (label, value) in enumerate(items):
        left = pdf.l_margin + width * index
        pdf.set_xy(left, top)
        pdf.set_font("helvetica", "B", 15)
        pdf.cell(width, 7, latin(value))
        pdf.set_xy(left, top + 7)
        pdf.set_font("helvetica", "", 7.5)
        pdf.set_text_color(105)
        pdf.cell(width, 4, latin(label))
        pdf.set_text_color(0)
    pdf.set_y(top + 14)


def short_suc(value: str) -> str:
    text = (value or "").upper()
    if "RIO" in text:
        return "Rio Abajo"
    if "CORONADO" in text:
        return "Coronado"
    if "ADI" in text:
        return "ADI"
    return value


def build_pdf(result: dict[str, Any], out_path: Path, sage_src: Path, psk_src: Path) -> None:
    psk = result["psk"]
    sage = result["sage"]
    days = result["days"]
    period = f"{days[0]} a {days[-1]}" if days else "sin datos"
    psk_total = round(sum(row["total"] for row in psk), 2)
    sage_total = round(sum(row["total"] for row in sage), 2)
    missing = result["missing_inside"] + result["missing_after"]
    missing_total = round(sum(row["total"] for row in missing), 2)

    pdf = Report(period)
    pdf.add_page()

    pdf.set_font("helvetica", "B", 17)
    pdf.cell(0, 9, "Cruce PsKloud vs Sage 50")
    pdf.ln(10)
    pdf.set_font("helvetica", "", 9)
    pdf.set_text_color(95)
    pdf.multi_cell(
        0,
        4.5,
        latin(
            "Periodo "
            + period
            + ".  Generado "
            + datetime.now().strftime("%d/%m/%Y %H:%M")
            + ".\n"
            + "PsKloud: "
            + psk_src.name
            + " (vista autohub_v_facturas).\n"
            + "Sage: "
            + sage_src.name
            + " (Invoice Register, LYL CONSTRUCTIONS SUPPLY INC 2025-2026).\n"
            + "Llave de cruce: numero Auto-Hub AH + ddMMyy + sucursal (C/R/A) + ultimos 5 digitos"
            " del documento. No se usa el numero fiscal FE."
        ),
    )
    pdf.set_text_color(0)
    pdf.ln(4)

    kpi_row(
        pdf,
        [
            ("Facturas PsKloud", str(len(psk))),
            ("Facturas Sage", str(len(sage))),
            ("En PSK, no en Sage", str(len(missing))),
            ("Monto distinto", str(len(result["amount_diff"]))),
        ],
    )
    kpi_row(
        pdf,
        [
            ("Total PsKloud (USD)", fmt(psk_total)),
            ("Total Sage (USD)", fmt(sage_total)),
            ("Diferencia (USD)", fmt(round(psk_total - sage_total, 2))),
            ("No cargado (USD)", fmt(missing_total)),
        ],
    )

    title(pdf, "Reconciliacion")
    table(
        pdf,
        ["Resultado", "Facturas", "Monto PSK (USD)"],
        [120, 33, 33],
        [
            ["En Sage, monto y cliente iguales", str(len(result["full_ok"])), fmt(sum(r["psk"] for r in result["full_ok"]))],
            ["En Sage, monto igual, cliente distinto", str(len(result["client_diff"])), fmt(sum(r["psk"] for r in result["client_diff"]))],
            ["En Sage, mismo numero, monto distinto", str(len(result["amount_diff"])), fmt(sum(r["psk"] for r in result["amount_diff"]))],
            ["Solo en PsKloud (no llego a Sage)", str(len(missing)), fmt(missing_total)],
            ["Solo en Sage (no existe en PsKloud)", str(len(result["only_sage"])), "-"],
            ["Total PsKloud", str(len(psk)), fmt(psk_total)],
        ],
        ["L", "R", "R"],
    )

    title(pdf, "Facturas por dia")
    note(
        pdf,
        "Conteo diario en cada fuente. La ultima fecha con movimiento en Sage es "
        + result["last_sage_day"]
        + ".",
    )
    day_rows = []
    for day in days:
        count_psk = result["per_day_psk"][day]
        count_sage = result["per_day_sage"][day]
        gap = count_psk - count_sage
        day_rows.append([day, str(count_psk), str(count_sage), ("-" if gap == 0 else str(gap))])
    table(pdf, ["Fecha", "PsKloud", "Sage", "Faltan"], [40, 28, 28, 28], day_rows, ["L", "R", "R", "R"])

    if result["missing_inside"]:
        total = sum(row["total"] for row in result["missing_inside"])
        title(pdf, f"En PsKloud y no en Sage hasta {result['last_sage_day']}")
        note(
            pdf,
            f"{len(result['missing_inside'])} facturas por USD {fmt(total)}. Caen en dias que Sage"
            " si tiene movimiento, asi que no se explican por una consulta pendiente.",
        )
        table(
            pdf,
            ["Fecha", "Doc PsKloud", "Numero Sage", "Cliente", "Sucursal", "Monto"],
            [18, 24, 32, 63, 22, 27],
            [
                [
                    row["fecha"][5:],
                    row["doc"],
                    row["ref"],
                    row["name"],
                    short_suc(row["sucursal"]),
                    fmt(row["total"]),
                ]
                for row in result["missing_inside"]
            ],
            ["L", "L", "L", "L", "L", "R"],
        )

    if result["missing_after"]:
        total = sum(row["total"] for row in result["missing_after"])
        title(pdf, f"En PsKloud y no en Sage despues de {result['last_sage_day']}")
        note(
            pdf,
            f"{len(result['missing_after'])} facturas por USD {fmt(total)}. Sage no registra ninguna"
            " factura en esas fechas.",
        )
        table(
            pdf,
            ["Fecha", "Doc PsKloud", "Numero Sage", "Cliente", "Sucursal", "Monto"],
            [18, 24, 32, 63, 22, 27],
            [
                [
                    row["fecha"][5:],
                    row["doc"],
                    row["ref"],
                    row["name"],
                    short_suc(row["sucursal"]),
                    fmt(row["total"]),
                ]
                for row in result["missing_after"]
            ],
            ["L", "L", "L", "L", "L", "R"],
        )

    if result["amount_diff"]:
        over = [row for row in result["amount_diff"] if row["delta"] > 0]
        under = [row for row in result["amount_diff"] if row["delta"] < 0]
        title(pdf, "Mismo numero Sage, monto distinto")
        note(
            pdf,
            f"Delta = Sage - PsKloud. {len(over)} facturas quedaron de mas en Sage por USD "
            + fmt(sum(row["delta"] for row in over))
            + f" y {len(under)} de menos por USD "
            + fmt(abs(sum(row["delta"] for row in under)))
            + ".",
        )
        table(
            pdf,
            ["Fecha", "Doc PsKloud", "Cliente", "PSK", "Sage", "Delta"],
            [18, 24, 74, 24, 24, 22],
            [
                [
                    row["fecha"][5:],
                    row["doc"],
                    row["psk_name"],
                    fmt(row["psk"]),
                    fmt(row["sage"]),
                    ("+" if row["delta"] > 0 else "") + fmt(row["delta"]),
                ]
                for row in result["amount_diff"]
            ],
            ["L", "L", "L", "R", "R", "R"],
        )

    if result["client_diff"]:
        title(pdf, "Mismo monto, cliente distinto en Sage")
        note(
            pdf,
            "El total cuadra pero el cliente asignado en Sage no corresponde al de PsKloud."
            " El Invoice Register recorta nombres largos; estos casos no se explican por el recorte.",
        )
        table(
            pdf,
            ["Fecha", "Doc PsKloud", "Cliente PsKloud", "Cliente Sage", "Monto"],
            [18, 24, 62, 62, 20],
            [
                [
                    row["fecha"][5:],
                    row["doc"],
                    row["psk_name"],
                    row["sage_name"],
                    fmt(row["psk"]),
                ]
                for row in result["client_diff"]
            ],
            ["L", "L", "L", "L", "R"],
        )

    if result["duplicated"]:
        title(pdf, "Numeros Sage repetidos")
        note(
            pdf,
            "Varias facturas de PsKloud generan el mismo numero Auto-Hub, asi que se pisan entre"
            " ellas al cargar en Sage.",
        )
        rows = []
        for ref, group in sorted(result["duplicated"].items()):
            for row in group:
                rows.append(
                    [
                        ref,
                        row["fecha_emision"],
                        row["documento"],
                        row["cliente_nombre"],
                        fmt(row["total"]),
                    ]
                )
        table(
            pdf,
            ["Numero Sage", "Fecha", "Doc PsKloud", "Cliente", "Monto"],
            [32, 22, 26, 84, 22],
            rows,
            ["L", "L", "L", "L", "R"],
        )

    if result["only_sage"]:
        title(pdf, "En Sage y no en PsKloud")
        table(
            pdf,
            ["Numero Sage", "Fecha", "Cliente", "Monto"],
            [34, 22, 108, 22],
            [[row["ref"], row["date"], row["name"], fmt(row["total"])] for row in result["only_sage"]],
            ["L", "L", "L", "R"],
        )

    pdf.output(str(out_path))


def main() -> int:
    parser = argparse.ArgumentParser(description="Cruce PsKloud vs Sage en PDF")
    parser.add_argument("--sage", type=Path, default=ROOT / "Invoice Register 09232026.pdf")
    parser.add_argument("--psk", type=Path, default=ROOT / "Resultado del Query.txt")
    parser.add_argument("--out", type=Path, default=ROOT / "Cruce PsKloud vs Sage.pdf")
    args = parser.parse_args()

    for path in (args.sage, args.psk):
        if not path.is_file():
            print("No existe: " + str(path))
            return 1

    psk = load_psk(args.psk)
    sage = load_sage(args.sage)
    if not psk or not sage:
        print(f"Sin datos usables (PsKloud {len(psk)}, Sage {len(sage)}).")
        return 1

    result = cross_match(psk, sage)
    build_pdf(result, args.out, args.sage, args.psk)

    missing = len(result["missing_inside"]) + len(result["missing_after"])
    print(
        f"PsKloud {len(psk)} | Sage {len(sage)} | iguales {len(result['full_ok'])}"
        f" | monto distinto {len(result['amount_diff'])} | cliente distinto {len(result['client_diff'])}"
        f" | no cargadas {missing}"
    )
    print("PDF: " + str(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
