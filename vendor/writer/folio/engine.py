"""The document engine: a thin wrapper around the embedded document view.

Everything the rest of the app does with a document goes through Engine:
load / new / save, sending commands, reading the live formatting state, and
the lists (fonts, styles) the engine knows about.
"""
import ctypes
import json
import os
import re
import urllib.parse

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, GObject, Gtk  # noqa: E402
try:
    # the old engine (LibreOffice) is optional: Folio's own engine needs none of it
    gi.require_version("LOKDocView", "0.1")
    from gi.repository import LOKDocView  # noqa: E402
except (ValueError, ImportError):
    LOKDocView = None

from . import bridge  # noqa: E402

ENGINE_REAL = "/usr/lib/libreoffice"
_DEBUG_STATE = bool(os.environ.get("FOLIO_DEBUG_STATE"))
ENGINE_DIR = ENGINE_REAL + "/program"


_START_MARK = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"),
                           "folio-writer", "engine-start")


def _mark_start(kind):
    try:
        os.makedirs(os.path.dirname(_START_MARK), exist_ok=True)
        with open(_START_MARK, "w") as f:
            f.write(kind)
    except OSError:
        pass


def engine_started():
    """Called once a document has loaded: the engine setup works."""
    try:
        os.remove(_START_MARK)
    except OSError:
        pass


def _engine_dir():
    """The engine install, seen through a private tree of links in which the
    view's touch-screen selection handles are blank (desktop editing shows
    none). Rebuilt when the engine changes."""
    if os.environ.get("FOLIO_REAL_ENGINE"):
        return ENGINE_DIR
    # if the last start with the link tree never got going, don't use it again
    if os.path.exists(_START_MARK):
        try:
            with open(_START_MARK) as f:
                if f.read().strip() == "linked":
                    return ENGINE_DIR
        except OSError:
            pass
    cache = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"),
                         "folio-writer", "engine")
    try:
        real_prog = os.path.join(ENGINE_REAL, "program")
        st = os.stat(real_prog)
        stamp = "v3 %s %d %d" % (os.path.realpath(ENGINE_REAL), st.st_mtime,
                              len(os.listdir(real_prog)))
        stamp_file = os.path.join(cache, ".stamp")
        try:
            with open(stamp_file) as f:
                if f.read() == stamp:
                    return os.path.join(cache, "program")
        except OSError:
            pass
        import shutil
        if os.path.isdir(cache):
            shutil.rmtree(cache)
        os.makedirs(os.path.join(cache, "program"))
        for name in os.listdir(real_prog):
            src = os.path.join(real_prog, name)
            dst = os.path.join(cache, "program", name)
            if (name.endswith("rc") or name.endswith(".ini")) and os.path.isfile(src):
                # bootstrap files are read relative to where they sit: copy,
                # don't link (newer engines resolve links and look elsewhere)
                shutil.copyfile(src, dst)
            else:
                os.symlink(src, dst)
        for name in os.listdir(ENGINE_REAL):
            if name == "presets":
                # copied into new profiles without following links: real copy
                shutil.copytree(os.path.join(ENGINE_REAL, name), os.path.join(cache, name),
                                symlinks=False)
            elif name not in ("program", "share"):
                os.symlink(os.path.join(ENGINE_REAL, name), os.path.join(cache, name))
        real_share = os.path.join(ENGINE_REAL, "share")
        os.makedirs(os.path.join(cache, "share", "libreofficekit"))
        for name in os.listdir(real_share):
            if name != "libreofficekit":
                os.symlink(os.path.join(real_share, name), os.path.join(cache, "share", name))
        from gi.repository import GdkPixbuf
        pb = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 1, 1)
        pb.fill(0)
        for n in ("handle_image_start.png", "handle_image_middle.png", "handle_image_end.png"):
            pb.savev(os.path.join(cache, "share", "libreofficekit", n), "png", [], [])
        with open(stamp_file, "w") as f:
            f.write(stamp)
        return os.path.join(cache, "program")
    except Exception as e:
        print("engine links:", e)
        return ENGINE_DIR

# Save formats: (file extension, engine filter name)
FORMATS = {
    "docx": ("docx", "MS Word 2007 XML"),
    "dotx": ("dotx", "MS Word 2007 XML Template"),
    "doc": ("doc", "MS Word 97"),
    "rtf": ("rtf", "Rich Text Format"),
    "odt": ("odt", "writer8"),
    "txt": ("txt", "Text"),
    "pdf": ("pdf", "writer_pdf_Export"),
    "html": ("html", "HTML (StarWriter)"),
    "epub": ("epub", "EPUB"),
}


_SAVEAS = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_char_p,
                           ctypes.c_char_p, ctypes.c_char_p)
_GETTEXTSEL = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p,
                               ctypes.POINTER(ctypes.c_char_p))
_PASTE = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_char_p,
                          ctypes.c_char_p, ctypes.c_size_t)
_GETCMDVALUES = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p)
_GETCLIP = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(ctypes.c_char_p),
                            ctypes.POINTER(ctypes.c_size_t),
                            ctypes.POINTER(ctypes.POINTER(ctypes.c_char_p)),
                            ctypes.POINTER(ctypes.POINTER(ctypes.c_size_t)),
                            ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))
_POSTWINDOW = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_uint, ctypes.c_int,
                              ctypes.c_char_p)
_GETPAGERECTS = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p)
_GETSELTYPE = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p)
_PAINTTILE = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                              ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int)
_POSTMOUSE = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                             ctypes.c_int, ctypes.c_int, ctypes.c_int)

_POSTKEY = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int)

# The document's function table, in the order of LibreOfficeKit.h
_SLOTS = {10: ("paintTile", _PAINTTILE), 15: ("postKeyEvent", _POSTKEY), 16: ("postMouseEvent", _POSTMOUSE), 2: ("saveAs", _SAVEAS), 5: ("getPartPageRectangles", _GETPAGERECTS), 19: ("getTextSelection", _GETTEXTSEL),
          20: ("paste", _PASTE), 23: ("getCommandValues", _GETCMDVALUES),
          37: ("postWindow", _POSTWINDOW), 53: ("getClipboard", _GETCLIP),
          55: ("getSelectionType", _GETSELTYPE)}
_fields = [("nSize", ctypes.c_size_t)]
for _i in range(1, 56):
    _name, _typ = _SLOTS.get(_i, ("slot%d" % _i, ctypes.c_void_p))
    _fields.append((_name, _typ))


class _DocClass(ctypes.Structure):
    _fields_ = _fields


class _Doc(ctypes.Structure):
    _fields_ = [("pClass", ctypes.POINTER(_DocClass))]


_libc = ctypes.CDLL(None)
_libc.free.argtypes = [ctypes.c_void_p]

SEL_NONE, SEL_TEXT, SEL_LARGE_TEXT, SEL_COMPLEX = 0, 1, 2, 3


def file_url(path):
    return "file://" + urllib.parse.quote(os.path.abspath(path))


def _arg_type(v):
    if isinstance(v, bool):
        return "boolean", "true" if v else "false"
    if isinstance(v, int):
        return "long", str(v)
    if isinstance(v, float):
        return "float", repr(v)
    return "string", str(v)


def make_args(args):
    """{"Name": value} -> the engine's JSON argument format."""
    if not args:
        return "{}"
    out = {}
    for k, v in args.items():
        if isinstance(v, tuple):          # explicit (type, value)
            out[k] = {"type": v[0], "value": str(v[1])}
            continue
        t, s = _arg_type(v)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and k.endswith("Height"):
            t = "float"
        out[k] = {"type": t, "value": s}
    return json.dumps(out)


# ------------------------------------------------------------ office hook
# The view widget asserts (and aborts the app) on engine messages it doesn't
# know, such as the dialog descriptions newer engines send. The app takes
# over the engine-wide message channel: passwords are asked by the app,
# progress is ignored, and any dialog the engine opens is closed at once
# (and the app shows its own instead).
_OFFICE_CB = ctypes.CFUNCTYPE(None, ctypes.c_int, ctypes.c_char_p, ctypes.c_void_p)
_REGCB = ctypes.CFUNCTYPE(None, ctypes.c_void_p, _OFFICE_CB, ctypes.c_void_p)
_SETPW = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p)
_DLGEVT = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_ulonglong, ctypes.c_char_p)


class _OfficeHook:
    def __init__(self):
        self.office = None
        self.engines = []
        self.closed = set()
        self._cb = _OFFICE_CB(self._callback)

    def install(self, office_ptr):
        """(Re)take the channel: the view claims it again on every load."""
        if not office_ptr:
            return
        self.office = int(office_ptr)
        slots = self._slots()
        _REGCB(slots[6])(self.office, self._cb, None)

    def _slots(self):
        pclass = ctypes.cast(ctypes.c_void_p(self.office), ctypes.POINTER(ctypes.c_void_p))[0]
        return ctypes.cast(ctypes.c_void_p(pclass), ctypes.POINTER(ctypes.c_void_p))

    def _callback(self, kind, payload, data):
        # engine thread: hand over to the UI thread and return at once
        text = payload.decode("utf-8", "replace") if payload else ""
        if kind in (20, 21, 46, 22):
            GLib.idle_add(self._handle, kind, text)

    def _handle(self, kind, text):
        if kind in (20, 21):
            eng = self.engines[-1] if self.engines else None
            pw = None
            if eng is not None:
                try:
                    eng.view.emit("password-required", text, kind == 21)
                    return False
                except TypeError:
                    pass
            self.set_password(text, pw)
        elif kind == 46:
            self._dialog(text)
        return False

    def set_password(self, url, pw):
        _SETPW(self._slots()[9])(self.office, url.encode(), pw.encode() if pw else None)

    def _dialog(self, text):
        try:
            data = json.loads(text)
        except ValueError:
            return
        wid = data.get("id")
        if not isinstance(wid, int) or wid in self.closed:
            return
        title = data.get("text") or data.get("title") or ""
        self.closed.add(wid)
        for args in ('{"id":"__DIALOG__","cmd":"response","data":"0"}',
                     '{"id":"__DIALOG__","cmd":"close","data":""}'):
            try:
                _DLGEVT(self._slots()[14])(self.office, wid, args.encode())
            except Exception:
                pass
        target = None
        for eng in self.engines:
            top = eng.view.get_toplevel()
            if top is not None and top.is_active():
                target = eng
        target = target or (self.engines[-1] if self.engines else None)
        if target is not None:
            target.emit("engine-dialog", title)


OFFICE_HOOK = _OfficeHook()


_FONT_JUNK = re.compile(
    r"Emoji|Unifont|\bMath\b|Fallback|CJK|WenQuanYi|^IPA|^Droid Sans (?!Mono$)|"
    r"^Noto (?!(Sans|Serif)( Mono| Display)?$)|^Latin Modern (Roman|Sans|Mono) .|^LM (?!(Roman|Sans|Mono) 10$)|^Noto Sans (Mono|Display) \w|^OpenSymbol$|"
    r"^(Lohit|Kacst|Samyak|Sawasdee|Tlwg|Garuda|Kinnari|Laksaman|Loma|Norasi|Purisa|"
    r"Umpush|Waree|Khmer OS|Padauk|Phetsarath|Mukti|Pothana|Vemana|Rachana|Meera|"
    r"Gargi|Nakula|Sahadeva|Kalimati|Jamrul|Likhan|Saab|Suruma|Chandas|Abyssinica)")

_SCRIPT_LANGS = {"ja", "ko", "zh-cn", "zh-tw"}
_LATIN_FONTS = []


def latin_font_families():
    """Family names (all aliases) of fonts covering English that aren't
    built for another script. None when fontconfig can't be asked."""
    if _LATIN_FONTS:
        return _LATIN_FONTS[0]
    import subprocess
    try:
        out = subprocess.run(["fc-list", ":lang=en", "family", "lang"], capture_output=True,
                             text=True, timeout=10).stdout
    except Exception:
        return None
    ok, bad = set(), set()
    for line in out.splitlines():
        fam, _, langs = line.partition(":lang=")
        names = [f.replace("\\", "").strip() for f in fam.split(",") if f.strip()]
        langset = set(langs.split("|"))
        target = bad if langset & _SCRIPT_LANGS and not any(
            n.startswith(("DejaVu", "Free", "Noto Sans", "Noto Serif")) for n in names) else ok
        target.update(names)
    _LATIN_FONTS.append(ok - bad if ok else None)
    return _LATIN_FONTS[0]


class Engine(GObject.GObject):
    """One document view. Signals:
    state-changed(command, value)   live formatting/document state
    loaded(ok)                      a document finished loading
    """
    __gsignals__ = {
        "state-changed": (GObject.SignalFlags.RUN_LAST, None, (str, str)),
        "loaded": (GObject.SignalFlags.RUN_LAST, None, (bool,)),
        "zoom-changed": (GObject.SignalFlags.RUN_LAST, None, (float,)),
        "model-ready": (GObject.SignalFlags.RUN_LAST, None, ()),
        # the engine tried to show one of its own dialogs (closed at once)
        "engine-dialog": (GObject.SignalFlags.RUN_LAST, None, (str,)),
    }

    def __init__(self, profile_dir, author=""):
        super().__init__()
        self.author = author
        self._font_cache = None
        self.profile_url = file_url(profile_dir)
        bridge.prepare_path()
        bridge.install(profile_dir)
        # one engine instance per process; each window gets its own document
        edir = _engine_dir()
        _mark_start("linked" if edir != ENGINE_DIR else "real")
        self.view = LOKDocView.View.new_from_user_profile(edir, self.profile_url, None)
        try:
            OFFICE_HOOK.install(self.view.get_property("lopointer"))
            OFFICE_HOOK.engines.append(self)
        except Exception as e:
            print("engine hook:", e)
        # comments are drawn by the app (in the margin), not painted into the page
        if not os.environ.get("FOLIO_TILED_COMMENTS"):
            self.view.set_property("tiled-annotations", False)
        self.model = None
        self.view.set_can_focus(True)
        self.state = {}
        self.path = None           # file on disk (None for a new document)
        self.format = "docx"
        self.is_new = True
        self.view.connect("command-changed", self._on_state)
        self.view.connect("command-result", self._on_result)
        self._closed_windows = set()
        try:
            self.view.connect("window", self._on_window)
        except TypeError:
            pass
        self._sync_waiting = []
        self.view.connect("notify::zoom-level",
                          lambda *a: self.emit("zoom-changed", self.view.get_zoom()))

    # ---------------------------------------------------------------- state
    def _on_state(self, view, payload):
        if _DEBUG_STATE:
            print("STATE", payload[:160], flush=True)
        if payload.startswith("{"):
            try:
                data = json.loads(payload)
                cmd = data.get("commandName")
                if cmd:
                    val = data.get("state", "")
                    if not isinstance(val, str):
                        val = json.dumps(val)
                    self.state[cmd] = val
                    self.emit("state-changed", cmd, val)
            except ValueError:
                pass
            return
        if "=" in payload:
            cmd, val = payload.split("=", 1)
        else:
            cmd, val = payload, ""
        self.state[cmd] = val
        self.emit("state-changed", cmd, val)

    def _on_window(self, view, payload):
        """The engine never gets to show its own windows: any dialog it opens
        is closed straight away (the app shows its own instead)."""
        try:
            data = json.loads(payload)
        except ValueError:
            return
        wid = data.get("id")
        action = data.get("action")
        if wid is None or wid in self._closed_windows:
            return
        if action in ("created", "title_changed") and data.get("type") not in ("tooltip",
                                                                               "deck"):
            self._closed_windows.add(wid)
            title = data.get("title", "")

            def close():
                doc = self._doc_ptr()
                if doc is not None:
                    doc.contents.pClass.contents.postWindow(doc, int(wid), 0, None)
                self.emit("engine-dialog", title)
                return False
            GLib.idle_add(close)

    def _on_result(self, view, payload):
        if self._sync_waiting and '".uno:InsertText"' in payload and '"success": false' in payload:
            fn = self._sync_waiting.pop(0)
            fn()

    def sync(self, fn):
        """Run fn once everything already sent to the engine (keys, commands)
        has been processed."""
        if self.model is None:
            fn()
            return
        self._sync_waiting.append(fn)
        self.view.post_command(".uno:InsertText", make_args({"Text": ""}), True)

    def get(self, cmd, default=""):
        return self.state.get(cmd, default)

    def is_on(self, cmd):
        return self.state.get(cmd) == "true"

    # -------------------------------------------------------------- loading
    def open(self, path, on_done=None):
        self.opened_path = os.path.abspath(path)
        self.path = os.path.abspath(path) if path else None
        ext = os.path.splitext(path)[1].lower().lstrip(".")
        self.format = ext if ext in FORMATS and ext not in ("pdf", "epub") else "docx"
        self.is_new = False

        def done(src, res, data=None):
            ok = False
            try:
                ok = self.view.open_document_finish(res)
            except GLib.Error:
                ok = False
            if ok:
                engine_started()
                try:
                    OFFICE_HOOK.install(self.view.get_property("lopointer"))
                except Exception as e:
                    print("engine hook:", e)
                self.view.set_edit(True)
                self.model = None
                if not os.environ.get("FOLIO_NO_BRIDGE"):
                    bridge.request(self)
            self.emit("loaded", ok)
            if on_done:
                on_done(ok)
        args = {".uno:Author": {"type": "string", "value": self.author}} if self.author else {}
        self.view.open_document(path, json.dumps(args), None, done, None)

    def new(self, template, on_done=None):
        """A new document based on a template file. The template is copied
        to a private scratch file first so the new document is editable even
        when the template itself is read-only."""
        import shutil
        import tempfile
        scratch = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"),
                               "folio-writer", "new")
        os.makedirs(scratch, exist_ok=True)
        fd, tmp = tempfile.mkstemp(suffix=os.path.splitext(template)[1] or ".ott", dir=scratch)
        os.close(fd)
        shutil.copyfile(template, tmp)
        self._scratch = tmp

        def done(ok):
            self.path = None
            self.is_new = True
            self.format = "docx"
            try:
                os.remove(tmp)
            except OSError:
                pass
            if on_done:
                on_done(ok)
        self.open(tmp, done)

    def _set_model(self, model):
        self.model = model
        GLib.idle_add(lambda: (self.emit("model-ready"), False)[1])

    # --------------------------------------------------------------- saving
    def _doc_ptr(self):
        ptr = self.view.get_property("docpointer")
        if not ptr:
            return None
        return ctypes.cast(ctypes.c_void_p(int(ptr)), ctypes.POINTER(_Doc))

    save_hooks = ()
    written_hooks = ()        # fix(path, fmt) run on the file just written

    def save_as(self, path, fmt=None, options=None, keep=True, filter_data=None):
        """Write the document. keep=True makes `path` the document's file
        (like Save As); keep=False writes a copy (Export / PDF).
        filter_data: {name: value} export settings (PDF page range...).
        save_hooks: (before, after) pairs run around the write, e.g. to open
        collapsed headings so they are not saved hidden."""
        hooks = list(self.save_hooks)
        for before, _after in hooks:
            try:
                before()
            except Exception as e:
                print("save hook:", e)
        try:
            return self._save_as(path, fmt, options, keep, filter_data)
        finally:
            for _before, after in reversed(hooks):
                try:
                    after()
                except Exception as e:
                    print("save hook:", e)

    def _save_as(self, path, fmt=None, options=None, keep=True, filter_data=None):
        fmt = fmt or os.path.splitext(path)[1].lower().lstrip(".") or "docx"
        ext, _ = FORMATS.get(fmt, FORMATS["docx"])
        doc = self._doc_ptr()
        if doc is None:
            return False
        if fmt in ("pdf", "epub", "html", "txt"):
            keep = False
        opts = [o for o in (options or "").split(",") if o]
        if keep:
            opts.append("TakeOwnership")
        opt_str = ",".join(opts).encode() if opts else None
        if filter_data:
            import json

            def typed(v):
                if isinstance(v, bool):
                    return {"type": "boolean", "value": "true" if v else "false"}
                if isinstance(v, int):
                    return {"type": "long", "value": str(v)}
                return {"type": "string", "value": str(v)}
            opt_str = json.dumps({k: typed(v) for k, v in filter_data.items()}).encode()
        ok = doc.contents.pClass.contents.saveAs(
            doc, file_url(path).encode(), ext.encode(), opt_str)
        if not ok or not os.path.exists(path):
            return False
        for fix in self.written_hooks:
            try:
                fix(path, fmt)
            except Exception as e:
                print("save fix:", e)
        if keep:
            self.path = os.path.abspath(path)
            self.format = fmt
            self.is_new = False
        return True

    def save(self):
        if self.path is None:
            return False
        return self.save_as(self.path, self.format)

    # ------------------------------------------------- direct document calls
    def paste_data(self, mime, data):
        """Insert clipboard-style data (any format, binary safe)."""
        doc = self._doc_ptr()
        if doc is None:
            return False
        if isinstance(data, str):
            data = data.encode("utf-8")
        return bool(doc.contents.pClass.contents.paste(doc, mime.encode(), data, len(data)))

    def selection(self, mime="text/plain;charset=utf-8"):
        doc = self._doc_ptr()
        if doc is None:
            return ""
        used = ctypes.c_char_p()
        ptr = doc.contents.pClass.contents.getTextSelection(doc, mime.encode(), ctypes.byref(used))
        if not ptr:
            return ""
        try:
            return ctypes.string_at(ptr).decode("utf-8", "replace")
        finally:
            _libc.free(ptr)

    def selection_bytes(self, mime):
        """The selection in one format, binary safe (b"" if unavailable)."""
        doc = self._doc_ptr()
        if doc is None:
            return b""
        req = (ctypes.c_char_p * 2)(mime.encode(), None)
        count = ctypes.c_size_t()
        mimes = ctypes.POINTER(ctypes.c_char_p)()
        sizes = ctypes.POINTER(ctypes.c_size_t)()
        streams = ctypes.POINTER(ctypes.c_void_p)()
        ok = doc.contents.pClass.contents.getClipboard(
            doc, req, ctypes.byref(count), ctypes.byref(mimes), ctypes.byref(sizes),
            ctypes.byref(streams))
        data = b""
        if ok:
            mptrs = ctypes.cast(mimes, ctypes.POINTER(ctypes.c_void_p))
            for i in range(count.value):
                if streams[i] and not data:
                    data = ctypes.string_at(streams[i], sizes[i])
                _libc.free(mptrs[i])
                if streams[i]:
                    _libc.free(streams[i])
            _libc.free(ctypes.cast(mimes, ctypes.c_void_p))
            _libc.free(ctypes.cast(sizes, ctypes.c_void_p))
            _libc.free(ctypes.cast(streams, ctypes.c_void_p))
        return data

    EMBED_MIME = ('application/x-openoffice-embed-source-xml;'
                  'windows_formatname="Star Embed Source (XML)"')

    def selected_formula(self):
        """Formula markup of the selected equation object, or None.
        Uses the engine's private clipboard (the desktop one is untouched)."""
        if self.selection_type() != SEL_COMPLEX:
            return None
        self.command(".uno:Copy")
        data = self.selection_bytes(self.EMBED_MIME)
        if not data.startswith(b"PK"):
            return None
        import io
        import re
        import zipfile
        try:
            z = zipfile.ZipFile(io.BytesIO(data))
            for n in z.namelist():
                if n.endswith("/content.xml"):
                    xml = z.read(n).decode("utf-8", "replace")
                    m = re.search(r'<annotation[^>]*encoding="StarMath[^"]*"[^>]*>(.*?)'
                                  r'</annotation>', xml, re.S)
                    if m:
                        import html
                        return html.unescape(m.group(1))
                    if "<math" in xml:
                        return ""
        except (zipfile.BadZipFile, KeyError):
            pass
        return None

    def page_rects(self):
        """[(x, y, w, h)] of every page, in twips (document coordinates)."""
        doc = self._doc_ptr()
        if doc is None:
            return []
        ptr = doc.contents.pClass.contents.getPartPageRectangles(doc)
        if not ptr:
            return []
        try:
            raw = ctypes.string_at(ptr).decode()
        finally:
            _libc.free(ptr)
        out = []
        for part in raw.split(";"):
            nums = [int(v) for v in part.replace(" ", "").split(",") if v.strip("-").isdigit()]
            if len(nums) == 4:
                out.append(tuple(nums))
        return out

    def px_to_twips(self, x, y):
        z = self.view.get_zoom() or 1.0
        return int(x * 15 / z), int(y * 15 / z)

    def twips_to_px(self, x, y):
        z = self.view.get_zoom() or 1.0
        return x * z / 15.0, y * z / 15.0

    def render(self, x, y, w, h, width_px):
        """Render a document area (twips) to a cairo surface width_px wide."""
        import cairo
        doc = self._doc_ptr()
        if doc is None:
            return None
        width_px = max(1, int(width_px))
        height_px = max(1, int(round(h * width_px / float(w))))
        stride = cairo.ImageSurface.format_stride_for_width(cairo.FORMAT_ARGB32, width_px)
        if stride != width_px * 4:
            width_px = stride // 4
        buf = bytearray(width_px * height_px * 4)
        cbuf = (ctypes.c_ubyte * len(buf)).from_buffer(buf)
        doc.contents.pClass.contents.paintTile(doc, ctypes.addressof(cbuf), width_px,
                                               height_px, int(x), int(y), int(w), int(h))
        return cairo.ImageSurface.create_for_data(buf, cairo.FORMAT_ARGB32, width_px,
                                                  height_px, width_px * 4)

    def click_at(self, x_twips, y_twips):
        """Put the cursor at a document position (as a click there would)."""
        doc = self._doc_ptr()
        if doc is None:
            return
        fn = doc.contents.pClass.contents.postMouseEvent
        fn(doc, 0, int(x_twips), int(y_twips), 1, 1, 0)     # button down
        fn(doc, 1, int(x_twips), int(y_twips), 1, 1, 0)     # button up

    def post_key(self, key_code, char_code=0):
        """Send a key press+release straight to the engine (awt key code)."""
        doc = self._doc_ptr()
        if doc is None:
            return
        fn = doc.contents.pClass.contents.postKeyEvent
        fn(doc, 0, char_code, key_code)
        fn(doc, 1, char_code, key_code)

    def selection_type(self):
        doc = self._doc_ptr()
        if doc is None:
            return SEL_NONE
        return doc.contents.pClass.contents.getSelectionType(doc)

    @property
    def modified(self):
        return self.state.get(".uno:ModifiedStatus") == "true"

    def mark_saved(self):
        self.state[".uno:ModifiedStatus"] = "false"
        self.emit("state-changed", ".uno:ModifiedStatus", "false")

    # ------------------------------------------------------------- commands
    def command(self, cmd, args=None, notify=False):
        self.view.post_command(cmd, make_args(args), notify)

    def values(self, cmd):
        raw = self.view.get_command_values(cmd)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            return None

    def fonts(self, all_fonts=False):
        """Font families for the font lists. Unless all_fonts, only fonts made
        for Latin-script text: no CJK/Indic/Thai/... script fonts, emoji,
        math or fallback fonts."""
        if all_fonts or self._font_cache is None:
            data = self.values(".uno:CharFontName") or {}
            names = sorted((data.get("commandValues") or {}).keys(), key=str.lower)
            if all_fonts:
                return names
            if not names:
                return []
            ok = latin_font_families()
            self._font_cache = [n for n in names if (ok is None or n in ok)
                                and not _FONT_JUNK.search(n)] or names
        return list(self._font_cache)

    def paragraph_styles(self):
        data = self.values(".uno:StyleApply") or {}
        return (data.get("commandValues") or {}).get("ParagraphStyles", [])

    def zoom(self, factor):
        self.view.set_zoom(max(0.1, min(5.0, factor)))
