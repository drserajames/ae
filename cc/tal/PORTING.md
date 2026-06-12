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
3. Ladderize is in `cc/tree/` (`number-of-leaves` done; `max-edge-length` is a stub —
   complete it when needed).
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

**Phase B — drawing (BLOCKED on #1 → ~M3):**
5. Agree a shared `ae::draw::Surface` interface with the map-draw agent; grow `CairoPdf`
   to implement it (lines/paths first, then Pango text).
6. Port `DrawTree`, then the column elements (time-series, clades, dash-bars, hz-sections),
   then `Title`/`Legend`/`DrawAATransitions`.
7. `AntigenicMaps` last — also gated on map-draw render + hidb (#2).

**Phase C — settings DSL & CLI:**
8. Port the `Settings`/`apply_built_in` mod pipeline (`settings.cc`) and `bin/tal`.

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
- **Deep newick trees (≳1000-node caterpillar) segfault inside `ae.tree.load()`** —
  a pre-existing recursion limit in `cc/tree/` (parser / cumulative / node_id), unrelated
  to TAL. `compute_layout` itself is iterative and safe. Worth fixing in `cc/tree/`.

## 6. Conf / format docs to mine next
- `~/AC/eu/AD/sources/acmacs-tal/doc/tal-conf.org` — the settings DSL reference.
- `~/AC/eu/AD/sources/acmacs-tal/doc/tal-processing.org` — processing stages.
- `~/AC/eu/AD/sources/acmacs-tal/doc/phylogenetic-tree-v3.format.json` — JSON tree schema.
