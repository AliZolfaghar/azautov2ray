"""Background health observer and automatic failover."""

from __future__ import annotations

import signal
import sys
import time
import traceback

from azautov2ray import XRAY_BIN
from azautov2ray.config import load_config
from azautov2ray.service import restart_xray
from azautov2ray.state import load_state, save_state
from azautov2ray.sub_fetcher import fetch_all, parse_uris
from azautov2ray.tester import measure_real_delay, node_summary, run_full_pipeline
from azautov2ray.xray_gen import build_server_config, write_xray_json

_running = True


def _handle_signal(signum, frame) -> None:  # noqa: ANN001, ARG001
    global _running
    _running = False
    print(f"[observer] received signal {signum}, shutting down...")


def apply_selected(cfg: dict, node: dict | None) -> None:
    xray_cfg = build_server_config(cfg, node)
    write_xray_json(xray_cfg)
    # Only restart xray — never restart this observer process via systemd
    restart_xray()


def rescan(cfg: dict) -> list[dict]:
    print("[observer] full rescan of subscriptions...")
    uris = fetch_all(cfg.get("subscriptions") or [])
    nodes = parse_uris(uris)
    print(f"[observer] parsed {len(nodes)} nodes")
    ranked = run_full_pipeline(cfg, nodes, xray_bin=XRAY_BIN)
    return ranked


def pick_next(ranked: list[dict], current: dict | None) -> dict | None:
    if not ranked:
        return None
    if not current:
        return ranked[0]
    cur_uri = current.get("uri")
    # Prefer next after current
    for i, node in enumerate(ranked):
        if node.get("uri") == cur_uri:
            if i + 1 < len(ranked):
                return ranked[i + 1]
            break
    # Otherwise first that is different
    for node in ranked:
        if node.get("uri") != cur_uri:
            return node
    return ranked[0]


def loop_once(cfg: dict) -> None:
    t = cfg.get("testing") or {}
    obs = cfg.get("observer") or {}
    state = load_state()
    selected = state.get("selected")
    ranked = state.get("ranked") or []

    if not selected:
        ranked = rescan(cfg)
        if not ranked:
            state["status"] = "no_nodes"
            state["last_error"] = "no healthy nodes found"
            save_state(state)
            print("[observer] no healthy nodes")
            return
        selected = ranked[0]
        state["ranked"] = [node_summary(n) for n in ranked]
        state["selected"] = node_summary(selected)
        state["fails"] = 0
        state["status"] = "switched"
        state["last_delay_ms"] = selected.get("delay_ms")
        state["last_speed_mbps"] = selected.get("speed_mbps")
        save_state(state)
        apply_selected(cfg, selected)
        print(f"[observer] selected: {selected.get('name')}")
        return

    delay = measure_real_delay(
        selected,
        url=t.get("real_delay_url") or "https://www.google.com/generate_204",
        max_ms=int(t.get("real_delay_max_ms", 2000)) * 2,  # slightly looser for live check
        xray_bin=XRAY_BIN,
    )
    if delay is not None:
        state["fails"] = 0
        state["last_ok_at"] = int(time.time())
        state["last_delay_ms"] = round(delay, 1)
        state["last_error"] = ""
        state["status"] = "ok"
        save_state(state)
        print(f"[observer] OK delay={state['last_delay_ms']}ms node={selected.get('name')}")
        return

    fails = int(state.get("fails") or 0) + 1
    state["fails"] = fails
    state["last_error"] = "real_delay_failed"
    state["status"] = "degraded"
    save_state(state)
    threshold = int(obs.get("fail_threshold", 3))
    print(f"[observer] FAIL {fails}/{threshold} node={selected.get('name')}")

    if fails < threshold:
        return

    # Failover
    next_node = pick_next(ranked, selected)
    if next_node is None or next_node.get("uri") == selected.get("uri"):
        if obs.get("rescan_on_fail", True):
            ranked = rescan(cfg)
            state["ranked"] = [node_summary(n) for n in ranked]
            next_node = ranked[0] if ranked else None
        else:
            next_node = None

    if not next_node:
        state["status"] = "no_nodes"
        state["last_error"] = "failover exhausted"
        save_state(state)
        print("[observer] failover failed — no candidates")
        return

    state["selected"] = node_summary(next_node)
    state["fails"] = 0
    state["status"] = "failover"
    state["last_delay_ms"] = next_node.get("delay_ms")
    state["last_speed_mbps"] = next_node.get("speed_mbps")
    save_state(state)
    apply_selected(cfg, next_node)
    print(f"[observer] FAIL OVER → {next_node.get('name')}")


def main() -> int:
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    print("[observer] starting")
    while _running:
        try:
            cfg = load_config()
            loop_once(cfg)
            interval = int((cfg.get("observer") or {}).get("interval_s", 60))
        except Exception:
            traceback.print_exc()
            interval = 60
        # sleep in small chunks for responsive shutdown
        for _ in range(max(interval, 5)):
            if not _running:
                break
            time.sleep(1)
    print("[observer] stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
