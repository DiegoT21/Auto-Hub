"""Invoca el writer Sage SDK (empresa de PRUEBA) desde Auto-Hub."""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

TEST_COMPANY = "LYL CONST CIA de PRUEBA"
TEST_CUSTOMER_ID = "C SUAREZ TORRE 1"
SAMPLE_NAME = "sample_invoice.json"


def sdk_script_dir(root: Path) -> Path:
    bundled = root / "scripts" / "sage_sdk"
    temp = Path(r"C:\Temp\sage_sdk")
    if (temp / "WriteTestInvoice.cs").exists() and (temp / "app_id.txt").exists():
        return temp
    return bundled


def load_sika_test_rows(root: Path) -> list[dict[str, Any]]:
    path = root / "scripts" / "sage_sdk" / SAMPLE_NAME
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    rows: list[dict[str, Any]] = []
    for item in payload:
        rec = item.get("record") or item
        rows.append(_coerce_row(rec))
    if not rows:
        raise ValueError("sample_invoice.json no tiene lineas.")
    return rows


def _coerce_row(rec: dict[str, Any]) -> dict[str, Any]:
    return {
        "factura_id": str(rec.get("factura_id") or ""),
        "numero_factura": str(rec.get("numero_factura") or ""),
        "fecha_emision": str(rec.get("fecha_emision") or "")[:10],
        "subtotal": float(rec.get("subtotal") or 0),
        "itbms_factura": float(rec.get("itbms_factura") or 0),
        "total_factura": float(rec.get("total_factura") or 0),
        "cliente_codigo": str(rec.get("cliente_codigo") or ""),
        "cliente_nombre": str(rec.get("cliente_nombre") or ""),
        "ruc": str(rec.get("ruc") or "CF"),
        "linea": rec.get("linea") or 1,
        "descripcion": str(rec.get("descripcion") or ""),
        "cantidad": float(rec.get("cantidad") or 0),
        "precio_unitario": float(rec.get("precio_unitario") or 0),
        "tasa_itbms": float(rec.get("tasa_itbms") or 0.07),
        "total_linea": float(rec.get("total_linea") or 0),
    }


def rows_to_outbox(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = []
    for row in rows:
        rec = dict(row)
        rec["ruc"] = rec.get("ruc") or "CF"
        out.append({"sentAt": now, "record": rec})
    return out


def write_outbox_json(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows_to_outbox(rows), indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _find_api_dir() -> Path | None:
    candidates = [
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Sage" / "Peachtree" / "API",
        Path(r"C:\Program Files (x86)\Sage\Peachtree\API"),
        Path(r"C:\Archivos de programa (x86)\Sage\Peachtree\API"),
    ]
    for folder in candidates:
        if (folder / "Sage.Peachtree.API.dll").exists():
            return folder
    return None


def _read_app_id(sdk_dir: Path) -> str:
    path = sdk_dir / "app_id.txt"
    if not path.exists():
        raise FileNotFoundError(
            "Falta app_id.txt en "
            + str(sdk_dir)
            + ". Copia el Application ID (misma carpeta que en C:\\Temp\\sage_sdk)."
        )
    app_id = path.read_text(encoding="utf-8").strip().splitlines()[0].strip()
    if not app_id:
        raise ValueError("app_id.txt esta vacio.")
    return app_id


def compile_writer(sdk_dir: Path, api_dir: Path) -> Path:
    csc = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework" / "v4.0.30319" / "csc.exe"
    webext = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework" / "v4.0.30319" / "System.Web.Extensions.dll"
    cs = sdk_dir / "WriteTestInvoice.cs"
    exe = sdk_dir / "WriteTestInvoice.exe"
    if not csc.exists():
        raise FileNotFoundError("No se encontro csc.exe de .NET 4.x")
    if not cs.exists():
        raise FileNotFoundError("Falta WriteTestInvoice.cs en " + str(sdk_dir))
    if exe.exists():
        try:
            exe.unlink()
        except OSError:
            pass
    cmd = [
        str(csc),
        "/nologo",
        "/platform:x86",
        "/t:exe",
        "/out:" + str(exe),
        "/r:" + str(api_dir / "Sage.Peachtree.API.dll"),
        "/r:" + str(api_dir / "Sage.Peachtree.API.Resolver.dll"),
        "/r:" + str(webext),
        str(cs),
    ]
    proc = subprocess.run(cmd, cwd=str(sdk_dir), capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError((proc.stdout or "") + "\n" + (proc.stderr or ""))
    return exe


def run_test_company_write(
    root: Path,
    rows: list[dict[str, Any]],
    on_log: Callable[[str], None] | None = None,
) -> int:
    def log(msg: str) -> None:
        if on_log:
            on_log(msg)

    sdk_dir = sdk_script_dir(root)
    log("Carpeta SDK: " + str(sdk_dir))
    json_path = write_outbox_json(sdk_dir / SAMPLE_NAME, rows)
    log("JSON escrito: " + json_path.name + " (" + str(len(rows)) + " lineas)")

    api_dir = _find_api_dir()
    if api_dir is None:
        raise FileNotFoundError(
            "No esta el Sage 50 SDK en esta PC.\n"
            "Auto-Hub tiene que correr en la maquina de Sage (AnyDesk),\n"
            "o copia sample_invoice.json a C:\\Temp\\sage_sdk y usa ABRIR_WRITE_INVOICE.bat"
        )

    app_id = _read_app_id(sdk_dir)
    log("Compilando WriteTestInvoice.cs ...")
    exe = compile_writer(sdk_dir, api_dir)
    log("Empresa: " + TEST_COMPANY)
    log("Cliente Sage (prueba): " + TEST_CUSTOMER_ID)
    log("Si Sage pide Always Allow -> aceptar")

    env = os.environ.copy()
    env["SAGE_SDK_NOPAUSE"] = "1"
    proc = subprocess.run(
        [str(exe), TEST_COMPANY, app_id, SAMPLE_NAME],
        cwd=str(sdk_dir),
        capture_output=True,
        text=True,
        env=env,
        timeout=240,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    for line in out.splitlines():
        log(line)
    if proc.returncode != 0:
        raise RuntimeError("WriteTestInvoice salio con codigo " + str(proc.returncode))
    return proc.returncode
