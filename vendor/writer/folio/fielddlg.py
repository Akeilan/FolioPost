"""The Field dialog, as in the original: categories, field names, field
properties (formats, new values), field options, and the field codes."""
from gi.repository import Gtk

from . import bridge, docapi
from .widgets import FDialog, combo, heading, list_selected, listbox

DATE_FORMATS = ["M/d/yyyy", "dddd, MMMM d, yyyy", "MMMM d, yyyy", "M/d/yy", "yyyy-MM-dd",
                "d-MMM-yy", "M.d.yyyy", "MMM. d, yy", "d MMMM yyyy", "MMMM yy", "MMM-yy",
                "M/d/yyyy h:mm am/pm", "M/d/yyyy h:mm:ss am/pm", "h:mm am/pm",
                "h:mm:ss am/pm", "HH:mm", "HH:mm:ss"]
NUM_FORMATS = [("1, 2, 3, ...", 4, "Arabic"), ("a, b, c, ...", 1, "alphabetic"),
               ("A, B, C, ...", 0, "ALPHABETIC"), ("i, ii, iii, ...", 3, "roman"),
               ("I, II, III, ...", 2, "ROMAN")]
TEXT_FORMATS = [("(none)", 0, ""), ("Uppercase", 1, "Upper"), ("Lowercase", 2, "Lower"),
                ("First capital", 3, "FirstCap"), ("Title case", 3, "Caps")]

# name: (category, kind, description)
FIELDS = [
    ("Author", "Document Information", "author", "The name of the document's author"),
    ("Comments", "Document Information", "comments", "The comments of the document"),
    ("CreateDate", "Date and Time", "created", "The date the document was created"),
    ("Date", "Date and Time", "date", "Today's date"),
    ("FileName", "Document Information", "filename", "The document's name"),
    ("Fillin", "Mail Merge", "fillin", "Prompt the user to enter text"),
    ("Keywords", "Document Information", "keywords", "The keywords of the document"),
    ("LastSavedBy", "Document Information", "lastsavedby",
     "The name of the person who last saved the document"),
    ("NumChars", "Document Information", "chars", "The number of characters in the document"),
    ("NumPages", "Document Information", "pages", "The number of pages in the document"),
    ("NumWords", "Document Information", "words", "The number of words in the document"),
    ("Page", "Numbering", "page", "The number of the current page"),
    ("PageRef", "Links and References", "pageref", "The page number of a bookmark"),
    ("PrintDate", "Date and Time", "printed", "The date the document was last printed"),
    ("Ref", "Links and References", "ref", "The text of a bookmark"),
    ("SaveDate", "Date and Time", "saved", "The date the document was last saved"),
    ("Seq", "Numbering", "seq", "A sequence number (for numbering items in a document)"),
    ("Subject", "Document Information", "subject", "The document's subject"),
    ("Time", "Date and Time", "time", "The current time"),
    ("Title", "Document Information", "title", "The document's title"),
    ("UserAddress", "User Information", "useraddress", "Your postal address"),
    ("UserInitials", "User Information", "userinitials", "Your initials"),
    ("UserName", "User Information", "username", "Your name"),
]
CATEGORIES = ["(All)", "Date and Time", "Document Information", "Links and References",
              "Mail Merge", "Numbering", "User Information"]
DATE_KINDS = ("date", "time", "created", "saved", "printed")
NUM_KINDS = ("page", "pages", "words", "chars", "seq", "pageref")
TEXT_KINDS = ("author", "title", "subject", "comments", "keywords", "lastsavedby",
              "username", "userinitials", "useraddress", "filename", "ref")
DOCINFO = {"title": "Title", "subject": "Subject", "comments": "Description",
           "keywords": "Keywords"}


def lo_date_format(fmt):
    """The original's date picture to the engine's number format code."""
    out, i = [], 0
    toks = [("dddd", "NNNN"), ("ddd", "NNN"), ("dd", "DD"), ("d", "D"), ("MMMM", "MMMM"),
            ("MMM", "MMM"), ("MM", "MM"), ("M", "M"), ("yyyy", "YYYY"), ("yy", "YY"),
            ("HH", "HH"), ("H", "H"), ("hh", "HH"), ("h", "H"), ("mm", "MM"), ("m", "M"),
            ("ss", "SS"), ("s", "S"), ("am/pm", "AM/PM"), ("AM/PM", "AM/PM")]
    while i < len(fmt):
        for a, b in toks:
            if fmt.startswith(a, i):
                out.append(b)
                i += len(a)
                break
        else:
            ch = fmt[i]
            out.append('"%s"' % ch if ch.isalpha() else ch)
            i += 1
    return "".join(out)


def field_code(name, kind, opts):
    code = name.upper()
    if kind in DATE_KINDS and opts.get("date"):
        code += ' \\@ "%s"' % opts["date"]
    if kind in NUM_KINDS and opts.get("num"):
        code += " \\* %s" % opts["num"]
    if kind in TEXT_KINDS and opts.get("case"):
        code += " \\* %s" % opts["case"]
    if kind == "filename" and opts.get("path"):
        code += " \\p"
    if kind in ("ref", "pageref") and opts.get("bookmark"):
        code = "%s %s \\h" % (name.upper(), opts["bookmark"])
    if kind == "seq":
        code = "SEQ %s" % (opts.get("seq") or "Figure")
    if kind == "fillin" and opts.get("prompt"):
        code = 'FILLIN "%s"' % opts["prompt"]
    if opts.get("new"):
        code += ' "%s"' % opts["new"]
    if opts.get("merge", True):
        code += " \\* MERGEFORMAT"
    return code


def parse_code(code):
    """'DATE \\@ "M/d/yyyy" \\* MERGEFORMAT' -> (field entry, options)."""
    import re
    import shlex
    try:
        parts = shlex.split(code.replace("\\", "\\\\"))
    except ValueError:
        parts = code.split()
    if not parts:
        return None, {}
    name = parts[0].upper()
    f = next((x for x in FIELDS if x[0].upper() == name), None)
    if f is None:
        return None, {}
    o = {"merge": "MERGEFORMAT" in code.upper()}
    mt = re.search(r'\\@\s*"([^"]*)"', code)
    if mt:
        o["date"] = mt.group(1)
    for label, num, word in NUM_FORMATS:
        if re.search(r"\\\*\s*%s\b" % word, code):
            o["num"], o["numtype"] = word, num
    for label, cm, word in TEXT_FORMATS:
        if word and re.search(r"\\\*\s*%s\b" % word, code, re.I):
            o["case"], o["casemap"] = word, cm
    if "\\p" in code:
        o["path"] = True
    if f[2] in ("ref", "pageref", "seq") and len(parts) > 1 and not parts[1].startswith("\\"):
        o["bookmark" if f[2] != "seq" else "seq"] = parts[1]
    return f, o


def insert(m, kind, opts):
    vc = docapi.view_cursor(m)
    text = vc.getText()
    f = None
    if kind in ("date", "time"):
        f = m.createInstance("com.sun.star.text.textfield.DateTime")
        f.IsDate = kind == "date" and not any(c in (opts.get("date") or "") for c in "hHm")
        f.IsFixed = False
    elif kind in ("created", "saved", "printed"):
        svc = {"created": "CreateDateTime", "saved": "ChangeDateTime",
               "printed": "PrintDateTime"}[kind]
        f = m.createInstance("com.sun.star.text.textfield.docinfo." + svc)
        try:
            f.IsDate = True
        except Exception:
            pass
    elif kind in ("page", "pages", "words", "chars"):
        svc = {"page": "PageNumber", "pages": "PageCount", "words": "WordCount",
               "chars": "CharacterCount"}[kind]
        f = m.createInstance("com.sun.star.text.textfield." + svc)
        f.NumberingType = opts.get("numtype", 4)
        if kind == "page":
            f.SubType = bridge.enum("com.sun.star.text.PageNumberType", "CURRENT")
    elif kind == "author":
        if opts.get("new"):
            m.getDocumentProperties().Author = opts["new"]
        f = m.createInstance("com.sun.star.text.textfield.docinfo.CreateAuthor")
    elif kind == "lastsavedby":
        f = m.createInstance("com.sun.star.text.textfield.docinfo.ChangeAuthor")
    elif kind in DOCINFO:
        if opts.get("new"):
            setattr(m.getDocumentProperties(), DOCINFO[kind], opts["new"])
        f = m.createInstance("com.sun.star.text.textfield.docinfo." + DOCINFO[kind])
    elif kind == "filename":
        f = m.createInstance("com.sun.star.text.textfield.FileName")
        f.FileFormat = 2 if opts.get("path") else 1      # FULL / NAME_AND_EXT
    elif kind in ("username", "userinitials", "useraddress"):
        if kind == "username":
            f = m.createInstance("com.sun.star.text.textfield.Author")
            f.FullName = True
            if opts.get("new"):
                f.IsFixed = True
                f.Content = opts["new"]
        else:
            f = m.createInstance("com.sun.star.text.textfield.ExtendedUser")
            f.UserDataType = 3 if kind == "userinitials" else 4
            if opts.get("new"):
                f.IsFixed = True
                f.Content = opts["new"]
    elif kind in ("ref", "pageref"):
        f = m.createInstance("com.sun.star.text.textfield.GetReference")
        f.ReferenceFieldSource = 2          # bookmark
        f.SourceName = opts.get("bookmark") or ""
        f.ReferenceFieldPart = 0 if kind == "pageref" else 2   # PAGE / TEXT
    elif kind == "fillin":
        f = m.createInstance("com.sun.star.text.textfield.Input")
        f.Hint = opts.get("prompt") or ""
        f.Content = opts.get("new") or ""
    elif kind == "seq":
        name = opts.get("seq") or "Figure"
        f = m.createInstance("com.sun.star.text.textfield.SetExpression")
        f.attachTextFieldMaster(docapi._seq_master(m, name))
        f.Content = name + "+1"
        f.NumberingType = opts.get("numtype", 4)
    if f is None:
        return None
    if kind in DATE_KINDS and opts.get("date"):
        try:
            f.NumberFormat = docapi._number_format(m, lo_date_format(opts["date"]))
        except Exception as e:
            print("field format:", e)
    text.insertTextContent(vc, f, not vc.isCollapsed())
    if opts.get("casemap"):
        try:
            a = f.getAnchor()
            a.CharCaseMap = opts["casemap"]
        except Exception:
            pass
    try:
        docapi.update_indexes(m)
    except Exception:
        pass
    return f


def dialog(win):
    native = getattr(win, "native", False)
    m = win.engine.model
    if m is None and not native:
        return
    d = FDialog(win, "Field")
    outer = Gtk.Box(spacing=14)
    # ---- left: categories + names
    left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    left.pack_start(heading("Please choose a field"), False, False, 0)
    cat = combo(CATEGORIES, 0)
    left.pack_start(Gtk.Label(label="_Categories:", xalign=0, use_underline=True),
                    False, False, 0)
    left.pack_start(cat, False, False, 0)
    left.pack_start(Gtk.Label(label="_Field names:", xalign=0, use_underline=True),
                    False, False, 0)
    sw, tv, store = listbox([f[0] for f in FIELDS], height=230, width=180,
                            on_activate=lambda *_: d.response(Gtk.ResponseType.OK))
    left.pack_start(sw, True, True, 0)
    outer.pack_start(left, False, False, 0)
    # ---- middle: properties
    mid = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    mid.pack_start(heading("Field properties"), False, False, 0)
    props_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    mid.pack_start(props_box, True, True, 0)
    outer.pack_start(mid, True, True, 0)
    # ---- right: options
    right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    right.pack_start(heading("Field options"), False, False, 0)
    opts_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    right.pack_start(opts_box, True, True, 0)
    keep = Gtk.CheckButton.new_with_mnemonic("Preser_ve formatting during updates")
    keep.set_active(True)
    right.pack_end(keep, False, False, 0)
    outer.pack_start(right, True, True, 0)
    d.add(outer, expand=True)
    desc = Gtk.Label(xalign=0)
    desc.set_line_wrap(True)
    d.add(desc)
    # ---- field codes
    codes_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    codes_box.set_no_show_all(True)
    code = Gtk.Entry()
    code.set_width_chars(60)
    codes_box.pack_start(Gtk.Label(label="Advanced field properties", xalign=0),
                         False, False, 0)
    codes_box.pack_start(Gtk.Label(label="Field codes:", xalign=0), False, False, 0)
    codes_box.pack_start(code, False, False, 0)
    d.add(codes_box)
    codes_btn = d.add_button("Field _Codes", 2)
    codes_btn.set_use_underline(True)
    d.get_action_area().reorder_child(codes_btn, 0)
    state = {"w": {}}

    def current():
        name = list_selected(tv)
        return next((f for f in FIELDS if f[0] == name), None)

    def opts():
        w = state["w"]
        o = {"merge": keep.get_active()}
        if "date" in w:
            o["date"] = w["date"].get_child().get_text()
        if "num" in w:
            i = max(0, w["num"].get_active())
            o["num"], o["numtype"] = NUM_FORMATS[i][2], NUM_FORMATS[i][1]
        if "case" in w:
            i = max(0, w["case"].get_active())
            o["case"], o["casemap"] = TEXT_FORMATS[i][2], TEXT_FORMATS[i][1]
        if "new" in w and w["new"].get_text().strip():
            o["new"] = w["new"].get_text().strip()
        if "path" in w:
            o["path"] = w["path"].get_active()
        if "bookmark" in w:
            o["bookmark"] = list_selected(w["bookmark"]) or ""
        if "seq" in w:
            o["seq"] = w["seq"].get_child().get_text().strip()
        if "prompt" in w:
            o["prompt"] = w["prompt"].get_text()
        return o

    def update_code(*_):
        f = current()
        if f:
            code.set_text(field_code(f[0], f[2], opts()))

    def build(*_):
        for b in (props_box, opts_box):
            for c in b.get_children():
                b.remove(c)
        state["w"] = w = {}
        f = current()
        if f is None:
            return
        name, _cat, kind, text = f
        desc.set_text("Description:\n" + text)
        if kind in DATE_KINDS:
            props_box.pack_start(Gtk.Label(label="Date formats:", xalign=0), False, False, 0)
            e = Gtk.ComboBoxText.new_with_entry()
            for x in DATE_FORMATS:
                e.append_text(x)
            e.get_child().set_text("h:mm am/pm" if kind == "time" else "M/d/yyyy")
            w["date"] = e
            props_box.pack_start(e, False, False, 0)
            _sw, ltv, _st = listbox(DATE_FORMATS, height=170, width=200)
            ltv.get_selection().connect("changed", lambda *_: list_selected(ltv) and
                                        e.get_child().set_text(list_selected(ltv)))
            props_box.pack_start(_sw, True, True, 0)
            e.get_child().connect("changed", update_code)
        if kind in NUM_KINDS:
            props_box.pack_start(Gtk.Label(label="Format:", xalign=0), False, False, 0)
            c = combo([n for n, _v, _c in NUM_FORMATS], 0)
            w["num"] = c
            props_box.pack_start(c, False, False, 0)
            c.connect("changed", update_code)
        if kind in TEXT_KINDS and kind not in ("ref",):
            props_box.pack_start(Gtk.Label(label="Format:", xalign=0), False, False, 0)
            c = combo([n for n, _v, _c in TEXT_FORMATS], 0)
            w["case"] = c
            props_box.pack_start(c, False, False, 0)
            c.connect("changed", update_code)
        if kind in ("author", "title", "subject", "comments", "keywords", "username",
                    "userinitials", "useraddress", "fillin"):
            label = {"author": "New name:", "title": "New title:", "subject": "New subject:",
                     "comments": "New comments:", "keywords": "New keywords:",
                     "username": "New name:", "userinitials": "New initials:",
                     "useraddress": "New address:", "fillin": "Default response:"}[kind]
            props_box.pack_start(Gtk.Label(label=label, xalign=0), False, False, 0)
            e = Gtk.Entry()
            w["new"] = e
            props_box.pack_start(e, False, False, 0)
            e.connect("changed", update_code)
        if kind == "fillin":
            props_box.pack_start(Gtk.Label(label="Prompt:", xalign=0), False, False, 0)
            e = Gtk.Entry()
            w["prompt"] = e
            props_box.pack_start(e, False, False, 0)
            e.connect("changed", update_code)
        if kind in ("ref", "pageref"):
            props_box.pack_start(Gtk.Label(label="Bookmark name:", xalign=0), False, False, 0)
            marks = win.engine.ed.bookmark_names() if native else docapi.bookmarks(m)
            _sw, btv, _st = listbox(marks, height=170, width=200)
            w["bookmark"] = btv
            props_box.pack_start(_sw, True, True, 0)
            btv.get_selection().connect("changed", update_code)
        if kind == "seq":
            props_box.pack_start(Gtk.Label(label="Identifier:", xalign=0), False, False, 0)
            e = Gtk.ComboBoxText.new_with_entry()
            for x in ("Figure", "Table", "Equation"):
                e.append_text(x)
            e.get_child().set_text("Figure")
            w["seq"] = e
            props_box.pack_start(e, False, False, 0)
            e.get_child().connect("changed", update_code)
        if kind == "filename":
            p = Gtk.CheckButton.new_with_mnemonic("_Add path to filename")
            w["path"] = p
            opts_box.pack_start(p, False, False, 0)
            p.connect("toggled", update_code)
        if not props_box.get_children():
            props_box.pack_start(Gtk.Label(label="This field has no properties.", xalign=0),
                                 False, False, 0)
        if not opts_box.get_children():
            opts_box.pack_start(Gtk.Label(label="No field options are available for this "
                                                "field.", xalign=0, wrap=True,
                                          max_width_chars=26), False, False, 0)
        props_box.show_all()
        opts_box.show_all()
        update_code()

    def filter_names(*_):
        c = cat.get_active_text()
        store.clear()
        for f in FIELDS:
            if c == "(All)" or f[1] == c:
                store.append([f[0]])
        tv.get_selection().select_path(Gtk.TreePath(0))
    tv.get_selection().connect("changed", build)
    cat.connect("changed", filter_names)
    keep.connect("toggled", update_code)
    filter_names()
    d.show_all()
    while True:
        r = d.run()
        if r == 2:
            show = not codes_box.get_visible()
            codes_box.set_visible(show)
            if show:
                codes_box.show_all()
            outer.set_visible(not show)
            codes_btn.set_label("Hide _Codes" if show else "Field _Codes")
            continue
        break
    if r == Gtk.ResponseType.OK:
        f, o = current(), None
        if codes_box.get_visible() and code.get_text().strip():
            pf, po = parse_code(code.get_text().strip())
            if pf is not None:
                f, o = pf, po
        if f is not None and native:
            if codes_box.get_visible() and code.get_text().strip():
                instr = code.get_text().strip()
            else:
                instr = field_code(f[0], f[2], opts())
            win.engine.ed.insert_field_now(instr)
            win.engine.view.after_edit()
        elif f is not None:
            um = m.getUndoManager()
            um.enterUndoContext("Insert Field")
            try:
                insert(m, f[2], o if o is not None else opts())
            except Exception as e:
                win.dialogs.message("Error! %s" % e)
            finally:
                um.leaveUndoContext()
    d.destroy()
    win.focus_document()
