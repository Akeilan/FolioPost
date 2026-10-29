"""The message editor from Folio Writer (M-04).

Mail is written in Writer's own document engine and view (folio_core and its page view, vendored
from Folio Writer by tools/sync_writer.sh), laid out as Web Layout: the same typing, selection,
fonts, styles, lists, tables, pictures, links and spelling marks as in Writer, the way Outlook
writes mail with Word. The message goes out as the HTML (and plain text) Writer makes of it.

WriterEditor has the interface compose.py uses of richedit.RichEditor, which stays as the
fallback when the engine can't be loaded (FOLIO_POST_EDITOR=simple also asks for it).
"""
import base64
import os
import re
import sys
import tempfile

from gi.repository import Gdk, GLib, Gtk

_HERE = os.path.dirname(os.path.abspath(__file__))
VENDOR_DIRS = [os.environ.get("FOLIO_POST_WRITER", ""),
               os.path.normpath(os.path.join(_HERE, "..", "..", "vendor", "writer")),   # source tree
               os.path.normpath(os.path.join(_HERE, "..", "writer")),                   # /usr/lib/folio-post/writer
               "/usr/lib/folio-post/writer"]

_mods = None


def _vendor():
    for d in VENDOR_DIRS:
        if d and os.path.isdir(os.path.join(d, "folio", "native")):
            return d
    return None


def load():
    """Writer's engine modules, or None when they can't be loaded here."""
    global _mods
    if _mods is not None:
        return _mods or None
    _mods = False
    if os.environ.get("FOLIO_POST_EDITOR") == "simple":
        return None
    d = _vendor()
    if d is None:
        return None
    lib = os.path.join(d, "folio_core.so")
    if os.path.exists(lib) and not os.environ.get("FOLIO_CORE_LIB"):
        os.environ["FOLIO_CORE_LIB"] = lib
    if d not in sys.path:
        sys.path.insert(0, d)
    try:
        from folio import native
        if native.core() is None:
            return None
        from folio.native import engine as wengine, htmlexport, htmlpaste, spell
    except Exception as e:  # an old or broken copy: the simple editor still works
        print("Folio Post: Folio Page's editor isn't available:", e)
        return None
    _mods = {"native": native, "engine": wengine, "htmlexport": htmlexport, "htmlpaste": htmlpaste, "spell": spell,
             "templates": os.path.join(d, "templates")}
    return _mods


def available():
    return load() is not None


def writer_version():
    d = _vendor()
    try:
        with open(os.path.join(d, "WRITER_VERSION")) as f:
            return f.read().strip()
    except (OSError, TypeError):
        return ""


# Word's highlight names and the colours Post's ribbon offers
HIGHLIGHTS = {"FFFF00": "yellow", "00FF00": "green", "00FFFF": "cyan", "FF00FF": "magenta", "0000FF": "blue",
              "FF0000": "red", "000080": "darkBlue", "008080": "darkCyan", "008000": "darkGreen",
              "800080": "darkMagenta", "800000": "darkRed", "808000": "darkYellow", "808080": "darkGray",
              "C0C0C0": "lightGray", "000000": "black"}
HL_RGB = {v: k for k, v in HIGHLIGHTS.items()}
ALIGN_IN = {"left": "left", "center": "center", "right": "right", "justify": "both"}
ALIGN_OUT = {"left": "left", "start": "left", "center": "center", "right": "right", "end": "right",
             "both": "justify", "distribute": "justify"}
WORD = re.compile(r"[A-Za-zÀ-ɏ]+(?:'[A-Za-z]+)?")


_LIST_P = re.compile(r'<p class="ListParagraph"([^>]*)><span class="label">([^<]*)</span>(?:&#9;|\t)?(.*?)</p>', re.S)


def _lists_to_html(body):
    """Writer's list paragraphs (a label, a tab, the text) as HTML lists, which every mail program shows
    as lists (and screen readers read as lists)."""
    out = []
    pos = 0
    cur = None
    for m in _LIST_P.finditer(body):
        between = body[pos:m.start()]
        label = m.group(2).strip()
        kind = "ol" if re.match(r"^[\w]{1,4}[.)]$", label) else "ul"
        if cur and between.strip():
            out.append("</%s>" % cur)
            cur = None
        out.append(between if not cur else between.strip())
        if cur != kind:
            if cur:
                out.append("</%s>" % cur)
            out.append("<%s>" % kind)
            cur = kind
        attrs = m.group(1)
        out.append("<li%s>%s</li>" % (attrs, m.group(3)))
        pos = m.end()
    if cur:
        out.append("</%s>" % cur)
    out.append(body[pos:])
    return "".join(out)


class _Win:
    """What Writer's engine and speller ask of their window."""

    def __init__(self, editor):
        self.editor = editor
        self.app = self
        self.settings = {"auto_spell": True, "ignore_upper": True}
        self.ignored_words = set()

    @property
    def engine(self):
        return self.editor.engine

    def clipboard(self):
        return None


def _hex(c):
    """A colour from the ribbon ("#rrggbb", (r, g, b) in 0..1 or 0..255) as RRGGBB."""
    if c is None:
        return None
    if isinstance(c, str):
        c = c.strip().lstrip("#")
        return c.upper() if re.fullmatch(r"[0-9a-fA-F]{6}", c) else None
    try:
        vals = list(c)[:3]
        if all(isinstance(v, float) and v <= 1.0 for v in vals):
            vals = [int(round(v * 255)) for v in vals]
        return "%02X%02X%02X" % tuple(int(v) for v in vals)
    except (TypeError, ValueError):
        return None


class WriterEditor(Gtk.EventBox):
    """Writer's document view in Web Layout, with the editing interface of RichEditor."""

    def __init__(self):
        super().__init__()
        m = load()
        if m is None:
            raise RuntimeError("Folio Page's editor isn't available")
        self.m = m
        self.win = _Win(self)
        self.engine = m["engine"].NativeEngine(author=GLib.get_real_name() or "")
        self.engine.win = self.win
        self.view = self.engine.view
        self.view.continuous = True
        self.add(self.view)
        self.get_style_context().add_class("folio-editor")
        self.get_style_context().add_class("folio-writer-editor")
        self.view.set_can_focus(True)
        self.speller = None
        self.on_state = None
        self.on_ignore = None
        self.ignored = set()
        self.default_font = "Calibri"
        self.default_size = 11
        self._changed = []
        self._state_id = 0
        self.view.connect("changed", self._on_changed)
        self.view.connect("selection-changed", lambda *_: self._notify())
        self.view.connect("size-allocate", self._sized)
        self.view.connect("button-press-event", self._press)
        # mouse-up callbacks (the Format Painter) run after the view's own handling
        self._mouse_up = {}
        self._mouse_id = 0
        try:
            self.view.disconnect_by_func(self.view._release)
        except TypeError:
            pass

        def released(w, ev):
            r = self.view._release(w, ev)
            for cb in list(self._mouse_up.values()):
                cb()
            return r
        self.view.connect("button-release-event", released)
        self._width = 0
        self.new()

    # ------------------------------------------------------------ the document
    def _template(self):
        t = self.m["templates"]
        for name in ("Normal-Letter.docx", "Normal-A4.docx"):
            p = os.path.join(t, name)
            if os.path.exists(p):
                return p
        return None

    def _set_ed(self, ed):
        self.engine.ed = ed
        try:
            ed.set_author(self.engine.author or "")
        except Exception:
            pass
        self.view.set_editor(ed)
        self._web_layout()
        self._notify()

    def new(self, data=None):
        """An empty message (or one from .docx bytes)."""
        core = self.m["native"].core()
        if data is None:
            with open(self._template(), "rb") as f:
                data = f.read()
        self._set_ed(core.Editor.from_bytes(data))

    @property
    def ed(self):
        return self.engine.ed

    def _web_layout(self):
        v = self.view
        alloc = v.get_allocated_width()
        sw = v.get_parent()
        while sw is not None and not isinstance(sw, Gtk.ScrolledWindow):
            sw = sw.get_parent()
        if sw is not None:
            alloc = sw.get_allocated_width() or alloc
        width = max(144.0, (alloc - 24) / v.ppp) if alloc > 50 else 468.0
        self._width = alloc
        try:
            self.ed.set_view_mode(2, width)
        except Exception:
            return
        v.document_changed()

    def _sized(self, *_):
        sw = self.get_parent()
        while sw is not None and not isinstance(sw, Gtk.ScrolledWindow):
            sw = sw.get_parent()
        w = sw.get_allocated_width() if sw is not None else self.view.get_allocated_width()
        if abs(w - self._width) > 8:
            GLib.idle_add(lambda: (self._web_layout(), False)[1])

    def _on_changed(self, *_):
        if self.speller is not None:
            try:
                self.view.speller.invalidate()
            except Exception:
                pass
        for cb in list(self._changed):
            cb()
        self._notify()

    def connect_changed(self, cb):
        self._changed.append(cb)

    def _notify(self):
        if self.on_state and not self._state_id:
            def go():
                self._state_id = 0
                if self.on_state:
                    self.on_state(self.state())
                return False
            self._state_id = GLib.idle_add(go)

    def grab_focus(self):
        self.view.grab_focus()

    def on_mouse_up(self, cb):
        self._mouse_id += 1
        self._mouse_up[self._mouse_id] = lambda: cb()
        return self._mouse_id

    def off_mouse_up(self, hid):
        self._mouse_up.pop(hid, None)

    def has_focus_in(self, w):
        return w is self or w is self.view

    def _edit(self, fn, *a):
        r = fn(*a)
        self.view.after_edit()
        return r

    # ------------------------------------------------------------ state
    def state(self):
        if self.ed is None:
            return {}
        s = self.ed.state()
        col = s.get("color")
        hl = s.get("highlight")
        return {"bold": bool(s.get("bold")), "italic": bool(s.get("italic")),
                "underline": s.get("underline", "none") != "none", "strike": bool(s.get("strike")),
                "font": s.get("font") or self.default_font, "size": s.get("size") or self.default_size,
                "color": None if col in (None, "auto") else "#" + col.lower(),
                "highlight": None if hl in (None, "none") else "#" + HL_RGB.get(hl, "FFFF00").lower(),
                "align": ALIGN_OUT.get(s.get("align"), "left"), "list": s.get("list") or None,
                "indent": int(round((s.get("ind_left") or 0) / 720.0)) if not s.get("list") else 0,
                "link": self.ed.link_at_caret() or None, "style": s.get("style"),
                "can_undo": s.get("can_undo"), "can_redo": s.get("can_redo")}

    # ------------------------------------------------------------ formatting
    def set_char(self, kind, value):
        ed = self.ed
        st = self.state()
        if kind in ("bold", "italic", "strike"):
            if bool(value) != st[kind]:
                self._edit(ed.toggle, {"bold": "w:b", "italic": "w:i", "strike": "w:strike"}[kind])
        elif kind == "underline":
            self._edit(ed.set_underline, "single" if value else "none")
        elif kind == "font":
            self._edit(ed.set_font, value or self.default_font)
        elif kind == "size":
            self._edit(ed.set_size, float(value or self.default_size))
        elif kind == "color":
            self._edit(ed.set_color, _hex(value) or "auto")
        elif kind == "highlight":
            h = _hex(value)
            name = HIGHLIGHTS.get(h) if h else None
            if h and name is None:
                # the nearest of Word's highlight colours
                r, g, b = int(h[:2], 16), int(h[2:4], 16), int(h[4:], 16)
                name = min(HIGHLIGHTS.items(), key=lambda kv: (int(kv[0][:2], 16) - r) ** 2 + (int(kv[0][2:4], 16) - g) ** 2
                           + (int(kv[0][4:], 16) - b) ** 2)[1]
            self._edit(ed.set_highlight, name or "none")
        elif kind == "link":
            if value:
                self.insert_link(value)
            else:
                self._edit(ed.remove_link)

    def toggle(self, kind):
        self.set_char(kind, not self.state().get(kind))

    def clear_formatting(self):
        self._edit(self.ed.clear_formatting)

    def set_align(self, value):
        self._edit(self.ed.set_align, ALIGN_IN.get(value, "left"))

    def indent(self, step):
        st = self.ed.state()
        if st.get("list"):
            self._edit(self.ed.change_list_level, 1 if step > 0 else -1)
            return
        left = max(0, int(st.get("ind_left") or 0) + 720 * step)
        self._edit(self.ed.set_indent, left, None, None)

    def set_list(self, kind):
        self._edit(self.ed.toggle_list, kind)

    def insert_link(self, url, text=None):
        if not url:
            self._edit(self.ed.remove_link)
            return
        self._edit(self.ed.insert_hyperlink, url, text if text else (None if self.ed.has_selection() else url))

    def insert_picture(self, data, ctype="image/png", width=None):
        ext = {"image/jpeg": ".jpg", "image/gif": ".gif", "image/bmp": ".bmp", "image/webp": ".webp"}.get(ctype, ".png")
        fd, path = tempfile.mkstemp(suffix=ext, prefix="folio-post-pic-")
        try:
            os.write(fd, data)
            os.close(fd)
            return self._edit(self.ed.insert_picture, path)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def insert_table(self, rows, cols, cells=None):
        self._edit(self.ed.insert_table, rows, cols)
        for r, row in enumerate(cells or ()):
            for c, txt in enumerate(row):
                if txt:
                    self.ed.type_text(str(txt))
                if c < cols - 1:
                    self.ed.cell_step(False)
            if r < rows - 1:
                self.ed.cell_step(False)
        self.view.after_edit()
        return True

    def insert_text(self, text):
        self._edit(self.ed.type_text, text)

    # ------------------------------------------------------------ undo
    def do_undo(self):
        if self.ed.can_undo():
            self._edit(self.ed.undo)

    def do_redo(self):
        if self.ed.can_redo():
            self._edit(self.ed.redo)

    @property
    def undo(self):
        return ["step"] if self.ed is not None and self.ed.can_undo() else []

    @undo.setter
    def undo(self, v):
        """undo = [] after loading: the loaded text is where undo starts."""
        if v or self.ed is None or not self.ed.can_undo():
            return
        data = self._docx_bytes()
        # the caret by paragraph number: node ids differ in the reloaded document
        caret = self.ed.selection_range()
        nodes = self._nodes()
        idx = nodes.index(caret[0]) if caret[0] in nodes else 0
        self._set_ed(self.m["native"].core().Editor.from_bytes(data))
        nodes = self._nodes()
        if nodes:
            p = nodes[min(idx, len(nodes) - 1)]
            off = min(caret[1], len(self.ed.para_text_of(p)))
            self.ed.select_ranges([(p, off, p, off)])

    # ------------------------------------------------------------ clipboard and caret
    def caret_to_start(self):
        self.ed.move_caret("doc_start", False)
        self.view.after_move()

    def caret_to_end(self):
        self.ed.move_caret("doc_end", False)
        self.view.after_move()

    def _pos(self, off):
        """(paragraph, offset) of character `off` of the paragraphs joined with newlines."""
        nodes = self._nodes()
        for i, p in enumerate(nodes):
            ln = len(self.ed.para_text_of(p))
            if off <= ln or i == len(nodes) - 1:
                return p, min(off, ln)
            off -= ln + 1
        return (nodes[0] if nodes else 0), 0

    def select_offsets(self, a, b):
        pa, oa = self._pos(a)
        pb, ob = self._pos(b)
        self._select(pa, oa, pb, ob)

    def select_all(self):
        self.ed.select_all()
        self.view.after_move()

    def has_selection(self):
        return bool(self.ed and self.ed.has_selection())

    def copy(self):
        self.engine.copy()

    def cut(self):
        self.engine.copy(cut=True)

    def paste(self, plain=False):
        self.engine.paste(plain)

    # ------------------------------------------------------------ spelling
    def set_speller(self, sp, ignored=()):
        """sp: an Enchant dictionary (Post's own), used for the Spelling check; the marks as you type
        are Writer's, from the same dictionaries."""
        self.speller = sp
        self.ignored = set(w.lower() for w in ignored)
        self.win.ignored_words = set(ignored)
        try:
            self.view.speller = self.m["spell"].Speller(self.win)
        except Exception:
            self.view.speller = None
        self.view.queue_draw()

    def _nodes(self):
        """The body's paragraphs in order (table cells' paragraphs included), as engine node ids."""
        out = []
        try:
            for kind, node, ti in self.ed.body_blocks():
                if kind == "p":
                    out.append(node)
                else:
                    for row in self.ed.table_cells(ti):
                        for cell in row:
                            out.extend(cell)
        except Exception:
            pass
        return out

    def _paras(self):
        return len(self._nodes())

    def _select(self, na, a, nb, b):
        self.ed.select_ranges([(na, a, nb, b)])
        self.view.after_move()

    def misspelt(self):
        """[((para, start), (para, end), word)] of the words the dictionary doesn't know."""
        if self.speller is None:
            return []
        out = []
        for p in self._nodes():
            text = self.ed.para_text_of(p)
            for mm in WORD.finditer(text):
                w = mm.group(0)
                if len(w) < 2 or w.isupper() or w.lower() in self.ignored:
                    continue
                pre = text[max(0, mm.start() - 1):mm.start()]
                post = text[mm.end():mm.end() + 1]
                if pre and pre in "@./:" or post and post in ("@", "/"):
                    continue
                try:
                    ok = self.speller.check(w)
                except Exception:
                    ok = True
                if not ok:
                    out.append(((p, mm.start()), (p, mm.end()), w))
        return out

    def check_spelling(self):
        if self.view.speller is not None:
            try:
                self.view.speller.invalidate()
            except Exception:
                pass
        self.view.queue_draw()
        return False

    def suggest(self, word):
        try:
            return list(self.speller.suggest(word))
        except Exception:
            return []

    def select_issue(self, so, eo):
        (pa, a), (pb, b) = so, eo
        self._select(pa, a, pb, b)

    def replace_range(self, so, eo, text):
        (pa, a), (pb, b) = so, eo
        self._select(pa, a, pb, b)
        self._edit(self.ed.type_text, text)
        self.check_spelling()

    def ignore(self, word):
        self.ignored.add(word.lower())
        self.win.ignored_words.add(word)
        if self.on_ignore:
            self.on_ignore(word, False)
        self.check_spelling()

    def learn(self, word):
        self.ignored.add(word.lower())
        self.win.ignored_words.add(word)
        if self.on_ignore:
            self.on_ignore(word, True)
        self.check_spelling()

    def _press(self, view, ev):
        """Right-click on a misspelt word: suggestions, Ignore All, Add to Dictionary."""
        if ev.button != 3 or self.speller is None or self.ed is None:
            return False
        sp = self.view.speller
        hit = None
        try:
            pg, x, y = self.view.page_at(ev.x, ev.y)
            hit = sp.at(pg, x, y) if sp is not None else None
        except Exception:
            hit = None
        if not hit:
            return False
        para, a, b, word = hit[:4]
        menu = Gtk.Menu()
        for sug in self.suggest(word)[:6]:
            mi = Gtk.MenuItem(label=sug)
            mi.connect("activate", lambda *_x, s=sug: self.replace_range((para, a), (para, b), s))
            menu.append(mi)
        if len(menu.get_children()):
            menu.append(Gtk.SeparatorMenuItem())
        for label, fn in (("Ignore All", lambda *_: self.ignore(word)), ("Add to Dictionary", lambda *_: self.learn(word))):
            mi = Gtk.MenuItem(label=label)
            mi.connect("activate", fn)
            menu.append(mi)
        menu.show_all()
        menu.attach_to_widget(self, None)
        menu.popup_at_pointer(ev)
        return True

    # ------------------------------------------------------------ out
    def _docx_bytes(self):
        fd, path = tempfile.mkstemp(suffix=".docx", prefix="folio-post-")
        os.close(fd)
        try:
            self.ed.save(path)
            with open(path, "rb") as f:
                return f.read()
        finally:
            os.unlink(path)

    def text(self):
        try:
            lines = self.engine.plain_lines()
        except Exception:
            lines = [self.ed.para_text_of(p) for p in self._nodes()]
        return "\n".join(lines).replace("￼", "")

    def is_empty(self):
        if self.text().strip():
            return False
        try:
            return not self.ed.objects_list() and all(k == "p" for k, _n, _t in self.ed.body_blocks())
        except Exception:
            return True

    def to_html_raw(self):
        return self.to_html(inline_data=True)[0]

    def to_html(self, inline_data=False):
        """The body as HTML, and the pictures it shows: [(content id, type, bytes)]."""
        hx = self.m["htmlexport"]
        fd, path = tempfile.mkstemp(suffix=".docx", prefix="folio-post-")
        os.close(fd)
        try:
            self.ed.save(path)
            try:
                labels = {k: v for k, v in enumerate(self.ed.body_labels()) if v}
            except Exception:
                labels = {}
            page = hx.docx_to_html(path, "", labels)
        finally:
            os.unlink(path)
        m = re.search(r"<body[^>]*>(.*)</body>", page, re.S)
        body = m.group(1).strip() if m else page
        body = _lists_to_html(body)
        # mail programs drop <style> blocks: the paragraph spacing goes on the paragraphs
        body = re.sub(r"<p(?=[\s>])(?![^>]*style=)", '<p style="margin:0 0 8pt 0;line-height:1.08"', body)
        pics = []
        if not inline_data:
            def cid(mm):
                ctype, data = mm.group(1), base64.b64decode(mm.group(2))
                n = len(pics) + 1
                c = "image%03d.%s@folio-post" % (n, (ctype.split("/")[-1] or "png").replace("jpeg", "jpg"))
                pics.append((c, ctype, data))
                return 'src="cid:%s"' % c
            body = re.sub(r'src="data:([\w/+.-]+);base64,([A-Za-z0-9+/=\s]+)"', cid, body)
        doc = ('<div style="font-family:%s,Carlito,sans-serif;font-size:%spt">%s</div>' %
               (self.default_font, self.default_size, body))
        return doc, pics

    def load_html(self, text):
        """Formatted text into a fresh message (a draft, a signature, a reply's start)."""
        self.new()
        if text and text.strip():
            self.engine.paste_html(text)
            # pasting leaves a blank paragraph from the template at the end
            self.ed.move_caret("doc_end", False)
            nodes = self._nodes()
            if len(nodes) > 1 and not self.ed.para_text_of(nodes[-1]):
                self.ed.delete(False, False)
            self.ed.move_caret("doc_start", False)
        self.view.after_edit()

    def insert_html(self, text):
        """HTML (a signature) at the caret."""
        self.engine.paste_html(text)
