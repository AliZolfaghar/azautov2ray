"""Fetch and parse proxy subscription URLs into node dicts."""

from __future__ import annotations

import base64
import json
import re
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import requests

SUPPORTED_SCHEMES = ("vless", "vmess", "trojan", "ss")


def _b64decode(data: str) -> bytes:
    data = data.strip().replace("-", "+").replace("_", "/")
    pad = (-len(data)) % 4
    if pad:
        data += "=" * pad
    return base64.b64decode(data)


def _decode_subscription_body(text: str) -> str:
    text = text.strip()
    if not text:
        return ""
    # Already a list of URIs
    if any(text.startswith(s + "://") or f"\n{s}://" in text for s in SUPPORTED_SCHEMES):
        return text
    try:
        decoded = _b64decode(text).decode("utf-8", errors="ignore")
        if any(s + "://" in decoded for s in SUPPORTED_SCHEMES):
            return decoded
    except Exception:
        pass
    return text


def fetch_subscription(url: str, timeout: int = 30) -> list[str]:
    headers = {"User-Agent": "azautov2ray/1.0"}
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    body = _decode_subscription_body(resp.text)
    lines: list[str] = []
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        scheme = line.split("://", 1)[0].lower()
        if scheme in SUPPORTED_SCHEMES:
            lines.append(line)
    return lines


def fetch_all(urls: list[str]) -> list[str]:
    all_uris: list[str] = []
    seen: set[str] = set()
    for url in urls:
        url = (url or "").strip()
        if not url:
            continue
        try:
            uris = fetch_subscription(url)
            print(f"  [sub] {url} → {len(uris)} configs")
            for u in uris:
                if u not in seen:
                    seen.add(u)
                    all_uris.append(u)
        except Exception as exc:
            print(f"  [sub] FAILED {url}: {exc}")
    return all_uris


def _parse_vmess(uri: str) -> dict[str, Any] | None:
    try:
        raw = uri.split("://", 1)[1]
        data = json.loads(_b64decode(raw).decode("utf-8"))
    except Exception:
        return None
    host = data.get("add") or data.get("host") or ""
    port = int(data.get("port") or 0)
    if not host or not port:
        return None
    return {
        "protocol": "vmess",
        "name": data.get("ps") or f"vmess-{host}:{port}",
        "address": host,
        "port": port,
        "uuid": data.get("id") or "",
        "alterId": int(data.get("aid") or 0),
        "security": data.get("scy") or "auto",
        "network": data.get("net") or "tcp",
        "tls": data.get("tls") or "",
        "sni": data.get("sni") or data.get("host") or "",
        "path": data.get("path") or "/",
        "host_header": data.get("host") or "",
        "type": data.get("type") or "none",
        "alpn": data.get("alpn") or "",
        "fp": data.get("fp") or "",
        "uri": uri,
    }


def _qs_first(qs: dict[str, list[str]], key: str, default: str = "") -> str:
    vals = qs.get(key)
    if not vals:
        return default
    return unquote(vals[0])


def _parse_vless(uri: str) -> dict[str, Any] | None:
    try:
        parsed = urlparse(uri)
        if parsed.scheme != "vless":
            return None
        uuid_ = parsed.username or ""
        host = parsed.hostname or ""
        port = int(parsed.port or 0)
        if not uuid_ or not host or not port:
            return None
        qs = parse_qs(parsed.query)
        name = unquote(parsed.fragment) if parsed.fragment else f"vless-{host}:{port}"
        return {
            "protocol": "vless",
            "name": name,
            "address": host,
            "port": port,
            "uuid": uuid_,
            "encryption": _qs_first(qs, "encryption", "none"),
            "flow": _qs_first(qs, "flow"),
            "network": _qs_first(qs, "type", "tcp"),
            "security": _qs_first(qs, "security"),
            "sni": _qs_first(qs, "sni"),
            "fp": _qs_first(qs, "fp"),
            "pbk": _qs_first(qs, "pbk"),
            "sid": _qs_first(qs, "sid"),
            "spx": _qs_first(qs, "spx"),
            "path": _qs_first(qs, "path", "/"),
            "host_header": _qs_first(qs, "host"),
            "headerType": _qs_first(qs, "headerType", "none"),
            "serviceName": _qs_first(qs, "serviceName"),
            "mode": _qs_first(qs, "mode"),
            "alpn": _qs_first(qs, "alpn"),
            "uri": uri,
        }
    except Exception:
        return None


def _parse_trojan(uri: str) -> dict[str, Any] | None:
    try:
        parsed = urlparse(uri)
        if parsed.scheme != "trojan":
            return None
        password = unquote(parsed.username or "")
        host = parsed.hostname or ""
        port = int(parsed.port or 0)
        if not password or not host or not port:
            return None
        qs = parse_qs(parsed.query)
        name = unquote(parsed.fragment) if parsed.fragment else f"trojan-{host}:{port}"
        return {
            "protocol": "trojan",
            "name": name,
            "address": host,
            "port": port,
            "password": password,
            "network": _qs_first(qs, "type", "tcp"),
            "security": _qs_first(qs, "security", "tls"),
            "sni": _qs_first(qs, "sni") or host,
            "fp": _qs_first(qs, "fp"),
            "path": _qs_first(qs, "path", "/"),
            "host_header": _qs_first(qs, "host"),
            "alpn": _qs_first(qs, "alpn"),
            "uri": uri,
        }
    except Exception:
        return None


def _parse_ss(uri: str) -> dict[str, Any] | None:
    """Parse ss://method:password@host:port or ss://base64#name"""
    try:
        if not uri.startswith("ss://"):
            return None
        rest = uri[5:]
        name = ""
        if "#" in rest:
            rest, frag = rest.split("#", 1)
            name = unquote(frag)
        # SIP002: base64(method:pass)@host:port
        if "@" in rest:
            userinfo, hostport = rest.rsplit("@", 1)
            try:
                decoded = _b64decode(userinfo).decode("utf-8")
            except Exception:
                decoded = unquote(userinfo)
            if ":" not in decoded:
                return None
            method, password = decoded.split(":", 1)
            if ":" not in hostport:
                return None
            host, port_s = hostport.rsplit(":", 1)
            port = int(port_s)
        else:
            decoded = _b64decode(rest).decode("utf-8")
            # method:password@host:port
            m = re.match(r"^(.+?):(.+)@(.+):(\d+)$", decoded)
            if not m:
                return None
            method, password, host, port_s = m.groups()
            port = int(port_s)
        return {
            "protocol": "shadowsocks",
            "name": name or f"ss-{host}:{port}",
            "address": host,
            "port": port,
            "method": method,
            "password": password,
            "uri": uri,
        }
    except Exception:
        return None


def parse_uri(uri: str) -> dict[str, Any] | None:
    uri = uri.strip()
    if uri.startswith("vmess://"):
        return _parse_vmess(uri)
    if uri.startswith("vless://"):
        return _parse_vless(uri)
    if uri.startswith("trojan://"):
        return _parse_trojan(uri)
    if uri.startswith("ss://"):
        return _parse_ss(uri)
    return None


def parse_uris(
    uris: list[str],
    *,
    only_ports: set[int] | None = None,
) -> list[dict[str, Any]]:
    """Parse URIs into nodes. By default only keep configs listening on port 443."""
    if only_ports is None:
        only_ports = {443}
    nodes: list[dict[str, Any]] = []
    skipped = 0
    for uri in uris:
        node = parse_uri(uri)
        if not node:
            continue
        try:
            port = int(node.get("port") or 0)
        except (TypeError, ValueError):
            skipped += 1
            continue
        if only_ports and port not in only_ports:
            skipped += 1
            continue
        nodes.append(node)
    if only_ports:
        ports_txt = ",".join(str(p) for p in sorted(only_ports))
        print(f"  Port filter ({ports_txt}): kept {len(nodes)}, dropped {skipped}")
    return nodes
