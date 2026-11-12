"""Un ciclo trae tandas de 25 hasta vaciar la cola, sin repetir lo que la nube no confirmo."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.user_log import classify
from src.auto_poll import FOLLOW_UP_MS, POLL_INTERVAL_MS, next_poll
from src.ledger_bridge import MAX_PULLS_PER_CYCLE, list_inbox_jobs, process_ledger_pending


def _tmp_job(fid: str) -> dict:
    return {
        "ack_id": fid,
        "branch_id": "branch-1",
        "raw": {"branchId": "branch-1", "facturaId": fid},
        "rows": [
            {
                "factura_id": fid,
                "numero_factura": "0 Recibida",
                "fecha_emision": "2026-09-20",
                "cliente_codigo": "C1",
                "cliente_nombre": "Cliente",
                "descripcion": "x",
                "cantidad": 1,
                "precio_unitario": 1,
                "linea": 1,
                "item_codigo": "SKU1",
            }
        ],
    }


def _batch(start: int, n: int = 25) -> tuple[list[dict], str]:
    jobs = [_tmp_job("000002:001:FAC:TMP" + str(start + i)) for i in range(n)]
    return jobs, json.dumps({"invoices": [j["raw"] for j in jobs], "count": n})


def _ack(_root, _config, items):
    return {"sent": len(items), "confirmed": len(items), "received": len(items), "alreadyConsumed": 0}


def _run(root: Path, fetch) -> tuple[dict, list[str], list[tuple[int, int, str]]]:
    logs: list[str] = []
    progress: list[tuple[int, int, str]] = []
    with (
        patch("src.ledger_bridge.is_configured", return_value=True),
        patch("src.ledger_bridge.sage_ui_running", return_value=True),
        patch("src.ledger_bridge.fetch_pending", side_effect=fetch),
        patch("src.ledger_bridge.ack_ids", side_effect=_ack),
        patch("src.ledger_bridge.run_test_company_write", side_effect=AssertionError("no Sage")),
    ):
        stats = process_ledger_pending(root, {}, logs.append, on_progress=lambda k, n, l: progress.append((k, n, l)))
    return stats, logs, progress


def main() -> None:
    # 3 tandas de 25 y luego vacia: un solo ciclo las trae todas.
    with tempfile.TemporaryDirectory() as tmp:
        queue = [_batch(0), _batch(25), _batch(50, 10), ([], "")]
        stats, logs, progress = _run(Path(tmp), lambda *_a: queue.pop(0))
        assert stats["skipped"] == 60 and stats["cleared"] == 60, stats
        assert stats["cloud_empty"] == 1 and stats["more_pending"] == 0, stats
        assert queue == []
        assert [m for m in logs if m.startswith("Tanda ")] == [
            "Tanda 1: 25 en cola...",
            "Tanda 2: 25 en cola...",
            "Tanda 3: 10 en cola...",
        ], logs
        assert any(m.startswith("Cola vacia: todo cargado (3 tanda(s)") for m in logs), logs
        assert progress[-1][2].startswith("Tanda 3 · "), progress[-1]
        assert next_poll(0, stats)[1:] == (POLL_INTERVAL_MS, "work")

    # La nube repite las mismas: se corta, no hay bucle.
    with tempfile.TemporaryDirectory() as tmp:
        calls: list[int] = []

        def same(*_a):
            calls.append(1)
            return _batch(0)

        stats, logs, _p = _run(Path(tmp), same)
        assert len(calls) == 2, calls
        assert stats["more_pending"] == 0, stats

    # Tanda sin nada confirmado en la nube (nack de reintento): se corta.
    with tempfile.TemporaryDirectory() as tmp:
        calls = []

        def fresh(*_a):
            calls.append(1)
            return _batch(len(calls) * 100)

        with patch("src.ledger_bridge.ack_ids", side_effect=RuntimeError("ack caido")):
            logs: list[str] = []
            with (
                patch("src.ledger_bridge.is_configured", return_value=True),
                patch("src.ledger_bridge.sage_ui_running", return_value=True),
                patch("src.ledger_bridge.fetch_pending", side_effect=fresh),
            ):
                stats = process_ledger_pending(Path(tmp), {}, logs.append)
        assert len(calls) == 1, calls
        assert len(list_inbox_jobs(Path(tmp))) == 0

    # Cola enorme: tope de tandas y el automatico vuelve en 2 minutos.
    with tempfile.TemporaryDirectory() as tmp:
        calls = []

        def endless(*_a):
            calls.append(1)
            return _batch(len(calls) * 100)

        stats, logs, _p = _run(Path(tmp), endless)
        assert len(calls) == MAX_PULLS_PER_CYCLE, len(calls)
        assert stats["more_pending"] == 1 and stats["cloud_empty"] == 0, stats
        assert next_poll(0, stats)[1:] == (FOLLOW_UP_MS, "more")
        assert next_poll(0, dict(stats, failed=2))[1:] == (FOLLOW_UP_MS, "more")
        assert next_poll(0, dict(stats, blocked=1))[1:] == (POLL_INTERVAL_MS, "error")

    ev = classify("Tanda 2: 25 en cola...")
    assert ev == ("status", "Tanda 2: 25 en cola..."), ev
    ev = classify("Cola vacia: todo cargado (3 tanda(s), 60 cargadas)")
    assert ev and ev[0] == "status", ev
    assert next_poll(0, {"cloud_empty": 1})[1:] == (POLL_INTERVAL_MS, "empty")

    print("test_drain_queue ok")


if __name__ == "__main__":
    main()
