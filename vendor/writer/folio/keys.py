"""Keyboard: the full binding table, handled by the app before the document
sees the key. Keys not listed here: plain typing and navigation go to the
document; any other Ctrl/Alt combination is swallowed so nothing unexpected
happens."""
from gi.repository import Gdk

C, S, A = "ctrl", "shift", "alt"


def key(spec):
    """'ctrl+shift+a' -> (mods frozenset, keyval-name lowercased)."""
    parts = spec.split("+")
    name = parts[-1]
    mods = frozenset(p for p in parts[:-1])
    return mods, name.lower()


# (key spec, action). Actions: '.uno:...' engine command, (cmd, args),
# or an app action name (see actions.py).
BINDINGS = [
    # ---- file
    ("ctrl+n", "new"), ("ctrl+o", "backstage-open"), ("ctrl+F12", "open-dialog"),
    ("ctrl+s", "save"), ("shift+F12", "save"), ("F12", "save-as"),
    ("ctrl+p", "backstage-print"), ("ctrl+shift+F12", "backstage-print"),
    ("ctrl+F2", "backstage-print"), ("alt+ctrl+i", "backstage-print"),
    ("ctrl+w", "close"), ("ctrl+F4", "close"), ("alt+F4", "close"),
    # ---- edit
    ("ctrl+z", "undo"), ("alt+BackSpace", "undo"), ("ctrl+y", "redo-repeat"),
    ("F4", "repeat"), ("ctrl+x", "cut"), ("shift+Delete", "cut"),
    ("ctrl+c", "copy"), ("ctrl+Insert", "copy"), ("ctrl+v", "paste"),
    ("shift+Insert", "paste"), ("ctrl+alt+v", "paste-special"),
    ("ctrl+shift+c", "copy-format"), ("ctrl+shift+v", "paste-format"),
    ("ctrl+a", ".uno:SelectAll"), ("ctrl+f", "find-pane"), ("ctrl+h", "replace"),
    ("ctrl+g", "goto"), ("F5", "goto"), ("shift+F5", "go-back"),
    ("ctrl+BackSpace", ".uno:DelToStartOfWord"), ("ctrl+Delete", ".uno:DelToEndOfWord"),
    ("F8", "extend-selection"),
    # ---- character
    ("ctrl+b", ".uno:Bold"), ("ctrl+shift+b", ".uno:Bold"),
    ("ctrl+i", ".uno:Italic"), ("ctrl+shift+i", ".uno:Italic"),
    ("ctrl+u", ".uno:Underline"), ("ctrl+shift+d", "double-underline"),
    ("ctrl+shift+w", "word-underline"), ("ctrl+shift+a", "all-caps"),
    ("ctrl+shift+k", "small-caps"), ("ctrl+shift+h", "hidden"),
    ("ctrl+equal", ".uno:SubScript"), ("ctrl+shift+plus", ".uno:SuperScript"),
    ("ctrl+shift+equal", ".uno:SuperScript"),
    ("ctrl+shift+greater", "grow-font"), ("ctrl+shift+period", "grow-font"),
    ("ctrl+shift+less", "shrink-font"), ("ctrl+shift+comma", "shrink-font"),
    ("ctrl+bracketright", "grow-font-1"), ("ctrl+bracketleft", "shrink-font-1"),
    ("ctrl+d", "font-dialog"), ("ctrl+shift+f", "font-dialog"), ("ctrl+shift+p", "font-dialog"),
    ("ctrl+F3", "spike"), ("ctrl+shift+F3", "spike-paste"), ("alt+F8", "view-macros"),
    ("shift+F3", "change-case-cycle"), ("ctrl+space", "clear-char-format"),
    ("ctrl+shift+z", "clear-char-format"), ("ctrl+alt+h", "highlight"),
    # ---- paragraph
    ("ctrl+l", ".uno:LeftPara"), ("ctrl+e", ".uno:CenterPara"), ("ctrl+r", ".uno:RightPara"),
    ("ctrl+j", ".uno:JustifyPara"), ("ctrl+1", "spacing-1"), ("ctrl+2", "spacing-2"),
    ("ctrl+5", "spacing-15"), ("ctrl+0", "space-before-toggle"),
    ("ctrl+m", "indent"), ("ctrl+shift+m", "outdent"), ("ctrl+t", "hanging-indent"),
    ("ctrl+shift+t", "unhang"), ("ctrl+q", "reset-paragraph"),
    ("ctrl+shift+8", ".uno:ControlCodes"), ("ctrl+shift+asterisk", ".uno:ControlCodes"),
    ("ctrl+shift+n", ("style", "Normal")),
    ("ctrl+alt+1", ("style", "Heading 1")), ("ctrl+alt+2", ("style", "Heading 2")),
    ("ctrl+alt+3", ("style", "Heading 3")), ("ctrl+shift+l", ("style", "List Bullet")),
    ("ctrl+shift+s", "apply-styles"), ("ctrl+alt+shift+s", "styles-pane"),
    ("alt+shift+Left", "promote"), ("alt+shift+Right", "demote"),
    ("alt+shift+Up", "move-up"), ("alt+shift+Down", "move-down"), ("alt+x", "unicode-toggle"),
    ("ctrl+F9", "field-braces"),
    # ---- insert
    ("ctrl+Return", ".uno:InsertPagebreak"), ("ctrl+shift+Return", ".uno:InsertColumnBreak"),
    ("shift+Return", ".uno:InsertLinebreak"), ("ctrl+shift+space", "nbsp"),
    ("ctrl+minus", "soft-hyphen"), ("ctrl+shift+underscore", "nb-hyphen"),
    ("ctrl+alt+space", "read-aloud"), ("alt+shift+i", "mark-citation"),
    ("ctrl+k", "hyperlink"), ("ctrl+alt+m", "comment"), ("ctrl+alt+f", ".uno:InsertFootnote"),
    ("ctrl+alt+d", ".uno:InsertEndnote"), ("ctrl+shift+F5", "bookmark"),
    ("alt+shift+d", ("model", "insert_field", "date", False, "M/D/YYYY")),
    ("alt+shift+t", ("model", "insert_field", "time", False, "H:MM AM/PM")),
    ("alt+shift+p", ("model", "insert_field", "page")), ("alt+equal", "equation"),
    ("alt+shift+x", "mark-entry"), ("F11", ("model", "goto_field", True)),
    ("shift+F11", ("model", "goto_field", False)), ("ctrl+shift+F9", ("model", "unlink_fields")),
    ("ctrl+F11", ("model", "lock_fields", True)), ("ctrl+shift+F11", ("model", "lock_fields", False)),
    ("alt+F9", ("model", "toggle_field_codes")), ("shift+F9", ("model", "toggle_field_codes")),
    ("ctrl+alt+c", ("text", "©")), ("ctrl+alt+r", ("text", "®")),
    ("ctrl+alt+t", ("text", "™")), ("ctrl+alt+period", ("text", "…")),
    ("ctrl+alt+minus", ("text", "—")), ("ctrl+alt+KP_Subtract", ("text", "—")),
    ("ctrl+KP_Subtract", ("text", "–")), ("ctrl+alt+e", ("text", "€")),
    # ---- review / tools
    ("F7", "spelling"), ("shift+F7", "thesaurus"), ("ctrl+shift+g", "word-count"),
    ("ctrl+shift+e", ".uno:TrackChanges"), ("alt+q", "search-box"),
    ("shift+F10", "context-menu"), ("Menu", "context-menu"),
    ("F6", "next-region"), ("shift+F6", "prev-region"),
    ("ctrl+alt+s", "split"), ("ctrl+F6", "next-window"), ("ctrl+shift+F6", "prev-window"),
    ("ctrl+F1", "toggle-ribbon"), ("F1", "help"), ("F9", "update-fields"),
    ("ctrl+alt+shift+z", "go-back"),
    # ---- view
    ("ctrl+alt+p", "print-layout"), ("ctrl+alt+o", "outline-view"), ("ctrl+alt+n", "draft-view"),
    ("ctrl+plus", "zoom-in"), ("ctrl+KP_Add", "zoom-in"),
    ("ctrl+alt+minus+zoom", "zoom-out"),
]

# Keys handed to the document unchanged (navigation & editing).
PASSTHROUGH = {
    "left", "right", "up", "down", "home", "end", "page_up", "page_down", "prior", "next",
    "backspace", "delete", "return", "kp_enter", "tab", "iso_left_tab", "escape",
    "insert", "kp_home", "kp_end", "kp_left", "kp_right", "kp_up", "kp_down",
    "kp_page_up", "kp_page_down", "kp_prior", "kp_next", "kp_delete", "kp_insert",
}


def _norm_name(keyval):
    name = Gdk.keyval_name(Gdk.keyval_to_lower(keyval)) or ""
    return name.lower()


class _StyleAction(tuple):
    user = True


class _SymbolAction(tuple):
    user = True


class KeyMap:
    def __init__(self):
        self.table = {}
        for spec, action in BINDINGS:
            if spec.endswith("+zoom"):
                continue
            self.table[key(spec)] = action

    user = {}

    def set_user_keys(self, table):
        """User shortcuts for ribbon commands ({'ctrl+alt+q': action})."""
        self.user = {key(spec): (tuple(act) if isinstance(act, list) else act)
                     for spec, act in (table or {}).items()}

    def set_style_keys(self, mapping):
        """User shortcuts that apply a style ({'ctrl+alt+1': 'Heading 1'})."""
        for k in [k for k, v in self.table.items() if isinstance(v, tuple) and
                  v and v[0] == "style" and getattr(v, "user", False)]:
            del self.table[k]
        for spec, name in (mapping or {}).items():
            self.table[key(spec)] = _StyleAction(("style", name))

    def set_symbol_keys(self, mapping):
        """User shortcuts that type a symbol ({'alt+ctrl+c': '©'})."""
        for k in [k for k, v in self.table.items() if isinstance(v, _SymbolAction)]:
            del self.table[k]
        for spec, ch in (mapping or {}).items():
            self.table[key(spec)] = _SymbolAction(("text", ch))

    def lookup(self, event):
        state = event.state
        mods = set()
        if state & Gdk.ModifierType.CONTROL_MASK:
            mods.add("ctrl")
        if state & Gdk.ModifierType.SHIFT_MASK:
            mods.add("shift")
        if state & Gdk.ModifierType.MOD1_MASK:
            mods.add("alt")
        keyval = event.keyval
        name = _norm_name(keyval)
        # shifted punctuation: try both the shifted symbol and the base key
        names = [name]
        raw = (Gdk.keyval_name(keyval) or "").lower()
        if raw and raw not in names:
            names.append(raw)
        # map hardware key to its unshifted symbol (e.g. ctrl+shift+> on '.')
        try:
            keymap = Gdk.Keymap.get_for_display(Gdk.Display.get_default())
            ok, keys = keymap.get_entries_for_keyval(keyval)
            if ok and keys:
                base = keymap.lookup_key(Gdk.KeymapKey(keycode=keys[0].keycode, group=0, level=0))
                bname = (Gdk.keyval_name(base) or "").lower()
                if bname and bname not in names:
                    names.append(bname)
        except Exception:
            pass
        fm = frozenset(mods)
        for n in names:
            act = self.user.get((fm, n))
            if act is not None:
                return act, mods, name
        for n in names:
            act = self.table.get((fm, n))
            if act is not None:
                return act, mods, name
        return None, mods, name
