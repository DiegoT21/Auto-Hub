"""Actualizar Auto-Hub: ZIP local por AnyDesk, o git/GitHub si hay sesion."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request, urlopen

from src.paths import is_frozen

KEEP_RELATIVE = {
    ".venv",
    "data",
    "output",
    "state",
    "config/connections.json",
    "scripts/sage_sdk/app_id.txt",
}

SKIP_NAMES = {
    ".venv",
    "__pycache__",
    ".git",
    "data",
    "output",
    "state",
    "_update_staging",
}

UPDATE_ZIP_NAMES = (
    "AutoHub-update.zip",
    "AutoHub.zip",
    "AutoHub-AnyDesk.zip",
    "autohub-update.zip",
)

APPLY_BAT = "_aplicar_update.bat"
STAGING_DIR = "_update_staging"

LOCAL_ZIP_HELP = (
    "No hace falta iniciar sesion en GitHub en esta PC.\n\n"
    "Pasa por AnyDesk el archivo AutoHub-update.zip al Escritorio "
    "o a la misma carpeta de AutoHub.exe, y vuelve a pulsar Actualizar."
)


def load_update_config(root: Path) -> dict[str, Any]:
    path = root / "config" / "update.json"
    if not path.exists():
        return {"github_repo": "DiegoT21/Auto-Hub", "branch": "main", "source_subdir": ""}
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _git_exe() -> str | None:
    found = shutil.which("git")
    if found:
        return found
    for candidate in (
        Path(r"C:\Program Files\Git\bin\git.exe"),
        Path(r"C:\Program Files (x86)\Git\bin\git.exe"),
    ):
        if candidate.exists():
            return str(candidate)
    return None


def _run(cmd: list[str], cwd: Path, timeout: int = 120) -> str:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    out = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    if proc.returncode != 0:
        raise RuntimeError(out or ("comando fallo: " + " ".join(cmd)))
    return out


def _should_keep(rel: Path) -> bool:
    posix = rel.as_posix()
    if posix in KEEP_RELATIVE:
        return True
    parts = rel.parts
    if parts and parts[0] in SKIP_NAMES:
        return True
    return False


def _copy_tree(src: Path, dest: Path, on_log: Callable[[str], None] | None) -> None:
    for item in src.rglob("*"):
        rel = item.relative_to(src)
        if _should_keep(rel):
            continue
        if any(p in SKIP_NAMES or p == "__pycache__" for p in rel.parts):
            continue
        target = dest / rel
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)
        if on_log and rel.suffix in {".py", ".json", ".cs", ".bat", ".vbs", ".txt", ".exe"}:
            on_log("  " + rel.as_posix())


def find_local_update_zip(root: Path) -> Path | None:
    folders = [
        root,
        Path.home() / "Desktop",
        Path.home() / "Escritorio",
        Path.home() / "OneDrive" / "Desktop",
        Path.home() / "Downloads",
        Path.home() / "Descargas",
    ]
    found: list[Path] = []
    for folder in folders:
        if not folder.is_dir():
            continue
        for name in UPDATE_ZIP_NAMES:
            candidate = folder / name
            if candidate.is_file():
                found.append(candidate)
    if not found:
        return None
    return max(found, key=lambda path: path.stat().st_mtime)


def _resolve_zip_source(extract_dir: Path) -> Path:
    tops = [p for p in extract_dir.iterdir() if p.is_dir()]
    files = [p for p in extract_dir.iterdir() if p.is_file()]
    source = tops[0] if len(tops) == 1 and not files else extract_dir
    if (source / "AutoHub.exe").exists():
        return source
    nested = source / "AutoHub"
    if (nested / "AutoHub.exe").exists():
        return nested
    return source


def _extract_update_source(zip_path: Path) -> tuple[Path, tempfile.TemporaryDirectory[str]]:
    tmp = tempfile.TemporaryDirectory()
    extract_dir = Path(tmp.name) / "extracted"
    extract_dir.mkdir()
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(extract_dir)
    return _resolve_zip_source(extract_dir), tmp


def update_via_local_zip(root: Path, zip_path: Path, on_log: Callable[[str], None]) -> str:
    on_log("Usando ZIP local: " + str(zip_path))
    source, tmp = _extract_update_source(zip_path)
    try:
        on_log("Copiando archivos (sin contraseñas ni datos locales)...")
        _copy_tree(source, root, on_log)
    finally:
        tmp.cleanup()
    return "zip-local"


def stage_frozen_update(root: Path, zip_path: Path, on_log: Callable[[str], None]) -> str:
    on_log("Usando ZIP local: " + str(zip_path))
    staging = root / STAGING_DIR
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    source, tmp = _extract_update_source(zip_path)
    try:
        on_log("Preparando archivos (se aplican al cerrar la app)...")
        _copy_tree(source, staging, on_log)
    finally:
        tmp.cleanup()
    exe = root / "AutoHub.exe"
    bat = root / APPLY_BAT
    bat.write_text(
        "\n".join(
            [
                "@echo off",
                "timeout /t 4 /nobreak >nul",
                f'robocopy "{staging}" "{root}" /E /NFL /NDL /NJH /NJS /nc /ns /np',
                f'rmdir /S /Q "{staging}"',
                f'del /Q "{zip_path}" 2>nul',
                f'start "" "{exe}"',
                'del "%~f0"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    on_log("Listo: al cerrar se copia el ZIP y se reabre AutoHub.exe")
    return "zip-local"


def update_via_git(root: Path, cfg: dict[str, Any], on_log: Callable[[str], None]) -> str:
    git = _git_exe()
    if git is None:
        raise FileNotFoundError("Git no esta instalado en esta PC.")
    if not (root / ".git").exists():
        raise FileNotFoundError("Esta carpeta no es un clone de git.")
    branch = str(cfg.get("branch") or "main")
    on_log("git fetch ...")
    _run([git, "fetch", "origin"], root)
    on_log("git pull origin " + branch)
    out = _run([git, "pull", "origin", branch], root)
    on_log(out or "git pull OK")
    return "git"


def update_via_zip(root: Path, cfg: dict[str, Any], on_log: Callable[[str], None]) -> str:
    repo = str(cfg.get("github_repo") or "").strip()
    branch = str(cfg.get("branch") or "main").strip()
    if not repo:
        raise ValueError("Falta github_repo en config/update.json")
    url = f"https://github.com/{repo}/archive/refs/heads/{branch}.zip"
    on_log("Descargando " + url)
    req = Request(url, headers={"User-Agent": "AutoHub-Updater"})
    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / "update.zip"
        with urlopen(req, timeout=60) as resp:
            zip_path.write_bytes(resp.read())
        extract_dir = Path(tmp) / "extracted"
        extract_dir.mkdir()
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract_dir)
        tops = [p for p in extract_dir.iterdir() if p.is_dir()]
        if not tops:
            raise RuntimeError("El ZIP de GitHub vino vacio.")
        source = tops[0]
        sub = str(cfg.get("source_subdir") or "").strip()
        if sub:
            source = source / sub
            if not source.is_dir():
                raise FileNotFoundError(
                    "En el repo no esta la carpeta '"
                    + sub
                    + "'. Auto-Hub todavia no esta publicado ahi."
                )
        on_log("Copiando archivos (sin .venv ni contraseñas)...")
        _copy_tree(source, root, on_log)
    return "zip"


def pip_sync(root: Path, on_log: Callable[[str], None]) -> None:
    py = root / ".venv" / "Scripts" / "python.exe"
    req = root / "requirements.txt"
    if not py.exists() or not req.exists():
        return
    on_log("pip install -r requirements.txt")
    out = _run([str(py), "-m", "pip", "install", "-r", str(req)], root, timeout=300)
    if on_log:
        tail = "\n".join(out.splitlines()[-8:])
        if tail:
            on_log(tail)


def _uses_exe(root: Path) -> bool:
    return is_frozen() or (root / "AutoHub.exe").exists()


def run_update(root: Path, on_log: Callable[[str], None] | None = None) -> str:
    def log(msg: str) -> None:
        if on_log:
            on_log(msg)

    local = find_local_update_zip(root)
    if local:
        if _uses_exe(root):
            method = stage_frozen_update(root, local, log)
        else:
            method = update_via_local_zip(root, local, log)
            pip_sync(root, log)
        log("Actualizacion lista (" + method + "). Auto-Hub se reiniciara.")
        return method

    if _uses_exe(root):
        raise RuntimeError(LOCAL_ZIP_HELP)

    cfg = load_update_config(root)
    if (root / ".git").exists() and _git_exe():
        try:
            method = update_via_git(root, cfg, log)
        except Exception as exc:
            log("git pull no pudo (" + str(exc) + "). Probando ZIP...")
            method = update_via_zip(root, cfg, log)
    else:
        method = update_via_zip(root, cfg, log)
    pip_sync(root, log)
    log("Actualizacion lista (" + method + "). Auto-Hub se reiniciara.")
    return method


def restart_autohub(root: Path) -> None:
    apply_bat = root / APPLY_BAT
    if apply_bat.exists():
        subprocess.Popen(
            ["cmd.exe", "/c", str(apply_bat)],
            cwd=str(root),
            close_fds=True,
        )
        return
    if is_frozen():
        subprocess.Popen([sys.executable], cwd=str(root), close_fds=True)
        return
    launcher = root / "launch_autohub.vbs"
    if launcher.exists():
        os.startfile(str(launcher))
        return
    py = root / ".venv" / "Scripts" / "pythonw.exe"
    if not py.exists():
        py = Path(sys.executable)
    subprocess.Popen(
        [str(py), str(root / "app" / "main.py")],
        cwd=str(root),
        close_fds=True,
    )
