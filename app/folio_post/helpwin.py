"""Help: how Post works, and its keyboard shortcuts."""
from gi.repository import Gtk

from . import APP_NAME

HELP = """<big><b>Folio Post</b></big>

<b>Accounts.</b> File &gt; Add Account. Gmail: sign in with Google in your browser (needs an OAuth client ID you make
once in your Google Cloud console) or use an app password. Proton Mail: install Proton Mail Bridge, sign in there, and
use the password Bridge shows. Other providers: your address and password, or the server settings.

<b>Reading.</b> Pick a folder on the left and a message in the list. Pictures from the internet stay off until you
choose Download Pictures. Double-click a message to open it in its own window.

<b>Writing.</b> New Email (Ctrl+N), Reply (Ctrl+R), Reply All (Ctrl+Shift+R), Forward (Ctrl+F). Send with Ctrl+Enter or
Alt+S. Unsent messages are saved in Drafts every few minutes.

<b>Working offline.</b> Everything you've received is kept on this computer. Send / Receive &gt; Work Offline keeps new
mail in the Outbox until you go online again.

<b>Organizing.</b> Drag messages to folders (hold Ctrl to copy). Flag (Insert), categorize, Quick Steps, rules, and
the junk lists in Home &gt; Junk.
"""

SHORTCUTS = [
    ("New email", "Ctrl+N"), ("Reply", "Ctrl+R"), ("Reply All", "Ctrl+Shift+R"), ("Forward", "Ctrl+F"),
    ("Forward as attachment", "Ctrl+Alt+F"), ("Send", "Ctrl+Enter / Alt+S"), ("Delete", "Delete / Ctrl+D"),
    ("Delete permanently", "Shift+Delete"), ("Archive", "Backspace"), ("Mark as read", "Ctrl+Q"),
    ("Mark as unread", "Ctrl+U"), ("Flag / clear flag", "Insert"), ("Move to folder", "Ctrl+Shift+V"),
    ("Go to folder", "Ctrl+Y"), ("New folder", "Ctrl+Shift+E"), ("Search", "Ctrl+E / F3"),
    ("Send/Receive all folders", "F9"), ("Update folder", "Shift+F9"), ("Next / previous item", "Ctrl+. / Ctrl+,"),
    ("Open item", "Enter / Ctrl+O"), ("Print", "Ctrl+P"), ("Save as", "Ctrl+S"), ("Undo", "Ctrl+Z"),
    ("Mail, Calendar, People, Tasks", "Ctrl+1 … Ctrl+4"), ("KeyTips", "Alt / F10"), ("Check names (in To)", "Ctrl+K"),
    ("Hyperlink (in the message)", "Ctrl+K"), ("Bold, italic, underline", "Ctrl+B, Ctrl+I, Ctrl+U"),
    ("Bullets", "Ctrl+Shift+L"), ("Align left / center / right", "Ctrl+L / Ctrl+E / Ctrl+R"),
]


def show_help(win):
    d = Gtk.Dialog(title="%s Help" % APP_NAME, transient_for=win)
    d.set_default_size(620, 520)
    lab = Gtk.Label(xalign=0, yalign=0)
    lab.set_markup(HELP.replace("\n\n", " ").replace("\n", " ").replace(" ", "\n\n"))
    lab.set_line_wrap(True)
    lab.set_border_width(16)
    sw = Gtk.ScrolledWindow()
    sw.add(lab)
    d.get_content_area().pack_start(sw, True, True, 0)
    d.add_button("Close", Gtk.ResponseType.CLOSE)
    d.connect("response", lambda *_: d.destroy())
    d.show_all()
    return d


def show_shortcuts(win):
    d = Gtk.Dialog(title="Keyboard Shortcuts", transient_for=win)
    d.set_default_size(480, 560)
    grid = Gtk.Grid(column_spacing=24, row_spacing=4)
    grid.set_border_width(16)
    for i, (what, keys) in enumerate(SHORTCUTS):
        grid.attach(Gtk.Label(label=what, xalign=0), 0, i, 1, 1)
        k = Gtk.Label(xalign=0)
        k.set_markup("<b>%s</b>" % keys)
        grid.attach(k, 1, i, 1, 1)
    sw = Gtk.ScrolledWindow()
    sw.add(grid)
    d.get_content_area().pack_start(sw, True, True, 0)
    d.add_button("Close", Gtk.ResponseType.CLOSE)
    d.connect("response", lambda *_: d.destroy())
    d.show_all()
    return d
