"""The main window's ribbon, laid out as the original's desktop ribbon for Mail (cloud, sign-in to
the vendor, add-ins and AI commands are left out)."""
from gi.repository import Gtk

from .ribbon import CheckControl, Group, MenuButton, RibbonButton, SplitButton, Tab, menu_popover

CATEGORIES = [("Red Category", "E74856"), ("Orange Category", "FF8C00"), ("Yellow Category", "FFB900"),
              ("Green Category", "16C60C"), ("Blue Category", "0078D4"), ("Purple Category", "886CE4")]


class Cmd:
    def __init__(self, win, cmd):
        self.win = win
        self.cmd = cmd

    def __call__(self, *_):
        self.win.run(self.cmd)


class Builder:
    def __init__(self, win):
        self.win = win
        self.r = win.ribbon

    def menu(self, items):
        out = []
        for it in items:
            if it is None or isinstance(it, Gtk.Widget):
                out.append(it)
                continue
            label, cmd = it[0], it[1]
            if isinstance(cmd, list):
                out.append((label, self.menu(cmd)))
                continue
            if callable(cmd):
                out.append((label, cmd))
                continue
            icon = it[2] if len(it) > 2 else None
            out.append((label, Cmd(self.win, cmd), icon) if icon else (label, Cmd(self.win, cmd)))
        return out

    def _m(self, menu):
        if callable(menu):
            return lambda: menu_popover(None, self.menu(menu()))
        return self.menu(menu)

    def big(self, label, icon, cmd, keytip, menu=None, tip=None, state=None):
        if menu is not None:
            if cmd is None:
                return MenuButton(self.r, label, icon, self._m(menu), size="large", keytip=keytip, tooltip=tip or label)
            return SplitButton(self.r, label, icon, cmd, self._m(menu), size="large", keytip=keytip, tooltip=tip or label)
        return RibbonButton(self.r, label, icon, cmd, size="large", keytip=keytip, tooltip=tip or label, state=state)

    def small(self, label, icon, cmd, keytip, menu=None, tip=None, state=None):
        if label is None and menu is None:
            return RibbonButton(self.r, None, icon, cmd, size="icon", keytip=keytip, tooltip=tip, state=state)
        if menu is not None:
            if cmd is None:
                return MenuButton(self.r, label, icon, self._m(menu), size="small", keytip=keytip, tooltip=tip or label)
            return SplitButton(self.r, label, icon, cmd, self._m(menu), size="small", keytip=keytip,
                               tooltip=tip or label, state=state)
        return RibbonButton(self.r, label, icon, cmd, size="small", keytip=keytip, tooltip=tip or label, state=state)

    def group(self, tab, caption, columns, launcher=None, launcher_keytip=None):
        g = Group(caption, columns, launcher=launcher, ribbon=self.r, launcher_keytip=launcher_keytip)
        tab.add(g)
        return g


def move_menu(win, cmd="move"):
    """The folders of every account, for Move and Copy."""
    items = []
    for acc in win.store.accounts():
        sub = []
        for f in win.store.folders(acc["id"]):
            if f["role"] == "outbox":
                continue
            sub.append((win.folder_label(f), "%s:%d" % (cmd, f["id"])))
        items.append((acc["name"] or acc["email"], sub))
    if len(items) == 1:
        items = items[0][1]
    return items + [None, ("Other Folder...", cmd + "-other"), ("Copy to Folder...", "copy-other")]


def categories_menu():
    return [(n, "categorize:" + n.split()[0]) for n, _c in CATEGORIES] + [None, ("Clear All Categories", "categorize:")]


def follow_up_menu():
    return [("Today", "flag-due:today", "p-flag"), ("Tomorrow", "flag-due:tomorrow", "p-flag"),
            ("This Week", "flag-due:this-week", "p-flag"), ("Next Week", "flag-due:next-week", "p-flag"),
            ("No Date", "flag-due:none", "p-flag"), None, ("Flag Message", "flag:on", "p-flag"),
            ("Mark Complete", "flag:done", "p-flag-done"), ("Clear Flag", "flag:off")]


def filter_menu():
    return [("All", "filter:all"), ("Unread", "filter:unread"), ("Has Attachments", "filter:attach"),
            ("Flagged", "filter:flagged"), ("Important", "filter:important"), ("Sent To: Me", "filter:to-me"),
            ("This Week", "filter:week"), ("Categorized", "filter:categorized")]


def arrange_menu():
    return [("Date", "arrange:date"), ("From", "arrange:from"), ("To", "arrange:to"), ("Categories", "arrange:categories"),
            ("Flag: Due Date", "arrange:flag"), ("Size", "arrange:size"), ("Subject", "arrange:subject"),
            ("Type", "arrange:type"), ("Attachments", "arrange:attach"), ("Importance", "arrange:importance"),
            None, ("Reverse Sort", "reverse-sort"), ("Show in Groups", "toggle-groups")]


def build_ribbon(win):
    B = Builder(win)
    r = win.ribbon
    na = lambda name: "not-available:" + name  # noqa: E731

    # ================================================================ Home
    t = r.building(Tab("Home", "H"))
    B.group(t, "New", [
        B.big("New Email", "p-new-email", "new-email", "N",
              menu=[("E-mail Message", "new-email", "p-new-email"), ("Meeting", "new-meeting", "p-meeting"),
                    ("Contact", "new-contact"), ("Task", "new-task"), None,
                    ("Folder...", "new-folder", "p-new-folder")],
              tip="New Email (Ctrl+N)"),
    ])
    B.group(t, "Delete", [
        [B.small("Ignore", "p-ignore", "ignore", "X", tip="Ignore Conversation"),
         B.small("Clean Up", "p-clean-up", None, "CU",
                 menu=[("Clean Up Conversation", "clean-up:conversation"), ("Clean Up Folder", "clean-up:folder")]),
         B.small("Junk", "p-junk", None, "J",
                 menu=[("Block Sender", "block-sender", "p-block"), ("Never Block Sender", "never-block"),
                       ("Not Junk", "not-junk", "p-not-junk"), None, ("Junk E-mail Options...", "junk-options")])],
        B.big("Delete", "p-delete", "delete", "D", tip="Delete (Ctrl+D)"),
        B.big("Archive", "p-archive", "archive", "EA", tip="Archive (Backspace)"),
    ])
    B.group(t, "Respond", [
        B.big("Reply", "p-reply", "reply", "RP", tip="Reply (Ctrl+R)"),
        B.big("Reply All", "p-reply-all", "reply-all", "RA", tip="Reply All (Ctrl+Shift+R)"),
        B.big("Forward", "p-forward", "forward", "FW", tip="Forward (Ctrl+F)"),
        [B.small("More", "p-attach-item", None, "M",
                 menu=[("Forward as Attachment", "forward-attachment"), ("Reply with Meeting", "reply-with-meeting")])],
    ])
    B.group(t, "Quick Steps", [
        B.big("Quick Steps", "p-quick-steps", None, "QS",
              menu=lambda: win.quick_steps_menu()),
    ])
    B.group(t, "Move", [
        B.big("Move", "p-move", None, "MV", menu=lambda: move_menu(win), tip="Move to Folder (Ctrl+Shift+V)"),
        [B.small("Rules", "p-rules", None, "RR",
                 menu=[("Always Move Messages From This Sender...", "rule-from"), None, ("Manage Rules && Alerts...",
                                                                                         "rules")])],
    ])
    B.group(t, "Tags", [
        [B.small("Unread/ Read", "p-unread", "toggle-read", "W", tip="Mark Unread/Read (Ctrl+Q / Ctrl+U)"),
         B.small("Categorize", "p-categorize", None, "G", menu=categories_menu),
         B.small("Follow Up", "p-flag", "flag:toggle", "U", menu=follow_up_menu(), tip="Follow Up (Insert)")],
    ])
    B.group(t, "Find", [
        [B.small("Search People", "p-search-people", "search-people", "FP"),
         B.small("Address Book", "p-address-book", "address-book", "AB", tip="Address Book (Ctrl+Shift+B)"),
         B.small("Filter Email", "p-filter", None, "L", menu=filter_menu())],
    ])
    B.group(t, "Send/Receive", [
        B.big("Send/Receive All Folders", "p-send-receive", "send-receive", "SR", tip="Send/Receive All Folders (F9)"),
    ])

    # ================================================================ Send / Receive
    r.add_tab(t)

    t = r.building(Tab("Send / Receive", "S"))
    B.group(t, "Send & Receive", [
        B.big("Send/Receive All Folders", "p-send-receive", "send-receive", "A", tip="Send/Receive All Folders (F9)"),
        [B.small("Update Folder", "p-update-folder", "update-folder", "F", tip="Update Folder (Shift+F9)"),
         B.small("Send All", "p-send-all", "send-all", "SA"),
         B.small("Send/Receive Groups", "p-send-receive", None, "G",
                 menu=lambda: [(a["name"] or a["email"], "send-receive:%d" % a["id"]) for a in win.store.accounts()
                               if a["kind"] != "local"])],
    ])
    B.group(t, "Download", [
        B.big("Show Progress", "p-progress", "show-progress", "SP"),
        B.big("Cancel All", "p-cancel-all", "cancel-all", "C"),
    ])
    win.offline_button = B.big("Work Offline", "p-offline", "work-offline", "W")
    B.group(t, "Preferences", [win.offline_button])

    # ================================================================ Folder
    r.add_tab(t)

    t = r.building(Tab("Folder", "O"))
    B.group(t, "New", [B.big("New Folder", "p-new-folder", "new-folder", "N", tip="New Folder (Ctrl+Shift+E)"),
                       B.big("New Search Folder", "p-filter", "new-search-folder", "S")])
    B.group(t, "Actions", [
        [B.small("Rename Folder", "p-rename-folder", "rename-folder", "RN"),
         B.small("Copy Folder", "p-folder", "copy-folder", "CF"),
         B.small("Move Folder", "p-move", "move-folder", "MF")],
        [B.small("Delete Folder", "p-delete-folder", "delete-folder", "D"),
         B.small("Mark All as Read", "p-mark-all-read", "mark-all-read", "MA"),
         B.small("Update Folder", "p-update-folder", "update-folder", "U")],
    ])
    B.group(t, "Clean Up", [
        [B.small("Clean Up Folder", "p-clean-up", "clean-up:folder", "CU"),
         B.small("Delete All", "p-delete", "delete-all", "DA")],
    ])
    B.group(t, "Properties", [B.big("Folder Properties", "p-properties", "folder-properties", "FP")])

    # ================================================================ View
    r.add_tab(t)

    t = r.building(Tab("View", "V"))
    B.group(t, "Current View", [
        B.big("Change View", "p-change-view", None, "CV",
              menu=[("Compact", "view-mode:compact"), ("Single", "view-mode:single"), ("Preview", "view-mode:preview")]),
        [B.small("Reset View", "p-change-view", "reset-view", "X")],
    ])
    win.conv_check = CheckControl(r, "Show as Conversations", "toggle-conversations", state="conversations", keytip="CO")
    B.group(t, "Messages", [[win.conv_check]])
    B.group(t, "Arrangement", [
        B.big("Arrange By", "p-arrange", None, "AB", menu=arrange_menu()),
        [B.small("Reverse Sort", "p-reverse", "reverse-sort", "RS"),
         B.small("Message Preview", "p-change-view", None, "MP",
                 menu=[("Off", "preview:0"), ("1 Line", "preview:1"), ("2 Lines", "preview:2"), ("3 Lines", "preview:3")])],
    ])
    B.group(t, "Layout", [
        B.big("Folder Pane", "p-folder-pane", None, "F",
              menu=[("Normal", "folder-pane:normal"), ("Minimized", "folder-pane:min"), ("Off", "folder-pane:off")]),
        B.big("Reading Pane", "p-reading-pane", None, "PN",
              menu=[("Right", "reading-pane:right"), ("Bottom", "reading-pane:bottom"), ("Off", "reading-pane:off"), None,
                    ("Options...", "options:reading")]),
    ])
    B.group(t, "Window", [
        [B.small("Open in New Window", "p-open-file", "open-item", "O"),
         B.small("Zoom", "p-zoom", "zoom", "Q"),
         B.small("Close All Items", "p-cancel-all", "close-items", "CA")],
    ])

    # ================================================================ Help
    r.add_tab(t)

    t = r.building(Tab("Help", "Y"))
    B.group(t, "Help", [
        B.big("Help", "p-help", "help", "H", tip="Help (F1)"),
        B.big("Keyboard Shortcuts", "p-options", "shortcuts", "K"),
        B.big("About", "p-about", "about", "A"),
    ])
    r.add_tab(t)
    r.select(r.tab_by_name("Home"))
