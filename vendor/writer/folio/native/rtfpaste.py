"""RTF from the clipboard as plain text (the new engine pastes its words; formatting
comes with HTML, which other programs offer too)."""
import re


def to_text(data):
    if isinstance(data, bytes):
        data = data.decode("latin-1", "replace")
    out = []
    depth_skip = []
    i = 0
    n = len(data)
    depth = 0
    skip_at = None
    while i < n:
        ch = data[i]
        if ch == "{":
            depth += 1
            # destinations that hold no text
            m = re.match(r"\{\\\*|\{\\(fonttbl|colortbl|stylesheet|info|pict|header|footer|listtable|listoverridetable|themedata|colorschememapping|latentstyles|datastore|xmlnstbl|rsidtbl|generator)", data[i:i + 40])
            if m and skip_at is None:
                skip_at = depth
            i += 1
            continue
        if ch == "}":
            if skip_at == depth:
                skip_at = None
            depth -= 1
            i += 1
            continue
        if ch == "\\":
            m = re.match(r"\\([a-zA-Z]+)(-?\d+)? ?|\\'([0-9a-fA-F]{2})|\\(.)", data[i:])
            if not m:
                i += 1
                continue
            i += m.end()
            if skip_at is not None:
                continue
            word, hexv, sym = m.group(1), m.group(3), m.group(4)
            if word in ("par", "line", "sect"):
                out.append("\n")
            elif word == "tab":
                out.append("\t")
            elif word == "u" and m.group(2):
                code = int(m.group(2))
                out.append(chr(code + 65536 if code < 0 else code))
                # the fallback character after \uN
                if i < n and data[i] not in "\\{}":
                    i += 1
            elif hexv:
                out.append(bytes([int(hexv, 16)]).decode("cp1252", "replace"))
            elif sym in ("\\", "{", "}"):
                out.append(sym)
            elif sym == "~":
                out.append("\u00a0")
            continue
        if ch in "\r\n":
            i += 1
            continue
        if skip_at is None:
            out.append(ch)
        i += 1
    return "".join(out).strip("\n")
