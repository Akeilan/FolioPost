"""Grammar and style checks for the Editor pane, plus readability statistics.

The engine's English grammar checker (Lightproof, when installed) is asked
first; a few extra rules here catch common slips it doesn't."""
import re

from . import bridge, docapi

LIGHTPROOF = "org.openoffice.comp.pyuno.Lightproof.lightproof_en"
_PR = []


def _proofreader():
    if not _PR:
        try:
            _PR.append(bridge.create(LIGHTPROOF))
        except Exception:
            _PR.append(None)
    return _PR[0]


def enable_online(m=None):
    """Use the grammar checker for underlining as you type (English)."""
    try:
        lsm = bridge.create("com.sun.star.linguistic2.LinguServiceManager")
        for country in ("US", "GB", "AU", "CA", "NZ", "ZA", "IE", "IN"):
            loc = docapi.locale("en", country)
            avail = lsm.getAvailableServices("com.sun.star.linguistic2.Proofreader", loc)
            if LIGHTPROOF in avail:
                lsm.setConfiguredServices("com.sun.star.linguistic2.Proofreader", loc,
                                          (LIGHTPROOF,))
        install_equation_filter()
        return True
    except Exception as e:
        print("grammar:", e)
        return False


RULES = [
    # (pattern, message, replacement function or None)
    (re.compile(r"\b(\w+)\s+\1\b", re.I), "Repeated word",
     lambda mm: mm.group(1)),
    (re.compile(r"\b(should|could|would|must|might)\s+of\b", re.I), "Did you mean 'have'?",
     lambda mm: mm.group(1) + " have"),
    (re.compile(r"(?<![\w'])i(?![\w'])"), "Capitalize the pronoun 'I'",
     lambda mm: "I"),
    (re.compile(r"(?<=\S)  +(?=\S)"), "Extra space between words",
     lambda mm: " "),
    (re.compile(r"\s+([,.;:!?])(?=\s|$)"), "Space before punctuation",
     lambda mm: mm.group(1)),
    (re.compile(r"([.!?])\s+([a-z])"), "Capitalize the first word of a sentence",
     lambda mm: mm.group(1) + " " + mm.group(2).upper()),
    (re.compile(r"\b(a)\s+(?=[aeiou]\w)", re.I), "Use 'an' before a vowel sound",
     lambda mm: ("An " if mm.group(1)[0].isupper() else "an ")),
    (re.compile(r"\b(an)\s+(?=[bcdfgjklmnpqrstvwxyz]\w)", re.I),
     "Use 'a' before a consonant sound", lambda mm: ("A " if mm.group(1)[0].isupper() else "a ")),
]
_EXCEPT_AN = re.compile(r"\b(an?)\s+(hour|honest|honor|heir|uni\w*|use\w*|user\w*|one|once|eu\w*)",
                        re.I)


def check(text, lang="en", country="US"):
    """[(start, length, message, [suggestions])] for one paragraph."""
    out = []
    pr = _proofreader() if lang == "en" else None
    if pr is not None and text.strip():
        try:
            res = pr.doProofreading("folio", text, docapi.locale(lang, country), 0,
                                    len(text), ())
            for e in res.aErrors:
                out.append((e.nErrorStart, e.nErrorLength,
                            e.aShortComment or e.aFullComment, list(e.aSuggestions)))
        except Exception as e:
            print("lightproof:", e)
    if lang == "en":
        exceptions = {m.start() for m in _EXCEPT_AN.finditer(text)}
        for rx, msg, fix in RULES:
            if msg is None:
                continue
            for mm in rx.finditer(text):
                if "'a'" in msg or "'an'" in msg:
                    if mm.start() in exceptions:
                        continue
                if msg == "Repeated word" and mm.group(1).lower() in ("that", "had"):
                    continue          # "had had", "that that" can be correct
                start, length = mm.start(), mm.end() - mm.start()
                if any(not (start + length <= s or s + n <= start) for s, n, _m, _x in out):
                    continue
                out.append((start, length, msg, [fix(mm)] if fix else []))
    out.sort()
    return out


def next_issue(m, after_range=None, ignored=()):
    """Find and select the next grammar issue in the body text.
    Returns (message, suggestions, original text) or None."""
    body = m.getText()
    vc = docapi.view_cursor(m)
    loc = docapi.doc_locale(m)
    try:
        here = body.createTextCursorByRange(vc.getEnd() if after_range else vc.getStart())
    except Exception:
        here = body.createTextCursor()
        here.gotoStart(False)
    for wrap in (0, 1):
        en = body.createEnumeration()
        while en.hasMoreElements():
            para = en.nextElement()
            if not para.supportsService("com.sun.star.text.Paragraph"):
                continue
            text = para.getString()
            if not text.strip():
                continue
            try:
                if not wrap and body.compareRegionEnds(para, here) > 0:
                    continue          # paragraph ends before the cursor
            except Exception:
                pass
            pc = body.createTextCursorByRange(para.getStart())
            for start, length, msg, sugg in check(text, loc.Language or "en",
                                                   loc.Country or "US"):
                key = (text, start)
                if key in ignored:
                    continue
                c = body.createTextCursorByRange(pc.getStart())
                c.goRight(start, False)
                if not wrap:
                    try:
                        if body.compareRegionStarts(c, here) > 0:
                            continue  # before the cursor
                        if after_range and body.compareRegionStarts(c, here) == 0:
                            continue
                    except Exception:
                        pass
                c.goRight(length, True)
                docapi.controller(m).select(c)
                return msg, sugg, c.getString(), key
        if wrap:
            break
    return None


# ------------------------------------------------------------ readability
def _syllables(word):
    w = word.lower()
    w = re.sub(r"[^a-z]", "", w)
    if not w:
        return 0
    if len(w) <= 3:
        return 1
    w = re.sub(r"(?:[^laeiouy]es|ed|[^laeiouy]e)$", "", w)
    w = re.sub(r"^y", "", w)
    return max(1, len(re.findall(r"[aeiouy]{1,2}", w)))


def readability(m):
    text = m.getText().getString()
    paras = [p for p in text.split("\n") if p.strip()]
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", " ".join(paras)) if s.strip()]
    words = re.findall(r"[A-Za-z0-9'’-]+", text)
    chars = sum(len(re.sub(r"\W", "", w)) for w in words)
    syl = sum(_syllables(w) for w in words)
    nw, ns, np_ = len(words), max(1, len(sentences)), max(1, len(paras))
    passive = sum(1 for s in sentences if re.search(
        r"\b(am|is|are|was|were|be|been|being)\s+\w+(ed|en)\b", s, re.I))
    fre = 206.835 - 1.015 * (nw / ns) - 84.6 * (syl / max(1, nw))
    fk = 0.39 * (nw / ns) + 11.8 * (syl / max(1, nw)) - 15.59
    return {
        "Words": nw, "Characters": chars, "Paragraphs": len(paras),
        "Sentences": len(sentences),
        "Sentences per Paragraph": round(len(sentences) / np_, 1),
        "Words per Sentence": round(nw / ns, 1),
        "Characters per Word": round(chars / max(1, nw), 1),
        "Passive Sentences": "%d%%" % round(100.0 * passive / ns),
        "Flesch Reading Ease": round(max(0.0, min(100.0, fre)), 1),
        "Flesch-Kincaid Grade Level": round(max(0.0, fk), 1),
    }


# ------------------------------------------------------------ equations
# The engine leaves objects out of the text it hands to the grammar checker,
# so "the value <equation> is" arrives as "the value  is" and the checker
# flags the double space (and "space before punctuation" next to commas).
# Errors touching the place where an equation was are dropped here. The map
# of those places is kept up to date on the UI thread (the checker runs on
# its own thread and must not call into the document).
GAPS = {}
_PATCHED = []


CONTEXT = []        # [(text before, text after)] around each in-line object


def _gaps_of(par):
    gaps = []
    pos = 0
    en = par.createEnumeration()
    while en.hasMoreElements():
        r = en.nextElement()
        kind = getattr(r, "TextPortionType", "")
        if kind == "Frame":
            gaps.append(pos)
        elif kind == "Text":
            pos += len(r.getString())
    return gaps


def refresh_gaps(m):
    """Remember where equations sit: by paragraph text, and by the few
    characters on each side (which survive edits elsewhere in the paragraph)."""
    if m is None:
        return
    try:
        seen = {}
        ctx = []
        for obj in docapi.formulas(m):
            try:
                anchor = obj.getAnchor()
                cur = anchor.getText().createTextCursorByRange(anchor.getStart())
                cur.gotoStartOfParagraph(False)
                cur.gotoEndOfParagraph(True)
                en = cur.createEnumeration()
                par = en.nextElement() if en.hasMoreElements() else None
                if par is None:
                    continue
                text = par.getString()
                if text not in seen:
                    seen[text] = _gaps_of(par)
                    for g in seen[text]:
                        ctx.append((text[max(0, g - 12):g], text[g:g + 12]))
            except Exception:
                continue
        GAPS.clear()
        GAPS.update(seen)
        CONTEXT[:] = ctx
    except Exception as e:
        print("grammar gaps:", e)


def gaps_in(text):
    g = GAPS.get(text)
    if g:
        return g
    out = []
    for before, after in CONTEXT:
        if not before and not after:
            continue
        i = text.find(before + after)
        while i >= 0:
            out.append(i + len(before))
            i = text.find(before + after, i + 1)
    return out


def install_equation_filter():
    if _PATCHED:
        return
    import sys
    _proofreader()
    impl = sys.modules.get("lightproof_impl_lightproof_en")
    if impl is None or not hasattr(impl, "proofread"):
        return
    orig = impl.proofread

    def proofread(nDocId, TEXT, LOCALE, nStartOfSentencePos, nSuggestedSentenceEndPos,
                  rProperties):
        errs = orig(nDocId, TEXT, LOCALE, nStartOfSentencePos, nSuggestedSentenceEndPos,
                    rProperties)
        if not errs or not CONTEXT:
            return errs
        gaps = gaps_in(TEXT)
        if not gaps:
            return errs
        keep = []
        for e in errs:
            a, b = e.nErrorStart, e.nErrorStart + e.nErrorLength
            if any(a - 2 <= g <= b + 2 for g in gaps):
                continue
            keep.append(e)
        return tuple(keep)
    impl.proofread = proofread
    _PATCHED.append(orig)
