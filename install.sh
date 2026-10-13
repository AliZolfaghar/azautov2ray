#!/usr/bin/env bash
# azautov2ray - one-shot installer / management launcher
set -euo pipefail

ETC_DIR="/etc/azautov2ray"
OPT_DIR="/opt/azautov2ray"
CONFIG_FILE="${ETC_DIR}/config.yaml"

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}[*]${NC} $*"; }
ok()    { echo -e "${GREEN}[+]${NC} $*"; }
err()   { echo -e "${RED}[!]${NC} $*" >&2; }

need_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    err "Please run as root: sudo bash install.sh"
    exit 1
  fi
}

resolve_repo_root() {
  # When piped from curl, BASH_SOURCE may be empty / stdin
  local src="${BASH_SOURCE[0]:-}"
  if [[ -n "${src}" && "${src}" != "bash" && "${src}" != "/dev/stdin" && -f "${src}" ]]; then
    cd "$(cd "$(dirname "${src}")" && pwd)"
    REPO_ROOT="$(pwd)"
    return
  fi

  # Prefer already-installed copy
  if [[ -d "${OPT_DIR}/azautov2ray" ]]; then
    REPO_ROOT="${OPT_DIR}"
    return
  fi

  # Bootstrap from GitHub
  REPO_ROOT="$(mktemp -d /tmp/azautov2ray-src.XXXXXX)"
  info "Downloading source to ${REPO_ROOT} ..."
  if command -v git >/dev/null 2>&1; then
    git clone --depth 1 https://github.com/AliZolfaghar/azautov2ray.git "${REPO_ROOT}"
  else
    local zipurl="https://github.com/AliZolfaghar/azautov2ray/archive/refs/heads/main.tar.gz"
    curl -fsSL "${zipurl}" | tar -xz -C "${REPO_ROOT}" --strip-components=1
  fi
}

ensure_python() {
  if command -v python3 >/dev/null 2>&1; then
    return
  fi
  info "Installing python3 ..."
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update -y
    apt-get install -y python3 python3-venv python3-pip curl ca-certificates unzip
  elif command -v dnf >/dev/null 2>&1; then
    dnf install -y python3 python3-pip curl ca-certificates unzip
  elif command -v yum >/dev/null 2>&1; then
    yum install -y python3 python3-pip curl ca-certificates unzip
  else
    err "python3 not found and no supported package manager available."
    exit 1
  fi
}

is_installed() {
  [[ -f "${CONFIG_FILE}" ]] || return 1
  python3 - <<'PY'
from pathlib import Path
import sys
sys.path.insert(0, "/opt/azautov2ray")
try:
    from azautov2ray.config import is_installed
    sys.exit(0 if is_installed() else 1)
except Exception:
    # Fallback: config exists with generated uuid key
    text = Path("/etc/azautov2ray/config.yaml").read_text(encoding="utf-8", errors="ignore")
    sys.exit(0 if "reality_private_key:" in text and "uuid:" in text else 1)
PY
}

attach_tty() {
  # When launched via `curl | bash`, stdin is the script pipe — reconnect to the real terminal.
  if [[ ! -t 0 ]] && [[ -r /dev/tty ]]; then
    exec </dev/tty
  fi
}

run_python_cli() {
  local py
  if [[ -x "${OPT_DIR}/venv/bin/python" ]]; then
    py="${OPT_DIR}/venv/bin/python"
    export PYTHONPATH="${OPT_DIR}${PYTHONPATH:+:$PYTHONPATH}"
  else
    ensure_python
    py="python3"
    export PYTHONPATH="${REPO_ROOT}${PYTHONPATH:+:$PYTHONPATH}"
  fi
  cd "${REPO_ROOT}"
  attach_tty
  exec "${py}" -m azautov2ray.cli "$@"
}

main() {
  need_root
  resolve_repo_root
  ensure_python
  attach_tty

  echo
  echo "=============================================="
  echo "  azautov2ray"
  echo "=============================================="
  echo

  if is_installed; then
    ok "Installation detected at ${ETC_DIR}"
    info "Opening management menu ..."
    run_python_cli menu "$@"
  else
    info "Not installed yet — starting setup wizard ..."
    # First run: use repo checkout so package is importable
    export PYTHONPATH="${REPO_ROOT}${PYTHONPATH:+:$PYTHONPATH}"
    # Minimal deps for wizard bootstrap (full venv created inside wizard)
    python3 -m pip install --user -q PyYAML requests 'qrcode[pil]' Pillow 2>/dev/null || \
      python3 -m pip install -q PyYAML requests 'qrcode[pil]' Pillow || true
    cd "${REPO_ROOT}"
    attach_tty
    exec python3 -m azautov2ray.cli "$@"
  fi
}

main "$@"
