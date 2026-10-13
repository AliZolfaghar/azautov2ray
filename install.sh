#!/usr/bin/env bash
# azautov2ray - one-shot installer / management launcher
set -euo pipefail

ETC_DIR="/etc/azautov2ray"
OPT_DIR="/opt/azautov2ray"
VENV_DIR="${OPT_DIR}/venv"
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
  info "Ensuring python3 + venv tooling ..."
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update -y >/dev/null
    DEBIAN_FRONTEND=noninteractive apt-get install -y \
      python3 python3-venv python3-pip curl ca-certificates unzip >/dev/null
  elif command -v dnf >/dev/null 2>&1; then
    dnf install -y python3 python3-pip curl ca-certificates unzip >/dev/null
  elif command -v yum >/dev/null 2>&1; then
    yum install -y python3 python3-pip curl ca-certificates unzip >/dev/null
  elif command -v pacman >/dev/null 2>&1; then
    pacman -Sy --noconfirm python python-pip curl ca-certificates unzip >/dev/null
  elif command -v apk >/dev/null 2>&1; then
    apk add --no-cache python3 py3-pip curl ca-certificates unzip >/dev/null
  fi

  if ! command -v python3 >/dev/null 2>&1; then
    err "python3 not found and could not be installed."
    exit 1
  fi

  # Verify venv module works (needed on Debian/Ubuntu PEP 668)
  if ! python3 -c "import venv" 2>/dev/null; then
    err "python3-venv is missing. On Debian/Ubuntu: apt install python3-venv"
    exit 1
  fi
}

ensure_venv() {
  mkdir -p "${OPT_DIR}"
  if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
    info "Creating virtualenv at ${VENV_DIR} ..."
    python3 -m venv "${VENV_DIR}"
  fi
  info "Installing Python dependencies into venv (not system-wide) ..."
  "${VENV_DIR}/bin/pip" install --upgrade pip >/dev/null
  if [[ -f "${REPO_ROOT}/requirements.txt" ]]; then
    "${VENV_DIR}/bin/pip" install -r "${REPO_ROOT}/requirements.txt"
  else
    "${VENV_DIR}/bin/pip" install "PyYAML>=6.0.1" "requests>=2.31.0" "qrcode[pil]>=7.4.2" "Pillow>=10.0.0"
  fi
  ok "venv ready"
}

is_installed() {
  [[ -f "${CONFIG_FILE}" ]] || return 1
  # Prefer venv python if present; fall back to system python3
  local py="python3"
  [[ -x "${VENV_DIR}/bin/python" ]] && py="${VENV_DIR}/bin/python"
  PYTHONPATH="${OPT_DIR}:${REPO_ROOT:-}" "${py}" - <<'PY'
from pathlib import Path
import sys
sys.path.insert(0, "/opt/azautov2ray")
try:
    from azautov2ray.config import is_installed
    sys.exit(0 if is_installed() else 1)
except Exception:
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
  export PYTHONPATH="${OPT_DIR}:${REPO_ROOT}${PYTHONPATH:+:$PYTHONPATH}"
  cd "${REPO_ROOT}"
  attach_tty
  exec "${VENV_DIR}/bin/python" -m azautov2ray.cli "$@"
}

main() {
  need_root
  resolve_repo_root
  ensure_python
  ensure_venv
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
    export PYTHONPATH="${REPO_ROOT}:${OPT_DIR}${PYTHONPATH:+:$PYTHONPATH}"
    cd "${REPO_ROOT}"
    attach_tty
    exec "${VENV_DIR}/bin/python" -m azautov2ray.cli "$@"
  fi
}

main "$@"
