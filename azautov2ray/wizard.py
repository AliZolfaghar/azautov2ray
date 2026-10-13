"""Interactive first-time install wizard."""

from __future__ import annotations

import socket
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from azautov2ray import OPT_DIR, XRAY_BIN
from azautov2ray.bootstrap import (
    create_venv,
    download_xray,
    ensure_python_packages_system,
    install_cli_wrapper,
    install_package_editable,
    open_firewall_port,
)
from azautov2ray.config import DEFAULT_CONFIG, ensure_etc_dirs, save_config
from azautov2ray.prompt import ask, ask_int, ask_multiline, ask_yes_no
from azautov2ray.reality import (
    build_vless_link,
    generate_reality_keys,
    generate_short_id,
    generate_uuid,
    print_qr,
)
from azautov2ray.service import has_systemd, install_units, start_services
from azautov2ray.state import save_state
from azautov2ray.sub_fetcher import fetch_all, parse_uris
from azautov2ray.tester import dump_ranked, node_summary, run_full_pipeline
from azautov2ray.xray_gen import build_server_config, write_xray_json


def detect_public_ip() -> str:
    for url in (
        "https://api.ipify.org",
        "https://ifconfig.me/ip",
        "https://icanhazip.com",
    ):
        try:
            with urlopen(url, timeout=5) as resp:
                ip = resp.read().decode("utf-8").strip()
                if ip:
                    return ip
        except Exception:
            continue
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return ""


def run_wizard(repo_root: str) -> None:
    print()
    print("=" * 60)
    print("  azautov2ray — first-time setup")
    print("=" * 60)
    print()

    print("  Domain is optional. If empty, the public IP is used in the client link.")
    domain = ask("Domain (optional)", default="")
    detected_ip = detect_public_ip()
    public_ip = ask("Public IP", detected_ip or "")
    if not public_ip and not domain:
        print("  Need at least a public IP (or a domain). Aborting.")
        return
    if not public_ip and domain:
        # domain-only is fine for the share link; still store empty IP
        pass
    reality_port = ask_int("Reality listen port", 443)
    dest = ask("Reality dest (host:port)", "www.microsoft.com:443")
    sni = dest.split(":")[0]
    subs = ask_multiline("Subscription URL(s)")
    if not subs:
        print("  At least one subscription URL is required.")
        return
    interval = ask_int("Observer interval (seconds)", 60)
    fail_threshold = ask_int("Fail threshold before switch", 3)
    open_fw = ask_yes_no("Open firewall port automatically?", True)

    print()
    print("--- Installing dependencies ---")
    ensure_python_packages_system()
    ensure_etc_dirs()
    req_file = Path(repo_root) / "requirements.txt"
    create_venv(requirements_file=str(req_file) if req_file.is_file() else None)
    install_package_editable(repo_root)
    download_xray(XRAY_BIN)

    print()
    print("--- Generating Reality credentials ---")
    private_key, public_key = generate_reality_keys(XRAY_BIN)
    uid = generate_uuid()
    short_id = generate_short_id(8)
    print(f"  UUID: {uid}")
    print(f"  ShortId: {short_id}")
    print(f"  Public key: {public_key}")

    cfg: dict[str, Any] = {
        "server": {
            "domain": domain,
            "public_ip": public_ip,
            "reality_port": reality_port,
            "reality_dest": dest,
            "reality_server_names": [sni],
        },
        "subscriptions": subs,
        "testing": dict(DEFAULT_CONFIG["testing"]),
        "observer": {
            "interval_s": interval,
            "fail_threshold": fail_threshold,
            "rescan_on_fail": True,
        },
        "generated": {
            "uuid": uid,
            "reality_private_key": private_key,
            "reality_public_key": public_key,
            "short_id": short_id,
        },
    }
    save_config(cfg)

    if open_fw:
        open_firewall_port(reality_port)

    print()
    print("--- Fetching & testing subscription nodes ---")
    uris = fetch_all(subs)
    nodes = parse_uris(uris)
    print(f"  Parsed {len(nodes)} nodes")
    ranked = run_full_pipeline(cfg, nodes, xray_bin=XRAY_BIN)
    selected = ranked[0] if ranked else None
    if not selected:
        print("  WARNING: no healthy nodes found. Reality inbound will start with direct placeholder.")
        print("  Use menu option 'Retest' after fixing subscriptions.")
    else:
        print(
            f"  Best node: {selected.get('name')}  "
            f"delay={selected.get('delay_ms')}ms  speed={selected.get('speed_mbps')}Mbps"
        )

    save_state(
        {
            "selected": node_summary(selected),
            "ranked": dump_ranked(ranked),
            "fails": 0,
            "status": "installed",
            "last_delay_ms": (selected or {}).get("delay_ms"),
            "last_speed_mbps": (selected or {}).get("speed_mbps"),
        }
    )

    xray_cfg = build_server_config(cfg, selected)
    write_xray_json(xray_cfg)

    print()
    print("--- Installing systemd services ---")
    if has_systemd():
        install_units(str(Path(repo_root) / "systemd"))
        start_services()
    else:
        print("  systemd not detected — start manually:")
        print(f"    {XRAY_BIN} run -c /etc/azautov2ray/xray.json")
        print(f"    {OPT_DIR}/venv/bin/python -m azautov2ray.observer")

    install_cli_wrapper()

    link = build_vless_link(cfg)
    print()
    print("=" * 60)
    print("  Install complete. Scan QR or copy the VLESS link:")
    print("=" * 60)
    print_qr(link)
    print()
    print("  Config: /etc/azautov2ray/config.yaml")
    print("  Re-run this script anytime for the management menu.")
