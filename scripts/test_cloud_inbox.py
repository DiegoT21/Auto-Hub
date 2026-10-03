"""Cloud inbox: pull writes files; process clears skip/pre-block without Sage."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.user_log import classify
from src.ledger_bridge import (
    cloud_inbox_dir,
    list_inbox_jobs,
    process_inbox_to_sage,
    pull_pending_to_inbox,
    save_jobs_to_inbox,
)


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


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        jobs = [_tmp_job("000002:001:FAC:TMP00" + str(i)) for i in range(1, 4)]
        raw = json.dumps({"invoices": [], "count": 3})

        logs: list[str] = []

        def on_log(msg: str) -> None:
            logs.append(msg)

        with patch("src.ledger_bridge.fetch_pending", return_value=(jobs, raw)):
            n_saved, stats = pull_pending_to_inbox(root, {}, on_log)

        assert n_saved == 3, n_saved
        assert stats.get("cloud_empty") == 0
        inbox_files = list(cloud_inbox_dir(root).glob("*.json"))
        assert len(inbox_files) == 3, inbox_files
        assert any("lote(s) pendientes" in m for m in logs), logs
        assert len(list_inbox_jobs(root)) == 3

        progress: list[tuple[int, int, str]] = []
        sage_calls: list[object] = []

        def on_progress(k: int, n: int, label: str) -> None:
            progress.append((k, n, label))

        with (
            patch("src.ledger_bridge.run_test_company_write", side_effect=lambda *a, **k: sage_calls.append(1)),
            patch("src.ledger_bridge.ack_ids", return_value={"sent": 3, "confirmed": 3, "received": 3, "alreadyConsumed": 0}),
        ):
            out = process_inbox_to_sage(root, {}, on_log, on_progress=on_progress)

        assert sage_calls == [], "skip/pre-block must not open Sage"
        assert out["skipped"] == 3, out
        assert out["sent"] == 0
        assert list_inbox_jobs(root) == []
        done = list((cloud_inbox_dir(root) / "done").glob("*.json"))
        assert len(done) == 3, done
        assert progress and progress[-1][0] == progress[-1][1] == 3

        # save_jobs_to_inbox helper
        n = save_jobs_to_inbox(root, [_tmp_job("FAC:TMP0099")])
        assert n == 1 and len(list_inbox_jobs(root)) == 1

    ev = classify("Cargando Sage 2/5 · *0008193")
    assert ev and ev[0] == "progress" and "2/5" in ev[1], ev
    ev2 = classify("Cola nube: 12")
    assert ev2 and ev2[0] == "status" and "12" in ev2[1], ev2
    ev3 = classify("Ledger Bridge: 7 lote(s) pendientes")
    assert ev3 and "7" in ev3[1] and "cola" in ev3[1].lower(), ev3

    print("test_cloud_inbox ok")


if __name__ == "__main__":
    main()
