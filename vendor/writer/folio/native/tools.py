"""Sort Text and Word Count with the new engine."""
from gi.repository import Gtk

from ..widgets import FDialog, combo, grid


def sort_dialog(win):
    ed = win.engine.ed
    if ed is None:
        return
    in_table = bool(ed.cell_name())
    d = FDialog(win, "Sort Text")
    sort_by = combo(["Column 1" if in_table else "Paragraphs"], 0)
    kind = combo(["Text", "Number"], 0)
    asc = Gtk.RadioButton.new_with_mnemonic(None, "_Ascending")
    desc = Gtk.RadioButton.new_with_mnemonic_from_widget(asc, "_Descending")
    order = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    order.pack_start(asc, False, False, 0)
    order.pack_start(desc, False, False, 0)
    d.add(grid([["_Sort by:", sort_by], ["T_ype:", kind], ["", order]]))
    header = Gtk.CheckButton.new_with_mnemonic("Header _row")
    header.set_sensitive(in_table)
    d.add(Gtk.Label(label="My list has", xalign=0))
    d.add(header)
    r = d.ask()
    args = (desc.get_active(), kind.get_active() == 1, header.get_active())
    d.done()
    if r != Gtk.ResponseType.OK:
        return
    if ed.sort_paras(*args):
        win.engine.view.after_edit()
    else:
        win.status.flash("Select the paragraphs or table rows to sort.")


def word_count(win):
    ed = win.engine.ed
    if ed is None:
        return
    d = FDialog(win, "Word Count", buttons=(("Close", Gtk.ResponseType.CLOSE),))
    d.add(Gtk.Label(label="Statistics:", xalign=0))
    g = Gtk.Grid(column_spacing=40, row_spacing=4)
    g.set_margin_start(12)
    d.add(g)
    inc = Gtk.CheckButton(label="Include textboxes, footnotes and endnotes")
    inc.set_active(True)
    d.add(inc)

    def fill(*_):
        for ch in g.get_children():
            g.remove(ch)
        s = ed.stats(inc.get_active())
        rows = [("Pages", s["pages"]), ("Words", s["words"]),
                ("Characters (no spaces)", s["chars"]),
                ("Characters (with spaces)", s["chars_spaces"]),
                ("Paragraphs", s["paras"]), ("Lines", s["lines"])]
        for i, (k, v) in enumerate(rows):
            g.attach(Gtk.Label(label=k, xalign=0), 0, i, 1, 1)
            g.attach(Gtk.Label(label="{:,}".format(v), xalign=1), 1, i, 1, 1)
        g.show_all()
    inc.connect("toggled", fill)
    fill()
    d.ask()
    d.done()
