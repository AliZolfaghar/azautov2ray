"""Load and save application configuration."""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

import yaml

from azautov2ray import CONFIG_PATH, ETC_DIR

# Always offered during setup; users can disable or add more
BUILTIN_SUBSCRIPTIONS: list[str] = [
    "https://raw.githubusercontent.com/barry-far/V2ray-config/main/All_Configs_base64_Sub.txt",
]

DEFAULT_CONFIG: dict[str, Any] = {
    "server": {
        "domain": "",
        "public_ip": "",
        "reality_port": 443,
        "reality_dest": "www.microsoft.com:443",
        "reality_server_names": ["www.microsoft.com"],
    },
    "subscriptions": list(BUILTIN_SUBSCRIPTIONS),
    "testing": {
        "ping_timeout_ms": 1500,
        "real_delay_url": "https://www.google.com/generate_204",
        "real_delay_max_ms": 2000,
        "speed_url": "https://speed.cloudflare.com/__down?bytes=10000000",
        "speed_timeout_s": 15,
        "max_candidates_for_speed": 10,
        "concurrency": 20,
        # Only test/use subscription nodes on these ports (others discarded)
        "only_ports": [443],
        # Only Reality configs (security=reality + pbk)
        "only_reality": True,
    },
    "observer": {
        "interval_s": 60,
        "fail_threshold": 3,
        "rescan_on_fail": True,
    },
    "generated": {
        "uuid": "",
        "reality_private_key": "",
        "reality_public_key": "",
        "short_id": "",
    },
}


def is_installed(config_path: str = CONFIG_PATH) -> bool:
    path = Path(config_path)
    if not path.is_file():
        return False
    try:
        cfg = load_config(config_path)
    except Exception:
        return False
    gen = cfg.get("generated") or {}
    return bool(gen.get("uuid") and gen.get("reality_private_key"))


def deep_merge(base: dict, overlay: dict) -> dict:
    result = copy.deepcopy(base)
    for key, value in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def load_config(config_path: str = CONFIG_PATH) -> dict[str, Any]:
    path = Path(config_path)
    if not path.is_file():
        return copy.deepcopy(DEFAULT_CONFIG)
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    return deep_merge(DEFAULT_CONFIG, raw)


def save_config(cfg: dict[str, Any], config_path: str = CONFIG_PATH) -> None:
    path = Path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(cfg, fh, default_flow_style=False, allow_unicode=True, sort_keys=False)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def ensure_etc_dirs() -> None:
    Path(ETC_DIR).mkdir(parents=True, exist_ok=True)
    Path(ETC_DIR, "logs").mkdir(parents=True, exist_ok=True)
