"""Cover pages and header / footer designs with the new engine, as Word keeps
them: a cover page is a block content control in the "Cover Pages" gallery at
the start of the document, ending in a page break; its coloured band is a shape
behind the text. Header and footer designs fill the section's header or footer,
with PAGE, TITLE, AUTHOR and DATE fields."""
import datetime
from xml.sax.saxutils import escape

from ..covers import COVERS, FOOTERS, HEADERS  # noqa: F401  (the same galleries)

GALLERY = "Cover Pages"
SHAPE = "CoverPageShape"


def _ed(win):
    return win.engine.ed


def _hex(c):
    return "%06X" % (c & 0xFFFFFF)


def _style_ids(ed):
    return {name: sid for sid, name in ed.paragraph_styles()}


def _props(win):
    from . import docprops
    try:
        c = docprops.core(_ed(win))
    except Exception:
        c = {}
    try:
        user = win.app.user_name()
    except Exception:
        user = ""
    return (c.get("title") or "Document title", c.get("subject") or "Document subtitle",
            c.get("creator") or user or "Author",
            datetime.date.today().strftime("%B %-d, %Y"))


def _para(text="", style=None, jc="left", color=None, size=None, caps=False, bold=False,
          bottom=None, page_break=False, italic=False, shade=None, tabs=(), runs=None):
    ppr = []
    if style:
        ppr.append('<w:pStyle w:val="%s"/>' % style)
    if bottom:
        ppr.append('<w:pBdr><w:bottom w:val="single" w:sz="12" w:space="4" w:color="%s"/></w:pBdr>' % bottom)
    if shade is not None:
        ppr.append('<w:shd w:val="clear" w:color="auto" w:fill="%s"/>' % _hex(shade))
    if tabs:
        ppr.append("<w:tabs>%s</w:tabs>" % "".join('<w:tab w:val="%s" w:pos="%d"/>' % (k, int(p)) for p, k in tabs))
    if jc != "left":
        ppr.append('<w:jc w:val="%s"/>' % jc)
    rpr = []
    if bold:
        rpr.append("<w:b/>")
    if italic:
        rpr.append("<w:i/>")
    if caps:
        rpr.append("<w:caps/>")
    if color is not None:
        rpr.append('<w:color w:val="%s"/>' % _hex(color))
    if size:
        rpr.append('<w:sz w:val="%d"/><w:szCs w:val="%d"/>' % (size * 2, size * 2))
    r = "<w:rPr>%s</w:rPr>" % "".join(rpr) if rpr else ""
    body = ""
    for piece in (runs if runs is not None else ([text] if text else [])):
        if isinstance(piece, tuple):
            instr, shown = piece
            body += ('<w:r>%s<w:fldChar w:fldCharType="begin"/></w:r><w:r>%s<w:instrText xml:space="preserve"> %s </w:instrText></w:r>'
                     '<w:r>%s<w:fldChar w:fldCharType="separate"/></w:r><w:r>%s<w:t xml:space="preserve">%s</w:t></w:r>'
                     '<w:r>%s<w:fldChar w:fldCharType="end"/></w:r>' % (r, r, instr, r, r, escape(shown), r))
        elif piece == "\t":
            body += "<w:r>%s<w:tab/></w:r>" % r
        else:
            body += '<w:r>%s<w:t xml:space="preserve">%s</w:t></w:r>' % (r, escape(piece))
    if page_break:
        body += '<w:r><w:br w:type="page"/></w:r>'
    return "<w:p>%s%s</w:p>" % ("<w:pPr>%s</w:pPr>" % "".join(ppr) if ppr else "", body)


def cover_id(ed):
    for cid, pr, _t, block in ed.content_controls():
        if block and GALLERY in pr:
            return cid
    return None


def remove_cover(win):
    ed = _ed(win)
    found = False
    ed.begin_group("Remove Cover Page")
    try:
        for _i in range(20):
            objs = [o for o in ed.objects_list() if (o[1] or "").startswith(SHAPE)]
            if not objs:
                break
            ed.select_object_node(objs[0][0])
            ed.object_delete()
            found = True
        cid = cover_id(ed)
        if cid is not None:
            ed.move_caret("doc_end", False)
            ed.remove_control(cid, False)
            # the empty paragraphs the cover left at the start
            for _i in range(5):
                blocks = ed.body_blocks()
                if len(blocks) > 1 and blocks[0][0] == "p" and not ed.para_text_of(blocks[0][1]):
                    ed.select_nodes(blocks[0][1], 0, blocks[0][1], 0)
                    ed.delete(True, False)
                else:
                    break
            ed.move_caret("doc_start", False)
            found = True
    finally:
        ed.end_group()
    if found:
        win.engine.view.after_edit()
    return found


def insert_cover(win, name):
    ed = _ed(win)
    spec = dict(COVERS)[name]
    ids = _style_ids(ed)
    title, sub, author, date = _props(win)
    band = spec.get("band")
    on_dark = band == "full"
    tcol = 0xFFFFFF if on_dark or band == "top" else spec["accent"]
    jc = {"left": "left", "right": "right", "center": "center"}[spec["align"]]
    ps = []
    for _ in range({"top": 2, "bottom": 7, "left": 7, "full": 8}.get(band, 6)):
        ps.append(_para())
    ps.append(_para(title, ids.get("Title"), jc, tcol, spec["size"], spec["caps"],
                    bottom=_hex(spec["accent"]) if spec.get("rule") else None))
    ps.append(_para(sub, ids.get("Subtitle"), jc, 0xFFFFFF if band in ("top", "full") else 0x595959))
    for _ in range({"top": 16, "bottom": 4, "full": 10}.get(band, 14)):
        ps.append(_para())
    light = band in ("bottom", "full")
    ps.append(_para(author, None, jc, 0xFFFFFF if light else spec["accent"], bold=True))
    ps.append(_para(date, None, jc, 0xFFFFFF if light else 0x595959, page_break=True))
    sdt = ('<w:sdt><w:sdtPr><w:id w:val="%d"/><w:docPartObj><w:docPartGallery w:val="%s"/>'
           '<w:docPartUnique/></w:docPartObj></w:sdtPr><w:sdtContent>%s</w:sdtContent></w:sdt>'
           % (abs(hash(name)) % 2000000000, GALLERY, "".join(ps)))
    ed.begin_group("Cover Page")
    try:
        remove_cover(win)
        ed.move_caret("doc_start", False)
        ed.paste_fragment(sdt, False)
        if band:
            ed.move_caret("doc_start", False)
            W, H = ed.page_size(0)
            x, y, w, h = {"top": (0, 0, W, H * 0.38), "bottom": (0, H * 0.72, W, H * 0.28),
                          "left": (0, 0, W * 0.08, H), "full": (0, 0, W, H)}[band]
            if ed.insert_shape("rect", 0, x, y, w, h, SHAPE + "1", False):
                ed.object_fill('<a:solidFill><a:srgbClr val="%s"/></a:solidFill>' % _hex(spec["accent"]))
                ed.object_set_wrap("behind")
                ed.deselect_object()
    finally:
        ed.end_group()
    ed.move_caret("doc_start", False)
    win.engine.view.after_edit()
    return True


# ---------------------------------------------------------------- headers / footers
def hf_design(win, which, name):
    """A built-in design in the current section's header or footer."""
    ed = _ed(win)
    footer = which == "footer"
    pg = ed.caret_page()
    accent = 0x4472C4
    W, _H = ed.page_size(pg)
    try:
        mg = ed.page_margins(pg)
        ml, mr = mg[3], mg[1]
    except Exception:
        ml = mr = 72
    tw = (W - ml - mr) * 20
    title_f = ("TITLE", _props(win)[0])
    page_f = ("PAGE", str(pg + 1))
    date_f = ('DATE \\@ "MMMM d, yyyy"', datetime.date.today().strftime("%B %-d, %Y"))
    author_f = ("AUTHOR", _props(win)[2])
    line = _hex(accent)
    if name == "Blank":
        p = _para("[Type here]")
    elif name == "Blank (Three Columns)":
        p = _para(runs=["[Type here]", "\t", "[Type here]", "\t", "[Type here]"],
                  tabs=((tw / 2, "center"), (tw, "right")))
    elif name in ("Austin", "Ion", "Semaphore"):
        p = _para(runs=[title_f if not footer else page_f], jc="right" if name != "Semaphore" else "center", color=accent)
    elif name == "Banded":
        p = _para(runs=[title_f if not footer else page_f], jc="center", color=0xFFFFFF, shade=accent)
    elif name == "Facet":
        p = _para(runs=[title_f] if not footer else [title_f, "\t", page_f], color=accent, tabs=((tw, "right"),) if footer else ())
    elif name == "Grid":
        p = _para(runs=[title_f, "\t", date_f], tabs=((tw, "right"),))
    elif name == "Integral":
        p = _para(runs=[title_f] if not footer else [author_f, "\t", page_f], caps=True, color=accent,
                  jc="center" if not footer else "left", tabs=((tw, "right"),) if footer else (), bottom=line)
    elif name == "Retrospect":
        p = _para(runs=[title_f, "\t", date_f] if not footer else [author_f, "\t", "Page ", page_f],
                  color=0x595959, tabs=((tw, "right"),), bottom=line)
    elif name == "Sideline":
        p = _para(runs=[title_f] if not footer else [page_f], color=0x595959,
                  jc="center" if footer else "left", bottom=line)
    elif name == "Whisp":
        p = _para(runs=[title_f], jc="right", color=0x7F7F7F, italic=True)
    else:
        p = _para("[Type here]")
    ed.begin_group("Footer" if footer else "Header")
    try:
        if not ed.page_hf(pg)[1 if footer else 0]:
            ed.ensure_header_footer_kind(ed.page_section(pg), footer, ed.page_hf_kind(pg))
        ed.edit_header_footer(pg, footer)
        ed.select_all()
        ed.paste_fragment(p, False)
    finally:
        ed.end_group()
    try:
        ed.update_fields()
    except Exception:
        pass
    win.engine.view.document_changed()
    win.engine.view.scroll_to_caret()
    return True


def remove_hf(win, which):
    ed = _ed(win)
    pg = ed.caret_page()
    footer = which == "footer"
    if not ed.page_hf(pg)[1 if footer else 0]:
        return False
    ed.edit_header_footer(pg, footer)
    ed.select_all()
    ed.delete(True, False)
    ed.edit_header_footer(None)
    win.engine.view.after_edit()
    return True
