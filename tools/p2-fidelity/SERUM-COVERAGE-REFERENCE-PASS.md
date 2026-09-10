# Serum circles / serum coverage — how to produce the reference pass (milestones F, G)

Milestones **F** (serum circles) and **G** (serum coverage) are the most geometry-heavy part
of the native renderer — empirical vs theoretical radius, fold, dash, angle radius-lines,
per-passage outline/fill, fallback radius, and the within/outside coverage restyle — and they
are the only report map families that the figure-matrix run could not pixel-verify **at all**.
This document says why, what has been fixed, and the exact pass a human still has to run.

The same blocker (and the same fix) applies to the multiple-serum-circles family
(`mc-plain` / `mc-circles`).

---

## 1. Why it was blocked

Not a renderer failure — a **missing reference chart**.

The report produces ~1850 serum-coverage golden PDFs per run
(`<lab>/serum-coverage/sc-<nnn>-f<fold>-{e,t}[zoom].pdf`), and they *are* genuine kateri
output (`%PDF-1.5` + `/Type/Catalog/Version/1.7/PageMode/UseNone`; the native renderer emits
Cairo's `%PDF-1.7`). But **no chart on disk carries the styles that produced them**: a scan of
69 charts across 3 report runs found **zero** `sc-*`, `-sci-*`, `-sco-*` (and zero `mc-*`)
entries in any `c["R"]`.

The cause is structural, and it is *not* that `styled.ace` strips them — the two charts are
simply different objects built by different commands:

| | `export` → `styled.ace` | `serum_coverage_export` → the `sc-*` maps |
|---|---|---|
| source | `adjusted.ace` | `adjusted.ace` |
| styling | `populate_for_style` (prestyles + serology + older-than + continent + pale + new + time-series) | `populate_for_prestyle` + `semantic.pale.style` + `semantic.serum_circle.attributes` + `add_serum_coverage_styles` |
| written out | yes, `styled.ace` | **nothing** — rendered from memory and discarded |

So the `sc-*` family had no persisted chart of its own, and it could not simply be adopted
into `styled.ace` either: the serum-circle **radius** is read at draw time from each serum's
`CI<fold>` semantic attribute (`cc/map-draw/styled-draw.cc`, `chart.sera()[sr].semantic()`),
and `populate_for_style` does **not** set those attributes — the call is commented out in
`chart_modifier.populate_with_attributes_for_style`. Injecting `sc-*` styles into `styled.ace`
would therefore produce fallback circles (a plain `fold`-unit heavily-dashed circle), i.e. a
*different* map from the golden. **Persisting the serum-coverage chart itself is the correct
fix; grafting the styles onto `styled.ace` is not.**

Reconstructing the styles by hand was rejected earlier and stays rejected: the front style
embeds a report-specific title, the curated serum selection and the fold/zoom variants, so a
diff against a reconstruction measures the reconstruction, not the renderer.

---

## 2. What changed (branch `serum-circle-style-persist`)

`ae.report.map_renderer.write_render_chart(chart, filename)` saves the chart that was handed
to the map renderer, verbatim. It is wired into the two producers that previously threw their
styled chart away, in both cases **opt-in and additive** — a normal report run writes exactly
the files it wrote before:

| producer | new artefact | switch |
|---|---|---|
| `commander.CommanderBasic.serum_coverage_export` | `<lab>/serum-coverage/styled-serum-coverage.ace` | `AE_REPORT_PERSIST_RENDER_CHART=1`, or `persist_chart=True` |
| `multiple_circles.generate_lab` | `<lab>/styled-multiple-circles.ace` | same |

The saved chart is the **same object** both backends consume — the native renderer serialises
it to a temp `.ace` (`NativeRenderer.export_pdfs`) and kateri is sent the same bytes over the
socket (`kateri.communicator.send_chart`) — so the file is a record, not a re-derivation.

**Verified round trip** (`test/test-serum-coverage-style-persistence.py`, plus a
production-scale run):

* on `test/chart1.ace`: 50 `sc-*`/`-sci-*`/`-sco-*` styles for 10 sera; whole exported chart
  JSON identical after write → read → write; 10/10 sera keep their `CI2` radius attribute;
  **20/20** `sc-*` front maps render pixel-identically from the persisted file; `angles` +
  `radius_lines` geometry round-trips too;
* at production scale (a real report chart, 6925 antigens × 142 sera, 710 sc-family styles,
  284 front maps): reloaded chart JSON identical to the in-memory one, and **284/284** maps
  rasterise identically between the in-memory render path and the persisted-chart render path.

> **Do not compare native PDFs by byte hash.** Cairo stamps `/Producer` + `/CreationDate` into
> every file, so two renders of the *same* chart a second apart differ in bytes (confirmed:
> the only semantic delta is the `/CreationDate`, the rest is xref offsets shifting behind
> it). Compare rasters — which is what `fidelity.py` does.

---

## 3. The pass that still has to be run (macOS + kateri)

The existing golden PDFs **cannot** be reused. In the newest report run the
`serum-coverage/*.pdf` files are ~6 months older than the `adjusted.ace` they would be
compared against; in the runs where they *are* co-temporal, the clade/vaccine reference data
(`semantic_clades` / `semantic_vaccines`) has moved on since. A **fresh** golden pass is
required, and it must run under kateri, which is a macOS GUI app driven over a Unix socket.
This part could not be automated from a sandboxed agent session.

### 3.1 Generate goldens + the matching chart, per lab

From inside a lab directory of a report working dir (**outside this repo**, read-only inputs;
everything written stays in that working dir):

```bash
export PYTHONPATH=<ae>/build:<ae>/py          # ae_backend + py/ae
export AE_REPORT_MAP_RENDERER=kateri          # goldens MUST come from kateri, not native
export AE_REPORT_PERSIST_RENDER_CHART=1       # <- the new switch: also save the chart

cd <report-working-dir>/<lab>                 # e.g. a subtype-assay-lab dir
./0do serum_coverage_export
```

This writes, into `<lab>/serum-coverage/`:

* `sc-<nnn>-f2.0-{e,t}[zoom].pdf` — the kateri goldens, and
* `styled-serum-coverage.ace` — the chart that produced them, now carrying the `sc-*`,
  `-sci-*`, `-sco-*` styles **and** the `CI2`/`CI3` radius attributes.

Repeat per lab dir. For the multiple-serum-circles family, the equivalent is the report dir's
`gen-multiple-circles-ae.py` driver (it calls `multiple_circles.generate_lab`), which with the
same env var also writes `<lab>/styled-multiple-circles.ace` next to `plain.pdf` /
`multiple-serum-circles.pdf`.

Sanity check one output before running the whole set:

```bash
# kateri golden: %PDF-1.5 + /Type/Catalog/Version/1.7 ; native would be %PDF-1.7 (Cairo)
head -c 200 serum-coverage/sc-000-f2.0-e.pdf | strings | head -3
# the chart must now carry the styles (this printed 0 for every chart before the change)
decat serum-coverage/styled-serum-coverage.ace | python3 -c \
  'import json,sys; R=json.load(sys.stdin)["c"].get("R",{}); print(sum(1 for k in R if k.startswith(("sc-","-sci-","-sco-"))), "sc-family styles")'
```

### 3.2 Build the manifest and run the harness

The manifest schema is [`manifest.example.json`](manifest.example.json); the generated one
carries real report paths, so **do not commit it**. One entry per map:

```json
{
  "raster_size": 800,
  "width": 800,
  "projection": 0,
  "maps": [
    {
      "label":  "<lab>/sc-000-f2.0-e",
      "chart":  "<report-dir>/<lab>/serum-coverage/styled-serum-coverage.ace",
      "style":  "sc-000-f2.0-e",
      "golden": "<report-dir>/<lab>/serum-coverage/sc-000-f2.0-e.pdf"
    }
  ]
}
```

`golden: "auto"` does **not** work for this family — it derives `<chart-dir>/out.1.<style>.pdf`,
which is the main-map naming convention, not `serum-coverage/<style>.pdf`. Name the golden
explicitly. Generate the entries by globbing `serum-coverage/sc-*.pdf` and taking the style
name from the stem; the same three admission gates as the figure-matrix run still apply
(kateri PDF signature, style present in the chart's `c["R"]`, golden not older than the chart —
with a same-run pass all three hold by construction). Leave `ad_ref` out: the AD serum-coverage
references are page-embedded in composed addendum PDFs, not isolable single-map files.

Then:

```bash
python3.14 tools/p2-fidelity/fidelity.py <manifest.json> \
    --build-dir <ae>/build \
    --out-dir   "$TMPDIR/p2-fidelity-serum-coverage" \
    --size 800 --timeout 180
```

`--only sc-` filters to this family if the manifest also carries others. Read the **fuzz30**
column: the target is `< 1–2 %`, and per §5 of the figure-matrix write-up the anti-aliasing
floor on this corpus is ~0.4–1.0 % fuzz30 (up to ~1.9 % on text-dense maps), so anything at or
below ~1 % is at the floor. Serum-coverage maps carry a 3-line title and a legend, so expect
them to sit nearer the serology end than the by-clade end.

A **content** miss in this family would look like: a circle radius that is right on one of
`-e`/`-t` and wrong on the other (empirical/theoretical mix-up); a circle drawn heavily dashed
when the golden's is solid (the fallback path firing, i.e. a missing `CI<fold>` attribute); a
red/blue/orange circle-colour swap (the reassortant-vs-egg passage classification); or
within/outside antigens coloured the wrong way round. Those hold their value across a fuzz
sweep, unlike AA.

### 3.3 Scale

Roughly `2 × n_sera` maps per lab (`n_sera` was 142 in one H1 lab → 284 maps) over ~18 lab
dirs — order 1850 maps. Native renders ~13 maps/s from a persisted chart, but the **kateri**
golden pass is the slow half and needs a GUI session. Consider doing 2–3 representative lab
dirs per subtype first and only widening if they pass.

---

## 4. Status

| | state |
|---|---|
| structural blocker (no chart carries the styles) | **fixed** — opt-in persistence, round trip proven exact |
| kateri golden pass | **not run** — needs macOS + a kateri GUI session (§3.1) |
| F/G fidelity numbers | **still none** — no honest number can be produced before that pass |

Nothing here fabricates a comparison: until §3 is run, milestones F and G remain
pixel-unverified, and that is the correct thing to report.
