"""The window's engine interface (as engine.Engine offers it) over Folio's
own document engine, so the ribbon, keys and status bar drive it."""
import os
import shutil
import tempfile

from gi.repository import GLib, GObject

from . import core
from .view import NativeView

HIGHLIGHT_NAMES = {
    0xFFFF00: "yellow", 0x00FF00: "green", 0x00FFFF: "cyan", 0xFF00FF: "magenta",
    0x0000FF: "blue", 0xFF0000: "red", 0x000080: "darkBlue", 0x008080: "darkCyan",
    0x008000: "darkGreen", 0x800080: "darkMagenta", 0x800000: "darkRed",
    0x808000: "darkYellow", 0x808080: "darkGray", 0xC0C0C0: "lightGray", 0x000000: "black",
}

TABLE_COMMANDS = {
    ".uno:InsertRowsBefore": "insert_rows_above", ".uno:InsertRowsAfter": "insert_rows_below",
    ".uno:InsertColumnsBefore": "insert_cols_left", ".uno:InsertColumnsAfter": "insert_cols_right",
    ".uno:DeleteRows": "delete_rows", ".uno:DeleteColumns": "delete_cols",
    ".uno:DeleteTable": "delete_table", ".uno:MergeCells": "merge",
}

# Word's font size steps (Grow/Shrink Font)
SIZES = [8, 9, 10, 11, 12, 14, 16, 18, 20, 22, 24, 26, 28, 36, 48, 72]


def _clip_path():
    d = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir(), "folio-writer")
    os.makedirs(d, mode=0o700, exist_ok=True)
    return os.path.join(d, "clipboard.json")


def _store_fragment(text, xml, token):
    import json
    try:
        with open(_clip_path(), "w") as f:
            json.dump({"text": text, "xml": xml, "token": token}, f)
    except OSError as e:
        print("clipboard:", e)


def _load_fragment(text):
    """The formatted copy that goes with the clipboard's text, if Folio made
    it: (xml, document token)."""
    import json
    try:
        with open(_clip_path()) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    if d.get("text") == text and d.get("xml"):
        return d["xml"], d.get("token", "")
    return None


def _user_name():
    try:
        import pwd
        n = pwd.getpwuid(os.getuid()).pw_gecos.split(",")[0]
        return n or os.environ.get("USER", "Author")
    except Exception:
        return os.environ.get("USER", "Author")


def _arg(args, key, default=None):
    if not args:
        return default
    v = args.get(key, default)
    if isinstance(v, tuple):
        v = v[1]
    return v


LIST_STYLES = {
    ".uno:BulletListStyle": ("bullet", "o", "Courier New"),
    ".uno:NumberListStyle": ("decimal", "%1)", None),
    ".uno:AlphaListStyle": ("upperLetter", "%1.", None),
    ".uno:AlphaLowListStyle": ("lowerLetter", "%1)", None),
    ".uno:RomanListStyle": ("upperRoman", "%1.", None),
    ".uno:RomanLowListStyle": ("lowerRoman", "%1.", None),
}
CASES = {".uno:ChangeCaseToSentenceCase": "sentence", ".uno:ChangeCaseToLower": "lower",
         ".uno:ChangeCaseToUpper": "upper", ".uno:ChangeCaseToTitleCase": "title",
         ".uno:ChangeCaseToToggleCase": "toggle"}

def _is_zip(path):
    try:
        with open(path, "rb") as fh:
            return fh.read(4) == b"PK\x03\x04"
    except OSError:
        return False


class NativeEngine(GObject.GObject):
    native = True
    __gsignals__ = {
        "state-changed": (GObject.SignalFlags.RUN_LAST, None, (str, str)),
        "loaded": (GObject.SignalFlags.RUN_LAST, None, (bool,)),
        "zoom-changed": (GObject.SignalFlags.RUN_LAST, None, (float,)),
        "model-ready": (GObject.SignalFlags.RUN_LAST, None, ()),
        "engine-dialog": (GObject.SignalFlags.RUN_LAST, None, (str,)),
    }

    def __init__(self, profile_dir=None, author=""):
        super().__init__()
        self.author = author
        self.view = NativeView()
        self._model = None         # no UNO model: features that need it stay off
        self.ed = None
        self.state = {}
        self.path = None
        self.format = "docx"
        self.is_new = True
        self.save_hooks = []
        self.written_hooks = []
        self._state_id = 0
        self.view.connect("changed", lambda *_: self._schedule_state())
        self.view.connect("selection-changed", lambda *_: self._schedule_state())
        self.view.connect("zoom-changed", lambda v, z: self.emit("zoom-changed", z))
        from . import review
        self.view.get_command_values = lambda cmd: review.command_values(self, cmd)
        self._cm_id = 0
        self.view.connect("changed", lambda *_: self._schedule_comments())

    # which features asked for the old engine's document model (they do nothing here)
    model_wanted = {}

    @property
    def model(self):
        if self._model is None:
            import sys as _sys
            f = _sys._getframe(1)
            key = "%s:%s" % (os.path.basename(f.f_code.co_filename), f.f_code.co_name)
            NativeEngine.model_wanted[key] = NativeEngine.model_wanted.get(key, 0) + 1
        return self._model

    @model.setter
    def model(self, v):
        self._model = v

    def _schedule_comments(self):
        """Comment balloons follow the text they mark after edits."""
        win = getattr(self, "win", None)
        margin = getattr(win, "comments", None) if win is not None else None
        if margin is None or self._cm_id or not margin.comments:
            return

        def run():
            self._cm_id = 0
            margin.reload()
            return False
        self._cm_id = GLib.timeout_add(250, run)

    # --------------------------------------------------------------- files
    def _import(self, path):
        """An Editor for a file that isn't Word's own format: plain text read
        here; .doc, .odt, .rtf and the rest through LibreOffice's converter,
        when it's installed."""
        ext = os.path.splitext(path)[1].lower()
        if ext in (".txt", ".text", ".md", ".csv", ".log"):
            tpl = None
            here = os.path.dirname(os.path.abspath(__file__))
            for d in ("/usr/share/folio-writer/templates",
                      os.path.join(here, "..", "..", "..", "share", "templates")):
                p = os.path.join(d, "Normal-Letter.docx")
                if os.path.exists(p):
                    tpl = p
                    break
            ed = core().Editor.open(tpl)
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read().replace("\r\n", "\n").replace("\r", "\n")
            if text:
                ed.type_text(text.rstrip("\n"))
            ed.move_caret("doc_start", False)
            return ed
        import shutil
        import subprocess
        soffice = shutil.which("soffice") or shutil.which("libreoffice")
        if not soffice:
            raise RuntimeError("needs-converter")
        tmpd = tempfile.mkdtemp(prefix="folio-")
        try:
            r = subprocess.run([soffice, "--headless", "--convert-to", "docx:MS Word 2007 XML",
                                "--outdir", tmpd, path], capture_output=True, timeout=180)
            out = os.path.join(tmpd, os.path.splitext(os.path.basename(path))[0] + ".docx")
            if r.returncode != 0 or not os.path.exists(out):
                raise RuntimeError("conversion failed")
            return core().Editor.open(out)
        finally:
            shutil.rmtree(tmpd, ignore_errors=True)

    def open(self, path, on_done=None):
        self.open_error = None
        try:
            if os.path.splitext(path)[1].lower() in (".docx", ".docm", ".dotx", ".dotm", "") \
                    or _is_zip(path):
                ed = core().Editor.open(path)
            else:
                ed = self._import(path)
        except Exception as e:
            self.open_error = str(e)
            print("open:", e)
            if on_done:
                GLib.idle_add(lambda: (on_done(False), False)[1])
            self.emit("loaded", False)
            return
        self.ed = ed
        self.path = path
        ed.set_file_name(os.path.abspath(path))
        ed.set_author(self.author or _user_name())
        self.is_new = False
        self.format = os.path.splitext(path)[1].lower().lstrip(".") or "docx"
        self.view.set_editor(ed)
        self._schedule_state()
        self.emit("loaded", True)
        if on_done:
            GLib.idle_add(lambda: (on_done(True), False)[1])

    def new(self, template, on_done=None):
        """A new document from the Normal template (.docx)."""
        base, ext = os.path.splitext(template)
        # Set as Default keeps the user's own .docx Normal template
        user = os.path.join(os.path.expanduser("~/.config/folio-writer/templates"),
                            os.path.basename(base) + ".docx")
        try:
            from ..app import CONFIG
            user = os.path.join(CONFIG, "templates", os.path.basename(base) + ".docx")
        except Exception:
            pass
        if os.path.exists(user):
            template, ext = user, ".docx"
        if ext.lower() != ".docx":
            cand = base + ".docx"
            if os.path.exists(cand):
                template = cand
            else:
                here = os.path.dirname(os.path.abspath(__file__))
                for d in ("/usr/share/folio-writer/templates",
                          os.path.join(here, "..", "..", "..", "share", "templates")):
                    p = os.path.join(d, os.path.basename(base) + ".docx")
                    if os.path.exists(p):
                        template = p
                        break

        def done(ok):
            self.path = None
            self.is_new = True
            self.format = "docx"
            if on_done:
                on_done(ok)
        self.open(template, done)
        self.is_new = True
        self.path = None

    def save(self):
        if not self.path:
            return False
        return self.save_as(self.path)

    def save_as(self, path, fmt=None, options=None, keep=True, filter_data=None):
        ext = (fmt or os.path.splitext(path)[1].lstrip(".") or "docx").lower()
        try:
            if ext == "pdf":
                fd = filter_data or {}
                pages = []
                rng = str(fd.get("PageRange", "") or "").replace(" ", "")
                for part in [x for x in rng.split(",") if x]:
                    a, _, b = part.partition("-")
                    try:
                        lo = int(a)
                        hi = int(b) if b else lo
                        pages += list(range(lo - 1, hi))
                    except ValueError:
                        pass
                n = self.ed.page_count()
                pages = [p for p in pages if 0 <= p < n]
                if rng and not pages:
                    self.save_error = "The page range is outside the document (it has %d page%s)." % (n, "" if n == 1 else "s")
                    return False
                from . import docprops
                c = docprops.core(self.ed)
                self.ed.export_pdf_opts(path, pages, bool(fd.get("ExportBookmarks", True)),
                                        c.get("title", ""), c.get("creator", ""),
                                        c.get("subject", ""), c.get("keywords", ""))
                return True
            try:
                from . import docprops
                docprops.stamp_saved(self.ed, self.author or _user_name())
            except Exception as e:
                print("properties:", e)
            if ext == "txt":
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write("\n".join(self.plain_lines()) + "\n")
                return True
            if ext in ("html", "htm", "rtf"):
                return self._save_own(path, ext)
            if ext not in ("docx", "docm", "dotx"):
                return self._save_converted(path, ext)
            self.ed.save(path)
        except Exception as e:
            print("save:", e)
            return False
        if keep:
            self.path = path
            self.ed.set_file_name(os.path.abspath(path))
            self.is_new = False
            self.format = ext
        self._schedule_state()
        return True

    def plain_lines(self):
        """The body as plain text, as Word saves it: a line per paragraph, table
        cells separated by tabs."""
        ed = self.ed
        out = []
        for kind, node, ti in ed.body_blocks():
            if kind == "p":
                out.append(ed.para_text_of(node).replace("\ufffc", ""))
            else:
                for row in ed.table_cells(ti):
                    out.append("\t".join(" ".join(ed.para_text_of(p) for p in cell).replace("\ufffc", "") for cell in row))
        return out

    def _save_own(self, path, ext):
        """Web Page and Rich Text Format, written by Folio itself."""
        from . import htmlexport
        tmpd = tempfile.mkdtemp(prefix="folio-")
        try:
            src = os.path.join(tmpd, "doc.docx")
            self.ed.save(src)
            if ext == "rtf":
                data = htmlexport.docx_to_rtf(src)
                with open(path, "w", encoding="ascii", errors="replace") as fh:
                    fh.write(data)
            else:
                try:
                    labels = dict(enumerate(self.ed.body_labels()))
                except Exception:
                    labels = {}
                title = os.path.splitext(os.path.basename(path))[0]
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(htmlexport.docx_to_html(src, title, {k: v for k, v in labels.items() if v}))
            return True
        finally:
            shutil.rmtree(tmpd, ignore_errors=True)

    def _save_converted(self, path, ext):
        """Other formats (.doc, .odt, .rtf, .txt...) go through LibreOffice's
        converter, from the .docx."""
        import subprocess
        if not (shutil.which("soffice") or shutil.which("libreoffice")):
            self.save_error = "needs-converter"
            return False
        tmpd = tempfile.mkdtemp(prefix="folio-")
        try:
            src = os.path.join(tmpd, "doc.docx")
            self.ed.save(src)
            filt = {"doc": "doc:MS Word 97", "odt": "odt", "rtf": "rtf", "txt": "txt:Text",
                    "html": "html:HTML (StarWriter)", "epub": "epub"}.get(ext, ext)
            r = subprocess.run(["soffice", "--headless", "--convert-to", filt, "--outdir", tmpd,
                                src], capture_output=True, timeout=120)
            out = os.path.join(tmpd, "doc." + ext)
            if r.returncode != 0 or not os.path.exists(out):
                return False
            shutil.move(out, path)
            return True
        finally:
            shutil.rmtree(tmpd, ignore_errors=True)

    @property
    def modified(self):
        return bool(self.ed and self.ed.modified)

    def mark_saved(self):
        if self.ed:
            self.ed.mark_saved()
        self.emit("state-changed", ".uno:ModifiedStatus", "false")

    # ------------------------------------------------------------- state
    def _schedule_state(self):
        if not self._state_id:
            self._state_id = GLib.idle_add(self._push_state)

    def _set(self, key, value):
        if self.state.get(key) != value:
            self.state[key] = value
            self.emit("state-changed", key, value)

    def _push_state(self):
        self._state_id = 0
        if self.ed is None:
            return False
        s = self.ed.state()
        b = lambda v: "true" if v else "false"
        self._set(".uno:TableBoundaries", b(getattr(self.view, "gridlines", True)))
        self._set(".uno:ControlCodes", b(getattr(self.view, "marks", False)))
        self._set(".uno:Bold", b(s["bold"]))
        self._set(".uno:Italic", b(s["italic"]))
        self._set(".uno:Underline", b(s["underline"] != "none"))
        self._set(".uno:UnderlineDouble", b(s["underline"] == "double"))
        self._set(".uno:Strikeout", b(s["strike"]))
        self._set(".uno:SuperScript", b(s["vert_align"] == "superscript"))
        self._set(".uno:SubScript", b(s["vert_align"] == "subscript"))
        self._set(".uno:CharFontName", s["font"])
        size = s["size"]
        self._set(".uno:FontHeight", ("%g" % size))
        al = s["align"]
        self._set(".uno:LeftPara", b(al in ("left", "start")))
        self._set(".uno:CenterPara", b(al == "center"))
        self._set(".uno:RightPara", b(al in ("right", "end")))
        self._set(".uno:JustifyPara", b(al in ("both", "distribute")))
        self._set(".uno:StyleApply", s["style"])
        self._set(".uno:Undo", "enabled" if s["can_undo"] else "disabled")
        self._set(".uno:Redo", "enabled" if s["can_redo"] else "disabled")
        self._set(".uno:StatePageNumber", "Page %d of %d" % (s["page"], s["pages"]))
        words, chars = self.ed.counts()
        self._set(".uno:StateWordCount", "%s words, %s characters" % (
            "{:,}".format(words), "{:,}".format(chars)))
        self._set(".uno:ModifiedStatus", b(s["modified"]))
        self._set(".uno:DefaultBullet", b(s.get("list") == "bullet"))
        self._set(".uno:DefaultNumbering", b(s.get("list") == "number"))
        self._set(".uno:StateTableCell", self.ed.cell_name())
        self._set(".uno:StateNativeHF", "true" if self.ed.story() == "hf" else "false")
        self._set(".uno:InsertFootnote", "enabled" if self.ed.story() == "body" else "disabled")
        o = self.ed.selected_object()
        self._set(".uno:StateNativeObject", "%s:%.1f:%.1f" % (o["kind"], o["w"], o["h"]) if o else "")
        self._set(".uno:TrackChanges", b(self.ed.track_changes()))
        self._set(".uno:ShowTrackedChanges", b(self.ed.markup() == "all"))
        self._set(".uno:ShowChangesInMargin", b(self.ed.balloons()))
        self._set(".uno:InsertMode", "true")
        return False

    def get(self, cmd, default=""):
        return self.state.get(cmd, default)

    def is_on(self, cmd):
        return self.state.get(cmd) == "true"

    def sync(self, fn):
        fn()

    # ---------------------------------------------------------- commands
    def _edit(self, fn, *a):
        if self.ed is None:
            return
        fn(*a)
        self.view.after_edit()

    def command(self, cmd, args=None, notify=False):
        """The engine commands the ribbon and keys send; returns False for
        ones this engine doesn't do yet."""
        ed = self.ed
        if ed is None:
            return False
        if "?" in cmd and not args:
            from .actions import split_command
            cmd, args = split_command(cmd)
        toggles = {".uno:Bold": "w:b", ".uno:Italic": "w:i", ".uno:Strikeout": "w:strike"}
        from . import objects
        if cmd in (".uno:InsertFootnote", ".uno:InsertEndnote"):
            if ed.story() != "body":
                # as in the original: notes go in the main text only
                try:
                    self.win.status.flash("Notes can only be inserted in the main text.")
                except Exception:
                    pass
                return True
            ok = ed.insert_note(cmd == ".uno:InsertEndnote")
            self.view.document_changed()
            self.view.scroll_to_caret()
            return ok
        if cmd in (".uno:JumpToHeader", ".uno:JumpToFooter"):
            pg = ed.story_page()
            pg = ed.caret_page() if pg is None else pg
            footer = cmd == ".uno:JumpToFooter"
            if not ed.page_hf(pg)[1 if footer else 0]:
                ed.ensure_header_footer_kind(ed.page_section(pg), footer, ed.page_hf_kind(pg))
            ed.edit_header_footer(pg, footer)
            self.view.document_changed()
            self.view.scroll_to_caret()
            return True
        from . import review
        if cmd in review.COMMANDS:
            return review.command(self, cmd, args)
        if cmd in objects.UNO:
            return objects.uno_command(self.win, cmd) if getattr(self, "win", None) else False
        aligns = {".uno:LeftPara": "left", ".uno:CenterPara": "center",
                  ".uno:RightPara": "right", ".uno:JustifyPara": "both"}
        if cmd in (".uno:SelectWord", ".uno:SelectSentence", ".uno:SelectText"):
            from .units import select_unit
            select_unit(ed, {".uno:SelectWord": "word", ".uno:SelectSentence": "sentence",
                             ".uno:SelectText": "paragraph"}[cmd])
            self.view.after_move()
            return True
        if cmd in (".uno:DelToStartOfWord", ".uno:DelToEndOfWord"):
            ed.delete(cmd == ".uno:DelToEndOfWord", True)
            self.view.after_edit()
            return True
        if cmd in toggles:
            self._edit(ed.toggle, toggles[cmd])
        elif cmd == ".uno:Underline":
            # what the text has now (the reported state may lag behind fast typing)
            cur = (ed.run_values() or {}).get("underline", "none")
            self._edit(ed.set_underline, "none" if cur not in ("none", None, "") else "single")
        elif cmd == ".uno:UnderlineDouble":
            self._edit(ed.set_underline,
                       "none" if self.is_on(".uno:UnderlineDouble") else "double")
        elif cmd == ".uno:SuperScript":
            self._edit(ed.set_vert_align, "superscript")
        elif cmd == ".uno:SubScript":
            self._edit(ed.set_vert_align, "subscript")
        elif cmd in aligns:
            self._edit(ed.set_align, aligns[cmd])
        elif cmd == ".uno:CharFontName":
            name = _arg(args, "CharFontName.FamilyName")
            if name:
                self._edit(ed.set_font, name)
        elif cmd == ".uno:FontHeight":
            v = _arg(args, "FontHeight.Height")
            try:
                self._edit(ed.set_size, float(v))
            except (TypeError, ValueError):
                return False
        elif cmd in (".uno:Grow", ".uno:Shrink"):
            self.step_size(1 if cmd == ".uno:Grow" else -1)
        elif cmd in (".uno:Color", ".uno:FontColor"):
            c = _arg(args, "Color", _arg(args, "FontColor"))
            try:
                c = int(c)
            except (TypeError, ValueError):
                return False
            self._edit(ed.set_color, "auto" if c < 0 else "%06X" % (c & 0xFFFFFF))
        elif cmd in (".uno:CharBackColor", ".uno:BackColor"):
            c = _arg(args, "CharBackColor.Color", _arg(args, "BackColor"))
            try:
                c = int(c)
            except (TypeError, ValueError):
                return False
            self._edit(ed.set_highlight, "none" if c < 0 else HIGHLIGHT_NAMES.get(c & 0xFFFFFF,
                                                                                  "yellow"))
        elif cmd == ".uno:BackgroundColor":
            # Home > Shading: the selected text, or the paragraph when nothing is selected
            c = _arg(args, "BackgroundColor")
            try:
                c = int(c)
            except (TypeError, ValueError):
                return False
            shd = None if c < 0 else [("w:val", "clear"), ("w:color", "auto"), ("w:fill", "%06X" % (c & 0xFFFFFF))]
            a = ed.selection_range()
            if ed.has_selection() and a[0] == a[2] and not (a[1] == 0 and a[3] >= len(ed.para_text_of(a[0]))):
                self._edit(ed.apply_run, [("w:shd", shd)], "Shading")
            else:
                self._edit(ed.apply_para, [("w:shd", shd)], "Shading")
        elif cmd == ".uno:StyleApply":
            self.apply_style(_arg(args, "Style", ""))
        elif cmd == ".uno:ResetAttributes":
            self._edit(ed.clear_formatting)
        elif cmd == ".uno:Undo":
            self._edit(ed.undo)
        elif cmd == ".uno:Redo":
            self._edit(ed.redo)
        elif cmd == ".uno:SelectAll":
            ed.select_all()
            self.view.after_move()
        elif cmd == ".uno:InsertText":
            t = _arg(args, "Text", "")
            if t:
                self._edit(ed.type_text, t)
        elif cmd == ".uno:InsertPara":
            self._edit(ed.type_text, "\n")
        elif cmd == ".uno:InsertLinebreak":
            self._edit(ed.type_text, "\u000b")
        elif cmd in (".uno:GoToStartOfDoc", ".uno:GoToEndOfDoc"):
            ed.move_caret("doc_start" if cmd.endswith("StartOfDoc") else "doc_end", False)
            self.view.after_move()
        elif cmd in (".uno:SpacePara1", ".uno:SpacePara15", ".uno:SpacePara2"):
            v = {".uno:SpacePara1": 240, ".uno:SpacePara15": 360, ".uno:SpacePara2": 480}[cmd]
            self._edit(ed.set_line_spacing, "auto", v)
        elif cmd in (".uno:Copy", ".uno:Cut"):
            self.copy(cut=cmd == ".uno:Cut")
        elif cmd == ".uno:Paste":
            self.paste()
        elif cmd in LIST_STYLES:
            fmt, text, font = LIST_STYLES[cmd]
            self._edit(ed.set_list_format, fmt, text, font)
        elif cmd == ".uno:RemoveBullets":
            self._edit(ed.remove_list)
        elif cmd in CASES:
            self._edit(ed.change_case, CASES[cmd])
        elif cmd in (".uno:InsertPagebreak", ".uno:InsertColumnBreak"):
            self._edit(ed.insert_break, "page" if cmd == ".uno:InsertPagebreak" else "column")
        elif cmd == ".uno:ControlCodes":
            on = not self.view.marks
            self.view.set_marks(on)
            self._set(".uno:ControlCodes", "true" if on else "false")
        elif cmd in (".uno:DefaultBullet", ".uno:DefaultNumbering"):
            self._edit(ed.toggle_list, "bullet" if cmd == ".uno:DefaultBullet" else "number")
        elif cmd in (".uno:IncrementLevel", ".uno:DecrementLevel"):
            if ed.change_list_level(1 if cmd == ".uno:IncrementLevel" else -1):
                self.view.after_edit()
        elif cmd == ".uno:InsertTable":
            try:
                cols = int(_arg(args, "Columns", 2))
                rows = int(_arg(args, "Rows", 2))
            except (TypeError, ValueError):
                cols, rows = 2, 2
            self._edit(ed.insert_table, rows, cols)
        elif cmd == ".uno:TableCellBackgroundColor":
            from . import tables
            try:
                c = int(_arg(args, "TableCellBackgroundColor", -1))
            except (TypeError, ValueError):
                c = -1
            tables.shading(self._win(), c)
        elif cmd in (".uno:DistributeColumns",):
            from . import tables
            tables.distribute(self._win(), "cols")
        elif cmd in (".uno:EntireRow", ".uno:EntireColumn", ".uno:SelectTable"):
            from . import tables
            tables.select(self._win(), {".uno:EntireRow": "row", ".uno:EntireColumn": "column",
                                        ".uno:SelectTable": "table"}[cmd])
        elif cmd == ".uno:SetOptimalColumnWidth":
            self._edit(ed.autofit_contents)
        elif cmd == ".uno:DistributeRows":
            self._edit(ed.distribute_rows)
        elif cmd == ".uno:TableBoundaries":
            on = not self.view.gridlines
            self.view.set_gridlines(on)
            self._set(".uno:TableBoundaries", "true" if on else "false")
        elif cmd in TABLE_COMMANDS:
            if ed.table_command(TABLE_COMMANDS[cmd]):
                self.view.after_edit()
        elif cmd in (".uno:ZoomPlus", ".uno:ZoomMinus"):
            self.zoom(self.view.get_zoom() + (0.1 if cmd == ".uno:ZoomPlus" else -0.1))
        else:
            return False
        return True

    def _win(self):
        w = self.view.get_toplevel()
        return w

    def step_size(self, d):
        try:
            cur = float(self.get(".uno:FontHeight") or 11)
        except ValueError:
            cur = 11.0
        if d > 0:
            nxt = next((s for s in SIZES if s > cur), cur + 10)
        else:
            nxt = next((s for s in reversed(SIZES) if s < cur), max(1, cur - 1))
        self._edit(self.ed.set_size, float(nxt))

    # Word's built-in styles a template may not carry yet: made when first used
    BUILTIN = {
        "List Bullet": ("ListBullet", '<w:pPr><w:ind w:left="360" w:hanging="360"/><w:contextualSpacing/></w:pPr>', "bullet"),
        "List Number": ("ListNumber", '<w:pPr><w:ind w:left="360" w:hanging="360"/><w:contextualSpacing/></w:pPr>', "number"),
        "Quote": ("Quote", '<w:pPr><w:spacing w:before="200" w:after="160"/><w:ind w:left="864" w:right="864"/>'
                  '<w:jc w:val="center"/></w:pPr><w:rPr><w:i/><w:iCs/><w:color w:val="404040"/></w:rPr>', None),
        "Intense Quote": ("IntenseQuote", '<w:pPr><w:pBdr><w:top w:val="single" w:sz="4" w:space="10" w:color="4472C4"/>'
                          '<w:bottom w:val="single" w:sz="4" w:space="10" w:color="4472C4"/></w:pBdr>'
                          '<w:spacing w:before="360" w:after="360"/><w:ind w:left="864" w:right="864"/><w:jc w:val="center"/>'
                          '</w:pPr><w:rPr><w:i/><w:iCs/><w:color w:val="4472C4"/></w:rPr>', None),
        "No Spacing": ("NoSpacing", '<w:pPr><w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr>', None),
    }

    def apply_style(self, name):
        if not name or self.ed is None:
            return
        for sid, nm in self.ed.paragraph_styles():
            if nm == name or sid == name:
                self._edit(self.ed.set_style, sid)
                if name in self.BUILTIN and self.BUILTIN[name][2] and self.ed.list_info() is None:
                    self._edit(self.ed.toggle_list, self.BUILTIN[name][2])
                return
        for sid, nm in self.ed.character_styles():
            if nm == name or sid == name:
                self._edit(self.ed.set_char_style, sid)
                return
        if name in self.BUILTIN:
            sid, body, _lst = self.BUILTIN[name]
            from xml.sax.saxutils import quoteattr
            self.ed.add_style_xml('<w:style w:type="paragraph" w:styleId=%s><w:name w:val=%s/>'
                                  '<w:basedOn w:val="Normal"/><w:uiPriority w:val="9"/><w:qFormat/>%s</w:style>'
                                  % (quoteattr(sid), quoteattr(name), body))
            if any(s == sid for s, _n in self.ed.paragraph_styles()):
                self.apply_style(name)

    def paragraph_styles(self):
        return [nm for _sid, nm in self.ed.paragraph_styles()] if self.ed else []

    # ------------------------------------------------------- clipboard
    def selection(self, mime="text/plain;charset=utf-8"):
        return self.ed.selected_text() if self.ed else ""

    def copy(self, cut=False):
        from gi.repository import Gdk, Gtk
        t = self.selection()
        if not t:
            return
        # the formatted copy, for pasting in Folio: kept beside the text
        try:
            frag = self.ed.copy_fragment()
        except Exception as e:
            print("copy:", e)
            frag = None
        html = None
        if frag:
            try:
                from . import htmlexport
                html = htmlexport.fragment_to_html(frag, self.ed.paragraph_styles())
            except Exception as e:
                print("copy html:", e)
        cb = None
        try:
            cb = self.win.app.clipboard()
        except Exception:
            cb = None
        if html and cb is not None:
            cb.set(html, t)
        else:
            Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(t, -1)
        _store_fragment(t, frag, self._doc_token())
        if cut:
            self._edit(self.ed.delete, True)

    def _doc_token(self):
        return "%d:%d" % (os.getpid(), id(self.ed))

    def paste(self, plain=False):
        from gi.repository import Gdk, Gtk
        cb = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        t = cb.wait_for_text()
        html_atom = Gdk.Atom.intern("text/html", False)
        if not t and not plain and cb.wait_is_target_available(html_atom):
            # formatted text only (some programs offer no plain text)
            sel = cb.wait_for_contents(html_atom)
            if sel is not None and self.paste_html(bytes(sel.get_data())):
                return
        if t:
            frag = None if plain else _load_fragment(t)
            if frag is not None and self.ed is not None:
                xml, token = frag
                self._edit(self.ed.paste_fragment, xml, token == self._doc_token())
                return
            # another program's formatted copy (a web page, a mail)
            if not plain and cb.wait_is_target_available(Gdk.Atom.intern("text/html", False)):
                sel = cb.wait_for_contents(Gdk.Atom.intern("text/html", False))
                if sel is not None and self.paste_html(bytes(sel.get_data())):
                    return
            self.paste_data("text/plain;charset=utf-8", t)
            return
        img = cb.wait_for_image() if cb.wait_is_image_available() else None
        if img is not None and self.ed is not None:
            import os as _os
            fd, path = tempfile.mkstemp(suffix=".png", prefix="folio-paste-")
            _os.close(fd)
            try:
                img.savev(path, "png", [], [])
                self._edit(self.ed.insert_picture, path)
            finally:
                _os.unlink(path)

    def paste_html(self, data):
        """Formatted text from HTML; False when there's nothing in it to paste."""
        if self.ed is None:
            return False
        if isinstance(data, bytes):
            if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
                data = data.decode("utf-16", "replace")
            else:
                data = data.decode("utf-8", "replace")
        from . import htmlpaste
        xml = htmlpaste.to_fragment(data, [sid for sid, _n in self.ed.paragraph_styles()])
        if not xml:
            return False
        ok = self.ed.paste_fragment(xml, False)
        self.view.after_edit()
        return bool(ok)

    def paste_data(self, mime, data):
        if self.ed is None:
            return
        if mime.startswith("text/html"):
            if not self.paste_html(data):
                import re as _re
                import html as _html
                text = _html.unescape(_re.sub(r"<[^>]+>", "", data if isinstance(data, str) else data.decode("utf-8", "replace")))
                self._edit(self.ed.type_text, text)
            return
        if mime == "image/png":
            fd, path = tempfile.mkstemp(suffix=".png", prefix="folio-paste-")
            os.write(fd, data)
            os.close(fd)
            try:
                self._edit(self.ed.insert_picture, path)
            finally:
                os.unlink(path)
            return
        if mime == "text/rtf":
            from . import rtfpaste
            data = rtfpaste.to_text(data)
            mime = "text/plain"
        if isinstance(data, bytes):
            data = data.decode("utf-8", "replace")
        if mime.startswith("text/plain"):
            self._edit(self.ed.type_text, data.replace("\r\n", "\n"))

    # ------------------------------------------------------------- view
    def zoom(self, factor):
        self.view.set_zoom(factor)

    def selection_type(self):
        return 1 if self.ed and self.ed.has_selection() else 0

    # the original engine's key codes, as Extend mode sends them
    KEY_MOVES = {1024: ("down", "para_down"), 1025: ("up", "para_up"), 1026: ("left", "word_left"),
                 1027: ("right", "word_right"), 1028: ("home", "doc_start"), 1029: ("end", "doc_end")}

    def post_key(self, key_code, char_code=0):
        ed = self.ed
        if ed is None:
            return
        base = key_code & 4095
        shift = bool(key_code & 4096)
        ctrl = bool(key_code & 8192)
        if base in self.KEY_MOVES:
            plain, with_ctrl = self.KEY_MOVES[base]
            ed.move_caret(with_ctrl if ctrl else plain, shift)
        elif base in (1030, 1031):
            ed.move_by(500.0 if base == 1031 else -500.0, shift)
        else:
            return
        self.view.after_move()

    # Document coordinates (twips) stack the pages top to bottom with a gap,
    # as the original engine's do.
    PAGE_GAP_TW = 400

    def page_rects(self):
        out = []
        if self.ed is None:
            return out
        y = 0
        for i in range(self.ed.page_count()):
            w, h = self.ed.page_size(i)
            out.append((0, y, int(w * 20), int(h * 20)))
            y += int(h * 20) + self.PAGE_GAP_TW
        return out

    def render(self, x, y, w, h, width_px):
        from .views import render
        return render(self.win, x, y, w, h, width_px)

    def page_top_tw(self, page):
        r = self.page_rects()
        return r[page][1] if 0 <= page < len(r) else 0

    def px_to_twips(self, x, y):
        hit = self.view.page_at(x, y)
        if hit is None:
            return 0, 0
        return int(hit[1] * 20), self.page_top_tw(hit[0]) + int(hit[2] * 20)

    def twips_to_px(self, x, y):
        rects = self.page_rects()
        pg = 0
        for i, (_rx, ry, _rw, _rh) in enumerate(rects):
            if y >= ry - self.PAGE_GAP_TW:
                pg = i
        top = rects[pg][1] if rects else 0
        return self.view.to_widget(pg, x / 20.0, (y - top) / 20.0)

    def fonts(self, all_fonts=False):
        from ..engine import _FONT_JUNK, latin_font_families
        try:
            names = latin_font_families() or set()
        except Exception:
            names = set()
        names = sorted(names, key=str.lower)
        if all_fonts:
            return names
        return [n for n in names if not _FONT_JUNK.search(n)] or names

    def values(self, cmd):
        return {}
