// grid.js — all-centres grid of small multiples (Stage 2: G1)
//
// SCAFFOLD. Empty in F1. Owns the "all centres at once" view: a grid of small
// map panels (one per chart) that all link to the shared tree and to each other.
// Contract (see PLAN.md task G1):
//   - render(): lay out one small-multiple map per chart in DATA.charts; reuse
//     IV.Map's point drawing where practical; share IV.State selection across panels.
//   - refresh(): re-apply highlight across every panel (subscribed to IV.State).
// Toggled from a view control (added with G1). Hidden in F1.
(function (IV) {
  "use strict";
  const State = IV.State;

  const Grid = {
    render() { /* G1 — Stage 2 */ },
    refresh() { /* respond to selection across panels — Stage 2 */ },
  };

  IV.Grid = Grid;
  State.subscribe(Grid.refresh);
})(window.IV);
