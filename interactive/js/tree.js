// tree.js — phylogram render + highlight (owns tree layout & tip nodes)
//
// Exposes IV.Tree.leaves / IV.Tree.normToLeaves so the map and UI can resolve
// strain linkage without re-walking the tree. Subscribes to IV.State so hover /
// clade-filter changes re-apply highlight to its own tips.
(function (IV) {
  "use strict";
  const State = IV.State, Colour = IV.Colour, el = IV.el;

  let leaves = [];           // leaf nodes, top-to-bottom order
  let normToLeaves = {};     // norm -> [leaf node]
  let maxX = 0;
  let tipNodes = {};         // norm -> [circle elements]

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

  function tipHtml(lf) {
    return `<b>${lf.name}</b><br>${lf.date || "?"} · ${lf.country || lf.continent || ""}` +
      (lf.clade ? `<br>clade: <b>${lf.clade}</b>` : "") +
      (lf.ag && lf.ag.length ? `<br>${lf.ag.length} antigen(s) on map` : "<br><i>no antigen on this map</i>");
  }

  function render() {
    const svg = document.getElementById("treeSvg");
    svg.innerHTML = "";
    tipNodes = {};
    const rowH = 11, padL = 8, padR = 160, padT = 10;
    const H = padT * 2 + leaves.length * rowH;
    const innerW = 360;
    const W = padL + innerW + padR;
    svg.setAttribute("width", W); svg.setAttribute("height", H);
    const sx = x => padL + (maxX ? (x / maxX) * innerW : 0);
    const sy = y => padT + y * rowH;

    // edges
    (function edges(n) {
      const px = sx(n.x), py = sy(n._y);
      (n.children || []).forEach(c => {
        const cx = sx(c.x), cy = sy(c._y);
        svg.appendChild(el("path", { class: "edge", d: `M${px},${py} V${cy} H${cx}` }));
        edges(c);
      });
    })(IV.DATA.tree);

    // tips
    leaves.forEach(lf => {
      const cx = sx(lf.x), cy = sy(lf._y);
      const c = el("circle", { class: "tip", cx, cy, r: 3, fill: Colour.leaf(lf), "data-norm": lf.norm });
      c.addEventListener("mouseenter", e => { State.setActive(lf.norm); IV.UI.showTip(e, tipHtml(lf)); });
      c.addEventListener("mousemove", IV.UI.moveTip);
      c.addEventListener("mouseleave", () => { State.setActive(null); IV.UI.hideTip(); });
      svg.appendChild(c);
      (tipNodes[lf.norm] = tipNodes[lf.norm] || []).push(c);
      const t = el("text", { x: cx + 5, y: cy + 3, "font-size": 9, fill: "#333" });
      t.textContent = lf.name.replace(/_[A-Za-z0-9]+_[0-9A-Fa-f]+$/, "");
      svg.appendChild(t);
    });
  }

  function refresh() {
    leaves.forEach(lf => {
      (tipNodes[lf.norm] || []).forEach(c => {
        const hidden = State.isCladeHidden(lf.clade);
        c.classList.toggle("dim", hidden || (State.active && lf.norm !== State.active));
        c.classList.toggle("lift", State.active && lf.norm === State.active);
      });
    });
  }

  IV.Tree = {
    layout, render, refresh,
    get leaves() { return leaves; },
    get normToLeaves() { return normToLeaves; },
  };
  State.subscribe(refresh);
})(window.IV);
