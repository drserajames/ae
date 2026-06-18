// glyph.js — IV.Glyph: shared point-shape factory (v3 foundation)
//
// The SINGLE source of truth for point shapes, so the map and the tree draw
// identical glyphs for the same role. Pure and dependency-free: no IV.State, no
// DOM queries, no colour logic — it only builds geometry. Callers pass the centre
// (cx, cy), a radius/role size, and the fill/stroke they want.
//
// Two flavours per shape:
//   - *Path(cx, cy, r, …)  → an SVG path `d` string (pure geometry; reuse anywhere,
//     e.g. inline legend glyphs).
//   - element builders      → a live SVG element with fill/stroke/etc. applied.
//
// Roles → glyph:
//   circle      antigen
//   square      serum
//   star        vaccine
//   egg         egg-passaged antigen  (smooth egg/oval outline)
//   uglyEgg     egg-passaged serum    (deliberately distinct, lopsided egg)
//   reassortant reassortant strain    (triangle)
window.IV = window.IV || {};
(function (IV) {
  "use strict";
  const NS = "http://www.w3.org/2000/svg";

  // ---- pure geometry: path `d` strings -------------------------------------
  // n-pointed star centred at (cx,cy); outer radius r, inner = r*innerRatio.
  function starPath(cx, cy, r, spikes, innerRatio) {
    spikes = spikes || 5;
    const outer = r, inner = r * (innerRatio || 0.46);
    let rot = -Math.PI / 2;                 // first point straight up
    const step = Math.PI / spikes;
    let d = `M${cx + Math.cos(rot) * outer},${cy + Math.sin(rot) * outer}`;
    for (let i = 0; i < spikes; i++) {
      rot += step; d += `L${cx + Math.cos(rot) * inner},${cy + Math.sin(rot) * inner}`;
      rot += step; d += `L${cx + Math.cos(rot) * outer},${cy + Math.sin(rot) * outer}`;
    }
    return d + "Z";
  }

  // Smooth egg outline: pointed top, bulbous bottom, total height ~2r (egg antigen).
  function eggPath(cx, cy, r) {
    const rx = r * 0.72, top = cy - r, bot = cy + r * 0.92;
    return `M${cx},${top}` +
      `C${cx + rx},${cy - r * 0.5} ${cx + rx},${bot} ${cx},${bot}` +
      `C${cx - rx},${bot} ${cx - rx},${cy - r * 0.5} ${cx},${top}Z`;
  }

  // Deliberately distinct, lopsided egg for the egg-passaged serum (uglyEgg): a
  // tilted, dented teardrop so it never reads as the clean antigen egg.
  function uglyEggPath(cx, cy, r) {
    const rx = r * 0.8, top = cy - r, bot = cy + r * 0.95;
    return `M${cx},${top}` +
      `C${cx + rx},${cy - r * 0.7} ${cx + rx * 1.1},${cy + r * 0.5} ${cx + r * 0.18},${bot}` +
      `C${cx - rx * 0.6},${bot + r * 0.12} ${cx - rx * 1.05},${cy + r * 0.15} ${cx},${top}Z`;
  }

  // Upward triangle for reassortants, centred on (cx,cy).
  function reassortantPath(cx, cy, r) {
    const w = r * 1.15, top = cy - r * 1.15, base = cy + r * 0.75;
    return `M${cx},${top}L${cx + w},${base}L${cx - w},${base}Z`;
  }

  // ---- element builders -----------------------------------------------------
  // Apply the common presentation options to an element. Recognised opts:
  // fill, stroke, strokeWidth, fillOpacity, opacity, class (className), dataNorm.
  function apply(e, opts) {
    if (!opts) return e;
    if (opts.fill != null) e.setAttribute("fill", opts.fill);
    if (opts.stroke != null) e.setAttribute("stroke", opts.stroke);
    if (opts.strokeWidth != null) e.setAttribute("stroke-width", opts.strokeWidth);
    if (opts.fillOpacity != null) e.setAttribute("fill-opacity", opts.fillOpacity);
    if (opts.opacity != null) e.setAttribute("opacity", opts.opacity);
    if (opts.class != null) e.setAttribute("class", opts.class);
    if (opts.dataNorm != null) e.setAttribute("data-norm", opts.dataNorm);
    return e;
  }
  function elem(tag, attrs, opts) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    return apply(e, opts);
  }

  function circle(cx, cy, r, opts) { return elem("circle", { cx, cy, r }, opts); }
  function square(cx, cy, r, opts) { return elem("rect", { x: cx - r, y: cy - r, width: 2 * r, height: 2 * r }, opts); }
  function star(cx, cy, r, opts) {
    return elem("path", { d: starPath(cx, cy, r, opts && opts.spikes, opts && opts.innerRatio) }, opts);
  }
  function egg(cx, cy, r, opts) { return elem("path", { d: eggPath(cx, cy, r) }, opts); }
  function uglyEgg(cx, cy, r, opts) { return elem("path", { d: uglyEggPath(cx, cy, r) }, opts); }
  function reassortant(cx, cy, r, opts) { return elem("path", { d: reassortantPath(cx, cy, r) }, opts); }

  const Glyph = {
    // path builders (pure d-strings)
    starPath, eggPath, uglyEggPath, reassortantPath,
    // element builders (one per role)
    circle, square, star, egg, uglyEgg, reassortant,
    // dispatch by role name → element (kinds: circle/square/star/egg/uglyEgg/reassortant)
    make(kind, cx, cy, r, opts) {
      const f = ELEMS[kind];
      return f ? f(cx, cy, r, opts) : null;
    },
  };
  const ELEMS = { circle, square, star, egg, uglyEgg, reassortant };

  IV.Glyph = Glyph;
})(window.IV);
