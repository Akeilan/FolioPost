# Run inside Folio Post (FOLIO_TEST_SCRIPT): drives the window as a user would, against the local test mail server.
import os
import sys
import time
import traceback

from gi.repository import Gdk, GLib, Gtk

sys.path.insert(0, os.environ["FOLIO_TESTS"])
import mailserver  # noqa: E402

FAILS = []
OUT = os.environ.get("UI_OUT", "/tmp/ui_out")
os.makedirs(OUT, exist_ok=True)
INFO = []


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
    w.queue_draw()
    pump(0.2)
    alloc = w.get_allocation()
    img = cairo.ImageSurface(cairo.FORMAT_ARGB32, max(1, alloc.width), max(1, alloc.height))
    cr = cairo.Context(img)
    w.draw(cr)
    img.write_to_png(os.path.join(OUT, "post_" + name + ".png"))


class Ev:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def key(target, name, ctrl=False, shift=False, alt=False, focus=None):
    st = 0
    if ctrl:
        st |= Gdk.ModifierType.CONTROL_MASK
    if shift:
        st |= Gdk.ModifierType.SHIFT_MASK
    if alt:
        st |= Gdk.ModifierType.MOD1_MASK
    if focus is not None:
        focus.grab_focus()
        pump(0.05)
    ev = Ev(keyval=Gdk.keyval_from_name(name), state=Gdk.ModifierType(st), type=Gdk.EventType.KEY_PRESS)
    r = target.on_key(target, ev)
    pump(0.1)
    return r


# no modal dialogs in the test: answers come from here
from folio_post import dialogs as D  # noqa: E402
from folio_post import window as W  # noqa: E402
ANSWERS = []
D.Dialogs.info = lambda self, text, title=None: INFO.append(text)
D.Dialogs.message = lambda self, text, title=None: INFO.append(text)
D.Dialogs.ask_text = lambda self, title, label, value="": ANSWERS.pop(0) if ANSWERS else value
W.PostWindow.ask = lambda self, text, yes="Yes", no="No": True
_run = Gtk.Dialog.run


def dialog_run(d):
    INFO.append("dialog:" + (d.get_title() or ""))
    if isinstance(d, Gtk.MessageDialog):
        return Gtk.ResponseType.YES
    return Gtk.ResponseType.CANCEL
Gtk.Dialog.run = dialog_run


def compose_windows():
    return list(app.composers)


try:
    store = app.store
    world = mailserver.World()
    boxes = world.add_user("me@example.org", "secret")
    world.add_user("bob@example.org", "pw")
    for i in range(8):
        boxes["INBOX"].add(mailserver.sample(i, html=i == 0, attach=i == 2,
                                             frm="Bob Stone <bob@example.org>" if i in (1, 3) else "Ann Lee <ann@example.org>"),
                           ["\\Seen"] if i > 4 else [])
    _w, ip, sp, stop = mailserver.start(world)
    cfg = {"imap_host": "127.0.0.1", "imap_port": ip, "imap_security": "none", "smtp_host": "127.0.0.1", "smtp_port": sp,
           "smtp_security": "none", "user": "me@example.org"}
    from folio_post.accounts import create_account
    check(win.get_title().endswith("Folio Post"), "window title")
    check([t.name for t in win.ribbon.tabs] == ["Home", "Send / Receive", "Folder", "View", "Help"], "ribbon tabs as Outlook")
    aid = create_account(win, "Me Myself", "me@example.org", cfg, "secret")
    ok = wait(lambda: store.folder_by_role(aid, "inbox") and len(store.messages(store.folder_by_role(aid, "inbox")["id"])) == 8, 30)
    check(ok, "first sync brings 8 messages")
    wait(lambda: not app.busy(), 10)
    pump(0.5)
    inbox = store.folder_by_role(aid, "inbox")
    win.go_folder(inbox["id"])
    pump(0.3)
    labels = []
    win.folders_model.foreach(lambda m, p, it: labels.append(m[it][0]))
    check(any("Inbox" in l and ">5<" in l for l in labels), "Folder Pane: Inbox shows 5 unread: %s" % labels[:3])
    check(any("Sent Items" in l for l in labels) and any("Deleted Items" in l for l in labels), "folder names as Outlook's")
    rows = win.iter_rows()
    check(len(rows) == 8, "the list shows 8 messages")
    heads = []
    win.list_model.foreach(lambda m, p, it: heads.append(m[it][1]) if not m[it][0] else None)
    check(len(heads) >= 1, "grouped by date: %s" % heads)
    check(win.status.left.get_text().startswith("Items: 8"), "status bar counts: %s" % win.status.left.get_text())
    shot(win, "main")

    # reading
    first = rows[0][0]
    win.select_ids([first])
    pump(0.3)
    m0 = store.message(first)
    check(win.reading.mid == first and win.reading.subject.get_text() == m0["subject"], "Reading Pane shows the message")
    check(win.reading.bar.get_visible(), "remote pictures blocked, with the bar")
    check("alert" not in win.reading.view.text(), "scripts aren't shown")
    win.select_ids([rows[1][0]])
    pump(0.3)
    check(store.message(first)["seen"] == 1, "marked read when the selection changes")
    # attachment
    m2 = [r for r in store.messages(inbox["id"]) if r["subject"] == "Message 2"][0]
    win.select_ids([m2["id"]])
    pump(0.3)
    check(win.reading.att_box.get_visible() and win.reading.atts[0]["name"] == "notes.txt", "attachment shown")
    import tempfile
    d = tempfile.mkdtemp()
    saved = win.reading.save_all(d)
    check(saved and open(saved[0], "rb").read() == b"attached notes\n", "Save All Attachments")
    shot(win, "reading")

    # flags, categories, read/unread, keyboard
    key(win, "Insert", focus=win.list_view)
    check(store.message(m2["id"])["flagged"] == 1, "Insert flags the message")
    win.run("categorize:Blue")
    check(store.message(m2["id"])["categories"] == "Blue", "Categorize")
    key(win, "u", ctrl=True, focus=win.list_view)
    check(store.message(m2["id"])["seen"] == 0, "Ctrl+U marks unread")
    key(win, "q", ctrl=True, focus=win.list_view)
    check(store.message(m2["id"])["seen"] == 1, "Ctrl+Q marks read")
    win.run("flag:done")
    check(store.message(m2["id"])["done"] == 1 and store.message(m2["id"])["flagged"] == 0, "Mark Complete")
    wait(lambda: not app.busy(), 10)
    time.sleep(1.5)
    pump(0.5)
    wait(lambda: not app.busy(), 10)
    srv = {m[0]: m[1] for m in boxes["INBOX"].msgs}
    check("\\Seen" in srv.get(store.message(first)["uid"], set()), "read state reaches the server")

    # delete, undo
    target = [r for r in store.messages(inbox["id"]) if r["subject"] == "Message 3"][0]
    win.select_ids([target["id"]])
    pump(0.2)
    key(win, "Delete", focus=win.list_view)
    trash = store.folder_by_role(aid, "trash")
    check(len(store.messages(inbox["id"])) == 7 and any(r["subject"] == "Message 3" for r in store.messages(trash["id"])),
          "Delete moves to Deleted Items")
    key(win, "z", ctrl=True, focus=win.list_view)
    check(any(r["subject"] == "Message 3" for r in store.messages(inbox["id"])), "Undo brings it back")
    wait(lambda: not app.busy(), 10)

    # search
    win.search.set_text("Message 4")
    pump(0.4)
    check(len(win.iter_rows()) >= 1 and all("4" in store.message(i)["subject"] for i, _ in win.iter_rows()), "search")
    win.clear_search()
    pump(0.2)
    check(len(win.iter_rows()) == 8, "search cleared")
    win.run("filter:unread")
    check(all(not store.message(i)["seen"] for i, _ in win.iter_rows()), "Unread filter")
    win.run("filter:all")

    # views
    win.run("view-mode:single")
    check(win.list_view.get_headers_visible() and len(win.list_view.get_columns()) >= 7, "Single view has columns")
    shot(win, "single")
    win.run("view-mode:compact")
    win.run("arrange:from")
    heads = []
    win.list_model.foreach(lambda m, p, it: heads.append(m[it][1]) if not m[it][0] else None)
    check("Bob Stone" in heads and "Ann Lee" in heads, "Arrange By From groups by sender: %s" % heads)
    win.run("arrange:date")
    win.run("toggle-conversations")
    check(win.vset("conversations") is True, "Show as Conversations on")
    win.run("toggle-conversations")
    win.run("reading-pane:bottom")
    check(win.right.get_orientation() == Gtk.Orientation.VERTICAL, "Reading Pane at the bottom")
    win.run("reading-pane:right")
    win.run("reading-pane:off")
    check(not win.reading.get_visible(), "Reading Pane off")
    win.run("reading-pane:right")

    # reply and send
    ann = [r for r in store.messages(inbox["id"]) if r["subject"] == "Message 4"][0]
    win.select_ids([ann["id"]])
    pump(0.2)
    key(win, "r", ctrl=True, focus=win.list_view)
    pump(0.5)
    cw = compose_windows()
    check(len(cw) == 1, "Ctrl+R opens a reply")
    c = cw[-1]
    check(c.subject.get_text() == "RE: Message 4", "reply subject: %s" % c.subject.get_text())
    check("ann@example.org" in c.fields["to"].get_text(), "reply goes to the sender")
    check(c.quote_box.get_visible(), "the original is quoted")
    c.editor.grab_focus()
    c.editor.buf.insert_at_cursor("Thanks Ann, ")
    c.editor.buf.place_cursor(c.editor.buf.get_start_iter())
    s, e = c.editor.buf.get_start_iter(), c.editor.buf.get_iter_at_offset(6)
    c.editor.buf.select_range(s, e)
    key(c, "b", ctrl=True, focus=c.editor)
    shot(c, "reply")
    c.editor.buf.place_cursor(c.editor.buf.get_end_iter())
    key(c, "Return", ctrl=True, focus=c.editor)
    pump(0.3)
    check(c not in app.composers, "Ctrl+Enter sends and closes")
    ok = wait(lambda: any("RE: Message 4" in r.decode("utf-8", "replace") for _f, _r, r in world.smtp_log), 20)
    check(ok, "the reply reached the SMTP server")
    if ok:
        raw = [r for _f, _r, r in world.smtp_log if b"RE: Message 4" in r][-1]
        from folio_post import mime
        msg = mime.parse(raw)
        h = mime.body_part(msg, "html") or ""
        check("<b>Thanks</b>" in h, "bold text sent as HTML")
        check("In-Reply-To" in msg and "m4." in mime.header(msg, "In-Reply-To"), "In-Reply-To set")
        check("From:" in h and "Message 4" in h, "the original quoted in the HTML")
        check(mime.text_of(msg).startswith("Thanks Ann"), "a plain-text part too")
    wait(lambda: store.message(ann["id"])["answered"] == 1, 5)
    check(store.message(ann["id"])["answered"] == 1, "the original is marked replied")
    wait(lambda: not app.busy(), 10)
    sent = store.folder_by_role(aid, "sent")
    check(any(r["subject"] == "RE: Message 4" for r in store.messages(sent["id"])), "a copy in Sent Items")
    check(not store.outbox(aid), "Outbox empty after sending")

    # new message: bcc stays hidden from recipients, attachments, high importance
    key(win, "n", ctrl=True, focus=win.list_view)
    pump(0.4)
    c = compose_windows()[-1]
    c.fields["to"].set_text("bob@example.org")
    c.run("toggle-bcc")
    c.fields["bcc"].set_text("secret@example.org")
    c.subject.set_text("Plans")
    c.editor.buf.insert_at_cursor("See the file.")
    p = os.path.join(d, "plan.txt")
    open(p, "w").write("plan\n")
    c.run("attach-file:" + p)
    c.run("importance:2")
    c.run("bullets")
    check(c.editor.state()["list"] == "bullet", "Bullets in the editor")
    c.run("send")
    ok = wait(lambda: any(b"Subject: Plans" in r for _f, _r, r in world.smtp_log), 20)
    check(ok, "new message sent")
    if ok:
        f, rc, raw = [x for x in world.smtp_log if b"Subject: Plans" in x[2]][-1]
        check("secret@example.org" in rc and b"secret@example.org" not in raw, "Bcc delivered but not shown")
        msg = mime.parse(raw)
        check([a["name"] for a in mime.attachments(msg)] == ["plan.txt"], "attachment sent")
        check(mime.header(msg, "Importance") == "High", "High Importance")
        check("<ul>" in (mime.body_part(msg, "html") or ""), "bullets sent as a list")
    check(any(a[1] == "bob@example.org" for a in store.get("recent-addresses", [])), "addresses remembered for autocomplete")

    # empty subject asks; no recipients refused
    c = app.compose(account=aid)
    pump(0.3)
    INFO.clear()
    check(c.run("send") is False and any("at least one name" in t for t in INFO), "no recipients: not sent")
    c.fields["to"].set_text("nobody")
    INFO.clear()
    check(c.run("send") is False and any("recognize" in t for t in INFO), "an unknown name is caught by Check Names")
    c.fields["to"].set_text("Bob Stone")
    check(c.check_names() and "bob@example.org" in c.fields["to"].get_text(), "Check Names resolves a known name")
    # drafts
    c.subject.set_text("Draft one")
    c.editor.buf.insert_at_cursor("draft body")
    key(c, "s", ctrl=True, focus=c.subject)
    drafts = store.folder_by_role(aid, "drafts")
    check(any(r["subject"] == "Draft one" for r in store.messages(drafts["id"])), "Ctrl+S saves to Drafts")
    did = [r for r in store.messages(drafts["id"]) if r["subject"] == "Draft one"][0]["id"]
    c.modified = False
    c.close()
    pump(0.3)
    c = app.compose(draft=did)
    pump(0.3)
    check(c.subject.get_text() == "Draft one" and "draft body" in c.editor.text(), "a draft opens again")
    check("Bob Stone" in c.fields["to"].get_text(), "draft keeps its recipients")
    c.modified = False
    c.destroy_window()

    # forward keeps attachments
    win.select_ids([m2["id"]])
    pump(0.2)
    key(win, "f", ctrl=True, focus=win.list_view)
    pump(0.3)
    c = compose_windows()[-1]
    check(c.subject.get_text() == "FW: Message 2" and [a[0] for a in c.attachments] == ["notes.txt"], "Forward keeps the attachment")
    c.modified = False
    c.destroy_window()

    # folders: new, move, rename, delete
    ANSWERS[:] = ["Projects"]
    fid = win.run("new-folder:account:%d" % aid)
    check(fid and "Projects" in world.users["me@example.org"][1], "New Folder made on the server")
    m5 = [r for r in store.messages(inbox["id"]) if r["subject"] == "Message 5"][0]
    win.go_folder(inbox["id"])
    win.select_ids([m5["id"]])
    win.run("move:%d" % fid)
    check(any(r["subject"] == "Message 5" for r in store.messages(fid)), "Move to folder")
    time.sleep(1.5)
    pump(0.3)
    wait(lambda: not app.busy(), 10)
    wait(lambda: len(world.users["me@example.org"][1]["Projects"].msgs) == 1, 10)
    check(len(world.users["me@example.org"][1]["Projects"].msgs) == 1, "the move reached the server")
    win.go_folder(fid)
    ANSWERS[:] = ["Work"]
    win.run("rename-folder")
    check("Work" in world.users["me@example.org"][1] and store.folder(fid)["name"] == "Work", "Rename Folder")
    win.run("delete-folder")
    check("Work" not in world.users["me@example.org"][1] and store.folder(fid) is None, "Delete Folder")
    win.go_folder(inbox["id"])
    pump(0.3)

    # junk
    bob = [r for r in store.messages(inbox["id"]) if r["from_addr"] == "bob@example.org"][0]
    win.select_ids([bob["id"]])
    win.run("block-sender")
    junk = store.folder_by_role(aid, "junk")
    check("bob@example.org" in store.get("blocked-senders") and any(r["from_addr"] == "bob@example.org" for r in store.messages(junk["id"])),
          "Block Sender moves to Junk Email")
    # new mail from a blocked sender goes to Junk; rules move mail
    rules = [{"on": True, "from": "carol@example.org", "subject": "", "to": "", "move": trash["id"], "read": True,
              "flag": False, "category": "", "name": "carol"}]
    store.put("rules", rules)
    boxes["INBOX"].add(mailserver.sample(20, frm="Bob Stone <bob@example.org>", subject="Blocked one"))
    boxes["INBOX"].add(mailserver.sample(21, frm="Carol <carol@example.org>", subject="Rule one"))
    win.run("send-receive")
    ok = wait(lambda: any(r["subject"] == "Blocked one" for r in store.messages(junk["id"])), 20)
    check(ok, "new mail from a blocked sender goes to Junk Email")
    ok = wait(lambda: any(r["subject"] == "Rule one" and r["seen"] for r in store.messages(trash["id"])), 10)
    check(ok, "a rule moves and marks new mail")
    wait(lambda: not app.busy(), 10)

    # offline: queued in the Outbox, sent when back online
    win.run("work-offline")
    check(app.syncer.offline and "Offline" in win.status.right.get_text(), "Work Offline")
    c = app.compose(account=aid, to="bob@example.org", subject="Later")
    pump(0.3)
    c.editor.buf.insert_at_cursor("queued")
    c.run("send")
    check(len(store.outbox(aid)) == 1, "offline: the message waits in the Outbox")
    labels = []
    win.refresh_folders()
    win.folders_model.foreach(lambda m, p, it: labels.append(m[it][0]))
    check(any("Outbox" in l and "[1]" in l for l in labels), "Outbox shows in the Folder Pane")
    win.run("work-offline")
    ok = wait(lambda: any(b"Subject: Later" in r for _f, _r, r in world.smtp_log), 20)
    check(ok and not app.syncer.offline, "back online: the Outbox is sent")

    # mail arriving elsewhere, deleted elsewhere
    boxes["INBOX"].add(mailserver.sample(30, subject="Fresh"))
    key(win, "F9")
    ok = wait(lambda: any(r["subject"] == "Fresh" for r in store.messages(inbox["id"])), 20)
    check(ok, "F9 gets new mail")
    wait(lambda: not app.busy(), 10)
    pump(0.3)
    check(any(r["subject"] == "Fresh" for r in getattr(win, "last_new_mail", [])), "new-mail alert")

    # open in own window
    pump(0.5)
    fresh = [r for r in store.messages(inbox["id"]) if r["subject"] == "Fresh"][0]
    win.select_ids([fresh["id"]])
    mw = win.run("open-item")
    pump(0.3)
    check(mw is not None and mw.reading.subject.get_text() == "Fresh", "message opens in its own window")
    shot(mw, "message_window")
    mw.destroy()

    # Quick Steps
    win.select_ids([fresh["id"]])
    win.run("quick-step:0")
    archive = store.folder_by_role(aid, "archive")
    check(archive and any(r["subject"] == "Fresh" for r in store.messages(archive["id"])), "Quick Step Done archives")

    # Save As .eml / .txt
    win.select_ids([win.iter_rows()[0][0]])
    p = win.run("save-as:" + os.path.join(d, "m.eml"))
    check(p and open(p, "rb").read().startswith(b"From:") or b"Subject" in open(p, "rb").read(), "Save As .eml")
    p = win.run("save-as:" + os.path.join(d, "m.txt"))
    check("Subject:" in open(p).read(), "Save As .txt")
    from folio_post.printing import print_message
    pdf = os.path.join(d, "m.pdf")
    print_message(win, store.raw(win.iter_rows()[0][0]), to_file=pdf)
    check(os.path.exists(pdf) and os.path.getsize(pdf) > 500, "Print (to PDF)")

    # mailto
    c = app.compose_mailto("mailto:bob@example.org?subject=Hi%20there&body=Line")
    pump(0.3)
    check(c.subject.get_text() == "Hi there" and "bob@example.org" in c.fields["to"].get_text() and "Line" in c.editor.text(),
          "mailto: links open a new message")
    c.modified = False
    c.destroy_window()

    # account dialog flows
    from folio_post.accounts import AccountDialog, guess
    check(guess("x@gmail.com")[0] == "gmail" and guess("x@proton.me")[0] == "proton", "provider presets")
    dlg = AccountDialog(win)
    dlg.email_entry.set_text("someone@gmail.com")
    dlg.response(Gtk.ResponseType.OK)
    pump(0.2)
    check(dlg.page == "gmail", "Gmail: sign-in choice")
    dlg.response(1)
    pump(0.1)
    dlg.email_entry.set_text("someone@proton.me")
    dlg.response(Gtk.ResponseType.OK)
    pump(0.2)
    check(dlg.page == "proton", "Proton: Bridge page")
    shot(dlg, "proton")
    dlg.response(1)
    dlg.email_entry.set_text("bob@example.org")
    dlg.manual_check.set_active(True)
    dlg.response(Gtk.ResponseType.OK)
    pump(0.2)
    check(dlg.page == "manual", "manual settings page")
    dlg.m["imap_host"].set_text("127.0.0.1")
    dlg.m["imap_port"].set_value(ip)
    dlg.m["imap_security"].set_active_id("none")
    dlg.m["smtp_host"].set_text("127.0.0.1")
    dlg.m["smtp_port"].set_value(sp)
    dlg.m["smtp_security"].set_active_id("none")
    dlg.m["password"].set_text("pw")
    dlg.response(Gtk.ResponseType.OK)
    ok = wait(lambda: any(a["email"] == "bob@example.org" for a in store.accounts()), 20)
    check(ok, "a second account added through the dialog")
    wait(lambda: not app.busy(), 15)
    win.refresh_folders()
    tops = []
    win.folders_model.foreach(lambda m, p, it: tops.append(m[it][0]) if m[it][4] == "account" else None)
    check(len(tops) == 2, "both accounts in the Folder Pane")
    # wrong password reported
    dlg = AccountDialog(win)
    dlg.email_entry.set_text("me2@example.org")
    dlg.manual_check.set_active(True)
    dlg.response(Gtk.ResponseType.OK)
    for k, v in (("imap_host", "127.0.0.1"), ("smtp_host", "127.0.0.1")):
        dlg.m[k].set_text(v)
    dlg.m["imap_port"].set_value(ip)
    dlg.m["imap_security"].set_active_id("none")
    dlg.m["password"].set_text("bad")
    dlg.response(Gtk.ResponseType.OK)
    wait(lambda: "accept" in dlg.msg.get_text() or "reach" in dlg.msg.get_text(), 15)
    check("accept" in dlg.msg.get_text() or "reach" in dlg.msg.get_text(), "a wrong password is reported: %s" % dlg.msg.get_text())
    dlg.destroy()

    # signatures
    from folio_post.options import signatures_dialog
    sd = signatures_dialog(win)
    ANSWERS[:] = ["Work"]
    sd.parts["new"]()
    pump(0.1)
    sd.parts["editor"].set_sensitive(True)
    sd.parts["editor"].buf.insert_at_cursor("Me Myself\nFolio")
    sd.parts["new_combo"].set_active_id("Work")
    sd.response(Gtk.ResponseType.OK)
    pump(0.2)
    check("Work" in store.get("signatures", {}), "signature saved")
    c = app.compose(account=aid)
    pump(0.3)
    check("Me Myself" in c.editor.text(), "new message starts with the signature")
    c.modified = False
    c.destroy_window()

    # backstage, keytips, help
    win.show_backstage()
    pump(0.2)
    check(win.backstage.get_visible(), "File opens the Backstage")
    shot(win, "backstage")
    key(win, "Escape")
    check(not win.backstage.get_visible(), "Esc closes it")
    win.keytips.start()
    pump(0.2)
    check(win.keytips.active, "KeyTips")
    win.keytips.leave()
    INFO.clear()
    win.run("go:people")
    check(win.module == "people" and win.nav_buttons["people"].get_active(), "the Navigation bar opens People")
    win.run("go:mail")
    check(win.module == "mail" and win.nav_buttons["mail"].get_active(), "and back to Mail")
    win.run("view-mode:single")
    win.run("reset-view")
    check(win.vset("mode", "compact") == "compact", "Reset View")
    stop()
except Exception:
    traceback.print_exc()
    FAILS.append("exception")

print("UI FAILS: %d" % len(FAILS) if FAILS else "UI all passed")
sys.stdout.flush()
os._exit(1 if FAILS else 0)
