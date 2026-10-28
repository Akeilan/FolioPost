"""Mail merge Rules (Ask, Fill-in, If...Then...Else, Merge Record #, Merge
Sequence #, Next Record, Next Record If, Set Bookmark, Skip Record If), Match
Fields, and Auto Check for Errors."""
import json

from gi.repository import Gtk

from ._lazy import docapi
from .widgets import FDialog, combo, grid

PREFIX = "com.sun.star.text.fieldmaster.User."
OPS = [("Equal to", "eq"), ("Not equal to", "ne"), ("Less than", "lt"),
       ("Greater than", "gt"), ("Less than or equal", "le"),
       ("Greater than or equal", "ge"), ("Is blank", "blank"), ("Is not blank", "notblank")]
LABELS = {"next": "Next Record", "nextif": "Next Record If", "skipif": "Skip Record If",
          "ask": "", "set": "", "record": "Merge Record #", "seq": "Merge Sequence #"}

WORD_FIELDS = ["Courtesy Title", "First Name", "Last Name", "Company", "Address 1",
               "Address 2", "City", "State", "Postal Code", "Country or Region", "Phone",
               "E-mail Address"]
GUESS = {"Courtesy Title": ("Title", "Salutation"),
         "First Name": ("First Name", "FirstName", "Given Name", "First"),
         "Last Name": ("Last Name", "LastName", "Surname", "Family Name", "Last"),
         "Company": ("Company", "Company Name", "Organization"),
         "Address 1": ("Address Line 1", "Address1", "Address", "Street"),
         "Address 2": ("Address Line 2", "Address2"), "City": ("City", "Town"),
         "State": ("State", "Province", "Region"),
         "Postal Code": ("ZIP Code", "Zip", "Postal Code", "Postcode", "ZIP"),
         "Country or Region": ("Country", "Country or Region"),
         "Phone": ("Phone", "Telephone", "Home Phone", "Work Phone"),
         "E-mail Address": ("Email", "E-mail", "Email Address", "E-mail Address")}


# ------------------------------------------------------------ storage
def rules(m):
    if not hasattr(m, "getTextFields") and hasattr(m, "engine"):
        from .native import mailmerge
        return mailmerge.rules(m)
    try:
        r = json.loads(docapi._doc_setting(m, "MergeRules", "") or "{}")
        return r if isinstance(r, dict) else {}
    except ValueError:
        return {}


def _save(m, r):
    docapi._set_doc_setting(m, "MergeRules", json.dumps(r))


def matches(m):
    if not hasattr(m, "getTextFields") and hasattr(m, "engine"):
        from .native import mailmerge
        try:
            v = json.loads(mailmerge._docvar(m, "FolioMergeMatch") or "{}")
            return v if isinstance(v, dict) else {}
        except ValueError:
            return {}
    try:
        v = json.loads(docapi._doc_setting(m, "MergeMatch", "") or "{}")
        return v if isinstance(v, dict) else {}
    except ValueError:
        return {}


def matched_column(m, word_field, cols):
    mm = matches(m)
    if word_field in mm:
        return mm[word_field] or None
    low = {c.lower().replace(" ", "").replace("_", "").replace("-", ""): c for c in cols}
    for n in GUESS.get(word_field, (word_field,)):
        c = low.get(n.lower().replace(" ", "").replace("_", "").replace("-", ""))
        if c:
            return c
    return None


# ------------------------------------------------------------ evaluation
def _num(v):
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


def condition(rule, record):
    v = str(record.get(rule.get("field", ""), ""))
    op = rule.get("op", "eq")
    target = str(rule.get("value", ""))
    if op == "blank":
        return not v.strip()
    if op == "notblank":
        return bool(v.strip())
    a, b = _num(v), _num(target)
    if a is None or b is None:
        a, b = v.lower(), target.lower()
    return {"eq": a == b, "ne": a != b, "lt": a < b, "gt": a > b, "le": a <= b,
            "ge": a >= b}.get(op, False)


def value(rule, record, ctx):
    """The text a rule shows for a record. ctx: {'record', 'seq', 'answers'}."""
    k = rule["kind"]
    if k == "if":
        return rule.get("then", "") if condition(rule, record) else rule.get("else", "")
    if k == "fillin":
        return ctx.get("answers", {}).get(rule["id"], rule.get("default", ""))
    if k == "record":
        return str(ctx.get("record", 1))
    if k == "seq":
        return str(ctx.get("seq", 1))
    if k == "ref":
        return ctx.get("bookmarks", {}).get(rule.get("name", ""), "")
    return ""


def placeholder(rule):
    k = rule["kind"]
    if k in ("next", "nextif", "skipif"):
        return "«%s»" % LABELS[k]
    if k == "if":
        return rule.get("then", "") or rule.get("else", "")
    if k == "fillin":
        return rule.get("default", "")
    if k == "record":
        return "«Merge Record #»"
    if k == "seq":
        return "«Merge Sequence #»"
    if k == "ref":
        return "«%s»" % rule.get("name", "")
    return ""


def _master(m, rid, content):
    fm = m.getTextFieldMasters()
    full = PREFIX + "MergeRule_" + rid
    if fm.hasByName(full):
        ma = fm.getByName(full)
    else:
        ma = m.createInstance("com.sun.star.text.fieldmaster.User")
        ma.Name = "MergeRule_" + rid
    ma.Content = content
    return ma


def insert_rule(m, rule):
    r = rules(m)
    rid = str(max([int(k) for k in r] + [0]) + 1)
    rule["id"] = rid
    r[rid] = rule
    _save(m, r)
    vc = docapi.view_cursor(m)
    f = m.createInstance("com.sun.star.text.textfield.User")
    f.attachTextFieldMaster(_master(m, rid, placeholder(rule)))
    vc.getText().insertTextContent(vc, f, False)
    return rid


def preview(m, index, rows):
    """Show the rules' values for record `index` (None = placeholders)."""
    r = rules(m)
    fm = m.getTextFieldMasters()
    ctx = {"record": (index or 0) + 1, "seq": (index or 0) + 1,
           "bookmarks": bookmarks_for(r, rows[index] if rows and index is not None else {}, {})}
    for rid, rule in r.items():
        full = PREFIX + "MergeRule_" + rid
        if not fm.hasByName(full):
            continue
        ma = fm.getByName(full)
        if index is None or not rows:
            ma.Content = placeholder(rule)
        elif rule["kind"] in ("next", "nextif", "skipif", "ask", "set"):
            ma.Content = ""
        else:
            ma.Content = value(rule, rows[max(0, min(index, len(rows) - 1))], ctx)


def bookmarks_for(r, record, answers):
    out = {}
    for rid, rule in r.items():
        if rule["kind"] == "set":
            out[rule["name"]] = rule.get("value", "")
        elif rule["kind"] == "ask":
            out[rule["name"]] = answers.get(rid, rule.get("default", ""))
    return out


def skipped(m, record):
    return any(rule["kind"] == "skipif" and condition(rule, record)
               for rule in rules(m).values())


# ------------------------------------------------------------ merging
def fields_in_order(doc):
    """(field, anchor, master name) for merge and rule fields, in reading order."""
    en = doc.getTextFields().createEnumeration()
    out = []
    while en.hasMoreElements():
        f = en.nextElement()
        try:
            if not f.supportsService("com.sun.star.text.textfield.User"):
                continue
            name = f.getTextFieldMaster().Name
        except Exception:
            continue
        if name.startswith("Merge_") or name.startswith("MergeRule_"):
            out.append((f, f.getAnchor(), name))
    body = doc.getText()

    def key(t):
        a = t[1]
        try:
            if a.getText() == body:
                cur = body.createTextCursor()
                cur.gotoStart(False)
                cur.gotoRange(a.getStart(), True)
                return (0, len(cur.getString()))
        except Exception:
            pass
        return (1, 0)
    out.sort(key=key)
    return out


def unlink(doc, rule_defs, records, ptr, seq, answers, master_name_of):
    """Replace this copy's fields with text; returns how many records it used."""
    cur_rec = 0
    by_master = {}
    fields = fields_in_order(doc)
    from .mailings import _drop_empty_line
    for f, a, name in fields:
        rec = records[min(len(records) - 1, ptr + cur_rec)]
        if name.startswith("MergeRule_"):
            rule = rule_defs.get(name[len("MergeRule_"):], {"kind": ""})
            k = rule.get("kind")
            if k == "next" or (k == "nextif" and condition(rule, rec)):
                if ptr + cur_rec + 1 < len(records):
                    cur_rec += 1
                text_value = ""
            else:
                ctx = {"record": rec.get("__index", ptr + cur_rec + 1), "seq": seq, "answers": answers,
                       "bookmarks": bookmarks_for(rule_defs, rec, answers)}
                text_value = value(rule, rec, ctx)
        else:
            if not by_master:
                by_master.update(master_name_of)
            col = by_master.get(name, name[6:])
            text_value = rec.get(col, "")
        text = a.getText()
        c = text.createTextCursorByRange(a)
        text.removeTextContent(f)
        text.insertString(c, text_value, False)
        if not text_value:
            _drop_empty_line(text, c)
    return cur_rec + 1


def ask_answers(win, m, per_record=None):
    """Prompt for Fill-in and Ask rules (those asked once, or for a record)."""
    if getattr(win.engine, "native", False):
        from .native import mailmerge
        return mailmerge.ask_answers(win, per_record)
    r = rules(m)
    answers = {}
    for rid, rule in r.items():
        if rule["kind"] not in ("fillin", "ask"):
            continue
        if per_record is not None and rule.get("once", True):
            continue
        if per_record is None and not rule.get("once", True):
            continue
        a = win.dialogs.ask_text("Fill-in" if rule["kind"] == "fillin" else "Ask",
                                 rule.get("prompt", ""), rule.get("default", ""))
        answers[rid] = rule.get("default", "") if a is None else a
    return answers


# ------------------------------------------------------------ dialogs
def _cond_rows(cols, rule=None):
    field = combo(cols or [""], (rule or {}).get("field") or 0)
    op = combo([o[0] for o in OPS], 0)
    target = Gtk.Entry(text=(rule or {}).get("value", ""))
    op.connect("changed", lambda *_: target.set_sensitive(OPS[op.get_active()][1] not in
                                                          ("blank", "notblank")))
    return field, op, target


def _native(win):
    return getattr(win.engine, "native", False)


def _insert(win, m, rule):
    if _native(win):
        from .native import mailmerge
        mailmerge.insert_rule(win, rule)
        win.refresh_mailings()
    else:
        win.engine.sync(lambda: (insert_rule(m, rule), win.refresh_mailings()))


def rule_dialog(win, kind):
    from . import mailings as M
    if _native(win):
        from .native import mailmerge as M
        m = win
    else:
        m = win.engine.model
    if m is None:
        return
    cols = M.recipients(m)[0]
    if kind in ("record", "seq", "next"):
        _insert(win, m, {"kind": kind})
        return
    titles = {"if": "Insert Word Field: IF", "fillin": "Insert Word Field: Fill-in",
              "ask": "Insert Word Field: Ask", "set": "Insert Word Field: Set",
              "nextif": "Insert Word Field: Next Record If",
              "skipif": "Insert Word Field: Skip Record If"}
    d = FDialog(win, titles[kind])
    rule = {"kind": kind}
    if kind in ("if", "nextif", "skipif"):
        field, op, target = _cond_rows(cols)
        d.add(grid([["Field name:", field], ["Comparison:", op], ["Compare to:", target]]))
        if kind == "if":
            then = Gtk.TextView()
            other = Gtk.TextView()
            for tv in (then, other):
                tv.set_size_request(380, 60)
                tv.set_wrap_mode(Gtk.WrapMode.WORD)
            d.add(Gtk.Label(label="Insert this text:", xalign=0))
            f1 = Gtk.Frame()
            f1.add(then)
            d.add(f1)
            d.add(Gtk.Label(label="Otherwise insert this text:", xalign=0))
            f2 = Gtk.Frame()
            f2.add(other)
            d.add(f2)
    if kind in ("ask", "set"):
        name = Gtk.Entry()
        name.set_placeholder_text("Bookmark")
        d.add(grid([["Bookmark:", name]]))
    if kind in ("ask", "fillin"):
        prompt = Gtk.Entry()
        prompt.set_width_chars(40)
        d.add(grid([["Prompt:", prompt]]))
    if kind in ("ask", "fillin", "set"):
        default = Gtk.Entry()
        d.add(grid([["Default " + ("bookmark text:" if kind != "fillin" else "fill-in text:")
                     if kind != "set" else "Value:", default]]))
    if kind in ("ask", "fillin"):
        once = Gtk.CheckButton(label="Ask once")
        d.add(once)
    if d.ask() != Gtk.ResponseType.OK:
        d.done()
        return
    if kind in ("if", "nextif", "skipif"):
        rule.update({"field": field.get_active_text(), "op": OPS[op.get_active()][1],
                     "value": target.get_text()})
        if kind == "if":
            b1, b2 = then.get_buffer(), other.get_buffer()
            rule["then"] = b1.get_text(*b1.get_bounds(), False)
            rule["else"] = b2.get_text(*b2.get_bounds(), False)
    if kind in ("ask", "set"):
        rule["name"] = name.get_text().strip() or "Bookmark1"
    if kind in ("ask", "fillin"):
        rule["prompt"] = prompt.get_text()
        rule["once"] = once.get_active()
    if kind in ("ask", "fillin", "set"):
        rule["default" if kind != "set" else "value"] = default.get_text()
    d.done()
    if kind == "fillin":
        a = win.dialogs.ask_text("Microsoft" if False else "Fill-in", rule["prompt"],
                                 rule.get("default", ""))
        if a is not None:
            rule["default"] = a
    _insert(win, m, rule)


def bookmark_names(m):
    if not hasattr(m, "getTextFields") and hasattr(m, "engine"):
        from .native import mailmerge
        return mailmerge.bookmark_names(m)
    return sorted({rule["name"] for rule in rules(m).values()
                   if rule["kind"] in ("ask", "set") and rule.get("name")})


def insert_ref(win, name):
    if _native(win):
        _insert(win, win, {"kind": "ref", "name": name})
        return
    m = win.engine.model
    win.engine.sync(lambda: (insert_rule(m, {"kind": "ref", "name": name}),
                             win.refresh_mailings()))


def match_fields_dialog(win):
    from . import mailings as M
    m = win.engine.model
    if _native(win):
        from .native import mailmerge as M
        m = win
    if m is None:
        return
    cols = M.recipients(m)[0]
    if not cols:
        win.dialogs.message("Select a recipient list first.")
        return
    d = FDialog(win, "Match Fields")
    lab = Gtk.Label(xalign=0)
    lab.set_line_wrap(True)
    lab.set_max_width_chars(60)
    lab.set_text("Special features in mail merge make it easy to insert information from "
                  "your recipient list. Use the drop-down lists to choose the column that "
                  "matches each address field.")
    d.add(lab)
    choices = ["(not matched)"] + cols
    rows, widgets = [], {}
    for wf in WORD_FIELDS:
        c = matched_column(m, wf, cols)
        w = combo(choices, c if c in cols else "(not matched)")
        widgets[wf] = w
        rows.append([wf + ":", w])
    sw = Gtk.ScrolledWindow()
    sw.set_size_request(420, 320)
    sw.add(grid(rows))
    d.add(sw, expand=True)
    remember = Gtk.CheckButton(label="Remember this matching for this set of data sources "
                                     "on this computer")
    remember.set_active(True)
    d.add(remember)
    if d.ask() == Gtk.ResponseType.OK:
        mm = {wf: (w.get_active_text() if w.get_active() > 0 else "")
              for wf, w in widgets.items()}
        if _native(win):
            from .native import mailmerge
            mailmerge._set_docvar(win, "FolioMergeMatch", json.dumps(mm))
        else:
            docapi._set_doc_setting(m, "MergeMatch", json.dumps(mm))
    d.done()


def auto_check_dialog(win):
    """Checking and Reporting Errors."""
    from . import mailings as M
    from .dlg_mail import finish
    m = win.engine.model
    if _native(win):
        m = win
    if m is None:
        return
    d = FDialog(win, "Checking and Reporting Errors")
    r1 = Gtk.RadioButton.new_with_mnemonic(
        None, "_Simulate the merge and report errors in a new document.")
    r2 = Gtk.RadioButton.new_with_mnemonic_from_widget(
        r1, "Complete the merge, _pausing to report each error as it occurs.")
    r3 = Gtk.RadioButton.new_with_mnemonic_from_widget(
        r1, "Complete the merge _without pausing. Report errors in a new document.")
    for r in (r1, r2, r3):
        d.add(r)
    res = d.ask()
    mode = [r1, r2, r3].index(next(r for r in (r1, r2, r3) if r.get_active()))
    d.done()
    if res != Gtk.ResponseType.OK:
        return
    errors = find_errors(m)
    if mode == 1 and errors:
        for e in errors:
            if not win.dialogs.confirm(e + "\n\nContinue?", yes="OK", no="Cancel"):
                return
        finish(win)
        return
    if mode == 0 and not errors:
        win.dialogs.message("No mail merge errors have been found in %s." %
                            (win.doc_name()))
        return
    if errors:
        w = win.app.new_window()

        def fill():
            if w.engine.model is None:
                return True
            w.actions.insert_text("Mail Merge Errors\n\n" + "\n".join(errors))
            return False
        from gi.repository import GLib
        GLib.timeout_add(800, fill)
    if mode == 2:
        finish(win)


def find_errors(m):
    from . import mailings as M
    if not hasattr(m, "getTextFields") and hasattr(m, "engine"):
        from .native import mailmerge as M
    cols, rows, inc = M.recipients(m)
    out = []
    if not rows:
        out.append("The document has no recipient list.")
        return out
    for col in M.merge_masters(m):
        if col not in cols:
            out.append("The merge field «%s» doesn't match a column in the recipient list."
                       % col)
    for rule in rules(m).values():
        if rule.get("field") and rule["field"] not in cols:
            out.append("A %s rule uses the field «%s», which isn't in the recipient list."
                       % (LABELS.get(rule["kind"]) or rule["kind"].upper(), rule["field"]))
    if not any(inc):
        out.append("No recipients are selected.")
    return out
