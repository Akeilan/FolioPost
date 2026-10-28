"""OpenPGP for mail (RFC 3156, PGP/MIME) through the gpg program: encrypting to the recipients'
public keys, signing with your own, and decrypting and checking what arrives."""
import os
import re
import shutil
import subprocess
import uuid

from . import mime


def gpg():
    return shutil.which("gpg")


def _run(args, data=None):
    exe = gpg()
    if exe is None:
        raise RuntimeError("OpenPGP needs GnuPG (package gnupg)")
    p = subprocess.run([exe, "--batch", "--yes", "--no-tty", "--status-fd", "2"] + args, input=data, capture_output=True)
    return p.returncode, p.stdout, p.stderr.decode("utf-8", "replace")


def has_key(addr, secret=False):
    if gpg() is None or not addr:
        return False
    code, out, _e = _run(["--with-colons", "--list-secret-keys" if secret else "--list-keys", "<%s>" % addr])
    return code == 0 and ((b"sec:" in out) if secret else (b"pub:" in out))


def missing_keys(addrs):
    return [a for a in addrs if not has_key(a)]


def encrypt(data, rcpts, sign_as=None):
    args = ["--armor", "--trust-model", "always", "--encrypt"]
    for r in rcpts:
        args += ["-r", "<%s>" % r]
    if sign_as:
        args += ["--sign", "-u", "<%s>" % sign_as]
    code, out, err = _run(args, data)
    if code != 0:
        raise RuntimeError(_why(err) or "gpg couldn't encrypt")
    return out


def sign(data, signer):
    code, out, err = _run(["--armor", "--detach-sign", "--digest-algo", "SHA256", "-u", "<%s>" % signer], data)
    if code != 0:
        raise RuntimeError(_why(err) or "gpg couldn't sign")
    return out


def _why(err):
    for line in err.splitlines():
        if line.startswith("gpg:") and ("error" in line or "No public key" in line or "skipped" in line or "failed" in line):
            return line[4:].strip()
    return ""


def _signer(status):
    m = re.search(r"\[GNUPG:\] GOODSIG \S+ (.+)", status)
    if m:
        return "good", m.group(1).strip()
    m = re.search(r"\[GNUPG:\] BADSIG \S+ (.+)", status)
    if m:
        return "bad", m.group(1).strip()
    if "[GNUPG:] NO_PUBKEY" in status or "[GNUPG:] ERRSIG" in status:
        return "unknown", ""
    return None, ""


def decrypt(armored):
    """(plaintext, signature state, signer) — the state is good / bad / unknown / None."""
    code, out, err = _run(["--decrypt"], armored)
    if code != 0 and not out:
        raise RuntimeError(_why(err) or "this message is encrypted for a key that isn't on this computer")
    st, who = _signer(err)
    return out, st, who


def verify(data, signature):
    exe = gpg()
    if exe is None:
        return None, ""
    import tempfile
    d = tempfile.mkdtemp(prefix="folio-pgp-")
    sp = os.path.join(d, "sig.asc")
    dp = os.path.join(d, "data")
    with open(sp, "wb") as fh:
        fh.write(signature)
    with open(dp, "wb") as fh:
        fh.write(data)
    _c, _o, err = _run(["--verify", sp, dp])
    shutil.rmtree(d, ignore_errors=True)
    return _signer(err)


# ---------------------------------------------------------------- PGP/MIME
def _crlf(b):
    return re.sub(rb"\r?\n", b"\r\n", b)


def _body_entity(m):
    """The message's content as a MIME entity of its own (its Content-* headers and body)."""
    raw = mime.to_bytes(m)
    head, _, body = raw.partition(b"\r\n\r\n")
    keep = []
    for line in re.split(rb"\r\n(?![ \t])", head):
        if line.lower().startswith((b"content-", b"mime-version")) and not line.lower().startswith(b"mime-version"):
            keep.append(line)
    return _crlf(b"\r\n".join(keep) + b"\r\n\r\n" + body)


def _outer_headers(m):
    raw = mime.to_bytes(m)
    head = raw.partition(b"\r\n\r\n")[0]
    out = []
    for line in re.split(rb"\r\n(?![ \t])", head):
        if not line.lower().startswith((b"content-", b"mime-version")):
            out.append(line)
    return b"\r\n".join(out)


def protect(m, encrypt_to=None, sign_as=None):
    """The message, encrypted (to `encrypt_to` addresses) and/or signed (by `sign_as`), as bytes to send."""
    entity = _body_entity(m)
    head = _outer_headers(m)
    b = "=-folio-%s" % uuid.uuid4().hex
    if encrypt_to:
        enc = encrypt(entity, encrypt_to, sign_as)
        body = ("MIME-Version: 1.0\r\nContent-Type: multipart/encrypted; protocol=\"application/pgp-encrypted\"; boundary=\"%s\"\r\n\r\n"
                "This is an OpenPGP/MIME encrypted message (RFC 4880 and 3156)\r\n--%s\r\nContent-Type: application/pgp-encrypted\r\n"
                "Content-Description: PGP/MIME version identification\r\n\r\nVersion: 1\r\n\r\n--%s\r\n"
                "Content-Type: application/octet-stream; name=\"encrypted.asc\"\r\nContent-Description: OpenPGP encrypted message\r\n"
                "Content-Disposition: inline; filename=\"encrypted.asc\"\r\n\r\n" % (b, b, b)).encode() + _crlf(enc) + \
            ("\r\n--%s--\r\n" % b).encode()
        return head + b"\r\n" + body
    sig = sign(entity, sign_as)
    body = ("MIME-Version: 1.0\r\nContent-Type: multipart/signed; micalg=pgp-sha256; protocol=\"application/pgp-signature\"; "
            "boundary=\"%s\"\r\n\r\nThis is an OpenPGP/MIME signed message (RFC 4880 and 3156)\r\n--%s\r\n" % (b, b)).encode() + \
        entity + ("\r\n--%s\r\nContent-Type: application/pgp-signature; name=\"signature.asc\"\r\nContent-Description: OpenPGP "
                  "digital signature\r\nContent-Disposition: attachment; filename=\"signature.asc\"\r\n\r\n" % b).encode() + \
        _crlf(sig) + ("\r\n--%s--\r\n" % b).encode()
    return head + b"\r\n" + body


def kind(msg):
    ct = msg.get_content_type()
    proto = (msg.get_param("protocol") or "").lower()
    if ct == "multipart/encrypted" and proto == "application/pgp-encrypted":
        return "encrypted"
    if ct == "multipart/signed" and proto == "application/pgp-signature":
        return "signed"
    text = mime.body_part(msg, "plain") or ""
    if "-----BEGIN PGP MESSAGE-----" in text:
        return "inline-encrypted"
    return None


def open_message(raw):
    """What a protected message says: (message to show, note) — the note tells about encryption and signature."""
    msg = mime.parse(raw)
    k = kind(msg)
    if k is None:
        return msg, None
    try:
        if k == "encrypted":
            parts = msg.get_payload()
            data = parts[1].get_payload(decode=True) if len(parts) > 1 else b""
            plain, st, who = decrypt(data)
            inner = mime.parse(plain)
            # the outer headers (From, To, Subject) with the decrypted content
            for h in ("From", "To", "Cc", "Subject", "Date", "Message-ID"):
                if msg.get(h) and not inner.get(h):
                    inner[h] = str(msg.get(h))
            note = "Encrypted" + _sig_note(st, who)
            if kind(inner) == "signed":
                inner2, note2 = open_message(mime.to_bytes(inner))
                return inner2, "Encrypted · " + (note2 or "")
            return inner, note
        if k == "signed":
            b = msg.get_boundary()
            text = raw if isinstance(raw, bytes) else raw.encode()
            text = _crlf(text)
            sep = ("--%s\r\n" % b).encode()
            pieces = text.split(sep)
            if len(pieces) >= 3:
                signed = pieces[1][:-2] if pieces[1].endswith(b"\r\n") else pieces[1]
                sig = msg.get_payload()[1].get_payload(decode=True)
                st, who = verify(signed, sig)
            else:
                st, who = None, ""
            inner = msg.get_payload()[0]
            for h in ("From", "To", "Cc", "Subject", "Date", "Message-ID"):
                if msg.get(h) and not inner.get(h):
                    inner[h] = str(msg.get(h))
            return inner, _sig_note(st, who).lstrip(" ·") or "Signed"
        if k == "inline-encrypted":
            text = mime.body_part(msg, "plain")
            block = re.search(r"-----BEGIN PGP MESSAGE-----.*?-----END PGP MESSAGE-----", text, re.S).group(0)
            plain, st, who = decrypt(block.encode())
            from email.message import EmailMessage
            out = EmailMessage()
            for h in ("From", "To", "Cc", "Subject", "Date"):
                if msg.get(h):
                    out[h] = str(msg.get(h))
            out.set_content(plain.decode("utf-8", "replace"))
            return out, "Encrypted" + _sig_note(st, who)
    except Exception as e:
        return msg, "Couldn't open: %s" % e
    return msg, None


def _sig_note(st, who):
    if st == "good":
        return " · Signed by %s (good signature)" % who
    if st == "bad":
        return " · The signature of %s does NOT match: the message changed on the way" % who
    if st == "unknown":
        return " · Signed with a key that isn't on this computer"
    return ""
