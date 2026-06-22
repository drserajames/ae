// colour.js — colour API (shared contract; see CONTRACT.md)
//
// The one place that maps a tree node or chart antigen to a colour, honouring the
// active State.colorBy. Feature modules (legend, tree, map, future C1/C2) call
// these rather than re-deriving palettes.
(function (IV) {
  "use strict";
  const State = IV.State;

  // Continent palette. v3 sources this from the chart's own report style
  // (bundle.continent_color, keyed by uppercase T.C9) so it matches the report
  // PDFs; the map below is only a last-resort fallback for pre-v3 bundles. The old
  // default had EUROPE blue — the report's EUROPE is green — which was the
  // everything-looks-blue bug (#6).
  const CONTINENT_FALLBACK = {
    AFRICA: "#e15759", EUROPE: "#4e79a7", "NORTH-AMERICA": "#59a14f",
    "SOUTH-AMERICA": "#edc948", ASIA: "#f28e2b", OCEANIA: "#b07aa1",
    ANTARCTICA: "#999",
  };
  let contColor = CONTINENT_FALLBACK;   // replaced from bundle.continent_color in init()
  const BASE = "#4e79a7"; // colorBy === "none"

  // passage-type markers (P1). Default palette matches chart_modifier.py / the
  // contract; bundle.passage_color [E1] overrides. Shared by the legend marker
  // key (L1) and the tip/point passage markers (P1) so both stay in sync.
  const PASSAGE_DEFAULT = { egg: "#FF0000", cell: "#0000FF", reassortant: "#FFA500" };
  const PASSAGE_LABEL = { egg: "egg", cell: "cell", reassortant: "reassortant" };

  // categorical palette for colour-by-AA (C1): distinct, stable, assigned to the
  // sorted set of residue values present so the same value always gets the same hue.
  const CAT = [
    "#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f", "#edc948",
    "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac", "#1f77b4", "#2ca02c",
    "#d62728", "#9467bd", "#8c564b", "#e377c2", "#17becf", "#bcbd22",
    "#7f7f7f", "#393b79",
  ];
  // sequential scale for colour-by-stress (C2): ColorBrewer YlOrRd, low→high.
  const SEQ = ["#ffffb2", "#fecc5c", "#fd8d3c", "#f03b20", "#bd0026"];

  // viridis 3-point Bézier control colours for colour-by-time (F1; acmacs-tal
  // color-gradient.cc): oldest #440154 → mid #40ffff → newest #fde725. Quadratic
  // Bernstein per channel.
  const VIRIDIS = [[68, 1, 84], [64, 255, 255], [253, 231, 37]];

  let cladeColor = {};      // clade label -> hex (from bundle.clade_color, report style)
  let cladeLegend = {};     // clade label -> legend text (from bundle.clade_legend)
  let cladePriority = {};   // clade label -> report legend priority (higher = earlier)
  let passageColor = {};    // passage type -> hex
  let hasPassage = false;   // did the bundle provide passage_color? (E1/P1 live)
  let UNMATCHED = "#d9d9d9";

  // ---- C1: colour by amino acid at HA position(s) ----------------------------
  let aaSeq = {};           // norm -> reconstructed AA sequence string (bundle.aa [E2])
  let aaHasData = false;
  let aaPos = [];           // active 1-based HA positions, e.g. [145, 159]
  let aaValueColor = {};    // residue-combination value -> hex

  // ---- C2: colour by per-point stress (computed in JS from E2 titer data) -----
  let stressByAg = {};      // antigen index -> stress (active chart)
  let stressByNorm = {};    // norm -> stress (worst matched antigen, for tree tips)
  let stressCap = 0;        // robust colour-scale top (p95 of nonzero stresses)
  let stressMax = 0;        // true max (legend label)
  let stressChart = -1;     // chart index stress is cached for
  // F5: per-point stress ÷ that point's titre count (stress per titre)
  let stressPerByAg = {}, stressPerByNorm = {}, stressPerCap = 0, stressPerMax = 0;

  // ---- F1: colour by time since collection -----------------------------------
  let metaGenerated = null; // bundle.meta.generated (page-generation date) or null
  let timeOldest = null, timeNewest = null, timeGen = null; // epoch ms (per chart)
  let timeChart = -1;

  // ---- F3: serum-coverage colouring (active when a serum is selected) ---------
  const COV_PINK = "#FFC0CB";          // #3: report-addendum "pink" (was #ff1493, too bright)
  const COV_W = { pink: 1.5, black: 2.5 };  // #1: thin outlines (black still > pink)
  let covSig = null;                   // chart|serumIdx signature for the cache
  let covSerum = null;                 // the selected serum (active chart) or null
  let covThreshold = null;             // log2(homologous/10) − 2 for that serum
  let titreMin = null, titreMax = null;   // F1: log2(titre/10) range vs the serum

  const Colour = {
    init(bundle) {
      cladeColor = bundle.clade_color || {};
      cladeLegend = bundle.clade_legend || {};
      cladePriority = bundle.clade_priority || {};
      contColor = (bundle.continent_color && Object.keys(bundle.continent_color).length)
        ? bundle.continent_color : CONTINENT_FALLBACK;
      hasPassage = !!bundle.passage_color;
      passageColor = Object.assign({}, PASSAGE_DEFAULT, bundle.passage_color || {});
      UNMATCHED = bundle.unmatched_color || "#d9d9d9";
      aaSeq = bundle.aa || {};
      aaHasData = !!(bundle.aa && Object.keys(aaSeq).length);
      metaGenerated = (bundle.meta && bundle.meta.generated) || null;
      stressChart = -1; timeChart = -1;   // force recompute on first use
    },
    unmatched() { return UNMATCHED; },
    cladeColor(c) { return cladeColor[c] || UNMATCHED; },
    cladeLegend(c) { return cladeLegend[c] || c; },
    clades() { return Object.keys(cladeColor); },
    // clades in the report's legend order: by legend priority (higher first — the
    // report assigns 99, 98, … top-down), then legend text, then label.
    cladesOrdered() {
      return Object.keys(cladeColor).sort((a, b) => {
        const pa = cladePriority[a], pb = cladePriority[b];
        const na = (pa == null), nb = (pb == null);
        if (na !== nb) return na ? 1 : -1;             // nulls last
        if (!na && pa !== pb) return pb - pa;          // higher priority first
        return (cladeLegend[a] || a).localeCompare(cladeLegend[b] || b);
      });
    },

    // ---- continent key (colorBy === "continent"); palette from report style ----
    continentColor(c) { return contColor[(c || "").toUpperCase()] || UNMATCHED; },
    continents() { return Object.keys(contColor); },

    // ---- passage markers (P1 + legend marker key) ----
    passageColor(type) { return passageColor[type] || null; },
    passageLabel(type) { return PASSAGE_LABEL[type] || type; },
    passages() { return Object.keys(passageColor); },
    hasPassageMarkers() { return hasPassage; },

    // ---- C1: amino-acid colouring -------------------------------------------
    hasAA() { return aaHasData; },
    aaPositions() { return aaPos.slice(); },
    // Set the active HA positions from a free-text spec ("145", "145, 159"); the
    // value/colour map is rebuilt over the whole bundle so colours are stable
    // regardless of which chart/tips are visible. Returns {positions, nValues}.
    setAAPositions(spec) {
      aaPos = String(spec || "").split(/[\s,;]+/)
        .map(s => parseInt(s, 10)).filter(n => Number.isInteger(n) && n > 0);
      aaValueColor = {};
      if (aaPos.length) {
        const vals = new Set();
        for (const n in aaSeq) { const v = aaValueOf(n); if (v) vals.add(v); }
        Array.from(vals).sort().forEach((v, i) => { aaValueColor[v] = CAT[i % CAT.length]; });
      }
      return { positions: aaPos.slice(), nValues: Object.keys(aaValueColor).length };
    },
    aaValue(norm) { return aaValueOf(norm); },
    aaValues() { return Object.keys(aaValueColor).sort(); },
    aaColor(v) { return aaValueColor[v] || UNMATCHED; },

    // ---- C2: per-point stress -----------------------------------------------
    // active chart has the E2 titer data needed to compute stress?
    hasStress() {
      const ch = IV.DATA && IV.DATA.charts[State.chartIdx];
      return !!(ch && ch.logged && ch.column_bases);
    },
    stressOfAg(a) { ensureStress(); return stressByAg[a.i]; },
    stressOfNorm(n) { ensureStress(); return stressByNorm[n]; },
    stressColor(s) { return s == null ? UNMATCHED : seqColor(stressCap > 0 ? Math.min(1, s / stressCap) : 0); },
    stressScale() { ensureStress(); return { cap: stressCap, max: stressMax, stops: SEQ.slice() }; },
    // F5: per-titre stress (per-point stress ÷ titre count), its own colour scale
    stressPerColor(s) { return s == null ? UNMATCHED : seqColor(stressPerCap > 0 ? Math.min(1, s / stressPerCap) : 0); },
    stressPerScale() { ensureStress(); return { cap: stressPerCap, max: stressPerMax, stops: SEQ.slice() }; },

    // ---- F1: colour by collection date (viridis over [oldest … generated]) ----
    hasTime() { ensureTime(); return timeOldest != null; },
    timeColor(dateStr) { ensureTime(); return timeColorOf(dateStr); },
    timeStops(n) { n = n || 7; const o = []; for (let i = 0; i < n; i++) o.push(viridis(i / (n - 1))); return o; },
    // date window for the legend; `generatedExplicit` = came from meta.generated.
    timeWindow() {
      ensureTime();
      return {
        oldest: isoDate(timeOldest), newest: isoDate(timeNewest), generated: isoDate(timeGen),
        generatedExplicit: metaGenerated != null,
      };
    },

    // ---- F3: serum-coverage colouring (v7) ----------------------------------
    // Needs the chart's logged titers + EXACTLY ONE serum selected; it only shows
    // then (coverageSerum()). v7: fill stays the antigen's bright clade colour for
    // all; untitrated antigens RECEDE by dimming (like clade-select), folded into
    // State.emphasis() via coverageDim(norm) — not a pale fill. The titrated outline
    // (coverageOutline) marks coverage: pink ≤4-fold of homologous (thin), black
    // >4-fold (thicker, to flag the poorly-covered ones).
    hasCoverage() { const ch = IV.DATA && IV.DATA.charts[State.chartIdx]; return !!(ch && ch.logged && ch.sera && ch.sera.length); },
    coverageSerum() { ensureCoverage(); return covSerum; },
    coverageWidths() { return { pink: COV_W.pink, black: COV_W.black }; },
    // #7 (v9): returns the pink/black coverage outline for a titrated antigen
    // whenever a coverage serum is resolved (the isolated serum). NO colorBy gate —
    // the caller (map.js) applies it both in the `coverage` colour mode AND whenever
    // that serum's circle is shown. Threshold is vs the homologous titre (#4: max
    // over the serum's homologous antigens, matching the circle's min-radius rule).
    coverageOutline(a) {
      ensureCoverage();
      if (!covSerum) return null;
      const titer = titerOf(a.i);
      if (titer == null) return null;             // untitrated → no outline (it dims)
      const pink = covThreshold != null && titer >= covThreshold;   // ≤4-fold of homologous
      return pink ? { stroke: COV_PINK, width: COV_W.pink } : { stroke: "#000", width: COV_W.black };
    },
    // ---- F1 (v10): colour by log2(titre/10) vs the selected serum ------------
    // Only meaningful when a single serum is resolved (coverageSerum()). Reuses the
    // sequential gradient (SEQ, like stress) over the titre range against that serum.
    hasTitre() { ensureCoverage(); return !!covSerum && titreMin != null; },
    titreColor(titer) {
      if (titer == null || titreMin == null) return UNMATCHED;
      const span = titreMax - titreMin;
      return seqColor(span > 0 ? (titer - titreMin) / span : 0.5);
    },
    titreScale() { ensureCoverage(); return { min: titreMin, max: titreMax, stops: SEQ.slice() }; },
    // true when coverage mode is showing and `norm`'s antigen was NOT titrated by the
    // selected serum — State.emphasis() folds this in so untitrated points dim (v7).
    coverageDim(norm) {
      if (State.colorBy !== "coverage") return false;
      ensureCoverage();
      if (!covSerum || norm === covSerum.norm) return false;   // never dim the serum itself
      const ch = IV.DATA.charts[State.chartIdx];
      const idxs = ch.norm_to_ag && ch.norm_to_ag[norm];
      if (!idxs || !idxs.length) return false;
      for (const ai of idxs) if (titerOf(ai) != null) return false;   // any titrated → covered
      return true;                                 // all of this norm's antigens untitrated → dim
    },
    coveragePink() { return COV_PINK; },

    leaf(lf) {
      switch (State.colorBy) {
        case "none": return BASE;
        case "continent": return contColor[(lf.continent || "").toUpperCase()] || UNMATCHED;
        case "aa": { const v = aaValueOf(lf.norm); return v ? (aaValueColor[v] || UNMATCHED) : UNMATCHED; }
        case "stress": { ensureStress(); const s = stressByNorm[lf.norm]; return s == null ? UNMATCHED : Colour.stressColor(s); }
        case "stressn": { ensureStress(); const s = stressPerByNorm[lf.norm]; return s == null ? UNMATCHED : Colour.stressPerColor(s); }
        case "time": { ensureTime(); return timeColorOf(lf.date); }
        // v7: bright clade colour for all; untitrated tips recede via emphasis dim
        case "coverage": { ensureCoverage(); return covSerum ? (lf.clade ? (cladeColor[lf.clade] || UNMATCHED) : UNMATCHED) : UNMATCHED; }
        case "titre": { ensureCoverage(); return covSerum ? Colour.titreColor(titreByNorm(lf.norm)) : UNMATCHED; }
        default: return lf.clade ? (cladeColor[lf.clade] || UNMATCHED) : UNMATCHED;
      }
    },
    antigen(a) {
      switch (State.colorBy) {
        case "none": return BASE;
        case "continent": return contColor[(a.continent || "").toUpperCase()] || UNMATCHED; // #6
        case "aa": { const v = aaValueOf(a.norm); return v ? (aaValueColor[v] || UNMATCHED) : UNMATCHED; }
        case "stress": { ensureStress(); const s = stressByAg[a.i]; return s == null ? UNMATCHED : Colour.stressColor(s); }
        case "stressn": { ensureStress(); const s = stressPerByAg[a.i]; return s == null ? UNMATCHED : Colour.stressPerColor(s); }
        case "time": { ensureTime(); return timeColorOf(a.date); }
        case "coverage": { ensureCoverage(); return covSerum ? (a.clade ? (cladeColor[a.clade] || UNMATCHED) : UNMATCHED) : UNMATCHED; }
        case "titre": { ensureCoverage(); return covSerum ? Colour.titreColor(titerOf(a.i)) : UNMATCHED; }
        default: return a.clade ? (cladeColor[a.clade] || UNMATCHED) : UNMATCHED;
      }
    },
  };

  // residue value at the active positions for a norm ("N", "NY", …); null if any
  // position is missing / gap ("-") / unknown ("X") / beyond the sequence.
  function aaValueOf(norm) {
    if (!aaPos.length) return null;
    const seq = aaSeq[norm];
    if (!seq) return null;
    let v = "";
    for (const p of aaPos) {
      const c = seq[p - 1];
      if (!c || c === "-" || c === "X") return null;
      v += c;
    }
    return v;
  }

  // Per-point stress for the active chart: Σ error² over each point's measured
  // titers, reusing IV.Lines' error formula (threshold-aware) so C2 and the N1
  // error lines agree. Cached per chart. Map distance is euclidean on the oriented
  // coords (antigenic units), matching the units IV.Lines._errorFromDist expects.
  function ensureStress() {
    const idx = State.chartIdx;
    if (stressChart === idx) return;
    stressChart = idx;
    stressByAg = {}; stressByNorm = {}; stressCap = 0; stressMax = 0;
    stressPerByAg = {}; stressPerByNorm = {}; stressPerCap = 0; stressPerMax = 0;
    const ch = IV.DATA && IV.DATA.charts[idx];
    if (!ch || !ch.logged || !ch.column_bases) return;
    const errFn = (IV.Lines && IV.Lines._errorFromDist) || ((td, md) => td - md);
    const positioned = ch.sera.filter(s => s.x != null && s.y != null);
    const all = [], allPer = [];
    for (const a of ch.antigens) {
      if (a.x == null || a.y == null) continue;
      const lr = ch.logged[a.i];
      if (!lr) continue;
      const tr = ch.titers && ch.titers[a.i];
      let s = 0, n = 0;
      for (const sr of positioned) {
        const lg = lr[sr.i];
        if (lg == null) continue;
        const cb = ch.column_bases[sr.i];
        if (cb == null) continue;
        let td = cb - lg; if (td < 0) td = 0;
        const md = Math.hypot(a.x - sr.x, a.y - sr.y);
        const e = errFn(td, md, tr ? tr[sr.i] : null);
        s += e * e; n++;
      }
      stressByAg[a.i] = s;
      all.push(s);
      if (s > stressMax) stressMax = s;
      if (stressByNorm[a.norm] == null || s > stressByNorm[a.norm]) stressByNorm[a.norm] = s;
      // F5: stress per titre (mean error² over the point's measured titres)
      const sp = n > 0 ? s / n : 0;
      stressPerByAg[a.i] = sp;
      allPer.push(sp);
      if (sp > stressPerMax) stressPerMax = sp;
      if (stressPerByNorm[a.norm] == null || sp > stressPerByNorm[a.norm]) stressPerByNorm[a.norm] = sp;
    }
    // robust colour-scale top: 95th percentile of nonzero values (so a few extreme
    // outliers saturate rather than flattening the rest to one colour).
    stressCap = p95(all) || stressMax || 1;
    stressPerCap = p95(allPer) || stressPerMax || 1;
  }
  // 95th percentile of the nonzero values (0 if none)
  function p95(arr) {
    const nz = arr.filter(v => v > 0).sort((a, b) => a - b);
    return nz.length ? nz[Math.min(nz.length - 1, Math.floor(nz.length * 0.95))] : 0;
  }

  // F1: date-window for the active chart (oldest..newest antigen date; newest
  // anchor = meta.generated when it's a valid date ≥ the newest antigen). Cached.
  function ensureTime() {
    const idx = State.chartIdx;
    if (timeChart === idx) return;
    timeChart = idx;
    timeOldest = timeNewest = timeGen = null;
    const ch = IV.DATA && IV.DATA.charts[idx];
    if (!ch) return;
    let mn = Infinity, mx = -Infinity;
    for (const a of ch.antigens) {
      const t = dateMs(a.date);
      if (t == null) continue;
      if (t < mn) mn = t;
      if (t > mx) mx = t;
    }
    if (mn === Infinity) return;
    timeOldest = mn; timeNewest = mx;
    const g = dateMs(metaGenerated);
    timeGen = (g != null && g >= mx) ? g : mx;   // anchor newest = generation date
  }
  function timeColorOf(dateStr) {
    const t = dateMs(dateStr);
    if (t == null || timeOldest == null) return UNMATCHED;
    const span = timeGen - timeOldest;
    return viridis(span > 0 ? (t - timeOldest) / span : 0);
  }
  // quadratic Bézier (Bernstein) through the three VIRIDIS control colours
  function viridis(t) {
    t = Math.max(0, Math.min(1, t));
    const u = 1 - t, b0 = u * u, b1 = 2 * u * t, b2 = t * t;
    const ch = k => Math.round(b0 * VIRIDIS[0][k] + b1 * VIRIDIS[1][k] + b2 * VIRIDIS[2][k]);
    return `rgb(${ch(0)},${ch(1)},${ch(2)})`;
  }
  function dateMs(s) {
    if (!s || typeof s !== "string") return null;
    const t = Date.parse(s);
    return Number.isFinite(t) ? t : null;
  }
  function isoDate(ms) {
    if (ms == null) return null;
    try { return new Date(ms).toISOString().slice(0, 10); } catch (_) { return null; }
  }

  // F3 (v7/v8): resolve the coverage serum — the double-click-ISOLATED serum
  // (`State.isolatedSerum()`, the v8 way to pick one exact serum), else the fallback
  // of a single selected serum norm. Threshold = log2(homologous/10) − 2 (logged
  // units). Cached by a (chart|serum) signature so it only recomputes on change.
  function ensureCoverage() {
    const ch = IV.DATA && IV.DATA.charts[State.chartIdx];
    let serum = (State.isolatedSerum && State.isolatedSerum()) || null;
    if (!serum && ch && ch.sera) {
      // fallback: exactly one serum selected — counted by distinct serum NORM, since
      // a strain's egg+cell sera share a norm (selecting one square selects both).
      const norms = new Set(); let first = null;
      for (const s of ch.sera) {
        if (s.norm && State.selected.has(s.norm)) { norms.add(s.norm); if (!first) first = s; }
      }
      if (norms.size === 1) serum = first;
    }
    const sig = State.chartIdx + "|" + (serum ? serum.i : "none");
    if (sig === covSig) return;
    covSig = sig; covSerum = serum; covThreshold = null;
    if (serum && ch.logged && serum.homologous != null) {
      // #4: `homologous` is now a list of antigen indices (a serum may have several
      // reference strains, e.g. egg+cell). Threshold uses the MAX homologous titre
      // — matching the serum circle, which takes the min radius over them.
      const homs = Array.isArray(serum.homologous) ? serum.homologous : [serum.homologous];
      let ht = null;
      for (const h of homs) {
        const row = ch.logged[h];
        const v = row ? row[serum.i] : null;
        if (v != null && (ht == null || v > ht)) ht = v;
      }
      covThreshold = (ht == null) ? null : ht - 2;
    }
    // F1: log2(titre/10) range over antigens titrated by this serum (for the gradient)
    titreMin = titreMax = null;
    if (serum && ch.logged) {
      for (let i = 0; i < ch.antigens.length; i++) {
        const row = ch.logged[i];
        const v = row ? row[serum.i] : null;
        if (v == null) continue;
        if (titreMin == null || v < titreMin) titreMin = v;
        if (titreMax == null || v > titreMax) titreMax = v;
      }
    }
  }
  // logged titer of antigen index `ai` against the selected serum (null = untitrated)
  function titerOf(ai) {
    const ch = IV.DATA.charts[State.chartIdx];
    const lr = ch.logged && ch.logged[ai];
    return lr ? lr[covSerum.i] : null;
  }
  // best (highest) logged titre over a norm's antigens vs the serum (for tree tips)
  function titreByNorm(norm) {
    const ch = IV.DATA.charts[State.chartIdx];
    const idxs = ch.norm_to_ag && ch.norm_to_ag[norm];
    if (!idxs || !idxs.length) return null;
    let best = null;
    for (const ai of idxs) { const t = titerOf(ai); if (t != null && (best == null || t > best)) best = t; }
    return best;
  }

  // interpolate the SEQ stops at t in [0,1] -> "#rrggbb"
  function seqColor(t) {
    t = Math.max(0, Math.min(1, t));
    const seg = (SEQ.length - 1) * t;
    const i = Math.min(SEQ.length - 2, Math.floor(seg)), f = seg - i;
    const a = hex2rgb(SEQ[i]), b = hex2rgb(SEQ[i + 1]);
    const m = k => Math.round(a[k] + (b[k] - a[k]) * f);
    return `rgb(${m(0)},${m(1)},${m(2)})`;
  }
  function hex2rgb(h) {
    return [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];
  }

  IV.Colour = Colour;
})(window.IV);
