"""The desktop clipboard, shared with every other application.

Copying offers the selection as formatted text (HTML) and plain text, so
other programs paste it with or without formatting. Whether the clipboard
still holds our own copy is known from the desktop itself (we are told the
moment another program copies something), so pasting always takes the
newest copy, wherever it was made."""
from gi.repository import Gdk, Gtk

HTML, TEXT = 1, 2


class Clipboard:
    def __init__(self):
        self.owner = Gtk.Invisible()
        self.owner.realize()
        self.html = None
        self.text = ""
        self.owned = False
        sel = Gdk.SELECTION_CLIPBOARD
        targets = [Gtk.TargetEntry.new("text/html", 0, HTML),
                   Gtk.TargetEntry.new("UTF8_STRING", 0, TEXT),
                   Gtk.TargetEntry.new("text/plain;charset=utf-8", 0, TEXT),
                   Gtk.TargetEntry.new("TEXT", 0, TEXT),
                   Gtk.TargetEntry.new("STRING", 0, TEXT),
                   Gtk.TargetEntry.new("text/plain", 0, TEXT)]
        Gtk.selection_add_targets(self.owner, sel, targets)
        self.owner.connect("selection-get", self._get)
        self.owner.connect("selection-clear-event", self._lost)

    def set(self, html, text):
        self.html, self.text = html, text or ""
        ok = Gtk.selection_owner_set(self.owner, Gdk.SELECTION_CLIPBOARD, Gdk.CURRENT_TIME)
        if not ok:
            # fall back to plain text only
            cb = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
            cb.set_text(self.text, -1)
        self.owned = True

    def ours(self):
        if not self.owned:
            return False
        try:
            w = Gdk.selection_owner_get(Gdk.SELECTION_CLIPBOARD)
            mine = self.owner.get_window()
            if w is not None and mine is not None and w != mine:
                self.owned = False
        except Exception:
            pass
        return self.owned

    def _get(self, widget, data, info, time):
        if info == HTML and self.html:
            data.set(Gdk.Atom.intern("text/html", False), 8, self.html.encode("utf-8"))
        else:
            data.set_text(self.text, -1)

    def _lost(self, widget, event):
        self.owned = False
        return False

    def keep_after_exit(self):
        """On quit: hand the text to the desktop's clipboard keeper, so a copy
        made just before closing can still be pasted elsewhere."""
        if self.ours() and self.text:
            cb = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
            cb.set_text(self.text, -1)
            cb.store()
