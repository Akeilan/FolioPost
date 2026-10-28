"""Review > Check Accessibility: an Accessibility pane listing errors and
warnings, with why/how to fix and a jump to each issue."""
import re

from gi.repository import GLib, Gtk, Pango

from ._lazy import docapi
from .panes import Pane

WHY = {
    "Missing alternative text": (
        "Alternative text helps people who can't see the screen understand what's "
        "important in images and other visual content.",
        "Right-click the object and choose Edit Alt Text, then describe it in one or two "
        "sentences. If it's purely decorative, mark it as decorative."),
    "Missing table header": (
        "Table headers provide context and help people navigate the table's data.",
        "Select the table, then on the Table Design tab select Header Row, and on the "
        "Layout tab select Repeat Header Rows."),
    "Hard-to-read text contrast": (
        "Text that doesn't contrast well with its background is hard to read.",
        "Choose a darker or lighter font color, or change the background."),
    "Unclear hyperlink text": (
        "Link text that says only “click here” or shows a raw address doesn't "
        "tell people where the link goes.",
        "Right-click the link, choose Edit Hyperlink, and change the text to describe "
        "the destination."),
    "Skipped heading level": (
        "Headings in order let people navigate the document's structure.",
        "Change the heading's style so levels follow each other (Heading 1, then "
        "Heading 2...)."),
    "Repeated blank characters": (
        "Several spaces, tabs or empty paragraphs in a row are announced one by one by "
        "screen readers.",
        "Use paragraph spacing, indents or tab stops instead of repeated blank "
        "characters."),
    "Object not inline": (
        "Floating objects can be hard for screen readers to reach in reading order.",
        "Select the object, choose Wrap Text > In Line with Text."),
    "Missing document title": (
        "A document title helps people know what the document is about.",
        "Go to File > Info and enter a Title in the properties."),
    "Image or object without caption": (
        "", ""),
}

ERRORS = ("Missing alternative text", "Missing table header", "Hard-to-read text contrast")


def _lum(c):
    def ch(v):
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (c >> 16) & 255, (c >> 8) & 255, c & 255
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a, b):
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def check(m):
    """[(category, label, target)] — target is a UNO object or range to select."""
    issues = []
    # objects: alt text, inline
    try:
        objs, seen = [], set()
        for coll in (m.getDrawPage(), m.getGraphicObjects(), m.getEmbeddedObjects()):
            try:
                n = coll.getCount()
            except Exception:
                n = 0
            for i in range(n):
                o = coll.getByIndex(i)
                try:
                    key = o.Name
                except Exception:
                    key = id(o)
                if key in seen:
                    continue
                seen.add(key)
                objs.append(o)
        for sh in objs:
            name = ""
            try:
                name = sh.Name or ""
            except Exception:
                pass
            try:
                if sh.CLSID.upper() == "078B7ABA-54FC-457F-8551-6147E776A997":
                    continue                 # equations
            except Exception:
                pass
            if name.startswith("Ink "):
                continue
            try:
                decorative = bool(getattr(sh, "Decorative", False))
            except Exception:
                decorative = False
            desc = ""
            for p in ("Description", "Title"):
                try:
                    v = (getattr(sh, p) or "").strip()
                except Exception:
                    v = ""
                if re.search(r"\.(png|jpe?g|gif|bmp|svg|webp|tiff?|emf|wmf)$", v, re.I):
                    v = ""                 # a file name isn't a description
                desc = desc or v
            is_frame = False
            try:
                is_frame = sh.supportsService("com.sun.star.text.TextFrame")
            except Exception:
                pass
            label = name or "Object"
            if not desc and not decorative and not is_frame:
                issues.append(("Missing alternative text", label, sh))
            try:
                at = str(sh.AnchorType.value)
                if at != "AS_CHARACTER" and not is_frame:
                    issues.append(("Object not inline", label, sh))
            except Exception:
                pass
    except Exception as e:
        print("a11y objects:", e)
    # tables: header row
    try:
        tables = m.getTextTables()
        for i in range(tables.getCount()):
            t = tables.getByIndex(i)
            hdr = False
            try:
                hdr = bool(t.RepeatHeadline)
            except Exception:
                pass
            if not hdr:
                issues.append(("Missing table header", t.getName(), t))
    except Exception as e:
        print("a11y tables:", e)
    # paragraphs: headings order, blank runs, contrast, links
    body = m.getText()
    last_level = 0
    empties = 0
    try:
        en = body.createEnumeration()
        while en.hasMoreElements():
            p = en.nextElement()
            if not p.supportsService("com.sun.star.text.Paragraph"):
                continue
            text = p.getString()
            lvl = 0
            try:
                lvl = p.OutlineLevel or 0
            except Exception:
                pass
            if lvl and text.strip():
                if last_level and lvl > last_level + 1:
                    issues.append(("Skipped heading level", text.strip()[:40], p))
                last_level = lvl
            if not text.strip():
                empties += 1
                if empties == 3:
                    issues.append(("Repeated blank characters", "Empty paragraphs", p))
            else:
                empties = 0
                if re.search(r"(?: {4,}|\t{3,})", text):
                    issues.append(("Repeated blank characters", text.strip()[:40], p))
            # runs: contrast and hyperlinks
            try:
                pen = p.createEnumeration()
                while pen.hasMoreElements():
                    r = pen.nextElement()
                    s = r.getString()
                    if not s.strip():
                        continue
                    try:
                        url = r.HyperLinkURL
                    except Exception:
                        url = ""
                    if url:
                        low = s.strip().lower()
                        if low in ("click here", "here", "link", "this link", "read more",
                                   "more") or low.startswith(("http://", "https://", "www.")):
                            issues.append(("Unclear hyperlink text", s.strip()[:40], r))
                    try:
                        col = r.CharColor
                        bg = r.CharBackColor if r.CharBackColor not in (-1, None) else (
                            p.ParaBackColor if p.ParaBackColor not in (-1, None) else 0xFFFFFF)
                        if col not in (-1, None) and contrast(col, bg) < 4.5:
                            issues.append(("Hard-to-read text contrast", s.strip()[:40], r))
                    except Exception:
                        pass
            except Exception:
                pass
    except Exception as e:
        print("a11y paragraphs:", e)
    # title
    try:
        if not (m.getDocumentProperties().Title or "").strip():
            issues.append(("Missing document title", "Document", None))
    except Exception:
        pass
    return issues


class AccessibilityPane(Pane):
    TITLE = "Accessibility"
    WIDTH = 300

    def __init__(self, win):
        Pane.__init__(self, win)
        head = Gtk.Label(xalign=0)
        head.set_markup("<b>Inspection Results</b>")
        self.pack_start(head, False, False, 0)
        self.store = Gtk.TreeStore(str, object, str)
        self.tv = Gtk.TreeView(model=self.store)
        self.tv.set_headers_visible(False)
        cell = Gtk.CellRendererText()
        cell.set_property("ellipsize", Pango.EllipsizeMode.END)
        self.tv.append_column(Gtk.TreeViewColumn("", cell, markup=0))
        self.tv.get_selection().connect("changed", self._selected)
        sw = Gtk.ScrolledWindow()
        sw.set_vexpand(True)
        sw.add(self.tv)
        self.pack_start(sw, True, True, 0)
        info = Gtk.Label(xalign=0)
        info.set_markup("<b>Additional Information</b>")
        self.pack_start(info, False, False, 0)
        self.why = Gtk.Label(xalign=0, yalign=0)
        self.why.set_line_wrap(True)
        self.why.set_max_width_chars(36)
        self.why.set_selectable(False)
        self.pack_start(self.why, False, False, 0)
        self.keep = Gtk.CheckButton(label="Keep accessibility checker running while I work")
        self.pack_start(self.keep, False, False, 0)
        self._timer = None
        win.engine.connect("state-changed", self._state)

    def _state(self, eng, key, value):
        if self.keep.get_active() and key == ".uno:ModifiedStatus" and self.get_mapped():
            if self._timer:
                GLib.source_remove(self._timer)
            self._timer = GLib.timeout_add(1500, self._auto)

    def _auto(self):
        self._timer = None
        self.refresh()
        return False

    def on_shown(self):
        self.refresh()

    def _native(self):
        return getattr(self.win.engine, "native", False)

    def refresh(self):
        if self._native():
            ed = self.win.engine.ed
            if ed is None:
                return
            issues = ed.accessibility_issues()
        else:
            m = self.model
            if m is None:
                return
            issues = check(m)
        self.store.clear()
        groups = {}
        for kind in ("Errors", "Warnings"):
            cats = [c for c, _l, _t in issues if (c in ERRORS) == (kind == "Errors")]
            if not cats:
                continue
            top = self.store.append(None, ["<b>%s</b>" % kind, None, ""])
            groups[kind] = top
            for cat in dict.fromkeys(cats):
                items = [(l, t) for c, l, t in issues if c == cat]
                ci = self.store.append(top, ["%s (%d)" % (cat, len(items)), None, cat])
                for label, target in items:
                    self.store.append(ci, [GLib.markup_escape_text(label), target, cat])
        if not issues:
            self.store.append(None, ["No accessibility issues found. People with "
                                     "disabilities\nshould not have difficulty reading "
                                     "this document.", None, ""])
        self.tv.expand_all()
        self.why.set_text("")
        self.win.status.set_a11y(not [c for c, _l, _t in issues
                                      if c != "Missing document title"])

    def _selected(self, sel):
        model, it = sel.get_selected()
        if it is None:
            return
        target, cat = model[it][1], model[it][2]
        w = WHY.get(cat)
        if w and w[0]:
            self.why.set_markup("<b>Why Fix:</b>\n%s\n\n<b>How To Fix:</b>\n%s" % (
                GLib.markup_escape_text(w[0]), GLib.markup_escape_text(w[1])))
        if target is None:
            return
        if self._native():
            ed = self.win.engine.ed
            v = self.win.engine.view
            if cat in ("Missing alternative text", "Object not inline") and ed.select_object_node(target):
                v.objs.refresh()
                v.after_move()
            elif ed.goto_node(target):
                v.after_move()
            v.scroll_to_caret()
            return
        m = self.model
        try:
            docapi.controller(m).select(target)
        except Exception:
            try:
                docapi.view_cursor(m).gotoRange(target.getStart(), False)
            except Exception:
                pass
