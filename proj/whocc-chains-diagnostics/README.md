# whocc-chains diagnostic plots

Three standalone diagnostic plotting tools, ported from the AD (acmacs-whocc)
originals to self-contained Python + matplotlib on top of `ae_backend.chart_v3`.

They are **analysis tools, not part of the chains web app**. Each reads charts
directly and computes everything itself — no shelling out to AD's
`chart-export` / `acmacs_draw_backend` / the C++ histogram tool / R.

| tool | AD original | reads | plots |
|------|-------------|-------|-------|
| `whocc-column-bases-plot-for-chain.py` | `whocc-column-bases-plot-for-chain` (py, PdfCairo) | a chain output **directory** | per-serum column basis (log2 max titre) vs table-step index; one line per serum + an "All sera" page |
| `whocc-plot-titer-map-distances.py` | `whocc-plot-titer-map-distances` (Rscript) | one **chart with a projection** | per-serum grid of logged-titre (y) vs map-distance (x): scatter (+jitter), linear regression, LOWESS, red `y = column_basis − distance` line |
| `whocc-titer-histograms.py` | `whocc-titer-histograms` (py → C++ `whocc-histogram-of-titers`) | one or more **charts** | histogram of titre values (bar per distinct titre string, or per log2 dilution bucket) |

Each script is fully self-contained (no shared module) so the three can be
committed independently.

## Dependencies

- **matplotlib** (the only extra dependency; numpy is already present in the build python).
  scipy/statsmodels are **not** required — the LOWESS curve is implemented in numpy.
- If matplotlib is missing, install it into the build python (Homebrew `python@3.14`
  ships without a CA bundle, hence `SSL_CERT_FILE`):

  ```sh
  SSL_CERT_FILE=/etc/ssl/cert.pem \
    python3 -m pip install --user --break-system-packages matplotlib
  ```

  (This is how it was installed for this work package.)

## Running

From the worktree root, source the ae environment first (sets `PYTHONPATH` to
`build/` + `py/`, and `SEQDB_V4` etc.):

```sh
source ae-env.sh

# 1. column bases across a chain
python3 proj/whocc-chains-diagnostics/whocc-column-bases-plot-for-chain.py \
    <chain-dir> -o out/column-bases.pdf

# 2. titre vs map distance for a relaxed step (needs a projection)
python3 proj/whocc-chains-diagnostics/whocc-plot-titer-map-distances.py \
    <step>.incremental.ace -o out/titer-map-distances.pdf

# 3. histogram of titres for a table / set of tables
python3 proj/whocc-chains-diagnostics/whocc-titer-histograms.py \
    <table>.ace [<more>.ace ...] -o out/titer-histogram.pdf
```

Output extension `.pdf` (multi-page where relevant) or `.png` is inferred from `-o`.
Run any tool with `-h` for its options.

### whocc-titer-histograms modes

The AD C++ tool draws one bar per distinct titre *string* (ideal for discrete HI
tables: 10, 20, 40, …, `<10`, `>1280`). For continuous titres (HINT /
neutralisation charts) that would be hundreds of one-count bars, so this port
adds a `log2` mode that buckets titres into doubling-dilution bins on a log2
axis, with `<` / `>` / `*` grouped into their own bars. `--mode auto` (default)
picks `categorical` when there are few distinct regular titres, else `log2`.
Missing (`*`) cells are counted as their own bar (as the C++ tool does); use
`--drop-missing` to omit them.

## Deviations from the AD originals

- **Self-contained inputs.** AD tool 1 consumed a pre-made JSON of per-serum
  column-basis-per-step; here we walk the chain directory's numbered steps and
  read each step's `.merge.ace` (bare table for step 000) directly. AD tools 2/3
  consumed `chart-export` output / a C++ binary; here titres, map distances and
  column bases are read straight from `ae_backend.chart_v3`.
- **Layout, not pixels.** Multi-panel matplotlib figures replace the bespoke
  PdfCairo / R page layouts. Same axes, quantities and overlays; pixel fidelity
  is not a goal for these diagnostics.
- **LOWESS** is a numpy tricube-weighted local linear regression (R used
  `loess()`); curves are visually equivalent for these data.
- **Histogram `log2` mode** is new (see above); `categorical` mode reproduces the
  AD C++ behaviour.

## Demo outputs

Generated against the CDC-HINT test chain
`~/AC/eu/ac/results/whocc-chains-port-test/chains/f-20221130-none/` into
`~/AC/eu/ac/results/whocc-chains-port-test/diagnostics/`:

- `column-bases-cdc-hint.pdf` — 9 steps, 15 sera.
- `titer-map-distances-cdc-hint.pdf` — from `008.*.incremental.ace` (15 sera grid).
- `titer-histogram-cdc-hint.pdf` — from `000.20200122.ace` (auto → log2, continuous titres).
