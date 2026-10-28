"""Printing a message (Memo Style): the header block, then the body as text."""
import time

from gi.repository import Gtk, Pango, PangoCairo

from . import mime


def message_layout_text(raw):
    msg = mime.parse(raw)
    head = []
    for k, v in mime.quote_header(msg):
        head.append("<b>%s:</b>\t%s" % (k, _esc(v)))
    atts = [a["name"] for a in mime.attachments(msg) if not a["inline"]]
    if atts:
        head.append("<b>Attachments:</b>\t%s" % _esc("; ".join(atts)))
    return "\n".join(head), mime.text_of(msg)


def _esc(s):
    from gi.repository import GLib
    return GLib.markup_escape_text(s or "")


def print_message(parent, raw, to_file=None):
    head, body = message_layout_text(raw)
    op = Gtk.PrintOperation()
    op.set_job_name("Folio Post message")
    state = {"pages": []}

    def begin(op, ctx):
        w = ctx.get_width()
        h = ctx.get_height()
        lay = ctx.create_pango_layout()
        lay.set_width(int(w * Pango.SCALE))
        lay.set_wrap(Pango.WrapMode.WORD_CHAR)
        lay.set_font_description(Pango.FontDescription("Sans 10"))
        lay.set_markup(head + "\n" + "_" * 60 + "\n\n" + _esc(body), -1)
        state["layout"] = lay
        pages, start, y0 = [], 0, 0
        it = lay.get_iter()
        while True:
            line_rect = it.get_line_extents()[1]
            top = line_rect.y / Pango.SCALE
            if top + line_rect.height / Pango.SCALE - y0 > h:
                pages.append((start, y0))
                start, y0 = it.get_index(), top
            if not it.next_line():
                break
        pages.append((start, y0))
        state["pages"] = pages
        op.set_n_pages(len(pages))

    def draw(op, ctx, n):
        cr = ctx.get_cairo_context()
        lay = state["layout"]
        _start, y0 = state["pages"][n]
        h = ctx.get_height()
        cr.rectangle(0, 0, ctx.get_width(), h)
        cr.clip()
        cr.move_to(0, -y0)
        PangoCairo.show_layout(cr, lay)

    op.connect("begin-print", begin)
    op.connect("draw-page", draw)
    if to_file:
        op.set_export_filename(to_file)
        return op.run(Gtk.PrintOperationAction.EXPORT, parent)
    return op.run(Gtk.PrintOperationAction.PRINT_DIALOG, parent)
