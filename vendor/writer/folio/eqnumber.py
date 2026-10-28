"""Equation numbers: typing E=mc^2#(1) puts the equation in the middle of its
line and (1) against the right margin, as in the original. The paragraph
gets a centre and a right tab stop: <tab>equation<tab>(1)."""
from . import bridge, docapi


def _para_cursor(obj):
    anchor = obj.getAnchor()
    text = anchor.getText()
    return text, anchor


def _after(text, anchor):
    """A cursor just after the equation (its anchor sits in front of it)."""
    cur = text.createTextCursorByRange(anchor.getStart())
    cur.goRight(1, False)
    return cur


def current(obj):
    """The number text after the equation, or None."""
    try:
        text, anchor = _para_cursor(obj)
        cur = _after(text, anchor)
        cur.gotoEndOfParagraph(True)
        s = cur.getString()
        if s.startswith("\t") and s.strip():
            par = text.createTextCursorByRange(anchor.getStart())
            if len(par.ParaTabStops) >= 2:
                return s[1:].strip()
    except Exception:
        pass
    return None


def _stops(m):
    ps = docapi.page_setup(m)
    width = ps["width"] - ps["left"] - ps["right"]
    centre = bridge.struct("com.sun.star.style.TabStop")
    centre.Position = int(width / 2)
    centre.Alignment = bridge.enum("com.sun.star.style.TabAlign", "CENTER")
    right = bridge.struct("com.sun.star.style.TabStop")
    right.Position = int(width)
    right.Alignment = bridge.enum("com.sun.star.style.TabAlign", "RIGHT")
    return (centre, right)


def apply(win, obj, number):
    """Set (number) or remove (None) the equation's number."""
    m = win.engine.model
    if m is None:
        return
    old = current(obj)
    if old == number or (old is None and not number):
        return
    text, anchor = _para_cursor(obj)
    um = m.getUndoManager()
    um.enterUndoContext("Equation Number")
    try:
        after = _after(text, anchor)
        after.gotoEndOfParagraph(True)
        before = text.createTextCursorByRange(anchor.getStart())
        before.gotoStartOfParagraph(True)
        if number:
            after.setString("\t" + number)
            if before.getString() != "\t":
                before.setString("\t")
            par = text.createTextCursorByRange(anchor.getStart())
            par.ParaTabStops = _stops(m)
            par.ParaAdjust = 0
        else:
            after.setString("")
            if before.getString() == "\t":
                before.setString("")
            par = text.createTextCursorByRange(anchor.getStart())
            par.ParaTabStops = ()
            par.ParaAdjust = 3
    finally:
        um.leaveUndoContext()
