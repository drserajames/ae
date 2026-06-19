// grid.js — all-centres grid of small multiples (G1)
//
// Owns the "all centres at once" view: a grid of small map panels (one per chart
// in DATA.charts), all linked to the shared tree and to each other through
// IV.State. Each panel projects its OWN chart independently (centres have their
// own orientations); linkage is by strain `norm`, not by coordinate alignment —
// hovering/selecting a strain in any panel (or the tree) highlights it everywhere.
//
// Point drawing is reused from IV.Map.paintChart so the grid stays in sync with the
// single map's styling (clade fill, passage rings, ref/vaccine/serum glyphs). The
// View control (single / all centres) is wired here, self-contained.
//
// Structure vs repaint: the cell/title/svg DOM and IV.installSelect (which adds
// window listeners and is keyed on the svg node) are built ONCE per panel. Recolour
// / refresh only clears+repaints each existing svg's contents — it never recreates
// nodes, so window listeners don't accumulate and installSelect runs once per panel.
(function (IV) {
  "use strict";
  const State = IV.State, el = IV.el;

  // fixed small-multiple size — deterministic (no layout measurement needed, so it
  // renders identically headless). PW matches the template's 3-column min track so
  // the svg never overflows its panel (#5). R0 = the per-point radius passed to
  // paintChart; the fit is padded by the largest rendered radius below.
  const PW = 300, PH = 260, PAD_BASE = 12, R0 = 2.2;

  let panels = [];          // [{ chart, svg, nodes }]  (svg nodes are stable)
  let structureBuilt = false;
  let activeView = "single";
  let lastColorBy = null;
  let _covKey = "";         // F3: last coverage key (serum) the panels were painted for

  // Fit one chart's points into a PW×PH panel (its own orientation, y flipped).
  function fitProj(chart) {
    const all = chart.antigens.filter(a => a.x != null && a.y != null)
      .concat(chart.sera.filter(s => s.x != null && s.y != null));
    if (!all.length) return null;
    const xs = all.map(p => p.x), ys = all.map(p => p.y);
    const xmin = Math.min(...xs), xmax = Math.max(...xs);
    const ymin = Math.min(...ys), ymax = Math.max(...ys);
    const spanX = xmax - xmin || 1, spanY = ymax - ymin || 1;
    // pad by the largest rendered point radius so edge points (vaccines) stay
    // fully on-panel instead of being clipped at the border (#5).
    let maxR = R0;
    for (const p of all) {
      const r = p.vac ? R0 * 2.2 : p.ref ? R0 * 1.43 : (p.serum_id != null) ? R0 * 1.7 : R0;
      if (r > maxR) maxR = r;
    }
    const pad = PAD_BASE + maxR + 2;
    const scale = Math.min((PW - 2 * pad) / spanX, (PH - 2 * pad) / spanY);
    const ox = (PW - spanX * scale) / 2, oy = (PH - spanY * scale) / 2;
    return { SX: x => ox + (x - xmin) * scale, SY: y => oy + (ymax - y) * scale, scale, xmin, ymax };
  }

  // Build the cell/title/svg DOM once, install selection once per svg. The chart set
  // is fixed for the life of the document, so this runs a single time.
  function buildStructure() {
    const wrap = document.getElementById("gridWrap");
    if (!wrap) return;
    // #8: let the grid scroll inside the pane instead of overflowing into the legend.
    // min-height:0 frees the flex item to shrink; .scroll already gives overflow:auto.
    wrap.style.minHeight = "0";
    wrap.innerHTML = ""; panels = [];
    IV.DATA.charts.forEach(chart => {
      const cell = document.createElement("div"); cell.className = "gridPanel";
      const ttl = document.createElement("div"); ttl.className = "gridPanelTitle";
      ttl.textContent = `${chart.label} — ${chart.n_antigens} ag, ${chart.n_sera} sr`;
      const holder = document.createElement("div"); holder.className = "gridPanelMap";
      const svg = el("svg", { width: PW, height: PH });
      holder.appendChild(svg); cell.appendChild(ttl); cell.appendChild(holder);
      wrap.appendChild(cell);
      IV.installSelect(svg);   // ONCE per svg: box / click select → shared selection
      panels.push({ chart, svg, hi: [] });
    });
    structureBuilt = true;
    lastColorBy = null;        // force the next paint
  }

  // Clear + repaint every existing panel svg (reusing the same svg nodes).
  function paintPanels() {
    lastColorBy = State.colorBy;
    panels.forEach(p => {
      p.svg.innerHTML = "";
      const proj = fitProj(p.chart);
      if (proj) {
        // #7: 1-AU gridlines behind the points (static — panels don't zoom)
        const g = el("g", { class: "gridLayer", "pointer-events": "none" });
        for (const ln of IV.Map.gridLineEls(proj.SX, proj.SY, proj.scale, proj.xmin, proj.ymax, PW, PH))
          g.appendChild(ln);
        p.svg.appendChild(g);
        p.hi = IV.Map.paintChart(p.svg, p.chart, proj, { r0: R0 }).hi;
      } else {
        p.hi = [];
        const t = el("text", { x: PW / 2, y: PH / 2, "text-anchor": "middle", fill: "#999", "font-size": 12 });
        t.textContent = "no positioned points"; p.svg.appendChild(t);
      }
    });
    applyHighlight();
  }

  function applyHighlight() {
    // F3: re-paint coverage fill+outline only when the selected serum changes.
    const ck = IV.Map.coverageKey ? IV.Map.coverageKey() : "";
    const covChanged = ck !== _covKey; _covKey = ck;
    panels.forEach(p => {
      (p.hi || []).forEach(n => {
        const extraHidden = !n.serum && State.onlyMatched && !IV.Tree.normToLeaves[n.norm];
        const e = State.emphasis(n.norm, n.clade, extraHidden);
        n.el.classList.toggle("dim", e.dim);
        n.el.classList.toggle("lift", e.lift);
        n.el.classList.toggle("sel", e.sel);
      });
      // v7 #3: new-since is a dim-the-others emphasis now (handled by the loop above
      // via State.emphasis()), no bold outline. F3 coverage re-paints on serum change.
      if (covChanged) IV.Map.applyCoverage(p.hi || []);
    });
  }

  // Bring the grid up to date for the current colorBy (repaint only if it changed).
  function sync() {
    if (!structureBuilt) buildStructure();
    if (lastColorBy !== State.colorBy) paintPanels(); else applyHighlight();
  }

  function refresh() {
    if (activeView !== "grid" || !structureBuilt) return;
    if (lastColorBy !== State.colorBy) { paintPanels(); return; }  // recolour → repaint
    applyHighlight();
  }

  function setView(mode) {
    activeView = mode;
    const single = mode === "single";
    const mapWrap = document.getElementById("mapWrap");
    const gridWrap = document.getElementById("gridWrap");
    if (mapWrap) mapWrap.style.display = single ? "" : "none";
    if (gridWrap) gridWrap.style.display = single ? "none" : "";
    const cs = document.getElementById("chartSel"); if (cs) cs.disabled = !single;
    const mt = document.getElementById("mapTitle");
    if (!single) {
      sync();
      if (mt) mt.textContent = `Antigenic maps — all ${IV.DATA.charts.length} centres`;
    } else if (mt) {
      const ch = IV.DATA.charts[State.chartIdx];
      mt.textContent = `Antigenic map — ${ch.label}: ${ch.name}`;
    }
  }

  // Wire the View toggle (markup lives in the template's map pane title row).
  const sel = document.getElementById("viewMode");
  if (sel) sel.onchange = () => setView(sel.value);

  IV.Grid = { render: sync, refresh, setView };
  State.subscribe(refresh);
})(window.IV);
