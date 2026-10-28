"""Font, Paragraph, Styles, Borders and Shading, Drop Cap, Sort dialogs."""
from gi.repository import GLib, Gtk, Pango, PangoCairo

from . import bridge, docapi
from .actions import CHAR_STYLES, engine_style, word_style
from .widgets import (FDialog, LengthSpin, PointSpin, Preview, color_button, combo,
                      combo_text, grid, heading, list_select, list_selected, listbox, rgb)

UNDERLINES = [("(none)", 0), ("Words only", -1), ("Single", 1), ("Double", 2),
              ("Thick", 12), ("Dotted", 3), ("Dash", 5), ("Dot-dash", 7),
              ("Dot-dot-dash", 8), ("Wave", 10), ("Double wave", 11)]
SIZES = ["8", "9", "10", "10.5", "11", "12", "14", "16", "18", "20", "22", "24", "26",
         "28", "36", "48", "72"]
STYLES = ["Regular", "Italic", "Bold", "Bold Italic"]
ALIGN = [("Left", 0), ("Centered", 3), ("Right", 1), ("Justified", 2)]
LINE_RULES = ["Single", "1.5 lines", "Double", "At least", "Exactly", "Multiple"]
SAMPLE = "The quick brown fox jumps over the lazy dog."


def _italic():
    return bridge.enum("com.sun.star.awt.FontSlant", "ITALIC")


def _upright():
    return bridge.enum("com.sun.star.awt.FontSlant", "NONE")


def _is_italic(v):
    return getattr(v, "value", str(v)) in ("ITALIC", "OBLIQUE")



# OpenType features (as the engine writes them after the font name: "Font:liga&onum")
# The engine shapes text with standard and contextual ligatures on unless told
# otherwise, so those are the "no features" state.
LIGATURES = [("None", ["liga=0", "clig=0"]), ("Standard Only", ["clig=0"]),
             ("Standard and Contextual", []),
             ("Historical and Discretionary", ["liga=0", "clig=0", "hlig", "dlig"]),
             ("All", ["hlig", "dlig"])]
NUMBER_SPACING = [("Default", []), ("Proportional", ["pnum"]), ("Tabular", ["tnum"])]
NUMBER_FORMS = [("Default", []), ("Lining", ["lnum"]), ("Old-style", ["onum"])]


def _parse_features(text):
    return [f for f in (text or "").split("&") if f]


def _known_feature(f):
    tag = f.split("=")[0]
    return tag in ("liga", "clig", "hlig", "dlig", "pnum", "tnum", "lnum", "onum", "calt") or \
        (tag.startswith("ss") and tag[2:].isdigit())


def _ligature_index(feats):
    on = set(f for f in feats if f.split("=")[0] in ("liga", "clig", "hlig", "dlig"))
    for i, (_n, fs) in enumerate(LIGATURES):
        if set(fs) == on:
            return i
    return 2


def _pick(feats, table):
    for i, (_n, fs) in enumerate(table):
        if fs and all(f in feats for f in fs):
            return i
    return 0

class TextDialogs:
    # =================================================================== Font
    _style_target = None

    def _cursor(self, m):
        """Where the Font / Paragraph / Tabs dialogs read and write: the
        selection, or a style being modified."""
        if self._style_target is not None:
            return self._style_target
        if getattr(self.win.engine, "native", False):
            from .native.uno_props import CursorProps
            return CursorProps(self.win.engine)
        return docapi.view_cursor(m)

    def font_dialog(self):
        m = self._model_or_warn()
        if m is None:
            return
        vc = self._cursor(m)
        sel_text = (vc.getString() or "").split("\n")[0][:60].strip()
        fonts = self.eng.fonts() or ["Carlito", "Caladea", "Liberation Sans",
                                     "Liberation Serif", "DejaVu Sans"]
        full_name = vc.CharFontName or ""
        base_name, _sep, feat_str = full_name.partition(":")
        feats = _parse_features(feat_str)
        cur = {
            "font": base_name, "size": vc.CharHeight or 11.0,
            "bold": (vc.CharWeight or 100) >= 150, "italic": _is_italic(vc.CharPosture),
            "color": vc.CharColor, "underline": vc.CharUnderline or 0,
            "word_mode": bool(vc.CharWordMode),
            "ucolor": vc.CharUnderlineColor if vc.CharUnderlineHasColor else -1,
            "strike": vc.CharStrikeout or 0, "esc": vc.CharEscapement or 0,
            "casemap": vc.CharCaseMap or 0, "hidden": bool(vc.CharHidden),
            "scale": vc.CharScaleWidth or 100, "kerning": vc.CharKerning or 0,
            "autokern": bool(vc.CharAutoKerning),
        }
        d = FDialog(self.win, "Font", buttons=(("OK", Gtk.ResponseType.OK),
                                                ("Cancel", Gtk.ResponseType.CANCEL)))
        nb = Gtk.Notebook()
        d.add(nb)

        # ---- Font tab
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        page.set_border_width(10)
        font_entry = Gtk.Entry(text=cur["font"])
        sw_f, tv_f, _ = listbox(fonts, height=110, width=220)
        style_entry = Gtk.Entry(text=STYLES[(2 if cur["bold"] else 0) + (1 if cur["italic"] else 0)])
        sw_s, tv_s, _ = listbox(STYLES, height=110, width=130)
        size_entry = Gtk.Entry(text=("%.1f" % cur["size"]).rstrip("0").rstrip("."))
        size_entry.set_width_chars(6)
        sw_z, tv_z, _ = listbox(SIZES, height=110, width=70)
        list_select(tv_f, cur["font"])
        list_select(tv_s, style_entry.get_text())
        list_select(tv_z, size_entry.get_text())

        def bind(tv, entry):
            def changed(sel):
                v = list_selected(tv)
                if v is not None and entry.get_text() != v:
                    entry.set_text(v)
            tv.get_selection().connect("changed", changed)
            entry.connect("changed", lambda e: (list_select(tv, e.get_text()), upd()))
        g = Gtk.Grid(column_spacing=10, row_spacing=4)
        g.attach(Gtk.Label(label="_Font:", xalign=0, use_underline=True), 0, 0, 1, 1)
        g.attach(Gtk.Label(label="Font st_yle:", xalign=0, use_underline=True), 1, 0, 1, 1)
        g.attach(Gtk.Label(label="_Size:", xalign=0, use_underline=True), 2, 0, 1, 1)
        g.attach(font_entry, 0, 1, 1, 1)
        g.attach(style_entry, 1, 1, 1, 1)
        g.attach(size_entry, 2, 1, 1, 1)
        g.attach(sw_f, 0, 2, 1, 1)
        g.attach(sw_s, 1, 2, 1, 1)
        g.attach(sw_z, 2, 2, 1, 1)
        page.pack_start(g, False, False, 0)

        color_btn = color_button(cur["color"] if cur["color"] is not None else -1,
                                 lambda c: upd())
        ul_names = [u[0] for u in UNDERLINES]
        ul_now = -1 if cur["word_mode"] and cur["underline"] else cur["underline"]
        ul_combo = combo(ul_names, next((i for i, u in enumerate(UNDERLINES) if u[1] == ul_now), 0))
        ul_combo.connect("changed", lambda *_: upd())
        ucolor_btn = color_button(cur["ucolor"], lambda c: upd())
        page.pack_start(grid([["Font _color:", "_Underline style:", "Underline color:"],
                              [color_btn, ul_combo, ucolor_btn]]), False, False, 0)

        page.pack_start(heading("Effects"), False, False, 0)
        chk = {}
        eff = Gtk.Grid(column_spacing=30, row_spacing=2)
        for i, (key, label) in enumerate((("strike", "Stri_kethrough"),
                                          ("dstrike", "Double strikethrough"),
                                          ("sup", "Su_perscript"), ("sub", "Su_bscript"),
                                          ("smallcaps", "S_mall caps"), ("caps", "_All caps"),
                                          ("hidden", "_Hidden"))):
            cb = Gtk.CheckButton.new_with_mnemonic(label)
            chk[key] = cb
            col = 0 if i < 4 else 1
            eff.attach(cb, col, i if i < 4 else i - 4, 1, 1)
        chk["strike"].set_active(cur["strike"] in (1, 3, 4, 5, 6))
        chk["dstrike"].set_active(cur["strike"] == 2)
        chk["sup"].set_active(cur["esc"] > 0)
        chk["sub"].set_active(cur["esc"] < 0)
        chk["smallcaps"].set_active(cur["casemap"] == 4)
        chk["caps"].set_active(cur["casemap"] == 1)
        chk["hidden"].set_active(cur["hidden"])

        def exclusive(a, b):
            def f(w):
                if w.get_active():
                    chk[b].set_active(False)
                upd()
            chk[a].connect("toggled", f)
        for a, b in (("strike", "dstrike"), ("dstrike", "strike"), ("sup", "sub"),
                     ("sub", "sup"), ("smallcaps", "caps"), ("caps", "smallcaps")):
            exclusive(a, b)
        chk["hidden"].connect("toggled", lambda *_: upd())
        page.pack_start(eff, False, False, 0)

        # ---- Advanced tab
        adv = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        adv.set_border_width(10)
        adv.pack_start(heading("Character Spacing"), False, False, 0)
        scale = combo(["200%", "150%", "100%", "90%", "80%", "66%", "50%", "33%"],
                      "%d%%" % cur["scale"], entry=True)
        spacing_kind = combo(["Normal", "Expanded", "Condensed"],
                             0 if cur["kerning"] == 0 else (1 if cur["kerning"] > 0 else 2))
        spacing_by = PointSpin(abs(docapi.to_pt(cur["kerning"])), 0, 1584, 0.1)
        spacing_by.set_digits(1)
        pos_kind = combo(["Normal", "Raised", "Lowered"],
                         0 if cur["esc"] == 0 or abs(cur["esc"]) in (33, 101) else
                         (1 if cur["esc"] > 0 else 2))
        pos_by = PointSpin(round(abs(cur["esc"]) * cur["size"] / 100.0, 1)
                           if abs(cur["esc"]) not in (33, 101) else 0, 0, 1584, 1)
        kern = Gtk.CheckButton.new_with_mnemonic("_Kerning for fonts:")
        kern.set_active(cur["autokern"])
        adv.pack_start(grid([["Sc_ale:", scale],
                             ["_Spacing:", spacing_kind, "By:", spacing_by],
                             ["_Position:", pos_kind, "By:", pos_by],
                             [kern, Gtk.Label(label="Points and above")]]), False, False, 0)
        for w in (spacing_kind, pos_kind):
            w.connect("changed", lambda *_: upd())
        adv.pack_start(heading("OpenType Features"), False, False, 0)
        lig = combo([n for n, _f in LIGATURES], _ligature_index(feats))
        nsp = combo([n for n, _f in NUMBER_SPACING], _pick(feats, NUMBER_SPACING))
        nfm = combo([n for n, _f in NUMBER_FORMS], _pick(feats, NUMBER_FORMS))
        sets = ["Default"] + ["%d" % i for i in range(1, 21)]
        ss_now = next((int(f[2:4]) for f in feats if f.startswith("ss") and f[2:4].isdigit()
                       and not f.endswith("=0")), 0)
        sset = combo(sets, ss_now)
        calt = Gtk.CheckButton.new_with_mnemonic("Use Con_textual Alternates")
        calt.set_active("calt=0" not in feats)      # on unless switched off
        adv.pack_start(grid([["_Ligatures:", lig], ["Number spac_ing:", nsp],
                             ["Number _forms:", nfm], ["Stylistic se_ts:", sset]]),
                       False, False, 0)
        adv.pack_start(calt, False, False, 0)

        nb.append_page(page, Gtk.Label(label="Font"))
        nb.append_page(adv, Gtk.Label(label="Advanced"))

        # ---- preview
        d.add(heading("Preview"))

        def draw(cr, w, h):
            name = font_entry.get_text() or "Sans"
            try:
                size = float(size_entry.get_text().replace(",", "."))
            except ValueError:
                size = 11
            st = style_entry.get_text()
            desc = Pango.FontDescription()
            desc.set_family(name)
            desc.set_size(int(min(size, 36) * Pango.SCALE * 1.2))
            if "Bold" in st:
                desc.set_weight(Pango.Weight.BOLD)
            if "Italic" in st:
                desc.set_style(Pango.Style.ITALIC)
            text = sel_text or font_entry.get_text() or SAMPLE
            if chk["caps"].get_active():
                text = text.upper()
            if chk["smallcaps"].get_active():
                desc.set_variant(Pango.Variant.SMALL_CAPS)
            layout = PangoCairo.create_layout(cr)
            layout.set_font_description(desc)
            attrs = Pango.AttrList()
            if chk["strike"].get_active() or chk["dstrike"].get_active():
                attrs.insert(Pango.attr_strikethrough_new(True))
            ul = UNDERLINES[ul_combo.get_active()][1] if ul_combo.get_active() >= 0 else 0
            if ul:
                attrs.insert(Pango.attr_underline_new(
                    Pango.Underline.DOUBLE if ul in (2, 11) else
                    Pango.Underline.ERROR if ul in (10, 11) else Pango.Underline.SINGLE))
            layout.set_attributes(attrs)
            layout.set_text(text, -1)
            tw, th = layout.get_pixel_size()
            c = color_btn.color if color_btn.color is not None and color_btn.color >= 0 else 0
            cr.set_source_rgb(*rgb(c))
            if chk["hidden"].get_active():
                cr.set_source_rgba(*rgb(c), 0.35)
            cr.move_to(max(4, (w - tw) / 2), (h - th) / 2)
            PangoCairo.show_layout(cr, layout)
        prev = Preview(draw, 420, 60)
        d.add(prev)
        note = Gtk.Label(label="", xalign=0)
        note.get_style_context().add_class("dim-label")
        d.add(note)

        def upd(*_):
            prev.queue_draw()
            avail = font_entry.get_text() in fonts
            note.set_text("" if avail or not font_entry.get_text() else
                          "This font isn't installed. A similar font will be used on screen "
                          "and when printing.")
        bind(tv_f, font_entry)
        bind(tv_s, style_entry)
        bind(tv_z, size_entry)
        set_def = Gtk.Button(label="Set As _Default", use_underline=True)
        set_def.set_no_show_all(self._style_target is not None)
        d.get_action_area().pack_start(set_def, False, False, 0)
        d.get_action_area().reorder_child(set_def, 0)
        fx = Gtk.Button(label="Text _Effects...", use_underline=True)
        d.get_action_area().pack_start(fx, False, False, 0)
        d.get_action_area().reorder_child(fx, 1)

        def text_effects(*_):
            from .stylemodify import effects_dialog
            um = m.getUndoManager()
            um.enterUndoContext("Text Effects")
            try:
                effects_dialog(d, self._cursor(m))
            finally:
                um.leaveUndoContext()
        fx.connect("clicked", text_effects)
        fx.show()
        defaults = []
        set_def.connect("clicked", lambda *_: (defaults.append(True),
                                               d.response(Gtk.ResponseType.OK)))
        r = d.ask()
        if r != Gtk.ResponseType.OK:
            d.done()
            return
        # ---- apply only what changed
        vc = self._cursor(m)
        name = font_entry.get_text().strip()
        try:
            size = float(size_entry.get_text().replace(",", "."))
        except ValueError:
            size = cur["size"]
        st = style_entry.get_text()
        if defaults:
            if not self.confirm("Do you want to set the default font to %s, %s pt?\n\n"
                                "This changes the Normal style of this document and of new "
                                "documents." % (name, ("%g" % size)), yes="OK"):
                d.done()
                return
            docapi.set_default_font(m, name, size)
            self.win.app.set_default_font(name, size)
            d.done()
            return
        new_feats = []
        new_feats += LIGATURES[max(0, lig.get_active())][1]
        new_feats += NUMBER_SPACING[max(0, nsp.get_active())][1]
        new_feats += NUMBER_FORMS[max(0, nfm.get_active())][1]
        if sset.get_active() > 0:
            new_feats.append("ss%02d" % sset.get_active())
        if not calt.get_active():
            new_feats.append("calt=0")
        keep = [f for f in feats if not _known_feature(f)]
        new_full = (name or cur["font"]) + (
            ":" + "&".join(keep + new_feats) if keep + new_feats else "")
        if name and (name != cur["font"] or new_full != full_name):
            name = new_full
            vc.CharFontName = name
            for p in ("CharFontNameAsian", "CharFontNameComplex"):
                try:
                    setattr(vc, p, name)
                except Exception:
                    pass
        if abs(size - cur["size"]) > 0.01:
            vc.CharHeight = size
        bold, ital = "Bold" in st, "Italic" in st
        if bold != cur["bold"]:
            vc.CharWeight = 150.0 if bold else 100.0
        if ital != cur["italic"]:
            vc.CharPosture = _italic() if ital else _upright()
        if color_btn.color != cur["color"]:
            vc.CharColor = -1 if color_btn.color is None else color_btn.color
        ul = UNDERLINES[ul_combo.get_active()][1]
        if ul != ul_now:
            vc.CharWordMode = ul == -1
            vc.CharUnderline = 1 if ul == -1 else ul
        if ucolor_btn.color != cur["ucolor"]:
            uc = ucolor_btn.color
            vc.CharUnderlineHasColor = uc is not None and uc >= 0
            if uc is not None and uc >= 0:
                vc.CharUnderlineColor = uc
        strike = 2 if chk["dstrike"].get_active() else (1 if chk["strike"].get_active() else 0)
        if strike != (cur["strike"] if cur["strike"] in (0, 1, 2) else 1):
            vc.CharStrikeout = strike
        casemap = 4 if chk["smallcaps"].get_active() else (1 if chk["caps"].get_active() else 0)
        if casemap != (cur["casemap"] if cur["casemap"] in (0, 1, 4) else 0):
            vc.CharCaseMap = casemap
        if chk["hidden"].get_active() != cur["hidden"]:
            vc.CharHidden = chk["hidden"].get_active()
        # position: superscript/subscript or raised/lowered by points
        sup, sub = chk["sup"].get_active(), chk["sub"].get_active()
        pk = pos_kind.get_active()
        if sup or sub:
            esc, esch = (33, 58) if sup else (-33, 58)
            if (cur["esc"] > 0) != sup or (cur["esc"] < 0) != sub:
                vc.CharEscapement, vc.CharEscapementHeight = esc, esch
        elif pk in (1, 2) and pos_by.points > 0:
            pct = int(round(pos_by.points / max(size, 1) * 100))
            vc.CharEscapement = pct if pk == 1 else -pct
            vc.CharEscapementHeight = 100
        elif cur["esc"] != 0:
            vc.CharEscapement, vc.CharEscapementHeight = 0, 100
        try:
            sc = int(combo_text(scale).replace("%", "").strip())
            if sc != cur["scale"]:
                vc.CharScaleWidth = max(1, min(600, sc))
        except ValueError:
            pass
        sk = spacing_kind.get_active()
        kv = docapi.pt(spacing_by.points)
        newk = 0 if sk == 0 else (kv if sk == 1 else -kv)
        if newk != cur["kerning"]:
            vc.CharKerning = newk
        if kern.get_active() != cur["autokern"]:
            vc.CharAutoKerning = kern.get_active()
        d.done()

    # ============================================================== Paragraph
    def paragraph_dialog(self, tab=0):
        m = self._model_or_warn()
        if m is None:
            return
        vc = self._cursor(m)
        ls = vc.ParaLineSpacing
        cur = {"align": vc.ParaAdjust, "left": vc.ParaLeftMargin, "right": vc.ParaRightMargin,
               "first": vc.ParaFirstLineIndent, "before": vc.ParaTopMargin,
               "after": vc.ParaBottomMargin, "mode": ls.Mode, "height": ls.Height,
               "context": bool(vc.ParaContextMargin), "outline": vc.OutlineLevel or 0,
               "widows": (vc.ParaWidows or 0) > 0, "keepnext": bool(vc.ParaKeepTogether),
               "split": bool(vc.ParaSplit),
               "pagebreak": getattr(vc.BreakType, "value", "") == "PAGE_BEFORE",
               "linenum": bool(vc.ParaLineNumberCount), "hyph": bool(vc.ParaIsHyphenation)}
        d = FDialog(self.win, "Paragraph")
        nb = Gtk.Notebook()
        d.add(nb)
        p1 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        p1.set_border_width(10)
        p1.pack_start(heading("General"), False, False, 0)
        align = combo([a[0] for a in ALIGN],
                      next((i for i, a in enumerate(ALIGN) if a[1] == cur["align"]), 0))
        outline = combo(["Body Text"] + ["Level %d" % i for i in range(1, 10)],
                        min(cur["outline"], 9))
        collapsed = Gtk.CheckButton.new_with_mnemonic("Collapsed by de_fault")
        from . import editfeatures
        collapsed.set_active(editfeatures.is_collapsed_by_default(m, vc))
        p1.pack_start(grid([["Ali_gnment:", align], ["_Outline level:", outline, collapsed]]),
                      False, False, 0)
        outline.connect("changed", lambda c: collapsed.set_sensitive(c.get_active() > 0))
        collapsed.set_sensitive(cur["outline"] > 0)
        p1.pack_start(heading("Indentation"), False, False, 0)
        first = cur["first"]
        left_v = cur["left"]
        left = LengthSpin(left_v, -55880, 55880)
        right = LengthSpin(cur["right"], -55880, 55880)
        special = combo(["(none)", "First line", "Hanging"],
                        0 if first == 0 else (1 if first > 0 else 2))
        by = LengthSpin(abs(first), 0, 55880)
        p1.pack_start(grid([["_Left:", left, "_Special:", "B_y:"],
                            ["_Right:", right, special, by]]), False, False, 0)
        # Mirror indents: Left and Right become Inside and Outside
        mirror = Gtk.CheckButton.new_with_mnemonic("_Mirror indents")
        ned = getattr(self.eng, "ed", None) if getattr(self.eng, "native", False) else None
        mirror_was = bool(ned is not None and "w:mirrorIndents" in (ned.para_xml() if hasattr(ned, "para_xml") else ""))
        mirror.set_active(mirror_was)
        mirror.set_sensitive(ned is not None)
        p1.pack_start(mirror, False, False, 0)
        p1.pack_start(heading("Spacing"), False, False, 0)
        before = PointSpin(round(docapi.to_pt(cur["before"])), 0, 1584, 6)
        after = PointSpin(round(docapi.to_pt(cur["after"])), 0, 1584, 6)
        # line spacing rule
        if cur["mode"] == 0:
            rule = {100: 0, 150: 1, 200: 2}.get(cur["height"], 5)
            at_v = cur["height"] / 100.0
        elif cur["mode"] == 1:
            rule, at_v = 3, docapi.to_pt(cur["height"])
        elif cur["mode"] == 3:
            rule, at_v = 4, docapi.to_pt(cur["height"])
        else:
            rule, at_v = 3, docapi.to_pt(cur["height"])
        rule_c = combo(LINE_RULES, rule)
        at = Gtk.SpinButton.new_with_range(0, 1584, 0.25)
        at.set_digits(2)
        at.set_value(at_v)

        def rule_changed(*_):
            r = rule_c.get_active()
            at.set_sensitive(r >= 3)
            if r < 3:
                at.set_value((1.0, 1.5, 2.0)[r])
            elif r == 5 and at.get_value() > 10:
                at.set_value(1.08)
            elif r in (3, 4) and at.get_value() < 6:
                at.set_value(12)
            prev.queue_draw()
        rule_c.connect("changed", rule_changed)
        context = Gtk.CheckButton.new_with_mnemonic(
            "_Don't add space between paragraphs of the same style")
        context.set_active(cur["context"])
        p1.pack_start(grid([["_Before:", before, "Li_ne spacing:", "_At:"],
                            ["Aft_er:", after, rule_c, at]]), False, False, 0)
        p1.pack_start(context, False, False, 0)
        p1.pack_start(heading("Preview"), False, False, 0)

        def draw(cr, w, h):
            a = ALIGN[max(0, align.get_active())][1]
            cr.set_source_rgb(0.8, 0.8, 0.8)
            y = 8
            for i in range(2):
                cr.rectangle(10, y, w - 20, 3)
                y += 6
            cr.fill()
            y += before.points / 3
            lm = 10 + left.mm100 / 254.0 * 4
            rm = 10 + right.mm100 / 254.0 * 4
            sp = special.get_active()
            fl = by.mm100 / 254.0 * 4 if sp == 1 else (-by.mm100 / 254.0 * 4 if sp == 2 else 0)
            r = rule_c.get_active()
            step = 6 * ((1.0, 1.5, 2.0)[r] if r < 3 else (at.get_value() if r == 5 else 1.2))
            cr.set_source_rgb(0.25, 0.25, 0.25)
            for i in range(4):
                x0 = lm + (fl if i == 0 else 0)
                width = w - x0 - rm
                if i == 3:
                    width *= 0.6
                if a == 3:
                    x0 += (w - x0 - rm - width) / 2
                elif a == 1:
                    x0 = w - rm - width
                cr.rectangle(x0, y, max(10, width), 3)
                y += step
            cr.fill()
            y += after.points / 3
            cr.set_source_rgb(0.8, 0.8, 0.8)
            for i in range(2):
                cr.rectangle(10, y, w - 20, 3)
                y += 6
            cr.fill()
        prev = Preview(draw, 420, 110)
        p1.pack_start(prev, False, False, 0)
        for w in (left, right, by, before, after, at):
            w.connect("value-changed", lambda *_: prev.queue_draw())
        for w in (align, special):
            w.connect("changed", lambda *_: prev.queue_draw())
        rule_changed()

        p2 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        p2.set_border_width(10)
        p2.pack_start(heading("Pagination"), False, False, 0)
        widow = Gtk.CheckButton.new_with_mnemonic("_Widow/Orphan control")
        keepnext = Gtk.CheckButton.new_with_mnemonic("Keep with ne_xt")
        keeplines = Gtk.CheckButton.new_with_mnemonic("_Keep lines together")
        pagebreak = Gtk.CheckButton.new_with_mnemonic("Page _break before")
        widow.set_active(cur["widows"])
        keepnext.set_active(cur["keepnext"])
        keeplines.set_active(not cur["split"])
        pagebreak.set_active(cur["pagebreak"])
        for w in (widow, keepnext, keeplines, pagebreak):
            p2.pack_start(w, False, False, 0)
        p2.pack_start(heading("Formatting exceptions"), False, False, 0)
        nolines = Gtk.CheckButton.new_with_mnemonic("_Suppress line numbers")
        nohyph = Gtk.CheckButton.new_with_mnemonic("_Don't hyphenate")
        nolines.set_active(not cur["linenum"])
        nohyph.set_active(not cur["hyph"])
        p2.pack_start(nolines, False, False, 0)
        p2.pack_start(nohyph, False, False, 0)

        nb.append_page(p1, Gtk.Label(label="Indents and Spacing"))
        nb.append_page(p2, Gtk.Label(label="Line and Page Breaks"))
        d.show_all()
        nb.set_current_page(tab)
        tabs_btn = Gtk.Button(label="_Tabs...", use_underline=True)
        tabs_btn.connect("clicked", lambda *_: self.tabs_dialog())
        d.get_action_area().pack_start(tabs_btn, False, False, 0)
        d.get_action_area().reorder_child(tabs_btn, 0)
        pdef = Gtk.Button(label="Set As _Default", use_underline=True)
        pdef.connect("clicked", lambda *_: d.response(5))
        d.get_action_area().pack_start(pdef, False, False, 0)
        d.get_action_area().reorder_child(pdef, 1)
        tabs_btn.show()
        pdef.show()
        r = d.ask()
        default_scope = None
        if r == 5:
            default_scope = self._ask_default_scope()
            if default_scope is None:
                d.done()
                return
            r = Gtk.ResponseType.OK
        if r != Gtk.ResponseType.OK:
            d.done()
            return
        vc = self._cursor(m)
        if default_scope is not None:
            # the Normal style takes the formatting (and the template, for
            # every new document)
            vc = docapi.para_styles(m).getByName("Standard")
            cur = dict(cur, align=None, left=None, right=None, first=None, before=None,
                       after=None, mode=None, height=None, context=None, outline=0)
        a = ALIGN[align.get_active()][1]
        if a != cur["align"]:
            vc.ParaAdjust = a
        if outline.get_active() != cur["outline"]:
            vc.OutlineLevel = outline.get_active()
        sp = special.get_active()
        fl = by.mm100 if sp == 1 else (-by.mm100 if sp == 2 else 0)
        if left.mm100 != cur["left"]:
            vc.ParaLeftMargin = left.mm100
        if right.mm100 != cur["right"]:
            vc.ParaRightMargin = right.mm100
        if fl != cur["first"]:
            vc.ParaFirstLineIndent = fl
        if docapi.pt(before.points) != cur["before"] and \
                abs(before.points - docapi.to_pt(cur["before"])) > 0.4:
            vc.ParaTopMargin = docapi.pt(before.points)
        if abs(after.points - docapi.to_pt(cur["after"])) > 0.4:
            vc.ParaBottomMargin = docapi.pt(after.points)
        rr = rule_c.get_active()
        new_ls = bridge.struct("com.sun.star.style.LineSpacing")
        if rr < 3:
            new_ls.Mode, new_ls.Height = 0, (100, 150, 200)[rr]
        elif rr == 5:
            new_ls.Mode, new_ls.Height = 0, int(round(at.get_value() * 100))
        elif rr == 3:
            new_ls.Mode, new_ls.Height = 1, docapi.pt(at.get_value())
        else:
            new_ls.Mode, new_ls.Height = 3, docapi.pt(at.get_value())
        if (new_ls.Mode, new_ls.Height) != (cur["mode"], cur["height"]):
            vc.ParaLineSpacing = new_ls
        if context.get_active() != cur["context"]:
            vc.ParaContextMargin = context.get_active()
        if widow.get_active() != cur["widows"]:
            vc.ParaWidows = 2 if widow.get_active() else 0
            vc.ParaOrphans = 2 if widow.get_active() else 0
        if keepnext.get_active() != cur["keepnext"]:
            vc.ParaKeepTogether = keepnext.get_active()
        if keeplines.get_active() == cur["split"]:
            vc.ParaSplit = not keeplines.get_active()
        if pagebreak.get_active() != cur["pagebreak"]:
            vc.BreakType = bridge.enum("com.sun.star.style.BreakType",
                                       "PAGE_BEFORE" if pagebreak.get_active() else "NONE")
        if nolines.get_active() == cur["linenum"]:
            vc.ParaLineNumberCount = not nolines.get_active()
        if nohyph.get_active() == cur["hyph"]:
            vc.ParaIsHyphenation = not nohyph.get_active()
        if ned is not None and mirror.get_active() != mirror_was:
            ned.apply_para([("w:mirrorIndents", [] if mirror.get_active() else None)], "Paragraph")
        if default_scope is None and outline.get_active() > 0:
            try:
                editfeatures.set_collapsed_by_default(self.win, m, self._cursor(m),
                                                      collapsed.get_active())
            except Exception as e:
                print("collapsed by default:", e)
        if default_scope == "all":
            props = {}
            for k in ("ParaAdjust", "ParaLeftMargin", "ParaRightMargin", "ParaFirstLineIndent",
                      "ParaTopMargin", "ParaBottomMargin", "ParaLineSpacing",
                      "ParaContextMargin"):
                try:
                    props[k] = vc.getPropertyValue(k)
                except Exception:
                    pass

            def tmpl(doc):
                st = doc.getStyleFamilies().getByName("ParagraphStyles").getByName("Standard")
                for k, v in props.items():
                    try:
                        st.setPropertyValue(k, v)
                    except Exception:
                        pass
            try:
                self.win.app._edit_normal_template(tmpl)
            except Exception as e:
                print("paragraph default:", e)
        d.done()

    def _ask_default_scope(self):
        """'doc' / 'all' / None, as the original asks."""
        d = FDialog(self.win, "Folio Writer")
        d.add(Gtk.Label(label="Do you want to set the default paragraph formatting to:",
                        xalign=0))
        this = Gtk.RadioButton.new_with_mnemonic(None, "This _document only?")
        alld = Gtk.RadioButton.new_with_mnemonic_from_widget(
            this, "_All documents based on the Normal template?")
        d.add(this)
        d.add(alld)
        r = d.ask()
        out = None
        if r == Gtk.ResponseType.OK:
            out = "doc" if this.get_active() else "all"
        d.done()
        return out

    def tabs_dialog(self):
        m = self.model
        if m is None:
            return
        vc = self._cursor(m)
        stops = list(vc.ParaTabStops or ())
        d = FDialog(self.win, "Tabs")
        kinds = [("Left", "LEFT"), ("Center", "CENTER"), ("Right", "RIGHT"),
                 ("Decimal", "DECIMAL")]
        if getattr(self.eng, "native", False):
            kinds.append(("Bar", "BAR"))
        leaders = [("1 None", " "), ("2 .......", "."), ("3 -------", "-"), ("4 ____", "_")]
        from .widgets import fmt_len, parse_len
        pos = Gtk.Entry()
        sw, tv, store = listbox([fmt_len(s.Position) for s in stops], height=110, width=140)
        kind_rb = []
        kb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        grp = None
        for label, _v in kinds:
            rb = Gtk.RadioButton.new_with_label_from_widget(grp, label)
            grp = grp or rb
            kind_rb.append(rb)
            kb.pack_start(rb, False, False, 0)
        lead_rb = []
        lb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        grp = None
        for label, _v in leaders:
            rb = Gtk.RadioButton.new_with_label_from_widget(grp, label)
            grp = grp or rb
            lead_rb.append(rb)
            lb.pack_start(rb, False, False, 0)
        default = LengthSpin(1270, 0, 55880)
        top = Gtk.Box(spacing=16)
        left_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        left_col.pack_start(Gtk.Label(label="_Tab stop position:", xalign=0, use_underline=True),
                            False, False, 0)
        left_col.pack_start(pos, False, False, 0)
        left_col.pack_start(sw, True, True, 0)
        top.pack_start(left_col, False, False, 0)
        right_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        right_col.pack_start(grid([["De_fault tab stops:", default]]), False, False, 0)
        right_col.pack_start(heading("Alignment"), False, False, 0)
        right_col.pack_start(kb, False, False, 0)
        right_col.pack_start(heading("Leader"), False, False, 0)
        right_col.pack_start(lb, False, False, 0)
        top.pack_start(right_col, True, True, 0)
        d.add(top)
        btns = Gtk.Box(spacing=6)
        setb = Gtk.Button(label="_Set", use_underline=True)
        clr = Gtk.Button(label="Cl_ear", use_underline=True)
        clra = Gtk.Button(label="Clear _All", use_underline=True)
        for b in (setb, clr, clra):
            btns.pack_start(b, False, False, 0)
        d.add(btns)

        def refresh():
            store.clear()
            for s in sorted(stops, key=lambda s: s.Position):
                store.append([fmt_len(s.Position)])

        def do_set(*_):
            mm = parse_len(pos.get_text(), -1)
            if mm < 0:
                return
            ts = bridge.struct("com.sun.star.style.TabStop")
            ts.Position = mm
            ts.Alignment = bridge.enum("com.sun.star.style.TabAlign",
                                       kinds[[r.get_active() for r in kind_rb].index(True)][1])
            ts.FillChar = leaders[[r.get_active() for r in lead_rb].index(True)][1]
            ts.DecimalChar = "."
            stops[:] = [s for s in stops if s.Position != mm] + [ts]
            refresh()

        def do_clear(*_):
            mm = parse_len(pos.get_text(), -1)
            stops[:] = [s for s in stops if s.Position != mm]
            refresh()
        setb.connect("clicked", do_set)
        clr.connect("clicked", do_clear)
        clra.connect("clicked", lambda *_: (stops.clear(), refresh()))
        tv.get_selection().connect("changed", lambda s: pos.set_text(list_selected(tv) or ""))
        if d.ask() == Gtk.ResponseType.OK:
            if pos.get_text().strip() and not any(
                    fmt_len(s.Position) == pos.get_text().strip() for s in stops):
                do_set()
            vc.ParaTabStops = tuple(sorted(stops, key=lambda s: s.Position))
        d.done()

    # ================================================================= Styles
    def new_style(self, modify=None):
        """Create New Style from Formatting / Modify Style."""
        from .stylemodify import modify_dialog
        return modify_dialog(self.win, modify)

    def _old_new_style(self, modify=None):
        m = self._model_or_warn()
        if m is None:
            return
        family = "ParagraphStyles"
        if modify:
            eng_name = engine_style(modify)
            family = "CharacterStyles" if modify in CHAR_STYLES else "ParagraphStyles"
            info = docapi.style_info(m, eng_name, family) or {}
        else:
            vc = docapi.view_cursor(m)
            info = {p: getattr(vc, p) for p in docapi.STYLE_PROPS if hasattr(vc, p)}
            info["parent"] = vc.ParaStyleName
            info["follow"] = None
        names = [word_style(n) for n, _disp in docapi.style_names(m, "ParagraphStyles")]
        names = sorted(set(names), key=str.lower)
        d = FDialog(self.win, "Modify Style" if modify else "Create New Style from Formatting")
        d.add(heading("Properties"))
        name_e = Gtk.Entry(text=modify or self._unique_style_name(m))
        name_e.set_sensitive(not modify or modify not in ("Normal", "Heading 1"))
        kind = combo(["Paragraph", "Character"], 1 if family == "CharacterStyles" else 0)
        kind.set_sensitive(not modify)
        based = combo(["(no style)"] + names, word_style(info.get("parent") or "") or "Normal")
        follow = combo(names, word_style(info.get("follow") or "") or
                       (modify or "Normal"))
        d.add(grid([["_Name:", name_e], ["Style _type:", kind],
                    ["Style _based on:", based], ["_Style for following paragraph:", follow]]))
        d.add(heading("Formatting"))
        fonts = self.eng.fonts()
        font = combo(fonts, info.get("CharFontName") or "Carlito", entry=True)
        size = combo(SIZES, ("%g" % (info.get("CharHeight") or 11)), entry=True)
        size.get_child().set_width_chars(5)
        bold = Gtk.ToggleButton(label="B")
        bold.set_active((info.get("CharWeight") or 100) >= 150)
        ital = Gtk.ToggleButton(label="I")
        ital.set_active(_is_italic(info.get("CharPosture")))
        und = Gtk.ToggleButton(label="U")
        und.set_active(bool(info.get("CharUnderline")))
        color = color_button(info.get("CharColor", -1))
        row1 = Gtk.Box(spacing=4)
        for w in (font, size, bold, ital, und, color):
            row1.pack_start(w, False, False, 0)
        d.add(row1)
        align = combo([a[0] for a in ALIGN],
                      next((i for i, a in enumerate(ALIGN) if a[1] == info.get("ParaAdjust", 0)), 0))
        lsp = combo(["Single", "1.08", "1.15", "1.5 lines", "Double"], 1)
        mode, height = info.get("line_mode", 0), info.get("line_height", 108)
        if mode == 0:
            lsp.set_active({100: 0, 108: 1, 115: 2, 150: 3, 200: 4}.get(height, 1))
        before = PointSpin(round(docapi.to_pt(info.get("ParaTopMargin") or 0)), 0, 1584, 6)
        after = PointSpin(round(docapi.to_pt(info.get("ParaBottomMargin") or 0)), 0, 1584, 6)
        para_row = grid([["Alignment:", align, "Line spacing:", lsp],
                         ["Spacing before:", before, "After:", after]])
        d.add(para_row)
        only = Gtk.RadioButton.new_with_mnemonic(None, "Only in this _document")
        newdocs = Gtk.RadioButton.new_with_mnemonic_from_widget(
            only, "New documents based on this _template")
        rb = Gtk.Box(spacing=16)
        rb.pack_start(only, False, False, 0)
        rb.pack_start(newdocs, False, False, 0)
        d.add(rb)

        def kind_changed(*_):
            para_row.set_sensitive(kind.get_active() == 0)
            follow.set_sensitive(kind.get_active() == 0)
        kind.connect("changed", kind_changed)
        kind_changed()
        if d.ask() != Gtk.ResponseType.OK:
            d.done()
            return
        name = name_e.get_text().strip()
        if not name:
            d.done()
            return
        fam = "CharacterStyles" if kind.get_active() == 1 else "ParagraphStyles"
        props = {"CharFontName": combo_text(font) or "Carlito",
                 "CharWeight": 150.0 if bold.get_active() else 100.0,
                 "CharPosture": _italic() if ital.get_active() else _upright(),
                 "CharUnderline": 1 if und.get_active() else 0}
        try:
            props["CharHeight"] = float(combo_text(size).replace(",", "."))
        except ValueError:
            pass
        if color.color is not None:
            props["CharColor"] = color.color
        if fam == "ParagraphStyles":
            props["ParaAdjust"] = ALIGN[align.get_active()][1]
            props["ParaTopMargin"] = docapi.pt(before.points)
            props["ParaBottomMargin"] = docapi.pt(after.points)
            props["line"] = (0, (100, 108, 115, 150, 200)[lsp.get_active()])
        eng_name = engine_style(name)
        based_on = based.get_active_text()
        based_on = None if based_on in (None, "(no style)") else engine_style(based_on)
        try:
            if modify:
                docapi.set_style(m, engine_style(modify), fam, **props)
                if fam == "ParagraphStyles":
                    st = m.getStyleFamilies().getByName(fam).getByName(engine_style(modify))
                    if follow.get_active_text():
                        st.FollowStyle = engine_style(follow.get_active_text())
            else:
                docapi.new_style(m, eng_name, based_on=based_on,
                                 follow=engine_style(follow.get_active_text() or name)
                                 if fam == "ParagraphStyles" else None,
                                 family=fam, from_selection=False, **props)
        except Exception as e:
            self.message("The style couldn't be saved: %s" % e)
        if newdocs.get_active():
            self.win.app.remember_style(name if not modify else modify, fam, props)
        d.done()
        self.win.refresh_styles()

    def _unique_style_name(self, m):
        fam = docapi.para_styles(m)
        i = 1
        while fam.hasByName("Style%d" % i):
            i += 1
        return "Style%d" % i

    def modify_style(self, name):
        from .stylemodify import modify_dialog
        modify_dialog(self.win, name)

    def apply_styles(self):
        """Apply Styles box (Ctrl+Shift+S): type a style name and press Enter."""
        m = self.model
        names = sorted({word_style(n) for n, _ in docapi.style_names(m)} if m else [],
                       key=str.lower)
        d = FDialog(self.win, "Apply Styles", buttons=(("Reapply", Gtk.ResponseType.OK),
                                                       ("Cancel", Gtk.ResponseType.CANCEL)))
        d.add(Gtk.Label(label="Style Name:", xalign=0))
        e = Gtk.ComboBoxText.new_with_entry()
        for n in names:
            e.append_text(n)
        cur = word_style(self.eng.get(".uno:StyleApply") or "Normal")
        e.get_child().set_text(cur)
        e.get_child().set_activates_default(True)
        comp = Gtk.EntryCompletion()
        st = Gtk.ListStore(str)
        for n in names:
            st.append([n])
        comp.set_model(st)
        comp.set_text_column(0)
        e.get_child().set_completion(comp)
        d.add(e)
        mod = Gtk.Button(label="_Modify...", use_underline=True)
        d.get_action_area().pack_start(mod, False, False, 0)
        mod.connect("clicked", lambda *_: d.response(42))
        r = d.ask()
        name = e.get_child().get_text().strip()
        d.done()
        if r == Gtk.ResponseType.OK and name:
            self.win.actions.apply_style(name)
        elif r == 42 and name:
            self.modify_style(name)

    # ==================================================== Borders and Shading
    def borders_dialog(self, page_tab=False):
        if getattr(self.eng, "native", False):
            from .native import borders
            borders.dialog(self.win, 1 if page_tab else 0)
            return
        if self._model_or_warn() is not None:
            from . import bordersdlg
            bordersdlg.dialog(self.win, 1 if page_tab else 0)

    def page_borders(self):
        if getattr(self.eng, "native", False):
            from .native import pageborders
            pageborders.dialog(self.win)
            return
        self.borders_dialog(page_tab=True)

    def border(self, which):
        """Borders drop-down on the Home tab."""
        m = self.model
        if m is None:
            return
        sides = {"bottom": {"bottom"}, "top": {"top"}, "left": {"left"}, "right": {"right"},
                 "none": set(), "all": {"top", "bottom", "left", "right"},
                 "outside": {"top", "bottom", "left", "right"}}.get(which)
        if sides is None:
            return
        if which in ("bottom", "top", "left", "right"):
            vc = docapi.view_cursor(m)
            now = {s for s, p in (("top", "TopBorder"), ("bottom", "BottomBorder"),
                                  ("left", "LeftBorder"), ("right", "RightBorder"))
                   if getattr(vc, p).OuterLineWidth > 0}
            sides = now ^ sides
        docapi.para_border(m, sides)

    # =============================================================== Drop cap
    def drop_cap(self):
        if getattr(self.eng, "native", False):
            return self._native_drop_cap()
        m = self._model_or_warn()
        if m is None:
            return
        vc = docapi.view_cursor(m)
        cur = vc.DropCapFormat
        d = FDialog(self.win, "Drop Cap")
        d.add(heading("Position"))
        grp = None
        radios = []
        hb = Gtk.Box(spacing=16)
        for label in ("None", "Dropped", "In margin"):
            rb = Gtk.RadioButton.new_with_label_from_widget(grp, label)
            grp = grp or rb
            radios.append(rb)
            hb.pack_start(rb, False, False, 0)
        radios[1 if cur.Lines > 1 else 0].set_active(True)
        d.add(hb)
        d.add(heading("Options"))
        lines = Gtk.SpinButton.new_with_range(1, 10, 1)
        lines.set_value(cur.Lines if cur.Lines > 1 else 3)
        dist = LengthSpin(cur.Distance, 0, 25400)
        fonts = self.eng.fonts() or []
        cur_font = ""
        try:
            csn = vc.DropCapCharStyleName
            if csn:
                cur_font = docapi.char_styles(m).getByName(csn).CharFontName
        except Exception:
            pass
        font = combo(fonts, cur_font or (vc.CharFontName or "").split(":")[0], entry=True)
        d.add(grid([["_Font:", font], ["_Lines to drop:", lines],
                    ["Distance from te_xt:", dist]]))
        if d.ask() == Gtk.ResponseType.OK:
            mode = ("none", "dropped", "margin")[[r.get_active() for r in radios].index(True)]
            docapi.drop_cap(m, mode, int(lines.get_value()), dist.mm100)
            fname = combo_text(font).strip()
            if mode != "none" and fname and fname != (vc.CharFontName or "").split(":")[0]:
                try:
                    cs = docapi.char_styles(m)
                    name = "Drop Caps"
                    if not cs.hasByName(name):
                        cs.insertByName(name, m.createInstance(
                            "com.sun.star.style.CharacterStyle"))
                    cs.getByName(name).CharFontName = fname
                    docapi.view_cursor(m).DropCapCharStyleName = name
                except Exception as e:
                    print("drop cap font:", e)
            elif mode != "none":
                try:
                    docapi.view_cursor(m).DropCapCharStyleName = ""
                except Exception:
                    pass
        d.done()

    def _native_drop_cap(self):
        ed = self.eng.ed
        cur = ed.drop_cap_info()
        d = FDialog(self.win, "Drop Cap")
        d.add(heading("Position"))
        grp = None
        radios = []
        hb = Gtk.Box(spacing=16)
        for label in ("None", "Dropped", "In margin"):
            rb = Gtk.RadioButton.new_with_label_from_widget(grp, label)
            grp = grp or rb
            radios.append(rb)
            hb.pack_start(rb, False, False, 0)
        radios[{"drop": 1, "margin": 2}.get(cur[0] if cur else "", 0)].set_active(True)
        d.add(hb)
        d.add(heading("Options"))
        lines = Gtk.SpinButton.new_with_range(1, 10, 1)
        lines.set_value(cur[1] if cur else 3)
        dist = LengthSpin((cur[2] if cur else 0) * 2540.0 / 1440.0, 0, 25400)
        fonts = self.eng.fonts() or []
        font = combo(fonts, ed.state().get("font", ""), entry=True)
        d.add(grid([["_Font:", font], ["_Lines to drop:", lines], ["Distance from te_xt:", dist]]))
        r = d.ask()
        mode = ("none", "drop", "margin")[[x.get_active() for x in radios].index(True)]
        vals = (int(lines.get_value()), int(round(dist.mm100 * 1440.0 / 2540.0)), combo_text(font).strip())
        d.done()
        if r != Gtk.ResponseType.OK:
            return
        n, ds, fname = vals
        if ed.set_drop_cap(mode, n, ds, fname or None):
            self.eng.view.after_edit()

    # =================================================================== Sort
    def sort_dialog(self):
        m = self._model_or_warn()
        if m is None:
            return
        from . import sortdlg
        sortdlg.dialog(self.win)


def _object_size(self):
    from . import objlayout
    if self._model_or_warn() is not None:
        objlayout.layout_dialog(self.win, 2)


def _object_size_old(self):
    from . import drawing
    from .widgets import LengthSpin, FDialog, grid
    m = self._model_or_warn()
    obj = drawing.selected_shape(m) if m else None
    if obj is None:
        return
    size = obj.Size
    d = FDialog(self.win, "Layout")
    w = LengthSpin(size.Width, 10, 300000)
    h = LengthSpin(size.Height, 10, 300000)
    lock = Gtk.CheckButton.new_with_mnemonic("Lock _aspect ratio")
    lock.set_active(drawing.kind_of(obj) == "picture")
    ratio = size.Width / float(size.Height or 1)
    busy = [False]

    def keep(src, dst, r):
        if lock.get_active() and not busy[0]:
            busy[0] = True
            dst.set_value(src.get_value() * r)
            busy[0] = False
    w.connect("value-changed", lambda *_: keep(w, h, 1 / ratio))
    h.connect("value-changed", lambda *_: keep(h, w, ratio))
    d.add(grid([["_Height:", h], ["_Width:", w]]))
    d.add(lock)
    if d.ask() == Gtk.ResponseType.OK:
        drawing.set_size(obj, w.mm100, h.mm100)
    d.done()


TextDialogs.object_size = _object_size
