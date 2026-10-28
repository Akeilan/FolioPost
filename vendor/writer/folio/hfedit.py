"""Headers and footers the way the original handles them:

* double-click the top or bottom margin of a page to edit the header or
  footer (it is created on the spot if the page has none, without moving
  the body text); double-click the body to go back;
* while you are in one, a single click on the body does nothing, and while
  you are in the body a single click on a header or footer does nothing;
* Link to Previous, Previous / Next section, Show Document Text and the
  Page Number Format dialog on the Header & Footer tab."""
import json

from gi.repository import Gtk

from . import bridge, docapi
from .widgets import FDialog, combo, grid

MM = 1440.0 / 2540.0       # mm100 -> twips


# ------------------------------------------------------------ geometry
def _page_at(win, tx, ty):
    for i, (rx, ry, rw, rh) in enumerate(win.engine.page_rects()):
        if rx <= tx <= rx + rw and ry <= ty <= ry + rh:
            return i, (rx, ry, rw, rh)
    return None, None


def zone(win, x_px, y_px):
    """'header', 'footer', 'body' or None for a point on the view."""
    m = win.engine.model
    if m is None:
        return None, None
    tx, ty = win.engine.px_to_twips(x_px, y_px)
    i, r = _page_at(win, tx, ty)
    if r is None:
        return None, None
    try:
        ps = docapi.page_style(m)
        top = ps.TopMargin + (ps.HeaderHeight if ps.HeaderIsOn else 0)
        bottom = ps.BottomMargin + (ps.FooterHeight if ps.FooterIsOn else 0)
    except Exception:
        return None, None
    rx, ry, rw, rh = r
    if ty < ry + top * MM:
        return "header", (i, r, tx, ty)
    if ty > ry + rh - bottom * MM:
        return "footer", (i, r, tx, ty)
    return "body", (i, r, tx, ty)


def press(win, event):
    """Button press on the document. True when it was handled here."""
    from gi.repository import Gdk
    if event.button != 1 or event.state & (Gdk.ModifierType.SHIFT_MASK |
                                           Gdk.ModifierType.CONTROL_MASK):
        return False
    if getattr(win, "multipage", None) is not None:
        return False
    z, info = zone(win, event.x, event.y)
    if z is None:
        return False
    inside = win.in_header_footer()
    double = event.type == Gdk.EventType._2BUTTON_PRESS
    if event.type == Gdk.EventType._3BUTTON_PRESS:
        return inside != (z != "body")
    if z == "body":
        if not inside:
            return False
        if double:
            # back to the body, where the double-click was
            win.engine.click_at(info[2], info[3])
            return True
        return True                 # single clicks on the dimmed body do nothing
    # header / footer zone
    if inside:
        return False                # editing it: clicks work as usual
    if not double:
        return True
    try:
        enter(win, z, info)
    except Exception:
        import traceback
        traceback.print_exc()
    return True


def enter(win, which, info=None):
    """Into the header or footer of the page at info (or the current one)."""
    m = win.engine.model
    if m is None:
        return
    ps = docapi.page_style(m)
    key = "Header" if which == "header" else "Footer"
    created = not getattr(ps, key + "IsOn")
    if created:
        um = m.getUndoManager()
        um.enterUndoContext("Insert " + key)
        try:
            docapi.enable_header_footer(m, which, ps)
        finally:
            um.leaveUndoContext()
    if info is None:
        win.engine.command(".uno:JumpToHeader" if which == "header" else ".uno:JumpToFooter")
        return
    _i, (rx, ry, rw, rh), tx, _ty = info
    if which == "header":
        y = ry + (ps.TopMargin + 60) * MM
    else:
        y = ry + rh - (ps.BottomMargin + ps.FooterHeight - 60) * MM
    x = min(max(tx, rx + ps.LeftMargin * MM + 20), rx + rw - ps.RightMargin * MM - 20)

    def go():
        win.engine.click_at(x, y)
        return False
    from gi.repository import GLib
    GLib.timeout_add(80 if created else 0, go)


# ------------------------------------------------------------ sections
def section_styles(m):
    """Page styles in document order: one per section."""
    out = []
    try:
        first = m.getText().createTextCursor()
        first.gotoStart(False)
        out.append(first.PageStyleName or "Standard")
    except Exception:
        out.append("Standard")
    en = m.getText().createEnumeration()
    while en.hasMoreElements():
        p = en.nextElement()
        try:
            name = p.PageDescName
        except Exception:
            name = None
        if name and name not in out:
            out.append(name)
    return out


def _style(m, name):
    return m.getStyleFamilies().getByName("PageStyles").getByName(name)


def _linked(m):
    try:
        v = json.loads(docapi._doc_setting(m, "HFLinks", "") or "{}")
        return v if isinstance(v, dict) else {}
    except ValueError:
        return {}


def which_part(win):
    m = win.engine.model
    try:
        impl = docapi.read_cursor(m).getText()
        ps = docapi.page_style(m)
        for k in ("Header", "Footer"):
            for suffix in ("Text", "TextFirst", "TextLeft", "TextRight"):
                try:
                    t = getattr(ps, k + suffix)
                except Exception:
                    continue
                if t is not None and t == impl:
                    return k.lower(), suffix
    except Exception:
        pass
    return "header", "Text"


def is_linked(win):
    m = win.engine.model
    if m is None:
        return False
    name = docapi.read_cursor(m).PageStyleName or "Standard"
    styles = section_styles(m)
    if name not in styles or styles.index(name) == 0:
        return False
    part, _s = which_part(win)
    return bool(_linked(m).get("%s|%s" % (name, part), True))


def _copy_part(win, src, dst, part):
    """Copy one style's header/footer (with formatting) into another's."""
    m = win.engine.model
    key = "Header" if part == "header" else "Footer"
    if not getattr(src, key + "IsOn"):
        return
    if not getattr(dst, key + "IsOn"):
        docapi.enable_header_footer(m, part, dst)
    st, dt = getattr(src, key + "Text"), getattr(dst, key + "Text")
    ctrl = docapi.controller(m)
    vc = docapi.view_cursor(m)
    keep = vc.getText().createTextCursorByRange(vc.getStart())
    # in a header/footer, going back by position would land on another page's
    # copy of it: go back to where the caret was on screen instead
    caret = getattr(win, "_follow_rect", None) if win.in_header_footer() else None
    try:
        a = st.createTextCursor()
        a.gotoStart(False)
        a.gotoEnd(True)
        ctrl.select(a)
        t = ctrl.getTransferable()
        b = dt.createTextCursor()
        b.gotoStart(False)
        b.gotoEnd(True)
        b.setString("")
        ctrl.select(b)
        ctrl.insertTransferable(t)
    finally:
        try:
            if caret is not None:
                win.engine.click_at(caret[0] + 1, caret[1] + max(1, caret[3] // 2))
            else:
                vc.gotoRange(keep, False)
        except Exception:
            pass


def set_link(win, on):
    """Link to Previous: this section's header (or footer) is the previous
    section's; turning it on copies it over, and edits are carried along."""
    m = win.engine.model
    if m is None:
        return
    name = docapi.read_cursor(m).PageStyleName or "Standard"
    styles = section_styles(m)
    if name not in styles or styles.index(name) == 0:
        win.status.flash("The first section has nothing before it to link to.")
        return
    part, _s = which_part(win)
    links = _linked(m)
    links["%s|%s" % (name, part)] = bool(on)
    docapi._set_doc_setting(m, "HFLinks", json.dumps(links))
    if on:
        if win.dialogs.confirm("Do you want to delete this header/footer and connect to the "
                               "header/footer in the previous section?", yes="Yes", no="No"):
            prev = _style(m, styles[styles.index(name) - 1])
            _copy_part(win, prev, _style(m, name), part)
        else:
            links["%s|%s" % (name, part)] = False
            docapi._set_doc_setting(m, "HFLinks", json.dumps(links))
    win.ribbon.update("folio:hf-link", "true" if is_linked(win) else "false")


def propagate(win, style_name, part):
    """After editing a header/footer: copy it into the sections linked to it."""
    m = win.engine.model
    if m is None:
        return
    styles = section_styles(m)
    if style_name not in styles:
        return
    links = _linked(m)
    i = styles.index(style_name)
    src = _style(m, style_name)
    for nxt in styles[i + 1:]:
        if not links.get("%s|%s" % (nxt, part), True):
            break
        _copy_part(win, src, _style(m, nxt), part)


def goto_section(win, d):
    """Previous / Next: the header (or footer) of the neighbouring section."""
    m = win.engine.model
    if m is None:
        return
    name = docapi.read_cursor(m).PageStyleName or "Standard"
    styles = section_styles(m)
    if name not in styles:
        return
    k = styles.index(name) + d
    if not 0 <= k < len(styles):
        win.status.flash("There is no %s section." % ("previous" if d < 0 else "next"))
        return
    part, _s = which_part(win)
    ps = _style(m, styles[k])
    key = "Header" if part == "header" else "Footer"
    if not getattr(ps, key + "IsOn"):
        docapi.enable_header_footer(m, part, ps)
    try:
        vc = docapi.view_cursor(m)
        vc.gotoRange(getattr(ps, key + "Text").getStart(), False)
    except Exception as e:
        print("section:", e)


# ------------------------------------------------------------ page numbers
FORMATS = [("1, 2, 3, ...", 4), ("a, b, c, ...", 1), ("A, B, C, ...", 0),
           ("i, ii, iii, ...", 3), ("I, II, III, ...", 2)]
SEPARATORS = [("- (hyphen)", "-"), (". (period)", "."), (": (colon)", ":"),
              ("— (em dash)", "—"), ("– (en dash)", "–")]


def _page_fields(m, ps):
    out = []
    for key in ("Header", "Footer"):
        if not getattr(ps, key + "IsOn"):
            continue
        for suffix in ("Text", "TextFirst", "TextLeft"):
            try:
                t = getattr(ps, key + suffix)
            except Exception:
                continue
            if t is None:
                continue
            en = t.createEnumeration()
            while en.hasMoreElements():
                p = en.nextElement()
                try:
                    pe = p.createEnumeration()
                except Exception:
                    continue
                while pe.hasMoreElements():
                    r = pe.nextElement()
                    if getattr(r, "TextPortionType", "") == "TextField":
                        f = r.TextField
                        if f.supportsService("com.sun.star.text.textfield.PageNumber"):
                            out.append((t, r, f))
    return out


def _section_first_para(m, name):
    en = m.getText().createEnumeration()
    first = None
    while en.hasMoreElements():
        p = en.nextElement()
        if not p.supportsService("com.sun.star.text.Paragraph"):
            continue
        if first is None:
            first = p
        try:
            if p.PageDescName == name:
                return p
        except Exception:
            pass
    return first


def format_dialog(win):
    m = win.engine.model
    if m is None:
        return
    ps = docapi.page_style(m)
    name = docapi.read_cursor(m).PageStyleName or "Standard"
    d = FDialog(win, "Page Number Format")
    cur_fmt = getattr(ps, "NumberingType", 4)
    fmt = combo([f for f, _v in FORMATS], next((i for i, (_f, v) in enumerate(FORMATS)
                                                 if v == cur_fmt), 0))
    d.add(grid([["Number _format:", fmt]]))
    chap = Gtk.CheckButton.new_with_mnemonic("Include chapter _number")
    heads = combo(["Heading %d" % i for i in range(1, 10)], 0)
    sep = combo([s for s, _v in SEPARATORS], 0)
    cg = grid([["Chapter starts with style:", heads], ["Use separator:", sep]])
    cg.set_margin_start(20)
    cg.set_sensitive(False)
    chap.connect("toggled", lambda b: cg.set_sensitive(b.get_active()))
    d.add(chap)
    d.add(cg)
    first = _section_first_para(m, name)
    try:
        off = first.PageNumberOffset
    except Exception:
        off = None
    d.add(Gtk.Label(label="Page numbering", xalign=0))
    cont = Gtk.RadioButton.new_with_mnemonic(None, "_Continue from previous section")
    start = Gtk.RadioButton.new_with_mnemonic_from_widget(cont, "Start _at:")
    spin = Gtk.SpinButton.new_with_range(0, 9999, 1)
    spin.set_value(off if isinstance(off, int) and off > 0 else 1)
    if isinstance(off, int) and off > 0:
        start.set_active(True)
    row = Gtk.Box(spacing=6)
    row.pack_start(start, False, False, 0)
    row.pack_start(spin, False, False, 0)
    d.add(cont)
    d.add(row)
    if d.ask() == Gtk.ResponseType.OK:
        um = m.getUndoManager()
        um.enterUndoContext("Page Number Format")
        try:
            ps.NumberingType = FORMATS[fmt.get_active()][1]
            for _t, _r, f in _page_fields(m, ps):
                f.NumberingType = 7          # follow the page style
            if first is not None:
                try:
                    if start.get_active():
                        if not first.PageDescName:
                            first.PageDescName = name
                        first.PageNumberOffset = int(spin.get_value())
                    else:
                        first.setPropertyToDefault("PageNumberOffset")
                except Exception as e:
                    print("page offset:", e)
            _chapter(m, ps, chap.get_active(), heads.get_active() + 1,
                     SEPARATORS[sep.get_active()][1])
        finally:
            um.leaveUndoContext()
    d.done()


def _chapter(m, ps, on, level, separator):
    """Put (or take away) "chapter-separator" in front of each page number."""
    for text, rng, f in _page_fields(m, ps):
        cur = text.createTextCursorByRange(rng.getStart())
        # existing chapter field just before?
        probe = text.createTextCursorByRange(rng.getStart())
        probe.goLeft(2, True)
        has = False
        try:
            en = probe.createEnumeration()
            while en.hasMoreElements():
                p = en.nextElement()
                pe = p.createEnumeration()
                while pe.hasMoreElements():
                    r = pe.nextElement()
                    if getattr(r, "TextPortionType", "") == "TextField" and \
                            r.TextField.supportsService("com.sun.star.text.textfield.Chapter"):
                        has = True
        except Exception:
            pass
        if has and not on:
            probe.setString("")
        elif on and not has:
            c = m.createInstance("com.sun.star.text.textfield.Chapter")
            c.Level = level - 1
            c.ChapterFormat = 1     # number only
            text.insertTextContent(cur, c, False)
            text.insertString(cur, separator, False)


def alignment_tab_dialog(win):
    """Insert Alignment Tab: a tab that lines the text up at the left,
    centre or right of the margin (or indent)."""
    from gi.repository import Gtk
    from . import bridge, docapi
    from .widgets import FDialog, combo, grid, heading
    m = win.engine.model
    if m is None:
        return
    d = FDialog(win, "Alignment Tab")
    d.add(heading("Alignment"))
    al = Gtk.Box(spacing=12)
    left = Gtk.RadioButton.new_with_mnemonic(None, "_Left")
    center = Gtk.RadioButton.new_with_mnemonic_from_widget(left, "_Center")
    right = Gtk.RadioButton.new_with_mnemonic_from_widget(left, "_Right")
    right.set_active(True)
    for w in (left, center, right):
        al.pack_start(w, False, False, 0)
    d.add(al)
    rel = combo(["Margin", "Indent"], 0)
    d.add(grid([["Ali_gn relative to:", rel]]))
    d.add(heading("Leader"))
    leaders = [("1 None", " "), ("2 .......", "."), ("3 -------", "-"), ("4 ____", "_")]
    lead = combo([n for n, _c in leaders], 0)
    d.add(lead)
    if d.ask() == Gtk.ResponseType.OK:
        try:
            vc = docapi.view_cursor(m)
            ps = docapi.page_style(m)
            width = ps.Width - ps.LeftMargin - ps.RightMargin
            c = vc.getText().createTextCursorByRange(vc.getStart())
            li = c.ParaLeftMargin if rel.get_active() == 1 else 0
            ri = c.ParaRightMargin if rel.get_active() == 1 else 0
            if left.get_active():
                pos, kind = 0, "LEFT"
            elif center.get_active():
                pos, kind = (width - li - ri) // 2, "CENTER"
            else:
                pos, kind = width - li - ri - 1, "RIGHT"
            stops = [t for t in (c.ParaTabStops or ()) if abs(t.Position - pos) > 10]
            ts = bridge.struct("com.sun.star.style.TabStop")
            ts.Position = int(pos)
            ts.Alignment = bridge.enum("com.sun.star.style.TabAlign", kind)
            ts.FillChar = leaders[max(0, lead.get_active())][1]
            stops.append(ts)
            stops.sort(key=lambda t: t.Position)
            c.ParaTabStops = tuple(stops)
            win.actions.insert_text("\t")
        except Exception as e:
            print("alignment tab:", e)
    d.done()
