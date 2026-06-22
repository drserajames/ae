# TODO: Interactive tree + antigenic-map viewer — v2 (fixes + features)

## Context

The committed viewer (`ae-interactive/interactive/`, `726d44c`) links a phylo tree to
antigenic map(s) by strain. User review raised **6 issues + 9 features**. Research
(2 Explore agents + `ae_backend` probes) confirmed all are feasible from `ae_backend`
data and pinned the algorithms/colour sources. Decisions: **phased, 2 stages**;
all-centres = **grid of small multiples**. Dataset stays **H3N2 HI, `2026-0223-ssm`**.
Env: arm64 / Py-3.10 via `run.sh`. Outputs → the report folder, never the repo.

## Parallelization model (how to split across agents)

The viewer is one self-contained `.html` today → parallel edits conflict. **Task F1
modularizes it** into ES modules that the exporter inlines at export time, with a fixed
**JSON bundle contract (F0)**. Once F0+F1 land, the exporter and each viewer module are
**separate files** → ownable by different agents in parallel.

- **Serial foundation (must land first):** F0 (data contract) → F1 (module scaffold).
- **Then fan out:** exporter (one agent) + viewer modules (one agent each), all coding
  against the F0 contract. Cross-cutting modules (selection, colour) own a shared API
  defined in F1 so feature modules call it rather than edit each other.

Coupling points to respect (state once, in F1): the **selection store** (which strains
are selected) and the **colour API** (`colourFor(point)` given the active mode). Tree,
map, lines, and grid all read these; they must not be duplicated.

---

## F — Foundation (serial, do first; me or one lead agent)

- **F0 — JSON bundle contract.** Write the schema both sides build against: shared
  `norm→{aa, passage}` table; `tree` (nested kept nodes: id, x, name, norm, date,
  continent, country, clade, ag[], `A` transitions); per-chart `{label, name,
  transform-applied coords, antigens[], sera[], titers(logged), colbases, min_cb}`;
  `clade→{color,legend}`; passage colours. ~½ day. **Blocks everything.**
- **F1 — Viewer module scaffold + inline-bundler.** Split `viewer_template.html` into
  `js/` modules (`state.js` selection store + `colour.js` colour API as the shared
  contract; `tree.js`, `map.js`, `lines.js`, `grid.js`, `ui.js`, `main.js`); add a
  build step in `export_interactive.py` that concatenates/inlines them into the
  template (keeps single-file output, no deps). ~½–1 day. **Blocks all viewer tasks.**

---

## Stage 1 — 6 fixes + core interactions

| ID | Task (issue/feature) | Module / file | Depends | Agent? |
|----|----------------------|---------------|---------|--------|
| **E1** | Exporter Stage-1 data: apply `transformation()` to coords (#5); canonical colours+legend via `semantic_clades` re-derived clades (#1,#2); passage per antigen+tip (#4); export node `A` AA-transitions (#6) | `export_interactive.py` | F0 | **Yes — own agent** (separate file, well-specified) |
| **T1** | Fix tree edge rendering — parent→child elbows, no gaps (#3) | `tree.js` | F1 | Yes |
| **T2** | Default zoom fits whole tree to pane (#6) | `tree.js` | F1,T1 | Yes (same owner as T1) |
| **T3** | Independent zoom/pan for tree (#feat3) | `tree.js` | F1 | Yes (same owner) |
| **T4** | Click branch → show AA changes from `A` (#feat6) | `tree.js`+`ui.js` | F1,E1 | Yes (same owner) |
| **M1** | Map render with orientation applied; zoom/pan independent (#feat3,#5) | `map.js` | F1,E1 | **Yes — own agent** |
| **P1** | Passage marking on tips + map points + legend key (#4) | `tree.js`,`map.js`,`ui.js` | F1,E1 | Shared — coordinate via `colour.js`/markers |
| **S1** | Bidirectional selection + drag-box on either panel (#feat1) | `state.js`,`tree.js`,`map.js` | F1 | **Yes — own agent** (owns selection store) |
| **S2** | Search by name → multi-match select (#feat5) | `ui.js`,`state.js` | F1,S1 | Same owner as S1 |
| **L1** | Persistent legend (clade swatches+counts, marker key) (#2) | `ui.js`,`colour.js` | F1,E1 | Yes |

**Stage-1 checkpoint:** regenerate + screenshot + open; user review before Stage 2.

## Stage 2 — overlays, AA/stress colouring, all-centres grid

| ID | Task (feature) | Module / file | Depends | Agent? |
|----|----------------|---------------|---------|--------|
| **E2** | Exporter Stage-2 data: shared `norm→aa` table; per-chart titers (`logged_array`), `column_bases`, `min_col_basis` | `export_interactive.py` | F0,E1 | **Yes — own agent** |
| **C1** | Colour-by-amino-acid / combination at given positions (#feat2) | `colour.js` | F1,E2 | **Yes — own agent** (colour engine) |
| **C2** | Colour-by-stress (per-point stress in JS) (#feat7) | `colour.js`,`lines.js` | F1,E2 | Same owner as C1 |
| **N1** | Error lines (red>0/blue<0, sigmoid for `<`) (#feat9) | `lines.js` | F1,E2,M1 | **Yes — own agent** (overlay) |
| **N2** | Connection lines (titer≠`*`, within selection) (#feat8) | `lines.js` | F1,E2,M1 | Same owner as N1 |
| **G1** | All-centres grid of small multiples; links across all maps (#feat4) | `grid.js`,`map.js` | F1,M1,S1 | **Yes — own agent** |

---

## Colour matching (shared spec for E1 / C1 / L1)

Report palette = `acmacs-data/semantic_clades.py`
(`semantic_plot_spec_data_for_subtype("A(H3N2)")` → `{name,legend,color}`). 2026-chart
stored clade labels (`122D`,`223V 145N`) **don't** all match v10 names, so re-derive
clades the way `chart_modifier` does: import `semantic_clades`; `populate_from_seqdb()`
if needed; apply `semantic_clades.semantic_attribute_data_for_subtype(subtype)["clades"]`
via `ae.semantic.clade.attributes(chart, …)` (in `ae/py/ae/semantic/clade.py`); read the
assigned clade name; map `name→color`. Tree tips inherit their matched antigen's clade
(one colour space). Unmatched → grey, **logged**. Passage colours from
`chart_modifier.py:386` (egg `#FF0000`, cell `#0000FF`, reassortant `#FFA500`).

## Error / stress formulas (shared spec for N1 / C2)

`table_dist = colbase[serum] − logtiter` (clamp ≥0); `map_dist` = euclidean on oriented
coords. Regular `error = table_dist − map_dist`; less-than `(Δ+1)·√sigmoid((Δ+1)·10)`,
`Δ=table_dist−map_dist`. Per-point stress = Σ of `error²` over that point's titers.

## Files
- `ae-interactive/interactive/export_interactive.py` (E1,E2,F1 bundler)
- `ae-interactive/interactive/js/*.js` (new, F1) — inlined into output
- `ae-interactive/interactive/viewer_template.html` (becomes thin shell after F1)
- `ae-interactive/interactive/README.md` (document modules + options)
- Reuse: `ae/py/ae/semantic/clade.py`, `acmacs-data/semantic_clades.py`.

## Verification (per stage)
Regenerate via `run.sh` (single + all-centres) into the report folder; headless-Chrome
screenshot. Confirm: edges connect; whole tree fits by default; colours match
`semantic_clades` hex (spot-check 3–4 clades); orientation matches a report map PDF;
passage markers present; drag-box selects matching tips; branch click shows AA subs;
error lines red/blue sane; colour-by-145 splits clades; per-point stress flags outliers;
all 6 centre panels render and link. Log unmatched clades/strains. File opens from
`file://`. **No WHO data committed (policy check before any commit; push → drserajames).**

## Suggested agent assignment (max parallelism)
After F0+F1 (serial, lead): **Agent-EXP** = E1→E2; **Agent-TREE** = T1–T4+P1(tree side);
**Agent-MAP** = M1→G1+P1(map side); **Agent-SELECT** = S1,S2; **Agent-COLOUR** = L1→C1,C2;
**Agent-LINES** = N1,N2. Lead integrates + runs verification each stage. Worktree
isolation per agent if they touch `export_interactive.py` concurrently (E1/E2 vs F1
bundler) — otherwise file-per-module avoids conflicts.

---

# v3 — second feedback wave (7 fixes + 8 features)

Status: v1/v2 (E1, T1–T4, M1/P1/G1, S1/S2, L1, E2, N1/N2, C1/C2) all landed and
reviewed on `ae-interactive`. This wave is from a round of user testing.

## Key finding — match the report by reading the chart's own `R` plot-specs

The report's colours/styles are **baked into `styled.ace` under the `R` dict**, and the
antigen semantic `T` carries more than E1 currently exports. Use these as the source of
truth instead of re-deriving:
- `R["-clades-v10"]["A"]` — list of `{T:{C:"<clade>"}, F:"#fill", O:"outline",
  L:{p:priority, t:"legend"}}`. **This is the report's clade colour+legend+priority map.**
- `R["-continent"]` — continent palette; `R["-vaccines-v10"]` — vaccine styling;
  `R["serology"]` — serology styling.
- Antigen `T`: `C9`=continent, `c9`=country, `p`=passage (`e`/`c`/`r`), `C`=clade list,
  `R`=reference, `sequenced`. (Inspect with `decat styled.ace | python -m json.tool`.)

## Serial foundation (land first; A1 & A2 are independent → parallel)

- **A1 — Agent-EXP** (`export_interactive.py` + `CONTRACT.md`). Export report-authoritative
  data: clade colours/legend/priority from `R["-clades-v10"]` (#2); antigen `continent`
  (`T.C9`) + continent palette from `R["-continent"]` (#6); passage from `T.p` (#3/#4);
  vaccine + serology flags/styling (#5, F2, F3); serum `norm` + each serum's homologous
  antigen index (F1); per-chart projection `stress` (F6). Bump CONTRACT.
- **A2 — shared glyph module `js/glyph.js`** (new; Agent-MAP authors). One source for point
  shapes used by map + tree: circle, square (serum), star (vaccine), egg (egg antigen),
  "ugly egg" (egg serum), reassortant glyph; role-based sizing. Add to `MODULE_ORDER`
  before `tree.js`/`map.js`. Underpins #5, F2, F7.

## Fan-out (after A1/A2). #1/#7/F4/F5 are independent and can start immediately.

| Agent | Items | Files |
|-------|-------|-------|
| Agent-COLOUR | #2 report clade palette; #3 drop unused `cell` from marker key; #4 passage colours; #6 continent colouring of antigens; **F8** legend-click tri-state (select → send-to-back → normal) | `colour.js`, `ui.js`, (`state.js` w/ SELECT) |
| Agent-MAP | #5 fix vaccine stars; #7 macOS zoom (pinch/wheel/buttons); F2 larger vaccines; **F5** 1-AU gridlines; **F6** stress in corner; F7 egg/serum shapes; A2 glyph | `map.js`, `glyph.js` |
| Agent-TREE | #1 edges invisible when window unfocused (initial transform/rAF/layout); F2 larger vaccine tips; **F3** serology tips slightly larger; **F4** clade labels on tree (report-style); F7 egg-shape tips | `tree.js` |
| Agent-SELECT | **F1** serum-click selects homologous antigen + tree tip (sera carry `data-norm`); F8 cycle semantics + send-to-back ordering | `state.js`, `map.js`/`tree.js` hooks |

Dependencies: #2/#6/F1/F3/F6 need A1; #5/F2/F7 need A2; F8 shared COLOUR+SELECT (define
cycle states once in `state.js`). Verify per task: re-export single + all-centres to a
scratch dir (never the repo), headless render; remember post-load `requestAnimationFrame`
does not fire under `--virtual-time-budget` (override rAF→setTimeout to test
zoom/pan/lines/colour repaints). Commit own files only; WHO-data check before commit
(real data → report folder, not repo); push only on request.

---

# v4 — third feedback wave (12 fixes + 2 features)

From a third round of testing. Theme: match the report's exact point SHAPES, fix the
tree-label nomenclature, and a few layout/interaction fixes.

## Canonical references (investigated against kateri / acmacs-data — use verbatim)

**Point shapes** (kateri `lib/src/draw_on*.dart`, the report renderer):
- **egg** (antigen): `M0,r C1.4r,0.95r 0.8r,-0.98r 0,-r C-0.8r,-0.98r -1.4r,0.95r 0,r Z`,
  then **aspect scale x0.75** (width = 0.75·height). Replaces the too-pointy current egg (#4).
- **uglyEgg** (egg serum): hexagon `M0,r L1.0r,0.6r L0.8r,-0.6r L0,-r L-0.8r,-0.6r L-1.0r,0.6r Z`,
  aspect x0.75 (#5).
- **reassortant** = egg (antigen) / uglyEgg (serum) **rotated 0.5 rad (~28.6°)** (#11/#12).
- **vaccine** = NOT a star — the antigen's normal passage shape but **larger** (kateri size
  ~40 vs ref ~20–32), black outline (#3).
- Passage ⇒ SHAPE, **no outline ring** (#10). Antigen: cell→circle, egg→egg, reassortant→tilted
  egg. Serum: cell→box(square), egg→uglyEgg, reassortant→tilted uglyEgg.

**Clade labels (#2):** the bundle `clade_legend` already embeds the Pango name where one
exists (`158K 189R (J.2.3)`, `135K 189R (J.2.4)`, or bare `K`), from `semantic_clades.py`
clades-v10. Exporter derives `clade_short` (parse `\(([A-Za-z0-9.]+)\)`, else the legend if it
is already a short token, else null). Tree labels with `clade_short`; clades with none are not
labelled (never show the AA motif). Motif-only clades (`135A`, `189R`) have no Pango.

**#1 lead:** edges render but `computeFit` reads a too-small `treeScroll` height (layout
timing), squishing the phylogram into a ~156px band that reads as "no lines."

## Tasks by agent

| Agent | Items | Files |
|-------|-------|-------|
| Agent-MAP | glyph: fix `eggPath`(#4)/`uglyEggPath`(#5)+rotation(#11/#12), drop vaccine-star; map: vaccine=bigger passage shape(#3), reassortant tilted egg(#11)/serum tilted uglyEgg(#12), egg serum=uglyEgg(#5), **remove passage outline**(#10), remove darker gridlines(#6), gridlines on grid panels(#7), grid not overflowing legend(#8), **F1** sera outline = colour-by colour | `glyph.js`, `map.js`, `grid.js` |
| Agent-TREE | #1 branch-line visibility (computeFit pane-height/layout), #2 Pango clade labels (`clade_short`, skip motif-only), #3 vaccine tip=bigger shape, #4 egg tip shape, #10 no passage outline, #11 reassortant tip=tilted egg | `tree.js` |
| Agent-COLOUR | #9 legend clickable where it overlaps the map (z-index/pointer-events), coordinate #8, **F2** extend legend click-cycle to continent + amino-acid legends | `colour.js`, `ui.js`, template |
| Agent-SELECT | **F2** generalise the clade cycle to a per-attribute cycle (clade/continent/aa value) + fold into `emphasis()` | `state.js` |
| Agent-EXP | #2 export `clade_short` (Pango per clade or null) | `export_interactive.py`, `CONTRACT.md` |

Dependencies: glyph shape fixes land with map+tree shape adoption; #2 needs Agent-EXP
`clade_short` before Agent-TREE; F2 = Agent-SELECT (store) + Agent-COLOUR (legend) together.
Verify/commit/WHO/rAF rules as in v3.

---

# v6 — fourth feedback wave (6 fixes + 3 features)

## Canonical references (investigated; use verbatim)

- **Time-since-collection gradient (F1):** viridis 3-point Bézier — `#440154` (oldest) →
  `#40ffff` → `#fde725` (newest), quadratic Bernstein per channel, `t = i/(n−1)` linear
  over the date window. Anchor newest = page-generation date; span back to oldest antigen
  date. (from acmacs-tal `color-gradient.cc`.)
- **New since report/VCM (F2):** antigen semantic `T.new` = 1 (since previous **report**) or
  2 (since previous **VCM**). Style = bold **black outline**, width **3** for new=1, **6**
  for new=2, raised to front (`chart_modifier.py:127`). Export `new` per antigen.
- **Serum circles (F3):** `proj.serum_circles(fold=2.0)` → per-serum `.theoretical()` /
  `.empirical()` (floored 2.0; report shows **empirical**). Theoretical = `2.0 + column_basis
  − log2(homologous/10)`. Coverage colouring: `threshold = log2(homologous/10) − 2`; titrated
  ≥threshold → **pink** 3px outline, <threshold → **black** 3px outline, both bright fill;
  **untitrated → pale**. Circle centred on serum, radius in map units; outline by serum
  passage (egg=red/cell=blue/reassortant=orange), translucent `#18RRGGBB` fill.
- Serum API: `serum.passage()`, `serum.serum_id()`, `serum.serum_species()` (for #6).

## Tasks by agent

| Agent | Items | Files |
|-------|-------|-------|
| Agent-EXP | #1 uppercase chart `label`; #6 serum `passage`/`serum_id`(/species); F1 `meta.generated`; F2 antigen `new` (1/2); F3 per-serum `{cb,theoretical,empirical}` via `serum_circles(2.0)` | `export_interactive.py`, `CONTRACT.md` |
| Agent-MAP | #5 all-centres **3×2** + fix off-page points + **narrower tree pane** (single & grid); #6 serum tooltip passage+id; F2 bold-outline (w3/w6) on new antigens; F3 draw serum circles (with LINES) | `map.js`, `grid.js`, template |
| Agent-TREE | #3 keep J.2.4/K clade labels anchored near their clade (placement/de-overlap); F2 bold outline on new tips | `tree.js` |
| Agent-COLOUR | #4 legend marker key via `IV.Glyph` (reassortant=tilted egg, vaccine=bigger shape, not triangle/star); F1 colour-by-time gradient mode + gradient legend + show generation date; F3 serum-coverage colour mode (pale untitrated, pink/black borders) | `colour.js`, `ui.js` |
| Agent-LINES | #2 error/connection lines for selected **sera** (serum titer row); F2 "new since report/VCM" toggles in Overlays; F3 serum circles in Overlays (show-all + show-on-select), passage-coloured | `lines.js` |
| Agent-SELECT | #2 **double-click-to-isolate** (hovered point only, bypass homolog expansion); F2 State flags for the new-since toggles | `state.js` |

Placement: F2 highlight = Overlays toggles + bold outline (not colour menu); F3 circles =
Overlays (all / on-select), serum-coverage point colouring = Colour menu. Dependencies:
all viewer F-tasks need Agent-EXP's new fields first. Verify/commit/WHO/rAF rules as in v3.

---

# v7 — fifth feedback wave (4 refinements)

Theme: new-since and serum-coverage should both use the **dim-the-others emphasis**
(like clade-select "select" mode), not bold outlines / pale tints.

## Diagnoses (investigated)
- **#1 double-click isolate fails on the MAP:** two dblclick listeners on the *same*
  `#mapSvg` node — `state.js` isolate (capture, `stopPropagation`) + `map.js` `resetView`
  (bubble, ~line 370). `stopPropagation` does NOT block a same-node listener, so a point
  dblclick both isolates AND resets zoom. (Tree works: its resetView is on the container.)
- **#2 clade labels K/J.2.5 too low:** anchored at the clade's **median tip row**; for
  nested/spread clades the median lands below the branch. Anchor at the clade's MRCA node y.

## Tasks
- **#1** Agent-MAP: in `map.js` dblclick, `return` (skip resetView) when
  `e.target.closest("[data-norm]")`; Agent-SELECT: isolate handler uses
  `stopImmediatePropagation()` for belt-and-braces. Verify a map point dblclick isolates
  (and shows only that point's lines) without resetting zoom.
- **#2** Agent-TREE: anchor each clade label at the clade's representative internal node
  (MRCA of its tips) y, not the median tip row. Verify K and J.2.5 sit on their branch.
- **#3** new-since = emphasis, not outline. Agent-SELECT: fold the new-since set
  (`new`=1 for showNewReport, `new`>=1 for showNewVCM) into `emphasis()` so non-matching
  antigens DIM (like clade-select); Agent-MAP + Agent-TREE: remove the width-3/6 black
  outline render. (Toggles stay in Overlays.)
- **#4** serum-coverage rework (single serum selected only):
  - untitrated antigens → DIM/transparent (like clade-select), not pale-lightened.
  - titrated ≤4-fold of homologous (`log2(titer/10) >= log2(hom/10) − 2`) → **pink** outline;
    >4-fold → **black** outline **thicker than pink** (e.g. pink 3, black 4–5).
  - gate on EXACTLY one serum selected.
  - **NEW: apply the same coverage treatment on the tree tips.**
  Agent-COLOUR (outline widths + untitrated→dim) + Agent-MAP (apply) + Agent-TREE (coverage
  on tips) + Agent-SELECT (single-serum gating + emphasis integration).

Verify/commit/WHO/rAF rules as in v3.

---

# v8 — point-identity selection + map-coverage fix

## Problem
Selection is keyed by **normalised strain name** (`norm`). A serum and its same-name
antigen share that key, so you can't select only the serum — selecting the strain
highlights both, and double-click-isolate (which only drops homolog expansion) can't
separate them. Sera-specific features (error/connection lines, serum circle, coverage)
need to scope to ONE serum, not a strain.

## Tasks
- **Point-identity selection (Agent-SELECT, `state.js`):** add an "isolated point"
  selection distinct from the norm set — `State.isolated = {kind:'serum'|'antigen', i}`
  (i = index in the active chart), with setter + clear. **Double-click a point sets it to
  that exact point** (replacing the old dblclick-isolate-by-norm); single click stays
  norm-based (with homolog expansion). Expose `isIsolated()`, `isolatedSerum()` (the serum
  object when `kind==='serum'`), and a predicate the panels use, e.g.
  `pointEmphasis(kind, i, norm, clade)` → {dim,sel}: when a point is isolated, ONLY that
  exact element is `sel`; everything else dims (so a serum isolates without lighting its
  same-name antigen). Empty-space click / Esc clears isolation.
- **Map (Agent-MAP, `map.js`/`grid.js`):** mark each glyph with its identity (e.g.
  `data-kind`+`data-i`, or carry kind/i in hiList — antigen entries already have `a.i`,
  sera need `i`). In refresh, when isolated, set `sel` only on the exact element, dim the
  rest. **Also fix #4 map-coverage:** `applyCoverageTo` currently doesn't apply (rendered
  antigens keep base stroke `#000/1.3` though `Colour.coverageOutline` returns valid data
  and the tree applies it) — drive coverage off the **isolated serum** (`isolatedSerum()`)
  and ensure the pink(≤4-fold,w3)/black(>4-fold,w4.5) outlines actually get written
  (check the `ck!==_covKey` gate / timing).
- **Lines (Agent-LINES, `lines.js`):** when a serum is isolated, draw its error/connection
  lines for that one serum only (key off `isolatedSerum()`), not the strain.
- **Tree (Agent-TREE, `tree.js`):** isolating a serum highlights no tip (sera aren't on the
  tree) but the **serum-coverage tip outlines** should scope to the isolated serum (already
  works via coverageSerum — point it at `isolatedSerum()`).

Coordination: Agent-SELECT defines `isolated` + `isolatedSerum()` first; map/tree/lines
consume it (coverage `singleSelectedSerum` → `isolatedSerum`). Verify: double-click a serum
→ only that serum highlighted (same-name antigen NOT), its lines/circle/coverage show; map
coverage outlines render (pink + thicker black). Verify/commit/WHO/rAF rules as in v3.

---

# v9 — sixth feedback wave (10 fixes + 5 features)

Diagnoses: F4 stress readout already exists (`map.js showStress`, bottom-left) but is
occluded by the bottom legend (same cause as #9) → move to a visible corner. #5 double-click
uses the **native `dblclick`** event (state.js) — unreliable in Safari; replace with manual
detection (two clicks <~300ms on the same point).

| Agent | Items |
|-------|-------|
| Agent-MAP | #1 gridlines behind points/error/conn lines (z-order); #9 reset/zoom buttons clear of bottom legend; **F1** draw points old→new by collection date, refs+vaccines on top; **F4** move stress readout to a non-occluded corner; #7 (shared) circle-tied coverage outline |
| Agent-LINES | #2 new-since toggles mutually exclusive; #3 keep Overlays panel size stable when conn/error ticked; **#8** empirical-vs-theoretical serum-circle toggle (bundle has both radii); #7 circle-tied outline |
| Agent-COLOUR | #10 stress colour bar: numeric values + start at 0; **F5** colour-by-stress-per-titre (per-point stress ÷ titre count); **F3** marker categories (reference/vaccine/serum/egg/reassortant) clickable like clade; **F2** map dblclick resets legend cycle |
| Agent-SELECT | **#5** Safari double-click: replace native `dblclick` with manual detection (timestamp+target); #2 mutual-exclusion flags; F2 clear cycle on dblclick; F3 cycle for marker categories |
| Agent-EXP | **#4** sera with >1 reference: export ALL homologous antigen indices (egg+cell), not just first; serum-circle algo takes min over them |
| Agent-TREE | #6 verify J.2.5 clade-label placement (anchor on its clade) |

#7 circle↔coverage: when a single serum + its circle is shown, titrated antigens get a
slightly thicker outline — pink ≤4-fold of homologous, black >4-fold (report addendum style);
reconcile with the existing `coverage` colorBy so it's driven by the shown circle, not only
the colour mode. Coordination: #2/F2/F3/#5 span SELECT + LINES/COLOUR; #7 spans MAP+LINES
+COLOUR; #4 (EXP) feeds #7. Verify/commit/WHO/rAF rules as in v3.

---

# v10 — seventh feedback wave (5 fixes + 1 feature)

- **#1** Agent-COLOUR: serum-coverage outlines too thick — reduce widths (pink/black are
  currently 3/4.5; the addendum uses thin outlines).
- **#3** Agent-COLOUR: pink too bright — `COV_PINK` is `#ff1493` (deeppink); use the report
  addendum's lighter **`#FFC0CB`** ("pink").
- **#2** Agent-MAP: untitrated antigens show a thick outline though `coverageOutline` correctly
  returns null for them (colour.js:186). Fix map-side: `applyCoverageTo` must restore the
  BASE (thin) stroke for untitrated points; confirm reference antigens' own black outline
  isn't being mistaken for coverage (e.g. A9910).
- **#4** Agent-SELECT/MAP: selecting "egg" in the legend also selects cell antigens (and
  "reassortant" selects egg+cell). `state.js` membership looks strict (`a.pt === 'egg'`), so
  the bug is likely the map resolving marker membership via its `passageType` regex fallback —
  match marker categories strictly on `a.pt` (no regex), so egg=only pt egg etc.
- **#5** Agent-EXP/LINES: H3 VIDRL serum A9933 has no circle. Data shows theoretical/empirical
  null — one copy `homologous:[]`, the other `homologous:[4]` with a non-regular homolog titre
  → legitimately circle-less per the acmacs algorithm. Confirm no homolog is being missed
  (ties to v9 multi-homologous); optionally show a "no valid homologous titre — no circle" note.
- **F1** Agent-COLOUR: new colorBy option **`titre`** = `log2(titre/10)` vs the selected serum,
  same colour range as elsewhere; shown only when a single serum is selected.

Verify/commit/WHO/rAF rules as in v3.

---

# v11 — titre/coverage emphasis (done)

Problem: colour-by-`titre` (and `coverage`) require a single serum, set via double-click
ISOLATION — but isolation's emphasis dims everything except the isolated point, so the
titrated antigens (the focus) are faded.

Fix (Agent-SELECT, `state.js`): when `colorBy ∈ {titre, coverage}` AND a single serum is
active (`isolatedSerum()`), drive antigen opacity by titrated-vs-not, NOT by isolation:
in `emphasis()`/`pointEmphasis()` an antigen returns `dim = !titrated(serum, antigen)`
(`logged[a.i][serum.i] != null` → foreground; null → dim); the serum stays lifted; this
overrides the isolation dim for just these two modes. Other modes unchanged. Agent-COLOUR
confirms titre fill / coverage outline still apply to the now-foreground points.
Verify: isolate serum → titre mode → titrated antigens full-opacity & titre-coloured,
untitrated faded; same in coverage. (Status: DONE — implemented in `state.js` via
`_serumScope()` + the titration branches in `emphasis()`/`pointEmphasis()`; gated on
`colorBy ∈ {coverage, titre}` and `isolatedSerum()`, keying titration off
`logged[a.i][serum.i] != null`.)
