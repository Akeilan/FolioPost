"""Symbol tables shared by the equation converter and the editor."""

# Control words typed as \name in the equation bar (converted on space).
CONTROL_WORDS = {
    # Greek, lower case
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ϵ",
    "varepsilon": "ε", "zeta": "ζ", "eta": "η", "theta": "θ", "vartheta": "ϑ",
    "iota": "ι", "kappa": "κ", "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ",
    "omicron": "ο", "pi": "π", "varpi": "ϖ", "rho": "ρ", "varrho": "ϱ",
    "sigma": "σ", "varsigma": "ς", "tau": "τ", "upsilon": "υ", "phi": "ϕ",
    "varphi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω",
    # Greek, upper case
    "Alpha": "Α", "Beta": "Β", "Gamma": "Γ", "Delta": "Δ", "Epsilon": "Ε",
    "Zeta": "Ζ", "Eta": "Η", "Theta": "Θ", "Iota": "Ι", "Kappa": "Κ",
    "Lambda": "Λ", "Mu": "Μ", "Nu": "Ν", "Xi": "Ξ", "Omicron": "Ο", "Pi": "Π",
    "Rho": "Ρ", "Sigma": "Σ", "Tau": "Τ", "Upsilon": "Υ", "Phi": "Φ",
    "Chi": "Χ", "Psi": "Ψ", "Omega": "Ω",
    # binary operators
    "pm": "±", "mp": "∓", "times": "×", "div": "÷", "cdot": "⋅", "ast": "∗",
    "circ": "∘", "bullet": "∙", "oplus": "⊕", "ominus": "⊖", "otimes": "⊗",
    "odot": "⊙", "cap": "∩", "cup": "∪", "setminus": "∖", "wedge": "∧",
    "vee": "∨", "neg": "¬", "lnot": "¬", "land": "∧", "lor": "∨",
    # relations
    "le": "≤", "leq": "≤", "ge": "≥", "geq": "≥", "ne": "≠", "neq": "≠",
    "approx": "≈", "equiv": "≡", "cong": "≅", "sim": "∼", "simeq": "≃",
    "propto": "∝", "ll": "≪", "gg": "≫", "prec": "≺", "succ": "≻",
    "preceq": "⪯", "succeq": "⪰", "perp": "⊥", "parallel": "∥", "mid": "∣",
    "nmid": "∤", "in": "∈", "notin": "∉", "ni": "∋", "subset": "⊂",
    "supset": "⊃", "subseteq": "⊆", "supseteq": "⊇", "nsubset": "⊄",
    "nsupset": "⊅", "doteq": "≐", "asymp": "≍", "coloneq": "≔", "defeq": "≝",
    "models": "⊨", "vdash": "⊢", "dashv": "⊣",
    # arrows
    "to": "→", "rightarrow": "→", "leftarrow": "←", "uparrow": "↑",
    "downarrow": "↓", "leftrightarrow": "↔", "Rightarrow": "⇒",
    "Leftarrow": "⇐", "Leftrightarrow": "⇔", "Uparrow": "⇑", "Downarrow": "⇓",
    "mapsto": "↦", "longrightarrow": "⟶", "longleftarrow": "⟵",
    "Longrightarrow": "⟹", "Longleftarrow": "⟸", "iff": "⟺", "implies": "⟹",
    "nearrow": "↗", "searrow": "↘", "nwarrow": "↖", "swarrow": "↙",
    "rightleftharpoons": "⇌",
    # letters and misc symbols
    "infty": "∞", "partial": "∂", "nabla": "∇", "forall": "∀", "exists": "∃",
    "nexists": "∄", "emptyset": "∅", "aleph": "ℵ", "beth": "ℶ", "hbar": "ℏ",
    "ell": "ℓ", "wp": "℘", "Re": "ℜ", "Im": "ℑ", "angle": "∠",
    "degree": "°", "prime": "′", "pprime": "″", "ppprime": "‴",
    "dots": "…", "ldots": "…", "cdots": "⋯", "vdots": "⋮", "ddots": "⋱",
    "adots": "⋰", "therefore": "∴", "because": "∵", "Box": "□",
    "triangle": "△", "square": "□", "diamond": "⋄", "star": "⋆", "top": "⊤",
    "bot": "⊥", "dagger": "†", "ddagger": "‡", "Dd": "ⅅ", "dd": "ⅆ",
    "ee": "ⅇ", "ii": "ⅈ", "jj": "ⅉ",
    "R": "ℝ", "C": "ℂ", "N": "ℕ", "Z": "ℤ", "Q": "ℚ",
    "Rset": "ℝ", "Cset": "ℂ", "Nset": "ℕ", "Zset": "ℤ", "Qset": "ℚ",
    # large operators
    "sum": "∑", "prod": "∏", "coprod": "∐", "int": "∫", "iint": "∬",
    "iiint": "∭", "oint": "∮", "oiint": "∯", "oiiint": "∰",
    "bigcup": "⋃", "bigcap": "⋂", "bigvee": "⋁", "bigwedge": "⋀",
    # structure characters
    "sqrt": "√", "cbrt": "∛", "qdrt": "∜", "matrix": "■", "eqarray": "█",
    "pmatrix": "(■", "begin": "〖", "end": "〗", "funcapply": "⁡",
    "naryand": "▒", "of": "▒", "above": "┬", "below": "┴", "atop": "¦",
    "ndiv": "⊘", "overbrace": "⏞", "underbrace": "⏟", "overparen": "⏜",
    "underparen": "⏝", "overbar": "¯", "underbar": "▁", "box": "□",
    "rect": "▭", "close": "┤", "open": "├", "vbar": "│", "norm": "‖",
    "langle": "⟨", "rangle": "⟩", "lfloor": "⌊", "rfloor": "⌋", "lceil": "⌈",
    "rceil": "⌉", "lbrace": "{", "rbrace": "}", "lbrack": "[", "rbrack": "]",
    "left": "├", "right": "┤", "placeholder": "⬚",
    # accents (combining characters, typed after the operand)
    "hat": "̂", "check": "̌", "tilde": "̃", "acute": "́",
    "grave": "̀", "dot": "̇", "ddot": "̈", "dddot": "⃛",
    "bar": "̅", "Bar": "̿", "vec": "⃗", "breve": "̆",
    "hvec": "⃑", "tvec": "⃡",
    # spaces
    "thinsp": " ", "medsp": " ", "thicksp": " ",
    "quad": " ", "qquad": "  ", "nbsp": " ",
}

# Character pairs converted as soon as they are typed (math AutoCorrect).
AUTO_PAIRS = [
    ("+-", "±"), ("-+", "∓"), ("<=", "≤"), (">=", "≥"), ("!=", "≠"),
    ("~=", "≅"), ("~~", "≈"), ("->", "→"), ("=>", "⇒"),
    ("<<", "≪"), (">>", "≫"), (":=", "≔"), ("...", "…"), ("''", "″"),
]

GREEK_NAMES = {
    "α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "ε": "varepsilon",
    "ϵ": "epsilon", "ζ": "zeta", "η": "eta", "θ": "theta", "ϑ": "vartheta",
    "ι": "iota", "κ": "kappa", "λ": "lambda", "μ": "mu", "ν": "nu",
    "ξ": "xi", "ο": "omicron", "π": "pi", "ϖ": "varpi", "ρ": "rho",
    "ϱ": "varrho", "σ": "sigma", "ς": "varsigma", "τ": "tau", "υ": "upsilon",
    "ϕ": "phi", "φ": "varphi", "χ": "chi", "ψ": "psi", "ω": "omega",
    "Α": "ALPHA", "Β": "BETA", "Γ": "GAMMA", "Δ": "DELTA", "Ε": "EPSILON",
    "Ζ": "ZETA", "Η": "ETA", "Θ": "THETA", "Ι": "IOTA", "Κ": "KAPPA",
    "Λ": "LAMBDA", "Μ": "MU", "Ν": "NU", "Ξ": "XI", "Ο": "OMICRON",
    "Π": "PI", "Ρ": "RHO", "Σ": "SIGMA", "Τ": "TAU", "Υ": "UPSILON",
    "Φ": "PHI", "Χ": "CHI", "Ψ": "PSI", "Ω": "OMEGA",
}

# Operators, relations and symbols -> formula-engine keywords.
OPERATORS = {
    "+": "+", "-": "-", "−": "-", "=": "=", "<": "<", ">": ">",
    "±": "+-", "∓": "-+", "×": "times", "÷": "div", "⋅": "cdot", "·": "cdot",
    "∙": "cdot", "∗": "*", "*": "*", "∘": "circ", "⊕": "oplus", "⊖": "ominus",
    "⊗": "otimes", "⊙": "odot", "∩": "intersection", "∪": "union",
    "∖": "setminus", "∧": "and", "∨": "or",
    "≤": "<=", "≥": ">=", "≠": "<>", "≈": "approx", "≡": "equiv",
    "≅": "simeq", "∼": "sim", "≃": "simeq", "∝": "prop", "≪": "<<",
    "≫": ">>", "≺": "prec", "≻": "succ", "⪯": "preccurlyeq",
    "⪰": "succcurlyeq", "⊥": "ortho", "∥": "parallel", "∣": "divides",
    "∤": "ndivides", "∈": "in", "∉": "notin", "∋": "owns", "⊂": "subset",
    "⊃": "supset", "⊆": "subseteq", "⊇": "supseteq", "⊄": "nsubset",
    "⊅": "nsupset", "⊈": "nsubseteq", "⊉": "nsupseteq", "≐": "dotsaxis",
    "≝": "def", "→": "toward", "⇒": "drarrow", "⇐": "dlarrow",
    "⇔": "dlrarrow", "⟹": "drarrow", "⟸": "dlarrow", "⟺": "dlrarrow",
    "≔": "\":=\"",
}

# Relations get relation spacing; everything else in OPERATORS is binary.
RELATIONS = set("=<>≤≥≠≈≡≅∼≃∝≪≫≺≻⪯⪰⊥∥∣∤∈∉∋⊂⊃⊆⊇⊄⊅⊈⊉≐≝→⇒⇐⇔⟹⟸⟺≔←↔↦⟶⟵")

SYMBOLS = {
    "∞": "infinity", "∂": "partial", "∇": "nabla", "∀": "forall",
    "∃": "exists", "∄": "notexists", "∅": "emptyset", "ℵ": "aleph",
    "℘": "wp", "ℜ": "Re", "ℑ": "Im", "ℏ": "hbar", "ℝ": "setR", "ℂ": "setC",
    "ℕ": "setN", "ℤ": "setZ", "ℚ": "setQ", "…": "dotslow", "⋯": "dotsaxis",
    "⋮": "dotsvert", "⋱": "dotsdown", "⋰": "dotsup", "¬": "neg",
    "←": "leftarrow", "↑": "uparrow", "↓": "downarrow",
}

NARY = {
    "∑": "sum", "∏": "prod", "∐": "coprod", "∫": "int", "∬": "iint",
    "∭": "iiint", "∮": "lint", "∯": "llint", "∰": "lllint",
    "⋃": "union", "⋂": "intersection", "⋁": "or", "⋀": "and",
}
# N-ary operators the engine has no large form for (drawn with "oper").
NARY_OPER = {"⋃": "∪", "⋂": "∩", "⋁": "∨", "⋀": "∧"}

FUNCTIONS = {
    "sin", "cos", "tan", "cot", "sec", "csc", "sinh", "cosh", "tanh", "coth",
    "sech", "csch", "arcsin", "arccos", "arctan", "arccot", "arcsec",
    "arccsc", "arsinh", "arcosh", "artanh", "log", "ln", "lg", "exp", "lim",
    "liminf", "limsup", "max", "min", "sup", "inf", "det", "gcd", "lcm",
    "deg", "dim", "ker", "arg", "mod", "Pr", "hom", "tr", "sgn", "erf",
}
# Functions whose subscript goes underneath (limits).
LIMIT_FUNCTIONS = {"lim", "liminf", "limsup", "max", "min", "sup", "inf"}
# Functions the engine knows natively.
NATIVE_FUNCTIONS = {
    "sin", "cos", "tan", "cot", "sinh", "cosh", "tanh", "coth", "arcsin",
    "arccos", "arctan", "arccot", "arsinh", "arcosh", "artanh", "arcoth",
    "log", "ln", "exp", "lim", "liminf", "limsup",
}

ACCENTS = {
    "̂": "widehat", "̌": "check", "̃": "widetilde",
    "́": "acute", "̀": "grave", "̇": "dot", "̈": "ddot",
    "⃛": "dddot", "̅": "overline", "̄": "bar",
    "̿": "overline", "⃗": "widevec", "̆": "breve",
    "⃑": "harpoon", "⃡": "widevec",
}
# Accents that should not be wide when applied to one letter
NARROW_ACCENT = {"widehat": "hat", "widetilde": "tilde", "widevec": "vec"}

OPEN_BRACKETS = {"(": ")", "[": "]", "{": "}", "⟨": "⟩", "⌊": "⌋", "⌈": "⌉",
                 "〖": "〗", "├": "┤", "⟦": "⟧"}
CLOSE_BRACKETS = {v: k for k, v in OPEN_BRACKETS.items()}
SELF_BRACKETS = {"|", "‖", "│"}

BRACKET_SM = {
    "(": "(", ")": ")", "[": "[", "]": "]", "{": "lbrace", "}": "rbrace",
    "⟨": "langle", "⟩": "rangle", "⌊": "lfloor", "⌋": "rfloor",
    "⌈": "lceil", "⌉": "rceil", "|": "lline", "‖": "ldline", "│": "lline",
    "⟦": "ldbracket", "⟧": "rdbracket", "": "none",
}
BRACKET_SM_RIGHT = dict(BRACKET_SM, **{"|": "rline", "‖": "rdline",
                                        "│": "rline"})

PLACEHOLDER = "⬚"

# Characters with a structural meaning in the linear format.
STRUCTURE = set("/⊘¦^_√∛∜■█▒┬┴⏞⏟⏜⏝¯▁□▭&@⁡")

# Words that are keywords of the formula engine: variables with these names
# are written as italic text so they are not read as commands.
ENGINE_KEYWORDS = set("""
abs acute aleph alignb alignc alignl alignm alignr alignt and approx aqua
arccos arccot arcosh arcoth arcsin arctan arsinh artanh backepsilon bar binom
black blue bold boper breve bslash cdot check circ circle color coprod cos cosh
cot coth csub csup dddot ddot def div divides dlarrow dlrarrow dot dotsaxis
dotsdiag dotsdown dotslow dotsup dotsvert downarrow drarrow emptyset equiv
evaluate exists exp fact fixed font from frac frown func fuchsia ge geslant gg
grave gray green gt harpoon hat hbar hex iiint iint im in infinity infty int
intd intersection ital itimes lambdabar langle lbrace lceil ldbracket ldline le
left leftarrow leslant lfloor lim liminf limsup lint ll lline llint lllint ln
log lsub lsup lt maroon matrix minusplus mline nabla navy nbold ndivides neg
neq newline ni nitalic none nospace notexists notin nroot nsubset nsubseteq
nsupset nsupseteq odivide odot olive ominus oper oplus or ortho otimes over
overbrace overline overstrike owns parallel partial phantom plusminus prec
preccurlyeq precsim prod prop purple rangle rbrace rceil rdbracket rdline re
red rfloor rgb right rightarrow rline rsub rsup sans serif setc setminus setn
setq setr setz silver sim simeq sin sinh size slash sqrt stack sub subset
subseteq succ succcurlyeq succsim sum sup supset supseteq tan tanh teal tilde
times to toward transl transr uoper underbrace underline union uparrow vec
white widebslash widehat wideharpoon wideslash widetilde widevec wp yellow
cyan magenta lime orange coral crimson midnightblue
""".split())
