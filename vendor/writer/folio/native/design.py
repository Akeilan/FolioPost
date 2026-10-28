"""Design tab with the new engine: theme colours and fonts (the theme part),
themes, paragraph spacing, and Set as Default."""
import os

from .. import themedata as TD


def _done(win):
    win.engine.view.document_changed()
    try:
        win.design_changed()
    except Exception:
        pass


def colors(win, name):
    cs = TD.COLOR_SCHEMES.get(name)
    if cs and win.engine.ed.set_theme_colors(name, cs):
        _done(win)


def fonts(win, name):
    fs = TD.FONT_SCHEMES.get(name)
    if fs and win.engine.ed.set_theme_fonts(name, fs[0], fs[1]):
        _done(win)


def theme(win, name):
    c, f = TD.THEMES.get(name, ("Standard", "Standard"))
    ed = win.engine.ed
    ed.begin_group("Theme")
    ed.set_theme_colors(c, TD.COLOR_SCHEMES[c])
    ed.set_theme_fonts(f, *TD.FONT_SCHEMES[f])
    ed.end_group()
    _done(win)


def spacing(win, preset):
    before, after, line = TD.SPACING.get(preset, TD.SPACING["default"])
    if win.engine.ed.set_paragraph_spacing(before * 20, after * 20, int(round(line * 2.4))):
        _done(win)


def set_as_default(win):
    if not win.dialogs.confirm("Do you want to set the current style set and theme as the default?\n\n"
                               "New documents will use these settings.", yes="Yes", no="No"):
        return
    app = win.app
    try:
        src = app.normal_template()
    except FileNotFoundError:
        return
    base = os.path.splitext(os.path.basename(src))[0]
    tpl = os.path.splitext(src)[0] + ".docx"
    if not os.path.exists(tpl):
        for d in ("/usr/share/folio-writer/templates",
                  os.path.join(os.path.dirname(__file__), "..", "..", "..", "share", "templates")):
            p = os.path.join(d, base + ".docx")
            if os.path.exists(p):
                tpl = p
                break
    out = os.path.join(os.path.dirname(app.user_template_path()), base + ".docx")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    try:
        win.engine.ed.save_as_template(tpl, out)
    except OSError as e:
        win.dialogs.message("Folio couldn't save the default template.\n\n%s" % e, kind="error")
