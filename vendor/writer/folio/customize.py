"""Customize the Ribbon (show/hide tabs, your own tabs and groups of
commands) and Customize Keyboard (a shortcut for any command)."""
from gi.repository import Gdk, Gtk

from . import icons
from .ribbon import Group, RibbonButton, SplitButton, Tab

POPULAR = ["Home|Bold", "Home|Italic", "Home|Underline", "Home|Copy", "Home|Cut",
           "Home|Paste", "Home|Format Painter", "Home|Bullets", "Home|Numbering",
           "Home|Find", "Home|Replace", "Insert|Table", "Insert|Pictures",
           "Insert|Hyperlink" if False else "Insert|Link", "Insert|Comment",
           "Insert|Page Break", "Insert|Text Box", "Layout|Margins", "Review|New Comment",
           "Review|Track Changes", "Review|Spelling & Grammar", "View|Print Layout",
           "References|Insert Footnote", "Insert|Equation", "Insert|Symbol"]


def _clean(label):
    return " ".join((label or "").split())


def catalog(win):
    """{key: (label, icon, control)} for every ribbon button."""
    out = {}
    for c in win.ribbon.controls:
        if not isinstance(c, (RibbonButton, SplitButton)):
            continue
        tab = getattr(c, "tab_name", "")
        if tab.startswith("Custom:"):
            continue
        label = _clean(c.label) or (c.tooltip_text or "").split(" (")[0]
        if not label:
            continue
        key = "%s|%s" % (tab, label)
        if key not in out:
            out[key] = (label, c.icon_name, c)
    return out


def settings(app):
    s = app.settings.get("ribbon_custom")
    if not isinstance(s, dict) or "hidden" not in s:
        s = dict(s) if isinstance(s, dict) else {}
        s["hidden"] = ["Developer"]          # off until turned on, as in the original
    s.setdefault("hidden", [])
    s.setdefault("groups", [])         # [{"tab", "name", "commands": [keys]}]
    s.setdefault("tabs", [])           # [{"name"}]
    return s


def apply(win):
    """Show the user's tabs, groups and hidden tabs on this window's ribbon."""
    r = win.ribbon
    cfg = settings(win.app)
    cat = catalog(win)
    # remove what was added before
    for t in list(r.tabs):
        for g in getattr(t, "custom_groups", []):
            parent = g.get_parent()
            if parent is not None:
                parent.remove(g)
            if g in getattr(t, "groups", []):
                t.groups.remove(g)
        t.custom_groups = []
        if t.name.startswith("Custom:") and t.name[7:] not in [x["name"] for x in cfg["tabs"]]:
            t.button.hide()
    for spec in cfg["tabs"]:
        name = "Custom:" + spec["name"]
        t = r.tab_by_name(name)
        if t is None:
            t = Tab(name, spec.get("keytip") or "Y" + str(len(cfg["tabs"])))
            t.custom_groups = []
            r.add_tab(t)
            t.button.set_label(spec["name"])
            t.body.get_parent().show_all() if t.body.get_parent() else None
            r.stack.get_child_by_name(name).show_all()
        t.button.show()
    for g in cfg["groups"]:
        tab_name = g["tab"] if r.tab_by_name(g["tab"]) else "Custom:" + g["tab"]
        t = r.tab_by_name(tab_name)
        if t is None:
            continue
        r.building(t)
        buttons = []
        for key in g.get("commands", []):
            entry = cat.get(key)
            if entry is None:
                continue
            label, icon, ctrl = entry
            b = RibbonButton(r, label, icon or "cmd/sc_adddirect", ctrl.action, size="small",
                             tooltip=label)
            buttons.append(b)
        r.building(None)
        cols = [buttons[i:i + 3] for i in range(0, len(buttons), 3)] or [[Gtk.Label(
            label="(empty)")]]
        grp = Group(g["name"] + " (Custom)" if not t.name.startswith("Custom:") else g["name"],
                    cols)
        if getattr(t, "_groups", 0):
            sep = Gtk.Box()
            sep.get_style_context().add_class("folio-sep")
            t.body.pack_start(sep, False, False, 0)
        t.body.pack_start(grp, False, False, 0)
        t._groups = getattr(t, "_groups", 0) + 1
        if not hasattr(t, "groups"):
            t.groups = []
        t.groups.append(grp)
        t.custom_groups.append(grp)
        grp.show_all()
    for t in r.tabs:
        if t.contextual or t.name.startswith("Custom:"):
            continue
        if t.name in cfg["hidden"]:
            t.button.set_no_show_all(True)
            t.button.hide()
            if r.current is t:
                r.select(r.tab_by_name("Home"))
        else:
            t.button.set_no_show_all(False)
            t.button.show()
    r.fit()


# ------------------------------------------------------------ Options page
def ribbon_page(win, box):
    """Options > Customize Ribbon."""
    app = win.app
    cfg = settings(app)
    cat = catalog(win)
    hb = Gtk.Box(spacing=10)
    box.pack_start(Gtk.Label(label="Customize the Ribbon and keyboard shortcuts.", xalign=0),
                   False, False, 0)
    box.pack_start(hb, True, True, 0)
    # left: commands
    left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    left.pack_start(Gtk.Label(label="Choose commands from:", xalign=0), False, False, 0)
    source = Gtk.ComboBoxText()
    for t in ("Popular Commands", "All Commands") + tuple(
            "%s Tab" % t.name for t in win.ribbon.tabs if not t.name.startswith("Custom:")):
        source.append_text(t)
    source.set_active(0)
    left.pack_start(source, False, False, 0)
    cstore = Gtk.ListStore(str, str)        # label, key
    ctv = Gtk.TreeView(model=cstore)
    ctv.set_headers_visible(False)
    ctv.append_column(Gtk.TreeViewColumn("", Gtk.CellRendererText(), text=0))
    csw = Gtk.ScrolledWindow()
    csw.set_size_request(230, 300)
    csw.add(ctv)
    left.pack_start(csw, True, True, 0)

    def fill_commands(*_):
        cstore.clear()
        which = source.get_active_text() or ""
        if which == "Popular Commands":
            keys = [k for k in POPULAR if k in cat]
        elif which == "All Commands":
            keys = sorted(cat, key=lambda k: cat[k][0].lower())
        else:
            tab = which[:-4]
            keys = [k for k in cat if k.startswith(tab + "|")]
        seen = set()
        for k in keys:
            label = cat[k][0]
            shown = label if which != "All Commands" or label not in seen else \
                "%s (%s)" % (label, k.split("|")[0])
            seen.add(label)
            cstore.append([shown, k])
    source.connect("changed", fill_commands)
    fill_commands()
    hb.pack_start(left, True, True, 0)
    # middle: add / remove
    mid = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    mid.set_valign(Gtk.Align.CENTER)
    add = Gtk.Button(label="Add >>")
    rem = Gtk.Button(label="<< Remove")
    mid.pack_start(add, False, False, 0)
    mid.pack_start(rem, False, False, 0)
    hb.pack_start(mid, False, False, 0)
    # right: tabs and groups
    right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    right.pack_start(Gtk.Label(label="Customize the Ribbon:", xalign=0), False, False, 0)
    tstore = Gtk.TreeStore(bool, str, str, str)   # shown, label, kind, id
    ttv = Gtk.TreeView(model=tstore)
    ttv.set_headers_visible(False)
    chk = Gtk.CellRendererToggle()
    tcol = Gtk.TreeViewColumn("", chk, active=0)
    tcol.set_cell_data_func(chk, lambda col, cell, model, it, d: cell.set_visible(
        model[it][2] == "tab"))
    ttv.append_column(tcol)
    ttv.append_column(Gtk.TreeViewColumn("", Gtk.CellRendererText(), text=1))
    tsw = Gtk.ScrolledWindow()
    tsw.set_size_request(260, 300)
    tsw.add(ttv)
    right.pack_start(tsw, True, True, 0)
    rb = Gtk.Box(spacing=4)
    new_tab = Gtk.Button(label="New Tab")
    new_group = Gtk.Button(label="New Group")
    rename = Gtk.Button(label="Rename...")
    rb.pack_start(new_tab, False, False, 0)
    rb.pack_start(new_group, False, False, 0)
    rb.pack_start(rename, False, False, 0)
    right.pack_start(rb, False, False, 0)
    reset = Gtk.Button(label="Reset")
    right.pack_start(reset, False, False, 0)
    hb.pack_start(right, True, True, 0)

    def tab_names():
        return [t.name for t in win.ribbon.tabs if not t.contextual and
                not t.name.startswith("Custom:")] + [t["name"] for t in cfg["tabs"]]

    def fill_tabs(select=None):
        tstore.clear()
        target = None
        for name in tab_names():
            custom = name in [t["name"] for t in cfg["tabs"]]
            it = tstore.append(None, [name not in cfg["hidden"],
                                      name + (" (Custom)" if custom else ""), "tab", name])
            if select == ("tab", name):
                target = it
            for gi, g in enumerate(cfg["groups"]):
                if g["tab"] != name:
                    continue
                git = tstore.append(it, [True, g["name"] + " (Custom)", "group", str(gi)])
                if select == ("group", str(gi)):
                    target = git
                for k in g["commands"]:
                    label = cat[k][0] if k in cat else k.split("|")[-1]
                    cit = tstore.append(git, [True, label, "cmd", "%d|%s" % (gi, k)])
        ttv.expand_all()
        if target is not None:
            ttv.get_selection().select_iter(target)

    def toggled(cell, path):
        row = tstore[path]
        if row[2] != "tab":
            return
        row[0] = not row[0]
        if row[0] and row[3] in cfg["hidden"]:
            cfg["hidden"].remove(row[3])
        elif not row[0] and row[3] not in cfg["hidden"]:
            cfg["hidden"].append(row[3])
    chk.connect("toggled", toggled)

    def sel_tree():
        model, it = ttv.get_selection().get_selected()
        return (model[it][2], model[it][3], it) if it else (None, None, None)

    def ask(title, label, value=""):
        return win.dialogs.ask_text(title, label, value)

    def do_new_tab(*_):
        name = ask("New Tab", "Tab name:", "New Tab")
        if not name:
            return
        cfg["tabs"].append({"name": name})
        cfg["groups"].append({"tab": name, "name": "New Group", "commands": []})
        fill_tabs(("group", str(len(cfg["groups"]) - 1)))

    def do_new_group(*_):
        kind, ident, it = sel_tree()
        if kind is None:
            win.dialogs.message("Select a tab first.")
            return
        tab = ident if kind == "tab" else (cfg["groups"][int(ident)]["tab"] if kind == "group"
                                           else cfg["groups"][int(ident.split("|")[0])]["tab"])
        name = ask("New Group", "Group name:", "New Group")
        if not name:
            return
        cfg["groups"].append({"tab": tab, "name": name, "commands": []})
        fill_tabs(("group", str(len(cfg["groups"]) - 1)))

    def do_rename(*_):
        kind, ident, it = sel_tree()
        if kind == "group":
            g = cfg["groups"][int(ident)]
            name = ask("Rename", "Display name:", g["name"])
            if name:
                g["name"] = name
                fill_tabs(("group", ident))
        elif kind == "tab" and ident in [t["name"] for t in cfg["tabs"]]:
            name = ask("Rename", "Display name:", ident)
            if name:
                for t in cfg["tabs"]:
                    if t["name"] == ident:
                        t["name"] = name
                for g in cfg["groups"]:
                    if g["tab"] == ident:
                        g["tab"] = name
                fill_tabs(("tab", name))
        else:
            win.dialogs.message("Only your own tabs and groups can be renamed.")

    def do_add(*_):
        model, it = ctv.get_selection().get_selected()
        kind, ident, tit = sel_tree()
        if it is None:
            return
        if kind not in ("group", "cmd"):
            win.dialogs.message("Commands can only be added to custom groups. Select a "
                                "group you created, or click New Group.")
            return
        gi = int(ident if kind == "group" else ident.split("|")[0])
        key = model[it][1]
        if key not in cfg["groups"][gi]["commands"]:
            cfg["groups"][gi]["commands"].append(key)
        fill_tabs(("group", str(gi)))

    def do_remove(*_):
        kind, ident, it = sel_tree()
        if kind == "cmd":
            gi, key = ident.split("|", 1)
            gi = int(gi)
            if key in cfg["groups"][gi]["commands"]:
                cfg["groups"][gi]["commands"].remove(key)
            fill_tabs(("group", str(gi)))
        elif kind == "group":
            del cfg["groups"][int(ident)]
            fill_tabs()
        elif kind == "tab" and ident in [t["name"] for t in cfg["tabs"]]:
            cfg["tabs"] = [t for t in cfg["tabs"] if t["name"] != ident]
            cfg["groups"] = [g for g in cfg["groups"] if g["tab"] != ident]
            fill_tabs()

    def do_reset(*_):
        if win.dialogs.confirm("Delete all Ribbon customizations?", yes="Yes", no="No"):
            cfg["hidden"], cfg["groups"], cfg["tabs"] = [], [], []
            fill_tabs()
    new_tab.connect("clicked", do_new_tab)
    new_group.connect("clicked", do_new_group)
    rename.connect("clicked", do_rename)
    add.connect("clicked", do_add)
    rem.connect("clicked", do_remove)
    reset.connect("clicked", do_reset)
    ctv.connect("row-activated", lambda *_: do_add())
    fill_tabs()
    kb = Gtk.Box(spacing=8)
    kb.pack_start(Gtk.Label(label="Keyboard shortcuts:"), False, False, 0)
    kbtn = Gtk.Button(label="Customize...")
    kbtn.connect("clicked", lambda *_: keyboard_dialog(win, box.get_toplevel()))
    kb.pack_start(kbtn, False, False, 0)
    box.pack_start(kb, False, False, 0)

    def save():
        app.settings["ribbon_custom"] = cfg
        for w in app.windows:
            apply(w)
    return save


# ------------------------------------------------------------ keyboard
def user_keys(app):
    k = app.settings.get("user_keys")
    return k if isinstance(k, dict) else {}


def apply_keys(win):
    cat = catalog(win)
    table = {}
    for spec, key in user_keys(win.app).items():
        entry = cat.get(key)
        if entry is not None:
            table[spec] = entry[2].action
    win.keymap.set_user_keys(table)


def _pretty(spec):
    return "+".join(p.capitalize() if len(p) > 1 else p.upper() for p in spec.split("+"))


def keyboard_dialog(win, parent=None):
    from .keys import BINDINGS
    from .widgets import FDialog
    cat = catalog(win)
    keys = dict(user_keys(win.app))
    d = FDialog(parent or win, "Customize Keyboard",
                buttons=(("Close", Gtk.ResponseType.OK),))
    hb = Gtk.Box(spacing=10)
    cats = Gtk.ListStore(str)
    tabs = []
    for k in cat:
        t = k.split("|")[0]
        if t not in tabs:
            tabs.append(t)
    for t in tabs:
        cats.append(["%s Tab" % t])
    ctv = Gtk.TreeView(model=cats)
    ctv.set_headers_visible(False)
    ctv.append_column(Gtk.TreeViewColumn("", Gtk.CellRendererText(), text=0))
    sw1 = Gtk.ScrolledWindow()
    sw1.set_size_request(170, 220)
    sw1.add(ctv)
    cmds = Gtk.ListStore(str, str)
    mtv = Gtk.TreeView(model=cmds)
    mtv.set_headers_visible(False)
    mtv.append_column(Gtk.TreeViewColumn("", Gtk.CellRendererText(), text=0))
    sw2 = Gtk.ScrolledWindow()
    sw2.set_size_request(230, 220)
    sw2.add(mtv)
    v1 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    v1.pack_start(Gtk.Label(label="Categories:", xalign=0), False, False, 0)
    v1.pack_start(sw1, True, True, 0)
    v2 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    v2.pack_start(Gtk.Label(label="Commands:", xalign=0), False, False, 0)
    v2.pack_start(sw2, True, True, 0)
    hb.pack_start(v1, True, True, 0)
    hb.pack_start(v2, True, True, 0)
    d.add(hb, expand=True)
    cur_store = Gtk.ListStore(str, str)
    cur = Gtk.TreeView(model=cur_store)
    cur.set_headers_visible(False)
    cur.append_column(Gtk.TreeViewColumn("", Gtk.CellRendererText(), text=0))
    cur.set_size_request(-1, 70)
    entry = Gtk.Entry()
    entry.set_placeholder_text("Press new shortcut key")
    note = Gtk.Label(xalign=0)
    g = Gtk.Grid(column_spacing=10, row_spacing=6)
    g.attach(Gtk.Label(label="Current keys:", xalign=0), 0, 0, 1, 1)
    g.attach(cur, 0, 1, 1, 1)
    g.attach(Gtk.Label(label="Press new shortcut key:", xalign=0), 1, 0, 1, 1)
    g.attach(entry, 1, 1, 1, 1)
    g.attach(note, 0, 2, 2, 1)
    d.add(g)
    bb = Gtk.Box(spacing=6)
    assign = Gtk.Button(label="Assign")
    remove = Gtk.Button(label="Remove")
    reset = Gtk.Button(label="Reset All...")
    for b in (assign, remove, reset):
        bb.pack_start(b, False, False, 0)
    d.add(bb)
    state = {"spec": None}

    def current_cmd():
        model, it = mtv.get_selection().get_selected()
        return model[it][1] if it else None

    def fill_current(*_):
        cur_store.clear()
        key = current_cmd()
        if not key:
            return
        ctrl = cat[key][2]
        for spec, act in BINDINGS:
            if act == ctrl.action and not spec.endswith("+zoom"):
                cur_store.append([_pretty(spec), spec])
        for spec, k in keys.items():
            if k == key:
                cur_store.append([_pretty(spec), spec])

    def fill_cmds(*_):
        model, it = ctv.get_selection().get_selected()
        cmds.clear()
        if it is None:
            return
        tab = model[it][0][:-4]
        for k in sorted((k for k in cat if k.startswith(tab + "|")),
                        key=lambda k: cat[k][0].lower()):
            cmds.append([cat[k][0], k])
    ctv.get_selection().connect("changed", fill_cmds)
    mtv.get_selection().connect("changed", fill_current)

    def on_key(w, ev):
        name = (Gdk.keyval_name(Gdk.keyval_to_lower(ev.keyval)) or "").lower()
        if name in ("control_l", "control_r", "shift_l", "shift_r", "alt_l", "alt_r",
                    "tab", "iso_left_tab"):
            return False
        mods = []
        if ev.state & Gdk.ModifierType.CONTROL_MASK:
            mods.append("ctrl")
        if ev.state & Gdk.ModifierType.MOD1_MASK:
            mods.append("alt")
        if ev.state & Gdk.ModifierType.SHIFT_MASK:
            mods.append("shift")
        if not mods and not name.startswith("f"):
            return True
        spec = "+".join(mods + [name])
        state["spec"] = spec
        entry.set_text(_pretty(spec))
        taken = [a for s, a in BINDINGS if s == spec]
        user = keys.get(spec)
        if user:
            note.set_text("Currently assigned to: %s" % cat.get(user, (user,))[0])
        elif taken:
            note.set_text("Currently assigned to: %s" % (taken[0] if isinstance(taken[0], str)
                                                         else "another command"))
        else:
            note.set_text("Currently assigned to: [unassigned]")
        return True
    entry.connect("key-press-event", on_key)

    def do_assign(*_):
        key = current_cmd()
        if key and state["spec"]:
            keys[state["spec"]] = key
            save()
            fill_current()
            entry.set_text("")

    def do_remove(*_):
        model, it = cur.get_selection().get_selected()
        if it is None:
            return
        spec = model[it][1]
        if spec in keys:
            del keys[spec]
            save()
        else:
            note.set_text("Built-in shortcuts can't be removed; assign the key to another "
                          "command instead.")
        fill_current()

    def do_reset(*_):
        if win.dialogs.confirm("Do you want to reset all your keyboard shortcuts?",
                               yes="Yes", no="No"):
            keys.clear()
            save()
            fill_current()

    def save():
        win.app.settings["user_keys"] = dict(keys)
        try:
            win.app.save_settings()
        except OSError:
            pass
        for w in win.app.windows:
            apply_keys(w)
    assign.connect("clicked", do_assign)
    remove.connect("clicked", do_remove)
    reset.connect("clicked", do_reset)
    ctv.get_selection().select_path(Gtk.TreePath(0))
    d.ask()
    d.done()
