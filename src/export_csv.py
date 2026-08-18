from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


def export_csv(frame: pd.DataFrame, config: dict[str, Any], root: Path) -> Path:
    output_dir = root / config["output"]["output_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"sage_export_{timestamp}.csv"

    frame.to_csv(
        output_path,
        index=False,
        sep=config["output"].get("delimiter", ","),
        encoding=config["output"].get("encoding", "utf-8-sig"),
    )
    return output_path


def export_rejected(rejected: list[dict[str, Any]], config: dict[str, Any], root: Path) -> Path | None:
    if not rejected:
        return None

    output_dir = root / config["output"]["output_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"rejected_{timestamp}.csv"

    pd.DataFrame(rejected).to_csv(output_path, index=False, encoding="utf-8-sig")
    return output_path
