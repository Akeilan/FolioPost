"""Review > Tracking launcher: Track Changes Options and Advanced Track
Changes Options (how insertions, deletions and changed lines are marked,
colours by author, balloons)."""
from gi.repository import Gtk

from . import bridge
from .widgets import FDialog, color_button, combo, grid

INSERT_MARKS = [("(none)", 0), ("Bold", 1), ("Italic", 2), ("Underline", 3),
                ("Double underline", 4)]
DELETE_MARKS = [("(none)", 0), ("Bold", 1), ("Italic", 2), ("Strikethrough", 3)]
LINE_MARKS = [("(none)", 0), ("Left border", 1), ("Right border", 2), ("Outside border", 3)]
BALLOONS = ["Revisions", "Comments and formatting", "Nothing"]
DEFAULTS = {"ins_mark": 3, "ins_color": -1, "del_mark": 3, "del_color": -1,
            "line_mark": 3, "line_color": 0, "attr_color": -1, "balloon_width": 250,
            "show_comments": True, "show_insdel": True, "show_formatting": True,
            "balloons": "Revisions"}


def options(app):
    o = app.settings.get("track_options")
    if not isinstance(o, dict):
        o = {}
    return dict(DEFAULTS, **o)


def apply(win):
    """Write the marks into the engine's settings and redraw."""
    o = options(win.app)
    try:
        import uno
        prov = bridge.create("com.sun.star.configuration.ConfigurationProvider")

        def acc(path):
            arg = uno.createUnoStruct("com.sun.star.beans.PropertyValue")
            arg.Name, arg.Value = "nodepath", path
            return prov.createInstanceWithArguments(
                "com.sun.star.configuration.ConfigurationUpdateAccess", (arg,))
        base = "/org.openoffice.Office.Writer/Revision/"
        for node, mark, color in (("TextDisplay/Insert", o["ins_mark"], o["ins_color"]),
                                  ("TextDisplay/Delete", o["del_mark"], o["del_color"]),
                                  ("TextDisplay/ChangedAttribute", 1, o["attr_color"])):
            a = acc(base + node)
            a.setPropertyValue("Attribute", int(mark))
            a.setPropertyValue("Color", int(color))
            a.commitChanges()
        a = acc(base + "LinesChanged")
        a.setPropertyValue("Mark", int(o["line_mark"]))
        a.setPropertyValue("Color", int(o["line_color"]))
        a.commitChanges()
    except Exception as e:
        print("track options:", e)
    # redraw with the new marks
    eng = win.engine
    if eng.model is not None:
        eng.command(".uno:ShowTrackedChanges")
        eng.command(".uno:ShowTrackedChanges")
    try:
        win.comments.set_width(int(o["balloon_width"]))
    except Exception:
        pass


def _color_row(value):
    by_author = Gtk.CheckButton(label="By author")
    by_author.set_active(value == -1)
    btn = color_button(value if value is not None and value >= 0 else 0x000000, lambda c: None)
    btn.set_sensitive(value != -1)
    by_author.connect("toggled", lambda b: btn.set_sensitive(not b.get_active()))
    box = Gtk.Box(spacing=6)
    box.pack_start(by_author, False, False, 0)
    box.pack_start(btn, False, False, 0)
    box.value = lambda: -1 if by_author.get_active() else (btn.color if btn.color is not None
                                                           and btn.color >= 0 else 0)
    return box


def advanced_dialog(win):
    app = win.app
    o = options(app)
    d = FDialog(win, "Advanced Track Changes Options")
    ins = combo([n for n, _v in INSERT_MARKS], next((i for i, (_n, v) in enumerate(INSERT_MARKS)
                                                     if v == o["ins_mark"]), 3))
    dele = combo([n for n, _v in DELETE_MARKS], next((i for i, (_n, v) in enumerate(DELETE_MARKS)
                                                      if v == o["del_mark"]), 3))
    lines = combo([n for n, _v in LINE_MARKS], next((i for i, (_n, v) in enumerate(LINE_MARKS)
                                                     if v == o["line_mark"]), 3))
    ic, dc = _color_row(o["ins_color"]), _color_row(o["del_color"])
    lc = color_button(o["line_color"] if o["line_color"] >= 0 else 0, lambda c: None)
    fc = _color_row(o["attr_color"])
    d.add(Gtk.Label(label="Markup", xalign=0))
    d.add(grid([["_Insertions:", ins, "Color:", ic],
                ["_Deletions:", dele, "Color:", dc],
                ["Changed _lines:", lines, "Color:", lc],
                ["Formatting color:", None, "", fc]]))
    d.add(Gtk.Label(label="Balloons", xalign=0))
    width = Gtk.SpinButton.new_with_range(150, 600, 10)
    width.set_value(o["balloon_width"])
    d.add(grid([["Preferred _width (pixels):", width]]))
    if d.ask() == Gtk.ResponseType.OK:
        o.update(ins_mark=INSERT_MARKS[ins.get_active()][1], ins_color=ic.value(),
                 del_mark=DELETE_MARKS[dele.get_active()][1], del_color=dc.value(),
                 line_mark=LINE_MARKS[lines.get_active()][1],
                 line_color=lc.color if lc.color is not None and lc.color >= 0 else 0,
                 attr_color=fc.value(), balloon_width=int(width.get_value()))
        app.settings["track_options"] = o
        app.save_settings()
        apply(win)
    d.done()


def dialog(win):
    app = win.app
    o = options(app)
    d = FDialog(win, "Track Changes Options")
    d.add(Gtk.Label(label="Show", xalign=0))
    cm = Gtk.CheckButton.new_with_mnemonic("_Comments")
    cm.set_active(o["show_comments"])
    idl = Gtk.CheckButton.new_with_mnemonic("_Insertions and Deletions")
    idl.set_active(o["show_insdel"])
    fm = Gtk.CheckButton.new_with_mnemonic("_Formatting")
    fm.set_active(o["show_formatting"])
    for w in (cm, idl, fm):
        d.add(w)
    bal = combo(BALLOONS, o["balloons"])
    d.add(grid([["_Balloons in All Markup view show:", bal]]))
    bb = Gtk.Box(spacing=6)
    adv = Gtk.Button.new_with_mnemonic("Ad_vanced Options...")
    user = Gtk.Button.new_with_mnemonic("Change _User Name...")
    adv.connect("clicked", lambda *_: advanced_dialog(win))
    user.connect("clicked", lambda *_: win.run("options"))
    bb.pack_start(adv, True, True, 0)
    bb.pack_start(user, True, True, 0)
    d.add(bb)
    if d.ask() == Gtk.ResponseType.OK:
        changed_insdel = idl.get_active() != o["show_insdel"]
        o.update(show_comments=cm.get_active(), show_insdel=idl.get_active(),
                 show_formatting=fm.get_active(), balloons=bal.get_active_text())
        app.settings["track_options"] = o
        app.save_settings()
        try:
            if win.comments.show_markup != cm.get_active():
                win.comments.set_visible(cm.get_active())
        except Exception:
            pass
        if changed_insdel:
            win.engine.command(".uno:ShowTrackedChanges")
        win.set_balloons(o["balloons"] == "Revisions")
    d.done()
