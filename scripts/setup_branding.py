"""Genera autohub.ico y actualiza el acceso directo de Auto-Hub en el escritorio."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LOGO_PNG = ROOT / "assets" / "autohub_logo.png"
LOGO_ICO = ROOT / "assets" / "autohub.ico"
LAUNCHER = ROOT / "launch_autohub.vbs"
SHORTCUT_NAME = "Auto-Hub.lnk"


def ensure_ico() -> Path:
    if not LOGO_PNG.exists():
        raise FileNotFoundError(f"No se encontro el logo: {LOGO_PNG}")

    try:
        from PIL import Image
    except ImportError:
        raise RuntimeError("Falta Pillow. Ejecuta: pip install pillow")

    img = Image.open(LOGO_PNG).convert("RGBA")
    sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    img.save(LOGO_ICO, format="ICO", sizes=sizes)
    return LOGO_ICO


def desktop_path() -> Path:
    import win32com.client

    shell = win32com.client.Dispatch("WScript.Shell")
    return Path(shell.SpecialFolders("Desktop"))


def update_desktop_shortcut() -> Path:
    import win32com.client

    if not LAUNCHER.exists():
        raise FileNotFoundError(f"No se encontro el launcher: {LAUNCHER}")

    ico = ensure_ico()
    shortcut_path = desktop_path() / SHORTCUT_NAME
    shell = win32com.client.Dispatch("WScript.Shell")
    link = shell.CreateShortCut(str(shortcut_path))
    link.Targetpath = str(LAUNCHER.resolve())
    link.WorkingDirectory = str(ROOT.resolve())
    link.IconLocation = f"{ico.resolve()},0"
    link.Description = "Auto-Hub - Automation Engine for Sage"
    link.save()
    return shortcut_path


def main() -> None:
    try:
        shortcut = update_desktop_shortcut()
        print(f"Icono: {LOGO_ICO}")
        print(f"Acceso directo actualizado: {shortcut}")
    except Exception as exc:
        print(f"setup_branding: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
