"""Interactive first-time install / reinstall wizard."""

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
from azautov2ray.config import (
    BUILTIN_SUBSCRIPTIONS,
    DEFAULT_CONFIG,
    ensure_etc_dirs,
    load_config,
    save_config,
)
from azautov2ray.prompt import ask, ask_int, ask_multiline, ask_yes_no
from azautov2ray.reality import (
    build_vless_link,
    generate_reality_keys,
    generate_short_id,
    generate_uuid,
    print_qr,
)
from azautov2ray.service import has_systemd, install_units, start_services, stop_services
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


def _collect_answers(existing: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Ask install questions. Prefills from existing config when reinstalling."""
    existing = existing or {}
    server = existing.get("server") or {}
    obs = existing.get("observer") or {}
    old_subs = list(existing.get("subscriptions") or [])

    print("  Domain is optional. If empty, the public IP is used in the client link.")
    domain = ask("Domain (optional)", default=str(server.get("domain") or ""))
    detected_ip = detect_public_ip()
    public_ip = ask(
        "Public IP",
        str(server.get("public_ip") or detected_ip or ""),
    )
    if not public_ip and not domain:
        print("  Need at least a public IP (or a domain). Aborting.")
        return None

    reality_port = ask_int("Reality listen port", int(server.get("reality_port") or 443))
    dest = ask(
        "Reality dest (host:port)",
        str(server.get("reality_dest") or "www.microsoft.com:443"),
    )
    sni = dest.split(":")[0]

    print()
    print("Built-in subscription(s):")
    for u in BUILTIN_SUBSCRIPTIONS:
        print(f"  - {u}")
    include_builtin = ask_yes_no("Include built-in subscription(s)?", True)

    if old_subs:
        print("Current subscription URL(s):")
        for u in old_subs:
            print(f"  - {u}")
        if ask_yes_no("Keep these subscription URLs?", True):
            extra = old_subs
        else:
            extra = ask_multiline("Additional / replacement subscription URL(s) (optional)")
    else:
        extra = ask_multiline("Additional subscription URL(s) (optional, Enter on empty to skip)")

    subs: list[str] = []
    seen: set[str] = set()
    if include_builtin:
        for u in BUILTIN_SUBSCRIPTIONS:
            if u not in seen:
                seen.add(u)
                subs.append(u)
    for u in extra:
        u = (u or "").strip()
        if u and u not in seen:
            seen.add(u)
            subs.append(u)
    if not subs:
        print("  At least one subscription URL is required.")
        return None

    interval = ask_int("Observer interval (seconds)", int(obs.get("interval_s") or 60))
    fail_threshold = ask_int(
        "Fail threshold before switch",
        int(obs.get("fail_threshold") or 3),
    )
    open_fw = ask_yes_no("Open / ensure firewall port?", True)

    return {
        "domain": domain,
        "public_ip": public_ip,
        "reality_port": reality_port,
        "dest": dest,
        "sni": sni,
        "subs": subs,
        "interval": interval,
        "fail_threshold": fail_threshold,
        "open_fw": open_fw,
    }


def run_wizard(repo_root: str, *, reinstall: bool = False) -> None:
    existing = load_config() if reinstall else None
    title = "reinstall / reconfigure" if reinstall else "first-time setup"

    print()
    print("=" * 60)
    print(f"  azautov2ray — {title}")
    print("=" * 60)
    print()
    if reinstall:
        print("  Keeps downloaded Xray binary and Python venv when already present.")
        print("  You can keep or regenerate Reality keys (QR / client link).")
        print()

    answers = _collect_answers(existing)
    if not answers:
        return

    keep_keys = False
    old_gen = (existing or {}).get("generated") or {}
    if reinstall and old_gen.get("uuid") and old_gen.get("reality_private_key"):
        keep_keys = ask_yes_no(
            "Keep existing Reality keys? (same QR/link for clients)",
            True,
        )

    if reinstall:
        print()
        print("--- Stopping services briefly ---")
        try:
            stop_services()
        except Exception as exc:
            print(f"  (stop warning: {exc})")

    print()
    print("--- Preparing dependencies (reuse if already present) ---")
    ensure_python_packages_system()
    ensure_etc_dirs()
    req_file = Path(repo_root) / "requirements.txt"
    create_venv(requirements_file=str(req_file) if req_file.is_file() else None)
    install_package_editable(repo_root)
    download_xray(XRAY_BIN)  # skips download if binary already exists

    print()
    print("--- Reality credentials ---")
    if keep_keys:
        uid = old_gen["uuid"]
        private_key = old_gen["reality_private_key"]
        public_key = old_gen["reality_public_key"]
        short_id = old_gen["short_id"]
        print("  Keeping existing UUID / keys / shortId")
    else:
        private_key, public_key = generate_reality_keys(XRAY_BIN)
        uid = generate_uuid()
        short_id = generate_short_id(8)
        print(f"  UUID: {uid}")
        print(f"  ShortId: {short_id}")
        print(f"  Public key: {public_key}")

    # Preserve testing section from previous install when reinstalling
    testing = dict(DEFAULT_CONFIG["testing"])
    if existing and existing.get("testing"):
        testing.update(existing["testing"])

    cfg: dict[str, Any] = {
        "server": {
            "domain": answers["domain"],
            "public_ip": answers["public_ip"],
            "reality_port": answers["reality_port"],
            "reality_dest": answers["dest"],
            "reality_server_names": [answers["sni"]],
        },
        "subscriptions": answers["subs"],
        "testing": testing,
        "observer": {
            "interval_s": answers["interval"],
            "fail_threshold": answers["fail_threshold"],
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

    if answers["open_fw"]:
        open_firewall_port(answers["reality_port"])

    print()
    print("--- Fetching & testing subscription nodes ---")
    uris = fetch_all(answers["subs"])
    only_ports = set(int(p) for p in (cfg.get("testing") or {}).get("only_ports") or [443])
    nodes = parse_uris(uris, only_ports=only_ports)
    print(f"  Nodes to test (port {sorted(only_ports)}): {len(nodes)}")
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
            "status": "reinstalled" if reinstall else "installed",
            "last_delay_ms": (selected or {}).get("delay_ms"),
            "last_speed_mbps": (selected or {}).get("speed_mbps"),
            "last_error": "",
        }
    )

    write_xray_json(build_server_config(cfg, selected))

    print()
    print("--- Installing / refreshing systemd services ---")
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
    print("  Setup complete. Scan QR or copy the VLESS link:")
    print("=" * 60)
    print_qr(link)
    print()
    if keep_keys:
        print("  Reality keys kept — clients do not need to re-scan if host/port unchanged.")
    print("  Config: /etc/azautov2ray/config.yaml")
    print("  Re-run this script anytime for the management menu.")
