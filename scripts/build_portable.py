"""Arma AutoHub.exe + ZIP para pasar por AnyDesk (sin GitHub en la PC de Sage)."""
from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist" / "AutoHub"
BUNDLE = ROOT / "build" / "portable_data"
ZIP_NAME = "AutoHub-AnyDesk.zip"
README_NAME = "LEEME-SAGE-PC.txt"

README = """Auto-Hub en la PC de Sage
==========================

NO hace falta iniciar sesion en GitHub.

Instalar (una vez)
------------------
1. Pasa esta carpeta por AnyDesk (o el ZIP AutoHub-AnyDesk.zip).
2. Dejala en C:\\AutoHub
3. Doble clic en AutoHub.exe

El Application ID de Sage ya debe estar en:
  C:\\Temp\\sage_sdk\\app_id.txt
(el que usamos en las pruebas).

Actualizar despues
------------------
1. Te paso un AutoHub-update.zip nuevo por AnyDesk.
2. Ponlo en el Escritorio o junto a AutoHub.exe.
3. Abre Auto-Hub y pulsa "Actualizar app".

No pisa contraseñas, app_id.txt ni ledger_bridge.jwt.

Ledger Bridge (obligatorio en esta version)
------------------------------------------
Copia el JWT injector (cred ledge.txt) a:
  la carpeta config junto al AutoHub.exe
  (ejemplo: C:\\AutoHub\\config\\ledger_bridge.jwt)
Una sola linea, sin comillas.

Sage abierto en LYL + Conectar Sage (Always Allow una vez) + Automatico ON.
La pantalla muestra tres recuadros: lo que esta haciendo ahora, las que cargo en Sage y los fallos.
Las facturas viejas no llenan la lista: solo suman en Omitidas.
El detalle del dia (y el dump de Sage si una factura fallo) esta en la carpeta logs junto al exe. Boton Ver logs.
Solo facturas desde el 3 sep 2026 entran a Sage (mismo piso que el Extractor).
"""

CONFIG_IGNORE = {
    "connections.json",
    "config.json",
    "app_id.txt",
    "ledger_bridge.jwt",
}
CONFIG_IGNORE_SUFFIXES = (".local.json",)


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=str(ROOT))
    if proc.returncode != 0:
        raise SystemExit(proc.returncode)


def _should_skip_config(path: Path) -> bool:
    if path.name in CONFIG_IGNORE:
        return True
    return path.name.endswith(CONFIG_IGNORE_SUFFIXES)


def prepare_bundle() -> None:
    if BUNDLE.exists():
        shutil.rmtree(BUNDLE)
    for rel in ("assets", "scripts/sage_sdk"):
        src = ROOT / rel
        dest = BUNDLE / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(
            src,
            dest,
            ignore=shutil.ignore_patterns(
                "app_id.txt",
                "dump",
                "*.exe",
                "__pycache__",
                "Lanzador*",
            ),
        )
    dest_cfg = BUNDLE / "config"
    dest_cfg.mkdir(parents=True, exist_ok=True)
    for item in (ROOT / "config").iterdir():
        if item.is_file() and not _should_skip_config(item):
            shutil.copy2(item, dest_cfg / item.name)


def main() -> None:
    py = ROOT / ".venv" / "Scripts" / "python.exe"
    if not py.exists():
        py = Path(sys.executable)
    run([str(py), "-m", "pip", "install", "-q", "pyinstaller"])
    prepare_bundle()
    cmd = [
        str(py),
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--name",
        "AutoHub",
        "--onedir",
        "--paths",
        str(ROOT),
        "--add-data",
        str(BUNDLE / "assets") + ";assets",
        "--add-data",
        str(BUNDLE / "config") + ";config",
        "--add-data",
        str(BUNDLE / "scripts" / "sage_sdk") + ";scripts/sage_sdk",
        "--collect-all",
        "customtkinter",
        "--hidden-import",
        "src.paths",
        "--hidden-import",
        "src.app_update",
        "--hidden-import",
        "src.sage_sdk_write",
        "--hidden-import",
        "src.extractor_inbox",
        "--hidden-import",
        "src.ledger_bridge",
        "--hidden-import",
        "src.session_log",
        "--hidden-import",
        "app.ops_app",
        "--hidden-import",
        "app.theme",
        "--hidden-import",
        "app.components",
        "--hidden-import",
        "app.dialogs",
        "--hidden-import",
        "app.user_log",
        "--exclude-module",
        "pandas",
        "--exclude-module",
        "numpy",
        "--exclude-module",
        "mysql",
        "--exclude-module",
        "mysql.connector",
        "--exclude-module",
        "openpyxl",
        "--exclude-module",
        "CTkTable",
        "--exclude-module",
        "pdfplumber",
        "--exclude-module",
        "pdfminer",
        "--exclude-module",
        "pypdfium2",
        "--exclude-module",
        "pypdfium2_raw",
        "--exclude-module",
        "fpdf2",
        "--exclude-module",
        "matplotlib",
        "--exclude-module",
        "scipy",
        "--exclude-module",
        "tzdata",
        "--exclude-module",
        "IPython",
        "--exclude-module",
        "pytest",
        "--hidden-import",
        "PIL._tkinter_finder",
        str(ROOT / "app" / "ops_app.py"),
    ]
    icon = ROOT / "assets" / "autohub.ico"
    if icon.exists():
        cmd.extend(["--icon", str(icon)])
    run(cmd)

    DIST.mkdir(parents=True, exist_ok=True)
    (DIST / README_NAME).write_text(README, encoding="utf-8")
    for rel in ("scripts/sage_sdk", "config", "assets"):
        src = BUNDLE / rel
        dest = DIST / rel
        if not src.exists():
            continue
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)

    zip_path = ROOT / "dist" / ZIP_NAME
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in DIST.rglob("*"):
            if item.is_file():
                zf.write(item, Path("AutoHub") / item.relative_to(DIST))

    update_zip = ROOT / "dist" / "AutoHub-update.zip"
    shutil.copy2(zip_path, update_zip)

    hub_extrac = ROOT.parent
    if hub_extrac.is_dir():
        shutil.copy2(zip_path, hub_extrac / ZIP_NAME)
        shutil.copy2(update_zip, hub_extrac / "AutoHub-update.zip")
        print("ZIP en Hub + Extrac:", hub_extrac / ZIP_NAME)
        print("Update ZIP:", hub_extrac / "AutoHub-update.zip")

    desktop = Path.home() / "Desktop"
    if not desktop.is_dir():
        desktop = Path.home() / "OneDrive" / "Desktop"
    if desktop.is_dir():
        shutil.copy2(zip_path, desktop / ZIP_NAME)
        shutil.copy2(update_zip, desktop / "AutoHub-update.zip")
        print("ZIP en Escritorio:", desktop / ZIP_NAME)
    print("ZIP dist:", zip_path)
    print("Carpeta:", DIST)
    print("Pasa AutoHub-update.zip por AnyDesk a la PC de Sage")


if __name__ == "__main__":
    main()
