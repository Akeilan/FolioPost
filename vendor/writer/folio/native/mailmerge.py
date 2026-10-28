"""Mailings with the new engine, as Word keeps them: MERGEFIELD, ADDRESSBLOCK,
GREETINGLINE and the rule fields (ASK, FILLIN, IF, MERGEREC, MERGESEQ, NEXT,
NEXTIF, SET, SKIPIF, REF) in the text; the merge type and the recipient list
(a CSV file, linked) in the document's mail merge settings. Envelopes, labels,
preview, Find Recipient and Finish & Merge.

The functions take the window where the old engine's mailings module takes its
document, so the Mailings dialogs work with either."""
import csv
import json
import os
import re
import shlex
import tempfile
from xml.sax.saxutils import escape, quoteattr

from gi.repository import GLib

from .. import mailings as C
from .refs import parse

ENVELOPES = C.ENVELOPES
LABELS = C.LABELS
read_csv = C.read_csv
address_columns = C.address_columns
OPEN, CLOSE = "«", "»"
TYPES = {"letters": "formLetters", "envelopes": "envelopes", "labels": "mailingLabels",
         "directory": "catalog", "email": "email"}
KINDS = {v: k for k, v in TYPES.items()}
REL_DATA = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/mailMergeSource"
DATA_DIR = os.path.expanduser("~/Documents/My Data Sources")


def _ed(win):
    return win.engine.ed


def _after(win):
    win.engine.view.after_edit()


# ================================================================ settings
def _mm(win):
    x = _ed(win).settings_xml("w:mailMerge") or ""
    out = {}
    m = re.search(r'<w:mainDocumentType w:val="([^"]*)"', x)
    if m:
        out["type"] = KINDS.get(m.group(1), m.group(1))
    m = re.search(r'<w:query w:val="([^"]*)"', x)
    if m:
        q = re.sub(r"&quot;", '"', m.group(1))
        q = q.replace("&amp;", "&")
        mm = re.match(r"\s*SELECT \* FROM [`\"]?(.+?)[`\"]?\s*$", q, re.I)
        if mm:
            out["path"] = mm.group(1)
    out["xml"] = x
    return out


def _docvar(win, name):
    x = _ed(win).settings_xml("w:docVars") or ""
    m = re.search(r'<w:docVar w:name=%s w:val="([^"]*)"' % re.escape(quoteattr(name)), x)
    if not m:
        return ""
    from xml.sax.saxutils import unescape
    return unescape(m.group(1), {"&quot;": '"'})


def _set_docvar(win, name, value):
    ed = _ed(win)
    x = ed.settings_xml("w:docVars") or "<w:docVars></w:docVars>"
    x = re.sub(r'<w:docVar w:name=%s w:val="[^"]*"\s*/>' % re.escape(quoteattr(name)), "", x)
    if value:
        x = x.replace("</w:docVars>", "<w:docVar w:name=%s w:val=%s/></w:docVars>" % (quoteattr(name), quoteattr(value)))
        if x.endswith("/>") and "<w:docVar " not in x:
            x = "<w:docVars><w:docVar w:name=%s w:val=%s/></w:docVars>" % (quoteattr(name), quoteattr(value))
    if "<w:docVar " not in x:
        ed.set_settings_xml("w:docVars", None)
    else:
        ed.set_settings_xml("w:docVars", x)


def _write_mm(win, kind=None, path=None):
    cur = _mm(win)
    kind = kind if kind is not None else cur.get("type", "letters")
    path = path if path is not None else cur.get("path", "")
    ed = _ed(win)
    if not kind and not path:
        ed.set_settings_xml("w:mailMerge", None)
        return
    parts = ['<w:mailMerge><w:mainDocumentType w:val="%s"/>' % TYPES.get(kind, "formLetters")]
    if path:
        rid = ed.add_settings_rel(REL_DATA, "file:///" + path.lstrip("/"), True)
        parts.append('<w:linkToQuery/><w:dataType w:val="textFile"/><w:connectString w:val=""/>'
                     '<w:query w:val=%s/>' % quoteattr("SELECT * FROM %s" % path))
        if rid:
            parts.append('<w:dataSource r:id="%s"/>' % rid)
    parts.append("</w:mailMerge>")
    ed.set_settings_xml("w:mailMerge", "".join(parts))


# ================================================================ recipients
def recipients(win):
    """(columns, records, included flags)."""
    path = _mm(win).get("path", "")
    cols, rows = [], []
    if path and os.path.exists(path):
        try:
            cols, rows = read_csv(path)
        except Exception as e:
            print("recipients:", e)
    inc = [c == "1" for c in _docvar(win, "FolioMergeInclude").split(",") if c]
    if len(inc) != len(rows):
        inc = [True] * len(rows)
    return cols, rows, inc


def set_recipients(win, columns, rows, path="", include=None):
    if not path:
        # a typed list is kept in a file of its own, as the original keeps it
        os.makedirs(DATA_DIR, exist_ok=True)
        n = 1
        while os.path.exists(os.path.join(DATA_DIR, "Address List %d.csv" % n)):
            n += 1
        path = os.path.join(DATA_DIR, "Address List %d.csv" % n)
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(columns)
            for r in rows:
                w.writerow([r.get(c, "") for c in columns])
    _write_mm(win, path=path)
    set_included(win, include or [True] * len(rows))
    _after(win)


def save_list(win, columns, rows):
    """Edit Recipient List / a typed list changed: write it back to its file."""
    path = _mm(win).get("path", "")
    if not path:
        return set_recipients(win, columns, rows)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(columns)
        for r in rows:
            w.writerow([r.get(c, "") for c in columns])


def set_included(win, include):
    _set_docvar(win, "FolioMergeInclude", "" if all(include) else ",".join("1" if v else "0" for v in include))


def merge_type(win):
    return _mm(win).get("type", "")


def set_merge_type(win, kind):
    _write_mm(win, kind=kind)


# ================================================================ fields
def q(s):
    return '"%s"' % s.replace('"', "'") if re.search(r'[\s"]', s) else s


def insert_field(win, col, text=None, cursor=None):
    _ed(win).insert_field("MERGEFIELD %s" % q(col), OPEN + col + CLOSE)
    _after(win)


def fields(win):
    """[(index, depth, kind, args, switches, result)] of every body field."""
    out = []
    for i, (depth, code, res) in enumerate(_ed(win).fields_all()):
        k, args, sw = parse(code)
        out.append((i, depth, k, args, sw, res))
    return out


def merge_masters(win):
    """{column: True} for the merge fields in the document."""
    return {f[3][0]: True for f in fields(win) if f[2] == "MERGEFIELD" and f[3]}


def _run(text):
    return '<w:r><w:t xml:space="preserve">%s</w:t></w:r>' % escape(text)


def _field_runs(code, result="", inner=None):
    """A field as runs; `inner` (runs) goes in its code after the first word."""
    head, _, rest = code.partition(" ") if inner is not None else (code, "", "")
    s = '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
    s += '<w:r><w:instrText xml:space="preserve"> %s </w:instrText></w:r>' % escape(head)
    if inner is not None:
        s += inner
        if rest:
            s += '<w:r><w:instrText xml:space="preserve"> %s </w:instrText></w:r>' % escape(rest)
    s += '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
    if result:
        s += _run(result)
    s += '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    return s


def insert_runs(win, runs):
    _ed(win).paste_fragment("<w:p>%s</w:p>" % runs, True)
    _after(win)


def insert_address_block(win):
    cols, _r, _i = recipients(win)
    if not cols:
        return False
    code = 'ADDRESSBLOCK \\f "<<_TITLE0_ >><<_FIRST0_>><< _LAST0_>><< _SUFFIX0_>>\n<<_COMPANY_\n>><<_STREET1_\n>><<_STREET2_\n>><<_CITY_>><<, _STATE_>><< _POSTAL_>><<\n_COUNTRY_>>" \\l 1033 \\c 2 \\e "United States" \\d'
    _ed(win).insert_field(code, OPEN + "AddressBlock" + CLOSE)
    _after(win)
    return True


def insert_greeting(win, salutation="Dear", punct=","):
    code = 'GREETINGLINE \\f "%s <<_FIRST0_>><< _LAST0_>>%s" \\l 1033 \\e "%s Sir or Madam%s"' % (
        salutation, punct, salutation, punct)
    _ed(win).insert_field(code, OPEN + "GreetingLine" + CLOSE)
    _after(win)


# ================================================================ rules (fields)
OPS = {"eq": "=", "ne": "<>", "lt": "<", "gt": ">", "le": "<=", "ge": ">=", "blank": "=", "notblank": "<>"}
PLACE = {"MERGEREC": "«Merge Record #»", "MERGESEQ": "«Merge Sequence #»"}


def insert_rule(win, rule):
    k = rule["kind"]
    ed = _ed(win)

    def cond_runs(head, tail=""):
        field = rule.get("field") or ""
        op = OPS.get(rule.get("op", "eq"), "=")
        val = "" if rule.get("op") in ("blank", "notblank") else rule.get("value", "")
        inner = _field_runs("MERGEFIELD %s" % q(field), OPEN + field + CLOSE)
        return _field_runs("%s %s \"%s\"%s" % (head, op, val.replace('"', "'"), tail), rule.get("then", "") if head == "IF" else "",
                           inner=inner)
    if k == "if":
        insert_runs(win, cond_runs("IF", ' "%s" "%s"' % (rule.get("then", "").replace('"', "'"),
                                                         rule.get("else", "").replace('"', "'"))))
    elif k in ("nextif", "skipif"):
        insert_runs(win, cond_runs("NEXTIF" if k == "nextif" else "SKIPIF"))
    elif k == "record":
        ed.insert_field("MERGEREC", PLACE["MERGEREC"])
    elif k == "seq":
        ed.insert_field("MERGESEQ", PLACE["MERGESEQ"])
    elif k == "next":
        ed.insert_code_field("NEXT")
    elif k == "set":
        ed.insert_code_field('SET %s "%s"' % (rule.get("name") or "Bookmark1", rule.get("value", "").replace('"', "'")))
    elif k == "ask":
        ed.insert_code_field('ASK %s "%s" \\d "%s"%s' % (rule.get("name") or "Bookmark1", rule.get("prompt", "").replace('"', "'"),
                                                          rule.get("default", "").replace('"', "'"), " \\o" if rule.get("once") else ""))
    elif k == "fillin":
        ed.insert_field('FILLIN "%s" \\d "%s"%s' % (rule.get("prompt", "").replace('"', "'"), rule.get("default", "").replace('"', "'"),
                                                    " \\o" if rule.get("once") else ""), rule.get("default", ""))
    elif k == "ref":
        ed.insert_field("REF %s" % rule["name"], OPEN + rule["name"] + CLOSE)
    _after(win)


def rules(win):
    """The rule fields as the old engine's rules: {index: rule}."""
    out = {}
    for i, _d, k, args, sw, _r in fields(win):
        if k in ("ASK", "SET") and args:
            out[str(i)] = {"kind": k.lower(), "name": args[0], "prompt": args[1] if len(args) > 1 else "",
                           "value": args[1] if k == "SET" and len(args) > 1 else "",
                           "default": sw.get("d") if isinstance(sw.get("d"), str) else "", "once": "o" in sw}
        elif k == "FILLIN":
            out[str(i)] = {"kind": "fillin", "prompt": args[0] if args else "",
                           "default": sw.get("d") if isinstance(sw.get("d"), str) else "", "once": "o" in sw}
    return out


def bookmark_names(win):
    return sorted({r["name"] for r in rules(win).values() if r["kind"] in ("ask", "set")})


def ask_answers(win, per_record=None):
    """Prompt for FILLIN and ASK fields: {field index: answer}."""
    answers = {}
    for rid, rule in rules(win).items():
        if rule["kind"] not in ("fillin", "ask"):
            continue
        if per_record is not None and rule.get("once", True):
            continue
        if per_record is None and not rule.get("once", True):
            continue
        a = win.dialogs.ask_text("Fill-in" if rule["kind"] == "fillin" else "Ask", rule.get("prompt", ""),
                                 rule.get("default", ""))
        answers[rid] = rule.get("default", "") if a is None else a
    return answers


# ================================================================ evaluating
def _num(v):
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


def compare(a, op, b):
    x, y = _num(a), _num(b)
    if x is None or y is None:
        x, y = str(a).lower(), str(b).lower()
    if op == "=" and isinstance(x, str) and ("*" in y or "?" in y):
        import fnmatch
        return fnmatch.fnmatch(x, y)
    return {"=": x == y, "<>": x != y, "<": x < y, ">": x > y, "<=": x <= y, ">=": x >= y}.get(op, False)


def _split(code):
    try:
        return shlex.split(code, posix=True)
    except ValueError:
        return code.split()


def _value_of(code_rest):
    """IF a op b "t" "f": (a, op, b, t, f)."""
    t = _split(code_rest)
    if len(t) < 3:
        return None
    a, op, b = t[0], t[1], t[2]
    if op not in ("=", "<>", "<", ">", "<=", ">="):
        # "a" with nothing to compare (a blank field): op shifts left
        if t[0] in ("=", "<>", "<", ">", "<=", ">="):
            a, op, b = "", t[0], t[1]
            t = [""] + t
        else:
            return None
    yes = t[3] if len(t) > 3 else ""
    no = t[4] if len(t) > 4 else ""
    return a, op, b, yes, no


def _address(win, rec, cols):
    lines = []
    try:
        lines_cols = address_columns(cols, win)
    except Exception:
        lines_cols = address_columns(cols)
    try:
        from ..mailrules import matched_column
        city = matched_column(win, "City", cols)
    except Exception:
        city = None
    for line in lines_cols:
        vals = [(c, rec.get(c, "").strip()) for c in line]
        out = ""
        for k, (c, val) in enumerate(vals):
            if not val:
                continue
            if out:
                # City, State ZIP
                out += ", " if vals[k - 1][0] == city and vals[k - 1][1] else " "
            out += val
        if out:
            lines.append(out)
    return "\n".join(lines)


def _greeting(code, rec, cols):
    k, args, sw = parse(code)
    fmt = sw.get("f") if isinstance(sw.get("f"), str) else "Dear <<_FIRST0_>><< _LAST0_>>,"
    first = C._find(cols, "First Name", "FirstName", "Given Name", "First", "Name")
    last = C._find(cols, "Last Name", "LastName", "Surname")
    vals = {"_FIRST0_": rec.get(first, "") if first else "", "_LAST0_": rec.get(last, "") if last else "",
            "_TITLE0_": rec.get(C._find(cols, "Title", "Salutation") or "", "")}
    if not any(vals.values()):
        alt = sw.get("e") if isinstance(sw.get("e"), str) else "Dear Sir or Madam,"
        return alt

    def chunk(m):
        inner = m.group(1)
        for key, v in vals.items():
            if key in inner:
                return inner.replace(key, v) if v else ""
        return inner
    return re.sub(r"<<(.*?)>>", chunk, fmt)


def evaluate(win, ed, rows, idx, ctx):
    """Show record `idx` in editor `ed`; returns (next record, skip this one)."""
    cols = list(rows[0].keys()) if rows else []
    cur = idx
    skip = False
    bookmarks = {}
    answers = ctx.get("answers", {})
    fl = ed.fields_all()
    i = 0
    while i < len(fl):
        depth, code, res = fl[i]
        k, args, sw = parse(code)
        rec = rows[cur] if 0 <= cur < len(rows) else {}
        if k == "MERGEFIELD" and args:
            ed.set_field_text_at(i, rec.get(args[0], ""))
        elif k == "NEXT":
            cur += 1
        elif k in ("NEXTIF", "SKIPIF", "IF"):
            # its own merge fields first, with this record
            j = i + 1
            while j < len(fl) and fl[j][0] > depth:
                kk, aa, _s = parse(fl[j][1])
                if kk == "MERGEFIELD" and aa:
                    ed.set_field_text_at(j, rec.get(aa[0], ""))
                j += 1
            code = ed.fields_all()[i][1]
            rest = code.split(None, 1)[1] if " " in code else ""
            v = _value_of(rest)
            if v is not None:
                ok = compare(v[0], v[1], v[2])
                if k == "IF":
                    ed.set_field_text_at(i, v[3] if ok else v[4])
                elif k == "NEXTIF" and ok:
                    cur += 1
                elif k == "SKIPIF" and ok:
                    skip = True
            fl = ed.fields_all()
            i = j
            continue
        elif k == "MERGEREC":
            ed.set_field_text_at(i, str(cur + 1))
        elif k == "MERGESEQ":
            ed.set_field_text_at(i, str(ctx.get("seq", cur + 1)))
        elif k == "SET" and len(args) >= 2:
            bookmarks[args[0]] = args[1]
        elif k == "ASK" and args:
            d = sw.get("d") if isinstance(sw.get("d"), str) else ""
            bookmarks[args[0]] = answers.get(str(i), d)
        elif k == "FILLIN":
            d = sw.get("d") if isinstance(sw.get("d"), str) else ""
            ed.set_field_text_at(i, answers.get(str(i), d))
        elif k == "REF" and args and args[0] in bookmarks:
            ed.set_field_text_at(i, bookmarks[args[0]])
        elif k == "ADDRESSBLOCK":
            ed.set_field_text_at(i, _address(win, rec, cols))
        elif k == "GREETINGLINE":
            ed.set_field_text_at(i, _greeting(code, rec, cols))
        fl = ed.fields_all() if k in ("MERGEFIELD", "ADDRESSBLOCK") else fl
        i += 1
    return cur + 1, skip


def placeholders(ed):
    """Merge fields show their names (Preview Results off)."""
    for i, (depth, code, res) in enumerate(ed.fields_all()):
        k, args, sw = parse(code)
        if k == "MERGEFIELD" and args:
            ed.set_field_text_at(i, OPEN + args[0] + CLOSE)
        elif k in PLACE:
            ed.set_field_text_at(i, PLACE[k])
        elif k == "ADDRESSBLOCK":
            ed.set_field_text_at(i, OPEN + "AddressBlock" + CLOSE)
        elif k == "GREETINGLINE":
            ed.set_field_text_at(i, OPEN + "GreetingLine" + CLOSE)
        elif k == "REF" and args:
            ed.set_field_text_at(i, OPEN + args[0] + CLOSE)
    for i, (depth, code, res) in enumerate(ed.fields_all()):
        k, args, sw = parse(code)
        if k == "IF":
            v = _value_of(code.split(None, 1)[1] if " " in code else "")
            if v is not None:
                ed.set_field_text_at(i, v[3])


def show_record(win, index):
    """Preview: the fields show record `index`; None: their names."""
    ed = _ed(win)
    cols, rows, inc = recipients(win)
    ed.begin_group("Preview Results")
    try:
        if index is None or not rows:
            placeholders(ed)
        else:
            evaluate(win, ed, rows, max(0, min(index, len(rows) - 1)), {"seq": index + 1})
    finally:
        ed.end_group()
    _after(win)


def find_recipient(win, needle, start=0):
    _cols, rows, _inc = recipients(win)
    n = needle.lower()
    for k in list(range(start, len(rows))) + list(range(0, start)):
        if any(n in str(v).lower() for v in rows[k].values()):
            return k
    return None


# ================================================================ finish & merge
def _snapshot(win):
    fd, path = tempfile.mkstemp(suffix=".docx", prefix="folio-merge-")
    os.close(fd)
    _ed(win).save(path)
    return path


def merged_document(win, which="all", first=1, last=None, answers=None):
    """Finish & Merge into a file: a copy of the document for each record (labels:
    as many records as the page takes). Returns (path, count)."""
    from . import core
    cols, rows, inc = recipients(win)
    kind = merge_type(win) or "letters"
    picks = [i for i, ok in enumerate(inc) if ok]
    if isinstance(which, int):
        picks = [which]
    elif which == "current":
        cur = getattr(win, "merge_preview", None) or 0
        picks = [cur]
    elif which == "range":
        picks = [i for i in picks if first - 1 <= i <= (last or len(rows)) - 1]
    if not rows or not picks:
        return None, 0
    src = _snapshot(win)
    E = core().Editor.open(src)
    out = core().Editor.open(src)
    out.select_all()
    out.type_text("")
    frags = []
    seq = 0
    k = 0
    while k < len(picks):
        idx = picks[k]
        seq += 1
        nxt, skip = evaluate(win, E, rows, idx, {"seq": seq, "answers": answers or {}})
        # NEXT fields used up records
        used = max(1, nxt - idx)
        k += used
        if skip:
            continue
        E.select_all()
        frag = E.copy_fragment()
        if frag:
            frags.append(frag)
    for n, frag in enumerate(frags):
        if n and kind not in ("directory",):
            out.move_caret("doc_end", False)
            out.insert_break("nextPage")
        out.move_caret("doc_end", False)
        out.paste_fragment(frag, True)
    out.unlink_fields()
    out.set_settings_xml("w:mailMerge", None)
    fd, path = tempfile.mkstemp(suffix=".docx", prefix="Letters-")
    os.close(fd)
    out.save(path)
    try:
        os.unlink(src)
    except OSError:
        pass
    return path, len(frags)


def merge(win, which="all", first=1, last=None, answers=None):
    """The merged document's path (the caller opens it)."""
    path, n = merged_document(win, which, first, last, answers)
    if not path:
        raise ValueError("There are no recipients to merge.")
    return path


# ================================================================ envelopes, labels
def _mm100_tw(v):
    return int(round(v * 1440 / 2540.0))


def _page(ed, sec, w, h, top, bottom, left, right, landscape):
    """Page size and margins (1/100 mm) of one section."""
    ed.begin_group("Page Setup")
    try:
        ed.section_attr(sec, "w:pgSz", "w:w", str(_mm100_tw(w)), "Page Setup")
        ed.section_attr(sec, "w:pgSz", "w:h", str(_mm100_tw(h)), "Page Setup")
        ed.section_attr(sec, "w:pgSz", "w:orient", "landscape" if landscape else None, "Page Setup")
        for k, v in (("w:top", top), ("w:bottom", bottom), ("w:left", left), ("w:right", right)):
            ed.section_attr(sec, "w:pgMar", k, str(_mm100_tw(v)), "Page Setup")
    finally:
        ed.end_group()


def envelope(win, delivery, ret, size_index=0, omit_return=False, opts=None):
    """An envelope page at the start of the document."""
    opts = opts or {}
    ed = _ed(win)
    name, w, h = ENVELOPES[size_index]
    ed.begin_group("Add to Document")
    try:
        ed.move_caret("doc_start", False)
        lines = [] if omit_return else [l for l in ret.splitlines()]
        dl = delivery.splitlines() or [""]
        ed.insert_break("nextPage")
        ed.move_caret("doc_start", False)
        ret_x = '<w:pPr><w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr>'
        left = int(opts["delivery_left"]) - 1000 if opts.get("delivery_left") is not None else int(w * 0.42)
        top = int(opts["delivery_top"]) - 1000 if opts.get("delivery_top") is not None else int(h * 0.30)
        dlv_x = '<w:pPr><w:spacing w:before="%d" w:after="0" w:line="240" w:lineRule="auto"/><w:ind w:left="%d"/></w:pPr>' % (
            _mm100_tw(top), _mm100_tw(left))

        def para(ppr, text_lines, font=None):
            rpr = ""
            if font:
                f, sz = font
                rpr = "<w:rPr>%s%s</w:rPr>" % ('<w:rFonts w:ascii=%s w:hAnsi=%s/>' % (quoteattr(f), quoteattr(f)) if f else "",
                                              '<w:sz w:val="%d"/>' % int(float(sz) * 2) if sz else "")
            runs = ""
            for i, ln in enumerate(text_lines):
                if i:
                    runs += "<w:r>%s<w:br/></w:r>" % rpr
                runs += '<w:r>%s<w:t xml:space="preserve">%s</w:t></w:r>' % (rpr, escape(ln))
            return "<w:p>%s%s</w:p>" % (ppr, runs)
        xml = ""
        if lines:
            xml += para(ret_x, lines, opts.get("return_font"))
        xml += para(dlv_x, dl, opts.get("delivery_font"))
        ed.paste_fragment(xml, True)
        sec = 0
        _page(ed, sec, w, h, 1000, 800, 1000, 800, True)
    finally:
        ed.end_group()
    _after(win)


def labels_document(win, address, label_index=0, full_page=True, row=1, col=1):
    """Fill a new (empty) document with a sheet of labels as a table."""
    (name, pw, ph, lw, lh, cols, rows, top, side, hp, vp) = LABELS[label_index]
    ed = _ed(win)
    ed.begin_group("Labels")
    try:
        right = max(0, pw - side - cols * hp + (hp - lw))
        _page(ed, 0, pw, ph, top, 0, side, right, False)
        gap = _mm100_tw(hp - lw)
        widths = []
        for c in range(cols):
            widths.append(_mm100_tw(lw))
            if c < cols - 1 and gap > 0:
                widths.append(gap)
        grid = "".join('<w:gridCol w:w="%d"/>' % wd for wd in widths)
        addr = address.splitlines()
        trs = ""
        for r in range(rows):
            tcs = ""
            for k, wd in enumerate(widths):
                is_label = gap <= 0 or k % 2 == 0
                cidx = k // 2 if gap > 0 else k
                text = ""
                if is_label and address and (full_page or (r == row - 1 and cidx == col - 1)):
                    text = "".join(('<w:r><w:br/></w:r>' if i else "") +
                                   '<w:r><w:t xml:space="preserve">%s</w:t></w:r>' % escape(ln)
                                   for i, ln in enumerate(addr))
                ppr = '<w:pPr><w:spacing w:before="%d" w:after="0" w:line="240" w:lineRule="auto"/><w:ind w:left="%d" w:right="%d"/></w:pPr>' % (
                    0, 115, 115) if is_label else '<w:pPr><w:spacing w:after="0"/></w:pPr>'
                tcs += '<w:tc><w:tcPr><w:tcW w:w="%d" w:type="dxa"/>%s</w:tcPr><w:p>%s%s</w:p></w:tc>' % (
                    wd, '<w:vAlign w:val="center"/>' if is_label else "", ppr, text)
            trs += '<w:tr><w:trPr><w:cantSplit/><w:trHeight w:val="%d" w:hRule="exact"/></w:trPr>%s</w:tr>' % (
                _mm100_tw(vp), tcs)
        tbl = ('<w:tbl><w:tblPr><w:tblW w:w="0" w:type="auto"/><w:tblLayout w:type="fixed"/>'
               '<w:tblCellMar><w:left w:w="15" w:type="dxa"/><w:right w:w="15" w:type="dxa"/></w:tblCellMar>'
               '<w:tblLook w:val="0000"/></w:tblPr><w:tblGrid>%s</w:tblGrid>%s</w:tbl>' % (grid, trs))
        ed.move_caret("doc_start", False)
        ed.paste_fragment(tbl, True)
        # the paragraph after the table must not push a second page
        ed.move_caret("doc_end", False)
        ed.apply_para([("w:spacing", [("w:before", "0"), ("w:after", "0"), ("w:line", "20"), ("w:lineRule", "exact")])],
                      "Labels")
    finally:
        ed.end_group()
    _after(win)


def update_labels(win):
    """Copy the first label (with its merge fields) to every label, each after a
    Next Record field."""
    ed = _ed(win)
    cells = ed.table_cells(0)
    if not cells:
        return False
    label_cells = []
    for r in cells:
        for k, c in enumerate(r):
            if len(r) > 1 and len(r) % 2 == 1 and k % 2 == 1:
                continue        # the gap between labels
            label_cells.append(c)
    first = label_cells[0]
    if not first:
        return False
    last_len = None
    from . import docops
    lens = {p: len(t) for p, t, _l in docops.paragraphs(ed)}
    a, b = first[0], first[-1]
    ed.select_nodes(a, 0, b, lens.get(b, 0))
    frag = ed.copy_fragment()
    if not frag:
        return False
    ed.begin_group("Update Labels")
    try:
        for c in label_cells[1:]:
            if not c:
                continue
            lens = {p: len(t) for p, t, _l in docops.paragraphs(ed)}
            ed.select_nodes(c[0], 0, c[-1], lens.get(c[-1], 0))
            ed.paste_fragment(frag, True)
            # the Next Record field at the label's start
            cells2 = ed.table_cells(0)
            ed.goto_node(_same_cell(cells2, label_cells.index(c), cells)[0])
            ed.move_caret("line_start", False)
            ed.insert_code_field("NEXT")
    finally:
        ed.end_group()
    _after(win)
    return True


def _same_cell(cells2, i, cells):
    out = []
    for r in cells2:
        for k, c in enumerate(r):
            if len(r) > 1 and len(r) % 2 == 1 and k % 2 == 1:
                continue
            out.append(c)
    return out[i] if i < len(out) else out[-1]


def start(win, kind, label_index=0, envelope_index=0):
    """Start Mail Merge: letters / envelopes / labels / directory / normal."""
    ed = _ed(win)
    if kind == "normal":
        show_record(win, None)
        ed.set_settings_xml("w:mailMerge", None)
        _set_docvar(win, "FolioMergeInclude", "")
        return
    set_merge_type(win, kind)
    if kind == "envelopes":
        name, w, h = ENVELOPES[envelope_index]
        _page(ed, 0, w, h, 1000, 800, 1000, 800, True)
        ed.move_caret("doc_start", False)
        ed.apply_para([("w:ind", [("w:left", str(_mm100_tw(w * 0.42)))]),
                       ("w:spacing", [("w:before", str(_mm100_tw(h * 0.30)))])], "Envelope")
    elif kind == "labels":
        if not ed.table_cells(0):
            labels_document(win, "", label_index, True)
    _after(win)


# ================================================================ highlight
def field_rects(win):
    ed = _ed(win)
    out = []
    for instr, _res, para, a, b in ed.body_fields():
        k = instr.split(None, 1)[0].upper() if instr else ""
        if k in ("MERGEFIELD", "ADDRESSBLOCK", "GREETINGLINE", "IF", "MERGEREC", "MERGESEQ", "FILLIN", "REF") \
                and b < 2 ** 63:
            out += ed.range_rects(para, a, para, b)
    return out


def highlight(win, on):
    v = win.engine.view
    hid = getattr(win, "_merge_hl_id", 0)
    if hid:
        v.disconnect(hid)
        win._merge_hl_id = 0
    if on:
        def upd(*_):
            v.merge_shading = field_rects(win)
        win._merge_hl_id = v.connect("changed", upd)
        upd()
    else:
        v.merge_shading = []
    v.queue_draw()
