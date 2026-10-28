"""Layout > Line Numbers and Hyphenation with the new engine."""
from gi.repository import Gtk

from ..widgets import FDialog, LengthSpin, grid

TW = 1440.0 / 2540.0
RESTART = {"continuous": "continuous", "page": "newPage", "section": "newSection"}


def _done(win):
    win.engine.view.document_changed()


def line_numbers(win, mode):
    ed = win.engine.ed
    if mode == "suppress":
        on = not ed.para_values().get("suppress_line_numbers", False)
        ed.apply_para([("w:suppressLineNumbers", [] if on else None)], "Suppress Line Numbers")
    elif mode == "none":
        ed.set_line_numbers(None)
    else:
        cur = ed.line_numbers()
        by, start, dist = (cur[1], cur[2], cur[3]) if cur else (1, 0, 0)
        ed.set_line_numbers(RESTART.get(mode, "newPage"), by, start, dist)
    _done(win)


def line_numbers_dialog(win):
    ed = win.engine.ed
    cur = ed.line_numbers()
    d = FDialog(win, "Line Numbers")
    on = Gtk.CheckButton.new_with_mnemonic("Add _line numbering")
    on.set_active(cur is not None)
    d.add(on)
    start = Gtk.SpinButton.new_with_range(1, 32767, 1)
    start.set_value((cur[2] if cur else 0) + 1)
    dist = LengthSpin((cur[3] if cur and cur[3] else 0) / TW, 0, 25400)
    auto = Gtk.CheckButton.new_with_mnemonic("_Auto")
    auto.set_active(not (cur and cur[3]))
    dist.set_sensitive(not auto.get_active())
    auto.connect("toggled", lambda b: dist.set_sensitive(not b.get_active()))
    count = Gtk.SpinButton.new_with_range(1, 100, 1)
    count.set_value(cur[1] if cur else 1)
    body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    dbox = Gtk.Box(spacing=6)
    dbox.pack_start(dist, False, False, 0)
    dbox.pack_start(auto, False, False, 0)
    body.pack_start(grid([["Start _at:", start], ["From _text:", dbox], ["Count _by:", count]]), False, False, 0)
    body.pack_start(Gtk.Label(label="Numbering:", xalign=0), False, False, 0)
    r_page = Gtk.RadioButton.new_with_mnemonic(None, "Restart each _page")
    r_sec = Gtk.RadioButton.new_with_mnemonic_from_widget(r_page, "Restart each _section")
    r_cont = Gtk.RadioButton.new_with_mnemonic_from_widget(r_page, "_Continuous")
    mode = cur[0] if cur else "newPage"
    {"newSection": r_sec, "continuous": r_cont}.get(mode, r_page).set_active(True)
    for rb in (r_page, r_sec, r_cont):
        body.pack_start(rb, False, False, 0)
    body.set_margin_start(20)
    d.add(body)
    on.connect("toggled", lambda w: body.set_sensitive(w.get_active()))
    body.set_sensitive(on.get_active())
    r = d.ask()
    vals = (on.get_active(), int(start.get_value()) - 1, 0 if auto.get_active() else int(round(dist.mm100 * TW)),
            int(count.get_value()),
            "newPage" if r_page.get_active() else "newSection" if r_sec.get_active() else "continuous")
    d.done()
    if r != Gtk.ResponseType.OK:
        return
    is_on, st, ds, by, rs = vals
    ed.set_line_numbers(rs if is_on else None, by, st, ds)
    _done(win)


def hyphenation(win, auto):
    ed = win.engine.ed
    ed.set_setting("autoHyphenation", bool(auto))
    _done(win)


def options_dialog(win):
    ed = win.engine.ed
    zone_tw, limit_n = ed.hyphenation_options()
    d = FDialog(win, "Hyphenation")
    auto = Gtk.CheckButton.new_with_mnemonic("_Automatically hyphenate document")
    auto.set_active(ed.setting("autoHyphenation"))
    caps = Gtk.CheckButton.new_with_mnemonic("Hyphenate words in _CAPS")
    caps.set_active(not ed.setting("doNotHyphenateCaps"))
    zone = LengthSpin(zone_tw / TW, 0, 25400)
    limit = Gtk.ComboBoxText.new_with_entry()
    for x in ("No limit", "1", "2", "3", "4", "5"):
        limit.append_text(x)
    limit.get_child().set_text(str(limit_n) if limit_n else "No limit")
    d.add(auto)
    d.add(caps)
    d.add(grid([["Hyphenation _zone:", zone], ["_Limit consecutive hyphens to:", limit]]))
    manual = d.add_button("_Manual...", 2)
    manual.set_use_underline(True)
    d.get_action_area().reorder_child(manual, 0)
    r = d.ask()
    t = limit.get_child().get_text().strip()
    vals = (auto.get_active(), caps.get_active(), int(round(zone.mm100 * TW)), int(t) if t.isdigit() else 0)
    d.done()
    if r in (Gtk.ResponseType.OK, 2):
        a, c, z, n = vals
        ed.set_setting("autoHyphenation", a)
        ed.set_setting("doNotHyphenateCaps", not c)
        ed.set_hyphenation_options(z, n)
        _done(win)
    if r == 2:
        manual_dialog(win)


def manual_dialog(win):
    """Manual Hyphenation: each word starting a line, offered with its
    hyphenation points; Yes puts an optional hyphen where the last '-' is."""
    ed = win.engine.ed
    seen = set()
    done = 0
    while True:
        cands = [c for c in ed.line_start_words() if (c[0], c[1]) not in seen]
        if not cands:
            break
        node, off, word = cands[0]
        seen.add((node, off))
        pts = ed.hyph_points(word)
        if not pts:
            continue
        ed.select_nodes(node, off, node, off + len(word))
        win.engine.view.after_move()
        shown = "".join(ch + ("-" if (i + 1) in pts else "") for i, ch in enumerate(word))
        d = FDialog(win, "Manual Hyphenation: English",
                    buttons=(("Yes", Gtk.ResponseType.YES), ("No", Gtk.ResponseType.NO),
                             ("Cancel", Gtk.ResponseType.CANCEL)))
        e = Gtk.Entry(text=shown)
        e.set_width_chars(30)
        d.add(grid([["Hyphenate _at:", e]]))
        r = d.ask()
        text = e.get_text()
        d.done()
        if r not in (Gtk.ResponseType.YES, Gtk.ResponseType.NO):
            break
        if r != Gtk.ResponseType.YES:
            continue
        k = len(text[:text.rfind("-")].replace("-", "")) if "-" in text else 0
        if 0 < k < len(word):
            ed.select_nodes(node, off + k, node, off + k)
            ed.type_text("­")
            done += 1
            win.engine.view.after_edit()
    win.dialogs.message("Hyphenation is complete." if done or seen else
                        "There is nothing to hyphenate.", title="Manual Hyphenation")
