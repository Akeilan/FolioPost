"""People in the main window: its ribbon and commands."""
import os
import re

from gi.repository import GLib, Gtk

from . import carddav, vcard
from .ribbon import Ribbon, Tab
from .ribbon_post import Builder


def build_people_ribbon(win, r):
    B = Builder(win)
    B.r = r
    na = lambda n: "not-available:" + n  # noqa: E731
    t = r.building(Tab("Home", "H"))
    B.group(t, "New", [B.big("New Contact", "p-nav-people", "new-contact", "N", tip="New Contact (Ctrl+N)"),
                       B.big("New Contact Group", "p-conversations", "new-contact-group", "G", tip="New Contact Group (Ctrl+Shift+L)"),
                       [B.small("New Items", "p-new-email", None, "I", menu=[("E-mail Message", "new-email-message"),
                                                                            ("Meeting", "new-meeting")])]])
    B.group(t, "Delete", [B.big("Delete", "p-delete", "delete-contact", "D")])
    B.group(t, "Communicate", [B.big("Email", "p-new-email", "contact-email", "E"), B.big("Meeting", "p-meeting", "contact-meeting", "MR")])
    B.group(t, "Current View", [B.big("Change View", "p-change-view", None, "CV", menu=[("People", "people-view:card"),
                                                                                         ("List", "people-view:list")])])
    B.group(t, "Actions", [[B.small("Forward Contact", "p-forward", "forward-contact", "FW"),
                            B.small("Import vCard...", "p-open-file", "import-vcard", "IV"),
                            B.small("Export vCard...", "p-save-as", "export-vcard", "EV")]])
    B.group(t, "Find", [[B.small("Search People", "p-search-people", "search", "FP"),
                         B.small("Address Book", "p-address-book", "address-book", "AB")]])
    r.add_tab(t)
    t = r.building(Tab("Send / Receive", "S"))
    B.group(t, "Send & Receive", [B.big("Send/Receive All Folders", "p-send-receive", "send-receive", "A"),
                                  [B.small("Update Folder", "p-update-folder", "update-contacts", "F")]])
    B.group(t, "Preferences", [B.big("Work Offline", "p-offline", "work-offline", "W")])
    r.add_tab(t)
    t = r.building(Tab("Folder", "O"))
    B.group(t, "New", [B.big("New Address Book", "p-new-folder", "new-address-book", "N")])
    B.group(t, "Open", [B.big("Open Address Book", "p-open-file", None, "OA", menu=[
        ("From a Contacts Server (CardDAV)...", "open-address-book-server"),
        ("Google Contacts of an Account", "add-google-contacts")])])
    B.group(t, "Actions", [[B.small("Rename Address Book", "p-rename-folder", "rename-address-book", "RN"),
                            B.small("Delete Address Book", "p-delete-folder", "delete-address-book", "D")]])
    r.add_tab(t)
    t = r.building(Tab("View", "V"))
    B.group(t, "Current View", [B.big("Change View", "p-change-view", None, "CV", menu=[("People", "people-view:card"),
                                                                                         ("List", "people-view:list")]),
                                [B.small("Reset View", "p-change-view", "people-view:card", "X")]])
    B.group(t, "Layout", [B.big("Folder Pane", "p-folder-pane", None, "F",
                                menu=[("Normal", "people-folder-pane:normal"), ("Off", "people-folder-pane:off")])])
    r.add_tab(t)
    t = r.building(Tab("Help", "Y"))
    B.group(t, "Help", [B.big("Help", "p-help", "help", "H"), B.big("Keyboard Shortcuts", "p-options", "shortcuts", "K"),
                        B.big("About", "p-about", "about", "A")])
    r.add_tab(t)
    r.select(r.tab_by_name("Home"))


class PeopleCommands:
    peopleview = None

    def ensure_people(self):
        if self.peopleview is not None:
            return self.peopleview
        from .peopleview import PeopleView
        self.peopleview = PeopleView(self)
        self.peopleview.show_all()
        self.modules.add_named(self.peopleview, "people")
        self.people_ribbon = Ribbon(self.run, lambda: self.peopleview.tv.grab_focus())
        self.people_ribbon.connect("file-clicked", lambda *_: self.show_backstage())
        build_people_ribbon(self, self.people_ribbon)
        self.people_ribbon.show_all()
        return self.peopleview

    def update_people_status(self, view):
        if self.module != "people":
            return
        self.status.left.set_text("Items: %d" % len(view.model))
        errs = list(self.app.contactsync.errors.values())
        self.status.right.set_text("Working Offline" if self.app.syncer.offline else ("Contacts: " + errs[0]) if errs else
                                   "All folders are up to date.")

    def people_changed(self, push=False):
        if self.peopleview is not None:
            self.peopleview.refresh()
        if push and not self.app.syncer.offline:
            if getattr(self, "_people_push", None):
                GLib.source_remove(self._people_push)
            self._people_push = GLib.timeout_add_seconds(int(os.environ.get("FOLIO_POST_PUSH_DELAY", "8")), self._push_people)

    def _push_people(self):
        self._people_push = None
        if self.app.syncer.offline:
            return False
        dirty = [b["id"] for b in self.store.books() if b["kind"] != "local" and
                 any(c["pending"] for c in self.store.contacts(b["id"], with_deleted=True))]
        if dirty:
            self.app.background(lambda: [self.app.contactsync.sync(b) for b in dirty], lambda *_: self.people_changed())
        return False

    def _after_books(self):
        if self.peopleview is not None:
            self.peopleview.refresh_books()
            self.peopleview.refresh()

    # ---- contacts
    def act_new_contact(self, name="", email=""):
        from .contactwin import ContactWindow
        w = ContactWindow(self, name=name, email=email)
        w.present()
        return w

    def act_new_contact_group(self):
        from .contactwin import ContactWindow
        w = ContactWindow(self, group=True)
        w.present()
        return w

    def act_open_contact(self):
        from .contactwin import ContactWindow
        ids = self.ensure_people().selected_ids()
        if not ids:
            return None
        w = ContactWindow(self, cid=ids[0])
        w.present()
        return w

    def act_delete_contact(self):
        v = self.ensure_people()
        ids = v.selected_ids()
        if not ids:
            return
        for cid in ids:
            row = self.store.contact(cid)
            book = self.store.book(row["book"]) if row else None
            if book and book["readonly"]:
                continue
            carddav.delete_contact(self.store, cid)
        self.people_changed(push=True)

    def _selected_people(self):
        out = []
        for cid in self.ensure_people().selected_ids():
            row = self.store.contact(cid)
            if row is None:
                continue
            if row["is_group"]:
                out.append(("", "group:%d" % cid))
            elif row["emails"]:
                out.append((row["name"], row["emails"].split(",")[0]))
        return out

    def act_contact_email(self):
        from .contactwin import expand_groups
        people = expand_groups(self.store, self._selected_people())
        if not people:
            return self.dialogs.info("The selected contacts have no e-mail address.")
        return self.app.compose(to="; ".join(("%s <%s>" % (n, a)) if n else a for n, a in people))

    def act_contact_meeting(self):
        from .contactwin import expand_groups
        people = expand_groups(self.store, self._selected_people())
        w = self.act_new_meeting()
        if w is not None:
            w.to.set_text("; ".join(("%s <%s>" % (n, a)) if n else a for n, a in people))
        return w

    def act_forward_contact(self):
        ids = self.ensure_people().selected_ids()
        if not ids:
            return None
        atts = []
        for cid in ids:
            row = self.store.contact(cid)
            atts.append(("%s.vcf" % (re.sub(r"[^\w -]", "", row["name"]) or "contact"), "text/vcard", row["vcard"].encode()))
        acc = self.current_account()
        return self.app.compose(account=acc["id"] if acc else None, subject=", ".join(self.store.contact(i)["name"] for i in ids),
                                attach_data=atts)

    def import_vcards(self, text, bid=None):
        book = self.store.book(bid) if bid else self.ensure_people().current_book()
        n = 0
        for c in vcard.parse_all(text):
            if not c.uid:
                import uuid
                c.comp.add("UID", str(uuid.uuid4()))
            old = self.store.contact_by_uid(book["id"], c.uid)
            carddav.save_contact(self.store, book["id"], c, old["id"] if old else None)
            n += 1
        self.people_changed(push=True)
        return n

    def act_import_vcard(self, path=None):
        if path is None:
            dlg = Gtk.FileChooserDialog(title="Import vCard", transient_for=self, action=Gtk.FileChooserAction.OPEN)
            dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Open", Gtk.ResponseType.OK)
            f = Gtk.FileFilter()
            f.set_name("vCard (*.vcf)")
            f.add_pattern("*.vcf")
            f.add_pattern("*.vcard")
            dlg.add_filter(f)
            path = dlg.get_filename() if dlg.run() == Gtk.ResponseType.OK else None
            dlg.destroy()
        if not path:
            return 0
        return self.import_vcards(open(path, encoding="utf-8", errors="replace").read())

    def act_export_vcard(self, path=None):
        v = self.ensure_people()
        ids = v.selected_ids() or [r[0] for r in v.model]
        if path is None:
            dlg = Gtk.FileChooserDialog(title="Export vCard", transient_for=self, action=Gtk.FileChooserAction.SAVE)
            dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Save", Gtk.ResponseType.OK)
            dlg.set_do_overwrite_confirmation(True)
            dlg.set_current_name("Contacts.vcf")
            path = dlg.get_filename() if dlg.run() == Gtk.ResponseType.OK else None
            dlg.destroy()
        if not path:
            return None
        with open(path, "w") as fh:
            for cid in ids:
                row = self.store.contact(cid)
                c = vcard.parse(row["vcard"]) if row else None
                if c:
                    fh.write(c.dumps())
        return path

    def act_people_view(self, how):
        self.set_vset("people_view", how)
        v = self.ensure_people()
        v.card.get_parent().get_parent().set_visible(how != "list")

    def act_people_folder_pane(self, how):
        self.ensure_people().left.set_visible(how != "off")

    def act_address_book(self):
        from .contactwin import select_names
        got = select_names(self, "Address Book: Contacts", ["To", "Cc", "Bcc"])
        if got and any(got.values()):
            from .contactwin import expand_groups
            fmt = lambda xs: "; ".join(("%s <%s>" % (n, a)) if n else a for n, a in  # noqa: E731
                                       expand_groups(self.store, [(nm, v) for _k, nm, v in xs]))
            return self.app.compose(to=fmt(got["To"]), cc=fmt(got["Cc"]), bcc=fmt(got["Bcc"]))
        return None

    def act_add_sender_to_contacts(self):
        ids = self.selected_ids()
        if not ids:
            return None
        m = self.store.message(ids[0])
        return self.act_new_contact(m["from_name"] if m["from_name"] != m["from_addr"] else "", m["from_addr"])

    # ---- address books
    def act_new_address_book(self, name=None):
        if name is None:
            name = self.dialogs.ask_text("Create New Address Book", "Name:")
        if not name:
            return None
        bid = self.store.add_book(name, "local")
        self._after_books()
        return bid

    def _book_target(self):
        v = self.ensure_people()
        b = self.store.book(v.book_id) if v.book_id else None
        if b is None:
            self.dialogs.info("Select an address book in the list first.")
        return b

    def act_rename_address_book(self):
        b = self._book_target()
        if b:
            n = self.dialogs.ask_text("Rename Address Book", "Name:", b["name"])
            if n:
                self.store.update_book(b["id"], name=n)
                self._after_books()

    def act_delete_address_book(self):
        b = self._book_target()
        if b and self.ask("Remove the address book “%s” from Folio Post? Contacts on a server stay there." % b["name"]):
            self.store.remove_book(b["id"])
            self.ensure_people().book_id = None
            self._after_books()

    def act_open_address_book_server(self):
        from .accounts import CardDavDialog
        return CardDavDialog(self)

    def act_add_google_contacts(self):
        accs = [a for a in self.store.accounts() if a["config"].get("auth") == "oauth"]
        if not accs:
            self.dialogs.info("Google Contacts needs a Gmail account added with Google sign-in (File > Add Account).")
            return None
        acc = accs[0]
        if any(b["account"] == acc["id"] and b["kind"] == "google" for b in self.store.books()):
            self.dialogs.info("The contacts of %s are already here." % acc["email"])
            return None

        def job():
            ids = self.app.contactsync.add_google(acc["id"])
            for i in ids:
                self.app.contactsync.sync(i)
        self.app.background(job, lambda r, e: (self._after_books(),
                                               self.dialogs.message("Google Contacts couldn't be reached: %s" % e) if e else None))

    def act_update_contacts(self):
        if not self.app.syncer.offline:
            self.app.background(self.app.contactsync.sync_all, lambda *_: self.people_changed())
