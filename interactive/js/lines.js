// lines.js — map overlay lines (Stage 2: N1 error lines, N2 connection lines)
//
// SCAFFOLD. Empty in F1. Owns line overlays drawn on top of the map SVG.
// Contract (see PLAN.md tasks N1/N2 and CONTRACT.md E2 fields):
//   - render(): draw error lines (red error>0 / blue error<0; sigmoid for "<" titers)
//     and connection lines (titer != "*", within current selection) using the active
//     chart's titers/logged/column_bases/min_col_basis.
//   - refresh(): respond to selection changes (subscribed to IV.State).
// Reads stress/error per the formulas in PLAN.md ("Error / stress formulas").
(function (IV) {
  "use strict";
  const State = IV.State;

  const Lines = {
    render() { /* N1/N2 — Stage 2 */ },
    refresh() { /* respond to selection — Stage 2 */ },
  };

  IV.Lines = Lines;
  State.subscribe(Lines.refresh);
})(window.IV);
