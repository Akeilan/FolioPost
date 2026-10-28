"""The ribbon: tabs of captioned groups of buttons, all owned by the app.

One module for Folio Writer, Sheets, Deliver and Post (X2-02). The copy in folio-suite/shared
is the one to change; folio-suite/tools/sync_shared.sh copies it into each app, and
sync_shared.sh --check fails when an app's copy differs.

Every control registers:
  * the command it runs (an engine command like '.uno:Bold' or an app
    action name like 'font-dialog'),
  * optionally a state key whose value checks/updates it,
  * a KeyTip.
"""
from gi.repository import Gdk, GLib, GObject, Gtk, Pango

from . import icons


def _label(text, cls=None):
    lab = Gtk.Label(label=text)
    if cls:
        lab.get_style_context().add_class(cls)
    return lab


# ---------------------------------------------------------------- popovers
def _recorder(widget):
    """The window's macro recorder, if a macro is being recorded."""
    try:
        top = widget.get_toplevel() if widget is not None else None
        return getattr(top, "macro_recorder", None)
    except Exception:
        return None


def menu_popover(relative_to, items, on_pick=None):
    """items: list of (label, callback[, icon]) | None (separator) |
    ('#', heading) | Gtk.Widget. Returns a Gtk.Popover."""
    pop = Gtk.Popover.new(relative_to)
    pop.set_position(Gtk.PositionType.BOTTOM)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
    box.set_margin_top(4)
    box.set_margin_bottom(4)
    for it in items:
        if it is None:
            box.pack_start(Gtk.Separator(), False, False, 3)
            continue
        if isinstance(it, Gtk.Widget):
            # a widget shown in an earlier menu moves to this one
            if it.get_parent() is not None:
                it.get_parent().remove(it)
            box.pack_start(it, False, False, 0)
            continue
        if it[0] == "#":
            lab = Gtk.Label(xalign=0)
            lab.set_markup("<b>%s</b>" % GLib.markup_escape_text(it[1]))
            lab.set_margin_start(10)
            lab.set_margin_top(4)
            lab.set_margin_bottom(2)
            box.pack_start(lab, False, False, 0)
            continue
        label, cb = it[0], it[1]
        if isinstance(cb, list):
            # a submenu: opens beside its entry
            b = Gtk.Button()
            b.set_relief(Gtk.ReliefStyle.NONE)
            inner = Gtk.Box(spacing=8)
            inner.pack_start(Gtk.Label(label=label, xalign=0), True, True, 0)
            inner.pack_end(Gtk.Label(label="›"), False, False, 0)
            b.add(inner)
            b.submenu_items = cb

            def open_sub(btn, items=cb):
                sub = menu_popover(btn, items)
                sub.set_position(Gtk.PositionType.RIGHT)
                sub.connect("closed", lambda *_: pop.popdown())
                sub.popup()
            b.connect("clicked", open_sub)
            box.pack_start(b, False, False, 0)
            continue
        icon = it[2] if len(it) > 2 else None
        b = Gtk.Button()
        b.set_relief(Gtk.ReliefStyle.NONE)
        inner = Gtk.Box(spacing=8)
        if icon is not None:
            if isinstance(icon, Gtk.Widget):
                inner.pack_start(icon, False, False, 0)
            else:
                inner.pack_start(icons.image(icon, 16), False, False, 0)
        lab = Gtk.Label(label=label, xalign=0)
        inner.pack_start(lab, True, True, 0)
        b.add(inner)

        def clicked(_b, cb=cb, label=label):
            pop.popdown()
            if cb:
                rec = _recorder(relative_to)
                if rec is not None and rec.active:
                    rec.menu(relative_to, label)

                    def go():
                        rec.suspended = True
                        try:
                            cb()
                        finally:
                            rec.suspended = False
                        return False
                    GLib.idle_add(go)
                else:
                    GLib.idle_add(lambda: (cb(), False)[1])
        b.connect("clicked", clicked)
        box.pack_start(b, False, False, 0)
    box.show_all()
    pop.add(box)
    return pop


# ---------------------------------------------------------------- controls
class Control:
    """Mixin: command, state binding and keytip."""
    def setup(self, ribbon, action, state=None, keytip=None, tooltip=None,
              enable_key=None):
        self.ribbon = ribbon
        self.action = action
        self.state_key = state
        self.enable_key = enable_key or (action if isinstance(action, str) and
                                         action.startswith(".uno:") else None)
        self.keytip = keytip
        self._updating = False
        self.tooltip_text = " ".join((tooltip or "").split())
        if tooltip:
            from .screentips import markup
            mk = markup(tooltip)
            if mk:
                self.set_tooltip_markup(mk)
            else:
                self.set_tooltip_text(self.tooltip_text)
        ribbon.register(self)

    def run(self, *args):
        if self._updating:
            return
        self.ribbon.current_control = self
        try:
            self.ribbon.run(self.action)
        finally:
            self.ribbon.current_control = None

    def press(self):
        """KeyTip activation."""
        self.run()

    def update(self, key, value):
        if key == self.enable_key and value in ("enabled", "disabled"):
            self.set_sensitive(value == "enabled")
        if key == self.state_key:
            self.apply_state(value)

    def apply_state(self, value):
        pass


class RibbonButton(Gtk.Button, Control):
    """size: 'large' (icon above label), 'small' (icon + label), 'icon'."""
    def __init__(self, ribbon, label, icon, action, size="small", state=None,
                 keytip=None, tooltip=None, toggle=False):
        Gtk.Button.__init__(self)
        self.toggle = toggle
        self.icon_name = icon
        self.label = label
        self.get_style_context().add_class("folio-btn")
        self.get_style_context().add_class(size)
        self.set_focus_on_click(False)
        if size == "large":
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            box.pack_start(icons.image(icon, 32), False, False, 0)
            lab = Gtk.Label(label=label)
            lab.set_justify(Gtk.Justification.CENTER)
            lab.set_line_wrap(True)
            lab.set_max_width_chars(10)
            box.pack_start(lab, False, False, 0)
            self.label_widget = lab
            self.add(box)
        elif size == "small":
            box = Gtk.Box(spacing=4)
            box.pack_start(icons.image(icon, 16), False, False, 0)
            if label:
                box.pack_start(Gtk.Label(label=label, xalign=0), False, False, 0)
            self.add(box)
        else:
            self.add(icons.image(icon, 16))
        self.setup(ribbon, action, state=state, keytip=keytip,
                   tooltip=tooltip or label)
        self.connect("clicked", self.run)

    def apply_state(self, value):
        on = value == "true"
        ctx = self.get_style_context()
        if on:
            ctx.add_class("checked")
        else:
            ctx.remove_class("checked")

    def set_label_text(self, text):
        """A command whose name follows its state (Protect Sheet / Unprotect Sheet)."""
        lab = getattr(self, "label_widget", None)
        if lab is not None:
            lab.set_text(text)
        self.label = text
        self.set_tooltip_text(" ".join(text.split()))


class SplitButton(Gtk.Box, Control):
    """A button with a drop-down arrow. `menu` is a list for menu_popover or
    a callable returning a widget for a custom popover."""
    def __init__(self, ribbon, label, icon, action, menu, size="small",
                 state=None, keytip=None, tooltip=None, icon_widget=None):
        orient = Gtk.Orientation.VERTICAL if size == "large" else Gtk.Orientation.HORIZONTAL
        Gtk.Box.__init__(self, orientation=orient, spacing=0)
        self.get_style_context().add_class("folio-split")
        self.menu = menu
        self.icon_name = icon
        self.label = label
        self.main = Gtk.Button()
        self.main.get_style_context().add_class("folio-btn")
        self.main.get_style_context().add_class(size)
        self.main.set_focus_on_click(False)
        img = icon_widget or icons.image(icon, 32 if size == "large" else 16)
        self.icon_widget = img
        if size == "large":
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            inner.pack_start(img, False, False, 0)
            self.main.add(inner)
            self.arrow = Gtk.Button()
            ab = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            lab = Gtk.Label(label=label)
            ab.pack_start(lab, False, False, 0)
            ab.pack_start(icons.image("chevron", 12),
                          False, False, 0)
            self.arrow.add(ab)
        else:
            inner = Gtk.Box(spacing=4)
            inner.pack_start(img, False, False, 0)
            if label:
                inner.pack_start(Gtk.Label(label=label), False, False, 0)
            self.main.add(inner)
            self.arrow = Gtk.Button()
            self.arrow.add(icons.image("chevron", 12))
        self.arrow.get_style_context().add_class("folio-btn")
        self.arrow.get_style_context().add_class("arrow")
        self.arrow.set_focus_on_click(False)
        self.pack_start(self.main, False, False, 0)
        self.pack_start(self.arrow, False, False, 0)
        self.setup(ribbon, action, state=state, keytip=keytip, tooltip=tooltip or label)
        self.main.connect("clicked", self.run)
        self.arrow.connect("clicked", lambda *_: self.open_menu())

    def set_swatch(self, color):
        """Recolour the icon's colour bar (Fill Color, Font Color)."""
        if color is None or not isinstance(self.icon_widget, Gtk.Image):
            return
        pb = icons.swatch_pixbuf(self.icon_name, 16, color)
        if pb is not None:
            self.icon_widget.set_from_pixbuf(pb)
        self.swatch = color

    def open_menu(self):
        if callable(self.menu):
            content = self.menu()
            if isinstance(content, Gtk.Popover):
                pop = content
                pop.set_relative_to(self)
            else:
                pop = Gtk.Popover.new(self)
                content.show_all()
                pop.add(content)
        else:
            pop = menu_popover(self, self.menu)
        pop.set_position(Gtk.PositionType.BOTTOM)
        pop.popup()
        return pop

    def press(self):
        # KeyTips open the menu of split buttons whose main part is a menu
        if self.action is None:
            self.open_menu()
        else:
            self.run()

    def apply_state(self, value):
        ctx = self.main.get_style_context()
        if value == "true":
            ctx.add_class("checked")
        else:
            ctx.remove_class("checked")


class MenuButton(SplitButton):
    """Whole button opens the menu (no separate default action)."""
    def __init__(self, ribbon, label, icon, menu, size="large", keytip=None,
                 tooltip=None, state=None):
        SplitButton.__init__(self, ribbon, label, icon, None, menu, size=size,
                             keytip=keytip, tooltip=tooltip, state=state)
        self.main.disconnect_by_func(self.run)
        self.main.connect("clicked", lambda *_: self.open_menu())

    def run(self, *args):
        self.open_menu()


class ComboControl(Gtk.ComboBoxText, Control):
    def __init__(self, ribbon, items, action_fn, width_chars, state=None,
                 keytip=None, tooltip=None, display=None):
        Gtk.ComboBoxText.__init__(self, has_entry=True)
        self.get_style_context().add_class("folio-combo")
        self.display = display or (lambda v: v)
        self.action_fn = action_fn
        entry = self.get_child()
        entry.set_width_chars(width_chars)
        self.set_items(items)
        self.setup(ribbon, None, state=state, keytip=keytip, tooltip=tooltip)
        self.connect("changed", self._changed)
        entry.connect("activate", self._activate)
        self.preview = None          # text -> apply(model), for Live Preview
        self.connect("notify::popup-shown", self._popup_shown)

    def _popup_shown(self, *_):
        win = self.get_toplevel()
        lp = getattr(win, "live_preview", None)
        if lp is None or self.preview is None:
            return
        if not self.get_property("popup-shown"):
            lp.unhover()
            return
        GLib.idle_add(self._hook_menu, lp)

    def _hook_menu(self, lp):
        """Each name in the open list previews while highlighted."""
        for top in Gtk.Window.list_toplevels():
            if not top.get_visible():
                continue
            for menu in _walk(top):
                if isinstance(menu, Gtk.Menu) and menu.get_attach_widget() is self:
                    model = self.get_model()
                    items = [c for c in menu.get_children() if isinstance(c, Gtk.MenuItem)]
                    for i, mi in enumerate(items):
                        if getattr(mi, "_lp_hooked", False) or i >= len(model):
                            continue
                        mi._lp_hooked = True
                        text = model[i][0]
                        mi.connect("select", lambda _m, t=text: self._prev(lp, t))
                        mi.connect("deselect", lambda *_: lp.unhover())
                    return False
        return False

    def _prev(self, lp, text):
        fn = self.preview(text) if self.preview else None
        if fn is not None:
            lp.hover(("combo", id(self), text), fn)

    def set_items(self, items):
        self._updating = True
        self.remove_all()
        for it in items:
            self.append_text(it)
        self._updating = False

    def _changed(self, combo):
        if self._updating:
            return
        lp = getattr(self.get_toplevel(), "live_preview", None)
        if lp is not None:
            lp.commit()
        if self.get_active() >= 0:
            self.action_fn(self.get_active_text())
            self.ribbon.focus_document()

    def _activate(self, entry):
        text = entry.get_text().strip()
        if text:
            self.action_fn(text)
        self.ribbon.focus_document()

    def press(self):
        entry = self.get_child()
        entry.grab_focus()
        entry.select_region(0, -1)

    def apply_state(self, value):
        self._updating = True
        entry = self.get_child()
        if not entry.has_focus():
            entry.set_text(self.display(value))
        self._updating = False


class CheckControl(Gtk.CheckButton, Control):
    """A ribbon check box (View > Show > Ruler)."""
    def __init__(self, ribbon, label, action, active=False, state=None, keytip=None,
                 tooltip=None):
        Gtk.CheckButton.__init__(self, label=label)
        self.get_style_context().add_class("folio-check")
        self.set_focus_on_click(False)
        self.set_active(active)
        self.setup(ribbon, action, state=state, keytip=keytip, tooltip=tooltip or label)
        self.connect("toggled", self.run)

    def set_checked(self, on):
        self._updating = True
        self.set_active(bool(on))
        self._updating = False

    def press(self):
        self.set_active(not self.get_active())

    def apply_state(self, value):
        self.set_checked(value == "true")


class ChoiceControl(Gtk.ComboBoxText, Control):
    """A drop-down list without an entry (Review > Display for Review)."""
    def __init__(self, ribbon, items, action_fn, active=0, keytip=None, tooltip=None):
        Gtk.ComboBoxText.__init__(self)
        self.get_style_context().add_class("folio-choice")
        self.action_fn = action_fn
        for it in items:
            self.append_text(it)
        self.setup(ribbon, None, keytip=keytip, tooltip=tooltip)
        self._updating = True
        self.set_active(active)
        self._updating = False
        self.connect("changed", self._changed)

    def _changed(self, combo):
        if not self._updating and self.get_active() >= 0:
            self.action_fn(self.get_active_text())
            self.ribbon.focus_document()

    def press(self):
        self.popup()


# ---------------------------------------------------------------- layout
def _walk(w):
    yield w
    if isinstance(w, Gtk.Container):
        for c in w.get_children():
            yield from _walk(c)


class Group(Gtk.Box):
    """A captioned group. `columns` is a list of widgets or of lists of
    widgets (stacked vertically, up to three per column)."""
    def __init__(self, caption, columns, launcher=None, ribbon=None,
                 launcher_keytip=None):
        Gtk.Box.__init__(self, orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.get_style_context().add_class("folio-group")
        body = Gtk.Box(spacing=2)
        body.set_vexpand(True)
        # three rows at most, as the suite's ribbon has (96 px tall)
        split = []
        for col in columns:
            if isinstance(col, (list, tuple)) and len(col) > 3:
                col = list(col)
                for k in range(0, len(col), 3):
                    split.append(col[k:k + 3])
            else:
                split.append(col)
        columns = split
        for col in columns:
            if isinstance(col, (list, tuple)):
                v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
                v.set_valign(Gtk.Align.CENTER)
                for w in col:
                    if isinstance(w, (list, tuple)):
                        row = Gtk.Box(spacing=1)
                        for x in w:
                            row.pack_start(x, False, False, 0)
                        v.pack_start(row, False, False, 0)
                    else:
                        if isinstance(w, Gtk.Widget):
                            w.set_halign(Gtk.Align.START)
                        v.pack_start(w, False, False, 0)
                body.pack_start(v, False, False, 0)
            else:
                col.set_valign(Gtk.Align.START if not isinstance(col, Gtk.ComboBox)
                               else Gtk.Align.CENTER)
                body.pack_start(col, False, False, 0)
        self.pack_start(body, True, True, 0)
        # the launcher floats over the caption row so every caption sits on
        # the same baseline, with or without a launcher
        cap_row = Gtk.Overlay()
        cap = _label(caption, "folio-caption")
        cap.set_hexpand(True)
        cap_row.add(cap)
        if launcher and ribbon:
            lb = RibbonButton(ribbon, None, "launcher", launcher, size="icon",
                              keytip=launcher_keytip, tooltip=caption + " Settings")
            lb.get_style_context().add_class("folio-launcher")
            lb.set_halign(Gtk.Align.END)
            lb.set_valign(Gtk.Align.CENTER)
            cap_row.add_overlay(lb)
            cap.set_margin_start(16)
            cap.set_margin_end(16)
        self.pack_end(cap_row, False, False, 0)
        self.set_hexpand(False)     # groups keep their natural width
        self.caption = caption
        self.body = body
        self.cap_row = cap_row
        self.collapsed = False
        self.compact = None
        self._pop = None

    # -- narrow windows: the group folds into one button with a drop-down
    def _first_icon(self):
        found = []

        def walk(w):
            if found:
                return
            if isinstance(w, Gtk.Image) and w.get_pixbuf() is not None:
                found.append(w.get_pixbuf())
            elif isinstance(w, Gtk.Container):
                for ch in w.get_children():
                    walk(ch)
        walk(self.body)
        return found[0] if found else None

    def _make_compact(self):
        b = Gtk.Button()
        b.get_style_context().add_class("folio-btn")
        b.get_style_context().add_class("large")
        b.set_focus_on_click(False)
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        pb = icons.pixbuf("styles", 32) if self.caption == "Styles" else self._first_icon()
        if pb is not None:
            from gi.repository import GdkPixbuf
            if pb.get_width() < 32:
                pb = pb.scale_simple(32, 32, GdkPixbuf.InterpType.BILINEAR)
            v.pack_start(Gtk.Image.new_from_pixbuf(pb), False, False, 0)
        v.pack_start(_label(self.caption), False, False, 0)
        v.pack_start(icons.image("chevron", 12),
                     False, False, 0)
        b.add(v)
        b.set_valign(Gtk.Align.START)
        b.set_tooltip_text(self.caption)
        b.connect("clicked", lambda *_: self.open_compact())
        b.show_all()
        b.set_no_show_all(True)
        self.compact = b
        self.pack_start(b, True, True, 0)

    def open_compact(self):
        pop = Gtk.Popover.new(self.compact)
        pop.set_position(Gtk.PositionType.BOTTOM)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.get_style_context().add_class("folio-ribbon")
        for w in (self.body, self.cap_row):
            self.remove(w)
            box.pack_start(w, w is self.body, w is self.body, 0)
            w.show()
        box.show()
        pop.add(box)

        def closed(*_):
            for w in (self.body, self.cap_row):
                box.remove(w)
                if w is self.body:
                    self.pack_start(w, True, True, 0)
                else:
                    self.pack_end(w, False, False, 0)
                w.set_visible(not self.collapsed)
            pop.destroy()
            self._pop = None
        pop.connect("closed", closed)
        self._pop = pop
        pop.popup()

    def set_collapsed(self, on):
        if on == self.collapsed:
            return
        if self._pop is not None:
            self._pop.popdown()
        if self.compact is None:
            self._make_compact()
        self.collapsed = on
        self.body.set_visible(not on)
        self.cap_row.set_visible(not on)
        self.compact.set_visible(on)

    def press_compact(self):
        if self.collapsed:
            self.open_compact()


class Tab:
    # tabs whose label differs from their name (the original shows the
    # table's layout tab simply as "Layout")
    LABELS = {"Table Layout": "Layout"}

    def __init__(self, name, keytip, contextual=False):
        self.name = name
        self.label = self.LABELS.get(name, name)
        self.keytip = keytip
        self.contextual = contextual
        self.body = Gtk.Box(spacing=0)
        self.body.get_style_context().add_class("folio-ribbon")
        self.controls = []
        self.button = None
        self._groups = 0

    def add(self, group):
        if not hasattr(self, "groups"):
            self.groups = []
        self.groups.append(group)
        if self._groups:
            sep = Gtk.Box()
            sep.get_style_context().add_class("folio-sep")
            self.body.pack_start(sep, False, False, 0)
        self.body.pack_start(group, False, False, 0)
        self._groups += 1


class Ribbon(Gtk.Box):
    __gsignals__ = {
        "file-clicked": (GObject.SignalFlags.RUN_LAST, None, ()),
    }

    def __init__(self, runner, focus_document):
        Gtk.Box.__init__(self, orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.runner = runner              # callable(action)
        self.focus_document = focus_document
        self.controls = []
        self.tabs = []
        self.current = None
        self._building = None
        self.collapsed = False
        self._last_w = 0
        self.connect("size-allocate", self._resized)
        self.set_vexpand(False)       # groups expand inside; the ribbon doesn't

        self.tabbar = Gtk.Box(spacing=0)
        self.tabbar.get_style_context().add_class("folio-tabs")
        self.pack_start(self.tabbar, False, False, 0)
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.NONE)
        self.stack.set_vhomogeneous(True)
        self.stack.set_size_request(-1, 96)
        self.revealer = Gtk.Revealer()
        self.revealer.set_transition_type(Gtk.RevealerTransitionType.NONE)
        self.revealer.add(self.stack)
        self.revealer.set_reveal_child(True)
        self.pack_start(self.revealer, False, False, 0)
        self.file_button = Gtk.Button(label="File")
        self.file_button.set_relief(Gtk.ReliefStyle.NONE)
        self.file_button.get_style_context().add_class("folio-tab")
        self.file_button.get_style_context().add_class("file")
        self.file_button.connect("clicked", lambda *_: self.emit("file-clicked"))
        self.file_button.keytip = "F"
        self.tabbar.pack_start(self.file_button, False, False, 0)
        # Ribbon Display Options
        self.on_display_mode = None
        self.collapse_btn = Gtk.Button()
        self.collapse_btn.set_relief(Gtk.ReliefStyle.NONE)
        self.collapse_btn.add(Gtk.Image.new_from_icon_name("pan-down-symbolic", Gtk.IconSize.MENU))
        self.collapse_btn.set_tooltip_text("Ribbon Display Options")
        self.collapse_btn.connect("clicked", lambda b: self.display_options(b))
        self.tabbar.pack_end(self.collapse_btn, False, False, 0)

    # -- building
    def add_tab(self, tab):
        self.tabs.append(tab)
        b = Gtk.Button(label=getattr(tab, "label", tab.name))
        b.set_relief(Gtk.ReliefStyle.NONE)
        b.set_focus_on_click(False)
        b.get_style_context().add_class("folio-tab")
        if tab.contextual:
            b.get_style_context().add_class("contextual")
            b.set_no_show_all(True)
        b.connect("clicked", lambda *_: self.select(tab))
        tab.button = b
        self.tabbar.pack_start(b, False, False, 0)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        scroller.set_overlay_scrolling(True)
        scroller.add(tab.body)
        self.stack.add_named(scroller, tab.name)
        if self.current is None:
            self.select(tab)

    def building(self, tab):
        self._building = tab
        return tab

    def register(self, control):
        self.controls.append(control)
        if self._building is not None:
            self._building.controls.append(control)
            control.tab_name = self._building.name

    # -- behaviour
    def _resized(self, w, alloc):
        if alloc.width != self._last_w:
            self._last_w = alloc.width
            GLib.idle_add(self.fit)

    def all_controls(self):
        """Controls with a label_text, for the command search box."""
        for c in self.controls:
            if not hasattr(c, "label_text"):
                texts = []

                def walk(w):
                    if isinstance(w, Gtk.Label):
                        texts.append(w.get_text())
                    elif isinstance(w, Gtk.Container):
                        for ch in w.get_children():
                            walk(ch)
                walk(c)
                c.label_text = " ".join(t for t in texts if t).strip() or \
                    (c.tooltip_text or "").split(" (")[0]
        return self.controls

    def select(self, tab):
        if self.current is not None and self.current.button is not None:
            self.current.button.get_style_context().remove_class("active")
        self.current = tab
        tab.button.get_style_context().add_class("active")
        self.stack.set_visible_child_name(tab.name)
        if self.collapsed:
            self.revealer.set_reveal_child(True)
        GLib.idle_add(self.fit)

    def fit(self, *_):
        """Fold groups (right to left) until the tab fits the window."""
        tab = self.current
        if tab is None or not getattr(tab, "groups", None):
            return False
        width = self.get_allocated_width() - 16
        if width <= 50:
            return False
        groups = tab.groups
        for g in groups:
            g.set_collapsed(False)
        galleries = [w for g in groups for w in _walk(g.body)
                     if hasattr(w, "set_visible_count")]
        for gal in galleries:
            gal.set_visible_count(gal.MAX_VISIBLE)
        need = tab.body.get_preferred_width()[1]
        # galleries give up tiles before any group folds
        for gal in galleries:
            while need > width and gal.VISIBLE > gal.MIN_VISIBLE:
                gal.set_visible_count(gal.VISIBLE - 1)
                need = tab.body.get_preferred_width()[1]
        i = len(groups) - 1
        while need > width and i >= 0:
            groups[i].set_collapsed(True)
            need = tab.body.get_preferred_width()[1]
            i -= 1
        return False

    def tab_by_name(self, name):
        for t in self.tabs:
            if t.name == name:
                return t
        return None

    def show_contextual(self, name, show):
        t = self.tab_by_name(name)
        if t is None:
            return
        if show:
            t.button.show()
        else:
            if self.current is t:
                self.select(self.tabs[0])
            t.button.hide()

    def toggle_collapse(self):
        self.collapsed = not self.collapsed
        self.revealer.set_reveal_child(not self.collapsed)

    MODES = [("full", "Full-screen mode",
              "Hide the ribbon for the best reading view. Select the three dots at the "
              "top to show it."),
             ("tabs", "Show tabs only",
              "Show only the ribbon tabs. Select a tab to show its commands."),
             ("always", "Always show Ribbon", "Keep the ribbon always showing.")]

    def display_options(self, btn):
        pop = Gtk.Popover.new(btn)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin=6, spacing=2)
        cur = getattr(self, "display_mode", "tabs" if self.collapsed else "always")
        for key, title, desc in self.MODES:
            b = Gtk.Button()
            b.set_relief(Gtk.ReliefStyle.NONE)
            row = Gtk.Box(spacing=8)
            mark = Gtk.Label(label="✓" if key == cur else "", width_chars=2)
            row.pack_start(mark, False, False, 0)
            txt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            t = Gtk.Label(xalign=0)
            t.set_markup("<b>%s</b>" % title)
            d = Gtk.Label(label=desc, xalign=0)
            d.set_line_wrap(True)
            d.set_max_width_chars(36)
            d.get_style_context().add_class("dim-label")
            txt.pack_start(t, False, False, 0)
            txt.pack_start(d, False, False, 0)
            row.pack_start(txt, True, True, 0)
            b.add(row)
            b.connect("clicked", lambda _b, k=key: (pop.popdown(), self.set_display_mode(k)))
            box.pack_start(b, False, False, 0)
        box.pack_start(Gtk.Separator(), False, False, 4)
        qat_shown = getattr(self, "qat_shown", True)
        q = Gtk.ModelButton(text="Hide Quick Access Toolbar" if qat_shown
                            else "Show Quick Access Toolbar")
        q.connect("clicked", lambda *_: self.on_display_mode and
                  self.on_display_mode("qat", not qat_shown))
        box.pack_start(q, False, False, 0)
        box.show_all()
        pop.add(box)
        pop.popup()

    def set_display_mode(self, mode):
        self.display_mode = mode
        want = mode == "tabs"
        if want != self.collapsed:
            self.toggle_collapse()
        if self.on_display_mode:
            self.on_display_mode("mode", mode)

    def run(self, action):
        if action is not None:
            self.runner(action)
            if self.collapsed:
                self.revealer.set_reveal_child(False)

    def update(self, key, value):
        for c in self.controls:
            if key == c.state_key or key == c.enable_key:
                c.update(key, value)
