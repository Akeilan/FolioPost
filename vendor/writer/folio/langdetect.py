"""Detect language automatically: a finished paragraph written in another
language (one with a dictionary installed) is marked as that language, so
its spelling is checked correctly."""
import re

from . import bridge, docapi

WORD = re.compile(r"[^\W\d_]{2,}", re.U)
_installed = None


def installed():
    global _installed
    if _installed is None:
        _installed = [(l, c) for _n, l, c in docapi.LANGUAGES if docapi.has_dictionary(l, c)]
    return _installed


def detect(text, current):
    words = WORD.findall(text)
    if len(words) < 4:
        return None
    words = words[:40]
    scores = {}
    for l, c in installed():
        loc = bridge.struct("com.sun.star.lang.Locale", Language=l, Country=c)
        scores[(l, c)] = sum(1 for w in words if docapi.spell_ok(w, loc)) / float(len(words))
    if not scores:
        return None
    cur = scores.get(tuple(current), 0)
    best = max(scores, key=scores.get)
    # another language family only when clearly better
    if best[0] != current[0] and scores[best] >= 0.7 and scores[best] - cur >= 0.3:
        return best
    return None


def check_paragraph(win, back=1):
    if not win.app.settings.get("detect_language", True):
        return False
    m = win.engine.model
    if m is None or len(installed()) < 2:
        return False
    try:
        vc = docapi.view_cursor(m)
        c = vc.getText().createTextCursorByRange(vc.getStart())
        for _i in range(back):
            c.gotoPreviousParagraph(False)
        c.gotoStartOfParagraph(False)
        c.gotoEndOfParagraph(True)
        loc = c.CharLocale
        if loc.Language == "zxx":
            return False
        found = detect(c.getString(), (loc.Language, loc.Country))
        if found:
            c.CharLocale = bridge.struct("com.sun.star.lang.Locale", Language=found[0],
                                         Country=found[1])
            win.status.schedule_proof()
    except Exception as e:
        print("detect language:", e)
    return False
