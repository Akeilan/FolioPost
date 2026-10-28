"""Equations: insert, edit and the Equation tab.

An equation lives in the document as a real formula object and is edited in
place on the page (mathedit.InlineEditor), in built-up (Professional) or
one-line (Linear) form. Linear text can be typed in UnicodeMath or LaTeX;
control words (\\alpha, \\sum ...) and structures (a/b, x^2 ...) build up
when followed by a space or an operator, as in the original.
"""
import os

from gi.repository import Gdk, GLib, Gtk, Pango

from . import SHARE, docapi, icons
from .eqn import galleries as G
from .eqn import latex, starmath, unicodemath
from .eqn import model as M

PLACEHOLDER_MARKUP = '"Type equation here."'
SLOT = unicodemath.S.PLACEHOLDER if hasattr(unicodemath.S, "PLACEHOLDER") else "⬚"
MATH_FONT = "Latin Modern Math, DejaVu Math TeX Gyre, Cambria Math, serif"


def gallery_image(item_id):
    for base in (os.path.join(SHARE, "equations"),
                 os.path.join(os.path.dirname(__file__), "..", "..", "share", "equations")):
        p = os.path.join(base, item_id + ".png")
        if os.path.exists(p):
            return p
    return None


def _item_widget(item_id, title, linear, big=False):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    img = gallery_image(item_id)
    if img:
        from gi.repository import GdkPixbuf
        try:
            pb = GdkPixbuf.Pixbuf.new_from_file(img)
            maxw = 300 if big else 64
            if pb.get_width() > maxw:
                pb = pb.scale_simple(maxw, int(pb.get_height() * maxw / pb.get_width()),
                                     GdkPixbuf.InterpType.BILINEAR)
            box.pack_start(Gtk.Image.new_from_pixbuf(pb), False, False, 0)
        except Exception:
            img = None
    if not img:
        lab = Gtk.Label()
        lab.set_markup('<span font_family="%s" size="%s">%s</span>' % (
            MATH_FONT.split(",")[0], "large" if big else "medium",
            GLib.markup_escape_text(linear.replace(SLOT, "⬚"))))
        lab.set_ellipsize(Pango.EllipsizeMode.END)
        lab.set_max_width_chars(40 if big else 10)
        box.pack_start(lab, False, False, 0)
    if big:
        t = Gtk.Label(label=title, xalign=0)
        t.get_style_context().add_class("dim-label")
        box.pack_start(t, False, False, 0)
    return box


def gallery_popover(name, on_pick, big=False, columns=4):
    """A popover for one structure gallery (Fraction, Script, ...)."""
    items = dict(G.GALLERIES).get(name, [])
    pop = Gtk.Popover()
    outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    outer.set_border_width(6)
    sw = Gtk.ScrolledWindow()
    sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    sw.set_propagate_natural_height(True)
    sw.set_max_content_height(520)
    inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    sw.add(inner)
    outer.pack_start(sw, True, True, 0)
    flow = None
    for it in items:
        iid, title, lin = it
        if iid == "#":
            h = Gtk.Label(xalign=0)
            h.set_markup("<b>%s</b>" % GLib.markup_escape_text(title))
            h.get_style_context().add_class("folio-gallery-head")
            inner.pack_start(h, False, False, 2)
            flow = Gtk.FlowBox()
            flow.set_max_children_per_line(1 if big else columns)
            flow.set_selection_mode(Gtk.SelectionMode.NONE)
            inner.pack_start(flow, False, False, 0)
            continue
        if flow is None:
            flow = Gtk.FlowBox()
            flow.set_max_children_per_line(1 if big else columns)
            flow.set_selection_mode(Gtk.SelectionMode.NONE)
            inner.pack_start(flow, False, False, 0)
        b = Gtk.Button()
        b.set_relief(Gtk.ReliefStyle.NONE)
        b.get_style_context().add_class("folio-eq-item")
        b.set_tooltip_text(title)
        b.add(_item_widget(iid, title, lin, big))
        b.connect("clicked", lambda _b, lin=lin: (pop.popdown(), on_pick(lin)))
        flow.add(b)
    outer.show_all()
    pop.add(outer)
    return pop


def equation_gallery(win):
    """Insert > Equation drop-down: built-in equations + new equation."""
    pop = gallery_popover("Equation", lambda lin: win.eqbar.new_equation(lin), big=True)
    box = pop.get_child()
    box.pack_end(Gtk.Separator(), False, False, 2)
    for label, cb, icon in (
            ("Insert New Equation", lambda: win.eqbar.new_equation(), "cmd/sc_insertobjectstarmath"),
            ("Save Selection to Equation Gallery...", lambda: win.eqbar.save_to_gallery(), None)):
        b = Gtk.Button()
        b.set_relief(Gtk.ReliefStyle.NONE)
        hb = Gtk.Box(spacing=8)
        if icon:
            hb.pack_start(icons.image(icon, 16), False, False, 0)
        hb.pack_start(Gtk.Label(label=label, xalign=0), True, True, 0)
        b.add(hb)
        b.connect("clicked", lambda _b, cb=cb: (pop.popdown(), GLib.idle_add(lambda: (cb(), False)[1])))
        b.show_all()
        box.pack_end(b, False, False, 0)
    user = win.app.settings.get("user_equations", [])
    if user:
        h = Gtk.Label(xalign=0)
        h.set_markup("<b>General</b>")
        box.pack_start(h, False, False, 2)
        box.reorder_child(h, 0)
        for i, (title, lin) in enumerate(user):
            b = Gtk.Button()
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.add(_item_widget("", title, lin, True))
            b.connect("clicked", lambda _b, lin=lin: (pop.popdown(), win.eqbar.new_equation(lin)))
            b.show_all()
            box.pack_start(b, False, False, 0)
            box.reorder_child(b, i + 1)
    return pop


class EquationBar(Gtk.Revealer):
    """The equation controller (the name is kept from the time equations
    were typed in a bar above the page; the bar itself is gone)."""
    def __init__(self, win):
        Gtk.Revealer.__init__(self)
        self.win = win
        self.set_reveal_child(False)
        self.set_no_show_all(True)
        self.input_format = win.app.settings.get("eq_input", "unicode")
        self.normal_text = False
        from .mathedit import InlineEditor
        from . import eqoptions
        eqoptions.apply(win.app)
        if getattr(win.engine, "native", False):
            from .native.equations import NativeInlineEditor
            self.ed = NativeInlineEditor(win, self)
        else:
            self.ed = InlineEditor(win, self)
        self.entry = _EntryShim(self)
        self.listener = None

    @property
    def obj(self):
        return self.ed.obj

    # -------------------------------------------------------------- selection
    def _selection_changed(self, click=None):
        m = self.win.engine.model
        if m is None:
            return
        obj = docapi.selected_formula_object(m)
        if obj is not None:
            self.edit(obj, click=click)
            return
        if self.ed.active:
            self.close(commit=True, move_cursor=False)

    # -------------------------------------------------------------- open/close
    def new_equation(self, linear=None):
        if getattr(self.win.engine, "native", False):
            from .native import equations
            equations.new_equation(self, linear)
            return
        m = self.win.engine.model
        if m is None:
            self.win.dialogs.message("The document is still opening. Try again in a moment.")
            return
        if self.ed.active:
            self.finish()
        vc = docapi.view_cursor(m)
        cur = vc.getText().createTextCursorByRange(vc)
        cur.gotoStartOfParagraph(True)
        alone = cur.getString().strip() == ""
        cur = vc.getText().createTextCursorByRange(vc)
        cur.gotoEndOfParagraph(True)
        alone = alone and cur.getString().strip() == ""
        if not vc.isCollapsed() and linear is None:
            linear = vc.getString()
            vc.setString("")
        markup = PLACEHOLDER_MARKUP
        if linear:
            try:
                markup = M.to_starmath(M.from_linear(linear))
            except Exception:
                markup = PLACEHOLDER_MARKUP
        try:
            obj = docapi.insert_formula(m, markup, display=alone)
        except Exception as e:
            self.win.dialogs.message("The equation couldn't be inserted: %s" % e)
            return
        if alone:
            j = self.win.app.settings.get("eq_options", {}).get("justify", "centered")
            try:
                obj.getAnchor().ParaAdjust = {"left": 0, "right": 1}.get(j, 3)
            except Exception:
                pass
        self.ed.start(obj)
        if linear and markup == PLACEHOLDER_MARKUP:
            self.ed.load_linear(linear)

    def edit(self, obj, linear=None, click=None):
        self.ed.start(obj, click=click)
        if linear:
            self.ed.load_linear(linear)

    def close(self, commit=True, move_cursor=True):
        self.ed.stop(move_cursor=move_cursor)

    def finish(self, cursor="after"):
        obj = self.ed.obj
        self.ed.stop(move_cursor=cursor is not None)
        if getattr(self.win.engine, "native", False):
            if cursor == "before" and obj is not None:
                self.win.engine.ed.caret_by_math(obj.id, False)
                self.win.engine.view.after_move()
            self.win.focus_document()
            return
        if cursor == "before" and obj is not None:
            try:
                vc = docapi.view_cursor(self.win.engine.model)
                vc.gotoRange(obj.getAnchor().getStart(), False)
            except Exception:
                pass
        self.win.focus_document()

    # -------------------------------------------------------------- ribbon
    def insert(self, linear):
        """Insert a structure or symbol (from the Equation tab)."""
        if not self.ed.active:
            self.new_equation(linear if SLOT not in linear else None)
            if SLOT not in linear or not self.ed.active:
                return
        self.ed.insert_linear(linear)
        self.win.focus_document()

    def set_input(self, fmt):
        """Unicode or LaTeX linear format."""
        self.input_format = fmt
        self.win.app.settings["eq_input"] = fmt
        self.win.app.save_settings()
        self.sync_input_buttons()

    def sync_input_buttons(self):
        self.win.ribbon.update("folio:eq-unicode", "true" if self.input_format == "unicode"
                              else "false")
        self.win.ribbon.update("folio:eq-latex", "true" if self.input_format == "latex"
                              else "false")
        self.win.ribbon.update("folio:eq-text", "true" if self.normal_text else "false")

    def convert(self, how):
        """Convert > Current - Professional / Linear; Normal Text."""
        if how == "text":
            # Normal Text toggles: what you type next is plain text in the equation
            self.normal_text = not self.normal_text
            self.sync_input_buttons()
            if self.ed.active and self.ed.mode == "professional":
                ed = self.ed
                seq, i = ed.caret
                if ed.anchor is not None and ed.anchor != i:
                    ed.remember()
                    a, z = sorted((ed.anchor, i))
                    for k in range(a, z):
                        it = seq.items[k]
                        if hasattr(it, "kind") and it.kind in ("ident", "num", "op", "sym"):
                            it.kind = "text"
                    ed.changed()
            self.win.focus_document()
            return
        if not self.ed.active and getattr(self.win.engine, "native", False):
            self.win.dialogs.message("Click in an equation first.")
            return
        if not self.ed.active:
            m = self.win.engine.model
            obj = docapi.selected_formula_object(m) if m else None
            if obj is None:
                self.win.dialogs.message("Click in an equation first.")
                return
            self.ed.start(obj)
        if how == "professional":
            self.ed.to_professional()
        elif how == "linear":
            self.ed.to_linear_mode()
        self.win.focus_document()

    def convert_all(self, how):
        """Convert > All - Professional / Linear."""
        if getattr(self.win.engine, "native", False):
            from .native import equations
            n = equations.convert_all(self, how)
            self.win.status.flash("Converted %d equation%s." % (n, "" if n == 1 else "s"))
            return
        from .mathedit import is_linear_markup, linear_markup, linear_of_markup
        m = self.win.engine.model
        if m is None:
            return
        if self.ed.active:
            self.finish()
        n = 0
        for obj in docapi.formulas(m):
            mk = docapi.formula_of(obj) or ""
            try:
                if how == "linear" and not is_linear_markup(mk):
                    tree = M.from_starmath(mk)
                    lin = M.to_latex(tree) if self.input_format == "latex" else M.to_linear(tree)
                    docapi.set_formula(obj, linear_markup(lin))
                    n += 1
                elif how == "professional" and is_linear_markup(mk):
                    lin = linear_of_markup(mk)
                    tree = M.from_latex(lin) if self.input_format == "latex" else \
                        M.from_linear(unicodemath.expand_control_words(lin, final=True))
                    docapi.set_formula(obj, M.to_starmath(tree))
                    n += 1
            except Exception as e:
                print("convert:", e)
        self.win.status.flash("Converted %d equation%s." % (n, "" if n == 1 else "s"))

    def set_display(self, display):
        """Change to Display (own centred line) / Change to Inline."""
        obj = self.ed.obj
        if getattr(self.win.engine, "native", False):
            from .native import equations
            equations.set_display(self, display)
            return
        m = self.win.engine.model
        if obj is None or m is None:
            return
        um = m.getUndoManager()
        um.enterUndoContext("Change Equation Display")
        try:
            anchor = obj.getAnchor()
            text = anchor.getText()
            if display:
                cur = text.createTextCursorByRange(anchor.getStart())
                cur.gotoStartOfParagraph(True)
                if cur.getString().strip():
                    text.insertControlCharacter(anchor.getStart(), 0, False)
                cur = text.createTextCursorByRange(obj.getAnchor().getStart())
                cur.goRight(1, False)
                end = text.createTextCursorByRange(cur)
                end.gotoEndOfParagraph(True)
                if end.getString().strip():
                    text.insertControlCharacter(cur, 0, False)
                obj.getAnchor().ParaAdjust = 3
            else:
                obj.getAnchor().ParaAdjust = 0
        finally:
            um.leaveUndoContext()
        self.ed.changed()
        GLib.timeout_add(150, lambda: (self.ed._locate(), False)[1])

    def justify(self, how):
        obj = self.ed.obj
        if obj is None:
            return
        try:
            obj.getAnchor().ParaAdjust = {"left": 0, "right": 1, "centered": 3,
                                          "group": 3}[how]
        except Exception:
            pass
        GLib.timeout_add(150, lambda: (self.ed._locate(), False)[1])

    def options_menu(self, event):
        """The equation's drop-down tab (and its right-click menu)."""
        ed = self.ed
        menu = Gtk.Menu()

        def item(label, cb, check=None, sensitive=True):
            if check is None:
                mi = Gtk.MenuItem(label=label)
            else:
                mi = Gtk.CheckMenuItem(label=label)
                mi.set_active(check)
                mi.set_draw_as_radio(True)
            mi.set_sensitive(sensitive)
            mi.connect("activate", lambda *_: GLib.idle_add(lambda: (cb(), False)[1]))
            menu.append(mi)
            return mi
        if event.button == 3:
            item("Cut", lambda: (ed.copy(cut=True)))
            item("Copy", lambda: ed.copy())
            item("Paste", lambda: ed.paste())
            menu.append(Gtk.SeparatorMenuItem())
            for group in ed.structure_menu():
                for label, cb, _st in group:
                    item(label, cb)
                menu.append(Gtk.SeparatorMenuItem())
        item("Professional", lambda: self.convert("professional"),
             check=ed.mode == "professional")
        item("Linear", lambda: self.convert("linear"), check=ed.mode == "linear")
        menu.append(Gtk.SeparatorMenuItem())
        disp = ed._display()
        item("Change to Inline" if disp else "Change to Display",
             lambda: self.set_display(not disp))
        jm = Gtk.MenuItem(label="Justification")
        sub = Gtk.Menu()
        cur = None
        try:
            cur = {0: "left", 1: "right", 3: "centered"}.get(int(ed.obj.getAnchor().ParaAdjust))
        except Exception:
            pass
        for key, label in (("left", "Left"), ("right", "Right"), ("centered", "Centered"),
                           ("group", "Centered as Group")):
            mi = Gtk.CheckMenuItem(label=label)
            mi.set_draw_as_radio(True)
            mi.set_active(cur == key)
            mi.set_sensitive(disp)
            mi.connect("activate", lambda _m, k=key: self.justify(k))
            sub.append(mi)
        jm.set_submenu(sub)
        menu.append(jm)
        menu.append(Gtk.SeparatorMenuItem())
        item("Save as New Equation...", lambda: self.save_to_gallery())
        menu.show_all()
        menu.attach_to_widget(self.win.engine.view, None)
        menu.popup_at_pointer(event)

    def save_to_gallery(self):
        lin = self.ed.linear_text() if self.ed.active else ""
        if self.ed.active and self.ed.mode == "professional":
            lin = M.to_linear(self.ed.root)
        if not lin:
            m = self.win.engine.model
            obj = docapi.selected_formula_object(m) if m else None
            if obj is None:
                self.win.dialogs.message("Select an equation first.")
                return
            lin = starmath.to_linear_text(docapi.formula_of(obj) or "")
        name = self.win.dialogs.ask_text("Create New Building Block", "Name:", lin[:30])
        if name:
            self.win.app.settings.setdefault("user_equations", []).append((name, lin))
            self.win.app.save_settings()

    def options_dialog(self):
        from . import eqoptions
        eqoptions.dialog(self.win)

    def ink_equation(self):
        from . import inkmath
        inkmath.dialog(self.win)


class _EntryShim:
    """The old bar's entry, for scripts: the equation as linear text."""
    def __init__(self, bar):
        self.bar = bar

    def get_text(self):
        ed = self.bar.ed
        return ed.linear_text() if ed.active else ""

    def set_text(self, text):
        if self.bar.ed.active:
            self.bar.ed.load_linear(text)

    def has_focus(self):
        return self.bar.ed.active

    def grab_focus(self):
        pass

    def set_position(self, *_a):
        pass
