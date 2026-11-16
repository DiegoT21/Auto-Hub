"""Separate retry work from historical attempts without changing the queue."""
import json
import re
from pathlib import Path


def _doc_key(ref):
    ref = str(ref or "").strip().upper().lstrip("#")
    if ":" in ref:
        ref = ref.rsplit(":", 1)[-1]
    sage = re.fullmatch(r"AH\d{6}-([CRA])-(\d+)", ref)
    if sage:
        return (sage.group(1), int(sage.group(2)))
    source = re.fullmatch(r"([C*]?)(\d+)", ref)
    if source:
        prefix, number = source.groups()
        return ({"C": "C", "*": "R", "": "A"}[prefix], int(number))
    return None


def invoice_identity(card):
    ref = str(card.get("ref") or "").strip().upper()
    date = str(card.get("date") or "")[:10]
    key = _doc_key(ref)
    if key:
        return (*key, date)
    return (ref, date)


def sent_documents(root: Path) -> set:
    """(sucursal, numero) de todo lo que sage_sent.json ya registra como cargado."""
    path = Path(root) / "state" / "sage_sent.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    keys = set()
    for entry in (data.get("by_factura_id") or {}).values():
        if not isinstance(entry, dict):
            continue
        for ref in (entry.get("factura_id"), entry.get("sage_ref")):
            key = _doc_key(ref)
            if key:
                keys.add(key)
    return keys


def already_in_sage(card, sent: set) -> bool:
    key = _doc_key(card.get("ref"))
    return bool(key) and key in sent
