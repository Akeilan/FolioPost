"""vCard (RFC 6350 and 2426) read and written by Post: people and contact groups."""
import base64
import re
import uuid

from .ical import Component, escape, fold, parse_line, unescape, unfold

EMAIL_TYPES = ["work", "home", "other"]
PHONE_TYPES = [("work", "Business"), ("home", "Home"), ("cell", "Mobile"), ("fax", "Business Fax"), ("other", "Other")]


def parse_all(text):
    """Every VCARD in a text (a .vcf can hold many)."""
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    out = []
    cur = None
    for line in unfold(text):
        if not line.strip():
            continue
        name, params, value = parse_line(line)
        if "." in name:
            name = name.split(".", 1)[1]           # item1.EMAIL → EMAIL
        if name == "BEGIN" and value.upper() == "VCARD":
            cur = Component("VCARD")
        elif name == "END" and value.upper() == "VCARD":
            if cur is not None:
                out.append(Contact(cur))
            cur = None
        elif cur is not None:
            if params.get("ENCODING", "").upper() == "QUOTED-PRINTABLE":
                import quopri
                value = quopri.decodestring(value.encode()).decode(params.get("CHARSET", "utf-8"), "replace")
                params.pop("ENCODING")
            cur.props.append((name, params, value))
    return out


def parse(text):
    cs = parse_all(text)
    return cs[0] if cs else None


def _types(params):
    t = params.get("TYPE", "")
    return [x.strip().lower() for x in t.split(",") if x.strip()]


class Contact:
    def __init__(self, comp=None):
        self.comp = comp or Component("VCARD")

    # ---- reading
    @property
    def uid(self):
        return re.sub(r"(?i)^urn:uuid:", "", self.comp.get("UID", ""))

    @property
    def is_group(self):
        k = (self.comp.get("KIND", "") or self.comp.get("X-ADDRESSBOOKSERVER-KIND", "")).lower()
        return k == "group"

    @property
    def name(self):
        fn = unescape(self.comp.get("FN", "")).strip()
        if fn:
            return fn
        n = self.n
        full = " ".join(x for x in (n[3], n[1], n[2], n[0], n[4]) if x)
        if full:
            return full
        if self.company:
            return self.company
        e = self.emails
        return e[0][1] if e else ""

    @property
    def n(self):
        """(family, given, additional, prefix, suffix)."""
        v = self.comp.get("N", "")
        parts = [unescape(p) for p in re.split(r"(?<!\\);", v)] if v else []
        parts += [""] * (5 - len(parts))
        return tuple(parts[:5])

    @property
    def emails(self):
        out = []
        for p, v in self.comp.all("EMAIL"):
            t = [x for x in _types(p) if x in ("work", "home", "internet", "pref")]
            kind = "work" if "work" in t else "home" if "home" in t else "other"
            out.append((kind, unescape(v).strip()))
        return out

    @property
    def phones(self):
        out = []
        for p, v in self.comp.all("TEL"):
            t = _types(p)
            kind = "fax" if "fax" in t else "cell" if ("cell" in t or "mobile" in t) else "home" if "home" in t else \
                "work" if "work" in t else "other"
            out.append((kind, unescape(re.sub(r"^tel:", "", v))))
        return out

    @property
    def addresses(self):
        out = []
        for p, v in self.comp.all("ADR"):
            parts = [unescape(x) for x in re.split(r"(?<!\\);", v)]
            parts += [""] * (7 - len(parts))
            t = _types(p)
            out.append(("home" if "home" in t else "work" if "work" in t else "other",
                        {"pobox": parts[0], "ext": parts[1], "street": parts[2], "city": parts[3], "region": parts[4],
                         "postal": parts[5], "country": parts[6]}))
        return out

    @property
    def company(self):
        v = self.comp.get("ORG", "")
        return unescape(re.split(r"(?<!\\);", v)[0]) if v else ""

    @property
    def department(self):
        v = self.comp.get("ORG", "")
        parts = re.split(r"(?<!\\);", v) if v else []
        return unescape(parts[1]) if len(parts) > 1 else ""

    def text(self, name):
        return unescape(self.comp.get(name, ""))

    @property
    def title(self):
        return self.text("TITLE")

    @property
    def note(self):
        return self.text("NOTE")

    @property
    def birthday(self):
        return self.comp.get("BDAY", "")

    @property
    def urls(self):
        return [unescape(v) for _p, v in self.comp.all("URL")]

    @property
    def photo(self):
        """The picture's bytes, if it's inside the card."""
        p, v = self.comp.getp("PHOTO")
        if v is None:
            return None
        if v.startswith("data:"):
            try:
                return base64.b64decode(v.split(",", 1)[1])
            except Exception:
                return None
        if (p or {}).get("ENCODING", "").lower() in ("b", "base64"):
            try:
                return base64.b64decode(v)
            except Exception:
                return None
        return None

    @property
    def categories(self):
        v = self.comp.get("CATEGORIES", "")
        return [unescape(x) for x in re.split(r"(?<!\\),", v) if x]

    @property
    def members(self):
        """A group's members: e-mail addresses (mailto:) and contact uids (urn:uuid:)."""
        out = []
        for _p, v in self.comp.all("MEMBER") + self.comp.all("X-ADDRESSBOOKSERVER-MEMBER"):
            out.append(v)
        return out

    def member_emails(self):
        return [re.sub(r"(?i)^mailto:", "", m) for m in self.members if m.lower().startswith("mailto:")]

    def member_uids(self):
        return [re.sub(r"(?i)^urn:uuid:", "", m) for m in self.members if m.lower().startswith("urn:uuid:")]

    # ---- writing
    def set_text(self, name, value):
        self.comp.set(name, escape(value) if value else None)

    def set_name(self, full, given="", family=""):
        self.comp.set("FN", escape(full))
        if given or family or not self.is_group:
            if not (given or family):
                bits = full.split()
                given, family = (" ".join(bits[:-1]), bits[-1]) if len(bits) > 1 else (full, "")
            self.comp.set("N", ";".join(escape(x).replace("\\,", ",") for x in (family, given, "", "", "")))

    def set_emails(self, items):
        self.comp.props = [x for x in self.comp.props if x[0] != "EMAIL"]
        for i, (kind, addr) in enumerate(items):
            if addr:
                p = {"TYPE": "INTERNET," + kind.upper() if kind in ("work", "home") else "INTERNET"}
                if i == 0:
                    p["TYPE"] += ",PREF"
                self.comp.add("EMAIL", addr, p)

    def set_phones(self, items):
        self.comp.props = [x for x in self.comp.props if x[0] != "TEL"]
        for kind, num in items:
            if num:
                t = {"work": "WORK,VOICE", "home": "HOME,VOICE", "cell": "CELL", "fax": "WORK,FAX"}.get(kind, "VOICE")
                self.comp.add("TEL", num, {"TYPE": t})

    def set_address(self, kind, a):
        self.comp.props = [x for x in self.comp.props if not (x[0] == "ADR" and (kind in _types(x[1]) or not _types(x[1])))]
        if any(a.get(k) for k in ("street", "city", "region", "postal", "country")):
            v = ";".join(escape(a.get(k, "")) for k in ("pobox", "ext", "street", "city", "region", "postal", "country"))
            self.comp.add("ADR", v, {"TYPE": kind.upper()})

    def set_company(self, company, department=""):
        self.comp.set("ORG", (escape(company) + (";" + escape(department) if department else "")) if company else None)

    def set_photo(self, data, mimetype="image/jpeg"):
        if data is None:
            self.comp.set("PHOTO", None)
        else:
            self.comp.set("PHOTO", base64.b64encode(data).decode(), {"ENCODING": "b", "TYPE": mimetype.split("/")[-1].upper()})

    def set_members(self, emails=(), uids=()):
        self.comp.props = [x for x in self.comp.props if x[0] not in ("MEMBER", "X-ADDRESSBOOKSERVER-MEMBER")]
        for e in emails:
            self.comp.add("X-ADDRESSBOOKSERVER-MEMBER", "mailto:" + e)
        for u in uids:
            self.comp.add("X-ADDRESSBOOKSERVER-MEMBER", "urn:uuid:" + u)

    def touch(self):
        import datetime as dt
        self.comp.set("REV", dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ"))

    def dumps(self):
        # written as vCard 3.0, which every address book reads
        props = [x for x in self.comp.props if x[0] != "VERSION"]
        out = ["BEGIN:VCARD", "VERSION:3.0"]
        for n, p, v in props:
            head = n + "".join(";%s=%s" % (k, ('"%s"' % pv) if re.search(r"[:;]", pv) else pv) for k, pv in p.items())
            out.append(fold(head + ":" + v))
        out.append("END:VCARD")
        return "\r\n".join(out) + "\r\n"


def new_contact(name, email="", company="", phone=""):
    c = Contact()
    c.comp.add("UID", str(uuid.uuid4()))
    c.set_name(name)
    if email:
        c.set_emails([("work", email)])
    if company:
        c.set_company(company)
    if phone:
        c.set_phones([("cell", phone)])
    c.touch()
    return c


def new_group(name, emails=(), uids=()):
    c = Contact()
    c.comp.add("UID", str(uuid.uuid4()))
    c.comp.add("X-ADDRESSBOOKSERVER-KIND", "group")
    c.comp.set("FN", escape(name))
    c.comp.set("N", escape(name) + ";;;;")
    c.set_members(emails, uids)
    c.touch()
    return c
