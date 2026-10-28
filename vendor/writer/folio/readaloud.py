"""Read Aloud (Review > Read Aloud, Ctrl+Alt+Space): reads the document from
the cursor, highlighting each word, with a small player in the corner; and
the Immersive Reader view."""
import re
import shutil
import subprocess
import threading

from gi.repository import GLib, Gtk, Pango

from . import icons
from ._lazy import docapi

WORD_RE = re.compile(r"[\w’'\-]+[.,;:!?]?", re.U)


# ------------------------------------------------------------ speech back ends
class Speaker:
    """Speaks one paragraph at a time; calls on_word(i) as word i starts and
    on_done() at the end."""

    def __init__(self):
        self.client = None
        self.proc = None
        self.rate = 0            # -100..100
        self.voice = None
        self._gen = 0
        self.speechd = None
        try:
            import speechd
        except Exception:
            speechd = None
        if speechd is not None:
            # connecting can hang if the speech service is stuck: give it 3 s
            box = {}

            def connect():
                try:
                    c = speechd.SSIPClient("folio-writer")
                    c.set_data_mode(speechd.DataMode.SSML)
                    box["c"] = c
                except Exception:
                    pass
            th = threading.Thread(target=connect, daemon=True)
            th.start()
            th.join(3.0)
            if "c" in box:
                self.speechd = speechd
                self.client = box["c"]
        # all calls to the speech service run in order on one worker thread,
        # so a slow or stuck service never freezes the window
        import queue
        self._q = queue.Queue()

        def worker():
            while True:
                fn = self._q.get()
                try:
                    fn()
                except Exception as e:
                    print("speech:", e)
        threading.Thread(target=worker, daemon=True).start()
        self.espeak = shutil.which("espeak-ng") or shutil.which("espeak")

    @property
    def available(self):
        return self.client is not None or self.espeak is not None

    def voices(self):
        if self.client is not None:
            box = []
            th = threading.Thread(target=lambda: box.append(
                [v[0] for v in self.client.list_synthesis_voices()][:60]), daemon=True)
            th.start()
            th.join(1.5)
            return box[0] if box else []
        return []

    def speak(self, words, on_word, on_done):
        self.stop()
        self._gen += 1
        gen = self._gen
        if self.client is not None:
            ssml = "<speak>" + " ".join(
                '<mark name="%d"/>%s' % (i, GLib.markup_escape_text(w))
                for i, w in enumerate(words)) + "</speak>"

            def cb(kind, index_mark=None):
                if gen != self._gen:
                    return
                if kind == self.speechd.CallbackType.INDEX_MARK and index_mark is not None:
                    GLib.idle_add(lambda: (on_word(int(index_mark)), False)[1])
                elif kind == self.speechd.CallbackType.END:
                    GLib.idle_add(lambda: (on_done(), False)[1])
            client, rate, voice = self.client, int(self.rate), self.voice
            types = (self.speechd.CallbackType.INDEX_MARK, self.speechd.CallbackType.END)

            def go():
                client.set_rate(rate)
                if voice:
                    client.set_synthesis_voice(voice)
                client.speak(ssml, callback=cb, event_types=types)
            self._q.put(go)
            return
        if self.espeak is None:
            return
        # espeak: speak the paragraph and move the highlight along by timing
        wpm = int(175 * (1 + self.rate / 100.0 * 0.8))
        try:
            self.proc = subprocess.Popen([self.espeak, "-s", str(max(80, wpm)),
                                          " ".join(words)],
                                         stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL)
        except OSError:
            self.proc = None
            return
        per_char = 60.0 / max(80, wpm) / 5.5
        t = 0.0
        for i, w in enumerate(words):
            GLib.timeout_add(int(t * 1000), lambda i=i, g=gen: (
                on_word(i) if g == self._gen else None, False)[1])
            t += max(0.18, len(w) * per_char) + 0.05
        proc = self.proc

        def wait():
            proc.wait()
            if gen == self._gen and proc.returncode == 0:
                GLib.idle_add(lambda: (on_done(), False)[1])
        threading.Thread(target=wait, daemon=True).start()

    def pause(self):
        if self.client is not None:
            self._q.put(self.client.pause)
        elif self.proc is not None and self.proc.poll() is None:
            self.proc.send_signal(19)          # SIGSTOP

    def resume(self):
        if self.client is not None:
            self._q.put(self.client.resume)
        elif self.proc is not None and self.proc.poll() is None:
            self.proc.send_signal(18)          # SIGCONT

    def stop(self):
        self._gen += 1
        if self.client is not None:
            self._q.put(self.client.cancel)
        if self.proc is not None and self.proc.poll() is None:
            try:
                self.proc.send_signal(18)
                self.proc.terminate()
            except Exception:
                pass
        self.proc = None


# ------------------------------------------------------------ sources
class DocSource:
    """Paragraphs of the document body from the cursor on."""

    def __init__(self, win):
        self.win = win
        m = win.engine.model
        self.paras = []
        body = m.getText()
        here = docapi.read_cursor(m).getStart()
        en = body.createEnumeration()
        started = False
        while en.hasMoreElements():
            p = en.nextElement()
            if not p.supportsService("com.sun.star.text.Paragraph"):
                continue
            if not started:
                try:
                    if body.compareRegionEnds(p, here) > 0:
                        continue
                except Exception:
                    pass
                started = True
            if p.getString().strip():
                self.paras.append(p)
        self.first_offset = 0
        if self.paras:
            try:
                c = body.createTextCursorByRange(self.paras[0].getStart())
                c.gotoRange(here, True)
                self.first_offset = len(c.getString())
            except Exception:
                pass

    def __len__(self):
        return len(self.paras)

    def words(self, i):
        text = self.paras[i].getString()
        start = self.first_offset if i == 0 else 0
        out = [(mm.start(), mm.end() - mm.start(), mm.group())
               for mm in WORD_RE.finditer(text) if mm.start() >= start]
        return out

    def highlight(self, i, start, length):
        m = self.win.engine.model
        p = self.paras[i]
        try:
            c = p.getText().createTextCursorByRange(p.getStart())
            c.goRight(start, False)
            c.goRight(length, True)
            docapi.controller(m).select(c)
        except Exception:
            pass

    def clear(self):
        pass


class ReadAloud:
    def __init__(self, win):
        self.win = win
        self.speaker = None
        self.source = None
        self.para = 0
        self.words = []
        self.playing = False
        self.bar = None

    def toggle(self, source=None):
        if self.bar is not None and self.bar.get_visible():
            if self.playing:
                self.pause()
            else:
                self.play()
            return
        self.start(source)

    def start(self, source=None):
        if self.speaker is None:
            self.speaker = Speaker()
        if not self.speaker.available:
            self.win.dialogs.message("Read Aloud needs a speech engine. Install the "
                                     "speech-dispatcher or espeak-ng package.")
            return
        if source is None and getattr(self.win.engine, "native", False):
            from .native.views import DocSource as _NativeSource
            source = _NativeSource(self.win)
        self.source = source or DocSource(self.win)
        if not len(self.source):
            self.win.status.flash("There's no text to read from here.")
            return
        self.para = 0
        self._show_bar()
        self.play()

    def _speak_para(self):
        if self.para >= len(self.source):
            self.stop()
            return
        self.words = self.source.words(self.para)
        if not self.words:
            self.para += 1
            self._speak_para()
            return
        self.speaker.speak([w for _s, _l, w in self.words], self._on_word, self._on_done)

    def _on_word(self, i):
        if 0 <= i < len(self.words) and self.playing:
            s, n, _w = self.words[i]
            self.source.highlight(self.para, s, n)

    def _on_done(self):
        if not self.playing:
            return
        self.para += 1
        self._speak_para()

    def play(self):
        if self.playing:
            return
        resumed = getattr(self, "_paused", False)
        self.playing = True
        self._paused = False
        self._set_play_icon()
        if resumed:
            self.speaker.resume()
        else:
            self._speak_para()

    def pause(self):
        self.playing = False
        self._paused = True
        self.speaker.pause()
        self._set_play_icon()

    def step(self, n):
        self.speaker.stop()
        self._paused = False
        self.para = max(0, min(len(self.source) - 1, self.para + n))
        self.playing = True
        self._set_play_icon()
        self._speak_para()

    def stop(self):
        self.playing = False
        self._paused = False
        if self.speaker is not None:
            self.speaker.stop()
        if self.source is not None:
            self.source.clear()
        if self.bar is not None:
            self.bar.hide()

    # ------------------------------------------------------------ player bar
    def _show_bar(self):
        if self.bar is None:
            self.bar = self._make_bar()
            self.win.canvas_overlay.add_overlay(self.bar)
        self.bar.show_all()

    def _make_bar(self):
        bar = Gtk.Box(spacing=2)
        bar.get_style_context().add_class("folio-readaloud")
        bar.set_halign(Gtk.Align.END)
        bar.set_valign(Gtk.Align.START)
        bar.set_margin_top(8)
        bar.set_margin_end(24)
        bar.set_no_show_all(False)

        def b(icon, tip, cb):
            btn = Gtk.Button()
            btn.set_relief(Gtk.ReliefStyle.NONE)
            btn.add(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON))
            btn.set_tooltip_text(tip)
            btn.set_focus_on_click(False)
            btn.connect("clicked", lambda *_: cb())
            bar.pack_start(btn, False, False, 0)
            return btn
        b("media-skip-backward-symbolic", "Previous", lambda: self.step(-1))
        self.play_btn = b("media-playback-pause-symbolic", "Pause",
                          lambda: self.pause() if self.playing else self.play())
        b("media-skip-forward-symbolic", "Next", lambda: self.step(1))
        sett = Gtk.MenuButton()
        sett.set_relief(Gtk.ReliefStyle.NONE)
        sett.add(Gtk.Image.new_from_icon_name("emblem-system-symbolic", Gtk.IconSize.BUTTON))
        sett.set_tooltip_text("Settings")
        pop = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=10)
        box.pack_start(Gtk.Label(label="Reading speed", xalign=0), False, False, 0)
        speed = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, -80, 80, 10)
        speed.set_value(self.speaker.rate if self.speaker else 0)
        speed.set_draw_value(False)
        speed.set_size_request(200, -1)
        speed.connect("value-changed", lambda s: setattr(self.speaker, "rate", s.get_value()))
        box.pack_start(speed, False, False, 0)
        voices = self.speaker.voices() if self.speaker else []
        if voices:
            box.pack_start(Gtk.Label(label="Voice selection", xalign=0), False, False, 0)
            vc = Gtk.ComboBoxText()
            for v in voices:
                vc.append_text(v)
            vc.connect("changed", lambda c: setattr(self.speaker, "voice",
                                                    c.get_active_text()))
            box.pack_start(vc, False, False, 0)
        box.show_all()
        pop.add(box)
        sett.set_popover(pop)
        bar.pack_start(sett, False, False, 0)
        b("window-close-symbolic", "Stop", self.stop)
        return bar

    def _set_play_icon(self):
        if self.bar is None:
            return
        img = self.play_btn.get_child()
        img.set_from_icon_name("media-playback-pause-symbolic" if self.playing else
                               "media-playback-start-symbolic", Gtk.IconSize.BUTTON)
        self.play_btn.set_tooltip_text("Pause" if self.playing else "Play")


# ------------------------------------------------------------ Immersive Reader
PAGE_COLORS = [("None", "#ffffff", "#1b1b1b"), ("Sepia", "#f5ecd8", "#3b2f1e"),
               ("Inverse", "#121212", "#f2f2f2"), ("Light Blue", "#dbe9f6", "#1b1b1b"),
               ("Light Green", "#e2f0d9", "#1b1b1b"), ("Lavender", "#e9e2f4", "#1b1b1b"),
               ("Light Gray", "#ededed", "#1b1b1b")]
WIDTHS = [("Very Narrow", 360), ("Narrow", 520), ("Moderate", 700), ("Wide", 900)]


class ImmersiveReader(Gtk.Box):
    """A full-window reading view of the document text."""

    def __init__(self, win):
        Gtk.Box.__init__(self, orientation=Gtk.Orientation.VERTICAL)
        self.win = win
        self.width = 700
        self.color = PAGE_COLORS[0]
        self.spacing = False
        self.syllables = False
        self.focus_lines = 0
        self.get_style_context().add_class("folio-immersive")
        self.tv = Gtk.TextView()
        self.tv.set_editable(False)
        self.tv.set_cursor_visible(False)
        self.tv.set_wrap_mode(Gtk.WrapMode.WORD)
        self.tv.set_pixels_below_lines(14)
        self.buf = self.tv.get_buffer()
        self.hl = self.buf.create_tag("hl", background="#c5dcf5")
        self.sw = Gtk.ScrolledWindow()
        self.sw.add(self.tv)
        self.sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.pack_start(self.sw, True, True, 0)
        self.focus_area = Gtk.DrawingArea()
        self.tv.connect_after("draw", self._draw_focus)
        self.connect("size-allocate", lambda *_: self._margins())
        self.css = Gtk.CssProvider()
        self.tv.get_style_context().add_provider(self.css, 800)
        self.paras = []

    def load(self):
        if getattr(self.win.engine, "native", False):
            from .native.views import immersive_paras
            self.buf.set_text("")
            self.paras = []
            heading_tags = {}
            for text, lvl in immersive_paras(self.win, self.syllables):
                start = self.buf.get_end_iter().get_offset()
                if lvl:
                    tag = heading_tags.get(lvl)
                    if tag is None:
                        tag = self.buf.create_tag(None, weight=Pango.Weight.BOLD,
                                                  scale=max(1.0, 1.6 - lvl * 0.15))
                        heading_tags[lvl] = tag
                    self.buf.insert_with_tags(self.buf.get_end_iter(), text + "\n", tag)
                else:
                    self.buf.insert(self.buf.get_end_iter(), text + "\n")
                self.paras.append((start, text))
            self.apply_look()
            return
        m = self.win.engine.model
        self.buf.set_text("")
        self.paras = []
        heading_tags = {}
        en = m.getText().createEnumeration()
        while en.hasMoreElements():
            p = en.nextElement()
            if not p.supportsService("com.sun.star.text.Paragraph"):
                continue
            text = p.getString()
            if not text.strip():
                continue
            lvl = 0
            try:
                lvl = p.OutlineLevel or 0
            except Exception:
                pass
            if self.syllables:
                text = syllabify(m, text)
            start = self.buf.get_end_iter().get_offset()
            if lvl:
                tag = heading_tags.get(lvl)
                if tag is None:
                    tag = self.buf.create_tag(None, weight=Pango.Weight.BOLD,
                                              scale=max(1.0, 1.6 - lvl * 0.15))
                    heading_tags[lvl] = tag
                self.buf.insert_with_tags(self.buf.get_end_iter(), text + "\n", tag)
            else:
                self.buf.insert(self.buf.get_end_iter(), text + "\n")
            self.paras.append((start, text))
        self.apply_look()

    def apply_look(self):
        name, bg, fg = self.color
        self.css.load_from_data(("textview, textview text { background: %s; color: %s; "
                                 "font-size: 17pt; letter-spacing: %s; "
                                 "font-family: 'Carlito', 'Calibri', sans-serif; }"
                                 % (bg, fg, "2px" if self.spacing else "0px")).encode())
        self.tv.set_pixels_below_lines(24 if self.spacing else 14)
        self.tv.set_pixels_inside_wrap(10 if self.spacing else 4)
        self._margins()
        self.tv.queue_draw()

    def _margins(self):
        w = self.get_allocated_width()
        side = max(24, (w - self.width) // 2)
        self.tv.set_left_margin(side)
        self.tv.set_right_margin(side)
        self.tv.set_top_margin(40)

    def _draw_focus(self, tv, cr):
        if not self.focus_lines:
            return False
        # dim everything except a band of lines in the middle of the view
        alloc = tv.get_allocation()
        line_h = 17 * 1.33 + (10 if self.spacing else 4)
        band = line_h * self.focus_lines + 8
        vis = tv.get_visible_rect()
        mid = vis.height / 2.0
        cr.set_source_rgba(0, 0, 0, 0.55)
        cr.rectangle(0, vis.y, alloc.width, mid - band / 2)
        cr.rectangle(0, vis.y + mid + band / 2, alloc.width, vis.height)
        cr.fill()
        return False

    # read-aloud source interface
    def source(self):
        reader = self

        class Src:
            def __len__(self):
                return len(reader.paras)

            def words(self, i):
                text = reader.paras[i][1]
                return [(mm.start(), mm.end() - mm.start(), mm.group())
                        for mm in WORD_RE.finditer(text)]

            def highlight(self, i, start, length):
                base = reader.paras[i][0]
                b = reader.buf
                b.remove_tag(reader.hl, b.get_start_iter(), b.get_end_iter())
                s = b.get_iter_at_offset(base + start)
                e = b.get_iter_at_offset(base + start + length)
                b.apply_tag(reader.hl, s, e)
                reader.tv.scroll_to_iter(s, 0.2, False, 0, 0)

            def clear(self):
                b = reader.buf
                b.remove_tag(reader.hl, b.get_start_iter(), b.get_end_iter())
        return Src()


def syllabify(m, text):
    """Words broken into syllables with middle dots (Immersive Reader)."""
    try:
        from . import bridge
        lsm = bridge.create("com.sun.star.linguistic2.LinguServiceManager")
        hy = lsm.getHyphenator()
        loc = docapi.doc_locale(m)
    except Exception:
        return text

    def one(mm):
        w = mm.group()
        if len(w) < 4:
            return w
        try:
            ph = hy.createPossibleHyphens(w, loc, ())
            if ph is None:
                return w
            pos = list(ph.getHyphenationPositions())
        except Exception:
            return w
        out, last = [], 0
        for p in pos:
            out.append(w[last:p + 1])
            last = p + 1
        out.append(w[last:])
        return "·".join(x for x in out if x)
    return re.sub(r"[A-Za-z]{4,}", one, text)
