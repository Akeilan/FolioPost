"""AutoCorrect lists: the engine's English lists, adjusted to the familiar
behaviour ((c) -> ©, :) -> ☺, arrows), and an editor for "Replace text as
you type"."""
import html
import os
import re
import zipfile

# Folio's own copies first (LibreOffice's English lists, MPL-2.0), so they work without it
_HERE = os.path.dirname(os.path.abspath(__file__))
SHARE_DIRS = ["/usr/share/folio-writer/autocorr", os.path.join(_HERE, "..", "..", "share", "autocorr"),
              "/usr/lib/libreoffice/share/autocorr", "/opt/libreoffice/share/autocorr"]
LANGS = ["en-US", "en-GB", "en-AU", "en-ZA"]
AC_VERSION = "3"

EXTRA = [
    ("(c)", "©"), ("(C)", "©"), ("(r)", "®"), ("(R)", "®"),
    ("(tm)", "™"), ("(TM)", "™"), ("(e)", "€"), ("(E)", "€"),
    (":)", "\u263a\ufe0e"), (":-)", "\u263a\ufe0e"), (":(", "\u2639\ufe0e"),
    (":-(", "\u2639\ufe0e"),
    ("-->", "→"), ("<--", "←"), ("==>", "⇒"), ("<==", "⇐"),
    ("<=>", "⇔"), ("...", "…"), ("->", "→"), ("<-", "←"), ("=>", "⇒"),
    ("1/2", "½"), ("1/4", "¼"), ("3/4", "¾"),
    ("abotu", "about"), ("acn", "can"), ("adn", "and"), ("alot", "a lot"),
    ("bakc", "back"), ("becuase", "because"), ("cna", "can"), ("doesnt", "doesn't"),
    ("dont", "don't"), ("didnt", "didn't"), ("freind", "friend"), ("hte", "the"),
    ("i", "I"), ("im", "I'm"), ("isnt", "isn't"), ("taht", "that"), ("thier", "their"),
    ("recieve", "receive"), ("wiht", "with"), ("wont", "won't"), ("youre", "you're"),
]
# Abbreviations the engine treats as sentence ends but that are ordinary words.
NOT_ABBREVIATIONS = {"in.", "no.", "sat.", "sun.", "wed.", "mar.", "min.", "max.", "temp.",
                     "rec.", "org.", "est.", "pos.", "var.", "lit.", "nat.", "int.", "rel.",
                     "rev.", "spec.", "tot.", "prev.", "ne.", "se.", "sw.", "nw.", "mon.",
                     "fri.", "dec.", "neg.", "norm.", "sci.", "ext.", "obj.", "orig.", "mun.",
                     "cont.", "resp.", "pl.", "ln.", "mi.", "sq.", "ct.", "rd.", "ft.", "hr."}

NS = 'xmlns:block-list="http://openoffice.org/2001/block-list"'
ENTRY = re.compile(r'<block-list:block block-list:abbreviated-name="([^"]*)" '
                   r'block-list:name="([^"]*)"\s*/>')


def _share_file(lang):
    for d in SHARE_DIRS:
        p = os.path.join(d, "acor_%s.dat" % lang)
        if os.path.exists(p):
            return p
    return None


def _unescape(s):
    return html.unescape(s)


def _escape(s):
    return html.escape(s, quote=True)


def read_list(path):
    """[(replace, with), ...] from an AutoCorrect .dat file."""
    with zipfile.ZipFile(path) as z:
        xml = z.read("DocumentList.xml").decode("utf-8")
    return [(_unescape(a), _unescape(b)) for a, b in ENTRY.findall(xml)]


def _read_all(path):
    with zipfile.ZipFile(path) as z:
        return {n: z.read(n) for n in z.namelist()}


def _write(path, files, entries=None, exceptions=None):
    if entries is not None:
        body = "".join('<block-list:block block-list:abbreviated-name="%s" '
                       'block-list:name="%s"/>' % (_escape(a), _escape(b)) for a, b in entries)
        files["DocumentList.xml"] = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                                     '<block-list:block-list %s>%s</block-list:block-list>'
                                     % (NS, body)).encode("utf-8")
    if exceptions is not None:
        body = "".join('<block-list:block block-list:abbreviated-name="%s"/>' % _escape(a)
                       for a in exceptions)
        files["SentenceExceptList.xml"] = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                                           '<block-list:block-list %s>%s</block-list:block-list>'
                                           % (NS, body)).encode("utf-8")
    tmp = path + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        if "mimetype" in files:
            z.writestr(zipfile.ZipInfo("mimetype"), files["mimetype"], zipfile.ZIP_STORED)
        for n, data in files.items():
            if n != "mimetype" and not n.endswith("/"):
                z.writestr(n, data)
    os.replace(tmp, path)


def install(user_dir):
    """Create/upgrade the user's English AutoCorrect lists in the engine profile."""
    d = os.path.join(user_dir, "autocorr")
    os.makedirs(d, exist_ok=True)
    marker = os.path.join(d, "folio.version")
    try:
        with open(marker) as f:
            if f.read().strip() == AC_VERSION:
                return
    except OSError:
        pass
    for lang in LANGS:
        user = os.path.join(d, "acor_%s.dat" % lang)
        base = user if os.path.exists(user) else _share_file(lang)
        if base is None:
            continue
        try:
            files = _read_all(base)
            entries = read_list(base)
            keys = {a for a, _b in EXTRA}
            entries = [e for e in entries if e[0] not in keys] + EXTRA
            exc_xml = files.get("SentenceExceptList.xml", b"").decode("utf-8")
            exc = [_unescape(a) for a in re.findall(r'abbreviated-name="([^"]*)"', exc_xml)]
            exc = [a for a in exc if a.lower() not in NOT_ABBREVIATIONS]
            _write(user, files, entries, exc)
        except Exception as e:
            print("autocorrect", lang, e)
    with open(marker, "w") as f:
        f.write(AC_VERSION + "\n")


def user_list_path(user_dir, lang="en-US"):
    p = os.path.join(user_dir, "autocorr", "acor_%s.dat" % lang)
    return p if os.path.exists(p) else None


def save_list(path, entries):
    files = _read_all(path)
    _write(path, files, entries)


def read_exceptions(path):
    """(after these no capital follows, these keep their two capitals)"""
    files = _read_all(path)

    def names(n):
        xml = files.get(n, b"").decode("utf-8")
        return [_unescape(a) for a in re.findall(r'abbreviated-name="([^"]*)"', xml)]
    return names("SentenceExceptList.xml"), names("WordExceptList.xml")


def save_exceptions(path, first, caps):
    files = _read_all(path)
    _write(path, files, None, first)
    body = "".join('<block-list:block block-list:abbreviated-name="%s"/>' % _escape(a)
                   for a in caps)
    files = _read_all(path)
    files["WordExceptList.xml"] = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                                   '<block-list:block-list %s>%s</block-list:block-list>'
                                   % (NS, body)).encode("utf-8")
    _write(path, files)
