"""The Selection pane with the new engine: every picture, shape, text box and chart in the
document, front-most first; click one to select it, the eye shows or hides it, a name can be
edited, and the arrows bring it forward or send it backward."""
from gi.repository import GLib

from ..arrange import SelectionPane


class NativeSelectionPane(SelectionPane):
    def refresh(self):
        ed = self.win.engine.ed
        if ed is None:
            return
        self._muted = True
        self.store.clear()
        counts = {}
        for node, name, kind, visible in ed.objects_list():
            counts[kind] = counts.get(kind, 0) + 1
            self.store.append([name or "%s %d" % (kind, counts[kind]), visible, node])
        self._muted = False

    def _click(self, tv, ev):
        res = tv.get_path_at_pos(int(ev.x), int(ev.y))
        if not res:
            return False
        path, col = res[0], res[1]
        if col is tv.get_column(1) and ev.button == 1:
            row = self.store[path]
            row[1] = not row[1]
            self.win.engine.ed.object_set_meta(row[2], visible=row[1])
            self.win.engine.view.document_changed()
            return True
        return False

    def _selected(self, sel):
        if self._muted:
            return
        model, paths = sel.get_selected_rows()
        nodes = [model[p][2] for p in paths if model[p][1]]
        if nodes:
            ed = self.win.engine.ed
            ed.select_object_node(nodes[0])
            self.win.engine.view.objs.refresh()
            self.win.engine.view.after_move()
            GLib.timeout_add(120, lambda: (self.win.update_object_tabs(), False)[1])

    def _renamed(self, cell, path, text):
        text = text.strip()
        if text:
            self.win.engine.ed.object_set_meta(self.store[path][2], name=text)
            self.store[path][0] = text

    def show_all_objects(self, on):
        ed = self.win.engine.ed
        ed.begin_group("Show All" if on else "Hide All")
        for row in self.store:
            ed.object_set_meta(row[2], visible=on)
            row[1] = on
        ed.end_group()
        self.win.engine.view.document_changed()

    def reorder(self, delta):
        model, paths = self.tv.get_selection().get_selected_rows()
        ed = self.win.engine.ed
        for p in paths:
            if ed.select_object_node(model[p][2]):
                ed.object_z(int(delta))
        self.win.engine.view.document_changed()
        self.refresh()
