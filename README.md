# demopasha

The best QuakeWorld demo parser out there — zero unmined data,
self-validating on a 4090.

**Status:** Phase 0 (GPU POC) complete. All four POCs pass. GO for
Phase A. See the
[POC report](docs/superpowers/reports/2026-04-12-phase0-gpu-poc.md) and
[foundation design spec](docs/superpowers/specs/2026-04-12-demopasha-foundation-design.md).

## Goals

1. **Be the best demo parser out there** — by combining BSP geometry, loc
   files, and demo data into a single fused data layer. No one pillar is
   enough on its own; the value is in the combination.

2. **Leave no data unmined** — every byte of every demo, every entity in
   every BSP, every coordinate in every loc file must be extracted. Silent
   recovery, heuristic fallbacks, and partial decoding are not acceptable
   end states. Unknown byte = hard failure, not a `continue`.

3. **Self-validating, automatically, using the RTX 4090** — the solution
   must prove its own correctness on an ongoing basis without human
   intervention. The 4090 carries real load: GPU clipnode walks for
   player-in-solid validation (24B queries/sec proven), OptiX ray tracing
   for line-of-sight ground truth, BSP visual parity rendering, and
   trajectory anomaly detection.

## Mission

Fuse MVD demo data, BSP v29 map geometry, and loc zone files into a single
protocol-complete, geometry-grounded, continuously self-validating
foundational data layer for QuakeWorld 4on4 analysis.

This is a dedicated data-quality project. It has no opinions about coaching,
patterns, or analysis — those live downstream and depend on this layer.

## Phase 0 results (GPU proof of concept)

| POC | What | Result |
|---|---|---|
| **A** | GPU clipnode walk | 24,048 M queries/sec — 2,400x above target, zero diffs vs CPU |
| **B** | Ray-triangle (brute-force) | 6.9M rays/sec — no BVH, no RT cores; OptiX will be 100x+ faster |
| **C** | BSP face rendering | Unmistakably dm3; geometry pipeline validated end-to-end |
| **D** | Signature test | 0.000% unexplained; 64,251 real positions from 10 demos cross-validated |

## Scope

- **In:** MVD (QW multi-view demo), BSP v29 (QuakeWorld maps), loc files
- **Out:** QWD, vanilla Q1 `.dem`, analysis layer, coaching, Discord delivery

## Architecture

Four workstreams, each with its own pass criterion:

1. **Byte-perfect MVD parser** (Rust) — every byte consumed by a named
   handler; `bytes_unknown == 0` across the full corpus
2. **Independent cross-validation parser** (Python + `construct`) — a
   second witness in a different language with different error modes
3. **Full BSP parse + GPU validation** (Rust + C++/CUDA/OptiX) — five
   layers of GPU proof: visual parity, ray-query parity, player-in-solid,
   PVS soundness, and spatial ground truth
4. **Loc + BSP cross-validation** (Rust) — loc ↔ BSP entity agreement,
   auto-loc generation, map registry

## Crate layout

```
crates/
├── demopasha-mvd/           # Workstream 1 — byte-perfect parser
├── demopasha-ref-parser/    # Workstream 2 — Python construct
├── demopasha-bsp/           # Workstream 3 — full BSP v29 parser
├── demopasha-loc/           # Workstream 4 — loc + cross-check
├── demopasha-gpu/           # Workstream 3 — CUDA/OptiX validation kernels
├── demopasha-state/         # state reconstruction + spatial ground truth
├── demopasha-daemon-cpu/    # servexeri continuous QA daemon
└── demopasha-daemon-gpu/    # pinnaclepowerhouse 4090 daemon
```

## Non-goals

- Replace MIMER's analysis layer
- Cover every Quake engine demo format (QWD/DEM are future projects)
- Realtime in-game use
