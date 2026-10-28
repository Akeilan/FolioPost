"""S/MIME (RFC 8551) through the openssl program: your certificate and key from a .p12/.pfx file,
other people's certificates gathered from the signed mail they send, encrypting and signing, and
opening and checking what arrives."""
import glob
import os
import re
import shutil
import subprocess
import tempfile

from . import mime


def openssl():
    return shutil.which("openssl")


def home():
    d = os.environ.get("FOLIO_POST_SMIME") or os.path.join(
        os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "folio-post", "smime")
    os.makedirs(d, mode=0o700, exist_ok=True)
    return d


def _run(args, data=None):
    exe = openssl()
    if exe is None:
        raise RuntimeError("S/MIME needs OpenSSL (package openssl)")
    p = subprocess.run([exe] + args, input=data, capture_output=True)
    return p.returncode, p.stdout, p.stderr.decode("utf-8", "replace")


def _safe(addr):
    return re.sub(r"[^\w.@+-]", "_", addr.lower())


def my_files(addr):
    d = home()
    cert, key = os.path.join(d, "me-%s.crt" % _safe(addr)), os.path.join(d, "me-%s.key" % _safe(addr))
    return (cert, key) if os.path.exists(cert) and os.path.exists(key) else (None, None)


def has_mine(addr):
    return my_files(addr)[0] is not None


def cert_of(addr):
    p = os.path.join(home(), "%s.crt" % _safe(addr))
    if os.path.exists(p):
        return p
    mine = my_files(addr)[0]
    return mine


def missing_certs(addrs):
    return [a for a in addrs if cert_of(a) is None]


def emails_in_cert(pem_path):
    code, out, _e = _run(["x509", "-in", pem_path, "-noout", "-email", "-subject"])
    text = out.decode("utf-8", "replace")
    found = set(x.strip().lower() for x in text.splitlines() if "@" in x and "=" not in x)
    found |= set(m.lower() for m in re.findall(r"emailAddress\s*=\s*([^,/\s]+)", text))
    return sorted(found)


def import_p12(path, password, addr):
    """Your certificate and private key, from a .p12 / .pfx file (as certificate authorities hand them out)."""
    cert, key = os.path.join(home(), "me-%s.crt" % _safe(addr)), os.path.join(home(), "me-%s.key" % _safe(addr))
    for args, out in ((["pkcs12", "-in", path, "-clcerts", "-nokeys", "-passin", "pass:" + password], cert),
                      (["pkcs12", "-in", path, "-nocerts", "-nodes", "-passin", "pass:" + password], key)):
        code, data, err = _run(args)
        if code != 0:
            code, data, err = _run(args[:1] + ["-legacy"] + args[1:])
        if code != 0 or not data:
            raise RuntimeError("the file couldn't be opened (is the password right?)")
        with open(out, "wb") as fh:
            os.chmod(out, 0o600)
            fh.write(data)
    return cert


def learn_from(raw):
    """Keep the sender's certificate from a signed message, so mail to them can be encrypted."""
    if openssl() is None:
        return None
    d = tempfile.mkdtemp(prefix="folio-smime-")
    mp = os.path.join(d, "m.eml")
    with open(mp, "wb") as fh:
        fh.write(raw)
    out = os.path.join(d, "signer.pem")
    _run(["smime", "-verify", "-noverify", "-in", mp, "-signer", out, "-out", os.devnull])
    learned = None
    if os.path.exists(out) and os.path.getsize(out):
        for e in emails_in_cert(out):
            target = os.path.join(home(), "%s.crt" % _safe(e))
            shutil.copyfile(out, target)
            learned = e
    shutil.rmtree(d, ignore_errors=True)
    return learned


# ---------------------------------------------------------------- sending
def _entity(m):
    raw = mime.to_bytes(m)
    head, _, body = raw.partition(b"\r\n\r\n")
    keep = [ln for ln in re.split(rb"\r\n(?![ \t])", head) if ln.lower().startswith(b"content-")]
    return b"\r\n".join(keep) + b"\r\n\r\n" + body


def _outer(m):
    raw = mime.to_bytes(m)
    head = raw.partition(b"\r\n\r\n")[0]
    return b"\r\n".join(ln for ln in re.split(rb"\r\n(?![ \t])", head) if not ln.lower().startswith((b"content-", b"mime-version")))


def protect(m, encrypt_to=None, sign_as=None):
    entity = _entity(m)
    d = tempfile.mkdtemp(prefix="folio-smime-")
    try:
        cur = os.path.join(d, "in")
        with open(cur, "wb") as fh:
            fh.write(entity)
        if sign_as:
            cert, key = my_files(sign_as)
            if cert is None:
                raise RuntimeError("there's no S/MIME certificate of yours for %s" % sign_as)
            out = os.path.join(d, "signed")
            code, _o, err = _run(["smime", "-sign", "-in", cur, "-signer", cert, "-inkey", key, "-out", out, "-binary"])
            if code != 0:
                raise RuntimeError(err.strip().splitlines()[-1] if err.strip() else "openssl couldn't sign")
            cur = out
        if encrypt_to:
            certs = [cert_of(a) for a in encrypt_to]
            out = os.path.join(d, "enc")
            code, _o, err = _run(["smime", "-encrypt", "-aes-256-cbc", "-in", cur, "-out", out, "-binary"] + certs)
            if code != 0:
                raise RuntimeError(err.strip().splitlines()[-1] if err.strip() else "openssl couldn't encrypt")
            cur = out
        with open(cur, "rb") as fh:
            body = fh.read()
    finally:
        shutil.rmtree(d, ignore_errors=True)
    body = re.sub(rb"\r?\n", b"\r\n", body)
    # openssl writes MIME-Version and the Content-Type itself
    return _outer(m) + b"\r\n" + body


# ---------------------------------------------------------------- reading
def kind(msg):
    ct = msg.get_content_type()
    if ct in ("application/pkcs7-mime", "application/x-pkcs7-mime"):
        return "encrypted" if "signed-data" not in (msg.get_param("smime-type") or "") else "signed-opaque"
    if ct == "multipart/signed" and (msg.get_param("protocol") or "").lower() in ("application/pkcs7-signature",
                                                                                  "application/x-pkcs7-signature"):
        return "signed"
    return None


def open_message(raw, my_addrs=()):
    msg = mime.parse(raw)
    k = kind(msg)
    if k is None:
        return msg, None
    d = tempfile.mkdtemp(prefix="folio-smime-")
    try:
        mp = os.path.join(d, "m.eml")
        with open(mp, "wb") as fh:
            fh.write(raw if isinstance(raw, bytes) else raw.encode())
        note = ""
        if k == "encrypted":
            done = None
            for a in my_addrs:
                cert, key = my_files(a)
                if cert is None:
                    continue
                out = os.path.join(d, "plain")
                code, _o, _e = _run(["smime", "-decrypt", "-in", mp, "-recip", cert, "-inkey", key, "-out", out])
                if code == 0:
                    done = out
                    break
            if done is None:
                return msg, "Encrypted with S/MIME for a certificate that isn't on this computer"
            data = open(done, "rb").read()
            inner = mime.parse(data)
            note = "Encrypted (S/MIME)"
            if kind(inner) in ("signed", "signed-opaque"):
                for h in ("From", "To", "Cc", "Subject", "Date"):
                    if msg.get(h) and not inner.get(h):
                        inner[h] = str(msg.get(h))
                inner2, n2 = open_message(mime.to_bytes(inner) if not data.startswith(b"MIME") else data, my_addrs)
                for h in ("From", "To", "Cc", "Subject", "Date"):
                    if msg.get(h) and not inner2.get(h):
                        inner2[h] = str(msg.get(h))
                return inner2, note + " · " + (n2 or "")
        else:
            out = os.path.join(d, "content")
            code, _o, err = _run(["smime", "-verify", "-in", mp, "-out", out, "-purpose", "any"] +
                                 (["-CApath", "/etc/ssl/certs"] if os.path.isdir("/etc/ssl/certs") else []))
            if code == 0:
                note = "Signed (S/MIME, the certificate is trusted)"
            else:
                code2, _o, _e = _run(["smime", "-verify", "-noverify", "-in", mp, "-out", out])
                note = ("Signed (S/MIME); the sender's certificate isn't from an authority this computer trusts" if code2 == 0
                        else "The S/MIME signature does NOT match: the message changed on the way")
            if os.path.exists(out) and os.path.getsize(out):
                data = open(out, "rb").read()
            else:
                data = None
            learn_from(raw if isinstance(raw, bytes) else raw.encode())
            if data is None:
                return msg, note
            inner = mime.parse(data)
        for h in ("From", "To", "Cc", "Subject", "Date", "Message-ID"):
            if msg.get(h) and not inner.get(h):
                inner[h] = str(msg.get(h))
        return inner, note
    except Exception as e:
        return msg, "Couldn't open: %s" % e
    finally:
        shutil.rmtree(d, ignore_errors=True)
