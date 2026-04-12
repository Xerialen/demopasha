#!/usr/bin/env python3
"""Extract position timeline + kill events + item events from demos for the dashboard.

Builds phase0/data/dashboard_data.json with:
  - maps:  dict keyed by map name → {world_mins, world_maxs, topdown_image}
  - demos: list of {filename, map, hub_game_id, duration, teams, players, snapshots, kills, itemEvents}

Each snapshot position now includes flags, pitch, yaw for view-cone rendering
and weapon/powerup indicators.
"""

import glob
import json
import os
import re
import subprocess
from pathlib import Path

MIMER = os.path.expanduser("~/projects/demoparser/target/release/mimer")
DEMO_DIR = os.path.expanduser("~/projects/demoparser/data/testdemos")
DATA_DIR = Path(__file__).parent / "data"
OUT = DATA_DIR / "dashboard_data.json"

# Pick one representative demo per map (first alphabetical match).
MAPS = ["dm2", "dm3", "e1m2", "schloss", "phantombase"]


def extract_demo(demo_path):
    result = subprocess.run(
        [MIMER, demo_path, "--dump-analysis"],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        print(f"  WARN: mimer failed on {demo_path}: {result.stderr[:200]}")
        return None
    return json.loads(result.stdout)


def parse_hub_game_id(filename):
    """Extract numeric game id from filenames like `dm3_202415.mvd.gz`. Returns None if not found."""
    m = re.match(r"^\w+_(\d{5,})\.mvd", filename)
    return m.group(1) if m else None


def process_demo(demo_path, map_name):
    name = os.path.basename(demo_path)
    print(f"  {name}...")
    data = extract_demo(demo_path)
    if not data:
        return None

    pt = data.get("position_timeline", {})
    players_meta = pt.get("players", [])
    snapshots_raw = pt.get("snapshots", [])
    item_events = pt.get("item_events", [])
    static_items = pt.get("static_items", [])
    powerup_events = pt.get("powerup_events", [])

    player_lookup = {p["num"]: {"name": p["name"], "team": p["team"]} for p in players_meta}

    teams = {}
    for p in players_meta:
        teams.setdefault(p["team"], []).append(p["name"])
    team_list = [{"name": t, "players": ps} for t, ps in teams.items()]

    snapshots = []
    for snap in snapshots_raw:
        positions = {}
        for entry in snap["p"]:
            num = entry[0]
            if num not in player_lookup:
                continue
            pinfo = player_lookup[num]
            # Snapshot array: [num, x, y, z, alive, health, armor, flags, pitch_x10, yaw_x10]
            positions[pinfo["name"]] = {
                "x": entry[1], "y": entry[2], "z": entry[3],
                "alive": bool(entry[4]),
                "health": entry[5], "armor": entry[6],
                "flags": entry[7] if len(entry) > 7 else 0,
                "pitch": (entry[8] / 10.0) if len(entry) > 8 else 0.0,
                "yaw": (entry[9] / 10.0) if len(entry) > 9 else 0.0,
            }
        snapshots.append({"t": round(snap["t"], 1), "positions": positions})

    kills = []
    for k in data.get("kill_events", []):
        kills.append({
            "t": round(k["time"], 1),
            "killer": k["killer"],
            "victim": k["victim"],
            "weapon": k["weapon"],
            "killer_pos": k.get("killer_pos"),
            "victim_pos": k.get("victim_pos"),
        })

    duration = snapshots[-1]["t"] if snapshots else 0

    return {
        "filename": name,
        "map": map_name,
        "hub_game_id": parse_hub_game_id(name),
        "duration": duration,
        "teams": team_list,
        "players": [{"name": p["name"], "team": p["team"], "num": p["num"]} for p in players_meta],
        "snapshots": snapshots,
        "kills": kills,
        "itemEvents": item_events,
        "staticItems": static_items,
        "powerupEvents": powerup_events,
    }


def load_map_meta(map_name):
    """Return {world_mins, world_maxs, topdown_image} for a map, or None if meta not found."""
    meta_path = DATA_DIR / map_name / "bsp_meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
        return {
            "world_mins": meta["world_mins"],
            "world_maxs": meta["world_maxs"],
            "topdown_image": f"{map_name}/{map_name}_topdown.png",
        }
    # Fallback to the legacy top-level bsp_meta.json (single-map version)
    legacy = DATA_DIR / "bsp_meta.json"
    if legacy.exists():
        meta = json.loads(legacy.read_text())
        return {
            "world_mins": meta["world_mins"],
            "world_maxs": meta["world_maxs"],
            "topdown_image": f"{map_name}/{map_name}_topdown.png",
        }
    return {
        "world_mins": [-4096, -4096, -512],
        "world_maxs": [4096, 4096, 512],
        "topdown_image": None,
    }


def pick_demo_for_map(map_name):
    """Pick one representative demo per map, preferring short filenames."""
    patterns = [f"{DEMO_DIR}/{map_name}_*.mvd.gz", f"{DEMO_DIR}/{map_name}_*.mvd"]
    candidates = []
    for p in patterns:
        candidates.extend(glob.glob(p))
    if not candidates:
        return None
    candidates.sort(key=lambda p: (len(os.path.basename(p)), p))
    return candidates[0]


def main():
    print(f"Extracting dashboard data for {len(MAPS)} maps...")

    maps_meta = {}
    demos = []
    for map_name in MAPS:
        print(f"\n[{map_name}]")
        maps_meta[map_name] = load_map_meta(map_name)
        demo_path = pick_demo_for_map(map_name)
        if not demo_path:
            print(f"  no demo found for {map_name}")
            continue
        d = process_demo(demo_path, map_name)
        if d:
            demos.append(d)

    dashboard = {"maps": maps_meta, "demos": demos}
    OUT.write_text(json.dumps(dashboard))
    size_kb = OUT.stat().st_size / 1024
    total_snaps = sum(len(d["snapshots"]) for d in demos)
    total_events = sum(len(d["itemEvents"]) for d in demos)
    print(f"\nSaved: {OUT} ({size_kb:.0f} KB)")
    print(f"Demos: {len(demos)}, snapshots: {total_snaps}, item events: {total_events}")


if __name__ == "__main__":
    main()
