"""The search box in the title bar (Alt+Q), as in the original: suggestions
appear as you type - commands from every tab and their menus, matched word
by word ("insert table", "page num", "landscape") and forgiving small typos -
plus searching the document and help. Clicking into the empty box offers the
recently used actions."""
import difflib
import re

from gi.repository import Gdk, GLib, Gtk

WORD = re.compile(r"[a-z0-9]+")


def _clean(s):
    return (s or "").replace("\n", " ").replace("_", "").replace("...", "").replace("…", "").strip()


class SearchBox:
    def __init__(self, win, entry):
        self.win = win
        self.entry = entry
        self.index = None
        self.pop = None
        self.rows = []
        self.sel = 0
        self._timer = 0
        entry.connect("search-changed", self._changed)
        entry.connect("key-press-event", self._key)
        entry.connect("focus-in-event", lambda *_: (setattr(self, "index", None),
                                                   GLib.idle_add(self._show_recent), False)[2])
        entry.connect("focus-out-event", lambda *_: (GLib.timeout_add(200, self._maybe_close),
                                                    False)[1])

    # ------------------------------------------------------------ index
    def build(self):
        out = []
        seen = set()
        for c in self.win.ribbon.controls:
            tab = getattr(c, "tab_name", "") or ""
            if tab.startswith("Custom:"):
                continue
            label = _clean(getattr(c, "label", "")) or \
                _clean((getattr(c, "tooltip_text", "") or "").split(" (")[0])
            tip = getattr(c, "tooltip_text", "") or ""
            if label and (tab, label) not in seen:
                seen.add((tab, label))
                out.append((label, tab, "%s %s %s" % (label, tab, tip),
                            (lambda c=c: c.press() if hasattr(c, "press") else c.run())))
            items = getattr(c, "menu", None)
            if isinstance(items, (list, tuple)) and label:
                for it in items:
                    if it is None or isinstance(it, Gtk.Widget) or it[0] == "#" or \
                            not callable(it[1]):
                        continue
                    il = _clean(it[0].split("  (")[0])
                    if not il or (label, il) in seen:
                        continue
                    seen.add((label, il))
                    out.append(("%s: %s" % (label, il), tab, "%s %s %s" % (il, label, tab),
                                it[1]))
        self.index = [(d, t, set(WORD.findall(h.lower())), fn) for d, t, h, fn in out]

    @staticmethod
    def _tok_score(q, words):
        if q in words:
            return 3
        if any(w.startswith(q) for w in words):
            return 2
        if len(q) >= 4 and difflib.get_close_matches(q, words, n=1, cutoff=0.8):
            return 1
        return 0

    def find(self, text, limit=8):
        if self.index is None:
            self.build()
        qs = WORD.findall(text.lower())
        if not qs:
            return []
        hidden = set()
        for t in self.win.ribbon.tabs:
            if t.contextual and not (t.button and t.button.get_visible()):
                hidden.add(t.name)
        scored = []
        for disp, tab, words, fn in self.index:
            total = 0
            for q in qs:
                s = self._tok_score(q, words)
                if not s:
                    break
                total += s
            else:
                head = WORD.findall(disp.lower())
                if head and head[0].startswith(qs[-1]):
                    total += 1
                if all(any(h.startswith(q) for h in head) for q in qs):
                    total += 3          # the command's own name matches
                if tab in hidden:
                    total -= 3          # a tab that isn't showing right now
                scored.append((-total, len(disp), disp, tab, fn))
        scored.sort(key=lambda r: (r[0], r[1]))
        return [(d, t, fn) for _s, _l, d, t, fn in scored[:limit]]

    # ------------------------------------------------------------ popup
    def _changed(self, *_):
        if self._timer:
            GLib.source_remove(self._timer)
        self._timer = GLib.timeout_add(120, self._refresh)

    def _refresh(self):
        self._timer = 0
        text = self.entry.get_text().strip()
        if not text:
            self._show_recent()
            return False
        hits = self.find(text)
        rows = [("Actions", None)] + [("%s" % d, (fn, d, t)) for d, t, fn in hits]
        if not hits:
            rows.append(("No actions match “%s”" % text, None))
        rows += [("", None),
                 ("Find “%s” in Document" % text,
                  (lambda: self.win.dialogs.find_pane(text), None, None)),
                 ("Get Help on “%s”" % text, (lambda: self.win.dialogs.help(text), None, None))]
        self._show(rows)
        return False

    def _show_recent(self):
        if self.entry.get_text().strip() or not self.entry.has_focus():
            return False
        recent = self.win.app.settings.get("search_recent", [])
        if self.index is None:
            self.build()
        byname = {d: (fn, d, t) for d, t, _w, fn in self.index}
        rows = [(d, byname[d]) for d in recent if d in byname]
        if rows:
            self._show([("Recently Used Actions", None)] + rows)
        return False

    def _show(self, rows):
        if self.pop is None:
            self.pop = Gtk.Popover.new(self.entry)
            self.pop.set_modal(False)
            self.pop.set_position(Gtk.PositionType.BOTTOM)
            self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin=4)
            self.box.set_size_request(320, -1)
            self.pop.add(self.box)
        for c in self.box.get_children():
            self.box.remove(c)
        self.rows = []
        for label, act in rows:
            if act is None:
                if label:
                    h = Gtk.Label(xalign=0)
                    h.set_markup("<b>%s</b>" % GLib.markup_escape_text(label))
                    h.set_margin_start(8)
                    h.set_margin_top(4)
                    self.box.pack_start(h, False, False, 0)
                else:
                    self.box.pack_start(Gtk.Separator(), False, False, 3)
                continue
            b = Gtk.Button()
            b.set_relief(Gtk.ReliefStyle.NONE)
            row = Gtk.Box(spacing=8)
            row.pack_start(Gtk.Label(label=label, xalign=0), True, True, 0)
            if act[2]:
                tl = Gtk.Label(label=act[2], xalign=1)
                tl.get_style_context().add_class("dim-label")
                row.pack_end(tl, False, False, 0)
            b.add(row)
            b.connect("clicked", lambda _b, a=act: self._run(a))
            self.box.pack_start(b, False, False, 0)
            self.rows.append((b, act))
        self.sel = 0
        self._mark()
        self.box.show_all()
        self.pop.popup()

    def _mark(self):
        for i, (b, _a) in enumerate(self.rows):
            ctx = b.get_style_context()
            if i == self.sel:
                ctx.add_class("folio-search-current")
            else:
                ctx.remove_class("folio-search-current")

    def _maybe_close(self):
        if self.pop is not None and not self.entry.has_focus():
            focus = self.win.get_focus()
            if focus is None or not focus.is_ancestor(self.pop):
                self.pop.popdown()
        return False

    def close(self):
        if self.pop is not None:
            self.pop.popdown()

    def _run(self, act):
        fn, disp, _tab = act
        self.close()
        self.entry.set_text("")
        if disp:
            rec = [d for d in self.win.app.settings.get("search_recent", []) if d != disp]
            self.win.app.settings["search_recent"] = [disp] + rec[:4]
        self.win.focus_document()
        GLib.idle_add(lambda: (fn(), False)[1])

    def _key(self, entry, ev):
        k = ev.keyval
        if k == Gdk.KEY_Escape:
            self.close()
            entry.set_text("")
            self.win.focus_document()
            return True
        if not self.rows or self.pop is None or not self.pop.get_visible():
            if k in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
                self._refresh()
                if self.rows:
                    self._run(self.rows[0][1])
                return True
            return False
        if k == Gdk.KEY_Down:
            self.sel = min(len(self.rows) - 1, self.sel + 1)
            self._mark()
            return True
        if k == Gdk.KEY_Up:
            self.sel = max(0, self.sel - 1)
            self._mark()
            return True
        if k in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self._run(self.rows[self.sel][1])
            return True
        return False
