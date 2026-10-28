"""The message editor: formatted text in a Gtk.TextView (fonts, sizes, bold, italic, underline,
strikethrough, colours, highlight, alignment, bullets, numbering, indents, links and pictures),
written out as the HTML and plain text a message carries."""
import base64
import html
import re
import uuid
from html.parser import HTMLParser

from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, Pango

DEFAULT_FONT = "Calibri"
DEFAULT_SIZE = 11
CHAR_PROPS = ("bold", "italic", "underline", "strike", "font", "size", "color", "highlight", "link")
PARA_PROPS = ("align", "list", "indent")


class RichEditor(Gtk.TextView):
    def __init__(self):
        Gtk.TextView.__init__(self)
        self.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.set_left_margin(14)
        self.set_right_margin(14)
        self.set_top_margin(10)
        self.set_bottom_margin(10)
        self.get_style_context().add_class("folio-editor")
        self.buf = self.get_buffer()
        self.tags = {}
        self.pending = {}          # formatting typed next, with no selection
        self.images = {}           # anchor -> (cid, type, bytes)
        self.undo = []
        self.redo_ = []
        self._quiet = False
        self.default_font = DEFAULT_FONT
        self.default_size = DEFAULT_SIZE
        self.on_state = None
        self.buf.connect("insert-text", self._before_insert)
        self.buf.connect_after("insert-text", self._after_insert)
        self.buf.connect("delete-range", self._before_delete)
        self.buf.connect("mark-set", lambda *_: self._notify())
        self.connect("key-press-event", self._key)
        self._base = self.buf.create_tag("base", family=DEFAULT_FONT, size_points=DEFAULT_SIZE)

    # ------------------------------------------------------------ tags
    def tag(self, kind, value=True):
        key = (kind, value)
        t = self.tags.get(key)
        if t is not None:
            return t
        props = {}
        if kind == "bold":
            props["weight"] = Pango.Weight.BOLD
        elif kind == "italic":
            props["style"] = Pango.Style.ITALIC
        elif kind == "underline":
            props["underline"] = Pango.Underline.SINGLE
        elif kind == "strike":
            props["strikethrough"] = True
        elif kind == "font":
            props["family"] = value
        elif kind == "size":
            props["size_points"] = float(value)
        elif kind == "color":
            props["foreground"] = "#" + value
        elif kind == "highlight":
            props["background"] = "#" + value
        elif kind == "link":
            props["foreground"] = "#0563C1"
            props["underline"] = Pango.Underline.SINGLE
        elif kind == "align":
            props["justification"] = {"left": Gtk.Justification.LEFT, "center": Gtk.Justification.CENTER,
                                      "right": Gtk.Justification.RIGHT, "justify": Gtk.Justification.FILL}[value]
        elif kind == "indent":
            props["left_margin"] = 14 + 36 * int(value)
        elif kind == "list":
            props["left_margin"] = 14 + 24
            props["indent"] = -18
        t = self.buf.create_tag(None, **props)
        t.kind, t.value = kind, value
        self.tags[key] = t
        return t

    def _tags_of(self, it, kind):
        return [t for t in it.get_tags() if getattr(t, "kind", None) == kind]

    def state(self):
        """The formatting at the cursor (or the selection's start)."""
        b = self.buf
        if b.get_has_selection():
            it = b.get_selection_bounds()[0]
        else:
            it = b.get_iter_at_mark(b.get_insert())
            if not it.starts_line():
                it.backward_char()
        out = {k: None for k in CHAR_PROPS + PARA_PROPS}
        for k in ("bold", "italic", "underline", "strike"):
            out[k] = bool(self._tags_of(it, k))
        for k in ("font", "size", "color", "highlight", "link", "align", "list", "indent"):
            ts = self._tags_of(it, k)
            out[k] = ts[0].value if ts else None
        ps = self._tags_of(self._line_start(b.get_iter_at_mark(b.get_insert())), "align")
        out["align"] = ps[0].value if ps else "left"
        ls = self._tags_of(self._line_start(b.get_iter_at_mark(b.get_insert())), "list")
        out["list"] = ls[0].value if ls else None
        out["font"] = out["font"] or self.default_font
        out["size"] = out["size"] or self.default_size
        for k, v in self.pending.items():
            out[k] = v
        return out

    def _notify(self):
        if self.on_state:
            GLib.idle_add(lambda: (self.on_state(self.state()) if self.on_state else None, False)[1])

    def _line_start(self, it):
        it = it.copy()
        it.set_line_offset(0)
        return it

    # ------------------------------------------------------------ undo
    def _snapshot(self):
        if self._quiet:
            return
        self.undo.append(self.to_html_raw())
        del self.undo[:-100]
        self.redo_ = []

    def do_undo(self):
        if not self.undo:
            return False
        self.redo_.append(self.to_html_raw())
        self._quiet = True
        self.load_html(self.undo.pop())
        self._quiet = False
        return True

    def do_redo(self):
        if not self.redo_:
            return False
        self.undo.append(self.to_html_raw())
        self._quiet = True
        self.load_html(self.redo_.pop())
        self._quiet = False
        return True

    # ------------------------------------------------------------ typing
    def _before_insert(self, buf, it, text, n):
        if not self._quiet and (len(text) > 1 or text in " \n" or not self.undo):
            self._snapshot()
        self._ins_at = it.get_offset()

    def _after_insert(self, buf, it, text, n):
        if self._quiet:
            return
        start = buf.get_iter_at_offset(self._ins_at)
        # the typed text takes the formatting before it, then what was chosen for it
        before = start.copy()
        if before.backward_char() and before.get_char() != "\n":
            for t in before.get_tags():
                k = getattr(t, "kind", None)
                if k in CHAR_PROPS and k not in self.pending and k != "link":
                    buf.apply_tag(t, start, it)
        for k, v in self.pending.items():
            for t in list(self.tags.values()):
                if t.kind == k:
                    buf.remove_tag(t, start, it)
            if v not in (None, False):
                buf.apply_tag(self.tag(k, v), start, it)
        buf.apply_tag(self._base, start, it)
        if "\n" in text:
            # the new paragraph keeps its paragraph's alignment and list
            ln = self._line_start(start)
            pt = [t for t in ln.get_tags() if getattr(t, "kind", None) in PARA_PROPS]
            for t in pt:
                buf.apply_tag(t, start, it)

    def _before_delete(self, buf, a, b):
        if not self._quiet:
            self._snapshot()

    def _key(self, w, ev):
        if ev.keyval == Gdk.KEY_Return and not (ev.state & Gdk.ModifierType.SHIFT_MASK):
            # an empty list item ends the list
            b = self.buf
            it = b.get_iter_at_mark(b.get_insert())
            ls = self._tags_of(self._line_start(it), "list")
            if ls:
                ln = self._line_start(it)
                end = ln.copy()
                end.forward_to_line_end()
                text = b.get_text(ln, end, True)
                if text.strip() in ("•", "") or re.fullmatch(r"\d+\.\s*", text):
                    self.set_list(None)
                    return True
                GLib.idle_add(self._continue_list, ls[0].value)
        if ev.keyval == Gdk.KEY_Tab and ev.state & Gdk.ModifierType.CONTROL_MASK == 0:
            b = self.buf
            it = b.get_iter_at_mark(b.get_insert())
            if self._tags_of(self._line_start(it), "list"):
                self.indent(-1 if ev.state & Gdk.ModifierType.SHIFT_MASK else 1)
                return True
        return False

    def _continue_list(self, kind):
        b = self.buf
        it = b.get_iter_at_mark(b.get_insert())
        self._quiet = True
        ln = self._line_start(it)
        b.insert(ln, self._marker(kind, ln.get_line()))
        ln = self._line_start(b.get_iter_at_mark(b.get_insert()))
        e = ln.copy()
        e.forward_to_line_end()
        b.apply_tag(self.tag("list", kind), ln, e)
        self._quiet = False
        self._renumber()
        return False

    # ------------------------------------------------------------ formatting commands
    def _range(self):
        b = self.buf
        if b.get_has_selection():
            return b.get_selection_bounds()
        return None

    def _word_range(self):
        b = self.buf
        it = b.get_iter_at_mark(b.get_insert())
        if it.inside_word() and not it.starts_word():
            s, e = it.copy(), it.copy()
            s.backward_word_start()
            e.forward_word_end()
            return s, e
        return None

    def set_char(self, kind, value):
        """Apply character formatting to the selection (or the word, or what is typed next)."""
        r = self._range() or self._word_range()
        if r is None:
            self.pending[kind] = value
            self._notify()
            return
        self._snapshot()
        s, e = r
        for t in list(self.tags.values()):
            if t.kind == kind:
                self.buf.remove_tag(t, s, e)
        if value not in (None, False):
            self.buf.apply_tag(self.tag(kind, value), s, e)
        self._notify()

    def toggle(self, kind):
        self.set_char(kind, not self.state().get(kind))

    def clear_formatting(self):
        r = self._range()
        if r is None:
            self.pending = {}
            return
        self._snapshot()
        for t in list(self.tags.values()):
            if t.kind in CHAR_PROPS and t.kind != "link":
                self.buf.remove_tag(t, *r)
        self._notify()

    def _lines(self):
        b = self.buf
        r = self._range()
        if r:
            s, e = r
        else:
            s = e = b.get_iter_at_mark(b.get_insert())
        return range(s.get_line(), e.get_line() + 1)

    def _line_bounds(self, n):
        b = self.buf
        s = b.get_iter_at_line(n)
        e = s.copy()
        if not e.ends_line():
            e.forward_to_line_end()
        e2 = e.copy()
        e2.forward_char()   # the newline carries the paragraph's tags too
        return s, e2

    def set_align(self, value):
        self._snapshot()
        for n in self._lines():
            s, e = self._line_bounds(n)
            for t in list(self.tags.values()):
                if t.kind == "align":
                    self.buf.remove_tag(t, s, e)
            if value != "left":
                self.buf.apply_tag(self.tag("align", value), s, e)
        self._notify()

    def indent(self, step):
        self._snapshot()
        for n in self._lines():
            s, e = self._line_bounds(n)
            cur = self._tags_of(s, "indent")
            lvl = max(0, min(8, (cur[0].value if cur else 0) + step))
            for t in cur:
                self.buf.remove_tag(t, s, e)
            if lvl:
                self.buf.apply_tag(self.tag("indent", lvl), s, e)

    def _marker(self, kind, line):
        return "•\t" if kind == "bullet" else "1.\t"

    def set_list(self, kind):
        """Bullets ('bullet'), numbering ('number') or none for the selected paragraphs."""
        self._snapshot()
        self._quiet = True
        b = self.buf
        lines = list(self._lines())
        def marked(n):
            s0 = b.get_iter_at_line(n)
            e0 = s0.copy()
            e0.forward_to_line_end()
            return re.match(r"(•\t|\d+\.\t)", b.get_text(s0, e0, True)) is not None
        cur = self._tags_of(b.get_iter_at_line(lines[0]), "list")
        if kind is not None and cur and cur[0].value == kind and all(marked(n) for n in lines):
            kind = None
        for n in lines:
            s = b.get_iter_at_line(n)
            e = s.copy()
            e.forward_to_line_end()
            text = b.get_text(s, e, True)
            m = re.match(r"(•\t|\d+\.\t)", text)
            if m:
                e2 = s.copy()
                e2.forward_chars(len(m.group(1)))
                b.delete(s, e2)
                s = b.get_iter_at_line(n)
            s, e = self._line_bounds(n)
            for t in list(self.tags.values()):
                if t.kind == "list":
                    b.remove_tag(t, s, e)
            if kind:
                s = b.get_iter_at_line(n)
                b.insert(s, self._marker(kind, n))
                s, e = self._line_bounds(n)
                b.apply_tag(self.tag("list", kind), s, e)
        self._quiet = False
        self._renumber()
        self._notify()

    def _renumber(self):
        b = self.buf
        self._quiet = True
        k = 0
        for n in range(b.get_line_count()):
            s = b.get_iter_at_line(n)
            ls = self._tags_of(s, "list")
            if ls and ls[0].value == "number":
                k += 1
                e = s.copy()
                e.forward_to_line_end()
                m = re.match(r"\d+\.\t", b.get_text(s, e, True))
                if m and m.group(0) != "%d.\t" % k:
                    e2 = s.copy()
                    e2.forward_chars(len(m.group(0)))
                    b.delete(s, e2)
                    s = b.get_iter_at_line(n)
                    b.insert(s, "%d.\t" % k)
                    s, e = self._line_bounds(n)
                    b.apply_tag(self.tag("list", "number"), s, e)
            else:
                k = 0
        self._quiet = False

    def insert_link(self, url, text=None):
        self._snapshot()
        b = self.buf
        r = self._range()
        if r is None:
            it = b.get_iter_at_mark(b.get_insert())
            off = it.get_offset()
            self._quiet = True
            b.insert(it, text or url)
            self._quiet = False
            s = b.get_iter_at_offset(off)
            e = b.get_iter_at_mark(b.get_insert())
        else:
            s, e = r
        for t in list(self.tags.values()):
            if t.kind == "link":
                b.remove_tag(t, s, e)
        if url:
            b.apply_tag(self.tag("link", url), s, e)
            b.apply_tag(self._base, s, e)

    def insert_picture(self, data, ctype="image/png", width=None):
        self._snapshot()
        loader = GdkPixbuf.PixbufLoader()
        loader.write(data)
        loader.close()
        pb = loader.get_pixbuf()
        if pb is None:
            return False
        maxw = width or 600
        if pb.get_width() > maxw:
            pb = pb.scale_simple(maxw, int(pb.get_height() * maxw / pb.get_width()), GdkPixbuf.InterpType.BILINEAR)
        b = self.buf
        it = b.get_iter_at_mark(b.get_insert())
        anchor = b.create_child_anchor(it)
        img = Gtk.Image.new_from_pixbuf(pb)
        img.show()
        self.add_child_at_anchor(img, anchor)
        self.images[anchor] = ("img%s@folio" % uuid.uuid4().hex[:12], ctype, data, pb.get_width())
        return True

    def insert_text(self, text):
        b = self.buf
        b.insert_at_cursor(text)

    # ------------------------------------------------------------ out
    def is_empty(self):
        return not self.text().strip() and not self.images

    def text(self):
        b = self.buf
        return b.get_text(b.get_start_iter(), b.get_end_iter(), False).replace("￼", "")

    def to_html_raw(self):
        return self.to_html(inline_data=True)[0]

    def to_html(self, inline_data=False):
        """The body as HTML, and the pictures it shows: [(content id, type, bytes)]."""
        b = self.buf
        out = []
        pics = []
        lines = b.get_line_count()
        list_open = None
        for n in range(lines):
            s = b.get_iter_at_line(n)
            e = s.copy()
            if not e.ends_line():
                e.forward_to_line_end()
            ls = self._tags_of(s, "list")
            kind = ls[0].value if ls else None
            if kind != list_open:
                if list_open:
                    out.append("</ul>" if list_open == "bullet" else "</ol>")
                if kind:
                    out.append("<ul>" if kind == "bullet" else "<ol>")
                list_open = kind
            al = self._tags_of(s, "align")
            ind = self._tags_of(s, "indent")
            style = "margin:0"
            if al:
                style += ";text-align:%s" % al[0].value
            if ind:
                style += ";margin-left:%dpt" % (36 * ind[0].value)
            inner = self._runs_html(s, e, pics, inline_data)
            if kind:
                inner = re.sub(r"^((?:<[^>]+>)*)(•&emsp;|\d+\.&emsp;)", r"\1", inner)
                inner = re.sub(r"<span style=\"[^\"]*\"></span>", "", inner)
                out.append("<li>%s</li>" % (inner or "<br>"))
            else:
                out.append('<p style="%s">%s</p>' % (style, inner or "<br>"))
        if list_open:
            out.append("</ul>" if list_open == "bullet" else "</ol>")
        body = "\n".join(out)
        doc = ('<div style="font-family:%s,sans-serif;font-size:%spt">%s</div>' %
               (html.escape(self.default_font), self.default_size, body))
        return doc, pics

    def _runs_html(self, s, e, pics, inline_data):
        out = []
        it = s.copy()
        while it.compare(e) < 0:
            anchor = it.get_child_anchor()
            if anchor is not None:
                if anchor in self.images:
                    cid, ctype, data, w = self.images[anchor]
                    src = ("data:%s;base64,%s" % (ctype, base64.b64encode(data).decode())) if inline_data else "cid:" + cid
                    out.append('<img src="%s" width="%d">' % (src, w))
                    pics.append((cid, ctype, data))
                it.forward_char()
                continue
            nxt = it.copy()
            if not nxt.forward_to_tag_toggle(None) or nxt.compare(e) > 0:
                nxt = e.copy()
            # stop at pictures inside the run
            t2 = it.copy()
            while t2.compare(nxt) < 0:
                if t2.get_child_anchor() is not None and t2.compare(it) > 0:
                    nxt = t2.copy()
                    break
                t2.forward_char()
            text = it.get_text(nxt)
            if not text:
                it.forward_char()
                continue
            tags = {getattr(t, "kind", None): getattr(t, "value", None) for t in it.get_tags()}
            h = html.escape(text).replace("\t", "&emsp;").replace("  ", " &nbsp;")
            st = []
            if "font" in tags:
                st.append("font-family:%s" % html.escape(tags["font"]))
            if "size" in tags:
                st.append("font-size:%spt" % tags["size"])
            if "color" in tags:
                st.append("color:#%s" % tags["color"])
            if "highlight" in tags:
                st.append("background-color:#%s" % tags["highlight"])
            if st:
                h = '<span style="%s">%s</span>' % (";".join(st), h)
            if "bold" in tags:
                h = "<b>%s</b>" % h
            if "italic" in tags:
                h = "<i>%s</i>" % h
            if "underline" in tags:
                h = "<u>%s</u>" % h
            if "strike" in tags:
                h = "<s>%s</s>" % h
            if "link" in tags:
                h = '<a href="%s">%s</a>' % (html.escape(tags["link"], quote=True), h)
            out.append(h)
            it = nxt
        return "".join(out)

    # ------------------------------------------------------------ in
    def load_html(self, text):
        """Formatted text back into the editor (a draft, a signature, undo)."""
        self._quiet = True
        self.buf.set_text("")
        self.images = {}
        p = _Loader(self)
        try:
            p.feed(text)
            p.close()
        except Exception:
            import traceback
            traceback.print_exc()
        # a trailing empty paragraph
        end = self.buf.get_end_iter()
        it = end.copy()
        if it.backward_char() and it.get_char() == "\n":
            self.buf.delete(it, end)
        self._quiet = False
        self._renumber()

    def insert_html(self, text):
        """HTML (a signature) at the cursor."""
        mark = self.buf.create_mark(None, self.buf.get_iter_at_mark(self.buf.get_insert()), True)
        self._quiet = True
        p = _Loader(self, at_cursor=True)
        try:
            p.feed(text)
            p.close()
        except Exception:
            pass
        self._quiet = False
        self.buf.delete_mark(mark)


def _css(style):
    out = {}
    for part in (style or "").split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip().lower()] = v.strip()
    return out


def _hex(v):
    v = (v or "").strip().lower()
    m = re.fullmatch(r"#([0-9a-f]{6})", v)
    if m:
        return m.group(1).upper()
    m = re.fullmatch(r"#([0-9a-f]{3})", v)
    if m:
        return "".join(c * 2 for c in m.group(1)).upper()
    m = re.fullmatch(r"rgb\((\d+),\s*(\d+),\s*(\d+)\)", v)
    if m:
        return "%02X%02X%02X" % tuple(int(x) for x in m.groups())
    named = {"red": "FF0000", "blue": "0000FF", "green": "008000", "black": "000000", "white": "FFFFFF",
             "yellow": "FFFF00", "gray": "808080", "grey": "808080"}
    return named.get(v)


class _Loader(HTMLParser):
    BLOCK = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "blockquote"}

    def __init__(self, ed, at_cursor=False):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.ed = ed
        self.b = ed.buf
        self.stack = []
        self.lists = []
        self.para = {}
        self.at_cursor = at_cursor
        self.started = False
        self.skip = 0

    def _it(self):
        return self.b.get_iter_at_mark(self.b.get_insert()) if self.at_cursor else self.b.get_end_iter()

    def write(self, text):
        if not text:
            return
        it = self._it()
        off = it.get_offset()
        self.b.insert(it, text)
        s = self.b.get_iter_at_offset(off)
        e = self.b.get_iter_at_offset(off + len(text))
        self.b.apply_tag(self.ed._base, s, e)
        merged = {}
        for _tag, props in self.stack:
            merged.update(props)
        if merged.get("font", "").lower() == self.ed.default_font.lower():
            merged.pop("font")
        if "size" in merged and float(merged["size"]) == float(self.ed.default_size):
            merged.pop("size")
        for k, v in merged.items():
            self.b.apply_tag(self.ed.tag(k, v), s, e)
        for k, v in self.para.items():
            ln = s.copy()
            ln.set_line_offset(0)
            self.b.apply_tag(self.ed.tag(k, v), ln, e)
        self.started = True

    def newline(self):
        if self.started:
            it = self._it()
            if not it.starts_line() or True:
                self.write("\n")

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("style", "script", "head", "title"):
            self.skip += 1
            return
        css = _css(a.get("style"))
        props = {}
        if tag in ("b", "strong") or css.get("font-weight") in ("bold", "700", "600"):
            props["bold"] = True
        if tag in ("i", "em") or css.get("font-style") == "italic":
            props["italic"] = True
        if tag == "u" or "underline" in css.get("text-decoration", ""):
            props["underline"] = True
        if tag in ("s", "strike", "del") or "line-through" in css.get("text-decoration", ""):
            props["strike"] = True
        if "font-family" in css:
            props["font"] = css["font-family"].split(",")[0].strip("'\" ")
        if "font-size" in css:
            m = re.match(r"([\d.]+)pt", css["font-size"])
            if m:
                props["size"] = float(m.group(1)) if "." in m.group(1) else int(m.group(1))
        c = _hex(css.get("color"))
        if c:
            props["color"] = c
        h = _hex(css.get("background-color") or css.get("background"))
        if h and tag not in ("div", "p", "td", "table", "body"):
            props["highlight"] = h
        if tag == "font":
            if a.get("face"):
                props["font"] = a["face"].split(",")[0]
            c = _hex(a.get("color"))
            if c:
                props["color"] = c
        if tag == "a" and a.get("href"):
            props["link"] = a["href"]
        if tag in ("ul", "ol"):
            self.lists.append("bullet" if tag == "ul" else "number")
        if tag in self.BLOCK:
            if self.started and not self._it().starts_line():
                self.write("\n")
            self.para = {}
            if css.get("text-align") in ("center", "right", "justify"):
                self.para["align"] = css["text-align"]
            m = re.match(r"([\d.]+)pt", css.get("margin-left", ""))
            if m and float(m.group(1)) >= 30:
                self.para["indent"] = min(8, int(round(float(m.group(1)) / 36)))
            if tag == "li" and self.lists:
                self.para["list"] = self.lists[-1]
                self.write("•\t" if self.lists[-1] == "bullet" else "1.\t")
        if tag == "br":
            self.write("\n")
        if tag == "img":
            src = a.get("src", "")
            m = re.match(r"data:([\w/+.-]+);base64,(.*)", src, re.S)
            if m:
                try:
                    data = base64.b64decode(m.group(2))
                    it = self._it()
                    self.b.place_cursor(it) if not self.at_cursor else None
                    w = int(a.get("width") or 0) or None
                    self.ed.insert_picture(data, m.group(1), w)
                except Exception:
                    pass
            return
        self.stack.append((tag, props))

    def handle_endtag(self, tag):
        if tag in ("style", "script", "head", "title"):
            self.skip = max(0, self.skip - 1)
            return
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break
        if tag in ("ul", "ol") and self.lists:
            self.lists.pop()
        if tag in self.BLOCK:
            self.write("\n")
            self.para = {}

    def handle_data(self, data):
        if self.skip:
            return
        if not data.strip() and ("\n" in data or self._it().starts_line()):
            return
        data = re.sub(r"[\r\n]+", " ", data)
        data = data.replace(" ", "\t")
        if not data.strip() and not self.started:
            return
        self.write(data)
