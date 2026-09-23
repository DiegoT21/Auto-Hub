"""Logs de sesion en disco: detalle sin pintar la UI."""
from __future__ import annotations

import os
import re
import threading
from datetime import datetime
from pathlib import Path

_LOCK = threading.Lock()
_last_kind = ""
_last_text = ""


def log_dir(root: Path) -> Path:
    path = root / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def day_log_path(root: Path) -> Path:
    name = "autohub-" + datetime.now().strftime("%Y-%m-%d") + ".txt"
    return log_dir(root) / name


def append(root: Path, kind: str, text: str) -> None:
    global _last_kind, _last_text
    shown = (text or "").replace("\n", " ").strip()
    path = day_log_path(root)
    with _LOCK:
        if kind in ("err", "status") and _last_kind == kind and _last_text == shown:
            return
        if kind in ("err", "status"):
            _last_kind = kind
            _last_text = shown
        else:
            _last_kind = ""
            _last_text = ""
        line = datetime.now().strftime("%H:%M:%S") + "  [" + kind + "]  " + shown + "\n"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)


def write_sage_fail(root: Path, label: str, text: str) -> Path | None:
    """Un dump por factura. Si ya existe, no crea otro."""
    raw = (label or "factura").replace("*", "R").replace("?", "_")
    safe = re.sub(r"[^\w.-]+", "_", raw)[:40] or "factura"
    folder = log_dir(root)
    path = folder / ("sage-fail-" + safe + ".txt")
    with _LOCK:
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass
        path.write_text(text or "", encoding="utf-8", errors="replace")
    return path


def open_folder(root: Path) -> None:
    os.startfile(str(log_dir(root)))
