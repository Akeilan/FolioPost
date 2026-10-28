"""Developer > Controls: content controls (rich text, plain text, picture,
check box, combo box, drop-down list, date picker), their Properties, and
the pickers that open when you click a drop-down or date control."""
import datetime

from gi.repository import Gdk, GLib, Gtk

from . import bridge, docapi
from .widgets import FDialog, grid

PLACEHOLDER = {"rich": "Click or tap here to enter text.",
               "plain": "Click or tap here to enter text.",
               "combo": "Choose an item.", "dropdown": "Choose an item.",
               "date": "Click or tap to enter a date.", "picture": "", "checkbox": ""}


def _native(win):
    if getattr(win.engine, "native", False):
        from .native import controls
        return controls
    return None


def insert(win, kind):
    if _native(win):
        return _native(win).insert(win, kind)
    m = win.engine.model
    if m is None:
        return

    def go():
        vc = docapi.view_cursor(m)
        text = vc.getText()
        um = m.getUndoManager()
        um.enterUndoContext("Insert Content Control")
        try:
            cc = m.createInstance("com.sun.star.text.ContentControl")
            sel = vc.getString()
            if not sel:
                if kind == "checkbox":
                    text.insertString(vc, "☐", True)
                elif kind != "picture":
                    text.insertString(vc, PLACEHOLDER[kind], True)
            rng = text.createTextCursorByRange(vc)
            if kind == "checkbox":
                cc.Checkbox = True
                cc.Checked = False
                cc.CheckedState = "☒"
                cc.UncheckedState = "☐"
            elif kind == "plain":
                cc.PlainText = True
            elif kind in ("combo", "dropdown"):
                items = ((bridge.prop("DisplayText", "Choose an item."),
                          bridge.prop("Value", "")),)
                import uno
                uno.invoke(cc, "setPropertyValue", ("ListItems", uno.Any(
                    "[][]com.sun.star.beans.PropertyValue", items)))
                if kind == "combo":
                    cc.ComboBox = True
                else:
                    cc.DropDown = True
            elif kind == "date":
                cc.Date = True
                cc.DateFormat = "M/d/yyyy"
                cc.DateLanguage = "en-US"
            elif kind == "picture":
                cc.Picture = True
            if kind not in ("checkbox", "picture") and not sel:
                cc.ShowingPlaceHolder = True
            text.insertTextContent(rng, cc, True)
            if kind == "picture":
                _insert_placeholder_picture(m, cc)
        except Exception as e:
            import traceback
            traceback.print_exc()
            win.dialogs.message("The control couldn't be inserted: %s" % e)
        finally:
            um.leaveUndoContext()
    win.engine.sync(go)


def _insert_placeholder_picture(m, cc):
    import os
    import tempfile
    try:
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (240, 180), (242, 242, 242))
        d = ImageDraw.Draw(img)
        d.rectangle([0, 0, 239, 179], outline=(166, 166, 166))
        d.polygon([(70, 130), (105, 85), (125, 110), (150, 75), (180, 130)],
                  fill=(166, 166, 166))
        d.ellipse([150, 45, 170, 65], fill=(166, 166, 166))
        path = tempfile.mktemp(suffix=".png")
        img.save(path)
        rng = cc.getText().createTextCursorByRange(cc.getStart()) if hasattr(
            cc, "getText") else None
        vc = docapi.view_cursor(m)
        if rng is not None:
            vc.gotoRange(rng, False)
        docapi.insert_picture(m, path)
        os.remove(path)
    except Exception as e:
        print("picture control:", e)


def control_at_cursor(m):
    """The content control the cursor is in, or None."""
    vc = docapi.read_cursor(m)
    try:
        cc = vc.ContentControl
        if cc is not None:
            return cc
    except Exception:
        pass
    try:
        text = vc.getText()
        here = vc.getStart()
        para = text.createTextCursorByRange(here)
        para.gotoStartOfParagraph(False)
        para.gotoEndOfParagraph(True)
        en = para.createEnumeration()
        while en.hasMoreElements():
            p = en.nextElement()
            if not p.supportsService("com.sun.star.text.Paragraph"):
                continue
            pe = p.createEnumeration()
            while pe.hasMoreElements():
                r = pe.nextElement()
                if getattr(r, "TextPortionType", "") != "ContentControl":
                    continue
                cc = r.ContentControl
                try:
                    if text.compareRegionStarts(cc.getStart(), here) >= 0 and \
                            text.compareRegionEnds(cc.getEnd(), here) <= 0:
                        return cc
                except Exception:
                    continue
    except Exception:
        pass
    return None


def kind_of(cc):
    for k, prop in (("checkbox", "Checkbox"), ("combo", "ComboBox"), ("dropdown", "DropDown"),
                    ("date", "Date"), ("picture", "Picture"), ("plain", "PlainText")):
        try:
            if getattr(cc, prop):
                return k
        except Exception:
            pass
    return "rich"


def _items(cc):
    out = []
    try:
        for item in cc.ListItems:
            d = {p.Name: p.Value for p in item}
            out.append((d.get("DisplayText", ""), d.get("Value", "")))
    except Exception:
        pass
    return out


def _set_items(cc, items):
    import uno
    seq = tuple((bridge.prop("DisplayText", t), bridge.prop("Value", v)) for t, v in items)
    uno.invoke(cc, "setPropertyValue", ("ListItems", uno.Any(
        "[][]com.sun.star.beans.PropertyValue", seq)))


def _set_text(m, cc, value):
    um = m.getUndoManager()
    um.enterUndoContext("Content Control")
    try:
        c = cc.getText().createTextCursorByRange(cc.getStart())
        c.gotoRange(cc.getEnd(), True)
        c.setString(value)
        try:
            cc.ShowingPlaceHolder = False
        except Exception:
            pass
    finally:
        um.leaveUndoContext()


def on_click(win, x, y):
    """After a click: open the list or calendar of a drop-down / date control,
    or tick a check box."""
    if _native(win):
        return _native(win).on_click(win, x, y)
    m = win.engine.model
    if m is None:
        return
    cc = control_at_cursor(m)
    if cc is None:
        return
    k = kind_of(cc)
    if k == "checkbox":
        um = m.getUndoManager()
        um.enterUndoContext("Check Box")
        try:
            on = not cc.Checked
            cc.Checked = on
            _set_text(m, cc, cc.CheckedState if on else cc.UncheckedState)
        finally:
            um.leaveUndoContext()
        return
    if k not in ("combo", "dropdown", "date"):
        if getattr(cc, "ShowingPlaceHolder", False):
            # select the placeholder so typing replaces it
            c = cc.getText().createTextCursorByRange(cc.getStart())
            c.gotoRange(cc.getEnd(), True)
            docapi.controller(m).select(c)
        return
    rect = Gdk.Rectangle()
    rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
    pop = Gtk.Popover.new(win.engine.view)
    pop.set_pointing_to(rect)
    pop.set_position(Gtk.PositionType.BOTTOM)
    if k == "date":
        cal = Gtk.Calendar()

        def picked(c):
            yv, mv, dv = c.get_date()
            dt = datetime.date(yv, mv + 1, dv)
            pop.popdown()
            win.engine.sync(lambda: _set_text(m, cc, "%d/%d/%d" % (dt.month, dt.day, dt.year)))
        cal.connect("day-selected-double-click", picked)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin=6)
        box.pack_start(cal, False, False, 0)
        today = Gtk.Button(label="Today")
        today.connect("clicked", lambda *_: (cal.select_month(
            datetime.date.today().month - 1, datetime.date.today().year),
            cal.select_day(datetime.date.today().day), picked(cal)))
        box.pack_start(today, False, False, 0)
        pop.add(box)
    else:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin=4)
        for text, _v in _items(cc):
            if text == "Choose an item." and len(_items(cc)) > 1:
                pass
            b = Gtk.ModelButton(text=text)
            b.connect("clicked", lambda _b, t=text: win.engine.sync(
                lambda: _set_text(m, cc, t)))
            box.pack_start(b, False, False, 0)
        pop.add(box)
    pop.show_all()
    pop.popup()


def properties(win):
    if _native(win):
        return _native(win).properties(win)
    m = win.engine.model
    if m is None:
        return
    cc = control_at_cursor(m)
    if cc is None:
        win.dialogs.message("Put the cursor in a content control first.")
        return
    k = kind_of(cc)
    d = FDialog(win, "Content Control Properties")
    title = Gtk.Entry(text=getattr(cc, "Alias", "") or "")
    tag = Gtk.Entry(text=getattr(cc, "Tag", "") or "")
    d.add(grid([["_Title:", title], ["T_ag:", tag]]))
    lock = Gtk.CheckButton(label="Content control cannot be deleted")
    try:
        lock.set_active(bool(cc.Lock in ("sdtLocked", "sdtContentLocked")))
    except Exception:
        pass
    d.add(lock)
    store = None
    if k in ("combo", "dropdown"):
        store = Gtk.ListStore(str, str)
        for t, v in _items(cc):
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
        add = Gtk.Button(label="Add...")
        rem = Gtk.Button(label="Remove")
        up = Gtk.Button(label="Move Up")
        down = Gtk.Button(label="Move Down")
        for b in (add, rem, up, down):
            bb.pack_start(b, False, False, 0)
        hb.pack_start(bb, False, False, 0)
        d.add(hb)

        def do_add(*_):
            t = win.dialogs.ask_text("Add Choice", "Display Name:")
            if t:
                store.append([t, t])

        def sel():
            mdl, it = tv.get_selection().get_selected()
            return it

        def do_rem(*_):
            it = sel()
            if it:
                store.remove(it)

        def move(delta):
            it = sel()
            if it is None:
                return
            other = store.iter_previous(it) if delta < 0 else store.iter_next(it)
            if other is not None:
                store.swap(it, other)
        add.connect("clicked", do_add)
        rem.connect("clicked", do_rem)
        up.connect("clicked", lambda *_: move(-1))
        down.connect("clicked", lambda *_: move(1))
    if d.ask() == Gtk.ResponseType.OK:
        def go():
            try:
                cc.Alias = title.get_text()
                cc.Tag = tag.get_text()
            except Exception:
                pass
            try:
                cc.Lock = "sdtLocked" if lock.get_active() else ""
            except Exception:
                pass
            if store is not None:
                _set_items(cc, [(r[0], r[1]) for r in store])
        win.engine.sync(go)
    d.done()
