from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import pdfplumber
except ImportError:
    pdfplumber = None  # type: ignore[assignment]


def load_pdf_config(root: Path) -> dict[str, Any]:
    path = root / "config" / "pdf_extractor.json"
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _first_match(text: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.MULTILINE | re.DOTALL)
        if not match:
            continue
        if match.lastindex:
            return match.group(1).strip()
        return match.group(0).strip()
    return None


def _parse_money(value: str | None) -> float | None:
    if value is None:
        return None
    cleaned = value.replace(",", "").replace("$", "").replace("B/.", "").strip()
    if not cleaned:
        return None
    try:
        return round(float(cleaned), 2)
    except ValueError:
        return None


def _parse_labeled_amount(text: str, patterns: list[str], *, exclude_subtotal: bool = False) -> float | None:
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.MULTILINE | re.IGNORECASE):
            if exclude_subtotal:
                prefix = text[max(0, match.start() - 4) : match.start()].lower()
                if prefix.endswith("sub"):
                    continue
            if match.lastindex:
                amount = _parse_money(match.group(1))
            else:
                amount = _parse_money(match.group(0))
            if amount is not None:
                return amount
    return None


def _normalize_date(value: str | None) -> str:
    if not value:
        return datetime.now().strftime("%Y-%m-%d")
    value = value.strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return value


def _normalize_invoice_number(value: str | None, fallback: str) -> str:
    if not value:
        return fallback
    cleaned = re.sub(r"\s+", "-", value.strip().upper())
    cleaned = cleaned.replace("FE--", "FE-")
    if cleaned.startswith("FE") and not cleaned.startswith("FE-"):
        cleaned = cleaned.replace("FE", "FE-", 1)
    return cleaned


def _read_pdf_content(path: Path) -> tuple[str, list[list[list[str | None]]]]:
    if pdfplumber is None:
        raise RuntimeError("Falta pdfplumber. Ejecuta: pip install pdfplumber")

    text_parts: list[str] = []
    tables: list[list[list[str | None]]] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text_parts.append(page.extract_text() or "")
            for table in page.extract_tables() or []:
                if table:
                    tables.append(table)
    return "\n".join(text_parts), tables


def _match_header_columns(cells: list[str], headers_cfg: dict[str, list[str]]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for idx, raw in enumerate(cells):
        cell = raw.strip().lower()
        if not cell:
            continue
        for field, aliases in headers_cfg.items():
            if field in mapping:
                continue
            if any(alias in cell for alias in aliases):
                mapping[field] = idx
    needed = {"description", "amount"}
    if not needed.issubset(mapping.keys()):
        return {}
    return mapping


def _cell_value(row: list[str | None], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    return str(row[index] or "").strip()


def _should_skip_line(description: str, skip_keywords: list[str]) -> bool:
    lowered = description.lower()
    if len(lowered) < 2:
        return True
    return any(keyword in lowered for keyword in skip_keywords)


def _lines_from_tables(
    tables: list[list[list[str | None]]],
    pdf_config: dict[str, Any],
) -> list[dict[str, Any]]:
    headers_cfg = pdf_config["line_table_headers"]
    skip_keywords = pdf_config.get("skip_line_keywords", [])
    default_tax = float(pdf_config["defaults"].get("tasa_itbms", 0.07))
    lines: list[dict[str, Any]] = []

    for table in tables:
        if not table or len(table) < 2:
            continue

        header_idx: int | None = None
        col_map: dict[str, int] = {}
        for idx, row in enumerate(table):
            cells = [str(cell or "") for cell in row]
            mapping = _match_header_columns(cells, headers_cfg)
            if mapping:
                header_idx = idx
                col_map = mapping
                break

        if header_idx is None:
            continue

        line_no = 0
        for row in table[header_idx + 1 :]:
            description = _cell_value(row, col_map.get("description"))
            amount = _parse_money(_cell_value(row, col_map.get("amount")))
            if amount is None or _should_skip_line(description, skip_keywords):
                continue

            qty_raw = _cell_value(row, col_map.get("quantity"))
            price_raw = _cell_value(row, col_map.get("unit_price"))
            quantity = _parse_money(qty_raw) if qty_raw else None
            unit_price = _parse_money(price_raw) if price_raw else None

            if quantity is None or quantity <= 0:
                quantity = 1.0
            if unit_price is None:
                unit_price = round(amount / quantity, 2)

            line_no += 1
            lines.append(
                {
                    "linea": line_no,
                    "descripcion": description,
                    "cantidad": quantity,
                    "precio_unitario": unit_price,
                    "tasa_itbms": default_tax,
                    "total_linea": amount,
                }
            )

    return lines


def _lines_from_text(text: str, pdf_config: dict[str, Any]) -> list[dict[str, Any]]:
    skip_keywords = pdf_config.get("skip_line_keywords", [])
    default_tax = float(pdf_config["defaults"].get("tasa_itbms", 0.07))
    lines: list[dict[str, Any]] = []
    patterns = [
        re.compile(
            r"^(?P<qty>\d+(?:\.\d+)?)\s+(?P<desc>.+?)\s+(?P<price>\d+(?:\.\d+)?)\s+(?P<total>\d+(?:\.\d+)?)\s*$"
        ),
        re.compile(
            r"^(?P<desc>.+?)\s+(?P<qty>\d+(?:\.\d+)?)\s+(?P<price>\d+(?:\.\d+)?)\s+(?P<total>\d+(?:\.\d+)?)\s*$"
        ),
    ]

    for raw_line in text.splitlines():
        line = re.sub(r"\s{2,}", "  ", raw_line.strip())
        if not line:
            continue

        match = None
        for pattern in patterns:
            match = pattern.match(line)
            if match:
                break
        if not match:
            continue

        description = match.group("desc").strip()
        if _should_skip_line(description, skip_keywords):
            continue

        quantity = float(match.group("qty"))
        unit_price = float(match.group("price"))
        total_linea = float(match.group("total"))
        lines.append(
            {
                "linea": len(lines) + 1,
                "descripcion": description,
                "cantidad": quantity,
                "precio_unitario": unit_price,
                "tasa_itbms": default_tax,
                "total_linea": total_linea,
            }
        )

    return lines


def _build_rows_from_parsed_invoice(
    *,
    factura_id: int,
    numero_factura: str,
    fecha_emision: str,
    cliente_nombre: str,
    cliente_codigo: str,
    ruc: str,
    subtotal: float,
    itbms_factura: float,
    total_factura: float,
    lines: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in lines:
        rows.append(
            {
                "factura_id": factura_id,
                "numero_factura": numero_factura,
                "fecha_emision": fecha_emision,
                "subtotal": subtotal,
                "itbms_factura": itbms_factura,
                "total_factura": total_factura,
                "cliente_codigo": cliente_codigo,
                "cliente_nombre": cliente_nombre,
                "ruc": ruc,
                "linea": line["linea"],
                "descripcion": line["descripcion"],
                "cantidad": line["cantidad"],
                "precio_unitario": line["precio_unitario"],
                "tasa_itbms": line["tasa_itbms"],
                "total_linea": line["total_linea"],
                "source_file": line.get("source_file", ""),
            }
        )
    return rows


def parse_invoice_document(
    text: str,
    tables: list[list[list[str | None]]],
    pdf_config: dict[str, Any],
    *,
    source_name: str = "",
    factura_id: int | None = None,
) -> list[dict[str, Any]]:
    patterns = pdf_config["patterns"]
    defaults = pdf_config["defaults"]

    numero = _normalize_invoice_number(
        _first_match(text, patterns["invoice_number"]),
        fallback=Path(source_name).stem if source_name else "PDF-0001",
    )
    fecha = _normalize_date(_first_match(text, patterns["date"]))
    ruc = _first_match(text, patterns["ruc"]) or "CF"
    customer = _first_match(text, patterns["customer"]) or "Cliente PDF"
    customer = re.sub(r"\s+", " ", customer).strip(" :-")

    lines = _lines_from_tables(tables, pdf_config)
    if not lines:
        lines = _lines_from_text(text, pdf_config)

    if not lines:
        raise ValueError(
            "No se encontraron lineas de detalle en el PDF. "
            "Verifica que el PDF tenga tabla de productos o lineas con cantidad/precio/total."
        )

    subtotal = _parse_labeled_amount(text, patterns["subtotal"])
    itbms = _parse_labeled_amount(text, patterns["itbms"])
    total = _parse_labeled_amount(text, patterns["total"], exclude_subtotal=True)

    computed_subtotal = round(sum(float(line["total_linea"]) for line in lines), 2)
    computed_itbms = round(
        sum(float(line["total_linea"]) * float(line["tasa_itbms"]) for line in lines),
        2,
    )

    if subtotal is None:
        subtotal = computed_subtotal
    if itbms is None:
        itbms = computed_itbms
    if total is None:
        total = round(subtotal + itbms, 2)

    invoice_id = factura_id if factura_id is not None else abs(hash(numero)) % 9_000_000 + 1_000_000
    customer_code = f"{defaults.get('cliente_codigo_prefix', 'PDF')}-{re.sub(r'[^A-Z0-9]', '', customer.upper())[:12] or 'CLIENT'}"

    if source_name:
        for line in lines:
            line["source_file"] = source_name

    return _build_rows_from_parsed_invoice(
        factura_id=invoice_id,
        numero_factura=numero,
        fecha_emision=fecha,
        cliente_nombre=customer,
        cliente_codigo=customer_code,
        ruc=ruc,
        subtotal=subtotal,
        itbms_factura=itbms,
        total_factura=total,
        lines=lines,
    )


def extract_invoices_from_pdf(path: Path, root: Path) -> list[dict[str, Any]]:
    pdf_config = load_pdf_config(root)
    text, tables = _read_pdf_content(path)
    if not text.strip() and not tables:
        raise ValueError(f"El PDF no contiene texto legible: {path.name}. Puede ser escaneado sin OCR.")

    return parse_invoice_document(
        text,
        tables,
        pdf_config,
        source_name=path.name,
    )


def extract_pdf_with_meta(path: Path, root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    pdf_config = load_pdf_config(root)
    text, tables = _read_pdf_content(path)
    if not text.strip() and not tables:
        raise ValueError(
            f"El PDF '{path.name}' no contiene texto seleccionable. "
            "Si es una imagen escaneada, necesitas OCR antes de importar."
        )
    rows = parse_invoice_document(text, tables, pdf_config, source_name=path.name)
    first = rows[0] if rows else {}
    meta = {
        "archivo": path.name,
        "numero_factura": first.get("numero_factura", ""),
        "fecha": first.get("fecha_emision", ""),
        "cliente": first.get("cliente_nombre", ""),
        "ruc": first.get("ruc", ""),
        "subtotal": first.get("subtotal", ""),
        "itbms": first.get("itbms_factura", ""),
        "total": first.get("total_factura", ""),
        "lineas": len(rows),
        "detected_fields": {
            "Factura": first.get("numero_factura", ""),
            "Fecha": first.get("fecha_emision", ""),
            "Cliente": first.get("cliente_nombre", ""),
            "RUC": first.get("ruc", ""),
            "Subtotal": first.get("subtotal", ""),
            "ITBMS": first.get("itbms_factura", ""),
            "Total": first.get("total_factura", ""),
        },
        "raw_text_preview": text[:2500],
    }
    return rows, meta


def extract_invoices_from_pdfs(paths: list[Path], root: Path) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    all_rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    combined_meta: dict[str, Any] = {"archivos": [], "detected_fields": {}, "raw_text_preview": ""}

    for index, path in enumerate(paths, start=1):
        try:
            rows, meta = extract_pdf_with_meta(path, root)
            offset = index * 10_000
            for row in rows:
                row["factura_id"] = int(row["factura_id"]) + offset
            all_rows.extend(rows)
            combined_meta["archivos"].append(path.name)
            combined_meta["detected_fields"][path.name] = meta.get("detected_fields", {})
            preview = meta.get("raw_text_preview", "")
            if preview:
                combined_meta["raw_text_preview"] += f"\n\n--- {path.name} ---\n{preview[:1200]}"
        except Exception as exc:
            warnings.append(f"{path.name}: {exc}")

    if not all_rows:
        detail = "\n".join(warnings) if warnings else "No se pudo leer ningun PDF."
        raise ValueError(detail)

    return all_rows, warnings, combined_meta
