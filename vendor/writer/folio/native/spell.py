"""Spelling as you type with the new engine: misspelled words on the pages in view get a
red wavy underline (checked with the system's Hunspell dictionaries through Enchant, the
user's dictionary included); the right-click menu offers suggestions, Ignore All and Add to
Dictionary."""
import math
import re

from gi.repository import GLib

WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*", re.UNICODE)
_DICTS = {}


USER_WORDS = "~/.config/folio-writer/dictionary.txt"


def user_words_path():
    import os
    path = os.path.expanduser(USER_WORDS)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        open(path, "a").close()
    return path


def add_to_dictionary(word):
    word = word.strip()
    if not word:
        return
    path = user_words_path()
    with open(path, encoding="utf-8", errors="replace") as f:
        words = [w.strip() for w in f if w.strip()]
    if word not in words:
        with open(path, "a", encoding="utf-8") as f:
            f.write(word + "\n")
    reload_user_words()


def _dict(tag):
    """An Enchant dictionary for a language tag (en-US, nl-NL...); None: no checking."""
    tag = (tag or "").replace("-", "_")
    if tag in _DICTS:
        return _DICTS[tag]
    d = None
    try:
        import enchant
        pwl = user_words_path()
        for t in (tag, tag.split("_")[0], "en_US"):
            if not t:
                continue
            try:
                if enchant.dict_exists(t):
                    d = enchant.DictWithPWL(t, pwl)
                    break
            except Exception:
                continue
    except ImportError:
        d = None
    _DICTS[tag] = d
    return d


def reload_user_words():
    _DICTS.clear()


class Speller:
    def __init__(self, win):
        self.win = win
        self.cache = {}           # (para, text) -> [(a, b, word)]
        self.pages = {}           # page -> (version, [(para, a, b, word)], [(x, y, w, h, para, a, b, word)])
        self.pending = set()
        self._idle = 0

    @property
    def ed(self):
        return self.win.engine.ed

    def enabled(self):
        s = getattr(self.win.app, "settings", {}) or {}
        if not s.get("auto_spell", True):
            return False
        ed = self.ed
        try:
            return ed is not None and not ed.setting("hideSpellingErrors")
        except Exception:
            return ed is not None

    def default_lang(self):
        s = getattr(self.win.app, "settings", {}) or {}
        return s.get("proofing_language") or "en_US"

    def ignored(self, word):
        ig = getattr(self.win, "ignored_words", None) or ()
        s = getattr(self.win.app, "settings", {}) or {}
        if s.get("ignore_upper", True) and word.isupper():
            return True
        return word in ig or len(word) < 2

    def check_word(self, word, lang):
        if self.ignored(word):
            return True
        if lang in ("zxx", "x-none"):
            return True
        d = _dict(lang or self.default_lang())
        if d is None:
            return True
        try:
            return d.check(word) or d.check(word.replace("’", "'"))
        except Exception:
            return True

    def suggestions(self, word, lang=None, limit=6):
        """Hunspell's suggestions, the closest first (a swapped pair of letters counts as one
        change, as the original ranks "Teh" -> "The")."""
        d = _dict(lang or self.default_lang())
        if d is None:
            return []
        try:
            cands = []
            if word[:1].isupper() and not word.isupper():
                # a capitalised word is looked up as typed in lower case too, its order first
                for s in d.suggest(word.lower()):
                    c = s[:1].upper() + s[1:]
                    if c not in cands:
                        cands.append(c)
            for c in d.suggest(word):
                if c not in cands:
                    cands.append(c)
        except Exception:
            return []
        order = {c: i for i, c in enumerate(cands)}
        cands.sort(key=lambda c: (_distance(word.lower(), c.lower()), " " in c, order[c]))
        return cands[:limit]

    def para_marks(self, para, text, langs):
        key = (para, text)
        hit = self.cache.get(key)
        if hit is not None:
            return hit
        out = []
        for m in WORD.finditer(text):
            a, b = m.start(), m.end()
            # the word right after an object or field isn't a word of its own
            if (a > 0 and text[a - 1] == "￼") or (b < len(text) and text[b] == "￼"):
                continue
            lang = next((l for (s, e, l) in langs if s <= a < e), "")
            if not self.check_word(m.group(0), lang):
                out.append((a, b, m.group(0)))
        if len(self.cache) > 4000:
            self.cache.clear()
        self.cache[key] = out
        return out

    def page_marks(self, page):
        """Rectangles under the misspelled words of a page (computed in idle time)."""
        ed = self.ed
        if ed is None or not self.enabled():
            return []
        hit = self.pages.get(page)
        if hit and hit[0] == ed.version:
            return hit[2]
        if page not in self.pending:
            self.pending.add(page)
            if not self._idle:
                self._idle = GLib.idle_add(self._work)
        return hit[2] if hit else []

    def _work(self):
        self._idle = 0
        ed = self.ed
        if ed is None:
            self.pending.clear()
            return False
        caret = None
        try:
            caret = ed.caret_pos()
        except Exception:
            caret = None
        done = []
        for page in list(self.pending)[:3]:
            self.pending.discard(page)
            marks, rects = [], []
            try:
                paras = ed.page_text(page)
            except Exception:
                paras = []
            for para, text, langs in paras:
                for a, b, w in self.para_marks(para, text, langs):
                    # the word being typed isn't marked yet
                    if caret is not None and caret[0] == para and a <= caret[1] <= b and getattr(self.win.engine.view, "typing", False):
                        continue
                    marks.append((para, a, b, w))
                    for (pg, x, y, wd, h) in ed.range_rects(para, a, para, b):
                        if pg == page:
                            rects.append((x, y, wd, h, para, a, b, w))
            self.pages[page] = (ed.version, marks, rects)
            done.append(page)
        if done:
            self.win.engine.view.queue_draw()
        if self.pending:
            self._idle = GLib.idle_add(self._work)
        return False

    def invalidate(self):
        self.pages.clear()
        self.pending.clear()

    def at(self, page, x, y):
        """The misspelled word under a point (page coordinates): (para, a, b, word) or None."""
        hit = self.pages.get(page)
        if not hit:
            return None
        for (rx, ry, rw, rh, para, a, b, w) in hit[2]:
            if rx <= x <= rx + rw and ry <= y <= ry + rh:
                return (para, a, b, w)
        return None


def draw(cr, rects, ox, oy, s):
    """Red wavy lines under the words."""
    if not rects:
        return
    cr.save()
    cr.set_source_rgb(0.86, 0.1, 0.1)
    cr.set_line_width(max(0.8, s * 0.6))
    amp = max(1.0, s * 0.9)
    step = max(2.0, s * 2.0)
    for (x, y, w, h, *_rest) in rects:
        x0 = ox + x * s
        x1 = ox + (x + w) * s
        yb = oy + (y + h) * s - amp - max(0.5, s * 0.4)
        cr.move_to(x0, yb)
        k = 0
        xx = x0
        while xx < x1:
            xx = min(x1, xx + step / 2)
            k += 1
            cr.line_to(xx, yb + (amp if k % 2 else 0))
        cr.stroke()
    cr.restore()


def menu_items(win, hit):
    """Suggestions for the word under the pointer, for the right-click menu."""
    para, a, b, word = hit
    sp = win.engine.view.speller
    ed = win.engine.ed
    items = []

    def replace(w):
        ed.select_nodes(para, a, para, b)
        win.engine._edit(ed.type_text, w)
    sug = sp.suggestions(word)
    for w in sug:
        items.append((w, lambda w=w: replace(w)))
    if not sug:
        items.append(("(no suggestions)", None))
    items.append(None)

    def ignore():
        if not hasattr(win, "ignored_words") or win.ignored_words is None:
            win.ignored_words = set()
        win.ignored_words.add(word)
        sp.cache.clear()
        sp.invalidate()
        win.engine.view.queue_draw()

    def add():
        add_to_dictionary(word)
        sp.cache.clear()
        sp.invalidate()
        win.engine.view.queue_draw()
    items.append(("Ignore All", ignore))
    items.append(("Add to Dictionary", add))
    items.append(None)
    return items


def _distance(a, b):
    """Optimal string alignment distance (edits, with adjacent swaps as one)."""
    la, lb = len(a), len(b)
    d = [[0] * (lb + 1) for _ in range(la + 1)]
    for i in range(la + 1):
        d[i][0] = i
    for j in range(lb + 1):
        d[0][j] = j
    for i in range(1, la + 1):
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[la][lb]
