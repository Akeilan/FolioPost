"""The editable equation tree used by the in-place equation editor.

It is the linear-format parse tree (eqn.unicodemath) brought into a regular
shape: every argument of a structure is a Seq ("slot") whose items are
single-character atoms or further structures, and an empty Seq is an empty
slot (a dotted box). export() turns it back into the parser's own shape, so
the existing converters write the formula markup and the linear text.
"""
import copy

from . import symbols as S
from . import unicodemath as U
from .unicodemath import (Accent, Atom, Brace, Delim, EqArray, Fact, Frac, Func, Limit,
                          Matrix, Nary, Prime, Root, Script, Seq)

# slot attributes per structure, in the order the caret visits them
SLOTS = {
    Frac: ("num", "den"),
    Script: ("base", "sub", "sup"),
    Root: ("index", "body"),
    Nary: ("sub", "sup", "body"),
    Delim: ("body",),
    Accent: ("body",),
    Func: ("name", "sub", "sup", "arg"),
    Limit: ("base", "label"),
    Brace: ("body", "label"),
    Prime: ("base",),
    Fact: ("base",),
}


def is_struct(node):
    return not isinstance(node, (Atom, Seq))


def slots(node):
    """The node's slots (Seqs) in caret order."""
    if isinstance(node, (Matrix, EqArray)):
        return [c for row in node.rows for c in row]
    out = []
    for a in SLOTS.get(type(node), ()):
        v = getattr(node, a, None)
        if isinstance(v, Seq):
            out.append(v)
    return out


# ---------------------------------------------------------------- normalize
def _fmt(src, dst):
    """Carry a run's formatting (from the document) over to a new atom."""
    for a in ("wrpr", "mrpr"):
        v = getattr(src, a, None)
        if v is not None:
            setattr(dst, a, v)
    return dst


def _atoms(atom):
    if atom.kind == "placeholder":
        return [Atom("placeholder", "")]
    if atom.kind in ("ident", "num", "text") and len(atom.value) > 1:
        return [_fmt(atom, Atom(atom.kind, ch)) for ch in atom.value]
    return [_fmt(atom, Atom(atom.kind, atom.value))]


def items_of(node):
    """A node as a flat list of slot items."""
    if node is None:
        return []
    if isinstance(node, Seq):
        out = []
        for it in node.items:
            out.extend(items_of(it))
        return out
    if isinstance(node, Atom):
        return _atoms(node)
    return [norm(node)]


def slot(node):
    items = items_of(node)
    if all(isinstance(i, Atom) and i.kind == "placeholder" for i in items):
        items = []
    return Seq(items)


def opt(node):
    return None if node is None else slot(node)


def norm(node):
    """A parser node (structure) in editable shape."""
    if isinstance(node, Frac):
        return Frac(slot(node.num), slot(node.den), node.kind)
    if isinstance(node, Script):
        return Script(slot(node.base), opt(node.sub), opt(node.sup), node.pre)
    if isinstance(node, Root):
        return Root(slot(node.body), opt(node.index))
    if isinstance(node, Nary):
        return Nary(node.op, opt(node.sub), opt(node.sup), slot(node.body))
    if isinstance(node, Delim):
        return Delim(node.open, node.close, slot(node.body))
    if isinstance(node, Matrix):
        return Matrix([[slot(c) for c in row] for row in node.rows])
    if isinstance(node, EqArray):
        return EqArray([[slot(c) for c in row] for row in node.rows])
    if isinstance(node, Accent):
        return Accent(node.mark, slot(node.body))
    if isinstance(node, Func):
        name = Seq([Atom("fn", ch) for ch in (node.name or "")])
        arg = slot(node.arg)
        # "lim┬(n→∞)" style limits come out of the parser as a limit on
        # an empty base: show them as the function's lower limit
        if node.sub is None and len(arg.items) >= 1 and isinstance(arg.items[0], Limit) \
                and not arg.items[0].base.items:
            lim = arg.items.pop(0)
            return Func(name, lim.label, opt(node.sup), arg)
        return Func(name, opt(node.sub), opt(node.sup), arg)
    if isinstance(node, Limit):
        return Limit(slot(node.base), slot(node.label), node.above)
    if isinstance(node, Brace):
        return Brace(node.mark, slot(node.body), opt(node.label))
    if isinstance(node, Prime):
        return Prime(slot(node.base), node.count)
    if isinstance(node, Fact):
        return Fact(slot(node.base))
    if isinstance(node, Seq):
        return slot(node)
    return node


def from_linear(text):
    """Linear (UnicodeMath) text -> editable Seq. Raises U.ParseError."""
    if not text.strip():
        return Seq([])
    return slot(U.parse(text))


def from_starmath(markup):
    from . import starmath
    return from_linear(starmath.to_linear_text(markup))


# ---------------------------------------------------------------- export
_MERGE = ("ident", "num", "text")


def _ex_seq(seq, unwrap=True):
    items = []
    for it in seq.items:
        if isinstance(it, Atom):
            if it.kind == "fn":
                it = Atom("ident", it.value)
            same_fmt = getattr(items[-1], "wrpr", None) == getattr(it, "wrpr", None) and \
                getattr(items[-1], "mrpr", None) == getattr(it, "mrpr", None) if items else False
            if items and isinstance(items[-1], Atom) and items[-1].kind == it.kind and \
                    it.kind in _MERGE and same_fmt and not (it.kind == "ident" and _breaks(items[-1], it)):
                items[-1] = _fmt(it, Atom(it.kind, items[-1].value + it.value))
                continue
            items.append(_fmt(it, Atom(it.kind, it.value)))
        else:
            items.append(export(it))
    if not items:
        return Atom("placeholder", "")
    if unwrap and len(items) == 1:
        return items[0]
    return Seq(items)


def _breaks(a, b):
    # keep single Greek letters apart so the engine sees %alpha %beta
    return a.value[-1] in S.GREEK_NAMES or b.value in S.GREEK_NAMES


def _ex_opt(seq):
    return None if seq is None else _ex_seq(seq)


def export(node):
    """Editable tree -> parser tree (for the markup and linear writers)."""
    if isinstance(node, Seq):
        return _ex_seq(node, unwrap=False)
    if isinstance(node, Frac):
        return Frac(_ex_seq(node.num), _ex_seq(node.den), node.kind)
    if isinstance(node, Script):
        return Script(_ex_seq(node.base), _ex_opt(node.sub), _ex_opt(node.sup), node.pre)
    if isinstance(node, Root):
        return Root(_ex_seq(node.body), _ex_opt(node.index))
    if isinstance(node, Nary):
        return Nary(node.op, _ex_opt(node.sub), _ex_opt(node.sup), _ex_seq(node.body))
    if isinstance(node, Delim):
        return Delim(node.open, node.close, _ex_seq(node.body, unwrap=False))
    if isinstance(node, Matrix):
        return Matrix([[_ex_seq(c) for c in row] for row in node.rows])
    if isinstance(node, EqArray):
        return EqArray([[_ex_seq(c) for c in row] for row in node.rows])
    if isinstance(node, Accent):
        return Accent(node.mark, _ex_seq(node.body))
    if isinstance(node, Func):
        name = "".join(a.value for a in node.name.items if isinstance(a, Atom)) or "f"
        return Func(name, _ex_opt(node.sub), _ex_opt(node.sup), _ex_seq(node.arg))
    if isinstance(node, Limit):
        return Limit(_ex_seq(node.base), _ex_seq(node.label), node.above)
    if isinstance(node, Brace):
        return Brace(node.mark, _ex_seq(node.body), _ex_opt(node.label))
    if isinstance(node, Prime):
        return Prime(_ex_seq(node.base), node.count)
    if isinstance(node, Fact):
        return Fact(_ex_seq(node.base))
    return node


def to_linear(seq):
    return U.to_linear(export(seq))


def raw_linear(items):
    """Linear text of slot items for re-parsing during build-up: atoms
    exactly as typed, structures fenced in invisible brackets 〖〗."""
    out = []
    text = []

    def flush():
        if text:
            out.append('"' + "".join(text) + '"')
            del text[:]
    for it in items:
        if isinstance(it, Atom):
            if it.kind == "text":
                text.append(it.value)
                continue
            flush()
            out.append("⬚" if it.kind == "placeholder" else it.value)
        else:
            flush()
            out.append("〖" + U.to_linear(export(it)) + "〗")
    flush()
    return "".join(out)


def unfence(seq):
    """Undo raw_linear's fences after parsing."""
    out = []
    for it in seq.items:
        if isinstance(it, Delim) and it.open == "" and it.close == "" and \
                len(it.body.items) == 1 and is_struct(it.body.items[0]):
            it = it.body.items[0]
        if is_struct(it):
            for s in slots(it):
                s.items[:] = unfence(s).items
        out.append(it)
    return Seq(out)


def to_starmath(seq):
    if not seq.items:
        return "<?>"
    return U._sm(export(seq)).strip() or "<?>"


# ---------------------------------------------------------------- LaTeX
_TEX_ACC = {"̂": "hat", "̌": "check", "̃": "tilde", "́": "acute", "̀": "grave",
            "̇": "dot", "̈": "ddot", "⃛": "dddot", "̅": "overline", "̄": "bar",
            "̿": "overline", "⃗": "vec", "̆": "breve", "⃑": "vec", "⃡": "overleftrightarrow"}
_TEX_NARY = {"∑": "sum", "∏": "prod", "∐": "coprod", "∫": "int", "∬": "iint",
             "∭": "iiint", "∮": "oint", "⋃": "bigcup", "⋂": "bigcap", "⋁": "bigvee",
             "⋀": "bigwedge"}
_TEX_BR = {"{": "\\{", "}": "\\}", "⟨": "\\langle", "⟩": "\\rangle", "⌊": "\\lfloor",
           "⌋": "\\rfloor", "⌈": "\\lceil", "⌉": "\\rceil", "‖": "\\|", "": "."}


def _tex_char(ch):
    for name, sym in S.CONTROL_WORDS.items():
        if sym == ch and len(name) > 1 and name.isalpha():
            return "\\" + name + " "
    return {"{": "\\{", "}": "\\}", "%": "\\%", "&": "\\&", "#": "\\#"}.get(ch, ch)


def _tex_seq(seq):
    out = []
    text = []

    def flush():
        if text:
            out.append("\\text{" + "".join(text) + "}")
            del text[:]
    for it in seq.items:
        if isinstance(it, Atom) and it.kind == "text":
            text.append(it.value)
            continue
        flush()
        out.append(_tex(it))
    flush()
    s = "".join(out)
    return s.strip()


def _g(seq):
    s = _tex_seq(seq) if seq is not None else ""
    if len(s) == 1:
        return s
    return "{" + s + "}"


def _tex(node):
    if isinstance(node, Seq):
        return _tex_seq(node)
    if isinstance(node, Atom):
        return _tex_char(node.value) if node.kind not in ("num",) else node.value
    if isinstance(node, Frac):
        if node.kind == "linear":
            return _g(node.num) + "/" + _g(node.den)
        if node.kind == "stack":
            return "\\genfrac{}{}{0pt}{}" + _g(node.num) + _g(node.den)
        if node.kind == "skew":
            return "{}^{" + _tex_seq(node.num) + "}\\!/_{" + _tex_seq(node.den) + "}"
        return "\\frac" + _g(node.num) + _g(node.den)
    if isinstance(node, Script) and node.pre:
        s = "{}"
        if node.sub is not None:
            s += "_" + _g(node.sub)
        if node.sup is not None:
            s += "^" + _g(node.sup)
        return s + _g(node.base)
    if isinstance(node, Script):
        s = _g(node.base)
        if node.sub is not None:
            s += "_" + _g(node.sub)
        if node.sup is not None:
            s += "^" + _g(node.sup)
        return s
    if isinstance(node, Root):
        if node.index is not None:
            return "\\sqrt[" + _tex_seq(node.index) + "]" + _g(node.body)
        return "\\sqrt" + _g(node.body)
    if isinstance(node, Nary):
        s = "\\" + _TEX_NARY.get(node.op, "sum")
        if node.sub is not None:
            s += "_" + _g(node.sub)
        if node.sup is not None:
            s += "^" + _g(node.sup)
        return s + " " + _tex_seq(node.body)
    if isinstance(node, Delim):
        return "\\left" + _TEX_BR.get(node.open, node.open) + _tex_seq(node.body) + \
            "\\right" + _TEX_BR.get(node.close, node.close)
    if isinstance(node, (Matrix, EqArray)):
        env = "matrix" if isinstance(node, Matrix) else "aligned"
        rows = " \\\\ ".join(" & ".join(_tex_seq(c) for c in r) for r in node.rows)
        return "\\begin{" + env + "}" + rows + "\\end{" + env + "}"
    if isinstance(node, Accent):
        return "\\" + _TEX_ACC.get(node.mark, "hat") + _g(node.body)
    if isinstance(node, Func):
        name = "".join(a.value for a in node.name.items)
        s = "\\" + name if name in S.FUNCTIONS else "\\operatorname{" + name + "}"
        if node.sub is not None:
            s += "_" + _g(node.sub)
        if node.sup is not None:
            s += "^" + _g(node.sup)
        return s + " " + _tex_seq(node.arg)
    if isinstance(node, Limit):
        return ("\\overset" if node.above else "\\underset") + _g(node.label) + _g(node.base)
    if isinstance(node, Brace):
        kw = {"⏞": "overbrace", "⏟": "underbrace", "⏜": "overparen", "⏝": "underparen",
              "¯": "overline", "▁": "underline", "□": "boxed", "▭": "boxed"}.get(node.mark,
                                                                                  "boxed")
        s = "\\" + kw + _g(node.body)
        if node.label is not None:
            s += ("^" if node.mark in "⏞⏜" else "_") + _g(node.label)
        return s
    if isinstance(node, Prime):
        return _g(node.base) + "'" * node.count
    if isinstance(node, Fact):
        return _g(node.base) + "!"
    return ""


def to_latex(seq):
    return _tex_seq(seq)


def from_latex(text):
    from . import latex
    return from_linear(latex.to_linear(text))


# ---------------------------------------------------------------- helpers
def deep(seq):
    return copy.deepcopy(seq)


def is_empty(seq):
    return seq is None or not seq.items


def parents(root):
    """{id(seq): (node, owner_seq)} for every slot below root."""
    out = {}

    def walk(seq):
        for it in seq.items:
            if is_struct(it):
                for s in slots(it):
                    out[id(s)] = (it, seq)
                    walk(s)
    walk(root)
    return out


def first_slot(node):
    """Where the caret goes when entering a structure from the left."""
    ss = slots(node)
    return ss[0] if ss else None


def last_slot(node):
    ss = slots(node)
    return ss[-1] if ss else None


def first_empty(seq):
    """The first empty slot inside seq's items (depth first), or None."""
    for it in seq.items:
        if is_struct(it):
            for s in slots(it):
                if not s.items:
                    return s
                r = first_empty(s)
                if r is not None:
                    return r
    return None
