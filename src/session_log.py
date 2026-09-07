"""Logs de sesion en disco: detalle sin pintar la UI."""
from __future__ import annotations

import os
import re
import threading
from datetime import datetime
from pathlib import Path

_LOCK = threading.Lock()


def log_dir(root: Path) -> Path:
    path = root / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def day_log_path(root: Path) -> Path:
    name = "autohub-" + datetime.now().strftime("%Y-%m-%d") + ".txt"
    return log_dir(root) / name


def append(root: Path, kind: str, text: str) -> None:
    line = datetime.now().strftime("%H:%M:%S") + "  [" + kind + "]  " + (text or "").replace("\n", " ").strip() + "\n"
    path = day_log_path(root)
    with _LOCK:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)


def write_sage_fail(root: Path, label: str, text: str) -> Path:
    safe = re.sub(r"[^\w.*-]+", "_", label or "factura")[:40] or "factura"
    name = "sage-fail-" + safe + "-" + datetime.now().strftime("%H%M%S") + ".txt"
    path = log_dir(root) / name
    with _LOCK:
        path.write_text(text or "", encoding="utf-8", errors="replace")
    return path


def open_folder(root: Path) -> None:
    os.startfile(str(log_dir(root)))
