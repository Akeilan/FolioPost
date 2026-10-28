"""The parts of the document's UNO interface the app's dialogs use (styles,
undo contexts, the view cursor, document settings), answered by Folio's own
engine, so those dialogs work unchanged with it."""
from .uno_props import CursorProps, StyleProps

FAMILY_KIND = {"ParagraphStyles": "paragraph", "CharacterStyles": "character"}


def _maps():
    from ..actions import engine_style, word_style
    return engine_style, word_style


class NativeStyle:
    """One style (com.sun.star.style.Style as the dialogs use it)."""

    def __init__(self, model, sid):
        object.__setattr__(self, "_m", model)
        object.__setattr__(self, "sid", sid)
        object.__setattr__(self, "_props", StyleProps(model.eng, sid))

    def _info(self):
        return self._m.info(self.sid)

    @property
    def Name(self):
        engine_style, _w = _maps()
        return engine_style(self._info()[1])

    @property
    def DisplayName(self):
        return self._info()[1]

    def getName(self):
        return self.Name

    def setName(self, n):
        self._m.eng.ed.style_set_meta(self.sid, name=n)
        self._m.changed()

    def isUserDefined(self):
        return self._info()[5]

    def isInUse(self):
        return True

    def __getattr__(self, k):
        if k == "ParentStyle":
            b = self._info()[3]
            return self._m.engine_name(b) if b else ""
        if k == "FollowStyle":
            n = self._info()[4] or self.sid
            return self._m.engine_name(n)
        if k == "IsAutoUpdate":
            return self._info()[6]
        return getattr(object.__getattribute__(self, "_props"), k)

    def __setattr__(self, k, v):
        ed = self._m.eng.ed
        if k == "ParentStyle":
            ed.style_set_meta(self.sid, based_on=self._m.id_of(v) if v else "")
        elif k == "FollowStyle":
            ed.style_set_meta(self.sid, next=self._m.id_of(v) or self.sid)
        elif k == "IsAutoUpdate":
            ed.style_set_meta(self.sid, auto=bool(v))
        else:
            setattr(self._props, k, v)
            return
        self._m.changed()

    def getPropertyValue(self, k):
        return getattr(self, k)

    def setPropertyValue(self, k, v):
        setattr(self, k, v)


class _NewStyle:
    """What createInstance hands back: a style not yet in a family."""

    def __init__(self, kind):
        self.kind = kind


class NativeFamily:
    def __init__(self, model, fam):
        self.m = model
        self.fam = fam
        self.kind = FAMILY_KIND.get(fam, "")

    def _styles(self):
        return [s for s in self.m.styles() if s[2] == self.kind]

    def getElementNames(self):
        return tuple(self.m.engine_name(s[0]) for s in self._styles())

    def getCount(self):
        return len(self._styles())

    def hasByName(self, name):
        return self._find(name) is not None

    def _find(self, name):
        _e, word_style = _maps()
        w = word_style(name).lower()
        for s in self._styles():
            if s[0] == name or s[1].lower() == w or s[1].lower() == name.lower():
                return s[0]
        return None

    def getByName(self, name):
        sid = self._find(name)
        if sid is None:
            raise KeyError(name)
        return NativeStyle(self.m, sid)

    def insertByName(self, name, st):
        _e, word_style = _maps()
        self.m.eng.ed.create_style(word_style(name), self.kind, "Normal" if self.kind == "paragraph"
                                   else None)
        self.m.changed()


class NativeFamilies:
    def __init__(self, model):
        self.m = model

    def getByName(self, fam):
        return NativeFamily(self.m, fam)

    def hasByName(self, fam):
        return fam in FAMILY_KIND

    def getElementNames(self):
        return tuple(FAMILY_KIND)


class _Undo:
    def __init__(self, model):
        self.m = model
        self.depth = 0

    def enterUndoContext(self, name):
        if self.depth == 0:
            self.m.eng.ed.begin_group(name)
        self.depth += 1

    def leaveUndoContext(self):
        self.depth = max(0, self.depth - 1)
        if self.depth == 0:
            self.m.eng.ed.end_group()
            self.m.changed()

    def getAllUndoActionTitles(self):
        n = self.m.eng.ed.state().get("undo_name")
        return (n,) if n else ()

    def isRedoPossible(self):
        return self.m.eng.ed.can_redo()


class _Controller:
    def __init__(self, model):
        self.m = model

    def getViewCursor(self):
        return CursorProps(self.m.eng)

    def getSelection(self):
        return None


class _UserProps:
    """Document settings the app keeps (style gallery, theme colours...)."""

    def __init__(self, store):
        self.store = store

    def getPropertyValue(self, k):
        if k not in self.store:
            raise KeyError(k)
        return self.store[k]

    def setPropertyValue(self, k, v):
        self.store[k] = v

    def addProperty(self, k, attrs, v):
        self.store[k] = v

    def getPropertySetInfo(self):
        store = self.store

        class Info:
            def hasPropertyByName(self, k):
                return k in store
        return Info()


class _DocProps:
    def __init__(self, store):
        self.ud = _UserProps(store)

    def getUserDefinedProperties(self):
        return self.ud


class NativeModel:
    """Stands in for the UNO document."""

    def __init__(self, engine):
        self.eng = engine
        if not hasattr(engine, "doc_settings"):
            engine.doc_settings = {}

    def __bool__(self):
        return True

    # ---------------------------------------------------------- helpers
    def styles(self):
        return self.eng.ed.style_list()

    def info(self, sid):
        for s in self.styles():
            if s[0] == sid:
                return s
        return (sid, sid, "", "", "", True, False, False)

    def engine_name(self, sid):
        engine_style, _w = _maps()
        return engine_style(self.info(sid)[1])

    def id_of(self, name):
        _e, word_style = _maps()
        w = word_style(name).lower()
        for s in self.styles():
            if s[0] == name or s[1].lower() == w:
                return s[0]
        return ""

    def changed(self):
        self.eng.view.after_edit()

    # ---------------------------------------------------------- UNO
    def getStyleFamilies(self):
        return NativeFamilies(self)

    def getUndoManager(self):
        u = getattr(self.eng, "_uno_undo", None)
        if u is None:
            u = self.eng._uno_undo = _Undo(self)
        return u

    def getCurrentController(self):
        return _Controller(self)

    def getDocumentProperties(self):
        from .docprops import DocumentProperties
        return DocumentProperties(self.eng.ed)

    def getText(self):
        from . import docops
        ed = self.eng.ed

        class T:
            def getString(self):
                # the body only, as the original's text (headers and footers aren't in it)
                return "\n".join(self.lines())

            def lines(self):
                return [t.replace("\ufffc", "") for t in self.eng_lines()]

            def eng_lines(self):
                return [ed.para_text_of(n) for k, n, _t in ed.body_blocks() if k == "p"]
        _ = docops
        return T()

    def createInstance(self, svc):
        return _NewStyle("character" if "Character" in svc else "paragraph")

    def __getattr__(self, k):
        raise AttributeError(k)
