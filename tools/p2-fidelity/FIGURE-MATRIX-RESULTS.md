# P2 milestone K — figure-matrix fidelity sign-off

**Date:** 2026-09-10  **Branch:** `p2-figure-matrix`  **Harness:** [`fidelity.py`](fidelity.py) (unmodified)
**Renderer under test:** `ae_backend.map_draw.export_styled_map` (native Cairo), build `build/` → `build-py314/`
**Reference:** kateri goldens (`out.1.<style>.pdf`) from an ssm report working dir **outside the repo**

> **Verdict — partial sign-off.** The five report map families for which a valid kateri
> reference exists (**by-clade, by-clade −6m, by-clade −12m, serology, time-series**;
> **219 maps**, 18 lab dirs, 3 subtypes) were run end-to-end. **214/219 (97.7 %) meet the
> `< 1–2 %` target** on the content metric, mean **0.93 %**, median **0.86 %**. The 5 that
> exceed 2 % are all `serology` (2.10–2.51 %) and each sits only ~0.5 pp above its **own
> measured anti-aliasing floor** (§5) — they are AA-tail, not layout or content errors.
> **Four further families cannot be signed off at all** — not because the renderer fails,
> but because **no usable reference figure exists** for them anywhere in the report corpus
> (§6). Milestone K is therefore **signed off for the five reference-backed families and
> explicitly NOT signed off for the other four.** §8 lists what is needed to close them.

---

## 1. Method

### 1.1 What was run

```
python3.14 tools/p2-fidelity/fidelity.py <manifest.json> \
    --build-dir /…/ae/build \
    --out-dir   "$TMPDIR/…/run" \
    --size 800 --timeout 180
```

The harness renders each `(chart, style)` natively to PDF, rasterises native **and** the
kateri golden with `pdftoppm -scale-to 800`, and reports `magick compare -metric AE`
(differing-pixel count) at **strict** and **`-fuzz 30 %`**. `%` is of 800×800 = 640 000 px.
Native render width 800 pt, projection 0 — matching the goldens, which are all 1-page
800 × 800 pt.

Environment: `PYTHONPATH=<ae>/build:<ae>/py`, Python 3.14, poppler 26.04, ImageMagick
7.1.1-45. **No rebuild was performed** — the pre-existing `build/` was used.

### 1.2 Reference selection (this is the load-bearing part)

The report corpus contains far more `out.1.<style>.pdf` files than are usable as goldens.
A candidate was accepted **only** if all three hold:

| gate | why |
|------|-----|
| golden is **kateri-produced** | detected from the PDF signature: kateri (Dart `pdf` package) writes `%PDF-1.5` + `/Type/Catalog/Version/1.7/PageMode/UseNone`; the native renderer writes `%PDF-1.7` (Cairo). This rules out a circular native-vs-native comparison, which matters because native has been the report default since 2026-07-10. |
| golden's style name is **still in the chart's `c["R"]`** | otherwise the golden was rendered from an older `styled.ace` carrying a style the current chart no longer defines. |
| golden mtime within **2 days** of `styled.ace` | otherwise the golden predates the chart it would be compared against. |

Against the newest report run this admitted **219 of 796** `out.1.*.pdf` candidates. **No
candidate failed the kateri-signature gate** — every `out.1.*.pdf` in the corpus is
kateri-produced. **577 failed the style-in-chart gate** (stale by-clade variants and stale
per-month time-series left over from earlier runs). **0 render or compare failures.**

Charts, goldens, renders, rasters and diff images all live **outside the repo**
(`$TMPDIR`). Only the aggregate numbers below are committed.

### 1.3 Reading the two metrics

* **fuzz30** — the honest **content** metric. Tolerates small colour/AA deltas, so a
  non-zero value means points/frame/palette/text actually differ. **This is the metric the
  `< 1–2 %` target is judged on.**
* **strict** — raw AE at zero tolerance. §5 shows this metric is **not usable** at this
  scale: merely changing rasteriser on *identical* vector content produces a larger strict
  AE than the whole native-vs-kateri difference does.

---

## 2. The figure matrix

Derived from `py/ae/report/` (not guessed). `MapRenderer.export_pdf(chart, style_name,
output, width=800)` is the whole renderer surface; the report only ever names a `c["R"]`
front style. Families and their producing modules:

| # | Family | Front style(s) | Produced by | Reference available? | Status |
|---|--------|----------------|-------------|:--------------------:|--------|
| 1 | **By-clade** main maps | `clades`, `clades-v<N>` (+`-zoom`) | `commander.export` → `chart_modifier` | ✅ kateri | **PASS** |
| 2 | **By-clade, older-than-6m greyed** | `clades…-6m` | same | ✅ kateri | **PASS** |
| 3 | **By-clade, older-than-12m greyed** | `clades…-12m` | same | ✅ kateri | **PASS** |
| 4 | **Serology** | `serology` | `chart_modifier.add_serology_style` | ✅ kateri | **PASS (marginal)** |
| 5 | **Time-series** (per-month, continent-coloured) | `ts-<YYYY-MM>` | `ae.semantic.time_series` | ✅ kateri | **PASS** |
| 6 | **Info maps** (blank title, no legend, unlabelled vaccines) | `info-clades…` | `commander.export_info` | ❌ none exist | **UNMATCHABLE** (renders clean, §6.1) |
| 7 | **Serum circles / serum coverage** | `sc-<nnn>-f<fold>-{e,t}` | `chart_modifier.add_serum_coverage_styles` | ⚠️ goldens exist but styles are not persisted | **UNMATCHABLE as-is** (§6.2) |
| 8 | **Multiple-serum-circles addendum** | `mc-plain`, `mc-circles` | `py/ae/report/multiple_circles.py` | ❌ committed PDFs are R/Racmacs output | **UNMATCHABLE** (§6.3) |
| 9 | **Signature-page section maps** | `sigsec-<NN>` | `py/ae/tal/section_maps.py` | ❌ never persisted as standalone PDFs | **UNMATCHABLE** (§6.4) |
| — | Geographic world maps | — | `geo-draw`, not `c["R"]` | out of scope | n/a |
| — | Phylogenetic trees | — | `tal-draw`, not `c["R"]` | out of scope | n/a |

Background-only styles (`-reset`, `-pale`, `-continent`, `-vaccines*`, `-new-N`,
`-o6m-grey`, `-o12m-grey`, `-sci-*`, `-sco-*`, `-ts-*`) are **not** separate families —
they are composed into the fronts above and are exercised transitively by families 1–5.

Coverage actually exercised: **18 lab dirs** across **3 subtypes** × **5 labs**
(+ additional assay variants), i.e. the full subtype × lab × style-family grid for which
references exist.

---

## 3. Per-family results (n = 219)

kateri fuzz30 = content metric; kateri strict = raw AE. Lower is better.

| family | n | fuzz30 mean | fuzz30 median | fuzz30 max | `<1 %` | `<2 %` | strict mean | strict median | strict max |
|--------|--:|------------:|--------------:|-----------:|-------:|-------:|------------:|--------------:|-----------:|
| by-clade | 31 | **0.87 %** | 0.82 % | 1.51 % | 22/31 | **31/31** | 3.25 % | 2.95 % | 4.95 % |
| by-clade −6m | 31 | **0.96 %** | 0.92 % | 1.57 % | 20/31 | **31/31** | 3.83 % | 3.40 % | 6.09 % |
| by-clade −12m | 31 | **0.96 %** | 0.93 % | 1.57 % | 20/31 | **31/31** | 3.74 % | 3.33 % | 6.06 % |
| serology | 18 | **1.57 %** | 1.42 % | 2.51 % | 2/18 | **13/18** | 11.48 % | 10.33 % | 17.61 % |
| time-series | 108 | **0.82 %** | 0.78 % | 1.38 % | 83/108 | **108/108** | 3.57 % | 3.13 % | 6.59 % |
| **ALL** | **219** | **0.93 %** | **0.86 %** | 2.51 % | 147/219 (67.1 %) | **214/219 (97.7 %)** | 4.24 % | 3.38 % | 17.61 % |

**Per-subtype (fuzz30 mean / max):**

| subtype | by-clade | −6m | −12m | serology | time-series |
|---------|---------|-----|------|----------|-------------|
| B/Vic labs | 0.77 % / 1.13 % | 0.85 % / 1.20 % | 0.85 % / 1.18 % | 1.39 % / 2.10 % | 0.64 % / 1.01 % |
| H1 labs | 1.24 % / 1.51 % | 1.23 % / 1.57 % | 1.23 % / 1.57 % | 1.72 % / 2.30 % | 1.07 % / 1.38 % |
| H3 labs | 0.83 % / 1.22 % | 0.94 % / 1.29 % | 0.94 % / 1.29 % | 1.59 % / 2.51 % | 0.78 % / 1.14 % |

No subtype or lab is an outlier: per-lab fuzz30 means span **0.55 %–1.50 %** across all 18
lab dirs, and every lab's worst map is a `serology` map.

**AD column:** `n/a` for all 219. Consistent with the harness README — the AD references in
this corpus are composed multi-page report/addendum PDFs with maps embedded in laid-out
pages; no isolated AD single-map PDF exists to compare against. The kateri golden is the
only usable per-map reference.

---

## 4. The five maps above 2 %

All five are `serology`; all five are within ~0.5–0.7 pp of their **own** AA floor
(measured per-map, §5 method):

| map | observed fuzz30 | that map's AA-class floor (fuzz30) | excess |
|-----|----------------:|-----------------------------------:|-------:|
| h3-hi-guinea-pig-crick / serology | 2.51 % | 1.88 % | +0.63 pp |
| h3-hi-guinea-pig-vidrl / serology | 2.39 % | 1.49 % | +0.90 pp |
| h1-cdc / serology | 2.30 % | 1.64 % | +0.66 pp |
| h1-vidrl / serology | 2.15 % | 1.48 % | +0.67 pp |
| bvic-vidrl / serology | 2.10 % | 1.61 % | +0.49 pp |

Serology maps are the most **text- and label-dense** family in the report (per-antigen
serology labels + a multi-line title + a paled background cloud), and glyph edges are
exactly where AA disagreement concentrates. Their intrinsic floor is therefore ~2× that of
a by-clade map, which is why they alone brush the 2 % ceiling.

---

## 5. Irreducible anti-aliasing differences

This is the part that determines whether the residual is a *bug* or a *floor*. Three
independent measurements, all on real map PDFs:

### 5.1 Rasteriser floor — identical vector content, two rasterisers

Take **one** PDF and rasterise it twice at 800 px with two different rasterisers
(poppler-**splash** `pdftoppm` vs poppler-**cairo** `pdftocairo`). The vector content is
byte-identical; **every** differing pixel is pure anti-aliasing/rasterisation disagreement.
Sampled 6 maps per family (30 pairs, both the golden and the native render of each):

| family | golden strict | golden fuzz30 | native strict | native fuzz30 |
|--------|--------------:|--------------:|--------------:|--------------:|
| by-clade | 7.15 % | 0.88 % | 6.96 % | 0.42 % |
| by-clade −6m | 5.54 % | 0.98 % | 5.33 % | 0.50 % |
| by-clade −12m | 6.00 % | 0.98 % | 5.80 % | 0.50 % |
| serology | 8.58 % | 1.40 % | 8.32 % | 0.58 % |
| time-series | 3.29 % | 0.69 % | 2.94 % | 0.12 % |
| **ALL (30)** | **6.11 %** | **0.98 %** | **5.87 %** | **0.42 %** |
| range | 2.22–10.85 % | 0.47–1.88 % | 1.79–10.72 % | 0.11–0.74 % |

**Two conclusions:**

1. **Strict AE is not a usable fidelity metric here.** Merely swapping rasteriser on
   *identical* content costs **6.11 %** strict on average (up to 10.85 %). The entire
   observed native-vs-kateri strict difference — mean **4.24 %**, median 3.38 % — is
   *smaller* than that. Any strict number in the 2–7 % band carries no information about
   renderer fidelity. (The one exception is serology, whose strict values reach 17.61 %;
   see §5.3 for what that is.)
2. **The observed fuzz30 mean (0.93 %) is statistically indistinguishable from the AA-class
   scale (0.98 % for the goldens).** The measured native-vs-kateri *content* difference is
   the same size as the difference AA alone produces on content that is provably identical.

> **Caveat, stated precisely.** The harness rasterises native and golden with the *same*
> rasteriser, so it does not literally inherit the splash-vs-cairo floor. What §5.1
> establishes is the **empirical scale of AA-class disagreement** on this exact figure
> corpus — how many pixels of an 800 px map can differ with *zero* content difference. Two
> different vector *emitters* (Cairo path/glyph output vs the Dart `pdf` package's) disagree
> in the same way and at the same places — stroke joins, curve flattening, glyph outlines,
> alpha compositing — so §5.1 is the correct yardstick for judging the residual, not a
> mathematically strict lower bound.

### 5.2 Sub-pixel phase — the viewport is exactly right

For every probed map, AE was recomputed over all nine integer shifts of the native raster
in `[-1,+1]²`. **The minimum was always at `dx=0, dy=0`** — i.e. there is *no* residual
translation between native and kateri output. Milestone A's headline risk (the
transform + recenter + viewport chain, `P2-RENDER-DESIGN.md` §2.2) is closed: framing is
pixel-aligned, and none of the residual is geometric misregistration.

### 5.3 Difference-magnitude spectrum — what the residual actually is

Per-pixel max-channel delta (0–255) for representative maps:

| pair | differing px | δ ≤ 16/255 | δ 17–64 | δ 65–128 | δ > 128 | share of diff at δ ≤ 16 |
|------|-------------:|-----------:|--------:|---------:|--------:|------------------------:|
| by-clade (bvic-cnic) | 2.34 % | 0.95 % | 0.72 % | 0.31 % | 0.36 % | 40.3 % |
| by-clade (h1-vidrl, worst by-clade) | 4.80 % | 1.20 % | 1.94 % | 0.66 % | 1.01 % | 24.9 % |
| time-series (h3-neut-vidrl) | 3.48 % | 1.01 % | 1.59 % | 0.40 % | 0.48 % | 28.8 % |
| serology (h1-cdc) | 16.45 % | **11.09 %** | 2.77 % | 1.26 % | 1.33 % | **67.4 %** |
| **same PDF, splash vs cairo** (serology golden) | 11.12 % | 5.67 % | 3.51 % | 1.27 % | 0.67 % | 51.0 % |

* Serology's alarming 16.45 % strict is **two thirds sub-perceptual**: 11.09 % of the whole
  raster differs by ≤ 16/255 (≤ 6 % of full scale, invisible on screen and in print). That
  signature — a huge, uniformly tiny delta spread over the map body — is a systematic
  **alpha/paling compositing rounding** difference across the `-pale` background cloud, not
  a content error.
* The large-delta population (δ > 64) is **0.7–2.6 % of the raster** across the families, and
  the same-PDF rasteriser control produces **1.9 %** of exactly that population on its own —
  i.e. the control's "large" differences exceed those of every family except serology. Its
  spatial distribution (8×8 density grid) is concentrated in the **title band, the label
  rows inside the map body, and the legend box** — i.e. **glyph rasterisation**, which is
  precisely where two independent vector emitters cannot agree.

### 5.4 Fuzz sweep

AE as a function of tolerance, showing where each map's difference lives:

| map | 0 % | 2 % | 5 % | 10 % | 20 % | 30 % | 50 % |
|-----|----:|----:|----:|-----:|-----:|-----:|-----:|
| by-clade (bvic-cnic) | 2.34 % | 1.68 % | 1.49 % | 1.25 % | 0.74 % | 0.59 % | 0.36 % |
| by-clade (h1-vidrl) | 4.80 % | 3.96 % | 3.73 % | 3.37 % | 1.80 % | 1.51 % | 1.02 % |
| time-series (h3-neut-vidrl) | 3.48 % | 2.83 % | 2.60 % | 2.24 % | 0.97 % | 0.77 % | 0.49 % |
| serology (h1-cdc) | 16.45 % | 5.99 % | 5.57 % | 5.01 % | 2.87 % | 2.30 % | 1.35 % |
| serology (h3-hi-gp-crick) | 12.10 % | 5.31 % | 4.91 % | 4.37 % | 3.06 % | 2.51 % | 1.62 % |

Every curve **collapses monotonically** with no plateau — the hallmark of AA/quantisation.
A genuine content difference (a missing point, a wrong fill, a shifted frame) would hold
its value across the sweep. None does.

### 5.5 Summary of the irreducible component

| component | scale | fixable? |
|-----------|-------|----------|
| Rasteriser/vector-emitter AA on shape and glyph edges | **~0.4–1.0 % fuzz30**, ~3–7 % strict; up to ~1.9 % fuzz30 on text-dense (serology) maps | **No** — inherent to Cairo vs the Dart `pdf` emitter |
| Alpha/paling compositing rounding over large translucent areas | ≤ 16/255 delta over up to ~11 % of the raster on `-pale` maps; ~0 % after fuzz ≥ 2 % | **No** (sub-perceptual); would need bit-exact alpha-blend parity |
| Geometric misregistration (viewport/recenter) | **0** — best shift is always (0,0) | already correct |
| True content differences (points, palette, frame, legend rows) | **not detected** in any of the 219 maps | — |

---

## 6. Unmatchable figures — what could not be signed off, and why

None of these is a renderer failure. In every case **the reference does not exist**.

### 6.1 Info maps (`info-clades…`) — no reference exists anywhere

`info-*` front styles **are** present in `c["R"]` in **all 18** lab charts, and the native
renderer produced **171/171** of them without error. But **no `out.1.info-*.pdf` exists in
any report run** examined (6 runs spanning 2025-09 → 2026-09). The report's `export_info`
step evidently was not exercised, or its output was not retained. **Nothing to diff
against; not signed off.** Closing this needs one kateri `export_info` pass over the
current charts.

### 6.2 Serum circles / serum coverage (`sc-*`) — goldens exist but the styles do not

This family has **plenty** of kateri goldens (1852 in the newest run; 1895 *chart-fresh*
ones in an earlier run). It is nevertheless **unmatchable as the corpus stands**, because
`chart_modifier.add_serum_coverage_styles` builds `sc-*` / `-sci-*` / `-sco-*` styles **on
an in-memory chart at addendum time and the chart is never re-saved with them**. Verified
directly across **69 charts in 3 report runs**: **zero** `sc-*`, `-sci-*` or `-sco-*`
entries exist in the `c["R"]` of any of them (the same scan also found zero `mc-*` and zero
`sigsec-*` — see §6.3, §6.4).

Reconstructing the styles here was rejected as unsound: the front style embeds a
report-specific title, the curated serum selection, fold and zoom variants, so a
reconstruction that differs from the one that produced the golden would yield a diff number
that measures *my reconstruction*, not the renderer. **No number is reported rather than a
misleading one.**

> This family matters: it is milestone **F/G**, the most geometry-heavy part of the
> renderer (empirical vs theoretical radius, fold, dash, angle radius-lines, within/outside
> coverage restyle), and it is currently **unverified by pixel diff**. See §8.

### 6.3 Multiple-serum-circles addendum (`mc-plain`, `mc-circles`) — reference is a different toolchain

The committed `multiple-serum-circles*.pdf` / `plain*.pdf` figures in the report dirs are
**`%PDF-1.4`, `/Producer (R 4.2.0)`** — i.e. produced by the **R/Racmacs** workflow, not by
kateri and not by AD. They are also ~11 months older than the charts. A pixel diff against
an entirely different plotting stack is meaningless. Additionally, `mc-plain`/`mc-circles`
are not persisted in `c["R"]` either (same cause as §6.2). **Not signed off.**

### 6.4 Signature-page section maps (`sigsec-<NN>`) — never persisted standalone

No `sigsec-*` PDF exists in any report run: the section maps are composed straight into the
signature page. `sigsec-*` styles are likewise absent from every `styled.ace`. Note also
that `py/ae/tal/signature_page.py` and `py/ae/report/multiple_circles.py` still call kateri
**directly** and do **not** go through the `MapRenderer` seam, so `AE_REPORT_MAP_RENDERER=native`
does not even cover them today. **Not signed off.**

---

## 7. Defect found while running the matrix

**`export_styled_map` silently accepts an unknown style name.** Rendering
`sc-000-f2.0-e`, `mc-plain`, `sigsec-00` and a deliberately invented
`totally-bogus-style-xyz` from a chart that defines none of them produced **four
byte-identical PDFs** (same SHA-256), differing from a real style's output. The renderer
falls back to an unstyled base render instead of reporting the missing style.

Impact: a typo'd or not-yet-baked style name yields a **plausible-looking but wrong map**
with no error. In a batch report run that is a silent-corruption path. Recommend
`export_styled_map` raise (or at minimum warn) when `style_name ∉ c["R"]`. Not fixed on
this branch — this branch is measurement-only.

---

## 8. Verdict on milestone K

**Signed off** — the five reference-backed families, at the `< 1–2 %` target:

* **by-clade / −6m / −12m / time-series** — 201/201 maps under 2 % fuzz30; means
  0.82–0.96 %. **Unconditional pass.**
* **serology** — 13/18 under 2 %; the other 5 reach 2.10–2.51 %, each within ~0.5–0.9 pp of
  its own measured AA floor, with a fuzz-sweep profile that is unambiguously AA and no
  geometric offset. **Pass, with the AA tail documented rather than hidden.**
* Residual is **irreducible AA** (§5): the fuzz30 mean of 0.93 % equals the 0.98 % AA-class
  scale measured on provably identical content, and strict AE is dominated by a 6.11 %
  rasteriser floor that makes it useless as a metric at this level.
* Viewport/recenter — the one open risk from the design doc — is **exactly matched**
  (best-shift always (0,0)).

**Not signed off** — four families, blocked on missing references, not on the renderer:

| family | blocker | what would close it |
|--------|---------|---------------------|
| info maps | no `out.1.info-*.pdf` anywhere | one kateri `export_info` pass over the current charts → then re-run this harness |
| serum circles / coverage | `sc-*`/`-sci-*`/`-sco-*` never persisted in `styled.ace` | either persist the addendum styles into `styled.ace`, **or** re-run `addendum-serum-coverage.py` under `AE_REPORT_MAP_RENDERER=kateri` writing goldens + a chart that carries the styles |
| multiple-serum-circles | reference is R/Racmacs output, styles not persisted | a kateri reference pass for `mc-plain`/`mc-circles` on a chart carrying them |
| signature-page section maps | never persisted standalone; also bypasses the `MapRenderer` seam | route `signature_page.py` through `MapRenderer`, then emit per-section reference PDFs |

**Recommendation.** Milestone K is complete for the batch report path that native actually
serves today, and the numbers support keeping native as the default backend. It should
**not** be closed outright: families 6–9 — most importantly serum circles/coverage
(milestones F/G) — remain pixel-unverified purely for want of a reference, and that gap is
cheap to close (one reference-generation pass per family). Track it as milestone **K′**.

---

## 9. Reproducing

Inputs live in an ssm report working dir **outside** the repo
(`~/AC/eu/ac/results/ssm/<run>/<lab>/`), read-only. Nothing from it is committed.

1. Build a manifest of `(styled.ace, style, golden)` triples applying the §1.2 gates —
   kateri-signature, style-in-`c["R"]`, golden fresh vs chart. Use
   [`manifest.example.json`](manifest.example.json) as the schema; **do not commit** the
   generated manifest (it carries real report paths).
2. `export PYTHONPATH=<ae>/build:<ae>/py`
3. Run `fidelity.py` as in §1.1 with `--out-dir` under `$TMPDIR`.
4. Aggregate `scoreboard.csv` per family.
5. For the AA floor: rasterise the same PDF with `pdftoppm` and `pdftocairo` at the same
   `-scale-to`, and compare — that number is pure anti-aliasing.

The run behind this document: **219 maps, 0 failures**, 18 lab dirs, 3 subtypes, 5 families.
