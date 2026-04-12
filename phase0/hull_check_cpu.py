#!/usr/bin/env python3
"""CPU reference implementation of SV_RecursiveHullCheck for BSP v29 point containment.

Usage:
    python hull_check_cpu.py <data_dir> <num_points>

Loads clipnodes.bin, planes.bin, bsp_meta.json from <data_dir>.
Generates <num_points> random test points within the world AABB,
runs point_contents on each, reports timing and distribution,
and saves test_points.bin + cpu_results.bin to <data_dir>.
"""

import json
import sys
import time

import numpy as np


# BSP leaf content constants
CONTENTS_EMPTY = -1
CONTENTS_SOLID = -2
CONTENTS_WATER = -3
CONTENTS_SLIME = -4
CONTENTS_LAVA = -5
CONTENTS_SKY = -6

CONTENTS_NAMES = {
    CONTENTS_EMPTY: "EMPTY",
    CONTENTS_SOLID: "SOLID",
    CONTENTS_WATER: "WATER",
    CONTENTS_SLIME: "SLIME",
    CONTENTS_LAVA: "LAVA",
    CONTENTS_SKY: "SKY",
}


def load_data(data_dir: str):
    """Load BSP collision data from binary files."""
    with open(f"{data_dir}/bsp_meta.json") as f:
        meta = json.load(f)

    planes = np.fromfile(f"{data_dir}/planes.bin", dtype=np.float32).reshape(-1, 5)
    clipnodes = np.fromfile(f"{data_dir}/clipnodes.bin", dtype=np.int32).reshape(-1, 4)

    assert planes.shape[0] == meta["n_planes"], (
        f"plane count mismatch: {planes.shape[0]} vs {meta['n_planes']}"
    )
    assert clipnodes.shape[0] == meta["n_clipnodes"], (
        f"clipnode count mismatch: {clipnodes.shape[0]} vs {meta['n_clipnodes']}"
    )

    return meta, planes, clipnodes


def point_contents(hull_start: int, planes: np.ndarray, clipnodes: np.ndarray,
                   point: tuple[float, float, float]) -> int:
    """Walk the clipnode BSP tree to determine point contents.

    This mirrors Quake's SV_RecursiveHullCheck for a single-point query
    (no segment tracing, just leaf classification).

    Args:
        hull_start: Root clipnode index (hull 1 for player-sized hull).
        planes: (N, 5) float32 array — [nx, ny, nz, dist, type].
        clipnodes: (M, 4) int32 array — [planenum, child_front, child_back, pad].
        point: (x, y, z) test point.

    Returns:
        Leaf contents value (CONTENTS_EMPTY, CONTENTS_SOLID, etc.).
    """
    node = hull_start
    px, py, pz = point

    while node >= 0:
        cn = clipnodes[node]
        planenum = cn[0]
        plane = planes[planenum]
        plane_type = int(plane[4])

        # Axial planes: just compare the relevant coordinate against dist
        if plane_type == 0:
            d = px - plane[3]
        elif plane_type == 1:
            d = py - plane[3]
        elif plane_type == 2:
            d = pz - plane[3]
        else:
            # General plane: dot product
            d = plane[0] * px + plane[1] * py + plane[2] * pz - plane[3]

        if d >= 0:
            node = cn[1]  # front child
        else:
            node = cn[2]  # back child

    return node  # negative value = leaf contents


def point_contents_batch(hull_start: int, planes: np.ndarray, clipnodes: np.ndarray,
                         points: np.ndarray) -> np.ndarray:
    """Batch point_contents over an array of points.

    Args:
        hull_start: Root clipnode index.
        planes: (N, 5) float32 array.
        clipnodes: (M, 4) int32 array.
        points: (K, 3) float32 array of test points.

    Returns:
        (K,) int32 array of leaf contents.
    """
    results = np.empty(len(points), dtype=np.int32)
    for i in range(len(points)):
        results[i] = point_contents(hull_start, planes, clipnodes,
                                    (points[i, 0], points[i, 1], points[i, 2]))
    return results


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <data_dir> <num_points>", file=sys.stderr)
        sys.exit(1)

    data_dir = sys.argv[1]
    num_points = int(sys.argv[2])

    print(f"Loading BSP data from {data_dir}/...")
    meta, planes, clipnodes = load_data(data_dir)

    hull_start = meta["hull1_start"]
    world_mins = np.array(meta["world_mins"], dtype=np.float32)
    world_maxs = np.array(meta["world_maxs"], dtype=np.float32)

    print(f"  Planes: {planes.shape[0]}, Clipnodes: {clipnodes.shape[0]}")
    print(f"  Hull 1 root: {hull_start}")
    print(f"  World AABB: [{world_mins[0]:.0f}, {world_mins[1]:.0f}, {world_mins[2]:.0f}]"
          f" -> [{world_maxs[0]:.0f}, {world_maxs[1]:.0f}, {world_maxs[2]:.0f}]")

    # ── Sanity checks ──────────────────────────────────────────────────
    print("\nSanity checks:")

    center = (world_mins + world_maxs) / 2.0
    center_contents = point_contents(hull_start, planes, clipnodes,
                                     (float(center[0]), float(center[1]), float(center[2])))
    print(f"  Map center ({center[0]:.0f}, {center[1]:.0f}, {center[2]:.0f})"
          f" -> {CONTENTS_NAMES.get(center_contents, center_contents)}"
          f" (expected EMPTY={CONTENTS_EMPTY})")
    assert center_contents == CONTENTS_EMPTY, (
        f"Map center should be EMPTY, got {center_contents}"
    )

    outside = world_maxs + np.array([1000.0, 1000.0, 1000.0], dtype=np.float32)
    outside_contents = point_contents(hull_start, planes, clipnodes,
                                      (float(outside[0]), float(outside[1]), float(outside[2])))
    print(f"  Outside point ({outside[0]:.0f}, {outside[1]:.0f}, {outside[2]:.0f})"
          f" -> {CONTENTS_NAMES.get(outside_contents, outside_contents)}"
          f" (expected SOLID={CONTENTS_SOLID})")
    assert outside_contents == CONTENTS_SOLID, (
        f"Outside point should be SOLID, got {outside_contents}"
    )

    print("  Both sanity checks PASSED.")

    # ── Generate random test points ────────────────────────────────────
    print(f"\nGenerating {num_points:,} random points (seed=42) within world AABB...")
    rng = np.random.default_rng(seed=42)
    points = np.empty((num_points, 3), dtype=np.float32)
    for axis in range(3):
        points[:, axis] = rng.uniform(world_mins[axis], world_maxs[axis], size=num_points).astype(np.float32)

    # ── Run point_contents on all points ───────────────────────────────
    print(f"Running point_contents on {num_points:,} points...")
    t0 = time.perf_counter()
    results = point_contents_batch(hull_start, planes, clipnodes, points)
    elapsed = time.perf_counter() - t0

    qps = num_points / elapsed
    print(f"\n  Time: {elapsed:.3f}s")
    print(f"  Queries/sec: {qps:,.0f}")

    # ── Report distribution ────────────────────────────────────────────
    print(f"\n  Contents distribution:")
    unique, counts = np.unique(results, return_counts=True)
    n_solid = 0
    n_empty = 0
    n_other = 0
    for val, cnt in zip(unique, counts):
        name = CONTENTS_NAMES.get(int(val), f"UNKNOWN({val})")
        pct = 100.0 * cnt / num_points
        print(f"    {name:>8s}: {cnt:>10,} ({pct:5.1f}%)")
        if val == CONTENTS_SOLID:
            n_solid = int(cnt)
        elif val == CONTENTS_EMPTY:
            n_empty = int(cnt)
        else:
            n_other += int(cnt)

    print(f"\n  Summary: {n_solid:,} solid, {n_empty:,} empty, {n_other:,} water/other")

    # ── Save outputs ───────────────────────────────────────────────────
    points_path = f"{data_dir}/test_points.bin"
    results_path = f"{data_dir}/cpu_results.bin"

    points.tofile(points_path)
    results.tofile(results_path)

    print(f"\n  Saved: {points_path} ({points.nbytes:,} bytes, float32x3)")
    print(f"  Saved: {results_path} ({results.nbytes:,} bytes, int32)")


if __name__ == "__main__":
    main()
