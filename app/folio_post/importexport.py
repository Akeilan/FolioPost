"""Import and Export: messages (.eml, .mbox), Outlook data files (.pst and .ost, through readpst from
pst-utils), Outlook messages (.msg, through msgconvert), calendars (.ics) and contacts (.vcf)."""
import mailbox
import os
import shutil
import subprocess
import tempfile

from gi.repository import Gtk

CHOICES = [("import-eml", "Import messages (.eml files) into the current folder"),
           ("import-mbox", "Import a mailbox file (.mbox)"),
           ("import-pst", "Import an Outlook data file (.pst or .ost)"),
           ("import-ics", "Import a calendar (.ics)"),
           ("import-vcf", "Import contacts (.vcf)"),
           ("export-mbox", "Export the current folder to a mailbox file (.mbox)"),
           ("export-ics", "Export the calendar (.ics)"),
           ("export-vcf", "Export contacts (.vcf)")]

PATTERNS = {"import-eml": ["*.eml"], "import-mbox": ["*.mbox", "*.mbx", "mbox", "*"], "import-pst": ["*.pst", "*.ost"],
            "import-ics": ["*.ics"], "import-vcf": ["*.vcf", "*.vcard"]}


def import_export(win, choice=None, path=None):
    if choice is None:
        d = Gtk.Dialog(title="Import and Export Wizard", transient_for=win, modal=True)
        d.get_style_context().add_class("folio-dialog")
        box = d.get_content_area()
        box.set_border_width(12)
        box.set_spacing(4)
        box.pack_start(Gtk.Label(label="Choose an action to perform:", xalign=0), False, False, 4)
        first = None
        radios = {}
        for k, label in CHOICES:
            r = Gtk.RadioButton.new_with_label_from_widget(first, label)
            first = first or r
            radios[k] = r
            box.pack_start(r, False, False, 0)
        d.add_button("Cancel", Gtk.ResponseType.CANCEL)
        d.add_button("Next", Gtk.ResponseType.OK)
        d.show_all()
        ok = d.run() == Gtk.ResponseType.OK
        choice = [k for k, r in radios.items() if r.get_active()][0]
        d.destroy()
        if not ok:
            return None
    if path is None:
        save = choice.startswith("export")
        dlg = Gtk.FileChooserDialog(title=dict(CHOICES)[choice], transient_for=win,
                                    action=Gtk.FileChooserAction.SAVE if save else Gtk.FileChooserAction.OPEN)
        dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Save" if save else "Open", Gtk.ResponseType.OK)
        if save:
            dlg.set_do_overwrite_confirmation(True)
            dlg.set_current_name({"export-mbox": "Mail.mbox", "export-ics": "Calendar.ics", "export-vcf": "Contacts.vcf"}[choice])
        else:
            if choice == "import-eml":
                dlg.set_select_multiple(True)
            f = Gtk.FileFilter()
            for pat in PATTERNS.get(choice, ["*"]):
                f.add_pattern(pat)
            f.set_name(", ".join(PATTERNS.get(choice, ["*"])))
            dlg.add_filter(f)
        ok = dlg.run() == Gtk.ResponseType.OK
        path = "|".join(dlg.get_filenames()) if ok and choice == "import-eml" else (dlg.get_filename() if ok else None)
        dlg.destroy()
        if not path:
            return None
    fn = globals()[choice.replace("-", "_")]
    try:
        n = fn(win, path)
    except Exception as e:
        win.dialogs.message("The %s didn't finish: %s" % ("export" if choice.startswith("export") else "import", e))
        return None
    win._do_refresh() if hasattr(win, "_do_refresh") else None
    return n


def _target_folder(win, name=None):
    """Imported mail goes to the current folder, or a folder on this computer."""
    f = win.current_folder()
    if f and f["role"] not in ("outbox",) and name is None:
        return f["id"]
    return local_folder(win.store, name or "Imported")


def local_account(store, name="On This Computer"):
    for a in store.accounts():
        if a["kind"] == "local" and a["name"] == name:
            return a["id"]
    return store.add_account(name, "", "local", {})


def local_folder(store, path, account=None, delim="/"):
    aid = account or local_account(store)
    return store.ensure_folder(aid, path, "", delim)


def _add(store, fid, raw, seen=True):
    f = store.folder(fid)
    acc = store.account(f["account"]) if f else None
    mid = store.add_message(fid, raw, 0, ["seen"] if seen else [])
    if acc and acc["kind"] == "imap":
        store.set_fields(mid, pending="new")
    return mid


def import_eml(win, path):
    fid = _target_folder(win)
    n = 0
    for p in path.split("|"):
        with open(p, "rb") as fh:
            _add(win.store, fid, fh.read())
        n += 1
    win.store.changed("messages")
    if hasattr(win, "push_soon"):
        win.push_soon()
    return n


def import_mbox(win, path, fid=None):
    if fid is None:
        fid = local_folder(win.store, os.path.splitext(os.path.basename(path))[0] or "Imported")
    n = 0
    box = mailbox.mbox(path, create=False)
    try:
        for msg in box:
            raw = msg.as_bytes()
            seen = "R" in (msg.get_flags() or "") or "O" in (msg.get_flags() or "")
            _add(win.store, fid, raw, seen)
            n += 1
    finally:
        box.close()
    win.store.changed("messages")
    win.refresh_folders()
    return n


def export_mbox(win, path):
    rows = win.list_rows() if win.folder_id and win.folder_id < 0 else (win.store.messages(win.folder_id) if win.folder_id else [])
    if os.path.exists(path):
        os.remove(path)
    box = mailbox.mbox(path)
    try:
        for r in reversed(rows):
            m = mailbox.mboxMessage(win.store.raw(r["id"]))
            if r["seen"]:
                m.set_flags("RO")
            box.add(m)
        box.flush()
    finally:
        box.close()
    return len(rows)


def import_pst(win, path):
    """Mail, contacts and calendar from an Outlook data file, read by readpst (pst-utils)."""
    readpst = shutil.which("readpst")
    if readpst is None:
        raise RuntimeError("reading .pst files needs readpst. Install it with:  sudo apt install pst-utils")
    out = tempfile.mkdtemp(prefix="folio-pst-")
    subprocess.run([readpst, "-r", "-cv", "-q", "-o", out, path], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    store = win.store
    name = "Outlook Data File (%s)" % os.path.splitext(os.path.basename(path))[0]
    aid = local_account(store, name)
    n = 0
    for root, dirs, files in os.walk(out):
        rel = os.path.relpath(root, out)
        parts = [p for p in rel.split(os.sep) if p and p != "."]
        if len(parts) > 1:
            parts = parts[1:]                      # readpst's top folder is the data file's own name
        folder = "/".join(parts) or "Inbox"
        for f in files:
            fp = os.path.join(root, f)
            if f == "mbox" or f.endswith(".mbox"):
                role = {"inbox": "inbox", "sent items": "sent", "deleted items": "trash", "drafts": "drafts",
                        "junk e-mail": "junk", "junk email": "junk"}.get(folder.split("/")[-1].lower(), "")
                fid = store.ensure_folder(aid, folder, role, "/")
                n += import_mbox(win, fp, fid)
            elif f.startswith("contacts"):
                if hasattr(win, "import_vcards"):
                    n += win.import_vcards(open(fp, encoding="utf-8", errors="replace").read())
            elif f.startswith("calendar"):
                if hasattr(win, "import_ics"):
                    n += win.import_ics(open(fp, encoding="utf-8", errors="replace").read())
    shutil.rmtree(out, ignore_errors=True)
    win.refresh_folders()
    return n


def msg_to_eml(path):
    """An Outlook .msg as an RFC 822 message (read here; msgconvert for what this doesn't read)."""
    from . import msgfile
    try:
        with open(path, "rb") as fh:
            return msgfile.to_eml(fh.read())
    except Exception:
        pass
    conv = shutil.which("msgconvert")
    if conv is None:
        raise RuntimeError("opening .msg files needs msgconvert. Install it with:  sudo apt install libemail-outlook-message-perl")
    out = tempfile.mkdtemp(prefix="folio-msg-")
    target = os.path.join(out, "message.eml")
    subprocess.run([conv, "--outfile", target, path], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with open(target, "rb") as fh:
        return fh.read()


def import_ics(win, path):
    return win.import_ics(open(path, encoding="utf-8", errors="replace").read())


def import_vcf(win, path):
    return win.import_vcards(open(path, encoding="utf-8", errors="replace").read())


def export_ics(win, path):
    from . import ical
    evs = []
    for row in win.store.events():
        evs += ical.events_of(ical.parse(row["ics"]))
    with open(path, "w") as fh:
        fh.write(ical.dumps(ical.calendar_of(evs)))
    return len(evs)


def export_vcf(win, path):
    from . import vcard
    n = 0
    with open(path, "w") as fh:
        for r in win.store.contacts():
            c = vcard.parse(r["vcard"])
            if c:
                fh.write(c.dumps())
                n += 1
    return n
