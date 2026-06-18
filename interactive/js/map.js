// map.js — antigenic map render + highlight (owns map point nodes)
//
// Plots the active chart's antigens (circles), sera (squares), references and
// vaccines (stars). Subscribes to IV.State so hover / clade-filter / only-matched
// changes re-apply highlight. Resolves tree linkage via IV.Tree.normToLeaves.
//
// M1: orientation + independent zoom/pan. Coordinates arrive already oriented
// (E1 bakes the chart transformation() into x/y), so the map plots them directly.
// Zoom/pan is implemented by RE-PROJECTING the points (folding a zoom factor +
// pan offset into the screen projection) rather than by an SVG <g>/viewBox
// transform. That keeps the "1 SVG user-unit == 1 px" invariant that S1 selection
// (getBBox vs client offset) and the IV.Lines overlay (IV.Map.project) both rely
// on, so both follow zoom/pan for free. After every view change geom is updated
// and IV.Map.onView listeners fire so overlays can reflow.
//
// P1: passage markers. When the bundle carries passage colours (E1), each antigen
// gets a coloured ring (egg/cell/reassortant) in addition to its clade fill.
(function (IV) {
  "use strict";
  const State = IV.State, Colour = IV.Colour, el = IV.el;

  let ptNodes = {};   // norm -> [elements]   (active single map)
  let agByIdx = {};   // antigen index -> antigen (active chart)
  // Current map geometry, refreshed on every render() and view change. Exposed via
  // IV.Map.project(x,y) / IV.Map.scale so overlay modules (IV.Lines N1/N2) align to
  // the map without re-deriving the projection — including under zoom/pan.
  let geom = null;
  let base = null;    // {xmin,xmax,ymin,ymax, bScale, ox, oy} base (fit) projection
  let view = { k: 1, tx: 0, ty: 0 };  // zoom factor + pan (px) on top of the fit
  let placed = [];    // {el, kind:'ag'|'vac'|'serum', x, y, r} for fast reprojection
  const viewListeners = [];           // overlay reflow callbacks (IV.Map.onView)
  let handlersBound = false;

  function star(cx, cy, spikes, inner, outer) {
    let rot = Math.PI / 2 * 3, step = Math.PI / spikes, p = `M${cx},${cy - outer}`;
    for (let i = 0; i < spikes; i++) {
      p += `L${cx + Math.cos(rot) * outer},${cy + Math.sin(rot) * outer}`; rot += step;
      p += `L${cx + Math.cos(rot) * inner},${cy + Math.sin(rot) * inner}`; rot += step;
    }
    return p + "Z";
  }

  // Passage type for an antigen: prefer E1's authoritative classification (`pt`,
  // the same egg/cell/reassortant value E1 puts on tree tips as `passage`), else
  // best-effort classify the raw passage string (egg/cell; reassortant needs E1).
  // Markers only show when the bundle provides passage colours (hasPassageMarkers).
  function passageType(a) {
    if (a.pt) return a.pt;
    if (a.ptype) return a.ptype;
    const p = (a.passage || "").toUpperCase();
    if (!p) return null;
    if (/(REASSORTANT|RESORTANT|\bNYMC\b|\bIVR-?\d|\bNIB-?\d|\bBX-?\d)/.test(p)) return "reassortant";
    if (/(^|[ _/-])E\d|\bEGG\b/.test(p)) return "egg";
    if (/(MDCK|SIAT|QMC|HCK|\bMK\d|\bC\d|CELL)/.test(p)) return "cell";
    return null;
  }
  // Ring only the salient passages (egg / reassortant): cell is the common default
  // for these assays, so ringing every cell point would bury the clade fills. The
  // legend still lists all passage colours; cell points keep the neutral stroke.
  function passageStroke(a) {
    if (!(Colour.hasPassageMarkers && Colour.hasPassageMarkers())) return null;
    const t = passageType(a);
    return (t && t !== "cell") ? Colour.passageColor(t) : null;
  }

  function agHtml(a) {
    const inTree = IV.Tree.normToLeaves[a.norm]
      ? `<br>${IV.Tree.normToLeaves[a.norm].length} tip(s) in tree`
      : "<br><i>not in tree</i>";
    const pt = passageType(a);
    return `<b>${a.name}</b>` + (a.passage ? ` <span style="opacity:.7">${a.passage}</span>` : "") +
      (pt ? ` <span style="opacity:.7">[${pt}]</span>` : "") +
      `<br>${a.date || "?"}` + (a.clade ? `<br>clade: <b>${a.clade}</b>` : "") +
      (a.ref ? "<br><i>reference antigen</i>" : "") + (a.vac ? "<br><b>vaccine</b>" : "") + inTree;
  }

  // ---- projection ------------------------------------------------------------
  // Base (fit) projection: data coords -> screen px, whole map centred in the pane.
  function computeBase(all, W, H) {
    const xs = all.map(p => p.x), ys = all.map(p => p.y);
    const xmin = Math.min(...xs), xmax = Math.max(...xs);
    const ymin = Math.min(...ys), ymax = Math.max(...ys);
    const pad = 30;
    const spanX = xmax - xmin || 1, spanY = ymax - ymin || 1;
    const bScale = Math.min((W - 2 * pad) / spanX, (H - 2 * pad) / spanY);
    const ox = (W - spanX * bScale) / 2, oy = (H - spanY * bScale) / 2;
    return { xmin, xmax, ymin, ymax, bScale, ox, oy, W, H };
  }
  // Keep at least a sliver of the content bbox in the pane, so the map can't be
  // panned fully off-screen (parity with the tree's clampPan). Adjusts view.tx/ty
  // for the current view.k; called after every zoom/pan, before scheduleApply().
  function clampView() {
    if (!base) return;
    const margin = 40;
    const scale = base.bScale * view.k;
    const cw = (base.xmax - base.xmin) * scale, ch = (base.ymax - base.ymin) * scale;
    const fit = (left, lo, hi) => (lo > hi ? (lo + hi) / 2 : Math.max(lo, Math.min(hi, left)));
    // left = SX(xmin) = view.tx + view.k*base.ox ; keep it within [margin-cw, W-margin]
    const left = fit(view.tx + view.k * base.ox, margin - cw, base.W - margin);
    view.tx = left - view.k * base.ox;
    const top = fit(view.ty + view.k * base.oy, margin - ch, base.H - margin);
    view.ty = top - view.k * base.oy;
  }
  // Fold the current zoom/pan view into geom (SX/SY closures + effective scale).
  function recomputeGeom() {
    const b = base, k = view.k;
    const scale = b.bScale * k;
    const ox = view.tx + k * b.ox, oy = view.ty + k * b.oy;
    const SX = x => ox + (x - b.xmin) * scale;
    const SY = y => oy + (b.ymax - y) * scale;   // flip y (data y-up -> screen y-down)
    geom = { scale, SX, SY };
  }
  function reposition() {
    for (const d of placed) {
      const X = geom.SX(d.x), Y = geom.SY(d.y);
      if (d.kind === "serum") { d.el.setAttribute("x", X - d.r); d.el.setAttribute("y", Y - d.r); }
      else if (d.kind === "vac") { d.el.setAttribute("d", star(X, Y, 6, d.r * 0.52, d.r)); }
      else { d.el.setAttribute("cx", X); d.el.setAttribute("cy", Y); }
    }
  }
  let raf = 0;
  function scheduleApply() {
    if (raf) return;
    raf = requestAnimationFrame(() => {
      raf = 0; recomputeGeom(); reposition();
      for (const fn of viewListeners) { try { fn(geom); } catch (_) { /* overlay reflow */ } }
    });
  }
  function zoomAt(mx, my, f) {
    const k2 = Math.max(0.3, Math.min(50, view.k * f));
    f = k2 / view.k;
    view.tx = mx - f * (mx - view.tx);
    view.ty = my - f * (my - view.ty);
    view.k = k2;
    clampView();
    scheduleApply();
  }
  function resetView() { view = { k: 1, tx: 0, ty: 0 }; scheduleApply(); }

  // ---- point painting (shared with IV.Grid) ---------------------------------
  // Draw one chart's sera + antigens into `svg` using projection `proj` ({SX,SY}).
  // Returns { nodes: norm->[el], placed:[descriptor] } so the caller can wire its
  // own highlight (and, for the single map, reproject on zoom/pan).
  function paintChart(svg, chart, proj, opts) {
    opts = opts || {};
    const r0 = opts.r0 || 3.5;
    const nodes = {}, plc = [];
    const pts = chart.antigens.filter(a => a.x != null && a.y != null);
    const sera = chart.sera.filter(s => s.x != null && s.y != null);

    sera.forEach(s => {
      const r = r0 * 1.7, X = proj.SX(s.x), Y = proj.SY(s.y);
      const sq = el("rect", { class: "serum pt", x: X - r, y: Y - r, width: 2 * r, height: 2 * r });
      sq.addEventListener("mouseenter", e => IV.UI.showTip(e, `<b>${s.name}</b><br><i>serum</i>`));
      sq.addEventListener("mousemove", IV.UI.moveTip);
      sq.addEventListener("mouseleave", IV.UI.hideTip);
      svg.appendChild(sq);
      plc.push({ el: sq, kind: "serum", x: s.x, y: s.y, r });
    });

    pts.forEach(a => {
      const r = a.ref ? r0 * 1.43 : a.vac ? r0 * 1.7 : r0;
      let shape;
      if (a.vac) shape = el("path", { class: "pt", d: star(proj.SX(a.x), proj.SY(a.y), 6, r * 0.52, r) });
      else shape = el("circle", { class: "pt", cx: proj.SX(a.x), cy: proj.SY(a.y), r });
      shape.setAttribute("fill", Colour.antigen(a));
      shape.setAttribute("fill-opacity", a.ref ? 0.55 : 0.85);
      const pStroke = a.ref ? null : passageStroke(a);
      shape.setAttribute("stroke", a.ref ? "#000" : (pStroke || "rgba(0,0,0,.3)"));
      shape.setAttribute("stroke-width", a.ref ? 1.3 : (pStroke ? 1.4 : 0.6));
      shape.setAttribute("data-norm", a.norm);
      shape.addEventListener("mouseenter", e => { State.setActive(a.norm); IV.UI.showTip(e, agHtml(a)); });
      shape.addEventListener("mousemove", IV.UI.moveTip);
      shape.addEventListener("mouseleave", () => { State.setActive(null); IV.UI.hideTip(); });
      svg.appendChild(shape);
      (nodes[a.norm] = nodes[a.norm] || []).push(shape);
      plc.push({ el: shape, kind: a.vac ? "vac" : "ag", x: a.x, y: a.y, r });
    });
    return { nodes, placed: plc };
  }

  // ---- single active map -----------------------------------------------------
  function render() {
    const svg = document.getElementById("mapSvg");
    const wrap = document.getElementById("mapWrap");
    const chart = IV.DATA.charts[State.chartIdx];
    svg.innerHTML = ""; ptNodes = {}; agByIdx = {}; placed = [];
    chart.antigens.forEach(a => { agByIdx[a.i] = a; });
    const all = chart.antigens.filter(a => a.x != null && a.y != null)
      .concat(chart.sera.filter(s => s.x != null && s.y != null));
    if (!all.length) { geom = null; return; }
    const W = wrap.clientWidth || 600, H = wrap.clientHeight || 600;
    svg.setAttribute("width", W); svg.setAttribute("height", H);

    base = computeBase(all, W, H);
    view = { k: 1, tx: 0, ty: 0 };   // new chart / re-render fits the whole map
    recomputeGeom();

    const out = paintChart(svg, chart, geom, { r0: 3.5 });
    ptNodes = out.nodes; placed = out.placed;

    bindViewHandlers(svg);
    IV.installSelect(svg);   // S1: click / drag-box selection (shared, idempotent)
  }

  // Zoom/pan input — bound once to the (reused) #mapSvg node. Conflict-free with
  // S1 selection: S1 owns left-button drag (box select); zoom/pan uses the wheel
  // (pinch / ctrl+wheel = zoom to cursor, two-finger scroll = pan) and right/middle
  // -button drag = pan. See the zoom controls in ui chrome for button equivalents.
  function bindViewHandlers(svg) {
    if (handlersBound) return;
    handlersBound = true;

    svg.addEventListener("wheel", e => {
      if (!geom) return;
      e.preventDefault();
      const r = svg.getBoundingClientRect();
      if (e.ctrlKey || e.metaKey) {            // pinch-zoom / ctrl+wheel
        zoomAt(e.clientX - r.left, e.clientY - r.top, Math.exp(-e.deltaY * 0.01));
      } else {                                  // two-finger scroll = pan
        view.tx -= e.deltaX; view.ty -= e.deltaY; clampView(); scheduleApply();
      }
    }, { passive: false });

    let panDrag = null;
    svg.addEventListener("mousedown", e => {       // non-left button = pan (S1 uses left)
      if (e.button === 0 || !geom) return;
      e.preventDefault(); panDrag = { x: e.clientX, y: e.clientY };
    });
    svg.addEventListener("contextmenu", e => { if (panDrag) e.preventDefault(); });
    window.addEventListener("mousemove", e => {
      if (!panDrag) return;
      view.tx += e.clientX - panDrag.x; view.ty += e.clientY - panDrag.y;
      panDrag = { x: e.clientX, y: e.clientY }; clampView(); scheduleApply();
    });
    window.addEventListener("mouseup", () => { panDrag = null; });
    svg.addEventListener("dblclick", e => { e.preventDefault(); resetView(); });

    // on-map zoom controls (button equivalents for mouse users)
    const zi = document.getElementById("mapZoomIn");
    const zo = document.getElementById("mapZoomOut");
    const zr = document.getElementById("mapZoomReset");
    const ctr = () => { const w = document.getElementById("mapWrap"); return [(w.clientWidth || 600) / 2, (w.clientHeight || 600) / 2]; };
    if (zi) zi.onclick = () => { const c = ctr(); zoomAt(c[0], c[1], 1.3); };
    if (zo) zo.onclick = () => { const c = ctr(); zoomAt(c[0], c[1], 1 / 1.3); };
    if (zr) zr.onclick = resetView;
  }

  function refresh() {
    const chart = IV.DATA.charts[State.chartIdx];
    chart.antigens.forEach(a => {
      (ptNodes[a.norm] || []).forEach(s => {
        const extraHidden = State.onlyMatched && !IV.Tree.normToLeaves[a.norm];
        const e = State.emphasis(a.norm, a.clade, extraHidden);
        s.classList.toggle("dim", e.dim);
        s.classList.toggle("lift", e.lift);
        s.classList.toggle("sel", e.sel);
      });
    });
  }

  IV.Map = {
    render, refresh, paintChart,
    get agByIdx() { return agByIdx; },
    // View controls (M1) — also driven by the on-map zoom buttons.
    zoomIn() { const w = (document.getElementById("mapWrap") || {}); zoomAt((w.clientWidth || 600) / 2, (w.clientHeight || 600) / 2, 1.3); },
    zoomOut() { const w = (document.getElementById("mapWrap") || {}); zoomAt((w.clientWidth || 600) / 2, (w.clientHeight || 600) / 2, 1 / 1.3); },
    resetView,
    // Overlay projection contract (consumed by IV.Lines). Returns screen [px,py]
    // for chart coords, or null before the first render / when nothing is plotted.
    project(x, y) { return geom ? [geom.SX(x), geom.SY(y)] : null; },
    get scale() { return geom ? geom.scale : null; },   // antigenic-units -> px
    // Overlay reflow hook: fn(geom) runs after every zoom/pan so overlays drawn via
    // project() can reposition. Returns an unsubscribe fn.
    onView(fn) { viewListeners.push(fn); return () => { const i = viewListeners.indexOf(fn); if (i >= 0) viewListeners.splice(i, 1); }; },
  };
  State.subscribe(refresh);
})(window.IV);
