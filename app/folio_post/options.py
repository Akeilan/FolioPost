"""Options, signatures, junk e-mail lists, Quick Steps and rules."""
from gi.repository import Gtk

from . import APP_NAME


def _dialog(parent, title, w=520, h=-1):
    d = Gtk.Dialog(title=title, transient_for=parent, modal=True)
    d.get_style_context().add_class("folio-dialog")
    d.set_default_size(w, h)
    box = d.get_content_area()
    box.set_border_width(14)
    box.set_spacing(8)
    return d, box


def _store(parent):
    return parent.store


def _app(parent):
    return parent.app


# ---------------------------------------------------------------- Options
def options_dialog(win, page=""):
    app = win.app
    d, box = _dialog(win, "%s Options" % APP_NAME, 560)
    nb = Gtk.Notebook()
    box.pack_start(nb, True, True, 0)

    def section(title):
        b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        b.set_border_width(12)
        nb.append_page(b, Gtk.Label(label=title))
        return b

    g = section("General")
    name = Gtk.Entry(text=app.user_name())
    g.pack_start(Gtk.Label(label="User name", xalign=0), False, False, 0)
    g.pack_start(name, False, False, 0)
    m = section("Mail")
    remind = Gtk.CheckButton(label="Remind me when I mention an attachment but haven't attached anything")
    remind.set_active(app.setting("attachment_reminder", True))
    m.pack_start(remind, False, False, 0)
    autosave = Gtk.SpinButton.new_with_range(1, 99, 1)
    autosave.set_value(app.setting("autosave_minutes", 3))
    row = Gtk.Box(spacing=6)
    row.pack_start(Gtk.Label(label="Save unsent messages every"), False, False, 0)
    row.pack_start(autosave, False, False, 0)
    row.pack_start(Gtk.Label(label="minutes"), False, False, 0)
    m.pack_start(row, False, False, 0)
    sig = Gtk.Button(label="Signatures...")
    sig.set_halign(Gtk.Align.START)
    sig.connect("clicked", lambda *_: signatures_dialog(win))
    m.pack_start(sig, False, False, 6)
    r = section("Reading Pane")
    wait = Gtk.RadioButton.new_with_label(None, "Mark items as read when viewed in the Reading Pane")
    change = Gtk.RadioButton.new_with_label_from_widget(wait, "Mark item as read when selection changes")
    never = Gtk.RadioButton.new_with_label_from_widget(wait, "Don't mark items as read automatically")
    how = app.setting("mark_read", "change")
    {"wait": wait, "change": change, "never": never}[how].set_active(True)
    secs = Gtk.SpinButton.new_with_range(0, 999, 1)
    secs.set_value(app.setting("mark_read_seconds", 5))
    for w in (wait,):
        r.pack_start(w, False, False, 0)
    row = Gtk.Box(spacing=6)
    row.set_margin_start(24)
    row.pack_start(Gtk.Label(label="Wait"), False, False, 0)
    row.pack_start(secs, False, False, 0)
    row.pack_start(Gtk.Label(label="seconds before marking item as read"), False, False, 0)
    r.pack_start(row, False, False, 0)
    r.pack_start(change, False, False, 0)
    r.pack_start(never, False, False, 0)
    s = section("Send/Receive")
    every = Gtk.SpinButton.new_with_range(0, 1440, 1)
    every.set_value(app.setting("sync_minutes", 5))
    row = Gtk.Box(spacing=6)
    row.pack_start(Gtk.Label(label="Schedule an automatic send/receive every"), False, False, 0)
    row.pack_start(every, False, False, 0)
    row.pack_start(Gtk.Label(label="minutes (0: never)"), False, False, 0)
    s.pack_start(row, False, False, 0)
    t = section("Trust Center")
    safe = Gtk.Label(xalign=0)
    safe.set_markup("Pictures from the internet in HTML messages aren't downloaded unless you allow them, so senders "
                    "can't tell that you read their message.")
    safe.set_line_wrap(True)
    t.pack_start(safe, False, False, 0)
    junk = Gtk.Button(label="Junk E-mail Options...")
    junk.set_halign(Gtk.Align.START)
    junk.connect("clicked", lambda *_: junk_options(win))
    t.pack_start(junk, False, False, 4)
    pages = {"mail": 1, "reading": 2, "send": 3, "trust": 4}
    d.add_button("Cancel", Gtk.ResponseType.CANCEL)
    ok = d.add_button("OK", Gtk.ResponseType.OK)
    ok.get_style_context().add_class("folio-default")
    d.show_all()
    if page in pages:
        nb.set_current_page(pages[page])
    d.widgets = {"name": name, "remind": remind, "autosave": autosave, "wait": wait, "change": change, "never": never,
                 "secs": secs, "every": every, "notebook": nb}

    def done(_d, resp):
        if resp == Gtk.ResponseType.OK:
            app.settings["author"] = name.get_text()
            app.settings["attachment_reminder"] = remind.get_active()
            app.settings["autosave_minutes"] = int(autosave.get_value())
            app.settings["mark_read"] = "wait" if wait.get_active() else "change" if change.get_active() else "never"
            app.settings["mark_read_seconds"] = int(secs.get_value())
            app.settings["sync_minutes"] = int(every.get_value())
            try:
                app.save_settings()
            except OSError:
                pass
            app.schedule_sync()
        d.destroy()
    d.connect("response", done)
    return d


# ---------------------------------------------------------------- Signatures
def signatures_dialog(win):
    from .richedit import RichEditor
    store = win.store
    sigs = dict(store.get("signatures", {}) or {})
    defaults = dict(store.get("signature-defaults", {}) or {})
    d, box = _dialog(win, "Signatures and Stationery", 640, 520)
    top = Gtk.Box(spacing=10)
    left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    left.pack_start(Gtk.Label(label="Select signature to edit", xalign=0), False, False, 0)
    model = Gtk.ListStore(str)
    tv = Gtk.TreeView(model=model)
    tv.set_headers_visible(False)
    tv.append_column(Gtk.TreeViewColumn("", Gtk.CellRendererText(), text=0))
    sw = Gtk.ScrolledWindow()
    sw.set_size_request(220, 120)
    sw.add(tv)
    left.pack_start(sw, True, True, 0)
    bar = Gtk.Box(spacing=4)
    left.pack_start(bar, False, False, 0)
    top.pack_start(left, True, True, 0)
    right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    right.pack_start(Gtk.Label(label="Choose default signature", xalign=0), False, False, 0)
    acc_combo = Gtk.ComboBoxText()
    accs = win.store.accounts()
    for a in accs:
        acc_combo.append(str(a["id"]), a["email"])
    new_combo = Gtk.ComboBoxText()
    reply_combo = Gtk.ComboBoxText()
    right.pack_start(Gtk.Label(label="E-mail account:", xalign=0), False, False, 0)
    right.pack_start(acc_combo, False, False, 0)
    right.pack_start(Gtk.Label(label="New messages:", xalign=0), False, False, 0)
    right.pack_start(new_combo, False, False, 0)
    right.pack_start(Gtk.Label(label="Replies/forwards:", xalign=0), False, False, 0)
    right.pack_start(reply_combo, False, False, 0)
    top.pack_start(right, True, True, 0)
    box.pack_start(top, False, False, 0)
    box.pack_start(Gtk.Label(label="Edit signature", xalign=0), False, False, 0)
    ed = RichEditor()
    esw = Gtk.ScrolledWindow()
    esw.add(ed)
    esw.set_size_request(-1, 180)
    fmt = Gtk.Box(spacing=2)
    for label, fn in (("B", lambda: ed.toggle("bold")), ("I", lambda: ed.toggle("italic")),
                      ("U", lambda: ed.toggle("underline"))):
        b = Gtk.Button(label=label)
        b.connect("clicked", lambda *_a, f=fn: f())
        fmt.pack_start(b, False, False, 0)
    box.pack_start(fmt, False, False, 0)
    box.pack_start(esw, True, True, 0)
    state = {"cur": None}

    def save_current():
        if state["cur"] is not None:
            sigs[state["cur"]] = ed.to_html(inline_data=True)[0]

    def fill(select=None):
        model.clear()
        for n in sorted(sigs):
            it = model.append([n])
            if n == select:
                tv.get_selection().select_iter(it)
        for c in (new_combo, reply_combo):
            c.remove_all()
            c.append("", "(none)")
            for n in sorted(sigs):
                c.append(n, n)
        load_defaults()

    def load_defaults(*_):
        aid = acc_combo.get_active_id() or ""
        p = defaults.get(aid, {})
        new_combo.set_active_id(p.get("new", "") or "")
        reply_combo.set_active_id(p.get("reply", "") or "")

    def store_defaults(*_):
        aid = acc_combo.get_active_id() or ""
        defaults[aid] = {"new": new_combo.get_active_id() or "", "reply": reply_combo.get_active_id() or ""}

    def selected(*_):
        save_current()
        m, it = tv.get_selection().get_selected()
        state["cur"] = m[it][0] if it is not None else None
        ed.load_html(sigs.get(state["cur"], "") if state["cur"] else "")
        ed.set_sensitive(state["cur"] is not None)

    def new():
        n = win.dialogs.ask_text("New Signature", "Type a name for this signature:")
        if n:
            save_current()
            sigs[n] = sigs.get(n, "")
            state["cur"] = None
            fill(n)

    def delete():
        if state["cur"] and state["cur"] in sigs:
            del sigs[state["cur"]]
            state["cur"] = None
            fill()
            ed.load_html("")

    def rename():
        old = state["cur"]
        if not old:
            return
        n = win.dialogs.ask_text("Rename", "Type a new name for this signature:", old)
        if n and n != old:
            save_current()
            sigs[n] = sigs.pop(old)
            for p in defaults.values():
                for k in ("new", "reply"):
                    if p.get(k) == old:
                        p[k] = n
            state["cur"] = None
            fill(n)
    for label, fn in (("New", new), ("Delete", delete), ("Rename", rename)):
        b = Gtk.Button(label=label)
        b.connect("clicked", lambda *_a, f=fn: f())
        bar.pack_start(b, False, False, 0)
    tv.get_selection().connect("changed", selected)
    acc_combo.connect("changed", load_defaults)
    new_combo.connect("changed", store_defaults)
    reply_combo.connect("changed", store_defaults)
    if accs:
        acc_combo.set_active(0)
    fill()
    ed.set_sensitive(False)
    d.add_button("Cancel", Gtk.ResponseType.CANCEL)
    ok = d.add_button("OK", Gtk.ResponseType.OK)
    ok.get_style_context().add_class("folio-default")

    def done(_d, resp):
        if resp == Gtk.ResponseType.OK:
            save_current()
            store_defaults()
            store.put("signatures", sigs)
            store.put("signature-defaults", defaults)
        d.destroy()
    d.connect("response", done)
    d.show_all()
    d.parts = {"new": new, "editor": ed, "sigs": sigs, "defaults": defaults, "fill": fill, "tree": tv,
               "new_combo": new_combo, "reply_combo": reply_combo, "select": lambda n: fill(n)}
    return d


# ---------------------------------------------------------------- Junk
def junk_options(win):
    store = win.store
    d, box = _dialog(win, "Junk E-mail Options", 520, 420)
    nb = Gtk.Notebook()
    box.pack_start(nb, True, True, 0)
    lists = {}
    for key, title, text in (("safe-senders", "Safe Senders", "E-mail from these addresses is never treated as junk, "
                              "and its pictures are downloaded."),
                             ("blocked-senders", "Blocked Senders", "E-mail from these addresses or domains is moved to "
                              "the Junk Email folder.")):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        page.set_border_width(10)
        lab = Gtk.Label(label=text, xalign=0)
        lab.set_line_wrap(True)
        page.pack_start(lab, False, False, 0)
        model = Gtk.ListStore(str)
        for a in store.get(key, []) or []:
            model.append([a])
        tv = Gtk.TreeView(model=model)
        tv.set_headers_visible(False)
        tv.append_column(Gtk.TreeViewColumn("", Gtk.CellRendererText(), text=0))
        sw = Gtk.ScrolledWindow()
        sw.add(tv)
        page.pack_start(sw, True, True, 0)
        bar = Gtk.Box(spacing=4)

        def add(_b, model=model):
            a = win.dialogs.ask_text("Add address or domain", "E-mail address or domain (like @example.com):")
            if a:
                model.append([a.strip().lower()])

        def remove(_b, tv=tv):
            m, it = tv.get_selection().get_selected()
            if it is not None:
                m.remove(it)
        for label, fn in (("Add...", add), ("Remove", remove)):
            b = Gtk.Button(label=label)
            b.connect("clicked", fn)
            bar.pack_start(b, False, False, 0)
        page.pack_start(bar, False, False, 0)
        nb.append_page(page, Gtk.Label(label=title))
        lists[key] = model
    d.add_button("Cancel", Gtk.ResponseType.CANCEL)
    d.add_button("OK", Gtk.ResponseType.OK)

    def done(_d, resp):
        if resp == Gtk.ResponseType.OK:
            for key, model in lists.items():
                store.put(key, [r[0] for r in model])
        d.destroy()
    d.connect("response", done)
    d.show_all()
    d.lists = lists
    return d


# ---------------------------------------------------------------- Quick Steps
ACTIONS = [("read", "Mark as read"), ("unread", "Mark as unread"), ("flag", "Flag message"),
           ("flag-done", "Mark complete"), ("reply", "Reply"), ("forward", "Forward"), ("archive", "Move to Archive"),
           ("delete", "Delete message")]


def quick_step_dialog(win, index=None):
    store = win.store
    steps = store.get("quick-steps", []) or []
    step = dict(steps[index]) if index is not None else {"name": "", "actions": []}
    d, box = _dialog(win, "Edit Quick Step", 420)
    box.pack_start(Gtk.Label(label="Name:", xalign=0), False, False, 0)
    name = Gtk.Entry(text=step["name"])
    box.pack_start(name, False, False, 0)
    box.pack_start(Gtk.Label(label="Actions:", xalign=0), False, False, 4)
    checks = {}
    for k, label in ACTIONS:
        c = Gtk.CheckButton(label=label)
        c.set_active(k in step["actions"])
        box.pack_start(c, False, False, 0)
        checks[k] = c
    folders = Gtk.ComboBoxText()
    folders.append("", "(don't move)")
    for f in win.store.folders():
        if f["role"] != "outbox":
            folders.append(str(f["id"]), "%s - %s" % (win.store.account(f["account"])["email"], win.folder_label(f)))
    mv = [a for a in step["actions"] if a.startswith("move:")]
    folders.set_active_id(mv[0][5:] if mv else "")
    box.pack_start(Gtk.Label(label="Move to folder:", xalign=0), False, False, 4)
    box.pack_start(folders, False, False, 0)
    d.add_button("Cancel", Gtk.ResponseType.CANCEL)
    d.add_button("Save", Gtk.ResponseType.OK)

    def done(_d, resp):
        if resp == Gtk.ResponseType.OK and name.get_text().strip():
            acts = [k for k, _l in ACTIONS if checks[k].get_active() and k not in ("archive", "delete")]
            if folders.get_active_id():
                acts.append("move:" + folders.get_active_id())
            acts += [k for k in ("archive", "delete") if checks[k].get_active()]
            new = {"name": name.get_text().strip(), "actions": acts}
            if index is None:
                steps.append(new)
            else:
                steps[index] = new
            store.put("quick-steps", steps)
        d.destroy()
    d.connect("response", done)
    d.show_all()
    d.parts = {"name": name, "checks": checks, "folders": folders}
    return d


def manage_quick_steps(win):
    store = win.store
    d, box = _dialog(win, "Manage Quick Steps", 420, 320)
    model = Gtk.ListStore(str, int)

    def fill():
        model.clear()
        for i, s in enumerate(store.get("quick-steps", []) or []):
            model.append([s["name"], i])
    fill()
    tv = Gtk.TreeView(model=model)
    tv.set_headers_visible(False)
    tv.append_column(Gtk.TreeViewColumn("", Gtk.CellRendererText(), text=0))
    sw = Gtk.ScrolledWindow()
    sw.add(tv)
    box.pack_start(sw, True, True, 0)
    bar = Gtk.Box(spacing=4)

    def sel():
        m, it = tv.get_selection().get_selected()
        return m[it][1] if it is not None else None

    def edit():
        i = sel()
        if i is not None:
            quick_step_dialog(win, i).connect("destroy", lambda *_: fill())

    def new():
        quick_step_dialog(win).connect("destroy", lambda *_: fill())

    def delete():
        i = sel()
        if i is not None:
            steps = store.get("quick-steps", []) or []
            del steps[i]
            store.put("quick-steps", steps)
            fill()
    for label, fn in (("New...", new), ("Edit...", edit), ("Delete", delete)):
        b = Gtk.Button(label=label)
        b.connect("clicked", lambda *_a, f=fn: f())
        bar.pack_start(b, False, False, 0)
    box.pack_start(bar, False, False, 0)
    d.add_button("Close", Gtk.ResponseType.CLOSE)
    d.connect("response", lambda *_: d.destroy())
    d.show_all()
    return d


# ---------------------------------------------------------------- Rules
def manage_rules(win):
    store = win.store
    d, box = _dialog(win, "Rules and Alerts", 560, 360)
    box.pack_start(Gtk.Label(label="Rules run on new messages in the Inbox, in this order.", xalign=0), False, False, 0)
    model = Gtk.ListStore(bool, str, int)

    def fill():
        model.clear()
        for i, r in enumerate(store.get("rules", []) or []):
            dest = store.folder(r.get("move")) if r.get("move") else None
            desc = r.get("name") or ""
            if dest:
                desc += "  →  " + win.folder_label(dest)
            model.append([r.get("on", True), desc, i])
    fill()
    tv = Gtk.TreeView(model=model)
    tog = Gtk.CellRendererToggle()

    def toggled(_c, path):
        rules = store.get("rules", []) or []
        i = model[path][2]
        rules[i]["on"] = not rules[i].get("on", True)
        store.put("rules", rules)
        fill()
    tog.connect("toggled", toggled)
    tv.append_column(Gtk.TreeViewColumn("On", tog, active=0))
    tv.append_column(Gtk.TreeViewColumn("Rule", Gtk.CellRendererText(), text=1))
    sw = Gtk.ScrolledWindow()
    sw.add(tv)
    box.pack_start(sw, True, True, 0)
    bar = Gtk.Box(spacing=4)

    def new():
        rule_dialog(win).connect("destroy", lambda *_: fill())

    def delete():
        m, it = tv.get_selection().get_selected()
        if it is not None:
            rules = store.get("rules", []) or []
            del rules[m[it][2]]
            store.put("rules", rules)
            fill()

    def run_now():
        n = win.apply_rules(all_inbox=True)
        win.dialogs.info("%d message%s moved." % (n, "" if n == 1 else "s"))
    for label, fn in (("New Rule...", new), ("Delete", delete), ("Run Rules Now", run_now)):
        b = Gtk.Button(label=label)
        b.connect("clicked", lambda *_a, f=fn: f())
        bar.pack_start(b, False, False, 0)
    box.pack_start(bar, False, False, 0)
    d.add_button("Close", Gtk.ResponseType.CLOSE)
    d.connect("response", lambda *_: d.destroy())
    d.show_all()
    return d


def rule_dialog(win):
    store = win.store
    d, box = _dialog(win, "Create Rule", 460)
    box.pack_start(Gtk.Label(label="When I get e-mail with all of the selected conditions", xalign=0), False, False, 0)
    frm = Gtk.Entry()
    frm.set_placeholder_text("from (address or part of it)")
    subj = Gtk.Entry()
    subj.set_placeholder_text("subject contains")
    to = Gtk.Entry()
    to.set_placeholder_text("sent to")
    for w in (frm, subj, to):
        box.pack_start(w, False, False, 0)
    box.pack_start(Gtk.Label(label="Do the following", xalign=0), False, False, 4)
    folders = Gtk.ComboBoxText()
    folders.append("", "(don't move)")
    for f in store.folders():
        if f["role"] != "outbox":
            folders.append(str(f["id"]), "%s - %s" % (store.account(f["account"])["email"], win.folder_label(f)))
    folders.set_active(0)
    box.pack_start(Gtk.Label(label="Move the item to folder:", xalign=0), False, False, 0)
    box.pack_start(folders, False, False, 0)
    read = Gtk.CheckButton(label="Mark it as read")
    flag = Gtk.CheckButton(label="Flag it")
    cat = Gtk.ComboBoxText()
    cat.append("", "(no category)")
    for c in ("Red", "Orange", "Yellow", "Green", "Blue", "Purple"):
        cat.append(c, c + " Category")
    cat.set_active(0)
    for w in (read, flag, cat):
        box.pack_start(w, False, False, 0)
    d.add_button("Cancel", Gtk.ResponseType.CANCEL)
    d.add_button("OK", Gtk.ResponseType.OK)

    def done(_d, resp):
        if resp == Gtk.ResponseType.OK:
            r = {"on": True, "from": frm.get_text().strip().lower(), "subject": subj.get_text().strip().lower(),
                 "to": to.get_text().strip().lower(), "move": int(folders.get_active_id() or 0) or None,
                 "read": read.get_active(), "flag": flag.get_active(), "category": cat.get_active_id() or ""}
            parts = [("from " + r["from"]) if r["from"] else "", ("subject has " + r["subject"]) if r["subject"] else "",
                     ("to " + r["to"]) if r["to"] else ""]
            r["name"] = ", ".join(p for p in parts if p) or "Every message"
            rules = store.get("rules", []) or []
            rules.append(r)
            store.put("rules", rules)
        d.destroy()
    d.connect("response", done)
    d.show_all()
    d.parts = {"from": frm, "subject": subj, "to": to, "folders": folders, "read": read, "flag": flag, "category": cat}
    return d
