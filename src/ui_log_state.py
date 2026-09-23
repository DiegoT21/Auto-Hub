"""Persistencia de las tarjetas y contadores visibles del panel."""
from __future__ import annotations

import json
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

STATE_NAME = "ui_logs.json"


def _empty() -> dict[str, Any]:
    return {"ok": 0, "err": 0, "skip": 0, "cards": []}


def state_path(root: Path) -> Path:
    return root / "state" / STATE_NAME


def _as_count(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def load(root: Path) -> dict[str, Any]:
    path = state_path(root)
    if not path.exists():
        migrated = _load_latest_text_log(root)
        if migrated["cards"] or migrated["skip"]:
            save(
                root,
                ok=migrated["ok"],
                err=migrated["err"],
                skip=migrated["skip"],
                cards=migrated["cards"],
            )
        return migrated
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return _empty()
    if not isinstance(data, dict):
        return _empty()
    cards = data.get("cards")
    if not isinstance(cards, list):
        cards = []
    cards = [card for card in cards if isinstance(card, dict)]
    if data.get("version") != 2:
        # Recover cards discarded by the old 24-card cap from existing logs.
        recovered = _load_latest_text_log(root)["cards"]
        remaining = Counter(json.dumps(c, sort_keys=True) for c in recovered)
        merged = list(recovered)
        for card in cards:
            key = json.dumps(card, sort_keys=True)
            if remaining[key]:
                remaining[key] -= 1
            else:
                merged.append(card)
        cards = merged
        save(root, ok=data.get("ok", 0), err=data.get("err", 0),
             skip=data.get("skip", 0), cards=cards)
    return {
        "ok": _as_count(data.get("ok")),
        "err": _as_count(data.get("err")),
        "skip": _as_count(data.get("skip")),
        "cards": cards,
    }


def _load_latest_text_log(root: Path) -> dict[str, Any]:
    """Recupera las tarjetas de los logs disponibles al migrar el historial."""
    folder = root / "logs"
    paths = sorted(folder.glob("autohub-*.txt")) if folder.is_dir() else []
    if not paths:
        return _empty()
    try:
        lines = []
        for path in paths:
            lines.extend(path.read_text(encoding="utf-8", errors="replace").splitlines())
    except OSError:
        return _empty()

    cards: list[dict[str, Any]] = []
    card_times: list[str] = []
    skip = 0
    for line in lines:
        if "  [card]  " in line:
            raw = line.split("  [card]  ", 1)[1].strip()
            if raw.lower().startswith("[card]"):
                raw = raw.split("]", 1)[-1].strip()
            try:
                card = json.loads(raw)
            except (ValueError, TypeError):
                continue
            if not isinstance(card, dict):
                continue
            # Versiones anteriores podían registrar dos veces el mismo output
            # (stdout y transcript de PowerShell).
            event_time = line[:8]
            if cards and cards[-1] == card and card_times[-1] == event_time:
                continue
            cards.append(card)
            card_times.append(event_time)
        elif "  [skip]  " in line:
            shown = line.split("  [skip]  ", 1)[1]
            amount = 1
            for word in shown.split():
                if word.isdigit():
                    amount = int(word)
                    break
            skip += amount

    return {
        "ok": sum(1 for card in cards if bool(card.get("ok"))),
        "err": sum(1 for card in cards if not bool(card.get("ok"))),
        "skip": skip,
        "cards": cards,
    }


def save(
    root: Path,
    *,
    ok: int,
    err: int,
    skip: int,
    cards: Iterable[dict[str, Any]],
) -> Path:
    path = state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 2,
        "ok": _as_count(ok),
        "err": _as_count(err),
        "skip": _as_count(skip),
        "cards": [card for card in cards if isinstance(card, dict)],
    }
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.replace(tmp_name, path)
    finally:
        try:
            Path(tmp_name).unlink(missing_ok=True)
        except OSError:
            pass
    return path
