# Phase 0.5 — Foundation Ready for AI

**Date:** 2026-04-16
**Status:** Committed, pre-code
**Author:** DXerialen (via Claude Code brainstorm)
**Repo:** `~/projects/demopasha`
**Precedes:** Phase A (Workstream 1 — byte-perfect parser)
**Builds on:** [Phase 0 report](../reports/2026-04-12-phase0-gpu-poc.md), [foundation spec](2026-04-12-demopasha-foundation-design.md)

---

## 1. Why 0.5 exists

Phase 0 landed GO on all four POCs with massive headroom — the 4090 walks BSP
clipnodes at 24 B queries/sec, brute-force ray tracing at 6.9 M rays/sec,
0.000 % unexplained player-in-solid hits. The foundation spec's next
scheduled step is Phase A (byte-perfect Rust parser, ~3 weeks).

Phase 0.5 is a ~5-week insert between Phase 0 and Phase A. It exists because
of two insights that emerged after Phase 0:

1. **ParadokS's qw-eventlog repo** (github.com/ParadokS81/qw-eventlog) was
   explicitly prepared as a handoff to this project. It is a third
   independent implementation of the MVD event surface — not a dependency
   but a witness. The foundation spec's §5.2 "two-witness rule" (Rust ↔
   Python `construct`) is straightforwardly stronger as a three-witness
   rule, and the third witness exists today.

2. **The long-term vision is AI-driven tactical analysis** of individual
   skill and team play. The foundation spec treats "best MVD parser" as the
   mission. But AI-driven analysis needs a specific *shape* of foundation
   that the foundation spec does not explicitly prioritise: full-rate
   positions, wall-aware spatial truth (LOS / cover / real distance / PVS
   membership), and accurate event attribution. The 4090 + OptiX is exactly
   what delivers the first two; Workstream 1 delivers the third. Reframing
   OptiX as "data layer for future AI analysis" — not just validation —
   is what motivates spending five weeks on it before Phase A begins.

Phase 0.5 is also the right moment to invert the spec's implied order. The
foundation spec assumes parser-then-validator. Phase 0.5 builds the
validator first, so Phase A's parser is born into a running validation
harness instead of being bolted onto one.

## 2. Mission reframe — foundation for AI-driven tactical analysis

The long-term goal, on the far side of Phases A–D, is an AI layer that can
answer questions like:

- "Was that a coordinated team push or a scattered rush?"
- "Did player X have information advantage when they committed to the quad
  room?"
- "Was this a trade or a pick — who had LOS to whom in the preceding 500 ms?"

No amount of parser polishing answers those. They require a foundation
with these properties, *all* of which Phase 0.5 sets up directly or
unblocks:

| Property | Provider | Phase 0.5 contribution |
|---|---|---|
| Position coverage at full 77 Hz | Phase A parser (not downsampled in state layer) | Skeleton emits no positions yet; dashboard surfaces the gap explicitly |
| Line-of-sight booleans per frame per player pair | OptiX through parsed BSP faces | WS3.5 prototype kernel in Week 2 |
| Wall-aware distance through real geometry | OptiX through parsed BSP | Same kernel |
| Cover state / flanking geometry | OptiX geometric queries on BSP | Unblocked by WS3.5 prototype |
| PVS cluster membership per position | WS3.4 soundness check, parsed PVS | Wired in Week 2 |
| Accurate kill attribution, weapon, backpack ownership | Phase A parser (byte-perfect, no `"unknown"`) | Out of scope for 0.5; surfaced in Mission dashboard |
| Frame-perfect event timing | Phase A parser | Out of scope for 0.5 |

Phase 0.5 doesn't build the AI layer. It builds the GPU-backed
spatial-truth layer that the AI layer will consume — and ensures that when
Phase A's parser arrives, it enters a validation environment that catches
errors immediately.

## 3. Scope — three moves in five weeks

Three moves, serialized by risk-first ordering (OptiX first because its
feasibility is the least measured):

1. **OptiX spike + integration (Week 1–2).** Prove OptiX delivers hundreds
   of millions of rays/sec on dm3's BVH, then integrate into three of the
   five GPU validation layers from foundation spec §5.3.1: ray-parity (3.2),
   PVS soundness (3.4), and prototype spatial ground truth (3.5 — LOS
   queries).

2. **qw-eventlog Witness #3 + skeleton parser (Week 2–3).** Vendor
   qw-eventlog into the repo. Run a 2-way diff between mimer and qw-eventlog
   across all 1,315 demos; publish the "prior-art disagreement" report as a
   forensic artefact. Bootstrap `crates/demopasha-mvd` as a match-complete
   event emitter (not byte-perfect, not Phase A) to turn the harness 3-way.

3. **Nightly visual-parity loop + Mission dashboard (Week 4).** SQLite QA
   schema on servexeri, pinnacle GPU daemon processing a per-demo queue,
   dashboard Mission tab showing live progress against both Phase 0.5's
   gates and the foundation spec's §11 end-state.

Week 5 is buffer: determinism experiment, first corpus end-to-end run,
report, Phase A go/no-go.

## 4. Non-goals — what Phase 0.5 is NOT

Hard boundaries, to prevent scope creep from Phase A or Phase C:

- **Not byte-perfect.** No `bytes_unknown == 0` bar on the skeleton parser.
  No `cargo fuzz`. No reconstruction-sufficiency roundtrip. Those define
  Phase A.
- **No position emission in the skeleton.** `PositionSample` events stay
  behind Phase A's byte-perfect door because position decoding is where FTE
  extensions, delta encoding, and the 3.5 % `U_*` failure concentrate.
  Solve that properly in Phase A.
- **No analysis, no coaching, no ML, no Discord.** Those are out of the
  whole project per foundation spec §3.
- **No production hardening.** The glue servers and dashboard stay "POC
  duct tape" per CLAUDE.md until the project moves out of `phase0/` and
  toward production Cargo workspaces.
- **Not all five GPU validation layers.** Only three of five: ray-parity
  (3.2), PVS soundness (3.4), spatial ground truth *prototype* (3.5).
  Visual parity (3.1 — wgpu renders vs ezQuake SSIM) and the full 3.5
  corpus sweep stay Phase C work. Phase 0.5's 3.5 prototype answers "does
  LOS work on dm3," not "sweep 16 B rays across the corpus."
- **No automated pixel-diff regression gate** until the Week 5 determinism
  experiment decides whether pixel-diff is a viable oracle. The
  visual-parity side ships as a *human-facing artefact* (rendered frames
  in the dashboard, worst-10 queue for eyeballing) — not a pass/fail
  signal — until determinism is verified.

## 5. Week-by-week

Target start 2026-04-20, target finish 2026-05-22 (5 weeks). Flexible;
each week has its own success bar that must be green before the next
begins.

### Week 1 — OptiX spike (pinnacle)

**Goal:** Install OptiX 8 SDK on pinnacle, build a BVH over dm3's
triangulated faces, fire 1 M rays, measure throughput.

Stays in `phase0/` as throwaway (this is a spike, not integrated code).
Reuses the same Python `bsp_parse.py` → flat-binary pipeline from Phase 0.

**Tasks:**

- Install OptiX 8 SDK + verify against NVIDIA's `optixHello` example
- Port POC B's brute-force ray-triangle kernel to use OptiX BVH traversal
  with `optixTrace`
- Benchmark against 1 M random rays (same origin/direction distribution as
  POC B)
- Spot-check 1,000 hits against the POC B brute-force reference — 0 diff
  required
- Write brief report with measured throughput

**Success bar:** ≥ 100 M rays/sec sustained, 0 diff on spot check. Miss →
reassess (see Risks §12).

### Week 2 — OptiX integration + qw-eventlog vendoring (pinnacle + quakeboot)

**Goal:** Promote OptiX from spike to integrated validation layer; start
the 2-way witness diff.

**Pinnacle side:**

- Create `Cargo.toml` workspace at repo root with initial members
- Create `crates/demopasha-gpu/` — Rust host + C++/CUDA/OptiX kernels via
  FFI (foundation spec §6 language matrix)
- Migrate Week 1's OptiX kernel into the crate
- Implement three validation kernels:
  - **3.2 ray-parity:** 10 M rays on dm3 via OptiX BVH, diff vs POC B
    brute-force reference
  - **3.4 PVS soundness:** sample 1,000 points per leaf, ray-trace to every
    other leaf, confirm parsed PVS is a superset of measured visibility
  - **3.5 LOS prototype:** given two positions, return boolean "clear path?"
    through the BSP face BVH. Test cases include hand-picked pairs with
    expected results (two players either side of a known wall → blocked;
    two positions in the same room → clear)

**Quakeboot side:**

- Vendor qw-eventlog under `vendor/qw-eventlog/` (git subtree or submodule,
  pinned to the `ParadokS81/qw-eventlog` handoff repo's HEAD at vendoring
  time; that repo is frozen upstream against Slipgate commit `2c584b4`)
- Write `phase0/diff_witnesses.py` that runs both mimer and qw-eventlog on
  every demo in the corpus, field-diffs events, writes results to SQLite
- Produce the **prior-art disagreement report** as
  `docs/superpowers/reports/2026-05-??-prior-art-diff.md` (date filled in
  when published)

**Success bar:**

- OptiX kernels: ray-parity 0 diff on dm3; PVS-soundness 0 violations on
  dm3; LOS prototype returns sensible answers on hand-picked position
  pairs
- Disagreement report published, covering all 1,315 demos, quantifying
  mimer ↔ qw-eventlog agreement rate by event type

### Week 3 — `demopasha-mvd` skeleton (quakeboot)

**Goal:** Bootstrap Rust event emitter; turn the harness 3-way.

**Tasks:**

- Create `crates/demopasha-mvd/` with MVD frame walker and event emitter
- Emit these 12 event types (match-complete, zero positions):
  - `DemoStart`, `MatchStart`, `MatchEnd`
  - `Spawn`, `ItemPickup`, `ItemRespawn`
  - `Kill`, `PlayerDeath`, `FragCountChange`, `DamageDealt`
  - `ChatMessage`, `ConsoleMessage`
- **Explicitly deferred to Phase A:** no byte accounting, no `bytes_unknown`
  tracking, no fuzzing, no FTE extension parse, no reconstruction
  sufficiency, no `PositionSample` emission. Unknown bytes may be silently
  skipped in the skeleton — this is the one place in the project where
  that rule doesn't apply, and it's justified because the skeleton's
  purpose is semantic-event cross-check, not byte-completeness. See
  Risk R4 §12 for the concession rationale.
- Extend `diff_witnesses.py` to a 3-way diff (mimer ↔ qw-eventlog ↔
  demopasha-mvd)
- Write results to SQLite with enough granularity that the Mission tab can
  compute triple-agreement rate per event type

**Success bar:** demopasha-mvd parses every demo in the corpus without
panicking; 3-way harness runs to completion on the full corpus; SQLite
populated.

### Week 4 — Nightly loop + Mission dashboard (pinnacle + servexeri + quakeboot)

**Goal:** Put everything on a recurring schedule and make the goals
visible.

**Pinnacle:** systemd user timer fires `demopasha-gpu-nightly.service`
once per day; processes each demo through WS3.2 / 3.4 / 3.5 via the OptiX
kernels, writes results to SQLite.

**Servexeri:** the SQLite QA DB lives at
`/mnt/usb-ssd/mimer-demo-watcher/data/demopasha-quality.db` per foundation
spec §7. Accessed over SSH from pinnacle (writes) and from the glue
server on quakeboot (reads).

**Quakeboot:** the dashboard gets a new **Mission tab** between Replay and
Validator. Four bands — see §9 for full layout.

**Success bar:** Mission tab reflects SQLite data within 60 s of a new QA
row landing; nightly timer has run unattended for ≥ 24 h without
intervention before the end of Week 4.

### Week 5 — Buffer: determinism experiment + first corpus sweep + Phase 0.5 report

**Determinism experiment (first half of week).** Render dm3 twice on
pinnacle via headless ezQuake (or FTEQW, if no ezQuake headless build is
available — FTEQW is already deployed on pinnacle port 8088 per the
Validator POC spec). Same build, same settings. Check whether
framebuffers are bit-identical. Result drives visual-parity strategy for
Phase C — pixel-diff if identical, structured-state diff if not. Write up
as `docs/superpowers/reports/2026-05-??-render-determinism.md`.

**First full corpus sweep (second half).** Run the nightly loop manually
end-to-end; verify the Mission tab populates correctly; identify any
SQLite schema or harness issues.

**Phase 0.5 report:** `docs/superpowers/reports/2026-05-??-phase05-report.md`
with measured numbers against each week's success bar and a go/no-go for
Phase A.

**Success bar:** Phase 0.5 report signed off; go for Phase A.

## 6. The `demopasha-mvd` skeleton

The skeleton is the first inhabitant of the Cargo workspace described in
foundation spec §10. It deliberately does *less* than Phase A's target
parser:

| Aspect | Skeleton (Phase 0.5) | Phase A parser |
|---|---|---|
| Protocol coverage | Enough to emit 12 event types | All svc_* opcodes 0–94 |
| Unknown bytes | May silently skip (documented) | Hard failure |
| `bytes_unknown` accounting | Not tracked | Must be 0 |
| Fuzzing | None | `cargo fuzz` harnesses |
| FTE extensions | Only what the 12 events require | Full 55–94 trace |
| Reconstruction sufficiency | No | Semantically-equivalent roundtrip |
| `PositionSample` emission | Not emitted | 77 Hz, per-`svc_playerinfo` |
| Hidden messages 4, 5, 6, 9, 10, 11 | Types 10 (KTXstats) and 11 (timestamp) for match lifecycle only | All types exhaustively |

The skeleton's single contract: emit the same 12 event variants
qw-eventlog emits, in chronological order, so the diff harness can
cross-check them.

When Phase A begins, the skeleton becomes the starting point of the
byte-perfect parser — its event emission interface stays stable while its
internals get the full Workstream 1 treatment.

## 7. OptiX integration — three validation pillars

Foundation spec §5.3.1 names five GPU validation layers. Phase 0.5
implements three (the three where OptiX is load-bearing). The other two
(visual parity via wgpu SSIM, full 3.5 corpus sweep) stay Phase C.

**3.2 — ray-parity vs a Q1 BSP reference.** Fire 10 M random rays through
our parsed BVH via OptiX; compare hit distances to POC B's CPU/CUDA
brute-force reference. Any disagreement means our face / edge / surfedge /
vertex / plane decoding has a bug. On OptiX this is sub-second per map.

**3.4 — PVS soundness.** For each leaf, sample 1,000 positions inside;
ray-trace from each to every other leaf. Record which leaves are reached
by rays. The parsed PVS should be a superset. Any reached leaf that PVS
*didn't* claim → PVS decoder bug.

**3.5 — LOS prototype (seed for the spatial ground-truth layer).** Given
two 3D positions, return a boolean: is there a clear line-of-sight between
them through the parsed BSP faces? In Phase C this scales to ~16 B rays
across the corpus; in Phase 0.5 we prove the kernel works on dm3 with
hand-picked position pairs. Same kernel becomes the foundation of
wall-aware distance, cover booleans, and every spatial-truth feature the
future AI layer will consume.

All three share one OptiX BVH over the triangulated BSP faces, built once
per map and reused for the entire corpus's demos on that map. BVH build
cost amortizes to nothing.

## 8. Triple-witness harness

Three independent MVD event-stream implementations, each with a different
error surface:

| Witness | Language | Underlying protocol impl | Independence |
|---|---|---|---|
| **mimer** | Rust | demoparser's own `src/mvd/` | The existing broken baseline — the thing we're eventually replacing |
| **qw-eventlog** | Rust | Vikpe's `quake` crate | Third-party, frozen at Slipgate commit `2c584b4`; event-centric abstraction over `quake` |
| **demopasha-mvd skeleton** | Rust | Our own | From-spec, first-principles |

All three consume raw MVD bytes and emit event streams that can be
field-diffed.

### Disagreement report (Week 2 deliverable)

Before demopasha-mvd exists, the 2-way mimer ↔ qw-eventlog diff produces
the **prior-art disagreement report** — a forensic artefact independent of
Phase 0.5's other deliverables. It answers:

- Across all 1,315 demos, what fraction of events do mimer and qw-eventlog
  agree on, by event type?
- Which demos exhibit the largest per-type disagreement? (These become the
  "hard cases" we feed to demopasha-mvd first.)
- Which mimer findings from the 2026-04-11 audit are quantified at event
  scale?

The report is useful even if Phase 0.5 otherwise fails. It's banked
information.

### 3-way harness (Week 3+)

Once demopasha-mvd emits events, the harness becomes 3-way:

- **All three agree** → high confidence, event marked green
- **2 agree, 1 disagrees** → the minority is under suspicion
- **All three disagree** → protocol ambiguity or spec bug, manual
  adjudication required

**Weakness to acknowledge:** qw-eventlog is best-effort — it *tolerates*
unknown bytes by skipping them. If demopasha-mvd also silently skips the
same bytes (as the skeleton is allowed to), the two can agree on a missing
event without noticing its absence. This is why byte-completeness is not
qw-eventlog's job — that guard stays with Workstream 2's future Python
`construct` witness in Phase B.

## 9. Mission dashboard tab

New tab in `phase0/dashboard.html`, between Replay and Validator. Single
source of truth is the SQLite QA DB on servexeri, read via the glue server.

### Four bands, top to bottom

**1. North-star scorecard** (the §11 bars, made live)

- `quality_score == 1.0` demos: `X / 1,315`
- Continuous unattended uptime: `HH:MM:SS` (target 72 h)
- Latest ingest-to-QA time: `N s` (target ≤ 5 min)
- Flagged maps / silent fallbacks / `"unknown"` tags: `0 / 0 / 0` (red
  until all three zero)

**2. Workstream health** (four sparkline rows)

- **WS1 byte-perfect parser** — `bytes_unknown` sum, parse errors, panics
  from fuzzing
- **WS2 witnesses** — triple-witness agreement rate %, roundtrip OK %,
  KTXstats / MVDSV cross-check OK %
- **WS3 GPU validation** — OptiX rays/sec, ray-parity diff count,
  positions-inside-solid (unexplained), PVS soundness violations
- **WS4 loc + BSP** — maps with green QA, loc hard-fails

**3. AI-foundation readiness** (the long-term vision made measurable)

- Position sample rate: `1 Hz` (mimer) → goal `77 Hz` (demopasha)
- Spatial features per demo: LOS ✅ / wall-aware distance ✅ / cover
  state ⏳ / PVS membership ✅
- Kill-attribution confidence: `X %` (mimer baseline `54 %` on backpacks)
- `"unknown"` weapon tags: count (goal 0)

**4. Worst-10 demo queue** — clickable list of lowest-scoring demos, each
opens directly in the Validator tab for human eyeballing.

Plus an **alert row** pinned above tab nav: red banner when any
must-be-100 % metric slips, mirroring the `notify-send` trigger on
quakeboot.

### Implementation notes

- Single-file HTML extension; don't graduate the dashboard out of `phase0/`
  until the project itself graduates
- Refresh cadence: 30 s polling while the tab is open, no push / SSE /
  websockets (keeps the glue server simple)
- All metric formulas documented next to their widgets so users can audit
  them — no mystery numbers
- Red banner at top when any must-be-100 % metric fails; banner is
  dismissible but reappears on next refresh if the condition persists

## 10. Success criteria for Phase 0.5

Phase 0.5 is green when **all** of these hold, at end of Week 5:

1. OptiX spike hit ≥ 100 M rays/sec on dm3 BVH (Week 1)
2. Ray-parity kernel (3.2) returns 0 diff on dm3 against brute-force
   reference (Week 2)
3. PVS soundness kernel (3.4) returns 0 violations on dm3 (Week 2)
4. LOS prototype (3.5) returns expected booleans on a hand-picked test
   set (pairs either side of walls → blocked; pairs in the same room →
   clear) (Week 2)
5. Prior-art disagreement report published, covering all 1,315 demos
   (Week 2)
6. `crates/demopasha-mvd` skeleton parses all 1,315 demos without
   panicking (Week 3)
7. Triple-witness harness produces per-demo SQLite rows with agreement
   rates (Week 3)
8. Nightly timer on pinnacle runs unattended for ≥ 24 h before end of
   Week 4
9. Mission dashboard tab live, showing all four bands, reading from
   SQLite (Week 4)
10. Determinism experiment concluded; visual-parity strategy for Phase C
    decided (Week 5)
11. Phase 0.5 report committed with measured numbers against each success
    bar (Week 5)

Any red means we pause, investigate root cause, and decide whether to
fix-and-continue or re-scope before Phase A begins.

## 11. Machine topology

Per foundation spec §7:

| Machine | Role in Phase 0.5 |
|---|---|
| **pinnaclepowerhouse** (192.168.86.20, 4090) | OptiX spike, OptiX kernels, nightly GPU daemon, headless ezQuake for determinism experiment |
| **servexeri** (192.168.86.33) | SQLite QA DB, demo corpus source of truth, future home of CPU daemon (not in 0.5) |
| **quakeboot** (192.168.86.34, 4070) | Rust crate dev, `demopasha-mvd` skeleton build+test, dashboard viewer, glue server read-only SQLite access |

Orchestration is SSH-based, consistent with Phase 0. No VPN changes, no
new services on quakeboot beyond the existing glue server.

## 12. Risks and mitigations

### R1 — Rendering determinism for visual parity has no guaranteed oracle

Pixel-diff against headless ezQuake presumes the engine renders the same
demo to byte-identical framebuffers twice. In practice Q1 engines drift on
lightmap lookups, interpolation timing, particle RNG, and driver state.
If drift exists, pixel-diff is a fuzzy judge that either false-alarms
constantly or misses real bugs.

**Mitigation:** Week 5's determinism experiment runs the same demo twice
and compares. Outcome drives Phase C strategy:

- **Framebuffers match** → pixel-diff is a viable gate. Keep on the
  roadmap.
- **Framebuffers differ** → structured-state diff becomes the primary gate
  (positions, events, flags per frame — mathematically exact). Rendered
  frames stay as human-facing artefacts in the dashboard, not a pass/fail
  signal.

Phase 0.5 ships no pixel-diff gate regardless; the question is what Phase
C builds.

### R2 — qw-eventlog is a weak witness for byte-completeness

qw-eventlog tolerates unknown bytes by design. demopasha's pass criterion
(in Phase A) is `bytes_unknown == 0`. If we let qw-eventlog judge
demopasha's byte-completeness, it'll silently agree with a buggy demopasha
because it's ignoring the same bytes.

**Mitigation:** qw-eventlog's harness role is scoped to **semantic events
only** — kills, pickups, chat, match lifecycle. Byte-completeness
judgement stays with Workstream 2's Python `construct` second parser
(Phase B), which shares demopasha's strict discipline. The Mission
dashboard's WS2 band distinguishes between these two witness axes.

### R3 — OptiX integration is its own project with measurable downside risk

OptiX SDK install, Rust↔C++ FFI, BVH management, GPU memory ownership —
realistic size is 2–3 weeks, and the 500 M–2 B rays/sec projection is
extrapolated from POC B's brute-force number, not measured with OptiX.

**Mitigation:** Week 1 is a bounded spike with a hard exit condition (≥
100 M rays/sec or rescope). If it stalls, Phase 0.5 pivots: move #1 drops
entirely (no OptiX integration, no WS3.5 LOS prototype), and Phase 0.5
delivers moves #2 and #3 only — witness harness + Mission dashboard on
existing CPU/brute-force data. That's still a useful deliverable and
preserves the Phase A start on schedule. WS3.2, 3.4, 3.5 all revert to
Phase C with the original foundation-spec timeline.

### R4 — Skeleton parser's "silent skip" concession contradicts the spec's hard rule

Foundation spec §5.1 says unknown byte = hard failure, no `continue`. The
skeleton deliberately violates this in Phase 0.5 to ship on time, under
the rationale that the skeleton's purpose is semantic-event emission,
not byte-completeness.

**Mitigation:** Document the skeleton's silent-skip concession prominently
in its `README.md`, its crate-level doc comment, and in this spec's §6.
When Phase A begins, the first task is lifting the skeleton to the
hard-failure discipline before adding any new event types. The skeleton
is an explicit, time-boxed exception — not a precedent.

## 13. Relationship to other specs

- **`2026-04-12-demopasha-foundation-design.md`** — the authoritative
  mission. Phase 0.5 does not modify it; it inserts a new phase between
  its Phase 0 and Phase A.
- **`2026-04-12-validator-poc-design.md`** — the current Validator tab's
  design. Phase 0.5 adds the Mission tab alongside but does not alter the
  Validator tab.
- **`2026-04-12-map-visuals-design.md`** — the dashboard's visual
  contract. Mission tab inherits the existing color palette; no new
  design decisions needed.
- **`docs/superpowers/reports/2026-04-12-phase0-gpu-poc.md`** — the
  measured numbers Phase 0.5 builds on (24 B clipnode queries/sec, 6.9 M
  brute-force rays/sec, 0.000 % unexplained).

## 14. Open questions

- **OptiX 8 vs OptiX 7.** OptiX 8 is current (2024). Week 1's first
  decision is which to install — 8 unless we discover ecosystem blockers.
  Revisit in the spike.
- **qw-eventlog vendoring mechanism.** git subtree, git submodule, or
  Cargo.toml `[patch]` pointing to a local clone. Decide in Week 2 based
  on which makes the Cargo workspace cleanest.
- **Dashboard refresh strategy.** 30 s polling is the stated baseline. If
  the SQLite QA DB grows large, we may need paginated queries. Revisit if
  measured query latency > 500 ms.
