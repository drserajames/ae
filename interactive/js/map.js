// map.js — antigenic map render + highlight (owns map point nodes)
//
// Plots the active chart's antigens and sera. All point SHAPES come from the shared
// IV.Glyph factory so the map and tree stay identical (never hand-roll shapes here):
//   cell antigen → circle           cell serum         → square
//   egg antigen  → egg              egg serum          → uglyEgg
//   reassortant  → egg rotated 0.5  reassortant serum  → uglyEgg rotated 0.5
//   vaccine      → its passage shape, larger + black outline (not a star)
// Passage is conveyed by shape (no outline ring); a serum's outline shows its
// strain's colour-by colour. 1-AU gridlines track zoom/pan.
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
  // Passage is shown by SHAPE (#10), not an outline ring. Antigen: cell→circle,
  // egg→egg, reassortant→egg rotated 0.5 rad (#11). Vaccine keeps its passage shape
  // (just larger + black outline, #3).
  function antigenShape(a) {
    const pt = passageType(a);
    if (pt === "egg") return { shape: "egg", rot: 0 };
    if (pt === "reassortant") return { shape: "egg", rot: 0.5 };
    return { shape: "circle", rot: 0 };
  }
  // Serum shape mirrors its homologous antigen's passage (sera carry no passage of
  // their own): cell→square, egg→uglyEgg (#5), reassortant→uglyEgg rotated 0.5 (#12).
  function homAg(chart, s) {
    const h = s.homologous;
    return (h != null && chart.antigens[h]) ? chart.antigens[h] : null;
  }
  function serumShape(chart, s) {
    const ag = homAg(chart, s), pt = ag ? ag.pt : null;
    if (pt === "egg") return { shape: "uglyEgg", rot: 0, label: "egg" };
    if (pt === "reassortant") return { shape: "uglyEgg", rot: 0.5, label: "reassortant" };
    return { shape: "square", rot: 0, label: "" };
  }
  // Feature 1: a serum's outline = its strain's current colour-by colour (clade / AA
  // / continent / stress), taken from its homologous antigen so it tracks colorBy.
  function serumColour(chart, s) {
    const ag = homAg(chart, s);
    return ag ? Colour.antigen(ag) : Colour.unmatched();
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

  // #6: serum tooltip — name + passage, then serum-id (+ species if present).
  function serumHtml(s) {
    let h = `<b>${s.name}</b>` + (s.passage ? ` <span style="opacity:.7">${s.passage}</span>` : "");
    h += "<br><i>serum</i>";
    const meta = [];
    if (s.serum_id) meta.push(`id <b>${s.serum_id}</b>`);
    if (s.serum_species) meta.push(s.serum_species);
    if (meta.length) h += " · " + meta.join(" · ");
    return h;
  }

  // ---- projection ------------------------------------------------------------
  function computeBase(all, W, H, r0) {
    const xs = all.map(p => p.x), ys = all.map(p => p.y);
    const xmin = Math.min(...xs), xmax = Math.max(...xs);
    const ymin = Math.min(...ys), ymax = Math.max(...ys);
    // pad by the largest rendered point radius so edge points (vaccines) aren't
    // drawn past the pane edge (#5).
    const R = r0 || 3.5;
    let maxR = R;
    for (const p of all) {
      const r = p.vac ? R * 2.2 : p.ref ? R * 1.43 : (p.serum_id != null) ? R * 1.7 : R;
      if (r > maxR) maxR = r;
    }
    const pad = 20 + maxR + 3;
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
        case "egg": d.el.setAttribute("d", G.eggPath(X, Y, d.r, d.rot)); break;
        case "uglyEgg": d.el.setAttribute("d", G.uglyEggPath(X, Y, d.r, d.rot)); break;
        default: d.el.setAttribute("cx", X); d.el.setAttribute("cy", Y);  // circle
      }
    }
  }

  // ---- F5: 1-antigenic-unit gridlines --------------------------------------
  // Build the gridlines for a projection (SX/SY) + AU scale into a pane W×H.
  // Uniform light lines only (#6: no darker axis lines). Reused by the single map
  // (re-projected on zoom/pan) and by the all-centres grid panels (#7).
  function gridLineEls(SX, SY, scale, xmin, ymax, W, H) {
    const out = [];
    if (!(scale >= 8)) return out;          // 1 AU < 8px → too dense to be useful
    const invX = px => xmin + (px - SX(xmin)) / scale;
    const invY = py => ymax - (py - SY(ymax)) / scale;
    const gx0 = Math.ceil(invX(0)), gx1 = Math.floor(invX(W));
    const gy0 = Math.ceil(invY(H)), gy1 = Math.floor(invY(0));
    if (gx1 - gx0 > 250 || gy1 - gy0 > 250) return out;   // safety cap
    for (let gx = gx0; gx <= gx1; gx++)
      out.push(el("line", { x1: SX(gx), y1: 0, x2: SX(gx), y2: H, stroke: "#ededed", "stroke-width": 1 }));
    for (let gy = gy0; gy <= gy1; gy++)
      out.push(el("line", { x1: 0, y1: SY(gy), x2: W, y2: SY(gy), stroke: "#ededed", "stroke-width": 1 }));
    return out;
  }
  function drawGrid() {
    if (!gridG || !geom || !base) return;
    gridG.textContent = "";
    for (const ln of gridLineEls(geom.SX, geom.SY, geom.scale, base.xmin, base.ymax, base.W, base.H))
      gridG.appendChild(ln);
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
      const ss = serumShape(chart, s);
      // F1: carry the serum norm so a click resolves it (installSelect → expandNorms
      // pulls the homologous antigen + its tree tip); without it a click cleared.
      // Feature 1: serum outline = its strain's colour-by colour. Set fill/stroke as
      // attributes (not the .serum CSS class) so the .lift/.sel highlight classes still
      // override; `sr` is a non-styling marker class. Self-contained — no CSS needed.
      // fill:"transparent" (not "none") so the whole box is a hit target — sera read
      // as hollow but the interior is clickable, not just the 1px stroke (#2).
      const o = { class: "pt sr", fill: "transparent", stroke: serumColour(chart, s), strokeWidth: 1.3 };
      if (s.norm) o.dataNorm = s.norm;
      if (ss.rot) o.rot = ss.rot;
      const node = G.make(ss.shape, X, Y, r, o);
      node.addEventListener("mouseenter", e => {
        if (s.norm) State.setActive(s.norm);
        IV.UI.showTip(e, serumHtml(s));
      });
      node.addEventListener("mousemove", IV.UI.moveTip);
      node.addEventListener("mouseleave", () => { if (s.norm) State.setActive(null); IV.UI.hideTip(); });
      svg.appendChild(node);
      plc.push({ el: node, shape: ss.shape, rot: ss.rot || 0, x: s.x, y: s.y, r });
      if (s.norm) {
        (nodes[s.norm] = nodes[s.norm] || []).push(node);
        hi.push({ el: node, norm: s.norm, clade: null, serum: true });
      }
    });

    function drawAntigen(a) {
      const X = proj.SX(a.x), Y = proj.SY(a.y);
      const sh = antigenShape(a);
      // #3: vaccine = its passage shape but larger (kateri ~40 vs ref ~20–32).
      const r = a.vac ? r0 * 2.2 : a.ref ? r0 * 1.4 : r0;
      const o = { class: "pt" };
      if (sh.rot) o.rot = sh.rot;
      const node = G.make(sh.shape, X, Y, r, o);
      node.setAttribute("fill", Colour.antigen(a));
      node.setAttribute("fill-opacity", a.ref ? 0.55 : 0.85);
      // #10: passage is shown by shape — no passage ring. Vaccine/ref get a black
      // outline; everything else a thin neutral edge. Remember the base stroke so F2
      // can restore it when the new-since highlight turns off.
      const baseStroke = a.vac ? "#000" : a.ref ? "#000" : "rgba(0,0,0,.35)";
      const baseSW = a.vac ? 1.6 : a.ref ? 1.3 : 0.6;
      node.setAttribute("stroke", baseStroke); node.setAttribute("stroke-width", baseSW);
      node.setAttribute("data-norm", a.norm);
      node.addEventListener("mouseenter", e => { State.setActive(a.norm); IV.UI.showTip(e, agHtml(a)); });
      node.addEventListener("mousemove", IV.UI.moveTip);
      node.addEventListener("mouseleave", () => { State.setActive(null); IV.UI.hideTip(); });
      svg.appendChild(node);
      (nodes[a.norm] = nodes[a.norm] || []).push(node);
      plc.push({ el: node, shape: sh.shape, rot: sh.rot || 0, x: a.x, y: a.y, r });
      hi.push({ el: node, norm: a.norm, clade: a.clade, serum: false, a: a, nw: a.new || 0, baseStroke, baseSW });
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

    base = computeBase(all, W, H, 3.5);
    view = { k: 1, tx: 0, ty: 0 };   // new chart / re-render fits the whole map
    recomputeGeom();

    gridG = el("g", { class: "gridLayer", "pointer-events": "none" });
    svg.appendChild(gridG);          // first child → behind all points
    drawGrid();

    const out = paintChart(svg, chart, geom, { r0: 3.5 });
    hiList = out.hi; placed = out.placed;
    applyNewHighlight();     // F2: re-apply new-since highlight to the fresh nodes
    _covKey = coverageKey(); applyCoverageTo(hiList);   // F3: coverage outline (fill is from paintChart)

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
  //   wheel               → zoom to cursor (plain scroll-to-zoom; pinch/ctrl/cmd too)
  //   pan (#feature)      → hold Space + drag, OR the pan-tool toggle, OR right/middle
  //                         drag, OR shift+wheel. Pan-tool/Space suppress box-select.
  //   double-click        → reset;  on-map +/-/pan buttons
  let panMode = false, spaceHeld = false, overMap = false, panBtn = null;
  function panArmed() { return panMode || spaceHeld; }
  function setCursor(grabbing) {
    const svg = document.getElementById("mapSvg");
    if (svg) svg.style.cursor = grabbing ? "grabbing" : (panArmed() ? "grab" : "");
  }
  function reflectPan() {
    if (panBtn) { panBtn.style.background = panMode ? "#1558d6" : ""; panBtn.style.color = panMode ? "#fff" : ""; }
    setCursor(false);
  }
  function bindViewHandlers(svg) {
    if (handlersBound) return;
    handlersBound = true;

    svg.addEventListener("mouseenter", () => { overMap = true; });
    svg.addEventListener("mouseleave", () => { overMap = false; });

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
    svg.addEventListener("mousedown", e => {
      if (!geom) return;
      // pan on: any non-left button, OR left button while the pan tool / Space is armed.
      if (!(e.button !== 0 || panArmed())) return;        // else let S1 box-select run
      if (e.button === 0) e.stopImmediatePropagation();   // suppress S1 for armed left-drag
      e.preventDefault(); panDrag = { x: e.clientX, y: e.clientY }; setCursor(true);
    });
    svg.addEventListener("contextmenu", e => { if (panDrag) e.preventDefault(); });
    window.addEventListener("mousemove", e => {
      if (!panDrag) return;
      view.tx += e.clientX - panDrag.x; view.ty += e.clientY - panDrag.y;
      panDrag = { x: e.clientX, y: e.clientY }; clampView(); scheduleApply();
    });
    window.addEventListener("mouseup", () => { if (panDrag) { panDrag = null; setCursor(false); } });
    svg.addEventListener("dblclick", e => { e.preventDefault(); resetView(); });

    // Space = temporary hand tool, but only while hovering the map (so Space still
    // works for focused controls / typing elsewhere).
    const typing = () => { const a = document.activeElement; return a && /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName); };
    window.addEventListener("keydown", e => {
      if (e.code === "Space" && overMap && !typing() && !spaceHeld) { spaceHeld = true; e.preventDefault(); setCursor(false); }
    });
    window.addEventListener("keyup", e => { if (e.code === "Space") { spaceHeld = false; setCursor(false); } });

    // on-map controls. #3: move the cluster to the BOTTOM-right so it isn't hidden
    // under the Overlays panel (lines.js, top-right). Add a discoverable pan toggle.
    const mapCtl = document.querySelector(".mapCtl");
    if (mapCtl) {
      mapCtl.style.top = "auto"; mapCtl.style.bottom = "8px";
      panBtn = document.createElement("button");
      panBtn.id = "mapPan"; panBtn.type = "button";
      panBtn.title = "Pan tool (toggle) — or hold Space and drag, or drag with the right button. Scroll = zoom; plain drag = box-select.";
      panBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v18M3 12h18M12 3l-3 3M12 3l3 3M12 21l-3-3M12 21l3-3M3 12l3-3M3 12l3 3M21 12l-3-3M21 12l-3 3"/></svg>';
      panBtn.onclick = () => { panMode = !panMode; reflectPan(); };
      mapCtl.insertBefore(panBtn, mapCtl.firstChild);
    }
    const zi = document.getElementById("mapZoomIn");
    const zo = document.getElementById("mapZoomOut");
    const zr = document.getElementById("mapZoomReset");
    const ctr = () => { const w = document.getElementById("mapWrap"); return [(w.clientWidth || 600) / 2, (w.clientHeight || 600) / 2]; };
    if (zi) zi.onclick = () => { const c = ctr(); zoomAt(c[0], c[1], 1.4); };
    if (zo) zo.onclick = () => { const c = ctr(); zoomAt(c[0], c[1], 1 / 1.4); };
    if (zr) zr.onclick = resetView;

    // discoverability: a faint one-line hint along the map bottom (between the
    // bottom-left stress readout and the bottom-right controls).
    const wrap = document.getElementById("mapWrap");
    if (wrap && !document.getElementById("mapHint")) {
      const h = document.createElement("div");
      h.id = "mapHint";
      h.style.cssText = "position:absolute;left:50%;bottom:8px;transform:translateX(-50%);" +
        "font-size:10.5px;color:#999;background:rgba(255,255,255,.8);padding:2px 8px;border-radius:4px;" +
        "pointer-events:none;z-index:4;white-space:nowrap;";
      h.textContent = "scroll = zoom · Space- or right-drag = pan · drag = box-select · dbl-click = reset";
      wrap.appendChild(h);
    }
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
    if (_f2r !== State.showNewReport || _f2v !== State.showNewVCM) {
      _f2r = State.showNewReport; _f2v = State.showNewVCM; applyNewHighlight();
    }
    // F3 serum-coverage colour mode: re-paint fill + pink/black outline when the
    // selected serum (covSerum) changes — Colour.antigen()/coverageOutline() depend
    // on it, but a selection change fires only a notify (no re-render).
    const ck = coverageKey();
    if (ck !== _covKey) { _covKey = ck; applyCoverageTo(hiList); }
  }

  // ---- F3: serum-coverage colour mode --------------------------------------
  // colorBy === "coverage" only *shows* once a serum is selected. coverageKey()
  // changes whenever the active serum changes, so panels re-paint exactly then.
  let _covKey = "";
  function coverageKey() {
    if (State.colorBy !== "coverage") return "";
    const s = Colour.coverageSerum && Colour.coverageSerum();
    return "cov:" + (s ? s.i : "none");
  }
  function applyCoverageTo(list) {
    if (State.colorBy !== "coverage") return;
    for (const n of list) {
      if (n.serum || !n.a) continue;
      n.el.setAttribute("fill", Colour.antigen(n.a));   // pale untitrated / bright titrated
      const o = Colour.coverageOutline(n.a);
      if (o) { n.el.setAttribute("stroke", o.stroke); n.el.setAttribute("stroke-width", o.width); }
      else { n.el.setAttribute("stroke", n.baseStroke); n.el.setAttribute("stroke-width", n.baseSW); }
    }
  }

  // F2 (v6): bold BLACK outline on "new since report/VCM" antigens, raised to front.
  // Driven by Agent-SELECT's State.showNewReport (new>=1) / showNewVCM (new==2);
  // width 3 for new=1, 6 for new=2 (chart_modifier). Restores the base stroke when off.
  let _f2r = false, _f2v = false;
  // Outline width for an antigen given its `new` value and the active toggles, or 0.
  // Shared with IV.Grid so the small multiples highlight identically.
  function newOutlineWidth(nw) {
    if (!nw) return 0;
    let w = 0;
    if (State.showNewReport && nw >= 1) w = nw === 2 ? 6 : 3;
    if (State.showNewVCM && nw === 2) w = 6;
    return w;
  }
  // Apply the new-since highlight to a hi-list of {el, serum, nw, baseStroke, baseSW}
  // within `svg`, restoring base strokes when off and raising highlighted to front.
  function applyNewTo(list, svg) {
    const front = [];
    for (const n of list) {
      if (n.serum || !n.nw) continue;
      const w = newOutlineWidth(n.nw);
      if (w) { n.el.setAttribute("stroke", "#000"); n.el.setAttribute("stroke-width", w); front.push(n.el); }
      else { n.el.setAttribute("stroke", n.baseStroke); n.el.setAttribute("stroke-width", n.baseSW); }
    }
    if (svg) for (const el of front) svg.appendChild(el);   // raise to front
  }
  function applyNewHighlight() { applyNewTo(hiList, document.getElementById("mapSvg")); }

  IV.Map = {
    render, refresh, paintChart, gridLineEls,
    applyNewHighlight: applyNewTo,   // F2: shared with IV.Grid for the small multiples
    applyCoverage: applyCoverageTo,  // F3: coverage fill+outline, shared with IV.Grid
    coverageKey,                     // F3: gate grid re-paint on serum change
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
