"""A message open in its own window (double-click, Enter, or a saved .eml file)."""
from gi.repository import Gdk, Gtk

from . import APP_NAME, icons, mime
from .dialogs import Dialogs
from .readingpane import ReadingPane
from .ribbon import Ribbon, Tab
from .ribbon_post import Builder, categories_menu, follow_up_menu, move_menu


class MessageWindow(Gtk.Window):
    def __init__(self, main, mid, raw=None, path=None):
        Gtk.Window.__init__(self)
        self.main = main
        self.app = main.app
        self.store = main.store
        self.mid = mid
        self.path = path
        self.dialogs = Dialogs(self)
        self.set_default_size(900, 720)
        self.set_icon_name("folio-post")
        self.header = Gtk.HeaderBar()
        self.header.set_show_close_button(True)
        self.header.get_style_context().add_class("folio-titlebar")
        self.title_label = Gtk.Label()
        self.title_label.get_style_context().add_class("title")
        self.header.set_custom_title(self.title_label)
        self.qat = Gtk.Box()
        for icon, cmd, tip in (("p-reply", "reply", "Reply"), ("p-up", "previous", "Previous Item (Ctrl+,)"),
                               ("p-down", "next", "Next Item (Ctrl+.)")):
            b = Gtk.Button()
            b.add(icons.white_image(icon, 16))
            b.set_tooltip_text(tip)
            b.connect("clicked", lambda _b, c=cmd: self.run(c))
            self.qat.pack_start(b, False, False, 0)
        self.header.pack_start(self.qat)
        self.set_titlebar(self.header)
        self.overlay = Gtk.Overlay()
        self.add(self.overlay)
        self.outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.overlay.add(self.outer)
        self.ribbon = Ribbon(self.run, lambda: self.reading.view.grab_focus())
        self.ribbon.connect("file-clicked", lambda *_: self.show_backstage())
        self.outer.pack_start(self.ribbon, False, False, 0)
        self.reading = ReadingPane(self)
        self.outer.pack_start(self.reading, True, True, 0)
        self.build_ribbon()
        from .keytips import KeyTips
        self.keytips = KeyTips(self)
        self.connect("key-press-event", self.on_key)
        self.show_all()
        self.show_item(mid, raw)

    def show_item(self, mid, raw=None):
        self.mid = mid
        self.reading.show_message(mid, raw)
        subj = mime.header(self.reading.msg, "Subject") if self.reading.msg is not None else ""
        self.title_label.set_text("%s - Message - %s" % (subj or "(no subject)", APP_NAME))
        self.set_title(self.title_label.get_text())

    def build_ribbon(self):
        B = Builder(self)
        r = self.ribbon
        t = r.building(Tab("Message", "H"))
        B.group(t, "Delete", [
            [B.small("Junk", "p-junk", None, "J", menu=[("Block Sender", "block-sender"), ("Not Junk", "not-junk")])],
            B.big("Delete", "p-delete", "delete", "D"), B.big("Archive", "p-archive", "archive", "EA")])
        B.group(t, "Respond", [B.big("Reply", "p-reply", "reply", "RP"), B.big("Reply All", "p-reply-all", "reply-all", "RA"),
                               B.big("Forward", "p-forward", "forward", "FW")])
        B.group(t, "Move", [B.big("Move", "p-move", None, "MV", menu=lambda: move_menu(self.main))])
        B.group(t, "Tags", [[B.small("Mark Unread", "p-unread", "mark-unread", "W"),
                             B.small("Categorize", "p-categorize", None, "G", menu=categories_menu),
                             B.small("Follow Up", "p-flag", None, "U", menu=follow_up_menu())]])
        B.group(t, "Editing", [[B.small("Copy", "r-copy-sm", "copy", "C"), B.small("Print", "p-print", "print", "P"),
                                B.small("Save As", "p-save-as", "save-as", "S")]])
        B.group(t, "Zoom", [B.big("Zoom", "p-zoom", "zoom", "Q")])
        r.add_tab(t)
        r.select(t)

    def show_backstage(self, page=None):
        menu = Gtk.Menu()
        for label, cmd in (("Save As...", "save-as"), ("Save Attachments...", "save-attachments"), ("Print", "print"),
                           ("Close", "close")):
            mi = Gtk.MenuItem(label=label)
            mi.connect("activate", lambda _m, c=cmd: self.run(c))
            menu.append(mi)
        menu.show_all()
        menu.popup_at_widget(self.ribbon.file_button, Gdk.Gravity.SOUTH_WEST, Gdk.Gravity.NORTH_WEST, None)

    def run(self, cmd, *args):
        if cmd is None:
            return None
        name, _, arg = cmd.partition(":")
        fn = getattr(self, "act_" + name.replace("-", "_"), None)
        if fn is not None:
            return fn(arg) if arg or _ else fn()
        if self.mid is None:
            if name in ("reply", "reply-all", "forward"):
                return self._respond_file(name)
            self.dialogs.info("This message is a file, not in a mailbox, so “%s” doesn't apply." % name)
            return None
        # the rest act on this message through the main window
        self.main.select_ids([self.mid])
        after = None
        if name in ("delete", "archive", "move", "block-sender", "not-junk"):
            after = self.main._next_after([self.mid])
        r = self.main.run(cmd)
        if name in ("delete", "archive", "move", "block-sender", "not-junk"):
            if after:
                self.show_item(after)
            else:
                self.destroy()
        elif self.mid and self.store.message(self.mid):
            self.show_item(self.mid)
        return r

    def _respond_file(self, mode):
        raw = self.reading.raw
        acc = self.main.current_account()
        # replying to a file: a copy goes into a local scratch folder so the window has it to quote
        local = [a for a in self.store.accounts() if a["kind"] == "local"]
        if local:
            aid = local[0]["id"]
        else:
            aid = self.store.add_account("On This Computer", "", "local", {})
        inbox = self.store.folder_by_role(aid, "inbox")
        mid = self.store.add_message(inbox["id"], raw, 0, ["seen"])
        return self.app.compose(reply_to=mid, mode=mode, account=acc["id"] if acc else None)

    def act_previous(self):
        self._step(-1)

    def act_next(self):
        self._step(1)

    def _step(self, d):
        rows = [r[0] for r in self.main.iter_rows()]
        if self.mid in rows:
            i = rows.index(self.mid) + d
            if 0 <= i < len(rows):
                self.show_item(rows[i])
                self.main.mark_read([rows[i]])

    def act_copy(self):
        t = self.reading.selected_text() or self.reading.view.text()
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(t, -1)

    def act_save_as(self):
        from .window import save_message
        dlg = Gtk.FileChooserDialog(title="Save As", transient_for=self, action=Gtk.FileChooserAction.SAVE)
        dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Save", Gtk.ResponseType.OK)
        dlg.set_do_overwrite_confirmation(True)
        dlg.set_current_name("message.eml")
        path = dlg.get_filename() if dlg.run() == Gtk.ResponseType.OK else None
        dlg.destroy()
        if path:
            save_message(self.reading.raw, path)

    def act_save_attachments(self):
        self.reading.save_all()

    def act_print(self):
        from .printing import print_message
        print_message(self, self.reading.raw)

    def act_zoom(self):
        z = self.dialogs.ask_text("Zoom", "Zoom (percent):", str(int(self.reading.zoom * 100)))
        try:
            self.reading.set_zoom(max(50, min(500, int((z or "").strip().rstrip("%")))) / 100.0)
        except ValueError:
            pass

    def act_close(self):
        self.destroy()

    def on_key(self, w, ev):
        ctrl = ev.state & Gdk.ModifierType.CONTROL_MASK
        shift = ev.state & Gdk.ModifierType.SHIFT_MASK
        if self.keytips.active:
            return self.keytips.key(ev)
        k = ev.keyval
        if k == Gdk.KEY_Escape:
            self.destroy()
            return True
        if ctrl and shift and k in (Gdk.KEY_R, Gdk.KEY_r):
            self.run("reply-all")
            return True
        if ctrl and not shift:
            cmd = {Gdk.KEY_r: "reply", Gdk.KEY_f: "forward", Gdk.KEY_d: "delete", Gdk.KEY_p: "print", Gdk.KEY_u: "mark-unread",
                   Gdk.KEY_period: "next", Gdk.KEY_comma: "previous", Gdk.KEY_c: "copy", Gdk.KEY_s: "save-as"}.get(k)
            if cmd:
                self.run(cmd)
                return True
        if k == Gdk.KEY_Delete and not ctrl:
            self.run("delete")
            return True
        if k == Gdk.KEY_F10:
            self.keytips.start()
            return True
        return False
