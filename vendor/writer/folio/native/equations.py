"""Equations with the new engine: the in-place equation editor (mathedit)
works on the engine's OMML. While an equation is edited the editor draws it
over the page; every change is written back as OMML, so the page reflows as
you type, and leaving the equation leaves the engine's own rendering."""
from ..eqn import model as M, omml
from ..mathedit import InlineEditor

PLACEHOLDER = '<m:oMath xmlns:m="%s"/>' % omml.M_NS


class NativeEq:
    """An equation of the document (its m:oMath element)."""

    def __init__(self, eng, mid):
        self.eng = eng
        self.id = mid

    def __eq__(self, other):
        return isinstance(other, NativeEq) and other.id == self.id

    def __hash__(self):
        return hash(self.id)

    def info(self):
        return self.eng.ed.math_info(self.id) if self.eng.ed else None


def model_of(xml):
    try:
        return M.slot(omml.from_omml(xml))
    except Exception as e:
        print("equation:", e)
        from ..eqn.unicodemath import Seq
        return Seq([])


def unnumber(root):
    """A numbered equation (an equation array of one row holding '#'):
    the row itself, number included, as the editor shows it."""
    from ..eqn.unicodemath import Atom, EqArray, Seq
    if len(root.items) == 1 and isinstance(root.items[0], EqArray):
        rows = root.items[0].rows
        if len(rows) == 1 and len(rows[0]) == 1:
            cell = rows[0][0]
            if any(isinstance(i, Atom) and i.value == "#" for i in cell.items):
                return Seq(list(cell.items))
    return root


LINEAR_CHARS = set("^_/√∛∜▒■┬┴@&")


def linear_text(xml):
    """The linear text of an equation kept in linear form (nothing but runs
    holding linear syntax), else None."""
    import xml.etree.ElementTree as ET
    try:
        el = ET.fromstring(xml)
    except ET.ParseError:
        return None
    m = "{%s}" % omml.M_NS
    kids = [k for k in el if k.tag != m + "ctrlPr"]
    if not kids or any(k.tag != m + "r" for k in kids):
        return None
    text = "".join(t.text or "" for k in kids for t in k.iter(m + "t"))
    return text if any(c in LINEAR_CHARS for c in text) else None


def linear_xml(text):
    sp = ' xml:space="preserve"' if text != text.strip() else ""
    return '<m:oMath xmlns:m="%s" xmlns:w="%s"><m:r>%s<m:t%s>%s</m:t></m:r></m:oMath>' % (
        omml.M_NS, omml.W_NS, omml.MATH_RPR, sp, omml._xesc(text))


def xml_of(root):
    if not root.items:
        return PLACEHOLDER
    return omml.to_omml(M.export(root))


class NativeInlineEditor(InlineEditor):
    """InlineEditor over the new engine's equations."""

    @property
    def eng(self):
        return self.win.engine

    def start(self, obj, click=None, at=None):
        from ..eqn import render as R
        from gi.repository import GLib
        if self.obj is not None:
            if obj == self.obj:
                if click:
                    self.click(*click)
                return
            self.stop()
        ed = self.eng.ed
        if ed is None:
            return
        self.obj = obj
        self.undo_stack, self.redo_stack = [], []
        self.picked = None
        self.anchor = None
        R.set_family(self.opts().get("font") or "STIX Two Math")
        xml = ed.math_xml(obj.id)
        lin = linear_text(xml)
        self.mode = "linear" if lin is not None else "professional"
        self.lin = lin or ""
        self.lin_pos = len(self.lin)
        self.lin_anchor = None
        self.root = unnumber(model_of(xml)) if lin is None else Seq_empty()
        self.caret = (self.root, len(self.root.items))
        empty = M.first_empty(self.root)
        if at == "start":
            self.caret = (self.root, 0)
        elif empty is not None and at is None:
            self.caret = (empty, 0)
        self._last_markup = xml_of(self.root)
        # the engine's caret goes after the equation
        ed.caret_by_math(obj.id, True)
        self.frame = None
        self._pending_click = click
        GLib.idle_add(self._locate)
        self._start_blink()
        rb = self.win.ribbon
        rb.show_contextual("Equation", True)
        tab = rb.tab_by_name("Equation")
        if tab is not None:
            rb.select(tab)
        self.bar.sync_input_buttons()
        self.win.focus_document()

    def stop(self, move_cursor=True):
        if self.obj is None:
            return
        obj = self.obj
        if self.mode == "professional" and self.opts().get("autobuild", True):
            try:
                self.build_up()
            except Exception as e:
                print("build-up:", e)
        self._push_now(final=True)
        empty = not self.root.items if self.mode == "professional" else not self.lin.strip()
        self.obj = None
        self.frame = None
        if self._blink:
            from gi.repository import GLib
            GLib.source_remove(self._blink)
            self._blink = 0
        self.win.ribbon.show_contextual("Equation", False)
        ed = self.eng.ed
        if ed is not None:
            if empty:
                ed.delete_math(obj.id)
            elif move_cursor:
                ed.caret_by_math(obj.id, True)
            self.eng.view.document_changed()
        self.eng.view.queue_draw()

    def _locate(self):
        if self.obj is None:
            return False
        inf = self.obj.info()
        if inf is None:
            return False
        eng = self.eng
        top = eng.page_top_tw(inf["page"])
        x = inf["x"] * 20
        y = top + (inf["base"] - inf["asc"]) * 20
        self.obj_rect = (x, y, inf["w"] * 20, (inf["asc"] + inf["desc"]) * 20)
        self._base_pt = inf["size"]
        self._disp = inf["display"]
        if self._pending_click is not None:
            cx, cy = self._pending_click
            self._pending_click = None
            self._layout()
            self.click(cx, cy)
        self._layout()
        eng.view.queue_draw()
        return False

    def cursor_moved(self):
        pass

    def _base_px(self):
        z = self.eng.view.get_zoom() or 1.0
        return getattr(self, "_base_pt", 11.0) * 96.0 / 72.0 * z

    def _display(self):
        return bool(getattr(self, "_disp", False))

    def _alone(self):
        return self._display()

    def markup(self):
        if self.mode == "linear":
            # kept in linear form, as the original keeps it
            return linear_xml(self.lin) if self.lin.strip() else PLACEHOLDER
        root, num = self._split_number(self.root)
        if num is not None and num.items:
            from ..eqn.unicodemath import Atom, EqArray, Seq
            whole = M.export(Seq(root.items + [Atom("op", "#")] + num.items))
            return omml.to_omml(EqArray([[whole]]))
        return xml_of(root)

    def _push_now(self, final=False):
        self._push = 0
        if self.obj is None:
            return False
        mk = self.markup()
        if mk != self._last_markup and self.eng.ed is not None:
            self.eng.ed.set_math(self.obj.id, mk)
            self._last_markup = mk
            self.eng.view.document_changed()
            # the page moved under us: follow it
            self._locate()
        return False

    def _ensure_fonts(self):
        pass

    def _number_save(self, obj):
        pass

    def _number_load(self):
        pass


def Seq_empty():
    from ..eqn.unicodemath import Seq
    return Seq([])


def convert_all(bar, how):
    """Convert > All - Professional / Linear."""
    eng = bar.win.engine
    ed = eng.ed
    if ed is None:
        return 0
    if bar.ed.active:
        bar.finish()
    latex = bar.input_format == "latex"
    n = 0
    ed.begin_group("Convert Equations")
    try:
        for mid in ed.all_math():
            xml = ed.math_xml(mid)
            lin = linear_text(xml)
            try:
                if how == "linear" and lin is None:
                    tree = unnumber(model_of(xml))
                    text = M.to_latex(tree) if latex else M.to_linear(tree)
                    ed.set_math(mid, linear_xml(text))
                    n += 1
                elif how == "professional" and lin is not None:
                    from ..eqn import unicodemath
                    tree = M.from_latex(lin) if latex else \
                        M.from_linear(unicodemath.expand_control_words(lin, final=True))
                    ed.set_math(mid, xml_of(tree))
                    n += 1
            except Exception as e:
                print("convert:", e)
    finally:
        ed.end_group()
    eng.view.document_changed()
    return n


# ----------------------------------------------------------------- commands
def new_equation(bar, linear=None):
    """Insert > Equation (Alt+=): a new equation at the caret, edited."""
    eng = bar.win.engine
    ed = eng.ed
    if ed is None:
        return
    if bar.ed.active:
        bar.finish()
    if ed.has_selection() and linear is None:
        linear = ed.selected_text()
    xml = PLACEHOLDER
    if linear:
        try:
            xml = xml_of(M.from_linear(linear))
        except Exception:
            xml = PLACEHOLDER
    display = ed.caret_para_empty()
    mid = ed.insert_math(xml, display)
    eng.view.document_changed()
    if mid is None:
        return
    bar.ed.start(NativeEq(eng, mid))


def click(win, pg, x, y):
    """A click on an equation edits it (True when it was one)."""
    eng = win.engine
    mid = eng.ed.math_at(pg, x, y)
    if mid is None:
        return False
    win.eqbar.ed.start(NativeEq(eng, mid))
    return True


def arrow_into(win, forward):
    eng = win.engine
    mid = eng.ed.math_beside_caret(forward)
    if mid is None:
        return False
    win.eqbar.ed.start(NativeEq(eng, mid), at="start" if forward else "end")
    return True


def set_display(bar, display):
    obj = bar.ed.obj
    if obj is None:
        return
    eng = bar.win.engine
    bar.ed._push_now()
    eng.ed.set_math_display(obj.id, display)
    eng.view.document_changed()
    bar.ed._locate()
