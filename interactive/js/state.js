// state.js — selection store + global view state (shared contract; see CONTRACT.md)
//
// This is the single owner of "what is selected / filtered / how are we colouring".
// Panels (tree, map, lines, grid) call State.subscribe(fn) and re-apply their own
// highlight when State.notify() fires. No module should duplicate this state.
window.IV = window.IV || {};
(function (IV) {
  "use strict";

  // ---- shared DOM helpers ----
  const SVGNS = "http://www.w3.org/2000/svg";
  IV.SVGNS = SVGNS;
  IV.el = (t, a = {}) => {
    const e = document.createElementNS(SVGNS, t);
    for (const k in a) e.setAttribute(k, a[k]);
    return e;
  };

  // IV.DATA is the bundle (CONTRACT.md). main.js assigns it from IV.__DATA__.
  IV.DATA = null;

  const listeners = [];
  const SERUM_CATS = ["serum"];   // F3: marker categories for a serum glyph

  const State = {
    chartIdx: 0,          // active chart (Centre dropdown)
    colorBy: "clade",     // "clade" | "continent" | "none"
    onlyMatched: false,   // map: dim antigens with no tree tip
    offClades: new Set(), // clade labels toggled off in the legend
    active: null,         // transient hovered strain norm
    selected: new Set(),  // persistent selection (S1 populates this; empty in F1)
    isolated: null,       // v8: {kind:'serum'|'antigen', i} point-identity isolation (active chart) | null

    subscribe(fn) { listeners.push(fn); },
    notify() { for (const fn of listeners) fn(State); },

    setActive(norm) { State.active = norm; State.notify(); },

    // chart change re-renders the map (caller's job), so no implicit notify here.
    // isolation indexes the active chart, so it can't carry across charts — clear it.
    setChart(i) { State.chartIdx = i; State.isolated = null; },

    setColorBy(mode) { State.colorBy = mode; },
    setOnlyMatched(on) { State.onlyMatched = on; State.notify(); },

    // ---- F2 (v6): "new since report / VCM" highlight toggles ----------------
    // Driven by the Overlays checkboxes (Agent-LINES). map/tree render read these
    // and bold-outline antigens/tips whose semantic `new` is 1 (since previous
    // report) or 2 (since previous VCM). Flags only; the drawing lives in the panels.
    showNewReport: false,   // highlight antigens with new >= 1
    showNewVCM: false,      // highlight antigens with new == 2
    // #2 (v9): the two new-since toggles are mutually exclusive.
    setShowNewReport(on) { State.showNewReport = !!on; if (on) State.showNewVCM = false; State.notify(); },
    setShowNewVCM(on) { State.showNewVCM = !!on; if (on) State.showNewReport = false; State.notify(); },

    toggleClade(c) {
      if (State.offClades.has(c)) State.offClades.delete(c);
      else State.offClades.add(c);
      State.notify();
    },
    isCladeHidden(c) { return !!c && State.offClades.has(c); },

    // ---- selection (S1) -----------------------------------------------------
    // `selected` is a Set of strain `norm`s. Both panels reflect it via
    // emphasis() below; the box/click installer mutates it. All mutators notify.
    isSelected(norm) { return State.selected.has(norm); },
    hasSelection() { return State.selected.size > 0; },

    // Replace the whole selection with `norms` (used by search S2 + plain click).
    setSelection(norms) {
      State.selected = new Set([...norms].filter(Boolean));
      State.notify();
    },
    // Add `norms`; pass {additive:false} to replace first (default adds).
    select(norms, { additive = true } = {}) {
      if (!additive) State.selected = new Set();
      for (const n of norms) if (n) State.selected.add(n);
      State.notify();
    },
    // Toggle one strain (shift/ctrl/cmd-click).
    toggleSelect(norm) {
      if (!norm) return;
      if (State.selected.has(norm)) State.selected.delete(norm);
      else State.selected.add(norm);
      State.notify();
    },
    deselect(norms) {
      let changed = false;
      for (const n of norms) if (State.selected.delete(n)) changed = true;
      if (changed) State.notify();
    },
    clearSelection() {
      if (!State.selected.size) return;
      State.selected.clear();
      State.notify();
    },

    // ---- F1: serum -> homologous-antigen expansion --------------------------
    // Selecting a serum should also light its homologous antigen (and thus the
    // matching tree tip, which is keyed by the antigen's norm). The bundle gives
    // each serum a `homologous` antigen index; we add that antigen's norm when it
    // differs from the serum norm. Cached per active chart.
    _homCache: { idx: -1, map: null },
    _homMap() {
      const idx = State.chartIdx;
      if (State._homCache.idx === idx && State._homCache.map) return State._homCache.map;
      const m = new Map();   // serum norm -> homologous antigen norm (only when different)
      const ch = IV.DATA && IV.DATA.charts[idx];
      if (ch && ch.sera && ch.antigens) for (const s of ch.sera) {
        if (s.homologous == null || !s.norm) continue;
        const ag = ch.antigens[s.homologous];
        if (ag && ag.norm && ag.norm !== s.norm) m.set(s.norm, ag.norm);
      }
      State._homCache = { idx, map: m };
      return m;
    },
    // Expand norms to include the homologous antigen norm for any serum norms.
    expandNorms(norms) {
      const hom = State._homMap();
      const out = new Set();
      for (const n of norms) { if (!n) continue; out.add(n); const h = hom.get(n); if (h) out.add(h); }
      return [...out];
    },

    // ---- F2: per-attribute legend cycle (z-order tri-state) -----------------
    // Generalises the v3 per-clade cycle to ANY legend attribute — clade,
    // continent, or aa-value — whichever colorBy is active. Each (attr,value)
    // group cycles normal -> select(front) -> back -> normal. A "select" group
    // pops while the rest fade (like a selection); a "back" group dims and sorts
    // behind. The legend (Agent-COLOUR) calls cycleActive(value) on the active
    // attribute; emphasis() resolves each point's value for the active attribute
    // and folds the mode in, so every panel reflects it via its existing refresh.
    cycle: new Map(),        // "attr\x00value" -> "select" | "back"  (absent = normal)
    _zDirty: false,          // a cycle changed since the last z-order pass
    _ck(attr, val) { return attr + "\x00" + val; },
    // active cyclable attribute, from colorBy (null for non-categorical: stress/none)
    activeAttr() {
      const m = State.colorBy;
      return (m === "clade" || m === "continent" || m === "aa") ? m : null;
    },
    // generic (attr, value) accessors
    attrMode(attr, val) { return (val != null && State.cycle.get(State._ck(attr, val))) || "normal"; },
    attrZRank(attr, val) { const m = State.attrMode(attr, val); return m === "select" ? 1 : m === "back" ? -1 : 0; },
    cycleAttr(attr, val) {
      if (!attr || val == null) return "normal";
      const k = State._ck(attr, val), cur = State.cycle.get(k) || "normal";
      const next = cur === "normal" ? "select" : cur === "select" ? "back" : "normal";
      if (next === "normal") State.cycle.delete(k); else State.cycle.set(k, next);
      State._zDirty = true; State.notify();
      return next;
    },
    // convenience for the legend, which always operates on the active attribute
    activeMode(val) { const a = State.activeAttr(); return a ? State.attrMode(a, val) : "normal"; },
    activeZRank(val) { const a = State.activeAttr(); return a ? State.attrZRank(a, val) : 0; },
    cycleActive(val) { const a = State.activeAttr(); return a ? State.cycleAttr(a, val) : "normal"; },
    resetCycle() { if (State.cycle.size) { State.cycle.clear(); State._zDirty = true; State.notify(); } },
    // any "select" group within attribute `a`?
    _anyFront(a) {
      const pre = a + "\x00";
      for (const [k, v] of State.cycle) if (v === "select" && k.lastIndexOf(pre, 0) === 0) return true;
      return false;
    },
    // a point's value for attribute `a` (clade is passed through since panels have it)
    _attrValue(a, norm, clade) {
      if (a === "clade") return clade;
      if (a === "continent") return State._contOf(norm);
      if (a === "aa") return (IV.Colour && IV.Colour.aaValue) ? IV.Colour.aaValue(norm) : null;
      return null;
    },
    // lazy norm -> uppercase continent map (antigens + tree leaves), for the
    // continent cycle (panels pass clade, not continent, to emphasis()).
    _contCache: null,
    _contOf(norm) {
      if (!State._contCache) {
        const m = Object.create(null), d = IV.DATA;
        if (d) {
          (d.charts || []).forEach(ch => (ch.antigens || []).forEach(a => {
            if (a.norm && a.continent && !m[a.norm]) m[a.norm] = String(a.continent).toUpperCase();
          }));
          (function walk(n) {
            if (!n) return;
            if (!n.children || !n.children.length) {
              if (n.norm && n.continent && !m[n.norm]) m[n.norm] = String(n.continent).toUpperCase();
            } else n.children.forEach(walk);
          })(d.tree);
        }
        State._contCache = m;
      }
      return State._contCache[norm] || null;
    },

    // ---- #3 (v7): new-since highlight as a "keep" emphasis layer ------------
    // When showNewReport/showNewVCM is on, antigens with the matching `new` level
    // are kept and the rest dim (folded into emphasis() — no bold outline). Keep
    // set: showNewReport -> new==1; showNewVCM -> new>=1 (union when both on).
    _newCache: null, _newDataFlag: null,
    _newOf(norm) {                       // lazy norm -> max `new` level across charts
      if (!State._newCache) {
        const m = Object.create(null), d = IV.DATA;
        if (d) (d.charts || []).forEach(ch => (ch.antigens || []).forEach(a => {
          if (a.norm && a.new != null) { const v = +a.new; if (!(m[a.norm] >= v)) m[a.norm] = v; }
        }));
        State._newCache = m;
      }
      return State._newCache[norm];
    },
    _hasNewData() {
      if (State._newDataFlag == null) {
        let has = false; const d = IV.DATA;
        for (const ch of (d && d.charts || [])) { for (const a of (ch.antigens || [])) { if (a.new != null) { has = true; break; } } if (has) break; }
        State._newDataFlag = has;
      }
      return State._newDataFlag;
    },
    _newActive() { return (State.showNewReport || State.showNewVCM) && State._hasNewData(); },
    _newMatch(norm) {
      const n = State._newOf(norm);
      if (n == null) return false;
      return (State.showNewReport && n === 1) || (State.showNewVCM && n >= 1);
    },

    // ---- F3 (v9): marker-category cycle ------------------------------------
    // A second cyclable dimension keyed "marker\x00<category>", ALWAYS active
    // (independent of colorBy). Agent-COLOUR's legend marker swatches call
    // cycleMarker(cat); emphasis()/pointEmphasis() fold the modes in exactly like
    // the clade cycle — a front category pops while the rest fade. A point can be
    // in several categories (e.g. an egg reference antigen). "serum" matches only
    // serum glyphs (resolved by kind in pointEmphasis), so it has no tree tips.
    MARKERS: ["reference", "vaccine", "serum", "egg", "reassortant"],
    cycleMarker(cat) { return State.cycleAttr("marker", cat); },
    markerMode(cat) { return State.attrMode("marker", cat); },
    markerZRank(cat) { return State.attrZRank("marker", cat); },
    _markerCache: null,
    _markersOfNorm(norm) {                 // antigen marker categories for a norm
      if (!State._markerCache) {
        const m = Object.create(null), d = IV.DATA;
        if (d) (d.charts || []).forEach(ch => (ch.antigens || []).forEach(a => {
          if (!a.norm) return;
          const arr = m[a.norm] || (m[a.norm] = []);
          const add = c => { if (arr.indexOf(c) < 0) arr.push(c); };
          if (a.ref) add("reference");
          if (a.vac) add("vaccine");
          if (a.pt === "egg") add("egg");
          if (a.pt === "reassortant") add("reassortant");
        }));
        State._markerCache = m;
      }
      return State._markerCache[norm] || null;
    },
    // front/back contribution of a point's marker categories
    _markerEmph(cats) {
      let front = false, back = false;
      if (cats) for (const c of cats) {
        const mm = State.cycle.get("marker\x00" + c);
        if (mm === "select") front = true; else if (mm === "back") back = true;
      }
      return { front, back };
    },

    // ---- v8: point-identity isolation --------------------------------------
    // A double-click isolates ONE exact point (a serum or antigen, by index in the
    // active chart) — distinct from the norm selection, so a serum can be isolated
    // WITHOUT lighting its same-name antigen (which shares the norm). The panels
    // read this via pointEmphasis(kind,i,...) (map/grid) and isolatedSerum() (lines,
    // tree coverage). Sera-only features (error lines, serum circle, coverage)
    // scope to isolatedSerum().
    setIsolated(kind, i) {
      if (kind == null || i == null) { State.clearIsolated(); return; }
      State.isolated = { kind, i: +i };
      State.notify();
    },
    clearIsolated() { if (State.isolated) { State.isolated = null; State.notify(); } },
    isIsolated() { return !!State.isolated; },
    isolatedSerum() {
      const iso = State.isolated;
      if (!iso || iso.kind !== "serum") return null;
      const ch = IV.DATA && IV.DATA.charts[State.chartIdx];
      if (!ch || !ch.sera) return null;
      return ch.sera.find(s => s.i === iso.i) || ch.sera[iso.i] || null;
    },
    // the norm an isolated ANTIGEN lights on norm-based panels (the tree); a serum
    // lights no tip (it isn't on the tree), so this is null for a serum isolation.
    _isolatedKeptNorm() {
      const iso = State.isolated;
      if (!iso || iso.kind !== "antigen") return null;
      const ch = IV.DATA && IV.DATA.charts[State.chartIdx];
      const a = ch && ch.antigens && (ch.antigens.find(x => x.i === iso.i) || ch.antigens[iso.i]);
      return a ? a.norm : null;
    },

    // ---- #4 serum-coverage (v7/v8): single source of truth ------------------
    // Coverage is active when the Colour menu is in "coverage" mode AND a serum is
    // ISOLATED (v8 — was "exactly one serum selected"). Antigens titrated against
    // that serum are kept and untitrated ones dim (folded into emphasis() and
    // pointEmphasis()); panels draw the pink/black outlines on the titrated ones.
    _covCache: null,
    _coverage() {
      if (State.colorBy !== "coverage") { State._covCache = null; return null; }
      const s = State.isolatedSerum();
      if (!s) { State._covCache = null; return null; }
      const key = State.chartIdx + "\x00s" + s.i;
      if (State._covCache && State._covCache.key === key) return State._covCache.val;
      const ch = IV.DATA && IV.DATA.charts[State.chartIdx];
      let val = null;
      if (ch && ch.logged) {                     // need E2 titers to judge titration
        const titrated = new Set();
        (ch.antigens || []).forEach(a => {
          const row = ch.logged[a.i];
          if (row && row[s.i] != null) titrated.add(a.norm);
        });
        val = { serum: { i: s.i, norm: s.norm }, titrated };
      }
      State._covCache = { key, val };
      return val;
    },
    coverageActive() { return !!State._coverage(); },
    coverageSerum() { const c = State._coverage(); return c ? c.serum : null; },
    coverageTitrated(norm) { const c = State._coverage(); return !!(c && c.titrated.has(norm)); },

    // back-compat clade aliases (v3 F8 names; ui.js clade legend still calls these)
    cladeMode(c) { return State.attrMode("clade", c); },
    cladeZRank(c) { return State.attrZRank("clade", c); },
    cycleClade(c) { return State.cycleAttr("clade", c); },
    resetCladeCycle() { return State.resetCycle(); },

    // Shared emphasis classifier so tree.js and map.js apply identical highlight
    // logic. `extraHidden` lets the map fold in its only-matched dimming. Returns
    // the classes panels toggle (dim / lift / sel) plus a draw-order rank `z`.
    //   sel   — persistently selected (ring)
    //   lift  — transient hover focus (active)
    //   dim   — faded: clade-hidden, sent-to-back (F2), a hover focusing someone
    //           else, OR a "keep" layer is active (manual selection, a front F2
    //           group, the new-since set #3, or serum-coverage titration #4) and
    //           this point is in none of the active keep-sets.
    //   z     — F2 draw-order rank (-1 back, 0 normal, 1 front); panels may reorder.
    emphasis(norm, clade, extraHidden = false) {
      const hidden = extraHidden || State.isCladeHidden(clade);

      // v8: point isolation dominates — norm-based panels (the tree) keep only the
      // isolated antigen's tip (a serum lights no tip) plus coverage-titrated tips.
      if (State.isolated) {
        const keptNorm = State._isolatedKeptNorm();
        const isKept = keptNorm != null && norm === keptNorm;
        const cov = State._coverage();
        const covKeep = !!cov && cov.titrated.has(norm);
        return { dim: hidden || (!isKept && !covKeep), lift: false, sel: isKept, z: isKept ? 1 : 0 };
      }

      return State._coreEmphasis(norm, clade, hidden, State._markersOfNorm(norm));
    },

    // Core emphasis shared by emphasis() (tree, norm-based) and pointEmphasis()
    // (map/grid, identity-based). Folds the active-attr cycle (clade/continent/aa),
    // the F3 marker cycle (markerCats), the manual selection, and #3 new-since.
    _coreEmphasis(norm, clade, hidden, markerCats) {
      const isActive = !!State.active && norm === State.active;
      const isSel = State.selected.has(norm);

      // F2: the active attribute's (clade/continent/aa) cycle
      const attr = State.activeAttr();
      const aval = attr ? State._attrValue(attr, norm, clade) : null;
      const amode = attr ? State.attrMode(attr, aval) : "normal";

      // F3: the marker cycle (always active, independent of colorBy)
      const mk = State._markerEmph(markerCats);

      const isFront = amode === "select" || mk.front;
      const isBack = !isFront && (amode === "back" || mk.back);
      const hasFront = (attr && State._anyFront(attr)) || State._anyFront("marker");

      // #3 new-since: a "keep" layer that dims non-members (coverage needs isolation)
      const newActive = State._newActive();
      const newKeep = newActive && State._newMatch(norm);

      // any active keep-layer dims everything not in one of the active keep-sets
      const hasEmph = State.selected.size > 0 || hasFront || newActive;
      const isEmph = isSel || isFront || newKeep;
      const dim = hidden || isBack ||
        (!!State.active && !isActive) ||
        (hasEmph && !isEmph && !isActive);
      return { dim, lift: isActive, sel: isSel, z: isFront ? 1 : (isBack ? -1 : 0) };
    },

    // v8: point-identity emphasis for panels whose glyphs carry (kind,i) — map/grid.
    // When a point is isolated, ONLY the exact (kind,i) is `sel`; everything else
    // dims (so a serum isolates without lighting its same-name antigen). In coverage
    // mode the titrated antigens stay visible (kept) for their pink/black outlines.
    // With nothing isolated it runs the shared core, resolving "serum" markers by kind.
    pointEmphasis(kind, i, norm, clade) {
      const iso = State.isolated;
      if (iso) {
        const isThis = kind === iso.kind && +i === iso.i;
        const cov = State._coverage();
        const covKeep = !isThis && kind === "antigen" && !!cov && cov.titrated.has(norm);
        const hidden = State.isCladeHidden(clade);
        return { dim: hidden || (!isThis && !covKeep), lift: false, sel: isThis, z: isThis ? 1 : 0 };
      }
      const cats = kind === "serum" ? SERUM_CATS : State._markersOfNorm(norm);
      return State._coreEmphasis(norm, clade, State.isCladeHidden(clade), cats);
    },
  };

  // ---- generic box + click selection (S1) -----------------------------------
  // Installed once per panel SVG by tree.js / map.js. Works off any descendant
  // carrying a `data-norm` attribute, so it needs no knowledge of either panel's
  // layout: a click toggles/replaces, a drag rubber-bands and selects every
  // `[data-norm]` whose centre falls inside the box. Shift/Ctrl/Cmd = additive.
  // The SVG has no viewBox (1 user unit = 1 px), so client offset == user coord.
  function userPoint(svg, e) {
    const r = svg.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  }

  IV.installSelect = function (svg) {
    if (svg.__ivSelect) return;   // idempotent across re-renders (svg node is reused)
    svg.__ivSelect = true;

    let drag = null;   // { x0,y0, additive, point, kind, i, rect, moved }
    let lastClick = null;   // #5 manual double-click: { point, kind, i, t }

    svg.addEventListener("mousedown", e => {
      if (e.button !== 0) return;
      const p = userPoint(svg, e);
      const hit = e.target.closest("[data-norm]");
      drag = {
        x0: p.x, y0: p.y, moved: false,
        additive: e.shiftKey || e.metaKey || e.ctrlKey,
        point: hit ? hit.getAttribute("data-norm") : null,
        kind: hit ? hit.getAttribute("data-kind") : null,
        i: hit ? hit.getAttribute("data-i") : null,
        rect: null,
      };
      e.preventDefault();
    });

    window.addEventListener("mousemove", e => {
      if (!drag) return;
      const p = userPoint(svg, e);
      if (!drag.moved &&
          (Math.abs(p.x - drag.x0) > 3 || Math.abs(p.y - drag.y0) > 3))
        drag.moved = true;
      if (!drag.moved) return;
      if (!drag.rect) {           // first real movement: start the rubber-band
        drag.rect = IV.el("rect", { class: "selbox" });
        svg.appendChild(drag.rect);
      }
      const x = Math.min(p.x, drag.x0), y = Math.min(p.y, drag.y0);
      drag.rect.setAttribute("x", x);
      drag.rect.setAttribute("y", y);
      drag.rect.setAttribute("width", Math.abs(p.x - drag.x0));
      drag.rect.setAttribute("height", Math.abs(p.y - drag.y0));
    });

    window.addEventListener("mouseup", e => {
      if (!drag) return;
      const d = drag; drag = null;
      if (d.rect) d.rect.remove();

      if (!d.moved) {             // a click, not a drag
        if (d.point) {
          // #5 (v9): manual double-click detection — the native dblclick event on
          // SVG is unreliable in Safari, so we pair two clicks on the same point
          // within 300 ms ourselves. Second click → isolate that EXACT point (by
          // identity, not norm) and F2: clear the legend cycle. First/lone click →
          // norm selection (with F1 homolog expansion).
          const now = (window.performance && performance.now) ? performance.now() : Date.now();
          if (lastClick && lastClick.point === d.point && lastClick.kind === d.kind &&
              lastClick.i === d.i && (now - lastClick.t) < 300) {
            lastClick = null;
            State.cycle.clear(); State._zDirty = true;   // F2: dblclick clears the legend cycle
            if (d.kind && d.i != null && d.i !== "") {
              State.setIsolated(d.kind, +d.i);           // identity-carrying glyph (map/grid)
            } else {                                     // tree tip (norm only) → matching antigen
              const ch = IV.DATA && IV.DATA.charts[State.chartIdx];
              const a = ch && ch.antigens && ch.antigens.find(x => x.norm === d.point);
              if (a) State.setIsolated("antigen", a.i); else State.clearIsolated();
            }
            return;
          }
          lastClick = { point: d.point, kind: d.kind, i: d.i, t: now };
          State.isolated = null;          // a fresh single click supersedes isolation (v8)
          const norms = State.expandNorms([d.point]);   // F1 homolog expansion
          if (d.additive) {
            if (State.isSelected(d.point)) State.deselect(norms);
            else State.select(norms, { additive: true });
          } else {
            State.setSelection(norms);   // always notifies → reflects the cleared isolation
          }
        } else {                          // empty space → clear selection + isolation
          lastClick = null;
          const hadIso = !!State.isolated;
          State.isolated = null;
          if (!d.additive) {
            if (State.selected.size) State.clearSelection();
            else if (hadIso) State.notify();
          } else if (hadIso) {
            State.notify();
          }
        }
        return;
      }

      // box-drag: collect every [data-norm] whose bbox centre is inside the box
      const p = userPoint(svg, e);
      const x1 = Math.min(p.x, d.x0), x2 = Math.max(p.x, d.x0);
      const y1 = Math.min(p.y, d.y0), y2 = Math.max(p.y, d.y0);
      const hits = new Set();
      svg.querySelectorAll("[data-norm]").forEach(el => {
        let b; try { b = el.getBBox(); } catch (_) { return; }
        const cx = b.x + b.width / 2, cy = b.y + b.height / 2;
        if (cx >= x1 && cx <= x2 && cy >= y1 && cy <= y2)
          hits.add(el.getAttribute("data-norm"));
      });
      State.isolated = null;             // box-select supersedes isolation
      lastClick = null;                  // a drag breaks any pending double-click
      State.select(State.expandNorms(hits), { additive: d.additive });
    });

    // #5 (v9): isolation is now driven by the manual two-click detection above
    // (the native dblclick event is unreliable in Safari). This listener only
    // SUPPRESSES the panel's own zoom-reset on a point dblclick where the native
    // event *does* fire (e.g. Chrome): capture phase + stopImmediatePropagation so
    // it beats a resetView listener on the SAME SVG node (#1 v7). Where the native
    // dblclick doesn't fire (Safari), the panel's resetView (also native dblclick)
    // doesn't fire either, so there is nothing to suppress. An empty-space dblclick
    // falls through untouched and still resets the view.
    svg.addEventListener("dblclick", e => {
      if (!e.target.closest("[data-norm]")) return;   // empty space → allow zoom-reset
      e.preventDefault();
      e.stopImmediatePropagation();
    }, true);

    // Esc clears isolation (and selection). Bound once globally.
    if (!window.__ivEscBound) {
      window.__ivEscBound = true;
      window.addEventListener("keydown", e => {
        if (e.key !== "Escape") return;
        const had = State.isolated || State.selected.size;
        State.isolated = null; State.selected.clear();
        if (had) State.notify();
      });
    }
  };

  IV.State = State;
})(window.IV);
