# mvd_analyzer integration into demopasha

**Date**: 2026-04-28
**Status**: implementation in progress
**Author**: Claude (autonomous), reviewed by Codex per CLAUDE.md rule

## Problem

demopasha's mission (foundation spec, 2026-04-12) is a byte-perfect MVD
parser with **unknown byte = hard fail** semantics, validated by an
independent Python `construct` witness and GPU-grounded BSP geometry.
Phase 0 proved the GPU layer; the parser layer (Workstream 1, Rust)
has not yet started. In the meantime the dashboard shells out to
the *external* `mimer` binary at `~/projects/demoparser/target/release/mimer`,
which is the exact stack demopasha exists to replace.

`galfthan/mvd_analyzer` is a mature Go MVD parser + analytics + WASM
web stack. Its layered architecture (`qwdemo` ingestion → `qwanalytics`
analysis → `qw-web` UI) and clean event-stream contract make it a
strong candidate to:

1. Replace `mimer` as the dashboard's MVD parsing source (in-tree, no
   external binary dependency, builds with `go build`).
2. Serve as the **second-witness** parser for Workstream 2's
   cross-validation requirement once the Rust parser is built — a
   "different reasoning path, declarative-ish event stream" parser
   alongside the eventual Python `construct` witness.
3. Provide rich analyses (frags, items, weaponPickups, backpacks,
   timeline) that the demopasha dashboard already wants but currently
   re-derives from mimer.

## Tension with demopasha's hard rule

mvd_analyzer's parser is **lenient by default**: unknown svc opcodes,
unknown temp-entity types, and unknown hidden message types are logged
as `Warning` records (in diagnostic mode) and the rest of the payload
is abandoned, but parsing continues. demopasha invariant #1 forbids
this: "unknown byte = hard failure, never `continue`".

Resolution: add an opt-in **strict mode** to the vendored parser.
When `Parser.SetStrictMode(true)` is set, every `warn(...)` call also
records a sticky `parseErr`, and `Parser.ParseOne()` returns that
error after the message. Diagnostic mode is implicitly enabled in
strict mode (since strict needs the warning string to surface a
useful error).

mvd_analyzer's own UI keeps the lenient default — flipping to strict
upstream would be a behaviour change the upstream maintainer didn't
ask for. The strict path is purely additive; no existing callers see
new errors.

## What gets vendored

The fork at `https://github.com/Xerialen/mvd_analyzer` is added to
demopasha as a git **subtree** at `external/mvd_analyzer/` (squash
merge, no full upstream history pollution). Subtree was chosen over
submodule because:

- Submodules require a `git submodule update --init` step everywhere
  demopasha is checked out — including on `pinnaclepowerhouse` and
  `servexeri`. Subtree is invisible to consumers.
- The strict-mode patch lives in the vendored copy. Submodule pin
  semantics make patch + sync awkward; subtree merge is straightforward.
- The user explicitly asked for a fork. Subtree preserves the
  attribution and lets us pull future upstream changes via
  `git subtree pull --prefix=external/mvd_analyzer`.

## What gets built

1. `external/mvd_analyzer/qwdemo/parser/strict.go` — strict-mode
   plumbing (new file, no edits to existing files except a few
   one-line additions to `parser.go` to consult `parseErr`).

2. `external/mvd_analyzer/qwanalytics/cmd/demopasha-extract/` —
   a new CLI mode that emits the **mimer-compatible** dashboard JSON
   shape (`{position_timeline: {players, snapshots, item_events,
   static_items, powerup_events}, kill_events, data_quality, map}`).
   This is what `glue-server.js` already understands, so the dashboard
   needs zero changes.

3. `phase0/glue-server.js` — adds optional `parser` and `strict` fields
   to the `POST /parse` JSON request body (`{"parser": "mvd_analyzer",
   "strict": true}`). Default remains mimer. `strict: true` is rejected
   with HTTP 400 unless `parser: "mvd_analyzer"` is also set, since
   mimer cannot enforce demopasha's hard-fail invariant. SSH and SCP
   invocations are switched to argv-array `spawnSync` (no shell
   interpolation of demo filenames).

4. `external/mvd_analyzer/README.md` — overlay note pointing at this
   spec and explaining the vendoring contract.

## What is explicitly *not* in scope

- Replacing `mimer` as the default dashboard source. Until the
  cross-validation passes against the existing baseline scorecards,
  `mimer` stays the default. The new path is opt-in.
- Bringing mvd_analyzer's WASM bundle into the dashboard. The dashboard
  currently uses HTTP `POST /parse` — moving to in-browser WASM is a
  separate UX decision.
- Replacing `qw-web` with `dashboard.html`. They serve different
  purposes (mvd_analyzer = standalone analyzer; demopasha dashboard =
  validator with BSP overlay). They coexist.
- Modifying anything under `qwanalytics/mapgen/` — that uses BSPs in
  a way that overlaps with `phase0/render/` but is a separate
  geometry pipeline. Reconciliation belongs in Phase A.
- Touching the upstream lenient-mode parser behaviour. Strict mode
  is purely additive.

## Cross-validation use (future)

Once the Rust parser (Workstream 1) lands, the integration plan is:

```
demo bytes
  ├── Rust parser (demopasha-mvd)  ──► event stream A
  └── mvd_analyzer (this vendor)   ──► event stream B  (strict mode)

  ────────────► reconciler asserts A ≡ B per-event
```

`bytes_unknown == 0` from both, modulo documented disagreement
categories (e.g. mvd_analyzer abandons payload after an unknown opcode
in lenient mode; in strict it fails — equivalent for the
"valid demo" set we run for cross-validation).

The Python `construct` witness from the original spec (Workstream 2)
remains planned. mvd_analyzer is a *third* witness in different
language (Go), not a replacement for the Python one.

## Success criteria for *this* integration

1. `cd external/mvd_analyzer && make test` passes after strict-mode
   patch (no upstream test regressions).
2. `go run ./external/mvd_analyzer/qwanalytics/cmd/demopasha-extract <demo>` outputs JSON
   that `phase0/glue-server.js` can transform identically to the
   current mimer pipeline (same fields, snapshots line up at the same
   times, kill events match within tolerance).
3. Strict mode on the Phase 0 corpus of 10 dm3 demos produces zero
   warnings (i.e. they parse cleanly under demopasha's invariant). If
   any do produce warnings, document the warning categories — that
   IS the value of the cross-check.
4. Lenient mode behaves identically to upstream `qw-analyze` for the
   same demo (output JSON byte-identical to upstream JSON for at
   least one corpus demo).
5. Codex review passes per `~/.claude/CLAUDE.md` global rule.

## Out-of-band coordination

- Upstream PR back to `galfthan/mvd_analyzer`: deferred. Strict mode is
  useful upstream too, but submitting a PR is a non-goal of this
  vendoring step.
- Future sync: `git subtree pull --prefix=external/mvd_analyzer
  https://github.com/Xerialen/mvd_analyzer.git main --squash`.
  Strict-mode patch must be re-applied on top of any pull (it lives
  in `external/mvd_analyzer/qwdemo/parser/strict.go`, a new file, so
  conflicts will be limited to the parser.go hook lines).
