"""Equations in .docx files that the engine's importer gets wrong.

The engine drops the operator of n-ary structures it has no keyword for
(big union, big intersection, the n-ary logic operators, ...), leaving a
bare "from ... to ..." that shows as an error mark. After a .docx opens,
the operators are put back from the file's own equation markup."""
import re
import zipfile
import xml.etree.ElementTree as ET

from . import docapi

M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
OPS = {"int", "iint", "iiint", "lint", "llint", "lllint", "sum", "prod", "coprod",
       "lim", "liminf", "limsup", "oper", "uoper", "boper", "union", "intersection",
       "sup", "inf", "max", "min", "}"}
NAMED = {"∑": "sum", "∏": "prod", "∐": "coprod", "∫": "int", "∬": "iint", "∭": "iiint",
         "∮": "lint", "∯": "llint", "∰": "lllint"}


def _nary_chars(omath):
    out = []
    for n in omath.iter("{%s}nary" % M_NS):
        ch = "∫"
        pr = n.find("{%s}naryPr" % M_NS)
        if pr is not None:
            c = pr.find("{%s}chr" % M_NS)
            if c is not None and c.get("{%s}val" % M_NS):
                ch = c.get("{%s}val" % M_NS)
        out.append(ch)
    return out


def _bare_froms(formula):
    """Character offsets of 'from' keywords that have no operator before them."""
    out = []
    for mm in re.finditer(r"(?<![A-Za-z])from(?![A-Za-z])", formula):
        before = formula[:mm.start()].rstrip()
        if re.search(r'oper\s+("[^"]*"|\S+)$', before):
            continue
        prev = re.search(r"([A-Za-z]+|\S)$", before)
        tok = prev.group(1) if prev else ""
        if tok not in OPS:
            out.append(mm.start())
    return out


def repair(formula, chars):
    """Put n-ary operators back in front of bare 'from' keywords."""
    bare = _bare_froms(formula)
    if not bare:
        return formula
    # the bare ones are the operators the engine couldn't name
    named = set(NAMED)
    missing = [c for c in chars if c not in named] or chars
    out = formula
    for pos, ch in reversed(list(zip(bare, missing[:len(bare)]))):
        op = NAMED.get(ch) or 'oper "%s"' % ch
        out = out[:pos] + op + " " + out[pos:]
    return out


def _sorted_formulas(m):
    objs = docapi.formulas(m)
    keyed = []
    for o in objs:
        try:
            a = o.getAnchor()
            if a.getText() != m.getText():
                continue            # headers, footers, frames, tables: skip
            keyed.append((a, o))
        except Exception:
            pass
    text = m.getText()
    import functools

    def cmp(x, y):
        try:
            return -text.compareRegionStarts(x[0], y[0])
        except Exception:
            return 0
    keyed.sort(key=functools.cmp_to_key(cmp))
    return [o for _a, o in keyed]


FIXED = []


def fix_document(m, path):
    """Returns how many equations were repaired."""
    del FIXED[:]
    if not path or not path.lower().endswith((".docx", ".docm", ".dotx")):
        return 0
    try:
        with zipfile.ZipFile(path) as z:
            root = ET.fromstring(z.read("word/document.xml"))
    except Exception:
        return 0
    body = root.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}body")
    if body is None:
        return 0
    # top-level equations of the body text (not inside tables or text boxes)
    W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    maths = []
    for p in body.findall(W + "p"):
        maths.extend(p.iter("{%s}oMath" % M_NS))
    objs = _sorted_formulas(m)
    if len(objs) != len(maths):
        return 0
    fixed = 0
    for o, om in zip(objs, maths):
        try:
            f = o.Model.Formula
        except Exception:
            continue
        if not _bare_froms(f):
            continue
        new = repair(f, _nary_chars(om))
        if new != f:
            try:
                o.Model.Formula = new
                fixed += 1
                FIXED.append(o)
            except Exception as e:
                print("math fix:", e)
    return fixed
