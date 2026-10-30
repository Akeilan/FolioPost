# Run inside Folio Post (FOLIO_TEST_SCRIPT): Backlog 3 — an Exchange account added in the dialog, Automatic
# Replies, the Scheduling Assistant, other people's calendars and permissions, voting buttons, Outlook
# templates and RSS feeds, against the local test servers.
import datetime as dt
import http.server
import os
import sys
import tempfile
import threading
import time
import traceback

from gi.repository import Gtk

sys.path.insert(0, os.environ["FOLIO_TESTS"])
import ewsserver  # noqa: E402
import mailserver  # noqa: E402
import sieveserver  # noqa: E402

FAILS = []
INFO = []
OUT = os.environ.get("UI_OUT", "/tmp/ui_out")
os.makedirs(OUT, exist_ok=True)
TMP = tempfile.mkdtemp(prefix="post-b3-")


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
    alloc = w.get_allocation()
    img = cairo.ImageSurface(cairo.FORMAT_ARGB32, max(1, alloc.width), max(1, alloc.height))
    w.draw(cairo.Context(img))
    img.write_to_png(os.path.join(OUT, "b3_" + name + ".png"))


from folio_post import dialogs as D  # noqa: E402
ANSWERS = []
DLG = []          # functions that answer the next Gtk.Dialog.run
D.Dialogs.info = lambda self, text, title=None: INFO.append(text)
D.Dialogs.message = lambda self, text, title=None: INFO.append(text)
D.Dialogs.ask_text = lambda self, title, label, value="": ANSWERS.pop(0) if ANSWERS else value


def fake_run(d):
    pump(0.1)
    if DLG:
        return DLG.pop(0)(d)
    return Gtk.ResponseType.CANCEL


Gtk.Dialog.run = fake_run

try:
    from folio_post import ews, freebusy, eventwin, ical, mime, msgfile, rss, voting
    store = app.store
    L = ical.local_tz()
    # ---------------------------------------------------------------- an Exchange account, through Add Account
    ew = ewsserver.World()
    megan = ew.add_user("me@contoso.test", "secret", "Megan Bowen")
    bob = ew.add_user("bob@contoso.test", "pw", "Bob Kelly")
    esrv, eurl = ewsserver.start(ew)
    from folio_post.accounts import AccountDialog
    d = AccountDialog(win)
    d.name_entry.set_text("Megan Bowen")
    d.email_entry.set_text("me@contoso.test")
    d.exchange_check.set_active(True)
    d.on_response(d, Gtk.ResponseType.OK)
    pump(0.2)
    check(d.page == "exchange" and d.ex_ms.get_active(), "Add Account > Exchange: Microsoft sign-in offered first")
    shot(d, "exchange_page")
    d.ex_pw.set_active(True)
    d.ex["url"].set_text(eurl)
    d.ex["user"].set_text("CONTOSO\\me")
    d.ex["password"].set_text("secret")
    d.ex["auth"].set_active_id("ntlm")
    d.on_response(d, Gtk.ResponseType.OK)
    ok = wait(lambda: any(a["kind"] == "ews" for a in store.accounts()), 20)
    check(ok, "the Exchange account is added (NTLM sign-in)")
    acc = [a for a in store.accounts() if a["kind"] == "ews"][0]
    aid = acc["id"]
    check(any(c["kind"] == "ews" and c["account"] == aid for c in store.calendars()) and
          any(b["kind"] == "ews" and b["account"] == aid for b in store.books()) and store.get("tasks-account") == aid,
          "with its Calendar, Contacts and Tasks")
    wait(lambda: store.folder_by_role(aid, "inbox") is not None, 20)
    wait(lambda: not app.busy(), 20)
    check(store.folder_by_role(aid, "sent") is not None, "Exchange's folders arrive")

    # ---------------------------------------------------------------- Automatic Replies
    def oof_answer(dlg):
        dlg.on.set_active(True)
        dlg.views["internal"].get_buffer().set_text("Away until Monday.")
        dlg.views["external"].get_buffer().set_text("Away.")
        shot(dlg, "autoreplies")
        return Gtk.ResponseType.OK
    win.go_folder(store.folder_by_role(aid, "inbox")["id"])
    DLG.append(oof_answer)
    r = win.run("automatic-replies")
    check(r and megan.oof["state"] == "Enabled" and megan.oof["internal"] == "Away until Monday.", "Automatic Replies on Exchange")
    check(win.autoreply_bar.get_visible(), "the AUTOMATIC REPLIES bar shows")
    shot(win, "autoreply_bar")

    def oof_off(dlg):
        dlg.off.set_active(True)
        return Gtk.ResponseType.OK
    DLG.append(oof_off)
    win.run("automatic-replies")
    check(megan.oof["state"] == "Disabled" and not win.autoreply_bar.get_visible(), "and off again")
    # an IMAP account with ManageSieve
    sw = sieveserver.World()
    su = sw.add_user("me@example.org", "secret")
    ssrv, sport = sieveserver.start(sw)
    mw = mailserver.World()
    mw.add_user("me@example.org", "secret")
    _m, ip, sp, mstop = mailserver.start(mw)
    cfg = {"imap_host": "127.0.0.1", "imap_port": ip, "imap_security": "none", "smtp_host": "127.0.0.1", "smtp_port": sp,
           "smtp_security": "none", "user": "me@example.org", "sieve_port": sport}
    from folio_post.accounts import create_account
    iaid = create_account(win, "Me", "me@example.org", cfg, "secret")
    wait(lambda: store.folder_by_role(iaid, "inbox") is not None, 20)
    wait(lambda: not app.busy(), 20)
    from folio_post import autoreply

    def sieve_answer(dlg):
        dlg.on.set_active(True)
        dlg.timed.set_active(True)
        dlg.entries["Start time"].set_text("2026-11-02 09:00")
        dlg.entries["End time"].set_text("2026-11-06 17:00")
        dlg.views["internal"].get_buffer().set_text("On holiday.")
        check("external" not in dlg.views, "a mail server's Sieve has one reply for everyone")
        return Gtk.ResponseType.OK
    DLG.append(sieve_answer)
    s = autoreply.dialog(win, store.account(iaid))
    check(s and s["state"] == "scheduled" and "vacation" in su["scripts"].get(autoreply.SCRIPT, ""),
          "Automatic Replies through ManageSieve, for a time range")

    # ---------------------------------------------------------------- Scheduling Assistant
    import xml.etree.ElementTree as ET
    bx = ET.fromstring('<t:CalendarItem xmlns:t="%s"><t:Subject>Busy</t:Subject><t:Start>2026-11-02T09:00:00Z</t:Start>'
                       '<t:End>2026-11-02T11:00:00Z</t:End><t:LegacyFreeBusyStatus>Busy</t:LegacyFreeBusyStatus></t:CalendarItem>' % ewsserver.T)
    ewsserver.set_id(bx, "I-bob1")
    bob.folders[bob.dist["calendar"]]["items"]["I-bob1"] = bx
    ecal = [c for c in store.calendars() if c["kind"] == "ews" and c["account"] == aid][0]
    evw = eventwin.EventWindow(win, start=dt.datetime(2026, 11, 2, 10, 0, tzinfo=ical.UTC),
                               end=dt.datetime(2026, 11, 2, 10, 30, tzinfo=ical.UTC), meeting=True, calendar=ecal["id"])
    evw.subject.set_text("Planning")
    evw.to.set_text("Bob Kelly <bob@contoso.test>")
    pump(0.3)
    check(any(getattr(c, "action", "") == "scheduling-assistant" for c in evw.ribbon.controls), "the meeting has a Scheduling Assistant button")
    got = {}

    def assistant(dlg):
        dlg.refresh(wait=True)
        got["busy"] = dlg.busy.get("bob@contoso.test")
        got["conflicts"] = dlg.conflicts()
        shot(dlg, "assistant")
        got["auto"] = dlg.autopick()
        return Gtk.ResponseType.OK
    DLG.append(assistant)
    new = evw.run("scheduling-assistant")
    check(got.get("busy") and got["busy"][0][0].astimezone(ical.UTC).hour == 9, "Bob's busy time from Exchange")
    check(got.get("conflicts") == ["Bob Kelly"], "the meeting clashes with Bob")
    check(new is not None and new.astimezone(ical.UTC) == dt.datetime(2026, 11, 2, 11, 0, tzinfo=ical.UTC) and
          evw.start_row.value().astimezone(ical.UTC).hour == 11, "AutoPick moves the meeting to when everyone is free (%s, %s)"
          % (new, evw.start_row.value()))
    evw.modified = False
    evw.destroy()

    # ---------------------------------------------------------------- other people's calendars, permissions
    win.run("go:calendar")
    pump(0.3)
    oc = [c for c in win.ribbon.controls if getattr(c, "label", "") == "Calendar Permissions"]
    check(bool(oc), "Calendar Permissions on the Calendar ribbon")
    ids = win.act_open_shared_calendar("bob@contoso.test", aid)
    check(ids is None and any("share it with you" in i for i in INFO), "Bob's calendar is closed until he shares it")
    cb = ews.Client(eurl, "bob@contoso.test", "pw")
    cb.add_delegate("bob@contoso.test", "me@contoso.test", calendar="Reviewer")
    ids = win.act_open_shared_calendar("bob@contoso.test", aid)
    check(ids and wait(lambda: [e["summary"] for e in store.events(ids[0])] == ["Busy"], 10), "Open Shared Calendar: Bob's events")

    def perms(dlg):
        dlg.add("bob@contoso.test", "Editor")
        got["perm"] = [tuple(r) for r in dlg.store_]
        shot(dlg, "permissions")
        dlg.remove("bob@contoso.test")
        got["perm2"] = [tuple(r) for r in dlg.store_]
        return Gtk.ResponseType.CLOSE
    DLG.append(perms)
    win.act_calendar_permissions(aid)
    check(got.get("perm") == [("bob@contoso.test", "Editor")] and got.get("perm2") == [], "Calendar Permissions: Bob made Editor, then removed")
    win.run("go:mail")
    pump(0.3)

    # ---------------------------------------------------------------- voting buttons
    c = app.compose(account=iaid, to="bob@example.org", subject="Budget 2027")
    pump(0.3)
    c.editor.load_html("<p>Please vote.</p>")
    c.run("voting:Approve;Reject")
    check(c.voting == ["Approve", "Reject"], "Options > Use Voting Buttons > Approve;Reject")
    m = c.build()
    check(mime.header(m, voting.HEADER) == "Approve;Reject" and "Vote: Approve | Reject" in mime.text_of(m), "the choices go with the message")
    # M3-09: Outlook's own voting information too (winmail.dat), unless Options > Mail says not
    from folio_post import tnef
    t = mime.tnef_of(m)
    check(t is not None and tnef.vote_choices(t["props"].get((tnef.PSETID_COMMON, tnef.LID_VERB_STREAM))) == ["Approve", "Reject"]
          and mime.header(m, "X-MS-TNEF-Correlator") == mime.header(m, "Message-ID"), "voting buttons Outlook shows (winmail.dat)")
    app.settings["outlook_voting"] = False
    check(mime.tnef_of(c.build()) is None, "Options > Mail: no winmail.dat when turned off")
    app.settings["outlook_voting"] = True
    mw.add_user("bob@example.org", "pw")
    c.run("send")
    ok = wait(lambda: any(b"Budget 2027" in x[3] for x in mw.users["bob@example.org"][1]["INBOX"].msgs), 20)
    check(ok, "sent")
    wait(lambda: not app.busy(), 20)
    # Bob's vote arrives; the sender's copy shows the tally
    orig = mime.parse([x[3] for x in mw.users["bob@example.org"][1]["INBOX"].msgs if b"Budget 2027" in x[3]][0])
    vote = voting.build_response({"name": "Bob", "email": "bob@example.org"}, orig, "Approve")
    mw.users["me@example.org"][1]["INBOX"].add(mime.to_bytes(vote))
    app.send_receive([iaid])
    wait(lambda: not app.busy(), 20)
    sent = store.folder_by_role(iaid, "sent")
    srow = [r for r in store.messages(sent["id"]) if r["subject"] == "Budget 2027"][0]
    win.go_folder(sent["id"])
    win.select_ids([srow["id"]])
    pump(0.3)
    check(win.reading.vote.get_visible() and "Approve: 1" in win.reading.vote_label.get_text(), "the sender sees the tally")
    check(not srow["attach"] and not any(a["name"] == "winmail.dat" for a in mime.attachments(win.reading.msg)),
          "the Sent copy shows no winmail.dat")
    shot(win, "vote_tally")
    DLG.append(lambda dlg: Gtk.ResponseType.CLOSE)
    counts = win.reading.show_tracking()
    check(counts == {"Approve": ["Bob"], "Reject": []}, "View Tracking lists Bob's answer")
    # and the other side: a message with voting buttons in the Inbox
    mw.users["me@example.org"][1]["INBOX"].add(mime.to_bytes(mime.build(("Ann", "ann@example.org"), [("Me", "me@example.org")], (), (),
                                                                         "Lunch place", "Where?", None, (), (),
                                                                         extra={voting.HEADER: "Pizza;Sushi"})))
    mw.add_user("ann@example.org", "pw")
    app.send_receive([iaid])
    wait(lambda: not app.busy(), 20)
    inbox = store.folder_by_role(iaid, "inbox")
    lrow = [r for r in store.messages(inbox["id"]) if r["subject"] == "Lunch place"][0]
    win.go_folder(inbox["id"])
    win.select_ids([lrow["id"]])
    pump(0.3)
    names = [b.get_label() for b in win.reading.vote_buttons.get_children()]
    check(names == ["Pizza", "Sushi"], "the Reading Pane shows the voting buttons")
    shot(win, "vote_buttons")
    win.reading.vote_for("Sushi")
    ok = wait(lambda: any(b"Sushi: Lunch place" in x[3] for x in mw.users["ann@example.org"][1]["INBOX"].msgs), 20)
    check(ok and "You voted Sushi" in win.reading.vote_label.get_text(), "one click sends the vote")
    # Outlook's voting buttons on a message from Outlook (M3-09)
    om = mime.build(("Carl", "carl@example.org"), [("Me", "me@example.org")], subject="Offsite date", text="Pick one.")
    om["X-MS-TNEF-Correlator"] = om["Message-ID"]
    om.add_attachment(tnef.build([(tnef.PT_BINARY, (tnef.PSETID_COMMON, tnef.LID_VERB_STREAM), tnef.verb_stream(["May", "June"]))]),
                      maintype="application", subtype="ms-tnef", filename="winmail.dat")
    mw.users["me@example.org"][1]["INBOX"].add(mime.to_bytes(om))
    mw.add_user("carl@example.org", "pw")
    app.send_receive([iaid])
    wait(lambda: not app.busy(), 20)
    orow = [r for r in store.messages(inbox["id"]) if r["subject"] == "Offsite date"][0]
    win.select_ids([orow["id"]])
    pump(0.3)
    names = [b.get_label() for b in win.reading.vote_buttons.get_children()]
    check(names == ["May", "June"] and not orow["attach"], "Outlook's voting buttons show (and winmail.dat isn't an attachment)")
    shot(win, "vote_outlook")
    win.reading.vote_for("June")
    ok = wait(lambda: any(b"June: Offsite date" in x[3] for x in mw.users["carl@example.org"][1]["INBOX"].msgs), 20)
    ans = [mime.parse(x[3]) for x in mw.users["carl@example.org"][1]["INBOX"].msgs if b"June: Offsite date" in x[3]]
    at = mime.tnef_of(ans[0]) if ans else None
    check(ok and at is not None and at["props"].get((tnef.PSETID_COMMON, tnef.LID_VERB_RESPONSE)) == "June",
          "the answer carries Outlook's voting response")

    # ---------------------------------------------------------------- Outlook templates
    c = app.compose(account=iaid, to="Ann <ann@example.org>", subject="Weekly report")
    pump(0.3)
    c.editor.load_html("<p>This <b>week</b>:</p>")
    oft = os.path.join(TMP, "weekly.oft")
    c.save_to(oft)
    check(msgfile.read(open(oft, "rb").read())["subject"] == "Weekly report", "Save As > Outlook Template (.oft)")
    c.modified = False
    c.destroy_window()
    n0 = len(app.composers)
    c2 = win.run("choose-form:" + oft)
    pump(0.3)
    check(c2 is not None and len(app.composers) == n0 + 1 and c2.subject.get_text() == "Weekly report" and
          "ann@example.org" in c2.fields["to"].get_text(), "Choose Form opens a new message from it")
    check("week" in c2.editor.text(), "with its body")
    c2.modified = False
    c2.destroy_window()

    # ---------------------------------------------------------------- RSS
    FEED = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>Folio Blog</title><link>http://x/</link>
<item><title>Hello</title><link>http://x/1</link><guid>1</guid><description>First</description></item></channel></rss>"""

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", str(len(FEED)))
            self.end_headers()
            self.wfile.write(FEED)
    hs = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=hs.serve_forever, daemon=True).start()
    ANSWERS.append("http://127.0.0.1:%d/feed.xml" % hs.server_address[1])
    fid = win.run("add-rss-feed")
    check(fid and store.folder(fid)["name"] == "Folio Blog" and win.folder_id == fid and
          [r["subject"] for r in store.messages(fid)] == ["Hello"], "Folder > New RSS Feed: its folder and article")
    shot(win, "rss")
    check(win.run("remove-rss-feed") and store.folder(fid) is None, "Remove RSS Feed")
    hs.shutdown()
    ssrv.shutdown()
    mstop()
    esrv.shutdown()
except Exception:
    traceback.print_exc()
    FAILS.append("exception")
print("UI FAILS: %d" % len(FAILS) if FAILS else "UI all passed")
sys.stdout.flush()
os._exit(1 if FAILS else 0)
