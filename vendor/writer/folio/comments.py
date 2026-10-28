"""Comment balloons in the margin beside the page, with the commented text
highlighted, Reply / Resolve / Delete, and replies threaded under their
comment. The engine reports comments; the app draws them."""
import datetime
import html
import json

from gi.repository import GLib, Gtk, Pango


def comment_text(c):
    """A comment's plain text: the engine reports either text or html."""
    t = c.get("text")
    if t:
        return t
    h = c.get("html") or ""
    if not h:
        return ""
    import re as _re
    h = _re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", h)
    h = _re.sub(r"<[^>]+>", "", h)
    return html.unescape(h).strip("\n")

CARD_W = 250
GAP = 14


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


def _when(s):
    try:
        d = datetime.datetime.strptime(s.split(",")[0].split(".")[0], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return ""
    now = datetime.datetime.now()
    if d.date() == now.date():
        mins = int((now - d).total_seconds() // 60)
        if mins < 1:
            return "A few seconds ago"
        if mins < 60:
            return "%d minute%s ago" % (mins, "" if mins == 1 else "s")
        return d.strftime("%-I:%M %p")
    return d.strftime("%B %-d, %Y")


class CommentsMargin:
    def __init__(self, win, overlay):
        self.win = win
        self.eng = win.engine
        self.comments = {}          # id -> dict
        self.overlay = overlay
        self.cards = {}
        self.active = None
        self.eng.view.connect("comment", self._on_comment)
        self.eng.view.connect_after("draw", self._draw_ranges)
        self.eng.connect("loaded", lambda *_: GLib.timeout_add(600, self.reload))
        self.eng.connect("zoom-changed", lambda *_: self.schedule())
        sw = win.canvas
        sw.get_vadjustment().connect("value-changed", lambda *_: self.layout())
        sw.get_hadjustment().connect("value-changed", lambda *_: self.layout())
        overlay.connect("size-allocate", lambda *_: self.schedule())
        self.show_markup = True
        self.hidden_authors = set()
        self._pending = None

    def card_w(self):
        try:
            return int(self.win.app.settings.get("track_options", {}).get("balloon_width",
                                                                          CARD_W))
        except Exception:
            return CARD_W

    def set_width(self, w):
        self.rebuild()
        self.schedule()

    # ------------------------------------------------------------ data
    def reload(self):
        raw = self.eng.view.get_command_values(".uno:ViewAnnotations")
        self.comments = {}
        try:
            data = json.loads(raw or "{}")
            for c in data.get("comments", []) + data.get("revisions", []):
                self.comments[str(c["id"])] = c
        except (ValueError, KeyError, TypeError):
            pass
        self.rebuild()
        return False

    def _on_comment(self, view, payload):
        try:
            c = json.loads(payload)["comment"]
        except (ValueError, KeyError):
            return
        cid = str(c.get("id"))
        action = c.get("action")
        if action == "Remove":
            self.comments.pop(cid, None)
        elif action in ("Add", "Modify", "RedlinedDeletion"):
            old = self.comments.get(cid, {})
            old.update(c)
            self.comments[cid] = old
        else:
            return
        self.rebuild()

    # ------------------------------------------------------------ cards
    def rebuild(self):
        for w in self.cards.values():
            self.overlay.remove(w)
        self.cards = {}
        visible = self.show_markup and bool(self.comments)
        # make room for the balloons beside the page
        self.eng.view.set_margin_end(self.card_w() + 2 * GAP if visible else 0)
        if not visible:
            self.eng.view.queue_draw()
            return
        for cid, c in self.comments.items():
            if str(c.get("parentId", "0")) not in ("0", "", "None"):
                continue
            if c.get("author") in self.hidden_authors:
                continue
            card = self._card(c)
            card.set_halign(Gtk.Align.START)
            card.set_valign(Gtk.Align.START)
            card.set_no_show_all(False)
            self.cards[cid] = card
            self.overlay.add_overlay(card)
            card.hide()
        self.schedule()
        self.eng.view.queue_draw()

    def _rev_card(self, c):
        """A revision balloon: 'Deleted: text' / 'Formatted: Bold'."""
        frame = Gtk.EventBox()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        box.get_style_context().add_class("folio-balloon")
        box.get_style_context().add_class("revision")
        box.set_size_request(self.card_w(), -1)
        frame.add(box)
        head = Gtk.Label(xalign=0)
        head.set_markup("<small><b>%s</b>  %s</small>" % (
            html.escape(c.get("author") or "Author"), html.escape(_when(c.get("dateTime", "")))))
        box.pack_start(head, False, False, 0)
        label = c.get("text") or ""
        kind, _, rest = label.partition(": ")
        body = Gtk.Label(xalign=0)
        body.set_line_wrap(True)
        body.set_max_width_chars(30)
        if kind == "Deleted":
            body.set_markup("<b>Deleted:</b> <span foreground='#b0141c'>%s</span>" % html.escape(rest))
        else:
            body.set_markup("<b>%s:</b> %s" % (html.escape(kind), html.escape(rest)))
        box.pack_start(body, False, False, 0)
        frame.show_all()
        return frame

    def _card(self, c):
        if c.get("revision"):
            return self._rev_card(c)
        cid = str(c["id"])
        frame = Gtk.EventBox()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        box.get_style_context().add_class("folio-balloon")
        if c.get("resolved") == "true":
            box.get_style_context().add_class("resolved")
        box.set_size_request(self.card_w(), -1)
        frame.add(box)
        for item in [c] + [r for r in self.comments.values()
                           if str(r.get("parentId")) == cid]:
            head = Gtk.Box(spacing=6)
            initials = "".join(w[0] for w in (item.get("author") or "?").split()[:2]).upper()
            av = Gtk.Label(label=initials or "?")
            av.get_style_context().add_class("folio-avatar")
            head.pack_start(av, False, False, 0)
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            a = Gtk.Label(xalign=0)
            a.set_markup("<b>%s</b>" % html.escape(item.get("author") or "Author"))
            t = Gtk.Label(label=_when(item.get("dateTime", "")), xalign=0)
            t.get_style_context().add_class("dim-label")
            v.pack_start(a, False, False, 0)
            v.pack_start(t, False, False, 0)
            head.pack_start(v, True, True, 0)
            box.pack_start(head, False, False, 0)
            body = Gtk.Label(label=comment_text(item), xalign=0)
            body.set_line_wrap(True)
            body.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            body.set_max_width_chars(30)
            body.set_selectable(False)
            box.pack_start(body, False, False, 0)
        acts = Gtk.Box(spacing=4)
        for label, cb in (("Reply", lambda: self.reply(cid)),
                          ("Resolve" if c.get("resolved") != "true" else "Reopen",
                           lambda: self.resolve(cid)),
                          ("Edit", lambda: self.edit(cid)),
                          ("Delete", lambda: self.delete(cid))):
            b = Gtk.Button(label=label)
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.get_style_context().add_class("folio-balloon-btn")
            b.connect("clicked", lambda _b, cb=cb: cb())
            acts.pack_start(b, False, False, 0)
        box.pack_start(acts, False, False, 0)
        frame.connect("button-press-event", lambda *_: (self.focus(cid), False)[1])
        frame.show_all()
        return frame

    def schedule(self):
        if self._pending is None:
            self._pending = GLib.idle_add(self._timed_layout)

    def _timed_layout(self):
        self._pending = None
        self.layout()
        return False

    def _page_right_px(self, y_twips):
        rects = self.eng.page_rects()
        for rx, ry, rw, rh in rects:
            if ry <= y_twips < ry + rh:
                return rx + rw
        return rects[0][0] + rects[0][2] if rects else 12240

    def layout(self):
        if not self.cards:
            return
        view = self.eng.view
        items = []
        for cid, card in self.cards.items():
            c = self.comments.get(cid, {})
            pos = _rects(c.get("anchorPos"))
            if not pos:
                continue
            x, y, w, h = pos[0]
            items.append((y, cid, card, x))
        items.sort()
        last_bottom = -1e9
        for y, cid, card, x in items:
            px, py = self.eng.twips_to_px(self._page_right_px(y), y)
            res = view.translate_coordinates(self.overlay, int(px), int(py))
            if not res:
                continue
            ox, oy = res
            oy = max(oy - 8, last_bottom + 8)
            card_h = card.get_child().get_preferred_height_for_width(self.card_w())[1]
            vis_h = self.overlay.get_allocated_height()
            if oy + card_h < 0 or oy > vis_h:
                card.hide()
            else:
                card.set_margin_start(max(0, ox + GAP))
                card.set_margin_top(max(0, int(oy)))
                card.show()
            last_bottom = oy + card_h
            ctx = card.get_child().get_style_context()
            if cid == self.active:
                ctx.add_class("active")
            else:
                ctx.remove_class("active")

    def _draw_ranges(self, view, cr):
        if not self.show_markup or not self.comments:
            return False
        for cid, c in self.comments.items():
            if c.get("revision") and c.get("author") not in self.hidden_authors:
                # a dotted leader from the change to the margin
                pos = _rects(c.get("anchorPos"))
                if pos:
                    x, y, _w, h = pos[0]
                    x0, y0 = self.eng.twips_to_px(x, y + h)
                    x1, _y1 = self.eng.twips_to_px(self._page_right_px(y), y + h)
                    cr.save()
                    cr.set_source_rgb(0.72, 0.1, 0.12)
                    cr.set_line_width(1)
                    cr.set_dash([2, 2])
                    cr.move_to(x0, int(y0) + 0.5)
                    cr.line_to(x1 + GAP, int(y0) + 0.5)
                    cr.stroke()
                    cr.restore()
                continue
            if str(c.get("parentId", "0")) not in ("0", "", "None"):
                continue
            active = cid == self.active
            cr.set_source_rgba(0.98, 0.80, 0.45, 0.55 if active else 0.32)
            for x, y, w, h in _rects(c.get("textRange")):
                x0, y0 = self.eng.twips_to_px(x, y)
                x1, y1 = self.eng.twips_to_px(x + w, y + h)
                cr.rectangle(x0, y0, max(2, x1 - x0), y1 - y0)
            cr.fill()
        return False

    # ------------------------------------------------------------ actions
    def focus(self, cid):
        self.active = cid
        self.layout()
        self.eng.view.queue_draw()

    def _ask(self, title, text=""):
        return self.win.dialogs.ask_text(title, "Comment:", text)

    def reply(self, cid):
        t = self._ask("Reply")
        if t:
            self.eng.command(".uno:ReplyComment", {"Id": str(cid), "Text": t,
                                                   "Author": self.win.app.user_name()})

    def resolve(self, cid):
        self.eng.command(".uno:ResolveComment", {"Id": str(cid)})

    def edit(self, cid):
        c = self.comments.get(cid, {})
        t = self._ask("Edit Comment", comment_text(c))
        if t is not None:
            self.eng.command(".uno:EditAnnotation", {"Id": str(cid), "Text": t})

    def delete(self, cid):
        self.eng.command(".uno:DeleteComment", {"Id": str(cid)})

    def delete_all(self, shown_only=False):
        if shown_only and self.hidden_authors:
            for a in sorted({c.get("author") for c in self.comments.values()}):
                if a and a not in self.hidden_authors:
                    self.eng.command(".uno:DeleteAuthor", {"Author": a})
            return
        self.eng.command(".uno:DeleteAllNotes")

    def authors(self):
        out = []
        for c in self.comments.values():
            a = c.get("author")
            if a and a not in out:
                out.append(a)
        return out

    def set_visible(self, on):
        self.show_markup = on
        self.rebuild()
