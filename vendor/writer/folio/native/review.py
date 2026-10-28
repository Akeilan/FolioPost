"""Review for the new engine: Track Changes, accepting and rejecting
changes, the markup display, and comments, answered with the engine
commands and the LOK-style reports (.uno:ViewAnnotations, redlines) the
window's comment margin and Reviewing Pane read."""
import json

from gi.repository import GLib

COMMANDS = {
    ".uno:TrackChanges", ".uno:ShowTrackedChanges",
    ".uno:AcceptTrackedChange", ".uno:RejectTrackedChange",
    ".uno:AcceptTrackedChangeToNext", ".uno:RejectTrackedChangeToNext",
    ".uno:AcceptAllTrackedChanges", ".uno:RejectAllTrackedChanges",
    ".uno:NextTrackedChange", ".uno:PreviousTrackedChange",
    ".uno:InsertAnnotation", ".uno:ReplyComment", ".uno:ResolveComment",
    ".uno:EditAnnotation", ".uno:DeleteComment", ".uno:DeleteAllNotes",
    ".uno:DeleteAuthor", ".uno:NextAnnotation", ".uno:PreviousAnnotation",
    ".uno:ShowChangesInMargin",
}

MARKUP = {"All Markup": "all", "Simple Markup": "simple", "No Markup": "final",
          "Original": "original"}


def _arg(args, key, default=None):
    if not args:
        return default
    v = args.get(key, default)
    if isinstance(v, dict):
        v = v.get("value", default)
    if isinstance(v, tuple):
        v = v[1]
    return v


def _lok_id(cid):
    """Comment ids as reported: "0" means "no parent" there, so a prefix."""
    return "c" + str(cid)


def _own_id(v):
    v = str(v if v is not None else "")
    return v[1:] if v.startswith("c") else v


def _message(eng, text):
    win = getattr(eng, "win", None)
    if win is not None and hasattr(win, "dialogs"):
        GLib.idle_add(lambda: (win.dialogs.message(text), False)[1])


def refresh_comments(eng):
    win = getattr(eng, "win", None)
    margin = getattr(win, "comments", None) if win is not None else None
    if margin is not None:
        margin.reload()


def command(eng, cmd, args=None):
    ed = eng.ed
    if ed is None:
        return False
    view = eng.view
    changed = True
    if cmd == ".uno:TrackChanges":
        win = getattr(eng, "win", None)
        if ed.track_changes() and getattr(win, "track_locked", False):
            _message(eng, "Track Changes is locked: this document only allows tracked "
                          "changes. (Review > Track Changes > Lock Tracking)")
            return True
        ed.set_track_changes(not ed.track_changes())
        eng._schedule_state()
        changed = False
    elif cmd == ".uno:ShowChangesInMargin":
        ed.set_balloons(not ed.balloons())
        refresh_comments(eng)
    elif cmd == ".uno:ShowTrackedChanges":
        ed.set_markup("simple" if ed.markup() == "all" else "all")
    elif cmd in (".uno:AcceptTrackedChange", ".uno:RejectTrackedChange"):
        if not ed.accept_reject(cmd == ".uno:AcceptTrackedChange"):
            changed = False
    elif cmd in (".uno:AcceptTrackedChangeToNext", ".uno:RejectTrackedChangeToNext"):
        if not ed.accept_reject_next(cmd == ".uno:AcceptTrackedChangeToNext"):
            _message(eng, "The document contains no more tracked changes.")
    elif cmd in (".uno:AcceptAllTrackedChanges", ".uno:RejectAllTrackedChanges"):
        ed.accept_reject_all(cmd == ".uno:AcceptAllTrackedChanges")
    elif cmd in (".uno:NextTrackedChange", ".uno:PreviousTrackedChange"):
        if not ed.goto_change(cmd == ".uno:NextTrackedChange"):
            _message(eng, "The document contains no more tracked changes.")
        view.after_move()
        return True
    elif cmd in (".uno:NextAnnotation", ".uno:PreviousAnnotation"):
        if not ed.goto_comment(cmd == ".uno:NextAnnotation"):
            _message(eng, "There are no more comments.")
        view.after_move()
        return True
    elif cmd == ".uno:InsertAnnotation":
        text = _arg(args, "Text", "") or ""
        if ed.insert_comment(text, _arg(args, "Author", "") or "") is None:
            return False
    elif cmd == ".uno:ReplyComment":
        ed.reply_comment(_own_id(_arg(args, "Id", "")), _arg(args, "Text", "") or "",
                         _arg(args, "Author", "") or "")
    elif cmd == ".uno:ResolveComment":
        ed.resolve_comment(_own_id(_arg(args, "Id", "")))
    elif cmd == ".uno:EditAnnotation":
        ed.edit_comment(_own_id(_arg(args, "Id", "")), _arg(args, "Text", "") or "")
    elif cmd == ".uno:DeleteComment":
        cid = _arg(args, "Id")
        cid = ed.comment_at_caret() if cid is None else _own_id(cid)
        if cid is None or not ed.delete_comments([cid]):
            return True
    elif cmd == ".uno:DeleteAllNotes":
        ed.delete_all_comments()
    elif cmd == ".uno:DeleteAuthor":
        ed.delete_all_comments(_arg(args, "Author", ""))
    else:
        return False
    if changed:
        view.document_changed()
    if "Annotation" in cmd or "Comment" in cmd or "Notes" in cmd or "Author" in cmd:
        refresh_comments(eng)
    eng._schedule_state()
    return True


def set_markup(eng, mode):
    """The window's Display for Review choice."""
    if eng.ed is None:
        return
    eng.ed.set_markup(MARKUP.get(mode, "simple"))
    refresh_comments(eng)
    # the original text is for reading
    eng.view.set_edit(mode != "Original" and not getattr(getattr(eng, "win", None),
                                                          "restricted", False))
    eng.view.document_changed()
    eng._schedule_state()


def _tw(eng, page, x, y):
    return int(x * 20), eng.page_top_tw(page) + int(y * 20)


def annotations(eng):
    """.uno:ViewAnnotations as LibreOfficeKit reports it (twips)."""
    out = []
    ed = eng.ed
    if ed is None:
        return {"comments": out}
    for c in ed.comments():
        rects = []
        for pg, x, y, w, h in c["rects"]:
            tx, ty = _tw(eng, pg, x, y)
            rects.append("%d, %d, %d, %d" % (tx, ty, int(w * 20), int(h * 20)))
        a = c["anchor"]
        if a is not None:
            ax, ay = _tw(eng, a[0], a[1], a[2])
            anchor = "%d, %d, %d, %d" % (ax, ay, 0, int(a[3] * 20))
        else:
            anchor = ""
        out.append({"id": _lok_id(c["id"]),
                    "parentId": _lok_id(c["parent"]) if c["parent"] is not None else "0", "author": c["author"],
                    "initials": c["initials"], "text": c["text"], "dateTime": c["date"],
                    "resolved": "true" if c["done"] else "false",
                    "anchorPos": anchor, "textRange": "; ".join(rects)})
    revs = []
    for i, (author, date, label, pg, x, y, h) in enumerate(ed.revision_balloons()):
        tx, ty = _tw(eng, pg, x, y)
        revs.append({"id": "rev%d" % i, "parentId": "0", "author": author, "dateTime": date,
                     "text": label, "revision": True,
                     "anchorPos": "%d, %d, 0, %d" % (tx, ty, int(h * 20)), "textRange": ""})
    return {"comments": out, "revisions": revs}


TYPE_NAMES = {"Insert": "Insert", "Delete": "Delete", "Format": "Format",
              "ParagraphFormat": "ParagraphFormat", "TableFormat": "TableFormat",
              "TableRowInsert": "TableRowInsert", "TableRowDelete": "TableRowDelete"}


def redlines(eng):
    """The changes as .uno:AcceptTrackedChanges reports them. No textRange:
    the engine draws its own change bars."""
    out = []
    ed = eng.ed
    if ed is None:
        return {"redlines": out}
    for i, (kind, author, date, _para, _s, _e, text) in enumerate(ed.changes()):
        out.append({"index": str(i), "type": TYPE_NAMES.get(kind, kind), "author": author,
                    "dateTime": date, "comment": "", "description": text, "textRange": ""})
    return {"redlines": out}


def command_values(eng, cmd):
    if cmd == ".uno:ViewAnnotations":
        return json.dumps(annotations(eng))
    if cmd == ".uno:AcceptTrackedChanges":
        return json.dumps(redlines(eng))
    return ""


def pane_changes(eng):
    """The Reviewing Pane's list: [{type, author, text, date, para, start,
    end}]."""
    out = []
    for kind, author, date, para, s, e, text in eng.ed.changes():
        d = date.replace("T", " ").rstrip("Z")[:16]
        out.append({"type": kind, "author": author, "text": text, "date": d,
                    "para": para, "start": s, "end": e})
    return out
