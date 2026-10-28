"""Document operations that work on the engine's document model directly.

Everything here takes the model (engine.model) and does the work in one
go. Lengths are in 1/100 mm unless stated otherwise.
"""
import datetime
import os
import re

from . import bridge

MM100_PER_INCH = 2540
MATH_CLSID = "078B7ABA-54FC-457F-8551-6147e776a997"


def inch(v):
    return int(round(v * MM100_PER_INCH))


def pt(v):
    return int(round(v * 2540 / 72))


def to_pt(mm100):
    return mm100 * 72 / 2540.0


# ------------------------------------------------------------------ basics
def controller(m):
    return m.getCurrentController()


def read_cursor(m):
    """The text cursor for reading (page style, language, table...). Unlike
    view_cursor it never changes the selection, so a selected picture stays
    selected."""
    return controller(m).getViewCursor()


def view_cursor(m):
    """The text cursor. If an object (shape, picture, equation) is selected,
    the cursor moves to the object's anchor first, as text commands expect."""
    ctl = controller(m)
    try:
        sel = ctl.getSelection()
        if sel is None or sel.supportsService("com.sun.star.text.TextRanges"):
            return ctl.getViewCursor()
    except Exception:
        pass
    sel = ctl.getSelection()
    anchor = None
    try:
        if hasattr(sel, "getAnchor"):
            anchor = sel.getAnchor()
        elif hasattr(sel, "getCount") and sel.getCount():
            first = sel.getByIndex(0)
            anchor = first.getAnchor()
    except Exception:
        anchor = None
    if anchor is None:
        anchor = m.getText().getStart()
    try:
        ctl.select(anchor.getText().createTextCursorByRange(anchor.getStart()))
        vc = ctl.getViewCursor()
        vc.getStart()
        return vc
    except Exception:
        pass
    # still in a drawing mode: leave it, like pressing Esc
    try:
        helper = bridge.create("com.sun.star.frame.DispatchHelper")
        for _ in range(2):
            helper.executeDispatch(ctl.getFrame(), ".uno:Escape", "", 0, ())
        ctl.select(m.getText().createTextCursorByRange(anchor))
    except Exception:
        pass
    return ctl.getViewCursor()


def page_style(m):
    name = read_cursor(m).PageStyleName or "Standard"
    return m.getStyleFamilies().getByName("PageStyles").getByName(name)


def para_styles(m):
    return m.getStyleFamilies().getByName("ParagraphStyles")


def char_styles(m):
    return m.getStyleFamilies().getByName("CharacterStyles")


def locale(lang="en", country="US"):
    return bridge.struct("com.sun.star.lang.Locale", Language=lang, Country=country)


def doc_locale(m):
    try:
        loc = read_cursor(m).CharLocale
        if loc.Language:
            return loc
    except Exception:
        pass
    return locale()


def selection_text(m):
    sel = controller(m).getSelection()
    try:
        if sel.supportsService("com.sun.star.text.TextRanges"):
            return "".join(sel.getByIndex(i).getString() for i in range(sel.getCount()))
    except Exception:
        pass
    return ""


def select(m, rng):
    controller(m).select(rng)


def goto(m, rng, expand=False):
    vc = view_cursor(m)
    vc.gotoRange(rng, expand)


# ------------------------------------------------------------- page setup
def page_setup(m):
    ps = page_style(m)
    cols = 1
    try:
        cols = ps.TextColumns.getColumnCount() or 1
    except Exception:
        pass
    return {"width": ps.Width, "height": ps.Height, "top": _body_margin(ps, "top"),
            "bottom": _body_margin(ps, "bottom"), "left": ps.LeftMargin,
            "right": ps.RightMargin,
            "landscape": bool(ps.IsLandscape), "columns": cols,
            "header": bool(ps.HeaderIsOn), "footer": bool(ps.FooterIsOn),
            "header_dist": ps.HeaderBodyDistance if ps.HeaderIsOn else 0,
            "gutter": getattr(ps, "GutterMargin", 0),
            "different_first": False, "name": ps.Name}


def set_page(m, width=None, height=None, top=None, bottom=None, left=None, right=None,
             landscape=None, columns=None, gutter=None):
    ps = page_style(m)
    if landscape is not None and bool(ps.IsLandscape) != landscape:
        w, h = ps.Width, ps.Height
        ps.IsLandscape = landscape
        if (landscape and w < h) or (not landscape and w > h):
            ps.Width, ps.Height = h, w
    if width is not None and height is not None:
        if ps.IsLandscape:
            width, height = max(width, height), min(width, height)
        else:
            width, height = min(width, height), max(width, height)
        ps.Width, ps.Height = width, height
    for k, v in (("LeftMargin", left), ("RightMargin", right)):
        if v is not None:
            setattr(ps, k, int(v))
    if top is not None:
        _set_body_margin(ps, "top", top)
    if bottom is not None:
        _set_body_margin(ps, "bottom", bottom)
    if gutter is not None:
        try:
            ps.GutterMargin = int(gutter)
        except Exception:
            pass
    if columns is not None:
        tc = ps.TextColumns
        tc.setColumnCount(max(1, int(columns)))
        try:
            tc.AutomaticDistance = inch(0.5)
        except Exception:
            pass
        ps.TextColumns = tc


def page_color(m, color):
    ps = page_style(m)
    if color is None or color < 0:
        ps.FillStyle = bridge.enum("com.sun.star.drawing.FillStyle", "NONE")
        return
    ps.FillStyle = bridge.enum("com.sun.star.drawing.FillStyle", "SOLID")
    ps.FillColor = int(color)
    try:
        ps.BackgroundFullSize = True
    except Exception:
        pass


def _line(width_pt=0.5, color=0, style=0):
    w = int(round(width_pt * 2540 / 72))
    return bridge.struct("com.sun.star.table.BorderLine2", Color=color, LineWidth=w,
                         OuterLineWidth=w, LineStyle=style)


def page_border(m, kind="box", width_pt=0.5, color=0, style=0):
    """kind: none | box | shadow"""
    ps = page_style(m)
    line = _line(width_pt, color, style) if kind != "none" else _line(0)
    if kind == "none":
        line = bridge.struct("com.sun.star.table.BorderLine2")
    for side in ("LeftBorder", "RightBorder", "TopBorder", "BottomBorder"):
        setattr(ps, side, line)
    dist = pt(24) if kind != "none" else 0
    for side in ("LeftBorderDistance", "RightBorderDistance", "TopBorderDistance",
                 "BottomBorderDistance"):
        try:
            setattr(ps, side, dist)
        except Exception:
            pass
    sh = bridge.struct("com.sun.star.table.ShadowFormat")
    if kind == "shadow":
        sh.Location = bridge.enum("com.sun.star.table.ShadowLocation", "BOTTOM_RIGHT")
        sh.ShadowWidth = pt(4)
        sh.Color = 0x808080
    ps.ShadowFormat = sh


def para_border(m, sides, width_pt=0.5, color=0):
    """sides: set of 'top','bottom','left','right' ('none' clears all) on the
    selected paragraphs."""
    vc = view_cursor(m)
    line = _line(width_pt, color)
    empty = bridge.struct("com.sun.star.table.BorderLine2")
    for side, prop in (("top", "TopBorder"), ("bottom", "BottomBorder"),
                       ("left", "LeftBorder"), ("right", "RightBorder")):
        setattr(vc, prop, line if side in sides else empty)
    for prop in ("TopBorderDistance", "BottomBorderDistance", "LeftBorderDistance",
                 "RightBorderDistance"):
        setattr(vc, prop, pt(1) if sides else 0)


def line_numbering(m, mode):
    """mode: none | continuous | page | section | suppress"""
    if mode == "suppress":
        view_cursor(m).ParaLineNumberCount = False
        return
    ln = m.getLineNumberingProperties()
    if mode == "none":
        ln.IsOn = False
        return
    ln.IsOn = True
    ln.CountEmptyLines = False
    ln.Interval = 1
    ln.Distance = inch(0.25)
    ln.RestartAtEachPage = mode == "page"
    view_cursor(m).ParaLineNumberCount = True
    try:
        from .dlg_doc import set_line_number_starts
        set_line_number_starts(m, 1, mode == "section")
    except Exception as e:
        print("line numbers:", e)


def hyphenation(m, auto):
    st = para_styles(m).getByName("Standard")
    st.ParaIsHyphenation = bool(auto)


def drop_cap(m, mode, lines=3, distance=0):
    vc = view_cursor(m)
    fmt = bridge.struct("com.sun.star.style.DropCapFormat")
    if mode != "none":
        fmt.Lines = max(2, min(10, int(lines)))
        fmt.Count = 1
        fmt.Distance = int(distance)
    vc.DropCapFormat = fmt
    vc.DropCapWholeWord = False


# ------------------------------------------------------------- statistics
def statistics(m):
    stats = {p.Name: p.Value for p in m.getDocumentProperties().DocumentStatistics}
    text = m.getText().getString()
    stats["LineCount"] = None
    try:
        vc = view_cursor(m)
        stats["Page"] = vc.getPage()
    except Exception:
        pass
    stats["Text"] = text
    return stats


def count_text(text):
    words = len(re.findall(r"\S+", text))
    chars = len(text.replace("\n", "").replace("\r", ""))
    nospace = len(re.sub(r"\s", "", text))
    paras = len([p for p in re.split(r"[\r\n]+", text) if p.strip()])
    return {"words": words, "chars": chars, "nospace": nospace, "paras": paras}


# ------------------------------------------------------------ properties
def doc_properties(m):
    p = m.getDocumentProperties()

    def dt(d):
        try:
            if d.Year:
                return datetime.datetime(d.Year, d.Month, d.Day, d.Hours, d.Minutes)
        except Exception:
            pass
        return None
    return {"title": p.Title, "subject": p.Subject, "author": p.Author,
            "keywords": ", ".join(p.Keywords), "comments": p.Description,
            "modified_by": p.ModifiedBy, "created": dt(p.CreationDate),
            "modified": dt(p.ModificationDate), "printed": dt(p.PrintDate),
            "revision": p.EditingCycles, "editing_minutes": p.EditingDuration // 60,
            "template": p.TemplateName}


def set_doc_property(m, key, value):
    p = m.getDocumentProperties()
    if key == "title":
        p.Title = value
    elif key == "subject":
        p.Subject = value
    elif key == "author":
        p.Author = value
    elif key == "keywords":
        p.Keywords = tuple(k.strip() for k in value.split(",") if k.strip())
    elif key == "comments":
        p.Description = value


def stamp_created(m):
    import time
    now = time.localtime()
    dt = bridge.struct("com.sun.star.util.DateTime", Year=now.tm_year, Month=now.tm_mon,
                       Day=now.tm_mday, Hours=now.tm_hour, Minutes=now.tm_min,
                       Seconds=now.tm_sec)
    p = m.getDocumentProperties()
    p.CreationDate = dt
    p.ModificationDate = dt


def set_author(m, name):
    p = m.getDocumentProperties()
    if not p.Author:
        p.Author = name


# ------------------------------------------------------------- headings
def headings(m, max_level=9):
    """[(level, text, paragraph)] for the body text."""
    out = []
    enum = m.getText().createEnumeration()
    while enum.hasMoreElements():
        par = enum.nextElement()
        try:
            if not par.supportsService("com.sun.star.text.Paragraph"):
                continue
            lvl = par.OutlineLevel
        except Exception:
            continue
        if lvl and lvl <= max_level:
            txt = par.getString().strip()
            if txt:
                out.append((lvl, txt, par))
    return out


def goto_start(m, rng):
    vc = view_cursor(m)
    vc.gotoRange(rng.getStart(), False)


# ------------------------------------------------------------ bookmarks
def bookmarks(m):
    bms = m.getBookmarks()
    return [n for n in bms.getElementNames() if not n.startswith("_")]


def add_bookmark(m, name):
    bms = m.getBookmarks()
    if bms.hasByName(name):
        old = bms.getByName(name)
        old.getAnchor().getText().removeTextContent(old)
    vc = view_cursor(m)
    bm = m.createInstance("com.sun.star.text.Bookmark")
    bm.setName(name)
    vc.getText().insertTextContent(vc, bm, not vc.isCollapsed())


def goto_bookmark(m, name):
    bms = m.getBookmarks()
    if bms.hasByName(name):
        goto(m, bms.getByName(name).getAnchor())
        return True
    return False


def delete_bookmark(m, name):
    bms = m.getBookmarks()
    if bms.hasByName(name):
        bm = bms.getByName(name)
        bm.getAnchor().getText().removeTextContent(bm)


# ------------------------------------------------------------- hyperlink
def selected_link(m):
    vc = view_cursor(m)
    try:
        return vc.HyperLinkURL or ""
    except Exception:
        return ""


def set_link(m, url, text=None, tip="", target=""):
    vc = view_cursor(m)
    if text is not None and (vc.isCollapsed() or vc.getString() != text):
        vc.setString(text)
    vc.HyperLinkURL = url
    vc.HyperLinkTarget = target or ""
    try:
        vc.HyperLinkName = tip or ""
    except Exception:
        pass
    if vc.isCollapsed() is False:
        vc.collapseToEnd()


def remove_link(m):
    vc = view_cursor(m)
    if vc.isCollapsed():
        # whole link around the cursor
        cur = vc.getText().createTextCursorByRange(vc)
        url = vc.HyperLinkURL
        if not url:
            return
        while cur.goLeft(1, True) and cur.HyperLinkURL == url:
            pass
        cur.collapseToEnd()
        cur.goRight(0, False)
        start = vc.getText().createTextCursorByRange(vc)
        while start.goLeft(1, False):
            t = vc.getText().createTextCursorByRange(start)
            if not t.goRight(1, True) or t.HyperLinkURL != url:
                start.goRight(1, False)
                break
        end = vc.getText().createTextCursorByRange(vc)
        while True:
            t = vc.getText().createTextCursorByRange(end)
            if not t.goRight(1, True) or t.HyperLinkURL != url:
                break
            end.goRight(1, False)
        rng = vc.getText().createTextCursorByRange(start)
        rng.gotoRange(end, True)
        rng.HyperLinkURL = ""
        return
    vc.HyperLinkURL = ""


# ---------------------------------------------------------------- fields
def _number_format(m, code):
    fmts = m.getNumberFormats()
    loc = doc_locale(m)
    key = fmts.queryKey(code, loc, False)
    if key == -1:
        key = fmts.addNew(code, loc)
    return key


def insert_field(m, kind, fixed=False, fmt=None):
    vc = view_cursor(m)
    text = vc.getText()
    svc = {"page": "PageNumber", "pages": "PageCount", "date": "DateTime",
           "time": "DateTime", "author": "Author", "title": "docinfo.Title",
           "filename": "FileName", "words": "WordCount", "subject": "docinfo.Subject",
           "created": "docinfo.CreateDateTime", "saved": "docinfo.ChangeDateTime"}[kind]
    f = m.createInstance("com.sun.star.text.textfield." + svc)
    if kind == "page":
        f.NumberingType = 4   # ARABIC
        f.SubType = bridge.enum("com.sun.star.text.PageNumberType", "CURRENT")
    elif kind == "pages":
        f.NumberingType = 4
    elif kind in ("date", "time"):
        f.IsDate = kind == "date"
        f.IsFixed = bool(fixed)
        if fmt:
            f.NumberFormat = _number_format(m, fmt)
    elif kind == "author":
        f.IsFixed = bool(fixed)
        f.FullName = True
    elif kind == "filename":
        f.FileFormat = 1      # name with extension
    elif kind in ("created", "saved"):
        try:
            f.IsDate = True
        except Exception:
            pass
    text.insertTextContent(vc, f, not vc.isCollapsed())
    return f


def enable_header_footer(m, which, ps=None):
    """Turn a header/footer on the way the original does: it sits 0.5" from the
    page edge, inside the margin, and the body text doesn't move."""
    ps = ps or page_style(m)
    key = "Header" if which == "header" else "Footer"
    if getattr(ps, key + "IsOn"):
        return
    margin = "TopMargin" if key == "Header" else "BottomMargin"
    body = getattr(ps, margin)
    setattr(ps, key + "IsOn", True)
    edge = min(1270, max(body // 2, 0))
    try:
        setattr(ps, key + "IsDynamicHeight", True)
        setattr(ps, key + "BodyDistance", 0)
        setattr(ps, margin, edge)
        setattr(ps, key + "Height", max(body - edge, 300))
    except Exception as e:
        print("header geometry:", e)


def insert_header_footer(m, which, page_numbers=None, align="center", text=""):
    """Turn on the header or footer and optionally put a page number in it."""
    ps = page_style(m)
    key = "Header" if which == "header" else "Footer"
    enable_header_footer(m, which, ps)
    if page_numbers:
        body = getattr(ps, key + "Text")
        body.setString("")
        cur = body.createTextCursor()
        cur.ParaAdjust = {"left": 0, "right": 1, "center": 3}[align]
        f = m.createInstance("com.sun.star.text.textfield.PageNumber")
        f.NumberingType = 4
        f.SubType = bridge.enum("com.sun.star.text.PageNumberType", "CURRENT")
        if page_numbers == "page-x-of-y":
            body.insertString(cur, "Page ", False)
            body.insertTextContent(cur, f, False)
            body.insertString(cur, " of ", False)
            c = m.createInstance("com.sun.star.text.textfield.PageCount")
            c.NumberingType = 4
            body.insertTextContent(cur, c, False)
        else:
            body.insertTextContent(cur, f, False)
    elif text:
        getattr(ps, key + "Text").setString(text)


def remove_header_footer(m, which, ps=None):
    """Turn the header/footer off; the body keeps its position."""
    ps = ps or page_style(m)
    key = "Header" if which == "header" else "Footer"
    if not getattr(ps, key + "IsOn"):
        return
    margin = "TopMargin" if key == "Header" else "BottomMargin"
    body = getattr(ps, margin) + getattr(ps, key + "Height")
    setattr(ps, key + "IsOn", False)
    setattr(ps, margin, body)


def _body_margin(ps, side):
    """Word-style margin (page edge to body text) for 'top'/'bottom'."""
    key = "Header" if side == "top" else "Footer"
    margin = "TopMargin" if side == "top" else "BottomMargin"
    v = getattr(ps, margin)
    if getattr(ps, key + "IsOn"):
        v += getattr(ps, key + "Height")
    return v


def _set_body_margin(ps, side, value):
    key = "Header" if side == "top" else "Footer"
    margin = "TopMargin" if side == "top" else "BottomMargin"
    value = int(value)
    if getattr(ps, key + "IsOn"):
        edge = min(getattr(ps, margin), max(value - 300, 0))
        setattr(ps, margin, edge)
        setattr(ps, key + "Height", max(value - edge, 300))
    else:
        setattr(ps, margin, value)


def remove_page_numbers(m):
    ps = page_style(m)
    for key in ("Header", "Footer"):
        if getattr(ps, key + "IsOn"):
            body = getattr(ps, key + "Text")
            fields = body.createEnumeration()
            # remove PageNumber/PageCount fields inside the header/footer
            while fields.hasMoreElements():
                par = fields.nextElement()
                portions = par.createEnumeration()
                while portions.hasMoreElements():
                    por = portions.nextElement()
                    if por.TextPortionType == "TextField":
                        f = por.TextField
                        if f.supportsService("com.sun.star.text.textfield.PageNumber") or \
                                f.supportsService("com.sun.star.text.textfield.PageCount"):
                            body.removeTextContent(f)


# ---------------------------------------------------------- toc & captions
def insert_toc(m, title="Contents", levels=3, links=True):
    vc = view_cursor(m)
    idx = m.createInstance("com.sun.star.text.ContentIndex")
    idx.CreateFromOutline = True
    idx.Level = levels
    idx.Title = title
    if links:
        try:
            lf = idx.LevelFormat
            new = [lf.getByIndex(0)]
            for i in range(1, lf.getCount()):
                tokens = list(lf.getByIndex(i))
                toks = [tuple(t) for t in tokens]
                start = (bridge.prop("TokenType", "TokenHyperlinkStart"),)
                end = (bridge.prop("TokenType", "TokenHyperlinkEnd"),)
                if toks:
                    toks = [start] + toks + [end]
                new.append(tuple(toks))
            import uno
            for i in range(1, lf.getCount()):
                uno.invoke(lf, "replaceByIndex", (i, uno.Any(
                    "[][]com.sun.star.beans.PropertyValue", new[i])))
            idx.LevelFormat = lf
        except Exception as e:
            print("toc links:", e)
    vc.getText().insertTextContent(vc, idx, False)
    idx.update()
    return idx


def tocs(m):
    out = []
    ix = m.getDocumentIndexes()
    for i in range(ix.getCount()):
        x = ix.getByIndex(i)
        if x.supportsService("com.sun.star.text.ContentIndex"):
            out.append(x)
    return out


def update_indexes(m):
    ix = m.getDocumentIndexes()
    for i in range(ix.getCount()):
        ix.getByIndex(i).update()
    try:
        m.getTextFields().refresh()
    except Exception:
        pass


def remove_toc(m):
    for x in tocs(m):
        x.getAnchor().getText().removeTextContent(x)


def add_text_to_toc(m, level):
    """Word's 'Add Text': make the paragraph a heading of that level, or
    leave it out of the table of contents (level 0)."""
    vc = view_cursor(m)
    if level == 0:
        vc.ParaStyleName = "Standard"
        vc.OutlineLevel = 0
    else:
        vc.ParaStyleName = "Heading %d" % level


def _seq_master(m, name):
    fm = m.getTextFieldMasters()
    key = "com.sun.star.text.fieldmaster.SetExpression." + name
    if fm.hasByName(key):
        return fm.getByName(key)
    master = m.createInstance("com.sun.star.text.fieldmaster.SetExpression")
    master.Name = name
    master.SubType = 0     # sequence
    return master


def insert_caption(m, label="Figure", text="", below=True, numtype=4, chapter=None,
                   exclude_label=False):
    """chapter: (outline level 1-9, separator) to number as 'Figure 1-1'."""
    vc = view_cursor(m)
    body = vc.getText()
    cur = body.createTextCursorByRange(vc)
    if below is None:
        cur.gotoStartOfParagraph(False)     # an empty paragraph made for it
    elif below:
        cur.gotoEndOfParagraph(False)
        body.insertControlCharacter(cur, 0, False)    # paragraph break
    else:
        cur.gotoStartOfParagraph(False)
        body.insertControlCharacter(cur, 0, False)
        cur.gotoPreviousParagraph(False)
    cur.ParaStyleName = "Caption"
    if not exclude_label:
        body.insertString(cur, label + " ", False)
    master = _seq_master(m, label)
    if chapter:
        try:
            master.ChapterNumberingLevel = int(chapter[0]) - 1
            master.NumberingSeparator = chapter[1]
        except Exception as e:
            print("caption chapter:", e)
    f = m.createInstance("com.sun.star.text.textfield.SetExpression")
    f.attachTextFieldMaster(master)
    f.NumberingType = numtype
    f.Content = label + "+1"
    body.insertTextContent(cur, f, False)
    if text:
        body.insertString(cur, (": " if not text.startswith((":", ".", " ")) else "") + text,
                          False)
    try:
        m.getTextFields().refresh()
    except Exception:
        pass


def references(m):
    """Targets for a cross-reference: {'Heading': [...], 'Bookmark': [...],
    'Figure': [...], 'Table': [...], ...}"""
    out = {"Heading": [(t, "h%d" % i) for i, (_l, t, _p) in enumerate(headings(m))],
           "Bookmark": [(b, b) for b in bookmarks(m)]}
    seqs = {}
    en = m.getTextFields().createEnumeration()
    while en.hasMoreElements():
        f = en.nextElement()
        try:
            if f.supportsService("com.sun.star.text.textfield.SetExpression") and \
                    f.SubType == 0:
                name = f.TextFieldMaster.Name
                par = f.getAnchor().getText().createTextCursorByRange(f.getAnchor())
                par.gotoStartOfParagraph(False)
                par.gotoEndOfParagraph(True)
                seqs.setdefault(name, []).append((par.getString(), f.SequenceValue))
        except Exception:
            continue
    out.update(seqs)
    return out


def insert_cross_reference(m, kind, target, part="text", hyperlink=True, above=False):
    vc = view_cursor(m)
    f = m.createInstance("com.sun.star.text.textfield.GetReference")
    # com.sun.star.text.ReferenceFieldPart
    parts = {"text": 2, "page": 0, "above": 3, "number": 8, "number-no-context": 9,
             "number-full": 10, "label-number": 5, "caption-only": 6}
    if kind == "Bookmark":
        f.ReferenceFieldSource = 2
        f.SourceName = target
    elif kind == "Heading":
        # bookmark the heading so the reference survives saving
        idx = int(target[1:])
        _lvl, text, par = headings(m)[idx]
        name = "_Ref_" + re.sub(r"\W+", "_", text)[:30] + "_%d" % idx
        bms = m.getBookmarks()
        if not bms.hasByName(name):
            bm = m.createInstance("com.sun.star.text.Bookmark")
            bm.setName(name)
            par.getText().insertTextContent(par, bm, True)
        f.ReferenceFieldSource = 2
        f.SourceName = name
    else:
        f.ReferenceFieldSource = 1    # sequence field
        f.SourceName = kind
        f.SequenceNumber = int(target)
    f.ReferenceFieldPart = parts.get(part, 2)
    text = vc.getText()
    start = text.createTextCursorByRange(vc.getStart())
    text.insertTextContent(vc, f, False)
    if above and part != "above":
        g = m.createInstance("com.sun.star.text.textfield.GetReference")
        g.ReferenceFieldSource = f.ReferenceFieldSource
        g.SourceName = f.SourceName
        try:
            g.SequenceNumber = f.SequenceNumber
        except Exception:
            pass
        g.ReferenceFieldPart = 3
        text.insertString(vc, " ", False)
        text.insertTextContent(vc, g, False)
    try:
        m.getTextFields().refresh()
    except Exception:
        pass
    if hyperlink and f.ReferenceFieldSource == 2:
        try:
            a = f.getAnchor()
            rng = text.createTextCursorByRange(a.getStart())
            rng.gotoRange(a.getEnd(), True)
            rng.HyperLinkURL = "#" + f.SourceName
        except Exception as e:
            print("reference link:", e)
    return f


# ------------------------------------------------- footnotes and comments
def _anchors(m, kind):
    out = []
    if kind == "footnote":
        c = m.getFootnotes()
        out = [c.getByIndex(i).getAnchor() for i in range(c.getCount())]
    elif kind == "endnote":
        c = m.getEndnotes()
        out = [c.getByIndex(i).getAnchor() for i in range(c.getCount())]
    elif kind == "comment":
        en = m.getTextFields().createEnumeration()
        while en.hasMoreElements():
            f = en.nextElement()
            if f.supportsService("com.sun.star.text.textfield.Annotation"):
                out.append(f.getAnchor())
    return out


def goto_next(m, kind, forward=True):
    """Move to the next/previous footnote, endnote or comment anchor."""
    vc = view_cursor(m)
    body = m.getText()
    anchors = []
    for a in _anchors(m, kind):
        try:
            if a.getText() == body or True:
                anchors.append(a)
        except Exception:
            pass
    best = None
    for a in anchors:
        try:
            cmp = body.compareRegionStarts(vc, a)
        except Exception:
            continue
        # cmp: 1 if vc before a, -1 if after, 0 equal
        if forward and cmp == 1:
            if best is None or body.compareRegionStarts(a, best) == 1:
                best = a
        elif not forward and cmp == -1:
            if best is None or body.compareRegionStarts(a, best) == -1:
                best = a
    if best is not None:
        vc.gotoRange(best.getStart(), False)
        return True
    return False


def delete_comments(m, only_current=False):
    en = m.getTextFields().createEnumeration()
    victims = []
    while en.hasMoreElements():
        f = en.nextElement()
        if f.supportsService("com.sun.star.text.textfield.Annotation"):
            victims.append(f)
    for f in victims:
        f.getAnchor().getText().removeTextContent(f)


def comments(m):
    out = []
    en = m.getTextFields().createEnumeration()
    while en.hasMoreElements():
        f = en.nextElement()
        if f.supportsService("com.sun.star.text.textfield.Annotation"):
            out.append({"author": f.Author, "text": f.Content, "field": f})
    return out


# ---------------------------------------------------------------- styles
STYLE_PROPS = ("CharFontName", "CharHeight", "CharWeight", "CharPosture", "CharColor",
               "CharUnderline", "ParaAdjust", "ParaTopMargin", "ParaBottomMargin",
               "ParaLeftMargin", "ParaRightMargin", "ParaFirstLineIndent")


def style_info(m, name, family="ParagraphStyles"):
    fam = m.getStyleFamilies().getByName(family)
    if not fam.hasByName(name):
        return None
    st = fam.getByName(name)
    info = {"name": st.Name, "display": st.DisplayName, "parent": st.ParentStyle,
            "in_use": st.isInUse(), "user": st.isUserDefined()}
    for p in STYLE_PROPS:
        try:
            info[p] = getattr(st, p)
        except Exception:
            pass
    try:
        info["follow"] = st.FollowStyle
        ls = st.ParaLineSpacing
        info["line_mode"], info["line_height"] = ls.Mode, ls.Height
    except Exception:
        pass
    return info


def set_style(m, name, family="ParagraphStyles", **props):
    fam = m.getStyleFamilies().getByName(family)
    st = fam.getByName(name)
    for k, v in props.items():
        if k == "line":
            mode, height = v
            ls = st.ParaLineSpacing
            ls.Mode, ls.Height = mode, height
            st.ParaLineSpacing = ls
        else:
            setattr(st, k, v)


def new_style(m, name, based_on="Standard", follow=None, family="ParagraphStyles",
              from_selection=True, **props):
    fam = m.getStyleFamilies().getByName(family)
    if not fam.hasByName(name):
        svc = "com.sun.star.style.ParagraphStyle" if family == "ParagraphStyles" \
            else "com.sun.star.style.CharacterStyle"
        st = m.createInstance(svc)
        fam.insertByName(name, st)
    st = fam.getByName(name)
    if based_on:
        try:
            st.ParentStyle = based_on
        except Exception:
            pass
    if follow and family == "ParagraphStyles":
        st.FollowStyle = follow
    if from_selection:
        vc = view_cursor(m)
        for p in STYLE_PROPS:
            if family == "CharacterStyles" and p.startswith("Para"):
                continue
            try:
                setattr(st, p, getattr(vc, p))
            except Exception:
                pass
    set_style(m, name, family, **props) if props else None
    vc = view_cursor(m)
    if family == "ParagraphStyles":
        vc.ParaStyleName = name
    else:
        vc.CharStyleName = name
    return name


def update_style_to_match(m, name):
    vc = view_cursor(m)
    st = para_styles(m).getByName(name)
    for p in STYLE_PROPS:
        try:
            setattr(st, p, getattr(vc, p))
        except Exception:
            pass


def style_names(m, family="ParagraphStyles", used_only=False):
    fam = m.getStyleFamilies().getByName(family)
    out = []
    for n in fam.getElementNames():
        st = fam.getByName(n)
        if used_only and not st.isInUse():
            continue
        out.append((n, st.DisplayName))
    return out


# document-wide paragraph spacing presets (Design > Paragraph Spacing)
SPACING_PRESETS = {
    "none": (0, 0, 100),
    "compact": (0, 4, 100),
    "tight": (0, 6, 100),
    "open": (0, 10, 115),
    "relaxed": (0, 6, 150),
    "double": (0, 8, 200),
    "default": (0, 8, 108),
}


def doc_spacing(m, preset):
    before, after, line = SPACING_PRESETS[preset]
    st = para_styles(m).getByName("Standard")
    st.ParaTopMargin = pt(before)
    st.ParaBottomMargin = pt(after)
    ls = st.ParaLineSpacing
    ls.Mode, ls.Height = 0, line
    st.ParaLineSpacing = ls
    # body-like styles that set their own spacing follow the preset too
    for name in ("Text Body", "List Paragraph", "List"):
        if para_styles(m).hasByName(name):
            s = para_styles(m).getByName(name)
            try:
                s.ParaBottomMargin = pt(after)
                s.setPropertyToDefault("ParaLineSpacing")
            except Exception:
                pass


def current_doc_spacing(m):
    st = para_styles(m).getByName("Standard")
    vals = (round(to_pt(st.ParaTopMargin)), round(to_pt(st.ParaBottomMargin)),
            st.ParaLineSpacing.Height)
    for k, v in SPACING_PRESETS.items():
        if v == vals:
            return k
    return None


def set_default_font(m, name=None, size=None):
    st = para_styles(m).getByName("Standard")
    if name:
        st.CharFontName = name
        for p in ("CharFontNameAsian", "CharFontNameComplex"):
            try:
                setattr(st, p, name)
            except Exception:
                pass
    if size:
        st.CharHeight = float(size)


# ---------------------------------------------------------------- theme
from . import themedata as _TD

FONT_PAIRS = dict(_TD.FONT_SCHEMES)

# name: heading 1, heading 2, title, accent (the classic engine's use of a scheme)
COLOR_SETS = {k: (_TD.shade(v[4], 0.75), _TD.shade(v[4], 0.75), v[0], v[4])
              for k, v in _TD.COLOR_SCHEMES.items()}


def apply_fonts(m, pair):
    head, body = FONT_PAIRS[pair]
    ps = para_styles(m)
    ps.getByName("Standard").CharFontName = body
    for n in ("Heading", "Heading 1", "Heading 2", "Heading 3", "Heading 4", "Title",
              "Subtitle"):
        if ps.hasByName(n):
            ps.getByName(n).CharFontName = head


def _doc_setting(m, key, default=None):
    try:
        ud = m.getDocumentProperties().getUserDefinedProperties()
        return ud.getPropertyValue(key)
    except Exception:
        return default


def _set_doc_setting(m, key, value):
    try:
        ud = m.getDocumentProperties().getUserDefinedProperties()
        if ud.getPropertySetInfo().hasPropertyByName(key):
            ud.setPropertyValue(key, value)
        else:
            ud.addProperty(key, 128, value)       # REMOVEABLE
    except Exception:
        pass


def current_color_set(m):
    v = _doc_setting(m, "ThemeColors", "Blue")
    return v if v in COLOR_SETS else "Blue"


def current_style_set(m):
    v = _doc_setting(m, "StyleSet", "Default")
    return v if v in STYLE_SETS else "Default"


def apply_colors(m, name):
    h1, h2, title, accent = COLOR_SETS[name]
    _set_doc_setting(m, "ThemeColors", name)
    ps = para_styles(m)
    for n, c in (("Heading 1", h1), ("Heading 2", h2), ("Heading 3", h2),
                 ("Heading 4", h2), ("Title", title)):
        if ps.hasByName(n):
            ps.getByName(n).CharColor = c
    # style sets that use the accent colour follow the new colours
    if current_style_set(m) != "Default":
        apply_style_set(m, current_style_set(m), keep_colors=False)


# Style sets (Design > Document Formatting gallery). For each style:
# size (pt), bold, caps, colour ('title', 'h1', 'h2', 'accent', 'white', 'gray' or
# None = text), align ('left'/'center'), border ('top'/'bottom'/None, width in
# 1/100 mm, colour), shade (colour key or None), italic.
STYLE_SETS = {
    "Default": {
        "Title": dict(size=28, color="title"),
        "Heading 1": dict(size=16, color="h1"),
        "Heading 2": dict(size=13, color="h2")},
    "Basic (Elegant)": {
        "Title": dict(size=26, caps=True, align="center"),
        "Heading 1": dict(size=14, caps=True, border=("bottom", 18, None)),
        "Heading 2": dict(size=12, caps=True)},
    "Basic (Simple)": {
        "Title": dict(size=26, caps=True, color="accent"),
        "Heading 1": dict(size=14, caps=True, color="accent"),
        "Heading 2": dict(size=12, caps=True, color="h2")},
    "Basic (Stylish)": {
        "Title": dict(size=28, color="accent"),
        "Heading 1": dict(size=14, bold=True, color="h1"),
        "Heading 2": dict(size=12, bold=True)},
    "Casual": {
        "Title": dict(size=30, color="accent"),
        "Heading 1": dict(size=15, color="accent"),
        "Heading 2": dict(size=12, italic=True, color="h2")},
    "Centered": {
        "Title": dict(size=26, caps=True, align="center", color="h1"),
        "Heading 1": dict(size=14, caps=True, align="center", color="h1"),
        "Heading 2": dict(size=12, align="center", color="h2")},
    "Lines (Distinctive)": {
        "Title": dict(size=28, border=("bottom", 53, None)),
        "Heading 1": dict(size=14, bold=True, border=("bottom", 18, None)),
        "Heading 2": dict(size=12, bold=True)},
    "Lines (Simple)": {
        "Title": dict(size=26, color="h1"),
        "Heading 1": dict(size=14, border=("top", 18, "accent"), color="h1"),
        "Heading 2": dict(size=12, color="h2")},
    "Lines (Stylish)": {
        "Title": dict(size=28, color="accent", border=("bottom", 35, "accent")),
        "Heading 1": dict(size=14, color="h1", border=("bottom", 18, "accent")),
        "Heading 2": dict(size=12, color="h2")},
    "Minimalist": {
        "Title": dict(size=24, color="gray"),
        "Heading 1": dict(size=13, bold=True),
        "Heading 2": dict(size=11, bold=True, color="gray")},
    "Shaded": {
        "Title": dict(size=26, color="white", shade="accent"),
        "Heading 1": dict(size=14, caps=True, color="white", shade="h1"),
        "Heading 2": dict(size=12, caps=True, color="h1")},
}


def _set_color(m, key):
    h1, h2, title, accent = COLOR_SETS[current_color_set(m)]
    return {"title": title, "h1": h1, "h2": h2, "accent": accent, "white": 0xFFFFFF,
            "gray": 0x595959, None: -1}.get(key, -1)


def style_set_props(m, name, colors=None):
    """Resolved properties per style: {style: dict(...)} with colours as ints."""
    out = {}
    for st, d in STYLE_SETS[name].items():
        e = dict(d)
        e["color"] = _set_color(m, d.get("color")) if m is not None else d.get("color")
        if d.get("shade"):
            e["shade"] = _set_color(m, d["shade"]) if m is not None else d["shade"]
        if d.get("border"):
            side, w, c = d["border"]
            e["border"] = (side, w, _set_color(m, c) if (m is not None and c) else 0x000000)
        out[st] = e
    return out


def apply_style_set(m, name, keep_colors=False):
    um = m.getUndoManager()
    um.enterUndoContext("Style Set")
    try:
        _set_doc_setting(m, "StyleSet", name)
        ps = para_styles(m)
        empty = bridge.struct("com.sun.star.table.BorderLine2")
        for st, e in style_set_props(m, name).items():
            if not ps.hasByName(st):
                continue
            s = ps.getByName(st)
            s.CharHeight = float(e["size"])
            s.CharWeight = 150.0 if e.get("bold") else 100.0
            s.CharPosture = bridge.enum("com.sun.star.awt.FontSlant",
                                        "ITALIC" if e.get("italic") else "NONE")
            s.CharCaseMap = 1 if e.get("caps") else 0
            if not keep_colors:
                s.CharColor = e["color"] if e["color"] != -1 else -1
            s.ParaAdjust = 3 if e.get("align") == "center" else 0
            for side in ("Top", "Bottom"):
                setattr(s, "%sBorder" % side, empty)
            if e.get("border"):
                side, w, c = e["border"]
                bl = bridge.struct("com.sun.star.table.BorderLine2", Color=c, LineWidth=w,
                                   OuterLineWidth=w, LineStyle=0)
                setattr(s, "%sBorder" % side.capitalize(), bl)
                setattr(s, "%sBorderDistance" % side.capitalize(), 106 if e.get("shade") else 35)
            if e.get("shade"):
                s.ParaBackColor = e["shade"]
                s.ParaBackTransparent = False
                s.ParaLeftMargin = 0
            else:
                s.ParaBackColor = -1
                s.ParaBackTransparent = True
    finally:
        um.leaveUndoContext()


THEMES = dict(_TD.THEMES)


def apply_theme(m, name):
    colors, fonts = THEMES[name]
    apply_fonts(m, fonts)
    apply_colors(m, colors)


def style_previews(m, names):
    """Pango markup attributes showing how each style looks in this document."""
    from .actions import engine_style
    out = {}
    ps = para_styles(m)
    cs = char_styles(m)
    for n in names:
        lookup = engine_style(n)
        if ps.hasByName(lookup):
            s = ps.getByName(lookup)
        elif cs.hasByName(lookup):
            s = cs.getByName(lookup)
        else:
            continue
        try:
            size = min(18.0, max(8.0, float(s.CharHeight)))
            a = ["font_family='%s'" % (s.CharFontName or "Carlito").replace("'", ""),
                 "size='%gpt'" % size]
            if s.CharWeight > 100:
                a.append("weight='bold'")
            if getattr(s.CharPosture, "value", "NONE") != "NONE":
                a.append("style='italic'")
            if s.CharCaseMap == 4:
                a.append("variant='smallcaps'")
            if s.CharColor not in (-1, 0xFFFFFFFF) and s.CharColor >= 0:
                a.append("foreground='#%06x'" % (s.CharColor & 0xFFFFFF))
            try:
                if s.ParaBackColor not in (-1,) and not s.ParaBackTransparent:
                    a.append("background='#%06x'" % (s.ParaBackColor & 0xFFFFFF))
            except Exception:
                pass
            out[n] = (" ".join(a), s.CharCaseMap == 1)
        except Exception:
            pass
    return out


# ---------------------------------------------------------------- equations
def selected_object(m):
    sel = controller(m).getSelection()
    try:
        if sel.supportsService("com.sun.star.text.TextEmbeddedObject"):
            return sel
    except Exception:
        pass
    return None


def selected_formula_object(m):
    obj = selected_object(m)
    if obj is None:
        return None
    try:
        if obj.CLSID.upper() == MATH_CLSID.upper():
            return obj
    except Exception:
        pass
    return None


def formula_beside_cursor(m, direction):
    """The equation right after (direction 1) or before (-1) the collapsed
    cursor, or None."""
    try:
        vc = read_cursor(m)
        if not vc.isCollapsed():
            return None
        cur = vc.getText().createTextCursorByRange(vc.getStart())
        if direction > 0:
            if not cur.goRight(1, True):
                return None
        elif not cur.goLeft(1, True):
            return None
        en = cur.createContentEnumeration("com.sun.star.text.TextContent")
        while en.hasMoreElements():
            o = en.nextElement()
            try:
                if o.supportsService("com.sun.star.text.TextEmbeddedObject") and \
                        o.CLSID.upper() == MATH_CLSID.upper():
                    return o
            except Exception:
                continue
    except Exception:
        pass
    return None


def formula_of(obj):
    try:
        return obj.getEmbeddedObject().Formula
    except Exception:
        return None


def set_formula(obj, markup):
    emb = obj.getEmbeddedObject()
    emb.Formula = markup
    try:
        obj.getEmbeddedObject().setModified(True)
    except Exception:
        pass


MATH_TEXT_FONT = ["Caladea"]


def insert_formula(m, markup, display=False):
    um = m.getUndoManager()
    um.enterUndoContext("Insert Equation")
    try:
        return _insert_formula(m, markup, display)
    finally:
        um.leaveUndoContext()


def _insert_formula(m, markup, display):
    vc = view_cursor(m)
    text = vc.getText()
    obj = m.createInstance("com.sun.star.text.TextEmbeddedObject")
    obj.CLSID = MATH_CLSID
    obj.AnchorType = bridge.enum("com.sun.star.text.TextContentAnchorType", "AS_CHARACTER")
    if display:
        cur = text.createTextCursorByRange(vc)
        cur.gotoStartOfParagraph(True)
        empty_before = cur.getString().strip() == ""
        cur = text.createTextCursorByRange(vc)
        cur.gotoEndOfParagraph(True)
        empty_after = cur.getString().strip() == ""
        if not (empty_before and empty_after):
            text.insertControlCharacter(vc, 0, False)
        vc.ParaAdjust = 3
    text.insertTextContent(vc, obj, False)
    set_formula(obj, markup)
    try:
        emb = obj.getEmbeddedObject()
        emb.BaseFontHeight = int(round(view_cursor(m).CharHeight or 11))
        for p in ("FontNameVariables", "FontNameFunctions", "FontNameNumbers",
                  "FontNameText"):
            setattr(emb, p, MATH_TEXT_FONT[0])
        emb.FontVariablesIsItalic = True
    except Exception:
        pass
    return obj


def select_object(m, obj):
    controller(m).select(obj)


def formulas(m):
    out = []
    objs = m.getEmbeddedObjects()
    for n in objs.getElementNames():
        o = objs.getByName(n)
        try:
            if o.CLSID.upper() == MATH_CLSID.upper():
                out.append(o)
        except Exception:
            pass
    return out


# ------------------------------------------------------------- language
def _lingu():
    return bridge.create("com.sun.star.linguistic2.LinguServiceManager")


_DICTS = {}


def _dict(loc):
    """A spelling dictionary for the locale (same word lists the engine uses),
    with the user's own words added."""
    tag = "%s_%s" % (loc.Language, loc.Country) if loc.Country else loc.Language
    d = _DICTS.get(tag)
    if d is None:
        import enchant
        import os
        pwl = user_words_path()
        for t in (tag, loc.Language, "en_US"):
            try:
                d = enchant.DictWithPWL(t, pwl)
                break
            except Exception:
                continue
        _DICTS[tag] = d
    return d


def spell_ok(word, loc):
    try:
        d = _dict(loc)
        return d is None or d.check(word)
    except Exception:
        return True


def suggestions(word, loc, limit=8):
    try:
        d = _dict(loc)
        return d.suggest(word)[:limit] if d else []
    except Exception:
        return []


USER_WORDS = "~/.config/folio-writer/dictionary.txt"
_USER_DICT = []


def user_words_path():
    import os
    path = os.path.expanduser(USER_WORDS)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        open(path, "a").close()
    return path


def user_words():
    with open(user_words_path(), encoding="utf-8", errors="replace") as f:
        return [w.strip() for w in f if w.strip()]


def save_user_words(words):
    with open(user_words_path(), "w", encoding="utf-8") as f:
        f.write("\n".join(sorted(set(words), key=str.lower)) + ("\n" if words else ""))


def user_dictionary():
    """The engine's word list for words the user added. The engine can't write
    its own dictionary files here, so the list lives in memory and is filled
    from the user's word file (shared with the app's own spell checker)."""
    import uno
    if _USER_DICT:
        return _USER_DICT[0]
    dl = bridge.create("com.sun.star.linguistic2.DictionaryList")
    d = dl.getDictionaryByName("FolioWords")
    if d is None:
        d = dl.createDictionary("FolioWords", locale("", ""),
                                uno.Enum("com.sun.star.linguistic2.DictionaryType",
                                         "POSITIVE"), "")
        for w in user_words():
            try:
                d.add(w, False, "")
            except Exception:
                pass
        dl.addDictionary(d)
    d.setActive(True)
    _USER_DICT.append(d)
    return d


def add_to_dictionary(word):
    word = word.strip()
    if not word:
        return
    words = user_words()
    if word not in words:
        words.append(word)
        save_user_words(words)
    for d in _DICTS.values():
        if d is not None:
            try:
                d.add_to_session(word)
            except Exception:
                pass
    try:
        user_dictionary().add(word, False, "")
    except Exception as e:
        print("dictionary:", e)


def remove_from_dictionary(word):
    save_user_words([w for w in user_words() if w != word])
    try:
        user_dictionary().remove(word)
    except Exception:
        pass
    _DICTS.clear()          # the app's checker reloads the word file


def ignore_all(word):
    try:
        dl = bridge.create("com.sun.star.linguistic2.DictionaryList")
        for name in ("List of Ignored Words", "IgnoreAllList"):
            d = dl.getDictionaryByName(name)
            if d is not None:
                d.add(word, False, "")
                break
    except Exception as e:
        print("ignore all:", e)


def synonyms(word, loc):
    th = _lingu().getThesaurus()
    out = []
    try:
        for meaning in th.queryMeanings(word, loc, ()):
            clean = lambda t: t.replace(" (generic term)", "").replace(" (similar term)", "") \
                .replace(" (related term)", "").replace(" (antonym)", " (opposite)")
            out.append((clean(meaning.getMeaning()),
                        [clean(x) for x in meaning.querySynonyms()]))
    except Exception:
        pass
    return out


WORD_RE = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*", re.UNICODE)


def next_misspelling(m, start_after_cursor=True, ignored=()):
    """Find and select the next misspelled word from the cursor on.
    Returns the word or None."""
    vc = view_cursor(m)
    body = m.getText()
    loc = doc_locale(m)
    try:
        cur = body.createTextCursorByRange(vc.getEnd() if start_after_cursor else vc.getStart())
    except Exception:
        # cursor in a table, header or frame: check the body text from the top
        cur = body.createTextCursor()
        cur.gotoStart(False)
    first = True
    for _wrap in range(2):
        while True:
            if not first and not cur.gotoNextWord(False):
                break
            first = False
            w = body.createTextCursorByRange(cur)
            w.gotoEndOfWord(True)
            word = w.getString().strip()
            if word and WORD_RE.fullmatch(word) and word not in ignored and \
                    not word.isupper() and len(word) > 1:
                try:
                    lc = w.CharLocale if w.CharLocale.Language else loc
                    if lc.Language in ("zxx",):
                        continue
                    if not spell_ok(word, lc):
                        controller(m).select(w)
                        return word
                except Exception:
                    pass
        cur = body.createTextCursor()
        cur.gotoStart(False)
        first = True
        if _wrap:
            break
    return None


def replace_selection_text(m, text):
    vc = view_cursor(m)
    vc.setString(text)
    vc.collapseToEnd()


# -------------------------------------------------------------- tables
def table_at_cursor(m):
    vc = read_cursor(m)
    try:
        return vc.TextTable
    except Exception:
        return None


def table_style(m, header_fill=0x4472C4, band_fill=0xD9E2F3, border=0x8EAADB,
                header_font=0xFFFFFF):
    t = table_at_cursor(m)
    if t is None:
        return
    rows = t.getRows().getCount()
    cols = t.getColumns().getCount()
    line = _line(0.5, border)
    for r in range(rows):
        for c in range(cols):
            name = t.getCellByPosition(c, r)
            if r == 0:
                name.BackColor = header_fill
                cur = name.createTextCursor()
                cur.gotoEnd(True)
                cur.CharColor = header_font
                cur.CharWeight = 150.0
            elif r % 2 == 0:
                name.BackColor = band_fill
            else:
                name.BackColor = -1
            for side in ("LeftBorder", "RightBorder", "TopBorder", "BottomBorder"):
                setattr(name, side, line)


def sort_paragraphs(m, descending=False, case=False):
    """Sort the selected paragraphs by their text, keeping formatting."""
    vc = view_cursor(m)
    if vc.isCollapsed():
        return False
    try:
        desc = vc.createSortDescriptor()
    except Exception:
        return False
    props = []
    for p in desc:
        if p.Name == "IsSortInTable":
            p.Value = False
        elif p.Name == "SortFields":
            fields = list(p.Value)
            if fields:
                f = fields[0]
                f.IsAscending = not descending
                f.IsCaseSensitive = case
                fields[0] = f
                p.Value = tuple(fields)
        props.append(p)
    vc.sort(tuple(props))
    return True


# ---------------------------------------------------------------- pictures
def insert_picture(m, path):
    """Insert an image file in line with text at the cursor, scaled to fit
    the text column (as the reference word processor does)."""
    import uno
    from .engine import file_url
    gp = bridge.create("com.sun.star.graphic.GraphicProvider")
    graphic = gp.queryGraphic((bridge.prop("URL", file_url(path)),))
    if graphic is None:
        raise ValueError("unreadable picture")
    size = graphic.Size100thMM
    if not size.Width or not size.Height:
        px = graphic.SizePixel
        size = bridge.struct("com.sun.star.awt.Size", Width=int(px.Width * 2540 / 96),
                             Height=int(px.Height * 2540 / 96))
    ps = page_setup(m)
    maxw = ps["width"] - ps["left"] - ps["right"]
    w, h = size.Width, size.Height
    if w > maxw:
        h = int(h * maxw / w)
        w = maxw
    um = m.getUndoManager()
    um.enterUndoContext("Insert Picture")
    try:
        obj = m.createInstance("com.sun.star.text.TextGraphicObject")
        obj.Graphic = graphic
        obj.AnchorType = bridge.enum("com.sun.star.text.TextContentAnchorType", "AS_CHARACTER")
        vc = view_cursor(m)
        vc.getText().insertTextContent(vc, obj, False)
        obj.Size = bridge.struct("com.sun.star.awt.Size", Width=w, Height=h)
        try:
            obj.Title = os.path.basename(path)
        except Exception:
            pass
        controller(m).select(obj)
        return obj
    finally:
        um.leaveUndoContext()


def multilevel_list(m):
    """1. / a. / i. numbering that changes level with Tab and Shift+Tab."""
    from . import lists
    lists.apply_multilevel(m, lists.MULTI[0][1])


# ------------------------------------------------------------- sections
def _copy_props(src, dst, skip=("Name", "DisplayName", "FollowStyle", "IsPhysical",
                                "IsAutoUpdate", "Hidden", "ParentStyle")):
    for p in src.getPropertySetInfo().getProperties():
        if p.Name in skip or p.Attributes & 16:      # READONLY
            continue
        try:
            dst.setPropertyValue(p.Name, src.getPropertyValue(p.Name))
        except Exception:
            pass


def _text_columns(m, n, spacing=1250):
    tc = m.createInstance("com.sun.star.text.TextColumns")
    tc.setColumnCount(max(1, int(n)))
    try:
        tc.AutomaticDistance = spacing
    except Exception:
        pass
    return tc


def insert_section_break(m, kind="next-page"):
    """Word's section breaks. 'next-page' (and 'even'/'odd') start a new page
    with its own copy of the page settings, so margins, orientation and
    headers can differ per section. 'continuous' starts a new section on the
    same page, so columns can change mid-page."""
    um = m.getUndoManager()
    um.enterUndoContext("Section Break")
    try:
        vc = view_cursor(m)
        text = vc.getText()
        if kind == "continuous":
            cur = text.createTextCursorByRange(vc.getStart())
            text.insertControlCharacter(cur, 0, False)
            cur = text.createTextCursorByRange(vc.getStart())
            cur.gotoStartOfParagraph(False)
            cur.gotoEnd(True)
            sec = m.createInstance("com.sun.star.text.TextSection")
            text.insertTextContent(cur, sec, True)
            return sec
        ps = page_style(m)
        fam = m.getStyleFamilies().getByName("PageStyles")
        i = 1
        while fam.hasByName("Section %d" % i):
            i += 1
        name = "Section %d" % i
        new = m.createInstance("com.sun.star.style.PageStyle")
        fam.insertByName(name, new)
        _copy_props(ps, new)
        if kind in ("even", "odd"):
            try:
                new.PageStyleLayout = bridge.enum("com.sun.star.style.PageStyleLayout",
                                                  "LEFT" if kind == "even" else "RIGHT")
            except Exception:
                pass
        text.insertControlCharacter(vc, 0, False)
        vc.PageDescName = name
        return name
    finally:
        um.leaveUndoContext()


def set_columns(m, n):
    """Columns for the selected text (in its own section, as Word does), for
    the section the cursor is in, or for the page."""
    vc = view_cursor(m)
    text = vc.getText()
    if not vc.isCollapsed():
        sec = m.createInstance("com.sun.star.text.TextSection")
        sec.TextColumns = _text_columns(m, n)
        text.insertTextContent(vc, sec, True)
        return
    sec = None
    try:
        sec = vc.TextSection
    except Exception:
        pass
    if sec is not None:
        sec.TextColumns = _text_columns(m, n)
        return
    set_page(m, columns=int(n))


# ------------------------------------------------------------- text from file
def insert_text_from_file(m, path):
    vc = view_cursor(m)
    cur = vc.getText().createTextCursorByRange(vc.getStart())
    url = uno_url(path)
    cur.insertDocumentFromURL(url, ())


def uno_url(path):
    import uno
    import os
    return uno.systemPathToFileUrl(os.path.abspath(path))


# ------------------------------------------------------------- figures & index
def insert_table_of_figures(m, label="Figure"):
    vc = view_cursor(m)
    idx = m.createInstance("com.sun.star.text.IllustrationsIndex")
    idx.LabelCategory = label
    idx.CreateFromLabels = True
    idx.Title = ""
    try:
        idx.LabelDisplayType = 0     # label, number and text
    except Exception:
        pass
    vc.getText().insertTextContent(vc, idx, False)
    idx.update()
    return idx


def mark_index_entry(m, entry=None, main=False):
    vc = view_cursor(m)
    mark = m.createInstance("com.sun.star.text.DocumentIndexMark")
    if entry and entry != vc.getString():
        mark.AlternativeText = entry
    try:
        mark.IsMainEntry = bool(main)
    except Exception:
        pass
    vc.getText().insertTextContent(vc, mark, not vc.isCollapsed())
    return mark


def insert_index(m, columns=2):
    vc = view_cursor(m)
    idx = m.createInstance("com.sun.star.text.DocumentIndex")
    idx.Title = ""
    vc.getText().insertTextContent(vc, idx, False)
    try:
        idx.UseAlphabeticalSeparators = True
        idx.TextColumns = _text_columns(m, columns, 500)
        idx.update()
    except Exception:
        pass
    return idx


# ------------------------------------------------------------- language
LANGUAGES = [
    ("English (United States)", "en", "US"), ("English (United Kingdom)", "en", "GB"),
    ("English (Australia)", "en", "AU"), ("English (Canada)", "en", "CA"),
    ("English (India)", "en", "IN"), ("English (Ireland)", "en", "IE"),
    ("English (New Zealand)", "en", "NZ"), ("English (South Africa)", "en", "ZA"),
    ("Danish", "da", "DK"), ("Dutch (Netherlands)", "nl", "NL"), ("Dutch (Belgium)", "nl", "BE"),
    ("Finnish", "fi", "FI"), ("French (France)", "fr", "FR"), ("French (Canada)", "fr", "CA"),
    ("German (Germany)", "de", "DE"), ("German (Austria)", "de", "AT"),
    ("German (Switzerland)", "de", "CH"), ("Greek", "el", "GR"), ("Hungarian", "hu", "HU"),
    ("Italian (Italy)", "it", "IT"), ("Norwegian (Bokmål)", "nb", "NO"), ("Polish", "pl", "PL"),
    ("Portuguese (Brazil)", "pt", "BR"), ("Portuguese (Portugal)", "pt", "PT"),
    ("Romanian", "ro", "RO"), ("Russian", "ru", "RU"), ("Spanish (Spain)", "es", "ES"),
    ("Spanish (Mexico)", "es", "MX"), ("Swedish (Sweden)", "sv", "SE"), ("Turkish", "tr", "TR"),
    ("Ukrainian", "uk", "UA"),
]


def language_name(code):
    """'en-US' -> 'English (United States)'."""
    code = (code or "").replace("_", "-")
    for name, l, c in LANGUAGES:
        if code in ("%s-%s" % (l, c), l):
            return name
    return code


def has_dictionary(lang, country):
    try:
        import enchant
        return any(enchant.dict_exists(t) for t in ("%s_%s" % (lang, country), lang))
    except Exception:
        return False


def current_language(m):
    vc = read_cursor(m)
    loc = vc.CharLocale
    return loc.Language, loc.Country


def set_language(m, lang, country, no_proof=False, default=False, whole=False):
    """Mark the selection (or the whole document) as this language, or as
    'do not check'."""
    loc = bridge.struct("com.sun.star.lang.Locale",
                        Language="zxx" if no_proof else lang,
                        Country="" if no_proof else country)
    if whole:
        cur = m.getText().createTextCursor()
        cur.gotoStart(False)
        cur.gotoEnd(True)
        cur.CharLocale = loc
    else:
        view_cursor(m).CharLocale = loc
    if default:
        st = m.getStyleFamilies().getByName("ParagraphStyles").getByName("Standard")
        st.CharLocale = bridge.struct("com.sun.star.lang.Locale", Language=lang, Country=country)
        try:
            m.CharLocale = st.CharLocale
        except Exception:
            pass


# ------------------------------------------------------------- fields
def _fields_in_order(m):
    out = []
    en = m.getTextFields().createEnumeration()
    while en.hasMoreElements():
        f = en.nextElement()
        try:
            a = f.getAnchor()
            if a.getText() is not None:
                out.append((f, a))
        except Exception:
            pass
    return out


def _cmp(text, a, b):
    """1 if a is before b, 0 same, -1 after (text.compareRegionStarts)."""
    try:
        return text.compareRegionStarts(a, b)
    except Exception:
        return None


def goto_field(m, forward=True):
    """F11 / Shift+F11: select the next (previous) field."""
    vc = view_cursor(m)
    here = vc.getEnd() if forward else vc.getStart()
    best = None
    for f, a in _fields_in_order(m):
        c = _cmp(a.getText(), here, a)
        if c is None:
            continue
        if forward and c == 1 or (not forward and c == -1):
            if best is None:
                best = a
            else:
                c2 = _cmp(a.getText(), a, best)
                if c2 is not None and ((forward and c2 == 1) or (not forward and c2 == -1)):
                    best = a
    if best is not None:
        vc.gotoRange(best.getStart(), False)
        vc.gotoRange(best.getEnd(), True)
        return True
    return False


def unlink_fields(m):
    """Ctrl+Shift+F9: replace the selected fields with their current text."""
    vc = view_cursor(m)
    text = vc.getText()
    whole = vc.isCollapsed()
    n = 0
    for f, a in _fields_in_order(m):
        if a.getText() != text:
            continue
        if not whole:
            s = _cmp(text, vc.getStart(), a.getStart())
            e = _cmp(text, a.getEnd(), vc.getEnd())
            if s is None or e is None or s < 0 or e < 0:
                continue
        else:
            # just the field at the cursor
            if _cmp(text, a.getStart(), vc.getStart()) == -1 or \
                    _cmp(text, vc.getStart(), a.getEnd()) == -1:
                continue
        try:
            shown = f.getPresentation(False)
        except Exception:
            shown = a.getString()
        cur = text.createTextCursorByRange(a)
        text.removeTextContent(f)
        text.insertString(cur, shown, False)
        n += 1
    return n


def lock_fields(m, lock=True):
    """Ctrl+F11 / Ctrl+Shift+F11: fixed fields stop updating."""
    vc = view_cursor(m)
    text = vc.getText()
    for f, a in _fields_in_order(m):
        if a.getText() != text:
            continue
        if _cmp(text, vc.getStart(), a.getEnd()) == -1 or _cmp(text, a.getStart(), vc.getEnd()) == -1:
            continue
        for prop in ("IsFixed", "IsFixedLanguage"):
            try:
                if prop == "IsFixed":
                    f.IsFixed = lock
                break
            except Exception:
                continue


def toggle_field_codes(m):
    """Alt+F9: show field codes instead of their results, or back."""
    vs = controller(m).getViewSettings()
    vs.ShowFieldCommands = not vs.ShowFieldCommands


# ------------------------------------------------------------- tracked changes
REDLINE_NAMES = {"Insert": "Inserted", "Delete": "Deleted", "Format": "Formatted",
                 "Attributes": "Formatted", "ParagraphFormat": "Formatted",
                 "TextTable": "Table", "TableRowInsert": "Inserted row",
                 "TableRowDelete": "Deleted row", "TableCellInsert": "Inserted cell",
                 "TableCellDelete": "Deleted cell"}


def redlines(m):
    out = []
    en = m.getRedlines().createEnumeration()
    while en.hasMoreElements():
        r = en.nextElement()
        try:
            start, end = r.RedlineStart, r.RedlineEnd
            text = ""
            try:
                c = start.getText().createTextCursorByRange(start)
                c.gotoRange(end, True)
                text = c.getString()
            except Exception:
                pass
            dt = r.RedlineDateTime
            out.append({"type": REDLINE_NAMES.get(r.RedlineType, r.RedlineType),
                        "author": r.RedlineAuthor, "text": text,
                        "date": "%d/%d/%d %d:%02d" % (dt.Month, dt.Day, dt.Year, dt.Hours,
                                                     dt.Minutes),
                        "start": start, "end": end})
        except Exception:
            continue
    return out


def select_range(m, start, end):
    vc = view_cursor(m)
    vc.gotoRange(start, False)
    vc.gotoRange(end, True)


# ------------------------------------------------------------- header/footer options
def hf_options(m):
    ps = page_style(m)
    out = {"first": False, "odd_even": False, "header_top": 1270, "footer_bottom": 1270}
    try:
        out["first"] = not ps.FirstIsShared
    except Exception:
        pass
    try:
        out["odd_even"] = not ps.HeaderIsShared
    except Exception:
        pass
    if ps.HeaderIsOn:
        out["header_top"] = ps.TopMargin
    if ps.FooterIsOn:
        out["footer_bottom"] = ps.BottomMargin
    return out


def set_hf_option(m, key, value):
    ps = page_style(m)
    if key == "first":
        ps.FirstIsShared = not value
    elif key == "odd_even":
        ps.HeaderIsShared = not value
        ps.FooterIsShared = not value
    elif key in ("header_top", "footer_bottom"):
        which = "Header" if key == "header_top" else "Footer"
        margin = "TopMargin" if which == "Header" else "BottomMargin"
        v = max(0, int(value))
        if getattr(ps, which + "IsOn"):
            # keep the body text where it is: the header area absorbs the change
            body = getattr(ps, margin) + getattr(ps, which + "Height")
            setattr(ps, margin, v)
            setattr(ps, which + "Height", max(body - v, 300))
        else:
            setattr(ps, margin, v)


# ------------------------------------------------------------- outline sections
def section_range(m, heading_par):
    """A text cursor over a heading and everything under it (up to the next
    heading of the same or a higher level)."""
    body = m.getText()
    level = heading_par.OutlineLevel or 9
    cur = body.createTextCursorByRange(heading_par.getStart())
    end = None
    seen = False
    en = body.createEnumeration()
    while en.hasMoreElements():
        p = en.nextElement()
        if not seen:
            try:
                if body.compareRegionStarts(p.getStart(), heading_par.getStart()) == 0:
                    seen = True
            except Exception:
                pass
            continue
        try:
            if p.supportsService("com.sun.star.text.Paragraph") and p.OutlineLevel and \
                    p.OutlineLevel <= level and p.getString().strip():
                end = p.getStart()
                break
        except Exception:
            continue
    if end is not None:
        cur.gotoRange(end, True)
    else:
        cur.gotoEnd(True)
    return cur, end is None


def move_section(m, src_par, dst_par, after=False):
    """Move a heading with its content before (or after) another heading's
    section, keeping all formatting."""
    body = m.getText()
    ctl = controller(m)
    um = m.getUndoManager()
    um.enterUndoContext("Move Section")
    try:
        src, src_is_last = section_range(m, src_par)
        if after:
            dst_rng, dst_is_last = section_range(m, dst_par)
            target = body.createTextCursorByRange(dst_rng.getEnd())
        else:
            target = body.createTextCursorByRange(dst_par.getStart())
            dst_is_last = False
        # the moved block must end with a paragraph break
        if src_is_last:
            tail = body.createTextCursorByRange(src.getEnd())
            body.insertControlCharacter(tail, 0, False)
            src, _x = section_range(m, src_par)
        if after and dst_is_last:
            body.insertControlCharacter(target, 0, False)
        vc = view_cursor(m)
        vc.gotoRange(src.getStart(), False)
        vc.gotoRange(src.getEnd(), True)
        t = ctl.getTransferable()
        vc.gotoRange(target.getStart(), False)
        ctl.insertTransferable(t)
        src.setString("")
        if src_is_last:
            # drop the empty paragraph the moved section left at the end
            try:
                c = body.createTextCursorByRange(src.getStart())
                if not c.getString() and c.goLeft(1, True):
                    c.setString("")
            except Exception:
                pass
    finally:
        um.leaveUndoContext()


def set_heading_level(m, par, delta):
    lvl = par.OutlineLevel or 0
    new = max(1, min(9, lvl + delta))
    if lvl == 0:
        return
    par.ParaStyleName = "Heading %d" % new


def delete_section(m, par):
    rng, _last = section_range(m, par)
    rng.setString("")
