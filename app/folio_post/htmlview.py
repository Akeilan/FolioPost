"""Showing HTML mail safely, without a web engine: the HTML is parsed here and only text,
formatting, links, lists, simple tables and pictures are shown. Scripts, forms, styles that
could hide or fake content, and remote pictures (until allowed) never run or load."""
import html
import re
from html.parser import HTMLParser

from gi.repository import Gdk, GdkPixbuf, Gtk, Pango

BLOCK = {"p", "div", "section", "article", "header", "footer", "main", "aside", "nav", "address", "center", "form",
         "fieldset", "figure", "figcaption", "details", "summary"}
HEAD = {"h1": 1.8, "h2": 1.5, "h3": 1.25, "h4": 1.1, "h5": 1.0, "h6": 0.9}
SKIP = {"script", "style", "head", "title", "noscript", "template", "iframe", "object", "embed", "applet", "svg",
        "math", "select", "textarea", "button", "canvas", "video", "audio", "frameset", "frame", "meta", "link", "base"}
NAMED_COLORS = {"black": "#000000", "white": "#ffffff", "red": "#ff0000", "green": "#008000", "blue": "#0000ff",
                "gray": "#808080", "grey": "#808080", "navy": "#000080", "maroon": "#800000", "purple": "#800080",
                "orange": "#ffa500", "yellow": "#ffff00", "silver": "#c0c0c0", "teal": "#008080", "olive": "#808000"}


def _color(v):
    v = (v or "").strip().lower()
    if v in NAMED_COLORS:
        return NAMED_COLORS[v]
    m = re.match(r"#([0-9a-f]{3}|[0-9a-f]{6})$", v)
    if m:
        h = m.group(1)
        return "#" + ("".join(c * 2 for c in h) if len(h) == 3 else h)
    m = re.match(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", v)
    if m:
        return "#%02x%02x%02x" % tuple(min(255, int(x)) for x in m.groups())
    return None


def _style(s):
    out = {}
    for part in (s or "").split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip().lower()] = v.strip()
    return out


def _size(v, base):
    m = re.match(r"([\d.]+)\s*(px|pt|em|rem|%)?", (v or "").strip())
    if not m:
        return None
    n = float(m.group(1))
    u = m.group(2) or "px"
    return n * 0.75 if u == "px" else n if u == "pt" else n * base if u in ("em", "rem") else n / 100 * base


def safe_link(href):
    h = (href or "").strip()
    low = re.sub(r"[\s\x00-\x1f]", "", h).lower()
    if low.startswith(("http:", "https:", "mailto:", "tel:")) or low.startswith("#"):
        return h
    return None


class _Builder(HTMLParser):
    """Parses HTML into runs of text with formatting, written straight into a TextBuffer."""

    def __init__(self, view, images, allow_remote, base_size):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.v = view
        self.buf = view.buf
        self.images = images            # cid -> bytes
        self.allow_remote = allow_remote
        self.base = base_size
        self.stack = []                 # (tag, {props})
        self.skip = 0
        self.pending_space = False
        self.at_line_start = True
        self.lists = []                 # [kind, counter]
        self.pre = 0
        self.blocked = 0
        self.links = []
        self.cell = None                # table: cells of the current row
        self.row_open = False

    # the formatting in force
    def props(self):
        p = {}
        for _t, d in self.stack:
            p.update(d)
        return p

    def tag_for(self, p):
        key = tuple(sorted(p.items()))
        t = self.v.tags.get(key)
        if t is None:
            t = self.buf.create_tag(None)
            for k, val in p.items():
                if k == "bold":
                    t.set_property("weight", Pango.Weight.BOLD)
                elif k == "italic":
                    t.set_property("style", Pango.Style.ITALIC)
                elif k == "underline":
                    t.set_property("underline", Pango.Underline.SINGLE)
                elif k == "strike":
                    t.set_property("strikethrough", True)
                elif k == "color":
                    t.set_property("foreground", val)
                elif k == "bg":
                    t.set_property("background", val)
                elif k == "size":
                    t.set_property("size-points", val)
                elif k == "mono":
                    t.set_property("family", "Monospace")
                elif k == "family":
                    t.set_property("family", val)
                elif k == "indent":
                    t.set_property("left-margin", 12 + int(val))
                elif k == "quote":
                    t.set_property("left-margin", 12 + 24 * val)
                    t.set_property("foreground", "#555555")
                elif k == "center":
                    t.set_property("justification", Gtk.Justification.CENTER)
                elif k == "right":
                    t.set_property("justification", Gtk.Justification.RIGHT)
                elif k == "link":
                    t.set_property("foreground", "#0563c1")
                    t.set_property("underline", Pango.Underline.SINGLE)
                elif k == "super":
                    t.set_property("rise", 4 * Pango.SCALE)
                    t.set_property("scale", 0.75)
                elif k == "sub":
                    t.set_property("rise", -3 * Pango.SCALE)
                    t.set_property("scale", 0.75)
            if "link" in p:
                t.link = p["link"]
            self.v.tags[key] = t
        return t

    def write(self, text):
        if not text:
            return
        p = self.props()
        if "hidden" in p:
            return
        self.buf.insert_with_tags(self.buf.get_end_iter(), text, self.tag_for(p))
        self.at_line_start = text.endswith("\n")

    def newline(self, n=1):
        """End the current line (n=2: a blank line between blocks)."""
        end = self.buf.get_end_iter()
        if self.buf.get_char_count() == 0:
            return
        # count the newlines already there
        have = 0
        it = end.copy()
        while have < n and it.backward_char() and it.get_char() == "\n":
            have += 1
        self.write("\n" * (n - have) if n > have else "")
        self.pending_space = False
        self.at_line_start = True

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag in SKIP:
            if tag not in ("meta", "link", "base"):
                self.skip += 1
            return
        if self.skip:
            return
        st = _style(a.get("style"))
        if st.get("display", "").strip() == "none" or "hidden" in a or st.get("visibility") == "hidden" or \
                st.get("max-height", "").strip() in ("0", "0px") or st.get("font-size", "").strip() in ("0", "0px"):
            props = {"hidden": True}
        else:
            props = {}
        cur = self.props()
        base = cur.get("size", self.base)
        if tag in ("b", "strong"):
            props["bold"] = True
        elif tag in ("i", "em", "cite", "var"):
            props["italic"] = True
        elif tag in ("u", "ins"):
            props["underline"] = True
        elif tag in ("s", "strike", "del"):
            props["strike"] = True
        elif tag in ("code", "tt", "kbd", "samp"):
            props["mono"] = True
        elif tag == "sup":
            props["super"] = True
        elif tag == "sub":
            props["sub"] = True
        elif tag == "pre":
            self.newline(2)
            props["mono"] = True
            self.pre += 1
        elif tag in HEAD:
            self.newline(2)
            props["bold"] = True
            props["size"] = self.base * HEAD[tag]
        elif tag == "blockquote":
            self.newline(2)
            props["quote"] = cur.get("quote", 0) + 1
        elif tag in ("ul", "ol"):
            self.newline(1 if self.lists else 2)
            self.lists.append([tag, int(a.get("start", "1") or 1) - 1])
            props["indent"] = 22 * len(self.lists)
        elif tag == "li":
            self.newline(1)
            if self.lists:
                kind = self.lists[-1]
                kind[1] += 1
                self.write(("%d. " % kind[1]) if kind[0] == "ol" else "• ")
            else:
                self.write("• ")
        elif tag == "a":
            href = safe_link(a.get("href"))
            if href:
                props["link"] = href
        elif tag == "font":
            c = _color(a.get("color"))
            if c:
                props["color"] = c
            if a.get("size", "").strip().lstrip("+-").isdigit():
                n = int(a["size"].strip()) if not a["size"].strip().startswith(("+", "-")) else 3 + int(a["size"])
                props["size"] = {1: 7.5, 2: 10, 3: 12, 4: 13.5, 5: 18, 6: 24, 7: 36}.get(max(1, min(7, n)), 12)
            if a.get("face"):
                props["family"] = a["face"].split(",")[0].strip("'\" ")
        elif tag == "br":
            self.write("\n")
            return
        elif tag == "hr":
            self.newline(1)
            self.write("─" * 40 + "\n")
            return
        elif tag == "img":
            self.image(a)
            return
        elif tag == "table":
            self.newline(1)
        elif tag == "tr":
            self.newline(1)
            self.cell = 0
        elif tag in ("td", "th"):
            if self.cell:
                self.write("\t")
            self.cell = (self.cell or 0) + 1
            if tag == "th":
                props["bold"] = True
        elif tag in BLOCK:
            self.newline(1 if tag == "div" else 2)
        # styles that are safe to show
        if "color" in st and _color(st["color"]):
            props["color"] = _color(st["color"])
        if "background-color" in st and _color(st["background-color"]) and tag not in ("table", "td", "tr", "body", "div", "th"):
            props["bg"] = _color(st["background-color"])
        if st.get("font-weight", "").strip() in ("bold", "bolder", "600", "700", "800", "900"):
            props["bold"] = True
        if st.get("font-style", "").strip() == "italic":
            props["italic"] = True
        if "underline" in st.get("text-decoration", ""):
            props["underline"] = True
        if "font-size" in st:
            s = _size(st["font-size"], base)
            if s and 6 <= s <= 48:
                props["size"] = s
        if st.get("text-align", "").strip() == "center" or tag == "center" or a.get("align", "").lower() == "center":
            props["center"] = True
        elif st.get("text-align", "").strip() == "right" or a.get("align", "").lower() == "right":
            props["right"] = True
        if tag in ("p", "div", "td", "span", "a", "b", "i", "u", "font", "strong", "em", "li", "h1", "h2", "h3", "h4",
                   "h5", "h6", "blockquote", "ul", "ol", "table", "tr", "th", "pre", "code", "s", "sup", "sub",
                   "center", "section", "article", "header", "footer", "small", "big", "label", "abbr", "mark",
                   "tbody", "thead", "tfoot", "nav", "main", "aside", "address", "figure", "figcaption", "cite",
                   "dl", "dt", "dd", "q", "ins", "del", "strike", "tt", "kbd", "samp", "var", "time", "body", "html"):
            if tag == "small":
                props["size"] = base * 0.85
            elif tag == "big":
                props["size"] = base * 1.2
            elif tag == "mark":
                props["bg"] = "#ffff00"
            elif tag == "dd":
                props["indent"] = 22
            self.stack.append((tag, props))

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in SKIP:
            if tag not in ("meta", "link", "base"):
                self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        # close up to the matching tag
        for k in range(len(self.stack) - 1, -1, -1):
            if self.stack[k][0] == tag:
                del self.stack[k:]
                break
        if tag in ("ul", "ol") and self.lists:
            self.lists.pop()
            self.newline(1 if self.lists else 2)
        elif tag in BLOCK or tag in HEAD or tag in ("blockquote", "pre", "table"):
            self.newline(2 if tag not in ("div", "table") else 1)
            if tag == "pre":
                self.pre -= 1
        elif tag in ("tr", "li", "dt", "dd"):
            self.newline(1)

    def handle_data(self, data):
        if self.skip:
            return
        if not self.pre:
            data = re.sub(r"\s+", " ", data)
            if self.at_line_start:
                data = data.lstrip()
            if not data:
                return
        self.write(data)

    def image(self, a):
        src = (a.get("src") or "").strip()
        alt = a.get("alt", "")
        w = a.get("width", "")
        h = a.get("height", "")
        # tracking pixels: tiny pictures aren't shown at all
        if w in ("0", "1") and h in ("0", "1"):
            return
        data = None
        if src.lower().startswith("cid:"):
            data = self.images.get(src[4:].strip("<>"))
        elif src.lower().startswith("data:image/"):
            import base64
            try:
                data = base64.b64decode(src.split(",", 1)[1])
            except Exception:
                data = None
        elif src.lower().startswith(("http:", "https:")):
            if self.allow_remote is None or src not in self.allow_remote:
                self.blocked += 1
                if alt:
                    self.write("[%s]" % alt)
                return
            data = self.allow_remote[src]
        if not data:
            if alt:
                self.write("[%s]" % alt)
            return
        try:
            ld = GdkPixbuf.PixbufLoader()
            ld.write(data)
            ld.close()
            pb = ld.get_pixbuf()
        except Exception:
            return
        want_w = int(w) if w.isdigit() else None
        maxw = 640
        pw, ph = pb.get_width(), pb.get_height()
        tw = min(want_w or pw, maxw)
        if tw != pw and pw > 0:
            pb = pb.scale_simple(tw, max(1, int(ph * tw / pw)), GdkPixbuf.InterpType.BILINEAR)
        self.buf.insert_pixbuf(self.buf.get_end_iter(), pb)
        self.at_line_start = False


def remote_images(html_text):
    """The http(s) picture addresses an HTML body would load."""
    return list(dict.fromkeys(re.findall(r"""<img\b[^>]*\bsrc\s*=\s*["']?(https?://[^"'\s>]+)""", html_text or "", re.I)))


class MessageView(Gtk.TextView):
    """A read-only view of a message body (HTML shown safely, or plain text)."""

    def __init__(self):
        Gtk.TextView.__init__(self)
        self.set_editable(False)
        self.set_cursor_visible(False)
        self.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.set_left_margin(16)
        self.set_right_margin(16)
        self.set_top_margin(10)
        self.set_bottom_margin(16)
        self.get_style_context().add_class("folio-message")
        self.buf = self.get_buffer()
        self.tags = {}
        self.blocked = 0
        self.on_link = None
        self.connect("button-release-event", self._click)
        self.connect("motion-notify-event", self._motion)
        tabs = Pango.TabArray.new(8, True)
        for k in range(8):
            tabs.set_tab(k, Pango.TabAlign.LEFT, 160 * (k + 1))
        self.set_tabs(tabs)

    def clear(self):
        self.buf.set_text("")
        self.tags = {}
        self.blocked = 0

    def show_text(self, text, size=11.0):
        self.clear()
        b = _Builder(self, {}, None, size)
        # links in plain text become links
        pos = 0
        for m in re.finditer(r"(https?://[^\s<>\"]+|www\.[^\s<>\"]+|[\w.+-]+@[\w-]+\.[\w.-]+)", text):
            b.write(text[pos:m.start()])
            u = m.group(0)
            href = u if u.startswith("http") else ("mailto:" + u if "@" in u and not u.startswith("www") else "http://" + u)
            b.stack.append(("a", {"link": href}))
            b.write(u)
            b.stack.pop()
            pos = m.end()
        b.write(text[pos:])

    def show_html(self, html_text, images=None, allow_remote=None, size=11.0):
        self.clear()
        b = _Builder(self, images or {}, allow_remote, size)
        try:
            b.feed(html_text)
            b.close()
        except Exception:
            pass
        self.blocked = b.blocked
        # trailing blank lines
        end = self.buf.get_end_iter()
        it = end.copy()
        while it.backward_char() and it.get_char() in "\n ":
            pass
        it.forward_char()
        self.buf.delete(it, self.buf.get_end_iter())

    def text(self):
        return self.buf.get_text(self.buf.get_start_iter(), self.buf.get_end_iter(), False)

    def link_at(self, x, y):
        bx, by = self.window_to_buffer_coords(Gtk.TextWindowType.WIDGET, int(x), int(y))
        ok, it = self.get_iter_at_location(bx, by)
        if not ok:
            return None
        for t in it.get_tags():
            if getattr(t, "link", None):
                return t.link
        return None

    def _click(self, w, ev):
        if ev.button != 1:
            return False
        if self.buf.get_has_selection():
            return False
        link = self.link_at(ev.x, ev.y)
        if link and self.on_link:
            self.on_link(link)
            return True
        return False

    def _motion(self, w, ev):
        win = self.get_window(Gtk.TextWindowType.TEXT)
        if win is not None:
            name = "pointer" if self.link_at(ev.x, ev.y) else "text"
            win.set_cursor(Gdk.Cursor.new_from_name(win.get_display(), name))
        return False
