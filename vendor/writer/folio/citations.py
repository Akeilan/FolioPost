"""Citations & Bibliography: sources, in-text citations in APA / MLA / Chicago /
IEEE style, and a bibliography that formats itself in the same style.

Citations are the engine's bibliography fields; the source's tag is kept in
the field's Custom1 entry so a citation can be re-rendered when the style or
the source changes. Sources that aren't cited yet live in a document property
and in the user's master list (~/.config/folio-writer/sources.json)."""
import json
import os
import re

from ._lazy import bridge, docapi

STYLES = ["APA", "Chicago", "Harvard", "IEEE", "ISO 690", "MLA", "Turabian"]
STYLE_NAMES = {s: s for s in STYLES}
# in-text behaviour follows a related style
BASE = {"Harvard": "APA", "Turabian": "Chicago", "ISO 690": "Chicago"}

# Word-style source types -> engine bibliography type
TYPES = [("Book", 1), ("Book Section", 4), ("Journal Article", 0),
         ("Article in a Periodical", 0), ("Conference Proceedings", 6), ("Report", 13),
         ("Web site", 16), ("Document From Web site", 16), ("Miscellaneous", 10)]
TYPE_CODE = dict(TYPES)

# which entry boxes each type shows: (key, label)
FIELDS = {
    "Book": [("author", "Author"), ("title", "Title"), ("year", "Year"), ("city", "City"),
             ("publisher", "Publisher")],
    "Book Section": [("author", "Author"), ("title", "Title"), ("booktitle", "Book Title"),
                     ("editor", "Editor"), ("year", "Year"), ("pages", "Pages"),
                     ("city", "City"), ("publisher", "Publisher")],
    "Journal Article": [("author", "Author"), ("title", "Title"), ("journal", "Journal Name"),
                        ("year", "Year"), ("volume", "Volume"), ("issue", "Issue"),
                        ("pages", "Pages")],
    "Article in a Periodical": [("author", "Author"), ("title", "Title"),
                                ("journal", "Periodical Title"), ("year", "Year"),
                                ("month", "Month"), ("pages", "Pages")],
    "Conference Proceedings": [("author", "Author"), ("title", "Title"),
                               ("booktitle", "Conference Name"), ("year", "Year"),
                               ("pages", "Pages"), ("city", "City"),
                               ("publisher", "Publisher")],
    "Report": [("author", "Author"), ("title", "Title"), ("year", "Year"),
               ("publisher", "Publisher"), ("city", "City")],
    "Web site": [("author", "Author"), ("title", "Name of Web Page"),
                 ("journal", "Name of Web Site"), ("year", "Year"), ("url", "URL")],
    "Document From Web site": [("author", "Author"), ("title", "Name of Web Page"),
                               ("journal", "Name of Web Site"), ("year", "Year"),
                               ("url", "URL")],
    "Miscellaneous": [("author", "Author"), ("title", "Title"), ("year", "Year"),
                      ("publisher", "Publisher"), ("city", "City")],
}

# engine data fields
F = {"identifier": 0, "type": 1, "city": 2, "author": 4, "booktitle": 5, "editor": 8,
     "journal": 11, "month": 12, "note": 13, "issue": 14, "pages": 16, "publisher": 17,
     "title": 20, "volume": 22, "year": 23, "url": 24, "tag": 25}
ENGINE_NAMES = {"identifier": "Identifier", "type": "BibiliographicType", "city": "Address",
                "author": "Author", "booktitle": "Booktitle", "editor": "Editor",
                "journal": "Journal", "month": "Month", "note": "Note", "issue": "Number",
                "pages": "Pages", "publisher": "Publisher", "title": "Title",
                "volume": "Volume", "year": "Year", "url": "URL", "tag": "Custom1"}

MASTER = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
                      "folio-writer", "sources.json")


# ------------------------------------------------------------------ authors
def authors(src):
    """'Smith, John; Jones, Ann' -> [('Smith', 'John'), ('Jones', 'Ann')]"""
    out = []
    for a in re.split(r"\s*;\s*|\s+and\s+", (src.get("author") or "").strip()):
        if not a:
            continue
        if "," in a:
            last, first = [x.strip() for x in a.split(",", 1)]
        else:
            parts = a.split()
            last, first = parts[-1], " ".join(parts[:-1])
        out.append((last, first))
    return out


def _initials(first):
    return " ".join(p[0] + "." for p in first.replace("-", " ").split() if p)


def author_list(src, style):
    a = authors(src)
    if not a:
        return src.get("title", "")
    if style == "Harvard":
        names = ["%s, %s" % (l, _initials(f)) if f else l for l, f in a]
        return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    if style == "ISO 690":
        names = ["%s, %s" % (l.upper(), f) if f else l.upper() for l, f in a]
        return " and ".join(names) if len(names) <= 2 else "; ".join(names)
    style = BASE.get(style, style)
    if style == "APA":
        names = ["%s, %s" % (l, _initials(f)) if f else l for l, f in a]
        if len(names) == 1:
            return names[0]
        return ", ".join(names[:-1]) + ", & " + names[-1]
    if style == "MLA":
        l, f = a[0]
        first = "%s, %s" % (l, f) if f else l
        if len(a) == 1:
            return first
        if len(a) == 2:
            l2, f2 = a[1]
            return "%s, and %s" % (first, ("%s %s" % (f2, l2)).strip())
        return first + ", et al."
    if style == "IEEE":
        names = [("%s %s" % (_initials(f), l)).strip() for l, f in a]
        if len(names) == 1:
            return names[0]
        return ", ".join(names[:-1]) + " and " + names[-1]
    # Chicago
    l, f = a[0]
    names = ["%s, %s" % (l, f) if f else l] + [("%s %s" % (f2, l2)).strip() for l2, f2 in a[1:]]
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + ", and " + names[-1]


def citation_text(src, style):
    """What appears in the text, without the brackets."""
    orig = style
    style = BASE.get(style, style)
    a = authors(src)
    year = src.get("year") or "n.d."
    if a:
        if len(a) == 1:
            who = a[0][0]
        elif len(a) == 2:
            who = "%s %s %s" % (a[0][0], "&" if orig == "APA" else "and", a[1][0])
        else:
            who = a[0][0] + " et al."
    else:
        who = src.get("title", "Untitled")
    if style == "APA":
        return "%s, %s" % (who, year)
    if style == "MLA":
        return who
    if style == "Chicago":
        return "%s %s" % (who, year)
    return src.get("tag", who)


_PAGES = re.compile(r",\s*pp?\.\s*([\d][\d\-\u2013,\s]*)$")


def cite_label(src, style, base, opts):
    """The in-text label for one citation: the source's label (base), with
    the citation's own page numbers and suppressed parts."""
    opts = opts or {}
    style = BASE.get(style, style)
    sup = set(opts.get("suppress") or ())
    pages = (opts.get("pages") or "").strip()
    if style == "IEEE":
        lab = base
        return lab + (", p. %s" % pages if pages else "")
    a = authors(src)
    who = base
    year = src.get("year") or "n.d."
    if style in ("APA", "Chicago"):
        # base is "Who, Year" (APA) or "Who Year" (Chicago), maybe with a/b suffix
        sep = ", " if style == "APA" else " "
        if sep in base:
            who, year = base.rsplit(sep, 1)
        parts = []
        if "author" not in sup:
            parts.append(who)
        if "year" not in sup:
            parts.append(year)
        if not parts and "title" not in sup:
            parts.append(src.get("title", ""))
        lab = sep.join(p for p in parts if p)
        if pages:
            lab += (", p. %s" if style == "APA" else ", %s") % pages
        return lab
    # MLA: (Author page)
    lab = "" if "author" in sup else who
    if pages:
        lab = (lab + " " + pages).strip()
    return lab or (src.get("title", "") if "title" not in sup else "")


def make_tag(src, existing=()):
    a = authors(src)
    base = (a[0][0] if a else (src.get("title") or "Src"))[:3]
    base = re.sub(r"\W", "", base) or "Src"
    tag = base + (src.get("year") or "")[-2:]
    out, n = tag, 1
    while out in existing:
        n += 1
        out = "%s%d" % (tag, n)
    return out


# ------------------------------------------------------------------ entry formatting
def entry_parts(src, style):
    """The bibliography entry as [(text, italic)] (also used for the preview)."""
    t = src.get("type", "Book")
    A = author_list(src, style)
    y = src.get("year") or "n.d."
    title = src.get("title", "")
    pub = src.get("publisher", "")
    city = src.get("city", "")
    j = src.get("journal", "")
    vol, iss, pages = src.get("volume", ""), src.get("issue", ""), src.get("pages", "")
    url = src.get("url", "")
    book = src.get("booktitle", "")
    ed = src.get("editor", "")
    out = []

    def add(text, italic=False):
        if text:
            out.append((text, italic))
    article = t in ("Journal Article", "Article in a Periodical")
    web = t in ("Web site", "Document From Web site")
    if style == "Turabian":
        style = "Chicago"
    if style in ("Harvard", "ISO 690"):
        harvard = style == "Harvard"
        add(("%s (%s) " if harvard else "%s. %s. ") % (A, y))
        if article:
            add(title + ". " if harvard else title + ". ")
            add(j, True)
            add("%s%s%s." % (", " + vol if vol else "", "(%s)" % iss if iss else "",
                             (", pp. " if harvard else ", ") + pages if pages else ""))
        elif web:
            add(title, True)
            add(". [Online]. " if not harvard else ". ")
            add(("Available at: %s" if harvard else "Available from: %s") % url if url else "")
        elif t in ("Book Section", "Conference Proceedings"):
            add(title + ". In: ")
            add(book, True)
            add(". %s%s." % (city + ": " if city else "", pub))
        else:
            add(title, True)
            add(". %s%s." % (city + ": " if city else "", pub) if (pub or city) else ".")
        if out:
            t0, it = out[-1]
            out[-1] = (t0.rstrip(), it)
        return out
    if style == "APA":
        add("%s (%s). " % (A, y))
        if article:
            add(title + ". ")
            add(j, True)
            if vol:
                add(", ")
                add(vol, True)
            if iss:
                add("(%s)" % iss)
            if pages:
                add(", " + pages)
            add(".")
        elif t == "Book Section" or t == "Conference Proceedings":
            add(title + ". ")
            add("In %s%s, " % (ed, " (Ed.)" if ed else "") if ed else "In ")
            add(book, True)
            if pages:
                add(" (pp. %s)" % pages)
            add(". " + pub + "." if pub else ".")
        elif web:
            add(title, True)
            add(". ")
            if j:
                add(j + ". ")
            add(url)
        else:
            add(title, True)
            add(". ")
            add(pub + "." if pub else "")
    elif style == "MLA":
        add(A + ". ")
        if article:
            add("“%s.” " % title)
            add(j, True)
            bits = [b for b in ("vol. " + vol if vol else "", "no. " + iss if iss else "",
                                y, "pp. " + pages if pages else "") if b]
            add(", " + ", ".join(bits) + "." if bits else ".")
        elif web:
            add("“%s.” " % title)
            add(j, True)
            add(", %s, %s." % (y, url) if url else ", %s." % y)
        elif t in ("Book Section", "Conference Proceedings"):
            add("“%s.” " % title)
            add(book, True)
            add(", %s%s, %s%s." % ("edited by %s, " % ed if ed else "", pub, y,
                                    ", pp. " + pages if pages else ""))
        else:
            add(title, True)
            add(". %s, %s." % (pub, y) if pub else ". %s." % y)
    elif style == "Chicago":
        add("%s. %s. " % (A, y))
        if article:
            add("“%s.” " % title)
            add(j, True)
            add(" %s%s%s." % (vol, " (%s)" % iss if iss else "", ": " + pages if pages else ""))
        elif web:
            add("“%s.” " % title)
            add(j + ". " if j else "")
            add(url + "." if url else "")
        else:
            add(title, True)
            add(". %s%s." % (city + ": " if city else "", pub) if (pub or city) else ".")
    else:  # IEEE
        add("%s, " % A)
        if article:
            add("“%s,” " % title)
            add(j, True)
            bits = [b for b in ("vol. " + vol if vol else "", "no. " + iss if iss else "",
                                "pp. " + pages if pages else "", y) if b]
            add(", " + ", ".join(bits) + ".")
        elif web:
            add("“%s.” " % title)
            add(j + ". " if j else "")
            add("[Online]. Available: " + url if url else "")
        else:
            add(title, True)
            where = (city + ": " if city and pub else city) + pub
            add(". " + ", ".join(b for b in (where, y) if b) + ".")
    if out:
        t, it = out[-1]
        out[-1] = (t.rstrip(), it)
    return out


def entry_text(src, style):
    return "".join(t for t, _i in entry_parts(src, style))


# ------------------------------------------------------------------ storage
def _load_master():
    try:
        with open(MASTER, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def master_sources():
    return _load_master()


def save_master(sources):
    os.makedirs(os.path.dirname(MASTER), exist_ok=True)
    tmp = MASTER + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(sources, f, indent=1, ensure_ascii=False)
    os.replace(tmp, MASTER)


def add_to_master(src):
    ms = [s for s in _load_master() if s.get("tag") != src.get("tag")]
    ms.append(src)
    save_master(ms)


def _fields_data(f):
    return {p.Name: p.Value for p in f.Fields}


def _bib_fields(m):
    out = []
    en = m.getTextFields().createEnumeration()
    while en.hasMoreElements():
        f = en.nextElement()
        try:
            if f.supportsService("com.sun.star.text.textfield.Bibliography"):
                out.append(f)
        except Exception:
            pass
    return out


def _from_field(f):
    d = _fields_data(f)
    src = {}
    for key, name in ENGINE_NAMES.items():
        if key in ("identifier", "type"):
            continue
        v = d.get(name)
        if v:
            src[key] = v
    src["type"] = d.get("Note") if d.get("Note") in FIELDS else _type_name(d.get(
        "BibiliographicType"))
    src["tag"] = d.get("Custom1") or d.get("Identifier")
    if d.get("Custom2"):
        src["author"] = d["Custom2"]
    src.pop("note", None)
    return src


def _type_name(code):
    try:
        code = int(code)
    except (TypeError, ValueError):
        return "Book"
    for n, c in TYPES:
        if c == code:
            return n
    return "Miscellaneous"


_CITE = re.compile(r'^\s*CITATION\s+"?([^"\\]+?)"?(\s+\\.*)?$')


def _stored(m):
    try:
        return json.loads(docapi._doc_setting(m, "Sources", "") or "[]")
    except ValueError:
        return []


def _resolve_tag(m, d, stored):
    """The source tag of a citation field. Files saved as .docx come back with
    the field code (CITATION "label") as the identifier; map it back."""
    tag = d.get("Custom1")
    if tag:
        return tag
    ident = d.get("Identifier") or ""
    mm = _CITE.match(ident)
    label = mm.group(1).strip() if mm else ident
    tags = {s.get("tag") for s in stored}
    if label in tags:
        return label
    candidates = [label]
    pm = _PAGES.search(label)
    if pm:
        candidates.append(label[:pm.start()].strip())
    for cand in candidates:
        for style in STYLES:
            for s in stored:
                if citation_text(s, style) == cand or s.get("title") == cand:
                    return s.get("tag")
    return label


def _opts_of(d):
    try:
        return json.loads(d.get("Custom3") or "{}")
    except ValueError:
        return {}


def doc_sources(m):
    """Sources of this document: the cited ones and the stored list."""
    by_tag = {}
    stored = _stored(m)
    for s in stored:
        by_tag[s.get("tag")] = s
    for f in _bib_fields(m):
        d = _fields_data(f)
        tag = _resolve_tag(m, d, stored)
        if tag in by_tag:
            continue
        s = _from_field(f)
        s["tag"] = tag
        by_tag[tag] = s
    return [s for t, s in by_tag.items() if t]


def save_doc_sources(m, sources):
    docapi._set_doc_setting(m, "Sources", json.dumps(sources, ensure_ascii=False))


def add_source(m, src, master=True):
    tags = {s.get("tag") for s in doc_sources(m)}
    if not src.get("tag") or src["tag"] in tags and not src.get("_editing"):
        src["tag"] = make_tag(src, tags)
    src.pop("_editing", None)
    sources = [s for s in doc_sources(m) if s.get("tag") != src["tag"]] + [src]
    save_doc_sources(m, sources)
    if master:
        add_to_master(src)
    refresh(m)
    return src


def delete_source(m, tag):
    save_doc_sources(m, [s for s in doc_sources(m) if s.get("tag") != tag])


def is_cited(m, tag):
    stored = _stored(m)
    return any(_resolve_tag(m, _fields_data(f), stored) == tag for f in _bib_fields(m))


def has_citations(m):
    return bool(_bib_fields(m))


# ------------------------------------------------------------------ style
def current_style(m):
    v = docapi._doc_setting(m, "CitationStyle", "APA")
    return v if v in STYLES else "APA"


def _identifiers(m, sources, style):
    """Unique in-text labels; same author and year get 2020a, 2020b (APA)."""
    labels = {}
    seen = {}
    for s in sources:
        lab = citation_text(s, style)
        seen.setdefault(lab, []).append(s["tag"])
    for lab, tags in seen.items():
        if len(tags) == 1 or BASE.get(style, style) in ("MLA", "IEEE"):
            for t in tags:
                labels[t] = lab if style != "IEEE" else t
        else:
            for i, t in enumerate(tags):
                labels[t] = lab + "abcdefghijklmnopqrstuvwxyz"[i % 26]
    return labels


def _master_field(m):
    fm = m.getTextFieldMasters()
    name = "com.sun.star.text.fieldmaster.Bibliography"
    return fm.getByName(name) if fm.hasByName(name) else None


def _field_values(src, ident, style="APA", opts=None):
    vals = [bridge.prop("Identifier", ident),
            bridge.prop("Custom3", json.dumps(opts) if opts else ""),
            bridge.prop("BibiliographicType", TYPE_CODE.get(src.get("type"), 1)),
            bridge.prop("Note", src.get("type", "Book")),
            bridge.prop("Custom1", src["tag"]),
            bridge.prop("Custom2", src.get("author", "")),
            bridge.prop("Author", author_list(src, style) if src.get("author") else "")]
    for key, name in ENGINE_NAMES.items():
        if key in ("identifier", "type", "tag", "note", "author"):
            continue
        if src.get(key):
            vals.append(bridge.prop(name, src[key]))
    return tuple(vals)


def refresh(m):
    """Re-render every citation and the bibliography in the current style."""
    style = current_style(m)
    sources = {s["tag"]: s for s in doc_sources(m)}
    labels = _identifiers(m, list(sources.values()), style)
    if style == "IEEE":
        labels = _numbers_in_order(m)
    stored = _stored(m)
    ordered = _fields_in_order(m)
    try:
        record = json.loads(docapi._doc_setting(m, "Citations", "") or "[]")
    except ValueError:
        record = []
    restore = bool(ordered) and all(not _fields_data(f).get("Custom1") for f in ordered) \
        and len(record) == len(ordered)
    new_record = []
    for i, f in enumerate(ordered):
        d = _fields_data(f)
        if restore:
            # reopened from .docx: the engine's own field data is lost there,
            # so take tag and options from the record kept with the document
            tag, opts = record[i].get("tag"), record[i].get("opts") or {}
        else:
            tag, opts = _resolve_tag(m, d, stored), _opts_of(d)
        new_record.append({"tag": tag, "opts": opts})
        src = sources.get(tag)
        if src is None:
            continue
        base = labels.get(tag, tag)
        f.Fields = _field_values(src, cite_label(src, style, base, opts), style, opts)
    if new_record != record:
        docapi._set_doc_setting(m, "Citations", json.dumps(new_record))
    for sec in own_bibliographies(m):
        _write_bibliography(m, sec, style, sources, labels)
    ma = _master_field(m)
    if ma is not None:
        ma.BracketBefore = "[" if style == "IEEE" else "("
        ma.BracketAfter = "]" if style == "IEEE" else ")"
        ma.IsNumberEntries = False
        ma.IsSortByPosition = style == "IEEE"
        if style != "IEEE":
            ma.SortKeys = ((bridge.prop("SortKey", F["author"]),
                            bridge.prop("IsSortAscending", True)),
                           (bridge.prop("SortKey", F["year"]),
                            bridge.prop("IsSortAscending", True)))
    for idx in bibliographies(m):
        _format_index(m, idx, style)
        try:
            idx.ParaStyleLevel1 = _entry_style(m)
        except Exception:
            pass
        idx.update()
    try:
        m.getTextFields().refresh()
    except Exception:
        pass


def _numbers_in_order(m):
    """IEEE: sources numbered in the order they are first cited."""
    body = m.getText()
    found = []
    stored = _stored(m)
    for f in _bib_fields(m):
        found.append((f.getAnchor(), _resolve_tag(m, _fields_data(f), stored)))

    import functools

    def cmp(a, b):
        try:
            r = body.compareRegionStarts(a[0], b[0])
            return -r
        except Exception:
            return 0
    found.sort(key=functools.cmp_to_key(cmp))
    labels = {}
    for _a, tag in found:
        if tag not in labels:
            labels[tag] = "%d" % (len(labels) + 1)
    n = len(labels)
    for s in doc_sources(m):
        if s["tag"] not in labels:
            n += 1
            labels[s["tag"]] = "%d" % n
    return labels


def set_style(m, style):
    docapi._set_doc_setting(m, "CitationStyle", style)
    refresh(m)


# ------------------------------------------------------------------ insert
def insert_citation(m, tag):
    sources = {s["tag"]: s for s in doc_sources(m)}
    src = sources.get(tag)
    if src is None:
        for s in master_sources():
            if s.get("tag") == tag:
                src = s
                add_source(m, dict(s), master=False)
                break
    if src is None:
        return None
    style = current_style(m)
    labels = _identifiers(m, list({**sources, tag: src}.values()), style)
    um = m.getUndoManager()
    um.enterUndoContext("Insert Citation")
    try:
        vc = docapi.view_cursor(m)
        f = m.createInstance("com.sun.star.text.textfield.Bibliography")
        f.Fields = _field_values(src, cite_label(src, style, labels.get(tag, tag), {}), style)
        vc.getText().insertTextContent(vc, f, False)
        refresh(m)
    finally:
        um.leaveUndoContext()
    return f


def bibliographies(m):
    out = []
    ix = m.getDocumentIndexes()
    for i in range(ix.getCount()):
        x = ix.getByIndex(i)
        if x.supportsService("com.sun.star.text.Bibliography"):
            out.append(x)
    return out


def _tok_field(field, italic=False):
    return (bridge.prop("TokenType", "TokenBibliographyDataField"),
            bridge.prop("CharacterStyleName", "Emphasis" if italic else ""),
            bridge.prop("BibliographyDataField", F[field]))


def _tok_text(text):
    return (bridge.prop("TokenType", "TokenText"), bridge.prop("CharacterStyleName", ""),
            bridge.prop("Text", text))


def _tokens(style, tname):
    """Index format tokens matching entry_parts() for one type."""
    T, D = _tok_text, _tok_field
    article = tname in ("Journal Article", "Article in a Periodical")
    web = tname in ("Web site", "Document From Web site")
    section = tname in ("Book Section", "Conference Proceedings")
    if style == "APA":
        head = [D("author"), T(" ("), D("year"), T("). ")]
        if article:
            return head + [D("title"), T(". "), D("journal", True), T(", "), D("volume", True),
                           T("("), D("issue"), T("), "), D("pages"), T(".")]
        if section:
            return head + [D("title"), T(". In "), D("editor"), T(" (Ed.), "),
                           D("booktitle", True), T(" (pp. "), D("pages"), T("). "),
                           D("publisher"), T(".")]
        if web:
            return head + [D("title", True), T(". "), D("journal"), T(". "), D("url")]
        return head + [D("title", True), T(". "), D("publisher"), T(".")]
    if style == "MLA":
        head = [D("author"), T(". ")]
        if article:
            return head + [T("“"), D("title"), T(".” "), D("journal", True),
                           T(", vol. "), D("volume"), T(", no. "), D("issue"), T(", "),
                           D("year"), T(", pp. "), D("pages"), T(".")]
        if web:
            return head + [T("“"), D("title"), T(".” "), D("journal", True), T(", "),
                           D("year"), T(", "), D("url"), T(".")]
        if section:
            return head + [T("“"), D("title"), T(".” "), D("booktitle", True),
                           T(", edited by "), D("editor"), T(", "), D("publisher"), T(", "),
                           D("year"), T(", pp. "), D("pages"), T(".")]
        return head + [D("title", True), T(". "), D("publisher"), T(", "), D("year"), T(".")]
    if style == "Chicago":
        head = [D("author"), T(". "), D("year"), T(". ")]
        if article:
            return head + [T("“"), D("title"), T(".” "), D("journal", True), T(" "),
                           D("volume"), T(" ("), D("issue"), T("): "), D("pages"), T(".")]
        if web:
            return head + [T("“"), D("title"), T(".” "), D("journal"), T(". "),
                           D("url"), T(".")]
        return head + [D("title", True), T(". "), D("city"), T(": "), D("publisher"), T(".")]
    head = [T("["), D("identifier"), T("]\t"), D("author"), T(", ")]
    if article:
        return head + [T("“"), D("title"), T(",” "), D("journal", True),
                       T(", vol. "), D("volume"), T(", no. "), D("issue"), T(", pp. "),
                       D("pages"), T(", "), D("year"), T(".")]
    if web:
        return head + [T("“"), D("title"), T(".” "), D("journal"),
                       T(". [Online]. Available: "), D("url")]
    return head + [D("title", True), T(". "), D("city"), T(": "), D("publisher"), T(", "),
                   D("year"), T(".")]


def _set_level(lf, i, tokens):
    import uno
    uno.invoke(lf, "replaceByIndex", (i, uno.Any("[][]com.sun.star.beans.PropertyValue",
                                                   tuple(tokens))))


def _format_index(m, idx, style):
    lf = idx.LevelFormat
    for tname, code in TYPES:
        try:
            _set_level(lf, code + 1, _tokens(style, tname))
        except Exception as e:
            print("bibliography format:", e)
    # every other engine type: the 'Book' layout
    for code in range(0, 22):
        if code not in TYPE_CODE.values():
            try:
                _set_level(lf, code + 1, _tokens(style, "Book"))
            except Exception:
                pass
    idx.LevelFormat = lf


def _entry_style(m):
    """Entries use a hanging indent of 0.5", like the original's Bibliography style."""
    ps = docapi.para_styles(m)
    name = "Bibliography 1"
    if not ps.hasByName(name):
        st = m.createInstance("com.sun.star.style.ParagraphStyle")
        ps.insertByName(name, st)
        st.ParentStyle = "Standard"
    b = ps.getByName(name)
    b.ParaLeftMargin = 1270
    b.ParaFirstLineIndent = -1270
    return name


SECTION = "FolioBibliography"


def own_bibliographies(m):
    out = []
    secs = m.getTextSections()
    for n in secs.getElementNames():
        if n.startswith(SECTION):
            out.append(secs.getByName(n))
    return out


def _fields_in_order(m):
    body = m.getText()
    fs = [f for f in _bib_fields(m)]
    import functools

    def cmp(a, b):
        try:
            return -body.compareRegionStarts(a.getAnchor(), b.getAnchor())
        except Exception:
            return 0
    fs.sort(key=functools.cmp_to_key(cmp))
    return fs


def _cited_tags_in_order(m):
    body = m.getText()
    stored = _stored(m)
    found = []
    for f in _bib_fields(m):
        found.append((f.getAnchor(), _resolve_tag(m, _fields_data(f), stored)))
    import functools

    def cmp(a, b):
        try:
            return -body.compareRegionStarts(a[0], b[0])
        except Exception:
            return 0
    found.sort(key=functools.cmp_to_key(cmp))
    out = []
    for _a, t in found:
        if t not in out:
            out.append(t)
    return out


def _sort_key(src):
    a = authors(src)
    return ((a[0][0] if a else src.get("title", "")).lower(), src.get("year", ""),
            src.get("title", "").lower())


def _write_bibliography(m, sec, style, sources, labels):
    """(Re)write the entries of an app-made bibliography: cited sources only,
    sorted as the style requires, empty fields left out."""
    title = docapi._doc_setting(m, "BibTitle:" + sec.getName(), "")
    cited = _cited_tags_in_order(m)
    srcs = [sources[t] for t in cited if t in sources]
    if style == "IEEE":
        nums = _numbers_in_order(m)
        srcs.sort(key=lambda s: int(nums.get(s["tag"], "999")))
    else:
        srcs.sort(key=_sort_key)
    anchor = sec.getAnchor()
    text = anchor.getText()
    cur = text.createTextCursorByRange(anchor)
    cur.setString("")
    entry = _entry_style(m)
    first = True

    def para(style_name):
        nonlocal first
        if not first:
            text.insertControlCharacter(cur, 0, False)
        first = False
        cur.ParaStyleName = style_name
        cur.CharPosture = bridge.enum("com.sun.star.awt.FontSlant", "NONE")

    if title:
        para("Heading 1")
        text.insertString(cur, title, False)
    if not srcs:
        para(entry)
        text.insertString(cur, "There are no sources in the current document.", False)
    for src in srcs:
        para(entry)
        if style == "IEEE":
            text.insertString(cur, "[%s]\t" % labels.get(src["tag"], ""), False)
        for t, italic in entry_parts(src, style):
            cur.CharPosture = bridge.enum("com.sun.star.awt.FontSlant",
                                          "ITALIC" if italic else "NONE")
            text.insertString(cur, t, False)
        cur.CharPosture = bridge.enum("com.sun.star.awt.FontSlant", "NONE")


def insert_bibliography(m, title="Bibliography"):
    """A bibliography the app writes itself (in a section), so entries skip
    empty fields cleanly and citations can carry page numbers."""
    style = current_style(m)
    um = m.getUndoManager()
    um.enterUndoContext("Insert Bibliography")
    try:
        vc = docapi.view_cursor(m)
        secs = m.getTextSections()
        i = 1
        while secs.hasByName("%s%d" % (SECTION, i)):
            i += 1
        name = "%s%d" % (SECTION, i)
        sec = m.createInstance("com.sun.star.text.TextSection")
        sec.setName(name)
        text = vc.getText()
        text.insertTextContent(vc, sec, False)
        docapi._set_doc_setting(m, "BibTitle:" + name, title or "")
        refresh(m)
        return sec
    finally:
        um.leaveUndoContext()


def citation_at_cursor(m):
    """The citation field at (or just before) the cursor, or None."""
    vc = docapi.read_cursor(m)
    text = vc.getText()
    for f in _bib_fields(m):
        a = f.getAnchor()
        try:
            if a.getText() != text:
                continue
            s = text.compareRegionStarts(a.getStart(), vc.getStart())
            e = text.compareRegionEnds(a.getEnd(), vc.getStart())
            if s >= 0 and e <= 0:
                return f
        except Exception:
            continue
    return None


def citation_info(m, f):
    d = _fields_data(f)
    tag = _resolve_tag(m, d, _stored(m))
    return tag, _opts_of(d)


def set_citation_options(m, f, opts):
    d = _fields_data(f)
    vals = []
    for k, v in d.items():
        if k == "Custom3":
            continue
        vals.append(bridge.prop(k, v))
    vals.append(bridge.prop("Custom3", json.dumps(opts)))
    f.Fields = tuple(vals)
    refresh(m)


def insert_bibliography_index(m, title="Bibliography"):
    style = current_style(m)
    um = m.getUndoManager()
    um.enterUndoContext("Insert Bibliography")
    try:
        _entry_style(m)
        vc = docapi.view_cursor(m)
        idx = m.createInstance("com.sun.star.text.Bibliography")
        idx.Title = title or ""
        vc.getText().insertTextContent(vc, idx, False)
        try:
            idx.ParaStyleHeading = "Heading 1"
        except Exception:
            pass
        _format_index(m, idx, style)
        refresh(m)
        idx.update()
        return idx
    finally:
        um.leaveUndoContext()
