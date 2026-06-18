// map.js — antigenic map render + highlight (owns map point nodes)
//
// Plots the active chart's antigens (circles), sera (squares), references and
// vaccines (stars). Subscribes to IV.State so hover / clade-filter / only-matched
// changes re-apply highlight. Resolves tree linkage via IV.Tree.normToLeaves.
(function (IV) {
  "use strict";
  const State = IV.State, Colour = IV.Colour, el = IV.el;

  let ptNodes = {};   // norm -> [elements]
  let agByIdx = {};   // antigen index -> antigen (active chart)

  function star(cx, cy, spikes, inner, outer) {
    let rot = Math.PI / 2 * 3, step = Math.PI / spikes, p = `M${cx},${cy - outer}`;
    for (let i = 0; i < spikes; i++) {
      p += `L${cx + Math.cos(rot) * outer},${cy + Math.sin(rot) * outer}`; rot += step;
      p += `L${cx + Math.cos(rot) * inner},${cy + Math.sin(rot) * inner}`; rot += step;
    }
    return p + "Z";
  }

  function agHtml(a) {
    const inTree = IV.Tree.normToLeaves[a.norm]
      ? `<br>${IV.Tree.normToLeaves[a.norm].length} tip(s) in tree`
      : "<br><i>not in tree</i>";
    return `<b>${a.name}</b>` + (a.passage ? ` <span style="opacity:.7">${a.passage}</span>` : "") +
      `<br>${a.date || "?"}` + (a.clade ? `<br>clade: <b>${a.clade}</b>` : "") +
      (a.ref ? "<br><i>reference antigen</i>" : "") + (a.vac ? "<br><b>vaccine</b>" : "") + inTree;
  }

  function render() {
    const svg = document.getElementById("mapSvg");
    const wrap = document.getElementById("mapWrap");
    const chart = IV.DATA.charts[State.chartIdx];
    svg.innerHTML = ""; ptNodes = {}; agByIdx = {};
    const pts = chart.antigens.filter(a => a.x != null && a.y != null);
    const sera = chart.sera.filter(s => s.x != null && s.y != null);
    const all = pts.concat(sera);
    if (!all.length) return;
    const xs = all.map(p => p.x), ys = all.map(p => p.y);
    const xmin = Math.min(...xs), xmax = Math.max(...xs), ymin = Math.min(...ys), ymax = Math.max(...ys);
    const W = wrap.clientWidth || 600, H = wrap.clientHeight || 600;
    const pad = 30;
    const spanX = xmax - xmin || 1, spanY = ymax - ymin || 1;
    const scale = Math.min((W - 2 * pad) / spanX, (H - 2 * pad) / spanY);
    const ox = (W - spanX * scale) / 2, oy = (H - spanY * scale) / 2;
    const SX = x => ox + (x - xmin) * scale, SY = y => oy + (ymax - y) * scale; // flip y
    svg.setAttribute("width", W); svg.setAttribute("height", H);

    // sera first (behind)
    sera.forEach(s => {
      const r = 6, x = SX(s.x) - r, y = SY(s.y) - r;
      const sq = el("rect", { class: "serum pt", x, y, width: 2 * r, height: 2 * r });
      sq.addEventListener("mouseenter", e => IV.UI.showTip(e, `<b>${s.name}</b><br><i>serum</i>`));
      sq.addEventListener("mousemove", IV.UI.moveTip);
      sq.addEventListener("mouseleave", IV.UI.hideTip);
      svg.appendChild(sq);
    });
    // antigens
    pts.forEach(a => {
      agByIdx[a.i] = a;
      const r = a.ref ? 5 : a.vac ? 6 : 3.5;
      let shape;
      if (a.vac) shape = el("path", { class: "pt", d: star(SX(a.x), SY(a.y), 6, 2.6, 5) });
      else shape = el("circle", { class: "pt", cx: SX(a.x), cy: SY(a.y), r });
      shape.setAttribute("fill", Colour.antigen(a));
      shape.setAttribute("fill-opacity", a.ref ? 0.55 : 0.85);
      shape.setAttribute("stroke", a.ref ? "#000" : "rgba(0,0,0,.3)");
      shape.setAttribute("stroke-width", a.ref ? 1.3 : 0.6);
      shape.setAttribute("data-norm", a.norm);
      shape.addEventListener("mouseenter", e => { State.setActive(a.norm); IV.UI.showTip(e, agHtml(a)); });
      shape.addEventListener("mousemove", IV.UI.moveTip);
      shape.addEventListener("mouseleave", () => { State.setActive(null); IV.UI.hideTip(); });
      svg.appendChild(shape);
      (ptNodes[a.norm] = ptNodes[a.norm] || []).push(shape);
    });
  }

  function refresh() {
    const chart = IV.DATA.charts[State.chartIdx];
    chart.antigens.forEach(a => {
      (ptNodes[a.norm] || []).forEach(s => {
        const hidden = State.isCladeHidden(a.clade) ||
          (State.onlyMatched && !IV.Tree.normToLeaves[a.norm]);
        s.classList.toggle("dim", hidden || (State.active && a.norm !== State.active));
        s.classList.toggle("lift", State.active && a.norm === State.active);
      });
    });
  }

  IV.Map = {
    render, refresh,
    get agByIdx() { return agByIdx; },
  };
  State.subscribe(refresh);
})(window.IV);
