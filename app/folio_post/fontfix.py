"""Same text height on Ubuntu 22.04 and 24.04 (Zorin 17 and 18).

The chrome font falls back to Carlito. The Carlito in 24.04 (fonts-crosextra-carlito 2023)
carries Calibri's tall line metrics, so every label is a third taller than on 22.04 (16 px
instead of 12 px at 9 pt): ribbons, status bars and dialogs grow. When that Carlito is the font
in use, labels get a line height of one em, which is what 22.04 draws. Nothing changes
anywhere else.

    from . import fontfix; fontfix.install()      # once, at startup, after the CSS is loaded

The canonical copy lives in folio-suite/shared; each app carries a copy.
"""
_ratio = None


def _measure(family="Segoe UI, Noto Sans, Open Sans, Ubuntu, sans-serif"):
    import gi
    gi.require_version("Pango", "1.0")
    gi.require_version("PangoCairo", "1.0")
    from gi.repository import Pango, PangoCairo
    fm = PangoCairo.FontMap.get_default()
    ctx = fm.create_context()
    desc = Pango.FontDescription(family + " 9")
    font = fm.load_font(ctx, desc)
    if font is None:
        return None, 1.0
    name = font.describe().get_family() or ""
    m = font.get_metrics(None)
    em = 9 * 96 / 72.0
    return name, (m.get_ascent() + m.get_descent()) / Pango.SCALE / em


def needed():
    global _ratio
    if _ratio is None:
        try:
            name, r = _measure()
            _ratio = r if name.lower().startswith("carlito") else 1.0
        except Exception:
            _ratio = 1.0
    return _ratio > 1.1


def fix_label(lab):
    from gi.repository import Gtk, Pango
    try:
        st = lab.get_style_context()
        fd = st.get_property("font", st.get_state())
        size = fd.get_size()
        if not size:
            return
        px = size / Pango.SCALE * (96 / 72.0) if not fd.get_size_is_absolute() else size / Pango.SCALE
        want = int(round(px)) * Pango.SCALE
        if getattr(lab, "_folio_lh", None) == want:
            return
        lab._folio_lh = want
        old = lab.get_attributes()
        attrs = Pango.AttrList()
        if old is not None:
            for a in old.get_attributes():
                if a.klass.type != Pango.AttrType.ABSOLUTE_LINE_HEIGHT:
                    attrs.insert(a.copy())
        attrs.insert(Pango.attr_line_height_new_absolute(want))
        lab.set_attributes(attrs)
    except Exception:
        pass


def install():
    """Hook every label the app makes (only when the tall Carlito is in use)."""
    if not needed():
        return False
    from gi.repository import GObject, Gtk

    def hook(w, *a):
        if isinstance(w, Gtk.Label):
            fix_label(w)
        return True
    # style-updated comes when a label joins a window and whenever its font changes, before it
    # is measured (labels on ribbon tabs not shown yet are measured too, but never realized)
    GObject.add_emission_hook(Gtk.Label, "style-updated", hook)
    return True
