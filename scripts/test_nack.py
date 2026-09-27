"""Ack solo cierra lo guardado. Nack permanente saca fallos de datos de la cola."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import src.ledger_bridge as bridge


def main() -> None:
    permanent, error = bridge.cloud_failure("linea 1 sin item_codigo | TORNILLO")
    assert permanent and error.startswith("MISSING_ITEM:"), error
    permanent, error = bridge.cloud_failure("ITBMS no cuadra 4.97 vs 4.54")
    assert permanent and error.startswith("MANUAL_REVIEW:"), error
    permanent, error = bridge.cloud_failure("Sage timeout al guardar")
    assert not permanent and error.startswith("SAGE_TIMEOUT:"), error
    permanent, error = bridge.cloud_failure("cliente 155 no existe")
    assert permanent and error.startswith("MISSING_CUSTOMER:"), error

    calls = []

    def fake_request(method, url, token, body=None, timeout=60):
        calls.append((method, url, body))
        if url.endswith("/v1/ack"):
            n = len(body["items"])
            return 200, {"ok": True, "confirmed": n, "received": n, "alreadyConsumed": 0}, ""
        n = len(body["items"])
        return 200, {"ok": True, "released": n}, ""

    bridge._request = fake_request
    bridge.load_jwt = lambda root, config: "token"
    item = {"branchId": "b1", "facturaId": "000002:001:FAC:C0003389"}
    logs = []
    stats = {"failed": 0}
    bridge._finish_cloud(
        ROOT,
        {},
        logs.append,
        stats,
        [item],
        [{**item, "facturaId": "000002:001:FAC:C0003378", "error": "MISSING_ITEM: 750748"}],
        [{**item, "facturaId": "000002:001:FAC:C0003379", "error": "SAGE_TIMEOUT"}],
    )
    assert stats["failed"] == 0, stats
    ack = next(body for _m, url, body in calls if url.endswith("/v1/ack"))
    assert ack["items"] == [item], ack
    nacks = [body for _m, url, body in calls if url.endswith("/v1/nack")]
    assert nacks[0]["permanent"] is True, nacks
    assert nacks[0]["items"][0]["error"].startswith("MISSING_ITEM:")
    assert nacks[1]["permanent"] is False
    assert any("confirmed=1" in line for line in logs), logs
    assert any("permanent=true" in line for line in logs), logs

    calls.clear()
    bridge._request = lambda method, url, token, body=None, timeout=60: (
        200,
        {"ok": True, "confirmed": 0, "received": 1, "alreadyConsumed": 0},
        "",
    )
    try:
        bridge.ack_ids(ROOT, {}, [item])
    except RuntimeError as exc:
        assert "confirmed=0" in str(exc), exc
    else:
        raise AssertionError("ack con confirmed 0 debio fallar")
    print("OK: nack permanente, nack transitorio y ack incompleto.")


if __name__ == "__main__":
    main()
