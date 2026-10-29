"""Voting buttons (M3-05): Options > Use Voting Buttons puts the choices on the message; the
people it goes to answer with one click (a reply whose subject starts with the choice, as
Outlook's answers do); the sender's Sent Items copy shows the tally under Tracking.

The choices travel in an X-Folio-Voting header, and the message also carries a line with a
link for each choice, so people whose mail app has no voting buttons can answer too."""
import re
import urllib.parse
from html import escape

PRESETS = [("Approve;Reject", "Approve;Reject"), ("Yes;No", "Yes;No"), ("Yes;No;Maybe", "Yes;No;Maybe")]
HEADER = "X-Folio-Voting"
VOTE_HEADER = "X-Folio-Vote"


def parse_choices(text):
    return [c.strip() for c in re.split(r"[;\n]", text or "") if c.strip()][:10]


def footer(choices, sender, subject):
    """(text, html) added to the message: the choices as reply links."""
    links = []
    for c in choices:
        q = urllib.parse.urlencode({"subject": "%s: %s" % (c, subject)}, quote_via=urllib.parse.quote)
        links.append((c, "mailto:%s?%s" % (sender, q)))
    text = "\n\nVote: %s\n(Reply with your choice at the start of the subject, or use the voting buttons.)\n" % \
        " | ".join(c for c, _u in links)
    html = ("<p style='margin-top:16px;padding:8px;border:1px solid #c8c6c4;font-family:sans-serif'>Vote: %s</p>"
            % " &nbsp;|&nbsp; ".join("<a href='%s'>%s</a>" % (escape(u, True), escape(c)) for c, u in links))
    return text, html


def choices_of(msg):
    from . import mime
    return parse_choices(mime.header(msg, HEADER))


def vote_of(subject, choices):
    """The choice a reply's subject starts with ("Approve: Budget"), or None."""
    for c in sorted(choices, key=len, reverse=True):
        if re.match(r"^\s*%s\s*:" % re.escape(c), subject or "", re.I):
            return c
    return None


def build_response(acc, original, choice):
    """The reply that casts a vote."""
    from . import mime
    to = mime.addresses(original, "Reply-To") or mime.addresses(original, "From")
    subj = re.sub(r"^\s*(re|fw|fwd)\s*:\s*", "", mime.header(original, "Subject") or "", flags=re.I)
    mid = mime.header(original, "Message-ID").strip() or None
    m = mime.build((acc["name"], acc["email"]), to[:1], (), (), "%s: %s" % (choice, subj), "", None, (), (),
                   in_reply_to=mid, references=((mime.header(original, "References") + " " + (mid or "")).strip() or None),
                   extra={VOTE_HEADER: choice})
    return m


def tally(store, sent_row, choices):
    """{choice: [voter]} and [(voter, choice, date)] for a sent message with voting buttons."""
    mid = sent_row["msgid"]
    out = {c: [] for c in choices}
    rows = []
    seen = {}
    if not mid:
        return out, rows
    for r in store.q("select * from messages where in_reply_to=? and deleted=0 order by date", (mid,)):
        c = vote_of(r["subject"], choices)
        if c is None:
            continue
        who = r["from_name"] or r["from_addr"]
        seen[r["from_addr"].lower()] = (who, c, r["date"])       # the last answer counts
    for who, c, when in seen.values():
        out[c].append(who)
        rows.append((who, c, when))
    return out, sorted(rows, key=lambda x: x[2])


def send_vote(win, row, msg, choice):
    """Vote from the Reading Pane: the answer goes out at once."""
    from . import mime
    store = win.store
    f = store.folder(row["folder"]) if row else None
    acc = store.account(f["account"]) if f else win.current_account()
    if acc is None or acc["kind"] == "local":
        accs = [a for a in store.accounts() if a["kind"] != "local"]
        acc = accs[0] if accs else None
    if acc is None:
        win.dialogs.info("Add an account to vote.", "Vote")
        return None
    m = build_response(acc, msg, choice)
    store.queue(acc["id"], mime.to_bytes(m), mime.recipients(m))
    if row:
        store.set_flag([row["id"]], "answered", True)
        store.put("voted:%s" % (row["msgid"] or row["id"]), choice)
    if not win.app.syncer.offline:
        win.app.send_receive([acc["id"]])
    return m
