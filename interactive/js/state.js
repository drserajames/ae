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
  };

  IV.State = State;
})(window.IV);
