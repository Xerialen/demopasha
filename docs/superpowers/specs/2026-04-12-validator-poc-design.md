# Validator POC — Synced Demo Playback for Position Validation

**Date:** 2026-04-12
**Status:** Design
**Scope:** POC — prove that parsed positions match FTEQW ground truth

## Purpose

The demopasha north-star goal is to build the greatest MVD parser. To validate that our parser's position data is correct, we need to see it side-by-side with the actual game engine's rendering. This POC builds a "browse → parse → synced play" workflow into the dashboard's Validator tab.

## Architecture

Three machines on LAN:

| Machine | Role | Key assets |
|---|---|---|
| **servexeri** (192.168.86.33) | Demo storage | 1,302 demos on USB SSD at `/mnt/usb-ssd/mimer-demo-watcher/data/firehose/` |
| **pinnaclepowerhouse** (192.168.86.20) | Compute + FTEQW host | 7800X3D + RTX 4090. Runs `mimer --dump-analysis`. Serves FTEQW WebAssembly on port 8088 (nginx, already deployed). |
| **quakeboot** (192.168.86.34) | Workstation | Dashboard in browser. Local demos in `~/projects/demoparser/data/testdemos/` (194 files). Orchestrates via SSH. |

### Data flow when a demo is selected

1. Dashboard calls a local HTTP endpoint on quakeboot (glue server).
2. Glue server fetches the demo (SSH from servexeri, or local read).
3. Glue server pipes the demo to pinnacle via SSH, runs `mimer --dump-analysis`.
4. Parsed JSON streams back to quakeboot.
5. Glue server copies the demo to pinnacle's `~/fteqw-web/demos/` for FTEQW.
6. Dashboard loads parsed JSON into map view and points the FTEQW iframe at `http://192.168.86.20:8088/?demo=<filename>`.

### Glue server

A small Node or Python HTTP server on quakeboot (localhost only). Single endpoint:

- `POST /parse` — body: `{ source: "firehose" | "local", path: "<relative path>" }`
- Response: streamed JSON with progress events, then the parsed dashboard data.
- Side effect: demo file copied to pinnacle's FTEQW demos directory.

This is POC duct tape. It doesn't need auth, error recovery, or persistence.

**File format note:** Firehose demos on servexeri are uncompressed `.mvd`. Local test demos are `.mvd.gz`. The glue server handles both — mimer accepts either format. When copying to pinnacle's FTEQW server, the filename is preserved as-is (FTEQW handles both `.mvd` and `.mvd.gz`).

### Prerequisite: build mimer on pinnacle

Clone the demoparser repo to pinnacle, `cargo build --release`. The binary at `target/release/mimer` is the only dependency.

## Validator Tab — UI Design

The Validator tab has three states: **Browse**, **Parsing**, and **Playback**.

### Browse mode

Full-width demo browser. Replaces the current toolbar + split view.

**Source tabs** across the top:
- **Firehose** (default) — lists demos from servexeri's USB SSD. Fetched on tab open via the glue server (`GET /demos?source=firehose`). Sorted by date descending.
- **Local** — lists demos from quakeboot's `data/testdemos/`. Fetched via `GET /demos?source=local`.

**Demo list** as a table: filename, date (parsed from filename), size. Clicking a row triggers parsing immediately — no separate Load button.

**Filters** (POC scope: map filter only, parsed from filename bracket notation like `[dm2]`).

### Parsing state

Centered progress overlay replacing the demo list. Shows:
- Demo filename
- Progress bar
- Step checklist: ✓ Fetched · ✓ Parsed (N.Ns) · ◌ Staging for FTEQW...

On completion, transitions automatically to Playback mode.

### Playback mode

**Compact toolbar** with: map name, teams, date, POV dropdown, 2D/3D toggle, "← Browse" button.

**Split view** (50/50):
- Left: FTEQW iframe (`http://192.168.86.20:8088/?demo=<filename>&track=<player>`)
- Right: demopasha map view (2D canvas or Three.js BSP, togglable)

**Shared timeline bar** at the bottom: play/pause, time label, scrub slider, speed (1x/2x/4x/8x), Sync button.

**POV dropdown**: lists all players grouped by team. Selecting a player:
- Highlights them on the map (yellow ring in 2D, yellow sphere in 3D)
- Reloads FTEQW iframe with `&track=<player>`
- Kill feed entries for the tracked player are highlighted

### Sync behavior

- **Play/Pause** — controls the map view animation. FTEQW plays independently once loaded.
- **Scrub** — updates map view instantly. Pressing Sync reloads FTEQW at the current time.
- **Speed** — controls map animation speed. FTEQW plays at native 1x (speed sync requires newtube JS bindings, out of POC scope).
- **Sync button** — reloads FTEQW iframe at the map view's current timestamp and POV. Use after scrubbing to re-align.

### Known POC limitations

- FTEQW iframe reloads are coarse (~1s accuracy, brief loading flash).
- Speed only affects the map side; FTEQW always plays at 1x.
- No frame-level time sync — the two views drift during playback. Sync button re-aligns.
- Demo list is fetched fresh each time (no caching).

## Cleanup: Remove hub links from Replay tab

The Replay tab sidebar currently has a "Hub links" section with a Game ID input and links to hub.quakeworld.nu at current time, 5:00, 10:00, and 15:00. This is obsolete now that FTEQW runs locally. Remove:
- The `<h2>Hub links</h2>` heading
- The Game ID input (`#hubGameId`)
- The links container (`#hubLinks`)
- The `updateHubLinks()` function and all calls to it
- The `hub_game_id` field from demo data (no longer needed)

## Dashboard data format

The glue server returns the same schema as `dashboard_data.json` but for a single demo:

```json
{
  "map": { "world_mins": [...], "world_maxs": [...], "topdown_image": "..." },
  "demo": {
    "filename": "...",
    "map": "...",
    "duration": float,
    "teams": [{ "name": "...", "players": ["..."] }],
    "players": [{ "name": "...", "team": "...", "num": int }],
    "snapshots": [{ "t": float, "positions": { "name": { "x","y","z","alive","health","armor" } } }],
    "kills": [{ "t": float, "killer": "...", "victim": "...", "weapon": "...", "killer_pos": [...], "victim_pos": [...] }]
  }
}
```

The existing `dashboard_data.json` with its 4 hardcoded hub demos is not used by the Validator. The Replay tab continues to use it unchanged.

## Implementation scope

1. Build mimer on pinnacle (clone repo + cargo build)
2. Glue server on quakeboot (~100 LOC: list demos, parse, stage)
3. Rewrite Validator tab JS: browse mode, parsing overlay, playback mode
4. Remove hub links from Replay tab sidebar
5. Test with a firehose demo end-to-end
