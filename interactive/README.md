# Interactive tree + antigenic map viewer

A standalone, **double-click-to-open** HTML visualisation that places a
phylogenetic tree next to one or more antigenic maps and links the two panels by
strain. Intended as an interactive adjunct to the seasonal report (whose tree and
map figures are otherwise static PDF).

```
interactive/
  export_interactive.py   # builds the viewer from a tree + chart(s) via ae_backend
                          #   + inline bundler: concatenates js/*.js into the template
  viewer_template.html    # thin shell: markup + CSS + /*__DATA__*/ and /*__MODULES__*/ slots
  js/                     # viewer modules (vanilla JS + SVG, no deps), inlined at export
    state.js              #   IV.State — selection store + view state (shared contract)
    colour.js             #   IV.Colour — colour API (shared contract)
    ui.js                 #   IV.UI — tooltip, legend, header controls, titles
    tree.js               #   IV.Tree — phylogram render + highlight
    map.js                #   IV.Map — antigenic map render + highlight
    lines.js              #   IV.Lines — Stage-2 overlay scaffold (error/connection lines)
    grid.js               #   IV.Grid — Stage-2 all-centres grid scaffold
    main.js               #   entry point (loaded last); wires bundle → modules
  CONTRACT.md             # F0: the JSON bundle schema both exporter and viewer build against
  PLAN.md                 # the v2 roadmap (issues + features, task ownership, parallelism)
  run.sh                  # wires up the ae arm64 / Python-3.10 env and runs the exporter
  data/                   # local scratch only — git-ignored, do NOT keep outputs here
```

## Architecture (post-F1)

The viewer is authored as separate `js/*.js` modules sharing a single `IV.*`
namespace and **inlined into `viewer_template.html` at export time** (no bundler, no
server) so the output stays one dependency-free file that opens from `file://`.
Module load order is fixed by `MODULE_ORDER` in `export_interactive.py`
(`state → colour → ui → tree → map → lines → grid → main`).

Two cross-cutting modules define the shared APIs the rest build on — never
duplicate this state:

- **`state.js` (`IV.State`)** — the selection store and view state (`active`,
  `selected`, `offClades`, `onlyMatched`, `chartIdx`, `colorBy`) with
  `subscribe(fn)` / `notify()`. Each panel subscribes and re-applies its own
  highlight when state changes.
- **`colour.js` (`IV.Colour`)** — the colour API (`leaf`, `antigen`, `cladeColor`,
  `clades`, `unmatched`) honouring the active `colorBy`.

The bundle handed from exporter to viewer is specified in **`CONTRACT.md`**; the
phased roadmap and per-agent task ownership are in **`PLAN.md`**.

> **Where outputs go.** A generated viewer embeds the real WHO surveillance data
> inline, so it must **not** live in the `ae` repo. Write it into the report run it
> came from, e.g. `<report-dir>/interactive/`. The `data/` dir here is git-ignored
> scratch only.

> **Per-report driver.** Each report carries its own `0do` recipe at
> `<report-dir>/interactive/0do` (beside `<report-dir>/tree/0do`), holding the
> report-specific trees/chart-dirs and calling `run.sh` here — the report-folder
> equivalent of how `tree/0do` calls the `tal` binary. `run.sh` and
> `export_interactive.py` (this dir) are the reusable engine; the recipe is not.

## Quick start

```sh
SSM=~/AC/eu/ac/results/ssm/2026-0223-ssm
OUT="$SSM/interactive"          # outputs belong with the report data, not in ae
mkdir -p "$OUT"

# single centre
./run.sh --tree "$SSM/tree/h3.asr.after-2021.tjz" \
  --chart "vidrl=$SSM/h3-hi-guinea-pig-vidrl/styled.ace" \
  --subtype "A(H3N2)" --assay HI --out "$OUT/h3-hi-vidrl.html"

# all five WHO Collaborating Centres in one file (switchable in the viewer)
./run.sh --tree "$SSM/tree/h3.asr.after-2021.tjz" \
  --chart "cdc=$SSM/h3-hi-guinea-pig-cdc/styled.ace" \
  --chart "cnic=$SSM/h3-hi-guinea-pig-cnic/styled.ace" \
  --chart "crick=$SSM/h3-hi-guinea-pig-crick/styled.ace" \
  --chart "niid=$SSM/h3-hi-guinea-pig-niid/styled.ace" \
  --chart "vidrl=$SSM/h3-hi-guinea-pig-vidrl/styled.ace" \
  --subtype "A(H3N2)" --assay HI --out "$OUT/h3-hi-all-centres.html"
```

Open the resulting `.html` in any browser — it has no external dependencies and
needs no server (all data is inlined; the viewer is plain SVG + JavaScript).

Each `--chart` is `LABEL=PATH`; the label names the centre in the viewer's
**Centre** dropdown. The tree is shared across all charts.

## What it shows

- **Left:** phylogram (x = cumulative branch length / genetic distance, tips
  ordered top-to-bottom). Tips coloured by clade.
- **Right:** the antigenic map — filled circles = antigens, open squares = sera,
  black-edged circles = reference antigens, stars = vaccines.
- **Linking:** hover a tip → its antigen(s) light up on the map (and vice versa),
  matched by strain. Click clade swatches in the legend to filter; *map: linked
  only* dims map points that have no tree tip.
- **Legend (persistent):** a colour key for the active *Colour* mode — clade
  swatches with tree-tip counts (click to show/hide a clade), continent key, or a
  uniform-colour note — alongside a fixed marker key (reference / vaccine / serum
  shapes, plus egg/cell/reassortant passage colours once passage data is exported).
- **Selection:** click a tip or map point to select it (Shift/Cmd-click adds to
  the selection); drag a box on either panel to select every strain inside it.
  Selected strains keep a blue ring in **both** panels and the rest fade. The
  search box selects **all** name matches at once; click empty space to clear.
- **Map zoom/pan (M1):** pinch or ⌃-scroll (or the on-map ＋ / − / ⤢ buttons) to
  zoom toward the cursor; two-finger scroll or a right/middle-button drag to pan;
  double-click resets. The map starts fitted to the pane. Zoom/pan re-projects the
  points (it does not transform the SVG) so box-selection and overlay lines stay
  aligned. Left-button drag stays reserved for box-selection.
- **All-centres view (G1):** the *View → all centres* toggle replaces the single
  map with a grid of small-multiple maps, one per centre, each in its own
  orientation. Hover/select/search links the highlight across **every** panel and
  the tree at once, so a strain can be compared across labs.

## How the link is made

Tree tip names (`TOGO/764/2022_OR_4D211EF9`) and chart antigen names
(`A(H3N2)/THAILAND/8/2022`) are normalised to a common `LOCATION/ID/YEAR` key
(passage tag + sequence hash stripped from tips; subtype prefix stripped from
antigens). The full ~70 k-leaf seqdb tree is **pruned to the induced subtree of
linked tips** (degree-2 nodes collapsed) so the file stays light and every visible
tip corresponds to an assayed strain. Clades are re-derived canonically (E1, see
below) and each tip inherits its matched antigen's clade.

For the H3N2 2026-0223 report, ~1.5 k of 2.9 k antigens (one centre) and ~2.1 k
across all centres link to a tree tip; unmatched antigens are typically
un-sequenced isolates or reassortants.

## Exporter data (E1)

The exporter prepares the report-faithful data the viewer renders:

- **Oriented coordinates.** Each chart's projection `transformation` (parsed in-process
  from `str(projection.transformation())`, which emits the 2×2 matrix as a JSON list) is
  baked into the exported antigen/serum `x`/`y`, so the map matches the report's
  orientation.
- **Canonical clade colours + legend.** Clades are re-derived the way `chart_modifier`
  does — `populate_from_seqdb()` then `ae.semantic.clade.attributes()` with
  `semantic_clades.semantic_attribute_data_for_subtype()` — and each antigen's primary
  clade is the most-specific label present in the report palette
  (`semantic_clades.semantic_plot_spec_data_for_subtype()`). `clade_color`/`clade_legend`
  use those canonical hexes; labels with no palette entry (e.g. `122D`) get a generated
  colour and are logged.
- **Passage markers.** Each antigen is classified egg/cell/reassortant (`pt`), tips
  inherit their matched antigen's type, and `passage_color` carries the marker palette.
- **AA transitions.** Each tree edge's `A` substitutions are derived by diffing the
  reconstructed ancestral sequences on the `.asr` tree (the C++ consensus path is broken
  in this build); positions are HA1-numbered and line up with the clade names.

Stage-2 data (E2), for the colour-by-AA and stress/error overlays:

- **Shared `aa` table.** `norm → aligned HA1 AA sequence string` (from the `.asr`
  tree); C1 reads residue `p` as `aa[norm][p-1]`. Same numbering as the clade names
  and `A` transitions.
- **Per-chart titers.** `titers` (raw strings, so `<`/`>`/`*` are distinguishable),
  `logged` (`log2(titer/10)`, null for missing), `column_bases`, and `min_col_basis`
  — used by N1/N2/C2. `column_bases` are the projection's **forced** bases when present
  (those match the coordinates); the exported data reproduces the optimiser's stress
  (≈6.15 k vs 6.19 k on vidrl), whereas the recomputed bases would roughly double it.

> A two-centre H3 file is ≈6 MB (the tree ≈3 MB and `aa` table are shared; each chart
> adds its titer/logged matrices). All-centres files scale with the number of charts.

## Known limitations / next steps
- **Pruned context.** Only linked tips are kept. An option to retain surrounding
  tree context (or a full-tree mode with on-demand sequence loading) is a natural
  follow-up.
- **Name matching** is string-based (~50–70 % of antigens). Matching on the
  seqdb sequence hash that already appears in the tip name would be more robust.
- **Sera** are not linked to the tree (antisera have no HA sequence).
- The x-axis is genetic distance; a time-scaled view is possible (tip dates are
  exported).
- **Report integration.** The exporter currently stands alone; folding it into
  `ae/py/ae/report` (alongside `trees.py`) would let the report build emit these
  pages automatically.

## Environment

`ae_backend` is a CPython **3.10 arm64** extension. `run.sh` sets
`PYTHONPATH=$AE/build-arm64:$AE/py:$EU/acmacs-data` (the last for `semantic_clades`) and runs
`arch -arm64 /Library/Frameworks/Python.framework/Versions/3.10/bin/python3`.
Use `run.sh` rather than a bare `python3` (the system Homebrew Python is 3.14 and
cannot load the extension).
