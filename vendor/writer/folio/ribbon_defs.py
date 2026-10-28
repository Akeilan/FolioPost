"""The ribbon's tabs, groups and controls."""
import gi
gi.require_version("PangoCairo", "1.0")
from . import livepreview as LP
from . import lists
from . import objlayout as OL
from . import bordermenu as BM
from gi.repository import Gdk, GLib, Gtk, Pango, PangoCairo

from . import docapi, icons
from .actions import HIGHLIGHTS, word_style
from .ribbon import (CheckControl, ChoiceControl, ComboControl, Group, MenuButton,
                     RibbonButton, SplitButton, Tab, menu_popover)

SIZES = ["8", "9", "10", "10.5", "11", "12", "14", "16", "18", "20", "22", "24", "26",
         "28", "36", "48", "72"]

THEME_COLORS = [0xFFFFFF, 0x000000, 0xE7E6E6, 0x44546A, 0x4472C4, 0xED7D31, 0xA5A5A5,
                0xFFC000, 0x5B9BD5, 0x70AD47]
STANDARD_COLORS = [0xC00000, 0xFF0000, 0xFFC000, 0xFFFF00, 0x92D050, 0x00B050,
                   0x00B0F0, 0x0070C0, 0x002060, 0x7030A0]

# Style gallery: (name, preview markup attributes)
GALLERY = [
    ("Normal", "size='11pt'"),
    ("No Spacing", "size='11pt'"),
    ("Heading 1", "size='14pt' foreground='#2f5496'"),
    ("Heading 2", "size='12pt' foreground='#2f5496'"),
    ("Title", "size='18pt'"),
    ("Subtitle", "size='11pt' foreground='#5a5a5a'"),
    ("Subtle Emphasis", "size='11pt' style='italic' foreground='#404040'"),
    ("Emphasis", "size='11pt' style='italic'"),
    ("Intense Emphasis", "size='11pt' style='italic' foreground='#2f5496'"),
    ("Strong", "size='11pt' weight='bold'"),
    ("Quote", "size='11pt' style='italic' foreground='#404040'"),
    ("Intense Quote", "size='11pt' style='italic' foreground='#2f5496'"),
    ("Subtle Reference", "size='9pt' variant='smallcaps' foreground='#5a5a5a'"),
    ("Intense Reference", "size='9pt' variant='smallcaps' weight='bold' foreground='#2f5496'"),
    ("Book Title", "size='11pt' weight='bold' style='italic'"),
    ("List Paragraph", "size='11pt'"),
]


def _mix(c, other, t):
    r = ((c >> 16) & 255) * (1 - t) + ((other >> 16) & 255) * t
    g = ((c >> 8) & 255) * (1 - t) + ((other >> 8) & 255) * t
    b = (c & 255) * (1 - t) + (other & 255) * t
    return (int(r) << 16) | (int(g) << 8) | int(b)


def _swatch(color, on_pick, tip=None, preview=None):
    b = Gtk.Button()
    if preview is not None:
        win_, fn = preview
        from . import livepreview
        livepreview.attach(win_, b, ("swatch", color), fn(color))
    b.get_style_context().add_class("folio-swatch")
    css = Gtk.CssProvider()
    css.load_from_data(("button { background: #%06x; }" % color).encode())
    b.get_style_context().add_provider(css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
    b.set_tooltip_text(tip or "#%06X" % color)
    b.connect("clicked", lambda *_: on_pick(color))
    return b


def color_palette(on_pick, none_label=None, more=None, popover_ref=None, preview=None,
                  extra=None):
    """Theme colors with tints/shades, standard colors, extras. preview:
    (win, color -> apply(model)) for Live Preview."""
    def swatch(c, pick, tip=None):
        return _swatch(c, pick, tip, preview)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    box.set_margin_start(8)
    box.set_margin_end(8)
    box.set_margin_top(8)
    box.set_margin_bottom(8)

    def pick(c):
        if popover_ref and popover_ref[0]:
            popover_ref[0].popdown()
        on_pick(c)

    if none_label:
        nb = Gtk.Button(label=none_label)
        nb.set_relief(Gtk.ReliefStyle.NONE)
        nb.connect("clicked", lambda *_: pick(None))
        box.pack_start(nb, False, False, 0)
    box.pack_start(Gtk.Label(label="Theme Colors", xalign=0), False, False, 0)
    grid = Gtk.Grid(column_spacing=3, row_spacing=1)
    for col, c in enumerate(THEME_COLORS):
        grid.attach(swatch(c, pick), col, 0, 1, 1)
        for row, t in enumerate((0.8, 0.6, 0.4), start=1):
            base = c if c not in (0xFFFFFF,) else 0xFFFFFF
            v = _mix(base, 0xFFFFFF, t) if c != 0xFFFFFF else _mix(0xFFFFFF, 0x000000, 0.05 * row)
            grid.attach(swatch(v, pick), col, row, 1, 1)
        for row, t in enumerate((0.25, 0.5), start=4):
            v = _mix(c, 0x000000, t) if c != 0x000000 else _mix(0x000000, 0xFFFFFF, 0.5 - 0.15 * (row - 4))
            grid.attach(swatch(v, pick), col, row, 1, 1)
    box.pack_start(grid, False, False, 0)
    box.pack_start(Gtk.Label(label="Standard Colors", xalign=0), False, False, 4)
    std = Gtk.Box(spacing=3)
    for c in STANDARD_COLORS:
        std.pack_start(swatch(c, pick), False, False, 0)
    box.pack_start(std, False, False, 0)
    if more:
        mb = Gtk.Button(label="More Colors...")
        mb.set_relief(Gtk.ReliefStyle.NONE)
        mb.connect("clicked", lambda *_: (popover_ref[0].popdown() if popover_ref else None, more()))
        box.pack_start(mb, False, False, 0)
    for label, fn in extra or ():
        eb = Gtk.Button(label=label)
        eb.set_relief(Gtk.ReliefStyle.NONE)
        eb.connect("clicked", lambda *_a, fn=fn: (popover_ref[0].popdown() if popover_ref
                                                  else None, fn()))
        box.pack_start(eb, False, False, 0)
    return box


def swatch(color, on_pick, tip=None, preview=None):
    return _swatch(color, on_pick, tip, preview)


class StyleGallery(Gtk.Box):
    VISIBLE = 5
    MAX_VISIBLE = 5
    MIN_VISIBLE = 2

    def set_visible_count(self, n):
        """Narrow windows show fewer styles before the group folds up."""
        n = max(self.MIN_VISIBLE, min(self.MAX_VISIBLE, n))
        if n != self.VISIBLE:
            self.VISIBLE = n
            self.fill()

    def __init__(self, win):
        Gtk.Box.__init__(self, spacing=0)
        self.win = win
        self.get_style_context().add_class("folio-gallery")
        self.first = 0
        self.current = "Normal"
        self.items = Gtk.Box(spacing=0)
        self.pack_start(self.items, False, False, 0)
        nav = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        for icon, sign in (("pan-up-symbolic", -1), ("pan-down-symbolic", 1)):
            b = Gtk.Button()
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.add(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU))
            b.connect("clicked", lambda _b, s=sign: self.scroll(s * self.VISIBLE))
            nav.pack_start(b, False, False, 0)
        more = Gtk.Button()
        more.set_relief(Gtk.ReliefStyle.NONE)
        more.add(Gtk.Image.new_from_icon_name("view-more-symbolic", Gtk.IconSize.MENU))
        more.set_tooltip_text("More styles")
        more.connect("clicked", lambda b: self.more(b))
        nav.pack_start(more, False, False, 0)
        self.pack_start(nav, False, False, 0)
        self.fill()

    previews = {}

    def update_previews(self, previews):
        """Show each style as it is defined in the document."""
        self.previews = previews or {}
        self.fill()

    def _tile(self, name, attrs):
        caps = False
        if name in self.previews:
            attrs, caps = self.previews[name]
        b = Gtk.Button()
        b.get_style_context().add_class("folio-style")
        b.set_focus_on_click(False)
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        prev = Gtk.Label()
        prev.set_markup("<span %s>%s</span>" % (attrs, "AABBCCDD" if caps else "AaBbCcDd"))
        prev.set_ellipsize(Pango.EllipsizeMode.END)
        prev.set_max_width_chars(9)
        v.pack_start(prev, True, True, 0)
        lab = Gtk.Label(label=name)
        lab.get_style_context().add_class("name")
        lab.set_ellipsize(Pango.EllipsizeMode.END)
        lab.set_max_width_chars(12)
        v.pack_start(lab, False, False, 0)
        b.add(v)
        b.set_tooltip_text(name)
        b.connect("clicked", lambda *_: (self.win.live_preview.commit(),
                                         self.win.actions.apply_style(name),
                                         self.win.focus_document()))
        b.connect("button-press-event", self._right_click, name)
        from . import livepreview
        livepreview.attach(self.win, b, ("style", name), livepreview.para_style(name))
        b.style_name = name
        if name == self.current:
            b.get_style_context().add_class("current")
        return b

    def _right_click(self, widget, ev, name):
        if ev.button != 3:
            return False
        from .stylemodify import context_menu
        context_menu(self.win, name, widget, ev)
        return True

    def entries(self):
        """(name, default markup) for the styles shown in the gallery."""
        from .stylemodify import gallery_names
        defaults = dict(GALLERY)
        try:
            names = gallery_names(self.win.engine.model)
        except Exception:
            names = [n for n, _a in GALLERY]
        return [(n, defaults.get(n, "size='11pt'")) for n in names]

    def fill(self):
        for c in self.items.get_children():
            self.items.remove(c)
        entries = self.entries()
        self.first = max(0, min(self.first, len(entries) - self.VISIBLE))
        for name, attrs in entries[self.first:self.first + self.VISIBLE]:
            self.items.pack_start(self._tile(name, attrs), False, False, 0)
        self.items.show_all()

    def scroll(self, step):
        self.first = max(0, min(len(self.entries()) - self.VISIBLE, self.first + step))
        self.fill()

    def set_current(self, name):
        self.current = name
        for b in self.items.get_children():
            ctx = b.get_style_context()
            if b.style_name == name:
                ctx.add_class("current")
            else:
                ctx.remove_class("current")

    def more(self, button):
        pop = Gtk.Popover.new(button)
        grid = Gtk.FlowBox()
        grid.set_max_children_per_line(5)
        grid.set_selection_mode(Gtk.SelectionMode.NONE)
        for name, attrs in self.entries():
            grid.add(self._tile(name, attrs))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.pack_start(grid, False, False, 0)
        box.pack_start(Gtk.Separator(), False, False, 2)
        for label, act in (("Create a Style", "new-style"), ("Clear Formatting", "clear-all-formatting"),
                           ("Apply Styles...", "apply-styles")):
            b = Gtk.Button(label=label)
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.get_child().set_xalign(0)
            b.connect("clicked", lambda _b, a=act: (pop.popdown(), self.win.run(a)))
            box.pack_start(b, False, False, 0)
        box.show_all()
        pop.add(box)
        pop.popup()

    # KeyTip support
    keytip = "L"

    def press(self):
        self.more(self)


class StyleSetGallery(Gtk.Box):
    """Design > Document Formatting: thumbnails of each style set drawn with
    the document's current colours and fonts."""
    VISIBLE = 6
    W, H = 78, 64

    def __init__(self, win):
        Gtk.Box.__init__(self, spacing=0)
        self.win = win
        self.get_style_context().add_class("folio-gallery")
        self.get_style_context().add_class("folio-styleset")
        self.first = 0
        self.items = Gtk.Box(spacing=2)
        self.pack_start(self.items, False, False, 0)
        nav = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        for icon, step in (("pan-up-symbolic", -self.VISIBLE),
                           ("pan-down-symbolic", self.VISIBLE)):
            b = Gtk.Button()
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.add(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU))
            b.connect("clicked", lambda _b, st=step: self.scroll(st))
            nav.pack_start(b, False, False, 0)
        more = Gtk.Button()
        more.set_relief(Gtk.ReliefStyle.NONE)
        more.add(Gtk.Image.new_from_icon_name("view-more-symbolic", Gtk.IconSize.MENU))
        more.set_tooltip_text("More style sets")
        more.connect("clicked", lambda b: self.more(b))
        nav.pack_start(more, False, False, 0)
        self.pack_start(nav, False, False, 0)
        self.fill()

    def names(self):
        return list(docapi.STYLE_SETS)

    def _draw_thumb(self, area, cr, name):
        W, H = area.get_allocated_width(), area.get_allocated_height()
        cr.set_source_rgb(1, 1, 1)
        cr.paint()
        m = self.win.engine.model
        try:
            props = docapi.style_set_props(m, name)
            fonts = docapi.FONT_PAIRS.get("Modern")
            if m is not None:
                ps = docapi.para_styles(m)
                fonts = (ps.getByName("Heading 1").CharFontName,
                         ps.getByName("Standard").CharFontName)
        except Exception:
            props = docapi.style_set_props(None, name)
            fonts = ("Carlito", "Carlito")

        def rgb(c, default=(0, 0, 0)):
            if not isinstance(c, int) or c < 0:
                return default
            return ((c >> 16) & 255) / 255.0, ((c >> 8) & 255) / 255.0, (c & 255) / 255.0

        def text(y, label, st, scale):
            e = props[st]
            lay = area.create_pango_layout(label.upper() if e.get("caps") else label)
            fd = Pango.FontDescription("%s %g" % (fonts[0], max(4.0, e["size"] * scale)))
            if e.get("bold"):
                fd.set_weight(Pango.Weight.BOLD)
            if e.get("italic"):
                fd.set_style(Pango.Style.ITALIC)
            lay.set_font_description(fd)
            tw, th = lay.get_pixel_size()
            x = (W - tw) / 2 if e.get("align") == "center" else 6
            if e.get("shade") not in (None, -1):
                cr.set_source_rgb(*rgb(e["shade"]))
                cr.rectangle(4, y - 1, W - 8, th + 2)
                cr.fill()
            cr.set_source_rgb(*rgb(e.get("color"), (0.1, 0.1, 0.1) if e.get("color") != 0xFFFFFF
                                   else (1, 1, 1)))
            cr.move_to(x, y)
            PangoCairo.show_layout(cr, lay)
            if e.get("border"):
                side, w, c = e["border"]
                cr.set_source_rgb(*rgb(c))
                cr.set_line_width(max(0.6, w / 35.0))
                yy = y + th + 1 if side == "bottom" else y - 1
                cr.move_to(4, yy)
                cr.line_to(W - 4, yy)
                cr.stroke()
            return y + th + 3

        y = 4
        y = text(y, "Title", "Title", 0.38)
        y = text(y, "Heading 1", "Heading 1", 0.45)
        cr.set_source_rgb(0.55, 0.55, 0.55)
        for i in range(3):
            if y + 2 > H - 2:
                break
            cr.rectangle(6, y + 1, (W - 12) * (0.92 if i < 2 else 0.6), 1.4)
            cr.fill()
            y += 4
        return False

    def _tile(self, name):
        b = Gtk.Button()
        b.get_style_context().add_class("folio-style")
        b.set_focus_on_click(False)
        area = Gtk.DrawingArea()
        area.set_size_request(self.W, self.H)
        area.connect("draw", self._draw_thumb, name)
        b.add(area)
        b.set_tooltip_text(name)
        b.connect("clicked", lambda *_: (self.win.run(("style-set", name)),
                                         self.win.focus_document()))
        b.set_name = name
        cur = None
        try:
            cur = docapi.current_style_set(self.win.engine.model)
        except Exception:
            pass
        if name == (cur or "Default"):
            b.get_style_context().add_class("current")
        return b

    def fill(self):
        for c in self.items.get_children():
            self.items.remove(c)
        for name in self.names()[self.first:self.first + self.VISIBLE]:
            self.items.pack_start(self._tile(name), False, False, 0)
        self.items.show_all()

    def refresh(self):
        self.fill()

    def scroll(self, step):
        self.first = max(0, min(len(self.names()) - self.VISIBLE, self.first + step))
        self.fill()

    def more(self, button):
        pop = Gtk.Popover.new(button)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_border_width(6)
        for title, names in (("This Document", [docapi.current_style_set(self.win.engine.model)
                                                if self.win.engine.model is not None
                                                else "Default"]),
                             ("Built-In", self.names())):
            lab = Gtk.Label(xalign=0)
            lab.set_markup("<b>%s</b>" % title)
            box.pack_start(lab, False, False, 0)
            grid = Gtk.FlowBox()
            grid.set_max_children_per_line(6)
            grid.set_selection_mode(Gtk.SelectionMode.NONE)
            for n in names:
                t = self._tile(n)
                t.connect("clicked", lambda *_: pop.popdown())
                grid.add(t)
            box.pack_start(grid, False, False, 0)
        box.pack_start(Gtk.Separator(), False, False, 2)
        for label, act in (("Reset to the Default Style Set", ("style-set", "Default")),
                           ("Save as a New Style Set...", "set-as-default")):
            b = Gtk.Button(label=label)
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.get_child().set_xalign(0)
            b.connect("clicked", lambda _b, a=act: (pop.popdown(), self.win.run(a)))
            box.pack_start(b, False, False, 0)
        box.show_all()
        pop.add(box)
        pop.popup()

    keytip = "SS"

    def press(self):
        self.more(self)


class TableStyleGallery(Gtk.Box):
    """Table Design > Table Styles: thumbnails drawn with the same rules the
    document uses, following the Table Style Options."""
    VISIBLE = 7
    W, H = 60, 44

    def __init__(self, win):
        Gtk.Box.__init__(self, spacing=0)
        from . import tablestyles
        self.ts = tablestyles
        self.win = win
        self.opts = dict(tablestyles.DEFAULT_OPTS)
        self.current = ("grid", 0)
        self.get_style_context().add_class("folio-gallery")
        self.get_style_context().add_class("folio-styleset")
        self.flat = [it for _s, items in tablestyles.all_styles() for it in items]
        self.first = 5          # start at Grid Table 1 Light, like the original
        self.items = Gtk.Box(spacing=2)
        self.pack_start(self.items, False, False, 0)
        nav = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        for icon, step in (("pan-up-symbolic", -self.VISIBLE),
                           ("pan-down-symbolic", self.VISIBLE)):
            b = Gtk.Button()
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.add(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU))
            b.connect("clicked", lambda _b, st=step: self.scroll(st))
            nav.pack_start(b, False, False, 0)
        more = Gtk.Button()
        more.set_relief(Gtk.ReliefStyle.NONE)
        more.add(Gtk.Image.new_from_icon_name("view-more-symbolic", Gtk.IconSize.MENU))
        more.set_tooltip_text("More table styles")
        more.connect("clicked", lambda b: self.more(b))
        nav.pack_start(more, False, False, 0)
        self.pack_start(nav, False, False, 0)
        self.fill()

    def _draw(self, area, cr, kind, accent):
        W, H = area.get_allocated_width(), area.get_allocated_height()
        cr.set_source_rgb(1, 1, 1)
        cr.paint()
        rows, cols = 5, 5
        cw, ch = (W - 6) / cols, (H - 6) / rows
        x0, y0 = 3, 3

        def rgb(c):
            return ((c >> 16) & 255) / 255.0, ((c >> 8) & 255) / 255.0, (c & 255) / 255.0
        cells = [[self.ts.cell(kind, accent, self.opts, r, c, rows, cols) for c in range(cols)]
                 for r in range(rows)]
        for r in range(rows):
            for c in range(cols):
                s = cells[r][c]
                x, y = x0 + c * cw, y0 + r * ch
                if s["fill"] != -1:
                    cr.set_source_rgb(*rgb(s["fill"]))
                    cr.rectangle(x, y, cw + 0.5, ch + 0.5)
                    cr.fill()
                # a little 'text' dash
                tc = s["color"] if s["color"] != -1 else 0x404040
                cr.set_source_rgb(*rgb(tc))
                cr.rectangle(x + cw * 0.25, y + ch / 2 - (0.8 if s["bold"] else 0.5),
                             cw * 0.5, 1.6 if s["bold"] else 1.0)
                cr.fill()
        for r in range(rows):
            for c in range(cols):
                s = cells[r][c]
                x, y = x0 + c * cw, y0 + r * ch
                for side, (ax, ay, bx, by) in (("top", (x, y, x + cw, y)),
                                               ("bottom", (x, y + ch, x + cw, y + ch)),
                                               ("left", (x, y, x, y + ch)),
                                               ("right", (x + cw, y, x + cw, y + ch))):
                    b = s[side]
                    if b:
                        cr.set_source_rgb(*rgb(b[1]))
                        cr.set_line_width(max(0.8, b[0] * 0.8))
                        cr.move_to(ax, ay)
                        cr.line_to(bx, by)
                        cr.stroke()
        return False

    def _tile(self, name, kind, accent):
        b = Gtk.Button()
        b.get_style_context().add_class("folio-style")
        b.set_focus_on_click(False)
        area = Gtk.DrawingArea()
        area.set_size_request(self.W, self.H)
        area.connect("draw", self._draw, kind, accent)
        b.add(area)
        b.set_tooltip_text(name)
        b.connect("clicked", lambda *_: (self.win.live_preview.commit(),
                                         self.win.run(("table-style2", (kind, accent))),
                                         self.win.focus_document()))
        from . import livepreview

        def prev(m, kind=kind, accent=accent):
            self.ts.apply(m, kind, accent)
        prev.native = lambda w, kind=kind, accent=accent: w.actions._run(("table-style2", (kind, accent)))
        livepreview.attach(self.win, b, ("table", kind, accent), prev)
        if (kind, accent) == self.current:
            b.get_style_context().add_class("current")
        return b

    def fill(self):
        for c in self.items.get_children():
            self.items.remove(c)
        for name, kind, accent in self.flat[self.first:self.first + self.VISIBLE]:
            self.items.pack_start(self._tile(name, kind, accent), False, False, 0)
        self.items.show_all()

    def scroll(self, step):
        self.first = max(0, min(len(self.flat) - self.VISIBLE, self.first + step))
        self.fill()

    def update(self, kind, accent, opts):
        self.current = (kind, accent)
        self.opts = dict(opts)
        self.fill()

    def more(self, button):
        pop = Gtk.Popover.new(button)
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.set_size_request(7 * (self.W + 12) + 20, 420)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_border_width(6)
        for section, items in self.ts.all_styles():
            lab = Gtk.Label(xalign=0)
            lab.set_markup("<b>%s</b>" % section)
            box.pack_start(lab, False, False, 0)
            grid = Gtk.FlowBox()
            grid.set_max_children_per_line(7)
            grid.set_min_children_per_line(7)
            grid.set_selection_mode(Gtk.SelectionMode.NONE)
            for name, kind, accent in items:
                t = self._tile(name, kind, accent)
                t.connect("clicked", lambda *_: pop.popdown())
                grid.add(t)
            box.pack_start(grid, False, False, 0)
        sw.add(box)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.pack_start(sw, True, True, 0)
        outer.pack_start(Gtk.Separator(), False, False, 2)
        clear = Gtk.Button(label="Clear")
        clear.set_relief(Gtk.ReliefStyle.NONE)
        clear.get_child().set_xalign(0)
        clear.connect("clicked", lambda *_: (pop.popdown(),
                                             self.win.run(("table-style2", ("plain4", 0)))))
        outer.pack_start(clear, False, False, 0)
        outer.show_all()
        pop.add(outer)
        pop.popup()

    keytip = "S"

    def press(self):
        self.more(self)


class ShapeStyleGallery(Gtk.Box):
    """Shape Format > Shape Styles: one row in the ribbon, the full set
    (theme colours x effects) in the drop-down."""
    W, H = 30, 26

    def __init__(self, win):
        Gtk.Box.__init__(self, spacing=2)
        from . import drawing
        self.win = win
        self.get_style_context().add_class("folio-gallery")
        self.get_style_context().add_class("folio-styleset")
        for a in drawing.ACCENTS:
            self.pack_start(self._thumb(3, a), False, False, 0)
        more = Gtk.MenuButton()
        more.set_relief(Gtk.ReliefStyle.NONE)
        more.add(Gtk.Image.new_from_icon_name("pan-down-symbolic", Gtk.IconSize.MENU))
        more.set_tooltip_text("More")
        pop = Gtk.Popover()
        g = Gtk.Grid(row_spacing=3, column_spacing=3, margin=8)
        hdr = Gtk.Label(xalign=0)
        hdr.set_markup("<b>Theme Styles</b>")
        g.attach(hdr, 0, 0, len(drawing.ACCENTS), 1)
        for row, name in enumerate(drawing.STYLE_VARIANTS):
            for col, a in enumerate(drawing.ACCENTS):
                b = self._thumb(row, a, pop)
                g.attach(b, col, row + 1, 1, 1)
        g.show_all()
        pop.add(g)
        more.set_popover(pop)
        self.pack_start(more, False, False, 0)
        self.more = more

    def _thumb(self, variant, accent, pop=None):
        from . import drawing
        b = Gtk.Button()
        b.get_style_context().add_class("folio-style")
        b.set_focus_on_click(False)
        area = Gtk.DrawingArea()
        area.set_size_request(self.W, self.H)
        area.connect("draw", self._draw, variant, accent)
        b.add(area)
        names = ["Black", "Blue, Accent 1", "Orange, Accent 2", "Gray, Accent 3",
                 "Gold, Accent 4", "Blue, Accent 5", "Green, Accent 6"]
        b.set_tooltip_text("%s - %s" % (drawing.STYLE_VARIANTS[variant],
                                        names[drawing.ACCENTS.index(accent)]))

        def go(_b):
            if pop is not None:
                pop.popdown()
            self.win.object_call("set_shape_style", variant, accent)
            self.win.focus_document()
        b.connect("clicked", go)
        return b

    def _draw(self, area, cr, variant, accent):
        from . import drawing
        fill, line, text, shadow = drawing.style_spec(variant, accent)
        W, H = area.get_allocated_width(), area.get_allocated_height()

        def rgb(c):
            cr.set_source_rgb(((c >> 16) & 255) / 255.0, ((c >> 8) & 255) / 255.0,
                              (c & 255) / 255.0)
        x, y, w, h = 3, 3, W - 7, H - 7
        if shadow:
            cr.set_source_rgba(0, 0, 0, 0.3)
            cr.rectangle(x + 2, y + 2, w, h)
            cr.fill()
        rgb(fill)
        cr.rectangle(x, y, w, h)
        cr.fill_preserve()
        rgb(line)
        cr.set_line_width(1.2)
        cr.stroke()
        rgb(text)
        cr.select_font_face("Sans")
        cr.set_font_size(11)
        ext = cr.text_extents("Abc")
        cr.move_to(x + (w - ext.width) / 2 - ext.x_bearing, y + (h - ext.height) / 2 - ext.y_bearing)
        cr.show_text("Abc")
        return False

    keytip = "K"


class SymbolGallery(Gtk.Box):
    """Equation > Symbols: a three-row grid of symbols in the ribbon with
    scroll arrows, and a More drop-down that shows a whole category, with a
    drop-down to switch category (as in the original)."""
    ROWS, COLS, CELL = 3, 10, 22

    def __init__(self, win):
        Gtk.Box.__init__(self, spacing=0)
        from .eqn import galleries as EG
        self.win = win
        self.sets = EG.SYMBOL_SETS
        self.cat = 0
        self.offset = 0
        self.get_style_context().add_class("folio-gallery")
        self.get_style_context().add_class("folio-symgallery")
        self.grid = Gtk.Grid()
        self.pack_start(self.grid, False, False, 0)
        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        side.get_style_context().add_class("folio-gallery-side")
        self.up = self._arrow("pan-up-symbolic", "Row Up", lambda *_: self.scroll(-1))
        self.down = self._arrow("pan-down-symbolic", "Row Down", lambda *_: self.scroll(1))
        more = Gtk.MenuButton()
        more.set_relief(Gtk.ReliefStyle.NONE)
        more.set_focus_on_click(False)
        more.add(Gtk.Image.new_from_icon_name("view-more-symbolic", Gtk.IconSize.MENU))
        more.set_tooltip_text("More")
        more.get_style_context().add_class("folio-gallery-arrow")
        self.pop = Gtk.Popover()
        self.pop.connect("show", lambda *_: self._fill_more())
        more.set_popover(self.pop)
        self.more = more
        for w in (self.up, self.down, more):
            side.pack_start(w, True, True, 0)
        self.pack_start(side, False, False, 0)
        self.refresh()

    def _arrow(self, icon, tip, cb):
        b = Gtk.Button()
        b.set_relief(Gtk.ReliefStyle.NONE)
        b.set_focus_on_click(False)
        b.add(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU))
        b.set_tooltip_text(tip)
        b.get_style_context().add_class("folio-gallery-arrow")
        b.connect("clicked", cb)
        return b

    def _cell(self, ch, pop=None):
        b = Gtk.Button(label=ch)
        b.set_focus_on_click(False)
        b.get_style_context().add_class("folio-symcell")
        try:
            import unicodedata
            b.set_tooltip_text(unicodedata.name(ch).title())
        except (ValueError, TypeError):
            pass

        def go(_b):
            if pop is not None:
                pop.popdown()
            self.win.eqbar.insert(ch)
        b.connect("clicked", go)
        return b

    def chars(self):
        return self.sets[self.cat][1]

    def scroll(self, d):
        rows = (len(self.chars()) + self.COLS - 1) // self.COLS
        self.offset = max(0, min(rows - self.ROWS, self.offset + d))
        self.refresh()

    def refresh(self):
        for c in self.grid.get_children():
            self.grid.remove(c)
        ch = self.chars()
        start = self.offset * self.COLS
        for i, c in enumerate(ch[start:start + self.ROWS * self.COLS]):
            self.grid.attach(self._cell(c), i % self.COLS, i // self.COLS, 1, 1)
        self.grid.show_all()
        rows = (len(ch) + self.COLS - 1) // self.COLS
        self.up.set_sensitive(self.offset > 0)
        self.down.set_sensitive(self.offset < rows - self.ROWS)

    def _fill_more(self):
        for c in self.pop.get_children():
            self.pop.remove(c)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        head = Gtk.Box()
        head.get_style_context().add_class("folio-gallery-head")
        cat = Gtk.ComboBoxText()
        for name, _c in self.sets:
            cat.append_text(name)
        cat.set_active(self.cat)
        cat.get_style_context().add_class("folio-symcat")
        head.pack_start(cat, False, False, 0)
        box.pack_start(head, False, False, 0)
        flow = Gtk.FlowBox()
        flow.set_max_children_per_line(self.COLS + 2)
        flow.set_min_children_per_line(self.COLS + 2)
        flow.set_selection_mode(Gtk.SelectionMode.NONE)
        flow.set_column_spacing(0)
        flow.set_row_spacing(0)
        flow.set_border_width(4)
        box.pack_start(flow, False, False, 0)

        def fill():
            for c in flow.get_children():
                flow.remove(c)
            for c in self.chars():
                flow.add(self._cell(c, self.pop))
            flow.show_all()

        def changed(c):
            self.cat = c.get_active()
            self.offset = 0
            self.refresh()
            fill()
        cat.connect("changed", changed)
        fill()
        box.show_all()
        self.pop.add(box)

    keytip = "S"


class ChartStyleGallery(Gtk.Box):
    """Chart Design > Chart Styles thumbnails."""
    W, H = 52, 40

    def __init__(self, win, call):
        Gtk.Box.__init__(self, spacing=2)
        from . import charts
        self.get_style_context().add_class("folio-gallery")
        self.get_style_context().add_class("folio-styleset")
        for i, name in enumerate(charts.CHART_STYLES):
            b = Gtk.Button()
            b.get_style_context().add_class("folio-style")
            b.set_focus_on_click(False)
            a = Gtk.DrawingArea()
            a.set_size_request(self.W, self.H)
            a.connect("draw", self._draw, i)
            b.add(a)
            b.set_tooltip_text(name)
            b.connect("clicked", lambda _b, i=i: call("set_chart_style", i))
            self.pack_start(b, False, False, 0)

    def _draw(self, area, cr, i):
        W, H = area.get_allocated_width(), area.get_allocated_height()
        dark = i in (5, 7)
        bg = (0.25, 0.25, 0.25) if dark else ((0.95, 0.95, 0.95) if i == 6 else (1, 1, 1))
        cr.set_source_rgb(*bg)
        cr.paint()
        if i not in (2, 4):
            cr.set_source_rgb(*((0.4, 0.4, 0.4) if dark else (0.85, 0.85, 0.85)))
            for k in range(1, 4):
                cr.rectangle(4, 6 + k * 8, W - 8, 0.6)
            cr.fill()
        cols = [(0.27, 0.45, 0.77), (0.93, 0.49, 0.19), (0.65, 0.65, 0.65)]
        vals = [[0.6, 0.4, 0.3], [0.4, 0.7, 0.3], [0.5, 0.3, 0.45], [0.7, 0.45, 0.8]]
        gw = (W - 8) / 4.0
        wide = i in (2, 7)
        for g, row in enumerate(vals):
            bw = gw * (0.85 if wide else 0.7) / 3
            for s, v in enumerate(row):
                x = 4 + g * gw + gw * (0.075 if wide else 0.15) + s * bw
                hh = v * (H - 14)
                cr.set_source_rgba(*(cols[s] + ((0.6,) if i == 4 else (1,))))
                cr.rectangle(x, H - 4 - hh, bw - (0.8 if i == 3 else 0), hh)
                cr.fill()
        cr.set_source_rgb(*((0.6, 0.6, 0.6) if not dark else (0.5, 0.5, 0.5)))
        cr.rectangle(4, H - 4, W - 8, 0.8)
        cr.fill()
        return False

    keytip = "S"


class PictureStyleGallery(Gtk.Box):
    """Picture Format > Picture Styles: frames and shadows, drawn as
    thumbnails."""
    W, H = 58, 46

    def __init__(self, win):
        Gtk.Box.__init__(self, spacing=2)
        from . import drawing
        self.win = win
        self.get_style_context().add_class("folio-gallery")
        self.get_style_context().add_class("folio-styleset")
        for name, w, c, shadow in drawing.PICTURE_STYLES[1:]:
            b = Gtk.Button()
            b.get_style_context().add_class("folio-style")
            b.set_focus_on_click(False)
            area = Gtk.DrawingArea()
            area.set_size_request(self.W, self.H)
            area.connect("draw", self._draw, w, c, shadow)
            b.add(area)
            b.set_tooltip_text(name)
            b.connect("clicked", lambda _b, n=name: (win.live_preview.commit(),
                                                    win.object_call("set_picture_style", n),
                                                    win.focus_document()))
            from . import livepreview

            def prev(m, n=name):
                from . import drawing as _d
                obj = _d.selected_shape(m)
                if obj is not None:
                    _d.set_picture_style(obj, n)
            prev.native = lambda w, n=name: w.object_call("set_picture_style", n)
            livepreview.attach(win, b, ("picstyle", name), prev)
            self.pack_start(b, False, False, 0)

    def _draw(self, area, cr, w, c, shadow):
        W, H = area.get_allocated_width(), area.get_allocated_height()
        cr.set_source_rgb(1, 1, 1)
        cr.paint()
        x, y, pw, ph = 8, 7, W - 18, H - 17
        if shadow:
            cr.set_source_rgba(0, 0, 0, 0.35)
            cr.rectangle(x + 3, y + 3, pw, ph)
            cr.fill()
        if w:
            bw = max(1.0, w / 3.0)
            cr.set_source_rgb(((c >> 16) & 255) / 255.0, ((c >> 8) & 255) / 255.0,
                              (c & 255) / 255.0)
            cr.rectangle(x - bw, y - bw, pw + 2 * bw, ph + 2 * bw)
            cr.fill()
            if c == 0xFFFFFF:
                cr.set_source_rgb(0.75, 0.75, 0.75)
                cr.set_line_width(0.5)
                cr.rectangle(x - bw, y - bw, pw + 2 * bw, ph + 2 * bw)
                cr.stroke()
        # a little landscape: sky, hill, sun
        cr.set_source_rgb(0.62, 0.78, 0.93)
        cr.rectangle(x, y, pw, ph)
        cr.fill()
        cr.set_source_rgb(0.35, 0.62, 0.33)
        cr.move_to(x, y + ph)
        cr.curve_to(x + pw * 0.3, y + ph * 0.45, x + pw * 0.6, y + ph * 0.9, x + pw, y + ph * 0.55)
        cr.line_to(x + pw, y + ph)
        cr.close_path()
        cr.fill()
        cr.set_source_rgb(1.0, 0.84, 0.3)
        cr.arc(x + pw * 0.75, y + ph * 0.28, ph * 0.13, 0, 6.3)
        cr.fill()
        return False

    keytip = "K"

    def press(self):
        pass


def build_ribbon(win):
    r = win.ribbon
    A = win.actions
    run = win.run

    def btn(label, icon, action, size="small", state=None, keytip=None, tip=None):
        return RibbonButton(r, label, icon, action, size=size, state=state, keytip=keytip,
                            tooltip=tip)

    def picker_popover(build):
        ref = [None]

        def make():
            pop = Gtk.Popover()
            ref[0] = pop
            content = build(ref)
            content.show_all()
            pop.add(content)
            return pop
        return make

    # ================================================================= HOME
    t = r.building(Tab("Home", "H"))
    paste = SplitButton(r, "Paste", "cmd/lc_paste", "paste", [
        ("#", "Paste Options:"),
        ("Keep Source Formatting", lambda: A.do_paste(), "cmd/sc_paste"),
        ("Keep Text Only", lambda: A.do_paste_text(), "cmd/sc_pasteunformatted"),
        None,
        ("Paste Special...", lambda: run("paste-special"), "cmd/sc_pastespecial"),
        ("Set Default Paste...", lambda: run("options")),
    ], size="large", keytip="V", tooltip="Paste (Ctrl+V)")
    t.add(Group("Clipboard", [
        paste,
        [btn("Cut", "cmd/sc_cut", "cut", keytip="X", tip="Cut (Ctrl+X)"),
         btn("Copy", "cmd/sc_copy", "copy", keytip="C", tip="Copy (Ctrl+C)"),
         _painter(btn("Format Painter", "cmd/sc_formatpaintbrush", ".uno:FormatPaintbrush",
                      keytip="FP",
                      tip="Format Painter (Ctrl+Shift+C / Ctrl+Shift+V)"), win)],
    ], launcher="clipboard-pane", ribbon=r, launcher_keytip="FO"))

    font = FontCombo(win, r, A.font_name)
    win.font_combo = font
    font.preview = lambda t: (None if t in HEADERS or t == "-" else
                              LP.char_prop(CharFontName=FontCombo._name(t)))
    size = ComboControl(r, SIZES, A.font_size, 4, state=".uno:FontHeight", keytip="FS",
                        tooltip="Font Size (Ctrl+Shift+P)",
                        display=lambda v: ("" if v in ("0", "") else
                                           (v[:-2] if v.endswith(".0") else v)))
    size.preview = lambda t: LP.char_prop(CharHeight=float(t)) if t.replace(".", "").isdigit() \
        else None

    underline_menu = [(lab, (lambda s=s: A.underline_style(s))) for lab, s in (
        ("Underline", 1), ("Double Underline", 2), ("Thick Underline", 12),
        ("Dotted Underline", 3), ("Dashed Underline", 5), ("Dot-Dash Underline", 7),
        ("Wave Underline", 10))] + [None, ("More Underlines...", lambda: run("font-dialog"))]
    case_menu = [("Sentence case.", lambda: A.cmd(".uno:ChangeCaseToSentenceCase")),
                 ("lowercase", lambda: A.cmd(".uno:ChangeCaseToLower")),
                 ("UPPERCASE", lambda: A.cmd(".uno:ChangeCaseToUpper")),
                 ("Capitalize Each Word", lambda: A.cmd(".uno:ChangeCaseToTitleCase")),
                 ("tOGGLE cASE", lambda: A.cmd(".uno:ChangeCaseToToggleCase"))]

    def font_color_pick(c):
        if c is None:
            A.cmd(".uno:Color", {"Color": ("long", -1)})
            return
        win.last_font_color = c
        A.font_color(c)

    def highlight_pick(c):
        if c is None:
            A.highlight(-1)
            return
        win.last_highlight = c
        A.highlight(c)

    def highlight_menu(ref):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_margin_start(8)
        box.set_margin_end(8)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        grid = Gtk.Grid(column_spacing=3, row_spacing=3)
        for i, (name, c) in enumerate(HIGHLIGHTS):
            grid.attach(swatch(c, lambda c: (ref[0].popdown(), highlight_pick(c)), name,
                               preview=(win, lambda c: LP.char_prop(CharBackColor=c))),
                        i % 5, i // 5, 1, 1)
        box.pack_start(grid, False, False, 0)
        nb = Gtk.Button(label="No Color")
        nb.set_relief(Gtk.ReliefStyle.NONE)
        nb.connect("clicked", lambda *_: (ref[0].popdown(), highlight_pick(None)))
        box.pack_start(nb, False, False, 0)
        return box

    t.add(Group("Font", [
        [[font, size,
          btn(None, "cmd/sc_grow", "grow-font", size="icon", keytip="FG",
              tip="Increase Font Size (Ctrl+Shift+>)"),
          btn(None, "cmd/sc_shrink", "shrink-font", size="icon", keytip="FK",
              tip="Decrease Font Size (Ctrl+Shift+<)"),
          MenuButton(r, None, "cmd/sc_changecaserotatecase", case_menu, size="small",
                     keytip="7", tooltip="Change Case (Shift+F3)"),
          btn(None, "cmd/sc_setdefault", "clear-all-formatting", size="icon", keytip="E",
              tip="Clear All Formatting")],
         [btn(None, "cmd/sc_bold", ".uno:Bold", size="icon", state=".uno:Bold", keytip="1",
              tip="Bold (Ctrl+B)"),
          btn(None, "cmd/sc_italic", ".uno:Italic", size="icon", state=".uno:Italic",
              keytip="2", tip="Italic (Ctrl+I)"),
          SplitButton(r, None, "cmd/sc_underline", ".uno:Underline", underline_menu,
                      state=".uno:Underline", keytip="3", tooltip="Underline (Ctrl+U)"),
          btn(None, "cmd/sc_strikeout", ".uno:Strikeout", size="icon",
              state=".uno:Strikeout", keytip="4", tip="Strikethrough"),
          btn(None, "cmd/sc_subscript", ".uno:SubScript", size="icon",
              state=".uno:SubScript", keytip="5", tip="Subscript (Ctrl+=)"),
          btn(None, "cmd/sc_superscript", ".uno:SuperScript", size="icon",
              state=".uno:SuperScript", keytip="6", tip="Superscript (Ctrl+Shift+=)"),
          MenuButton(r, None, "cmd/sc_fontworkgalleryfloater",
                     lambda: _effects_popover(win, "effects"), size="small", keytip="FT",
                     tooltip="Text Effects and Typography"),
          SplitButton(r, None, "cmd/sc_charbackcolor", "highlight",
                      picker_popover(highlight_menu), keytip="I",
                      tooltip="Text Highlight Color"),
          SplitButton(r, None, "cmd/sc_color", "font-color",
                      picker_popover(lambda ref: color_palette(
                          font_color_pick, none_label="Automatic",
                          more=lambda: win.dialogs.pick_color(font_color_pick),
                          popover_ref=ref, preview=(win, lambda c: LP.char_prop(CharColor=c)))),
                      keytip="FC", tooltip="Font Color")]],
    ], launcher="font-dialog", ribbon=r, launcher_keytip="FN"))

    list_menu = [("#", "Bullet Library"),
                 ("•  Filled bullet", lambda: A.do_bullets()),
                 ("◦  Open bullet", lambda: (A.cmd(".uno:BulletListStyle"))),
                 ("▪  Square bullet", lambda: A.cmd(".uno:DefaultBullet")),
                 None, ("None", lambda: A.cmd(".uno:RemoveBullets"))]
    num_menu = [("#", "Numbering Library"),
                ("1.  2.  3.", lambda: A.do_numbering()),
                ("1)  2)  3)", lambda: A.cmd(".uno:NumberListStyle")),
                ("A.  B.  C.", lambda: A.cmd(".uno:AlphaListStyle")),
                ("a)  b)  c)", lambda: A.cmd(".uno:AlphaLowListStyle")),
                ("I.  II.  III.", lambda: A.cmd(".uno:RomanListStyle")),
                ("i.  ii.  iii.", lambda: A.cmd(".uno:RomanLowListStyle")),
                None, ("None", lambda: A.cmd(".uno:RemoveBullets")),
                ("Set Numbering Value...", lambda: lists.set_numbering_value(win))]
    spacing_menu = [(lab, (lambda f=f: A.line_spacing(f))) for lab, f in (
        ("1.0", 1.0), ("1.15", 1.15), ("1.5", 1.5), ("2.0", 2.0), ("2.5", 2.5), ("3.0", 3.0))] + [
        None, ("Line Spacing Options...", lambda: run("paragraph-dialog")),
        ("Add Space Before Paragraph", lambda: A.set_spacing(before=423)),
        ("Remove Space After Paragraph", lambda: A.set_spacing(after=0))]
    t.add(Group("Paragraph", [
        [[SplitButton(r, None, "cmd/sc_defaultbullet", "bullets", list_menu,
                      state=".uno:DefaultBullet", keytip="U", tooltip="Bullets"),
          SplitButton(r, None, "cmd/sc_defaultnumbering", "numbering", num_menu,
                      state=".uno:DefaultNumbering", keytip="N", tooltip="Numbering"),
          MenuButton(r, None, "cmd/sc_setoutline", lambda: lists.multilevel_gallery(win),
                     size="small", keytip="M", tooltip="Multilevel List"),
          btn(None, "cmd/sc_decrementindent", "outdent", size="icon", keytip="AO",
              tip="Decrease Indent"),
          btn(None, "cmd/sc_incrementindent", "indent", size="icon", keytip="AI",
              tip="Increase Indent"),
          btn(None, "cmd/sc_sortdialog", "sort-dialog", size="icon", keytip="SO", tip="Sort"),
          btn(None, "cmd/sc_controlcodes", ".uno:ControlCodes", size="icon",
              state=".uno:ControlCodes", keytip="8", tip="Show/Hide ¶ (Ctrl+Shift+8)")],
         [btn(None, "cmd/sc_leftpara", ".uno:LeftPara", size="icon", state=".uno:LeftPara",
              keytip="AL", tip="Align Left (Ctrl+L)"),
          btn(None, "cmd/sc_centerpara", ".uno:CenterPara", size="icon",
              state=".uno:CenterPara", keytip="AC", tip="Center (Ctrl+E)"),
          btn(None, "cmd/sc_rightpara", ".uno:RightPara", size="icon",
              state=".uno:RightPara", keytip="AR", tip="Align Right (Ctrl+R)"),
          btn(None, "cmd/sc_justifypara", ".uno:JustifyPara", size="icon",
              state=".uno:JustifyPara", keytip="AJ", tip="Justify (Ctrl+J)"),
          MenuButton(r, None, "cmd/sc_linespacing", spacing_menu, size="small", keytip="K",
                     tooltip="Line and Paragraph Spacing"),
          SplitButton(r, None, "cmd/sc_backgroundcolor", None,
                      picker_popover(lambda ref: color_palette(
                          lambda c: A.cmd(".uno:BackgroundColor",
                                          {"BackgroundColor": ("long", -1 if c is None else c)}),
                          none_label="No Color", popover_ref=ref)),
                      keytip="H", tooltip="Shading"),
          MenuButton(r, None, "cmd/sc_borderdialog", [
              ("Bottom Border", lambda: BM.apply_win(win, "bottom")),
              ("Top Border", lambda: BM.apply_win(win, "top")),
              ("Left Border", lambda: BM.apply_win(win, "left")),
              ("Right Border", lambda: BM.apply_win(win, "right")),
              None,
              ("No Border", lambda: BM.apply_win(win, "none")),
              ("All Borders", lambda: BM.apply_win(win, "all")),
              ("Outside Borders", lambda: BM.apply_win(win, "outside")),
              ("Inside Borders", lambda: BM.apply_win(win, "inside")),
              None,
              ("Inside Horizontal Border", lambda: BM.apply_win(win, "inside-h")),
              ("Inside Vertical Border", lambda: BM.apply_win(win, "inside-v")),
              ("Diagonal Down Border", lambda: BM.apply_win(win, "diag-down")),
              ("Diagonal Up Border", lambda: BM.apply_win(win, "diag-up")),
              None, ("Horizontal Line", lambda: BM.horizontal_line(win)),
              None, ("Draw Table", lambda: win.table_draw.begin("draw")),
              ("View Gridlines", lambda: A.cmd(".uno:TableBoundaries")),
              ("Borders and Shading...", lambda: run("paragraph-borders"))],
              size="small", keytip="B", tooltip="Borders")]],
    ], launcher="paragraph-dialog", ribbon=r, launcher_keytip="PG"))

    gallery = StyleGallery(win)
    win.style_gallery = gallery
    t.controls.append(gallery)
    t.add(Group("Styles", [gallery], launcher="styles-pane", ribbon=r, launcher_keytip="FY"))
    t.add(Group("Editing", [
        [SplitButton(r, "Find", "cmd/sc_recsearch", "find-pane", [
            ("Find", lambda: run("find-pane"), "cmd/sc_recsearch"),
            ("Advanced Find...", lambda: run("replace"), "cmd/sc_searchdialog"),
            ("Go To...", lambda: run("goto"), "cmd/sc_gotopage")], keytip="FD",
            tooltip="Find (Ctrl+F)"),
         btn("Replace", "cmd/sc_searchdialog", "replace", keytip="R", tip="Replace (Ctrl+H)"),
         MenuButton(r, "Select", "cmd/sc_selectall", [
             ("Select All", lambda: A.cmd(".uno:SelectAll"), "cmd/sc_selectall"),
             ("Select Objects", lambda: A.cmd(".uno:SelectObject"), "cmd/sc_drawselect"),
             ("Select All Text With Similar Formatting", lambda: run("select-similar")),
             ("Selection Pane...", lambda: run("selection-pane"), "cmd/sc_navigator"),
             ], size="small", keytip="SL", tooltip="Select")],
    ]))
    r.add_tab(t)

    # ================================================================= INSERT
    t = r.building(Tab("Insert", "N"))
    t.add(Group("Pages", [
        [MenuButton(r, "Cover Page", "cmd/sc_titlepagedialog", lambda: _cover_menu(win),
                    size="small", keytip="V"),
         btn("Blank Page", "cmd/sc_insertpage", "blank-page", keytip="NP"),
         btn("Page Break", "cmd/sc_insertpagebreak", ".uno:InsertPagebreak", keytip="B",
             tip="Page Break (Ctrl+Enter)")]]))
    t.add(Group("Tables", [
        MenuButton(r, "Table", "cmd/lc_inserttable", lambda: win.dialogs.table_grid_popover(),
                   keytip="T", tooltip="Add a Table")]))
    t.add(Group("Illustrations", [
        btn("Pictures", "cmd/lc_insertgraphic", "insert-picture", size="large", keytip="P"),
        MenuButton(r, "Shapes", "cmd/lc_basicshapes", [
            it if it is None or it[0] == "#" else (it[0], (lambda k=it[1]: run(("draw-shape", k))))
            for it in __import__("folio.drawing", fromlist=["SHAPE_MENU"]).SHAPE_MENU], keytip="SH"),
        btn("Icons", "insert-icons",
            lambda: __import__("folio.insertmore", fromlist=["x"]).icons_dialog(win),
            size="large", keytip="Y1"),
        btn("SmartArt", "cmd/lc_diagramdata" if not icons.exists("cmd/lc_insertdiagram")
            else "cmd/lc_insertdiagram",
            lambda: __import__("folio.insertmore", fromlist=["x"]).smartart_dialog(win),
            size="large", keytip="M"),
        btn("Chart", "cmd/lc_insertobjectchart",
            lambda: __import__("folio.native.charts" if win.native else "folio.charts",
                               fromlist=["x"]).insert_chart_dialog(win),
            size="large", keytip="C"),
        MenuButton(r, "Screenshot", "screenshot", [
                       ("#", "Screenshot"),
                       ("Screen Clipping", lambda: __import__(
                           "folio.insertmore", fromlist=["x"]).screenshot(win, True)),
                       ("Full Screen", lambda: __import__(
                           "folio.insertmore", fromlist=["x"]).screenshot(win, False))],
                   keytip="SC")]))
    t.add(Group("Links", [
        [btn("Link", "cmd/sc_hyperlinkdialog", "hyperlink", keytip="I", tip="Insert Link (Ctrl+K)"),
         btn("Bookmark", "cmd/sc_insertbookmark", "bookmark", keytip="K"),
         btn("Cross-reference", "cmd/sc_insertreferencefield", "cross-reference", keytip="RF")]]))
    t.add(Group("Comments", [
        btn("Comment", "cmd/lc_insertannotation", "comment", size="large", keytip="L",
            tip="New Comment (Ctrl+Alt+M)")]))
    t.add(Group("Header & Footer", [
        [MenuButton(r, "Header", "cmd/sc_insertpageheader", lambda: _hf_menu(win, "header"),
                    size="small", keytip="H"),
         MenuButton(r, "Footer", "cmd/sc_insertpagefooter", lambda: _hf_menu(win, "footer"),
                    size="small", keytip="O"),
         MenuButton(r, "Page Number", "cmd/sc_insertpagenumberfield",
                    lambda: __import__("folio.pagenum", fromlist=["x"]).menu(win),
                    size="small", keytip="NU")]]))
    from . import insertextras as IX
    t.add(Group("Text", [
        MenuButton(r, "Text\nBox", "cmd/lc_text", [("#", "Built-In")] + [
            (lab, (lambda k=k: win.model_call_sync("insertextras.insert_textbox", k)))
            for lab, k in IX.TEXTBOXES] + [
            None, ("Draw Text Box", lambda: run(("draw-shape", "textbox"))),
            ("Save Selection to Text Box Gallery...",
             lambda: __import__("folio.covers", fromlist=["x"]).save_selection(win, "Text Boxes"))],
            keytip="X"),
        MenuButton(r, "Quick\nParts", "cmd/lc_insertfieldctrl", lambda: IX.quick_parts_menu(win), keytip="Q"),
        MenuButton(r, "WordArt", "cmd/lc_fontworkgalleryfloater",
                   lambda: _effects_popover(win, "wordart"), keytip="W"),
        [btn("Date & Time", "cmd/sc_insertdatefield", "date-time", keytip="D"),
         btn("Field", "cmd/sc_insertfieldctrl", "field-dialog", keytip="Q"),
         MenuButton(r, "Drop Cap", "cmd/sc_dropcap", [
             ("None", lambda: win.model_call("drop_cap", "none")),
             ("Dropped", lambda: win.model_call("drop_cap", "dropped")),
             ("In margin", lambda: win.model_call("drop_cap", "margin")),
             None, ("Drop Cap Options...", lambda: run("drop-cap"))], size="small", keytip="RC")],
        [MenuButton(r, "Signature Line", "cmd/sc_signaturelinedialog", [
            ("Signature Line...", lambda: IX.signature_dialog(win))], size="small",
                    keytip="G"),
         MenuButton(r, "Object", "cmd/sc_insertobject", [
            ("Object...", lambda: IX.object_dialog(win)),
            ("Text from File...", lambda: run("text-from-file"))], size="small", keytip="J")]]))
    t.add(Group("Symbols", [
        SplitButton(r, "Equation", "cmd/lc_insertobjectstarmath", "equation",
                    lambda: win.dialogs.equation_gallery_popover(), size="large",
                    keytip="E", tooltip="Equation (Alt+=)"),
        MenuButton(r, "Symbol", "cmd/lc_charmapcontrol", lambda: win.dialogs.symbol_popover(),
                   size="large", keytip="U")]))
    r.add_tab(t)

    # ================================================================= DRAW
    t = r.building(Tab("Draw", "JI"))
    win.draw_buttons = {}
    sel = btn("Select", "cmd/lc_selectobject", lambda: win.ink.stop(), size="large",
              keytip="S")
    win.draw_buttons["select"] = sel
    era = btn("Eraser", "eraser", lambda: win.ink.begin(
        "eraser"), size="large", keytip="E")
    win.draw_buttons["eraser"] = era
    t.add(Group("Drawing Tools", [sel, era]))
    ink_colors = [("Black", 0x000000), ("Red", 0xC00000), ("Blue", 0x0070C0),
                  ("Green", 0x00B050), ("Yellow", 0xFFFF00), ("Orange", 0xFFC000),
                  ("Purple", 0x7030A0), ("Pink", 0xFF66CC), ("Gray", 0x7F7F7F)]
    widths = [("0.25 mm", 25), ("0.5 mm", 50), ("1 mm", 100), ("2 mm", 200),
              ("3.5 mm", 350), ("5 mm", 500), ("8 mm", 800)]

    def pen_menu(tool):
        return ([("#", "Colors")] +
                [(n, (lambda c=c: win.ink.set_pen(tool, color=c))) for n, c in ink_colors] +
                [None, ("#", "Thickness")] +
                [(n, (lambda w=w: win.ink.set_pen(tool, width=w))) for n, w in widths])
    pens = []
    for tool, label, icon, kt in (("pen", "Pen", "pen-black", "P1"),
                                  ("pen2", "Pen", "pen-red", "P2"),
                                  ("highlighter", "Highlighter", "highlighter", "P3")):
        b = SplitButton(r, label, icon, (lambda tl=tool: win.ink.begin(tl)), pen_menu(tool),
                        size="large", keytip=kt, tooltip=label)
        win.draw_buttons[tool] = b
        pens.append(b)
    t.add(Group("Pens", pens))
    t.add(Group("Convert", [
        btn("Ink to\nMath", "cmd/lc_insertobjectstarmath", lambda: __import__("folio.inkmath", fromlist=["x"]).dialog(win), size="large",
            keytip="IM")]))
    r.add_tab(t)

    # ================================================================= DESIGN
    t = r.building(Tab("Design", "G"))
    t.add(Group("Themes", [
        MenuButton(r, "Themes", "cmd/lc_designerdialog", [
            ("#", "Built-In")] + [(name, (lambda n=name: run(("doc-theme", n))))
                                  for name in docapi.THEMES] + [
            None, ("Reset to Theme from Template", lambda: run(("doc-theme", "Default")))],
            keytip="TH")]))
    sets = StyleSetGallery(win)
    win.styleset_gallery = sets
    t.controls.append(sets)
    t.add(Group("Document Formatting", [
        sets,
        MenuButton(r, "Colors", "cmd/lc_fontcolor", [
            (name, (lambda n=name: run(("doc-colors", n)))) for name in docapi.COLOR_SETS],
            keytip="TC"),
        MenuButton(r, "Fonts", "cmd/lc_fontdialog", [
            ("%s  (%s / %s)" % (name, h, b), (lambda n=name: run(("doc-fonts", n))))
            for name, (h, b) in docapi.FONT_PAIRS.items()], keytip="TF"),
        MenuButton(r, "Paragraph Spacing", "cmd/lc_paraspaceincrease", [
            ("#", "Built-In"),
            ("Default", lambda: run("doc-spacing-default")),
            ("No Paragraph Space", lambda: run("doc-spacing-none")),
            ("Compact", lambda: run("doc-spacing-compact")),
            ("Tight", lambda: run("doc-spacing-tight")),
            ("Open", lambda: run("doc-spacing-open")),
            ("Relaxed", lambda: run("doc-spacing-relaxed")),
            ("Double", lambda: run("doc-spacing-double")),
            None, ("Custom Paragraph Spacing...", lambda: run("paragraph-dialog"))], keytip="PS"),
        btn("Set as Default", "cmd/lc_stylenewbyexample", "set-as-default", size="large",
            keytip="SD")]))
    t.add(Group("Page Background", [
        MenuButton(r, "Watermark", "cmd/lc_watermark", [
            ("CONFIDENTIAL", lambda: run(("watermark", "CONFIDENTIAL"))),
            ("DO NOT COPY", lambda: run(("watermark", "DO NOT COPY"))),
            ("DRAFT", lambda: run(("watermark", "DRAFT"))),
            ("SAMPLE", lambda: run(("watermark", "SAMPLE"))),
            ("URGENT", lambda: run(("watermark", "URGENT"))),
            None, ("Custom Watermark...", lambda: run("watermark-dialog")),
            ("Remove Watermark", lambda: run(("watermark", "")))], keytip="PW"),
        MenuButton(r, "Page Color", "cmd/lc_backgroundcolor",
                   picker_popover(lambda ref: color_palette(
                       lambda c: run(("page-color", c)), none_label="No Color",
                       more=lambda: win.dialogs.pick_color(lambda c: run(("page-color", c))),
                       popover_ref=ref, extra=[("Fill Effects...",
                                               lambda: __import__("folio.filleffects",
                                                                  fromlist=["x"]).dialog(win))])),
                   keytip="PC"),
        btn("Page Borders", "cmd/lc_borderdialog", "page-borders", size="large", keytip="PB")]))
    r.add_tab(t)

    # ================================================================= LAYOUT
    t = r.building(Tab("Layout", "P"))
    margins = [(lab, (lambda m=m: run(("margins", m)))) for lab, m in (
        ("Normal  (Top 1\", Bottom 1\", Left 1\", Right 1\")", (2540, 2540, 2540, 2540)),
        ("Narrow  (0.5\" all sides)", (1270, 1270, 1270, 1270)),
        ("Moderate  (Top 1\", Bottom 1\", Left 0.75\", Right 0.75\")", (2540, 2540, 1905, 1905)),
        ("Wide  (Top 1\", Bottom 1\", Left 2\", Right 2\")", (2540, 2540, 5080, 5080)),
        ("Mirrored  (Top 1\", Bottom 1\", Inside 1.25\", Outside 1\")", "mirrored"),
        ("Office 2003 Default  (Top 1\", Bottom 1\", Left 1.25\", Right 1.25\")",
         (2540, 2540, 3175, 3175)))] + [
        None, ("Custom Margins...", lambda: run("page-setup"))]
    sizes = [(lab, (lambda w=w, h=h: run(("paper", (w, h))))) for lab, w, h in (
        ("Letter  8.5\" x 11\"", 21590, 27940), ("Legal  8.5\" x 14\"", 21590, 35560),
        ("A4  8.27\" x 11.69\"", 21000, 29700), ("A5  5.83\" x 8.27\"", 14800, 21000),
        ("Executive  7.25\" x 10.5\"", 18415, 26670))] + [None, ("More Paper Sizes...",
                                                              lambda: run("page-setup"))]
    t.add(Group("Page Setup", [
        MenuButton(r, "Margins", "cmd/lc_pagemargin", margins, keytip="M"),
        MenuButton(r, "Orientation", "cmd/lc_orientation", [
            ("Portrait", lambda: run(("orientation", False))),
            ("Landscape", lambda: run(("orientation", True)))], keytip="O"),
        MenuButton(r, "Size", "cmd/lc_attributepagesize", sizes, keytip="SZ"),
        MenuButton(r, "Columns", "cmd/lc_pagecolumntype", [
            ("One", lambda: run(("columns", 1))), ("Two", lambda: run(("columns", 2))),
            ("Three", lambda: run(("columns", 3))),
            None, ("More Columns...", lambda: run(("columns", "more")))], keytip="J"),
        [MenuButton(r, "Breaks", "cmd/sc_insertbreak", [
            ("#", "Page Breaks"),
            ("Page", lambda: A.cmd(".uno:InsertPagebreak")),
            ("Column", lambda: A.cmd(".uno:InsertColumnBreak")),
            ("Text Wrapping", lambda: A.cmd(".uno:InsertLinebreak")),
            ("#", "Section Breaks"),
            ("Next Page", lambda: run(("section-break", "next-page"))),
            ("Continuous", lambda: run(("section-break", "continuous"))),
            ("Even Page", lambda: run(("section-break", "even"))),
            ("Odd Page", lambda: run(("section-break", "odd")))], size="small", keytip="B"),
         MenuButton(r, "Line Numbers", "cmd/sc_linenumberingdialog", [
             ("None", lambda: run(("line-numbers", "none"))),
             ("Continuous", lambda: run(("line-numbers", "continuous"))),
             ("Restart Each Page", lambda: run(("line-numbers", "page"))),
             ("Restart Each Section", lambda: run(("line-numbers", "section"))),
             ("Suppress for Current Paragraph", lambda: run(("line-numbers", "suppress"))),
             None, ("Line Numbering Options...", lambda: run("line-numbers"))],
             size="small", keytip="LN"),
         MenuButton(r, "Hyphenation", "cmd/sc_hyphenate", [
             ("None", lambda: run(("hyphenation", False))),
             ("Automatic", lambda: run(("hyphenation", True))),
             ("Manual...", lambda: win.dialogs.manual_hyphenation()),
             None, ("Hyphenation Options...", lambda: win.dialogs.hyphenation_options())],
             size="small", keytip="H")]],
        launcher="page-setup", ribbon=r, launcher_keytip="SP"))
    win.indent_spins = {}

    def spin(kind, keytip):
        from .widgets import LengthSpin, PointSpin
        if kind.startswith("indent"):
            sb = LengthSpin(0, -55880, 55880)
        else:
            sb = PointSpin(0, 0, 1584, 6)
        sb.set_width_chars(5)
        sb.keytip = keytip
        sb.press = lambda: (sb.grab_focus(), sb.select_region(0, -1))
        sb.connect("value-changed", lambda s: run((kind, s.get_value())) if not
                   getattr(s, "_updating", False) else None)
        sb.connect("activate", lambda s: win.focus_document())
        win.indent_spins[kind] = sb
        t.controls.append(sb)
        return sb

    def labeled(text, w):
        b = Gtk.Box(spacing=4)
        b.pack_start(Gtk.Label(label=text, xalign=0, width_chars=7), False, False, 0)
        b.pack_start(w, False, False, 0)
        return b
    t.add(Group("Paragraph", [
        [Gtk.Label(label="Indent", xalign=0), labeled("Left:", spin("indent-left", "IL")),
         labeled("Right:", spin("indent-right", "IR"))],
        [Gtk.Label(label="Spacing", xalign=0), labeled("Before:", spin("space-before", "SB")),
         labeled("After:", spin("space-after", "SA"))]],
        launcher="paragraph-dialog", ribbon=r, launcher_keytip="PG"))
    def align_menu(keytip):
        def go(where):
            win.arrange_call("align", where)
        mode = {"v": "margin"}
        return MenuButton(r, "Align", "cmd/sc_objectalignleft", [
            ("Align Left", lambda: go("left"), "cmd/sc_objectalignleft"),
            ("Align Center", lambda: go("center"), "cmd/sc_alignhorizontalcenter"),
            ("Align Right", lambda: go("right"), "cmd/sc_objectalignright"),
            ("Align Top", lambda: go("top"), "cmd/sc_alignup"),
            ("Align Middle", lambda: go("middle"), "cmd/sc_alignmiddle"),
            ("Align Bottom", lambda: go("bottom"), "cmd/sc_aligndown"),
            None,
            ("Distribute Horizontally", lambda: win.arrange_call("distribute", "h"),
             "cmd/sc_distributehorzcenter"),
            ("Distribute Vertically", lambda: win.arrange_call("distribute", "v"),
             "cmd/sc_distributevertcenter"),
            None,
            ("Align to Page", lambda: win.set_align_mode("page")),
            ("Align to Margin", lambda: win.set_align_mode("margin")),
            ("Align Selected Objects", lambda: win.set_align_mode("objects"))],
            size="small", keytip=keytip)

    def group_menu(keytip):
        return MenuButton(r, "Group", "cmd/sc_formatgroup", [
            ("Group", lambda: A.cmd(".uno:FormatGroup"), "cmd/sc_formatgroup"),
            ("Regroup", lambda: A.cmd(".uno:Regroup" if getattr(win.engine, "native", False) else ".uno:FormatGroup")),
            ("Ungroup", lambda: A.cmd(".uno:FormatUngroup"), "cmd/sc_formatungroup")],
            size="small", keytip=keytip)

    t.add(Group("Arrange", [
        MenuButton(r, "Wrap Text", "cmd/lc_wrapon", [
            ("In Line with Text", lambda: A.cmd(".uno:WrapOff")),
            ("Square", lambda: A.cmd(".uno:WrapOn")),
            ("Tight", lambda: A.cmd(".uno:WrapIdeal")),
            ("Behind Text", lambda: A.cmd(".uno:WrapThrough"))], keytip="TW"),
        [btn("Bring Forward", "cmd/sc_bringtofront", ".uno:BringToFront", keytip="AF"),
         btn("Send Backward", "cmd/sc_sendtoback", ".uno:SendToBack", keytip="AE"),
         btn("Selection Pane", "cmd/sc_navigator", "selection-pane", keytip="AP")],
        [align_menu("AA"), group_menu("GG")]]))
    r.add_tab(t)

    # ================================================================= REFERENCES
    t = r.building(Tab("References", "S"))
    t.add(Group("Table of Contents", [
        MenuButton(r, "Table of\nContents", "cmd/lc_insertmultiindex", [
            ("#", "Built-In"),
            ("Automatic Table 1  (Contents)", lambda: run("insert-toc")),
            ("Automatic Table 2  (Table of Contents)", lambda: run("insert-toc-2")),
            None, ("Custom Table of Contents...", lambda: run("toc-dialog")),
            ("Remove Table of Contents", lambda: run("remove-toc"))], keytip="T"),
        [MenuButton(r, "Add Text", "addtext", [
            ("Do Not Show in Table of Contents", lambda: run(("add-text", 0))),
            ("Level 1", lambda: run(("add-text", 1))), ("Level 2", lambda: run(("add-text", 2))),
            ("Level 3", lambda: run(("add-text", 3)))], size="small", keytip="A"),
         btn("Update Table", "cmd/sc_updatecurindex", "update-toc", keytip="U")]]))
    t.add(Group("Footnotes", [
        btn("Insert\nFootnote", "cmd/lc_insertfootnote", ".uno:InsertFootnote", size="large",
            keytip="F", tip="Insert Footnote (Ctrl+Alt+F)"),
        [btn("Insert Endnote", "cmd/sc_insertendnote", ".uno:InsertEndnote", keytip="E",
             tip="Insert Endnote (Ctrl+Alt+D)"),
         SplitButton(r, "Next Footnote", "cmd/sc_insertfootnote",
                     lambda: run("next-footnote"), [
                         ("Next Footnote", lambda: run("next-footnote")),
                         ("Previous Footnote", lambda: run("prev-footnote")),
                         ("Next Endnote", lambda: run("next-endnote")),
                         ("Previous Endnote", lambda: run("prev-endnote"))], keytip="O"),
         btn("Show Notes", "cmd/sc_footnotedialog", "show-notes", keytip="H")]],
        launcher="footnote-dialog", ribbon=r, launcher_keytip="Q"))
    from . import dlg_cite

    def cite_style(v):
        if getattr(win.engine, "native", False):
            from .native import refs as _refs
            _refs.cites().set_style(win, v)
            return
        m = win.engine.model
        if m is not None:
            win.engine.sync(lambda: __import__("folio.citations", fromlist=["x"]).set_style(
                win.engine.model, v))
    win.cite_style_choice = ChoiceControl(r, __import__("folio.citations", fromlist=["x"]).STYLES,
                                          cite_style,
                                          keytip="L", tooltip="Style")
    t.add(Group("Citations & Bibliography", [
        MenuButton(r, "Insert\nCitation", "insertcitation",
                   lambda: dlg_cite.citation_menu(win), keytip="C"),
        [btn("Manage Sources", "cmd/sc_bibliographycomponent",
             lambda: dlg_cite.manage_sources(win), keytip="M"),
         _labeled_choice("Style:", win.cite_style_choice),
         MenuButton(r, "Bibliography", "bibliography", [
             ("#", "Built-In"),
             ("Bibliography", lambda: win.model_call_sync("citations.insert_bibliography",
                                                          "Bibliography")),
             ("References", lambda: win.model_call_sync("citations.insert_bibliography",
                                                        "References")),
             ("Works Cited", lambda: win.model_call_sync("citations.insert_bibliography",
                                                         "Works Cited")),
             None,
             ("Insert Bibliography", lambda: win.model_call_sync(
                 "citations.insert_bibliography", "")),
             ("Save Selection to Bibliography Gallery...",
              lambda: __import__("folio.covers", fromlist=["x"]).save_selection(win, "Bibliographies"))],
             size="small", keytip="B")]]))
    t.add(Group("Captions", [
        btn("Insert\nCaption", "cmd/lc_insertcaptiondialog", "caption", size="large", keytip="P"),
        [btn("Insert Table of Figures", "tof", "table-of-figures", keytip="G"),
         btn("Update Table", "cmd/sc_updatecurindex", "update-toc", keytip="V"),
         btn("Cross-reference", "cmd/sc_insertreferencefield", "cross-reference", keytip="RF")]]))
    t.add(Group("Index", [
        btn("Mark\nEntry", "cmd/lc_insertindexesentry", "mark-entry", size="large",
            keytip="N", tip="Mark Entry (Alt+Shift+X)"),
        [btn("Insert Index", "cmd/sc_insertindexesentry", "insert-index", keytip="X"),
         btn("Update Index", "cmd/sc_updatecurindex", "update-toc", keytip="D")]]))
    from . import authorities as TOA
    t.add(Group("Table of Authorities", [
        btn("Mark\nCitation", "cmd/lc_insertauthoritiesentry" if icons.exists(
            "cmd/lc_insertauthoritiesentry") else "cmd/lc_insertindexesentry",
            "mark-citation", size="large", keytip="I", tip="Mark Citation (Alt+Shift+I)"),
        [btn("Insert Table of Authorities", "toa",
             lambda: run("insert-toa") if getattr(win.engine, "native", False) else TOA.insert_dialog(win),
             keytip="T"),
         btn("Update Table", "cmd/sc_updatecurindex",
             lambda: run("update-toa") if getattr(win.engine, "native", False) else
             win.engine.sync(lambda: TOA.update_tables(win.engine.model)),
             keytip="U")]]))
    r.add_tab(t)

    # ================================================================= MAILINGS
    from . import dlg_mail as DM
    t = r.building(Tab("Mailings", "M"))
    win.mail_controls = {"need_recipients": []}
    need = win.mail_controls["need_recipients"]

    def needs(w):
        need.append(w)
        return w
    t.add(Group("Create", [
        btn("Envelopes", "cmd/lc_insertenvelope",
            lambda: DM.envelopes(win), size="large", keytip="E"),
        btn("Labels", "cmd/lc_label",
            lambda: DM.labels(win), size="large", keytip="L")]))
    t.add(Group("Start Mail Merge", [
        MenuButton(r, "Start Mail\nMerge", "cmd/lc_mailmergewizard", [
            ("Letters", lambda: DM.start_mail_merge(win, "letters")),
            ("Envelopes...", lambda: DM.start_mail_merge(win, "envelopes")),
            ("Labels...", lambda: DM.start_mail_merge(win, "labels")),
            ("E-mail Messages", lambda: DM.not_available(win, "Merging to e-mail")),
            ("Directory", lambda: DM.start_mail_merge(win, "directory")),
            ("Normal Word Document", lambda: DM.start_mail_merge(win, "normal")),
            None,
            ("Step-by-Step Mail Merge Wizard...", lambda: DM.wizard(win))], keytip="S"),
        MenuButton(r, "Select\nRecipients", "cmd/lc_addressbooksource", [
            ("Type a New List...", lambda: DM.type_new_list(win)),
            ("Use an Existing List...", lambda: DM.use_existing_list(win)),
            ("Choose from Outlook Contacts...", lambda: DM.not_available(win, "Outlook Contacts"))],
            keytip="R"),
        needs(btn("Edit\nRecipient List", "cmd/lc_mailmergeemaildocuments" if False else
                  "cmd/lc_dbviewtables", lambda: DM.edit_recipients(win), size="large",
                  keytip="D"))]))
    hl = btn("Highlight\nMerge Fields", "cmd/lc_viewvaluehighlighting",
             "highlight-merge-fields", size="large", keytip="H")
    win.mail_controls["highlight"] = hl
    from . import mailrules as MR
    t.add(Group("Write & Insert Fields", [
        needs(hl),
        needs(btn("Address\nBlock", "cmd/lc_addressbooksource",
                  lambda: win.model_call_sync("mailings.insert_address_block"), size="large",
                  keytip="A")),
        needs(btn("Greeting\nLine", "cmd/lc_insertfixedtext",
                  lambda: DM.greeting(win), size="large", keytip="G")),
        needs(MenuButton(r, "Insert Merge\nField", "cmd/lc_insertfieldctrl",
                         lambda: DM.field_menu(win), keytip="I")),
        [needs(MenuButton(r, "Rules", "cmd/sc_insertfieldctrl", [
            ("Ask...", lambda: MR.rule_dialog(win, "ask")),
            ("Fill-in...", lambda: MR.rule_dialog(win, "fillin")),
            ("If...Then...Else...", lambda: MR.rule_dialog(win, "if")),
            ("Merge Record #", lambda: MR.rule_dialog(win, "record")),
            ("Merge Sequence #", lambda: MR.rule_dialog(win, "seq")),
            ("Next Record", lambda: MR.rule_dialog(win, "next")),
            ("Next Record If...", lambda: MR.rule_dialog(win, "nextif")),
            ("Set Bookmark...", lambda: MR.rule_dialog(win, "set")),
            ("Skip Record If...", lambda: MR.rule_dialog(win, "skipif"))],
            size="small", keytip="R")),
         needs(btn("Match Fields", "cmd/sc_addressbooksource",
                   lambda: MR.match_fields_dialog(win), keytip="T")),
         needs(btn("Update Labels", "cmd/sc_reload",
                   lambda: win.model_call_sync("mailings.update_labels"), keytip="B"))]]))
    pv = btn("Preview\nResults", "cmd/lc_mailmergepreviewemail" if False else "cmd/lc_printpreview",
             "merge-preview", size="large", keytip="P")
    win.mail_controls["preview"] = pv
    rec = Gtk.Entry()
    rec.set_width_chars(4)
    rec.set_alignment(0.5)
    rec.connect("activate", lambda e: e.get_text().isdigit() and
                win.merge_go(int(e.get_text()) - 1))
    win.mail_controls["record"] = rec
    nav = Gtk.Box(spacing=2)
    for icon, where, tip in (("cmd/sc_firstrecord", "first", "First Record"),
                             ("cmd/sc_prevrecord", "prev", "Previous Record")):
        nav.pack_start(needs(btn(None, icon, lambda w=where: win.merge_go(w), size="icon",
                                 tip=tip)), False, False, 0)
    nav.pack_start(needs(rec), False, False, 0)
    for icon, where, tip in (("cmd/sc_nextrecord", "next", "Next Record"),
                             ("cmd/sc_lastrecord", "last", "Last Record")):
        nav.pack_start(needs(btn(None, icon, lambda w=where: win.merge_go(w), size="icon",
                                 tip=tip)), False, False, 0)
    t.add(Group("Preview Results", [
        needs(pv),
        [nav,
         needs(btn("Find Recipient", "cmd/sc_recsearch", "find-recipient", keytip="FR")),
         needs(btn("Check for Errors", "cmd/sc_spellingandgrammardialog",
                   lambda: MR.auto_check_dialog(win), keytip="K",
                   tip="Auto Check for Errors"))]]))
    t.add(Group("Finish", [
        needs(MenuButton(r, "Finish &\nMerge", "cmd/lc_mailmergecreatedocuments", [
            ("Edit Individual Documents...", lambda: DM.finish(win)),
            ("Print Documents...", lambda: DM.finish(win, print_after=True)),
            ("Send Email Messages...", lambda: DM.not_available(win, "Sending e-mail"))],
            keytip="F"))]))
    r.add_tab(t)

    # ================================================================= REVIEW
    t = r.building(Tab("Review", "R"))
    t.add(Group("Proofing", [
        btn("Spelling &\nGrammar", "cmd/lc_spellingandgrammardialog", "spelling",
            size="large", keytip="S", tip="Spelling & Grammar (F7)"),
        [btn("Thesaurus", "cmd/sc_thesaurusdialog", "thesaurus", keytip="E",
             tip="Thesaurus (Shift+F7)"),
         btn("Word Count", "cmd/sc_wordcountdialog", "word-count", keytip="W",
             tip="Word Count (Ctrl+Shift+G)")]]))
    t.add(Group("Speech", [
        btn("Read\nAloud", "readaloud", "read-aloud", size="large", keytip="R2",
            tip="Read Aloud (Ctrl+Alt+Space)")]))
    t.add(Group("Accessibility", [
        SplitButton(r, "Check\nAccessibility", "accessibility",
                    lambda: run("check-accessibility"), [
                        ("Check Accessibility", lambda: run("check-accessibility")),
                        ("Alt Text", lambda: win.dialogs.alt_text()),
                        ("Navigation Pane", lambda: win.toggle_navigation_pane())],
                    size="large", keytip="A1")]))
    t.add(Group("Language", [
        MenuButton(r, "Language", "cmd/lc_languagemenu", [
            ("Set Proofing Language...", lambda: run("language-dialog"))], keytip="UL")]))
    t.add(Group("Comments", [
        btn("New\nComment", "cmd/lc_insertannotation", "comment", size="large", keytip="C",
            tip="New Comment (Ctrl+Alt+M)"),
        [SplitButton(r, "Delete", "cmd/sc_deleteannotation", ".uno:DeleteComment", [
            ("Delete", lambda: A.cmd(".uno:DeleteComment")),
            ("Delete All Comments Shown", lambda: win.comments.delete_all(shown_only=True)),
            ("Delete All Comments in Document", lambda: win.comments.delete_all())],
            keytip="D"),
         btn("Previous", "cmd/sc_previousannotation", "prev-comment", keytip="V"),
         btn("Next", "cmd/sc_nextannotation", "next-comment", keytip="N")],
        [btn("Show Comments", "cmd/sc_showannotations" if False else "cmd/sc_insertannotation",
             lambda: win.comments.set_visible(not win.comments.show_markup), keytip="P")]]))
    t.add(Group("Tracking", [
        SplitButton(r, "Track\nChanges", "cmd/lc_trackchanges", ".uno:TrackChanges", [
            ("For Everyone", lambda: A.cmd(".uno:TrackChanges")),
            ("Just Mine", lambda: win.status.flash(
                "Just Mine is for documents shared online, which Folio Writer doesn't do; "
                "For Everyone tracks your changes.")),
            ("Lock Tracking", lambda: win.lock_tracking())],
            size="large", state=".uno:TrackChanges", keytip="G",
            tooltip="Track Changes (Ctrl+Shift+E)"),
        [_mk_markup_choice(r, win),
         MenuButton(r, "Show Markup", "cmd/sc_showtrackedchanges", [
             ("Comments", lambda: win.comments.set_visible(not win.comments.show_markup)),
             ("Insertions and Deletions", lambda: A.cmd(".uno:ShowTrackedChanges")),
             ("Formatting", lambda: win.toggle_formatting_markup()),
             ("Specific People...", lambda: _reviewers_dialog(win)),
             None, ("#", "Balloons"),
             ("Show Revisions in Balloons", lambda: win.set_balloons(True)),
             ("Show All Revisions Inline", lambda: win.set_balloons(False)),
             ("Show Only Comments and Formatting in Balloons",
              lambda: win.set_balloons(False))], size="small", keytip="TM"),
         btn("Reviewing Pane", "cmd/sc_acceptrejectchanges" if False else
             "cmd/sc_trackchangesbar", "manage-changes", keytip="TP")]],
        launcher=lambda: __import__("folio.trackoptions", fromlist=["x"]).dialog(win),
        ribbon=r, launcher_keytip="TO"))
    t.add(Group("Changes", [
        SplitButton(r, "Accept", "cmd/lc_accepttrackedchange", ".uno:AcceptTrackedChange", [
            ("Accept This Change", lambda: A.cmd(".uno:AcceptTrackedChange")),
            ("Accept and Move to Next", lambda: A.cmd(".uno:AcceptTrackedChangeToNext")),
            ("Accept All Changes Shown", lambda: win.accept_reject_shown(True)),
            ("Accept All Changes", lambda: A.cmd(".uno:AcceptAllTrackedChanges")),
            ("Accept All Changes and Stop Tracking",
             lambda: (A.cmd(".uno:AcceptAllTrackedChanges"), win.stop_tracking()))],
            size="large", keytip="A2"),
        SplitButton(r, "Reject", "cmd/lc_rejecttrackedchange", ".uno:RejectTrackedChange", [
            ("Reject This Change", lambda: A.cmd(".uno:RejectTrackedChange")),
            ("Reject and Move to Next", lambda: A.cmd(".uno:RejectTrackedChangeToNext")),
            ("Reject All Changes Shown", lambda: win.accept_reject_shown(False)),
            ("Reject All Changes", lambda: A.cmd(".uno:RejectAllTrackedChanges")),
            ("Reject All Changes and Stop Tracking",
             lambda: (A.cmd(".uno:RejectAllTrackedChanges"), win.stop_tracking()))],
            size="large", keytip="J"),
        [btn("Previous", "cmd/sc_previoustrackedchange", ".uno:PreviousTrackedChange", keytip="F"),
         btn("Next", "cmd/sc_nexttrackedchange", ".uno:NextTrackedChange", keytip="H")]]))
    from . import review as RV
    t.add(Group("Compare", [
        MenuButton(r, "Compare", "cmd/lc_comparedocuments", [
            ("Compare...", lambda: RV.compare_dialog(win)),
            ("Combine...", lambda: RV.compare_dialog(win, combine=True)),
            None, ("#", "Show Source Documents"),
            ("Hide Source Documents", lambda: RV.show_sources(win, "hide")),
            ("Show Original", lambda: RV.show_sources(win, "original")),
            ("Show Revised", lambda: RV.show_sources(win, "revised")),
            ("Show Both", lambda: RV.show_sources(win, "both"))], keytip="M")]))
    t.add(Group("Protect", [
        btn("Restrict\nEditing", "cmd/lc_protecttracechangemode" if False else
            "cmd/lc_protect", lambda: win.show_pane(RV.RestrictPane, "right"),
            size="large", keytip="PE")]))
    r.add_tab(t)

    # ================================================================= VIEW
    t = r.building(Tab("View", "W"))
    t.add(Group("Views", [
        btn("Read\nMode", "read-mode", "read-mode", size="large", keytip="F"),
        btn("Print\nLayout", "cmd/lc_printlayout", "print-layout", size="large", keytip="P"),
        btn("Web\nLayout", "cmd/lc_browseview", "web-layout", size="large", keytip="L"),
        [btn("Outline", "cmd/sc_outlinebullet", "outline-view", keytip="U"),
         btn("Draft", "cmd/sc_normalviewmode", "draft-view", keytip="E")]]))
    t.add(Group("Immersive", [
        btn("Focus", "cmd/lc_fullscreen", "focus-mode", size="large", keytip="FM"),
        btn("Immersive\nReader", "immersive", "immersive-reader", size="large", keytip="L2")]))
    t.add(Group("Page Movement", [
        btn("Vertical", "cmd/lc_printlayout",
            lambda: win.close_multipage(), size="large", keytip="VV"),
        btn("Side\nto Side", "cmd/lc_showtwopages",
            "side-to-side", size="large", keytip="VS")]))
    ruler_chk = CheckControl(r, "Ruler", "toggle-ruler",
                             active=win.app.settings.get("ruler", True), keytip="R")
    win.ruler_check = ruler_chk
    nav_chk = CheckControl(r, "Navigation Pane", lambda: win.toggle_navigation_pane(),
                           keytip="K")
    win.nav_check = nav_chk
    t.add(Group("Show", [
        [ruler_chk,
         CheckControl(r, "Formatting Marks", ".uno:ControlCodes", state=".uno:ControlCodes",
                      keytip="8"),
         nav_chk]]))
    t.add(Group("Zoom", [
        btn("Zoom", "cmd/lc_zoom", "zoom-dialog", size="large", keytip="Q"),
        btn("100%", "cmd/lc_zoom100percent", "zoom-100", size="large", keytip="J"),
        [btn("One Page", "cmd/sc_zoompage", "zoom-one-page", keytip="1"),
         btn("Multiple Pages", "cmd/sc_showmultiplepages", "multiple-pages", keytip="M"),
         btn("Page Width", "cmd/sc_zoompagewidth", "zoom-page-width", keytip="I")]]))
    t.add(Group("Window", [
        btn("New\nWindow", "cmd/lc_newwindow", "new-window", size="large", keytip="N"),
        [btn("Arrange All", "cmd/sc_stackwindow", "arrange-all", keytip="A"),
         _set(win, "split_button", btn("Split", "cmd/sc_splitwindow", "split", keytip="SP"))],
        [RibbonButton(r, "View Side by Side", "side-by-side", "side-by-side",
                      state="folio:side-by-side", keytip="B", tooltip="View Side by Side"),
         RibbonButton(r, "Synchronous Scrolling", "sync-scroll", "sync-scrolling",
                      state="folio:sync-scroll", keytip="YS", tooltip="Synchronous Scrolling"),
         btn("Reset Window Position", "reset-window", "reset-window-position", keytip="T")],
        MenuButton(r, "Switch\nWindows", "cmd/lc_splitwindow",
                   lambda: win.switch_windows_menu(), keytip="W")]))
    t.add(Group("Macros", [
        SplitButton(r, "Macros", "cmd/lc_macrodialog" if icons.exists("cmd/lc_macrodialog")
                    else "cmd/lc_runbasic", "view-macros", [
                        ("View Macros", lambda: run("view-macros")),
                        ("Record Macro...", lambda: run("record-macro")),
                        ("Stop Recording", lambda: run("stop-recording")),
                        ("Pause Recording", lambda: run("pause-recording"))],
                    size="large", keytip="M", tooltip="Macros (Alt+F8)")]))
    r.add_tab(t)

    # ================================================================= HELP
    t = r.building(Tab("Help", "Y"))
    t.add(Group("Help", [
        btn("Help", "cmd/lc_helpindex", "help", size="large", keytip="H", tip="Help (F1)"),
        btn("Keyboard\nShortcuts", "cmd/lc_insertsymbol",
            "help", size="large", keytip="K"),
        btn("About", "cmd/lc_helpindex", "about", size="large", keytip="A")]))
    r.add_tab(t)

    # ================================================================= TABLE (contextual)
    t = r.building(Tab("Table Layout", "JL", contextual=True))
    t.add(Group("Table", [
        [MenuButton(r, "Select", "cmd/sc_selecttable", [
            ("Select Cell", lambda: run("select-cell")),
            ("Select Column", lambda: A.cmd(".uno:EntireColumn")),
            ("Select Row", lambda: A.cmd(".uno:EntireRow")),
            ("Select Table", lambda: A.cmd(".uno:SelectTable"))], size="small", keytip="K"),
         btn("View Gridlines", "cmd/sc_inserttable", ".uno:TableBoundaries", keytip="TG"),
         btn("Properties", "cmd/sc_tabledialog", "table-properties", keytip="O")]]))
    win.table_draw_buttons = {}
    dt = btn("Draw\nTable", "pen-black", lambda: win.table_draw.begin("draw"), size="large",
             keytip="DT")
    er = btn("Eraser", "eraser", lambda: win.table_draw.begin("erase"), size="large",
             keytip="E")
    win.table_draw_buttons.update({"draw": dt, "erase": er})
    t.add(Group("Draw", [dt, er]))
    t.add(Group("Rows & Columns", [
        btn("Delete\nTable", "cmd/lc_deletetable", ".uno:DeleteTable", size="large", keytip="D"),
        [btn("Insert Above", "cmd/sc_insertrowsbefore", ".uno:InsertRowsBefore", keytip="A"),
         btn("Insert Below", "cmd/sc_insertrowsafter", ".uno:InsertRowsAfter", keytip="BE"),
         btn("Delete Rows", "cmd/sc_deleterows", ".uno:DeleteRows", keytip="DR")],
        [btn("Insert Left", "cmd/sc_insertcolumnsbefore", ".uno:InsertColumnsBefore", keytip="L"),
         btn("Insert Right", "cmd/sc_insertcolumnsafter", ".uno:InsertColumnsAfter", keytip="R"),
         btn("Delete Columns", "cmd/sc_deletecolumns", ".uno:DeleteColumns", keytip="DC")]],
        launcher="insert-cells", ribbon=r, launcher_keytip="IC"))
    t.add(Group("Merge", [
        [btn("Merge Cells", "cmd/sc_mergecells", ".uno:MergeCells", keytip="M"),
         btn("Split Cells", "cmd/sc_splitcell", "split-cells", keytip="P"),
         btn("Split Table", "cmd/sc_splittable", "split-table", keytip="T")]]))
    from . import tablelayout as TL
    tl = lambda fn, *a: win.model_call_sync("tablelayout." + fn, *a)  # noqa: E731
    win.cell_spins = {}

    def cell_spin(key, keytip, label):
        from .widgets import LengthSpin
        sb = LengthSpin(500, 10, 558800)
        sb.set_width_chars(8)
        sb.keytip = keytip
        sb.press = lambda: (sb.grab_focus(), sb.select_region(0, -1))
        sb.connect("value-changed", lambda w: None if getattr(w, "_updating", False) else
                   tl("set_row_height" if key == "height" else "set_col_width", w.get_value()))
        sb.connect("activate", lambda w: win.focus_document())
        win.cell_spins[key] = sb
        t.controls.append(sb)
        b = Gtk.Box(spacing=4)
        b.pack_start(Gtk.Label(label=label, xalign=0, width_chars=7), False, False, 0)
        b.pack_start(sb, False, False, 0)
        return b

    def autofit(how):
        if how == "contents":
            def go():
                A.cmd(".uno:SelectTable")
                A.cmd(".uno:SetOptimalColumnWidth")
            win.engine.sync(go)
        else:
            tl("autofit", how)
    t.add(Group("Cell Size", [
        MenuButton(r, "AutoFit", "cmd/lc_setoptimalcolumnwidth", [
            ("AutoFit Contents", lambda: autofit("contents")),
            ("AutoFit Window", lambda: autofit("window")),
            ("Fixed Column Width", lambda: autofit("fixed"))], keytip="F"),
        [cell_spin("height", "H", "Height:"), cell_spin("width", "W", "Width:")],
        [btn("Distribute Rows", "cmd/sc_distributerows", ".uno:DistributeRows", keytip="HH"),
         btn("Distribute Columns", "cmd/sc_distributecolumns", ".uno:DistributeColumns",
             keytip="HW")]], launcher="table-properties", ribbon=r, launcher_keytip="TP"))

    def al(h, v, tip, icon, keytip):
        return btn(None, icon, lambda: tl("align_cells", h, v), size="icon", keytip=keytip,
                   tip=tip)
    t.add(Group("Alignment", [
        [[al("left", "top", "Align Top Left", "cellalign-tl", "TL"),
          al("center", "top", "Align Top Center", "cellalign-tc", "TC"),
          al("right", "top", "Align Top Right", "cellalign-tr", "TR")],
         [al("left", "center", "Align Center Left", "cellalign-cl", "CL"),
          al("center", "center", "Align Center", "cellalign-cc", "CC"),
          al("right", "center", "Align Center Right", "cellalign-cr", "CR")],
         [al("left", "bottom", "Align Bottom Left", "cellalign-bl", "BL"),
          al("center", "bottom", "Align Bottom Center", "cellalign-bc", "BC"),
          al("right", "bottom", "Align Bottom Right", "cellalign-br", "BR")]],
        btn("Text\nDirection", "cmd/lc_textdirectiontoptobottom",
            lambda: tl("text_direction"), size="large", keytip="X"),
        btn("Cell\nMargins", "cmd/lc_tabledialog", lambda: TL.cell_margins_dialog(win),
            size="large", keytip="M")]))
    win.repeat_header_btn = btn("Repeat Header Rows", "cmd/sc_tableheadline" if False else
                                "cmd/sc_insertrowsbefore", lambda: tl("repeat_header"),
                                keytip="RH")
    t.add(Group("Data", [
        btn("Sort", "cmd/lc_sortascending", lambda: TL.sort_dialog(win), size="large",
            keytip="SO"),
        [win.repeat_header_btn,
         btn("Convert to Text", "cmd/sc_converttexttable" if False else "cmd/sc_inserttable",
             lambda: TL.convert_dialog(win), keytip="V"),
         btn("Formula", "cmd/sc_insertformula" if False else "cmd/sc_dbviewfunctions",
             lambda: TL.formula_dialog(win), keytip="UL")]]))
    r.add_tab(t)

    # ================================================================= TABLE DESIGN
    t = r.building(Tab("Table Design", "JT", contextual=True))
    win.table_opt_checks = {}

    def topt(label, key, keytip):
        cb = CheckControl(r, label, lambda k=key: win.run(("table-option", k)), keytip=keytip)
        win.table_opt_checks[key] = cb
        return cb
    t.add(Group("Table Style Options", [
        [topt("Header Row", "header", "A"), topt("Total Row", "total", "T"),
         topt("Banded Rows", "banded_rows", "R")],
        [topt("First Column", "first_col", "F"), topt("Last Column", "last_col", "L"),
         topt("Banded Columns", "banded_cols", "C")]]))
    tsg = TableStyleGallery(win)
    win.table_style_gallery = tsg
    t.controls.append(tsg)
    t.add(Group("Table Styles", [tsg]))
    t.add(Group("Borders", [
        MenuButton(r, "Borders", "cmd/lc_setborderstyle", [
            ("Bottom Border", lambda: BM.apply_win(win, "bottom")),
            ("Top Border", lambda: BM.apply_win(win, "top")),
            ("Left Border", lambda: BM.apply_win(win, "left")),
            ("Right Border", lambda: BM.apply_win(win, "right")),
            None,
            ("No Border", lambda: BM.apply_win(win, "none")),
            ("All Borders", lambda: BM.apply_win(win, "all")),
            ("Outside Borders", lambda: BM.apply_win(win, "outside")),
            ("Inside Borders", lambda: BM.apply_win(win, "inside")),
            None,
            ("Inside Horizontal Border", lambda: BM.apply_win(win, "inside-h")),
            ("Inside Vertical Border", lambda: BM.apply_win(win, "inside-v")),
            None, ("View Gridlines", lambda: A.cmd(".uno:TableBoundaries")),
            ("Borders and Shading...", lambda: run("paragraph-borders"))], keytip="B"),
        MenuButton(r, "Shading", "cmd/lc_backgroundcolor", picker_popover(lambda ref: color_palette(
            lambda c: A.cmd(".uno:TableCellBackgroundColor", {"TableCellBackgroundColor": ("long", -1 if c is None else c)}),
            none_label="No Color", popover_ref=ref)), keytip="H")]))
    r.add_tab(t)

    # ================================================================= SHAPE / PICTURE FORMAT
    win.obj_spins = {}

    from . import drawing as drawing_mod

    def oc_pt(fn, *a):
        win.object_call_module("pictools", fn, *a)

    def _effects_items(win, picture, oc, ol):
        """Shape / Picture Effects: the new engine draws every kind."""
        if getattr(win.engine, "native", False):
            from .native import objects as NO
            items = [("#", "Shadow"), ("No Shadow", lambda: oc("set_shadow", None))]
            items += [(n, (lambda n=n: oc("set_shadow", n))) for n in NO.SHADOWS]
            items += [("#", "Reflection"), ("No Reflection", lambda: oc("set_reflection", None))]
            items += [(n, (lambda n=n: oc("set_reflection", n))) for n in NO.REFLECTIONS]
            items += [("#", "Glow")] + [(lab, (lambda pt=pt, c=c: oc("set_glow", pt, c)))
                                        for lab, pt, c in OL.GLOWS]
            items += [("#", "Soft Edges")] + [(lab, (lambda pt=pt: oc("set_soft_edges", pt)))
                                              for lab, pt in OL.SOFT]
            items += [("#", "Bevel"), ("No Bevel", lambda: oc("set_bevel", None))]
            items += [(n, (lambda n=n: oc("set_bevel", n))) for n in NO.BEVELS]
            items += [("#", "3-D Rotation"), ("No Rotation", lambda: oc("set_rotation", None))]
            items += [("#", n) if p is None else (n, (lambda p=p: oc("set_rotation", p)))
                      for n, p in NO.ROTATIONS]
            return items
        return [("#", "Shadow"),
                ("No Shadow", lambda: oc("set_shadow", False)),
                ("Offset: Bottom Right", lambda: oc("set_shadow", True))] + ([] if picture else [
                ("#", "Glow")] + [
                (lab, (lambda pt=pt, c=c: ol("set_glow", pt, c)))
                for lab, pt, c in OL.GLOWS[:9]] + [
                ("#", "Soft Edges")] + [
                (lab, (lambda pt=pt: ol("set_soft_edges", pt))) for lab, pt in OL.SOFT])

    def object_tab(name, keytip, picture):
        oc = win.object_call
        t = r.building(Tab(name, keytip, contextual=True))
        if not picture:
            t.add(Group("Insert Shapes", [
                MenuButton(r, "Shapes", "cmd/lc_basicshapes", [
                    it if it is None or it[0] == "#" else
                    (it[0], (lambda k=it[1]: run(("draw-shape", k))))
                    for it in __import__("folio.drawing", fromlist=["x"]).SHAPE_MENU],
                    keytip="SH"),
                [MenuButton(r, "Edit Shape", "cmd/sc_toggleobjectbeziermode", [
                    ("#", "Change Shape")] + [
                    (it[0], (lambda k=it[1]: oc("change_shape", k)))
                    for it in __import__("folio.drawing", fromlist=["x"]).SHAPE_MENU
                    if it and it[0] != "#" and __import__("folio.drawing", fromlist=["x"])
                    .SHAPES.get(it[1], ("",))[0].endswith("CustomShape")] + [
                    None, ("Edit Points", lambda: win.act_edit_points())],
                    size="small", keytip="E"),
                 btn("Draw Text Box", "cmd/sc_text", ("draw-shape", "textbox"),
                     size="small", keytip="X"),
                 MenuButton(r, "Merge Shapes", "cmd/sc_mergeshapes" if icons.exists(
                     "cmd/sc_mergeshapes") else "cmd/sc_merge" if icons.exists("cmd/sc_merge")
                     else "cmd/sc_formatgroup", [
                     ("Union", lambda: win.merge_shapes("union")),
                     ("Combine", lambda: win.merge_shapes("combine")),
                     ("Fragment", lambda: win.merge_shapes("fragment")),
                     ("Intersect", lambda: win.merge_shapes("intersect")),
                     ("Subtract", lambda: win.merge_shapes("subtract"))],
                     size="small", keytip="M")]]))
        else:
            corrections = [("#", "Brightness/Contrast")]
            for b in (-40, -20, 0, 20, 40):
                for c in (-20, 0, 20):
                    corrections.append(("Brightness: %+d%%  Contrast: %+d%%%s" % (
                        b, c, "  (Normal)" if b == 0 and c == 0 else ""),
                        (lambda b=b, c=c: oc("set_adjust", b, c))))
            corrections += [None, ("Picture Corrections Options...",
                                   lambda: win.dialogs.picture_corrections())]
            def artistic_menu():
                from . import pictools
                m = win.engine.model
                obj = drawing_mod.selected_shape(m) if m is not None else None
                pop = Gtk.Popover()
                if obj is None or not pictools._pil():
                    pop.add(Gtk.Label(label="Select a picture first." if obj is None else
                                      "Install python3-pil for artistic effects.",
                                      margin=10))
                    pop.get_child().show()
                    return pop
                thumbs = pictools.effect_thumbnails(obj)
                g = Gtk.FlowBox()
                g.set_max_children_per_line(4)
                g.set_selection_mode(Gtk.SelectionMode.NONE)
                for name in pictools.EFFECTS:
                    b = Gtk.Button()
                    b.add(Gtk.Image.new_from_pixbuf(thumbs[name]))
                    b.set_tooltip_text(name)
                    b.connect("clicked", lambda _b, n=name: (pop.popdown(),
                                                             oc_pt("artistic_effect", n)))
                    g.add(b)
                g.show_all()
                pop.add(g)
                return pop
            t.add(Group("Adjust", [
                btn("Remove\nBackground", "removebg", lambda: win.bg_removal_start(),
                    size="large", keytip="E"),
                MenuButton(r, "Corrections", "cmd/lc_grafluminance", corrections, keytip="R"),
                MenuButton(r, "Color", "cmd/lc_grafmode", [
                    ("#", "Recolor"),
                    ("No Recolor", lambda: oc("set_color_mode", "color")),
                    ("Grayscale", lambda: oc("set_color_mode", "grayscale")),
                    ("Black and White", lambda: oc("set_color_mode", "bw")),
                    ("Washout", lambda: oc("set_color_mode", "washout"))], keytip="I"),
                MenuButton(r, "Transparency", "cmd/lc_graftransparence", [
                    ("%d%%" % v, (lambda v=v: oc("set_transparency", v)))
                    for v in (0, 15, 30, 50, 65, 80, 95)], keytip="T"),
                MenuButton(r, "Artistic\nEffects", "cmd/lc_graphicfilterpopart" if
                           icons.exists("cmd/lc_graphicfilterpopart") else
                           "cmd/lc_graphicfiltertoolbox", artistic_menu, keytip="X"),
                [btn("Compress Pictures", "cmd/sc_compressgraphic" if icons.exists(
                    "cmd/sc_compressgraphic") else "cmd/sc_graphicdialog",
                     lambda: __import__("folio.pictools", fromlist=["x"]).compress_dialog(win),
                     keytip="M"),
                 btn("Change Picture", "cmd/sc_insertgraphic",
                     lambda: win.dialogs.change_picture(), keytip="G"),
                 SplitButton(r, "Reset Picture", "cmd/sc_resetattributes",
                             lambda: oc("reset_picture", False), [
                                 ("Reset Picture", lambda: oc("reset_picture", False)),
                                 ("Reset Picture & Size", lambda: oc("reset_picture", True))],
                             keytip="Q")]]))
        fill_label = "Shape Fill" if not picture else "Picture Fill"
        styles = []
        if picture:
            styles.append(PictureStyleGallery(win))
            t.controls.append(styles[0])
        else:
            styles.append(ShapeStyleGallery(win))
            t.controls.append(styles[0])
        styles.append(
            [MenuButton(r, fill_label if not picture else "Picture Border",
                        "cmd/sc_backgroundcolor" if not picture else "cmd/sc_xlinecolor",
                        picker_popover(
                lambda ref: color_palette(lambda c: oc("set_fill", c), none_label="No Fill",
                                          more=lambda: win.dialogs.pick_color(
                                              lambda c: oc("set_fill", c)), popover_ref=ref))
                        if not picture else picker_popover(
                lambda ref: color_palette(lambda c: oc("set_outline", c, None, c is None),
                                          none_label="No Outline", popover_ref=ref)),
                size="small", keytip="SF" if not picture else "SO")] +
            ([MenuButton(r, "Shape Outline", "cmd/sc_xlinecolor", picker_popover(
                lambda ref: color_palette(lambda c: oc("set_outline", c, None, c is None),
                                          none_label="No Outline", popover_ref=ref)),
                size="small", keytip="SO")] if not picture else []) +
            [MenuButton(r, "Weight", "cmd/sc_linewidth", [
                 ("%s pt" % lab, (lambda v=v: oc("set_outline", None, v)))
                 for lab, v in (("¼", 0.25), ("½", 0.5), ("¾", 0.75), ("1", 1),
                                ("1½", 1.5), ("2¼", 2.25), ("3", 3), ("4½", 4.5),
                                ("6", 6))], size="small", keytip="W"),
             MenuButton(r, "Shape Effects" if not picture else "Picture Effects",
                        "cmd/sc_fillshadow", _effects_items(win, picture, oc, lambda *a: ol(*a)),
                        size="small", keytip="SE" if not picture else "E")])
        t.add(Group("Shape Styles" if not picture else "Picture Styles", styles))
        if not picture:
            from .pictools import TRANSFORMS
            t.add(Group("WordArt Styles", [
                [MenuButton(r, "Text Fill", "cmd/sc_fontcolor", picker_popover(
                    lambda ref: color_palette(lambda c: oc("set_text_color", c),
                                              popover_ref=ref)), size="small", keytip="TI"),
                 MenuButton(r, "Text Outline", "cmd/sc_xlinecolor", picker_popover(
                     lambda ref: color_palette(lambda c: oc("set_text_outline", c),
                                               none_label="No Outline", popover_ref=ref)),
                     size="small", keytip="TO"),
                 MenuButton(r, "Text Effects", "cmd/sc_fontworkgalleryfloater" if
                            icons.exists("cmd/sc_fontworkgalleryfloater") else "cmd/sc_shadowed",
                            [("#", "Transform")] + [
                                it if it[0] == "#" else
                                (it[0], (lambda k=it[1]: win.wordart_transform(k)))
                                for it in TRANSFORMS] + [
                                None, ("No Transform", lambda: win.wordart_transform(
                                    "fontwork-plain-text"))],
                            size="small", keytip="TX")]]))
        if not picture:
            from . import textlinks as TL

            def tl(fname, *a):
                win.object_call_module("textlinks", fname, *a)
            t.add(Group("Text", [
                [MenuButton(r, "Text Direction", "cmd/sc_textdirectiontoptobottom", [
                    (lab, (lambda v=v: tl("set_direction", v))) for lab, v in TL.DIRECTIONS],
                    size="small", keytip="TD"),
                 MenuButton(r, "Align Text", "cmd/sc_cellvertcenter", [
                     (lab, (lambda v=v: tl("set_align", v))) for lab, v in TL.ALIGN],
                     size="small", keytip="AT"),
                 btn("Create Link", "cmd/sc_chainframes",
                     lambda: win.text_linker.create(), size="small", keytip="CL"),
                 btn("Break Link", "cmd/sc_unhainframes",
                     lambda: win.text_linker.break_link(), size="small", keytip="BL")]]))
        if picture:
            t.add(Group("Accessibility", [
                btn("Alt\nText", "cmd/lc_objecttitledescription",
                    lambda: win.dialogs.alt_text(), size="large", keytip="AT")]))
        def ol(fname, *a):
            win.object_call_module("objlayout", fname, *a)
            win.object_call_refresh()
        positions = [("#", "In Line with Text"),
                     ("In Line with Text", lambda: oc("set_wrap", "inline")),
                     ("#", "With Text Wrapping")]
        for v in ("top", "middle", "bottom"):
            for h in ("left", "center", "right"):
                positions.append(("Position in %s %s" % (
                    {"top": "Top", "middle": "Middle", "bottom": "Bottom"}[v],
                    {"left": "Left", "center": "Center", "right": "Right"}[h]),
                    (lambda v=v, h=h: (oc("set_wrap", "square"), oc("align", h),
                                       oc("align", v)))))
        positions += [None, ("More Layout Options...", lambda: OL.layout_dialog(win, 0))]
        t.add(Group("Arrange", [
            MenuButton(r, "Position", "cmd/lc_toggleanchortype", positions, keytip="PO"),
            MenuButton(r, "Wrap\nText", "cmd/lc_wrapon", [
                ("In Line with Text", lambda: oc("set_wrap", "inline")),
                ("Square", lambda: oc("set_wrap", "square")),
                ("Tight", lambda: oc("set_wrap", "tight")),
                ("Through", lambda: oc("set_wrap", "through")),
                ("Top and Bottom", lambda: oc("set_wrap", "topbottom")),
                ("Behind Text", lambda: oc("set_wrap", "behind")),
                ("In Front of Text", lambda: oc("set_wrap", "front")), None,
                ("Edit Wrap Points", lambda: OL.edit_wrap_points(win)), None,
                ("Move with Text", lambda: oc("set_anchor_mode", "paragraph")),
                ("Fix Position on Page", lambda: oc("set_anchor_mode", "page")), None,
                ("More Layout Options...", lambda: OL.layout_dialog(win, 1))], keytip="TW"),
            [btn("Bring Forward", "cmd/sc_bringtofront", lambda: oc("z_order", 1), keytip="AF"),
             btn("Send Backward", "cmd/sc_sendtoback", lambda: oc("z_order", -1), keytip="AE"),
             btn("Delete", "cmd/sc_delete", lambda: win.object_delete(), keytip="D")],
            [btn("Selection Pane", "cmd/sc_navigator", "selection-pane", keytip="AP"),
             align_menu("AA"), group_menu("GP"),
             MenuButton(r, "Rotate", "cmd/sc_toggleobjectrotatemode", [
                 ("Rotate Right 90°", lambda: oc("rotate", "right")),
                 ("Rotate Left 90°", lambda: oc("rotate", "left")),
                 ("Flip Vertical", lambda: oc("rotate", "flipv")),
                 ("Flip Horizontal", lambda: oc("rotate", "fliph"))], size="small",
                 keytip="AY")]]))

        def size_spin(key, keytip):
            from .widgets import LengthSpin
            sb = LengthSpin(2540, 10, 558800)
            sb.set_width_chars(8)
            sb.keytip = keytip
            sb.press = lambda: (sb.grab_focus(), sb.select_region(0, -1))
            sb.connect("value-changed", lambda w: None if getattr(w, "_updating", False) else
                       oc("set_size_locked", *((w.get_value(), None) if key == "width"
                                               else (None, w.get_value())),
                          win.lock_aspect()))
            sb.connect("activate", lambda w: win.focus_document())
            win.obj_spins.setdefault(key, []).append(sb)
            t.controls.append(sb)
            box = Gtk.Box(spacing=4)
            box.pack_start(Gtk.Label(label="Height:" if key == "height" else "Width:",
                                     xalign=0, width_chars=7), False, False, 0)
            box.pack_start(sb, False, False, 0)
            return box
        size_items = []
        if picture:
            size_items.append(SplitButton(r, "Crop", "cmd/lc_crop", lambda: win.crop_mode.begin(), [
                ("Crop", lambda: win.crop_mode.begin()),
                ("Crop...", lambda: win.dialogs.crop()),
                ("#", "Crop to Aspect Ratio"),
                ("Square  1:1", lambda: oc("crop_to_ratio", 1, 1)),
                ("Landscape  4:3", lambda: oc("crop_to_ratio", 4, 3)),
                ("Landscape  3:2", lambda: oc("crop_to_ratio", 3, 2)),
                ("Landscape  16:9", lambda: oc("crop_to_ratio", 16, 9)),
                ("Portrait  3:4", lambda: oc("crop_to_ratio", 3, 4)),
                ("Portrait  2:3", lambda: oc("crop_to_ratio", 2, 3)),
                ("#", "Crop to Shape")] + [
                (lab, (lambda k=k: OL.crop_to_shape(win, k))) for lab, k in OL.CROP_SHAPES] + [
                None, ("Fill", lambda: ol("aspect_fill")), ("Fit", lambda: ol("aspect_fit"))],
                size="large", keytip="C"))
        size_items.append([size_spin("height", "H"), size_spin("width", "W")])
        t.add(Group("Size", size_items, launcher="object-size", ribbon=r,
                    launcher_keytip="SZ"))
        r.add_tab(t)
    object_tab("Shape Format", "JD", False)

    def chart_call(fn, *args):
        from . import charts
        m = win.engine.model
        obj = charts.selected_chart(m) if m is not None else None
        if win.native:
            from .native import charts
            obj = charts.selected(win)
        if obj is None:
            return
        if charts.is_image(obj) and fn not in ("edit", "type", "title", "set_title"):
            from . import imagecharts as IC
            opt = {"set_colors": lambda c: {"colors": list(c)},
                   "set_legend": lambda w: {"legend": w},
                   "set_data_labels": lambda w: {"labels": w is not None,
                                                 "values": w is not None and w != "center"},
                   "set_chart_style": lambda i: {"style": i},
                   "quick_layout": lambda i: [{"legend": "top", "labels": True, "values": False},
                                              {"legend": "right", "labels": True,
                                               "values": True},
                                              {"legend": "none", "labels": True,
                                               "values": True},
                                              {"legend": "bottom", "labels": False,
                                               "values": True}][i % 4]}.get(fn)
            if opt is None:
                win.status.flash("That option isn't available for this chart type.")
                return
            IC.set_option(m, obj, **opt(*args))
            win.focus_document()
            return
        if fn == "edit":
            charts.edit_chart(win, obj)
        elif fn == "type":
            idx = charts.type_dialog(win, charts.type_index(obj), "Change Chart Type")
            if idx is not None:
                charts.set_type(obj, idx)
        elif fn == "title":
            t = win.dialogs.ask_text("Chart Title", "Title:", charts.title_of(obj))
            if t is not None:
                charts.set_title(obj, t)
        elif fn == "axis-title":
            x, y = charts.axis_titles(obj)
            which = args[0]
            t = win.dialogs.ask_text("Axis Title", "Title:", x if which == "x" else y)
            if t is not None:
                charts.set_axis_titles(obj, **{which: t or False})
        elif fn == "switch":
            d = charts.get_data(obj)
            charts.set_data(obj, {"rows": list(d["cols"]), "cols": list(d["rows"]),
                                  "values": [[d["values"][r][c] for r in range(len(d["rows"]))]
                                             for c in range(len(d["cols"]))]})
        elif fn == "grid":
            cur = charts.gridlines(obj)
            i = args[0]
            cur[i] = not cur[i]
            charts.set_gridlines(obj, *cur)
        else:
            getattr(charts, fn)(obj, *args)
        charts.refresh(obj)
        win.focus_document()
    from . import charts as _charts
    t = r.building(Tab("Chart Design", "JC", contextual=True))
    t.add(Group("Chart Layouts", [
        MenuButton(r, "Add Chart\nElement", "cmd/lc_insertobjectchart", [
            ("#", "Axes"),
            ("Primary Horizontal", lambda: chart_call("set_axes", True, None)),
            ("Primary Vertical", lambda: chart_call("set_axes", None, True)),
            ("No Axes", lambda: chart_call("set_axes", False, False)),
            ("#", "Axis Titles"),
            ("Primary Horizontal Title...", lambda: chart_call("axis-title", "x")),
            ("Primary Vertical Title...", lambda: chart_call("axis-title", "y")),
            ("No Axis Titles", lambda: chart_call("set_axis_titles", False, False)),
            ("#", "Chart Title"),
            ("Above Chart...", lambda: chart_call("title")),
            ("None", lambda: chart_call("set_title", "")),
            ("#", "Data Labels"),
            ("None", lambda: chart_call("set_data_labels", None)),
            ("Center", lambda: chart_call("set_data_labels", "center")),
            ("Inside End", lambda: chart_call("set_data_labels", "inside-end")),
            ("Inside Base", lambda: chart_call("set_data_labels", "inside-base")),
            ("Outside End", lambda: chart_call("set_data_labels", "outside-end")),
            ("#", "Data Table"),
            ("None", lambda: chart_call("set_data_table", False)),
            ("With Legend Keys", lambda: chart_call("set_data_table", True)),
            ("#", "Gridlines"),
            ("Primary Major Horizontal", lambda: chart_call("grid", 0)),
            ("Primary Major Vertical", lambda: chart_call("grid", 1)),
            ("Primary Minor Horizontal", lambda: chart_call("grid", 2)),
            ("Primary Minor Vertical", lambda: chart_call("grid", 3)),
            ("#", "Legend"),
            ("None", lambda: chart_call("set_legend", "none")),
            ("Right", lambda: chart_call("set_legend", "right")),
            ("Top", lambda: chart_call("set_legend", "top")),
            ("Left", lambda: chart_call("set_legend", "left")),
            ("Bottom", lambda: chart_call("set_legend", "bottom"))], keytip="A"),
        MenuButton(r, "Quick\nLayout", "cmd/lc_diagramtype", [
            (name, (lambda i=i: chart_call("quick_layout", i)))
            for i, (name, *_rest) in enumerate(_charts.QUICK_LAYOUTS)], keytip="L")]))
    sg = ChartStyleGallery(win, chart_call)
    t.controls.append(sg)
    t.add(Group("Chart Styles", [
        MenuButton(r, "Change\nColors", "cmd/lc_diagramarea", [("#", "Colorful")] + [
            (n, (lambda c=c: chart_call("set_colors", c))) for n, c in _charts.COLORFUL] +
            [("#", "Monochromatic")] + [
            (n, (lambda c=c: chart_call("set_colors", c))) for n, c in _charts.MONOCHROMATIC],
            keytip="H"),
        sg]))
    def chart_filters():
        from . import charts
        m = win.engine.model
        obj = charts.selected_chart(m) if m is not None else None
        if win.native:
            from .native import charts as NC
            obj = NC.selected(win)
            if obj is not None and not NC.special(obj):
                return charts.filter_popover_for(win, obj, NC)
        if obj is None or charts.is_image(obj) or charts.special(obj):
            pop = Gtk.Popover()
            lab = Gtk.Label(label="Filters work on column, bar, line, area and pie charts.",
                            margin=10)
            lab.show()
            pop.add(lab)
            return pop
        return charts.filter_popover(win, obj)

    def format_pane():
        from . import charts
        cls = getattr(win, "_chart_pane_cls", None)
        if cls is None:
            cls = charts.ChartFormatPane.make(win)
            win._chart_pane_cls = cls
        win.show_pane(cls)
    t.add(Group("Data", [
        btn("Edit\nData", "cmd/lc_diagramdata", lambda: chart_call("edit"), size="large",
            keytip="D"),
        [btn("Switch Row/\nColumn", "cmd/sc_toggleaxistitle" if False else "cmd/sc_datainrows"
             if icons.exists("cmd/sc_datainrows") else "cmd/sc_diagramdata",
             lambda: chart_call("switch"), keytip="W"),
         MenuButton(r, "Chart Filters", "cmd/sc_datafilterautofilter" if icons.exists(
             "cmd/sc_datafilterautofilter") else "cmd/sc_diagramdata", chart_filters,
             size="small", keytip="F"),
         btn("Format Pane", "cmd/sc_diagramarea", format_pane, keytip="FP")]]))
    t.add(Group("Type", [
        btn("Change\nChart Type", "cmd/lc_diagramtype",
            lambda: chart_call("type"), size="large", keytip="C")]))
    r.add_tab(t)
    object_tab("Picture Format", "JP", True)

    # ================================================================= HEADER & FOOTER
    t = r.building(Tab("Header & Footer", "JH", contextual=True))
    t.add(Group("Header & Footer", [
        btn("Header", "cmd/lc_insertpageheader", "header", size="large", keytip="H"),
        btn("Footer", "cmd/lc_insertpagefooter", "footer", size="large", keytip="O"),
        MenuButton(r, "Page\nNumber", "cmd/lc_insertpagenumberfield",
                   lambda: __import__("folio.pagenum", fromlist=["x"]).menu(win), keytip="NU")]))
    t.add(Group("Insert", [
        btn("Date &\nTime", "cmd/lc_insertdatefield", "date-time", size="large", keytip="D"),
        MenuButton(r, "Document\nInfo", "cmd/lc_insertfieldctrl", [
            ("Author", lambda: win.model_call("insert_field", "author")),
            ("File Name", lambda: win.model_call("insert_field", "filename")),
            ("Document Title", lambda: win.model_call("insert_field", "title")),
            ("Document Property", lambda: run("field-dialog"))], keytip="I"),
        MenuButton(r, "Quick\nParts", "cmd/lc_insertfieldctrl",
                   lambda: __import__("folio.insertextras", fromlist=["x"]).quick_parts_menu(win),
                   keytip="Q"),
        btn("Pictures", "cmd/lc_insertgraphic", "insert-picture", size="large", keytip="P")]))
    t.add(Group("Navigation", [
        [btn("Go to Header", "cmd/sc_insertpageheader", ".uno:JumpToHeader", keytip="GH"),
         btn("Go to Footer", "cmd/sc_insertpagefooter", ".uno:JumpToFooter", keytip="GF")],
        [btn("Previous", "cmd/sc_prevrecord", lambda: __import__(
            "folio.hfedit", fromlist=["x"]).goto_section(win, -1), keytip="R"),
         btn("Next", "cmd/sc_nextrecord", lambda: __import__(
             "folio.hfedit", fromlist=["x"]).goto_section(win, 1), keytip="N"),
         RibbonButton(r, "Link to Previous", "cmd/sc_insertreferencefield", lambda: __import__(
             "folio.hfedit", fromlist=["x"]).set_link(
                 win, not __import__("folio.hfedit", fromlist=["x"]).is_linked(win)),
             state="folio:hf-link", keytip="K", tooltip="Link to Previous")]]))
    win.hf_checks = {}

    def hfopt(label, key, keytip):
        cb = CheckControl(r, label, lambda k=key: win.run(("hf-option", k)), keytip=keytip)
        win.hf_checks[key] = cb
        return cb
    t.add(Group("Options", [
        [hfopt("Different First Page", "first", "A"),
         hfopt("Different Odd & Even Pages", "odd_even", "V"),
         hfopt("Show Document Text", "show_text", "W")]]))
    win.hf_spins = {}

    def hfspin(key, keytip):
        from .widgets import LengthSpin
        sb = LengthSpin(1270, 0, 25400)
        sb.set_width_chars(8)
        sb.keytip = keytip
        sb.press = lambda: (sb.grab_focus(), sb.select_region(0, -1))
        sb.connect("value-changed", lambda w: None if getattr(w, "_updating", False)
                   else run(("hf-position", (key, w.get_value()))))
        sb.connect("activate", lambda w: win.focus_document())
        win.hf_spins[key] = sb
        t.controls.append(sb)
        return sb

    def lab(text, w):
        b = Gtk.Box(spacing=4)
        b.pack_start(Gtk.Label(label=text, xalign=0, width_chars=16), False, False, 0)
        b.pack_start(w, False, False, 0)
        return b
    t.add(Group("Position", [
        [lab("Header from Top:", hfspin("header_top", "P")),
         lab("Footer from Bottom:", hfspin("footer_bottom", "B")),
         btn("Insert Alignment Tab", "cmd/sc_paragraphdialog",
             lambda: __import__("folio.hfedit", fromlist=["x"]).alignment_tab_dialog(win),
             keytip="TA")]]))
    t.add(Group("Close", [
        btn("Close Header\nand Footer", "cmd/lc_closedoc", "close-header-footer", size="large",
            keytip="C")]))
    r.add_tab(t)

    # ================================================================= EQUATION
    from .eqbar import gallery_popover
    from .eqn import galleries as EG
    # ================================================================= OUTLINING (contextual)
    t = r.building(Tab("Outlining", "U", contextual=True))

    def ov(fn, *a):
        v = win.outline()
        if v is not None:
            getattr(v, fn)(*a)
            v.tv.grab_focus()
    win.outline_checks = {}

    def ocheck(label, key, keytip, active):
        def go():
            v = win.outline()
            if v is not None:
                on = not getattr(v, key)
                (v.set_show_formatting if key == "show_formatting" else
                 v.set_first_line_only)(on)
                win.outline_checks[key].set_checked(on)
        cb = CheckControl(r, label, go, active=active, keytip=keytip)
        win.outline_checks[key] = cb
        return cb
    t.add(Group("Outline Tools", [
        [btn("Promote to Heading 1", "cmd/sc_decrementsublevels" if icons.exists(
            "cmd/sc_decrementsublevels") else "cmd/sc_decrementlevel",
             lambda: ov("set_level", 1), keytip="1"),
         btn("Promote", "cmd/sc_decrementlevel", lambda: ov("change_level", -1),
             keytip="P", tip="Promote (Alt+Shift+Left)"),
         btn("Demote", "cmd/sc_incrementlevel", lambda: ov("change_level", 1), keytip="D",
             tip="Demote (Alt+Shift+Right)"),
         btn("Demote to Body Text", "cmd/sc_controlcodes", lambda: ov("set_level", 10),
             keytip="T", tip="Demote to Body Text (Ctrl+Shift+N)")],
        [btn("Move Up", "cmd/sc_moveup", lambda: ov("move", -1), keytip="MU",
             tip="Move Up (Alt+Shift+Up)"),
         btn("Move Down", "cmd/sc_movedown", lambda: ov("move", 1), keytip="MD",
             tip="Move Down (Alt+Shift+Down)"),
         btn("Expand", "cmd/sc_showdetail" if icons.exists("cmd/sc_showdetail") else
             "pan-down-symbolic", lambda: ov("expand", True), keytip="E",
             tip="Expand (Alt+Shift+Plus)"),
         btn("Collapse", "cmd/sc_hidedetail" if icons.exists("cmd/sc_hidedetail") else
             "pan-up-symbolic", lambda: ov("expand", False), keytip="C",
             tip="Collapse (Alt+Shift+Minus)")],
        [MenuButton(r, "Show Level", "cmd/sc_navigator", [
            ("Level %d" % n, (lambda n=n: ov("show_level", n))) for n in range(1, 10)] +
            [("All Levels", lambda: ov("show_level", 9))], size="small", keytip="S"),
         ocheck("Show Text Formatting", "show_formatting", "SF", True),
         ocheck("Show First Line Only", "first_line_only", "SL", False)]]))
    t.add(Group("Close", [
        btn("Close\nOutline View", "cmd/lc_closedoc", "close-outline", size="large",
            keytip="C")]))
    r.add_tab(t)

    # ================================================================= SMARTART DESIGN
    from . import insertmore as IM
    t = r.building(Tab("SmartArt Design", "JS", contextual=True))

    def smart_group():
        if win.native:
            from .native import smartart as NS
            return NS.selected(win)
        from . import drawing
        m = win.engine.model
        return IM.smartart_of(m, drawing.selected_shape(m)) if m is not None else None

    def sa(fn, *a, **kw):
        m = win.engine.model
        g = smart_group()
        if g is None:
            return
        if win.native:
            from .native import smartart as NS
            {"text": lambda: NS.text_pane(win, g), "edit": lambda: NS.edit_graphic(win, g, *a),
             "reset": lambda: NS.reset_graphic(win, g), "to-text": lambda: NS.convert_to_text(win, g),
             "to-shapes": lambda: NS.convert_to_shapes(win, g)}.get(
                fn, lambda: NS.change_layout(win, g, *a, **kw))()
            return
        if fn == "text":
            IM.text_pane(win, g)
        elif fn == "edit":
            win.engine.sync(lambda: IM.edit_graphic(win, g, *a))
        elif fn == "reset":
            win.engine.sync(lambda: IM.reset_graphic(win, g))
        elif fn == "to-text":
            win.engine.sync(lambda: IM.convert_to_text(win, g))
        elif fn == "to-shapes":
            win.engine.sync(lambda: IM.convert_to_shapes(win, g))
        else:
            win.engine.sync(lambda: IM.change_layout(win, g, *a, **kw))
    t.add(Group("Create Graphic", [
        [SplitButton(r, "Add Shape", "cmd/sc_basicshapes", lambda: sa("edit", "after"), [
            ("Add Shape After", lambda: sa("edit", "after")),
            ("Add Shape Before", lambda: sa("edit", "before")),
            ("Add Shape Above", lambda: sa("edit", "above")),
            ("Add Shape Below", lambda: sa("edit", "below"))], keytip="A"),
         btn("Add Bullet", "cmd/sc_defaultbullet", lambda: sa("edit", "bullet"), keytip="B"),
         btn("Text Pane", "cmd/sc_text", lambda: sa("text"), keytip="TP")],
        [btn("Promote", "cmd/sc_outlineleft" if icons.exists("cmd/sc_outlineleft") else
             "cmd/sc_decrementindent", lambda: sa("edit", "promote"), keytip="P"),
         btn("Demote", "cmd/sc_outlineright" if icons.exists("cmd/sc_outlineright") else
             "cmd/sc_incrementindent", lambda: sa("edit", "demote"), keytip="D"),
         btn("Right to Left", "cmd/sc_pararighttoleft",
             lambda: sa("layout", rtl=not ((__import__("folio.native.smartart", fromlist=["x"]).info(win)
                                            if win.native else IM.smartart_info(win.engine.model, smart_group()))
                                           or {}).get("rtl", False)), keytip="R")],
        [btn("Move Up", "cmd/sc_moveup", lambda: sa("edit", "up"), keytip="U"),
         btn("Move Down", "cmd/sc_movedown", lambda: sa("edit", "down"), keytip="W")]]))
    t.add(Group("Layouts", [
        MenuButton(r, "Layouts", "cmd/lc_diagramtype",
                   [it for cat in IM.CATEGORIES[1:] for it in
                    ([("#", cat)] + [(name, (lambda k=k: sa("layout", k)))
                                     for c2, name, k in IM.LAYOUTS if c2 == cat])] +
                   [None, ("More Layouts...", lambda: IM.smartart_dialog(win))],
                   keytip="L")]))
    t.add(Group("SmartArt Styles", [
        MenuButton(r, "Change\nColors", "cmd/lc_diagramarea", [
            ("#", "Colorful"),
            ("Colorful - Accent Colors", lambda: sa("layout", colorful=True))] + [
            ("Accent %d" % (i + 1), (lambda c=c: sa("layout", None, c)))
            for i, c in enumerate(IM.SMART_COLORS)], keytip="C"),
        MenuButton(r, "Styles", "cmd/lc_designerdialog" if icons.exists("cmd/lc_designerdialog")
                   else "cmd/lc_diagramarea", [
            (name, (lambda i=i: sa("layout", style=i))) for i, (name, _x) in
            enumerate(IM.STYLES)], keytip="S")]))
    t.add(Group("Reset", [
        [btn("Reset Graphic", "cmd/sc_setdefault" if icons.exists("cmd/sc_setdefault") else
             "cmd/sc_undo", lambda: sa("reset"), keytip="G"),
         MenuButton(r, "Convert", "cmd/sc_convertmenu" if icons.exists("cmd/sc_convertmenu")
                    else "cmd/sc_formatgroup", [
             ("Convert to Text", lambda: sa("to-text")),
             ("Convert to Shapes", lambda: sa("to-shapes"))], size="small", keytip="V")]]))
    r.add_tab(t)

    # ================================================================= DEVELOPER
    from . import contentcontrols as CC
    t = r.building(Tab("Developer", "L"))
    t.add(Group("Controls", [
        [btn(None, "cc-rich", lambda: CC.insert(win, "rich"),
             size="icon", tip="Rich Text Content Control", keytip="R"),
         btn(None, "cc-plain",
             lambda: CC.insert(win, "plain"), size="icon", tip="Plain Text Content Control",
             keytip="P"),
         btn(None, "cc-picture",
             lambda: CC.insert(win, "picture"), size="icon",
             tip="Picture Content Control", keytip="I")],
        [btn(None, "cc-check",
             lambda: CC.insert(win, "checkbox"), size="icon",
             tip="Check Box Content Control", keytip="H"),
         btn(None, "cc-combo",
             lambda: CC.insert(win, "combo"), size="icon",
             tip="Combo Box Content Control", keytip="O"),
         btn(None, "cc-dropdown",
             lambda: CC.insert(win, "dropdown"), size="icon",
             tip="Drop-Down List Content Control", keytip="Q")],
        [btn(None, "cc-date",
             lambda: CC.insert(win, "date"), size="icon",
             tip="Date Picker Content Control", keytip="D"),
         btn("Properties", "cmd/sc_contentcontrolproperties" if icons.exists(
             "cmd/sc_contentcontrolproperties") else "cmd/sc_controlproperties",
             lambda: CC.properties(win), keytip="L")]]))
    t.add(Group("Protect", [
        btn("Restrict\nEditing", "cmd/lc_protect", lambda: win.show_pane(
            __import__("folio.review", fromlist=["x"]).RestrictPane), size="large",
            keytip="PE")]))
    r.add_tab(t)

    # ================================================================= BACKGROUND REMOVAL
    t = r.building(Tab("Background Removal", "JB", contextual=True))
    t.add(Group("Refine", [
        btn("Mark Areas\nto Keep", "cmd/lc_insertplugin" if False else "pen-black",
            lambda: win.bg_mark("keep"), size="large", keytip="K"),
        btn("Mark Areas\nto Remove", "eraser", lambda: win.bg_mark("remove"), size="large",
            keytip="R")]))
    t.add(Group("Close", [
        btn("Discard All\nChanges", "cmd/lc_delete", lambda: win.bg_finish(False),
            size="large", keytip="D"),
        btn("Keep\nChanges", "cmd/lc_ok" if icons.exists("cmd/lc_ok") else "cmd/lc_apply",
            lambda: win.bg_finish(True), size="large", keytip="C")]))
    r.add_tab(t)

    # ================================================================= IMMERSIVE READER
    from . import readaloud as RA
    t = r.building(Tab("Immersive Reader", "IR", contextual=True))

    def ir(fn):
        v = win.immersive()
        if v is not None:
            fn(v)

    def set_attr(k, val):
        def f(v):
            setattr(v, k, val)
            if k == "syllables":
                v.load()
            else:
                v.apply_look()
        return lambda: ir(f)
    win.ir_checks = {}

    def irtoggle(label, key, icon, keytip):
        def go():
            v = win.immersive()
            if v is None:
                return
            on = not getattr(v, key)
            set_attr(key, on)()
            win.ir_checks[key].apply_state("true" if on else "false")
        b = btn(label, icon, go, size="large", keytip=keytip)
        win.ir_checks[key] = b
        return b
    t.add(Group("Immersive Reader", [
        MenuButton(r, "Column\nWidth", "cmd/lc_formatcolumns", [
            (n, set_attr("width", w)) for n, w in RA.WIDTHS], keytip="CW"),
        MenuButton(r, "Page\nColor", "cmd/lc_backgroundcolor", [
            (c[0], set_attr("color", c)) for c in RA.PAGE_COLORS], keytip="PC"),
        MenuButton(r, "Line\nFocus", "cmd/lc_linenumberingdialog", [
            ("None", set_attr("focus_lines", 0)), ("One Line", set_attr("focus_lines", 1)),
            ("Three Lines", set_attr("focus_lines", 3)),
            ("Five Lines", set_attr("focus_lines", 5))], keytip="LF"),
        irtoggle("Text\nSpacing", "spacing", "cmd/lc_spacepara15", "TS"),
        irtoggle("Syllables", "syllables", "cmd/lc_hyphenate", "SY"),
        btn("Read\nAloud", "readaloud", "read-aloud", size="large", keytip="RA")]))
    t.add(Group("Close", [
        btn("Close\nImmersive Reader", "cmd/lc_closedoc", "close-immersive", size="large",
            keytip="C")]))
    r.add_tab(t)

    t = r.building(Tab("Equation", "JE", contextual=True))
    eq = lambda: win.eqbar
    t.add(Group("Tools", [
        MenuButton(r, "Equation", "eq-equation",
                   lambda: __import__("folio.eqbar", fromlist=["equation_gallery"]).equation_gallery(win),
                   keytip="E", tooltip="Equation"),
        btn("Ink\nEquation", "eq-ink", lambda: eq().ink_equation(), size="large", keytip="I",
            tip="Ink Equation")],
        launcher=lambda: eq().options_dialog(), ribbon=r, launcher_keytip="FO"))
    conv_items = [("Current - Professional", lambda: eq().convert("professional")),
                  ("Current - Linear", lambda: eq().convert("linear")),
                  None,
                  ("All - Professional", lambda: eq().convert_all("professional")),
                  ("All - Linear", lambda: eq().convert_all("linear"))]
    unicode_b = RibbonButton(r, "Unicode", "eq-unicode", lambda: eq().set_input("unicode"),
                             state="folio:eq-unicode", keytip="U",
                             tooltip="Unicode")
    latex_b = RibbonButton(r, "LaTeX", "eq-latex", lambda: eq().set_input("latex"),
                           state="folio:eq-latex", keytip="LX",
                           tooltip="LaTeX")
    t.add(Group("Conversions", [
        [unicode_b, latex_b],
        MenuButton(r, "Convert", "eq-professional", conv_items, keytip="C",
                   tooltip="Convert"),
        RibbonButton(r, "Normal\nText", "eq-normaltext", lambda: eq().convert("text"),
                     size="large", state="folio:eq-text", keytip="N", tooltip="Normal Text")]))
    t.add(Group("Symbols", [SymbolGallery(win)]))
    struct_icons = {"Fraction": "eq-fraction", "Script": "eq-script", "Radical": "eq-radical",
                    "Integral": "eq-integral", "Large Operator": "eq-largeop",
                    "Bracket": "eq-bracket", "Function": "eq-function", "Accent": "eq-accent",
                    "Limit and Log": "eq-limit", "Operator": "eq-operator",
                    "Matrix": "eq-matrix"}
    struct_tips = {"Fraction": "F", "Script": "S", "Radical": "R", "Integral": "I",
                   "Large Operator": "L", "Bracket": "B", "Function": "U", "Accent": "A",
                   "Limit and Log": "O", "Operator": "P", "Matrix": "M"}
    t.add(Group("Structures", [
        MenuButton(r, name.replace(" ", "\n", 1) if " " in name else name,
                   struct_icons.get(name, "eq-equation"),
                   (lambda n=name: gallery_popover(n, win.eqbar.insert)), keytip=struct_tips.get(name))
        for name, _items in EG.GALLERIES if name != "Equation"]))
    r.add_tab(t)

    r.building(None)
    GLib.idle_add(_load_fonts, win)


def _painter(b, win):
    """Double-click Format Painter: it stays on for as many pastes as you like
    (until Esc or another click on it), as in the original."""
    def press(w, ev):
        if ev.button == 1 and ev.type == Gdk.EventType._2BUTTON_PRESS:
            w._skip_click = True
            # the first click switched it on for one use: switch to "keep on"
            win.painter.start(sticky=True)
            win.status.flash("Format Painter stays on. Press Esc to turn it off.")
            return True
        return False

    def run(*_a):
        if getattr(b, "_skip_click", False):
            b._skip_click = False
            return
        b.ribbon.run(b.action)
    b.disconnect_by_func(b.run)
    b.connect("clicked", run)
    b.connect("button-press-event", press)
    return b


def _load_fonts(win):
    fonts = win.engine.fonts()
    if not fonts:
        GLib.timeout_add(500, _load_fonts, win)
        return False
    win.font_combo.set_fonts(fonts)
    return False


HEADERS = ("Theme Fonts", "Recently Used Fonts", "All Fonts")


def _effects_popover(win, mode):
    """WordArt / Text Effects gallery: an 'A' for each style."""
    from . import insertextras as IX
    pop = Gtk.Popover()
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    box.set_border_width(8)
    g = Gtk.Grid(column_spacing=4, row_spacing=4)
    for i, (name, color, outline, shadow, bold) in enumerate(IX.EFFECTS):
        b = Gtk.Button()
        b.set_relief(Gtk.ReliefStyle.NONE)
        lab = Gtk.Label()
        attrs = "size='22pt' weight='%s' foreground='#%06x'" % ("bold" if bold else "normal",
                                                               color)
        lab.set_markup("<span %s>A</span>" % attrs)
        if outline:
            lab.get_style_context().add_class("folio-outline-a")
        b.add(lab)
        b.set_tooltip_text(name)

        def pick(_b, i=i):
            pop.popdown()
            if mode == "wordart":
                win.model_call_sync("insertextras.insert_wordart", i)
            else:
                win.model_call_sync("insertextras.text_effect", i)
        b.connect("clicked", pick)
        g.attach(b, i % 5, i // 5, 1, 1)
    box.pack_start(g, False, False, 0)
    if mode != "wordart":
        box.pack_start(Gtk.Separator(), False, False, 2)
        for label, prop in (("Outline", "CharContoured"), ("Shadow", "CharShadowed")):
            bb = Gtk.Button(label=label)
            bb.set_relief(Gtk.ReliefStyle.NONE)
            bb.get_child().set_xalign(0)
            bb.connect("clicked", lambda _b, p=prop: (pop.popdown(), win.model_call_sync(
                "insertextras.toggle_char", p)))
            box.pack_start(bb, False, False, 0)
    box.show_all()
    pop.add(box)
    return pop


def _set(win, name, widget):
    setattr(win, name, widget)
    return widget


def _cover_menu(win):
    from . import covers
    from .ribbon import menu_popover
    items = [("#", "Built-in")] + [
        (n, (lambda n=n: win.engine.sync(lambda: covers.insert_cover(win, n))))
        for n, _s in covers.COVERS]
    saved = covers.gallery_parts("Cover Pages")
    if saved:
        items += [("#", "Custom")] + [(p["name"], (lambda p=p: covers.insert_saved(
            win, p, "cover"))) for p in saved]
    items += [None, ("Remove Current Cover Page",
                     lambda: win.engine.sync(lambda: covers.remove_current(win))),
              ("Save Selection to Cover Page Gallery...",
               lambda: covers.save_selection(win, "Cover Pages"))]
    return menu_popover(None, items)


def _hf_menu(win, which):
    from . import covers
    from .ribbon import menu_popover
    names = covers.HEADERS if which == "header" else covers.FOOTERS
    gal = "Headers" if which == "header" else "Footers"
    word = "Header" if which == "header" else "Footer"
    items = [("#", "Built-in")] + [
        (n, (lambda n=n: (covers.hf_design(win, which, n) if getattr(win, "native", False) else
                          (win.engine.sync(lambda: covers.hf_design(win, which, n)), win.run(which)))))
        for n in names]
    saved = covers.gallery_parts(gal)
    if saved:
        items += [("#", "Custom")] + [(p["name"], (lambda p=p: covers.insert_saved(
            win, p, which))) for p in saved]
    items += [None, ("Edit %s" % word, lambda: win.run(which)),
              ("Remove %s" % word, lambda: win.run("remove-" + which)),
              ("Save Selection to %s Gallery..." % word,
               lambda: covers.save_selection(win, gal))]
    return menu_popover(None, items)


def _reviewers_dialog(win):
    """Show Markup > Specific People: tick the reviewers to show."""
    from .widgets import FDialog
    names = sorted(set(win.comments.authors()) | set(win.change_bars.authors()))
    d = FDialog(win, "Specific People")
    if not names:
        d.add(Gtk.Label(label="There are no reviewers in this document.", xalign=0))
    allc = Gtk.CheckButton(label="All Reviewers")
    allc.set_active(not win.change_bars.hidden_authors and not win.comments.hidden_authors)
    d.add(allc)
    checks = {}
    for n in names:
        c = Gtk.CheckButton(label=n)
        c.set_active(n not in win.change_bars.hidden_authors)
        c.set_margin_start(18)
        checks[n] = c
        d.add(c)
    allc.connect("toggled", lambda b: [c.set_active(b.get_active()) for c in checks.values()])
    d.show_all()
    if d.ask() == Gtk.ResponseType.OK:
        for n, c in checks.items():
            win.reviewer_filter(n, c.get_active())
    d.destroy()


def _mk_markup_choice(r, win):
    c = ChoiceControl(r, ["All Markup", "Simple Markup", "No Markup", "Original"],
                      lambda v: win.set_markup_display(v), keytip="TD",
                      tooltip="Display for Review")
    win.markup_choice = c
    return c


def _labeled_choice(text, w):
    b = Gtk.Box(spacing=4)
    b.pack_start(Gtk.Label(label=text), False, False, 0)
    b.pack_start(w, False, False, 0)
    return b


class FontCombo(ComboControl):
    """The font box: Theme Fonts, Recently Used Fonts and All Fonts, each
    name shown in its own typeface."""
    def __init__(self, win, ribbon, apply):
        self.win = win
        self.apply = apply
        self.all = []
        self.theme = ("Carlito", "Carlito")
        ComboControl.__init__(self, ribbon, [], self._picked, 14, state=".uno:CharFontName",
                              keytip="FF", tooltip="Font (Ctrl+Shift+F)")
        cell = self.get_cells()[0]
        self.set_cell_data_func(cell, self._cell)
        try:
            self.set_wrap_width(0)
        except Exception:
            pass

    def _cell(self, layout, cell, model, it, data=None):
        t = model[it][0]
        if t in HEADERS:
            cell.set_property("family", "")
            cell.set_property("weight", 700)
            cell.set_property("sensitive", False)
            cell.set_property("background", "#f0f0f0")
            cell.set_property("background-set", True)
        else:
            cell.set_property("family", t.split(" (")[0])
            cell.set_property("weight", 400)
            cell.set_property("sensitive", True)
            cell.set_property("background-set", False)

    @staticmethod
    def _name(text):
        for suffix in (" (Headings)", " (Body)"):
            if text.endswith(suffix):
                return text[:-len(suffix)]
        return text

    def _picked(self, text):
        if text in HEADERS or text == "-":
            return
        name = self._name(text)
        self.apply(name)
        rec = [f for f in self.win.app.settings.get("recent_fonts", []) if f != name]
        self.win.app.settings["recent_fonts"] = [name] + rec[:5]
        GLib.idle_add(self.rebuild)

    def set_fonts(self, fonts):
        self.all = fonts
        self.rebuild()

    def set_theme(self, heading, body):
        self.theme = (heading or "Carlito", body or "Carlito")
        self.rebuild()

    def rebuild(self):
        if self.get_child().has_focus() and self.get_property("popup-shown"):
            return False
        recent = [f for f in self.win.app.settings.get("recent_fonts", []) if f in self.all][:6]
        items = ["Theme Fonts", "%s (Headings)" % self.theme[0], "%s (Body)" % self.theme[1]]
        if recent:
            items += ["Recently Used Fonts"] + recent
        items += ["All Fonts"] + self.all
        text = self.get_child().get_text()
        self.set_items(items)
        self._updating = True
        self.get_child().set_text(text)
        self._updating = False
        return False
