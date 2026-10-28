"""Built-in cover pages and header / footer designs, as in the original's
galleries, plus saving the selection to those galleries."""
import datetime

from . import bridge, docapi

MARK = "_CoverPage"
SHAPE = "CoverPageShape"

# name: accent, band (None / top / bottom / left / full), title colour on band,
# title size, uppercase, align
COVERS = [
    ("Simple", dict(accent=0x2F5496, band=None, size=40, caps=False, align="left")),
    ("Banded", dict(accent=0xC00000, band="bottom", size=36, caps=True, align="center")),
    ("Grid", dict(accent=0x375623, band="left", size=36, caps=False, align="left")),
    ("Facet", dict(accent=0x70AD47, band="left", size=40, caps=True, align="right")),
    ("Ion (Dark)", dict(accent=0x1F3864, band="full", size=44, caps=True, align="left")),
    ("Ion (Light)", dict(accent=0x4472C4, band=None, size=44, caps=True, align="left")),
    ("Motion", dict(accent=0xED7D31, band="top", size=36, caps=False, align="left")),
    ("Retrospect", dict(accent=0x5B9BD5, band="bottom", size=40, caps=True, align="center")),
    ("Semaphore", dict(accent=0xA5A5A5, band="top", size=40, caps=True, align="left")),
    ("Sideline", dict(accent=0x4472C4, band=None, size=40, caps=False, align="left",
                      rule=True)),
    ("Slice (Dark)", dict(accent=0x262626, band="full", size=44, caps=True, align="left")),
    ("Whisp", dict(accent=0x7F7F7F, band=None, size=36, caps=False, align="left",
                   rule=True)),
]
ALIGN = {"left": 0, "right": 1, "center": 3}


def _props(win, m):
    p = docapi.doc_properties(m)
    return (p["title"] or "Document title", p["subject"] or "Document subtitle",
            p["author"] or win.app.user_name(),
            datetime.date.today().strftime("%B %-d, %Y"))


def remove_cover(m):
    bms = m.getBookmarks()
    found = False
    if bms.hasByName(MARK):
        bm = bms.getByName(MARK)
        a = bm.getAnchor()
        text = a.getText()
        c = text.createTextCursorByRange(a.getStart())
        c.gotoRange(a.getEnd(), True)
        # with the paragraph that ends the cover page
        c.gotoEndOfParagraph(True)
        nxt = text.createTextCursorByRange(c.getEnd())
        if nxt.gotoNextParagraph(False):
            c.gotoRange(nxt.getStart(), True)
        text.removeTextContent(bm)
        c.setString("")
        try:
            c.BreakType = bridge.enum("com.sun.star.style.BreakType", "NONE")
        except Exception:
            pass
        found = True
    dp = m.getDrawPage()
    for i in reversed(range(dp.getCount())):
        try:
            o = dp.getByIndex(i)
            if (o.Name or "").startswith(SHAPE):
                dp.remove(o)
                found = True
        except Exception:
            pass
    # the first paragraph of the document took the page break: no more
    try:
        first = m.getText().createEnumeration().nextElement()
        if getattr(first.BreakType, "value", "") == "PAGE_BEFORE":
            first.BreakType = bridge.enum("com.sun.star.style.BreakType", "NONE")
    except Exception:
        pass
    return found


def _band(m, spec, ps):
    band = spec.get("band")
    if not band:
        return None
    W, H = ps.Width, ps.Height
    x, y, w, h = {"top": (0, 0, W, int(H * 0.38)), "bottom": (0, int(H * 0.72), W, int(H * 0.28)),
                  "left": (0, 0, int(W * 0.08), H), "full": (0, 0, W, H)}[band]
    s = m.createInstance("com.sun.star.drawing.RectangleShape")
    s.AnchorType = bridge.enum("com.sun.star.text.TextContentAnchorType", "AT_PAGE")
    m.getDrawPage().add(s)
    s.AnchorPageNo = 1
    s.Size = bridge.struct("com.sun.star.awt.Size", Width=w, Height=h)
    s.HoriOrient, s.HoriOrientRelation, s.HoriOrientPosition = 0, 7, x
    s.VertOrient, s.VertOrientRelation, s.VertOrientPosition = 0, 7, y
    s.FillColor = spec["accent"]
    s.LineStyle = bridge.enum("com.sun.star.drawing.LineStyle", "NONE")
    s.TextWrap = bridge.enum("com.sun.star.text.WrapTextMode", "THROUGH")
    s.Opaque = False
    s.Name = SHAPE + "1"
    return band


def _native(win):
    return getattr(getattr(win, "engine", None), "native", False)


def remove_current(win):
    """Remove Current Cover Page."""
    if _native(win):
        from .native import covers as nc
        return nc.remove_cover(win)
    m = win.engine.model
    return remove_cover(m) if m is not None else False


def insert_cover(win, name):
    if _native(win):
        from .native import covers as nc
        return nc.insert_cover(win, name)
    m = win.engine.model
    if m is None:
        return
    spec = dict(COVERS)[name]
    um = m.getUndoManager()
    um.enterUndoContext("Cover Page")
    try:
        remove_cover(m)
        title, sub, author, date = _props(win, m)
        body = m.getText()
        cur = body.createTextCursor()
        cur.gotoStart(False)
        ps = docapi.page_style(m)
        band = _band(m, spec, ps)
        on_dark = band in ("full",)
        tcol = 0xFFFFFF if on_dark else spec["accent"]
        align = ALIGN[spec["align"]]

        def para(text, style_name, **kw):
            cur.ParaStyleName = style_name
            cur.ParaAdjust = align
            for k, v in kw.items():
                setattr(cur, k, v)
            body.insertString(cur, text, False)
            body.insertControlCharacter(cur, 0, False)
            for k in list(kw) + ["ParaAdjust"]:
                try:
                    cur.setPropertyToDefault(k)
                except Exception:
                    pass
        top_gap = {"top": 2, "bottom": 7, "left": 7, "full": 8}.get(band, 6)
        for _ in range(top_gap):
            para("", "Standard")
        rule = bridge.struct("com.sun.star.table.BorderLine2", Color=spec["accent"],
                             LineWidth=53, OuterLineWidth=53) if spec.get("rule") else None
        kw = dict(CharColor=tcol, CharHeight=float(spec["size"]))
        if spec["caps"]:
            kw["CharCaseMap"] = 1
        if rule is not None:
            kw["BottomBorder"] = rule
            kw["BottomBorderDistance"] = 100
        if band == "top":
            kw["CharColor"] = 0xFFFFFF
        para(title, "Title", **kw)
        para(sub, "Subtitle", CharColor=0xFFFFFF if band in ("top", "full") else 0x595959)
        for _ in range({"top": 16, "bottom": 4, "full": 10}.get(band, 14)):
            para("", "Standard")
        on_band_bottom = band in ("bottom", "full")
        para(author, "Standard", CharColor=0xFFFFFF if on_band_bottom else spec["accent"],
             CharWeight=150.0)
        para(date, "Standard", CharColor=0xFFFFFF if on_band_bottom else 0x595959)
        cur.ParaStyleName = "Standard"
        cur.BreakType = bridge.enum("com.sun.star.style.BreakType", "PAGE_BEFORE")
        mark = body.createTextCursor()
        mark.gotoStart(False)
        prev = body.createTextCursorByRange(cur.getStart())
        prev.gotoPreviousParagraph(False)
        prev.gotoEndOfParagraph(False)
        mark.gotoRange(prev.getStart(), True)
        bm = m.createInstance("com.sun.star.text.Bookmark")
        bm.setName(MARK)
        body.insertTextContent(mark, bm, True)
    finally:
        um.leaveUndoContext()


# ---------------------------------------------------------------- headers / footers
HEADERS = ["Blank", "Blank (Three Columns)", "Austin", "Banded", "Facet", "Grid", "Integral",
           "Ion", "Retrospect", "Sideline", "Whisp"]
FOOTERS = ["Blank", "Blank (Three Columns)", "Austin", "Banded", "Facet", "Integral", "Ion",
           "Retrospect", "Semaphore", "Sideline"]


def _field(m, kind):
    if kind == "page":
        f = m.createInstance("com.sun.star.text.textfield.PageNumber")
        f.NumberingType = 4
        f.SubType = bridge.enum("com.sun.star.text.PageNumberType", "CURRENT")
    elif kind == "pages":
        f = m.createInstance("com.sun.star.text.textfield.PageCount")
        f.NumberingType = 4
    elif kind == "title":
        f = m.createInstance("com.sun.star.text.textfield.docinfo.Title")
    elif kind == "author":
        f = m.createInstance("com.sun.star.text.textfield.docinfo.CreateAuthor")
    elif kind == "date":
        f = m.createInstance("com.sun.star.text.textfield.DateTime")
        f.IsDate = True
        f.IsFixed = False
    else:
        return None
    return f


def hf_design(win, which, name):
    """Put a built-in design in the header or footer of the current
    section."""
    if _native(win):
        from .native import covers as nc
        return nc.hf_design(win, which, name)
    m = win.engine.model
    if m is None:
        return
    ps = docapi.page_style(m)
    key = "Header" if which == "header" else "Footer"
    um = m.getUndoManager()
    um.enterUndoContext("Header" if which == "header" else "Footer")
    try:
        docapi.enable_header_footer(m, which, ps)
        text = getattr(ps, key + "Text")
        text.setString("")
        cur = text.createTextCursor()
        accent = 0x4472C4
        tw = ps.Width - ps.LeftMargin - ps.RightMargin

        def tabs(*stops):
            out = []
            for pos, al in stops:
                ts = bridge.struct("com.sun.star.style.TabStop")
                ts.Position = int(pos)
                ts.Alignment = bridge.enum("com.sun.star.style.TabAlign", al)
                out.append(ts)
            cur.ParaTabStops = tuple(out)

        def put(*parts):
            for p in parts:
                if isinstance(p, tuple):
                    f = _field(m, p[0])
                    if f is not None:
                        text.insertTextContent(cur, f, False)
                else:
                    text.insertString(cur, p, False)
        line = bridge.struct("com.sun.star.table.BorderLine2", Color=accent, LineWidth=26,
                             OuterLineWidth=26)
        if name == "Blank":
            put("[Type here]")
        elif name == "Blank (Three Columns)":
            tabs((tw / 2, "CENTER"), (tw, "RIGHT"))
            put("[Type here]\t[Type here]\t[Type here]")
        elif name in ("Austin", "Ion", "Semaphore"):
            cur.ParaAdjust = 1 if name != "Semaphore" else 3
            cur.CharColor = accent
            put(("title",) if which == "header" else ("page",))
        elif name == "Banded":
            cur.ParaAdjust = 3
            cur.ParaBackColor = accent
            cur.CharColor = 0xFFFFFF
            put(("title",) if which == "header" else ("page",))
        elif name == "Facet":
            cur.CharColor = accent
            if which == "header":
                put(("title",))
            else:
                tabs((tw, "RIGHT"))
                put(("title",), "\t", ("page",))
        elif name == "Grid":
            tabs((tw, "RIGHT"))
            put(("title",), "\t", ("date",))
        elif name == "Integral":
            cur.CharCaseMap = 1
            cur.CharColor = accent
            if which == "header":
                cur.ParaAdjust = 3
                put(("title",))
            else:
                tabs((tw, "RIGHT"))
                put(("author",), "\t", ("page",))
            setattr(cur, "BottomBorder" if which == "header" else "TopBorder", line)
        elif name == "Retrospect":
            tabs((tw, "RIGHT"))
            cur.CharColor = 0x595959
            put(("title",), "\t", ("date",)) if which == "header" else \
                put(("author",), "\t", "Page ", ("page",))
            setattr(cur, "BottomBorder" if which == "header" else "TopBorder", line)
        elif name == "Sideline":
            cur.CharColor = 0x595959
            if which == "header":
                put(("title",))
                cur.BottomBorder = line
            else:
                cur.ParaAdjust = 3
                put(("page",))
                cur.TopBorder = line
        elif name == "Whisp":
            cur.ParaAdjust = 1
            cur.CharPosture = bridge.enum("com.sun.star.awt.FontSlant", "ITALIC")
            cur.CharColor = 0x7F7F7F
            put(("title",))
    finally:
        um.leaveUndoContext()
    try:
        m.getTextFields().refresh()
    except Exception:
        pass


# ---------------------------------------------------------------- galleries
def gallery_parts(gallery):
    from .insertextras import load_parts
    return [p for p in load_parts() if p.get("gallery") == gallery]


def insert_saved(win, part, where):
    """A design saved by the user: a cover page goes at the start, header
    and footer content into the header / footer."""
    m = win.engine.model
    if m is None:
        return
    from .insertextras import insert_part
    if where == "cover":
        remove_cover(m)
        vc = docapi.view_cursor(m)
        vc.gotoStart(False)
        text = m.getText()
        text.insertControlCharacter(vc, 0, False)
        vc.gotoStart(False)
        insert_part(win, part)

        def brk():
            vc2 = docapi.view_cursor(m)
            c = vc2.getText().createTextCursorByRange(vc2.getStart())
            c.gotoNextParagraph(False)
            c.BreakType = bridge.enum("com.sun.star.style.BreakType", "PAGE_BEFORE")
        win.engine.sync(brk)
        return
    docapi.enable_header_footer(m, where)
    win.engine.command(".uno:JumpToHeader" if where == "header" else ".uno:JumpToFooter")
    win.engine.sync(lambda: (win.engine.command(".uno:SelectAll"),
                             insert_part(win, part), win.refresh_hf()))


def save_selection(win, gallery):
    from . import insertextras
    insertextras.save_selection_as_part(win, gallery)
