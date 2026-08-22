"""Invoca el writer Sage SDK (empresa de PRUEBA) desde Auto-Hub."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

TEST_COMPANY = "LYL CONSTRUCTIONS SUPPLY INC 2025-2026"
TEST_CUSTOMER_ID = "C SUAREZ TORRE 1"
SAMPLE_NAME = "sample_invoice.json"

FALLBACK_SIKA_RECORDS = [
    {
        "factura_id": "*0000001",
        "numero_factura": "*0000001",
        "fecha_emision": "2024-01-26",
        "subtotal": 33.84,
        "itbms_factura": 2.37,
        "total_factura": 36.21,
        "cliente_codigo": "8-770-1583",
        "cliente_nombre": "MIGUEL DEL RIO",
        "ruc": "CF",
        "linea": 1,
        "descripcion": "SIKAFLEX 221 BLANCO (300ML)",
        "cantidad": 3,
        "precio_unitario": 7.70,
        "tasa_itbms": 0.07,
        "total_linea": 21.945,
    },
    {
        "factura_id": "*0000001",
        "numero_factura": "*0000001",
        "fecha_emision": "2024-01-26",
        "subtotal": 33.84,
        "itbms_factura": 2.37,
        "total_factura": 36.21,
        "cliente_codigo": "8-770-1583",
        "cliente_nombre": "MIGUEL DEL RIO",
        "ruc": "CF",
        "linea": 2,
        "descripcion": "SIKACRYL150 BLANCO (300ML)",
        "cantidad": 2,
        "precio_unitario": 4.10,
        "tasa_itbms": 0.07,
        "total_linea": 7.79,
    },
    {
        "factura_id": "*0000001",
        "numero_factura": "*0000001",
        "fecha_emision": "2024-01-26",
        "subtotal": 33.84,
        "itbms_factura": 2.37,
        "total_factura": 36.21,
        "cliente_codigo": "8-770-1583",
        "cliente_nombre": "MIGUEL DEL RIO",
        "ruc": "CF",
        "linea": 3,
        "descripcion": "SIKACRYL150 BLANCO (300ML)",
        "cantidad": 1,
        "precio_unitario": 4.10,
        "tasa_itbms": 0.07,
        "total_linea": 4.10,
    },
]


def sdk_script_dir(root: Path) -> Path:
    """Usa el WriteTestInvoice.cs de esta version de Auto-Hub, no el de C:\\Temp."""
    from src.paths import app_root, resource_root

    dest = app_root() / "scripts" / "sage_sdk"
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("WriteTestInvoice.cs", "RunSageHost.ps1"):
        candidates = [
            resource_root() / "scripts" / "sage_sdk" / name,
            root / "scripts" / "sage_sdk" / name,
            dest / name,
        ]
        src = next((path for path in candidates if path.exists()), None)
        if src is None:
            continue
        target = dest / name
        if src.resolve() != target.resolve():
            shutil.copy2(src, target)
        temp_copy = Path(r"C:\Temp\sage_sdk") / name
        if temp_copy.parent.exists():
            try:
                shutil.copy2(src, temp_copy)
            except OSError:
                pass
    return dest


def _app_id_path(sdk_dir: Path) -> Path:
    for path in (
        Path(r"C:\Temp\sage_sdk") / "app_id.txt",
        sdk_dir / "app_id.txt",
    ):
        if not path.exists():
            continue
        app_id = path.read_text(encoding="utf-8").strip().splitlines()[0].strip()
        if app_id:
            return path
    raise FileNotFoundError(
        "Falta app_id.txt (C:\\Temp\\sage_sdk o scripts\\sage_sdk). "
        "Copia el Application ID que usamos en las pruebas."
    )


def _read_app_id(sdk_dir: Path) -> str:
    path = _app_id_path(sdk_dir)
    return path.read_text(encoding="utf-8").strip().splitlines()[0].strip()


def _hidden_kw() -> dict[str, Any]:
    """Evita que tasklist/PowerShell abran una ventana CMD."""
    if os.name != "nt":
        return {}
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = 0
    return {"creationflags": flags, "startupinfo": info}


def _powershell32() -> Path:
    path = Path(os.environ.get("WINDIR", r"C:\Windows")) / "SysWOW64" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    if not path.exists():
        raise FileNotFoundError("No se encontro PowerShell 32-bit (SysWOW64).")
    return path


def _process_running(image_name: str) -> bool:
    proc = subprocess.run(
        ["tasklist", "/FI", f"IMAGENAME eq {image_name}", "/NH"],
        capture_output=True,
        text=True,
        timeout=15,
        **_hidden_kw(),
    )
    out = (proc.stdout or "").lower()
    return image_name.lower() in out


def sage_ui_running() -> bool:
    return any(_process_running(name) for name in ("peachw.exe", "Peachtree.exe"))


def _kill_image(image_name: str) -> None:
    subprocess.run(
        ["taskkill", "/F", "/IM", image_name, "/T"],
        capture_output=True,
        text=True,
        timeout=20,
        **_hidden_kw(),
    )


def _ensure_writer_dead() -> None:
    _kill_image("WriteTestInvoice.exe")
    deadline = time.time() + 5
    while time.time() < deadline and _process_running("WriteTestInvoice.exe"):
        time.sleep(0.3)
        _kill_image("WriteTestInvoice.exe")


def _restart_actian(log: Callable[[str], None]) -> None:
    names = (
        "Actian Zen Workgroup Engine",
        "Actian PSQL Workgroup Engine",
        "Pervasive PSQL Workgroup Engine",
    )
    for name in names:
        subprocess.run(
            ["net", "stop", name],
            capture_output=True,
            text=True,
            timeout=40,
            **_hidden_kw(),
        )
        started = subprocess.run(
            ["net", "start", name],
            capture_output=True,
            text=True,
            timeout=40,
            **_hidden_kw(),
        )
        if started.returncode == 0:
            log("Actian reiniciado: " + name)
            return
    log("No se pudo reiniciar Actian solo. Si Sage no abre: services.msc → Actian → Reiniciar.")


def load_sika_test_rows(root: Path) -> list[dict[str, Any]]:
    from src.paths import resource_root

    candidates = [
        root / "scripts" / "sage_sdk" / SAMPLE_NAME,
        resource_root() / "scripts" / "sage_sdk" / SAMPLE_NAME,
        Path(r"C:\Temp\sage_sdk") / SAMPLE_NAME,
    ]
    for path in candidates:
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        rows: list[dict[str, Any]] = []
        for item in payload:
            rec = item.get("record") or item
            rows.append(_coerce_row(rec))
        if rows:
            return rows
    return [_coerce_row(rec) for rec in FALLBACK_SIKA_RECORDS]


SUCURSAL_LABELS = {
    "01": "ADI SUPPLY",
    "02": "CORONADO",
    "03": "RIO ABAJO",
}


def sucursal_label(rec: dict[str, Any]) -> str:
    explicit = str(rec.get("sucursal") or "").strip()
    if explicit:
        return explicit
    code = str(rec.get("sucursal_codigo") or rec.get("almacen") or "").strip()
    if code in SUCURSAL_LABELS:
        return SUCURSAL_LABELS[code]
    name = str(rec.get("sucursal_nombre") or "").strip()
    return name or "SIN SUCURSAL"


def _as_iso_date(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    return text[:10]


def _json_default(obj: Any) -> Any:
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if hasattr(obj, "item"):
        return obj.item()
    return str(obj)


def _coerce_row(rec: dict[str, Any]) -> dict[str, Any]:
    return {
        "factura_id": str(rec.get("factura_id") or ""),
        "numero_factura": str(rec.get("numero_factura") or ""),
        "fecha_emision": _as_iso_date(rec.get("fecha_emision")),
        "subtotal": float(rec.get("subtotal") or 0),
        "itbms_factura": float(rec.get("itbms_factura") or 0),
        "total_factura": float(rec.get("total_factura") or 0),
        "cliente_codigo": str(rec.get("cliente_codigo") or ""),
        "cliente_nombre": str(rec.get("cliente_nombre") or ""),
        "ruc": str(rec.get("ruc") or "CF"),
        "linea": int(rec.get("linea") or 1),
        "descripcion": str(rec.get("descripcion") or ""),
        "cantidad": float(rec.get("cantidad") or 0),
        "precio_unitario": float(rec.get("precio_unitario") or 0),
        "tasa_itbms": float(rec.get("tasa_itbms") or 0.07),
        "total_linea": float(rec.get("total_linea") or 0),
        "sucursal_codigo": str(rec.get("sucursal_codigo") or "").strip(),
        "sucursal": sucursal_label(rec),
    }


def rows_to_outbox(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = []
    for row in rows:
        rec = _coerce_row(row)
        rec["ruc"] = rec.get("ruc") or "CF"
        out.append({"sentAt": now, "record": rec})
    return out


def write_outbox_json(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(rows_to_outbox(rows), indent=2, ensure_ascii=False, default=_json_default),
        encoding="utf-8",
    )
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
        _kill_image("WriteTestInvoice.exe")
        time.sleep(0.3)
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
    proc = subprocess.run(cmd, cwd=str(sdk_dir), capture_output=True, text=True, **_hidden_kw())
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

    if sage_ui_running():
        log("Sage esta abierto: bien para Always Allow. Deja abierta LYL CONSTRUCTIONS SUPPLY INC 2025-2026.")
    else:
        log(
            "Sage cerrado. Si pide permiso: abre Sage en LYL CONSTRUCTIONS SUPPLY INC 2025-2026 "
            "y elige Always Allow (una vez)."
        )

    return _run_writer(root, rows, on_log=log, auth_only=False)


def authorize_sage_access(
    root: Path,
    on_log: Callable[[str], None] | None = None,
) -> int:
    """Solo RequestAccess / Always Allow. No escribe facturas."""

    def log(msg: str) -> None:
        if on_log:
            on_log(msg)

    if not sage_ui_running():
        log(
            "Abre Sage 50 en 'LYL CONSTRUCTIONS SUPPLY INC 2025-2026' ahora. "
            "El dialogo Always Allow solo aparece con la empresa abierta."
        )
    return _run_writer(root, [], on_log=log, auth_only=True)


def _customer_from_rows(rows: list[dict[str, Any]]) -> tuple[str, str]:
    rec = rows[0] if rows else {}
    return (
        str(rec.get("cliente_codigo") or "").strip(),
        str(rec.get("cliente_nombre") or "").strip(),
    )


SENT_LOG_NAME = "sage_sent.json"


class DuplicateSageInvoice(RuntimeError):
    """La factura de PsKloud ya se envio a Sage desde Auto-Hub."""


def _sent_log_path(root: Path) -> Path:
    path = root / "state" / SENT_LOG_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load_sent_log(root: Path) -> dict[str, Any]:
    path = _sent_log_path(root)
    if not path.exists():
        return {"by_factura_id": {}, "by_numero": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"by_factura_id": {}, "by_numero": {}}
    if not isinstance(data, dict):
        return {"by_factura_id": {}, "by_numero": {}}
    data.setdefault("by_factura_id", {})
    data.setdefault("by_numero", {})
    return data


def _save_sent_log(root: Path, data: dict[str, Any]) -> None:
    _sent_log_path(root).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _invoice_keys(rows: list[dict[str, Any]]) -> tuple[str, str]:
    rec = rows[0] if rows else {}
    return (
        str(rec.get("factura_id") or "").strip(),
        str(rec.get("numero_factura") or "").strip(),
    )


def find_sent_invoice(root: Path, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    factura_id, numero = _invoice_keys(rows)
    data = _load_sent_log(root)
    if factura_id and factura_id in data["by_factura_id"]:
        return data["by_factura_id"][factura_id]
    if numero and numero in data["by_numero"]:
        return data["by_numero"][numero]
    return None


def record_sent_invoice(
    root: Path,
    rows: list[dict[str, Any]],
    *,
    sage_ref: str,
    sucursal: str = "",
) -> None:
    factura_id, numero = _invoice_keys(rows)
    if not factura_id and not numero:
        return
    data = _load_sent_log(root)
    entry = {
        "factura_id": factura_id,
        "numero_factura": numero,
        "sage_ref": sage_ref,
        "sucursal": sucursal,
        "cliente": str((rows[0] or {}).get("cliente_nombre") or ""),
        "sent_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if factura_id:
        data["by_factura_id"][factura_id] = entry
    if numero:
        data["by_numero"][numero] = entry
    _save_sent_log(root, data)


def _parse_sage_ref(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("reference:"):
            return stripped.split(":", 1)[-1].strip()
        if "ReferenceNumber Sage:" in stripped:
            return stripped.split(":", 1)[-1].strip()
    return ""


def _run_writer(
    root: Path,
    rows: list[dict[str, Any]],
    *,
    on_log: Callable[[str], None],
    auth_only: bool,
) -> int:
    _ensure_writer_dead()
    sdk_dir = sdk_script_dir(root)
    on_log("Carpeta SDK: " + str(sdk_dir))

    json_path = None
    if not auth_only:
        already = find_sent_invoice(root, rows)
        if already:
            sage_ref = str(already.get("sage_ref") or "(sin referencia)")
            sent_at = str(already.get("sent_at") or "")
            on_log("Factura ya enviada a Sage: " + sage_ref)
            raise DuplicateSageInvoice(
                "Esta factura de PsKloud ya se envio a Sage.\n"
                "Invoice No. Sage: "
                + sage_ref
                + ("\nEnviada: " + sent_at if sent_at else "")
                + "\n\nNo se creo otra para no duplicar. Buscala en Sales Invoices."
            )
        json_path = write_outbox_json(sdk_dir / SAMPLE_NAME, rows)
        on_log("JSON escrito: " + json_path.name + " (" + str(len(rows)) + " lineas)")

    api_dir = _find_api_dir()
    if api_dir is None:
        raise FileNotFoundError(
            "No esta el Sage 50 SDK en esta PC.\n"
            "Auto-Hub tiene que correr en la maquina de Sage (AnyDesk),\n"
            "o copia sample_invoice.json a C:\\Temp\\sage_sdk y usa ABRIR_WRITE_INVOICE.bat"
        )

    _read_app_id(sdk_dir)
    host = sdk_dir / "RunSageHost.ps1"
    if not host.exists():
        raise FileNotFoundError("Falta RunSageHost.ps1 en " + str(sdk_dir))

    on_log("Conectando con Sage 50...")
    on_log("Empresa: " + TEST_COMPANY)
    cust_id, cust_name = _customer_from_rows(rows)
    if auth_only:
        on_log("Modo autorizar: espera Always Allow en Sage (hasta 3 min).")
    else:
        on_log("Cliente factura: " + (cust_id or "(sin codigo)") + " | " + (cust_name or "(sin nombre)"))

    cmd = [
        str(_powershell32()),
        "-NoProfile",
        "-WindowStyle",
        "Hidden",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(host),
        "-Company",
        TEST_COMPANY,
        "-AppIdFile",
        str(_app_id_path(sdk_dir)),
    ]
    if auth_only:
        cmd.append("-AuthOnly")
    else:
        cmd.extend(
            [
                "-SampleJson",
                str(json_path),
                "-CustomerId",
                cust_id,
                "-CustomerName",
                cust_name,
            ]
        )

    proc = subprocess.Popen(
        cmd,
        cwd=str(sdk_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        **_hidden_kw(),
    )
    # Pending puede tardar hasta ~3 min mientras el usuario da Always Allow.
    timeout_sec = 200
    try:
        out, err = proc.communicate(timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            out, err = proc.communicate(timeout=10)
        except Exception:
            out, err = "", ""
        _ensure_writer_dead()
        text = (out or "") + (err or "")
        for line in text.splitlines():
            on_log(line)
        raise RuntimeError(
            "Se agoto el tiempo esperando Always Allow.\n"
            "1) Abre Sage en LYL CONSTRUCTIONS SUPPLY INC 2025-2026\n"
            "2) Pulsa 'Conectar Sage' otra vez\n"
            "3) En el dialogo elige ALWAYS ALLOW (no solo Allow)\n"
            "Despues de eso, Enviar a Sage ya no deberia pedir permiso."
        )
    finally:
        if proc.poll() is None:
            proc.kill()
            _ensure_writer_dead()

    text = (out or "") + (err or "")
    for line in text.splitlines():
        on_log(line)
    if proc.returncode != 0:
        raise RuntimeError(
            ("Conectar Sage" if auth_only else "Enviar a Sage")
            + " salio con codigo "
            + str(proc.returncode)
        )
    if not auth_only:
        sage_ref = _parse_sage_ref(text)
        sucursal = str((rows[0] or {}).get("sucursal") or "")
        record_sent_invoice(root, rows, sage_ref=sage_ref or "AH", sucursal=sucursal)
        if sage_ref:
            on_log("Registrada para no duplicar: " + sage_ref)
    return proc.returncode
