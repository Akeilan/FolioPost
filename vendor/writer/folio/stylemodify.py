"""Editing styles the way the original does: right-click a style in the Styles
gallery or the Styles pane (Update to Match Selection, Modify..., Select All,
Rename..., Add to/Remove from Style Gallery) and the full Modify Style dialog
with its formatting toolbar, preview, description and Format menu."""
import json

from gi.repository import Gtk, Pango, PangoCairo

from . import bridge, docapi, icons
from .actions import CHAR_STYLES, engine_style, word_style
from .widgets import FDialog, color_button, combo, combo_text, grid, heading

SIZES = ["8", "9", "10", "10.5", "11", "12", "14", "16", "18", "20", "22", "24", "26", "28",
         "36", "48", "72"]
ALIGNS = [("Align Left", 0, "cmd/sc_leftpara"), ("Center", 3, "cmd/sc_centerpara"),
          ("Align Right", 1, "cmd/sc_rightpara"), ("Justify", 2, "cmd/sc_justifypara")]
SPACINGS = [("Single Space", 100, "cmd/sc_spacepara1"), ("1.5 Space", 150, "cmd/sc_spacepara15"),
            ("Double Space", 200, "cmd/sc_spacepara2")]
COLOR_NAMES = {0x000000: "Black", 0xFFFFFF: "White", 0x2F5496: "Accent 1, Darker 25%",
               0x4472C4: "Accent 1", 0x1F3763: "Accent 1, Darker 50%", 0x404040: "Text 1, "
               "Lighter 25%", 0x5A5A5A: "Text 1, Lighter 35%", 0xED7D31: "Accent 2"}


# ------------------------------------------------------------ helpers
def _model(win):
    eng = win.engine
    if getattr(eng, "native", False):
        from .native.uno_model import NativeModel
        return NativeModel(eng)
    return eng.model


class StyleProxy:
    """Reads a style (or the current formatting); writes are kept until the
    dialog's OK. The font / paragraph / tabs dialogs work on it as they would
    on the cursor."""

    def __init__(self, base):
        object.__setattr__(self, "_base", base)
        object.__setattr__(self, "pending", {})

    def __getattr__(self, k):
        p = object.__getattribute__(self, "pending")
        if k in p:
            return p[k]
        return getattr(object.__getattribute__(self, "_base"), k)

    def __setattr__(self, k, v):
        self.pending[k] = v

    def getString(self):
        return ""

    def isCollapsed(self):
        return True


def style_family(m, name):
    eng = engine_style(name)
    fams = m.getStyleFamilies()
    if name in CHAR_STYLES or (fams.getByName("CharacterStyles").hasByName(eng) and
                               not fams.getByName("ParagraphStyles").hasByName(eng)):
        return "CharacterStyles"
    return "ParagraphStyles"


def style_obj(m, name):
    fam = style_family(m, name)
    f = m.getStyleFamilies().getByName(fam)
    eng = engine_style(name)
    return (f.getByName(eng) if f.hasByName(eng) else None), fam


def gallery_names(m):
    from .ribbon_defs import GALLERY
    default = [n for n, _a in GALLERY]
    if m is None:
        return default
    try:
        v = json.loads(docapi._doc_setting(m, "StyleGallery", "") or "null")
    except ValueError:
        v = None
    return v if isinstance(v, list) and v else default


def set_gallery(m, names):
    docapi._set_doc_setting(m, "StyleGallery", json.dumps(names))


def in_gallery(m, name):
    return name in gallery_names(m)


def toggle_gallery(win, name, on=None):
    m = _model(win)
    names = gallery_names(m)
    on = (name not in names) if on is None else on
    if on and name not in names:
        names.append(name)
    elif not on and name in names:
        names.remove(name)
    set_gallery(m, names)
    win.refresh_styles()


def instances(m, name):
    """Paragraphs (or text) using the style, as a found-ranges container."""
    st, fam = style_obj(m, name)
    if st is None:
        return None
    try:
        sd = m.createSearchDescriptor()
        sd.SearchStyles = True
        sd.SearchString = st.DisplayName if fam == "ParagraphStyles" else st.Name
        if fam == "CharacterStyles":
            return None
        found = m.findAll(sd)
        return found if found.getCount() else None
    except Exception as e:
        print("instances:", e)
        return None


def count_instances(m, name):
    if hasattr(m, "eng") and getattr(m.eng, "native", False):
        sid = m.id_of(name)
        return m.eng.ed.count_style_instances(sid) if sid else 0
    f = instances(m, name)
    return f.getCount() if f is not None else 0


def select_all(win, name):
    if getattr(win.engine, "native", False):
        from .native.uno_model import NativeModel
        sid = NativeModel(win.engine).id_of(name)
        if sid:
            win.engine.ed.select_style_instances(sid)
            win.engine.view.after_move()
        win.focus_document()
        return
    m = _model(win)
    f = instances(m, name)
    if f is not None:
        docapi.controller(m).select(f)
    win.focus_document()


def update_to_match(win, name):
    m = _model(win)
    st, fam = style_obj(m, name)
    if st is None:
        return
    vc = docapi.read_cursor(m)
    um = m.getUndoManager()
    um.enterUndoContext("Update Style")
    try:
        for p in docapi.STYLE_PROPS:
            if fam == "CharacterStyles" and p.startswith("Para"):
                continue
            try:
                setattr(st, p, getattr(vc, p))
            except Exception:
                pass
    finally:
        um.leaveUndoContext()
    win.refresh_styles()


def rename_style(win, name):
    m = _model(win)
    st, fam = style_obj(m, name)
    if st is None:
        return
    new = win.dialogs.ask_text("Rename Style", "Enter new name for the style:", name)
    if not new or new.strip() == name:
        return
    new = new.strip()
    f = m.getStyleFamilies().getByName(fam)
    if f.hasByName(engine_style(new)):
        win.dialogs.message("A style with that name already exists.")
        return
    try:
        st.setName(new)
    except Exception as e:
        win.dialogs.message("Built-in styles can't be renamed." if not st.isUserDefined()
                            else "The style couldn't be renamed: %s" % e)
        return
    names = gallery_names(m)
    if name in names:
        names[names.index(name)] = new
        set_gallery(m, names)
    win.refresh_styles()


def context_menu(win, name, widget, event=None):
    """The right-click menu for a style."""
    from .ribbon import menu_popover
    m = _model(win)
    if m is None:
        return
    st, _fam = style_obj(m, name)
    n = count_instances(m, name)
    user = bool(st is not None and st.isUserDefined())
    items = [("Update %s to Match Selection" % name, lambda: update_to_match(win, name)),
             ("Modify...", lambda: modify_dialog(win, name))]
    sel = ("Select All: %d Instance(s)" % n, lambda: select_all(win, name)) if n else \
        _disabled("Select All: (No Data)")
    items.append(sel)
    items.append(("Rename...", lambda: rename_style(win, name)) if user else
                 _disabled("Rename..."))
    if in_gallery(m, name):
        items.append(("Remove from Style Gallery", lambda: toggle_gallery(win, name, False)))
    else:
        items.append(("Add to Style Gallery", lambda: toggle_gallery(win, name, True)))
    if user:
        items += [None, ("Delete %s..." % name, lambda: delete_style(win, name))]
    pop = menu_popover(widget, items)
    if event is not None:
        from .panes import Gdk_rect
        pop.set_pointing_to(Gdk_rect(event))
    pop.popup()
    return pop


def _disabled(label):
    b = Gtk.Button(label=label)
    b.set_relief(Gtk.ReliefStyle.NONE)
    b.get_child().set_xalign(0)
    b.set_sensitive(False)
    return b


def delete_style(win, name):
    m = _model(win)
    st, fam = style_obj(m, name)
    if st is None or not st.isUserDefined():
        return
    if not win.dialogs.confirm("Do you want to delete style %s from the document?" % name,
                               yes="Yes", no="No"):
        return
    m.getStyleFamilies().getByName(fam).removeByName(st.Name)
    names = gallery_names(m)
    if name in names:
        names.remove(name)
        set_gallery(m, names)
    win.refresh_styles()


# ------------------------------------------------------------ description
def _color_name(c):
    if c is None or c < 0:
        return "Auto"
    return COLOR_NAMES.get(c & 0xFFFFFF, "Custom Color(RGB(%d,%d,%d))" % (
        (c >> 16) & 255, (c >> 8) & 255, c & 255))


def describe(p, fam, based, follow, gallery, auto):
    parts = []
    try:
        parts.append("Font: %s, %g pt" % (p.CharFontName, p.CharHeight))
        if p.CharWeight >= 150:
            parts.append("Bold")
        if getattr(p.CharPosture, "value", "NONE") != "NONE":
            parts.append("Italic")
        if p.CharUnderline:
            parts.append("Underline")
        if p.CharColor not in (-1, None):
            parts.append("Font color: %s" % _color_name(p.CharColor))
        if p.CharCaseMap == 1:
            parts.append("All caps")
        elif p.CharCaseMap == 4:
            parts.append("Small caps")
    except Exception:
        pass
    if fam == "ParagraphStyles":
        try:
            al = {0: "Left", 1: "Right", 2: "Justified", 3: "Centered"}.get(p.ParaAdjust)
            if al and al != "Left":
                parts.append(al)
            ls = p.ParaLineSpacing
            if ls.Mode == 0:
                parts.append("Line spacing: %s" % {100: "single", 150: "1.5 lines",
                                                    200: "double"}.get(
                    ls.Height, "Multiple %g li" % (ls.Height / 100.0)))
            else:
                parts.append("Line spacing: %s %g pt" % ("Exactly" if ls.Mode == 3 else
                                                         "At least",
                                                         round(docapi.to_pt(ls.Height), 1)))
            parts.append("Space Before: %g pt" % round(docapi.to_pt(p.ParaTopMargin), 1))
            parts.append("After: %g pt" % round(docapi.to_pt(p.ParaBottomMargin), 1))
            if p.ParaLeftMargin:
                parts.append("Indent: Left: %.2f cm" % (p.ParaLeftMargin / 1000.0))
            if p.ParaKeepTogether:
                parts.append("Keep with next")
            if not p.ParaSplit:
                parts.append("Keep lines together")
            lvl = getattr(p, "OutlineLevel", 0) or 0
            if lvl:
                parts.append("Level %d" % lvl)
        except Exception:
            pass
    out = ", ".join(parts)
    extra = []
    extra.append("Style: %s" % ("Character" if fam == "CharacterStyles" else "Linked"))
    if gallery:
        extra.append("Show in the Styles gallery")
    if auto:
        extra.append("Automatically update")
    out += "\n" + ", ".join(extra)
    if based:
        out += "\nBased on: %s" % based
    if follow and fam == "ParagraphStyles":
        out += "\nFollowing style: %s" % follow
    return out


# ------------------------------------------------------------ preview
def _draw_preview(area, cr, p, fam):
    W, H = area.get_allocated_width(), area.get_allocated_height()
    cr.set_source_rgb(1, 1, 1)
    cr.paint()
    pad = 10
    width = W - 2 * pad

    def para(y, text, desc, color, align=0, indent=0):
        lay = PangoCairo.create_layout(cr)
        lay.set_font_description(desc)
        lay.set_width(int((width - indent) * Pango.SCALE))
        lay.set_wrap(Pango.WrapMode.WORD)
        lay.set_alignment({0: Pango.Alignment.LEFT, 1: Pango.Alignment.RIGHT,
                           3: Pango.Alignment.CENTER}.get(align, Pango.Alignment.LEFT))
        if align == 2:
            lay.set_justify(True)
        lay.set_text(text, -1)
        cr.set_source_rgb(*color)
        cr.move_to(pad + indent, y)
        PangoCairo.show_layout(cr, lay)
        return y + lay.get_pixel_size()[1]

    grey = (0.62, 0.62, 0.62)
    small = Pango.FontDescription("Sans 6.5")
    prev = ("Previous Paragraph " * 14).strip()
    y = para(4, prev, small, grey)
    try:
        before = docapi.to_pt(p.ParaTopMargin) if fam == "ParagraphStyles" else 0
        after = docapi.to_pt(p.ParaBottomMargin) if fam == "ParagraphStyles" else 0
        align = p.ParaAdjust if fam == "ParagraphStyles" else 0
        indent = (p.ParaLeftMargin / 2540.0 * 96 * 0.5) if fam == "ParagraphStyles" else 0
    except Exception:
        before = after = indent = 0
        align = 0
    y += min(18, before * 0.6) + 4
    desc = Pango.FontDescription()
    try:
        desc.set_family(p.CharFontName or "Sans")
        desc.set_size(int(min(20, max(6, p.CharHeight * 0.8)) * Pango.SCALE))
        if p.CharWeight >= 150:
            desc.set_weight(Pango.Weight.BOLD)
        if getattr(p.CharPosture, "value", "NONE") != "NONE":
            desc.set_style(Pango.Style.ITALIC)
        if p.CharCaseMap == 4:
            desc.set_variant(Pango.Variant.SMALL_CAPS)
        c = p.CharColor
        color = (0, 0, 0) if c in (-1, None) or c < 0 else (
            ((c >> 16) & 255) / 255.0, ((c >> 8) & 255) / 255.0, (c & 255) / 255.0)
        caps = p.CharCaseMap == 1
    except Exception:
        color, caps = (0, 0, 0), False
    sample = ("Sample Text " * 9).strip()
    if fam == "CharacterStyles":
        sample = "Sample Text Sample Text Sample Text"
    y0 = y
    y = para(y, sample.upper() if caps else sample, desc, color, align, indent)
    try:
        if p.CharUnderline:
            cr.set_source_rgb(*color)
            cr.rectangle(pad + indent, y - 2, min(width - indent, 200), 1)
            cr.fill()
    except Exception:
        pass
    _ = y0
    y += min(18, after * 0.6) + 4
    para(y, ("Following Paragraph " * 14).strip(), small, grey)
    return False


# ------------------------------------------------------------ the dialog
def modify_dialog(win, name=None):
    """Modify Style (name given) or Create New Style from Formatting."""
    m = _model(win)
    if m is None:
        return
    fams = m.getStyleFamilies()
    if name:
        st, fam = style_obj(m, name)
        if st is None:
            win.dialogs.message("The style %s doesn't exist in this document." % name)
            return
        proxy = StyleProxy(st)
        try:
            parent = word_style(st.ParentStyle) if st.ParentStyle else ""
        except Exception:
            parent = ""
        if parent in ("Heading", ""):
            parent = "Normal" if name != "Normal" else ""
        try:
            follow0 = word_style(fams.getByName("ParagraphStyles").getByName(
                st.FollowStyle).DisplayName) if fam == "ParagraphStyles" else ""
        except Exception:
            follow0 = name
        auto0 = bool(getattr(st, "IsAutoUpdate", False)) if fam == "ParagraphStyles" else False
    else:
        st, fam = None, "ParagraphStyles"
        vc = docapi.read_cursor(m)
        proxy = StyleProxy(vc)
        parent = word_style(vc.ParaStyleName or "Standard")
        follow0 = None
        auto0 = False
    para_names = sorted({word_style(d) for _n, d in docapi.style_names(m, "ParagraphStyles")},
                        key=str.lower)
    char_names = sorted({word_style(d) for _n, d in docapi.style_names(m, "CharacterStyles")},
                        key=str.lower)

    d = FDialog(win, "Modify Style" if name else "Create New Style from Formatting")
    d.add(heading("Properties"))
    name_e = Gtk.Entry(text=name or _unique_name(m))
    name_e.set_activates_default(True)
    if st is not None and not st.isUserDefined():
        name_e.set_editable(False)
        name_e.set_can_focus(False)
    kind = combo(["Linked (paragraph and character)", "Paragraph", "Character"],
                 2 if fam == "CharacterStyles" else 0)
    kind.set_sensitive(name is None)
    based = combo(["(no style)"] + (para_names if fam == "ParagraphStyles" else char_names),
                  parent or "(no style)")
    follow = combo(para_names, follow0 or (name or "Normal"))
    d.add(grid([["_Name:", name_e], ["Style _type:", kind], ["Style _based on:", based],
                ["_Style for following paragraph:", follow]]))
    d.add(heading("Formatting"))

    # ---- toolbar
    state = {"busy": False}
    fonts = win.engine.fonts() or ["Carlito"]
    font = combo(fonts, proxy.CharFontName or "Carlito", entry=True)
    font.get_child().set_width_chars(16)
    size = combo(SIZES, "%g" % (proxy.CharHeight or 11), entry=True)
    size.get_child().set_width_chars(4)
    toggles = {}

    def tbtn(key, label, tip):
        b = Gtk.ToggleButton(label=label)
        b.set_tooltip_text(tip)
        toggles[key] = b
        return b
    bold, ital, und = tbtn("b", "B", "Bold"), tbtn("i", "I", "Italic"), tbtn("u", "U", "Underline")
    bold.get_child().set_markup("<b>B</b>")
    ital.get_child().set_markup("<i>I</i>")
    und.get_child().set_markup("<u>U</u>")
    color = color_button(proxy.CharColor if proxy.CharColor is not None else -1,
                         on_change=lambda c: changed("color", c))
    row1 = Gtk.Box(spacing=4)
    for w in (font, size, bold, ital, und, color):
        row1.pack_start(w, False, False, 0)
    d.add(row1)

    row2 = Gtk.Box(spacing=2)
    align_btns, space_btns = {}, {}

    def ibtn(icon, tip, cb, toggle=True):
        b = Gtk.ToggleButton() if toggle else Gtk.Button()
        b.add(icons.image(icon, 16))
        b.set_tooltip_text(tip)
        b.connect("toggled" if toggle else "clicked", lambda w: cb(w))
        row2.pack_start(b, False, False, 0)
        return b
    for tip, val, icon in ALIGNS:
        align_btns[val] = ibtn(icon, tip, lambda w, v=val: w.get_active() and changed("align", v))
    row2.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 4)
    for tip, val, icon in SPACINGS:
        space_btns[val] = ibtn(icon, tip, lambda w, v=val: w.get_active() and changed("line", v))
    row2.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 4)
    ibtn("cmd/sc_paraspaceincrease", "Increase Paragraph Spacing",
         lambda w: changed("space", 6), toggle=False)
    ibtn("cmd/sc_paraspacedecrease", "Decrease Paragraph Spacing",
         lambda w: changed("space", -6), toggle=False)
    row2.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 4)
    ibtn("cmd/sc_decrementindent", "Decrease Indent", lambda w: changed("indent", -635),
         toggle=False)
    ibtn("cmd/sc_incrementindent", "Increase Indent", lambda w: changed("indent", 635),
         toggle=False)
    d.add(row2)

    preview = Gtk.DrawingArea()
    preview.set_size_request(520, 150)
    preview.connect("draw", lambda a, cr: _draw_preview(a, cr, proxy, cur_fam()))
    fr = Gtk.Frame()
    fr.add(preview)
    d.add(fr)
    desc = Gtk.Label(xalign=0)
    desc.set_line_wrap(True)
    desc.set_max_width_chars(80)
    desc.get_style_context().add_class("dim-label")
    d.add(desc)

    opts = Gtk.Box(spacing=16)
    add_gal = Gtk.CheckButton.new_with_mnemonic("_Add to the Styles gallery")
    add_gal.set_active(in_gallery(m, name) if name else True)
    auto = Gtk.CheckButton.new_with_mnemonic("A_utomatically update")
    auto.set_active(auto0)
    opts.pack_start(add_gal, False, False, 0)
    opts.pack_start(auto, False, False, 0)
    d.add(opts)
    only = Gtk.RadioButton.new_with_mnemonic(None, "Only in this _document")
    newdocs = Gtk.RadioButton.new_with_mnemonic_from_widget(
        only, "New documents based on this _template")
    rb = Gtk.Box(spacing=16)
    rb.pack_start(only, False, False, 0)
    rb.pack_start(newdocs, False, False, 0)
    d.add(rb)

    def cur_fam():
        return "CharacterStyles" if kind.get_active() == 2 else "ParagraphStyles"

    def sync():
        """Show the proxy's values in the toolbar."""
        state["busy"] = True
        try:
            font.get_child().set_text(proxy.CharFontName or "")
            size.get_child().set_text("%g" % (proxy.CharHeight or 11))
            bold.set_active((proxy.CharWeight or 100) >= 150)
            ital.set_active(getattr(proxy.CharPosture, "value", "NONE") != "NONE")
            und.set_active(bool(proxy.CharUnderline))
            color.color = proxy.CharColor if proxy.CharColor is not None else -1
            color.queue_draw()
            para = cur_fam() == "ParagraphStyles"
            row2.set_sensitive(para)
            follow.set_sensitive(para)
            auto.set_sensitive(para)
            if para:
                for v, b in align_btns.items():
                    b.set_active(proxy.ParaAdjust == v)
                ls = proxy.ParaLineSpacing
                for v, b in space_btns.items():
                    b.set_active(ls.Mode == 0 and ls.Height == v)
        except Exception as e:
            print("modify style sync:", e)
        finally:
            state["busy"] = False
        desc.set_text(describe(proxy, cur_fam(), based.get_active_text()
                               if based.get_active_text() != "(no style)" else "",
                               follow.get_active_text(), add_gal.get_active(),
                               auto.get_active()))
        preview.queue_draw()

    def changed(what, v=None):
        if state["busy"]:
            return
        try:
            if what == "font":
                t = combo_text(font).strip()
                if t:
                    for p in ("CharFontName", "CharFontNameAsian", "CharFontNameComplex"):
                        setattr(proxy, p, t)
            elif what == "size":
                try:
                    proxy.CharHeight = float(combo_text(size).replace(",", "."))
                except ValueError:
                    return
            elif what == "b":
                proxy.CharWeight = 150.0 if bold.get_active() else 100.0
            elif what == "i":
                proxy.CharPosture = bridge.enum("com.sun.star.awt.FontSlant",
                                                "ITALIC" if ital.get_active() else "NONE")
            elif what == "u":
                proxy.CharUnderline = 1 if und.get_active() else 0
            elif what == "color":
                proxy.CharColor = -1 if v is None or v < 0 else v
            elif what == "align":
                proxy.ParaAdjust = v
            elif what == "line":
                ls = proxy.ParaLineSpacing
                new = bridge.struct("com.sun.star.style.LineSpacing", Mode=0, Height=v)
                if not (ls.Mode == 0 and ls.Height == v):
                    proxy.ParaLineSpacing = new
            elif what == "space":
                for p in ("ParaTopMargin", "ParaBottomMargin"):
                    pt = docapi.to_pt(getattr(proxy, p)) + v
                    if p == "ParaTopMargin" or v > 0 or pt >= 0:
                        setattr(proxy, p, docapi.pt(max(0, pt)))
            elif what == "indent":
                proxy.ParaLeftMargin = max(0, (proxy.ParaLeftMargin or 0) + v)
        except Exception as e:
            print("modify style:", e)
        sync()
    font.connect("changed", lambda *_: changed("font"))
    size.connect("changed", lambda *_: changed("size"))
    bold.connect("toggled", lambda *_: changed("b"))
    ital.connect("toggled", lambda *_: changed("i"))
    und.connect("toggled", lambda *_: changed("u"))
    for w in (based, follow, kind):
        w.connect("changed", lambda *_: sync())
    for w in (add_gal, auto):
        w.connect("toggled", lambda *_: sync())

    # ---- Format menu
    fmt = Gtk.MenuButton(label="F_ormat", use_underline=True)
    fmt.set_direction(Gtk.ArrowType.UP)

    def sub(fn):
        def go():
            win.dialogs._style_target = proxy
            try:
                fn()
            finally:
                win.dialogs._style_target = None
            sync()
        return go
    menu = Gtk.Menu()
    for label, cb in (("_Font...", sub(win.dialogs.font_dialog)),
                      ("_Paragraph...", sub(win.dialogs.paragraph_dialog)),
                      ("_Tabs...", sub(win.dialogs.tabs_dialog)),
                      ("_Border...", lambda: (border_dialog(d, proxy), sync())),
                      ("_Language...", lambda: (language_dialog(d, proxy), sync())),
                      ("_Numbering...", lambda: (numbering_dialog(d, m, proxy), sync())),
                      ("Shortcut _key...", lambda: shortcut_dialog(d, win,
                                                                   name_e.get_text().strip())),
                      ("Te_xt Effects...", lambda: (effects_dialog(d, proxy), sync()))):
        it = Gtk.MenuItem.new_with_mnemonic(label)
        it.connect("activate", lambda _i, cb=cb: cb())
        menu.append(it)
    menu.show_all()
    fmt.set_popup(menu)
    area = d.get_action_area()
    area.pack_start(fmt, False, False, 0)
    area.reorder_child(fmt, 0)
    try:
        area.set_child_secondary(fmt, True)
    except Exception:
        pass
    sync()
    r = d.ask()
    new_name = name_e.get_text().strip()
    if r != Gtk.ResponseType.OK or not new_name:
        d.done()
        return
    target_fam = cur_fam()
    based_v = based.get_active_text()
    follow_v = follow.get_active_text()
    gal = add_gal.get_active()
    autoupd = auto.get_active()
    template = newdocs.get_active()
    d.done()

    um = m.getUndoManager()
    um.enterUndoContext("Modify Style" if name else "New Style")
    try:
        if st is None:
            if fams.getByName(target_fam).hasByName(engine_style(new_name)):
                win.dialogs.message("A style with that name already exists.")
                return
            docapi.new_style(m, engine_style(new_name),
                             based_on=None if based_v in (None, "(no style)")
                             else engine_style(based_v),
                             follow=engine_style(follow_v or new_name)
                             if target_fam == "ParagraphStyles" else None,
                             family=target_fam, from_selection=True)
            st = fams.getByName(target_fam).getByName(engine_style(new_name))
        else:
            if new_name != name and st.isUserDefined():
                try:
                    st.setName(new_name)
                except Exception as e:
                    print("rename:", e)
            if based_v and based_v != (parent or "(no style)"):
                try:
                    st.ParentStyle = "" if based_v == "(no style)" else engine_style(based_v)
                except Exception as e:
                    print("based on:", e)
            if target_fam == "ParagraphStyles" and follow_v and follow_v != follow0:
                try:
                    st.FollowStyle = engine_style(follow_v)
                except Exception as e:
                    print("follow:", e)
        for k, v in proxy.pending.items():
            if target_fam == "CharacterStyles" and k.startswith("Para"):
                continue
            try:
                setattr(st, k, v)
            except Exception as e:
                print("style prop", k, e)
        if target_fam == "ParagraphStyles":
            try:
                st.IsAutoUpdate = autoupd
            except Exception:
                pass
    finally:
        um.leaveUndoContext()
    names = gallery_names(m)
    if name and name in names and new_name != name:
        names[names.index(name)] = new_name
    if gal and new_name not in names:
        names.append(new_name)
    elif not gal and new_name in names:
        names.remove(new_name)
    if names != gallery_names(m):
        set_gallery(m, names)
    if template:
        try:
            win.app.remember_style(new_name, target_fam, dict(proxy.pending))
        except Exception as e:
            print("template:", e)
    win.refresh_styles()


def _unique_name(m):
    fam = docapi.para_styles(m)
    i = 1
    while fam.hasByName("Style%d" % i):
        i += 1
    return "Style%d" % i


# ------------------------------------------------------------ Format sub-dialogs
def border_dialog(parent, p):
    d = FDialog(parent, "Borders and Shading")
    setting = combo(["None", "Box", "Bottom", "Top", "Top and bottom"], 0)
    try:
        sides = [s for s, prop in (("top", "TopBorder"), ("bottom", "BottomBorder"),
                                   ("left", "LeftBorder"), ("right", "RightBorder"))
                 if getattr(p, prop).OuterLineWidth > 0]
    except Exception:
        sides = []
    if len(sides) == 4:
        setting.set_active(1)
    elif sides == ["bottom"]:
        setting.set_active(2)
    elif sides == ["top"]:
        setting.set_active(3)
    elif sorted(sides) == ["bottom", "top"]:
        setting.set_active(4)
    widths = [0.25, 0.5, 0.75, 1.0, 1.5, 2.25, 3.0, 4.5, 6.0]
    width = combo(["%g pt" % w for w in widths], 1)
    col = color_button(0)
    shade = color_button(p.ParaBackColor if (p.ParaBackColor or -1) >= 0 else -1,
                         auto_label="No Color")
    d.add(grid([["Setting:", setting], ["Width:", width], ["Color:", col],
                ["Shading fill:", shade]]))
    if d.ask() == Gtk.ResponseType.OK:
        chosen = {0: set(), 1: {"top", "bottom", "left", "right"}, 2: {"bottom"},
                  3: {"top"}, 4: {"top", "bottom"}}[setting.get_active()]
        w = widths[width.get_active()]
        c = col.color if col.color is not None and col.color >= 0 else 0
        line = bridge.struct("com.sun.star.table.BorderLine2", Color=c,
                             OuterLineWidth=int(w * 35.28), LineWidth=int(w * 35.28))
        empty = bridge.struct("com.sun.star.table.BorderLine2")
        for side, prop in (("top", "TopBorder"), ("bottom", "BottomBorder"),
                           ("left", "LeftBorder"), ("right", "RightBorder")):
            setattr(p, prop, line if side in chosen else empty)
            setattr(p, prop + "Distance", docapi.pt(1) if chosen else 0)
        if shade.color is None or shade.color < 0:
            p.ParaBackColor = -1
            p.ParaBackTransparent = True
        else:
            p.ParaBackColor = shade.color
            p.ParaBackTransparent = False
    d.done()


def language_dialog(parent, p):
    d = FDialog(parent, "Language")
    names = [n for n, _l, _c in docapi.LANGUAGES]
    cur = 0
    try:
        loc = p.CharLocale
        for i, (_n, lang, country) in enumerate(docapi.LANGUAGES):
            if lang == loc.Language and country == loc.Country:
                cur = i
    except Exception:
        pass
    c = combo(names, cur)
    nocheck = Gtk.CheckButton(label="Do not check spelling or grammar")
    try:
        nocheck.set_active(p.CharLocale.Language == "zxx")
    except Exception:
        pass
    d.add(Gtk.Label(label="Mark selected text as:", xalign=0))
    d.add(c)
    d.add(nocheck)
    if d.ask() == Gtk.ResponseType.OK:
        if nocheck.get_active():
            p.CharLocale = docapi.locale("zxx", "")
        else:
            _n, lang, country = docapi.LANGUAGES[c.get_active()]
            p.CharLocale = docapi.locale(lang, country)
    d.done()


def numbering_dialog(parent, m, p):
    d = FDialog(parent, "Numbering and Bullets")
    fam = m.getStyleFamilies().getByName("NumberingStyles")
    names = []
    for n in fam.getElementNames():
        try:
            names.append((fam.getByName(n).DisplayName, n))
        except Exception:
            names.append((n, n))
    names.sort(key=lambda t: t[0].lower())
    labels = ["None"] + [t[0] for t in names]
    cur = 0
    try:
        current = p.NumberingStyleName
        for i, (_disp, n) in enumerate(names):
            if n == current:
                cur = i + 1
    except Exception:
        pass
    c = combo(labels, cur)
    d.add(Gtk.Label(label="List style:", xalign=0))
    d.add(c)
    if d.ask() == Gtk.ResponseType.OK:
        i = c.get_active()
        p.NumberingStyleName = "" if i <= 0 else names[i - 1][1]
    d.done()


def effects_dialog(parent, p):
    """Format Text Effects: text fill, text outline and effects."""
    from .widgets import color_button
    d = FDialog(parent, "Format Text Effects")
    nb = Gtk.Notebook()
    d.add(nb)
    # ---- text fill & outline
    fo = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    fo.set_border_width(10)
    fo.pack_start(heading("Text Fill"), False, False, 0)
    cur_col = getattr(p, "CharColor", -1)
    cur_tr = 0
    try:
        cur_tr = int(p.CharTransparence or 0)
    except Exception:
        pass
    nofill = Gtk.RadioButton.new_with_mnemonic(None, "_No fill")
    solid = Gtk.RadioButton.new_with_mnemonic_from_widget(nofill, "_Solid fill")
    solid.set_active(True)
    if cur_tr >= 100:
        nofill.set_active(True)
    fo.pack_start(nofill, False, False, 0)
    fo.pack_start(solid, False, False, 0)
    col = color_button(cur_col)
    tr = Gtk.SpinButton.new_with_range(0, 100, 1)
    tr.set_value(cur_tr if cur_tr < 100 else 0)
    fg = grid([["_Color", col], ["_Transparency", tr, Gtk.Label(label="%")]])
    fg.set_margin_start(20)
    fo.pack_start(fg, False, False, 0)
    solid.connect("toggled", lambda b: fg.set_sensitive(b.get_active()))
    fo.pack_start(heading("Text Outline"), False, False, 0)
    noline = Gtk.RadioButton.new_with_mnemonic(None, "No _line")
    solidline = Gtk.RadioButton.new_with_mnemonic_from_widget(noline, "S_olid line")
    try:
        (solidline if p.CharContoured else noline).set_active(True)
    except Exception:
        pass
    fo.pack_start(noline, False, False, 0)
    fo.pack_start(solidline, False, False, 0)
    nb.append_page(fo, Gtk.Label(label="Text Fill & Outline"))
    # ---- effects
    ef = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    ef.set_border_width(10)
    ef.pack_start(heading("Shadow"), False, False, 0)
    shadow = Gtk.CheckButton.new_with_mnemonic("_Shadow")
    try:
        shadow.set_active(bool(p.CharShadowed))
    except Exception:
        pass
    ef.pack_start(shadow, False, False, 0)
    ef.pack_start(heading("3-D Format"), False, False, 0)
    relief = combo(["None", "Emboss", "Engrave"], 0)
    try:
        relief.set_active(int(p.CharRelief or 0))
    except Exception:
        pass
    ef.pack_start(grid([["_Bevel:", relief]]), False, False, 0)
    nb.append_page(ef, Gtk.Label(label="Text Effects"))
    d.show_all()
    if d.ask() == Gtk.ResponseType.OK:
        try:
            if nofill.get_active():
                p.CharTransparence = 100
            else:
                if col.color is not None:
                    p.CharColor = col.color
                p.CharTransparence = int(tr.get_value())
        except Exception as e:
            print("text fill:", e)
        p.CharContoured = solidline.get_active()
        p.CharShadowed = shadow.get_active()
        p.CharRelief = relief.get_active()
    d.done()


def shortcut_dialog(parent, win, name):
    """Assign a keyboard shortcut that applies the style."""
    from gi.repository import Gdk
    d = FDialog(parent, "Customize Keyboard")
    d.add(Gtk.Label(label="Commands: %s" % name, xalign=0))
    keys = win.app.settings.get("style_keys") or {}
    current = [k for k, v in keys.items() if v == name]
    cur_l = Gtk.Label(label="Current keys: " + (", ".join(_pretty(k) for k in current)
                                                 or "(none)"), xalign=0)
    d.add(cur_l)
    e = Gtk.Entry()
    e.set_placeholder_text("Press new shortcut key")
    spec = {"v": None}

    def key(w, ev):
        name_ = (Gdk.keyval_name(Gdk.keyval_to_lower(ev.keyval)) or "").lower()
        if name_ in ("control_l", "control_r", "shift_l", "shift_r", "alt_l", "alt_r",
                     "tab", "iso_left_tab"):
            return False
        mods = []
        if ev.state & Gdk.ModifierType.CONTROL_MASK:
            mods.append("ctrl")
        if ev.state & Gdk.ModifierType.MOD1_MASK:
            mods.append("alt")
        if ev.state & Gdk.ModifierType.SHIFT_MASK:
            mods.append("shift")
        if not mods:
            return True
        spec["v"] = "+".join(mods + [name_])
        e.set_text(_pretty(spec["v"]))
        from .keys import BINDINGS
        taken = [a for s, a in BINDINGS if s == spec["v"]]
        warn.set_text("Currently assigned to: %s" % taken[0] if taken else
                      "Currently assigned to: [unassigned]")
        return True
    e.connect("key-press-event", key)
    warn = Gtk.Label(xalign=0)
    d.add(e)
    d.add(warn)
    remove = Gtk.CheckButton(label="Remove current keys")
    if current:
        d.add(remove)
    if d.ask() == Gtk.ResponseType.OK:
        keys = dict(keys)
        if remove.get_active():
            for k in current:
                keys.pop(k, None)
        if spec["v"]:
            keys[spec["v"]] = name
        win.app.settings["style_keys"] = keys
        try:
            win.app.save_settings()
        except OSError:
            pass
        for w in win.app.windows:
            w.keymap.set_style_keys(keys)
    d.done()


def _pretty(spec):
    return "+".join(p.capitalize() if len(p) > 1 else p.upper() for p in spec.split("+"))
