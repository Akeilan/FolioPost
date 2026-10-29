"""X2-01: does any text, field or button take the desktop theme's colours?

Used from inside a running Folio app (GTK 3). Two desktop themes are tried:
  dark    Adwaita:dark. Every visible text must stay readable: its colour against the pixels
          actually drawn behind it has a contrast of at least 3:1 (1.8:1 for greyed-out text).
  colour  FolioTestColour, a deliberately loud theme (aqua background, pink text, lime
          borders) layered over Adwaita, set where real themes set colours (windows, buttons,
          fields, lists, menus). Nothing in the app's own window may show those
          colours, and no text may be drawn in the theme's pink.

  theme_env(mode, home)   environment for starting the app under a theme
  audit(win, where)       check one window as it is drawn now; returns a list of problems

The canonical copy lives in folio-suite/tests; each app's tests carry a copy so its installed
package can be tested on its own.
"""
import os

THEME = "FolioTestColour"
SIG_BG = (0x13, 0xD6, 0xC2)
SIG_FG = (0xFF, 0x2F, 0xD0)
SIG_LINE = (0xD6, 0xFF, 0x13)

CSS = """@import url("resource:///org/gtk/libgtk/theme/Adwaita/gtk-contained.css");
@define-color theme_bg_color #13d6c2; @define-color theme_fg_color #ff2fd0;
@define-color theme_base_color #13d6c2; @define-color theme_text_color #ff2fd0;
@define-color theme_selected_bg_color #d6ff13; @define-color theme_selected_fg_color #ff2fd0;
window, .background, headerbar, toolbar, menubar, menu, menuitem, popover, tooltip, list, row,
treeview, textview, entry, spinbutton, button, checkbutton, radiobutton, notebook tab, combobox,
label:disabled { color: #ff2fd0; border-color: #d6ff13; }
window, .background, headerbar, toolbar, menubar, menu, menuitem, popover, tooltip,
list, row, treeview.view, textview text, entry, spinbutton, button, notebook, notebook header,
scrollbar, switch, checkbutton check, radiobutton radio { background-color: #13d6c2; background-image: none; }
*:selected { background-color: #d6ff13; color: #ff2fd0; }
"""


def theme_env(mode, home=None):
    """Environment additions that start a GTK app under `mode` ("dark" or "colour")."""
    if mode == "dark":
        return {"GTK_THEME": "Adwaita:dark"}
    home = home or os.path.expanduser("~")
    d = os.path.join(home, ".themes", THEME, "gtk-3.0")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "gtk.css"), "w") as f:
        f.write(CSS)
    return {"GTK_THEME": THEME}


def mode():
    t = os.environ.get("GTK_THEME", "")
    if t == THEME:
        return "colour"
    if "dark" in t.lower():
        return "dark"
    return "light"


def _lum(c):
    def ch(v):
        v = v / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(c[0]) + 0.7152 * ch(c[1]) + 0.0722 * ch(c[2])


def contrast(a, b):
    la, lb = _lum(a), _lum(b)
    if la < lb:
        la, lb = lb, la
    return (la + 0.05) / (lb + 0.05)


def _near(c, s, tol=24):
    return abs(c[0] - s[0]) <= tol and abs(c[1] - s[1]) <= tol and abs(c[2] - s[2]) <= tol


def _settle(win):
    """Wait until the window has stopped changing size (a grab mid-resize is garbage)."""
    import time
    from gi.repository import Gtk
    last = None
    for _ in range(40):
        end = time.time() + 0.1
        while time.time() < end:
            while Gtk.events_pending():
                Gtk.main_iteration_do(False)
            time.sleep(0.005)
        gw = win.get_window()
        if gw is None:
            return
        a = win.get_allocation()
        now = (gw.get_width(), gw.get_height(), a.width, a.height)
        if now == last:
            return
        last = now


def _grab(win):
    """The window as GTK draws it (offscreen, so other windows on top don't get in the way)."""
    import cairo
    _settle(win)
    a = win.get_allocation()
    w, h = max(1, a.width), max(1, a.height)
    img = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cr = cairo.Context(img)
    cr.set_source_rgb(1, 1, 1)
    cr.paint()
    from gi.repository import Gtk
    Gtk.Widget.draw(win, cr)   # not win.draw: an app may use that name for its own things
    img.flush()
    return img, w, h, img.get_stride(), img.get_data()


def _px(data, stride, x, y):
    i = y * stride + x * 4
    return (data[i + 2], data[i + 1], data[i])


def _text_of(w):
    from gi.repository import Gtk
    try:
        if isinstance(w, Gtk.Label):
            return w.get_text()
        if isinstance(w, Gtk.Entry):
            return w.get_text() or w.get_placeholder_text() or "(entry)"
        if isinstance(w, Gtk.TextView):
            b = w.get_buffer()
            return b.get_text(b.get_start_iter(), b.get_end_iter(), False)[:30] or "(text)"
    except Exception:
        pass
    return ""


def _name(w):
    parts = []
    p = w
    for _ in range(4):
        if p is None:
            break
        n = type(p).__name__
        try:
            cls = p.get_style_context().list_classes()
            if cls:
                n += "." + ".".join(cls[:2])
        except Exception:
            pass
        parts.append(n)
        p = p.get_parent()
    return " < ".join(parts)


def _walk(w, out):
    from gi.repository import Gtk
    if not w.get_visible() or not w.get_mapped():
        return
    out.append(w)
    if isinstance(w, Gtk.Container):
        kids = []
        w.forall(lambda c: kids.append(c))
        for c in kids:
            _walk(c, out)


def _scrolled_out(w, win, cx, cy):
    """True when (cx, cy) lies outside a scrolled view `w` sits in (scrolled out of sight)."""
    from gi.repository import Gtk
    p = w.get_parent()
    while p is not None and p is not win:
        if isinstance(p, (Gtk.Viewport, Gtk.ScrolledWindow)):
            a = p.get_allocation()
            xy = p.translate_coordinates(win, 0, 0)
            if xy and not (xy[0] <= cx < xy[0] + a.width and xy[1] <= cy < xy[1] + a.height):
                return True
        p = p.get_parent()
    return False


def _covered(w, win, cx, cy):
    """True when an overlay child is drawn over the point (cx, cy) of `w` (window coordinates),
    or the point is scrolled out of sight."""
    from gi.repository import Gtk
    if _scrolled_out(w, win, cx, cy):
        return True
    child, p = w, w.get_parent()
    while p is not None:
        if isinstance(p, Gtk.Overlay) and child is p.get_child():
            kids = []
            p.forall(lambda c: kids.append(c))
            for k in kids:
                if k is child or not k.get_visible() or not k.get_mapped():
                    continue
                if not k.get_style_context().list_classes() and not isinstance(k, Gtk.Container):
                    continue
                a = k.get_allocation()
                xy = k.translate_coordinates(win, 0, 0)
                if xy and xy[0] <= cx < xy[0] + a.width and xy[1] <= cy < xy[1] + a.height \
                        and a.width * a.height > 2500:
                    return True
        child, p = p, p.get_parent()
    return False


def audit(win, where=""):
    """Problems in `win` as it is drawn now, under the theme the app was started with."""
    from gi.repository import Gtk
    m = mode()
    if m == "light":
        return []
    img, W, H, stride, data = _grab(win)
    problems = []
    seen = set()
    widgets = []
    _walk(win, widgets)
    for w in widgets:
        text = _text_of(w)
        if not text or not text.strip():
            continue
        a = w.get_allocation()
        try:
            xy = w.translate_coordinates(win, 0, 0)
        except Exception:
            xy = None
        if not xy or a.width < 4 or a.height < 4:
            continue
        x0, y0 = max(0, xy[0]), max(0, xy[1])
        x1, y1 = min(W, xy[0] + a.width), min(H, xy[1] + a.height)
        if x1 - x0 < 3 or y1 - y0 < 3:
            continue
        if _covered(w, win, (x0 + x1) // 2, (y0 + y1) // 2):
            continue
        ctx = w.get_style_context()
        st = ctx.get_state()
        c = ctx.get_color(st)
        fg = (int(c.red * 255), int(c.green * 255), int(c.blue * 255))
        # what is drawn behind the text: the commonest colour in the widget's box
        counts = {}
        step = max(1, (x1 - x0) * (y1 - y0) // 1500)
        n = 0
        for y in range(y0, y1, max(1, int(step ** 0.5))):
            for x in range(x0, x1, max(1, int(step ** 0.5))):
                p = _px(data, stride, x, y)
                q = (p[0] >> 3, p[1] >> 3, p[2] >> 3)
                counts[q] = counts.get(q, 0) + 1
                n += 1
        q = max(counts, key=counts.get)
        bg = (q[0] * 8 + 4, q[1] * 8 + 4, q[2] * 8 + 4)
        label = "%s %r" % (_name(w), text[:30])
        if label in seen:
            continue
        insensitive = not w.is_sensitive()
        need = 1.8 if insensitive else 3.0
        r = contrast(fg, bg)
        if r < need:
            seen.add(label)
            problems.append("%s: text #%02x%02x%02x on #%02x%02x%02x, contrast %.1f (%s)"
                            % (where, fg[0], fg[1], fg[2], bg[0], bg[1], bg[2], r, label))
            continue
        if m == "colour":
            if _near(fg, SIG_FG, 30):
                seen.add(label)
                problems.append("%s: text in the theme's colour (%s)" % (where, label))
            elif _near(bg, SIG_BG) or _near(bg, SIG_LINE):
                seen.add(label)
                problems.append("%s: background in the theme's colour (%s)" % (where, label))
    if m == "colour":
        sig = 0
        tot = 0
        for y in range(0, H, 3):
            for x in range(0, W, 3):
                p = _px(data, stride, x, y)
                tot += 1
                if _near(p, SIG_BG) or _near(p, SIG_LINE) or _near(p, SIG_FG):
                    sig += 1
        if tot and sig * 1000 > tot * 5:
            problems.append("%s: %.1f%% of the window is in the theme's colours" % (where, 100.0 * sig / tot))
    return problems


def save(win, path):
    img = _grab(win)[0]
    img.write_to_png(path)


if __name__ == "__main__":
    # python3 themecheck.py dark|colour  -> prints the GTK_THEME value to use (writes the theme)
    import sys
    print(theme_env(sys.argv[1] if len(sys.argv) > 1 else "colour")["GTK_THEME"])
