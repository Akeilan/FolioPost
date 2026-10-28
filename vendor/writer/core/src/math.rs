//! Office Math (OMML): equations laid out with an OpenType MATH font, the
//! way the original sets them (TeX's rules, driven by the font's MATH
//! constants, glyph variants and assemblies), and drawn as glyphs and rules.

use crate::fonts::{Font, FontCache};
use crate::xml::{NodeId, XmlDoc};
use rustybuzz::ttf_parser;
use std::cell::RefCell;
use std::collections::HashMap;
use std::sync::Arc;

/// Something a laid-out equation draws. Coordinates are points from the
/// box origin (the left end of its baseline), y downwards.
#[derive(Clone, Debug)]
pub enum Draw {
    Glyph { font: Arc<Font>, gid: u16, x: f64, y: f64, size: f64, color: u32 },
    /// a filled rectangle (fraction bars, radical overbars); y is its top
    Rule { x: f64, y: f64, w: f64, h: f64, color: u32 },
    /// a stroked line (box borders, strikes)
    Line { x0: f64, y0: f64, x1: f64, y1: f64, w: f64, color: u32 },
}

impl Draw {
    fn shifted(&self, dx: f64, dy: f64) -> Draw {
        match self {
            Draw::Glyph { font, gid, x, y, size, color } => {
                Draw::Glyph { font: font.clone(), gid: *gid, x: x + dx, y: y + dy, size: *size, color: *color }
            }
            Draw::Rule { x, y, w, h, color } => Draw::Rule { x: x + dx, y: y + dy, w: *w, h: *h, color: *color },
            Draw::Line { x0, y0, x1, y1, w, color } => {
                Draw::Line { x0: x0 + dx, y0: y0 + dy, x1: x1 + dx, y1: y1 + dy, w: *w, color: *color }
            }
        }
    }
}

/// Spacing classes (TeX's atom types).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Class {
    Ord,
    Op,
    Bin,
    Rel,
    Open,
    Close,
    Punct,
    Inner,
}

/// A laid-out piece of an equation.
#[derive(Clone, Debug)]
pub struct MBox {
    pub w: f64,
    pub asc: f64,
    pub desc: f64,
    pub draws: Vec<Draw>,
    /// italic correction of its last glyph
    pub italic: f64,
    pub class: Class,
    /// a single character (scripts and accents treat these specially)
    pub single: Option<(Arc<Font>, u16)>,
}

impl MBox {
    fn empty() -> MBox {
        MBox { w: 0.0, asc: 0.0, desc: 0.0, draws: Vec::new(), italic: 0.0, class: Class::Ord, single: None }
    }
    fn add(&mut self, b: &MBox, dx: f64, dy: f64) {
        for d in &b.draws {
            self.draws.push(d.shifted(dx, dy));
        }
    }
    pub fn height(&self) -> f64 {
        self.asc + self.desc
    }
}

/// The MATH table constants (font units).
#[allow(dead_code)]
#[derive(Clone, Debug, Default)]
struct Consts {
    script_pct: f64,
    sscript_pct: f64,
    delim_min_h: f64,
    disp_op_min_h: f64,
    axis: f64,
    accent_base: f64,
    sub_down: f64,
    sub_top_max: f64,
    sub_drop_min: f64,
    sup_up: f64,
    sup_up_cramped: f64,
    sup_bottom_min: f64,
    sup_drop_max: f64,
    subsup_gap: f64,
    sup_bottom_max_sub: f64,
    space_after_script: f64,
    upper_gap: f64,
    upper_rise: f64,
    lower_gap: f64,
    lower_drop: f64,
    stack_top: f64,
    stack_top_d: f64,
    stack_bot: f64,
    stack_bot_d: f64,
    stack_gap: f64,
    stack_gap_d: f64,
    stretch_top: f64,
    stretch_bot: f64,
    stretch_gap_above: f64,
    stretch_gap_below: f64,
    num_up: f64,
    num_up_d: f64,
    den_down: f64,
    den_down_d: f64,
    num_gap: f64,
    num_gap_d: f64,
    frac_rule: f64,
    den_gap: f64,
    den_gap_d: f64,
    skew_hgap: f64,
    skew_vgap: f64,
    over_gap: f64,
    over_rule: f64,
    over_extra: f64,
    under_gap: f64,
    under_rule: f64,
    under_extra: f64,
    rad_gap: f64,
    rad_gap_d: f64,
    rad_rule: f64,
    rad_extra: f64,
    rad_kern_before: f64,
    rad_kern_after: f64,
    rad_raise_pct: f64,
    min_overlap: f64,
}

/// A math font and what its MATH table says.
#[allow(dead_code)]
pub struct MathFont {
    pub font: Arc<Font>,
    upem: f64,
    k: Consts,
    has_math: bool,
}

#[derive(Clone, Copy)]
struct Part {
    gid: u16,
    start: f64,
    end: f64,
    adv: f64,
    ext: bool,
}

impl MathFont {
    fn load(font: Arc<Font>) -> MathFont {
        let mut k = Consts::default();
        let mut upem = 1000.0;
        let mut has_math = false;
        if let Ok(face) = ttf_parser::Face::parse(font.data(), font.index) {
            upem = face.units_per_em() as f64;
            if let Some(c) = face.tables().math.and_then(|m| m.constants) {
                has_math = true;
                let v = |m: ttf_parser::math::MathValue| m.value as f64;
                k = Consts {
                    script_pct: c.script_percent_scale_down() as f64,
                    sscript_pct: c.script_script_percent_scale_down() as f64,
                    delim_min_h: c.delimited_sub_formula_min_height() as f64,
                    disp_op_min_h: c.display_operator_min_height() as f64,
                    axis: v(c.axis_height()),
                    accent_base: v(c.accent_base_height()),
                    sub_down: v(c.subscript_shift_down()),
                    sub_top_max: v(c.subscript_top_max()),
                    sub_drop_min: v(c.subscript_baseline_drop_min()),
                    sup_up: v(c.superscript_shift_up()),
                    sup_up_cramped: v(c.superscript_shift_up_cramped()),
                    sup_bottom_min: v(c.superscript_bottom_min()),
                    sup_drop_max: v(c.superscript_baseline_drop_max()),
                    subsup_gap: v(c.sub_superscript_gap_min()),
                    sup_bottom_max_sub: v(c.superscript_bottom_max_with_subscript()),
                    space_after_script: v(c.space_after_script()),
                    upper_gap: v(c.upper_limit_gap_min()),
                    upper_rise: v(c.upper_limit_baseline_rise_min()),
                    lower_gap: v(c.lower_limit_gap_min()),
                    lower_drop: v(c.lower_limit_baseline_drop_min()),
                    stack_top: v(c.stack_top_shift_up()),
                    stack_top_d: v(c.stack_top_display_style_shift_up()),
                    stack_bot: v(c.stack_bottom_shift_down()),
                    stack_bot_d: v(c.stack_bottom_display_style_shift_down()),
                    stack_gap: v(c.stack_gap_min()),
                    stack_gap_d: v(c.stack_display_style_gap_min()),
                    stretch_top: v(c.stretch_stack_top_shift_up()),
                    stretch_bot: v(c.stretch_stack_bottom_shift_down()),
                    stretch_gap_above: v(c.stretch_stack_gap_above_min()),
                    stretch_gap_below: v(c.stretch_stack_gap_below_min()),
                    num_up: v(c.fraction_numerator_shift_up()),
                    num_up_d: v(c.fraction_numerator_display_style_shift_up()),
                    den_down: v(c.fraction_denominator_shift_down()),
                    den_down_d: v(c.fraction_denominator_display_style_shift_down()),
                    num_gap: v(c.fraction_numerator_gap_min()),
                    num_gap_d: v(c.fraction_num_display_style_gap_min()),
                    frac_rule: v(c.fraction_rule_thickness()),
                    den_gap: v(c.fraction_denominator_gap_min()),
                    den_gap_d: v(c.fraction_denom_display_style_gap_min()),
                    skew_hgap: v(c.skewed_fraction_horizontal_gap()),
                    skew_vgap: v(c.skewed_fraction_vertical_gap()),
                    over_gap: v(c.overbar_vertical_gap()),
                    over_rule: v(c.overbar_rule_thickness()),
                    over_extra: v(c.overbar_extra_ascender()),
                    under_gap: v(c.underbar_vertical_gap()),
                    under_rule: v(c.underbar_rule_thickness()),
                    under_extra: v(c.underbar_extra_descender()),
                    rad_gap: v(c.radical_vertical_gap()),
                    rad_gap_d: v(c.radical_display_style_vertical_gap()),
                    rad_rule: v(c.radical_rule_thickness()),
                    rad_extra: v(c.radical_extra_ascender()),
                    rad_kern_before: v(c.radical_kern_before_degree()),
                    rad_kern_after: v(c.radical_kern_after_degree()),
                    rad_raise_pct: c.radical_degree_bottom_raise_percent() as f64,
                    min_overlap: 0.0,
                };
                if let Some(vs) = face.tables().math.and_then(|m| m.variants) {
                    k.min_overlap = vs.min_connector_overlap as f64;
                }
            }
        }
        if !has_math {
            // TeX-like defaults relative to a 1000 unit em
            let e = upem / 1000.0;
            k = Consts {
                script_pct: 70.0, sscript_pct: 50.0, delim_min_h: 1300.0 * e, disp_op_min_h: 1300.0 * e,
                axis: 250.0 * e, accent_base: 450.0 * e, sub_down: 200.0 * e, sub_top_max: 350.0 * e,
                sub_drop_min: 50.0 * e, sup_up: 360.0 * e, sup_up_cramped: 290.0 * e, sup_bottom_min: 110.0 * e,
                sup_drop_max: 380.0 * e, subsup_gap: 160.0 * e, sup_bottom_max_sub: 350.0 * e,
                space_after_script: 40.0 * e, upper_gap: 100.0 * e, upper_rise: 300.0 * e, lower_gap: 100.0 * e,
                lower_drop: 600.0 * e, stack_top: 450.0 * e, stack_top_d: 680.0 * e, stack_bot: 350.0 * e,
                stack_bot_d: 680.0 * e, stack_gap: 120.0 * e, stack_gap_d: 280.0 * e, stretch_top: 200.0 * e,
                stretch_bot: 600.0 * e, stretch_gap_above: 100.0 * e, stretch_gap_below: 100.0 * e,
                num_up: 400.0 * e, num_up_d: 680.0 * e, den_down: 350.0 * e, den_down_d: 680.0 * e,
                num_gap: 40.0 * e, num_gap_d: 120.0 * e, frac_rule: 40.0 * e, den_gap: 40.0 * e,
                den_gap_d: 120.0 * e, skew_hgap: 350.0 * e, skew_vgap: 100.0 * e, over_gap: 120.0 * e,
                over_rule: 40.0 * e, over_extra: 40.0 * e, under_gap: 120.0 * e, under_rule: 40.0 * e,
                under_extra: 40.0 * e, rad_gap: 50.0 * e, rad_gap_d: 150.0 * e, rad_rule: 40.0 * e,
                rad_extra: 40.0 * e, rad_kern_before: 280.0 * e, rad_kern_after: -550.0 * e,
                rad_raise_pct: 60.0, min_overlap: 20.0 * e,
            };
        }
        MathFont { font, upem, k, has_math }
    }

    fn face(&self) -> Option<ttf_parser::Face<'_>> {
        ttf_parser::Face::parse(self.font.data(), self.font.index).ok()
    }

    fn gid(&self, ch: char) -> Option<u16> {
        self.face()?.glyph_index(ch).map(|g| g.0).filter(|&g| g != 0)
    }

    fn adv(&self, gid: u16) -> f64 {
        self.face().and_then(|f| f.glyph_hor_advance(ttf_parser::GlyphId(gid))).unwrap_or(0) as f64
    }

    /// (ymin, ymax) of the glyph's ink.
    fn ybounds(&self, gid: u16) -> (f64, f64) {
        self.face()
            .and_then(|f| f.glyph_bounding_box(ttf_parser::GlyphId(gid)))
            .map(|b| (b.y_min as f64, b.y_max as f64))
            .unwrap_or((0.0, 0.0))
    }

    fn italic(&self, gid: u16) -> f64 {
        self.face()
            .and_then(|f| f.tables().math)
            .and_then(|m| m.glyph_info)
            .and_then(|gi| gi.italic_corrections)
            .and_then(|ic| ic.get(ttf_parser::GlyphId(gid)))
            .map(|v| v.value as f64)
            .unwrap_or(0.0)
    }

    fn top_accent(&self, gid: u16) -> Option<f64> {
        self.face()
            .and_then(|f| f.tables().math)
            .and_then(|m| m.glyph_info)
            .and_then(|gi| gi.top_accent_attachments)
            .and_then(|ta| ta.get(ttf_parser::GlyphId(gid)))
            .map(|v| v.value as f64)
    }

    /// Bigger versions of a glyph (vertical or horizontal) and its assembly.
    fn construction(&self, gid: u16, vertical: bool) -> (Vec<(u16, f64)>, Option<Vec<Part>>) {
        let Some(face) = self.face() else { return (Vec::new(), None) };
        let Some(vs) = face.tables().math.and_then(|m| m.variants) else { return (Vec::new(), None) };
        let cons = if vertical { vs.vertical_constructions } else { vs.horizontal_constructions };
        let Some(c) = cons.get(ttf_parser::GlyphId(gid)) else { return (Vec::new(), None) };
        let variants = c.variants.into_iter().map(|v| (v.variant_glyph.0, v.advance_measurement as f64)).collect();
        let asm = c.assembly.map(|a| {
            a.parts
                .into_iter()
                .map(|p| Part {
                    gid: p.glyph_id.0,
                    start: p.start_connector_length as f64,
                    end: p.end_connector_length as f64,
                    adv: p.full_advance as f64,
                    ext: p.part_flags.extender(),
                })
                .collect()
        });
        (variants, asm)
    }
}

thread_local! {
    static MATH_FONTS: RefCell<HashMap<usize, Arc<MathFont>>> = RefCell::new(HashMap::new());
}

/// Families tried for equations: the document's math font when it is
/// installed, then OpenType MATH fonts.
const MATH_FAMILIES: &[&str] = &["Cambria Math", "STIX Two Math", "Latin Modern Math", "DejaVu Math TeX Gyre",
                                 "TeX Gyre Termes Math", "Libertinus Math"];

pub fn math_font(fonts: &mut FontCache, wanted: Option<&str>) -> Arc<MathFont> {
    let mut names: Vec<&str> = Vec::new();
    if let Some(w) = wanted {
        names.push(w);
    }
    names.extend(MATH_FAMILIES.iter().copied());
    let fam = names.into_iter().find(|n| fonts.has_family(n)).unwrap_or("Cambria Math");
    let font = fonts.get(fam, false, false);
    MATH_FONTS.with(|m| {
        m.borrow_mut().entry(font.id).or_insert_with(|| Arc::new(MathFont::load(font.clone()))).clone()
    })
}

// ------------------------------------------------------------- characters
fn class_of(c: char) -> Class {
    match c {
        '=' | '<' | '>' | '≤' | '≥' | '≠' | '≈' | '≡' | '≅' | '∼' | '≃' | '∝' | '→' | '←' | '↔' | '⇒' | '⇐'
        | '⇔' | '↦' | '∈' | '∉' | '∋' | '⊂' | '⊃' | '⊆' | '⊇' | '⊄' | '≪' | '≫' | '≺' | '≻' | '⊥' | '∥'
        | '∣' | '≜' | '≝' | '≐' | '≔' | ':' | '⟶' | '⟹' | '⟵' | '⟷' | '↑' | '↓' | '≲' | '≳' | '∶' | '⊢'
        | '⊨' | '≦' | '≧' | '⩽' | '⩾' | '≯' | '≮' | '∌' | '⊊' | '⊋' | '⇌' | '⇄' | '↗' | '↘' | '≍' | '≑' => {
            Class::Rel
        }
        '+' | '−' | '-' | '±' | '∓' | '×' | '÷' | '·' | '⋅' | '∗' | '∘' | '∙' | '⊕' | '⊗' | '⊖' | '∪' | '∩'
        | '∧' | '∨' | '⊙' | '∖' | '†' | '‡' | '⋆' | '⊎' | '⊓' | '⊔' | '⊲' | '⊳' | '≀' | '⨯' | '⊘' | '⋄' => {
            Class::Bin
        }
        '(' | '[' | '{' | '⟨' | '⌈' | '⌊' | '⟦' | '〈' => Class::Open,
        ')' | ']' | '}' | '⟩' | '⌉' | '⌋' | '⟧' | '〉' | '!' => Class::Close,
        ',' | ';' => Class::Punct,
        '∑' | '∏' | '∐' | '∫' | '∬' | '∭' | '∮' | '∯' | '∰' | '⋃' | '⋂' | '⋁' | '⋀' | '⨁' | '⨂' | '⨀' => Class::Op,
        _ => Class::Ord,
    }
}

/// Spacing between two atoms, in 1/18 em (TeX's table; in brackets: only
/// in display and text styles).
fn space_between(a: Class, b: Class, script: bool) -> f64 {
    use Class::*;
    // (n, only_big)
    let (n, big) = match (a, b) {
        (Ord, Op) | (Op, Ord) | (Op, Op) | (Close, Op) | (Inner, Op) => (3, false),
        (Ord, Bin) | (Bin, Ord) | (Bin, Op) | (Bin, Open) | (Bin, Inner) | (Close, Bin) | (Inner, Bin) => (4, true),
        (Ord, Rel) | (Op, Rel) | (Rel, Ord) | (Rel, Op) | (Rel, Open) | (Rel, Inner) | (Close, Rel)
        | (Inner, Rel) => (5, true),
        (Ord, Inner) | (Op, Inner) | (Close, Inner) | (Inner, Ord) | (Inner, Open) | (Inner, Punct)
        | (Inner, Inner) | (Punct, Inner) => (3, true),
        (Punct, Ord) | (Punct, Op) | (Punct, Rel) | (Punct, Open) | (Punct, Close) | (Punct, Punct) => (3, true),
        _ => (0, false),
    };
    if big && script {
        0.0
    } else {
        n as f64
    }
}

/// Mathematical alphanumeric symbols: a letter in a style.
fn styled(c: char, italic: bool, bold: bool, scr: &str) -> char {
    let off = |base: u32, from: char| char::from_u32(base + (c as u32 - from as u32));
    let latin_upper = c.is_ascii_uppercase();
    let latin_lower = c.is_ascii_lowercase();
    let digit = c.is_ascii_digit();
    let exc = |table: &[(char, u32)]| table.iter().find(|(k, _)| *k == c).and_then(|(_, v)| char::from_u32(*v));
    let r = match scr {
        "script" if latin_upper || latin_lower => {
            if let Some(e) = exc(&[('B', 0x212C), ('E', 0x2130), ('F', 0x2131), ('H', 0x210B), ('I', 0x2110),
                                  ('L', 0x2112), ('M', 0x2133), ('R', 0x211B), ('e', 0x212F), ('g', 0x210A),
                                  ('o', 0x2134)]) {
                Some(e)
            } else if bold {
                if latin_upper { off(0x1D4D0, 'A') } else { off(0x1D4EA, 'a') }
            } else if latin_upper {
                off(0x1D49C, 'A')
            } else {
                off(0x1D4B6, 'a')
            }
        }
        "fraktur" if latin_upper || latin_lower => {
            if let Some(e) = exc(&[('C', 0x212D), ('H', 0x210C), ('I', 0x2111), ('R', 0x211C), ('Z', 0x2128)]) {
                Some(e)
            } else if latin_upper {
                off(if bold { 0x1D56C } else { 0x1D504 }, 'A')
            } else {
                off(if bold { 0x1D586 } else { 0x1D51E }, 'a')
            }
        }
        "double-struck" if latin_upper || latin_lower || digit => {
            if let Some(e) = exc(&[('C', 0x2102), ('H', 0x210D), ('N', 0x2115), ('P', 0x2119), ('Q', 0x211A),
                                  ('R', 0x211D), ('Z', 0x2124)]) {
                Some(e)
            } else if digit {
                off(0x1D7D8, '0')
            } else if latin_upper {
                off(0x1D538, 'A')
            } else {
                off(0x1D552, 'a')
            }
        }
        "sans-serif" if latin_upper || latin_lower || digit => {
            let (u, l, d) = match (bold, italic) {
                (false, false) => (0x1D5A0, 0x1D5BA, 0x1D7E2),
                (true, false) => (0x1D5D4, 0x1D5EE, 0x1D7EC),
                (false, true) => (0x1D608, 0x1D622, 0x1D7E2),
                (true, true) => (0x1D63C, 0x1D656, 0x1D7EC),
            };
            if digit { off(d, '0') } else if latin_upper { off(u, 'A') } else { off(l, 'a') }
        }
        "monospace" if latin_upper || latin_lower || digit => {
            if digit { off(0x1D7F6, '0') } else if latin_upper { off(0x1D670, 'A') } else { off(0x1D68A, 'a') }
        }
        _ => {
            if latin_upper || latin_lower {
                match (bold, italic) {
                    (false, true) => {
                        if c == 'h' { Some('\u{210E}') } else if latin_upper { off(0x1D434, 'A') } else { off(0x1D44E, 'a') }
                    }
                    (true, true) => if latin_upper { off(0x1D468, 'A') } else { off(0x1D482, 'a') },
                    (true, false) => if latin_upper { off(0x1D400, 'A') } else { off(0x1D41A, 'a') },
                    _ => Some(c),
                }
            } else if digit && bold {
                off(0x1D7CE, '0')
            } else if ('α'..='ω').contains(&c) {
                match (bold, italic) {
                    (false, true) => off(0x1D6FC, 'α'),
                    (true, true) => off(0x1D736, 'α'),
                    (true, false) => off(0x1D6C2, 'α'),
                    _ => Some(c),
                }
            } else if ('Α'..='Ω').contains(&c) && bold {
                off(if italic { 0x1D71C } else { 0x1D6A8 }, 'Α')
            } else {
                match (c, italic) {
                    ('ϵ', true) => Some('\u{1D716}'),
                    ('ϑ', true) => Some('\u{1D717}'),
                    ('ϕ', true) => Some('\u{1D719}'),
                    ('ϱ', true) => Some('\u{1D71A}'),
                    ('ϖ', true) => Some('\u{1D71B}'),
                    ('ı', true) => Some('\u{1D6A4}'),
                    ('ȷ', true) => Some('\u{1D6A5}'),
                    _ => Some(c),
                }
            }
        }
    };
    r.unwrap_or(c)
}

// ------------------------------------------------------------------ styles
#[derive(Clone, Copy, Debug, PartialEq)]
struct Style {
    /// 0 display, 1 text, 2 script, 3 scriptscript
    level: u8,
    cramped: bool,
}

impl Style {
    fn sup(self) -> Style {
        Style { level: if self.level < 2 { 2 } else { 3 }, cramped: self.cramped }
    }
    fn sub(self) -> Style {
        Style { level: if self.level < 2 { 2 } else { 3 }, cramped: true }
    }
    fn num(self) -> Style {
        Style { level: (self.level + 1).min(3), cramped: self.cramped }
    }
    fn den(self) -> Style {
        Style { level: (self.level + 1).min(3), cramped: true }
    }
    fn cramp(self) -> Style {
        Style { level: self.level, cramped: true }
    }
    fn display(self) -> bool {
        self.level == 0
    }
}

// ------------------------------------------------------------------ layout
/// The run properties that matter here.
#[derive(Clone, Copy)]
pub struct Base {
    pub size: f64,
    pub color: u32,
}

struct Ctx<'a> {
    dom: &'a XmlDoc,
    fonts: &'a mut FontCache,
    mf: Arc<MathFont>,
    base: Base,
    /// inside a function name: letters upright
    upright_letters: bool,
    /// the run being set has its own size (w:sz)
    run_size: Option<f64>,
    /// a display equation's line width (equation numbers go to its end)
    avail: Option<f64>,
}

fn mval<'a>(dom: &'a XmlDoc, n: NodeId, pr: &str, name: &str) -> Option<&'a str> {
    let p = dom.child(n, pr)?;
    let c = dom.child(p, name)?;
    Some(dom.attr(c, "m:val").unwrap_or("1"))
}

fn on(v: Option<&str>) -> bool {
    matches!(v, Some("1" | "on" | "true"))
}

impl<'a> Ctx<'a> {
    fn scale(&self, st: Style) -> f64 {
        match st.level {
            0 | 1 => 1.0,
            2 => self.mf.k.script_pct / 100.0,
            _ => self.mf.k.sscript_pct / 100.0,
        }
    }
    fn size(&self, st: Style) -> f64 {
        self.run_size.unwrap_or(self.base.size) * self.scale(st)
    }
    /// font units -> points at a style's size
    fn u(&self, v: f64, st: Style) -> f64 {
        v * self.size(st) / self.mf.upem
    }
    fn em(&self, st: Style) -> f64 {
        self.size(st)
    }
    fn axis(&self, st: Style) -> f64 {
        self.u(self.mf.k.axis, st)
    }

    fn glyph_box(&self, mf: &MathFont, gid: u16, size: f64, color: u32) -> MBox {
        let s = size / mf.upem;
        let (ymin, ymax) = mf.ybounds(gid);
        MBox {
            w: mf.adv(gid) * s,
            asc: ymax * s,
            desc: -ymin * s,
            draws: vec![Draw::Glyph { font: mf.font.clone(), gid, x: 0.0, y: 0.0, size, color }],
            italic: mf.italic(gid) * s,
            class: Class::Ord,
            single: Some((mf.font.clone(), gid)),
        }
    }

    /// One character in the math font (or a font that has it).
    fn char_box(&mut self, c: char, st: Style, color: u32) -> MBox {
        let size = self.size(st);
        if let Some(g) = self.mf.gid(c) {
            let mf = self.mf.clone();
            return self.glyph_box(&mf, g, size, color);
        }
        let fb = self.fonts.fallback(c, false, false);
        if let Some(f) = fb {
            let mf = MATH_FONTS.with(|m| {
                m.borrow_mut().entry(f.id).or_insert_with(|| Arc::new(MathFont::load(f.clone()))).clone()
            });
            if let Some(g) = mf.gid(c) {
                return self.glyph_box(&mf, g, size, color);
            }
        }
        // nothing has it: an empty box the width of a space
        let mut b = MBox::empty();
        b.w = size * 0.3;
        b
    }

    /// Where the boxes of a row go: their x positions, their classes after
    /// the binary-operator rules, and the row's width.
    fn arrange(&self, items: &[MBox], st: Style) -> (Vec<f64>, Vec<Class>, f64) {
        let n = items.len();
        // binary operators with nothing to join become ordinary
        let mut classes: Vec<Class> = items.iter().map(|b| b.class).collect();
        for i in 0..n {
            if classes[i] == Class::Bin {
                let prev = if i == 0 { None } else { Some(classes[i - 1]) };
                if matches!(prev, None | Some(Class::Bin | Class::Op | Class::Rel | Class::Open | Class::Punct)) {
                    classes[i] = Class::Ord;
                }
            }
        }
        for i in 0..n {
            if classes[i] == Class::Bin {
                let next = classes.get(i + 1).copied();
                if matches!(next, None | Some(Class::Rel | Class::Close | Class::Punct)) {
                    classes[i] = Class::Ord;
                }
            }
        }
        let script = st.level >= 2;
        let mu = self.em(st) / 18.0;
        let mut x = 0.0;
        let mut xs = Vec::with_capacity(n);
        for (i, b) in items.iter().enumerate() {
            if i > 0 {
                x += space_between(classes[i - 1], classes[i], script) * mu;
            }
            xs.push(x);
            x += b.w;
        }
        (xs, classes, x)
    }

    /// A row of boxes with the spacing their classes call for.
    fn row(&self, items: Vec<MBox>, st: Style) -> MBox {
        let mut out = MBox::empty();
        let n = items.len();
        let (xs, _classes, w) = self.arrange(&items, st);
        for (b, x) in items.iter().zip(&xs) {
            out.add(b, *x, 0.0);
            out.asc = out.asc.max(b.asc);
            out.desc = out.desc.max(b.desc);
        }
        out.w = w;
        if let Some(last) = items.last() {
            out.italic = last.italic;
        }
        if n == 1 {
            out.class = items[0].class;
            out.single = items[0].single.clone();
        } else {
            out.class = Class::Ord;
        }
        out
    }

    /// An inline equation in pieces the line may break between: after its
    /// relations and binary operators (as the original breaks them).
    fn segments(&self, items: Vec<MBox>, st: Style) -> Vec<MBox> {
        let (xs, classes, w) = self.arrange(&items, st);
        let n = items.len();
        let mut cuts: Vec<usize> = Vec::new();
        for i in 0..n.saturating_sub(1) {
            if matches!(classes[i], Class::Rel | Class::Bin) && !matches!(classes[i + 1], Class::Rel | Class::Bin) {
                cuts.push(i + 1);
            }
        }
        cuts.push(n);
        let mut out = Vec::new();
        let mut a = 0;
        for &b in &cuts {
            if b <= a {
                continue;
            }
            let x0 = xs[a];
            let x1 = if b < n { xs[b] } else { w };
            let mut seg = MBox::empty();
            for i in a..b {
                seg.add(&items[i], xs[i] - x0, 0.0);
                seg.asc = seg.asc.max(items[i].asc);
                seg.desc = seg.desc.max(items[i].desc);
            }
            seg.w = x1 - x0;
            out.push(seg);
            a = b;
        }
        out
    }

    /// The content of an argument element (m:e, m:num...): its children.
    fn arg(&mut self, n: Option<NodeId>, st: Style) -> MBox {
        let Some(n) = n else { return MBox::empty() };
        let mut items = Vec::new();
        let kids: Vec<NodeId> = self.dom.elements(n).collect();
        for c in kids {
            self.node(c, st, &mut items);
        }
        if items.len() == 1 {
            return items.pop().unwrap();
        }
        self.row(items, st)
    }

    fn node(&mut self, n: NodeId, st: Style, out: &mut Vec<MBox>) {
        // a structure's own size: its properties' m:ctrlPr/w:rPr/w:sz
        let dom = self.dom;
        let sz = dom.elements(n)
            .find(|&k| dom.name(k).ends_with("Pr") && dom.name(k).starts_with("m:"))
            .and_then(|pr| dom.child(pr, "m:ctrlPr"))
            .and_then(|c| dom.child(c, "w:rPr"))
            .and_then(|r| dom.child(r, "w:sz"))
            .and_then(|z| dom.attr(z, "w:val"))
            .and_then(|v| v.parse::<f64>().ok());
        if let Some(v) = sz {
            let saved = self.run_size;
            self.run_size = Some(v / 2.0);
            self.node_inner(n, st, out);
            self.run_size = saved;
        } else {
            self.node_inner(n, st, out);
        }
    }

    fn node_inner(&mut self, n: NodeId, st: Style, out: &mut Vec<MBox>) {
        let dom = self.dom;
        let name = dom.name(n).to_string();
        match name.as_str() {
            "m:r" => self.run(n, st, out),
            "w:r" => self.wrun(n, st, out),
            "m:f" => out.push(self.frac(n, st)),
            "m:sSup" | "m:sSub" | "m:sSubSup" => out.push(self.scripts(n, st)),
            "m:sPre" => out.push(self.prescripts(n, st)),
            "m:rad" => out.push(self.radical(n, st)),
            "m:nary" => {
                let (op, body) = self.nary(n, st);
                out.push(op);
                out.push(body);
            }
            "m:d" => out.push(self.delim(n, st)),
            "m:m" => out.push(self.matrix(n, st)),
            "m:eqArr" => out.push(self.eqarr(n, st)),
            "m:acc" => out.push(self.accent(n, st)),
            "m:bar" => out.push(self.bar(n, st)),
            "m:func" => {
                let fname = dom.child(n, "m:fName");
                let saved = self.upright_letters;
                self.upright_letters = true;
                let mut name_box = self.arg(fname, st);
                self.upright_letters = saved;
                name_box.class = Class::Op;
                name_box.italic = 0.0;
                let mut arg = self.arg(dom.child(n, "m:e"), st);
                if arg.class == Class::Op {
                    arg.class = Class::Ord;
                }
                let thin = self.em(st) * 3.0 / 18.0;
                let mut b = MBox::empty();
                b.add(&name_box, 0.0, 0.0);
                b.add(&arg, name_box.w + thin, 0.0);
                b.w = name_box.w + thin + arg.w;
                b.asc = name_box.asc.max(arg.asc);
                b.desc = name_box.desc.max(arg.desc);
                b.italic = arg.italic;
                b.class = Class::Op;
                out.push(b);
            }
            "m:limLow" | "m:limUpp" => out.push(self.limit(n, st, name == "m:limUpp")),
            "m:groupChr" => out.push(self.group_chr(n, st)),
            "m:borderBox" => out.push(self.border_box(n, st)),
            "m:box" => {
                let mut b = self.arg(dom.child(n, "m:e"), st);
                if on(mval(dom, n, "m:boxPr", "m:opEmu")) {
                    b.class = Class::Rel;
                }
                out.push(b);
            }
            "m:phant" => out.push(self.phantom(n, st)),
            "m:oMath" | "m:e" => {
                for c in dom.elements(n).collect::<Vec<_>>() {
                    self.node(c, st, out);
                }
            }
            // w:bookmarkStart, m:ctrlPr, revisions around runs...
            "w:ins" | "w:moveTo" | "w:smartTag" | "w:customXml" => {
                for c in dom.elements(n).collect::<Vec<_>>() {
                    self.node(c, st, out);
                }
            }
            _ => {}
        }
    }

    /// m:r: math text.
    fn run(&mut self, n: NodeId, st: Style, out: &mut Vec<MBox>) {
        let dom = self.dom;
        let sz = dom.child(n, "w:rPr").and_then(|r| dom.child(r, "w:sz")).and_then(|z| dom.attr(z, "w:val"))
            .and_then(|v| v.parse::<f64>().ok()).map(|v| v / 2.0);
        let saved = self.run_size;
        if sz.is_some() {
            self.run_size = sz;
        }
        self.run_inner(n, st, out);
        self.run_size = saved;
    }

    fn run_inner(&mut self, n: NodeId, st: Style, out: &mut Vec<MBox>) {
        let dom = self.dom;
        let rpr = dom.child(n, "m:rPr");
        let get = |name: &str| rpr.and_then(|r| dom.child(r, name)).map(|c| dom.attr(c, "m:val").unwrap_or("1"));
        let normal = on(get("m:nor"));
        let sty = get("m:sty");
        let scr = get("m:scr").unwrap_or("roman").to_string();
        let color = dom.child(n, "w:rPr")
            .and_then(|r| dom.child(r, "w:color"))
            .and_then(|c| dom.attr(c, "w:val"))
            .and_then(|v| u32::from_str_radix(v, 16).ok())
            .unwrap_or(self.base.color);
        let text: String = dom.elements(n).filter(|&t| dom.is(t, "m:t") || dom.is(t, "w:t")).map(|t| dom.text(t)).collect();
        if text.is_empty() {
            return;
        }
        let (bold, italic_letters) = match sty {
            Some("p") => (false, false),
            Some("b") => (true, false),
            Some("i") => (false, true),
            Some("bi") => (true, true),
            _ => (false, !self.upright_letters),
        };
        if normal {
            // ordinary text in the document's font
            let f = self.fonts.get("Cambria", bold, false);
            let mf = MATH_FONTS.with(|m| {
                m.borrow_mut().entry(f.id).or_insert_with(|| Arc::new(MathFont::load(f.clone()))).clone()
            });
            let size = self.size(st);
            let mut x = 0.0;
            let mut b = MBox::empty();
            for c in text.chars() {
                let g = mf.gid(c).unwrap_or(0);
                let gb = self.glyph_box(&mf, g, size, color);
                b.add(&gb, x, 0.0);
                b.asc = b.asc.max(gb.asc);
                b.desc = b.desc.max(gb.desc);
                x += gb.w;
            }
            b.w = x;
            out.push(b);
            return;
        }
        let chars: Vec<char> = text.chars().collect();
        for (i, &c0) in chars.iter().enumerate() {
            let c = match c0 {
                '-' => '−',
                '*' => '∗',
                '\'' => '′',
                _ => c0,
            };
            if c == ' ' {
                let mut b = MBox::empty();
                b.w = self.em(st) * 0.25;
                out.push(b);
                continue;
            }
            let letter = c.is_alphabetic();
            let mapped = if letter || c.is_ascii_digit() {
                // uppercase Greek stays upright unless asked
                let it = italic_letters && !('Α'..='Ω').contains(&c) && letter;
                styled(c, it, bold, &scr)
            } else {
                c
            };
            let mut b = self.char_box(mapped, st, color);
            b.class = class_of(c);
            // a minus sign after an operator or at the start is a sign
            if b.class == Class::Bin && (i == 0 && out.is_empty()) {
                b.class = Class::Ord;
            }
            out.push(b);
        }
    }

    /// w:r inside an equation: plain text.
    fn wrun(&mut self, n: NodeId, st: Style, out: &mut Vec<MBox>) {
        let dom = self.dom;
        let text: String = dom.elements(n).filter(|&t| dom.is(t, "w:t")).map(|t| dom.text(t)).collect();
        if text.is_empty() {
            return;
        }
        let f = self.fonts.get("Cambria", false, false);
        let mf = MATH_FONTS.with(|m| m.borrow_mut().entry(f.id).or_insert_with(|| Arc::new(MathFont::load(f.clone()))).clone());
        let size = self.size(st);
        let mut b = MBox::empty();
        let mut x = 0.0;
        for c in text.chars() {
            let gb = self.glyph_box(&mf, mf.gid(c).unwrap_or(0), size, self.base.color);
            b.add(&gb, x, 0.0);
            b.asc = b.asc.max(gb.asc);
            b.desc = b.desc.max(gb.desc);
            x += gb.w;
        }
        b.w = x;
        out.push(b);
    }

    // ------------------------------------------------------------ fractions
    fn frac(&mut self, n: NodeId, st: Style) -> MBox {
        let dom = self.dom;
        let kind = mval(dom, n, "m:fPr", "m:type").unwrap_or("bar").to_string();
        if kind == "lin" {
            let num = self.arg(dom.child(n, "m:num"), st);
            let den = self.arg(dom.child(n, "m:den"), st);
            let mut slash = self.char_box('/', st, self.base.color);
            slash.class = Class::Ord;
            let mut r = self.row(vec![num, slash, den], st);
            r.class = Class::Ord;
            return r;
        }
        if kind == "skw" {
            let num = self.arg(dom.child(n, "m:num"), st.num());
            let den = self.arg(dom.child(n, "m:den"), st.den());
            let slash = self.char_box('/', st, self.base.color);
            let k = &self.mf.k;
            let hgap = self.u(k.skew_hgap, st);
            let vgap = self.u(k.skew_vgap, st);
            let mut b = MBox::empty();
            let up = self.axis(st) + vgap / 2.0;
            let down = vgap / 2.0;
            b.add(&num, 0.0, -(up - 0.0).max(0.0) + 0.0 - num.desc.min(0.0));
            let sx = num.w + hgap / 2.0 - slash.w / 2.0;
            b.add(&slash, sx.max(num.w * 0.5), 0.0);
            let dx = num.w + hgap;
            b.add(&den, dx, down + den.asc * 0.3);
            b.w = dx + den.w;
            b.asc = (num.asc + up).max(slash.asc);
            b.desc = (den.desc + down + den.asc * 0.3).max(slash.desc);
            b.class = Class::Inner;
            return b;
        }
        let num = self.arg(dom.child(n, "m:num"), st.num());
        let den = self.arg(dom.child(n, "m:den"), st.den());
        let k = self.mf.k.clone();
        let d = st.display();
        let axis = self.axis(st);
        let mut b = MBox::empty();
        let pad = self.em(st) * 0.12;
        let w = num.w.max(den.w) + 2.0 * pad;
        let (mut up, mut down);
        if kind == "noBar" {
            up = self.u(if d { k.stack_top_d } else { k.stack_top }, st);
            down = self.u(if d { k.stack_bot_d } else { k.stack_bot }, st);
            let gap_min = self.u(if d { k.stack_gap_d } else { k.stack_gap }, st);
            let gap = (up - num.desc) - (den.asc - down);
            if gap < gap_min {
                let extra = (gap_min - gap) / 2.0;
                up += extra;
                down += extra;
            }
        } else {
            let t = self.u(k.frac_rule, st);
            up = self.u(if d { k.num_up_d } else { k.num_up }, st);
            down = self.u(if d { k.den_down_d } else { k.den_down }, st);
            let ng = self.u(if d { k.num_gap_d } else { k.num_gap }, st);
            let dg = self.u(if d { k.den_gap_d } else { k.den_gap }, st);
            // clear the bar
            let num_bottom = up - num.desc;
            if num_bottom - (axis + t / 2.0) < ng {
                up += ng - (num_bottom - (axis + t / 2.0));
            }
            let den_top = den.asc - down;
            if (axis - t / 2.0) - den_top < dg {
                down += dg - ((axis - t / 2.0) - den_top);
            }
            b.draws.push(Draw::Rule { x: pad * 0.5, y: -(axis + t / 2.0), w: w - pad, h: t, color: self.base.color });
        }
        b.add(&num, (w - num.w) / 2.0, -up);
        b.add(&den, (w - den.w) / 2.0, down);
        b.w = w;
        b.asc = up + num.asc;
        b.desc = down + den.desc;
        b.class = Class::Inner;
        b
    }

    // -------------------------------------------------------------- scripts
    /// Attach scripts to a base box.
    fn attach(&self, base: MBox, sub: Option<MBox>, sup: Option<MBox>, st: Style, limits_italic: bool) -> MBox {
        let k = &self.mf.k;
        let single = base.single.is_some();
        let mut b = MBox::empty();
        b.add(&base, 0.0, 0.0);
        let mut w = base.w;
        let mut asc = base.asc;
        let mut desc = base.desc;
        let ss = st.sup();
        let mut sup_shift = 0.0;
        let mut sub_shift = 0.0;
        if let Some(sp) = &sup {
            let drop = if single { 0.0 } else { base.asc - self.u(k.sup_drop_max, ss) };
            let std = self.u(if st.cramped { k.sup_up_cramped } else { k.sup_up }, st);
            sup_shift = std.max(drop).max(sp.desc + self.u(k.sup_bottom_min, st));
        }
        if let Some(sb) = &sub {
            let drop = if single { 0.0 } else { base.desc + self.u(k.sub_drop_min, st.sub()) };
            sub_shift = self.u(k.sub_down, st).max(drop).max(sb.asc - self.u(k.sub_top_max, st));
        }
        if let (Some(sp), Some(sb)) = (&sup, &sub) {
            let gap = (sup_shift - sp.desc) - (sb.asc - sub_shift);
            let min = self.u(k.subsup_gap, st);
            if gap < min {
                sub_shift += min - gap;
                let max_bottom = self.u(k.sup_bottom_max_sub, st);
                let lift = max_bottom - (sup_shift - sp.desc);
                if lift > 0.0 {
                    sup_shift += lift;
                    sub_shift -= lift;
                }
            }
        }
        let after = self.u(k.space_after_script, st);
        let mut end = w;
        if let Some(sp) = &sup {
            let x = w + if limits_italic { base.italic } else { base.italic };
            b.add(sp, x, -sup_shift);
            asc = asc.max(sup_shift + sp.asc);
            desc = desc.max(sp.desc - sup_shift);
            end = end.max(x + sp.w);
        }
        if let Some(sb) = &sub {
            // integrals: the subscript tucks in under the slant
            let x = w - if limits_italic { base.italic } else { 0.0 };
            b.add(sb, x, sub_shift);
            asc = asc.max(sb.asc - sub_shift);
            desc = desc.max(sub_shift + sb.desc);
            end = end.max(x + sb.w);
        }
        w = end + after;
        b.w = w;
        b.asc = asc;
        b.desc = desc;
        b.class = base.class;
        b
    }

    fn scripts(&mut self, n: NodeId, st: Style) -> MBox {
        let dom = self.dom;
        let base = self.arg(dom.child(n, "m:e"), st);
        let sup = dom.child(n, "m:sup").map(|s| self.arg(Some(s), st.sup()));
        let sub = dom.child(n, "m:sub").map(|s| self.arg(Some(s), st.sub()));
        self.attach(base, sub, sup, st, false)
    }

    fn prescripts(&mut self, n: NodeId, st: Style) -> MBox {
        let dom = self.dom;
        let sup = self.arg(dom.child(n, "m:sup"), st.sup());
        let sub = self.arg(dom.child(n, "m:sub"), st.sub());
        let base = self.arg(dom.child(n, "m:e"), st);
        // scripts laid out against an empty base, then the base after them
        let mut probe = MBox::empty();
        probe.asc = base.asc;
        probe.desc = base.desc;
        let s = self.attach(probe, Some(sub.clone()), Some(sup.clone()), st, false);
        let sw = sub.w.max(sup.w);
        let mut b = MBox::empty();
        let k = &self.mf.k;
        let sup_shift = self.u(if st.cramped { k.sup_up_cramped } else { k.sup_up }, st).max(sup.desc + self.u(k.sup_bottom_min, st));
        let sub_shift = self.u(k.sub_down, st).max(sub.asc - self.u(k.sub_top_max, st));
        b.add(&sup, sw - sup.w, -sup_shift);
        b.add(&sub, sw - sub.w, sub_shift);
        let gap = self.em(st) / 18.0;
        b.add(&base, sw + gap, 0.0);
        b.w = sw + gap + base.w;
        b.asc = s.asc.max(base.asc);
        b.desc = s.desc.max(base.desc);
        b.class = base.class;
        b
    }

    // ------------------------------------------------------------- radicals
    fn radical(&mut self, n: NodeId, st: Style) -> MBox {
        let dom = self.dom;
        let body = self.arg(dom.child(n, "m:e"), st.cramp());
        let hide_deg = on(mval(dom, n, "m:radPr", "m:degHide"));
        let deg = dom.child(n, "m:deg").filter(|&d| !hide_deg && dom.elements(d).any(|k| !dom.is(k, "m:ctrlPr")));
        let deg_box = deg.map(|d| self.arg(Some(d), Style { level: 3, cramped: true }));
        let k = self.mf.k.clone();
        let t = self.u(k.rad_rule, st);
        let mut gap = self.u(if st.display() { k.rad_gap_d } else { k.rad_gap }, st);
        let target = body.asc + body.desc + gap + t;
        let mf = self.mf.clone();
        let size = self.size(st);
        let mut sign = match mf.gid('√') {
            Some(g) => self.stretch(&mf, g, target, true, size),
            None => self.char_box('√', st, self.base.color),
        };
        let sign_h = sign.asc + sign.desc;
        if sign_h > target {
            gap += (sign_h - target) / 2.0;
        }
        // the sign's top is the bar's top
        let top = body.asc + gap + t;
        let shift = top - sign.asc;
        let mut b = MBox::empty();
        let mut x = 0.0;
        if let Some(db) = &deg_box {
            let before = self.u(k.rad_kern_before, st);
            let after = self.u(k.rad_kern_after, st);
            let raise = (sign_h) * k.rad_raise_pct / 100.0 - sign.desc - shift;
            b.add(db, before, -(raise + db.desc));
            x = (before + db.w + after).max(0.0);
            b.asc = b.asc.max(raise + db.desc + db.asc);
        }
        sign.class = Class::Ord;
        b.add(&sign, x, -shift);
        x += sign.w;
        b.draws.push(Draw::Rule { x, y: -top, w: body.w, h: t, color: self.base.color });
        b.add(&body, x, 0.0);
        b.w = x + body.w;
        b.asc = b.asc.max(top + self.u(k.rad_extra, st));
        b.desc = body.desc.max(sign.desc + shift);
        b.class = Class::Ord;
        b
    }

    /// A glyph made at least `target` long (vertical: height + depth;
    /// horizontal: width): a bigger variant, else an assembly. Vertical
    /// results keep the glyph's own vertical position.
    fn stretch(&self, mf: &MathFont, gid: u16, target: f64, vertical: bool, size: f64) -> MBox {
        let s = size / mf.upem;
        let (variants, asm) = mf.construction(gid, vertical);
        let mut best = gid;
        let mut found = false;
        for (g, adv) in &variants {
            best = *g;
            if adv * s >= target {
                found = true;
                break;
            }
        }
        if found || asm.is_none() {
            return self.glyph_box(mf, best, size, self.base.color);
        }
        let parts = asm.unwrap();
        let target_u = target / s;
        let min_ov = mf.k.min_overlap;
        // repeat the extenders until the assembly can reach the length
        let mut seq: Vec<Part> = Vec::new();
        for reps in 0..40 {
            seq.clear();
            for p in &parts {
                if p.ext {
                    for _ in 0..reps.max(1) {
                        seq.push(*p);
                    }
                } else {
                    seq.push(*p);
                }
            }
            let full: f64 = seq.iter().map(|p| p.adv).sum();
            let max_len = full - min_ov * (seq.len().saturating_sub(1)) as f64;
            if max_len >= target_u {
                break;
            }
        }
        let full: f64 = seq.iter().map(|p| p.adv).sum();
        let joins = seq.len().saturating_sub(1).max(1) as f64;
        let mut ov = ((full - target_u) / joins).max(min_ov);
        // never overlap past the connectors
        let max_ov = seq.windows(2).map(|w| w[0].end.min(w[1].start)).fold(f64::INFINITY, f64::min);
        if max_ov.is_finite() {
            ov = ov.min(max_ov.max(min_ov));
        }
        let mut b = MBox::empty();
        let mut pos = 0.0;
        let mut positions = Vec::new();
        for (i, p) in seq.iter().enumerate() {
            if i > 0 {
                pos -= ov;
            }
            positions.push(pos);
            pos += p.adv;
        }
        let len = pos * s;
        if vertical {
            // parts go bottom to top, each glyph's origin moved up by its
            // place in the assembly
            let mut asc = f64::NEG_INFINITY;
            let mut desc = f64::NEG_INFINITY;
            for (p, at) in seq.iter().zip(&positions) {
                let (ymin, ymax) = mf.ybounds(p.gid);
                let oy = at * s;
                b.draws.push(Draw::Glyph { font: mf.font.clone(), gid: p.gid, x: 0.0, y: -oy, size, color: self.base.color });
                asc = asc.max(oy + ymax * s);
                desc = desc.max(-(oy + ymin * s));
            }
            b.w = seq.iter().map(|p| mf.adv(p.gid) * s).fold(0.0, f64::max);
            b.asc = asc;
            b.desc = desc;
            let _ = len;
        } else {
            for (p, at) in seq.iter().zip(&positions) {
                b.draws.push(Draw::Glyph { font: mf.font.clone(), gid: p.gid, x: at * s, y: 0.0, size, color: self.base.color });
            }
            b.w = len;
            let (lo, hi) = seq.iter().map(|p| mf.ybounds(p.gid)).fold((0.0f64, 0.0f64), |a, (l, h)| (a.0.min(l), a.1.max(h)));
            b.asc = hi * s;
            b.desc = -lo * s;
        }
        b.single = None;
        b
    }

    /// Centre a box on the math axis.
    fn on_axis(&self, mut b: MBox, st: Style) -> MBox {
        let axis = self.axis(st);
        let shift = (b.asc - b.desc) / 2.0 - axis;
        if shift.abs() < 1e-6 {
            return b;
        }
        for d in b.draws.iter_mut() {
            *d = d.shifted(0.0, shift);
        }
        b.asc -= shift;
        b.desc += shift;
        b
    }

    // --------------------------------------------------------------- n-ary
    fn nary(&mut self, n: NodeId, st: Style) -> (MBox, MBox) {
        let dom = self.dom;
        let chr = mval(dom, n, "m:naryPr", "m:chr").and_then(|v| v.chars().next()).unwrap_or('∫');
        let integral = matches!(chr, '∫' | '∬' | '∭' | '∮' | '∯' | '∰' | '∱' | '∲' | '∳' | '⨌');
        let loc = mval(dom, n, "m:naryPr", "m:limLoc").map(|s| s.to_string())
            .unwrap_or_else(|| if integral { "subSup".into() } else { "undOvr".into() });
        let sub_hide = on(mval(dom, n, "m:naryPr", "m:subHide"));
        let sup_hide = on(mval(dom, n, "m:naryPr", "m:supHide"));
        let mf = self.mf.clone();
        let size = self.size(st);
        let mut op = match mf.gid(chr) {
            Some(g) if st.display() => {
                let min = self.u(mf.k.disp_op_min_h, st);
                let (variants, _) = mf.construction(g, true);
                let s = size / mf.upem;
                let pick = variants.iter().find(|(_, a)| a * s >= min).or(variants.last()).map(|v| v.0).unwrap_or(g);
                self.glyph_box(&mf, pick, size, self.base.color)
            }
            Some(g) => self.glyph_box(&mf, g, size, self.base.color),
            None => self.char_box(chr, st, self.base.color),
        };
        op = self.on_axis(op, st);
        op.class = Class::Op;
        let sub = if sub_hide { None } else { dom.child(n, "m:sub").filter(|&s| dom.elements(s).any(|k| !dom.is(k, "m:ctrlPr"))) };
        let sup = if sup_hide { None } else { dom.child(n, "m:sup").filter(|&s| dom.elements(s).any(|k| !dom.is(k, "m:ctrlPr"))) };
        let sub_box = sub.map(|s| self.arg(Some(s), st.sub()));
        let sup_box = sup.map(|s| self.arg(Some(s), st.sup()));
        let mut opb = if loc == "undOvr" && st.display() {
            self.limits(op, sub_box, sup_box, st)
        } else {
            let mut o = op;
            o.single = Some((mf.font.clone(), 0));
            self.attach(o, sub_box, sup_box, st, integral)
        };
        opb.class = Class::Op;
        let mut body = self.arg(dom.child(n, "m:e"), st);
        if body.class == Class::Op {
            body.class = Class::Ord;
        }
        if body.class == Class::Bin {
            body.class = Class::Ord;
        }
        (opb, body)
    }

    /// Limits above and below an operator.
    fn limits(&self, op: MBox, under: Option<MBox>, over: Option<MBox>, st: Style) -> MBox {
        let k = &self.mf.k;
        let w = op.w.max(under.as_ref().map_or(0.0, |b| b.w)).max(over.as_ref().map_or(0.0, |b| b.w));
        let mut b = MBox::empty();
        b.add(&op, (w - op.w) / 2.0, 0.0);
        b.asc = op.asc;
        b.desc = op.desc;
        if let Some(o) = &over {
            let shift = (op.asc + self.u(k.upper_gap, st) + o.desc).max(op.asc + self.u(k.upper_rise, st));
            // italic operators: the upper limit leans right
            let dx = (w - o.w) / 2.0 + op.italic / 2.0;
            b.add(o, dx, -shift);
            b.asc = shift + o.asc;
        }
        if let Some(u) = &under {
            let shift = (op.desc + self.u(k.lower_gap, st) + u.asc).max(op.desc + self.u(k.lower_drop, st));
            let dx = (w - u.w) / 2.0 - op.italic / 2.0;
            b.add(u, dx, shift);
            b.desc = shift + u.desc;
        }
        b.w = w;
        b.class = op.class;
        b
    }

    fn limit(&mut self, n: NodeId, st: Style, upper: bool) -> MBox {
        let dom = self.dom;
        let base = self.arg(dom.child(n, "m:e"), st);
        let lim = self.arg(dom.child(n, "m:lim"), st.sub());
        let mut b = if upper { self.limits(base, None, Some(lim), st) } else { self.limits(base, Some(lim), None, st) };
        b.class = Class::Op;
        b
    }

    // ---------------------------------------------------------- delimiters
    fn fence(&mut self, c: char, st: Style, target: f64, grow: bool) -> MBox {
        let mf = self.mf.clone();
        let size = self.size(st);
        let mut b = match mf.gid(c) {
            Some(g) if grow => {
                let mut v = self.stretch(&mf, g, target, true, size);
                v.italic = 0.0;
                v
            }
            Some(g) => self.glyph_box(&mf, g, size, self.base.color),
            None => self.char_box(c, st, self.base.color),
        };
        b = self.on_axis(b, st);
        b.single = None;
        b
    }

    fn delim(&mut self, n: NodeId, st: Style) -> MBox {
        let dom = self.dom;
        let beg = match mval(dom, n, "m:dPr", "m:begChr") { Some(v) => v.chars().next(), None => Some('(') };
        let end = match mval(dom, n, "m:dPr", "m:endChr") { Some(v) => v.chars().next(), None => Some(')') };
        let sep = match mval(dom, n, "m:dPr", "m:sepChr") { Some(v) => v.chars().next(), None => Some('|') };
        let grow = mval(dom, n, "m:dPr", "m:grow").map_or(true, |v| !matches!(v, "0" | "off" | "false"));
        let es: Vec<NodeId> = dom.children_named(n, "m:e").collect();
        let parts: Vec<MBox> = es.iter().map(|&e| self.arg(Some(e), st)).collect();
        let axis = self.axis(st);
        let (mut a, mut d) = (0.0f64, 0.0f64);
        for p in &parts {
            a = a.max(p.asc);
            d = d.max(p.desc);
        }
        let half = (a - axis).max(d + axis);
        let k = &self.mf.k;
        // TeX: 90% of the content, or within 5pt of it
        let target = (2.0 * half * 0.901).max(2.0 * half - self.base.size * 0.5);
        let _ = k;
        let mut items: Vec<MBox> = Vec::new();
        if let Some(c) = beg {
            let mut f = self.fence(c, st, target, grow);
            f.class = Class::Open;
            items.push(f);
        }
        for (i, p) in parts.into_iter().enumerate() {
            if i > 0 {
                if let Some(c) = sep {
                    let mut f = self.fence(c, st, target, grow);
                    f.class = Class::Rel;
                    items.push(f);
                }
            }
            let mut p = p;
            if matches!(p.class, Class::Bin | Class::Rel) {
                p.class = Class::Ord;
            }
            items.push(p);
        }
        if let Some(c) = end {
            let mut f = self.fence(c, st, target, grow);
            f.class = Class::Close;
            items.push(f);
        }
        let mut b = self.row(items, st);
        b.class = Class::Inner;
        b.single = None;
        b.italic = 0.0;
        b
    }

    // ------------------------------------------------------------- arrays
    fn grid(&mut self, rows: Vec<Vec<MBox>>, st: Style, col_gap: f64, align: &dyn Fn(usize) -> f64) -> MBox {
        let ncols = rows.iter().map(|r| r.len()).max().unwrap_or(0);
        let mut widths = vec![0.0f64; ncols];
        for r in &rows {
            for (j, c) in r.iter().enumerate() {
                widths[j] = widths[j].max(c.w);
            }
        }
        let em = self.em(st);
        let row_gap = em * 0.3;
        let strut_a = em * 0.7;
        let strut_d = em * 0.3;
        let mut b = MBox::empty();
        let mut y = 0.0;
        let mut first = true;
        let mut total_w = 0.0;
        for r in &rows {
            let a = r.iter().map(|c| c.asc).fold(strut_a, f64::max);
            let d = r.iter().map(|c| c.desc).fold(strut_d, f64::max);
            if !first {
                y += row_gap;
            }
            first = false;
            y += a;
            let mut x = 0.0;
            for (j, c) in r.iter().enumerate() {
                let slack = widths[j] - c.w;
                b.add(c, x + slack * align(j), y);
                x += widths[j] + if j + 1 < ncols { col_gap } else { 0.0 };
            }
            total_w = f64::max(total_w, x);
            y += d;
        }
        total_w = total_w.max(widths.iter().sum::<f64>() + col_gap * (ncols.saturating_sub(1)) as f64);
        // rows hang from the top; centre the whole on the axis
        b.w = total_w;
        b.asc = 0.0;
        b.desc = y;
        let mut b = self.on_axis(b, st);
        b.class = Class::Ord;
        b
    }

    fn matrix(&mut self, n: NodeId, st: Style) -> MBox {
        let dom = self.dom;
        let rows: Vec<Vec<MBox>> = dom
            .children_named(n, "m:mr")
            .collect::<Vec<_>>()
            .into_iter()
            .map(|r| dom.children_named(r, "m:e").collect::<Vec<_>>().into_iter().map(|e| self.arg(Some(e), st)).collect())
            .collect();
        let gap = self.em(st) * 0.8;
        self.grid(rows, st, gap, &|_| 0.5)
    }

    fn eqarr(&mut self, n: NodeId, st: Style) -> MBox {
        let dom = self.dom;
        let mut rows: Vec<Vec<MBox>> = Vec::new();
        let mut numbers: Vec<Vec<MBox>> = Vec::new();
        let avail = self.avail.take();
        for e in dom.children_named(n, "m:e").collect::<Vec<_>>() {
            // split the row's items at '&' (alignment) and '#' (its number)
            let mut cells: Vec<Vec<MBox>> = vec![Vec::new()];
            let mut number: Option<Vec<MBox>> = None;
            for c in dom.elements(e).collect::<Vec<_>>() {
                if dom.is(c, "m:r") {
                    let text: String = dom.elements(c).filter(|&t| dom.is(t, "m:t")).map(|t| dom.text(t)).collect();
                    if text.contains('&') || text.contains('#') {
                        let mut part = String::new();
                        let flush = |me: &mut Self, part: &mut String, cells: &mut Vec<Vec<MBox>>, number: &mut Option<Vec<MBox>>| {
                            if !part.is_empty() {
                                let mut tmp = Vec::new();
                                me.text_items(c, part, st, &mut tmp);
                                match number.as_mut() {
                                    Some(nb) => nb.extend(tmp),
                                    None => cells.last_mut().unwrap().extend(tmp),
                                }
                                part.clear();
                            }
                        };
                        for ch in text.chars() {
                            match ch {
                                '&' if number.is_none() => {
                                    flush(self, &mut part, &mut cells, &mut number);
                                    cells.push(Vec::new());
                                }
                                '#' => {
                                    flush(self, &mut part, &mut cells, &mut number);
                                    number = Some(Vec::new());
                                }
                                _ => part.push(ch),
                            }
                        }
                        flush(self, &mut part, &mut cells, &mut number);
                        continue;
                    }
                }
                let mut tmp = Vec::new();
                self.node(c, st, &mut tmp);
                match number.as_mut() {
                    Some(nb) => nb.extend(tmp),
                    None => cells.last_mut().unwrap().extend(tmp),
                }
            }
            let row: Vec<MBox> = cells.into_iter().map(|items| self.row(items, st)).collect();
            rows.push(row);
            numbers.push(number.unwrap_or_default());
        }
        let nrows = rows.len();
        // pairs of columns meet at the alignment point
        let g = self.grid(rows, st, 0.0, &|j| if j % 2 == 0 { 1.0 } else { 0.0 });
        let has_number = numbers.iter().any(|n| !n.is_empty());
        match avail {
            Some(w) if has_number && nrows == 1 => {
                // a numbered display equation: centred, its number at the
                // right end of the line
                let num = self.row(numbers.pop().unwrap(), st);
                let mut b = MBox::empty();
                let x = ((w - g.w) / 2.0).max(0.0);
                b.add(&g, x, 0.0);
                b.add(&num, (w - num.w).max(x + g.w), 0.0);
                b.w = w.max(x + g.w + num.w);
                b.asc = g.asc.max(num.asc);
                b.desc = g.desc.max(num.desc);
                b
            }
            _ => g,
        }
    }

    /// The items of a run's text other than its own (eqArr splits).
    fn text_items(&mut self, run: NodeId, text: &str, st: Style, out: &mut Vec<MBox>) {
        // a stand-in run with this text: reuse run() through a temporary
        // element would need a mutable tree; lay the characters out here
        let dom = self.dom;
        let rpr = dom.child(run, "m:rPr");
        let sty = rpr.and_then(|r| dom.child(r, "m:sty")).and_then(|c| dom.attr(c, "m:val"));
        let italic = match sty { Some("p" | "b") => false, Some(_) => true, None => !self.upright_letters };
        for c0 in text.chars() {
            let c = if c0 == '-' { '−' } else { c0 };
            if c == ' ' {
                continue;
            }
            let mapped = if c.is_alphabetic() && italic && !('Α'..='Ω').contains(&c) { styled(c, true, false, "roman") } else { c };
            let mut b = self.char_box(mapped, st, self.base.color);
            b.class = class_of(c);
            out.push(b);
        }
    }

    // ------------------------------------------------------- accents, bars
    fn accent(&mut self, n: NodeId, st: Style) -> MBox {
        let dom = self.dom;
        let chr = mval(dom, n, "m:accPr", "m:chr").and_then(|v| v.chars().next()).unwrap_or('\u{0302}');
        let body = self.arg(dom.child(n, "m:e"), st.cramp());
        let mf = self.mf.clone();
        let size = self.size(st);
        let s = size / mf.upem;
        // combining marks: their spacing forms as fallback
        let g = mf.gid(chr).or_else(|| {
            let alt = match chr {
                '\u{0302}' => '^', '\u{0303}' => '~', '\u{0307}' => '˙', '\u{0308}' => '¨', '\u{0301}' => '´',
                '\u{0300}' => '`', '\u{030C}' => 'ˇ', '\u{0306}' => '˘', '\u{0305}' | '\u{0304}' => '¯',
                '\u{20D7}' => '→', '\u{20D6}' => '←', _ => chr,
            };
            mf.gid(alt)
        });
        let Some(g) = g else { return body };
        let acc = self.stretch(&mf, g, body.w, false, size);
        let base_h = self.u(mf.k.accent_base, st);
        let lift = (body.asc - base_h).max(0.0);
        // where it sits: over the base's accent point (a slanted letter's
        // is right of centre)
        let base_x = match &body.single {
            Some((_, bg)) if *bg != 0 => mf.top_accent(*bg).map(|v| v * s).unwrap_or(body.w / 2.0 + body.italic / 2.0),
            _ => body.w / 2.0,
        };
        let acc_x = match acc.single.as_ref() {
            Some((_, ag)) => mf.top_accent(*ag).map(|v| v * s).unwrap_or(acc.w / 2.0),
            None => acc.w / 2.0,
        };
        let mut b = MBox::empty();
        b.add(&body, 0.0, 0.0);
        let dx = base_x - acc_x;
        b.add(&acc, dx, -lift);
        b.w = body.w.max(dx + acc.w);
        b.asc = body.asc.max(acc.asc + lift);
        b.desc = body.desc;
        b.italic = body.italic;
        b.class = Class::Ord;
        b
    }

    fn bar(&mut self, n: NodeId, st: Style) -> MBox {
        let dom = self.dom;
        let top = mval(dom, n, "m:barPr", "m:pos") == Some("top");
        let body = self.arg(dom.child(n, "m:e"), if top { st.cramp() } else { st });
        let k = self.mf.k.clone();
        let mut b = MBox::empty();
        b.add(&body, 0.0, 0.0);
        b.w = body.w;
        if top {
            let t = self.u(k.over_rule, st);
            let gap = self.u(k.over_gap, st);
            let y = body.asc + gap + t;
            b.draws.push(Draw::Rule { x: 0.0, y: -y, w: body.w, h: t, color: self.base.color });
            b.asc = y + self.u(k.over_extra, st);
            b.desc = body.desc;
        } else {
            let t = self.u(k.under_rule, st);
            let gap = self.u(k.under_gap, st);
            let y = body.desc + gap;
            b.draws.push(Draw::Rule { x: 0.0, y, w: body.w, h: t, color: self.base.color });
            b.asc = body.asc;
            b.desc = y + t + self.u(k.under_extra, st);
        }
        b.class = Class::Ord;
        b
    }

    fn group_chr(&mut self, n: NodeId, st: Style) -> MBox {
        let dom = self.dom;
        let chr = mval(dom, n, "m:groupChrPr", "m:chr").and_then(|v| v.chars().next()).unwrap_or('⏟');
        let pos_top = mval(dom, n, "m:groupChrPr", "m:pos") == Some("top");
        let body = self.arg(dom.child(n, "m:e"), st);
        let mf = self.mf.clone();
        let size = self.size(st);
        let Some(g) = mf.gid(chr) else { return body };
        let brace = self.stretch(&mf, g, body.w, false, size);
        let k = self.mf.k.clone();
        let mut b = MBox::empty();
        b.add(&body, 0.0, 0.0);
        let bx = (body.w - brace.w) / 2.0;
        if pos_top {
            let gap = self.u(k.stretch_gap_below, st);
            let y = body.asc + gap + brace.desc;
            b.add(&brace, bx, -y);
            b.asc = y + brace.asc;
            b.desc = body.desc;
        } else {
            let gap = self.u(k.stretch_gap_above, st);
            let y = body.desc + gap + brace.asc;
            b.add(&brace, bx, y);
            b.asc = body.asc;
            b.desc = y + brace.desc;
        }
        b.w = body.w.max(brace.w);
        b.class = Class::Op;
        b
    }

    fn border_box(&mut self, n: NodeId, st: Style) -> MBox {
        let dom = self.dom;
        let body = self.arg(dom.child(n, "m:e"), st);
        let flag = |name: &str| on(mval(dom, n, "m:borderBoxPr", name));
        let pad = self.em(st) * 0.15;
        let lw = self.u(self.mf.k.frac_rule, st).max(0.4);
        let mut b = MBox::empty();
        b.add(&body, pad, 0.0);
        let (x0, x1) = (0.0, body.w + 2.0 * pad);
        let (y0, y1) = (-(body.asc + pad), body.desc + pad);
        let c = self.base.color;
        let mut line = |a: f64, bb: f64, cc: f64, d: f64| b.draws.push(Draw::Line { x0: a, y0: bb, x1: cc, y1: d, w: lw, color: c });
        if !flag("m:hideTop") { line(x0, y0, x1, y0); }
        if !flag("m:hideBot") { line(x0, y1, x1, y1); }
        if !flag("m:hideLeft") { line(x0, y0, x0, y1); }
        if !flag("m:hideRight") { line(x1, y0, x1, y1); }
        if flag("m:strikeH") { let ya = -self.axis(st); line(x0, ya, x1, ya); }
        if flag("m:strikeV") { let xm = (x0 + x1) / 2.0; line(xm, y0, xm, y1); }
        if flag("m:strikeBLTR") { line(x0, y1, x1, y0); }
        if flag("m:strikeTLBR") { line(x0, y0, x1, y1); }
        b.w = x1;
        b.asc = -y0 + lw;
        b.desc = y1 + lw;
        b.class = Class::Ord;
        b
    }

    fn phantom(&mut self, n: NodeId, st: Style) -> MBox {
        let dom = self.dom;
        let body = self.arg(dom.child(n, "m:e"), st);
        let show = mval(dom, n, "m:phantPr", "m:show").map_or(true, |v| !matches!(v, "0" | "off" | "false"));
        let mut b = if show { body.clone() } else { MBox { draws: Vec::new(), ..body.clone() } };
        if on(mval(dom, n, "m:phantPr", "m:zeroWid")) { b.w = 0.0; }
        if on(mval(dom, n, "m:phantPr", "m:zeroAsc")) { b.asc = 0.0; }
        if on(mval(dom, n, "m:phantPr", "m:zeroDesc")) { b.desc = 0.0; }
        b
    }
}

/// An inline equation in the pieces a line may break between.
pub fn layout_inline(dom: &XmlDoc, fonts: &mut FontCache, n: NodeId, base: Base,
                     font_name: Option<&str>) -> Vec<MBox> {
    let mf = math_font(fonts, font_name);
    let mut cx = Ctx { dom, fonts, mf, base, upright_letters: false, run_size: None, avail: None };
    let st = Style { level: 1, cramped: false };
    let mut items = Vec::new();
    for c in dom.elements(n).collect::<Vec<_>>() {
        cx.node(c, st, &mut items);
    }
    if items.is_empty() {
        let mut b = MBox::empty();
        b.w = base.size * 0.5;
        b.asc = base.size * 0.7;
        b.desc = base.size * 0.2;
        return vec![b];
    }
    cx.segments(items, st)
}

/// Lay out an m:oMath element. `display`: set as a display equation (its
/// own line), else inline with the text.
pub fn layout(dom: &XmlDoc, fonts: &mut FontCache, n: NodeId, base: Base, display: bool,
              font_name: Option<&str>, avail: Option<f64>) -> MBox {
    let mf = math_font(fonts, font_name);
    let mut cx = Ctx { dom, fonts, mf, base, upright_letters: false, run_size: None,
                       avail: if display { avail } else { None } };
    let st = Style { level: if display { 0 } else { 1 }, cramped: false };
    let mut items = Vec::new();
    for c in dom.elements(n).collect::<Vec<_>>() {
        cx.node(c, st, &mut items);
    }
    let mut b = cx.row(items, st);
    if b.w == 0.0 && b.draws.is_empty() {
        // an empty equation still takes a little room
        b.w = base.size * 0.5;
        b.asc = base.size * 0.7;
        b.desc = base.size * 0.2;
    }
    b
}

/// Draw a laid-out equation with its baseline at (x, y).
pub fn draw(cr: &cairo::Context, b: &MBox, x: f64, y: f64, face: &mut dyn FnMut(&Font) -> Option<cairo::FontFace>) {
    let rgb = |cr: &cairo::Context, c: u32| {
        cr.set_source_rgb(((c >> 16) & 255) as f64 / 255.0, ((c >> 8) & 255) as f64 / 255.0, (c & 255) as f64 / 255.0)
    };
    for d in &b.draws {
        match d {
            Draw::Glyph { font, gid, x: gx, y: gy, size, color } => {
                let Some(ff) = face(font) else { continue };
                cr.save().ok();
                cr.set_font_face(&ff);
                cr.set_font_matrix(cairo::Matrix::new(*size, 0.0, 0.0, *size, 0.0, 0.0));
                let mut fo = cairo::FontOptions::new().unwrap();
                fo.set_hint_style(cairo::HintStyle::None);
                fo.set_hint_metrics(cairo::HintMetrics::Off);
                cr.set_font_options(&fo);
                rgb(cr, *color);
                cr.show_glyphs(&[cairo::Glyph::new(*gid as _, x + gx, y + gy)]).ok();
                cr.restore().ok();
            }
            Draw::Rule { x: rx, y: ry, w, h, color } => {
                rgb(cr, *color);
                cr.rectangle(x + rx, y + ry, *w, *h);
                cr.fill().ok();
            }
            Draw::Line { x0, y0, x1, y1, w, color } => {
                rgb(cr, *color);
                cr.set_line_width(*w);
                cr.move_to(x + x0, y + y0);
                cr.line_to(x + x1, y + y1);
                cr.stroke().ok();
            }
        }
    }
}

/// The math font named in the document's settings (m:mathPr/m:mathFont).
pub fn doc_math_font(settings: Option<&XmlDoc>) -> Option<String> {
    let s = settings?;
    let pr = s.child(s.root, "m:mathPr")?;
    s.child(pr, "m:mathFont").and_then(|f| s.attr(f, "m:val")).map(|v| v.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn alphabets() {
        assert_eq!(styled('x', true, false, "roman"), '\u{1D465}');
        assert_eq!(styled('h', true, false, "roman"), '\u{210E}');
        assert_eq!(styled('R', false, false, "double-struck"), 'ℝ');
        assert_eq!(styled('α', true, false, "roman"), '\u{1D6FC}');
        assert_eq!(styled('2', true, false, "roman"), '2');
    }
}
