"""View > Macros: record what you do (ribbon commands, shortcuts, typing and
editing keys) and play it back. Macros are kept with your settings and can
have a keyboard shortcut, as in the original's Record Macro."""
import json

from gi.repository import Gdk, GLib, Gtk

from .widgets import FDialog, grid, listbox

# Gdk key -> engine key code (com.sun.star.awt.Key)
AWT = {Gdk.KEY_Return: 1280, Gdk.KEY_KP_Enter: 1280, Gdk.KEY_Escape: 1281,
       Gdk.KEY_Tab: 1282, Gdk.KEY_ISO_Left_Tab: 1282, Gdk.KEY_BackSpace: 1283,
       Gdk.KEY_Delete: 1286, Gdk.KEY_Down: 1024, Gdk.KEY_Up: 1025, Gdk.KEY_Left: 1026,
       Gdk.KEY_Right: 1027, Gdk.KEY_Home: 1028, Gdk.KEY_End: 1029, Gdk.KEY_Page_Up: 1030,
       Gdk.KEY_Page_Down: 1031, Gdk.KEY_Insert: 1285}
SHIFT, MOD1, MOD2 = 4096, 8192, 16384


def store(app):
    m = app.settings.get("macros")
    if not isinstance(m, dict):
        m = {}
        app.settings["macros"] = m
    return m


class Recorder:
    def __init__(self, win):
        self.win = win
        self.steps = None
        self.paused = False
        self.name = None

    suspended = False

    @property
    def active(self):
        return self.steps is not None and not self.paused and not self.suspended

    def menu(self, control, label):
        """A drop-down menu item of a ribbon button."""
        from .customize import catalog
        key = next((k for k, (_l, _i, c) in catalog(self.win).items() if c is control), None)
        if key:
            self.steps.append(["menu", [key, label]])

    # ------------------------------------------------------------ recording
    def action(self, action, control=None):
        if not self.active or action in ("record-macro", "stop-recording", "pause-recording",
                                         "view-macros", "macros"):
            return
        if callable(action):
            if control is None:
                return
            from .customize import catalog
            key = next((k for k, (_l, _i, c) in catalog(self.win).items() if c is control), None)
            if key:
                self.steps.append(["control", key])
            return
        try:
            json.dumps(action)
        except (TypeError, ValueError):
            return
        self.steps.append(["run", list(action) if isinstance(action, tuple) else action])

    def key(self, event):
        """A key the document is about to get."""
        if not self.active:
            return
        st = event.state
        ctrl = bool(st & Gdk.ModifierType.CONTROL_MASK)
        alt = bool(st & Gdk.ModifierType.MOD1_MASK)
        shift = bool(st & Gdk.ModifierType.SHIFT_MASK)
        kv = event.keyval
        if kv in AWT:
            code = AWT[kv] | (SHIFT if shift else 0) | (MOD1 if ctrl else 0) | \
                (MOD2 if alt else 0)
            self.steps.append(["key", code])
            return
        ch = Gdk.keyval_to_unicode(kv)
        if ch and not ctrl and not alt:
            c = chr(ch)
            if self.steps and self.steps[-1][0] == "text":
                self.steps[-1][1] += c
            else:
                self.steps.append(["text", c])

    # ------------------------------------------------------------ control
    def start(self, name):
        self.name = name
        self.steps = []
        self.paused = False
        self.win.status.set_recording(True)
        self.win.ribbon.update("folio:recording", "true")

    def stop(self):
        if self.steps is None:
            return
        macros = store(self.win.app)
        entry = macros.get(self.name, {})
        entry["steps"] = self.steps
        macros[self.name] = entry
        self.win.app.save_settings()
        self.win.status.flash("Macro “%s” recorded (%d step%s)." % (
            self.name, len(self.steps), "" if len(self.steps) == 1 else "s"))
        self.steps = None
        self.paused = False
        self.win.status.set_recording(False)
        self.win.ribbon.update("folio:recording", "false")

    def pause(self):
        if self.steps is not None:
            self.paused = not self.paused
            self.win.status.flash("Recording paused." if self.paused else "Recording resumed.")


def play(win, name):
    macro = store(win.app).get(name)
    if not macro:
        win.dialogs.message("The macro “%s” doesn't exist." % name)
        return
    steps = list(macro.get("steps", []))
    from .customize import catalog
    controls = None

    def nxt():
        nonlocal controls
        if not steps:
            return False
        kind, arg = steps.pop(0)
        try:
            if kind == "run":
                win.run(tuple(arg) if isinstance(arg, list) else arg)
            elif kind == "control":
                if controls is None:
                    controls = catalog(win)
                c = controls.get(arg)
                if c is not None:
                    c[2].run()
            elif kind == "menu":
                if controls is None:
                    controls = catalog(win)
                c = controls.get(arg[0])
                items = getattr(c[2], "menu", None) if c is not None else None
                if isinstance(items, (list, tuple)):
                    for it in items:
                        if it is not None and not isinstance(it, Gtk.Widget) and \
                                it[0] != "#" and it[0] == arg[1] and it[1]:
                            it[1]()
                            break
            elif kind == "text":
                win.actions.insert_text(arg)
            elif kind == "key":
                win.engine.post_key(int(arg))
        except Exception as e:
            print("macro step:", kind, arg, e)
        GLib.timeout_add(40, nxt)
        return False
    win.engine.sync(lambda: GLib.idle_add(nxt))


def record_dialog(win):
    rec = win.macro_recorder
    if rec.steps is not None:
        rec.stop()
        return
    macros = store(win.app)
    n = 1
    while "Macro%d" % n in macros:
        n += 1
    d = FDialog(win, "Record Macro")
    name = Gtk.Entry(text="Macro%d" % n)
    desc = Gtk.Entry()
    key_btn = Gtk.Button.new_with_mnemonic("_Keyboard")
    shortcut = {"spec": None}
    key_lab = Gtk.Label(label="", xalign=0)

    def pick_key(*_):
        spec = _ask_shortcut(win)
        if spec:
            shortcut["spec"] = spec
            key_lab.set_text("Shortcut: " + spec)
    key_btn.connect("clicked", pick_key)
    d.add(grid([["_Macro name:", name], ["_Description:", desc]]))
    row = Gtk.Box(spacing=8)
    row.pack_start(Gtk.Label(label="Assign macro to:"), False, False, 0)
    row.pack_start(key_btn, False, False, 0)
    row.pack_start(key_lab, False, False, 0)
    d.add(row)
    d.add(Gtk.Label(label="Store macro in: All Documents", xalign=0))
    if d.ask() == Gtk.ResponseType.OK:
        nm = "".join(c for c in name.get_text().strip() if c.isalnum() or c == "_") or \
            "Macro%d" % n
        macros[nm] = {"desc": desc.get_text(), "steps": [], "key": shortcut["spec"]}
        if shortcut["spec"]:
            keys = win.app.settings.setdefault("user_keys", {})
            keys[shortcut["spec"]] = ["run-macro", nm]
            win.keymap.set_user_keys(keys)
        win.app.save_settings()
        rec.start(nm)
        win.status.flash("Recording “%s”. Use Macros > Stop Recording when done." % nm)
    d.done()


def _ask_shortcut(win):
    d = FDialog(win, "Customize Keyboard")
    d.add(Gtk.Label(label="Press new shortcut key:", xalign=0))
    e = Gtk.Entry()
    e.set_placeholder_text("Press keys")
    spec = {"v": None}

    def key(w, ev):
        name = Gdk.keyval_name(ev.keyval) or ""
        if name in ("Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R"):
            return True
        parts = []
        if ev.state & Gdk.ModifierType.CONTROL_MASK:
            parts.append("ctrl")
        if ev.state & Gdk.ModifierType.MOD1_MASK:
            parts.append("alt")
        if ev.state & Gdk.ModifierType.SHIFT_MASK:
            parts.append("shift")
        parts.append(name.lower() if len(name) == 1 else name)
        spec["v"] = "+".join(parts)
        w.set_text(spec["v"].replace("ctrl", "Ctrl").replace("alt", "Alt")
                   .replace("shift", "Shift"))
        return True
    e.connect("key-press-event", key)
    d.add(e)
    r = d.ask()
    d.done()
    return spec["v"] if r == Gtk.ResponseType.OK else None


def view_dialog(win):
    macros = store(win.app)
    d = FDialog(win, "Macros", buttons=(("Run", 10), ("Close", Gtk.ResponseType.CANCEL)))
    name = Gtk.Entry()
    sw, tv, st = listbox(sorted(macros), height=180, width=320,
                         on_activate=lambda *_: d.response(10))
    desc = Gtk.Label(xalign=0)
    desc.set_line_wrap(True)
    steps_lab = Gtk.Label(xalign=0)
    steps_lab.get_style_context().add_class("dim-label")

    def picked(sel):
        mdl, it = sel.get_selected()
        if it is None:
            return
        n = mdl[it][0]
        name.set_text(n)
        mac = macros.get(n, {})
        desc.set_text(mac.get("desc") or "")
        k = mac.get("key")
        steps_lab.set_text("%d step%s%s" % (len(mac.get("steps", [])),
                                            "" if len(mac.get("steps", [])) == 1 else "s",
                                            ("   Shortcut: %s" % k) if k else ""))
    tv.get_selection().connect("changed", picked)
    d.add(grid([["_Macro name:", name]]))
    body = Gtk.Box(spacing=8)
    body.pack_start(sw, True, True, 0)
    btns = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    for label, cb in (("_Step Into", lambda: show_steps(win, name.get_text())),
                      ("_Delete", lambda: delete(name.get_text())),
                      ("_Record...", lambda: (d.response(Gtk.ResponseType.CANCEL),
                                             GLib.idle_add(lambda: (record_dialog(win),
                                                                    False)[1])))):
        b = Gtk.Button.new_with_mnemonic(label)
        b.connect("clicked", lambda _b, cb=cb: cb())
        btns.pack_start(b, False, False, 0)
    body.pack_start(btns, False, False, 0)
    d.add(body)
    d.add(desc)
    d.add(steps_lab)

    def delete(n):
        if n in macros and win.dialogs.confirm("Delete the macro “%s”?" % n,
                                               yes="Yes", no="No"):
            k = macros[n].get("key")
            macros.pop(n)
            if k:
                keys = win.app.settings.get("user_keys", {})
                keys.pop(k, None)
                win.keymap.set_user_keys(keys)
            win.app.save_settings()
            for row in st:
                if row[0] == n:
                    st.remove(row.iter)
                    break
    if len(st):
        tv.get_selection().select_path(Gtk.TreePath(0))
    while True:
        r = d.ask()
        if r == 10:
            n = name.get_text()
            d.done()
            play(win, n)
            return
        break
    d.done()


def show_steps(win, name):
    """A plain list of the recorded steps, editable as text."""
    macros = store(win.app)
    mac = macros.get(name)
    if mac is None:
        return
    d = FDialog(win, "Macro: " + name)
    tv = Gtk.TextView()
    tv.set_monospace(True)
    tv.get_buffer().set_text("\n".join(json.dumps(s, ensure_ascii=False)
                                       for s in mac.get("steps", [])))
    sw = Gtk.ScrolledWindow()
    sw.set_size_request(480, 300)
    sw.add(tv)
    d.add(sw, expand=True)
    if d.ask() == Gtk.ResponseType.OK:
        b = tv.get_buffer()
        out = []
        for line in b.get_text(*b.get_bounds(), False).splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                s = json.loads(line)
                if isinstance(s, list) and len(s) == 2:
                    out.append(s)
            except ValueError:
                pass
        mac["steps"] = out
        win.app.save_settings()
    d.done()
