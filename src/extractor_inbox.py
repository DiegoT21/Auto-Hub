"""Lee lotes del Extractor (outbox JSONL) y los manda a Sage."""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Callable

from src.sage_sdk_write import (
    DuplicateSageInvoice,
    _coerce_row,
    find_sent_invoice,
    run_test_company_write,
    sage_ui_running,
)


def default_outbox_dir() -> Path:
    programdata = os.environ.get("ProgramData") or r"C:\ProgramData"
    return Path(programdata) / "PsKloudExtractor" / "outbox"


def outbox_dir(config: dict[str, Any], root: Path) -> Path:
    custom = str((config.get("extraction") or {}).get("extractor_outbox") or "").strip()
    if custom:
        path = Path(custom)
        return path if path.is_absolute() else (root / path)
    return default_outbox_dir()


def list_batch_files(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    return sorted(
        path
        for path in folder.glob("batch-*.jsonl")
        if path.is_file() and path.parent == folder
    )


def parse_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        item = json.loads(line)
        rec = item.get("record") if isinstance(item, dict) else item
        if not isinstance(rec, dict):
            continue
        rows.append(_coerce_row(rec))
    return rows


def group_invoices(rows: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    order: list[str] = []
    buckets: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        key = str(row.get("factura_id") or row.get("numero_factura") or "").strip()
        if not key:
            key = "_sin_id_"
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(row)
    return [buckets[key] for key in order]


def _archive(path: Path, dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / path.name
    if target.exists():
        target = dest_dir / f"{path.stem}-{int(time.time())}{path.suffix}"
    shutil.move(str(path), str(target))


def process_extractor_outbox(
    root: Path,
    config: dict[str, Any],
    on_log: Callable[[str], None],
) -> dict[str, int]:
    stats = {"sent": 0, "skipped": 0, "failed": 0, "files": 0}
    folder = outbox_dir(config, root)
    if not sage_ui_running():
        on_log("Automatico: Sage no esta abierto. Deja LYL 2025-2026 abierta.")
        return stats

    from src.ledger_bridge import is_configured, process_ledger_pending

    if is_configured(root, config):
        cloud = process_ledger_pending(root, config, on_log)
        for key in stats:
            stats[key] += int(cloud.get(key) or 0)

    pending = list_batch_files(folder)
    if not pending:
        return stats

    now = time.time()
    for path in pending:
        try:
            if now - path.stat().st_mtime < 2:
                continue
        except OSError:
            continue
        on_log("Extractor lote: " + path.name)
        try:
            rows = parse_jsonl(path)
        except Exception as exc:
            on_log("JSONL invalido " + path.name + ": " + str(exc))
            _archive(path, folder / "error")
            stats["failed"] += 1
            stats["files"] += 1
            continue
        if not rows:
            _archive(path, folder / "done")
            stats["files"] += 1
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
        _archive(path, folder / ("done" if file_ok else "error"))
        stats["files"] += 1
    return stats
