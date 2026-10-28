"""The desktop's Online Accounts (GNOME Online Accounts, which Zorin and Ubuntu have): Google and
Microsoft accounts you sign in to once in Settings. Post asks it for access tokens, as Evolution
does, so there is no client ID or password to type."""
from gi.repository import Gio, GLib

BUS = "org.gnome.OnlineAccounts"
ROOT = "/org/gnome/OnlineAccounts"
ACCOUNT = "org.gnome.OnlineAccounts.Account"
OAUTH2 = "org.gnome.OnlineAccounts.OAuth2Based"
MAIL = "org.gnome.OnlineAccounts.Mail"
PROVIDERS = {"google": "google", "windows_live": "microsoft", "ms_graph": "microsoft"}

# tests replace this with a stand-in
backend = None


def _bus():
    try:
        return Gio.bus_get_sync(Gio.BusType.SESSION, None)
    except Exception:
        return None


def available():
    if backend is not None:
        return backend.available()
    bus = _bus()
    if bus is None:
        return False
    try:
        r = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "ListActivatableNames",
                          None, GLib.VariantType("(as)"), Gio.DBusCallFlags.NONE, 2000, None)
        names = r.unpack()[0]
        r2 = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "ListNames",
                           None, GLib.VariantType("(as)"), Gio.DBusCallFlags.NONE, 2000, None)
        return BUS in names or BUS in r2.unpack()[0]
    except Exception:
        return False


def accounts():
    """[{id, provider ('google' | 'microsoft'), email, mail}] of the desktop's online accounts."""
    if backend is not None:
        return backend.accounts()
    bus = _bus()
    if bus is None:
        return []
    try:
        r = bus.call_sync(BUS, ROOT, "org.freedesktop.DBus.ObjectManager", "GetManagedObjects", None, None,
                          Gio.DBusCallFlags.NONE, 5000, None)
    except Exception:
        return []
    out = []
    for path, ifaces in r.unpack()[0].items():
        a = ifaces.get(ACCOUNT)
        if not a:
            continue
        prov = PROVIDERS.get(a.get("ProviderType", ""))
        if prov is None or OAUTH2 not in ifaces:
            continue
        mail = ifaces.get(MAIL, {})
        email = mail.get("EmailAddress") or a.get("PresentationIdentity") or a.get("Identity", "")
        out.append({"id": a.get("Id", path.rsplit("/", 1)[-1]), "path": path, "provider": prov, "email": email,
                    "mail": bool(mail) and not a.get("MailDisabled", False),
                    "calendar": not a.get("CalendarDisabled", True), "contacts": not a.get("ContactsDisabled", True)})
    return out


def find(email, provider=None):
    for a in accounts():
        if a["email"].lower() == (email or "").lower() and (provider is None or a["provider"] == provider):
            return a
    return None


def token(goa_id):
    """A fresh access token for the online account (Online Accounts refreshes it)."""
    if backend is not None:
        return backend.token(goa_id)
    bus = _bus()
    for a in accounts():
        if a["id"] == goa_id:
            r = bus.call_sync(BUS, a["path"], OAUTH2, "GetAccessToken", None, GLib.VariantType("(si)"),
                              Gio.DBusCallFlags.NONE, 20000, None)
            return r.unpack()[0]
    raise RuntimeError("this account was removed from Online Accounts in Settings")


def open_settings():
    """Settings > Online Accounts, to add one."""
    import shutil
    import subprocess
    for cmd in (["gnome-control-center", "online-accounts"], ["zorin-control-center", "online-accounts"]):
        if shutil.which(cmd[0]):
            subprocess.Popen(cmd)
            return True
    return False
