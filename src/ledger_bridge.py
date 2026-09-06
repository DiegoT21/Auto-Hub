"""Cola Ledger Bridge: pending → Sage → ack."""
from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from typing import Any, Callable
from pathlib import Path

from src.extractor_inbox import group_invoices
from src.sage_sdk_write import (
    DuplicateSageInvoice,
    _coerce_row,
    find_sent_invoice,
    run_test_company_write,
    sage_ui_running,
)

DEFAULT_BASE_URL = "https://bt41axxide.execute-api.us-east-1.amazonaws.com"
_CTX = ssl.create_default_context()


def ledger_config(config: dict[str, Any]) -> dict[str, Any]:
    block = config.get("ledger_bridge")
    return block if isinstance(block, dict) else {}


def base_url(config: dict[str, Any]) -> str:
    raw = str(ledger_config(config).get("base_url") or os.environ.get("LEDGER_BRIDGE_URL") or DEFAULT_BASE_URL)
    return raw.strip().rstrip("/")


def credential_path(root: Path, config: dict[str, Any]) -> Path:
    rel = str(ledger_config(config).get("credential_file") or "config/ledger_bridge.jwt").strip()
    path = Path(rel)
    return path if path.is_absolute() else (root / path)


def load_jwt(root: Path, config: dict[str, Any]) -> str:
    env = str(os.environ.get("LEDGER_BRIDGE_JWT") or "").strip()
    if env:
        return env
    path = credential_path(root, config)
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8").strip()
    if not text or text.startswith("#"):
        return ""
    return text.splitlines()[0].strip()


def is_configured(root: Path, config: dict[str, Any]) -> bool:
    return bool(load_jwt(root, config))


def _request(
    method: str,
    url: str,
    token: str,
    body: dict[str, Any] | None = None,
    timeout: int = 30,
) -> tuple[int, Any, str]:
    data = None
    headers = {
        "Authorization": "Bearer " + token,
        "Accept": "application/json",
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            status = int(resp.status)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        status = int(exc.code)
    parsed: Any = None
    if raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = raw
    return status, parsed, raw


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


_FIELD_ALIASES = {
    "factura_id": ("factura_id", "facturaId", "invoice_id", "invoiceId", "id_factura"),
    "numero_factura": (
        "numero_factura",
        "numeroFactura",
        "numeroFe",
        "invoice_number",
        "invoiceNumber",
        "Invoice Number",
        "numero",
    ),
    "fecha_emision": (
        "fecha_emision",
        "fechaEmision",
        "invoice_date",
        "invoiceDate",
        "Date",
        "fecha",
    ),
    "cliente_codigo": (
        "cliente_codigo",
        "clienteCodigo",
        "customer_id",
        "customerId",
        "Customer ID",
        "codigo_cliente",
    ),
    "cliente_nombre": (
        "cliente_nombre",
        "clienteNombre",
        "customer_name",
        "customerName",
        "Customer Name",
        "nombre_cliente",
    ),
    "ruc": ("ruc", "tax_id", "taxId"),
    "descripcion": ("descripcion", "description", "Description", "item"),
    "cantidad": ("cantidad", "quantity", "Quantity", "qty"),
    "precio_unitario": (
        "precio_unitario",
        "precioUnitario",
        "unit_price",
        "unitPrice",
        "Unit Price",
    ),
    "total_linea": ("total_linea", "totalLinea", "line_amount", "Line Amount", "amount"),
    "total_factura": ("total_factura", "totalFactura", "invoice_total", "Invoice Total", "total"),
    "subtotal": ("subtotal", "Subtotal"),
    "itbms_factura": ("itbms_factura", "itbmsFactura", "tax_amount", "Tax Amount"),
    "tasa_itbms": ("tasa_itbms", "tasaItbms"),
    "linea": ("linea", "line", "line_number"),
}


def _first(rec: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        if name in rec and rec[name] not in (None, ""):
            return rec[name]
    return None


def _normalize_record(rec: dict[str, Any]) -> dict[str, Any]:
    out = dict(rec)
    for dest, names in _FIELD_ALIASES.items():
        if not out.get(dest):
            val = _first(rec, names)
            if val not in (None, ""):
                out[dest] = val
    return out


def _row_from_item(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    rec = item.get("record") if isinstance(item.get("record"), dict) else item
    if isinstance(item.get("invoice"), dict) and not (
        rec.get("factura_id") or rec.get("numero_factura")
    ):
        rec = item["invoice"]
    if not isinstance(rec, dict):
        return None
    rec = _normalize_record(rec)
    if not (rec.get("factura_id") or rec.get("numero_factura")):
        return None
    return _coerce_row(rec)


def invoice_date(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    return str(rows[0].get("fecha_emision") or "")[:10]


def too_old_for_company(rows: list[dict[str, Any]], min_fecha: str = "2025-01-01") -> bool:
    stamp = invoice_date(rows)
    return bool(stamp) and stamp < min_fecha


def invoice_ready(rows: list[dict[str, Any]]) -> bool:
    for row in rows:
        has_num = bool(str(row.get("factura_id") or row.get("numero_factura") or "").strip())
        has_cust = bool(str(row.get("cliente_codigo") or row.get("cliente_nombre") or "").strip())
        if has_num and has_cust:
            return True
    return False


def payload_preview(payload: Any) -> str:
    if isinstance(payload, dict):
        return "obj keys=" + ",".join(list(payload.keys())[:24])
    if isinstance(payload, list):
        n = len(payload)
        first = payload[0] if n else None
        if isinstance(first, dict):
            return "list[" + str(n) + "] keys=" + ",".join(list(first.keys())[:24])
        return "list[" + str(n) + "]"
    return type(payload).__name__


def dump_pending(root: Path, raw: str) -> Path:
    path = root / "state" / "ledger_pending_last.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(raw or "null", encoding="utf-8")
    return path


def _ack_token(item: dict[str, Any]) -> str:
    item = _normalize_record(item) if isinstance(item, dict) else {}
    for key in ("id", "ack_id", "invoice_id", "batch_id", "jti", "facturaId", "factura_id"):
        val = item.get(key)
        if val not in (None, ""):
            return str(val)
    return str(item.get("numero_factura") or item.get("numeroFactura") or "").strip()


def _branch_id(raw: Any) -> str:
    if isinstance(raw, dict):
        return str(raw.get("branchId") or raw.get("branch_id") or "").strip()
    return ""


def _ack_item(job: dict[str, Any], factura_id: str = "") -> dict[str, Any]:
    raw = job.get("raw") if isinstance(job.get("raw"), dict) else {}
    bid = str(raw.get("branchId") or job.get("branch_id") or "").strip()
    fid = str(raw.get("facturaId") or factura_id or job.get("ack_id") or "").strip()
    if not bid or not fid:
        return {}
    return {"branchId": bid, "facturaId": fid}


def _job(ack_id: str, rows: list[dict[str, Any]], raw: Any) -> dict[str, Any]:
    return {"ack_id": ack_id, "rows": rows, "raw": raw, "branch_id": _branch_id(raw)}


def pending_jobs(payload: Any) -> list[dict[str, Any]]:
    """Normaliza GET /v1/pending a [{ack_id, rows}]."""
    if payload is None or payload == "":
        return []
    if isinstance(payload, dict):
        for key in ("pending", "invoices", "items", "batches", "data"):
            if key in payload:
                return pending_jobs(payload[key])
        if isinstance(payload.get("records"), list):
            rows = [row for row in (_row_from_item(item) for item in payload["records"]) if row]
            if rows:
                ack_id = _ack_token(payload) or str(rows[0].get("factura_id") or "")
                return [_job(ack_id, rows, payload)]
        if payload.get("factura_id") or payload.get("record"):
            payload = [payload]
        else:
            return []
    jobs: list[dict[str, Any]] = []
    line_rows: list[dict[str, Any]] = []
    for item in _as_list(payload):
        if not isinstance(item, dict):
            continue
        line_blob = item.get("records") or item.get("lines")
        if isinstance(line_blob, list) and line_blob:
            header = _normalize_record(item)
            rows = []
            for line in line_blob:
                if not isinstance(line, dict):
                    continue
                merged = dict(header)
                merged.update(_normalize_record(line))
                for keep in ("factura_id", "numero_factura", "cliente_codigo", "cliente_nombre", "fecha_emision", "ruc", "total_factura", "subtotal", "itbms_factura"):
                    if header.get(keep) and not merged.get(keep):
                        merged[keep] = header[keep]
                if header.get("factura_id"):
                    merged["factura_id"] = header["factura_id"]
                if not (merged.get("factura_id") or merged.get("numero_factura")):
                    continue
                rows.append(_coerce_row(merged))
            if not rows:
                continue
            ack_id = _ack_token(item) or str(rows[0].get("factura_id") or "")
            jobs.append(_job(ack_id, rows, item))
            continue
        row = _row_from_item(item)
        if row:
            line_rows.append(row)
    if line_rows and not jobs:
        ack_id = str(line_rows[0].get("factura_id") or line_rows[0].get("numero_factura") or "")
        return [_job(ack_id, line_rows, payload)]
    if line_rows:
        ack_id = str(line_rows[0].get("factura_id") or "")
        jobs.append(_job(ack_id, line_rows, payload))
    return jobs


def fetch_pending(root: Path, config: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    token = load_jwt(root, config)
    if not token:
        return [], ""
    url = base_url(config) + "/v1/pending"
    status, parsed, raw = _request("GET", url, token)
    if status == 204:
        return [], ""
    if status >= 400:
        snippet = raw[:300] if raw else ""
        raise RuntimeError("Ledger Bridge pending HTTP " + str(status) + (" " + snippet if snippet else ""))
    return pending_jobs(parsed), raw


def ack_ids(root: Path, config: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    token = load_jwt(root, config)
    payload = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        bid = str(item.get("branchId") or "").strip()
        fid = str(item.get("facturaId") or "").strip()
        key = (bid, fid)
        if not bid or not fid or key in seen:
            continue
        seen.add(key)
        payload.append({"branchId": bid, "facturaId": fid})
    empty = {"ok": True, "received": 0, "confirmed": 0, "alreadyConsumed": 0, "sent": 0}
    if not token or not payload:
        return empty
    url = base_url(config) + "/v1/ack"
    status, parsed, raw = _request("POST", url, token, {"items": payload})
    result = parsed if isinstance(parsed, dict) else {}
    confirmed = int(result.get("confirmed") or 0)
    received = int(result.get("received") or 0)
    already = int(result.get("alreadyConsumed") or 0)
    ok = status < 400 and result.get("ok") is not False
    if not ok or (payload and confirmed < 1 and already < 1):
        raise RuntimeError(
            "Ledger Bridge ack HTTP "
            + str(status)
            + " confirmed="
            + str(confirmed)
            + " received="
            + str(received)
            + " "
            + (raw or str(parsed) or "")[:400]
        )
    result["sent"] = len(payload)
    return result


def process_ledger_pending(
    root: Path,
    config: dict[str, Any],
    on_log: Callable[[str], None],
) -> dict[str, int]:
    stats = {"sent": 0, "skipped": 0, "failed": 0, "files": 0}
    if not is_configured(root, config):
        return stats
    if not sage_ui_running():
        return stats

    jobs, raw = fetch_pending(root, config)
    dump_path = dump_pending(root, raw)
    parsed_preview: Any = None
    if raw.strip():
        try:
            parsed_preview = json.loads(raw)
        except json.JSONDecodeError:
            parsed_preview = raw[:200]
    if not jobs:
        empty = False
        if isinstance(parsed_preview, dict):
            inv = parsed_preview.get("invoices")
            cnt = parsed_preview.get("count")
            empty = inv == [] or cnt == 0
        if raw and raw.strip() not in ("", "[]", "{}", "null") and not empty:
            on_log("Ledger Bridge pending sin facturas usables. " + payload_preview(parsed_preview))
            on_log("JSON: " + str(dump_path))
        return stats

    on_log("Ledger Bridge: " + str(len(jobs)) + " lote(s) pendientes")
    on_log("JSON pending: " + str(dump_path))
    done_items: list[dict[str, str]] = []
    old_count = sum(1 for job in jobs if too_old_for_company(job.get("rows") or []))
    if old_count:
        on_log("Factura vieja: " + str(old_count) + " de anos atras. No se cargan a Sage 2025-2026.")

    for job in jobs:
        rows = job["rows"]
        ack_id = str(job.get("ack_id") or "")
        item = _ack_item(job, ack_id)
        if not invoice_ready(rows):
            on_log("Lote incompleto (sin numero o cliente). No se envia a Sage.")
            on_log("Preview: " + payload_preview(job.get("raw")))
            stats["skipped"] += 1
            stats["files"] += 1
            if item.get("branchId") and item.get("facturaId"):
                done_items.append(item)
            continue
        if too_old_for_company(rows):
            stats["skipped"] += 1
            stats["files"] += 1
            if item.get("branchId") and item.get("facturaId"):
                done_items.append(item)
            continue
        file_ok = True
        for inv in group_invoices(rows):
            label = str(inv[0].get("factura_id") or inv[0].get("numero_factura") or "?")
            cliente = str(inv[0].get("cliente_nombre") or "")
            try:
                already = find_sent_invoice(root, inv)
                if already:
                    on_log("Ya enviada, se omite: " + label)
                    stats["skipped"] += 1
                    continue
                on_log("Enviando " + label + " | " + cliente)
                run_test_company_write(root, inv, on_log=on_log)
                stats["sent"] += 1
            except DuplicateSageInvoice:
                on_log("Ya enviada, se omite: " + label)
                stats["skipped"] += 1
            except Exception as exc:
                on_log("ERROR auto " + label + ": " + str(exc))
                stats["failed"] += 1
                file_ok = False
        if file_ok and item.get("branchId") and item.get("facturaId"):
            done_items.append(item)
        stats["files"] += 1

    if done_items:
        try:
            ack_res = ack_ids(root, config, done_items)
            on_log(
                "Ledger Bridge ack OK: sent="
                + str(ack_res.get("sent") or len(done_items))
                + " confirmed="
                + str(ack_res.get("confirmed") or 0)
                + " received="
                + str(ack_res.get("received") or 0)
                + " already="
                + str(ack_res.get("alreadyConsumed") or 0)
            )
        except Exception as exc:
            on_log("Ledger Bridge ack fallo: " + str(exc))
            stats["failed"] += 1
    return stats
