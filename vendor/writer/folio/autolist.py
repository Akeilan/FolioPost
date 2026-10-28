"""AutoFormat As You Type: lists started by typing a marker and a space, for
the markers the engine doesn't turn into lists itself - "a) ", "A. ",
"i. ", "(1) ", "(a) ", "> " - as in the original."""
import re

from gi.repository import GLib

from . import bridge, docapi

ROMAN = re.compile(r"^(?=[ivxlcdm]+$)m{0,3}(cm|cd|d?c{0,3})(xc|xl|l?x{0,3})(ix|iv|v?i{0,3})$")

# numbering types (com.sun.star.style.NumberingType)
UPPER, LOWER, ROMAN_UP, ROMAN_LOW, ARABIC = 0, 1, 2, 3, 4

PATTERN = re.compile(r"^(\(?)([A-Za-z]{1,4}|\d{1,3})([.)])$")


def _roman_value(s):
    vals = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}
    s = s.lower()
    total = 0
    for i, ch in enumerate(s):
        v = vals[ch]
        if i + 1 < len(s) and vals[s[i + 1]] > v:
            total -= v
        else:
            total += v
    return total


def parse_marker(text):
    """'a)' -> (LOWER, 1, '', ')'); None when it isn't a list marker."""
    if text == ">":
        return ("arrow",)
    mm = PATTERN.match(text)
    if not mm:
        return None
    pre, core, suf = mm.groups()
    if pre and suf != ")":
        return None
    if core.isdigit():
        if not pre:
            return None          # "1. " and "1) " are the engine's own
        return (ARABIC, int(core), pre, suf)
    if len(core) == 1 and core not in "iIvVxX":
        return (LOWER if core.islower() else UPPER, ord(core.lower()) - 96, pre, suf)
    if ROMAN.match(core.lower()) and (core.islower() or core.isupper()):
        return (ROMAN_LOW if core.islower() else ROMAN_UP, _roman_value(core), pre, suf)
    return None


def on_space(win):
    """Called before a plain Space reaches the document. True when it started
    a list (the space is used up, as in the original)."""
    if not win.app.settings.get("ac_lists", True):
        return False
    m = win.engine.model
    if m is None:
        return False
    try:
        vc = docapi.view_cursor(m)
        if not vc.isCollapsed():
            return False
        c = vc.getText().createTextCursorByRange(vc.getStart())
        c.gotoStartOfParagraph(True)
        before = c.getString()
        if not before or len(before) > 6:
            return False
        para = c.getText().createTextCursorByRange(c.getStart())
        para.gotoEndOfParagraph(True)
        if getattr(para, "NumberingIsNumber", False):
            return False
        spec = parse_marker(before)
        if spec is None:
            return False
        um = m.getUndoManager()
        um.enterUndoContext("AutoFormat")
        try:
            c.setString("")
        finally:
            um.leaveUndoContext()
    except Exception as e:
        print("autolist:", e)
        return False
    win.actions.do_bullets() if spec[0] == "arrow" else win.actions.do_numbering()
    win.engine.sync(lambda: GLib.timeout_add(220, _apply, win, spec))
    return True


def _apply(win, spec):
    """Give the new list the typed marker's numbering format."""
    import uno
    m = win.engine.model
    try:
        vc = docapi.view_cursor(m)
        c = vc.getText().createTextCursorByRange(vc.getStart())
        rules = c.NumberingRules
        if rules is None:
            return False
        lvl = c.NumberingLevel or 0
        if spec[0] == "arrow":
            changes = {"NumberingType": 6, "BulletChar": "\u27a2"}
        else:
            kind, start, pre, suf = spec
            changes = {"NumberingType": kind, "Prefix": pre, "Suffix": suf,
                       "StartWith": start, "ListFormat": pre + "%" + str(lvl + 1) + "%" + suf}
        out = []
        for p in rules.getByIndex(lvl):
            if p.Name in changes:
                p = bridge.prop(p.Name, changes.pop(p.Name))
            out.append(p)
        for k, v in changes.items():
            out.append(bridge.prop(k, v))
        uno.invoke(rules, "replaceByIndex",
                   (lvl, uno.Any("[]com.sun.star.beans.PropertyValue", tuple(out))))
        c.NumberingRules = rules
    except Exception as e:
        print("autolist:", e)
    return False


def on_marker_char(win, ch):
    """Typing '.' or ')' right after a lowercase roman numeral at the start of
    a paragraph: put it in directly, so AutoCorrect doesn't capitalize the
    'i' before the list is made."""
    m = win.engine.model
    if m is None or not win.app.settings.get("ac_lists", True):
        return False
    try:
        vc = docapi.view_cursor(m)
        if not vc.isCollapsed():
            return False
        c = vc.getText().createTextCursorByRange(vc.getStart())
        c.gotoStartOfParagraph(True)
        before = c.getString()
        if not before or not ROMAN.match(before.lstrip("(")) or before != before.lower():
            return False
        if before.startswith("(") and ch != ")":
            return False
        win.actions.insert_text(ch)
        return True
    except Exception:
        return False
