"""Review > Language with the new engine: w:lang (and w:noProof) on the selected text, the
Normal template's default language; spelling as you type follows."""


def set_language(win, lang, country, no_proof=False, default=False):
    ed = win.engine.ed
    tag = "%s-%s" % (lang, country) if country else lang
    ed.begin_group("Language")
    ed.apply_run([("w:lang", [("w:val", tag)]), ("w:noProof", [] if no_proof else None)], "Language")
    if default:
        _default_lang(win, tag)
    ed.end_group()
    win.engine.view.after_edit()
    sp = getattr(win.engine.view, "speller", None)
    if sp is not None:
        sp.cache.clear()
        sp.invalidate()


def _default_lang(win, tag):
    """The document's and the Normal template's default (the Normal style)."""
    ed = win.engine.ed
    sid = next((sid for sid, name in ed.paragraph_styles() if name == "Normal"), "Normal")
    ed.style_apply_run(sid, [("w:lang", [("w:val", tag)])])
    try:
        from . import edit_normal_template
        edit_normal_template(win.app, lambda t: t.style_apply_run(sid, [("w:lang", [("w:val", tag)])]))
    except Exception as e:
        print("default language:", e)
