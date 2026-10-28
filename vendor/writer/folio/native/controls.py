"""Developer > Controls with the new engine: content controls kept as Word
keeps them (w:sdt), their Properties, and the list, calendar and check box
they answer clicks with."""
import datetime
import re
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape, quoteattr

from gi.repository import Gdk, GLib, Gtk

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W14 = "http://schemas.microsoft.com/office/word/2010/wordml"
NS = 'xmlns:w="%s" xmlns:w14="%s"' % (W, W14)
PLACEHOLDER = {"rich": "Click or tap here to enter text.",
               "plain": "Click or tap here to enter text.",
               "combo": "Choose an item.", "dropdown": "Choose an item.",
               "date": "Click or tap to enter a date.", "picture": "", "checkbox": ""}
CHECKED, UNCHECKED = "☒", "☐"


def _ed(win):
    return win.engine.ed


def _done(win):
    win.engine.view.after_edit()


# ---------------------------------------------------------------- sdtPr
def _type_xml(kind):
    if kind == "plain":
        return "<w:text/>"
    if kind == "picture":
        return "<w:picture/>"
    if kind == "checkbox":
        return ('<w14:checkbox><w14:checked w14:val="0"/>'
                '<w14:checkedState w14:val="2612" w14:font="MS Gothic"/>'
                '<w14:uncheckedState w14:val="2610" w14:font="MS Gothic"/></w14:checkbox>')
    if kind in ("combo", "dropdown"):
        tag = "w:comboBox" if kind == "combo" else "w:dropDownList"
        return '<%s><w:listItem w:displayText="Choose an item." w:value=""/></%s>' % (tag, tag)
    if kind == "date":
        return ('<w:date><w:dateFormat w:val="M/d/yyyy"/><w:lid w:val="en-US"/>'
                '<w:storeMappedDataAs w:val="dateTime"/><w:calendar w:val="gregorian"/></w:date>')
    return ""


def _parse(pr):
    try:
        return ET.fromstring(pr.replace("<w:sdtPr", "<w:sdtPr %s" % NS, 1)
                             if "xmlns:w=" not in pr else pr)
    except ET.ParseError:
        return None


def _q(tag):
    p, n = tag.split(":")
    return "{%s}%s" % (W14 if p == "w14" else W, n)


def info(ed, cid):
    """{kind, title, tag, lock, items [(text, value)], checked, format, placeholder}"""
    pr = ed.control_pr(cid) or ""
    root = _parse(pr)
    d = {"id": cid, "kind": "rich", "title": "", "tag": "", "lock": "", "items": [],
         "checked": False, "format": "M/d/yyyy", "placeholder": ed.showing_placeholder(cid),
         "color": None, "style": None, "remove": False}
    if root is None:
        return d
    for k, tag in (("title", "w:alias"), ("tag", "w:tag"), ("lock", "w:lock")):
        e = root.find(_q(tag))
        if e is not None:
            d[k] = e.get(_q("w:val"), "")
    if root.find(_q("w:temporary")) is not None:
        d["remove"] = True
    st = root.find(_q("w:rPr") + "/" + _q("w:rStyle"))
    if st is not None:
        d["style"] = st.get(_q("w:val"))
    if root.find(_q("w:text")) is not None:
        d["kind"] = "plain"
    elif root.find(_q("w:picture")) is not None:
        d["kind"] = "picture"
    elif root.find(_q("w14:checkbox")) is not None:
        d["kind"] = "checkbox"
        c = root.find(_q("w14:checkbox") + "/" + _q("w14:checked"))
        d["checked"] = c is not None and c.get(_q("w14:val")) in ("1", "true")
        for k, tag in (("on", "w14:checkedState"), ("off", "w14:uncheckedState")):
            s = root.find(_q("w14:checkbox") + "/" + _q(tag))
            if s is not None:
                try:
                    d[k] = chr(int(s.get(_q("w14:val"), "0"), 16))
                except ValueError:
                    pass
    elif root.find(_q("w:date")) is not None:
        d["kind"] = "date"
        f = root.find(_q("w:date") + "/" + _q("w:dateFormat"))
        if f is not None:
            d["format"] = f.get(_q("w:val"), d["format"])
    else:
        for kind, tag in (("combo", "w:comboBox"), ("dropdown", "w:dropDownList")):
            e = root.find(_q(tag))
            if e is not None:
                d["kind"] = kind
                d["items"] = [(li.get(_q("w:displayText"), li.get(_q("w:value"), "")),
                               li.get(_q("w:value"), "")) for li in e.findall(_q("w:listItem"))]
    return d


def _set_child(pr, tag, xml, before=("w:id", "w:lock", "w:placeholder", "w:temporary",
                                     "w:showingPlcHdr")):
    """Replace (or with xml None remove) a direct child of an sdtPr XML string."""
    pr = re.sub(r"<%s\b[^>]*/>|<%s\b[^>]*>.*?</%s>" % (tag, tag, tag), "", pr, count=1, flags=re.S)
    if xml is None:
        return pr
    # schema order: rPr, alias, tag, id, lock, ...
    order = ["w:rPr", "w:alias", "w:tag", "w:id", "w:lock", "w:placeholder", "w:temporary",
             "w:showingPlcHdr"]
    later = order[order.index(tag) + 1:] if tag in order else []
    for t in later:
        m = re.search(r"<%s\b" % t, pr)
        if m:
            return pr[:m.start()] + xml + pr[m.start():]
    m = re.search(r"<w:sdtPr\b[^>]*>", pr)
    if not m:
        return pr
    # after the elements that come before it
    pos = m.end()
    for t in order[:order.index(tag)] if tag in order else order:
        mm = re.search(r"<%s\b[^>]*/>|<%s\b[^>]*>.*?</%s>" % (t, t, t), pr, flags=re.S)
        if mm:
            pos = max(pos, mm.end())
    return pr[:pos] + xml + pr[pos:]


# ---------------------------------------------------------------- insert
def insert(win, kind):
    ed = _ed(win)
    if ed is None:
        return
    pr = "<w:sdtPr>%s</w:sdtPr>" % _type_xml(kind)
    sel = ed.has_selection()
    if kind == "picture" and not sel:
        p, off = ed.caret_pos()
        path = _placeholder_picture()
        if path:
            from .objects import insert_picture_path
            if insert_picture_path(win, path):
                ed.select_nodes(p, off, p, off + 1)
            import os
            os.remove(path)
        sel = ed.has_selection()
    text = UNCHECKED if kind == "checkbox" else ("" if sel else PLACEHOLDER[kind])
    if kind != "checkbox" and not sel:
        # the flag goes before the type element
        pr = "<w:sdtPr><w:showingPlcHdr/>%s</w:sdtPr>" % _type_xml(kind)
    if kind == "checkbox" and sel:
        win.dialogs.message("A check box control goes in at the cursor.")
        return
    cid = ed.insert_content_control(pr, text)
    if cid is None:
        win.status.flash("Select text in one paragraph for the content control.")
        return
    if kind == "checkbox":
        ed.set_control_text(cid, UNCHECKED, False)
        p, a, b = ed.control_range(cid)
        ed.select_nodes(p, b, p, b)
    _done(win)


def _placeholder_picture():
    import tempfile
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    img = Image.new("RGB", (240, 180), (242, 242, 242))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 239, 179], outline=(166, 166, 166))
    d.polygon([(70, 130), (105, 85), (125, 110), (150, 75), (180, 130)], fill=(166, 166, 166))
    d.ellipse([150, 45, 170, 65], fill=(166, 166, 166))
    fd, path = tempfile.mkstemp(suffix=".png", prefix="folio-cc-")
    import os
    os.close(fd)
    img.save(path)
    return path


# ---------------------------------------------------------------- clicks
def toggle_check(win, cid):
    ed = _ed(win)
    d = info(ed, cid)
    on = not d["checked"]
    pr = ed.control_pr(cid)
    pr = re.sub(r'(<w14:checked\b[^>]*w14:val=")[^"]*(")', r"\g<1>%d\g<2>" % int(on), pr)
    ed.set_control_pr(cid, pr)
    ed.set_control_text(cid, d.get("on", CHECKED) if on else d.get("off", UNCHECKED), False)
    p, a, b = ed.control_range(cid)
    ed.select_nodes(p, b, p, b)
    _done(win)


def choose(win, cid, text, value=None):
    """A drop-down / combo item, or a date, into the control."""
    ed = _ed(win)
    ed.set_control_text(cid, text, False)
    if value is not None:
        pr = ed.control_pr(cid)
        if "<w:date" in pr:
            pr = re.sub(r'\sw:fullDate="[^"]*"', "", pr)
            pr = pr.replace("<w:date", '<w:date w:fullDate="%s"' % value, 1)
            ed.set_control_pr(cid, pr)
    p, a, b = ed.control_range(cid)
    ed.select_nodes(p, b, p, b)
    _done(win)


def _date_text(d, fmt):
    """A date in Word's date picture (M/d/yyyy, dddd, MMMM d, yyyy...)."""
    def one(m):
        t = m.group()
        return {"yyyy": "%04d" % d.year, "yy": "%02d" % (d.year % 100), "MMMM": d.strftime("%B"),
                "MMM": d.strftime("%b"), "MM": "%02d" % d.month, "M": str(d.month),
                "dddd": d.strftime("%A"), "ddd": d.strftime("%a"), "dd": "%02d" % d.day,
                "d": str(d.day)}.get(t, t)
    return re.sub(r"yyyy|yy|MMMM|MMM|MM|M|dddd|ddd|dd|d", one, fmt)


def on_click(win, x, y):
    ed = _ed(win)
    if ed is None or ed.has_selection():
        return
    cid = ed.control_at_caret()
    if cid is None:
        return
    d = info(ed, cid)
    if d["kind"] == "checkbox":
        toggle_check(win, cid)
        return
    if d["placeholder"] and d["kind"] not in ("combo", "dropdown", "date"):
        # select the placeholder: typing replaces it
        ed.select_control(cid)
        win.engine.view.after_move()
        return
    if d["kind"] not in ("combo", "dropdown", "date"):
        return
    rect = Gdk.Rectangle()
    rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
    pop = Gtk.Popover.new(win.engine.view)
    pop.set_pointing_to(rect)
    pop.set_position(Gtk.PositionType.BOTTOM)
    if d["kind"] == "date":
        cal = Gtk.Calendar()

        def picked(c):
            yv, mv, dv = c.get_date()
            dt = datetime.date(yv, mv + 1, dv)
            pop.popdown()
            choose(win, cid, _date_text(dt, d["format"]), dt.strftime("%Y-%m-%dT00:00:00Z"))
        cal.connect("day-selected-double-click", picked)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin=6)
        box.pack_start(cal, False, False, 0)
        today = Gtk.Button(label="Today")

        def go_today(*_):
            t = datetime.date.today()
            cal.select_month(t.month - 1, t.year)
            cal.select_day(t.day)
            picked(cal)
        today.connect("clicked", go_today)
        box.pack_start(today, False, False, 0)
        pop.add(box)
    else:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin=4)
        for text, _v in d["items"]:
            b = Gtk.ModelButton(text=text)
            b.connect("clicked", lambda _b, t=text: choose(win, cid, t) if t != "Choose an item."
                      else (ed.set_control_text(cid, t, True), _done(win)))
            box.pack_start(b, False, False, 0)
        pop.add(box)
    pop.show_all()
    pop.popup()
    win._cc_popover = pop


# ---------------------------------------------------------------- properties
def apply_properties(ed, cid, title=None, tag=None, lock=None, items=None, fmt=None,
                     remove_when_edited=None, on=None, off=None):
    pr = ed.control_pr(cid) or ""
    if title is not None:
        pr = _set_child(pr, "w:alias", '<w:alias w:val=%s/>' % quoteattr(title) if title else None)
    if tag is not None:
        pr = _set_child(pr, "w:tag", '<w:tag w:val=%s/>' % quoteattr(tag) if tag else None)
    if lock is not None:
        pr = _set_child(pr, "w:lock", '<w:lock w:val="%s"/>' % lock if lock else None)
    if remove_when_edited is not None:
        pr = _set_child(pr, "w:temporary", "<w:temporary/>" if remove_when_edited else None)
    if items is not None:
        tag_name = "w:comboBox" if "<w:comboBox" in pr else "w:dropDownList"
        li = "".join('<w:listItem w:displayText=%s w:value=%s/>' % (quoteattr(t), quoteattr(v))
                     for t, v in items)
        pr = re.sub(r"<%s\b[^>]*/>|<%s\b[^>]*>.*?</%s>" % (tag_name, tag_name, tag_name),
                    "<%s>%s</%s>" % (tag_name, li, tag_name), pr, count=1, flags=re.S)
    if fmt is not None:
        pr = re.sub(r'(<w:dateFormat w:val=")[^"]*(")', lambda m: m.group(1) + escape(fmt) + m.group(2), pr)
    for which, ch in (("checkedState", on), ("uncheckedState", off)):
        if ch:
            pr = re.sub(r'(<w14:%s w14:val=")[^"]*(")' % which, r"\g<1>%04X\g<2>" % ord(ch), pr)
    return ed.set_control_pr(cid, pr)


def properties(win):
    from ..widgets import FDialog, grid
    ed = _ed(win)
    cid = ed.control_at_caret() if ed is not None else None
    if cid is None:
        win.dialogs.message("Put the cursor in a content control first.")
        return
    d0 = info(ed, cid)
    k = d0["kind"]
    d = FDialog(win, "Content Control Properties")
    title = Gtk.Entry(text=d0["title"])
    tag = Gtk.Entry(text=d0["tag"])
    d.add(grid([["_Title:", title], ["T_ag:", tag]]))
    temp = Gtk.CheckButton(label="Remove content control when contents are edited")
    temp.set_active(d0["remove"])
    d.add(temp)
    d.add(Gtk.Label(label="Locking", xalign=0))
    nodel = Gtk.CheckButton(label="Content control cannot be deleted")
    noedit = Gtk.CheckButton(label="Contents cannot be edited")
    nodel.set_active(d0["lock"] in ("sdtLocked", "sdtContentLocked"))
    noedit.set_active(d0["lock"] in ("contentLocked", "sdtContentLocked"))
    d.add(nodel)
    d.add(noedit)
    store = None
    fmt = None
    on_e = off_e = None
    if k in ("combo", "dropdown"):
        store = Gtk.ListStore(str, str)
        for t, v in d0["items"]:
            store.append([t, v])
        tv = Gtk.TreeView(model=store)
        for i, h in enumerate(("Display Name", "Value")):
            cell = Gtk.CellRendererText(editable=True)
            cell.connect("edited", lambda c, p, t, i=i: store.__getitem__(p).__setitem__(i, t))
            tv.append_column(Gtk.TreeViewColumn(h, cell, text=i))
        sw = Gtk.ScrolledWindow()
        sw.set_size_request(360, 150)
        sw.add(tv)
        d.add(Gtk.Label(label="Drop-Down List Properties", xalign=0))
        hb = Gtk.Box(spacing=6)
        hb.pack_start(sw, True, True, 0)
        bb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        for label, fn in (("Add...", lambda *_: _add(win, store)),
                          ("Remove", lambda *_: _sel(tv) and store.remove(_sel(tv))),
                          ("Move Up", lambda *_: _move(tv, store, -1)),
                          ("Move Down", lambda *_: _move(tv, store, 1))):
            b = Gtk.Button(label=label)
            b.connect("clicked", fn)
            bb.pack_start(b, False, False, 0)
        hb.pack_start(bb, False, False, 0)
        d.add(hb)
    elif k == "date":
        fmt = Gtk.ComboBoxText.new_with_entry()
        for f in ("M/d/yyyy", "dddd, MMMM d, yyyy", "MMMM d, yyyy", "M/d/yy", "yyyy-MM-dd",
                  "d-MMM-yy", "M.d.yyyy", "MMM. d, yy", "d MMMM yyyy", "MMMM yy", "MMM-yy"):
            fmt.append_text(f)
        fmt.get_child().set_text(d0["format"])
        d.add(Gtk.Label(label="Date Picker Properties", xalign=0))
        d.add(grid([["_Display the date like this:", fmt]]))
    elif k == "checkbox":
        on_e = Gtk.Entry(text=d0.get("on", CHECKED), max_length=1, width_chars=3)
        off_e = Gtk.Entry(text=d0.get("off", UNCHECKED), max_length=1, width_chars=3)
        d.add(Gtk.Label(label="Check Box Properties", xalign=0))
        d.add(grid([["Checked symbol:", on_e], ["Unchecked symbol:", off_e]]))
    if d.ask() == Gtk.ResponseType.OK:
        lock = {(True, True): "sdtContentLocked", (True, False): "sdtLocked",
                (False, True): "contentLocked", (False, False): ""}[(nodel.get_active(), noedit.get_active())]
        apply_properties(ed, cid, title.get_text(), tag.get_text(), lock,
                         [(r[0], r[1]) for r in store] if store is not None else None,
                         fmt.get_child().get_text() if fmt is not None else None,
                         temp.get_active(),
                         on_e.get_text() if on_e else None, off_e.get_text() if off_e else None)
        _done(win)
    d.done()


def _sel(tv):
    _m, it = tv.get_selection().get_selected()
    return it


def _add(win, store):
    t = win.dialogs.ask_text("Add Choice", "Display Name:")
    if t:
        store.append([t, t])


def _move(tv, store, delta):
    it = _sel(tv)
    if it is None:
        return
    other = store.iter_previous(it) if delta < 0 else store.iter_next(it)
    if other is not None:
        store.swap(it, other)
