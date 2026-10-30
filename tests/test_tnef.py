"""M3-09: voting buttons Outlook shows — Outlook's winmail.dat (TNEF), written and read.
Written TNEF is checked with two independent readers when installed (ytnefprint, tnef)."""
import os
import shutil
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "app"))
from folio_post import mime, tnef, voting  # noqa: E402

FAILS = []
N = [0]


def check(ok, what):
    N[0] += 1
    print(("ok   " if ok else "FAIL ") + what)
    if not ok:
        FAILS.append(what)


T = tempfile.mkdtemp()
ch = ["Approve", "Reject", "Später"]

# ---- the verb stream
vs = tnef.verb_stream(ch)
check(struct.unpack_from("<HI", vs)[0] == 0x0102 and struct.unpack_from("<HI", vs)[1] == 3, "verb stream: version and count")
check(tnef.vote_choices(vs) == ch, "verb stream read back (Unicode names)")
# one option is 4 + (1+n) + 9 + 1 + (1+n) + 29 bytes
check(len(vs) == 6 + sum(4 + 1 + len(c.encode("cp1252")) + 9 + 1 + 1 + len(c.encode("cp1252")) + 29 for c in ch)
      + 2 + sum(2 + 4 * len(c) for c in ch), "verb stream: every field where Outlook expects it")

# ---- the message Post sends
m = mime.build(("Me", "me@example.org"), [("Ann", "ann@example.org")], subject="Budget 2027", text="Please vote.",
               html_body="<p>Please vote.</p>", extra={voting.HEADER: ";".join(ch)})
voting.add_outlook(m, ch)
raw = mime.to_bytes(m)
back = mime.parse(raw)
check(mime.header(back, "X-MS-TNEF-Correlator") == mime.header(back, "Message-ID"), "TNEF correlator header = Message-ID")
parts = [p for p in back.walk() if p.get_content_type() == "application/ms-tnef"]
check(len(parts) == 1 and parts[0].get_filename() == "winmail.dat", "winmail.dat attached as application/ms-tnef")
dat = parts[0].get_payload(decode=True)
t = tnef.parse(dat)
check(t["class"] == "IPM.Note", "message class IPM.Note")
check(t["props"].get(tnef.TAG_TNEF_CORRELATION_KEY) == mime.header(back, "Message-ID").encode() + b"\0",
      "PidTagTnefCorrelationKey matches the header")
check(tnef.vote_choices(t["props"][(tnef.PSETID_COMMON, tnef.LID_VERB_STREAM)]) == ch, "PidLidVerbStream on the message")
check(mime.attachments(back) == [], "winmail.dat isn't shown as an attachment")
check(not mime.summary(raw)["attach"], "no paper clip for it")
check(mime.body_part(back, "html") is not None and "Please vote" in mime.text_of(back), "the body is still there for every mail app")
# checksums: every attribute's checksum is the byte sum of its data
p, okc = 6, True
while p < len(dat):
    _lv, _a, ln = struct.unpack_from("<BII", dat, p)
    d = dat[p + 9:p + 9 + ln]
    okc = okc and struct.unpack_from("<H", dat, p + 9 + ln)[0] == sum(d) & 0xFFFF
    p += 9 + ln + 2
check(okc and p == len(dat), "attribute checksums and lengths")

open(os.path.join(T, "w.dat"), "wb").write(dat)
if shutil.which("ytnefprint"):
    out = subprocess.run(["ytnefprint", os.path.join(T, "w.dat")], capture_output=True, text=True).stdout
    check("IPM.Note" in out and "UD:x8520" in out and "PR_TNEF_CORRELATION_KEY" in out, "ytnefprint reads it: class, verb stream, correlation key")
if shutil.which("tnef"):
    r = subprocess.run(["tnef", "-t", os.path.join(T, "w.dat")], capture_output=True, text=True)
    check(r.returncode == 0, "tnef reads it")

# ---- Outlook's voting message arriving: buttons, and the answer carries Outlook's response
outlook = mime.build(("Bob", "bob@corp.example"), [("Me", "me@example.org")], subject="Lunch?", text="Vote.")
del outlook["X-Folio-Voting"]
tag = b"PCDFEB09\0\x01\0\0\0" + b"\x11" * 20
data = tnef.build([(tnef.PT_BINARY, (tnef.PSETID_COMMON, tnef.LID_VERB_STREAM), tnef.verb_stream(["Yes", "No"])),
                   (tnef.PT_BINARY, tnef.TAG_REPORT_TAG, tag)])
outlook["X-MS-TNEF-Correlator"] = outlook["Message-ID"]
outlook.add_attachment(data, maintype="application", subtype="ms-tnef", filename="winmail.dat")
om = mime.parse(mime.to_bytes(outlook))
check(voting.choices_of(om) == ["Yes", "No"], "Outlook's voting buttons show in Post")
resp = voting.build_response({"name": "Me", "email": "me@example.org"}, om, "No")
rb = mime.parse(mime.to_bytes(resp))
check(mime.header(rb, "Subject") == "No: Lunch?", "the answer's subject, as Outlook writes it")
rt = mime.tnef_of(rb)
check(rt is not None and rt["props"].get((tnef.PSETID_COMMON, tnef.LID_VERB_RESPONSE)) == "No", "PidLidVerbResponse on the answer")
check(rt["props"].get(tnef.TAG_REPORT_TAG) == tag, "the answer carries the original's report tag (Outlook's tracking)")
# a vote on Post's own message stays plain (no winmail.dat to a Post user)
p_resp = voting.build_response({"name": "Ann", "email": "ann@example.org"}, back, "Approve")
check(mime.tnef_of(mime.parse(mime.to_bytes(p_resp))) is None, "answering Post's buttons adds no winmail.dat")

# ---- files Outlook packs inside winmail.dat are shown as attachments
pdf = b"%PDF-1.4 fake" * 50
lp = tnef.props_block([(tnef.PT_UNICODE, tnef.TAG_ATTACH_LONG_FILENAME, "Quarterly report.pdf")])
wd = tnef.build([]) + b"".join([
    tnef._attr(2, tnef.ATT_ATTACH_REND_DATA, b"\0" * 14),
    tnef._attr(2, tnef.ATT_ATTACH_TITLE, b"QUARTE~1.PDF\0"),
    tnef._attr(2, tnef.ATT_ATTACH_DATA, pdf),
    tnef._attr(2, tnef.ATT_ATTACHMENT, lp)])
x = mime.build(("Bob", "bob@corp.example"), ["me@example.org"], subject="Report", text="Attached.")
x.add_attachment(wd, maintype="application", subtype="ms-tnef", filename="winmail.dat")
xa = mime.attachments(mime.parse(mime.to_bytes(x)))
check(len(xa) == 1 and xa[0]["name"] == "Quarterly report.pdf" and xa[0]["data"] == pdf, "a file inside winmail.dat is an attachment, long name")
check(mime.summary(mime.to_bytes(x))["attach"], "paper clip for it")
if shutil.which("tnef"):
    d2 = os.path.join(T, "x")
    os.makedirs(d2)
    open(os.path.join(T, "x.dat"), "wb").write(wd)
    subprocess.run(["tnef", "-C", d2, "--use-paths", os.path.join(T, "x.dat")], capture_output=True)
    got = os.listdir(d2)
    check(len(got) == 1 and open(os.path.join(d2, got[0]), "rb").read() == pdf, "tnef extracts the same file from what we read")
check(tnef.parse(b"not tnef") is None and tnef.vote_choices(b"\x02\x01") == [], "junk is ignored")
shutil.rmtree(T)
print("%d checks, %d failed" % (N[0], len(FAILS)))
sys.exit(1 if FAILS else 0)
