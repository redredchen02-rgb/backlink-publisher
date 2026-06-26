#!/usr/bin/env bash
# weights weekly optimization — invoked by com.dex.bp-weights launchd plist.
# Runs Sunday 07:00: collect signals then optimize weights.
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd -P)
BP_DIR=$(cd "$SCRIPT_DIR/.." && pwd -P)

"$BP_DIR/.venv/bin/weights" collect
"$BP_DIR/.venv/bin/weights" optimize
