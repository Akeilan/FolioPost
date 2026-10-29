"""A small Exchange Web Services server for the tests: mailboxes in memory with folders, mail
(sent messages arrive in the other mailboxes here), calendar, contacts and tasks, Automatic
Replies, free/busy, delegates and Check Names. Signs in with Basic, Bearer or NTLM, as Exchange
does. Enough of EWS for Post's client, written from Microsoft's EWS reference."""
import base64
import copy
import email
import email.policy
import hashlib
import hmac
import http.server
import os
import re
import sys
import threading
import time
import uuid
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
from folio_post import ews as client  # noqa: E402  (its NTLM pieces check the sign-in)

S = "http://schemas.xmlsoap.org/soap/envelope/"
T = "http://schemas.microsoft.com/exchange/services/2006/types"
M = "http://schemas.microsoft.com/exchange/services/2006/messages"
NS = {"s": S, "t": T, "m": M}
ET.register_namespace("t", T)
ET.register_namespace("m", M)
ET.register_namespace("s", S)
DIST = [("msgfolderroot", "Top of Information Store", "", "Folder", ""), ("inbox", "Inbox", "msgfolderroot", "Folder", "IPF.Note"),
        ("drafts", "Drafts", "msgfolderroot", "Folder", "IPF.Note"), ("sentitems", "Sent Items", "msgfolderroot", "Folder", "IPF.Note"),
        ("deleteditems", "Deleted Items", "msgfolderroot", "Folder", "IPF.Note"),
        ("junkemail", "Junk Email", "msgfolderroot", "Folder", "IPF.Note"), ("outbox", "Outbox", "msgfolderroot", "Folder", "IPF.Note"),
        ("archive", "Archive", "msgfolderroot", "Folder", "IPF.Note"),
        ("calendar", "Calendar", "msgfolderroot", "CalendarFolder", "IPF.Appointment"),
        ("contacts", "Contacts", "msgfolderroot", "ContactsFolder", "IPF.Contact"),
        ("tasks", "Tasks", "msgfolderroot", "TasksFolder", "IPF.Task")]


def t(n):
    return "{%s}%s" % (T, n)


def m(n):
    return "{%s}%s" % (M, n)


class Box:
    def __init__(self, email_, password, name):
        self.email = email_
        self.password = password
        self.name = name
        self.folders = {}            # id -> dict(name, parent, kind, cls, items {id: element})
        self.dist = {}
        for d, nm, parent, kind, cls in DIST:
            fid = "F-%s-%s" % (d, uuid.uuid4().hex[:8])
            self.dist[d] = fid
            self.folders[fid] = {"name": nm, "parent": self.dist.get(parent, ""), "kind": kind, "cls": cls, "items": {}}
        self.oof = {"state": "Disabled", "audience": "All", "start": "", "end": "", "internal": "", "external": ""}
        self.delegates = {}          # email -> {calendar, tasks, inbox}


class World:
    def __init__(self):
        self.boxes = {}
        self.log = []
        self.lock = threading.Lock()

    def add_user(self, email_, password, name=""):
        self.boxes[email_.lower()] = Box(email_, password, name or email_.split("@")[0].capitalize())
        return self.boxes[email_.lower()]

    def box(self, e):
        return self.boxes.get((e or "").lower())

    def find_item(self, iid):
        for b in self.boxes.values():
            for fid, f in b.folders.items():
                if iid in f["items"]:
                    return b, fid, f["items"][iid]
        return None, None, None


def new_ck():
    return "CK" + uuid.uuid4().hex[:10]


def item_id(el):
    return el.find(t("ItemId")).get("Id")


def set_id(el, iid, ck=None):
    old = el.find(t("ItemId"))
    if old is not None:
        el.remove(old)
    x = ET.Element(t("ItemId"), {"Id": iid, "ChangeKey": ck or new_ck()})
    el.insert(0, x)


def child(el, name):
    return el.find(t(name))


def text_of(el, name, default=""):
    x = el.find(t(name)) if el is not None else None
    return x.text if x is not None and x.text is not None else default


def set_child(el, name, value):
    x = el.find(t(name))
    if x is None:
        x = ET.SubElement(el, t(name))
    x.text = value
    return x


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    # ------------------------------------------------------------ sign-in
    def who(self):
        w = self.server.world
        h = self.headers.get("Authorization", "")
        if h.startswith("Bearer ") and h[7:] == "test-token":
            return next(iter(w.boxes.values()))
        if h.startswith("Basic "):
            u, _, p = base64.b64decode(h[6:]).decode().partition(":")
            b = w.box(u)
            if b is not None and b.password == p:
                return b
            return None
        if h.startswith("NTLM "):
            msg = base64.b64decode(h[5:])
            kind = int.from_bytes(msg[8:12], "little")
            if kind == 1:
                self.server_challenge = os.urandom(8)
                ti = (b"\x02\x00" + len("TEST".encode("utf-16-le")).to_bytes(2, "little") + "TEST".encode("utf-16-le") +
                      b"\x01\x00" + len("EXCH".encode("utf-16-le")).to_bytes(2, "little") + "EXCH".encode("utf-16-le") + b"\0\0\0\0")
                ch = (b"NTLMSSP\0" + (2).to_bytes(4, "little") + b"\0\0\0\0" + (48).to_bytes(4, "little") +
                      client.NTLM_FLAGS.to_bytes(4, "little") + self.server_challenge + b"\0" * 8 +
                      len(ti).to_bytes(2, "little") + len(ti).to_bytes(2, "little") + (48).to_bytes(4, "little") + ti)
                self.connection_challenge = self.server_challenge
                return ("challenge", base64.b64encode(ch).decode())
            if kind == 3:
                def field(k):
                    ln, _mx, off = int.from_bytes(msg[12 + 8 * k:14 + 8 * k], "little"), 0, int.from_bytes(msg[16 + 8 * k:20 + 8 * k], "little")
                    return msg[off:off + ln]
                nt, dom, usr = field(1), field(2).decode("utf-16-le"), field(3).decode("utf-16-le")
                chal = getattr(self, "connection_challenge", None)
                for b in w.boxes.values():
                    if b.email.split("@")[0].lower() != usr.lower() and b.email.lower() != usr.lower():
                        continue
                    key = client.ntowf_v2(usr, b.password, dom)
                    proof = hmac.new(key, chal + nt[16:], hashlib.md5).digest() if chal else b""
                    if proof == nt[:16]:
                        self.server.ntlm_conn[id(self.connection)] = b
                        return b
                return None
        b = self.server.ntlm_conn.get(id(self.connection))
        return b

    def send(self, code, body=b"", extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/xml; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0") or 0)
        data = self.rfile.read(n)
        who = self.who()
        if isinstance(who, tuple):
            return self.send(401, b"", {"WWW-Authenticate": "NTLM " + who[1]})
        if who is None:
            return self.send(401, b"", {"WWW-Authenticate": 'Basic realm="ews"', "WWW-Authenticate-2": "NTLM"})
        root = ET.fromstring(data)
        body = root.find("s:Body", NS)
        op = body[0]
        name = op.tag.split("}")[1]
        w = self.server.world
        with w.lock:
            w.log.append(name)
            try:
                out = getattr(self, "op_" + name)(who, op)
            except Problem as e:
                out = '<m:%sResponse><m:ResponseMessages><m:%sResponseMessage ResponseClass="Error"><m:MessageText>%s</m:MessageText>' \
                      '<m:ResponseCode>%s</m:ResponseCode></m:%sResponseMessage></m:ResponseMessages></m:%sResponse>' % (
                          name, name.replace("Request", ""), e.args[1] if len(e.args) > 1 else "", e.args[0],
                          name.replace("Request", ""), name)
        env = ('<?xml version="1.0" encoding="utf-8"?><s:Envelope xmlns:s="%s" xmlns:t="%s" xmlns:m="%s"><s:Body>%s</s:Body></s:Envelope>'
               % (S, T, M, out))
        self.send(200, env)

    # ------------------------------------------------------------ helpers
    def folder_of(self, who, el):
        """(box, folder id) for a FolderId or DistinguishedFolderId element."""
        w = self.server.world
        tag = el.tag.split("}")[1]
        if tag == "DistinguishedFolderId":
            mb = el.find("t:Mailbox/t:EmailAddress", NS)
            box = w.box(mb.text) if mb is not None else who
            if box is None:
                raise Problem("ErrorNonExistentMailbox")
            if box is not who:
                d = box.delegates.get(who.email.lower())
                need = {"calendar": "calendar", "tasks": "tasks", "inbox": "inbox"}.get(el.get("Id"))
                if not d or not need or d.get(need, "None") == "None":
                    raise Problem("ErrorAccessDenied", "Access is denied. Check credentials and try again.")
            return box, box.dist[el.get("Id")]
        fid = el.get("Id")
        for b in w.boxes.values():
            if fid in b.folders:
                return b, fid
        raise Problem("ErrorFolderNotFound")

    def items_xml(self, els):
        return "".join(ET.tostring(e, encoding="unicode") for e in els)

    def ok(self, op, inner=""):
        return ('<m:%sResponse><m:ResponseMessages><m:%sResponseMessage ResponseClass="Success"><m:ResponseCode>NoError</m:ResponseCode>'
                '%s</m:%sResponseMessage></m:ResponseMessages></m:%sResponse>' % (op, op, inner, op, op))

    # ------------------------------------------------------------ folders
    def op_FindFolder(self, who, op):
        box, base = self.folder_of(who, op.find("m:ParentFolderIds", NS)[0])
        out = []

        def walk(pid):
            for fid, f in box.folders.items():
                if f["parent"] == pid:
                    out.append('<t:%s><t:FolderId Id="%s" ChangeKey="x"/><t:ParentFolderId Id="%s" ChangeKey="x"/>'
                               '<t:FolderClass>%s</t:FolderClass><t:DisplayName>%s</t:DisplayName></t:%s>'
                               % (f["kind"], fid, pid, f["cls"], esc(f["name"]), f["kind"]))
                    walk(fid)
        walk(base)
        return self.ok("FindFolder", '<m:RootFolder TotalItemsInView="%d" IncludesLastItemInRange="true"><t:Folders>%s</t:Folders></m:RootFolder>'
                       % (len(out), "".join(out)))

    def op_GetFolder(self, who, op):
        msgs = []
        for el in op.find("m:FolderIds", NS):
            try:
                box, fid = self.folder_of(who, el)
                f = box.folders[fid]
                msgs.append('<m:GetFolderResponseMessage ResponseClass="Success"><m:ResponseCode>NoError</m:ResponseCode><m:Folders>'
                            '<t:%s><t:FolderId Id="%s" ChangeKey="x"/><t:DisplayName>%s</t:DisplayName></t:%s></m:Folders>'
                            '</m:GetFolderResponseMessage>' % (f["kind"], fid, esc(f["name"]), f["kind"]))
            except (Problem, KeyError):
                msgs.append('<m:GetFolderResponseMessage ResponseClass="Error"><m:ResponseCode>ErrorFolderNotFound</m:ResponseCode>'
                            '</m:GetFolderResponseMessage>')
        return "<m:GetFolderResponse><m:ResponseMessages>%s</m:ResponseMessages></m:GetFolderResponse>" % "".join(msgs)

    def op_CreateFolder(self, who, op):
        box, pid = self.folder_of(who, op.find("m:ParentFolderId", NS)[0])
        f = op.find("m:Folders", NS)[0]
        fid = "F-" + uuid.uuid4().hex[:12]
        box.folders[fid] = {"name": text_of(f, "DisplayName"), "parent": pid, "kind": "Folder",
                            "cls": text_of(f, "FolderClass", "IPF.Note"), "items": {}}
        return self.ok("CreateFolder", '<m:Folders><t:Folder><t:FolderId Id="%s" ChangeKey="x"/></t:Folder></m:Folders>' % fid)

    def op_DeleteFolder(self, who, op):
        box, fid = self.folder_of(who, op.find("m:FolderIds", NS)[0])
        box.folders.pop(fid, None)
        return self.ok("DeleteFolder")

    def op_UpdateFolder(self, who, op):
        ch = op.find("m:FolderChanges/t:FolderChange", NS)
        box, fid = self.folder_of(who, ch[0])
        nm = ch.find(".//t:Folder/t:DisplayName", NS)
        if nm is not None:
            box.folders[fid]["name"] = nm.text
        return self.ok("UpdateFolder")

    # ------------------------------------------------------------ items
    def op_FindItem(self, who, op):
        box, fid = self.folder_of(who, op.find("m:ParentFolderIds", NS)[0])
        items = list(box.folders[fid]["items"].values())
        pv = op.find("m:IndexedPageItemView", NS)
        off = int(pv.get("Offset", "0")) if pv is not None else 0
        mx = int(pv.get("MaxEntriesReturned", "1000")) if pv is not None else 1000
        page = items[off:off + mx]
        out = []
        for el in page:
            e = copy.deepcopy(el)
            for x in e.findall(t("MimeContent")):
                e.remove(x)
            out.append(e)
        last = off + len(page) >= len(items)
        return self.ok("FindItem", '<m:RootFolder TotalItemsInView="%d" IncludesLastItemInRange="%s"><t:Items>%s</t:Items></m:RootFolder>'
                       % (len(items), "true" if last else "false", self.items_xml(out)))

    def op_GetItem(self, who, op):
        want_mime = (op.findtext("m:ItemShape/t:IncludeMimeContent", "false", NS) or "false") == "true"
        msgs = []
        for i in op.find("m:ItemIds", NS):
            _b, _f, el = self.server.world.find_item(i.get("Id"))
            if el is None:
                msgs.append('<m:GetItemResponseMessage ResponseClass="Error"><m:ResponseCode>ErrorItemNotFound</m:ResponseCode>'
                            '</m:GetItemResponseMessage>')
                continue
            e = copy.deepcopy(el)
            if not want_mime:
                for x in e.findall(t("MimeContent")):
                    e.remove(x)
            msgs.append('<m:GetItemResponseMessage ResponseClass="Success"><m:ResponseCode>NoError</m:ResponseCode><m:Items>%s</m:Items>'
                        '</m:GetItemResponseMessage>' % ET.tostring(e, encoding="unicode"))
        return "<m:GetItemResponse><m:ResponseMessages>%s</m:ResponseMessages></m:GetItemResponse>" % "".join(msgs)

    def _mime_fields(self, el):
        """Fill Subject, From, IsRead... of a message from its MIME content, as Exchange does."""
        mc = el.find(t("MimeContent"))
        if mc is None:
            return None
        raw = base64.b64decode(mc.text or "")
        msg = email.message_from_bytes(raw, policy=email.policy.default)
        set_child(el, "Subject", str(msg.get("Subject", "")))
        set_child(el, "DateTimeReceived", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        if el.find(t("IsRead")) is None:
            set_child(el, "IsRead", "false")
        return msg, raw

    def op_CreateItem(self, who, op):
        w = self.server.world
        disp = op.get("MessageDisposition", "SaveOnly")
        sf = op.find("m:SavedItemFolderId", NS)
        made = []
        for el in op.find("m:Items", NS):
            el = copy.deepcopy(el)
            kind = el.tag.split("}")[1]
            iid = "I-" + uuid.uuid4().hex
            set_id(el, iid)
            if kind == "Message":
                got = self._mime_fields(el)
                ep = el.find("t:ExtendedProperty", NS)
                if ep is not None:
                    flags = int(ep.findtext("t:Value", "0", NS))
                    set_child(el, "IsRead", "true" if flags & 1 else "false")
                    el.remove(ep)
                if disp in ("SendOnly", "SendAndSaveCopy") and got:
                    msg, raw = got
                    rc = []
                    for h in ("To", "Cc", "Bcc"):
                        rc += [a for _n, a in email.utils.getaddresses([str(x) for x in msg.get_all(h, [])])]
                    clean = re.sub(rb"(?im)^Bcc:.*\r?\n(?:[ \t].*\r?\n)*", b"", raw)
                    w.log.append("sent to " + ",".join(rc))
                    for a in rc:
                        box = w.box(a)
                        if box is None:
                            continue
                        inc = copy.deepcopy(el)
                        set_id(inc, "I-" + uuid.uuid4().hex)
                        inc.find(t("MimeContent")).text = base64.b64encode(clean).decode()
                        set_child(inc, "IsRead", "false")
                        box.folders[box.dist["inbox"]]["items"][item_id(inc)] = inc
                        self._auto_reply(who, box, msg)
                    if disp == "SendOnly":
                        made.append(el)
                        continue
                    el.find(t("MimeContent")).text = base64.b64encode(clean).decode()
                    set_child(el, "IsRead", "true")
                    box, fid = (who, who.dist["sentitems"])
                    if sf is not None:
                        box, fid = self.folder_of(who, sf[0])
                else:
                    box, fid = self.folder_of(who, sf[0]) if sf is not None else (who, who.dist["drafts"])
            else:
                default = {"CalendarItem": "calendar", "Contact": "contacts", "DistributionList": "contacts", "Task": "tasks"}.get(kind, "drafts")
                box, fid = self.folder_of(who, sf[0]) if sf is not None else (who, who.dist[default])
                if kind == "CalendarItem":
                    if child(el, "UID") is None:
                        set_child(el, "UID", uuid.uuid4().hex)
                    org = ET.SubElement(el, t("Organizer"))
                    mb = ET.SubElement(org, t("Mailbox"))
                    ET.SubElement(mb, t("Name")).text = box.name
                    ET.SubElement(mb, t("EmailAddress")).text = box.email
            box.folders[fid]["items"][iid] = el
            made.append(el)
        ids = "".join('<t:%s><t:ItemId Id="%s" ChangeKey="%s"/></t:%s>' % (e.tag.split("}")[1], item_id(e),
                                                                         e.find(t("ItemId")).get("ChangeKey"), e.tag.split("}")[1])
                      for e in made)
        return self.ok("CreateItem", "<m:Items>%s</m:Items>" % ids)

    def _auto_reply(self, sender, box, msg):
        """Automatic Replies: a reply once to the sender while they're on."""
        o = box.oof
        on = o["state"] == "Enabled" or (o["state"] == "Scheduled" and o["start"] <= time.strftime("%Y-%m-%dT%H:%M:%S") <= o["end"])
        if not on or sender is box:
            return
        inc = ET.Element(t("Message"))
        set_id(inc, "I-" + uuid.uuid4().hex)
        raw = ("From: %s <%s>\r\nTo: %s\r\nSubject: Automatic reply: %s\r\nAuto-Submitted: auto-replied\r\n\r\n%s\r\n"
               % (box.name, box.email, sender.email, msg.get("Subject", ""), o["internal"])).encode()
        ET.SubElement(inc, t("MimeContent")).text = base64.b64encode(raw).decode()
        set_child(inc, "Subject", "Automatic reply: %s" % msg.get("Subject", ""))
        set_child(inc, "IsRead", "false")
        sender.folders[sender.dist["inbox"]]["items"][item_id(inc)] = inc

    def op_UpdateItem(self, who, op):
        made = []
        for ch in op.find("m:ItemChanges", NS):
            iid = ch.find("t:ItemId", NS).get("Id")
            _b, _f, el = self.server.world.find_item(iid)
            if el is None:
                raise Problem("ErrorItemNotFound")
            for up in ch.find("t:Updates", NS):
                kind = up.tag.split("}")[1]
                fu = up[0]
                if kind == "DeleteItemField":
                    nm = fu.get("FieldURI").split(":")[-1]
                    for x in el.findall(t(nm)):
                        el.remove(x)
                    continue
                if fu.tag == t("ExtendedFieldURI"):
                    continue
                newel = up[1][0]
                nm = newel.tag.split("}")[1]
                if fu.tag == t("IndexedFieldURI"):
                    cont = el.find(t(nm))
                    if cont is None:
                        cont = ET.SubElement(el, t(nm))
                    entry = newel[0]
                    old = [e for e in cont if e.get("Key") == entry.get("Key")]
                    if nm == "PhysicalAddresses" and old:
                        for part in entry:
                            o = old[0].find(part.tag)
                            if o is None:
                                o = ET.SubElement(old[0], part.tag)
                            o.text = part.text
                    else:
                        for o in old:
                            cont.remove(o)
                        cont.append(copy.deepcopy(entry))
                    continue
                for x in el.findall(t(nm)):
                    el.remove(x)
                el.append(copy.deepcopy(newel))
            set_id(el, iid)
            made.append(el)
        ids = "".join('<t:Item><t:ItemId Id="%s" ChangeKey="%s"/></t:Item>' % (item_id(e), e.find(t("ItemId")).get("ChangeKey"))
                      for e in made)
        return self.ok("UpdateItem", "<m:Items>%s</m:Items>" % ids)

    def op_DeleteItem(self, who, op):
        how = op.get("DeleteType", "HardDelete")
        for i in op.find("m:ItemIds", NS):
            box, fid, el = self.server.world.find_item(i.get("Id"))
            if el is None:
                raise Problem("ErrorItemNotFound")
            del box.folders[fid]["items"][i.get("Id")]
            if how == "MoveToDeletedItems" and fid != box.dist["deleteditems"]:
                box.folders[box.dist["deleteditems"]]["items"][i.get("Id")] = el
        return self.ok("DeleteItem")

    def op_MoveItem(self, who, op):
        box, dest = self.folder_of(who, op.find("m:ToFolderId", NS)[0])
        out = []
        for i in op.find("m:ItemIds", NS):
            b, fid, el = self.server.world.find_item(i.get("Id"))
            if el is None:
                raise Problem("ErrorItemNotFound")
            del b.folders[fid]["items"][i.get("Id")]
            nid = "I-" + uuid.uuid4().hex
            set_id(el, nid)
            box.folders[dest]["items"][nid] = el
            out.append('<t:Message><t:ItemId Id="%s" ChangeKey="x"/></t:Message>' % nid)
        return self.ok("MoveItem", "<m:Items>%s</m:Items>" % "".join(out))

    # ------------------------------------------------------------ Automatic Replies
    def op_GetUserOofSettingsRequest(self, who, op):
        o = who.oof
        dur = "<t:Duration><t:StartTime>%s</t:StartTime><t:EndTime>%s</t:EndTime></t:Duration>" % (o["start"], o["end"]) if o["start"] else ""
        return ('<m:GetUserOofSettingsResponse><m:ResponseMessage ResponseClass="Success"><m:ResponseCode>NoError</m:ResponseCode>'
                '</m:ResponseMessage><t:OofSettings><t:OofState>%s</t:OofState><t:ExternalAudience>%s</t:ExternalAudience>%s'
                '<t:InternalReply><t:Message>%s</t:Message></t:InternalReply><t:ExternalReply><t:Message>%s</t:Message></t:ExternalReply>'
                '</t:OofSettings><m:AllowExternalOof>All</m:AllowExternalOof></m:GetUserOofSettingsResponse>'
                % (o["state"], o["audience"], dur, esc(o["internal"]), esc(o["external"])))

    def op_SetUserOofSettingsRequest(self, who, op):
        s = op.find("t:UserOofSettings", NS)
        who.oof = {"state": text_of(s, "OofState", "Disabled"), "audience": text_of(s, "ExternalAudience", "All"),
                   "start": s.findtext("t:Duration/t:StartTime", "", NS)[:19], "end": s.findtext("t:Duration/t:EndTime", "", NS)[:19],
                   "internal": s.findtext("t:InternalReply/t:Message", "", NS), "external": s.findtext("t:ExternalReply/t:Message", "", NS)}
        return ('<m:SetUserOofSettingsResponse><m:ResponseMessage ResponseClass="Success"><m:ResponseCode>NoError</m:ResponseCode>'
                '</m:ResponseMessage></m:SetUserOofSettingsResponse>')

    # ------------------------------------------------------------ free/busy
    def op_GetUserAvailabilityRequest(self, who, op):
        w = self.server.world
        tw = op.find("t:FreeBusyViewOptions/t:TimeWindow", NS)
        ws, we = tw.findtext("t:StartTime", "", NS)[:19], tw.findtext("t:EndTime", "", NS)[:19]
        out = []
        for md in op.find("m:MailboxDataArray", NS):
            box = w.box(md.findtext("t:Email/t:Address", "", NS))
            if box is None:
                out.append('<m:FreeBusyResponse><m:ResponseMessage ResponseClass="Error"><m:ResponseCode>ErrorMailRecipientNotFound'
                           '</m:ResponseCode></m:ResponseMessage></m:FreeBusyResponse>')
                continue
            evs = []
            for el in box.folders[box.dist["calendar"]]["items"].values():
                s, e = text_of(el, "Start")[:19], text_of(el, "End")[:19]
                if s < we and e > ws:
                    evs.append('<t:CalendarEvent><t:StartTime>%s</t:StartTime><t:EndTime>%s</t:EndTime><t:BusyType>%s</t:BusyType>'
                               '</t:CalendarEvent>' % (s, e, text_of(el, "LegacyFreeBusyStatus", "Busy")))
            out.append('<m:FreeBusyResponse><m:ResponseMessage ResponseClass="Success"><m:ResponseCode>NoError</m:ResponseCode>'
                       '</m:ResponseMessage><m:FreeBusyView><t:FreeBusyViewType>Detailed</t:FreeBusyViewType>'
                       '<t:CalendarEventArray>%s</t:CalendarEventArray></m:FreeBusyView></m:FreeBusyResponse>' % "".join(evs))
        return ('<m:GetUserAvailabilityResponse><m:FreeBusyResponseArray>%s</m:FreeBusyResponseArray></m:GetUserAvailabilityResponse>'
                % "".join(out))

    # ------------------------------------------------------------ delegates
    def op_GetDelegate(self, who, op):
        out = "".join('<m:DelegateUserResponseMessageType ResponseClass="Success"><m:ResponseCode>NoError</m:ResponseCode>'
                      '<m:DelegateUser><t:UserId><t:PrimarySmtpAddress>%s</t:PrimarySmtpAddress><t:DisplayName>%s</t:DisplayName>'
                      '</t:UserId><t:DelegatePermissions><t:CalendarFolderPermissionLevel>%s</t:CalendarFolderPermissionLevel>'
                      '<t:TasksFolderPermissionLevel>%s</t:TasksFolderPermissionLevel><t:InboxFolderPermissionLevel>%s'
                      '</t:InboxFolderPermissionLevel></t:DelegatePermissions></m:DelegateUser></m:DelegateUserResponseMessageType>'
                      % (e, esc(self.server.world.box(e).name if self.server.world.box(e) else e), d["calendar"], d["tasks"], d["inbox"])
                      for e, d in who.delegates.items())
        return ('<m:GetDelegateResponse ResponseClass="Success"><m:ResponseCode>NoError</m:ResponseCode><m:ResponseMessages>%s'
                '</m:ResponseMessages></m:GetDelegateResponse>' % out)

    def op_AddDelegate(self, who, op):
        for du in op.find("m:DelegateUsers", NS):
            e = du.findtext("t:UserId/t:PrimarySmtpAddress", "", NS).lower()
            if self.server.world.box(e) is None:
                raise Problem("ErrorDelegateNoUser", "The delegate does not map to a user in the Active Directory.")
            p = du.find("t:DelegatePermissions", NS)
            who.delegates[e] = {"calendar": text_of(p, "CalendarFolderPermissionLevel", "None"),
                                "tasks": text_of(p, "TasksFolderPermissionLevel", "None"),
                                "inbox": text_of(p, "InboxFolderPermissionLevel", "None")}
        return ('<m:AddDelegateResponse ResponseClass="Success"><m:ResponseCode>NoError</m:ResponseCode></m:AddDelegateResponse>')

    op_UpdateDelegate = op_AddDelegate

    def op_RemoveDelegate(self, who, op):
        for u in op.find("m:UserIds", NS):
            who.delegates.pop(u.findtext("t:PrimarySmtpAddress", "", NS).lower(), None)
        return ('<m:RemoveDelegateResponse ResponseClass="Success"><m:ResponseCode>NoError</m:ResponseCode></m:RemoveDelegateResponse>')

    def op_ResolveNames(self, who, op):
        text = (op.findtext("m:UnresolvedEntry", "", NS) or "").lower()
        hits = [b for b in self.server.world.boxes.values() if text in b.email.lower() or text in b.name.lower()]
        res = "".join('<t:Resolution><t:Mailbox><t:Name>%s</t:Name><t:EmailAddress>%s</t:EmailAddress></t:Mailbox></t:Resolution>'
                      % (esc(b.name), esc(b.email)) for b in hits)
        if not hits:
            raise Problem("ErrorNameResolutionNoResults")
        return self.ok("ResolveNames", '<m:ResolutionSet TotalItemsInView="%d" IncludesLastItemInRange="true">%s</m:ResolutionSet>'
                       % (len(hits), res))


class Problem(Exception):
    pass


def esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True


def start(world, port=0):
    srv = Server(("127.0.0.1", port), Handler)
    srv.world = world
    srv.ntlm_conn = {}
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    return srv, "http://127.0.0.1:%d/EWS/Exchange.asmx" % srv.server_address[1]


if __name__ == "__main__":
    w = World()
    w.add_user(sys.argv[1] if len(sys.argv) > 1 else "me@example.com", sys.argv[2] if len(sys.argv) > 2 else "secret")
    srv, url = start(w, int(sys.argv[3]) if len(sys.argv) > 3 else 8085)
    print(url)
    threading.Event().wait()
