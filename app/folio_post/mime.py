"""Reading and writing messages (RFC 5322 / MIME): headers, the text and HTML bodies, attachments
and inline pictures; building the messages Post sends."""
import email
import email.policy
import html
import mimetypes
import os
import re
import time
from email.message import EmailMessage
from email.utils import formataddr, format_datetime, getaddresses, make_msgid, parseaddr, parsedate_to_datetime

POLICY = email.policy.default.clone(raise_on_defect=False)


def parse(raw):
    if isinstance(raw, str):
        raw = raw.encode("utf-8", "replace")
    try:
        return email.message_from_bytes(raw, policy=POLICY)
    except Exception:
        return email.message_from_bytes(b"Subject: (unreadable message)\r\n\r\n", policy=POLICY)


def header(msg, name):
    try:
        v = msg.get(name)
        return str(v) if v is not None else ""
    except Exception:
        try:
            return str(msg.get_all(name, [""])[0])
        except Exception:
            return ""


def addresses(msg, name):
    """[(display name, address)] of an address header."""
    vals = []
    try:
        vals = msg.get_all(name, [])
    except Exception:
        pass
    out = []
    for n, a in getaddresses([str(v) for v in vals]):
        if a or n:
            out.append((n, a))
    return out


def show_addresses(pairs):
    return "; ".join(n if n else a for n, a in pairs)


def date_of(msg):
    d = header(msg, "Date")
    try:
        return parsedate_to_datetime(d).timestamp()
    except Exception:
        return 0


def body_part(msg, kind):
    """The text/plain or text/html part (the first not an attachment)."""
    try:
        p = msg.get_body(preferencelist=(kind,))
    except Exception:
        p = None
    if p is None:
        return None
    try:
        return p.get_content()
    except Exception:
        try:
            return p.get_payload(decode=True).decode("utf-8", "replace")
        except Exception:
            return None


def text_of(msg):
    t = body_part(msg, "plain")
    if t is not None:
        return t
    h = body_part(msg, "html")
    if h is not None:
        return html_to_text(h)
    return ""


def html_to_text(h):
    h = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", " ", h)
    h = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</h\d>|</li>", "\n", h)
    h = re.sub(r"(?s)<[^>]+>", "", h)
    h = html.unescape(h)
    h = re.sub(r"[ \t\r\f\v]+", " ", h)
    return re.sub(r"\n\s*\n+", "\n\n", h).strip()


def attachments(msg):
    """[(file name, content type, size, part, content id, inline)] — inline pictures too."""
    out = []
    for p in msg.walk():
        if p.is_multipart():
            continue
        disp = (p.get_content_disposition() or "").lower()
        ctype = p.get_content_type()
        cid = (header(p, "Content-ID") or "").strip("<> ")
        name = p.get_filename()
        if disp == "attachment" or (name and ctype not in ("text/plain", "text/html")) or \
                (cid and ctype.startswith("image/")):
            try:
                data = p.get_payload(decode=True) or b""
            except Exception:
                data = b""
            if not name:
                ext = mimetypes.guess_extension(ctype) or ".bin"
                name = "attachment" + ext
            out.append({"name": name, "type": ctype, "size": len(data), "data": data, "cid": cid,
                        "inline": disp != "attachment" and bool(cid)})
    return out


def thread_key(msg):
    refs = header(msg, "References").split()
    if refs:
        return refs[0].strip()
    irt = header(msg, "In-Reply-To").strip().split()
    if irt:
        return irt[0]
    return header(msg, "Message-ID").strip()


def summary(raw):
    """What the message list needs."""
    msg = parse(raw)
    frm = addresses(msg, "From")
    fn, fa = frm[0] if frm else ("", "")
    text = text_of(msg) or ""
    att = [a for a in attachments(msg) if not a["inline"]]
    prio = (header(msg, "X-Priority") or "3")[:1]
    imp = header(msg, "Importance").lower()
    importance = 2 if prio in "12" or imp == "high" else 0 if prio in "45" or imp == "low" else 1
    return {"subject": header(msg, "Subject"), "from_name": fn or fa, "from_addr": fa,
            "to": show_addresses(addresses(msg, "To")), "cc": show_addresses(addresses(msg, "Cc")),
            "date": date_of(msg), "msgid": header(msg, "Message-ID").strip(),
            "in_reply_to": header(msg, "In-Reply-To").strip(), "refs": header(msg, "References").strip(),
            "thread": thread_key(msg), "attach": bool(att), "snippet": re.sub(r"\s+", " ", text)[:200],
            "text": text, "importance": importance}


# ---------------------------------------------------------------- writing
def build(sender, to, cc=(), bcc=(), subject="", text="", html_body=None, attachments=(), inline=(),
          in_reply_to=None, references=None, importance=1, msgid=None, date=None, request_receipt=False, extra=None):
    """A message to send: addresses are (name, address) or strings; attachments (name, type, bytes);
    inline pictures (content id, type, bytes) for the HTML."""
    m = EmailMessage(policy=POLICY)

    def addr(a):
        if isinstance(a, (tuple, list)):
            return formataddr((a[0], a[1]))
        return a
    m["From"] = addr(sender)
    if to:
        m["To"] = ", ".join(addr(a) for a in to)
    if cc:
        m["Cc"] = ", ".join(addr(a) for a in cc)
    if bcc:
        m["Bcc"] = ", ".join(addr(a) for a in bcc)
    m["Subject"] = subject
    m["Date"] = format_datetime(date or email.utils.localtime())
    dom = (parseaddr(addr(sender))[1].split("@")[-1] or "localhost") if sender else "localhost"
    m["Message-ID"] = msgid or make_msgid(domain=dom)
    if in_reply_to:
        m["In-Reply-To"] = in_reply_to
    if references:
        m["References"] = references
    if importance == 2:
        m["Importance"] = "High"
        m["X-Priority"] = "1"
    elif importance == 0:
        m["Importance"] = "Low"
        m["X-Priority"] = "5"
    if request_receipt:
        m["Disposition-Notification-To"] = addr(sender)
    for k, v in (extra or {}).items():
        m[k] = v
    m.set_content(text or "")
    if html_body is not None:
        m.add_alternative(html_body, subtype="html")
        if inline:
            h = m.get_payload()[-1]
            for cid, ctype, data in inline:
                maintype, subtype = ctype.split("/", 1)
                h.add_related(data, maintype=maintype, subtype=subtype, cid="<%s>" % cid)
    for name, ctype, data in attachments:
        ctype = ctype or mimetypes.guess_type(name)[0] or "application/octet-stream"
        maintype, subtype = ctype.split("/", 1)
        m.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    return m


def to_bytes(m):
    return m.as_bytes(policy=POLICY.clone(linesep="\r\n"))


def without_bcc(raw):
    m = parse(raw)
    del m["Bcc"]
    return to_bytes(m)


def recipients(m):
    out = []
    for h in ("To", "Cc", "Bcc"):
        out += [a for _n, a in addresses(m, h) if a]
    return out


def quote_header(msg):
    """The 'From / Sent / To / Subject' block a reply or forward quotes, as Outlook writes it."""
    when = date_of(msg)
    sent = time.strftime("%A, %B %d, %Y %I:%M %p", time.localtime(when)) if when else header(msg, "Date")
    lines = [("From", show_addresses(addresses(msg, "From"))), ("Sent", sent),
             ("To", show_addresses(addresses(msg, "To")))]
    cc = show_addresses(addresses(msg, "Cc"))
    if cc:
        lines.append(("Cc", cc))
    lines.append(("Subject", header(msg, "Subject")))
    return lines


def file_attachment(path):
    with open(path, "rb") as fh:
        data = fh.read()
    return (os.path.basename(path), mimetypes.guess_type(path)[0] or "application/octet-stream", data)
