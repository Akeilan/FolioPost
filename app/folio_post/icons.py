"""Icons: Folio's own SVGs (folio_post/icons), then the open-licensed Colibre set
(MPL 2.0 / CC BY-SA 4.0) shipped with Post, in its own blues."""
import os
import re
import weakref
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


_LOG = os.environ.get("FOLIO_ICON_LOG")


# Dark mode: the icons' ink and bodies are recoloured so they read on the dark ribbon: greys are
# turned round (dark ink becomes light, white bodies dark grey); the gold accent is lightened.
ACCENT_DARK = {"d9d9ec": "2e2e55", "222244": "a8a8e0", "333366": "8a8ad0"}
_HEX = re.compile(r"#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})(?![0-9a-fA-F])")


def _dark_hex(m):
    h = m.group(1).lower()
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if h in ACCENT_DARK:
        return "#" + ACCENT_DARK[h]
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    if max(r, g, b) - min(r, g, b) <= 6:          # a neutral grey: light and dark swap
        v = max(0, min(255, round(263.6 - 0.806 * (r + g + b) / 3)))
        return "#%02x%02x%02x" % (v, v, v)
    return m.group(0)


def _dark():
    from . import appearance
    return appearance.is_dark()


def dark_svg(svg):
    return _HEX.sub(_dark_hex, svg)


import colorsys

ORANGE_HUE = 30.5 / 360.0
_RGB_FN = re.compile(r"rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)")


def orange_rgb(r, g, b):
    """A blue (0-255 channels) as the matching Tennessee orange; other hues as they are."""
    h, l, s = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
    if s < 0.18 or not (0.47 <= h <= 0.75):
        return r, g, b
    l2 = l * 0.9 if l < 0.7 else l
    nr, ng, nb = colorsys.hls_to_rgb(ORANGE_HUE, l2, min(1.0, s * 0.95))
    return int(round(nr * 255)), int(round(ng * 255)), int(round(nb * 255))


def _hex_orange(m):
    h = m.group(1)
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return "#%02x%02x%02x" % orange_rgb(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def orange_svg(svg):
    return svg


def _orange_svg_unused(svg):
    svg = _HEX.sub(_hex_orange, svg)
    return _RGB_FN.sub(lambda m: "rgb(%d,%d,%d)" % orange_rgb(*(int(x) for x in m.groups())), svg)


def _load_svg(text, size):
    loader = GdkPixbuf.PixbufLoader.new_with_type("svg")
    loader.set_size(size, size)
    loader.write(text.encode())
    loader.close()
    return loader.get_pixbuf()


def pixbuf(name, size):
    """name: a command ('bold', '.uno:Bold') or a path inside the theme
    ('cmd/lc_bold'); size 16 or 32 (scaled to fit)."""
    dark = _dark()
    key = (name, size, dark)
    if _LOG:
        with open(_LOG, "a") as f:
            f.write("%s %d\n" % (name, size))
    if key in _cache:
        return _cache[key]
    _open()
    pb = None
    base = name.replace(".uno:", "").lower()
    own = os.path.join(OWN, base + ".svg")
    candidates = []
    if os.path.exists(own):
        try:
            if dark:
                with open(own) as f:
                    pb = _load_svg(dark_svg(f.read()), size)
            else:
                pb = GdkPixbuf.Pixbuf.new_from_file_at_size(own, size, size)
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
                    text = orange_svg(data.decode("utf-8", "replace"))
                    if dark:
                        text = dark_svg(text)
                    data = text.encode()
                loader.write(data)
                loader.close()
                pb = loader.get_pixbuf()
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


def swatch_pixbuf(name, size, color):
    """An own icon with its colour bar (the rect at the bottom) in `color` (0xRRGGBB)."""
    import re
    path = os.path.join(OWN, name + ".svg")
    try:
        with open(path) as f:
            svg = f.read()
    except OSError:
        return pixbuf(name, size)
    from .ribbon_defs import resolve
    hexc = "#%06x" % (resolve(color) & 0xFFFFFF)
    if _dark():
        svg = dark_svg(svg)
    svg2, n = re.subn(r'(<rect x="1" y="13"[^>]*fill=")#[0-9a-fA-F]{6}', lambda m: m.group(1) + hexc, svg)
    if not n:
        return pixbuf(name, size)
    from gi.repository import GdkPixbuf
    loader = GdkPixbuf.PixbufLoader.new_with_type("svg")
    loader.set_size(size, size)
    loader.write(svg2.encode())
    loader.close()
    return loader.get_pixbuf()


_images = weakref.WeakSet()


def image(name, size):
    pb = pixbuf(name, size)
    if pb is None:
        img = Gtk.Image.new_from_icon_name("image-missing", Gtk.IconSize.MENU)
        img.set_pixel_size(size)
        return img
    img = Gtk.Image.new_from_pixbuf(pb)
    img._folio_icon = (name, size)
    _images.add(img)
    return img


def restyle():
    """After switching light/dark: every icon made by image() is drawn again in the new colours."""
    for img in list(_images):
        try:
            name, size = img._folio_icon
            pb = pixbuf(name, size)
            if pb is not None:
                img.set_from_pixbuf(pb)
        except Exception:
            pass


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


def dark_image(name, size, rgb=(0x1a, 0x1a, 0x1a)):
    """The icon as a near-black silhouette (for the orange title bar, where white would not read)."""
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
            data[i], data[i + 1], data[i + 2] = rgb
    out = GdkPixbuf.Pixbuf.new_from_data(bytes(data), GdkPixbuf.Colorspace.RGB, True, 8, w, h, rs)
    return Gtk.Image.new_from_pixbuf(out.copy())
