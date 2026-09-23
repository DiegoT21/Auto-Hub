"""Intervalos de Automatico: barato en cola vacia, rapido si hay trabajo o fallo sin ACK."""
from __future__ import annotations

from typing import Any

# Cola vacia: 20s → 45s → 90s → 3 min → 5 min (cap). Menos GET /v1/pending.
EMPTY_BACKOFF_MS = (20_000, 45_000, 90_000, 180_000, 300_000)
# Sage/AWS fallo: reintentar pronto (la factura sigue en pending, no hubo ACK).
ERROR_BACKOFF_MS = (20_000, 45_000, 90_000)
# Hubo carga u omitidas: vaciar el resto de la cola.
WORK_DELAY_MS = 10_000


def format_wait(delay_ms: int) -> str:
    sec = max(1, int(round(delay_ms / 1000)))
    if sec < 60:
        return str(sec) + " s"
    minutes, rest = divmod(sec, 60)
    if rest == 0:
        return str(minutes) + " min"
    return str(minutes) + " min " + str(rest) + " s"


def next_poll(
    idle_idx: int,
    stats: dict[str, Any] | None,
    error: str = "",
) -> tuple[int, int, str]:
    """Devuelve (nuevo_idx, delay_ms, motivo) con motivo work|empty|error."""
    stats = stats or {}
    failed = int(stats.get("failed") or 0)
    blocked = int(stats.get("blocked") or 0)
    sent = int(stats.get("sent") or 0)
    skipped = int(stats.get("skipped") or 0)

    if error or failed or blocked:
        idx = min(max(idle_idx, 0), len(ERROR_BACKOFF_MS) - 1)
        delay = ERROR_BACKOFF_MS[idx]
        return min(idle_idx + 1, len(ERROR_BACKOFF_MS) - 1), delay, "error"
    if sent or skipped:
        return 0, WORK_DELAY_MS, "work"
    idx = min(max(idle_idx, 0), len(EMPTY_BACKOFF_MS) - 1)
    delay = EMPTY_BACKOFF_MS[idx]
    return min(idle_idx + 1, len(EMPTY_BACKOFF_MS) - 1), delay, "empty"
