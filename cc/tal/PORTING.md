# TAL (phylogenetic tree drawing) — port plan & milestone-1 exploration

> Subsystem #3 in [`TODO.md`](../../TODO.md). This file is the **milestone-1
> deliverable**: exploration of `acmacs-tal` and identification of the tree-layout
> and draw entry points, plus the dependency analysis that gates the rest of the port.
> No drawing code is ported yet — see **Blocker** below.

**AD source:** `~/AC/eu/AD/sources/acmacs-tal` — 42 `.cc` files, ~10,700 LOC.
Binary `tal` (`cc/tal.cc`), shared lib `libtal`.

---

## 1. Run pipeline (entry point → output)

From `cc/tal.cc` `main()`:

```
Tal tal
  tal.import_chart(--chart)                 // optional, for the signature page
  Settings settings{tal}                    // acmacs::settings::v3 JSON DSL
  settings.load_from_conf({tal.json, vaccines.json})
  settings.load(--s files); settings.set_defines(--D)
loop:
  tal.import_tree(tree.newick|.phy|.json[.xz])
  settings.apply("tal-default")             // builds the Layout from JSON mods
  [if --chart] AntigenicMaps.maps_settings.load_from_conf({mapi.json, tal.json, clades.json, vaccines.json})
  tal.prepare()                             // compute node positions, aa-transitions, time series, clades
  for output in outputs: tal.export_tree(output)   // .pdf .json[.xz] .html .names  /json /names
```

`Settings::apply("tal-default")` is the heart: a settings-v3 mod pipeline whose
built-in commands (`Settings::apply_built_in`, `cc/settings.cc`, ~71 KB) each
`add_*` a `LayoutElement` to `Draw::layout()`. Porting the DSL is a late milestone;
the elements it builds are the substance.

## 2. Core data model

```
class Tal {                 // cc/tal-data.hh
    Tree tree_;             // recursive vector<Node>
    chart::ChartP chart_;   // optional
    Draw draw_;             // owns the Layout
    Settings* settings_;
};
```

`class Node` (`cc/tree.hh`) — single recursive type for leaves and branches:
- topology/metrics: `edge_length`, `cumulative_edge_length`, `subtree`, `number_leaves`,
  `node_id{vertical,horizontal}`, `first_prev_leaf`/`last_next_leaf`, `leaf_pos`, `hidden`
- leaf data (from seqdb): `seq_id`, `strain_name`, `date`, `continent`, `country`,
  `hi_names`, `clades`, `aa_sequence`, `nuc_sequence`
- export styling: `edge_line_width_scale`, `color_edge_line`, `label_scale`, `label_color`

> ae already has an independent tree model in [`cc/tree/`](../tree/) (`tree.hh`,
> `aa-transitions.cc`, `newick.cc`, `export.cc`). The TAL `Node` is **richer** (carries
> layout numbering + draw styling). Decide early: extend `cc/tree/`'s `Node`, or keep a
> TAL-local node and adapt. Reusing `cc/tree/` for parse/aa-transitions and layering TAL
> draw-state on top is the lower-duplication path.

## 3. Rendering architecture (where the Surface dependency lives)

`Draw` (`cc/draw.hh`) owns a `Layout` = `vector<unique_ptr<LayoutElement>>`. Each element:

```cpp
virtual void prepare(preparation_stage_t stage);          // headless: compute positions
virtual void draw(acmacs::surface::Surface& surface) const = 0;   // <-- needs the Cairo surface
```

`Layout::draw(acmacs::surface::Surface&)` walks elements left-to-right across the canvas.
`Draw::export_pdf()` creates the surface and calls it.

### LayoutElement subclasses → source files
| Element(s) | File | Notes |
|---|---|---|
| `DrawTree`, `DrawOnTree` | `draw-tree.cc` | the tree itself; `vertical_step`/`horizontal_step` |
| `TimeSeries`, `TimeSeriesWithShift` | `time-series.cc` | date-bucketed columns |
| `Clades` | `clades.cc` | clade bars |
| `DrawAATransitions` | `draw-aa-transitions.cc` | branch aa-substitution labels |
| `DashBar`, `DashBarAAAt`, `DashBarClades` | `dash-bar.cc` | per-leaf dash columns |
| `HzSections`, `HzSectionMarker` | `hz-sections.cc` | horizontal section bands |
| `Title` | `title.cc` | text title |
| `Gap` | `layout.cc` | spacer (no draw) |
| `Legend` | `legend.cc` | colour legend |
| `AntigenicMaps` | `antigenic-maps.cc` | embeds maps — **also needs map-draw + hidb** |

### Supporting (computation, mostly Surface-independent)
- **AA-transition engine:** `aa-transition.cc`, `aa-transition-20200915.cc`,
  `aa-transition-20210503.cc`, `aa-counter.hh` — branch/clade aa labelling, several
  algorithm versions. Overlaps [`cc/tree/aa-transitions.cc`](../tree/aa-transitions.cc).
- **Coloring:** `coloring.cc` (by continent/clade/aa-pos).
- **I/O:** `newick.cc`, `json-import.cc`/`json-export.cc` (phylo-tree-v3 format, see
  `doc/phylogenetic-tree-v3.format.json`), `html-export.cc`, `import-export.cc`.
- **Layout numbering:** node vertical/horizontal ids, ladderize, cumulative edge length —
  in `tree.cc` (`set_first_last_next_node_id` etc.) and `DrawTree::prepare`.

---

## 4. BLOCKER — TAL depends on subsystem #1 (and #2)

TAL is built entirely on **`acmacs::surface::Surface`** — AD's rich vector+text Cairo
abstraction (`~/AC/eu/AD/sources/acmacs-draw/cc/surface.hh`, ~15 KB: lines, paths,
text via Pango, rotated sub-surfaces, viewport transforms). Every `draw()` takes a
`Surface&`.

ae today provides only **`ae::draw::CairoPdf`** ([`cc/draw/cairo-surface.hh`](../draw/cairo-surface.hh)):
`background`, `circle`, `square`. That is map-draw **M1** (the minimal points-to-PDF slice).

| TAL needs | ae has | Gap |
|---|---|---|
| Full `Surface` (lines, paths, sub-surfaces, transforms) | `CairoPdf` (3 shape methods) | map-draw **M1→M2** |
| Pango text (labels, titles, aa-transition labels) | none | map-draw **M3** |
| `AntigenicMaps`: embedded map render + vaccine/reference id | none | map-draw render + **hidb (#2)** |

**Conclusion:** the *drawing half* of TAL cannot compile or be verified until subsystem
#1 reaches ~M3 and exposes a reusable surface API. This matches the TODO note: *"Depends
on the Cairo backend from #1 … best started after map-draw M1–M3 land, or coordinate on
the `cc/draw/` surface API."*

---

## 5. Recommended port order

**Phase A — headless (unblocked, can start now, unit-testable without Cairo):**
1. JSON import/export of the phylo-tree-v3 format — **already in `cc/tree/`**
   (`export_json`/`load_json`/`is_json` in `cc/tree/export.cc`); Newick load too.
   No re-port needed.
2. **Tree layout (node positions) — DONE.** [`layout.hh`](layout.hh)/[`layout.cc`](layout.cc),
   `ae::tal::compute_layout(Tree&)` → `TreeLayout{height, max_cumulative, leaves[], inodes[]}`.
   Port of acmacs-tal `compute_cumulative_vertical_offsets()`: shown leaves stacked one per
   `default_vertical_offset`, inodes at the midpoint of their first/last shown child;
   horizontal = cumulative edge (reuses `Tree::calculate_cumulative()`). Iterative
   post-order (no recursion → safe on deep ladderized trees). Exposed as `ae_backend.tal`
   ([`cc/py/tal.cc`](../py/tal.cc)). Verified by [`test/test-layout.py`](test/test-layout.py).
3. Ladderize is in `cc/tree/` (`number-of-leaves` and `max-edge-length` both done — 2026-06-17;
   wired through `tal-draw` via the `ladderize` setting / `--ladderize=`).
4. AA-transition labelling — `cc/tree/aa-transitions.cc` already ports a consensus method;
   reconcile with acmacs-tal's versioned algorithms when richer labelling is needed.
5. **Clade sections — DONE.** [`clades.hh`](clades.hh)/[`clades.cc`](clades.cc),
   `ae::tal::compute_clade_sections(Tree&)` → `[Clade{name, sections[]}]`. Port of
   `Tree::make_clade_sections()`: shown leaves grouped into per-clade vertically-contiguous
   runs (a gap starts a new section). Reuses `ae::tree::Leaf::clades`. Exposed as
   `ae_backend.tal.compute_clade_sections`. Verified by
   [`test/test-clades.py`](test/test-clades.py).
6. **Time series (date bucketing) — DONE.** [`time-series.hh`](time-series.hh)/[`time-series.cc`](time-series.cc),
   `ae::tal::compute_time_series(Tree&, interval, start?, end?)` → `TimeSeries{slots[], …}`
   for year/month/week/day intervals. Ports the *data* side of `time-series.cc` (slot
   generation + per-slot leaf counts) using `ae::date` + C++20 `<chrono>` instead of porting
   `acmacs-base/time-series`. Reuses `ae::tree::Leaf::date`. Exposed as
   `ae_backend.tal.compute_time_series`. Verified by
   [`test/test-time-series.py`](test/test-time-series.py).
7. AA-transition labelling — `cc/tree/aa-transitions.cc` already ports a consensus method;
   reconcile with acmacs-tal's versioned algorithms when richer labelling is needed.
   Remaining Phase-A: hz-section detection (`hz-sections.cc`).

**Phase B — drawing (unblocked by subsystem #1 reaching M3):**
5. **M1 — tree → PDF — DONE.** [`draw-tree.hh`](draw-tree.hh)/[`draw-tree.cc`](draw-tree.cc),
   `ae::tal::export_tree_pdf(Tree&, output, image_size, labels)` + the **`tal-draw`** CLI
   ([`tal-draw-main.cc`](tal-draw-main.cc)). Port of the leaf/inode loop in acmacs-tal
   `DrawTree::draw`: each node's horizontal edge segment (scaled by cumulative edge) + the
   vertical connector under each inode; optional leaf-name labels. Reuses `compute_layout`
   (Phase A) and the `ae::draw::CairoPdf` surface from subsystem #1. Cairo is linked **only**
   into the `tal-draw` executable (like `chart-draw`), never into libae/ae_backend.
   **Verify:** `sh cc/tal/test/test-draw-tree.sh` → `OK: tal-draw renders valid PDFs`
   (a 20-leaf tree was also rasterised and eyeballed — correct topology, branch-length
   scaling, labels).
   - *Used the existing concrete `CairoPdf` directly rather than first extracting an abstract
     `ae::draw::Surface` — lowest-conflict path while map-draw is actively evolving `CairoPdf`.
     The surface-abstraction extraction is still worthwhile (shared with map-draw, alongside
     SVG/PNG); revisit when adding the rotated/sub-surface primitives the column elements need.*
6. **M2 — coloring + aligned columns — DONE.** `export_tree_pdf` now takes a
   `TreeDrawParameters` and draws, aligned to the tree's leaf rows: **leaf coloring by
   clade** (palette keyed on `compute_clade_sections` order), a **clades column** (one bar
   per section, spanning `first_node..last_node`, with the clade name), and a **time-series
   dash column** (per-leaf dash placed in the `compute_time_series` slot whose `[first,
   after_last)` contains the leaf's date, via canonical-ISO string compare; grey slot
   separators). CLI flags: `--color-by-clade --clades --time-series --interval=…`. Done with
   only the existing `line()`/`text()` primitives (thick lines as bars/dashes, horizontal
   labels) — **no `CairoPdf` change**, so no map-draw coordination needed yet. **Verify:**
   `sh cc/tal/test/test-draw-tree.sh`; a 24-leaf 3-clade tree (`--labels --color-by-clade
   --clades --time-series --interval=year`) was rasterised & eyeballed — coloring, clade
   bars and per-year dashes all align to rows correctly.
   - *Deferred to a later pass (need new surface primitives): rotated month/year slot
     labels and clade arrows (rotated text), filled slot backgrounds (filled rect).*
7. **M3 — title + legend + aa-transitions + rotated slot labels — DONE.** Added two
   primitives to the shared surface — `CairoPdf::rectangle()` (filled/outlined) and
   `text_rotated()` — then: a centred **title** (`--title=`), a **clade legend** row
   (`--legend`, filled-rect swatches), **aa-transition labels** at inodes
   (`--aa-transitions`, ports `DrawAATransitions`, reads `Inode::aa_transitions` from the
   phylo-tree-v3 `"A"` field), and **rotated year/month slot labels** under the time-series
   column. **Verify:** `sh cc/tal/test/test-draw-tree.sh`; a 24-leaf 3-clade tree with
   inode aa-transitions rendered as a full signature-page-style figure (title + tree +
   aa labels + clade bars + time-series with rotated year labels + legend) — rasterised &
   eyeballed.
8. **M4+ — DONE** (see the items below): label-collision avoidance (#12), `hz-sections` (#16),
   aa-transition computation (#17), `dash-bar-aa-at` (#18), and `AntigenicMaps` — the full
   tree+map signature page composed from kateri PDFs + hidb/WHOCC vaccine marks (#13–#15).

**Phase C — settings DSL:**
9. **M1 — declarative JSON config — DONE.** [`settings.hh`](settings.hh)/[`settings.cc`](settings.cc),
   `ae::tal::load_draw_settings(file)` → `TreeDrawParameters`, plus `tal-draw --settings=FILE`.
   Rather than porting AD's full settings-v3 mod pipeline (node-selection + if/then + ~71 KB
   of `settings.cc` built-ins), this maps a single declarative JSON object onto the draw
   parameters and adds what flags can't express: **per-clade `color` / `display_name`
   overrides** and explicit time-series `start`/`end`. Parsed with `rjson::v3` (already in
   libae). Schema documented in `settings.hh`; example `test/draw-settings.json`. **Verify:**
   `sh cc/tal/test/test-draw-tree.sh` (settings case); the 24-leaf tree rendered via
   `--settings` with override colours/names was rasterised & eyeballed (palette replaced by
   the configured hex colours; clade labels/legend show the short display names).
10. **M2 — node select/apply mods — DONE.** A `"nodes": [{ "select": {…}, "apply": {…} }]`
    array drives the core of acmacs-tal's mod pipeline. **Select** by `seq_id` (string or
    list), `cumulative_min` (long branches), `edge_min` (`.tal` `edge >=` — hide long-edge
    outliers), `date_min`/`date_max`; **apply** `hide` (drops
    the node + subtree from the layout — applied before `compute_layout`), `edge_color`,
    `label_color`, `label_scale`. Resolved in `draw-tree.cc` via per-node override maps
    (keyed by node index) consulted while drawing. **Verify:** `sh cc/tal/test/test-draw-tree.sh`
    (node-mods case); a 24-leaf render hiding S3/S20, red-scaling S5's label and recolouring
    S13–S15 edges was rasterised & eyeballed.
**Drawing quality:**
12. **Label-collision avoidance — DONE.** Leaf labels share the fixed column at `x_label0`,
    so collisions are purely vertical: a greedy top-to-bottom pass keeps a label only if it
    clears the last kept one by `label_fs * 1.15`. Labels singled out by a node mod
    (`label_color`/`label_scale`) are **forced** on. On by default (`labels_avoid_collisions`;
    `tal-draw --labels-overlap` disables it). `export_tree_pdf` returns the suppressed count
    (surfaced by the CLI — "N labels hidden", no silent drop). **Verify:** a 250-leaf tree at
    900 px hid 125/250 overlapping labels — rasterised & eyeballed (off = unreadable smear,
    on = cleanly spaced); the full tree/edges are always drawn, only labels thin.

**Signature page (acmacs-tal `AntigenicMaps`):**
13. **Tree + antigenic-map composition — DONE.** [`bin/tal-signature-page`](../../bin/tal-signature-page)
    + [`py/ae/tal/signature_page.py`](../../py/ae/tal/signature_page.py). In ae the two halves
    come from separate tools — the **tree** from `tal-draw` (this subsystem), **antigenic maps**
    from **kateri** (the Dart map/PDF generator) — so the page is composed at the **PDF level**
    (not on one Cairo surface as AD did): render the tree → obtain the map PDF(s) → compose
    tree (left) + map(s) (right) on one landscape page with `pdfjam`. The output is exactly what
    `py/ae/report`'s `signature_page` page type embeds via `image:`. Supports `--mark ID,…` to
    highlight vaccine/reference strains on the tree (generates node-mods, merged into the
    settings) — the hook for **hidb (#2)** identification. The map source is `--map PDF`
    (pre-rendered) or `--chart ACE` (rendered via kateri over its unix socket per
    `py/ae/utils/kateri.py`). **Verify:** `sh cc/tal/test/test-signature-page.sh` (skips if
    pdfjam/tal-draw absent); a 24-leaf tree + stand-in map with S5/S12/S20 marked was
    rasterised & eyeballed — tree left (marked strains red/enlarged), map right, one page.
    - **kateri path verified live.** `--chart CHART.ace` renders the antigenic map via kateri
      and composes it beside the tree. **Verified end-to-end**: an optimized `test/chart1.ace`
      → kateri PDF → signature page (tree left + the real antigenic map right: green test
      antigens, open reference circles, serum squares; rasterised & eyeballed). Two launch
      requirements found: (1) kateri is a Flutter **GUI** app that connects only after its
      window builds, so on macOS it must be launched via **`open -n -a kateri.app --args
      --socket …`** (a bare subprocess gets no Aqua session and never connects) —
      `render_map_via_kateri` resolves the `.app` from the on-PATH `kateri` symlink and does
      this; (2) the `--chart` path imports `ae_backend`, so run it under the arm64 **python3.10**
      (the `--map` path is pure-stdlib and runs anywhere). Committed as the **opt-in** test
      [`test/test-signature-page-kateri.sh`](test/test-signature-page-kateri.sh) (runs only with
      `TAL_TEST_KATERI=1`; skips in headless CI).
14. **`--mark-vaccines` (WHOCC vaccine strains) — DONE, real-data verified.** `--mark-vaccines
    SUBTYPE --vaccines-file …/semantic_vaccines.py` reads the vaccine list (acmacs-data's
    `semantic_vaccines.py`, the modern `sData[subtype] -> [{"name":…}]` replacement for AD's
    `vaccines.json`), matches each against the tree's leaf seq_ids (normalise spaces↔underscores,
    prefix-match so every passage of a strain is caught), and feeds the hits to the `--mark`
    node-mods. `load_vaccine_names` + `match_leaves_by_name` in `signature_page.py` (the latter
    needs `ae_backend`). **Verify (committed, synthetic):**
    `python3 cc/tal/test/test-mark-vaccines.py` → matches A,E from a fake list. **Verify
    (real, one-off):** a real ~38k-leaf B/Vic tree + the real BV vaccine list matched 7 leaves
    and rendered a signature page (vaccines red on the tree + kateri map) in ~2 s — rasterised &
    eyeballed. (Counts only; per rule #8 no real strain names go in the repo.)
15. **`--mark-reference` (hidb reference antigens) — DONE (mechanism), 0 useful hits on
    current trees.** `--mark-reference SUBTYPE [--hidb-dir DIR] [--reference-tables N]` unions
    the reference antigens of the most recent N hidb tables (`get_reference_antigen_names`, via
    `HiDb.reference_antigens(table)` → `antigen.name_without_subtype()` so the format matches
    leaf seq_ids), matches them with the same `match_leaves_by_name`, and marks them **blue** (vs
    red for vaccines) — multiple coloured node-mod groups assembled by `_settings_with_mark_groups`.
    `match_leaves_by_name` skips the few real-tree leaves carrying non-UTF-8 bytes. **Honest
    finding:** hidb reference antigens are established **older anchor strains** (kept across HI
    tables for comparability), so on a current-season tree (recent tips) they match **0** leaves —
    expected, not a bug (the same `match_leaves_by_name` matched 7 *vaccine* leaves because
    vaccines are recent). `get_reference_antigen_names` is verified to return the real hidb
    reference panel; the feature would mark references on a tree that spans their era. *(The more
    useful related feature for a current signature page would be marking a chart's own
    antigens/sera on the tree — not yet built.)*
**Real-report parity (toward running the production `.tal` configs):**
16. **`hz-sections` — DONE.** `TreeDrawParameters.hz_sections` + a left marker column in
    `draw-tree.cc`: each section `{first, last, label}` resolves first/last leaf seq_ids to
    vertical positions, drawing a bracket (spine + end ticks) and a rotated label, plus a faint
    separator across the tree at the section's top boundary. Settings key `"hz_sections": [...]`.
    **Verify:** `sh cc/tal/test/test-draw-tree.sh` (hz-sections case); a 24-leaf tree with three
    sections rasterised & eyeballed (brackets aligned to the clade groups, labelled 2a/3a/2a1b).
17. **aa-transition *computation* — DONE (incl. a `cc/tree` fix).** tal-draw gains
    `--aa-transitions-compute` (settings `aa_transitions.compute`) — computes transitions via
    `set_aa_nuc_transition_labels` before drawing — and `aa_transitions.min_leaves` (only label
    inodes whose subtree has ≥ N leaves, like AD's `minimum-number-leaves-in-subtree`, so big
    trees stay readable). **Found and fixed a stub:** `cc/tree/aa-transitions.cc`'s consensus
    `set_transitions` body was entirely commented out (it built the `common_aa` counters but
    assigned **nothing** — 0 transitions). Implemented it: a transition is placed on a child
    branch whose subtree consensus aa (most-frequent > `non_common_tolerance`, ignoring gaps/X)
    differs from its parent's. **Verify:** `python3 cc/tal/test/test-aa-transitions.py` →
    computes `T3A` on a synthetic derived-clade tree; also ran on a real 70k-leaf ASR tree.
18. **`dash-bar-aa-at` — DONE.** `TreeDrawParameters.dash_bars` + per-leaf dash columns
    (right of the time-series column): each `{pos, colors_by_aa}` draws one dash per shown leaf
    coloured by its amino acid at `pos` (explicit `colors_by_aa`, else by frequency — most
    common = grey, variants pop), with the position label below. Settings key `"dash_bars"`,
    CLI `--dash-bar=POS`. **Verify:** `sh cc/tal/test/test-draw-tree.sh` (dash-bar case) on the
    aa-sequence tree (pos 3: T grey, the A variant red).
19. **settings-v3 reader — DONE (structural).** [`py/ae/tal/settings_v3.py`](../../py/ae/tal/settings_v3.py)
    translates an acmacs-tal `{"N":…}` `.tal` config into the tal-draw schema:
    relaxed-JSON load (tolerates trailing commas / `//` comments), `$var` defines, named
    sub-array recursion, `?N` skipping, and command mapping — `canvas`→image_size,
    `clades`/`clades-whocc`→clade column, `time-series`→time-series, `draw-aa-transitions`
    (`method`/`min-leaves`)→aa-transitions, `hz-sections`→hz-sections, `dash-bar-aa-at`→dash
    column, `nodes` select/apply→node-mods, `tree` `color-by`→leaf colouring (see #21), and
    `if`/`then`/`else` conditionals (see #23). `tal-signature-page --tal CONFIG.tal -D name[=val]`
    translates + renders (`-D name` is a truthy flag for conditions). **Structural, not pixel-perfect:**
    the few remaining unsupported bits (exact layout ratios, `for-each`) are collected as `warnings`,
    not silently dropped; `apply.text` positioned labels, per-clade `show:false`, colouring, and
    conditionals now all map. **Verify:** `python3 cc/tal/test/test-settings-v3.py` (synthetic config,
    28 mapping + grammar checks); a **real** h3.tal + its 70k-leaf tree translated and rendered in
    ~1.3 s (clade column + monthly time-series + labels all present).
20. **DrawOnTree positioned labels + per-clade hiding — DONE.** `nodes` `apply.text` now draws a
    positioned text label at a leaf tip (`NodeText{text, offset, color, size}`; offset/size as
    fractions of image_size) — port of acmacs-tal `DrawOnTree`. Per-clade `show:false` (settings
    `clade_styles[].hide`) suppresses a clade's bar + label from the clades column and legend while
    keeping its leaves drawn (AD semantics — `show:false` hides the annotation, not the subtree).
    Both wired through `draw-tree.{hh,cc}`, `settings.cc`, and the settings-v3 reader
    (`apply.text`→node text; `clades` `per-clade`→`clade_styles`). **Verify:**
    `sh cc/tal/test/test-draw-tree.sh` (per-clade-hide + positioned-labels case) + a PDF-text check
    (display-name `clade-X` and labels `vaccine`/`ref` present; hidden clade `Y` gone from the column
    /legend, its leaves still drawn).
21. **Continent / aa-pos leaf colouring — DONE.** Leaf colour now resolves by aa-at-pos >
    continent > clade > black (`draw-tree.cc` `leaf_color`). `color_by_continent` uses the AD
    continent palette (ported into `draw-tree.cc`); `color_by_pos` colours by amino acid at a 1-based
    position — explicit `color_by_pos_colors` or, when absent, by frequency (most common = grey,
    variants pop, shared `frequency_palette`). The bottom legend is now mode-aware (clade /
    continent / `<pos><aa>`). Wired through `settings.cc` (`color_by_continent`, `color_by_pos`
    `{pos, colors}`), the CLI (`--color-by-continent`, `--color-by-pos=N`), and the settings-v3
    reader (`{"N":"tree","color-by": "continent" | {"N":"pos-aa-frequency"|"pos-aa-colors","pos":N}}`
    + `legend.show`). **Verify:** `sh cc/tal/test/test-draw-tree.sh` (continent + by-pos cases on
    `tree-geo.json` / `tree-aa.json`) + PDF-text check (continent legend `EUROPE/ASIA/NORTH-AMERICA
    /AFRICA`, by-pos legend `3T`/`3A`); `python3 cc/tal/test/test-settings-v3.py` (15 checks).
22. **`if`/`then` conditionals + `-D` defines — DONE.** The settings-v3 reader now interprets
    `{"N":"if","condition":…,"then":[…],"else":[…]}` instead of dropping it: `_eval_condition`
    ports the AD grammar (`$var` resolve, `and`/`or`/`not`/`empty`/`not-empty`/`equal`/`not-equal`,
    bool/number literals) and the matching branch is run as a sub-program. `bin/tal-signature-page`
    now accepts bare `-D name` (truthy flag) as well as `-D name=value`. **Verify:** `python3
    cc/tal/test/test-settings-v3.py` (12 direct grammar checks + an `if`-gated dash-bar in the
    synthetic config: pos 145 included when `$enable_extra` set, pos 999 `not`-branch excluded).
23. **Finer signature-page layout — DONE.** `py/ae/tal/signature_page.py` `compose_grid` composes
    the tree (left) + an R×C grid of **captioned** antigenic maps (right) with an optional page title
    and tree caption, via `pdflatex` (LaTeX `geometry`+`graphicx`); columns default to
    `ceil(sqrt(n))`. Falls back to the plain `pdfjam` stack when `pdflatex` is absent. Used by
    `make_signature_page` (and `tal-signature-page`'s `--caption` / `--page-title` / `--tree-caption`
    / `--columns`) whenever any grid option is given; the plain side-by-side path is unchanged.
    **Verify:** `sh cc/tal/test/test-signature-page-grid.sh` (tree + 3 captioned maps, 2-col grid,
    title → one landscape A4 page; pdftotext confirms title + all captions present).
24. **Low-value tail — mostly DONE (2026-06-17).** `for-each` loops (`settings_v3` `run()` binds
    `$var` over `values` and runs `do` per iteration); `ladderize` (`max-edge-length` was a stub in
    `cc/tree/tree.cc` `Tree::ladderize` — implemented via the existing `compare_max_edge_length`
    comparator, and wired through `settings_v3`→`settings.cc`→`draw-tree.cc` `tree.ladderize()` before
    `compute_layout`, + `--ladderize=`); `.names` output (`tal-draw out.names` writes shown leaf names
    in draw order via `compute_layout`). **Verify:** `cc/tal/test/test-settings-v3.py` (for-each
    expansion + ladderize schema) + `test-draw-tree.sh` (`.names` draw order, `--ladderize=max-edge-length`
    reorders). **Only `.html`** interactive tree output remains deferred (a separate renderer port that
    overlaps kateri; no seasonal-report need).
25. **Report-tree fidelity (from ssm-report #4 (b), 2026-06-15) — IN PROGRESS (code landed, build/verify
    pending).** Rendering the real report `.tal` (`{bvic.after-2021, h3.after-2021}.tal`) via
    `ae.report.trees` → `tal-draw` produced *square* PDFs with a purple aa-transition flood, monochrome
    matrix and 38k/70k leaf labels — unfaithful to the AD portrait references (bvic 631×1000, h3 648×1000).
    Fixed (in code):
    - **Portrait canvas.** `TreeDrawParameters.width_to_height_ratio`; `export_tree_pdf` draws a page of
      width = height × ratio (square when 0). The X axis uses `width`/`margin`, the Y axis `height`/`vmargin`
      (split out a vertical margin + reworked the title/legend/positioned-label coordinates accordingly).
      Positioned-label offsets are now fractions of width (x) / height (y); label `size` a fraction of height.
    - **Aspect from the `.tal`.** `py/ae/tal/settings_v3` reads `{"N":"tree","width-to-height-ratio":r}` and
      computes the overall page ratio. *(Originally a per-column allowance — clades +0.07, time-series +0.13,
      dash +0.025 each, hz +0.03, labels +0.10 — superseded by the faithful program-order sum in #26.)*
    - **Clade-coloured matrix, black edges.** `clades-whocc` → `color_by_clade`; a new `edge_color_for`
      keeps tree edges BLACK under clade colouring while `leaf_color` colours the matrix (time-series dashes
      / clade column) by clade. Only by-continent / by-aa-pos recolour edges (acmacs-tal semantics).
    - **No aa-transition flood.** `draw-aa-transitions` was being translated to consensus `compute=True`,
      labelling every inode (the purple). Now compute is off; the curated `per-node` labels are placed (see below).
    - **Curated `draw-aa-transitions` labels — DONE (MRCA).** Each `per-node` entry selects its node by AD's
      draw-time `node_id` "vertical.horizontal", which ae's `.tjz` lacks — BUT every entry also records that
      node's first/last leaf seq_ids (as `?first`/`?last`, `?`-disabled). Since **MRCA(first,last) IS that
      node**, the translator emits an `MrcaLabel{first,last,text,offset,…}` and `tal-draw` finds the MRCA (leaf
      lookup + `Tree::parent` walk in `draw-tree.cc`) and draws the label there — no AD node-numbering port
      needed. 33/44/40 labels render on bvic/h3/h1. `MrcaLabel` in `draw-tree.{hh,cc}`, parsed in `settings.cc`,
      emitted by `settings_v3`. **Verify:** `sh cc/tal/test/test-draw-tree.sh` (MRCA(A,B) case) +
      `cc/tal/test/test-settings-v3.py`.
    - **Translator nits.** `?`-prefixed string refs (e.g. `"?dash-bars"`) skipped silently (were recursing
      into the disabled array); per-leaf name labels default off for these dense trees.
    **Still open:** #2 curated per-node aa-transition labels (need node_id), exact WHOCC clade hex palette,
    geographic world-map inset (#5). **Verify (pending build):** rebuild
    `tal-draw`, run the §reproduce loop, `pdftoppm -png -r 100` + eyeball; confirm bvic/h3 come out ~0.63/0.65
    portrait, edges black, matrix clade-coloured, no purple flood.
26. **Faithful page-width accounting (from ssm-report #4, 2026-06-16) — DONE.** The #25 per-column
    *allowance* (fixed increments by which columns are present) was structurally wrong: column COUNT does not
    predict width — h3 has the most dash columns yet renders narrower than h1 (whose clades column alone is
    0.092 and whose time-series slots are nearly 2× as wide). The old heuristic left h1 ~19% too narrow
    (~640 vs the AD reference 794). Replaced by `_compute_layout_width` in
    [`py/ae/tal/settings_v3.py`](../../py/ae/tal/settings_v3.py), a port of acmacs-tal's actual sizing
    (cc/draw.cc `Draw::set_width_to_height_ratio` + cc/layout.cc `Layout::width_relative_to_height`):
    `page_ratio = (Σ enabled normal-position element widths + margin.left + margin.right) / (1 + margin.top
    + margin.bottom)`. The sum walks the `.tal` program in order (following string + `{"N":"<sub-array>"}`
    invocations, `if`/`then`/`else`, skipping `?`-disabled), contributing per element: **tree** its
    `width-to-height-ratio`; **gap** `pixels`/canvas-height (pixels wins) else `width-to-height-ratio` else
    the 0.05 default; **time-series** `n_slots × slot.width` (slot 0.01 default; `n_slots` = whole months in
    `[start, end)`, end exclusive); **clades** its explicit `width-to-height-ratio` (the reports always set
    it) else `(n_slots+2)×slot.width`; **dash-bar / -aa-at / -clades** explicit `width-to-height-ratio` else
    the 0.009 `DashBarBase` default; **hz-section-marker** 0.005; everything else (title, draw-aa-transitions,
    tree-only hz-sections, nodes, …) absolute / 0. Margins default `{left .025, right 0, top .025, bottom
    .025}`, a `margins` command overriding only named keys. **Builtin layout hook:** acmacs-tal's
    `layout-tree-only` (conf/tal.json) draws tree/time-series/clades as id-keyed singletons the user `.tal`
    overrides (settings find-or-update), but it *also* invokes three user-overridable column hooks between
    tree and time-series — `tal-dash-bar-left-1`, `tal-dash-bar-clades`, `tal-dash-bar-left-2` — that the
    user program never invokes itself; the reports redefine `tal-dash-bar-clades` to add a per-subtype gap
    (h3 0.015, h1 0.009; empty for bvic), so those are walked (if not already visited) after the user
    program. **Result:** ae now matches the AD references to <0.1px — bvic **631.6**, h3 **648.6**, h1
    **794.3** (×1000), vs AD 631.6 / 648.6 / 794.3. **Verify:** `python3 cc/tal/test/test-settings-v3.py`
    (30/30 green); render the three report `.tal` via `ae.report.trees.make_tree` → `pdfinfo` page size.

- **Milestone: continent legend (top-right) + curated clade-label column (vs AD refs).** Two gaps
    remained on the report tree page vs `/tmp/ad-{h1,h3,bvic}.*.pdf`: no colour legend, and the clade
    column was sparse/mispositioned (drawn left of the matrix, every fragmented section as its own bar,
    no curation). Fixed:
    - **`clades-whocc` is the report's OWN sub-array, not a builtin.** The translator
      (`settings_v3.run`) was intercepting the string `"clades-whocc"` as a hardcoded builtin
      (set `clades.show` + continent) **before** the `elif item in tal` sub-array branch — so the
      report `.tal`'s own `clades-whocc` array (a `{"N":"clades", "per-clade":[…]}` carrying the
      curated show/hide + display-name set) was never run and **all curation was dropped** (0 clade
      styles). Now the `clades-whocc` handler sets continent + `legend.show` and then **runs the
      user sub-array if defined** (builtin fallback only when undefined). h1 now yields 33 hidden +
      curated display names (e.g. `C.1.8.other` → `C.1.8`), 20 visible clades.
    - **`clades` no longer forces clade-colouring under continent.** The `clades` command set
      `color_by_clade=True` unconditionally; under the WHOCC continent reports that fought the
      continent matrix. Now it only sets `color_by_clade` when `color_by_continent` is not already on.
      Also reads the `display_name` key directly (not only `label.text`).
    - **Continent legend → top-right** (`draw-tree.cc`). The legend (coloured swatch + name per
      `legend_items`, active-mode = continent/aa-pos/clade) was a bottom-left row; now a right-aligned
      vertical stack in the top-right corner (acmacs-tal `LegendColoredByPos` offset), so it no longer
      needs a bottom reserve. (AD draws the *continent* legend as the bottom-left world map —
      `LegendContinentMap`, `continent-map.hh`; ae has no map asset linked into `tal-draw`, so the
      coloured-squares legend top-right is the substitute. World-map inset stays open, #5.)
    - **Clade column → bracket staircase, between matrix and dash-bars.** The clades column sits
      after the time-series matrix and left of the aa dash-bars (AD column order). Each shown
      clade is a vertical **double-arrow bracket** (spine + arrowheads, BLACK) with a **rotated**
      name label and top/bottom **horizontal arms**, in a **slot** (`set_slots` port): widest
      extent → slot 0 (the **LEFT** edge, matrix side), overlapping sub-clades bumped **right** →
      AD's nested staircase with **deeper clades to the RIGHT of their parent** (e.g. h3 `K` right
      of `J.2.4`). *(This is AD's time-series-to-the-left layout: `pos_x = viewport.left +
      slot.width·(slot+1)`, horizontal_line from viewport.left to the spine. An earlier ae version
      had slot 0 at the right edge / deeper-left — the opposite — now corrected.)* ae's `compute_clade_sections` has **no section tolerance**
      (acmacs-tal `section-inclusion/exclusion-tolerance`), so a clade interrupted by interspersed
      leaves fragments into dozens–hundreds of 1-leaf sections (e.g. `C (5a.2)`: 338 sections). Drawing
      them all was a cloud of ticks. Approximated the tolerances **at draw time**: drop sections below
      a leaf-count floor (`max(5, 0.001·height)`), then merge survivors separated by ≤ `0.04·height`
      into bands → one (or a few) clean bracket(s) per clade. Eyeballed h1/h3/bvic: legend top-right,
      `C (5a.2)`/`C.1 (5a.2a)` outermost, `C.1.1`/`D`/`D.3.1`/`D.x`/`C.1.7.x`/`C.1.8`/`C.1.9.x` nested
      (h1); `J.x`/`K` (h3); `C.5.x`/`V1A.3a2` (bvic) — structurally matching the AD refs.
    - **Wiring.** `legend.show` already flowed end-to-end (`TreeDrawParameters.legend`,
      `settings.cc` `config["legend"]["show"]`, `--legend` CLI flag); the only missing link was the
      translator enabling it under `clades-whocc` (now done). Tests: `test-settings-v3.py` +3 checks
      (clades-whocc sub-array runs, `display_name` key, continent kept); `test-draw-tree.sh` + a
      continent-legend-top-right + clade-column render case. Both green.
    **Approximations / deferred:** per-clade label rotation/scale/slot/offset and the exact
    `section-*-tolerance` values from the `.tal` are not honoured (global draw-time floor/merge instead);
    the world-map continent inset (#5) is still unported (squares legend used).

**Not a remaining item — `clades-whocc` (clade-from-sequence assignment).** This was struck off
after auditing the AD source. In acmacs-tal `clades-whocc` is a draw-time settings macro that
expands to per-clade `clade_set_by_aa_at_pos` calls — and it is **obsolete in AD itself**
(`conf/tal.json` marks it `"clades-whocc obsolete"`; the "forgot to add clades-whocc?" warning in
AD `cc/tree.cc` is commented out), because clades are now assigned **upstream at tree-build time
(seqdb-3)** and stored in the `.tjz`, which ae's `tal-draw` already reads. Where persisted
relabelling *is* wanted, ae already has the engine: `Tree::set_clades(clades_json)`
(`cc/tree/tree.cc:305`, bound as `tree.set_clades("clades.json")` in `cc/py/tree.cc`) re-derives
each leaf's clades from its aa/nuc sequence via the `cc/sequences/clades.hh` `Clades` engine (WHOCC
aa-at-position rules, e.g. `acmacs-data/clades.json` / `semantic_clades.py`) and `export` writes
them back. So nothing to port here — a draw-time recompute would only duplicate the tree's stored
clades.

---

## Geographic inset (continent-coloured world map, lower-left) — DONE

Port of AD `acmacs-tal` `LegendContinentMap` (`cc/legend.{cc,hh}`), which draws the small
continent-coloured equirectangular world map in the lower-left of the signature page. It
doubles as the **continent legend** for the report's continent-coloured tree/matrix.

**Files**
- `cc/tal/continent-map.{cc,hh}` — the per-continent baked outline + draw helper.
  `continent-map.cc` is AD `acmacs-draw/continent-path.cc`'s path data **verbatim** (the
  ten `static const double <continent>[][2]` arrays, freevectormaps.com data processed by
  AD in 2016), wrapped in `ae::tal`. `draw_continent_inset(pdf, x, y, w, h)` reproduces AD
  `continent-map.cc::continent_map_draw`: loop the nine drawn continents (Antarctica
  omitted, matching AD `ContinentLabels`) and fill each in its own colour.
- Colour palette is **reused** from `cc/geo/geographic-map.cc` (`ae::geo::continent_color`,
  the exact AD `acmacs-base/color-continent.cc` primary palette). To link that symbol,
  `meson.build`'s `tal-draw` target now also compiles `cc/geo/geographic-map.cc` +
  `cc/geo/geographic-path.cc`.

**Coordinate conventions — note the difference from `cc/geo/geographic-path.cc`.**
The continent data lives in a `{660, 320}` rectangle (`continent_map_size`) — its own
projection, *not* the surveillance world map's `{1261.3, 632.591}` / lon-lat bounds. And
its negative-move encoding negates **both** coords on a move entry (AD
`path_fill_negative_move` → `close_move_to_line_to` uses `std::abs` on x *and* y), whereas
`cc/geo/geographic-path.cc` negates only x and keeps y as-is (consumed by
`CairoPdf::path_negative_move`, which only flips x back). So `draw_continent_inset` rewrites
each move entry to `{-dev_x(|x|), dev_y(|y|)}` before handing the subpath to
`CairoPdf::path_negative_move` with a transparent outline (fill only, no coastline).

**Wiring**
- `TreeDrawParameters::geo_inset` flag (`cc/tal/draw-tree.hh`); drawn in
  `export_tree_pdf` just before the leaf-tip text labels. Box = 18% of page width with the
  map's aspect, sitting just above the bottom margin. When `geo_inset && color_by_continent`
  the bottom-row continent **swatch legend is suppressed** — the inset is the legend.
- Parsed from the JSON settings key `geo_inset` in `cc/tal/settings.cc`; CLI `--geo-inset`
  in `cc/tal/tal-draw-main.cc`.
- `py/ae/tal/settings_v3.py` sets `geo_inset: true` whenever a `.tal` references the
  `clades-whocc` builtin (alongside the existing `color_by_continent`), mirroring AD's
  WHOCC builtin which draws the `LegendContinentMap`.
- `cc/tal/test/test-draw-tree.sh` has a synthetic `--color-by-continent --geo-inset` case.

**Verified** by rasterising the three report trees (h1/h3/bvic `*.after-2021`) and the
synthetic `tree-geo.json`: a nine-colour continent map renders lower-left on each, matching
the AD reference PDFs (colours per `ae::geo::continent_color`: N-America dark blue,
S-America turquoise, Europe green, Africa orange, Middle-East purple, Asia red, Russia
maroon, Australia-Oceania pink, Central-America cyan).

---

## Build & verify notes (gotchas hit during the layout milestone)

- **Reconfigure fails on the `lexy` CMake subproject** ("Compatibility with CMake < 3.5
  has been removed"). Any `meson.build` edit triggers a reconfigure that re-runs lexy's
  vendored CMake. Work around it by exporting `CMAKE_POLICY_VERSION_MINIMUM=3.5` before
  `ninja` (newer CMake honours this env var). Then the normal arm64 ninja line builds.
- **`stubgen` step fails** (`mypy` is x86_64, the build is arm64) — this is the *last*
  target and is non-essential type-stub generation; `ae_backend.*.so` links fine before it.
  Ignore the stubgen error.
- **An editable-install `ae_backend` shadows the fresh build.** `python3` may resolve to
  Homebrew 3.14 (wrong ABI), and even with 3.10 a meta-path finder loads
  `~/AC/projects/ae-backend/build/cp310/ae_backend…so` ahead of `build/` regardless of
  `PYTHONPATH` / `sys.path.insert(0, …)`. Load the exact `.so` by path via
  `importlib.util.spec_from_file_location` (see `test/test-layout.py`).
- **Deep newick trees (≳1000-node caterpillar) — FIXED.** The Newick parser in
  `cc/tree/newick.cc` was a lexy recursive-descent grammar whose real C++ recursion was
  capped at `max_recursion_depth=1000`; deeper trees aborted the parse, `load_newick()`
  returned `nullptr`, and `ae::tree::load()` then segfaulted dereferencing it inside
  `calculate_cumulative`. Replaced the recursive grammar with a hand-written iterative
  scanner driving the existing explicit-stack `tree_builder_t`, so parse depth no longer
  consumes C++ call-stack (verified: 5000-leaf caterpillar loads). Added a `nullptr` guard
  in `load()` so genuinely malformed input raises a clean `RuntimeError` instead of
  crashing. `calculate_cumulative` / `set_node_id` were already iterative and were only
  victims of the null deref. `compute_layout` was always iterative and safe.

## 6. Conf / format docs to mine next
- `~/AC/eu/AD/sources/acmacs-tal/doc/tal-conf.org` — the settings DSL reference.
- `~/AC/eu/AD/sources/acmacs-tal/doc/tal-processing.org` — processing stages.
- `~/AC/eu/AD/sources/acmacs-tal/doc/phylogenetic-tree-v3.format.json` — JSON tree schema.
