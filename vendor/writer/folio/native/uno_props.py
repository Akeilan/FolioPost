"""The formatting at the caret (or of a style) under the property names the
app's dialogs already use (CharWeight, ParaLeftMargin...), read from and
written to Folio's own engine."""
from gi.repository import GLib

from .. import bridge

MM = 2540.0 / 1440.0      # 1/100 mm per twip

UL_TO_NUM = {"none": 0, "single": 1, "double": 2, "dotted": 3, "dash": 5, "dashLong": 6,
             "dotDash": 7, "dotDotDash": 8, "wave": 10, "wavyDouble": 11, "thick": 12,
             "dottedHeavy": 13, "dashedHeavy": 14, "dashLongHeavy": 15, "dashDotHeavy": 16,
             "dashDotDotHeavy": 17, "wavyHeavy": 18, "words": 1}
NUM_TO_UL = {v: k for k, v in UL_TO_NUM.items() if k != "words"}
NUM_TO_UL[9] = "wave"
JC_TO_ADJ = {"left": 0, "start": 0, "right": 1, "end": 1, "both": 2, "distribute": 2,
             "center": 3}
ADJ_TO_JC = {0: "left", 1: "right", 2: "both", 3: "center"}
TAB_KIND = {"left": "LEFT", "center": "CENTER", "right": "RIGHT", "decimal": "DECIMAL", "bar": "BAR"}
LEADER = {"dot": ".", "hyphen": "-", "underscore": "_", "middleDot": "·", "none": " "}


def _enum_value(v):
    return getattr(v, "value", v)


def _tw(mm100):
    return int(round((mm100 or 0) / MM))


class CursorProps:
    """Reads and writes the selection's formatting. Writes made in one go
    (a dialog's OK) undo as one step."""

    def __init__(self, engine, label="Format"):
        object.__setattr__(self, "eng", engine)
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "_group", False)

    # -------------------------------------------------------------- reading
    @property
    def _r(self):
        return self.eng.ed.run_values()

    @property
    def _p(self):
        return self.eng.ed.para_values()

    def _set_tabs(self, tabs):
        self._begin()
        self.eng.ed.set_tabs(tabs)

    def _set_char_style(self, v):
        self._begin()
        self.eng.ed.set_char_style(v or "")

    def getString(self):
        return self.eng.ed.selected_text()

    def isCollapsed(self):
        return not self.eng.ed.has_selection()

    def getPropertyValue(self, k):
        return getattr(self, k)

    def setPropertyValue(self, k, v):
        setattr(self, k, v)

    def __getattr__(self, k):
        r = lambda: object.__getattribute__(self, "_r")
        p = lambda: object.__getattribute__(self, "_p")
        if k == "CharFontName":
            return r()["font"]
        if k in ("CharHeight", "CharHeightAsian", "CharHeightComplex"):
            return r()["size"]
        if k == "CharWeight":
            return 150.0 if r()["bold"] else 100.0
        if k == "CharPosture":
            return bridge.enum("com.sun.star.awt.FontSlant", "ITALIC" if r()["italic"] else "NONE")
        if k == "CharUnderline":
            return UL_TO_NUM.get(r()["underline"], 1)
        if k == "CharWordMode":
            return r()["underline"] == "words"
        if k == "CharUnderlineHasColor":
            return r()["underline_color"] >= 0
        if k == "CharUnderlineColor":
            return r()["underline_color"]
        if k == "CharColor":
            return r()["color"]
        if k == "CharStrikeout":
            v = r()
            return 2 if v["dstrike"] else (1 if v["strike"] else 0)
        if k == "CharEscapement":
            va = r()["vert_align"]
            return 33 if va == "superscript" else (-33 if va == "subscript" else 0)
        if k == "CharEscapementHeight":
            return 58 if r()["vert_align"] in ("superscript", "subscript") else 100
        if k == "CharCaseMap":
            v = r()
            return 1 if v["caps"] else (4 if v["small_caps"] else 0)
        if k == "CharHidden":
            return r()["hidden"]
        if k == "CharScaleWidth":
            return r()["scale"]
        if k == "CharKerning":
            return int(round(r()["spacing"] * MM))
        if k == "CharAutoKerning":
            return r()["kern"] > 0
        if k == "CharContoured":
            return r()["outline"]
        if k == "CharShadowed":
            return r()["shadow"]
        if k == "CharRelief":
            v = r()
            return 1 if v["emboss"] else (2 if v["imprint"] else 0)
        if k == "CharTransparence":
            return 0
        if k == "CharBackColor":
            return -1
        if k == "CharStyleName":
            return r()["style"]
        if k == "CharLocale":
            return bridge.struct("com.sun.star.lang.Locale", Language="en", Country="US")
        # paragraph
        if k == "ParaAdjust":
            return JC_TO_ADJ.get(p()["align"], 0)
        if k == "ParaLeftMargin":
            return int(round(p()["ind_left"] * MM))
        if k == "ParaRightMargin":
            return int(round(p()["ind_right"] * MM))
        if k == "ParaFirstLineIndent":
            return int(round(p()["ind_first"] * MM))
        if k == "ParaTopMargin":
            return int(round(p()["before"] * MM))
        if k == "ParaBottomMargin":
            return int(round(p()["after"] * MM))
        if k == "ParaLineSpacing":
            v = p()
            ls = bridge.struct("com.sun.star.style.LineSpacing")
            if v["line_rule"] == "exact":
                ls.Mode, ls.Height = 3, int(round(abs(v["line"]) * MM))
            elif v["line_rule"] == "atLeast":
                ls.Mode, ls.Height = 1, int(round(v["line"] * MM))
            else:
                ls.Mode, ls.Height = 0, int(round(v["line"] * 100 / 240.0))
            return ls
        if k == "ParaContextMargin":
            return p()["contextual"]
        if k == "OutlineLevel":
            lv = p()["outline_lvl"]
            return 0 if lv >= 9 else lv + 1
        if k in ("ParaWidows", "ParaOrphans"):
            return 2 if p()["widow"] else 0
        if k == "ParaKeepTogether":
            return p()["keep_next"]
        if k == "ParaSplit":
            return not p()["keep_lines"]
        if k == "BreakType":
            return bridge.enum("com.sun.star.style.BreakType",
                               "PAGE_BEFORE" if p()["page_break_before"] else "NONE")
        if k == "ParaLineNumberCount":
            return not p()["suppress_line_numbers"]
        if k == "ParaIsHyphenation":
            return not p()["suppress_hyphens"]
        if k == "ParaStyleName":
            return self.eng.ed.state()["style"]
        if k == "ParaTabStops":
            out = []
            for pos, kind, leader in p()["tabs"]:
                ts = bridge.struct("com.sun.star.style.TabStop")
                ts.Position = int(round(pos * MM))
                ts.Alignment = bridge.enum("com.sun.star.style.TabAlign",
                                           TAB_KIND.get(kind, "LEFT"))
                ts.FillChar = LEADER.get(leader, " ")
                ts.DecimalChar = "."
                out.append(ts)
            return tuple(out)
        if k in ("ParaBackColor",):
            return -1
        if k in ("ParaBackTransparent",):
            return True
        if k in ("DropCapFormat", "DropCapCharStyleName", "NumberingStyleName"):
            return None
        if k == "ParaIsAutoFirstLineIndent":
            return False
        raise AttributeError(k)

    # -------------------------------------------------------------- writing
    def _begin(self):
        if not self._group:
            object.__setattr__(self, "_group", True)
            self.eng.ed.begin_group(self.label)

            def end():
                object.__setattr__(self, "_group", False)
                self.eng.ed.end_group()
                self.eng.view.after_edit()
                return False
            GLib.idle_add(end)

    def _run(self, edits):
        self._begin()
        self.eng.ed.apply_run(edits, self.label)

    def _para(self, name, attrs):
        self._begin()
        self.eng.ed.apply_para_attrs(name, attrs, self.label)

    def _para_el(self, edits):
        self._begin()
        self.eng.ed.apply_para(edits, self.label)

    @staticmethod
    def _toggle(name, on, cs=None):
        val = [] if on else [("w:val", "0")]
        e = [(name, val)]
        if cs:
            e.append((cs, list(val)))
        return e

    def __setattr__(self, k, v):
        if k == "CharFontName":
            f = str(v).split(":")[0]
            self._run([("w:rFonts", [("w:ascii", f), ("w:hAnsi", f), ("w:cs", f),
                                     ("w:eastAsia", f)])])
        elif k in ("CharHeight", "CharHeightAsian", "CharHeightComplex"):
            hp = str(int(round(float(v) * 2)))
            self._run([("w:sz", [("w:val", hp)]), ("w:szCs", [("w:val", hp)])])
        elif k == "CharWeight":
            self._run(self._toggle("w:b", float(v) >= 150, "w:bCs"))
        elif k == "CharPosture":
            self._run(self._toggle("w:i", _enum_value(v) in ("ITALIC", "OBLIQUE"), "w:iCs"))
        elif k == "CharUnderline":
            n = int(v)
            if n == 0:
                self._run([("w:u", None)])
            else:
                self._run([("w:u", [("w:val", NUM_TO_UL.get(n, "single"))])])
        elif k == "CharWordMode":
            if v and self._r["underline"] not in ("none",):
                self._run([("w:u", [("w:val", "words")])])
        elif k == "CharUnderlineColor":
            cur = self._r["underline"]
            if cur != "none":
                at = [("w:val", cur)]
                if int(v) >= 0:
                    at.append(("w:color", "%06X" % (int(v) & 0xFFFFFF)))
                self._run([("w:u", at)])
        elif k == "CharUnderlineHasColor":
            pass
        elif k == "CharColor":
            c = int(v)
            self._run([("w:color", [("w:val", "auto" if c < 0 else "%06X" % (c & 0xFFFFFF))])])
        elif k == "CharStrikeout":
            n = int(v)
            self._run(self._toggle("w:strike", n not in (0, 2)) +
                      self._toggle("w:dstrike", n == 2))
        elif k == "CharEscapement":
            n = int(v)
            if n > 0:
                self._run([("w:vertAlign", [("w:val", "superscript")])])
            elif n < 0:
                self._run([("w:vertAlign", [("w:val", "subscript")])])
            else:
                self._run([("w:vertAlign", None)])
        elif k == "CharEscapementHeight":
            pass
        elif k == "CharCaseMap":
            n = int(v)
            self._run(self._toggle("w:caps", n == 1) + self._toggle("w:smallCaps", n == 4))
        elif k == "CharHidden":
            self._run(self._toggle("w:vanish", bool(v)))
        elif k == "CharScaleWidth":
            n = int(v)
            self._run([("w:w", None if n == 100 else [("w:val", str(n))])])
        elif k == "CharKerning":
            t = _tw(int(v))
            self._run([("w:spacing", None if t == 0 else [("w:val", str(t))])])
        elif k == "CharAutoKerning":
            self._run([("w:kern", [("w:val", "2")] if v else None)])
        elif k == "CharContoured":
            self._run(self._toggle("w:outline", bool(v)))
        elif k == "CharShadowed":
            self._run(self._toggle("w:shadow", bool(v)))
        elif k == "CharRelief":
            n = int(v)
            self._run(self._toggle("w:emboss", n == 1) + self._toggle("w:imprint", n == 2))
        elif k == "CharStyleName":
            self._set_char_style(v)
        elif k in ("CharTransparence", "CharLocale", "CharBackColor", "CharBackTransparent"):
            pass
        # paragraph
        elif k == "ParaAdjust":
            jc = ADJ_TO_JC.get(int(_enum_value(v)) if not isinstance(_enum_value(v), str)
                               else {"LEFT": 0, "RIGHT": 1, "BLOCK": 2, "CENTER": 3}.get(
                                   _enum_value(v), 0), "left")
            self._para_el([("w:jc", None if jc == "left" else [("w:val", jc)])])
        elif k == "ParaLeftMargin":
            self._para("w:ind", [("w:left", str(_tw(v))), ("w:start", None)])
        elif k == "ParaRightMargin":
            self._para("w:ind", [("w:right", str(_tw(v))), ("w:end", None)])
        elif k == "ParaFirstLineIndent":
            t = _tw(v)
            if t < 0:
                self._para("w:ind", [("w:hanging", str(-t)), ("w:firstLine", None)])
            else:
                self._para("w:ind", [("w:firstLine", str(t)), ("w:hanging", None)])
        elif k == "ParaTopMargin":
            self._para("w:spacing", [("w:before", str(_tw(v))), ("w:beforeAutospacing", None),
                                     ("w:beforeLines", None)])
        elif k == "ParaBottomMargin":
            self._para("w:spacing", [("w:after", str(_tw(v))), ("w:afterAutospacing", None),
                                     ("w:afterLines", None)])
        elif k == "ParaLineSpacing":
            mode, h = int(v.Mode), int(v.Height)
            if mode == 0:
                self._para("w:spacing", [("w:line", str(int(round(h * 240 / 100.0)))),
                                         ("w:lineRule", "auto")])
            elif mode == 1:
                self._para("w:spacing", [("w:line", str(_tw(h))), ("w:lineRule", "atLeast")])
            else:
                self._para("w:spacing", [("w:line", str(_tw(h))), ("w:lineRule", "exact")])
        elif k == "ParaContextMargin":
            self._para_el(self._toggle("w:contextualSpacing", bool(v)))
        elif k == "OutlineLevel":
            n = int(v)
            self._para_el([("w:outlineLvl", None if n == 0 else [("w:val", str(n - 1))])])
        elif k == "ParaWidows":
            self._para_el(self._toggle("w:widowControl", int(v) > 0))
        elif k == "ParaOrphans":
            pass
        elif k == "ParaKeepTogether":
            self._para_el(self._toggle("w:keepNext", bool(v)))
        elif k == "ParaSplit":
            self._para_el(self._toggle("w:keepLines", not v))
        elif k == "BreakType":
            self._para_el(self._toggle("w:pageBreakBefore", _enum_value(v) == "PAGE_BEFORE"))
        elif k == "ParaLineNumberCount":
            self._para_el(self._toggle("w:suppressLineNumbers", not v))
        elif k == "ParaIsHyphenation":
            self._para_el(self._toggle("w:suppressAutoHyphens", not v))
        elif k == "ParaStyleName":
            self._begin()
            self.eng.apply_style(v)
        elif k == "ParaTabStops":
            tabs = []
            for ts in v:
                kind = {"LEFT": "left", "CENTER": "center", "RIGHT": "right",
                        "DECIMAL": "decimal", "BAR": "bar"}.get(_enum_value(ts.Alignment), "left")
                lead = {".": "dot", "-": "hyphen", "_": "underscore",
                        "·": "middleDot"}.get(str(getattr(ts.FillChar, "value", ts.FillChar)), "none")
                tabs.append((_tw(ts.Position), kind, lead))
            self._set_tabs(tabs)
        else:
            print("native: property not supported:", k)


class StyleProps(CursorProps):
    """A style's formatting under the same names; writes change the style."""

    def __init__(self, engine, sid):
        CursorProps.__init__(self, engine, "Modify Style")
        object.__setattr__(self, "sid", sid)

    @property
    def _r(self):
        return self.eng.ed.style_run_values(self.sid)

    @property
    def _p(self):
        return self.eng.ed.style_para_values(self.sid)

    def _run(self, edits):
        self._begin()
        self.eng.ed.style_apply_run(self.sid, edits)

    def _para(self, name, attrs):
        self._begin()
        self.eng.ed.style_apply_para_attrs(self.sid, name, attrs)

    def _para_el(self, edits):
        self._begin()
        self.eng.ed.style_apply_para(self.sid, edits)

    def _set_tabs(self, tabs):
        self._begin()
        self.eng.ed.style_set_tabs(self.sid, tabs)

    def _set_char_style(self, v):
        pass

    def getString(self):
        return ""

    def isCollapsed(self):
        return True


class NativeModel:
    """Stands in for the UNO document where dialogs only check that one is
    open; anything else they ask of it isn't there."""

    def __init__(self, engine):
        self.eng = engine

    def __bool__(self):
        return True

    def __getattr__(self, k):
        raise AttributeError(k)
