"""Equations as Office Math in RTF.

The engine turns pasted RTF math ({\\mmath ...}) into a real, editable
equation object, and gives it back the same way when an equation is
selected. to_rtf() builds that from linear text; from_rtf() reads it back
into linear text for the equation bar.
"""
import re

from . import symbols as S
from .unicodemath import (Accent, Atom, Brace, Delim, EqArray, Fact, Frac, Func,
                          Limit, Matrix, Nary, Prime, Root, Script, Seq, parse,
                          to_linear)


# --------------------------------------------------------------- RTF text
def _esc(text):
    out = []
    for ch in text:
        o = ord(ch)
        if ch in "\\{}":
            out.append("\\" + ch)
        elif o < 128:
            out.append(ch)
        elif o <= 0xFFFF:
            out.append("\\u%d?" % (o - 65536 if o > 32767 else o))
        else:
            o -= 0x10000
            hi, lo = 0xD800 + (o >> 10), 0xDC00 + (o & 0x3FF)
            out.append("\\u%d?\\u%d?" % (hi - 65536, lo - 65536))
    return "".join(out)


def _g(word, *parts):
    return "{\\" + word + " " + "".join(parts) + "}"


def _r(text, normal=False):
    if not text:
        return ""
    if normal:
        return "{\\mr {\\mrPr {\\mnor 1}}" + _esc(text) + "}"
    return "{\\mr " + _esc(text) + "}"


def _prop(name, value):
    return "{\\m%s %s}" % (name, _esc(value))


# --------------------------------------------------------------- tree -> math
def _e(node, word="me"):
    return _g(word, _m(node))


def _m(node):
    if node is None:
        return ""
    if isinstance(node, Seq):
        return "".join(_m(i) for i in node.items)
    if isinstance(node, Atom):
        k, v = node.kind, node.value
        if k == "text":
            return _r(v, normal=True)
        if k == "placeholder":
            return _r("\u2b1a")
        if k == "space":
            return _r(v)
        return _r(v)
    if isinstance(node, Frac):
        pr = ""
        if node.kind == "linear":
            pr = _g("mfPr", _prop("type", "lin"))
        elif node.kind == "stack":
            pr = _g("mfPr", _prop("type", "noBar"))
        elif node.kind == "skew":
            pr = _g("mfPr", _prop("type", "skw"))
        return _g("mf", pr, _e(node.num, "mnum"), _e(node.den, "mden"))
    if isinstance(node, Script):
        base = _e(node.base)
        if node.pre:
            return _g("msPre", _e(node.sub, "msub"), _e(node.sup, "msup"), base)
        if node.sub is not None and node.sup is not None:
            return _g("msSubSup", base, _e(node.sub, "msub"), _e(node.sup, "msup"))
        if node.sub is not None:
            return _g("msSub", base, _e(node.sub, "msub"))
        return _g("msSup", base, _e(node.sup, "msup"))
    if isinstance(node, Prime):
        return _g("msSup", _e(node.base), _g("msup", _r("\u2032" * node.count)))
    if isinstance(node, Fact):
        return _m(node.base) + _r("!")
    if isinstance(node, Root):
        if node.index is None:
            return _g("mrad", _g("mradPr", _prop("degHide", "1")), _g("mdeg", ""),
                      _e(node.body))
        return _g("mrad", _e(node.index, "mdeg"), _e(node.body))
    if isinstance(node, Nary):
        pr = _prop("chr", node.op)
        if node.op in "∫∬∭∮∯∰":
            pr += _prop("limLoc", "subSup")
        else:
            pr += _prop("limLoc", "undOvr")
        if node.sub is None:
            pr += _prop("subHide", "1")
        if node.sup is None:
            pr += _prop("supHide", "1")
        return _g("mnary", _g("mnaryPr", pr), _e(node.sub, "msub"),
                  _e(node.sup, "msup"), _e(node.body))
    if isinstance(node, Delim):
        if node.open == "(" and node.close == ")":
            pr = ""
        else:
            pr = _g("mdPr", _prop("begChr", node.open), _prop("endChr", node.close))
        return _g("md", pr, _e(node.body))
    if isinstance(node, Matrix):
        rows = "".join(_g("mmr", *[_e(c) for c in r]) for r in node.rows)
        return _g("mm", rows)
    if isinstance(node, EqArray):
        rows = []
        for r in node.rows:
            parts = []
            for j, c in enumerate(r):
                if j:
                    parts.append(_r("&"))
                parts.append(_m(c))
            rows.append(_g("me", "".join(parts)))
        return _g("meqArr", "".join(rows))
    if isinstance(node, Accent):
        return _g("macc", _g("maccPr", _prop("chr", node.mark)), _e(node.body))
    if isinstance(node, Func):
        name = _r(node.name)
        if node.sub is not None and node.name in S.LIMIT_FUNCTIONS:
            name = _g("mlimLow", _g("me", name), _e(node.sub, "mlim"))
        elif node.sub is not None and node.sup is not None:
            name = _g("msSubSup", _g("me", name), _e(node.sub, "msub"), _e(node.sup, "msup"))
        elif node.sub is not None:
            name = _g("msSub", _g("me", name), _e(node.sub, "msub"))
        if node.sup is not None and not (node.sub is not None and
                                         node.name not in S.LIMIT_FUNCTIONS):
            name = _g("msSup", _g("me", name), _e(node.sup, "msup"))
        return _g("mfunc", _g("mfName", name), _e(node.arg))
    if isinstance(node, Limit):
        word = "mlimUpp" if node.above else "mlimLow"
        return _g(word, _e(node.base), _e(node.label, "mlim"))
    if isinstance(node, Brace):
        if node.mark in "⏞⏜⏟⏝":
            top = node.mark in "⏞⏜"
            grp = _g("mgroupChr", _g("mgroupChrPr", _prop("chr", node.mark),
                                     _prop("pos", "top" if top else "bot"),
                                     _prop("vertJc", "bot" if top else "top")),
                     _e(node.body))
            if node.label is not None:
                return _g("mlimUpp" if top else "mlimLow", _g("me", grp),
                          _e(node.label, "mlim"))
            return grp
        if node.mark in "¯▁":
            return _g("mbar", _g("mbarPr", _prop("pos", "top" if node.mark == "¯" else "bot")),
                      _e(node.body))
        if node.mark == "▭":
            return _g("mborderBox", _e(node.body))
        return _g("mbox", _e(node.body))
    return ""


def to_rtf(text, display=False):
    """Linear text -> an RTF document holding one equation."""
    body = _m(parse(text)) if text.strip() else _r("\u2b1a")
    math = "{\\mmath {\\*\\moMath " + body + "}}"
    if display:
        math = "{\\mmath {\\*\\moMathPara " + "{\\*\\moMath " + body + "}}}"
    return ("{\\rtf1\\ansi\\deff0{\\fonttbl{\\f0 Cambria Math;}}"
            "{\\mmathPr{\\mmathFont0}}" + math + "}")


# --------------------------------------------------------------- RTF -> tree
class _G:
    __slots__ = ("word", "arg", "kids", "wrpr", "mrpr")

    def __init__(self, word, arg=None):
        self.word, self.arg, self.kids = word, arg, []
        # an m:r's own formatting (w:rPr, m:rPr) as XML, kept for writing back
        self.wrpr = self.mrpr = None

    def find(self, word):
        for k in self.kids:
            if isinstance(k, _G) and k.word == word:
                return k
        return None

    def text(self):
        out = []
        for k in self.kids:
            if isinstance(k, str):
                out.append(k)
        return "".join(out)


_TOKEN = re.compile(r"\\u(-?\d+)\s?(\?|\\'[0-9a-fA-F]{2})?|\\'([0-9a-fA-F]{2})|"
                    r"\\([a-zA-Z]+)(-?\d+)?\s?|\\([\\{}*])|([{}])|([^\\{}]+)",
                    re.S)


def _tree(rtf):
    root = _G("root")
    stack = [root]
    pend = []      # pending UTF-16 surrogate
    for m in _TOKEN.finditer(rtf):
        u, _skip, hexch, word, num, esc, brace, text = m.groups()
        cur = stack[-1]
        if brace == "{":
            g = _G(None)
            cur.kids.append(g)
            stack.append(g)
        elif brace == "}":
            if len(stack) > 1:
                stack.pop()
        elif word is not None:
            if cur.word is None and not any(isinstance(k, (str, _G)) for k in cur.kids):
                cur.word, cur.arg = word, num
            elif cur.word is None:
                cur.word, cur.arg = word, num
            else:
                g = _G(word, num)   # inline control word (e.g. \par)
                cur.kids.append(g)
        elif u is not None:
            o = int(u)
            if o < 0:
                o += 65536
            if 0xD800 <= o < 0xDC00:
                pend.append(o)
                continue
            if 0xDC00 <= o < 0xE000 and pend:
                hi = pend.pop()
                o = 0x10000 + ((hi - 0xD800) << 10) + (o - 0xDC00)
            cur.kids.append(chr(o))
        elif hexch is not None:
            cur.kids.append(bytes([int(hexch, 16)]).decode("cp1252", "replace"))
        elif esc is not None:
            if esc != "*":
                cur.kids.append(esc)
        elif text is not None:
            t = text.replace("\r", "").replace("\n", "")
            if t:
                if cur.word in ("mr", "mchr", "mbegChr", "mendChr", "msepChr", "mtype",
                                "mpos", "mlimLoc", "mdegHide", "msubHide", "msupHide"):
                    t = t.lstrip(" ") if not cur.kids else t
                cur.kids.append(t)
    return root


def _collect(g, word, out):
    if not isinstance(g, _G):
        return
    if g.word == word:
        out.append(g)
        return
    for k in g.kids:
        _collect(k, word, out)


def _pv(g, prname, name, default=None):
    pr = g.find(prname)
    if pr is None:
        return default
    p = pr.find("m" + name)
    if p is None:
        return default
    return p.text().strip() if name not in ("chr", "begChr", "endChr", "sepChr") else p.text()


def _seq(g):
    """Children of an argument group -> node."""
    items = []
    if g is None:
        return Seq()
    for k in g.kids:
        if isinstance(k, _G):
            n = _node(k)
            if n is not None:
                if isinstance(n, Seq):
                    items.extend(n.items)
                else:
                    items.append(n)
    if len(items) == 1:
        return items[0]
    return Seq(items)


def _items(node):
    return node.items if isinstance(node, Seq) else [node]


def _run_atoms(text):
    """Split a math run into atoms the linear writer understands."""
    seq = parse(text) if text.strip() else Seq()
    return seq


def _keep_format(node, g):
    """Give the atoms a run made the run's formatting."""
    if g.wrpr is None and g.mrpr is None:
        return node
    stack = [node]
    while stack:
        n = stack.pop()
        if isinstance(n, Atom):
            n.wrpr, n.mrpr = g.wrpr, g.mrpr
        elif isinstance(n, Seq):
            stack.extend(n.items)
    return node


def _node(g):
    if g.word == "mr":
        return _keep_format(_node_inner(g), g)
    return _node_inner(g)


def _node_inner(g):
    w = g.word
    if w == "mr":
        pr = g.find("mrPr")
        txt = g.text()
        if pr is not None and pr.find("mnor") is not None:
            return Atom("text", txt)
        if txt == "\u2b1a":
            return Atom("placeholder", txt)
        if "&" in txt:
            out = []
            for i, part in enumerate(txt.split("&")):
                if i:
                    out.append(Atom("op", "&"))
                if part.strip():
                    out.extend(_items(_run_atoms(part)))
            return Seq(out)
        try:
            return _run_atoms(txt)
        except Exception:
            return Atom("text", txt)
    if w == "mf":
        t = _pv(g, "mfPr", "type", "bar")
        kind = {"lin": "linear", "noBar": "stack", "skw": "skew"}.get(t, "bar")
        return Frac(_seq(g.find("mnum")), _seq(g.find("mden")), kind)
    if w == "msSup":
        return Script(_seq(g.find("me")), None, _seq(g.find("msup")))
    if w == "msSub":
        return Script(_seq(g.find("me")), _seq(g.find("msub")), None)
    if w == "msSubSup":
        return Script(_seq(g.find("me")), _seq(g.find("msub")), _seq(g.find("msup")))
    if w == "msPre":
        return Script(_seq(g.find("me")), _seq(g.find("msub")), _seq(g.find("msup")), pre=True)
    if w == "mrad":
        hide = _pv(g, "mradPr", "degHide", "0") in ("1", "on", "true")
        deg = _seq(g.find("mdeg"))
        return Root(_seq(g.find("me")), None if hide or not _items(deg) else deg)
    if w == "mnary":
        op = _pv(g, "mnaryPr", "chr", "∫") or "∫"
        subh = _pv(g, "mnaryPr", "subHide", "0") in ("1", "on", "true")
        suph = _pv(g, "mnaryPr", "supHide", "0") in ("1", "on", "true")
        sub = None if subh else _seq(g.find("msub"))
        sup = None if suph else _seq(g.find("msup"))
        return Nary(op, sub if sub is None or _items(sub) else None,
                    sup if sup is None or _items(sup) else None, _seq(g.find("me")))
    if w == "md":
        beg = _pv(g, "mdPr", "begChr", "(")
        end = _pv(g, "mdPr", "endChr", ")")
        es = [k for k in g.kids if isinstance(k, _G) and k.word == "me"]
        sep = _pv(g, "mdPr", "sepChr", "|")
        body = Seq()
        for i, e in enumerate(es):
            if i:
                body.items.append(Atom("op", sep))
            body.items.extend(_items(_seq(e)))
        return Delim(beg if beg is not None else "", end if end is not None else "", body)
    if w == "mm":
        rows = []
        for r in g.kids:
            if isinstance(r, _G) and r.word == "mmr":
                rows.append([_seq(c) for c in r.kids if isinstance(c, _G) and c.word == "me"])
        return Matrix(rows)
    if w == "meqArr":
        rows = []
        for e in g.kids:
            if isinstance(e, _G) and e.word == "me":
                cells, cur = [], []
                for it in _items(_seq(e)):
                    if isinstance(it, Atom) and it.value == "&":
                        cells.append(Seq(cur))
                        cur = []
                    else:
                        cur.append(it)
                cells.append(Seq(cur))
                rows.append(cells)
        return EqArray(rows)
    if w == "macc":
        return Accent(_pv(g, "maccPr", "chr", "\u0302") or "\u0302", _seq(g.find("me")))
    if w == "mfunc":
        fn = g.find("mfName")
        name, sub, sup = "", None, None
        inner = [k for k in fn.kids if isinstance(k, _G)] if fn else []
        for k in inner:
            if k.word == "mr":
                name += k.text()
            elif k.word in ("mlimLow", "msSub", "msSup", "msSubSup"):
                e = k.find("me")
                name += "".join(x.text() for x in e.kids if isinstance(x, _G)) if e else ""
                if k.word == "mlimLow":
                    sub = _seq(k.find("mlim"))
                if k.word in ("msSub", "msSubSup"):
                    sub = _seq(k.find("msub"))
                if k.word in ("msSup", "msSubSup"):
                    sup = _seq(k.find("msup"))
        return Func(name.strip(), sub, sup, _seq(g.find("me")))
    if w in ("mlimLow", "mlimUpp"):
        base = g.find("me")
        lab = _seq(g.find("mlim"))
        inner = [k for k in base.kids if isinstance(k, _G)] if base else []
        if len(inner) == 1 and inner[0].word == "mgroupChr":
            br = _node(inner[0])
            br.label = lab
            return br
        return Limit(_seq(base), lab, w == "mlimUpp")
    if w == "mgroupChr":
        ch = _pv(g, "mgroupChrPr", "chr", "⏟") or "⏟"
        return Brace(ch, _seq(g.find("me")))
    if w == "mbar":
        pos = _pv(g, "mbarPr", "pos", "bot")
        return Brace("¯" if pos == "top" else "▁", _seq(g.find("me")))
    if w == "mborderBox":
        return Brace("▭", _seq(g.find("me")))
    if w == "mbox":
        return Brace("□", _seq(g.find("me")))
    if w in ("moMath", "moMathPara", "mmath", "me"):
        return _seq(g)
    return None


def from_rtf(rtf):
    """Linear text of the first equation in an RTF fragment, or None."""
    root = _tree(rtf)
    found = []
    _collect(root, "moMath", found)
    if not found:
        return None
    try:
        return to_linear(_seq(found[0]))
    except Exception:
        return None


def has_math(rtf):
    return "\\moMath" in rtf


# --------------------------------------------------------------- OOXML (.docx)
M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _xml_tree(el):
    """An m: element as the same group tree the RTF reader builds."""
    tag = el.tag
    ns, _, local = tag[1:].partition("}") if tag.startswith("{") else ("", "", tag)
    if ns != M_NS:
        g = _G(None)
        return g
    g = _G("m" + local)
    if local == "r":
        import xml.etree.ElementTree as ET
        import re as _re
        ET.register_namespace("w", W_NS)
        ET.register_namespace("m", M_NS)

        def xml_of(e):
            t = ET.tostring(e, encoding="unicode")
            return _re.sub(r' xmlns:[a-z]+="[^"]*"', "", t)
        w_rpr = el.find("{%s}rPr" % W_NS)
        m_rpr = el.find("{%s}rPr" % M_NS)
        if w_rpr is not None:
            g.wrpr = xml_of(w_rpr)
        if m_rpr is not None and len(m_rpr):
            g.mrpr = xml_of(m_rpr)
    val = el.get("{%s}val" % M_NS)
    if val is not None:
        g.kids.append(val)
    if local == "t":
        return el.text or ""
    for k in el:
        kns = k.tag[1:].partition("}")[0] if k.tag.startswith("{") else ""
        if kns == M_NS:
            sub = _xml_tree(k)
            if isinstance(sub, str):
                g.kids.append(sub)
            else:
                g.kids.append(sub)
        elif k.tag == "{%s}r" % W_NS or kns == W_NS:
            # text in a w:r inside math (rare)
            t = "".join(x.text or "" for x in k.iter("{%s}t" % W_NS))
            if t:
                g.kids.append(t)
    return g


def omath_linear(el):
    """Linear text of an m:oMath element, or None."""
    try:
        return to_linear(_seq(_xml_tree(el)))
    except Exception as e:
        print("omml:", e)
        return None


def docx_equations(path):
    """Linear text of every m:oMath in a .docx body, in document order."""
    import zipfile
    import xml.etree.ElementTree as ET
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    out = []
    for el in root.iter("{%s}oMath" % M_NS):
        out.append(omath_linear(el))
    return out


# --------------------------------------------------------------- tree -> OMML XML
def _xesc(text):
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def _xg(word, *parts):
    body = "".join(parts)
    return "<m:%s>%s</m:%s>" % (word, body, word) if body else "<m:%s/>" % word


def _xprop(name, value):
    return '<m:%s m:val="%s"/>' % (name, _xesc(value))


MATH_RPR = '<w:rPr><w:rFonts w:ascii="Cambria Math" w:hAnsi="Cambria Math"/></w:rPr>'


def _xr(text, normal=False, upright=False, atom=None):
    if not text:
        return ""
    pr = ""
    wrpr = getattr(atom, "wrpr", None) or MATH_RPR
    mrpr = getattr(atom, "mrpr", None)
    if mrpr:
        sp = ' xml:space="preserve"' if text != text.strip() else ""
        return "<m:r>%s%s<m:t%s>%s</m:t></m:r>" % (mrpr, wrpr, sp, _xesc(text))
    if normal:
        pr = "<m:rPr><m:nor/></m:rPr>"
    elif upright:
        pr = '<m:rPr><m:sty m:val="p"/></m:rPr>'
    sp = ' xml:space="preserve"' if text != text.strip() else ""
    return "<m:r>%s%s<m:t%s>%s</m:t></m:r>" % (pr, wrpr, sp, _xesc(text))


def _xe(node, word="e"):
    return "<m:%s>%s</m:%s>" % (word, _x(node), word)


def _x(node):
    if node is None:
        return ""
    if isinstance(node, Seq):
        return "".join(_x(i) for i in node.items)
    if isinstance(node, Atom):
        k, v = node.kind, node.value
        if k == "text":
            return _xr(v, normal=True, atom=node)
        if k == "placeholder":
            return ""
        if k == "fn":
            return _xr(v, upright=True, atom=node)
        return _xr(v, atom=node)
    if isinstance(node, Frac):
        pr = ""
        t = {"linear": "lin", "stack": "noBar", "skew": "skw"}.get(node.kind)
        if t:
            pr = _xg("fPr", _xprop("type", t))
        return _xg("f", pr, _xe(node.num, "num"), _xe(node.den, "den"))
    if isinstance(node, Script):
        if node.pre:
            return _xg("sPre", _xe(node.sub, "sub"), _xe(node.sup, "sup"), _xe(node.base))
        if node.sub is not None and node.sup is not None:
            return _xg("sSubSup", _xe(node.base), _xe(node.sub, "sub"), _xe(node.sup, "sup"))
        if node.sub is not None:
            return _xg("sSub", _xe(node.base), _xe(node.sub, "sub"))
        return _xg("sSup", _xe(node.base), _xe(node.sup, "sup"))
    if isinstance(node, Prime):
        return _xg("sSup", _xe(node.base), "<m:sup>%s</m:sup>" % _xr("′" * node.count))
    if isinstance(node, Fact):
        return _x(node.base) + _xr("!")
    if isinstance(node, Root):
        if node.index is None:
            return _xg("rad", _xg("radPr", _xprop("degHide", "1")), "<m:deg/>", _xe(node.body))
        return _xg("rad", _xe(node.index, "deg"), _xe(node.body))
    if isinstance(node, Nary):
        pr = _xprop("chr", node.op)
        pr += _xprop("limLoc", "subSup" if node.op in "∫∬∭∮∯∰" else "undOvr")
        if node.sub is None:
            pr += _xprop("subHide", "1")
        if node.sup is None:
            pr += _xprop("supHide", "1")
        return _xg("nary", _xg("naryPr", pr), _xe(node.sub, "sub"), _xe(node.sup, "sup"),
                   _xe(node.body))
    if isinstance(node, Delim):
        pr = ""
        if not (node.open == "(" and node.close == ")"):
            pr = _xg("dPr", _xprop("begChr", node.open), _xprop("endChr", node.close))
        return _xg("d", pr, _xe(node.body))
    if isinstance(node, Matrix):
        rows = "".join("<m:mr>%s</m:mr>" % "".join(_xe(c) for c in r) for r in node.rows)
        return _xg("m", rows)
    if isinstance(node, EqArray):
        rows = []
        for r in node.rows:
            parts = []
            for j, c in enumerate(r):
                if j:
                    parts.append(_xr("&"))
                parts.append(_x(c))
            rows.append("<m:e>%s</m:e>" % "".join(parts))
        return _xg("eqArr", "".join(rows))
    if isinstance(node, Accent):
        return _xg("acc", _xg("accPr", _xprop("chr", node.mark)), _xe(node.body))
    if isinstance(node, Func):
        name = _xr(node.name, upright=True)
        if node.sub is not None and node.name in S.LIMIT_FUNCTIONS:
            name = _xg("limLow", "<m:e>%s</m:e>" % name, _xe(node.sub, "lim"))
        elif node.sub is not None and node.sup is not None:
            name = _xg("sSubSup", "<m:e>%s</m:e>" % name, _xe(node.sub, "sub"), _xe(node.sup, "sup"))
        elif node.sub is not None:
            name = _xg("sSub", "<m:e>%s</m:e>" % name, _xe(node.sub, "sub"))
        if node.sup is not None and not (node.sub is not None and
                                         node.name not in S.LIMIT_FUNCTIONS):
            name = _xg("sSup", "<m:e>%s</m:e>" % name, _xe(node.sup, "sup"))
        return _xg("func", "<m:fName>%s</m:fName>" % name, _xe(node.arg))
    if isinstance(node, Limit):
        return _xg("limUpp" if node.above else "limLow", _xe(node.base), _xe(node.label, "lim"))
    if isinstance(node, Brace):
        if node.mark in "⏞⏜⏟⏝":
            top = node.mark in "⏞⏜"
            grp = _xg("groupChr", _xg("groupChrPr", _xprop("chr", node.mark),
                                      _xprop("pos", "top" if top else "bot"),
                                      _xprop("vertJc", "bot" if top else "top")), _xe(node.body))
            if node.label is not None:
                return _xg("limUpp" if top else "limLow", "<m:e>%s</m:e>" % grp,
                           _xe(node.label, "lim"))
            return grp
        if node.mark in "¯▁":
            return _xg("bar", _xg("barPr", _xprop("pos", "top" if node.mark == "¯" else "bot")),
                       _xe(node.body))
        if node.mark == "▭":
            return _xg("borderBox", _xe(node.body))
        return _xg("box", _xe(node.body))
    return ""


def to_omml(tree):
    """A parser tree (eqn.model.export) -> an m:oMath element (XML text)."""
    return '<m:oMath xmlns:m="%s" xmlns:w="%s">%s</m:oMath>' % (M_NS, W_NS, _x(tree))


def from_omml(xml):
    """An m:oMath element (XML text) -> parser tree."""
    import xml.etree.ElementTree as ET
    el = ET.fromstring(xml)
    return _seq(_xml_tree(el))
