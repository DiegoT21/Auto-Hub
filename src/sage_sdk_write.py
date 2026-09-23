"""Invoca el writer Sage SDK (empresa de PRUEBA) desde Auto-Hub."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
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
    """Host Sage/CMD: corre, pero sin ventana ni icono en la barra de tareas."""
    if os.name != "nt":
        return {}
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = 0
    return {"creationflags": flags, "startupinfo": info}


def _hide_process_windows(pid: int) -> None:
    """Por si PowerShell igual crea un hwnd: ocultarlo y quitarlo de la barra."""
    if os.name != "nt" or int(pid or 0) <= 0:
        return
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        gwl_exstyle = -20
        ws_ex_appwindow = 0x00040000
        ws_ex_toolwindow = 0x00000080
        sw_hide = 0
        want = int(pid)

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def _enum(hwnd: int, _lparam: int) -> bool:
            got = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(got))
            if int(got.value) != want:
                return True
            try:
                user32.ShowWindow(hwnd, sw_hide)
                ex = user32.GetWindowLongW(hwnd, gwl_exstyle)
                user32.SetWindowLongW(
                    hwnd,
                    gwl_exstyle,
                    (int(ex) | ws_ex_toolwindow) & ~ws_ex_appwindow,
                )
                user32.ShowWindow(hwnd, sw_hide)
            except Exception:
                pass
            return True

        user32.EnumWindows(_enum, 0)
    except Exception:
        pass


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


def _sage_pids() -> list[int]:
    pids: list[int] = []
    for name in ("peachw.exe", "Peachtree.exe"):
        try:
            proc = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {name}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=15,
                **_hidden_kw(),
            )
        except Exception:
            continue
        for line in (proc.stdout or "").splitlines():
            parts = [p.strip().strip('"') for p in line.split(",")]
            if len(parts) >= 2 and parts[1].isdigit():
                pids.append(int(parts[1]))
    return pids


def _focus_sage_ui() -> None:
    """Pone Sage al frente para que Maintain Inventory reciba teclas/UIA."""
    pids = set(_sage_pids())
    if not pids:
        return
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        user32.AllowSetForegroundWindow(-1)
        found: list[int] = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def _enum(hwnd: int, _lparam: int) -> bool:
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if int(pid.value) in pids:
                found.append(int(hwnd))
            return True

        user32.EnumWindows(_enum, 0)
        WM_SYSCOMMAND = 0x0112
        SC_RESTORE = 0xF120
        SW_RESTORE = 9
        SW_SHOWMAXIMIZED = 3
        for hwnd in found:
            try:
                user32.OpenIcon(hwnd)
            except Exception:
                pass
            user32.PostMessageW(hwnd, WM_SYSCOMMAND, SC_RESTORE, 0)
            user32.SendMessageW(hwnd, WM_SYSCOMMAND, SC_RESTORE, 0)
            user32.ShowWindow(hwnd, SW_RESTORE)
            user32.ShowWindow(hwnd, SW_SHOWMAXIMIZED)
            try:
                user32.SwitchToThisWindow(hwnd, True)
            except Exception:
                pass
            user32.SetForegroundWindow(hwnd)
            break
    except Exception:
        pass


def _kill_image(image_name: str) -> None:
    subprocess.run(
        ["taskkill", "/F", "/IM", image_name, "/T"],
        capture_output=True,
        text=True,
        timeout=20,
        **_hidden_kw(),
    )


def _kill_sage_hosts() -> None:
    """Cierra hosts Sage colgados. Si no, Conectar/Borrar AH se quedan esperando la sesion anterior."""
    ps64 = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    if not ps64.exists():
        return
    script = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.Name -match 'powershell' -and $_.CommandLine -like '*RunSageHost.ps1*' } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
    )
    try:
        subprocess.run(
            [str(ps64), "-NoProfile", "-WindowStyle", "Hidden", "-Command", script],
            capture_output=True,
            text=True,
            timeout=20,
            **_hidden_kw(),
        )
    except Exception:
        pass


def _ensure_writer_dead() -> None:
    _kill_image("WriteTestInvoice.exe")
    _kill_sage_hosts()
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


def _short_documento(rec: dict[str, Any]) -> str:
    """Id corto tipo C0003345, *0008018, 00011222 (tambien dentro de factura_id compuesto)."""
    explicit = str(rec.get("documento") or "").strip()
    if explicit and not explicit.upper().startswith("FE"):
        return explicit
    blob = f"{rec.get('factura_id') or ''} {rec.get('numero_factura') or ''}"
    marked = re.search(r"(C\d{7}|\*\d{7,})", blob, flags=re.IGNORECASE)
    if marked:
        return marked.group(1)
    for raw in (rec.get("factura_id"), rec.get("numero_factura")):
        text = str(raw or "").strip()
        if not text or text.upper().startswith("FE"):
            continue
        if ":" in text:
            text = text.rsplit(":", 1)[-1].strip()
        if text and len(text) <= 12:
            return text
    digits = re.search(r"\d{7,}", blob)
    if digits:
        return digits.group(0)
    return ""


def sucursal_label(rec: dict[str, Any]) -> str:
    # Pending manda sucursal en camel; si no, la tienda va en el documento (C / * / digito).
    named = str(rec.get("sucursal") or "").strip().upper()
    if "RIO ABAJO" in named:
        return "SIKA CENTER RIO ABAJO"
    if "CORONADO" in named:
        return "CORONADO"
    if named.startswith("ADI"):
        return "ADI SUPPLY"
    doc = _short_documento(rec)
    if not doc:
        return "SIN SUCURSAL"
    first = doc[0]
    if first.upper() == "C":
        return "CORONADO"
    if first == "*":
        return "SIKA CENTER RIO ABAJO"
    if first.isdigit():
        return "ADI SUPPLY"
    return "SIN SUCURSAL"


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


def _money(value: Any) -> float:
    raw = Decimal(str(value if value not in (None, "") else 0))
    return float(raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _raw_number(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    return float(Decimal(str(value)))


def _coerce_row(rec: dict[str, Any]) -> dict[str, Any]:
    qty = float(rec.get("cantidad") or 0)
    price = _money(rec.get("precio_unitario") or 0)
    item_codigo = str(
        rec.get("item_codigo")
        or rec.get("codigo")
        or rec.get("itemCode")
        or rec.get("itemCodigo")
        or rec.get("sku")
        or rec.get("coditem")
        or ""
    ).strip()
    dsctounit = _raw_number(
        rec.get("dsctounit") if rec.get("dsctounit") not in (None, "") else rec.get("dsctoUnit")
    )
    dsctoprc = _raw_number(
        rec.get("dsctoprc")
        if rec.get("dsctoprc") not in (None, "")
        else (rec.get("dsctoPrc") if rec.get("dsctoPrc") not in (None, "") else rec.get("desctoprc"))
    )
    documento = str(rec.get("documento") or "").strip()
    if not documento:
        documento = _short_documento(rec)
    return {
        "factura_id": str(rec.get("factura_id") or ""),
        "numero_factura": str(rec.get("numero_factura") or ""),
        "documento": documento,
        "fecha_emision": _as_iso_date(rec.get("fecha_emision")),
        "subtotal": _money(rec.get("subtotal") or 0),
        "itbms_factura": _money(rec.get("itbms_factura") or 0),
        "total_factura": _money(rec.get("total_factura") or 0),
        "cliente_codigo": str(rec.get("cliente_codigo") or ""),
        "cliente_nombre": str(rec.get("cliente_nombre") or ""),
        "ruc": str(rec.get("ruc") or "CF"),
        "linea": int(rec.get("linea") or 1),
        "descripcion": str(rec.get("descripcion") or ""),
        "cantidad": qty,
        "precio_unitario": price,
        "tasa_itbms": float(rec.get("tasa_itbms") or 0.07),
        "total_linea": _money(Decimal(str(qty)) * Decimal(str(price))),
        "sucursal_codigo": str(rec.get("sucursal_codigo") or "").strip(),
        "sucursal": sucursal_label(rec),
        "item_codigo": item_codigo,
        "codigo": item_codigo,
        "dsctounit": dsctounit,
        "dsctoprc": dsctoprc,
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
    timeout_sec: int | None = None,
    hold_missing: bool = False,
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

    return _run_writer(
        root,
        rows,
        on_log=log,
        auth_only=False,
        timeout_sec=timeout_sec,
        hold_missing=hold_missing,
    )


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


def _forget_sent_refs(root: Path, refs: set[str]) -> int:
    if not refs:
        return 0
    data = _load_sent_log(root)
    n = 0
    for bucket in ("by_factura_id", "by_numero"):
        drop = [
            key
            for key, value in data[bucket].items()
            if str((value or {}).get("sage_ref") or "") in refs
        ]
        for key in drop:
            del data[bucket][key]
            n += 1
    if n:
        _save_sent_log(root, data)
    return n


def _forget_all_ah_sent(root: Path) -> int:
    data = _load_sent_log(root)
    n = 0
    for bucket in ("by_factura_id", "by_numero"):
        drop = [
            key
            for key, value in data[bucket].items()
            if str((value or {}).get("sage_ref") or "").upper().startswith("AH")
        ]
        for key in drop:
            del data[bucket][key]
            n += 1
    if n:
        _save_sent_log(root, data)
    return n


def _entry_blob(key: str, value: dict[str, Any] | None) -> str:
    v = value or {}
    return " ".join(
        [
            str(key or ""),
            str(v.get("sage_ref") or ""),
            str(v.get("factura_id") or ""),
            str(v.get("numero_factura") or ""),
        ]
    ).upper()


def forget_sent_needles(root: Path, needles: list[str]) -> int:
    """Quita del sent-log claves/refs que coincidan (8012, *0008013, -08012)."""
    cleaned = [str(n or "").strip().upper().lstrip("*") for n in needles if str(n or "").strip()]
    if not cleaned:
        return 0
    data = _load_sent_log(root)
    n = 0
    for bucket in ("by_factura_id", "by_numero"):
        drop = []
        for key, value in data[bucket].items():
            blob = _entry_blob(str(key), value)
            blob_plain = blob.replace("*", "")
            if any(nd in blob_plain for nd in cleaned):
                drop.append(key)
        for key in drop:
            del data[bucket][key]
            n += 1
    if n:
        _save_sent_log(root, data)
    return n


def delete_ah_invoices(
    root: Path,
    on_log: Callable[[str], None] | None = None,
    only_seq: list[str] | None = None,
) -> dict[str, int]:
    """Borra en Sage las Sales Invoices AH. only_seq=['08012','08013'] limita el borrado."""

    def log(msg: str) -> None:
        if on_log:
            on_log(msg)

    if not sage_ui_running():
        raise RuntimeError(
            "Abre Sage 50 en LYL CONSTRUCTIONS SUPPLY INC 2025-2026 y vuelve a pulsar Borrar AH."
        )

    _ensure_writer_dead()
    sdk_dir = sdk_script_dir(root)
    host = sdk_dir / "RunSageHost.ps1"
    if not host.exists():
        raise FileNotFoundError("Falta RunSageHost.ps1 en " + str(sdk_dir))
    _read_app_id(sdk_dir)
    seqs = [str(s).strip() for s in (only_seq or []) if str(s).strip()]
    if seqs:
        log("Borrando en Sage solo AH*-" + ", AH*-".join(seqs) + "...")
    else:
        log("Borrando facturas AH de Sage...")
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
        "-DeleteAh",
    ]
    if seqs:
        cmd.extend(["-OnlySeq", ",".join(seqs)])
    proc = subprocess.Popen(
        cmd,
        cwd=str(sdk_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        **_hidden_kw(),
    )
    _hide_process_windows(int(proc.pid or 0))
    try:
        out, err = proc.communicate(timeout=400)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            out, err = proc.communicate(timeout=10)
        except Exception:
            out, err = "", ""
        _ensure_writer_dead()
        text = (out or "") + (err or "")
        _dump_sage_fail(root, "borrar-AH", text, log)
        raise RuntimeError("Sage no termino de borrar las facturas AH. Revisa Always Allow y vuelve a intentar.")
    finally:
        if proc.poll() is None:
            proc.kill()
            _ensure_writer_dead()

    text = (out or "") + (err or "")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            log(stripped)
    if proc.returncode != 0:
        _dump_sage_fail(root, "borrar-AH", text, log)
        raise RuntimeError("No se pudieron borrar las facturas AH. " + _sage_error_hint(text))

    deleted = [
        line.split(":", 1)[-1].strip()
        for line in text.splitlines()
        if line.strip().lower().startswith("borrada:")
    ]
    failed = sum(1 for line in text.splitlines() if line.strip().lower().startswith("no se pudo borrar"))
    if seqs:
        forgotten = forget_sent_needles(root, seqs + ["000" + s for s in seqs])
        forgotten += _forget_sent_refs(root, set(deleted))
    elif failed == 0:
        forgotten = _forget_all_ah_sent(root)
    else:
        forgotten = _forget_sent_refs(root, set(deleted))
    log("Quitadas de enviadas: " + str(forgotten))
    return {"deleted": len(deleted), "failed": failed, "forgotten": forgotten}


def probe_sage_items(
    root: Path,
    on_log: Callable[[str], None] | None = None,
) -> str:
    """Prueba match de S-020 / P-001 / N-001 en LYL. No crea items ni facturas."""

    def log(msg: str) -> None:
        if on_log:
            on_log(msg)

    if not sage_ui_running():
        raise RuntimeError(
            "Abre Sage 50 en LYL CONSTRUCTIONS SUPPLY INC 2025-2026 y vuelve a pulsar Probar items."
        )

    _ensure_writer_dead()
    sdk_dir = sdk_script_dir(root)
    host = sdk_dir / "RunSageHost.ps1"
    if not host.exists():
        raise FileNotFoundError("Falta RunSageHost.ps1 en " + str(sdk_dir))
    _read_app_id(sdk_dir)
    log("Probando match de items en Sage (S-020, P-001, N-001; no se crean)...")
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
        "-ProbeItems",
    ]
    proc = subprocess.Popen(
        cmd,
        cwd=str(sdk_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        **_hidden_kw(),
    )
    _hide_process_windows(int(proc.pid or 0))
    try:
        out, err = proc.communicate(timeout=300)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            out, err = proc.communicate(timeout=10)
        except Exception:
            out, err = "", ""
        _ensure_writer_dead()
        text = (out or "") + (err or "")
        _dump_sage_fail(root, "probe-items", text, log)
        raise RuntimeError("Sage no termino la prueba de items. Revisa Always Allow y vuelve a intentar.")
    finally:
        if proc.poll() is None:
            proc.kill()
            _ensure_writer_dead()

    text = (out or "") + (err or "")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            log(stripped)
    if proc.returncode != 0:
        _dump_sage_fail(root, "probe-items", text, log)
        raise RuntimeError("La prueba de items fallo. " + _sage_error_hint(text))
    summary = next(
        (line.strip() for line in text.splitlines() if line.strip().upper().startswith("PROBE RESUMEN")),
        "Prueba de items terminada.",
    )
    return summary


def build_full_probe_rows() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Factura de prueba: cliente nuevo, 3 SKU que ya existen, 2 con descuento, Rio 4001/4031."""
    now = datetime.now()
    stamp = now.strftime("%H%M%S")
    seq = "99" + f"{int(time.time()) % 1000:03d}"
    doc = "*00" + seq
    cust_id = "AHT" + now.strftime("%y%m%d%H%M%S")
    cust_name = "AH TEST " + stamp
    skus = ["S-020", "P-001", "N-001"]
    specs = [
        (1, skus[0], "SELLADOR TRANSP.ACRILICO", 2.0, 15.00, 1.25),
        (2, skus[1], "MALLA DE SARAN NEG. 80%", 3.0, 8.00, 0.50),
        (3, skus[2], "ONETIME MASILLA DE 1GL", 1.0, 12.50, 0.0),
    ]
    line_totals: list[float] = []
    disc_total = Decimal("0")
    rows: list[dict[str, Any]] = []
    today = date.today().isoformat()
    for linea, sku, desc, qty, price, dscto in specs:
        line_totals.append(_money(Decimal(str(qty)) * Decimal(str(price))))
        disc_total += Decimal(str(qty)) * Decimal(str(dscto))
        rows.append(
            {
                "factura_id": "000002:001:FAC:" + doc,
                "numero_factura": doc,
                "documento": doc,
                "fecha_emision": today,
                "subtotal": 0,
                "itbms_factura": 0,
                "total_factura": 0,
                "cliente_codigo": cust_id,
                "cliente_nombre": cust_name,
                "ruc": "CF",
                "linea": linea,
                "descripcion": desc,
                "cantidad": qty,
                "precio_unitario": price,
                "tasa_itbms": 0.07,
                "total_linea": _money(Decimal(str(qty)) * Decimal(str(price))),
                "sucursal_codigo": "*",
                "sucursal": "Sika Center Rio Abajo",
                "item_codigo": sku,
                "codigo": sku,
                "dsctounit": dscto,
                "dsctoprc": 10 if dscto else 0,
            }
        )
    subtotal = _money(sum(line_totals))
    discount = _money(disc_total)
    taxable = _money(Decimal(str(subtotal)) - Decimal(str(discount)))
    itbms = _money(Decimal(str(taxable)) * Decimal("0.07"))
    total = _money(Decimal(str(taxable)) + Decimal(str(itbms)))
    for row in rows:
        row["subtotal"] = subtotal
        row["itbms_factura"] = itbms
        row["total_factura"] = total
    meta: dict[str, Any] = {
        "seq": seq,
        "documento": doc,
        "customer_id": cust_id,
        "customer_name": cust_name,
        "skus": skus,
        "sales_gl": "4001",
        "discount_gl": "4031",
        "subtotal": subtotal,
        "discount": discount,
        "itbms": itbms,
        "total": total,
        "expected_ref_part": "-R-" + seq,
        "stamp": stamp,
    }
    return rows, meta


def _probe_check(name: str, ok: bool, detail: str = "") -> dict[str, Any]:
    return {"name": name, "ok": bool(ok), "detail": detail}


def _analyze_full_probe(blob: str, meta: dict[str, Any]) -> list[dict[str, Any]]:
    low = blob.lower()
    matched = "item sage encontrado" in low or "[item] match" in low or ("item=" in low and "linea 1" in low)
    fail16 = "no existe en sage" in low or "codigo 16" in low
    checks = [
        _probe_check(
            "Factura guardada",
            "ok - factura guardada" in low or "listo: la factura ya esta" in low,
        ),
        _probe_check(
            "Invoice No Rio " + str(meta["expected_ref_part"]),
            str(meta["expected_ref_part"]).lower() in low or str(meta["seq"]) in blob,
        ),
        _probe_check("Linea 1", "linea 1" in low),
        _probe_check("Linea 2", "linea 2" in low),
        _probe_check("Linea 3", "linea 3" in low),
        _probe_check("Descuento en factura", "descuento" in low),
        _probe_check("Cuenta ventas 4001", "4001" in blob),
        _probe_check("Cuenta descuento 4031", "4031" in blob),
        _probe_check(
            "Cliente nuevo",
            any(
                token in low
                for token in (
                    "cliente nuevo",
                    "creando cliente",
                    "este cliente no estaba",
                    "customerfactory",
                    "createcustomer",
                )
            ),
        ),
        _probe_check(
            "Items MATCH en Sage",
            matched and not fail16,
            "MATCH" if matched and not fail16 else "sin match",
        ),
    ]
    for sku in meta.get("skus") or []:
        checks.append(_probe_check("SKU " + str(sku), str(sku).lower() in low))
    return checks


def _failure_digest(log_lines: list[str]) -> list[str]:
    """Seccion corta: funcion, paso, linea de factura y SKU del ultimo FAIL."""
    out = ["DONDE FALLO", "------------"]
    fails: list[str] = []
    traces: list[str] = []
    for raw in log_lines:
        s = str(raw or "").strip()
        if not s:
            continue
        low = s.lower()
        if s.startswith("[TRACE]"):
            traces.append(s)
            if " fail " in low or "ultimo_fail" in low or "ultimo_paso" in low:
                fails.append(s)
        elif "aviso win32 ui no cargo" in low:
            fails.append(s[:500])
        elif s.startswith("[ITEM] FALLO") or s.startswith("[ITEM] UI no creo"):
            fails.append(s[:400])
        elif low.startswith("error:"):
            fails.append(s[:500])
        elif "salio con codigo" in low or "no existe en sage" in low or "no se pudo crear item sage" in low:
            fails.append(s[:500])
    if fails:
        out.append("Ultimos FAIL:")
        for item in fails[-15:]:
            out.append("  * " + item)
    elif traces:
        out.append("(no hay FAIL; ultima traza:)")
        out.append("  * " + traces[-1][:400])
    else:
        out.append("(sin FAIL marcado; ver LOG SAGE abajo)")
        return out
    last = fails[-1] if fails else traces[-1]
    out.append("")
    out.append("Resumen:")
    fn = re.search(r"fn=([^\s]+)", last)
    paso = re.search(r"paso=([^\s]+)", last)
    linea = re.search(r"linea[= ](\d+)", last, flags=re.I)
    sku = re.search(r"sku=([^\s]+)|codigo=([^\s|]+)", last, flags=re.I)
    if fn:
        out.append("  Funcion: " + fn.group(1))
    if paso:
        out.append("  Paso: " + paso.group(1))
    if linea:
        out.append("  Linea de factura: " + linea.group(1))
    if sku:
        out.append("  SKU: " + (sku.group(1) or sku.group(2)))
    low_last = last.lower()
    if "add-type" in low_last or "no cargo" in low_last or "no existe en el contexto" in low_last:
        out.append("  Donde: Ensure-SageUiWin32 (compilacion C# SageUiHost)")
        out.append("  Que: el host Win32 no cargo; click de menu y CloseJournal no se ejecutaron.")
    elif "openinventorywindow" in low_last or "waitinventory" in low_last:
        out.append("  Donde: SageUiHost.OpenInventoryWindow")
        out.append("  Que: Sage no abrio Maintain Inventory Items (LINEITEM).")
    elif "createinventoryitem" in low_last:
        out.append("  Donde: SageUiHost.CreateInventoryItem")
        out.append("  Que: la ventana de inventario abrio pero no se pudo rellenar/guardar el SKU.")
    elif " com " in low_last or "paso=com" in low_last:
        out.append("  Donde: Import-SageInventoryItemCom")
    out.append("  Ultimo mensaje: " + last[:400])
    if traces:
        out.extend(["", "TRAZA (ultimas 40)", "-------------------"])
        out.extend(traces[-40:])
    return out


def _write_full_probe_report(
    root: Path,
    meta: dict[str, Any],
    *,
    saved: bool,
    sage_ref: str,
    deleted: dict[str, int] | None,
    delete_error: str,
    checks: list[dict[str, Any]],
    log_lines: list[str],
) -> Path:
    from src.session_log import log_dir

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = log_dir(root) / ("sage-probe-full-" + stamp + ".txt")
    passed = sum(1 for c in checks if c.get("ok"))
    failed = sum(1 for c in checks if not c.get("ok"))
    lines = [
        "PRUEBA FULL SAGE",
        "Fecha: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Empresa: " + TEST_COMPANY,
        "",
        "Documento: " + str(meta.get("documento") or ""),
        "Seq Invoice: " + str(meta.get("seq") or ""),
        "Invoice No esperado: AH" + date.today().strftime("%d%m%y") + str(meta.get("expected_ref_part") or ""),
        "Invoice No Sage: " + (sage_ref or "(no salio en el log)"),
        "Cliente nuevo: " + str(meta.get("customer_id") or "") + " | " + str(meta.get("customer_name") or ""),
        "Items: " + ", ".join(str(s) for s in (meta.get("skus") or [])),
        "Lineas: 3 (qty 2 / 3 / 1). Descuento lineas 1 y 2.",
        "Cuentas: ventas "
        + str(meta.get("sales_gl") or "4001")
        + ", descuento "
        + str(meta.get("discount_gl") or "4031")
        + ", ITBMS 7%.",
        "Montos: subtotal "
        + str(meta.get("subtotal"))
        + "  descuento "
        + str(meta.get("discount"))
        + "  ITBMS "
        + str(meta.get("itbms"))
        + "  total "
        + str(meta.get("total")),
        "",
        "RESULTADO GUARDAR: " + ("OK" if saved else "FALLO"),
        "RESULTADO BORRAR: "
        + (
            "no se intento (no se guardo)"
            if not saved
            else (
                "error: " + delete_error
                if delete_error
                else "OK deleted="
                + str((deleted or {}).get("deleted") or 0)
                + " failed="
                + str((deleted or {}).get("failed") or 0)
            )
        ),
        "",
        "CHEQUEOS: " + str(passed) + " ok / " + str(failed) + " fallo",
    ]
    for check in checks:
        mark = "OK" if check.get("ok") else "FAIL"
        extra = ("  " + str(check.get("detail") or "")).rstrip()
        lines.append("  [" + mark + "] " + str(check.get("name") or "") + extra)
    lines.append("")
    lines.extend(_failure_digest(log_lines))
    lines.extend(
        [
            "",
            "NOTA: el cliente AHT* queda en Sage para que lo veas. Los items no se crean (solo match).",
            "La factura de prueba se borra solo si se guardo. No se tocan otras AH.",
            "",
            "LOG SAGE",
            "--------",
        ]
    )
    lines.extend(log_lines)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", errors="replace")
    return path


def run_full_sage_probe(
    root: Path,
    on_log: Callable[[str], None] | None = None,
) -> str:
    """Escribe una factura completa de prueba, la borra si sale OK, y deja un reporte en logs/."""

    def log(msg: str) -> None:
        if on_log:
            on_log(msg)

    if not sage_ui_running():
        raise RuntimeError(
            "Abre Sage 50 en LYL CONSTRUCTIONS SUPPLY INC 2025-2026 y vuelve a pulsar Prueba full."
        )

    rows, meta = build_full_probe_rows()
    captured: list[str] = []

    def capture(msg: str) -> None:
        text = str(msg)
        captured.append(text)
        log(text)

    log(
        "Prueba full Sage: cliente "
        + str(meta["customer_id"])
        + " + 3 items existentes "
        + ", ".join(meta["skus"])
        + " + descuento 4031 + ventas 4001."
    )
    forget_sent_needles(root, [str(meta["seq"]), str(meta["documento"])])

    saved = False
    sage_ref = ""
    write_error = ""
    try:
        run_test_company_write(root, rows, on_log=capture, timeout_sec=420)
    except Exception as exc:
        write_error = str(exc)
        capture("Error prueba full: " + write_error)

    blob = "\n".join(captured)
    low = blob.lower()
    saved = "ok - factura guardada" in low or "listo: la factura ya esta" in low
    sage_ref = _parse_sage_ref(blob)
    if not sage_ref:
        sent = find_sent_invoice(root, rows)
        sage_ref = str((sent or {}).get("sage_ref") or "")
    checks = _analyze_full_probe(blob, meta)
    if write_error:
        checks.insert(0, _probe_check("Writer sin excepcion", False, write_error[:200]))

    deleted: dict[str, int] | None = None
    delete_error = ""
    if saved:
        log("Factura de prueba guardada. Borrando solo AH*-" + str(meta["seq"]) + "...")
        try:
            deleted = delete_ah_invoices(root, on_log=capture, only_seq=[str(meta["seq"])])
            if int((deleted or {}).get("deleted") or 0) < 1:
                delete_error = "Sage no reporto Borrada: para " + str(meta["seq"])
        except Exception as exc:
            delete_error = str(exc)
            capture("No se pudo borrar la factura de prueba: " + delete_error)
    else:
        log("No se guardo la factura. No se borra nada.")

    report = _write_full_probe_report(
        root,
        meta,
        saved=saved,
        sage_ref=sage_ref,
        deleted=deleted,
        delete_error=delete_error,
        checks=checks,
        log_lines=captured,
    )
    log("Reporte de prueba full: " + str(report))

    fail_names = [str(c.get("name")) for c in checks if not c.get("ok")]
    if saved and not delete_error and not fail_names:
        summary = (
            "Prueba full: OK. "
            + (sage_ref or ("AH*-" + str(meta["seq"])))
            + " creada y borrada. Reporte: "
            + report.name
        )
    elif saved and not delete_error:
        summary = (
            "Prueba full: factura "
            + (sage_ref or str(meta["seq"]))
            + " creada y borrada, con avisos: "
            + ", ".join(fail_names)
            + ". Reporte: "
            + report.name
        )
    elif saved:
        summary = (
            "Prueba full: se creo "
            + (sage_ref or str(meta["seq"]))
            + " pero no se borro ("
            + delete_error
            + "). Reporte: "
            + report.name
        )
    else:
        summary = "Prueba full: FALLO al crear la factura. Reporte: " + report.name
        raise RuntimeError(summary)
    return summary


PLAYA_TEST_ROWS: list[dict[str, Any]] = [
    {
        "factura_id": "AHTEST-PLAYA-1",
        "numero_factura": "AHTEST-PLAYA-1",
        "fecha_emision": date.today().isoformat(),
        "subtotal": 10.00,
        "itbms_factura": 0.70,
        "total_factura": 10.70,
        "cliente_codigo": TEST_CUSTOMER_ID,
        "cliente_nombre": TEST_CUSTOMER_ID,
        "ruc": "CF",
        "linea": 1,
        "descripcion": "C0003355 PLAYA BLANCA",
        "cantidad": 1,
        "precio_unitario": 10.00,
        "tasa_itbms": 0.07,
        "total_linea": 10.00,
        "sucursal_codigo": "C",
        "sucursal": "CORONADO",
        "item_codigo": "C0003355",
        "codigo": "C0003355",
        "dsctounit": 0,
        "dsctoprc": 0,
    }
]


def run_playa_blanca_test(
    root: Path,
    on_log: Callable[[str], None] | None = None,
) -> int:
    """Una linea PLAYA BLANCA para verificar create+attach en esta PC."""
    stamp = datetime.now().strftime("%H%M%S")
    num = "AHTESTP" + stamp
    row = dict(PLAYA_TEST_ROWS[0])
    row["factura_id"] = num
    row["numero_factura"] = num
    row["fecha_emision"] = date.today().isoformat()
    return run_test_company_write(root, [row], on_log=on_log)


def _customer_map_paths(root: Path) -> list[Path]:
    from src.paths import app_root, resource_root

    return [
        app_root() / "config" / "sage_customer_map.json",
        root / "config" / "sage_customer_map.json",
        resource_root() / "config" / "sage_customer_map.json",
    ]


def _load_customer_map(root: Path) -> dict[str, str]:
    merged: dict[str, str] = {}
    for path in _customer_map_paths(root):
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        for bucket in ("by_codigo", "by_nombre"):
            block = data.get(bucket) or {}
            if isinstance(block, dict):
                for key, value in block.items():
                    k = str(key or "").strip().upper()
                    v = str(value or "").strip()
                    if k and v:
                        merged[k] = v
        for key, value in data.items():
            if key in ("by_codigo", "by_nombre") or not isinstance(value, str):
                continue
            k = str(key or "").strip().upper()
            v = value.strip()
            if k and v:
                merged[k] = v
        break
    return merged


def _customer_from_rows(root: Path, rows: list[dict[str, Any]]) -> tuple[str, str]:
    rec = rows[0] if rows else {}
    codigo = str(rec.get("cliente_codigo") or "").strip()
    nombre = str(rec.get("cliente_nombre") or "").strip()
    mapped = _load_customer_map(root)
    sage_name = mapped.get(codigo.upper()) or mapped.get(nombre.upper())
    if sage_name:
        return sage_name, sage_name
    return codigo, nombre


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


def _invoice_label(rows: list[dict[str, Any]]) -> str:
    rec = rows[0] if rows else {}
    return str(rec.get("factura_id") or rec.get("numero_factura") or "factura").strip() or "factura"


def _sage_error_hint(text: str) -> str:
    last_fail = ""
    for line in text.splitlines():
        stripped = line.strip()
        lower = stripped.lower()
        if stripped.startswith("[TRACE]") and (" fail " in lower or "ultimo_fail" in lower):
            last_fail = stripped[:280]
        elif "aviso win32 ui no cargo" in lower:
            last_fail = stripped[:280]
        elif lower.startswith("error") or "rounded" in lower or "current period" in lower or "unit price" in lower:
            last_fail = stripped[:240]
    return last_fail


def _dump_sage_fail(root: Path, label: str, text: str, on_log: Callable[[str], None]) -> None:
    try:
        from src.session_log import write_sage_fail

        path = write_sage_fail(root, label, text)
        if path:
            on_log("Dump Sage: " + str(path))
    except Exception:
        pass


def _host_output(out: str, err: str, host_log: Path | None) -> str:
    """Prefiere el transcript; no concatena dos copias del mismo output."""
    text = (out or "") + (err or "")
    if host_log is None or not host_log.exists():
        return text
    try:
        transcript = host_log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return text
    if not transcript.strip():
        return text
    stderr = (err or "").strip()
    if stderr and stderr not in transcript:
        return transcript + "\n" + stderr
    return transcript


def _run_writer(
    root: Path,
    rows: list[dict[str, Any]],
    *,
    on_log: Callable[[str], None],
    auth_only: bool,
    timeout_sec: int | None = None,
    hold_missing: bool = False,
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
        json_path = write_outbox_json(
            sdk_dir / ("sample_" + str(os.getpid()) + "_" + str(int(time.time() * 1000)) + ".json"),
            rows,
        )
        on_log("JSON escrito: " + json_path.name + " (" + str(len(rows)) + " lineas)")

    try:
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
        cust_id, cust_name = _customer_from_rows(root, rows)
        if auth_only:
            on_log("Modo autorizar: espera Always Allow en Sage (hasta 3 min).")
        else:
            origen = ""
            if rows:
                origen = str(rows[0].get("cliente_nombre") or rows[0].get("cliente_codigo") or "")
            on_log("Cliente factura: " + (cust_id or "(sin codigo)") + " | " + (cust_name or "(sin nombre)"))
            if origen and cust_name and origen.strip().upper() != cust_name.strip().upper():
                on_log("  Mapeado desde PsKloud: " + origen)

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
        popen_kw: dict[str, Any] = {
            "cwd": str(sdk_dir),
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            **_hidden_kw(),
        }
        host_log = None
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
            host_log = sdk_dir / ("hostlog_" + str(os.getpid()) + ".txt")
            env = os.environ.copy()
            env["AUTOHUB_SAGE_HOST_LOG"] = str(host_log)
            popen_kw["env"] = env
        proc = subprocess.Popen(cmd, **popen_kw)
        _hide_process_windows(int(proc.pid or 0))
        timeout_sec = int(timeout_sec or 240)
        label = "auth" if auth_only else _invoice_label(rows)
        try:
            out, err = proc.communicate(timeout=timeout_sec)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                out, err = proc.communicate(timeout=10)
            except Exception:
                out, err = "", ""
            _ensure_writer_dead()
            text = _host_output(out or "", err or "", host_log)
            _dump_sage_fail(root, label, text, on_log)
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

        text = _host_output(out or "", err or "", host_log)
        if host_log is not None and host_log.exists():
            try:
                host_log.unlink(missing_ok=True)
            except OSError:
                pass
        for line in text.splitlines():
            stripped = line.strip()
            if stripped:
                on_log(stripped)
        if proc.returncode != 0:
            _dump_sage_fail(root, label, text, on_log)
            hint = _sage_error_hint(text)
            msg = (
                ("Conectar Sage" if auth_only else "Enviar a Sage")
                + " salio con codigo "
                + str(proc.returncode)
                + ((" " + hint) if hint else "")
            )
            if hold_missing and (not auth_only) and int(proc.returncode) == 16:
                from src.sage_retry import MissingSageItems, queue_failed_invoice

                entry = queue_failed_invoice(root, rows, hint or msg, text)
                missing = list(entry.get("missing_skus") or [])
                on_log(
                    "FALLIDA guardada: "
                    + label
                    + " | crear en Sage: "
                    + (", ".join(missing) if missing else "ver items_pendientes.txt")
                )
                raise MissingSageItems(msg, missing)
            raise RuntimeError(msg)
        if not auth_only:
            sage_ref = _parse_sage_ref(text)
            sucursal = str((rows[0] or {}).get("sucursal") or "")
            record_sent_invoice(root, rows, sage_ref=sage_ref or "AH", sucursal=sucursal)
            low_text = text.lower()
            if "ok - factura guardada" not in low_text and "listo: la factura ya esta" not in low_text:
                on_log("OK - factura guardada")
            if sage_ref:
                on_log("Reference: " + sage_ref)
            else:
                on_log("AVISO: Sage no imprimio ReferenceNumber en el log")
        return proc.returncode
    finally:
        if json_path is not None:
            try:
                json_path.unlink(missing_ok=True)
            except OSError:
                pass
