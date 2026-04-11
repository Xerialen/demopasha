# demopasha

The best QuakeWorld demo parser out there — zero unmined data, self-validating on a 4090.

**Status:** Pre-code. Foundation design locked 2026-04-12. See
[`docs/superpowers/specs/2026-04-12-demopasha-foundation-design.md`](docs/superpowers/specs/2026-04-12-demopasha-foundation-design.md).

## Mission

Fuse MVD demo data, BSP v29 map geometry, and loc zone files into a single
protocol-complete, geometry-grounded, self-validating foundational data layer
for QuakeWorld 4on4 analysis. Every byte of every demo accounted for. Every
spatial claim grounded in real map geometry. Every parse continuously
cross-validated against independent witnesses.

This is a dedicated data-quality project. It has no opinions about coaching,
patterns, or analysis — those live downstream and depend on this layer.

## Scope

- **In:** MVD (QW multi-view demo), BSP v29 (QuakeWorld maps), loc files
- **Out (this project):** QWD, vanilla Q1 `.dem`, Quake 2 demos, analysis
  layer, coaching, Discord delivery

## Architecture

- `crates/demopasha-mvd/` — byte-perfect MVD parser (Rust)
- `crates/demopasha-ref-parser/` — independent second parser (Python +
  `construct`), for cross-validation only
- `crates/demopasha-bsp/` — full BSP v29 parser, every lump (Rust)
- `crates/demopasha-loc/` — loc parser + BSP cross-check (Rust)
- `crates/demopasha-gpu/` — GPU validation kernels (C++ / CUDA / OptiX)
  called from a Rust host
- `crates/demopasha-state/` — state reconstruction depending on spatial ground
  truth (Rust)
- `crates/demopasha-daemon-cpu/` — servexeri daemon (Rust)
- `crates/demopasha-daemon-gpu/` — pinnaclepowerhouse 4090 daemon (Rust +
  FFI to the C++/CUDA layer)

## Non-goals

- Replace MIMER's analysis layer
- Cover every Quake engine demo format
- Realtime in-game use
