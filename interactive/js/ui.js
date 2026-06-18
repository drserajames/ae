// ui.js — tooltip, legend, header controls, titles
//
// Shared chrome: the tooltip helpers (used by tree.js + map.js), the clade legend,
// and the header control wiring. Mutates IV.State and triggers panel re-renders.
(function (IV) {
  "use strict";
  const State = IV.State, Colour = IV.Colour;

  // ---- tooltip (shared by tree + map) ----
  const tipEl = () => document.getElementById("tooltip");
  function showTip(e, html) { const t = tipEl(); t.innerHTML = html; t.style.opacity = 1; moveTip(e); }
  function moveTip(e) { const t = tipEl(); t.style.left = (e.clientX + 12) + "px"; t.style.top = (e.clientY + 12) + "px"; }
  function hideTip() { tipEl().style.opacity = 0; }

  // ---- legend ----
  function renderLegend() {
    const lg = document.getElementById("legend"); lg.innerHTML = "";
    if (State.colorBy !== "clade") {
      lg.innerHTML = '<span class="footnote">Legend shown when colouring by clade.</span>';
      return;
    }
    Colour.clades().sort().forEach(c => {
      const d = document.createElement("div");
      d.className = "lg" + (State.offClades.has(c) ? " off" : "");
      d.innerHTML = `<span class="sw" style="background:${Colour.cladeColor(c)}"></span>${c}`;
      d.onclick = () => { State.toggleClade(c); d.classList.toggle("off"); };
      lg.appendChild(d);
    });
    const u = document.createElement("div"); u.className = "lg";
    u.innerHTML = `<span class="sw" style="background:${Colour.unmatched()}"></span>no clade`;
    lg.appendChild(u);
  }

  // ---- header controls ----
  function bindControls() {
    const chartSel = document.getElementById("chartSel");
    IV.DATA.charts.forEach((c, i) => {
      const o = document.createElement("option");
      o.value = i; o.textContent = `${c.label} (${c.n_antigens} ag, ${c.n_sera} sr)`;
      chartSel.appendChild(o);
    });
    chartSel.onchange = () => { State.setChart(+chartSel.value); IV.Map.render(); State.notify(); updateTitles(); };

    document.getElementById("colorBy").onchange = e => {
      State.setColorBy(e.target.value);
      IV.Tree.render(); IV.Map.render(); renderLegend(); State.notify();
    };

    const onlyMatched = document.getElementById("onlyMatched");
    onlyMatched.onchange = () => State.setOnlyMatched(onlyMatched.checked);

    const search = document.getElementById("search");
    search.oninput = () => {
      const q = search.value.trim().toUpperCase();
      if (!q) { State.setActive(null); return; }
      const lf = IV.Tree.leaves.find(l => l.name.toUpperCase().includes(q));
      const ag = IV.DATA.charts[State.chartIdx].antigens.find(a => a.name.toUpperCase().includes(q));
      State.setActive(lf ? lf.norm : (ag ? ag.norm : "__none__"));
    };
  }

  function updateTitles() {
    const m = IV.DATA.meta, ch = IV.DATA.charts[State.chartIdx];
    document.getElementById("title").textContent = `${m.subtype || ""} ${m.assay || ""} — tree + antigenic map`.trim();
    document.getElementById("metaline").textContent =
      `${m.n_kept_leaves} linked tips / ${m.n_tree_leaves} in tree · ${m.n_matched_norms} strains matched`;
    document.getElementById("treeTitle").textContent =
      `Phylogenetic tree (${m.tree_file}) — ${IV.Tree.leaves.length} linked tips`;
    document.getElementById("mapTitle").textContent = `Antigenic map — ${ch.label}: ${ch.name}`;
    document.getElementById("foot").textContent =
      "Hover a tip or map point to link the two panels by strain. Click legend swatches to filter clades. " +
      "Open circle/black-edge = reference antigen; star = vaccine; squares = sera.";
  }

  IV.UI = { showTip, moveTip, hideTip, renderLegend, bindControls, updateTitles };
})(window.IV);
