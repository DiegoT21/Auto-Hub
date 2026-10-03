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
