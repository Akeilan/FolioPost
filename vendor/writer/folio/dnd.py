"""Drag and drop: documents dropped on the window open; pictures dropped on
the page are inserted where they land; dragged text is inserted."""
import os
from urllib.parse import unquote, urlparse

from gi.repository import Gdk, GLib, Gtk

from . import docapi

PICTURES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".tif", ".tiff", ".webp",
            ".emf", ".wmf"}
DOCUMENTS = {".docx", ".doc", ".docm", ".dotx", ".dot", ".odt", ".ott", ".rtf", ".txt",
             ".htm", ".html", ".xml", ".fodt", ".wpd", ".pdf"}


def _paths(data):
    out = []
    for uri in data.get_uris() or []:
        u = urlparse(uri)
        if u.scheme == "file":
            out.append(unquote(u.path))
    return out


class DropHandler:
    def __init__(self, win):
        self.win = win
        targets = [Gtk.TargetEntry.new("text/uri-list", 0, 0),
                   Gtk.TargetEntry.new("text/html", 0, 2),
                   Gtk.TargetEntry.new("UTF8_STRING", 0, 1),
                   Gtk.TargetEntry.new("text/plain;charset=utf-8", 0, 1),
                   Gtk.TargetEntry.new("text/plain", 0, 1),
                   Gtk.TargetEntry.new("STRING", 0, 1)]
        for w in (win, win.engine.view):
            w.drag_dest_set(Gtk.DestDefaults.ALL, targets, Gdk.DragAction.COPY)
            w.connect("drag-data-received", self._received)
            w.connect("drag-motion", self._motion)
        self._last_motion = 0

    def _to_view(self, widget, x, y):
        """Drops reach the window (overlays sit above the page view): find
        where on the page they landed."""
        view = self.win.engine.view
        if widget is view:
            return True, x, y
        if not view.get_mapped():
            return False, x, y
        res = widget.translate_coordinates(view, int(x), int(y))
        if not res:
            return False, x, y
        vx, vy = res
        a = view.get_allocation()
        if 0 <= vx < a.width and 0 <= vy < a.height:
            return True, vx, vy
        return False, x, y

    def _received(self, widget, ctx, x, y, data, info, time):
        on_page, x, y = self._to_view(widget, x, y)
        paths = _paths(data)
        if paths:
            for p in paths:
                ext = os.path.splitext(p)[1].lower()
                if ext in PICTURES and on_page:
                    GLib.idle_add(self._picture, p, x, y)
                elif ext in DOCUMENTS or ext in PICTURES:
                    self.win.app.open_path(p, from_window=self.win)
            widget.stop_emission_by_name("drag-data-received")
            return
        html = None
        try:
            if data.get_data_type().name() == "text/html":
                raw = bytes(data.get_data())
                if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
                    html = raw.decode("utf-16")
                else:
                    html = raw.decode("utf-8", "replace")
        except Exception:
            html = None
        text = data.get_text()
        if (text or html) and on_page:
            self._move(x, y)
            eng = self.win.engine
            if html:
                eng.sync(lambda: eng.paste_data("text/html", html.encode("utf-8")))
            else:
                eng.sync(lambda: eng.paste_data("text/plain;charset=utf-8", text))
            widget.stop_emission_by_name("drag-data-received")
            GLib.idle_add(self.win.focus_document)

    def _motion(self, widget, ctx, x, y, time):
        """While something is dragged over the page, the cursor follows the
        pointer, showing where it will go."""
        import time as _t
        now = _t.time()
        if now - self._last_motion < 0.08:
            return False
        self._last_motion = now
        on_page, vx, vy = self._to_view(widget, x, y)
        if on_page and getattr(self.win, "drag_move", None) is not None and \
                self.win.drag_move.state is None:
            self._move(vx, vy)
        return False

    def _move(self, x, y):
        eng = self.win.engine
        if getattr(eng, "native", False):
            hit = eng.view.page_at(x, y)
            if hit is not None and eng.ed is not None:
                eng.ed.click(hit[0], hit[1], hit[2], False)
                eng.view.after_move()
            return
        tx, ty = eng.px_to_twips(x, y)
        eng.click_at(tx, ty)

    def _picture(self, path, x, y):
        self._move(x, y)

        def insert():
            if getattr(self.win.engine, "native", False):
                from .native import objects
                if objects.insert_picture_path(self.win, path):
                    self.win.select_tab("Picture Format")
                return
            m = self.win.engine.model
            if m is None:
                return
            try:
                docapi.insert_picture(m, path)
                self.win.update_object_tabs()
                self.win.select_tab("Picture Format")
            except Exception as e:
                self.win.dialogs.message("This picture couldn't be inserted. (%s)" % e,
                                         kind="error")
        self.win.engine.sync(insert)
        return False
