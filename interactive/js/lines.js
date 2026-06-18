// lines.js — map overlay lines (Stage 2: N1 error lines, N2 connection lines)
//
// Owns the line overlays drawn on the antigenic map. Two independent layers,
// each toggled from a small control box in the map pane and both scoped to the
// current selection (or the hovered strain) so the map stays legible:
//
//   N2 connection lines — antigen→serum segment for every measured titer
//      (titer != "*") of a selected antigen. Shows which sera titrate it.
//   N1 error lines      — per titer, a short segment at the antigen and at the
//      serum showing the table-vs-map discrepancy. Red = points too close on
//      the map (should be further apart); blue = too far (should be closer).
//      Threshold titers use the acmacs sigmoid (see formulas below).
//
// Geometry comes from IV.Map (project / scale) so the overlay tracks the map
// exactly — including any future M1 zoom/pan — with a fallback that mirrors
// map.js's fit-projection for the pre-M1 state. Data comes from the active
// chart's E2 fields (titers / logged / column_bases) per CONTRACT.md; when E2
// has not been exported yet these are absent and the overlay self-disables.
//
// Error / stress formulas (PLAN.md "Error / stress formulas"):
//   table_dist = colbase[serum] - logtiter      (clamped >= 0)
//   map_dist   = euclidean distance on oriented map coords
//   regular:   error = table_dist - map_dist
//   "<" titer: D = table_dist - map_dist;  err = (D+1)*sqrt(sigmoid((D+1)*10))
//              (one-sided: a lower-bound distance is only violated by being too
//               close, so this is always a push-apart/"red" error)
//   ">" titer: mirror of "<" with D = map_dist - table_dist, drawn as a
//              pull-together/"blue" error (an upper-bound distance is only
//              violated by being too far).
//   err > 0  => map points too close  (red, push apart)
//   err < 0  => map points too far    (blue, pull together)
(function (IV) {
  "use strict";
  const State = IV.State;

  const RED = "#d62728";    // too close — should move apart
  const BLUE = "#1f77b4";   // too far  — should move together
  const CONN = "#8a8a8a";   // connection line

  const show = { error: false, conn: false };
  let ctlBuilt = false;

  const sigmoid = z => 1 / (1 + Math.exp(-z));
  const activeChart = () => IV.DATA && IV.DATA.charts[State.chartIdx];
  const hasE2 = ch => !!(ch && ch.logged && ch.column_bases);

  // Strains the overlay applies to: the explicit selection, else the hovered one.
  function targetNorms() {
    if (State.selected && State.selected.size) return State.selected;
    if (State.active) return new Set([State.active]);
    return new Set();
  }

  // Map projection: prefer the map's own (tracks zoom/pan); fall back to a copy
  // of map.js's fit-projection so the overlay still aligns before M1 / in tests.
  function getProj(ch) {
    if (IV.Map && typeof IV.Map.project === "function" && IV.Map.scale != null) {
      const t = IV.Map.project(0, 0);
      if (t) return { project: IV.Map.project, scale: IV.Map.scale };
    }
    const wrap = document.getElementById("mapWrap");
    const pts = ch.antigens.filter(a => a.x != null && a.y != null);
    const sera = ch.sera.filter(s => s.x != null && s.y != null);
    const all = pts.concat(sera);
    if (!all.length) return null;
    const xs = all.map(p => p.x), ys = all.map(p => p.y);
    const xmin = Math.min(...xs), xmax = Math.max(...xs);
    const ymin = Math.min(...ys), ymax = Math.max(...ys);
    const W = (wrap && wrap.clientWidth) || 600, H = (wrap && wrap.clientHeight) || 600;
    const pad = 30, spanX = xmax - xmin || 1, spanY = ymax - ymin || 1;
    const scale = Math.min((W - 2 * pad) / spanX, (H - 2 * pad) / spanY);
    const ox = (W - spanX * scale) / 2, oy = (H - spanY * scale) / 2;
    return { project: (x, y) => [ox + (x - xmin) * scale, oy + (ymax - y) * scale], scale };
  }

  // Signed error for the titer between antigen index ai and serum index si.
  // Returns null if missing / not positioned.
  function titerError(ch, ai, si) {
    const lg = ch.logged[ai] && ch.logged[ai][si];
    if (lg == null) return null;                       // "*" / missing
    const raw = ch.titers && ch.titers[ai] ? ch.titers[ai][si] : null;
    const colbase = ch.column_bases[si];
    if (colbase == null) return null;
    let tableDist = colbase - lg;
    if (tableDist < 0) tableDist = 0;
    return { tableDist, raw };
  }

  function errorFromDist(tableDist, mapDist, raw) {
    const lt = typeof raw === "string" && raw[0] === "<";
    const mt = typeof raw === "string" && raw[0] === ">";
    if (lt) { const D = tableDist - mapDist; return (D + 1) * Math.sqrt(sigmoid((D + 1) * 10)); }
    if (mt) { const D = mapDist - tableDist; return -(D + 1) * Math.sqrt(sigmoid((D + 1) * 10)); }
    return tableDist - mapDist;
  }

  function clearLayer(svg) {
    const old = svg && svg.querySelector("g.linesLayer");
    if (old) old.remove();
  }

  function draw() {
    ensureControls();
    const svg = document.getElementById("mapSvg");
    if (!svg) return;
    clearLayer(svg);
    const ch = activeChart();
    let drawn = 0, hint = "";

    if ((show.error || show.conn)) {
      if (!hasE2(ch)) {
        hint = "titer data not exported (E2) — overlay unavailable";
      } else {
        const norms = targetNorms();
        if (!norms.size) {
          hint = "hover a point or drag-box to select strains";
        } else {
          const proj = getProj(ch);
          if (proj) drawn = paint(svg, ch, proj, norms);
        }
      }
    }
    updateHint(drawn, hint);
  }

  function paint(svg, ch, proj, norms) {
    // pointer-events:none so the overlay never intercepts hover / drag-select.
    const g = IV.el("g", { class: "linesLayer", "pointer-events": "none" });
    svg.insertBefore(g, svg.firstChild);   // behind the points
    let n = 0;

    for (const a of ch.antigens) {
      if (!norms.has(a.norm) || a.x == null || a.y == null) continue;
      const A = proj.project(a.x, a.y);
      for (const s of ch.sera) {
        if (s.x == null || s.y == null) continue;
        const te = titerError(ch, a.i, s.i);
        if (!te) continue;                          // unmeasured / missing
        const S = proj.project(s.x, s.y);
        const sdx = S[0] - A[0], sdy = S[1] - A[1];
        const screenDist = Math.hypot(sdx, sdy);

        if (show.conn) {
          g.appendChild(IV.el("line", {
            x1: A[0], y1: A[1], x2: S[0], y2: S[1],
            stroke: CONN, "stroke-width": 0.8, "stroke-opacity": 0.45,
          }));
          n++;
        }

        if (show.error && screenDist > 0) {
          // map_dist in antigenic units = screen distance / scale.
          const err = errorFromDist(te.tableDist, screenDist / proj.scale, te.raw);
          const L = Math.abs(err) * proj.scale;       // error length in px
          if (L < 0.5) continue;                       // negligible
          const ux = sdx / screenDist, uy = sdy / screenDist;
          const col = err > 0 ? RED : BLUE;
          const sign = err > 0 ? 1 : -1;               // push apart vs pull together
          // antigen end moves -sign*u (away when too close); serum end +sign*u.
          line(g, A[0], A[1], A[0] - sign * ux * L, A[1] - sign * uy * L, col);
          line(g, S[0], S[1], S[0] + sign * ux * L, S[1] + sign * uy * L, col);
          n++;
        }
      }
    }
    return n;
  }

  function line(g, x1, y1, x2, y2, col) {
    g.appendChild(IV.el("line", {
      x1, y1, x2, y2, stroke: col, "stroke-width": 1.6, "stroke-opacity": 0.9,
    }));
  }

  // ---- control box (lives in #mapWrap; survives map re-renders) --------------
  function ensureControls() {
    if (ctlBuilt) return;
    const wrap = document.getElementById("mapWrap");
    if (!wrap) return;
    ctlBuilt = true;
    const box = document.createElement("div");
    box.id = "linesCtl";
    box.style.cssText =
      "position:absolute;top:8px;right:8px;z-index:5;background:rgba(255,255,255,.92);" +
      "border:1px solid #ccc;border-radius:5px;padding:6px 8px;font-size:11px;" +
      "line-height:1.5;box-shadow:0 1px 3px rgba(0,0,0,.12);user-select:none;";
    box.innerHTML =
      '<div style="font-weight:600;margin-bottom:2px">Overlays</div>' +
      '<label style="display:block;cursor:pointer"><input type="checkbox" id="lnConn"> connection lines</label>' +
      '<label style="display:block;cursor:pointer"><input type="checkbox" id="lnErr"> error lines</label>' +
      '<div id="lnKey" style="margin-top:4px;color:#777"></div>';
    wrap.appendChild(box);
    box.querySelector("#lnConn").onchange = e => { show.conn = e.target.checked; draw(); };
    box.querySelector("#lnErr").onchange = e => { show.error = e.target.checked; draw(); };
  }

  function updateHint(drawn, hint) {
    const key = document.getElementById("lnKey");
    if (!key) return;
    if (hint) { key.textContent = hint; return; }
    if (!show.error && !show.conn) { key.textContent = ""; return; }
    let h = "";
    if (show.error)
      h += '<span style="color:' + RED + '">▬</span> too close ' +
           '<span style="color:' + BLUE + '">▬</span> too far<br>';
    h += drawn + " line(s) · selected strains only";
    key.innerHTML = h;
  }

  const Lines = {
    render() { draw(); },     // full (re)draw — used on chart/colour re-render
    refresh() { draw(); },    // selection / hover change (subscribed to State)
    // exposed for verification / reuse (C2 per-point stress shares the math)
    _errorFromDist: errorFromDist,
  };

  IV.Lines = Lines;
  State.subscribe(Lines.refresh);
  // Reflow on zoom/pan: M1 reprojects points without a State.notify, so subscribe
  // to the map's view hook to re-lay the overlay against the updated projection.
  if (IV.Map && typeof IV.Map.onView === "function") IV.Map.onView(() => draw());
})(window.IV);
