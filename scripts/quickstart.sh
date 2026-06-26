#!/usr/bin/env bash
# F3: One-command dev environment setup for backlink-publisher.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== backlink-publisher quickstart ==="
echo "Repo: $REPO_DIR"

# 1. Python version check
PYTHON_VERSION=$(python3 --version 2>&1)
echo "Python: $PYTHON_VERSION"
if ! python3 --version 2>&1 | grep -qE "3\.1[12]"; then
    echo "ERROR: Python 3.11 or 3.12 required. Got: $PYTHON_VERSION" >&2
    exit 1
fi

# 2. Create venv if not exists
if [[ ! -d "$REPO_DIR/.venv" ]]; then
    echo "Creating .venv..."
    python3 -m venv "$REPO_DIR/.venv"
fi

# shellcheck disable=SC1091
source "$REPO_DIR/.venv/bin/activate"

# 3. Install with dev deps (use python -m pip to avoid shebang path issues)
echo "Installing backlink-publisher[dev]..."
python -m pip install -e "$REPO_DIR[dev]" -q

# 4. Playwright (optional — skip if chromium already installed)
if ! python -c "from playwright.sync_api import sync_playwright; p = sync_playwright().start(); p.stop()" 2>/dev/null; then
    echo "Installing Playwright browsers..."
    python -m playwright install chromium --with-deps 2>/dev/null || \
    python -m playwright install chromium
fi

# 5. Config dir scaffold
CONFIG_DIR="${BACKLINK_PUBLISHER_CONFIG_DIR:-$HOME/.config/backlink-publisher}"
mkdir -p "$CONFIG_DIR"
if [[ ! -f "$CONFIG_DIR/config.toml" ]]; then
    echo "Creating example config at $CONFIG_DIR/config.toml"
    cp "$REPO_DIR/config.example.toml" "$CONFIG_DIR/config.toml"
fi

# 6. Credential permissions audit
echo "Checking credential file permissions..."
python "$SCRIPT_DIR/audit_credential_permissions.py" --fix || true

# 7. Run fast tests
echo "Running tests (fast subset)..."
cd "$REPO_DIR"
PYTHONHASHSEED=0 python -m pytest tests/ -x -q --timeout=30 -k "not real_" --tb=short

echo ""
echo "Done! Start WebUI with:"
echo "  source .venv/bin/activate && python webui.py"
