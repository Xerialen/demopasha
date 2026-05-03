# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Mission in one paragraph

demopasha is a QuakeWorld demo parsing / validation project whose north-star
is a **protocol-complete, geometry-grounded, self-validating foundational
data layer** fusing MVD demos + BSP v29 map geometry + loc files. It exists
because an audit of the sibling `demoparser`/`mimer` stack found 27
data-honesty issues (silent recoveries, heuristic fallbacks, partial
decodes). demopasha replaces that foundation. Hard rule: **unknown byte =
hard failure, never `continue`**. The RTX 4090 on `pinnaclepowerhouse` is
the primary validation instrument (not decoration), via GPU clipnode walks,
OptiX ray parity, visual parity renders, and PVS soundness checks.

**Status: Phase 0 complete, not yet started on the full Cargo workspace.**
All code currently lives under `phase0/` and is throwaway — the crate
layout described in `README.md` (`crates/demopasha-mvd`, `demopasha-bsp`,
etc.) does **not** exist yet. Do not fabricate it.

## Authoritative design documents

Before making non-trivial changes, read the doc that governs the area you
are touching. These are the source of truth — the spec beats the code when
they disagree in Phase 0:

- `docs/superpowers/specs/2026-04-12-demopasha-foundation-design.md` —
  mission, four workstreams, language matrix, phasing, success definition.
  The load-bearing spec.
- `docs/superpowers/specs/2026-04-12-validator-poc-design.md` — Validator
  tab architecture, three-machine data flow, glue-server contract.
- `docs/superpowers/specs/2026-04-12-map-visuals-design.md` — color palette,
  item spawn indicators, view cones, powerup glow, weapon pips. The dashboard's
  visual contract.
- `docs/superpowers/reports/2026-04-12-phase0-gpu-poc.md` — measured Phase 0
  numbers and the GO recommendation for Phase A.
- `docs/superpowers/plans/2026-04-12-phase0-gpu-poc.md` — the step-by-step
  plan Phase 0 followed.

## Repository layout (current, not aspirational)

```
demopasha/
├── README.md                 # Describes aspirational crate layout (Phase A+)
├── docs/superpowers/         # Specs, plans, reports — AUTHORITATIVE
├── phase0/                   # All current code lives here (throwaway)
│   ├── bsp_parse.py          # Python `construct` BSP v29 lump extractor
│   ├── clipnode_walk.cu      # CUDA kernel: GPU SV_RecursiveHullCheck
│   ├── ray_trace.cu          # CUDA kernel: brute-force Möller-Trumbore
│   ├── hull_check_cpu.py     # CPU reference for clipnode walk
│   ├── extract_positions.py  # Pulls player positions from demos
│   ├── run_poc_{a,b,d}.py    # POC drivers / validators
│   ├── render/               # Rust wgpu-less top-down rasterizer (112 LOC)
│   ├── glue-server.js        # Node HTTP glue, runs on quakeboot
│   ├── glue-server-pinnacle.js  # Node HTTP glue, runs on pinnaclepowerhouse
│   ├── dashboard.html        # Single-file dashboard (Replay + Validator tabs)
│   ├── extract_dashboard_data.py  # Builds data/dashboard_data.json
│   ├── baseline/             # Mimer baseline scorecards (frozen pre-demopasha)
│   └── data/                 # **gitignored** — BSPs, demos, render outputs
└── .gitignore                # `data/` is gitignored everywhere
```

`.superpowers/` and `data/` are gitignored — never commit demos, BSPs, PAK
contents, or the dashboard JSON bundle.

## Three-machine topology

demopasha is inherently multi-host. Know which machine runs what before
writing commands:

| Machine | Role | What runs here |
|---|---|---|
| `quakeboot` (LAN 192.168.86.34 / .42, this workstation) | Dev + 4070 | Rust `phase0/render`, BSP extraction from pak0, `glue-server.js`, dashboard in browser |
| `pinnaclepowerhouse` (192.168.86.20, 7800X3D + RTX 4090) | GPU compute | CUDA kernels, Python `construct` parser runs, `mimer --dump-analysis`, FTEQW WebAssembly on port 8088, `glue-server-pinnacle.js`, OptiX work in Phase C |
| `servexeri` (192.168.86.33) | Demo storage + CPU daemon | 1,315-demo firehose at `/mnt/usb-ssd/mimer-demo-watcher/data/firehose/qtv/`, will host `demopasha-daemon-cpu` in Phase B |

SSH-based orchestration is intentional. The dashboard's glue server is
"POC duct tape" (no auth, no caching, no persistence) — don't add
production hardening to it unless the spec calls for it.

## Common Phase 0 commands

### Re-run a POC on pinnacle

```bash
# BSP parse → flat binaries for CUDA
ssh pinnaclepowerhouse 'cd ~/projects/demopasha/phase0 && \
  source .venv/bin/activate && \
  python bsp_parse.py data/dm3.bsp data'

# GPU clipnode walk (POC A)
ssh pinnaclepowerhouse 'cd ~/projects/demopasha/phase0 && \
  nvcc -O3 -o clipnode_walk clipnode_walk.cu && \
  ./clipnode_walk <hull1_start> <n_planes> <n_clipnodes> <n_points>'

# Compare GPU vs CPU reference
ssh pinnaclepowerhouse 'cd ~/projects/demopasha/phase0 && \
  source .venv/bin/activate && python run_poc_a.py'
```

POC D (signature test on real demos) pipeline:
`extract_positions.py` → `clipnode_walk.cu` → `run_poc_d.py`.

### Top-down render (POC C, runs on quakeboot)

```bash
cd phase0/render && cargo run --release
# reads phase0/data/{triangles,vertexes}.bin → writes phase0/data/dm3_topdown.png
```

### Dashboard / Validator locally

```bash
# glue server (quakeboot flavor) — talks to servexeri + pinnacle over SSH
cd phase0 && node glue-server.js    # listens on localhost:3456
# then open phase0/dashboard.html in a browser
```

The pinnacle-native variant (`glue-server-pinnacle.js`) is what runs on
pinnaclepowerhouse when the dashboard is served from there, serving
`~/demopasha-dashboard/static/` and proxying `~/fteqw-web/` under `/fte/`.

### Dashboard data bundle (Replay tab)

```bash
cd phase0 && python3 extract_dashboard_data.py
# → writes phase0/data/dashboard_data.json
# depends on mimer binary at ~/projects/demoparser/target/release/mimer
```

### Mimer baseline (frozen pre-demopasha scorecards)

```bash
cd phase0/baseline && python3 capture_baseline.py
# compares later demopasha output against these to measure improvement
```

## Data contracts worth internalizing

**Per-snapshot player array layout** (used by glue server → dashboard):
indices `[num, x, y, z, alive, health, armor, flags, pitch*10, yaw*10]`.
`pitch` and `yaw` are integer-encoded; divide by 10 to restore the float.

**`flags` bitmask:** bit 0 = has RL, bit 1 = has LG, bit 2 = Quad,
bit 3 = Pent. These drive the view cones / pips / glow logic in
`dashboard.html` — see the map-visuals spec for the full contract.

**BSP v29 collision model:** Q1 BSPs have **no brushes**. Collision is
resolved by walking the **clipnodes** tree with the player AABB
(`SV_RecursiveHullCheck`). Hull 0 = point, Hull 1 = standard player
(32×32×56), Hull 2 = crouch. Never try to build a BVH over "brushes" in
this codebase — they don't exist in the file format. The face BVH (for
rendering + ray parity + PVS + LOS) is a **separate** geometry from the
clipnodes tree (for player-in-solid).

**"Inside solid" is not always a parser bug.** Per Phase 0 POC D, ~31% of
raw demo positions report `CONTENTS_SOLID` in Hull 1, fully explained by
three known categories: spectator `(0,0,0)` origins (~26%), hull-boundary
quantization (~5%), and dead-player/telefrag/map-edge edge cases (~0.4%).
Production Workstream 3.3 must filter these before asserting zero. Do not
"fix" the parser if you see these categories — they are documented in the
Phase 0 report.

## Coding invariants (from the foundation spec)

These are hard rules, not guidelines. Violating them is a bug even if a
test passes:

1. **No silent skips.** Unknown temp-entity opcodes, unknown hidden
   message types, unknown BSP lumps, malformed loc lines — all must
   produce a named error carrying the raw bytes. Never `continue`.
2. **No heuristic fallbacks.** Don't approximate backpack attribution,
   weapon classification, or item pickup ownership. If the protocol gives
   you the answer, decode it; if it doesn't, fail loudly and escalate.
3. **Parser preserves every update.** Don't downsample to 1 Hz inside the
   parser. Downsampling is an analysis-side decision. Phase 0 position
   extraction already preserves every `svc_playerinfo`.
4. **Byte accounting is mandatory.** Every parse produces
   `{bytes_in, bytes_consumed, bytes_unknown, per_message_type_breakdown}`.
   `bytes_unknown == 0` is the bar.
5. **Two-witness rule.** Every parser has an independent cross-check
   (Rust ↔ Python `construct`, plus KTXstats, MVDSV replay, byte-identical
   roundtrip where applicable).
6. **GPU carries real load.** The 4090 is not a demo prop. If a validation
   workload fits in seconds on the 4090, run it there, not in CPU Python.

## Scope discipline (what this repo does NOT cover)

Per §3 of the foundation spec these are explicit **non-goals** — reject
scope creep into any of them:

- QWD, vanilla Quake 1 `.dem`, Quake 2 demos. (In this repo, `dm2` is the
  *map* Claustrophobopolis, not a demo file extension.)
- Analysis / coaching / patterns / metrics / composer / Discord / Supabase
  ingest. Those live in `demoparser`/`mimer` and consume demopasha as a
  versioned dependency.
- Realtime / in-game use.
- New metrics or insights — the mission is securing existing data, not
  mining new signal.

## Sibling project references (on this machine)

- `~/projects/demoparser/` — the existing mimer stack demopasha is
  validating against and will eventually replace as the foundation. The
  `mimer` binary at `~/projects/demoparser/target/release/mimer` is used
  by Phase 0 extraction scripts (`--dump-analysis`).
- `~/projects/ezquake-source/` — authoritative client-side MVD parser
  (`src/cl_parse.c`). Reference only — do not FFI-link it (see spec R1).

## Git and review

- Git identity: DXerialen / benyah@gmail.com (set globally).
- **Code review is done by Codex**, not self-review — use the
  `codex:rescue` skill for any meaningful new implementation, spec, or
  refactor before declaring work done. Specs and design docs are reviewed
  by the user directly, per 2026-04-12 feedback captured in spec R8.
