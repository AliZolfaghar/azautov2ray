"""Build Xray JSON configs from nodes and app settings."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from azautov2ray import XRAY_JSON_PATH


def _stream_settings(node: dict[str, Any]) -> dict[str, Any]:
    network = (node.get("network") or "tcp").lower()
    # VMess uses "security" for cipher (auto/aes-...); TLS flag lives in "tls"
    if node.get("protocol") == "vmess":
        security = (node.get("tls") or "").lower()
    else:
        security = (node.get("security") or node.get("tls") or "").lower()
    if security not in ("tls", "reality", "none", ""):
        security = ""
    stream: dict[str, Any] = {"network": network}

    if network in ("ws", "websocket"):
        stream["network"] = "ws"
        stream["wsSettings"] = {
            "path": node.get("path") or "/",
            "headers": {},
        }
        if node.get("host_header"):
            stream["wsSettings"]["headers"]["Host"] = node["host_header"]
    elif network == "grpc":
        stream["grpcSettings"] = {
            "serviceName": node.get("serviceName") or node.get("path") or "",
            "multiMode": (node.get("mode") or "") == "multi",
        }
    elif network == "tcp":
        header_type = node.get("headerType") or node.get("type") or "none"
        if header_type and header_type != "none":
            stream["tcpSettings"] = {"header": {"type": header_type}}

    if security in ("tls", "reality"):
        stream["security"] = security
        if security == "tls":
            tls: dict[str, Any] = {
                "serverName": node.get("sni") or node.get("address") or "",
                "allowInsecure": False,
            }
            if node.get("fp"):
                tls["fingerprint"] = node["fp"]
            if node.get("alpn"):
                tls["alpn"] = [a.strip() for a in str(node["alpn"]).split(",") if a.strip()]
            stream["tlsSettings"] = tls
        else:
            reality: dict[str, Any] = {
                "serverName": node.get("sni") or "",
                "publicKey": node.get("pbk") or "",
                "shortId": node.get("sid") or "",
                "spiderX": node.get("spx") or "/",
            }
            if node.get("fp"):
                reality["fingerprint"] = node["fp"]
            stream["realitySettings"] = reality
    else:
        stream["security"] = "none"

    return stream


def node_to_outbound(node: dict[str, Any], tag: str = "proxy") -> dict[str, Any]:
    protocol = node["protocol"]
    outbound: dict[str, Any] = {"tag": tag, "protocol": protocol}

    if protocol == "vless":
        user: dict[str, Any] = {
            "id": node["uuid"],
            "encryption": node.get("encryption") or "none",
        }
        if node.get("flow"):
            user["flow"] = node["flow"]
        outbound["settings"] = {
            "vnext": [
                {
                    "address": node["address"],
                    "port": int(node["port"]),
                    "users": [user],
                }
            ]
        }
        outbound["streamSettings"] = _stream_settings(node)
    elif protocol == "vmess":
        outbound["settings"] = {
            "vnext": [
                {
                    "address": node["address"],
                    "port": int(node["port"]),
                    "users": [
                        {
                            "id": node["uuid"],
                            "alterId": int(node.get("alterId") or 0),
                            "security": node.get("security") or "auto",
                        }
                    ],
                }
            ]
        }
        outbound["streamSettings"] = _stream_settings(node)
    elif protocol == "trojan":
        outbound["settings"] = {
            "servers": [
                {
                    "address": node["address"],
                    "port": int(node["port"]),
                    "password": node["password"],
                }
            ]
        }
        outbound["streamSettings"] = _stream_settings(node)
    elif protocol == "shadowsocks":
        outbound["settings"] = {
            "servers": [
                {
                    "address": node["address"],
                    "port": int(node["port"]),
                    "method": node["method"],
                    "password": node["password"],
                }
            ]
        }
    else:
        raise ValueError(f"Unsupported protocol: {protocol}")

    return outbound


def build_test_config(node: dict[str, Any], socks_port: int) -> dict[str, Any]:
    """Minimal Xray config: local SOCKS → single outbound node."""
    return {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "tag": "socks-in",
                "listen": "127.0.0.1",
                "port": socks_port,
                "protocol": "socks",
                "settings": {"udp": False},
            }
        ],
        "outbounds": [
            node_to_outbound(node, tag="proxy"),
            {"tag": "direct", "protocol": "freedom"},
            {"tag": "block", "protocol": "blackhole"},
        ],
        "routing": {
            "domainStrategy": "AsIs",
            "rules": [
                {"type": "field", "inboundTag": ["socks-in"], "outboundTag": "proxy"},
            ],
        },
    }


def build_server_config(cfg: dict[str, Any], selected_node: dict[str, Any] | None) -> dict[str, Any]:
    """Full VPS config: Reality inbound + selected upstream outbound."""
    server = cfg["server"]
    gen = cfg["generated"]
    port = int(server["reality_port"])
    dest = server.get("reality_dest") or "www.microsoft.com:443"
    server_names = server.get("reality_server_names") or ["www.microsoft.com"]
    short_id = gen["short_id"]

    inbound = {
        "tag": "reality-in",
        "listen": "0.0.0.0",
        "port": port,
        "protocol": "vless",
        "settings": {
            "clients": [
                {
                    "id": gen["uuid"],
                    "flow": "xtls-rprx-vision",
                }
            ],
            "decryption": "none",
        },
        "streamSettings": {
            "network": "tcp",
            "security": "reality",
            "realitySettings": {
                "show": False,
                "dest": dest,
                "xver": 0,
                "serverNames": server_names,
                "privateKey": gen["reality_private_key"],
                "shortIds": [short_id],
            },
        },
        "sniffing": {
            "enabled": True,
            "destOverride": ["http", "tls", "quic"],
        },
    }

    outbounds: list[dict[str, Any]] = []
    if selected_node:
        outbounds.append(node_to_outbound(selected_node, tag="proxy"))
    else:
        # Placeholder until a node is selected — direct only (no tunnel)
        outbounds.append({"tag": "proxy", "protocol": "freedom", "settings": {}})

    outbounds.extend(
        [
            {"tag": "direct", "protocol": "freedom"},
            {"tag": "block", "protocol": "blackhole"},
            {"tag": "api", "protocol": "freedom"},
        ]
    )

    return {
        "log": {
            "loglevel": "warning",
            "access": "/etc/azautov2ray/logs/xray-access.log",
            "error": "/etc/azautov2ray/logs/xray-error.log",
        },
        "api": {
            "tag": "api",
            "listen": "127.0.0.1:10085",
            "services": ["HandlerService", "StatsService", "LoggerService"],
        },
        "inbounds": [inbound],
        "outbounds": outbounds,
        "routing": {
            "domainStrategy": "AsIs",
            "rules": [
                {"type": "field", "inboundTag": ["api"], "outboundTag": "api"},
                {"type": "field", "inboundTag": ["reality-in"], "outboundTag": "proxy"},
            ],
        },
    }


def write_xray_json(config: dict[str, Any], path: str = XRAY_JSON_PATH) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as fh:
        json.dump(config, fh, ensure_ascii=False, indent=2)
