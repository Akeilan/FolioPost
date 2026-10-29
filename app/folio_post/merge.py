"""Mail merge from Folio Writer (M3-08), the contract between the two apps:

  folio-post --send-merge FILE.json [--json]
      FILE = {"subject", "from"?, "format": "html"|"text"|"attachment",
              "messages": [{"to", "cc"?, "bcc"?, "subject"?, "html"?, "text"?, "attachments"?}]}
      One confirm window (account, count, Send/Cancel); each message is sent and filed in Sent
      Items, with progress shown; exit 0 when all were sent. With --json:
      {"sent": n, "failed": [{"to", "error"}]}.

  folio-post --list-contacts [--json]
      [{"name", "email", "company", "phone", "groups": [..]}] for every account's contacts and
      groups, printed with no window.
"""
import json
import mimetypes
import os
import sys

from . import mime, vcard


def list_contacts(store):
    people = []
    groups = []
    for r in store.contacts():
        k = vcard.parse(r["vcard"])
        if k is None:
            continue
        if k.is_group:
            groups.append(k)
            continue
        people.append(k)
    out = []
    for k in people:
        emails = [e for _t, e in k.emails if e]
        phones = k.phones
        phone = next((n for t, n in phones if t == "cell"), phones[0][1] if phones else "")
        mine = set(e.lower() for e in emails)
        gs = sorted(set(g.name for g in groups if mine & set(e.lower() for e in g.member_emails()) or k.uid in g.member_uids()))
        if not emails:
            out.append({"name": k.name, "email": "", "company": k.company, "phone": phone, "groups": gs})
        for e in emails[:1]:
            out.append({"name": k.name, "email": e, "company": k.company, "phone": phone, "groups": gs})
    for g in groups:
        out.append({"name": g.name, "email": "", "company": "", "phone": "", "groups": [], "members": g.member_emails(),
                    "is_group": True})
    return sorted(out, key=lambda x: (x.get("is_group", False), x["name"].lower()))


def _addrs(v):
    if not v:
        return []
    if isinstance(v, list):
        out = []
        for x in v:
            out += _addrs(x)
        return out
    from .compose import parse_recipients
    return [(n, a) if a else ("", n) for n, a in parse_recipients(v)]


def load(path):
    with open(path, encoding="utf-8") as fh:
        job = json.load(fh)
    if not isinstance(job.get("messages"), list):
        raise ValueError("the merge file has no messages")
    return job


def pick_account(store, job):
    accs = [a for a in store.accounts() if a["kind"] not in ("local", "rss")]
    want = (job.get("from") or "").lower()
    for a in accs:
        if want and (a["email"].lower() == want or want in a["email"].lower()):
            return a, accs
    return (accs[0] if accs else None), accs


def build(acc, job, m):
    """The MIME message for one merged letter."""
    fmt = job.get("format", "html")
    subject = m.get("subject") or job.get("subject", "")
    text = m.get("text") or (mime.html_to_text(m["html"]) if m.get("html") else "")
    html = m.get("html") if fmt == "html" else None
    if html and "<html" not in html.lower():
        html = "<html><head><meta charset='utf-8'></head><body>%s</body></html>" % html
    atts = []
    for p in m.get("attachments") or []:
        if isinstance(p, dict):
            data = open(p["path"], "rb").read()
            atts.append((p.get("name") or os.path.basename(p["path"]), p.get("type") or
                         mimetypes.guess_type(p["path"])[0] or "application/octet-stream", data))
        else:
            atts.append((os.path.basename(p), mimetypes.guess_type(p)[0] or "application/octet-stream", open(p, "rb").read()))
    sender = (acc["name"], acc["email"]) if acc["name"] != acc["email"] else ("", acc["email"])
    return mime.build(sender, _addrs(m.get("to")), _addrs(m.get("cc")), _addrs(m.get("bcc")), subject, text, html, atts, ())


def send_one(syncer, acc, raw, rcpts):
    """Send one message now (not through the Outbox), then file it in Sent Items."""
    from . import imap as net
    if acc["kind"] == "ews":
        c = syncer.ews_client(acc)
        try:
            c.send_mime(raw, save=True)
        finally:
            c.close()
    else:
        pw, tok = syncer.credentials(acc)
        net.send(acc["config"], mime.without_bcc(raw), acc["email"], rcpts, pw, tok)
        syncer.after_sent(acc, raw)


def run(app_store, syncer, job, acc, progress=None):
    """Send every message: {"sent": n, "failed": [{"to", "error"}]}."""
    sent, failed = 0, []
    msgs = job["messages"]
    for k, m in enumerate(msgs):
        to = m.get("to") if isinstance(m.get("to"), str) else ", ".join(m.get("to") or [])
        try:
            msg = build(acc, job, m)
            rcpts = mime.recipients(msg)
            if not rcpts:
                raise ValueError("no recipient")
            send_one(syncer, acc, mime.to_bytes(msg), rcpts)
            sent += 1
        except Exception as e:
            failed.append({"to": to, "error": str(e)})
        if progress:
            progress(k + 1, len(msgs))
    if sent and acc["kind"] != "ews":
        # the copies made in Sent Items go up to the server
        s = app_store.folder_by_role(acc["id"], "sent")
        if s is not None:
            try:
                syncer.sync_account(acc["id"], [s["id"]])
            except Exception:
                pass
    return {"sent": sent, "failed": failed}


def main_send(path, as_json):
    """folio-post --send-merge FILE.json [--json]"""
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk
    from .app import CONFIG, DATA
    from .store import Store
    from .sync import Secrets, Syncer
    from .oauth import TokenSource
    store = Store(DATA)
    secrets = Secrets(os.path.join(CONFIG, "secrets.json"))
    syncer = Syncer(store, secrets, TokenSource(store, secrets))
    try:
        job = load(path)
    except Exception as e:
        res = {"sent": 0, "failed": [{"to": "", "error": "the merge file can't be read: %s" % e}]}
        print(json.dumps(res) if as_json else res["failed"][0]["error"])
        return 2
    acc, accs = pick_account(store, job)
    n = len(job["messages"])
    if acc is None:
        res = {"sent": 0, "failed": [{"to": m.get("to", ""), "error": "no account that sends mail"} for m in job["messages"]]}
        print(json.dumps(res) if as_json else "Folio Post has no account that sends mail. Add one in Folio Post first.")
        return 1
    win = Gtk.Window(title="Mail Merge - Folio Post")
    win.set_default_size(460, -1)
    win.set_icon_name("folio-post")
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin=16)
    win.add(box)
    head = Gtk.Label(xalign=0)
    head.set_markup("<big><b>Send %d message%s</b></big>" % (n, "" if n == 1 else "s"))
    box.pack_start(head, False, False, 0)
    row = Gtk.Box(spacing=8)
    row.pack_start(Gtk.Label(label="Send from"), False, False, 0)
    combo = Gtk.ComboBoxText()
    for a in accs:
        combo.append(str(a["id"]), a["email"])
    combo.set_active_id(str(acc["id"]))
    row.pack_start(combo, True, True, 0)
    box.pack_start(row, False, False, 0)
    first = job["messages"][0] if job["messages"] else {}
    info = Gtk.Label(xalign=0)
    info.set_line_wrap(True)
    info.set_text("Subject: %s\nFirst message to: %s" % (first.get("subject") or job.get("subject", ""), first.get("to", "")))
    box.pack_start(info, False, False, 0)
    bar = Gtk.ProgressBar()
    bar.set_show_text(True)
    bar.set_no_show_all(True)
    box.pack_start(bar, False, False, 0)
    btns = Gtk.Box(spacing=8)
    cancel = Gtk.Button(label="Cancel")
    send = Gtk.Button(label="Send")
    send.get_style_context().add_class("suggested-action")
    btns.pack_end(send, False, False, 0)
    btns.pack_end(cancel, False, False, 0)
    box.pack_start(btns, False, False, 0)
    state = {"res": None}

    def pump():
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)

    def progress(k, total):
        bar.set_fraction(k / max(1, total))
        bar.set_text("Sent %d of %d" % (k, total))
        pump()

    def go(*_):
        a = store.account(int(combo.get_active_id()))
        send.set_sensitive(False)
        cancel.set_sensitive(False)
        combo.set_sensitive(False)
        bar.show()
        pump()
        state["res"] = run(store, syncer, job, a, progress)
        Gtk.main_quit()

    def stop(*_):
        state["res"] = {"sent": 0, "failed": [{"to": m.get("to", ""), "error": "cancelled"} for m in job["messages"]]}
        Gtk.main_quit()
        return True
    send.connect("clicked", go)
    cancel.connect("clicked", stop)
    win.connect("delete-event", stop)
    win.show_all()
    win.present()
    if os.environ.get("FOLIO_POST_MERGE_AUTOSEND"):
        from gi.repository import GLib
        GLib.timeout_add(300, lambda: (go(), False)[1])
    Gtk.main()
    res = state["res"] or {"sent": 0, "failed": []}
    if as_json:
        print(json.dumps(res))
    else:
        print("Sent %d of %d." % (res["sent"], n))
        for f in res["failed"]:
            print("Not sent to %s: %s" % (f["to"], f["error"]))
    sys.stdout.flush()
    return 0 if res["sent"] == n and not res["failed"] else 1


def main_list(as_json=True):
    from .app import DATA
    from .store import Store
    store = Store(DATA)
    out = list_contacts(store)
    print(json.dumps(out, ensure_ascii=False, indent=None if as_json else 1))
    return 0
