# demopasha — Foundation Design

**Date:** 2026-04-12
**Status:** Committed, pre-code
**Author:** DXerialen (via Claude Code brainstorm)
**Repo:** `~/projects/demopasha` (new, separate from `demoparser`/`mimer`)

---

## 1. Mission

Build the best QuakeWorld demo parser out there, by fusing three data sources
into one protocol-complete, geometry-grounded, continuously self-validating
foundational data layer:

1. **MVD** (QuakeWorld multi-view demos)
2. **BSP v29** map geometry (brushes, planes, leaves, PVS, entities, etc.)
3. **Loc files** (zone names → coordinates)

The project exists because the existing `demoparser`/`mimer` analysis stack
sits on a foundation with 27 documented data-honesty issues (silent recoveries,
heuristic fallbacks, partial decodes, approximated spatial features). Any
insight the analysis layer produces is bounded by the quality of that
foundation. This project replaces the foundation.

## 2. North-star goals (locked 2026-04-11)

1. **Best demo parser out there**, by fusing BSP + loc + MVD into a single
   data layer. No one pillar is enough; the value is in the combination.
2. **Zero unmined data** — every byte of every MVD, every BSP lump, every
   loc line is extracted. Silent recovery, heuristic fallbacks, and partial
   decoding are not acceptable end states. Unknown byte = hard failure, not
   a `continue`.
3. **Self-validating automatically**, with the RTX 4090 on
   `pinnaclepowerhouse` carrying real load (not decoration). The 4090 is
   the primary validation instrument, proving the BSP parse correct by
   multiple independent GPU methods and providing geometry-grounded spatial
   features that retire CPU-side heuristics.

## 3. Non-goals (explicit)

- **Old demo formats:** QWD, vanilla Quake 1 `.dem`, Quake 2 demos. These
  are related but separate future projects. Do not scope-creep them into
  this one. (In this project, `dm2` refers to the map Claustrophobopolis,
  not a demo file extension.)
- **Analysis layer:** coaching, patterns, validator, metrics, composer,
  Discord bot, Supabase ingest, dashboard UI. These live in the existing
  `demoparser`/`mimer` stack and will consume this foundation as a
  versioned dependency once it is green.
- **Realtime / in-game use:** this is a batch / post-match / continuous
  pipeline, not a live overlay.
- **New insights:** this mission is about securing existing data, not
  generating new metrics.

## 4. Foundation audit summary (motivation)

An audit on 2026-04-11 of the existing `demoparser` repo found **27
distinct data-honesty issues**. Highlights:

**Parser (`src/mvd/`)**
- Entity U_* parsing fails ~3.5% of the time; errors swallowed, empty
  `PacketEntities` returned.
- Unknown temp entity types assume a 3-coord format ("we can't know the
  size. This is a real problem for parsing").
- Hidden message types 4, 5, 6, 9 (`weapon_instruction`), 10, 11
  (`timestamp`) all skipped into an `Other` variant.
- `MVDHIDDEN_DMGDONE` reads first 6 bytes and discards the rest.
- FTE entity delta is a "best-effort implementation covering the common
  flags."
- On any message parse error, the entire frame's remaining messages are
  skipped.

**State reconstruction (`src/state/`)**
- Backpack dropper attribution is 54% accurate (300-unit radius, 5-sec
  window, first match wins).
- Backpack picker: closest-player-within-200-units, ties broken by
  `HashMap` iteration order.
- Kill-message fallback parses by name position order.
- Weapon fallback returns the literal string `"unknown"`.
- Only 4 of 32 `STAT_*` indices are tracked.
- Position timeline is downsampled to 1 Hz inside the state layer.

**Map / loc (`src/map/`)**
- BSP reader reads only the entity lump. Brushes, planes, nodes, leaves,
  PVS, texinfo, faces, edges, lightmaps — all ignored. Approximately 95%
  of BSP data untouched.
- Only 17 item classnames extracted from the entity lump.
- BSP version ≠ 29 rejected silently.
- Loc bad lines silently `continue`.
- PAK name-field null-terminator fallback pads with garbage bytes.

**Meta observation:** none of this is fundamental. MVD, BSP v29, and loc
are all deterministic, fully specified, and have multiple open-source
reference implementations. Zero unknowns is an *effort* bound, not a
physics bound. This project is the effort.

## 5. Architecture — four workstreams (plus one optional)

The plan has four first-class workstreams, each with its own pass criterion.
Workstream 3 is elevated to a first-class pillar (not a sub-bullet of map
work) because GPU validation is the signature technical ambition of the
project. A fifth workstream (neural layers) is explicitly optional and
lives in Phase D only, conditional on Workstreams 1–4 landing green.

### 5.1 Workstream 1 — Byte-perfect protocol coverage (CPU)

**Bar:** every byte of every MVD consumed by a named handler. Unknown byte
= hard failure, not `continue`.

**Scope:**
- Complete FTE extension parse: svc_* opcodes 55–94, tracing ezQuake's
  `CL_ParseDelta` line-by-line.
- Parse hidden message types 0–11 exhaustively. Delete the `Other` variant.
- Eliminate the 3.5% entity U_* failure. Root cause it, don't paper over it.
  It is almost certainly uncovered FTE delta bits.
- Unknown temp entity: store opcode + raw bytes; never guess the length.
- Frame parse errors: recover at the exact failing byte, not by breaking
  the frame loop.
- Push 1 Hz position sampling **out** of the parser. The parser preserves
  every `svc_playerinfo` update from every frame. Downsampling is an
  analysis-side decision, not a parser-side one.
- **Byte accounting**: every demo produces a report
  `{bytes_in, bytes_consumed, bytes_unknown, per_message_type_breakdown}`.
  `bytes_unknown == 0` is the pass bar.
- `cargo fuzz` harnesses on the frame and message parsers. Invariants:
  `should_not_panic`, `should_consume_all_bytes_or_error_precisely`.
- **Reconstruction sufficiency:** the structured parser output must be
  sufficient to reconstruct a semantically-equivalent MVD — not just to
  decode one. Any field, flag, or delta base reference whose loss would
  prevent an independent encoder from producing a semantically-equivalent
  demo must be preserved in the structured output. "Semantically
  equivalent" means: when played back through a reference renderer
  (ezQuake / FTE) with deterministic settings, every frame renders
  identically up to pixel-diff tolerance, and every hidden-message field
  (KTXstats, damage events, weapon instructions, timestamps) survives
  intact. This is a stricter reading of "no `Other` variant" and is
  cheap to guarantee now, expensive to retrofit later. Enables the
  Phase D visual-playback parity check (see §9) without rearchitecting
  the parser output.

**Pass criterion:** across all 1,315 demos in the corpus:
`bytes_unknown == 0` AND zero parser errors AND zero panics under 1-hour
fuzzing per harness AND structured-output → encoder → parser roundtrip
produces a semantically-equivalent model (field-by-field equality on the
structured model, not byte equality on the wire).

**Language:** Rust. `cargo fuzz` tooling and zero-cost abstractions are
decisive.

### 5.2 Workstream 2 — Independent parser cross-validation (CPU)

**Bar:** a second witness. "Our parser agrees with an independent
implementation on every field of every demo in the corpus."

**Approach:** write a **second parser from the protocol spec, in a
different language, by a different reasoning path**. The whole point of
a second witness is to have independent error modes. Same-language
reimplementation risks shared author bias.

**Language decision:** **Python 3 + `construct`**. Reasons:
1. `construct` is a declarative binary-protocol DSL. The parser is written
   as a data structure, not as imperative code. This is a fundamentally
   different way of approaching the same spec — stronger independence.
2. Python is the maximum linguistic distance from Rust while still having
   first-class binary-parsing tooling.
3. Speed doesn't matter for a nightly validation run; we can parse the
   whole corpus in batch.
4. Avoids the C-build-deps cost of an ezQuake FFI path, which was the
   initial instinct but turns out to couple too tightly to ezQuake's
   `cl.frames` / `cls.netchan` / UI state.

**Auxiliary witnesses** (on top of the primary Rust ↔ Python diff):
- **KTXstats cross-check**: every KTXstats numeric field (frags, deaths,
  accuracy, EWEP, xferRL, spawn frags, timeheld) must agree between our
  parser's extracted stats and the hidden-message KTXstats block.
- **MVDSV replay**: spawn a headless MVDSV process in QTV mode on the demo
  and compare re-served output to our output. MVDSV is the authoritative
  server-side parser.
- **Roundtrip**: parse → re-serialize → parse → hash. Byte-identical
  round-trip or bug.

**Pass criterion:** on every demo in the corpus, the Rust parser's output
equals the Python `construct` parser's output field-by-field; KTXstats
cross-check green; MVDSV replay green; roundtrip byte-identical.

### 5.3 Workstream 3 — Full BSP parse + GPU validation (the 4090 pillar)

**Bar:** parse 100% of the BSP v29 format AND prove the parse correct via
five independent GPU checks.

#### 5.3.0 Full BSP parse

Every one of the 15 BSP v29 lumps gets a decoded struct, not just the
entity lump:

1. Entities (all classnames, not just the 17 currently extracted)
2. Planes
3. Miptex (texture data)
4. Vertexes
5. Visibility (PVS)
6. Nodes (rendering BSP tree)
7. Texinfo
8. Faces
9. Lightmaps
10. **Clipnodes** (collision BSP tree — Q1 uses this, *not* brushes; Q2/Q3's brush model does not apply here)
11. Leaves (with `contents` field: `SOLID`, `EMPTY`, `WATER`, `SLIME`, `LAVA`, `SKY`)
12. Marksurfaces (leaffaces)
13. Edges
14. Surfedges
15. Models

Invariant: parse → serialize → parse → hash is byte-identical.

**Q1 BSP collision model (important):** Quake 1 BSPs do not have brushes
or brushsides. Collision is resolved by recursively walking the clipnodes
tree with the player's bounding box (`SV_RecursiveHullCheck` in engine
source). Hull 0 is point collision, Hull 1 is the standard player AABB
(32×32×56), Hull 2 is the crouched / hipnotic AABB. Workstream 3 must
therefore walk clipnodes for "is this position inside solid" queries —
it cannot build a BVH over brushes, because the brushes don't exist in
the file.

**Language:** Rust. Same rationale as Workstream 1.

**Cross-validation:** parse every BSP a second time in Python (same
`construct` DSL approach) as a sibling of the ref-parser. Diff.

#### 5.3.1 GPU validation — five layers of proof

These run on the RTX 4090 on `pinnaclepowerhouse`. The kernels are written
in **C++ / CUDA / OptiX**, called from a Rust host via a thin FFI. Reason:
Rust's GPU story is strong for compute and rasterization but lags on
NVIDIA RT-core ray tracing. OptiX is officially C++ only, and pro graphics
teams in Rust projects routinely write GPU kernels in C++/CUDA and FFI
them. This project follows that pattern.

**GPU geometry representations (two of them).** Workstream 3 needs
two distinct BSP-derived geometries on the GPU, because Q1 BSP has two
separate collision models:

- **Face BVH (for rendering + ray parity + PVS + LOS):** triangulate the
  BSP's faces (polygon fan over edges/surfedges/vertexes), build an
  OptiX BVH over those triangles. This is the standard RT-core workload.
- **Clipnode tree (for player-in-solid + spatial containment):** flatten
  the clipnodes tree from Hull 1 into a GPU-walkable array, implement
  `SV_RecursiveHullCheck` as a CUDA kernel. This is compute-only, not
  RT-core.

**3.1 — Visual parity vs ezQuake rendering.**
Render our parsed BSP through a `wgpu` pipeline from top-down and 8
cardinal first-person positions per map, using the face BVH (or direct
triangle list). Render the same BSP via headless ezQuake to the same
views. Compare via SSIM + feature matching. Zero significant diff =
parse is visually correct. `wgpu` is Rust; the ezQuake capture is a
subprocess. Output doubles as a corpus-wide map-overview gallery for
eyeballing.

**3.2 — Ray-query parity vs a Q1 BSP reference.**
Fire 10M random rays (origins uniform in map AABB, directions uniform
on sphere) through the face BVH via `optixTrace`. Compare hit results
to an independent Q1 BSP face-hit reference. Reference choices (pick
one in Phase 0 based on integration cost): `ericw-tools`' collision
code (used during vis), a port of `QuakeSpasm`'s `SV_RecursiveHullCheck`
to Python/Rust, or a from-scratch re-implementation of the documented
face/plane intersection algorithm. Any ray disagreement = faces, edges,
surfedges, vertexes, or planes are decoded wrong.

**3.3 — Player-position-vs-solid (the signature test).**
Take every player position from every frame of every demo in the corpus.
Estimated workload:
- 77 Hz × 600 s × 8 players × 1,315 demos ≈ **~490M player-positions**

For each position, walk the Hull 1 clipnodes tree on the GPU (or in a
CUDA kernel) and resolve the leaf `contents` field: is this position
inside a `CONTENTS_SOLID` leaf? Players cannot physically be inside
solid walls. If any position reports `CONTENTS_SOLID`, exactly one of
three things is true:
1. Our BSP parse is wrong (a plane, clipnode link, or leaf contents bit
   is decoded wrong)
2. Our demo parse is wrong (player position is decoded wrong)
3. A real physics edge case (telefrag mid-step, clip prediction quirk,
   movement reconciliation) that we need to model

The corpus itself is the oracle — this check cross-validates Workstream 1
AND Workstream 3 in a single sweep. This is the kind of validation that
is impossible without a GPU: CPU `SV_RecursiveHullCheck` over 490M
positions would take many hours per corpus run; on GPU with parallel
walks it is minutes.

**3.4 — PVS soundness.**
For each leaf, enumerate "leaves visible from this leaf" per our parsed
PVS. Compare against ray-traced visibility (10k rays from random points
in each leaf). PVS should be a strict superset of ray-traced visibility.
If PVS says "leaf 17 visible from leaf 3" but zero rays ever confirm,
flag.

**3.5 — Spatial ground-truth layer (mission value).**
Once validated, the same BVH becomes the spatial ground-truth layer for
everything downstream. Per-frame, per-player-pair: line of sight,
wall-aware distance, PVS cluster membership, zone containment. Estimated
workload: ~16 billion rays across the corpus, seconds-to-minutes per
demo on the 4090. This is what replaces `CLAUDE.md`'s *"500-unit
proximity from 1 Hz snapshots, directional, not frame-perfect"* with
geometry-grounded booleans.

**Pass criterion:** (a) BSP round-trip byte-identical, (b) visual parity
passes on every map in the corpus, (c) ray parity zero-diff vs
`ericw-tools`, (d) **zero player positions inside solid brushes across
the whole corpus**, (e) PVS soundness confirmed on every map, (f)
spatial ground-truth layer runs to completion on every demo.

### 5.4 Workstream 4 — Loc + BSP cross-validation + auto-loc + map registry

**Bar:** every map referenced by any demo in the corpus has BSP + loc +
green QA. Zero silent gaps.

**Scope:**
- **Loc parse**: hard-fail on any malformed line. No silent `continue`.
- **Loc ↔ BSP entity cross-check:** for every loc zone, find the nearest
  BSP `weapon_*` / `item_*` / `armor_*` entity. If the zone name
  contradicts the nearest item (loc says "RL" but nearest entity is
  `item_armorInv`), flag the loc as incorrect.
- **Auto-loc from BSP + GPU clustering:** for maps with missing or
  flagged locs, generate a skeleton loc by running GPU clustering
  (HDBSCAN via RAPIDS or a k-means kernel) on aggregate player-position
  density across the corpus to discover "rooms," then labelling each
  cluster by its nearest BSP entity.
- **Map registry** (SQLite): every map referenced by any demo, with
  `bsp_hash`, `loc_hash`, last QA result, quality score. Missing entries
  visible and alertable.

**Language:** Rust (host), Python for the clustering kernel (RAPIDS
cuML or PyTorch).

**Pass criterion:** every map referenced by any demo has BSP + loc +
green QA. Zero missing, zero flagged.

## 6. Language matrix

| Workstream | Language | Rationale |
|---|---|---|
| 1 — byte-perfect parser | Rust | `nom` + `cargo fuzz` unbeatable |
| 2 — independent second parser | Python + `construct` | Maximum linguistic + paradigm distance from Workstream 1 → true independent witness |
| 3.0 — BSP lump parser | Rust | Same rationale as Workstream 1 |
| 3.0 — BSP cross-check parser | Python + `construct` | Same rationale as Workstream 2 |
| 3.1 — visual parity rendering | Rust + `wgpu` | Mature rasterization; runs on any NVIDIA GPU |
| 3.2 / 3.3 / 3.4 — GPU ray validation | **C++ / CUDA / OptiX**, called from Rust via FFI | Rust lacks mature RT-core ray tracing; OptiX is C++ only; pro graphics teams in Rust projects do this routinely |
| 4 — loc + BSP cross-check | Rust | Simple text + struct work |
| 4 — GPU auto-loc clustering | Python (RAPIDS / PyTorch) | ML ergonomics |
| 5 — neural layers (optional) | Python + PyTorch | Obvious |

The project is Rust-dominant: host daemons, data model, CPU pipelines,
FFI boundaries, rasterization. Specialist languages for specialist jobs:
Python/`construct` as the cross-validation witness, C++/CUDA/OptiX as the
GPU validation kernels.

## 7. Automation topology

**Continuous, not periodic.**

| Node | Role |
|---|---|
| `servexeri` | systemd unit `demopasha-daemon-cpu.service` (from the `demopasha-daemon-cpu` crate) watches `/mnt/usb-ssd/mimer-demo-watcher/data/firehose/qtv/`. On each new MVD, runs Workstream 1 + 2 + 4 (CPU pipeline). Writes per-demo QA records to `/mnt/usb-ssd/mimer-demo-watcher/data/demopasha-quality.db` (SQLite). Enqueues GPU jobs in a table. |
| `pinnaclepowerhouse` (4090) | systemd unit `demopasha-daemon-gpu.service` (from the `demopasha-daemon-gpu` crate) pulls queued jobs from the shared DB via SSH, runs Workstream 3 + Workstream 4 auto-loc, writes results back. |
| `quakeboot` (4070) | Developer workstation and secondary visual-parity rendering node. The 4070 can run `wgpu` rasterization and PyTorch inference, just not OptiX RT-core kernels. |
| GitHub Actions | Nightly container job runs Workstream 1 + 2 on a fixture subset and compares aggregate scores to a baseline. Any regression fails the build. |

**Per-demo QA record schema (SQLite):**

```sql
CREATE TABLE demo_quality (
  demo_sha TEXT PRIMARY KEY,
  map TEXT NOT NULL,
  played_at TEXT,                -- ISO 8601 parsed from filename
  ingested_at TEXT NOT NULL,     -- ISO 8601 daemon ingest time

  -- Workstream 1
  bytes_total INTEGER NOT NULL,
  bytes_consumed INTEGER NOT NULL,
  bytes_unknown INTEGER NOT NULL, -- MUST be 0
  entity_failures INTEGER NOT NULL, -- MUST be 0
  parse_errors INTEGER NOT NULL, -- MUST be 0
  unknown_message_types INTEGER NOT NULL, -- MUST be 0

  -- Workstream 2
  ref_parser_diff_count INTEGER, -- MUST be 0
  ktxstats_xcheck_ok INTEGER,    -- MUST be 1
  mvdsv_xcheck_ok INTEGER,       -- MUST be 1
  roundtrip_ok INTEGER,          -- MUST be 1

  -- Workstream 3
  bsp_hash TEXT,
  bsp_roundtrip_ok INTEGER,
  bsp_visual_parity_ok INTEGER,
  bsp_ray_parity_ok INTEGER,
  positions_inside_solid INTEGER, -- MUST be 0
  pvs_soundness_ok INTEGER,
  spatial_gt_ok INTEGER,

  -- Workstream 4
  loc_hash TEXT,
  loc_bsp_agreement_pct REAL,
  loc_hard_fail INTEGER,         -- MUST be 0

  -- Rollup
  quality_score REAL             -- geometric mean across all checks
);
```

**Dashboard:** static HTML regenerated on every QA run. Rolling corpus
quality, per-workstream health, recent regressions, top 10 worst-scoring
demos as an actionable queue. No login, no service, just a file served
locally or on pinnacle.

**Alerts:** any must-be-100% metric dropping below 100% fires
`notify-send` on quakeboot and writes a state file that Claude Code can
read at session start. No Slack, no email — low-noise, local.

## 8. Phase 0 — GPU proof of concept (GATE, 2–3 days)

**Before any other phase, prove the 4090 can do what the plan requires.**
The full mission bets ~12 weeks on the 4090 delivering on Workstream 3.
Phase 0 buys information for that bet in 2–3 days.

Phase 0 runs entirely on `pinnaclepowerhouse`. Code is throwaway, in its
own `phase0/` subdirectory, not part of the final crate layout. Output is
a measured report, not production code.

### POC A — GPU clipnode walk (player-in-solid)

- Input: `dm3.bsp` (we have it locally at `~/quake/id1/maps/dm3.bsp`)
- Parse BSP v29 clipnodes + planes + leaves (with `contents`) with a
  minimal Python `construct` script (writing this also sanity-checks
  Workstream 2's approach on one lump at a time)
- Implement `SV_RecursiveHullCheck` on CPU first, using Hull 1 (player
  AABB), as the ground-truth reference — maybe 100 LOC from the
  QuakeSpasm source
- Port the walk to a CUDA kernel — flatten clipnodes into a plane-index +
  left/right array, iterative walk from the Hull 1 root
- Generate 1M uniformly-random 3D points within the map AABB
- Query each: CPU vs GPU → same `contents` result?
- **Success bar:** >10M queries/sec on GPU, zero diff vs CPU reference

### POC B — OptiX ray tracing through face BVH

- Parse BSP v29 faces, edges, surfedges, vertexes, planes from `dm3.bsp`
- Triangulate each face (polygon fan over its surfedges → vertex indices)
- Build an OptiX BVH over the resulting triangles
- Fire 10M random rays (origins in AABB, directions uniform on sphere)
  via `optixTrace` on RT cores
- **Success bar:** >100M rays/sec on the 4090 and hit distances that
  match a CPU `SV_RecursiveHullCheck` face-hit reference on a spot check
  of 1000 rays

### POC C — Visual parity seed

- Render `dm3.bsp` top-down via `wgpu` in Rust
- Compare against a known-good overview image
- **Success bar:** recognizable map, major features aligned with the reference

### POC D — The signature test, scaled down

- Extract player positions from 10 demos from the corpus (all on dm3
  for POC simplicity — we have plenty)
- Run the POC-A GPU clipnode walk on every extracted position
- Expected result: zero positions report `CONTENTS_SOLID`
- If any do, manually investigate each — is it our BSP parse, our demo
  parse, or a real physics edge case (telefrag, clip prediction)?
- **Success bar:** ≤0.01% of positions flagged, and every flag has a
  named root cause

**Phase 0 deliverable:** a short POC report at
`docs/superpowers/reports/2026-04-12-phase0-gpu-poc.md` with measured
numbers, screenshots where applicable, and a go/no-go recommendation for
Phase A. If POC A hits <1M queries/sec, the spatial-grounding pillar must
be re-scoped before committing to the full plan.

## 9. Phasing

| Phase | Length | Scope | Gate |
|---|---|---|---|
| **0** | 2–3 days | GPU POCs A–D on pinnacle; measured report | Go/no-go for Phase A |
| **A** | ~3 weeks | Workstream 1: byte-perfect parser, fuzzing, byte accounting | All 1,315 demos green on bytes_unknown == 0 |
| **B** | ~3 weeks | Workstream 2: Python `construct` ref-parser, KTXstats / MVDSV / roundtrip cross-checks, servexeri CPU daemon, SQLite QA schema | All 1,315 demos zero-diff between parsers |
| **C** | ~4 weeks | Workstream 3: full BSP + five GPU validation layers + spatial ground truth layer + pinnacle GPU daemon + Workstream 4 map registry / auto-loc | All pass criteria in §5.3 and §5.4 met |
| **D** | ~2 weeks | Optional neural layers: fragfile classifier (retires `"unknown"` weapon fallback), trajectory autoencoder, GPU coverage-guided fuzzer | Conditional on A–C green |

**Total: ~12 weeks + 3 days POC gate.** This is not a sprint. Each phase
ends on a visible green gate before the next begins.

## 10. Repository layout

One repo, Cargo workspace. Separate from the existing `demoparser` repo.
Sits on `quakeboot` at `~/projects/demopasha` (parking-lot reminder: the
user prefers persistent infra off quakeboot — flag when hosting moves
from "works on my machine" to "runs in production," and revisit then).

```
demopasha/
├── Cargo.toml                     # workspace
├── README.md
├── .gitignore
├── crates/
│   ├── demopasha-mvd/             # Workstream 1 — byte-perfect parser
│   ├── demopasha-ref-parser/      # Workstream 2 — Python construct, packaged as a subdir
│   ├── demopasha-bsp/             # Workstream 3.0 — full BSP parser
│   ├── demopasha-loc/             # Workstream 4 — loc + cross-check
│   ├── demopasha-gpu/             # Workstream 3.1-3.5 — Rust host + C++/CUDA/OptiX kernels
│   ├── demopasha-state/           # State reconstruction, depends on spatial GT
│   ├── demopasha-daemon-cpu/      # servexeri daemon
│   └── demopasha-daemon-gpu/      # pinnaclepowerhouse daemon
├── docs/
│   └── superpowers/
│       ├── specs/                  # design docs (this file)
│       ├── plans/                  # writing-plans output (Phase 0 plan next)
│       └── reports/                # Phase 0 POC report, phase summaries
├── phase0/                         # throwaway POC code, pruned before Phase A
└── data/
    └── .gitignore                  # never commit demos or BSPs to the repo
```

## 11. Success definition

**The whole mission is done when all of the following hold:**

1. Every demo in the corpus reports `quality_score == 1.0` across every
   workstream
2. The automation has run continuously for **72 hours** without human
   intervention
3. A new demo dropped into the firehose reaches `quality_score == 1.0`
   automatically within **5 minutes**
4. The dashboard shows **zero** flagged maps, **zero** silent fallbacks,
   **zero** `"unknown"` tags in any data produced
5. For any byte of any demo you can name: *what it means, who parsed it,
   which reference agrees with the parse, and which 4090 check validates
   it*

Anything less is a yellow flag. The project is not done until all five
hold simultaneously for 72 consecutive hours.

## 12. Risks and open questions

**R1 — ezQuake FFI was tempting and turned out wrong.**
My initial instinct in brainstorming was to link `cl_parse.c` from
ezQuake as the reference parser. On reflection, ezQuake's parser is
tightly coupled to client state (`cl.frames`, `cls.netchan`, UI),
isolating it is a project in itself, and the C build surface would
complicate the servexeri daemon. Python + `construct` is better. **If
Phase B reveals Python + `construct` is too slow even in batch, revisit
ezQuake FFI.**

**R2 — OptiX + Rust FFI friction.**
C++/CUDA/OptiX kernels called from Rust is a well-trodden pattern but
adds build complexity. Phase 0 POC A exercises this path first; any
pain shows up there, not in Phase C when the stakes are higher.

**R3 — 4090 workload estimates may be optimistic.**
The ~490M player-position queries and ~16B spatial ground-truth rays
across the corpus are back-of-envelope, not measured. Phase 0 POC A and
B measure real throughput. If POC A < 1M queries/sec or POC B < 10M
rays/sec, the Workstream 3 workload estimates are wrong and Phase C
must be re-scoped before it starts.

**R4 — BSP physics edge cases leak into Workstream 3.3.**
Players might legitimately be "inside solid" for one frame during
telefrag, clip prediction mismatch, or server-side movement
reconciliation. Phase 0 POC D investigates whether this is a real
problem on 10 sample demos. If we find >0.01% inside-solid at that
scale, we need a physics-model layer before Phase C can pass.

**R5 — Corpus drift.**
New demos keep arriving at servexeri. The automation daemon handles
live ingestion, but the backtest baseline for CI regression gating
must be a frozen snapshot, not "current corpus." Phase B fixes a
baseline snapshot.

**R6 — Memory budgets for the 4090.**
24 GB VRAM. BSP BVH + rendered frames + PyTorch inference state must
fit simultaneously. Measure in Phase 0.

**R7 — Workspace hosting.**
The user prefers persistent infra off `quakeboot`. Phase 0 runs on
`pinnaclepowerhouse` for the GPU work; the spec lives on `quakeboot`
for dev ergonomics. Before any production cron or systemd daemon
commitment, revisit: does the git origin, the SQLite DB, the
dashboard static HTML, the daemon artifact — all live off quakeboot?

**R8 — Codex review scope.**
Per user feedback on 2026-04-12, Codex reviews written code only, not
specs/plans/design docs. This spec is therefore reviewed by the user
directly, not sent to Codex. Codex comes back in once Phase 0 POCs
produce actual code.

## 13. Glossary

- **MVD** — QuakeWorld multi-view demo format. Server-side recording;
  captures all player POVs plus hidden messages (damage events, KTXstats,
  etc.).
- **BSP v29** — Quake 1 binary space partition map format. Used by
  QuakeWorld. 15 lumps, fully documented.
- **Loc file** — ezQuake-format text file mapping 3D coordinates to
  human-readable zone names (e.g. "rl", "quad", "cross"). Used for
  location-aware voice callouts and analysis.
- **KTXstats** — authoritative match statistics block emitted by the KTX
  QuakeWorld server mod at match end. Transported as a hidden message
  type in the MVD.
- **PVS** — Potentially Visible Set. Pre-computed per-leaf visibility
  cluster stored in the BSP. Conservative upper bound on what can be
  seen from any point in a leaf.
- **Clipnodes** — Q1 BSP v29's collision tree. Separate from the
  rendering BSP (`nodes`/`leaves`). Walked recursively with the player's
  AABB to resolve collision. Hull 0 = point, Hull 1 = standard player
  (32×32×56), Hull 2 = crouch / hipnotic. Q1 does not use brushes;
  `SV_RecursiveHullCheck` is the canonical walk algorithm.
- **BVH** — Bounding Volume Hierarchy. GPU-friendly spatial index used
  by OptiX for ray tracing, built over triangulated BSP faces in this
  project.
- **OptiX** — NVIDIA's C++ ray-tracing API, uses RT cores on RTX GPUs.
- **`SV_RecursiveHullCheck`** — the canonical Q1 BSP collision walk
  algorithm, ~100 LOC in engine source (QuakeSpasm, ezQuake, fteqw).
  Walks the clipnodes tree with a plane-split-based recursion.
- **`construct`** — Python binary-parsing library with a declarative DSL.
- **Corpus** — 1,315 MVDs on `servexeri`'s USB SSD at
  `/mnt/usb-ssd/mimer-demo-watcher/data/firehose/qtv/`, sharded by 24
  QTV server IPs.

## 14. References

- ezQuake source: `~/projects/ezquake-source/` — authoritative client-side
  MVD parser (`src/cl_parse.c`, `src/cl_main.c`).
- MVDSV source: the authoritative server-side MVD parser and re-serializer.
- QuakeSpasm source: canonical `SV_RecursiveHullCheck` reference
  (`world.c`).
- `ericw-tools`: Q1 BSP collision code used during `vis` compilation —
  one candidate reference for ray-parity cross-check.
- `construct` Python library: https://construct.readthedocs.io/
- OptiX 8 documentation (NVIDIA).
- Q1 BSP v29 format reference: the Quake Engine Wiki / Quake 1 BSP file
  format document. 15 lumps, little-endian, versioned `HEADER.version == 29`.
- Existing `demoparser` repo audit: 27 findings documented 2026-04-11.
- Memory: `project_demoparser_north_star.md` — the three locked north-star
  goals.
