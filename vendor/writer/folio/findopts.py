"""The 'More >>' part of Find and Replace, as in the original: Sounds like,
Find all word forms, Match prefix / suffix, Ignore punctuation and white
space, Format (find and replace formatting), Reading Highlight and Find In."""
import re

from gi.repository import Gtk

from . import bridge, docapi

PUNCT = "[\\p{P}]*"
SPACE = "[\\s ]*"


# ---------------------------------------------------------------- words
def soundex(word):
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return ""
    codes = {**dict.fromkeys("bfpv", "1"), **dict.fromkeys("cgjkqsxz", "2"),
             **dict.fromkeys("dt", "3"), "l": "4", **dict.fromkeys("mn", "5"), "r": "6"}
    out = w[0].upper()
    last = codes.get(w[0], "")
    for ch in w[1:]:
        c = codes.get(ch, "")
        if c and c != last:
            out += c
        if ch not in "hw":
            last = c
    return (out + "000")[:4]


IRREGULAR = {
    "be": "am is are was were been being", "go": "goes went gone going",
    "have": "has had having", "do": "does did done doing", "say": "says said saying",
    "make": "makes made making", "take": "takes took taken taking",
    "see": "sees saw seen seeing", "come": "comes came coming", "get": "gets got gotten getting",
    "give": "gives gave given giving", "find": "finds found finding",
    "think": "thinks thought thinking", "write": "writes wrote written writing",
    "run": "runs ran running", "sit": "sits sat sitting", "eat": "eats ate eaten eating",
    "buy": "buys bought buying", "bring": "brings brought bringing",
    "know": "knows knew known knowing", "begin": "begins began begun beginning",
    "child": "children", "man": "men", "woman": "women", "mouse": "mice",
    "foot": "feet", "tooth": "teeth", "person": "people",
}
_IRR_INDEX = {}
for _base, _forms in IRREGULAR.items():
    _all = [_base] + _forms.split()
    for _f in _all:
        _IRR_INDEX[_f] = _all


def word_forms(word):
    w = word.lower()
    if w in _IRR_INDEX:
        return sorted(set(_IRR_INDEX[w]))
    stems = {w}
    for suf, rep in (("ies", "y"), ("ied", "y"), ("ying", "ie"), ("ing", ""), ("ing", "e"),
                     ("ed", ""), ("ed", "e"), ("es", ""), ("s", ""), ("er", ""), ("est", "")):
        if w.endswith(suf) and len(w) - len(suf) >= 2:
            stems.add(w[:-len(suf)] + rep)
    out = set()
    for s in stems:
        out |= {s, s + "s", s + "es", s + "ed", s + "ing", s + "er"}
        if s.endswith("e"):
            out |= {s + "d", s[:-1] + "ing", s + "r"}
        if s.endswith("y") and len(s) > 2 and s[-2] not in "aeiou":
            out |= {s[:-1] + "ies", s[:-1] + "ied"}
        if len(s) >= 3 and s[-1] not in "aeiouwxy" and s[-2] in "aeiou" and \
                s[-3] not in "aeiou":
            out |= {s + s[-1] + "ed", s + s[-1] + "ing"}
    return sorted(out)


def search_pattern(text, opts, doc_text=""):
    """(search string, is regular expression) for the options of the
    original. opts: dict of booleans."""
    if opts.get("wild"):
        return _wildcards(text), True
    if opts.get("sounds"):
        code = soundex(text)
        words = sorted({w for w in re.findall(r"[A-Za-z]+", doc_text)
                        if soundex(w) == code}, key=len, reverse=True)
        if not words:
            words = [text]
        return "\\b(" + "|".join(re.escape(w) for w in words) + ")\\b", True
    if opts.get("forms"):
        forms = word_forms(text)
        return "\\b(" + "|".join(re.escape(f) for f in sorted(forms, key=len, reverse=True)) + \
            ")\\b", True
    ip, iw = opts.get("ign_punct"), opts.get("ign_space")
    prefix, suffix = opts.get("prefix"), opts.get("suffix")
    if not (ip or iw or prefix or suffix):
        return text, False
    parts = []
    for ch in text:
        if ip and re.match(r"[^\w\s]", ch):
            continue
        if iw and ch.isspace():
            continue
        parts.append(re.escape(ch))
    gap = (PUNCT if ip else "") + (SPACE if iw else "")
    if ip and iw:
        gap = "[\\p{P}\\s ]*"
    s = gap.join(parts)
    if prefix:
        s = "\\b" + s
    if suffix:
        s = s + "\\b"
    return s, True


def _wildcards(s):
    """The original's wildcard syntax to a regular expression: ? * @ < >
    [ ] {n,m} ( ) and \\ escapes."""
    out, i = [], 0
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s):
            out.append(re.escape(s[i + 1]))
            i += 2
            continue
        if ch == "?":
            out.append(".")
        elif ch == "*":
            out.append(".*?")
        elif ch == "@":
            out.append("+")
        elif ch == "<":
            out.append("\\b(?=\\w)")
        elif ch == ">":
            out.append("\\b(?<=\\w)")
        elif ch == "[":
            j = s.find("]", i)
            if j < 0:
                out.append("\\[")
            else:
                body = s[i + 1:j]
                if body.startswith("!"):
                    body = "^" + body[1:]
                out.append("[" + body + "]")
                i = j
        elif ch == "{":
            j = s.find("}", i)
            if j < 0:
                out.append("\\{")
            else:
                out.append("{" + s[i + 1:j].replace(";", ",") + "}")
                i = j
        elif ch in "()":
            out.append(ch)
        else:
            out.append(re.escape(ch))
        i += 1
    return "".join(out)


# ---------------------------------------------------------------- formatting
class Format:
    """Formatting to find (or to replace with)."""

    def __init__(self):
        self.attrs = {}        # UNO property -> value
        self.style = None      # paragraph style (engine name)
        self.words = []        # description

    def clear(self):
        self.attrs, self.style, self.words = {}, None, []

    def text(self):
        return ", ".join(self.words)

    def empty(self):
        return not self.attrs and not self.style

    def props(self):
        return tuple(bridge.prop(k, v) for k, v in self.attrs.items())


def format_menu(parent, fmt, changed):
    """The Format ▾ button's menu."""
    menu = Gtk.Menu()

    def add(label, fn):
        mi = Gtk.MenuItem(label=label)
        mi.connect("activate", lambda *_: (fn(), changed()))
        menu.append(mi)
    add("Font...", lambda: _font(parent, fmt))
    add("Paragraph...", lambda: _paragraph(parent, fmt))
    add("Language...", lambda: _language(parent, fmt))
    add("Style...", lambda: _style(parent, fmt))
    add("Highlight", lambda: _highlight(fmt))
    menu.show_all()
    return menu


def _font(parent, fmt):
    from .widgets import FDialog, grid
    d = FDialog(parent, "Find Font")
    name = Gtk.ComboBoxText.new_with_entry()
    for f in ("", "Calibri", "Carlito", "Cambria", "Caladea", "Arial", "Liberation Sans",
              "Times New Roman", "Liberation Serif", "Courier New"):
        name.append_text(f)
    style = Gtk.ComboBoxText()
    for s in ("", "Regular", "Italic", "Bold", "Bold Italic"):
        style.append_text(s)
    size = Gtk.ComboBoxText.new_with_entry()
    for s in ("", "8", "9", "10", "11", "12", "14", "16", "18", "20", "24", "28", "36"):
        size.append_text(s)
    und = Gtk.ComboBoxText()
    for s in ("", "(none)", "Single", "Double"):
        und.append_text(s)
    color = Gtk.ComboBoxText()
    for s in ("", "Automatic", "Red", "Blue", "Green"):
        color.append_text(s)
    d.add(grid([["_Font:", name], ["Font st_yle:", style], ["_Size:", size],
                ["_Underline style:", und], ["Font _color:", color]]))
    d.show_all()
    if d.ask() == Gtk.ResponseType.OK:
        n = name.get_child().get_text().strip()
        if n:
            fmt.attrs["CharFontName"] = n
            fmt.words.append("Font: " + n)
        st = style.get_active_text() or ""
        if st:
            fmt.attrs["CharWeight"] = 150.0 if "Bold" in st else 100.0
            fmt.attrs["CharPosture"] = bridge.enum(
                "com.sun.star.awt.FontSlant", "ITALIC" if "Italic" in st else "NONE")
            fmt.words.append({"Regular": "Not Bold, Not Italic"}.get(st, st))
        sz = size.get_child().get_text().strip()
        try:
            if sz:
                fmt.attrs["CharHeight"] = float(sz)
                fmt.words.append("Font: %s pt" % sz)
        except ValueError:
            pass
        u = und.get_active_text() or ""
        if u:
            fmt.attrs["CharUnderline"] = {"(none)": 0, "Single": 1, "Double": 2}[u]
            fmt.words.append("Underline" if u != "(none)" else "No underline")
        c = color.get_active_text() or ""
        if c:
            fmt.attrs["CharColor"] = {"Automatic": -1, "Red": 0xFF0000, "Blue": 0x0070C0,
                                      "Green": 0x00B050}[c]
            fmt.words.append("Font color: " + c)
    d.destroy()


def _paragraph(parent, fmt):
    from .widgets import FDialog, grid
    d = FDialog(parent, "Find Paragraph")
    al = Gtk.ComboBoxText()
    for s in ("", "Left", "Centered", "Right", "Justified"):
        al.append_text(s)
    d.add(grid([["Ali_gnment:", al]]))
    d.show_all()
    if d.ask() == Gtk.ResponseType.OK and al.get_active_text():
        a = al.get_active_text()
        fmt.attrs["ParaAdjust"] = bridge.enum(
            "com.sun.star.style.ParagraphAdjust",
            {"Left": "LEFT", "Centered": "CENTER", "Right": "RIGHT", "Justified": "BLOCK"}[a])
        fmt.words.append(a)
    d.destroy()


def _language(parent, fmt):
    from .widgets import FDialog
    d = FDialog(parent, "Find Language")
    c = Gtk.ComboBoxText()
    for name, _l, _c in docapi.LANGUAGES:
        c.append_text(name)
    c.set_active(0)
    d.add(c)
    d.show_all()
    if d.ask() == Gtk.ResponseType.OK:
        name, lang, country = docapi.LANGUAGES[c.get_active()]
        fmt.attrs["CharLocale"] = bridge.struct("com.sun.star.lang.Locale",
                                                Language=lang, Country=country)
        fmt.words.append(name)
    d.destroy()


def _style(parent, fmt):
    from .widgets import FDialog
    from .actions import FROM_ENGINE, engine_style
    win = parent
    m = getattr(getattr(win, "engine", None), "model", None)
    if m is None:
        try:
            m = parent.get_transient_for().engine.model
        except Exception:
            return
    d = FDialog(parent, "Find Style")
    ps = m.getStyleFamilies().getByName("ParagraphStyles")
    names = sorted({FROM_ENGINE.get(n, n) for n in ps.getElementNames()
                    if ps.getByName(n).isInUse() or n.startswith("Heading")}, key=str.lower)
    c = Gtk.ComboBoxText()
    for n in names:
        c.append_text(n)
    c.set_active(names.index("Normal") if "Normal" in names else 0)
    d.add(Gtk.Label(label="Find what style:", xalign=0))
    d.add(c)
    d.show_all()
    if d.ask() == Gtk.ResponseType.OK and c.get_active_text():
        fmt.style = engine_style(c.get_active_text())
        fmt.words.append("Style: " + c.get_active_text())
    d.destroy()


def _highlight(fmt):
    fmt.attrs["CharHighlight"] = 0xFFFF00
    fmt.words.append("Highlight")


def matches_format(rng, fmt):
    """Does the found text carry the formatting?"""
    if fmt.empty():
        return True
    try:
        if fmt.style and rng.ParaStyleName != fmt.style:
            return False
        for k, v in fmt.attrs.items():
            cur = rng.getPropertyValue(k)
            if k == "CharLocale":
                if (cur.Language, cur.Country) != (v.Language, v.Country):
                    return False
            elif k == "CharHighlight":
                if cur in (-1, None) and getattr(rng, "CharBackColor", -1) in (-1, None):
                    return False
            elif hasattr(v, "value"):
                if getattr(cur, "value", cur) != v.value:
                    return False
            elif isinstance(v, float):
                if cur is None or abs(cur - v) > 0.01:
                    return False
            elif cur != v:
                return False
    except Exception:
        return False
    return True


def apply_format(rng, fmt):
    if fmt.style:
        rng.ParaStyleName = fmt.style
    for k, v in fmt.attrs.items():
        try:
            rng.setPropertyValue(k, v)
        except Exception as e:
            print("replace format:", e)


# ---------------------------------------------------------------- highlight
class ReadingHighlight:
    """Highlights every match on screen without changing the document: the
    highlighting isn't undoable, saved or counted as a change."""

    def __init__(self, win):
        self.win = win
        self.marks = []
        win.engine.save_hooks = tuple(win.engine.save_hooks) + ((self.clear, lambda: None),)

    def highlight(self, ranges):
        self.clear()
        m = self.win.engine.model
        if m is None:
            return 0
        was = m.isModified()
        um = m.getUndoManager()
        um.lock()
        try:
            for r in ranges:
                try:
                    c = r.getText().createTextCursorByRange(r)
                    self.marks.append((c, c.CharBackColor, c.CharBackTransparent))
                    c.CharBackColor = 0xFFFF00
                except Exception:
                    pass
        finally:
            um.unlock()
            if not was:
                m.setModified(False)
        return len(self.marks)

    def clear(self):
        if not self.marks:
            return
        m = self.win.engine.model
        if m is None:
            self.marks = []
            return
        was = m.isModified()
        um = m.getUndoManager()
        um.lock()
        try:
            for c, color, transp in self.marks:
                try:
                    c.CharBackColor = color
                    c.CharBackTransparent = transp
                except Exception:
                    pass
        finally:
            um.unlock()
            self.marks = []
            if not was:
                m.setModified(False)
