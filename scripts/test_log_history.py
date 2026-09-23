"""Regression: full history, migration, and retry queue counts without Sage."""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.ui_log_state import load, save
from src.sage_retry import failed_count, pending_cards, remove_failed


def main():
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        cards = [{"ok": i % 3 == 0, "ref": f"INV-{i}", "detail": "test"} for i in range(130)]
        save(root, ok=44, err=86, skip=0, cards=cards)
        assert load(root)["cards"] == cards
        logs = root / "logs"
        logs.mkdir()
        (logs / "autohub-2026-09-17.txt").write_text("\n".join(
            "12:00:00  [card]  [CARD] " + json.dumps(c) for c in cards[:60]), encoding="utf-8")
        (logs / "autohub-2026-09-18.txt").write_text("\n".join(
            "12:01:00  [card]  [CARD] " + json.dumps(c) for c in cards[60:]), encoding="utf-8")
        (root / "state/ui_logs.json").write_text(json.dumps({"version": 1, "cards": cards[-24:]}))
        assert load(root)["cards"] == cards, "restore old truncated history from logs"
        assert load(root)["cards"] == cards, "migration must not duplicate on next launch"
        save(root, ok=0, err=0, skip=0, cards=[])
        assert load(root)["cards"] == [], "explicit clear must remain cleared"
        queue = {f"INV-{i}": {"key": f"INV-{i}", "rows": [], "error": "missing"} for i in range(35)}
        (root / "state/sage_failed.json").write_text(json.dumps({"invoices": queue}))
        assert len(pending_cards(root)) == failed_count(root) == 35
        remove_failed(root, "INV-0")
        assert len(pending_cards(root)) == failed_count(root) == 34
        assert not load(root)["cards"], "retry queue must not depend on visible log clearing"
    print("OK: 130 cards, migration, restart, clear, 35 retry cards and removal counts.")

if __name__ == "__main__":
    main()
