#!/usr/bin/env python3
"""Minify CSS and JS files in webui_app/static/ using Python stdlib only.

Usage:
    python scripts/optimize_static.py          # minify all files
    python scripts/optimize_static.py --check   # dry-run, show stats only

Output: <name>.min.<ext> alongside each source file.
"""

from __future__ import annotations

import pathlib
import re
import sys

STATIC_DIR = pathlib.Path(__file__).resolve().parent.parent / "webui_app" / "static"


def _minify_css(content: str) -> str:
    """Basic CSS minification: strip comments, whitespace, and trailing semicolons."""
    content = re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL)
    content = re.sub(r"\s+", " ", content)
    content = re.sub(r"\s*([{};,:])\s*", r"\1", content)
    content = re.sub(r";}", "}", content)
    return content.strip()


def _minify_js(content: str) -> str:
    """Basic JS minification: strip comments, extra whitespace."""
    content = re.sub(r"//[^\n]*", "", content)
    content = re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL)
    content = re.sub(r"\s+", " ", content)
    content = re.sub(r"\s*([{}();,:+\-*/=<>!])\s*", r"\1", content)
    return content.strip()


def _process_file(src: pathlib.Path, check_only: bool) -> dict[str, object]:
    """Minify a single file. Returns stats dict."""
    original_size = src.stat().st_size
    content = src.read_text(encoding="utf-8")

    ext = src.suffix.lower()
    if ext == ".css":
        minified = _minify_css(content)
    elif ext == ".js":
        minified = _minify_js(content)
    else:
        return {"skipped": True, "reason": f"unsupported extension {ext}"}

    minified_size = len(minified.encode("utf-8"))
    savings = original_size - minified_size
    pct = (savings / original_size * 100) if original_size > 0 else 0

    if not check_only:
        dst = src.with_name(src.stem + ".min" + src.suffix)
        dst.write_text(minified, encoding="utf-8")

    return {
        "file": str(src.relative_to(STATIC_DIR)),
        "original": original_size,
        "minified": minified_size,
        "savings": savings,
        "pct": round(pct, 1),
    }


def main() -> None:
    check_only = "--check" in sys.argv

    total_original = 0
    total_minified = 0
    results: list[dict[str, object]] = []

    for ext in (".css", ".js"):
        dir_path = STATIC_DIR / ("css" if ext == ".css" else "js")
        if not dir_path.exists():
            continue
        for fpath in sorted(dir_path.iterdir()):
            if fpath.suffix.lower() != ext or fpath.name.endswith(".min" + ext):
                continue
            result = _process_file(fpath, check_only)
            results.append(result)
            total_original += result.get("original", 0)
            total_minified += result.get("minified", 0)

    if not results:
        print("No static files found to optimize.", file=sys.stderr)
        return

    # Print stats
    action = "Check" if check_only else "Minified"
    print(f"{action} {len(results)} file(s):")
    print(f"{'File':<40} {'Before':>8} {'After':>8} {'Saved':>8} {'%':>6}")
    print("-" * 70)
    for r in results:
        if r.get("skipped"):
            print(f"{r['file']:<40} {'(skipped)':>22}")
        else:
            print(
                f"{r['file']:<40} {r['original']:>8} {r['minified']:>8} "
                f"{r['savings']:>8} {r['pct']:>5}%"
            )
    print("-" * 70)
    print(f"{'TOTAL':<40} {total_original:>8} {total_minified:>8} "
          f"{total_original - total_minified:>8} "
          f"{round((total_original - total_minified) / total_original * 100, 1) if total_original else 0:>5}%")


if __name__ == "__main__":
    main()
