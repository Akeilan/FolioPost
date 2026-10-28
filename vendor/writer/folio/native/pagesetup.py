"""Layout > Margins, Orientation, Size and Columns with the new engine:
the section's w:sectPr (the caret's section), and mirror margins."""

TW_PER_MM100 = 1440.0 / 2540.0


def _tw(mm100):
    return str(int(round(mm100 * TW_PER_MM100)))


def _apply(win, label, changes):
    ed = win.engine.ed
    sec = ed.current_section()
    ed.begin_group(label)
    try:
        for el, attr, val in changes:
            ed.section_attr(sec, el, attr, val, label)
    finally:
        ed.end_group()
    win.engine.view.document_changed()


def margins(win, top, bottom, left, right, mirrored=False):
    """Margins in 1/100 mm; mirrored: inside / outside on facing pages."""
    ed = win.engine.ed
    ed.begin_group("Margins")
    _apply(win, "Margins", [("w:pgMar", "w:top", _tw(top)), ("w:pgMar", "w:bottom", _tw(bottom)),
                            ("w:pgMar", "w:left", _tw(left)), ("w:pgMar", "w:right", _tw(right))])
    ed.set_setting("mirrorMargins", bool(mirrored))
    ed.end_group()
    win.engine.view.document_changed()


def orientation(win, landscape):
    ed = win.engine.ed
    ps = ed.page_setup(ed.current_section())
    if ps is None:
        return
    w, h = ps["width"], ps["height"]
    if bool(landscape) == (w > h):
        return
    _apply(win, "Orientation", [("w:pgSz", "w:w", str(h)), ("w:pgSz", "w:h", str(w)),
                                ("w:pgSz", "w:orient", "landscape" if landscape else None)])


def paper(win, width, height):
    """Paper size in 1/100 mm, in the current orientation."""
    ed = win.engine.ed
    ps = ed.page_setup(ed.current_section())
    landscape = bool(ps and ps["width"] > ps["height"])
    w, h = (max(width, height), min(width, height)) if landscape else (min(width, height), max(width, height))
    _apply(win, "Size", [("w:pgSz", "w:w", _tw(w)), ("w:pgSz", "w:h", _tw(h))])


def columns(win, n, space_tw=720):
    _apply(win, "Columns", [("w:cols", "w:num", str(int(n)) if int(n) > 1 else None),
                            ("w:cols", "w:space", str(space_tw))])


# ---------------------------------------------------------------- the Page Setup dialog
MM_PER_TW = 2540.0 / 1440.0
START = {"continuous": 0, "nextColumn": 1, "nextPage": 2, "evenPage": 3, "oddPage": 4}
START_VAL = {v: k for k, v in START.items()}
VALIGN = {"top": "TOP", "center": "CENTER", "both": "BLOCK", "bottom": "BOTTOM"}
VALIGN_VAL = {v: k for k, v in VALIGN.items()}


def _mm(tw):
    return int(round((tw or 0) * MM_PER_TW))


def read(win):
    """The current section's page, as the dialog wants it (1/100 mm)."""
    ed = win.engine.ed
    ps = ed.page_setup(ed.current_section())
    return {"width": _mm(ps["width"]), "height": _mm(ps["height"]), "top": _mm(ps["top"]),
            "bottom": _mm(ps["bottom"]), "left": _mm(ps["left"]), "right": _mm(ps["right"]),
            "gutter": _mm(ps["gutter"]), "landscape": ps["width"] > ps["height"],
            "mirror": ed.setting("mirrorMargins"), "gutter_top": ed.setting("gutterAtTop"),
            "valign": VALIGN.get(ps["v_align"] or "top", "TOP"),
            "diff_odd_even": ed.setting("evenAndOddHeaders"), "diff_first": bool(ps["title_pg"]),
            "header_edge": _mm(ps["header"]), "footer_edge": _mm(ps["footer"]),
            "header": True, "footer": True, "start": START.get(ps["start"] or "nextPage", 2),
            "section_count": ps["section_count"]}


def _apply_section(ed, sec, v):
    w, h = v["width"], v["height"]
    if v["landscape"]:
        w, h = max(w, h), min(w, h)
    else:
        w, h = min(w, h), max(w, h)
    lab = "Page Setup"
    for el, attr, val in (("w:pgSz", "w:w", _tw(w)), ("w:pgSz", "w:h", _tw(h)),
                          ("w:pgSz", "w:orient", "landscape" if v["landscape"] else None),
                          ("w:pgMar", "w:top", _tw(v["top"])), ("w:pgMar", "w:bottom", _tw(v["bottom"])),
                          ("w:pgMar", "w:left", _tw(v["left"])), ("w:pgMar", "w:right", _tw(v["right"])),
                          ("w:pgMar", "w:gutter", _tw(v["gutter"])),
                          ("w:pgMar", "w:header", _tw(v["header_edge"])),
                          ("w:pgMar", "w:footer", _tw(v["footer_edge"])),
                          ("w:type", "w:val", None if v["start"] == 2 else START_VAL.get(v["start"])),
                          ("w:vAlign", "w:val", None if v["valign"] == "TOP" else VALIGN_VAL.get(v["valign"]))):
        ed.section_attr(sec, el, attr, val, lab)
    ed.section_flag(sec, "w:titlePg", bool(v["diff_first"]), lab)


def apply_to(win, v, where):
    """where: 0 whole document, 1 this section, 2 this point forward (a new section)."""
    ed = win.engine.ed
    ed.begin_group("Page Setup")
    try:
        if where == 0:
            secs = list(range(ed.page_setup(0)["section_count"]))
        elif where == 2:
            kind = {0: "continuous", 3: "evenPage", 4: "oddPage"}.get(v["start"], "nextPage")
            ed.insert_break(kind)
            secs = [ed.current_section()]
        else:
            secs = [ed.current_section()]
        for sec in secs:
            _apply_section(ed, sec, v)
        ed.set_setting("mirrorMargins", bool(v["mirror"]))
        ed.set_setting("gutterAtTop", bool(v["gutter_top"]))
        ed.set_setting("evenAndOddHeaders", bool(v["diff_odd_even"]))
    finally:
        ed.end_group()
    win.engine.view.document_changed()


def set_default(win, v):
    """Set As Default: the Normal template's page."""
    from . import edit_normal_template

    def fn(ed):
        for sec in range(ed.page_setup(0)["section_count"]):
            _apply_section(ed, sec, dict(v, start=2))
        ed.set_setting("mirrorMargins", bool(v["mirror"]))
        ed.set_setting("gutterAtTop", bool(v["gutter_top"]))
    try:
        edit_normal_template(win.app, fn)
    except Exception as e:
        print("page default:", e)
