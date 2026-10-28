"""Format Painter, as in the original: click it, then click a word or drag
over text to give it the formatting of where you started. Double-click it
to paint several places (Esc or another click turns it off)."""
from gi.repository import Gdk, GLib


class Painter:
    def __init__(self, win):
        self.win = win
        self.active = False
        self.sticky = False
        self.data = None
        view = win.engine.view
        view.connect_after("button-release-event", self._released)
        view.connect("enter-notify-event", lambda *_: (self._cursor(), False)[1])

    def _buttons(self):
        out = []
        for c in getattr(self.win.ribbon, "controls", []):
            if getattr(c, "action", None) == ".uno:FormatPaintbrush":
                out.append(c)
        return out

    def _show(self):
        for c in self._buttons():
            try:
                c.apply_state("true" if self.active else "false")
            except Exception:
                pass
        self._cursor()

    def _cursor(self):
        gw = self.win.engine.view.get_window()
        if gw is None:
            return
        if self.active:
            gw.set_cursor(Gdk.Cursor.new_from_name(gw.get_display(), "copy"))
        else:
            gw.set_cursor(None)

    def start(self, sticky=False):
        data = self.win.actions.copy_format_data()
        if data is None:
            return
        self.data = data
        self.active = True
        self.sticky = sticky
        self._show()

    _t = 0.0

    def toggle(self, sticky=False):
        import time
        now = time.monotonic()
        if self.active and not sticky and now - self._t < 0.5:
            # a double-click on the button: it stays on for several places
            self.sticky = True
            self._t = 0.0
            self._show()
            return
        self._t = now
        if self.active and not sticky:
            self.stop()
        else:
            self.start(sticky)

    def stop(self):
        if not self.active:
            return
        self.active = False
        self.sticky = False
        self._show()

    def _released(self, view, event):
        if not self.active or event.button != 1:
            return False
        # the engine has placed the cursor / made the selection by now
        self.win.engine.sync(lambda: GLib.timeout_add(60, self._apply))
        return False

    def _apply(self):
        if not self.active:
            return False
        try:
            self.win.actions.apply_format_data(self.data)
        except Exception as e:
            print("format painter:", e)
        if not self.sticky:
            self.stop()
        else:
            self._cursor()
        return False
