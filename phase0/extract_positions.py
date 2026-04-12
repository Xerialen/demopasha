#!/usr/bin/env python3
"""Extract player positions from dm3 demos using the mimer binary.

Runs mimer --dump-analysis on the first 10 dm3 demos, extracts all player
positions from position_timeline snapshots, and saves them as a compact
float32 binary file plus a JSON metadata sidecar.

Output:
    data/demo_positions.bin       — flat float32 array: [x, y, z] x N
    data/demo_positions_meta.json — {n_positions, n_demos, demos}
"""

import json
import os
import struct
import subprocess
import sys
from glob import glob
from pathlib import Path

MIMER_BIN = os.path.expanduser("~/projects/demoparser/target/release/mimer")
DEMO_DIR = os.path.expanduser("~/projects/demoparser/data/testdemos")
OUTPUT_DIR = Path(__file__).resolve().parent / "data"

N_DEMOS = 10


def find_demos():
    """Return sorted list of first N_DEMOS dm3 demo paths."""
    pattern = os.path.join(DEMO_DIR, "dm3_*.mvd.gz")
    demos = sorted(glob(pattern))
    if len(demos) < N_DEMOS:
        print(f"WARNING: found only {len(demos)} dm3 demos, expected {N_DEMOS}")
    return demos[:N_DEMOS]


def run_mimer(demo_path):
    """Run mimer --dump-analysis and return parsed JSON, or None on failure."""
    try:
        result = subprocess.run(
            [MIMER_BIN, demo_path, "--dump-analysis"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            print(f"  WARNING: mimer exited {result.returncode} for {os.path.basename(demo_path)}")
            if result.stderr:
                print(f"    stderr: {result.stderr[:200]}")
            return None
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        print(f"  WARNING: mimer timed out for {os.path.basename(demo_path)}")
        return None
    except json.JSONDecodeError as e:
        print(f"  WARNING: invalid JSON from mimer for {os.path.basename(demo_path)}: {e}")
        return None
    except Exception as e:
        print(f"  WARNING: unexpected error for {os.path.basename(demo_path)}: {e}")
        return None


def extract_positions(analysis):
    """Extract (x, y, z) tuples from position_timeline snapshots.

    Format: position_timeline.snapshots is a list of {t, p} where p is
    a list of [num, x, y, z, alive, health, armor, flags] per player.
    """
    positions = []
    pt = analysis.get("position_timeline")
    if pt is None:
        return positions

    snapshots = pt.get("snapshots", [])
    for snap in snapshots:
        for entry in snap.get("p", []):
            # entry: [num, x, y, z, alive, health, armor, flags]
            if len(entry) >= 4:
                x, y, z = entry[1], entry[2], entry[3]
                positions.append((float(x), float(y), float(z)))
    return positions


def main():
    if not os.path.isfile(MIMER_BIN):
        print(f"ERROR: mimer binary not found at {MIMER_BIN}")
        sys.exit(1)

    demos = find_demos()
    if not demos:
        print("ERROR: no dm3 demos found")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    all_positions = []
    meta_demos = []
    total = 0

    for i, demo_path in enumerate(demos):
        name = os.path.basename(demo_path)
        print(f"[{i+1}/{len(demos)}] {name} ... ", end="", flush=True)

        analysis = run_mimer(demo_path)
        if analysis is None:
            print("SKIPPED")
            continue

        positions = extract_positions(analysis)
        count = len(positions)
        total += count
        all_positions.extend(positions)
        meta_demos.append(name)
        print(f"{count} positions")

    print(f"\nTotal: {total} positions from {len(meta_demos)} demos")

    # Write binary: flat float32 array [x, y, z, x, y, z, ...]
    bin_path = OUTPUT_DIR / "demo_positions.bin"
    with open(bin_path, "wb") as f:
        for x, y, z in all_positions:
            f.write(struct.pack("<fff", x, y, z))

    bin_size = os.path.getsize(bin_path)
    print(f"Wrote {bin_path} ({bin_size:,} bytes, {total} positions)")

    # Write metadata
    meta_path = OUTPUT_DIR / "demo_positions_meta.json"
    meta = {
        "n_positions": total,
        "n_demos": len(meta_demos),
        "demos": meta_demos,
    }
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"Wrote {meta_path}")


if __name__ == "__main__":
    main()
