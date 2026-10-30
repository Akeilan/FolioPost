"""TNEF (winmail.dat), the format Outlook uses to carry its own message properties (M3-09).

Folio Post writes it for voting buttons Outlook shows (PidLidVerbStream on the message,
PidLidVerbResponse on the answer) and reads it to show Outlook's voting buttons and the files
an Outlook message carries inside winmail.dat. Formats: [MS-OXTNEF], [MS-OXOMSG] 2.2.1.74.

  build(props, key=None)          winmail.dat bytes for a message with these MAPI properties
  parse(data)                     {"class", "props", "attachments": [(name, bytes)]}
  verb_stream(choices)            PidLidVerbStream value for these voting choices
  vote_choices(stream)            the choices in a PidLidVerbStream value
"""
import struct
import uuid

SIGNATURE = 0x223E9F78
LVL_MESSAGE, LVL_ATTACHMENT = 1, 2
# attributes: (type << 16) | id
ATT_TNEF_VERSION = 0x00089006
ATT_OEM_CODEPAGE = 0x00069007
ATT_MESSAGE_CLASS = 0x00078008
ATT_MSG_PROPS = 0x00069003
ATT_ATTACH_REND_DATA = 0x00069002
ATT_ATTACH_TITLE = 0x00018010
ATT_ATTACH_DATA = 0x0006800F
ATT_ATTACHMENT = 0x00069005

PT_SHORT, PT_LONG, PT_BOOLEAN, PT_SYSTIME = 0x0002, 0x0003, 0x000B, 0x0040
PT_STRING8, PT_UNICODE, PT_BINARY, PT_OBJECT, PT_CLSID = 0x001E, 0x001F, 0x0102, 0x000D, 0x0048
PSETID_COMMON = uuid.UUID("00062008-0000-0000-C000-000000000046")
LID_VERB_STREAM = 0x8520
LID_VERB_RESPONSE = 0x8524
TAG_TNEF_CORRELATION_KEY = 0x007F
TAG_REPORT_TAG = 0x0031
TAG_ATTACH_LONG_FILENAME = 0x3707
TAG_ATTACH_FILENAME = 0x3704
TAG_ATTACH_DATA = 0x3701

_FIXED = {PT_SHORT: 4, PT_LONG: 4, PT_BOOLEAN: 4, 0x0004: 4, 0x0005: 8, 0x0006: 8, 0x0007: 8,
          PT_SYSTIME: 8, 0x0014: 8, 0x000A: 4, PT_CLSID: 16}
_VARIABLE = (PT_STRING8, PT_UNICODE, PT_BINARY, PT_OBJECT)


def _pad(b):
    return b + b"\0" * (-len(b) % 4)


def _attr(level, att, data):
    return struct.pack("<BII", level, att, len(data)) + data + struct.pack("<H", sum(data) & 0xFFFF)


def _value(ptype, v):
    if ptype == PT_UNICODE:
        d = (v + "\0").encode("utf-16-le")
    elif ptype == PT_STRING8:
        d = (v + "\0").encode("cp1252", "replace")
    elif ptype in (PT_BINARY, PT_OBJECT):
        d = bytes(v)
    elif ptype in (PT_LONG, PT_SHORT, PT_BOOLEAN):
        return struct.pack("<I", int(v) & 0xFFFFFFFF)
    else:
        raise ValueError("property type %#x not written" % ptype)
    return struct.pack("<II", 1, len(d)) + _pad(d)


def props_block(props):
    """MAPI property list. props: [(ptype, tag or (guid, lid), value)]."""
    out = [struct.pack("<I", len(props))]
    for ptype, tag, v in props:
        if isinstance(tag, tuple):
            guid, lid = tag
            out.append(struct.pack("<HH", ptype, 0x8000) + guid.bytes_le + struct.pack("<II", 0, lid))
        else:
            out.append(struct.pack("<HH", ptype, tag))
        out.append(_value(ptype, v))
    return b"".join(out)


def build(props, message_class="IPM.Note", key=None):
    key = 0x4F46 if key is None else key & 0xFFFF
    out = [struct.pack("<IH", SIGNATURE, key),
           _attr(LVL_MESSAGE, ATT_TNEF_VERSION, struct.pack("<I", 0x00010000)),
           _attr(LVL_MESSAGE, ATT_OEM_CODEPAGE, struct.pack("<II", 1252, 0)),
           _attr(LVL_MESSAGE, ATT_MESSAGE_CLASS, message_class.encode("ascii") + b"\0")]
    if props:
        out.append(_attr(LVL_MESSAGE, ATT_MSG_PROPS, props_block(props)))
    return b"".join(out)


def parse_props(d):
    """{tag or (guid, lid) or (guid, name): value} from a MAPI property list."""
    out = {}
    n = struct.unpack_from("<I", d, 0)[0]
    p = 4
    for _ in range(n):
        ptype, tag = struct.unpack_from("<HH", d, p)
        p += 4
        multi = bool(ptype & 0x1000)
        base = ptype & 0x0FFF
        key = tag
        if tag >= 0x8000:
            guid = uuid.UUID(bytes_le=bytes(d[p:p + 16]))
            kind = struct.unpack_from("<I", d, p + 16)[0]
            p += 20
            if kind == 0:
                key = (guid, struct.unpack_from("<I", d, p)[0])
                p += 4
            else:
                ln = struct.unpack_from("<I", d, p)[0]
                p += 4
                key = (guid, bytes(d[p:p + ln]).decode("utf-16-le", "replace").rstrip("\0"))
                p += ln + (-ln % 4)
        if base in _VARIABLE:
            cnt = struct.unpack_from("<I", d, p)[0]
            p += 4
            vals = []
            for _i in range(cnt):
                ln = struct.unpack_from("<I", d, p)[0]
                p += 4
                raw = bytes(d[p:p + ln])
                p += ln + (-ln % 4)
                if base == PT_UNICODE:
                    raw = raw.decode("utf-16-le", "replace").rstrip("\0")
                elif base == PT_STRING8:
                    raw = raw.decode("cp1252", "replace").rstrip("\0")
                elif base == PT_OBJECT:
                    raw = raw[16:]          # the interface id comes first
                vals.append(raw)
            v = vals if multi else (vals[0] if vals else None)
        else:
            size = _FIXED.get(base)
            if size is None:
                break                       # a type we can't step over: stop here
            if multi:
                cnt = struct.unpack_from("<I", d, p)[0]
                p += 4
                v = [bytes(d[p + i * size:p + (i + 1) * size]) for i in range(cnt)]
                p += cnt * size + (-(cnt * size) % 4)
            else:
                raw = bytes(d[p:p + size])
                p += size + (-size % 4)
                v = struct.unpack("<I", raw)[0] if base in (PT_LONG, PT_BOOLEAN) else \
                    struct.unpack("<h", raw[:2])[0] if base == PT_SHORT else raw
        out[key] = v
    return out


def parse(data):
    """What a winmail.dat holds; None when it isn't TNEF."""
    data = bytes(data or b"")
    if len(data) < 6 or struct.unpack_from("<I", data, 0)[0] != SIGNATURE:
        return None
    res = {"class": "", "props": {}, "attachments": []}
    att = None
    p = 6

    def close():
        if att is not None and (att.get("data") is not None):
            res["attachments"].append((att.get("long") or att.get("title") or "attachment", att["data"]))
    while p + 9 <= len(data):
        level, aid, ln = struct.unpack_from("<BII", data, p)
        p += 9
        d = data[p:p + ln]
        p += ln + 2
        try:
            if aid == ATT_MESSAGE_CLASS:
                res["class"] = d.rstrip(b"\0").decode("ascii", "replace")
            elif aid == ATT_MSG_PROPS and level == LVL_MESSAGE:
                res["props"].update(parse_props(d))
            elif aid == ATT_ATTACH_REND_DATA:
                close()
                att = {}
            elif att is not None and aid == ATT_ATTACH_TITLE:
                att["title"] = d.rstrip(b"\0").decode("cp1252", "replace")
            elif att is not None and aid == ATT_ATTACH_DATA:
                att["data"] = bytes(d)
            elif att is not None and aid == ATT_ATTACHMENT:
                pr = parse_props(d)
                att["long"] = pr.get(TAG_ATTACH_LONG_FILENAME) or pr.get(TAG_ATTACH_FILENAME) or att.get("long")
                if att.get("data") is None and isinstance(pr.get(TAG_ATTACH_DATA), bytes):
                    att["data"] = pr[TAG_ATTACH_DATA]
        except (struct.error, ValueError, UnicodeError):
            continue
    close()
    return res


# ---------------------------------------------------------------- voting
def verb_stream(choices):
    """PidLidVerbStream: one voting option per choice, answered after a prompt to send or edit,
    as Outlook writes them."""
    def a(s):
        b = s.encode("cp1252", "replace")[:255]
        return struct.pack("<B", len(b)) + b
    opts = []
    for i, c in enumerate(choices, 1):
        opts.append(struct.pack("<I", 4) + a(c) + a("IPM.Note") + a("") + a(c) +
                    struct.pack("<IBIIIIII", 0, 0, 0, 1, 2, 2, i, 0xFFFFFFFF))
    extras = []
    for c in choices:
        u = c[:255]
        w = u.encode("utf-16-le")
        extras.append(struct.pack("<B", len(u)) + w + struct.pack("<B", len(u)) + w)
    return struct.pack("<HI", 0x0102, len(choices)) + b"".join(opts) + struct.pack("<H", 0x0104) + b"".join(extras)


def vote_choices(stream):
    """The voting choices (verb type 4) in a PidLidVerbStream value, Unicode names when given."""
    s = bytes(stream or b"")
    try:
        ver, n = struct.unpack_from("<HI", s, 0)
        p = 6
        names = []
        kinds = []

        def a():
            nonlocal p
            ln = s[p]
            v = s[p + 1:p + 1 + ln].decode("cp1252", "replace")
            p += 1 + ln
            return v
        for _ in range(n):
            vt = struct.unpack_from("<I", s, p)[0]
            p += 4
            name = a()
            a()
            a()
            a()
            p += 4 + 1 + 4 * 6
            kinds.append(vt)
            names.append(name)
        if p + 2 <= len(s) and struct.unpack_from("<H", s, p)[0] == 0x0104:
            p += 2
            for i in range(n):
                ln = s[p]
                w = s[p + 1:p + 1 + 2 * ln].decode("utf-16-le", "replace")
                p += 1 + 2 * ln
                ln2 = s[p]
                p += 1 + 2 * ln2
                if w:
                    names[i] = w
    except (IndexError, struct.error):
        return []
    return [nm for nm, k in zip(names, kinds) if k == 4 and nm]


def voting_message(choices, correlator):
    """winmail.dat for a message with voting buttons."""
    return build([(PT_BINARY, (PSETID_COMMON, LID_VERB_STREAM), verb_stream(choices)),
                  (PT_BINARY, TAG_TNEF_CORRELATION_KEY, correlator.encode("ascii", "replace") + b"\0")])


def voting_response(choice, correlator, report_tag=None):
    """winmail.dat for the answer to Outlook voting buttons."""
    props = [(PT_UNICODE, (PSETID_COMMON, LID_VERB_RESPONSE), choice),
             (PT_BINARY, TAG_TNEF_CORRELATION_KEY, correlator.encode("ascii", "replace") + b"\0")]
    if report_tag:
        props.append((PT_BINARY, TAG_REPORT_TAG, report_tag))
    return build(props)
