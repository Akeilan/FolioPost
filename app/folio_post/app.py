"""Folio Post application: the store, accounts' syncing in the background, windows."""
import json
import os
import subprocess
import sys
import threading
import time
import urllib.parse

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from . import APP_ID, APP_NAME, VERSION  # noqa: E402

GLib.set_prgname(APP_ID)
GLib.set_application_name(APP_NAME)
Gdk.set_program_class(APP_ID)

CONFIG = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "folio-post")
DATA = os.environ.get("FOLIO_POST_DATA") or os.path.join(
    os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "folio-post")


class PostApp(Gtk.Application):
    def __init__(self):
        flags = Gio.ApplicationFlags.HANDLES_OPEN
        if os.environ.get("FOLIO_POST_NON_UNIQUE"):
            flags |= Gio.ApplicationFlags.NON_UNIQUE
        # one Post at a time (one store, one sync); a second start hands its links and files to the first
        Gtk.Application.__init__(self, application_id=APP_ID, flags=flags)
        self.windows = []
        self.composers = []
        self.settings = self._load_settings()
        from .store import Store
        from .sync import Secrets, Syncer
        from .oauth import TokenSource
        self.store = Store(DATA)
        self.secrets = Secrets(os.path.join(CONFIG, "secrets.json"))
        self.tokens = TokenSource(self.store, self.secrets)
        self.syncer = Syncer(self.store, self.secrets, self.tokens)
        self.syncer.offline = bool(self.settings.get("offline"))
        from .caldav import CalendarSync
        from .reminders import Reminders
        self.calsync = CalendarSync(self.store, self.secrets, self.tokens)
        from .carddav import ContactSync
        self.contactsync = ContactSync(self.store, self.secrets, self.tokens)
        self.reminders = Reminders(self)
        self.queue = []
        self.queue_lock = threading.Lock()
        self.queue_event = threading.Event()
        self.worker = threading.Thread(target=self._work, daemon=True)
        self.worker.start()
        self._timer = None

    # ------------------------------------------------------------ settings
    def _load_settings(self):
        try:
            with open(os.path.join(CONFIG, "settings.json")) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def save_settings(self):
        os.makedirs(CONFIG, exist_ok=True)
        tmp = os.path.join(CONFIG, "settings.json.tmp")
        with open(tmp, "w") as f:
            json.dump(self.settings, f, indent=1)
        os.replace(tmp, os.path.join(CONFIG, "settings.json"))

    def setting(self, key, default=None):
        return self.settings.get(key, default)

    def set_setting(self, key, value):
        self.settings[key] = value
        try:
            self.save_settings()
        except OSError:
            pass

    def user_name(self):
        return self.settings.get("author") or os.environ.get("USER", "")

    # ------------------------------------------------------------ background work
    def _work(self):
        while True:
            self.queue_event.wait()
            with self.queue_lock:
                job = self.queue.pop(0) if self.queue else None
                if not self.queue:
                    self.queue_event.clear()
            if job is None:
                continue
            fn, done = job
            try:
                r = fn()
                err = None
            except Exception as e:
                import traceback
                traceback.print_exc()
                r, err = None, e
            if done is not None:
                GLib.idle_add(lambda d=done, r=r, e=err: (d(r, e), False)[1])

    def background(self, fn, done=None):
        with self.queue_lock:
            self.queue.append((fn, done))
            self.queue_event.set()

    def busy(self):
        with self.queue_lock:
            return bool(self.queue) or self.syncer.lock.locked()

    def send_receive(self, aids=None, folders=None, done=None):
        aids = aids or [a["id"] for a in self.store.accounts() if a["kind"] != "local"]

        def job():
            r = [self.syncer.sync_account(a, folders) for a in aids]
            if folders is None and not self.syncer.offline:
                self.calsync.sync_all()
                self.contactsync.sync_all()
            return r

        def finished(r, e):
            for w in list(self.windows):
                try:
                    w.after_sync()
                except Exception:
                    import traceback
                    traceback.print_exc()
            if done is not None:
                done(r, e)
        self.background(job, finished)

    def cancel_all(self):
        with self.queue_lock:
            self.queue = []
            self.queue_event.clear()

    def schedule_sync(self):
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = None
        mins = int(self.settings.get("sync_minutes", 5) or 0)
        if mins > 0 and not os.environ.get("FOLIO_POST_NO_AUTOSYNC"):
            self._timer = GLib.timeout_add_seconds(mins * 60, self._auto_sync)

    def _auto_sync(self):
        if not self.syncer.offline and not self.busy():
            self.send_receive()
        return True

    def set_offline(self, on):
        self.syncer.offline = on
        self.set_setting("offline", on)
        for w in self.windows:
            w.update_status()
        if not on:
            self.send_receive()

    # ------------------------------------------------------------ life cycle
    def do_startup(self):
        Gtk.Application.do_startup(self)
        css = Gtk.CssProvider()
        css.load_from_path(os.path.join(os.path.dirname(__file__), "theme.css"))
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        extra = os.path.join(os.path.dirname(__file__), "post.css")
        if os.path.exists(extra):
            css2 = Gtk.CssProvider()
            css2.load_from_path(extra)
            Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), css2,
                                                     Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        # X2-01: every window Post opens wears Post's colours, so a dark or coloured desktop theme
        # never shows through (folio-own: all of them; folio-dialog: dialogs and small windows)
        from gi.repository import GObject

        def _own(w, *a):
            try:
                if w.get_window_type() == Gtk.WindowType.TOPLEVEL and not isinstance(w, Gtk.FileChooserDialog):
                    ctx = w.get_style_context()
                    ctx.add_class("folio-own")
                    if isinstance(w, Gtk.Dialog) or not hasattr(w, "ribbon"):
                        ctx.add_class("folio-dialog")
            except Exception:
                pass
            return True
        GObject.add_emission_hook(Gtk.Window, "realize", _own)
        # X2-04: the same text height on Ubuntu 24.04, whose Carlito has taller line metrics
        from . import fontfix
        fontfix.install()
        from . import appearance
        self._dark_css = Gtk.CssProvider()
        self._dark_css.load_from_path(os.path.join(os.path.dirname(__file__), "theme-dark.css"))
        appearance.apply_initial()
        self._apply_dark(appearance.is_dark())
        appearance.on_change(self._apply_dark)
        self.schedule_sync()
        if not os.environ.get("FOLIO_POST_NO_REMINDERS"):
            self.reminders.start()

    def _apply_dark(self, dark):
        screen = Gdk.Screen.get_default()
        if screen is None:
            return
        if dark:
            Gtk.StyleContext.add_provider_for_screen(screen, self._dark_css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 2)
        else:
            Gtk.StyleContext.remove_provider_for_screen(screen, self._dark_css)
        from . import icons
        icons.restyle()
        for w in Gtk.Window.list_toplevels():
            w.queue_draw()

    def do_activate(self):
        if self.windows:
            self.windows[-1].present()
            return
        win = self.new_window()
        self._maybe_script(win)

    def _maybe_script(self, win):
        script = os.environ.get("FOLIO_TEST_SCRIPT")
        if script:
            def run_script():
                ns = {"app": self, "win": win, "GLib": GLib, "Gtk": Gtk, "Gdk": Gdk}
                try:
                    with open(script) as f:
                        exec(compile(f.read(), script, "exec"), ns)
                except Exception:
                    import traceback
                    traceback.print_exc()
                    sys.stdout.flush()
                    os._exit(3)
                return False
            GLib.timeout_add(int(os.environ.get("FOLIO_TEST_DELAY", "2500")), run_script)

    def do_open(self, files, n_files, hint):
        win = self.windows[-1] if self.windows else self.new_window()
        for f in files:
            uri = f.get_uri()
            if uri.startswith("mailto:"):
                self.compose_mailto(uri)
                continue
            path = f.get_path()
            if path and path.lower().endswith((".eml", ".msg")):
                win.open_message_file(path)
        self._maybe_script(win)

    def new_window(self):
        from .window import PostWindow
        win = PostWindow(self)
        self.windows.append(win)
        win.present()
        if not self.store.accounts() and not os.environ.get("FOLIO_POST_NO_WELCOME"):
            GLib.idle_add(lambda: (win.run("add-account"), False)[1])
        return win

    def window_closed(self, win):
        if win in self.windows:
            self.windows.remove(win)
        if not self.windows and not self.composers:
            GLib.idle_add(self.quit)

    def composer_closed(self, c):
        if c in self.composers:
            self.composers.remove(c)
        if not self.windows and not self.composers:
            GLib.idle_add(self.quit)

    # ------------------------------------------------------------ writing
    def compose(self, **kw):
        from .compose import ComposeWindow
        c = ComposeWindow(self, **kw)
        self.composers.append(c)
        c.present()
        return c

    def compose_mailto(self, uri):
        u = urllib.parse.urlparse(uri)
        to = urllib.parse.unquote(u.path)
        q = urllib.parse.parse_qs(u.query)
        get = lambda k: q.get(k, q.get(k.capitalize(), [""]))[0]  # noqa: E731
        to = ", ".join(x for x in [to, get("to")] if x)
        return self.compose(to=to, cc=get("cc"), bcc=get("bcc"), subject=get("subject"), body_text=get("body"),
                            attach=q.get("attach", []) + q.get("attachment", []))


MIME_DEFAULTS = ["x-scheme-handler/mailto", "message/rfc822"]


def make_default():
    for t in MIME_DEFAULTS:
        subprocess.run(["xdg-mime", "default", APP_ID + ".desktop", t], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def attach_argv(argv):
    """folio-post --attach FILE... (Send as attachment from the other Folio apps): the files go in a
    mailto: link, so a Post that is already running opens the new message."""
    if "--attach" not in argv:
        return list(argv)
    i = argv.index("--attach")
    files = [os.path.abspath(a) for a in argv[i + 1:]]
    return argv[:i] + ["mailto:?" + "&".join("attach=" + urllib.parse.quote("file://" + f) for f in files)]


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv)
    if "--version" in argv:
        print("%s %s" % (APP_NAME, VERSION))
        return 0
    if "--list-contacts" in argv:
        from .merge import main_list
        return main_list("--json" in argv)
    if "--send-merge" in argv:
        from .merge import main_send
        i = argv.index("--send-merge")
        if i + 1 >= len(argv):
            print("usage: folio-post --send-merge FILE.json [--json]")
            return 2
        code = main_send(argv[i + 1], "--json" in argv)
        sys.stdout.flush()
        os._exit(code)
    if "--make-default" in argv:
        make_default()
        print("%s is now the default mail app." % APP_NAME)
        return 0
    if "--reset-settings" in argv:
        p = os.path.join(CONFIG, "settings.json")
        if os.path.exists(p):
            os.remove(p)
        print("Settings reset.")
        return 0
    # "Send as attachment" from the other apps: folio-post --attach FILE... becomes a mailto: link the running
    # Post (or this one) opens
    argv = attach_argv(argv)
    app = PostApp()
    code = app.run(argv)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code or 0)
