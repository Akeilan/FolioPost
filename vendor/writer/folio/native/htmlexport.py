"""WordprocessingML as HTML and RTF, without the old converter: a whole
document (Save As > Web Page / Rich Text Format) or a copied fragment (the
clipboard's formatted text for other programs).

Covered: headings and paragraph styles, alignment and indents, bold /
italic / underline / strike / super- and subscript, fonts, sizes, colours,
highlight, line and page breaks, tabs, hyperlinks, list paragraphs (with
their labels), tables (with merged cells) and pictures (embedded)."""
import base64
import html
import os
import re
import zipfile
import xml.etree.ElementTree as ET

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
PR = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"w": W, "r": R, "a": A}
NS_DECL = ('xmlns:w="%s" xmlns:r="%s" xmlns:a="%s" '
           'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
           'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture" '
           'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
           'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" '
           'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape" '
           'xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office" '
           'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math" '
           'xmlns:w15="http://schemas.microsoft.com/office/word/2012/wordml"' % (W, R, A))
HIGHLIGHT = {"yellow": "#FFFF00", "green": "#00FF00", "cyan": "#00FFFF", "magenta": "#FF00FF",
             "blue": "#0000FF", "red": "#FF0000", "darkBlue": "#000080", "darkCyan": "#008080",
             "darkGreen": "#008000", "darkMagenta": "#800080", "darkRed": "#800000",
             "darkYellow": "#808000", "darkGray": "#808080", "lightGray": "#C0C0C0",
             "black": "#000000", "white": "#FFFFFF"}


def q(tag):
    p, t = tag.split(":")
    return "{%s}%s" % (NS[p], t)


def _val(el, tag, attr="w:val"):
    if el is None:
        return None
    c = el.find(tag, NS)
    if c is None:
        return None
    return c.get(q(attr), "true")


def _on(el, tag):
    v = _val(el, tag)
    return v is not None and v not in ("0", "false", "off")


class Styles:
    """Paragraph style id -> (name, base, pPr, rPr)."""

    def __init__(self, xml=None, names=None):
        self.by_id = {}
        if xml:
            try:
                root = ET.fromstring(xml)
            except ET.ParseError:
                root = None
            if root is not None:
                for s in root.findall("w:style", NS):
                    sid = s.get(q("w:styleId"))
                    nm = s.find("w:name", NS)
                    base = s.find("w:basedOn", NS)
                    self.by_id[sid] = (nm.get(q("w:val")) if nm is not None else sid,
                                       base.get(q("w:val")) if base is not None else None,
                                       s.find("w:pPr", NS), s.find("w:rPr", NS))
        for sid, nm in (names or []):
            self.by_id.setdefault(sid, (nm, None, None, None))

    def name(self, sid):
        return self.by_id.get(sid, (sid or "Normal",))[0] or "Normal"

    def chain(self, sid):
        out, seen = [], set()
        while sid and sid in self.by_id and sid not in seen:
            seen.add(sid)
            out.append(self.by_id[sid])
            sid = self.by_id[sid][1]
        return out

    def heading(self, sid):
        m = re.match(r"(?i)heading\s*(\d)$", self.name(sid))
        if m:
            return min(6, int(m.group(1)))
        if self.name(sid).lower() == "title":
            return 1
        return 0


def _run_props(rpr, inherited=()):
    """The run's formatting: a dict of what's set (style first, then direct)."""
    st = {}
    for el in list(inherited) + [rpr]:
        if el is None:
            continue
        for tag, key in (("w:b", "b"), ("w:i", "i"), ("w:strike", "s"), ("w:dstrike", "s"),
                         ("w:caps", "caps"), ("w:smallCaps", "smallcaps"), ("w:vanish", "hidden")):
            if el.find(tag, NS) is not None:
                st[key] = _on(el, tag)
        u = _val(el, "w:u")
        if u is not None:
            st["u"] = u != "none"
        va = _val(el, "w:vertAlign")
        if va:
            st["va"] = va
        sz = _val(el, "w:sz")
        if sz and sz.isdigit():
            st["sz"] = int(sz) / 2
        c = _val(el, "w:color")
        if c and c != "auto":
            st["color"] = c
        hl = _val(el, "w:highlight")
        if hl and hl != "none":
            st["hl"] = HIGHLIGHT.get(hl)
        shd = el.find("w:shd", NS)
        if shd is not None and shd.get(q("w:fill")) not in (None, "auto"):
            st["hl"] = "#" + shd.get(q("w:fill"))
        f = el.find("w:rFonts", NS)
        if f is not None and (f.get(q("w:ascii")) or f.get(q("w:hAnsi"))):
            st["font"] = f.get(q("w:ascii")) or f.get(q("w:hAnsi"))
    return st


def _css_run(st):
    out = []
    if st.get("font"):
        out.append("font-family:'%s'" % st["font"].replace("'", ""))
    if st.get("sz"):
        out.append("font-size:%gpt" % st["sz"])
    if st.get("color"):
        out.append("color:#%s" % st["color"])
    if st.get("hl"):
        out.append("background:%s" % st["hl"])
    if st.get("caps"):
        out.append("text-transform:uppercase")
    if st.get("smallcaps"):
        out.append("font-variant:small-caps")
    return ";".join(out)


class Writer:
    """Walks body XML and writes HTML."""

    def __init__(self, styles, rels=None, media=None, labels=None):
        self.styles = styles
        self.rels = rels or {}
        self.media = media or {}
        self.labels = labels or {}
        self.para_index = 0

    # ------------------------------------------------------------ blocks
    def blocks(self, parent):
        out = []
        for el in parent:
            if el.tag == q("w:p"):
                out.append(self.para(el))
            elif el.tag == q("w:tbl"):
                out.append(self.table(el))
            elif el.tag == q("w:sdt"):
                c = el.find("w:sdtContent", NS)
                if c is not None:
                    out.append(self.blocks(c))
        return "\n".join(x for x in out if x is not None)

    def para(self, p):
        ppr = p.find("w:pPr", NS)
        sid = _val(ppr, "w:pStyle") or "Normal"
        chain = self.styles.chain(sid)
        inherited = [c[3] for c in reversed(chain)]
        css = []
        jc = _val(ppr, "w:jc")
        if jc is None:
            jc = next((_val(c[2], "w:jc") for c in chain if _val(c[2], "w:jc")), None)
        if jc in ("center", "right", "both", "end"):
            css.append("text-align:%s" % {"both": "justify", "end": "right"}.get(jc, jc))
        ind = ppr.find("w:ind", NS) if ppr is not None else None
        if ind is not None:
            for attr, prop in (("w:left", "margin-left"), ("w:start", "margin-left"),
                               ("w:right", "margin-right"), ("w:firstLine", "text-indent")):
                v = ind.get(q(attr))
                if v and v.lstrip("-").isdigit() and int(v):
                    css.append("%s:%gpt" % (prop, int(v) / 20))
            h = ind.get(q("w:hanging"))
            if h and h.isdigit() and int(h):
                css.append("text-indent:-%gpt" % (int(h) / 20))
        shd = ppr.find("w:shd", NS) if ppr is not None else None
        if shd is not None and shd.get(q("w:fill")) not in (None, "auto"):
            css.append("background:#%s" % shd.get(q("w:fill")))
        body = self.inlines(p, inherited)
        label = self.labels.get(self.para_index)
        self.para_index += 1
        if label:
            body = "<span class=\"label\">%s</span>&#9;%s" % (html.escape(label), body)
        lvl = self.styles.heading(sid)
        tag = "h%d" % lvl if lvl else "p"
        name = self.styles.name(sid)
        cls = "" if lvl or name == "Normal" else ' class="%s"' % re.sub(r"\W+", "", name)
        style = ' style="%s"' % ";".join(css) if css else ""
        return "<%s%s%s>%s</%s>" % (tag, cls, style, body or "&nbsp;", tag)

    def table(self, t):
        rows = []
        vmerge = {}
        for tr in t.findall("w:tr", NS):
            cells, col = [], 0
            for tc in tr.findall("w:tc", NS):
                tcpr = tc.find("w:tcPr", NS)
                span = int(_val(tcpr, "w:gridSpan") or 1)
                vm = tcpr.find("w:vMerge", NS) if tcpr is not None else None
                if vm is not None and vm.get(q("w:val")) != "restart":
                    if col in vmerge:
                        vmerge[col][1] += 1
                        vmerge[col][0]["rowspan"] = vmerge[col][1]
                    col += span
                    continue
                attrs = {}
                if span > 1:
                    attrs["colspan"] = span
                css = []
                shd = tcpr.find("w:shd", NS) if tcpr is not None else None
                if shd is not None and shd.get(q("w:fill")) not in (None, "auto"):
                    css.append("background:#%s" % shd.get(q("w:fill")))
                cell = [attrs, css, self.blocks(tc)]
                if vm is not None:
                    vmerge[col] = [attrs, 1]
                else:
                    vmerge.pop(col, None)
                cells.append(cell)
                col += span
            rows.append(cells)
        out = ['<table border="1" cellspacing="0" cellpadding="4" style="border-collapse:collapse">']
        for cells in rows:
            out.append("<tr>")
            for attrs, css, body in cells:
                a = "".join(' %s="%s"' % kv for kv in attrs.items())
                s = ' style="%s"' % ";".join(css) if css else ""
                out.append("<td%s%s>%s</td>" % (a, s, body))
            out.append("</tr>")
        out.append("</table>")
        return "\n".join(out)

    # ------------------------------------------------------------ runs
    def inlines(self, parent, inherited):
        out = []
        field = []          # complex field: (instruction, showing result)
        for el in parent:
            tag = el.tag
            if tag == q("w:r"):
                fc = el.find("w:fldChar", NS)
                if fc is not None:
                    t = fc.get(q("w:fldCharType"))
                    if t == "begin":
                        field.append(["", False, len(out)])
                    elif t == "separate" and field:
                        field[-1][1] = True
                        field[-1][2] = len(out)
                    elif t == "end" and field:
                        instr, _shown, at = field.pop()
                        m = re.search(r'HYPERLINK\s+"([^"]+)"', instr)
                        if m and at <= len(out):
                            inner = "".join(out[at:])
                            del out[at:]
                            out.append('<a href="%s">%s</a>' % (html.escape(m.group(1), True), inner))
                    continue
                it = el.find("w:instrText", NS)
                if it is not None and field:
                    field[-1][0] += it.text or ""
                    continue
                if field and not field[-1][1]:
                    continue
                out.append(self.run(el, inherited))
            elif tag == q("w:hyperlink"):
                rid = el.get(q("r:id"))
                href = self.rels.get(rid, ("", ""))[1] if rid else ""
                if not href and el.get(q("w:anchor")):
                    href = "#" + el.get(q("w:anchor"))
                inner = self.inlines(el, inherited)
                out.append('<a href="%s">%s</a>' % (html.escape(href, True), inner) if href else inner)
            elif tag in (q("w:ins"), q("w:smartTag"), q("w:customXml"), q("w:fldSimple")):
                out.append(self.inlines(el, inherited))
            elif tag == q("w:sdt"):
                c = el.find("w:sdtContent", NS)
                if c is not None:
                    out.append(self.inlines(c, inherited))
            elif tag == q("w:bookmarkStart"):
                nm = el.get(q("w:name"))
                if nm and not nm.startswith("_"):
                    out.append('<a name="%s"></a>' % html.escape(nm, True))
        return "".join(out)

    def run(self, r, inherited):
        st = _run_props(r.find("w:rPr", NS), inherited)
        if st.get("hidden"):
            return ""
        parts = []
        for c in r:
            t = c.tag
            if t == q("w:t"):
                parts.append(html.escape(c.text or ""))
            elif t == q("w:tab"):
                parts.append("&emsp;")
            elif t == q("w:br"):
                parts.append('<br style="page-break-before:always">' if c.get(q("w:type")) == "page" else "<br>")
            elif t == q("w:noBreakHyphen"):
                parts.append("&#8209;")
            elif t == q("w:sym"):
                ch = c.get(q("w:char"))
                if ch:
                    try:
                        parts.append("&#%d;" % int(ch, 16))
                    except ValueError:
                        pass
            elif t in (q("w:drawing"), q("w:pict")) or t.endswith("}AlternateContent"):
                parts.append(self.picture(c))
        s = "".join(parts)
        if not s:
            return ""
        css = _css_run(st)
        if css:
            s = '<span style="%s">%s</span>' % (css, s)
        for key, tag in (("b", "b"), ("i", "i"), ("u", "u"), ("s", "s")):
            if st.get(key):
                s = "<%s>%s</%s>" % (tag, s, tag)
        if st.get("va") == "superscript":
            s = "<sup>%s</sup>" % s
        elif st.get("va") == "subscript":
            s = "<sub>%s</sub>" % s
        return s

    def picture(self, el):
        blip = el.find(".//a:blip", NS)
        if blip is None:
            return ""
        rid = blip.get(q("r:embed"))
        target = self.rels.get(rid, ("", ""))[1] if rid else ""
        data = self.media.get(target)
        ext = el.find(".//{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}extent")
        size = ""
        if ext is not None:
            try:
                size = ' width="%d" height="%d"' % (int(ext.get("cx")) / 9525, int(ext.get("cy")) / 9525)
            except (TypeError, ValueError):
                size = ""
        if data is None:
            return ""
        mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif",
                "bmp": "image/bmp", "svg": "image/svg+xml", "webp": "image/webp"}.get(
            os.path.splitext(target)[1].lstrip(".").lower(), "image/png")
        return '<img src="data:%s;base64,%s"%s alt="">' % (mime, base64.b64encode(data).decode(), size)


PAGE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="Generator" content="Folio Writer">
<title>%s</title>
<style>
body { font-family: Calibri, Carlito, sans-serif; font-size: 11pt; max-width: 8.5in; margin: 1in auto; }
p { margin: 0 0 8pt 0; line-height: 1.08; }
h1 { font-size: 16pt; color: #2F5496; font-weight: normal; }
h2 { font-size: 13pt; color: #2F5496; font-weight: normal; }
h3 { font-size: 12pt; color: #1F3763; font-weight: normal; }
table { margin: 0 0 8pt 0; }
td p { margin: 0; }
</style>
</head>
<body>
%s
</body>
</html>
"""


def docx_to_html(docx, title="", labels=None):
    """A whole .docx as one HTML page (pictures embedded)."""
    with zipfile.ZipFile(docx) as z:
        names = set(z.namelist())
        doc = ET.fromstring(z.read("word/document.xml"))
        styles = Styles(z.read("word/styles.xml") if "word/styles.xml" in names else None)
        rels = {}
        if "word/_rels/document.xml.rels" in names:
            for r in ET.fromstring(z.read("word/_rels/document.xml.rels")):
                rels[r.get("Id")] = (r.get("Type", ""), r.get("Target", ""))
        media = {}
        for rid, (_t, target) in rels.items():
            p = "word/" + target if not target.startswith("/") else target.lstrip("/")
            if p in names and target.startswith("media/"):
                media[target] = z.read(p)
    body = doc.find("w:body", NS)
    w = Writer(styles, rels, media, labels)
    return PAGE % (html.escape(title or "Document"), w.blocks(body) if body is not None else "")


def fragment_to_html(xml, style_names=()):
    """Copied paragraphs (the clipboard fragment) as HTML."""
    try:
        root = ET.fromstring("<root %s>%s</root>" % (NS_DECL, xml))
    except ET.ParseError:
        return None
    w = Writer(Styles(names=style_names))
    return "<html><body>\n%s\n</body></html>" % w.blocks(root)


# ================================================================ RTF
def _rtf_text(s):
    out = []
    for ch in s:
        o = ord(ch)
        if ch in "\\{}":
            out.append("\\" + ch)
        elif o > 127:
            out.append("\\u%d?" % (o if o < 32768 else o - 65536))
        else:
            out.append(ch)
    return "".join(out)


class RtfWriter:
    def __init__(self, styles):
        self.styles = styles
        self.fonts = ["Calibri"]
        self.colors = []

    def font(self, name):
        if name not in self.fonts:
            self.fonts.append(name)
        return self.fonts.index(name)

    def color(self, hexv):
        hexv = hexv.lstrip("#").upper()
        if hexv not in self.colors:
            self.colors.append(hexv)
        return self.colors.index(hexv) + 1

    def blocks(self, parent, in_cell=False):
        out = []
        for el in parent:
            if el.tag == q("w:p"):
                out.append(self.para(el, in_cell))
            elif el.tag == q("w:tbl"):
                out.append(self.table(el))
            elif el.tag == q("w:sdt"):
                c = el.find("w:sdtContent", NS)
                if c is not None:
                    out.append(self.blocks(c, in_cell))
        return "".join(out)

    def para(self, p, in_cell=False):
        ppr = p.find("w:pPr", NS)
        sid = _val(ppr, "w:pStyle") or "Normal"
        chain = self.styles.chain(sid)
        inherited = [c[3] for c in reversed(chain)]
        lvl = self.styles.heading(sid)
        head = "\\pard\\plain" + ("\\intbl" if in_cell else "")
        if lvl:
            head += "\\outlinelevel%d" % (lvl - 1)
        jc = _val(ppr, "w:jc")
        head += {"center": "\\qc", "right": "\\qr", "end": "\\qr", "both": "\\qj"}.get(jc, "\\ql")
        ind = ppr.find("w:ind", NS) if ppr is not None else None
        if ind is not None:
            for attr, kw in (("w:left", "li"), ("w:start", "li"), ("w:right", "ri"), ("w:firstLine", "fi")):
                v = ind.get(q(attr))
                if v and v.lstrip("-").isdigit():
                    head += "\\%s%s" % (kw, v)
            h = ind.get(q("w:hanging"))
            if h and h.isdigit():
                head += "\\fi-%s" % h
        head += "\\sa160\\sl259\\slmult1 "
        body = []
        for r in p.iter(q("w:r")):
            st = _run_props(r.find("w:rPr", NS), inherited)
            if lvl and "sz" not in st:
                st["sz"] = {1: 16, 2: 13, 3: 12}.get(lvl, 11)
            if st.get("hidden"):
                continue
            txt = []
            for c in r:
                if c.tag == q("w:t"):
                    txt.append(_rtf_text(c.text or ""))
                elif c.tag == q("w:tab"):
                    txt.append("\\tab ")
                elif c.tag == q("w:br"):
                    txt.append("\\page " if c.get(q("w:type")) == "page" else "\\line ")
            if not txt:
                continue
            fmt = "\\f%d\\fs%d" % (self.font(st.get("font") or "Calibri"), int(round((st.get("sz") or 11) * 2)))
            if st.get("b"):
                fmt += "\\b"
            if st.get("i"):
                fmt += "\\i"
            if st.get("u"):
                fmt += "\\ul"
            if st.get("s"):
                fmt += "\\strike"
            if st.get("va") == "superscript":
                fmt += "\\super"
            elif st.get("va") == "subscript":
                fmt += "\\sub"
            if st.get("color"):
                fmt += "\\cf%d" % self.color(st["color"])
            if st.get("caps"):
                fmt += "\\caps"
            body.append("{%s %s}" % (fmt, "".join(txt)))
        return head + "".join(body) + ("\\cell " if in_cell else "\\par\n")

    def table(self, t):
        out = []
        for tr in t.findall("w:tr", NS):
            cells = tr.findall("w:tc", NS)
            row = "\\trowd\\trgaph108"
            x = 0
            for tc in cells:
                tcpr = tc.find("w:tcPr", NS)
                tw = tcpr.find("w:tcW", NS) if tcpr is not None else None
                wv = tw.get(q("w:w")) if tw is not None else None
                x += int(wv) if wv and wv.isdigit() and tw.get(q("w:type"), "dxa") == "dxa" else 2160
                row += "\\clbrdrt\\brdrs\\clbrdrl\\brdrs\\clbrdrb\\brdrs\\clbrdrr\\brdrs\\cellx%d" % x
            out.append(row + "\n")
            for tc in cells:
                paras = tc.findall("w:p", NS)
                for i, p in enumerate(paras):
                    s = self.para(p, True)
                    if i < len(paras) - 1:
                        s = s[:-len("\\cell ")] + "\\par "
                    out.append(s)
            out.append("\\row\n")
        return "".join(out)

    def document(self, body):
        content = self.blocks(body)
        fonts = "".join("{\\f%d\\fnil %s;}" % (i, _rtf_text(f)) for i, f in enumerate(self.fonts))
        colors = ";" + "".join("\\red%d\\green%d\\blue%d;" % (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16))
                               for c in self.colors)
        return ("{\\rtf1\\ansi\\ansicpg1252\\deff0\\uc1{\\fonttbl%s}{\\colortbl%s}\n"
                "{\\*\\generator Folio Writer;}\\viewkind4\n%s}" % (fonts, colors, content))


def docx_to_rtf(docx):
    with zipfile.ZipFile(docx) as z:
        names = set(z.namelist())
        doc = ET.fromstring(z.read("word/document.xml"))
        styles = Styles(z.read("word/styles.xml") if "word/styles.xml" in names else None)
    body = doc.find("w:body", NS)
    return RtfWriter(styles).document(body if body is not None else [])


def fragment_to_rtf(xml, style_names=()):
    try:
        root = ET.fromstring("<root %s>%s</root>" % (NS_DECL, xml))
    except ET.ParseError:
        return None
    return RtfWriter(Styles(names=style_names)).document(root)
