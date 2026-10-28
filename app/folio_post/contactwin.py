"""The contact window (name, company, e-mail, phones, address, web page, birthday, notes, picture),
the contact group window, and the Select Names box the To, Cc and Bcc buttons open."""
import re

from gi.repository import Gdk, GLib, Gtk

from . import APP_NAME, carddav, icons, vcard
from .dialogs import Dialogs
from .ribbon import Ribbon, Tab
from .ribbon_post import Builder


class ContactWindow(Gtk.Window):
    def __init__(self, main, cid=None, book=None, name="", email="", group=False):
        Gtk.Window.__init__(self)
        self.main = main
        self.app = main.app
        self.store = main.store
        self.dialogs = Dialogs(self)
        self.cid = cid
        self.missing_log = []
        self.modified = False
        row = self.store.contact(cid) if cid else None
        self.book_id = row["book"] if row else (book or main.ensure_people().current_book()["id"])
        self.card = vcard.parse(row["vcard"]) if row else (vcard.new_group(name) if group else vcard.new_contact(name, email))
        self.group = self.card.is_group
        self.photo = self.card.photo
        self.set_default_size(760, 600)
        self.set_icon_name("folio-post")
        hb = Gtk.HeaderBar()
        hb.set_show_close_button(True)
        hb.get_style_context().add_class("folio-titlebar")
        self.title_label = Gtk.Label()
        self.title_label.get_style_context().add_class("title")
        hb.set_custom_title(self.title_label)
        self.qat = Gtk.Box()
        b = Gtk.Button()
        b.add(icons.white_image("qat-save", 16))
        b.connect("clicked", lambda *_: self.run("save"))
        self.qat.pack_start(b, False, False, 0)
        hb.pack_start(self.qat)
        self.set_titlebar(hb)
        self.overlay = Gtk.Overlay()
        self.add(self.overlay)
        self.outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.overlay.add(self.outer)
        self.ribbon = Ribbon(self.run, lambda: None)
        self.ribbon.connect("file-clicked", lambda *_: self.run("save-as"))
        self.outer.pack_start(self.ribbon, False, False, 0)
        B = Builder(self)
        t = self.ribbon.building(Tab("Contact Group" if self.group else "Contact", "H"))
        B.group(t, "Actions", [B.big("Save & Close", "qat-save", "save-close", "AV"), B.big("Delete", "p-delete", "delete", "D"),
                               [B.small("Save & New", "p-new-email", "save-new", "N"),
                                B.small("Forward", "p-forward", "forward", "FW")]])
        if self.group:
            B.group(t, "Members", [B.big("Add Members", "p-nav-people", "add-members", "M"),
                                   [B.small("Remove Member", "p-delete", "remove-member", "R")]])
        else:
            B.group(t, "Communicate", [B.big("Email", "p-new-email", "email", "E"), B.big("Meeting", "p-meeting", "meeting", "MR")])
            B.group(t, "Options", [B.big("Picture", "insertgraphic", None, "P", menu=[("Add Picture...", "picture"),
                                                                                      ("Remove Picture", "remove-picture")])])
        self.ribbon.add_tab(t)
        self.ribbon.select(t)
        grid = Gtk.Grid(column_spacing=8, row_spacing=6)
        grid.set_border_width(14)
        self.f = {}
        c = self.card
        r = 0

        def add(key, label, value, width=2):
            nonlocal r
            grid.attach(Gtk.Label(label=label, xalign=0), 0, r, 1, 1)
            e = Gtk.Entry(text=value or "")
            e.set_hexpand(True)
            e.connect("changed", lambda *_: self._dirty())
            grid.attach(e, 1, r, width, 1)
            self.f[key] = e
            r += 1
            return e
        add("name", "Group name" if self.group else "Full Name", c.name)
        self.f["name"].connect("changed", lambda *_: self.update_title())
        if self.group:
            self.members = Gtk.ListStore(str, str)        # shown text, member value (mailto: / urn:uuid:)
            for m in c.members:
                self.members.append([self._member_text(m), m])
            tv = Gtk.TreeView(model=self.members)
            tv.append_column(Gtk.TreeViewColumn("Members", Gtk.CellRendererText(), text=0))
            self.members_view = tv
            sw = Gtk.ScrolledWindow()
            sw.add(tv)
            sw.set_vexpand(True)
            grid.attach(sw, 0, r, 3, 1)
            r += 1
            grid.attach(Gtk.Label(label="Add by address", xalign=0), 0, r, 1, 1)
            self.new_member = Gtk.Entry()
            self.new_member.set_placeholder_text("name@example.org")
            self.new_member.connect("activate", lambda *_: self.run("add-member-address"))
            grid.attach(self.new_member, 1, r, 2, 1)
        else:
            add("company", "Company", c.company)
            add("department", "Department", c.department)
            add("title", "Job title", c.title)
            em = c.emails + [("work", "")] * 3
            for i in range(3):
                add("email%d" % i, "E-mail" if i == 0 else "E-mail %d" % (i + 1), em[i][1])
            ph = dict((k, v) for k, v in reversed(c.phones))
            for kind, label in vcard.PHONE_TYPES[:4]:
                add("tel_" + kind, label, ph.get(kind, ""))
            ad = dict(c.addresses)
            for kind, label in (("work", "Business address"), ("home", "Home address")):
                a = ad.get(kind, {})
                txt = "\n".join(x for x in (a.get("street", ""), " ".join(y for y in (a.get("postal", ""), a.get("city", "")) if y),
                                            a.get("region", ""), a.get("country", "")) if x) if a else ""
                grid.attach(Gtk.Label(label=label, xalign=0, yalign=0), 0, r, 1, 1)
                tvw = Gtk.TextView()
                tvw.get_buffer().set_text(txt)
                tvw.set_size_request(-1, 54)
                tvw.get_style_context().add_class("folio-editor")
                tvw.get_buffer().connect("changed", lambda *_: self._dirty())
                grid.attach(tvw, 1, r, 2, 1)
                self.f["adr_" + kind] = tvw
                r += 1
            add("url", "Web page", (c.urls or [""])[0])
            add("bday", "Birthday", c.birthday)
            grid.attach(Gtk.Label(label="Notes", xalign=0, yalign=0), 0, r, 1, 1)
            self.notes = Gtk.TextView()
            self.notes.get_buffer().set_text(c.note)
            self.notes.set_size_request(-1, 70)
            self.notes.get_style_context().add_class("folio-editor")
            grid.attach(self.notes, 1, r, 2, 1)
        sw = Gtk.ScrolledWindow()
        sw.add(grid)
        self.outer.pack_start(sw, True, True, 0)
        from .keytips import KeyTips
        self.keytips = KeyTips(self)
        self.connect("key-press-event", self.on_key)
        self.connect("delete-event", self.on_delete)
        self.show_all()
        self.update_title()
        self.modified = False
        book = self.store.book(self.book_id)
        self.readonly = bool(book and book["readonly"])

    def _member_text(self, m):
        if m.lower().startswith("mailto:"):
            return m[7:]
        uid = re.sub(r"(?i)^urn:uuid:", "", m)
        for b in self.store.books():
            x = self.store.contact_by_uid(b["id"], uid)
            if x:
                return "%s <%s>" % (x["name"], (x["emails"] or "").split(",")[0])
        return uid

    def _dirty(self):
        self.modified = True

    def update_title(self):
        n = self.f["name"].get_text().strip() or "Untitled"
        self.title_label.set_text("%s - %s" % (n, "Contact Group" if self.group else "Contact"))
        self.set_title(self.title_label.get_text())

    def run(self, cmd, *args):
        if cmd is None:
            return None
        name, _, arg = cmd.partition(":")
        fn = getattr(self, "act_" + name.replace("-", "_"), None)
        if fn is None:
            self.missing_log.append(cmd)
            self.dialogs.info("“%s” isn't available yet in %s." % (arg if name == "not-available" else cmd, APP_NAME))
            return None
        try:
            return fn(arg) if arg or _ else fn()
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.dialogs.message("Something went wrong running this command.\n\n%s" % e)
            return None

    # ------------------------------------------------------------ the card
    def collect(self):
        c = self.card
        name = self.f["name"].get_text().strip()
        if not name and not self.group:
            em = self.f["email0"].get_text().strip()
            name = em or self.f["company"].get_text().strip()
        if not name:
            self.dialogs.message("Type a name first.")
            return None
        if self.group:
            c.comp.set("FN", vcard.escape(name))
            c.comp.set("N", vcard.escape(name) + ";;;;")
            vals = [row[1] for row in self.members]
            c.set_members([v[7:] for v in vals if v.lower().startswith("mailto:")],
                          [re.sub(r"(?i)^urn:uuid:", "", v) for v in vals if v.lower().startswith("urn:uuid:")])
        else:
            c.set_name(name)
            c.set_company(self.f["company"].get_text().strip(), self.f["department"].get_text().strip())
            c.set_text("TITLE", self.f["title"].get_text().strip())
            c.set_emails([("work" if i == 0 else "home" if i == 1 else "other", self.f["email%d" % i].get_text().strip())
                          for i in range(3)])
            c.set_phones([(k, self.f["tel_" + k].get_text().strip()) for k, _l in vcard.PHONE_TYPES[:4]])
            for kind in ("work", "home"):
                b = self.f["adr_" + kind].get_buffer()
                lines = [x.strip() for x in b.get_text(b.get_start_iter(), b.get_end_iter(), False).split("\n") if x.strip()]
                a = {"street": lines[0] if lines else ""}
                if len(lines) > 1:
                    m = re.match(r"(\S*\d\S*(?:\s+[A-Z]{2})?)\s+(.*)", lines[1])
                    a["postal"], a["city"] = (m.group(1), m.group(2)) if m else ("", lines[1])
                if len(lines) > 2:
                    a["country"] = lines[-1]
                if len(lines) > 3:
                    a["region"] = lines[2]
                c.set_address(kind, a)
            url = self.f["url"].get_text().strip()
            c.comp.set("URL", vcard.escape(url) if url else None)
            bd = self.f["bday"].get_text().strip()
            c.comp.set("BDAY", bd or None)
            b = self.notes.get_buffer()
            c.set_text("NOTE", b.get_text(b.get_start_iter(), b.get_end_iter(), False))
            if self.photo != c.photo:
                c.set_photo(self.photo)
        c.touch()
        return c

    def act_save(self):
        if self.readonly:
            self.dialogs.message("This address book is read-only.")
            return None
        c = self.collect()
        if c is None:
            return None
        self.cid = carddav.save_contact(self.store, self.book_id, c, self.cid)
        self.modified = False
        self.main.people_changed(push=True)
        return self.cid

    def act_save_close(self):
        if self.act_save() is not None:
            self.destroy()

    def act_save_new(self):
        if self.act_save() is not None:
            ContactWindow(self.main, book=self.book_id).present()
            self.destroy()

    def act_delete(self):
        if self.cid:
            carddav.delete_contact(self.store, self.cid)
            self.main.people_changed(push=True)
        self.modified = False
        self.destroy()

    def act_close(self):
        self.close()

    def act_forward(self):
        c = self.collect() or self.card
        acc = self.main.current_account()
        self.app.compose(account=acc["id"] if acc else None, subject=c.name,
                         attach_data=[("%s.vcf" % (re.sub(r"[^\w -]", "", c.name) or "contact"), "text/vcard", c.dumps().encode())])

    def act_save_as(self):
        dlg = Gtk.FileChooserDialog(title="Save As", transient_for=self, action=Gtk.FileChooserAction.SAVE)
        dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Save", Gtk.ResponseType.OK)
        dlg.set_current_name((re.sub(r"[^\w -]", "", self.f["name"].get_text()) or "contact") + ".vcf")
        path = dlg.get_filename() if dlg.run() == Gtk.ResponseType.OK else None
        dlg.destroy()
        if path:
            c = self.collect() or self.card
            with open(path, "w") as fh:
                fh.write(c.dumps())

    def act_email(self):
        e = self.f.get("email0")
        addr = e.get_text().strip() if e else ""
        if addr:
            self.app.compose(to="%s <%s>" % (self.f["name"].get_text().strip(), addr))

    def act_meeting(self):
        e = self.f.get("email0")
        w = self.main.act_new_meeting()
        if w is not None and e is not None:
            w.to.set_text("%s <%s>" % (self.f["name"].get_text().strip(), e.get_text().strip()))

    def act_picture(self, path=None):
        if path is None:
            dlg = Gtk.FileChooserDialog(title="Add Contact Picture", transient_for=self, action=Gtk.FileChooserAction.OPEN)
            dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Open", Gtk.ResponseType.OK)
            f = Gtk.FileFilter()
            f.add_mime_type("image/*")
            f.set_name("Pictures")
            dlg.add_filter(f)
            path = dlg.get_filename() if dlg.run() == Gtk.ResponseType.OK else None
            dlg.destroy()
        if path:
            from gi.repository import GdkPixbuf
            pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, 256, 256, True)
            ok, data = pb.save_to_bufferv("jpeg", ["quality"], ["90"])
            if ok:
                self.photo = bytes(data)
                self._dirty()

    def act_remove_picture(self):
        self.photo = None
        self._dirty()

    def act_add_members(self):
        if not self.group:
            return
        got = select_names(self, "Select Members", ["Members"], groups=False)
        if got:
            for kind, name, value in got.get("Members", []):
                self.members.append([self._member_text(value), value])
            self._dirty()

    def act_add_member_address(self):
        if not self.group:
            return
        t = self.new_member.get_text().strip()
        from .compose import parse_recipients
        for n, a in parse_recipients(t):
            if a:
                self.members.append([a, "mailto:" + a])
        self.new_member.set_text("")
        self._dirty()

    def act_remove_member(self):
        if not self.group:
            return
        m, it = self.members_view.get_selection().get_selected()
        if it is not None:
            m.remove(it)
            self._dirty()

    def on_delete(self, *a):
        if self.modified and not self.readonly:
            d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                                  text="Want to save your changes?")
            d.add_button("Save", 1)
            d.add_button("Don't Save", 2)
            d.add_button("Cancel", 3)
            r = d.run()
            d.destroy()
            if r == 1:
                if self.act_save() is None:
                    return True
            elif r != 2:
                return True
        return False

    def on_key(self, w, ev):
        ctrl = ev.state & Gdk.ModifierType.CONTROL_MASK
        if self.keytips.active:
            return self.keytips.key(ev)
        if ctrl and ev.keyval in (Gdk.KEY_s, Gdk.KEY_S):
            self.run("save")
            return True
        if ev.keyval == Gdk.KEY_Escape:
            self.close()
            return True
        if ev.keyval == Gdk.KEY_F10:
            self.keytips.start()
            return True
        return False


# ---------------------------------------------------------------- Select Names
def people_rows(store, text=""):
    """(kind, display name, e-mail or member value, contact row id) for contacts and groups, by name."""
    out = []
    t = (text or "").lower()
    for r in store.contacts():
        if r["is_group"]:
            if not t or t in r["name"].lower():
                out.append(("group", r["name"], "group:%d" % r["id"], r["id"]))
            continue
        for e in [x for x in (r["emails"] or "").split(",") if x]:
            if not t or t in (r["name"] + " " + e).lower():
                out.append(("person", r["name"], e, r["id"]))
    return out


def select_names(parent, title, buttons, groups=True, answer=None):
    """The Select Names box: pick people for each of `buttons` ('To', 'Cc', 'Bcc', 'Members').
    Returns {button: [(kind, name, value)]} or None. `answer` drives it in tests."""
    store = parent.store
    d = Gtk.Dialog(title=title, transient_for=parent, modal=True)
    d.get_style_context().add_class("folio-dialog")
    d.set_default_size(560, 460)
    box = d.get_content_area()
    box.set_border_width(10)
    box.set_spacing(6)
    top = Gtk.Box(spacing=6)
    top.pack_start(Gtk.Label(label="Search:"), False, False, 0)
    search = Gtk.SearchEntry()
    top.pack_start(search, True, True, 0)
    box.pack_start(top, False, False, 0)
    model = Gtk.ListStore(str, str, str, int)

    def fill(*_):
        model.clear()
        for kind, name, value, rid in people_rows(store, search.get_text()):
            if kind == "group" and not groups:
                continue
            model.append([name + (" (group)" if kind == "group" else ""), "" if kind == "group" else value, value, rid])
    fill()
    search.connect("search-changed", fill)
    tv = Gtk.TreeView(model=model)
    tv.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
    tv.append_column(Gtk.TreeViewColumn("Name", Gtk.CellRendererText(), text=0))
    tv.append_column(Gtk.TreeViewColumn("E-mail Address", Gtk.CellRendererText(), text=1))
    sw = Gtk.ScrolledWindow()
    sw.add(tv)
    box.pack_start(sw, True, True, 0)
    picked = {b: [] for b in buttons}
    entries = {}
    for b in buttons:
        row = Gtk.Box(spacing=6)
        btn = Gtk.Button(label=b + " ->")
        e = Gtk.Entry()
        e.set_editable(False)
        entries[b] = e

        def add(_x, b=b):
            m, paths = tv.get_selection().get_selected_rows()
            for p in paths:
                name, value, rid = m[p][0], m[p][2], m[p][3]
                kind = "group" if value.startswith("group:") else "person"
                if b == "Members":
                    c = store.contact(rid)
                    from . import vcard as V
                    cc = V.parse(c["vcard"]) if c else None
                    value = ("urn:uuid:" + cc.uid) if cc and cc.uid and kind == "person" else "mailto:" + m[p][1]
                picked[b].append((kind, name.replace(" (group)", ""), value))
            entries[b].set_text("; ".join(n for _k, n, _v in picked[b]))
        btn.connect("clicked", add)
        tv.connect("row-activated", lambda *_x, b=buttons[0], f=add: f(None, b))
        row.pack_start(btn, False, False, 0)
        row.pack_start(e, True, True, 0)
        box.pack_start(row, False, False, 0)
    d.add_button("Cancel", Gtk.ResponseType.CANCEL)
    d.add_button("OK", Gtk.ResponseType.OK)
    d.show_all()
    d.parts = {"search": search, "tree": tv, "model": model, "picked": picked}
    resp = answer(d) if answer else d.run()
    d.destroy()
    return picked if resp == Gtk.ResponseType.OK else None


def expand_groups(store, people):
    """'group:N' recipients become their members' addresses."""
    out = []
    for n, a in people:
        if a.startswith("group:"):
            row = store.contact(int(a[6:]))
            c = vcard.parse(row["vcard"]) if row else None
            if c:
                for e in c.member_emails():
                    out.append(("", e))
                for u in c.member_uids():
                    for b in store.books():
                        x = store.contact_by_uid(b["id"], u)
                        if x and x["emails"]:
                            out.append((x["name"], x["emails"].split(",")[0]))
        else:
            out.append((n, a))
    return out
