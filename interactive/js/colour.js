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
      stressChart = -1;     // force recompute on first use
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

    leaf(lf) {
      switch (State.colorBy) {
        case "none": return BASE;
        case "continent": return contColor[(lf.continent || "").toUpperCase()] || UNMATCHED;
        case "aa": { const v = aaValueOf(lf.norm); return v ? (aaValueColor[v] || UNMATCHED) : UNMATCHED; }
        case "stress": { ensureStress(); const s = stressByNorm[lf.norm]; return s == null ? UNMATCHED : Colour.stressColor(s); }
        default: return lf.clade ? (cladeColor[lf.clade] || UNMATCHED) : UNMATCHED;
      }
    },
    antigen(a) {
      switch (State.colorBy) {
        case "none": return BASE;
        case "continent": return contColor[(a.continent || "").toUpperCase()] || UNMATCHED; // #6
        case "aa": { const v = aaValueOf(a.norm); return v ? (aaValueColor[v] || UNMATCHED) : UNMATCHED; }
        case "stress": { ensureStress(); const s = stressByAg[a.i]; return s == null ? UNMATCHED : Colour.stressColor(s); }
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
    const ch = IV.DATA && IV.DATA.charts[idx];
    if (!ch || !ch.logged || !ch.column_bases) return;
    const errFn = (IV.Lines && IV.Lines._errorFromDist) || ((td, md) => td - md);
    const positioned = ch.sera.filter(s => s.x != null && s.y != null);
    const all = [];
    for (const a of ch.antigens) {
      if (a.x == null || a.y == null) continue;
      const lr = ch.logged[a.i];
      if (!lr) continue;
      const tr = ch.titers && ch.titers[a.i];
      let s = 0;
      for (const sr of positioned) {
        const lg = lr[sr.i];
        if (lg == null) continue;
        const cb = ch.column_bases[sr.i];
        if (cb == null) continue;
        let td = cb - lg; if (td < 0) td = 0;
        const md = Math.hypot(a.x - sr.x, a.y - sr.y);
        const e = errFn(td, md, tr ? tr[sr.i] : null);
        s += e * e;
      }
      stressByAg[a.i] = s;
      all.push(s);
      if (s > stressMax) stressMax = s;
      if (stressByNorm[a.norm] == null || s > stressByNorm[a.norm]) stressByNorm[a.norm] = s;
    }
    // robust colour-scale top: 95th percentile of nonzero stresses (so a few
    // extreme outliers saturate rather than flattening the rest to one colour).
    const nz = all.filter(v => v > 0).sort((p, q) => p - q);
    stressCap = nz.length ? nz[Math.min(nz.length - 1, Math.floor(nz.length * 0.95))] : stressMax;
    if (!(stressCap > 0)) stressCap = stressMax || 1;
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
