#!/usr/bin/env python3
"""
P2 render-spike POC: headless consumption of the report's on-chart styling (c["R"] named
styles + c["p"] base plot-spec) to draw ONE report map WITHOUT kateri.

Reads a styled.ace READ-ONLY, resolves a named front style, applies it, draws with PIL.
Proves the styling contract can be consumed headlessly. NOT pixel-perfect by design.
"""
import sys, json, subprocess, math
from PIL import Image, ImageDraw, ImageFont

DECAT = "/Users/sarahjames/AC/eu/bin/decat"

def load_chart(path):
    raw = subprocess.check_output([DECAT, path])
    return json.loads(raw)["c"]

# ---- colour parsing -------------------------------------------------------
_NAMED = {
    "black": (0,0,0,255), "white": (255,255,255,255), "red": (255,0,0,255),
    "green": (0,128,0,255), "blue": (0,0,255,255), "grey": (128,128,128,255),
    "gray": (128,128,128,255), "orange": (255,165,0,255), "transparent": None,
}
def parse_color(c):
    if c is None: return None
    if isinstance(c, str):
        s = c.strip()
        if s in ("", "T", "transparent", ":bright"):   # :bright placeholder -> leave as light grey
            return None if s != ":bright" else (200,200,200,255)
        if s.startswith("#"):
            h = s[1:]
            if len(h) == 6:
                return (int(h[0:2],16), int(h[2:4],16), int(h[4:6],16), 255)
            if len(h) == 8:  # AARRGGBB
                a=int(h[0:2],16); r=int(h[2:4],16); g=int(h[4:6],16); b=int(h[6:8],16)
                return (r,g,b,a)
        low = s.lower()
        if low.startswith("gray") or low.startswith("grey"):
            try:
                pct = int(low[4:]); v=round(pct*255/100); return (v,v,v,255)
            except ValueError: pass
        return _NAMED.get(low, (128,128,128,255))
    return (128,128,128,255)

# ---- base plot-spec -------------------------------------------------------
def base_point_styles(c):
    p = c["p"]; styles = p["P"]; idx = p["p"]; order = p.get("d", list(range(len(idx))))
    pts = []
    for i in range(len(idx)):
        st = dict(styles[idx[i]])
        pts.append({
            "fill": st.get("F"), "outline": st.get("O", "black"),
            "outline_width": st.get("o", 1.0), "size": st.get("s", 1.0),
            "shape": st.get("S", "C"), "shown": True, "label": None,
        })
    return pts, list(order)

# ---- semantic selector matching ------------------------------------------
def match(sel, only, c, nag):
    n_total = len(c["a"]) + len(c["s"])
    if only == 1: cand = range(nag)
    elif only == 0: cand = range(nag, n_total)
    else: cand = range(n_total)
    def sem(i):
        if i < nag: return c["a"][i].get("T", {})
        return c["s"][i-nag].get("T", {})
    if not sel:
        return list(cand)
    if "!i" in sel:
        j = sel["!i"]
        if only == 0: j = nag + j
        return [j] if 0 <= j < n_total else []
    out = []
    for i in cand:
        t = sem(i)
        ok = True
        for k, v in sel.items():
            if k == "C":
                clist = t.get("C", [])
                if isinstance(clist, str): clist = [clist]
                if v not in clist: ok = False; break
            elif k == "R":
                if bool(t.get("R", False)) != bool(v): ok = False; break
            elif k == "V":
                if bool(t.get("V", False)) != bool(v): ok = False; break
            elif k == "p":
                if t.get("p") != v: ok = False; break
            else:
                if t.get(k) != v: ok = False; break
        if ok: out.append(i)
    return out

# ---- style resolver -------------------------------------------------------
def resolve(name, R, out_mods, state, depth=0):
    st = R.get(name)
    if st is None:  # tolerate undefined refs (e.g. -new-1 absent)
        return
    if "V" in st: state["viewport"] = st["V"]
    for m in st.get("A", []):
        keys = set(m.keys())
        if "R" in m and keys <= {"R"}:          # pure parent reference -> recurse
            resolve(m["R"], R, out_mods, state, depth+1)
        else:
            out_mods.append(m)
    if depth == 0:                               # front style carries title + legend
        if "T" in st: state["title"] = st["T"]
        if "L" in st: state["legend_flags"] = st["L"]

# ---- apply ----------------------------------------------------------------
def build(c, style_name):
    R = c["R"]; nag = len(c["a"])
    pts, order = base_point_styles(c)
    state = {"viewport": None, "title": None, "legend_flags": None}
    mods = []
    resolve(style_name, R, mods, state)
    legend_rows = []
    for m in mods:
        sel = m.get("T", {}); only = m.get("A")
        idxs = match(sel, only, c, nag)
        for i in idxs:
            pt = pts[i]
            if "F" in m: pt["fill"] = m["F"]
            if "O" in m: pt["outline"] = m["O"]
            if "o" in m: pt["outline_width"] = m["o"]
            if "s" in m: pt["size"] = m["s"]
            if "S" in m: pt["shape"] = m["S"]
            if "-" in m: pt["shown"] = not m["-"]
            if "l" in m: pt["label"] = m["l"]
            if m.get("D") == "r":                # raise: move to end of draw order
                if i in order: order.remove(i); order.append(i)
        if "L" in m:
            legend_rows.append((m["L"].get("p",0), m["L"].get("t",""), m.get("F")))
    legend_rows.sort(key=lambda r: -r[0])
    return pts, order, state, legend_rows

# ---- draw -----------------------------------------------------------------
def render(c, style_name, out_png, autoframe=True):
    pts, order, state, legend_rows = build(c, style_name)
    W = H = 800
    img = Image.new("RGBA", (W, H), (255,255,255,255))
    dr = ImageDraw.Draw(img)
    lay = c["P"][0]["l"]; tr = c["P"][0].get("t")
    def xf(pt):
        x, y = pt[0], pt[1]
        if tr: x, y = tr[0]*x+tr[1]*y, tr[2]*x+tr[3]*y
        return x, y
    if autoframe:
        xs=[]; ys=[]
        for i,co in enumerate(lay):
            if co and len(co)>=2 and co[0] is not None and pts[i]["shown"]:
                X,Y=xf(co); xs.append(X); ys.append(Y)
        cx=(min(xs)+max(xs))/2; cy=(min(ys)+max(ys))/2
        span=max(max(xs)-min(xs), max(ys)-min(ys))*1.06
        vx,vy,vw,vh = cx-span/2, cy-span/2, span, span
    else:
        vp = state["viewport"] or [-5,-5,10,10]
        vx, vy, vw, vh = vp
    def dev(x, y):
        return ((x-vx)/vw*W, (y-vy)/vh*H)   # NO flip (layout y already screen-down)
    unit_px = W/vw
    for i in order:
        if i >= len(lay): continue
        co = lay[i]
        if not co or len(co) < 2 or co[0] is None: continue
        pt = pts[i]
        if not pt["shown"]: continue
        wx, wy = xf(co); dx, dy = dev(wx, wy)
        r = max(pt["size"] * 0.5 * (W/800.0), 0.8)   # s is ~pixel diameter at 800px ref
        fill = parse_color(pt["fill"]); outline = parse_color(pt["outline"]) or (0,0,0,255)
        ow = max(1, round(pt["outline_width"]))
        shape = (pt["shape"] or "C")[0].upper()
        bbox = [dx-r, dy-r, dx+r, dy+r]
        if shape == "B":
            dr.rectangle(bbox, fill=fill, outline=outline, width=ow)
        elif shape == "T":
            dr.polygon([(dx,dy-r),(dx-r,dy+r),(dx+r,dy+r)], fill=fill, outline=outline)
        else:  # circle / egg approx
            dr.ellipse(bbox, fill=fill, outline=outline, width=ow)
        if pt["label"]:
            lb = pt["label"]; off = lb.get("p",[0,0]); txt = lb.get("t","")
            try: fnt = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", int(lb.get("s",20)*0.5))
            except Exception: fnt = ImageFont.load_default()
            dr.text((dx+off[0]*r*1.5, dy+off[1]*r*1.5), txt, fill=(0,0,0,255), font=fnt, anchor="mm")
    # title
    ttl = state["title"]
    if ttl and ttl.get("T",{}).get("t"):
        t = ttl["T"]; box = ttl.get("B",{}); off = box.get("O",[10,10])
        try: fnt = ImageFont.truetype("/System/Library/Fonts/HelveticaNeue.ttc", int(t.get("s",25)))
        except Exception: fnt = ImageFont.load_default()
        dr.text((off[0], off[1]), t.get("t",""), fill=parse_color(t.get("c","black")), font=fnt)
    # legend
    if legend_rows and state.get("legend_flags",{}) and state["legend_flags"].get("-", True) is not False:
        try: lf = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 16)
        except Exception: lf = ImageFont.load_default()
        lx, ly = 12, H-18*len(legend_rows)-14
        for pr, txt, fillc in legend_rows:
            fc = parse_color(fillc) or (128,128,128,255)
            dr.ellipse([lx, ly, lx+12, ly+12], fill=fc, outline=(0,0,0,255))
            dr.text((lx+18, ly-1), txt, fill=(0,0,0,255), font=lf)
            ly += 18
    img.convert("RGB").save(out_png)
    print(f"wrote {out_png}  frame=[{vx:.1f},{vy:.1f},{vw:.1f}]  legend_rows={len(legend_rows)}")

if __name__ == "__main__":
    ace, style, out = sys.argv[1], sys.argv[2], sys.argv[3]
    c = load_chart(ace)
    render(c, style, out)
