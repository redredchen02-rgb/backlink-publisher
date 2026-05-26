#!/usr/bin/env python3
import sys, subprocess, toml

def load_budget():
    with open('monolith_budget.toml', 'r') as f:
        return toml.load(f)

def measure_sloc(path):
    out = subprocess.check_output(['radon', 'raw', '-s', path], text=True)
    # radon raw output example: "    123    45    67    89 filename"
    # We want the second number? Actually radon raw -s prints lines with multiple numbers. We need SLOC count which is the second column? Let's parse simply.
    # Safer: use radon raw -j to get JSON
    return None

if __name__ == '__main__':
    budget = load_budget()
    failures = []
    for file, meta in budget['files'].items():
        # Get SLOC via radon raw JSON
        try:
            out = subprocess.check_output(['radon', 'raw', '-j', file], text=True)
            import json
            data = json.loads(out)
            sloc = data[file]['sloc']
            ceiling = meta['ceiling']
            if sloc > ceiling:
                failures.append(f"{file}: SLOC={sloc} > ceiling={ceiling}")
        except Exception as e:
            failures.append(f"{file}: error {e}")
    if failures:
        print("Monolith budget violations:")
        for f in failures:
            print(f"- {f}")
        sys.exit(1)
    else:
        print("All files within monolith budget.")
        sys.exit(0)
