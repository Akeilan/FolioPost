"""Light or dark, as the desktop is set (S-08).

The desktop's choice is read from the freedesktop settings portal (org.freedesktop.appearance
color-scheme, which GNOME, KDE and others publish), then GNOME's own setting, then the GTK theme's
name. FOLIO_THEME=dark or FOLIO_THEME=light overrides it. Changes on the desktop apply at once.
"""

import os

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk  # noqa: E402

_dark = None
_listeners = []
_watching = False
_proxy = None
_gsettings = None


def _portal_scheme():
    """1 = prefer dark, 2 = prefer light, 0 = no preference, None = no portal."""
    global _proxy
    try:
        if _proxy is None:
            _proxy = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SESSION, Gio.DBusProxyFlags.DO_NOT_AUTO_START_AT_CONSTRUCTION, None,
                "org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop",
                "org.freedesktop.portal.Settings", None)
        v = _proxy.call_sync("Read", GLib.Variant("(ss)", ("org.freedesktop.appearance", "color-scheme")),
                             Gio.DBusCallFlags.NONE, 300, None)
        val = v.unpack()[0]
        while isinstance(val, GLib.Variant):
            val = val.unpack()
        return int(val)
    except Exception:
        return None


def _gnome_scheme():
    global _gsettings
    try:
        src = Gio.SettingsSchemaSource.get_default()
        schema = src.lookup("org.gnome.desktop.interface", True) if src else None
        if schema is None:
            return None
        if _gsettings is None:
            _gsettings = Gio.Settings.new("org.gnome.desktop.interface")
        if schema.has_key("color-scheme"):
            cs = _gsettings.get_string("color-scheme")
            if cs == "prefer-dark":
                return True
            if cs == "prefer-light":
                return False
        theme = _gsettings.get_string("gtk-theme").lower()
        return "dark" in theme if theme else None
    except Exception:
        return None


def system_prefers_dark():
    env = os.environ.get("FOLIO_THEME", "").strip().lower()
    if env in ("dark", "black"):
        return True
    if env in ("light", "colorful", "white"):
        return False
    gt = os.environ.get("GTK_THEME", "").lower()
    if gt:
        return "dark" in gt
    p = _portal_scheme()
    if p in (1, 2):
        return p == 1
    g = _gnome_scheme()
    if g is not None:
        return g
    s = Gtk.Settings.get_default()
    if s is not None:
        name = (s.get_property("gtk-theme-name") or "").lower()
        if "dark" in name:
            return True
    return False


def is_dark():
    global _dark
    if _dark is None:
        _dark = system_prefers_dark()
    return _dark


def set_dark(dark):
    """Switch (used when the desktop changes, and by tests)."""
    global _dark
    dark = bool(dark)
    if dark == _dark:
        return
    _dark = dark
    s = Gtk.Settings.get_default()
    if s is not None:
        s.set_property("gtk-application-prefer-dark-theme", dark)
    for fn in list(_listeners):
        try:
            fn(dark)
        except Exception:
            import traceback
            traceback.print_exc()


def on_change(fn):
    """fn(dark) runs whenever the mode changes."""
    _listeners.append(fn)
    _watch()


def refresh():
    set_dark(system_prefers_dark())


def _watch():
    global _watching
    if _watching:
        return
    _watching = True
    if os.environ.get("FOLIO_THEME"):
        return
    try:
        if _proxy is None:
            _portal_scheme()
        if _proxy is not None:
            def sig(proxy, sender, signal, params):
                if signal == "SettingChanged":
                    ns, key, _v = params.unpack()
                    if ns == "org.freedesktop.appearance" and key == "color-scheme":
                        GLib.idle_add(lambda: (refresh(), False)[1])
            _proxy.connect("g-signal", sig)
    except Exception:
        pass
    try:
        _gnome_scheme()
        if _gsettings is not None:
            _gsettings.connect("changed", lambda *_: GLib.idle_add(lambda: (refresh(), False)[1]))
    except Exception:
        pass
    s = Gtk.Settings.get_default()
    if s is not None:
        s.connect("notify::gtk-theme-name", lambda *_: GLib.idle_add(lambda: (refresh(), False)[1]))


def apply_initial():
    """Set GTK's own widgets (dialogs, entries, menus) to match, before any window is shown."""
    s = Gtk.Settings.get_default()
    if s is not None:
        s.set_property("gtk-application-prefer-dark-theme", is_dark())
