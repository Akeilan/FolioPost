"""The Mini Toolbar: common formatting next to the pointer after selecting
text with the mouse."""
from gi.repository import Gdk, GLib, Gtk

from . import icons


class MiniToolbar:
    def __init__(self, win):
        self.win = win
        self.pop = None
        view = win.engine.view
        view.connect("button-release-event", self._release)
        view.connect("key-press-event", lambda *_: (self.hide(), False)[1])
        view.connect("button-press-event", lambda *_: (self.hide(), False)[1])
        view.connect("motion-notify-event", self._motion)
        self._at = None

    def _motion(self, view, ev):
        # as in the original, it fades away as the pointer moves off
        if self._at is not None and self.get_visible():
            dx, dy = ev.x - self._at[0], ev.y - self._at[1]
            if dx * dx + dy * dy > 140 * 140:
                self.hide()
        return False

    def _release(self, view, ev):
        if ev.button != 1 or not self.win.app.settings.get("mini_toolbar", True):
            return False
        x, y = int(ev.x), int(ev.y)
        # give the engine a moment to report the new selection
        GLib.timeout_add(250, self._maybe_show, x, y)
        return False

    def _maybe_show(self, x, y):
        eng = self.win.engine
        if eng.selection_type() not in (1, 2):     # text selections only
            return False
        if self.win.draw.active:
            return False
        if getattr(eng.view, "bar_select", False):
            return False        # the selection bar in the margin: no toolbar over the text
        self.show(x, y)
        return False

    def hide(self):
        if self.pop is not None:
            self.pop.popdown()

    def get_visible(self):
        return self.pop is not None and self.pop.get_visible()

    def show(self, x, y):
        self.hide()
        self._at = (x, y)
        A = self.win.actions
        run = self.win.run
        pop = Gtk.Popover.new(self.win.engine.view)
        pop.set_modal(False)
        pop.set_position(Gtk.PositionType.TOP)
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = x, y - 6, 1, 1
        pop.set_pointing_to(rect)
        pop.get_style_context().add_class("folio-minibar")
        grid = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        grid.set_border_width(3)
        row1 = Gtk.Box(spacing=2)
        row2 = Gtk.Box(spacing=2)
        font = Gtk.ComboBoxText.new_with_entry()
        for f in self.win.engine.fonts()[:200]:
            font.append_text(f)
        font.get_child().set_text(self.win.engine.get(".uno:CharFontName"))
        font.get_child().set_width_chars(12)
        font.connect("changed", lambda c: c.get_active() >= 0 and A.font_name(c.get_active_text()))
        size = Gtk.ComboBoxText.new_with_entry()
        for s in ("8", "9", "10", "11", "12", "14", "16", "18", "20", "24", "28", "36", "48", "72"):
            size.append_text(s)
        size.get_child().set_text(self.win.engine.get(".uno:FontHeight"))
        size.get_child().set_width_chars(3)
        size.connect("changed", lambda c: c.get_active() >= 0 and A.font_size(c.get_active_text()))
        size.get_child().connect("activate", lambda e: A.font_size(e.get_text()))
        font.get_child().connect("activate", lambda e: A.font_name(e.get_text()))
        row1.pack_start(font, False, False, 0)
        row1.pack_start(size, False, False, 0)

        def b(box, icon, action, tip):
            btn = Gtk.Button()
            btn.set_relief(Gtk.ReliefStyle.NONE)
            btn.add(icons.image(icon, 16))
            btn.set_tooltip_text(tip)
            btn.set_focus_on_click(False)
            btn.connect("clicked", lambda *_: run(action))
            box.pack_start(btn, False, False, 0)
        b(row1, "cmd/sc_grow", "grow-font", "Increase Font Size")
        b(row1, "cmd/sc_shrink", "shrink-font", "Decrease Font Size")
        b(row1, "cmd/sc_stylesmenu" if False else "cmd/sc_designerdialog", "styles-pane", "Styles")
        b(row2, "cmd/sc_bold", ".uno:Bold", "Bold")
        b(row2, "cmd/sc_italic", ".uno:Italic", "Italic")
        b(row2, "cmd/sc_underline", ".uno:Underline", "Underline")
        b(row2, "cmd/sc_backcolor", "highlight", "Text Highlight Color")
        b(row2, "cmd/sc_color", "font-color", "Font Color")
        b(row2, "cmd/sc_formatpaintbrush", ".uno:FormatPaintbrush", "Format Painter")
        b(row2, "cmd/sc_defaultbullet", "bullets", "Bullets")
        b(row2, "cmd/sc_defaultnumbering", "numbering", "Numbering")
        b(row2, "cmd/sc_insertannotation", "comment", "New Comment")
        grid.pack_start(row1, False, False, 0)
        grid.pack_start(row2, False, False, 0)
        grid.show_all()
        pop.add(grid)
        pop.popup()
        self.pop = pop
