"""Punto de entrada de Auto-Hub (UI de servicio)."""
from __future__ import annotations

import sys
from pathlib import Path

if not getattr(sys, "frozen", False):
    _BOOTSTRAP = Path(__file__).resolve().parent.parent
    if str(_BOOTSTRAP) not in sys.path:
        sys.path.insert(0, str(_BOOTSTRAP))

from app.ops_app import main

if __name__ == "__main__":
    main()
