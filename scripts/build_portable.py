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

No pisa contraseñas ni app_id.txt.
"""

CONFIG_IGNORE = {
    "connections.json",
    "config.json",
    "app_id.txt",
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
        "--collect-submodules",
        "app",
        "--hidden-import",
        "src.paths",
        "--hidden-import",
        "src.connections",
        "--hidden-import",
        "src.db",
        "--hidden-import",
        "src.extract",
        "--hidden-import",
        "src.transform",
        "--hidden-import",
        "src.validate",
        "--hidden-import",
        "src.app_update",
        "--hidden-import",
        "src.sage_sdk_write",
        "--hidden-import",
        "src.export_csv",
        "--hidden-import",
        "src.csv_import",
        "--hidden-import",
        "src.excel_automation",
        "--hidden-import",
        "src.sage_excel",
        "--hidden-import",
        "src.preview_utils",
        "--hidden-import",
        "mysql.connector.locales.eng.client_error",
        "--hidden-import",
        "mysql.connector.plugins.mysql_native_password",
        "--collect-submodules",
        "mysql.connector.locales",
        "--collect-submodules",
        "mysql.connector.plugins",
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
        "pandas.plotting",
        "--hidden-import",
        "PIL._tkinter_finder",
        str(ROOT / "app" / "main.py"),
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

    desktop = Path.home() / "Desktop"
    if not desktop.is_dir():
        desktop = Path.home() / "OneDrive" / "Desktop"
    if desktop.is_dir():
        shutil.copy2(zip_path, desktop / ZIP_NAME)
        shutil.copy2(update_zip, desktop / "AutoHub-update.zip")
        print("ZIP en Escritorio:", desktop / ZIP_NAME)
        print("Update ZIP:", desktop / "AutoHub-update.zip")
    print("ZIP:", zip_path)
    print("Carpeta:", DIST)
    print("Pasa AutoHub-AnyDesk.zip por AnyDesk y extrae a C:\\AutoHub")


if __name__ == "__main__":
    main()
