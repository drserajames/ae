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

  // Active-chart antigen counts per primary clade (the clade swatches key the map
  // points too, so the legend pairs tips with antigens). Recomputed each render,
  // so a chart switch reflects that chart's antigens.
  function agCladeCounts() {
    const clade = {}; let noClade = 0;
    (IV.DATA.charts[State.chartIdx].antigens || []).forEach(a => {
      if (a.clade) clade[a.clade] = (clade[a.clade] || 0) + 1; else noClade++;
    });
    return { clade, noClade };
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
      // un-ringed passage: a clade-grey point with the neutral stroke the map uses
      neutral: '<circle cx="7" cy="7" r="5" fill="#d9d9d9" stroke="rgba(0,0,0,.3)" stroke-width="0.6"/>',
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

  function footnoteInto(parent, text) {
    const n = document.createElement("span");
    n.className = "footnote"; n.style.padding = "0"; n.textContent = text;
    parent.appendChild(n);
  }

  // C1 colour key: residue value at the active HA position(s), with tip counts.
  function aaLegend(colKey) {
    if (!Colour.aaPositions().length) {
      footnoteInto(colKey, "enter HA position(s) above to colour by residue"); return;
    }
    const cnt = {};
    (IV.Tree.leaves || []).forEach(l => { const v = Colour.aaValue(l.norm); if (v) cnt[v] = (cnt[v] || 0) + 1; });
    const vals = Colour.aaValues();
    if (!vals.length) {
      footnoteInto(colKey, "no residue data at that position in the matched set"); return;
    }
    vals.forEach(v => {
      const d = document.createElement("div"); d.className = "lg";
      d.innerHTML = `<span class="sw" style="background:${Colour.aaColor(v)}"></span>${v}<span class="cnt">${cnt[v] || 0}</span>`;
      colKey.appendChild(d);
    });
    const u = document.createElement("div"); u.className = "lg";
    u.innerHTML = `<span class="sw" style="background:${Colour.unmatched()}"></span>no seq<span class="cnt"></span>`;
    colKey.appendChild(u);
  }

  // C2 colour key: a sequential gradient bar for per-point stress (Σ error²).
  function stressLegend(colKey) {
    if (!Colour.hasStress()) {
      footnoteInto(colKey, "titer data not exported (E2) — stress unavailable"); return;
    }
    const sc = Colour.stressScale();
    const bar = document.createElement("div"); bar.className = "lg";
    bar.innerHTML =
      'low <span style="display:inline-block;width:120px;height:11px;border:1px solid rgba(0,0,0,.25);' +
      `border-radius:2px;vertical-align:-1px;background:linear-gradient(to right,${sc.stops.join(",")})"></span> high`;
    colKey.appendChild(bar);
    const g = document.createElement("div"); g.className = "lg";
    g.innerHTML = `<span class="sw" style="background:${Colour.unmatched()}"></span>no titer`;
    colKey.appendChild(g);
    footnoteInto(colKey, `Σ error² per point · scale top p95≈${sc.cap.toFixed(1)} (max ${sc.max.toFixed(1)})`);
  }

  function renderLegend() {
    const lg = document.getElementById("legend"); lg.innerHTML = "";
    const counts = tipCounts();

    // ---- colour key (depends on colorBy) ----
    const titleByMode = {
      clade: "Clade", continent: "Continent",
      aa: "AA " + (Colour.aaPositions().join("+") || "position?"), stress: "Stress",
    };
    const colKey = section(titleByMode[State.colorBy] || "Colour");

    if (State.colorBy === "aa") {
      aaLegend(colKey);
    } else if (State.colorBy === "stress") {
      stressLegend(colKey);
    } else if (State.colorBy === "clade") {
      // count = tips/antigens (tree tips / active-chart map points). The two are
      // told apart by magnitude (antigens smaller, except the unsequenced row).
      const ag = agCladeCounts();
      Colour.clades().sort().forEach(c => {
        const t = counts.clade[c] || 0, a = ag.clade[c] || 0;
        const d = document.createElement("div");
        d.className = "lg" + (State.offClades.has(c) ? " off" : "");
        d.title = `${t} tip(s) / ${a} antigen(s) — click to show / hide`;
        d.innerHTML = `<span class="sw" style="background:${Colour.cladeColor(c)}"></span>` +
          `${Colour.cladeLegend(c)}<span class="cnt">${t}/${a}</span>`;
        d.onclick = () => { State.toggleClade(c); d.classList.toggle("off"); };
        colKey.appendChild(d);
      });
      const u = document.createElement("div"); u.className = "lg";
      u.title = `${counts.noClade} tip(s) / ${ag.noClade} antigen(s)`;
      u.innerHTML = `<span class="sw" style="background:${Colour.unmatched()}"></span>` +
        `no clade<span class="cnt">${counts.noClade}/${ag.noClade}</span>`;
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
      // Only the salient passages are ringed on the map/tree (map.js/tree.js ring
      // `type !== "cell"`); cell keeps the neutral stroke so its rings don't bury
      // the clade fills. Mirror that here: coloured dot = ringed; neutral = not.
      Colour.passages().forEach(p => {
        const ringed = p !== "cell";
        item(ringed
          ? `${glyph("dot", Colour.passageColor(p))}${Colour.passageLabel(p)}`
          : `${glyph("neutral")}${Colour.passageLabel(p)} <span class="footnote" style="padding:0">(no ring)</span>`);
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
    chartSel.onchange = () => {
      State.setChart(+chartSel.value);
      IV.Map.render();
      if (State.colorBy === "stress") IV.Tree.render();   // per-chart stress recolours tips
      renderLegend(); State.notify(); updateTitles();
    };

    // Colour-mode controls. The two data-driven modes (C1 amino-acid, C2 stress)
    // and the AA-position input are injected here rather than in the template, so
    // they stay self-contained in this module and don't collide with map/grid work.
    const colorBy = document.getElementById("colorBy");
    if (IV.Colour.hasAA()) addOption(colorBy, "aa", "amino acid");
    if (IV.Colour.hasStress()) addOption(colorBy, "stress", "stress");
    const aaPos = makeAAInput(colorBy);

    colorBy.onchange = e => {
      const mode = e.target.value;
      State.setColorBy(mode);
      aaPos.wrap.style.display = mode === "aa" ? "" : "none";
      if (mode === "aa" && Colour.aaPositions().length === 0) {
        if (!aaPos.input.value) aaPos.input.value = "145";   // a useful H3 default
        Colour.setAAPositions(aaPos.input.value);
      }
      IV.Tree.render(); IV.Map.render(); renderLegend(); State.notify();
    };

    const onlyMatched = document.getElementById("onlyMatched");
    onlyMatched.onchange = () => State.setOnlyMatched(onlyMatched.checked);

    // Search (S2): substring match across tree tips + active chart antigens,
    // selecting EVERY match (multi-match) so both panels highlight them and fade
    // the rest. Empty query clears the selection.
    const search = document.getElementById("search");
    search.oninput = () => {
      const q = search.value.trim().toUpperCase();
      if (!q) { State.clearSelection(); search.classList.remove("nohit"); search.title = ""; return; }
      const hit = s => s && s.toUpperCase().includes(q);
      const norms = new Set();
      IV.Tree.leaves.forEach(l => { if (hit(l.name) || hit(l.norm)) norms.add(l.norm); });
      IV.DATA.charts[State.chartIdx].antigens.forEach(a => { if (hit(a.name) || hit(a.norm)) norms.add(a.norm); });
      State.setSelection(norms);
      search.classList.toggle("nohit", norms.size === 0);
      search.title = `${norms.size} strain(s) matched`;
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
      "Hover a tip or map point to link the two panels by strain. " +
      "Click to select (Shift/Cmd-click to add); drag a box on either panel to select many; " +
      "search selects all matches; click empty space to clear. " +
      "Click a clade swatch in the legend to show / hide that clade.";
  }

  function addOption(sel, value, label) {
    if (Array.prototype.some.call(sel.options, o => o.value === value)) return;
    const o = document.createElement("option");
    o.value = value; o.textContent = label;
    sel.appendChild(o);
  }

  // The colour-by-AA position box, inserted after the Colour control and hidden
  // until that mode is active. Typing positions (e.g. "145, 159") recolours live.
  function makeAAInput(colorBy) {
    const wrap = document.createElement("label");
    wrap.style.display = "none";
    wrap.innerHTML = 'pos <input id="aaPos" type="text" size="8" placeholder="e.g. 145, 159" ' +
      'style="font-size:12px;padding:3px 6px;border:1px solid var(--line);border-radius:4px;width:90px">';
    const host = colorBy.closest("label") || colorBy;
    host.parentNode.insertBefore(wrap, host.nextSibling);
    const input = wrap.querySelector("#aaPos");
    // Debounce: a full tree+map re-render is heavy (~1570 tips + ~3000 edges), so
    // coalesce bursts of keystrokes into one recolour ~200 ms after typing stops.
    let timer = 0;
    input.oninput = () => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        Colour.setAAPositions(input.value);
        if (State.colorBy === "aa") { IV.Tree.render(); IV.Map.render(); renderLegend(); State.notify(); }
      }, 200);
    };
    return { wrap, input };
  }

  IV.UI = { showTip, moveTip, hideTip, renderLegend, bindControls, updateTitles };
})(window.IV);
