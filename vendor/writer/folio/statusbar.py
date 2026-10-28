"""Status bar: page, words, language | views, zoom."""
import re

from gi.repository import GLib, Gtk


def _num(s):
    try:
        return int(s.replace(",", "").replace(".", ""))
    except ValueError:
        return 0


LANG_NAMES = {"en-US": "English (United States)", "en-GB": "English (United Kingdom)",
              "nl-NL": "Dutch (Netherlands)", "de-DE": "German (Germany)",
              "fr-FR": "French (France)", "es-ES": "Spanish (Spain)"}


# (key, menu label, shown by default)
ITEMS = [("formatted_page", "Formatted Page Number", False), ("section", "Section", False),
         ("page", "Page Number", True), ("vpos", "Vertical Page Position", False),
         ("line", "Line Number", False), ("column", "Column", False),
         ("words", "Word Count", True), ("chars", "Character Count (with spaces)", False),
         ("proof", "Spelling and Grammar Check", True), ("lang", "Language", True),
         ("a11y", "Accessibility Checker", True), ("track", "Track Changes", False),
         ("caps", "Caps Lock", False), ("overtype", "Overtype", False),
         ("focus", "Focus", True), ("views", "View Shortcuts", True),
         ("zoomslider", "Zoom Slider", True), ("zoom", "Zoom", True)]


def cursor_metrics(m, want_line):
    """{'section', 'vpos' (mm100 from page top), 'line', 'column', 'page_label'}."""
    from . import docapi
    out = {}
    vc = docapi.view_cursor(m)
    try:
        y = vc.getPosition().Y
        out["y"] = y
    except Exception:
        y = None
    # section: page-style breaks and continuous sections before the cursor
    try:
        body = m.getText()
        here = vc.getStart()
        n = 1
        en = body.createEnumeration()
        first = True
        while en.hasMoreElements():
            p = en.nextElement()
            try:
                if body.compareRegionStarts(p.getStart(), here) < 0:
                    break
            except Exception:
                break
            if not first:
                try:
                    if p.supportsService("com.sun.star.text.Paragraph") and p.PageDescName:
                        n += 1
                except Exception:
                    pass
            first = False
        secs = m.getTextSections()
        for i in range(secs.getCount()):
            sec = secs.getByIndex(i)
            try:
                if sec.getName().startswith("Folio") or sec.getParentSection() is not None:
                    continue
                if body.compareRegionStarts(sec.getAnchor().getStart(), here) > 0:
                    n += 1
            except Exception:
                pass
        out["section"] = n
    except Exception:
        pass
    # line counting moves the view cursor; outside the main text putting it
    # back would land on another page's copy of the header/footer
    in_body = False
    try:
        in_body = "HeadFoot" not in vc.getText().getImplementationName()
    except Exception:
        pass
    if want_line and vc.isCollapsed() and in_body:
        # the engine coalesces cursor updates, so only the restored position
        # is ever drawn
        try:
            rng = vc.getText().createTextCursorByRange(vc.getStart())
            try:
                col = 1
                vc.gotoStartOfLine(True)
                col = len(vc.getString()) + 1
                vc.gotoRange(rng, False)
                target = vc.getPosition().Y
                vc.jumpToStartOfPage()
                line = 1
                last = None
                while line < 400:
                    py = vc.getPosition().Y
                    if py >= target - 5 or py == last:
                        break
                    last = py
                    if not vc.goDown(1, False):
                        break
                    line += 1
                out["line"], out["column"] = line, col
            finally:
                vc.gotoRange(rng, False)
        except Exception as e:
            print("line:", e)
    return out


class StatusBar(Gtk.Box):
    def __init__(self, window):
        Gtk.Box.__init__(self, spacing=2)
        self.win = window
        self._busy = False
        self.get_style_context().add_class("folio-status")
        self.connect("button-press-event", self._menu)
        self.add_events(__import__("gi.repository.Gdk", fromlist=["Gdk"]).EventMask
                        .BUTTON_PRESS_MASK)
        self.formatted_page = Gtk.Label(label="Page 1")
        self.section = Gtk.Label(label="Section: 1")
        self.vpos = Gtk.Label(label="At: 2.5cm")
        self.line = Gtk.Label(label="Line: 1")
        self.column = Gtk.Label(label="Column: 1")
        self.chars = Gtk.Label(label="0 characters")
        self.caps = Gtk.Label(label="")
        self.overtype = Gtk.Button(label="Insert")
        self.overtype.connect("clicked", lambda *_: window.engine.command(".uno:InsertMode"))
        self.a11y = Gtk.Button(label="Accessibility: Good to go")
        self.a11y.connect("clicked", lambda *_: window.run("check-accessibility"))
        for w in (self.formatted_page, self.section, self.vpos, self.line, self.column,
                  self.chars, self.caps):
            w.set_margin_start(6)
            w.set_margin_end(6)
        self._metric_timer = None
        self.page = Gtk.Button(label="Page 1 of 1")
        self.page.set_tooltip_text("Page number in document. Click to open the Go To dialog.")
        self.page.connect("clicked", lambda *_: window.run("goto"))
        self.words = Gtk.Button(label="0 words")
        self.words.set_tooltip_text("Word count. Click to open the Word Count dialog.")
        self.words.connect("clicked", lambda *_: window.run("word-count"))
        self.proof = Gtk.Button()
        self.proof_img = Gtk.Image()
        self.proof.add(self.proof_img)
        self.proof.set_tooltip_text("No proofing errors")
        self.proof.connect("clicked", lambda *_: window.run("spelling"))
        self._proof_timer = None
        self.set_proof(None)
        self.lang = Gtk.Button(label="English (United States)")
        self.lang.set_tooltip_text("Language. Click to change the proofing language.")
        self.lang.connect("clicked", lambda *_: window.run("language-dialog"))
        self.track = Gtk.Label(label="")
        self.track_item = Gtk.Button(label="Track Changes: Off")
        self.track_item.connect("clicked", lambda *_: window.engine.command(".uno:TrackChanges"))
        for w in (self.formatted_page, self.section, self.page, self.vpos, self.line,
                  self.column, self.words, self.chars, self.proof, self.lang, self.a11y,
                  self.track_item, self.caps, self.overtype):
            self.pack_start(w, False, False, 0)
        self.pack_start(self.track, False, False, 6)
        # a macro being recorded: a small stop square, as in the original
        self.rec_btn = Gtk.Button()
        self.rec_btn.add(Gtk.Image.new_from_icon_name("media-playback-stop-symbolic",
                                                      Gtk.IconSize.MENU))
        self.rec_btn.set_tooltip_text("A macro is being recorded. Click to stop recording.")
        self.rec_btn.connect("clicked", lambda *_: window.run("stop-recording"))
        self.rec_btn.set_no_show_all(True)
        self.pack_start(self.rec_btn, False, False, 0)

        right = Gtk.Box(spacing=2)
        self.focus_btn = Gtk.Button(label="Focus")
        self.focus_btn.set_tooltip_text("Focus mode: hide the ribbon and status bar (Esc to leave)")
        self.focus_btn.connect("clicked", lambda *_: window.run("focus-mode"))
        right.pack_start(self.focus_btn, False, False, 6)
        self.views_box = Gtk.Box(spacing=2)
        right.pack_start(self.views_box, False, False, 0)
        self.view_btns = {}
        for name, icon, tip in (("read", "read-mode", "Read Mode"),
                                ("print", "cmd/sc_printlayout", "Print Layout"),
                                ("web", "cmd/sc_browseview", "Web Layout")):
            from . import icons
            b = Gtk.ToggleButton()
            b.add(icons.image(icon, 16))
            b.set_tooltip_text(tip)
            b.connect("toggled", self._view_toggled, name)
            self.view_btns[name] = b
            self.views_box.pack_start(b, False, False, 0)
        self.view_btns["print"].set_active(True)
        minus = Gtk.Button(label="−")
        minus.connect("clicked", lambda *_: self.step_zoom(-10))
        self.zoom = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 10, 500, 10)
        self.zoom.set_draw_value(False)
        self.zoom.set_value(100)
        self.zoom.add_mark(100, Gtk.PositionType.BOTTOM, None)
        self._zoom_handler = self.zoom.connect("value-changed", self._zoom_changed)
        plus = Gtk.Button(label="+")
        plus.connect("clicked", lambda *_: self.step_zoom(10))
        self.zoom_pct = Gtk.Button(label="100%")
        self.zoom_pct.set_tooltip_text("Zoom level. Click to open the Zoom dialog.")
        self.zoom_pct.connect("clicked", lambda *_: window.run("zoom-dialog"))
        self.slider_box = Gtk.Box(spacing=2)
        for w in (minus, self.zoom, plus):
            self.slider_box.pack_start(w, False, False, 0)
        right.pack_start(self.slider_box, False, False, 0)
        right.pack_start(self.zoom_pct, False, False, 0)
        self.pack_end(right, False, False, 0)
        self._busy = False
        self.widgets = {"formatted_page": self.formatted_page, "section": self.section,
                        "page": self.page, "vpos": self.vpos, "line": self.line,
                        "column": self.column, "words": self.words, "chars": self.chars,
                        "proof": self.proof, "lang": self.lang, "a11y": self.a11y,
                        "track": self.track_item, "caps": self.caps,
                        "overtype": self.overtype, "focus": self.focus_btn,
                        "views": self.views_box, "zoomslider": self.slider_box,
                        "zoom": self.zoom_pct}
        for w in self.widgets.values():
            w.set_no_show_all(True)
        GLib.idle_add(lambda: (self.apply_items(), False)[1])

    # ------------------------------------------------------------ customize
    def enabled(self):
        st = self.win.app.settings.get("status_items")
        if not isinstance(st, dict):
            st = {}
        return {k: st.get(k, default) for k, _l, default in ITEMS}

    def apply_items(self):
        on = self.enabled()
        for k, w in self.widgets.items():
            if on.get(k):
                w.set_no_show_all(False)
                w.show_all()
                w.set_no_show_all(True)
            else:
                w.hide()
        self.schedule_metrics()

    def _menu(self, w, ev):
        if ev.button != 3:
            return False
        menu = Gtk.Menu()
        on = self.enabled()
        values = self._values()
        menu.append(self._header("Customize Status Bar"))
        for k, label, _d in ITEMS:
            it = Gtk.CheckMenuItem()
            box = Gtk.Box(spacing=24)
            box.pack_start(Gtk.Label(label=label, xalign=0), True, True, 0)
            v = values.get(k, "")
            if v:
                vl = Gtk.Label(label=v, xalign=1)
                vl.get_style_context().add_class("dim-label")
                box.pack_end(vl, False, False, 0)
            it.add(box)
            it.set_active(bool(on.get(k)))
            it.connect("toggled", self._toggle, k)
            menu.append(it)
        menu.show_all()
        menu.attach_to_widget(self, None)
        menu.popup_at_pointer(ev)
        return True

    def _header(self, text):
        it = Gtk.MenuItem()
        lab = Gtk.Label(xalign=0)
        lab.set_markup("<b>%s</b>" % text)
        it.add(lab)
        it.set_sensitive(False)
        return it

    def _toggle(self, item, key):
        st = dict(self.win.app.settings.get("status_items") or {})
        st[key] = item.get_active()
        self.win.app.settings["status_items"] = st
        try:
            self.win.app.save_settings()
        except OSError:
            pass
        for w in self.win.app.windows:
            w.status.apply_items()

    def _values(self):
        return {"formatted_page": self.formatted_page.get_text(),
                "section": self.section.get_text().replace("Section: ", ""),
                "page": self.page.get_label().replace("Page ", ""),
                "vpos": self.vpos.get_text().replace("At: ", ""),
                "line": self.line.get_text().replace("Line: ", ""),
                "column": self.column.get_text().replace("Column: ", ""),
                "words": self.words.get_label().replace(" words", "").replace(" word", ""),
                "chars": self.chars.get_text().replace(" characters", ""),
                "proof": "", "lang": self.lang.get_label(),
                "a11y": self.a11y.get_label().replace("Accessibility: ", ""),
                "track": "On" if self.win.engine.is_on(".uno:TrackChanges") else "Off",
                "caps": "On" if self.caps.get_text() else "Off",
                "overtype": self.overtype.get_label(),
                "zoom": self.zoom_pct.get_label()}

    def schedule_metrics(self, delay=500):
        on = self.enabled()
        if not any(on.get(k) for k in ("section", "vpos", "line", "column", "chars",
                                        "formatted_page")):
            return
        if self._metric_timer:
            GLib.source_remove(self._metric_timer)
        self._metric_timer = GLib.timeout_add(delay, self._metrics)

    def _metrics(self):
        self._metric_timer = None
        m = self.win.engine.model
        if m is None:
            return False
        eqb = getattr(self.win, "eqbar", None)
        if eqb is not None and eqb.ed.active:
            return False
        on = self.enabled()
        try:
            r = cursor_metrics(m, on.get("line") or on.get("column"))
        except Exception as e:
            print("status metrics:", e)
            return False
        if "section" in r:
            self.section.set_text("Section: %d" % r["section"])
        if "line" in r:
            self.line.set_text("Line: %d" % r["line"])
            self.column.set_text("Column: %d" % r["column"])
        if "y" in r:
            try:
                eng = self.win.engine
                from . import docapi
                rects = eng.page_rects()
                top = docapi.page_setup(m)["top"]
                ty = rects[0][1] + (top + r["y"]) * 1440.0 / 2540.0
                for rx, ry, rw, rh in rects:
                    if ry <= ty < ry + rh:
                        from .widgets import fmt_len
                        self.vpos.set_text("At: %s" % fmt_len(int((ty - ry) * 2540 / 1440)))
                        break
            except Exception:
                pass
        if on.get("chars"):
            try:
                from . import docapi
                st = docapi.statistics(m)
                self.chars.set_text("{:,} characters".format(st.get("CharacterCount", 0)))
            except Exception:
                pass
        if on.get("formatted_page"):
            self.formatted_page.set_text(self.page.get_label().split(" of ")[0])
        return False

    def set_recording(self, on):
        if on:
            self.rec_btn.show_all()
        else:
            self.rec_btn.hide()

    def set_caps(self, on):
        self.caps.set_text("Caps Lock" if on else "")

    def set_a11y(self, ok):
        self.a11y.set_label("Accessibility: Good to go" if ok else "Accessibility: Investigate")

    def _view_toggled(self, btn, name):
        if self._busy or not btn.get_active():
            if not any(b.get_active() for b in self.view_btns.values()) and not self._busy:
                self._busy = True
                btn.set_active(True)
                self._busy = False
            return
        self._busy = True
        for n, b in self.view_btns.items():
            if n != name:
                b.set_active(False)
        self._busy = False
        self.win.run({"read": "read-mode", "print": "print-layout", "web": "web-layout"}[name])

    def set_view(self, name):
        self._busy = True
        for n, b in self.view_btns.items():
            b.set_active(n == name)
        self._busy = False

    def step_zoom(self, delta):
        v = self.zoom.get_value()
        if delta > 0:
            v = (int(v) // 10 + 1) * 10
        else:
            v = max(10, (int(v) - 1) // 10 * 10)
        self.zoom.set_value(v)

    def _zoom_changed(self, scale):
        v = int(round(scale.get_value()))
        self.zoom_pct.set_label("%d%%" % v)
        self.win.engine.zoom(v / 100.0)

    def flash(self, text, seconds=4):
        self.track.set_text(text)
        GLib.timeout_add_seconds(seconds, lambda: (self.track.set_text(
            "Track Changes: On" if self.win.engine.is_on(".uno:TrackChanges") else ""), False)[1])

    def set_zoom(self, factor):
        self.zoom.set_value(max(10, min(500, int(round(factor * 100)))))

    def show_zoom(self, factor):
        v = int(round(factor * 100))
        self.zoom.handler_block(self._zoom_handler)
        self.zoom.set_value(v)
        self.zoom.handler_unblock(self._zoom_handler)
        self.zoom_pct.set_label("%d%%" % v)

    def set_proof(self, errors):
        from . import icons
        icon = "proof-err" if errors else "proof-ok"
        self.proof_img.set_from_pixbuf(icons.pixbuf(icon, 16))
        self.proof.set_tooltip_text(
            "Proofing errors were found. Click to correct." if errors else
            "No proofing errors" if errors is not None else "Checking...")
        ctx = self.proof.get_style_context()
        (ctx.add_class if errors else ctx.remove_class)("folio-proof-errors")

    def schedule_proof(self):
        if not self.win.app.settings.get("auto_spell", True):
            return
        if self._proof_timer:
            GLib.source_remove(self._proof_timer)
        self._proof_timer = GLib.timeout_add(2500, self._check_proof)

    def _check_proof(self):
        self._proof_timer = None
        if getattr(self.win.engine, "native", False):
            ed = self.win.engine.ed
            if ed is None:
                return False
            sp = getattr(self.win.engine.view, "speller", None)
            if sp is not None and sp.enabled():
                from .native import docops
                bad = False
                for para, text, langs in docops.paragraphs(ed)[:3000]:
                    if sp.para_marks(para, text, langs):
                        bad = True
                        break
                self.set_proof(bad)
            if self.enabled().get("a11y"):
                try:
                    issues = ed.accessibility_issues()
                    self.set_a11y(not [c for c, _l, _t in issues if c != "Missing document title"])
                except Exception as e:
                    print("a11y:", e)
            return False
        m = self.win.engine.model
        if m is None:
            return False
        try:
            from . import docapi
            text = m.getText().getString()
            loc = docapi.doc_locale(m)
            bad = False
            for w in docapi.WORD_RE.findall(text[:200000]):
                if len(w) > 1 and not w.isupper() and w not in self.win.ignored_words \
                        and not docapi.spell_ok(w, loc):
                    bad = True
                    break
            self.set_proof(bad)
        except Exception:
            pass
        if self.enabled().get("a11y"):
            try:
                from . import accessibility
                if m.getText().getString().count("\n") < 3000:
                    issues = accessibility.check(m)
                    self.set_a11y(not [c for c, _l, _t in issues
                                       if c != "Missing document title"])
            except Exception as e:
                print("a11y:", e)
        return False

    def update(self, key, value):
        if key in (".uno:StateWordCount", ".uno:ModifiedStatus"):
            self.schedule_proof()
        if key == ".uno:StatePageNumber":
            m = re.search(r"(\d+)\D+(\d+)", value)
            if m:
                cur, total = m.group(1), m.group(2)
                # physical page and page count, as the original shows them
                # (the engine's state can show a restarted page number)
                try:
                    doc = self.win.engine.model
                    ctl = doc.getCurrentController()
                    cur = str(ctl.getViewCursor().getPage())
                    total = str(ctl.PageCount)
                except Exception:
                    pass
                self.page.set_label("Page %s of %s" % (cur, total))
        elif key == ".uno:StateWordCount":
            sel = value.startswith("Selected")
            m = re.search(r"([\d,.]+) words?", value)
            n = m.group(1) if m else "0"
            if sel:
                total = self.win.doc_words
                self.words.set_label("%s of %s words" % (n, total) if total else "%s words" % n)
            else:
                self.win.doc_words = n
                self.words.set_label("%s word%s" % (n, "" if _num(n) == 1 else "s"))
        elif key == ".uno:LanguageStatus":
            code = value.split(";")[-1] if ";" in value else ""
            if code == "zxx" or value.startswith("[None]"):
                self.lang.set_label("Do not check")
            else:
                from .docapi import language_name
                n = language_name(code)
                self.lang.set_label(LANG_NAMES.get(code, n if n != code else value.split(";")[0]))
        elif key == ".uno:TrackChanges":
            self.track.set_text("Track Changes: On" if value == "true" and
                                not self.enabled().get("track") else "")
            self.track_item.set_label("Track Changes: %s" % ("On" if value == "true" else
                                                             "Off"))
        elif key == ".uno:InsertMode":
            self.overtype.set_label("Insert" if value == "true" else "Overtype")
        if key in (".uno:StatePageNumber", ".uno:StateWordCount", ".uno:Position",
                   ".uno:StyleApply", ".uno:ModifiedStatus"):
            self.schedule_metrics()
