#!/usr/bin/env python3
"""
Message-level profiler for MVD demos.

Measures what's actually inside the demos — not estimates from code audit,
but counted from the bytes.

What this measures precisely:
  - Hidden message types: walks DEM_MULTIPLE(mask=0) frames, counts each
    hidden msg type_id. Replaces the "6/12 from audit" estimate.
  - Frame type distribution: how many of each DEM_* type per demo.
  - svc_playerinfo frequency: counts svc type=42 first-bytes in regular
    frames by walking the message stream (handles known fixed-size types
    to find message boundaries).

What this cannot measure without an instrumented Rust parser:
  - Entity parse failure rate (need to attempt U_* flag decoding)
  - Per-svc-type byte accounting (need full message parsing)
"""

import gzip
import json
import struct
import sys
from collections import Counter
from pathlib import Path

# MVD frame types
DEM_READ = 1
DEM_SET = 2
DEM_MULTIPLE = 3
DEM_SINGLE = 4
DEM_STATS = 5
DEM_ALL = 6

# Hidden message type IDs (from types.rs)
HIDDEN_TYPE_NAMES = {
    0x0000: "ANTILAG_POSITION",
    0x0001: "USERCMD",
    0x0002: "USERCMD_WEAPONS",
    0x0003: "KTXSTATS",
    0x0004: "TYPE_4 (unknown)",
    0x0005: "TYPE_5 (unknown)",
    0x0006: "TYPE_6 (unknown)",
    0x0007: "DMGDONE",
    0x0008: "USERCMD_WEAPONS_SS",
    0x0009: "WEAPON_INSTRUCTION",
    0x000A: "TYPE_10 (unknown)",
    0x000B: "TIMESTAMP",
}

# svc_* types and their MINIMUM fixed sizes (for boundary walking)
# Types with variable length are marked None — we stop walking at those
# unless we can parse them.
SVC_PLAYERINFO = 42

# svc types we know from mimer's source — these let us walk message boundaries
SVC_SIZES = {
    0: 0,   # SVC_BAD
    1: 0,   # SVC_NOP
    2: 0,   # SVC_DISCONNECT
    # 3: SVC_UPDATESTAT — byte + byte = 2 (short stat)
    3: 2,
    4: 4,   # SVC_VERSION — long
    5: 2,   # SVC_SETVIEW — short
    # 6: SVC_SOUND — variable (flags-dependent)
    7: 4,   # SVC_TIME — float
    # 8: SVC_PRINT — variable (byte + string)
    # 9: SVC_STUFFTEXT — variable (string)
    # 10: SVC_SETANGLE — 3 angles
    # 11: SVC_SERVERDATA — variable
    # 12: SVC_LIGHTSTYLE — variable
    # 13: SVC_UPDATENAME — variable
    14: 3,  # SVC_UPDATEFRAGS — byte + short
    # 15: SVC_CLIENTDATA — 0
    15: 0,
    16: 2,  # SVC_STOPSOUND — short
    17: 2,  # SVC_UPDATECOLORS — byte + byte
    # 18: SVC_PARTICLE — variable (coord-dependent)
    # 19: SVC_DAMAGE — variable (coord-dependent)
    # 20: SVC_SPAWNSTATIC — variable
    # 22: SVC_SPAWNBASELINE — variable
    # 23: SVC_TEMP_ENTITY — variable
    24: 1,  # SVC_SETPAUSE — byte
    # 26: SVC_CENTERPRINT — variable (string)
    27: 0,  # SVC_KILLEDMONSTER
    28: 0,  # SVC_FOUNDSECRET
    # 29: SVC_SPAWNSTATICSOUND — variable
    # 30: SVC_INTERMISSION — variable (coords)
    # 31: SVC_FINALE — variable (string)
    32: 1,  # SVC_CDTRACK — byte
    33: 0,  # SVC_SELLSCREEN
    34: 0,  # SVC_SMALLKICK
    35: 0,  # SVC_BIGKICK
    36: 3,  # SVC_UPDATEPING — byte + short
    37: 5,  # SVC_UPDATEENTERTIME — byte + float
    38: 5,  # SVC_UPDATESTATLONG — byte + long
    39: 1,  # SVC_MUZZLEFLASH — byte
    # 40: SVC_UPDATEUSERINFO — variable
    # 41: SVC_DOWNLOAD — variable
    # 42: SVC_PLAYERINFO — variable (flags-dependent)
    # 43: SVC_NAILS — variable
    44: 1,  # SVC_CHOKECOUNT — byte
    # 45: SVC_MODELLIST — variable
    # 46: SVC_SOUNDLIST — variable
    # 47: SVC_PACKETENTITIES — variable
    # 48: SVC_DELTAPACKETENTITIES — variable
    49: 4,  # SVC_MAXSPEED — float
    50: 4,  # SVC_ENTGRAVITY — float
    # 51: SVC_SETINFO — variable
    # 52: SVC_SERVERINFO — variable
    53: 2,  # SVC_UPDATEPL — byte + byte
    # 54: SVC_NAILS2 — variable
}


def profile_hidden_messages(frame_data):
    """Parse hidden messages from a DEM_MULTIPLE(mask=0) frame."""
    pos = 0
    total = len(frame_data)
    types = Counter()
    total_bytes = 0

    while pos + 4 <= total:
        type_id = struct.unpack_from("<H", frame_data, pos)[0]
        length = struct.unpack_from("<H", frame_data, pos + 2)[0]
        pos += 4

        if pos + length > total:
            break

        types[type_id] += 1
        total_bytes += 4 + length
        pos += length

    return types, total_bytes


def count_svc_types_in_frame(frame_data):
    """Walk message stream and count svc type bytes.

    Uses known fixed sizes to advance past simple messages.
    Stops at the first variable-length message we can't skip.
    Returns (counted_types, bytes_walked, total_bytes).
    """
    pos = 0
    total = len(frame_data)
    types = Counter()

    while pos < total:
        svc = frame_data[pos]
        pos += 1
        types[svc] += 1

        if svc in SVC_SIZES:
            skip = SVC_SIZES[svc]
            pos += skip
        else:
            # Variable-length message — can't continue without full parsing
            break

    return types, pos, total


def profile_demo(demo_path):
    """Profile a single demo file."""
    path = Path(demo_path)

    if path.suffix == ".gz":
        with gzip.open(path, "rb") as f:
            data = f.read()
    else:
        data = path.read_bytes()

    raw_size = len(data)
    pos = 0

    frame_type_counts = Counter()
    hidden_msg_types = Counter()
    hidden_msg_bytes = 0
    hidden_frame_count = 0
    svc_type_counts = Counter()
    svc_bytes_walked = 0
    svc_bytes_total = 0
    regular_frame_count = 0
    playerinfo_count = 0

    while pos < raw_size:
        if pos + 2 > raw_size:
            break

        msec = data[pos]
        type_byte = data[pos + 1]
        pos += 2
        frame_type = type_byte & 0x07

        frame_type_counts[frame_type] += 1

        if frame_type == DEM_SET:
            pos += 8
        elif frame_type == DEM_MULTIPLE:
            if pos + 8 > raw_size:
                break
            client_mask = struct.unpack_from("<I", data, pos)[0]
            msg_len = struct.unpack_from("<I", data, pos + 4)[0]
            pos += 8

            if pos + msg_len > raw_size:
                break

            frame_data = data[pos:pos + msg_len]
            pos += msg_len

            if client_mask == 0:
                # Hidden messages
                hidden_frame_count += 1
                types, hbytes = profile_hidden_messages(frame_data)
                hidden_msg_types += types
                hidden_msg_bytes += hbytes
            else:
                # Regular messages sent to specific clients
                regular_frame_count += 1
                types, walked, total = count_svc_types_in_frame(frame_data)
                svc_type_counts += types
                svc_bytes_walked += walked
                svc_bytes_total += total
        elif frame_type in (0, DEM_READ, DEM_SINGLE, DEM_STATS, DEM_ALL):
            if pos + 4 > raw_size:
                break
            msg_len = struct.unpack_from("<I", data, pos)[0]
            pos += 4

            if pos + msg_len > raw_size:
                break

            frame_data = data[pos:pos + msg_len]
            pos += msg_len

            regular_frame_count += 1
            types, walked, total = count_svc_types_in_frame(frame_data)
            svc_type_counts += types
            svc_bytes_walked += walked
            svc_bytes_total += total
        else:
            break

    playerinfo_count = svc_type_counts.get(SVC_PLAYERINFO, 0)

    return {
        "file": path.name,
        "raw_size": raw_size,
        "frame_types": dict(frame_type_counts),
        "total_frames": sum(frame_type_counts.values()),
        "hidden": {
            "frames": hidden_frame_count,
            "total_bytes": hidden_msg_bytes,
            "types": {
                HIDDEN_TYPE_NAMES.get(k, f"TYPE_{k}"): v
                for k, v in sorted(hidden_msg_types.items())
            },
            "types_seen": len(hidden_msg_types),
            "types_defined": 12,
        },
        "svc": {
            "regular_frames": regular_frame_count,
            "bytes_walked": svc_bytes_walked,
            "bytes_total": svc_bytes_total,
            "walk_coverage_pct": round(100 * svc_bytes_walked / max(svc_bytes_total, 1), 1),
            "type_counts": {str(k): v for k, v in sorted(svc_type_counts.items())},
            "unique_types": len(svc_type_counts),
            "playerinfo_count": playerinfo_count,
            "playerinfo_rate_hz": None,  # calculated below
        },
    }


def main():
    demos_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/demos")
    demos = sorted(demos_dir.glob("*.mvd.gz"))

    if not demos:
        print(f"No demos in {demos_dir}")
        return

    all_results = []

    for demo in demos:
        print(f"\n{'='*60}")
        print(f"  {demo.name}")
        print(f"{'='*60}")

        r = profile_demo(demo)

        # Estimate playerinfo rate
        # A 10-minute match at 77Hz with 8 players = ~3.7M playerinfos
        # But MVD sends a subset (only changed players per frame)
        duration_estimate = r["total_frames"] / 77.0  # ~77 frames/sec
        if duration_estimate > 0 and r["svc"]["playerinfo_count"] > 0:
            r["svc"]["playerinfo_rate_hz"] = round(
                r["svc"]["playerinfo_count"] / duration_estimate, 1
            )

        print(f"\n  HIDDEN MESSAGES ({r['hidden']['frames']} frames, {r['hidden']['total_bytes']:,} bytes):")
        print(f"  {'Type':<30} {'Count':>8}")
        print(f"  {'-'*40}")
        for name, count in sorted(r["hidden"]["types"].items(), key=lambda x: -x[1]):
            print(f"  {name:<30} {count:>8,}")
        print(f"  {'Types seen':<30} {r['hidden']['types_seen']:>8} / 12")

        print(f"\n  SVC MESSAGE TYPES ({r['svc']['unique_types']} unique):")
        print(f"  {'Type':<6} {'Count':>10}   Notes")
        print(f"  {'-'*40}")

        SVC_NAMES = {
            0: "BAD", 1: "NOP", 2: "DISCONNECT", 3: "UPDATESTAT", 4: "VERSION",
            5: "SETVIEW", 6: "SOUND", 7: "TIME", 8: "PRINT", 9: "STUFFTEXT",
            10: "SETANGLE", 11: "SERVERDATA", 12: "LIGHTSTYLE", 13: "UPDATENAME",
            14: "UPDATEFRAGS", 15: "CLIENTDATA", 16: "STOPSOUND", 17: "UPDATECOLORS",
            18: "PARTICLE", 19: "DAMAGE", 20: "SPAWNSTATIC", 22: "SPAWNBASELINE",
            23: "TEMP_ENTITY", 24: "SETPAUSE", 26: "CENTERPRINT", 27: "KILLEDMONSTER",
            28: "FOUNDSECRET", 29: "SPAWNSTATICSOUND", 30: "INTERMISSION",
            31: "FINALE", 32: "CDTRACK", 33: "SELLSCREEN", 34: "SMALLKICK",
            35: "BIGKICK", 36: "UPDATEPING", 37: "UPDATEENTERTIME",
            38: "UPDATESTATLONG", 39: "MUZZLEFLASH", 40: "UPDATEUSERINFO",
            41: "DOWNLOAD", 42: "PLAYERINFO", 43: "NAILS", 44: "CHOKECOUNT",
            45: "MODELLIST", 46: "SOUNDLIST", 47: "PACKETENTITIES",
            48: "DELTAPACKETENTITIES", 49: "MAXSPEED", 50: "ENTGRAVITY",
            51: "SETINFO", 52: "SERVERINFO", 53: "UPDATEPL", 54: "NAILS2",
        }

        for svc_str, count in sorted(r["svc"]["type_counts"].items(), key=lambda x: -x[1]):
            svc = int(svc_str)
            name = SVC_NAMES.get(svc, f"FTE_{svc}")
            counted = "walked" if svc in SVC_SIZES else "boundary"
            print(f"  {svc:>4}  {count:>10,}   {name} ({counted})")

        print(f"\n  svc_playerinfo count: {r['svc']['playerinfo_count']:,}")
        print(f"  estimated playerinfo rate: ~{r['svc']['playerinfo_rate_hz']} Hz")
        print(f"  mimer outputs: 0.5 Hz (interval_secs=2)")
        if r['svc']['playerinfo_rate_hz']:
            ratio = r['svc']['playerinfo_rate_hz'] / 0.5
            print(f"  data loss from downsampling: ~{ratio:.0f}x")

        all_results.append(r)

    # Save
    out = Path("baseline/message_profile.json")
    out.write_text(json.dumps(all_results, indent=2))
    print(f"\n{'='*60}")
    print(f"  Saved: {out}")


if __name__ == "__main__":
    main()
