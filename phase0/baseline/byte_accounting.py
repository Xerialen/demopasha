#!/usr/bin/env python3
"""
Measure byte-level accounting for MVD demo files.
Walks the MVD frame structure and counts how many bytes are consumed
by recognized frames vs how many are left over / unaccounted.
"""

import gzip
import json
import struct
import sys
from pathlib import Path

# MVD frame types (lower 3 bits of type byte)
DEM_READ = 1
DEM_SET = 2
DEM_MULTIPLE = 3
DEM_SINGLE = 4
DEM_STATS = 5
DEM_ALL = 6

FRAME_NAMES = {
    DEM_READ: "dem_read",
    DEM_SET: "dem_set",
    DEM_MULTIPLE: "dem_multiple",
    DEM_SINGLE: "dem_single",
    DEM_STATS: "dem_stats",
    DEM_ALL: "dem_all",
}


def walk_mvd(data):
    """Walk MVD frame structure, return byte accounting stats."""
    pos = 0
    total = len(data)
    frames = 0
    frame_bytes = 0
    frame_type_counts = {}
    errors = []

    while pos < total:
        frame_start = pos

        # Need at least 2 bytes for msec + type
        if pos + 2 > total:
            errors.append(f"Truncated at {pos}: need 2 bytes for frame header, have {total - pos}")
            break

        msec = data[pos]
        type_byte = data[pos + 1]
        pos += 2

        frame_type = type_byte & 0x07

        if frame_type == DEM_SET:
            # DEM_SET: 8 bytes payload (two int32: last_incoming, last_outgoing)
            if pos + 8 > total:
                errors.append(f"Truncated DEM_SET at {pos}")
                break
            pos += 8
        elif frame_type == DEM_MULTIPLE:
            # DEM_MULTIPLE: u32 client_mask + u32 msg_len + payload
            if pos + 8 > total:
                errors.append(f"Truncated DEM_MULTIPLE at {pos}")
                break
            _client_mask = struct.unpack_from("<I", data, pos)[0]
            msg_len = struct.unpack_from("<I", data, pos + 4)[0]
            pos += 8
            if pos + msg_len > total:
                errors.append(f"Truncated DEM_MULTIPLE payload at {pos}: need {msg_len}, have {total - pos}")
                break
            pos += msg_len
        elif frame_type in (0, DEM_READ, DEM_SINGLE, DEM_STATS, DEM_ALL):
            # All length-prefixed frames: u32 msg_len + payload
            # Type 0 is handled by mimer's fallback path (read length + skip)
            if pos + 4 > total:
                errors.append(f"Truncated frame header at {pos}: need length")
                break
            msg_len = struct.unpack_from("<I", data, pos)[0]
            pos += 4
            if pos + msg_len > total:
                errors.append(f"Truncated payload at {pos}: need {msg_len}, have {total - pos}")
                break
            pos += msg_len
        else:
            errors.append(f"Unknown frame type {frame_type} at offset {frame_start}")
            break

        frame_bytes += (pos - frame_start)
        frames += 1
        name = FRAME_NAMES.get(frame_type, f"unknown_{frame_type}")
        frame_type_counts[name] = frame_type_counts.get(name, 0) + 1

    return {
        "total_bytes": total,
        "bytes_consumed": frame_bytes,
        "bytes_remaining": total - pos,
        "coverage_pct": round(100 * frame_bytes / max(total, 1), 4),
        "frames": frames,
        "frame_types": frame_type_counts,
        "errors": errors,
    }


def analyze_demo(demo_path):
    path = Path(demo_path)
    compressed_size = path.stat().st_size

    if path.suffix == ".gz":
        with gzip.open(path, "rb") as f:
            data = f.read()
    else:
        data = path.read_bytes()

    raw_size = len(data)
    result = walk_mvd(data)
    result["file"] = path.name
    result["compressed_size"] = compressed_size
    result["raw_size"] = raw_size
    return result


def main():
    demos_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/demos")
    demos = sorted(demos_dir.glob("*.mvd.gz"))

    if not demos:
        print(f"No .mvd.gz files found in {demos_dir}")
        return

    print(f"{'Demo':<35} {'Raw':>10} {'Parsed':>10} {'Coverage':>10} {'Frames':>8} {'Errors':>6}")
    print("-" * 85)

    all_results = []
    for demo in demos:
        r = analyze_demo(demo)
        all_results.append(r)
        err_str = str(len(r["errors"])) if r["errors"] else "0"
        print(f"{r['file']:<35} {r['raw_size']:>10,} {r['bytes_consumed']:>10,} {r['coverage_pct']:>9.2f}% {r['frames']:>8,} {err_str:>6}")
        if r["errors"]:
            for e in r["errors"][:3]:
                print(f"  ERROR: {e}")

    # Summary
    total_raw = sum(r["raw_size"] for r in all_results)
    total_parsed = sum(r["bytes_consumed"] for r in all_results)
    total_errors = sum(len(r["errors"]) for r in all_results)
    overall_pct = round(100 * total_parsed / max(total_raw, 1), 4)

    print("-" * 85)
    print(f"{'TOTAL':<35} {total_raw:>10,} {total_parsed:>10,} {overall_pct:>9.2f}% {sum(r['frames'] for r in all_results):>8,} {total_errors:>6}")

    # Save results
    out = Path("baseline/byte_accounting.json")
    out.write_text(json.dumps(all_results, indent=2))
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
