"""Actualizar Auto-Hub en la PC de Sage con un clic (git pull o ZIP de GitHub)."""
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
from urllib.request import urlopen, Request

KEEP_RELATIVE = {
    ".venv",
    "data",
    "output",
    "state",
    "config/connections.json",
    "scripts/sage_sdk/app_id.txt",
}

SKIP_NAMES = {".venv", "__pycache__", ".git", "data", "output", "state"}


def load_update_config(root: Path) -> dict[str, Any]:
    path = root / "config" / "update.json"
    if not path.exists():
        return {"github_repo": "gspspdev/desktop-sage-ps", "branch": "develop", "source_subdir": ""}
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
        if on_log and rel.suffix in {".py", ".json", ".cs", ".bat", ".vbs", ".txt"}:
            on_log("  " + rel.as_posix())


def update_via_git(root: Path, cfg: dict[str, Any], on_log: Callable[[str], None]) -> str:
    git = _git_exe()
    if git is None:
        raise FileNotFoundError("Git no esta instalado en esta PC.")
    if not (root / ".git").exists():
        raise FileNotFoundError("Esta carpeta no es un clone de git.")
    branch = str(cfg.get("branch") or "develop")
    on_log("git fetch ...")
    _run([git, "fetch", "origin"], root)
    on_log("git pull origin " + branch)
    out = _run([git, "pull", "origin", branch], root)
    on_log(out or "git pull OK")
    return "git"


def update_via_zip(root: Path, cfg: dict[str, Any], on_log: Callable[[str], None]) -> str:
    repo = str(cfg.get("github_repo") or "").strip()
    branch = str(cfg.get("branch") or "develop").strip()
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


def run_update(root: Path, on_log: Callable[[str], None] | None = None) -> str:
    def log(msg: str) -> None:
        if on_log:
            on_log(msg)

    cfg = load_update_config(root)
    method = "zip"
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
