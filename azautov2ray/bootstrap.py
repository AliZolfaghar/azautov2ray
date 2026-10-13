"""Install system deps, venv, and download Xray-core binary."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from urllib.request import urlretrieve

from azautov2ray import OPT_DIR, VENV_DIR, XRAY_BIN

XRAY_VERSION = "26.9.30"  # pin a known-good release; update as needed


def run(cmd: list[str], check: bool = True, **kwargs) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd, check=check, **kwargs)


def detect_pkg_manager() -> str | None:
    for name in ("apt-get", "dnf", "yum", "pacman", "apk"):
        if shutil.which(name):
            return name
    return None


def ensure_python_packages_system() -> None:
    """Ensure python3 and venv tooling exist via package manager."""
    if sys.version_info < (3, 9):
        raise RuntimeError("Python 3.9+ is required")
    mgr = detect_pkg_manager()
    if mgr is None:
        print("  No supported package manager found; assuming python3 is ready.")
        return
    need_venv = not Path(sys.prefix).joinpath("bin", "python3").exists() or not shutil.which("python3")
    # Always try to ensure venv module available
    if mgr == "apt-get":
        run(["apt-get", "update", "-y"], check=False)
        run(
            ["apt-get", "install", "-y", "python3", "python3-venv", "python3-pip", "curl", "ca-certificates", "unzip"],
            check=False,
        )
    elif mgr == "dnf":
        run(["dnf", "install", "-y", "python3", "python3-pip", "curl", "ca-certificates", "unzip"], check=False)
    elif mgr == "yum":
        run(["yum", "install", "-y", "python3", "python3-pip", "curl", "ca-certificates", "unzip"], check=False)
    elif mgr == "pacman":
        run(["pacman", "-Sy", "--noconfirm", "python", "python-pip", "curl", "ca-certificates", "unzip"], check=False)
    elif mgr == "apk":
        run(["apk", "add", "--no-cache", "python3", "py3-pip", "curl", "ca-certificates", "unzip"], check=False)
    _ = need_venv


def xray_asset_name() -> str:
    machine = platform.machine().lower()
    system = platform.system().lower()
    if system != "linux":
        # Allow local testing on non-Linux with a warning
        print(f"  WARNING: non-Linux platform ({system}); downloading linux binary anyway.")
    arch_map = {
        "x86_64": "64",
        "amd64": "64",
        "aarch64": "arm64-v8a",
        "arm64": "arm64-v8a",
        "armv7l": "arm32-v7a",
        "armv6l": "arm32-v6",
        "i386": "32",
        "i686": "32",
    }
    arch = arch_map.get(machine)
    if not arch:
        raise RuntimeError(f"Unsupported architecture: {machine}")
    return f"Xray-linux-{arch}.zip"


def _latest_xray_tag() -> str | None:
    try:
        import json
        from urllib.request import Request, urlopen

        req = Request(
            "https://api.github.com/repos/XTLS/Xray-core/releases/latest",
            headers={"User-Agent": "azautov2ray"},
        )
        with urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        tag = (data.get("tag_name") or "").lstrip("v")
        return tag or None
    except Exception:
        return None


def download_xray(dest_bin: str = XRAY_BIN) -> str:
    Path(dest_bin).parent.mkdir(parents=True, exist_ok=True)
    if Path(dest_bin).is_file() and os.access(dest_bin, os.X_OK):
        print(f"  Xray already present: {dest_bin}")
        return dest_bin

    asset = xray_asset_name()
    versions = [XRAY_VERSION]
    latest = _latest_xray_tag()
    if latest and latest not in versions:
        versions.append(latest)

    last_err: Exception | None = None
    for ver in versions:
        url = f"https://github.com/XTLS/Xray-core/releases/download/v{ver}/{asset}"
        print(f"  Downloading Xray {ver}: {url}")
        try:
            with tempfile.TemporaryDirectory(prefix="azauto-xray-") as tmp:
                zip_path = Path(tmp) / asset
                urlretrieve(url, zip_path)
                with zipfile.ZipFile(zip_path, "r") as zf:
                    zf.extractall(tmp)
                extracted = Path(tmp) / "xray"
                if not extracted.is_file():
                    candidates = list(Path(tmp).rglob("xray"))
                    if not candidates:
                        raise RuntimeError("xray binary not found in release zip")
                    extracted = candidates[0]
                shutil.copy2(extracted, dest_bin)
                os.chmod(dest_bin, 0o755)
                for geo in ("geoip.dat", "geosite.dat"):
                    src = Path(tmp) / geo
                    if src.is_file():
                        shutil.copy2(src, Path(dest_bin).parent / geo)
            print(f"  Installed Xray → {dest_bin}")
            return dest_bin
        except Exception as exc:
            last_err = exc
            print(f"  Download failed for {ver}: {exc}")
    raise RuntimeError(f"Failed to download Xray-core: {last_err}")


def create_venv(venv_dir: str = VENV_DIR, requirements_file: str | None = None) -> str:
    venv_path = Path(venv_dir)
    python = venv_path / "bin" / "python"
    if not python.is_file():
        print(f"  Creating venv at {venv_dir}")
        run([sys.executable, "-m", "venv", str(venv_path)])
    pip = venv_path / "bin" / "pip"
    run([str(pip), "install", "--upgrade", "pip"], check=False)
    if requirements_file and Path(requirements_file).is_file():
        run([str(pip), "install", "-r", requirements_file])
    else:
        run([str(pip), "install", "PyYAML", "requests", "qrcode[pil]", "Pillow"])
    return str(python)


def install_package_editable(repo_root: str, venv_dir: str = VENV_DIR) -> None:
    """Copy package into OPT_DIR and make it importable."""
    src = Path(repo_root)
    dest = Path(OPT_DIR)
    dest.mkdir(parents=True, exist_ok=True)
    pkg_src = src / "azautov2ray"
    pkg_dest = dest / "azautov2ray"
    if pkg_dest.exists():
        shutil.rmtree(pkg_dest)
    shutil.copytree(pkg_src, pkg_dest)
    # Also copy requirements and systemd templates if present
    for name in ("requirements.txt",):
        f = src / name
        if f.is_file():
            shutil.copy2(f, dest / name)
    systemd_src = src / "systemd"
    if systemd_src.is_dir():
        systemd_dest = dest / "systemd"
        if systemd_dest.exists():
            shutil.rmtree(systemd_dest)
        shutil.copytree(systemd_src, systemd_dest)
    # Write a small sitecustomize /.pth so venv finds the package
    site_packages = list((Path(venv_dir) / "lib").glob("python*/site-packages"))
    if site_packages:
        pth = site_packages[0] / "azautov2ray.pth"
        pth.write_text(str(dest) + "\n", encoding="utf-8")
    print(f"  Package installed under {dest}")


def open_firewall_port(port: int) -> None:
    port = int(port)
    if shutil.which("ufw"):
        status = subprocess.run(["ufw", "status"], capture_output=True, text=True)
        if "Status: active" in (status.stdout or ""):
            run(["ufw", "allow", f"{port}/tcp"], check=False)
            print(f"  ufw: allowed {port}/tcp")
            return
    if shutil.which("firewall-cmd"):
        run(["firewall-cmd", "--permanent", f"--add-port={port}/tcp"], check=False)
        run(["firewall-cmd", "--reload"], check=False)
        print(f"  firewalld: allowed {port}/tcp")
        return
    print("  No ufw/firewalld active — ensure the port is open in your cloud panel.")


def close_firewall_port(port: int) -> None:
    port = int(port)
    if shutil.which("ufw"):
        run(["ufw", "delete", "allow", f"{port}/tcp"], check=False)
    if shutil.which("firewall-cmd"):
        run(["firewall-cmd", "--permanent", f"--remove-port={port}/tcp"], check=False)
        run(["firewall-cmd", "--reload"], check=False)


def install_cli_wrapper() -> None:
    """Install /usr/local/bin/azautov2ray → management menu."""
    wrapper = Path("/usr/local/bin/azautov2ray")
    content = f"""#!/usr/bin/env bash
set -euo pipefail
export PYTHONPATH="{OPT_DIR}${{PYTHONPATH:+:$PYTHONPATH}}"
exec "{VENV_DIR}/bin/python" -m azautov2ray.cli "$@"
"""
    try:
        wrapper.parent.mkdir(parents=True, exist_ok=True)
        wrapper.write_text(content, encoding="utf-8")
        os.chmod(wrapper, 0o755)
        print(f"  CLI wrapper: {wrapper}")
    except OSError as exc:
        print(f"  Could not install CLI wrapper: {exc}")


def remove_cli_wrapper() -> None:
    wrapper = Path("/usr/local/bin/azautov2ray")
    if wrapper.is_file():
        wrapper.unlink()
        print(f"  Removed {wrapper}")
