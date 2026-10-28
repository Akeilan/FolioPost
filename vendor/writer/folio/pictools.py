"""Picture and shape tools: Remove Background, Artistic Effects, Compress
Pictures, WordArt Transform and Merge Shapes."""
import math
import os
import tempfile

from gi.repository import GdkPixbuf, GLib, Gtk

from ._lazy import Lazy, bridge, docapi
drawing = Lazy("folio.drawing")

ORIGINALS = {}     # picture name -> original image file (for Reset / Discard)


def _pil():
    try:
        from PIL import Image  # noqa: F401
        return True
    except Exception:
        return False


# ------------------------------------------------------------ graphic I/O
def export_graphic(obj, path=None):
    """Write the picture's image to a PNG file; returns the path."""
    path = path or tempfile.mktemp(prefix="folio-pic-", suffix=".png")
    gp = bridge.create("com.sun.star.graphic.GraphicProvider")
    import uno
    gp.storeGraphic(obj.Graphic, (bridge.prop("URL", uno.systemPathToFileUrl(path)),
                                  bridge.prop("MimeType", "image/png")))
    return path


def load_graphic(path):
    gp = bridge.create("com.sun.star.graphic.GraphicProvider")
    import uno
    return gp.queryGraphic((bridge.prop("URL", uno.systemPathToFileUrl(path)),))


def set_image(obj, img, fmt="PNG", quality=90):
    path = tempfile.mktemp(prefix="folio-pic-", suffix=".png" if fmt == "PNG" else ".jpg")
    if fmt == "JPEG":
        img.convert("RGB").save(path, "JPEG", quality=quality, optimize=True)
    else:
        img.save(path, "PNG", optimize=True)
    obj.Graphic = load_graphic(path)
    return path


def open_image(obj):
    from PIL import Image
    name = obj.Name
    if name not in ORIGINALS:
        ORIGINALS[name] = export_graphic(obj)
    return Image.open(export_graphic(obj)).convert("RGBA")


def original_image(obj):
    from PIL import Image
    p = ORIGINALS.get(obj.Name) or export_graphic(obj)
    ORIGINALS.setdefault(obj.Name, p)
    return Image.open(p).convert("RGBA")


def reset_picture(obj):
    p = ORIGINALS.pop(obj.Name, None)
    if p and os.path.exists(p):
        obj.Graphic = load_graphic(p)
        return True
    return False


# ------------------------------------------------------------ remove background
def background_mask(img, keep=(), remove=(), tolerance=38):
    """A mask (L) of the foreground: background is flood-filled from the image
    edges (and from 'remove' marks) over similar colours; 'keep' marks stay."""
    from PIL import Image
    small = img.convert("RGB")
    w, h = small.size
    scale = 1.0
    if max(w, h) > 400:
        scale = 400.0 / max(w, h)
        small = small.resize((max(1, int(w * scale)), max(1, int(h * scale))))
    sw, sh = small.size
    px = small.load()
    bg = bytearray(sw * sh)
    seeds = []
    for x in range(sw):
        seeds += [(x, 0), (x, sh - 1)]
    for y in range(sh):
        seeds += [(0, y), (sw - 1, y)]
    seeds += [(int(x * sw), int(y * sh)) for x, y in remove]
    keep_px = {(int(x * sw), int(y * sh)) for x, y in keep}
    keep_zone = set()
    for kx, ky in keep_px:
        for dx in range(-8, 9):
            for dy in range(-8, 9):
                keep_zone.add((kx + dx, ky + dy))
    tol2 = tolerance * tolerance
    stack = []
    for sx, sy in seeds:
        if 0 <= sx < sw and 0 <= sy < sh:
            stack.append((sx, sy, px[sx, sy]))
    while stack:
        x, y, ref = stack.pop()
        i = y * sw + x
        if bg[i] or (x, y) in keep_zone:
            continue
        c = px[x, y]
        if (c[0] - ref[0]) ** 2 + (c[1] - ref[1]) ** 2 + (c[2] - ref[2]) ** 2 > tol2:
            continue
        bg[i] = 1
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < sw and 0 <= ny < sh and not bg[ny * sw + nx]:
                stack.append((nx, ny, c))
    mask = Image.frombytes("L", (sw, sh), bytes(0 if b else 255 for b in bg))
    from PIL import ImageFilter
    mask = mask.filter(ImageFilter.MedianFilter(3))
    return mask.resize((w, h), Image.BILINEAR).filter(ImageFilter.GaussianBlur(1))


def remove_background(obj, keep=(), remove=()):
    img = original_image(obj)
    mask = background_mask(img, keep, remove)
    from PIL import ImageChops
    a = ImageChops.multiply(img.getchannel("A"), mask)
    img.putalpha(a)
    set_image(obj, img)


# ------------------------------------------------------------ artistic effects
EFFECTS = ["None", "Pencil Grayscale", "Pencil Sketch", "Line Drawing", "Blur",
           "Paint Strokes", "Glow Edges", "Mosaic Bubbles", "Cutout", "Emboss",
           "Watercolor Sponge", "Film Grain"]


def apply_effect_image(img, name):
    from PIL import Image, ImageFilter, ImageOps, ImageChops
    rgb = img.convert("RGB")
    alpha = img.getchannel("A") if img.mode == "RGBA" else None
    if name == "Pencil Grayscale":
        g = ImageOps.grayscale(rgb)
        inv = ImageOps.invert(g).filter(ImageFilter.GaussianBlur(6))
        out = ImageChops.add(g, inv, scale=1.0)
        out = ImageOps.autocontrast(Image.blend(g, ImageChops.lighter(g, inv), 0.6))
        out = out.convert("RGB")
    elif name == "Pencil Sketch":
        g = ImageOps.grayscale(rgb)
        blur = ImageOps.invert(g).filter(ImageFilter.GaussianBlur(8))
        out = Image.composite(Image.new("L", g.size, 255), g,
                              ImageOps.invert(blur).point(lambda v: 255 if v > 200 else 0))
        out = ImageOps.grayscale(rgb).filter(ImageFilter.CONTOUR).convert("RGB")
    elif name == "Line Drawing":
        out = ImageOps.invert(ImageOps.grayscale(rgb).filter(ImageFilter.FIND_EDGES))
        out = out.point(lambda v: 255 if v > 210 else 0).convert("RGB")
    elif name == "Blur":
        out = rgb.filter(ImageFilter.GaussianBlur(max(2, rgb.width // 120)))
    elif name == "Paint Strokes":
        out = rgb.filter(ImageFilter.ModeFilter(7)).filter(ImageFilter.SMOOTH_MORE)
    elif name == "Glow Edges":
        out = ImageOps.autocontrast(rgb.filter(ImageFilter.FIND_EDGES)).filter(
            ImageFilter.MaxFilter(3))
    elif name == "Mosaic Bubbles":
        k = max(4, rgb.width // 60)
        out = rgb.resize((max(1, rgb.width // k), max(1, rgb.height // k)),
                         Image.BILINEAR).resize(rgb.size, Image.NEAREST)
    elif name == "Cutout":
        out = ImageOps.posterize(rgb.filter(ImageFilter.ModeFilter(5)), 2)
    elif name == "Emboss":
        out = ImageOps.grayscale(rgb).filter(ImageFilter.EMBOSS).convert("RGB")
    elif name == "Watercolor Sponge":
        out = rgb.filter(ImageFilter.MedianFilter(7)).filter(ImageFilter.SMOOTH_MORE)
        out = ImageOps.posterize(out, 4)
    elif name == "Film Grain":
        import random
        noise = Image.effect_noise(rgb.size, 40).convert("RGB")
        out = Image.blend(rgb, ImageChops.multiply(rgb, noise), 0.25)
        _ = random
    else:
        out = rgb
    out = out.convert("RGBA")
    if alpha is not None:
        out.putalpha(alpha)
    return out


def artistic_effect(obj, name):
    img = original_image(obj)
    if name == "None":
        set_image(obj, img)
        return
    set_image(obj, apply_effect_image(img, name))


def effect_thumbnails(obj, size=72):
    """{effect: GdkPixbuf} previews of the selected picture."""
    from PIL import Image
    img = original_image(obj)
    img.thumbnail((size * 2, size * 2))
    out = {}
    for name in EFFECTS:
        t = apply_effect_image(img, name) if name != "None" else img
        t = t.copy()
        t.thumbnail((size, size))
        path = tempfile.mktemp(suffix=".png")
        t.save(path)
        out[name] = GdkPixbuf.Pixbuf.new_from_file(path)
        os.remove(path)
    return out


# ------------------------------------------------------------ compress
RESOLUTIONS = [("High fidelity: preserves quality of the original picture", 0),
               ("HD (330 ppi): good quality for high-definition displays", 330),
               ("Print (220 ppi): excellent quality on most printers and screens", 220),
               ("Web (150 ppi): good for web pages and projectors", 150),
               ("E-mail (96 ppi): minimize document size for sharing", 96)]


def compress(obj, ppi, delete_cropped=True):
    from PIL import Image
    img = Image.open(export_graphic(obj))
    has_alpha = img.mode in ("RGBA", "LA") or "transparency" in img.info
    img = img.convert("RGBA" if has_alpha else "RGB")
    if delete_cropped:
        try:
            c = obj.GraphicCrop
            if c.Left or c.Right or c.Top or c.Bottom:
                # crop values are in mm100 of the original size
                orig = obj.ActualSize if hasattr(obj, "ActualSize") else None
                ow = orig.Width if orig and orig.Width else (obj.Size.Width + c.Left + c.Right)
                oh = orig.Height if orig and orig.Height else (obj.Size.Height + c.Top + c.Bottom)
                sx, sy = img.width / float(ow), img.height / float(oh)
                box = (int(c.Left * sx), int(c.Top * sy), img.width - int(c.Right * sx),
                       img.height - int(c.Bottom * sy))
                if box[2] > box[0] and box[3] > box[1]:
                    img = img.crop(box)
                    obj.GraphicCrop = bridge.struct("com.sun.star.text.GraphicCrop")
        except Exception as e:
            print("compress crop:", e)
    if ppi:
        s = obj.Size
        want_w = int(s.Width / 2540.0 * ppi)
        want_h = int(s.Height / 2540.0 * ppi)
        if img.width > want_w > 0 and img.height > want_h > 0:
            img = img.resize((want_w, want_h), Image.LANCZOS)
    size = obj.Size
    set_image(obj, img, "PNG" if has_alpha else "JPEG", 85 if ppi else 95)
    obj.Size = size


def compress_dialog(win):
    if getattr(win.engine, "native", False):
        from .native import arrange
        return arrange.compress_dialog(win)
    from .widgets import FDialog, heading
    m = win.engine.model
    if m is None:
        return
    if not _pil():
        win.dialogs.message("Picture tools need the python3-pil package.")
        return
    obj = drawing.selected_shape(m)
    d = FDialog(win, "Compress Pictures")
    d.add(heading("Compression options:"))
    only = Gtk.CheckButton.new_with_mnemonic("Apply only to this _picture")
    only.set_active(obj is not None and drawing.kind_of(obj) == "picture")
    only.set_sensitive(only.get_active())
    crop = Gtk.CheckButton.new_with_mnemonic("_Delete cropped areas of pictures")
    crop.set_active(True)
    d.add(only)
    d.add(crop)
    d.add(heading("Resolution:"))
    group, radios = None, []
    for i, (label, ppi) in enumerate(RESOLUTIONS):
        rb = Gtk.RadioButton.new_with_label_from_widget(group, label)
        group = group or rb
        radios.append(rb)
        d.add(rb)
    radios[2].set_active(True)
    res = d.ask()
    ppi = RESOLUTIONS[[r.get_active() for r in radios].index(True)][1]
    one, dc = only.get_active(), crop.get_active()
    d.done()
    if res != Gtk.ResponseType.OK:
        return
    pics = [obj] if one else [m.getGraphicObjects().getByIndex(i)
                              for i in range(m.getGraphicObjects().getCount())]
    um = m.getUndoManager()
    um.enterUndoContext("Compress Pictures")
    try:
        for p in pics:
            try:
                compress(p, ppi, dc)
            except Exception as e:
                print("compress:", e)
    finally:
        um.leaveUndoContext()
    win.status.flash("Compressed %d picture%s." % (len(pics), "" if len(pics) == 1 else "s"))


# ------------------------------------------------------------ WordArt transform
TRANSFORMS = [("#", "Follow Path"), ("Arch", "fontwork-arch-up-curve"),
              ("Arch: Down", "fontwork-arch-down-curve"), ("Circle", "fontwork-circle-curve"),
              ("#", "Warp"), ("Square", "fontwork-plain-text"),
              ("Triangle: Up", "fontwork-triangle-up"),
              ("Triangle: Down", "fontwork-triangle-down"),
              ("Chevron: Up", "fontwork-chevron-up"), ("Chevron: Down", "fontwork-chevron-down"),
              ("Wave: Up", "fontwork-wave"), ("Inflate", "fontwork-inflate"),
              ("Deflate", "mso-spt175" if False else "fontwork-curve-down"),
              ("Slant Up", "fontwork-slant-up"), ("Slant Down", "fontwork-slant-down"),
              ("Fade: Right", "fontwork-fade-right"), ("Fade: Left", "fontwork-fade-left"),
              ("Fade: Up", "fontwork-fade-up"), ("Fade: Down", "fontwork-fade-down")]


def _fontwork_geometry(kind):
    import uno
    follow = "arch" in kind or "circle" in kind
    mode = uno.Enum("com.sun.star.drawing.EnhancedCustomShapeTextPathMode",
                    "PATH" if follow else "SHAPE")
    tp = (bridge.prop("TextPath", True), bridge.prop("ScaleX", False),
          bridge.prop("TextPathMode", mode))
    return uno.Any("[]com.sun.star.beans.PropertyValue",
                   (bridge.prop("Type", kind),
                    bridge.prop("TextPath", uno.Any("[]com.sun.star.beans.PropertyValue", tp))))


def transform(m, obj, kind):
    """Bend WordArt or a text box's text along a path (No Transform = back
    to plain text)."""
    import uno
    if obj.getShapeType().endswith("CustomShape"):
        geo = list(obj.CustomShapeGeometry)
        if any(p.Name == "TextPath" for p in geo):
            size = obj.Size
            uno.invoke(obj, "setPropertyValue", ("CustomShapeGeometry",
                                                  _fontwork_geometry(kind)))
            obj.Size = size
            return obj
    # text box / WordArt frame: replace it with a Fontwork shape of the same text
    try:
        text = obj.getText().getString()
        cur = obj.getText().createTextCursor()
        cur.gotoEnd(True)
        color = cur.CharColor
        font = cur.CharFontName
        bold = cur.CharWeight
    except Exception:
        text, color, font, bold = "Your text here", 0x4472C4, "Carlito", 150
    size = obj.Size
    um = m.getUndoManager()
    um.enterUndoContext("Transform")
    try:
        sh = m.createInstance("com.sun.star.drawing.CustomShape")
        sh.AnchorType = bridge.enum("com.sun.star.text.TextContentAnchorType", "AT_PARAGRAPH")
        anchor = obj.getAnchor()
        anchor.getText().insertTextContent(anchor, sh, False)
        sh.Size = bridge.struct("com.sun.star.awt.Size", Width=max(3000, size.Width),
                                Height=max(1500, size.Height))
        uno.invoke(sh, "setPropertyValue", ("CustomShapeGeometry", _fontwork_geometry(kind)))
        sh.setString(text or "Your text here")
        sh.FillColor = color if color not in (-1, None) and color >= 0 else 0x4472C4
        sh.LineStyle = bridge.enum("com.sun.star.drawing.LineStyle", "NONE")
        try:
            sh.CharFontName = font
            sh.CharWeight = bold
        except Exception:
            pass
        for p in ("HoriOrient", "VertOrient", "HoriOrientPosition", "VertOrientPosition",
                  "HoriOrientRelation", "VertOrientRelation"):
            try:
                setattr(sh, p, getattr(obj, p))
            except Exception:
                pass
        sh.TextWrap = bridge.enum("com.sun.star.text.WrapTextMode", "NONE")
        try:
            sh.TextAutoGrowHeight = False
        except Exception:
            pass
        sh.Size = bridge.struct("com.sun.star.awt.Size", Width=max(6000, size.Width),
                                Height=max(2500, size.Height))
        uno.invoke(sh, "setPropertyValue", ("CustomShapeGeometry", _fontwork_geometry(kind)))
        anchor.getText().removeTextContent(obj)
        docapi.controller(m).select(sh)
        return sh
    finally:
        um.leaveUndoContext()


# ------------------------------------------------------------ merge shapes
def _polys(obj):
    """Polygons (lists of points, mm100, layout coordinates) of a shape."""
    t = obj.getShapeType()
    out = []
    if t.endswith("CustomShape"):
        eng = bridge.create("com.sun.star.drawing.EnhancedCustomShapeEngine",
                            bridge.prop("CustomShape", obj))
        import uno
        shapes = [uno.invoke(eng, "render", ())]
        while shapes:
            s = shapes.pop()
            if hasattr(s, "getCount"):
                shapes += [s.getByIndex(i) for i in range(s.getCount())]
                continue
            try:
                b = s.PolyPolygonBezier
            except Exception:
                b = None
            if b is not None:
                for coords, flags in zip(b.Coordinates, b.Flags):
                    out.append(_flatten(coords, flags))
                continue
            try:
                st = s.getShapeType()
                pos, size = s.Position, s.Size
            except Exception:
                continue
            x, y, w, h = pos.X, pos.Y, size.Width, size.Height
            if st.endswith("EllipseShape"):
                out.append([(x + w / 2.0 + w / 2.0 * math.cos(a * math.pi / 36),
                             y + h / 2.0 + h / 2.0 * math.sin(a * math.pi / 36))
                            for a in range(72)])
            else:
                out.append([(x, y), (x + w, y), (x + w, y + h), (x, y + h)])
    else:
        try:
            b = obj.PolyPolygonBezier
            for coords, flags in zip(b.Coordinates, b.Flags):
                out.append(_flatten(coords, flags))
        except Exception:
            try:
                for poly in obj.PolyPolygon:
                    out.append([(p.X, p.Y) for p in poly])
            except Exception:
                pass
    return [p for p in out if len(p) >= 3]


def _flatten(coords, flags):
    """Bezier curves to line segments."""
    pts = [(p.X, p.Y) for p in coords]
    fl = [str(getattr(f, "value", f)) for f in flags]
    out = []
    i = 0
    while i < len(pts):
        if fl[i] == "CONTROL" and i + 2 < len(pts) and out:
            p0, c1, c2, p3 = out[-1], pts[i], pts[i + 1], pts[i + 2]
            for k in range(1, 13):
                t = k / 12.0
                mt = 1 - t
                out.append((mt ** 3 * p0[0] + 3 * mt * mt * t * c1[0] + 3 * mt * t * t * c2[0] +
                            t ** 3 * p3[0],
                            mt ** 3 * p0[1] + 3 * mt * mt * t * c1[1] + 3 * mt * t * t * c2[1] +
                            t ** 3 * p3[1]))
            i += 3
        else:
            out.append(pts[i])
            i += 1
    return out


def _raster(polys, box, res):
    from PIL import Image, ImageDraw
    x0, y0, x1, y1 = box
    w = max(2, int((x1 - x0) / res) + 3)
    h = max(2, int((y1 - y0) / res) + 3)
    img = Image.new("1", (w, h), 0)
    d = ImageDraw.Draw(img)
    for poly in polys:
        # even-odd: draw each ring with XOR
        ring = Image.new("1", (w, h), 0)
        ImageDraw.Draw(ring).polygon([((x - x0) / res + 1, (y - y0) / res + 1) for x, y in poly],
                                     fill=1)
        from PIL import ImageChops
        img = ImageChops.logical_xor(img, ring)
    _ = d
    return img


def _trace(mask):
    """Marching squares: outlines of the filled areas as point loops (pixels)."""
    w, h = mask.size
    px = mask.load()

    def v(x, y):
        return 1 if 0 <= x < w and 0 <= y < h and px[x, y] else 0
    segs = {}
    for y in range(-1, h):
        for x in range(-1, w):
            a, b, c, d = v(x, y), v(x + 1, y), v(x + 1, y + 1), v(x, y + 1)
            idx = a * 8 + b * 4 + c * 2 + d
            if idx in (0, 15):
                continue
            top, right = (x + 0.5, y), (x + 1, y + 0.5)
            bottom, left = (x + 0.5, y + 1), (x, y + 0.5)
            table = {1: [(left, bottom)], 2: [(bottom, right)], 3: [(left, right)],
                     4: [(right, top)], 5: [(left, top), (right, bottom)],
                     6: [(bottom, top)], 7: [(left, top)], 8: [(top, left)],
                     9: [(top, bottom)], 10: [(top, right), (bottom, left)],
                     11: [(top, right)], 12: [(right, left)], 13: [(right, bottom)],
                     14: [(bottom, left)]}
            for s, e in table[idx]:
                segs.setdefault(s, []).append(e)
    loops = []
    while segs:
        start = next(iter(segs))
        loop = [start]
        cur = start
        while True:
            nxts = segs.get(cur)
            if not nxts:
                segs.pop(cur, None)
                break
            nxt = nxts.pop()
            if not nxts:
                segs.pop(cur, None)
            if nxt == start:
                break
            loop.append(nxt)
            cur = nxt
        if len(loop) >= 4:
            loops.append(loop)
    return loops


def _simplify(pts, eps):
    """Ramer-Douglas-Peucker on a closed loop."""
    if len(pts) < 5:
        return pts

    def rdp(seg):
        if len(seg) < 3:
            return seg
        (x1, y1), (x2, y2) = seg[0], seg[-1]
        dx, dy = x2 - x1, y2 - y1
        n = math.hypot(dx, dy) or 1e-9
        best, bi = -1, 0
        for i in range(1, len(seg) - 1):
            x, y = seg[i]
            d = abs(dy * x - dx * y + x2 * y1 - y2 * x1) / n
            if d > best:
                best, bi = d, i
        if best > eps:
            return rdp(seg[:bi + 1])[:-1] + rdp(seg[bi:])
        return [seg[0], seg[-1]]
    half = len(pts) // 2
    return rdp(pts[:half + 1])[:-1] + rdp(pts[half:] + [pts[0]])[:-1]


def merge_shapes(m, objs, op):
    """op: union, combine, intersect, subtract, fragment."""
    from PIL import ImageChops
    polys = [_polys(o) for o in objs]
    if any(not p for p in polys):
        raise ValueError("These shapes can't be merged.")
    allpts = [pt for ps in polys for poly in ps for pt in poly]
    box = (min(p[0] for p in allpts), min(p[1] for p in allpts),
           max(p[0] for p in allpts), max(p[1] for p in allpts))
    res = max(5.0, max(box[2] - box[0], box[3] - box[1]) / 700.0)
    masks = [_raster(p, box, res) for p in polys]
    if op == "union":
        results = [_reduce(ImageChops.logical_or, masks)]
    elif op == "combine":
        results = [_reduce(ImageChops.logical_xor, masks)]
    elif op == "intersect":
        results = [_reduce(ImageChops.logical_and, masks)]
    elif op == "subtract":
        rest = _reduce(ImageChops.logical_or, masks[1:])
        results = [ImageChops.logical_and(masks[0], ImageChops.invert(rest.convert("L"))
                                          .convert("1"))]
    else:   # fragment: every overlap region becomes its own shape
        results = []
        n = len(masks)
        for i in range(n):
            only = masks[i]
            for j in range(n):
                if j != i:
                    only = ImageChops.logical_and(only, ImageChops.invert(
                        masks[j].convert("L")).convert("1"))
            results.append(only)
        for i in range(n):
            for j in range(i + 1, n):
                results.append(ImageChops.logical_and(masks[i], masks[j]))
    first = objs[0]
    made = []
    um = m.getUndoManager()
    um.enterUndoContext("Merge Shapes")
    try:
        for mask in results:
            loops = _trace(mask)
            if not loops:
                continue
            coords = []
            for loop in loops:
                pts = _simplify(loop, 0.6)
                coords.append(tuple(bridge.struct(
                    "com.sun.star.awt.Point", X=int(box[0] + (x - 1) * res),
                    Y=int(box[1] + (y - 1) * res)) for x, y in pts))
            sh = m.createInstance("com.sun.star.drawing.PolyPolygonShape")
            sh.AnchorType = first.AnchorType
            m.getDrawPage().add(sh)
            import uno
            uno.invoke(sh, "setPropertyValue", ("PolyPolygon", uno.Any(
                "[][]com.sun.star.awt.Point", tuple(coords))))
            for p in ("AnchorPageNo", "FillColor", "FillStyle", "FillTransparence",
                      "LineColor", "LineWidth", "LineStyle", "TextWrap", "Opaque"):
                try:
                    setattr(sh, p, getattr(first, p))
                except Exception:
                    pass
            try:
                sh.HoriOrient = 0
                sh.VertOrient = 0
                sh.HoriOrientRelation = first.HoriOrientRelation
                sh.VertOrientRelation = first.VertOrientRelation
                # place it where the merged outline is
                dx = box[0] - _layout_left(first)
                dy = box[1] - _layout_top(first)
                xs = [p.X for ring in coords for p in ring]
                ys = [p.Y for ring in coords for p in ring]
                sh.HoriOrientPosition = first.HoriOrientPosition + dx + (min(xs) - box[0])
                sh.VertOrientPosition = first.VertOrientPosition + dy + (min(ys) - box[1])
            except Exception as e:
                print("merge place:", e)
            made.append(sh)
        for o in objs:
            try:
                m.getDrawPage().remove(o)
            except Exception:
                pass
    finally:
        um.leaveUndoContext()
    if made:
        from .arrange import select
        select(m, made)
    return made


def _layout_left(obj):
    return min(pt[0] for poly in _polys(obj) for pt in poly)


def _layout_top(obj):
    return min(pt[1] for poly in _polys(obj) for pt in poly)


def _reduce(fn, items):
    out = items[0]
    for it in items[1:]:
        out = fn(out, it)
    return out
