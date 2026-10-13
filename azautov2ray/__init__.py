"""azautov2ray — automatic Xray Reality relay with subscription testing."""

__version__ = "1.0.0"

# Default install paths (Linux VPS)
OPT_DIR = "/opt/azautov2ray"
ETC_DIR = "/etc/azautov2ray"
CONFIG_PATH = f"{ETC_DIR}/config.yaml"
STATE_PATH = f"{ETC_DIR}/state.json"
XRAY_JSON_PATH = f"{ETC_DIR}/xray.json"
XRAY_BIN = f"{OPT_DIR}/bin/xray"
VENV_DIR = f"{OPT_DIR}/venv"
LOG_DIR = f"{ETC_DIR}/logs"
