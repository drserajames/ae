# ssm-report → ae: vcm consolidation migration plan

Status: **engine consolidated; assembled-report run ✅ reproduced (capstone done).** Phases
0–3 + 1b complete: the AD-faithful `py/ae/report/` port was shelved (branch `report-shelved`)
and the **library tier** of the team's ae-based report engine (`vcm`) is consolidated into
`py/ae/report/`. The library tier is a **verified faithful** copy (see the [2026-0223 gap
analysis](#gap-analysis-2026-0223-capstone-attempt) below). The **full assembled report** of
the real `2026-0223-ssm` now builds on `ae.report` (`report.py` → 36-page `report.pdf`,
visually identical to the AD/vcm reference) after a **2-file / 3-edit** per-report adaptation.
Gap #1 (geographic clade/aa colouring) is **closed**; gap #2 (tree `.tal` fidelity) is **diffed
+ handed to TAL**. The adjust stage is ported (`ae.adjust` programmatic + kateri point-drag
interactive). The **per-map antigenic-map `style`/`export` is now also rewired to `ae.report`
and kateri** — the per-map `0do` library imports (`main_loop`/`commander`/`download`/`dirs`)
point at `ae.report.*`, and each subtype modifier (`h1`/`h3`/`b`) mixes in the concrete
`ConferenceData`; verified end-to-end through kateri: **h1-cdc** `out.1.clades.pdf` is
pixel-identical to the reference, and **bvic-crick** produces the full B clade set
(`clades-v1`/`v2`/`-6m`/`-12m` + serology + ts) — see the [per-map export rewire](#per-map-export-rewire-to-aereport--kateri).
The **from-scratch figure regeneration** has been run on `ae.report` against a **current hidb**:
**19/19** per-map dirs regenerated via kateri (incl. a `find_previous_chart` graceful-None fix), **stat** reproduced (structurally identical,
monotonic superset of the report's), **geo** reproduced for **all three subtypes (H1/H3/B)**, and
a **fully ae-generated 36-page `report.pdf`** re-assembled from the regenerated figures (maps +
trees + geo, no AD binaries/`vcm`) — and the regenerated maps are **pixel-verified** against the
pristine original (content-identical; <1 % differing pixels, all anti-aliasing edges). See
[from-scratch figure regeneration](#from-scratch-figure-regeneration-current-hidb).
**Remaining:** only the TAL tree-fidelity gaps (#3) — not an `ae.report` blocker. The `ae.report`
side of the seasonal report is **end-to-end reproducible** (engine, all four figure families,
assembled PDF).
This document records the plan and the as-built decisions. Read it before touching
report code. (Sections below are kept as the historical plan + rationale.)

---

## Gap analysis (2026-0223 capstone attempt)

Done 2026-06-14 while attempting a full assembled-report remake against a copy of the
real `2026-0223-ssm` report (a **later** report than the `2026-0119-tc2` the
consolidation was built from). Diffed that report's `py/vcm/v2` against `ae.report`.
**The capstone run is what surfaces these — they were not visible from import checks.**

**Verified faithful (ready).** After normalising `vcm.v2.*`→`ae.report.*`, the
library/engine tier differs only by header comments, the deliberate engine/per-report
decoupling, and raw-string `SyntaxWarning` fixes — **no missing logic**:

| module | real divergence from this report's vcm |
|---|---|
| `commander`, `download`, `main_loop`, `dirs`, `modules` | none (import-rewrite artifacts only) |
| `chart_modifier` | only base-class swap (`conference_data_base`) + guarded `semantic_*`/`serology` imports |
| `latex` | only `r"..."` warning fixes — byte-identical rendered output |

**Three genuine gaps (NOT ready for a faithful remake):**

1. **`geographic.py` — ✅ CLOSED 2026-06-14.** This report's vcm shells the AD
   **`geographic-draw`** binary with a full `-s settings.json` **clade/aa colouring**
   spec from `ConferenceData.geographic_coloring(subtype)` / `geographic_settings()`
   (`apply` rules like `["156N","155G"]`), `--time-series monthly`. `ae.report.geographic`
   now has a **`color_by="coloring"`** mode that consumes that spec faithfully: `_Coloring`
   is a Python port of AD `ColoringByAminoAcid::color` (ordered `apply` rules; a `sequenced`
   rule sets fill only; an `aa` rule matched via seqdb's `SequenceAA.matches_all` — incl. `!`
   negation and `-` deletions — overrides fill/outline/outline_width; later matches win;
   unmatched → `default`). geo-draw gained a packed-dots renderer (one dot per antigen,
   AD's concentric-ring packing via `point_size`/`density`; `CairoPdf::sector` + per-point
   `outline_width`; `circle()` skips the stroke on transparent/zero outline). **✅ Verified**
   on real H1 hidb (Dec 2023 window — local hidb is stale so the exact 2025-12 reference
   month can't be reproduced here): dots are clade-coloured by the report's exact palette
   (`#5b00d3`=D, `#BE187D`=C.1, `#98e1d7`=C.1.9; unmatched = faint grey rings), packed in
   rings per location, month-name title, no on-map legend — the AD representation. The older
   **continent** dot and **clade pie** modes still work (no regression). Residual cosmetic
   diffs: geo-draw's base map fills land light-grey (AD: white); a few unicode location names
   don't resolve in the local locdb.

2. **Trees — ⚠ DIFFED 2026-06-15; report glue OK, but NOT yet faithful (TAL gaps).**
   vcm/v2 has **no** `trees.py`; trees are produced by `tree/0do` shelling the **AD `tal`**
   binary, which auto-loads the builtin `$ACMACSD_ROOT/share/conf/{tal,vaccines}.json`
   (defines `$canvas-height`, `clades-whocc`, `eu-aa-transitions`, …) before the user `.tal`.
   `ae.report.trees` is a *new* wrapper over ae's `tal-draw` + the `ae.tal.settings_v3`
   `.tal`→schema translator. The **report glue itself works** — it translated + rendered the
   real bvic / h3 `.tal` (38 k / 70 k leaves) and named the output correctly. But diffing the
   ae PDFs against the AD references (`tree/{bvic.after-2021,h3.asr.after-2021}.pdf`) shows
   they are **not visually faithful**. All gaps are **TAL-subsystem** (`cc/tal` + `py/ae/tal`),
   not report-side:
   - **Canvas width / aspect.** ae renders **1000×1000 square**; AD is **portrait** (bvic
     631×1000, h3 648×1000) — tal-draw doesn't compute canvas *width* from the tree
     `width-to-height-ratio` (0.41) + accumulated column widths (`$canvas-height`=1000 matches).
   - **`draw-aa-transitions` positioned labels.** The biggest content gap: the report's
     manually-curated per-node clade/transition labels (a `{"N":"draw-aa-transitions", per_nodes:[{name, node_id, label:{offset…}, show}]}`
     section) are **not translated** by `settings_v3`, so most on-tree clade labels are missing.
     (tal-draw *does* support positioned `apply.text` labels per TODO #3 — so this is mostly a
     translation mapping `draw-aa-transitions[*]` → `nodes select{node_id} apply{text}`.)
   - **Clade-coloured matrix.** AD colours the right-side time-series / dash-bar matrix cells by
     clade; ae renders them monochrome black.
   - **Clade legend** is partial vs AD's full vertical colour-bar legend.
   - **Geographic map inset** (small world map, lower-left, from clades-whocc/builtin) is absent.
   - **Tree edge colour**: ae draws edges purple (a default/clade colouring); AD black.
   - **Translator robustness nits:** `?`-disabled keys inside objects (e.g. `?last`) emit
     spurious "unknown built-in … ignored" warnings (should be silently skipped); `nodes` with
     a string `apply` ("report") are skipped (informational-only — harmless).
   See the handoff list appended to TODO #3 (TAL). The report side needs no change.

3. **Per-report glue + assembled-report run — ✅ DONE 2026-06-15 (capstone).** Applied the
   per-report adaptation to a copy of the real `2026-0223-ssm` report and ran the full
   **assembled report** (`report.py` → `report.pdf`) on `ae.report`. The adaptation was
   **minimal — 2 files, 3 edits** (the library tier is faithful, so almost nothing changed):
   - `report.py`: `from vcm.v2 import latex, conference_data` → `from ae.report import latex`
     + `from vcm.v2 import conference_data`.
   - `conference_data.py`: `from . import latex` → `from ae.report import latex`; and
     `import vcm.v2.dirs` + `class ConferenceData(vcm.v2.dirs.VcmDirs)` →
     `from ae.report import conference_data_base` + `class ConferenceData(conference_data_base.ConferenceData)`.

   `conference_data.report_content()` drove `ae.report.latex` (cover / toc / section_title /
   geographic / phylogenetic_tree / maps_in_columns) to assemble the report's figures. **✅
   Verified:** `pdflatex` ran clean (rc=0, two passes) → a **36-page `report.pdf`** byte-for-byte
   the same page count and ~size (11.99 MB vs the AD/vcm reference 11.98 MB) with **visually
   identical** cover, geographic, and content pages. This proves the `ae.report` assembly engine
   reproduces the real report end-to-end.
   - *Scope note:* this **assembled the report's existing figure PDFs** (maps/geo/trees/stat,
     produced earlier by the report's own tooling) via the `ae.report` engine. It is the
     "assembled-report run" milestone — **not** a from-scratch regeneration of every figure on ae
     (that additionally needs a current hidb, kateri for the antigenic maps, the TAL tree-fidelity
     fixes from gap #2, and rewiring each per-map `0do` `style`/`export` to `ae.report`).
   - *Gotcha:* `\includepdf` (pdfpages) can't handle **spaces in absolute paths** (`latex` uses
     `Path.resolve()`); the working copy's `" copy"` dir-name broke the 3 tree pages until renamed
     to `2026-0223-ssm-copy`. Real report dirs have no spaces.
   - The `serology.py` + subtype `chart_modifier` mix-ins (`class H1_ChartModifier(ChartModifier,
     ConferenceData)`) are only needed for the per-map **style/export** (figure generation), not for
     assembly — so they remain for the from-scratch-regeneration follow-up, not the capstone.

   **No real report data entered the `ae` repo** — these 2 edits live in the report working copy
   under `~/AC/eu/ac/results/ssm/2026-0223-ssm-copy`, not in `ae`.

**Plus a non-mechanical rewire detail.** `stat.py` means **different things** in the two
trees — `ae.report.stat` is the new hidb writer; vcm's `stat.py` is `ae.report.stat_tables`.
So `0do`'s `from vcm.v2.stat import make_stat` → `from ae.report.stat_tables import make_stat`
is **not** a blind `s/vcm.v2/ae.report/`.

**Remake order (fix gaps as they surface):** (1) build + verify the geo-pie work → then
extend `ae.report.geographic` to consume `geographic_coloring`; (2) rewire one subtype-lab
dir (`h1-cdc`) + write per-report glue → diff the map PDF vs the existing `out.1.clades.pdf`;
(3) stat → geo(clade) → trees, each diffed vs the reference figures already in the folder;
(4) `report.py` → assembled `report.pdf`. **No real report data is copied into `ae`** — the
copy lives under `~/AC/eu/ac/results/ssm/`, outputs/verification stay there or in `/tmp`.

---

## Per-map export rewire to ae.report + kateri

Done 2026-06-16. The per-map antigenic-map generation (`<subtype>-<lab>/0do` `populate`/
`style`/`export`, which drives **kateri** to render `out.1.<style>.pdf`) now runs on
`ae.report` instead of `vcm.v2`. The rewire is mechanical and falls into two parts:

- **Per-map `0do` (×21):** rewrite only the **library** imports —
  `vcm.v2.{main_loop,commander,download,dirs}` → `ae.report.{…}`
  (`sed -E 's/vcm\.v2\.(main_loop|commander|download|dirs)/ae.report.\1/g'`). The
  per-report imports (`vcm.v2.<subtype>_chart_modifier`, `vcm.v2.conference_data`,
  `vcm.v2.serology`) **stay** `vcm.v2` — they live with the report.
- **Subtype modifiers (`h1`/`h3`/`b_chart_modifier.py`):** `import vcm.v2.chart_modifier as
  cm_m` → `import ae.report.chart_modifier as cm_m`, add `import vcm.v2.conference_data as
  conference_data`, and **mix the concrete ConferenceData into the subtype base** —
  `class H1_ChartModifier(cm_m.ChartModifier, conference_data.ConferenceData)` (same for
  `H3_ChartModifier`, `B_ChartModifier`; the `*_HI`/`*_Neut`/`B_Vic`/… subclasses inherit it).
  Needed because `ae.report.chart_modifier.ChartModifier` now inherits the
  `conference_data_base` stubs (so `ae.report` imports standalone); the mix-in puts the real
  per-season data back in the MRO.

**✅ Verified end-to-end through kateri** (worktree on `ad-port`; `PYTHONPATH` = report dirs +
`acmacs-data` + the main checkout's `build/` for `ae_backend` + the worktree `py`):
- **h1-cdc** `populate_export` → `out.1.clades.pdf` **pixel-identical** to the AD/vcm reference
  (same title, clade legend + counts, antigen cloud, vaccine labels).
- **bvic-crick** `populate_export` → the full **B** style set (`clades-v1`/`clades-v2` + `-6m`/
  `-12m` + `serology` + `ts-*`; B uses `clades-vN`, not bare `clades`), the B/Vic clade map
  renders correctly. (Exercises the `B_ChartModifier` mix-in.)
- **h3-hint-cdc** / bvic import + MRO checks pass (concrete `ConferenceData` resolves through
  the mix-in; commander base is `ae.report.commander`).

**One engine fix this surfaced** (committed to `ae`): `ae.utils.org.org_table_to_dict` now
tolerates **ragged rows** (a data row with fewer cells than the header) — the report's
top-level `serology.py` (which `ae.report.chart_modifier`'s guarded `import serology` resolves
to) tripped an `IndexError` otherwise.

The 21 `0do` + 3 modifier edits live in the **report working copy** (not `ae`). Running the
export for all dirs (the bulk figure regeneration) is mechanical from here, but heavy (each
`populate_export` launches kateri and writes the per-style PDFs); the rewire + cross-subtype
verification is what makes it reproducible on `ae.report`.

---

## From-scratch figure regeneration (current hidb)

Done 2026-06-16 — the full figure regeneration for the `2026-0223-ssm` report, run on
`ae.report` against a **freshly-updated hidb** (the owner ran `whocc-hidb5-update` on the
server + `hidb5-download`; coverage went from stale-2024-02 to **H1→2026-03 / H3→2026 /
B→2026-04**). All three non-map families confirmed; **no AD binaries** (`hidb5-stat`,
`geographic-draw`) and **no `vcm`** involved.

- **Antigenic maps (kateri): 19/19 dirs** regenerated their full current-window style set via
  `ae.report` + kateri (all of H1, H3, B across labs). *(Initially 17/19 — the 2 `-vidrl` dirs,
  which use the base `previous_charts()` requesting a **2-back** chart, hit
  `dirs.find_previous_chart` raising `NotImplementedError` because `2025-1217-tc1` has no chart
  for them. Fixed: `find_previous_chart` now returns `None` when the previous report exists but
  lacks this dir's chart — matching its own merges-branch behaviour and the caller's "eliminate
  not found" filter; only raises if the previous dir itself is missing. Both vidrl dirs then
  regenerated.)*
- **Pixel-verified against the pristine original report** (`2026-0223-ssm`, not the copy): 7
  maps across H1/H3/B and 6 labs differ by only **0.25–0.97 %** of pixels, and the diff image
  shows those are **anti-aliasing edges** on dots/text (sub-pixel kateri rendering), not content —
  no recolours, no moved points, no clade changes. The maps are **content-identical**; the
  A1-fixed `bvic-vidrl` matches at the same fidelity (0.29 %), confirming the fix yields a correct
  map. (The chart `.ace` + styling are deterministic; clade colours from a stable seqdb.)
- **stat (`ae.report.stat` → `ae.report.stat_tables`):** reproduced the report's `stat.json.xz`
  — **structurally identical** and a **monotonic superset**: all 1577 common numeric leaves
  `ae ≥ ref`, exact match where data is unchanged (e.g. `VIDRL 202511 AUSTRALIA-OCEANIA 20=20`),
  the higher ones pure hidb accretion Feb→Jun (e.g. `CDC NORTH-AMERICA 111→340`). This is the
  Python `hidb5-stat` port over `ae_backend.hidb` — no AD C++ binary.
- **geo (`ae.report.geographic`, `color_by="coloring"`): all three subtypes (H1/H3/B)**
  regenerated into `report/geo/` for the report window (Aug 2025–Jan 2026) — same clade-coloured
  packed-dot representation + report palette; more dots than the report-era reference, consistent
  with the same hidb accretion the stat showed (H3 is large: 223–1501 locations/month). Clade
  colouring resolved from seqdb (current enough for these strains). A few Chinese-character
  location names don't resolve in the local locdb (pre-existing — a handful of dropped dots).
- **Fully ae-generated `report.pdf`:** re-ran `report.py` after the regeneration → a **36-page
  A4 `report.pdf`** assembled on `ae.report` that embeds **only ae-regenerated figures**:
  antigenic maps (kateri), phylogenetic trees (ae `tal-draw`), geographic maps (ae `geo-draw`
  clade-colouring), cover/TOC/section pages (`ae.report.latex`). No AD binaries, no `vcm`. It is a
  **refreshed** report (current hidb → more data), not a byte-repro of the Feb original; the 2
  stale `-vidrl` maps are embedded where referenced (the previous-chart gap above); this report's
  content doesn't include stat *tables* (its `latex.time_series` calls are commented out), though
  stat itself is regenerated+verified separately.

**Infra note (build contention).** The shared `build/ae_backend.so` had **lost its `hidb`
submodule** — a concurrent agent on another branch (`fixed-column-bases`) had rebuilt it without
hidb. So this run used a **clean `ae_backend` (+`geo-draw`) built from `ad-port` in an isolated
worktree** (`ae-report/build-wt`), configured **offline** by copying the main checkout's
`subprojects/packagecache/` (the network was blocked for wrap downloads). hidb currency was first
confirmed with AD's `hidb5-dates` straight off the downloaded `.json.xz` (no rebuild needed for
the check).

**Data hygiene:** stat/geo outputs went to `/tmp`, maps to the report working copy under
`~/AC/eu/ac/...`; **nothing real entered the `ae` repo**. The only `ae` change from the whole
per-map/regeneration effort is the committed `ae.utils.org` ragged-row fix.

---

## TL;DR

- The WHO CC seasonal report is **already built on `ae`** today — by a tool called
  **`vcm`** that lives in each report working directory (`<report>/py/vcm/`), not in
  the `ae` repo.
- My `py/ae/report/` is an **AD-faithful re-port** of the *old* declarative AD
  `ssm-report` (`report.json` → `LatexReport`). It is **superseded by vcm** —
  **except `stat.py`**, which is genuinely additive (vcm still shells the AD C++
  `hidb5-stat`; my `stat.py` ports that to Python over `ae_backend.hidb`).
- Plan: **shelve** the AD-faithful port, **bring `vcm`'s stable library tier into
  `ae`**, keep the **per-season config** in the report dirs, and **wire vcm's stat to
  my `stat.py`** so the result has no AD/C++ dependency.

---

## How we got here (history)

| Era | Tooling | Evidence |
|---|---|---|
| ≤ ~2019 / early-2020 | **AD `ssm-report`** — `report.json`/`setup.json` → `ssm-make`/`maker.py`, shelling AD binaries (`hidb5-stat`, `geographic-draw`, `map-draw` mapi, `tal`) | report dirs `2018-*`…`2020-0224` carry `report.json` |
| ~2020-08 → 2022-02 | **intermediate** hand-written per-dir `report.py` | those dirs have neither `report.json` nor `vcm`, just `report.py` + `README.org` |
| ~2022-06 → now | **`vcm` (ae-based)** | first in `2022-0803-tc1`; every report since incl. `2026-0119-tc2` |

The integration into `ae` has been **happening gradually**: the 2022 `vcm` bundled its
own `kateri.py` / `date.py` / `lab.py`; by the 2026 `vcm` those are gone, imported from
`ae.utils.kateri` / `ae.utils.datetime` / `ae.utils.time_series`. The *generic* layer
already moved into `ae`; the *report logic* (`latex.py`, `conference_data.py`,
`chart_modifier*`, `stat.py`, `geographic.py`) is the slice still outside the repo —
exactly what `ae` TODO #4 ("ssm-report → `py/ae/report/`") points at.

**No `import acmacs` (AD) anywhere in vcm** — it is pure `ae`. The only AD that remains
in the report workflow was the interactive map-adjustment `0do`/`zero_do` framework — now
ported to ae (see [Stage B](#stage-b--interactive-map-adjustment-ported-to-ae--port-plan)).

**Canonical source for the port: the latest vcm, `~/AC/eu/ac/results/ssm/2026-0119-tc2/py/vcm/v2`**
(not the 2022 snapshot). Same 15-module structure, ~3,330 lines.

---

## Audit: `vcm/v2` vs `py/ae/report/`

| Concern | `py/ae/report/` (mine, AD-faithful) | `vcm/v2` (team, ae) | Verdict |
|---|---|---|---|
| LaTeX assembly | `report.py` (`LatexReport`, declarative from `report.json`) + `latex.py` (AD template strings) | `latex.py` (imperative functions → `list[str]`) | vcm supersedes |
| Report structure | `templates/report.json` | `conference_data.py` (Python) | vcm supersedes (per-report config) |
| **Stat computation** | `stat.py` — **ports `hidb5-stat` to Python** (`ae_backend.hidb`+`locdb_v3`) | `stat.py:49` — **shells external AD `hidb5-stat`** | **mine is additive — keep** |
| Stat tabs/CSV/HTML | — (LaTeX only, via `StatisticsTableMaker`) | `stat.py` `_make_tabs/_make_csv/_make_webpage` | vcm has more |
| Scaffolding | `init.py` (report-dir layout) | `dirs.py` (per-map layout) | vcm supersedes |
| Chart prep / styling | — | `download.py`, `chart_modifier*`, `commander.py` (`download`/`populate`/`prestyle`/`style`/`export`) via `ae.semantic`+kateri | vcm-only |
| Geographic / serology | — | `geographic.py`, `serology.py` | vcm-only |
| Orchestration | `cli.py` + `bin/ssm-report*` | `commander.py` + `main_loop.py` (kateri loop) + `modules.py` | vcm supersedes |
| Interactive adjustment | — | — (`adjust/0do` scripts) | **ported to ae** (`ae.adjust`, Stage B) |

---

## The decisive finding: vcm is two tiers

Diffing `vcm/v2` across reports (2024-0201 vs 2026-0119) shows a clean, objective seam.

**Per-report tier — edited every season, lives with the report:**

| module | lines changed 24→26 | what changes |
|---|--:|---|
| `conference_data.py` | **596** | report definition: meeting date, time-series window, labs/sections, map titles/layout |
| `serology.py` | **157** | which serology antigens to highlight |
| `h3_chart_modifier.py` | **39** | the season's clades (`clades-v2`→`clades-v10`), strain lists, style variants |
| `h1_chart_modifier.py` | **7** | same, H1 |

These encode **season-specific scientific decisions** (current clades, vaccine strains,
included labs, report structure) that genuinely change at every WHO CC meeting.

**Library tier — byte-identical 2024 == 2026:**

`stat.py`, `commander.py`, `main_loop.py`, `modules.py`, `dirs.py`, `download.py`, base
`chart_modifier.py`, `geographic.py`, `b_chart_modifier.py` — **0 changes**. `latex.py`
evolves slowly (~13 lines; the engine, not per-report).

vcm is **already structured for the split** — base class + per-season subclass:

```
chart_modifier.py:    class ChartModifier                       ← stable (2024 == 2026)
h3_chart_modifier.py: class H3_ChartModifier(ChartModifier)     ← edited each season
                      class H3_HI_ChartModifier(H3_ChartModifier), H3_Neut_…, …
```

So consolidation is **not** "freeze a moving target" — it is "lift the stable engine into
`ae`, leave the per-season config where it belongs."

---

## Target layout in `ae`

> **Open decision (naming):** `py/ae/report/` (reuse — matches TODO #4 and `bin/ssm-report*`)
> vs `py/ae/vcm/` (preserve the team's name; vcm is broader than "report" — it also does
> chart prep/styling/adjustment orchestration). Recommendation: **`py/ae/report/`**, with the
> public entry kept as `vcm`-style commands. Adjust the table below if `py/ae/vcm/` is chosen.

```
py/ae/report/
├── __init__.py
├── latex.py            # LIBRARY  ← vcm latex.py (assembler engine)
├── commander.py        # LIBRARY  ← vcm commander.py (command surface)
├── main_loop.py        # LIBRARY  ← vcm main_loop.py (async + kateri task)
├── modules.py          # LIBRARY  ← vcm modules.py
├── dirs.py             # LIBRARY  ← vcm dirs.py (working-dir conventions, lab_title/lab_of_dir)
├── download.py         # LIBRARY  ← vcm download.py (download/relax/orient/merge via ae_backend)
├── geographic.py       # LIBRARY  ← vcm geographic.py (geo settings; rendering via geo-draw, #1)
├── chart_modifier.py   # LIBRARY  ← vcm chart_modifier.py (BASE ChartModifier + semantic styling)
├── stat.py             # LIBRARY  ← MY stat.py (ae_backend.hidb port; replaces vcm's hidb5-stat shell)
├── stat_tables.py      # LIBRARY  ← vcm stat.py's _make_tabs/_make_csv/_make_webpage (tabs/csv/html)
└── templates/
    ├── conference_data.py.template   # per-report definition (copy + edit per season)
    ├── h3_chart_modifier.py.template # per-season clade styling subclass skeleton
    ├── h1_chart_modifier.py.template
    ├── b_chart_modifier.py.template  # (b_chart_modifier is stable; ship as base + thin template)
    └── serology.py.template
```

Per-report files (`conference_data.py`, `serology.py`, `h1/h3_chart_modifier.py`) are
**not library** — they ship as documented templates; each report copies and edits them,
subclassing the `ae` base classes.

---

## Module-by-module migration

| vcm/v2 module | tier | → destination | notes |
|---|---|---|---|
| `latex.py` | library | `ae.report.latex` | port as-is; slow-moving engine |
| `commander.py` | library | `ae.report.commander` | rename `vcm.v2.*` imports → `ae.report.*` |
| `main_loop.py` | library | `ae.report.main_loop` | kateri task loop |
| `modules.py` | library | `ae.report.modules` | |
| `dirs.py` | library | `ae.report.dirs` | uses `$WHOCC_TABLES_DIR`; keep env-driven |
| `download.py` | library | `ae.report.download` | `ae_backend.chart_v3` relax/orient/merge |
| `geographic.py` | library | `ae.report.geographic` | geo *settings*; map render = `geo-draw` (#1) |
| `chart_modifier.py` (base) | library | `ae.report.chart_modifier` | base `ChartModifier`; uses `ae.semantic` |
| `b_chart_modifier.py` | library* | `ae.report.b_chart_modifier` | stable; treat as base + thin template |
| `stat.py` (compute) | **drop** | — | replaced by my `ae.report.stat` (no `hidb5-stat`) |
| `stat.py` (tabs/csv/html) | library | `ae.report.stat_tables` | split the non-compute half out |
| `h3_chart_modifier.py` | per-report | `templates/…` | season clades; subclass per report |
| `h1_chart_modifier.py` | per-report | `templates/…` | season clades |
| `serology.py` | per-report | `templates/…` | season serology antigens |
| `conference_data.py` | per-report | `templates/…` | the report definition |

`*` `b_chart_modifier.py` is stable today but is conceptually per-season (B clades change
less often); ship the class in `ae` and let reports override if needed.

### From `py/ae/report/` (mine)

| file | action |
|---|---|
| `stat.py`, `bin/ssm-report-stat` | **KEEP** — becomes the stat compute layer; wire vcm to it |
| `report.py`, `latex.py`, `templates/*.json`, `jsonio.py`, `labs.py`, `cli.py`, `init.py`, `bin/ssm-report`, `bin/ssm-report-init` | **REMOVE** (preserved on `report-shelved`) |
| `README.md` | rewrite for the vcm-based package |

---

## Stat integration (de-AD-ing)

vcm `stat.py:49` does:
```python
subprocess.check_call(f"hidb5-stat --start … --end … --db-dir … '{output}'", shell=True)
```
Replace with my Python port:
```python
from ae.report.stat import make_stat_json
make_stat_json(output=output, start=time_series.front_YMD(), end=time_series.after_last_YMD(), db_dir=hidb_dir)
```
This removes the dependency on the AD C++ `hidb5-stat` binary (which does not exist in an
ae-only install). My `stat.py` already produces the exact `{antigens,sera,sera_unique}`
structure vcm's tabs/csv/html and `latex` stat tables consume — verified against real
H1/H3 hidb. (⚠ B is currently skipped — open hidb-side B-load bug, `STRING_ERROR`.)

---

## Dependencies to resolve

- `ae_backend.chart_v3`, `ae.semantic`, `ae.utils.{kateri,time_series,org,datetime,traceback}`
  — **already in `ae`**. ✅
- `semantic_clades`, `semantic_vaccines` — data files in **`acmacs-data`**
  (`~/AC/eu/acmacs-data/`). Decide: vendor a copy, add as a data dependency, or resolve via
  an env var / config path. These carry the clade/vaccine reference data, updated out-of-band.
- `$WHOCC_TABLES_DIR`, `$HIDB_V5`, `$LOCDB_V2` — runtime env the tools already expect.

---

## Stage B — interactive map adjustment (ported to ae) — port plan

The per-map fine-tuning in each `<map>/adjust/0do` script (select outlier antigens, `move`,
`relax`, `procrustes`) runs on **AD `acmacs` + `acmacs_py.zero_do_5`**
(`AD/sources/acmacs-py/py/acmacs_py/zero_do_5.py`, 534 lines). This is the **one genuinely
AD-dependent piece** left in the whole report workflow (`download`/`prestyle`/`style`/`export`
are all ae now). Investigated — here is the port plan.

**What it is.** A **scripted** (not live-GUI) geometry editor: the analyst writes a `0do`
Python script (`slot.select_antigens(…inside(path)…)`, `slot.move(ags, to=[…])`, `slot.relax()`),
runs it, reviews a rendered snapshot, iterates. Output: `adjusted.ace`. `Slot` is a thin wrapper
— almost every method delegates to AD's **`acmacs.ChartDraw`** (chart manipulation + rendering).

**Operation inventory vs ae:**

| op | ae status |
|----|-----------|
| relax / grid / disconnect, procrustes, rotate, flip e-w/n-s, select(predicate), merge / orient_to / relax_chart / populate_from_seqdb, stress, modify styles | ✅ already in `ae_backend.chart_v3` / `ae.report.download` / `ae.semantic` |
| **move points to coords** | ❌ Layout is read-only (`__getitem__`, no `__setitem__`) |
| **geometric select (`figure` + `ag.inside`)** | ❌ but the predicate ctx exposes `point_no` and the layout is readable → Python point-in-polygon is feasible |
| **flip_over_line** | ❌ reflect points over a line (pure-Python geometry on layout) |
| render / snapshot | AD `ChartDraw` → in ae use **kateri** (review only; not needed to produce `adjusted.ace`) |

**The real gap is one primitive.** All three missing ops are geometry on the layout, and all
are enabled by **writing layout coordinates** (currently read-only). With a coordinate setter:
move = set selected coords + mark `unmovable` (the getter exists; needs a setter) + relax;
flip_over_line = reflect coords; geometric select = point-in-polygon over the layout via `point_no`.

**Recommended approach (two layers, mostly Python):**
1. ✅ **DONE — One small `chart_v3` primitive** (C++/pybind): a Layout/Projection coordinate
   **setter** + settable `unmovable`. Now exposed in `ae_backend.chart_v3`:
   `Projection.set_coordinates(point_no, [x,y])`, `Layout.__setitem__` (`layout[i] = [x,y]`,
   negative index counts from the end), and `Projection.set_unmovable([i, j])` (pins points so a
   subsequent `relax()` keeps them fixed). `Layout.__getitem__` (`layout[i]`) now also reads coords
   by index. So **both** the scripted-Python and kateri-centric designs are unblocked on the
   chart-engine side.
2. **A pure-Python `zero_do` port** (new `py/ae/zero_do/` or `py/ae/report/`): reimplement
   `Slot`/`Zd` (`move`/`flip`/`select-inside`/`relax`/`procrustes`/`final_ace`) on
   `ae_backend.chart_v3`; snapshots via **kateri** (optional — the core `adjusted.ace` output
   needs no renderer). No live-GUI editor required (workflow is scripted batch with review).

**Effort:** modest — the chart-engine ops mostly exist; the new work is the coordinate-setter
primitive (✅ now done — see above) + ~500-line thin-wrapper Python framework. The sole
chart-engine dependency (the `chart_v3` coordinate setter + settable `unmovable`) is **resolved**.

**↻ Final framing — build BOTH front-ends (they share one core).** kateri is built for
*interactive* editing (hover hit-test `pointLookupByCoordinates`, drag selection-region
vertices `dragStart`/`vertexMove`/`reportRegion`, return the edited chart `get_chart`) — it
just doesn't drag antigen **points** yet (`dragStart` only grabs region vertices). Earlier I
leaned "kateri-centric, the coordinate setter isn't needed." **That was too narrow.** As the
work shifts from manual to **Claude-agent-driven**, an interactive-only (drag) design is a step
*backwards* for automation — an agent doesn't drag in a GUI, it writes a script (exactly what the
AD `0do` files already are). So the right design is a **combination**, and both front-ends share
the same `ae_backend` core (now done):

```
          ┌─ interactive  : kateri drags a point → get_chart        ─┐
shared    │                  (needs a small Dart point-drag branch)  ├→ adjusted.ace
core ✅    └─ programmatic : ae.zero_do move/select/relax (Python)  ─┘
   primitives: Projection.set_coordinates / Layout.__setitem__  +  Projection.set_unmovable
```

- ✅ **Programmatic (agent-facing) — DONE.** [`py/ae/adjust.py`](../adjust.py) — `Adjust` class
  on `ae_backend.chart_v3`: `figure()` (polygon) + `select_antigens/sera(predicate)` with geometric
  `pt.inside(figure)`, `move`/`move_by`/`flip_over_line`, `pin`/`unpin_all`, `relax`, `stress`,
  `procrustes`, `save`. Built on the new coordinate setter + `set_unmovable`. **Verified** on
  synthetic `test/chart1.ace`: geometric selection correct; pinned points stay exactly through
  relax while others move; flip reflects correctly; save/reload + procrustes(self)=0. This is the
  AD `0do` workflow, scriptable: `select region → move → relax → save`. (kateri snapshots optional.)
- ✅ **Interactive (human-facing) — DONE, with live relax animation.** kateri drags antigen/serum
  points (it only *moves* them — no relax) and the ae-side glue is in place:
  [`ae.adjust.adjust_from_kateri`](../adjust.py), dispatched from the `RLAX` notification in
  [`Communicator.connected`](../utils/kateri.py) (`handle_relax`). When the operator presses "Relax",
  kateri sends a bare `RLAX`; the ae side then does `get_chart` (edited layout) →
  `Adjust.relax_capturing_intermediates` (**all points free**, no pinning) → subsample the
  optimiser's per-iteration layouts to ~40 frames → Procrustes/Kabsch-align each onto the pre-relax
  layout (so frames don't flip/fly off from the optimiser's arbitrary MDS gauge) → stream each as a
  `LAYT` frame (`{"l": coords, "final": bool}`, same framing as `CHRT`). kateri repaints each frame,
  **animating the relax**; the last frame is `"final": true` and commits the layout (no full `CHRT`
  needed for the result). **Nothing is pinned** — the dragged positions are only better *starting*
  coordinates that let the optimiser escape the local optimum. `Communicator.get_moved_points`
  remains **informational only** (not used by the relax flow).
  - **C++ support:** `ae_backend.chart_v3.Projection.relax_capturing_intermediates(rough=False)`
    (new pybind binding over the existing `optimize(chart, projection, IntermediateLayouts&, …)`
    overload) relaxes in place and returns the per-iteration `(coords, stress)` sequence.
  - **Verified.** Automated ([`test/adjust_from_kateri.py`](../../../test/adjust_from_kateri.py),
    fake transport): a multi-frame `LAYT` stream (last=final) over the real `connected()` loop,
    frame 0 anchored exactly at the operator's drag, dragged points move freely, stress falls to the
    known optimum, Kabsch keeps non-dragged points in their original frame. **Live against real
    kateri:** `RLAX`/`handle_relax` round-tripped `get_chart` with the running GUI and streamed 40
    `LAYT` frames (last=final) that kateri rendered without error.

The report engine already follows this both/and pattern elsewhere (programmatic `make_geo`/
`make_trees`/`make_stat` for agents; interactive `0do`/kateri for humans) — the adjust stage now
matches: **both front-ends are built** on the shared `ae_backend` core. The only residual call is
whether to retire the AD `acmacs_py.zero_do_5` path or keep it as a transition fallback.

---

## Build & reproducibility implications of the package name

The report is built by running per-map `0do` scripts (e.g. `./0do download`). Those
scripts **already** `import ae_backend`, `from ae.utils import kateri`, `from ae import
semantic` **and** `import vcm.v2.commander` / `from vcm.v2.h1_chart_modifier import
H1_ChartModifier`, then subclass the modifier for that map. So the report environment
already has both `ae` and the per-report `vcm` importable.

**Naming `py/ae/report/` (vs keeping `vcm`) — effect on building:**

- **Command UX is unchanged.** `download`/`prestyle`/`style`/`populate`/`export` come from
  `commander.py`'s `@command` decorator — package-name-independent. You still run
  `./0do <command>`.
- **Existing reports are unaffected.** Each old report dir keeps its frozen `py/vcm/` and
  stays reproducible as-is. Only *future* reports are wired against `ae.report`.
- **Import lines change** in new reports' scripts: `from vcm.v2.x import Y` →
  `from ae.report.x import Y` (one-time edit in the report skeleton).
- **Path setup gets simpler, not harder.** `import vcm.v2.*` only resolves today because
  each report carries `<report>/py/vcm/` and puts `<report>/py` on `sys.path`. The `0do`
  already imports `ae.*` successfully, so `ae.report` resolves with **no per-report copy and
  no extra path plumbing** — it rides the path the report scripts already use. (Argument in
  favour of the `ae.report` name.)
- **The subclassing pattern is identical**, just importing the base from `ae.report.*`.

**The real consideration is reproducibility, and it is independent of the name:**

- *Today:* each report freezes its whole `vcm/v2/` → re-running a 2024 report uses the exact
  library it shipped with.
- *After:* the library is shared in `ae` → re-running an old report uses **whatever `ae` is
  checked out**, so engine changes can alter or break an old build.
- **Nuance / mitigation:** the `0do` scripts *already* depend on unpinned, shared
  `ae_backend` / `ae.utils` / `ae.semantic`, so reports are *already* reproducible only
  against a given `ae` version. Moving the report engine into `ae.report` extends that; it
  does not create a new failure mode. The clean fix is a **process** one: **record the `ae`
  git SHA in each report dir** (the report already pins its per-season config — pin the
  engine version too). This is orthogonal to whether the package is `report` or `vcm`.

**Recommendation:** `ae.report` — the name is free after Phase 3, matches TODO #4 and
`bin/ssm-report*`, and rides the already-imported `ae` path. Only keep the `vcm` name
(`ae.vcm`) if preserving that identity matters more than consistency; the build effort is the
same either way.

---

## Phased plan

- [x] **Phase 0 — preserve.** Branch `report-shelved` from `ad-port` HEAD, pushed to
      `drserajames` (`503e8c3`). All AD-faithful report work recoverable.
- [x] **Phase 1a — decoupled engine.** Landed `latex`, `dirs`, `main_loop`, `modules`,
      `download`, `stat_tables` (`vcm.v2.*`→`ae.report.*`); removed the AD-faithful assembler
      stack (`report.py`/`cli.py`/`jsonio.py`/`labs.py`/`bin/ssm-report` — on `report-shelved`);
      kept `stat.py`. All import clean (Py3.10 + `ae_backend`).
- [x] **Phase 1b — ConferenceData-coupled engine.** Landed `chart_modifier`, `geographic`,
      `commander` + a thin `conference_data_base.ConferenceData(VcmDirs)` base. `chart_modifier`
      inherits the base; `make_geo` takes an injected ConferenceData; `semantic_clades`/
      `semantic_vaccines`/`serology` are guarded imports so `ae.report` imports standalone.
      Per-report adaptation: the report's concrete `conference_data.py` subclasses
      `ae.report.conference_data_base.ConferenceData`. (`conference_data.py`, `serology.py`,
      subtype modifiers stay per-report.)
- [x] **Phase 2 — de-AD the stat path.** `stat_tables._compute_stat` now calls
      `ae.report.stat.make_stat_json` (`ae_backend.hidb` + `locdb_v3`) instead of shelling
      `hidb5-stat`. **✅ Verified:** `make_stat` over real hidb produces `stat.json.xz` +
      per-lab/subtype `*-tab.txt` + `stat.csv` + `index.html`, no AD/C++ binary.
- [x] **Phase 3 — removed the remaining AD scaffolding** (`init.py`, `templates/`,
      `bin/ssm-report-init`) and refreshed `README.md`. `ae.report` is now just the engine.
- [x] **End-to-end validated.** Real `2026-0119-tc2/h1-cdc` chart + adapted per-report classes:
      `populate_for_style()` ran the full `ae.report.chart_modifier` styling (clades/vaccines/
      serology via `ae.semantic`) and `ae.utils.kateri` drove kateri to export a styled
      `clades` map — a 1-page 800×800 PDF **visually identical to the known-good
      `out.1.clades.pdf`**. Surfaced + fixed a kateri-launcher bug (symlink → `@executable_path`
      framework-load failure) in `ae.utils.kateri`. Per-report adaptation: the subtype modifier
      mixes in the concrete `ConferenceData` (`class H1_ChartModifier(ChartModifier, ConferenceData)`).
- [x] **Geographic wired to `geo-draw`.** `geographic.make_geo` extracts per-month
      `{location, count}` from hidb, writes geo-draw's `--data` records JSON, and renders
      `<geo_dir>/<subtype>-<YYYY-MM>.pdf` (continent-coloured, count-sized). Decoupled from
      `ConferenceData`. **✅ Verified** on real H3 hidb.
- [x] **Geographic clade/lineage colouring — BUILT + VERIFIED 2026-06-14.** Two paths landed on
      `geo-draw`: (a) a **clade pie** mode (`color_by="clade"`: wedges per clade, stable palette +
      legend; `CairoPdf::sector` + `GeoWedge`/`LegendEntry`) — built, synthetic-verified; and (b)
      the **report-faithful `color_by="coloring"`** mode that consumes the report's
      `geographic_coloring(subtype)` aa/clade `apply` rules (`_Coloring` = port of AD
      `ColoringByAminoAcid`; seqdb `SequenceAA.matches_all`) and renders AD-style packed per-antigen
      dots (concentric-ring packing; per-point `outline_width`; `circle()` no-stroke on
      transparent). **✅ Verified** on real H1 hidb (clade palette correct, packed clusters,
      month-name title) — this closes [gap #1](#gap-analysis-2026-0223-capstone-attempt). Continent
      + pie modes unaffected.
- [x] **Trees wired to `tal-draw`.** `trees.make_trees` translates the report's settings-v3
      `.tal` (`ae.tal.settings_v3`) → tal-draw schema and renders the tree `.tjz` → the embedded
      `<subtype>.pdf` (replaces AD `tal -s …`). **✅ Verified** on a real H1 report tree (88 k
      leaves, clades, time-series). A few `.tal` features the translator skips are TAL follow-ups;
      signature-page composition is `bin/tal-signature-page` (TAL).
- [x] **Adjust stage (Stage B), incl. live relax animation.** kateri point-dragging + ae-side
      free-relax glue (`ae.adjust.adjust_from_kateri`, dispatched from the `RLAX` notification) — both
      front-ends done. Drags are starting seeds, not pins; all points relax freely. The relax now
      **animates**: `Projection.relax_capturing_intermediates` (new pybind binding) feeds the
      optimiser's per-iteration layouts, which are Kabsch-aligned and streamed as `LAYT` frames to
      kateri (last=final commits). Verified automated + live against real kateri (see Stage B above).
- [ ] **Remaining (see [gap analysis](#gap-analysis-2026-0223-capstone-attempt)):**
      (1) ✅ **DONE** — `ae.report.geographic` consumes `geographic_coloring` (clade/aa `apply`
      rules), built + verified on real H1 hidb; (2) ⚠ **DIFFED** — tree `.tal` fidelity assessed
      vs real bvic/h3 `.tal`: report glue works, but 6 TAL-subsystem rendering/translation gaps
      (canvas width, `draw-aa-transitions` labels, clade-coloured matrix, legend, geo inset, edge
      colour) — handed to TAL (TODO #3; a TAL agent has landed canvas/edge/matrix/nit fixes,
      build+verify pending); (3) ✅ **DONE** — per-report glue (2 files, 3 edits) applied to a copy
      of the real `2026-0223-ssm`; (4) ✅ **DONE (capstone)** — full assembled-report run on
      `ae.report` → 36-page `report.pdf` visually identical to the AD/vcm reference.
      **Remaining:** from-scratch figure regeneration on ae (current hidb + kateri maps + TAL tree
      fidelity + per-map `style`/`export` rewiring) — a larger, separate effort beyond the
      assembled-report milestone.

---

## Verification strategy

- **Library import:** `import ae.report` clean on Python 3.10 (needs `ae_backend`).
- **Stat:** already verified (cross-product invariants + LaTeX render) on real H1/H3.
- **End-to-end:** take a recent report dir (e.g. `2026-0119-tc2`), point its
  `conference_data.py` at the `ae.report` library, run `commander` `download`→`populate`→
  `style`→`export`, and confirm it reproduces the known-good PDFs. Requires the `kateri`
  executable, `$HIDB_V5`/`$LOCDB_V2`/`$WHOCC_TABLES_DIR`, and (for trees/geo) TAL `tal-draw`
  + the `geo-draw` renderer (#1).

---

## Open decisions (for the owner)

1. **Package name:** `py/ae/report/` (recommended) vs `py/ae/vcm/`.
2. **`acmacs-data` deps** (`semantic_clades`/`semantic_vaccines`): vendor, data-dep, or env path?
3. **Template strategy** for the per-report files: `.template` files vs a `report-skeleton/`
   dir a report copies wholesale.
4. **Ownership/sequencing:** this crosses into the team's live workflow code — confirm the
   `2026-0119-tc2` vcm is canonical before copying, and that no newer in-flight vcm exists.
5. **Phase 4 (`zero_do` / adjust)**: ✅ **landed** — the adjust stage is now ported to ae, no AD
   dependency. Both front-ends are done on `ae_backend.chart_v3`: programmatic ([`Adjust`](../adjust.py),
   the scriptable `0do` workflow) and interactive (kateri point-drag → `RLAX` → `handle_relax` →
   [`adjust_from_kateri`](../adjust.py), free relax + re-orient + push-back). See [Stage B](#stage-b--interactive-map-adjustment-ported-to-ae--port-plan).
   Residual decision is narrower: **retire the AD `acmacs_py.zero_do_5` path entirely, or keep it as
   a fallback during the transition?**
