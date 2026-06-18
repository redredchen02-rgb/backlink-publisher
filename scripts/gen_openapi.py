#!/usr/bin/env python3
"""Regenerate the committed OpenAPI 3.1 spec — Plan 2026-06-18-002 U1.

Usage:
    python scripts/gen_openapi.py            # write openapi/backlink-api.yaml
    python scripts/gen_openapi.py --check     # exit 1 if committed spec is stale

CI runs ``--check`` so the spec can never silently drift from the schemas, and
oasdiff runs against the committed file to gate breaking changes.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running from a source checkout without install.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from webui_app.api.v1.spec import spec_yaml  # noqa: E402

SPEC_PATH = Path(__file__).resolve().parent.parent / "openapi" / "backlink-api.yaml"


def main(argv: list[str]) -> int:
    generated = spec_yaml()
    check = "--check" in argv
    if check:
        if not SPEC_PATH.exists():
            print(f"FAIL: {SPEC_PATH} missing — run scripts/gen_openapi.py", file=sys.stderr)
            return 1
        current = SPEC_PATH.read_text()
        if current.strip() != generated.strip():
            print(
                "FAIL: openapi/backlink-api.yaml is stale. "
                "Run `python scripts/gen_openapi.py` and commit.",
                file=sys.stderr,
            )
            return 1
        print("OK: committed OpenAPI spec matches the schemas.")
        return 0
    SPEC_PATH.parent.mkdir(parents=True, exist_ok=True)
    SPEC_PATH.write_text(generated)
    print(f"Wrote {SPEC_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
