"""LaTeX math input -> linear text (then handled by the normal converter)."""
from . import symbols as S

ENV_WRAP = {
    "matrix": ("", ""), "smallmatrix": ("", ""), "pmatrix": ("(", ")"),
    "bmatrix": ("[", "]"), "Bmatrix": ("{", "}"), "vmatrix": ("|", "|"),
    "Vmatrix": ("‖", "‖"),
}
FONT_CMDS = {"mathrm", "mathit", "mathbf", "mathsf", "mathtt", "boldsymbol",
             "mathnormal", "bm", "operatorname"}
TEXT_CMDS = {"text", "textrm", "textit", "textbf", "mbox", "mathrm_text"}
BB = {"R": "ℝ", "C": "ℂ", "N": "ℕ", "Z": "ℤ", "Q": "ℚ", "P": "ℙ", "H": "ℍ"}
ACCENT_CMDS = {"hat": "̂", "widehat": "̂", "check": "̌",
               "tilde": "̃", "widetilde": "̃", "acute": "́",
               "grave": "̀", "dot": "̇", "ddot": "̈",
               "dddot": "⃛", "bar": "̅", "vec": "⃗",
               "breve": "̆", "overrightarrow": "⃗"}
SPACES = {",": " ", ":": " ", ";": " ", "quad": " ",
          "qquad": "  ", "!": "", " ": " "}
EXTRA = {"to": "→", "gets": "←", "lbrace": "{", "rbrace": "}", "{": "{",
         "}": "}", "|": "‖", "%": "%", "$": "$", "#": "#", "&": "&", "_": "_",
         "lvert": "|", "rvert": "|", "lVert": "‖", "rVert": "‖",
         "mid": "∣", "colon": ":", "dots": "…", "ldots": "…", "cdots": "⋯",
         "infty": "∞", "neq": "≠", "ne": "≠", "leq": "≤", "geq": "≥",
         "le": "≤", "ge": "≥", "lt": "<", "gt": ">", "vert": "|",
         "partial": "∂", "nabla": "∇", "prime": "′", "displaystyle": "",
         "textstyle": "", "limits": "", "nolimits": "", "middle": "",
         "big": "", "Big": "", "bigg": "", "Bigg": "", "bigl": "", "bigr": "",
         "Bigl": "", "Bigr": "", "biggl": "", "biggr": "", "Biggl": "",
         "Biggr": "", "cdot": "⋅", "ast": "∗", "times": "×", "div": "÷"}


class _L:
    def __init__(self, src):
        self.s = src
        self.i = 0

    def peek(self):
        return self.s[self.i] if self.i < len(self.s) else ""

    def eof(self):
        return self.i >= len(self.s)

    def command(self):
        """After a backslash: read the command name."""
        self.i += 1
        if self.eof():
            return ""
        if not self.s[self.i].isalpha():
            c = self.s[self.i]
            self.i += 1
            return c
        j = self.i
        while j < len(self.s) and self.s[j].isalpha():
            j += 1
        name = self.s[self.i:j]
        self.i = j
        return name

    def skip_ws(self):
        while not self.eof() and self.s[self.i] in " \t\n":
            self.i += 1

    def arg(self):
        """One argument: {group} or a single token."""
        self.skip_ws()
        if self.peek() == "{":
            self.i += 1
            out = self.seq(stop="}")
            if self.peek() == "}":
                self.i += 1
            return out
        if self.peek() == "\\":
            save = self.i
            name = self.command()
            self.i = save
            return self.atom()
        if self.eof():
            return "⬚"
        c = self.s[self.i]
        self.i += 1
        return c

    def opt(self):
        self.skip_ws()
        if self.peek() == "[":
            self.i += 1
            out = self.seq(stop="]")
            if self.peek() == "]":
                self.i += 1
            return out
        return None

    def raw_group(self):
        self.skip_ws()
        if self.peek() != "{":
            return ""
        depth = 0
        start = self.i
        while not self.eof():
            c = self.s[self.i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    self.i += 1
                    return self.s[start + 1:self.i - 1]
            self.i += 1
        return self.s[start + 1:]

    def seq(self, stop=None, env=None):
        out = []
        while not self.eof():
            c = self.peek()
            if stop and c == stop:
                break
            if c == "\\" and env and self.s.startswith("\\end", self.i):
                break
            if c == "\\" and self.s.startswith("\\right", self.i) and stop == "\\right":
                break
            out.append(self.atom(env))
        return "".join(out)

    def atom(self, env=None):
        c = self.peek()
        if c == "{":
            self.i += 1
            inner = self.seq(stop="}")
            if self.peek() == "}":
                self.i += 1
            return "〖" + inner + "〗"
        if c in "^_":
            self.i += 1
            a = self.arg()
            return c + _wrap(a)
        if c == "&":
            self.i += 1
            return "&"
        if c == "\\":
            return self.cmd(env)
        if c == "~":
            self.i += 1
            return " "
        if c == "'":
            self.i += 1
            return "′"
        self.i += 1
        return c

    def cmd(self, env):
        name = self.command()
        if name == "\\":
            return "@" if env else " "
        if name in ("frac", "dfrac", "tfrac", "cfrac"):
            a, b = self.arg(), self.arg()
            return "〖" + _wrap(a) + "/" + _wrap(b) + "〗"
        if name in ("binom", "dbinom", "tbinom"):
            a, b = self.arg(), self.arg()
            return "(" + a + "¦" + b + ")"
        if name == "sqrt":
            idx = self.opt()
            a = self.arg()
            if idx:
                return "√(" + idx + "&" + a + ")"
            return "√" + _wrap(a)
        if name in ACCENT_CMDS:
            a = self.arg()
            return _wrap(a) + ACCENT_CMDS[name]
        if name == "overline":
            return "¯" + _wrap(self.arg())
        if name == "underline":
            return "▁" + _wrap(self.arg())
        if name in ("overbrace", "underbrace"):
            a = self.arg()
            mark = "⏞" if name == "overbrace" else "⏟"
            out = mark + _wrap(a)
            self.skip_ws()
            if self.peek() in "^_":
                self.i += 1
                out += ("┬" if name == "overbrace" else "┴") + _wrap(self.arg())
            return out
        if name in ("overset", "stackrel"):
            top, base = self.arg(), self.arg()
            return _wrap(base) + "┬" + _wrap(top)
        if name == "underset":
            bottom, base = self.arg(), self.arg()
            return _wrap(base) + "┴" + _wrap(bottom)
        if name in TEXT_CMDS:
            return '"' + self.raw_group() + '"'
        if name in ("mathbb", "Bbb"):
            g = self.raw_group() or self.arg()
            return "".join(BB.get(ch, ch) for ch in g)
        if name in FONT_CMDS:
            g = self.arg()
            if name == "operatorname":
                return g + "⁡"
            return g
        if name == "left":
            self.skip_ws()
            d = self.peek()
            if d == "\\":
                d = self.command()
                d = {"{": "{", "lbrace": "{", "langle": "⟨", "lfloor": "⌊",
                     "lceil": "⌈", "|": "‖", "lvert": "|", "lVert": "‖"}.get(d, "(")
            else:
                self.i += 1
            if d == ".":
                d = "├"
            inner = self.seq(stop="\\right")
            close = ""
            if self.s.startswith("\\right", self.i):
                self.i += len("\\right")
                self.skip_ws()
                e = self.peek()
                if e == "\\":
                    e = self.command()
                    e = {"}": "}", "rbrace": "}", "rangle": "⟩", "rfloor": "⌋",
                         "rceil": "⌉", "|": "‖", "rvert": "|", "rVert": "‖"}.get(e, ")")
                else:
                    self.i += 1
                close = "┤" if e == "." else e
            if d == "├" and close in ("", "┤"):
                return "〖" + inner + "〗"
            return d + inner + (close or "┤")
        if name == "right":
            return ""
        if name == "begin":
            env_name = self.raw_group()
            body = self.seq(env=env_name)
            if self.s.startswith("\\end", self.i):
                self.i += len("\\end")
                self.raw_group()
            body = body.strip().rstrip("@")
            if env_name in ENV_WRAP:
                o, c = ENV_WRAP[env_name]
                return o + "■(" + body + ")" + c
            if env_name == "cases":
                return "{█(" + body + ")┤"
            return "█(" + body + ")"
        if name in SPACES:
            return SPACES[name]
        if name in EXTRA:
            return EXTRA[name]
        if name in S.FUNCTIONS:
            return name
        if name in S.CONTROL_WORDS:
            return S.CONTROL_WORDS[name]
        return "\\" + name


def _wrap(s):
    s = s.strip()
    if s.startswith("〖") and s.endswith("〗") and s.count("〖") == 1:
        s = s[1:-1]
    import re
    if len(s) == 1 or re.fullmatch(r"[0-9]*[A-Za-z]*", s):
        return s
    return "(" + s + ")"


def to_linear(src):
    src = src.strip()
    if src.startswith("$") and src.endswith("$"):
        src = src.strip("$")
    if src.startswith("\\[") and src.endswith("\\]"):
        src = src[2:-2]
    return _L(src).seq().strip()
