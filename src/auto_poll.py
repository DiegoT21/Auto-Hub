"""Automatico consulta la cola cada 6 horas; Consultar ahora fuerza un ciclo."""
from __future__ import annotations

from typing import Any

POLL_INTERVAL_MS = 6 * 60 * 60 * 1000


def format_wait(delay_ms: int) -> str:
    sec = max(1, int(round(delay_ms / 1000)))
    if sec < 60:
        return str(sec) + " s"
    minutes, rest = divmod(sec, 60)
    if minutes < 60:
        if rest == 0:
            return str(minutes) + " min"
        return str(minutes) + " min " + str(rest) + " s"
    hours, minutes = divmod(minutes, 60)
    if minutes == 0 and rest == 0:
        return str(hours) + " h"
    if rest == 0:
        return str(hours) + " h " + str(minutes) + " min"
    return str(hours) + " h " + str(minutes) + " min"


def next_poll(
    idle_idx: int,
    stats: dict[str, Any] | None,
    error: str = "",
) -> tuple[int, int, str]:
    """Devuelve (nuevo_idx, delay_ms, motivo) con motivo work|empty|error."""
    del idle_idx
    stats = stats or {}
    failed = int(stats.get("failed") or 0)
    blocked = int(stats.get("blocked") or 0)
    sent = int(stats.get("sent") or 0)
    skipped = int(stats.get("skipped") or 0)

    if error or failed or blocked:
        return 0, POLL_INTERVAL_MS, "error"
    if sent or skipped:
        return 0, POLL_INTERVAL_MS, "work"
    return 0, POLL_INTERVAL_MS, "empty"
