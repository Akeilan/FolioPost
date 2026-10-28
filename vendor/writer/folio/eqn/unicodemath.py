"""Linear (UnicodeMath-style) equation syntax -> formula-engine markup.

The linear format is what users type in the equation bar, e.g.

    x=(-b±√(b^2-4ac))/2a        ∑_(i=1)^n▒i^2        ■(a&b@c&d)

parse() turns it into a small tree; to_starmath() renders that tree in the
engine's markup; to_linear() renders it back as tidy linear text.
"""
from . import symbols as S


# --------------------------------------------------------------------------
# tree
class Node:
    pass


class Seq(Node):
    def __init__(self, items=None):
        self.items = list(items or [])

    def __repr__(self):
        return "Seq(%r)" % self.items


class Atom(Node):
    # kind: num ident op text sym space placeholder
    def __init__(self, kind, value):
        self.kind, self.value = kind, value

    def __repr__(self):
        return "%s:%r" % (self.kind, self.value)


class Frac(Node):
    def __init__(self, num, den, kind="bar"):
        self.num, self.den, self.kind = num, den, kind


class Script(Node):
    def __init__(self, base, sub=None, sup=None, pre=False):
        self.base, self.sub, self.sup, self.pre = base, sub, sup, pre


class Root(Node):
    def __init__(self, body, index=None):
        self.body, self.index = body, index


class Nary(Node):
    def __init__(self, op, sub, sup, body):
        self.op, self.sub, self.sup, self.body = op, sub, sup, body


class Delim(Node):
    def __init__(self, open_, close, body):
        self.open, self.close, self.body = open_, close, body


class Matrix(Node):
    def __init__(self, rows):
        self.rows = rows


class EqArray(Node):
    def __init__(self, rows):
        self.rows = rows


class Accent(Node):
    def __init__(self, mark, body):
        self.mark, self.body = mark, body


class Func(Node):
    def __init__(self, name, sub, sup, arg):
        self.name, self.sub, self.sup, self.arg = name, sub, sup, arg


class Limit(Node):
    # ┬ / ┴ (above / below)
    def __init__(self, base, label, above):
        self.base, self.label, self.above = base, label, above


class Brace(Node):
    # ⏞ ⏟ ⏜ ⏝ ¯ ▁ □ ▭
    def __init__(self, mark, body, label=None):
        self.mark, self.body, self.label = mark, body, label


class Prime(Node):
    def __init__(self, base, count):
        self.base, self.count = base, count


class Fact(Node):
    def __init__(self, base):
        self.base = base


class ParseError(Exception):
    pass


# --------------------------------------------------------------------------
# tokenizer
def _is_letter(ch):
    return ch.isalpha() and ch not in S.SYMBOLS and ch not in S.NARY \
        and ch not in S.GREEK_NAMES and not ("ℂ" <= ch <= "ℿ")


def expand_control_words(text, final=True):
    """Replace \\name control words. With final=False only names followed by a
    delimiter are replaced (what happens while typing)."""
    out = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n and text[i + 1].isalpha():
            j = i + 1
            while j < n and text[j].isalpha():
                j += 1
            name = text[i + 1:j]
            sym = S.CONTROL_WORDS.get(name)
            if sym is None:
                # longest known prefix (\alphax -> αx is not wanted; keep)
                out.append(text[i:j])
                i = j
                continue
            if j < n and text[j] == " ":
                out.append(sym)
                i = j + 1
                continue
            if j < n or final:
                out.append(sym)
                i = j
                continue
            out.append(text[i:j])
            i = j
            continue
        if ch == "\\" and i + 1 < n:
            # \( \) \[ \] \{ \} \| ... escape: literal character
            out.append("\x00" + text[i + 1])
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


class Tok:
    __slots__ = ("kind", "value")

    def __init__(self, kind, value):
        self.kind, self.value = kind, value

    def __repr__(self):
        return "%s:%r" % (self.kind, self.value)


def tokenize(text):
    text = expand_control_words(text)
    toks = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "\x00":            # escaped literal
            toks.append(Tok("lit", text[i + 1]))
            i += 2
        elif ch in " \t\n\u2009\u205f\u2005\u2003\u00a0":
            j = i
            while j < n and text[j] in " \t\n":
                j += 1
            if ch in "\u2009\u205f\u2005\u2003\u00a0":
                toks.append(Tok("mspace", ch))
                i += 1
            else:
                toks.append(Tok("space", " "))
                i = j
        elif ch == '"':
            j = text.find('"', i + 1)
            if j < 0:
                j = n
            toks.append(Tok("text", text[i + 1:j]))
            i = j + 1
        elif ch.isdigit():
            j = i
            while j < n and (text[j].isdigit() or
                             (text[j] in ".," and j + 1 < n and text[j + 1].isdigit()
                              and text[j] == ".")):
                j += 1
            toks.append(Tok("num", text[i:j]))
            i = j
        elif _is_letter(ch):
            j = i
            while j < n and _is_letter(text[j]):
                j += 1
            toks.append(Tok("word", text[i:j]))
            i = j
        elif ch in "′″‴'":
            count = {"′": 1, "″": 2, "‴": 3, "'": 1}[ch]
            toks.append(Tok("prime", count))
            i += 1
        else:
            toks.append(Tok("ch", ch))
            i += 1
    return toks


# --------------------------------------------------------------------------
# parser
OPERATOR_CHARS = set(S.OPERATORS) | set("←↔↦⟶⟵,;:!")


class Parser:
    def __init__(self, toks):
        self.toks = toks
        self.i = 0
        self.bar_depth = 0

    # helpers
    def peek(self, k=0):
        j = self.i + k
        return self.toks[j] if j < len(self.toks) else None

    def next(self):
        t = self.peek()
        self.i += 1
        return t

    def at(self, kind, value=None):
        t = self.peek()
        return t is not None and t.kind == kind and (value is None or t.value == value)

    def at_ch(self, *values):
        t = self.peek()
        return t is not None and t.kind == "ch" and t.value in values

    def skip_spaces(self):
        while self.at("space"):
            self.i += 1

    # grammar ---------------------------------------------------------------
    def parse(self):
        rows = self.parse_rows(stop=())
        if self.peek() is not None:
            # stray closer: treat as literal and continue
            t = self.next()
            rest = self.parse()
            first = rows[0][0] if len(rows) == 1 and len(rows[0]) == 1 else Seq()
            return Seq([first, Atom("sym", t.value), rest])
        if len(rows) == 1 and len(rows[0]) == 1:
            return rows[0][0]
        return EqArray(rows)

    def parse_rows(self, stop):
        """Rows separated by @, cells by &, until a stop closer."""
        rows = [[self.parse_expr(stop)]]
        while self.at_ch("&", "@"):
            t = self.next()
            if t.value == "&":
                rows[-1].append(self.parse_expr(stop))
            else:
                rows.append([self.parse_expr(stop)])
        return rows

    def is_stop(self, stop):
        t = self.peek()
        if t is None:
            return True
        if t.kind == "ch" and (t.value in stop or t.value in "&@"):
            return True
        if t.kind == "ch" and t.value in S.CLOSE_BRACKETS:
            return True
        if t.kind == "ch" and t.value in S.SELF_BRACKETS and self.bar_depth > 0 \
                and t.value in stop:
            return True
        return False

    def parse_expr(self, stop=()):
        items = []
        term = []          # factors of the current term (for fractions)

        def flush():
            if term:
                items.extend(term)
                term.clear()

        while not self.is_stop(stop):
            t = self.peek()
            if t.kind == "space":
                self.i += 1
                flush()
                continue
            if t.kind == "mspace":
                self.i += 1
                flush()
                items.append(Atom("space", t.value))
                continue
            if t.kind == "ch" and t.value in "/⊘¦⁄":
                self.i += 1
                num = _unwrap(Seq(term) if len(term) != 1 else term[0])
                term.clear()
                den = self.parse_fraction_operand(stop)
                kind = {"/": "bar", "⊘": "linear", "¦": "stack", "⁄": "skew"}[t.value]
                term.append(Frac(num if not _empty(num) else Atom("placeholder", ""),
                                 den, kind))
                continue
            if t.kind == "ch" and t.value in OPERATOR_CHARS and \
                    t.value not in S.SELF_BRACKETS:
                self.i += 1
                flush()
                op = Atom("op", t.value)
                if self.at_ch("┬", "┴"):
                    above = self.next().value == "┬"
                    op = Limit(op, self.parse_script_operand(stop), above)
                items.append(op)
                continue
            f = self.parse_factor(stop)
            if f is None:
                break
            term.append(f)
        flush()
        if len(items) == 1:
            return items[0]
        return Seq(items)

    def parse_fraction_operand(self, stop):
        """Denominator: the following run of factors (no operators/spaces)."""
        factors = []
        while not self.is_stop(stop):
            t = self.peek()
            if t.kind in ("space", "mspace"):
                break
            if t.kind == "ch" and (t.value in OPERATOR_CHARS or t.value in "/⊘¦"):
                break
            f = self.parse_factor(stop)
            if f is None:
                break
            factors.append(f)
        if not factors:
            return Atom("placeholder", "")
        node = factors[0] if len(factors) == 1 else Seq(factors)
        return _unwrap(node)

    def parse_script_operand(self, stop):
        t = self.peek()
        if t is None or t.kind == "space" or self.is_stop(stop):
            return Atom("placeholder", "")
        if t.kind == "ch" and t.value in "-+−±∓":
            self.i += 1
            rest = self.parse_script_operand(stop)
            return Seq([Atom("op", t.value), rest])
        if t.kind == "num":
            self.i += 1
            node = Atom("num", t.value)
            # 2y, 2n+1 is not grouped without brackets; 2y is
            if self.at("word"):
                w = self.next()
                return Seq([node, Atom("ident", w.value)])
            return node
        if t.kind == "word":
            self.i += 1
            if t.value in S.FUNCTIONS:
                return Atom("ident", t.value)
            return Atom("ident", t.value)
        if t.kind == "ch" and t.value in "/⊘¦^_":
            return Atom("placeholder", "")
        return _unwrap(self.parse_primary(stop, allow_scripts=False))

    def parse_factor(self, stop):
        node = self.parse_primary(stop)
        if node is None:
            return None
        return self.parse_postfix(node, stop)

    def parse_postfix(self, node, stop):
        while True:
            t = self.peek()
            if t is None:
                return node
            if t.kind == "prime":
                self.i += 1
                if isinstance(node, Prime):
                    node.count += t.value
                else:
                    node = Prime(node, t.value)
                continue
            if t.kind == "ch" and t.value in S.ACCENTS:
                self.i += 1
                node = Accent(t.value, _unwrap(node))
                continue
            if t.kind == "ch" and t.value in "_^":
                node = self.parse_scripts(node, stop)
                continue
            if t.kind == "ch" and t.value == "!":
                self.i += 1
                node = Fact(node)
                continue
            if t.kind == "ch" and t.value in "┬┴":
                self.i += 1
                label = self.parse_script_operand(stop)
                if isinstance(node, Brace) and node.mark in "⏞⏟⏜⏝" and node.label is None:
                    node.label = label
                else:
                    node = Limit(node, label, t.value == "┬")
                continue
            return node

    def parse_scripts(self, base, stop):
        sub = sup = None
        while self.at_ch("_", "^"):
            t = self.next()
            operand = self.parse_script_operand(stop)
            if t.value == "_" and sub is None:
                sub = operand
            elif t.value == "^" and sup is None:
                sup = operand
            else:
                base = Script(base, sub, sup)
                sub = operand if t.value == "_" else None
                sup = operand if t.value == "^" else None
        return Script(base, sub, sup)

    def parse_group_until(self, closer):
        """Parse the inside of a bracket pair; returns (rows)."""
        if closer in S.SELF_BRACKETS:
            self.bar_depth += 1
        rows = self.parse_rows(stop=(closer,))
        if closer in S.SELF_BRACKETS:
            self.bar_depth -= 1
        closed = False
        if self.at_ch(closer):
            self.i += 1
            closed = closer
        elif closer not in S.SELF_BRACKETS and self.peek() is not None and \
                self.peek().kind == "ch" and self.peek().value in S.CLOSE_BRACKETS:
            closed = self.next().value      # [0,1) style intervals
        return rows, closed

    def rows_to_node(self, rows):
        if len(rows) == 1 and len(rows[0]) == 1:
            return rows[0][0]
        if len(rows) == 1:
            # & used outside matrix: keep as row of cells
            return Matrix(rows)
        return EqArray(rows) if all(len(r) == 1 for r in rows) else Matrix(rows)

    def parse_primary(self, stop, allow_scripts=True):
        t = self.peek()
        if t is None or self.is_stop(stop):
            return None
        k, v = t.kind, t.value
        if k == "num":
            self.i += 1
            return Atom("num", v)
        if k == "text":
            self.i += 1
            return Atom("text", v)
        if k == "lit":
            self.i += 1
            return Atom("sym", v)
        if k == "prime":
            self.i += 1
            return Atom("sym", "′" * v)
        if k == "word":
            self.i += 1
            if v in S.FUNCTIONS:
                return self.parse_function(v, stop)
            # a run of letters may end with a function name? keep as variables
            return Atom("ident", v)
        if k != "ch":
            self.i += 1
            return Atom("sym", v)

        # structural characters
        if v == "⬚":
            self.i += 1
            return Atom("placeholder", "")
        if v in S.GREEK_NAMES:
            self.i += 1
            return Atom("ident", v)
        if v in S.SYMBOLS:
            self.i += 1
            return Atom("sym", v)
        if v in S.NARY:
            self.i += 1
            return self.parse_nary(v, stop)
        if v in "√∛∜":
            self.i += 1
            return self.parse_root(v, stop)
        if v in "■█":
            self.i += 1
            if self.at_ch("("):
                self.i += 1
                rows, _ = self.parse_group_until(")")
            else:
                rows = [[Atom("placeholder", "")]]
            if v == "█":
                return EqArray(rows)
            return Matrix(rows)
        if v in "⏞⏟⏜⏝¯▁□▭":
            self.i += 1
            body = self.parse_script_operand(stop)
            return Brace(v, _unwrap(body))
        if v in S.OPEN_BRACKETS:
            self.i += 1
            closer = S.OPEN_BRACKETS[v]
            rows, closed = self.parse_group_until(closer)
            body = self.rows_to_node(rows)
            if v == "〖":
                return Delim("", "", body)     # invisible grouping
            if v == "├":
                return Delim("", "" if closed in (False, "┤") else closed, body)
            if not closed or closed == "┤":
                # an unmatched opener is shown as a stretchy left bracket
                return Delim(v, "", body)
            return Delim(v, closed, body)
        if v in S.SELF_BRACKETS:
            self.i += 1
            rows, closed = self.parse_group_until(v)
            body = self.rows_to_node(rows)
            if not closed:
                return Seq([Atom("sym", v), body]) if not _empty(body) else Atom("sym", v)
            return Delim(v, v, body)
        if v in S.CLOSE_BRACKETS:
            return None
        if v in "/⊘¦":
            return None
        if v in "_^":
            # script with no base: placeholder base
            return Atom("placeholder", "")
        if v == "▒":
            self.i += 1
            return self.parse_primary(stop)
        if v == "⁡":
            self.i += 1
            return self.parse_primary(stop)
        if v in "┬┴":
            return Atom("placeholder", "")
        self.i += 1
        return Atom("sym", v)

    def parse_nary(self, op, stop):
        sub = sup = None
        while self.at_ch("_", "^"):
            t = self.next()
            operand = self.parse_script_operand(stop)
            if t.value == "_":
                sub = operand
            else:
                sup = operand
        body = None
        if self.at_ch("▒"):
            self.i += 1
            body = self.parse_factor(stop)
            if isinstance(body, Delim) and body.open == "":
                body = body.body
        else:
            if self.at("space"):
                self.i += 1
            # body: following run of factors up to an operator or space
            factors = []
            while not self.is_stop(stop):
                t = self.peek()
                if t.kind in ("space", "mspace"):
                    break
                if t.kind == "ch" and (t.value in OPERATOR_CHARS or t.value in "/⊘¦"):
                    break
                f = self.parse_factor(stop)
                if f is None:
                    break
                factors.append(f)
            if factors:
                body = factors[0] if len(factors) == 1 else Seq(factors)
        return Nary(op, sub, sup, body if body is not None else Atom("placeholder", ""))

    def parse_root(self, ch, stop):
        index = None
        if ch == "∛":
            index = Atom("num", "3")
        elif ch == "∜":
            index = Atom("num", "4")
        if self.at_ch("("):
            self.i += 1
            rows, _ = self.parse_group_until(")")
            if len(rows) == 1 and len(rows[0]) == 2 and index is None:
                return Root(rows[0][1], rows[0][0])
            body = self.rows_to_node(rows)
            return Root(body, index)
        body = self.parse_script_operand(stop)
        if isinstance(body, Atom) and body.kind == "placeholder" and self.peek() is None:
            return Root(body, index)
        return Root(_unwrap(body), index)

    def parse_function(self, name, stop):
        sub = sup = None
        while self.at_ch("_", "^"):
            t = self.next()
            operand = self.parse_script_operand(stop)
            if t.value == "_":
                sub = operand
            else:
                sup = operand
        if self.at_ch("⁡") or self.at_ch("▒"):
            self.i += 1
        elif self.at("space"):
            self.i += 1
        arg = None
        if not self.is_stop(stop):
            t = self.peek()
            if not (t.kind == "ch" and (t.value in OPERATOR_CHARS or t.value in "/⊘¦")) \
                    and t.kind not in ("space", "mspace"):
                arg = self.parse_factor(stop)
        return Func(name, sub, sup, arg)


def _empty(node):
    return node is None or (isinstance(node, Seq) and not node.items)


def _unwrap(node):
    """Brackets around an operand of a build-up operator are not shown."""
    if isinstance(node, Delim) and node.open in ("(", "") and \
            node.close in (")", ""):
        return node.body
    if isinstance(node, Seq) and len(node.items) == 1:
        return _unwrap(node.items[0])
    return node


def _is_blank(n):
    if n is None:
        return True
    if isinstance(n, Atom):
        return n.kind == "placeholder"
    if isinstance(n, Seq):
        return all(_is_blank(i) for i in n.items)
    return False


def _prescripts(node):
    """〖⬚_a^b〗X (an empty-based script in an invisible group right before
    its base) is a prescript on X."""
    if isinstance(node, Seq):
        out = []
        items = node.items
        i = 0
        while i < len(items):
            it = _prescripts(items[i])
            if isinstance(it, Delim) and it.open == "" and it.close == "" and \
                    i + 1 < len(items):
                body = it.body
                if isinstance(body, Seq) and len(body.items) == 1:
                    body = body.items[0]
                if isinstance(body, Script) and _is_blank(body.base) and not body.pre:
                    out.append(Script(_prescripts(items[i + 1]), body.sub, body.sup, True))
                    i += 2
                    continue
            out.append(it)
            i += 1
        node.items = out
        return node
    for k, v in list(vars(node).items()):
        if isinstance(v, Node):
            setattr(node, k, _prescripts(v))
        elif isinstance(v, list):
            setattr(node, k, [[_prescripts(c) for c in r] if isinstance(r, list)
                              else _prescripts(r) if isinstance(r, Node) else r for r in v])
    return node


def _number_split(text):
    """'eq#(1)': the equation and its number, at a '#' outside brackets."""
    depth = 0
    for i, ch in enumerate(text):
        if ch in S.OPEN_BRACKETS:
            depth += 1
        elif ch in S.CLOSE_BRACKETS:
            depth -= 1
        elif ch == "#" and depth == 0:
            return text[:i], text[i + 1:]
    return None


def parse(text):
    split = _number_split(text)
    if split is not None and split[0].strip():
        left, right = split
        a = parse(left)
        b = parse(right) if right.strip() else Seq()
        items = (a.items if isinstance(a, Seq) else [a]) + [Atom("op", "#")] + \
            (b.items if isinstance(b, Seq) else [b])
        return Seq(items)
    p = Parser(tokenize(text))
    tree = p.parse()
    if "〖" in text:
        tree = _prescripts(tree if isinstance(tree, Seq) else Seq([tree]))
        if len(tree.items) == 1:
            tree = tree.items[0]
    return tree


# --------------------------------------------------------------------------
# formula-engine markup
_SM_SPECIAL = set("{}#%&~`^_\"'\\[]()<>=+-*/|!?.,;:@$")


def _sm_ident(value):
    if len(value) > 1 and value.lower() in S.ENGINE_KEYWORDS:
        return 'ital "%s"' % value
    out = []
    for ch in value:
        if ch in S.GREEK_NAMES:
            name = S.GREEK_NAMES[ch]
            out.append(" %" + ("i" + name if name.islower() else name) + " ")
        else:
            out.append(ch)
    s = "".join(out).strip()
    return s


def _sm_text(value):
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


_DELIM_DEPTH = [0]


def _sm_sym(ch):
    if ch in S.SELF_BRACKETS and ch != "‖":
        return "mline" if _DELIM_DEPTH[0] else '"|"'
    if ch in S.SYMBOLS:
        return S.SYMBOLS[ch]
    if ch in S.OPERATORS:
        return S.OPERATORS[ch]
    if ch.isalnum():
        return ch
    if ch in ",;:.!":
        return '"%s"' % ch if ch in ";:" else ch
    return _sm_text(ch)


def _grp(s):
    return "{" + s + "}"


def _sm(node):
    if node is None:
        return "{}"
    if isinstance(node, Seq):
        if not node.items:
            return "{}"
        parts = []
        prev = None
        for it in node.items:
            if isinstance(it, Limit) and isinstance(it.base, Atom) and \
                    it.base.kind == "op":
                if prev is None:
                    parts.append("{}")
                parts.append(_sm_op(it.base.value, False) + (
                    " csup " if it.above else " csub ") + _grp(_sm(it.label)))
                prev = it
                continue
            if isinstance(it, Atom) and it.kind == "op":
                if prev is None and it.value in S.RELATIONS | set(S.OPERATORS) \
                        and it.value not in "+-−±∓":
                    parts.append("{}")
                parts.append(_sm_op(it.value, prev is None))
            else:
                parts.append(_sm(it))
            prev = it
        return " ".join(p for p in parts if p)
    if isinstance(node, Atom):
        k, v = node.kind, node.value
        if k == "num":
            return v
        if k == "ident":
            return _sm_ident(v)
        if k == "text":
            return _sm_text(v)
        if k == "op":
            if v not in "+-−±∓" and (v in S.RELATIONS or v in S.OPERATORS):
                return "{} " + _sm_op(v, True)
            return _sm_op(v, True)
        if k == "placeholder":
            return "<?>"
        if k == "space":
            return {"\u2009": "`", "\u205f": "`", "\u2005": "~",
                    "\u2003": "~~", "\u00a0": "~"}.get(v, "~")
        return _sm_sym(v)
    if isinstance(node, Frac):
        if node.kind == "linear":
            return _grp(_sm(node.num)) + " / " + _grp(_sm(node.den))
        if node.kind == "stack":
            return "binom " + _grp(_sm(node.num)) + " " + _grp(_sm(node.den))
        if node.kind == "skew":
            return _grp(_grp(_sm(node.num)) + " wideslash " + _grp(_sm(node.den)))
        return _grp(_grp(_sm(node.num)) + " over " + _grp(_sm(node.den)))
    if isinstance(node, Script) and node.pre:
        s = _base(node.base)
        if node.sub is not None:
            s += " lsub " + _grp(_sm(node.sub))
        if node.sup is not None:
            s += " lsup " + _grp(_sm(node.sup))
        return s
    if isinstance(node, Script):
        s = _base(node.base)
        if node.sub is not None:
            s += "_" + _grp(_sm(node.sub))
        if node.sup is not None:
            s += "^" + _grp(_sm(node.sup))
        return s
    if isinstance(node, Prime):
        return _base(node.base) + "^" + _grp('"' + "′" * node.count + '"')
    if isinstance(node, Fact):
        return "fact " + _grp(_sm(node.base))
    if isinstance(node, Root):
        if node.index is not None:
            return "nroot" + _grp(_sm(node.index)) + _grp(_sm(node.body))
        return "sqrt" + _grp(_sm(node.body))
    if isinstance(node, Nary):
        op = S.NARY[node.op]
        if node.op in S.NARY_OPER:
            op = 'oper "%s"' % S.NARY_OPER[node.op]
        s = op
        if node.sub is not None:
            s += " from" + _grp(_sm(node.sub))
        if node.sup is not None:
            s += " to" + _grp(_sm(node.sup))
        return _grp(s + " " + _grp(_sm(node.body)))
    if isinstance(node, Delim):
        if node.open == "" and node.close == "":
            return _grp(_sm(node.body))
        _DELIM_DEPTH[0] += 1
        try:
            body = _sm(node.body)
        finally:
            _DELIM_DEPTH[0] -= 1
        pair = S.OPEN_BRACKETS.get(node.open) == node.close or \
            (node.open in S.SELF_BRACKETS and node.open == node.close)
        if pair and not _tall(node.body):
            return "%s %s %s" % (S.BRACKET_SM.get(node.open),
                                 body or "{}",
                                 S.BRACKET_SM_RIGHT.get(node.close))
        return "left %s %s right %s" % (S.BRACKET_SM.get(node.open, "none"),
                                        body or "{}",
                                        S.BRACKET_SM_RIGHT.get(node.close, "none"))
    if isinstance(node, Matrix):
        rows = " ## ".join(" # ".join(_grp(_sm(c)) for c in r) for r in node.rows)
        return "matrix{" + rows + "}"
    if isinstance(node, EqArray):
        if any(len(r) > 1 for r in node.rows):
            # & marks the alignment point: right-align before, left-align after
            width = max(len(r) for r in node.rows)
            out = []
            for r in node.rows:
                cells = []
                for j in range(width):
                    c = _sm(r[j]) if j < len(r) else "{}"
                    align = "alignr" if j % 2 == 0 else "alignl"
                    cells.append(align + " " + _grp(c))
                out.append(" # ".join(cells))
            return "matrix{" + " ## ".join(out) + "}"
        return "stack{" + " # ".join(_grp(_sm(r[0])) for r in node.rows) + "}"
    if isinstance(node, Accent):
        kw = S.ACCENTS.get(node.mark, "hat")
        if _is_simple(node.body) and kw in S.NARROW_ACCENT:
            kw = S.NARROW_ACCENT[kw]
        return kw + " " + _grp(_sm(node.body))
    if isinstance(node, Func):
        name = node.name
        head = name if name in S.NATIVE_FUNCTIONS else 'func ' + name
        s = head
        if node.sub is not None:
            if name in S.LIMIT_FUNCTIONS and name in S.NATIVE_FUNCTIONS:
                s += " from" + _grp(_sm(node.sub))
            elif name in S.LIMIT_FUNCTIONS:
                s = _grp(s) + " csub " + _grp(_sm(node.sub))
            else:
                s += "_" + _grp(_sm(node.sub))
        if node.sup is not None:
            s += "^" + _grp(_sm(node.sup))
        if node.arg is not None:
            s += " " + _grp(_sm(node.arg))
        return _grp(s)
    if isinstance(node, Limit):
        kw = "csup" if node.above else "csub"
        if isinstance(node.base, Atom) and node.base.kind == "op":
            return "{} " + _sm_op(node.base.value, False) + " " + kw + " " + \
                _grp(_sm(node.label))
        return _grp(_grp(_sm(node.base)) + " " + kw + " " + _grp(_sm(node.label)))
    if isinstance(node, Brace):
        body = _grp(_sm(node.body))
        if node.mark in "⏞⏜":
            return _grp(body + " overbrace " + _grp(_sm(node.label) if node.label else "{}"))
        if node.mark in "⏟⏝":
            return _grp(body + " underbrace " + _grp(_sm(node.label) if node.label else "{}"))
        if node.mark == "¯":
            return "overline " + body
        if node.mark == "▁":
            return "underline " + body
        return body
    raise ParseError("cannot render %r" % node)


def _tall(node):
    """Does the content need stretchy brackets?"""
    if node is None:
        return False
    if isinstance(node, (Frac, Nary, Matrix, EqArray, Limit, Brace)):
        return not (isinstance(node, Frac) and node.kind == "linear")
    if isinstance(node, Seq):
        return any(_tall(i) for i in node.items)
    if isinstance(node, Root):
        return _tall(node.body)
    if isinstance(node, Script):
        return _tall(node.base) or _tall(node.sub) or _tall(node.sup)
    if isinstance(node, (Delim, Accent, Prime, Fact)):
        return _tall(node.body if hasattr(node, "body") else node.base)
    if isinstance(node, Func):
        return _tall(node.arg) or (node.sub is not None and node.name in S.LIMIT_FUNCTIONS)
    return False


def _is_simple(node):
    return isinstance(node, Atom) and node.kind in ("ident", "num") and len(node.value) == 1


def _base(node):
    s = _sm(node)
    if isinstance(node, (Atom,)) and node.kind in ("num", "ident", "sym", "placeholder"):
        return s
    return _grp(s)


def _sm_op(ch, leading):
    if ch in S.OPERATORS:
        kw = S.OPERATORS[ch]
    elif ch in S.SYMBOLS:
        kw = S.SYMBOLS[ch]
    elif ch in ",":
        return ","
    elif ch in ";:":
        return '";"' if ch == ";" else '":"'
    elif ch == "!":
        return '"!"'
    elif ch in "↔↦⟶⟵":
        return _sm_text(ch)
    else:
        kw = _sm_text(ch)
    if leading and kw in ("+", "-", "+-", "-+"):
        return kw + " "
    return kw


def to_starmath(text):
    """Convert linear text to formula markup. Empty input -> placeholder."""
    if not text.strip():
        return "<?>"
    return _sm(parse(text)).strip() or "<?>"


# --------------------------------------------------------------------------
# tree -> tidy linear text
def _lin(node):
    if node is None:
        return ""
    if isinstance(node, Seq):
        out = ""
        prev = None
        for it in node.items:
            piece = _lin(it)
            if out and piece and (
                    (_wordish(out[-1]) and _wordish(piece[0]) and
                     not (out[-1].isdigit() and piece[0].isalpha() and
                          not isinstance(prev, Atom) or
                          (isinstance(prev, Atom) and prev.kind == "num" and
                           isinstance(it, Atom) and it.kind == "ident"))) or
                    (isinstance(it, (Frac, Nary)) and not
                     (isinstance(prev, Atom) and prev.kind in ("op", "space")))):
                out += " "
            prev = it
            out += piece
        return out
    if isinstance(node, Atom):
        if node.kind == "placeholder":
            return "⬚"
        if node.kind == "text":
            return '"' + node.value + '"'
        return node.value
    if isinstance(node, Frac):
        ch = {"bar": "/", "linear": "⊘", "stack": "¦", "skew": "⁄"}[node.kind]
        return _arg(node.num) + ch + _arg(node.den)
    if isinstance(node, Script) and node.pre:
        s = "〖⬚"
        if node.sub is not None:
            s += "_" + _arg(node.sub)
        if node.sup is not None:
            s += "^" + _arg(node.sup)
        return s + "〗" + _arg(node.base, keep_simple=True)
    if isinstance(node, Script):
        s = _arg(node.base, keep_simple=True)
        if node.sub is not None:
            s += "_" + _arg(node.sub)
        if node.sup is not None:
            s += "^" + _arg(node.sup)
        return s
    if isinstance(node, Prime):
        return _arg(node.base, True) + "′" * node.count
    if isinstance(node, Fact):
        return _arg(node.base, True) + "!"
    if isinstance(node, Root):
        if node.index is not None:
            if isinstance(node.index, Atom) and node.index.value == "3":
                return "∛" + _arg(node.body)
            if isinstance(node.index, Atom) and node.index.value == "4":
                return "∜" + _arg(node.body)
            return "√(" + _lin(node.index) + "&" + _lin(node.body) + ")"
        return "√" + _arg(node.body)
    if isinstance(node, Nary):
        s = node.op
        if node.sub is not None:
            s += "_" + _arg(node.sub)
        if node.sup is not None:
            s += "^" + _arg(node.sup)
        body = _lin(node.body)
        if isinstance(node.body, (Atom, Delim)) or len(body) <= 1:
            return s + "▒" + body
        return s + "▒〖" + body + "〗"
    if isinstance(node, Delim):
        if node.open == "" and node.close == "":
            return "〖" + _lin(node.body) + "〗"
        return node.open + _lin(node.body) + node.close
    if isinstance(node, Matrix):
        return "■(" + "@".join("&".join(_lin(c) for c in r) for r in node.rows) + ")"
    if isinstance(node, EqArray):
        return "█(" + "@".join("&".join(_lin(c) for c in r) for r in node.rows) + ")"
    if isinstance(node, Accent):
        return _arg(node.body, True) + node.mark
    if isinstance(node, Func):
        s = node.name
        if node.sub is not None:
            s += "_" + _arg(node.sub)
        if node.sup is not None:
            s += "^" + _arg(node.sup)
        if node.arg is not None:
            a = _lin(node.arg)
            if isinstance(node.arg, Delim) or (isinstance(node.arg, Atom) and
                                                node.arg.kind != "text"):
                s += a if a.startswith("(") else "⁡" + a
            else:
                s += "⁡〖" + a + "〗"
        return s
    if isinstance(node, Limit):
        return _arg(node.base, True) + ("┬" if node.above else "┴") + _arg(node.label)
    if isinstance(node, Brace):
        s = node.mark + _arg(node.body)
        if node.label is not None:
            s += ("┬" if node.mark in "⏞⏜" else "┴") + _arg(node.label)
        return s
    return ""


def _wordish(ch):
    return ch.isalnum() or ch in S.GREEK_NAMES or ch in "⬚\"′"


def _arg(node, keep_simple=False):
    s = _lin(node)
    if isinstance(node, Atom) and (len(s) <= 1 or node.kind in ("num", "ident")):
        return s
    if isinstance(node, (Delim, Root, Accent)) and keep_simple:
        return s
    if isinstance(node, Delim) and node.open not in ("(", ""):
        return s
    if isinstance(node, Script) and keep_simple:
        return s
    return "(" + s + ")"


def to_linear(node):
    return _lin(node)
