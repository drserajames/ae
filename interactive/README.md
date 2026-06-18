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

## Quick start

```sh
SSM=~/AC/eu/ac/results/ssm/2026-0223-ssm
OUT="$SSM/interactive"          # outputs belong with the report data, not in ae
mkdir -p "$OUT"

# single centre
./run.sh --tree "$SSM/tree/h3.asr.tjz" \
  --chart "vidrl=$SSM/h3-hi-guinea-pig-vidrl/styled.ace" \
  --subtype "A(H3N2)" --assay HI --out "$OUT/h3-hi-vidrl.html"

# all centres in one file (switchable in the viewer)
./run.sh --tree "$SSM/tree/h3.asr.tjz" \
  --chart "cdc=$SSM/h3-hi-guinea-pig-cdc/styled.ace" \
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
  matched by strain. Click clade swatches in the legend to filter; use the search
  box to find a strain; *map: linked only* dims map points that have no tree tip.

## How the link is made

Tree tip names (`TOGO/764/2022_OR_4D211EF9`) and chart antigen names
(`A(H3N2)/THAILAND/8/2022`) are normalised to a common `LOCATION/ID/YEAR` key
(passage tag + sequence hash stripped from tips; subtype prefix stripped from
antigens). The full ~70 k-leaf seqdb tree is **pruned to the induced subtree of
linked tips** (degree-2 nodes collapsed) so the file stays light and every visible
tip corresponds to an assayed strain. Clade labels are taken from the chart
antigens' semantic attributes and propagated to the matched tips.

For the H3N2 2026-0223 report, ~1.5 k of 2.9 k antigens (one centre) and ~2.1 k
across all centres link to a tree tip; unmatched antigens are typically
un-sequenced isolates or reassortants.

## Known limitations / next steps

- **Clade source.** Clades come from each chart's styling (`semantic.clades`),
  which here mixes canonical names (`3C.2a1b.2a`) and substitution motifs
  (`223V 145S`). Colouring the *whole* tree by canonical clade would use
  `Tree.set_clades()` with the clade definitions in
  `~/AC/eu/influenza-clade-nomenclature` / `acmacs-data/clades.json`.
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
`PYTHONPATH=$AE/build-arm64:$AE/py` and runs
`arch -arm64 /Library/Frameworks/Python.framework/Versions/3.10/bin/python3`.
Use `run.sh` rather than a bare `python3` (the system Homebrew Python is 3.14 and
cannot load the extension).
