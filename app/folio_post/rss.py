"""RSS Feeds (M3-07): RSS 2.0, RSS 1.0 (RDF) and Atom feeds as folders under "RSS Feeds",
each article a message, brought up to date with Send/Receive. Nothing leaves the computer but
the request for the feed itself."""
import email.utils
import hashlib
import html
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.message import EmailMessage
from email.policy import SMTP

ATOM = "{http://www.w3.org/2005/Atom}"
RDF = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}"
RSS1 = "{http://purl.org/rss/1.0/}"
DC = "{http://purl.org/dc/elements/1.1/}"
CONTENT = "{http://purl.org/rss/1.0/modules/content/}"
ACCOUNT_NAME = "RSS Feeds"


def _t(el, *names):
    for n in names:
        x = el.find(n)
        if x is not None and (x.text or "").strip():
            return x.text.strip()
    return ""


def _date(s):
    if not s:
        return None
    try:
        return email.utils.parsedate_to_datetime(s).timestamp()
    except (TypeError, ValueError, IndexError):
        pass
    m = re.match(r"(\d{4})-(\d\d)-(\d\d)(?:[T ](\d\d):(\d\d)(?::(\d\d))?(?:\.\d+)?)?\s*(Z|[+-]\d\d:?\d\d)?", s)
    if not m:
        return None
    import datetime as dt
    y, mo, d, hh, mi, ss, tz = m.groups()
    off = dt.timezone.utc
    if tz and tz != "Z":
        sign = -1 if tz[0] == "-" else 1
        tz = tz[1:].replace(":", "")
        off = dt.timezone(sign * dt.timedelta(hours=int(tz[:2]), minutes=int(tz[2:])))
    return dt.datetime(int(y), int(mo), int(d), int(hh or 0), int(mi or 0), int(ss or 0), tzinfo=off).timestamp()


def parse(data, base=""):
    """(feed title, link, [item {id, title, link, author, date, html}])."""
    root = ET.fromstring(data)
    items = []
    if root.tag == ATOM + "feed":
        title = _t(root, ATOM + "title")
        link = next((l.get("href") for l in root.findall(ATOM + "link") if l.get("rel", "alternate") == "alternate"), "")
        for e in root.findall(ATOM + "entry"):
            lk = next((l.get("href") for l in e.findall(ATOM + "link") if l.get("rel", "alternate") == "alternate"), "")
            content = e.find(ATOM + "content")
            if content is None or not (content.text or len(content)):
                content = e.find(ATOM + "summary")
            body = ""
            if content is not None:
                if content.get("type") == "xhtml" and len(content):
                    body = "".join(ET.tostring(c, encoding="unicode") for c in content)
                elif content.get("type") in ("html", "text/html"):
                    body = content.text or ""
                else:
                    body = "<p>%s</p>" % html.escape(content.text or "")
            items.append({"id": _t(e, ATOM + "id") or lk, "title": _t(e, ATOM + "title"), "link": urllib.parse.urljoin(base, lk),
                          "author": _t(e, ATOM + "author/" + ATOM + "name"),
                          "date": _date(_t(e, ATOM + "updated", ATOM + "published")), "html": body})
        return title, link, items
    if root.tag == RDF + "RDF":
        ch = root.find(RSS1 + "channel")
        title = _t(ch, RSS1 + "title") if ch is not None else ""
        link = _t(ch, RSS1 + "link") if ch is not None else ""
        for e in root.findall(RSS1 + "item"):
            lk = _t(e, RSS1 + "link")
            items.append({"id": e.get(RDF + "about") or lk, "title": _t(e, RSS1 + "title"), "link": lk,
                          "author": _t(e, DC + "creator"), "date": _date(_t(e, DC + "date")),
                          "html": _t(e, CONTENT + "encoded") or "<p>%s</p>" % html.escape(_t(e, RSS1 + "description"))})
        return title, link, items
    ch = root.find("channel")
    if ch is None:
        raise ValueError("that address doesn't give an RSS or Atom feed")
    title, link = _t(ch, "title"), _t(ch, "link")
    for e in ch.findall("item"):
        lk = _t(e, "link")
        desc = _t(e, CONTENT + "encoded", "description")
        items.append({"id": _t(e, "guid") or lk or _t(e, "title"), "title": _t(e, "title") or "(no title)",
                      "link": urllib.parse.urljoin(base, lk), "author": _t(e, "author", DC + "creator"),
                      "date": _date(_t(e, "pubDate", DC + "date")), "html": desc})
    return title, link, items


def fetch(url, etag="", modified=""):
    """(status, data, etag, last-modified); 304 when it hasn't changed."""
    h = {"User-Agent": "Folio Post feed reader", "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml"}
    if etag:
        h["If-None-Match"] = etag
    if modified:
        h["If-Modified-Since"] = modified
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read(), r.headers.get("ETag", ""), r.headers.get("Last-Modified", "")
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return 304, b"", etag, modified
        raise


def message_of(feed_title, feed_url, it):
    m = EmailMessage(policy=SMTP)
    dom = urllib.parse.urlparse(feed_url).hostname or "feed"
    m["From"] = email.utils.formataddr((it["author"] or feed_title, "feed@%s" % dom))
    m["Subject"] = html.unescape(re.sub(r"<[^>]+>", "", it["title"]))
    m["Date"] = email.utils.formatdate(it["date"] or time.time(), localtime=True)
    m["Message-ID"] = "<%s@rss.folio>" % hashlib.sha1((feed_url + "|" + it["id"]).encode()).hexdigest()
    m["X-Folio-RSS"] = feed_url
    if it["link"]:
        m["Content-Base"] = it["link"]
    body = ("<html><head><meta charset='utf-8'></head><body><h2>%s</h2>%s<p><a href='%s'>View article...</a></p></body></html>"
            % (html.escape(m["Subject"]), it["html"] or "", html.escape(it["link"] or "", True)))
    text = re.sub(r"<[^>]+>", "", html.unescape(it["html"] or "")).strip() + ("\n\n" + it["link"] if it["link"] else "")
    m.set_content(text)
    m.add_alternative(body, subtype="html")
    return m.as_bytes()


class Feeds:
    def __init__(self, store):
        self.store = store

    def account(self, create=True):
        for a in self.store.accounts():
            if a["kind"] == "rss":
                return a["id"]
        if not create:
            return None
        aid = self.store.add_account(ACCOUNT_NAME, "", "rss", {})
        for f in self.store.folders(aid):
            self.store.drop_folder(f["id"])
        return aid

    def feeds(self):
        return self.store.get("rss-feeds", []) or []

    def _save(self, feeds):
        self.store.put("rss-feeds", feeds)

    def add(self, url, name=""):
        """Subscribe: the feed's folder, filled with what it has now."""
        url = url.strip()
        if url.startswith("feed:"):
            rest = url[5:]
            url = rest if rest.startswith(("http:", "https:")) else "http:" + rest
        if any(f["url"] == url for f in self.feeds()):
            raise ValueError("You're already subscribed to this feed.")
        st, data, et, mod = fetch(url)
        title, _link, _items = parse(data, url)
        aid = self.account()
        nm = (name or title or urllib.parse.urlparse(url).hostname or "Feed").replace("/", "-")
        base = nm
        k = 2
        while any(f["path"] == nm for f in self.store.folders(aid)):
            nm = "%s (%d)" % (base, k)
            k += 1
        fid = self.store.ensure_folder(aid, nm, "")
        feeds = self.feeds()
        feeds.append({"url": url, "name": nm, "folder": fid, "etag": "", "modified": "", "seen": [], "error": ""})
        self._save(feeds)
        n = self._take(feeds[-1], data, et, mod)
        self._save(feeds)
        self.store.changed("messages", fid)
        return fid, n

    def remove(self, url):
        feeds = self.feeds()
        for f in [f for f in feeds if f["url"] == url]:
            if self.store.folder(f["folder"]):
                self.store.drop_folder(f["folder"])
            feeds.remove(f)
        self._save(feeds)

    def _take(self, f, data, et, mod):
        title, _l, items = parse(data, f["url"])
        seen = set(f.get("seen", []))
        n = 0
        for it in reversed(items):
            key = hashlib.sha1(it["id"].encode()).hexdigest()[:16]
            if key in seen:
                continue
            self.store.add_message(f["folder"], message_of(title or f["name"], f["url"], it), 0, [], it["date"] or time.time())
            seen.add(key)
            n += 1
        f["seen"] = sorted(seen)[-2000:]
        f["etag"], f["modified"] = et, mod
        f["error"] = ""
        return n

    def refresh(self):
        """Bring every feed up to date; the number of new articles."""
        feeds = self.feeds()
        total = 0
        for f in feeds:
            if self.store.folder(f["folder"]) is None:
                f["folder"] = self.store.ensure_folder(self.account(), f["name"], "")
            try:
                st, data, et, mod = fetch(f["url"], f.get("etag", ""), f.get("modified", ""))
                if st != 304:
                    total += self._take(f, data, et, mod)
            except Exception as e:
                f["error"] = str(e)
            self.store.changed("messages", f["folder"])
        self._save(feeds)
        return total
