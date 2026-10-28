"""The Borders drop-down, as in the original: it works on the selected
paragraphs, or on the selected table cells (outside, inside, inside
horizontal / vertical, diagonal)."""
from . import bridge, docapi, tablelayout

SIDES = {"top": "TopBorder", "bottom": "BottomBorder", "left": "LeftBorder",
         "right": "RightBorder"}


def _line(width_pt=0.5, color=0):
    w = int(round(width_pt * 2540 / 72))
    return bridge.struct("com.sun.star.table.BorderLine2", Color=color, LineWidth=w,
                         OuterLineWidth=w)


def _none():
    return bridge.struct("com.sun.star.table.BorderLine2")


def _on(line):
    return line is not None and (line.OuterLineWidth > 0 or line.LineWidth > 0)


def apply_win(win, which):
    """The Borders menu for a window (either engine)."""
    if getattr(win.engine, "native", False):
        from .native import tables
        tables.borders_menu(win, which)
        return
    apply(win.engine.model, which)


def apply(m, which):
    t, _c = tablelayout.current(m)
    um = m.getUndoManager()
    um.enterUndoContext("Borders")
    try:
        if t is not None:
            _cells(m, t, which)
        else:
            _paragraphs(m, which)
    finally:
        um.leaveUndoContext()


def _cells(m, t, which):
    names = tablelayout._selected_cells(m, t)
    if not names:
        return
    pos = {n: tablelayout._rc(n) for n in names}
    rows = [r for r, _k in pos.values()]
    cols = [k for _r, k in pos.values()]
    r0, r1, c0, c1 = min(rows), max(rows), min(cols), max(cols)
    line, none = _line(), _none()
    # a single side toggles, as in the original
    if which in SIDES:
        cells = [n for n in names if
                 (which == "top" and pos[n][0] == r0) or (which == "bottom" and pos[n][0] == r1) or
                 (which == "left" and pos[n][1] == c0) or (which == "right" and pos[n][1] == c1)]
        on = not all(_on(getattr(t.getCellByName(n), SIDES[which])) for n in cells)
        for n in cells:
            setattr(t.getCellByName(n), SIDES[which], line if on else none)
        return
    if which in ("diag-down", "diag-up"):
        prop = "DiagonalTLBR" if which == "diag-down" else "DiagonalBLTR"
        for n in names:
            cell = t.getCellByName(n)
            try:
                cur = getattr(cell, prop)
                setattr(cell, prop, none if _on(cur) else line)
            except Exception as e:
                print("diagonal:", e)
        return
    for n in names:
        r, k = pos[n]
        cell = t.getCellByName(n)
        outer = {"top": r == r0, "bottom": r == r1, "left": k == c0, "right": k == c1}
        for side, prop in SIDES.items():
            inner_h = side in ("top", "bottom") and not outer[side]
            inner_v = side in ("left", "right") and not outer[side]
            if which == "none":
                val = none
            elif which == "all":
                val = line
            elif which == "outside":
                val = line if outer[side] else None
            elif which == "inside":
                val = line if (inner_h or inner_v) else None
            elif which == "inside-h":
                val = line if inner_h else None
            elif which == "inside-v":
                val = line if inner_v else None
            else:
                val = None
            if val is not None:
                setattr(cell, prop, val)


def _paragraphs(m, which):
    vc = docapi.view_cursor(m)
    text = vc.getText()
    c = text.createTextCursorByRange(vc.getStart())
    c.gotoStartOfParagraph(False)
    c.gotoRange(vc.getEnd(), True)
    c.gotoEndOfParagraph(True)
    paras = []
    en = c.createEnumeration()
    while en.hasMoreElements():
        p = en.nextElement()
        if p.supportsService("com.sun.star.text.Paragraph"):
            paras.append(p)
    if not paras:
        return
    line, none = _line(), _none()
    if which in SIDES:
        prop = SIDES[which]
        on = not all(_on(getattr(p, prop)) for p in paras)
        for p in paras:
            setattr(p, prop, line if on else none)
            setattr(p, prop + "Distance", int(1 * 2540 / 72) if on else 0)
        return
    if which in ("inside-h",):
        for i, p in enumerate(paras):
            p.BottomBorder = line if i < len(paras) - 1 else p.BottomBorder
            p.BottomBorderDistance = int(1 * 2540 / 72)
            p.ParaIsConnectBorder = False
        return
    if which in ("inside", "inside-v", "diag-down", "diag-up"):
        return                      # not for paragraphs (greyed in the original)
    for p in paras:
        for side, prop in SIDES.items():
            on = which in ("all", "outside")
            setattr(p, prop, line if on else none)
            setattr(p, prop + "Distance", (int(1 * 2540 / 72) if side in ("top", "bottom")
                                           else int(4 * 2540 / 72)) if on else 0)
        try:
            p.ParaIsConnectBorder = which in ("outside",)
        except Exception:
            pass


def horizontal_line(win):
    """A paragraph of its own with a line across, as the original inserts."""
    if getattr(win.engine, "native", False):
        ed = win.engine.ed
        p0 = ed.caret_pos()[0]
        for _i in range(500):
            ed.move_caret("end", False)
            c = ed.caret_pos()
            ed.move_caret("right", False)
            n = ed.caret_pos()
            if n[0] != p0 or n == c:
                if n != c:
                    ed.move_caret("left", False)
                break
        line = [("w:val", "single"), ("w:sz", "12"), ("w:space", "1"), ("w:color", "A0A0A0")]
        ed.begin_group("Horizontal Line")
        ed.type_text("\n")
        ed.set_borders("paras", [(s, None) for s in ("top", "left", "right", "between")] + [("bottom", line)])
        ed.type_text("\n")
        ed.set_borders("paras", [(s, None) for s in ("top", "left", "bottom", "right", "between")])
        ed.end_group()
        win.engine.view.after_edit()
        return
    m = win.engine.model
    if m is None:
        return
    um = m.getUndoManager()
    um.enterUndoContext("Horizontal Line")
    try:
        vc = docapi.view_cursor(m)
        text = vc.getText()
        cur = text.createTextCursorByRange(vc.getStart())
        cur.gotoEndOfParagraph(False)
        text.insertControlCharacter(cur, 0, False)
        cur.BottomBorder = bridge.struct("com.sun.star.table.BorderLine2", Color=0xA0A0A0,
                                         LineWidth=53, OuterLineWidth=53)
        cur.BottomBorderDistance = 0
        text.insertControlCharacter(cur, 0, False)
        cur.BottomBorder = _none()
        vc.gotoRange(cur.getStart(), False)
    finally:
        um.leaveUndoContext()
