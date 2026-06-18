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
