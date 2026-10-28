"""Icons for the ribbon: Folio's own, then the open-licensed Colibre set
(MPL 2.0 / CC BY-SA 4.0) shipped with Writer, recoloured in Writer's green."""
import os
import zipfile

from gi.repository import GdkPixbuf, Gtk

from . import SHARE

ARCHIVES = [
    (os.path.join(SHARE, "iconset", "colibre_svg.zip"), "svg"),
    (os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "share", "iconset", "colibre_svg.zip"), "svg"),
    ("/usr/lib/libreoffice/share/config/images_colibre_svg.zip", "svg"),
    ("/usr/share/libreoffice/share/config/images_colibre_svg.zip", "svg"),
    ("/usr/lib/libreoffice/share/config/images_colibre.zip", "png"),
]
OWN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")

_zip = None
_kind = None
_links = {}
_cache = {}


def _open():
    global _zip, _kind
    if _zip is not None:
        return
    for path, kind in ARCHIVES:
        if os.path.exists(path):
            try:
                _zip = zipfile.ZipFile(path)
                _kind = kind
                break
            except (OSError, zipfile.BadZipFile):
                continue
    if _zip is None:
        return
    try:
        for line in _zip.read("links.txt").decode().splitlines():
            parts = line.split()
            if len(parts) == 2:
                _links[parts[0]] = parts[1]
    except KeyError:
        pass


def _resolve(name):
    seen = 0
    while name in _links and seen < 8:
        name = _links[name]
        seen += 1
    return name


# Writer's colour: the borrowed icons' blues become hunter green (other hues — the reds,
# oranges and yellows that mean something — are left alone).
import colorsys
import re as _re

HUNTER_HUE = 128 / 360.0
_HEXC = _re.compile(r"#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})(?![0-9a-fA-F])")
_RGB_FN = _re.compile(r"rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)")


def green_rgb(r, g, b):
    """A blue (0-255 channels) as the matching hunter green; anything else as it is."""
    h, l, s = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
    if s < 0.18 or not (0.47 <= h <= 0.75):
        return r, g, b
    # deep blues become deep green; pale blue fills stay pale
    l2 = l * 0.82 if l < 0.7 else l
    s2 = min(1.0, s * 0.62)
    nr, ng, nb = colorsys.hls_to_rgb(HUNTER_HUE, l2, s2)
    return int(round(nr * 255)), int(round(ng * 255)), int(round(nb * 255))


def _hex_green(m):
    h = m.group(1)
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return "#%02x%02x%02x" % green_rgb(r, g, b)


def green_svg(svg):
    svg = _HEXC.sub(_hex_green, svg)
    return _RGB_FN.sub(lambda m: "rgb(%d,%d,%d)" % green_rgb(*(int(x) for x in m.groups())), svg)


def green_pixbuf(pb):
    if pb is None:
        return pb
    if not pb.get_has_alpha():
        pb = pb.add_alpha(False, 0, 0, 0)
    w, h, rs, n = pb.get_width(), pb.get_height(), pb.get_rowstride(), pb.get_n_channels()
    data = bytearray(pb.get_pixels())
    memo = {}
    for y in range(h):
        for x in range(w):
            i = y * rs + x * n
            if data[i + 3] == 0:
                continue
            k = (data[i], data[i + 1], data[i + 2])
            v = memo.get(k)
            if v is None:
                v = memo[k] = green_rgb(*k)
            data[i], data[i + 1], data[i + 2] = v
    return GdkPixbuf.Pixbuf.new_from_data(bytes(data), GdkPixbuf.Colorspace.RGB, True, 8,
                                          w, h, rs).copy()


def pixbuf(name, size):
    """name: a command ('bold', '.uno:Bold') or a path inside the theme
    ('cmd/lc_bold'); size 16 or 32 (scaled to fit)."""
    key = (name, size)
    if key in _cache:
        return _cache[key]
    _open()
    pb = None
    base = name.replace(".uno:", "").lower()
    own = os.path.join(OWN, base + ".svg")
    candidates = []
    if os.path.exists(own):
        try:
            with open(own, encoding="utf-8") as f:
                svg = green_svg(f.read())
            loader = GdkPixbuf.PixbufLoader.new_with_type("svg")
            loader.set_size(size, size)
            loader.write(svg.encode())
            loader.close()
            pb = loader.get_pixbuf()
        except Exception:
            pb = None
    if pb is None and _zip is not None:
        prefix = "lc_" if size > 20 else "sc_"
        if "/" in base:
            candidates.append(base)
        else:
            candidates += ["cmd/%s%s" % (prefix, base),
                           "cmd/%s%s" % ("sc_" if prefix == "lc_" else "lc_", base)]
        ext = "." + _kind
        for c in candidates:
            path = _resolve(c + ext)
            if path.endswith(".png") and _kind == "svg":
                continue
            try:
                data = _zip.read(path)
            except KeyError:
                continue
            loader = GdkPixbuf.PixbufLoader()
            try:
                if _kind == "svg":
                    loader.set_size(size, size)
                    data = green_svg(data.decode("utf-8", "replace")).encode()
                loader.write(data)
                loader.close()
                pb = loader.get_pixbuf()
                if _kind != "svg":
                    pb = green_pixbuf(pb)
                if pb is not None and (pb.get_width() != size or pb.get_height() != size):
                    w, h = pb.get_width(), pb.get_height()
                    scale = size / max(w, h)
                    pb = pb.scale_simple(max(1, int(w * scale)), max(1, int(h * scale)),
                                         GdkPixbuf.InterpType.BILINEAR)
                break
            except Exception:
                try:
                    loader.close()
                except Exception:
                    pass
                pb = None
    _cache[key] = pb
    return pb


def exists(name):
    return pixbuf(name, 16) is not None


def image(name, size):
    pb = pixbuf(name, size)
    if pb is None:
        img = Gtk.Image.new_from_icon_name("image-missing", Gtk.IconSize.MENU)
        img.set_pixel_size(size)
        return img
    return Gtk.Image.new_from_pixbuf(pb)


def white_image(name, size):
    """The icon as a white silhouette (for the coloured title bar)."""
    pb = pixbuf(name, size)
    if pb is None:
        return image(name, size)
    if not pb.get_has_alpha():
        pb = pb.add_alpha(False, 0, 0, 0)
    w, h, rs, n = pb.get_width(), pb.get_height(), pb.get_rowstride(), pb.get_n_channels()
    data = bytearray(pb.get_pixels())
    for y in range(h):
        for x in range(w):
            i = y * rs + x * n
            data[i] = data[i + 1] = data[i + 2] = 255
    out = GdkPixbuf.Pixbuf.new_from_data(bytes(data), GdkPixbuf.Colorspace.RGB, True, 8,
                                         w, h, rs)
    return Gtk.Image.new_from_pixbuf(out.copy())
