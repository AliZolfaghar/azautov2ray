"""Reality key helpers, VLESS share link, and terminal QR."""

from __future__ import annotations

import secrets
import subprocess
import uuid
from typing import Any
from urllib.parse import quote, urlencode


def generate_uuid() -> str:
    return str(uuid.uuid4())


def generate_short_id(nbytes: int = 8) -> str:
    return secrets.token_hex(nbytes)


def generate_reality_keys(xray_bin: str) -> tuple[str, str]:
    """Return (private_key, public_key) using `xray x25519`."""
    proc = subprocess.run(
        [xray_bin, "x25519"],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    private_key = ""
    public_key = ""
    for line in proc.stdout.splitlines():
        lower = line.lower().strip()
        if "private" in lower:
            private_key = line.split(":", 1)[-1].strip()
        elif "public" in lower:
            public_key = line.split(":", 1)[-1].strip()
    if not private_key or not public_key:
        raise RuntimeError(f"Failed to parse xray x25519 output:\n{proc.stdout}\n{proc.stderr}")
    return private_key, public_key


def build_vless_link(cfg: dict[str, Any]) -> str:
    server = cfg["server"]
    gen = cfg["generated"]
    host = server.get("domain") or server.get("public_ip")
    port = int(server["reality_port"])
    uid = gen["uuid"]
    pbk = gen["reality_public_key"]
    sid = gen["short_id"]
    sni = (server.get("reality_server_names") or ["www.microsoft.com"])[0]
    dest = server.get("reality_dest") or f"{sni}:443"
    # fingerprint chrome is widely compatible
    query = {
        "encryption": "none",
        "flow": "xtls-rprx-vision",
        "security": "reality",
        "sni": sni,
        "fp": "chrome",
        "pbk": pbk,
        "sid": sid,
        "spx": "/",
        "type": "tcp",
        "headerType": "none",
    }
    # dest is not part of standard share link but some clients accept it via extra params — omit
    _ = dest
    name = quote(f"azautov2ray-{host}")
    return f"vless://{uid}@{host}:{port}?{urlencode(query)}#{name}"


def print_qr(link: str) -> None:
    try:
        import qrcode
    except ImportError:
        print("(qrcode package not installed — showing link only)")
        print(link)
        return
    qr = qrcode.QRCode(border=1)
    qr.add_data(link)
    qr.make(fit=True)
    qr.print_ascii(invert=True)
    print()
    print(link)
