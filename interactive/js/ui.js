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

  // ---- legend (L1: persistent — colour key + marker key) ----
  //
  // Always shown. Left part is the colour key for the active colorBy (clade
  // swatches with tip counts / continent key / uniform note); right part is a
  // persistent marker key (reference/vaccine/serum shapes + passage colours).
  // Counts are tree-tip counts, computed from IV.Tree.leaves.

  function tipCounts() {
    const clade = {}, cont = {}; let noClade = 0;
    (IV.Tree.leaves || []).forEach(lf => {
      if (lf.clade) clade[lf.clade] = (clade[lf.clade] || 0) + 1; else noClade++;
      const c = (lf.continent || "").toUpperCase();
      if (c) cont[c] = (cont[c] || 0) + 1;
    });
    return { clade, cont, noClade };
  }

  // small inline-SVG glyphs for the marker key (14×14 box)
  function starPath(cx, cy, spikes, inner, outer) {
    let rot = Math.PI / 2 * 3, step = Math.PI / spikes, p = `M${cx},${cy - outer}`;
    for (let i = 0; i < spikes; i++) {
      p += `L${cx + Math.cos(rot) * outer},${cy + Math.sin(rot) * outer}`; rot += step;
      p += `L${cx + Math.cos(rot) * inner},${cy + Math.sin(rot) * inner}`; rot += step;
    }
    return p + "Z";
  }
  function glyph(kind, color) {
    const body = {
      ref: '<circle cx="7" cy="7" r="5" fill="#fff" stroke="#000" stroke-width="1.3"/>',
      vac: `<path d="${starPath(7, 7, 5, 2.8, 6)}" fill="${color || "#888"}" stroke="rgba(0,0,0,.4)" stroke-width="0.6"/>`,
      serum: '<rect x="2.5" y="2.5" width="9" height="9" fill="none" stroke="#555" stroke-width="1.3"/>',
      dot: `<circle cx="7" cy="7" r="5" fill="${color}" stroke="rgba(0,0,0,.3)" stroke-width="0.6"/>`,
    }[kind];
    return `<svg width="14" height="14" viewBox="0 0 14 14" style="vertical-align:-3px">${body}</svg>`;
  }

  function section(title) {
    const s = document.createElement("div");
    s.className = "lgSec";
    s.style.cssText = "display:flex;flex-wrap:wrap;align-items:center;gap:3px 10px;";
    if (title) {
      const h = document.createElement("span");
      h.className = "lgHead";
      h.style.cssText = "font-weight:600;color:var(--muted);margin-right:2px;";
      h.textContent = title;
      s.appendChild(h);
    }
    return s;
  }

  function renderLegend() {
    const lg = document.getElementById("legend"); lg.innerHTML = "";
    const counts = tipCounts();

    // ---- colour key (depends on colorBy) ----
    const colKey = section(
      State.colorBy === "clade" ? "Clade" :
      State.colorBy === "continent" ? "Continent" : "Colour");

    if (State.colorBy === "clade") {
      Colour.clades().sort().forEach(c => {
        const n = counts.clade[c] || 0;
        const d = document.createElement("div");
        d.className = "lg" + (State.offClades.has(c) ? " off" : "");
        d.title = "click to show / hide this clade";
        d.innerHTML = `<span class="sw" style="background:${Colour.cladeColor(c)}"></span>` +
          `${Colour.cladeLegend(c)}<span class="cnt">${n}</span>`;
        d.onclick = () => { State.toggleClade(c); d.classList.toggle("off"); };
        colKey.appendChild(d);
      });
      const u = document.createElement("div"); u.className = "lg";
      u.innerHTML = `<span class="sw" style="background:${Colour.unmatched()}"></span>` +
        `no clade<span class="cnt">${counts.noClade}</span>`;
      colKey.appendChild(u);
    } else if (State.colorBy === "continent") {
      Colour.continents().forEach(c => {
        const n = counts.cont[c] || 0;
        if (!n) return;
        const d = document.createElement("div"); d.className = "lg";
        d.innerHTML = `<span class="sw" style="background:${Colour.continentColor(c)}"></span>` +
          `${c.toLowerCase()}<span class="cnt">${n}</span>`;
        colKey.appendChild(d);
      });
      const note = document.createElement("span");
      note.className = "footnote"; note.style.padding = "0";
      note.textContent = "(tree tips; map points use a single colour)";
      colKey.appendChild(note);
    } else {
      const d = document.createElement("div"); d.className = "lg";
      d.innerHTML = `<span class="sw" style="background:#4e79a7"></span>uniform colour`;
      colKey.appendChild(d);
    }
    lg.appendChild(colKey);

    // ---- marker key (persistent) ----
    const mk = section("Markers");
    const item = (html) => { const d = document.createElement("div"); d.className = "lg"; d.innerHTML = html; mk.appendChild(d); };
    item(`${glyph("ref")}reference`);
    item(`${glyph("vac", "#888")}vaccine`);
    item(`${glyph("serum")}serum`);
    if (Colour.hasPassageMarkers()) {
      Colour.passages().forEach(p => {
        item(`${glyph("dot", Colour.passageColor(p))}${Colour.passageLabel(p)}`);
      });
    }
    lg.appendChild(mk);
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
