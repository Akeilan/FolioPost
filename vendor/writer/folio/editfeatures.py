"""Editing conveniences from the original:

* Collapse / expand headings: a small triangle beside a heading (shown when
  the mouse is over it, and always for collapsed headings) folds away
  everything up to the next heading of the same or a higher level.
  Collapsed text is opened up while the document is being saved, so it is
  never written out hidden.
* Click and Type: double-click in the empty space below the text to start
  typing there, left, centred or right according to where you clicked.
* The Spike: Ctrl+F3 cuts the selection onto the Spike, Ctrl+Shift+F3
  pastes everything on it and empties it.
* Resume reading: "Welcome back! Pick up where you left off" on reopening.
"""
import time

from gi.repository import Gdk, GLib, Gtk

from . import docapi

MM = 1440.0 / 2540.0
TRI = 11            # triangle size (px)


# ============================================================ helpers
def in_body(m):
    """Is the cursor in the main text (not a header, footer, frame or cell)?"""
    try:
        vc = docapi.view_cursor(m)
        return "HeadFoot" not in vc.getText().getImplementationName() and \
            vc.getText() == m.getText()
    except Exception:
        return False


def _keep_cursor(m):
    vc = docapi.view_cursor(m)
    t = vc.getText()
    return vc, t.createTextCursorByRange(vc.getStart()), t.createTextCursorByRange(vc.getEnd())


def _restore(vc, a, b):
    try:
        vc.gotoRange(a, False)
        vc.gotoRange(b, True)
    except Exception:
        pass


def _to_twips(win, pos):
    """View cursor position (mm100, from the first page's text origin) ->
    document twips."""
    m = win.engine.model
    rects = win.engine.page_rects()
    if not rects:
        return None
    ps = docapi.page_setup(m)
    return (rects[0][0] + (ps["left"] + pos.X) * MM, rects[0][1] + (ps["top"] + pos.Y) * MM)


def _unhide(rng):
    """Back to no hidden setting at all (not an explicit "not hidden")."""
    try:
        rng.setPropertyToDefault("CharHidden")
    except Exception:
        try:
            rng.CharHidden = False
        except Exception:
            pass


# ============================================================ headings
class HeadingFolds:
    def __init__(self, win):
        self.win = win
        self.collapsed = {}         # key -> (heading start cursor, hidden range cursor)
        self.marks = []             # [(key, level, x_twips, y_twips, h_twips)]
        self.stale = True
        self.hover = None
        view = win.engine.view
        view.connect_after("draw", self._draw)
        view.connect("motion-notify-event", self._motion)
        win.engine.save_hooks = tuple(win.engine.save_hooks) + ((self._open_all,
                                                                  self._close_all),)
        win.engine.connect("state-changed", self._state)

    # -- keys: a heading is known by its paragraph's position in the text
    @staticmethod
    def _key(par):
        return par.getStart()

    def _state(self, eng, key, value):
        if key in (".uno:ModifiedStatus", ".uno:StatePageNumber", ".uno:StyleApply"):
            self.stale = True

    def _headings(self):
        m = self.win.engine.model
        if m is None:
            return []
        try:
            return docapi.headings(m)
        except Exception:
            return []

    def refresh(self):
        """Where each heading is on the page (measured with the view cursor,
        which is put back where it was)."""
        m = self.win.engine.model
        if m is None or not in_body(m):
            # measuring moves the view cursor and puts it back by position; in a
            # header or footer that would land on the last page's copy of it
            return
        self.stale = False
        hs = self._headings()
        if not hs or len(hs) > 400:
            self.marks = []
            return
        out = []
        vc, a, b = _keep_cursor(m)
        try:
            for lvl, _t, par in hs:
                try:
                    vc.gotoRange(par.getStart(), False)
                    p = _to_twips(self.win, vc.getPosition())
                    h = (par.CharHeight or 11) * 20 * 1.3
                except Exception:
                    continue
                if p is not None:
                    out.append((par, lvl, p[0], p[1], h))
        finally:
            _restore(vc, a, b)
        self.marks = out

    def _is_collapsed(self, par):
        t = par.getText()
        for k, (start, _rng) in self.collapsed.items():
            try:
                if t.compareRegionStarts(start, par.getStart()) == 0:
                    return k
            except Exception:
                continue
        return None

    def _range_after(self, par, level):
        """From the end of the heading to the next heading of level <= level."""
        m = self.win.engine.model
        text = m.getText()
        en = text.createEnumeration()
        found = False
        end = None
        while en.hasMoreElements():
            p = en.nextElement()
            if not found:
                try:
                    if text.compareRegionStarts(p.getStart(), par.getStart()) == 0:
                        found = True
                except Exception:
                    pass
                continue
            try:
                lvl = p.OutlineLevel if p.supportsService("com.sun.star.text.Paragraph") else 0
            except Exception:
                lvl = 0
            if lvl and lvl <= level:
                end = p.getStart()
                break
        cur = text.createTextCursorByRange(par.getEnd())
        if end is None:
            cur.gotoEnd(True)
        else:
            cur.gotoRange(end, True)
            cur.goLeft(1, True)         # keep the next heading's own paragraph
        return cur

    def toggle(self, par, level):
        m = self.win.engine.model
        if m is None:
            return
        was = m.isModified()
        k = self._is_collapsed(par)
        um = m.getUndoManager()
        try:
            um.lock()           # folding is a view on the document, not an edit
        except Exception:
            pass
        try:
            if k is not None:
                _start, rng = self.collapsed.pop(k)
                _unhide(rng)
                # headings inside that stay collapsed
                for _k2, (_s2, r2) in self.collapsed.items():
                    try:
                        r2.CharHidden = True
                    except Exception:
                        pass
            else:
                rng = self._range_after(par, level)
                if not rng.getString() and rng.isCollapsed():
                    return
                rng.CharHidden = True
                start = par.getText().createTextCursorByRange(par.getStart())
                self.collapsed[id(start)] = (start, rng)
        finally:
            try:
                um.unlock()
            except Exception:
                pass
            if not was:
                m.setModified(False)
        self.stale = True
        self.win.engine.view.queue_draw()

    def expand_all(self):
        for k in list(self.collapsed):
            _s, rng = self.collapsed.pop(k)
            _unhide(rng)
        self.stale = True
        self.win.engine.view.queue_draw()

    def collapse_all(self):
        for lvl, _t, par in self._headings():
            if lvl == 1 and self._is_collapsed(par) is None:
                self.toggle(par, lvl)

    def _open_all(self):
        for _s, rng in self.collapsed.values():
            _unhide(rng)

    def _close_all(self):
        m = self.win.engine.model
        was = m.isModified() if m is not None else True
        for _s, rng in self.collapsed.values():
            try:
                rng.CharHidden = True
            except Exception:
                pass
        if m is not None and not was:
            m.setModified(False)

    # -- mouse
    def _tri_rect(self, mark):
        par, lvl, tx, ty, h = mark
        x, y = self.win.engine.twips_to_px(tx, ty)
        _x2, y2 = self.win.engine.twips_to_px(tx, ty + h)
        return x - TRI - 8, (y + y2) / 2 - TRI / 2, TRI + 6, TRI

    def _mark_at(self, x, y, band=False):
        for mk in self.marks:
            rx, ry, rw, rh = self._tri_rect(mk)
            if band:
                _x, y0 = self.win.engine.twips_to_px(mk[2], mk[3])
                _x, y1 = self.win.engine.twips_to_px(mk[2], mk[3] + mk[4])
                if y0 - 2 <= y <= y1 + 2:
                    return mk
            elif rx - 3 <= x <= rx + rw + 3 and ry - 4 <= y <= ry + rh + 4:
                return mk
        return None

    def _motion(self, view, event):
        if not self.win.app.settings.get("collapse_headings", True):
            return False
        if self.stale and not (event.state & (Gdk.ModifierType.BUTTON1_MASK |
                                              Gdk.ModifierType.BUTTON3_MASK)) and \
                self._text_selected():
            self.refresh()
        mk = self._mark_at(event.x, event.y, band=True)
        if mk is not self.hover:
            self.hover = mk
            view.queue_draw()
        return False

    def _text_selected(self):
        """Measuring moves the view cursor, which would drop a selected picture,
        shape or equation (and break a resize in progress): only with text."""
        m = self.win.engine.model
        if m is None or getattr(self.win, "eqbar", None) is not None and \
                self.win.eqbar.ed.active:
            return False
        try:
            sel = docapi.controller(m).getSelection()
            return sel is not None and sel.supportsService("com.sun.star.text.TextRanges")
        except Exception:
            return False

    def press(self, event):
        if event.button != 1 or not self.marks:
            return False
        mk = self._mark_at(event.x, event.y)
        if mk is None:
            return False
        self.toggle(mk[0], mk[1])
        return True

    def _draw(self, view, cr):
        if not self.marks:
            return False
        for mk in self.marks:
            col = self._is_collapsed(mk[0]) is not None
            if not col and mk is not self.hover:
                continue
            x, y, w, h = self._tri_rect(mk)
            cr.save()
            cr.set_source_rgb(0.35, 0.35, 0.35)
            if col:         # ▸
                cr.move_to(x + 3, y)
                cr.line_to(x + 3 + h * 0.8, y + h / 2)
                cr.line_to(x + 3, y + h)
            else:           # ◢
                cr.move_to(x + 3 + h, y)
                cr.line_to(x + 3 + h, y + h)
                cr.line_to(x + 3, y + h)
            cr.close_path()
            cr.fill()
            cr.restore()
        return False


# ============================================================ click and type
def click_and_type(win, event):
    """Double-click in the empty space below the end of the text."""
    if event.button != 1 or event.type != Gdk.EventType._2BUTTON_PRESS:
        return False
    if not win.app.settings.get("click_and_type", True):
        return False
    m = win.engine.model
    if m is None or win.in_header_footer():
        return False
    eng = win.engine
    tx, ty = eng.px_to_twips(event.x, event.y)
    rects = eng.page_rects()
    if not rects:
        return False
    vc, a, b = _keep_cursor(m)
    vc.gotoEnd(False)
    end = _to_twips(win, vc.getPosition())
    try:
        line = (vc.CharHeight or 11) * 20 * 1.25 + (vc.ParaBottomMargin or 0) * MM
    except Exception:
        line = 300
    if end is None or ty < end[1] + line * 1.4:
        _restore(vc, a, b)
        return False
    # the click must be on the same page as the end of the text
    page = next((r for r in rects if r[1] <= ty <= r[1] + r[3]), None)
    if page is None or not (page[1] <= end[1] <= page[1] + page[3]):
        _restore(vc, a, b)
        return False
    ps = docapi.page_setup(m)
    left = page[0] + ps["left"] * MM
    right = page[0] + page[2] - ps["right"] * MM
    if not left - 200 <= tx <= right + 200:
        _restore(vc, a, b)
        return False
    um = m.getUndoManager()
    um.enterUndoContext("Click and Type")
    try:
        text = vc.getText()
        n = 0
        while n < 80:
            text.insertControlCharacter(vc, 0, False)
            n += 1
            p = _to_twips(win, vc.getPosition())
            if p is None or p[1] + line * 0.5 >= ty:
                break
        width = right - left
        mid = left + width / 2
        cur = text.createTextCursorByRange(vc)
        if abs(tx - mid) < width * 0.12:
            cur.ParaAdjust = 3
        elif tx > right - width * 0.12:
            cur.ParaAdjust = 1
        else:
            cur.ParaAdjust = 0
            off = tx - left
            if off > 360:
                from . import bridge
                ts = bridge.struct("com.sun.star.style.TabStop")
                ts.Position = int(off / MM)
                ts.Alignment = bridge.enum("com.sun.star.style.TabAlign", "LEFT")
                cur.ParaTabStops = (ts,)
                text.insertString(vc, "\t", False)
    finally:
        um.leaveUndoContext()
    return True


# ============================================================ spike
def spike_cut(win):
    m = win.engine.model
    if m is None:
        return
    if not win.engine.get(".uno:StateWordCount", "").startswith("Selected"):
        try:
            if docapi.view_cursor(m).isCollapsed():
                win.status.flash("Select something to add to the Spike.")
                return
        except Exception:
            return
    win.actions.do_copy(cut=True)
    html, text = getattr(win.actions, "_clip_data", (None, ""))
    win.app.spike = getattr(win.app, "spike", [])
    win.app.spike.append((html, text))
    win.status.flash("Added to the Spike (%d item%s)." % (
        len(win.app.spike), "" if len(win.app.spike) == 1 else "s"))


def spike_paste(win):
    items = getattr(win.app, "spike", [])
    if not items:
        win.status.flash("The Spike is empty.")
        return
    import re
    bodies = []
    for html, text in items:
        if html:
            mt = re.search(r"<body[^>]*>(.*)</body>", html, re.S | re.I)
            bodies.append(mt.group(1) if mt else html)
        else:
            from html import escape
            bodies.append("<p>%s</p>" % escape(text))
    doc = "<html><head><meta charset='utf-8'></head><body>%s</body></html>" % "".join(bodies)
    win.engine.paste_data("text/html", doc)
    win.app.spike = []


# ============================================================ resume reading
def _para_index(m):
    vc = docapi.read_cursor(m)
    text = m.getText()
    try:
        here = vc.getStart()
        if here.getText() != text:
            return None, ""
    except Exception:
        return None, ""
    en = text.createEnumeration()
    i = 0
    while en.hasMoreElements():
        p = en.nextElement()
        try:
            if text.compareRegionStarts(p.getEnd(), here) > 0:   # ends before the cursor
                i += 1
                continue
        except Exception:
            pass
        try:
            snippet = p.getString().strip()
        except Exception:
            snippet = ""
        return i, snippet
    return i, ""


def remember_position(win):
    m = win.engine.model
    path = win.engine.path
    if m is None or not path:
        return
    try:
        i, snippet = _para_index(m)
    except Exception:
        return
    store = win.app.settings.setdefault("resume", {})
    if i is None or i < 3:
        store.pop(path, None)
    else:
        store[path] = {"para": i, "snippet": snippet[:60], "time": time.time()}
        if len(store) > 50:
            for k in sorted(store, key=lambda k: store[k].get("time", 0))[:len(store) - 50]:
                store.pop(k, None)
    win.app.save_settings()


def _ago(t):
    d = time.time() - t
    if d < 120:
        return "a moment ago"
    if d < 3600:
        return "%d minutes ago" % (d // 60)
    if d < 86400 * 2:
        h = d // 3600
        return "%d hour%s ago" % (h, "" if h == 1 else "s")
    days = d // 86400
    return "%d days ago" % days


def offer_resume(win):
    path = win.engine.path
    if not path:
        return
    rec = win.app.settings.get("resume", {}).get(path)
    if not rec:
        return
    b = Gtk.Button()
    b.get_style_context().add_class("folio-resume")
    v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    t = Gtk.Label(xalign=0)
    t.set_markup("<b>Welcome back!</b>")
    v.pack_start(t, False, False, 0)
    v.pack_start(Gtk.Label(label="Pick up where you left off:", xalign=0), False, False, 0)
    s = Gtk.Label(label=(rec.get("snippet") or "")[:40] or "Paragraph %d" % rec["para"],
                  xalign=0)
    s.get_style_context().add_class("dim-label")
    v.pack_start(s, False, False, 0)
    w = Gtk.Label(label=_ago(rec.get("time", time.time())), xalign=0)
    w.get_style_context().add_class("dim-label")
    v.pack_start(w, False, False, 0)
    b.add(v)
    b.set_halign(Gtk.Align.END)
    b.set_valign(Gtk.Align.START)
    b.set_margin_end(24)
    b.set_margin_top(12)

    def go(*_):
        m = win.engine.model
        try:
            en = m.getText().createEnumeration()
            k = 0
            while en.hasMoreElements():
                p = en.nextElement()
                if k == rec["para"]:
                    docapi.view_cursor(m).gotoRange(p.getStart(), False)
                    break
                k += 1
        except Exception as e:
            print("resume:", e)
        close()
        win.focus_document()

    def close(*_):
        if b.get_parent() is not None:
            b.get_parent().remove(b)
        return False
    b.connect("clicked", go)
    win.canvas_overlay.add_overlay(b)
    b.show_all()
    GLib.timeout_add_seconds(20, close)
    win.canvas.get_vadjustment().connect(
        "value-changed", lambda a: close() if a.get_value() > 400 else None)


# ---------------------------------------------------------------- collapsed by default
COLLAPSED_PROP = "FolioCollapsedHeadings"


def _collapsed_list(m):
    import json
    try:
        v = m.getDocumentProperties().getUserDefinedProperties().getPropertyValue(
            COLLAPSED_PROP)
        return list(json.loads(v))
    except Exception:
        return []


def _store_collapsed(m, items):
    import json
    udp = m.getDocumentProperties().getUserDefinedProperties()
    val = json.dumps(items)
    try:
        if udp.getPropertySetInfo().hasPropertyByName(COLLAPSED_PROP):
            if items:
                udp.setPropertyValue(COLLAPSED_PROP, val)
            else:
                udp.removeProperty(COLLAPSED_PROP)
        elif items:
            udp.addProperty(COLLAPSED_PROP, 128, val)     # REMOVABLE
    except Exception as e:
        print("collapsed headings:", e)


def _para_of(vc):
    c = vc.getText().createTextCursorByRange(vc.getStart())
    c.gotoStartOfParagraph(False)
    c.gotoEndOfParagraph(True)
    en = c.createEnumeration()
    return en.nextElement() if en.hasMoreElements() else None


def is_collapsed_by_default(m, vc):
    try:
        p = _para_of(vc)
        return p is not None and p.getString().strip() in _collapsed_list(m)
    except Exception:
        return False


def set_collapsed_by_default(win, m, vc, on):
    p = _para_of(vc)
    if p is None:
        return
    text = p.getString().strip()
    items = [t for t in _collapsed_list(m) if t != text]
    if on and text:
        items.append(text)
    was = m.isModified()
    _store_collapsed(m, items)
    folds = win.folds
    lvl = p.OutlineLevel or 0
    if on and lvl and folds._is_collapsed(p) is None:
        folds.toggle(p, lvl)


def apply_collapsed_defaults(win):
    """On opening: collapse the headings set to be collapsed by default."""
    m = win.engine.model
    if m is None:
        return False
    items = set(_collapsed_list(m))
    if not items:
        return False
    was = m.isModified()
    for lvl, text, par in docapi.headings(m):
        if text in items and win.folds._is_collapsed(par) is None:
            try:
                win.folds.toggle(par, lvl)
            except Exception as e:
                print("collapse:", e)
    if not was:
        m.setModified(False)
    return False
