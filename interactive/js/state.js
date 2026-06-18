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

  const State = {
    chartIdx: 0,          // active chart (Centre dropdown)
    colorBy: "clade",     // "clade" | "continent" | "none"
    onlyMatched: false,   // map: dim antigens with no tree tip
    offClades: new Set(), // clade labels toggled off in the legend
    active: null,         // transient hovered strain norm
    selected: new Set(),  // persistent selection (S1 populates this; empty in F1)

    subscribe(fn) { listeners.push(fn); },
    notify() { for (const fn of listeners) fn(State); },

    setActive(norm) { State.active = norm; State.notify(); },

    // chart change re-renders the map (caller's job), so no implicit notify here
    setChart(i) { State.chartIdx = i; },

    setColorBy(mode) { State.colorBy = mode; },
    setOnlyMatched(on) { State.onlyMatched = on; State.notify(); },

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
    //           else, OR an emphasis (manual selection or a front F2 group) exists
    //           and this point is none of it.
    //   z     — F2 draw-order rank (-1 back, 0 normal, 1 front); panels may reorder.
    emphasis(norm, clade, extraHidden = false) {
      const hidden = extraHidden || State.isCladeHidden(clade);
      const isActive = !!State.active && norm === State.active;
      const isSel = State.selected.has(norm);

      // F2: fold the active attribute's (clade/continent/aa) cycle in
      const attr = State.activeAttr();
      const val = attr ? State._attrValue(attr, norm, clade) : null;
      const mode = attr ? State.attrMode(attr, val) : "normal";
      const isFront = mode === "select", isBack = mode === "back";
      const hasFront = attr ? State._anyFront(attr) : false;

      // a "front" group behaves as an emphasis layer alongside the manual selection
      const hasEmph = State.selected.size > 0 || hasFront;
      const isEmph = isSel || isFront;
      const dim = hidden || isBack ||
        (!!State.active && !isActive) ||
        (hasEmph && !isEmph && !isActive);
      return { dim, lift: isActive, sel: isSel, z: attr ? State.attrZRank(attr, val) : 0 };
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

    let drag = null;   // { x0,y0, additive, point, rect, moved }

    svg.addEventListener("mousedown", e => {
      if (e.button !== 0) return;
      const p = userPoint(svg, e);
      const hit = e.target.closest("[data-norm]");
      drag = {
        x0: p.x, y0: p.y, moved: false,
        additive: e.shiftKey || e.metaKey || e.ctrlKey,
        point: hit ? hit.getAttribute("data-norm") : null,
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
          // F1: a serum click also pulls its homologous antigen (+ its tree tip).
          const norms = State.expandNorms([d.point]);
          if (d.additive) {
            if (State.isSelected(d.point)) State.deselect(norms);
            else State.select(norms, { additive: true });
          } else {
            State.setSelection(norms);
          }
        } else if (!d.additive) {
          State.clearSelection();   // click on empty space clears
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
      State.select(State.expandNorms(hits), { additive: d.additive });
    });
  };

  IV.State = State;
})(window.IV);
