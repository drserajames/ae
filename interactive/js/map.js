// map.js — antigenic map render + highlight (owns map point nodes)
//
// Plots the active chart's antigens and sera. All point SHAPES come from the shared
// IV.Glyph factory so the map and tree stay identical (never hand-roll shapes here):
//   antigen        → circle        egg antigen → egg
//   vaccine        → star (large)  serum       → square
//   reassortant    → reassortant (triangle, +orange ring; matches the tree)
//   egg serum      → uglyEgg
// Subscribes to IV.State so hover / clade-filter / only-matched / selection changes
// re-apply highlight. Resolves tree linkage via IV.Tree.normToLeaves.
//
// M1: orientation + independent zoom/pan. Coordinates arrive already oriented (E1
// bakes the chart transformation() into x/y). Zoom/pan RE-PROJECTS the points (folds
// a zoom factor + pan offset into the screen projection) rather than using an SVG
// <g>/viewBox transform, keeping the "1 SVG user-unit == 1 px" invariant that S1
// selection (getBBox vs client offset) and the IV.Lines overlay (IV.Map.project) rely
// on. After every view change geom is updated, gridlines + points reproject, and
// IV.Map.onView listeners fire so overlays can reflow.
//
// Wheel = zoom to cursor (plain scroll-to-zoom; pinch / ctrl / cmd also zoom);
// shift+wheel or right/middle-drag = pan; dbl-click / buttons reset/step. F5 draws
// 1-antigenic-unit gridlines that track the view; F6 shows the chart stress.
(function (IV) {
  "use strict";
  const State = IV.State, Colour = IV.Colour, el = IV.el, G = IV.Glyph;

  let hiList = [];    // flat highlight list {el, norm, clade, serum} (active single map)
  let agByIdx = {};   // antigen index -> antigen (active chart)
  // Current map geometry, refreshed on every render() and view change. Exposed via
  // IV.Map.project(x,y) / IV.Map.scale so overlay modules (IV.Lines N1/N2) align to
  // the map without re-deriving the projection — including under zoom/pan.
  let geom = null;
  let base = null;    // {xmin,xmax,ymin,ymax, bScale, ox, oy, W, H} base (fit) projection
  let view = { k: 1, tx: 0, ty: 0 };  // zoom factor + pan (px) on top of the fit
  let placed = [];    // {el, shape, x, y, r} for fast reprojection
  let gridG = null;   // <g> holding the antigenic-unit gridlines (behind points)
  let stressEl = null;// corner stress readout (F6)
  const viewListeners = [];           // overlay reflow callbacks (IV.Map.onView)
  let handlersBound = false;

  // Passage type for an antigen: prefer E1/v3's authoritative `pt` (egg/cell/
  // reassortant), else best-effort classify the raw passage string.
  function passageType(a) {
    if (a.pt) return a.pt;
    const p = (a.passage || "").toUpperCase();
    if (!p) return null;
    if (/(REASSORTANT|RESORTANT|\bNYMC\b|\bIVR-?\d|\bNIB-?\d|\bBX-?\d)/.test(p)) return "reassortant";
    if (/(^|[ _/-])E\d|\bEGG\b/.test(p)) return "egg";
    if (/(MDCK|SIAT|QMC|HCK|\bMK\d|\bC\d|CELL)/.test(p)) return "cell";
    return null;
  }
  // Ring colour for the salient passages (egg / reassortant). Cell is the common
  // default so it keeps the neutral stroke; egg antigens are already egg-SHAPED, so
  // the ring just reinforces them. Null when the bundle has no passage colours.
  function passageStroke(a) {
    if (!(Colour.hasPassageMarkers && Colour.hasPassageMarkers())) return null;
    const t = passageType(a);
    return (t && t !== "cell") ? Colour.passageColor(t) : null;
  }
  // A serum is "egg" if its homologous antigen was egg-grown (the bundle carries the
  // homologous antigen index; sera have no passage field of their own).
  function isEggSerum(chart, s) {
    const h = s.homologous;
    if (h == null) return false;
    const a = chart.antigens[h];
    return !!(a && a.pt === "egg");
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
  // Keep a sliver of the content bbox in the pane (parity with the tree's clampPan).
  function clampView() {
    if (!base) return;
    const margin = 40;
    const scale = base.bScale * view.k;
    const cw = (base.xmax - base.xmin) * scale, ch = (base.ymax - base.ymin) * scale;
    const fit = (v, lo, hi) => (lo > hi ? (lo + hi) / 2 : Math.max(lo, Math.min(hi, v)));
    const left = fit(view.tx + view.k * base.ox, margin - cw, base.W - margin);
    view.tx = left - view.k * base.ox;
    const top = fit(view.ty + view.k * base.oy, margin - ch, base.H - margin);
    view.ty = top - view.k * base.oy;
  }
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
      switch (d.shape) {
        case "square": d.el.setAttribute("x", X - d.r); d.el.setAttribute("y", Y - d.r); break;
        case "star": d.el.setAttribute("d", G.starPath(X, Y, d.r)); break;
        case "egg": d.el.setAttribute("d", G.eggPath(X, Y, d.r)); break;
        case "uglyEgg": d.el.setAttribute("d", G.uglyEggPath(X, Y, d.r)); break;
        case "reassortant": d.el.setAttribute("d", G.reassortantPath(X, Y, d.r)); break;
        default: d.el.setAttribute("cx", X); d.el.setAttribute("cy", Y);  // circle
      }
    }
  }

  // ---- F5: 1-antigenic-unit gridlines (track zoom/pan) ----------------------
  function drawGrid() {
    if (!gridG || !geom || !base) return;
    gridG.textContent = "";
    const scale = geom.scale;
    if (scale < 8) return;                 // 1 AU < 8px → too dense to be useful
    const W = base.W, H = base.H;
    const sxMin = geom.SX(base.xmin), syMax = geom.SY(base.ymax);
    const invX = px => base.xmin + (px - sxMin) / scale;
    const invY = py => base.ymax - (py - syMax) / scale;
    const gx0 = Math.ceil(invX(0)), gx1 = Math.floor(invX(W));
    const gy0 = Math.ceil(invY(H)), gy1 = Math.floor(invY(0));
    if (gx1 - gx0 > 250 || gy1 - gy0 > 250) return;   // safety cap
    for (let gx = gx0; gx <= gx1; gx++) {
      const X = geom.SX(gx);
      gridG.appendChild(el("line", { x1: X, y1: 0, x2: X, y2: H,
        stroke: gx === 0 ? "#cfcfcf" : "#ededed", "stroke-width": 1 }));
    }
    for (let gy = gy0; gy <= gy1; gy++) {
      const Y = geom.SY(gy);
      gridG.appendChild(el("line", { x1: 0, y1: Y, x2: W, y2: Y,
        stroke: gy === 0 ? "#cfcfcf" : "#ededed", "stroke-width": 1 }));
    }
  }

  let raf = 0;
  function scheduleApply() {
    if (raf) return;
    raf = requestAnimationFrame(() => {
      raf = 0; recomputeGeom(); drawGrid(); reposition();
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
  function resetView() { view = { k: 1, tx: 0, ty: 0 }; clampView(); scheduleApply(); }

  // ---- point painting (shared with IV.Grid) ---------------------------------
  // Draw one chart's sera + antigens into `svg` using projection `proj` ({SX,SY}).
  // Vaccines are drawn LAST (on top), larger, so they're never lost in dense areas.
  // Returns { nodes: norm->[el], placed:[descriptor] } for highlight + reprojection.
  function paintChart(svg, chart, proj, opts) {
    opts = opts || {};
    const r0 = opts.r0 || 3.5;
    const nodes = {}, plc = [], hi = [];   // hi = flat highlight list {el,norm,clade,serum}
    const pts = chart.antigens.filter(a => a.x != null && a.y != null);
    const sera = chart.sera.filter(s => s.x != null && s.y != null);

    sera.forEach(s => {
      const X = proj.SX(s.x), Y = proj.SY(s.y), r = r0 * 1.7;
      const egg = isEggSerum(chart, s);
      // F1: carry the serum norm so a click resolves it (installSelect → expandNorms
      // pulls the homologous antigen + its tree tip); without it a click cleared.
      const o = { class: "serum pt" };
      if (s.norm) o.dataNorm = s.norm;
      const node = egg ? G.uglyEgg(X, Y, r, o) : G.square(X, Y, r, o);
      node.addEventListener("mouseenter", e => {
        if (s.norm) State.setActive(s.norm);
        IV.UI.showTip(e, `<b>${s.name}</b><br><i>serum${egg ? " · egg" : ""}</i>`);
      });
      node.addEventListener("mousemove", IV.UI.moveTip);
      node.addEventListener("mouseleave", () => { if (s.norm) State.setActive(null); IV.UI.hideTip(); });
      svg.appendChild(node);
      plc.push({ el: node, shape: egg ? "uglyEgg" : "square", x: s.x, y: s.y, r });
      if (s.norm) {
        (nodes[s.norm] = nodes[s.norm] || []).push(node);
        hi.push({ el: node, norm: s.norm, clade: null, serum: true });
      }
    });

    function drawAntigen(a) {
      const X = proj.SX(a.x), Y = proj.SY(a.y);
      const pt = passageType(a);
      let shape, r, node;
      if (a.vac) { shape = "star"; r = r0 * 2.4; node = G.star(X, Y, r, { class: "pt" }); }
      else if (pt === "egg") { shape = "egg"; r = r0; node = G.egg(X, Y, r, { class: "pt" }); }
      else if (pt === "reassortant") { shape = "reassortant"; r = r0; node = G.reassortant(X, Y, r, { class: "pt" }); }
      else { shape = "circle"; r = a.ref ? r0 * 1.43 : r0; node = G.circle(X, Y, r, { class: "pt" }); }
      node.setAttribute("fill", Colour.antigen(a));
      node.setAttribute("fill-opacity", a.ref ? 0.55 : 0.85);
      const pStroke = a.ref ? null : passageStroke(a);
      let stroke, sw;
      if (a.vac) { stroke = pStroke || "#222"; sw = 1.4; }       // dark outline → star reads clearly
      else if (a.ref) { stroke = "#000"; sw = 1.3; }
      else if (pStroke) { stroke = pStroke; sw = 1.4; }
      else { stroke = "rgba(0,0,0,.3)"; sw = 0.6; }
      node.setAttribute("stroke", stroke); node.setAttribute("stroke-width", sw);
      node.setAttribute("data-norm", a.norm);
      node.addEventListener("mouseenter", e => { State.setActive(a.norm); IV.UI.showTip(e, agHtml(a)); });
      node.addEventListener("mousemove", IV.UI.moveTip);
      node.addEventListener("mouseleave", () => { State.setActive(null); IV.UI.hideTip(); });
      svg.appendChild(node);
      (nodes[a.norm] = nodes[a.norm] || []).push(node);
      plc.push({ el: node, shape, x: a.x, y: a.y, r });
      hi.push({ el: node, norm: a.norm, clade: a.clade, serum: false });
    }

    const vacs = [];
    pts.forEach(a => { if (a.vac) vacs.push(a); else drawAntigen(a); });
    vacs.forEach(drawAntigen);   // vaccines on top

    return { nodes, placed: plc, hi };
  }

  // ---- single active map -----------------------------------------------------
  function render() {
    const svg = document.getElementById("mapSvg");
    const wrap = document.getElementById("mapWrap");
    const chart = IV.DATA.charts[State.chartIdx];
    svg.innerHTML = ""; hiList = []; agByIdx = {}; placed = [];
    chart.antigens.forEach(a => { agByIdx[a.i] = a; });
    showStress(chart);
    const all = chart.antigens.filter(a => a.x != null && a.y != null)
      .concat(chart.sera.filter(s => s.x != null && s.y != null));
    if (!all.length) { geom = null; return; }
    const W = wrap.clientWidth || 600, H = wrap.clientHeight || 600;
    svg.setAttribute("width", W); svg.setAttribute("height", H);

    base = computeBase(all, W, H);
    view = { k: 1, tx: 0, ty: 0 };   // new chart / re-render fits the whole map
    recomputeGeom();

    gridG = el("g", { class: "gridLayer", "pointer-events": "none" });
    svg.appendChild(gridG);          // first child → behind all points
    drawGrid();

    const out = paintChart(svg, chart, geom, { r0: 3.5 });
    hiList = out.hi; placed = out.placed;

    bindViewHandlers(svg);
    IV.installSelect(svg);   // S1: click / drag-box selection (shared, idempotent)
  }

  // F6: chart stress readout in a corner of the map pane (DOM overlay, fixed to the
  // pane so it doesn't move with zoom/pan).
  function showStress(chart) {
    const wrap = document.getElementById("mapWrap");
    if (!wrap) return;
    if (!stressEl) {
      stressEl = document.createElement("div");
      stressEl.id = "mapStress";
      stressEl.style.cssText = "position:absolute;left:8px;bottom:8px;font-size:11px;" +
        "color:#666;background:rgba(255,255,255,.82);padding:2px 7px;border-radius:4px;" +
        "pointer-events:none;z-index:4;font-variant-numeric:tabular-nums;";
      wrap.appendChild(stressEl);
    }
    const s = chart && chart.stress;
    stressEl.textContent = (s != null) ? `stress ${(+s).toFixed(1)}` : "";
    stressEl.style.display = (s != null) ? "" : "none";
  }

  // Zoom/pan input — bound once to the (reused) #mapSvg node. Conflict-free with S1
  // selection (which owns left-button drag = box select):
  //   wheel              → zoom to cursor (plain scroll-to-zoom; pinch/ctrl/cmd too)
  //   shift + wheel      → pan
  //   right/middle drag  → pan
  //   double-click       → reset;  on-map +/- buttons step zoom
  function bindViewHandlers(svg) {
    if (handlersBound) return;
    handlersBound = true;

    svg.addEventListener("wheel", e => {
      if (!geom) return;
      e.preventDefault();
      const r = svg.getBoundingClientRect();
      if (e.shiftKey && !e.ctrlKey && !e.metaKey) {       // shift = pan
        view.tx -= e.deltaX; view.ty -= e.deltaY; clampView(); scheduleApply();
      } else {                                            // zoom to cursor
        const px = e.deltaY * (e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 400 : 1);
        zoomAt(e.clientX - r.left, e.clientY - r.top, Math.exp(-px * 0.0018));
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

    // on-map zoom controls (button equivalents)
    const zi = document.getElementById("mapZoomIn");
    const zo = document.getElementById("mapZoomOut");
    const zr = document.getElementById("mapZoomReset");
    const ctr = () => { const w = document.getElementById("mapWrap"); return [(w.clientWidth || 600) / 2, (w.clientHeight || 600) / 2]; };
    if (zi) zi.onclick = () => { const c = ctr(); zoomAt(c[0], c[1], 1.4); };
    if (zo) zo.onclick = () => { const c = ctr(); zoomAt(c[0], c[1], 1 / 1.4); };
    if (zr) zr.onclick = resetView;
  }

  function refresh() {
    for (const n of hiList) {
      // sera are never in the tree, so only-matched dimming applies to antigens
      const extraHidden = !n.serum && State.onlyMatched && !IV.Tree.normToLeaves[n.norm];
      const e = State.emphasis(n.norm, n.clade, extraHidden);
      n.el.classList.toggle("dim", e.dim);
      n.el.classList.toggle("lift", e.lift);
      n.el.classList.toggle("sel", e.sel);
    }
  }

  IV.Map = {
    render, refresh, paintChart,
    get agByIdx() { return agByIdx; },
    zoomIn() { const w = (document.getElementById("mapWrap") || {}); zoomAt((w.clientWidth || 600) / 2, (w.clientHeight || 600) / 2, 1.4); },
    zoomOut() { const w = (document.getElementById("mapWrap") || {}); zoomAt((w.clientWidth || 600) / 2, (w.clientHeight || 600) / 2, 1 / 1.4); },
    resetView,
    // Overlay projection contract (consumed by IV.Lines). Returns screen [px,py] for
    // chart coords, or null before the first render / when nothing is plotted.
    project(x, y) { return geom ? [geom.SX(x), geom.SY(y)] : null; },
    get scale() { return geom ? geom.scale : null; },   // antigenic-units -> px
    onView(fn) { viewListeners.push(fn); return () => { const i = viewListeners.indexOf(fn); if (i >= 0) viewListeners.splice(i, 1); }; },
  };
  State.subscribe(refresh);
})(window.IV);
