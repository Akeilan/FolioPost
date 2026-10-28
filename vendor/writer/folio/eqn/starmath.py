"""Formula-engine markup -> linear text, so existing equations (from .docx
files or older documents) can be edited in the equation bar."""
from . import symbols as S
from .unicodemath import (Seq, Atom, Frac, Script, Root, Nary, Delim, Matrix,
                          EqArray, Accent, Func, Limit, Brace, Fact, to_linear)

REL = {
    "=": "=", "<": "<", ">": ">", "<=": "≤", ">=": "≥", "<>": "≠", "lt": "<",
    "gt": ">", "le": "≤", "ge": "≥", "leslant": "≤", "geslant": "≥",
    "neq": "≠", "approx": "≈", "sim": "∼", "simeq": "≃", "equiv": "≡",
    "prop": "∝", "parallel": "∥", "ortho": "⊥", "divides": "∣",
    "ndivides": "∤", "toward": "→", "dlarrow": "⇐", "dlrarrow": "⇔",
    "drarrow": "⇒", "def": "≝", "in": "∈", "notin": "∉", "owns": "∋",
    "ni": "∋", "subset": "⊂", "supset": "⊃", "subseteq": "⊆",
    "supseteq": "⊇", "nsubset": "⊄", "nsupset": "⊅", "nsubseteq": "⊈",
    "nsupseteq": "⊉", "ll": "≪", "gg": "≫", "<<": "≪", ">>": "≫",
    "prec": "≺", "succ": "≻", "preccurlyeq": "⪯", "succcurlyeq": "⪰",
    "precsim": "≾", "succsim": "≿", "nprec": "⊀", "nsucc": "⊁",
    "transl": "⊷", "transr": "⊶",
}
SUMOP = {"+": "+", "-": "-", "+-": "±", "-+": "∓", "plusminus": "±",
         "minusplus": "∓", "or": "∨", "circ": "∘", "union": "∪",
         "setminus": "∖", "bslash": "∖", "oplus": "⊕", "ominus": "⊖"}
PRODOP = {"*": "∗", "cdot": "⋅", "times": "×", "div": "÷", "and": "∧",
          "intersection": "∩", "otimes": "⊗", "odot": "⊙", "odivide": "⊘",
          "/": "/", "slash": "/"}
SYMS = {
    "infinity": "∞", "infty": "∞", "partial": "∂", "nabla": "∇",
    "exists": "∃", "notexists": "∄", "forall": "∀", "emptyset": "∅",
    "aleph": "ℵ", "wp": "℘", "re": "ℜ", "im": "ℑ", "hbar": "ℏ",
    "lambdabar": "ƛ", "setn": "ℕ", "setz": "ℤ", "setq": "ℚ", "setr": "ℝ",
    "setc": "ℂ", "dotsaxis": "⋯", "dotslow": "…", "dotsvert": "⋮",
    "dotsdown": "⋱", "dotsup": "⋰", "dotsdiag": "⋰", "backepsilon": "∍",
    "leftarrow": "←", "rightarrow": "→", "uparrow": "↑", "downarrow": "↓",
    "neg": "¬", "mline": "|",
}
NARYKW = {"sum": "∑", "prod": "∏", "coprod": "∐", "int": "∫", "iint": "∬",
          "iiint": "∭", "lint": "∮", "llint": "∯", "lllint": "∰",
          "union": "⋃", "intersection": "⋂", "intd": "∫"}
ACC = {}
for _mark, _kw in S.ACCENTS.items():
    ACC.setdefault(_kw, _mark)
for _wide, _narrow in S.NARROW_ACCENT.items():
    ACC.setdefault(_narrow, ACC[_wide])
ACC["overline"] = "̅"
ACC["bar"] = "̄"
LBR = {"(": "(", "[": "[", "lbrace": "{", "langle": "⟨", "lceil": "⌈",
       "lfloor": "⌊", "lline": "|", "ldline": "‖", "ldbracket": "⟦",
       "none": "", "{": "{"}
RBR = {")": ")", "]": "]", "rbrace": "}", "rangle": "⟩", "rceil": "⌉",
       "rfloor": "⌋", "rline": "|", "rdline": "‖", "rdbracket": "⟧",
       "none": "", "}": "}"}
ATTR1 = {"bold", "ital", "italic", "nbold", "nitalic", "phantom", "overstrike",
         "sans", "serif", "fixed"}
ATTR2 = {"color", "size", "font"}
GREEK = {}
for _ch, _name in S.GREEK_NAMES.items():
    GREEK[_name] = _ch
    GREEK["i" + _name] = _ch
FUNC_NATIVE = {"sin", "cos", "tan", "cot", "sinh", "cosh", "tanh", "coth",
               "arcsin", "arccos", "arctan", "arccot", "arsinh", "arcosh",
               "artanh", "arcoth", "log", "ln", "exp", "lim", "liminf",
               "limsup"}


class Tok:
    __slots__ = ("kind", "value")

    def __init__(self, kind, value):
        self.kind, self.value = kind, value

    def __repr__(self):
        return "%s:%r" % (self.kind, self.value)


MULTI = ["<?>", "##", "<<", ">>", "<=", ">=", "<>", "+-", "-+"]


def tokenize(src):
    toks = []
    i, n = 0, len(src)
    while i < n:
        ch = src[i]
        if ch.isspace():
            i += 1
            continue
        if ch == '"':
            j = i + 1
            buf = []
            while j < n and src[j] != '"':
                if src[j] == "\\" and j + 1 < n:
                    j += 1
                buf.append(src[j])
                j += 1
            toks.append(Tok("text", "".join(buf)))
            i = j + 1
            continue
        if ch == "%":
            j = i + 1
            while j < n and src[j].isalnum():
                j += 1
            toks.append(Tok("greek", src[i + 1:j]))
            i = j
            continue
        if ch.isdigit() or (ch == "." and i + 1 < n and src[i + 1].isdigit()):
            j = i
            while j < n and (src[j].isdigit() or src[j] in ".,"):
                if src[j] == "," and not (j + 1 < n and src[j + 1].isdigit()):
                    break
                j += 1
            toks.append(Tok("num", src[i:j]))
            i = j
            continue
        if ch.isalpha():
            j = i
            while j < n and src[j].isalnum():
                j += 1
            toks.append(Tok("word", src[i:j]))
            i = j
            continue
        for m in MULTI:
            if src.startswith(m, i):
                toks.append(Tok("op", m))
                i += len(m)
                break
        else:
            toks.append(Tok("op", ch))
            i += 1
    return toks


class P:
    def __init__(self, toks):
        self.t = toks
        self.i = 0
        self.saw_align = False

    def peek(self, k=0):
        j = self.i + k
        return self.t[j] if j < len(self.t) else None

    def next(self):
        t = self.peek()
        self.i += 1
        return t

    def is_word(self, *words):
        t = self.peek()
        return t is not None and t.kind == "word" and t.value.lower() in words

    def is_op(self, *ops):
        t = self.peek()
        return t is not None and t.kind == "op" and t.value in ops

    def stop(self):
        t = self.peek()
        if t is None:
            return True
        if t.kind == "op" and t.value in ("}", "#", "##"):
            return True
        if t.kind == "word" and t.value.lower() in ("right", "newline", "from",
                                                   "to"):
            return True
        if t.kind == "op" and t.value in (")", "]"):
            return True
        if t.kind == "word" and t.value.lower() in RBR and t.value.lower() != "none":
            return True
        return False

    # Expression := Relation {Relation}
    def expression(self):
        rows = [[]]
        while not self.stop() or self.is_word("newline"):
            if self.is_word("newline"):
                self.i += 1
                rows.append([])
                continue
            start = self.i
            rows[-1].append(self.relation())
            if self.i == start:
                self.i += 1
        if len(rows) > 1:
            return EqArray([[_seq(r)] for r in rows])
        return _seq(rows[0])

    def relation(self):
        items = [self.sum()]
        while True:
            t = self.peek()
            if t is None:
                break
            key = t.value if t.kind == "op" else t.value.lower() if t.kind == "word" else None
            if key in REL:
                self.i += 1
                op = Atom("op", REL[key])
                if self.is_word("csup", "csub"):
                    above = self.next().value.lower() == "csup"
                    op = Limit(op, self.term(), above)
                items.append(op)
                if not self.stop():
                    items.append(self.sum())
            else:
                break
        return _seq(items)

    def sum(self):
        items = []
        t = self.peek()
        if t is not None and t.kind == "op" and t.value in ("+", "-", "+-", "-+"):
            self.i += 1
            items.append(Atom("op", SUMOP[t.value]))
        elif self.is_word("plusminus", "minusplus", "neg"):
            w = self.next().value.lower()
            items.append(Atom("op", SUMOP.get(w, "¬")))
        items.append(self.product())
        while True:
            t = self.peek()
            if t is None:
                break
            key = t.value if t.kind == "op" else t.value.lower() if t.kind == "word" else None
            if key in SUMOP and not (key == "union" and self._nary_follows()):
                self.i += 1
                items.append(Atom("op", SUMOP[key]))
                items.append(self.product())
            else:
                break
        return _seq(items)

    def _nary_follows(self):
        return False

    def product(self):
        node = self.power()
        while True:
            t = self.peek()
            if t is None:
                break
            key = t.value if t.kind == "op" else t.value.lower() if t.kind == "word" else None
            if key == "over":
                self.i += 1
                node = Frac(node, self.power())
            elif key in ("wideslash",):
                self.i += 1
                node = Frac(node, self.power(), "skew")
            elif key in ("overbrace", "underbrace"):
                self.i += 1
                label = self.power()
                node = Brace("⏞" if key == "overbrace" else "⏟", node, label)
            elif key in PRODOP and key not in ("/",):
                self.i += 1
                node = _seq([node, Atom("op", PRODOP[key]), self.power()])
            elif key == "/":
                self.i += 1
                node = Frac(node, self.power(), "linear")
            else:
                break
        return node

    def power(self):
        node = self.term()
        sub = sup = None
        pre = False
        while True:
            t = self.peek()
            if t is None:
                break
            key = t.value if t.kind == "op" else t.value.lower() if t.kind == "word" else None
            if key in ("_", "rsub", "sub", "lsub"):
                self.i += 1
                pre = key == "lsub"
                sub = self.term()
            elif key in ("^", "rsup", "sup", "lsup"):
                self.i += 1
                pre = key == "lsup"
                sup = self.term()
            elif key in ("csub", "csup"):
                self.i += 1
                label = self.term()
                base = node
                if isinstance(base, Seq) and len(base.items) == 1:
                    base = base.items[0]
                if isinstance(base, Func) and key == "csub" and base.sub is None \
                        and sub is None and sup is None:
                    base.sub = label
                    node = base
                    continue
                if sub is not None or sup is not None:
                    node = Script(node, sub, sup)
                    sub = sup = None
                node = Limit(node, label, key == "csup")
            else:
                break
        if sup is not None and sub is None and isinstance(sup, Atom) and \
                sup.kind == "text" and sup.value and set(sup.value) <= set("′″‴'"):
            from .unicodemath import Prime
            return Prime(node, sum({"′": 1, "″": 2, "‴": 3, "'": 1}[c] for c in sup.value))
        if sub is not None or sup is not None:
            if isinstance(node, Func) and node.sub is None and node.sup is None:
                node.sub, node.sup = sub, sup
                return node
            return Script(node, sub, sup, pre)
        return node

    def group(self):
        """{ ... }"""
        self.i += 1
        node = self.expression()
        if self.is_op("}"):
            self.i += 1
        return node

    def operand(self):
        """The operand of a prefix keyword: a power-level item."""
        return self.power()

    def term(self):
        t = self.peek()
        if t is None:
            return Atom("placeholder", "")
        if t.kind == "op":
            v = t.value
            if v == "{":
                return self.group()
            if v == "<?>":
                self.i += 1
                return Atom("placeholder", "")
            if v in ("(", "["):
                self.i += 1
                body = self.expression()
                close = ""
                if self.is_op(")", "]"):
                    close = self.next().value
                return Delim(v, close, body)
            if v in ("`", "~"):
                self.i += 1
                return Atom("space", " " if v == "`" else " ")
            if v in ("+", "-", "+-", "-+"):
                self.i += 1
                return _seq([Atom("op", SUMOP[v]), self.power()])
            if v in REL or v in PRODOP:
                return Atom("placeholder", "")
            self.i += 1
            return Atom("sym", v)
        if t.kind == "num":
            self.i += 1
            return Atom("num", t.value)
        if t.kind == "text":
            self.i += 1
            return Atom("text", t.value)
        if t.kind == "greek":
            self.i += 1
            ch = GREEK.get(t.value) or GREEK.get(t.value.lower())
            if ch is None:
                return Atom("text", t.value)
            return Atom("ident", ch)
        # words
        w = t.value
        lw = w.lower()
        self.i += 1
        if lw in ("alignl", "alignr", "alignc", "alignm", "alignt", "alignb"):
            self.saw_align = True
            return self.operand() if not self.stop() else Seq()
        if lw in ATTR1:
            node = self.operand()
            if lw in ("ital", "italic") and isinstance(node, Atom) and \
                    node.kind == "text" and node.value.isalpha():
                return Atom("ident", node.value)
            return node
        if lw in ATTR2:
            self.next()        # the attribute value
            if lw == "color" and self.peek() is not None and \
                    self.peek().kind == "num":
                # color rgb r g b
                while self.peek() is not None and self.peek().kind == "num":
                    self.i += 1
            return self.operand()
        if lw == "nospace":
            return self.operand()
        if lw in ("sqrt",):
            return Root(_unwrap_group(self.operand()))
        if lw == "nroot":
            idx = self.term()
            return Root(_unwrap_group(self.operand()), idx)
        if lw == "binom":
            a = self.term()
            b = self.term()
            return Frac(a, b, "stack")
        if lw == "frac":
            a = self.term()
            b = self.term()
            return Frac(a, b)
        if lw == "fact":
            return Fact(self.operand())
        if lw in ("abs",):
            return Delim("|", "|", self.operand())
        if lw == "stack":
            rows = self._cells()
            return EqArray([[c] for r in rows for c in r]) if rows else Atom("placeholder", "")
        if lw == "matrix":
            before = self.saw_align
            self.saw_align = False
            rows = self._cells()
            aligned = self.saw_align
            self.saw_align = before
            if aligned:
                return EqArray(rows)
            return Matrix(rows)
        if lw == "left":
            open_ = self.next()
            ov = open_.value.lower() if open_ is not None else "none"
            body = self.expression()
            close = ""
            if self.is_word("right"):
                self.i += 1
                c = self.next()
                cv = c.value.lower() if c is not None else "none"
                close = RBR.get(cv, RBR.get(c.value if c else "", ""))
            return Delim(LBR.get(ov, LBR.get(open_.value, "")), close, body)
        if lw in LBR and lw not in ("none", "(", "["):
            body = self.expression()
            close = LBR[lw]
            if self.peek() is not None and self.peek().kind == "word" and \
                    self.peek().value.lower() in RBR:
                close = RBR[self.next().value.lower()]
            return Delim(LBR[lw], close, body)
        if lw in ACC:
            return Accent(ACC[lw], _unwrap_group(self.operand()))
        if lw == "underline":
            return Brace("▁", _unwrap_group(self.operand()))
        if lw in NARYKW or lw == "oper":
            op = NARYKW.get(lw)
            if lw == "oper":
                nt = self.next()
                op = nt.value if nt is not None else "∑"
                op = {"∪": "⋃", "∩": "⋂", "∨": "⋁", "∧": "⋀"}.get(op, op)
            sub = sup = None
            while self.is_word("from", "to") or self.is_op("_", "^"):
                k = self.next().value.lower()
                if k in ("from", "_"):
                    sub = self.term()
                else:
                    sup = self.term()
            body = self.operand()
            return Nary(op, sub, sup, _unwrap_group(body))
        if lw in FUNC_NATIVE or lw == "func":
            name = w if lw != "func" else (self.next().value if self.peek() else "f")
            sub = sup = None
            while self.is_word("from") or self.is_op("_", "^"):
                k = self.next().value.lower()
                if k in ("from", "_"):
                    sub = self.term()
                else:
                    sup = self.term()
            arg = None
            if not self.stop() and not self._at_binary():
                arg = self.power()
            return Func(name, sub, sup, arg)
        if lw in SYMS:
            ch = SYMS[lw]
            return Atom("sym", ch)
        if lw in ("newline",):
            return Atom("placeholder", "")
        return Atom("ident", w)

    def _at_binary(self):
        t = self.peek()
        if t is None:
            return True
        key = t.value if t.kind == "op" else t.value.lower() if t.kind == "word" else None
        return key in REL or key in SUMOP or key in PRODOP or key in (
            "over", "_", "^", "csub", "csup", "#", "##")

    def _cells(self):
        if not self.is_op("{"):
            return []
        self.i += 1
        rows = [[]]
        while self.peek() is not None and not self.is_op("}"):
            if self.is_op("##"):
                self.i += 1
                rows.append([])
                continue
            if self.is_op("#"):
                self.i += 1
                if not rows[-1]:
                    rows[-1].append(Atom("placeholder", ""))
                rows[-1].append(None)
                continue
            start = self.i
            cell = self.expression()
            if rows[-1] and rows[-1][-1] is None:
                rows[-1][-1] = cell
            else:
                rows[-1].append(cell)
            if self.i == start:
                self.i += 1
        if self.is_op("}"):
            self.i += 1
        return [[c if c is not None else Atom("placeholder", "") for c in r]
                for r in rows]


def _seq(items):
    items = [i for i in items if i is not None]
    flat = []
    for i in items:
        if isinstance(i, Seq):
            flat.extend(i.items)
        else:
            flat.append(i)
    if len(flat) == 1:
        return flat[0]
    return Seq(flat)


def _unwrap_group(node):
    if isinstance(node, Seq) and len(node.items) == 1:
        return node.items[0]
    return node


def parse(src):
    return P(tokenize(src)).expression()


def to_linear_text(src):
    """Best-effort conversion of formula markup to linear text."""
    src = (src or "").strip()
    if not src or src == "<?>":
        return ""
    return to_linear(parse(src))
