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
  "clade_color":   { "<clade>": "#rrggbb" },   // [live] clade -> colour
  "clade_legend":  { "<clade>": "<label>" },   // [E1]  clade -> legend text (canonical)
  "unmatched_color": "#d9d9d9",  // [live] colour for tips/antigens with no clade
  "passage_color": {             // [E1]  passage-type -> colour (P1 markers)
    "egg": "#FF0000", "cell": "#0000FF", "reassortant": "#FFA500"
  },
  "aa": { "<norm>": { "<pos>": "<aa>" } }      // [E2]  shared norm -> AA table (C1)
}
```

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

  // E2 additions (for stress/error overlays N1/N2/C2):
  "titers":      [[ "<encoded>", ... ]], // [E2] antigens x sera, raw titer strings
  "logged":      [[ <float|null>, ... ]],// [E2] log2 titers (null = missing/"*")
  "column_bases":[ <float>, ... ],       // [E2] one per serum
  "min_col_basis": "none"                // [E2] minimum column basis used
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
  "passage": "MDCK1",         // raw passage string ([E1] classified type in "pt" + tree.passage)
  "pt": "cell",               // [E1] classified passage type: "egg"|"cell"|"reassortant"|null (P1 markers)
  "date": "2022-02-01",
  "x": 1.234, "y": -0.567,    // map coords (null if not positioned); transform-applied [E1]
  "clade": "3C.2a1b.2a",      // [E1] primary clade = most-specific canonical (semantic_clades) label present, or null
  "clades": ["3C.2a1b.2a"],   // all clade labels
  "ref": false,               // reference antigen
  "vac": false                // vaccine strain
}
```

### Serum [live]

```jsonc
{ "i": 3, "name": "...", "x": 0.1, "y": 0.2 }   // x/y null if not positioned
```

---

## Viewer-side access (F1)

The bundle is reachable to every module as `IV.DATA`. The two cross-cutting
contracts that feature modules build on (rather than re-deriving) are:

- **`IV.State`** — selection store + view state (`active`, `selected`,
  `offClades`, `onlyMatched`, `chartIdx`, `colorBy`) with `subscribe(fn)` /
  `notify()`. Panels subscribe and re-apply highlight on change.
- **`IV.Colour`** — colour API: `Colour.leaf(node)`, `Colour.antigen(ag)`,
  `Colour.cladeColor(c)`, `Colour.clades()`, `Colour.unmatched()`, honouring the
  active `State.colorBy`.

See `PLAN.md` for task ownership and `README.md` for module roles.
