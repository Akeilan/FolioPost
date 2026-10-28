"""File > Options."""
import os

from gi.repository import GLib, Gtk

from . import docapi
from .widgets import FDialog, combo, grid, heading

THEMES = ["Colorful", "Dark Gray", "Black", "White"]


class OptionsDialog:
    def __init__(self, win):
        self.win = win
        self.app = win.app
        self.s = self.app.settings

    def run_dialog(self, page_name=None):
        s = self.s
        d = FDialog(self.win, "Options")
        d.set_default_size(760, 520)
        d.set_resizable(True)
        body = Gtk.Box(spacing=0)
        side = Gtk.StackSidebar()
        stack = Gtk.Stack()
        side.set_stack(stack)
        side.set_size_request(170, -1)
        body.pack_start(side, False, False, 0)
        body.pack_start(stack, True, True, 0)
        d.add(body, expand=True)

        def page(name):
            b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            b.set_border_width(16)
            stack.add_titled(b, name.lower(), name)
            return b

        # General
        g = page("General")
        g.pack_start(heading("User Interface options"), False, False, 0)
        mini = Gtk.CheckButton(label="Show Mini Toolbar on selection")
        mini.set_active(s.get("mini_toolbar", True))
        tips = Gtk.CheckButton(label="Show feature descriptions in ScreenTips")
        tips.set_active(s.get("screentips", True))
        g.pack_start(mini, False, False, 0)
        g.pack_start(tips, False, False, 0)
        g.pack_start(heading("Personalize your copy"), False, False, 0)
        uname = Gtk.Entry(text=self.app.user_name())
        initials = Gtk.Entry(text=s.get("initials") or "".join(
            w[0] for w in self.app.user_name().split()[:3]).upper())
        initials.set_width_chars(6)
        theme = combo(THEMES, s.get("theme", "Colorful"))
        g.pack_start(grid([["_User name:", uname], ["_Initials:", initials],
                           ["_Theme:", theme]]), False, False, 0)
        g.pack_start(heading("Start up options"), False, False, 0)
        start = Gtk.CheckButton(label="Show the Start screen when this application starts")
        start.set_active(s.get("start_screen", False))
        g.pack_start(start, False, False, 0)

        # Display
        dpg = page("Display")
        dpg.pack_start(heading("Always show these formatting marks on the screen"), False, False, 0)
        marks = Gtk.CheckButton(label="Show all formatting marks")
        marks.set_active(self.win.engine.is_on(".uno:ControlCodes"))
        dpg.pack_start(marks, False, False, 0)

        # Proofing
        pr = page("Proofing")
        pr.pack_start(heading("AutoCorrect options"), False, False, 0)
        ac = {}
        pr.pack_start(Gtk.Label(label="Change how text is corrected and formatted as you type:",
                                xalign=0), False, False, 0)
        acb = Gtk.Button(label="_AutoCorrect Options...", use_underline=True)
        acb.set_halign(Gtk.Align.START)
        acb.connect("clicked", lambda *_: autocorrect_options(self.win))
        pr.pack_start(acb, False, False, 0)
        pr.pack_start(heading("When correcting spelling"), False, False, 0)
        autospell = Gtk.CheckButton(label="Check spelling as you type")
        autospell.set_active(s.get("auto_spell", True))
        pr.pack_start(autospell, False, False, 0)
        autogram = Gtk.CheckButton(label="Mark grammar errors as you type")
        autogram.set_active(s.get("auto_grammar", True))
        pr.pack_start(autogram, False, False, 0)
        readab = Gtk.CheckButton(label="Show readability statistics")
        readab.set_active(s.get("readability", True))
        pr.pack_start(readab, False, False, 0)
        cdb = Gtk.Button(label="Custom _Dictionaries...", use_underline=True)
        cdb.set_halign(Gtk.Align.START)
        cdb.connect("clicked", lambda *_: dictionaries_dialog(self.win))
        pr.pack_start(cdb, False, False, 0)

        # Save
        sv = page("Save")
        sv.pack_start(heading("Save documents"), False, False, 0)
        fmt = combo(["Document (*.docx)", "OpenDocument Text (*.odt)", "Document 97-2003 (*.doc)",
                     "Rich Text Format (*.rtf)"],
                    {"docx": 0, "odt": 1, "doc": 2, "rtf": 3}.get(s.get("default_format", "docx"), 0))
        autosave = Gtk.CheckButton(label="Save AutoRecover information every")
        autosave.set_active(s.get("autorecover", True))
        mins = Gtk.SpinButton.new_with_range(1, 120, 1)
        mins.set_value(s.get("autorecover_minutes", 10))
        ar = Gtk.Box(spacing=6)
        ar.pack_start(autosave, False, False, 0)
        ar.pack_start(mins, False, False, 0)
        ar.pack_start(Gtk.Label(label="minutes"), False, False, 0)
        loc = Gtk.FileChooserButton(title="Default local file location",
                                    action=Gtk.FileChooserAction.SELECT_FOLDER)
        loc.set_current_folder(s.get("default_dir") or self.win.dialogs.last_dir)
        sv.pack_start(grid([["Save files in this _format:", fmt]]), False, False, 0)
        sv.pack_start(ar, False, False, 0)
        sv.pack_start(grid([["Default local file location:", loc]]), False, False, 0)

        # Advanced
        adv = page("Advanced")
        adv.pack_start(heading("Editing options"), False, False, 0)
        typing_replaces = Gtk.CheckButton(label="Typing replaces selected text")
        typing_replaces.set_active(True)
        typing_replaces.set_sensitive(False)
        ctrl_click = Gtk.CheckButton(label="Use Ctrl+Click to follow hyperlink")
        ctrl_click.set_active(s.get("ctrl_click_links", True))
        adv.pack_start(typing_replaces, False, False, 0)
        adv.pack_start(ctrl_click, False, False, 0)
        adv.pack_start(heading("Show document content"), False, False, 0)
        anim = Gtk.CheckButton(label="Show text animation")
        anim.set_sensitive(False)
        anim.set_tooltip_text("Text animation (blinking, marching ants) is shown as plain text, as in current versions of the original.")
        adv.pack_start(anim, False, False, 0)
        adv.pack_start(heading("Cut, copy, and paste"), False, False, 0)
        modes = ["Keep Source Formatting (Default)", "Merge Formatting", "Keep Text Only"]
        keys = ["source", "merge", "text"]
        within = combo(modes, keys.index(s.get("paste_within", "source")))
        other = combo(modes, keys.index(s.get("paste_other", "source")))
        adv.pack_start(grid([["Pasting within the same document:", within],
                             ["Pasting from other programs:", other]]), False, False, 0)
        adv.pack_start(heading("Display"), False, False, 0)
        from .widgets import units as cur_units
        cur = {"in": "Inches", "cm": "Centimeters", "mm": "Millimeters", "pt": "Points",
               "pi": "Picas"}[cur_units()[0]]
        units = combo(["Inches", "Centimeters", "Millimeters", "Points", "Picas"],
                      s.get("units", cur))
        recent_n = Gtk.SpinButton.new_with_range(0, 50, 1)
        recent_n.set_value(s.get("recent_count", 50))
        adv.pack_start(grid([["Show this number of Recent Documents:", recent_n],
                             ["Show measurements in units of:", units]]), False, False, 0)
        adv.pack_start(heading("Compatibility"), False, False, 0)
        adv.pack_start(Gtk.Label(label="Files are saved so they open correctly in other word "
                                       "processors.", xalign=0), False, False, 0)
        adv.pack_start(heading("Document engine"), False, False, 0)
        from . import native as _native
        new_engine = Gtk.CheckButton(
            label="Use Folio's own document engine (applies to new windows)")
        new_engine.set_active(s.get("engine", "native") != "classic")
        new_engine.set_sensitive(_native.available() and _native.classic_available())
        if not _native.classic_available():
            new_engine.set_tooltip_text("The old engine isn't installed, so Folio's own engine is always used.")
        adv.pack_start(new_engine, False, False, 0)

        # Language
        lg = page("Language")
        lg.pack_start(heading("Office authoring languages and proofing"), False, False, 0)
        lg.pack_start(Gtk.Label(label="Manage the languages used for creating and editing "
                                      "documents, including proofing tools such as spelling "
                                      "and grammar.", xalign=0, wrap=True, max_width_chars=70),
                      False, False, 0)
        cur_lang = tuple(s.get("language") or ("en", "US"))
        langs = [tuple(x) for x in s.get("editing_languages") or [list(cur_lang)]]
        if cur_lang not in langs:
            langs.insert(0, cur_lang)
        lstore = Gtk.ListStore(str, str, str)

        def lname(l, c):
            return next((n for n, a, b in docapi.LANGUAGES if (a, b) == (l, c)), "%s-%s" % (l, c))

        def lfill():
            lstore.clear()
            for l, c in langs:
                tag = "  <preferred>" if (l, c) == cur_lang_v[0] else ""
                proof = "Proofing installed" if docapi.has_dictionary(l, c) else \
                    "Proofing not installed"
                lstore.append([lname(l, c) + tag, proof, "%s-%s" % (l, c)])
        cur_lang_v = [cur_lang]
        ltv = Gtk.TreeView(model=lstore)
        ltv.append_column(Gtk.TreeViewColumn("Editing Language", Gtk.CellRendererText(), text=0))
        ltv.append_column(Gtk.TreeViewColumn("Proofing", Gtk.CellRendererText(), text=1))
        lsw = Gtk.ScrolledWindow()
        lsw.set_size_request(-1, 140)
        lsw.add(ltv)
        lg.pack_start(lsw, False, False, 0)
        lb = Gtk.Box(spacing=6)
        add_l = combo([n for n, _a, _b in docapi.LANGUAGES], 0)
        add_b = Gtk.Button(label="_Add a Language", use_underline=True)
        rem_b = Gtk.Button(label="_Remove", use_underline=True)
        pref_b = Gtk.Button(label="Set as _Preferred", use_underline=True)
        for w in (add_l, add_b, rem_b, pref_b):
            lb.pack_start(w, False, False, 0)
        lg.pack_start(lb, False, False, 0)

        def lsel():
            mdl, it = ltv.get_selection().get_selected()
            return tuple(mdl[it][2].split("-")) if it else None

        def l_add(*_):
            _n, a, b = docapi.LANGUAGES[max(0, add_l.get_active())]
            if (a, b) not in langs:
                langs.append((a, b))
                lfill()

        def l_rem(*_):
            x = lsel()
            if x and x != cur_lang_v[0] and x in langs:
                langs.remove(x)
                lfill()

        def l_pref(*_):
            x = lsel()
            if x:
                cur_lang_v[0] = x
                lfill()
        add_b.connect("clicked", l_add)
        rem_b.connect("clicked", l_rem)
        pref_b.connect("clicked", l_pref)
        lfill()
        lg.pack_start(heading("Display Language"), False, False, 0)
        lg.pack_start(Gtk.Label(label="Display language: English", xalign=0), False, False, 0)

        # Accessibility
        acc = page("Accessibility")
        acc.pack_start(heading("Document accessibility options"), False, False, 0)
        st_items = dict(s.get("status_items") or {})
        keep_a11y = Gtk.CheckButton(label="Keep accessibility checker running while I work")
        keep_a11y.set_active(st_items.get("a11y", True))
        acc.pack_start(keep_a11y, False, False, 0)
        acc.pack_start(heading("Application display options"), False, False, 0)
        acc_tips = Gtk.CheckButton(label="Show feature descriptions in ScreenTips")
        acc_tips.set_active(s.get("screentips", True))
        acc_tips.connect("toggled", lambda b: tips.set_active(b.get_active()))
        tips.connect("toggled", lambda b: acc_tips.set_active(b.get_active()))
        acc.pack_start(acc_tips, False, False, 0)
        acc.pack_start(heading("Document display options"), False, False, 0)
        acc_marks = Gtk.CheckButton(label="Show all formatting marks")
        acc_marks.set_active(marks.get_active())
        acc_marks.connect("toggled", lambda b: marks.set_active(b.get_active()))
        marks.connect("toggled", lambda b: acc_marks.set_active(b.get_active()))
        acc.pack_start(acc_marks, False, False, 0)

        # Quick Access Toolbar
        qp = page("Quick Access Toolbar")
        qp.pack_start(heading("Customize the Quick Access Toolbar"), False, False, 0)
        qcmds = {c[0]: c[1] for c in self.win.QAT_COMMANDS}
        chosen_q = [k for k in s.get("qat", ["save", "undo", "redo"]) if k in qcmds]
        avail_s, cur_s = Gtk.ListStore(str, str), Gtk.ListStore(str, str)

        def qfill():
            avail_s.clear()
            cur_s.clear()
            for k, lab in qcmds.items():
                avail_s.append([lab, k])
            for k in chosen_q:
                cur_s.append([qcmds[k], k])

        def qtv(store):
            tv = Gtk.TreeView(model=store)
            tv.set_headers_visible(False)
            tv.append_column(Gtk.TreeViewColumn("", Gtk.CellRendererText(), text=0))
            sw = Gtk.ScrolledWindow()
            sw.set_size_request(220, 220)
            sw.add(tv)
            return tv, sw
        atv, asw = qtv(avail_s)
        ctv, csw = qtv(cur_s)

        def qsel(tv):
            mdl, it = tv.get_selection().get_selected()
            return mdl[it][1] if it else None

        def q_add(*_):
            k = qsel(atv)
            if k and k not in chosen_q:
                chosen_q.append(k)
                qfill()

        def q_rem(*_):
            k = qsel(ctv)
            if k in chosen_q:
                chosen_q.remove(k)
                qfill()

        def q_move(delta):
            k = qsel(ctv)
            if k in chosen_q:
                i = chosen_q.index(k)
                j = max(0, min(len(chosen_q) - 1, i + delta))
                chosen_q[i], chosen_q[j] = chosen_q[j], chosen_q[i]
                qfill()
                ctv.get_selection().select_path(Gtk.TreePath(j))
        mid_b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        mid_b.set_valign(Gtk.Align.CENTER)
        for lab, fn in (("_Add >>", q_add), ("<< _Remove", q_rem)):
            b = Gtk.Button(label=lab, use_underline=True)
            b.connect("clicked", fn)
            mid_b.pack_start(b, False, False, 0)
        side_b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        side_b.set_valign(Gtk.Align.CENTER)
        for lab, dl in (("▲", -1), ("▼", 1)):
            b = Gtk.Button(label=lab)
            b.set_tooltip_text("Move Up" if dl < 0 else "Move Down")
            b.connect("clicked", lambda _b, dl=dl: q_move(dl))
            side_b.pack_start(b, False, False, 0)
        qh = Gtk.Box(spacing=8)
        v1 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        v1.pack_start(Gtk.Label(label="Choose commands from: Popular Commands", xalign=0),
                      False, False, 0)
        v1.pack_start(asw, True, True, 0)
        v2 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        v2.pack_start(Gtk.Label(label="Customize Quick Access Toolbar:", xalign=0),
                      False, False, 0)
        v2.pack_start(csw, True, True, 0)
        qh.pack_start(v1, True, True, 0)
        qh.pack_start(mid_b, False, False, 0)
        qh.pack_start(v2, True, True, 0)
        qh.pack_start(side_b, False, False, 0)
        qp.pack_start(qh, True, True, 0)
        qreset = Gtk.Button(label="R_eset", use_underline=True)
        qreset.set_halign(Gtk.Align.END)
        qreset.connect("clicked", lambda *_: (chosen_q.clear(),
                                              chosen_q.extend(["save", "undo", "redo"]),
                                              qfill()))
        qp.pack_start(qreset, False, False, 0)
        qfill()

        cr = page("Customize Ribbon")
        from . import customize
        save_ribbon = customize.ribbon_page(self.win, cr)

        # Add-ins and Trust Center: there to find, not offered here
        from . import APP_NAME as _APP
        for name, what in (("Add-ins", "Add-ins"),
                           ("Trust Center", "The Trust Center (macro and add-in security settings)")):
            pg = page(name)
            pg.pack_start(heading(name), False, False, 0)
            lab = Gtk.Label(label="%s aren't available in %s: it doesn't run add-ins or macros from "
                                  "documents, so there's nothing to set here." % (what, _APP)
                            if name == "Add-ins" else
                            "%s isn't available in %s: documents' macros and add-ins are never run, "
                            "and nothing is sent anywhere." % (what, _APP), xalign=0)
            lab.set_line_wrap(True)
            lab.set_max_width_chars(70)
            pg.pack_start(lab, False, False, 0)

        if page_name:
            d.show_all()
            stack.set_visible_child_name(page_name.lower())
        if d.ask() == Gtk.ResponseType.OK:
            s["user_name"] = uname.get_text().strip()
            s["initials"] = initials.get_text().strip()
            s["theme"] = theme.get_active_text()
            s["mini_toolbar"] = mini.get_active()
            s["screentips"] = tips.get_active()
            s["start_screen"] = start.get_active()
            for k, cb in ac.items():
                s[k] = cb.get_active()
            s["auto_spell"] = autospell.get_active()
            s["auto_grammar"] = autogram.get_active()
            s["readability"] = readab.get_active()
            s["default_format"] = ["docx", "odt", "doc", "rtf"][fmt.get_active()]
            s["autorecover"] = autosave.get_active()
            s["autorecover_minutes"] = int(mins.get_value())
            s["default_dir"] = loc.get_filename() or s.get("default_dir")
            s["ctrl_click_links"] = ctrl_click.get_active()
            s["engine"] = "native" if new_engine.get_active() else "classic"
            s["paste_within"] = keys[max(0, within.get_active())]
            s["paste_other"] = keys[max(0, other.get_active())]
            s["units"] = units.get_active_text()
            s["recent_count"] = int(recent_n.get_value())
            s["editing_languages"] = [list(x) for x in langs]
            if tuple(cur_lang_v[0]) != cur_lang:
                s["language"] = list(cur_lang_v[0])
                m = self.win.engine.model
                if m is not None:
                    try:
                        docapi.set_language(m, cur_lang_v[0][0], cur_lang_v[0][1],
                                            default=True, whole=False)
                    except Exception as e:
                        print("language:", e)
            st_items["a11y"] = keep_a11y.get_active()
            s["status_items"] = st_items
            s["qat"] = list(chosen_q)
            save_ribbon()
            self.app.save_settings()
            if marks.get_active() != self.win.engine.is_on(".uno:ControlCodes"):
                self.win.engine.command(".uno:ControlCodes")
            self.app.apply_settings()
        d.done()


def _ac_lang_path(win):
    from . import autocorrect
    user = os.path.join(win.app.engine_profile, "user")
    lang = "en-US"
    m = win.engine.model
    if m is not None:
        try:
            l, c = docapi.current_language(m)
            if l == "en" and c:
                lang = "en-" + c
        except Exception:
            pass
    return lang, autocorrect.user_list_path(user, lang) or autocorrect.user_list_path(user)


def remove_autocorrect_entry(win, word):
    """AutoCorrect button > Stop Automatically Correcting: drop the entry."""
    from . import autocorrect
    _lang, path = _ac_lang_path(win)
    if path is None:
        return
    entries = [e for e in autocorrect.read_list(path) if e[0] != word]
    autocorrect.save_list(path, entries)
    from .acwatch import ACWatch
    ACWatch._repl = None


AC_TABS = [
    ("AutoCorrect", [
        (None, None, None),
        ("ac_buttons", "Show AutoCorrect Options buttons", True),
        ("#", "", None),
        ("ac_two_caps", "Correct TWo INitial CApitals", True),
        ("ac_caps_first", "Capitalize first letter of sentences", True),
        ("ac_caps_cells", "Capitalize first letter of table cells", True),
        ("ac_days", "Capitalize names of days", True),
        ("ac_capslock", "Correct accidental usage of cAPS LOCK key", True),
        ("#", "", None),
        ("ac_replace", "Replace text as you type", True)]),
    ("AutoFormat As You Type", [
        ("#", "Replace as you type", None),
        ("ac_quotes", "\"Straight quotes\" with “smart quotes”", True),
        ("ac_ordinals", "Ordinals (1st) with superscript", True),
        ("ac_fractions", "Fractions (1/2) with fraction character (½)", True),
        ("ac_dashes", "Hyphens (--) with dash (—)", True),
        ("ac_bold_italic", "*Bold* and _italic_ with real formatting", True),
        ("ac_urls", "Internet and network paths with hyperlinks", True),
        ("#", "Apply as you type", None),
        ("ac_bullets", "Automatic bulleted lists", True),
        ("ac_numbers", "Automatic numbered lists", True),
        ("ac_borders", "Border lines", True),
        ("ac_tables", "Tables", True),
        ("ac_headings", "Built-in Heading styles", False),
        ("#", "Automatically as you type", None),
        ("ac_list_format", "Format beginning of list item like the one before it", True),
        ("ac_tab_indent", "Set left- and first-indent with tabs and backspaces", True),
        ("ac_define_styles", "Define styles based on your formatting", False)]),
]


def autocorrect_options(win, tab=0, with_text=None):
    """AutoCorrect, as in the original: AutoCorrect, Math AutoCorrect and
    AutoFormat As You Type."""
    from . import autocorrect
    from .app import apply_engine_config
    s = win.app.settings
    lang, path = _ac_lang_path(win)
    d = FDialog(win, "AutoCorrect: %s" % docapi.language_name(lang))
    d.set_default_size(520, 600)
    nb = Gtk.Notebook()
    checks = {}

    def page(spec, extra=None):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_border_width(10)
        for key, label, default in spec:
            if key is None:
                continue
            if key == "#":
                if label:
                    box.pack_start(heading(label), False, False, 4)
                else:
                    box.pack_start(Gtk.Separator(), False, False, 4)
                continue
            cb = Gtk.CheckButton(label=label)
            cur = s.get(key)
            if cur is None and key in ("ac_bullets", "ac_numbers"):
                cur = s.get("ac_lists", True)
            cb.set_active(default if cur is None else cur)
            checks[key] = cb
            box.pack_start(cb, False, False, 0)
        if extra is not None:
            box.pack_start(extra, True, True, 0)
        return box

    # ---- the replacement list
    entries, hidden = [], []
    if path is not None:
        entries = autocorrect.read_list(path)
        hidden = [e for e in entries if ".*" in e[0]]
        entries = [e for e in entries if ".*" not in e[0]]
    lbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    rep, wit = Gtk.Entry(), Gtk.Entry()
    rep.set_width_chars(14)
    wit.set_width_chars(30)
    lbox.pack_start(grid([["_Replace:", "_With:"], [rep, wit]]), False, False, 0)
    if with_text:
        GLib.idle_add(lambda: (wit.set_text(with_text), rep.grab_focus(), False)[2])
    store = Gtk.ListStore(str, str)
    for a, b in sorted(entries, key=lambda e: e[0].lower()):
        store.append([a, b])
    tv = Gtk.TreeView(model=store)
    tv.set_headers_visible(False)
    for i in (0, 1):
        col = Gtk.TreeViewColumn("", Gtk.CellRendererText(), text=i)
        col.set_min_width(120 if i == 0 else 260)
        tv.append_column(col)
    tv.set_search_column(0)
    sw = Gtk.ScrolledWindow()
    sw.set_size_request(440, 220)
    sw.add(tv)
    lbox.pack_start(sw, True, True, 0)
    btns = Gtk.Box(spacing=6)
    btns.set_halign(Gtk.Align.END)
    add = Gtk.Button(label="_Add", use_underline=True)
    delete = Gtk.Button(label="_Delete", use_underline=True)
    btns.pack_start(add, False, False, 0)
    btns.pack_start(delete, False, False, 0)
    lbox.pack_start(btns, False, False, 0)
    changed = [False]

    def find(key):
        for row in store:
            if row[0] == key:
                return row
        return None

    def on_rep(*_):
        row = find(rep.get_text())
        add.set_label("_Replace" if row is not None else "_Add")
        if row is not None:
            tv.get_selection().select_iter(row.iter)
            tv.scroll_to_cell(row.path, None, True, 0.3, 0)
    rep.connect("changed", on_rep)

    def on_sel(sel):
        model, it = sel.get_selected()
        if it is not None and rep.get_text() != model[it][0]:
            rep.set_text(model[it][0])
            wit.set_text(model[it][1])
    tv.get_selection().connect("changed", on_sel)

    def do_add(*_):
        a, b = rep.get_text(), wit.get_text()
        if not a or not b:
            return
        row = find(a)
        if row is not None:
            row[1] = b
        else:
            store.append([a, b])
        changed[0] = True
        rep.set_text("")
        wit.set_text("")
    add.connect("clicked", do_add)
    wit.connect("activate", do_add)

    def do_delete(*_):
        model, it = tv.get_selection().get_selected()
        if it is not None:
            model.remove(it)
            changed[0] = True
            rep.set_text("")
            wit.set_text("")
    delete.connect("clicked", do_delete)
    if path is None:
        lbox.set_sensitive(False)
    first = page(AC_TABS[0][1], lbox)
    exc = Gtk.Button(label="_Exceptions...", use_underline=True)
    exc.set_halign(Gtk.Align.END)
    exc.connect("clicked", lambda *_: exceptions_dialog(win, path))
    first.pack_start(exc, False, False, 0)
    first.reorder_child(exc, 2)
    nb.append_page(first, Gtk.Label(label="AutoCorrect"))
    # ---- Math AutoCorrect
    mpage = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    mpage.set_border_width(10)
    mo = Gtk.CheckButton(label="Use Math AutoCorrect rules outside of math regions")
    try:
        from . import eqoptions
        mo.set_active(eqoptions.options(win.app).get("outside", False))
    except Exception:
        pass
    mpage.pack_start(mo, False, False, 0)
    mb = Gtk.Button(label="Math AutoCorrect _Entries...", use_underline=True)
    mb.set_halign(Gtk.Align.START)
    mb.connect("clicked", lambda *_: __import__("folio.eqoptions",
                                               fromlist=["x"]).autocorrect_dialog(win))
    mpage.pack_start(mb, False, False, 0)
    fb = Gtk.Button(label="Recognized _Functions...", use_underline=True)
    fb.set_halign(Gtk.Align.START)
    fb.connect("clicked", lambda *_: __import__("folio.eqoptions",
                                               fromlist=["x"]).functions_dialog(win))
    mpage.pack_start(fb, False, False, 0)
    nb.append_page(mpage, Gtk.Label(label="Math AutoCorrect"))
    nb.append_page(page(AC_TABS[1][1]), Gtk.Label(label="AutoFormat As You Type"))
    if "ac_define_styles" in checks:
        checks["ac_define_styles"].set_active(False)
        checks["ac_define_styles"].set_sensitive(False)
        checks["ac_define_styles"].set_tooltip_text("Making styles from your formatting isn't available in this version.")
    for tab_name, note in (("AutoFormat", "AutoFormat for the whole document at once isn't available in %s; "
                                          "AutoFormat As You Type makes the same changes while you type."),
                           ("Actions", "Additional actions in the right-click menu (dates, financial symbols and "
                                       "the like) aren't available in %s.")):
        from . import APP_NAME as _APP
        tb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        tb.set_border_width(10)
        lab = Gtk.Label(label=note % _APP, xalign=0)
        lab.set_line_wrap(True)
        lab.set_max_width_chars(60)
        tb.pack_start(lab, False, False, 0)
        nb.append_page(tb, Gtk.Label(label=tab_name))
    d.add(nb, expand=True)
    nb.show_all()
    nb.set_current_page(tab)
    if d.ask() == Gtk.ResponseType.OK:
        for key, cb in checks.items():
            s[key] = cb.get_active()
        s["ac_lists"] = s.get("ac_bullets", True) or s.get("ac_numbers", True)
        try:
            from . import eqoptions
            o = eqoptions.options(win.app)
            o["outside"] = mo.get_active()
            win.app.settings["eq_options"] = o
        except Exception:
            pass
        win.app.save_settings()
        apply_engine_config(s)
        if changed[0] and path is not None:
            try:
                autocorrect.save_list(path, [(r[0], r[1]) for r in store] + hidden)
                from .acwatch import ACWatch
                ACWatch._repl = None
            except Exception as e:
                win.dialogs.message("The AutoCorrect list couldn't be saved. (%s)" % e,
                                    kind="error")
    d.done()


autocorrect_dialog = autocorrect_options


def exceptions_dialog(win, path):
    """AutoCorrect Exceptions: words after which no capital follows, and
    words with two initial capitals that stay as typed."""
    from . import autocorrect
    if path is None:
        return
    first, caps = autocorrect.read_exceptions(path)
    d = FDialog(win, "AutoCorrect Exceptions")
    nb = Gtk.Notebook()
    stores = []
    for title, words, hint in (("First Letter", first, "Don't capitalize after:"),
                               ("INitial CAps", caps, "Don't correct:")):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_border_width(8)
        box.pack_start(Gtk.Label(label=hint, xalign=0), False, False, 0)
        e = Gtk.Entry()
        box.pack_start(e, False, False, 0)
        st = Gtk.ListStore(str)
        for w in sorted(words, key=str.lower):
            st.append([w])
        tv = Gtk.TreeView(model=st)
        tv.set_headers_visible(False)
        tv.append_column(Gtk.TreeViewColumn("", Gtk.CellRendererText(), text=0))
        sw = Gtk.ScrolledWindow()
        sw.set_size_request(260, 240)
        sw.add(tv)
        box.pack_start(sw, True, True, 0)
        bb = Gtk.Box(spacing=6)
        a = Gtk.Button(label="_Add", use_underline=True)
        r = Gtk.Button(label="_Delete", use_underline=True)
        a.connect("clicked", lambda _b, e=e, st=st: (e.get_text().strip() and
                                                     st.append([e.get_text().strip()]),
                                                     e.set_text("")))
        r.connect("clicked", lambda _b, tv=tv: [tv.get_model().remove(it) for it in
                                                [tv.get_selection().get_selected()[1]] if it])
        bb.pack_start(a, False, False, 0)
        bb.pack_start(r, False, False, 0)
        box.pack_start(bb, False, False, 0)
        nb.append_page(box, Gtk.Label(label=title))
        stores.append(st)
    d.add(nb, expand=True)
    nb.show_all()
    if d.ask() == Gtk.ResponseType.OK:
        autocorrect.save_exceptions(path, [r[0] for r in stores[0]], [r[0] for r in stores[1]])
    d.done()


# ------------------------------------------------------------ custom dictionaries
def _dict_list():
    from . import bridge
    return bridge.create("com.sun.star.linguistic2.DictionaryList")


def _display(name):
    return {"FolioWords": "CUSTOM.DIC (Default)", "standard.dic": "CUSTOM.DIC",
            "IgnoreAllList": None,
            "List of Ignored Words": None, "technical.dic": None}.get(name, name)


def dictionaries_dialog(win):
    from .widgets import FDialog
    dl = _dict_list()
    d = FDialog(win, "Custom Dictionaries", buttons=(("OK", Gtk.ResponseType.OK),))
    d.add(Gtk.Label(label="Dictionary List", xalign=0))
    store = Gtk.ListStore(bool, str, str)
    tv = Gtk.TreeView(model=store)
    tv.set_headers_visible(False)
    tog = Gtk.CellRendererToggle()
    tv.append_column(Gtk.TreeViewColumn("", tog, active=0))
    tv.append_column(Gtk.TreeViewColumn("", Gtk.CellRendererText(), text=1))
    sw = Gtk.ScrolledWindow()
    sw.set_size_request(380, 180)
    sw.add(tv)
    hb = Gtk.Box(spacing=10)
    hb.pack_start(sw, True, True, 0)
    bb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    edit = Gtk.Button(label="Edit Word List...")
    new = Gtk.Button(label="New...")
    rem = Gtk.Button(label="Remove")
    for b in (edit, new, rem):
        bb.pack_start(b, False, False, 0)
    hb.pack_start(bb, False, False, 0)
    d.add(hb, expand=True)

    def fill():
        store.clear()
        from . import docapi
        docapi.user_dictionary()
        for dic in dl.getDictionaries():
            name = dic.getName()
            shown = _display(name)
            if shown is None or name.endswith(".dic") is False and name != "standard.dic" \
                    and not name.endswith(".dic"):
                if shown is None:
                    continue
            store.append([dic.isActive(), shown, name])

    def toggled(cell, path):
        row = store[path]
        dic = dl.getDictionaryByName(row[2])
        if dic is not None:
            dic.setActive(not row[0])
            row[0] = not row[0]
    tog.connect("toggled", toggled)

    def current():
        model, it = tv.get_selection().get_selected()
        return dl.getDictionaryByName(model[it][2]) if it else None

    def do_edit(*_):
        dic = current()
        if dic is not None:
            word_list_dialog(d, dic)

    def do_new(*_):
        name = win.dialogs.ask_text("Create Custom Dictionary", "File name:", "CUSTOM2.dic")
        if not name:
            return
        if not name.lower().endswith(".dic"):
            name += ".dic"
        from . import bridge, docapi
        import uno
        import os
        path = os.path.join(os.path.expanduser("~/.config/folio-writer/dictionaries"), name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            dic = dl.createDictionary(name, docapi.locale("", ""),
                                      uno.Enum("com.sun.star.linguistic2.DictionaryType",
                                               "POSITIVE"), uno.systemPathToFileUrl(path))
            dl.addDictionary(dic)
            dic.setActive(True)
        except Exception as e:
            win.dialogs.message("The dictionary couldn't be created: %s" % e)
        fill()

    def do_remove(*_):
        dic = current()
        if dic is None or dic.getName() == "standard.dic":
            return
        dl.removeDictionary(dic)
        fill()
    edit.connect("clicked", do_edit)
    new.connect("clicked", do_new)
    rem.connect("clicked", do_remove)
    tv.connect("row-activated", lambda *_: do_edit())
    fill()
    if len(store):
        tv.get_selection().select_path(Gtk.TreePath(0))
    d.ask()
    d.done()


def word_list_dialog(parent, dic):
    from .widgets import FDialog
    d = FDialog(parent, _display(dic.getName()) or dic.getName(),
                buttons=(("OK", Gtk.ResponseType.OK),))
    entry = Gtk.Entry()
    entry.set_placeholder_text("Word(s):")
    store = Gtk.ListStore(str)
    tv = Gtk.TreeView(model=store)
    tv.set_headers_visible(False)
    tv.append_column(Gtk.TreeViewColumn("", Gtk.CellRendererText(), text=0))
    sw = Gtk.ScrolledWindow()
    sw.set_size_request(320, 220)
    sw.add(tv)
    bb = Gtk.Box(spacing=6)
    add = Gtk.Button(label="Add")
    dele = Gtk.Button(label="Delete")
    clear = Gtk.Button(label="Delete all")
    for b in (add, dele, clear):
        bb.pack_start(b, False, False, 0)
    d.add(entry)
    d.add(Gtk.Label(label="Dictionary:", xalign=0))
    d.add(sw, expand=True)
    d.add(bb)

    def fill():
        store.clear()
        for e in sorted(dic.getEntries(), key=lambda e: e.getDictionaryWord().lower()):
            store.append([e.getDictionaryWord()])

    from . import docapi
    own = dic.getName() == "FolioWords"

    def do_add(*_):
        w = entry.get_text().strip()
        if w:
            if own:
                docapi.add_to_dictionary(w)
            else:
                dic.add(w, False, "")
            entry.set_text("")
            fill()

    def do_del(*_):
        model, it = tv.get_selection().get_selected()
        if it:
            if own:
                docapi.remove_from_dictionary(model[it][0])
            else:
                dic.remove(model[it][0])
            fill()
    add.connect("clicked", do_add)
    entry.connect("activate", do_add)
    dele.connect("clicked", do_del)
    clear.connect("clicked", lambda *_: (dic.clear(), own and docapi.save_user_words([]),
                                         fill()))
    fill()
    d.ask()
    d.done()
