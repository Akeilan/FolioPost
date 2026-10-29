"""The File view (Backstage) for Mail: Info (accounts), Open & Export, Save As, Save Attachments,
Print, Options, Exit."""
from gi.repository import GLib, Gtk

from . import icons

NAV = [("back", ""), ("info", "Info"), ("open", "Open & Export"), ("saveas", "Save As"),
       ("attachments", "Save Attachments"), ("print", "Print"), None, "spacer", ("options", "Options"), ("exit", "Exit")]


def _heading(text, cls="folio-bs-title"):
    lab = Gtk.Label(label=text, xalign=0)
    lab.get_style_context().add_class(cls)
    return lab


class Backstage(Gtk.Box):
    def __init__(self, win):
        Gtk.Box.__init__(self)
        self.win = win
        self.get_style_context().add_class("folio-backstage")
        nav = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        nav.get_style_context().add_class("folio-bs-nav")
        nav.set_size_request(180, -1)
        self.nav_buttons = {}
        for entry in NAV:
            if entry is None:
                s = Gtk.Separator()
                s.get_style_context().add_class("folio-bs-sep")
                nav.pack_start(s, False, False, 6)
                continue
            if entry == "spacer":
                nav.pack_start(Gtk.Box(), True, True, 0)
                continue
            key, label = entry
            b = Gtk.Button()
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.get_style_context().add_class("folio-bs-navbtn")
            if key == "back":
                b.add(Gtk.Image.new_from_icon_name("go-previous-symbolic", Gtk.IconSize.LARGE_TOOLBAR))
                b.set_tooltip_text("Back (Esc)")
                b.set_halign(Gtk.Align.START)
                b.get_style_context().add_class("back")
            else:
                b.add(Gtk.Label(label=label, xalign=0))
            b.connect("clicked", lambda _b, k=key: self.nav(k))
            nav.pack_start(b, False, False, 0)
            self.nav_buttons[key] = b
        self.pack_start(nav, False, False, 0)
        self.stack = Gtk.Stack()
        self.stack.get_style_context().add_class("folio-bs-body")
        self.pack_start(self.stack, True, True, 0)
        self.current = None

    def open(self, page="info"):
        self.win.ribbon.set_sensitive(False)
        self.show_all()
        self.nav(page)

    def close(self):
        self.hide()
        self.win.ribbon.set_sensitive(True)
        self.win.focus_document()

    def nav(self, key):
        direct = {"saveas": "save-as", "attachments": "save-attachments", "options": "options", "exit": "exit"}
        if key == "back":
            self.close()
            return
        if key in direct:
            self.close()
            self.win.run(direct[key])
            return
        self.current = key
        for k, b in self.nav_buttons.items():
            ctx = b.get_style_context()
            (ctx.add_class if k == key else ctx.remove_class)("active")
        old = self.stack.get_child_by_name(key)
        if old is not None:
            self.stack.remove(old)
        w = getattr(self, "page_" + key)()
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.add(w)
        sw.show_all()
        self.stack.add_named(sw, key)
        self.stack.set_visible_child_name(key)

    def _page(self, title):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_border_width(36)
        box.pack_start(_heading(title), False, False, 0)
        return box

    def _action(self, icon, title, text, cmd):
        row = Gtk.Box(spacing=16)
        b = Gtk.Button()
        b.get_style_context().add_class("folio-bs-printbtn")
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        inner.pack_start(icons.image(icon, 32), False, False, 0)
        inner.pack_start(Gtk.Label(label=title), False, False, 0)
        b.add(inner)
        b.set_size_request(110, 90)

        def go(*_):
            self.close()
            self.win.run(cmd)
        b.connect("clicked", go)
        row.pack_start(b, False, False, 0)
        lab = Gtk.Label(xalign=0)
        lab.set_markup("<b>%s</b>\n%s" % (GLib.markup_escape_text(title), GLib.markup_escape_text(text)))
        lab.set_line_wrap(True)
        lab.set_max_width_chars(70)
        row.pack_start(lab, False, False, 0)
        return row

    def page_info(self):
        box = self._page("Account Information")
        accs = self.win.store.accounts()
        acc = self.win.current_account()
        if acc:
            lab = Gtk.Label(xalign=0)
            kind = {"imap": "IMAP/SMTP", "pop3": "POP/SMTP", "local": "On this computer", "ews": "Microsoft Exchange"}.get(acc["kind"], acc["kind"])
            lab.set_markup("<big><b>%s</b></big>\n%s" % (GLib.markup_escape_text(acc["email"] or acc["name"]), kind))
            box.pack_start(lab, False, False, 4)
        elif not accs:
            box.pack_start(Gtk.Label(label="There are no accounts yet.", xalign=0), False, False, 4)
        add = Gtk.Button(label="+ Add Account")
        add.set_halign(Gtk.Align.START)
        add.connect("clicked", lambda *_: (self.close(), self.win.run("add-account")))
        box.pack_start(add, False, False, 4)
        box.pack_start(self._action("p-account", "Account Settings", "Change settings for this account or set up more "
                                    "connections.", "account-settings"), False, False, 6)
        box.pack_start(self._action("p-delay", "Automatic Replies", "Let people know you're away, on vacation, or not "
                                    "available to answer e-mail.", "automatic-replies"), False, False, 6)
        box.pack_start(self._action("p-clean-up", "Mailbox Settings", "Empty Deleted Items and clean up the mailbox.",
                                    "empty-trash"), False, False, 6)
        box.pack_start(self._action("p-rules", "Rules and Alerts", "Organize incoming mail and get told when it "
                                    "arrives.", "rules"), False, False, 6)
        box.pack_start(self._action("p-signature", "Signatures", "Make and choose the signatures new messages, replies "
                                    "and forwards end with.", "signatures"), False, False, 6)
        return box

    def page_open(self):
        box = self._page("Open & Export")
        box.pack_start(self._action("p-open-file", "Open Message", "Open a message saved as a file (.eml).", "open"),
                       False, False, 6)
        box.pack_start(self._action("p-move", "Import/Export", "Import or export messages, calendars and contacts.",
                                    "import-export"), False, False, 6)
        return box

    def page_print(self):
        box = self._page("Print")
        box.pack_start(self._action("p-print", "Print", "Print the selected message.", "print"), False, False, 6)
        return box
