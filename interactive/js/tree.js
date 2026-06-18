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
        (("A" in node) ? "No AA substitutions on this branch."
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

  // tip outline marks passage (P1): coloured ring for a known passage type, else
  // neutral grey. Fill stays the clade/continent colour from Colour.leaf.
  function tipStroke(lf) {
    const pc = lf.passage ? Colour.passageColor(lf.passage) : null;
    return pc || "rgba(0,0,0,.35)";
  }
  function tipStrokeW(lf) {
    return (lf.passage && Colour.passageColor(lf.passage)) ? 1.7 : 0.7;
  }

  function render() {
    ensureStyle();
    computeFit();
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
      const c = el("circle", { class: "tip", r: 3, fill: Colour.leaf(lf), "data-norm": lf.norm });
      c.setAttribute("stroke", tipStroke(lf));
      c.setAttribute("stroke-width", tipStrokeW(lf));
      c.addEventListener("mouseenter", e => { State.setActive(lf.norm); IV.UI.showTip(e, tipHtml(lf)); });
      c.addEventListener("mousemove", IV.UI.moveTip);
      c.addEventListener("mouseleave", () => { State.setActive(null); IV.UI.hideTip(); });
      tipsG.appendChild(c);
      (tipNodes[lf.norm] = tipNodes[lf.norm] || []).push(c);
      const t = el("text", { class: "tipLabel" });
      t.textContent = shortName(lf.name);
      tipsG.appendChild(t);
      tipEntries.push({ node: lf, circle: c, label: t });
    });

    IV.installSelect(svg);   // S1: click / drag-box selection (shared, idempotent)
    bindViewport(svg);
    apply();
    refresh();
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
      t.circle.setAttribute("cx", cx);
      t.circle.setAttribute("cy", cy);
      if (showLabels && cy >= -6 && cy <= fit.H + 6 && cx <= fit.W) {
        t.label.setAttribute("x", cx + 5);
        t.label.setAttribute("y", cy + 3);
        t.label.style.display = "";
      } else {
        t.label.style.display = "none";
      }
    }
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
