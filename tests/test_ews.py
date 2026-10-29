"""Exchange (EWS) tests against the test server: sign-in (Basic, Bearer, NTLM), mail both ways,
sending, calendar, contacts and tasks both ways, Automatic Replies, free/busy, delegates and
another person's calendar."""
import base64
import datetime as dt
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "app"))
sys.path.insert(0, HERE)
os.environ["FOLIO_POST_FILE_SECRETS"] = "1"

import ewsserver  # noqa: E402
from folio_post import ews, ical, mime, store as S, sync, tasks, vcard, caldav, carddav  # noqa: E402

FAILS = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    sys.stdout.flush()
    if not cond:
        FAILS.append(what)


# ---------------------------------------------------------------- NTLM pieces (MS-NLMP 4.2 test values)
check(ews.md4(b"").hex() == "31d6cfe0d16ae931b73c59d7e0c089c0" and ews.md4(b"abc").hex() == "a448017aaf21d8525fc10ae87aa6729d",
      "MD4 (RFC 1320 test values)")
check(ews.ntowf_v2("User", "Password", "Domain").hex() == "0c868a403bfd7a93a3001ef22ef02e3f", "NTOWFv2 (MS-NLMP 4.2.4.1.1)")

world = ewsserver.World()
me = world.add_user("me@contoso.test", "secret", "Megan Bowen")
bob = world.add_user("bob@contoso.test", "pw", "Bob Kelly")
ann = world.add_user("ann@contoso.test", "pw2", "Ann Lee")
srv, url = ewsserver.start(world)


def put_mail(box, folder, subject, read=False, body="Hello"):
    import xml.etree.ElementTree as ET
    raw = ("From: Bob Kelly <bob@contoso.test>\r\nTo: me@contoso.test\r\nSubject: %s\r\nMessage-ID: <%s@contoso.test>\r\n"
           "Date: Mon, 26 Oct 2026 10:00:00 +0000\r\n\r\n%s\r\n" % (subject, subject.replace(" ", ""), body)).encode()
    el = ET.Element(ewsserver.t("Message"))
    ewsserver.set_id(el, "I-%s" % os.urandom(6).hex())
    ET.SubElement(el, ewsserver.t("MimeContent")).text = base64.b64encode(raw).decode()
    ewsserver.set_child(el, "Subject", subject)
    ewsserver.set_child(el, "IsRead", "true" if read else "false")
    ewsserver.set_child(el, "DateTimeReceived", "2026-10-26T10:00:00Z")
    box.folders[box.dist[folder]]["items"][ewsserver.item_id(el)] = el
    return el


for i in range(5):
    put_mail(me, "inbox", "Report %d" % i, read=i > 2)
put_mail(me, "sentitems", "Earlier reply", read=True)

root = tempfile.mkdtemp()
st = S.Store(root)
sec = sync.Secrets(os.path.join(root, "secrets.json"))
sy = sync.Syncer(st, sec)
cfg = {"ews_url": url, "user": "me@contoso.test", "auth": "password", "ews_auth": "basic"}
check(sy.test_account(cfg, "secret", kind="ews") == "", "sign-in with a password works")
check("didn't accept" in sy.test_account(cfg, "wrong", kind="ews"), "a wrong password is reported")
c = ews.Client(url, "CONTOSO\\me", "secret", auth="ntlm")
check(c.get_folders(["inbox"]).get("inbox"), "NTLM sign-in (Exchange in an organisation)")
c2 = ews.Client(url, "CONTOSO\\me", "nope", auth="ntlm")
try:
    c2.get_folders(["inbox"])
    check(False, "a wrong NTLM password is refused")
except ews.AuthError:
    check(True, "a wrong NTLM password is refused")
cb = ews.Client(url, token=lambda: "test-token", auth="bearer")
check(cb.get_folders(["inbox"]).get("inbox"), "Microsoft sign-in (OAuth token) works")

aid = st.add_account("Megan", "me@contoso.test", "ews", cfg)
sec.set(aid, "secret")
check(sy.sync_account(aid), "first sync of the Exchange account")
inbox = st.folder_by_role(aid, "inbox")
check(inbox is not None and st.folder_by_role(aid, "sent") and st.folder_by_role(aid, "trash") and st.folder_by_role(aid, "junk"),
      "Exchange's folders with their roles")
msgs = st.messages(inbox["id"])
check(len(msgs) == 5 and st.counts(inbox["id"])[1] == 3, "5 messages, 3 unread")
check(b"Hello" in st.raw(msgs[0]["id"]), "the message itself came down")
# flags up and down
r0 = [x for x in msgs if x["subject"] == "Report 0"][0]
st.set_flag([r0["id"]], "seen", True)
st.set_flag([r0["id"]], "flagged", True)
sy.sync_account(aid)
el0 = [e for e in me.folders[me.dist["inbox"]]["items"].values() if ewsserver.text_of(e, "Subject") == "Report 0"][0]
check(ewsserver.text_of(el0, "IsRead") == "true", "read state sent to Exchange")
check(el0.findtext("t:Flag/t:FlagStatus", "", ewsserver.NS) == "Flagged", "flag sent to Exchange")
el1 = [e for e in me.folders[me.dist["inbox"]]["items"].values() if ewsserver.text_of(e, "Subject") == "Report 1"][0]
ewsserver.set_child(el1, "IsRead", "true")
sy.sync_account(aid)
check(st.message([x for x in msgs if x["subject"] == "Report 1"][0]["id"])["seen"] == 1, "read elsewhere shows read here")
# new mail arrives
put_mail(me, "inbox", "Fresh news")
sy.sync_account(aid)
check(any(x["subject"] == "Fresh news" for x in st.messages(inbox["id"])), "new mail arrives")
# move to another folder and delete
trash = st.folder_by_role(aid, "trash")
r2 = [x for x in st.messages(inbox["id"]) if x["subject"] == "Report 2"][0]
st.move([r2["id"]], trash["id"])
sy.sync_account(aid)
subj = lambda f: sorted(ewsserver.text_of(e, "Subject") for e in me.folders[me.dist[f]]["items"].values())  # noqa: E731
check("Report 2" in subj("deleteditems") and "Report 2" not in subj("inbox"), "moved to Deleted Items on Exchange")
r3 = [x for x in st.messages(inbox["id"]) if x["subject"] == "Report 3"][0]
st.delete(r3["id"])
sy.sync_account(aid)
check("Report 3" not in subj("inbox"), "deleted on Exchange")
# a folder made here
sy.server_op(aid, lambda cc: cc.create("Inbox/Projects"))
sy.sync_account(aid)
check(any(f["path"] == "Inbox/Projects" for f in st.folders(aid)), "a new folder on Exchange")
# sending
raw = (b"From: Megan Bowen <me@contoso.test>\r\nTo: Bob Kelly <bob@contoso.test>\r\nBcc: ann@contoso.test\r\nSubject: Lunch?\r\n"
       b"Message-ID: <lunch@contoso.test>\r\n\r\nShall we?\r\n")
st.queue(aid, raw, ["bob@contoso.test", "ann@contoso.test"])
sy.sync_account(aid)
bobs = [base64.b64decode(e.find(ewsserver.t("MimeContent")).text) for e in bob.folders[bob.dist["inbox"]]["items"].values()]
anns = [base64.b64decode(e.find(ewsserver.t("MimeContent")).text) for e in ann.folders[ann.dist["inbox"]]["items"].values()]
check(any(b"Lunch?" in x for x in bobs) and any(b"Lunch?" in x for x in anns), "sent through Exchange to To and Bcc")
check(not any(b"Bcc:" in x for x in bobs), "Bcc kept out of what arrives")
check("Lunch?" in subj("sentitems"), "Exchange keeps the copy in Sent Items")
sy.sync_account(aid)
sent = st.folder_by_role(aid, "sent")
check(sum(1 for x in st.messages(sent["id"]) if x["subject"] == "Lunch?") == 1, "one copy in Sent Items here")

# ---------------------------------------------------------------- calendar
cals, books = ews.add_account_sources(st, None, st.account(aid))
st.put("tasks-account", aid)
check(len(cals) == 1 and len(books) == 1, "the account's Calendar and Contacts are added")
cal = st.calendar(cals[0])
AMS = ical.tz("Europe/Amsterdam")
ev = ical.new_event("Planning", dt.datetime(2026, 11, 2, 10, 0, tzinfo=AMS), dt.datetime(2026, 11, 2, 11, 0, tzinfo=AMS),
                    location="Room 4", description="Agenda", rrule="FREQ=WEEKLY;BYDAY=MO;COUNT=4", reminder=10)
eid = caldav.save_event(st, cal["id"], [ev])
sy.sync_account(aid)
items = list(me.folders[me.dist["calendar"]]["items"].values())
check(len(items) == 1 and ewsserver.text_of(items[0], "Subject") == "Planning" and
      ewsserver.text_of(items[0], "Start") == "2026-11-02T09:00:00Z", "an event made here is on Exchange (at 09:00 UTC)")
check(items[0].find("t:Recurrence/t:WeeklyRecurrence", ewsserver.NS) is not None and
      items[0].findtext("t:Recurrence/t:NumberedRecurrence/t:NumberOfOccurrences", "", ewsserver.NS) == "4", "with its repeat")
check(ewsserver.text_of(items[0], "ReminderMinutesBeforeStart") == "10" and ewsserver.text_of(items[0], "Location") == "Room 4",
      "reminder and location")
e = st.event(eid)
check(e["href"] and not e["pending"], "the event knows its Exchange item")
ev2 = ical.Event(ical.events_of(ical.parse(e["ics"]))[0].comp)
ev2.set_text("SUMMARY", "Planning (moved)")
ev2.set_times(dt.datetime(2026, 11, 2, 14, 0, tzinfo=AMS), dt.datetime(2026, 11, 2, 15, 0, tzinfo=AMS))
caldav.save_event(st, cal["id"], [ev2], eid)
sy.sync_account(aid)
check(ewsserver.text_of(items[0], "Subject") == "Planning (moved)" and ewsserver.text_of(items[0], "Start") == "2026-11-02T13:00:00Z",
      "a change here goes to Exchange")
# made on Exchange (Outlook)
import xml.etree.ElementTree as ET  # noqa: E402
x = ET.fromstring('<t:CalendarItem xmlns:t="%s"><t:Subject>Dentist</t:Subject><t:Start>2026-11-05T08:30:00Z</t:Start>'
                  '<t:End>2026-11-05T09:00:00Z</t:End><t:IsAllDayEvent>false</t:IsAllDayEvent><t:Location>Town</t:Location>'
                  '<t:LegacyFreeBusyStatus>OOF</t:LegacyFreeBusyStatus><t:UID>dentist-1</t:UID></t:CalendarItem>' % ewsserver.T)
ewsserver.set_id(x, "I-dentist")
me.folders[me.dist["calendar"]]["items"]["I-dentist"] = x
y = ET.fromstring('<t:CalendarItem xmlns:t="%s"><t:Subject>Holiday</t:Subject><t:Start>2026-12-23T23:00:00Z</t:Start>'
                  '<t:End>2026-12-25T23:00:00Z</t:End><t:IsAllDayEvent>true</t:IsAllDayEvent><t:UID>hol-1</t:UID></t:CalendarItem>' % ewsserver.T)
ewsserver.set_id(y, "I-hol")
me.folders[me.dist["calendar"]]["items"]["I-hol"] = y
sy.sync_account(aid)
evs = {r["summary"]: r for r in st.events(cal["id"])}
check("Dentist" in evs and "Holiday" in evs, "events made in Outlook come here")
de = ical.events_of(ical.parse(evs["Dentist"]["ics"]))[0]
check(de.start.astimezone(dt.timezone.utc).hour == 8 and de.location == "Town" and de.busy == "oof", "with time, place and Out of Office")
he = ical.events_of(ical.parse(evs["Holiday"]["ics"]))[0]
check(he.all_day and str(he.start)[:10] == "2026-12-24", "an all-day event keeps its day (%s)" % he.start)
ewsserver.set_child(x, "Subject", "Dentist (moved)")
ewsserver.set_id(x, "I-dentist")
sy.sync_account(aid)
check(any(r["summary"] == "Dentist (moved)" for r in st.events(cal["id"])), "changes in Outlook come here")
caldav.delete_event(st, [r for r in st.events(cal["id"]) if r["summary"] == "Planning (moved)"][0]["id"])
sy.sync_account(aid)
check(not any(ewsserver.text_of(i, "Subject").startswith("Planning") for i in me.folders[me.dist["calendar"]]["items"].values()),
      "deleted here, gone from Exchange")
del me.folders[me.dist["calendar"]]["items"]["I-hol"]
sy.sync_account(aid)
check(not any(r["summary"] == "Holiday" for r in st.events(cal["id"])), "deleted in Outlook, gone here")

# ---------------------------------------------------------------- contacts
book = st.book(books[0])
k = vcard.new_contact("Diego Siciliani", "diego@contoso.test", "Contoso", "+31 6 1234 5678")
k.set_text("TITLE", "Engineer")
cid = carddav.save_contact(st, book["id"], k)
sy.sync_account(aid)
cts = list(me.folders[me.dist["contacts"]]["items"].values())
check(len(cts) == 1 and ewsserver.text_of(cts[0], "DisplayName") == "Diego Siciliani" and
      cts[0].findtext("t:EmailAddresses/t:Entry", "", ewsserver.NS) == "diego@contoso.test" and
      ewsserver.text_of(cts[0], "JobTitle") == "Engineer", "a contact made here is on Exchange")
k2 = vcard.parse(st.contact(cid)["vcard"])
k2.set_emails([("work", "diego.s@contoso.test")])
k2.set_phones([("cell", "+31 6 0000 0000")])
carddav.save_contact(st, book["id"], k2, cid)
sy.sync_account(aid)
check(cts[0].findtext("t:EmailAddresses/t:Entry", "", ewsserver.NS) == "diego.s@contoso.test" and
      cts[0].findtext("t:PhoneNumbers/t:Entry", "", ewsserver.NS) == "+31 6 0000 0000", "a change goes to Exchange")
g = ET.fromstring('<t:Contact xmlns:t="%s"><t:DisplayName>Isaiah Langer</t:DisplayName><t:GivenName>Isaiah</t:GivenName>'
                  '<t:Surname>Langer</t:Surname><t:CompanyName>Fabrikam</t:CompanyName><t:EmailAddresses>'
                  '<t:Entry Key="EmailAddress1">isaiah@fabrikam.test</t:Entry></t:EmailAddresses><t:PhoneNumbers>'
                  '<t:Entry Key="BusinessPhone">+1 555 0100</t:Entry></t:PhoneNumbers></t:Contact>' % ewsserver.T)
ewsserver.set_id(g, "I-isaiah")
me.folders[me.dist["contacts"]]["items"]["I-isaiah"] = g
dl = ET.fromstring('<t:DistributionList xmlns:t="%s"><t:DisplayName>Team</t:DisplayName><t:Members><t:Member><t:Mailbox>'
                   '<t:EmailAddress>bob@contoso.test</t:EmailAddress></t:Mailbox></t:Member><t:Member><t:Mailbox>'
                   '<t:EmailAddress>ann@contoso.test</t:EmailAddress></t:Mailbox></t:Member></t:Members></t:DistributionList>' % ewsserver.T)
ewsserver.set_id(dl, "I-team")
me.folders[me.dist["contacts"]]["items"]["I-team"] = dl
sy.sync_account(aid)
people = {r["name"]: vcard.parse(r["vcard"]) for r in st.contacts(book["id"])}
check("Isaiah Langer" in people and people["Isaiah Langer"].company == "Fabrikam" and
      people["Isaiah Langer"].emails[0][1] == "isaiah@fabrikam.test", "a contact made in Outlook comes here")
check("Team" in people and people["Team"].is_group and sorted(people["Team"].member_emails()) == ["ann@contoso.test", "bob@contoso.test"],
      "a contact group comes here with its members")
carddav.delete_contact(st, cid)
sy.sync_account(aid)
check(not any(ewsserver.text_of(i, "DisplayName") == "Diego Siciliani" for i in me.folders[me.dist["contacts"]]["items"].values()),
      "a contact deleted here is gone from Exchange")

# ---------------------------------------------------------------- tasks
tk = tasks.new_task("Write the report", dt.date(2026, 11, 9))
tasks.save(st, tk)
sy.sync_account(aid)
tis = list(me.folders[me.dist["tasks"]]["items"].values())
check(len(tis) == 1 and ewsserver.text_of(tis[0], "Subject") == "Write the report" and
      ewsserver.text_of(tis[0], "DueDate")[:10] == "2026-11-09", "a task made here is on Exchange")
import time as _time  # noqa: E402
_time.sleep(1.1)
row = st.todos("task")[0]
t2 = tasks.parse(row["data"])
t2.set_status("COMPLETED")
tasks.save(st, t2, row["id"])
sy.sync_account(aid)
check(ewsserver.text_of(tis[0], "Status") == "Completed", "marked complete here, complete on Exchange")
tx = ET.fromstring('<t:Task xmlns:t="%s"><t:Subject>Call Ann</t:Subject><t:Importance>High</t:Importance>'
                   '<t:Status>InProgress</t:Status><t:PercentComplete>50</t:PercentComplete></t:Task>' % ewsserver.T)
ewsserver.set_id(tx, "I-callann")
me.folders[me.dist["tasks"]]["items"]["I-callann"] = tx
sy.sync_account(aid)
tt = {r["subject"]: tasks.parse(r["data"]) for r in st.todos("task")}
check("Call Ann" in tt and tt["Call Ann"].priority == 1 and tt["Call Ann"].percent == 50 and tt["Call Ann"].status == "IN-PROCESS",
      "a task made in Outlook comes here")
del me.folders[me.dist["tasks"]]["items"]["I-callann"]
sy.sync_account(aid)
check("Call Ann" not in {r["subject"] for r in st.todos("task")}, "deleted in Outlook, gone here")

# ---------------------------------------------------------------- Automatic Replies, free/busy, delegates
cl = sy.ews_client(st.account(aid))
cl.set_oof("me@contoso.test", {"state": "on", "audience": "all", "internal": "I'm away until Monday.",
                                "external": "Away until Monday."})
o = cl.get_oof("me@contoso.test")
check(o["state"] == "on" and o["internal"] == "I'm away until Monday.", "Automatic Replies set on Exchange")
cb2 = ews.Client(url, "bob@contoso.test", "pw")
cb2.send_mime(b"From: bob@contoso.test\r\nTo: me@contoso.test\r\nSubject: Question\r\n\r\nHi\r\n")
check(any(ewsserver.text_of(e, "Subject") == "Automatic reply: Question" for e in bob.folders[bob.dist["inbox"]]["items"].values()),
      "and Exchange answers with them")
start = dt.datetime(2026, 11, 2, 7, 0, tzinfo=dt.timezone.utc)
bx = ET.fromstring('<t:CalendarItem xmlns:t="%s"><t:Subject>Busy</t:Subject><t:Start>2026-11-02T10:00:00Z</t:Start>'
                   '<t:End>2026-11-02T11:30:00Z</t:End><t:LegacyFreeBusyStatus>Busy</t:LegacyFreeBusyStatus></t:CalendarItem>' % ewsserver.T)
ewsserver.set_id(bx, "I-bobbusy")
bob.folders[bob.dist["calendar"]]["items"]["I-bobbusy"] = bx
fb = cl.availability(["bob@contoso.test", "nobody@contoso.test"], start, start + dt.timedelta(hours=12))
check(fb["bob@contoso.test"] and fb["bob@contoso.test"][0][0].hour == 10 and fb["bob@contoso.test"][0][2] == "busy",
      "Bob's free/busy from Exchange")
check(fb["nobody@contoso.test"] is None, "no free/busy for an unknown address")
check(cl.resolve("bob") == [("Bob Kelly", "bob@contoso.test")], "Check Names finds Bob")
# Bob shares his calendar with Megan (delegate)
try:
    ews.open_shared_calendar(st, cl, st.account(aid), "bob@contoso.test")
    check(False, "Bob's calendar is closed before he shares it")
except ews.EwsError as err:
    check(err.code == "ErrorAccessDenied", "Bob's calendar is closed before he shares it")
cb2.add_delegate("bob@contoso.test", "me@contoso.test", calendar="Reviewer")
check(cb2.get_delegates("bob@contoso.test")[0]["calendar"] == "Reviewer", "Bob makes Megan his delegate (Reviewer)")
sc = ews.open_shared_calendar(st, cl, st.account(aid), "bob@contoso.test", "Bob Kelly")
sy.sync_account(aid)
check([r["summary"] for r in st.events(sc)] == ["Busy"], "Megan sees Bob's calendar")
cl.add_delegate("me@contoso.test", "ann@contoso.test", calendar="Editor", tasks="Reviewer")
d = cl.get_delegates("me@contoso.test")
check(d and d[0]["email"] == "ann@contoso.test" and d[0]["calendar"] == "Editor" and d[0]["tasks"] == "Reviewer",
      "Megan gives Ann Editor on her calendar")
cl.remove_delegate("me@contoso.test", "ann@contoso.test")
check(cl.get_delegates("me@contoso.test") == [], "and takes it back")

srv.shutdown()
print("EWS tests: %s" % ("all passed" if not FAILS else "%d FAILED" % len(FAILS)))
sys.exit(1 if FAILS else 0)
