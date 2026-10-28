"""Restrict Editing, Lock Tracking and Mark as Final with the new engine, kept
the way Word keeps them: w:documentProtection in settings.xml (with Word's
password hash) and the _MarkAsFinal custom property."""
import base64
import hashlib
import os
import re
from xml.sax.saxutils import escape

_INITIAL = (0xE1F0, 0x1D0F, 0xCC9C, 0x84C0, 0x110C, 0x0E10, 0xF1CE, 0x313E, 0x1872,
            0xE139, 0xD40F, 0x84F9, 0x280C, 0xA96A, 0x4EC3)
_ROWS = (0xAEFC, 0x7B61, 0x4563, 0x0375, 0xD849, 0x6F45, 0xEB23, 0x47D3, 0xB861,
         0x45A0, 0xAA51, 0x76B4, 0x3730, 0x3331, 0x1021)


def _matrix():
    out = []
    for x in _ROWS:
        row = [x]
        for _ in range(6):
            x <<= 1
            if x & 0x10000:
                x = (x & 0xFFFF) ^ 0x1021
            row.append(x)
        out.append(row)
    return out


_MATRIX = _matrix()
_ALGS = {1: "md2", 2: "md4", 3: "md5", 4: "sha1", 12: "sha256", 13: "sha384", 14: "sha512"}
_NAMES = {"SHA-1": "sha1", "SHA-256": "sha256", "SHA-384": "sha384", "SHA-512": "sha512",
          "MD5": "md5"}


def legacy_key(pw):
    """Word's 32-bit key for a password (ECMA-376 Part 4, 2.15.1.28)."""
    chars = []
    for ch in pw[:15]:
        c = ord(ch)
        lo, hi = c & 0xFF, (c >> 8) & 0xFF
        chars.append(lo or hi)
    n = len(chars)
    if not n:
        return 0
    high = _INITIAL[n - 1]
    for i, c in enumerate(chars):
        for b in range(7):
            if c & (1 << b):
                high ^= _MATRIX[15 - n + i][b]
    low = 0
    for c in reversed(chars):
        low = (((low >> 14) & 1) | ((low << 1) & 0x7FFF)) ^ c
    low = (((low >> 14) & 1) | ((low << 1) & 0x7FFF)) ^ n ^ 0xCE4B
    return (high << 16) | low


def word_hash(pw, salt, spins=100000, alg="sha512", fmt="%02X"):
    """The hash Word writes in w:hash: the legacy key (bytes reversed, as hex
    text in UTF-16), salted, then hashed again spins times."""
    key = legacy_key(pw)
    hexkey = "".join(fmt % ((key >> (8 * i)) & 0xFF) for i in range(4))
    h = hashlib.new(alg, salt + hexkey.encode("utf-16-le")).digest()
    for i in range(spins):
        h = hashlib.new(alg, h + i.to_bytes(4, "little")).digest()
    return h


def _attrs(x):
    return dict(re.findall(r'w:(\w+)="([^"]*)"', x or ""))


def read(ed):
    """{"on", "mode" ("tracked" / "readonly" / "comments" / "forms"), "password"}"""
    x = ed.settings_xml("w:documentProtection") if ed is not None else None
    a = _attrs(x)
    if not a or a.get("enforcement") not in ("1", "true", "on"):
        return {}
    mode = {"trackedChanges": "tracked", "readOnly": "readonly", "comments": "comments",
            "forms": "forms"}.get(a.get("edit", ""), "readonly")
    return {"on": True, "mode": mode, "lock": mode == "tracked",
            "password": bool(a.get("hash") or a.get("hashValue"))}


def write(ed, mode, pw=""):
    if not mode:
        ed.set_settings_xml("w:documentProtection", None)
        return
    edit = {"tracked": "trackedChanges", "readonly": "readOnly", "comments": "comments",
            "forms": "forms"}[mode]
    extra = ""
    if pw:
        salt = os.urandom(16)
        h = word_hash(pw, salt)
        extra = (' w:cryptProviderType="rsaAES" w:cryptAlgorithmClass="hash" '
                 'w:cryptAlgorithmType="typeAny" w:cryptAlgorithmSid="14" '
                 'w:cryptSpinCount="100000" w:hash="%s" w:salt="%s"'
                 % (base64.b64encode(h).decode(), base64.b64encode(salt).decode()))
    ed.set_settings_xml("w:documentProtection",
                        '<w:documentProtection w:edit="%s" w:enforcement="1"%s/>' % (edit, extra))
    if mode == "tracked" and not ed.track_changes():
        ed.set_track_changes(True)


def check(ed, pw):
    """Does pw open the protection? (No password: anything does.)"""
    a = _attrs(ed.settings_xml("w:documentProtection"))
    if a.get("hash") and a.get("salt"):
        alg = _ALGS.get(int(a.get("cryptAlgorithmSid", "4") or 4), "sha1")
        spins = int(a.get("cryptSpinCount", "0") or 0)
        want = base64.b64decode(a["hash"])
    elif a.get("hashValue") and a.get("saltValue"):
        alg = _NAMES.get(a.get("algorithmName", "SHA-512"), "sha512")
        spins = int(a.get("spinCount", "0") or 0)
        want = base64.b64decode(a["hashValue"])
        a["salt"] = a["saltValue"]
    else:
        return True
    try:
        salt = base64.b64decode(a["salt"])
        # some writers leave the hex digits unpadded
        return any(word_hash(pw or "", salt, spins, alg, f) == want for f in ("%02X", "%X"))
    except Exception:
        return False


# ---------------------------------------------------------------- mark as final
def is_final(ed):
    try:
        return str(dict(ed.custom_properties()).get("_MarkAsFinal", "")).lower() in ("true", "1")
    except Exception:
        return False


def set_final(ed, on):
    try:
        ed.set_custom_property("_MarkAsFinal", "true" if on else None)
        return True
    except Exception:
        return False
