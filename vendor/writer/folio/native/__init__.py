"""Folio's own document engine (folio_core, written in Rust): the .docx is
the document model, laid out with the original's rules and drawn here."""
import importlib.machinery
import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_CANDIDATES = [
    os.environ.get("FOLIO_CORE_LIB", ""),
    # next to the code (installed), else a development checkout
    os.path.join(_HERE, "..", "..", "folio_core.so"),
    os.path.normpath(os.path.join(_HERE, "..", "..", "..", "core", "target", "release",
                                  "libfolio_core.so")),
    "/usr/lib/folio-writer/folio_core.so",
]

_core = None


def core():
    """The folio_core module, or None if it isn't installed."""
    global _core
    if _core is not None:
        return _core
    if "folio_core" in sys.modules:
        _core = sys.modules["folio_core"]
        return _core
    for path in _CANDIDATES:
        if path and os.path.exists(path):
            loader = importlib.machinery.ExtensionFileLoader("folio_core", path)
            spec = importlib.util.spec_from_file_location("folio_core", path, loader=loader)
            mod = importlib.util.module_from_spec(spec)
            try:
                loader.exec_module(mod)
            except ImportError as e:
                print("folio_core:", e)
                continue
            sys.modules["folio_core"] = mod
            _core = mod
            return mod
    return None


def available():
    return core() is not None


_classic = None


def classic_available():
    """Is the old engine (LibreOffice's, an optional extra) installed?"""
    global _classic
    if _classic is None:
        try:
            import gi
            gi.require_version("LOKDocView", "0.1")
            from gi.repository import LOKDocView  # noqa: F401
            import uno  # noqa: F401
            _classic = True
        except Exception:
            _classic = False
    return _classic


def wanted(settings):
    """Does the user want the new engine (Options > Advanced, or
    FOLIO_ENGINE=native)? Without the old engine installed, always."""
    env = os.environ.get("FOLIO_ENGINE")
    if env == "native" or (available() and not classic_available()):
        return True
    if env:
        return env == "native"
    # Folio's own engine is the default; "classic" keeps the old one
    return settings.get("engine", "native") != "classic"


def normal_docx(app):
    """(the Normal template to start from, where the user's own copy goes)."""
    from ..app import CONFIG, SHARE
    tpl = os.path.basename(app.user_template_path())
    name = os.path.splitext(tpl)[0] + ".docx"
    user = os.path.join(CONFIG, "templates", name)
    if os.path.exists(user):
        return user, user
    for base in (os.path.join(SHARE, "templates"),
                 os.path.join(_HERE, "..", "..", "..", "share", "templates")):
        p = os.path.join(base, name)
        if os.path.exists(p):
            return os.path.abspath(p), user
    raise FileNotFoundError(name)


def edit_normal_template(app, fn):
    """Let fn(editor) change the Normal template; it's stored as the user's own."""
    src, dst = normal_docx(app)
    ed = core().Editor.open(src)
    fn(ed)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    ed.save(dst)
    return True
