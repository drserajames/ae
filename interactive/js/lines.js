// lines.js — map overlay lines (Stage 2: N1 error lines, N2 connection lines)
//
// Owns the line overlays drawn on the antigenic map. Two independent layers,
// each toggled from a small control box in the map pane and both scoped to the
// current selection (or the hovered strain) so the map stays legible:
//
//   N2 connection lines — antigen→serum segment for every measured titer
//      (titer != "*"). Drawn for selected ANTIGENS (their serum row) and, since
//      v6 #2, selected SERA (their antigen column); pairs are de-duped.
//   N1 error lines      — per titer, a short segment at the antigen and at the
//      serum showing the table-vs-map discrepancy. Red = points too close on
//      the map (should be further apart); blue = too far (should be closer).
//      Threshold titers use the acmacs sigmoid (see formulas below).
//
// The Overlays control box (top-right of the map) also hosts, since v6:
//   F2 "new since report/VCM" toggles — flip shared State.showNew[1]/[2] flags
//      that map.js/tree.js read to bold-outline new antigens/tips (no overlay of
//      our own; we just own the toggles + flag contract).
//   F3 serum circles (off / selected / all) — translucent passage-coloured
//      coverage circles (empirical radius) drawn in our overlay layer.
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

  // overlay feature state: error/conn line layers + serum-circle mode/radius
  // circ: off|selected|all ; circRadius (#8): which serum_circles radius to draw.
  const show = { error: false, conn: false, circ: "off", circRadius: "empirical" };
  let ctlBuilt = false;

  // v6 F2: the "new since report/VCM" toggles drive shared State flags that
  // map.js / tree.js read to bold-outline new antigens/tips. The flags + setters
  // (State.showNewReport / showNewVCM, setShowNewReport / setShowNewVCM) live in
  // state.js (Agent-SELECT); we just own the Overlays checkboxes that flip them.

  // Cap how many strains the line overlay draws at once. paint() is selection×sera,
  // so a T4 branch-click (which can select a whole subtree — ~1500 norms in the H3
  // data) with both layers on would emit thousands of <line>s and jank the map.
  // Above the cap we draw nothing (or just the hovered strain) and hint instead.
  const MAX_LINE_NORMS = 40;
  // A second, finer cap on the number of antigen–serum PAIRS drawn. The norm cap
  // is not enough now that #2 draws a serum's whole column: a single serum can be
  // titrated against ~every antigen (~2900), so one serum norm alone could emit
  // thousands of <line>s. We draw up to this many pairs and hint that it's capped.
  const MAX_PAIRS = 1500;

  const sigmoid = z => 1 / (1 + Math.exp(-z));
  const activeChart = () => IV.DATA && IV.DATA.charts[State.chartIdx];
  const hasE2 = ch => !!(ch && ch.logged && ch.column_bases);

  // Strains the overlay applies to: the explicit selection, else the hovered one.
  function targetNorms() {
    if (State.selected && State.selected.size) return State.selected;
    if (State.active) return new Set([State.active]);
    return new Set();
  }

  // ---- serum passage → colour (for F3 circles) ------------------------------
  // Prefer the serum's own raw passage; fall back to its homologous antigen's
  // classified `pt`. Same regexes map.js uses, kept in sync.
  function serumPassageType(ch, s) {
    const p = (s.passage || "").toUpperCase();
    if (p) {
      if (/(REASSORTANT|RESORTANT|\bNYMC\b|\bIVR-?\d|\bNIB-?\d|\bBX-?\d)/.test(p)) return "reassortant";
      if (/(^|[ _/-])E\d|\bEGG\b/.test(p)) return "egg";
      if (/(MDCK|SIAT|QMC|HCK|\bMK\d|\bC\d|CELL)/.test(p)) return "cell";
    }
    // homologous is a list (v9 #4); use the scalar alias for the first homolog.
    const hi = s.homologous0;
    const ag = (hi != null && ch.antigens[hi]) ? ch.antigens[hi] : null;
    return ag && ag.pt ? ag.pt : null;
  }
  // "#rrggbb" → translucent rgba string (kateri serum-circle fill ≈ alpha 0x18).
  function fillFor(hex) {
    const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex || "");
    if (!m) return "rgba(120,120,120,0.09)";
    return `rgba(${parseInt(m[1], 16)},${parseInt(m[2], 16)},${parseInt(m[3], 16)},0.09)`;
  }

  // Map projection: prefer the map's own (tracks zoom/pan). The fallback below
  // reproduces map.js computeBase() at k=1 — same maxR-based padding — so overlay
  // lines align with the points before the first map render / when project() is null.
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
    // pad = 20 + maxR + 3, maxR = largest rendered point radius (map.js computeBase);
    // pad=30 here previously offset overlay lines from points by the maxR delta.
    const R = 3.5;
    let maxR = R;
    for (const p of all) {
      const r = p.vac ? R * 2.2 : p.ref ? R * 1.43 : (p.serum_id != null) ? R * 1.7 : R;
      if (r > maxR) maxR = r;
    }
    const pad = 20 + maxR + 3;
    const spanX = xmax - xmin || 1, spanY = ymax - ymin || 1;
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
    // Threshold titers are one-sided: a "<" (lower-bound distance) is only violated
    // by being too close (red, err>0); a ">" only by being too far (blue, err<0).
    // The sigmoid term flips sign when D+1<0 in the transition band, which would draw
    // a spurious opposite-colour tick — clamp each branch to its intended sign.
    if (lt) { const D = tableDist - mapDist; return Math.max(0, (D + 1) * Math.sqrt(sigmoid((D + 1) * 10))); }
    if (mt) { const D = mapDist - tableDist; return Math.min(0, -(D + 1) * Math.sqrt(sigmoid((D + 1) * 10))); }
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
    const wantLines = show.error || show.conn;
    const wantCirc = show.circ !== "off";
    if ((!wantLines && !wantCirc) || !ch) { updateHint(0, "", 0); return; }

    const proj = getProj(ch);
    if (!proj) { updateHint(0, "", 0); return; }
    // single overlay group, behind the points, never intercepting pointer events.
    const g = IV.el("g", { class: "linesLayer", "pointer-events": "none" });
    svg.insertBefore(g, svg.firstChild);

    // v8: a single isolated serum (double-click) scopes serum-only features to that
    // exact serum, NOT its norm — so its same-name antigen's lines don't also show.
    const isoSerum = (State.isolatedSerum && State.isolatedSerum()) || null;

    let circDrawn = 0;
    if (wantCirc) circDrawn = paintCircles(g, ch, proj, isoSerum);

    let drawn = 0, hint = "";
    if (wantLines) {
      if (!hasE2(ch)) {
        hint = "titer data not exported (E2) — lines unavailable";
      } else if (isoSerum) {
        // isolated serum: draw only that serum's titer column (no antigen-side row).
        const r = paintSerumLines(g, ch, proj, isoSerum);
        drawn = r.n;
        hint = r.trunc ? `showing first ${drawn} of the serum's titer pairs`
                       : `${drawn} line(s) · isolated serum`;
      } else {
        const norms = targetNorms();
        if (!norms.size) {
          hint = "hover a point or drag-box to select strains/sera";
        } else if (norms.size > MAX_LINE_NORMS) {
          // Selection too large to draw. Keep a single hovered strain live so
          // hover still works even with a big subtree selected.
          if (State.active) {
            const r = paintLines(g, ch, proj, new Set([State.active]));
            drawn = r.n;
            hint = `selection of ${norms.size} too large — showing hovered strain only` +
                   (r.trunc ? ` (first ${drawn} pairs)` : "");
          } else {
            hint = `selection too large for lines (${norms.size}) — narrow it or hover a single strain`;
          }
        } else {
          const r = paintLines(g, ch, proj, norms);
          drawn = r.n;
          if (r.trunc) hint = `showing first ${drawn} titer pairs — narrow the selection for the rest`;
        }
      }
    }
    if (!g.childNodes.length) g.remove();
    updateHint(drawn, hint, circDrawn);
  }

  // Draw error/connection lines for the selected ANTIGENS (their serum row) and the
  // selected SERA (their antigen column). #2: a serum's titers are drawn too. Pairs
  // are de-duped so a selected antigen + its selected serum don't double-draw.
  // Returns { n: pairs drawn, trunc: hit the MAX_PAIRS budget }.
  function paintLines(g, ch, proj, norms) {
    const seen = new Set();
    let n = 0, trunc = false;
    const selAg = ch.antigens.filter(a => norms.has(a.norm) && a.x != null && a.y != null);
    const selSr = ch.sera.filter(s => norms.has(s.norm) && s.x != null && s.y != null);
    // selected antigen × every serum, then selected serum × every antigen
    outer:
    for (const a of selAg)
      for (const s of ch.sera) {
        if (n >= MAX_PAIRS) { trunc = true; break outer; }
        n += pair(g, ch, proj, a, s, seen);
      }
    if (!trunc) outer2:
      for (const s of selSr)
        for (const a of ch.antigens) {
          if (n >= MAX_PAIRS) { trunc = true; break outer2; }
          n += pair(g, ch, proj, a, s, seen);
        }
    return { n, trunc };
  }

  // v8: lines for ONE isolated serum only — its titer column across antigens.
  function paintSerumLines(g, ch, proj, s) {
    if (s.x == null || s.y == null) return { n: 0, trunc: false };
    const seen = new Set();
    let n = 0, trunc = false;
    for (const a of ch.antigens) {
      if (n >= MAX_PAIRS) { trunc = true; break; }
      n += pair(g, ch, proj, a, s, seen);
    }
    return { n, trunc };
  }

  // Draw the one antigen–serum relationship (conn + error) once. Returns 1 if drawn.
  function pair(g, ch, proj, a, s, seen) {
    if (a.x == null || a.y == null || s.x == null || s.y == null) return 0;
    const key = a.i + ":" + s.i;
    if (seen.has(key)) return 0;
    const te = titerError(ch, a.i, s.i);
    if (!te) return 0;                              // unmeasured / missing
    seen.add(key);
    const A = proj.project(a.x, a.y), S = proj.project(s.x, s.y);
    const sdx = S[0] - A[0], sdy = S[1] - A[1];
    const screenDist = Math.hypot(sdx, sdy);
    let drew = 0;

    if (show.conn) {
      g.appendChild(IV.el("line", {
        x1: A[0], y1: A[1], x2: S[0], y2: S[1],
        stroke: CONN, "stroke-width": 0.8, "stroke-opacity": 0.45,
      }));
      drew = 1;
    }
    if (show.error && screenDist > 0) {
      const err = errorFromDist(te.tableDist, screenDist / proj.scale, te.raw);
      const L = Math.abs(err) * proj.scale;          // error length in px
      if (L >= 0.5) {
        const ux = sdx / screenDist, uy = sdy / screenDist;
        const col = err > 0 ? RED : BLUE;
        const sign = err > 0 ? 1 : -1;               // push apart vs pull together
        line(g, A[0], A[1], A[0] - sign * ux * L, A[1] - sign * uy * L, col);
        line(g, S[0], S[1], S[0] + sign * ux * L, S[1] + sign * uy * L, col);
        drew = 1;
      }
    }
    return drew;
  }

  function line(g, x1, y1, x2, y2, col) {
    g.appendChild(IV.el("line", {
      x1, y1, x2, y2, stroke: col, "stroke-width": 1.6, "stroke-opacity": 0.9,
    }));
  }

  // #8: the radius to draw — empirical (report default) or theoretical — falling
  // back to whichever one the bundle actually has for this serum.
  function circleRadius(s) {
    const c = s.circle; if (!c) return null;
    const primary = show.circRadius === "theoretical" ? c.theoretical : c.empirical;
    const other = show.circRadius === "theoretical" ? c.empirical : c.theoretical;
    return primary != null ? primary : other;
  }

  // #7: the single serum whose circle is the coverage subject, or null. The
  // isolated serum (v8) wins; otherwise a single selected serum with a circle in
  // "selected" mode. "all" mode / multiple sera → no single subject. map.js/colour.js
  // read this to tie the pink/black coverage outline to the *shown* circle (so it
  // appears whenever the circle is shown, not only in the coverage colour mode).
  function circleSerum() {
    if (show.circ === "off") return null;
    const ch = activeChart(); if (!ch) return null;
    const iso = State.isolatedSerum && State.isolatedSerum();
    if (iso && iso.circle && circleRadius(iso) > 0) return iso;
    if (show.circ === "selected") {
      const norms = targetNorms();
      const hit = ch.sera.filter(s => norms.has(s.norm) && s.x != null && s.y != null &&
        s.circle && circleRadius(s) > 0);
      if (hit.length === 1) return hit[0];
    }
    return null;
  }

  // #5: a single positioned serum that IS the circle subject (isolated, or the one
  // selected serum) but has NO drawable circle — e.g. H3 VIDRL A9933, which acmacs
  // leaves circle-less (no homologous antigen / no valid homologous titre). Lets the
  // overlay say so explicitly instead of silently drawing nothing. null otherwise.
  function circlelessSubject() {
    if (show.circ === "off") return null;
    const ch = activeChart(); if (!ch) return null;
    const positioned = s => s && s.x != null && s.y != null;
    const iso = State.isolatedSerum && State.isolatedSerum();
    if (iso) return (positioned(iso) && !(circleRadius(iso) > 0)) ? iso : null;
    if (show.circ === "selected") {
      const norms = targetNorms();
      const hit = ch.sera.filter(s => norms.has(s.norm) && positioned(s));
      if (hit.length === 1 && !(circleRadius(hit[0]) > 0)) return hit[0];
    }
    return null;
  }

  // ---- F3: serum coverage circles -------------------------------------------
  // One translucent circle per shown serum, radius (#8) = empirical (report) or
  // theoretical, in antigenic units → px, outline coloured by serum passage.
  // "selected" shows only sera in the selection/hover; "all" shows every positioned
  // serum with a circle. v8: when a serum is isolated, "selected" mode scopes to that
  // exact serum (by index), not its norm — so its same-name antigen's serum isn't in.
  function paintCircles(g, ch, proj, isoSerum) {
    if (proj.scale == null) return 0;
    const sel = show.circ === "all" ? null : targetNorms();   // null = all sera
    let n = 0;
    for (const s of ch.sera) {
      if (s.x == null || s.y == null) continue;
      if (isoSerum && show.circ === "selected") { if (s.i !== isoSerum.i) continue; }
      else if (sel && !sel.has(s.norm)) continue;
      const r = circleRadius(s);
      if (r == null || !(r > 0)) continue;
      const [cx, cy] = proj.project(s.x, s.y);
      const ptype = serumPassageType(ch, s);
      const stroke = (ptype && IV.Colour.passageColor(ptype)) || "#555";
      g.appendChild(IV.Glyph.circle(cx, cy, r * proj.scale, {
        fill: fillFor(stroke), stroke,
        strokeWidth: 2.4, class: "serumCircle",
      }));
      n++;
    }
    // #5: if the single subject serum is circle-less, label it at its point instead of
    // silently drawing nothing (e.g. H3 VIDRL A9933 — no valid homologous titre).
    if (n === 0) {
      const cl = circlelessSubject();
      if (cl && cl.x != null && cl.y != null) {
        const [cx, cy] = proj.project(cl.x, cl.y);
        const txt = IV.el("text", { x: cx + 7, y: cy - 7, class: "serumCircleNote",
          "font-size": 10, fill: "#a00", "pointer-events": "none" });
        txt.textContent = "no valid homologous titre — no circle";
        g.appendChild(txt);
      }
    }
    return n;
  }

  // ---- control box (lives in #mapWrap; survives map re-renders) --------------
  function ensureControls() {
    if (ctlBuilt) return;
    const wrap = document.getElementById("mapWrap");
    if (!wrap) return;
    ctlBuilt = true;
    const box = document.createElement("div");
    box.id = "linesCtl";
    // #3: fixed width + reserved key heights so ticking conn/error never grows the
    // panel (no horizontal reflow from wrapping hints, no vertical jump as the key
    // appears). min-height holds room for the (up to) two-line line key.
    box.style.cssText =
      "position:absolute;top:8px;right:8px;z-index:5;width:184px;background:rgba(255,255,255,.92);" +
      "border:1px solid #ccc;border-radius:5px;padding:6px 8px;font-size:11px;" +
      "line-height:1.5;box-shadow:0 1px 3px rgba(0,0,0,.12);user-select:none;";
    const div = "border-top:1px solid #e2e2e2;margin:5px 0 3px";
    box.innerHTML =
      '<div style="font-weight:600;margin-bottom:2px">Overlays</div>' +
      '<label style="display:block;cursor:pointer"><input type="checkbox" id="lnConn"> connection lines</label>' +
      '<label style="display:block;cursor:pointer"><input type="checkbox" id="lnErr"> error lines</label>' +
      '<div id="lnKey" style="margin:2px 0 0;color:#777;min-height:4.6em"></div>' +
      `<div style="${div}"></div>` +
      '<label style="display:block;cursor:pointer"><input type="checkbox" id="lnNewR"> new since report</label>' +
      '<label style="display:block;cursor:pointer"><input type="checkbox" id="lnNewV"> new since VCM</label>' +
      `<div style="${div}"></div>` +
      '<label style="display:block;cursor:pointer"><input type="checkbox" id="lnCircTh"> theoretical radius</label>' +
      '<label style="display:block">serum circles ' +
      '<select id="lnCirc"><option value="off">off</option>' +
      '<option value="selected">selected</option>' +
      '<option value="all">all</option></select></label>' +
      '<div id="lnCircKey" style="margin-top:2px;color:#777;min-height:1.3em"></div>';
    wrap.appendChild(box);
    box.querySelector("#lnConn").onchange = e => { show.conn = e.target.checked; draw(); };
    box.querySelector("#lnErr").onchange = e => { show.error = e.target.checked; draw(); };

    // #2: the new-since toggles are mutually exclusive. Ticking one unticks the
    // other; we drive the SELECT setters then mirror State back onto both boxes (so
    // it stays correct whether or not the setters themselves also enforce exclusion).
    const nr = box.querySelector("#lnNewR"), nv = box.querySelector("#lnNewV");
    const syncNew = () => { nr.checked = !!State.showNewReport; nv.checked = !!State.showNewVCM; };
    nr.onchange = e => {
      const on = e.target.checked;
      if (on && State.showNewVCM) State.setShowNewVCM(false);
      State.setShowNewReport(on); syncNew();
    };
    nv.onchange = e => {
      const on = e.target.checked;
      if (on && State.showNewReport) State.setShowNewReport(false);
      State.setShowNewVCM(on); syncNew();
    };

    // Circle toggles use State.notify() (not just draw()) so map.js re-runs its
    // circle-tied coverage outline (applyCoverageTo keys off IV.Lines.circleActive()).
    // notify() also fires our own subscribed refresh()→draw(), so the overlay updates.
    box.querySelector("#lnCircTh").onchange = e => {
      show.circRadius = e.target.checked ? "theoretical" : "empirical"; State.notify();
    };
    box.querySelector("#lnCirc").onchange = e => { show.circ = e.target.value; State.notify(); };
  }

  // hint text is static + numeric (no user input), so innerHTML is safe here.
  function updateHint(drawn, hint, circDrawn) {
    const key = document.getElementById("lnKey");
    if (key) {
      if (!show.error && !show.conn) key.textContent = "";
      else {
        let h = "";
        if (show.error && drawn > 0)
          h += '<span style="color:' + RED + '">▬</span> too close ' +
               '<span style="color:' + BLUE + '">▬</span> too far<br>';
        h += hint ? hint : (drawn + " line(s) · selected strains/sera");
        key.innerHTML = h;
      }
    }
    const ck = document.getElementById("lnCircKey");
    if (ck) {
      const cl = circDrawn ? null : circlelessSubject();   // #5
      ck.textContent = show.circ === "off" ? ""
        : circDrawn ? `${circDrawn} ${show.circRadius} circle(s) · outline = passage`
        : cl ? `${cl.serum_id || cl.name}: no valid homologous titre — no circle`
        : (show.circ === "selected" ? "select a serum to show its circle"
                                    : "no serum-circle data");
    }
  }

  const Lines = {
    // NB: the overlay lives inside #mapSvg, which IV.Map.render() clears. A bare
    // IV.Map.render() with no following State.notify() would wipe it — harmless
    // today because every render path (chart switch, colour, resize) also notifies,
    // which fires refresh() below and redraws.
    render() { draw(); },     // full (re)draw — used on chart/colour re-render
    refresh() { draw(); },    // selection / hover change (subscribed to State)
    // #7: the serum whose circle is the coverage subject (single-serum context), or
    // null. map.js applies Colour.coverageOutline tied to this so the pink/black
    // titrated outline shows whenever the circle is shown, not only in coverage mode.
    circleSerum,
    circleActive() { return circleSerum() != null; },
    // exposed for verification / reuse (C2 per-point stress shares the math)
    _errorFromDist: errorFromDist,
  };

  IV.Lines = Lines;
  State.subscribe(Lines.refresh);
  // Reflow on zoom/pan: M1 reprojects points without a State.notify, so subscribe
  // to the map's view hook to re-lay the overlay against the updated projection.
  if (IV.Map && typeof IV.Map.onView === "function") IV.Map.onView(() => draw());
})(window.IV);
