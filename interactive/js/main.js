// main.js — entry point (MUST be concatenated last)
//
// Wires the bundle into the modules and performs the initial render. The bundle is
// injected by the template as IV.__DATA__ (the /*__DATA__*/ placeholder); module
// load order is fixed by MODULE_ORDER in export_interactive.py.
(function (IV) {
  "use strict";
  const DATA = IV.__DATA__;
  IV.DATA = DATA;

  IV.Colour.init(DATA);
  IV.Tree.layout(DATA.tree);

  IV.Tree.render();
  IV.Map.render();
  IV.UI.renderLegend();
  IV.UI.bindControls();
  IV.UI.updateTitles();
  IV.State.notify(); // initial highlight pass across panels

  let rt;
  window.addEventListener("resize", () => {
    clearTimeout(rt);
    rt = setTimeout(() => { IV.Map.render(); IV.State.notify(); }, 150);
  });
})(window.IV);
