"""The View tab with the new engine: Draft and Web Layout (the engine lays the
text out without pages), Outline view, Read Mode, the Immersive Reader and Read
Aloud, Split and New Window (more views onto the same document)."""
import html
import re

from gi.repository import GLib

from ..outlineview import BODY, OutlineView

WORD_RE = re.compile(r"[^\W_]+(?:['’][^\W_]+)*", re.UNICODE)


def _ed(win):
    return win.engine.ed


# ================================================================ layouts
def set_layout(win, mode):
    """0 Print Layout, 1 Draft, 2 Web Layout."""
    v = win.engine.view
    ed = _ed(win)
    if ed is None:
        return
    v.continuous = mode != 0
    width = max(144.0, v.get_allocated_width() / v.ppp) if mode == 2 else 0.0
    ed.set_view_mode(mode, width)
    v.objs.refresh()
    v.document_changed()
    GLib.idle_add(lambda: (v.scroll_to_caret(), False)[1])
    win.draft = mode == 1
    try:
        win.rulers.v.set_visible(mode == 0 and win.app.settings.get("ruler", True))
    except Exception:
        pass
    try:
        win.status.set_view({0: "print", 1: None, 2: "web"}[mode])
    except Exception:
        pass


# ================================================================ more views
class _Sync:
    """Keeps a second view drawn as the document changes in either."""

    def __init__(self, win, v2):
        self.win, self.v2, self.busy = win, v2, False
        main = win.engine.view
        self.ids = [(main, main.connect("changed", self._from_main)),
                    (v2, v2.connect("changed", self._from_second)),
                    (main, main.connect("selection-changed", lambda *_: v2.queue_draw())),
                    (v2, v2.connect("selection-changed", lambda *_: main.queue_draw()))]

    def _from_main(self, *_):
        if self.busy:
            return
        self.busy = True
        try:
            self.v2.document_changed()
        finally:
            self.busy = False

    def _from_second(self, *_):
        if self.busy:
            return
        self.busy = True
        try:
            self.win.engine.view.document_changed()
        finally:
            self.busy = False

    def stop(self):
        for w, i in self.ids:
            try:
                w.disconnect(i)
            except Exception:
                pass
        self.ids = []


def second_view(win):
    """Another view onto the window's document (Split, New Window)."""
    from .view import NativeView
    main = win.engine.view
    v2 = NativeView()
    v2.set_editor(_ed(win))
    v2.set_zoom(main.get_zoom() or 1.0)
    v2.continuous = main.continuous
    v2.speller = main.speller
    v2.set_edit(main.get_edit())
    v2._sync = _Sync(win, v2)
    v2.connect("destroy", lambda *_: v2._sync.stop())
    return v2


# ================================================================ outline
class _Para:
    """What the outline shows of one paragraph."""

    def __init__(self, row):
        self.node, self.text, self.level, self.size, self.bold, self.italic, self.color, self.family = row


class NativeOutlineView(OutlineView):
    def load(self, keep_selection=True):
        ed = _ed(self.win)
        if ed is None:
            return
        sel = self._selected_para() if keep_selection else None
        sel_node = sel.node if sel is not None else ed.caret_pos()[0]
        self.store.clear()
        stack = [(0, None)]
        target = None
        for row in ed.outline_paras():
            p = _Para(row)
            level = p.level
            if level > self.max_level and level != BODY:
                continue
            if level == BODY and self.max_level < 9:
                continue
            while stack and stack[-1][0] >= level:
                stack.pop()
            parent = stack[-1][1] if stack else None
            it = self.store.append(parent, [self._markup(p, level), "", level, p])
            if level != BODY:
                stack.append((level, it))
            if p.node == sel_node and target is None:
                target = it
        self._symbols(None)
        self.tv.expand_all()
        from gi.repository import Gtk
        for path in sorted(self.collapsed, key=len, reverse=True):
            try:
                self.tv.collapse_row(Gtk.TreePath.new_from_string(path))
            except Exception:
                pass
        self._symbols(None)
        if target is not None:
            self.tv.get_selection().select_iter(target)

    def _markup(self, p, level):
        text = p.text
        if self.first_line_only and level == BODY and len(text) > 90:
            text = text[:90].rstrip() + "…"
        esc = html.escape(text) or "<i> </i>"
        if not self.show_formatting:
            return esc
        attrs = ["size='%gpt'" % min(20, max(9, p.size))]
        if p.bold:
            attrs.append("weight='bold'")
        if p.italic:
            attrs.append("style='italic'")
        if p.color >= 0:
            attrs.append("foreground='#%06x'" % (p.color & 0xFFFFFF))
        if p.family:
            attrs.append("font_family='%s'" % html.escape(p.family))
        return "<span %s>%s</span>" % (" ".join(attrs), esc)

    def _goto(self, p):
        ed = _ed(self.win)
        if ed.goto_node(p.node):
            self.win.engine.view.after_move()

    def _editing_started(self, cell, editable, path):
        from gi.repository import Gtk
        p = self.store[path][3]
        if isinstance(editable, Gtk.Entry):
            editable.set_text(p.text)

    def _edited(self, cell, path, text):
        p = self.store[path][3]
        if text == p.text:
            return
        _ed(self.win).set_para_text(p.node, text)
        self.win.engine.view.after_edit()
        p.text = text
        self.store[path][0] = self._markup(p, self.store[path][2])

    def set_level(self, level):
        p = self._selected_para()
        if p is None:
            return
        ed = _ed(self.win)
        ed.goto_node(p.node)
        self.win.actions.apply_style("Normal" if level == BODY else "Heading %d" % level)
        self.win.engine.view.after_edit()
        self.load()

    def move(self, delta):
        it = self._selected()
        if it is None:
            return
        ed = _ed(self.win)
        p = self.store[it][3]
        level = self.store[it][2]
        nodes = ed.section_paras(p.node) if level != BODY else [p.node]
        sib = self.store.iter_previous(it) if delta < 0 else self.store.iter_next(it)
        if level != BODY:
            while sib is not None and self.store[sib][2] == BODY:
                sib = self.store.iter_previous(sib) if delta < 0 else self.store.iter_next(sib)
        if sib is None:
            # body text: past the paragraph before / after it in the document
            paras = [r[0] for r in ed.outline_paras()]
            i = paras.index(p.node) if p.node in paras else -1
            j = i + (-1 if delta < 0 else len(nodes))
            if i < 0 or not (0 <= j < len(paras)):
                return
            ed.move_paras(nodes, paras[j], delta > 0)
        else:
            other = self.store[sib][3].node
            target = other if delta < 0 else ed.section_paras(other)[-1]
            ed.move_paras(nodes, target, delta > 0)
        self.win.engine.view.after_edit()
        self.load()

    def _dropped(self, tv, ctx, x, y, data, info, time):
        from gi.repository import Gtk
        model, it = tv.get_selection().get_selected()
        res = tv.get_dest_row_at_pos(x, y)
        if it is None or res is None:
            Gtk.drag_finish(ctx, False, False, time)
            return
        path, pos = res
        ed = _ed(self.win)
        src = self.store[it][3]
        dst = self.store[path][3]
        after = pos in (Gtk.TreeViewDropPosition.AFTER, Gtk.TreeViewDropPosition.INTO_OR_AFTER)
        nodes = ed.section_paras(src.node) if self.store[it][2] != BODY else [src.node]
        target = ed.section_paras(dst.node)[-1] if after and self.store[path][2] != BODY else dst.node
        ed.move_paras(nodes, target, after)
        Gtk.drag_finish(ctx, True, False, time)
        ctx.drag_status(0, time)
        self.win.engine.view.after_edit()
        GLib.idle_add(lambda: (self.load(), False)[1])
        tv.stop_emission_by_name("drag-data-received")


# ================================================================ read aloud, immersive
class DocSource:
    """Paragraphs of the body from the caret on (Read Aloud)."""

    def __init__(self, win):
        from . import docops
        self.win = win
        ed = _ed(win)
        cp, co = ed.caret_pos()
        paras = [(p, t) for p, t, _l in docops.paragraphs(ed)]
        idx = next((i for i, (p, _t) in enumerate(paras) if p == cp), 0)
        self.paras = [(p, t) for p, t in paras[idx:] if t.replace("￼", "").strip()]
        self.first_offset = co if self.paras and self.paras[0][0] == cp else 0

    def __len__(self):
        return len(self.paras)

    def words(self, i):
        text = self.paras[i][1]
        start = self.first_offset if i == 0 else 0
        return [(m.start(), m.end() - m.start(), m.group()) for m in WORD_RE.finditer(text) if m.start() >= start]

    def highlight(self, i, start, length):
        p = self.paras[i][0]
        ed = _ed(self.win)
        ed.select_nodes(p, start, p, start + length)
        v = self.win.engine.view
        v.after_move()
        v.scroll_to_caret()

    def clear(self):
        pass


def immersive_paras(win, syllables=False):
    """(text, heading level or 0) of each body paragraph with text."""
    ed = _ed(win)
    out = []
    lang = (win.app.settings.get("proofing_language") or "en_US").replace("_", "-")
    for row in ed.outline_paras():
        text = row[1]
        if not text.strip():
            continue
        if syllables:
            text = syllabify(ed, text, lang)
        out.append((text, 0 if row[2] == BODY else row[2]))
    return out


def syllabify(ed, text, lang="en-US"):
    def one(m):
        w = m.group()
        if len(w) < 4:
            return w
        pts = ed.hyphen_points(w, lang)
        if not pts:
            return w
        out, last = [], 0
        for p in pts:
            out.append(w[last:p])
            last = p
        out.append(w[last:])
        return "·".join(x for x in out if x)
    return re.sub(r"[A-Za-z]{4,}", one, text)


# ================================================================ read mode
def render(win, x, y, w, h, width_px):
    """A page (as page_rects gives it, twips) drawn width_px wide."""
    import cairo
    ed = _ed(win)
    rects = win.engine.page_rects()
    i = next((k for k, r in enumerate(rects) if r[1] == y), 0)
    scale = max(0.05, width_px / (w / 20.0))
    W, H, stride, data = ed.render_page(i, scale, False, False)
    return cairo.ImageSurface.create_for_data(bytearray(data), cairo.FORMAT_ARGB32, W, H, stride)
