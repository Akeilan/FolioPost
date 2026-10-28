"""The calls the Insert Hyperlink dialog makes, answered by the new engine."""


class _Cursor:
    def __init__(self, ed):
        self.ed = ed
        self.HyperLinkTarget = ""

    def getString(self):
        return self.ed.selected_text()

    def isCollapsed(self):
        return not self.ed.has_selection()


class LinkApi:
    def __init__(self, win):
        self.win = win

    @property
    def ed(self):
        return self.win.engine.ed

    def view_cursor(self, m):
        return _Cursor(self.ed)

    def selected_link(self, m):
        return self.ed.link_at_caret()

    def headings(self, m):
        return [(lvl, t, None) for lvl, t in self.ed.headings()]

    def bookmarks(self, m):
        return self.ed.bookmark_names()

    def set_link(self, m, url, shown, tip="", target=""):
        ed = self.ed
        if ed.link_at_caret() and not ed.has_selection():
            ed.remove_link()
        ed.insert_hyperlink(url, shown)
        self.win.engine.view.after_edit()

    def remove_link(self, m):
        self.ed.remove_link()
        self.win.engine.view.after_edit()

    def add_bookmark(self, m, name):
        self.ed.add_bookmark(name)
        self.win.engine.view.after_edit()

    def delete_bookmark(self, m, name):
        self.ed.delete_bookmark(name)
        self.win.engine.view.after_edit()

    def goto_bookmark(self, m, name):
        self.ed.goto_bookmark(name)
        self.win.engine.view.after_move()

    def references(self, m):
        out = {}
        for kind, shown, target in self.ed.references():
            out.setdefault(kind, []).append((shown, target))
        return out

    def insert_cross_reference(self, m, kind, target, part="text", hyperlink=True, above=False, sep=None):
        self.ed.insert_cross_reference(kind, target, part, hyperlink)
        if sep:
            # Separate numbers with: the REF field's \d switch
            fields = self.ed.body_fields()
            p, off = self.ed.caret_pos()
            for i in range(len(fields) - 1, -1, -1):
                instr, _r, fp, _a, b = fields[i]
                if fp == p and b <= off and instr.strip().upper().startswith("REF") and "\\d" not in instr:
                    self.ed.set_field_instr(i, instr.rstrip() + ' \\d "%s" ' % sep.replace('"', ''))
                    break
        if above and part != "above":
            self.ed.type_text(" ")
            self.ed.insert_cross_reference(kind, target, "above", hyperlink)
        self.win.engine.view.after_edit()
