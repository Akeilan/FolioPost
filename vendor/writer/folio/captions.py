"""Caption, as in the original: label, position, exclude label, New Label,
Delete Label, Numbering (format, chapter number) and AutoCaption."""
from gi.repository import Gtk

from . import docapi
from .widgets import FDialog, combo, grid, heading

BUILTIN = ["Equation", "Figure", "Table"]
NUMFMT = [("1, 2, 3, ...", 4), ("a, b, c, ...", 1), ("A, B, C, ...", 0),
          ("i, ii, iii, ...", 3), ("I, II, III, ...", 2)]
SEPARATORS = [("- (hyphen)", "-"), (". (period)", "."), (": (colon)", ":"),
              ("— (em dash)", "—"), ("– (en dash)", "–")]
AUTO_KINDS = [("Folio Picture", "picture"), ("Folio Table", "table"),
              ("Folio Equation", "equation")]


def _labels(win):
    return BUILTIN + win.app.settings.get("caption_labels", [])


def _fmt(n, t):
    if t == 1:
        return chr(96 + n)
    if t == 0:
        return chr(64 + n)
    if t in (2, 3):
        r = ["", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"][min(n, 10)]
        return r if t == 2 else r.lower()
    return str(n)


def dialog(win):
    m = win.engine.model
    st = win.app.settings
    labels = _labels(win)
    d = FDialog(win, "Caption")
    lab = combo(labels, st.get("caption_last", "Figure"))
    e = Gtk.Entry()
    e.set_width_chars(44)
    pos = combo(["Below selected item", "Above selected item"], 0)
    excl = Gtk.CheckButton.new_with_mnemonic("_Exclude label from caption")
    d.add(grid([["_Caption:", None], [e, None]]))
    d.add(heading("Options"))
    d.add(grid([["_Label:", lab], ["_Position:", pos]]))
    d.add(excl)
    num = dict(st.get("caption_numbering", {}))
    bb = Gtk.Box(spacing=6)
    newl = Gtk.Button(label="_New Label...", use_underline=True)
    dell = Gtk.Button(label="_Delete Label", use_underline=True)
    numb = Gtk.Button(label="N_umbering...", use_underline=True)
    for w in (newl, dell, numb):
        bb.pack_start(w, False, False, 0)
    d.add(bb)
    autob = Gtk.Button(label="_AutoCaption...", use_underline=True)
    autob.set_halign(Gtk.Align.START)
    d.add(autob)

    def counter(name):
        if getattr(win, "native", False):
            return win.engine.ed.seq_count(name) + 1
        return len(docapi.references(m).get(name, [])) + 1

    def numspec(name):
        return num.get(name, {"fmt": 4, "chapter": False, "level": 1, "sep": "-"})

    def upd(*_):
        n = lab.get_active_text() or "Figure"
        spec = numspec(n)
        base = "" if excl.get_active() else n + " "
        chap = ("1%s" % spec["sep"]) if spec["chapter"] else ""
        e.set_text(base + chap + _fmt(counter(n), spec["fmt"]))
        dell.set_sensitive(n not in BUILTIN)
    lab.connect("changed", upd)
    excl.connect("toggled", upd)

    def new_label(*_):
        t = win.dialogs.ask_text("New Label", "Label:")
        if t and t not in labels:
            labels.append(t)
            lab.append_text(t)
            lab.set_active(len(labels) - 1)
            st.setdefault("caption_labels", []).append(t)
            win.app.save_settings()

    def delete_label(*_):
        n = lab.get_active_text()
        if n in BUILTIN or n is None:
            return
        i = labels.index(n)
        labels.remove(n)
        lab.remove(i)
        lab.set_active(0)
        st["caption_labels"] = [x for x in st.get("caption_labels", []) if x != n]
        win.app.save_settings()

    def numbering(*_):
        n = lab.get_active_text() or "Figure"
        spec = dict(numspec(n))
        dd = FDialog(d, "Caption Numbering")
        fmt = combo([x for x, _v in NUMFMT],
                    next((i for i, (_x, v) in enumerate(NUMFMT) if v == spec["fmt"]), 0))
        chap = Gtk.CheckButton.new_with_mnemonic("Include _chapter number")
        chap.set_active(spec["chapter"])
        level = combo(["Heading %d" % i for i in range(1, 10)], spec["level"] - 1)
        sep = combo([x for x, _v in SEPARATORS],
                    next((i for i, (_x, v) in enumerate(SEPARATORS) if v == spec["sep"]), 0))
        g = grid([["Chapter starts with st_yle:", level], ["Use se_parator:", sep]])
        g.set_margin_start(20)
        dd.add(grid([["For_mat:", fmt]]))
        dd.add(chap)
        dd.add(g)
        chap.connect("toggled", lambda b: g.set_sensitive(b.get_active()))
        g.set_sensitive(chap.get_active())
        dd.show_all()
        if dd.ask() == Gtk.ResponseType.OK:
            num[n] = {"fmt": NUMFMT[max(0, fmt.get_active())][1], "chapter": chap.get_active(),
                      "level": level.get_active() + 1,
                      "sep": SEPARATORS[max(0, sep.get_active())][1]}
            st["caption_numbering"] = num
            win.app.save_settings()
            upd()
        dd.destroy()
    newl.connect("clicked", new_label)
    dell.connect("clicked", delete_label)
    numb.connect("clicked", numbering)
    autob.connect("clicked", lambda *_: (d.response(Gtk.ResponseType.CANCEL),
                                         autocaption_dialog(win)))
    upd()
    d.show_all()
    upd()
    if d.ask() == Gtk.ResponseType.OK:
        n = lab.get_active_text() or "Figure"
        spec = numspec(n)
        prefix = ("" if excl.get_active() else n + " ") + \
            (("1%s" % spec["sep"]) if spec["chapter"] else "") + _fmt(counter(n), spec["fmt"])
        extra = e.get_text()[len(prefix):] if e.get_text().startswith(prefix) else ""
        st["caption_last"] = n
        if getattr(win, "native", False):
            fmt = {0: "ALPHABETIC", 1: "alphabetic", 2: "ROMAN", 3: "roman"}.get(spec.get("fmt", 4), "ARABIC")
            win.engine.ed.insert_caption(n, extra.strip(), pos.get_active() == 0, fmt, excl.get_active())
            win.engine.view.after_edit()
        else:
            insert(m, n, extra.strip(), pos.get_active() == 0, spec, excl.get_active())
    d.destroy()
    win.focus_document()


def insert(m, label, text, below, spec, exclude=False):
    um = m.getUndoManager()
    um.enterUndoContext("Insert Caption")
    try:
        docapi.insert_caption(m, label, text, below=below, numtype=spec.get("fmt", 4),
                              chapter=(spec["level"], spec["sep"]) if spec.get("chapter")
                              else None, exclude_label=exclude)
    finally:
        um.leaveUndoContext()


def autocaption_dialog(win):
    st = win.app.settings
    auto = dict(st.get("autocaption", {}))
    d = FDialog(win, "AutoCaption")
    d.add(Gtk.Label(label="_Add caption when inserting:", xalign=0, use_underline=True))
    checks = {}
    lb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    for name, key in AUTO_KINDS:
        c = Gtk.CheckButton(label=name)
        c.set_active(key in auto)
        checks[key] = c
        lb.pack_start(c, False, False, 0)
    fr = Gtk.Frame()
    fr.add(lb)
    d.add(fr)
    d.add(heading("Options"))
    labels = _labels(win)
    lab = combo(labels, "Figure")
    pos = combo(["Below item", "Above item"], 0)
    d.add(grid([["_Use label:", lab], ["_Position:", pos]]))
    current = [None]

    def pick(key):
        current[0] = key
        spec = auto.get(key, {"label": {"table": "Table", "equation": "Equation"}.get(
            key, "Figure"), "below": key != "table"})
        lab.set_active(labels.index(spec["label"]) if spec["label"] in labels else 0)
        pos.set_active(0 if spec["below"] else 1)

    def store(*_):
        k = current[0]
        if k and checks[k].get_active():
            auto[k] = {"label": lab.get_active_text() or "Figure",
                       "below": pos.get_active() == 0}
    for key, c in checks.items():
        c.connect("toggled", lambda b, k=key: (pick(k), store() if b.get_active()
                                               else auto.pop(k, None)))
        c.connect("focus-in-event", lambda *_a, k=key: (pick(k), False)[1])
    lab.connect("changed", store)
    pos.connect("changed", store)
    pick("picture")
    d.show_all()
    if d.ask() == Gtk.ResponseType.OK:
        store()
        st["autocaption"] = {k: v for k, v in auto.items() if checks[k].get_active()}
        win.app.save_settings()
    d.destroy()


def after_insert(win, kind):
    """Called after a picture / table / equation is inserted."""
    spec = win.app.settings.get("autocaption", {}).get(kind)
    m = win.engine.model
    if not spec or m is None:
        return
    num = win.app.settings.get("caption_numbering", {}).get(
        spec["label"], {"fmt": 4, "chapter": False, "level": 1, "sep": "-"})
    try:
        if kind == "table":
            vc = docapi.view_cursor(m)
            t = vc.TextTable
            if t is None:
                return
            back = vc.getStart()
            text = m.getText()
            para = m.createInstance("com.sun.star.text.Paragraph")
            if spec.get("below", True):
                text.insertTextContentAfter(para, t)
            else:
                text.insertTextContentBefore(para, t)
            vc.gotoRange(para.getStart(), False)
            insert(m, spec["label"], "", None, num)
            vc.gotoRange(back, False)
        else:
            insert(m, spec["label"], "", spec.get("below", True), num)
    except Exception as e:
        print("autocaption:", e)
