# Run inside Folio Post (FOLIO_TEST_SCRIPT): People — contacts, groups, vCard, the address book in messages, CardDAV.
import os
import sys
import time
import traceback

from gi.repository import Gdk, Gtk

sys.path.insert(0, os.environ["FOLIO_TESTS"])
import davserver  # noqa: E402
import mailserver  # noqa: E402

FAILS = []
INFO = []
OUT = os.environ.get("UI_OUT", "/tmp/ui_out")
os.makedirs(OUT, exist_ok=True)


def pump(t=0.15):
    end = time.time() + t
    while time.time() < end:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        time.sleep(0.003)


def wait(cond, t=20):
    end = time.time() + t
    while time.time() < end:
        pump(0.05)
        try:
            if cond():
                return True
        except Exception:
            pass
    return False


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    sys.stdout.flush()
    if not cond:
        FAILS.append(what)


def shot(w, name):
    import cairo
    pump(0.3)
    a = w.get_allocation()
    img = cairo.ImageSurface(cairo.FORMAT_ARGB32, max(1, a.width), max(1, a.height))
    w.draw(cairo.Context(img))
    img.write_to_png(os.path.join(OUT, "people_" + name + ".png"))


class Ev:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def key(name, ctrl=False, shift=False, alt=False, target=None):
    st = 0
    if ctrl:
        st |= Gdk.ModifierType.CONTROL_MASK
    if shift:
        st |= Gdk.ModifierType.SHIFT_MASK
    t = target or win
    r = t.on_key(t, Ev(keyval=Gdk.keyval_from_name(name), state=Gdk.ModifierType(st), type=Gdk.EventType.KEY_PRESS))
    pump(0.1)
    return r


from folio_post import dialogs as D  # noqa: E402
from folio_post import window as W  # noqa: E402
ANSWERS = []
D.Dialogs.info = lambda self, text, title=None: INFO.append(text)
D.Dialogs.message = lambda self, text, title=None: INFO.append(text)
D.Dialogs.ask_text = lambda self, title, label, value="": ANSWERS.pop(0) if ANSWERS else value
W.PostWindow.ask = lambda self, text, yes="Yes", no="No": True
Gtk.Dialog.run = lambda d: Gtk.ResponseType.CANCEL

try:
    from folio_post import carddav, mime, vcard
    store = app.store
    mw = mailserver.World()
    boxes = mw.add_user("me@example.org", "secret")
    boxes["INBOX"].add(mailserver.sample(1, frm="Frank Ocean <frank@example.org>", subject="Hello"))
    _m, ip, sp, mstop = mailserver.start(mw)
    cfg = {"imap_host": "127.0.0.1", "imap_port": ip, "imap_security": "none", "smtp_host": "127.0.0.1", "smtp_port": sp,
           "smtp_security": "none", "user": "me@example.org"}
    from folio_post.accounts import create_account
    aid = create_account(win, "Me", "me@example.org", cfg, "secret")
    wait(lambda: store.folder_by_role(aid, "inbox") and store.messages(store.folder_by_role(aid, "inbox")["id"]), 20)
    wait(lambda: not app.busy(), 10)
    pump(0.4)

    key("3", ctrl=True)
    check(win.module == "people" and win.peopleview is not None, "Ctrl+3 opens People")
    check(any(getattr(c, "action", "") == "new-contact" for c in win.ribbon.controls), "the People ribbon")
    v = win.peopleview
    cw = win.run("new-contact")
    pump(0.2)
    cw.f["name"].set_text("Ann Lee")
    cw.f["company"].set_text("Folio Ltd")
    cw.f["title"].set_text("Manager")
    cw.f["email0"].set_text("ann@example.org")
    cw.f["tel_cell"].set_text("+31 6 1234 5678")
    cw.f["adr_work"].get_buffer().set_text("Main St 1\n1011 AB Amsterdam\nNetherlands")
    cw.notes.get_buffer().set_text("Met at the fair")
    shot(cw, "contact")
    cw.run("save-close")
    pump(0.3)
    rows = store.contacts()
    check(len(rows) == 1 and rows[0]["name"] == "Ann Lee" and rows[0]["emails"] == "ann@example.org", "contact saved")
    c = vcard.parse(rows[0]["vcard"])
    check(c.company == "Folio Ltd" and c.addresses[0][1]["city"] == "Amsterdam" and c.addresses[0][1]["postal"] == "1011 AB",
          "company and address: %s" % (c.addresses,))
    check(len(v.model) == 1, "listed in People")
    v.select_ids([rows[0]["id"]])
    pump(0.2)
    texts = []

    def walk(w):
        if isinstance(w, Gtk.Label):
            texts.append(w.get_text())
        elif isinstance(w, Gtk.Button) and not isinstance(w, Gtk.LinkButton):
            texts.append(w.get_label() or "")
        elif isinstance(w, Gtk.LinkButton):
            texts.append(w.get_label())
        if isinstance(w, Gtk.Container):
            for ch in w.get_children():
                walk(ch)
    walk(v.card)
    check("Ann Lee" in texts and "ann@example.org" in texts and "+31 6 1234 5678" in texts, "the contact card")
    shot(win, "people")
    # second contact from a message sender
    key("1", ctrl=True)
    inbox = store.folder_by_role(aid, "inbox")
    win.go_folder(inbox["id"])
    pump(0.3)
    win.select_ids([win.iter_rows()[0][0]])
    cw = win.run("add-sender-to-contacts")
    pump(0.2)
    check(cw.f["name"].get_text() == "Frank Ocean" and cw.f["email0"].get_text() == "frank@example.org", "Add Sender to Contacts")
    cw.run("save-close")
    # group
    key("3", ctrl=True)
    g = win.run("new-contact-group")
    pump(0.2)
    g.f["name"].set_text("Team")
    g.new_member.set_text("ann@example.org; frank@example.org")
    g.run("add-member-address")
    check(len(g.members) == 2, "members added")
    g.run("save-close")
    grp = [r for r in store.contacts() if r["is_group"]]
    check(grp and grp[0]["name"] == "Team", "contact group saved")
    # search
    win.search.set_text("fra")
    pump(0.3)
    check([r[1] for r in v.model] == ["Frank Ocean"], "search in People")
    win.search.set_text("")
    pump(0.2)
    # e-mail a group: autocomplete, group expands when sent
    c = app.compose(account=aid)
    pump(0.3)
    names = [r[0] for r in c._address_model()]
    check("Team" in names and "Ann Lee <ann@example.org>" in names, "autocomplete has contacts and groups")
    c.fields["to"].set_text("Team; ")
    c.subject.set_text("Team news")
    c.editor.insert_text("Hi all")
    check(c.check_names(), "a group name is a valid recipient")
    c.run("send")
    ok = wait(lambda: any(b"Team news" in r for _f, _r, r in mw.smtp_log), 20)
    check(ok, "sent to the group")
    if ok:
        f, rc, raw = [x for x in mw.smtp_log if b"Team news" in x[2]][-1]
        check(sorted(rc) == ["ann@example.org", "frank@example.org"], "group expanded to its members: %s" % rc)
    # Check Names resolves a contact's name
    c = app.compose(account=aid)
    pump(0.2)
    c.fields["to"].set_text("Ann Lee")
    check(c.check_names() and "ann@example.org" in c.fields["to"].get_text(), "Check Names uses the contacts")
    # Select Names box
    from folio_post.contactwin import select_names

    def pick(d):
        d.parts["search"].set_text("ann")
        pump(0.2)
        d.parts["tree"].get_selection().select_path(Gtk.TreePath.new_first())
        btns = [w for w in d.get_content_area().get_children() if isinstance(w, Gtk.Box)]
        for b in btns:
            for ch in b.get_children():
                if isinstance(ch, Gtk.Button) and ch.get_label() == "Cc ->":
                    ch.clicked()
        return Gtk.ResponseType.OK
    got = select_names(c, "Select Names", ["To", "Cc", "Bcc"], answer=pick)
    check(got and [x[1] for x in got["Cc"]] == ["Ann Lee"], "Select Names: %s" % got)
    c.modified = False
    c.destroy_window()
    # vCard out and in
    import tempfile
    d = tempfile.mkdtemp()
    v.tv.get_selection().unselect_all()
    p = win.run("export-vcard:" + os.path.join(d, "all.vcf"))
    text = open(p).read()
    check(text.count("BEGIN:VCARD") == 3, "export vCard")
    open(os.path.join(d, "new.vcf"), "w").write("BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Gina Ruiz\r\nEMAIL:gina@example.org\r\nEND:VCARD\r\n")
    n = win.run("import-vcard:" + os.path.join(d, "new.vcf"))
    check(n == 1 and any(r["name"] == "Gina Ruiz" for r in store.contacts()), "import vCard")
    # delete
    gina = [r for r in store.contacts() if r["name"] == "Gina Ruiz"][0]
    v.select_ids([gina["id"]])
    key("Delete")
    check(not any(r["name"] == "Gina Ruiz" for r in store.contacts()), "Delete removes a contact")
    # CardDAV two-way
    dav = davserver.World()
    dav.add_user("me@example.org", "secret", ("personal",), ("contacts",))
    dav.books["me@example.org"]["contacts"].put("h.vcf", vcard.new_contact("Hana Kim", "hana@example.org").dumps())
    _d, dport, dstop = davserver.start(dav)
    ids = app.contactsync.add_carddav("http://127.0.0.1:%d/" % dport, "me@example.org", "secret")
    for i in ids:
        app.contactsync.sync(i)
    win._after_books()
    check(any(r["name"] == "Hana Kim" for r in store.contacts(ids[0])), "CardDAV contacts come down")
    v.book_id = ids[0]
    v.refresh()
    cw = win.run("new-contact")
    pump(0.2)
    check(cw.book_id == ids[0], "a new contact goes in the selected address book")
    cw.f["name"].set_text("Ivan Petrov")
    cw.f["email0"].set_text("ivan@example.org")
    cw.run("save-close")
    ok = wait(lambda: any("Ivan Petrov" in dd for _e, dd in dav.books["me@example.org"]["contacts"].items.values()), 15)
    check(ok, "a new contact reaches the CardDAV server")
    win.run("go:mail")
    dstop()
    mstop()
except Exception:
    traceback.print_exc()
    FAILS.append("exception")
print("UI FAILS: %d" % len(FAILS) if FAILS else "UI all passed")
sys.stdout.flush()
os._exit(1 if FAILS else 0)
