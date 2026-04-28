# mvd_analyzer ⇆ demopasha integration

This is a vendored copy of [galfthan/mvd_analyzer](https://github.com/galfthan/mvd_analyzer)
(via the [Xerialen/mvd_analyzer](https://github.com/Xerialen/mvd_analyzer) fork)
brought into demopasha as a git subtree at `external/mvd_analyzer/`.

The integration design lives in the parent demopasha tree:
[`docs/superpowers/specs/2026-04-28-mvd-analyzer-integration.md`](../../docs/superpowers/specs/2026-04-28-mvd-analyzer-integration.md).

## What's modified vs. upstream

| File | Change |
|---|---|
| `qwdemo/parser/strict.go` | **new** — adds `SetStrictMode(bool)` to the parser. When on, every `warn(...)` also captures a sticky `parseErr` (a `*StrictError` wrapping the first `Warning`) which `ParseOne` returns. Implements demopasha's "unknown byte = hard fail" invariant. |
| `qwdemo/parser/strict_test.go` | **new** — unit tests for strict mode. |
| `qwdemo/parser/parser.go` | **modified** — adds `strictMode` and `parseErr` fields to `Parser`; `ParseOne` calls `takeStrictErr()` after each message. |
| `qwdemo/parser/diagnostic.go` | **modified** — `warn()` calls `strictPromote()` after appending the warning. |
| `qwanalytics/cmd/demopasha-extract/main.go` | **new** — CLI that emits dashboard-compatible JSON in the same shape as `mimer --dump-analysis` (the schema demopasha's `phase0/glue-server.js` already understands). Walks events directly; bucketed snapshots; surfaces strict-mode warnings as `data_quality`. |
| `Makefile` | **modified** — adds `make demopasha-extract` target that builds the CLI into `bin/demopasha-extract`. |

Lenient-mode behaviour is unchanged from upstream — strict mode is purely
opt-in. Existing callers of `parser.Parser` see no new errors.

## How to use

Build:

```bash
cd external/mvd_analyzer && make demopasha-extract
```

Run directly:

```bash
./bin/demopasha-extract <demo>             # lenient (collects warnings, parses through)
./bin/demopasha-extract -strict <demo>     # hard-fail on first unknown opcode
./bin/demopasha-extract -snap-hz 20 <demo> # 20 Hz snapshot bucketing (default 10)
```

Through the dashboard glue server:

```bash
curl -X POST http://localhost:3456/parse \
  -H 'Content-Type: application/json' \
  -d '{"source":"local","path":"/path/to/demo.mvd.gz","parser":"mvd_analyzer","strict":true}'
```

## Syncing from upstream

```bash
# from the parent demopasha repo root
git subtree pull --prefix=external/mvd_analyzer \
  https://github.com/Xerialen/mvd_analyzer.git main --squash
```

After a sync, re-run `go test ./qwdemo/parser/` to confirm the strict-mode
patch still applies cleanly. The patch is concentrated in:

- `qwdemo/parser/strict.go` (new, no merge conflicts possible)
- `qwdemo/parser/parser.go` (two small edits — struct fields + `ParseOne` hook)
- `qwdemo/parser/diagnostic.go` (one line in `warn()`)

If `make test` fails after a sync, the most likely cause is upstream
refactoring of `Parser` struct fields or `ParseOne` flow. Re-apply
manually using the patch files as reference.

## Scope of the integration (what this is *not*)

- This integration does **not** modify `qw-web/` or its WASM bundle.
  Upstream's standalone web UI is untouched and still buildable via
  `make build` / `make serve`.
- This integration does **not** replace `mimer` as the dashboard's
  default parser. The opt-in path is `parser=mvd_analyzer` in the
  glue-server `POST /parse` body. Default remains `mimer`.
- The `demopasha-extract` CLI emits a **subset** of the mimer schema
  today: positions, players, map, data_quality. `kill_events`,
  `item_events`, `static_items`, and `powerup_events` are emitted as
  empty arrays and are a planned follow-up using the analyzer Result.
