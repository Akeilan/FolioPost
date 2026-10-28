//! From resolved run formatting to measured text: which font each
//! character is drawn with, its size, and the shaped glyphs.

use crate::fonts::{Font, FontCache, Glyph};
use crate::props::{ColorVal, RunProps};
use crate::styles::StyleSheet;
use std::sync::Arc;

#[derive(Clone, Debug, PartialEq)]
pub struct TextStyle {
    pub size: f64,
    pub bold: bool,
    pub italic: bool,
    /// None = automatic (black, or white on dark shading)
    pub color: Option<u32>,
    pub underline: Option<String>,
    pub underline_color: Option<u32>,
    pub strike: bool,
    pub dstrike: bool,
    pub highlight: Option<u32>,
    pub shading: Option<u32>,
    pub caps: bool,
    pub small_caps: bool,
    pub hidden: bool,
    /// points the baseline is raised (negative: lowered)
    pub raise: f64,
    /// size the glyphs are drawn at (smaller for super/subscript)
    pub draw_size: f64,
    /// extra space after each character, points
    pub spacing: f64,
    pub scale: f64,
    pub kern: bool,
    pub outline: bool,
    pub shadow: bool,
    pub emboss: bool,
    pub imprint: bool,
    pub change: u8,
}

pub fn highlight_color(name: &str) -> Option<u32> {
    Some(match name {
        "yellow" => 0xFFFF00,
        "green" => 0x00FF00,
        "cyan" => 0x00FFFF,
        "magenta" => 0xFF00FF,
        "blue" => 0x0000FF,
        "red" => 0xFF0000,
        "darkBlue" => 0x000080,
        "darkCyan" => 0x008080,
        "darkGreen" => 0x008000,
        "darkMagenta" => 0x800080,
        "darkRed" => 0x800000,
        "darkYellow" => 0x808000,
        "darkGray" => 0x808080,
        "lightGray" => 0xC0C0C0,
        "black" => 0x000000,
        "white" => 0xFFFFFF,
        _ => return None,
    })
}

impl TextStyle {
    pub fn from_props(r: &RunProps) -> TextStyle {
        let size = r.size.unwrap_or(20) as f64 / 2.0;
        let va = r.vert_align.as_deref().unwrap_or("baseline");
        let small = va == "superscript" || va == "subscript";
        // the original draws super/subscript at two thirds of the size
        let draw_size = if small { size * 2.0 / 3.0 } else { size };
        let mut raise = r.position.unwrap_or(0) as f64 / 2.0;
        if va == "superscript" {
            raise += size / 3.0;
        } else if va == "subscript" {
            raise -= size / 7.0;
        }
        let ul = r.underline.clone().filter(|u| u != "none");
        TextStyle {
            size,
            bold: r.bold.unwrap_or(false),
            italic: r.italic.unwrap_or(false),
            color: match &r.color {
                Some(ColorVal::Rgb(c)) => Some(*c),
                _ => None,
            },
            underline: ul,
            underline_color: r.underline_color,
            strike: r.strike.unwrap_or(false),
            dstrike: r.dstrike.unwrap_or(false),
            highlight: r.highlight.as_deref().and_then(highlight_color),
            shading: r.shading,
            caps: r.caps.unwrap_or(false),
            small_caps: r.small_caps.unwrap_or(false),
            hidden: r.vanish.unwrap_or(false),
            raise,
            draw_size,
            spacing: r.spacing.unwrap_or(0) as f64 / 20.0,
            scale: r.scale.unwrap_or(100) as f64 / 100.0,
            kern: r.kern.map(|k| k > 0 && size * 2.0 >= k as f64).unwrap_or(false),
            outline: r.outline.unwrap_or(false),
            shadow: r.shadow.unwrap_or(false),
            emboss: r.emboss.unwrap_or(false),
            imprint: r.imprint.unwrap_or(false),
            change: 0,
        }
    }
}

#[derive(Clone, Copy, PartialEq, Debug)]
enum Slot {
    Ascii,
    HAnsi,
    East,
    Cs,
}

fn slot_of(ch: char) -> Slot {
    let c = ch as u32;
    if c < 0x80 {
        return Slot::Ascii;
    }
    match c {
        0x0590..=0x08FF | 0xFB1D..=0xFDFF | 0xFE70..=0xFEFF => Slot::Cs,
        0x0E00..=0x0E7F => Slot::Cs,
        0x1100..=0x11FF | 0x2E80..=0x9FFF | 0xA960..=0xA97F | 0xAC00..=0xD7FF | 0xF900..=0xFAFF
        | 0xFF00..=0xFFEF | 0x20000..=0x2FFFF => Slot::East,
        _ => Slot::HAnsi,
    }
}

/// The font family a run asks for, for a character.
pub fn family_for(styles: &StyleSheet, r: &RunProps, ch: char) -> String {
    let (font, theme) = match slot_of(ch) {
        Slot::Ascii => (&r.font_ascii, &r.theme_ascii),
        Slot::HAnsi => (&r.font_hansi, &r.theme_hansi),
        Slot::East => (&r.font_east, &r.theme_east),
        Slot::Cs => (&r.font_cs, &r.theme_cs),
    };
    if let Some(t) = theme {
        if let Some(f) = styles.theme_font(t) {
            return f;
        }
    }
    if let Some(f) = font {
        return f.clone();
    }
    // fall back to the other slots, then to the original's default
    for (f, t) in [(&r.font_hansi, &r.theme_hansi), (&r.font_ascii, &r.theme_ascii)] {
        if let Some(t) = t {
            if let Some(f) = styles.theme_font(t) {
                return f;
            }
        }
        if let Some(f) = f {
            return f.clone();
        }
    }
    "Times New Roman".into()
}

/// A stretch of characters drawn with one font and style.
#[derive(Clone, Debug)]
pub struct Shaped {
    pub font: Arc<Font>,
    pub style: TextStyle,
    pub text: Vec<char>,
    pub glyphs: Vec<Glyph>,
    /// advance of each character (points, spacing and scale included)
    pub widths: Vec<f64>,
    /// for each character, the range of glyphs drawn for it
    pub glyph_of: Vec<(u32, u32)>,
}

/// Shape a string with one style: split by the fonts the characters need,
/// measure every character.
pub fn shape_text(fonts: &mut FontCache, styles: &StyleSheet, r: &RunProps, style: &TextStyle,
                  text: &str) -> Vec<Shaped> {
    let mut out = Vec::new();
    let chars: Vec<char> = text.chars().collect();
    if chars.is_empty() {
        return out;
    }
    // characters as drawn (caps)
    let drawn: Vec<char> = chars
        .iter()
        .map(|&c| if style.caps || style.small_caps { c.to_uppercase().next().unwrap_or(c) } else { c })
        .collect();
    // the font each character is drawn with
    let mut fid: Vec<Arc<Font>> = Vec::with_capacity(chars.len());
    let mut last: Option<(String, Arc<Font>)> = None;
    for (i, &c) in chars.iter().enumerate() {
        let fam = family_for(styles, r, c);
        let base = match &last {
            Some((f, font)) if *f == fam => font.clone(),
            _ => {
                let f = fonts.get(&fam, style.bold, style.italic);
                last = Some((fam.clone(), f.clone()));
                f
            }
        };
        let d = drawn[i];
        let needs = !d.is_control() && !d.is_whitespace() && d != '\u{ad}' && !base.has_char(d);
        let f = if needs { fonts.fallback(d, style.bold, style.italic).unwrap_or(base) } else { base };
        fid.push(f);
    }
    let mut start = 0;
    while start < chars.len() {
        let mut end = start + 1;
        while end < chars.len() && fid[end].id == fid[start].id {
            end += 1;
        }
        out.push(shape_one(&fid[start], style, &drawn[start..end], &chars[start..end]));
        start = end;
    }
    out
}

fn shape_one(font: &Arc<Font>, style: &TextStyle, drawn: &[char], orig: &[char]) -> Shaped {
    // small caps: lowercase letters drawn smaller
    let s: String = drawn.iter().collect();
    let size = style.draw_size;
    let glyphs = font.shape(&s, size, style.kern, false);
    // byte offset of each char
    let mut byte_of = Vec::with_capacity(drawn.len() + 1);
    let mut b = 0u32;
    for c in drawn {
        byte_of.push(b);
        b += c.len_utf8() as u32;
    }
    byte_of.push(b);
    let mut widths = vec![0.0; drawn.len()];
    let mut glyph_of = vec![(0u32, 0u32); drawn.len()];
    // glyphs come in cluster order (left to right text)
    let char_at = |cluster: u32| -> usize {
        match byte_of.binary_search(&cluster) {
            Ok(i) => i.min(drawn.len().saturating_sub(1)),
            Err(i) => i.saturating_sub(1),
        }
    };
    let mut gi = 0;
    while gi < glyphs.len() {
        let cl = glyphs[gi].cluster;
        let ci = char_at(cl);
        let mut gj = gi;
        let mut adv = 0.0;
        while gj < glyphs.len() && glyphs[gj].cluster == cl {
            adv += glyphs[gj].advance;
            gj += 1;
        }
        // characters of this cluster: up to the next cluster's character
        let next_ci = if gj < glyphs.len() { char_at(glyphs[gj].cluster) } else { drawn.len() };
        let n = (next_ci.max(ci + 1) - ci).max(1);
        for k in 0..n {
            if ci + k < drawn.len() {
                widths[ci + k] = adv / n as f64;
                glyph_of[ci + k] = if k == 0 { (gi as u32, gj as u32) } else { (gj as u32, gj as u32) };
            }
        }
        gi = gj;
    }
    let mut out_glyphs = glyphs;
    if style.scale != 1.0 {
        for g in out_glyphs.iter_mut() {
            g.advance *= style.scale;
            g.x_offset *= style.scale;
        }
        for w in widths.iter_mut() {
            *w *= style.scale;
        }
    }
    if style.spacing != 0.0 {
        for w in widths.iter_mut() {
            *w += style.spacing;
        }
    }
    // soft hyphens take no room unless the line breaks there
    for (i, c) in orig.iter().enumerate() {
        if *c == '\u{ad}' {
            widths[i] = 0.0;
        }
    }
    Shaped { font: font.clone(), style: style.clone(), text: orig.to_vec(), glyphs: out_glyphs, widths, glyph_of }
}
