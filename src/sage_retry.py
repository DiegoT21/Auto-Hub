"""Cola de facturas que fallaron porque el item no existe en Sage."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

FAILED_NAME = "sage_failed.json"
PENDING_ITEMS_NAME = "items_pendientes.txt"


class MissingSageItems(RuntimeError):
    """Fail 16: hay que crear el SKU en Sage y pulsar Enviar fallidas."""

    def __init__(self, message: str, missing: list[str] | None = None):
        super().__init__(message)
        self.missing = [str(s).strip() for s in (missing or []) if str(s).strip()]


def _failed_path(root: Path) -> Path:
    path = root / "state" / FAILED_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _invoice_key(rows: list[dict[str, Any]]) -> str:
    rec = rows[0] if rows else {}
    return str(rec.get("factura_id") or rec.get("numero_factura") or "").strip()


def load_failed(root: Path) -> dict[str, Any]:
    path = _failed_path(root)
    if not path.exists():
        return {"invoices": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"invoices": {}}
    if not isinstance(data, dict):
        return {"invoices": {}}
    inv = data.get("invoices")
    if not isinstance(inv, dict):
        data["invoices"] = {}
    return data


def _save_failed(root: Path, data: dict[str, Any]) -> None:
    _failed_path(root).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    write_pending_items_report(root)


def list_failed(root: Path) -> list[dict[str, Any]]:
    data = load_failed(root)
    items = list((data.get("invoices") or {}).values())
    items.sort(key=lambda e: str(e.get("saved_at") or ""))
    return items


def failed_count(root: Path) -> int:
    return len(load_failed(root).get("invoices") or {})


def pending_cards(root: Path) -> list[dict[str, Any]]:
    """The UI and retry button both show the actual persisted retry queue."""
    cards = []
    for entry in list_failed(root):
        rows = entry.get("rows") or []
        first = rows[0] if rows else {}
        missing = {str(s).upper() for s in entry.get("missing_skus") or []}
        cards.append({
            "ok": False,
            "ref": first.get("documento") or entry.get("numero_factura") or entry.get("key"),
            "date": entry.get("fecha", ""),
            "customer_name": entry.get("cliente", ""),
            "customer_id": first.get("cliente_codigo", ""),
            "total": entry.get("total", ""),
            "detail": entry.get("error", ""),
            "lines": [{"n": row.get("linea") or i + 1,
                       "sku": row.get("item_codigo") or row.get("codigo") or "",
                       "qty": row.get("cantidad", ""),
                       "ok": str(row.get("item_codigo") or row.get("codigo") or "").upper() not in missing,
                       "err": "Item pendiente en Sage"}
                      for i, row in enumerate(rows)],
        })
    return cards


def find_failed_invoice(root: Path, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    key = _invoice_key(rows)
    if not key:
        return None
    return (load_failed(root).get("invoices") or {}).get(key)


def parse_missing_skus(rows: list[dict[str, Any]], text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    def add(sku: str) -> None:
        s = str(sku or "").strip()
        if not s:
            return
        u = s.upper()
        if u in seen:
            return
        seen.add(u)
        found.append(s)

    blob = text or ""
    for line in blob.splitlines():
        raw = line.strip()
        if not raw.lower().startswith("[card]"):
            continue
        payload = raw.split("]", 1)[-1].strip()
        try:
            data = json.loads(payload)
        except Exception:
            continue
        for ln in data.get("lines") or []:
            if isinstance(ln, dict) and not ln.get("ok"):
                add(str(ln.get("sku") or ""))
    for match in re.finditer(r"codigo=([^\s|]+)", blob, flags=re.I):
        add(match.group(1))
    if not found:
        for row in rows:
            add(str(row.get("item_codigo") or row.get("codigo") or ""))
    return found


def _missing_detail(rows: list[dict[str, Any]], missing: list[str]) -> list[dict[str, Any]]:
    want = {s.upper() for s in missing}
    out: list[dict[str, Any]] = []
    for row in rows:
        sku = str(row.get("item_codigo") or row.get("codigo") or "").strip()
        if sku.upper() not in want:
            continue
        out.append(
            {
                "linea": row.get("linea") or "",
                "sku": sku,
                "descripcion": str(row.get("descripcion") or ""),
                "cantidad": row.get("cantidad") or "",
            }
        )
    if out:
        return out
    return [{"linea": "", "sku": sku, "descripcion": "", "cantidad": ""} for sku in missing]


def queue_failed_invoice(
    root: Path,
    rows: list[dict[str, Any]],
    error: str,
    log_text: str = "",
) -> dict[str, Any]:
    key = _invoice_key(rows)
    if not key:
        key = "sin-id-" + datetime.now().strftime("%Y%m%d%H%M%S")
    rec = rows[0] if rows else {}
    missing = parse_missing_skus(rows, log_text + "\n" + error)
    entry = {
        "key": key,
        "factura_id": str(rec.get("factura_id") or ""),
        "numero_factura": str(rec.get("numero_factura") or ""),
        "cliente": str(rec.get("cliente_nombre") or rec.get("cliente_codigo") or ""),
        "fecha": str(rec.get("fecha_emision") or "")[:10],
        "total": rec.get("total_factura") or "",
        "sucursal": str(rec.get("sucursal") or ""),
        "missing_skus": missing,
        "missing_detail": _missing_detail(rows, missing),
        "error": (error or "")[:500],
        "saved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rows": rows,
    }
    data = load_failed(root)
    data.setdefault("invoices", {})[key] = entry
    _save_failed(root, data)
    return entry


def remove_failed(root: Path, key: str) -> None:
    data = load_failed(root)
    inv = data.get("invoices") or {}
    if key in inv:
        del inv[key]
        data["invoices"] = inv
        _save_failed(root, data)


def write_pending_items_report(root: Path) -> Path:
    from src.session_log import log_dir

    path = log_dir(root) / PENDING_ITEMS_NAME
    items = list_failed(root)
    lines = [
        "Items que hay que crear en Sage (Maintain Inventory Items)",
        "==========================================================",
        "Actualizado: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "",
    ]
    if not items:
        lines.append("No hay facturas fallidas esperando items.")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path
    by_sku: dict[str, list[str]] = {}
    for entry in items:
        docs = str(entry.get("numero_factura") or entry.get("factura_id") or entry.get("key") or "")
        for sku in entry.get("missing_skus") or []:
            by_sku.setdefault(str(sku), [])
            if docs and docs not in by_sku[str(sku)]:
                by_sku[str(sku)].append(docs)
    lines.append("SKU a crear:")
    for sku in sorted(by_sku):
        lines.append("  - " + sku + "  (facturas: " + ", ".join(by_sku[sku]) + ")")
    lines.append("")
    lines.append("Facturas en cola:")
    for entry in items:
        lines.append(
            "  - "
            + str(entry.get("numero_factura") or entry.get("key") or "")
            + " | "
            + str(entry.get("cliente") or "")
            + " | items: "
            + ", ".join(str(s) for s in (entry.get("missing_skus") or []))
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def failed_confirm_text(root: Path) -> str:
    items = list_failed(root)
    if not items:
        return "No hay facturas fallidas."
    skus: list[str] = []
    seen: set[str] = set()
    for entry in items:
        for sku in entry.get("missing_skus") or []:
            u = str(sku).upper()
            if u in seen:
                continue
            seen.add(u)
            skus.append(str(sku))
    bits = [
        "Hay "
        + str(len(items))
        + " factura(s) esperando items en Sage.",
        "",
        "Los dueños tienen que crear estos SKU en Maintain Inventory Items:",
        ", ".join(skus) if skus else "(ver logs/items_pendientes.txt)",
        "",
        "Cuando ya esten en Sage, Confirmar para reenviarlas.",
        "No se crean items desde Auto-Hub.",
    ]
    return "\n".join(bits)


def retry_failed_invoices(
    root: Path,
    on_log: Callable[[str], None] | None = None,
) -> dict[str, int]:
    from src.sage_sdk_write import run_test_company_write, sage_ui_running

    def log(msg: str) -> None:
        if on_log:
            on_log(msg)

    if not sage_ui_running():
        raise RuntimeError("Abre Sage 50 en LYL CONSTRUCTIONS SUPPLY INC 2025-2026.")
    items = list_failed(root)
    if not items:
        log("No hay facturas fallidas para reenviar.")
        return {"sent": 0, "failed": 0, "remaining": 0}
    sent = 0
    failed = 0
    log("Reenviando " + str(len(items)) + " factura(s) fallida(s)...")
    for entry in items:
        rows = list(entry.get("rows") or [])
        key = str(entry.get("key") or _invoice_key(rows))
        label = str(entry.get("numero_factura") or entry.get("factura_id") or key)
        cliente = str(entry.get("cliente") or "")
        try:
            log("Enviando fallida " + label + " | " + cliente)
            run_test_company_write(root, rows, on_log=log, hold_missing=True)
            remove_failed(root, key)
            sent += 1
            log("Fallida cargada: " + label)
        except MissingSageItems as exc:
            failed += 1
            log("Sigue sin item en Sage: " + label + " | " + ", ".join(exc.missing or []))
        except Exception as exc:
            failed += 1
            log("ERROR fallida " + label + ": " + str(exc))
    remaining = failed_count(root)
    log(
        "Fallidas: cargadas "
        + str(sent)
        + ", siguen "
        + str(remaining)
        + "."
    )
    return {"sent": sent, "failed": failed, "remaining": remaining}
