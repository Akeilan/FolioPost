"""Address books on servers: CardDAV (RFC 6352) — Google Contacts (with the Google sign-in), iCloud,
Fastmail, Nextcloud and the rest — kept in step both ways."""
import re
import threading
import urllib.parse
import uuid

from . import vcard
from .caldav import Client, DavError, NS

NS = dict(NS, card="urn:ietf:params:xml:ns:carddav")
GOOGLE_CARDDAV = "https://www.googleapis.com/carddav/v1/principals/%s/lists/default/"


class CardClient(Client):
    def home(self):
        pr = self.principal()
        if pr is None:
            return self.base
        body_props = ["card:addressbook-home-set"]
        res = self._propfind(pr, body_props)
        for _href, p in res:
            e = p.get("{urn:ietf:params:xml:ns:carddav}addressbook-home-set")
            if e is not None:
                h = e.findtext("d:href", "", NS)
                if h:
                    return h
        return pr

    def _propfind(self, url, props, depth="0"):
        body = ('<?xml version="1.0"?><d:propfind xmlns:d="DAV:" xmlns:card="urn:ietf:params:xml:ns:carddav" '
                'xmlns:cs="http://calendarserver.org/ns/"><d:prop>%s</d:prop></d:propfind>' % "".join("<%s/>" % p for p in props))
        root = self.xml("PROPFIND", url, body, depth)
        out = []
        for r in (root.findall("d:response", NS) if root is not None else []):
            href = r.findtext("d:href", "", NS)
            props_ = {}
            for ps in r.findall("d:propstat", NS):
                if "200" not in (ps.findtext("d:status", "", NS) or "200"):
                    continue
                prop = ps.find("d:prop", NS)
                for p in (list(prop) if prop is not None else []):
                    props_[p.tag] = p
            out.append((href, props_))
        return out

    def principal(self):
        for start in (self.base, "/.well-known/carddav"):
            try:
                res = self._propfind(start, ["d:current-user-principal"])
            except DavError:
                continue
            for _h, p in res:
                e = p.get("{DAV:}current-user-principal")
                if e is not None and e.findtext("d:href", "", NS):
                    return e.findtext("d:href", "", NS)
        return None

    def books(self):
        home = self.home()
        out = []
        for href, p in self._propfind(home, ["d:resourcetype", "d:displayname", "cs:getctag"], "1"):
            rt = p.get("{DAV:}resourcetype")
            if rt is None or rt.find("card:addressbook", NS) is None:
                continue
            name = (p.get("{DAV:}displayname").text if p.get("{DAV:}displayname") is not None else "") or \
                urllib.parse.unquote(href.rstrip("/").split("/")[-1])
            out.append({"href": href, "name": name})
        return out

    def ctag(self, href):
        for _h, p in self._propfind(href, ["cs:getctag", "d:sync-token"]):
            e = p.get("{http://calendarserver.org/ns/}getctag")
            if e is None:
                e = p.get("{DAV:}sync-token")
            return (e.text or "") if e is not None else ""
        return ""

    def etags(self, href):
        body = ('<?xml version="1.0"?><card:addressbook-query xmlns:d="DAV:" xmlns:card="urn:ietf:params:xml:ns:carddav">'
                '<d:prop><d:getetag/></d:prop></card:addressbook-query>')
        root = self.xml("REPORT", href, body, "1")
        out = {}
        for r in (root.findall("d:response", NS) if root is not None else []):
            h = r.findtext("d:href", "", NS)
            if h and not h.endswith("/"):
                out[h] = r.findtext(".//d:getetag", "", NS)
        return out

    def multiget(self, href, hrefs):
        out = []
        for i in range(0, len(hrefs), 50):
            body = ('<?xml version="1.0"?><card:addressbook-multiget xmlns:d="DAV:" xmlns:card="urn:ietf:params:xml:ns:carddav">'
                    '<d:prop><d:getetag/><card:address-data/></d:prop>%s</card:addressbook-multiget>' %
                    "".join("<d:href>%s</d:href>" % h.replace("&", "&amp;") for h in hrefs[i:i + 50]))
            root = self.xml("REPORT", href, body, "1")
            for r in (root.findall("d:response", NS) if root is not None else []):
                data = r.findtext(".//card:address-data", None, NS)
                if data:
                    out.append((r.findtext("d:href", "", NS), r.findtext(".//d:getetag", "", NS), data))
        return out

    def put(self, href, card, etag=None, new=False):
        h = {"Content-Type": "text/vcard; charset=utf-8"}
        if new:
            h["If-None-Match"] = "*"
        elif etag:
            h["If-Match"] = etag
        st, headers, _b = self.request("PUT", href, card, h)
        if st == 412:
            raise DavError(412, "changed on the server")
        if st >= 400:
            raise DavError(st)
        return headers.get("ETag") or headers.get("Etag") or headers.get("etag") or ""


class ContactSync:
    def __init__(self, store, secrets, tokens):
        self.store = store
        self.secrets = secrets
        self.tokens = tokens
        self.lock = threading.Lock()
        self.errors = {}

    def client_for(self, book):
        if book["kind"] == "google":
            acc = self.store.account(book["account"])
            return CardClient(book["url"], acc["email"], token=lambda: self.tokens(acc))
        src = self.store.get("book-source:%d" % book["id"], {}) or {}
        pw = self.secrets.get(src.get("secret_key", ""), "carddav") if src.get("secret_key") else None
        return CardClient(src.get("url") or book["url"], src.get("user", ""), pw)

    def add_carddav(self, url, user, password):
        c = CardClient(url, user, password)
        ids = []
        key = "carddav-src-%s" % uuid.uuid4().hex[:8]
        for b in c.books():
            u = c.url(b["href"])
            bid = self.store.add_book(b["name"], "carddav", u)
            self.store.put("book-source:%d" % bid, {"url": u, "user": user, "secret_key": key})
            ids.append(bid)
        if ids and password is not None:
            self.secrets.set(key, password, "carddav")
        return ids

    def add_google(self, account):
        acc = self.store.account(account)
        url = GOOGLE_CARDDAV % urllib.parse.quote(acc["email"])
        return [self.store.add_book("Contacts (%s)" % acc["email"], "google", url, account)]

    def sync(self, bid):
        book = self.store.book(bid)
        if book is None or book["kind"] == "local":
            return True
        with self.lock:
            try:
                if book["kind"] == "ews":
                    from . import ews
                    c = ews.client_for(self.store.account(book["account"]), self.secrets, self.tokens)
                    try:
                        ews.sync_book(self.store, c, book)
                    finally:
                        c.close()
                    self.errors.pop(bid, None)
                    return True
                self._sync(book)
                self.errors.pop(bid, None)
                return True
            except Exception as e:
                self.errors[bid] = str(e)
                return False

    def sync_all(self):
        return [self.sync(b["id"]) for b in self.store.books()]

    def _sync(self, book):
        c = self.client_for(book)
        bid = book["id"]
        for ct in self.store.contacts(bid, with_deleted=True):
            p = ct["pending"]
            if not p:
                continue
            try:
                if p == "deleted":
                    if ct["href"]:
                        st, _h, _b = c.request("DELETE", ct["href"], None, {"If-Match": ct["etag"]} if ct["etag"] else {})
                        if st >= 400 and st not in (404, 410):
                            raise DavError(st)
                    self.store.drop_contact(ct["id"])
                elif p == "new":
                    href = book["url"].rstrip("/") + "/" + urllib.parse.quote(re.sub(r"[^\w.@-]", "_", ct["uid"] or str(ct["id"]))) + ".vcf"
                    et = c.put(href, ct["vcard"], new=True)
                    self.store.set_contact_fields(ct["id"], href=urllib.parse.urlparse(c.url(href)).path, etag=et, pending="")
                else:
                    et = c.put(ct["href"], ct["vcard"], ct["etag"])
                    self.store.set_contact_fields(ct["id"], etag=et, pending="")
            except DavError as err:
                if err.status == 412:
                    self.store.set_contact_fields(ct["id"], pending="", etag="conflict")
                else:
                    raise
        tag = c.ctag(book["url"])
        if tag and tag == book["ctag"]:
            return
        remote = c.etags(book["url"])
        local = {x["href"]: x for x in self.store.contacts(bid, with_deleted=True) if x["href"]}
        for href, x in local.items():
            if href not in remote and not x["pending"]:
                self.store.drop_contact(x["id"])
        want = [h for h, et in remote.items() if h not in local or local[h]["etag"] != et]
        for href, et, data in c.multiget(book["url"], want):
            old = local.get(href)
            if old and old["pending"]:
                continue
            self.store.put_contact(bid, data, href, et, "", old["id"] if old else None)
        self.store.update_book(bid, ctag=tag)


def save_contact(store, bid, card, cid=None):
    """A contact made or changed here; the sync sends it."""
    book = store.book(bid)
    local = book is None or book["kind"] == "local"
    text = card.dumps() if isinstance(card, vcard.Contact) else card
    if cid is not None:
        old = store.contact(cid)
        if old and old["book"] != bid:
            delete_contact(store, cid)
            return store.put_contact(bid, text, "", "", "" if local else "new")
        pend = "" if local else ((old["pending"] or "changed") if old and old["href"] else "new")
        return store.put_contact(bid, text, old["href"] if old else "", old["etag"] if old else "", pend, cid)
    return store.put_contact(bid, text, "", "", "" if local else "new")


def delete_contact(store, cid):
    ct = store.contact(cid)
    if ct is None:
        return
    book = store.book(ct["book"])
    if ct["href"] and book and book["kind"] != "local":
        store.set_contact_fields(cid, pending="deleted")
    else:
        store.drop_contact(cid)
