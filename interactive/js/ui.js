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

  // small inline-SVG glyphs for the marker key (14×14 box), shapes from IV.Glyph
  // so the legend matches the map/tree points exactly.
  function glyph(kind, color) {
    const G = IV.Glyph;
    const body = {
      ref: '<circle cx="7" cy="7" r="5" fill="#fff" stroke="#000" stroke-width="1.3"/>',
      // #4: vaccine = the (larger) passage shape with a bold black outline, NOT a
      // star — map.js draws it as its passage shape, just bigger + black-edged.
      vac: `<circle cx="7" cy="7" r="6" fill="${color || "#bbb"}" stroke="#000" stroke-width="1.7"/>`,
      serum: '<rect x="2.5" y="2.5" width="9" height="9" fill="none" stroke="#555" stroke-width="1.3"/>',
      dot: `<circle cx="7" cy="7" r="5" fill="${color}" stroke="rgba(0,0,0,.3)" stroke-width="0.6"/>`,
      // #4: passage glyphs match the map/tree exactly — egg shape, and reassortant
      // = a TILTED egg (egg rotated 0.5 rad), not a triangle; passage-colour fill.
      egg: `<path d="${G.eggPath(7, 7, 5.5)}" fill="${color}" stroke="rgba(0,0,0,.45)" stroke-width="0.7"/>`,
      reassortant: `<path d="${G.eggPath(7, 7, 5.5, 0.5)}" fill="${color}" stroke="rgba(0,0,0,.45)" stroke-width="0.7"/>`,
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

  // F8 legend-cycle visual: "select" (front) = raised, blue outline + ▲; "back" =
  // sent behind, faded + ▼; "normal" = plain. The store (state.js) owns the cycle
  // and folds the front/back emphasis into State.emphasis() for the panels.
  function cycleBadge(mode) {
    if (mode === "select") return '<span style="margin-left:3px;color:#1558d6;font-size:9px">▲</span>';
    if (mode === "back") return '<span style="margin-left:3px;color:#999;font-size:9px">▼</span>';
    return "";
  }
  function styleCycleRow(d, mode) {
    if (mode === "select") {
      d.style.outline = "2px solid #1558d6"; d.style.outlineOffset = "-1px"; d.style.fontWeight = "600";
    } else if (mode === "back") {
      d.style.opacity = "0.45";
    }
  }
  // F2: make a categorical legend row cycle the *active attribute's* value
  // (normal → select → back → normal) through the generalised store, with the
  // badge + styling. Works for clade / continent / aa — whichever colorBy is active
  // (State.activeAttr resolves it); emphasis() folds the cycle into both panels.
  function applyCycle(d, value) {
    const mode = State.activeMode(value);
    d.insertAdjacentHTML("beforeend", cycleBadge(mode));
    styleCycleRow(d, mode);
    d.onclick = () => { State.cycleActive(value); renderLegend(); };
  }
  const CYCLE_HINT = " — click to cycle: bring to front → send to back → normal";

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
      d.title = `${cnt[v] || 0} tip(s)` + CYCLE_HINT;
      d.innerHTML = `<span class="sw" style="background:${Colour.aaColor(v)}"></span>${v}<span class="cnt">${cnt[v] || 0}</span>`;
      applyCycle(d, v);                       // F2: aa residue value
      colKey.appendChild(d);
    });
    const u = document.createElement("div"); u.className = "lg";
    u.innerHTML = `<span class="sw" style="background:${Colour.unmatched()}"></span>no seq<span class="cnt"></span>`;
    colKey.appendChild(u);
  }

  // #10: a sequential gradient bar labelled with numeric values, starting at 0.
  // Shared by colour-by-stress (C2) and colour-by-stress-per-titre (F5).
  const fmtStress = v => (v < 1 ? v.toFixed(2) : v.toFixed(1));
  function stressBar(colKey, sc, what) {
    const mid = sc.cap / 2;
    const bar = document.createElement("div"); bar.className = "lg";
    bar.innerHTML =
      '0 <span style="position:relative;display:inline-block;width:130px;height:11px;border:1px solid rgba(0,0,0,.25);' +
      `border-radius:2px;vertical-align:-1px;background:linear-gradient(to right,${sc.stops.join(",")})">` +
      `<span style="position:absolute;left:50%;top:11px;transform:translateX(-50%);font-size:9px;color:var(--muted)">${fmtStress(mid)}</span>` +
      `</span> ${fmtStress(sc.cap)}`;
    colKey.appendChild(bar);
    const g = document.createElement("div"); g.className = "lg";
    g.innerHTML = `<span class="sw" style="background:${Colour.unmatched()}"></span>no titre`;
    colKey.appendChild(g);
    footnoteInto(colKey, `${what} · 0 → p95≈${fmtStress(sc.cap)} (max ${fmtStress(sc.max)})`);
  }
  function stressLegend(colKey) {
    if (!Colour.hasStress()) { footnoteInto(colKey, "titer data not exported (E2) — stress unavailable"); return; }
    stressBar(colKey, Colour.stressScale(), "Σ error² per point");
  }
  // F5 colour key: per-point stress ÷ that point's titre count.
  function stressnLegend(colKey) {
    if (!Colour.hasStress()) { footnoteInto(colKey, "titer data not exported (E2) — stress unavailable"); return; }
    stressBar(colKey, Colour.stressPerScale(), "Σ error² ÷ titre count");
  }

  // F1 (v10) colour key: log2(titre/10) vs the selected serum, sequential gradient.
  function titreLegend(colKey) {
    const s = Colour.coverageSerum();
    if (!s) { footnoteInto(colKey, "select a serum (double-click its square) to colour by titre"); return; }
    const sc = Colour.titreScale();
    if (sc.min == null) { footnoteInto(colKey, "no titres against this serum"); return; }
    const bar = document.createElement("div"); bar.className = "lg";
    bar.innerHTML =
      `${fmtStress(sc.min)} <span style="display:inline-block;width:130px;height:11px;border:1px solid rgba(0,0,0,.25);` +
      `border-radius:2px;vertical-align:-1px;background:linear-gradient(to right,${sc.stops.join(",")})"></span> ${fmtStress(sc.max)}`;
    colKey.appendChild(bar);
    const g = document.createElement("div"); g.className = "lg";
    g.innerHTML = `<span class="sw" style="background:${Colour.unmatched()}"></span>untitrated`;
    colKey.appendChild(g);
    footnoteInto(colKey, `log₂(titre/10) vs ${s.name}`);
  }

  // F1 colour key: viridis gradient over the collection-date window, oldest →
  // newest (anchored at the page-generation date), with the dates labelled.
  function timeLegend(colKey) {
    if (!Colour.hasTime()) {
      footnoteInto(colKey, "no collection dates in this chart"); return;
    }
    const w = Colour.timeWindow();
    const bar = document.createElement("div"); bar.className = "lg";
    bar.innerHTML =
      `${w.oldest} <span style="display:inline-block;width:130px;height:11px;border:1px solid rgba(0,0,0,.25);` +
      `border-radius:2px;vertical-align:-1px;background:linear-gradient(to right,${Colour.timeStops(7).join(",")})"></span> ${w.generated}`;
    colKey.appendChild(bar);
    const g = document.createElement("div"); g.className = "lg";
    g.innerHTML = `<span class="sw" style="background:${Colour.unmatched()}"></span>no date`;
    colKey.appendChild(g);
    footnoteInto(colKey, w.generatedExplicit
      ? `newest = report generated ${w.generated}`
      : `newest = latest antigen ${w.newest} (generation date not exported)`);
  }

  // F3 colour key: serum-coverage, only meaningful once a serum is selected.
  function coverageLegend(colKey) {
    if (!Colour.hasCoverage()) {
      footnoteInto(colKey, "titer data not exported (E2) — coverage unavailable"); return;
    }
    const s = Colour.coverageSerum();
    if (!s) {
      footnoteInto(colKey, "select exactly one serum (click its square) to show its coverage"); return;
    }
    const pink = Colour.coveragePink(), w = Colour.coverageWidths();
    const row = (swStyle, label) => {
      const d = document.createElement("div"); d.className = "lg";
      d.innerHTML = `<span class="sw" style="${swStyle}"></span>${label}`;
      colKey.appendChild(d);
    };
    // v7: untitrated dim (not pale); pink ≤4-fold (thin), black >4-fold (thicker)
    row(`background:${Colour.unmatched()};opacity:0.3`, "untitrated (dimmed)");
    row(`background:#fff;border:${w.pink}px solid ${pink}`, "titrated, ≤4-fold of homologous");
    row(`background:#fff;border:${w.black}px solid #000`, "titrated, &gt;4-fold (further)");
    footnoteInto(colKey, `serum: ${s.name}`);
  }

  function renderLegend() {
    const lg = document.getElementById("legend"); lg.innerHTML = "";
    const counts = tipCounts();

    // ---- colour key (depends on colorBy) ----
    const titleByMode = {
      clade: "Clade", continent: "Continent",
      aa: "AA " + (Colour.aaPositions().join("+") || "position?"),
      stress: "Stress", stressn: "Stress / titre", time: "Collection date",
      coverage: "Serum coverage", titre: "Titre",
    };
    const colKey = section(titleByMode[State.colorBy] || "Colour");

    if (State.colorBy === "aa") {
      aaLegend(colKey);
    } else if (State.colorBy === "stress") {
      stressLegend(colKey);
    } else if (State.colorBy === "stressn") {
      stressnLegend(colKey);
    } else if (State.colorBy === "titre") {
      titreLegend(colKey);
    } else if (State.colorBy === "time") {
      timeLegend(colKey);
    } else if (State.colorBy === "coverage") {
      coverageLegend(colKey);
    } else if (State.colorBy === "clade") {
      // count = tips/antigens (tree tips / active-chart map points). The two are
      // told apart by magnitude (antigens smaller, except the unsequenced row).
      const ag = agCladeCounts();
      Colour.cladesOrdered().forEach(c => {   // #2 report legend order (priority)
        const t = counts.clade[c] || 0, a = ag.clade[c] || 0;
        const d = document.createElement("div");
        d.className = "lg";
        d.title = `${t} tip(s) / ${a} antigen(s)` + CYCLE_HINT;
        d.innerHTML = `<span class="sw" style="background:${Colour.cladeColor(c)}"></span>` +
          `${Colour.cladeLegend(c)}<span class="cnt">${t}/${a}</span>`;
        applyCycle(d, c);                     // F2 (was F8 clade-only)
        colKey.appendChild(d);
      });
      const u = document.createElement("div"); u.className = "lg";
      u.title = `${counts.noClade} tip(s) / ${ag.noClade} antigen(s)`;
      u.innerHTML = `<span class="sw" style="background:${Colour.unmatched()}"></span>` +
        `no clade<span class="cnt">${counts.noClade}/${ag.noClade}</span>`;
      colKey.appendChild(u);
    } else if (State.colorBy === "continent") {
      // #6: antigens now colour by continent too (bundle continent_color), so the
      // key pairs tips/antigens like the clade key.
      const agc = {};
      (IV.DATA.charts[State.chartIdx].antigens || []).forEach(a => {
        const k = (a.continent || "").toUpperCase();
        if (k) agc[k] = (agc[k] || 0) + 1;
      });
      Colour.continents().forEach(c => {
        const t = counts.cont[c] || 0, a = agc[c] || 0;
        if (!t && !a) return;
        const d = document.createElement("div"); d.className = "lg";
        d.title = `${t} tip(s) / ${a} antigen(s)` + CYCLE_HINT;
        d.innerHTML = `<span class="sw" style="background:${Colour.continentColor(c)}"></span>` +
          `${c.toLowerCase()}<span class="cnt">${t}/${a}</span>`;
        applyCycle(d, c);                     // F2: continent value is the uppercase key
        colKey.appendChild(d);
      });
    } else {
      const d = document.createElement("div"); d.className = "lg";
      d.innerHTML = `<span class="sw" style="background:#4e79a7"></span>uniform colour`;
      colKey.appendChild(d);
    }
    lg.appendChild(colKey);

    // ---- marker key (persistent) ----
    // F3 (v9): each category (reference/vaccine/serum/egg/reassortant) is clickable
    // and drives State's marker cycle (front → back → normal), like clade swatches —
    // emphasis()/pointEmphasis() fold the marker modes in. Always active (independent
    // of colorBy).
    const mk = section("Markers");
    const markerItem = (cat, html) => {
      const d = document.createElement("div"); d.className = "lg"; d.innerHTML = html;
      const mode = State.markerMode(cat);
      d.insertAdjacentHTML("beforeend", cycleBadge(mode));
      styleCycleRow(d, mode);
      d.title = "click to cycle: bring to front → send to back → normal";
      d.onclick = () => { State.cycleMarker(cat); renderLegend(); };
      mk.appendChild(d);
    };
    markerItem("reference", `${glyph("ref")}reference`);
    markerItem("vaccine", `${glyph("vac", "#888")}vaccine`);
    markerItem("serum", `${glyph("serum")}serum`);
    if (Colour.hasPassageMarkers()) {
      // egg + reassortant get a distinct glyph on the map/tree (F7); cell is the
      // default circle, so it's omitted from the key (#3). Glyphs are filled with
      // passage_color (#4) and shaped via IV.Glyph to match the points.
      Colour.passages().filter(p => p !== "cell").forEach(p => {
        markerItem(p, `${glyph(p, Colour.passageColor(p))}${Colour.passageLabel(p)}`);
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
      // stress(/per-titre) + time are per-chart, so tip colours change with the chart
      if (/^(stress|stressn|time)$/.test(State.colorBy)) IV.Tree.render();
      renderLegend(); State.notify(); updateTitles();
    };

    // Colour-mode controls. The two data-driven modes (C1 amino-acid, C2 stress)
    // and the AA-position input are injected here rather than in the template, so
    // they stay self-contained in this module and don't collide with map/grid work.
    const colorBy = document.getElementById("colorBy");
    if (IV.Colour.hasAA()) addOption(colorBy, "aa", "amino acid");
    if (IV.Colour.hasStress()) addOption(colorBy, "stress", "stress");
    if (IV.Colour.hasStress()) addOption(colorBy, "stressn", "stress / titre");   // F5
    if (IV.Colour.hasTime()) addOption(colorBy, "time", "collection date");
    if (IV.Colour.hasCoverage()) addOption(colorBy, "coverage", "serum coverage");
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
      "Click a legend swatch (clade / continent / AA) to cycle it: bring to front → send to back → normal.";
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

  // F1: the "titre" colour option only makes sense for ONE serum, so add it when a
  // single serum is resolved (like coverage's active condition) and remove it
  // otherwise — falling back to clade if that mode was active.
  function syncTitreOption() {
    const sel = document.getElementById("colorBy");
    if (!sel) return;
    const has = Colour.hasTitre();
    const opt = Array.prototype.find.call(sel.options, o => o.value === "titre");
    if (has && !opt) {
      addOption(sel, "titre", "titre");
    } else if (!has && opt) {
      opt.remove();
      if (State.colorBy === "titre") {              // mode no longer valid → fall back
        State.setColorBy("clade"); sel.value = "clade";
        IV.Tree.render(); IV.Map.render(); renderLegend();
      }
    }
  }

  // F3/F1: serum-coverage fill and titre colour depend on which serum is selected,
  // but a selection change only triggers panel refresh() (class toggles), not a
  // re-fill. So keep the titre option in sync and, when in coverage/titre mode and
  // the serum changes, re-render both panels + legend.
  let lastSerum = undefined;
  State.subscribe(() => {
    syncTitreOption();
    if (State.colorBy !== "coverage" && State.colorBy !== "titre") { lastSerum = undefined; return; }
    const s = Colour.coverageSerum();
    const id = s ? s.i : null;
    if (id !== lastSerum) {
      lastSerum = id;
      IV.Tree.render(); IV.Map.render(); renderLegend();
    }
  });

  IV.UI = { showTip, moveTip, hideTip, renderLegend, bindControls, updateTitles };
})(window.IV);
