"""The Paste Options button: after pasting, a small (Ctrl) button at the end
of the pasted text offers Keep Source Formatting / Keep Text Only. Pressing
Ctrl on its own opens it; K or T picks."""
from gi.repository import Gdk, GLib, Gtk

from . import icons


class PasteOptions:
    def __init__(self, win, overlay):
        self.win = win
        self.overlay = overlay
        self.cursor = None          # (x, y, w, h) in view pixels
        self.pop = None
        self.mode = "source"
        view = win.engine.view
        view.connect("cursor-changed", self._cursor)
        btn = Gtk.Button()
        btn.get_style_context().add_class("folio-pasteopts")
        box = Gtk.Box(spacing=2)
        box.pack_start(icons.image("cmd/sc_paste", 16), False, False, 0)
        box.pack_start(Gtk.Label(label="(Ctrl)"), False, False, 0)
        btn.add(box)
        btn.set_focus_on_click(False)
        btn.set_tooltip_text("Paste Options")
        btn.set_halign(Gtk.Align.START)
        btn.set_valign(Gtk.Align.START)
        btn.set_no_show_all(True)
        btn.connect("clicked", lambda *_: self.open_menu())
        overlay.add_overlay(btn)
        self.btn = btn
        self.visible = False
        view.connect("button-press-event", lambda *_: (self.hide(), False)[1])
        sw = win.canvas
        sw.get_vadjustment().connect("value-changed", lambda *_: self._place())

    def _cursor(self, view, x, y, w, h):
        self.cursor = (x, y, w, h)

    # ------------------------------------------------------------ show / hide
    def after_paste(self, mode="source"):
        """Called once the engine has handled a paste."""
        self.mode = mode
        GLib.timeout_add(120, self._show)

    def _show(self):
        self.visible = True
        self._place()
        return False

    def _place(self):
        if not self.visible or self.cursor is None:
            return
        x, y, w, h = self.cursor          # twips
        px, py = self.win.engine.twips_to_px(x, y + h)
        res = self.win.engine.view.translate_coordinates(self.overlay, int(px) + 4,
                                                         int(py) + 2)
        if not res:
            return
        ox, oy = res
        alloc_h = self.overlay.get_allocated_height()
        if oy < 0 or oy > alloc_h - 10:
            self.btn.hide()
            return
        self.btn.set_margin_start(max(0, ox))
        self.btn.set_margin_top(max(0, oy))
        self.btn.get_child().show_all()
        self.btn.show()

    def hide(self):
        self.visible = False
        self.btn.hide()
        if self.pop is not None:
            self.pop.popdown()

    # ------------------------------------------------------------ keys
    def key(self, event):
        """Window key handler hook. True = handled."""
        if not self.visible:
            return False
        name = (Gdk.keyval_name(event.keyval) or "").lower()
        if self.pop is not None and self.pop.get_visible():
            if name == "k":
                self.pick("source")
                return True
            if name == "t":
                self.pick("text")
                return True
            if name == "m":
                self.pick("merge")
                return True
            if name == "escape":
                self.pop.popdown()
                return True
            return False
        if name in ("control_l", "control_r"):
            self._ctrl_alone = True
            return False
        self._ctrl_alone = False
        if name in ("shift_l", "shift_r", "alt_l", "alt_r"):
            return False
        if name == "escape":
            self.hide()
            return True
        self.hide()
        return False

    def key_release(self, event):
        name = (Gdk.keyval_name(event.keyval) or "").lower()
        if self.visible and name in ("control_l", "control_r") and \
                getattr(self, "_ctrl_alone", False):
            self._ctrl_alone = False
            self.open_menu()
            return True
        return False

    # ------------------------------------------------------------ menu
    def open_menu(self):
        if not self.btn.get_visible():
            return
        pop = Gtk.Popover.new(self.btn)
        pop.set_modal(False)
        pop.set_position(Gtk.PositionType.BOTTOM)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_border_width(6)
        lab = Gtk.Label(xalign=0)
        lab.set_markup("<b>Paste Options:</b>")
        box.pack_start(lab, False, False, 0)
        row = Gtk.Box(spacing=4)
        for mode, icon, tip in (("source", "cmd/sc_paste", "Keep Source Formatting (K)"),
                                ("merge", "cmd/sc_pastespecial", "Merge Formatting (M)"),
                                ("text", "cmd/sc_pasteunformatted", "Keep Text Only (T)")):
            b = Gtk.Button()
            b.add(icons.image(icon, 24))
            b.set_tooltip_text(tip)
            b.get_style_context().add_class("folio-btn")
            if mode == self.mode:
                b.get_style_context().add_class("checked")
            b.connect("clicked", lambda _b, m=mode: self.pick(m))
            row.pack_start(b, False, False, 0)
        box.pack_start(row, False, False, 0)
        sd = Gtk.Button(label="Set Default Paste...")
        sd.set_relief(Gtk.ReliefStyle.NONE)
        sd.connect("clicked", lambda *_: (pop.popdown(), self.win.dialogs.options("Advanced")))
        box.pack_start(sd, False, False, 0)
        box.show_all()
        pop.add(box)
        pop.popup()
        self.pop = pop

    def pick(self, mode):
        if self.pop is not None:
            self.pop.popdown()
        if mode == self.mode:
            self.win.focus_document()
            return
        A = self.win.actions
        A.do_undo()
        self.win.engine.sync(lambda: A._paste(mode))
        self.mode = mode
        self.win.engine.sync(lambda: GLib.timeout_add(120, self._show))
        self.win.focus_document()


_KEEP = {"b", "strong", "i", "em", "u", "s", "strike", "sub", "sup", "p", "br", "ul", "ol",
         "li", "a", "table", "tr", "td", "th", "tbody", "thead"}


def merge_html(src):
    """Merge Formatting: keep emphasis, lists, links and tables, but drop fonts,
    sizes, colours and styles so the text takes on the surrounding format."""
    from html.parser import HTMLParser
    import html as H
    out = []

    class P(HTMLParser):
        def handle_starttag(self, tag, attrs):
            if tag in _KEEP:
                a = ""
                if tag == "a":
                    href = dict(attrs).get("href")
                    if href:
                        a = ' href="%s"' % H.escape(href, quote=True)
                out.append("<%s%s>" % (tag, a))
            elif tag in ("h1", "h2", "h3", "h4", "h5", "h6", "div"):
                out.append("<p>")

        def handle_endtag(self, tag):
            if tag in _KEEP and tag != "br":
                out.append("</%s>" % tag)
            elif tag in ("h1", "h2", "h3", "h4", "h5", "h6", "div"):
                out.append("</p>")

        def handle_data(self, data):
            out.append(H.escape(data, quote=False))
    try:
        body = src
        lo = src.lower()
        if "<body" in lo:
            body = src[lo.index("<body"):]
        P(convert_charrefs=True).feed(body)
    except Exception:
        return src
    body = "".join(out).strip()
    if body.count("<p>") == 1 and body.startswith("<p>") and body.endswith("</p>"):
        body = body[3:-4]          # one paragraph: paste inline, no new paragraph
    return "<html><body>%s</body></html>" % body
