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
| **1-px stroke tie-break on grid / legend-box edges** (§10, added after the K run) | **0.98 % strict** (23 % of the strict mean); **0.028 % fuzz30** (3.0 % of the fuzz30 mean) | **Partly** — see §10.6; one genuine renderer defect, the rest is a harness artefact |
| True content differences (points, palette, frame, legend rows) | **not detected** in any of the 219 maps | — |

> §5 was written before the stroke-tie analysis in §10. The line "essentially all of the
> residual is anti-aliasing" is **not** quite right: ~23 % of the strict residual and ~3 % of
> the fuzz30 residual are a deterministic 1-pixel rasterisation tie-break on axis-aligned
> 1-px strokes, not AA. It does not change any verdict — the corrected fuzz30 mean is
> **0.892 %** instead of 0.919 % — but it is a different mechanism and is documented in §10.

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

---

## 10. Follow-up — the dark straight lines in the amplified diff

**Date:** 2026-09-10. Same 219-map run, no re-render. Everything below is measured from the
existing `run/` PNGs and PDFs plus four synthetic single-line control PDFs.

Amplifying the native-vs-kateri difference images shows something §5 does not explain:
**long, straight, high-contrast lines** — the outer frame, some interior grid lines, and the
legend-box bottom edge — that are far darker than the surrounding glyph-edge noise. Glyph AA
cannot produce those. They are real, they are systematic, and they are **not** AA.

### 10.1 What the difference actually is

Not sub-pixel phase, not stroke width, not colour, not alpha. It is a **whole-pixel
tie-break**, and it lives in the **rasteriser**, not in either renderer's geometry.

Both renderers emit the *same* lines at the *same* nominal device coordinates with the
*same* 1.0 pt width. Verified by decompressing both content streams for one map
(`bvic-cdc/clades-v1`):

| | native (Cairo) | kateri (Dart `pdf`) |
|---|---|---|
| grid emission | 14 `x 0 m x 800 l S` + 14 `0 y m 800 y l S`, device coords direct | one path, 14+14 subpaths in **world** units under `61.53846 0 0 61.53846 110.76923 43.07692 cm` |
| grid line width | `1 w` (device) | `0.01625 w` × 61.53846 = **1.00000** device |
| grid colour | `0.8 0.8 0.8 RG` (204) | `0.8 0.8 0.8 RG` (204) |
| outermost grid lines | device **0.000000** and **800.000000** | device **0.000002** and **799.999982** |
| legend box | `10 551.52 273.828 238.48 re B`, bottom = **790.000000** | device rect `10.000002 … 283.793841`, bottom = **789.999978** |

The two emitters agree to **2 × 10⁻⁵ pt**. That is the entire geometric difference.

Poppler-splash then applies **thin-line stroke adjustment**: a 1-device-pixel stroke is
snapped to exactly one pixel row/column, chosen by rounding the stroke's extent. When the
stroke centre sits on an **exact integer** device coordinate its extent is exactly
`[N−0.5, N+0.5]` — a perfect tie — and a 2 × 10⁻⁵ pt nudge flips the answer by a **whole
pixel**. Native's coordinates land exactly on the integer; kateri's land a few ULP off it.

**Synthetic control** (single 1 pt line on an 800 × 800 page, `pdftoppm -scale-to 800`):

| line at PDF y | device y | painted row |
|---|---|---|
| `10` | 790.000000 | **790** |
| `10.000022` | 789.999978 | **789** |
| `9.5` | 790.500000 | 790 (no tie) |
| `0` | 800.000000 | **none — line lost** |
| `0.000022` | 799.999978 | **799** |
| `0.5` | 799.500000 | 799 (no tie) |

A 22-microns-of-a-point coordinate change moves a line one whole pixel, or deletes it. That
is the whole phenomenon.

### 10.2 It is systematic — three distinct populations

Measured over all 219 pairs (`d = max-channel |native − kateri|`; 640 000 px per raster).

**(a) Boundary grid lines — 219/219 maps.** The outermost grid lines lie exactly on the
viewport bounds, i.e. device 0 and device 800. Native's `800.000000` rounds *outward* and
the line falls entirely off the page:

| | left col 0 | right col 799 | top row 0 | bottom row 799 |
|---|---|---|---|---|
| native draws it | 219/219 | **0/219** | 219/219 | **0/219** |
| kateri draws it | 219/219 | 219/219 | 160/219 | 209/219 |

So **native loses the bottom and right edge of the map frame in every single map**, and
kateri's top edge is itself unstable (160/219) for the same reason with the opposite sign.

**(b) Interior grid lines that land on exact integers — 152/219 maps.** Whenever
`800·k/N` is an integer for some grid index `k`, that interior line hits the same tie.
Worst case is the `h3-hint-cdc` charts, whose viewport is exactly 8 units → grid step
exactly 100 px → **every** interior line ties: 15 rows + 12 columns each displaced by one
pixel, 21 600 px = **3.4 % of the raster**, about three quarters of that map's 4.60 % strict.

**(c) Legend-box bottom edge — 87/111 maps that have a legend.** The box is placed 10 pt
above the page bottom, so its bottom edge is at device `800 − 10 = 790.000000` — a tie
again. kateri paints row **789 in 111/111**; native paints **790 in 87** and 789 in 24.
Left, right and top edges are identical in all 111 maps; only the bottom differs, always by
exactly +1 row, always in the same direction. The 108 time-series maps have no legend and
are entirely unaffected.

That native is *bimodal* on a fixed coordinate is itself proof the arbiter is the
rasteriser: replaying the two real rectangles through the synthetic harness reproduces it
exactly — `10 551.52 273.828 238.48 re B` → rows 551/**790**, `10 518.062 162.984 271.938
re B` → rows 518/**789**, both with bottom = 790.000000.

**Not misregistration.** §5.2's best-of-9 integer-shift result (always (0,0)) holds for the
lines too: the displacement is +1 px only, only on lines whose coordinate is an exact
integer, and only in the +x/+y direction. Interior non-tie grid lines match **exactly** —
the aggregate row-mean diff at the 13 nominal grid rows of a 13-unit viewport is
0.24–4.07/255 versus 47.4 at row 799.

### 10.3 What it costs

Mean over 219 maps (raster = 640 000 px):

| component | strict px/map | strict % | share of the 4.235 % strict mean | fuzz30 px/map | fuzz30 % | share of the 0.919 % fuzz30 mean |
|---|---:|---:|---:|---:|---:|---:|
| (a) boundary grid lines | 1 737 | 0.271 % | **6.4 %** | 1.3 | 0.0002 % | 0.02 % |
| (b) interior grid ties | 4 351 | 0.680 % | **16.1 %** | ~0 | ~0 % | ~0 % |
| (c) legend-box bottom edge | 198 | 0.031 % | 0.7 % | 177 | 0.028 % | **3.0 %** |
| **total** | **~6 286** | **0.98 %** | **23.1 %** | **178** | **0.028 %** | **3.0 %** |

The grid components are grey 204 against white 255 — Δ = 51/255 = 20 %, **below the 30 %
fuzz threshold** — so they inflate strict by nearly a quarter and contribute essentially
nothing to the content metric. The legend edge is black against white (Δ = 255) and
therefore counts fully in both.

Per family, the legend-edge share of fuzz30: by-clade **6.2 %**, −12m **5.5 %**, −6m
**5.5 %**, serology **4.4 %**, time-series **0 %** (no legend). Across the 111
legend-bearing maps it is **5.4 %** of their 1.015 % fuzz30 mean.

**Corrected headline: fuzz30 mean 0.892 % (from 0.919 %), strict mean 3.26 % (from 4.235 %).**
No verdict in §8 changes.

### 10.4 It only happens at 1:1 rasterisation

The tie requires the stroke to be **exactly 1.0 device pixel wide**, which happens only when
the raster scale is exactly 1.0 — i.e. `-scale-to 800` on an 800 pt page, which is precisely
what the harness does. Re-rasterising the same two PDFs at other sizes:

| `-scale-to` | scale | last grid row/col: native / kateri | legend bottom row: native / kateri | strict |
|---|---|---|---|---|
| 799 | 0.9988 | 737 / 737 | 789 / 789 | 2.27 % |
| **800** | **1.0000** | **738 / 799** | **790 / 789** | **2.75 %** |
| 801 | 1.0012 | 800 / 800 | 790 / 790 | 2.25 % |
| 1600 | 2.0000 | 1599 / 1599 | 1579–1580 / 1579–1580 | 1.36 % |

At **any** other scale the difference vanishes completely — the grid extents match, the
legend edge matches, and strict drops by ~0.5 pp on this map (and by ~2.5 pp on the
step-100-grid `h3-hint-cdc` maps: 4.60 % → 2.13 %). So component (b) and most of (a) are an
**artefact of the harness's raster size**, not of the renderer, and are invisible to any
consumer of the PDF at print or screen resolution.

### 10.5 Bearing on milestone D (recorded as *unverified*)

`P2-RENDER-DESIGN.md` milestone D is "Background grid + border", left open on the question
of whether the styled path needs AD's outer map border, on the grounds that *"kateri draws
none"*. This investigation settles it:

* **kateri has no border code** — confirmed in `kateri/lib/src/`: `grid()` in
  `draw_on_pdf.dart` is the only line primitive, and there is no separate border, frame or
  axis-line path anywhere. What reads as a frame in the goldens is simply the **first and
  last grid lines**, which lie exactly on the viewport bounds.
* The styled native renderer already draws those same four lines. So **no AD-style border
  should be added** — the "missing border" question is moot.
* But native currently **loses two of the four** (bottom and right, in 219/219 maps) to
  §10.1's rounding. At 1:1 the native map frame is open on two sides where kateri's is
  closed. That is a small but genuine, deterministic, always-same-direction content loss —
  the one part of this finding that *is* a renderer defect rather than a harness artefact.

Milestone D can be marked verified with that caveat, and closed once the boundary-line fix
below lands.

### 10.6 Proposed fixes — *not applied on this branch*

`cc/map-draw/styled-draw.cc` is owned by another branch; this branch is measurement-only.
Two independent changes, in priority order.

**1. Renderer (the real defect) — clamp the boundary grid lines inside the surface.** In the
grid block (`cc/map-draw/styled-draw.cc`, the `for (double gx = 0.0; gx <= image_w + 0.5;
gx += step_x)` loops), stroke at a clamped position so the boundary line's centre is half a
line width inside the page instead of exactly on the edge:

```cpp
const double x = std::clamp(gx, 0.5, image_w - 0.5);   // and the gy / image_h analogue
surface.line(x, 0.0, x, image_h, grid, 1.0);
```

Interior lines are untouched (`0.5 ≤ gx ≤ image_w − 0.5` already). This is the same
reasoning as the AD renderer's own comment at `cc/map-draw/draw.cc:712-716`, which doubles
the border width for exactly this reason. Expected: restores the bottom and right frame
lines in 219/219 maps, removing ~1 600 px/map of strict (**≈ 0.25 pp**, ~6 % of the strict
mean); no effect on fuzz30. Verified in the synthetic control (device 799.5 → row 799).

**2. Optional, cosmetic — pixel-snap the legend-box rectangle.** At
`cc/map-draw/styled-draw.cc` (`surface.rectangle(box_x, box_y, box_w, box_h, BLACK, 1.0,
WHITE)`), snap the four stroked edges to pixel centres:

```cpp
const double sx0 = std::floor(box_x) + 0.5,            sy0 = std::floor(box_y) + 0.5;
const double sx1 = std::ceil(box_x + box_w) - 0.5,     sy1 = std::ceil(box_y + box_h) - 0.5;
surface.rectangle(sx0, sy0, sx1 - sx0, sy1 - sy0, BLACK, 1.0, WHITE);
```

Replaying the real coordinates through the synthetic harness confirms this moves the box to
rows 551/**789**, cols 10/283 — **exactly kateri's rendering** — and it removes native's
current bimodality (790 in 87 maps, 789 in 24) by making the outcome independent of the
rasteriser. Expected: removes the whole 0.028 pp legend component, i.e. **3.0 % of the mean
fuzz30 residual** (5.4 % on the 111 legend-bearing maps).

> Honest caveat on (2): both coordinates are "correct"; native's 790.000000 is the
> arithmetically exact one and kateri's 789.999978 is float noise. Snapping is justified
> because it makes native's own output deterministic, not because native is wrong.

**3. Harness — stop rasterising at exactly 1:1.** The cheapest and largest win: change
`fidelity.py`'s default `--size` from 800 to a value that is not the page size (801, or 1600
for a 2× comparison). §10.4 shows this eliminates *all three* components at once — the ties
cannot arise once the device stroke width is not exactly 1.0 px — and makes the strict metric
~23 % less noisy without touching the renderer. It should be done regardless of (1) and (2),
because until it is, the harness is measuring a rasteriser tie-break as if it were renderer
fidelity.

### 10.7 What was ruled out

* **Sub-pixel position offset** — no. Both emitters place the lines within 2 × 10⁻⁵ pt.
* **Line-width difference** — no. Both are exactly 1.0 device pt (kateri: `0.01625 w` under a
  61.53846× CTM).
* **Colour/alpha difference** — no. Grid `0.8 0.8 0.8 RG` in both; legend border black in both.
* **Pixel-grid snapping in either renderer** — neither snaps. `grep` finds no `floor`/`round`/
  `+ 0.5` on any grid, border or box coordinate in `cc/map-draw/` or in kateri's
  `draw_on_pdf.dart` / `draw_on_canvas.dart`. The snapping is poppler's, downstream of both.
* **Whole-map misregistration** — no; §5.2's (0,0) result holds for the lines specifically.
* **Grid phase or step mismatch** — no. Interior non-tie grid lines coincide to the pixel in
  both renderers; only lines at exact-integer device coordinates disagree.
* **A "central axis" (x=0 / y=0) code path** — there is none in either renderer. The lines
  that read as axes in an amplified diff are ordinary grid lines that happened to land on a
  tie (e.g. device 400 when the viewport is 8 or 16 units wide).
* **FP drift from repeated addition** in native's `gx += step_x` — present (up to ~0.002 pt
  visible in Cairo's 3-decimal output) but not the cause; it is two orders of magnitude too
  small to move a non-tie line and irrelevant at a tie.
