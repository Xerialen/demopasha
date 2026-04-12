#!/usr/bin/env python3
"""
Capture a quantitative baseline of what mimer extracts from each demo.
Produces a scorecard per demo + an aggregate summary.

Run against the same demos later with demopasha to measure improvement.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

MIMER = os.path.expanduser("~/projects/demoparser/target/release/mimer")
DEMOS_DIR = Path(os.path.expanduser("~/projects/demopasha/phase0/data/demos"))
OUT_DIR = Path(os.path.expanduser("~/projects/demopasha/phase0/baseline"))

DEMOS = [
    {"file": "dm3_202415.mvd.gz", "map": "dm3", "hub_game_id": 202415},
    {"file": "dm2_204035.mvd.gz", "map": "dm2", "hub_game_id": 204035},
    {"file": "schloss_199321.mvd.gz", "map": "schloss", "hub_game_id": 199321},
    {"file": "e1m2_189809.mvd.gz", "map": "e1m2", "hub_game_id": 189809},
    {"file": "193240.mvd.gz", "map": "phantombase", "hub_game_id": 193240},
]

# From the 2026-04-11 audit: these are the known capabilities and gaps
KNOWN_HIDDEN_MSG_TYPES_PARSED = [0, 1, 2, 3, 7, 8]
KNOWN_HIDDEN_MSG_TYPES_SKIPPED = [4, 5, 6, 9, 10, 11]
TOTAL_BSP_LUMPS = 15
TOTAL_STAT_INDICES = 32
MIMER_STAT_INDICES_TRACKED = 4  # STAT_ITEMS, STAT_HEALTH, STAT_ARMOR, STAT_ACTIVEWEAPON

KTXSTATS_ALL_FIELDS = [
    "frags", "deaths", "suicides", "teamkills",
    "damage_given", "damage_taken", "damage_team",
    "ewep", "ewep_pct", "spawn_frags", "speed_avg",
    "rl_accuracy", "lg_accuracy",
    "xfer_rl", "xfer_lg",
    # Fields KTXstats has but mimer might not extract:
    "top_weapon", "spree_max", "spree_quad",
    "control_pct", "avg_alive_time",
]


def get_file_size(path):
    return os.path.getsize(path)


def run_mimer(demo_path, flag):
    result = subprocess.run(
        [MIMER, str(demo_path), flag],
        capture_output=True, text=True, timeout=120,
    )
    return result.stdout, result.stderr, result.returncode


def score_demo(demo_info):
    demo_path = DEMOS_DIR / demo_info["file"]
    map_name = demo_info["map"]

    file_size = get_file_size(demo_path)

    # Get full analysis JSON
    stdout, stderr, rc = run_mimer(demo_path, "--dump-analysis")
    if rc != 0:
        return {"error": f"mimer failed: {stderr[:200]}", "file": demo_info["file"]}

    analysis = json.loads(stdout)

    # --- Byte accounting ---
    # Mimer does NOT report bytes_parsed/bytes_total. This is a known gap.
    byte_accounting = {
        "file_size_bytes": file_size,
        "bytes_parsed": None,  # UNKNOWN — mimer doesn't report this
        "bytes_unknown": None,  # UNKNOWN
        "coverage_pct": None,  # UNKNOWN
        "status": "NOT_TRACKED",
    }

    # --- Message type coverage ---
    # Mimer doesn't report which svc_* types it parsed per demo.
    # From the audit: it handles ~30 of ~40 defined svc types, but we can't
    # measure this per-demo without instrumenting the parser.
    msg_coverage = {
        "svc_types_defined": 40,  # approximate from types.rs
        "svc_types_parsed": None,  # UNKNOWN per-demo
        "svc_types_skipped": None,
        "status": "NOT_TRACKED",
    }

    # --- Hidden message coverage ---
    hidden_coverage = {
        "types_defined": 12,
        "types_parsed": len(KNOWN_HIDDEN_MSG_TYPES_PARSED),
        "types_skipped": len(KNOWN_HIDDEN_MSG_TYPES_SKIPPED),
        "parsed_list": KNOWN_HIDDEN_MSG_TYPES_PARSED,
        "skipped_list": KNOWN_HIDDEN_MSG_TYPES_SKIPPED,
        "coverage_pct": round(100 * len(KNOWN_HIDDEN_MSG_TYPES_PARSED) / 12, 1),
        "status": "PARTIAL",
    }

    # --- Entity tracking ---
    dq = analysis.get("data_quality", {})
    entity_tracking = {
        "entities_tracked": dq.get("entities_tracked", 0),
        "models_tracked": len(dq.get("models", [])),
        "failure_rate_pct": 3.5,  # from audit, not measurable per-demo
        "failure_count": None,  # UNKNOWN — not reported
        "status": "PARTIAL",
    }

    # --- Position timeline ---
    pt = analysis.get("position_timeline", {})
    snapshots = pt.get("snapshots", [])
    interval = pt.get("interval_secs", 2)
    duration = analysis.get("duration_secs", 0)

    # Count non-zero positions per snapshot
    total_positions = 0
    zero_positions = 0
    for snap in snapshots:
        for entry in snap.get("p", []):
            total_positions += 1
            if entry[1] == 0 and entry[2] == 0 and entry[3] == 0:
                zero_positions += 1

    position_timeline = {
        "sample_rate_hz": round(1.0 / interval, 2) if interval > 0 else 0,
        "total_snapshots": len(snapshots),
        "total_positions": total_positions,
        "zero_origin_positions": zero_positions,
        "zero_origin_pct": round(100 * zero_positions / max(total_positions, 1), 1),
        "duration_secs": round(duration, 1),
        "theoretical_max_hz": "77 (server tickrate)",
        "status": "DOWNSAMPLED",  # 0.5 Hz vs 77 Hz theoretical
    }

    # --- Stat tracking ---
    stat_tracking = {
        "indices_tracked": MIMER_STAT_INDICES_TRACKED,
        "indices_total": TOTAL_STAT_INDICES,
        "coverage_pct": round(100 * MIMER_STAT_INDICES_TRACKED / TOTAL_STAT_INDICES, 1),
        "tracked_list": ["STAT_ITEMS", "STAT_HEALTH", "STAT_ARMOR", "STAT_ACTIVEWEAPON"],
        "stat_transitions": dq.get("stat_transitions", 0),
        "status": "PARTIAL",
    }

    # --- KTXstats cross-check ---
    ks = analysis.get("ktxstats_summary", {})
    ks_players = ks.get("players", [])
    extracted_fields = set()
    if ks_players:
        extracted_fields = set(ks_players[0].keys()) - {"name"}

    ktxstats = {
        "players_with_stats": len(ks_players),
        "fields_extracted": sorted(extracted_fields),
        "fields_count": len(extracted_fields),
        "fields_possible": len(KTXSTATS_ALL_FIELDS),
        "coverage_pct": round(100 * len(extracted_fields) / max(len(KTXSTATS_ALL_FIELDS), 1), 1),
        "cross_check_frags": None,  # mimer checks frags/deaths but doesn't report pass/fail
        "cross_check_deaths": None,
        "status": "PARTIAL",
    }

    # --- BSP coverage ---
    bsp_coverage = {
        "lumps_total": TOTAL_BSP_LUMPS,
        "lumps_parsed": 1,  # only entity lump
        "lumps_parsed_list": ["entities (partial: 17 classnames)"],
        "coverage_pct": round(100 * 1 / TOTAL_BSP_LUMPS, 1),
        "classnames_extracted": 17,
        "spatial_queries": "500-unit proximity heuristic, 1Hz, no wall awareness",
        "status": "MINIMAL",
    }

    # --- Loc coverage ---
    loc_path = Path(os.path.expanduser(f"~/quake/qw/locs/{map_name}.loc"))
    loc_coverage = {
        "loc_file_exists": loc_path.exists(),
        "loc_lines": None,
        "malformed_handling": "silent_skip",
        "bsp_cross_check": False,
        "status": "NOT_VALIDATED" if loc_path.exists() else "MISSING",
    }
    if loc_path.exists():
        lines = loc_path.read_text().strip().split("\n")
        loc_coverage["loc_lines"] = len(lines)

    # --- Player data richness ---
    players = analysis.get("players", [])
    player_fields = set()
    if players:
        player_fields = set(players[0].keys())

    player_data = {
        "player_count": len(players),
        "fields_per_player": sorted(player_fields),
        "fields_count": len(player_fields),
    }

    # --- Kill events ---
    kills = analysis.get("kill_events", [])
    kill_fields = set()
    if kills:
        kill_fields = set(kills[0].keys())

    kill_data = {
        "kill_count": len(kills),
        "fields_per_kill": sorted(kill_fields),
        "fields_count": len(kill_fields),
        "unknown_weapon_count": sum(1 for k in kills if k.get("weapon") == "unknown"),
        "unknown_weapon_pct": round(
            100 * sum(1 for k in kills if k.get("weapon") == "unknown") / max(len(kills), 1), 1
        ),
    }

    # --- Cross-validation witnesses ---
    cross_validation = {
        "independent_parsers": 1,  # only mimer itself
        "ktxstats_cross_check": "partial (frags, deaths only)",
        "roundtrip_test": False,
        "visual_validation": False,
        "gpu_spatial_validation": False,
        "status": "MINIMAL",
    }

    # --- Aggregate score ---
    # Simple composite: average of the coverage percentages we can measure
    measurable_coverages = [
        hidden_coverage["coverage_pct"],
        stat_tracking["coverage_pct"],
        ktxstats["coverage_pct"],
        bsp_coverage["coverage_pct"],
    ]
    aggregate_score = round(sum(measurable_coverages) / len(measurable_coverages), 1)

    return {
        "file": demo_info["file"],
        "map": map_name,
        "hub_game_id": demo_info["hub_game_id"],
        "parser": "mimer",
        "parser_version": "Phase 4B (2026-04-11)",
        "byte_accounting": byte_accounting,
        "message_coverage": msg_coverage,
        "hidden_message_coverage": hidden_coverage,
        "entity_tracking": entity_tracking,
        "position_timeline": position_timeline,
        "stat_tracking": stat_tracking,
        "ktxstats": ktxstats,
        "bsp_coverage": bsp_coverage,
        "loc_coverage": loc_coverage,
        "player_data": player_data,
        "kill_data": kill_data,
        "cross_validation": cross_validation,
        "aggregate_score": aggregate_score,
    }


def print_scorecard(sc):
    print(f"\n{'='*60}")
    print(f"  {sc['map'].upper()} — {sc['file']}")
    print(f"  Parser: {sc['parser']} ({sc['parser_version']})")
    print(f"{'='*60}")

    rows = [
        ("Byte accounting", sc["byte_accounting"]["status"],
         sc["byte_accounting"]["coverage_pct"] or "?"),
        ("Message type coverage", sc["message_coverage"]["status"],
         sc["message_coverage"]["svc_types_parsed"] or "?"),
        ("Hidden msg coverage", sc["hidden_message_coverage"]["status"],
         f"{sc['hidden_message_coverage']['coverage_pct']}%"),
        ("Entity parse failures", sc["entity_tracking"]["status"],
         f"~{sc['entity_tracking']['failure_rate_pct']}% (est)"),
        ("Position sample rate", sc["position_timeline"]["status"],
         f"{sc['position_timeline']['sample_rate_hz']} Hz"),
        ("Stat indices tracked", sc["stat_tracking"]["status"],
         f"{sc['stat_tracking']['coverage_pct']}%"),
        ("KTXstats fields", sc["ktxstats"]["status"],
         f"{sc['ktxstats']['coverage_pct']}%"),
        ("BSP lump coverage", sc["bsp_coverage"]["status"],
         f"{sc['bsp_coverage']['coverage_pct']}%"),
        ("Loc file", sc["loc_coverage"]["status"],
         "yes" if sc["loc_coverage"]["loc_file_exists"] else "MISSING"),
        ("Unknown weapons", "",
         f"{sc['kill_data']['unknown_weapon_pct']}%"),
        ("Cross-validation", sc["cross_validation"]["status"],
         f"{sc['cross_validation']['independent_parsers']} parser(s)"),
    ]

    for label, status, value in rows:
        status_str = f"[{status}]" if status else ""
        print(f"  {label:<28} {str(value):>8}  {status_str}")

    print(f"\n  AGGREGATE SCORE: {sc['aggregate_score']}%")


def main():
    print("=" * 60)
    print("  MIMER BASELINE CAPTURE")
    print("  Measuring current data extraction quality")
    print("=" * 60)

    scorecards = []
    for demo in DEMOS:
        print(f"\nProcessing {demo['map']}...")
        sc = score_demo(demo)
        scorecards.append(sc)
        print_scorecard(sc)

        # Save individual scorecard
        out_file = OUT_DIR / f"scorecard_{demo['map']}_{demo['hub_game_id']}.json"
        out_file.write_text(json.dumps(sc, indent=2))

    # Aggregate summary
    print(f"\n{'='*60}")
    print(f"  AGGREGATE BASELINE SUMMARY")
    print(f"{'='*60}")

    avg_score = round(sum(s["aggregate_score"] for s in scorecards) / len(scorecards), 1)
    total_kills = sum(s["kill_data"]["kill_count"] for s in scorecards)
    total_unknown_weapons = sum(s["kill_data"]["unknown_weapon_count"] for s in scorecards)
    total_positions = sum(s["position_timeline"]["total_positions"] for s in scorecards)
    total_zero = sum(s["position_timeline"]["zero_origin_positions"] for s in scorecards)

    summary = {
        "parser": "mimer",
        "version": "Phase 4B (2026-04-11)",
        "demos": len(scorecards),
        "maps": [s["map"] for s in scorecards],
        "aggregate_score": avg_score,
        "byte_accounting": "NOT_TRACKED",
        "message_coverage": "NOT_TRACKED",
        "hidden_msg_coverage_pct": 50.0,
        "entity_failure_rate_pct": 3.5,
        "position_sample_rate_hz": 0.5,
        "stat_indices_coverage_pct": 12.5,
        "ktxstats_coverage_pct": scorecards[0]["ktxstats"]["coverage_pct"],
        "bsp_lump_coverage_pct": 6.7,
        "loc_files_present": sum(1 for s in scorecards if s["loc_coverage"]["loc_file_exists"]),
        "loc_files_missing": sum(1 for s in scorecards if not s["loc_coverage"]["loc_file_exists"]),
        "total_kills": total_kills,
        "unknown_weapons": total_unknown_weapons,
        "unknown_weapon_pct": round(100 * total_unknown_weapons / max(total_kills, 1), 1),
        "total_positions": total_positions,
        "zero_origin_pct": round(100 * total_zero / max(total_positions, 1), 1),
        "cross_validation_parsers": 1,
        "demopasha_target": {
            "byte_accounting": "100%",
            "hidden_msg_coverage_pct": 100.0,
            "entity_failure_rate_pct": 0.0,
            "position_sample_rate_hz": 77,
            "stat_indices_coverage_pct": 100.0,
            "bsp_lump_coverage_pct": 100.0,
            "unknown_weapon_pct": 0.0,
            "cross_validation_parsers": 2,
        },
    }

    print(f"\n  Demos scored:           {summary['demos']}")
    print(f"  Aggregate score:        {summary['aggregate_score']}%")
    print(f"  Byte accounting:        {summary['byte_accounting']}")
    print(f"  Hidden msg coverage:    {summary['hidden_msg_coverage_pct']}%")
    print(f"  Entity failure rate:    ~{summary['entity_failure_rate_pct']}%")
    print(f"  Position sample rate:   {summary['position_sample_rate_hz']} Hz (target: 77 Hz)")
    print(f"  Stat indices:           {summary['stat_indices_coverage_pct']}%")
    print(f"  BSP lump coverage:      {summary['bsp_lump_coverage_pct']}%")
    print(f"  Loc files present:      {summary['loc_files_present']}/{summary['demos']}")
    print(f"  Unknown weapons:        {summary['unknown_weapon_pct']}%")
    print(f"  Cross-validation:       {summary['cross_validation_parsers']} parser")
    print()

    summary_file = OUT_DIR / "baseline_summary.json"
    summary_file.write_text(json.dumps(summary, indent=2))
    print(f"  Saved: {summary_file}")

    # Save all scorecards together
    all_file = OUT_DIR / "baseline_all.json"
    all_file.write_text(json.dumps(scorecards, indent=2))
    print(f"  Saved: {all_file}")


if __name__ == "__main__":
    main()
