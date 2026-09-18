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
   **Section tolerance + hz-sections — DONE** (same files): `apply_section_tolerance()` ports
   `Clades::make_sections()` (`section-inclusion-tolerance` bridges a run split by interspersed
   leaves of another clade; `section-exclusion-tolerance` then drops the leftovers, unless every
   section of the clade is small, in which case acmacs-tal keeps them all), and
   `compute_hz_sections()` ports `Clades::make_clades()` handing its sections to `HzSections`
   plus `HzSections::sort / detect_intersect / set_prefix / set_aa_transitions` — ids
   `"{clade}-{section no}"`, prefixes A, B, C… top-to-bottom, and each section's transitions
   accumulated (add-or-replace by position) from every inode whose subtree contains it. Exposed
   as `ae_backend.tal.compute_hz_sections(tree, per_clade, all_clades)` with
   `ae_backend.tal.CladeSectionParameters`; the per-clade map is built from a `.tal`'s `clades`
   block by `ae.tal.settings_v3.parse_clade_section_parameters` and fed in by
   `ae.tal.section_maps.compute_sections`. This is the path acmacs-tal itself takes whenever the
   `hz` sub-program is absent from the running program — true of every report `.tal`'s own `tal`
   program from 2026-0805-tc1 on, which is what makes signature pages buildable again. Verified
   by [`test/test-clade-hz-sections.py`](../../test/test-clade-hz-sections.py) and differentially
   against AD (see the note under #7).
6. **Time series (date bucketing) — DONE.** [`time-series.hh`](time-series.hh)/[`time-series.cc`](time-series.cc),
   `ae::tal::compute_time_series(Tree&, interval, start?, end?)` → `TimeSeries{slots[], …}`
   for year/month/week/day intervals. Ports the *data* side of `time-series.cc` (slot
   generation + per-slot leaf counts) using `ae::date` + C++20 `<chrono>` instead of porting
   `acmacs-base/time-series`. Reuses `ae::tree::Leaf::date`. Exposed as
   `ae_backend.tal.compute_time_series`. Verified by
   [`test/test-time-series.py`](test/test-time-series.py).
   **The range is half-open `[start, end)`, and `end` is excluded exactly once** — on the slot
   generator's loop condition, as in `acmacs-base` `time_series::make` (`cc/time-series.cc:53`,
   `current < param.after_last`, where `current` is the slot's own start). An `end` of `"2026-10"`
   therefore draws the slot beginning September 2026. It was briefly excluded *twice* (`end` stepped
   back a day *and* the loop stopped early), which silently dropped the last slot of every explicit
   range — one month at the month interval, a whole year at the year interval (a one-year range came
   out empty), and it also made a mid-month `end` drop that month. An empty `end` still includes the
   bucket holding the latest leaf date. `test-time-series.py` now carries the five
   parameters→expected-series cases transcribed from AD's own
   `acmacs-base/cc/test-time-series.cc`, so ae is pinned to AD without needing AD built. AD's two
   *weekly* cases are excluded on purpose: AD's `detail::first()` leaves a week range's start
   un-snapped while ae aligns to the Monday on/before `start` — same slot count, offset by up to six
   days. That divergence is pre-existing and untouched.
7. AA-transition labelling — `cc/tree/aa-transitions.cc` already ports a consensus method;
   reconcile with acmacs-tal's versioned algorithms when richer labelling is needed.
   **This is now the one measured gap in the hz-section path.** The report `.tal`s ask
   `draw-aa-transitions` for `method: eu-20200915` (acmacs-tal
   `cc/aa-transition-20200915.cc`), which anchors every transition's left-hand residue to the
   **root sequence** and then runs a multi-pass flip/left-right-same cleanup. ae's `consensus`
   has no root anchoring, so it disagrees with acmacs-tal on which substitutions appear and on
   their polarity: measured on a real B/Vic tree, ae reports the left and right residues of a
   shared position the other way round from acmacs-tal, and produces none of acmacs-tal's
   root-anchored ancestral substitutions at all. The section *boundaries* are unaffected —
   they match acmacs-tal exactly — but the transition strings do not, so
   `ae.tal.section_maps.compute_sections` leaves them blank unless explicitly asked
   (`aa_transitions=True` / `AE_SECTION_AA_TRANSITIONS=1`) rather than printing wrong
   substitutions onto a report figure. Porting `eu-20200915` closes this.
   Phase A is otherwise complete (hz-section detection landed under #5).

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
27. **The rendered page was 5% wider than the ratio said (2026-09-15) — DONE.** #26 got the *ratio* right,
    but the rendered page did not follow it: every ae tree PDF came out **exactly 1.05×** AD's width for the
    same `.tal` + `.tjz` — bvic 663.2 vs 631.6, h1 834.0 vs 794.3, h3 681.0 vs 648.6 (×1000pt canvas), a
    5.00% / 5.00% / 5.00% overshoot. Cause: **`cc/tal/draw-tree.cc`** reserved a left band for the
    auto-placed aa-transition labels and ADDED it to the page —
    `aa_band = 0.05 * width_base; width = width_base + aa_band` — where AD draws exactly
    `height_ * width_to_height_ratio_` (cc/draw.cc:43) and reserves nothing. The 0.05 band is an ae-only
    device (AD has no auto-placer), so **AD is right**: the page is now `width_base` and the band is taken
    out of the drawable width (`aa_left`, as an earlier attempt did). The two objections that had the
    carved-out form rejected before do not apply any more — the title is drawn at the root, not the page
    margin, and the label metrics *improved*: on the three 2026-0223 trees, residual conflicts stay 0/0/0,
    worst leader 11.6→9.9 / 9.3→5.3 / 12.6→12.1 % of the page, off-envelope 1→0 / 0→0 / 2→1. (Dropping the
    band to 0 instead is measurably worse: bvic 3 residual leader/leader conflicts, h3 1 leader-over-text,
    worst tree-ink crossing 33→95 / 30→94 cells.) `settings_v3` also now rounds the ratio to **6** decimals,
    not 4 — on a 1000pt canvas 4 dp was up to 0.05pt out (measured 0.019/0.014/0.029pt). **Result:** page
    size is AD's to the printed precision — **631.619 / 794.286 / 648.571 × 1000**, both engines, same run.
    Only the tree page is affected; the signature-page path reserves no band (`output` is empty there).
    **Verify:** `python3 cc/tal/test/test-page-size.py` (7 checks; fails with `TAL_DRAW=` pointed at a
    pre-fix binary, reporting 630 where 600 is expected). Its last two checks pin the drawn
    time-series slot count to the count `settings_v3._time_series_slots` sized the page for — the two
    had drifted by one slot (12 sized, 11 drawn) while the page stayed the right width.

- **Milestone: fractional / negative clade `slot`, and a settable clades column gap.** A clade
    bracket sits at `slot.width * (slot + 1)` from the clades column's inner edge (AD
    `acmacs-tal cc/clades.cc:269`), and the column is one inter-column gap past the time-series
    matrix — so the matrix→bracket distance is `gap + slot.width*(slot+1)`. The only `.tal` lever on
    it used to be `slot.width`, which also sets the pitch between clade levels *and* the label size,
    so pulling one bracket towards the matrix shrank the whole staircase. Two levers now:
    - **`slot` is a `std::optional<double>`** (`CladeStyle::slot`), not an `int` with `-1` meaning
      "auto". Fractions and small negatives are honoured, so one bracket moves by a part-slot at
      full `slot.width`. Note AD's own `slot_no` is an unsigned `named_size_t`
      (`acmacs-tal cc/clades.hh:20`) and truncates `2.2` to `2`, so **this is a deliberate superset
      of AD, not a parity fix** — an integer `.tal` renders identically either way. Auto-placement
      still works in whole columns and reserves the column a fractional slot rounds to, so an
      auto-placed clade is never pushed onto a fractional neighbour's step.
    - **`clades.gap_ratio`** overrides the gap before the clades column (fraction of page width;
      `0` is legal and puts the column flush against the matrix; unset keeps the shared `0.012`).
      AD gets this from the explicit `{"N": "gap"}` element the `.tal` program puts between the two
      columns; ae lays the columns out itself, so it reads a ratio on the `clades` command.
    Measured at `slot.width` 0.02 on a 600×1000 page (one slot = 20pt, default gap = 7.2pt):
    matrix→bracket 27.20pt at slot 0, **17.20pt at slot −0.5**, 37.20pt at 0.5, and **10.00pt** at
    slot −0.5 with `gap_ratio: 0` — against 20.20 / 17.20pt from squeezing `slot.width` to
    0.013 / 0.010, which drags the level pitch down from 20pt to 13 / 10pt with it.
    **Verify:** `python3 cc/tal/test/test-clade-slots.py` (12 checks; 11 of them fail against a
    pre-fix binary, which renders slot −0.5, 0 and 0.5 identically).

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
      leaves fragments into dozens–hundreds of 1-leaf sections (the worst h1 clade: 338). Drawing
      them all was a cloud of ticks. Approximated the tolerances **at draw time**: drop sections below
      a leaf-count floor (`max(5, 0.001·height)`), then merge survivors separated by ≤ `0.04·height`
      into bands → one (or a few) clean bracket(s) per clade. Eyeballed h1/h3/bvic against the AD
      reference renders: legend top-right, the two broadest clades outermost and each sub-clade
      nested inside its parent, in all three subtypes — structurally matching the AD refs.
      (Clade names deliberately not reproduced here: this is a public repo.)
      *(Update: the real tolerances are now ported — `apply_section_tolerance` in
      [`clades.cc`](clades.cc), item #5 above. The draw-time floor/merge heuristic described here
      is still what the clade **column** uses; the signature-page **section boundaries** use the
      real algorithm and the `.tal`'s per-clade values. Moving the column onto it too would remove
      this approximation.)*
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

## Report-tree AD-fidelity completion (June 2026) — DONE

Iterative pass (branch `ae-tree`, worktree `~/AC/eu/ae-tree`) to make the three seasonal
report trees pixel-faithful to the AD references
(`~/AC/eu/ac/results/ssm/2026-0223-ssm/tree/{h3,h1,bvic}.asr.after-2021.pdf`). The earlier
items above got the structure right; this pass closed the remaining visual gaps, verified per
subtype against the AD reference (h3 alone is misleading — h1/bvic exposed bugs h3 masked).

**What landed (all three subtypes unless noted):**
- **aa-transition labels** — only the curated `mrca_labels` (no imported-transition flood);
  **monospace**, small, **grey** (`grey30`), with **leader lines** to the branch node.
- **Tree edges black** under WHOCC continent colouring — `edge_color_for`; continent colour
  tints only the matrix/time-series/dash-bars, never the edges. (`color-by:"continent"` on a
  `tree` element sets `color_edges`; the WHOCC continent comes from time-series/clades-whocc
  and does **not**.)
- **Tip strain names** re-enabled at the `.tal` `node-id-size` (0.0002) — tiny zoomable vector
  text (schema `tip_names:true`).
- **Single continent legend** = the lower-left world-map inset only (top-right swatch legend
  suppressed when `geo_inset` is on); **subtype title** (`A(H3N2)`/`A(H1N1)`/`B/Vic`).
- **Vertical fill** — tree+matrix use the full page height; title nudged to the very top.
- **Time series** — narrow AD slot width (`.tal` `slot.width` 0.005, label `scale`), `Mon YY`
  month labels at **top and bottom**, rotated **clockwise** (top→bottom), and faint horizontal
  row lines that **stop at the clade column** (don't cross the tree/left margin).
- **Clade column** (port of AD `clades.cc` `set_slots`) — labels read **top→bottom**, nested
  **rightward staircase** (deeper clade right of its parent, e.g. `K` right of `J.2.4`),
  **per-clade varying label size**.
- **aa colour bars** (`dash-bar-aa-at`) — coloured by **amino-acid identity** from the `.tal`'s
  explicit maps, with a coloured **position+aa legend at the bottom** (e.g. `135K`/`135A`).

**Two `.tal` gotchas worth remembering:**
1. `dash-bar-aa-at` entries come in two shapes: a **colours** shape (`"pos"`, explicit
   `"colors":{aa→hex}` where `"transparent"`=no dash, and a `"labels":{aa→{text,color,
   vertical_position}}` map → the legend) and an **aa-select** shape (`"selects":[{"aa":[…],
   "color":…}]`, multi-position, so it has no single `pos`). The translator must read both and
   honour the explicit colours/labels (not a frequency fallback). h3's third bar is position
   **158** (`158K/158D`), not 156.
2. **h1's colour-bar entries are all `?N`-disabled** in `h1.after-2021.tal` (`"?N":
   "dash-bar-aa-at"`). The translator must **skip any `?`-prefixed key/entry** and render the
   *active* dash-bars — picking up a disabled stub yielded `pos=None` and a blank bar.

**Pixel-diff harness:** [`cc/tal/test/tree-vs-ad.sh`](test/tree-vs-ad.sh) `{h3|h1|bvic|all}`
renders a subtype, rasterises it + the AD reference at matched geometry, and emits whole-page +
per-region RMSE and a `new|AD|diff` montage in `/tmp/treediff_<sub>/`. **RMSE is insensitive**
(dominated by tree-topology AA/alignment) — judge by the diff montage, not the number. Outputs
to `/tmp` only (inputs carry WHO strain data — nothing rendered is committed).

Status: feature-complete vs the AD references; minor cosmetic residuals only (legend lists one
extra aa variant AD omits; AD boxes matrix sections where ae draws separator lines). Branch
`ae-tree` not yet merged to `main`.

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

## eu-20200915 aa-transitions — ported and verified against AD (2026-09-11)

`cc/tree/aa-transitions.cc` now implements **`eu-20200915`** alongside its own `consensus`,
a port of AD `acmacs-tal/cc/aa-transition-20200915.cc`
(`update_aa_transitions_eu_20200915[_per_pos]`). This is the method the report `.tal`s name in
`draw-aa-transitions`. The per-position and all-positions forms of AD's driver are equivalent
(each position is computed independently), so only the per-position one is ported.

What it adds over `consensus`, in order of impact:

1. **Root-sequence anchoring (AD stage 3).** A label's left residue is the right residue of the
   nearest ancestor label at the same position, and where there is none, the residue of the
   tree's first leaf. This is what makes ancestral substitutions appear at all, and what sets
   their polarity. `consensus` had no such pass.
2. **Flip removal (AD stage 3).** A label whose descendants revert it within fewer than 3
   levels, across more than 0.5 % of its leaves, is dropped and the walk repeats.
3. **A stricter notion of "common"** — a node is common only when every child shares its
   consensus; a child is labelled only when at least two of the child's own children share the
   child's consensus.
4. **Label lifting** (AD `Node::replace_aa_transition`) — the same label is removed from the
   nearest descendants that carry one, pruned at the first labelled node on each path.
5. `X` is not counted into the consensus (`-` is), and `left == right` labels are dropped last.

Selectable as `method="eu-20200915"` on `ae_backend.tree.set_aa_nuc_transition_labels`, via a
`.tal`'s `draw-aa-transitions` `method` (settings key `aa_transitions.method`, translated in
`py/ae/tal/settings_v3.py`), and used by `ae.tal.section_maps.compute_sections`.

`AANucTransitionSettings::reset_labels` (default true) exists because **AD's `tal` does not
clear the labels a tree already carries**: `Tal::reset()` runs only in its interactive loop, so
on a `.asr` tjz the method computes on top of the imported `A` labels and those take part in
stage 3's ancestor chain. `compute_sections` passes `reset_labels=False` to match.

**Differential verification against AD, as data** (one AD run and one ae run per tree, same
tjz; AD invoked with a minimal `.tal` selecting the method and `-D ladderize-method=none`,
compared with `tal --first-last-leaves`, which prints each inode's first/last leaf and its
label list — keyed both on pre-order position and on the leaf pair, since node ids differ):

| tree | inodes compared | identical label lists |
|---|---:|---:|
| `bvic.after-2021` (Feb, 38 128 leaves)     | 5 376  | 5 376 |
| `h1.asr.after-2021` (Feb)                  | 16 734 | 16 734 |
| `h3.asr.after-2021` (Feb)                  | 10 136 | 10 136 |
| `h1.asr.after-2021` (Sep, 99 056 leaves)   | 17 585 | 17 585 |

Same substitutions, same order, same polarity, zero differences. End to end, ae's
`compute_sections` reproduces AD's real `sp/0do` section strings for **B/Vic, all 10 sections,
character for character**.

**One residual, and it is not the method.** ae's `compute_sections` does not apply the `.tal`'s
`{"N": "nodes", … "apply": {"hide": true}}` mods, which AD applies before computing; hidden
leaves are excluded from AD's consensus counters, leaf counts and vertical numbering. On the
Sep H1 page (483 hide mods) sections A–C match and D–M differ by 1–2 substitutions; re-running
AD's own command with every `"hide": true` flipped to false makes AD and ae agree on **13/13**.
B/Vic (52 hide mods) matches either way. Closing it means applying the `nodes` hide mods and
reproducing AD's hidden-aware leaf counting and `Tree::set_first_last_next_node_id` vertical
numbering (note the quirk: AD gives a hidden leaf `node_id.vertical = NotSet`, so an inode whose
leftmost leaf is hidden contributes to no section at all) — signature-page-stack work.

**Unrelated pre-existing crash found on the way:** `ae_backend.tree.Tree.ladderize()` segfaults
on a large real tree, and `Nodes.remove()` traps — both reproduce on `tal-clade-sections` at
`HEAD`, untouched by this work.

Tests: `cc/tal/test/test-aa-transitions-eu20200915.py` (7 checks, invented `J`/`O` residues).

## Clade-section diagnostic (`>>> Clades` / `.taleg`) — ported 2026-09-13

Port of AD `Clades::report_clades` (acmacs-tal `cc/clades.cc:221`) plus
`HzSections::report` / `detect_intersect` (`cc/hz-sections.cc:196` / `:112`). It restores the
workflow `RUNNING-THE-REPORT.md` §10.5 is written around, which had no ae equivalent: see each
clade's band count `(N)`, each band's size and leaf range, the **gap** to the next band of the
same clade, and the sibling-intersect warnings — without waiting out a full render.

* **On by default**, as in AD (`Clades::Parameters::report{true}`, acmacs-tal `clades.hh:99`).
  The `.tal`'s `{"N": "clades", …}` command turns it off with `"report": false`, and can redirect
  the file with `"report-file"` (`"-"` = no file). Translated by `py/ae/tal/settings_v3.py`,
  read in `cc/tal/settings.cc`.
  *(No report `.tal` sets `report` at all — AD printed the block because the default is true.)*
* **Output**: stderr, and `<output>.taleg` beside the rendered PDF (§10.5 documents reading
  that file). The shared-surface entry point (signature pages) passes no output path and so
  writes no file.
* **`tal-draw --clades-report`** prints the diagnostic and exits *before* `make_surface`, so no
  PDF is drawn: **0.6 s** on this round's bvic tree versus minutes for the full render.
* The `[…]` hz dump reproduces AD's column-aligned `hz` `"sections"` shape, so it can be pasted
  straight back into a `.tal`. Each section carries its **id** (`{clade}-{section no}`), which
  distinguishes a genuinely non-monophyletic clade from a stale-id duplicate.
* aa-transitions come from `ae::tal::section_aa_transitions` (`cc/tal/clades.cc`), factored out
  of `compute_hz_sections` so the diagnostic and the signature-page path report identically.
  They are empty when the tree's inodes carry no `A` field (B/Vic this round) — as in AD.

### Section aa-transitions: where ae deliberately does NOT match AD

Two independent things decide a section's aa-transitions text, and only one of them was ever
wrong in ae. Measured 2026-09-14 on the current round's three trees, AD (`AD/bin/tal`) and ae
(`tal-draw --clades-report`) re-derived in the same session, comparing the `All transitions`
string per section id. Both engines produce the **same section ids and the same `V` ranges** on
all three trees, so the spans are not in question.

**1. The accumulation (`section_aa_transitions`) — ae is right, AD has a sentinel bug.**

> **ACCEPTED DIVERGENCE — Sarah, 15 Sep 2026.** ae stays correct here rather than
> bug-compatible, and this is the standing decision: **h3's five differing sections are
> expected and are not a parity gap to close.** Do not "fix" ae to reproduce AD's answer.
>
> This was challenged before it was accepted, on the grounds that earlier "AD is buggy"
> reports had turned out to be correct AD behaviour misread. It survived the challenge, and
> *why* it survived is the part worth carrying forward: those earlier reports rested on
> **inferring intent**, whereas this one rests on an **unsigned sentinel reaching a `<=`** —
> `node_id_t::value_type` is `unsigned` and `NotSet` is `static_cast<value_type>(-1)`
> (`cc/tree.hh:52-53`), i.e. `0xFFFFFFFF`, the maximum. A comparison against it is
> unconditionally true one way and unconditionally false the other, under any reading of
> what the author wanted. Apply that test — *is this checkable without knowing anyone's
> intent?* — before accepting the next claim of this shape.
>
> Corroborating, from AD itself: `hz-sections.cc:82-83` warns when these extent pointers are
> **null**, so the author was guarding boundary cases here and missed the `NotSet` one.
>
> No report impact either way: both 2026-0921 round `.tal`s pin AD's text through the static
> `hz-sections` `aa_transitions` override, so the printed titles are AD's regardless. This is
> about the computation behind them.

AD's `HzSections::set_aa_transitions` (`acmacs-tal/cc/hz-sections.cc:84`) tests

```cpp
(section.first->node_id.vertical >= node.first_prev_leaf->node_id.vertical) &&
(section.last ->node_id.vertical <= node.last_next_leaf->node_id.vertical)
```

where an inode's `first_prev_leaf`/`last_next_leaf` (`Tree::set_first_last_next_node_id`,
`cc/tree.cc:748-754`) are its **literal** first/last descendant leaf — taken from
`subtree.front()`/`subtree.back()` with no regard to `hidden`. A hidden leaf's
`node_id.vertical` is left at the sentinel `node_id_t::NotSet == 0xFFFFFFFF` (`cc/tree.cc:726`),
so an inode whose last descendant leaf happens to be hidden makes the second test
**vacuously true** and its substitutions are attributed to *every* section starting at or below
it; mirror-image, an inode whose first descendant leaf is hidden fails the first test and is
dropped from sections it genuinely contains. ae uses the first/last **shown** leaf instead,
which is what the test is meant to ask.

Verified by re-implementing both rules independently in Python straight off the `.tjz` JSON
(no AD, no ae) on the round's H3 tree, where both engines start from the *same* stored labels
(that `.tal` asks for `method: imported`): the literal-extent rule reproduces AD **9/9**
sections string-for-string, the shown-extent rule reproduces ae **9/9** — and the five sections
where they differ are exactly the ones fed by inodes whose literal last leaf is hidden. On that
tree 13 label-carrying inodes leak that way and 9 are dropped; on H1, 33 and 23. In the worst
case a 2-leaf clade's substitutions were attributed to five sections spanning tens of thousands
of leaves. **Not reproduced in ae**; if a round ever needs AD's exact text, its `.tal` can pin
it with the static `hz-sections` `"aa_transitions"` override (AD's `label_aa_transitions`,
`acmacs-tal/cc/settings.cc:981`), which is what the current round does.

**2. The per-inode labels — ae was wrong, fixed 2026-09-14.** AD's
`Settings::add_draw_aa_transitions` (`acmacs-tal/cc/settings.cc:1256`) sets
`aa_transitions.calculate = true` for **every** `draw-aa-transitions` command, curated or not;
the `per-node` list only chooses what is *drawn*. `settings_v3.py` was dropping the whole
`aa_transitions` schema entry whenever the block carried curated `per-node` labels (which every
report tree `.tal` does), so a `.tal` asking for `method: eu-20200915` silently fell back to the
tree's stored `imported` labels. Now `show` and `compute` are decided separately — and, to match
AD, `tal-draw` computes **after** the node `hide` mods (both engines' consensus counters skip
hidden children) and with `reset_labels = false`. Sections matching AD exactly, before → after:
**B/Vic 0/10 → 10/10**, **H1 0/13 → 3/13**, **H3 4/9 → 4/9** (unchanged: that `.tal` is
`imported`, so nothing is computed; its 5 diffs are the AD sentinel bug above).

**3. The third defect: hidden leaves in the eu-20200915 port — fixed 2026-09-15.** H1's residual
was chased to two places, both about `hidden`, and both now match AD. Measured per-inode against
`AD/bin/tal -s <round>.tal --first-last-leaves 1`, keyed on each inode's (first leaf, last leaf)
pair, with AD and ae re-derived in the same run (ae side: `tal-draw --transitions-report=FILE`,
added for this):

| tree | inodes compared | identical label lists, before → after |
|---|---:|---|
| `h1.asr.after-2021` (99 595 shown leaves, 479 hide mods) | 17 721 | 17 719 → **17 721** |
| `bvic.after-2021` | 6 422 | 6 422 → 6 422 |
| `h3.asr.after-2021` (`imported`) | 13 430 | 13 430 → 13 430 |

* **`hide` was not recursive** (`cc/tal/draw-tree.cc`). AD's `Node::hide()` (`AD cc/tree.cc:567`)
  hides the matched node **and its whole subtree**, and `Tree::hide()` (`cc/tree.cc:594-599`) then
  hides every inode left with no shown child. ae set `shown = false` on the matched node only. The
  layout and the clade sections never noticed — both stop descending at a hidden inode, so the
  vertical numbering is identical either way — but the consensus did:
  `children_with_common_aa` (AD `number_of_children_with_the_same_common_aa`) reads a child inode's
  counter **without** a hidden check, exactly as AD does, and in AD a hidden inode's counter is
  empty because `update_common_aa` skipped all of its (also hidden) children. In ae it was fully
  populated from descendants still marked shown, so a hidden outlier subtree could still "agree"
  with its parent's consensus. On this round's H1 an `edge >= 0.01` mod hides 4 inodes covering 12
  leaves; ae now hides those 12 too, and its shown-leaf counts match AD's exactly (4 mismatches → 0).
  Ported as `propagate_hide()`, run after both node-mod walks.
* **Stage 3 counted hidden leaves.** `Tree::update_number_of_leaves_in_subtree()` counts every leaf;
  AD's `Node::number_leaves` is only ever the **shown** count (`Tree::set_first_last_next_node_id`,
  `AD cc/tree.cc:755-763`, sums `if (!child.hidden)`). Stage 3's flip removal divides the flipping
  descendants' leaves by the ancestor's and drops the ancestor's label when the ratio exceeds 0.5 %
  within 3 levels, so counting hidden leaves there **removes labels AD keeps**. AD's own trace
  (`"debug": true, "debug-pos": 528`) shows it: `keep flips_in_children 528 … leaves: 140 children: 2
  flips: 1 leaves: 0 ( 0.0%) min_flip_distance:1` — the flipping child is an all-hidden 3-leaf inode
  whose imported label still takes part in stage 3, and AD scores it 0 leaves. ae scored it 3/140 =
  2.1 %, dropped the ancestor's label, and the substitution reappeared one level down. Fixed with
  `update_number_of_leaves_in_subtree(shown_only_t::yes)` from the eu-20200915 driver; the default
  stays all-leaves because the tree exporter writes these counts out as the file's own `"L"`.

Regression test: the `tree-aa-hidden.json` case in `cc/tal/test/test-draw-tree.sh` (invented `J`/`O`
residues), which fails if either half is reverted.

Each half was re-checked individually on the merged tree (2026-09-15): reverting the recursive
hide fails the case with *"hide did not reach the hidden inode's leaves (shown leaves: 2)"*,
reverting the shown-only leaf count fails it with *"eu-20200915 dropped the parent's"* label —
two distinct failures, so the case guards both halves rather than one of them twice.

**Re-verified on a second round the fix had never seen (2026-09-15).** The concern was that this
changes *hide semantics*, which reaches far beyond aa-transitions, so it was replayed against the
previous round's three trees with the same driver and the same `.tal`s. Per-inode, AD and ae
re-derived in the same run:

| tree | inodes compared | identical label lists | identical shown-leaf counts |
|---|---:|---:|---:|
| bvic | 5 357 | **5 357** | 5 357 |
| h1   | 16 708 | **16 708** | 16 708 |
| h3   | 10 121 | **10 121** | 10 121 |

Hidden-leaf counts agree with AD on both rounds, and are unchanged by the fix: current round
43 / 491 / 361 hidden (bvic / h1 / h3), previous round 43 / 489 / 316, identical across AD, ae
before the fix and ae after it. The previous round's `.names` dumps are byte-identical before and
after, and the rendered trees pixel-identical — 0 differing pixels at both strict and `-fuzz 30%`
on ~10.6–13.3 Mpx rasters of all three. So the recursive hide reaches exactly the nodes AD hides
and nothing else: it changes the aa-transition consensus, and demonstrably nothing that is drawn.


**With the labels now identical, every remaining section difference is the AD sentinel bug (1).**
Proved by switching *only* the accumulation rule inside ae — `AE_SECTION_AD_SENTINEL=1` makes
`section_aa_transitions` use AD's literal extents with the `NotSet` sentinel, changing nothing else —
and re-deriving both sides in the same run:

| tree | ae's shown-extent rule | ae with AD's literal-extent rule |
|---|---:|---:|
| h1   | 3/13  | **13/13** |
| bvic | 10/10 | 10/10 |
| h3   | 4/9   | **9/9** |

So h1's 10 differing sections and h3's 5 are AD's `HzSections::set_aa_transitions` sentinel bug,
character for character — not port defects, and deliberately not reproduced. The switch exists only
to re-derive that claim; it prints a warning and is off by default.

> **`AE_SECTION_AD_SENTINEL` SHIPS — Sarah, 15 Sep 2026.** Asked explicitly whether to keep it,
> make it test-only, or remove it now this section records the finding; she chose **keep it as
> it is**. So it stays a `tal-draw`-reachable environment switch, off by default and warning when
> set, and the reason is that it makes a parity question here re-derivable in one command instead
> of by rebuilding an argument. It is **not** a licence to turn it on: the divergence above is
> accepted and ae stays correct. Re-derived on the merged tree (`aa-hidden-land`, 2026-09-15) and
> still reproduces AD character for character — h1 3/13 → 13/13, h3 4/9 → 9/9, bvic 10/10 either
> way — so the switch is itself covered by the numbers above.

> **Section-level string parity is NOT a meaningful measure** (`eu-70`/`ssm-a0`, 15 Sep 2026).
> AD has **two** fields where ae has one: `aa_transitions` is **curated** — hand-authored, the
> delta relative to the clade, empty whenever the section simply *is* a clade — and it is what
> the title template prints; `All transitions` is the **computed** cumulative root-to-section
> list, diagnostic only. ae puts the computed list into `aa_transitions` and `section_title`
> (`py/ae/tal/section_maps.py`) concatenates it unconditionally. The two engines were therefore
> never reporting the same quantity, which is the real explanation of the "differs in both
> directions" observation that opened this work. **Read the per-inode numbers, not the
> per-section ones.** Whether ae should grow a separate curated field is a design question;
> Sarah deferred it on 15 Sep 2026 — decide it separately, do not fold it into hidden-handling
> or aa-transition work.

### Reported from the DRAWING path, not `compute_hz_sections`

The diagnostic reports the `clade_plan` bands `draw-tree.cc` actually draws. That matters,
because ae has **two** section implementations and they do not agree:

| | `clades.cc` `apply_section_tolerance` (sig pages) | `draw-tree.cc` clade_plan (the tree) |
|---|---|---|
| merge gap `<= inclusion` | same | same |
| all bands small | AD behaviour: keep them **all** | same (fixed 2026-09-13; had kept only the largest) |
| `all-clades` tolerances | inherited as the per-clade default | **not read**; per-clade only, 0/missing → AD's 10/5 |

The remaining divergence (`all-clades` tolerances) changes nothing on this round's h1/h3/bvic —
no report `.tal` sets them. It is recorded rather than silently "fixed": changing it alters what
gets drawn and is a report-data decision.

### One bracket per BAND (changed 2026-09-13)

`draw-tree.cc` now draws an arrow + arms + label for **every** band that survives the
include/exclude tolerances, all of a clade's bands sharing the clade's slot — AD's per-section
draw (`Clades::draw`, acmacs-tal `clades.cc`). Previously it drew a single arrow over the clade's
**largest** band, so a fragmented clade rendered as one short bracket and the other bands vanished
silently. That hid exactly what §10.5 asks the user to notice; a fragmented clade must *show* as
several brackets, and bringing it back to one is the user's job via the tolerances.

Bands removed by `section-exclusion-tolerance` are still not drawn — that is what exclusion means —
which is why the diagnostic reports them separately: a clade shown `(1)` may be one genuine run, or
several runs whose strays were dropped, and §10.5's "does this resemble last round?" check needs to
tell those apart.

### Merged band size is the SPAN (fixed 2026-09-13)

`draw-tree.cc` accumulated the sizes of the runs it merged, so a merged band's size left out the
bridged gaps. AD's `clade_section_t::size()` is `last->node_id.vertical - first->node_id.vertical + 1`
(acmacs-tal `clades.hh:40-47`), recomputed from the merged first/last; ae's own `clades.cc`
`CladeSection::size()` is span-based too. Only the drawing path diverged, and the effect was that
`section-exclusion-tolerance` dropped bands AD keeps and draws.

**Verified against AD itself** — AD's `tal` run on the same tree + `.tal`, its `>>> Clades` block
diffed against ours. They now agree exactly:

```
C.1.9 (2)  (0) [26823] 25651..52473   gap 45761   (1) [55] 98235..98289
D.5   (2)  (0) [2500]  65602..68101   gap 22811   (1) [22] 90913..90934
```

— same sizes, gaps, leaf ranges, seq_ids and slots, and h3 all `(1)`, bvic `C.1 (2)`, h1 `D.3.1 (1)`.
With the per-band draw above, ae's rendered clade column reproduces AD's: C.1.9 and D.5 each draw
two brackets, bvic C.1 two (slot 4, page y≈28 and y≈804).

Checked against the **unmerged** `aa-label-placement` branch (its left aa band widens the page), by
stacking this work on it and re-measuring: every diagnostic number is unchanged — the band computation works in leaf verticals, before any page geometry — and
the clade column shifts right as a block with spacing intact (bvic slot 4 x 659→692, h1 slot 3
x 662→699; label y unchanged, since the band changes width only). No label collisions: bvic's two
C.1 labels sit at y 28..43 and 804..819, h1's two C.1.9 at y 382..414 and 947..978, and no pair in
any slot overlaps. Note ae's clade-label x then coincides with AD's ≈699 — which is why the
renderer is identified by its stderr banner and `.taleg`, not by coordinates. Recorded here so that
when that branch lands nobody re-investigates the shift; this work itself does not depend on it.

> Running AD's `tal` needs its libraries found: `DYLD_FALLBACK_LIBRARY_PATH=$ACMACSD_ROOT/build/lib:…/build/acmacs-base/dist:…`
> or it aborts with `libfmt.8.dylib not loaded`. ~82 s for a full H1 render, vs 0.6 s for
> `tal-draw --clades-report`.

Measured on `2026-0921-ssm` (`tree/bvic.after-2021.tal`, `tree/h1.after-2021.tal`):

* **bvic `C.1` is `(2)`** — `[873] 60..948` and `[138] 38002..38139`, `gap 37053`; the second
  band is flagged `INTRSCT` against the sibling `C.5-0` / `C.5.1-0`. ae draws only the first.
* **h1 `D.3.1`, `D.5`, `C.1.9` are each `(1)`** in the drawing path. `D.3.1` has no dropped
  bands at all (one contiguous run); `D.5` and `C.1.9` have strays that both ae *and* AD drop,
  since a full-size band survives. Under either implementation these three yield one section.

## Curated `hz-sections` merged into the computed set — ported 2026-09-15

Port of AD `HzSections::update_from_parameters` (`acmacs-tal/cc/hz-sections.cc:44`), with the
`sort` / `detect_intersect` / `set_prefix` that follow it (`:93` / `:112` / `:136`). ae had none
of it, and the gap was invisible on the current round.

**What AD does.** It keeps ONE section list. `Clades::make_clades` fills it from the computed
clade bands (`HzSections::add_section`); `update_from_parameters` then walks the `.tal`'s static
`hz` `sections` array and merges each entry **by id** via `find_add_section`:

* an id already in the list **overrides** that section's `first` / `last` / `show` / `label`;
* an id **not** in the list **adds a section**.

The second half is the whole point. A curator writes `<clade>-1`, `<clade>-2` beside the computed
`<clade>-0` and AD draws three bands where the tree yields one contiguous run. AD also applies a
step-back: when the curated `last` resolves to a `leaf_position::first` node it moves to that
node's previous shown leaf (`:62`), which is what lets a curator close a section by naming the
first leaf of the section *below* it. And AD never reads the `.tal`'s own `"L"` back —
`set_prefix` recomputes A, B, C… over the **shown** sections only, so a hidden section takes no
letter and does not consume one.

**What ae did.** The section set came from `clade_plan` alone (`cc/tal/draw-tree.cc`), and the
static block reached only `params.hz_sections` (`cc/tal/settings.cc`), where it drove the marker
column and the time-series separators and nothing else. `settings_v3` additionally dropped every
`show: false` entry and passed the `.tal`'s `"L"` through as the drawn letter. So the two
disagreed with each other, and with AD, on any tree whose `.tal` curates splits.

**Why only the Feb-2026 round exposes it — measured, not assumed.** Both rounds' `.tal`s *define*
an `hz` sub-program, but only the Feb ones **invoke** it in their `tal` program, and
`settings_v3` correctly fills `hz_sections` only from a command that actually runs. Entries
reaching the schema: **8 / 6 / 10** (2026-0223 bvic / h1 / h3) versus **0 / 0 / 0** (2026-0921).
Anyone testing only against the current round measures agreement and concludes there is nothing
to fix.

### Measured against AD, both sides re-derived in the same session

`AD/bin/tal -s <tal> --first-last-leaves 1 <tjz>` against
`tal-draw --settings=<schema> --clades-report <tjz>`, compared on `(id, first, last)` in order.

| tree | sections AD / ae | `V` agreement before → after | ids identical | `show` | letters |
|---|---:|---:|:-:|---:|---:|
| bvic | 14 / 14 | 12/14 → **14/14** | yes | 14/14 | 14/14 |
| h1   | 21 / 21 | 9/21 → **19/21** | yes | 21/21 | 21/21 |
| h3   | 15 / 15 | 7/15 → **15/15** | yes | 15/15 | 15/15 |

Before the fix ae reported **14 / 20 / 11** sections against AD's 14 / 21 / 15, missing
`D.3.1-1` on h1 and `H.2-1`, `H.2-2`, `H.2.2-0`, `J.2.4-1` on h3 — exactly the curated-only ids.

**h1's two residuals are AD's sentinel, not a gap.** `C.1.7-0` and `C.1.7.2-0` name the *same*
curated `last` leaf, and that leaf is present in the `.tjz` but hidden by a node mod. AD leaves
`node_id.vertical` at `node_id_t::NotSet` and prints `V [10101, 4294967295]` / `[11220,
4294967295]`; ae keeps the computed extent rather than propagating a sentinel into a coordinate.
Both sections are `show: false`, so neither is drawn either way. Same class as the accepted
divergence in §1 — do not reproduce it.

**No regression on the live round.** 2026-0921 stays at full parity: **10/10, 13/13, 11/11**,
ids identical, `show` and letters likewise. Note h3 is 11 because `tree/h3.asr.after-2021.tjz`
was re-claded at **09:47:55 on 15 Sep 2026** (J.2.4.2 added, K split); it read 9/9 against the
tree as it stood at 09:16. **`*.tjz` is gitignored, so `git status` is not a witness to a tree
rebuild — quote the tree's mtime beside any live-round number.** Both sides above were
re-derived against the 09:47 file.

### It changes the section set, and provably not what these trees draw

Pixel diff, previous round, `pdftoppm -png -scale-to 4000` then `magick compare -metric AE`
(the **parenthesised** number; the parser was validated against a copy with a known 100×100
block, which reports exactly 10000):

| tree | raster | differing px, strict | at `-fuzz 30%` |
|---|---|---:|---:|
| bvic | 2527×4000 (10.1 Mpx) | **0** | **0** |
| h1   | 3178×4000 (12.7 Mpx) | **0** | **0** |
| h3   | 2595×4000 (10.4 Mpx) | **0** | **0** |

That zero is a result, not an absence of one, and the mechanism is worth keeping:

* **These report `.tal`s contain no `hz-section-marker` element at all** (grep: 0 occurrences),
  so the bracket + letter column is never drawn on a *tree* PDF. The letter change is real but
  lands on **signature pages**, which are built through `signature_page.py` → `sections_for` →
  `compute_hz_sections`, a path this work deliberately leaves alone.
* The only drawn consumer here is the grey hz separators across the time-series matrix. Their
  `(first, last)` source set is **identical** before and after on h1 and h3; on bvic exactly one
  section's `last` steps back by one leaf, which over 38 084 leaves at 4000 px is ≈ **0.105 px**
  and rasterises to the same pixels.

### The signature-page list is NOT curated, and must not be merged

Two callers fill `params.hz_sections` and they mean different things by it. `settings_v3` passes
a curated list, every entry carrying an `id`. `py/ae/tal/signature_page.py` passes the sections
the page is actually built from, already lettered in tree order and with **no ids**; that list is
authoritative for the page and is drawn as given. The merge is therefore gated on entries
carrying ids, and `prefix` is still read for the caller that assigns it. The first cut of this
work read neither, and would have dropped the sig-page bracket letters and swapped the page's
section list for the computed clade bands — caught by `cc/tal/test/test-sigpage-hz-marker.py`
before it left the branch.

The curated `aa_transitions` override (AD `HzSection::label_aa_transitions`) is **deliberately
not read** — that is the curated-vs-computed field question Sarah deferred on 15 Sep 2026; see
the note at the end of §1.

### Regression test

`cc/tal/test/draw-settings-hz-curated.json` + four assertions in `cc/tal/test/test-draw-tree.sh`,
on synthetic data only (invented leaves A–E, clades X/Y). One assertion per separable behaviour,
each with its own failure message: a curated id that is not a computed section is **added**; a
curated `last` landing on a first-child leaf **steps back** one leaf; a curated hidden section is
still **reported**; and it consumes **no letter**. Verified by reverting the four source files to
the merge base and rebuilding: the case fails with *"curated hz-sections not merged -- expected 3
sections, got: >>> HZ sections (2)"*, and the reverted report independently shows all four
behaviours absent (2 sections, `Y-0` ending at D not C, `X-0` printing `"show": true` and
consuming letter A).

## aa-transition label-position dump (`>>> AA transition labels` / `.taleg`) — ported 2026-09-14

Port of AD `DrawAATransitions::report` (acmacs-tal `cc/draw-aa-transitions.cc:756`), the third
and last of AD's three tree diagnostics — the other two are the clade-section report above. AD
printed it on **every** tree draw; ae's `tal-draw` did not, and `./0do <subtype>_small` had
therefore stopped emitting the label positions the manual label-moving loop reads.

Every row is a pasteable `draw-aa-transitions` `per-node` entry: render, read the offsets the
placer chose, hand-edit the ones that want moving, paste the block back.

* **On by default** (`TreeDrawParameters::mrca_labels_report`), as AD was. A `.tal` opts out with
  `"label-report": false` on its `draw-aa-transitions` command.
  **Not** that command's `"report"` key — in AD that switches on the aa-transition *computation*
  debug trace (`Settings::add_draw_aa_transitions` → `aa_transitions.report`), and this round's
  h1/h3/bvic `.tal`s all set it `false` for exactly that reason. Wiring the dump to it would have
  silenced the thing being restored.
* **Output**: stderr, and appended to `<output>.taleg` after the clade report — one diagnostic
  file per tree. The shared-surface path (signature pages) has no output path, so stderr only.
* **Printed before the labels are drawn**, as in AD.
* `show: false` per-node entries are **reported but never drawn**. They used to be dropped in
  translation (`py/ae/tal/settings_v3.py`), so a dump pasted back would have silently revived
  every label the curation had switched off.

### Field set — where it departs from AD, and why

| field | AD | ae |
|---|---|---|
| `node_id` | recomputed draw-time id | **echoed** from the `.tal`; ae has no such id and never reads it |
| `first`/`last` | `?`-disabled (informational) | **live** — ae resolves the node as MRCA(first,last), so they carry the identity |
| value of `first`/`last` | the node's current extent | same: recomputed each draw, so a pasted block refreshes an identity gone stale |
| `pinned` | not printed | **printed** — ae auto-places un-pinned labels and ignores their offsets |
| `name` | the node's computed transitions | the curated label text |
| `offset` | 3 dp | 6 dp, and `offset_h` when the label was authored that way |

### Verified against AD — all three subtypes, both sides re-derived in one session

AD `tal` and ae `tal-draw` on the identical `.tal` + `.tjz` (2026-0921-ssm, `*.after-2021`):

```
                   AD rows   ae rows            node identity matched   `name` differs
2026-0921  h3         50       51 (7 hidden)    47/50 AD, 47/51 ae      1
2026-0921  h1         71       63 (19 hidden)   62/71 AD, 62/63 ae      0
2026-0921  bvic       35       33 (0 hidden)    29/35 AD, 29/33 ae      2
2026-0223  h3         51       51 (7 hidden)    51/51 AD, 51/51 ae      0
```

**The Feb (2026-0223) row is the control, and it confirms the diagnosis of the Sep residual.**
Feb's tree is the tree its `.tal` was written against, so nothing has drifted: AD's *detected*
set and the `.tal`'s *curated* set are the same 51 nodes, and the two dumps agree on every row,
every `name` and every `show`. The Sep shortfall is therefore tree drift since that `.tal` was
last regenerated — labels AD now detects that nobody has curated yet — not a defect in the dump.

Feb also covers what Sep could not: **it pins nothing** (Sep h3 pins 44 of 51), so every label
goes through the auto-placer on both sides. Offsets then differ as expected (median 0.036, max
0.171) — ae replaced AD's placer (`4162073`, `bc28392`) and that is settled, not a bug.

Offsets, h3, partitioned by whether AD could match the `.tal` entry at all (AD matches `per-node`
by `first`/`last` when live, else by the now-stale `node_id`; only 11 of the 51 active entries
carry a live pair):

```
AD CAN match  (live "first"/"last"): n=11  median |delta| 0.0004  10/11 within 0.001
AD CANNOT     ("?first" disabled)  : n=35  median |delta| 0.0272   0/35 within 0.001
```

So where AD honours the `.tal` pin, ae reproduces the same offset to AD's printed precision. Where
AD cannot, it discards the pin and auto-places — **that** is the divergence, not a dump bug, and ae
honouring the pin is the better behaviour. Same cause for the 5 `show` disagreements on h3: AD lost
the `show: false` curation on entries whose `?first` it could not match.

**The residual row-set difference is structural and is NOT closed here.** AD enumerates the
transitions it *detects* in the tree (min-leaves threshold, `hide-aa`); ae enumerates the *curated*
`per-node` set. So AD reports nodes ae never labels (3 on h3, 6 on bvic) and vice versa. Giving ae
AD's detection would change what the tree *draws*, not just what it reports — a separate decision.

**No render change**: the h3 PDF is byte-identical before and after this work (3 662 411 bytes;
the only differing bytes are cairo's `/CreationDate`), and the placer still reports `n=44`.

### The round trip — dump, paste back, re-render

The point of the block is that it goes back into the `.tal`, so that is tested end to end, on both
rounds and in both pinning states. Every comparison below is **exact — 0.0, not a tolerance**.

| | what was spliced back | result |
|---|---|---|
| 2026-0921 h3 (44 of 51 pinned) | the 51 dumped rows as-is | 51/51 rows identical in identity, `node_id`, `show`, `pinned`, offset and `?box`; re-rendered PDF byte-identical bar `/CreationDate` |
| 2026-0223 h3 (nothing pinned) | same `.tal` rendered twice | 51/51 offsets identical — the placer is deterministic, so the block diffs cleanly against the previous render |
| 2026-0223 h3 | the dump pasted back with the 44 shown rows' `"pinned"` flipped to `true` | 51/51 offsets identical — *auto-place, then freeze exactly what you see* is the workflow, and it holds |

So the recomputed `first`/`last` resolve to the same nodes the authored pair did, and an offset
survives the trip unchanged whether it was pinned already or pinned from the dump.

### Signature pages print it too, as AD did

AD's sig-page command stacks the curated tree `.tal` (`sp/0do:61`), so `DrawAATransitions::report`
ran there as well. ae's sig-page path renders the tree through `export_tree_into` (shared surface,
no output file), and the dump follows: AD `tal` and `ae.tal.signature_page` on the identical Feb
stack (`../bvic-cdc/sp.mapi`, `bvic.sp.tal`, `bvic.after-2021.tal`, `sp.tal`, `bvic-cdc.sp.tal`,
`--chart ../bvic-cdc/styled.ace`) give **33 rows each, 33/33 matching on identity, `show` and even
`node_id`** — Feb's tree has not drifted, so the echoed id still equals AD's recomputed one.

One difference remains, and it is ae-wide rather than this block's: **AD splits the streams** —
content rows to stdout, `vvvv`/`^^^^` banners to stderr (`AD_INFO`) — while ae sends whole blocks
to stderr, the convention the clade report established when it was ported. Line counts for one
bvic-cdc page: AD 63 stdout + 492 stderr, ae 0 + 144 (AD's stderr is mostly its own `@@ file:line`
logging chatter). Matching AD's split here would make this block disagree with the two beside it in
the same `.taleg`, so it is left alone; changing it is a decision about all three blocks at once.

No `.taleg` is written on this path — there is no output PDF path to derive one from, and the
geometry is a sub-rect of someone else's page, the same reason `mrca_label_sidecar` is skipped here.

### The 7 hidden labels are not drawn — measured, not argued

On Feb h3, ae `main` translates 44 `mrca_labels` and this branch translates 51 (the 7 `show: false`
entries it no longer discards). The rendered PDFs are **byte-identical, 2 747 642 bytes, differing
only in cairo's `/CreationDate`**, and the placer reports `n=44` on both. The extra entries reach
the report and nothing else.

### The drag editor is untouched

`Anchor` gained fields and the dump reads them, so the `mrca_label_sidecar` the WYSIWYG editor
consumes was re-derived on both sides: `tal-draw --mrca-sidecar` on h3, ae `main` vs this branch,
including each side's own `settings_v3` translation (44 mrca + 3 nodetext rows). The two sidecars
are **identical except the `"pdf"` field**, which only names the differing output file. `Anchor`'s
`first`/`last` deliberately stay the authored `.tal` values for that reason — the editor matches its
entry by them; only the dump uses the recomputed `cur_first`/`cur_last`.

### `.taleg` emission paths, all exercised on the synthetic tree

clades + dump (both blocks, clades first); clades hidden and `clades.report: false` (the dump alone
creates the file); `report_file: "-"` (no file, stderr only); `report_file: PATH` (both blocks go
there, nothing at the default path); `mrca_labels_report: false` (dump gone, clade report intact);
`--clades-report` (early exit — clade report only, no PDF, no dump).

Tests: `cc/tal/test/test-draw-tree.sh` (synthetic `tree-clades.json`) asserts the block appears on
stderr and in the `.taleg` **after** the clade report, both rows' full shape, and that the
`show: false` label is reported but absent from the rendered PDF.


## 6. Conf / format docs to mine next
- `~/AC/eu/AD/sources/acmacs-tal/doc/tal-conf.org` — the settings DSL reference.
- `~/AC/eu/AD/sources/acmacs-tal/doc/tal-processing.org` — processing stages.
- `~/AC/eu/AD/sources/acmacs-tal/doc/phylogenetic-tree-v3.format.json` — JSON tree schema.
