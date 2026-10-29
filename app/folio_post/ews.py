"""Exchange through Exchange Web Services (EWS): mail, calendar, contacts and tasks, both ways,
plus Automatic Replies, free/busy, other people's calendars and delegates. Signs in with a
Microsoft work or school account (OAuth, the same sign-in as Outlook.com mail) or with a
password (Basic or NTLM, for Exchange servers in an organisation).

The mail side looks like an IMAP connection to the sync (folders, numbered messages, flags), so
mail from Exchange is kept exactly as mail from any other server is."""
import base64
import datetime as dt
import hashlib
import hmac
import http.client
import json
import os
import re
import ssl
import struct
import time
import urllib.parse
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape as _esc

S = "http://schemas.xmlsoap.org/soap/envelope/"
T = "http://schemas.microsoft.com/exchange/services/2006/types"
M = "http://schemas.microsoft.com/exchange/services/2006/messages"
NS = {"s": S, "t": T, "m": M}
OFFICE365 = "https://outlook.office365.com/EWS/Exchange.asmx"
VERSION = "Exchange2013_SP1"
ITEM_TAGS = ("Message", "CalendarItem", "Contact", "DistributionList", "Task", "MeetingRequest", "MeetingResponse",
             "MeetingCancellation", "PostItem", "Item")


class EwsError(Exception):
    def __init__(self, code, text=""):
        Exception.__init__(self, "%s%s" % (code, (": " + text) if text else ""))
        self.code = code


class AuthError(Exception):
    pass


def esc(s):
    return _esc(str(s), {'"': "&quot;"})


def q(tag):
    p, _, n = tag.partition(":")
    return "{%s}%s" % (NS[p], n)


def txt(el, path, default=""):
    if el is None:
        return default
    x = el.find(path, NS)
    return x.text if x is not None and x.text is not None else default


# ---------------------------------------------------------------- NTLM (MS-NLMP), written here
def md4(data):
    """MD4 (RFC 1320): NTLM needs it and OpenSSL 3 no longer has it."""
    try:
        return hashlib.new("md4", data).digest()
    except (ValueError, TypeError):
        pass

    def f(x, y, z):
        return (x & y) | (~x & z)

    def g(x, y, z):
        return (x & y) | (x & z) | (y & z)

    def h(x, y, z):
        return x ^ y ^ z

    def rol(v, s):
        v &= 0xFFFFFFFF
        return ((v << s) | (v >> (32 - s))) & 0xFFFFFFFF
    msg = bytearray(data)
    n = len(msg) * 8
    msg.append(0x80)
    while len(msg) % 64 != 56:
        msg.append(0)
    msg += struct.pack("<Q", n)
    a, b, c, d = 0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476
    for off in range(0, len(msg), 64):
        X = struct.unpack("<16I", bytes(msg[off:off + 64]))
        aa, bb, cc, dd = a, b, c, d
        for i in range(16):
            k = i
            s = (3, 7, 11, 19)[i % 4]
            if i % 4 == 0:
                a = rol(a + f(b, c, d) + X[k], s)
            elif i % 4 == 1:
                d = rol(d + f(a, b, c) + X[k], s)
            elif i % 4 == 2:
                c = rol(c + f(d, a, b) + X[k], s)
            else:
                b = rol(b + f(c, d, a) + X[k], s)
        for i in range(16):
            k = (i % 4) * 4 + i // 4
            s = (3, 5, 9, 13)[i % 4]
            if i % 4 == 0:
                a = rol(a + g(b, c, d) + X[k] + 0x5A827999, s)
            elif i % 4 == 1:
                d = rol(d + g(a, b, c) + X[k] + 0x5A827999, s)
            elif i % 4 == 2:
                c = rol(c + g(d, a, b) + X[k] + 0x5A827999, s)
            else:
                b = rol(b + g(c, d, a) + X[k] + 0x5A827999, s)
        order = (0, 8, 4, 12, 2, 10, 6, 14, 1, 9, 5, 13, 3, 11, 7, 15)
        for i in range(16):
            k = order[i]
            s = (3, 9, 11, 15)[i % 4]
            if i % 4 == 0:
                a = rol(a + h(b, c, d) + X[k] + 0x6ED9EBA1, s)
            elif i % 4 == 1:
                d = rol(d + h(a, b, c) + X[k] + 0x6ED9EBA1, s)
            elif i % 4 == 2:
                c = rol(c + h(d, a, b) + X[k] + 0x6ED9EBA1, s)
            else:
                b = rol(b + h(c, d, a) + X[k] + 0x6ED9EBA1, s)
        a, b, c, d = (a + aa) & 0xFFFFFFFF, (b + bb) & 0xFFFFFFFF, (c + cc) & 0xFFFFFFFF, (d + dd) & 0xFFFFFFFF
    return struct.pack("<4I", a, b, c, d)


def ntowf_v2(user, password, domain):
    nt = md4(password.encode("utf-16-le"))
    return hmac.new(nt, (user.upper() + domain).encode("utf-16-le"), hashlib.md5).digest()


NTLM_FLAGS = 0x00000001 | 0x00000004 | 0x00000200 | 0x00008000 | 0x00080000 | 0x00800000 | 0x20000000 | 0x80000000 | 0x02000000


def ntlm_negotiate():
    return b"NTLMSSP\0" + struct.pack("<I", 1) + struct.pack("<I", NTLM_FLAGS) + b"\0" * 16


def ntlm_parse_challenge(msg):
    if msg[:8] != b"NTLMSSP\0" or struct.unpack_from("<I", msg, 8)[0] != 2:
        raise AuthError("the server's NTLM challenge isn't readable")
    flags = struct.unpack_from("<I", msg, 20)[0]
    challenge = msg[24:32]
    ti_len, _ti_max, ti_off = struct.unpack_from("<HHI", msg, 40) if len(msg) >= 48 else (0, 0, 0)
    return flags, challenge, msg[ti_off:ti_off + ti_len]


def ntlmv2_response(user, password, domain, server_challenge, target_info, client_challenge=None, timestamp=None):
    """(NTChallengeResponse, LMChallengeResponse, session base key)."""
    key = ntowf_v2(user, password, domain)
    cc = client_challenge if client_challenge is not None else os.urandom(8)
    if timestamp is None:
        timestamp = int((time.time() + 11644473600) * 10000000)
    temp = b"\x01\x01" + b"\0" * 6 + struct.pack("<Q", timestamp) + cc + b"\0" * 4 + target_info + b"\0" * 4
    proof = hmac.new(key, server_challenge + temp, hashlib.md5).digest()
    lm = hmac.new(key, server_challenge + cc, hashlib.md5).digest() + cc
    return proof + temp, lm, hmac.new(key, proof, hashlib.md5).digest()


def ntlm_authenticate(user, password, domain, challenge_msg, workstation=""):
    flags, chal, ti = ntlm_parse_challenge(challenge_msg)
    nt, lm, _k = ntlmv2_response(user, password, domain, chal, ti)
    dom, usr, ws = domain.encode("utf-16-le"), user.encode("utf-16-le"), workstation.encode("utf-16-le")
    off = 64
    fields = []
    payload = b""
    for blob in (lm, nt, dom, usr, ws, b""):
        fields.append(struct.pack("<HHI", len(blob), len(blob), off + len(payload)))
        payload += blob
    head = b"NTLMSSP\0" + struct.pack("<I", 3) + b"".join(fields) + struct.pack("<I", flags & NTLM_FLAGS)
    return head + payload


# ---------------------------------------------------------------- the connection
class Client:
    """SOAP over HTTPS to an EWS address."""

    def __init__(self, url, user="", password=None, token=None, auth="", insecure=False, mailbox=""):
        self.url = url
        self.user = user
        self.password = password
        self.token = token                 # a string or a function giving one
        self.auth = auth or ("bearer" if token else "basic")
        self.insecure = insecure
        self.conn = None
        self.ntlm_ok = False
        self.version = VERSION
        self.log = []

    def _connect(self):
        u = urllib.parse.urlparse(self.url)
        if u.scheme == "https":
            ctx = ssl.create_default_context()
            if self.insecure:
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            self.conn = http.client.HTTPSConnection(u.hostname, u.port or 443, timeout=60, context=ctx)
        else:
            self.conn = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=60)
        self.ntlm_ok = False

    def close(self):
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = None

    def _post(self, body, headers):
        if self.conn is None:
            self._connect()
        u = urllib.parse.urlparse(self.url)
        path = u.path + ("?" + u.query if u.query else "")
        try:
            self.conn.request("POST", path, body, headers)
            r = self.conn.getresponse()
        except (http.client.HTTPException, OSError):
            self._connect()
            self.conn.request("POST", path, body, headers)
            r = self.conn.getresponse()
        data = r.read()
        return r.status, dict((k.lower(), v) for k, v in r.getheaders()), data

    def _domain_user(self):
        if "\\" in self.user:
            d, u = self.user.split("\\", 1)
            return d, u
        return "", self.user

    def post(self, xml):
        body = xml.encode("utf-8")
        h = {"Content-Type": "text/xml; charset=utf-8", "Accept": "text/xml"}
        if self.auth == "bearer":
            tok = self.token() if callable(self.token) else self.token
            h["Authorization"] = "Bearer " + tok
        elif self.auth == "basic":
            h["Authorization"] = "Basic " + base64.b64encode(("%s:%s" % (self.user, self.password or "")).encode()).decode()
        elif self.auth == "ntlm" and not self.ntlm_ok:
            # the three-step handshake, on one connection; the connection stays signed in afterwards
            st, hd, _d = self._post(body, dict(h, Authorization="NTLM " + base64.b64encode(ntlm_negotiate()).decode()))
            m = re.search(r"NTLM ([A-Za-z0-9+/=]+)", hd.get("www-authenticate", ""))
            if st != 401 or not m:
                if st < 400:
                    self.ntlm_ok = True
                    return _d
                raise AuthError("the server doesn't offer NTLM sign-in")
            dom, usr = self._domain_user()
            auth = ntlm_authenticate(usr, self.password or "", dom, base64.b64decode(m.group(1)))
            h["Authorization"] = "NTLM " + base64.b64encode(auth).decode()
        st, hd, data = self._post(body, h)
        if st == 401:
            self.ntlm_ok = False
            raise AuthError("the server didn't accept the sign-in")
        if self.auth == "ntlm":
            self.ntlm_ok = True
        if st >= 400 and b"Envelope" not in data[:400]:
            raise EwsError("HTTP %d" % st, data[:200].decode("utf-8", "replace"))
        return data

    def call(self, body, impersonate=""):
        head = '<t:RequestServerVersion Version="%s"/>' % self.version
        env = ('<?xml version="1.0" encoding="utf-8"?>'
               '<s:Envelope xmlns:s="%s" xmlns:t="%s" xmlns:m="%s"><s:Header>%s</s:Header><s:Body>%s</s:Body></s:Envelope>'
               % (S, T, M, head, body))
        data = self.post(env)
        try:
            root = ET.fromstring(data)
        except ET.ParseError as e:
            raise EwsError("BadResponse", str(e))
        fault = root.find(".//s:Fault", NS)
        if fault is not None:
            raise EwsError(fault.findtext("faultcode") or "Fault", fault.findtext("faultstring") or "")
        return root

    @staticmethod
    def messages(root):
        """The response messages, raising for the first error."""
        out = []
        for rm in root.iter():
            if rm.tag.startswith("{%s}" % M) and rm.tag.endswith("ResponseMessage"):
                if rm.get("ResponseClass") == "Error":
                    raise EwsError(txt(rm, "m:ResponseCode", "Error"), txt(rm, "m:MessageText"))
                out.append(rm)
        return out

    # ------------------------------------------------------------ folders
    def find_folders(self, mailbox=""):
        root = self.call('<m:FindFolder Traversal="Deep"><m:FolderShape><t:BaseShape>IdOnly</t:BaseShape>'
                         '<t:AdditionalProperties><t:FieldURI FieldURI="folder:DisplayName"/>'
                         '<t:FieldURI FieldURI="folder:ParentFolderId"/><t:FieldURI FieldURI="folder:FolderClass"/>'
                         '</t:AdditionalProperties></m:FolderShape><m:ParentFolderIds>%s</m:ParentFolderIds></m:FindFolder>'
                         % dist("msgfolderroot", mailbox))
        out = []
        for rm in self.messages(root):
            for f in rm.find("m:RootFolder/t:Folders", NS) or []:
                fid = f.find("t:FolderId", NS)
                pid = f.find("t:ParentFolderId", NS)
                out.append({"id": fid.get("Id"), "parent": pid.get("Id") if pid is not None else "",
                            "name": txt(f, "t:DisplayName"), "class": txt(f, "t:FolderClass"),
                            "kind": f.tag.split("}")[1]})
        return out

    def get_folders(self, names, mailbox=""):
        """{distinguished name: folder id} (missing ones left out)."""
        body = "".join(dist(n, mailbox) for n in names)
        root = self.call('<m:GetFolder><m:FolderShape><t:BaseShape>IdOnly</t:BaseShape></m:FolderShape>'
                         '<m:FolderIds>%s</m:FolderIds></m:GetFolder>' % body)
        out = {}
        k = 0
        for rm in root.iter():
            if rm.tag == q("m:GetFolderResponseMessage"):
                if rm.get("ResponseClass") != "Error":
                    f = rm.find(".//t:FolderId", NS)
                    if f is not None:
                        out[names[k]] = f.get("Id")
                k += 1
        return out

    def create_folder(self, parent_id, name, cls="IPF.Note"):
        root = self.call('<m:CreateFolder><m:ParentFolderId>%s</m:ParentFolderId><m:Folders><t:Folder>'
                         '<t:FolderClass>%s</t:FolderClass><t:DisplayName>%s</t:DisplayName></t:Folder></m:Folders></m:CreateFolder>'
                         % (fid_xml(parent_id), esc(cls), esc(name)))
        self.messages(root)
        return root.find(".//t:FolderId", NS).get("Id")

    def delete_folder(self, folder_id):
        self.messages(self.call('<m:DeleteFolder DeleteType="MoveToDeletedItems"><m:FolderIds>%s</m:FolderIds></m:DeleteFolder>'
                                % fid_xml(folder_id)))

    def rename_folder(self, folder_id, name):
        self.messages(self.call('<m:UpdateFolder><m:FolderChanges><t:FolderChange>%s<t:Updates><t:SetFolderField>'
                                '<t:FieldURI FieldURI="folder:DisplayName"/><t:Folder><t:DisplayName>%s</t:DisplayName></t:Folder>'
                                '</t:SetFolderField></t:Updates></t:FolderChange></m:FolderChanges></m:UpdateFolder>'
                                % (fid_xml(folder_id), esc(name))))

    # ------------------------------------------------------------ items
    def find_items(self, folder, props=(), page=500):
        """Every item in a folder: [element] with their ids and the asked properties."""
        out = []
        offset = 0
        extra = "".join('<t:FieldURI FieldURI="%s"/>' % p for p in props)
        while True:
            root = self.call('<m:FindItem Traversal="Shallow"><m:ItemShape><t:BaseShape>IdOnly</t:BaseShape>%s</m:ItemShape>'
                             '<m:IndexedPageItemView MaxEntriesReturned="%d" Offset="%d" BasePoint="Beginning"/>'
                             '<m:ParentFolderIds>%s</m:ParentFolderIds></m:FindItem>'
                             % ("<t:AdditionalProperties>%s</t:AdditionalProperties>" % extra if extra else "", page, offset, folder))
            last = True
            got = 0
            for rm in self.messages(root):
                rf = rm.find("m:RootFolder", NS)
                if rf is None:
                    continue
                last = rf.get("IncludesLastItemInRange", "true") == "true"
                for it in rf.find("t:Items", NS) or []:
                    out.append(it)
                    got += 1
            if last or not got:
                return out
            offset += got

    def get_items(self, ids, props=(), mime=False, base="IdOnly"):
        if not ids:
            return []
        extra = "".join('<t:FieldURI FieldURI="%s"/>' % p for p in props)
        root = self.call('<m:GetItem><m:ItemShape><t:BaseShape>%s</t:BaseShape>%s%s</m:ItemShape><m:ItemIds>%s</m:ItemIds></m:GetItem>'
                         % (base, "<t:IncludeMimeContent>true</t:IncludeMimeContent>" if mime else "",
                            "<t:AdditionalProperties>%s</t:AdditionalProperties>" % extra if extra else "",
                            "".join('<t:ItemId Id="%s"/>' % esc(i) for i in ids)))
        out = []
        for rm in root.iter():
            if rm.tag == q("m:GetItemResponseMessage"):
                items = rm.find("m:Items", NS)
                out.append(items[0] if items is not None and len(items) else None)
        return out

    def create_item(self, item_xml, folder=None, disposition="SaveOnly", invitations="SendToNone"):
        attrs = ' MessageDisposition="%s"' % disposition if "<t:Message" in item_xml[:20] or disposition != "SaveOnly" else ""
        if "<t:CalendarItem" in item_xml[:20]:
            attrs = ' SendMeetingInvitations="%s"' % invitations
        root = self.call('<m:CreateItem%s>%s<m:Items>%s</m:Items></m:CreateItem>'
                         % (attrs, "<m:SavedItemFolderId>%s</m:SavedItemFolderId>" % folder if folder else "", item_xml))
        self.messages(root)
        i = root.find(".//t:ItemId", NS)
        return (i.get("Id"), i.get("ChangeKey")) if i is not None else (None, None)

    def update_item(self, item_id, change_key, updates, invitations="SendToNone"):
        extra = ' SendMeetingInvitationsOrCancellations="%s"' % invitations
        root = self.call('<m:UpdateItem ConflictResolution="AlwaysOverwrite" MessageDisposition="SaveOnly"%s><m:ItemChanges>'
                         '<t:ItemChange><t:ItemId Id="%s"%s/><t:Updates>%s</t:Updates></t:ItemChange></m:ItemChanges></m:UpdateItem>'
                         % (extra, esc(item_id), ' ChangeKey="%s"' % esc(change_key) if change_key else "", updates))
        self.messages(root)
        i = root.find(".//t:ItemId", NS)
        return (i.get("Id"), i.get("ChangeKey")) if i is not None else (item_id, change_key)

    def delete_items(self, ids, how="HardDelete", cancellations="SendToNone"):
        if not ids:
            return
        self.messages(self.call('<m:DeleteItem DeleteType="%s" SendMeetingCancellations="%s" AffectedTaskOccurrences="AllOccurrences">'
                                '<m:ItemIds>%s</m:ItemIds></m:DeleteItem>'
                                % (how, cancellations, "".join('<t:ItemId Id="%s"/>' % esc(i) for i in ids))))

    def move_items(self, ids, folder_id):
        root = self.call('<m:MoveItem><m:ToFolderId>%s</m:ToFolderId><m:ItemIds>%s</m:ItemIds></m:MoveItem>'
                         % (fid_xml(folder_id), "".join('<t:ItemId Id="%s"/>' % esc(i) for i in ids)))
        self.messages(root)
        return [i.get("Id") for i in root.iterfind(".//t:ItemId", NS)]

    def send_mime(self, raw, save=True):
        """Send a message as it is (its Bcc too: Exchange takes the recipients from it and keeps the Bcc out)."""
        item = '<t:Message><t:MimeContent CharacterSet="UTF-8">%s</t:MimeContent></t:Message>' % base64.b64encode(raw).decode()
        return self.create_item(item, dist("sentitems") if save else None, "SendAndSaveCopy" if save else "SendOnly")

    # ------------------------------------------------------------ Automatic Replies (M3-02)
    def get_oof(self, email):
        root = self.call('<m:GetUserOofSettingsRequest><t:Mailbox><t:Address>%s</t:Address></t:Mailbox>'
                         '</m:GetUserOofSettingsRequest>' % esc(email))
        rm = root.find(".//m:ResponseMessage", NS)
        if rm is not None and rm.get("ResponseClass") == "Error":
            raise EwsError(txt(rm, "m:ResponseCode"), txt(rm, "m:MessageText"))
        o = root.find(".//t:OofSettings", NS)
        state = txt(o, "t:OofState", "Disabled")
        start = parse_time(txt(o, "t:Duration/t:StartTime")) if o is not None and o.find("t:Duration", NS) is not None else None
        end = parse_time(txt(o, "t:Duration/t:EndTime")) if start else None
        return {"state": {"Enabled": "on", "Scheduled": "scheduled"}.get(state, "off"),
                "audience": {"None": "none", "Known": "known"}.get(txt(o, "t:ExternalAudience", "All"), "all"),
                "start": start, "end": end,
                "internal": _strip_html(txt(o, "t:InternalReply/t:Message")),
                "external": _strip_html(txt(o, "t:ExternalReply/t:Message"))}

    def set_oof(self, email, s):
        state = {"on": "Enabled", "scheduled": "Scheduled"}.get(s["state"], "Disabled")
        dur = ""
        if s.get("start") and s.get("end"):
            dur = "<t:Duration><t:StartTime>%s</t:StartTime><t:EndTime>%s</t:EndTime></t:Duration>" % (fmt_time(s["start"]), fmt_time(s["end"]))
        aud = {"none": "None", "known": "Known"}.get(s.get("audience", "all"), "All")
        body = ('<m:SetUserOofSettingsRequest><t:Mailbox><t:Address>%s</t:Address></t:Mailbox><t:UserOofSettings>'
                '<t:OofState>%s</t:OofState><t:ExternalAudience>%s</t:ExternalAudience>%s'
                '<t:InternalReply><t:Message>%s</t:Message></t:InternalReply>'
                '<t:ExternalReply><t:Message>%s</t:Message></t:ExternalReply></t:UserOofSettings></m:SetUserOofSettingsRequest>'
                % (esc(email), state, aud, dur, esc(s.get("internal", "")), esc(s.get("external", s.get("internal", "")))))
        root = self.call(body)
        rm = root.find(".//m:ResponseMessage", NS)
        if rm is not None and rm.get("ResponseClass") == "Error":
            raise EwsError(txt(rm, "m:ResponseCode"), txt(rm, "m:MessageText"))

    # ------------------------------------------------------------ free/busy (M3-03)
    def availability(self, emails, start, end):
        """{email: [(start, end, status)]} with status free/tentative/busy/oof."""
        boxes = "".join('<t:MailboxData><t:Email><t:Address>%s</t:Address></t:Email><t:AttendeeType>Required</t:AttendeeType>'
                        '<t:ExcludeConflicts>false</t:ExcludeConflicts></t:MailboxData>' % esc(e) for e in emails)
        body = ('<m:GetUserAvailabilityRequest><t:TimeZone><t:Bias>0</t:Bias><t:StandardTime><t:Bias>0</t:Bias><t:Time>00:00:00</t:Time>'
                '<t:DayOrder>1</t:DayOrder><t:Month>1</t:Month><t:DayOfWeek>Sunday</t:DayOfWeek></t:StandardTime>'
                '<t:DaylightTime><t:Bias>0</t:Bias><t:Time>00:00:00</t:Time><t:DayOrder>1</t:DayOrder><t:Month>1</t:Month>'
                '<t:DayOfWeek>Sunday</t:DayOfWeek></t:DaylightTime></t:TimeZone><m:MailboxDataArray>%s</m:MailboxDataArray>'
                '<t:FreeBusyViewOptions><t:TimeWindow><t:StartTime>%s</t:StartTime><t:EndTime>%s</t:EndTime></t:TimeWindow>'
                '<t:MergedFreeBusyIntervalInMinutes>30</t:MergedFreeBusyIntervalInMinutes><t:RequestedView>Detailed</t:RequestedView>'
                '</t:FreeBusyViewOptions></m:GetUserAvailabilityRequest>'
                % (boxes, fmt_time(start, naive=True), fmt_time(end, naive=True)))
        root = self.call(body)
        out = {}
        for e, fr in zip(emails, root.iterfind(".//m:FreeBusyResponse", NS)):
            rm = fr.find("m:ResponseMessage", NS)
            if rm is not None and rm.get("ResponseClass") == "Error":
                out[e] = None
                continue
            slots = []
            for ev in fr.iterfind(".//t:CalendarEvent", NS):
                st = {"Free": "free", "Tentative": "tentative", "OOF": "oof", "NoData": "free"}.get(txt(ev, "t:BusyType"), "busy")
                slots.append((parse_time(txt(ev, "t:StartTime")), parse_time(txt(ev, "t:EndTime")), st))
            out[e] = slots
        return out

    # ------------------------------------------------------------ delegates (M3-04)
    def get_delegates(self, email):
        root = self.call('<m:GetDelegate IncludePermissions="true"><m:Mailbox><t:EmailAddress>%s</t:EmailAddress></m:Mailbox>'
                         '</m:GetDelegate>' % esc(email))
        out = []
        for du in root.iterfind(".//m:DelegateUser", NS):
            out.append({"email": txt(du, "t:UserId/t:PrimarySmtpAddress"), "name": txt(du, "t:UserId/t:DisplayName"),
                        "calendar": txt(du, "t:DelegatePermissions/t:CalendarFolderPermissionLevel", "None"),
                        "tasks": txt(du, "t:DelegatePermissions/t:TasksFolderPermissionLevel", "None"),
                        "inbox": txt(du, "t:DelegatePermissions/t:InboxFolderPermissionLevel", "None")})
        return out

    def add_delegate(self, email, who, calendar="Editor", tasks="None", inbox="None", update=False):
        op = "UpdateDelegate" if update else "AddDelegate"
        root = self.call('<m:%s><m:Mailbox><t:EmailAddress>%s</t:EmailAddress></m:Mailbox><m:DelegateUsers><t:DelegateUser>'
                         '<t:UserId><t:PrimarySmtpAddress>%s</t:PrimarySmtpAddress></t:UserId><t:DelegatePermissions>'
                         '<t:CalendarFolderPermissionLevel>%s</t:CalendarFolderPermissionLevel>'
                         '<t:TasksFolderPermissionLevel>%s</t:TasksFolderPermissionLevel>'
                         '<t:InboxFolderPermissionLevel>%s</t:InboxFolderPermissionLevel></t:DelegatePermissions>'
                         '<t:ReceiveCopiesOfMeetingMessages>false</t:ReceiveCopiesOfMeetingMessages>'
                         '<t:ViewPrivateItems>false</t:ViewPrivateItems></t:DelegateUser></m:DelegateUsers>'
                         '<m:DeliverMeetingRequests>DelegatesAndMe</m:DeliverMeetingRequests></m:%s>'
                         % (op, esc(email), esc(who), calendar, tasks, inbox, op))
        self.messages(root)

    def remove_delegate(self, email, who):
        root = self.call('<m:RemoveDelegate><m:Mailbox><t:EmailAddress>%s</t:EmailAddress></m:Mailbox><m:UserIds><t:UserId>'
                         '<t:PrimarySmtpAddress>%s</t:PrimarySmtpAddress></t:UserId></m:UserIds></m:RemoveDelegate>'
                         % (esc(email), esc(who)))
        self.messages(root)

    def resolve(self, text):
        """[(name, email)] from the organisation's address list (Check Names)."""
        root = self.call('<m:ResolveNames ReturnFullContactData="false"><m:UnresolvedEntry>%s</m:UnresolvedEntry></m:ResolveNames>'
                         % esc(text))
        out = []
        for r in root.iterfind(".//t:Resolution", NS):
            out.append((txt(r, "t:Mailbox/t:Name"), txt(r, "t:Mailbox/t:EmailAddress")))
        return out


def dist(name, mailbox=""):
    mb = "<t:Mailbox><t:EmailAddress>%s</t:EmailAddress></t:Mailbox>" % esc(mailbox) if mailbox else ""
    return '<t:DistinguishedFolderId Id="%s">%s</t:DistinguishedFolderId>' % (name, mb)


def fid_xml(fid):
    if fid in DIST_NAMES:
        return dist(fid)
    return '<t:FolderId Id="%s"/>' % esc(fid)


DIST_NAMES = ("inbox", "drafts", "sentitems", "deleteditems", "junkemail", "outbox", "archive", "calendar", "contacts", "tasks",
              "msgfolderroot", "notes", "journal")
ROLES = {"inbox": "inbox", "drafts": "drafts", "sentitems": "sent", "deleteditems": "trash", "junkemail": "junk",
         "archive": "archive"}


def parse_time(s):
    if not s:
        return None
    s = s.strip()
    try:
        if s.endswith("Z"):
            return dt.datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc)
        if re.search(r"[+-]\d\d:\d\d$", s):
            return dt.datetime.fromisoformat(s[:19] + s[-6:])
        if "T" in s:
            return dt.datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc)
        return dt.datetime.strptime(s[:10], "%Y-%m-%d").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def fmt_time(d, naive=False):
    if isinstance(d, (int, float)):
        d = dt.datetime.fromtimestamp(d, dt.timezone.utc)
    if not isinstance(d, dt.datetime):
        d = dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc)
    if d.tzinfo is None:
        d = d.astimezone()
    d = d.astimezone(dt.timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S") + ("" if naive else "Z")


def _strip_html(s):
    if "<" not in (s or ""):
        return s or ""
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    import html
    return html.unescape(s).strip()


# ---------------------------------------------------------------- sign-in and finding the server
def autodiscover(email, password=None, user=None, timeout=15):
    """The EWS address for an e-mail address (Autodiscover, the plain-XML kind), or None."""
    dom = email.split("@")[-1]
    req = ('<?xml version="1.0" encoding="utf-8"?><Autodiscover xmlns="http://schemas.microsoft.com/exchange/autodiscover/'
           'outlook/requestschema/2006"><Request><EMailAddress>%s</EMailAddress><AcceptableResponseSchema>http://schemas.'
           'microsoft.com/exchange/autodiscover/outlook/responseschema/2006a</AcceptableResponseSchema></Request></Autodiscover>'
           % esc(email))
    import urllib.request
    for url in ("https://%s/autodiscover/autodiscover.xml" % dom, "https://autodiscover.%s/autodiscover/autodiscover.xml" % dom):
        try:
            r = urllib.request.Request(url, data=req.encode(), headers={"Content-Type": "text/xml"})
            if password is not None:
                r.add_header("Authorization", "Basic " + base64.b64encode(("%s:%s" % (user or email, password)).encode()).decode())
            with urllib.request.urlopen(r, timeout=timeout) as resp:
                data = resp.read().decode("utf-8", "replace")
            m = re.search(r"<EwsUrl>([^<]+)</EwsUrl>", data) or re.search(r"<ASUrl>([^<]+)</ASUrl>", data)
            if m:
                return m.group(1).strip()
        except Exception:
            continue
    return None


def client_for(acc, secrets, tokens, mailbox=""):
    cfg = acc["config"]
    url = cfg.get("ews_url") or OFFICE365
    if cfg.get("auth") in ("oauth", "goa"):
        return Client(url, cfg.get("user", acc["email"]), token=lambda: tokens(acc), auth="bearer",
                      insecure=cfg.get("insecure", False))
    pw = secrets.get(acc["id"]) or cfg.get("password", "")
    return Client(url, cfg.get("user", acc["email"]), pw, auth=cfg.get("ews_auth", "basic"), insecure=cfg.get("insecure", False))


# ---------------------------------------------------------------- mail, as the sync sees it
class Mail:
    """An Exchange mailbox with the same face as imap.Imap: folder paths, numbered messages, flags.
    The numbers stand for Exchange's item ids and are kept in the store."""

    def __init__(self, client, store, aid):
        self.c = client
        self.db = store
        self.aid = aid
        self.paths = {}          # path -> folder id
        self.cur = None
        self.cache = {}          # uid -> (id, change key, flags)
        self.deleted = set()

    # the numbering, kept per account
    def _map(self, path):
        return self.db.get("ews-map:%d:%s" % (self.aid, path), {}) or {"next": 1, "ids": {}}

    def _save_map(self, path, m):
        self.db.put("ews-map:%d:%s" % (self.aid, path), m)

    def connect(self, *_a):
        return self

    def close(self):
        self.c.close()

    def folders(self):
        """[(path, delim, role, raw, virtual)] for every mail folder."""
        names = list(ROLES)
        roles = self.c.get_folders(names)
        by_id = {v: ROLES[k] for k, v in roles.items()}
        fs = self.c.find_folders()
        info = {f["id"]: f for f in fs}
        root_ids = set(f["parent"] for f in fs if f["parent"] not in info)
        out = []
        for f in fs:
            if f["kind"] not in ("Folder",) or (f["class"] and not f["class"].startswith("IPF.Note")):
                continue
            parts = [f["name"]]
            p = f["parent"]
            n = 0
            while p in info and n < 20:
                parts.insert(0, info[p]["name"])
                p = info[p]["parent"]
                n += 1
            if p not in root_ids:
                continue
            path = "/".join(x.replace("/", "-") for x in parts)
            self.paths[path] = f["id"]
            out.append((path, "/", by_id.get(f["id"], ""), f, False))
        return out

    def _fid(self, path):
        if path not in self.paths:
            self.folders()
        if path not in self.paths:
            raise EwsError("ErrorFolderNotFound", path)
        return self.paths[path]

    def select(self, path, readonly=False):
        self.cur = path
        fid = self._fid(path)
        m = self._map(path)
        items = self.c.find_items(fid_xml(fid), ("message:IsRead", "item:Flag", "item:DateTimeReceived",
                                                 "message:IsReadReceiptRequested"))
        seen_ids = set()
        self.cache = {}
        changed = False
        for it in items:
            i = it.find("t:ItemId", NS)
            iid = i.get("Id")
            seen_ids.add(iid)
            if iid not in m["ids"]:
                m["ids"][iid] = m["next"]
                m["next"] += 1
                changed = True
            flags = set()
            if txt(it, "t:IsRead", "false") == "true":
                flags.add("\\seen")
            if txt(it, "t:Flag/t:FlagStatus") == "Flagged":
                flags.add("\\flagged")
            self.cache[m["ids"][iid]] = (iid, i.get("ChangeKey"), flags)
        for iid in [k for k in m["ids"] if k not in seen_ids]:
            del m["ids"][iid]
            changed = True
        if changed:
            self._save_map(path, m)
        return 1, m["next"], len(items)

    def all_uids(self):
        return sorted(self.cache)

    def uids(self, since_uid=1):
        return [u for u in self.all_uids() if u >= since_uid]

    def flags(self, uids):
        return {u: self.cache[u][2] for u in uids if u in self.cache}

    def fetch(self, uids):
        ids = [self.cache[u][0] for u in uids if u in self.cache]
        items = self.c.get_items(ids, ("item:DateTimeReceived", "message:IsRead", "item:Flag"), mime=True)
        out = []
        for u, it in zip([u for u in uids if u in self.cache], items):
            if it is None:
                continue
            mc = it.find("t:MimeContent", NS)
            if mc is None or not mc.text:
                continue
            raw = base64.b64decode(mc.text)
            when = parse_time(txt(it, "t:DateTimeReceived"))
            out.append((u, self.cache[u][2], when.timestamp() if when else None, raw))
        return out

    def store(self, uids, flags, add=True):
        for u in uids:
            if u not in self.cache:
                continue
            iid, ck, fl = self.cache[u]
            ups = []
            for f in flags:
                f = f.lower()
                if f == "\\seen":
                    ups.append(set_field("message:IsRead", "<t:Message><t:IsRead>%s</t:IsRead></t:Message>" % ("true" if add else "false")))
                elif f == "\\flagged":
                    ups.append(set_field("item:Flag", "<t:Message><t:Flag><t:FlagStatus>%s</t:FlagStatus></t:Flag></t:Message>"
                                         % ("Flagged" if add else "NotFlagged")))
                elif f == "\\answered" and add:
                    # PR_LAST_VERB_EXECUTED: 102 = replied
                    ups.append('<t:SetItemField><t:ExtendedFieldURI PropertyTag="0x1081" PropertyType="Integer"/><t:Message>'
                               '<t:ExtendedProperty><t:ExtendedFieldURI PropertyTag="0x1081" PropertyType="Integer"/>'
                               '<t:Value>102</t:Value></t:ExtendedProperty></t:Message></t:SetItemField>')
                elif f == "\\deleted":
                    self.deleted.add(u)
            if ups:
                iid, ck = self.c.update_item(iid, ck, "".join(ups))
                nf = set(fl)
                for f in flags:
                    (nf.add if add else nf.discard)(f.lower())
                self.cache[u] = (iid, ck, nf)

    def expunge(self, uids=None):
        gone = [u for u in (uids or list(self.deleted)) if u in self.cache]
        ids = [self.cache[u][0] for u in gone]
        if ids:
            self.c.delete_items(ids, "HardDelete")
        m = self._map(self.cur)
        for u in gone:
            iid = self.cache.pop(u)[0]
            m["ids"].pop(iid, None)
            self.deleted.discard(u)
        self._save_map(self.cur, m)

    def append(self, path, raw, flags=("\\Seen",)):
        fid = self._fid(path)
        read = any(f.lower() == "\\seen" for f in flags)
        draft = any(f.lower() == "\\draft" for f in flags)
        # PR_MESSAGE_FLAGS: read (1), and not a draft unless it is one (8 = unsent)
        mflags = (1 if read else 0) | (8 if draft else 0)
        item = ('<t:Message><t:MimeContent CharacterSet="UTF-8">%s</t:MimeContent><t:ExtendedProperty>'
                '<t:ExtendedFieldURI PropertyTag="0x0E07" PropertyType="Integer"/><t:Value>%d</t:Value></t:ExtendedProperty>'
                '</t:Message>' % (base64.b64encode(raw).decode(), mflags))
        iid, ck = self.c.create_item(item, fid_xml(fid), "SaveOnly")
        if iid is None:
            return 0
        m = self._map(path)
        u = m["next"]
        m["ids"][iid] = u
        m["next"] += 1
        self._save_map(path, m)
        if self.cur == path:
            self.cache[u] = (iid, ck, {"\\seen"} if read else set())
        return u

    def move(self, uids, path):
        dest = self._fid(path)
        ids = [self.cache[u][0] for u in uids if u in self.cache]
        self.c.move_items(ids, dest)
        self.expunge_local(uids)

    def expunge_local(self, uids):
        m = self._map(self.cur)
        for u in uids:
            if u in self.cache:
                m["ids"].pop(self.cache.pop(u)[0], None)
        self._save_map(self.cur, m)

    def create(self, path):
        parent, _, name = path.rpartition("/")
        pid = self._fid(parent) if parent else "msgfolderroot"
        self.paths[path] = self.c.create_folder(pid, name)

    def delete_folder(self, path):
        self.c.delete_folder(self._fid(path))
        self.paths.pop(path, None)

    def rename(self, old, new):
        self.c.rename_folder(self._fid(old), new.rpartition("/")[2])
        self.paths[new] = self.paths.pop(old)

    def noop(self):
        return True


def set_field(uri, item):
    return '<t:SetItemField><t:FieldURI FieldURI="%s"/>%s</t:SetItemField>' % (uri, item)


def delete_field(uri):
    return '<t:DeleteItemField><t:FieldURI FieldURI="%s"/></t:DeleteItemField>' % uri


# ---------------------------------------------------------------- calendar
WIN_OF = {v: k for k, v in __import__("folio_post.ical", fromlist=["WINDOWS_TZ"]).WINDOWS_TZ.items()}
WEEKDAY = {"MO": "Monday", "TU": "Tuesday", "WE": "Wednesday", "TH": "Thursday", "FR": "Friday", "SA": "Saturday", "SU": "Sunday"}
FREEBUSY = {"busy": "Busy", "free": "Free", "tentative": "Tentative", "oof": "OOF"}
CAL_PROPS = ("item:Subject", "item:Body", "calendar:Start", "calendar:End", "calendar:IsAllDayEvent", "calendar:Location",
             "calendar:UID", "calendar:LegacyFreeBusyStatus", "item:ReminderIsSet", "item:ReminderMinutesBeforeStart",
             "calendar:Organizer", "calendar:RequiredAttendees", "calendar:OptionalAttendees", "item:Categories")


def _recurrence_xml(rule, start):
    """An RRULE as EWS's Recurrence (the patterns Outlook offers)."""
    from . import ical
    r = ical.parse_rrule(rule) if isinstance(rule, str) else rule
    freq = r.get("FREQ", "")
    n = int(r.get("INTERVAL", "1") or 1)
    days = [WEEKDAY[d[-2:]] for d in r.get("BYDAY", "").split(",") if d[-2:] in WEEKDAY]
    if freq == "DAILY":
        pat = "<t:DailyRecurrence><t:Interval>%d</t:Interval></t:DailyRecurrence>" % n
    elif freq == "WEEKLY":
        days = days or [WEEKDAY[["MO", "TU", "WE", "TH", "FR", "SA", "SU"][start.weekday()]]]
        pat = "<t:WeeklyRecurrence><t:Interval>%d</t:Interval><t:DaysOfWeek>%s</t:DaysOfWeek></t:WeeklyRecurrence>" % (n, " ".join(days))
    elif freq == "MONTHLY":
        bd = r.get("BYDAY", "")
        m = re.match(r"^(-?\d)([A-Z]{2})$", bd)
        if m:
            idx = {"1": "First", "2": "Second", "3": "Third", "4": "Fourth", "-1": "Last"}.get(m.group(1), "First")
            pat = ("<t:RelativeMonthlyRecurrence><t:Interval>%d</t:Interval><t:DaysOfWeek>%s</t:DaysOfWeek>"
                   "<t:DayOfWeekIndex>%s</t:DayOfWeekIndex></t:RelativeMonthlyRecurrence>" % (n, WEEKDAY[m.group(2)], idx))
        else:
            pat = ("<t:AbsoluteMonthlyRecurrence><t:Interval>%d</t:Interval><t:DayOfMonth>%d</t:DayOfMonth></t:AbsoluteMonthlyRecurrence>"
                   % (n, int(r.get("BYMONTHDAY", start.day) or start.day)))
    elif freq == "YEARLY":
        pat = ("<t:AbsoluteYearlyRecurrence><t:DayOfMonth>%d</t:DayOfMonth><t:Month>%s</t:Month></t:AbsoluteYearlyRecurrence>"
               % (start.day, start.strftime("%B")))
    else:
        return ""
    sd = start.strftime("%Y-%m-%d")
    if r.get("COUNT"):
        rng = "<t:NumberedRecurrence><t:StartDate>%s</t:StartDate><t:NumberOfOccurrences>%s</t:NumberOfOccurrences></t:NumberedRecurrence>" % (sd, r["COUNT"])
    elif r.get("UNTIL"):
        u = r["UNTIL"]
        rng = "<t:EndDateRecurrence><t:StartDate>%s</t:StartDate><t:EndDate>%s-%s-%s</t:EndDate></t:EndDateRecurrence>" % (sd, u[:4], u[4:6], u[6:8])
    else:
        rng = "<t:NoEndRecurrence><t:StartDate>%s</t:StartDate></t:NoEndRecurrence>" % sd
    return "<t:Recurrence>%s%s</t:Recurrence>" % (pat, rng)


def _rrule_of(rec, start):
    """EWS's Recurrence element as an RRULE string."""
    if rec is None or not len(rec):
        return ""
    pat = rec[0]
    tag = pat.tag.split("}")[1]
    n = txt(pat, "t:Interval", "1")
    inv = {v: k for k, v in WEEKDAY.items()}
    days = ",".join(inv[d] for d in txt(pat, "t:DaysOfWeek").split() if d in inv)
    if tag == "DailyRecurrence":
        r = "FREQ=DAILY;INTERVAL=%s" % n
    elif tag == "WeeklyRecurrence":
        r = "FREQ=WEEKLY;INTERVAL=%s;BYDAY=%s" % (n, days)
    elif tag == "AbsoluteMonthlyRecurrence":
        r = "FREQ=MONTHLY;INTERVAL=%s;BYMONTHDAY=%s" % (n, txt(pat, "t:DayOfMonth"))
    elif tag == "RelativeMonthlyRecurrence":
        idx = {"First": "1", "Second": "2", "Third": "3", "Fourth": "4", "Last": "-1"}.get(txt(pat, "t:DayOfWeekIndex"), "1")
        r = "FREQ=MONTHLY;INTERVAL=%s;BYDAY=%s%s" % (n, idx, days)
    elif tag in ("AbsoluteYearlyRecurrence", "RelativeYearlyRecurrence"):
        r = "FREQ=YEARLY"
    else:
        return ""
    rng = rec[1] if len(rec) > 1 else None
    if rng is not None:
        rt = rng.tag.split("}")[1]
        if rt == "NumberedRecurrence":
            r += ";COUNT=%s" % txt(rng, "t:NumberOfOccurrences")
        elif rt == "EndDateRecurrence":
            r += ";UNTIL=%sT235959Z" % txt(rng, "t:EndDate")[:10].replace("-", "")
    return r


def _attendees_xml(tag, people):
    if not people:
        return ""
    return "<t:%s>%s</t:%s>" % (tag, "".join("<t:Attendee><t:Mailbox><t:Name>%s</t:Name><t:EmailAddress>%s</t:EmailAddress>"
                                               "</t:Mailbox></t:Attendee>" % (esc(n), esc(e)) for n, e in people), tag)


def event_fields(ics):
    """[(field URI, element)] for an event's master, in the order EWS wants them in a CalendarItem."""
    from . import ical
    cal = ical.parse(ics)
    evs = [e for e in ical.events_of(cal) if not e.recurrence_id] or ical.events_of(cal)
    e = evs[0]
    start, end, all_day = e.start, e.end, e.all_day
    rem = e.reminder
    req = [(a["name"], a["email"]) for a in e.attendees if a["role"] != "OPT-PARTICIPANT"]
    opt = [(a["name"], a["email"]) for a in e.attendees if a["role"] == "OPT-PARTICIPANT"]
    tzname = ""
    if all_day:
        lt = ical.local_tz() or dt.timezone.utc
        tzname = WIN_OF.get(getattr(lt, "key", ""), "UTC")
        start = dt.datetime(start.year, start.month, start.day, tzinfo=lt)
        end = dt.datetime(end.year, end.month, end.day, tzinfo=lt)
    cats = "".join("<t:String>%s</t:String>" % esc(c) for c in e.categories)
    f = [("item:Subject", "<t:Subject>%s</t:Subject>" % esc(e.summary)),
         ("item:Body", '<t:Body BodyType="Text">%s</t:Body>' % esc(e.description))]
    if cats:
        f.append(("item:Categories", "<t:Categories>%s</t:Categories>" % cats))
    f.append(("item:ReminderIsSet", "<t:ReminderIsSet>%s</t:ReminderIsSet>" % ("true" if rem is not None else "false")))
    if rem is not None:
        f.append(("item:ReminderMinutesBeforeStart", "<t:ReminderMinutesBeforeStart>%d</t:ReminderMinutesBeforeStart>" % rem))
    f.append(("calendar:UID", "<t:UID>%s</t:UID>" % esc(e.uid)))
    f.append(("calendar:Start", "<t:Start>%s</t:Start>" % fmt_time(start)))
    f.append(("calendar:End", "<t:End>%s</t:End>" % fmt_time(end)))
    f.append(("calendar:IsAllDayEvent", "<t:IsAllDayEvent>%s</t:IsAllDayEvent>" % ("true" if all_day else "false")))
    f.append(("calendar:LegacyFreeBusyStatus", "<t:LegacyFreeBusyStatus>%s</t:LegacyFreeBusyStatus>" % FREEBUSY.get(e.busy, "Busy")))
    f.append(("calendar:Location", "<t:Location>%s</t:Location>" % esc(e.location)))
    if req:
        f.append(("calendar:RequiredAttendees", _attendees_xml("RequiredAttendees", req)))
    if opt:
        f.append(("calendar:OptionalAttendees", _attendees_xml("OptionalAttendees", opt)))
    if e.rrule:
        f.append(("calendar:Recurrence", _recurrence_xml(e.rrule, start)))
    if tzname:
        f.append(("calendar:StartTimeZone", '<t:StartTimeZone Id="%s"/>' % esc(tzname)))
    return [x for x in f if x[1]]


def event_item_xml(ics):
    return "<t:CalendarItem>%s</t:CalendarItem>" % "".join(x for _u, x in event_fields(ics))


def event_updates(ics):
    f = event_fields(ics)
    out = [set_field(u, "<t:CalendarItem>%s</t:CalendarItem>" % x) for u, x in f if u != "calendar:UID"]
    have = set(u for u, _x in f)
    for u in ("calendar:Recurrence", "calendar:RequiredAttendees", "calendar:OptionalAttendees", "item:Categories"):
        if u not in have:
            out.append(delete_field(u))
    return "".join(out)


def ics_of_item(it):
    """An event's iCalendar, from Exchange's own MIME content when it gives one, else from its fields."""
    from . import ical
    mc = it.find("t:MimeContent", NS)
    if mc is not None and mc.text:
        try:
            text = base64.b64decode(mc.text).decode("utf-8", "replace")
            i = text.find("BEGIN:VCALENDAR")
            if i >= 0:
                text = text[i:text.rfind("END:VCALENDAR") + len("END:VCALENDAR")] + "\r\n"
                cal = ical.parse(text)
                if cal is not None and ical.events_of(cal):
                    return text
        except Exception:
            pass
    start = parse_time(txt(it, "t:Start"))
    end = parse_time(txt(it, "t:End")) or start
    all_day = txt(it, "t:IsAllDayEvent") == "true"
    if all_day and start:
        lt = ical.local_tz() or dt.timezone.utc
        start, end = start.astimezone(lt).date(), end.astimezone(lt).date()
    rem = int(txt(it, "t:ReminderMinutesBeforeStart", "15") or 15) if txt(it, "t:ReminderIsSet") == "true" else None
    rec = it.find("t:Recurrence", NS)
    rule = _rrule_of(rec, start)
    ev = ical.new_event(txt(it, "t:Subject"), start, end, all_day, txt(it, "t:Location"), _strip_html(txt(it, "t:Body")),
                        rule, rem)
    uid = txt(it, "t:UID") or it.find("t:ItemId", NS).get("Id")
    ev.comp.set("UID", uid)
    fb = {v: k for k, v in FREEBUSY.items()}.get(txt(it, "t:LegacyFreeBusyStatus"), "busy")
    if fb != "busy":
        ev.set_busy(fb)
    people = []
    for tag, role in (("t:RequiredAttendees", "REQ-PARTICIPANT"), ("t:OptionalAttendees", "OPT-PARTICIPANT")):
        for a in it.iterfind(tag + "/t:Attendee", NS):
            people.append({"name": txt(a, "t:Mailbox/t:Name"), "email": txt(a, "t:Mailbox/t:EmailAddress"), "role": role})
    if people:
        org = it.find("t:Organizer/t:Mailbox", NS)
        ev.set_attendees(people, (txt(org, "t:Name"), txt(org, "t:EmailAddress")) if org is not None else None)
    cats = [c.text for c in it.iterfind("t:Categories/t:String", NS) if c.text]
    if cats:
        ev.comp.set("CATEGORIES", ",".join(ical.escape(c) for c in cats))
    return ical.dumps(ical.calendar_of([ev]))


def sync_calendar(store, c, cal):
    """Two-way sync of one Exchange calendar (events.href = item id, events.etag = change key)."""
    from .caldav import summary_of
    src = store.get("ews-cal:%d" % cal["id"], {}) or {}
    folder = fid_xml(src["folder"]) if src.get("folder") else dist("calendar", src.get("mailbox", ""))
    cid = cal["id"]
    for e in store.events(cid, with_deleted=True):
        p = e["pending"]
        if not p or cal["readonly"]:
            continue
        try:
            if p == "deleted":
                if e["href"]:
                    c.delete_items([e["href"]], "MoveToDeletedItems")
                store.drop_event(e["id"])
            elif p == "new":
                iid, ck = c.create_item(event_item_xml(e["ics"]), folder)
                store.set_event_fields(e["id"], href=iid, etag=ck, pending="")
            else:
                iid, ck = c.update_item(e["href"], e["etag"], event_updates(e["ics"]))
                store.set_event_fields(e["id"], href=iid, etag=ck, pending="")
        except EwsError as err:
            if err.code in ("ErrorItemNotFound", "ErrorIrresolvableConflict"):
                store.set_event_fields(e["id"], pending="", etag="conflict")
            else:
                raise
    remote = {}
    for it in c.find_items(folder, ()):
        i = it.find("t:ItemId", NS)
        remote[i.get("Id")] = i.get("ChangeKey")
    local = {e["href"]: e for e in store.events(cid, with_deleted=True) if e["href"]}
    for href, e in local.items():
        if href not in remote and not e["pending"]:
            store.drop_event(e["id"])
    want = [h for h, ck in remote.items() if h not in local or local[h]["etag"] != ck]
    for k in range(0, len(want), 50):
        chunk = want[k:k + 50]
        for href, it in zip(chunk, c.get_items(chunk, CAL_PROPS + ("calendar:Recurrence",), mime=True)):
            if it is None:
                continue
            ics = ics_of_item(it)
            uid, s, st, un = summary_of(ics)
            old = local.get(href)
            if old and old["pending"]:
                continue
            store.put_event(cid, uid, ics, href, it.find("t:ItemId", NS).get("ChangeKey"), "", s, st, un,
                            old["id"] if old else None)
    store.update_calendar(cid, ctag=str(int(time.time())))


# ---------------------------------------------------------------- contacts
CONTACT_PROPS = ("item:Subject", "contacts:DisplayName", "contacts:GivenName", "contacts:Surname", "contacts:CompanyName",
                 "contacts:Department", "contacts:JobTitle", "contacts:EmailAddresses", "contacts:PhoneNumbers",
                 "contacts:PhysicalAddresses", "item:Body", "contacts:Birthday", "item:Categories")
PHONE_KEYS = [("work", "BusinessPhone"), ("cell", "MobilePhone"), ("home", "HomePhone"), ("fax", "BusinessFax"), ("other", "OtherTelephone")]
ADDR_KEYS = [("work", "Business"), ("home", "Home"), ("other", "Other")]


def contact_fields(k):
    """([(field URI, element)], indexed updates) for a contact or a contact group."""
    if k.is_group:
        members = "".join("<t:Member><t:Mailbox><t:EmailAddress>%s</t:EmailAddress></t:Mailbox></t:Member>" % esc(e)
                          for e in k.member_emails())
        return [("contacts:DisplayName", "<t:DisplayName>%s</t:DisplayName>" % esc(k.name)),
                ("distributionlist:Members", "<t:Members>%s</t:Members>" % members if members else "")], []
    fam, giv = k.n[0], k.n[1]
    emails = [("EmailAddress%d" % (i + 1), a) for i, (_t, a) in enumerate(k.emails[:3])]
    phones = []
    for kind, num in k.phones:
        key = dict(PHONE_KEYS).get(kind, "OtherTelephone")
        if key not in [p[0] for p in phones]:
            phones.append((key, num))
    addrs = []
    for kind, a in k.addresses:
        key = dict(ADDR_KEYS).get(kind, "Other")
        if key not in [x[0] for x in addrs]:
            addrs.append((key, [("Street", a["street"]), ("City", a["city"]), ("State", a["region"]),
                                ("CountryOrRegion", a["country"]), ("PostalCode", a["postal"])]))
    b = re.sub(r"\D", "", k.birthday or "")
    cats = "".join("<t:String>%s</t:String>" % esc(c) for c in k.categories)
    f = [("item:Body", '<t:Body BodyType="Text">%s</t:Body>' % esc(k.note)),
         ("item:Categories", "<t:Categories>%s</t:Categories>" % cats if cats else ""),
         ("contacts:DisplayName", "<t:DisplayName>%s</t:DisplayName>" % esc(k.name)),
         ("contacts:GivenName", "<t:GivenName>%s</t:GivenName>" % esc(giv)),
         ("contacts:CompanyName", "<t:CompanyName>%s</t:CompanyName>" % esc(k.company)),
         ("contacts:EmailAddresses", "<t:EmailAddresses>%s</t:EmailAddresses>" % "".join(
             '<t:Entry Key="%s">%s</t:Entry>' % (kk, esc(v)) for kk, v in emails) if emails else ""),
         ("contacts:PhysicalAddresses", "<t:PhysicalAddresses>%s</t:PhysicalAddresses>" % "".join(
             '<t:Entry Key="%s">%s</t:Entry>' % (kk, "".join("<t:%s>%s</t:%s>" % (n, esc(v), n) for n, v in parts))
             for kk, parts in addrs) if addrs else ""),
         ("contacts:PhoneNumbers", "<t:PhoneNumbers>%s</t:PhoneNumbers>" % "".join(
             '<t:Entry Key="%s">%s</t:Entry>' % (kk, esc(v)) for kk, v in phones) if phones else ""),
         ("contacts:Birthday", "<t:Birthday>%s-%s-%sT12:00:00Z</t:Birthday>" % (b[:4], b[4:6], b[6:8]) if len(b) >= 8 else ""),
         ("contacts:Department", "<t:Department>%s</t:Department>" % esc(k.department)),
         ("contacts:JobTitle", "<t:JobTitle>%s</t:JobTitle>" % esc(k.title)),
         ("contacts:Surname", "<t:Surname>%s</t:Surname>" % esc(fam))]
    indexed = []
    for kk, v in emails:
        indexed.append('<t:SetItemField><t:IndexedFieldURI FieldURI="contacts:EmailAddress" FieldIndex="%s"/><t:Contact>'
                       '<t:EmailAddresses><t:Entry Key="%s">%s</t:Entry></t:EmailAddresses></t:Contact></t:SetItemField>'
                       % (kk, kk, esc(v)))
    for kk, v in phones:
        indexed.append('<t:SetItemField><t:IndexedFieldURI FieldURI="contacts:PhoneNumber" FieldIndex="%s"/><t:Contact>'
                       '<t:PhoneNumbers><t:Entry Key="%s">%s</t:Entry></t:PhoneNumbers></t:Contact></t:SetItemField>'
                       % (kk, kk, esc(v)))
    for kk, parts in addrs:
        for n, v in parts:
            indexed.append('<t:SetItemField><t:IndexedFieldURI FieldURI="contacts:PhysicalAddress:%s" FieldIndex="%s"/>'
                           '<t:Contact><t:PhysicalAddresses><t:Entry Key="%s"><t:%s>%s</t:%s></t:Entry></t:PhysicalAddresses>'
                           '</t:Contact></t:SetItemField>' % (n, kk, kk, n, esc(v), n))
    return [x for x in f if x[1]], indexed


def contact_item_xml(card):
    from . import vcard
    k = vcard.parse(card) if isinstance(card, str) else card
    tag = "DistributionList" if k.is_group else "Contact"
    f, _i = contact_fields(k)
    return "<t:%s>%s</t:%s>" % (tag, "".join(x for _u, x in f), tag)


def contact_updates(card):
    from . import vcard
    k = vcard.parse(card)
    tag = "DistributionList" if k.is_group else "Contact"
    f, indexed = contact_fields(k)
    out = [set_field(u, "<t:%s>%s</t:%s>" % (tag, x, tag)) for u, x in f
           if u not in ("contacts:EmailAddresses", "contacts:PhoneNumbers", "contacts:PhysicalAddresses")]
    return "".join(out + indexed)


def card_of_item(it, uid_hint=""):
    from . import vcard
    tag = it.tag.split("}")[1]
    if tag == "DistributionList":
        emails = [txt(m, "t:Mailbox/t:EmailAddress") for m in it.iterfind("t:Members/t:Member", NS)]
        k = vcard.new_group(txt(it, "t:DisplayName") or txt(it, "t:Subject"), [e for e in emails if e])
    else:
        name = txt(it, "t:DisplayName") or " ".join(x for x in (txt(it, "t:GivenName"), txt(it, "t:Surname")) if x)
        k = vcard.new_contact(name)
        k.set_name(name, txt(it, "t:GivenName"), txt(it, "t:Surname"))
        em = [("work", e.text) for e in sorted(it.iterfind("t:EmailAddresses/t:Entry", NS), key=lambda e: e.get("Key")) if e.text]
        if em:
            k.set_emails(em)
        inv = {v: kk for kk, v in PHONE_KEYS}
        ph = [(inv.get(e.get("Key"), "other"), e.text) for e in it.iterfind("t:PhoneNumbers/t:Entry", NS) if e.text]
        if ph:
            k.set_phones(ph)
        for e in it.iterfind("t:PhysicalAddresses/t:Entry", NS):
            kind = {v: kk for kk, v in ADDR_KEYS}.get(e.get("Key"), "other")
            k.set_address(kind, {"street": txt(e, "t:Street"), "city": txt(e, "t:City"), "region": txt(e, "t:State"),
                                 "postal": txt(e, "t:PostalCode"), "country": txt(e, "t:CountryOrRegion")})
        if txt(it, "t:CompanyName") or txt(it, "t:Department"):
            k.set_company(txt(it, "t:CompanyName"), txt(it, "t:Department"))
        if txt(it, "t:JobTitle"):
            k.set_text("TITLE", txt(it, "t:JobTitle"))
        note = _strip_html(txt(it, "t:Body"))
        if note:
            k.set_text("NOTE", note)
        b = txt(it, "t:Birthday")
        if b:
            k.comp.set("BDAY", b[:10].replace("-", ""))
    cats = [c.text for c in it.iterfind("t:Categories/t:String", NS) if c.text]
    if cats:
        k.comp.set("CATEGORIES", ",".join(cats))
    k.comp.set("UID", uid_hint or it.find("t:ItemId", NS).get("Id")[-36:])
    return k.dumps()


def sync_book(store, c, book):
    bid = book["id"]
    src = store.get("ews-book:%d" % bid, {}) or {}
    folder = fid_xml(src["folder"]) if src.get("folder") else dist("contacts", src.get("mailbox", ""))
    for ct in store.contacts(bid, with_deleted=True):
        p = ct["pending"]
        if not p or book["readonly"]:
            continue
        try:
            if p == "deleted":
                if ct["href"]:
                    c.delete_items([ct["href"]], "MoveToDeletedItems")
                store.drop_contact(ct["id"])
            elif p == "new":
                iid, ck = c.create_item(contact_item_xml(ct["vcard"]), folder)
                store.set_contact_fields(ct["id"], href=iid, etag=ck, pending="")
            else:
                iid, ck = c.update_item(ct["href"], ct["etag"], contact_updates(ct["vcard"]))
                store.set_contact_fields(ct["id"], href=iid, etag=ck, pending="")
        except EwsError as err:
            if err.code in ("ErrorItemNotFound", "ErrorIrresolvableConflict"):
                store.set_contact_fields(ct["id"], pending="", etag="conflict")
            else:
                raise
    remote = {}
    for it in c.find_items(folder, ()):
        i = it.find("t:ItemId", NS)
        remote[i.get("Id")] = i.get("ChangeKey")
    local = {x["href"]: x for x in store.contacts(bid, with_deleted=True) if x["href"]}
    for href, x in local.items():
        if href not in remote and not x["pending"]:
            store.drop_contact(x["id"])
    want = [h for h, ck in remote.items() if h not in local or local[h]["etag"] != ck]
    for k in range(0, len(want), 50):
        chunk = want[k:k + 50]
        for href, it in zip(chunk, c.get_items(chunk, (), base="AllProperties")):
            if it is None:
                continue
            old = local.get(href)
            if old and old["pending"]:
                continue
            uid = ""
            if old:
                from . import vcard
                uid = vcard.parse(old["vcard"]).uid
            store.put_contact(bid, card_of_item(it, uid), href, it.find("t:ItemId", NS).get("ChangeKey"), "",
                              old["id"] if old else None)
    store.update_book(bid, ctag=str(int(time.time())))


# ---------------------------------------------------------------- tasks
TASK_STATUS = {"NEEDS-ACTION": "NotStarted", "IN-PROCESS": "InProgress", "COMPLETED": "Completed",
               "X-WAITING": "WaitingOnOthers", "X-DEFERRED": "Deferred"}


def task_item_xml(data):
    from . import tasks
    t = tasks.parse(data)
    imp = {1: "High", 9: "Low"}.get(t.priority, "Normal")
    rem = t.reminder
    x = ("<t:Task><t:Subject>%s</t:Subject><t:Body BodyType=\"Text\">%s</t:Body><t:Importance>%s</t:Importance>"
         "%s<t:ReminderIsSet>%s</t:ReminderIsSet>%s%s<t:PercentComplete>%d</t:PercentComplete>%s<t:Status>%s</t:Status></t:Task>"
         % (esc(t.subject), esc(t.notes), imp,
            "<t:ReminderDueBy>%s</t:ReminderDueBy>" % fmt_time(rem) if rem else "", "true" if rem else "false",
            "<t:DueDate>%sT00:00:00Z</t:DueDate>" % t.due.isoformat() if t.due else "",
            "", t.percent, "<t:StartDate>%sT00:00:00Z</t:StartDate>" % t.start.isoformat() if t.start else "",
            TASK_STATUS.get(t.status, "NotStarted")))
    return x


def task_updates(data):
    from . import tasks
    t = tasks.parse(data)
    imp = {1: "High", 9: "Low"}.get(t.priority, "Normal")
    out = [set_field("item:Subject", "<t:Task><t:Subject>%s</t:Subject></t:Task>" % esc(t.subject)),
           set_field("item:Body", "<t:Task><t:Body BodyType=\"Text\">%s</t:Body></t:Task>" % esc(t.notes)),
           set_field("item:Importance", "<t:Task><t:Importance>%s</t:Importance></t:Task>" % imp),
           set_field("task:Status", "<t:Task><t:Status>%s</t:Status></t:Task>" % TASK_STATUS.get(t.status, "NotStarted")),
           set_field("task:PercentComplete", "<t:Task><t:PercentComplete>%d</t:PercentComplete></t:Task>" % t.percent)]
    for name, uri, d in (("DueDate", "task:DueDate", t.due), ("StartDate", "task:StartDate", t.start)):
        out.append(set_field(uri, "<t:Task><t:%s>%sT00:00:00Z</t:%s></t:Task>" % (name, d.isoformat(), name)) if d else delete_field(uri))
    return "".join(out)


def task_of_item(it, uid):
    from . import tasks
    t = tasks.new_task(txt(it, "t:Subject"))
    t.comp.set("UID", uid)
    t.set_notes(_strip_html(txt(it, "t:Body")))
    st = {v: k for k, v in TASK_STATUS.items()}.get(txt(it, "t:Status"), "NEEDS-ACTION")
    t.set_status(st)
    try:
        t.set_percent(float(txt(it, "t:PercentComplete", "0") or 0))
    except ValueError:
        pass
    t.set_priority({"High": 1, "Low": 9}.get(txt(it, "t:Importance"), 5))
    for name, prop in (("t:DueDate", "DUE"), ("t:StartDate", "DTSTART")):
        d = parse_time(txt(it, name))
        if d:
            t.set_date(prop, d.date())
    if txt(it, "t:ReminderIsSet") == "true":
        r = parse_time(txt(it, "t:ReminderDueBy"))
        if r:
            t.set_reminder(r)
    return t


def sync_tasks(store, c, aid):
    """Tasks here and the account's Tasks folder, both ways. The account that keeps the tasks has
    'tasks' in its settings; the link from each task to its item is kept in the store."""
    from . import tasks
    key = "ews-tasks:%d" % aid
    m = store.get(key, {}) or {}         # uid -> [item id, change key, modified-at-sync]
    local = {t["uid"]: t for t in store.todos("task")}
    # changes here first
    for uid, t in local.items():
        link = m.get(uid)
        try:
            if link is None:
                iid, ck = c.create_item(task_item_xml(t["data"]), dist("tasks"))
                m[uid] = [iid, ck, t["modified"]]
            elif t["modified"] > link[2]:
                iid, ck = c.update_item(link[0], link[1], task_updates(t["data"]))
                m[uid] = [iid, ck, t["modified"]]
        except EwsError as err:
            if err.code != "ErrorItemNotFound":
                raise
            m.pop(uid, None)
    for uid in [u for u in m if u not in local]:
        try:
            c.delete_items([m[uid][0]], "MoveToDeletedItems", "SendToNone")
        except EwsError:
            pass
        del m[uid]
    # then the server's
    remote = {}
    for it in c.find_items(dist("tasks"), ()):
        i = it.find("t:ItemId", NS)
        remote[i.get("Id")] = i.get("ChangeKey")
    by_item = {v[0]: u for u, v in m.items()}
    for uid in [u for u in m if m[u][0] not in remote]:
        if uid in local:
            store.drop_todo(local[uid]["id"])
        del m[uid]
    want = [i for i, ck in remote.items() if i not in by_item or m[by_item[i]][1] != ck]
    for k in range(0, len(want), 50):
        chunk = want[k:k + 50]
        for iid, it in zip(chunk, c.get_items(chunk, (), base="AllProperties")):
            if it is None:
                continue
            uid = by_item.get(iid) or "%s@exchange" % hashlib.sha1(iid.encode()).hexdigest()[:24]
            t = task_of_item(it, uid)
            old = local.get(uid)
            tid = tasks.save(store, t, old["id"] if old else None)
            m[uid] = [iid, it.find("t:ItemId", NS).get("ChangeKey"), store.todo(tid)["modified"]]
    store.put(key, m)


# ---------------------------------------------------------------- adding an Exchange account's calendars and books
def add_account_sources(store, c, acc):
    """The Exchange account's own Calendar and Contacts in the Calendar and People views."""
    from .caldav import COLORS
    cals, books = [], []
    if not any(x["account"] == acc["id"] and x["kind"] == "ews" for x in store.calendars()):
        cid = store.add_calendar("Calendar (%s)" % acc["email"], COLORS[len(store.calendars()) % len(COLORS)], "ews", "", acc["id"])
        store.put("ews-cal:%d" % cid, {})
        cals.append(cid)
    if not any(b["account"] == acc["id"] and b["kind"] == "ews" for b in store.books()):
        bid = store.add_book("Contacts (%s)" % acc["email"], "ews", "", acc["id"])
        store.put("ews-book:%d" % bid, {})
        books.append(bid)
    return cals, books


def open_shared_calendar(store, c, acc, mailbox, name=""):
    """Another person's calendar (they shared it, or made this person their delegate)."""
    from .caldav import COLORS
    c.find_items(dist("calendar", mailbox), ())          # checks access
    cid = store.add_calendar(name or "Calendar - %s" % mailbox, COLORS[len(store.calendars()) % len(COLORS)], "ews", "",
                             acc["id"], False)
    store.put("ews-cal:%d" % cid, {"mailbox": mailbox})
    return cid


def json_dumps(x):
    return json.dumps(x)
