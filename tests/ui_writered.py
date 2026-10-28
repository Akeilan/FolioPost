# Run inside Folio Post (FOLIO_TEST_SCRIPT): M-04, mail written in Folio Writer's editor.
import base64
import os
import re
import sys
import time
import traceback

from gi.repository import Gtk

FAILS = []
OUT = os.environ.get("UI_OUT", "/tmp/ui_out")
os.makedirs(OUT, exist_ok=True)


def pump(t=0.1):
    end = time.time() + t
    while time.time() < end:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        time.sleep(0.003)


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    sys.stdout.flush()
    if not cond:
        FAILS.append(what)


def shot(w, name):
    import cairo
    from gi.repository import Gdk
    pump(0.3)
    gw = w.get_window()
    img = cairo.ImageSurface(cairo.FORMAT_ARGB32, gw.get_width(), gw.get_height())
    cr = cairo.Context(img)
    Gdk.cairo_set_source_window(cr, gw, 0, 0)
    cr.paint()
    img.write_to_png(os.path.join(OUT, "writered_%s.png" % name))


try:
    from folio_post import writered, mime
    from folio_post.compose import make_editor
    check(writered.available(), "Writer's engine is here (vendored Folio Writer %s)" % writered.writer_version())
    ed = make_editor()
    check(isinstance(ed, writered.WriterEditor), "new messages are written in Writer's editor")
    w = Gtk.Window()
    w.set_default_size(700, 500)
    sw = Gtk.ScrolledWindow()
    sw.add(ed)
    w.add(sw)
    w.show_all()
    pump(0.5)
    ed.insert_text("Hello world")
    ed.select_offsets(0, 5)
    ed.toggle("bold")
    check(ed.state()["bold"], "bold on the selection")
    ed.select_offsets(6, 11)
    ed.set_char("color", "C00000")
    ed.set_char("size", 16)
    st = ed.state()
    check(st["color"] == "#c00000" and float(st["size"]) == 16, "colour and size: %s" % st)
    h, pics = ed.to_html()
    check(re.search(r"<(b|strong)[^>]*>Hello</(b|strong)>", h) or "font-weight:bold" in h, "bold out: %s" % h[:300])
    check("C00000" in h.upper() and "16pt" in h, "colour and size out")
    ed.caret_to_end()
    ed.insert_text("\nCentered")
    ed.set_align("center")
    check(ed.state()["align"] == "center" and "center" in ed.to_html()[0], "centred paragraph")
    ed.insert_text("\nOne")
    ed.set_list("bullet")
    ed.insert_text("\nTwo")
    st = ed.state()
    check(st["list"] == "bullet", "a bulleted list continues on Enter")
    hh = ed.to_html()[0]
    check(hh.count("<li") == 2 or hh.count("•") == 2 or hh.count("&#8226;") == 2, "both bullets go out: %s" % hh[-400:])
    ed.insert_text("\n")
    ed.set_list("bullet")
    ed.insert_link("https://example.org/", "site")
    check('href="https://example.org/"' in ed.to_html()[0], "link out")
    t = ed.text()
    check(t.startswith("Hello world") and "Centered" in t and "site" in t, "plain text: %r" % t[:80])
    shot(w, "formatted")
    # round trip through HTML (drafts, signatures)
    before = ed.to_html()[0]
    ed.load_html(before)
    after = ed.to_html()[0]
    check("Hello" in after and "center" in after and "href=" in after, "HTML round trip: " + after[:400])
    # undo starts after loading
    ed.undo = []
    check(not ed.undo, "loaded text is where undo starts")
    ed.caret_to_end()
    ed.insert_text(" tail")
    ed.do_undo()
    check(" tail" not in ed.text(), "undo")
    # pictures go as cid: parts
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
    ed.insert_picture(png, "image/png")
    h, pics = ed.to_html()
    check(len(pics) == 1 and "cid:" + pics[0][0] in h, "picture as an inline part")
    m = mime.build(("", "me@example.org"), ["you@example.org"], subject="x", text=ed.text(), html_body=h, inline=pics)
    att = mime.attachments(mime.parse(mime.to_bytes(m)))
    check(any(a["cid"] == pics[0][0] for a in att), "the picture travels with the message")
    # foreign mail HTML
    ed.load_html('<div style="font-family:Arial"><p>Dear <strong>Ann</strong>,</p><ul><li>a</li><li>b</li></ul>'
                 '<p style="text-align:right">r</p><script>x()</script></div>')
    t = ed.text()
    check("Dear Ann," in t and "x()" not in t, "foreign HTML loads, scripts dropped: %r" % t)
    ed.select_offsets(5, 8)
    check(ed.state()["bold"], "strong becomes bold")
    # tables
    ed.load_html("<p>Before</p>")
    ed.caret_to_end()
    ed.insert_table(2, 3, [["Item", "", ""], ["", "", "42"]])
    h = ed.to_html()[0]
    check("<table" in h and ">Item<" in h.replace("</span>", "<").replace("<span", "<") or ("<table" in h and "Item" in h and "42" in h),
          "a table goes out as an HTML table")
    check("Item" in ed.text() and "42" in ed.text(), "and as text")
    # spelling
    try:
        import enchant
        sp = enchant.Dict("en_US")
    except Exception:
        sp = None
    if sp is not None:
        ed.load_html("<p>This sentense has a mistake and an adress.</p>")
        ed.set_speller(sp)
        bad = [x for _s, _e, x in ed.misspelt()]
        check(bad == ["sentense", "adress"], "misspelt words found: %s" % bad)
        s0, e0, w0 = ed.misspelt()[0]
        check("sentence" in ed.suggest(w0), "suggestions")
        ed.replace_range(s0, e0, "sentence")
        check("This sentence has" in ed.text(), "a suggestion replaces the word: %r" % ed.text())
        ed.ignore("adress")
        check(ed.misspelt() == [], "Ignore All")
        shot(w, "spelling")
    # empty
    ed.load_html("")
    check(ed.is_empty(), "an empty message is empty")
    w.destroy()
    # in a real compose window: typing, Ctrl+B, sending HTML
    c = app.compose(to="you@example.org", subject="Writer editor")
    pump(0.6)
    check(isinstance(c.editor, writered.WriterEditor), "the compose window uses Writer's editor")
    c.editor.grab_focus()
    c.editor.insert_text("From Writer")
    c.editor.select_offsets(0, 4)
    c.run("bold")
    check(c.editor.state()["bold"], "the ribbon's Bold reaches Writer's editor")
    c.run("bullets")
    check(c.editor.state()["list"] == "bullet", "Bullets")
    shot(c, "compose")
    check(c.modified, "editing marks the message changed")
    c.modified = False
    c.close()
except Exception:
    traceback.print_exc()
    FAILS.append("exception")
print("UI FAILS: %d" % len(FAILS) if FAILS else "UI all passed")
sys.stdout.flush()
os._exit(1 if FAILS else 0)
