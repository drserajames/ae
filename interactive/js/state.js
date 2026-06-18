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

    // ---- F8: per-clade legend cycle (z-order tri-state) ---------------------
    // Agent-COLOUR's legend click cycles a clade through three states:
    //   "normal" -> "select" (front) -> "back" -> "normal"
    // "select": clade raised to front + emphasised (others fade, like a selection)
    // "back":   clade sent behind everything (z-order) and de-emphasised
    // The store owns the cycle; panels read cladeZRank() for draw order and get the
    // emphasis (front pops / back dims) folded into emphasis() below for free.
    cladeCycle: new Map(),   // clade -> "select" | "back"   (absent == "normal")
    _zDirty: false,          // a cycle changed since the last z-order pass
    cladeMode(c) { return (c && State.cladeCycle.get(c)) || "normal"; },
    cycleClade(c) {
      if (!c) return "normal";
      const next = State.cladeMode(c) === "normal" ? "select"
                 : State.cladeMode(c) === "select" ? "back" : "normal";
      if (next === "normal") State.cladeCycle.delete(c); else State.cladeCycle.set(c, next);
      State._zDirty = true;
      State.notify();
      return next;
    },
    resetCladeCycle() {
      if (!State.cladeCycle.size) return;
      State.cladeCycle.clear(); State._zDirty = true; State.notify();
    },
    // draw-order rank for a clade: 1 = front (on top), -1 = back (behind), 0 = normal.
    cladeZRank(c) { const m = State.cladeMode(c); return m === "select" ? 1 : m === "back" ? -1 : 0; },
    _anyFront() { for (const v of State.cladeCycle.values()) if (v === "select") return true; return false; },

    // Shared emphasis classifier so tree.js and map.js apply identical highlight
    // logic. `extraHidden` lets the map fold in its only-matched dimming. Returns
    // the classes panels toggle (dim / lift / sel) plus a draw-order rank `z`.
    //   sel   — persistently selected (ring)
    //   lift  — transient hover focus (active)
    //   dim   — faded: clade-hidden, sent-to-back (F8), a hover focusing someone
    //           else, OR an emphasis (manual selection or front-clade F8) exists
    //           and this point is none of it.
    //   z     — F8 draw-order rank (-1 back, 0 normal, 1 front); panels may reorder.
    emphasis(norm, clade, extraHidden = false) {
      const hidden = extraHidden || State.isCladeHidden(clade);
      const isActive = !!State.active && norm === State.active;
      const isSel = State.selected.has(norm);
      const mode = State.cladeMode(clade);
      const isFront = mode === "select", isBack = mode === "back";
      // a "front" clade behaves as an emphasis layer alongside the manual selection
      const hasEmph = State.selected.size > 0 || State._anyFront();
      const isEmph = isSel || isFront;
      const dim = hidden || isBack ||
        (!!State.active && !isActive) ||
        (hasEmph && !isEmph && !isActive);
      return { dim, lift: isActive, sel: isSel, z: State.cladeZRank(clade) };
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
