#!/usr/bin/env python3
"""Extract dashboard data from 4 hub demos (one per map)."""

import json
import os
import subprocess
from pathlib import Path

MIMER = os.path.expanduser("~/projects/demoparser/target/release/mimer")
DATA = Path(os.path.expanduser("~/projects/demopasha/phase0/data"))

DEMOS = [
    {"file": "demos/dm3_202415.mvd.gz", "map": "dm3", "hub_game_id": 202415},
    {"file": "demos/dm2_204035.mvd.gz", "map": "dm2", "hub_game_id": 204035},
    {"file": "demos/schloss_199321.mvd.gz", "map": "schloss", "hub_game_id": 199321},
    {"file": "demos/e1m2_189809.mvd.gz", "map": "e1m2", "hub_game_id": 189809},
]


def process_demo(demo_info):
    demo_path = DATA / demo_info["file"]
    map_name = demo_info["map"]
    print(f"  {map_name} (gameId={demo_info['hub_game_id']})...")

    result = subprocess.run(
        [MIMER, str(demo_path), "--dump-analysis"],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        print(f"    WARN: mimer failed: {result.stderr[:200]}")
        return None

    data = json.loads(result.stdout)
    pt = data.get("position_timeline", {})
    players_meta = pt.get("players", [])
    snapshots_raw = pt.get("snapshots", [])

    player_lookup = {}
    for p in players_meta:
        player_lookup[p["num"]] = {"name": p["name"], "team": p["team"]}

    teams = {}
    for p in players_meta:
        t = p["team"]
        if t not in teams:
            teams[t] = []
        teams[t].append(p["name"])

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
    print(f"    {len(snapshots)} snapshots, {len(kills)} kills, {len(players_meta)} players")

    return {
        "filename": os.path.basename(str(demo_path)),
        "map": map_name,
        "hub_game_id": demo_info["hub_game_id"],
        "duration": duration,
        "teams": [{"name": t, "players": ps} for t, ps in teams.items()],
        "players": [{"name": p["name"], "team": p["team"], "num": p["num"]} for p in players_meta],
        "snapshots": snapshots,
        "kills": kills,
    }


def main():
    print("Extracting hub demos...")
    results = []
    map_meta = {}

    for demo_info in DEMOS:
        d = process_demo(demo_info)
        if d:
            results.append(d)
            # Load map metadata
            map_dir = DATA / demo_info["map"]
            meta = json.loads((map_dir / "bsp_meta.json").read_text())
            map_meta[demo_info["map"]] = {
                "world_mins": meta["world_mins"],
                "world_maxs": meta["world_maxs"],
                "topdown_image": f"{demo_info['map']}/{demo_info['map']}_topdown.png",
            }

    dashboard = {
        "maps": map_meta,
        "demos": results,
    }

    out = DATA / "dashboard_data.json"
    out.write_text(json.dumps(dashboard))
    print(f"\nSaved: {out} ({out.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
