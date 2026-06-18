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
  "clade_color":   { "<clade>": "#rrggbb" },   // [v3] clade -> colour, from the report style R["-clades-v10"]
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
> plot-spec (`R["-clades-v10"]` and `R["-continent"]`, readable with
> `decat <styled.ace>`), so the viewer matches the report PDFs exactly. A chart with
> no `-clades-v10` style falls back to the `semantic_clades` palette (then a generated
> one). Each antigen's `clade` is the rule applied **last** among its clade labels (the
> report layers rules, so the most specific clade wins); clades with no rule are greyed
> and logged.
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
tree tips to chart antigens. It is the join key throughout the bundle.

---

## `meta` [live]

```jsonc
{
  "subtype": "A(H3N2)",
  "assay": "HI",
  "tree_file": "h3.asr.tjz",
  "n_tree_leaves": 70000,   // leaves in the full source tree
  "n_kept_leaves": 2100,    // leaves kept after pruning to linked tips
  "n_matched_norms": 2100   // distinct norms matched between charts and tree
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
  "label": "vidrl",          // [live] centre label (Centre dropdown)
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
  "serology": false           // [v3] report serology test antigen (semantic T.serology)
}
```

### Serum [live]

```jsonc
{
  "i": 3, "name": "...", "x": 0.1, "y": 0.2,   // x/y null if not positioned
  "norm": "THAILAND/8/2022",   // [v3] join key, normalised like antigens (F1)
  "homologous": 0              // [v3] index of the antigen sharing this norm, or null (F1)
}
```

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
  **F8 clade legend cycle (z-order tri-state):** the legend clade click calls
  `State.cycleClade(clade)` (returns the new mode, cycling
  `normal → select → back → normal`); read state via `State.cladeMode(clade)` and
  `State.cladeZRank(clade)` (`1` front / `−1` back / `0` normal), reset all with
  `State.resetCladeCycle()`. `emphasis()` already folds the modes in (a *front*
  clade pops while others fade like a selection; a *back* clade dims), so the
  visual comes for free; panels MAY additionally reorder points by `z` to draw
  *back* clades behind and *front* clades on top.
- **`IV.Colour`** — colour API: `Colour.leaf(node)`, `Colour.antigen(ag)`,
  `Colour.cladeColor(c)`, `Colour.cladeLegend(c)`, `Colour.clades()`,
  `Colour.unmatched()`, honouring the active `State.colorBy`. Continent key:
  `Colour.continentColor(c)`, `Colour.continents()`. **Passage marker API (shared
  with P1):** `Colour.passageColor(type)` / `Colour.passageLabel(type)` /
  `Colour.passages()` (egg/cell/reassortant), and `Colour.hasPassageMarkers()`
  — true only once the bundle carries `passage_color` (E1). P1 should colour
  tip/point passage markers via these rather than re-deriving the palette.

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
