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
// Roles → glyph (kateri canonical):
//   circle      cell antigen
//   square      cell serum
//   egg         egg antigen          (rounded egg, aspect 0.75; rot 0.5 = reassortant)
//   uglyEgg     egg serum            (hexagon, aspect 0.75; rot 0.5 = reassortant egg serum)
//   star/reassortant — RETAINED for legacy consumers (tree vaccine tips, legend key)
//     pending their migration; vaccines are now drawn as their larger passage shape,
//     not a star, so map.js no longer uses star.
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

  // Transform a unit point (px,py as multiples of r) for the egg/uglyEgg family:
  // aspect (x narrowed to `asp`·height), optional rotation `rot` (radians), then
  // translate to (cx,cy). Baked into the path coords (NOT an SVG transform) so
  // getBBox stays in screen space for S1 box-select and overlay alignment.
  const EGG_ASPECT = 0.75;   // width = 0.75 · height (kateri)
  function ovalPt(px, py, cx, cy, r, rot) {
    let x = px * r * EGG_ASPECT, y = py * r;
    if (rot) { const c = Math.cos(rot), s = Math.sin(rot); const X = x * c - y * s; y = x * s + y * c; x = X; }
    return [cx + x, cy + y];
  }

  // Egg outline (kateri canonical: rounded — fixes the too-pointy top), aspect 0.75,
  // optional rotation. Egg antigen; rotated 0.5 rad marks a reassortant.
  function eggPath(cx, cy, r, rot) {
    const P = (px, py) => ovalPt(px, py, cx, cy, r, rot || 0);
    const p0 = P(0, 1), c1 = P(1.4, 0.95), c2 = P(0.8, -0.98), p1 = P(0, -1),
          c3 = P(-0.8, -0.98), c4 = P(-1.4, 0.95);
    return `M${p0[0]},${p0[1]}C${c1[0]},${c1[1]} ${c2[0]},${c2[1]} ${p1[0]},${p1[1]}` +
           `C${c3[0]},${c3[1]} ${c4[0]},${c4[1]} ${p0[0]},${p0[1]}Z`;
  }

  // uglyEgg (kateri canonical: a hexagon), aspect 0.75, optional rotation. Egg
  // serum; rotated 0.5 rad marks a reassortant egg serum.
  function uglyEggPath(cx, cy, r, rot) {
    const P = (px, py) => ovalPt(px, py, cx, cy, r, rot || 0);
    const pts = [P(0, 1), P(1.0, 0.6), P(0.8, -0.6), P(0, -1), P(-0.8, -0.6), P(-1.0, 0.6)];
    return "M" + pts.map(p => p[0] + "," + p[1]).join("L") + "Z";
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
  function egg(cx, cy, r, opts) { return elem("path", { d: eggPath(cx, cy, r, opts && opts.rot) }, opts); }
  function uglyEgg(cx, cy, r, opts) { return elem("path", { d: uglyEggPath(cx, cy, r, opts && opts.rot) }, opts); }
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
