# P2 fidelity harness — the renderer scoreboard

`fidelity.py` is the reusable pixel-diff harness that every P2 map-renderer milestone uses to
prove itself. Given a manifest of `(chart, style, [golden], [ad-ref])` entries it renders each
map with the **native** renderer (`ae_backend.map_draw.export_styled_map`) and pixel-compares
it against (a) the **kateri** golden PDF and (b) an **AD** single-map reference where one is
isolable — emitting a per-map AE (differing-pixel) table at both `-fuzz 30%` and strict.

## What it does per map

1. **render** native → PDF: `export_styled_map(chart, out.pdf, style, width, projection)`
2. **rasterise** native + each reference PDF to equal-size PNGs: `pdftoppm -png -scale-to SIZE`
3. **compare** native vs each reference: `magick compare -metric AE [-fuzz 30%]` → AE pixel count
4. **report**: per-map table to stdout + `scoreboard.csv` + `scoreboard.md` in the out-dir,
   plus optional `native|kateri[|AD]` montages (`--montage`).

`AE` is the count of differing pixels; `%` is `AE / (SIZE·SIZE)`. `-fuzz 30%` tolerates small
colour/AA deltas so it isolates *structural/content* differences from anti-aliasing noise;
strict is the raw count.

## Invocation

```bash
# ae_backend lives in the frozen render-spike build; point --build-dir at it (no rebuild).
python3.14 tools/p2-fidelity/fidelity.py MANIFEST.json \
    --build-dir /path/to/ae-p2-render-spike/build-py314 \
    --out-dir   /tmp/p2-fidelity-run \
    --size 800 --montage
```

Flags: `--build-dir DIR` (dir with `ae_backend*.so`; else `$AE_BUILD`, else an already-importable
`ae_backend` on `PYTHONPATH`, else `<repo>/build-py314`), `--out-dir DIR` (default a scratch dir),
`--size PX` (raster scale-to, default 800), `--width` / `--projection` (native render overrides),
`--montage` (write side-by-side PNGs), `--only SUBSTR` (filter by label), `--timeout SEC`
(per-command bound, default 120).

Requires: `python3.14` with `ae_backend`, `pdftoppm` (poppler), ImageMagick 7 (`magick`),
and `timeout` — every external command is wrapped in `timeout` so a hung tool cannot stall a run.

## Manifest format

JSON. Either a top-level object with config + a `maps` list, or a bare list of entries. See
[`manifest.example.json`](manifest.example.json) for the full annotated schema. Essentials:

| key | scope | meaning |
|-----|-------|---------|
| `chart` | entry (req) | path to a styled `.ace` (outside the repo) |
| `style` | entry (req) | a `c["R"]` front-style name: `clades-v1`, `serology`, `ts-2025-08`, `info-clades-v1`, … |
| `golden` | entry | kateri reference PDF path; `"auto"` derives `<chart-dir>/out.1.<style>.pdf`; omit to skip |
| `ad_ref` | entry | AD single-map reference PDF path; omit where AD is only page-embedded |
| `label` | entry | display name (default `<chart-dir-name>/<style>`) |
| `raster_size`,`width`,`projection`,`out_dir`,`build_dir` | top | run defaults (CLI flags override) |

## WHO-data policy (mandatory)

- The manifest references charts and reference PDFs **by path only** — real report data that
  lives **outside** this repo and is never committed. Do **not** embed chart contents or a
  manifest carrying real strain-tied paths in the repo.
- All rendered/rasterised output (a labelled antigenic map exposes strain names + titer-derived
  coordinates) goes to the **out-dir outside the repo**.
- Only the **synthetic** `manifest.example.json` (placeholder paths, generic style names) is
  committed. Style names like `clades-v1` / `ts-2025-08` are generic and carry no WHO data.

## Reading the scoreboard

- **kateri strict / fuzz30** — native vs the kateri golden. The fuzz30 column is the honest
  content metric; a large strict-vs-fuzz30 gap is dominated by AA/colour, not layout.
- **AD strict / fuzz30** — native vs an isolated AD single-map PDF. Usually `n/a`: the AD
  references for the ssm report are multi-page (`reference-AD/report.pdf`, `addendum-*.pdf`)
  with maps embedded in composed pages, so a single-map AD PDF is rarely isolable — note it as
  page-embedded and rely on the kateri golden.
- A map whose **fuzz30 %** is high is a **content** miss (wrong points/frame/palette) that a
  renderer milestone should target; a map with low fuzz30 but high strict is a framing/AA tail.
