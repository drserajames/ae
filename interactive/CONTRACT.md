# F0 — Interactive viewer JSON bundle contract

This is the **single source of truth** for the data structure that
`export_interactive.py` produces and that the viewer modules (`js/*.js`) consume.
Both sides MUST agree on this shape. Change it here first, then update both sides.

The exporter serialises one object (the *bundle*) and substitutes it into the
template at the `/*__DATA__*/` placeholder; the viewer reads it as `IV.__DATA__`
(exposed to modules as `IV.DATA`).

Legend for field status:

- **[live]** — produced/consumed today (baseline `726d44c` + F1).
- **[E1] / [E2]** — reserved by the contract; the exporter task (E1 Stage-1, E2
  Stage-2) fills it. Viewer modules MAY read it defensively (treat missing as
  "feature off") before E1/E2 land.

---

## Top-level bundle

```jsonc
{
  "meta":  { ... },              // [live] document-level metadata
  "tree":  { ...node... },       // [live] pruned tree, nested; root node
  "charts": [ { ...chart... } ], // [live] one entry per --chart (centre)
  "clade_color":   { "<clade>": "#rrggbb" },   // [v3] clade -> colour, from the chart's report clade style (per subtype, see below)
  "clade_legend":  { "<clade>": "<label>" },   // [v3] clade -> legend text, from the same rule's L.t
  "clade_priority":{ "<clade>": <int|null> },  // [v3] rule legend priority (L.p) for ordering the legend like the report
  "clade_short":   { "<clade>": "<pango>|null" }, // [v4] Pango short name parsed from the legend (null if it's an AA motif)
  "continent_color": { "<CONTINENT>": "#rrggbb" }, // [v3] from R["-continent"]; key is uppercase T.C9
  "unmatched_color": "#d9d9d9",  // [live] colour for tips/antigens with no clade rule
  "passage_color": {             // [E1]  passage-type -> colour (P1 markers)
    "egg": "#FF0000", "cell": "#0000FF", "reassortant": "#FFA500"
  },
  "aa": { "<norm>": "QKIPGND..." }             // [E2]  shared norm -> aligned full-HA AA sequence (C1)
}
```

> **Clade / continent colours [v3]** come straight from each chart's own report
> plot-spec (the clade style + `R["-continent"]`, readable with `decat <styled.ace>`),
> so the viewer matches the report PDFs exactly. The clade style key is chosen **per
> subtype** (first present wins): `-clades-v10` (H3) → `-clades` (H1) → `-clades-v2`
> (B/Vic — the current Pango "C" clades; `-clades-v1` is the older scheme, selectable
> via `--clade-style`) → `-clades-v1`. `--clade-style <key>` (with or without the leading
> `-`) forces one; pass it without the dash (`--clade-style clades-v1`) so argparse
> doesn't treat the value as a flag. A chart with no clade style falls back to the
> `semantic_clades` palette (then a generated one). Each antigen's `clade` is the rule
> applied **last** among its clade labels (the report layers rules, so the most specific
> clade wins); clades with no rule are greyed and logged.
>
> **`clade_short` [v4]** maps each clade to its Pango short name or `null`: the
> parenthesised Pango in the legend (`"135K 189R (J.2.4)"` → `J.2.4`), or the legend
> itself when it carries no AA-motif digits (`"K"` → `K`), else `null` for a bare AA
> motif (`"135K"`). Lets the viewer label by the short clade name when one exists.

The `aa` table maps each matched `norm` to its **aligned full-HA AA sequence
string** (reconstructed from the `.asr` tree; HA1 is the prefix, so HA1 numbering
still applies). Residue at 1-based position `p` is `aa[norm][p-1]` — same numbering
as clade names and tree-node `A` transitions. A string (not a `{pos: aa}` dict)
keeps the table ~4× smaller and lets C1 read any position the user asks for.

`norm` is the normalised strain key `LOCATION/ID/YEAR` (uppercase) used to link
tree tips to chart antigens. It is the join key throughout the bundle. The leading
subtype prefix is stripped from chart names — `A(...)/`, `B(...)/`, or a bare `A/`/`B/`
(so `B/HONG KONG/269/2017` → `HONG KONG/269/2017`), while a name with no such prefix
(`BHUTAN/212/2019`) is left untouched — so B/Vic names match the bare tree tips.

---

## `meta` [live]

```jsonc
{
  "subtype": "A(H3N2)",
  "assay": "HI",
  "tree_file": "h3.asr.tjz",
  "n_tree_leaves": 70000,   // leaves in the full source tree
  "n_kept_leaves": 2100,    // leaves kept after pruning to linked tips
  "n_matched_norms": 2100,  // distinct norms matched between charts and tree
  "generated": "2026-06-19" // [v6 F1] page-generation date (ISO, local date)
}
```

---

## Tree node (`tree` is the root node) 

Nested via `children` (empty array at leaves). Degree-2 internal nodes are
collapsed during pruning. `x` is **cumulative branch length** from the root
(genetic distance) — the viewer scales it to the pane width.

```jsonc
{
  "id": 12345,            // [live] node id (may be null on collapsed internals)
  "x": 0.0423,            // [live] cumulative edge length from root
  "children": [ ... ],    // [live] child nodes; [] at a leaf

  // leaf-only fields:
  "name": "TOGO/764/2022_OR_4D211EF9",  // [live] full tip name (with passage+hash)
  "norm": "TOGO/764/2022",              // [live] normalised join key
  "date": "2022-03-14",                 // [live] collection date ("" if unknown)
  "continent": "AFRICA",                // [live] uppercase continent
  "country": "TOGO",                    // [live] country
  "clade": "3C.2a1b.2a",                // [live] clade label (canonical after E1) or null
  "ag": [3, 17],                        // [live] antigen indices (chart 0) for this norm

  // E1 additions (leaf or internal):
  "passage": "egg",       // [E1]  passage type of the matched antigen (P1)
  "A": [                  // [E1]  AA substitutions on the edge into this node (T4)
    { "pos": 145, "from": "N", "to": "S" }   // pos = 1-based HA1 position (matches clade names); omitted if none
  ]
}
```

> `A` is derived by diffing the reconstructed ancestral AA sequences the `.asr` tree
> carries on every node (collapsed degree-2 chains roll their substitutions up onto the
> surviving descendant). Positions line up with clade nomenclature (e.g. a `135 T→K`
> edge feeds the `135K` clade). The C++ consensus path is not used (broken in the
> current build).

> Note: today the tree carries chart-0 antigen indices in `ag`. Linkage is by
> `norm`, so the viewer resolves antigens per active chart via that chart's
> `norm_to_ag` (below), not via `ag` alone.

---

## Chart entry (one per centre)

```jsonc
{
  "label": "VIDRL",          // [v6 #1] centre label, uppercased (Centre dropdown; display-only)
  "name": "A(H3N2) HI ...",  // [live] chart descriptive name
  "n_antigens": 2900,        // [live]
  "n_sera": 40,              // [live]

  "antigens": [ { ...antigen... } ],  // [live]
  "sera":     [ { ...serum... } ],    // [live]
  "norm_to_ag": { "<norm>": [i, ...] }, // [live] norm -> antigen indices in THIS chart
  "stress": 6190.07,         // [v3] this projection's optimiser stress (F6)

  // E2 additions (for stress/error overlays N1/N2/C2):
  "titers":      [[ "<encoded>", ... ]], // [E2] na x ns, raw titer strings ("*"/"<N"/">N"/num)
  "logged":      [[ <float|null>, ... ]],// [E2] na x ns, log2(titer/10); null = missing ("*")
  "column_bases":[ <float>, ... ],       // [E2] one per serum; the bases the projection was optimised with (forced if present, else computed at min_col_basis) — these match the coords
  "min_col_basis": "none"                // [E2] minimum column basis used (e.g. "none" or "1280")
}
```

**Coordinates are transform-applied** (the chart `transformation()` is baked into
`x`/`y` so the viewer plots oriented coords directly — E1 makes this so; baseline
plots raw layout coords).

### Antigen [live]

```jsonc
{
  "i": 17,                    // index within this chart's antigen list
  "name": "A(H3N2)/THAILAND/8/2022",
  "norm": "THAILAND/8/2022",  // join key
  "passage": "MDCK1",         // raw passage string (classified type in "pt" + tree.passage)
  "pt": "cell",               // [v3] passage type from semantic T.p: "egg"|"cell"|"reassortant"|null (P1)
  "date": "2022-02-01",
  "x": 1.234, "y": -0.567,    // map coords (null if not positioned); transform-applied [E1]
  "clade": "3C.2a1b.2a",      // [v3] primary clade = last-matching report rule among "clades", or null
  "clades": ["3C.2a1b.2a"],   // all clade labels (semantic T.C)
  "continent": "ASIA",        // [v3] uppercase continent, from semantic T.C9 (null if absent)
  "country": "THAILAND",      // [v3] country, from semantic T.c9 (null if absent)
  "ref": false,               // [v3] reference antigen (select_reference_antigens or semantic T.R)
  "vac": false,               // [v3] vaccine strain (semantic T.V truthy)
  "serology": false,          // [v3] report serology test antigen (semantic T.serology)
  "new": 0                    // [v6 F2] 1=new since previous report, 2=new since previous VCM, 0=neither
}
```

> **`new` [v6 F2]** is not stored in `styled.ace`, so the exporter computes it by
> comparing the chart to two earlier ones via `chart.select_new_antigens(prev)`: the
> **previous report** (`<SSM>/previous/<sub>/styled.ace`, the immediately preceding run)
> gives `1`, and the **previous VCM** (the most recent sibling `<YYYY-MMDD>-ssm` before
> this run) gives `2`. Report takes precedence (tighter subset), so `1` overrides `2`.
> A missing comparison chart is logged and leaves that tier at `0`.

### Serum [live]

```jsonc
{
  "i": 3, "name": "...", "x": 0.1, "y": 0.2,   // x/y null if not positioned
  "norm": "THAILAND/8/2022",   // [v3] join key, normalised like antigens (F1)
  "homologous": [0, 1, 304],   // [v9 #4] ALL antigen indices sharing this norm (egg+cell of the strain); [] if none
  "homologous0": 0,            // [v9 #4] scalar back-compat alias = first homologous index, or null
  "passage": "SIAT1",          // [v6 #6] raw serum passage string (str(serum.passage()))
  "serum_id": "A9824",         // [v6 #6] serum.serum_id()
  "serum_species": "",         // [v6 #6] serum.serum_species() ("" if unset)
  "circle": {                  // [v6 F3] serum-circle radii, proj.serum_circles(fold=2.0)
    "cb": 7.0,                 //   column basis (null if undefined)
    "theoretical": 3.0,        //   theoretical radius, log2 units (Optional float, may be null)
    "empirical": 3.35          //   empirical radius, log2 units (Optional float, may be null)
  }
}
```

> **`homologous` [v9 #4]** is now a **list** — a serum can have several homologous
> antigens (e.g. the egg and cell passages of its strain; 14/26 H3-vidrl sera do).
> Serum-circle / coverage consumers should fold over all of them (min radius, or
> per-antigen), not just the first. `homologous0` keeps the old scalar (first index,
> or null) for anything not yet migrated.

---

## Viewer-side access (F1)

The bundle is reachable to every module as `IV.DATA`. The two cross-cutting
contracts that feature modules build on (rather than re-deriving) are:

- **`IV.State`** — selection store + view state (`active`, `selected`,
  `offClades`, `onlyMatched`, `chartIdx`, `colorBy`) with `subscribe(fn)` /
  `notify()`. Panels subscribe and re-apply highlight on change. Selection API
  (S1): `setSelection(norms)`, `select(norms,{additive})`, `toggleSelect(norm)`,
  `deselect(norms)`, `clearSelection()`, `isSelected(norm)`, `hasSelection()`.
  Panels classify each point through
  `State.emphasis(norm, clade, extraHidden?) → {dim, lift, sel, z}` and toggle the
  dim/lift/sel classes (and may reorder by `z`) — do not re-derive the rules.
  `IV.installSelect(svg)` adds click + drag-box selection to any panel SVG whose
  points carry a `data-norm` attribute (idempotent; call once per render).
  **F1 serum select:** sera carry `data-norm = serum.norm` (Agent-MAP hook);
  `State.expandNorms(norms)` adds each serum's homologous-antigen norm so a serum
  click lights the serum + its homologous antigen + the matching tree tip
  (installSelect already routes clicks/box through `expandNorms`).
  **double-click isolate (v6/v7/v8) — point identity:** a point dblclick isolates
  ONE exact point by **identity, not norm** — `State.isolated = {kind:'serum'|
  'antigen', i}` (`i` = index in the active chart), with `setIsolated(kind,i)` /
  `clearIsolated()` / `isIsolated()` / `isolatedSerum()` (the active chart's serum
  object when `kind==='serum'`). So a serum isolates **without** lighting its
  same-name antigen. Map/grid glyphs carry `data-kind`+`data-i` (the handler reads
  them); a tree tip (norm-only) resolves to its matching antigen. Panels use
  `State.pointEmphasis(kind,i,norm,clade) → {dim,lift,sel,z}` (map/grid) — only the
  exact (kind,i) is `sel`, everything else dims (titrated antigens stay in coverage
  mode); `emphasis(norm,clade)` carries the same logic norm-side for the tree.
  Single click / box-select / empty-click / **Esc** clear isolation; isolation also
  clears on chart change. **#5 (v9): double-click is detected manually** (two clicks
  on the same point within 300 ms) because the native `dblclick` event on SVG is
  unreliable in Safari — the second click isolates and also `resetCycle()`s the
  legend cycle (**F2 v9**). A residual capture-phase `dblclick` listener only
  `stopImmediatePropagation`s on a point (to suppress the panel zoom-reset where the
  native event *does* fire, even on the same SVG node); empty-space dblclick still
  resets the view.
  **new-since toggles (v6/v7 #3, v9 #2):** `State.showNewReport` / `State.showNewVCM`
  booleans with `setShowNewReport/setShowNewVCM(on)` (both notify); **mutually
  exclusive** (v9 #2 — setting one clears the other). Agent-LINES wires the Overlays
  checkboxes. These are **emphasis keep-layers, not bold outlines**: `emphasis()`
  keeps antigens/tips whose semantic `new` matches (`showNewReport`→`new==1`,
  `showNewVCM`→`new>=1`) and dims the rest, via the panels' existing refresh.
  **serum-scoped colour modes — coverage (v7 #4 / v8) + titre (v10):** the two
  serum-scoped colorBy modes, `"coverage"` and `"titre"`, are driven by the
  **isolated** serum (`isolatedSerum()`). When either is active, point opacity
  follows **titration to that serum, overriding the isolation dimming**: an antigen
  is foreground iff it has a titre to the serum, untitrated ones dim, and the serum
  stays selected. The titration check is **per-antigen on the map**
  (`logged[antigen.i][serum.i] != null`, so a cell antigen isn't kept by an egg
  sibling's titre) and norm-level on the tree (no per-antigen index there). Coverage
  also exposes the single-source-of-truth `State.coverageActive()` /
  `State.coverageSerum() → {i,norm}|null` / `State.coverageTitrated(norm)` (these stay
  **coverage-only**, for the pink ≤4-fold / black >4-fold outline consumers); `titre`
  reuses the same titration but its fill comes from `Colour` (F1, independent of dim).
  **v12 refinements (don't regress):** in `titre` mode the OTHER sera are kept
  full-opacity and painted **black** (`map.js serumColour`) so the user can switch the
  titre serum — only the rest of the points follow titration dimming; the titre
  gradient/legend range is **GLOBAL over the whole chart** (`Colour.ensureTitreRange()`),
  identical for every serum (NOT per-serum), so titres are comparable across sera; and the
  new-since toggle narrows the titrated foreground to **titrated AND new** under both
  serum-scoped modes (the isolated branch now consults `_newActive()`/`_newMatch()`).
  **F2 legend cycle (per-attribute z-order tri-state):** generalises the v3 clade
  cycle to whichever attribute colorBy selects — `clade`, `continent`, or `aa`
  value. The legend (Agent-COLOUR) calls `State.cycleActive(value)` on the active
  attribute's entries (returns the new mode, cycling
  `normal → select → back → normal`); read state via `State.activeMode(value)` /
  `State.activeZRank(value)` (`1` front / `−1` back / `0` normal) and clear all
  with `State.resetCycle()`. Pass the value as the legend shows it: clade label,
  **uppercase** continent (e.g. `ASIA`), or `Colour.aaValues()` residue string.
  Generic forms exist (`cycleAttr/attrMode/attrZRank(attr, value)`) and the v3
  clade names remain as aliases (`cycleClade`/`cladeMode`/`cladeZRank`/
  `resetCladeCycle`). `emphasis()` resolves each point's value for the active
  attribute and folds the mode in (a *front* group pops while the rest fade like a
  selection; a *back* group dims), so every panel reflects it via its existing
  refresh; panels MAY additionally reorder points by `z` to draw *back* behind and
  *front* on top. Cycle state is keyed per `(attr, value)`, so it persists across
  colorBy switches and each mode only ever sees its own groups.
  **F3 marker cycle (v9 / v10 #4):** a second cyclable dimension, **always active**
  (independent of colorBy), for the marker-key categories `State.MARKERS =
  ["reference","vaccine","serum","egg","cell","reassortant"]`. Agent-COLOUR's legend
  marker swatches call `State.cycleMarker(cat)` and read `State.markerMode(cat)` /
  `State.markerZRank(cat)` (it's `cycleAttr("marker", cat)` under the hood).
  `emphasis()`/`pointEmphasis()` fold marker modes in exactly like the clade cycle —
  a *front* category pops, others fade; a point may match several categories (an egg
  reference antigen). Passage categories are matched **strictly on the authoritative
  `pt`** (#4 v10 — egg = only `pt==='egg'`, cell = only `pt==='cell'`, etc.; no
  passage-string/regex fallback), and **per-antigen on the map** (via the exact
  antigen index in `pointEmphasis`), so a cell antigen never inherits an egg same-name
  sibling's category; the tree uses each tip's own `passage`. `"serum"` matches only
  serum glyphs (resolved by `kind`), so fronting it dims every antigen and all tips.
- **`IV.Colour`** — colour API: `Colour.leaf(node)`, `Colour.antigen(ag)`,
  `Colour.cladeColor(c)`, `Colour.cladeLegend(c)`, `Colour.clades()`,
  `Colour.unmatched()`, honouring the active `State.colorBy`. Continent key:
  `Colour.continentColor(c)`, `Colour.continents()`. **Passage marker API (shared
  with P1):** `Colour.passageColor(type)` / `Colour.passageLabel(type)` /
  `Colour.passages()` (egg/cell/reassortant), and `Colour.hasPassageMarkers()`
  — true only once the bundle carries `passage_color` (E1). P1 should colour
  tip/point passage markers via these rather than re-deriving the palette.
  **colorBy modes** add `clade` / `continent` / `aa` / `stress` / `time` / `coverage`.
  `time` (v6 F1): viridis over [oldest antigen date … `meta.generated`]; gated on
  `Colour.hasTime()`, window via `Colour.timeWindow()`, ramp `Colour.timeStops(n)`.
  `coverage` (v6 F3): active when a serum is selected (`Colour.coverageSerum()`);
  `Colour.antigen(a)` returns the clade colour, paled (HSV) when the selected serum
  did not titrate that antigen. **Map should call `Colour.coverageOutline(a)` →
  `{stroke,width}|null`** to draw the titrated outline (pink ≥ homologous−2 log2,
  else black, 3px); gated on `Colour.hasCoverage()`.

Two more APIs feature modules build on rather than re-deriving:

- **`IV.Map` projection (overlay contract, consumed by N1/N2 lines)** —
  `Map.project(x, y) → [px, py]` (null before first render / nothing plotted) and
  `Map.scale` (antigenic-units → px). `Map.onView(fn)` registers a reflow callback
  that fires after every zoom/pan (M1 reprojects points without a `State.notify`),
  returning an unsubscribe fn. Overlays draw into a `pointer-events:none` group so
  they never intercept hover / drag-select. `Map.paintChart(svg, chart, proj, opts)`
  draws one chart's points and is reused by the all-centres grid (G1).
- **`IV.Lines`** — error/connection overlays (N1/N2). `Lines.render()` /
  `Lines.refresh()` (re)draw, scoped to the current selection (or hovered strain).
  The per-titer error math is exposed as `Lines._errorFromDist(tableDist, mapDist,
  rawTiter) → signed error` (>0 too close/red, <0 too far/blue; `<`/`>` use the
  acmacs sigmoid) so **C2 per-point stress can reuse it** (`Σ error²` over a point's
  titers) instead of re-deriving the formula.

See `PLAN.md` for task ownership and `README.md` for module roles.
