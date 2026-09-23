"""Pending invoices are not counts of historical failed attempts."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.failure_view import failure_groups

a = {"ref": "*0008142", "date": "2026-09-16", "ok": False}
success = {"ref": "AH160926-R-08142", "date": "2026-09-16", "ok": True}
pending = {"ref": "*0008089", "date": "2026-09-11", "ok": False}
blocked = {"ref": "*0008121", "date": "2026-09-15", "ok": False}
groups = failure_groups([a, a, pending, blocked, success], [pending])
assert groups[0][1] == [pending]
assert groups[1][1] == [blocked]
assert len(groups[2][1]) == 4
other_branch = dict(success, ref="AH160926-C-08142")
assert failure_groups([a, other_branch], [])[1][1] == [a]
assert failure_groups([a, success, a], [])[1][1] == [a]
print("OK: deduplicated current failures, resolved invoices, authoritative queue and full attempt history.")
