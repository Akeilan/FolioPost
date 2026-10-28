"""Document Inspector (File > Info > Check for Issues > Inspect Document):
find and remove comments, revisions, personal information, headers and
footers, hidden text and invisible objects."""
from gi.repository import Gtk

from . import docapi
from .widgets import FDialog

CATEGORIES = [
    ("comments", "Comments, Revisions, and Versions",
     "Inspects the document for comments, versions, and revision marks."),
    ("props", "Document Properties and Personal Information",
     "Inspects for hidden metadata or personal information saved with the document."),
    ("hf", "Headers, Footers, and Watermarks",
     "Inspects the document for information in headers, footers, and watermarks."),
    ("hidden", "Hidden Text", "Inspects the document for text that has been formatted as "
     "hidden."),
    ("invisible", "Invisible Content", "Inspects the document for objects that are not "
     "visible because they have been formatted as invisible."),
]


def _redline_count(win):
    import json
    try:
        raw = win.engine.view.get_command_values(".uno:AcceptTrackedChanges")
        return len(json.loads(raw or "{}").get("redlines", []))
    except Exception:
        return 0


def _hidden_ranges(m):
    out = []
    en = m.getText().createEnumeration()
    while en.hasMoreElements():
        p = en.nextElement()
        if not p.supportsService("com.sun.star.text.Paragraph"):
            continue
        pe = p.createEnumeration()
        while pe.hasMoreElements():
            r = pe.nextElement()
            try:
                if r.CharHidden and r.getString():
                    out.append(r)
            except Exception:
                pass
    return out


def _invisible(m):
    out = []
    dp = m.getDrawPage()
    for i in range(dp.getCount()):
        o = dp.getByIndex(i)
        try:
            if not o.Visible:
                out.append(o)
        except Exception:
            pass
    return out


def _page_styles_with_hf(m):
    out = []
    fam = m.getStyleFamilies().getByName("PageStyles")
    for n in fam.getElementNames():
        ps = fam.getByName(n)
        try:
            if ps.isInUse() and (ps.HeaderIsOn or ps.FooterIsOn):
                out.append(ps)
        except Exception:
            pass
    return out


def inspect(win, key):
    """(found, message)"""
    m = win.engine.model
    if key == "comments":
        nc = len(docapi.comments(m))
        nr = _redline_count(win)
        bits = []
        if nc:
            bits.append("Comments")
        if nr:
            bits.append("Revision marks")
        return bool(bits), ("The following items were found:\n• " + "\n• ".join(bits)
                            if bits else "No comments or revisions were found.")
    if key == "props":
        dp = m.getDocumentProperties()
        bits = []
        if (dp.Author or "").strip() or (dp.ModifiedBy or "").strip():
            bits.append("Author")
        if (dp.Title or dp.Subject or "").strip() or dp.Keywords:
            bits.append("Document properties")
        return bool(bits), ("The following document information was found:\n• " +
                            "\n• ".join(bits) if bits else
                            "No document properties or personal information was found.")
    if key == "hf":
        n = len(_page_styles_with_hf(m))
        return bool(n), ("The following items were found:\n• Headers\n• Footers" if n else
                         "No custom header, footer, or watermark information was found.")
    if key == "hidden":
        n = len(_hidden_ranges(m))
        return bool(n), ("Hidden text was found." if n else "No hidden text was found.")
    if key == "invisible":
        n = len(_invisible(m))
        return bool(n), ("Invisible objects found: %d" % n if n else
                         "No invisible objects found.")
    return False, ""


def remove(win, key):
    m = win.engine.model
    um = m.getUndoManager()
    um.enterUndoContext("Remove " + key)
    try:
        if key == "comments":
            docapi.delete_comments(m)
            win.engine.command(".uno:AcceptAllTrackedChanges")
        elif key == "props":
            dp = m.getDocumentProperties()
            for p in ("Author", "ModifiedBy", "Title", "Subject", "Description",
                      "PrintedBy"):
                try:
                    setattr(dp, p, "")
                except Exception:
                    pass
            dp.Keywords = ()
            try:
                settings = m.createInstance("com.sun.star.text.DocumentSettings")
                settings.RemovePersonalInformation = True
            except Exception:
                pass
        elif key == "hf":
            for ps in _page_styles_with_hf(m):
                ps.HeaderIsOn = False
                ps.FooterIsOn = False
        elif key == "hidden":
            for r in reversed(_hidden_ranges(m)):
                r.setString("")
        elif key == "invisible":
            for o in _invisible(m):
                try:
                    m.getDrawPage().remove(o)
                except Exception:
                    pass
    finally:
        um.leaveUndoContext()


def dialog(win):
    m = win.engine.model
    if m is None:
        return
    if win.engine.modified and win.dialogs.confirm(
            "This document has changes that haven't been saved. Do you want to save the "
            "file now?", yes="Yes", no="No"):
        win.save()
    d = FDialog(win, "Document Inspector", buttons=(("Inspect", 10),
                                                    ("Close", Gtk.ResponseType.CANCEL)))
    d.set_default_size(560, -1)
    intro = Gtk.Label(label="To check the document for the selected content, click "
                            "Inspect.", xalign=0)
    d.add(intro)
    stack = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    sw = Gtk.ScrolledWindow()
    sw.set_size_request(540, 340)
    sw.add(stack)
    d.add(sw, expand=True)
    checks = {}

    def show_checks():
        for c in stack.get_children():
            stack.remove(c)
        for key, title, desc in CATEGORIES:
            cb = Gtk.CheckButton()
            lab = Gtk.Label(xalign=0)
            lab.set_markup("<b>%s</b>\n<small>%s</small>" % (title, desc))
            lab.set_line_wrap(True)
            cb.add(lab)
            cb.set_active(checks.get(key, True) if not isinstance(checks.get(key), Gtk.Widget)
                          else checks[key].get_active())
            checks[key] = cb
            stack.pack_start(cb, False, False, 0)
        stack.show_all()

    def show_results():
        sel = [k for k, cb in checks.items() if cb.get_active()]
        for c in stack.get_children():
            stack.remove(c)
        intro.set_text("Review the inspection results.")
        for key, title, _desc in CATEGORIES:
            if key not in sel:
                continue
            found, msg = inspect(win, key)
            row = Gtk.Box(spacing=10)
            icon = Gtk.Image.new_from_icon_name("dialog-warning-symbolic" if found else
                                                "emblem-ok-symbolic", Gtk.IconSize.LARGE_TOOLBAR)
            row.pack_start(icon, False, False, 0)
            lab = Gtk.Label(xalign=0)
            lab.set_markup("<b>%s</b>\n<small>%s</small>" % (
                title, msg.replace("&", "&amp;")))
            lab.set_line_wrap(True)
            lab.set_max_width_chars(48)
            row.pack_start(lab, True, True, 0)
            if found:
                b = Gtk.Button(label="Remove All")

                def go(_b, key=key, icon=icon, lab=lab, title=title):
                    remove(win, key)
                    _b.hide()
                    icon.set_from_icon_name("emblem-ok-symbolic", Gtk.IconSize.LARGE_TOOLBAR)
                    lab.set_markup("<b>%s</b>\n<small>Removed.</small>" % title)
                b.connect("clicked", go)
                b.set_valign(Gtk.Align.CENTER)
                row.pack_start(b, False, False, 0)
            stack.pack_start(row, False, False, 0)
            stack.pack_start(Gtk.Separator(), False, False, 0)
        stack.show_all()
        d.buttons[10].set_label("Reinspect")
    show_checks()
    while True:
        r = d.ask()
        if r == 10:
            if d.buttons[10].get_label() == "Reinspect":
                d.buttons[10].set_label("Inspect")
                intro.set_text("To check the document for the selected content, click "
                               "Inspect.")
                show_checks()
            else:
                show_results()
            continue
        break
    d.done()
