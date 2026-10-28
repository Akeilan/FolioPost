"""Drop caps in .docx files.

The engine keeps a drop cap as a property of the paragraph but writes it to
.docx as plain text. The original stores it as a small framed paragraph
holding the letter(s), just before the paragraph. After a .docx is written
it is patched here into that form, which reads back as a drop cap here and
in the original."""
import os
import re
import shutil
import tempfile
import zipfile

DOCX = ("docx", "docm", "dotx", "dotm")
TAG = re.compile(r"<(/?)w:(p|tbl)(?=[\s>/])[^>]*?(/?)>")
T_RE = re.compile(r"<w:t(?:\s[^>]*)?>([^<]*)</w:t>")
RPR_AFTER = ("highlight", "u", "effect", "bdr", "shd", "fitText", "vertAlign", "rtl",
             "cs", "em", "lang", "eastAsianLayout", "specVanish", "oMath")


def collect(m):
    """[(index of top-level paragraph, text, letters, lines, distance twips,
    char height pt, line height pt)] for paragraphs with a drop cap."""
    out = []
    en = m.getText().createEnumeration()
    i = 0
    while en.hasMoreElements():
        p = en.nextElement()
        if not p.supportsService("com.sun.star.text.Paragraph"):
            continue
        try:
            fmt = p.DropCapFormat
            if fmt.Lines > 1:
                text = p.getString()
                if p.DropCapWholeWord:
                    n = len(re.match(r"\S*", text).group(0)) or 1
                else:
                    n = max(1, fmt.Count)
                c = p.getText().createTextCursorByRange(p.getStart())
                c.goRight(1, True)
                h = c.CharHeight or 11.0
                ls = p.ParaLineSpacing
                if ls.Mode == 0:
                    line = h * 1.22 * ls.Height / 100.0
                elif ls.Mode in (1, 3):
                    line = max(h * 1.22 if ls.Mode == 1 else 0, ls.Height * 72 / 2540.0)
                else:
                    line = h * 1.22 + ls.Height * 72 / 2540.0
                font = None
                try:
                    if p.DropCapCharStyleName:
                        font = m.getStyleFamilies().getByName("CharacterStyles").getByName(
                            p.DropCapCharStyleName).CharFontName
                except Exception:
                    font = None
                out.append((i, text, text[:n], fmt.Lines,
                            int(round(fmt.Distance * 1440 / 2540.0)), h, line, font))
        except Exception as e:
            print("drop cap:", e)
        i += 1
    return out


def _top_paragraphs(xml):
    """[(start, end)] of the body's top-level paragraphs (not in tables or
    text boxes), in order."""
    out = []
    pdepth = tdepth = 0
    start = None
    for mt in TAG.finditer(xml):
        closing, name, selfclose = mt.group(1), mt.group(2), mt.group(3)
        if name == "tbl":
            if selfclose:
                continue
            tdepth += -1 if closing else 1
            continue
        if selfclose:
            if pdepth == 0 and tdepth == 0:
                out.append((mt.start(), mt.end()))
            continue
        if closing:
            pdepth -= 1
            if pdepth == 0 and tdepth == 0 and start is not None:
                out.append((start, mt.end()))
                start = None
        else:
            if pdepth == 0 and tdepth == 0:
                start = mt.start()
            pdepth += 1
    return out


def _plain(pxml):
    return "".join(T_RE.findall(pxml))


def _rpr_for(pxml, pos):
    """The run properties of the run containing position pos."""
    r0 = pxml.rfind("<w:r>", 0, pos)
    r1 = pxml.rfind("<w:r ", 0, pos)
    r = max(r0, r1)
    if r < 0:
        return ""
    mt = re.compile(r"<w:rPr>(.*?)</w:rPr>|<w:rPr/>", re.S).match(pxml, pxml.index(">", r) + 1)
    if mt is None:
        return ""
    return mt.group(1) or ""


def _with_size(rpr, sz, pos):
    rpr = re.sub(r"<w:(sz|szCs|position)\s[^>]*/>", "", rpr)
    add = '<w:position w:val="%d"/><w:sz w:val="%d"/><w:szCs w:val="%d"/>' % (pos, sz, sz)
    for name in RPR_AFTER:
        mt = re.search(r"<w:%s[\s/>]" % name, rpr)
        if mt:
            return rpr[:mt.start()] + add + rpr[mt.start():]
    return rpr + add


def _take(pxml, n):
    """Remove the first n characters of text from the paragraph; returns
    (new xml, removed text, offset of the first removed character)."""
    out, taken, first = pxml, "", None
    pos = out.find("</w:pPr>")
    pos = 0 if pos < 0 else pos
    while len(taken) < n:
        mt = T_RE.search(out, pos)
        if mt is None:
            break
        txt = mt.group(1)
        if not txt:
            pos = mt.end()
            continue
        if first is None:
            first = mt.start()
        k = n - len(taken)
        taken += txt[:k]
        rest = txt[k:]
        open_tag = out[mt.start():mt.start(1)]
        if rest and "xml:space" not in open_tag:
            open_tag = '<w:t xml:space="preserve">'
        out = out[:mt.start()] + open_tag + rest + "</w:t>" + out[mt.end():]
        pos = mt.start() + len(open_tag) + len(rest) + 6
    return out, taken, first if first is not None else 0


def _frame_para(pxml, letters, lines, hspace, height, line):
    style = re.search(r"<w:pStyle\s[^>]*/>", pxml)
    exact = int(round(lines * line * 20))
    sz = int(round(exact / 20.0 * 1.34 * 2))
    pos = -int(round(sz * 0.08))
    return exact, sz, pos, style.group(0) if style else ""


def patch(path, items):
    if not items:
        return 0
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    paras = _top_paragraphs(xml)
    used = set()
    edits = []
    for idx, text, letters, lines, hspace, height, line, font in items:
        cand = None
        want = text.replace("\t", "").replace("\n", "")[:60]
        order = ([idx] if idx < len(paras) else []) + list(range(len(paras)))
        for k in order:
            if k in used:
                continue
            s, e = paras[k]
            if _plain(xml[s:e]).replace("\t", "")[:60] == want[:60] and want:
                cand = k
                break
        if cand is None:
            continue
        used.add(cand)
        s, e = paras[cand]
        pxml = xml[s:e]
        body, taken, at = _take(pxml, len(letters))
        if not taken:
            continue
        rpr = _rpr_for(pxml, at)
        exact, sz, pos, style = _frame_para(pxml, letters, lines, hspace, height, line)
        if font:
            rpr = re.sub(r"<w:rFonts\s[^>]*/>", "", rpr)
            f = font.replace("&", "&amp;").replace('"', "&quot;")
            rpr = '<w:rFonts w:ascii="%s" w:hAnsi="%s" w:cs="%s"/>' % (f, f, f) + \
                re.sub(r"^(<w:rStyle\s[^>]*/>)", "", rpr)
        rp = _with_size(rpr, sz, pos)
        frame = ('<w:p><w:pPr>%s<w:keepNext/><w:framePr w:dropCap="drop" w:lines="%d"%s '
                 'w:wrap="around" w:vAnchor="text" w:hAnchor="text"/>'
                 '<w:spacing w:before="0" w:after="0" w:line="%d" w:lineRule="exact"/>'
                 '<w:textAlignment w:val="baseline"/><w:rPr>%s</w:rPr></w:pPr>'
                 '<w:r><w:rPr>%s</w:rPr><w:t xml:space="preserve">%s</w:t></w:r></w:p>') % (
            style, lines, (' w:hSpace="%d"' % hspace) if hspace else "", exact, rp, rp,
            taken.replace("&", "&amp;").replace("<", "&lt;"))
        edits.append((s, e, frame + body))
    if not edits:
        return 0
    for s, e, new in sorted(edits, reverse=True):
        xml = xml[:s] + new + xml[e:]
    fd, tmp = tempfile.mkstemp(suffix=".docx", dir=os.path.dirname(os.path.abspath(path)))
    os.close(fd)
    try:
        with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
            for info in zin.infolist():
                data = xml.encode("utf-8") if info.filename == "word/document.xml" \
                    else zin.read(info.filename)
                zout.writestr(info, data)
        st = os.stat(path)
        shutil.move(tmp, path)
        try:
            os.chmod(path, st.st_mode & 0o7777)
        except OSError:
            pass
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return len(edits)


def install(win):
    """Patch every .docx the window writes."""
    def fix(path, fmt):
        if (fmt or "").lower() not in DOCX:
            return
        m = win.engine.model
        if m is None:
            return
        items = collect(m)
        if items:
            patch(path, items)
    win.engine.written_hooks = tuple(win.engine.written_hooks) + (fix,)
