"""Cola Ledger Bridge: pending → Sage → ack o nack."""
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
from src.sage_retry import MissingSageItems, find_failed_invoice
from src.invoice_lines import (
    forget_incomplete,
    incomplete_card,
    is_known_incomplete,
    pre_sage_block_reason,
    remember_incomplete,
)

DEFAULT_BASE_URL = "https://bt41axxide.execute-api.us-east-1.amazonaws.com"
# Mismo piso que el Extractor. Sage 2025-2026 esta en periodo sep 2026:
# enero 2025 entra al corte "2025+" pero Sage lo rechaza (periodo cerrado)
# y esas fallas se reintentan, tapando las facturas de esta semana.
MIN_SAGE_DATE = "2026-09-03"
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
    timeout: int = 20,
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
    "item_codigo": ("item_codigo", "codigo", "itemCode", "itemCodigo", "sku", "coditem"),
    "codigo": ("codigo", "item_codigo", "itemCode", "itemCodigo", "sku", "coditem"),
    "dsctounit": ("dsctounit", "dscto_unit", "dsctoUnit", "descuento_unitario"),
    "dsctoprc": ("dsctoprc", "desctoprc", "dscto_prc", "dsctoPrc", "descuento_porcentaje"),
    "sucursal": ("sucursal",),
    "documento": ("documento",),
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


def min_invoice_date(config: dict[str, Any] | None = None) -> str:
    raw = ""
    if config:
        raw = str(ledger_config(config).get("min_fecha") or "").strip()
    env = str(os.environ.get("LEDGER_BRIDGE_MIN_FECHA") or "").strip()
    stamp = (raw or env or MIN_SAGE_DATE)[:10]
    return stamp if len(stamp) >= 10 else MIN_SAGE_DATE


def too_old_for_company(rows: list[dict[str, Any]], min_fecha: str | None = None) -> bool:
    floor = (min_fecha or MIN_SAGE_DATE)[:10]
    stamp = invoice_date(rows)
    return bool(stamp) and stamp < floor


def documento_tail(rows: list[dict[str, Any]]) -> str:
    rec = rows[0] if rows else {}
    fid = str(rec.get("factura_id") or "").strip()
    if ":" in fid:
        return fid.rsplit(":", 1)[-1].strip()
    return str(rec.get("numero_factura") or rec.get("documento") or "").strip()


def skip_not_sales_invoice(rows: list[dict[str, Any]]) -> str:
    """TMP / '0 Recibida' no son FAC emitidas. No crear cliente ni Invoice No. S-00002."""
    rec = rows[0] if rows else {}
    tail = documento_tail(rows).upper()
    num = str(rec.get("numero_factura") or "").strip().lower()
    if tail.startswith("TMP"):
        return "TMP (borrador, no se carga a Sage)"
    if num in ("0 recibida", "recibida") or num.endswith(" recibida"):
        return "documento Recibida (no emitida, no se carga a Sage)"
    return ""


def missing_item_sku(rows: list[dict[str, Any]]) -> str:
    for row in rows:
        sku = str(row.get("item_codigo") or row.get("codigo") or "").strip()
        if sku:
            continue
        desc = str(row.get("descripcion") or "")
        linea = str(row.get("linea") or "1")
        return "linea " + linea + " sin item_codigo | " + desc
    return ""


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


def cloud_inbox_dir(root: Path) -> Path:
    path = root / "state" / "cloud_inbox"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _inbox_job_id(job: dict[str, Any]) -> str:
    ack = str(job.get("ack_id") or "").strip()
    if ack:
        return ack
    rows = job.get("rows") or []
    if rows and isinstance(rows[0], dict):
        return str(rows[0].get("factura_id") or rows[0].get("numero_factura") or "").strip()
    raw = job.get("raw") if isinstance(job.get("raw"), dict) else {}
    return str(raw.get("facturaId") or raw.get("factura_id") or "").strip()


def _safe_inbox_name(job_id: str) -> str:
    raw = (job_id or "job").strip() or "job"
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in raw)
    return safe[:120] or "job"


def save_jobs_to_inbox(root: Path, jobs: list[dict[str, Any]]) -> int:
    inbox = cloud_inbox_dir(root)
    saved = 0
    for idx, job in enumerate(jobs):
        if not isinstance(job, dict):
            continue
        job_id = _inbox_job_id(job) or ("job-" + str(idx + 1))
        path = inbox / (_safe_inbox_name(job_id) + ".json")
        path.write_text(json.dumps(job, ensure_ascii=False, default=str), encoding="utf-8")
        saved += 1
    return saved


def list_inbox_jobs(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    inbox = cloud_inbox_dir(root)
    out: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(inbox.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            out.append((path, data))
    return out


def mark_inbox_done(root: Path, path: Path) -> None:
    if not path.is_file():
        return
    done = cloud_inbox_dir(root) / "done"
    done.mkdir(parents=True, exist_ok=True)
    dest = done / path.name
    if dest.exists():
        dest = done / (path.stem + "-" + str(int(time.time())) + path.suffix)
    try:
        path.replace(dest)
    except OSError:
        try:
            path.unlink()
        except OSError:
            pass


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
                for keep in (
                    "factura_id",
                    "numero_factura",
                    "cliente_codigo",
                    "cliente_nombre",
                    "fecha_emision",
                    "ruc",
                    "total_factura",
                    "subtotal",
                    "itbms_factura",
                    "codigo",
                    "item_codigo",
                    "dsctounit",
                    "dsctoprc",
                    "sucursal",
                    "documento",
                ):
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
    accounted = confirmed + already
    if not ok or (payload and accounted < len(payload)):
        raise RuntimeError(
            "Ledger Bridge ack HTTP "
            + str(status)
            + " confirmed="
            + str(confirmed)
            + " received="
            + str(received)
            + " already="
            + str(already)
            + " "
            + (raw or str(parsed) or "")[:400]
        )
    result["sent"] = len(payload)
    return result


def cloud_failure(message: str) -> tuple[bool, str]:
    """(permanent, error) para POST /v1/nack. Transitorio vuelve a pending."""
    text = " ".join(str(message or "").split())
    lower = text.lower()
    transient = (
        "timeout",
        "timed out",
        "tiempo de espera",
        "connection",
        "conexion",
        "conexión",
        "network",
        "ocupad",
        "http 5",
    )
    if any(token in lower for token in transient):
        return False, ("SAGE_TIMEOUT: " + text)[:500]
    if "cliente" in lower and any(token in lower for token in ("no existe", "no encontr", "no se pudo")):
        return True, ("MISSING_CUSTOMER: " + text)[:500]
    if any(token in lower for token in ("faltan ", "item", "sku", "no existe en sage")):
        return True, ("MISSING_ITEM: " + text)[:500]
    if "descuento" in lower or "4031" in lower:
        return True, ("SAGE_DISCOUNT: " + text)[:500]
    if "itbms" in lower or "incompleta" in lower:
        return True, ("MANUAL_REVIEW: " + text)[:500]
    return False, ("SAGE_ERROR: " + text)[:500]


def nack_ids(
    root: Path,
    config: dict[str, Any],
    items: list[dict[str, Any]],
    *,
    permanent: bool,
) -> dict[str, Any]:
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
        payload.append(
            {
                "branchId": bid,
                "facturaId": fid,
                "error": str(item.get("error") or "SAGE_ERROR")[:500],
            }
        )
    empty = {"ok": True, "sent": 0, "released": 0, "permanent": permanent}
    if not token or not payload:
        return empty
    url = base_url(config) + "/v1/nack"
    status, parsed, raw = _request("POST", url, token, {"items": payload, "permanent": permanent})
    result = parsed if isinstance(parsed, dict) else {}
    released = int(result.get("released") or result.get("confirmed") or 0)
    already = int(result.get("alreadyConsumed") or result.get("alreadyFailed") or 0)
    ok = status < 400 and result.get("ok") is not False
    has_count = any(key in result for key in ("released", "confirmed", "alreadyConsumed", "alreadyFailed"))
    if not ok or (payload and has_count and released + already < 1):
        raise RuntimeError(
            "Ledger Bridge nack HTTP "
            + str(status)
            + " permanent="
            + str(permanent).lower()
            + " released="
            + str(released)
            + " "
            + (raw or str(parsed) or "")[:400]
        )
    result["sent"] = len(payload)
    result["released"] = released
    result["permanent"] = permanent
    return result


def _empty_stats() -> dict[str, int]:
    return {"sent": 0, "skipped": 0, "failed": 0, "files": 0, "cloud_empty": 0, "blocked": 0}


def _merge_stats(into: dict[str, int], extra: dict[str, int]) -> None:
    for key in ("sent", "skipped", "failed", "files", "cloud_empty", "blocked"):
        into[key] = int(into.get(key) or 0) + int(extra.get(key) or 0)


def process_ledger_pending(
    root: Path,
    config: dict[str, Any],
    on_log: Callable[[str], None],
    on_progress: Callable[[int, int, str], None] | None = None,
) -> dict[str, int]:
    """Inbox residual -> GET pending a state/cloud_inbox -> Sage -> ack/nack."""
    stats = _empty_stats()
    if not is_configured(root, config):
        on_log("Sin JWT de Ledger Bridge. Pon config/ledger_bridge.jwt")
        stats["blocked"] = 1
        return stats
    if not sage_ui_running():
        on_log("Automatico: Sage no esta abierto. Deja LYL 2025-2026 abierta.")
        stats["blocked"] = 1
        return stats

    residual = list_inbox_jobs(root)
    if residual:
        on_log("Ledger Bridge: " + str(len(residual)) + " lote(s) pendientes")
        _merge_stats(stats, process_inbox_to_sage(root, config, on_log, on_progress=on_progress))

    n_saved, pull_stats = pull_pending_to_inbox(root, config, on_log)
    _merge_stats(stats, pull_stats)
    if n_saved:
        stats["cloud_empty"] = 0
        _merge_stats(stats, process_inbox_to_sage(root, config, on_log, on_progress=on_progress))
    return stats


def peek_pending_count(root: Path, config: dict[str, Any]) -> int | None:
    """Conteo de GET /v1/pending para el chip Cola nube. None si falla JWT o red."""
    try:
        if not is_configured(root, config):
            return None
        jobs, _raw = fetch_pending(root, config)
        return len(jobs)
    except Exception:
        return None


def pull_pending_to_inbox(
    root: Path,
    config: dict[str, Any],
    on_log: Callable[[str], None],
) -> tuple[int, dict[str, int]]:
    stats = _empty_stats()
    jobs, raw = fetch_pending(root, config)
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
        if empty or not raw or raw.strip() in ("", "[]", "{}", "null"):
            stats["cloud_empty"] = 1
            on_log("Nube sin pendientes. Sigo esperando.")
            return 0, stats
        dump_path = dump_pending(root, raw)
        on_log("Ledger Bridge pending sin facturas usables. " + payload_preview(parsed_preview))
        on_log("JSON: " + str(dump_path))
        return 0, stats

    dump_path = dump_pending(root, raw)
    n_saved = save_jobs_to_inbox(root, jobs)
    on_log("Ledger Bridge: " + str(n_saved) + " lote(s) pendientes")
    on_log("JSON pending: " + str(dump_path))
    keys = [str((job.get("rows") or [{}])[0].get("factura_id") or "") for job in jobs]
    repetidas = sorted({key for key in keys if key and keys.count(key) > 1})
    if repetidas:
        on_log(
            "Nube repitio "
            + str(len(repetidas))
            + " factura(s) en el mismo lote: "
            + ", ".join(repetidas[:5])
        )
    return n_saved, stats


def _progress_steps(entries: list[tuple[Path, dict[str, Any]]], floor: str) -> int:
    total = 0
    for _path, job in entries:
        rows = job.get("rows") or []
        loadable = (
            invoice_ready(rows)
            and not skip_not_sales_invoice(rows)
            and not missing_item_sku(rows)
            and not too_old_for_company(rows, floor)
        )
        total += max(1, len(group_invoices(rows))) if loadable else 1
    return max(1, total)


def process_inbox_to_sage(
    root: Path,
    config: dict[str, Any],
    on_log: Callable[[str], None],
    on_progress: Callable[[int, int, str], None] | None = None,
) -> dict[str, int]:
    """Carga state/cloud_inbox a Sage. Cada lote cierra con ack o nack en la nube."""
    stats = _empty_stats()
    entries = list_inbox_jobs(root)
    if not entries:
        return stats
    ack_items: list[dict[str, str]] = []
    nack_permanent: list[dict[str, str]] = []
    nack_retry: list[dict[str, str]] = []
    handled: list[Path] = []
    floor = min_invoice_date(config)
    old_count = sum(1 for _path, job in entries if too_old_for_company(job.get("rows") or [], floor))
    if old_count:
        on_log("Factura vieja: " + str(old_count) + " anteriores a " + floor + ". No se cargan a Sage.")
    total_steps = _progress_steps(entries, floor)
    step = 0

    def tick(label: str) -> None:
        nonlocal step
        step += 1
        if on_progress:
            on_progress(step, total_steps, label)

    for path, job in entries:
        handled.append(path)
        rows = job.get("rows") or []
        ack_id = str(job.get("ack_id") or "")
        item = _ack_item(job, ack_id)
        loadable = (
            invoice_ready(rows)
            and not skip_not_sales_invoice(rows)
            and not missing_item_sku(rows)
            and not too_old_for_company(rows, floor)
        )
        if not loadable:
            tick(ack_id or path.stem)
        if not invoice_ready(rows):
            on_log("Lote incompleto (sin numero o cliente). No se envia a Sage.")
            on_log("Preview: " + payload_preview(job.get("raw")))
            stats["skipped"] += 1
            stats["files"] += 1
            _queue_nack(
                nack_permanent,
                item,
                "MANUAL_REVIEW: lote incompleto (sin numero o cliente)",
            )
            continue
        skip_tmp = skip_not_sales_invoice(rows)
        if skip_tmp:
            on_log("Omitida " + ack_id + ": " + skip_tmp)
            stats["skipped"] += 1
            stats["files"] += 1
            if item.get("branchId") and item.get("facturaId"):
                ack_items.append(item)
            continue
        sku_err = missing_item_sku(rows)
        if sku_err:
            on_log("ERROR auto " + ack_id + ": " + sku_err)
            stats["failed"] += 1
            stats["files"] += 1
            permanent, error = cloud_failure(sku_err)
            _queue_nack(nack_permanent if permanent else nack_retry, item, error)
            continue
        if too_old_for_company(rows, floor):
            stats["skipped"] += 1
            stats["files"] += 1
            if item.get("branchId") and item.get("facturaId"):
                ack_items.append(item)
            continue
        file_ok = True
        for inv in group_invoices(rows):
            label = str(inv[0].get("factura_id") or inv[0].get("numero_factura") or "?")
            cliente = str(inv[0].get("cliente_nombre") or "")
            tick(label)
            try:
                already = find_sent_invoice(root, inv)
                if already:
                    on_log("Ya enviada, se omite: " + label)
                    stats["skipped"] += 1
                    continue
                held = find_failed_invoice(root, inv)
                if held:
                    on_log(
                        "Ya en cola de fallidas (esperando items): "
                        + label
                        + " | crear en Sage: "
                        + ", ".join(str(s) for s in (held.get("missing_skus") or []))
                    )
                    stats["skipped"] += 1
                    permanent, error = cloud_failure(
                        "faltan items en Sage: "
                        + ", ".join(str(s) for s in (held.get("missing_skus") or []))
                    )
                    _queue_nack(nack_permanent if permanent else nack_retry, item, error)
                    file_ok = False
                    continue
                falta = pre_sage_block_reason(inv)
                if falta:
                    if is_known_incomplete(root, inv):
                        on_log("Sigue incompleta, en espera: " + label)
                        stats["skipped"] += 1
                    else:
                        remember_incomplete(root, inv, falta)
                        on_log("Enviando " + label + " | " + cliente)
                        on_log(incomplete_card(inv, falta))
                        if falta.lower().startswith("itbms"):
                            on_log("ITBMS no cuadra, no se carga a Sage: " + falta)
                        elif falta.lower().startswith("total no cuadra"):
                            on_log("Total no cuadra, no se carga a Sage: " + falta)
                        else:
                            on_log("Factura incompleta, no se carga a Sage: " + falta)
                        stats["failed"] += 1
                    permanent, error = cloud_failure(falta)
                    _queue_nack(nack_permanent if permanent else nack_retry, item, error)
                    file_ok = False
                    continue
                forget_incomplete(root, inv)
                on_log("Enviando " + label + " | " + cliente)
                run_test_company_write(root, inv, on_log=on_log, hold_missing=True)
                stats["sent"] += 1
            except DuplicateSageInvoice:
                on_log("Ya enviada, se omite: " + label)
                stats["skipped"] += 1
            except MissingSageItems as exc:
                on_log(
                    "Items faltantes en Sage. Factura en cola hasta Enviar fallidas. SKU: "
                    + (", ".join(exc.missing) if exc.missing else label)
                )
                stats["failed"] += 1
                permanent, error = cloud_failure(
                    "faltan items en Sage: " + (", ".join(exc.missing) if exc.missing else label)
                )
                _queue_nack(nack_permanent if permanent else nack_retry, item, error)
                file_ok = False
            except Exception as exc:
                on_log("ERROR auto " + label + ": " + str(exc))
                stats["failed"] += 1
                permanent, error = cloud_failure(str(exc))
                _queue_nack(nack_permanent if permanent else nack_retry, item, error)
                file_ok = False
        if file_ok and item.get("branchId") and item.get("facturaId"):
            ack_items.append(item)
        stats["files"] += 1

    # Si la nube no confirmo, los archivos se quedan para el proximo ciclo;
    # find_sent_invoice evita duplicar en Sage.
    if _finish_cloud(root, config, on_log, stats, ack_items, nack_permanent, nack_retry):
        for path in handled:
            mark_inbox_done(root, path)
    return stats


def _queue_nack(bucket: list[dict[str, str]], item: dict[str, Any], error: str) -> None:
    if not item.get("branchId") or not item.get("facturaId"):
        return
    key = (item["branchId"], item["facturaId"])
    if any((row.get("branchId"), row.get("facturaId")) == key for row in bucket):
        return
    bucket.append(
        {
            "branchId": str(item["branchId"]),
            "facturaId": str(item["facturaId"]),
            "error": error[:500],
        }
    )


def _finish_cloud(
    root: Path,
    config: dict[str, Any],
    on_log: Callable[[str], None],
    stats: dict[str, int],
    ack_items: list[dict[str, str]],
    nack_permanent: list[dict[str, str]],
    nack_retry: list[dict[str, str]],
) -> bool:
    ok = True
    blocked = {
        (row.get("branchId"), row.get("facturaId"))
        for row in nack_permanent + nack_retry
    }
    ack_items = [
        item
        for item in ack_items
        if (item.get("branchId"), item.get("facturaId")) not in blocked
    ]
    if ack_items:
        try:
            ack_res = ack_ids(root, config, ack_items)
            on_log(
                "Ledger Bridge ack OK: sent="
                + str(ack_res.get("sent") or len(ack_items))
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
            ok = False
    for permanent, batch in ((True, nack_permanent), (False, nack_retry)):
        if not batch:
            continue
        try:
            nack_res = nack_ids(root, config, batch, permanent=permanent)
            on_log(
                "Ledger Bridge nack OK: permanent="
                + str(permanent).lower()
                + " sent="
                + str(nack_res.get("sent") or len(batch))
                + " released="
                + str(nack_res.get("released") or 0)
            )
        except Exception as exc:
            on_log("Ledger Bridge nack fallo: " + str(exc))
            stats["failed"] += 1
            ok = False
    return ok
