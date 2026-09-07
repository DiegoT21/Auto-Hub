"""Rutas de la app: codigo fuente vs ejecutable (PyInstaller)."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

NEVER_OVERWRITE = {
    "config/connections.json",
    "config/config.json",
    "config/ledger_bridge.jwt",
    "scripts/sage_sdk/app_id.txt",
}
ALWAYS_REFRESH_SUFFIXES = {".cs", ".bat", ".sql", ".ps1"}


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_root() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_root() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    if is_frozen() and meipass:
        return Path(meipass)
    return Path(__file__).resolve().parent.parent


def seed_runtime_files() -> None:
    """Copia config/scripts/assets junto al .exe la primera vez."""
    if not is_frozen():
        return
    src_root = resource_root()
    dest_root = app_root()
    (dest_root / "data").mkdir(parents=True, exist_ok=True)
    (dest_root / "state").mkdir(parents=True, exist_ok=True)
    (dest_root / "output").mkdir(parents=True, exist_ok=True)
    (dest_root / "logs").mkdir(parents=True, exist_ok=True)
    for rel in ("scripts/sage_sdk", "config", "assets"):
        src = src_root / rel
        if not src.exists() or not src.is_dir():
            continue
        for item in src.rglob("*"):
            if item.is_dir():
                continue
            rel_item = (Path(rel) / item.relative_to(src)).as_posix()
            if rel_item in NEVER_OVERWRITE:
                continue
            target = dest_root / rel_item
            if target.exists() and item.suffix.lower() not in ALWAYS_REFRESH_SUFFIXES:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
    config_dir = dest_root / "config"
    for name in ("config.json", "connections.json"):
        dest = config_dir / name
        example = config_dir / (name.replace(".json", ".example.json"))
        if not dest.exists() and example.exists():
            shutil.copy2(example, dest)
