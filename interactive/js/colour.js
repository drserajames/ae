// colour.js — colour API (shared contract; see CONTRACT.md)
//
// The one place that maps a tree node or chart antigen to a colour, honouring the
// active State.colorBy. Feature modules (legend, tree, map, future C1/C2) call
// these rather than re-deriving palettes.
(function (IV) {
  "use strict";
  const State = IV.State;

  // continent palette (for colorBy === "continent")
  const contColor = {
    AFRICA: "#e15759", EUROPE: "#4e79a7", "NORTH-AMERICA": "#59a14f",
    "SOUTH-AMERICA": "#edc948", ASIA: "#f28e2b", OCEANIA: "#b07aa1",
    ANTARCTICA: "#999",
  };
  const BASE = "#4e79a7"; // colorBy === "none"

  let cladeColor = {};      // clade label -> hex (from bundle.clade_color)
  let UNMATCHED = "#d9d9d9";

  const Colour = {
    init(bundle) {
      cladeColor = bundle.clade_color || {};
      UNMATCHED = bundle.unmatched_color || "#d9d9d9";
    },
    unmatched() { return UNMATCHED; },
    cladeColor(c) { return cladeColor[c] || UNMATCHED; },
    clades() { return Object.keys(cladeColor); },

    leaf(lf) {
      if (State.colorBy === "none") return BASE;
      if (State.colorBy === "continent")
        return contColor[(lf.continent || "").toUpperCase()] || UNMATCHED;
      return lf.clade ? (cladeColor[lf.clade] || UNMATCHED) : UNMATCHED;
    },
    antigen(a) {
      if (State.colorBy === "none") return BASE;
      if (State.colorBy === "continent") return BASE; // continent not on antigens
      return a.clade ? (cladeColor[a.clade] || UNMATCHED) : UNMATCHED;
    },
  };

  IV.Colour = Colour;
})(window.IV);
