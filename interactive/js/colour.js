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

  // passage-type markers (P1). Default palette matches chart_modifier.py / the
  // contract; bundle.passage_color [E1] overrides. Shared by the legend marker
  // key (L1) and the tip/point passage markers (P1) so both stay in sync.
  const PASSAGE_DEFAULT = { egg: "#FF0000", cell: "#0000FF", reassortant: "#FFA500" };
  const PASSAGE_LABEL = { egg: "egg", cell: "cell", reassortant: "reassortant" };

  let cladeColor = {};      // clade label -> hex (from bundle.clade_color)
  let cladeLegend = {};     // clade label -> legend text (from bundle.clade_legend [E1])
  let passageColor = {};    // passage type -> hex
  let hasPassage = false;   // did the bundle provide passage_color? (E1/P1 live)
  let UNMATCHED = "#d9d9d9";

  const Colour = {
    init(bundle) {
      cladeColor = bundle.clade_color || {};
      cladeLegend = bundle.clade_legend || {};
      hasPassage = !!bundle.passage_color;
      passageColor = Object.assign({}, PASSAGE_DEFAULT, bundle.passage_color || {});
      UNMATCHED = bundle.unmatched_color || "#d9d9d9";
    },
    unmatched() { return UNMATCHED; },
    cladeColor(c) { return cladeColor[c] || UNMATCHED; },
    cladeLegend(c) { return cladeLegend[c] || c; },
    clades() { return Object.keys(cladeColor); },

    // ---- continent key (colorBy === "continent") ----
    continentColor(c) { return contColor[(c || "").toUpperCase()] || UNMATCHED; },
    continents() { return Object.keys(contColor); },

    // ---- passage markers (P1 + legend marker key) ----
    passageColor(type) { return passageColor[type] || null; },
    passageLabel(type) { return PASSAGE_LABEL[type] || type; },
    passages() { return Object.keys(passageColor); },
    hasPassageMarkers() { return hasPassage; },

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
