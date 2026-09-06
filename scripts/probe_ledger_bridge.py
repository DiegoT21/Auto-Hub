"""Prueba Ledger Bridge sin Sage: health, pending, ingest vacio, ack vacio."""
from __future__ import annotations

import json
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = "https://bt41axxide.execute-api.us-east-1.amazonaws.com"
ROOT = Path(__file__).resolve().parent.parent
HUB_EXTRAC = ROOT.parent
CTX = ssl.create_default_context()


def _jwt(path: Path) -> str:
    text = path.read_text(encoding="utf-8").strip()
    return text.splitlines()[0].strip() if text else ""


def call(method: str, path: str, token: str | None = None, body: dict | None = None) -> tuple[int, str]:
    headers = {"Accept": "application/json"}
    data = None
    if token:
        headers["Authorization"] = "Bearer " + token
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=25, context=CTX) as resp:
            return int(resp.status), resp.read().decode("utf-8", errors="replace")[:800]
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read().decode("utf-8", errors="replace")[:800]
    except Exception as exc:
        return 0, str(exc)


def main() -> int:
    injector = HUB_EXTRAC / "cred ledge.txt"
    extractor = HUB_EXTRAC / "cred ledge sage.txt"
    local_jwt = ROOT / "config" / "ledger_bridge.jwt"
    inj = _jwt(injector) if injector.is_file() else (_jwt(local_jwt) if local_jwt.is_file() else "")
    ext = _jwt(extractor) if extractor.is_file() else ""
    if not inj:
        print("Falta JWT injector (cred ledge.txt o config/ledger_bridge.jwt)")
        return 1
    if not ext:
        print("Falta JWT extractor (cred ledge sage.txt)")
        return 1

    tests = [
        ("GET", "/health", None, None, "sin token"),
        ("GET", "/v1/pending", inj, None, "injector"),
        ("GET", "/v1/pending", ext, None, "extractor (debe fallar rol)"),
        ("POST", "/v1/ingest", ext, {"records": [], "sentAt": "2026-09-05T15:00:00Z"}, "extractor"),
        ("POST", "/v1/ingest", inj, {"records": [], "sentAt": "2026-09-05T15:00:00Z"}, "injector (debe fallar rol)"),
        ("POST", "/v1/ack", inj, {"ids": [], "factura_ids": []}, "injector"),
    ]
    print("Base:", BASE)
    print()
    bad = 0
    for method, path, token, body, who in tests:
        status, raw = call(method, path, token, body)
        print(f"{method} {path}  [{who}]  ->  {status}")
        print(raw or "(vacio)")
        print("---")
        if path == "/health" and status != 200:
            bad += 1
        if path == "/v1/pending" and who == "injector" and status not in (200, 204):
            bad += 1
        if path == "/v1/ingest" and who == "extractor" and status not in (200, 201, 204, 400):
            # 400 = auth OK, cuerpo vacio rechazado
            if status in (401, 403, 0):
                bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
