# acmacs-whocc incremental-chains → ae port

## Goal

Port the WHO-CC **incremental-chain** workflow (the `chains-202105` engine + web app) from AD
(`acmacs_py.chain202105` + the `chains-202105` aiohttp app, both on the `acmacs` C++ extension)
to **ae**. This is the one substantial AD area still unported. It runs on a **Linux server**
with **SLURM** dispatch (no kateri anywhere). The antigenic-map renderer half is already done —
see the `map-draw-revive` worktree/branch (headless C++ Cairo renderer reproducing AD ChartDraw,
~4% mean pixel-diff). What remains is the Python orchestration + web layer + CLI wiring, and
verifying the chain reproduces AD's coordinates.

Worktree/branch: this dir (`/Users/sarahjames/AC/eu/ae-whocc-chains`, branch `whocc-chains-port`).
**Edit only files in this worktree.** Reference AD read-only. Test outputs go under
`~/AC/eu/ac/results/` (a new subdir), never into pre-existing chain dirs' `.py` files.

## Architecture insight (why this is tractable)

The AD chain engine (`acmacs_py.chain202105`, ~885 LOC / 7 files) is **pure-Python orchestration
that shells out to CLI tools** — it only touches `acmacs.Chart`/`acmacs.merge` in ~11 spots, and
it **already calls ae's `bin/seqdb-chart-populate`**. The heavy work is CLI tools ae already
ships (`chart-relax`, `chart-merge`, `chart-grid-test`, `chart-combine-projections`). Parallelism
is SLURM/local dispatch (`runner.py`) — command-agnostic, already Linux-native.

AD reference: `~/AC/eu/AD/sources/acmacs-py/py/acmacs_py/chain202105/` (engine),
`~/AC/eu/AD/sources/acmacs-whocc/web/chains-202105/` (web app),
`~/AC/eu/AD/sources/acmacs-chart-2/cc/chart-relax-grid.cc` (the optimizer CLI).
Golden data + a per-lab driver example: `~/AC/eu/ac/results/chains-202105/` (e.g.
`h3-hint-cdc/f-20221130.py`, the step `.ace`s under `f-*/`, and `*.grid.json`).

## Work packages

### #1 — CLI parity (`chart-relax-grid`)  ← START HERE (small, unblocks the engine)
The chain invokes `chart-relax-grid -n -d -m --keep-projections [--reorient M] [--no-disconnect-having-few-titers] --grid-json G --threads T source target`.
ae's `bin/chart-relax` already does relax+grid-by-default and **declares** `-n -d -m`,
`--keep-projections`, `--grid-json`, `--no-disconnect-having-few-titers`. Gaps to close:
- **`--grid-json`** is parsed but **not written** — wire it: after the grid-test loop, emit the
  results in AD's grid.json format. Match the schema of an existing file, e.g.
  `ac/results/chains-202105/h3-hint-cdc/f-*/001.*.grid.json`.
- **`--no-disconnect-having-few-titers`** is parsed but **not passed** to `relax()`. Verify the ae
  `relax` binding exposes `disconnect_too_few_numeric_titers` (AD default = disconnect=yes); if the
  binding lacks it, add the option (small `cc/py/chart-v3.cc` change) — otherwise the flag can't be
  honoured. Confirm ae's default matches AD (disconnect on).
- **`--reorient <master>`** is commented out — implement: after relax+grid, procrustes-reorient the
  result to the master's projection 0 over common antigens/sera (no scaling), matching
  `chart-relax-grid.cc`. `chart.orient_to(master)` already exists (the map-draw renderer uses it) —
  reuse it; verify it reorients as AD does (all projections; CommonAntigensSera match).
- **`--threads`** commented out — accept it; simplest is to set `OMP_NUM_THREADS` from it (the chain
  appends `--threads N` for SLURM per-node limiting).
- Provide **`bin/chart-relax-grid`** (symlink or thin wrapper to `chart-relax`) so the ported engine
  needs no command-name change.
- **Verify:** on the small CDC-HINT sample, `chart-relax-grid` reproduces an AD chain step — compare
  the output `.ace` projection-0 **coordinates + stress** and the `.grid.json` to the AD golden.

### #2 — Chain engine (`chain202105` → `ae.whocc.chains`)
Port the 7 files (chain_setup.py, chains.py [IncrementalChain / IndividualTableMapChain fold logic],
maps.py [command builders], run.py, runner.py, log.py, error.py) into `py/ae/whocc/chains/`.
Swaps: `acmacs.Chart`/`acmacs.merge` → `ae_backend.chart_v3`; AD command names → ae `bin/`
(`chart-relax-grid`, `chart-merge`, `seqdb-chart-populate`); keep `runner.py` (RunnerLocal +
RunnerSLURM) essentially as-is. Decide the per-lab driver format (AD `ChainSetupDefault` subclass in
`f-*.py`) — keep the API or adapt. Verify `chart-merge` supports the incremental-merge + column-basis
handling the chain needs (`merge_column_bases`, `extract_column_bases`).

### #3 — Wire in the renderer (DONE upstream)
Replace `chains-202105/py/chart.py` `make_map`/`make_pc` with `ae_backend.map_draw` (from
`map-draw-revive`). **Depends on** that branch being merged/available. Small wiring.

### #4 — Web/page layer (`chains-202105` aiohttp app → ae)
Port `application.py` + `index_page`/`chain_page`/`table_page`/`directories`/`utils` (+ js/css),
~8 files. Renderer-agnostic; swap chart reads → `ae_backend`, rendering → map-draw. Because ae's
renderer is fast in-process C++ (unlike kateri), AD's live-on-demand model is viable — or keep
pre-render + `png/` cache, or host on `py/ae/webserver`.

### #5 — Diagnostic plots (non-map; lower priority)
`whocc-titer-histograms`, column-basis plots, titer-map-distance, merge-matrix → matplotlib. Independent.

### #6 — Fidelity verification (cross-cutting; the real bar)
The maps only match if the **fold** matches. Compare ae chain-step `.ace` **coordinates + stress**
(and `.grid.json`) against AD's cached step outputs, on a small lab first (CDC-HINT), before scaling.
This is the gating correctness item — mirror the `ae-similar` fidelity approach.

## Sequence
#1 → (#2 + #6 together, on the CDC-HINT sample) → #3 → #4 → #5.

## Constraints
- Edit only this worktree. No WHO surveillance data (strain names/titers/serum IDs/sequences) in
  committed ae files, comments, or commit messages — test data stays under `ac/results/`.
- `#3` needs the `map-draw-revive` renderer (separate branch, not yet merged).
