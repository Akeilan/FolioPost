"""Mailings: Envelopes, Labels and Mail Merge.

Recipients come from a CSV/TSV file or a list typed in the app. Merge fields
are the engine's user fields: outside preview they show <<Name>>, during
preview the current record's values. Finish & Merge builds a new document with
one copy (or one label) per record, fields turned into plain text."""
import csv
import json
import os
import re
import tempfile

from gi.repository import GLib, Gtk

from ._lazy import bridge, docapi
from .widgets import FDialog, LengthSpin, combo, grid, heading

PREFIX = "com.sun.star.text.fieldmaster.User."
OPEN, CLOSE = "«", "»"

ENVELOPES = [  # name, width, height (1/100 mm, landscape)
    ("Size 10  (4 1/8 x 9 1/2 in)", 24130, 10477),
    ("DL  (110 x 220 mm)", 22000, 11000),
    ("C5  (162 x 229 mm)", 22900, 16200),
    ("C6  (114 x 162 mm)", 16200, 11400),
    ("Monarch  (3 7/8 x 7 1/2 in)", 19050, 9843),
]

LABELS = [  # name, page w, h, label w, h, cols, rows, top, side, hpitch, vpitch (mm100)
    ("Address, 30 per page (2.625\" x 1\")", 21590, 27940, 6668, 2540, 3, 10,
     1270, 476, 6985, 2540),
    ("Shipping, 10 per page (4\" x 2\")", 21590, 27940, 10160, 5080, 2, 5,
     1270, 397, 10795, 5080),
    ("Address, 14 per page (4\" x 1.33\")", 21590, 27940, 10160, 3387, 2, 7,
     2117, 397, 10795, 3387),
    ("Shipping, 6 per page (4\" x 3.33\")", 21590, 27940, 10160, 8467, 2, 3,
     1270, 397, 10795, 8467),
    ("Return address, 80 per page (1.75\" x 0.5\")", 21590, 27940, 4445, 1270, 4, 20,
     1270, 762, 5207, 1270),
    ("A4 address, 21 per page (63.5 x 38.1 mm)", 21000, 29700, 6350, 3810, 3, 7,
     1515, 720, 6604, 3810),
    ("A4 address, 24 per page (64 x 33.9 mm)", 21000, 29700, 6400, 3390, 3, 8,
     1290, 700, 6600, 3390),
    ("A4 parcel, 8 per page (99.1 x 67.7 mm)", 21000, 29700, 9910, 6770, 2, 4,
     1310, 470, 10160, 6770),
]


# ------------------------------------------------------------------ recipients
def _setting(m, key, default=""):
    return docapi._doc_setting(m, key, default)


def _set(m, key, value):
    docapi._set_doc_setting(m, key, value)


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        rows = list(csv.reader(f, dialect))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        return [], []
    head = [h.strip() or "Column%d" % (i + 1) for i, h in enumerate(rows[0])]
    data = []
    for r in rows[1:]:
        r = r + [""] * (len(head) - len(r))
        data.append(dict(zip(head, r[:len(head)])))
    return head, data


def recipients(m):
    """(columns, records, included-flags) for the document's recipient list."""
    try:
        d = json.loads(_setting(m, "MergeData", "") or "{}")
    except ValueError:
        d = {}
    cols, rows = d.get("columns", []), d.get("rows", [])
    path = _setting(m, "MergeSource", "")
    if path and os.path.exists(path):
        try:
            cols, rows = read_csv(path)
        except Exception as e:
            print("recipients:", e)
    inc = d.get("include") or [True] * len(rows)
    if len(inc) != len(rows):
        inc = [True] * len(rows)
    return cols, rows, inc


def set_recipients(m, columns, rows, path="", include=None):
    _set(m, "MergeSource", path or "")
    _set(m, "MergeData", json.dumps({"columns": columns,
                                     "rows": [] if path else rows,
                                     "include": include or [True] * len(rows)}))


def set_included(m, include):
    try:
        d = json.loads(_setting(m, "MergeData", "") or "{}")
    except ValueError:
        d = {}
    d["include"] = include
    _set(m, "MergeData", json.dumps(d))


def merge_type(m):
    return _setting(m, "MergeType", "")


def set_merge_type(m, kind):
    _set(m, "MergeType", kind)


# ------------------------------------------------------------------ fields
def _master_name(col):
    return "Merge_" + re.sub(r"\W", "_", col)


def _master(m, col):
    fm = m.getTextFieldMasters()
    full = PREFIX + _master_name(col)
    if fm.hasByName(full):
        return fm.getByName(full)
    ma = m.createInstance("com.sun.star.text.fieldmaster.User")
    ma.Name = _master_name(col)
    ma.Content = OPEN + col + CLOSE
    try:
        ma.IsExpression = False
    except Exception:
        pass
    return ma


def merge_masters(m):
    """{column: master} for the merge fields of this document."""
    out = {}
    cols, _rows, _inc = recipients(m)
    by = {_master_name(c): c for c in cols}
    fm = m.getTextFieldMasters()
    for n in fm.getElementNames():
        if n.startswith(PREFIX + "Merge_"):
            short = n[len(PREFIX):]
            out[by.get(short, short[6:])] = fm.getByName(n)
    return out


def insert_field(m, col, text=None, cursor=None):
    vc = cursor or docapi.view_cursor(m)
    text = text or vc.getText()
    f = m.createInstance("com.sun.star.text.textfield.User")
    f.attachTextFieldMaster(_master(m, col))
    text.insertTextContent(vc, f, False)
    return f


def _find(cols, *names):
    low = {c.lower().replace(" ", "").replace("_", ""): c for c in cols}
    for n in names:
        c = low.get(n.lower().replace(" ", "").replace("_", ""))
        if c:
            return c
    return None


def address_columns(cols, m=None):
    """Lines of an address block as lists of columns (Match Fields decides
    which column is which)."""
    if m is not None:
        from .mailrules import matched_column
        mc = lambda f: matched_column(m, f, cols)   # noqa: E731
        title, first, last = mc("Courtesy Title"), mc("First Name"), mc("Last Name")
        company, a1, a2 = mc("Company"), mc("Address 1"), mc("Address 2")
        city, state, zipc = mc("City"), mc("State"), mc("Postal Code")
        country = mc("Country or Region")
        name = _find(cols, "Name", "Full Name")
    else:
        title = _find(cols, "Title", "Salutation")
        first = _find(cols, "First Name", "FirstName", "Given Name", "First")
        last = _find(cols, "Last Name", "LastName", "Surname", "Family Name", "Last")
        name = _find(cols, "Name", "Full Name")
        company = _find(cols, "Company", "Company Name", "Organization")
        a1 = _find(cols, "Address Line 1", "Address1", "Address", "Street")
        a2 = _find(cols, "Address Line 2", "Address2")
        city = _find(cols, "City", "Town")
        state = _find(cols, "State", "Province", "Region")
        zipc = _find(cols, "ZIP Code", "Zip", "Postal Code", "Postcode", "ZIP")
        country = _find(cols, "Country", "Country or Region")
    lines = []
    who = [c for c in (title, first, last) if c] or ([name] if name else [])
    if who:
        lines.append(who)
    for c in (company, a1, a2):
        if c:
            lines.append([c])
    tail = [c for c in (city, state, zipc) if c]
    if tail:
        lines.append(tail)
    if country:
        lines.append([country])
    return lines or [[c] for c in cols[:4]]


def insert_address_block(m):
    cols, _r, _i = recipients(m)
    if not cols:
        return False
    vc = docapi.view_cursor(m)
    text = vc.getText()
    um = m.getUndoManager()
    um.enterUndoContext("Address Block")
    try:
        lines = address_columns(cols, m)
        from .mailrules import matched_column
        city = matched_column(m, "City", cols)
        for i, line in enumerate(lines):
            if i:
                text.insertControlCharacter(vc, 1, False)    # line break
            for j, col in enumerate(line):
                if j:
                    # City, State ZIP
                    text.insertString(vc, ", " if line[j - 1] == city else " ", False)
                insert_field(m, col, text, vc)
    finally:
        um.leaveUndoContext()
    return True


def insert_greeting(m, salutation="Dear", punct=","):
    cols, _r, _i = recipients(m)
    vc = docapi.view_cursor(m)
    text = vc.getText()
    first = _find(cols, "First Name", "FirstName", "Given Name", "First", "Name")
    last = _find(cols, "Last Name", "LastName", "Surname")
    text.insertString(vc, salutation + " ", False)
    if first:
        insert_field(m, first, text, vc)
    if last and first != last:
        text.insertString(vc, " ", False)
        insert_field(m, last, text, vc)
    if not first and not last:
        text.insertString(vc, "Sir or Madam", False)
    text.insertString(vc, punct, False)


# ------------------------------------------------------------------ preview
def show_record(m, index):
    """Preview: fields show record `index`; None = field names."""
    cols, rows, _inc = recipients(m)
    masters = merge_masters(m)
    for col, ma in masters.items():
        if index is None or not rows:
            ma.Content = OPEN + col + CLOSE
        else:
            rec = rows[max(0, min(index, len(rows) - 1))]
            ma.Content = rec.get(col, "")
    try:
        from . import mailrules
        mailrules.preview(m, index, rows)
    except Exception as e:
        print("rules preview:", e)
    try:
        m.getTextFields().refresh()
    except Exception:
        pass


def find_recipient(m, needle, start=0):
    _cols, rows, _inc = recipients(m)
    n = needle.lower()
    for k in list(range(start, len(rows))) + list(range(0, start)):
        if any(n in str(v).lower() for v in rows[k].values()):
            return k
    return None


# ------------------------------------------------------------------ merge
def _desktop():
    return bridge.create("com.sun.star.frame.Desktop")


def _store(doc, path, fmt="writer8"):
    import uno
    doc.storeToURL(uno.systemPathToFileUrl(path), (bridge.prop("FilterName", fmt),))


def _load_hidden(path):
    import uno
    return _desktop().loadComponentFromURL(uno.systemPathToFileUrl(path), "_blank", 0,
                                           (bridge.prop("Hidden", True),))


def _unlink_merge_fields(doc, values, only_in=None):
    """Replace merge fields with text. values: {column: text}."""
    cols_by_master = {}
    fm = doc.getTextFieldMasters()
    for n in fm.getElementNames():
        if n.startswith(PREFIX + "Merge_"):
            cols_by_master[n[len(PREFIX):]] = n
    en = doc.getTextFields().createEnumeration()
    todo = []
    while en.hasMoreElements():
        f = en.nextElement()
        try:
            if not f.supportsService("com.sun.star.text.textfield.User"):
                continue
            name = f.getTextFieldMaster().Name
        except Exception:
            continue
        if not name.startswith("Merge_"):
            continue
        a = f.getAnchor()
        if only_in is not None and a.getText() != only_in:
            continue
        todo.append((f, a, name))
    by_master = {_master_name(c): v for c, v in values.items()}
    for f, a, name in todo:
        text = a.getText()
        cur = text.createTextCursorByRange(a)
        text.removeTextContent(f)
        value = by_master.get(name, "")
        text.insertString(cur, value, False)
        if not value:
            _drop_empty_line(text, cur)


def _drop_empty_line(text, cur):
    """An empty field alone on its line takes the line with it (no blank
    lines in an address block)."""
    try:
        left = text.createTextCursorByRange(cur.getStart())
        left.goLeft(1, True)
        right = text.createTextCursorByRange(cur.getStart())
        at_end = right.isEndOfParagraph()
        right.goRight(1, True)
        if left.getString() == "\n" and (at_end or right.getString() == "\n"):
            left.setString("")
        elif left.isStartOfParagraph() and right.getString() == "\n":
            right.setString("")
    except Exception as e:
        print("empty line:", e)


def merge(m, which="all", first=1, last=None, answers=None):
    """Build the merged document; returns its path (an .odt in temp)."""
    cols, rows, inc = recipients(m)
    if not rows:
        raise ValueError("There are no recipients.")
    idx = [i for i in range(len(rows)) if inc[i]]
    if which == "range":
        idx = [i for i in idx if first - 1 <= i <= (last or len(rows)) - 1]
    elif isinstance(which, int):
        idx = [which]
    if not idx:
        raise ValueError("No records were selected.")
    show_record(m, None)
    tmpdir = tempfile.mkdtemp(prefix="folio-merge-")
    template = os.path.join(tmpdir, "template.odt")
    _store(m, template)
    out = os.path.join(tmpdir, "merged.odt")
    kind = merge_type(m)
    doc = _load_hidden(template)
    try:
        if kind == "labels" and doc.getTextTables().getCount():
            _merge_labels(doc, template, [rows[i] for i in idx])
        else:
            from . import mailrules
            rule_defs = mailrules.rules(m)
            records = [dict(rows[i], __index=i + 1) for i in idx
                       if not mailrules.skipped(m, rows[i])]
            if not records:
                raise ValueError("Every record was skipped by a Skip Record If rule.")
            names = {_master_name(c): c for c in cols}
            ptr, seq = 0, 0
            while ptr < len(records):
                if seq:
                    text = doc.getText()
                    cur = text.createTextCursor()
                    cur.gotoEnd(False)
                    text.insertControlCharacter(cur, 0, False)
                    if kind != "directory":
                        cur.BreakType = bridge.enum("com.sun.star.style.BreakType",
                                                    "PAGE_BEFORE")
                    try:
                        import uno
                        cur.insertDocumentFromURL(uno.systemPathToFileUrl(template), ())
                    except Exception as e:
                        print("merge insert:", e)
                seq += 1
                ptr += mailrules.unlink(doc, rule_defs, records, ptr, seq, answers or {},
                                        names)
        for key in ("MergeSource", "MergeData", "MergeType"):
            try:
                doc.getDocumentProperties().getUserDefinedProperties().removeProperty(key)
            except Exception:
                pass
        _store(doc, out)
    finally:
        doc.close(True)
    return out


def _merge_labels(doc, template, records):
    """Labels: each cell takes the next record; pages repeat as needed."""
    t = doc.getTextTables().getByIndex(0)
    per_page = len(t.getCellNames())
    pages = max(1, (len(records) + per_page - 1) // per_page)
    import uno
    for _p in range(pages - 1):
        text = doc.getText()
        cur = text.createTextCursor()
        cur.gotoEnd(False)
        text.insertControlCharacter(cur, 0, False)
        cur.BreakType = bridge.enum("com.sun.star.style.BreakType", "PAGE_BEFORE")
        cur.insertDocumentFromURL(uno.systemPathToFileUrl(template), ())
    k = 0
    tables = doc.getTextTables()
    for ti in range(tables.getCount()):
        tb = tables.getByIndex(ti)
        for name in _cell_order(tb):
            cell = tb.getCellByName(name)
            if k < len(records):
                _unlink_merge_fields(doc, records[k], only_in=cell)
            else:
                cell.setString("")
            k += 1


def _cell_order(t):
    def key(n):
        mm = re.match(r"([A-Z]+)(\d+)", n)
        return (int(mm.group(2)), mm.group(1)) if mm else (0, n)
    return sorted(t.getCellNames(), key=key)


# ------------------------------------------------------------------ envelopes
def envelope(m, delivery, ret, size_index=0, omit_return=False, opts=None):
    """Put an envelope page at the start of the document. opts: fonts
    ('delivery_font'/'return_font': (name, size)) and positions
    ('delivery_left'/'delivery_top'/'return_left'/'return_top', 1/100 mm from
    the envelope's edge; None = automatic)."""
    opts = opts or {}
    name, w, h = ENVELOPES[size_index]
    fam = m.getStyleFamilies().getByName("PageStyles")
    pname = "Envelope"
    if not fam.hasByName(pname):
        ps = m.createInstance("com.sun.star.style.PageStyle")
        fam.insertByName(pname, ps)
    ps = fam.getByName(pname)
    ps.IsLandscape = True
    ps.Width, ps.Height = w, h
    ps.TopMargin = ps.LeftMargin = 1000
    ps.BottomMargin = ps.RightMargin = 800
    ps.HeaderIsOn = ps.FooterIsOn = False
    body_style = docapi.read_cursor(m).PageStyleName or "Standard"
    um = m.getUndoManager()
    um.enterUndoContext("Add Envelope")
    try:
        text = m.getText()
        cur = text.createTextCursor()
        cur.gotoStart(False)
        start = text.createTextCursorByRange(cur.getStart())
        # return address
        lines = [] if omit_return else ret.splitlines()
        for ln in lines:
            text.insertString(cur, ln, False)
            text.insertControlCharacter(cur, 1, False)
        text.insertControlCharacter(cur, 0, False)
        # delivery address, in the middle of the envelope
        for i, ln in enumerate(delivery.splitlines()):
            if i:
                text.insertControlCharacter(cur, 1, False)
            text.insertString(cur, ln, False)
        text.insertControlCharacter(cur, 0, False)
        # first paragraph: envelope page style; the delivery paragraph indented
        p = text.createEnumeration()
        first = p.nextElement()
        first.PageDescName = pname
        first.ParaBottomMargin = 0
        second = p.nextElement()
        second.ParaLeftMargin = int(w * 0.42)
        second.ParaTopMargin = int(h * 0.30)
        third = p.nextElement()
        third.PageDescName = body_style
        third.ParaLeftMargin = 0
        third.ParaTopMargin = 0
        if opts.get("delivery_left") is not None:
            second.ParaLeftMargin = max(0, int(opts["delivery_left"]) - ps.LeftMargin)
        if opts.get("delivery_top") is not None:
            used = 0 if omit_return else int(len(lines) * 450)
            second.ParaTopMargin = max(0, int(opts["delivery_top"]) - ps.TopMargin - used)
        if opts.get("return_left") is not None:
            first.ParaLeftMargin = max(0, int(opts["return_left"]) - ps.LeftMargin)
        if opts.get("return_top") is not None:
            first.ParaTopMargin = max(0, int(opts["return_top"]) - ps.TopMargin)
        for par, key in ((first, "return_font"), (second, "delivery_font")):
            f = opts.get(key)
            if f:
                c = par.getText().createTextCursorByRange(par.getStart())
                c.gotoEndOfParagraph(True)
                if f[0]:
                    c.CharFontName = f[0]
                if f[1]:
                    c.CharHeight = float(f[1])
        return start
    finally:
        um.leaveUndoContext()


def labels_document(m, address, label_index=0, full_page=True, row=1, col=1):
    """Fill a new (empty) document with a sheet of labels as a table."""
    (name, pw, ph, lw, lh, cols, rows, top, side, hp, vp) = LABELS[label_index]
    ps = docapi.page_style(m)
    ps.IsLandscape = False
    ps.Width, ps.Height = pw, ph
    ps.TopMargin, ps.BottomMargin = top, 0
    ps.LeftMargin, ps.RightMargin = side, max(0, pw - side - cols * hp + (hp - lw))
    ps.HeaderIsOn = ps.FooterIsOn = False
    vc = docapi.view_cursor(m)
    t = m.createInstance("com.sun.star.text.TextTable")
    t.initialize(rows, cols)
    vc.getText().insertTextContent(vc, t, False)
    t.HoriOrient = 3     # LEFT
    t.Width = cols * hp - (hp - lw)
    empty = bridge.struct("com.sun.star.table.BorderLine2")
    tb = t.TableBorder2
    for s in ("Top", "Bottom", "Left", "Right", "Horizontal", "Vertical"):
        setattr(tb, s + "Line", empty)
        setattr(tb, "Is%sLineValid" % s, True)
    t.TableBorder2 = tb
    for r in range(rows):
        rr = t.getRows().getByIndex(r)
        rr.IsAutoHeight = False
        rr.Height = vp
    for nm in t.getCellNames():
        c = t.getCellByName(nm)
        for side in ("TopBorder", "BottomBorder", "LeftBorder", "RightBorder"):
            setattr(c, side, empty)
        c.VertOrient = 2
        c.LeftBorderDistance = c.RightBorderDistance = 200
        cur = c.createTextCursor()
        cur.ParaStyleName = "Standard"
        cur.ParaBottomMargin = 0
        cur.ParaTopMargin = 0
    # the paragraph after the table must not push a second page
    try:
        body = m.getText()
        end = body.createTextCursor()
        end.gotoEnd(False)
        end.CharHeight = 1
        end.ParaTopMargin = end.ParaBottomMargin = 0
        ls = end.ParaLineSpacing
        ls.Mode, ls.Height = 3, 20      # fixed, 0.2 mm
        end.ParaLineSpacing = ls
    except Exception as e:
        print("labels end:", e)
    targets = _cell_order(t) if full_page else [_cell_name(row - 1, col - 1)]
    for nm in targets:
        if nm in t.getCellNames() and address:
            c = t.getCellByName(nm)
            ctext = c.getText()
            cur = ctext.createTextCursor()
            for i, ln in enumerate(address.splitlines()):
                if i:
                    ctext.insertControlCharacter(cur, 1, False)
                ctext.insertString(cur, ln, False)
    return t


def _cell_name(r, c):
    return "%s%d" % (chr(65 + c), r + 1)


def update_labels(m):
    """Copy the first label's content (with its merge fields) to every label."""
    tables = m.getTextTables()
    if not tables.getCount():
        return False
    t = tables.getByIndex(0)
    order = _cell_order(t)
    src = t.getCellByName(order[0])
    src_text = src.getText()
    # describe the first cell: runs of text and merge fields
    parts = []
    pen = src_text.createEnumeration()
    first_para = True
    while pen.hasMoreElements():
        para = pen.nextElement()
        if not first_para:
            parts.append(("para", None))
        first_para = False
        ren = para.createEnumeration()
        while ren.hasMoreElements():
            portion = ren.nextElement()
            kind = portion.TextPortionType
            if kind == "TextField":
                f = portion.TextField
                try:
                    parts.append(("field", f.getTextFieldMaster().Name))
                except Exception:
                    parts.append(("text", portion.getString()))
            elif kind == "Text":
                for i, chunk in enumerate(portion.getString().split("\n")):
                    if i:
                        parts.append(("br", None))
                    if chunk:
                        parts.append(("text", chunk))
    cols, _r, _i = recipients(m)
    by_master = {_master_name(c): c for c in cols}
    for nm in order[1:]:
        c = t.getCellByName(nm)
        ctext = c.getText()
        ctext.setString("")
        cur = ctext.createTextCursor()
        if merge_type(m) == "labels":
            ctext.insertString(cur, "", False)
        for kind, val in parts:
            if kind == "text":
                ctext.insertString(cur, val, False)
            elif kind == "br":
                ctext.insertControlCharacter(cur, 1, False)
            elif kind == "para":
                ctext.insertControlCharacter(cur, 0, False)
            elif kind == "field":
                col = by_master.get(val, val[6:] if val.startswith("Merge_") else val)
                insert_field(m, col, ctext, cur)
    return True


def start(m, kind, label_index=0, envelope_index=0):
    """Start Mail Merge: letters / envelopes / labels / directory / normal."""
    if kind == "normal":
        show_record(m, None)
        for key in ("MergeSource", "MergeData", "MergeType"):
            try:
                m.getDocumentProperties().getUserDefinedProperties().removeProperty(key)
            except Exception:
                pass
        return
    set_merge_type(m, kind)
    if kind == "envelopes":
        name, w, h = ENVELOPES[envelope_index]
        ps = docapi.page_style(m)
        ps.IsLandscape = True
        ps.Width, ps.Height = w, h
        ps.TopMargin = ps.LeftMargin = 1000
        ps.BottomMargin = ps.RightMargin = 800
        text = m.getText()
        en = text.createEnumeration()
        p = en.nextElement()
        p.ParaLeftMargin = int(w * 0.42)
        p.ParaTopMargin = int(h * 0.30)
    elif kind == "labels":
        if not m.getTextTables().getCount():
            labels_document(m, "", label_index, True)


def highlight_fields(on):
    """Grey shading behind fields (Highlight Merge Fields)."""
    from .app import COLOR_SCHEME
    try:
        import uno
        prov = bridge.create("com.sun.star.configuration.ConfigurationProvider")
        arg = uno.createUnoStruct("com.sun.star.beans.PropertyValue")
        arg.Name, arg.Value = "nodepath", COLOR_SCHEME + "/WriterFieldShadings"
        acc = prov.createInstanceWithArguments(
            "com.sun.star.configuration.ConfigurationUpdateAccess", (arg,))
        acc.setPropertyValue("IsVisible", bool(on))
        acc.commitChanges()
        return True
    except Exception as e:
        print("highlight fields:", e)
        return False
