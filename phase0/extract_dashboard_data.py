#!/usr/bin/env python3
"""Extract position timeline + kill events from demos for the dashboard."""

import glob
import json
import os
import subprocess
import sys
from pathlib import Path

MIMER = os.path.expanduser("~/projects/demoparser/target/release/mimer")
DEMO_DIR = os.path.expanduser("~/projects/demoparser/data/testdemos")
OUT = Path(os.path.expanduser("~/projects/demopasha/phase0/data/dashboard_data.json"))


def extract_demo(demo_path):
    result = subprocess.run(
        [MIMER, demo_path, "--dump-analysis"],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        print(f"  WARN: mimer failed on {demo_path}")
        return None
    return json.loads(result.stdout)


def process_demo(demo_path):
    name = os.path.basename(demo_path)
    print(f"  {name}...")
    data = extract_demo(demo_path)
    if not data:
        return None

    pt = data.get("position_timeline", {})
    players_meta = pt.get("players", [])
    snapshots_raw = pt.get("snapshots", [])

    # Build player lookup: num -> {name, team}
    player_lookup = {}
    for p in players_meta:
        player_lookup[p["num"]] = {"name": p["name"], "team": p["team"]}

    # Group players by team
    teams = {}
    for p in players_meta:
        t = p["team"]
        if t not in teams:
            teams[t] = []
        teams[t].append(p["name"])

    team_list = [{"name": t, "players": ps} for t, ps in teams.items()]

    # Process snapshots
    snapshots = []
    for snap in snapshots_raw:
        t = snap["t"]
        positions = {}
        for entry in snap["p"]:
            num = entry[0]
            if num not in player_lookup:
                continue
            pinfo = player_lookup[num]
            positions[pinfo["name"]] = {
                "x": entry[1], "y": entry[2], "z": entry[3],
                "alive": bool(entry[4]),
                "health": entry[5], "armor": entry[6],
            }
        snapshots.append({"t": round(t, 1), "positions": positions})

    # Process kill events
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
        "duration": duration,
        "teams": team_list,
        "players": [{"name": p["name"], "team": p["team"], "num": p["num"]} for p in players_meta],
        "snapshots": snapshots,
        "kills": kills,
    }


def main():
    demos = sorted(glob.glob(f"{DEMO_DIR}/dm3_*.mvd.gz"))[:5]
    print(f"Extracting {len(demos)} demos...")

    bsp_meta = json.loads(
        (Path(__file__).parent / "data" / "bsp_meta.json").read_text()
    )

    results = []
    for demo in demos:
        d = process_demo(demo)
        if d:
            results.append(d)

    dashboard = {
        "map": "dm3",
        "world_mins": bsp_meta["world_mins"],
        "world_maxs": bsp_meta["world_maxs"],
        "demos": results,
    }

    OUT.write_text(json.dumps(dashboard))
    size_kb = OUT.stat().st_size / 1024
    print(f"\nSaved: {OUT} ({size_kb:.0f} KB)")
    print(f"Demos: {len(results)}, total snapshots: {sum(len(d['snapshots']) for d in results)}")


if __name__ == "__main__":
    main()
