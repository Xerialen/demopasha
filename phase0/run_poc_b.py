#!/usr/bin/env python3
"""POC-B verdict: load ray_hits.bin and report hit statistics."""

import sys
import os
import numpy as np

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
HITS_FILE = os.path.join(DATA_DIR, "ray_hits.bin")

PASS_THRESHOLD_MRAYS = 0.1  # 100K rays/sec = 0.1 M rays/sec


def main():
    if not os.path.exists(HITS_FILE):
        print(f"ERROR: {HITS_FILE} not found")
        sys.exit(1)

    hits = np.fromfile(HITS_FILE, dtype=np.float32)
    total = len(hits)
    hit_mask = hits > 0.0
    hit_count = int(np.sum(hit_mask))
    hit_rate = 100.0 * hit_count / total if total > 0 else 0.0

    print(f"=== POC-B Ray Trace Results ===")
    print(f"Total rays:  {total:,}")
    print(f"Hits:        {hit_count:,} ({hit_rate:.2f}%)")
    print(f"Misses:      {total - hit_count:,}")

    if hit_count > 0:
        hit_dists = hits[hit_mask]
        print(f"\nHit distance stats:")
        print(f"  Min:    {np.min(hit_dists):.2f}")
        print(f"  Max:    {np.max(hit_dists):.2f}")
        print(f"  Median: {np.median(hit_dists):.2f}")
        print(f"  Mean:   {np.mean(hit_dists):.2f}")
        print(f"  Std:    {np.std(hit_dists):.2f}")

    # Verdict
    print()
    if hit_count == 0:
        print("FAIL: zero hits — geometry or intersection code is broken")
        sys.exit(1)
    elif hit_rate < 1.0:
        print(f"WARN: hit rate very low ({hit_rate:.2f}%), may indicate issues")
        print("PASS (with warning)")
    else:
        print("PASS: ray tracing produced valid hits")


if __name__ == "__main__":
    main()
