"""Document-wide text operations the panes need, with the new engine: going through the
paragraphs in order, the next misspelling or grammar issue from the caret, the thesaurus
(the system's MyThes files), readability statistics, replacing the selection."""
import glob
import os
import re

from . import spell

WORD = spell.WORD


def _ed(win):
    return win.engine.ed


def paragraphs(ed):
    """Every paragraph laid out, in document order: (para, text, langs)."""
    seen = set()
    out = []
    for pg in range(ed.page_count()):
        for para, text, langs in ed.page_text(pg):
            if para in seen:
                continue
            seen.add(para)
            out.append((para, text, langs))
    return out


def _from_caret(ed, after):
    """The paragraphs from the caret's on, then the ones before it (wrapping), each with
    the offset to start looking at."""
    paras = paragraphs(ed)
    cp, co = ed.caret_pos()
    if ed.has_selection() and after:
        # from the end of the selection
        try:
            sel = ed.selection_nodes()
            cp, co = sel[2], sel[3]
        except Exception:
            pass
    idx = next((i for i, p in enumerate(paras) if p[0] == cp), 0)
    order = [(p, co if k == 0 else 0) for k, p in enumerate(paras[idx:])] + [(p, 0) for p in paras[:idx]]
    if paras[idx:] and idx < len(paras):
        order.append((paras[idx], 0))          # the caret's paragraph again, from its start
    return order


def next_misspelling(win, after=True, ignored=()):
    """Select the next misspelled word from the caret on; the word, or None."""
    ed = _ed(win)
    sp = win.engine.view.speller
    if ed is None or sp is None:
        return None
    first = True
    for (para, text, langs), start in _from_caret(ed, after):
        for a, b, w in sp.para_marks(para, text, langs):
            if a < start or (first and after and a == start and ed.has_selection()):
                continue
            if w in ignored:
                continue
            ed.select_nodes(para, a, para, b)
            win.engine.view.after_move()
            win.engine.view.scroll_to_caret()
            return w
        first = False
    return None


def next_grammar(win, after=True, ignored=()):
    """Select the next grammar issue: (message, suggestions, text, key) or None."""
    from .. import grammar
    ed = _ed(win)
    if ed is None:
        return None
    for (para, text, langs), start in _from_caret(ed, after):
        lang = (langs[0][2] if langs and langs[0][2] else "en-US").replace("_", "-")
        l, _s, c = lang.partition("-")
        clean = text.replace("￼", " ")
        for s, n, msg, sugg in grammar.check(clean, l or "en", c or "US"):
            if s < start or (after and s == start and ed.has_selection()):
                continue
            key = (text, s)
            if key in ignored:
                continue
            ed.select_nodes(para, s, para, s + n)
            win.engine.view.after_move()
            win.engine.view.scroll_to_caret()
            return msg, sugg, clean[s:s + n], key
    return None


def replace_selection(win, text):
    ed = _ed(win)
    if ed is None:
        return
    ed.type_text(text)
    win.engine.view.after_edit()


def replace_all(win, find, repl, whole=True, case=True):
    ed = _ed(win)
    n = ed.replace_all(find, repl, {"whole_word": whole, "match_case": case})
    win.engine.view.after_edit()
    return n


def select_word_at_caret(win):
    """The word at the caret, selected; its text."""
    ed = _ed(win)
    if ed.has_selection():
        return ed.selected_text().strip()
    para, off = ed.caret_pos()
    for p, text, _l in paragraphs(ed):
        if p != para:
            continue
        for m in WORD.finditer(text):
            if m.start() <= off <= m.end():
                ed.select_nodes(para, m.start(), para, m.end())
                win.engine.view.after_move()
                return m.group(0)
    return ""


def document_text(win):
    return "\n".join(t.replace("￼", "") for _p, t, _l in paragraphs(_ed(win)))


# ---------------------------------------------------------------- thesaurus
_TH = {}


def _thesaurus(lang):
    tag = (lang or "en_US").replace("-", "_")
    if tag in _TH:
        return _TH[tag]
    th = None
    for d in ("/usr/share/mythes", "/usr/share/myspell/dicts", "/usr/share/hunspell"):
        for pat in ("th_%s_v2.idx" % tag, "th_%s*.idx" % tag, "th_%s*.idx" % tag.split("_")[0]):
            hits = sorted(glob.glob(os.path.join(d, pat)))
            if hits:
                th = _MyThes(hits[0])
                break
        if th:
            break
    _TH[tag] = th
    return th


class _MyThes:
    """A MyThes thesaurus: an index of words to offsets in the data file."""

    def __init__(self, idx):
        self.dat = idx[:-4] + ".dat"
        self.index = {}
        with open(idx, encoding="utf-8", errors="replace") as f:
            enc = f.readline().strip()
            f.readline()
            for line in f:
                w, _, off = line.rstrip("\n").rpartition("|")
                if w:
                    try:
                        self.index[w.lower()] = int(off)
                    except ValueError:
                        pass
        self.enc = enc if enc.lower() not in ("iso8859-1",) else "latin-1"

    def lookup(self, word):
        off = self.index.get(word.lower())
        if off is None:
            return []
        out = []
        with open(self.dat, "rb") as f:
            f.seek(off)
            head = f.readline().decode(self.enc, "replace").rstrip("\n")
            try:
                n = int(head.rpartition("|")[2])
            except ValueError:
                return []
            for _ in range(n):
                parts = f.readline().decode(self.enc, "replace").rstrip("\n").split("|")
                if len(parts) < 2:
                    continue
                pos = parts[0].strip("()")
                words = [_clean(p) for p in parts[1:] if p]
                if words:
                    out.append(("%s (%s)" % (words[0], pos) if pos else words[0], words[1:] or words))
        return out


def _clean(t):
    return t.replace(" (generic term)", "").replace(" (similar term)", "").replace(" (related term)", "") \
        .replace(" (antonym)", " (opposite)")


def synonyms(word, lang=None):
    th = _thesaurus(lang)
    if th is None or not word:
        return []
    res = th.lookup(word)
    if not res and word.lower().endswith("s"):
        res = th.lookup(word[:-1])
    return res


def readability(win):
    """The Editor pane's statistics from the document's text."""
    from .. import grammar

    class _M:
        def getText(self):
            return self

        def getString(self):
            return document_text(win)
    return grammar.readability(_M())
