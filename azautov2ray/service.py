"""Manage systemd units for xray and observer."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from azautov2ray import OPT_DIR, VENV_DIR, XRAY_BIN, XRAY_JSON_PATH

XRAY_UNIT = "azautov2ray-xray.service"
OBSERVER_UNIT = "azautov2ray-observer.service"
UNIT_DIR = Path("/etc/systemd/system")


def _run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check, capture_output=True, text=True)


def xray_unit_content() -> str:
    return f"""[Unit]
Description=azautov2ray Xray Reality relay
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart={XRAY_BIN} run -c {XRAY_JSON_PATH}
Restart=on-failure
RestartSec=3
LimitNOFILE=1048576
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
"""


def observer_unit_content() -> str:
    python = f"{VENV_DIR}/bin/python"
    return f"""[Unit]
Description=azautov2ray observer (health + failover)
After=network-online.target {XRAY_UNIT}
Wants=network-online.target
Requires={XRAY_UNIT}

[Service]
Type=simple
WorkingDirectory={OPT_DIR}
ExecStart={python} -m azautov2ray.observer
Restart=on-failure
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
"""


def install_units(repo_systemd_dir: str | None = None) -> None:
    UNIT_DIR.mkdir(parents=True, exist_ok=True)
    # Prefer packaged templates if present; else generate
    templates = Path(repo_systemd_dir) if repo_systemd_dir else Path(OPT_DIR) / "systemd"
    xray_src = templates / XRAY_UNIT
    obs_src = templates / OBSERVER_UNIT

    xray_dest = UNIT_DIR / XRAY_UNIT
    obs_dest = UNIT_DIR / OBSERVER_UNIT

    if xray_src.is_file():
        text = xray_src.read_text(encoding="utf-8")
        text = (
            text.replace("@XRAY_BIN@", XRAY_BIN)
            .replace("@XRAY_JSON@", XRAY_JSON_PATH)
        )
        xray_dest.write_text(text, encoding="utf-8")
    else:
        xray_dest.write_text(xray_unit_content(), encoding="utf-8")

    if obs_src.is_file():
        text = obs_src.read_text(encoding="utf-8")
        text = (
            text.replace("@PYTHON@", f"{VENV_DIR}/bin/python")
            .replace("@OPT_DIR@", OPT_DIR)
            .replace("@XRAY_UNIT@", XRAY_UNIT)
        )
        obs_dest.write_text(text, encoding="utf-8")
    else:
        obs_dest.write_text(observer_unit_content(), encoding="utf-8")

    _run(["systemctl", "daemon-reload"])
    _run(["systemctl", "enable", XRAY_UNIT, OBSERVER_UNIT])
    print(f"  Installed systemd units: {XRAY_UNIT}, {OBSERVER_UNIT}")


def restart_xray() -> None:
    _run(["systemctl", "restart", XRAY_UNIT])
    print("  Xray restarted.")


def start_services() -> None:
    _run(["systemctl", "restart", XRAY_UNIT])
    _run(["systemctl", "restart", OBSERVER_UNIT])
    print("  Services started.")


def stop_services() -> None:
    _run(["systemctl", "stop", OBSERVER_UNIT], check=False)
    _run(["systemctl", "stop", XRAY_UNIT], check=False)


def restart_services() -> None:
    start_services()


def service_status_lines() -> list[str]:
    lines: list[str] = []
    for unit in (XRAY_UNIT, OBSERVER_UNIT):
        proc = _run(["systemctl", "is-active", unit], check=False)
        active = (proc.stdout or "").strip() or "unknown"
        lines.append(f"{unit}: {active}")
    return lines


def uninstall_units() -> None:
    stop_services()
    _run(["systemctl", "disable", XRAY_UNIT, OBSERVER_UNIT], check=False)
    for unit in (XRAY_UNIT, OBSERVER_UNIT):
        path = UNIT_DIR / unit
        if path.is_file():
            path.unlink()
    _run(["systemctl", "daemon-reload"], check=False)
    print("  Systemd units removed.")


def has_systemd() -> bool:
    return shutil.which("systemctl") is not None and Path("/run/systemd/system").exists()
