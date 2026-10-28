"""People engine tests: vCard and CardDAV two-way sync."""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "app"))
sys.path.insert(0, HERE)
from folio_post import carddav, vcard  # noqa: E402
from folio_post import store as S  # noqa: E402
from folio_post import sync  # noqa: E402
import davserver  # noqa: E402

FAILS = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        FAILS.append(what)


V3 = ("BEGIN:VCARD\r\nVERSION:3.0\r\nUID:ann-1\r\nFN:Ann Lee\r\nN:Lee;Ann;;;\r\nORG:Folio Ltd;Sales\r\nTITLE:Manager\r\n"
      "EMAIL;TYPE=INTERNET,WORK,PREF:ann@example.org\r\nEMAIL;TYPE=INTERNET,HOME:ann@home.example\r\n"
      "TEL;TYPE=CELL:+31 6 1234 5678\r\nTEL;TYPE=WORK,VOICE:+31 20 555 0101\r\n"
      "ADR;TYPE=WORK:;;Main St 1;Amsterdam;;1011 AB;Netherlands\r\nNOTE:Met at the fair\\, 2025\r\nBDAY:1990-04-05\r\nEND:VCARD\r\n")
V4 = ("BEGIN:VCARD\r\nVERSION:4.0\r\nUID:urn:uuid:bob-2\r\nFN:Bob Stone\r\nEMAIL;TYPE=work:bob@example.org\r\n"
      "item1.TEL:+1 555 0100\r\nEND:VCARD\r\n")
QP = ("BEGIN:VCARD\r\nVERSION:2.1\r\nN:M=C3=BCller;J=C3=BCrgen\r\nFN;CHARSET=UTF-8;ENCODING=QUOTED-PRINTABLE:J=C3=BCrgen M=C3=BCller\r\n"
      "EMAIL:j@example.de\r\nEND:VCARD\r\n")
cs = vcard.parse_all(V3 + V4 + QP)
check(len(cs) == 3, "three cards in one file")
a, b, j = cs
check(a.name == "Ann Lee" and a.n[0] == "Lee" and a.company == "Folio Ltd" and a.department == "Sales", "names and company")
check(a.emails == [("work", "ann@example.org"), ("home", "ann@home.example")], "e-mail addresses with their kinds")
check(("cell", "+31 6 1234 5678") in a.phones and ("work", "+31 20 555 0101") in a.phones, "phones")
check(a.addresses[0][1]["city"] == "Amsterdam" and a.note == "Met at the fair, 2025", "address and note")
check(b.uid == "bob-2" and b.phones == [("other", "+1 555 0100")], "vCard 4 and grouped properties")
check(j.name == "Jürgen Müller", "vCard 2.1 quoted-printable")
c = vcard.new_contact("Carol Diaz", "carol@example.org", "Acme", "+44 20 7946 0000")
c.set_address("home", {"street": "High St 5", "city": "London", "country": "UK"})
back = vcard.parse(c.dumps())
check(back.name == "Carol Diaz" and back.n[1] == "Carol" and back.emails[0][1] == "carol@example.org" and back.company == "Acme",
      "written and read back")
check(back.addresses[0][1]["city"] == "London", "address written")
g = vcard.new_group("Team", ["ann@example.org"], [b.uid])
gb = vcard.parse(g.dumps())
check(gb.is_group and gb.member_emails() == ["ann@example.org"] and gb.member_uids() == ["bob-2"], "contact group")
check(all(len(x.encode()) <= 75 for x in vcard.new_contact("x" * 120).dumps().split("\r\n")), "long lines folded")
c.set_photo(b"\x89PNGfake", "image/png")
check(vcard.parse(c.dumps()).photo == b"\x89PNGfake", "photo kept")

# CardDAV
world = davserver.World()
world.add_user("me@example.org", "secret", ("personal",), ("contacts", "work"))
world.books["me@example.org"]["contacts"].put("ann-1.vcf", V3)
_w, port, stop = davserver.start(world)
root = tempfile.mkdtemp()
st = S.Store(root)
sec = sync.Secrets(os.path.join(root, "secrets.json"))
cy = carddav.ContactSync(st, sec, None)
url = "http://127.0.0.1:%d/" % port
ids = cy.add_carddav(url, "me@example.org", "secret")
check(sorted(st.book(i)["name"] for i in ids) == ["Contacts", "Work"], "address books discovered")
bid = [i for i in ids if st.book(i)["name"] == "Contacts"][0]
check(cy.sync(bid) and [x["name"] for x in st.contacts(bid)] == ["Ann Lee"], "contacts brought down")
cid = carddav.save_contact(st, bid, vcard.new_contact("Dan Park", "dan@example.org"))
cy.sync(bid)
srv = world.books["me@example.org"]["contacts"].items
check(any("Dan Park" in d for _e, d in srv.values()), "new contact on the server")
ann = [x for x in st.contacts(bid) if x["name"] == "Ann Lee"][0]
card = vcard.parse(ann["vcard"])
card.set_name("Ann Lee-Smith")
carddav.save_contact(st, bid, card, ann["id"])
cy.sync(bid)
check("Ann Lee-Smith" in srv["ann-1.vcf"][1], "change on the server")
world.books["me@example.org"]["contacts"].put("eve.vcf", vcard.new_contact("Eve Ng", "eve@example.org").dumps())
cy.sync(bid)
check("Eve Ng" in [x["name"] for x in st.contacts(bid)], "server change comes down")
carddav.delete_contact(st, cid)
cy.sync(bid)
check(not any("Dan Park" in d for _e, d in srv.values()) and "Dan Park" not in [x["name"] for x in st.contacts(bid)], "deleted both sides")
check([x["name"] for x in st.find_people("ev")] == ["Eve Ng"] and st.find_people("example.org"), "find people")
cb = carddav.CardClient(url, "me@example.org", token=lambda: "test-token")
check(len(cb.books()) == 2, "OAuth bearer sign-in")
stop()
print("FAILED: %d" % len(FAILS) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
