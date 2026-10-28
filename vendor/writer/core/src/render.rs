//! Drawing pages with cairo: text with the fonts the layout measured,
//! highlighting, underlines, tab leaders, tracked changes, table cell
//! boxes and selections.

use crate::fonts::{Font, FontCache};
use crate::layout::{glyph_range, Line, ParaLayout, UnitKind};
use crate::paginate::{Layout, Page};
use crate::text::{Shaped, TextStyle};
use std::collections::HashMap;
use std::sync::Arc;

/// Colour of insertions/deletions by tracked-change author (Word's first
/// author colour).
const CHANGE_COLOR: u32 = 0xB5082E;

fn rgb(cr: &cairo::Context, c: u32) {
    cr.set_source_rgb(((c >> 16) & 255) as f64 / 255.0, ((c >> 8) & 255) as f64 / 255.0, (c & 255) as f64 / 255.0);
}

/// cairo font faces for our fonts (FreeType, from the same files the layout
/// measured).
pub struct Renderer {
    lib: Option<freetype::Library>,
    faces: HashMap<usize, cairo::FontFace>,
    /// decoded pictures by part name (None: can't be decoded)
    pics: HashMap<String, Option<cairo::ImageSurface>>,
    /// longest side pictures are decoded at
    pub max_px: u32,
}

impl Default for Renderer {
    fn default() -> Self {
        Self::new()
    }
}

/// What to draw on top of the text.
#[derive(Default, Clone)]
pub struct Overlay {
    /// selection rectangles (page coordinates, points)
    pub selection: Vec<(f64, f64, f64, f64)>,
    /// caret: x, y, height
    pub caret: Option<(f64, f64, f64)>,
    /// draw the text boundaries / cell gridlines like the original's
    /// "Show text boundaries" and table gridlines
    pub gridlines: bool,
    /// Show/Hide ¶: spaces, tabs, breaks and paragraph marks
    pub marks: bool,
    /// paragraphs ending a section, with the label of the break
    pub sect_breaks: HashMap<crate::xml::NodeId, String>,
}

impl Renderer {
    pub fn new() -> Renderer {
        Renderer { lib: freetype::Library::init().ok(), faces: HashMap::new(), pics: HashMap::new(), max_px: 2400 }
    }

    fn face(&mut self, f: &Font) -> Option<cairo::FontFace> {
        if let Some(ff) = self.faces.get(&f.id) {
            return Some(ff.clone());
        }
        let lib = self.lib.as_ref()?;
        let face = if f.path.as_os_str().is_empty() {
            lib.new_memory_face(std::rc::Rc::new(f.data().to_vec()), f.index as isize).ok()?
        } else {
            lib.new_face(&f.path, f.index as isize).ok()?
        };
        let ff = cairo::FontFace::create_from_ft(&face).ok()?;
        self.faces.insert(f.id, ff.clone());
        Some(ff)
    }

    /// Draw a page at `scale` (pixels per point) into a context whose origin
    /// is the page's top-left corner.
    pub fn draw_page(&mut self, cr: &cairo::Context, layout: &Layout, page: &Page, fonts: &mut FontCache,
                     ov: &Overlay) {
        cr.save().ok();
        match page.background {
            Some(c) => cr.set_source_rgb(((c >> 16) & 255) as f64 / 255.0, ((c >> 8) & 255) as f64 / 255.0, (c & 255) as f64 / 255.0),
            None => cr.set_source_rgb(1.0, 1.0, 1.0),
        }
        cr.rectangle(0.0, 0.0, page.width, page.height);
        cr.fill().ok();
        if let Some(f) = &page.fill {
            self.draw_page_fill(cr, f, page.width, page.height);
        }
        let text_box = (page.left, page.top, page.width - page.right, page.height - page.bottom);
        if let Some(b) = page.borders.as_ref().filter(|b| !b.front) {
            crate::art::draw(cr, b, page.width, page.height, text_box);
        }
        // objects behind the text
        let mut order: Vec<usize> = (0..page.floats.len()).collect();
        order.sort_by_key(|&i| page.floats[i].float.z);
        for &i in &order {
            if page.floats[i].float.behind {
                self.draw_float(cr, layout, &page.floats[i], fonts);
            }
        }
        // table cells: shading, then borders (gridlines where there are none)
        draw_cells(cr, &page.cells, ov.gridlines);
        draw_cells(cr, &page.hf_cells, ov.gridlines);
        // paragraph shading and borders
        for b in &page.boxes {
            let pp = &layout.paras[b.para].props;
            if let Some(c) = pp.shading {
                rgb(cr, c);
                cr.rectangle(b.x0, b.y0, b.x1 - b.x0, b.y1 - b.y0);
                cr.fill().ok();
            }
            let side = |cr: &cairo::Context, bd: &Option<crate::props::Border>, x0: f64, y0: f64, x1: f64, y1: f64| {
                let w = crate::props::border_width(bd);
                if let (Some(b), true) = (bd, w > 0.0) {
                    stroke_border(cr, b, w, x0, y0, x1, y1);
                }
            };
            if b.top {
                let w = crate::props::border_width(&pp.border_top);
                side(cr, &pp.border_top, b.x0, b.y0 + w / 2.0, b.x1, b.y0 + w / 2.0);
            }
            if b.between {
                let w = crate::props::border_width(&pp.border_between);
                side(cr, &pp.border_between, b.x0, b.y0 + w / 2.0, b.x1, b.y0 + w / 2.0);
            }
            if b.bottom {
                let w = crate::props::border_width(&pp.border_bottom);
                side(cr, &pp.border_bottom, b.x0, b.y1 - w / 2.0, b.x1, b.y1 - w / 2.0);
            }
            let wl = crate::props::border_width(&pp.border_left);
            side(cr, &pp.border_left, b.x0 + wl / 2.0, b.y0, b.x0 + wl / 2.0, b.y1);
            let wr = crate::props::border_width(&pp.border_right);
            side(cr, &pp.border_right, b.x1 - wr / 2.0, b.y0, b.x1 - wr / 2.0, b.y1);
        }
        // headers, footers, notes and their separators
        cr.set_source_rgb(0.0, 0.0, 0.0);
        cr.set_line_width(0.5);
        for (x0, y, x1) in &page.rules {
            cr.move_to(*x0, *y);
            cr.line_to(*x1, *y);
            cr.stroke().ok();
        }
        for pl in page.hf_lines.iter().chain(page.note_lines.iter()) {
            let p = &layout.paras[pl.para];
            let line = &p.lines[pl.line];
            draw_backgrounds(cr, p, line, pl.x, pl.y);
        }
        for pl in page.hf_lines.iter().chain(page.note_lines.iter()) {
            let p = &layout.paras[pl.para];
            let line = &p.lines[pl.line];
            self.draw_line(cr, p, line, pl.x, pl.y, fonts);
        }
        // change bars in the left margin
        if layout.markup != crate::document::Markup::Final && layout.markup != crate::document::Markup::Original {
            let simple = layout.markup == crate::document::Markup::Simple;
            if simple {
                cr.set_source_rgb(0.85, 0.1, 0.1);
            } else {
                cr.set_source_rgb(0.45, 0.45, 0.45);
            }
            cr.set_line_width(if simple { 1.0 } else { 0.75 });
            let bar_x = page.left - 14.0;
            for pl in &page.lines {
                let p = &layout.paras[pl.para];
                if p.line_changed(pl.line) {
                    let h = p.lines[pl.line].height;
                    cr.move_to(bar_x, pl.y);
                    cr.line_to(bar_x, pl.y + h);
                    cr.stroke().ok();
                }
            }
        }
        // backgrounds first so text is never covered
        for pl in &page.lines {
            let p = &layout.paras[pl.para];
            let line = &p.lines[pl.line];
            let turned = enter_frame(cr, pl);
            draw_backgrounds(cr, p, line, pl.x, pl.y);
            if turned {
                cr.restore().ok();
            }
        }
        for (x, y, w, h) in &ov.selection {
            cr.set_source_rgba(0.62, 0.75, 0.93, 0.55);
            cr.rectangle(*x, *y, *w, *h);
            cr.fill().ok();
        }
        for pl in &page.lines {
            let p = &layout.paras[pl.para];
            let line = &p.lines[pl.line];
            let turned = enter_frame(cr, pl);
            self.draw_line(cr, p, line, pl.x, pl.y, fonts);
            if turned {
                cr.restore().ok();
            }
        }
        for &i in &order {
            if !page.floats[i].float.behind {
                self.draw_float(cr, layout, &page.floats[i], fonts);
            }
        }
        if let Some(b) = page.borders.as_ref().filter(|b| b.front) {
            crate::art::draw(cr, b, page.width, page.height, text_box);
        }
        if !page.line_numbers.is_empty() {
            let font = fonts.get(&layout_default_font(layout), false, false);
            if let Some(ff) = self.face(&font) {
                cr.set_font_face(&ff);
                cr.set_source_rgb(0.0, 0.0, 0.0);
                for (x, y, n, size) in &page.line_numbers {
                    cr.set_font_size(*size);
                    let t = n.to_string();
                    let w = cr.text_extents(&t).map(|e| e.x_advance()).unwrap_or(0.0);
                    cr.move_to(x - w, *y);
                    cr.show_text(&t).ok();
                }
            }
        }
        if ov.marks {
            for pl in page.lines.iter().chain(page.hf_lines.iter()).chain(page.note_lines.iter()) {
                let turned = enter_frame(cr, pl);
                draw_marks(cr, &layout.paras[pl.para], pl, ov);
                if turned {
                    cr.restore().ok();
                }
            }
        }
        if let Some((x, y, h)) = ov.caret {
            cr.set_source_rgb(0.0, 0.0, 0.0);
            cr.set_line_width(1.0);
            cr.move_to(x.round() + 0.5, y);
            cr.line_to(x.round() + 0.5, y + h);
            cr.stroke().ok();
        }
        cr.restore().ok();
    }

    fn draw_line(&mut self, cr: &cairo::Context, p: &ParaLayout, line: &Line, x0: f64, y0: f64,
                 fonts: &mut FontCache) {
        let base_y = y0 + line.baseline;
        // clip lines with exact height
        let exact = p.props.line_rule.as_deref() == Some("exact")
            && p.props.frame.as_ref().map_or(true, |f| f.drop_cap.is_empty());
        if exact {
            cr.save().ok();
            cr.rectangle(x0 - 1000.0, y0, 4000.0, line.height);
            cr.clip();
        }
        // tab leaders
        for t in &line.tabs {
            let mark = &p.mark_style;
            let fam_font = p.units.get(line.start).and_then(|u| {
                if u.shaped != u32::MAX {
                    Some(p.shaped[u.shaped as usize].font.clone())
                } else {
                    None
                }
            });
            let font = fam_font.unwrap_or_else(|| fonts.get("Times New Roman", mark.bold, mark.italic));
            self.draw_leader(cr, &font, mark.size, t.leader, x0 + t.x, t.width, base_y, mark.color.unwrap_or(0));
        }
        // runs of units drawn with one shaped stretch
        let mut i = line.start;
        while i < line.end {
            let u = &p.units[i];
            if u.shaped == u32::MAX {
                if u.kind == UnitKind::Math {
                    let k = i - line.start;
                    let x = x0 + line.xs[k];
                    if let Some(mb) = p.maths.get(u.idx as usize) {
                        let mb = mb.clone();
                        crate::math::draw(cr, &mb, x, base_y, &mut |f| self.face(f));
                    }
                }
                if u.kind == UnitKind::Object {
                    let k = i - line.start;
                    let x = x0 + line.xs[k];
                    let (w, h) = u.obj;
                    if let Some(crate::document::Item::Object(_, _, pic)) = p.pieces.get(u.piece as usize).map(|pc| &pc.item) {
                        self.draw_pic(cr, pic, x, base_y - h);
                    } else {
                        placeholder(cr, x, base_y - h, w, h, "object");
                    }
                }
                i += 1;
                continue;
            }
            let si = u.shaped;
            let mut j = i + 1;
            while j < line.end && p.units[j].shaped == si {
                j += 1;
            }
            let sh = &p.shaped[si as usize];
            self.draw_run(cr, p, line, sh, i, j, x0, base_y);
            i = j;
        }
        // a word hyphenated at the line's end
        if line.hyphen > 0.0 && line.end > line.start {
            let k = line.end - 1;
            let u = &p.units[k];
            if u.shaped != u32::MAX {
                let sh = &p.shaped[u.shaped as usize];
                let x = x0 + line.xs[k - line.start] + line.ws[k - line.start];
                let st = &sh.style;
                let gl = sh.font.shape("-", 1.0, false, false);
                if let (Some(g), Some(face)) = (gl.first(), self.face(&sh.font)) {
                    cr.save().ok();
                    cr.set_font_face(&face);
                    cr.set_font_matrix(cairo::Matrix::new(st.draw_size * st.scale, 0.0, 0.0, st.draw_size, 0.0, 0.0));
                    let c = if st.change != 0 { CHANGE_COLOR } else { st.color.unwrap_or(0) };
                    rgb(cr, c);
                    cr.show_glyphs(&[cairo::Glyph::new(g.gid as _, x, base_y - st.raise)]).ok();
                    cr.restore().ok();
                }
            }
        }
        if exact {
            cr.restore().ok();
        }
    }

    #[allow(clippy::too_many_arguments)]
    fn draw_run(&mut self, cr: &cairo::Context, p: &ParaLayout, line: &Line, sh: &Shaped, a: usize, b: usize,
                x0: f64, base_y: f64) {
        let st = &sh.style;
        let color = if st.change != 0 { CHANGE_COLOR } else { st.color.unwrap_or(0) };
        let y = base_y - st.raise;
        let mut glyphs: Vec<cairo::Glyph> = Vec::new();
        for k in a..b {
            let u = &p.units[k];
            if let UnitKind::Char(c) = u.kind {
                if c == '\u{ad}' {
                    continue;
                }
            }
            let (g0, g1) = sh.glyph_of[u.idx as usize];
            let mut gx = x0 + line.xs[k - line.start];
            for g in &sh.glyphs[g0 as usize..g1 as usize] {
                glyphs.push(cairo::Glyph::new(g.gid as _, gx + g.x_offset, y - g.y_offset));
                gx += g.advance;
            }
        }
        if !glyphs.is_empty() {
            if let Some(face) = self.face(&sh.font) {
                cr.save().ok();
                cr.set_font_face(&face);
                let size = st.draw_size;
                let mut m = cairo::Matrix::new(size * st.scale, 0.0, 0.0, size, 0.0, 0.0);
                if st.italic && sh.font.synth_italic {
                    m = cairo::Matrix::new(size * st.scale, 0.0, -0.2 * size, size, 0.0, 0.0);
                }
                cr.set_font_matrix(m);
                let mut fo = cairo::FontOptions::new().unwrap();
                fo.set_hint_style(cairo::HintStyle::None);
                fo.set_hint_metrics(cairo::HintMetrics::Off);
                fo.set_antialias(cairo::Antialias::Gray);
                cr.set_font_options(&fo);
                rgb(cr, color);
                if st.outline || st.emboss || st.imprint {
                    cr.glyph_path(&glyphs);
                    cr.set_line_width(size / 30.0);
                    if st.outline {
                        cr.stroke().ok();
                    } else {
                        cr.set_source_rgb(1.0, 1.0, 1.0);
                        cr.fill_preserve().ok();
                        rgb(cr, if st.emboss { 0x808080 } else { 0x404040 });
                        cr.stroke().ok();
                    }
                } else {
                    if st.shadow {
                        cr.save().ok();
                        cr.translate(size / 18.0, size / 18.0);
                        cr.set_source_rgb(0.55, 0.55, 0.55);
                        cr.show_glyphs(&glyphs).ok();
                        cr.restore().ok();
                        rgb(cr, color);
                    }
                    if st.bold && sh.font.synth_bold {
                        cr.glyph_path(&glyphs);
                        cr.set_line_width(size / 28.0);
                        cr.fill_preserve().ok();
                        cr.stroke().ok();
                    } else {
                        cr.show_glyphs(&glyphs).ok();
                    }
                }
                cr.restore().ok();
            }
        }
        // decorations
        let xa = x0 + line.xs[a - line.start];
        let mut eb = b;
        // trailing spaces at the end of the line are not underlined
        if b == line.end {
            while eb > a && matches!(p.units[eb - 1].kind, UnitKind::Char(' ')) {
                eb -= 1;
            }
        }
        if eb <= a {
            return;
        }
        let xb = x0 + line.xs[eb - 1 - line.start] + line.ws[eb - 1 - line.start];
        let f = &sh.font;
        let size = st.draw_size;
        let thick = (f.underline_thick * size / f.upem).max(0.5);
        let ul = if st.change == 1 && st.underline.is_none() { Some("single".to_string()) } else { st.underline.clone() };
        if let Some(kind) = ul {
            let uy = y - f.underline_pos * size / f.upem;
            let uc = if st.change != 0 { CHANGE_COLOR } else { st.underline_color.unwrap_or(color) };
            rgb(cr, uc);
            draw_underline(cr, &kind, xa, xb, uy, thick, p, line, a, eb);
        }
        if st.strike || st.dstrike || st.change == 2 {
            let sy = y - f.strike_pos * size / f.upem;
            rgb(cr, color);
            cr.set_line_width(thick);
            if st.dstrike {
                for d in [-thick, thick] {
                    cr.move_to(xa, sy + d);
                    cr.line_to(xb, sy + d);
                }
            } else {
                cr.move_to(xa, sy);
                cr.line_to(xb, sy);
            }
            cr.stroke().ok();
        }
    }

    #[allow(clippy::too_many_arguments)]
    fn draw_leader(&mut self, cr: &cairo::Context, font: &Arc<Font>, size: f64, leader: char, x: f64, w: f64,
                   base_y: f64, color: u32) {
        if w <= 0.0 {
            return;
        }
        if leader == '_' {
            rgb(cr, color);
            cr.set_line_width((font.underline_thick * size / font.upem).max(0.5));
            let uy = base_y - font.underline_pos * size / font.upem;
            cr.move_to(x, uy);
            cr.line_to(x + w, uy);
            cr.stroke().ok();
            return;
        }
        let glyphs = font.shape(&leader.to_string(), size, false, false);
        let Some(g) = glyphs.first() else { return };
        if g.advance <= 0.0 {
            return;
        }
        // the original aligns leader characters to a grid of their width
        let start = ((x / g.advance).ceil() * g.advance).max(x);
        let mut gs = Vec::new();
        let mut gx = start;
        while gx + g.advance <= x + w + 0.01 {
            gs.push(cairo::Glyph::new(g.gid as _, gx, base_y));
            gx += g.advance;
        }
        if gs.is_empty() {
            return;
        }
        if let Some(face) = self.face(font) {
            cr.save().ok();
            cr.set_font_face(&face);
            cr.set_font_size(size);
            rgb(cr, color);
            cr.show_glyphs(&gs).ok();
            cr.restore().ok();
        }
    }
}

/// A border line of the given style between two points.
#[allow(clippy::too_many_arguments)]
pub fn stroke_border(cr: &cairo::Context, b: &crate::props::Border, w: f64, x0: f64, y0: f64, x1: f64, y1: f64) {
    let c = b.color.unwrap_or(0);
    rgb(cr, c);
    let horiz = (y1 - y0).abs() < (x1 - x0).abs();
    let style = b.style.as_str();
    let line = |cr: &cairo::Context, off: f64, lw: f64| {
        cr.set_line_width(lw);
        if horiz {
            cr.move_to(x0, y0 + off);
            cr.line_to(x1, y1 + off);
        } else {
            cr.move_to(x0 + off, y0);
            cr.line_to(x1 + off, y1);
        }
        cr.stroke().ok();
    };
    match style {
        "double" => {
            let t = w / 3.0;
            line(cr, -t, t);
            line(cr, t, t);
        }
        "dotted" => {
            cr.set_dash(&[w, w], 0.0);
            line(cr, 0.0, w);
            cr.set_dash(&[], 0.0);
        }
        "dashed" | "dashSmallGap" | "dotDash" | "dotDotDash" => {
            cr.set_dash(&[w * 3.0, w * 2.0], 0.0);
            line(cr, 0.0, w);
            cr.set_dash(&[], 0.0);
        }
        _ => line(cr, 0.0, w),
    }
}

#[allow(clippy::too_many_arguments)]
fn draw_underline(cr: &cairo::Context, kind: &str, xa: f64, xb: f64, uy: f64, thick: f64, p: &ParaLayout,
                  line: &Line, a: usize, b: usize) {
    let segments: Vec<(f64, f64)> = if kind == "words" {
        // only under words, not spaces
        let mut v = Vec::new();
        let mut s: Option<f64> = None;
        for k in a..b {
            let x = line.xs[k - line.start];
            let is_sp = matches!(p.units[k].kind, UnitKind::Char(' ') | UnitKind::Tab);
            match (is_sp, s) {
                (false, None) => s = Some(x),
                (true, Some(st)) => {
                    v.push((st, x));
                    s = None;
                }
                _ => {}
            }
        }
        if let Some(st) = s {
            v.push((st, xb - line.xs[0] + line.xs[0]));
        }
        v.into_iter().map(|(s, e)| (s + xa - line.xs[a - line.start], e + xa - line.xs[a - line.start])).collect()
    } else {
        vec![(xa, xb)]
    };
    let k = kind.to_ascii_lowercase();
    let w = if k.contains("thick") || k.contains("heavy") { thick * 2.0 } else { thick };
    cr.set_line_width(w);
    if k.contains("dotted") || k.contains("dot") && !k.contains("dash") {
        cr.set_dash(&[w, w * 2.0], 0.0);
    } else if k.contains("dashlong") {
        cr.set_dash(&[w * 8.0, w * 3.0], 0.0);
    } else if k.contains("dash") {
        cr.set_dash(&[w * 4.0, w * 3.0], 0.0);
    }
    for (s, e) in segments {
        if k.contains("wave") {
            let amp = w * 1.2;
            let step = w * 3.0;
            cr.move_to(s, uy);
            let mut x = s;
            let mut up = true;
            while x < e {
                let nx = (x + step).min(e);
                cr.curve_to(x + step / 2.0, uy + if up { -amp } else { amp }, x + step / 2.0,
                            uy + if up { -amp } else { amp }, nx, uy);
                x = nx;
                up = !up;
            }
        } else if k == "double" {
            cr.move_to(s, uy - w);
            cr.line_to(e, uy - w);
            cr.move_to(s, uy + w);
            cr.line_to(e, uy + w);
        } else {
            cr.move_to(s, uy);
            cr.line_to(e, uy);
        }
    }
    cr.stroke().ok();
    cr.set_dash(&[], 0.0);
}

/// Highlight and run shading behind the text.
fn draw_backgrounds(cr: &cairo::Context, p: &ParaLayout, line: &Line, x0: f64, y0: f64) {
    let mut i = line.start;
    while i < line.end {
        let u = &p.units[i];
        let st: Option<&TextStyle> = if u.shaped != u32::MAX { Some(&p.shaped[u.shaped as usize].style) } else { None };
        let bg = st.and_then(|s| s.highlight.or(s.shading));
        if let Some(c) = bg {
            let mut j = i + 1;
            while j < line.end {
                let v = &p.units[j];
                let s2 = if v.shaped != u32::MAX { Some(&p.shaped[v.shaped as usize].style) } else { None };
                if s2.and_then(|s| s.highlight.or(s.shading)) != Some(c) {
                    break;
                }
                j += 1;
            }
            let xa = x0 + line.xs[i - line.start];
            let xb = x0 + line.xs[j - 1 - line.start] + line.ws[j - 1 - line.start];
            rgb(cr, c);
            cr.rectangle(xa, y0, xb - xa, line.height);
            cr.fill().ok();
            i = j;
        } else {
            i += 1;
        }
    }
}

fn placeholder(cr: &cairo::Context, x: f64, y: f64, w: f64, h: f64, _kind: &str) {
    cr.set_source_rgb(0.85, 0.87, 0.9);
    cr.rectangle(x, y, w, h);
    cr.fill().ok();
    cr.set_source_rgb(0.6, 0.62, 0.66);
    cr.set_line_width(0.75);
    cr.rectangle(x + 0.375, y + 0.375, (w - 0.75).max(0.0), (h - 0.75).max(0.0));
    cr.stroke().ok();
}

impl Renderer {
    fn draw_page_fill(&mut self, cr: &cairo::Context, f: &crate::document::PageFill, w: f64, h: f64) {
        let rgb = |c: u32| (((c >> 16) & 255) as f64 / 255.0, ((c >> 8) & 255) as f64 / 255.0, (c & 255) as f64 / 255.0);
        let (r1, g1, b1) = rgb(f.c1);
        let (r2, g2, b2) = rgb(f.c2);
        cr.save().ok();
        match f.kind.as_str() {
            "gradient" => {
                // VML angles: 0 top to bottom... as Word writes them for the six styles
                let a = f.angle.to_radians();
                let (dx, dy) = (a.sin() * w / 2.0, a.cos() * h / 2.0);
                let g = cairo::LinearGradient::new(w / 2.0 - dx, h / 2.0 - dy, w / 2.0 + dx, h / 2.0 + dy);
                g.add_color_stop_rgb(0.0, r1, g1, b1);
                g.add_color_stop_rgb(1.0, r2, g2, b2);
                cr.set_source(&g).ok();
                cr.paint().ok();
            }
            "gradientRadial" => {
                let (cx, cy) = if f.focus.contains(".5") { (w / 2.0, h / 2.0) } else { (0.0, 0.0) };
                let g = cairo::RadialGradient::new(cx, cy, 0.0, cx, cy, w.max(h));
                g.add_color_stop_rgb(0.0, r1, g1, b1);
                g.add_color_stop_rgb(1.0, r2, g2, b2);
                cr.set_source(&g).ok();
                cr.paint().ok();
            }
            "pattern" => {
                cr.set_source_rgb(r2, g2, b2);
                cr.paint().ok();
                cr.set_source_rgb(r1, g1, b1);
                cr.set_line_width(0.75);
                let t = f.pattern.to_lowercase();
                let step = if t.contains("wide") { 3.0 } else if t.contains("large") { 12.0 } else { 6.0 };
                let mut x = -h;
                while x < w + h {
                    if t.contains("vertical") || t.contains("grid") {
                        cr.move_to(x, 0.0);
                        cr.line_to(x, h);
                    }
                    if t.contains("horizontal") || t.contains("grid") {
                        cr.move_to(0.0, x);
                        cr.line_to(w, x);
                    }
                    if t.contains("upward") || t.contains("cross") {
                        cr.move_to(x, h);
                        cr.line_to(x + h, 0.0);
                    }
                    if t.contains("downward") || t.contains("cross") {
                        cr.move_to(x, 0.0);
                        cr.line_to(x + h, h);
                    }
                    if t.contains('%') {
                        let mut y = 0.0;
                        while y < h {
                            if x >= 0.0 && x <= w {
                                cr.rectangle(x, y, 0.75, 0.75);
                            }
                            y += step;
                        }
                    }
                    x += step;
                }
                cr.stroke().ok();
                cr.fill().ok();
            }
            "frame" | "tile" => {
                if let Some(img) = &f.image {
                    if let Some(s) = self.surface(img) {
                        let (iw, ih) = (s.width() as f64, s.height() as f64);
                        if f.kind == "frame" {
                            cr.scale(w / iw.max(1.0), h / ih.max(1.0));
                            cr.set_source_surface(&s, 0.0, 0.0).ok();
                            cr.paint().ok();
                        } else {
                            let p = cairo::SurfacePattern::create(&s);
                            p.set_extend(cairo::Extend::Repeat);
                            cr.set_source(&p).ok();
                            cr.rectangle(0.0, 0.0, w, h);
                            cr.fill().ok();
                        }
                    }
                }
            }
            _ => {}
        }
        cr.restore().ok();
    }

    fn surface(&mut self, img: &crate::pictures::ImageData) -> Option<cairo::ImageSurface> {
        if !self.pics.contains_key(&img.part) {
            let s = crate::pictures::decode(&img.bytes, self.max_px);
            self.pics.insert(img.part.clone(), s);
        }
        self.pics.get(&img.part).cloned().flatten()
    }

    fn draw_float(&mut self, cr: &cairo::Context, layout: &Layout, fb: &crate::paginate::FloatBox,
                  fonts: &mut FontCache) {
        let pic = &fb.float.pic;
        self.draw_pic(cr, pic, fb.x - pic.effect[0], fb.y - pic.effect[1]);
        cr.save().ok();
        if pic.rot != 0.0 && !fb.lines.is_empty() {
            // a text box's text turns with it
            cr.translate(fb.x + pic.w / 2.0, fb.y + pic.h / 2.0);
            cr.rotate(pic.rot.to_radians());
            cr.translate(-(fb.x + pic.w / 2.0), -(fb.y + pic.h / 2.0));
        }
        if let Some(w) = pic.warp.as_deref() {
            if self.draw_warped(cr, layout, fb, fonts, w) {
                cr.restore().ok();
                return;
            }
        }
        for pl in &fb.lines {
            let p = &layout.paras[pl.para];
            let line = &p.lines[pl.line];
            draw_backgrounds(cr, p, line, pl.x, pl.y);
        }
        for pl in &fb.lines {
            let p = &layout.paras[pl.para];
            let line = &p.lines[pl.line];
            self.draw_line(cr, p, line, pl.x, pl.y, fonts);
        }
        cr.restore().ok();
    }

    /// WordArt Transform: the text box's text drawn off the page, then bent to
    /// the warp in thin strips across the shape.
    fn draw_warped(&mut self, cr: &cairo::Context, layout: &Layout, fb: &crate::paginate::FloatBox,
                   fonts: &mut FontCache, warp: &str) -> bool {
        let pic = &fb.float.pic;
        if fb.lines.is_empty() {
            return false;
        }
        // the text's extent
        let (mut x0, mut y0, mut x1, mut y1) = (f64::MAX, f64::MAX, f64::MIN, f64::MIN);
        for pl in &fb.lines {
            let p = &layout.paras[pl.para];
            let line = &p.lines[pl.line];
            if line.end <= line.start {
                continue;
            }
            let n = line.end - line.start;
            let a = pl.x + line.xs[0];
            let b = pl.x + line.xs[n - 1] + line.ws.get(n - 1).copied().unwrap_or(0.0);
            x0 = x0.min(a);
            x1 = x1.max(b);
            y0 = y0.min(pl.y + line.skip);
            y1 = y1.max(pl.y + line.skip + line.height);
        }
        if !(x1 > x0 && y1 > y0) {
            return false;
        }
        let dev = cr.matrix().xx().abs().max(0.25);
        let s = (dev * 3.0).min(12.0);
        let (bw, bh) = (x1 - x0, y1 - y0);
        let (iw, ih) = ((bw * s).ceil() as i32 + 2, (bh * s).ceil() as i32 + 2);
        if iw <= 2 || ih <= 2 || iw > 8000 || ih > 8000 {
            return false;
        }
        let Ok(surf) = cairo::ImageSurface::create(cairo::Format::ARgb32, iw, ih) else { return false };
        {
            let Ok(c2) = cairo::Context::new(&surf) else { return false };
            c2.scale(s, s);
            c2.translate(-x0, -y0);
            for pl in &fb.lines {
                let p = &layout.paras[pl.para];
                let line = &p.lines[pl.line];
                self.draw_line(&c2, p, line, pl.x, pl.y, fonts);
            }
        }
        // the shape's box (insets kept)
        let ins = pic.text.map(|t| t.1).unwrap_or([7.2, 3.6, 7.2, 3.6]);
        let (bx, by) = (fb.x + ins[0], fb.y + ins[1]);
        let (w, h) = ((pic.w - ins[0] - ins[2]).max(1.0), (pic.h - ins[1] - ins[3]).max(1.0));
        let map = |u: f64, v: f64| -> (f64, f64) { let (px, py) = warp_point(warp, u, v, w, h); (bx + px, by + py) };
        let n = ((bw * dev) / 2.0).clamp(24.0, 400.0) as usize;
        for i in 0..n {
            let (u0, u1) = (i as f64 / n as f64, (i + 1) as f64 / n as f64);
            let p00 = map(u0, 0.0);
            let p10 = map(u1, 0.0);
            let p01 = map(u0, 1.0);
            let p11 = map(u1, 1.0);
            // source strip: pixels sx0..sx1, 0..ih
            let sx0 = u0 * bw * s;
            let sw = (u1 - u0) * bw * s;
            let sh = bh * s;
            // affine: source (sx, sy) -> p00 + (sx - sx0)/sw * (p10 - p00) + sy/sh * (p01 - p00)
            let ax = ((p10.0 - p00.0) / sw, (p10.1 - p00.1) / sw);
            let ay = ((p01.0 - p00.0) / sh, (p01.1 - p00.1) / sh);
            let m = cairo::Matrix::new(ax.0, ax.1, ay.0, ay.1, p00.0 - ax.0 * sx0, p00.1 - ax.1 * sx0);
            cr.save().ok();
            // the strip's quad, a hair wider so strips meet
            let e = 0.35 / dev;
            cr.move_to(p00.0 - e, p00.1);
            cr.line_to(p10.0 + e, p10.1);
            cr.line_to(p11.0 + e, p11.1);
            cr.line_to(p01.0 - e, p01.1);
            cr.close_path();
            cr.clip();
            cr.transform(m);
            cr.set_source_surface(&surf, 0.0, 0.0).ok();
            cr.source().set_filter(cairo::Filter::Good);
            cr.paint().ok();
            cr.restore().ok();
        }
        true
    }

    /// Forget decoded pictures (a picture part was replaced).
    pub fn clear_pictures(&mut self) {
        self.pics.clear();
    }

    /// Draw a picture whose room (effects included) starts at x, y.
    pub fn draw_pic(&mut self, cr: &cairo::Context, pic: &crate::pictures::Pic, x: f64, y: f64) {
        let (px, py) = (x + pic.effect[0], y + pic.effect[1]);
        let (w, h) = (pic.w, pic.h);
        if w <= 0.0 || h <= 0.0 {
            return;
        }
        if pic.kind == "frame" || pic.hidden {
            return;
        }
        if let Some(fx) = pic.fx.as_deref() {
            if !fx.is_empty() {
                self.draw_pic_fx(cr, pic, fx, px, py);
                return;
            }
        }
        cr.save().ok();
        // rotation and flips about the picture's centre
        cr.translate(px + w / 2.0, py + h / 2.0);
        if pic.rot != 0.0 {
            cr.rotate(pic.rot.to_radians());
        }
        cr.scale(if pic.flip_h { -1.0 } else { 1.0 }, if pic.flip_v { -1.0 } else { 1.0 });
        cr.translate(-w / 2.0, -h / 2.0);
        self.draw_content(cr, pic);
        cr.restore().ok();
        self.draw_outline(cr, pic, px, py);
    }

    fn draw_outline(&mut self, cr: &cairo::Context, pic: &crate::pictures::Pic, px: f64, py: f64) {
        let (w, h) = (pic.w, pic.h);
        if let Some((lw, c)) = pic.line {
            cr.save().ok();
            cr.translate(px + w / 2.0, py + h / 2.0);
            if pic.rot != 0.0 {
                cr.rotate(pic.rot.to_radians());
            }
            rgb(cr, c);
            cr.set_line_width(lw);
            match &pic.clip {
                Some(shape) => {
                    cr.translate(-w / 2.0, -h / 2.0);
                    cr.new_path();
                    shape.outline(cr, w, h);
                }
                None => cr.rectangle(-w / 2.0, -h / 2.0, w, h),
            }
            cr.stroke().ok();
            cr.restore().ok();
        }
    }

    /// The picture's content in its own box (0, 0, w, h).
    fn draw_content(&mut self, cr: &cairo::Context, pic: &crate::pictures::Pic) {
        let (w, h) = (pic.w, pic.h);
        if pic.kind == "chart" || pic.kind == "chartex" {
            if let (Some(img), Some(theme)) = (&pic.image, &pic.chart_theme) {
                cr.save().ok();
                let ok = if pic.kind == "chartex" { crate::chart::draw_ex(cr, &img.bytes, w, h, theme, "Calibri") }
                         else { crate::chart::draw(cr, &img.bytes, w, h, theme, "Calibri") };
                cr.restore().ok();
                if ok {
                    return;
                }
            }
        }
        if let Some((text, family, bold, italic)) = &pic.textpath {
            // text stretched to fill the shape (watermarks, WordArt)
            if text.trim().is_empty() || w <= 0.0 || h <= 0.0 {
                return;
            }
            cr.save().ok();
            cr.select_font_face(family, if *italic { cairo::FontSlant::Italic } else { cairo::FontSlant::Normal },
                                if *bold { cairo::FontWeight::Bold } else { cairo::FontWeight::Normal });
            cr.set_font_size(100.0);
            if let Ok(e) = cr.text_extents(text) {
                if e.width() > 0.0 && e.height() > 0.0 {
                    cr.scale(w / e.width(), h / e.height());
                    cr.move_to(-e.x_bearing(), -e.y_bearing());
                    cr.text_path(text);
                    let (c, a) = pic.shape.as_ref().and_then(|s| s.fill).unwrap_or((0xC0C0C0, 0.5));
                    cr.set_source_rgba(((c >> 16) & 255) as f64 / 255.0, ((c >> 8) & 255) as f64 / 255.0,
                                       (c & 255) as f64 / 255.0, a);
                    cr.fill().ok();
                }
            }
            cr.restore().ok();
            return;
        }
        let surf = pic.image.as_ref().and_then(|i| self.surface(i));
        if surf.is_none() && (pic.shape.is_some() || !pic.children.is_empty()) {
            if let Some(sh) = &pic.shape {
                sh.draw(cr, w, h);
            }
            for (cx, cy, c) in &pic.children {
                self.draw_pic(cr, c, *cx, *cy);
            }
            return;
        }
        if surf.is_none() {
            if let Some(img) = pic.image.as_ref().filter(|i| crate::metafile::is_metafile(&i.bytes)) {
                // vector pictures draw straight onto the page
                let [cl, ct, cr_, cb] = pic.crop;
                let fw = w / (1.0 - cl - cr_).max(1e-3);
                let fh = h / (1.0 - ct - cb).max(1e-3);
                cr.save().ok();
                cr.rectangle(0.0, 0.0, w, h);
                cr.clip();
                cr.translate(-cl * fw, -ct * fh);
                crate::metafile::draw(&img.bytes, cr, fw, fh);
                cr.restore().ok();
                return;
            }
        }
        if surf.is_none() && pic.text.is_some() {
            return;
        }
        match surf {
            Some(s) => {
                let (iw, ih) = (s.width() as f64, s.height() as f64);
                let [cl, ct, cr_, cb] = pic.crop;
                // the part of the image shown (crop may be negative: padding)
                let sw = (iw * (1.0 - cl - cr_)).max(1e-6);
                let sh = (ih * (1.0 - ct - cb)).max(1e-6);
                cr.save().ok();
                match &pic.clip {
                    Some(shape) => {
                        cr.new_path();
                        shape.outline(cr, w, h);
                    }
                    None => cr.rectangle(0.0, 0.0, w, h),
                }
                cr.clip();
                cr.scale(w / sw, h / sh);
                cr.set_source_surface(&s, -iw * cl, -ih * ct).ok();
                let pat = cr.source();
                pat.set_filter(cairo::Filter::Good);
                // a negative crop (Fit) leaves empty room, not stretched edges
                pat.set_extend(if pic.crop.iter().any(|c| *c < -1e-6) { cairo::Extend::None } else { cairo::Extend::Pad });
                cr.paint().ok();
                cr.restore().ok();
            }
            None => placeholder(cr, 0.0, 0.0, w, h, pic.kind),
        }
    }

    /// A picture with effects: drawn off the page first, then its shadow,
    /// glow, reflection and the rest around and over it.
    fn draw_pic_fx(&mut self, cr: &cairo::Context, pic: &crate::pictures::Pic, fx: &crate::effects::Fx,
                   px: f64, py: f64) {
        use crate::effects as E;
        let (w, h) = (pic.w, pic.h);
        let (dx, dy) = cr.user_to_device_distance(1.0, 0.0).unwrap_or((1.0, 0.0));
        let k = (dx * dx + dy * dy).sqrt().clamp(0.5, 6.0);
        let (iw, ih) = ((w * k).ceil().max(1.0) as i32, (h * k).ceil().max(1.0) as i32);
        if iw > 8000 || ih > 8000 {
            return;
        }
        let Ok(mut surf) = cairo::ImageSurface::create(cairo::Format::ARgb32, iw, ih) else { return };
        {
            let Ok(c2) = cairo::Context::new(&surf) else { return };
            c2.scale(k, k);
            c2.translate(w / 2.0, h / 2.0);
            c2.scale(if pic.flip_h { -1.0 } else { 1.0 }, if pic.flip_v { -1.0 } else { 1.0 });
            c2.translate(-w / 2.0, -h / 2.0);
            self.draw_content(&c2, pic);
        }
        if fx.recolors() {
            E::recolor(&mut surf, fx);
        }
        if let Some(r) = fx.soft_edge.filter(|r| *r > 0.0) {
            // the edges fade out over the radius
            if let Ok(mut m) = cairo::ImageSurface::create(cairo::Format::A8, iw, ih) {
                {
                    if let Ok(c) = cairo::Context::new(&m) {
                        let inset = r * k * 0.5;
                        c.rectangle(inset, inset, (iw as f64 - 2.0 * inset).max(0.0), (ih as f64 - 2.0 * inset).max(0.0));
                        c.set_source_rgba(0.0, 0.0, 0.0, 1.0);
                        c.fill().ok();
                    }
                }
                E::blur_a8(&mut m, r * k);
                E::multiply_alpha(&mut surf, &mut m);
            }
        }
        cr.save().ok();
        cr.translate(px + w / 2.0, py + h / 2.0);
        if pic.rot != 0.0 {
            cr.rotate(pic.rot.to_radians());
        }
        if let Some((la, lo, rv)) = fx.camera {
            let (a, b, c, d) = E::camera_matrix(la, lo, rv);
            cr.transform(cairo::Matrix::new(a, b, c, d, 0.0, 0.0));
        }
        cr.translate(-w / 2.0, -h / 2.0);
        let paint_mask = |cr: &cairo::Context, m: &cairo::ImageSurface, pad: i32, color: u32, alpha: f64| {
            cr.save().ok();
            cr.scale(1.0 / k, 1.0 / k);
            cr.set_source_rgba(((color >> 16) & 255) as f64 / 255.0, ((color >> 8) & 255) as f64 / 255.0,
                               (color & 255) as f64 / 255.0, alpha);
            cr.mask_surface(m, -pad as f64, -pad as f64).ok();
            cr.restore().ok();
        };
        // the glow, under everything
        if let Some((r, col, a)) = fx.glow.filter(|g| g.0 > 0.0) {
            let pad = (r * k * 1.6).ceil() as i32 + 2;
            if let Some(mut m) = E::alpha_mask(&mut surf, pad) {
                E::blur_a8(&mut m, r * k * 1.2);
                E::boost_a8(&mut m, 2.2);
                paint_mask(cr, &m, pad, col, a);
            }
        }
        // the outer shadow
        if let Some(sh) = &fx.outer {
            let pad = (sh.blur * k).ceil() as i32 + 2;
            if let Some(mut m) = E::alpha_mask(&mut surf, pad) {
                E::blur_a8(&mut m, sh.blur * k);
                let (ox, oy) = (sh.dist * sh.dir.to_radians().cos(), sh.dist * sh.dir.to_radians().sin());
                let (ax, ay) = match sh.algn.as_str() {
                    "tl" => (0.0, 0.0),
                    "t" => (w / 2.0, 0.0),
                    "tr" => (w, 0.0),
                    "l" => (0.0, h / 2.0),
                    "ctr" => (w / 2.0, h / 2.0),
                    "r" => (w, h / 2.0),
                    "bl" => (0.0, h),
                    "br" => (w, h),
                    _ => (w / 2.0, h),
                };
                cr.save().ok();
                cr.translate(ax + ox, ay + oy);
                cr.scale(sh.sx, sh.sy);
                cr.translate(-ax, -ay);
                paint_mask(cr, &m, pad, sh.color, sh.alpha);
                cr.restore().ok();
            }
        }
        // the reflection, below
        if let Some(rf) = &fx.reflection {
            cr.save().ok();
            cr.translate(0.0, 2.0 * h + rf.dist);
            cr.scale(1.0, -1.0);
            let grad = cairo::LinearGradient::new(0.0, h, 0.0, h - (rf.end_pos * h).max(1.0));
            grad.add_color_stop_rgba(0.0, 0.0, 0.0, 0.0, rf.start_alpha);
            grad.add_color_stop_rgba(1.0, 0.0, 0.0, 0.0, rf.end_alpha);
            // a blurred reflection: drawn from a smaller copy
            let shrink = (rf.blur * k / 3.0).max(1.0);
            if shrink > 1.5 {
                let (sw, sh2) = ((iw as f64 / shrink).ceil() as i32, (ih as f64 / shrink).ceil() as i32);
                if let Ok(small) = cairo::ImageSurface::create(cairo::Format::ARgb32, sw.max(1), sh2.max(1)) {
                    if let Ok(c) = cairo::Context::new(&small) {
                        c.scale(1.0 / shrink, 1.0 / shrink);
                        c.set_source_surface(&surf, 0.0, 0.0).ok();
                        c.paint().ok();
                    }
                    let kk = k / shrink;
                    cr.scale(1.0 / kk, 1.0 / kk);
                    cr.set_source_surface(&small, 0.0, 0.0).ok();
                    cr.source().set_filter(cairo::Filter::Good);
                    cr.mask(&scaled_gradient(&grad, kk)).ok();
                }
            } else {
                cr.scale(1.0 / k, 1.0 / k);
                cr.set_source_surface(&surf, 0.0, 0.0).ok();
                cr.mask(&scaled_gradient(&grad, k)).ok();
            }
            cr.restore().ok();
        }
        // the picture
        cr.save().ok();
        cr.scale(1.0 / k, 1.0 / k);
        cr.set_source_surface(&surf, 0.0, 0.0).ok();
        cr.paint().ok();
        cr.restore().ok();
        // the inner shadow: the outside's blurred edge, inside the picture
        if let Some(sh) = &fx.inner {
            let pad = (sh.blur * k).ceil() as i32 + (sh.dist * k).ceil() as i32 + 2;
            if let (Some(mut m), Ok(mut t)) = (E::alpha_mask(&mut surf, pad), cairo::ImageSurface::create(cairo::Format::ARgb32, iw, ih)) {
                m.flush();
                if let Ok(mut d) = m.data() {
                    for v in d.iter_mut() {
                        *v = 255 - *v;
                    }
                }
                m.mark_dirty();
                E::blur_a8(&mut m, sh.blur * k);
                {
                    if let Ok(c) = cairo::Context::new(&t) {
                        let (ox, oy) = (sh.dist * sh.dir.to_radians().cos() * k, sh.dist * sh.dir.to_radians().sin() * k);
                        c.set_source_rgba(((sh.color >> 16) & 255) as f64 / 255.0, ((sh.color >> 8) & 255) as f64 / 255.0,
                                          (sh.color & 255) as f64 / 255.0, sh.alpha);
                        c.mask_surface(&m, ox - pad as f64, oy - pad as f64).ok();
                    }
                }
                if let Some(mut a) = E::alpha_mask(&mut surf, 0) {
                    E::multiply_alpha(&mut t, &mut a);
                }
                cr.save().ok();
                cr.scale(1.0 / k, 1.0 / k);
                cr.set_source_surface(&t, 0.0, 0.0).ok();
                cr.paint().ok();
                cr.restore().ok();
            }
        }
        // a bevel: light from the top left
        if let Some((bw, _bh, _p)) = &fx.bevel {
            if let Ok(mut t) = cairo::ImageSurface::create(cairo::Format::ARgb32, iw, ih) {
                {
                    if let Ok(c) = cairo::Context::new(&t) {
                        c.scale(k, k);
                        let b = bw.min(w / 2.0).min(h / 2.0);
                        let edge = |c: &cairo::Context, x0: f64, y0: f64, x1: f64, y1: f64, light: bool,
                                    pts: &[(f64, f64)]| {
                            let g = cairo::LinearGradient::new(x0, y0, x1, y1);
                            let v = if light { 1.0 } else { 0.0 };
                            g.add_color_stop_rgba(0.0, v, v, v, if light { 0.55 } else { 0.4 });
                            g.add_color_stop_rgba(1.0, v, v, v, 0.0);
                            c.move_to(pts[0].0, pts[0].1);
                            for p in &pts[1..] {
                                c.line_to(p.0, p.1);
                            }
                            c.close_path();
                            c.set_source(&g).ok();
                            c.fill().ok();
                        };
                        edge(&c, 0.0, 0.0, 0.0, b, true, &[(0.0, 0.0), (w, 0.0), (w - b, b), (b, b)]);
                        edge(&c, 0.0, 0.0, b, 0.0, true, &[(0.0, 0.0), (b, b), (b, h - b), (0.0, h)]);
                        edge(&c, 0.0, h, 0.0, h - b, false, &[(0.0, h), (b, h - b), (w - b, h - b), (w, h)]);
                        edge(&c, w, 0.0, w - b, 0.0, false, &[(w, 0.0), (w, h), (w - b, h - b), (w - b, b)]);
                    }
                }
                if let Some(mut a) = E::alpha_mask(&mut surf, 0) {
                    E::multiply_alpha(&mut t, &mut a);
                }
                cr.save().ok();
                cr.scale(1.0 / k, 1.0 / k);
                cr.set_source_surface(&t, 0.0, 0.0).ok();
                cr.paint().ok();
                cr.restore().ok();
            }
        }
        cr.restore().ok();
        self.draw_outline(cr, pic, px, py);
    }
}

/// A gradient given in points, for drawing at `k` pixels per point.
fn scaled_gradient(g: &cairo::LinearGradient, k: f64) -> cairo::LinearGradient {
    let (x0, y0, x1, y1) = g.linear_points().unwrap_or((0.0, 0.0, 0.0, 1.0));
    let n = cairo::LinearGradient::new(x0 * k, y0 * k, x1 * k, y1 * k);
    let count = g.color_stop_count().unwrap_or(0);
    for i in 0..count {
        if let Ok((o, r, gg, b, a)) = g.color_stop_rgba(i) {
            n.add_color_stop_rgba(o, r, gg, b, a);
        }
    }
    n
}

fn draw_cells(cr: &cairo::Context, cells: &[crate::paginate::CellBox], gridlines: bool) {
    for c in cells {
        if let Some(col) = c.shading {
            rgb(cr, col);
            cr.rectangle(c.x, c.y, c.w, c.h);
            cr.fill().ok();
        }
    }
    for c in cells {
        // diagonal lines across the cell
        for (i, d) in c.diag.iter().enumerate() {
            if let Some(bd) = d {
                let w = crate::props::border_width(d);
                let (x0, y0, x1, y1) = if i == 0 { (c.x, c.y, c.x + c.w, c.y + c.h) } else { (c.x + c.w, c.y, c.x, c.y + c.h) };
                stroke_border(cr, bd, w, x0, y0, x1, y1);
            }
        }
        let edges = [
            (c.x, c.y, c.x + c.w, c.y),
            (c.x, c.y, c.x, c.y + c.h),
            (c.x, c.y + c.h, c.x + c.w, c.y + c.h),
            (c.x + c.w, c.y, c.x + c.w, c.y + c.h),
        ];
        for (i, (x0, y0, x1, y1)) in edges.iter().enumerate() {
            let b = &c.bdr[i];
            let w = crate::props::border_width(b);
            if let (Some(bd), true) = (b, w > 0.0) {
                stroke_border(cr, bd, w, *x0, *y0, *x1, *y1);
            } else if gridlines && (i < 2) {
                cr.set_source_rgb(0.75, 0.82, 0.92);
                cr.set_line_width(0.5);
                cr.set_dash(&[1.0, 1.0], 0.0);
                cr.move_to(*x0, *y0);
                cr.line_to(*x1, *y1);
                cr.stroke().ok();
                cr.set_dash(&[], 0.0);
            }
        }
    }
}

/// Render a page to RGBA (cairo ARGB32, premultiplied, native endian) at
/// `scale` pixels per point.
pub fn render_page_image(r: &mut Renderer, layout: &Layout, page: usize, fonts: &mut FontCache, scale: f64,
                         ov: &Overlay) -> Option<cairo::ImageSurface> {
    let pg = layout.pages.get(page)?;
    let w = (pg.width * scale).ceil() as i32;
    let h = (pg.height * scale).ceil() as i32;
    let surf = cairo::ImageSurface::create(cairo::Format::ARgb32, w, h).ok()?;
    {
        let cr = cairo::Context::new(&surf).ok()?;
        cr.scale(scale, scale);
        r.draw_page(&cr, layout, pg, fonts, ov);
    }
    surf.flush();
    Some(surf)
}

/// Export the whole layout to PDF.
pub fn export_pdf(layout: &Layout, fonts: &mut FontCache, path: &str) -> Result<(), String> {
    export_pdf_with(layout, fonts, path, &PdfOptions::default())
}

/// What a PDF carries besides the pages.
#[derive(Default)]
pub struct PdfOptions {
    /// the pages (0-based) to export; empty: all
    pub pages: Vec<usize>,
    /// bookmarks: (level 1.., text, page, y in points)
    pub outline: Vec<(u32, String, usize, f64)>,
    pub title: String,
    pub author: String,
    pub subject: String,
    pub keywords: String,
}

pub fn export_pdf_with(layout: &Layout, fonts: &mut FontCache, path: &str, o: &PdfOptions) -> Result<(), String> {
    let pages: Vec<usize> = if o.pages.is_empty() { (0..layout.pages.len()).collect() }
                            else { o.pages.iter().copied().filter(|&i| i < layout.pages.len()).collect() };
    let first = layout.pages.get(*pages.first().ok_or("no pages")?).ok_or("no pages")?;
    let surf = cairo::PdfSurface::new(first.width, first.height, path).map_err(|e| e.to_string())?;
    for (k, v) in [(cairo::PdfMetadata::Title, &o.title), (cairo::PdfMetadata::Author, &o.author),
                   (cairo::PdfMetadata::Subject, &o.subject), (cairo::PdfMetadata::Keywords, &o.keywords)] {
        if !v.is_empty() {
            surf.set_metadata(k, v).ok();
        }
    }
    surf.set_metadata(cairo::PdfMetadata::Creator, "Folio Writer").ok();
    // bookmarks: their pages renumbered to the ones exported
    let mut parents: Vec<(u32, i32)> = Vec::new();
    for (level, text, page, y) in &o.outline {
        let Some(pi) = pages.iter().position(|p| p == page) else { continue };
        while parents.last().map_or(false, |(l, _)| *l >= *level) {
            parents.pop();
        }
        let parent = parents.last().map(|(_, id)| *id).unwrap_or(0);
        let link = format!("page={} pos=[0 {}]", pi + 1, y.max(0.0));
        if let Ok(id) = surf.add_outline(parent, text, &link, cairo::PdfOutline::OPEN) {
            parents.push((*level, id));
        }
    }
    let cr = cairo::Context::new(&surf).map_err(|e| e.to_string())?;
    let mut r = Renderer::new();
    r.max_px = 6000;
    for &i in &pages {
        let pg = &layout.pages[i];
        surf.set_size(pg.width, pg.height).ok();
        r.draw_page(&cr, layout, pg, fonts, &Overlay::default());
        cr.show_page().map_err(|e| e.to_string())?;
    }
    surf.finish();
    Ok(())
}

/// The glyph range helper is public for the view's hit testing.
pub fn glyphs_for(sh: &Shaped, a: u32, b: u32) -> (usize, usize) {
    glyph_range(sh, a, b)
}

/// Show/Hide ¶ on one line: dots for spaces, arrows for tabs, the break
/// characters and the paragraph mark (with a section break's label).
fn draw_marks(cr: &cairo::Context, p: &ParaLayout, pl: &crate::paginate::Placed, ov: &Overlay) {
    let Some(line) = p.lines.get(pl.line) else { return };
    let last = pl.line + 1 == p.lines.len();
    let size = if p.mark_style.size > 0.0 { p.mark_style.size } else { 11.0 };
    let base = pl.y + line.baseline;
    cr.save().ok();
    match p.mark_style.color {
        Some(c) if c != 0xFFFFFF => rgb(cr, c),
        _ => cr.set_source_rgb(0.2, 0.2, 0.2),
    }
    cr.select_font_face("DejaVu Sans", cairo::FontSlant::Normal, cairo::FontWeight::Normal);
    let label = |cr: &cairo::Context, x0: f64, x1: f64, y: f64, text: &str, double: bool| {
        cr.set_font_size(size * 0.7);
        let ext = cr.text_extents(text).ok();
        let tw = ext.map(|e| e.width()).unwrap_or(40.0);
        let mid = (x0 + x1) / 2.0;
        cr.set_line_width(0.5);
        cr.set_dash(&[1.0, 1.5], 0.0);
        for dy in if double { &[-1.0, 1.0][..] } else { &[0.0][..] } {
            cr.move_to(x0, y + dy);
            cr.line_to(mid - tw / 2.0 - 3.0, y + dy);
            cr.move_to(mid + tw / 2.0 + 3.0, y + dy);
            cr.line_to(x1, y + dy);
        }
        cr.stroke().ok();
        cr.set_dash(&[], 0.0);
        cr.move_to(mid - tw / 2.0, y + size * 0.25);
        cr.show_text(text).ok();
    };
    let right_edge = pl.x + p.width - p.right;
    let mut end_x = None;
    for u in line.start..line.end {
        let unit = &p.units[u];
        if unit.gen {
            continue;
        }
        let k = u - line.start;
        let (x, w) = (pl.x + line.xs[k], line.ws[k]);
        let us = if unit.asc + unit.desc > 0.0 { (unit.asc + unit.desc) / 1.15 } else { size };
        match unit.kind {
            UnitKind::Char(' ') | UnitKind::Char('\u{3000}') => {
                cr.arc(x + w / 2.0, base - us * 0.28, (us * 0.045).max(0.6), 0.0, std::f64::consts::TAU);
                cr.fill().ok();
            }
            UnitKind::Char('\u{a0}') => {
                cr.set_font_size(us * 0.8);
                cr.move_to(x + w / 2.0 - us * 0.15, base - us * 0.1);
                cr.show_text("\u{b0}").ok();
            }
            UnitKind::Tab => {
                let y = base - us * 0.3;
                let len = (w - 2.0).min(us * 0.8).max(us * 0.4);
                let x0 = x + (w - len) / 2.0;
                cr.set_line_width(0.6);
                cr.move_to(x0, y);
                cr.line_to(x0 + len, y);
                cr.move_to(x0 + len - us * 0.2, y - us * 0.15);
                cr.line_to(x0 + len, y);
                cr.line_to(x0 + len - us * 0.2, y + us * 0.15);
                cr.stroke().ok();
            }
            UnitKind::LineBreak => {
                cr.set_font_size(us * 0.9);
                cr.move_to(x + 1.0, base);
                cr.show_text("\u{21b5}").ok();
                end_x = Some(x);
            }
            UnitKind::PageBreak | UnitKind::ColumnBreak => {
                let text = if unit.kind == UnitKind::PageBreak { "Page Break" } else { "Column Break" };
                label(cr, x + 2.0, right_edge, base - us * 0.3, text, false);
                end_x = Some(right_edge);
            }
            _ => {}
        }
        if !matches!(unit.kind, UnitKind::LineBreak | UnitKind::PageBreak | UnitKind::ColumnBreak) {
            end_x = Some(x + w);
        }
    }
    if last {
        let x = match end_x {
            Some(x) if line.end > line.start => x,
            _ => {
                let left = p.left + if pl.line == 0 { p.first } else { 0.0 };
                pl.x + match p.props.jc.as_deref() {
                    Some("center") => (left + p.width - p.right) / 2.0,
                    Some("right") | Some("end") => p.width - p.right,
                    _ => left,
                }
            }
        };
        let broke = line.end > line.start && matches!(p.units[line.end - 1].kind, UnitKind::PageBreak | UnitKind::ColumnBreak);
        if let Some(text) = ov.sect_breaks.get(&p.node) {
            label(cr, x + 2.0, right_edge.max(x + 80.0), base - size * 0.3, text, true);
        } else if !broke || line.end > line.start {
            cr.set_font_size(size);
            cr.move_to(if broke { right_edge + 2.0 } else { x + 0.5 }, base);
            cr.show_text("\u{b6}").ok();
        }
    }
    cr.restore().ok();
}

/// Turned text (a cell's text direction): the context turned about the
/// frame's corner (saved: the caller restores when this returns true).
pub fn enter_frame(cr: &cairo::Context, pl: &crate::paginate::Placed) -> bool {
    let Some((tx, ty, kind)) = pl.frame else { return false };
    cr.save().ok();
    cr.translate(tx, ty);
    cr.rotate(if kind == 1 { std::f64::consts::FRAC_PI_2 } else { -std::f64::consts::FRAC_PI_2 });
    true
}

/// A point of a turned frame on the page.
pub fn frame_to_page(frame: (f64, f64, u8), x: f64, y: f64) -> (f64, f64) {
    let (tx, ty, kind) = frame;
    if kind == 1 { (tx - y, ty + x) } else { (tx + y, ty - x) }
}

/// A page point in a turned frame.
pub fn page_to_frame(frame: (f64, f64, u8), px: f64, py: f64) -> (f64, f64) {
    let (tx, ty, kind) = frame;
    if kind == 1 { (py - ty, tx - px) } else { (ty - py, px - tx) }
}

/// The body text's font (line numbers use it).
fn layout_default_font(layout: &Layout) -> String {
    layout.paras.first().and_then(|p| p.shaped.first()).map(|sh| sh.font.family.clone()).unwrap_or_else(|| "Calibri".into())
}

/// Where the point (u, v) of the text (0..1 across, 0..1 down) goes in a w x h
/// shape for a WordArt warp.
pub fn warp_point(warp: &str, u: f64, v: f64, w: f64, h: f64) -> (f64, f64) {
    use std::f64::consts::PI;
    let band = |top: f64, bottom: f64| (u * w, top + v * (bottom - top));
    let t = 2.0 * u - 1.0;
    match warp {
        "textArchUp" | "textArchUpPour" => {
            let th = PI * (1.0 - u);
            let k = 1.0 - 0.38 * v;
            (w / 2.0 + w / 2.0 * k * th.cos(), h - h * k * th.sin())
        }
        "textArchDown" | "textArchDownPour" => {
            let th = PI * (1.0 - u);
            let k = 0.62 + 0.38 * v;
            (w / 2.0 + w / 2.0 * k * th.cos(), h * k * th.sin())
        }
        "textCircle" | "textCirclePour" | "textButton" => {
            let th = PI - 2.0 * PI * u + PI / 2.0;
            let k = 1.0 - 0.3 * v;
            (w / 2.0 + w / 2.0 * k * th.cos(), h / 2.0 - h / 2.0 * k * th.sin())
        }
        "textTriangle" => band(0.85 * h * t.abs(), h),
        "textTriangleInverted" => band(0.0, h - 0.85 * h * t.abs()),
        "textChevron" => band(0.35 * h * t.abs(), h - 0.35 * h * (1.0 - t.abs())),
        "textChevronInverted" => band(0.35 * h * (1.0 - t.abs()), h - 0.35 * h * t.abs()),
        "textWave1" | "textWave2" | "textWave4" | "textDoubleWave1" => {
            let a = 0.12 * h;
            let d = a * (2.0 * PI * u).sin();
            band(a + d, h - a + d)
        }
        "textInflate" => band(0.3 * h * t * t, h - 0.3 * h * t * t),
        "textDeflate" => band(0.3 * h * (1.0 - t * t), h - 0.3 * h * (1.0 - t * t)),
        "textInflateTop" => band(0.3 * h * t * t, h),
        "textDeflateTop" => band(0.3 * h * (1.0 - t * t), h),
        "textInflateBottom" => band(0.0, h - 0.3 * h * t * t),
        "textDeflateBottom" => band(0.0, h - 0.3 * h * (1.0 - t * t)),
        "textSlantUp" => band(0.4 * h * (1.0 - u), 0.4 * h * (1.0 - u) + 0.6 * h),
        "textSlantDown" => band(0.4 * h * u, 0.4 * h * u + 0.6 * h),
        "textFadeRight" => band(0.3 * h * u, h - 0.3 * h * u),
        "textFadeLeft" => band(0.3 * h * (1.0 - u), h - 0.3 * h * (1.0 - u)),
        "textFadeUp" => (w * (0.5 + (u - 0.5) * (0.6 + 0.4 * v)), v * h),
        "textFadeDown" => (w * (0.5 + (u - 0.5) * (1.0 - 0.4 * v)), v * h),
        "textCanUp" => band(0.25 * h * (1.0 - t * t), h - 0.25 * h * (1.0 - t * t) * 0.0),
        "textCanDown" => band(0.25 * h * t * t, h - 0.25 * h * t * t * 0.0),
        _ => band(0.0, h),
    }
}
