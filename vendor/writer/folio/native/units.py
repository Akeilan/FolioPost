"""Selecting by unit with the new engine: the word, sentence or paragraph
around the caret (F8 in Extend mode, Ctrl+click, the Select commands)."""
import re

SENTENCE_END = re.compile(r"[.!?]+[\"'”’)\]]*\s+")


def word_bounds(text, off):
    """The word at off (with its trailing spaces, as Word selects it)."""
    if not text:
        return 0, 0
    off = min(off, len(text))
    isw = lambda c: c.isalnum() or c in "_'’"  # noqa: E731
    a = off
    if a < len(text) and isw(text[a]) or (a > 0 and isw(text[a - 1])):
        while a > 0 and isw(text[a - 1]):
            a -= 1
        b = off
        while b < len(text) and isw(text[b]):
            b += 1
    else:
        a, b = off, min(off + 1, len(text))
    while b < len(text) and text[b] == " ":
        b += 1
    return a, b


def sentence_bounds(text, off):
    a = 0
    for m in SENTENCE_END.finditer(text):
        if m.end() <= off:
            a = m.end()
        else:
            break
    b = len(text)
    for m in SENTENCE_END.finditer(text, a):
        b = m.end()
        break
    return a, b


def select_unit(ed, unit):
    if unit == "all":
        ed.select_all()
        return
    if ed.has_selection():
        pa, a, pb, b = ed.selection_range()
    else:
        pa, a = ed.caret_pos()
        pb, b = pa, a
    text = ed.para_text_of(pa)
    if unit == "word":
        x, y = word_bounds(text, a)
    elif unit == "sentence":
        x, y = sentence_bounds(text, a)
        if pb == pa:
            y = max(y, sentence_bounds(text, max(b - 1, a))[1])
    else:
        x, y = 0, len(text)
    if unit == "paragraph" or pb == pa:
        ed.select_nodes(pa, x, pa, y)
    else:
        ed.select_nodes(pa, x, pb, len(ed.para_text_of(pb)) if unit == "paragraph" else b)
