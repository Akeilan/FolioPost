"""Equation > Tools launcher: Equation Options, with the Math AutoCorrect and
Recognized Functions lists, and Math AutoCorrect outside equations."""
import re

from gi.repository import Gtk

from . import docapi
from .eqn import render as R
from .eqn import symbols as S
from .widgets import FDialog, combo, grid

FONTS = [("Caladea", "Caladea"), ("Latin Modern Roman", "Latin Modern Roman"),
         ("DejaVu Serif", "DejaVu Serif"), ("Liberation Serif", "Liberation Serif"),
         ("TeX Gyre Termes", "TeX Gyre Termes"), ("Noto Serif", "Noto Serif")]
JUSTIFY = [("group", "Centered as Group"), ("centered", "Centered"), ("left", "Left"),
           ("right", "Right")]
_WORD = re.compile(r"\\([A-Za-z]+)$")


def options(app):
    o = app.settings.get("eq_options")
    if not isinstance(o, dict):
        o = {}
        app.settings["eq_options"] = o
    return o


def apply(app):
    """Bring the saved options into effect (font, user words, functions)."""
    o = options(app)
    font = o.get("font", "Caladea")
    R.set_family(font)
    docapi.MATH_TEXT_FONT[0] = font
    for k, v in o.get("autocorrect", {}).items():
        S.CONTROL_WORDS[k] = v
    for k in o.get("removed_words", []):
        S.CONTROL_WORDS.pop(k, None)
    for f in o.get("functions", []):
        S.FUNCTIONS.add(f)
    for f in o.get("removed_functions", []):
        S.FUNCTIONS.discard(f)


def _installed(name):
    try:
        from gi.repository import PangoCairo
        fm = PangoCairo.FontMap.get_default()
        return any(f.get_name() == name for f in fm.list_families())
    except Exception:
        return name == "Caladea"


def dialog(win):
    app = win.app
    o = options(app)
    d = FDialog(win, "Equation Options")
    fonts = [label for name, label in FONTS if _installed(name)] or ["Caladea"]
    font = combo(fonts, o.get("font", "Caladea"))
    d.add(grid([["Default font for math regions:", font]]))
    auto = Gtk.CheckButton(label="Automatically convert expressions to Professional format")
    auto.set_active(o.get("autobuild", True))
    small = Gtk.CheckButton(label="Reduce size of nested fractions in display equations")
    small.set_active(o.get("small_fractions", True))
    outside = Gtk.CheckButton(label="Use Math AutoCorrect rules outside of math regions")
    outside.set_active(o.get("outside", False))
    for w in (auto, small):
        d.add(w)
    frame = Gtk.Frame(label="Display Math")
    inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=8)
    just = combo([label for _k, label in JUSTIFY],
                 dict(JUSTIFY).get(o.get("justify", "group"), "Centered as Group"))
    inner.pack_start(grid([["Default justification:", just]]), False, False, 0)
    frame.add(inner)
    d.add(frame)
    d.add(outside)
    bb = Gtk.Box(spacing=6)
    ac = Gtk.Button(label="Math AutoCorrect...")
    fn = Gtk.Button(label="Recognized Functions...")
    ac.connect("clicked", lambda *_: autocorrect_dialog(win))
    fn.connect("clicked", lambda *_: functions_dialog(win))
    bb.pack_start(ac, False, False, 0)
    bb.pack_start(fn, False, False, 0)
    d.add(bb)
    if d.ask() == Gtk.ResponseType.OK:
        o["font"] = font.get_active_text() or "Caladea"
        o["autobuild"] = auto.get_active()
        o["small_fractions"] = small.get_active()
        o["outside"] = outside.get_active()
        lab = just.get_active_text()
        o["justify"] = next((k for k, label in JUSTIFY if label == lab), "group")
        app.save_settings()
        apply(app)
        if win.eqbar.ed.active:
            win.eqbar.ed._ensure_fonts()
            win.eqbar.ed.changed()
    d.done()


def _list_dialog(win, title, rows, cols, on_save):
    d = FDialog(win, title)
    store = Gtk.ListStore(*([str] * len(cols)))
    for r in rows:
        store.append(list(r))
    tv = Gtk.TreeView(model=store)
    for i, h in enumerate(cols):
        tv.append_column(Gtk.TreeViewColumn(h, Gtk.CellRendererText(), text=i))
    sw = Gtk.ScrolledWindow()
    sw.set_size_request(360, 280)
    sw.add(tv)
    entries = [Gtk.Entry() for _c in cols]
    row = Gtk.Box(spacing=6)
    for c, e in zip(cols, entries):
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        v.pack_start(Gtk.Label(label=c + ":", xalign=0), False, False, 0)
        v.pack_start(e, False, False, 0)
        row.pack_start(v, True, True, 0)
    d.add(row)
    d.add(sw, expand=True)
    add = Gtk.Button(label="Add")
    rem = Gtk.Button(label="Delete")
    btns = Gtk.Box(spacing=6)
    btns.pack_end(rem, False, False, 0)
    btns.pack_end(add, False, False, 0)
    d.add(btns)

    def picked(sel):
        mdl, it = sel.get_selected()
        if it is not None:
            for i, e in enumerate(entries):
                e.set_text(mdl[it][i])
    tv.get_selection().connect("changed", picked)

    def do_add(*_):
        vals = [e.get_text().strip().lstrip("\\") if i == 0 else e.get_text()
                for i, e in enumerate(entries)]
        if not vals[0]:
            return
        for r in store:
            if r[0] == vals[0]:
                for i, v in enumerate(vals):
                    r[i] = v
                return
        store.append(vals)

    def do_rem(*_):
        mdl, it = tv.get_selection().get_selected()
        if it is not None:
            store.remove(it)
    add.connect("clicked", do_add)
    rem.connect("clicked", do_rem)
    if d.ask() == Gtk.ResponseType.OK:
        on_save([tuple(r) for r in store])
    d.done()


def autocorrect_dialog(win):
    app = win.app
    o = options(app)
    rows = sorted(("\\" + k, v) for k, v in S.CONTROL_WORDS.items())

    def save(new):
        new = {k.lstrip("\\"): v for k, v in new}
        added = {k: v for k, v in new.items() if S.CONTROL_WORDS.get(k) != v}
        removed = [k for k in S.CONTROL_WORDS if k not in new]
        o.setdefault("autocorrect", {}).update(added)
        o["removed_words"] = sorted(set(o.get("removed_words", [])) | set(removed))
        for k in removed:
            o["autocorrect"].pop(k, None)
        app.save_settings()
        apply(app)
    _list_dialog(win, "Math AutoCorrect", rows, ["Replace", "With"], save)


def functions_dialog(win):
    app = win.app
    o = options(app)
    rows = sorted((f,) for f in S.FUNCTIONS)

    def save(new):
        names = {r[0] for r in new}
        o["functions"] = sorted(names - S.FUNCTIONS | set(o.get("functions", [])) & names)
        o["removed_functions"] = sorted(S.FUNCTIONS - names)
        app.save_settings()
        apply(app)
    _list_dialog(win, "Recognized Math Functions", rows, ["Function"], save)


def outside_math(win):
    """Space typed in ordinary text: \\alpha -> α when the option is on."""
    if not options(win.app).get("outside"):
        return
    m = win.engine.model
    if m is None:
        return
    try:
        vc = docapi.read_cursor(m)
        if not vc.isCollapsed():
            return
        cur = vc.getText().createTextCursorByRange(vc.getStart())
        cur.goLeft(30, True)
        mt = _WORD.search(cur.getString())
        if not mt:
            return
        sym = S.CONTROL_WORDS.get(mt.group(1))
        if not sym:
            return
        rng = vc.getText().createTextCursorByRange(vc.getStart())
        rng.goLeft(len(mt.group(0)), True)
        rng.setString(sym)
    except Exception as e:
        print("math autocorrect:", e)
