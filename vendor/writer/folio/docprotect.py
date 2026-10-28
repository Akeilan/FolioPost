"""Backstage > Info extras: Mark as Final, the message bar, and version
history kept from AutoRecover snapshots."""
import hashlib
import os
import shutil
import time

from gi.repository import Gtk

from . import docapi


# ------------------------------------------------------------ message bar
class MessageBar(Gtk.Box):
    """The yellow bar under the ribbon (Marked as Final, autosaved versions)."""

    def __init__(self, win):
        Gtk.Box.__init__(self, spacing=10)
        self.win = win
        self.get_style_context().add_class("folio-msgbar")
        self.set_no_show_all(True)
        self.icon = Gtk.Image.new_from_icon_name("dialog-information-symbolic",
                                                 Gtk.IconSize.MENU)
        self.title = Gtk.Label(xalign=0)
        self.text = Gtk.Label(xalign=0)
        self.text.set_ellipsize(3)
        self.buttons = Gtk.Box(spacing=6)
        close = Gtk.Button()
        close.set_relief(Gtk.ReliefStyle.NONE)
        close.add(Gtk.Image.new_from_icon_name("window-close-symbolic", Gtk.IconSize.MENU))
        close.connect("clicked", lambda *_: self.hide_bar())
        for w in (self.icon, self.title, self.text):
            self.pack_start(w, False, False, 0)
        self.pack_start(self.buttons, False, False, 8)
        self.pack_end(close, False, False, 0)
        self.kind = None

    def show_bar(self, kind, title, text, buttons=()):
        self.kind = kind
        self.title.set_markup("<b>%s</b>" % title)
        self.text.set_text(text)
        for c in self.buttons.get_children():
            self.buttons.remove(c)
        for label, cb in buttons:
            b = Gtk.Button(label=label)
            b.connect("clicked", lambda _b, cb=cb: cb())
            self.buttons.pack_start(b, False, False, 0)
        for w in self.get_children() + self.buttons.get_children():
            w.show_all()
        self.show()

    def hide_bar(self, kind=None):
        if kind is None or kind == self.kind:
            self.hide()
            self.kind = None


# ------------------------------------------------------------ mark as final
def is_final(m):
    # Word's _MarkAsFinal custom property (older Folio files: MarkedFinal)
    v = docapi._doc_setting(m, "_MarkAsFinal", None)
    if v is not None:
        return v is True or str(v).lower() in ("true", "1")
    return docapi._doc_setting(m, "MarkedFinal", "") == "1"


def _set_final(m, on):
    try:
        ud = m.getDocumentProperties().getUserDefinedProperties()
        if ud.getPropertySetInfo().hasPropertyByName("MarkedFinal"):
            ud.removeProperty("MarkedFinal")
        if on:
            docapi._set_doc_setting(m, "_MarkAsFinal", True)
        elif ud.getPropertySetInfo().hasPropertyByName("_MarkAsFinal"):
            ud.removeProperty("_MarkAsFinal")
    except Exception:
        docapi._set_doc_setting(m, "MarkedFinal", "1" if on else "")
    try:
        p = m.getDocumentProperties()
        if on:
            p.ContentStatus = "Final"
        elif getattr(p, "ContentStatus", "") == "Final":
            p.ContentStatus = ""
    except Exception:
        pass


def mark_final(win, on=True):
    m = win.docmodel
    if m is None:
        return
    if on:
        if not win.dialogs.confirm("This document will be marked as final and then saved.",
                                   yes="OK", no="Cancel"):
            return
        _set_final(m, True)
        if win.save():
            win.dialogs.message(
                "This document has been marked as final to indicate that editing is "
                "complete and that this is the final version of the document.\n\n"
                "When a document is marked as final, the status property is set to "
                "“Final” and typing, editing commands, and proofing marks are "
                "turned off.", title="Marked as Final")
        apply_final(win)
    else:
        _set_final(m, False)
        apply_final(win)


def apply_final(win):
    m = win.docmodel
    if m is None:
        return
    if is_final(m):
        win.read_only = True
        win.engine.view.set_edit(False)
        win.msgbar.show_bar("final", "MARKED AS FINAL",
                            "An author has marked this document as final to discourage "
                            "editing.", [("Edit Anyway", lambda: edit_anyway(win))])
    else:
        if win.msgbar.kind == "final":
            win.read_only = False
            win.engine.view.set_edit(True)
            win.msgbar.hide_bar("final")
    win.update_title()


def edit_anyway(win):
    m = win.docmodel
    if m is not None:
        _set_final(m, False)
    win.read_only = False
    win.engine.view.set_edit(True)
    win.msgbar.hide_bar("final")
    win.update_title()


# ------------------------------------------------------------ versions
def versions_dir(app, path):
    key = hashlib.sha1(os.path.abspath(path).encode()).hexdigest()[:16]
    return os.path.join(app.autorecover_dir, "versions", key)


def keep_version(app, win, keep=12):
    """Store an AutoRecover snapshot of a saved document as a version."""
    path = win.engine.path
    if not path or win.engine.is_new:
        return
    d = versions_dir(app, path)
    os.makedirs(d, exist_ok=True)
    target = os.path.join(d, "%d.odt" % int(time.time()))
    if win.engine.save_as(target, "odt", keep=False):
        files = sorted(f for f in os.listdir(d) if f.endswith(".odt"))
        for f in files[:-keep]:
            try:
                os.remove(os.path.join(d, f))
            except OSError:
                pass


def versions(app, path):
    if not path:
        return []
    d = versions_dir(app, path)
    if not os.path.isdir(d):
        return []
    out = []
    for f in sorted(os.listdir(d), reverse=True):
        if f.endswith(".odt"):
            try:
                out.append((int(f[:-4]), os.path.join(d, f)))
            except ValueError:
                pass
    return out


def version_label(ts):
    import datetime
    t = datetime.datetime.fromtimestamp(ts)
    today = datetime.date.today()
    if t.date() == today:
        day = "Today"
    elif (today - t.date()).days == 1:
        day = "Yesterday"
    else:
        day = t.strftime("%A, %B %-d")
    return "%s, %s (autosave)" % (day, t.strftime("%-I:%M %p"))


def open_version(win, ts, vpath):
    """Open an autosaved version in its own window, with Restore / Compare."""
    original = win.engine.path
    w = win.app.new_window(template=vpath)
    w.untitled = "%s (%s)" % (win.doc_name(), version_label(ts).replace(" (autosave)", ""))

    def restore():
        if not win.dialogs.confirm("You are about to overwrite the last saved version with "
                                   "the selected version.", yes="OK", no="Cancel"):
            return
        fmt = os.path.splitext(original)[1].lstrip(".").lower() or "docx"
        if w.engine.save_as(original, fmt, keep=False):
            w.engine.mark_saved()
            w.close_document()
            for other in win.app.windows:
                if other.engine.path == original:
                    other.open_file(original)
        else:
            w.dialogs.message("The version couldn't be restored.")

    def compare():
        from .engine import file_url
        w.engine.command(".uno:CompareDocuments", {"URL": file_url(original),
                                                   "NoAcceptDialog": True})

    def ready():
        w.read_only = True
        w.engine.view.set_edit(False)
        w.update_title()
        w.msgbar.show_bar("version", "AUTOSAVED VERSION",
                          "This is a temporary file that was saved automatically.",
                          [("Compare", compare), ("Restore", restore)])
        return False
    from gi.repository import GLib
    GLib.timeout_add(900, ready)
    return w


def recover_unsaved(win):
    files = win.app.recovered_files()
    if not files:
        win.dialogs.message("There are no unsaved documents to recover.")
        return
    from .widgets import FDialog
    d = FDialog(win, "Recover Unsaved Documents", buttons=(("Open", Gtk.ResponseType.OK),
                                                           ("Cancel",
                                                            Gtk.ResponseType.CANCEL)))
    lb = Gtk.ListBox()
    for p, info in files:
        row = Gtk.ListBoxRow()
        row.path = p
        try:
            when = time.strftime("%-m/%-d/%Y %-I:%M %p", time.localtime(os.path.getmtime(p)))
        except OSError:
            when = ""
        lab = Gtk.Label(xalign=0)
        lab.set_markup("<b>%s</b>   <small>%s</small>" % (
            (info.get("name") or os.path.basename(p)).replace("&", "&amp;"), when))
        lab.set_margin_top(4)
        lab.set_margin_bottom(4)
        row.add(lab)
        lb.add(row)
    lb.select_row(lb.get_row_at_index(0))
    lb.connect("row-activated", lambda *_: d.response(Gtk.ResponseType.OK))
    d.add(lb)
    r = d.ask()
    row = lb.get_selected_row()
    d.done()
    if r == Gtk.ResponseType.OK and row is not None:
        w = win.app.new_window(template=row.path)
        try:
            dest = os.path.join(os.path.dirname(row.path), "recovered")
            os.makedirs(dest, exist_ok=True)
            shutil.move(row.path, os.path.join(dest, os.path.basename(row.path)))
            os.remove(row.path + ".info")
        except OSError:
            pass
        return w
