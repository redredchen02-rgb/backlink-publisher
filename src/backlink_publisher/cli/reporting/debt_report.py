"""debt-report — read debt_registry.toml and emit JSONL summary on stdout.

Single-file script, no engine subpackage. Reads debt_registry.toml at repo root
and emits each item as a JSONL row on stdout. stderr = diagnostics, exit 0 always
(advisory — debt is never a blocking signal)."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tomllib

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEBT_FILE = _REPO_ROOT / "debt_registry.toml"


def main() -> None:
    if not _DEBT_FILE.exists():
        print(f"debt-report: {_DEBT_FILE} not found — no debt tracked", file=sys.stderr)
        raise SystemExit(0)

    registry = tomllib.loads(_DEBT_FILE.read_text(encoding="utf-8"))
    items = registry.get("items", [])
    open_count = sum(1 for i in items if i.get("status") == "open")
    print(f"debt-report: {len(items)} items ({open_count} open)", file=sys.stderr)

    for item in items:
        sys.stdout.write(json.dumps(item, ensure_ascii=False, sort_keys=True))
        sys.stdout.write("\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
