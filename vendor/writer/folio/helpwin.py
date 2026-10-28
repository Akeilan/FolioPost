"""Help: keyboard shortcuts and short how-to topics, searchable."""
import os
import re

from gi.repository import Gtk, Pango

from . import APP_NAME, SHARE

TOPICS = [
    ("Get started", """\
Type to start. Use the Home tab for fonts, paragraphs and styles; the
Insert tab for tables, pictures, links and equations; Layout for margins,
orientation and paper size.

Press Alt (or F10) to show KeyTips: letters appear on the ribbon. Type a
letter to open a tab, then the letters on a command to use it - for
example Alt, H, B to open Borders.

Save with Ctrl+S. New documents are saved as .docx unless you choose
another format in Save As (F12)."""),
    ("Equations", """\
Press Alt+= to insert an equation. The equation bar above the page shows
the equation in linear form; the page shows it built up as you type.

  a/b          fraction           x^2, x_i      superscript, subscript
  \\sqrt(x)     square root        \\sum_(i=1)^n  sum with limits
  (a+b)        brackets grow      \\matrix(a&b@c&d)  matrix
  \\alpha       Greek letters      \\to \\le \\ne \\infty  symbols

Control words like \\alpha turn into symbols when you type a space. Tab
moves to the next empty box. Use the Equation tab for structures and
symbols. Press Enter or Esc to go back to the text. Click an equation to
edit it again. Switch the input format to LaTeX to type LaTeX instead."""),
    ("Styles", """\
Styles keep a document consistent. Pick one from the Styles gallery on the
Home tab, or press Ctrl+Alt+1/2/3 for Heading 1/2/3 and Ctrl+Shift+N for
Normal. Ctrl+Shift+S opens Apply Styles; Ctrl+Alt+Shift+S opens the
Styles pane where you can create, modify and update styles.

Headings feed the Navigation pane (Ctrl+F) and the table of contents."""),
    ("Table of contents", """\
Apply Heading styles to your headings, then choose References > Table of
Contents. When headings change, click Update Table (or press F9 inside
the table)."""),
    ("Find and replace", """\
Ctrl+F opens the Navigation pane: type to see every match. Ctrl+H opens
Find and Replace, Ctrl+G or F5 opens Go To (pages, bookmarks, headings,
tables, comments...). Wildcards accept regular expressions."""),
    ("Tables", """\
Insert > Table: drag over the grid to choose the size. Inside a table the
Table Design and Layout tabs appear. Tab moves to the next cell (and adds
a row at the end); Shift+Tab moves back."""),
    ("Printing and PDF", """\
Ctrl+P opens Print with a live preview. Choose a printer, copies, pages,
one- or two-sided printing and pages per sheet. To make a PDF, use
File > Export > Create PDF Document, or choose Print to PDF."""),
    ("Comments and review", """\
Ctrl+Alt+M adds a comment. Review > Track Changes (Ctrl+Shift+E) records
edits; Accept and Reject step through them. Review > Spelling & Grammar
(F7) opens the Editor pane, Shift+F7 the Thesaurus."""),
]


def _shortcut_sections():
    path = None
    for base in (SHARE, os.path.join(os.path.dirname(__file__), "..", "..", "share")):
        p = os.path.join(base, "SHORTCUTS.txt")
        if os.path.exists(p):
            path = p
            break
    if not path:
        return []
    with open(path, encoding="utf-8") as f:
        text = f.read()
    sections = []
    cur = None
    for line in text.splitlines()[4:]:
        if re.match(r"^[A-Z][A-Z &/\-]+$", line.strip()) and not line.startswith(" "):
            cur = [line.strip().title(), []]
            sections.append(cur)
        elif cur is not None and line.strip():
            cur[1].append(line.rstrip())
    return [("Keyboard shortcuts: " + t, "\n".join(lines)) for t, lines in sections]


class HelpWindow(Gtk.Window):
    _inst = None

    @classmethod
    def show_for(cls, parent, query=None):
        if cls._inst is None:
            cls._inst = HelpWindow(parent)
        cls._inst.present()
        if query:
            cls._inst.search.set_text(query)

    def __init__(self, parent):
        Gtk.Window.__init__(self, title="Help - " + APP_NAME)
        self.set_transient_for(parent)
        self.set_default_size(720, 560)
        self.connect("destroy", lambda *_: setattr(HelpWindow, "_inst", None))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_border_width(10)
        self.add(box)
        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text("Search help")
        self.search.connect("search-changed", lambda *_: self.fill())
        box.pack_start(self.search, False, False, 0)
        paned = Gtk.Paned()
        box.pack_start(paned, True, True, 0)
        self.store = Gtk.ListStore(str, str)
        self.tv = Gtk.TreeView(model=self.store)
        self.tv.set_headers_visible(False)
        self.tv.append_column(Gtk.TreeViewColumn("", Gtk.CellRendererText(), text=0))
        self.tv.get_selection().connect("changed", self.show)
        sw = Gtk.ScrolledWindow()
        sw.set_size_request(230, -1)
        sw.add(self.tv)
        paned.pack1(sw, False, False)
        self.text = Gtk.TextView()
        self.text.set_editable(False)
        self.text.set_cursor_visible(False)
        self.text.set_left_margin(14)
        self.text.set_top_margin(10)
        self.text.set_monospace(True)
        tsw = Gtk.ScrolledWindow()
        tsw.add(self.text)
        paned.pack2(tsw, True, False)
        self.topics = TOPICS + _shortcut_sections()
        self.fill()
        self.show_all()

    def fill(self):
        q = self.search.get_text().lower().strip()
        self.store.clear()
        for title, body in self.topics:
            if not q or q in title.lower() or q in body.lower():
                self.store.append([title, body])
        if len(self.store):
            self.tv.get_selection().select_path(Gtk.TreePath(0))
        else:
            self.text.get_buffer().set_text("No help topics match “%s”." % q)

    def show(self, sel):
        model, it = sel.get_selected()
        if not it:
            return
        buf = self.text.get_buffer()
        buf.set_text(model[it][0] + "\n\n" + model[it][1])
        q = self.search.get_text().strip()
        if q:
            tag = buf.get_tag_table().lookup("hit") or buf.create_tag("hit", background="#fff59d")
            start = buf.get_start_iter()
            while True:
                r = start.forward_search(q, Gtk.TextSearchFlags.CASE_INSENSITIVE, None)
                if not r:
                    break
                buf.apply_tag(tag, r[0], r[1])
                start = r[1]
