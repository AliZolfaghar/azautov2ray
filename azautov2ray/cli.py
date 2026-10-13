"""Management menu and CLI entrypoint."""

from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

from azautov2ray import ETC_DIR, OPT_DIR
from azautov2ray.bootstrap import close_firewall_port, remove_cli_wrapper
from azautov2ray.config import is_installed, load_config, save_config
from azautov2ray.prompt import ask, ask_yes_no, pause, read_line
from azautov2ray.reality import build_vless_link, print_qr
from azautov2ray.service import (
    restart_services,
    service_status_lines,
    stop_services,
    uninstall_units,
)
from azautov2ray.state import load_state, save_state
from azautov2ray.sub_fetcher import fetch_all, parse_uris
from azautov2ray.tester import dump_ranked, node_summary, run_full_pipeline
from azautov2ray.wizard import run_wizard
from azautov2ray.xray_gen import build_server_config, write_xray_json


def _pause() -> None:
    pause()


def show_status() -> None:
    cfg = load_config()
    state = load_state()
    print()
    print("--- Status ---")
    for line in service_status_lines():
        print(f"  {line}")
    server = cfg.get("server") or {}
    print(f"  Domain: {server.get('domain') or '(none — using IP)'}")
    print(f"  Public IP: {server.get('public_ip') or '(none)'}")
    print(f"  Reality port: {server.get('reality_port')}")
    selected = state.get("selected") or {}
    print(f"  Status: {state.get('status')}")
    print(f"  Fails: {state.get('fails')}")
    print(f"  Selected: {selected.get('name') or '(none)'}")
    if selected:
        print(f"    {selected.get('protocol')} {selected.get('address')}:{selected.get('port')}")
    if state.get("last_delay_ms") is not None:
        print(f"  Last delay: {state.get('last_delay_ms')} ms")
    if state.get("last_speed_mbps") is not None:
        print(f"  Last speed: {state.get('last_speed_mbps')} Mbps")
    if state.get("last_error"):
        print(f"  Last error: {state.get('last_error')}")
    updated = state.get("updated_at") or 0
    if updated:
        print(f"  State updated: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(updated))}")
    ranked = state.get("ranked") or []
    print(f"  Ranked candidates: {len(ranked)}")


def show_qr() -> None:
    cfg = load_config()
    link = build_vless_link(cfg)
    print()
    print("--- Reality VLESS link / QR ---")
    print_qr(link)


def retest_and_apply() -> None:
    from azautov2ray import XRAY_BIN

    cfg = load_config()
    print()
    print("--- Retest subscriptions ---")
    uris = fetch_all(cfg.get("subscriptions") or [])
    nodes = parse_uris(uris)
    print(f"  Parsed {len(nodes)} nodes")
    ranked = run_full_pipeline(cfg, nodes, xray_bin=XRAY_BIN)
    if not ranked:
        print("  No healthy nodes found. Keeping current selection.")
        return
    selected = ranked[0]
    save_state(
        {
            **load_state(),
            "selected": node_summary(selected),
            "ranked": dump_ranked(ranked),
            "fails": 0,
            "status": "retested",
            "last_delay_ms": selected.get("delay_ms"),
            "last_speed_mbps": selected.get("speed_mbps"),
            "last_error": "",
        }
    )
    write_xray_json(build_server_config(cfg, selected))
    restart_services()
    print(f"  Applied: {selected.get('name')}  "
          f"delay={selected.get('delay_ms')}ms  speed={selected.get('speed_mbps')}Mbps")


def edit_settings() -> None:
    cfg = load_config()
    print()
    print("--- Edit settings (Enter keeps current) ---")
    server = cfg.setdefault("server", {})
    obs = cfg.setdefault("observer", {})

    server["domain"] = ask("  Domain", str(server.get("domain") or ""))
    server["public_ip"] = ask("  Public IP", str(server.get("public_ip") or ""))
    port_s = ask("  Reality port", str(server.get("reality_port") or 443))
    try:
        server["reality_port"] = int(port_s)
    except ValueError:
        print("  Invalid port — unchanged.")
    server["reality_dest"] = ask("  Reality dest", str(server.get("reality_dest") or ""))
    sni = server["reality_dest"].split(":")[0]
    server["reality_server_names"] = [sni]

    print("  Subscriptions (comma-separated):")
    current_subs = ",".join(cfg.get("subscriptions") or [])
    new_subs = ask("  URLs", current_subs)
    cfg["subscriptions"] = [s.strip() for s in new_subs.split(",") if s.strip()]

    interval_s = ask("  Observer interval_s", str(obs.get("interval_s") or 60))
    fail_s = ask("  Fail threshold", str(obs.get("fail_threshold") or 3))
    try:
        obs["interval_s"] = int(interval_s)
        obs["fail_threshold"] = int(fail_s)
    except ValueError:
        print("  Invalid observer numbers — partially unchanged.")

    save_config(cfg)
    # Rebuild xray with same selected node (credentials unchanged)
    state = load_state()
    write_xray_json(build_server_config(cfg, state.get("selected")))
    restart_services()
    print("  Settings saved and services restarted.")
    print("  Tip: Reality client link may change if domain/port changed — show QR again.")


def do_restart() -> None:
    restart_services()
    print("  Services restarted.")


def do_reinstall(repo_root: str) -> None:
    print()
    print("--- Reinstall ---")
    print("  Re-runs setup wizard without uninstall.")
    print("  Keeps Xray binary + Python venv if already downloaded.")
    if not ask_yes_no("Continue with reinstall?", True):
        print("  Cancelled.")
        return
    # Prefer source under OPT_DIR when menu runs from installed copy
    root = repo_root
    if Path(OPT_DIR, "azautov2ray").is_dir() and not Path(root, "azautov2ray").is_dir():
        root = OPT_DIR
    elif Path(OPT_DIR, "azautov2ray").is_dir():
        # Refresh package from current running source if available
        pass
    run_wizard(root, reinstall=True)


def do_uninstall() -> None:
    print()
    confirm = read_line("  Type UNINSTALL to remove azautov2ray completely: ").strip()
    if confirm != "UNINSTALL":
        print("  Cancelled.")
        return
    cfg = load_config() if is_installed() else {}
    port = int((cfg.get("server") or {}).get("reality_port") or 0)
    print("  Stopping services...")
    try:
        uninstall_units()
    except Exception as exc:
        print(f"  (systemd cleanup warning: {exc})")
        stop_services()
    if port and read_line(f"  Close firewall port {port}? [y/N]: ").strip().lower() in ("y", "yes"):
        close_firewall_port(port)
    remove_cli_wrapper()
    for path in (OPT_DIR, ETC_DIR):
        p = Path(path)
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)
            print(f"  Removed {path}")
    print("  Uninstall complete.")


def management_menu(repo_root: str) -> None:
    while True:
        print()
        print("=" * 50)
        print("  azautov2ray management")
        print("=" * 50)
        print("  1) Status")
        print("  2) Show Reality QR / link")
        print("  3) Retest subscriptions & apply best")
        print("  4) Edit settings")
        print("  5) Restart services")
        print("  6) Reinstall (keep downloads)")
        print("  7) Uninstall")
        print("  0) Exit")
        choice = read_line("  Select: ").strip()
        try:
            if choice == "1":
                show_status()
                _pause()
            elif choice == "2":
                show_qr()
                _pause()
            elif choice == "3":
                retest_and_apply()
                _pause()
            elif choice == "4":
                edit_settings()
                _pause()
            elif choice == "5":
                do_restart()
                _pause()
            elif choice == "6":
                do_reinstall(repo_root)
                _pause()
            elif choice == "7":
                do_uninstall()
                return
            elif choice == "0":
                return
            else:
                print("  Invalid choice.")
        except KeyboardInterrupt:
            print("\n  Interrupted.")
            return
        except Exception as exc:
            print(f"  Error: {exc}")
            _pause()


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    repo_root = str(Path(__file__).resolve().parent.parent)

    # Allow override when installed under /opt
    if Path(OPT_DIR, "azautov2ray").is_dir():
        # Prefer installed copy's parent as root for templates
        installed_root = OPT_DIR
    else:
        installed_root = repo_root

    if not is_installed():
        if argv and argv[0] in ("--help", "-h"):
            print("Usage: install.sh | python -m azautov2ray.cli")
            print("First run starts the install wizard.")
            return 0
        run_wizard(repo_root)
        return 0

    if argv:
        cmd = argv[0]
        if cmd == "status":
            show_status()
        elif cmd == "qr":
            show_qr()
        elif cmd == "retest":
            retest_and_apply()
        elif cmd == "restart":
            do_restart()
        elif cmd == "reinstall":
            do_reinstall(installed_root)
        elif cmd == "uninstall":
            do_uninstall()
        elif cmd == "menu":
            management_menu(installed_root)
        else:
            print(f"Unknown command: {cmd}")
            return 1
        return 0

    management_menu(installed_root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
