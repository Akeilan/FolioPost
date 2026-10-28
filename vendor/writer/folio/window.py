"""The document window."""
import os
import subprocess

from gi.repository import Gdk, GLib, Gtk

from . import APP_NAME, docapi
from .actions import Actions, para_margins, para_spacing, word_style
from .keys import KeyMap, PASSTHROUGH
from .ribbon import Ribbon
from .statusbar import StatusBar
from . import icons


class DocWindow(Gtk.ApplicationWindow):
    def __init__(self, app, path=None, template=None):
        Gtk.ApplicationWindow.__init__(self, application=app)
        self.app = app
        geo = app.settings.get("window", {})
        self.set_default_size(geo.get("w", 1280), geo.get("h", 860))
        if geo.get("max", True):
            self.maximize()
        self.connect("configure-event", self._remember_geometry)
        self.connect("window-state-event", self._remember_state)
        self.set_icon_name("folio-writer")
        self.doc_words = ""
        self.untitled = None
        self.keymap = KeyMap()
        try:
            self.keymap.set_style_keys(app.settings.get("style_keys") or {})
            self.keymap.set_symbol_keys(app.settings.get("symbol_keys") or {})
        except Exception as e:
            print("style keys:", e)
        from . import native
        self.native = native.wanted(app.settings) and native.available()
        if self.native:
            from .native.actions import NativeActions
            self.actions = NativeActions(self)
        else:
            self.actions = Actions(self)
        self._alt_alone = False
        self.focus_mode = False
        self.read_only = False
        self.ignored_words = set()
        self.panes = {}
        self.extend_mode = False
        self._last_positions = []

        if self.native:
            from .native.engine import NativeEngine
            self.engine = NativeEngine(app.engine_profile, app.user_name())
            from .native.autocorrect import AutoCorrect
            self.engine.view.autocorrect = AutoCorrect(self)
            from .native.spell import Speller
            self.engine.view.speller = Speller(self)
        else:
            from .engine import Engine
            self.engine = Engine(app.engine_profile, app.user_name())
        self.engine.connect("state-changed", self.on_state)
        self.engine.connect("zoom-changed", lambda e, z: self.status.show_zoom(z))
        self.engine.connect("model-ready", self.on_model_ready)
        self.engine.connect("engine-dialog", lambda e, t: self.dialogs.engine_dialog(t))
        try:
            self.engine.view.connect("hyperlink-clicked", self.on_link)
            self.engine.view.connect("password-required", self.on_password)
        except TypeError:
            pass

        # ---- title bar
        self.header = Gtk.HeaderBar()
        self.header.set_show_close_button(True)
        self.header.get_style_context().add_class("folio-titlebar")
        self.title_label = Gtk.Label(label=APP_NAME)
        self.title_label.get_style_context().add_class("title")
        self.header.set_custom_title(self.title_label)
        qat = Gtk.Box(spacing=0)
        self.qat = qat
        self.build_qat()
        self.header.pack_start(qat)
        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text("Search (Alt+Q)")
        self.search.get_style_context().add_class("folio-search")
        self.search.set_width_chars(28)
        from .searchbox import SearchBox
        self.search_box = SearchBox(self, self.search)
        self.header.pack_end(self.search)
        self.set_titlebar(self.header)

        # ---- layout
        self.overlay = Gtk.Overlay()
        self.add(self.overlay)
        self.outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.overlay.add(self.outer)
        self.ribbon = Ribbon(self.run, self.focus_document)
        self.ribbon.connect("file-clicked", lambda *_: self.show_backstage())
        self.ribbon.on_display_mode = self.on_ribbon_display
        # full-screen mode: a thin bar whose three dots bring the ribbon back
        self.autohide_bar = Gtk.Box()
        self.autohide_bar.get_style_context().add_class("folio-autohide")
        self.autohide_bar.set_size_request(-1, 22)
        dots = Gtk.Button(label="•••")
        dots.set_relief(Gtk.ReliefStyle.NONE)
        dots.set_tooltip_text("Show the ribbon")
        dots.connect("clicked", lambda *_: self.peek_ribbon(True))
        self.autohide_bar.pack_end(dots, False, False, 6)
        self.autohide_bar.set_no_show_all(True)
        dots.show()
        self.outer.pack_start(self.autohide_bar, False, False, 0)
        self.outer.pack_start(self.ribbon, False, False, 0)
        from .docprotect import MessageBar
        self.msgbar = MessageBar(self)
        self.outer.pack_start(self.msgbar, False, False, 0)

        self.left_pane_slot = Gtk.Box()
        self.left_pane_slot.get_style_context().add_class("folio-pane-slot")
        self.canvas = Gtk.ScrolledWindow()
        self.canvas.get_style_context().add_class("folio-canvas")
        self.canvas.add(self.engine.view)
        # GtkViewport scrolls a newly focused child into view; the document is
        # taller than the window, so every refocus jumped back to page 1.
        vp = self.canvas.get_child()
        if isinstance(vp, Gtk.Container):
            vp.set_focus_vadjustment(Gtk.Adjustment())
            vp.set_focus_hadjustment(Gtk.Adjustment())
        self._follow_rect = None
        self._follow_id = 0
        if not self.native:
            self.engine.view.connect("cursor-changed", self.on_cursor_moved)
        else:
            self.engine.view.connect("cursor-changed", self._native_cursor_moved)
        # LOKDocView passes every key to the engine but reports it unhandled,
        # so GTK also ran its own arrow-key navigation and moved the focus up
        # into the ribbon (and back, scrolling to page 1). Keys the document
        # got stop there.
        self.engine.view.connect_after("key-press-event", lambda *_: True)
        self.engine.view.connect_after("key-release-event", lambda *_: True)
        center = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.center = center
        from .eqbar import EquationBar
        self.eqbar = EquationBar(self)
        from .editfeatures import HeadingFolds
        self.folds = HeadingFolds(self)
        from .textlinks import Linker
        self.text_linker = Linker(self)
        from .textmouse import DragMove
        self.drag_move = DragMove(self)
        from . import dropcap
        dropcap.install(self)
        from .findopts import ReadingHighlight
        self.reading_hl = ReadingHighlight(self)
        from .painter import Painter
        self.painter = Painter(self)
        from .livepreview import LivePreview
        self.live_preview = LivePreview(self)
        GLib.idle_add(self._restore_ribbon_mode)
        from .macros import Recorder
        self.macro_recorder = Recorder(self)
        center.pack_start(self.eqbar, False, False, 0)
        self.canvas_overlay = Gtk.Overlay()
        self.canvas_overlay.add(self.canvas)
        from .ruler import Rulers
        self.rulers = Rulers(self, None, None)
        hrow = Gtk.Box()
        hrow.pack_start(self.rulers.corner, False, False, 0)
        hrow.pack_start(self.rulers.h, True, True, 0)
        center.pack_start(hrow, False, False, 0)
        brow = Gtk.Box()
        brow.pack_start(self.rulers.v, False, False, 0)
        brow.pack_start(self.canvas_overlay, True, True, 0)
        center.pack_start(brow, True, True, 0)
        self.brow = brow
        self.split_view = None
        self.right_pane_slot = Gtk.Box()
        self.right_pane_slot.get_style_context().add_class("folio-pane-slot")
        inner = Gtk.Box()
        inner.pack_start(self.left_pane_slot, False, False, 0)
        inner.pack_start(center, True, True, 0)
        inner.pack_start(self.right_pane_slot, False, False, 0)
        self.outer.pack_start(inner, True, True, 0)

        self.status = StatusBar(self)
        self.outer.pack_start(self.status, False, False, 0)

        # ---- the rest of the UI lives in its own modules
        from .ribbon_defs import build_ribbon
        from .dialogs import Dialogs
        from .backstage import Backstage
        self.dialogs = Dialogs(self)
        build_ribbon(self)
        try:
            from . import customize
            customize.apply(self)
            customize.apply_keys(self)
        except Exception as e:
            print("customize:", e)
        self.backstage = Backstage(self)
        self.overlay.add_overlay(self.backstage)
        from .keytips import KeyTips
        self.keytips = KeyTips(self)
        from .drawing import DrawMode
        self.draw = DrawMode(self)
        from .minibar import MiniToolbar
        self.minibar = MiniToolbar(self)
        from .comments import CommentsMargin
        self.comments = CommentsMargin(self, self.canvas_overlay)
        from .pasteopts import PasteOptions
        self.paste_options = PasteOptions(self, self.canvas_overlay)
        from .acwatch import ACWatch
        self.acwatch = ACWatch(self, self.canvas_overlay)
        from .dnd import DropHandler
        self.drop = DropHandler(self)
        from .review import ChangeBars
        self.change_bars = ChangeBars(self)
        self.track_locked = False
        self.restricted = False
        from .ink import InkMode
        self.ink = InkMode(self)
        from .objecttools import CropMode, LayoutOptions
        self.layout_options = LayoutOptions(self, self.canvas_overlay)
        if self.native:
            from .native.objects import scroll_hook
            self.engine.win = self
            self.engine.view.objs.attach_button(self.canvas_overlay)
            scroll_hook(self.engine.view, self.engine.view.objs)
        self.crop_mode = CropMode(self)
        from .objecttools import EditPoints
        self.edit_points = EditPoints(self)
        if self.native:
            from .native import arrange as _arrange
            _arrange.install(self)
        from .tabledraw import TableDrawMode
        self.table_draw = TableDrawMode(self)

        self.connect("key-press-event", self.on_key)
        self.connect("key-release-event", self.on_key_release)
        self.connect("delete-event", self.on_delete)
        if self.native:
            self.engine.view.press_hook = lambda ev: self.on_doc_click(self.engine.view, ev)
        else:
            self.engine.view.connect("button-press-event", self.on_doc_click)
        self.engine.view.connect("scroll-event", self.on_doc_scroll)
        self.engine.view.connect("motion-notify-event", self.on_doc_motion)
        self.canvas.connect("scroll-event", self.on_doc_scroll)
        self.engine.view.connect("button-release-event", self.on_doc_release)

        self.show_all()
        self.rulers.set_visible(self.app.settings.get("ruler", True))
        if os.environ.get("FOLIO_DEBUG_RIBBON"):
            def dump():
                for name, w in (("ribbon", self.ribbon), ("tabbar", self.ribbon.tabbar),
                                ("revealer", self.ribbon.revealer), ("center", self.center),
                                ("eqbar", self.eqbar), ("canvas", self.canvas),
                                ("outer", self.outer), ("status", self.status)):
                    a = w.get_allocation()
                    print("ALLOC", name, a.x, a.y, a.width, a.height, w.get_preferred_height())
                return False
            GLib.timeout_add(4000, dump)
        self.backstage.hide()
        self.left_pane_slot.hide()
        self.right_pane_slot.hide()
        if path:
            self.open_file(path)
        else:
            self.new_document(template)
        self._autosave_id = None
        self.schedule_autorecover()

    QAT_COMMANDS = [
        ("new", "New", "cmd/sc_adddirect" if False else "cmd/sc_newdoc", "New (Ctrl+N)"),
        ("open", "Open", "cmd/sc_open", "Open (Ctrl+O)"),
        ("save", "Save", "cmd/sc_save", "Save (Ctrl+S)"),
        ("undo", "Undo", "cmd/sc_undo", "Undo (Ctrl+Z)"),
        ("redo", "Redo", "cmd/sc_redo", "Redo (Ctrl+Y)"),
        ("print", "Print Preview and Print", "cmd/sc_printpreview", "Print Preview and Print (Ctrl+P)"),
        ("spelling", "Spelling & Grammar", "cmd/sc_spellingandgrammardialog", "Spelling & Grammar (F7)"),
        ("table", "Draw Table", "cmd/sc_inserttable", "Insert Table"),
        ("format-painter", "Format Painter", "cmd/sc_formatpaintbrush", "Format Painter"),
    ]
    QAT_ACTIONS = {"new": "new", "open": "backstage-open", "save": "save", "undo": "undo",
                   "redo": "redo-repeat", "print": "backstage-print", "spelling": "spelling",
                   "table": "insert-table-dialog", "format-painter": ".uno:FormatPaintbrush"}

    def build_qat(self):
        qat = self.qat
        for c in qat.get_children():
            qat.remove(c)
        chosen = self.app.settings.get("qat", ["save", "undo", "redo"])
        byk = {c[0]: c for c in self.QAT_COMMANDS}
        for key, label, icon, tip in [byk[k] for k in chosen if k in byk]:
            b = Gtk.Button()
            own = {"save": "qat-save", "new": "qat-new", "print": "qat-print",
                   "table": "qat-table"}.get(key)
            b.add(icons.image(own, 16) if own else icons.white_image(icon, 16))
            b.set_tooltip_text(tip)
            b.set_focus_on_click(False)
            b.connect("clicked", lambda _b, a=self.QAT_ACTIONS[key]: self.run(a))
            qat.pack_start(b, False, False, 0)
            if key == "undo":
                arrow = Gtk.Button()
                arrow.add(icons.white_image("chevron", 12))
                arrow.set_focus_on_click(False)
                arrow.get_style_context().add_class("folio-qat-arrow")
                arrow.set_tooltip_text("Undo history")
                arrow.connect("clicked", lambda w: self.undo_history(w))
                qat.pack_start(arrow, False, False, 0)
        cust = Gtk.Button()
        cust.add(icons.white_image("chevron", 12))
        cust.set_tooltip_text("Customize Quick Access Toolbar")
        cust.set_focus_on_click(False)
        cust.get_style_context().add_class("folio-qat-arrow")
        cust.connect("clicked", self.customize_qat)
        qat.pack_start(cust, False, False, 0)
        qat.show_all()

    def customize_qat(self, btn):
        pop = Gtk.Popover.new(btn)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.set_border_width(6)
        head = Gtk.Label(xalign=0)
        head.set_markup("<b>Customize Quick Access Toolbar</b>")
        box.pack_start(head, False, False, 4)
        chosen = list(self.app.settings.get("qat", ["save", "undo", "redo"]))
        for key, label, icon, tip in self.QAT_COMMANDS:
            cb = Gtk.CheckButton(label=label)
            cb.set_active(key in chosen)

            def toggled(w, key=key):
                cur = list(self.app.settings.get("qat", ["save", "undo", "redo"]))
                if w.get_active() and key not in cur:
                    cur.append(key)
                elif not w.get_active() and key in cur:
                    cur.remove(key)
                order = [k for k, *_ in self.QAT_COMMANDS]
                self.app.settings["qat"] = sorted(cur, key=order.index)
                self.app.save_settings()
                for w2 in self.app.windows:
                    w2.build_qat()
            cb.connect("toggled", toggled)
            box.pack_start(cb, False, False, 0)
        box.pack_start(Gtk.Separator(), False, False, 4)
        mb = Gtk.ModelButton(text="Collapse the Ribbon" if not self.ribbon.collapsed
                             else "Show the Ribbon")
        mb.connect("clicked", lambda *_: self.act_toggle_ribbon())
        box.pack_start(mb, False, False, 0)
        box.show_all()
        pop.add(box)
        pop.popup()

    def undo_history(self, btn):
        m = self.engine.model
        titles = []
        try:
            titles = list(m.getUndoManager().getAllUndoActionTitles())[:20] if m else []
        except Exception:
            pass
        pop = Gtk.Popover.new(btn)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.set_border_width(4)
        status = Gtk.Label(label="Cancel", xalign=0.5)
        lb = Gtk.ListBox()
        lb.set_selection_mode(Gtk.SelectionMode.NONE)
        for t in titles:
            row = Gtk.ListBoxRow()
            row.add(Gtk.Label(label=t, xalign=0))
            lb.add(row)
        if not titles:
            lb.add(Gtk.Label(label="Nothing to undo"))

        def hover(w, ev):
            row = lb.get_row_at_y(int(ev.y))
            n = row.get_index() + 1 if row else 0
            for r in lb.get_children():
                r.get_style_context().remove_class("folio-undo-sel") if r.get_index() >= n \
                    else r.get_style_context().add_class("folio-undo-sel")
            status.set_text("Undo %d Action%s" % (n, "" if n == 1 else "s") if n else "Cancel")
            return False
        ev = Gtk.EventBox()
        ev.add(lb)
        ev.connect("motion-notify-event", hover)

        def activated(_lb, row):
            n = row.get_index() + 1
            pop.popdown()
            for _ in range(n):
                self.actions.do_undo()
        lb.connect("row-activated", activated)
        sw = Gtk.ScrolledWindow()
        sw.set_propagate_natural_height(True)
        sw.set_max_content_height(360)
        sw.set_min_content_width(220)
        sw.add(ev)
        box.pack_start(sw, True, True, 0)
        box.pack_start(status, False, False, 4)
        box.show_all()
        pop.add(box)
        pop.popup()

    def _remember_geometry(self, w, ev):
        if not self.is_maximized():
            g = self.app.settings.setdefault("window", {})
            g["w"], g["h"] = self.get_size()
        return False

    def _remember_state(self, w, ev):
        g = self.app.settings.setdefault("window", {})
        g["max"] = bool(ev.new_window_state & Gdk.WindowState.MAXIMIZED)
        return False

    # ---------------------------------------------------------- documents
    def new_document(self, template=None):
        self.untitled = self.app.next_untitled()
        self.engine.new(template or self.app.normal_template(), self._loaded)
        self.update_title()

    def open_file(self, path):
        self.untitled = None
        self.app.add_recent(path)
        self.engine.open(path, self._loaded)
        self.update_title()

    def _loaded(self, ok):
        if ok:
            # nudge the engine so it reports the formatting at the cursor
            GLib.timeout_add(200, lambda: (self.engine.command(".uno:GoToStartOfDoc"), False)[1])
        if not ok and getattr(self.engine, "open_error", None) == "needs-converter":
            self.dialogs.message("To open this kind of file, install LibreOffice (sudo apt install "
                                 "libreoffice-writer). %s uses it only to convert the file."
                                 % APP_NAME, kind="error")
        elif not ok:
            self.dialogs.message("%s couldn't open this file. It may be damaged or in a "
                                 "format %s doesn't support." % (APP_NAME, APP_NAME),
                                 kind="error")
        if ok and getattr(self.engine, "native", False):
            try:
                from . import docprotect, review
                review.enforce(self)
                if docprotect.is_final(self.docmodel):
                    docprotect.apply_final(self)
            except Exception as e:
                print("protection:", e)
        self.status.show_zoom(self.engine.view.get_zoom())
        self.focus_document()
        self.update_title()

    def _update_primary(self):
        """Text selected in Folio becomes the desktop's selection, so a
        middle-click in another program pastes it."""
        self._primary_timer = 0
        try:
            if self.get_focus() is self.engine.view:
                t = self.engine.selection()
                if t:
                    Gtk.Clipboard.get(Gdk.SELECTION_PRIMARY).set_text(t, -1)
        except Exception:
            pass
        return False

    @property
    def clipboard_owned(self):
        """Does the desktop clipboard still hold a copy made in Folio?"""
        return self.app.clipboard().ours()

    @clipboard_owned.setter
    def clipboard_owned(self, value):
        pass

    def _fix_imported_math(self):
        m = self.engine.model
        if m is None:
            return False
        try:
            from . import mathfix
            was = m.isModified()
            n = mathfix.fix_document(m, self.engine.path)
            if n and not was:
                # the objects re-render (and flag the document) over the next
                # few seconds; the repair isn't an edit of the user's
                import time
                t0 = time.time()

                def clear():
                    if getattr(self, "_last_input", 0) > t0:
                        return False
                    for o in mathfix.FIXED:
                        try:
                            if o.Model.isModified():
                                o.Model.setModified(False)
                        except Exception:
                            pass
                    if m.isModified():
                        m.setModified(False)
                    return time.time() - t0 < 6
                GLib.timeout_add(300, clear)
        except Exception as e:
            print("math fix:", e)
        return False

    def on_model_ready(self, *_):
        m = self.engine.model
        if m is None:
            return
        try:
            settings = m.createInstance("com.sun.star.text.DocumentSettings")
            was = m.isModified()
            settings.MathBaselineAlignment = True
            if self.engine.is_new:
                docapi.set_author(m, self.app.user_name())
                docapi.stamp_created(m)
            if self.engine.is_new or not was:
                m.setModified(False)
        except Exception:
            import traceback
            traceback.print_exc()
        for pane in self.panes.values():
            if pane.get_mapped():
                pane.on_shown()
        self.design_changed()
        GLib.timeout_add(1000, lambda: (self.refresh_mailings(), False)[1])
        if not self.engine.is_new:
            from . import editfeatures
            GLib.timeout_add(1200, lambda: (editfeatures.offer_resume(self), False)[1])
            GLib.timeout_add(900, lambda: editfeatures.apply_collapsed_defaults(self))
            GLib.timeout_add(700, self._fix_imported_math)
        from . import grammar
        if not getattr(self.app, "_grammar_on", False):
            self.app._grammar_on = True
            GLib.timeout_add(1500, lambda: (grammar.enable_online(), False)[1])
        # equations: keep the grammar checker from flagging the space they leave
        try:
            grammar.install_equation_filter()
            grammar.refresh_gaps(self.engine.model)
            if grammar.GAPS and self.engine.is_on(".uno:SpellOnline"):
                # recheck what was already checked while the document loaded
                self.engine.command(".uno:SpellOnline")
                self.engine.command(".uno:SpellOnline")
        except Exception as e:
            print("grammar filter:", e)
        try:
            docapi.user_dictionary()       # the user's added words
        except Exception as e:
            print("user dictionary:", e)
        try:
            from . import review
            review.enforce(self)
        except Exception as e:
            print("restrict:", e)
        try:
            from . import docprotect
            if docprotect.is_final(m):
                docprotect.apply_final(self)
        except Exception as e:
            print("final:", e)
        try:
            from . import citations
            if citations.has_citations(m):
                was_mod = m.isModified()
                citations.refresh(m)
                if not was_mod:
                    m.setModified(False)
        except Exception as e:
            print("citations:", e)
        try:
            from . import citations
            ch = getattr(self, "cite_style_choice", None)
            if ch is not None:
                ch._updating = True
                ch.set_active(citations.STYLES.index(citations.current_style(m)))
                ch._updating = False
        except Exception:
            pass
        GLib.timeout_add(800, lambda: (self.apply_view_settings(), False)[1])
        GLib.timeout_add(900, lambda: (self.on_state(self.engine, ".uno:ULSpacing", ""),
                                       self.on_state(self.engine, ".uno:LeftRightParaMargin",
                                                     ""), False)[2])

    def design_changed(self):
        """Styles changed: redraw the galleries so they show the document's
        actual style formatting."""
        m = self.engine.model
        if m is None:
            return
        from .stylemodify import gallery_names
        try:
            self.style_gallery.update_previews(
                docapi.style_previews(m, gallery_names(m)))
        except Exception as e:
            print("gallery:", e)
        try:
            self.styleset_gallery.refresh()
        except Exception:
            pass
        try:
            ps = docapi.para_styles(m)
            self.font_combo.set_theme(ps.getByName("Heading 1").CharFontName,
                                      ps.getByName("Standard").CharFontName)
        except Exception:
            pass

    @property
    def docmodel(self):
        """The document model for properties and settings: UNO's, or the new
        engine's stand-in."""
        eng = self.engine
        if getattr(eng, "native", False):
            if getattr(eng, "ed", None) is None:
                return None
            from .native.uno_model import NativeModel
            return NativeModel(eng)
        return eng.model

    def doc_name(self):
        if self.engine.path and not self.engine.is_new:
            base = os.path.basename(self.engine.path)
            return os.path.splitext(base)[0]
        return self.untitled or "Document1"

    def update_title(self):
        name = self.doc_name()
        extra = ""
        if self.read_only and getattr(self, "msgbar", None) is not None and \
                self.msgbar.kind == "final":
            extra = ""
        elif self.read_only:
            extra = " (Read-Only)"
        elif self.engine.format in ("doc", "rtf") and not self.engine.is_new:
            extra = " [Compatibility Mode]"
        title = "%s%s - %s" % (name, extra, APP_NAME)
        self.title_label.set_text(title)
        self.set_title(title)

    def save(self):
        if self.engine.path is None or self.engine.is_new:
            return self.save_as()
        if self.engine.format not in ("docx", "doc", "rtf", "odt", "dotx"):
            return self.save_as()
        if self.read_only:
            self.dialogs.message("This document is read-only. Use Save As to save a copy.")
            return self.save_as()
        ok = self.engine.save()
        self._after_save(ok)
        return ok

    def save_as(self, fmt=None):
        path = self.dialogs.save_file(self.doc_name(), fmt)
        if not path:
            return False
        return self.save_to(path)

    def save_to(self, path):
        fmt = os.path.splitext(path)[1].lower().lstrip(".")
        keep = fmt not in ("pdf", "epub", "html", "txt")
        from . import compat
        if not compat.check_before_save(self, fmt):
            return False
        if fmt in ("txt",) and not self.dialogs.confirm(
                "Saving as plain text will lose all formatting, pictures and objects. "
                "Do you want to continue?", yes="OK", no="Cancel"):
            return False
        self.engine.save_error = None
        ok = self.engine.save_as(path, keep=keep)
        if not ok and getattr(self.engine, "save_error", None) == "needs-converter":
            self.dialogs.message("To save in this format, install LibreOffice (sudo apt install "
                                 "libreoffice-writer). %s uses it only to convert the file. Word "
                                 "(.docx), PDF and plain text are saved without it." % APP_NAME,
                                 kind="error")
            return False
        if keep:
            self._after_save(ok)
            if ok:
                self.app.add_recent(path)
                self.read_only = False
                self.update_title()
        elif not ok:
            self.dialogs.message("The document couldn't be saved.", kind="error")
        return ok

    def _after_save(self, ok):
        if ok:
            self.engine.mark_saved()
            self.update_title()
            self.app.clear_autorecover(self)
        else:
            self.dialogs.message("The document couldn't be saved. Check that you have "
                                 "permission to write to that folder.", kind="error")

    def confirm_close(self):
        """True if the window may close (saving if asked)."""
        try:
            from . import editfeatures
            editfeatures.remember_position(self)
        except Exception as e:
            print("resume:", e)
        if not self.engine.modified:
            return True
        choice = self.dialogs.ask_save(self.doc_name())
        if choice == "save":
            return self.save()
        return choice == "dont"

    def on_delete(self, *a):
        if self.confirm_close():
            self.app.clear_autorecover(self)
            self.app.window_closed(self)
            return False
        return True

    def close_document(self):
        if self.confirm_close():
            self.app.clear_autorecover(self)
            self.app.window_closed(self)
            self.destroy()

    def apply_view_settings(self):
        st = self.app.settings
        tips = st.get("screentips", True)
        try:
            for c in self.ribbon.all_controls():
                c.set_has_tooltip(tips and bool(getattr(c, "tooltip_text", "")))
        except Exception:
            pass
        want = st.get("auto_spell", True)
        known = ".uno:SpellOnline" in self.engine.state
        if self.engine.model is not None and known and \
                self.engine.is_on(".uno:SpellOnline") != want:
            self.engine.command(".uno:SpellOnline")
        if not want:
            self.status.set_proof(None)

    def schedule_autorecover(self):
        if self._autosave_id:
            GLib.source_remove(self._autosave_id)
            self._autosave_id = None
        s = self.app.settings
        if s.get("autorecover", True):
            mins = max(1, int(s.get("autorecover_minutes", 10)))
            self._autosave_id = GLib.timeout_add_seconds(mins * 60, self._autorecover)

    def _autorecover(self):
        if self.engine.modified:
            self.app.write_autorecover(self)
            from .docprotect import keep_version
            try:
                keep_version(self.app, self)
            except Exception as e:
                print("version:", e)
        return True

    def toggle_read_only(self):
        self.read_only = not self.read_only
        self.engine.view.set_edit(not self.read_only)
        self.update_title()

    def encrypt_dialog(self):
        d = self.dialogs
        pw = d.ask_text("Encrypt Document", "Password:")
        if not pw:
            return
        pw2 = d.ask_text("Confirm Password", "Reenter password:")
        if pw != pw2:
            d.message("The passwords don't match.")
            return
        if self.engine.path and not self.engine.is_new:
            ok = self.engine.save_as(self.engine.path, self.engine.format,
                                     options="Password=" + pw.replace(",", ""))
            if ok:
                self.engine.mark_saved()
                d.message("The document is now encrypted. You'll need the password to open it.")
        else:
            d.message("Save the document first, then encrypt it.")

    # ---------------------------------------------------------- state
    def on_state(self, engine, key, value):
        self.ribbon.update(key, value)
        self.status.update(key, value)
        if key == ".uno:StateWordCount" and value.startswith("Selected") and \
                not getattr(self, "_primary_timer", 0):
            self._primary_timer = GLib.timeout_add(300, self._update_primary)
        if key == ".uno:ModifiedStatus":
            self.update_title()
        elif key == ".uno:StyleApply":
            self.style_gallery_update(word_style(value))
        elif key == ".uno:StateNativeHF":
            inside = value == "true"
            was = getattr(self, "_native_hf", False)
            self._native_hf = inside
            if inside != was:
                self.ribbon.show_contextual("Header & Footer", inside)
                if inside:
                    tab = [t for t in self.ribbon.tabs if t.name == "Header & Footer"]
                    if tab:
                        self.ribbon.select(tab[0])
        elif key == ".uno:StateNativeObject":
            kind = value.split(":")[0] if value else ""
            self.ribbon.show_contextual("Picture Format", kind == "picture")
            self.ribbon.show_contextual("Shape Format", kind in ("shape", "textbox", "group"))
            self.ribbon.show_contextual("Chart Design", kind == "chart")
            smart = False
            if kind == "group":
                try:
                    from .native import smartart
                    smart = smartart.selected(self) is not None
                except Exception:
                    pass
            self.ribbon.show_contextual("SmartArt Design", smart)
            if kind:
                try:
                    _k, w, h = value.split(":")
                    for key2, v in (("width", float(w)), ("height", float(h))):
                        for sb in self.obj_spins.get(key2, []):
                            if not sb.has_focus():
                                sb._updating = True
                                sb.set_value(v * 2540.0 / 72.0)
                                sb._updating = False
                except ValueError:
                    pass
        elif key == ".uno:StateTableCell":
            import re as _re
            value = value if value and _re.search(r"[A-Z]+\d+", value) else ""
            self.ribbon.show_contextual("Table Layout", bool(value))
            self.ribbon.show_contextual("Table Design", bool(value))
            if value:
                self.engine.sync(self.refresh_table_design)
        elif key == ".uno:LeftRightParaMargin":
            l, r, f = para_margins(engine)
            self._set_spin("indent-left", l)
            self._set_spin("indent-right", r)
        elif key == ".uno:ULSpacing":
            b, a = para_spacing(engine)
            self._set_spin("space-before", round(b * 72 / 2540.0))
            self._set_spin("space-after", round(a * 72 / 2540.0))

    def _set_spin(self, kind, value):
        sb = getattr(self, "indent_spins", {}).get(kind)
        if sb is None or sb.has_focus():
            return
        sb._updating = True
        sb.set_value(value)
        sb._updating = False

    def style_gallery_update(self, name):
        gal = getattr(self, "style_gallery", None)
        if gal is not None:
            gal.set_current(name)

    def refresh_styles(self):
        self.design_changed()
        from .panes import StylesPane
        p = self.panes.get(StylesPane)
        if p is not None and p.get_mapped():
            p.refresh()

    # ---------------------------------------------------------- actions
    def run(self, action):
        if not hasattr(self, "keytips"):
            return
        self.keytips.leave()
        rec = getattr(self, "macro_recorder", None)
        if rec is not None and rec.active:
            rec.action(action, getattr(self.ribbon, "current_control", None))
        self.actions.run(action)

    # ------------------------------------------------ macros
    def act_record_macro(self):
        from . import macros
        macros.record_dialog(self)

    def act_stop_recording(self):
        self.macro_recorder.stop()

    def act_pause_recording(self):
        self.macro_recorder.pause()

    def act_view_macros(self):
        from . import macros
        macros.view_dialog(self)

    def act_run_macro(self, name):
        from . import macros
        macros.play(self, name)

    def run_window_action(self, name, arg=None):
        self.engine.sync(lambda: self._run_window_action(name, arg))

    def _run_window_action(self, name, arg=None):
        key = name.replace("-", "_")
        for target in (self, self.dialogs):
            fn = getattr(target, ("act_" if target is self else "") + key, None)
            if fn is not None:
                if arg is None:
                    fn()
                else:
                    fn(arg)
                return

    def model_call_sync(self, path, *args):
        """Run module.function(model, *args) once the engine is idle."""
        import importlib
        mod, fn = path.rsplit(".", 1)
        if getattr(self.engine, "native", False):
            from .native import tables
            if mod == "tablelayout" and tables.call(self, fn, *args):
                return
            if mod == "citations":
                from .native import refs
                getattr(refs.cites(), fn)(self, *args)
                return
            if mod == "mailings":
                from .native import mailmerge
                getattr(mailmerge, fn)(self, *args)
                self.refresh_mailings()
                return
            if mod == "insertextras" and fn == "insert_textbox":
                from .native import objects
                objects.insert_builtin_textbox(self, *args)
                return
            if mod == "insertextras" and fn in ("insert_wordart", "text_effect", "toggle_char", "insert_doc_property"):
                from .native import effects
                getattr(effects, fn)(self, *args)
                return
            self.actions._not_yet()
            return

        def go():
            m = self.engine.model
            if m is not None:
                getattr(importlib.import_module("folio." + mod), fn)(m, *args)
        self.engine.sync(go)

    NATIVE_FIELDS = {"author": "AUTHOR", "filename": "FILENAME", "title": "TITLE", "page": "PAGE",
                     "pages": "NUMPAGES", "date": "DATE", "time": "TIME", "words": "NUMWORDS",
                     "subject": "SUBJECT", "created": "CREATEDATE", "saved": "SAVEDATE"}

    def model_call(self, fn_name, *args):
        if self.native:
            if fn_name == "insert_field" and args and args[0] in self.NATIVE_FIELDS:
                self.engine.ed.insert_field_now(self.NATIVE_FIELDS[args[0]] + " \\* MERGEFORMAT")
                self.engine.view.after_edit()
            elif fn_name == "multilevel_list":
                from . import lists as _lists
                from .native import lists as _nl
                _nl.apply_multilevel(self, _lists.MULTI[0][1])
            elif fn_name == "toggle_field_codes":
                self.engine.ed.toggle_field_codes()
                self.engine.view.after_edit()
            elif fn_name == "drop_cap":
                mode = {"dropped": "drop", "margin": "margin"}.get(args[0] if args else "", "none")
                if self.engine.ed.set_drop_cap(mode, 3, 0, None):
                    self.engine.view.after_edit()
            else:
                self.actions._not_yet()
            return None
        m = self.engine.model
        if m is None:
            self.dialogs.message("The document is still opening. Try again in a moment.")
            return None
        return getattr(docapi, fn_name)(m, *args)

    def act_new(self):
        self.app.new_window()

    def act_save(self):
        self.save()

    def act_save_as(self):
        self.save_as()

    def act_open_dialog(self):
        path = self.dialogs.open_file()
        if path:
            self.app.open_path(path, self)

    def act_backstage_open(self):
        self.show_backstage("open")

    def act_backstage_print(self):
        self.show_backstage("print")

    def act_close(self):
        self.close_document()

    def stop_tracking(self):
        if getattr(self.engine, "native", False):
            if self.engine.get(".uno:TrackChanges") == "true":
                self.engine.command(".uno:TrackChanges")
            return
        m = self.engine.model
        if m is None:
            return
        try:
            if m.RecordChanges:
                self.engine.command(".uno:TrackChanges")
        except Exception as e:
            print("stop tracking:", e)

    def act_toggle_ribbon(self):
        mode = getattr(self.ribbon, "display_mode", "always")
        self.ribbon.set_display_mode("always" if mode != "always" else "tabs")

    ribbon_full = False

    def on_ribbon_display(self, what, value):
        if what == "qat":
            self.ribbon.qat_shown = value
            self.qat.set_visible(value)
            self.app.settings["qat_hidden"] = not value
            self.app.save_settings()
            return
        full = value == "full"
        self.ribbon_full = full
        self.autohide_bar.set_visible(full)
        self.ribbon.set_visible(not full)
        self.header.set_visible(not full)
        if full:
            self.fullscreen()
        elif not self.focus_mode:
            self.unfullscreen()
        self.app.settings["ribbon_mode"] = value
        self.app.save_settings()

    def _restore_ribbon_mode(self):
        if self.app.settings.get("qat_hidden"):
            self.ribbon.qat_shown = False
            self.qat.set_visible(False)
        mode = self.app.settings.get("ribbon_mode")
        if mode in ("tabs", "full"):
            self.ribbon.set_display_mode(mode)
        return False

    def peek_ribbon(self, on):
        """Full-screen mode: show the ribbon over the page until you go back
        to the document."""
        if not self.ribbon_full:
            return
        self.ribbon.set_visible(on)
        self.autohide_bar.set_visible(not on)

    def act_search_box(self):
        self.search.grab_focus()

    def act_focus_mode(self):
        self.focus_mode = not self.focus_mode
        self.ribbon.set_visible(not self.focus_mode)
        self.status.set_visible(not self.focus_mode)
        self.header.set_visible(not self.focus_mode)
        if self.focus_mode:
            self.fullscreen()
        else:
            self.unfullscreen()

    # ---------------------------------------------------------- alternate views
    alt_view = None

    def show_alt_view(self, widget):
        """Replace the page view (rulers and pages) with another view."""
        self.close_alt_view()
        self.alt_view = widget
        for w in self.center.get_children():
            if w is not self.eqbar:
                w.hide()
        self.center.pack_start(widget, True, True, 0)
        widget.show_all()

    def close_alt_view(self):
        w = self.alt_view
        if w is None:
            return
        self.alt_view = None
        self.center.remove(w)
        from .readmode import ReadMode
        if isinstance(w, ReadMode):
            self._after_read_mode()
        for c in self.center.get_children():
            if c is not self.eqbar:
                c.show()
        try:
            self.rulers.set_visible(self.app.settings.get("ruler", True))
        except Exception:
            pass
        self.ribbon.show_contextual("Outlining", False)
        self.ribbon.show_contextual("Immersive Reader", False)
        self.focus_document()

    def act_outline_view(self):
        from .outlineview import OutlineView
        if isinstance(self.alt_view, OutlineView):
            return
        self.leave_special_views()
        if self.native:
            from .native.views import NativeOutlineView as OutlineView
        ov = OutlineView(self)
        self.show_alt_view(ov)
        ov.load()
        self.ribbon.show_contextual("Outlining", True)
        self.select_tab("Outlining")
        self.status.set_view(None)
        ov.tv.grab_focus()

    def act_close_outline(self):
        from .outlineview import OutlineView
        if isinstance(self.alt_view, OutlineView):
            self.close_alt_view()
        self.ribbon.show_contextual("Outlining", False)
        self.status.set_view("print")
        self.select_tab("Home")

    def outline(self):
        from .outlineview import OutlineView
        return self.alt_view if isinstance(self.alt_view, OutlineView) else None

    def act_immersive_reader(self):
        from .readaloud import ImmersiveReader
        if isinstance(self.alt_view, ImmersiveReader):
            return
        self.leave_special_views()
        ir = ImmersiveReader(self)
        self.show_alt_view(ir)
        ir.load()
        self.ribbon.show_contextual("Immersive Reader", True)
        self.select_tab("Immersive Reader")

    def immersive(self):
        from .readaloud import ImmersiveReader
        return self.alt_view if isinstance(self.alt_view, ImmersiveReader) else None

    def act_close_immersive(self):
        if self.read_aloud is not None:
            self.read_aloud.stop()
        self.close_alt_view()
        self.select_tab("View")

    read_aloud = None

    def act_read_aloud(self):
        from .readaloud import ReadAloud
        if self.read_aloud is None:
            self.read_aloud = ReadAloud(self)
        ir = self.immersive()
        self.read_aloud.toggle(ir.source() if ir is not None else None)

    def leave_special_views(self):
        if self.alt_view is not None:
            self.close_alt_view()
        if getattr(self, "draft", False) or (self.native and self.engine.view.continuous):
            self.act_print_layout()

    def act_draft_view(self):
        """Draft: text only, no page edges, margins, headers or pictures in
        place; it wraps at the page's text width."""
        self.leave_special_views()
        if self.native:
            from .native import views
            views.set_layout(self, 1)
            return
        if not self.engine.is_on(".uno:BrowseView"):
            self.engine.command(".uno:BrowseView")
        self.draft = True
        self.rulers.v.hide()
        self.status.set_view(None)

    def act_print_layout(self):
        self.close_alt_view()
        if self.native:
            from .native import views
            views.set_layout(self, 0)
            return
        if getattr(self, "draft", False):
            self.draft = False
            self.rulers.set_visible(self.app.settings.get("ruler", True))
        if self.engine.is_on(".uno:BrowseView"):
            self.engine.command(".uno:PrintLayout")
        self.status.set_view("print")

    def act_web_layout(self):
        self.close_alt_view()
        if self.native:
            from .native import views
            views.set_layout(self, 2)
            return
        if getattr(self, "draft", False):
            self.draft = False
            self.rulers.set_visible(self.app.settings.get("ruler", True))
        if not self.engine.is_on(".uno:BrowseView"):
            self.engine.command(".uno:BrowseView")
        self.status.set_view("web")

    def act_read_mode(self):
        from .readmode import ReadMode
        if isinstance(self.alt_view, ReadMode):
            return
        self.leave_special_views() if hasattr(self, "leave_special_views") else None
        self.show_alt_view(ReadMode(self))
        self.ribbon.hide()
        self.status.hide()
        self.status.set_view("read")

    def leave_read_mode(self):
        from .readmode import ReadMode
        if isinstance(self.alt_view, ReadMode):
            self.close_alt_view()

    def _after_read_mode(self):
        self.ribbon.set_visible(not self.ribbon_full)
        self.status.show()
        self.status.set_view("print")

    def act_spike(self):
        from . import editfeatures
        editfeatures.spike_cut(self)

    def act_spike_paste(self):
        from . import editfeatures
        editfeatures.spike_paste(self)

    def act_expand_all_headings(self):
        self.folds.expand_all()

    def act_collapse_all_headings(self):
        self.folds.collapse_all()

    def act_update_fields(self):
        """F9: update fields, and linked text pasted with Paste link."""
        self.engine.command(".uno:UpdateFields")
        from . import pastelink
        m = self.engine.model
        if m is not None and pastelink.links(m):
            pastelink.update(self)

    def act_equation(self):
        self.eqbar.new_equation()

    def act_help(self):
        self.dialogs.help()

    def act_draw_shape(self, kind):
        if kind == "canvas":
            self.insert_canvas()
            return
        if kind == "scribble":
            self.ink.begin("pen")
            return
        self.draw.begin(kind)

    def act_field_braces(self):
        """Ctrl+F9: empty field braces to type a field code in."""
        if not self.native:
            self.run("field-dialog")
            return
        from .native.fieldcode import FieldCodeEntry
        fc = getattr(self.engine.view, "field_code", None) or FieldCodeEntry(self)
        fc.start()

    def insert_canvas(self):
        """Insert > Shapes > New Drawing Canvas: an empty area at the caret
        to draw shapes on."""
        if not self.native:
            self.actions._not_yet()
            return
        ed = self.engine.ed
        r = ed.caret_rect()
        if r is None:
            return
        pg, _x, y, _h = r
        left = ed.page_margins(pg)[3]
        if ed.insert_shape("rect", pg, left, y + 14, 432.0, 216.0, "Drawing Canvas", False):
            ed.object_fill("<a:noFill/>")
            ed.object_outline("<a:ln><a:noFill/></a:ln>")
            v = self.engine.view
            v.document_changed()
            v.objs.refresh()
            v.after_move()
            v.grab_focus()

    def object_call_module(self, module, fname, *args):
        """Like object_call, for functions in other modules (picture tools)."""
        if self.native:
            from .native import objects
            if not objects.call(self, fname, *args):
                self.actions._not_yet()
            return
        import importlib
        m = self.engine.model
        from . import drawing
        obj = drawing.selected_shape(m) if m is not None else None
        if obj is None:
            return
        mod = importlib.import_module("folio." + module)
        um = m.getUndoManager()
        um.enterUndoContext("Format Picture")
        try:
            getattr(mod, fname)(obj, *args)
        except Exception as e:
            print(module, fname, e)
            self.dialogs.message("That didn't work on this picture: %s" % e)
        finally:
            um.leaveUndoContext()

    def merge_shapes(self, op):
        if self.native:
            from .native import arrange as _arrange
            _arrange.merge(self, op)
            return
        from . import arrange, pictools
        m = self.engine.model
        objs = arrange.selected_objects(m) if m is not None else []
        if len(objs) < 2:
            self.dialogs.message("Select two or more shapes to merge (Ctrl+click, or use "
                                 "the Selection Pane).")
            return
        if not pictools._pil():
            self.dialogs.message("Merging shapes needs the python3-pil package.")
            return
        try:
            pictools.merge_shapes(m, objs, op)
        except Exception as e:
            self.dialogs.message("These shapes can't be merged: %s" % e)
        GLib.timeout_add(200, self.update_object_tabs)

    def wordart_transform(self, kind):
        if self.native:
            from .native import arrange as _arrange
            _arrange.transform(self, kind)
            return
        from . import drawing, pictools
        m = self.engine.model
        obj = drawing.selected_shape(m) if m is not None else None
        if obj is None:
            return
        try:
            pictools.transform(m, obj, kind)
        except Exception as e:
            self.dialogs.message("The text couldn't be transformed: %s" % e)
        GLib.timeout_add(200, self.update_object_tabs)

    # ---------------------------------------------------------- background removal
    bg_state = None

    def bg_removal_start(self):
        if self.native:
            from .native import arrange as _arrange
            _arrange.bg_start(self)
            return
        from . import drawing, pictools
        m = self.engine.model
        obj = drawing.selected_shape(m) if m is not None else None
        if obj is None or drawing.kind_of(obj) != "picture":
            return
        if not pictools._pil():
            self.dialogs.message("Remove Background needs the python3-pil package.")
            return
        self.bg_state = {"obj": obj, "keep": [], "remove": [], "mode": None}
        self.bg_apply()
        self.ribbon.show_contextual("Background Removal", True)
        self.select_tab("Background Removal")

    def bg_apply(self):
        from . import pictools
        st = self.bg_state
        if st is None:
            return
        try:
            pictools.remove_background(st["obj"], st["keep"], st["remove"])
        except Exception as e:
            self.dialogs.message("The background couldn't be removed: %s" % e)

    def bg_mark(self, mode):
        if self.bg_state is None:
            return
        self.bg_state["mode"] = mode
        self.status.flash("Click the parts of the picture to %s." % (
            "keep" if mode == "keep" else "remove"))

    def bg_click(self, x, y):
        """A click while marking areas: returns True if used."""
        st = self.bg_state
        if st is None or not st.get("mode"):
            return False
        r = self.layout_options.rect
        if r is None:
            return False
        rx, ry, rw, rh = r
        if not (rx <= x <= rx + rw and ry <= y <= ry + rh):
            return False
        st[st["mode"]].append(((x - rx) / rw, (y - ry) / rh))
        self.bg_apply()
        return True

    def bg_finish(self, keep):
        if self.native:
            from .native import arrange as _arrange
            _arrange.bg_finish(self, keep)
            return
        from . import pictools
        st = self.bg_state
        self.bg_state = None
        if st is not None and not keep:
            pictools.reset_picture(st["obj"])
        self.ribbon.show_contextual("Background Removal", False)
        self.select_tab("Picture Format")

    def act_mark_citation(self):
        from . import authorities
        authorities.mark_dialog(self)

    def lock_tracking(self):
        from . import review
        review.lock_tracking(self)

    def act_selection_pane(self):
        if self.native:
            from .native.selection import NativeSelectionPane as SelectionPane
        else:
            from .arrange import SelectionPane
        pane = self.panes.get(SelectionPane)
        if pane is not None and pane.get_parent() is not None:
            self.hide_pane(pane)
        else:
            self.show_pane(SelectionPane)

    align_mode = "auto"

    def set_align_mode(self, mode):
        self.align_mode = mode
        self.status.flash({"page": "Objects align to the page.",
                           "margin": "Objects align to the margins.",
                           "objects": "Selected objects align to each other."}[mode])

    def arrange_call(self, fn, arg):
        """Align / distribute: several selected objects line up with each
        other; one object aligns to the margins (or page)."""
        if self.native:
            from .native import arrange as _arrange
            if not _arrange.selected(self):
                self.status.flash("Select a picture or shape first.")
            elif fn == "distribute":
                _arrange.distribute(self, arg)
            else:
                _arrange.align(self, arg)
            return
        from . import arrange, drawing
        m = self.engine.model
        if m is None:
            return
        objs = arrange.selected_objects(m)
        if not objs:
            return
        if fn == "distribute":
            if not arrange.distribute(m, objs, arg):
                self.status.flash("Select three or more objects to distribute them.")
        elif len(objs) > 1 and self.align_mode in ("auto", "objects"):
            arrange.align_objects(m, objs, arg)
        else:
            um = m.getUndoManager()
            um.enterUndoContext("Align")
            try:
                for o in objs:
                    drawing.align(o, arg, page=self.align_mode == "page")
            finally:
                um.leaveUndoContext()
        try:
            arrange.select(m, objs)
        except Exception:
            pass
        GLib.timeout_add(150, self.update_object_tabs)

    def act_select_similar(self):
        """Select all text with the same paragraph style as the cursor."""
        from . import stylemodify
        m = self.engine.model
        if m is None:
            return
        try:
            name = docapi.read_cursor(m).ParaStyleName
            st = docapi.para_styles(m).getByName(name)
            stylemodify.select_all(self, word_style(st.DisplayName))
        except Exception as e:
            print("select similar:", e)

    def act_check_accessibility(self):
        from .accessibility import AccessibilityPane
        pane = self.panes.get(AccessibilityPane)
        if pane is not None and pane.get_parent() is not None:
            pane.refresh()
        else:
            self.show_pane(AccessibilityPane)

    def act_footnote_dialog(self):
        from . import notes
        notes.dialog(self)

    def act_show_notes(self):
        """Jump between a note reference and its text."""
        from . import notes
        m = self.engine.model
        if m is None:
            return
        vc = docapi.read_cursor(m)
        try:
            fn = vc.getText()
            if fn.supportsService("com.sun.star.text.Footnote"):
                docapi.view_cursor(m).gotoRange(fn.getAnchor().getEnd(), False)
                return
        except Exception:
            pass
        all_notes = notes.notes(m, False) + notes.notes(m, True)
        if not all_notes:
            self.dialogs.message("There are no footnotes or endnotes in this document.")
            return
        docapi.view_cursor(m).gotoRange(all_notes[0].getText().getEnd(), False)

    def act_style_inspector(self):
        from .styletools import StyleInspector
        pane = self.panes.get(StyleInspector)
        if pane is not None and pane.get_parent() is not None:
            self.hide_pane(pane)
        else:
            self.show_pane(StyleInspector, side="right")

    def act_manage_styles(self):
        from .styletools import manage_styles
        manage_styles(self)

    def act_edit_points(self):
        """Edit Points: turn the shape into a freeform and edit its points."""
        self.edit_points.begin()

    def refresh_table_design(self):
        m = self.engine.model
        if m is None:
            return
        from . import tablestyles
        try:
            st = tablestyles.options(m)
        except Exception:
            st = None
        if st is None:
            return
        try:
            from . import tablelayout
            size = tablelayout.cell_size(m)
            if size:
                for key, v in (("height", size[0]), ("width", size[1])):
                    sb = getattr(self, "cell_spins", {}).get(key)
                    if sb is not None and not sb.has_focus():
                        sb._updating = True
                        sb.set_value(v)
                        sb._updating = False
            b = getattr(self, "repeat_header_btn", None)
            if b is not None:
                b.apply_state("true" if tablelayout.is_repeat_header(m) else "false")
        except Exception as e:
            print("cell size:", e)
        kind, accent, opts = st
        for k, cb in getattr(self, "table_opt_checks", {}).items():
            cb.set_checked(opts.get(k, False))
        g = getattr(self, "table_style_gallery", None)
        if g is not None:
            g.update(kind, accent, opts)

    def toggle_navigation_pane(self):
        from .panes import NavigationPane
        pane = self.panes.get(NavigationPane)
        if pane is not None and pane.get_parent() is not None:
            self.hide_pane(pane)
        else:
            self.show_pane(NavigationPane, "left")

    def _sync_pane_checks(self):
        from .panes import NavigationPane
        chk = getattr(self, "nav_check", None)
        if chk is not None:
            p = self.panes.get(NavigationPane)
            chk.set_checked(p is not None and p.get_parent() is not None)

    def set_markup_display(self, mode):
        """Display for Review: All Markup / Simple Markup / No Markup /
        Original."""
        if getattr(self.engine, "native", False):
            from .native import review as NR
            NR.set_markup(self.engine, mode)
            self.comments.set_visible(mode in ("All Markup", "Simple Markup"))
            self.change_bars.set_mode(mode)
            return
        if mode == "Original":
            self.enter_original()
            self.comments.set_visible(False)
            self.change_bars.set_mode("No Markup")
            return
        self.leave_original()
        show = mode == "All Markup"
        cur = self.engine.get(".uno:ShowTrackedChanges") == "true"
        if show != cur:
            self.engine.command(".uno:ShowTrackedChanges")
        self.comments.set_visible(mode != "No Markup")
        self.change_bars.set_mode(mode)

    in_original = False

    def enter_original(self):
        """The document as it was before the tracked changes: every change
        is taken back for display (one undo step, undone on leaving), and
        the document can't be edited meanwhile."""
        if self.in_original or self.engine.model is None:
            return
        m = self.engine.model
        self._orig_modified = m.isModified()
        self.engine.command(".uno:RejectAllTrackedChanges")
        self.in_original = True

        def lock():
            self.engine.view.set_edit(False)
            if not self._orig_modified:
                m.setModified(False)
        self.engine.sync(lock)
        if not getattr(self, "_orig_hooked", False):
            self._orig_hooked = True
            self.engine.save_hooks = tuple(self.engine.save_hooks) + (
                (self._orig_before_save, lambda: None),)

    def _orig_before_save(self):
        if self.in_original:
            self.leave_original(wait=True)
            if getattr(self, "markup_choice", None) is not None:
                try:
                    c = self.markup_choice
                    c._updating = True
                    c.set_active(0)
                    c._updating = False
                except Exception:
                    pass

    def leave_original(self, wait=False):
        if not self.in_original:
            return
        self.in_original = False
        m = self.engine.model
        self.engine.view.set_edit(not self.read_only)
        try:
            um = m.getUndoManager()
            titles = um.getAllUndoActionTitles()
            if titles and titles[0].startswith(("Reject", "Reject change")):
                um.undo()
                try:
                    um.clearRedo()
                except Exception:
                    pass
        except Exception as e:
            print("original:", e)

        def restore():
            if m is not None and not getattr(self, "_orig_modified", True):
                m.setModified(False)
        if wait:
            self.engine.sync(restore)
        else:
            self.engine.sync(restore)

    def reviewer_filter(self, author, show):
        for target in (self.comments, self.change_bars):
            if show:
                target.hidden_authors.discard(author)
            else:
                target.hidden_authors.add(author)
        self.comments.rebuild()
        self.change_bars.refresh()

    def all_reviewers(self, show):
        names = set(self.comments.authors()) | set(self.change_bars.authors())
        for target in (self.comments, self.change_bars):
            target.hidden_authors = set() if show else set(names)
        self.comments.rebuild()
        self.change_bars.refresh()

    def toggle_formatting_markup(self):
        self.change_bars.show_formatting = not self.change_bars.show_formatting
        if getattr(self.engine, "native", False) and self.engine.ed is not None:
            self.engine.ed.set_show_formatting_changes(self.change_bars.show_formatting)
            self.engine.view.document_changed()
        self.change_bars.refresh()

    def accept_reject_shown(self, accept):
        """Accept / Reject All Changes Shown: only the reviewers shown."""
        bars = self.change_bars
        if getattr(self.engine, "native", False) and bars.hidden_authors:
            shown = [a for a in bars.authors() if a not in bars.hidden_authors]
            self.engine.ed.accept_reject_all(accept, shown)
            self.engine.view.document_changed()
            bars.schedule()
            return
        if not bars.hidden_authors and bars.show_formatting:
            self.actions.cmd(".uno:AcceptAllTrackedChanges" if accept
                             else ".uno:RejectAllTrackedChanges")
            return
        cmd = ".uno:AcceptTrackedChange" if accept else ".uno:RejectTrackedChange"
        ids = [r.get("index") for r in bars.shown() if r.get("index") is not None]
        for i in sorted(ids, key=lambda x: int(x), reverse=True):
            self.engine.command(cmd, {cmd[5:]: ("unsigned short", int(i))})
        bars.schedule()

    def set_balloons(self, on):
        """Deleted text in the margin (balloons) or inline."""
        cur = self.engine.get(".uno:ShowChangesInMargin") == "true"
        if on != cur:
            self.engine.command(".uno:ShowChangesInMargin")

    def act_manage_changes(self):
        from .panes import ReviewingPane
        pane = self.panes.get(ReviewingPane)
        if pane is not None and pane.get_parent() is not None:
            self.hide_pane(pane)
        else:
            self.show_pane(ReviewingPane, "left")

    def _native_cursor_moved(self, view, *_a):
        """The caret in document twips, as the old engine reported it."""
        ed = self.engine.ed
        r = ed.caret_rect() if ed is not None else None
        if r:
            pg, x, y, h = r
            top = self.engine.page_top_tw(pg)
            self._follow_rect = (int(x * 20), int(top + y * 20), 20, int(h * 20))

    def on_cursor_moved(self, view, x, y, w, h):
        """Keep the text cursor on screen (LOKDocView leaves that to the host)."""
        self._follow_rect = (x, y, w, h)
        # the cursor may have gone into or out of a header/footer
        if not getattr(self, "_hf_timer", 0):
            def hf():
                self._hf_timer = 0
                try:
                    self.refresh_hf()
                except Exception as e:
                    print("hf refresh:", e)
                return False
            self._hf_timer = GLib.timeout_add(150, hf)
        eqb = getattr(self, "eqbar", None)
        if eqb is not None and eqb.ed.active:
            eqb.ed.cursor_moved()
        if not self._follow_id:
            self._follow_id = GLib.timeout_add(30, self._follow_cursor)

    def _follow_cursor(self):
        self._follow_id = 0
        r = self._follow_rect
        if r is None:
            return False
        x, y, w, h = r
        if w <= 0 and h <= 0 and x <= 0 and y <= 0:
            return False
        px, py = self.engine.twips_to_px(x, y)
        _pw, ph = self.engine.twips_to_px(w, h)
        margin = 24
        va = self.canvas.get_vadjustment()
        top, page = va.get_value(), va.get_page_size()
        if py < top + margin:
            v = py - margin
            va.set_value(va.get_lower() if v < 150 else v)
        elif py + ph > top + page - margin:
            va.set_value(min(va.get_upper() - page, py + ph + margin - page))
        ha = self.canvas.get_hadjustment()
        left, pw = ha.get_value(), ha.get_page_size()
        if ha.get_upper() > pw + 1:
            if px < left + margin:
                ha.set_value(max(ha.get_lower(), px - margin))
            elif px > left + pw - margin:
                ha.set_value(min(ha.get_upper() - pw, px + margin - pw))
        return False

    def on_doc_scroll(self, widget, event):
        """Ctrl+wheel zooms in steps of 10%, as in the original."""
        if not event.state & Gdk.ModifierType.CONTROL_MASK:
            view = self.engine.view
            if self.native and getattr(view, "side", False):
                # Side to Side: the wheel turns the pages
                ok, dx, dy = event.get_scroll_deltas()
                if event.direction == Gdk.ScrollDirection.UP:
                    dy = -1
                elif event.direction == Gdk.ScrollDirection.DOWN:
                    dy = 1
                ha = self.canvas.get_hadjustment()
                step = ha.get_page_size() / 2.0
                ha.set_value(max(0, min(ha.get_upper() - ha.get_page_size(),
                                        ha.get_value() + (dy or dx) * step)))
                return True
            return False
        ok, dx, dy = event.get_scroll_deltas()
        if event.direction == Gdk.ScrollDirection.UP or (ok and dy < 0):
            self.status.step_zoom(10)
        elif event.direction == Gdk.ScrollDirection.DOWN or (ok and dy > 0):
            self.status.step_zoom(-10)
        return True

    merge_preview = None
    merge_highlight = False

    def refresh_mailings(self):
        """Enable the merge controls once there are recipients; show the record."""
        from . import mailings
        m = self.engine.model
        if self.native:
            from .native import mailmerge as mailings
            m = self if self.engine.ed is not None else None
        if m is None or not hasattr(self, "mail_controls"):
            return
        try:
            cols, rows, inc = mailings.recipients(m)
        except Exception:
            cols, rows = [], []
        have = bool(rows)
        for w in self.mail_controls.get("need_recipients", []):
            w.set_sensitive(have)
        rec = self.mail_controls.get("record")
        if rec is not None:
            rec.set_text("" if self.merge_preview is None else str(self.merge_preview + 1))
        pv = self.mail_controls.get("preview")
        if pv is not None:
            pv.apply_state("true" if self.merge_preview is not None else "false")

    def act_merge_preview(self):
        from . import mailings
        m = self.engine.model
        if self.native:
            from .native import mailmerge as mailings
            m = self
        if m is None:
            return
        cols, rows, inc = mailings.recipients(m)
        if not rows:
            return
        self.merge_preview = None if self.merge_preview is not None else 0
        mailings.show_record(m, self.merge_preview)
        self.refresh_mailings()

    def merge_go(self, where):
        from . import mailings
        m = self.engine.model
        if self.native:
            from .native import mailmerge as mailings
            m = self
        if m is None:
            return
        cols, rows, inc = mailings.recipients(m)
        if not rows:
            return
        n = len(rows)
        cur = self.merge_preview or 0
        if isinstance(where, int):
            cur = where
        else:
            cur = {"first": 0, "prev": cur - 1, "next": cur + 1, "last": n - 1}[where]
        self.merge_preview = max(0, min(n - 1, cur))
        mailings.show_record(m, self.merge_preview)
        self.refresh_mailings()

    def act_find_recipient(self):
        from . import mailings
        m = self.engine.model
        if self.native:
            from .native import mailmerge as mailings
            m = self
        t = self.dialogs.ask_text("Find Entry", "Find:")
        if not t:
            return
        k = mailings.find_recipient(m, t, (self.merge_preview or 0) + 1)
        if k is None:
            self.dialogs.message("No matching entries were found.")
        else:
            self.merge_go(k)

    def act_highlight_merge_fields(self):
        from . import mailings
        self.merge_highlight = not self.merge_highlight
        if self.native:
            from .native import mailmerge
            mailmerge.highlight(self, self.merge_highlight)
        else:
            mailings.highlight_fields(self.merge_highlight)
        self.engine.view.queue_draw()
        b = self.mail_controls.get("highlight") if hasattr(self, "mail_controls") else None
        if b is not None:
            b.apply_state("true" if self.merge_highlight else "false")

    multipage = None

    def act_multiple_pages(self, side=False):
        if self.native:
            # the new engine edits the pages laid out side by side
            view = self.engine.view
            if (view.side if side else view.columns > 1):
                self.close_multipage()
                return
            alloc_w = max(400, self.canvas.get_allocated_width())
            alloc_h = max(300, self.canvas.get_allocated_height())
            pw, ph = view.ed.page_size(0) if view.ed else (612, 792)
            ppp96 = 96.0 / 72.0
            if side:
                view.set_page_layout(1, side=True)
                # two pages across the window, as the original shows them
                z = min((alloc_h - 40) / (ph * ppp96), (alloc_w - 60) / (2 * pw * ppp96))
            else:
                n = view.ed.page_count() if view.ed else 1
                cols = max(2, min(n, int(alloc_w // 260)))
                view.set_page_layout(cols)
                z = (alloc_w - (cols + 1) * 20) / (cols * pw * ppp96)
            view.set_zoom(max(0.1, z))
            self.status.flash("Pages side by side. Esc returns.")
            return
        if self.multipage is not None:
            self.close_multipage()
            if bool(self.multipage_side) == bool(side):
                return
        from .multipage import MultiPageView
        mp = MultiPageView(self, side_to_side=side)
        self.multipage = mp
        self.multipage_side = side
        self.canvas_overlay.remove(self.canvas)
        self.canvas_overlay.add(mp)
        mp.show_all()
        self.status.flash("Click a page to edit it. Esc returns.")

    def act_side_to_side(self):
        self.act_multiple_pages(True)

    def close_multipage(self, page=None):
        if self.native:
            view = self.engine.view
            if view.columns > 1 or view.side:
                view.set_page_layout(1)
                view.set_zoom(1.0)
            return
        mp = self.multipage
        if mp is None:
            return
        self.multipage = None
        self.canvas_overlay.remove(mp)
        self.canvas_overlay.add(self.canvas)
        mp.destroy()
        self.canvas.show_all()
        if page and self.engine.model is not None:
            def jump():
                vc = docapi.view_cursor(self.engine.model)
                vc.jumpToPage(page)
                vc.jumpToStartOfPage()
            self.engine.sync(jump)
        self.focus_document()

    def _second_view(self):
        if self.native:
            from .native import views
            return views.second_view(self)
        from gi.repository import LOKDocView
        return LOKDocView.View.new_from_widget(self.engine.view, "{}")

    def act_new_window(self):
        """View > New Window: a second window onto this same document."""
        try:
            v2 = self._second_view()
        except Exception as e:
            self.dialogs.message("A new window couldn't be opened. (%s)" % e)
            return
        w = Gtk.Window(title="%s:2 - %s" % (self.doc_name(), APP_NAME))
        w.set_default_size(*self.get_size())
        w.set_icon_name("folio-writer")
        sw = Gtk.ScrolledWindow()
        sw.get_style_context().add_class("folio-canvas")
        sw.add(v2)
        w.add(sw)
        v2.set_zoom(self.engine.view.get_zoom() or 1.0)

        def scroll(widget, ev):
            if ev.state & Gdk.ModifierType.CONTROL_MASK:
                z = v2.get_zoom() or 1.0
                up = ev.direction == Gdk.ScrollDirection.UP
                v2.set_zoom(max(0.1, min(5.0, z + (0.1 if up else -0.1))))
                return True
            return False
        v2.connect("scroll-event", scroll)
        self.connect("destroy", lambda *_: w.destroy())
        self.extra_windows = getattr(self, "extra_windows", []) + [w]
        w.connect("destroy", lambda *_: self.extra_windows.remove(w) if w in self.extra_windows else None)
        w.show_all()
        w.present()

    def act_split(self):
        """View > Split: a second pane on the same document above this one."""
        if self.split_view is not None:
            self.remove_split()
            return
        try:
            v2 = self._second_view()
        except Exception as e:
            self.dialogs.message("The window couldn't be split. (%s)" % e)
            return
        v2.set_zoom(self.engine.view.get_zoom() or 1.0)
        try:
            v2.set_edit(not getattr(self, "read_only", False))
        except Exception:
            pass
        sw = Gtk.ScrolledWindow()
        sw.get_style_context().add_class("folio-canvas")
        sw.add(v2)
        paned = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        paned.get_style_context().add_class("folio-split-bar")
        self.center.remove(self.brow)
        paned.pack1(sw, True, False)
        paned.pack2(self.brow, True, False)
        self.center.pack_start(paned, True, True, 0)
        paned.show_all()
        GLib.idle_add(lambda: (paned.set_position(max(120, paned.get_allocated_height() // 2)),
                               False)[1])
        self.split_view = (paned, sw, v2)
        btn = getattr(self, "split_button", None)
        if btn is not None:
            btn.apply_state("true")

    def remove_split(self):
        if self.split_view is None:
            return
        paned, sw, v2 = self.split_view
        self.split_view = None
        paned.remove(self.brow)
        self.center.remove(paned)
        self.center.pack_start(self.brow, True, True, 0)
        sw.destroy()
        btn = getattr(self, "split_button", None)
        if btn is not None:
            btn.apply_state("false")
        self.focus_document()

    def act_context_menu(self):
        self.dialogs.context_menu(None)

    def _regions(self):
        """F6 order: document, open panes, ribbon, status bar."""
        out = ["document"]
        for pane in self.panes.values():
            if pane.get_parent() is not None and pane.get_mapped():
                out.append(pane)
        out += ["ribbon", "status"]
        return out

    def _cycle_region(self, step):
        regions = self._regions()
        focus = self.get_focus()
        cur = 0
        if self.keytips.active:
            cur = regions.index("ribbon")
        elif focus is not None and focus is not self.engine.view:
            for i, r in enumerate(regions):
                if isinstance(r, Gtk.Widget) and (focus is r or focus.is_ancestor(r)):
                    cur = i
                elif r == "status" and focus.is_ancestor(self.status):
                    cur = i
        nxt = regions[(cur + step) % len(regions)]
        self.keytips.leave()
        if nxt == "document":
            self.focus_document()
        elif nxt == "ribbon":
            self.keytips.start()
        elif nxt == "status":
            self.status.page.set_can_focus(True)
            self.status.page.grab_focus()
            if not self.status.page.has_focus():
                self.status.child_focus(Gtk.DirectionType.TAB_FORWARD)
        else:
            nxt.child_focus(Gtk.DirectionType.TAB_FORWARD)

    def act_next_region(self):
        self._cycle_region(1)

    def act_prev_region(self):
        self._cycle_region(-1)

    def _cycle_window(self, step):
        wins = self.app.windows
        if len(wins) > 1:
            i = wins.index(self) if self in wins else 0
            wins[(i + step) % len(wins)].present()

    def act_next_window(self):
        self._cycle_window(1)

    def act_prev_window(self):
        self._cycle_window(-1)

    def act_arrange_all(self):
        """Tile all open documents one above the other."""
        wins = [w for w in self.app.windows if w.get_visible()]
        if not wins:
            return
        disp = self.get_display()
        mon = disp.get_monitor_at_window(self.get_window()) if self.get_window() else \
            disp.get_primary_monitor()
        area = mon.get_workarea()
        h = area.height // len(wins)
        for i, w in enumerate(wins):
            w.unmaximize()
            w.move(area.x, area.y + i * h)
            w.resize(area.width, max(300, h))

    # ------------------------------------------------ View Side by Side
    side_partner = None
    _sync_ids = None

    def act_side_by_side(self):
        """Two documents next to each other, scrolling together."""
        if self.side_partner is not None:
            self._end_side_by_side()
            return
        others = [w for w in self.app.windows if w is not self and w.get_visible()]
        if not others:
            self.dialogs.message("Open another document to compare it side by side.")
            return
        other = others[0]
        if len(others) > 1:
            from .widgets import FDialog, listbox
            d = FDialog(self, "Compare Side by Side")
            d.add(Gtk.Label(label="Compare Side by Side with:", xalign=0))
            sw, tv, _store = listbox([w.doc_name() for w in others], height=150, width=300,
                                     on_activate=lambda *_: d.response(Gtk.ResponseType.OK))
            tv.get_selection().select_path(Gtk.TreePath(0))
            d.add(sw)
            r = d.ask()
            model, it = tv.get_selection().get_selected()
            idx = model.get_path(it)[0] if it else 0
            d.done()
            if r != Gtk.ResponseType.OK:
                return
            other = others[idx]
        self.side_partner, other.side_partner = other, self
        self._tile_pair(other)
        self._set_sync(True)
        self.ribbon.update("folio:side-by-side", "true")
        other.ribbon.update("folio:side-by-side", "true")

    def _tile_pair(self, other):
        disp = self.get_display()
        mon = disp.get_monitor_at_window(self.get_window()) if self.get_window() else \
            disp.get_primary_monitor()
        area = mon.get_workarea()
        w = area.width // 2
        for i, win in enumerate((self, other)):
            win.unmaximize()
            win.move(area.x + i * w, area.y)
            win.resize(max(400, w), area.height)

    def act_reset_window_position(self):
        if self.side_partner is not None:
            self._tile_pair(self.side_partner)

    def act_sync_scrolling(self):
        if self.side_partner is None:
            return
        self._set_sync(self._sync_ids is None)

    def _set_sync(self, on):
        other = self.side_partner
        for w in (self, other):
            if w is None:
                continue
            if w._sync_ids:
                for adj, hid in w._sync_ids:
                    adj.disconnect(hid)
            w._sync_ids = None
        if on and other is not None:
            def follow(adj, src, dst):
                if getattr(dst, "_syncing", False):
                    return
                a = dst.canvas.get_vadjustment()
                span = max(1.0, adj.get_upper() - adj.get_page_size())
                frac = adj.get_value() / span
                src._syncing = True
                try:
                    a.set_value(frac * max(0.0, a.get_upper() - a.get_page_size()))
                finally:
                    src._syncing = False
            for src, dst in ((self, other), (other, self)):
                adj = src.canvas.get_vadjustment()
                hid = adj.connect("value-changed", follow, src, dst)
                src._sync_ids = [(adj, hid)]
        for w in (self, other):
            if w is not None:
                w.ribbon.update("folio:sync-scroll", "true" if on else "false")

    def _end_side_by_side(self):
        other = self.side_partner
        self._set_sync(False)
        for w in (self, other):
            if w is not None:
                w.side_partner = None
                w.ribbon.update("folio:side-by-side", "false")
                w.ribbon.update("folio:sync-scroll", "false")

    def switch_windows_menu(self):
        from .ribbon import menu_popover
        items = []
        for i, w in enumerate(self.app.windows, 1):
            mark = "\u2713 " if w is self else "    "
            items.append(("%s%d %s" % (mark, i, w.doc_name()), (lambda w=w: w.present())))
        return menu_popover(None, items)

    def act_toggle_ruler(self):
        on = not self.app.settings.get("ruler", True)
        self.app.settings["ruler"] = on
        self.app.save_settings()
        for w in self.app.windows:
            w.rulers.set_visible(on)
            chk = getattr(w, "ruler_check", None)
            if chk is not None:
                chk.set_checked(on)

    def ruler_add_tab(self, pos, align="LEFT"):
        self.ruler_move_tab(None, pos, align)

    def ruler_move_tab(self, old, new, align="LEFT"):
        """Add (old None), move, or remove (new None) a tab stop of the
        selected paragraphs."""
        m = self.engine.model
        if m is None:
            return
        from . import bridge
        vc = docapi.view_cursor(m)
        stops = [t for t in (vc.ParaTabStops or ())
                 if getattr(t.Alignment, "value", "") != "DEFAULT" and
                 (old is None or abs(t.Position - old) > 5) and
                 (new is None or abs(t.Position - new) > 50)]
        if new is not None:
            ts = bridge.struct("com.sun.star.style.TabStop")
            ts.Position = int(new)
            ts.Alignment = bridge.enum("com.sun.star.style.TabAlign", align)
            ts.FillChar = " "
            ts.DecimalChar = "."
            stops.append(ts)
        um = m.getUndoManager()
        um.enterUndoContext("Tabs")
        try:
            vc.ParaTabStops = tuple(sorted(stops, key=lambda t: t.Position))
        finally:
            um.leaveUndoContext()
        self.rulers.refresh()

    def act_paragraph_borders(self):
        self.dialogs.borders_dialog()

    def act_indent_left(self, v):
        self.actions.set_indents(left=int(v))

    def act_indent_right(self, v):
        self.actions.set_indents(right=int(v))

    def act_space_before(self, v):
        self.actions.set_spacing(before=int(round(v * 2540 / 72.0)))

    def act_space_after(self, v):
        self.actions.set_spacing(after=int(round(v * 2540 / 72.0)))

    def act_doc_colors(self, name):
        self.dialogs.doc_colors(name)

    def act_doc_fonts(self, name):
        self.dialogs.doc_fonts(name)

    def show_backstage(self, page="home"):
        self.keytips.leave()
        self.backstage.open(page)

    def focus_document(self):
        self.engine.view.grab_focus()

    def on_search_activate(self, entry):
        self.dialogs.command_search(entry.get_text())
        entry.set_text("")

    def _in_left_margin(self, x, y):
        """Is this view point in the selection bar left of the text?"""
        try:
            tx, ty = self.engine.px_to_twips(x, y)
            ps = self.ruler_state.get("page") if hasattr(self, "ruler_state") else None
            if ps is None:
                return None
            left = ps["left"] * 1440 // 2540
            for rx, ry, rw, rh in self.engine.page_rects():
                if ry <= ty < ry + rh:
                    if rx + 150 <= tx < rx + left - 120:
                        return rx + left, ty
                    return None
        except Exception:
            return None
        return None

    def _margin_select(self, hit, count):
        x, y = hit
        self.engine.click_at(x + 20, y)
        m = self.engine.model

        def select():
            if m is None:
                return
            if count >= 3:
                self.engine.command(".uno:SelectAll")
                return
            vc = docapi.view_cursor(m)
            if count == 2:
                cur = vc.getText().createTextCursorByRange(vc.getStart())
                cur.gotoStartOfParagraph(False)
                cur.gotoEndOfParagraph(True)
                vc.gotoRange(cur.getStart(), False)
                vc.gotoRange(cur.getEnd(), True)
            else:
                vc.gotoStartOfLine(False)
                vc.gotoEndOfLine(True)
        self.engine.sync(select)

    def on_doc_motion(self, view, event):
        want = "margin" if self._in_left_margin(event.x, event.y) else "text"
        if want != getattr(self, "_cursor_kind", "text"):
            self._cursor_kind = want
            win = view.get_window()
            if win is not None:
                win.set_cursor(Gdk.Cursor.new_for_display(view.get_display(),
                                                          Gdk.CursorType.RIGHT_PTR)
                               if want == "margin" else None)
        return False

    def on_doc_click(self, view, event):
        if self.native:
            if getattr(self, "draw", None) is not None and self.draw.active:
                return self.draw._press(view, event)
            if self.eqbar.ed.active and self.eqbar.ed.press(event):
                return True
            ed = self.engine.ed
            if event.button == 3 and event.type == Gdk.EventType.BUTTON_PRESS and ed is not None:
                # the shortcut menu (and the Mini Toolbar), as in the original; a
                # right-click outside the selection moves the caret there first
                hit = view.page_at(event.x, event.y)
                if hit is not None and not view.objs.active():
                    if not (ed.has_selection() and view._in_selection(*hit)):
                        if ed.object_at(*hit) and ed.select_object_at(*hit):
                            view.objs.refresh()
                        else:
                            ed.click(hit[0], hit[1], hit[2], False)
                        view.after_move()
                if self.app.settings.get("mini_toolbar", True):
                    try:
                        self.minibar.show(int(event.x), int(event.y) - 4)
                    except Exception:
                        pass
                self.dialogs.context_menu(event)
                return True
            if event.button == 2 and event.type == Gdk.EventType.BUTTON_PRESS and ed is not None:
                hit = view.page_at(event.x, event.y)
                if hit is not None:
                    ed.click(hit[0], hit[1], hit[2], False)
                    view.after_move()
                self.actions.paste_primary()
                return True
            if event.button == 1 and event.type == Gdk.EventType.BUTTON_PRESS and \
                    self.engine.ed is not None:
                hit = view.page_at(event.x, event.y)
                if hit is not None:
                    from .native import equations
                    if equations.click(self, hit[0], hit[1], hit[2]):
                        self.eqbar.ed._pending_click = (event.x, event.y)
                        return True
            return False
        import time
        self._last_input = time.time()
        self.keytips.leave()
        if self.ribbon_full and self.ribbon.get_visible():
            self.peek_ribbon(False)
        if self.eqbar.ed.active and self.eqbar.ed.press(event):
            return True
        from . import hfedit
        if hfedit.press(self, event):
            return True
        if self.text_linker.press(event):
            return True
        from . import editfeatures
        if self.folds.press(event):
            return True
        if event.type == Gdk.EventType._2BUTTON_PRESS and \
                editfeatures.click_and_type(self, event):
            return True
        if event.button == 1 and self.change_bars.mode == "Simple Markup" and \
                self.change_bars.hit(event.x, event.y):
            # clicking a red change bar shows all markup, as in the original
            mc = getattr(self, "markup_choice", None)
            if mc is not None:
                mc.set_active(0)
            else:
                self.set_markup_display("All Markup")
            return True
        if event.button == 1 and not (event.state & Gdk.ModifierType.SHIFT_MASK):
            hit = self._in_left_margin(event.x, event.y)
            if hit is not None:
                count = {Gdk.EventType._2BUTTON_PRESS: 2,
                         Gdk.EventType._3BUTTON_PRESS: 3}.get(event.type, 1)
                self._margin_select(hit, count)
                return True
        if event.type == Gdk.EventType._2BUTTON_PRESS and event.button == 1:
            # double-click on an embedded object: edit it here, never in-place
            from .engine import SEL_COMPLEX
            m = self.engine.model
            if m is not None and self.engine.selection_type() == SEL_COMPLEX:
                obj = docapi.selected_object(m)
                if obj is not None:
                    if docapi.selected_formula_object(m) is not None:
                        self.eqbar.edit(obj)
                    else:
                        self.edit_object(obj)
                    return True
        from . import textmouse
        if textmouse.press(self, event):
            return True
        if event.button == 2 and event.type == Gdk.EventType.BUTTON_PRESS:
            tx, ty = self.engine.px_to_twips(event.x, event.y)
            self.engine.click_at(tx, ty)
            self.engine.sync(self.actions.paste_primary)
            return True
        if event.button == 3:
            # the Mini Toolbar comes with the shortcut menu, as in the original
            if self.app.settings.get("mini_toolbar", True):
                try:
                    self.minibar.show(int(event.x), int(event.y) - 4)
                except Exception:
                    pass
            self.dialogs.context_menu(event)
            return True
        return False

    def object_call(self, fname, *args):
        if self.native:
            from .native import objects
            if self.engine.ed is not None and self.engine.ed.selected_object() is None \
                    and self.engine.ed.story() != "textbox":
                self.status.flash("Select a picture or shape first.")
                return
            if not objects.call(self, fname, *args):
                self.actions._not_yet()
            return
        from . import drawing
        m = self.engine.model
        obj = drawing.selected_shape(m) if m is not None else None
        if obj is None:
            return
        um = m.getUndoManager()
        um.enterUndoContext("Format Object")
        try:
            getattr(drawing, fname)(obj, *args)
        except Exception as e:
            print("object", fname, e)
        finally:
            um.leaveUndoContext()
        if fname in ("crop", "crop_to_ratio", "rotate", "reset_picture", "change_picture",
                     "set_size_locked"):
            self.object_call_refresh()

    def select_tab(self, name):
        tab = [t for t in self.ribbon.tabs if t.name == name]
        if tab:
            self.ribbon.select(tab[0])

    def lock_aspect(self):
        """Pictures keep their proportions when resized, as in the original."""
        if self.native:
            o = self.engine.ed.selected_object() if self.engine.ed else None
            return bool(o and o["kind"] == "picture")
        from . import drawing
        m = self.engine.model
        obj = drawing.selected_shape(m) if m is not None else None
        return obj is not None and drawing.kind_of(obj) == "picture"

    def object_call_refresh(self):
        GLib.timeout_add(100, self.update_object_tabs)

    def object_delete(self):
        if self.native:
            from .native import objects
            objects.delete(self)
            return
        from . import drawing
        m = self.engine.model
        obj = drawing.selected_shape(m) if m is not None else None
        if obj is not None:
            drawing.delete(m, obj)
            self.update_object_tabs()

    def update_object_tabs(self):
        if self.native:
            self.engine._schedule_state()
            return
        from . import drawing
        m = self.engine.model
        kind = None
        multi = False
        if m is not None:
            obj = drawing.selected_shape(m)
            if obj is not None:
                kind = drawing.kind_of(obj)
            else:
                from .arrange import selected_objects
                multi = len(selected_objects(m)) > 1
        chart = False
        if kind == "object":
            from . import charts
            chart = charts.selected_chart(m) is not None
        elif kind == "picture":
            from . import imagecharts
            if imagecharts.is_image_chart(m, drawing.selected_shape(m)):
                chart = True
                kind = "chart-picture"
        self.ribbon.show_contextual("Chart Design", chart)
        self.ribbon.show_contextual("Shape Format", kind in ("shape", "textbox") or multi)
        smart = False
        if kind == "shape":
            from . import insertmore
            smart = insertmore.smartart_of(m, drawing.selected_shape(m)) is not None
        self.ribbon.show_contextual("SmartArt Design", smart)
        self.ribbon.show_contextual("Picture Format", kind == "picture")
        self.layout_options.show(kind in ("picture", "shape", "textbox", "chart-picture"))
        if kind is None and self.crop_mode.active:
            self.crop_mode.cancel()
        if kind is not None:
            try:
                w, h = drawing.size_of(drawing.selected_shape(m))
                for key, v in (("width", w), ("height", h)):
                    for sb in self.obj_spins.get(key, []):
                        if not sb.has_focus():
                            sb._updating = True
                            sb.set_value(v)
                            sb._updating = False
            except Exception:
                pass
            from .panes import AltTextPane
            p = self.panes.get(AltTextPane)
            if p is not None and p.get_parent() is not None:
                p.on_shown()
        self.refresh_hf()
        return False

    def in_header_footer(self):
        m = self.engine.model
        if m is None:
            return False
        try:
            return "HeadFoot" in docapi.read_cursor(m).getText().getImplementationName()
        except Exception:
            return False

    def refresh_hf(self):
        """Show the Header & Footer tab while the cursor is in a header or
        footer, with its options filled in."""
        inside = self.in_header_footer()
        was = getattr(self, "_in_hf", False)
        self._in_hf = inside
        if getattr(self, "hf_overlay", None) is None:
            from .hfview import HFOverlay
            self.hf_overlay = HFOverlay(self)
        self.hf_overlay.update(inside)
        from . import hfedit
        if inside:
            try:
                self._hf_where = (docapi.read_cursor(self.engine.model).PageStyleName,
                                  hfedit.which_part(self)[0])
            except Exception:
                pass
            self.ribbon.update("folio:hf-link", "true" if hfedit.is_linked(self) else "false")
        elif was and getattr(self, "_hf_where", None):
            # leaving a header/footer: sections linked to it follow the edit
            style, part = self._hf_where
            self._hf_where = None
            try:
                hfedit.propagate(self, style, part)
            except Exception as e:
                print("link to previous:", e)
        if inside != was:
            self.ribbon.show_contextual("Header & Footer", inside)
            if inside:
                tab = [t for t in self.ribbon.tabs if t.name == "Header & Footer"]
                if tab:
                    self.ribbon.select(tab[0])
        if not inside:
            return
        try:
            o = docapi.hf_options(self.engine.model)
        except Exception:
            return
        o["show_text"] = self.hf_overlay.show_body
        for k, cb in getattr(self, "hf_checks", {}).items():
            cb.set_checked(o.get(k, False))
        for k, sb in getattr(self, "hf_spins", {}).items():
            if not sb.has_focus():
                sb._updating = True
                sb.set_value(o.get(k, 1270))
                sb._updating = False

    def on_doc_release(self, view, event):
        if self.native:
            if event.button == 1 and not (event.state & Gdk.ModifierType.SHIFT_MASK):
                x, y = event.x, event.y

                def cc_native():
                    try:
                        from .native import controls
                        controls.on_click(self, x, y)
                    except Exception as e:
                        print("content control:", e)
                    return False
                GLib.timeout_add(60, cc_native)
            return False
        if event.button == 1 and not (event.state & Gdk.ModifierType.SHIFT_MASK):
            x, y = event.x, event.y

            def cc_check():
                try:
                    from . import contentcontrols
                    contentcontrols.on_click(self, x, y)
                except Exception as e:
                    print("content control:", e)
                return False
            self.engine.sync(lambda: GLib.timeout_add(90, cc_check))
        if event.button == 1:
            self.engine.sync(lambda: GLib.timeout_add(80, self.update_object_tabs))
            # an equation clicked? (checked once the engine has handled the click)
            cx, cy = event.x, event.y
            self.engine.sync(lambda: GLib.timeout_add(
                60, lambda: (self.eqbar._selection_changed(click=(cx, cy)), False)[1]))
        return False

    def on_password(self, view, url, modify):
        name = os.path.basename(GLib.filename_from_uri(url)[0]) if url.startswith("file:") else url
        pw = self.dialogs.ask_password(
            "Password",
            ("Enter password to modify, or open read only.\n\n\u201c%s\u201d is reserved."
             if modify else "Enter password to open file\n%s") % name)
        view.set_document_password(url, pw)

    def edit_object(self, obj):
        """Embedded objects other than equations (charts...)."""
        try:
            from .charts import is_chart, edit_chart
            if is_chart(obj):
                edit_chart(self, obj)
        except ImportError:
            pass

    def on_link(self, view, url):
        if not url or url.startswith("#"):
            return
        try:
            Gtk.show_uri_on_window(self, url, Gtk.get_current_event_time())
        except GLib.Error:
            subprocess.Popen(["xdg-open", url])

    # ---------------------------------------------------------- panes
    def show_pane(self, cls, side="right"):
        pane = self.panes.get(cls)
        slot = self.left_pane_slot if side == "left" else self.right_pane_slot
        if pane is None:
            pane = cls(self)
            self.panes[cls] = pane
        for ch in slot.get_children():
            if ch is not pane:
                slot.remove(ch)
        if pane.get_parent() is None:
            slot.pack_start(pane, True, True, 0)
        slot.show_all()
        pane.on_shown()
        self._sync_pane_checks()
        return pane

    def hide_pane(self, pane):
        parent = pane.get_parent()
        if parent is not None:
            parent.remove(pane)
            if not parent.get_children():
                parent.hide()
        self._sync_pane_checks()
        self.focus_document()

    # ---------------------------------------------------------- navigation
    def go_back(self):
        """Shift+F5: back to the previous editing position."""
        m = self.engine.model
        if m is None or not self._last_positions:
            return
        rng = self._last_positions.pop()
        try:
            docapi.goto(m, rng)
        except Exception:
            pass

    def remember_position(self):
        m = self.engine.model
        if m is None:
            return
        try:
            vc = docapi.read_cursor(m)
            self._last_positions.append(vc.getText().createTextCursorByRange(vc.getStart()))
            self._last_positions = self._last_positions[-4:]
        except Exception:
            pass

    def extend_selection(self):
        """F8, as in the original: the first press turns on Extend mode (the
        arrow keys then extend the selection); each further press selects
        the word, sentence, paragraph, then the whole document."""
        level = min(getattr(self, "extend_level", 0) + 1, 5) if self.extend_mode else 1
        self.extend_mode = True
        self.extend_level = level
        if level == 1:
            self.status.flash("Extend Selection")
            return
        cmd = {2: ".uno:SelectWord", 3: ".uno:SelectSentence", 4: ".uno:SelectText",
               5: ".uno:SelectAll"}[level]
        self.engine.command(cmd)

    EXTEND_KEYS = {Gdk.KEY_Down: 1024, Gdk.KEY_Up: 1025, Gdk.KEY_Left: 1026,
                   Gdk.KEY_Right: 1027, Gdk.KEY_Home: 1028, Gdk.KEY_End: 1029,
                   Gdk.KEY_Page_Up: 1030, Gdk.KEY_Page_Down: 1031}

    def _extend_key(self, event):
        """Keys while Extend mode is on: moving keys extend the selection."""
        code = self.EXTEND_KEYS.get(event.keyval)
        if code is None:
            if event.keyval not in (Gdk.KEY_F8, Gdk.KEY_Shift_L, Gdk.KEY_Shift_R,
                                    Gdk.KEY_Control_L, Gdk.KEY_Control_R):
                self.extend_mode = False
                self.extend_level = 0
            return False
        code |= 4096
        if event.state & Gdk.ModifierType.CONTROL_MASK:
            code |= 8192
        self.engine.post_key(code)
        return True

    def _table_tab(self, event, back=False):
        """Tab / Shift+Tab in a table: the next cell's text comes selected."""
        m = self.engine.model
        if m is None:
            return False
        try:
            if docapi.view_cursor(m).Cell is None:
                return False
        except Exception:
            return False
        handled = False
        if back:
            try:
                vc = docapi.view_cursor(m)
                names = list(vc.TextTable.getCellNames())
                i = names.index(vc.Cell.CellName)
                if i > 0:
                    cell = vc.TextTable.getCellByName(names[i - 1])
                    cur = cell.getText().createTextCursor()
                    cur.gotoStart(False)
                    cur.gotoEnd(True)
                    if cur.getString():
                        docapi.controller(m).select(cur)
                    else:
                        vc.gotoRange(cur.getStart(), False)
            except Exception as e:
                print("shift+tab:", e)
            return True

        def pick():
            try:
                vc = docapi.view_cursor(m)
                cell = vc.Cell
                if cell is None:
                    return False
                cur = cell.getText().createTextCursor()
                cur.gotoStart(False)
                cur.gotoEnd(True)
                if cur.getString():
                    docapi.controller(m).select(cur)
            except Exception:
                pass
            return False
        self.engine.sync(lambda: GLib.timeout_add(40, pick))
        return handled

    # ---------------------------------------------------------- keys
    def on_key(self, widget, event):
        import time
        self._last_input = time.time()
        if event.keyval == Gdk.KEY_F6:
            ctrl = event.state & Gdk.ModifierType.CONTROL_MASK
            back = event.state & Gdk.ModifierType.SHIFT_MASK
            if ctrl:
                self._cycle_window(-1 if back else 1)
            else:
                self._cycle_region(-1 if back else 1)
            return True
        if self.keytips.active:
            return self.keytips.key(event)
        if self.eqbar.ed.active and self.get_focus() is self.engine.view and \
                not self.backstage.get_visible():
            if self.eqbar.ed.key(event):
                return True
        if self.backstage.get_visible():
            if event.keyval == Gdk.KEY_Escape:
                self.backstage.close()
                return True
            return False
        if self.get_focus() is self.engine.view and self.paste_options.key(event):
            return True
        if self.edit_points.key(event):
            return True
        if self.table_draw.key(event):
            return True
        if self.crop_mode.key(event):
            return True
        if getattr(self, "select_objects", None) is not None and self.select_objects.key(event):
            return True
        if self.ink.key(event):
            return True
        if event.keyval == Gdk.KEY_Escape and getattr(self, "painter", None) is not None \
                and self.painter.active:
            self.painter.stop()
            return True
        if event.keyval == Gdk.KEY_Escape and self.text_linker.pending:
            self.text_linker.cancel()
            return True
        if self.native and event.keyval == Gdk.KEY_Escape and not self.eqbar.ed.active and \
                (self.engine.view.columns > 1 or self.engine.view.side) and \
                self.engine.ed is not None and self.engine.ed.story() == "body":
            self.close_multipage()
            return True
        if self.multipage is not None and event.keyval == Gdk.KEY_Escape:
            self.close_multipage()
            return True
        name = (Gdk.keyval_name(event.keyval) or "").lower()
        self._alt_alone = name in ("alt_l", "alt_r") and not (
            event.state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK))
        focus = self.get_focus()
        in_doc = focus is self.engine.view
        if event.keyval == Gdk.KEY_Escape and getattr(self, "draw", None) and self.draw.active:
            self.draw.cancel()
            return True
        if self.focus_mode and event.keyval == Gdk.KEY_Escape:
            self.act_focus_mode()
            return True
        if event.keyval == Gdk.KEY_F10 and not (event.state & Gdk.ModifierType.MODIFIER_MASK
                                                & ~Gdk.ModifierType.MOD2_MASK):
            self.keytips.start()
            return True
        if self.native and in_doc:
            fc = getattr(self.engine.view, "field_code", None)
            if fc is not None and fc.active and fc.key(event):
                return True
        action, mods, keyname = self.keymap.lookup(event)
        if "alt" in mods and "ctrl" not in mods and action is None and len(keyname) == 1:
            # Alt+letter: ribbon KeyTips
            if self.keytips.start_with(keyname.upper()):
                return True
        if not in_doc:
            # text fields etc. keep their own keys, except the global ones
            if action in ("save", "new", "close", "backstage-print", "toggle-ribbon",
                          "help", "search-box", "backstage-open", "save-as",
                          "next-region", "prev-region", "next-window", "prev-window"):
                self.run(action)
                return True
            return False
        if self.native:
            # the view does the editing keys itself
            if action is not None:
                if action != "extend-selection" and self.extend_mode:
                    self.extend_mode = False
                    self.extend_level = 0
                self.run(action)
                return True
            if self.extend_mode and event.keyval == Gdk.KEY_Escape:
                self.extend_mode = False
                self.extend_level = 0
                return True
            if self.extend_mode and self._extend_key(event):
                return True
            if self.acwatch.tab_indent(keyname, list(mods)):
                return True
            return False
        if self.acwatch.tab_indent(keyname, list(mods)):
            return True
        self.acwatch.before_key(keyname, [m for m in mods if m != "shift"], event)
        if self.extend_mode and event.keyval == Gdk.KEY_Escape:
            self.extend_mode = False
            self.extend_level = 0
            return True
        if self.extend_mode and self._extend_key(event):
            return True
        if keyname in ("tab", "iso_left_tab") and "ctrl" not in mods and "alt" not in mods:
            if self._table_tab(event, back=("shift" in mods or keyname == "iso_left_tab")):
                return True
        if keyname in ("return", "kp_enter") and not mods:
            from .engine import SEL_COMPLEX
            m = self.engine.model
            if m is not None and self.engine.selection_type() == SEL_COMPLEX:
                obj = docapi.selected_object(m)
                if obj is not None:
                    if docapi.selected_formula_object(m) is not None:
                        self.eqbar.edit(obj)
                    else:
                        self.edit_object(obj)
                    return True
        if action is not None:
            if action in ("find-pane", "goto", "replace") or (
                    isinstance(action, str) and action.startswith(".uno:GoTo")):
                self.remember_position()
            self.run(action)
            return True
        if ("ctrl" in mods or "alt" in mods) and keyname not in PASSTHROUGH and \
                keyname not in ("control_l", "control_r", "alt_l", "alt_r", "shift_l",
                                "shift_r", "iso_level3_shift"):
            # not a binding: swallow rather than let the engine act on it,
            # except Ctrl+arrows/Home/End etc. (navigation)
            return True
        if keyname in ("period", "parenright") and "ctrl" not in mods and "alt" not in mods:
            from . import autolist
            if autolist.on_marker_char(self, "." if keyname == "period" else ")"):
                return True
        if keyname == "space" and not mods:
            from . import autolist
            if autolist.on_space(self):
                return True
            from . import eqoptions
            eqoptions.outside_math(self)
        if keyname in ("left", "right") and not mods and self.native and \
                self.engine.ed is not None and not self.eqbar.ed.active:
            from .native import equations
            if equations.arrow_into(self, keyname == "right"):
                return True
        if keyname in ("left", "right") and not mods and self.engine.model is not None:
            # arrowing into an equation edits it, as in the original
            d = 1 if keyname == "right" else -1
            obj = docapi.formula_beside_cursor(self.engine.model, d)
            if obj is not None:
                self.eqbar.ed.start(obj, at=("start" if d > 0 else "end"))
                return True
        if event.keyval in (Gdk.KEY_Page_Up, Gdk.KEY_Page_Down) or \
                (event.keyval in (Gdk.KEY_Home, Gdk.KEY_End) and "ctrl" in mods):
            self.remember_position()
        if self.macro_recorder.active:
            self.macro_recorder.key(event)
        if "alt" not in mods and event.keyval in (
                Gdk.KEY_Home, Gdk.KEY_End, Gdk.KEY_KP_Home, Gdk.KEY_KP_End):
            # LOKDocView drops Home/End (with or without Ctrl/Shift); send
            # them to the engine directly
            code = 1028 if event.keyval in (Gdk.KEY_Home, Gdk.KEY_KP_Home) else 1029
            if "ctrl" in mods:
                code |= 8192
            if "shift" in mods:
                code |= 4096
            self.engine.post_key(code)
            return True
        return False

    def _schedule_gaps(self):
        from . import grammar
        if not grammar.CONTEXT and not grammar.GAPS:
            return
        if getattr(self, "_gaps_timer", 0):
            GLib.source_remove(self._gaps_timer)

        def go():
            self._gaps_timer = 0
            grammar.refresh_gaps(self.engine.model)
            return False
        self._gaps_timer = GLib.timeout_add(250, go)

    def on_key_release(self, widget, event):
        self._schedule_gaps()
        if event.keyval == Gdk.KEY_Caps_Lock:
            try:
                km = Gdk.Keymap.get_for_display(self.get_display())
                self.status.set_caps(km.get_caps_lock_state())
            except Exception:
                pass
        if self.paste_options.key_release(event):
            return True
        name = (Gdk.keyval_name(event.keyval) or "").lower()
        if name in ("alt_l", "alt_r") and self._alt_alone and not self.keytips.active \
                and not self.backstage.get_visible():
            self._alt_alone = False
            self.keytips.start()
            return True
        return False
