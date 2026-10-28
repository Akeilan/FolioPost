"""KeyTips: Alt (tap) or F10 shows letters on the ribbon tabs; typing a
tab's letter opens it and shows letters on its controls; typing a control's
letters presses it. Esc steps back; any click leaves."""
from gi.repository import Gdk, GLib, Gtk

TAB_TIPS = {"Home": "H", "Insert": "N", "Draw": "JI", "Design": "G", "Layout": "P",
            "References": "S", "Mailings": "M", "Review": "R", "View": "W",
            "Help": "Y", "Table Design": "JT", "Table Layout": "JL",
            "Picture Format": "JP", "Outlining": "U"}


class KeyTips:
    def __init__(self, win):
        self.win = win
        self.active = False
        self.level = 0
        self.buffer = ""
        self.targets = {}
        self.badges = []
        self.layer = Gtk.Fixed()
        self.layer.set_halign(Gtk.Align.FILL)
        self.layer.set_valign(Gtk.Align.FILL)
        win.overlay.add_overlay(self.layer)
        win.overlay.set_overlay_pass_through(self.layer, True)
        self.layer.show()

    # ------------------------------------------------------------ badges
    def _clear(self):
        for b in self.badges:
            if isinstance(b, Gtk.Popover):
                b.popdown()
                b.destroy()
            else:
                self.layer.remove(b)
        self.badges = []

    def _pop_badge(self, widget, tip):
        """Badges for widgets outside the content area (title bar)."""
        pop = Gtk.Popover.new(widget)
        pop.set_position(Gtk.PositionType.BOTTOM)
        pop.set_modal(False)
        pop.get_style_context().add_class("folio-keytip-pop")
        lab = Gtk.Label(label=tip)
        lab.get_style_context().add_class("folio-keytip")
        pop.add(lab)
        lab.show()
        pop.popup()
        self.badges.append(pop)

    def _badge(self, widget, tip, below=False):
        if not widget.get_mapped():
            return
        alloc = widget.get_allocation()
        res = widget.translate_coordinates(self.win.outer, 0, 0)
        if not res:
            return
        x, y = res
        lab = Gtk.Label(label=tip)
        lab.get_style_context().add_class("folio-keytip")
        lab.show()
        bw = 10 + 7 * len(tip)
        bx = x + max(0, (alloc.width - bw) // 2)
        by = y + alloc.height - 12 if below else y + max(0, alloc.height - 16)
        self.layer.put(lab, bx, by)
        self.badges.append(lab)

    def _filter(self):
        for b in self.badges:
            lab = b.get_child() if isinstance(b, Gtk.Popover) else b
            b.set_visible(lab.get_text().startswith(self.buffer))

    # ------------------------------------------------------------ levels
    def start(self):
        self.leave()
        self.active = True
        self.level = 1
        self.buffer = ""
        self.targets = {}
        r = self.win.ribbon
        self.targets["F"] = ("file", None)
        self._badge(r.file_button, "F", below=True)
        for t in r.tabs:
            if not t.button.get_visible():
                continue
            tip = t.keytip or TAB_TIPS.get(t.name)
            if tip:
                self.targets[tip] = ("tab", t)
                self._badge(t.button, tip, below=True)
        # quick access toolbar: 1, 2, 3 ...
        for i, b in enumerate([c for c in self.win.qat.get_children() if not isinstance(c, Gtk.MenuButton)], start=1):
            self.targets[str(i)] = ("button", b)
            self._pop_badge(b, str(i))
        return True

    def start_with(self, letter):
        self.start()
        if not any(t.startswith(letter) for t in self.targets):
            self.leave()
            return False
        self._typed(letter)
        return True

    def show_tab(self, tab):
        self._clear()
        self.level = 2
        self.buffer = ""
        self.targets = {}
        self.win.ribbon.select(tab)

        def place():
            used = set()
            for c in tab.controls:
                tip = getattr(c, "keytip", None)
                if not tip or tip in used or not c.get_mapped():
                    continue
                used.add(tip)
                self.targets[tip] = ("control", c)
                self._badge(c, tip)
            # groups folded into one button on narrow windows: Z + letter
            for g in getattr(tab, "groups", []):
                if not getattr(g, "collapsed", False) or g.compact is None:
                    continue
                base = "Z" + (g.caption[:1].upper() or "X")
                tip, n = base, 1
                while tip in used:
                    n += 1
                    tip = "Z" + str(n)
                used.add(tip)
                self.targets[tip] = ("group", (tab, g))
                self._badge(g.compact, tip)
            return False
        GLib.idle_add(place)

    def show_group(self, tab, group):
        """Open a folded group and show KeyTips for the controls inside it."""
        self._clear()
        self.level = 3
        self.buffer = ""
        self.targets = {}
        group.open_compact()

        def place():
            used = set()
            for c in tab.controls:
                tip = getattr(c, "keytip", None)
                if not tip or tip in used or not c.get_mapped() or not c.is_ancestor(group.body):
                    continue
                used.add(tip)
                self.targets[tip] = ("control", c)
                self._pop_badge(c, tip)
            return False
        GLib.timeout_add(150, place)

    def leave(self):
        self.active = False
        self.level = 0
        self.buffer = ""
        self.targets = {}
        self._clear()

    # ------------------------------------------------------------ keys
    def key(self, event):
        kv = event.keyval
        name = (Gdk.keyval_name(kv) or "").lower()
        if name in ("alt_l", "alt_r", "shift_l", "shift_r", "control_l", "control_r"):
            return True
        if kv == Gdk.KEY_Escape:
            if self.level == 3:
                for g in getattr(self.win.ribbon.current, "groups", []):
                    if getattr(g, "_pop", None) is not None:
                        g._pop.popdown()
                self.show_tab(self.win.ribbon.current)
            elif self.level == 2:
                self.start()
            else:
                self.leave()
                self.win.focus_document()
            return True
        if kv == Gdk.KEY_BackSpace:
            self.buffer = self.buffer[:-1]
            self._filter()
            return True
        ch = Gdk.keyval_to_unicode(Gdk.keyval_to_upper(kv))
        ch = chr(ch).upper() if ch else ""
        if not ch or not ch.isalnum():
            self.leave()
            return False
        self._typed(ch)
        return True

    def _typed(self, ch):
        self.buffer += ch
        hit = self.targets.get(self.buffer)
        if hit is None:
            if any(t.startswith(self.buffer) for t in self.targets):
                self._filter()
            else:
                self.buffer = self.buffer[:-1]
            return
        kind, obj = hit
        if kind == "tab":
            self.show_tab(obj)
        elif kind == "group":
            self.show_group(*obj)
        elif kind == "file":
            self.leave()
            self.win.show_backstage()
        elif kind == "button":
            self.leave()
            obj.clicked()
        else:
            self.leave()
            GLib.idle_add(lambda: (obj.press(), False)[1])
