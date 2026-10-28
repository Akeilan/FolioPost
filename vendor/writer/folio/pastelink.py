"""Paste Special > Paste link: text copied from a saved document is pasted as
a link to it, and updates when the source changes (F9 / right-click
Update Link). The copied range gets a hidden bookmark in the source; the
target gets a section linked to that bookmark."""
import time

from . import bridge, docapi

SOURCE = {}


def remember_copy(win, text):
    """Called on Copy: keep the copied range so it can be linked to later."""
    m = win.engine.model
    if m is None or not text:
        SOURCE.clear()
        return
    try:
        vc = docapi.view_cursor(m)
        if vc.isCollapsed():
            SOURCE.clear()
            return
        rng = vc.getText().createTextCursorByRange(vc)
    except Exception:
        SOURCE.clear()
        return
    SOURCE.clear()
    SOURCE.update(win=win, range=rng, text=text, time=time.time())


def available(win, clip_text):
    """Can the clipboard be pasted as a link?"""
    src = SOURCE.get("win")
    return bool(src is not None and src is not win and SOURCE.get("text") and
                (clip_text or "").strip() == SOURCE["text"].strip())


def paste(win):
    src = SOURCE.get("win")
    if src is None:
        return False
    sm = src.engine.model
    if not src.engine.path:
        win.dialogs.message("Save the document you copied from first, then paste the "
                            "link again.")
        return False
    marks = sm.getBookmarks()
    n = 1
    while marks.hasByName("_Link%d" % n):
        n += 1
    name = "_Link%d" % n
    bm = sm.createInstance("com.sun.star.text.Bookmark")
    bm.setName(name)
    rng = SOURCE["range"]
    rng.getText().insertTextContent(rng, bm, True)
    src.save()
    m = win.engine.model
    vc = docapi.view_cursor(m)
    text = vc.getText()
    sec = m.createInstance("com.sun.star.text.TextSection")
    secs = m.getTextSections()
    k = 1
    while secs.hasByName("Link%d" % k):
        k += 1
    sec.setName("Link%d" % k)
    link = bridge.struct("com.sun.star.text.SectionFileLink")
    link.FileURL = docapi.uno_url(src.engine.path)
    link.FilterName = ""
    sec.FileLink = link
    sec.LinkRegion = name
    um = m.getUndoManager()
    um.enterUndoContext("Paste Link")
    try:
        text.insertTextContent(vc, sec, False)
    finally:
        um.leaveUndoContext()
    update(win)
    return True


def links(m):
    out = []
    secs = m.getTextSections()
    for i in range(secs.getCount()):
        s = secs.getByIndex(i)
        try:
            if s.FileLink.FileURL:
                out.append(s)
        except Exception:
            pass
    return out


def update(win):
    win.engine.command(".uno:UpdateAllLinks")


def section_at_cursor(m):
    try:
        sec = docapi.read_cursor(m).TextSection
        while sec is not None:
            if sec.FileLink.FileURL:
                return sec
            sec = sec.getParentSection()
    except Exception:
        pass
    return None
