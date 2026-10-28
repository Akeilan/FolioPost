"""Shape features for handwritten symbols (pure Python, no dependencies):
the strokes are normalised into a unit square and their direction is
accumulated into a coarse grid (4 directions x 8 x 8), then blurred.
Shared by the template builder (tools/build_ink_templates.py) and the
Ink Equation recogniser."""
import math

GRID = 8
DIRS = 4
DIM = GRID * GRID * DIRS


def bbox(strokes):
    xs = [p[0] for s in strokes for p in s]
    ys = [p[1] for s in strokes for p in s]
    if not xs:
        return 0, 0, 0, 0
    return min(xs), min(ys), max(xs), max(ys)


def features(strokes):
    x0, y0, x1, y1 = bbox(strokes)
    w, h = x1 - x0, y1 - y0
    size = max(w, h, 1e-6)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    v = [0.0] * DIM
    step = 0.03

    def add(x, y, angle, weight):
        # direction: soft split between the two nearest of 0/45/90/135 deg
        a = (angle % math.pi) / (math.pi / DIRS)
        d0 = int(a) % DIRS
        d1 = (d0 + 1) % DIRS
        f = a - int(a)
        gx = min(GRID - 1.001, max(0.0, x * GRID - 0.5))
        gy = min(GRID - 1.001, max(0.0, y * GRID - 0.5))
        ix, iy = int(gx), int(gy)
        fx, fy = gx - ix, gy - iy
        for dd, wd in ((d0, 1 - f), (d1, f)):
            if wd <= 0:
                continue
            base = dd * GRID * GRID
            for jx, wx in ((ix, 1 - fx), (ix + 1, fx)):
                if jx >= GRID or wx <= 0:
                    continue
                for jy, wy in ((iy, 1 - fy), (iy + 1, fy)):
                    if jy >= GRID or wy <= 0:
                        continue
                    v[base + jy * GRID + jx] += weight * wd * wx * wy
    for s in strokes:
        pts = [((p[0] - cx) / size + 0.5, (p[1] - cy) / size + 0.5) for p in s]
        if len(pts) == 1:
            pts = pts * 2
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            seg = math.hypot(bx - ax, by - ay)
            if seg < 1e-9:
                continue
            ang = math.atan2(by - ay, bx - ax)
            n = max(1, int(seg / step))
            for k in range(n):
                t = (k + 0.5) / n
                add(ax + (bx - ax) * t, ay + (by - ay) * t, ang, seg / n)
    # blur (3x3) inside each direction plane
    out = [0.0] * DIM
    for d in range(DIRS):
        base = d * GRID * GRID
        for y in range(GRID):
            for x in range(GRID):
                acc = 0.0
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        xx, yy = x + dx, y + dy
                        if 0 <= xx < GRID and 0 <= yy < GRID:
                            acc += v[base + yy * GRID + xx] * (2 if dx == dy == 0 else 1)
                out[base + y * GRID + x] = acc
    norm = math.sqrt(sum(a * a for a in out)) or 1.0
    return [a / norm for a in out]


def aspect(strokes):
    x0, y0, x1, y1 = bbox(strokes)
    return math.log((y1 - y0 + 1e-3) / (x1 - x0 + 1e-3))


def transform(strokes, slant=0.0, rot=0.0, sx=1.0):
    c, s = math.cos(rot), math.sin(rot)
    out = []
    for st in strokes:
        out.append([((x * c - y * s) * sx + slant * -(x * s + y * c), x * s + y * c)
                    for x, y in st])
    return out
