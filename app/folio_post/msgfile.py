"""Outlook item files: .msg messages and .oft templates (M3-06), read and written here from
[MS-OXMSG] (properties in a compound file), [MS-OXRTFCP] (compressed RTF) and [MS-OXRTFEX]
(HTML kept inside RTF)."""
import email.utils
import re
import struct

from . import cfb

PT_STRING = 0x001F
PT_STRING8 = 0x001E
PT_BINARY = 0x0102
PT_LONG = 0x0003
PT_BOOL = 0x000B
PT_TIME = 0x0040

SUBJECT, MESSAGE_CLASS, BODY, HTML, RTF = 0x0037, 0x001A, 0x1000, 0x1013, 0x1009
DISPLAY_TO, DISPLAY_CC, DISPLAY_BCC = 0x0E04, 0x0E03, 0x0E02
MESSAGE_FLAGS, IMPORTANCE, CODEPAGE = 0x0E07, 0x0017, 0x3FDE
R_DISPLAY, R_ADDRTYPE, R_EMAIL, R_TYPE, R_SMTP = 0x3001, 0x3002, 0x3003, 0x0C15, 0x39FE
A_DATA, A_FILENAME, A_LONGNAME, A_METHOD, A_MIME, A_CID = 0x3701, 0x3704, 0x3707, 0x3705, 0x370E, 0x3712
SENDER_NAME, SENDER_EMAIL = 0x0C1A, 0x0C1F
OFT_CLSID = "00020D0B-0000-0000-C000-000000000046"


# ---------------------------------------------------------------- writing
def _props(entries, header):
    out = bytearray(header)
    streams = {}
    for pid, ptype, value in entries:
        tag = (pid << 16) | ptype
        if ptype in (PT_STRING, PT_BINARY, PT_STRING8):
            data = (value + "\0").encode("utf-16-le") if ptype == PT_STRING else value
            streams["__substg1.0_%08X" % tag] = data
            out += struct.pack("<IIII", tag, 6, len(data), 0)
        elif ptype == PT_BOOL:
            out += struct.pack("<IIII", tag, 6, 1 if value else 0, 0)
        elif ptype == PT_TIME:
            out += struct.pack("<IIQ", tag, 6, value)
        else:
            out += struct.pack("<IIiI", tag, 6, int(value), 0)
    return bytes(out), streams


def write(fields, template=True):
    """A .oft (or .msg) from {subject, to, cc, bcc: [(name, address)], text, html, attachments: [(name, type, bytes)],
    importance}."""
    files = {}
    recips = [(n, a, 1) for n, a in fields.get("to", [])] + [(n, a, 2) for n, a in fields.get("cc", [])] + \
        [(n, a, 3) for n, a in fields.get("bcc", [])]
    atts = list(fields.get("attachments", []))
    entries = [(MESSAGE_CLASS, PT_STRING, "IPM.Note"), (SUBJECT, PT_STRING, fields.get("subject", "")),
               (BODY, PT_STRING, fields.get("text", "")), (MESSAGE_FLAGS, PT_LONG, 8 if template else 1),
               (IMPORTANCE, PT_LONG, {2: 2, 0: 0}.get(fields.get("importance", 1), 1)), (CODEPAGE, PT_LONG, 65001),
               (DISPLAY_TO, PT_STRING, "; ".join(n or a for n, a, t in recips if t == 1)),
               (DISPLAY_CC, PT_STRING, "; ".join(n or a for n, a, t in recips if t == 2)),
               (DISPLAY_BCC, PT_STRING, "; ".join(n or a for n, a, t in recips if t == 3))]
    if fields.get("html"):
        entries.append((HTML, PT_BINARY, fields["html"].encode("utf-8")))
    head = struct.pack("<8xIIII8x", len(recips), len(atts), len(recips), len(atts))
    data, streams = _props(entries, head)
    files["__properties_version1.0"] = data
    files.update(streams)
    for k, (n, a, t) in enumerate(recips):
        d, st = _props([(R_DISPLAY, PT_STRING, n or a), (R_ADDRTYPE, PT_STRING, "SMTP"), (R_EMAIL, PT_STRING, a),
                        (R_SMTP, PT_STRING, a), (R_TYPE, PT_LONG, t), (0x3000, PT_LONG, k)], b"\0" * 8)
        pre = "__recip_version1.0_#%08X/" % k
        files[pre + "__properties_version1.0"] = d
        files.update({pre + key: v for key, v in st.items()})
    for k, (name, ctype, blob) in enumerate(atts):
        ext = ("." + name.rsplit(".", 1)[1]) if "." in name else ""
        d, st = _props([(A_METHOD, PT_LONG, 1), (A_DATA, PT_BINARY, blob), (A_LONGNAME, PT_STRING, name),
                        (A_FILENAME, PT_STRING, name[:12]), (A_MIME, PT_STRING, ctype or "application/octet-stream"),
                        (0x3703, PT_STRING, ext), (0x0E21, PT_LONG, k)], b"\0" * 8)
        pre = "__attach_version1.0_#%08X/" % k
        files[pre + "__properties_version1.0"] = d
        files.update({pre + key: v for key, v in st.items()})
    for s in ("__substg1.0_00020102", "__substg1.0_00030102", "__substg1.0_00040102"):
        files["__nameid_version1.0/" + s] = b""
    return cfb.write(files)


# ---------------------------------------------------------------- reading
def _read_props(streams, prefix, header_len):
    raw = streams.get(prefix + "__properties_version1.0", b"")
    out = {}
    for off in range(header_len, len(raw) - 15, 16):
        tag, _flags = struct.unpack_from("<II", raw, off)
        pid, ptype = tag >> 16, tag & 0xFFFF
        if ptype in (PT_STRING, PT_STRING8, PT_BINARY):
            data = streams.get(prefix + "__substg1.0_%08X" % tag, b"")
            if ptype == PT_STRING:
                out[pid] = data.decode("utf-16-le", "replace").rstrip("\0")
            elif ptype == PT_STRING8:
                out[pid] = data.decode("cp1252", "replace").rstrip("\0")
            else:
                out[pid] = data
        elif ptype in (PT_LONG, PT_BOOL):
            out[pid] = struct.unpack_from("<i", raw, off + 8)[0]
    return out


def read(data):
    """{subject, to, cc, bcc, text, html, attachments, importance, from, message_class} of a .msg / .oft."""
    streams = cfb.read(data)
    top = _read_props(streams, "", 32)
    rec = {1: [], 2: [], 3: []}
    k = 0
    while "__recip_version1.0_#%08X/__properties_version1.0" % k in streams:
        p = _read_props(streams, "__recip_version1.0_#%08X/" % k, 8)
        addr = p.get(R_SMTP) or p.get(R_EMAIL, "")
        rec.setdefault(p.get(R_TYPE, 1), []).append((p.get(R_DISPLAY, ""), addr))
        k += 1
    atts = []
    k = 0
    while "__attach_version1.0_#%08X/__properties_version1.0" % k in streams:
        p = _read_props(streams, "__attach_version1.0_#%08X/" % k, 8)
        if isinstance(p.get(A_DATA), bytes):
            atts.append((p.get(A_LONGNAME) or p.get(A_FILENAME) or "attachment", p.get(A_MIME, "application/octet-stream"),
                         p[A_DATA]))
        k += 1
    html = top.get(HTML)
    if isinstance(html, bytes):
        html = html.decode("utf-8", "replace")
    if not html and isinstance(top.get(RTF), bytes):
        try:
            html = html_from_rtf(lzfu(top[RTF]))
        except Exception:
            html = None
    return {"subject": top.get(SUBJECT, ""), "to": rec[1], "cc": rec[2], "bcc": rec[3], "text": top.get(BODY, ""),
            "html": html or None, "attachments": atts, "message_class": top.get(MESSAGE_CLASS, ""),
            "importance": {2: 2, 0: 0}.get(top.get(IMPORTANCE, 1), 1),
            "from": (top.get(SENDER_NAME, ""), top.get(SENDER_EMAIL, ""))}


# ---------------------------------------------------------------- compressed RTF
PREBUF = (b"{\\rtf1\\ansi\\mac\\deff0\\deftab720{\\fonttbl;}{\\f0\\fnil \\froman \\fswiss \\fmodern \\fscript "
          b"\\fdecor MS Sans SerifSymbolArialTimes New RomanCourier{\\colortbl\\red0\\green0\\blue0\r\n\\par "
          b"\\pard\\plain\\f0\\fs20\\b\\i\\u\\tab\\tx")


def lzfu(data):
    """[MS-OXRTFCP]: the RTF inside PidTagRtfCompressed."""
    size, raw, magic, _crc = struct.unpack_from("<IIII", data, 0)
    if magic == 0x414C454D:                      # "MELA": stored uncompressed
        return data[16:16 + raw]
    if magic != 0x75465A4C:
        raise ValueError("not compressed RTF")
    buf = bytearray(4096)
    buf[:len(PREBUF)] = PREBUF
    wp = len(PREBUF)
    out = bytearray()
    i = 16
    end = min(len(data), size + 4)
    while i < end:
        flags = data[i]
        i += 1
        for bit in range(8):
            if i >= end:
                break
            if flags & (1 << bit):
                ref = (data[i] << 8) | data[i + 1]
                i += 2
                off, ln = ref >> 4, (ref & 0xF) + 2
                if off == wp:
                    return bytes(out)
                for _k in range(ln):
                    c = buf[off]
                    out.append(c)
                    buf[wp] = c
                    wp = (wp + 1) % 4096
                    off = (off + 1) % 4096
            else:
                c = data[i]
                i += 1
                out.append(c)
                buf[wp] = c
                wp = (wp + 1) % 4096
    return bytes(out[:raw])


def html_from_rtf(rtf):
    """[MS-OXRTFEX]: the HTML an RTF body keeps (\\fromhtml1); None for plain RTF."""
    s = rtf.decode("cp1252", "replace")
    if "\\fromhtml" not in s[:400]:
        return None
    out = []
    i, n = 0, len(s)
    depth = 0
    skip_depth = []           # group depths where \htmlrtf is on
    htmlrtf = False
    while i < n:
        ch = s[i]
        if ch == "{":
            depth += 1
            i += 1
            continue
        if ch == "}":
            depth -= 1
            while skip_depth and skip_depth[-1] > depth:
                skip_depth.pop()
            htmlrtf = bool(skip_depth)
            i += 1
            continue
        if ch == "\\":
            m = re.match(r"\\([a-z]+)(-?\d+)? ?|\\'([0-9a-f]{2})|\\([{}\\])|\\(\*)", s[i:i + 40])
            if not m:
                i += 1
                continue
            word, arg, hexv, lit = m.group(1), m.group(2), m.group(3), m.group(4)
            i += m.end()
            if hexv and not htmlrtf:
                out.append(bytes([int(hexv, 16)]).decode("cp1252", "replace"))
            elif lit and not htmlrtf:
                out.append(lit)
            elif word == "htmlrtf":
                on = arg != "0"
                if on:
                    skip_depth.append(depth)
                elif skip_depth:
                    skip_depth.pop()
                htmlrtf = bool(skip_depth)
            elif word == "par" and not htmlrtf:
                out.append("\n")
            elif word == "tab" and not htmlrtf:
                out.append("\t")
            elif word in ("fonttbl", "colortbl", "stylesheet", "pntext"):
                # skip the whole group
                d0 = depth
                while i < n and depth >= d0:
                    if s[i] == "{":
                        depth += 1
                    elif s[i] == "}":
                        depth -= 1
                    elif s[i] == "\\":
                        i += 1
                    i += 1
            continue
        if ch in "\r\n":
            i += 1
            continue
        if not htmlrtf:
            out.append(ch)
        i += 1
    html = "".join(out)
    k = html.lower().find("<html")
    return html[k:] if k >= 0 else html


def to_eml(data):
    """A .msg as an RFC 822 message (for opening it)."""
    from . import mime
    f = read(data)
    frm = f["from"] if f["from"][1] else ("", "")
    m = mime.build(frm, f["to"], f["cc"], f["bcc"], f["subject"], f["text"], f["html"], f["attachments"], (),
                   importance=f["importance"])
    return mime.to_bytes(m)


def fields_of_message(m):
    """The fields of an email.message (a message being written) for write()."""
    from . import mime
    return {"subject": mime.header(m, "Subject"), "to": mime.addresses(m, "To"), "cc": mime.addresses(m, "Cc"),
            "bcc": mime.addresses(m, "Bcc"), "text": mime.text_of(m), "html": _html_of(m),
            "attachments": [(a["name"], a["type"], a["data"]) for a in mime.attachments(m) if not a["inline"]],
            "importance": 2 if mime.header(m, "Importance").lower() == "high" else 0 if mime.header(m, "Importance").lower() == "low" else 1}


def _html_of(m):
    from . import mime
    return mime.body_part(m, "html")


_ = email.utils
