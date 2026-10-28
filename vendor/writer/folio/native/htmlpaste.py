"""HTML from the clipboard (a browser, another program) as WordprocessingML paragraphs and
tables, for the new engine's paste: headings, paragraphs, line breaks, lists, bold / italic /
underline / strike / super- and subscript, fonts, colours and sizes from inline styles, links
(as HYPERLINK fields) and tables."""
import html
import re
from html.parser import HTMLParser

BLOCKS = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "pre", "dt", "dd",
          "address", "section", "article", "header", "footer", "figcaption", "caption"}
SKIP = {"script", "style", "head", "title", "noscript", "template"}
NAMED = {"black": "000000", "white": "FFFFFF", "red": "FF0000", "green": "008000", "blue": "0000FF",
         "yellow": "FFFF00", "gray": "808080", "grey": "808080", "orange": "FFA500", "purple": "800080",
         "navy": "000080", "maroon": "800000", "teal": "008080", "silver": "C0C0C0"}


def _color(v):
    v = v.strip().lower()
    if v in NAMED:
        return NAMED[v]
    m = re.match(r"#([0-9a-f]{3})$", v)
    if m:
        return "".join(c * 2 for c in m.group(1)).upper()
    m = re.match(r"#([0-9a-f]{6})$", v)
    if m:
        return m.group(1).upper()
    m = re.match(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", v)
    if m:
        return "%02X%02X%02X" % tuple(min(255, int(x)) for x in m.groups())
    return None


def _size_pt(v):
    m = re.match(r"([\d.]+)\s*(pt|px|em|rem|%)?", v.strip())
    if not m:
        return None
    n, u = float(m.group(1)), m.group(2) or "px"
    return {"pt": n, "px": n * 0.75, "em": n * 11, "rem": n * 11, "%": n * 0.11}[u]


def _style(css):
    out = {}
    for part in (css or "").split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip().lower()] = v.strip()
    return out


def _esc(t):
    return html.escape(t, quote=False)


class _Conv(HTMLParser):
    def __init__(self, styles):
        super().__init__(convert_charrefs=True)
        self.styles = styles          # paragraph style ids in the document
        self.out = []                 # finished block XML
        self.runs = []                # runs of the paragraph being built
        self.ppr = None               # its pPr XML
        self.fmt = [{}]               # inline formatting stack
        self.tags = []
        self.lists = []               # "ul" / "ol" with counters
        self.skip = 0
        self.link = []                # hrefs
        self.tables = []              # [rows, row, cell blocks, cell-in-header]
        self.pre = 0

    # ---- paragraphs
    def _sink(self):
        return self.tables[-1]["cell"] if self.tables and self.tables[-1]["cell"] is not None else self.out

    def _flush(self, force=False):
        if self.runs or force:
            p = "<w:p>%s%s</w:p>" % (self.ppr or "", "".join(self.runs))
            self._sink().append(p)
        self.runs = []
        self.ppr = None

    def _style_ppr(self, sid):
        return '<w:pPr><w:pStyle w:val="%s"/></w:pPr>' % sid if sid in self.styles else None

    def _rpr(self):
        f = {}
        for d in self.fmt:
            f.update(d)
        parts = []
        if f.get("font"):
            parts.append('<w:rFonts w:ascii="%s" w:hAnsi="%s" w:cs="%s"/>' % ((html.escape(f["font"]),) * 3))
        for k, tag in (("b", "w:b"), ("i", "w:i")):
            if f.get(k):
                parts.append("<%s/>" % tag)
        if f.get("strike"):
            parts.append("<w:strike/>")
        if f.get("color"):
            parts.append('<w:color w:val="%s"/>' % f["color"])
        if f.get("size"):
            parts.append('<w:sz w:val="%d"/>' % int(round(f["size"] * 2)))
        if f.get("hl"):
            parts.append('<w:shd w:val="clear" w:color="auto" w:fill="%s"/>' % f["hl"])
        if f.get("u"):
            parts.append('<w:u w:val="single"/>')
        if f.get("va"):
            parts.append('<w:vertAlign w:val="%s"/>' % f["va"])
        return "<w:rPr>%s</w:rPr>" % "".join(parts) if parts else ""

    def _text(self, t):
        if not t:
            return
        rpr = self._rpr()
        run = '<w:r>%s<w:t xml:space="preserve">%s</w:t></w:r>' % (rpr, _esc(t))
        self.runs.append(run)

    # ---- parser callbacks
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in SKIP:
            self.skip += 1
            return
        if self.skip:
            return
        self.tags.append(tag)
        st = _style(a.get("style"))
        f = {}
        if tag in ("b", "strong") or st.get("font-weight") in ("bold", "700", "800", "900"):
            f["b"] = True
        if st.get("font-weight") in ("normal", "400"):
            f["b"] = False
        if tag in ("i", "em", "cite", "var") or st.get("font-style") == "italic":
            f["i"] = True
        if tag in ("u", "ins") or "underline" in st.get("text-decoration", ""):
            f["u"] = True
        if tag in ("s", "strike", "del") or "line-through" in st.get("text-decoration", ""):
            f["strike"] = True
        if tag == "sup":
            f["va"] = "superscript"
        if tag == "sub":
            f["va"] = "subscript"
        if tag in ("code", "kbd", "samp", "tt", "pre"):
            f["font"] = "Consolas"
        if st.get("font-family"):
            f["font"] = st["font-family"].split(",")[0].strip().strip("'\"")
        if st.get("color") and _color(st["color"]):
            f["color"] = _color(st["color"])
        if a.get("color") and _color(a["color"]):
            f["color"] = _color(a["color"])
        if st.get("background-color") and _color(st["background-color"]) and tag not in ("td", "th", "table", "tr"):
            f["hl"] = _color(st["background-color"])
        if st.get("font-size") and _size_pt(st["font-size"]):
            f["size"] = _size_pt(st["font-size"])
        if tag == "a" and a.get("href"):
            f["u"] = True
            f["color"] = "0563C1"
            self.link.append(a["href"])
            self.runs.append('<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText xml:space="preserve"> HYPERLINK "%s" </w:instrText></w:r><w:r><w:fldChar w:fldCharType="separate"/></w:r>'
                             % html.escape(a["href"]))
        self.fmt.append(f)
        if tag == "br":
            self.runs.append("<w:r><w:br/></w:r>")
        elif tag in ("ul", "ol"):
            self._flush()
            self.lists.append([tag, 0])
        elif tag in BLOCKS:
            self._flush()
            if tag[0] == "h" and tag[1:].isdigit():
                self.ppr = self._style_ppr("Heading%s" % tag[1:])
                if self.ppr is None:
                    self.fmt[-1].update({"b": True, "size": {1: 20, 2: 16, 3: 14}.get(int(tag[1]), 12)})
            elif tag == "li" and self.lists:
                kind = self.lists[-1]
                kind[1] += 1
                sid = "ListBullet" if kind[0] == "ul" else "ListNumber"
                self.ppr = self._style_ppr(sid)
                if self.ppr is None:
                    lvl = len(self.lists) - 1
                    self.ppr = '<w:pPr><w:ind w:left="%d" w:hanging="360"/></w:pPr>' % (720 * (lvl + 1))
                    self._text(("•\t" if kind[0] == "ul" else "%d.\t" % kind[1]))
            elif tag == "blockquote":
                self.ppr = '<w:pPr><w:ind w:left="720"/></w:pPr>'
            elif tag == "pre":
                self.pre += 1
            align = st.get("text-align")
            if align in ("center", "right", "justify"):
                jc = '<w:jc w:val="%s"/>' % {"justify": "both"}.get(align, align)
                self.ppr = (self.ppr or "<w:pPr></w:pPr>").replace("</w:pPr>", jc + "</w:pPr>")
        elif tag == "table":
            self._flush()
            self.tables.append({"rows": [], "row": None, "cell": None})
        elif tag == "tr" and self.tables:
            self.tables[-1]["row"] = []
        elif tag in ("td", "th") and self.tables:
            t = self.tables[-1]
            if t["row"] is None:
                t["row"] = []
            t["cell"] = []
            t["span"] = int(a.get("colspan", "1") or 1) if (a.get("colspan") or "1").isdigit() else 1
            fill = _color(st.get("background-color", "")) if st.get("background-color") else None
            t["fill"] = fill
            if tag == "th":
                self.fmt[-1]["b"] = True
        elif tag == "img":
            alt = a.get("alt")
            if alt:
                self._text("[%s]" % alt)

    def handle_endtag(self, tag):
        if tag in SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip or tag not in self.tags:
            return
        while self.tags:
            t = self.tags.pop()
            self.fmt.pop()
            self._close(t)
            if t == tag:
                break

    def _close(self, tag):
        if tag == "a" and self.link:
            self.link.pop()
            self.runs.append('<w:r><w:fldChar w:fldCharType="end"/></w:r>')
        elif tag in ("ul", "ol"):
            self._flush()
            if self.lists:
                self.lists.pop()
        elif tag in BLOCKS:
            self._flush()
            if tag == "pre":
                self.pre = max(0, self.pre - 1)
        elif tag in ("td", "th") and self.tables:
            self._flush()
            t = self.tables[-1]
            if t["cell"] is not None and t["row"] is not None:
                t["row"].append((t["cell"] or ["<w:p/>"], t.get("span", 1), t.get("fill")))
            t["cell"] = None
        elif tag == "tr" and self.tables:
            t = self.tables[-1]
            if t["row"]:
                t["rows"].append(t["row"])
            t["row"] = None
        elif tag == "table" and self.tables:
            self._flush()
            t = self.tables.pop()
            xml = _table(t["rows"])
            if xml:
                self._sink().append(xml)

    def handle_data(self, data):
        if self.skip:
            return
        if self.pre:
            lines = data.split("\n")
            for k, line in enumerate(lines):
                if k:
                    self.runs.append("<w:r><w:br/></w:r>")
                self._text(line)
            return
        t = re.sub(r"\s+", " ", data)
        if not self.runs and not t.strip():
            return
        if not self.runs:
            t = t.lstrip()
        self._text(t)

    def close(self):
        super().close()
        while self.tags:
            t = self.tags.pop()
            self.fmt.pop()
            self._close(t)
        self._flush()


def _table(rows):
    if not rows:
        return ""
    ncols = max(sum(span for _c, span, _f in r) for r in rows)
    w = 9360 // max(1, ncols)
    b = '<w:%s w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
    borders = "<w:tblBorders>%s</w:tblBorders>" % "".join(b % s for s in ("top", "left", "bottom", "right", "insideH", "insideV"))
    out = ['<w:tbl><w:tblPr><w:tblW w:w="0" w:type="auto"/>%s<w:tblLook w:val="04A0"/></w:tblPr><w:tblGrid>%s</w:tblGrid>'
           % (borders, "".join('<w:gridCol w:w="%d"/>' % w for _ in range(ncols)))]
    for r in rows:
        out.append("<w:tr>")
        used = 0
        for blocks, span, fill in r:
            tcpr = '<w:tcW w:w="%d" w:type="dxa"/>' % (w * span)
            if span > 1:
                tcpr += '<w:gridSpan w:val="%d"/>' % span
            if fill:
                tcpr += '<w:shd w:val="clear" w:color="auto" w:fill="%s"/>' % fill
            body = "".join(blocks)
            if not body.rstrip().endswith("</w:p>"):
                body += "<w:p/>"
            out.append("<w:tc><w:tcPr>%s</w:tcPr>%s</w:tc>" % (tcpr, body))
            used += span
        while used < ncols:
            out.append('<w:tc><w:tcPr><w:tcW w:w="%d" w:type="dxa"/></w:tcPr><w:p/></w:tc>' % w)
            used += 1
        out.append("</w:tr>")
    out.append("</w:tbl>")
    return "".join(out)


def to_fragment(text, styles=()):
    """Body XML (w:p and w:tbl elements) for an HTML fragment."""
    m = re.search(r"<!--StartFragment-->(.*)<!--EndFragment-->", text, re.S)
    if m:
        text = m.group(1)
    c = _Conv(set(styles))
    c.feed(text)
    c.close()
    return "".join(c.out)
