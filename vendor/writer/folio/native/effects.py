"""WordArt, Text Effects and Quick Parts > Document Property with the new
engine."""


def _ed(win):
    return win.engine.ed


def _effect_run(spec):
    """Run properties for a WordArt / Text Effects style."""
    _name, color, outline, shadow, bold = spec
    edits = [("w:color", [("w:val", "%06X" % color)])]
    if bold:
        edits.append(("w:b", []))
    if outline:
        edits.append(("w:outline", []))
    if shadow:
        edits.append(("w:shadow", []))
    return edits


def text_effect(win, i):
    from ..insertextras import EFFECTS
    ed = _ed(win)
    ed.apply_run(_effect_run(EFFECTS[i]), "Text Effects")
    win.engine.view.after_edit()


def toggle_char(win, prop):
    el = {"CharContoured": "w:outline", "CharShadowed": "w:shadow"}.get(prop)
    if el is None:
        return
    ed = _ed(win)
    ed.toggle(el)
    win.engine.view.after_edit()


def insert_wordart(win, i):
    """Insert > WordArt: a text box without fill or line, its text in the style."""
    from ..insertextras import EFFECTS
    ed = _ed(win)
    sel = ed.selected_text() if ed.has_selection() else ""
    text = sel.strip() or "Your text here"
    pg = ed.caret_page()
    ps = ed.page_setup(ed.current_section()) or {}
    pw = ps.get("width", 12240) / 20.0
    left, right, top = ps.get("left", 1440) / 20.0, ps.get("right", 1440) / 20.0, ps.get("top", 1440) / 20.0
    w = min(pw - left - right, 40.0 + 26.0 * len(text))
    ed.begin_group("Insert WordArt")
    try:
        if not ed.insert_shape("textbox", pg, left + (pw - left - right - w) / 2.0, top + 60.0, w, 70.0, "WordArt"):
            return False
        ed.type_text(text)
        ed.select_all()
        ed.set_size(36.0)
        ed.apply_run(_effect_run(EFFECTS[i]), "WordArt")
        ed.select_story_textbox()
        ed.object_fill("<a:noFill/>")
        ed.object_outline("<a:ln><a:noFill/></a:ln>")
    finally:
        ed.end_group()
    win.engine.view.after_edit()
    try:
        win.update_object_tabs()
    except Exception:
        pass
    return True


DOC_FIELDS = {"Author": "AUTHOR", "Title": "TITLE", "Subject": "SUBJECT", "Keywords": "KEYWORDS",
              "Comments": "COMMENTS", "Company": "DOCPROPERTY Company", "Status": "DOCPROPERTY Status"}


def insert_doc_property(win, name):
    ed = _ed(win)
    code = DOC_FIELDS.get(name, 'DOCPROPERTY "%s"' % name)
    ed.insert_field_now(code + " \\* MERGEFORMAT")
    win.engine.view.after_edit()
