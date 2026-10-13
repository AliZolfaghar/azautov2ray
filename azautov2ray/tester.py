"""Multi-stage node testing: TCP reachability, real delay, download speed."""

from __future__ import annotations

import concurrent.futures
import os
import socket
import subprocess
import tempfile
import time
from typing import Any

import requests

from azautov2ray import XRAY_BIN
from azautov2ray.xray_gen import build_test_config, write_xray_json


def tcp_ping(host: str, port: int, timeout_ms: int) -> float | None:
    """Return connect latency in ms, or None if unreachable."""
    timeout_s = max(timeout_ms / 1000.0, 0.1)
    start = time.perf_counter()
    try:
        with socket.create_connection((host, int(port)), timeout=timeout_s):
            return (time.perf_counter() - start) * 1000.0
    except OSError:
        return None


def filter_reachable(nodes: list[dict[str, Any]], timeout_ms: int, concurrency: int = 20) -> list[dict[str, Any]]:
    print(f"[1/3] TCP reachability test ({len(nodes)} nodes, timeout={timeout_ms}ms)...")
    alive: list[dict[str, Any]] = []

    def check(node: dict[str, Any]) -> dict[str, Any] | None:
        ms = tcp_ping(node["address"], node["port"], timeout_ms)
        if ms is None:
            return None
        out = dict(node)
        out["tcp_ms"] = round(ms, 1)
        return out

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(check, n) for n in nodes]
        for fut in concurrent.futures.as_completed(futures):
            result = fut.result()
            if result:
                alive.append(result)

    alive.sort(key=lambda n: n.get("tcp_ms", 99999))
    print(f"  → {len(alive)} reachable / {len(nodes)} total")
    return alive


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _run_xray_temp(config: dict[str, Any], xray_bin: str) -> tuple[subprocess.Popen, str]:
    fd, path = tempfile.mkstemp(prefix="azauto-test-", suffix=".json")
    os.close(fd)
    write_xray_json(config, path)
    proc = subprocess.Popen(
        [xray_bin, "run", "-c", path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Give xray a moment to bind
    time.sleep(0.4)
    return proc, path


def _stop_xray(proc: subprocess.Popen, conf_path: str) -> None:
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    try:
        os.unlink(conf_path)
    except OSError:
        pass


def measure_real_delay(
    node: dict[str, Any],
    url: str,
    max_ms: int,
    xray_bin: str = XRAY_BIN,
) -> float | None:
    socks_port = _free_port()
    conf = build_test_config(node, socks_port)
    proc, conf_path = _run_xray_temp(conf, xray_bin)
    try:
        proxies = {
            "http": f"socks5h://127.0.0.1:{socks_port}",
            "https": f"socks5h://127.0.0.1:{socks_port}",
        }
        timeout_s = max(max_ms / 1000.0, 1.0) + 2.0
        start = time.perf_counter()
        resp = requests.get(url, proxies=proxies, timeout=timeout_s, allow_redirects=False)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        if resp.status_code >= 400 and resp.status_code not in (204, 301, 302, 307, 308):
            return None
        if elapsed_ms > max_ms:
            return None
        return elapsed_ms
    except Exception:
        return None
    finally:
        _stop_xray(proc, conf_path)


def measure_speed(
    node: dict[str, Any],
    url: str,
    timeout_s: int,
    xray_bin: str = XRAY_BIN,
) -> float | None:
    """Return download speed in Mbps."""
    socks_port = _free_port()
    conf = build_test_config(node, socks_port)
    proc, conf_path = _run_xray_temp(conf, xray_bin)
    try:
        proxies = {
            "http": f"socks5h://127.0.0.1:{socks_port}",
            "https": f"socks5h://127.0.0.1:{socks_port}",
        }
        start = time.perf_counter()
        resp = requests.get(url, proxies=proxies, timeout=timeout_s, stream=True)
        total = 0
        for chunk in resp.iter_content(chunk_size=65536):
            if chunk:
                total += len(chunk)
            if time.perf_counter() - start > timeout_s:
                break
        elapsed = time.perf_counter() - start
        if elapsed <= 0 or total < 1024:
            return None
        mbps = (total * 8) / elapsed / 1_000_000
        return round(mbps, 3)
    except Exception:
        return None
    finally:
        _stop_xray(proc, conf_path)


def real_delay_filter(
    nodes: list[dict[str, Any]],
    url: str,
    max_ms: int,
    xray_bin: str = XRAY_BIN,
) -> list[dict[str, Any]]:
    print(f"[2/3] Real delay test ({len(nodes)} nodes, max={max_ms}ms)...")
    passed: list[dict[str, Any]] = []
    for i, node in enumerate(nodes, 1):
        name = node.get("name") or f"{node['address']}:{node['port']}"
        delay = measure_real_delay(node, url, max_ms, xray_bin=xray_bin)
        if delay is None:
            print(f"  [{i}/{len(nodes)}] FAIL  {name}")
            continue
        out = dict(node)
        out["delay_ms"] = round(delay, 1)
        passed.append(out)
        print(f"  [{i}/{len(nodes)}] OK    {name}  {out['delay_ms']} ms")
    passed.sort(key=lambda n: n.get("delay_ms", 99999))
    print(f"  → {len(passed)} passed real-delay")
    return passed


def speed_rank(
    nodes: list[dict[str, Any]],
    url: str,
    timeout_s: int,
    max_candidates: int,
    xray_bin: str = XRAY_BIN,
) -> list[dict[str, Any]]:
    candidates = nodes[: max(1, max_candidates)]
    print(f"[3/3] Download speed test (top {len(candidates)} by delay)...")
    ranked: list[dict[str, Any]] = []
    for i, node in enumerate(candidates, 1):
        name = node.get("name") or f"{node['address']}:{node['port']}"
        speed = measure_speed(node, url, timeout_s, xray_bin=xray_bin)
        if speed is None:
            print(f"  [{i}/{len(candidates)}] FAIL  {name}")
            continue
        out = dict(node)
        out["speed_mbps"] = speed
        ranked.append(out)
        print(f"  [{i}/{len(candidates)}] OK    {name}  {speed} Mbps")
    ranked.sort(key=lambda n: n.get("speed_mbps", 0), reverse=True)
    print(f"  → {len(ranked)} with measurable speed")
    return ranked


def run_full_pipeline(cfg: dict[str, Any], nodes: list[dict[str, Any]], xray_bin: str = XRAY_BIN) -> list[dict[str, Any]]:
    t = cfg.get("testing") or {}
    if not nodes:
        return []
    alive = filter_reachable(
        nodes,
        timeout_ms=int(t.get("ping_timeout_ms", 1500)),
        concurrency=int(t.get("concurrency", 20)),
    )
    if not alive:
        return []
    delayed = real_delay_filter(
        alive,
        url=t.get("real_delay_url") or "https://www.google.com/generate_204",
        max_ms=int(t.get("real_delay_max_ms", 2000)),
        xray_bin=xray_bin,
    )
    if not delayed:
        return []
    ranked = speed_rank(
        delayed,
        url=t.get("speed_url") or "https://speed.cloudflare.com/__down?bytes=10000000",
        timeout_s=int(t.get("speed_timeout_s", 15)),
        max_candidates=int(t.get("max_candidates_for_speed", 10)),
        xray_bin=xray_bin,
    )
    return ranked if ranked else delayed


def node_summary(node: dict[str, Any] | None) -> dict[str, Any] | None:
    if not node:
        return None
    keys = (
        "protocol",
        "name",
        "address",
        "port",
        "tcp_ms",
        "delay_ms",
        "speed_mbps",
        "uri",
        "uuid",
        "password",
        "method",
        "encryption",
        "flow",
        "network",
        "security",
        "tls",
        "sni",
        "fp",
        "pbk",
        "sid",
        "spx",
        "path",
        "host_header",
        "headerType",
        "serviceName",
        "mode",
        "alpn",
        "alterId",
    )
    return {k: node[k] for k in keys if k in node}


def dump_ranked(ranked: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [node_summary(n) for n in ranked if n]
