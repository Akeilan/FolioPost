"""Small building blocks for the app's dialogs and panes."""
import re

from gi.repository import Gdk, GLib, Gtk, Pango

MM100_PER_INCH = 2540

_UNIT = [None]


def units():
    """('in', mm100 per unit) for letter-paper locales, else ('cm', ...)."""
    if _UNIT[0] is None:
        try:
            import subprocess
            out = subprocess.run(["locale", "-k", "LC_PAPER"], capture_output=True,
                                 text=True, timeout=5).stdout
            _UNIT[0] = ("in", 2540) if "height=279" in out else ("cm", 1000)
        except Exception:
            _UNIT[0] = ("in", 2540)
    return _UNIT[0]


UNIT_CHOICES = {"Inches": ("in", 2540), "Centimeters": ("cm", 1000),
                "Millimeters": ("mm", 100), "Points": ("pt", 2540 / 72.0),
                "Picas": ("pi", 2540 / 6.0)}
SUFFIX = {"in": '"', "cm": " cm", "mm": " mm", "pt": " pt", "pi": " pi"}


def set_units(choice):
    """Options > Advanced > Show measurements in units of."""
    _UNIT[0] = UNIT_CHOICES.get(choice) if choice else None


def ruler_units():
    """Rulers count in inches or centimetres."""
    name, f = units()
    return ("in", 2540) if name in ("in", "pt", "pi") else ("cm", 1000)


def fmt_len(mm100):
    name, f = units()
    v = mm100 / f
    s = ("%.2f" % v if name in ("in", "cm") else "%.1f" % v).rstrip("0").rstrip(".")
    if s == "-0":
        s = "0"
    return s + SUFFIX.get(name, "")


def parse_len(text, default=0):
    """'1.5"', '2 cm', '12 pt', '3' -> mm100 (bare numbers use the UI unit)."""
    t = text.strip().lower().replace(",", ".")
    m = re.match(r"^(-?\d*\.?\d+)\s*(\"|in|inch|inches|cm|mm|pt|pi)?$", t)
    if not m:
        return default
    v = float(m.group(1))
    u = m.group(2)
    if u in ('"', "in", "inch", "inches"):
        return int(round(v * 2540))
    if u == "cm":
        return int(round(v * 1000))
    if u == "mm":
        return int(round(v * 100))
    if u == "pt":
        return int(round(v * 2540 / 72))
    if u == "pi":
        return int(round(v * 2540 / 6))
    return int(round(v * units()[1]))


class LengthSpin(Gtk.SpinButton):
    """Spin box showing a length with its unit, like 1.25" or 3.2 cm.
    Values in and out (mm100, set_value/get_value) are in 1/100 mm."""
    def __init__(self, mm100=0, lo=-55880, hi=55880, step=None):
        name, self.f = units()
        step = step or {"mm": 1, "pt": 1, "pi": 0.5}.get(name, 0.1)
        adj = Gtk.Adjustment(value=mm100 / self.f, lower=lo / self.f, upper=hi / self.f,
                             step_increment=step, page_increment=step * 5)
        Gtk.SpinButton.__init__(self, adjustment=adj, digits=2)
        self.set_numeric(False)
        self.set_width_chars(8)
        self.connect("output", self._output)
        self.set_value(mm100)

    def _output(self, spin):
        spin.set_text(fmt_len(int(round(Gtk.SpinButton.get_value(spin) * self.f))))
        return True

    def set_value(self, mm100):
        Gtk.SpinButton.set_value(self, mm100 / self.f)

    def get_value(self):
        return Gtk.SpinButton.get_value(self) * self.f

    @property
    def mm100(self):
        self.update()
        return int(round(self.get_value()))


class PointSpin(Gtk.SpinButton):
    """Spin box in points ('6 pt'), value in points."""
    def __init__(self, value=0.0, lo=0, hi=1584, step=6, auto_label=None):
        adj = Gtk.Adjustment(value=value, lower=lo, upper=hi, step_increment=step,
                             page_increment=step * 2)
        Gtk.SpinButton.__init__(self, adjustment=adj, digits=1)
        self.set_numeric(False)
        self.set_width_chars(7)
        self.auto_label = auto_label
        self.connect("output", self._output)
        self.set_value(value)

    def _output(self, spin):
        v = spin.get_value()
        if self.auto_label and v < 0:
            spin.set_text(self.auto_label)
        else:
            spin.set_text(("%.1f" % v).rstrip("0").rstrip(".") + " pt")
        return True

    @property
    def points(self):
        self.update()
        return self.get_value()


class FDialog(Gtk.Dialog):
    """A modal dialog with the app's look: content area and right-aligned
    buttons (default button first in `buttons`)."""
    def __init__(self, parent, title, buttons=(("OK", Gtk.ResponseType.OK),
                                               ("Cancel", Gtk.ResponseType.CANCEL)),
                 width=-1, help_text=None):
        Gtk.Dialog.__init__(self, title=title, transient_for=parent, modal=True,
                            use_header_bar=False)
        self.set_resizable(False)
        self.set_default_size(width, -1)
        self.get_style_context().add_class("folio-dialog")
        self.set_skip_taskbar_hint(True)
        self.box = self.get_content_area()
        self.box.set_spacing(8)
        self.box.set_border_width(12)
        area = self.get_action_area()
        area.set_border_width(8)
        self.buttons = {}
        first = True
        for label, resp in buttons:
            b = self.add_button(label, resp)
            self.buttons[resp] = b
            if first:
                b.get_style_context().add_class("suggested-action")
                b.get_style_context().add_class("folio-default")
                self.set_default_response(resp)
                first = False
        self.connect("key-press-event", self._key)

    def _key(self, w, ev):
        if ev.keyval == Gdk.KEY_Escape:
            self.response(Gtk.ResponseType.CANCEL)
            return True
        return False

    def add(self, widget, expand=False):
        self.box.pack_start(widget, expand, expand, 0)
        return widget

    def ask(self):
        self.show_all()
        r = self.run()
        return r

    def done(self):
        self.destroy()


def heading(text):
    """A section heading with a rule, like 'Effects ______'."""
    box = Gtk.Box(spacing=6)
    lab = Gtk.Label(xalign=0)
    lab.set_markup("<b>%s</b>" % GLib.markup_escape_text(text))
    box.pack_start(lab, False, False, 0)
    sep = Gtk.Separator()
    sep.set_valign(Gtk.Align.CENTER)
    box.pack_start(sep, True, True, 0)
    box.set_margin_top(6)
    return box


def grid(rows, col_spacing=10, row_spacing=6):
    """rows: list of lists of widgets/strings (None = empty)."""
    g = Gtk.Grid(column_spacing=col_spacing, row_spacing=row_spacing)
    for r, row in enumerate(rows):
        for c, w in enumerate(row):
            if w is None:
                continue
            if isinstance(w, str):
                w = Gtk.Label(label=w, xalign=0, use_underline=True)
            g.attach(w, c, r, 1, 1)
    return g


def combo(items, active=0, entry=False):
    c = Gtk.ComboBoxText.new_with_entry() if entry else Gtk.ComboBoxText()
    for it in items:
        c.append_text(it)
    if isinstance(active, str):
        if active in items:
            c.set_active(items.index(active))
        elif entry:
            c.get_child().set_text(active)
    elif active is not None and active >= 0 and items:
        c.set_active(active)
    return c


def combo_text(c):
    if isinstance(c.get_child(), Gtk.Entry):
        return c.get_child().get_text()
    return c.get_active_text() or ""


def listbox(items, height=140, width=180, on_activate=None, on_select=None):
    """A simple scrolled list. Returns (scrolled, treeview, store)."""
    store = Gtk.ListStore(str)
    for it in items:
        store.append([it])
    tv = Gtk.TreeView(model=store)
    tv.set_headers_visible(False)
    tv.append_column(Gtk.TreeViewColumn("", Gtk.CellRendererText(), text=0))
    sw = Gtk.ScrolledWindow()
    sw.set_size_request(width, height)
    sw.set_shadow_type(Gtk.ShadowType.IN)
    sw.add(tv)
    if on_activate:
        tv.connect("row-activated", lambda t, p, c: on_activate(store[p][0]))
    if on_select:
        tv.get_selection().connect("changed", lambda s: on_select(_sel(tv)))
    return sw, tv, store


def _sel(tv):
    model, it = tv.get_selection().get_selected()
    return model[it][0] if it else None


def list_selected(tv):
    return _sel(tv)


def list_select(tv, text):
    for row in tv.get_model():
        if row[0] == text:
            tv.get_selection().select_iter(row.iter)
            tv.scroll_to_cell(row.path, None, False, 0, 0)
            return True
    return False


class Preview(Gtk.DrawingArea):
    """A small page preview box: draw_fn(cr, w, h)."""
    def __init__(self, draw_fn, width=300, height=90):
        Gtk.DrawingArea.__init__(self)
        self.set_size_request(width, height)
        self.draw_fn = draw_fn
        self.connect("draw", self._draw)

    def _draw(self, w, cr):
        a = w.get_allocation()
        cr.set_source_rgb(1, 1, 1)
        cr.rectangle(0, 0, a.width, a.height)
        cr.fill()
        cr.set_source_rgb(0.75, 0.75, 0.75)
        cr.set_line_width(1)
        cr.rectangle(0.5, 0.5, a.width - 1, a.height - 1)
        cr.stroke()
        self.draw_fn(cr, a.width, a.height)


def rgb(color):
    return ((color >> 16) & 255) / 255.0, ((color >> 8) & 255) / 255.0, (color & 255) / 255.0


def color_button(color, on_change=None, auto_label="Automatic"):
    """A drop-down color picker button. .color holds the value (-1 auto)."""
    from .ribbon_defs import color_palette
    btn = Gtk.MenuButton()
    btn.color = color
    swatch = Gtk.DrawingArea()
    swatch.set_size_request(70, 14)

    def draw(w, cr):
        a = w.get_allocation()
        if btn.color is None or btn.color < 0:
            cr.set_source_rgb(0, 0, 0)
            cr.select_font_face("Sans")
            cr.set_font_size(11)
            cr.move_to(2, a.height - 3)
            cr.show_text(auto_label)
            return
        cr.set_source_rgb(*rgb(btn.color))
        cr.rectangle(0, 0, a.width, a.height)
        cr.fill()
    swatch.connect("draw", draw)
    btn.add(swatch)
    pop = Gtk.Popover.new(btn)
    ref = [pop]

    def pick(c):
        btn.color = c
        swatch.queue_draw()
        pop.popdown()
        if on_change:
            on_change(c)
    pal = color_palette(pick, none_label=auto_label, popover_ref=ref)
    pal.show_all()
    pop.add(pal)
    btn.set_popover(pop)
    return btn


def ellipsize_label(text, chars=40):
    lab = Gtk.Label(label=text, xalign=0)
    lab.set_ellipsize(Pango.EllipsizeMode.END)
    lab.set_max_width_chars(chars)
    return lab
