# Signature pages (tree + per-section antigenic maps)

ae-native reproduction of AD's `sigp` signature page: a phylogenetic **tree** on the
left and, on the right, **one antigenic map per shown horizontal tree section
(hz_section)**, each highlighting that section's antigens (coloured by date) and sera
over a greyed base map, captioned `"{prefix}. {label} {aa-transitions}"`.

AD draws the whole thing on one Cairo canvas (`acmacs-tal` `AntigenicMaps`, driven by
`ssm_report/signature_page.py`). ae has **no single-canvas renderer** (the tree is drawn
by the `tal-draw` C++ binary; antigenic maps by **kateri**, a separate Dart app), so the
signature page is composited at the **PDF level**. The section↔map coupling — the thing
that makes this a real signature page rather than two pasted panels — is reproduced in the
orchestration layer.

## Code

| Piece | File |
|-------|------|
| Coupling: hz-section parse, leaf↔chart matching, per-section antigen/sera, viridis date gradient, semantic styles | `py/ae/tal/section_maps.py` |
| Engine: render tree (tal-draw) + section maps (kateri) + compose grid | `py/ae/tal/signature_page.py` (`make_section_signature_page`, `render_section_maps_via_kateri`) |
| Engine CLI | `bin/tal-signature-page` (section mode triggers on `--tal` + `--chart`) |
| Report driver (loops per lab-subtype) | `py/ae/report/signature_page.py` |

## Single documented command

Needs: the **kateri** app on `PATH`, and the **arm64** Python that imports `ae_backend`
(the default Homebrew `python3` 3.14 with `build/` → `build-py314/`). The signature-page
path is pure-stdlib on the Python side — no numpy needed.

```bash
cd <your ae checkout>
source ae-env.sh            # sets PYTHONPATH -> build/ + py/

# Engine — one signature page from a tree + chart + .tal:
python3 bin/tal-signature-page \
    --tal   <report>/tree/h1.after-2021.tal \
    --chart <report>/h1-cdc/styled.ace \
    --page-title "A(H1N1) HI CDC" \
    <report>/tree/h1.asr.after-2021.tjz \
    /tmp/h1-cdc.sigp.pdf
```

```bash
# Report driver — all (or selected) per-lab pages for a seasonal-report dir:
python3 -m ae.report.signature_page <report> --list            # show discovered prefixes
python3 -m ae.report.signature_page <report> --prefix h1-cdc   # one
python3 -m ae.report.signature_page <report>                   # all discovered
```

> The driver writes to **`<report>/sp/pdfs-ae/`** by default — deliberately *not*
> `sp/pdfs/`, which holds the AD `sigp` reference PDFs of the same name. Pass
> `--output-subdir sp/pdfs` only when intentionally replacing the AD references.

`<report>` here is e.g. `ac/results/ssm/2026-0223-ssm`. Verified end-to-end on real
**H1+CDC**, **H3+HINT+CDC**, and **B/Vic+Crick** inputs.

## How the coupling works (faithful to AD)

1. **Parse the shown hz-sections** from the `.tal` (`{id, prefix(L), first, last, label,
   aa_transitions}`) and the **time-series window** (`start`/`end`).
2. **Leaf order** comes from `tal-draw <tree> out.names` — the draw-order leaf seq_ids,
   ladderized to match the rendered tree (so the section `[first,last]` ranges are the
   same contiguous ranges AD bounds).
3. **Match leaves → chart antigens/sera** by name (strip the subtype prefix; key on
   `LOCATION/ISOLATE/YEAR`). A section's antigens = matched antigens on leaves in
   `[first,last]` (AD `Tree::chart_antigens_in_section`); its sera = sera whose *first*
   owning leaf is in the range (AD's front()-node dedup, so a serum's circle appears on
   one map only).
4. **Date colour** = AD's `time-series-color-scale`: a quadratic-Bezier viridis gradient
   (`#440154 → #40ffff → #fde725`) over the month slots of the time-series window. Ported
   bit-for-bit from `acmacs::color::bezier_gradient` (`section_maps.bezier_gradient`).
   An antigen's date picks its slot colour; dates outside the window stay grey.
5. **Per-section semantic style**: grey the whole map, then for the section's antigens add
   outline+raise emphasis and fill-by-date, and draw its sera. Selection uses what kateri's
   resolver supports (`plot_spec.dart`): a per-section boolean attribute `sg{i}`/`ss{i}`
   (one key per section, so an antigen in nested clades belongs to several) ANDed with
   kateri's `!D` date-range selector for the month colour. kateri renders each style by
   name (`set_style`) in one session.
6. **Compose**: tree (left) + an R×C grid of captioned maps (right) via `pdflatex`, laid
   out **3 rows** high (`columns = ceil(n_sections / 3)`), as AD does.

## AD-fidelity pass (2026-06-22)

A round of visual diffing against the AD `sigp` reference (`sp/pdfs/<prefix>.…sp.pdf`)
drove these fixes, mapped to AD's `conf/tal.json` `layout-with-maps` spec:

| # | Issue | Fix | Layer |
|---|-------|-----|-------|
| 1 | Clade labels on wrong side | Draw the clades column **left** of the time-series matrix (`clades_before_time_series`; AD `layout-with-maps` vs `layout-tree-only`) | `draw-tree.cc` |
| 2 | hz-section letters + grey "in map" dash | Render section letters **A/B/C** + brackets in a right-edge column (`hz_section_labels`); add the grey `matches-chart-antigen` dash-bar (`#808080`) from the matched-leaf list | `draw-tree.cc` |
| 3 | Text between maps | Titles drawn inside each map (kateri `plot_title`); composite draws no captions | `signature_page.py` |
| 4 | Section letter/clade title too big | Map title → 16px Helvetica | `section_maps.py` |
| 5 | Missing black map border | Frame each map cell in a 0.5pt black box (kateri draws none) | `compose_grid` |
| 6 | Gridlines too light | Darken kateri's grid default `0xFFCCCCCC → 0xFFB0B0B0` (renders ~grey 204, matching AD) | kateri `draw_on_pdf.dart` + `draw_on_canvas.dart` |
| 7 | aa colour bar present | Drop the aa `dash-bar-aa-at` columns from the sig-page tree (AD disables them) | `signature_page.py` |
| 8 | Fonts | Helvetica/sans for composite + map titles; title drawn top-left by the tree (like AD) | `compose_grid` + `section_maps.py` |

The two layouts (`clades_before_time_series`, `hz_section_labels`, the grey dash, and the
aa-column drop) are **flag-gated**, so tree-only rendering is unchanged.

### Second fidelity pass (2026-06-22)

A closer diff against the AD codebase (`conf/tal.json` `antigenic-map-reset`, `hz-sections.cc`,
`ssm-report/signature_page.py`) drove:

- **AD map point sizes** (`section_maps.py`): all points light grey **grey88** with a **white
  outline** (no visible border); in-tree antigens **gray63**; in-section antigens small with a
  black outline; **vaccine marks small (≈15) with small labels (≈9)** — redrawn from the chart's
  `-vaccines` data (colours + label text) rather than inheriting the report's 40/30. Fixes the
  "antigens in white", oversized-points and oversized-vaccine feedback.
- **hz-section letters A, B, C…** assigned in **tree (draw) order** (AD `HzSections::set_prefix`,
  not the `.tal` "L"), used for both the markers and the map titles (`assign_prefixes`).
- **hz bracket direction** (`draw-tree.cc`): "]" with the spine on the right and arms extending
  **left** toward the matrix (AD `HzSectionMarker::draw`); the letter sits centred over a small
  white box.
- Tree fills slightly more height (reduced top/bottom margin).

Serum circles: AD's sig-page map removes them (`serum-circles-remove`), so they're **off by
default**. Opt in with **`tal-signature-page --serum-circles [--serum-circle-fold N]`** (or
`make_section_signature_page(..., serum_circles=True)`): each section's sera get their empirical
circle (passage-type coloured — cell blue / egg red / reassortant orange, via
`semantic.serum_circle`), with the serum point drawn dark so the centre is visible.

### hz-section marker column restored (2026-09-14)

The bracket + section-letter column described above was **drawing nothing** on every real
signature page — the page rendered the clade arrow labels but no `A`/`B`/`C` keys tying each
map panel to its section, which is easy to mistake for "the feature is there".

Cause was upstream of `draw-tree.cc`, whose marker block is gated on
`!params.hz_sections.empty()`. That list is filled from the tal-draw schema's `hz_sections`,
and `settings_v3.translate` only fills it from an `hz-sections` command the `.tal`'s program
actually RUNS. No report `.tal` from 2026-0805-tc1 on runs one: they keep the block but dropped
the `hz` sub-program, so `find_command` correctly ignores it and the list came out empty — while
`hz_section_labels` still reserved the column's 2.8 % of width. `_tal_to_settings` now takes
`hz_sections=` and writes the sections the page is really built from (`SM.sections_for`, the
clade-derived fallback AD itself uses), which is the authoritative list in either case.

Measured — single-letter text-show ops in the PDF content stream, clustered by x
(`pdftotext -bbox` is not enough on its own: it silently drops bare `I` glyphs, undercounting
both engines by one). ae rendered from `2026-0921-ssm`, AD reference from `2026-0223-ssm/sp`:

| page | AD column | ae before | ae after |
|---|---|---|---|
| `h3-hint-cdc` | 11 letters `A`–`K` @ x≈367 | **none** | 9 letters `A`–`I` @ x≈361 |
| `h1-cdc` | 6 letters `A`–`F` @ x≈429 | **none** | 13 letters `A`–`M` @ x≈416 |
| `bvic-cdc` | 8 letters `A`–`H` @ x≈315 | **none** | 10 letters `A`–`J` @ x≈396 |

All three subtypes had the same gap. The letter *counts* differ from AD because the section
SETS differ — AD's reference is Feb 2026's hand-curated `.tal` splits, ae's are the current
tree's clade-derived sections — not because letters are missing: each page's column matches the
`L` field of its own run's `>>> HZ sections` dump exactly (9 / 13 / 10), in order. Each letter
sits at its own section's first-leaf row: Pearson *r* between first-leaf draw index and letter
y = **0.999999 / 1.000000 / 0.999999**, strictly monotonic in all three.

Locked in by `cc/tal/test/test-sigpage-hz-marker.py` (synthetic `.tal` + section list).

### Checking
`python3 cc/tal/test/check-sigpage.py <ae.pdf> [<AD-reference.pdf>]` emits an AD-vs-ae
montage (eyeball #1/#2/#3/#4/#8) plus automated probes for the data-independent items
(#5 border, #6 gridline grey, #7 no aa legend, map-title size). Run against the AD
reference `sp/pdfs/<prefix>.…sp.pdf` (the style/layout is data-independent, so the stale
reference is a valid target for these).

### Remaining (data-driven, not defects)
- **Map count / grid columns** track the current `.tal`'s shown hz-sections (e.g. H1 = 6 → 2×3
  vs the 2025 reference's 9 → 3×3).
- **Date-colour skew** (ours bluer, AD greener) follows the `.tal` time-series window.
- **Page aspect** is A4 landscape; AD's page is wider.

## What matches AD

- Tree panel: rendered by `tal-draw` from the same `.tal` (continent-coloured time-series
  matrix, geo inset, clade-label column, hz-section brackets) — report-tree fidelity was
  already matched (TODO #3).
- Per-section maps: same section membership, same date colouring scheme/scale, sera per
  section, titles `"{prefix}. {label} {aa}"`, 3-row grid.

## Fidelity gaps (composite vs AD's single canvas)

- **Name matching is strain-based**, not seqdb `hi_names`. AD matches each leaf to chart
  antigens via the seqdb's full alternate-name set (egg/cell/reassortant variants); ae keys
  on `LOCATION/ISOLATE/YEAR` after stripping the subtype. Counts are close but not identical
  — a passage/reassortant variant named differently in the chart vs the tree can be missed.
- **Serum→section dedup** uses the first owning leaf in draw order; AD ranks candidate leaves
  by passage/reassortant match quality before taking the front. Differs only for sera that
  match multiple leaves across sections.
- **Viewport**: the section maps pass **no** viewport and let **kateri auto-fit/centre** each
  map, so the antigen cluster fills the cell like AD. (The chart's `-reset` viewport is
  off-centre for sig pages, and AD's `sp.mapi` viewport is in AD's *oriented* coordinate frame
  — the chart kateri receives is un-oriented, so that viewport leaves the map empty. Verified
  apples-to-apples: auto-fit frames the map like AD's.)
- **Section count / grid columns** differ from a given AD reference PDF when the `.tal` has
  evolved (e.g. current H1 `.tal` = 6 shown sections → 2×3; the 2025 reference had 9 → 3×3).
  This is correct for the current data, not a coupling defect.
- **Composite, not one canvas**: maps are independent kateri PDFs tiled by `pdflatex`. AD
  also draws each section map independently, so the only real loss is pixel-exact placement/
  margins — the per-map content + colouring is faithful.

## Comparison artifacts

Side-by-side AD-vs-ae renders are **not committed** (they embed real strain names / maps).
Regenerate locally by rendering `<report>/sp/<prefix>.…sp.pdf` (AD) next to the ae output.

## Build note

`ae_backend` + `tal-draw` are built for Python 3.14 at `build-py314/` (`build/` → it). The
py3.10 `build-arm64/` fallback was retired on 18 Sep 2026; note that **iterating tree
leaves in Python traps under the 3.14 build's libc++ hardening** on a non-UTF-8 leaf name —
the orchestration avoids this by reading draw-order names from `tal-draw`'s `.names` output
rather than iterating the tree in Python.
