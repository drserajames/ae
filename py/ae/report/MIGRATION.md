# ssm-report → ae: vcm consolidation migration plan

Status: **planning** (Phase 0 done). This document is the agreed plan for retiring
the AD-faithful `py/ae/report/` port and bringing the team's actual ae-based report
tooling (`vcm`) into the `ae` repo. Read this before touching report code.

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
in the report workflow is the interactive map-adjustment `0do`/`zero_do` framework (see
[Stage B](#stage-b--interactive-map-adjustment-still-ad)).

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
| Interactive adjustment | — | — (`adjust/0do` scripts) | **still AD** |

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

## Stage B — interactive map adjustment (still AD)

The per-map fine-tuning in each `<map>/adjust/0do` script (select outlier antigens, `move`,
`relax`, `procrustes`) runs on **AD `acmacs` + `acmacs_py.zero_do_5`**
(`AD/sources/acmacs-py/py/acmacs_py/zero_do_5.py`). vcm does *programmatic* relax/orient via
`ae_backend`, but the *interactive by-hand* adjustment has **not** moved to `ae`. Porting
`zero_do` onto `ae_backend` + kateri is the one genuinely-unstarted piece and a sizable
effort of its own — **out of scope for this consolidation; track separately.**

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
- [ ] **Phase 1 — bring vcm library tier into `ae`.** Copy the library modules from
      `2026-0119-tc2/py/vcm/v2`, rename `vcm.v2.*` → `ae.report.*`, split `stat.py`'s
      tabs/csv/html into `stat_tables.py`, resolve `semantic_clades`/`semantic_vaccines`.
      Ship per-report files as `templates/`.
- [ ] **Phase 2 — de-AD the stat path.** Point vcm stat at `ae.report.stat.make_stat_json`.
- [ ] **Phase 3 — remove the AD-faithful port** from `ad-port` (keep `stat.py` +
      `bin/ssm-report-stat`); rewrite `README.md`.
- [ ] **Phase 4 — (separate) port `zero_do`** interactive adjustment AD→ae.

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
5. **Phase 4 (`zero_do`)**: schedule as its own subsystem, or leave on AD indefinitely?
