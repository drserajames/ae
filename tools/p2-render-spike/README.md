# P2 render spike — scaffolding

Investigative scaffolding for the spike **"can the headless C++ `map-draw` renderer
become the canonical figure engine for `ae.report`, replacing the kateri (Dart/macOS/socket)
path?"** Findings and the go/no-go recommendation live in
[`../../P2-RENDER-SPIKE-PLAN.md`](../../P2-RENDER-SPIKE-PLAN.md).

## `compare.sh`

Renders a styled report chart through `map-draw` and pixel-diffs it against the golden PDF
that kateri produced for the same chart+style.

```bash
compare.sh <styled.ace> <kateri-golden.pdf> [out-dir] [size]
```

All inputs are paths to **real report data outside the repo**; all output goes to a scratch
dir outside the repo. **Nothing real-data is committed** — not the chart, not any render (a
labelled antigenic map exposes strain names + titer-derived coordinates).

Requires `map-draw` (`ae/build/map-draw`), `pdftoppm`, and ImageMagick.
