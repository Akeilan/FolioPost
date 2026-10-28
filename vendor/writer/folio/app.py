"""Folio Writer application: windows, recent files, settings."""
import json
import os
import subprocess
import sys

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from . import APP_ID, APP_NAME, SHARE, VERSION  # noqa: E402

CONFIG = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
                      "folio-writer")

# Engine settings, written into its private profile.
ENGINE_SETTINGS = [
    ("/org.openoffice.Office.Writer/AutoFunction/Completion", "Enable", "false"),
    ("/org.openoffice.Office.Writer/AutoFunction/Format/ByInput", "ApplyBulletsAfterSpace", "true"),
    ("/org.openoffice.Office.Writer/AutoFunction/Format/ByInput/ApplyNumbering", "Enable", "true"),
    ("/org.openoffice.Office.Common/Filter/Microsoft/Export", "CharBackgroundToHighlighting", "true"),
    ("/org.openoffice.Office.Common/Save/Document", "WarnAlienFormat", "false"),
    ("/org.openoffice.Office.Common/Misc", "ShowTipOfTheDay", "false"),
    ("/org.openoffice.Office.Common/Misc", "FirstRun", "false"),
    ("/org.openoffice.Office.Common/Security/Scripting", "MacroSecurityLevel", "3"),
    ("/org.openoffice.Office.Writer/Content/NonprintingCharacter", "HiddenCharacter", "false"),
    ("/org.openoffice.Office.Writer/Content/Display", "TextBoundaries", "false"),
    ("/org.openoffice.Office.Writer/Content/Display", "SectionBoundaries", "false"),
]
COLOR_SCHEME = "/org.openoffice.Office.UI/ColorScheme/ColorSchemes/" \
               "org.openoffice.Office.UI:ColorScheme['COLOR_SCHEME_LIBREOFFICE_AUTOMATIC']"
HIDDEN_MARKS = ("DocBoundaries", "WriterFieldShadings", "WriterSectionBoundaries",
                "WriterIdxShadings", "TableBoundaries")


AC = "/org.openoffice.Office.Common/AutoCorrect"
BYINPUT = "/org.openoffice.Office.Writer/AutoFunction/Format/ByInput"


def engine_config(settings):
    """Engine options that follow the user's Options choices."""
    g = lambda k, d=True: "true" if settings.get(k, d) else "false"  # noqa: E731
    return [
        (AC, "CapitalAtStartSentence", g("ac_caps_first")),
        (AC, "TwoCapitalsAtStart", g("ac_two_caps")),
        (AC, "ReplaceDoubleQuote", g("ac_quotes")),
        (AC, "ReplaceSingleQuote", g("ac_quotes")),
        (AC, "SetInetAttribute", g("ac_urls")),
        (AC, "ChangeOrdinalNumber", g("ac_ordinals")),
        (AC, "ChangeDash", g("ac_dashes")),
        (AC, "UseReplacementTable", g("ac_replace")),
        (BYINPUT, "ApplyBulletsAfterSpace", g("ac_bullets", settings.get("ac_lists", True))),
        (BYINPUT + "/ApplyNumbering", "Enable", g("ac_numbers", settings.get("ac_lists", True))),
        (AC, "ChangeUnderlineWeight", g("ac_bold_italic", True)),
        (AC, "CorrectAccidentalCapsLock", g("ac_capslock")),
        (BYINPUT, "ChangeToBorders", g("ac_borders")),
        (BYINPUT, "ChangeToTable", g("ac_tables")),
        (BYINPUT, "ChangeDash", g("ac_dashes")),
        ("/org.openoffice.Office.Linguistic/SpellChecking", "IsSpellAuto", g("auto_spell")),
        ("/org.openoffice.Office.Linguistic/GrammarChecking", "IsAutoCheck", g("auto_grammar")),
        ("/org.openoffice.Office.Common/Security/Scripting", "HyperlinksWithCtrlClick",
         g("ctrl_click_links")),
    ]


def apply_engine_config(settings):
    """Change the running engine's options (no restart needed)."""
    from . import bridge
    if bridge.ctx is None:
        return False
    try:
        import uno
        prov = bridge.create("com.sun.star.configuration.ConfigurationProvider")
        groups = {}
        for path, prop, value in engine_config(settings):
            groups.setdefault(path, []).append((prop, value == "true"))
        for path, props in groups.items():
            arg = uno.createUnoStruct("com.sun.star.beans.PropertyValue")
            arg.Name, arg.Value = "nodepath", path
            acc = prov.createInstanceWithArguments(
                "com.sun.star.configuration.ConfigurationUpdateAccess", (arg,))
            for prop, value in props:
                try:
                    acc.setPropertyValue(prop, value)
                except Exception as e:
                    print("config", path, prop, e)
            acc.commitChanges()
        return True
    except Exception as e:
        print("engine config:", e)
        return False


def install_autocorrect(user):
    try:
        from .autocorrect import install
        install(user)
    except Exception as e:
        print("autocorrect:", e)


def _xcu_item(path, prop, value):
    return ('<item oor:path="%s"><prop oor:name="%s" oor:op="fuse"><value>%s</value>'
            '</prop></item>' % (path, prop, value))


def prepare_engine_profile(profile, settings=None):
    user = os.path.join(profile, "user")
    os.makedirs(user, exist_ok=True)
    install_autocorrect(user)
    fn = os.path.join(user, "registrymodifications.xcu")
    stamp = os.path.join(profile, "folio.version")
    conf = engine_config(settings or {})
    import hashlib
    key = VERSION + " " + hashlib.sha1(repr(ENGINE_SETTINGS + conf).encode()).hexdigest()[:12]
    if os.path.exists(fn) and os.path.exists(stamp):
        with open(stamp) as f:
            if f.read().strip() == key:
                return
    items = [_xcu_item(p, k, v) for p, k, v in ENGINE_SETTINGS + conf]
    for entry in HIDDEN_MARKS:
        items.append(_xcu_item(COLOR_SCHEME + "/" + entry, "IsVisible", "false"))
    body = ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<oor:items xmlns:oor="http://openoffice.org/2001/registry" '
            'xmlns:xs="http://www.w3.org/2001/XMLSchema" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\n%s\n</oor:items>\n'
            % "\n".join(items))
    with open(fn, "w", encoding="utf-8") as f:
        f.write(body)
    with open(stamp, "w") as f:
        f.write(key + "\n")


def _paper_is_letter():
    try:
        out = subprocess.run(["locale", "-k", "LC_PAPER"], capture_output=True,
                             text=True, timeout=5).stdout
        return "height=279" in out
    except Exception:
        return False


class FolioApp(Gtk.Application):
    def __init__(self):
        Gtk.Application.__init__(self, application_id=APP_ID,
                                 flags=Gio.ApplicationFlags.HANDLES_OPEN)
        GLib.set_application_name(APP_NAME)
        GLib.set_prgname("folio-writer")
        os.makedirs(CONFIG, exist_ok=True)
        self.engine_profile = os.path.join(CONFIG, "engine")
        self.settings_path = os.path.join(CONFIG, "settings.json")
        self.settings = self._load_settings()
        prepare_engine_profile(self.engine_profile, self.settings)
        from .widgets import set_units
        set_units(self.settings.get("units"))
        self.windows = []
        self._untitled = 0
        self.config_dir = CONFIG
        self.clip_history = []
        self._clip = None
        self.autorecover_dir = os.path.join(CONFIG, "autorecover")
        os.makedirs(self.autorecover_dir, exist_ok=True)

    # -------------------------------------------------------- settings
    def _load_settings(self):
        try:
            with open(self.settings_path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {"recent": [], "author": os.environ.get("USER", "")}

    def save_settings(self):
        tmp = self.settings_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.settings, f, indent=1)
        os.replace(tmp, self.settings_path)

    def add_recent(self, path):
        path = os.path.abspath(path)
        rec = [p for p in self.settings.get("recent", []) if p != path]
        rec.insert(0, path)
        self.settings["recent"] = rec[:30]
        self.save_settings()
        try:
            Gtk.RecentManager.get_default().add_item("file://" + path)
        except Exception:
            pass

    def recent(self):
        n = self.settings.get("recent_count", 50)
        return [p for p in self.settings.get("recent", []) if os.path.exists(p)][:n]

    def pinned(self):
        return [p for p in self.settings.get("pinned", []) if os.path.exists(p)]

    def toggle_pin(self, path):
        pins = self.settings.get("pinned", [])
        if path in pins:
            pins.remove(path)
        else:
            pins.insert(0, path)
        self.settings["pinned"] = pins
        self.save_settings()

    def remove_recent(self, path):
        self.settings["recent"] = [p for p in self.settings.get("recent", []) if p != path]
        self.save_settings()

    def user_name(self):
        name = self.settings.get("user_name")
        if name:
            return name
        try:
            import pwd
            gecos = pwd.getpwuid(os.getuid()).pw_gecos.split(",")[0].strip()
            if gecos:
                return gecos
        except Exception:
            pass
        return os.environ.get("USER", "Author")

    def apply_settings(self):
        from .widgets import set_units
        set_units(self.settings.get("units"))
        apply_engine_config(self.settings)
        prepare_engine_profile(self.engine_profile, self.settings)
        for w in self.windows:
            w.schedule_autorecover()
            w.apply_view_settings()
            try:
                w.build_qat()
                w.qat.show_all()
                w.status.apply_items()
            except Exception as e:
                print("apply settings:", e)
        self.apply_theme()

    def apply_theme(self):
        theme = self.settings.get("theme", "Colorful")
        screen = Gdk.Screen.get_default()
        for w in self.windows:
            ctx = w.get_style_context()
            for t in ("theme-darkgray", "theme-black", "theme-white"):
                ctx.remove_class(t)
            if theme != "Colorful":
                ctx.add_class("theme-" + theme.lower().replace(" ", ""))

    # -------------------------------------------------------- templates
    def user_template_path(self):
        name = "Normal-Letter.ott" if _paper_is_letter() else "Normal-A4.ott"
        return os.path.join(CONFIG, "templates", name)

    def normal_template(self):
        name = "Normal-Letter.ott" if _paper_is_letter() else "Normal-A4.ott"
        user = self.user_template_path()
        if os.path.exists(user):
            return user
        for base in (os.path.join(SHARE, "templates"),
                     os.path.join(os.path.dirname(__file__), "..", "..", "share", "templates")):
            p = os.path.join(base, name)
            if os.path.exists(p):
                return os.path.abspath(p)
        raise FileNotFoundError(name)

    def _edit_normal_template(self, fn):
        """Open the Normal template hidden, let fn(doc) change it, store it as
        the user's Normal template."""
        from . import bridge
        from .engine import file_url
        src = self.normal_template()
        dst = self.user_template_path()
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if bridge.ctx is None:
            return False
        desktop = bridge.create("com.sun.star.frame.Desktop")
        doc = desktop.loadComponentFromURL(file_url(src), "_blank", 0,
                                           (bridge.prop("Hidden", True),
                                            bridge.prop("AsTemplate", False)))
        try:
            fn(doc)
            doc.storeToURL(file_url(dst), (bridge.prop("FilterName", "writer8_template"),
                                           bridge.prop("Overwrite", True)))
        finally:
            doc.close(True)
        return True

    def set_default_font(self, name, size):
        from . import docapi
        try:
            self._edit_normal_template(lambda d: docapi.set_default_font(d, name, size))
        except Exception as e:
            print("default font:", e)

    def save_styles_as_default(self, engine):
        import tempfile
        from . import bridge
        from .engine import file_url
        tmp = tempfile.mkdtemp(prefix="folio-styles-")
        path = os.path.join(tmp, "styles.odt")
        if not engine.save_as(path, "odt", keep=False):
            return

        def load(doc):
            doc.getStyleFamilies().loadStylesFromURL(file_url(path), (
                bridge.prop("OverwriteStyles", True), bridge.prop("LoadTextStyles", True),
                bridge.prop("LoadPageStyles", True), bridge.prop("LoadNumberingStyles", True)))
        try:
            self._edit_normal_template(load)
        except Exception as e:
            print("save styles:", e)
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def remember_style(self, name, family, props):
        # New documents based on the template: copy the whole style set over
        for w in self.windows:
            if w.engine.model is not None:
                self.save_styles_as_default(w.engine)
                break

    # -------------------------------------------------------- autorecover
    def _recover_path(self, win):
        return os.path.join(self.autorecover_dir, "%s-%d.odt" % (
            "".join(c for c in win.doc_name() if c.isalnum() or c in " -_") or "Document",
            id(win) % 100000))

    def write_autorecover(self, win):
        p = self._recover_path(win)
        if win.engine.save_as(p, "odt", keep=False):
            with open(p + ".info", "w", encoding="utf-8") as f:
                json.dump({"name": win.doc_name(), "path": win.engine.path or ""}, f)

    def clear_autorecover(self, win):
        p = self._recover_path(win)
        for f in (p, p + ".info"):
            try:
                os.remove(f)
            except OSError:
                pass

    def recovered_files(self):
        out = []
        for f in sorted(os.listdir(self.autorecover_dir)):
            if f.endswith(".odt"):
                p = os.path.join(self.autorecover_dir, f)
                info = {}
                try:
                    with open(p + ".info", encoding="utf-8") as fh:
                        info = json.load(fh)
                except (OSError, ValueError):
                    pass
                out.append((p, info))
        return out

    def next_untitled(self):
        self._untitled += 1
        return "Document%d" % self._untitled

    # -------------------------------------------------------- windows
    def do_startup(self):
        Gtk.Application.do_startup(self)
        css = Gtk.CssProvider()
        css.load_from_path(os.path.join(os.path.dirname(__file__), "theme.css"))
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), css,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_activate(self):
        if self.windows:
            self.windows[-1].present()
            return
        rec = self.recovered_files()
        win = self.new_window()
        script = os.environ.get("FOLIO_TEST_SCRIPT")
        if script:
            def run_script():
                ns = {"app": self, "win": win, "GLib": GLib, "Gtk": Gtk}
                with open(script) as f:
                    exec(compile(f.read(), script, "exec"), ns)
                return False
            GLib.timeout_add(6000, run_script)
        if rec:
            GLib.timeout_add(1500, self._offer_recovery, win, rec)

    def _offer_recovery(self, win, rec):
        names = ", ".join(info.get("name") or os.path.basename(p) for p, info in rec)
        if win.dialogs.confirm("%s recovered the following documents that weren't saved: %s.\n\n"
                               "Do you want to open them?" % (APP_NAME, names),
                               yes="Open", no="Discard", title="Document Recovery"):
            for p, info in rec:
                w = self.new_window(p)
                w.untitled = (info.get("name") or "Document") + " (Recovered)"
                w.engine.is_new = True
                GLib.timeout_add(1500, w.update_title)
        else:
            for p, _info in rec:
                for f in (p, p + ".info"):
                    try:
                        os.remove(f)
                    except OSError:
                        pass
        return False

    def do_open(self, files, n_files, hint):
        for f in files:
            path = f.get_path()
            if path:
                self.open_path(path)

    def new_window(self, path=None, template=None):
        from .window import DocWindow
        win = DocWindow(self, path, template)
        self.windows.append(win)
        self.apply_theme()
        win.present()
        return win

    def open_path(self, path, from_window=None):
        for w in self.windows:
            if w.engine.path == os.path.abspath(path):
                w.present()
                return w
        # reuse an untouched new document, as the reference app does
        if from_window is not None and from_window.engine.is_new and \
                not from_window.engine.modified:
            from_window.open_file(path)
            return from_window
        return self.new_window(path)

    def clipboard(self):
        if self._clip is None:
            from .clipboard import Clipboard
            self._clip = Clipboard()
        return self._clip

    def window_closed(self, win):
        try:
            self.save_settings()
        except OSError:
            pass
        if win in self.windows:
            self.windows.remove(win)
        if not self.windows:
            try:
                if self._clip is not None:
                    self._clip.keep_after_exit()
            except Exception:
                pass
            GLib.idle_add(self.quit)


MIME_DEFAULTS = [
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.template",
    "application/msword", "application/rtf", "text/rtf",
]


def make_default():
    for t in MIME_DEFAULTS:
        subprocess.run(["xdg-mime", "default", "folio-writer.desktop", t],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv)
    if "--version" in argv:
        print("%s %s" % (APP_NAME, VERSION))
        return 0
    if "--make-default" in argv:
        make_default()
        print("%s is now the default for .docx, .doc, .dotx and .rtf files." % APP_NAME)
        return 0
    if "--reset-settings" in argv:
        import shutil
        for name in ("settings.json", "templates", "engine"):
            p = os.path.join(CONFIG, name)
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
            elif os.path.exists(p):
                os.remove(p)
        print("Settings reset.")
        return 0
    app = FolioApp()
    if not app.settings.get("mime_registered") and os.path.exists(
            "/usr/share/applications/folio-writer.desktop"):
        make_default()
        app.settings["mime_registered"] = True
        app.save_settings()
    code = app.run(argv)
    sys.stdout.flush()
    sys.stderr.flush()
    # Everything is saved by now; skip the engine's own (slow, noisy) teardown.
    os._exit(code or 0)
