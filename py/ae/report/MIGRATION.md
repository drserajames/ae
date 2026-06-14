# ssm-report → ae: vcm consolidation migration plan

Status: **largely done.** Phases 0–3 + 1b complete: the AD-faithful `py/ae/report/`
port was shelved (branch `report-shelved`) and the team's ae-based report engine
(`vcm`) is consolidated into `py/ae/report/`. All four figure families generate on ae
(kateri antigenic maps · `stat`/`stat_tables` · `geo-draw` geographic · `tal-draw`
trees), the adjust stage is ported (`ae.adjust` programmatic + kateri point-drag
interactive), and a bootstrap `skeleton/` exists. **Remaining:** a full assembled-report
end-to-end run, and geo clade/lineage colouring (geo-draw pies, owned by map-draw #1).
This document records the plan and the as-built decisions. Read it before touching
report code. (Sections below are kept as the historical plan + rationale.)

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
- ✅ **Interactive (human-facing) — DONE.** kateri now drags antigen/serum points (it only
  *moves* them — no relax) and the ae-side glue is in place:
  [`ae.adjust.adjust_from_kateri`](../adjust.py), dispatched from the new `RLAX` notification in
  [`Communicator.connected`](../utils/kateri.py) (`handle_relax`). When the operator presses
  "Relax", kateri sends a bare `RLAX`; the ae side then does `get_chart` (edited layout) →
  `Adjust.relax` with **all points free** → `Adjust.orient_to` the pre-relax layout (procrustes; so
  the map doesn't flip/rotate from MDS reorientation) → `send_chart` back to kateri + optional
  `.ace` write. **Nothing is pinned** — the dragged positions are only better *starting* coordinates
  that let the optimiser escape the local optimum it was trapped in, so all points (including the
  dragged ones) settle freely. `Communicator.get_moved_points` remains as **informational reporting
  only** (not used by the relax flow). **Verified** on synthetic `test/chart1.ace`
  ([`test/adjust_from_kateri.py`](../../../test/adjust_from_kateri.py), fake transport): free relax
  lowers the perturbed-layout stress to the known optimum, the dragged points move (not held fixed),
  re-orient undoes a known reflection, the relaxed chart is pushed back, `get_moved_points`
  round-trips, and the full `RLAX` notification round trip works through the real `connected()` loop.
  - **Future enhancement — live relax animation (not built).** The GUI currently shows one jump
    from dragged → relaxed because `relax()` is a single blocking `ae_backend` call returning only
    the final layout. Animating the optimization would require `ae_backend` to expose intermediate
    layouts (a per-iteration / periodic callback); the glue would stream each as its own
    `send_chart` (`CHRT`) frame. kateri needs no change — every `CHRT` already repaints.

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
- [x] **Geographic wired to `geo-draw`.** `geographic.make_geo` now extracts per-month
      `{location, count}` from hidb, writes geo-draw's `--data` records JSON, and renders
      `<geo_dir>/<subtype>-<YYYY-MM>.pdf` (continent-coloured, count-sized). Decoupled from
      `ConferenceData`. **✅ Verified** on real H3 hidb. (Clade/lineage colouring awaits
      geo-draw pies — continent colouring works now.)
- [x] **Trees wired to `tal-draw`.** `trees.make_trees` translates the report's settings-v3
      `.tal` (`ae.tal.settings_v3`) → tal-draw schema and renders the tree `.tjz` → the embedded
      `<subtype>.pdf` (replaces AD `tal -s …`). **✅ Verified** on a real H1 report tree (88 k
      leaves, clades, time-series). A few `.tal` features the translator skips are TAL follow-ups;
      signature-page composition is `bin/tal-signature-page` (TAL).
- [x] **Adjust stage (Stage B).** kateri point-dragging + ae-side free-relax glue
      (`ae.adjust.adjust_from_kateri`, dispatched from the `RLAX` notification) — both front-ends
      done. Drags are starting seeds, not pins; all points relax freely. Possible future
      enhancement: live relax animation (needs an `ae_backend` intermediate-layout callback — see
      Stage B above).
- [ ] **Remaining:** geo clade/lineage colouring (geo-draw pies, map-draw); TAL `.tal`
      translation fidelity (TAL); optional per-report skeleton.

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
