"""Separate retry work from historical attempts without changing the queue."""
import re


def invoice_identity(card):
    ref = str(card.get("ref") or "").strip().upper()
    date = str(card.get("date") or "")[:10]
    sage = re.fullmatch(r"AH\d{6}-([CRA])-(\d+)", ref)
    source = re.fullmatch(r"([C*]?)(\d+)", ref)
    if sage:
        branch, number = sage.groups()
        return (branch, int(number), date)
    if source:
        prefix, number = source.groups()
        return ({"C": "C", "*": "R", "": "A"}[prefix], int(number), date)
    return (ref, date)


def failure_groups(history, pending):
    # One current state per invoice, not one pending task per failed attempt.
    latest = {}
    attempts = []
    for card in history:
        key = invoice_identity(card)
        latest.pop(key, None)
        latest[key] = card
        if not card.get("ok"):
            attempts.append(card)
    queued = {invoice_identity(card) for card in pending}
    blocked = [card for key, card in latest.items() if not card.get("ok") and key not in queued]
    return [("Para reenviar", pending),
            ("Requieren revision; no estan en la cola de reenvio", blocked),
            ("Historial de intentos fallidos", attempts)]
