//! Paragraph and run properties read from w:pPr / w:rPr, and how they
//! combine (defaults, styles, direct formatting).

use crate::xml::{NodeId, XmlDoc};

pub fn on_off(doc: &XmlDoc, n: NodeId) -> bool {
    !matches!(doc.attr(n, "w:val"), Some("0") | Some("false") | Some("off") | Some("none"))
}

pub fn int_attr(doc: &XmlDoc, n: NodeId, key: &str) -> Option<i32> {
    let v = doc.attr(n, key)?;
    if let Ok(i) = v.parse::<i32>() {
        return Some(i);
    }
    // values with units ("12pt", "1in") in strict documents
    let num: String = v.chars().take_while(|c| c.is_ascii_digit() || *c == '.' || *c == '-').collect();
    let f: f64 = num.parse().ok()?;
    let unit = &v[num.len()..];
    Some(match unit {
        "pt" => f * 20.0,
        "in" => f * 1440.0,
        "cm" => f * 1440.0 / 2.54,
        "mm" => f * 144.0 / 2.54,
        "pc" | "pi" => f * 240.0,
        _ => f,
    } as i32)
}

pub fn color_attr(v: &str) -> Option<u32> {
    if v.eq_ignore_ascii_case("auto") {
        return None;
    }
    u32::from_str_radix(v, 16).ok()
}

// ------------------------------------------------------------------ runs
#[derive(Clone, Debug, PartialEq)]
pub enum ColorVal {
    Auto,
    Rgb(u32),
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RunProps {
    pub style: Option<String>,
    pub font_ascii: Option<String>,
    pub font_hansi: Option<String>,
    pub font_east: Option<String>,
    pub font_cs: Option<String>,
    pub theme_ascii: Option<String>,
    pub theme_hansi: Option<String>,
    pub theme_east: Option<String>,
    pub theme_cs: Option<String>,
    /// half-points
    pub size: Option<u32>,
    pub size_cs: Option<u32>,
    pub bold: Option<bool>,
    pub italic: Option<bool>,
    pub caps: Option<bool>,
    pub small_caps: Option<bool>,
    pub strike: Option<bool>,
    pub dstrike: Option<bool>,
    pub outline: Option<bool>,
    pub shadow: Option<bool>,
    pub emboss: Option<bool>,
    pub imprint: Option<bool>,
    pub vanish: Option<bool>,
    pub underline: Option<String>,
    pub underline_color: Option<u32>,
    pub color: Option<ColorVal>,
    pub theme_color: Option<String>,
    pub highlight: Option<String>,
    pub shading: Option<u32>,
    pub vert_align: Option<String>,
    /// raise/lower in half-points
    pub position: Option<i32>,
    /// character spacing in twips
    pub spacing: Option<i32>,
    /// horizontal scale, percent
    pub scale: Option<u32>,
    /// kerning threshold in half-points (0 = off)
    pub kern: Option<u32>,
    pub lang: Option<String>,
    pub rtl: Option<bool>,
}

macro_rules! merge_fields {
    ($dst:ident, $src:ident, $($f:ident),*) => {
        $( if $src.$f.is_some() { $dst.$f = $src.$f.clone(); } )*
    };
}

const TOGGLES: usize = 10;

impl RunProps {
    pub fn parse(doc: &XmlDoc, rpr: NodeId) -> RunProps {
        let mut p = RunProps::default();
        for c in doc.elements(rpr) {
            match doc.name(c) {
                "w:rStyle" => p.style = doc.attr(c, "w:val").map(String::from),
                "w:rFonts" => {
                    p.font_ascii = doc.attr(c, "w:ascii").map(String::from);
                    p.font_hansi = doc.attr(c, "w:hAnsi").map(String::from);
                    p.font_east = doc.attr(c, "w:eastAsia").map(String::from);
                    p.font_cs = doc.attr(c, "w:cs").map(String::from);
                    p.theme_ascii = doc.attr(c, "w:asciiTheme").map(String::from);
                    p.theme_hansi = doc.attr(c, "w:hAnsiTheme").map(String::from);
                    p.theme_east = doc.attr(c, "w:eastAsiaTheme").map(String::from);
                    p.theme_cs = doc.attr(c, "w:cstheme").map(String::from);
                }
                "w:sz" => p.size = int_attr(doc, c, "w:val").map(|v| v.max(1) as u32),
                "w:szCs" => p.size_cs = int_attr(doc, c, "w:val").map(|v| v.max(1) as u32),
                "w:b" => p.bold = Some(on_off(doc, c)),
                "w:i" => p.italic = Some(on_off(doc, c)),
                "w:caps" => p.caps = Some(on_off(doc, c)),
                "w:smallCaps" => p.small_caps = Some(on_off(doc, c)),
                "w:strike" => p.strike = Some(on_off(doc, c)),
                "w:dstrike" => p.dstrike = Some(on_off(doc, c)),
                "w:outline" => p.outline = Some(on_off(doc, c)),
                "w:shadow" => p.shadow = Some(on_off(doc, c)),
                "w:emboss" => p.emboss = Some(on_off(doc, c)),
                "w:imprint" => p.imprint = Some(on_off(doc, c)),
                "w:vanish" => p.vanish = Some(on_off(doc, c)),
                "w:rtl" => p.rtl = Some(on_off(doc, c)),
                "w:u" => {
                    p.underline = Some(doc.attr(c, "w:val").unwrap_or("single").to_string());
                    p.underline_color = doc.attr(c, "w:color").and_then(color_attr);
                }
                "w:color" => {
                    p.color = Some(match doc.attr(c, "w:val").and_then(color_attr) {
                        Some(v) => ColorVal::Rgb(v),
                        None => ColorVal::Auto,
                    });
                    p.theme_color = doc.attr(c, "w:themeColor").map(|t| format!("{}|{}|{}", t,
                        doc.attr(c, "w:themeShade").unwrap_or(""), doc.attr(c, "w:themeTint").unwrap_or("")));
                }
                "w:highlight" => p.highlight = doc.attr(c, "w:val").map(String::from),
                "w:shd" => {
                    p.shading = doc.attr(c, "w:fill").and_then(color_attr);
                }
                "w:vertAlign" => p.vert_align = doc.attr(c, "w:val").map(String::from),
                "w:position" => p.position = int_attr(doc, c, "w:val"),
                "w:spacing" => p.spacing = int_attr(doc, c, "w:val"),
                "w:w" => p.scale = int_attr(doc, c, "w:val").map(|v| v.max(1) as u32),
                "w:kern" => p.kern = int_attr(doc, c, "w:val").map(|v| v.max(0) as u32),
                "w:lang" => p.lang = doc.attr(c, "w:val").map(String::from),
                _ => {}
            }
        }
        p
    }

    /// Later formatting overrides earlier formatting.
    pub fn apply(&mut self, o: &RunProps) {
        merge_fields!(self, o, style, size, size_cs, caps, small_caps, strike, dstrike, outline,
            shadow, emboss, imprint, vanish, underline, underline_color, color, theme_color,
            highlight, shading, vert_align, position, spacing, scale, kern, lang, rtl, bold, italic);
        self.apply_fonts(o);
    }

    fn apply_fonts(&mut self, o: &RunProps) {
        // a font name replaces the theme font of the same slot and vice versa
        if o.font_ascii.is_some() || o.theme_ascii.is_some() {
            self.font_ascii = o.font_ascii.clone();
            self.theme_ascii = o.theme_ascii.clone();
        }
        if o.font_hansi.is_some() || o.theme_hansi.is_some() {
            self.font_hansi = o.font_hansi.clone();
            self.theme_hansi = o.theme_hansi.clone();
        }
        if o.font_east.is_some() || o.theme_east.is_some() {
            self.font_east = o.font_east.clone();
            self.theme_east = o.theme_east.clone();
        }
        if o.font_cs.is_some() || o.theme_cs.is_some() {
            self.font_cs = o.font_cs.clone();
            self.theme_cs = o.theme_cs.clone();
        }
    }

    fn toggles_mut(&mut self) -> [&mut Option<bool>; TOGGLES] {
        [&mut self.bold, &mut self.italic, &mut self.caps, &mut self.small_caps, &mut self.strike,
         &mut self.dstrike, &mut self.outline, &mut self.shadow, &mut self.emboss, &mut self.vanish]
    }

    fn toggles(&self) -> [Option<bool>; TOGGLES] {
        [self.bold, self.italic, self.caps, self.small_caps, self.strike, self.dstrike,
         self.outline, self.shadow, self.emboss, self.vanish]
    }

    /// Style formatting: toggle properties (bold, italic, ...) switch
    /// what's below them instead of setting it, as the original does.
    pub fn apply_style(&mut self, o: &RunProps) {
        let theirs = o.toggles();
        let mut tmp = o.clone();
        for t in tmp.toggles_mut() {
            *t = None;
        }
        self.apply(&tmp);
        for (mine, t) in self.toggles_mut().into_iter().zip(theirs) {
            if let Some(v) = t {
                *mine = Some(if v { !mine.unwrap_or(false) } else { false });
            }
        }
    }
}

// ------------------------------------------------------------------ paragraphs
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum TabKind {
    Left,
    Center,
    Right,
    Decimal,
    Bar,
    Clear,
}

#[derive(Clone, Debug, PartialEq)]
pub struct TabStop {
    /// twips from the paragraph's left indent origin (the margin)
    pub pos: i32,
    pub kind: TabKind,
    pub leader: char,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Border {
    pub style: String,
    /// eighths of a point
    pub size: u32,
    /// points
    pub space: u32,
    pub color: Option<u32>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ParaProps {
    pub style: Option<String>,
    pub jc: Option<String>,
    /// twips
    pub ind_left: Option<i32>,
    pub ind_right: Option<i32>,
    /// first line: positive = first-line indent, negative = hanging
    pub ind_first: Option<i32>,
    pub before: Option<i32>,
    pub after: Option<i32>,
    pub before_auto: Option<bool>,
    pub after_auto: Option<bool>,
    pub before_lines: Option<i32>,
    pub after_lines: Option<i32>,
    pub line: Option<i32>,
    pub line_rule: Option<String>,
    pub contextual: Option<bool>,
    pub keep_next: Option<bool>,
    pub keep_lines: Option<bool>,
    pub page_break_before: Option<bool>,
    pub widow: Option<bool>,
    pub tabs: Vec<TabStop>,
    pub outline_lvl: Option<u8>,
    pub num_id: Option<i32>,
    pub ilvl: Option<i32>,
    pub border_top: Option<Border>,
    pub border_bottom: Option<Border>,
    pub border_left: Option<Border>,
    pub border_right: Option<Border>,
    pub border_between: Option<Border>,
    pub shading: Option<u32>,
    pub bidi: Option<bool>,
    pub suppress_line_numbers: Option<bool>,
    pub suppress_hyphens: Option<bool>,
    pub mirror_indents: Option<bool>,
    pub snap_to_grid: Option<bool>,
    pub frame: Option<Frame>,
}

/// A text frame (w:framePr): paragraphs positioned like a floating text
/// box, or a drop cap.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Frame {
    /// twips (None: from the content)
    pub w: Option<i32>,
    pub h: Option<i32>,
    pub h_rule: String,
    pub x: Option<i32>,
    pub y: Option<i32>,
    pub x_align: Option<String>,
    pub y_align: Option<String>,
    /// text, margin, page
    pub h_anchor: String,
    pub v_anchor: String,
    /// around, notBeside, none, tight, through, auto
    pub wrap: String,
    pub h_space: i32,
    pub v_space: i32,
    /// drop, margin (drop caps), or empty
    pub drop_cap: String,
    pub lines: i32,
}

impl Frame {
    pub fn parse(doc: &XmlDoc, n: NodeId) -> Frame {
        let a = |k: &str| doc.attr(n, k).map(|s| s.to_string());
        Frame {
            w: int_attr(doc, n, "w:w"),
            h: int_attr(doc, n, "w:h"),
            h_rule: a("w:hRule").unwrap_or_else(|| "auto".into()),
            x: int_attr(doc, n, "w:x"),
            y: int_attr(doc, n, "w:y"),
            x_align: a("w:xAlign"),
            y_align: a("w:yAlign"),
            h_anchor: a("w:hAnchor").unwrap_or_else(|| "page".into()),
            v_anchor: a("w:vAnchor").unwrap_or_else(|| "page".into()),
            wrap: a("w:wrap").unwrap_or_else(|| "auto".into()),
            h_space: int_attr(doc, n, "w:hSpace").unwrap_or(0),
            v_space: int_attr(doc, n, "w:vSpace").unwrap_or(0),
            drop_cap: a("w:dropCap").filter(|v| v != "none").unwrap_or_default(),
            lines: int_attr(doc, n, "w:lines").unwrap_or(1).max(1),
        }
    }
}

pub fn parse_border(doc: &XmlDoc, n: NodeId) -> Border {
    Border {
        style: doc.attr(n, "w:val").unwrap_or("single").to_string(),
        size: int_attr(doc, n, "w:sz").unwrap_or(4).max(0) as u32,
        space: int_attr(doc, n, "w:space").unwrap_or(0).max(0) as u32,
        color: doc.attr(n, "w:color").and_then(color_attr),
    }
}

impl ParaProps {
    pub fn parse(doc: &XmlDoc, ppr: NodeId) -> ParaProps {
        let mut p = ParaProps::default();
        for c in doc.elements(ppr) {
            match doc.name(c) {
                "w:pStyle" => p.style = doc.attr(c, "w:val").map(String::from),
                "w:jc" => p.jc = doc.attr(c, "w:val").map(String::from),
                "w:ind" => {
                    p.ind_left = int_attr(doc, c, "w:left").or_else(|| int_attr(doc, c, "w:start"));
                    p.ind_right = int_attr(doc, c, "w:right").or_else(|| int_attr(doc, c, "w:end"));
                    if let Some(h) = int_attr(doc, c, "w:hanging") {
                        p.ind_first = Some(-h);
                    } else if let Some(f) = int_attr(doc, c, "w:firstLine") {
                        p.ind_first = Some(f);
                    }
                }
                "w:spacing" => {
                    p.before = int_attr(doc, c, "w:before");
                    p.after = int_attr(doc, c, "w:after");
                    p.line = int_attr(doc, c, "w:line");
                    p.line_rule = doc.attr(c, "w:lineRule").map(String::from);
                    p.before_auto = doc.attr(c, "w:beforeAutospacing").map(|v| v == "1" || v == "true" || v == "on");
                    p.after_auto = doc.attr(c, "w:afterAutospacing").map(|v| v == "1" || v == "true" || v == "on");
                    p.before_lines = int_attr(doc, c, "w:beforeLines");
                    p.after_lines = int_attr(doc, c, "w:afterLines");
                    if p.line.is_some() && p.line_rule.is_none() {
                        p.line_rule = Some("auto".into());
                    }
                }
                "w:contextualSpacing" => p.contextual = Some(on_off(doc, c)),
                "w:keepNext" => p.keep_next = Some(on_off(doc, c)),
                "w:keepLines" => p.keep_lines = Some(on_off(doc, c)),
                "w:pageBreakBefore" => p.page_break_before = Some(on_off(doc, c)),
                "w:widowControl" => p.widow = Some(on_off(doc, c)),
                "w:bidi" => p.bidi = Some(on_off(doc, c)),
                "w:suppressLineNumbers" => p.suppress_line_numbers = Some(on_off(doc, c)),
                "w:suppressAutoHyphens" => p.suppress_hyphens = Some(on_off(doc, c)),
                "w:mirrorIndents" => p.mirror_indents = Some(on_off(doc, c)),
                "w:snapToGrid" => p.snap_to_grid = Some(on_off(doc, c)),
                "w:framePr" => p.frame = Some(Frame::parse(doc, c)),
                "w:outlineLvl" => p.outline_lvl = int_attr(doc, c, "w:val").map(|v| v.clamp(0, 9) as u8),
                "w:numPr" => {
                    if let Some(i) = doc.child(c, "w:ilvl") {
                        p.ilvl = int_attr(doc, i, "w:val");
                    }
                    if let Some(i) = doc.child(c, "w:numId") {
                        p.num_id = int_attr(doc, i, "w:val");
                    }
                }
                "w:shd" => p.shading = doc.attr(c, "w:fill").and_then(color_attr),
                "w:pBdr" => {
                    for b in doc.elements(c) {
                        let bd = Some(parse_border(doc, b));
                        match doc.name(b) {
                            "w:top" => p.border_top = bd,
                            "w:bottom" => p.border_bottom = bd,
                            "w:left" | "w:start" => p.border_left = bd,
                            "w:right" | "w:end" => p.border_right = bd,
                            "w:between" => p.border_between = bd,
                            _ => {}
                        }
                    }
                }
                "w:tabs" => {
                    for t in doc.children_named(c, "w:tab") {
                        let kind = match doc.attr(t, "w:val").unwrap_or("left") {
                            "center" => TabKind::Center,
                            "right" | "end" => TabKind::Right,
                            "decimal" => TabKind::Decimal,
                            "bar" => TabKind::Bar,
                            "clear" => TabKind::Clear,
                            _ => TabKind::Left,
                        };
                        let leader = match doc.attr(t, "w:leader").unwrap_or("none") {
                            "dot" => '.',
                            "hyphen" => '-',
                            "underscore" | "heavy" => '_',
                            "middleDot" => '\u{b7}',
                            _ => ' ',
                        };
                        p.tabs.push(TabStop { pos: int_attr(doc, t, "w:pos").unwrap_or(0), kind, leader });
                    }
                }
                _ => {}
            }
        }
        p
    }

    pub fn apply(&mut self, o: &ParaProps) {
        merge_fields!(self, o, style, jc, ind_left, ind_right, ind_first, before, after,
            before_auto, after_auto, before_lines, after_lines, line, line_rule, contextual,
            keep_next, keep_lines, page_break_before, widow, outline_lvl, num_id, ilvl,
            border_top, border_bottom, border_left, border_right, border_between, shading, bidi,
            suppress_line_numbers, suppress_hyphens, mirror_indents, snap_to_grid, frame);
        // tab stops add up; a "clear" stop removes an inherited one
        for t in &o.tabs {
            self.tabs.retain(|x| x.pos != t.pos);
            if t.kind != TabKind::Clear {
                self.tabs.push(t.clone());
            } else {
                self.tabs.push(t.clone()); // remembered so later levels see it
            }
        }
        self.tabs.sort_by_key(|t| t.pos);
    }

    /// The tab stops that are in effect (clears removed).
    pub fn tab_stops(&self) -> Vec<TabStop> {
        self.tabs.iter().filter(|t| t.kind != TabKind::Clear).cloned().collect()
    }
}

// ---------------------------------------------------------------- tables
/// Table-level formatting (from w:tblPr or a table style).
#[derive(Clone, Debug, Default, PartialEq)]
pub struct TblProps {
    pub style: Option<String>,
    /// cell margins, twips: top, left, bottom, right
    pub cell_mar: [Option<i32>; 4],
    /// top, left, bottom, right, insideH, insideV
    pub borders: [Option<Border>; 6],
    pub cell_spacing: Option<i32>,
    pub jc: Option<String>,
    pub ind: Option<i32>,
    pub width: Option<(i32, String)>,
    pub layout_fixed: Option<bool>,
    pub shading: Option<u32>,
}

pub fn parse_side_set(doc: &XmlDoc, n: NodeId, out: &mut [Option<Border>; 6]) {
    for c in doc.elements(n) {
        let i = match doc.name(c) {
            "w:top" => 0,
            "w:left" | "w:start" => 1,
            "w:bottom" => 2,
            "w:right" | "w:end" => 3,
            "w:insideH" => 4,
            "w:insideV" => 5,
            _ => continue,
        };
        out[i] = Some(parse_border(doc, c));
    }
}

pub fn parse_margins(doc: &XmlDoc, n: NodeId, out: &mut [Option<i32>; 4]) {
    for c in doc.elements(n) {
        let i = match doc.name(c) {
            "w:top" => 0,
            "w:left" | "w:start" => 1,
            "w:bottom" => 2,
            "w:right" | "w:end" => 3,
            _ => continue,
        };
        if doc.attr(c, "w:type").map(|t| t == "dxa" || t == "nil").unwrap_or(true) {
            out[i] = int_attr(doc, c, "w:w");
        }
    }
}

impl TblProps {
    pub fn parse(doc: &XmlDoc, n: NodeId) -> TblProps {
        let mut t = TblProps::default();
        for c in doc.elements(n) {
            match doc.name(c) {
                "w:tblStyle" => t.style = doc.attr(c, "w:val").map(String::from),
                "w:tblCellMar" => parse_margins(doc, c, &mut t.cell_mar),
                "w:tblBorders" => parse_side_set(doc, c, &mut t.borders),
                "w:tblCellSpacing" => t.cell_spacing = int_attr(doc, c, "w:w"),
                "w:jc" => t.jc = doc.attr(c, "w:val").map(String::from),
                "w:tblInd" => t.ind = int_attr(doc, c, "w:w"),
                "w:tblW" => {
                    t.width = Some((int_attr(doc, c, "w:w").unwrap_or(0), doc.attr(c, "w:type").unwrap_or("dxa").to_string()))
                }
                "w:tblLayout" => t.layout_fixed = Some(doc.attr(c, "w:type") == Some("fixed")),
                "w:shd" => t.shading = parse_shd(doc, c),
                _ => {}
            }
        }
        t
    }

    pub fn apply(&mut self, o: &TblProps) {
        macro_rules! take {
            ($f:ident) => {
                if o.$f.is_some() {
                    self.$f = o.$f.clone();
                }
            };
        }
        take!(style);
        take!(cell_spacing);
        take!(jc);
        take!(ind);
        take!(width);
        take!(layout_fixed);
        take!(shading);
        for i in 0..4 {
            if o.cell_mar[i].is_some() {
                self.cell_mar[i] = o.cell_mar[i];
            }
        }
        for i in 0..6 {
            if o.borders[i].is_some() {
                self.borders[i] = o.borders[i].clone();
            }
        }
    }
}

/// Width of a border line in points (0 for none/nil).
pub fn border_width(b: &Option<Border>) -> f64 {
    match b {
        Some(b) if b.style != "nil" && b.style != "none" => {
            let w = b.size as f64 / 8.0;
            match b.style.as_str() {
                "double" => w * 3.0,
                "triple" => w * 5.0,
                _ => w,
            }
        }
        _ => 0.0,
    }
}

/// Cell-level formatting from a w:tcPr, or a table style's (conditional)
/// formatting.
#[derive(Clone, Debug, Default)]
pub struct CellFmt {
    pub ppr: ParaProps,
    pub rpr: RunProps,
    pub shading: Option<u32>,
    /// top, left, bottom, right, insideH, insideV
    pub borders: [Option<Border>; 6],
    pub v_align: Option<String>,
    pub has_ppr: bool,
    pub has_rpr: bool,
}

/// The fill colour of a w:shd (a solid pattern uses its colour).
pub fn parse_shd(doc: &XmlDoc, n: NodeId) -> Option<u32> {
    let val = doc.attr(n, "w:val").unwrap_or("clear");
    if val == "nil" {
        return None;
    }
    if val == "solid" {
        return doc.attr(n, "w:color").and_then(color_attr).or(Some(0));
    }
    doc.attr(n, "w:fill").and_then(color_attr)
}

impl CellFmt {
    /// From a w:tcPr (shading, borders, vertical alignment).
    pub fn parse_tc(doc: &XmlDoc, tcpr: NodeId) -> CellFmt {
        let mut f = CellFmt::default();
        for c in doc.elements(tcpr) {
            match doc.name(c) {
                "w:shd" => f.shading = parse_shd(doc, c),
                "w:tcBorders" => parse_side_set(doc, c, &mut f.borders),
                "w:vAlign" => f.v_align = doc.attr(c, "w:val").map(String::from),
                _ => {}
            }
        }
        f
    }

    /// A w:tblStylePr (or a table style's own pPr/rPr/tcPr).
    pub fn parse_style_part(doc: &XmlDoc, n: NodeId) -> CellFmt {
        let mut f = CellFmt::default();
        for c in doc.elements(n) {
            match doc.name(c) {
                "w:pPr" => {
                    f.ppr = ParaProps::parse(doc, c);
                    f.has_ppr = true;
                }
                "w:rPr" => {
                    f.rpr = RunProps::parse(doc, c);
                    f.has_rpr = true;
                }
                "w:tcPr" => {
                    let t = CellFmt::parse_tc(doc, c);
                    f.shading = t.shading;
                    f.borders = t.borders;
                    f.v_align = t.v_align;
                }
                "w:tblPr" => {
                    if let Some(b) = doc.child(c, "w:tblBorders") {
                        parse_side_set(doc, b, &mut f.borders);
                    }
                    if let Some(sh) = doc.child(c, "w:shd") {
                        f.shading = parse_shd(doc, sh);
                    }
                }
                _ => {}
            }
        }
        f
    }

    pub fn apply(&mut self, o: &CellFmt) {
        if o.has_ppr {
            self.ppr.apply(&o.ppr);
            self.has_ppr = true;
        }
        if o.has_rpr {
            self.rpr.apply(&o.rpr);
            self.has_rpr = true;
        }
        if o.shading.is_some() {
            self.shading = o.shading;
        }
        for i in 0..6 {
            if o.borders[i].is_some() {
                self.borders[i] = o.borders[i].clone();
            }
        }
        if o.v_align.is_some() {
            self.v_align = o.v_align.clone();
        }
    }
}

/// A theme colour reference ("accent1|BF|" as RunProps keeps it: name,
/// shade, tint) in a theme's colour scheme.
pub fn theme_color(colors: &std::collections::HashMap<String, u32>, spec: &str) -> Option<u32> {
    let mut it = spec.split('|');
    let name = it.next()?;
    let key = match name {
        "text1" | "dark1" => "dk1",
        "background1" | "light1" => "lt1",
        "text2" | "dark2" => "dk2",
        "background2" | "light2" => "lt2",
        "hyperlink" => "hlink",
        "followedHyperlink" => "folHlink",
        other => other,
    };
    let c = *colors.get(key)?;
    let shade = it.next().and_then(|v| u8::from_str_radix(v, 16).ok());
    let tint = it.next().and_then(|v| u8::from_str_radix(v, 16).ok());
    if shade.is_none() && tint.is_none() {
        return Some(c);
    }
    // in HSL: the luminance darkened (shade) or lightened (tint)
    let (r, g, b) = (((c >> 16) & 255) as f64 / 255.0, ((c >> 8) & 255) as f64 / 255.0, (c & 255) as f64 / 255.0);
    let (mx, mn) = (r.max(g).max(b), r.min(g).min(b));
    let mut l = (mx + mn) / 2.0;
    let d = mx - mn;
    let s = if d == 0.0 { 0.0 } else { d / (1.0 - (2.0 * l - 1.0).abs()) };
    let h = if d == 0.0 {
        0.0
    } else if mx == r {
        60.0 * (((g - b) / d).rem_euclid(6.0))
    } else if mx == g {
        60.0 * ((b - r) / d + 2.0)
    } else {
        60.0 * ((r - g) / d + 4.0)
    };
    if let Some(sh) = shade {
        l *= sh as f64 / 255.0;
    }
    if let Some(t) = tint {
        let t = t as f64 / 255.0;
        l = l * t + (1.0 - t);
    }
    let cc = (1.0 - (2.0 * l - 1.0).abs()) * s;
    let x = cc * (1.0 - ((h / 60.0).rem_euclid(2.0) - 1.0).abs());
    let m = l - cc / 2.0;
    let (r1, g1, b1) = match (h / 60.0) as i32 {
        0 => (cc, x, 0.0),
        1 => (x, cc, 0.0),
        2 => (0.0, cc, x),
        3 => (0.0, x, cc),
        4 => (x, 0.0, cc),
        _ => (cc, 0.0, x),
    };
    let to = |v: f64| ((v + m).clamp(0.0, 1.0) * 255.0).round() as u32;
    Some(to(r1) << 16 | to(g1) << 8 | to(b1))
}
