# Run inside Folio Post (FOLIO_TEST_SCRIPT): the message editor's formatting in and out of HTML.
import os
import sys
import time
import traceback

from gi.repository import Gtk

FAILS = []


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


try:
    from folio_post.richedit import RichEditor
    from folio_post import mime
    w = Gtk.Window()
    ed = RichEditor()
    w.add(ed)
    w.show_all()
    pump()
    b = ed.buf
    b.insert_at_cursor("Hello world")
    b.select_range(b.get_iter_at_offset(0), b.get_iter_at_offset(5))
    ed.toggle("bold")
    b.select_range(b.get_iter_at_offset(6), b.get_iter_at_offset(11))
    ed.set_char("color", "C00000")
    ed.set_char("size", 16)
    h, pics = ed.to_html()
    check("<b>Hello</b>" in h, "bold out")
    check("color:#C00000" in h and "font-size:16pt" in h, "colour and size out")
    # typing continues the formatting before it
    b.place_cursor(b.get_iter_at_offset(5))
    b.insert_at_cursor("!")
    check("<b>Hello!</b>" in ed.to_html()[0], "typing keeps bold")
    # pending formatting for what's typed next
    b.place_cursor(b.get_end_iter())
    ed.pending = {}
    ed.set_char("italic", True) if ed._word_range() is None else None
    b.insert_at_cursor(" more")
    # paragraphs, alignment, lists
    b.place_cursor(b.get_end_iter())
    b.insert_at_cursor("\nCentered")
    ed.set_align("center")
    check("text-align:center" in ed.to_html()[0], "center out")
    b.insert_at_cursor("\nOne")
    ed.set_list("bullet")
    b.place_cursor(b.get_end_iter())
    b.insert_at_cursor("\nTwo")
    ed._continue_list("bullet") if False else None
    ed.set_list("bullet")
    h = ed.to_html()[0]
    check(h.count("<li>") == 2 and "<ul>" in h, "bullets out: %s" % h[-200:])
    check("•" not in h, "bullet markers aren't in the HTML")
    ed.set_list("number")
    h = ed.to_html()[0]
    check("<ol>" in h, "numbering")
    # link
    b.place_cursor(b.get_end_iter())
    b.insert_at_cursor("\n")
    ed.insert_link("https://example.org/", "site")
    check('<a href="https://example.org/">' in ed.to_html()[0], "link out")
    # round trip
    before = ed.to_html()[0]
    ed.load_html(before)
    after = ed.to_html()[0]
    check("<b>Hello!</b>" in after and "text-align:center" in after and "<a href=" in after and "<ol>" in after,
          "HTML round trip: " + after.replace("\n", " ")[:900])
    check(ed.text().startswith("Hello! world"), "text: %r" % ed.text()[:30])
    # undo
    ed.undo = []
    b.place_cursor(b.get_end_iter())
    b.insert_at_cursor(" tail")
    check(ed.do_undo() and " tail" not in ed.text(), "undo")
    # pictures go as cid: parts
    import base64
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
    ed.insert_picture(png, "image/png")
    h, pics = ed.to_html()
    check(len(pics) == 1 and "cid:" + pics[0][0] in h, "picture as an inline part")
    m = mime.build(("", "me@example.org"), ["you@example.org"], subject="x", text=ed.text(), html_body=h, inline=pics)
    raw = mime.to_bytes(m)
    att = mime.attachments(mime.parse(raw))
    check(any(a["cid"] == pics[0][0] for a in att), "the picture travels with the message")
    # loading mail-ish HTML
    ed.load_html('<div style="font-family:Arial"><p>Dear <strong>Ann</strong>,</p><ul><li>a</li><li>b</li></ul>'
                 '<p style="text-align:right">r</p><script>x()</script></div>')
    t = ed.text()
    check("Dear Ann," in t and "x()" not in t, "foreign HTML loads, scripts dropped")
    import re
    check(re.search(r"<b>(<span[^>]*>)?Ann", ed.to_html()[0]) is not None, "strong becomes bold")
    # tables
    ed.load_html("<p>Before</p>")
    b.place_cursor(b.get_end_iter())
    a = ed.insert_table(2, 3)
    ed.tables[a][0][0].set_text("Item")
    ed.tables[a][1][2].set_text("42")
    h = ed.to_html()[0]
    check("<table" in h and "<td" in h and ">Item<" in h and ">42<" in h, "a table goes out as an HTML table")
    check("Item\t\t" in ed.text() and "42" in ed.text(), "and as tab-separated text")
    ed.load_html(h)
    check(len(ed.tables) == 1 and list(ed.tables.values())[0][1][2].get_text() == "42", "tables come back in drafts")
    # spelling
    try:
        import enchant
        sp = enchant.Dict("en_US")
    except Exception:
        sp = None
    if sp is not None:
        ed.load_html("<p>This sentense has a mistake and an adress.</p>")
        ed.set_speller(sp)
        bad = [w for _s, _e, w in ed.misspelt()]
        check(bad == ["sentense", "adress"], "misspelt words found: %s" % bad)
        check(any(t is ed._misspelt for t in b.get_iter_at_offset(6).get_tags()), "underlined")
        s0, e0, w0 = ed.misspelt()[0]
        check("sentence" in ed.suggest(w0), "suggestions")
        ed.replace_range(s0, e0, "sentence")
        check("This sentence has" in ed.text(), "a suggestion replaces the word")
        ed.ignore("adress")
        check(ed.misspelt() == [], "Ignore All")
except Exception:
    traceback.print_exc()
    FAILS.append("exception")
print("UI FAILS: %d" % len(FAILS) if FAILS else "UI all passed")
sys.stdout.flush()
os._exit(1 if FAILS else 0)
