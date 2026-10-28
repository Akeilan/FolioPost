"""The Reading Pane: a message's header (sender, recipients, date), its attachments, the
remote-pictures bar and the body, shown safely."""
import hashlib
import os
import subprocess
import tempfile
import threading
import time
import urllib.request

from gi.repository import GLib, Gtk, Pango

from . import icons, mime
from .htmlview import MessageView, remote_images

AVATAR_COLORS = ["#333366", "#8764b8", "#038387", "#ca5010", "#498205", "#c239b3", "#0078d4", "#986f0b"]


def initials(name, addr):
    words = [w for w in (name or "").replace(",", " ").split() if w[:1].isalnum()]
    if len(words) >= 2:
        return (words[0][0] + words[-1][0]).upper()
    if words:
        return words[0][:2].upper()
    return (addr or "?")[:1].upper()


def avatar(name, addr, size=40):
    color = AVATAR_COLORS[int(hashlib.md5((addr or name or "").lower().encode()).hexdigest(), 16) % len(AVATAR_COLORS)]
    a = Gtk.DrawingArea()
    a.set_size_request(size, size)
    text = initials(name, addr)

    def draw(w, cr):
        import math
        from gi.repository import Gdk, PangoCairo
        rgba = Gdk.RGBA()
        rgba.parse(color)
        cr.set_source_rgb(rgba.red, rgba.green, rgba.blue)
        cr.arc(size / 2, size / 2, size / 2, 0, 2 * math.pi)
        cr.fill()
        lay = PangoCairo.create_layout(cr)
        lay.set_font_description(Pango.FontDescription("Sans %d" % int(size * 0.33)))
        lay.set_text(text, -1)
        tw, th = lay.get_pixel_size()
        cr.set_source_rgb(1, 1, 1)
        cr.move_to((size - tw) / 2, (size - th) / 2)
        PangoCairo.show_layout(cr, lay)
    a.connect("draw", draw)
    return a


def nice_size(n):
    if n < 1024:
        return "%d bytes" % n
    if n < 1024 * 1024:
        return "%d KB" % max(1, round(n / 1024))
    return "%.1f MB" % (n / 1048576)


def fetch_remote(urls, limit=40, max_bytes=5 * 1048576):
    out = {}
    for u in urls[:limit]:
        try:
            req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                out[u] = r.read(max_bytes)
        except Exception:
            pass
    return out


class ReadingPane(Gtk.Box):
    def __init__(self, win, compact=False):
        Gtk.Box.__init__(self, orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.win = win
        self.get_style_context().add_class("folio-reading")
        self.mid = None
        self.msg = None
        self.raw = b""
        self.remote = None
        self.html = None
        self.atts = []
        self.empty = Gtk.Label(label="Select an item to read")
        self.empty.get_style_context().add_class("folio-reading-empty")
        self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        # header
        hd = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        hd.get_style_context().add_class("folio-reading-head")
        hd.set_margin_start(16)
        hd.set_margin_end(16)
        hd.set_margin_top(12)
        hd.set_margin_bottom(6)
        self.subject = Gtk.Label(xalign=0)
        self.subject.set_line_wrap(True)
        self.subject.set_selectable(True)
        self.subject.get_style_context().add_class("folio-reading-subject")
        hd.pack_start(self.subject, False, False, 0)
        row = Gtk.Box(spacing=10)
        self.avatar_box = Gtk.Box()
        row.pack_start(self.avatar_box, False, False, 0)
        who = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        self.sender = Gtk.Label(xalign=0)
        self.sender.set_selectable(True)
        self.sender.set_ellipsize(Pango.EllipsizeMode.END)
        self.sender.get_style_context().add_class("folio-reading-sender")
        self.recips = Gtk.Label(xalign=0)
        self.recips.set_selectable(True)
        self.recips.set_line_wrap(True)
        self.recips.get_style_context().add_class("folio-reading-recips")
        who.pack_start(self.sender, False, False, 0)
        who.pack_start(self.recips, False, False, 0)
        row.pack_start(who, True, True, 0)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        btns = Gtk.Box(spacing=2)
        for label, icon, cmd, tip in (("Reply", "p-reply", "reply", "Reply (Ctrl+R)"),
                                      ("Reply All", "p-reply-all", "reply-all", "Reply All (Ctrl+Shift+R)"),
                                      ("Forward", "p-forward", "forward", "Forward (Ctrl+F)")):
            b = Gtk.Button()
            bx = Gtk.Box(spacing=4)
            bx.pack_start(icons.image(icon, 16), False, False, 0)
            if not compact:
                bx.pack_start(Gtk.Label(label=label), False, False, 0)
            b.add(bx)
            b.set_tooltip_text(tip)
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.get_style_context().add_class("folio-reading-btn")
            b.connect("clicked", lambda _b, c=cmd: self.win.run(c))
            btns.pack_start(b, False, False, 0)
        right.pack_start(btns, False, False, 0)
        self.date = Gtk.Label(xalign=1)
        self.date.get_style_context().add_class("folio-reading-date")
        right.pack_start(self.date, False, False, 0)
        row.pack_end(right, False, False, 0)
        hd.pack_start(row, False, False, 0)
        self.info = Gtk.Label(xalign=0)
        self.info.get_style_context().add_class("folio-reading-info")
        self.info.set_line_wrap(True)
        hd.pack_start(self.info, False, False, 0)
        self.content.pack_start(hd, False, False, 0)
        # meeting requests
        self.invite = Gtk.Box(spacing=6)
        self.invite.get_style_context().add_class("folio-invitebar")
        self.invite.set_margin_start(16)
        self.invite.set_margin_end(16)
        self.invite_label = Gtk.Label(xalign=0)
        self.invite_label.set_line_wrap(True)
        self.invite.pack_start(icons.image("p-nav-calendar", 16), False, False, 0)
        self.invite.pack_start(self.invite_label, True, True, 0)
        self.invite_buttons = {}
        for key, label in (("ACCEPTED", "✓ Accept"), ("TENTATIVE", "? Tentative"), ("DECLINED", "✗ Decline"),
                           ("remove", "Remove from Calendar")):
            b = Gtk.Button(label=label)
            b.connect("clicked", lambda _b, k=key: self.answer_invite(k))
            self.invite.pack_end(b, False, False, 0)
            self.invite_buttons[key] = b
        self.invite.set_no_show_all(True)
        self.content.pack_start(self.invite, False, False, 2)
        self.invite_ics = None
        # remote pictures
        self.bar = Gtk.EventBox()
        bb = Gtk.Box(spacing=8)
        bb.get_style_context().add_class("folio-infobar")
        self.bar_label = Gtk.Label(xalign=0)
        self.bar_label.set_line_wrap(True)
        bb.pack_start(self.bar_label, True, True, 0)
        dl = Gtk.Button(label="Download Pictures")
        dl.connect("clicked", lambda *_: self.download_pictures())
        self.bar_download = dl
        trust = Gtk.Button(label="Always Allow from Sender")
        trust.connect("clicked", lambda *_: self.trust_sender())
        bb.pack_end(trust, False, False, 0)
        bb.pack_end(dl, False, False, 0)
        bb.set_margin_start(16)
        bb.set_margin_end(16)
        self.bar.add(bb)
        self.bar.set_no_show_all(True)
        self.content.pack_start(self.bar, False, False, 2)
        # attachments
        self.att_box = Gtk.FlowBox()
        self.att_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self.att_box.set_max_children_per_line(6)
        self.att_box.set_margin_start(14)
        self.att_box.set_margin_end(14)
        self.att_box.set_no_show_all(True)
        self.content.pack_start(self.att_box, False, False, 2)
        sep = Gtk.Separator()
        sep.set_margin_start(16)
        sep.set_margin_end(16)
        self.content.pack_start(sep, False, False, 4)
        self.view = MessageView()
        self.view.on_link = self.open_link
        sw = Gtk.ScrolledWindow()
        sw.add(self.view)
        self.scroller = sw
        self.content.pack_start(sw, True, True, 0)
        self.stack = Gtk.Stack()
        self.stack.add_named(self.empty, "empty")
        self.stack.add_named(self.content, "message")
        self.pack_start(self.stack, True, True, 0)
        self.zoom = 1.0

    # ------------------------------------------------------------ showing
    def clear(self, text="Select an item to read"):
        self.mid = None
        self.msg = None
        self.empty.set_text(text)
        self.stack.set_visible_child_name("empty")

    def show_message(self, mid=None, raw=None):
        store = self.win.store
        if mid is not None:
            row = store.message(mid)
            if row is None:
                self.clear()
                return
            raw = store.raw(mid)
        else:
            row = None
        self.mid = mid
        self.row = row
        self.raw = raw or b""
        msg = mime.parse(self.raw)
        self.security = None
        from . import pgp
        if pgp.kind(msg):
            msg, self.security = pgp.open_message(self.raw)
        else:
            from . import smime
            if smime.kind(msg):
                me = [a["email"] for a in self.win.store.accounts() if a["email"]]
                msg, self.security = smime.open_message(self.raw, me)
        self.msg = msg
        self.remote = None
        subject = mime.header(msg, "Subject") or "(no subject)"
        self.subject.set_text(subject)
        frm = mime.addresses(msg, "From")
        fn, fa = frm[0] if frm else ("", "")
        for c in self.avatar_box.get_children():
            self.avatar_box.remove(c)
        av = avatar(fn, fa)
        av.show()
        self.avatar_box.pack_start(av, False, False, 0)
        self.sender.set_markup("<b>%s</b> &lt;%s&gt;" % (GLib.markup_escape_text(fn or fa), GLib.markup_escape_text(fa))
                               if fn else "<b>%s</b>" % GLib.markup_escape_text(fa or "(unknown sender)"))
        to = mime.show_addresses(mime.addresses(msg, "To"))
        cc = mime.show_addresses(mime.addresses(msg, "Cc"))
        bcc = mime.show_addresses(mime.addresses(msg, "Bcc"))
        lines = []
        if to:
            lines.append("To: " + to)
        if cc:
            lines.append("Cc: " + cc)
        if bcc:
            lines.append("Bcc: " + bcc)
        self.recips.set_text("\n".join(lines))
        when = mime.date_of(msg) or (row["date"] if row else 0)
        self.date.set_text(time.strftime("%a %d/%m/%Y %H:%M", time.localtime(when)) if when else "")
        info = []
        if row:
            if row["answered"]:
                info.append("You replied to this message.")
            if row["forwarded"]:
                info.append("You forwarded this message.")
            if row["flagged"]:
                info.append("Follow up.")
            if row["done"]:
                info.append("Completed.")
            if row["importance"] == 2:
                info.append("This message was sent with High importance.")
            if row["categories"]:
                info.append("Categories: " + row["categories"].replace(",", ", "))
        if self.security:
            info.insert(0, self.security + ".")
        if mime.header(msg, "Disposition-Notification-To"):
            info.append("The sender asked for a read receipt.")
        self.info.set_text(" ".join(info))
        self.info.set_visible(bool(info))
        # attachments
        self.atts = mime.attachments(msg)
        for c in self.att_box.get_children():
            self.att_box.remove(c)
        shown = [a for a in self.atts if not a["inline"]]
        for a in shown:
            self.att_box.add(self._att_button(a))
        if len(shown) > 1:
            b = Gtk.Button(label="Save All Attachments")
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.connect("clicked", lambda *_: self.save_all())
            self.att_box.add(b)
        self.att_box.set_visible(bool(shown))
        self.att_box.show_all()
        self.show_invite(msg)
        self.render()
        self.stack.set_visible_child_name("message")
        self.scroller.get_vadjustment().set_value(0)

    def calendar_part(self, msg):
        for p in msg.walk():
            if p.is_multipart():
                continue
            ct = p.get_content_type()
            if ct == "text/calendar" or (ct in ("application/ics", "application/octet-stream") and
                                         (p.get_filename() or "").lower().endswith(".ics")):
                try:
                    data = p.get_payload(decode=True) or b""
                except Exception:
                    continue
                text = data.decode("utf-8", "replace")
                if "BEGIN:VCALENDAR" in text:
                    return text
        return None

    def show_invite(self, msg):
        from . import ical
        self.invite_ics = None
        self.invite.set_visible(False)
        text = self.calendar_part(msg)
        if not text:
            return
        cal = ical.parse(text)
        evs = ical.events_of(cal)
        method = (cal.get("METHOD", "") if cal else "").upper()
        if not evs or method not in ("REQUEST", "CANCEL", "REPLY"):
            return
        e = evs[0]
        self.invite_ics = text
        self.invite_method = method
        when = ""
        if e.start:
            s = e.start.astimezone(ical.local_tz())
            when = s.strftime("%A, %d %B %Y") + ("" if e.all_day else s.strftime(" %H:%M") +
                                                   (e.end or e.start).astimezone(ical.local_tz()).strftime("–%H:%M"))
        main = getattr(self.win, "main", self.win)
        mine = main.find_event(e.uid) if hasattr(main, "find_event") else None
        for k, b in self.invite_buttons.items():
            b.set_visible((method == "REQUEST" and k != "remove") or (method == "CANCEL" and k == "remove" and mine is not None))
            b.set_no_show_all(not b.get_visible())
        if method == "REQUEST":
            state = ""
            if mine is not None:
                st = main.my_status(mine)
                state = {"ACCEPTED": " You accepted.", "TENTATIVE": " You tentatively accepted.",
                         "DECLINED": " You declined."}.get(st, " It's in your calendar.")
            txt = "<b>%s</b>\n%s%s%s" % (GLib.markup_escape_text(e.summary or "Meeting"), GLib.markup_escape_text(when),
                                         (" · " + GLib.markup_escape_text(e.location)) if e.location else "", state)
        elif method == "CANCEL":
            txt = "<b>This meeting was canceled.</b> %s" % GLib.markup_escape_text(e.summary)
            if mine is None:
                txt += " It isn't in your calendar."
        else:
            who = e.attendees[0] if e.attendees else {"name": "", "email": "", "status": ""}
            verb = {"ACCEPTED": "accepted", "TENTATIVE": "tentatively accepted", "DECLINED": "declined"}.get(who["status"], "answered")
            txt = "<b>%s %s.</b> %s" % (GLib.markup_escape_text(who["name"] or who["email"]), verb, GLib.markup_escape_text(e.summary))
            if hasattr(main, "record_reply"):
                main.record_reply(e)
        self.invite_label.set_markup(txt)
        self.invite.set_no_show_all(False)
        self.invite.show_all()
        for k, b in self.invite_buttons.items():
            if b.get_no_show_all():
                b.hide()

    def answer_invite(self, how):
        main = getattr(self.win, "main", self.win)
        if self.invite_ics is None or not hasattr(main, "respond_to_invitation"):
            return
        acc = None
        if self.row is not None:
            f = main.store.folder(self.row["folder"])
            acc = main.store.account(f["account"]) if f else None
        if how == "remove":
            main.remove_canceled(self.invite_ics)
        else:
            main.respond_to_invitation(self.invite_ics, how, acc)
        if self.msg is not None:
            self.show_invite(self.msg)

    def _sender(self):
        frm = mime.addresses(self.msg, "From") if self.msg is not None else []
        return (frm[0][1] if frm else "").lower()

    def render(self):
        msg = self.msg
        size = 11.0 * self.zoom
        h = mime.body_part(msg, "html")
        self.html = h
        if h is not None:
            images = {a["cid"]: a["data"] for a in self.atts if a["cid"]}
            allow = self.remote
            if allow is None and self._sender() in (self.win.store.get("safe-senders", []) or []):
                allow = {}
                self.remote_pending = True
                GLib.idle_add(self.download_pictures)
            self.view.show_html(h, images, allow, size=size)
            blocked = self.view.blocked
        else:
            self.view.show_text(mime.text_of(msg) or "", size=size)
            blocked = 0
        if blocked and self.remote is None:
            self.bar_label.set_text("To help protect your privacy, Folio Post didn't download %d picture%s in this "
                                    "message." % (blocked, "" if blocked == 1 else "s"))
            self.bar.show_all()
            self.bar.set_visible(True)
        else:
            self.bar.set_visible(False)

    def download_pictures(self):
        if self.msg is None or self.html is None:
            return False
        urls = remote_images(self.html)
        mid = self.mid
        self.bar_label.set_text("Downloading pictures...")

        def work():
            data = fetch_remote(urls)
            GLib.idle_add(done, data)

        def done(data):
            if self.mid == mid:
                self.remote = data
                self.render()
            return False
        threading.Thread(target=work, daemon=True).start()
        return False

    def trust_sender(self):
        s = self._sender()
        if s:
            safe = self.win.store.get("safe-senders", []) or []
            if s not in safe:
                safe.append(s)
                self.win.store.put("safe-senders", safe)
        self.download_pictures()

    def set_zoom(self, z):
        self.zoom = z
        if self.msg is not None:
            self.render()

    # ------------------------------------------------------------ attachments
    def _att_button(self, a):
        b = Gtk.MenuButton()
        b.set_relief(Gtk.ReliefStyle.NONE)
        b.get_style_context().add_class("folio-attachment")
        bx = Gtk.Box(spacing=6)
        bx.pack_start(icons.image("p-attach", 16), False, False, 0)
        lab = Gtk.Label(xalign=0)
        lab.set_markup("%s\n<small>%s</small>" % (GLib.markup_escape_text(a["name"]), nice_size(a["size"])))
        bx.pack_start(lab, False, False, 0)
        b.add(bx)
        b.set_tooltip_text(a["name"])
        menu = Gtk.Menu()
        for label, fn in (("Open", lambda *_: self.open_attachment(a)), ("Save As...", lambda *_: self.save_attachment(a)),
                          ("Save All Attachments...", lambda *_: self.save_all()),
                          ("Copy", lambda *_: self.copy_attachment(a))):
            mi = Gtk.MenuItem(label=label)
            mi.connect("activate", fn)
            menu.append(mi)
        menu.show_all()
        b.set_popup(menu)
        b.attachment = a
        return b

    def open_attachment(self, a):
        d = tempfile.mkdtemp(prefix="folio-post-")
        path = os.path.join(d, os.path.basename(a["name"]) or "attachment")
        with open(path, "wb") as fh:
            fh.write(a["data"])
        os.chmod(path, 0o400)
        if path.lower().endswith((".eml",)):
            self.win.app.windows[0].open_message_file(path) if self.win.app.windows else None
            return
        try:
            subprocess.Popen(["xdg-open", path])
        except OSError:
            self.win.dialogs.message("There's no app to open “%s”." % a["name"])

    def save_attachment(self, a):
        dlg = Gtk.FileChooserDialog(title="Save Attachment", transient_for=self.get_toplevel(),
                                    action=Gtk.FileChooserAction.SAVE)
        dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Save", Gtk.ResponseType.OK)
        dlg.set_do_overwrite_confirmation(True)
        dlg.set_current_name(os.path.basename(a["name"]))
        if dlg.run() == Gtk.ResponseType.OK:
            with open(dlg.get_filename(), "wb") as fh:
                fh.write(a["data"])
        dlg.destroy()

    def save_all(self, folder=None):
        shown = [a for a in self.atts if not a["inline"]]
        if folder is None:
            dlg = Gtk.FileChooserDialog(title="Save All Attachments", transient_for=self.get_toplevel(),
                                        action=Gtk.FileChooserAction.SELECT_FOLDER)
            dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Save", Gtk.ResponseType.OK)
            ok = dlg.run() == Gtk.ResponseType.OK
            folder = dlg.get_filename() if ok else None
            dlg.destroy()
        if not folder:
            return []
        out = []
        for a in shown:
            name = os.path.basename(a["name"]) or "attachment"
            path = os.path.join(folder, name)
            base, ext = os.path.splitext(path)
            k = 1
            while os.path.exists(path):
                k += 1
                path = "%s (%d)%s" % (base, k, ext)
            with open(path, "wb") as fh:
                fh.write(a["data"])
            out.append(path)
        return out

    def copy_attachment(self, a):
        d = tempfile.mkdtemp(prefix="folio-post-")
        path = os.path.join(d, os.path.basename(a["name"]))
        with open(path, "wb") as fh:
            fh.write(a["data"])
        from gi.repository import Gdk
        cb = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        cb.set_text("file://" + path, -1)

    def open_link(self, url):
        if url.startswith("mailto:"):
            self.win.app.compose_mailto(url)
            return
        if not url.startswith(("http:", "https:", "ftp:")):
            return
        try:
            subprocess.Popen(["xdg-open", url])
        except OSError:
            pass

    def selected_text(self):
        b = self.view.buf
        if b.get_has_selection():
            s, e = b.get_selection_bounds()
            return b.get_text(s, e, False)
        return ""
