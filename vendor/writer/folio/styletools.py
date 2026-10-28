"""Styles pane extras: the Style Inspector and the Manage Styles dialog."""
import html

from gi.repository import GLib, Gtk, Pango

from . import docapi
from .panes import Pane
from .widgets import FDialog

# (property, label, formatter) checked for direct formatting
PARA_PROPS = [
    ("ParaAdjust", "Alignment", lambda v: {0: "Left", 1: "Right", 2: "Justified", 3: "Centered"}
     .get(int(v), str(v))),
    ("ParaLeftMargin", "Indent: Left", lambda v: _len(v)),
    ("ParaRightMargin", "Indent: Right", lambda v: _len(v)),
    ("ParaFirstLineIndent", "First line", lambda v: _len(v) if v >= 0 else "Hanging: " +
     _len(-v)),
    ("ParaTopMargin", "Space Before", lambda v: "%g pt" % round(docapi.to_pt(v), 1)),
    ("ParaBottomMargin", "Space After", lambda v: "%g pt" % round(docapi.to_pt(v), 1)),
    ("ParaLineSpacing", "Line spacing", lambda v: _spacing(v)),
    ("ParaBackColor", "Shading", lambda v: "#%06X" % v if v >= 0 else "No Color"),
    ("ParaKeepTogether", "Keep lines together", None),
    ("ParaSplit", "Don't split", None),
    ("ParaOrphans", "Widow/Orphan control", None),
]
CHAR_PROPS = [
    ("CharFontName", "Font", lambda v: v),
    ("CharHeight", "Size", lambda v: "%g pt" % v),
    ("CharWeight", "Bold", lambda v: "Bold" if v >= 150 else "Not Bold"),
    ("CharPosture", "Italic", lambda v: "Italic" if str(getattr(v, "value", v)) != "NONE"
     else "Not Italic"),
    ("CharUnderline", "Underline", lambda v: "Underline" if v else "No underline"),
    ("CharStrikeout", "Strikethrough", lambda v: "Strikethrough" if v else "No strikethrough"),
    ("CharColor", "Font color", lambda v: "#%06X" % v if v >= 0 else "Automatic"),
    ("CharBackColor", "Highlight", lambda v: "#%06X" % v if v >= 0 else "No Color"),
    ("CharEscapement", "Position", lambda v: "Superscript" if v > 0 else
     ("Subscript" if v < 0 else "Normal")),
    ("CharCaseMap", "Case", lambda v: {1: "All caps", 2: "Lowercase", 3: "Title",
                                       4: "Small caps"}.get(v, "Normal")),
    ("CharKerning", "Spacing", lambda v: "Expanded" if v > 0 else "Condensed"),
]


def _len(v):
    from .widgets import fmt_len
    try:
        return fmt_len(v)
    except Exception:
        return "%.2f cm" % (v / 1000.0)


def _spacing(v):
    try:
        if v.Mode == 0:
            return {100: "Single", 150: "1.5 lines", 200: "Double"}.get(
                v.Height, "Multiple %g li" % (v.Height / 100.0))
        if v.Mode == 3:
            return "Exactly %g pt" % round(docapi.to_pt(v.Height), 1)
        return "At least %g pt" % round(docapi.to_pt(v.Height), 1)
    except Exception:
        return ""


def _same(a, b):
    if hasattr(a, "Mode") and hasattr(a, "Height"):
        return (a.Mode, a.Height) == (b.Mode, b.Height)
    if isinstance(a, float) or isinstance(b, float):
        try:
            return abs(float(a) - float(b)) < 0.01
        except (TypeError, ValueError):
            return False
    return a == b


def direct_formatting(m):
    """([paragraph descriptions], [text descriptions]) for formatting applied
    on top of the styles at the cursor (values that differ from the styles)."""
    import uno
    default = uno.Enum("com.sun.star.beans.PropertyState", "DEFAULT_VALUE")
    rc = docapi.read_cursor(m)
    try:
        vc = rc.getText().createTextCursorByRange(rc.getStart())
        if not rc.isCollapsed():
            vc.goRight(1, True)        # the first selected character
    except Exception:
        vc = rc
    try:
        pst = docapi.para_styles(m).getByName(vc.ParaStyleName)
    except Exception:
        return [], []
    cst = None
    try:
        if vc.CharStyleName:
            cst = docapi.char_styles(m).getByName(vc.CharStyleName)
    except Exception:
        cst = None
    out = ([], [])
    for k, props in enumerate((PARA_PROPS, CHAR_PROPS)):
        for prop, label, fmt in props:
            try:
                v = getattr(vc, prop)
                base = getattr(pst, prop)
                if k == 1 and cst is not None:
                    try:
                        if cst.getPropertyState(prop) != default:
                            base = getattr(cst, prop)
                    except Exception:
                        pass
            except Exception:
                continue
            if v is None or _same(v, base):
                continue
            plain = label in ("Bold", "Italic", "Underline", "Strikethrough", "Font", "Size",
                              "Position", "Case")
            try:
                out[k].append(label if fmt is None else (fmt(v) if plain else
                                                         "%s: %s" % (label, fmt(v))))
            except Exception:
                pass
    return out


class StyleInspector(Pane):
    TITLE = "Style Inspector"
    WIDTH = 260

    def __init__(self, win):
        Pane.__init__(self, win)
        self._timer = None
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=6)
        self.para_style, self.para_plus = self._section(box, "Paragraph formatting",
                                                         self.reset_para_style,
                                                         self.clear_para)
        self.char_style, self.char_plus = self._section(box, "Text level formatting",
                                                         self.reset_char_style,
                                                         self.clear_char)
        box.pack_start(Gtk.Separator(), False, False, 4)
        clear = Gtk.Button(label="Clear All")
        clear.set_halign(Gtk.Align.START)
        clear.connect("clicked", lambda *_: self.clear_all())
        box.pack_start(clear, False, False, 0)
        self.pack_start(box, True, True, 0)
        win.engine.connect("state-changed", self._state)

    def _section(self, box, title, reset, clear):
        h = Gtk.Label(xalign=0)
        h.set_markup("<b>%s</b>" % title)
        box.pack_start(h, False, False, 0)
        row = Gtk.Box(spacing=4)
        style = Gtk.Entry()
        style.set_editable(False)
        style.set_can_focus(False)
        row.pack_start(style, True, True, 0)
        b = self._icon_button("cmd/sc_resetattributes", "Reset to Normal", reset)
        row.pack_start(b, False, False, 0)
        box.pack_start(row, False, False, 0)
        row2 = Gtk.Box(spacing=4)
        plus = Gtk.Label(xalign=0, yalign=0)
        plus.set_line_wrap(True)
        plus.set_max_width_chars(30)
        plus.set_ellipsize(Pango.EllipsizeMode.NONE)
        frame = Gtk.Frame()
        frame.add(plus)
        plus.set_margin_start(4)
        plus.set_margin_top(2)
        plus.set_margin_bottom(2)
        row2.pack_start(frame, True, True, 0)
        row2.pack_start(self._icon_button("cmd/sc_resetattributes", "Clear Formatting", clear),
                        False, False, 0)
        box.pack_start(row2, False, False, 0)
        return style, plus

    def _icon_button(self, icon, tip, cb):
        from . import icons
        b = Gtk.Button()
        b.add(icons.image(icon, 16))
        b.set_tooltip_text(tip)
        b.set_relief(Gtk.ReliefStyle.NONE)
        b.connect("clicked", lambda *_: (cb(), self.schedule(150)))
        return b

    def _state(self, eng, key, value):
        if self.get_mapped():
            self.schedule()

    def schedule(self, delay=250):
        if self._timer:
            GLib.source_remove(self._timer)
        self._timer = GLib.timeout_add(delay, self.refresh)

    def on_shown(self):
        self.refresh()

    def refresh(self):
        self._timer = None
        m = self.model
        if m is None:
            return False
        from .actions import word_style
        try:
            vc = docapi.read_cursor(m)
            ps = word_style(docapi.para_styles(m).getByName(vc.ParaStyleName).DisplayName)
            cs = vc.CharStyleName or ""
            cs = word_style(docapi.char_styles(m).getByName(cs).DisplayName) if cs else \
                "Default Paragraph Font"
            para, text = direct_formatting(m)
        except Exception as e:
            print("inspector:", e)
            return False
        self.para_style.set_text(ps)
        self.char_style.set_text(cs)
        self.para_plus.set_markup("Plus: " + html.escape(", ".join(para) if para else "<none>"))
        self.char_plus.set_markup("Plus: " + html.escape(", ".join(text) if text else "<none>"))
        return False

    def reset_para_style(self):
        self.win.actions.apply_style("Normal")

    def clear_para(self):
        if self.model is not None:
            reset_para_direct(self.model)

    def reset_char_style(self):
        m = self.model
        if m is not None:
            vc = docapi.view_cursor(m)
            try:
                vc.setPropertyToDefault("CharStyleName")
            except Exception:
                pass

    def clear_char(self):
        m = self.model
        if m is not None:
            reset_char_direct(m)

    def clear_all(self):
        self.win.engine.command(".uno:ResetAttributes")
        self.reset_char_style()


def reset_para_direct(m):
    vc = docapi.view_cursor(m)
    for prop, _l, _f in PARA_PROPS:
        try:
            vc.setPropertyToDefault(prop)
        except Exception:
            pass


def reset_char_direct(m):
    vc = docapi.view_cursor(m)
    for prop, _l, _f in CHAR_PROPS:
        try:
            vc.setPropertyToDefault(prop)
        except Exception:
            pass


# ------------------------------------------------------------ manage styles
def manage_styles(win, page=0):
    from .actions import word_style, engine_style
    m = win.engine.model
    if m is None:
        return
    d = FDialog(win, "Manage Styles")
    nb = Gtk.Notebook()
    # --- Edit
    edit = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=8)
    sort = Gtk.ComboBoxText()
    for t in ("As Recommended", "Alphabetical", "Based On", "By type"):
        sort.append_text(t)
    sort.set_active(0)
    row = Gtk.Box(spacing=6)
    row.pack_start(Gtk.Label(label="Sort order:"), False, False, 0)
    row.pack_start(sort, False, False, 0)
    used = Gtk.CheckButton(label="Show recommended styles only")
    row.pack_start(used, False, False, 12)
    edit.pack_start(row, False, False, 0)
    store = Gtk.ListStore(str, str, str, str)     # word name, engine name, family, based on
    tv = Gtk.TreeView(model=store)
    tv.set_headers_visible(False)
    tv.append_column(Gtk.TreeViewColumn("", Gtk.CellRendererText(), text=0))
    sw = Gtk.ScrolledWindow()
    sw.set_size_request(440, 220)
    sw.add(tv)
    edit.pack_start(sw, True, True, 0)
    preview = Gtk.Label(xalign=0)
    preview.set_line_wrap(True)
    preview.set_max_width_chars(60)
    pf = Gtk.Frame(label="Preview of " + "")
    pf.add(preview)
    edit.pack_start(pf, False, False, 0)
    bb = Gtk.Box(spacing=6)
    b_mod = Gtk.Button(label="Modify...")
    b_del = Gtk.Button(label="Delete")
    b_new = Gtk.Button(label="New Style...")
    for b in (b_mod, b_del):
        bb.pack_start(b, False, False, 0)
    bb.pack_end(b_new, False, False, 0)
    edit.pack_start(bb, False, False, 0)
    from .panes import PREFERRED

    def fill():
        store.clear()
        rows = []
        for fam in ("ParagraphStyles", "CharacterStyles"):
            for n, disp in docapi.style_names(m, fam):
                st = m.getStyleFamilies().getByName(fam).getByName(n)
                wn = word_style(disp)
                if used.get_active() and wn not in PREFERRED and not st.isUserDefined():
                    continue
                if not (st.isInUse() or st.isUserDefined() or wn in PREFERRED):
                    continue
                parent = ""
                try:
                    parent = word_style(st.ParentStyle) if st.ParentStyle else ""
                except Exception:
                    pass
                rows.append((wn, n, fam, parent))
        mode = sort.get_active()
        order = {n: i for i, n in enumerate(PREFERRED)}
        if mode == 0:
            rows.sort(key=lambda r: (order.get(r[0], 999), r[0].lower()))
        elif mode == 1:
            rows.sort(key=lambda r: r[0].lower())
        elif mode == 2:
            rows.sort(key=lambda r: (r[3].lower(), r[0].lower()))
        else:
            rows.sort(key=lambda r: (r[2], r[0].lower()))
        seen = set()
        for r in rows:
            if (r[0], r[2]) in seen:
                continue
            seen.add((r[0], r[2]))
            store.append(list(r))
        if len(store):
            tv.get_selection().select_path(Gtk.TreePath(0))

    def current():
        model, it = tv.get_selection().get_selected()
        return tuple(model[it]) if it else None

    def show_preview(*_):
        cur = current()
        if not cur:
            return
        wn, n, fam, parent = cur
        si = docapi.style_info(m, n, fam) or {}
        pf.set_label("Preview of %s" % wn)
        size = si.get("CharHeight") or 11
        font = si.get("CharFontName") or "Sans"
        bold = " weight='bold'" if si.get("CharWeight", 100) >= 150 else ""
        desc = ["Font: %s, %g pt" % (font, size)]
        if parent:
            desc.append("Based on: %s" % parent)
        preview.set_markup("<span font_family='%s' size='%dpt'%s>AaBbCcEeGgHhIiJj</span>\n"
                           "<small>%s</small>" % (html.escape(font), min(20, size), bold,
                                                  html.escape(", ".join(desc))))
        try:
            user = m.getStyleFamilies().getByName(fam).getByName(n).isUserDefined()
        except Exception:
            user = False
        b_del.set_sensitive(user)

    tv.get_selection().connect("changed", show_preview)
    sort.connect("changed", lambda *_: fill())
    used.connect("toggled", lambda *_: fill())

    def modify(*_):
        cur = current()
        if cur:
            win.dialogs.modify_style(cur[0])
            fill()

    def delete(*_):
        cur = current()
        if not cur:
            return
        if win.dialogs.confirm("Do you want to delete style %s from the document?" % cur[0],
                               yes="Yes", no="No"):
            try:
                m.getStyleFamilies().getByName(cur[2]).removeByName(cur[1])
            except Exception as e:
                win.dialogs.message("The style couldn't be deleted: %s" % e)
            fill()

    def new(*_):
        win.dialogs.new_style()
        fill()
    b_mod.connect("clicked", modify)
    b_del.connect("clicked", delete)
    b_new.connect("clicked", new)
    tv.connect("row-activated", modify)
    fill()
    nb.append_page(edit, Gtk.Label(label="Edit"))

    # --- Set Defaults
    st = docapi.para_styles(m).getByName("Standard")
    defaults = Gtk.Grid(row_spacing=8, column_spacing=10, margin=10)
    hdr = Gtk.Label(xalign=0)
    hdr.set_markup("<b>Font</b>")
    defaults.attach(hdr, 0, 0, 4, 1)
    font = Gtk.ComboBoxText.new_with_entry()
    for f in win.engine.fonts()[:400]:
        font.append_text(f)
    font.get_child().set_text(st.CharFontName)
    size = Gtk.SpinButton.new_with_range(1, 400, 0.5)
    size.set_value(st.CharHeight)
    defaults.attach(Gtk.Label(label="Font:", xalign=0), 0, 1, 1, 1)
    defaults.attach(font, 1, 1, 1, 1)
    defaults.attach(Gtk.Label(label="Size:", xalign=0), 2, 1, 1, 1)
    defaults.attach(size, 3, 1, 1, 1)
    hdr2 = Gtk.Label(xalign=0)
    hdr2.set_markup("<b>Paragraph Spacing</b>")
    defaults.attach(hdr2, 0, 2, 4, 1)
    before = Gtk.SpinButton.new_with_range(0, 1584, 1)
    before.set_value(round(docapi.to_pt(st.ParaTopMargin)))
    after = Gtk.SpinButton.new_with_range(0, 1584, 1)
    after.set_value(round(docapi.to_pt(st.ParaBottomMargin)))
    line = Gtk.ComboBoxText()
    lines = [("Single", 100), ("1.08", 108), ("1.15", 115), ("1.5 lines", 150),
             ("Double", 200)]
    for t, _v in lines:
        line.append_text(t)
    cur_h = st.ParaLineSpacing.Height if st.ParaLineSpacing.Mode == 0 else 100
    line.set_active(min(range(len(lines)), key=lambda i: abs(lines[i][1] - cur_h)))
    defaults.attach(Gtk.Label(label="Before:", xalign=0), 0, 3, 1, 1)
    defaults.attach(before, 1, 3, 1, 1)
    defaults.attach(Gtk.Label(label="After:", xalign=0), 2, 3, 1, 1)
    defaults.attach(after, 3, 3, 1, 1)
    defaults.attach(Gtk.Label(label="Line spacing:", xalign=0), 0, 4, 1, 1)
    defaults.attach(line, 1, 4, 1, 1)
    scope_doc = Gtk.RadioButton(label="Only in this document")
    scope_tpl = Gtk.RadioButton(label="New documents based on this template",
                                group=scope_doc)
    defaults.attach(scope_doc, 0, 5, 4, 1)
    defaults.attach(scope_tpl, 0, 6, 4, 1)
    nb.append_page(defaults, Gtk.Label(label="Set Defaults"))
    d.add(nb, expand=True)
    nb.show_all()
    nb.set_current_page(page)
    r = d.ask()
    if r == Gtk.ResponseType.OK and nb.get_current_page() == 1 or (
            r == Gtk.ResponseType.OK and _defaults_changed(st, font, size, before, after,
                                                           line, lines)):
        um = m.getUndoManager()
        um.enterUndoContext("Set Defaults")
        try:
            docapi.set_default_font(m, font.get_child().get_text().strip() or None,
                                    size.get_value())
            st.ParaTopMargin = docapi.pt(before.get_value())
            st.ParaBottomMargin = docapi.pt(after.get_value())
            ls = st.ParaLineSpacing
            ls.Mode, ls.Height = 0, lines[line.get_active()][1]
            st.ParaLineSpacing = ls
        finally:
            um.leaveUndoContext()
        if scope_tpl.get_active():
            try:
                win.app.set_default_font(font.get_child().get_text().strip(), size.get_value())
            except Exception as e:
                print("defaults:", e)
        win.design_changed()
    d.done()


def _defaults_changed(st, font, size, before, after, line, lines):
    try:
        return (font.get_child().get_text().strip() != st.CharFontName or
                abs(size.get_value() - st.CharHeight) > 0.01 or
                round(docapi.to_pt(st.ParaTopMargin)) != before.get_value() or
                round(docapi.to_pt(st.ParaBottomMargin)) != after.get_value() or
                lines[line.get_active()][1] != st.ParaLineSpacing.Height)
    except Exception:
        return False
