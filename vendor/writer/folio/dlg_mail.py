"""Mailings dialogs and the Mailings tab's actions."""
import csv
import os

from gi.repository import GLib, Gtk

from . import mailings as _mailings


def _native(win):
    return getattr(win.engine, "native", False)


def _M(win):
    if _native(win):
        from .native import mailmerge
        return mailmerge
    return _mailings


def _m(win):
    """What the mailings functions work on: the window (new engine, once its
    document is open) or the old engine's document."""
    if _native(win):
        return win if win.engine.ed is not None else None
    return win.engine.model
from .widgets import FDialog, Preview, combo, grid, heading

NEW_LIST_COLUMNS = ["Title", "First Name", "Last Name", "Company Name", "Address Line 1",
                    "Address Line 2", "City", "State", "ZIP Code", "Country or Region",
                    "Home Phone", "Work Phone", "E-mail Address"]


def _textview(text="", height=90):
    tv = Gtk.TextView()
    tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
    tv.get_buffer().set_text(text)
    sw = Gtk.ScrolledWindow()
    sw.set_size_request(380, height)
    sw.set_shadow_type(Gtk.ShadowType.IN)
    sw.add(tv)
    return tv, sw


def _get(tv):
    b = tv.get_buffer()
    return b.get_text(b.get_start_iter(), b.get_end_iter(), False)


def _selected_text(win):
    if _native(win):
        return win.engine.ed.selected_text() if win.engine.ed is not None else ""
    m = _m(win)
    if m is None:
        return ""
    try:
        from . import docapi
        return docapi.read_cursor(m).getString()
    except Exception:
        return ""


# ------------------------------------------------------------------ envelopes
def envelopes(win):
    m = _m(win)
    if m is None:
        return
    st = win.app.settings
    d = FDialog(win, "Envelopes and Labels",
                buttons=(("Add to Document", 1), ("Print...", 2),
                         ("Cancel", Gtk.ResponseType.CANCEL)))
    d.add(heading("Envelopes"))
    d.add(Gtk.Label(label="Delivery address:", xalign=0))
    dtv, dsw = _textview(_selected_text(win))
    d.add(dsw)
    d.add(Gtk.Label(label="Return address:", xalign=0))
    rtv, rsw = _textview(st.get("return_address", ""), 70)
    d.add(rsw)
    omit = Gtk.CheckButton.new_with_mnemonic("_Omit")
    d.add(omit)
    tabs = Gtk.Box(spacing=8)
    to_labels = Gtk.Button(label="_Labels...", use_underline=True)
    to_labels.set_tooltip_text("Envelopes and Labels: the Labels tab")
    to_labels.connect("clicked", lambda *_: (d.response(Gtk.ResponseType.CANCEL),
                                             GLib.idle_add(lambda: (labels(win), False)[1])))
    epost = Gtk.Button(label="E-postage Properties...")
    epost.set_sensitive(False)
    epost.set_tooltip_text("E-postage isn't available in Folio Writer.")
    tabs.pack_start(to_labels, False, False, 0)
    tabs.pack_start(epost, False, False, 0)
    d.add(tabs)
    size = combo([e[0] for e in _M(win).ENVELOPES], st.get("envelope_size", 0))
    d.add(grid([["Envelope _size:", size]]))
    # preview and feed, as in the original
    pf = Gtk.Box(spacing=16)

    def draw_env(cr, W, H):
        idx = max(0, size.get_active())
        _n, ew, eh = _M(win).ENVELOPES[idx]
        ew, eh = max(ew, eh), min(ew, eh)
        s_ = min((W - 10) / ew, (H - 10) / eh)
        x0, y0 = (W - ew * s_) / 2, (H - eh * s_) / 2
        cr.set_source_rgb(1, 1, 1)
        cr.rectangle(x0, y0, ew * s_, eh * s_)
        cr.fill_preserve()
        cr.set_source_rgb(0.4, 0.4, 0.4)
        cr.set_line_width(1)
        cr.stroke()
        cr.set_source_rgb(0.3, 0.3, 0.3)
        if not omit.get_active():
            for i in range(min(3, len(_get(rtv).splitlines()) or 2)):
                cr.rectangle(x0 + 6, y0 + 6 + i * 5, ew * s_ * 0.25, 2)
        for i in range(min(4, len(_get(dtv).splitlines()) or 3)):
            cr.rectangle(x0 + ew * s_ * 0.42, y0 + eh * s_ * 0.45 + i * 5, ew * s_ * 0.3, 2)
        cr.fill()

    def draw_feed(cr, W, H):
        feed = st.get("envelope_feed", 0)
        cr.set_source_rgb(0.85, 0.85, 0.85)
        cr.rectangle(8, H - 22, W - 16, 14)          # the printer tray
        cr.fill()
        ew, eh = W * 0.45, H * 0.45
        x = [8, (W - ew) / 2, W - ew - 8][feed % 3]
        cr.set_source_rgb(1, 1, 1)
        cr.rectangle(x, H - 22 - eh, ew, eh)
        cr.fill_preserve()
        cr.set_source_rgb(0.3, 0.3, 0.3)
        cr.stroke()
        cr.move_to(x + ew / 2, H - 26 - eh)
        cr.line_to(x + ew / 2 - 5, H - 18 - eh)
        cr.line_to(x + ew / 2 + 5, H - 18 - eh)
        cr.close_path()
        cr.fill()
    for title, fn in (("Preview", draw_env), ("Feed", draw_feed)):
        vb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        vb.pack_start(Gtk.Label(label=title, xalign=0), False, False, 0)
        pv = Preview(fn, 150, 90)
        vb.pack_start(pv, False, False, 0)
        pf.pack_start(vb, False, False, 0)
        size.connect("changed", lambda *_a, pv=pv: pv.queue_draw())
        omit.connect("toggled", lambda *_a, pv=pv: pv.queue_draw())
    d.add(pf)
    optb = d.add_button("_Options...", 3)
    optb.set_use_underline(True)
    d.get_action_area().reorder_child(optb, 0)
    d.show_all()
    while True:
        r = d.ask()
        if r == 3:
            envelope_options(d, st, size)
            pf.queue_draw()
            continue
        break
    if r in (1, 2):
        st["return_address"] = _get(rtv)
        st["envelope_size"] = max(0, size.get_active())
        win.app.save_settings()
        delivery, ret, idx, om = _get(dtv), _get(rtv), max(0, size.get_active()), omit.get_active()
        eopts = dict(st.get("envelope_opts") or {})
        if r == 1:
            win.engine.sync(lambda: _M(win).envelope(m, delivery, ret, idx, om, eopts))
        else:
            w = win.app.new_window()

            def fill():
                if _m(w) is None:
                    return True
                _M(win).envelope(_m(w), delivery, ret, idx, om, eopts)
                GLib.timeout_add(600, lambda: (w.run("backstage-print"), False)[1])
                return False
            GLib.timeout_add(800, fill)
    d.done()


def envelope_options(parent, st, size_combo=None):
    """Envelope Options: size, address fonts and positions; printing
    options (feed method, face up / down, rotation)."""
    from .widgets import LengthSpin
    o = dict(st.get("envelope_opts") or {})
    d = FDialog(parent, "Envelope Options")
    nb = Gtk.Notebook()
    d.add(nb)
    p1 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    p1.set_border_width(10)
    size = combo([e[0] for e in _M(win).ENVELOPES],
                 size_combo.get_active() if size_combo is not None else
                 st.get("envelope_size", 0))
    p1.pack_start(grid([["Envelope _size:", size]]), False, False, 0)
    widgets = {}
    for key, title in (("delivery", "Delivery address"), ("return", "Return address")):
        p1.pack_start(heading(title), False, False, 0)
        f = o.get(key + "_font") or ["", 0]
        fbtn = Gtk.FontButton()
        if f[0]:
            fbtn.set_font("%s %g" % (f[0], f[1] or 11))
        auto_l = Gtk.CheckButton(label="Auto")
        auto_t = Gtk.CheckButton(label="Auto")
        left = LengthSpin(o.get(key + "_left") or 2540, 0, 60000)
        top = LengthSpin(o.get(key + "_top") or 2540, 0, 60000)
        auto_l.set_active(o.get(key + "_left") is None)
        auto_t.set_active(o.get(key + "_top") is None)
        auto_l.connect("toggled", lambda b, w=left: w.set_sensitive(not b.get_active()))
        auto_t.connect("toggled", lambda b, w=top: w.set_sensitive(not b.get_active()))
        left.set_sensitive(not auto_l.get_active())
        top.set_sensitive(not auto_t.get_active())
        p1.pack_start(grid([["_Font...", fbtn], ["From left:", left, auto_l],
                            ["From top:", top, auto_t]]), False, False, 0)
        widgets[key] = (fbtn, left, top, auto_l, auto_t)
    nb.append_page(p1, Gtk.Label(label="Envelope Options"))
    p2 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    p2.set_border_width(10)
    p2.pack_start(heading("Feed method"), False, False, 0)
    feed = combo(["Left, face up", "Center, face up", "Right, face up", "Left, face down",
                  "Center, face down", "Right, face down"], st.get("envelope_feed", 0))
    rot = Gtk.CheckButton.new_with_mnemonic("C_lockwise rotation")
    rot.set_active(bool(st.get("envelope_rotate", False)))
    p2.pack_start(feed, False, False, 0)
    p2.pack_start(rot, False, False, 0)
    p2.pack_start(grid([["_Feed from:", combo(["Default tray (Automatically Select)",
                                                "Manual Feed"], 0)]]), False, False, 0)
    nb.append_page(p2, Gtk.Label(label="Printing Options"))
    d.show_all()
    if d.ask() == Gtk.ResponseType.OK:
        from gi.repository import Pango
        for key, (fbtn, left, top, auto_l, auto_t) in widgets.items():
            fd = Pango.FontDescription.from_string(fbtn.get_font() or "")
            fam = fd.get_family() or ""
            sz = fd.get_size() / Pango.SCALE if fd.get_size() else 0
            o[key + "_font"] = [fam, sz] if fam else None
            o[key + "_left"] = None if auto_l.get_active() else left.mm100
            o[key + "_top"] = None if auto_t.get_active() else top.mm100
        st["envelope_opts"] = o
        st["envelope_feed"] = max(0, feed.get_active())
        st["envelope_rotate"] = rot.get_active()
        if size_combo is not None:
            size_combo.set_active(size.get_active())
        st["envelope_size"] = max(0, size.get_active())
    d.destroy()


# ------------------------------------------------------------------ labels
def label_options(win, current=0):
    d = FDialog(win, "Label Options")
    lst = combo([l[0] for l in _M(win).LABELS], current)
    d.add(grid([["_Product:", lst]]))
    info = Gtk.Label(xalign=0)
    info.get_style_context().add_class("dim-label")

    def upd(*_):
        l = _M(win).LABELS[max(0, lst.get_active())]
        info.set_text("Label size: %.2f x %.2f cm   Page: %.1f x %.1f cm   %d x %d" % (
            l[3] / 1000, l[4] / 1000, l[1] / 1000, l[2] / 1000, l[5], l[6]))
    lst.connect("changed", upd)
    upd()
    d.add(info)
    r = d.ask()
    out = max(0, lst.get_active()) if r == Gtk.ResponseType.OK else None
    d.done()
    return out


def labels(win):
    m = _m(win)
    if m is None:
        return
    st = win.app.settings
    d = FDialog(win, "Envelopes and Labels",
                buttons=(("New Document", Gtk.ResponseType.OK),
                         ("Cancel", Gtk.ResponseType.CANCEL)))
    d.add(heading("Labels"))
    d.add(Gtk.Label(label="Address:", xalign=0))
    tv, sw = _textview(_selected_text(win) or st.get("return_address", ""))
    d.add(sw)
    use_ret = Gtk.CheckButton.new_with_mnemonic("Use _return address")

    def put_return(b):
        if b.get_active():
            tv.get_buffer().set_text(st.get("return_address", ""))
    use_ret.connect("toggled", put_return)
    d.add(use_ret)
    full = Gtk.RadioButton.new_with_mnemonic(None, "_Full page of the same label")
    single = Gtk.RadioButton.new_with_mnemonic_from_widget(full, "Single _label")
    row = Gtk.SpinButton.new_with_range(1, 30, 1)
    col = Gtk.SpinButton.new_with_range(1, 6, 1)
    d.add(heading("Print"))
    d.add(full)
    sb = Gtk.Box(spacing=6)
    sb.pack_start(single, False, False, 0)
    sb.pack_start(Gtk.Label(label="Row:"), False, False, 0)
    sb.pack_start(row, False, False, 0)
    sb.pack_start(Gtk.Label(label="Column:"), False, False, 0)
    sb.pack_start(col, False, False, 0)
    d.add(sb)
    choice = [st.get("label_kind", 0)]
    lab = Gtk.Label(xalign=0)
    lab.set_text("Label: " + _M(win).LABELS[choice[0]][0])
    opts = Gtk.Button(label="_Options...", use_underline=True)

    def pick(*_):
        v = label_options(win, choice[0])
        if v is not None:
            choice[0] = v
            lab.set_text("Label: " + _M(win).LABELS[v][0])
    opts.connect("clicked", pick)
    ob = Gtk.Box(spacing=8)
    ob.pack_start(lab, True, True, 0)
    ob.pack_start(opts, False, False, 0)
    d.add(ob)
    if d.ask() == Gtk.ResponseType.OK:
        st["label_kind"] = choice[0]
        win.app.save_settings()
        address = _get(tv)
        fullp, r_, c_ = full.get_active(), int(row.get_value()), int(col.get_value())
        w = win.app.new_window()

        def fill():
            if _m(w) is None:
                return True
            _M(win).labels_document(_m(w), address, choice[0], fullp, r_, c_)
            return False
        GLib.timeout_add(800, fill)
    d.done()


# ------------------------------------------------------------------ recipients
def type_new_list(win):
    m = _m(win)
    if m is None:
        return
    d = FDialog(win, "New Address List",
                buttons=(("OK", Gtk.ResponseType.OK), ("Cancel", Gtk.ResponseType.CANCEL)))
    d.set_default_size(900, 420)
    d.set_resizable(True)
    cols = list(NEW_LIST_COLUMNS)
    store = Gtk.ListStore(*([str] * len(cols)))
    store.append([""] * len(cols))
    tv = Gtk.TreeView(model=store)
    tv.set_grid_lines(Gtk.TreeViewGridLines.BOTH)
    for i, c in enumerate(cols):
        cell = Gtk.CellRendererText(editable=True)
        cell.connect("edited", lambda _c, path, text, i=i: store[path].__setitem__(i, text))
        col = Gtk.TreeViewColumn(c, cell, text=i)
        col.set_resizable(True)
        col.set_min_width(110)
        tv.append_column(col)
    sw = Gtk.ScrolledWindow()
    sw.set_size_request(860, 300)
    sw.add(tv)
    d.add(Gtk.Label(label="Type recipient information in the table. To add more entries, "
                          "click New Entry.", xalign=0))
    d.add(sw, expand=True)
    bar = Gtk.Box(spacing=6)
    newb = Gtk.Button(label="_New Entry", use_underline=True)
    newb.connect("clicked", lambda *_: store.append([""] * len(cols)))
    delb = Gtk.Button(label="_Delete Entry", use_underline=True)

    def delete(*_):
        model, it = tv.get_selection().get_selected()
        if it is not None:
            model.remove(it)
    delb.connect("clicked", delete)
    bar.pack_start(newb, False, False, 0)
    bar.pack_start(delb, False, False, 0)
    d.add(bar)
    if d.ask() == Gtk.ResponseType.OK:
        rows = [dict(zip(cols, list(r))) for r in store if any(v for v in r)]
        folder = os.path.join(os.path.expanduser("~/Documents"), "My Data Sources")
        os.makedirs(folder, exist_ok=True)
        dd = Gtk.FileChooserDialog(title="Save Address List", transient_for=win,
                                   action=Gtk.FileChooserAction.SAVE)
        dd.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dd.add_button("Save", Gtk.ResponseType.ACCEPT)
        dd.set_current_folder(folder)
        dd.set_current_name("Address List.csv")
        dd.set_do_overwrite_confirmation(True)
        path = dd.get_filename() if dd.run() == Gtk.ResponseType.ACCEPT else None
        dd.destroy()
        if path:
            if not path.lower().endswith(".csv"):
                path += ".csv"
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(cols)
                for r in rows:
                    w.writerow([r.get(c, "") for c in cols])
            _M(win).set_recipients(m, cols, rows, path)
        else:
            _M(win).set_recipients(m, cols, rows)
        _started(win)
    d.done()


def use_existing_list(win):
    m = _m(win)
    if m is None:
        return
    path = win.dialogs.pick_file("Select Data Source", ["*.csv", "*.txt", "*.tsv"],
                                 "Data Sources")
    if not path:
        return
    try:
        cols, rows = _M(win).read_csv(path)
    except Exception as e:
        win.dialogs.message("This data source couldn't be read. (%s)" % e, kind="error")
        return
    if not cols:
        win.dialogs.message("The data source is empty.")
        return
    _M(win).set_recipients(m, cols, rows, path)
    _started(win)


def _started(win):
    m = _m(win)
    if not _M(win).merge_type(m):
        _M(win).set_merge_type(m, "letters")
    win.refresh_mailings()


def edit_recipients(win):
    m = _m(win)
    cols, rows, inc = _M(win).recipients(m) if m else ([], [], [])
    if not rows:
        win.dialogs.message("Select a recipient list first (Select Recipients).")
        return
    d = FDialog(win, "Mail Merge Recipients")
    d.set_default_size(900, 440)
    d.set_resizable(True)
    store = Gtk.ListStore(bool, int, *([str] * len(cols)))
    for i, r in enumerate(rows):
        store.append([inc[i], i] + [r.get(c, "") for c in cols])
    tv = Gtk.TreeView(model=store)
    tog = Gtk.CellRendererToggle()
    tog.connect("toggled", lambda _c, path: store[path].__setitem__(0, not store[path][0]))
    tv.append_column(Gtk.TreeViewColumn("", tog, active=0))
    for i, c in enumerate(cols):
        col = Gtk.TreeViewColumn(c, Gtk.CellRendererText(), text=i + 2)
        col.set_sort_column_id(i + 2)
        col.set_resizable(True)
        tv.append_column(col)
    sw = Gtk.ScrolledWindow()
    sw.set_size_request(860, 320)
    sw.add(tv)
    d.add(Gtk.Label(label="This is the list of recipients that will be used in your merge. "
                          "Use the check boxes to add or remove recipients from the merge.",
                    xalign=0))
    d.add(sw, expand=True)
    if d.ask() == Gtk.ResponseType.OK:
        new = [True] * len(rows)
        for r in store:
            new[r[1]] = r[0]
        _M(win).set_included(m, new)
    d.done()


# ------------------------------------------------------------------ fields
def field_menu(win):
    from .ribbon import menu_popover
    m = _m(win)
    cols = _M(win).recipients(m)[0] if m else []
    if not cols:
        return menu_popover(None, [("#", "Select recipients first")])
    from . import mailrules
    items = [(c, (lambda c=c: win.engine.sync(
        lambda: (_M(win).insert_field(_m(win), c), win.refresh_mailings())))) for c in cols]
    marks = mailrules.bookmark_names(m)
    if marks:
        items += [None, ("#", "Bookmarks")] + [
            (b, (lambda b=b: mailrules.insert_ref(win, b))) for b in marks]
    items += [None, ("Match Fields...", lambda: mailrules.match_fields_dialog(win))]
    return menu_popover(None, items)


def greeting(win):
    m = _m(win)
    if m is None:
        return
    d = FDialog(win, "Insert Greeting Line")
    sal = combo(["Dear", "To", "Hello", "Hi"], 0)
    punct = combo([",", ":", "!", "(none)"], 0)
    d.add(grid([["Greeting line format:", sal], ["Punctuation:", punct]]))
    if d.ask() == Gtk.ResponseType.OK:
        p = punct.get_active_text()
        s = sal.get_active_text()
        win.engine.sync(lambda: _M(win).insert_greeting(m, s, "" if p == "(none)" else p))
    d.done()


def check_errors(win):
    m = _m(win)
    cols, rows, inc = _M(win).recipients(m)
    if not rows:
        win.dialogs.message("There is no recipient list for this document.")
        return
    used = _M(win).merge_masters(m)
    missing = [c for c in used if c not in cols]
    if missing:
        win.dialogs.message("These merge fields don't match a column of the recipient list:"
                            "\n\n" + "\n".join(missing), kind="warning")
    else:
        win.dialogs.message("No mail merge errors have been found in %d record%s." % (
            sum(inc), "" if sum(inc) == 1 else "s"))


# ------------------------------------------------------------------ finish
def finish(win, print_after=False):
    m = _m(win)
    if m is None:
        return
    cols, rows, inc = _M(win).recipients(m)
    if not rows:
        win.dialogs.message("Select a recipient list first (Select Recipients).")
        return
    d = FDialog(win, "Merge to New Document" if not print_after else "Merge to Printer")
    allr = Gtk.RadioButton.new_with_mnemonic(None, "_All")
    cur = Gtk.RadioButton.new_with_mnemonic_from_widget(allr, "Current _record")
    rng = Gtk.RadioButton.new_with_mnemonic_from_widget(allr, "_From:")
    f = Gtk.SpinButton.new_with_range(1, len(rows), 1)
    t = Gtk.SpinButton.new_with_range(1, len(rows), 1)
    t.set_value(len(rows))
    d.add(heading("Merge records"))
    d.add(allr)
    d.add(cur)
    rb = Gtk.Box(spacing=6)
    rb.pack_start(rng, False, False, 0)
    rb.pack_start(f, False, False, 0)
    rb.pack_start(Gtk.Label(label="To:"), False, False, 0)
    rb.pack_start(t, False, False, 0)
    d.add(rb)
    if d.ask() == Gtk.ResponseType.OK:
        if allr.get_active():
            which, a, b = "all", 1, None
        elif cur.get_active():
            which, a, b = (win.merge_preview or 0), 1, None
        else:
            which, a, b = "range", int(f.get_value()), int(t.get_value())
        d.done()
        preview = win.merge_preview

        from . import mailrules
        answers = mailrules.ask_answers(win, m)

        def go():
            try:
                path = _M(win).merge(m, which, a, b, answers)
            except Exception as e:
                win.dialogs.message(str(e), kind="error")
                return
            if preview is not None:
                _M(win).show_record(m, preview)
            w = win.app.new_window(template=path)
            if print_after:
                GLib.timeout_add(2500, lambda: (w.run("backstage-print"), False)[1])
        win.engine.sync(go)
        return
    d.done()


def start_mail_merge(win, kind):
    m = _m(win)
    if m is None:
        return
    li, ei = 0, 0
    if kind == "labels":
        v = label_options(win, win.app.settings.get("label_kind", 0))
        if v is None:
            return
        li = v
    elif kind == "envelopes":
        d = FDialog(win, "Envelope Options")
        size = combo([e[0] for e in _M(win).ENVELOPES], win.app.settings.get("envelope_size", 0))
        d.add(grid([["Envelope _size:", size]]))
        r = d.ask()
        ei = max(0, size.get_active())
        d.done()
        if r != Gtk.ResponseType.OK:
            return
    win.engine.sync(lambda: (_M(win).start(m, kind, li, ei), win.refresh_mailings()))


def not_available(win, what):
    win.status.flash("%s isn't available in Folio Writer: it has no e-mail or Outlook connection." % what)


WIZARD_STEPS = ["Select document type", "Select starting document", "Select recipients",
                "Write your letter", "Preview your letters", "Complete the merge"]


def wizard(win):
    """Step-by-Step Mail Merge Wizard: Word's six steps, each with the
    Mailings tab's own commands."""
    d = FDialog(win, "Mail Merge", buttons=(("Close", Gtk.ResponseType.CLOSE),), width=340)
    d.set_modal(False)
    stack = Gtk.Stack()
    step_lbl = Gtk.Label(xalign=0)
    kinds = [("Letters", "letters"), ("Envelopes", "envelopes"), ("Labels", "labels"),
             ("Directory", "directory")]
    pages = []

    def page(title, *rows):
        b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        b.pack_start(heading(title), False, False, 0)
        for r in rows:
            if isinstance(r, str):
                lb = Gtk.Label(label=r, xalign=0, wrap=True, max_width_chars=44)
                b.pack_start(lb, False, False, 0)
            else:
                b.pack_start(r, False, False, 0)
        stack.add_named(b, str(len(pages)))
        pages.append(b)

    def button(label, fn):
        bt = Gtk.Button(label=label)
        bt.set_halign(Gtk.Align.START)
        bt.connect("clicked", lambda *_: fn())
        return bt
    radios = []
    for lab, _k in kinds:
        radios.append(Gtk.RadioButton.new_with_label_from_widget(radios[0] if radios else None, lab))
    page("Select document type", "What type of document are you working on?", *radios)
    page("Select starting document", "Use the current document.",
         "The document you have open becomes the main document of the merge.")
    page("Select recipients", button("Type a new list...", lambda: type_new_list(win)),
         button("Use an existing list...", lambda: use_existing_list(win)),
         button("Edit recipient list...", lambda: edit_recipients(win)))
    page("Write your letter", "Click where the information goes in the document, then:",
         button("Address block...", lambda: win.model_call_sync("mailings.insert_address_block")),
         button("Greeting line...", lambda: greeting(win)),
         button("More items...", lambda: field_menu(win)))
    page("Preview your letters", button("Preview results", lambda: win.run("merge-preview")),
         button("<< Previous record", lambda: win.merge_go("prev")),
         button("Next record >>", lambda: win.merge_go("next")),
         button("Find a recipient...", lambda: win.run("find-recipient")))
    page("Complete the merge", button("Print...", lambda: finish(win, print_after=True)),
         button("Edit individual letters...", lambda: finish(win)))
    d.add(step_lbl)
    d.add(stack, True)
    nav = Gtk.Box(spacing=6)
    prev_b, next_b = Gtk.Button(label="< Previous"), Gtk.Button(label="Next >")
    nav.pack_start(prev_b, False, False, 0)
    nav.pack_end(next_b, False, False, 0)
    d.add(nav)
    cur = [0]

    def show(i):
        cur[0] = max(0, min(len(pages) - 1, i))
        stack.set_visible_child_name(str(cur[0]))
        step_lbl.set_text("Step %d of %d" % (cur[0] + 1, len(pages)))
        prev_b.set_sensitive(cur[0] > 0)
        next_b.set_sensitive(cur[0] < len(pages) - 1)

    def nxt(*_):
        if cur[0] == 0:
            kind = kinds[next(i for i, r in enumerate(radios) if r.get_active())][1]
            start_mail_merge(win, kind)
        show(cur[0] + 1)
    prev_b.connect("clicked", lambda *_: show(cur[0] - 1))
    next_b.connect("clicked", nxt)
    d.connect("response", lambda *_: d.destroy())
    d.show_all()
    show(0)
    win.mail_wizard = d
    return d
