"""Runtime state persistence (selected node, rankings, health)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from azautov2ray import STATE_PATH


def default_state() -> dict[str, Any]:
    return {
        "updated_at": 0,
        "selected": None,
        "ranked": [],
        "fails": 0,
        "last_ok_at": 0,
        "last_delay_ms": None,
        "last_speed_mbps": None,
        "last_error": "",
        "status": "idle",
    }


def load_state(path: str = STATE_PATH) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        return default_state()
    try:
        with p.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        base = default_state()
        base.update(data)
        return base
    except (OSError, json.JSONDecodeError):
        return default_state()


def save_state(state: dict[str, Any], path: str = STATE_PATH) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    state = dict(state)
    state["updated_at"] = int(time.time())
    with p.open("w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)
