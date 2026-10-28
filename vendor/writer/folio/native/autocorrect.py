"""AutoCorrect and AutoFormat As You Type with the new engine, as Word does
them when you finish a word: the replacement list, a capital at the start of
a sentence, TWo INitial CApitals, smart quotes and apostrophes, dashes,
ordinals (1st), and at the start of a paragraph "* " / "1. " lists and
"---" lines. Each correction is its own undo step (Ctrl+Z puts the typed text
back), as in Word. The options are the AutoCorrect dialog's (Options >
Proofing > AutoCorrect Options)."""
import os
import re

BOUNDARY = set(" \t.,;:!?)]}\"'”’")
OPENERS = set(" \t([{ \n—–-") | {""}
SENT_END = re.compile(r"[.!?][\"'”’)\]]*\s+$")
DAYS = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
WORD = re.compile(r"[\w'’]+$", re.UNICODE)


class AutoCorrect:
    def __init__(self, win):
        self.win = win
        self._list = None
        self._exc = None
        self._path = None
        self.busy = False
        self.last = None        # (para, start, typed, replacement): for the AutoCorrect options button

    @property
    def ed(self):
        return self.win.engine.ed

    def opt(self, key, default=True):
        try:
            return bool(self.win.app.settings.get(key, default))
        except Exception:
            return default

    # ------------------------------------------------------------ the lists
    def _load(self):
        from .. import autocorrect as AC
        try:
            user = os.path.join(self.win.app.engine_profile, "user")
            AC.install(user)
            path = AC.user_list_path(user, "en-US") or AC.user_list_path(user)
        except Exception:
            path = None
        if path is None:
            for lang in ("en-US", "en-GB"):
                path = AC._share_file(lang)
                if path:
                    break
        try:
            mtime = os.path.getmtime(path) if path else 0
        except OSError:
            mtime = 0
        if self._list is not None and (path, mtime) == self._path:
            return
        self._path = (path, mtime)
        entries = AC.read_list(path) if path else []
        self._list = {}
        for a, b in list(AC.EXTRA) + list(entries):
            self._list[a] = b
        self._exc = set()
        if path:
            try:
                files = AC._read_all(path)
                xml = files.get("SentenceExceptList.xml", b"").decode("utf-8", "replace")
                self._exc = {AC._unescape(a).lower() for a in re.findall(r'abbreviated-name="([^"]*)"', xml)}
                xml = files.get("WordExceptList.xml", b"").decode("utf-8", "replace")
                self._two_caps_exc = {AC._unescape(a) for a in re.findall(r'abbreviated-name="([^"]*)"', xml)}
            except Exception:
                pass

    def lookup(self, token):
        self._load()
        rep = self._list.get(token)
        if rep is not None:
            return rep
        low = token.lower()
        rep = self._list.get(low)
        if rep is None or low == token:
            return None
        # keep the capital the user typed
        if token[:1].isupper() and token[1:] == low[1:]:
            return rep[:1].upper() + rep[1:]
        if token.isupper() and len(token) > 1:
            return rep.upper()
        return None

    # ------------------------------------------------------------ editing
    def _before(self):
        p, off = self.ed.caret_pos()
        return p, off, self.ed.para_text_of(p)[:off]

    def _note(self, kind):
        aw = getattr(self.win, "acwatch", None)
        if aw is not None and self.last is not None:
            try:
                aw.note(self.last[2], self.last[3], kind)
            except Exception as e:
                print("autocorrect button:", e)

    def _replace(self, p, a, b, new, label="AutoCorrect"):
        ed = self.ed
        old = ed.para_text_of(p)[a:b]
        keep = ed.caret_pos()
        ed.begin_group(label)
        try:
            ed.select_nodes(p, a, p, b)
            ed.type_text(new)
            delta = len(new) - (b - a)
            ed.select_nodes(keep[0], keep[1] + delta, keep[0], keep[1] + delta)
        finally:
            ed.end_group()
        self.last = (p, a, old, new)
        return True

    # ------------------------------------------------------------ hooks
    def typed(self, ch):
        """After a character went in: corrections it triggers."""
        if self.busy or self.ed is None or not ch or len(ch) != 1:
            return False
        if self.ed.story() not in ("body", "textbox", "hf", "notes"):
            return False
        self.busy = True
        try:
            done = False
            if ch in "\"'" and self.opt("ac_quotes"):
                done = self._quote(ch)
            if ch == " " and self._autoformat_start():
                return True
            if ch in BOUNDARY or ch in "\"'":
                done = self._word_end(skip=1) or done
            return done
        except Exception as e:
            print("autocorrect:", e)
            return False
        finally:
            self.busy = False

    def before_break(self):
        """Enter pressed: the word before it is finished too, and "---" lines."""
        if self.busy or self.ed is None:
            return False
        self.busy = True
        try:
            done = self._word_end(skip=0)
            h = self._heading_line()
            if h:
                return h
            done = self._border_line() or done
            done = self._table_line() or done
            return done
        except Exception as e:
            print("autocorrect:", e)
            return False
        finally:
            self.busy = False

    # ------------------------------------------------------------ quotes
    def _quote(self, ch):
        p, off, text = self._before()
        prev = text[-2:-1] if len(text) >= 2 else ""
        if ch == '"':
            new = "“" if prev in OPENERS or prev in "“‘" else "”"
        else:
            if prev.isalnum():
                new = "’"            # an apostrophe: don’t, Bob’s
            else:
                new = "‘" if prev in OPENERS or prev in "“" else "’"
        return self._replace(p, off - 1, off, new, "Smart Quotes")

    # ------------------------------------------------------------ words
    def _word_end(self, skip):
        """The token before the boundary (skip: the boundary characters
        already typed after it)."""
        p, off, text = self._before()
        end = off - skip
        if end <= 0:
            return False
        body = text[:end]
        start = max(body.rfind(" "), body.rfind("\t"), body.rfind(" ")) + 1
        token = body[start:]
        if not token:
            return False
        done = False
        lead_marker = start == 0 and text[end:end + 1] in (".", ")") and \
            bool(re.fullmatch(r"\(?([a-zA-Z]|[ivxlcdmIVXLCDM]{1,4})", token))
        # the replacement list, with the whole token ("(c)", ":)") or the word
        if self.opt("ac_replace") and not lead_marker:
            rep = self.lookup(token)
            t0, t1 = start, end
            if rep is None:
                m = re.match(r"^([\(\[\"“‘']*)(.*?)([\)\]\"”’'.,;:!?]*)$", token)
                core = m.group(2) if m else token
                if core and core != token:
                    rep = self.lookup(core)
                    t0 = start + len(m.group(1))
                    t1 = t0 + len(core)
            if rep is not None and rep != body[t0:t1]:
                self._replace(p, t0, t1, rep)
                self._note("replace")
                p, off, text = self._before()
                end = off - skip
                body = text[:end]
                token = body[start:]
                done = True
        # dashes: "word -- word" and "word--word"
        if self.opt("ac_dashes"):
            m = re.search(r"(\w)( ?)--( ?)(\w+)$", body)
            if m:
                a = m.start(2)
                b = m.end(3)
                spaced = bool(m.group(2) or m.group(3))
                self._replace(p, a, b, " – " if spaced else "—")
                p, off, text = self._before()
                end = off - skip
                body = text[:end]
                token = body[max(body.rfind(" "), body.rfind("\t")) + 1:]
                done = True
        word_m = WORD.search(body)
        word = word_m.group() if word_m else ""
        w0 = word_m.start() if word_m else end
        # TWo INitial CApitals
        if self.opt("ac_two_caps") and len(word) > 2 and word[0].isupper() and word[1].isupper() \
                and word[2:].islower() and word not in getattr(self, "_two_caps_exc", set()):
            self._replace(p, w0, w0 + len(word), word[0] + word[1].lower() + word[2:])
            self._note("caps")
            done = True
        # a capital at the start of a sentence
        # "a)" "i." "(c)" at the start of a paragraph may be a list starting: left alone
        marker = body[:w0] in ("", "(") and text[end:end + 1] in (".", ")") and (
            len(word) == 1 or all(c in "ivxlcdm" for c in word.lower())) and len(word) <= 4
        if self.opt("ac_caps_first") and word and word[0].islower() and not marker and self._sentence_start(body[:w0]):
            if not (word.startswith(("http", "www")) or "@" in token) and \
                    not (self.ed.cell_name() and not self.opt("ac_caps_cells") and not body[:w0].strip()):
                self._replace(p, w0, w0 + len(word), word[0].upper() + word[1:])
                self._note("caps")
                done = True
                word = word[0].upper() + word[1:]
        # names of days
        if self.opt("ac_days") and word.lower() in DAYS and word == word.lower():
            self._replace(p, w0, w0 + len(word), word.capitalize())
            self._note("days")
            done = True
        # ordinals: 1st, 22nd, 3rd, 4th
        if self.opt("ac_ordinals"):
            m = re.search(r"\b(\d+)(st|nd|rd|th)$", body)
            if m:
                ed = self.ed
                keep = ed.caret_pos()
                ed.select_nodes(p, m.start(2), p, m.end(2))
                ed.apply_run([("w:vertAlign", [("w:val", "superscript")])], "AutoFormat")
                ed.select_nodes(keep[0], keep[1], keep[0], keep[1])
                done = True
        # internet and e-mail addresses become links
        if self.opt("ac_urls") and re.match(r"^(https?://|www\.)\S+\.\S+$|^[\w.+-]+@[\w-]+\.[\w.]+$", token.rstrip(".,;:!?)")):
            url = token.rstrip(".,;:!?)")
            target = url if "://" in url else ("mailto:" + url if "@" in url else "http://" + url)
            ed = self.ed
            keep = ed.caret_pos()
            ed.select_nodes(p, start, p, start + len(url))
            ed.insert_hyperlink(target, url)
            ed.select_nodes(keep[0], keep[1], keep[0], keep[1])
            done = True
        return done

    def _sentence_start(self, before):
        s = before.rstrip("\"“‘'([")
        if not s.strip():
            return True
        if not SENT_END.search(s):
            return False
        prev = s.rstrip().split()[-1] if s.split() else ""
        self._load()
        if prev.lower() in self._exc:
            return False
        # "e.g." "U.S." and single letters with a stop
        if re.match(r"^(\w\.){2,}$", prev):
            return False
        return True

    # ------------------------------------------------------------ paragraph starts
    NUMBERED = re.compile(r"^(\(?)(\d{1,3}|[a-zA-Z]|[ivxlcdm]{1,6}|[IVXLCDM]{1,6})([.)])\s$")

    @staticmethod
    def _roman(t):
        vals = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}
        t = t.lower()
        n = 0
        for k, ch in enumerate(t):
            v = vals[ch]
            n += -v if k + 1 < len(t) and vals[t[k + 1]] > v else v
        return n

    def _autoformat_start(self):
        p, off, text = self._before()
        if self.ed.list_info() is not None:
            return False
        if text in ("* ", "- ", "> ", "• ", "-> ") and self.opt("ac_bullets", self.opt("ac_lists")):
            self._start_list(p, off, "bullet", text.strip())
            return True
        m = self.NUMBERED.match(text)
        if not m or not self.opt("ac_numbers", self.opt("ac_lists")):
            return False
        opn, mark, close = m.groups()
        if opn and close != ")":
            return False
        if mark.isdigit():
            fmt, start = "decimal", int(mark)
        elif len(mark) == 1 and mark.lower() not in "ivx" or len(mark) == 1 and mark.lower() in "vx":
            fmt = "lowerLetter" if mark.islower() else "upperLetter"
            start = ord(mark.lower()) - ord("a") + 1
        elif all(c in "ivxlcdm" for c in mark.lower()) and (mark.islower() or mark.isupper()):
            fmt = "lowerRoman" if mark.islower() else "upperRoman"
            start = self._roman(mark)
        else:
            return False
        label = ("(" if opn else "") + "%1" + close
        self._start_list(p, off, "number", fmt, label, start)
        return True

    def _start_list(self, p, off, kind, mark, label="%1.", start=1):
        ed = self.ed
        ed.begin_group("AutoFormat")
        try:
            ed.select_nodes(p, 0, p, off)
            ed.delete(True, False)
            if kind == "bullet":
                ed.toggle_list("bullet")
                glyph = {"-": "–", ">": "➢", "->": "➢"}.get(mark)
                if glyph:
                    try:
                        ed.set_list_format("bullet", glyph, None)
                    except Exception:
                        pass
            else:
                ed.toggle_list("number")
                try:
                    ed.set_list_format(mark, label, None, start)
                except Exception:
                    pass
        finally:
            ed.end_group()
        self.last = None

    def _border_line(self):
        if not self.opt("ac_borders"):
            return False
        p, off, text = self._before()
        kinds = {"---": ("single", "6"), "===": ("double", "6"), "___": ("single", "18"),
                 "***": ("dotted", "18"), "~~~": ("wave", "6"), "###": ("thinThickThinSmallGap", "18")}
        k = text.strip()
        if k not in kinds or text != k or self.ed.para_text_of(p) != text:
            return False
        val, sz = kinds[k]
        ed = self.ed
        border = [("bottom", [("w:val", val), ("w:sz", sz), ("w:space", "1"), ("w:color", "auto")])]
        ed.begin_group("AutoFormat")
        try:
            ed.select_nodes(p, 0, p, off)
            ed.delete(True, False)
            # the line goes under the paragraph above, as in the original; the
            # caret stays in the (now empty) paragraph after it
            ed.move_caret("left", False)
            above = tuple(ed.caret_pos())[0] != p and not ed.cell_name()
            if above:
                ed.set_borders("paras", border)
                ed.move_caret("right", False)
            else:
                ed.select_nodes(p, 0, p, 0)
                ed.set_borders("paras", border)
        finally:
            ed.end_group()
        if above:
            self.win.engine.view.after_edit()
            return "handled"
        return True

    def _heading_line(self):
        """Built-in Heading styles: a short line without a full stop, then Enter
        twice, becomes Heading 1 (off unless chosen, as in the original)."""
        if not self.opt("ac_headings", False):
            return False
        ed = self.ed
        p, off, text = self._before()
        if text or ed.para_text_of(p) or ed.cell_name() or ed.list_info() is not None:
            return False
        ed.move_caret("left", False)
        prev = ed.caret_pos()[0]
        t = ed.para_text_of(prev).strip()
        style = (ed.state() or {}).get("style", "")
        words = t.split()
        ok = prev != p and 0 < len(words) <= 10 and t[:1].isupper() and t[-1:] not in ".!?:;," \
            and style in ("Normal", "Body Text", "")
        if not ok:
            ed.move_caret("right", False)
            return False
        ed.begin_group("AutoFormat")
        try:
            sid = {n: i for i, n in ed.paragraph_styles()}.get("Heading 1")
            if sid:
                ed.set_style(sid)
            ed.move_caret("right", False)
        finally:
            ed.end_group()
        self.win.engine.view.after_edit()
        return "handled"

    def _table_line(self):
        """+----+----+ then Enter: a table with a column per gap."""
        if not self.opt("ac_tables"):
            return False
        p, off, text = self._before()
        if not re.fullmatch(r"\+(-+\+)+", text.strip()) or text != text.strip():
            return False
        cols = text.count("+") - 1
        ed = self.ed
        ed.begin_group("AutoFormat")
        try:
            ed.select_nodes(p, 0, p, off)
            ed.delete(True, False)
            ed.insert_table(1, cols)
        finally:
            ed.end_group()
        self.win.engine.view.after_edit()
        return "table"

    # ------------------------------------------------------------ undo the last one
    def undo_last(self):
        """Change back to what was typed (the AutoCorrect options button)."""
        if not self.last:
            return False
        p, a, old, new = self.last
        text = self.ed.para_text_of(p)
        if text[a:a + len(new)] != new:
            return False
        self._replace(p, a, a + len(new), old, "Undo AutoCorrect")
        self.last = None
        return True
