#!/usr/bin/env python3
"""
run_poc_a.py — Compare GPU clipnode walk results against CPU reference.

Loads data/cpu_results.bin and data/gpu_results.bin (both int32 arrays),
compares element-by-element, and reports match rate and any mismatches.
"""

import numpy as np
import sys
import os

def main():
    cpu_path = "data/cpu_results.bin"
    gpu_path = "data/gpu_results.bin"

    if not os.path.exists(cpu_path):
        print(f"ERROR: {cpu_path} not found")
        sys.exit(1)
    if not os.path.exists(gpu_path):
        print(f"ERROR: {gpu_path} not found")
        sys.exit(1)

    cpu = np.fromfile(cpu_path, dtype=np.int32)
    gpu = np.fromfile(gpu_path, dtype=np.int32)

    if len(cpu) != len(gpu):
        print(f"ERROR: size mismatch — CPU has {len(cpu)} entries, GPU has {len(gpu)}")
        sys.exit(1)

    n = len(cpu)
    diffs = np.where(cpu != gpu)[0]
    n_diffs = len(diffs)
    match_rate = (n - n_diffs) / n * 100.0

    print(f"Total points:  {n:,}")
    print(f"Differences:   {n_diffs:,}")
    print(f"Match rate:    {match_rate:.4f}%")

    if n_diffs > 0:
        print(f"\nFirst {min(10, n_diffs)} mismatches:")
        print(f"  {'Index':>10}  {'CPU':>8}  {'GPU':>8}")
        for i in diffs[:10]:
            print(f"  {i:>10}  {cpu[i]:>8}  {gpu[i]:>8}")
    else:
        print("\nPERFECT MATCH — GPU results identical to CPU reference.")

if __name__ == "__main__":
    main()
