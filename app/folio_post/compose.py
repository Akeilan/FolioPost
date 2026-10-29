"""The message window for writing: From, To, Cc, Bcc, Subject, attachments and the formatted
body, with the Message, Insert, Options, Format Text and Review tabs."""
import html
import os
import re
import time
from email.utils import getaddresses, parseaddr

from gi.repository import Gdk, GLib, Gtk, Pango, PangoCairo

from . import APP_NAME, icons, mime
from .dialogs import Dialogs
from .readingpane import nice_size
from .richedit import RichEditor
from . import writered


def make_editor():
    """Writer's editor (M-04) when its engine is here, else Post's own."""
    if writered.available():
        try:
            return writered.WriterEditor()
        except Exception as e:
            print("Folio Post: Writer's editor failed to start:", e)
    return RichEditor()
from .ribbon import CheckControl, ComboControl, Ribbon, SplitButton, Tab, menu_popover
from .ribbon_post import Builder

FONT_SIZES = ["8", "9", "10", "11", "12", "14", "16", "18", "20", "22", "24", "26", "28", "36", "48", "72"]
COLORS = ["000000", "FFFFFF", "44546A", "4472C4", "ED7D31", "A5A5A5", "FFC000", "5B9BD5", "70AD47", "C00000",
          "FF0000", "FFFF00", "92D050", "00B050", "00B0F0", "0070C0", "002060", "7030A0"]
HIGHLIGHTS = ["FFFF00", "00FF00", "00FFFF", "FF00FF", "0000FF", "FF0000", "000080", "008080", "008000", "800080",
              "800000", "808000", "808080", "C0C0C0"]
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def parse_recipients(text):
    """'Ann <ann@x.org>; bob@y.org' → [(name, address)]; bare names stay with an empty address."""
    text = (text or "").replace(";", ",")
    out = []
    for n, a in getaddresses([text]):
        n, a = n.strip(), a.strip()
        if not a and not n:
            continue
        if a and "@" not in a and not n:
            n, a = a, ""
        out.append((n, a))
    return out


def speller(app):
    try:
        import enchant
    except ImportError:
        return None
    for lang in (app.setting("language", ""), "en_US", "en_GB"):
        if not lang:
            continue
        try:
            return enchant.Dict(lang)
        except Exception:
            continue
    return None


def system_fonts():
    fm = PangoCairo.FontMap.get_default()
    return sorted(set(f.get_name() for f in fm.list_families()))


def palette(on_pick, colors, none_label=None, ref=None):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    box.set_border_width(8)
    if none_label:
        nb = Gtk.Button(label=none_label)
        nb.set_relief(Gtk.ReliefStyle.NONE)
        nb.connect("clicked", lambda *_: (ref[0].popdown() if ref and ref[0] else None, on_pick(None)))
        box.pack_start(nb, False, False, 0)
    grid = Gtk.Grid(column_spacing=3, row_spacing=3)
    for i, c in enumerate(colors):
        b = Gtk.Button()
        b.get_style_context().add_class("folio-swatch")
        css = Gtk.CssProvider()
        css.load_from_data(("button { background: #%s; min-width: 16px; min-height: 16px; }" % c).encode())
        b.get_style_context().add_provider(css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        b.set_tooltip_text("#" + c)
        b.connect("clicked", lambda _b, c=c: (ref[0].popdown() if ref and ref[0] else None, on_pick(c)))
        grid.attach(b, i % 9, i // 9, 1, 1)
    box.pack_start(grid, False, False, 0)
    return box


def color_menu(win, cmd, colors, none_label):
    ref = [None]

    def make():
        pop = Gtk.Popover()
        ref[0] = pop
        pop.add(palette(lambda c: win.run("%s:%s" % (cmd, c or "none")), colors, none_label, ref))
        return pop
    return make


from .voting import PRESETS as VOTING_PRESETS  # noqa: E402


class ComposeWindow(Gtk.Window):
    def __init__(self, app, account=None, to="", cc="", bcc="", subject="", body_text="", reply_to=None, mode=None,
                 draft=None, attach=(), attach_data=()):
        Gtk.Window.__init__(self)
        self.app = app
        self.store = app.store
        self.dialogs = Dialogs(self)
        self.attachments = []            # (name, type, bytes)
        self.original = None             # the message replied to / forwarded: (mid, msg)
        self.mode = mode
        self.draft_id = None
        self.modified = False
        self.plain = False
        self.importance = 1
        self.read_receipt = False
        self.voting = []
        self.delivery_receipt = False
        self.send_at = 0
        self.reply_to_addr = ""
        self.sent = False
        self.missing_log = []
        self.set_default_size(980, 760)
        self.set_icon_name("folio-post")
        self.connect("delete-event", self.on_delete)
        self.connect("key-press-event", self.on_key)

        self.header = Gtk.HeaderBar()
        self.header.set_show_close_button(True)
        self.header.get_style_context().add_class("folio-titlebar")
        self.title_label = Gtk.Label(label="Untitled - Message (HTML)")
        self.title_label.get_style_context().add_class("title")
        self.header.set_custom_title(self.title_label)
        self.qat = Gtk.Box()
        for icon, cmd, tip in (("qat-save", "save", "Save (Ctrl+S)"), ("r-undo-sm", "undo", "Undo (Ctrl+Z)"),
                               ("r-redo-sm", "redo", "Redo (Ctrl+Y)")):
            b = Gtk.Button()
            b.add(icons.white_image(icon, 16))
            b.set_tooltip_text(tip)
            b.set_focus_on_click(False)
            b.connect("clicked", lambda _b, c=cmd: self.run(c))
            self.qat.pack_start(b, False, False, 0)
        self.header.pack_start(self.qat)
        self.set_titlebar(self.header)

        self.overlay = Gtk.Overlay()
        self.add(self.overlay)
        self.outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.overlay.add(self.outer)
        self.ribbon = Ribbon(self.run, self.focus_document)
        self.ribbon.connect("file-clicked", lambda *_: self.show_backstage())
        self.outer.pack_start(self.ribbon, False, False, 0)

        # ---- the address block
        head = Gtk.Box(spacing=8)
        head.get_style_context().add_class("folio-compose-head")
        head.set_border_width(8)
        send = Gtk.Button()
        sb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        sb.pack_start(icons.image("p-send", 32), False, False, 0)
        sb.pack_start(Gtk.Label(label="Send"), False, False, 0)
        send.add(sb)
        send.get_style_context().add_class("folio-send")
        send.set_tooltip_text("Send (Alt+S / Ctrl+Enter)")
        send.connect("clicked", lambda *_: self.run("send"))
        send.set_valign(Gtk.Align.START)
        self.send_button = send
        head.pack_start(send, False, False, 0)
        grid = Gtk.Grid(column_spacing=6, row_spacing=4)
        self.fields = {}
        self.from_combo = Gtk.ComboBoxText()
        self.accounts = [a for a in self.store.accounts() if a["kind"] != "rss"]
        for a in self.accounts:
            self.from_combo.append(str(a["id"]), "%s <%s>" % (a["name"] or a["email"], a["email"]) if a["name"] else a["email"])
        row = 0
        self.from_label = Gtk.Button(label="From ▾")
        self.from_label.set_relief(Gtk.ReliefStyle.NONE)
        self.from_label.connect("clicked", lambda *_: self.from_combo.popup())
        grid.attach(self.from_label, 0, row, 1, 1)
        grid.attach(self.from_combo, 1, row, 1, 1)
        self.from_row = [self.from_label, self.from_combo]
        row += 1
        completion_model = self._address_model()
        for key, label in (("to", "To..."), ("cc", "Cc..."), ("bcc", "Bcc...")):
            b = Gtk.Button(label=label)
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.connect("clicked", lambda _b, k=key: self.pick_names(k))
            e = Gtk.Entry()
            e.set_hexpand(True)
            comp = Gtk.EntryCompletion()
            comp.set_model(completion_model)
            comp.set_text_column(0)
            comp.set_match_func(self._match, key)
            comp.connect("match-selected", self._completed, key)
            e.set_completion(comp)
            e.connect("changed", lambda *_: self._dirty())
            e.connect("focus-out-event", lambda w, ev, k=key: (self.check_names(k, quiet=True), False)[1])
            grid.attach(b, 0, row, 1, 1)
            grid.attach(e, 1, row, 1, 1)
            self.fields[key] = e
            if key == "bcc":
                self.bcc_row = [b, e]
            row += 1
        grid.attach(Gtk.Label(label="Subject", xalign=0, margin_start=10), 0, row, 1, 1)
        self.subject = Gtk.Entry()
        self.subject.connect("changed", lambda *_: (self._dirty(), self.update_title()))
        grid.attach(self.subject, 1, row, 1, 1)
        head.pack_start(grid, True, True, 0)
        self.outer.pack_start(head, False, False, 0)
        # attachments
        self.att_box = Gtk.FlowBox()
        self.att_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self.att_box.set_max_children_per_line(5)
        self.att_box.set_margin_start(100)
        self.att_box.set_no_show_all(True)
        self.outer.pack_start(self.att_box, False, False, 0)
        # body
        self.editor = make_editor()
        self.editor.on_state = self.sync_ribbon
        self.editor.connect_changed(lambda *_: self._dirty())
        self.editor.connect("focus-in-event", lambda *_: (self.sync_ribbon(self.editor.state()), False)[1])
        self.setup_spelling()
        self.editor.drag_dest_set(Gtk.DestDefaults.ALL, [Gtk.TargetEntry.new("text/uri-list", 0, 0)], Gdk.DragAction.COPY)
        self.editor.connect("drag-data-received", self._dropped)
        sw = Gtk.ScrolledWindow()
        sw.add(self.editor)
        body = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        body.pack1(sw, True, False)
        self.quote_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.quote_box.set_no_show_all(True)
        body.pack2(self.quote_box, True, False)
        self.body_paned = body
        self.outer.pack_start(body, True, True, 0)
        self.status = Gtk.Label(xalign=0)
        self.status.get_style_context().add_class("folio-status")
        self.outer.pack_start(self.status, False, False, 0)
        self.build_ribbon()
        from .keytips import KeyTips
        self.keytips = KeyTips(self)
        self.show_all()
        for w in self.bcc_row:
            w.set_visible(bool(bcc) or bool(self.app.setting("show_bcc")))
        show_from = len(self.accounts) > 1 or bool(self.app.setting("show_from"))
        for w in self.from_row:
            w.set_visible(show_from)

        # ---- content
        aid = account
        if aid is None and self.accounts:
            aid = self.accounts[0]["id"]
        if aid is not None:
            self.from_combo.set_active_id(str(aid))
        self._loading = True
        if draft:
            self.load_draft(draft)
        else:
            self.fields["to"].set_text(to or "")
            self.fields["cc"].set_text(cc or "")
            self.fields["bcc"].set_text(bcc or "")
            self.subject.set_text(subject or "")
            if reply_to:
                self.setup_reply(reply_to, mode or "reply")
            sig = self.signature("reply" if reply_to else "new")
            if body_text:
                self.editor.load_html("<p>%s</p>" % html.escape(body_text).replace("\n", "<br>"))
            elif sig:
                self.editor.load_html("<p><br></p><p><br></p>" + sig)
            self.editor.caret_to_start()
            for p in attach or ():
                p = p[7:] if p.startswith("file://") else p
                if os.path.isfile(p):
                    self.attachments.append(mime.file_attachment(p))
            for a in attach_data or ():
                self.attachments.append(a)
            self.refresh_attachments()
        self._loading = False
        self.modified = False
        self.editor.undo = []
        self.update_title()
        if self.fields["to"].get_text() or reply_to:
            GLib.idle_add(lambda: (self.editor.grab_focus(), False)[1])
        else:
            GLib.idle_add(lambda: (self.fields["to"].grab_focus(), False)[1])
        self._autosave = GLib.timeout_add_seconds(int(self.app.setting("autosave_minutes", 3)) * 60, self._autosave_tick)

    # ================================================================ ribbon
    def build_ribbon(self):
        B = Builder(self)
        r = self.ribbon
        na = lambda n: "not-available:" + n  # noqa: E731
        t = r.building(Tab("Message", "H"))
        B.group(t, "Clipboard", [
            B.big("Paste", "r-paste", "paste", "V", menu=[("Paste", "paste"), ("Keep Text Only", "paste-text")]),
            [B.small("Cut", "r-cut-sm", "cut", "X"), B.small("Copy", "r-copy-sm", "copy", "C"),
             B.small("Format Painter", "r-format-painter-sm", "format-painter", "FP")],
        ])
        self.font_combo = ComboControl(r, system_fonts(), lambda v: self.run("font:" + v), 14, state="font", keytip="FF",
                                       tooltip="Font")
        self.size_combo = ComboControl(r, FONT_SIZES, lambda v: self.run("size:" + v), 3, state="size", keytip="FS",
                                       tooltip="Font Size")
        B.group(t, "Basic Text", [
            [[self.font_combo, self.size_combo,
              B.small(None, "r-grow-sm", "grow", "FG", tip="Increase Font Size (Ctrl+Shift+>)"),
              B.small(None, "r-shrink-sm", "shrink", "FK", tip="Decrease Font Size (Ctrl+Shift+<)")],
             [B.small(None, "r-bold-sm", "bold", "1", tip="Bold (Ctrl+B)", state="bold"),
              B.small(None, "r-italic-sm", "italic", "2", tip="Italic (Ctrl+I)", state="italic"),
              B.small(None, "r-underline-sm", "underline", "3", tip="Underline (Ctrl+U)", state="underline"),
              SplitButton(r, None, "r-marker-color-sm", "highlight:FFFF00", color_menu(self, "highlight", HIGHLIGHTS, "No Color"),
                          size="icon", keytip="I", tooltip="Text Highlight Color"),
              SplitButton(r, None, "r-font-color-sm", "color:C00000", color_menu(self, "color", COLORS, "Automatic"),
                          size="icon", keytip="FC", tooltip="Font Color"),
              B.small(None, "defaultbullet", "bullets", "U", tip="Bullets (Ctrl+Shift+L)", state="bullets"),
              B.small(None, "defaultnumbering", "numbering", "N", tip="Numbering", state="numbering"),
              B.small(None, "decrementindent", "outdent", "AO", tip="Decrease Indent"),
              B.small(None, "incrementindent", "indent", "AI", tip="Increase Indent"),
              B.small(None, "r-clear-sm", "clear-formatting", "E", tip="Clear All Formatting (Ctrl+Space)"),
              B.small(None, "alignleft", "align:left", "AL", tip="Align Left (Ctrl+L)", state="align-left"),
              B.small(None, "aligncenter", "align:center", "AC", tip="Center (Ctrl+E)", state="align-center"),
              B.small(None, "alignright", "align:right", "AR", tip="Align Right (Ctrl+R)", state="align-right")]],
        ], launcher="font-dialog")
        B.group(t, "Names", [
            [B.small("Address Book", "p-address-book", "address-book", "AB"),
             B.small("Check Names", "p-check-names", "check-names", "M", tip="Check Names (Ctrl+K)")],
        ])
        B.group(t, "Include", [
            B.big("Attach File", "p-attach", "attach-file", "AF"),
            [B.small("Attach Item", "p-attach-item", "attach-item", "AI"),
             B.small("Signature", "p-signature", None, "G", menu=lambda: self.signature_menu())],
        ])
        B.group(t, "Tags", [
            [B.small("Follow Up", "p-flag", "flag", "W", state="flagged"),
             B.small("High Importance", "p-high", "importance:2", "H", state="imp-high"),
             B.small("Low Importance", "p-low", "importance:0", "L", state="imp-low")],
        ])
        r.add_tab(t)

        t = r.building(Tab("Insert", "N"))
        B.group(t, "Include", [
            B.big("Attach File", "p-attach", "attach-file", "AF"),
            B.big("Attach Item", "p-attach-item", "attach-item", "AI"),
            B.big("Signature", "p-signature", None, "G", menu=lambda: self.signature_menu()),
        ])
        B.group(t, "Tables", [B.big("Table", "inserttable", None, "T", menu=[("2 × 2", "insert-table:2x2"), ("3 × 3", "insert-table:3x3"),
                                                                             ("4 × 4", "insert-table:4x4"), ("2 × 5", "insert-table:5x2"),
                                                                             None, ("Insert Table...", "insert-table")])])
        B.group(t, "Illustrations", [B.big("Pictures", "insertgraphic", "insert-picture", "P")])
        B.group(t, "Links", [B.big("Link", "inserthyperlink", "insert-link", "I", tip="Link (Ctrl+K)")])
        B.group(t, "Text", [
            [B.small("Date & Time", "insertdatefield", "insert-date", "DT"),
             B.small("Horizontal Line", "line", "insert-line", "HL")],
        ])
        r.add_tab(t)

        t = r.building(Tab("Options", "P"))
        B.group(t, "Show Fields", [B.big("Bcc", "p-bcc", "toggle-bcc", "B"), B.big("From", "p-from", "toggle-from", "F")])
        B.group(t, "Encrypt", [B.big("Encrypt", "p-properties", "toggle-encrypt", "E", tip="Encrypt (S/MIME with your certificate, else OpenPGP)", state="encrypt"),
                               B.big("Sign", "p-signature", "toggle-sign", "SG", tip="Sign (S/MIME with your certificate, else OpenPGP)", state="sign")])
        self.receipt_check = CheckControl(r, "Request a Read Receipt", "toggle-read-receipt", state="read-receipt", keytip="Q")
        self.delivery_check = CheckControl(r, "Request a Delivery Receipt", "toggle-delivery-receipt",
                                           state="delivery-receipt", keytip="R")
        B.group(t, "Tracking", [B.big("Use Voting Buttons", "p-flag", None, "V",
                                      menu=[(label, "voting:" + v) for label, v in VOTING_PRESETS] +
                                      [("Custom...", "voting:custom"), None, ("No Voting Buttons", "voting:clear")],
                                      tip="Use Voting Buttons: the people you send this to answer with one click"),
                                [self.delivery_check, self.receipt_check]])
        B.group(t, "More Options", [
            B.big("Delay Delivery", "p-delay", "delay-delivery", "DD"),
            B.big("Direct Replies To", "p-reply", "direct-replies", "DR"),
        ])
        r.add_tab(t)

        t = r.building(Tab("Format Text", "O"))
        B.group(t, "Format", [
            [B.small("HTML", "newhtmldoc", "format:html", "H", state="fmt-html"),
             B.small("Plain Text", "textdirectionlefttoright", "format:plain", "T", state="fmt-plain")],
        ])
        B.group(t, "Font", [
            [[B.small(None, "r-bold-sm", "bold", "1", tip="Bold (Ctrl+B)", state="bold"),
              B.small(None, "r-italic-sm", "italic", "2", tip="Italic (Ctrl+I)", state="italic"),
              B.small(None, "r-underline-sm", "underline", "3", tip="Underline (Ctrl+U)", state="underline"),
              B.small(None, "strikeout", "strike", "4", tip="Strikethrough", state="strike")]],
        ])
        B.group(t, "Paragraph", [
            [[B.small(None, "defaultbullet", "bullets", "U", tip="Bullets"),
              B.small(None, "defaultnumbering", "numbering", "N", tip="Numbering"),
              B.small(None, "alignblock", "align:justify", "AJ", tip="Justify")]],
        ])
        r.add_tab(t)

        t = r.building(Tab("Review", "R"))
        B.group(t, "Proofing", [B.big("Spelling & Grammar", "spelling", "spelling", "S", tip="Spelling & Grammar (F7)"),
                                B.big("Word Count", "wordcountdialog", "word-count", "W")])
        r.add_tab(t)
        r.select(r.tab_by_name("Message"))

    def sync_ribbon(self, st):
        if not hasattr(self, "ribbon"):
            return
        for k in ("bold", "italic", "underline", "strike"):
            self.ribbon.update(k, "true" if st.get(k) else "false")
        for a in ("left", "center", "right"):
            self.ribbon.update("align-" + a, "true" if st.get("align") == a else "false")
        self.ribbon.update("bullets", "true" if st.get("list") == "bullet" else "false")
        self.ribbon.update("numbering", "true" if st.get("list") == "number" else "false")
        self.ribbon.update("font", st.get("font") or "")
        sz = st.get("size")
        self.ribbon.update("size", ("%g" % float(sz)) if sz else "")

    def sync_tags(self):
        self.ribbon.update("imp-high", "true" if self.importance == 2 else "false")
        self.ribbon.update("imp-low", "true" if self.importance == 0 else "false")
        self.ribbon.update("flagged", "true" if getattr(self, "flagged", False) else "false")
        self.ribbon.update("fmt-html", "false" if self.plain else "true")
        self.ribbon.update("fmt-plain", "true" if self.plain else "false")

    # ================================================================ fields
    def _address_model(self):
        model = Gtk.ListStore(str, str)
        names = {}
        order = []
        for n, a in (self.store.get("recent-addresses", []) or []):
            k = a.lower()
            if k not in names:
                order.append(k)
                names[k] = [n, a]
            elif n and not names[k][0]:
                names[k][0] = n
        for r in self.store.q("select from_name, from_addr, max(date) d from messages where from_addr!='' group by "
                              "lower(from_addr) order by d desc limit 2000"):
            a = r["from_addr"]
            n = r["from_name"] if r["from_name"] != a else ""
            k = a.lower()
            if k not in names:
                order.append(k)
                names[k] = [n, a]
            elif n and not names[k][0]:
                names[k][0] = n
        # contacts first: the address book's names win
        for r in self.store.contacts():
            if r["is_group"]:
                model.prepend([r["name"], (r["name"] + " group").lower()])
                continue
            for a in [x for x in (r["emails"] or "").split(",") if x]:
                k = a.lower()
                if k in names:
                    order.remove(k)
                names[k] = [r["name"], a]
                order.insert(0, k)
        for k in order:
            n, a = names[k]
            model.append(["%s <%s>" % (n, a) if n else a, (n + " " + a).lower()])
        return model

    def groups(self):
        return {r["name"].lower(): r for r in self.store.contacts() if r["is_group"]}

    def _current_token(self, entry):
        text = entry.get_text()
        pos = entry.get_position()
        start = max(text.rfind(";", 0, pos), text.rfind(",", 0, pos)) + 1
        return text[start:pos].strip().lower(), start, pos

    def _match(self, comp, key, it, field):
        tok = self._current_token(self.fields[field])[0]
        if len(tok) < 1:
            return False
        hay = comp.get_model()[it][1]
        return any(w.startswith(tok) for w in re.split(r"[\s<>@.]+", hay)) or hay.startswith(tok)

    def _completed(self, comp, model, it, field):
        e = self.fields[field]
        text = e.get_text()
        _tok, start, pos = self._current_token(e)
        new = text[:start] + (" " if start else "") + model[it][0] + "; " + text[pos:].lstrip(";, ")
        e.set_text(new)
        e.set_position(len(text[:start]) + len(model[it][0]) + 3)
        return True

    def recipients(self, key):
        return parse_recipients(self.fields[key].get_text())

    def check_names(self, key=None, quiet=False):
        """Resolves names to addresses from the people Post knows; marks the ones it can't."""
        known = {}
        m = self._address_model()
        for row in m:
            n, a = parseaddr(row[0])
            if n:
                known.setdefault(n.lower(), (n, a))
        bad = []
        groups = self.groups()
        for k in ([key] if key else ["to", "cc", "bcc"]):
            out = []
            changed = False
            for n, a in self.recipients(k):
                if not a and n.lower() in groups:
                    out.append((n, a))
                    continue
                if not a:
                    hit = known.get(n.lower())
                    if hit is None:
                        cands = [v for kk, v in known.items() if n.lower() in kk]
                        hit = cands[0] if len(cands) == 1 else None
                    if hit:
                        n, a = hit
                        changed = True
                if not a or not EMAIL_RE.match(a):
                    bad.append(n or a)
                out.append((n, a))
            if changed:
                self.fields[k].set_text("; ".join(("%s <%s>" % (n, a)) if n else a for n, a in out) + ("; " if out else ""))
        if bad and not quiet:
            self.dialogs.message("Folio Post doesn't recognize %s. Type the full e-mail address." % ", ".join("“%s”" % b for b in bad),
                                 "Check Names")
        return not bad

    def pick_names(self, key):
        from .contactwin import select_names
        got = select_names(self, "Select Names: Contacts", ["To", "Cc", "Bcc"])
        if not got:
            return
        for k in ("To", "Cc", "Bcc"):
            items = got.get(k) or []
            if not items:
                continue
            e = self.fields[k.lower()]
            cur = e.get_text().strip()
            if cur and not cur.endswith(";"):
                cur += ";"
            add = []
            for kind, name, value in items:
                add.append(name if kind == "group" else ("%s <%s>" % (name, value) if name else value))
            e.set_text((cur + " " if cur else "") + "; ".join(add) + "; ")
            if k == "Bcc":
                for w in self.bcc_row:
                    w.show()

    def account(self):
        aid = self.from_combo.get_active_id()
        return self.store.account(int(aid)) if aid else None

    # ================================================================ content
    def signature(self, kind="new"):
        sigs = self.store.get("signatures", {}) or {}
        acc = self.account()
        prefs = self.store.get("signature-defaults", {}) or {}
        p = prefs.get(str(acc["id"]) if acc else "", {}) or prefs.get("", {})
        name = p.get(kind)
        return sigs.get(name, "") if name else ""

    def signature_menu(self):
        sigs = self.store.get("signatures", {}) or {}
        return [(n, "insert-signature:" + n) for n in sorted(sigs)] + [None, ("Signatures...", "signatures")]

    def setup_reply(self, mid, mode):
        m = self.store.message(mid)
        raw = self.store.raw(mid)
        msg = mime.parse(raw)
        self.original = (mid, msg)
        subj = mime.header(msg, "Subject")
        prefix = "FW: " if mode == "forward" else "RE: "
        base = re.sub(r"^((re|fw|fwd|aw|sv|wg)\s*:\s*)+", "", subj or "", flags=re.I)
        self.subject.set_text(prefix + base)
        me = set(a["email"].lower() for a in self.store.accounts())
        if mode in ("reply", "reply-all"):
            rt = mime.addresses(msg, "Reply-To") or mime.addresses(msg, "From")
            frm_addr = (mime.addresses(msg, "From") or [("", "")])[0][1].lower()
            if frm_addr in me:
                # replying to one's own sent message goes to its recipients
                rt = mime.addresses(msg, "To")
            to = [x for x in rt]
            cc = []
            if mode == "reply-all":
                seen = {t[1].lower() for t in to} | me
                for n, a in mime.addresses(msg, "To"):
                    if a and a.lower() not in seen:
                        to.append((n, a))
                        seen.add(a.lower())
                for n, a in mime.addresses(msg, "Cc"):
                    if a and a.lower() not in seen:
                        cc.append((n, a))
                        seen.add(a.lower())
            self.fields["to"].set_text("; ".join(("%s <%s>" % (n, a)) if n else a for n, a in to) + ("; " if to else ""))
            if cc:
                self.fields["cc"].set_text("; ".join(("%s <%s>" % (n, a)) if n else a for n, a in cc) + "; ")
        else:
            # forwarding keeps the attachments
            for a in mime.attachments(msg):
                if not a["inline"]:
                    self.attachments.append((a["name"], a["type"], a["data"]))
        # which account: the one the message came to
        f = self.store.folder(m["folder"]) if m else None
        if f:
            self.from_combo.set_active_id(str(f["account"]))
        self.show_quote(msg)

    def show_quote(self, msg):
        from .htmlview import MessageView
        for c in self.quote_box.get_children():
            self.quote_box.remove(c)
        sep = Gtk.Separator()
        self.quote_box.pack_start(sep, False, False, 4)
        head = Gtk.Label(xalign=0)
        head.set_markup("\n".join("<b>%s:</b> %s" % (k, GLib.markup_escape_text(v)) for k, v in mime.quote_header(msg)))
        head.set_margin_start(14)
        head.set_selectable(True)
        self.quote_box.pack_start(head, False, False, 4)
        v = MessageView()
        h = mime.body_part(msg, "html")
        images = {a["cid"]: a["data"] for a in mime.attachments(msg) if a["cid"]}
        if h is not None:
            v.show_html(h, images)
        else:
            v.show_text(mime.text_of(msg))
        sw = Gtk.ScrolledWindow()
        sw.add(v)
        sw.set_size_request(-1, 120)
        self.quote_box.pack_start(sw, True, True, 0)
        self.quote_box.set_no_show_all(False)
        self.quote_box.show_all()
        GLib.idle_add(lambda: (self.body_paned.set_position(max(160, self.body_paned.get_allocated_height() // 2)), False)[1])

    def quoted_html(self):
        if not self.original:
            return "", [], ""
        _mid, msg = self.original
        head = "".join("<b>%s:</b> %s<br>" % (k, html.escape(v)) for k, v in mime.quote_header(msg))
        h = mime.body_part(msg, "html")
        if h is not None:
            h = re.sub(r"(?is)<(script|iframe|object|embed)\b.*?</\1>", "", h)
            m = re.search(r"(?is)<body[^>]*>(.*)</body>", h)
            body = m.group(1) if m else h
        else:
            body = "<div style='white-space:pre-wrap'>%s</div>" % html.escape(mime.text_of(msg))
        inline = [(a["cid"], a["type"], a["data"]) for a in mime.attachments(msg) if a["cid"] and a["type"].startswith("image/")]
        quoted = ('<div style="border:none;border-top:solid #E1E1E1 1.0pt;padding:3.0pt 0 0 0"><p style="margin:0">'
                  '<span style="font-family:Calibri,sans-serif;font-size:11pt">%s</span></p></div><br>%s' % (head, body))
        text = "\n\n" + "_" * 32 + "\n" + "\n".join("%s: %s" % kv for kv in mime.quote_header(msg)) + "\n\n" + \
               mime.text_of(msg)
        return quoted, inline, text

    def load_draft(self, mid):
        raw = self.store.raw(mid)
        msg = mime.parse(raw)
        self.draft_id = mid
        for k, h in (("to", "To"), ("cc", "Cc"), ("bcc", "Bcc")):
            v = mime.show_addresses(mime.addresses(msg, h)) and "; ".join(
                ("%s <%s>" % (n, a)) if n else a for n, a in mime.addresses(msg, h))
            self.fields[k].set_text(v or "")
            if k == "bcc" and v:
                for w in self.bcc_row:
                    w.show()
        self.subject.set_text(mime.header(msg, "Subject"))
        h = mime.body_part(msg, "html")
        if h is not None:
            # pictures by content id come back as data
            import base64
            for a in mime.attachments(msg):
                if a["cid"]:
                    h = h.replace("cid:" + a["cid"], "data:%s;base64,%s" % (a["type"], base64.b64encode(a["data"]).decode()))
            self.editor.load_html(h)
        else:
            self.plain = True
            self.editor.load_html("<p>%s</p>" % html.escape(mime.text_of(msg)).replace("\n", "<br>"))
        for a in mime.attachments(msg):
            if not a["inline"]:
                self.attachments.append((a["name"], a["type"], a["data"]))
        imp = mime.header(msg, "Importance").lower()
        self.importance = 2 if imp == "high" else 0 if imp == "low" else 1
        from .voting import parse_choices
        self.voting = parse_choices(mime.header(msg, "X-Folio-Voting"))
        self.refresh_attachments()
        self.sync_tags()

    def refresh_attachments(self):
        for c in self.att_box.get_children():
            self.att_box.remove(c)
        for i, (name, _t, data) in enumerate(self.attachments):
            b = Gtk.Box(spacing=4)
            b.get_style_context().add_class("folio-attachment")
            b.pack_start(icons.image("p-attach", 16), False, False, 0)
            b.pack_start(Gtk.Label(label="%s (%s)" % (name, nice_size(len(data)))), False, False, 0)
            x = Gtk.Button(label="×")
            x.set_relief(Gtk.ReliefStyle.NONE)
            x.set_tooltip_text("Remove Attachment")
            x.connect("clicked", lambda _b, i=i: self.remove_attachment(i))
            b.pack_start(x, False, False, 0)
            self.att_box.add(b)
        self.att_box.set_visible(bool(self.attachments))
        self.att_box.show_all()

    def remove_attachment(self, i):
        del self.attachments[i]
        self.refresh_attachments()
        self._dirty()

    def _dropped(self, w, ctx, x, y, data, info, t):
        for uri in data.get_uris() or []:
            path = GLib.filename_from_uri(uri)[0] if uri.startswith("file:") else None
            if path and os.path.isfile(path):
                self.attachments.append(mime.file_attachment(path))
        self.refresh_attachments()
        self._dirty()

    def _dirty(self):
        if not getattr(self, "_loading", False):
            self.modified = True

    def update_title(self):
        s = self.subject.get_text().strip() or "Untitled"
        self.title_label.set_text("%s - Message (%s)" % (s, "Plain Text" if self.plain else "HTML"))
        self.set_title(self.title_label.get_text())

    # ================================================================ building the message
    def build(self, for_draft=False):
        acc = self.account()
        sender = (acc["name"], acc["email"]) if acc else ("", "")
        if acc and acc["name"] == acc["email"]:
            sender = ("", acc["email"])
        to, cc, bcc = self.recipients("to"), self.recipients("cc"), self.recipients("bcc")
        groups = self.groups()
        if groups:
            from .contactwin import expand_groups

            def ex(xs):
                return expand_groups(self.store, [("", "group:%d" % groups[n.lower()]["id"]) if (not a and n.lower() in groups)
                                                  else (n, a) for n, a in xs])
            to, cc, bcc = ex(to), ex(cc), ex(bcc)
        fix = lambda xs: [(n, a) if a else ("", n) for n, a in xs]  # noqa: E731
        subject = self.subject.get_text()
        body_html, pics = self.editor.to_html()
        text = self.editor.text()
        quoted, qpics, qtext = self.quoted_html()
        extra = {}
        if self.reply_to_addr:
            extra["Reply-To"] = self.reply_to_addr
        if self.delivery_receipt:
            extra["Return-Receipt-To"] = sender[1]
        if getattr(self, "flagged", False):
            extra["X-Message-Flag"] = "Follow up"
        in_reply_to = refs = None
        if self.original and self.mode in ("reply", "reply-all"):
            _mid, om = self.original
            in_reply_to = mime.header(om, "Message-ID").strip() or None
            refs = (mime.header(om, "References").strip() + " " + (in_reply_to or "")).strip() or None
        vote_text = vote_html = ""
        if self.voting and not for_draft:
            from . import voting
            extra[voting.HEADER] = ";".join(self.voting)
            vote_text, vote_html = voting.footer(self.voting, sender[1], subject)
        elif self.voting:
            extra["X-Folio-Voting"] = ";".join(self.voting)
        if self.plain:
            html_body = None
            inline = ()
            text = text + vote_text + qtext
        else:
            text = text + vote_text
            body_html = body_html + vote_html
            full = body_html + (("<br>" + quoted) if quoted else "")
            html_body = ("<html><head><meta charset='utf-8'></head><body>%s</body></html>" % full)
            inline = list(pics) + list(qpics)
            text = text + qtext
        m = mime.build(sender, fix(to), fix(cc), fix(bcc), subject, text, html_body, self.attachments, inline,
                       in_reply_to=in_reply_to, references=refs, importance=self.importance,
                       request_receipt=self.read_receipt, extra=extra)
        if for_draft:
            m["X-Folio-Draft"] = "1"
        return m

    # ================================================================ commands
    def run(self, cmd, *args):
        if cmd is None:
            return None
        name, _, arg = cmd.partition(":")
        fn = getattr(self, "act_" + name.replace("-", "_"), None)
        if fn is None:
            self.missing_log.append(cmd)
            label = arg if name == "not-available" else cmd
            self.dialogs.info("“%s” isn't available yet in %s." % (label, APP_NAME))
            return None
        if self.keytips.active:
            self.keytips.leave()
        try:
            return fn(arg) if arg or _ else fn()
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.dialogs.message("Something went wrong running this command.\n\n%s" % e)
            return None

    def act_not_available(self, label):
        self.missing_log.append("not-available:" + label)
        self.dialogs.info("“%s” isn't available yet in %s." % (label, APP_NAME))

    def focus_document(self):
        self.editor.grab_focus()

    def show_backstage(self, page=None):
        menu = Gtk.Menu()
        for label, cmd in (("Save", "save"), ("Save As...", "save-as"), ("Print", "print"), (None, None),
                           ("Properties...", "properties"), ("Close", "close")):
            if label is None:
                menu.append(Gtk.SeparatorMenuItem())
                continue
            mi = Gtk.MenuItem(label=label)
            mi.connect("activate", lambda _m, c=cmd: self.run(c))
            menu.append(mi)
        menu.show_all()
        menu.popup_at_widget(self.ribbon.file_button, Gdk.Gravity.SOUTH_WEST, Gdk.Gravity.NORTH_WEST, None)
        self._file_menu = menu

    # ---- sending
    def act_send(self):
        acc = self.account()
        if acc is None:
            self.dialogs.message("Add an account before sending: File > Add Account in the main window.")
            return False
        if acc["kind"] == "local":
            self.dialogs.message("This account is kept on this computer only and can't send mail.")
            return False
        if not (self.recipients("to") or self.recipients("cc") or self.recipients("bcc")):
            self.dialogs.message("There must be at least one name or contact group in the To, Cc, or Bcc box.")
            return False
        if not self.check_names():
            return False
        if not self.subject.get_text().strip():
            d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                                  text="Do you want to send this message without a subject?")
            d.add_button("Don't Send", Gtk.ResponseType.NO)
            d.add_button("Send Anyway", Gtk.ResponseType.YES)
            r = d.run()
            d.destroy()
            if r != Gtk.ResponseType.YES:
                return False
        if not self.attachments and re.search(r"\b(attached|attachment|enclosed)\b", self.editor.text(), re.I) and \
                self.app.setting("attachment_reminder", True):
            d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                                  text="You may have forgotten to attach a file.")
            d.add_button("Don't Send", Gtk.ResponseType.NO)
            d.add_button("Send Anyway", Gtk.ResponseType.YES)
            r = d.run()
            d.destroy()
            if r != Gtk.ResponseType.YES:
                return False
        m = self.build()
        rcpts = mime.recipients(m)
        from . import smime
        use_smime = smime.openssl() is not None and smime.has_mine(acc["email"]) and \
            (not getattr(self, "encrypt", False) or not smime.missing_certs(rcpts))
        if use_smime and (getattr(self, "encrypt", False) or getattr(self, "sign", False)):
            try:
                raw = smime.protect(m, encrypt_to=(rcpts + [acc["email"]]) if getattr(self, "encrypt", False) else None,
                                    sign_as=acc["email"] if getattr(self, "sign", False) else None)
            except Exception as e:
                self.dialogs.message("S/MIME didn't work: %s" % e)
                return False
        elif getattr(self, "encrypt", False) or getattr(self, "sign", False):
            from . import pgp
            if pgp.gpg() is None:
                self.dialogs.message("Encrypting and signing need GnuPG (package gnupg).")
                return False
            me = acc["email"]
            if getattr(self, "sign", False) and not pgp.has_key(me, secret=True):
                self.dialogs.message("There's no OpenPGP key of yours for %s on this computer, so the message can't be signed. "
                                     "Make or import one with GnuPG (gpg --gen-key)." % me)
                return False
            if getattr(self, "encrypt", False):
                missing = pgp.missing_keys(rcpts)
                if missing:
                    self.dialogs.message("These recipients have no OpenPGP key on this computer, so the message can't be encrypted "
                                         "for them: %s. Import their keys with GnuPG, or send without encryption." % ", ".join(missing))
                    return False
            try:
                raw = pgp.protect(m, encrypt_to=(rcpts + [me]) if getattr(self, "encrypt", False) else None,
                                  sign_as=me if getattr(self, "sign", False) else None)
            except Exception as e:
                self.dialogs.message("OpenPGP didn't work: %s" % e)
                return False
        else:
            raw = mime.to_bytes(m)
        self.store.queue(acc["id"], raw, rcpts, self.send_at)
        self.remember_addresses(m)
        if self.original:
            mid = self.original[0]
            if self.store.message(mid):
                self.store.set_flag([mid], "forwarded" if self.mode == "forward" else "answered", True)
        if self.draft_id and self.store.message(self.draft_id):
            self.store.delete(self.draft_id)
        self.sent = True
        if not self.app.syncer.offline:
            self.app.send_receive([acc["id"]])
        self.destroy_window()
        return True

    def remember_addresses(self, m):
        rec = self.store.get("recent-addresses", []) or []
        have = {a.lower() for _n, a in rec}
        for h in ("To", "Cc", "Bcc"):
            for n, a in mime.addresses(m, h):
                if a and a.lower() not in have:
                    rec.insert(0, [n, a])
                    have.add(a.lower())
        self.store.put("recent-addresses", rec[:500])

    # ---- drafts
    def act_save(self):
        acc = self.account()
        if acc is None:
            return None
        drafts = self.store.folder_by_role(acc["id"], "drafts")
        if drafts is None:
            drafts = {"id": self.store.ensure_folder(acc["id"], "Drafts", "drafts")}
        raw = mime.to_bytes(self.build(for_draft=True))
        old = self.draft_id
        mid = self.store.add_message(drafts["id"], raw, 0, ["draft", "seen"])
        kind = acc["kind"]
        self.store.set_fields(mid, pending="" if kind in ("local", "pop3") else "new")
        if old and self.store.message(old):
            self.store.delete(old)
        self.draft_id = mid
        self.modified = False
        self.status.set_text("  Saved %s" % time.strftime("%H:%M"))
        self.store.changed("messages")
        return mid

    def _autosave_tick(self):
        if self.modified and not self.sent and (self.subject.get_text() or not self.editor.is_empty()):
            self.act_save()
        return True

    def act_save_as(self):
        dlg = Gtk.FileChooserDialog(title="Save As", transient_for=self, action=Gtk.FileChooserAction.SAVE)
        dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Save", Gtk.ResponseType.OK)
        dlg.set_do_overwrite_confirmation(True)
        dlg.set_current_name((re.sub(r"[^\w .,-]+", "", self.subject.get_text())[:80] or "Untitled") + ".eml")
        for name, pat in (("Message (*.eml)", "*.eml"), ("Outlook Template (*.oft)", "*.oft"), ("Outlook Message (*.msg)", "*.msg")):
            f = Gtk.FileFilter()
            f.set_name(name)
            f.add_pattern(pat)
            dlg.add_filter(f)
        dlg.connect("notify::filter", lambda d, _p: self._save_as_ext(d))
        path = dlg.get_filename() if dlg.run() == Gtk.ResponseType.OK else None
        dlg.destroy()
        if path:
            self.save_to(path)
        return path

    def _save_as_ext(self, dlg):
        f = dlg.get_filter()
        name = dlg.get_current_name() or ""
        ext = {"Outlook Template (*.oft)": ".oft", "Outlook Message (*.msg)": ".msg"}.get(f.get_name() if f else "", ".eml")
        dlg.set_current_name(re.sub(r"\.(eml|oft|msg)$", "", name, flags=re.I) + ext)

    def save_to(self, path):
        """Save As: .eml, an Outlook template (.oft) or an Outlook message (.msg)."""
        low = path.lower()
        if low.endswith((".oft", ".msg")):
            from . import msgfile
            data = msgfile.write(msgfile.fields_of_message(self.build(for_draft=True)), template=low.endswith(".oft"))
            with open(path, "wb") as fh:
                fh.write(data)
            return path
        from .window import save_message
        save_message(mime.to_bytes(self.build(for_draft=True)), path)
        return path

    def act_print(self):
        from .printing import print_message
        print_message(self, mime.to_bytes(self.build(for_draft=True)))

    def act_properties(self):
        imp = {2: "High", 1: "Normal", 0: "Low"}[self.importance]
        self.dialogs.info("Importance: %s\nRead receipt: %s\nDelivery receipt: %s\nDo not deliver before: %s" %
                          (imp, "Yes" if self.read_receipt else "No", "Yes" if self.delivery_receipt else "No",
                           time.strftime("%d/%m/%Y %H:%M", time.localtime(self.send_at)) if self.send_at else "None"),
                          "Properties")

    def act_close(self):
        self.close()

    def on_delete(self, *a):
        if self.modified and not self.sent:
            d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                                  text="Want to save your changes?")
            d.set_title(APP_NAME)
            d.add_button("Save", 1)
            d.add_button("Don't Save", 2)
            d.add_button("Cancel", 3)
            r = d.run()
            d.destroy()
            if r == 1:
                self.act_save()
            elif r != 2:
                return True
        self.destroy_window()
        return True

    def destroy_window(self):
        if self._autosave:
            GLib.source_remove(self._autosave)
            self._autosave = None
        self.app.composer_closed(self)
        self.destroy()

    # ---- editing
    def _focus_entry(self):
        f = self.get_focus()
        return f if isinstance(f, Gtk.Entry) else None

    def act_paste(self):
        e = self._focus_entry()
        if e:
            e.paste_clipboard()
            return
        cb = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        img = cb.wait_for_image()
        if img is not None and not cb.wait_is_text_available():
            ok, data = img.save_to_bufferv("png", [], [])
            if ok:
                self.editor.insert_picture(data, "image/png")
                return
        self.editor.paste()

    def act_paste_text(self):
        t = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).wait_for_text()
        if not t:
            return
        e = self._focus_entry()
        if e:
            pos = e.get_position()
            e.insert_text(t, pos)
            e.set_position(pos + len(t))
        else:
            self.editor.insert_text(t)

    def act_cut(self):
        e = self._focus_entry()
        (e.cut_clipboard() if e else self.editor.cut())

    def act_copy(self):
        e = self._focus_entry()
        (e.copy_clipboard() if e else self.editor.copy())

    def act_format_painter(self):
        st = self.editor.state()
        self._painter = {k: st[k] for k in ("bold", "italic", "underline", "strike", "font", "size", "color", "highlight")}
        self.status.set_text("  Select text to apply the copied formatting.")
        hid = [None]

        def released(*_):
            if self.editor.has_selection() and self._painter:
                for k, v in self._painter.items():
                    self.editor.set_char(k, v if v not in (None, False) else None)
                self._painter = None
                self.status.set_text("")
                self.editor.off_mouse_up(hid[0])
            return False
        hid[0] = self.editor.on_mouse_up(released)

    def act_select_all(self):
        e = self._focus_entry()
        if e:
            e.select_region(0, -1)
        else:
            self.editor.select_all()

    def act_undo(self):
        e = self._focus_entry()
        if e is None:
            self.editor.do_undo()

    def act_redo(self):
        self.editor.do_redo()

    def _char(self, kind, value):
        if self.plain:
            return
        self.editor.set_char(kind, value)
        self.editor.grab_focus()

    def act_bold(self):
        self.editor.toggle("bold")

    def act_italic(self):
        self.editor.toggle("italic")

    def act_underline(self):
        self.editor.toggle("underline")

    def act_strike(self):
        self.editor.toggle("strike")

    def act_font(self, name):
        self._char("font", name)

    def act_size(self, s):
        try:
            v = float(s)
        except ValueError:
            return
        self._char("size", int(v) if v == int(v) else v)

    def act_grow(self, step=1):
        cur = float(self.editor.state().get("size") or 11)
        sizes = [float(x) for x in FONT_SIZES]
        bigger = [x for x in sizes if x > cur]
        smaller = [x for x in sizes if x < cur]
        nv = (bigger[0] if bigger else cur + 2) if step > 0 else (smaller[-1] if smaller else max(1, cur - 1))
        self.act_size(str(nv))

    def act_shrink(self):
        self.act_grow(-1)

    def act_color(self, c):
        self._char("color", None if c in ("none", "") else c)

    def act_highlight(self, c):
        self._char("highlight", None if c in ("none", "") else c)

    def act_bullets(self):
        self.editor.set_list("bullet")

    def act_numbering(self):
        self.editor.set_list("number")

    def act_indent(self):
        self.editor.indent(1)

    def act_outdent(self):
        self.editor.indent(-1)

    def act_align(self, a):
        self.editor.set_align(a)

    def act_clear_formatting(self):
        self.editor.clear_formatting()

    def act_font_dialog(self):
        d = Gtk.FontChooserDialog(title="Font", transient_for=self)
        st = self.editor.state()
        d.set_font("%s %s" % (st["font"], st["size"]))
        if d.run() == Gtk.ResponseType.OK:
            fd = d.get_font_desc()
        else:
            fd = None
        if fd is not None and fd.get_family():
            self._char("font", fd.get_family())
            self._char("size", int(fd.get_size() / Pango.SCALE))
            self.editor.set_char("bold", fd.get_weight() >= Pango.Weight.BOLD)
            self.editor.set_char("italic", fd.get_style() != Pango.Style.NORMAL)
        d.destroy()

    def act_address_book(self):
        self.pick_names("to")

    def act_check_names(self):
        if self.check_names():
            self.status.set_text("  All names are recognized.")

    def act_attach_file(self, paths=None):
        if paths is None:
            dlg = Gtk.FileChooserDialog(title="Insert File", transient_for=self, action=Gtk.FileChooserAction.OPEN)
            dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Insert", Gtk.ResponseType.OK)
            dlg.set_select_multiple(True)
            paths = dlg.get_filenames() if dlg.run() == Gtk.ResponseType.OK else []
            dlg.destroy()
        for p in (paths.split("|") if isinstance(paths, str) else paths):
            if os.path.isfile(p):
                self.attachments.append(mime.file_attachment(p))
        self.refresh_attachments()
        self._dirty()

    def act_attach_item(self):
        main = self.app.windows[0] if self.app.windows else None
        ids = main.selected_ids() if main else []
        if not ids:
            self.dialogs.info("Select the message to attach in the main window's list first.")
            return
        for mid in ids:
            m = self.store.message(mid)
            name = (re.sub(r"[^\w .,-]+", "", m["subject"] or "message")[:60] or "message") + ".eml"
            self.attachments.append((name, "message/rfc822", self.store.raw(mid)))
        self.refresh_attachments()
        self._dirty()

    def act_insert_signature(self, name):
        sigs = self.store.get("signatures", {}) or {}
        if name in sigs:
            self.editor.insert_html(sigs[name])

    def act_signatures(self):
        from .options import signatures_dialog
        signatures_dialog(self)

    def act_insert_picture(self, path=None):
        if path is None:
            dlg = Gtk.FileChooserDialog(title="Insert Picture", transient_for=self, action=Gtk.FileChooserAction.OPEN)
            dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Insert", Gtk.ResponseType.OK)
            f = Gtk.FileFilter()
            f.set_name("Pictures")
            f.add_mime_type("image/*")
            dlg.add_filter(f)
            path = dlg.get_filename() if dlg.run() == Gtk.ResponseType.OK else None
            dlg.destroy()
        if path:
            name, ctype, data = mime.file_attachment(path)
            self.editor.insert_picture(data, ctype)

    def act_insert_link(self, url=None):
        st = self.editor.state()
        if url is None:
            url = self.dialogs.ask_text("Insert Hyperlink", "Address:", st.get("link") or "https://")
        if url is not None:
            self.editor.insert_link(url.strip() if url.strip() not in ("https://", "") else None)

    def act_insert_date(self):
        self.editor.insert_text(time.strftime("%d/%m/%Y"))

    def act_insert_line(self):
        self.editor.insert_text("\n" + "─" * 40 + "\n")

    def act_flag(self):
        self.flagged = not getattr(self, "flagged", False)
        self.sync_tags()

    def act_importance(self, v):
        v = int(v)
        self.importance = 1 if self.importance == v else v
        self.sync_tags()

    def act_toggle_encrypt(self):
        self.encrypt = not getattr(self, "encrypt", False)
        self.ribbon.update("encrypt", "true" if self.encrypt else "false")
        self.status.set_text("  This message will be encrypted." if self.encrypt else "")

    def act_toggle_sign(self):
        self.sign = not getattr(self, "sign", False)
        self.ribbon.update("sign", "true" if self.sign else "false")

    def act_toggle_bcc(self):
        on = not self.bcc_row[1].get_visible()
        for w in self.bcc_row:
            w.set_visible(on)
        self.app.set_setting("show_bcc", on)

    def act_toggle_from(self):
        on = not self.from_row[1].get_visible()
        for w in self.from_row:
            w.set_visible(on)
        self.app.set_setting("show_from", on)

    def act_voting(self, how="custom"):
        """Options > Use Voting Buttons."""
        from . import voting
        if how == "clear":
            self.voting = []
        elif how == "custom":
            text = self.dialogs.ask_text("Use Voting Buttons", "Choices, separated by semicolons:",
                                         ";".join(self.voting) or "Approve;Reject")
            if text is None:
                return self.voting
            self.voting = voting.parse_choices(text)
        else:
            self.voting = voting.parse_choices(how)
        self.modified = True
        if hasattr(self, "set_infobar_text"):
            self.set_infobar_text()
        return self.voting

    def act_toggle_read_receipt(self):
        self.read_receipt = self.receipt_check.get_active()

    def act_toggle_delivery_receipt(self):
        self.delivery_receipt = self.delivery_check.get_active()

    def act_delay_delivery(self, when=None):
        if when is None:
            cur = time.strftime("%Y-%m-%d %H:%M", time.localtime(self.send_at or time.time() + 3600))
            when = self.dialogs.ask_text("Delay Delivery", "Do not deliver before (YYYY-MM-DD HH:MM; empty for none):", cur)
        if when is None:
            return
        when = when.strip()
        if not when:
            self.send_at = 0
            return
        try:
            self.send_at = int(time.mktime(time.strptime(when, "%Y-%m-%d %H:%M")))
        except ValueError:
            self.dialogs.message("Type the date and time as YYYY-MM-DD HH:MM.")

    def act_direct_replies(self, addr=None):
        if addr is None:
            addr = self.dialogs.ask_text("Direct Replies To", "Have replies sent to:", self.reply_to_addr)
        if addr is not None:
            self.reply_to_addr = addr.strip()

    def act_format(self, kind):
        plain = kind == "plain"
        if plain == self.plain:
            return
        if plain and not self.editor.is_empty():
            d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                                  text="Plain text drops the message's formatting and pictures. Continue?")
            d.add_button("Cancel", Gtk.ResponseType.NO)
            d.add_button("Continue", Gtk.ResponseType.YES)
            r = d.run()
            d.destroy()
            if r != Gtk.ResponseType.YES:
                return
            text = self.editor.text()
            self.editor.load_html("<p>%s</p>" % html.escape(text).replace("\n", "<br>"))
        self.plain = plain
        self.sync_tags()
        self.update_title()

    def setup_spelling(self):
        if not self.app.setting("spell_as_you_type", True):
            return
        sp = speller(self.app)
        if sp is None:
            return
        words = self.store.get("dictionary-words", []) or []
        for w in words:
            try:
                sp.add_to_session(w)
            except Exception:
                pass

        def remember(word, learn):
            if learn:
                ws = self.store.get("dictionary-words", []) or []
                if word not in ws:
                    ws.append(word)
                    self.store.put("dictionary-words", ws)
            try:
                sp.add_to_session(word)
            except Exception:
                pass
        self.editor.on_ignore = remember
        self.editor.set_speller(sp, words)

    def act_spelling(self):
        ed = self.editor
        if ed.speller is None:
            sp = speller(self.app)
            if sp is None:
                self.dialogs.info("Spelling needs a dictionary (packages python3-enchant and hunspell-en-us).")
                return None
            ed.set_speller(sp)
        issues = ed.misspelt()
        if not issues:
            self.dialogs.info("The spelling check is complete.")
            return 0
        d = Gtk.Dialog(title="Spelling and Grammar", transient_for=self, modal=True)
        d.get_style_context().add_class("folio-dialog")
        box = d.get_content_area()
        box.set_border_width(12)
        box.set_spacing(6)
        word = Gtk.Label(xalign=0)
        box.pack_start(word, False, False, 0)
        box.pack_start(Gtk.Label(label="Suggestions:", xalign=0), False, False, 0)
        model = Gtk.ListStore(str)
        tv = Gtk.TreeView(model=model)
        tv.set_headers_visible(False)
        tv.append_column(Gtk.TreeViewColumn("", Gtk.CellRendererText(), text=0))
        tv.set_size_request(280, 150)
        box.pack_start(tv, True, True, 0)
        state = {"i": 0, "done": 0}

        def show():
            iss = ed.misspelt()
            if not iss:
                d.response(Gtk.ResponseType.CLOSE)
                return
            s_, e_, w = iss[0]
            word = iss[0][2]
            lab.set_markup("Not in Dictionary: <b>%s</b>" % GLib.markup_escape_text(word))
            model.clear()
            for sug in ed.suggest(word)[:8]:
                model.append([sug])
            if len(model):
                tv.get_selection().select_path(Gtk.TreePath.new_first())
            ed.select_issue(s_, e_)
            state["cur"] = iss[0]
        lab = word

        def change(*_):
            m, it = tv.get_selection().get_selected()
            if it is None or "cur" not in state:
                return
            s_, e_, w = state["cur"]
            ed.replace_range(s_, e_, m[it][0])
            state["done"] += 1
            show()

        def ignore(*_):
            if "cur" in state:
                ed.ignore(state["cur"][2])
            show()

        def add(*_):
            if "cur" in state:
                ed.learn(state["cur"][2])
            show()
        row = Gtk.Box(spacing=6)
        for label, fn in (("Ignore All", ignore), ("Add to Dictionary", add), ("Change", change)):
            b_ = Gtk.Button(label=label)
            b_.connect("clicked", fn)
            row.pack_start(b_, False, False, 0)
        box.pack_start(row, False, False, 0)
        d.add_button("Close", Gtk.ResponseType.CLOSE)
        d.parts = {"change": change, "ignore": ignore, "add": add, "model": model, "tree": tv}
        self.spelling_dialog = d
        d.show_all()
        show()
        if getattr(self, "spell_answer", None):
            self.spell_answer(d)
        else:
            d.run()
        d.destroy()
        return state["done"]

    def act_insert_table(self, spec=None):
        if spec is None:
            spec = self.dialogs.ask_text("Insert Table", "Columns × rows (like 3x2):", "3x2")
        if not spec:
            return None
        try:
            c, r = [int(x) for x in spec.lower().replace("×", "x").split("x")]
        except ValueError:
            return None
        if self.plain:
            return self.dialogs.info("Tables need HTML. Format Text > HTML first.")
        return self.editor.insert_table(max(1, min(r, 50)), max(1, min(c, 20)))

    def act_word_count(self):
        t = self.editor.text()
        words = len(re.findall(r"\S+", t))
        self.dialogs.info("Words: %d\nCharacters (no spaces): %d\nCharacters (with spaces): %d\nParagraphs: %d" %
                          (words, len(re.sub(r"\s", "", t)), len(t), len([p for p in t.split("\n") if p.strip()])),
                          "Word Count")

    # ================================================================ keys
    def on_key(self, w, ev):
        mods = ev.state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.MOD1_MASK)
        ctrl = mods & Gdk.ModifierType.CONTROL_MASK
        shift = mods & Gdk.ModifierType.SHIFT_MASK
        alt = mods & Gdk.ModifierType.MOD1_MASK
        k = ev.keyval
        if self.keytips.active:
            return self.keytips.key(ev)
        in_body = self.editor.has_focus_in(self.get_focus())
        if (ctrl and k in (Gdk.KEY_Return, Gdk.KEY_KP_Enter)) or (alt and k in (Gdk.KEY_s, Gdk.KEY_S)):
            self.run("send")
            return True
        if k == Gdk.KEY_F10 and not mods:
            self.keytips.start()
            return True
        if k == Gdk.KEY_F7:
            self.run("spelling")
            return True
        if ctrl and not alt:
            table = {Gdk.KEY_s: "save", Gdk.KEY_p: "print", Gdk.KEY_w: "close"}
            if in_body:
                table.update({Gdk.KEY_b: "bold", Gdk.KEY_i: "italic", Gdk.KEY_u: "underline", Gdk.KEY_l: "align:left",
                              Gdk.KEY_e: "align:center", Gdk.KEY_r: "align:right", Gdk.KEY_j: "align:justify",
                              Gdk.KEY_k: "insert-link", Gdk.KEY_z: "undo", Gdk.KEY_y: "redo", Gdk.KEY_space: "clear-formatting",
                              Gdk.KEY_m: "indent", Gdk.KEY_v: "paste", Gdk.KEY_a: "select-all", Gdk.KEY_c: "copy",
                              Gdk.KEY_x: "cut"})
                if shift:
                    table = {Gdk.KEY_B: "address-book", Gdk.KEY_L: "bullets", Gdk.KEY_greater: "grow", Gdk.KEY_less: "shrink", Gdk.KEY_M: "outdent",
                             Gdk.KEY_period: "grow", Gdk.KEY_comma: "shrink", Gdk.KEY_V: "paste-text"}
            else:
                table[Gdk.KEY_k] = "check-names"
                if shift:
                    table = {Gdk.KEY_B: "address-book"}
            cmd = table.get(k)
            if cmd:
                self.run(cmd)
                return True
        if k == Gdk.KEY_Escape and not mods:
            self.close()
            return True
        return False
