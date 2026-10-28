"""Document properties with the new engine, in Word's parts: docProps/core.xml
(title, author...), docProps/app.xml (template, editing time, revision) and
docProps/custom.xml (custom properties, and the settings the app keeps)."""
import datetime
import json
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

CP = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
DC = "http://purl.org/dc/elements/1.1/"
DCT = "http://purl.org/dc/terms/"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
EP = "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
CU = "http://schemas.openxmlformats.org/officeDocument/2006/custom-properties"
VT = "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"
FMTID = "{D5CDD505-2E9C-101B-9397-08002B2CF9AE}"
REL = "http://schemas.openxmlformats.org/"
CORE = [("title", DC), ("subject", DC), ("creator", DC), ("keywords", CP),
        ("description", DC), ("lastModifiedBy", CP), ("revision", CP),
        ("lastPrinted", CP), ("created", DCT), ("modified", DCT), ("category", CP),
        ("contentStatus", CP)]
_NS = {"cp": CP, "dc": DC, "dcterms": DCT}


def _parse(ed, name):
    x = ed.package_part(name)
    if not x:
        return None
    try:
        return ET.fromstring(x.encode() if isinstance(x, str) else x)
    except ET.ParseError:
        return None


# ---------------------------------------------------------------- core
def core(ed):
    root = _parse(ed, "docProps/core.xml")
    out = {}
    if root is None:
        return out
    for name, ns in CORE:
        e = root.find("{%s}%s" % (ns, name))
        if e is not None and e.text:
            out[name] = e.text
    return out


def set_core(ed, **values):
    d = core(ed)
    for k, v in values.items():
        if v is None or v == "":
            d.pop(k, None)
        else:
            d[k] = str(v)
    parts = []
    for name, ns in CORE:
        if name not in d:
            continue
        pre = {CP: "cp", DC: "dc", DCT: "dcterms"}[ns]
        typ = ' xsi:type="dcterms:W3CDTF"' if name in ("created", "modified") else ""
        parts.append("<%s:%s%s>%s</%s:%s>" % (pre, name, typ, escape(d[name]), pre, name))
    xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<cp:coreProperties xmlns:cp="%s" xmlns:dc="%s" xmlns:dcterms="%s" '
           'xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="%s">%s</cp:coreProperties>'
           % (CP, DC, DCT, XSI, "".join(parts)))
    ed.set_package_part("docProps/core.xml", xml,
                        "application/vnd.openxmlformats-package.core-properties+xml",
                        REL + "package/2006/relationships/metadata/core-properties")


def app(ed):
    root = _parse(ed, "docProps/app.xml")
    out = {}
    if root is not None:
        for e in root:
            if len(e) == 0 and e.text:
                out[e.tag.split("}")[-1]] = e.text
    return out


# ---------------------------------------------------------------- custom
def _value(e):
    for v in e:
        tag = v.tag.split("}")[-1]
        t = v.text or ""
        if tag in ("i4", "i8", "int", "i2", "i1", "ui4", "uint"):
            try:
                return int(t)
            except ValueError:
                return 0
        if tag in ("r8", "r4", "decimal"):
            try:
                return float(t)
            except ValueError:
                return 0.0
        if tag == "bool":
            return t.lower() in ("true", "1")
        if tag == "filetime":
            try:
                return datetime.datetime.strptime(t[:19], "%Y-%m-%dT%H:%M:%S")
            except ValueError:
                return t
        return t
    return ""


def custom(ed):
    root = _parse(ed, "docProps/custom.xml")
    out = {}
    if root is None:
        return out
    for p in root:
        n = p.get("name")
        if n:
            out[n] = _value(p)
    return out


def _vt(v):
    if isinstance(v, bool):
        return "<vt:bool>%s</vt:bool>" % ("true" if v else "false")
    if isinstance(v, int):
        return "<vt:i4>%d</vt:i4>" % v
    if isinstance(v, float):
        return "<vt:r8>%r</vt:r8>" % v
    if isinstance(v, datetime.datetime):
        return "<vt:filetime>%s</vt:filetime>" % v.strftime("%Y-%m-%dT%H:%M:%SZ")
    if not isinstance(v, str):
        v = json.dumps(v)
    return "<vt:lpwstr>%s</vt:lpwstr>" % escape(v)


def set_custom(ed, name, value):
    d = custom(ed)
    if value is None:
        if name not in d:
            return
        d.pop(name)
    else:
        if d.get(name) == value:
            return
        d[name] = value
    props = "".join('<property fmtid="%s" pid="%d" name="%s">%s</property>'
                    % (FMTID, i + 2, escape(k, {'"': "&quot;"}), _vt(v))
                    for i, (k, v) in enumerate(d.items()))
    xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<Properties xmlns="%s" xmlns:vt="%s">%s</Properties>' % (CU, VT, props))
    ed.set_package_part("docProps/custom.xml", xml,
                        "application/vnd.openxmlformats-officedocument.custom-properties+xml",
                        REL + "officeDocument/2006/relationships/custom-properties")


# ---------------------------------------------------------------- UNO stand-in
class _DT:
    def __init__(self, d):
        self.Year, self.Month, self.Day = d.year, d.month, d.day
        self.Hours, self.Minutes, self.Seconds = d.hour, d.minute, d.second


def _when(s):
    if not s:
        return None
    try:
        d = datetime.datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")
        # stored in UTC
        return d.replace(tzinfo=datetime.timezone.utc).astimezone().replace(tzinfo=None)
    except ValueError:
        return None


class _Empty:
    Year = Month = Day = Hours = Minutes = Seconds = 0


class UserProps:
    """getUserDefinedProperties(): custom.xml."""

    def __init__(self, ed):
        self.ed = ed

    def getPropertyValue(self, k):
        d = custom(self.ed)
        if k not in d:
            raise KeyError(k)
        return d[k]

    def setPropertyValue(self, k, v):
        set_custom(self.ed, k, v)

    def addProperty(self, k, attrs, v):
        set_custom(self.ed, k, v)

    def removeProperty(self, k):
        set_custom(self.ed, k, None)

    def getPropertySetInfo(self):
        d = custom(self.ed)

        class Info:
            def hasPropertyByName(self, k):
                return k in d

            def getProperties(self):
                return [type("P", (), {"Name": k})() for k in d]
        return Info()


_ATTR = {"Title": "title", "Subject": "subject", "Author": "creator",
         "Description": "description", "ModifiedBy": "lastModifiedBy",
         "Category": "category", "ContentStatus": "contentStatus"}
_DATES = {"CreationDate": "created", "ModificationDate": "modified", "PrintDate": "lastPrinted"}


class DocumentProperties:
    """What getDocumentProperties() gives with the classic engine."""

    def __init__(self, ed):
        object.__setattr__(self, "ed", ed)

    def getUserDefinedProperties(self):
        return UserProps(self.ed)

    def __getattr__(self, k):
        c = core(self.ed)
        if k in _ATTR:
            return c.get(_ATTR[k], "")
        if k == "Keywords":
            return tuple(x.strip() for x in c.get("keywords", "").replace(";", ",").split(",") if x.strip())
        if k in _DATES:
            d = _when(c.get(_DATES[k]))
            return _DT(d) if d else _Empty()
        if k == "DocumentStatistics":
            st = self.ed.stats(True)
            P = type("P", (), {})
            out = []
            for name, key in (("PageCount", "pages"), ("WordCount", "words"),
                              ("CharacterCount", "chars_spaces"), ("ParagraphCount", "paras"),
                              ("NonWhitespaceCharacterCount", "chars")):
                p = P()
                p.Name, p.Value = name, st.get(key, 0)
                out.append(p)
            return out
        a = app(self.ed)
        if k == "EditingCycles":
            try:
                return int(c.get("revision", "0"))
            except ValueError:
                return 0
        if k == "EditingDuration":
            try:
                return int(a.get("TotalTime", "0")) * 60
            except ValueError:
                return 0
        if k == "TemplateName":
            return a.get("Template", "")
        raise AttributeError(k)

    def __setattr__(self, k, v):
        if k in _ATTR:
            set_core(self.ed, **{_ATTR[k]: v})
        elif k == "Keywords":
            set_core(self.ed, keywords=", ".join(v) if not isinstance(v, str) else v)
        elif k in _DATES:
            if isinstance(v, (_DT, _Empty)) and v.Year:
                d = datetime.datetime(v.Year, v.Month, v.Day, v.Hours, v.Minutes, v.Seconds).astimezone()
                v = d.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            set_core(self.ed, **{_DATES[k]: v if isinstance(v, str) else None})
        else:
            object.__setattr__(self, k, v)


def stamp_saved(ed, author=""):
    """On save: modified time, revision, last modified by (as Word does)."""
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    c = core(ed)
    try:
        rev = int(c.get("revision", "0")) + 1
    except ValueError:
        rev = 1
    vals = {"modified": now, "revision": str(rev)}
    if "created" not in c:
        vals["created"] = now
    if author:
        vals["lastModifiedBy"] = author
        if not c.get("creator"):
            vals["creator"] = author
    set_core(ed, **vals)
