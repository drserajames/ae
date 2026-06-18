// tree.js — phylogram render + highlight (owns tree layout, tip nodes, tree viewport)
//
// Renders the pruned phylogenetic tree fit-to-pane by default (T2), with clean
// parent→child elbow edges and no gaps (T1), and an independent viewport (T3):
// two-finger / wheel scroll pans, ctrl/⌘ + wheel (or trackpad pinch) zooms around
// the cursor, double-click resets to fit. Clicking a branch opens an amino-acid
// substitutions panel and selects the subtree below it (T4). Tip passage
// (egg/cell/reassortant) is marked on the tip outline via the shared Colour API (P1).
//
// Coordination: left-drag box-selection + the selection store are owned by S1
// (IV.installSelect / IV.State); this module reuses them — branch clicks go through
// State.setSelection so the map highlights too, and refresh() uses State.emphasis.
// Panning is deliberately on wheel/scroll (not drag) so it never fights S1's drag.
//
// Zoom model: the tree is anisotropic — x is a tiny genetic distance, y indexes
// 1570 tip rows — so a *uniform* zoom scatters siblings off-screen. Instead the X
// (genetic-distance) axis is always fit to the pane width, and zoom/pan act on the
// Y (tip) axis: scroll pans through tips, ctrl/pinch-scroll expands/contracts tip
// spacing so labels become legible. This is the standard tall-phylogram interaction.
//
// Coordinate model: edges live in *tree space* (x = cumulative branch length,
// y = leaf-row index) inside one transformed <g>, so pan/zoom is a single cheap
// matrix update with non-scaling strokes. Tips/labels are positioned in *screen
// space* (1 svg user unit == 1 px, no viewBox — S1's box-select relies on that) so
// markers keep a constant pixel size; a non-uniform group scale would turn the tip
// circles into ellipses. Both share the same matrix params.
(function (IV) {
  "use strict";
  const State = IV.State, Colour = IV.Colour, el = IV.el;

  let leaves = [];           // leaf nodes, top-to-bottom order
  let normToLeaves = {};     // norm -> [leaf node]
  let maxX = 0;              // max cumulative branch length (tree-space x extent)
  let tipNodes = {};         // norm -> [circle elements]
  let tipEntries = [];       // [{node, circle, label}] for fast reposition on zoom/pan
  let edgesG = null;         // transformed <g> holding the edge path + branch hit paths
  let infoOpen = false;      // is the T4 AA panel showing?

  // viewport: X is always fit (screen_x = pad + kx*tx). Y zooms/pans:
  // screen_y = z*ky*ty + (z*pad + Ty). z=1, Ty=0 fits the whole tree to the pane.
  const view = { z: 1, Ty: 0 };
  const fit = { kx: 1, ky: 1, pad: 16, W: 600, H: 600 };
  let pendingApply = false;

  const clamp = (v, lo, hi) => v < lo ? lo : (v > hi ? hi : v);
  const shortName = s => s.replace(/_[A-Za-z0-9]+_[0-9A-Fa-f]+$/, "");
  const esc = s => String(s).replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

  // ---- layout: leaf order + node y (midpoint of children) ----
  function layout(root) {
    leaves = []; normToLeaves = {}; maxX = 0;
    (function walk(n) {
      if (!n.children || !n.children.length) leaves.push(n);
      else n.children.forEach(walk);
    })(root);
    leaves.forEach((lf, i) => { lf._y = i; if (lf.x > maxX) maxX = lf.x; });
    (function setY(n) {
      if (!n.children || !n.children.length) return n._y;
      const ys = n.children.map(setY);
      n._y = (Math.min(...ys) + Math.max(...ys)) / 2;
      return n._y;
    })(root);
    // leaf-row range [_lo,_hi] per node, for clade MRCA lookup (F4)
    (function range(n) {
      if (!n.children || !n.children.length) { n._lo = n._hi = n._y; return; }
      let lo = Infinity, hi = -Infinity;
      n.children.forEach(c => { range(c); lo = Math.min(lo, c._lo); hi = Math.max(hi, c._hi); });
      n._lo = lo; n._hi = hi;
    })(root);
    leaves.forEach(lf => { (normToLeaves[lf.norm] = normToLeaves[lf.norm] || []).push(lf); });
  }

  // ---- fit-to-pane base mapping (T2) ----
  function computeFit() {
    const sc = document.getElementById("treeScroll");
    fit.W = sc.clientWidth || 600;
    fit.H = sc.clientHeight || 600;
    fit.kx = (fit.W - 2 * fit.pad) / (maxX || 1);
    fit.ky = (fit.H - 2 * fit.pad) / Math.max(leaves.length - 1, 1);
  }
  function resetView() { view.z = 1; view.Ty = 0; }

  // matrix params: screen_x = a*tx + e (X always fit), screen_y = d*ty + f (Y zoom/pan)
  function mat() {
    return {
      a: fit.kx, e: fit.pad,
      d: view.z * fit.ky, f: view.z * fit.pad + view.Ty,
    };
  }

  // ---- styles + amino-acid substitutions panel (T4) ----
  function ensureStyle() {
    if (document.getElementById("treeStyle")) return;
    const s = document.createElement("style");
    s.id = "treeStyle";
    s.textContent = `
      #treeScroll { overflow:hidden; position:relative; }
      .edge { stroke:#999; stroke-width:1; fill:none; vector-effect:non-scaling-stroke; }
      .ehit { stroke:transparent; stroke-width:8; fill:none; vector-effect:non-scaling-stroke; cursor:pointer; }
      .tipLabel { font-size:9px; fill:#333; pointer-events:none; }
      .cladeLabel { font-size:11px; font-weight:700; pointer-events:none;
        paint-order:stroke; stroke:#fff; stroke-width:3px; stroke-linejoin:round; }
      .treeHud { position:absolute; left:8px; bottom:8px; font-size:10px; color:#888;
        background:rgba(255,255,255,.8); padding:2px 6px; border-radius:4px; pointer-events:none; z-index:4; }
      #treeInfo { position:absolute; top:8px; right:8px; width:232px; max-height:72%; overflow:auto;
        background:rgba(255,255,255,.97); border:1px solid #ccc; border-radius:6px; font-size:11px;
        box-shadow:0 2px 8px rgba(0,0,0,.12); z-index:6; display:none; }
      #treeInfo .ti-h { display:flex; align-items:center; gap:6px; font-weight:600; padding:6px 8px;
        border-bottom:1px solid #eee; }
      #treeInfo .ti-x { margin-left:auto; cursor:pointer; color:#999; font-weight:700; }
      #treeInfo .ti-x:hover { color:#333; }
      #treeInfo .ti-body { padding:6px 8px; line-height:1.5; }
      #treeInfo .ti-sub { color:#777; }
      #treeInfo .aa { display:inline-block; font-family:ui-monospace,Menlo,monospace; background:#f0f0f3;
        border:1px solid #e0e0e6; border-radius:3px; padding:0 3px; margin:1px 2px 1px 0; }
      #treeInfo .aa .pos { font-weight:600; }
    `;
    document.head.appendChild(s);
  }

  function infoBox() {
    let box = document.getElementById("treeInfo");
    if (!box) {
      const pane = document.getElementById("treePane");
      pane.style.position = "relative";
      box = document.createElement("div");
      box.id = "treeInfo";
      pane.appendChild(box);
    }
    return box;
  }
  function hideInfo() {
    infoOpen = false;
    const box = document.getElementById("treeInfo");
    if (box) box.style.display = "none";
  }

  function subtreeNorms(node) {
    const out = [];
    (function walk(n) {
      if (!n.children || !n.children.length) { if (n.norm) out.push(n.norm); }
      else n.children.forEach(walk);
    })(node);
    return out;
  }

  // click a branch (T4): show its AA substitutions + select the subtree below it.
  function onBranch(node) {
    ensureStyle();
    const norms = subtreeNorms(node);
    State.setSelection(norms);   // shared store → tree + map both highlight the clade
    const A = node.A || [];
    const title = node.name ? esc(shortName(node.name))
      : (node.id != null ? "node " + node.id : "internal branch");
    let body = `<div class="ti-sub">${norms.length} tip(s) below — selected on both panels</div>`;
    if (A.length) {
      body += `<div style="margin-top:5px">AA substitutions on this branch:</div><div style="margin-top:3px">` +
        A.map(s => `<span class="aa">${esc(s.from || "")}<span class="pos">${esc(s.pos)}</span>${esc(s.to || "")}</span>`).join("") +
        `</div>`;
    } else {
      body += `<div class="ti-sub" style="margin-top:5px">` +
        (IV.DATA.meta && IV.DATA.meta.aa_transitions
          ? "No AA substitutions on this branch."
          : "AA substitutions not in this bundle (exporter E1 pending).") + `</div>`;
    }
    const box = infoBox();
    box.innerHTML = `<div class="ti-h">${title}<span class="ti-x" title="close">×</span></div>` +
      `<div class="ti-body">${body}</div>`;
    box.querySelector(".ti-x").onclick = () => { hideInfo(); State.clearSelection(); };
    box.style.display = "block";
    infoOpen = true;
  }

  // ---- render ----
  function tipHtml(lf) {
    const pass = lf.passage ? `<br>passage: <b>${esc(lf.passage)}</b>` : "";
    return `<b>${esc(lf.name)}</b><br>${esc(lf.date || "?")} · ${esc(lf.country || lf.continent || "")}` +
      (lf.clade ? `<br>clade: <b>${esc(lf.clade)}</b>` : "") + pass +
      (lf.ag && lf.ag.length ? `<br>${lf.ag.length} antigen(s) on map` : "<br><i>no antigen on this map</i>");
  }

  // tip outline marks passage (P1), mirroring the map (map.js passageStroke): ring
  // ONLY the salient passages (egg / reassortant). cell is the overwhelming default,
  // so ringing every cell tip would bury the clade fills.
  function passageStroke(lf) {
    if (!(Colour.hasPassageMarkers && Colour.hasPassageMarkers())) return null;
    const t = lf.passage;
    return (t && t !== "cell") ? Colour.passageColor(t) : null;
  }

  // ---- per-tip glyphs (F2 vaccine / F3 serology / F7 egg), via the shared IV.Glyph
  // factory so the tree and map draw identical shapes. vaccine + serology are
  // antigen-level (not on the tree leaf), so resolve them per norm across ALL charts
  // — a vaccine/serology strain is a strain property, independent of active centre.
  let normMeta = {};   // norm -> {vac, serology}
  function buildNormMeta() {
    normMeta = {};
    for (const ch of IV.DATA.charts) for (const a of ch.antigens) {
      if (!a.norm) continue;
      const m = normMeta[a.norm] || (normMeta[a.norm] = { vac: false, serology: false });
      if (a.vac) m.vac = true;
      if (a.serology) m.serology = true;
    }
  }
  const TIP_R = { circle: 3, serology: 4.4, egg: 4, reassortant: 4, star: 6.5 };
  // role priority: vaccine > egg/reassortant (passage shape) > serology > default.
  function tipGlyph(lf) {
    const m = normMeta[lf.norm];
    if (m && m.vac) return { kind: "star", r: TIP_R.star };
    if (lf.passage === "egg") return { kind: "egg", r: TIP_R.egg };
    if (lf.passage === "reassortant") return { kind: "reassortant", r: TIP_R.reassortant };
    if (m && m.serology) return { kind: "circle", r: TIP_R.serology };
    return { kind: "circle", r: TIP_R.circle };
  }
  // glyphs must be positioned by GEOMETRY (cx/cy or path d) not by a transform —
  // S1's box-select reads getBBox(), which ignores an element's own transform.
  function glyphPathD(kind, cx, cy, r) {
    switch (kind) {
      case "star": return IV.Glyph.starPath(cx, cy, r, 5, 0.46);
      case "egg": return IV.Glyph.eggPath(cx, cy, r);
      case "reassortant": return IV.Glyph.reassortantPath(cx, cy, r);
      default: return null;
    }
  }
  function tipStrokeFor(lf, kind) {
    if (kind === "star") return "#000";                 // vaccine: dark outline
    return passageStroke(lf) || "rgba(0,0,0,.35)";      // egg/reassortant passage colour
  }
  function tipStrokeWFor(lf, kind) {
    if (kind === "star") return 1.0;
    return passageStroke(lf) ? 1.3 : 0.7;
  }

  // ---- clade labels at each clade's MRCA, like the report PDFs (F4) ----
  let cladeLabels = [];   // [{clade, x(tree), row, color, text, prio, el}]
  function computeCladeLabels(root) {
    cladeLabels = [];
    const byClade = {};
    leaves.forEach(lf => { if (lf.clade) (byClade[lf.clade] = byClade[lf.clade] || []).push(lf._y); });
    const prio = IV.DATA.clade_priority || {};
    for (const clade in byClade) {
      const rows = byClade[clade];
      if (rows.length < 4) continue;                    // skip tiny clades (clutter)
      const lo = Math.min(...rows), hi = Math.max(...rows);
      // MRCA = smallest node whose leaf-range [_lo,_hi] still contains [lo,hi]
      let node = root;
      for (;;) {
        const child = (node.children || []).find(c => c._lo <= lo && c._hi >= hi);
        if (!child) break;
        node = child;
      }
      cladeLabels.push({
        clade, x: node.x, row: (lo + hi) / 2, rowLo: lo, rowHi: hi,
        color: Colour.cladeColor(clade),
        text: (Colour.cladeLegend ? Colour.cladeLegend(clade) : clade) || clade,
        prio: (prio[clade] != null ? prio[clade] : 9999),
      });
    }
  }
  // position labels each frame with a greedy vertical de-overlap; lower clade_priority
  // wins a contested slot (matches the report's clade emphasis).
  function placeCladeLabels(m) {
    const placed = [], top = 6, bot = fit.H - 4;
    cladeLabels.slice().sort((a, b) => a.prio - b.prio).forEach(L => {
      if (!L.el) return;
      // show the label whenever the clade's tip band is on screen, anchored within
      // that band (so it "sticks" to the clade when zoomed/panned, not just at fit)
      const yLo = m.d * L.rowLo + m.f, yHi = m.d * L.rowHi + m.f;
      const y = clamp(m.d * L.row + m.f, Math.max(top, yLo), Math.min(bot, yHi));
      const onScreen = yHi >= top && yLo <= bot;
      const collide = placed.some(py => Math.abs(py - y) < 13);
      if (onScreen && !collide) {
        L.el.setAttribute("x", clamp(m.a * L.x + m.e + 6, 2, fit.W - 4));
        L.el.setAttribute("y", y + 3);
        L.el.style.display = "";
        placed.push(y);
      } else {
        L.el.style.display = "none";
      }
    });
  }

  function render() {
    ensureStyle();
    computeFit();
    buildNormMeta();
    computeCladeLabels(IV.DATA.tree);
    const svg = document.getElementById("treeSvg");
    svg.innerHTML = "";
    tipNodes = {}; tipEntries = [];
    svg.setAttribute("width", fit.W);
    svg.setAttribute("height", fit.H);   // no viewBox: 1 user unit == 1 px (S1 box-select)

    // edges in tree-space inside one transformed group (T1 clean elbows; T3 pan/zoom)
    edgesG = el("g", { id: "treeEdges" });
    svg.appendChild(edgesG);
    let dAll = "";
    const hitG = el("g");
    (function edges(n) {
      const kids = n.children || [];
      if (!kids.length) return;
      const ys = kids.map(c => c._y);
      dAll += `M${n.x} ${Math.min(...ys)}V${Math.max(...ys)}`;   // one riser, no gaps
      kids.forEach(c => {
        dAll += `M${n.x} ${c._y}H${c.x}`;                        // horizontal into child
        const hit = el("path", { class: "ehit", d: `M${n.x} ${c._y}H${c.x}` });
        // keep S1's box-select from starting on a branch press; act on click
        hit.addEventListener("mousedown", ev => ev.stopPropagation());
        hit.addEventListener("click", ev => { ev.stopPropagation(); onBranch(c); });
        hitG.appendChild(hit);
        edges(c);
      });
    })(IV.DATA.tree);
    edgesG.appendChild(el("path", { class: "edge", d: dAll || "M0 0" }));
    edgesG.appendChild(hitG);

    // tips + labels in screen space (positioned in apply())
    const tipsG = el("g", { id: "treeTips" });
    svg.appendChild(tipsG);
    leaves.forEach(lf => {
      const g = tipGlyph(lf);   // {kind, r}
      const opts = {
        class: "tip", fill: Colour.leaf(lf), dataNorm: lf.norm,
        stroke: tipStrokeFor(lf, g.kind), strokeWidth: tipStrokeWFor(lf, g.kind),
      };
      // build at origin; apply() positions by geometry (cx/cy for circle, d for paths)
      const node = g.kind === "circle" ? IV.Glyph.circle(0, 0, g.r, opts)
                                       : IV.Glyph.make(g.kind, 0, 0, g.r, opts);
      node.addEventListener("mouseenter", e => { State.setActive(lf.norm); IV.UI.showTip(e, tipHtml(lf)); });
      node.addEventListener("mousemove", IV.UI.moveTip);
      node.addEventListener("mouseleave", () => { State.setActive(null); IV.UI.hideTip(); });
      tipsG.appendChild(node);
      (tipNodes[lf.norm] = tipNodes[lf.norm] || []).push(node);
      const t = el("text", { class: "tipLabel" });
      t.textContent = shortName(lf.name);
      tipsG.appendChild(t);
      tipEntries.push({ node: lf, el: node, kind: g.kind, r: g.r, label: t });
    });

    // clade labels (F4) — one text per labelled clade, positioned in apply()
    const cladeG = el("g", { id: "treeCladeLabels" });
    svg.appendChild(cladeG);
    cladeLabels.forEach(L => {
      const t = el("text", { class: "cladeLabel", fill: L.color });
      t.textContent = L.text;
      cladeG.appendChild(t);
      L.el = t;
    });

    IV.installSelect(svg);   // S1: click / drag-box selection (shared, idempotent)
    bindViewport(svg);
    apply();
    refresh();
    // background/occluded first paint can land with a zero-size pane; re-fit once size is known
    if (fit.W < 10 || fit.H < 10) {
      requestAnimationFrame(() => { computeFit(); apply(); });
      setTimeout(() => { computeFit(); apply(); }, 200);
    }
  }

  // ---- viewport apply (positions everything from view state) ----
  function apply() {
    pendingApply = false;
    if (!edgesG) return;
    const m = mat();
    edgesG.setAttribute("transform", `matrix(${m.a},0,0,${m.d},${m.e},${m.f})`);
    const showLabels = (view.z * fit.ky) >= 9;   // only label when rows are legible
    for (const t of tipEntries) {
      const cx = m.a * t.node.x + m.e, cy = m.d * t.node._y + m.f;
      if (t.kind === "circle") { t.el.setAttribute("cx", cx); t.el.setAttribute("cy", cy); }
      else t.el.setAttribute("d", glyphPathD(t.kind, cx, cy, t.r));
      if (showLabels && cy >= -6 && cy <= fit.H + 6 && cx <= fit.W) {
        t.label.setAttribute("x", cx + 5);
        t.label.setAttribute("y", cy + 3);
        t.label.style.display = "";
      } else {
        t.label.style.display = "none";
      }
    }
    placeCladeLabels(m);   // F4: reposition + de-overlap clade labels
    const hud = document.getElementById("treeHud");
    if (hud) hud.textContent = view.z <= 1.001
      ? "fit · scroll = pan tips · ⌘/ctrl+scroll or pinch = expand · drag = select · click branch = AA"
      : `${view.z.toFixed(1)}× · scroll to pan · double-click = reset`;
  }
  function scheduleApply() {
    if (pendingApply) return;
    pendingApply = true;
    requestAnimationFrame(apply);
  }

  // ---- zoom / pan (T3): vertical (tip) axis only; X stays fit to pane width ----
  // keep at least a sliver of the tree on screen (no flinging it fully out of view)
  function clampPan() {
    const hi = fit.H - 20 - view.z * fit.pad;          // top edge not below ~bottom
    const lo = 20 - view.z * (fit.H - fit.pad);        // bottom edge not above ~top
    view.Ty = clamp(view.Ty, lo, hi);
  }
  function zoomAtY(my, factor) {
    const nz = clamp(view.z * factor, 1, 120);
    if (nz <= 1.0001) { resetView(); }
    else {
      view.Ty = my - (nz / view.z) * (my - view.Ty);  // keep tree point under cursor fixed
      view.z = nz;
      clampPan();
    }
    scheduleApply();
  }

  function bindViewport(svg) {
    const sc = document.getElementById("treeScroll");
    if (sc._ivBound) return;       // bind once; survives re-render (container persists)
    sc._ivBound = true;

    const hud = document.createElement("div");
    hud.id = "treeHud"; hud.className = "treeHud";
    sc.appendChild(hud);

    // wheel: plain scroll pans through tips (vertical); ctrl/⌘ + scroll (and
    // trackpad pinch, which the browser reports as ctrl+wheel) expands tip spacing.
    sc.addEventListener("wheel", e => {
      e.preventDefault();
      if (e.ctrlKey || e.metaKey) {
        const r = svg.getBoundingClientRect();
        zoomAtY(e.clientY - r.top, Math.exp(-e.deltaY * 0.0025));
      } else {
        view.Ty -= e.deltaY;
        clampPan();
        scheduleApply();
      }
    }, { passive: false });

    sc.addEventListener("dblclick", () => { resetView(); scheduleApply(); });

    // re-fit on pane resize (keeps the tree filling its pane)
    if (window.ResizeObserver) {
      let to;
      new ResizeObserver(() => {
        clearTimeout(to);
        to = setTimeout(() => { computeFit(); resetView(); apply(); }, 120);
      }).observe(sc);
    }

    // #1: when the viewer loads behind another app, the first paint can land before
    // the pane is sized / while rAF is throttled, leaving edges + tips invisible.
    // Re-measure and re-apply *synchronously* (not via the throttled scheduleApply)
    // when the app returns to the foreground — preserving the current zoom/pan.
    const relayout = () => { computeFit(); clampPan(); apply(); };
    document.addEventListener("visibilitychange", () => { if (!document.hidden) relayout(); });
    window.addEventListener("focus", relayout);
    window.addEventListener("pageshow", relayout);
  }

  // ---- highlight refresh (hover / clade filter / selection) ----
  function refresh() {
    leaves.forEach(lf => {
      (tipNodes[lf.norm] || []).forEach(c => {
        const e = State.emphasis(lf.norm, lf.clade);
        c.classList.toggle("dim", e.dim);
        c.classList.toggle("lift", e.lift);
        c.classList.toggle("sel", e.sel);
      });
    });
    // selection cleared elsewhere (e.g. click on empty space) also closes the AA panel
    if (infoOpen && !State.hasSelection()) hideInfo();
  }

  IV.Tree = {
    layout, render, refresh,
    get leaves() { return leaves; },
    get normToLeaves() { return normToLeaves; },
  };
  State.subscribe(refresh);
})(window.IV);
