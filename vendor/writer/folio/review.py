"""Review extras: change bars beside changed lines (red in Simple Markup,
grey in All Markup), Compare / Combine documents, and Restrict Editing."""
import hashlib
import json
import os

from gi.repository import GLib, Gtk

from . import docapi
from .panes import Pane
from .widgets import FDialog, grid, heading


def _rects(s):
    out = []
    for part in (s or "").split(";"):
        nums = [v.strip() for v in part.split(",")]
        if len(nums) == 4:
            try:
                out.append(tuple(int(float(n)) for n in nums))
            except ValueError:
                pass
    return out


class ChangeBars:
    def __init__(self, win):
        self.win = win
        self.mode = "All Markup"
        self.redlines = []
        self.hidden_authors = set()     # Show Markup > Specific People
        self.show_formatting = True     # Show Markup > Formatting
        self._timer = None
        view = win.engine.view
        view.connect_after("draw", self._draw)
        view.connect("key-release-event", lambda *_: (self.schedule(), False)[1])
        win.engine.connect("state-changed", self._state)
        win.engine.connect("loaded", lambda *_: self.schedule(800))

    def _state(self, eng, key, value):
        if key in (".uno:TrackChanges", ".uno:ShowTrackedChanges", ".uno:Undo",
                   ".uno:AcceptTrackedChange", ".uno:ModifiedStatus"):
            self.schedule()

    def schedule(self, delay=400):
        if self._timer:
            GLib.source_remove(self._timer)
        self._timer = GLib.timeout_add(delay, self.refresh)

    def refresh(self):
        self._timer = None
        try:
            raw = self.win.engine.view.get_command_values(".uno:AcceptTrackedChanges")
            self.redlines = json.loads(raw or "{}").get("redlines", [])
        except Exception:
            self.redlines = []
        self.win.engine.view.queue_draw()
        return False

    def set_mode(self, mode):
        self.mode = mode
        self.refresh()

    def _bar_x(self, y):
        eng = self.win.engine
        ps = getattr(self.win, "ruler_state", {}).get("page")
        left = (ps["left"] if ps else 2540) * 1440 // 2540
        for rx, ry, rw, rh in eng.page_rects():
            if ry <= y < ry + rh:
                return rx + left - 220
        return None

    def shown(self):
        """The changes that are being shown (reviewer and formatting
        filters)."""
        out = []
        for r in self.redlines:
            if r.get("author") in self.hidden_authors:
                continue
            if not self.show_formatting and r.get("type") not in ("Insert", "Delete"):
                continue
            out.append(r)
        return out

    def authors(self):
        out = []
        for r in self.redlines:
            a = r.get("author")
            if a and a not in out:
                out.append(a)
        return out

    def bars(self):
        """[(x_px, y0_px, y1_px)] for the changed lines."""
        out = []
        eng = self.win.engine
        for r in self.shown():
            for x, y, w, h in _rects(r.get("textRange")):
                bx = self._bar_x(y)
                if bx is None:
                    continue
                px, py0 = eng.twips_to_px(bx, y)
                _px, py1 = eng.twips_to_px(bx, y + h)
                out.append((px, py0, py1))
        return out

    def _draw(self, view, cr):
        if self.mode == "No Markup" or not self.redlines:
            return False
        red = self.mode == "Simple Markup"
        cr.set_source_rgb(0.85, 0.12, 0.12) if red else cr.set_source_rgb(0.55, 0.55, 0.55)
        for px, y0, y1 in self.bars():
            cr.rectangle(px, y0, 2 if not red else 2.5, max(2, y1 - y0))
        cr.fill()
        return False

    def hit(self, x, y):
        for px, y0, y1 in self.bars():
            if px - 5 <= x <= px + 7 and y0 - 2 <= y <= y1 + 2:
                return True
        return False


# ------------------------------------------------------------ compare / combine
def compare_dialog(win, combine=False):
    title = "Combine Documents" if combine else "Compare Documents"
    d = FDialog(win, title)
    orig = Gtk.FileChooserButton(title="Original document")
    rev = Gtk.FileChooserButton(title="Revised document")
    filt = Gtk.FileFilter()
    filt.set_name("Documents")
    for pat in ("*.docx", "*.doc", "*.odt", "*.rtf", "*.dotx", "*.ott"):
        filt.add_pattern(pat)
    for b in (orig, rev):
        b.add_filter(filt)
        b.set_width_chars(36)
    if win.engine.path and not win.engine.is_new:
        rev.set_filename(win.engine.path)
    label = Gtk.Entry(text=win.app.user_name() or "Author")
    d.add(heading("Original document"))
    d.add(orig)
    d.add(heading("Revised document"))
    d.add(rev)
    d.add(grid([["Label changes with:", label]]))
    r = d.ask()
    a, b = orig.get_filename(), rev.get_filename()
    d.done()
    if r != Gtk.ResponseType.OK:
        return
    if not a or not b:
        win.dialogs.message("Choose both documents.")
        return
    if os.path.abspath(a) == os.path.abspath(b):
        win.dialogs.message("The original and revised documents are the same file.")
        return
    # the result opens as a new document: the revised text with the
    # differences from the original shown as tracked changes
    w = win.app.new_window(template=b)
    w.compare_sources = {"original": a, "revised": b}
    w.source_windows = {}

    def go():
        if w.engine.model is None:
            return True
        from .engine import file_url
        if combine:
            w.engine.command(".uno:MergeDocuments", {"URL": file_url(a)})
        else:
            w.engine.command(".uno:CompareDocuments", {"URL": file_url(a),
                                                       "NoAcceptDialog": True})
        GLib.timeout_add(1500, lambda: (w.run("manage-changes"), False)[1])
        return False
    GLib.timeout_add(900, go)


def show_sources(win, which):
    """Compare > Show Source Documents: the original and/or revised document,
    read-only, beside the compared result."""
    src = getattr(win, "compare_sources", None)
    if not src:
        win.dialogs.message("Show Source Documents works on the result of Compare.")
        return
    win.app.settings["compare_sources"] = which
    want = {"hide": (), "original": ("original",), "revised": ("revised",),
            "both": ("original", "revised")}[which]
    open_ = win.source_windows
    for k in list(open_):
        if k not in want:
            w = open_.pop(k)
            try:
                w.destroy()
            except Exception:
                pass
    for k in want:
        if k in open_:
            continue
        w = win.app.new_window(src[k])
        w.source_of = win
        open_[k] = w
        w.connect("destroy", lambda _w, k=k: open_.pop(k, None))

        def ready(w=w, k=k):
            if w.engine.model is None:
                return True
            w.read_only = True
            w.engine.view.set_edit(False)
            w.ribbon.hide()
            w.update_title()
            w.msgbar.show_bar("source", "%s DOCUMENT" % k.upper(),
                              "This is the %s document of a comparison." % k, [])
            return False
        GLib.timeout_add(300, ready)
    GLib.timeout_add(400, lambda: (_tile_sources(win), False)[1])


def _tile_sources(win):
    wins = [win.source_windows[k] for k in ("original", "revised") if k in win.source_windows]
    gw = win.get_window()
    disp = win.get_display()
    mon = disp.get_monitor_at_window(gw) if gw else disp.get_primary_monitor()
    area = mon.get_workarea()
    if not wins:
        return
    main_w = area.width * 3 // 5
    win.unmaximize()
    win.move(area.x, area.y)
    win.resize(main_w, area.height)
    h = area.height // len(wins)
    for i, w in enumerate(wins):
        w.unmaximize()
        w.move(area.x + main_w, area.y + i * h)
        w.resize(area.width - main_w, h)


def source_state(win):
    if not getattr(win, "compare_sources", None):
        return None
    ks = set(getattr(win, "source_windows", {}))
    return "both" if ks == {"original", "revised"} else next(iter(ks), "hide")


# ------------------------------------------------------------ restrict editing
def _hash(pw):
    return hashlib.sha256(("folio:" + (pw or "")).encode()).hexdigest()


def _native_ed(m):
    eng = getattr(m, "eng", None)
    return eng.ed if eng is not None and getattr(eng, "native", False) else None


def restriction(m):
    """{"on", "mode", "lock", "hash" or "password"}: the editing restriction.
    The new engine keeps it as Word does (w:documentProtection)."""
    ed = _native_ed(m)
    if ed is not None:
        from .native import protect
        return protect.read(ed)
    try:
        return json.loads(docapi._doc_setting(m, "EditRestriction", "") or "{}")
    except ValueError:
        return {}


def set_restriction(m, data, pw=""):
    ed = _native_ed(m)
    if ed is not None:
        from .native import protect
        protect.write(ed, data.get("mode") if data else None, pw)
        return
    if data and pw:
        data = dict(data, hash=_hash(pw))
    docapi._set_doc_setting(m, "EditRestriction", json.dumps(data) if data else "")


def password_ok(m, r, pw):
    """Does pw lift restriction r?"""
    ed = _native_ed(m)
    if ed is not None:
        from .native import protect
        return protect.check(ed, pw or "")
    return not r.get("hash") or _hash(pw or "") == r["hash"]


def has_password(r):
    return bool(r.get("hash") or r.get("password"))


class RestrictPane(Pane):
    TITLE = "Restrict Editing"

    def __init__(self, win):
        Pane.__init__(self, win)
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.pack_start(self.body, True, True, 0)

    def on_shown(self):
        for c in self.body.get_children():
            self.body.remove(c)
        m = self.model
        if m is None:
            return
        r = restriction(m)
        if r.get("on"):
            lab = Gtk.Label(xalign=0)
            lab.set_line_wrap(True)
            lab.set_max_width_chars(34)
            lab.set_markup("<b>Your permissions</b>\n\nThis document is protected from "
                           "unintentional editing. " + (
                               "You may only make tracked changes." if r.get("mode") ==
                               "tracked" else "You may view this region, but you can't "
                               "modify it."))
            self.body.pack_start(lab, False, False, 0)
            stop = Gtk.Button(label="Stop Protection")
            stop.connect("clicked", lambda *_: self.stop())
            self.body.pack_start(stop, False, False, 0)
        else:
            h = Gtk.Label(xalign=0)
            h.set_markup("<b>1. Editing restrictions</b>")
            self.body.pack_start(h, False, False, 0)
            self.allow = Gtk.CheckButton(label="Allow only this type of editing in the "
                                               "document:")
            self.body.pack_start(self.allow, False, False, 0)
            self.kind = Gtk.ComboBoxText()
            for t in ("No changes (Read only)", "Tracked changes"):
                self.kind.append_text(t)
            self.kind.set_active(0)
            self.body.pack_start(self.kind, False, False, 0)
            h2 = Gtk.Label(xalign=0)
            h2.set_markup("<b>2. Start enforcement</b>")
            self.body.pack_start(h2, False, False, 0)
            go = Gtk.Button(label="Yes, Start Enforcing Protection")
            go.connect("clicked", lambda *_: self.start())
            self.body.pack_start(go, False, False, 0)
        self.body.show_all()

    def start(self):
        if not self.allow.get_active():
            self.win.dialogs.message("Select “Allow only this type of editing” first.")
            return
        d = self.win.dialogs
        pw = d.ask_password("Start Enforcing Protection",
                            "Enter new password (optional):") or ""
        if pw:
            pw2 = d.ask_password("Start Enforcing Protection", "Reenter password to "
                                 "confirm:") or ""
            if pw != pw2:
                d.message("The passwords don't match.")
                return
        mode = "tracked" if self.kind.get_active() == 1 else "readonly"
        set_restriction(self.model, {"on": True, "mode": mode}, pw)
        enforce(self.win)
        self.on_shown()

    def stop(self):
        m = self.model
        r = restriction(m)
        if has_password(r):
            pw = self.win.dialogs.ask_password("Unprotect Document", "Password:")
            if pw is None or not password_ok(m, r, pw):
                self.win.dialogs.message("The password is incorrect.", kind="error")
                return
        set_restriction(m, {})
        enforce(self.win)
        self.on_shown()


def enforce(win):
    """Apply the document's editing restriction to this window."""
    m = win.docmodel
    if m is None:
        return
    r = restriction(m)
    on = bool(r.get("on"))
    ro = on and r.get("mode") in ("readonly", "comments", "forms")
    win.engine.view.set_edit(not ro and not getattr(win, "read_only", False))
    win.restricted = ro
    if on and r.get("mode") == "tracked":
        if getattr(win.engine, "native", False):
            if not win.engine.ed.track_changes():
                win.engine.ed.set_track_changes(True)
                win.engine._schedule_state()
        elif win.engine.get(".uno:TrackChanges") != "true":
            win.engine.command(".uno:TrackChanges")
        win.track_locked = True
    else:
        win.track_locked = False
    win.update_title()


# ------------------------------------------------------------ lock tracking
def lock_tracking(win):
    """Review > Track Changes > Lock Tracking: others can't turn tracking off
    without the password."""
    m = win.docmodel
    if m is None:
        return
    r = restriction(m)
    d = win.dialogs
    if r.get("lock"):
        pw = d.ask_password("Unlock Tracking", "Password:") if has_password(r) else ""
        if pw is None:
            return
        if has_password(r) and not password_ok(m, r, pw):
            d.message("The password is incorrect.", kind="error")
            return
        set_restriction(m, {})
        enforce(win)
        win.status.flash("Tracking is unlocked.")
        return
    pw = d.ask_password("Lock Tracking", "Enter password (optional):")
    if pw is None:
        return
    if pw:
        pw2 = d.ask_password("Lock Tracking", "Reenter to confirm:") or ""
        if pw != pw2:
            d.message("The passwords don't match.")
            return
    set_restriction(m, {"on": True, "mode": "tracked", "lock": True}, pw)
    enforce(win)
    win.status.flash("Tracking is locked.")
