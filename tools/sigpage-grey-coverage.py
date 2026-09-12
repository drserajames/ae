#!/usr/bin/env python3
"""Grey88 coverage in the maps region, isolated from the grid and antialiasing-safely.

Why not the old metric: counting pixels EXACTLY #E0E0E0 is audit trap 13.3.3 -- a 0.94px
stroke antialiases to no exact-#E0E0E0 pixel at all, so it scores ~0, and widening it to
4.2px makes it score in full. That non-linearity, not the drawing, produced "74%" and "141%".

Here: coverage = (255-v)/31 (1.0 == a pixel fully covered by grey88 224), summed over pixels
whose value lies in [190,254] -- lighter than gray63(161) and its blends, darker than paper.
The #CCCCCC map grid also falls in that band, so grid rows/columns are detected structurally
(a line runs the length of the region; a dot does not) and masked with a 4px margin.

Residual bias, equal on both sides and unchanged by this fix: the ~660 in-section antigens'
colour fills land in the band where they are pale, and black edges contribute a 1px fringe.
"""
import subprocess, sys, os, tempfile

def pgm(pdf, dpi=300):
    with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as t:
        png = os.path.join(t, "p")
        subprocess.run(["pdftoppm","-r",str(dpi),"-png","-singlefile",pdf,png],
                       check=True, stderr=subprocess.DEVNULL)
        out = subprocess.run(["magick", png+".png","-colorspace","Gray","-depth","8","pgm:-"],
                             check=True, capture_output=True).stdout
    parts, i = [], 0
    while len(parts) < 4:
        while out[i:i+1].isspace(): i += 1
        if out[i:i+1] == b"#":
            while out[i:i+1] != b"\n": i += 1
            continue
        j = i
        while not out[j:j+1].isspace(): j += 1
        parts.append(out[i:j]); i = j
    return int(parts[1]), int(parts[2]), out[i+1:]

def maps_left(w, h, px, y0, y1):
    for x in range(w//2, w):
        runs, run = 0, 0
        for y in range(y0, y1, 2):
            if px[y*w+x] < 100: run += 1
            else:
                if run > (y1-y0)//40: runs += 1
                run = 0
        if run > (y1-y0)//40: runs += 1
        if runs >= 3: return x
    return None

GRID = range(198, 211)

def grid_masks(w, px, x0, x1, y0, y1):
    """Columns/rows that are map-grid lines: a grid value holds along most of the region."""
    rows = list(range(y0, y1, max(1, (y1-y0)//60)))
    cols = list(range(x0, x1, max(1, (x1-x0)//60)))
    bad_x = set()
    for x in range(x0, x1):
        if sum(1 for y in rows if px[y*w+x] in GRID) >= 0.75*len(rows):
            bad_x.update(range(x-4, x+5))
    bad_y = set()
    for y in range(y0, y1):
        base = y*w
        if sum(1 for x in cols if px[base+x] in GRID) >= 0.75*len(cols):
            bad_y.update(range(y-4, y+5))
    return bad_x, bad_y

def coverage(pdf):
    """Grey88 coverage as a fraction of the unmasked maps area.

    Normalised by area because the ae page is a little wider than AD's, so the absolute
    px-equivalent totals are not comparable but the densities are.
    """
    w, h, px = pgm(pdf)
    y0, y1 = int(h * 0.05), int(h * 0.95)
    x0 = maps_left(w, h, px, y0, y1)
    if x0 is None:
        raise SystemExit(f"{pdf}: could not locate the map grid")
    x1 = w - 20
    bad_x, bad_y = grid_masks(w, px, x0, x1, y0, y1)
    xs = [x for x in range(x0, x1) if x not in bad_x]
    ys = [y for y in range(y0, y1) if y not in bad_y]
    cov = 0.0
    for y in ys:
        base = y * w
        for x in xs:
            v = px[base + x]
            if 190 <= v <= 254:
                cov += (255 - v) / 31.0
    return cov / (len(xs) * len(ys)) * 100.0


def main(argv):
    if len(argv) > 2 and argv[1] == "--brief":
        label, ad, ae = argv[2], argv[3], argv[4]
        ca, cb = coverage(ad), coverage(ae)
        print(f"{label:<28} AD {ca:6.3f}%   ae {cb:6.3f}%   ae/AD {cb / ca * 100:4.0f}%")
        return 0
    for pdf in argv[1:]:
        print(f"{os.path.basename(pdf):<44} grey88 coverage {coverage(pdf):6.3f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
