"""People: address books on the left, the contacts in the middle, the selected one's card on the
right — e-mail addresses that start a message, phones, addresses, company, notes."""
from gi.repository import GdkPixbuf, GLib, Gtk, Pango

from . import vcard
from .readingpane import avatar


class PeopleView(Gtk.Box):
    def __init__(self, win):
        Gtk.Box.__init__(self)
        self.win = win
        self.store = win.store
        self.book_id = None
        self.filter = ""
        paned = Gtk.Paned()
        self.pack_start(paned, True, True, 0)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        left.get_style_context().add_class("folio-folderpane")
        left.set_size_request(220, -1)
        self.books = Gtk.ListBox()
        self.books.connect("row-selected", self._book_picked)
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.add(self.books)
        left.pack_start(sw, True, True, 0)
        self.left = left
        mid = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        mid.get_style_context().add_class("folio-listpane")
        self.model = Gtk.ListStore(int, str, str, bool)      # id, name, email, group
        self.tv = Gtk.TreeView(model=self.model)
        self.tv.set_headers_visible(False)
        self.tv.get_style_context().add_class("folio-messages")
        self.tv.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
        r = Gtk.CellRendererText()
        r.set_padding(8, 5)
        r.set_property("ellipsize", Pango.EllipsizeMode.END)
        col = Gtk.TreeViewColumn("", r)
        col.set_cell_data_func(r, lambda c, cell, m, it, _d: cell.set_property(
            "markup", "<b>%s</b>%s\n<span foreground='#767676'>%s</span>" % (
                GLib.markup_escape_text(m[it][1] or "(no name)"), "  (group)" if m[it][3] else "",
                GLib.markup_escape_text(m[it][2]))))
        self.tv.append_column(col)
        self.tv.get_selection().connect("changed", lambda *_: self.show_card())
        self.tv.connect("row-activated", lambda *_: self.win.run("open-contact"))
        msw = Gtk.ScrolledWindow()
        msw.add(self.tv)
        mid.pack_start(msw, True, True, 0)
        self.card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.card.get_style_context().add_class("folio-reading")
        self.card.set_border_width(0)
        csw = Gtk.ScrolledWindow()
        csw.add(self.card)
        right = Gtk.Paned()
        right.pack1(mid, True, False)
        right.pack2(csw, True, False)
        paned.pack1(left, False, False)
        paned.pack2(right, True, False)
        paned.set_position(230)
        GLib.idle_add(lambda: (right.set_position(max(280, right.get_allocated_width() // 2 - 60)), False)[1])
        self.refresh_books()
        self.refresh()

    # ------------------------------------------------------------ books
    def refresh_books(self):
        for c in self.books.get_children():
            self.books.remove(c)
        row = Gtk.ListBoxRow()
        lab = Gtk.Label(xalign=0)
        lab.set_markup("<b>My Contacts</b>")
        lab.set_margin_start(8)
        lab.set_margin_top(6)
        row.add(lab)
        row.book_id = None
        self.books.add(row)
        for b in self.store.books():
            row = Gtk.ListBoxRow()
            lab = Gtk.Label(label=b["name"] + ("  (read-only)" if b["readonly"] else ""), xalign=0)
            lab.set_margin_start(16)
            lab.set_ellipsize(Pango.EllipsizeMode.END)
            row.add(lab)
            row.book_id = b["id"]
            self.books.add(row)
            if b["id"] == self.book_id:
                self.books.select_row(row)
        self.books.show_all()

    def _book_picked(self, lb, row):
        self.book_id = getattr(row, "book_id", None) if row is not None else None
        self.refresh()

    def current_book(self):
        if self.book_id:
            b = self.store.book(self.book_id)
            if b and not b["readonly"]:
                return b
        for b in self.store.books():
            if not b["readonly"]:
                return b
        bid = self.store.add_book("Contacts", "local")
        self.book_id = bid
        self.refresh_books()
        return self.store.book(bid)

    # ------------------------------------------------------------ contacts
    def refresh(self):
        sel = self.selected_ids()
        self.model.clear()
        rows = self.store.contacts(self.book_id) if self.book_id else self.store.contacts()
        t = self.filter.lower()
        for r in rows:
            if t and t not in (r["name"] + " " + r["emails"]).lower():
                continue
            self.model.append([r["id"], r["name"], (r["emails"] or "").split(",")[0], bool(r["is_group"])])
        if sel:
            self.select_ids(sel)
        elif len(self.model):
            self.tv.get_selection().select_path(Gtk.TreePath.new_first())
        self.show_card()
        self.win.update_people_status(self)

    def selected_ids(self):
        m, paths = self.tv.get_selection().get_selected_rows()
        return [m[p][0] for p in paths]

    def select_ids(self, ids):
        s = self.tv.get_selection()
        s.unselect_all()
        for row in self.model:
            if row[0] in ids:
                s.select_iter(row.iter)

    def show_card(self):
        for c in self.card.get_children():
            self.card.remove(c)
        ids = self.selected_ids()
        if len(ids) != 1:
            lab = Gtk.Label(label="%d contacts selected" % len(ids) if ids else "")
            lab.get_style_context().add_class("folio-reading-empty")
            self.card.pack_start(lab, True, True, 40)
            self.card.show_all()
            return
        row = self.store.contact(ids[0])
        c = vcard.parse(row["vcard"]) if row else None
        if c is None:
            return
        head = Gtk.Box(spacing=12)
        head.set_border_width(16)
        pic = c.photo
        img = None
        if pic:
            try:
                ld = GdkPixbuf.PixbufLoader()
                ld.write(pic)
                ld.close()
                pb = ld.get_pixbuf().scale_simple(72, 72, GdkPixbuf.InterpType.BILINEAR)
                img = Gtk.Image.new_from_pixbuf(pb)
            except Exception:
                img = None
        emails = c.emails
        head.pack_start(img or avatar(c.name, emails[0][1] if emails else "", 72), False, False, 0)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        nm = Gtk.Label(xalign=0)
        nm.set_markup("<span size='x-large'>%s</span>" % GLib.markup_escape_text(c.name or "(no name)"))
        nm.set_selectable(True)
        box.pack_start(nm, False, False, 0)
        sub = ", ".join(x for x in (c.title, c.department, c.company) if x)
        if c.is_group:
            sub = "Contact group · %d members" % len(c.members)
        if sub:
            s = Gtk.Label(label=sub, xalign=0)
            s.get_style_context().add_class("folio-reading-recips")
            box.pack_start(s, False, False, 0)
        acts = Gtk.Box(spacing=4)
        for label, cmd in (("Email", "contact-email"), ("Meeting", "contact-meeting"), ("Edit", "open-contact")):
            b = Gtk.Button(label=label)
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.connect("clicked", lambda _b, k=cmd: self.win.run(k))
            acts.pack_start(b, False, False, 0)
        box.pack_start(acts, False, False, 4)
        head.pack_start(box, True, True, 0)
        self.card.pack_start(head, False, False, 0)
        grid = Gtk.Grid(column_spacing=16, row_spacing=6)
        grid.set_margin_start(20)
        grid.set_margin_end(16)
        r = 0

        def line(label, value, link=None):
            nonlocal r
            k = Gtk.Label(label=label, xalign=0, yalign=0)
            k.get_style_context().add_class("folio-reading-recips")
            if link:
                v = Gtk.LinkButton.new_with_label(link, value)
                v.set_halign(Gtk.Align.START)
                v.connect("activate-link", lambda b: (self.win.app.compose_mailto(b.get_uri()) if b.get_uri().startswith("mailto:")
                                                      else None, b.get_uri().startswith("mailto:"))[1])
            else:
                v = Gtk.Label(label=value, xalign=0)
                v.set_selectable(True)
                v.set_line_wrap(True)
            grid.attach(k, 0, r, 1, 1)
            grid.attach(v, 1, r, 1, 1)
            r += 1
        if c.is_group:
            names = []
            for e in c.member_emails():
                names.append(e)
            for u in c.member_uids():
                for b in self.store.books():
                    m = self.store.contact_by_uid(b["id"], u)
                    if m:
                        names.append("%s <%s>" % (m["name"], (m["emails"] or "").split(",")[0]))
            for n in names:
                line("Member", n)
        labels = {"work": "Work", "home": "Personal", "other": "Email"}
        for kind, e in emails:
            line(labels.get(kind, "Email"), e, "mailto:" + e)
        plabels = dict(vcard.PHONE_TYPES)
        for kind, p in c.phones:
            line(plabels.get(kind, "Phone"), p)
        for kind, a in c.addresses:
            txt = "\n".join(x for x in (a["street"], " ".join(y for y in (a["postal"], a["city"]) if y), a["region"], a["country"]) if x)
            line({"home": "Home address", "work": "Work address"}.get(kind, "Address"), txt)
        for u in c.urls:
            line("Web page", u)
        if c.birthday:
            line("Birthday", c.birthday)
        if c.note:
            line("Notes", c.note)
        self.card.pack_start(grid, False, False, 0)
        # recent mail with them
        if emails:
            addr = emails[0][1]
            rows = self.store.q("select subject, date from messages where (lower(from_addr)=? or lower(to_text) like ?) and deleted=0 "
                                "order by date desc limit 5", (addr.lower(), "%" + addr.lower() + "%"))
            if rows:
                import time as _t
                hdr = Gtk.Label(xalign=0)
                hdr.set_markup("<b>Recent messages</b>")
                hdr.set_margin_start(20)
                hdr.set_margin_top(12)
                self.card.pack_start(hdr, False, False, 0)
                for m in rows:
                    l2 = Gtk.Label(label="%s  %s" % (_t.strftime("%d/%m/%Y", _t.localtime(m["date"])), m["subject"]), xalign=0)
                    l2.set_margin_start(20)
                    l2.set_ellipsize(Pango.EllipsizeMode.END)
                    self.card.pack_start(l2, False, False, 0)
        self.card.show_all()
