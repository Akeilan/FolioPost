//! Drawing a chart with cairo: title, legend, axes, gridlines and the series.

use super::model::{self, auto_color, Chart, Group, Kind, Plot};
use std::f64::consts::PI;

type Ctx = cairo::Context;

#[derive(Clone)]
pub struct FontSpec {
    pub family: String,
    pub size: f64,
    pub bold: bool,
    pub color: u32,
}

#[derive(Clone, Copy, PartialEq)]
enum Align {
    Left,
    Center,
}

/// Text for the chart: measured, then shown with its top-left at a point
/// (lines broken to a width when one is given).
pub struct Pen {
    measure: Ctx,
    lines: Vec<String>,
    font: Option<FontSpec>,
    width: Option<f64>,
    align: Align,
    line_h: f64,
}

impl Pen {
    pub fn new() -> Pen {
        let surf = cairo::ImageSurface::create(cairo::Format::ARgb32, 4, 4).expect("surface");
        Pen { measure: Ctx::new(&surf).expect("context"), lines: Vec::new(), font: None, width: None, align: Align::Left, line_h: 0.0 }
    }

    fn apply(cr: &Ctx, f: &FontSpec, z: f64) {
        cr.select_font_face(&f.family, cairo::FontSlant::Normal,
                            if f.bold { cairo::FontWeight::Bold } else { cairo::FontWeight::Normal });
        cr.set_font_size(f.size * z);
    }

    fn adv(&self, t: &str) -> f64 {
        self.measure.text_extents(t).map(|e| e.x_advance()).unwrap_or(0.0)
    }

    fn set_align(&mut self, a: Align) {
        self.align = a;
    }

    /// Measure text: (width, height).
    pub fn set(&mut self, text: &str, f: &FontSpec, z: f64, width: Option<f64>) -> (f64, f64) {
        Pen::apply(&self.measure, f, z);
        let fe = self.measure.font_extents().ok();
        self.line_h = fe.map(|e| e.height()).unwrap_or(f.size * z * 1.2);
        let mut lines = Vec::new();
        for para in text.split('\n') {
            match width {
                Some(w) if w > 0.0 && self.adv(para) > w => {
                    let mut cur = String::new();
                    for word in para.split(' ') {
                        let trial = if cur.is_empty() { word.to_string() } else { format!("{cur} {word}") };
                        if self.adv(&trial) > w && !cur.is_empty() {
                            lines.push(std::mem::take(&mut cur));
                            cur = word.to_string();
                        } else {
                            cur = trial;
                        }
                    }
                    lines.push(cur);
                }
                _ => lines.push(para.to_string()),
            }
        }
        let tw = lines.iter().map(|l| self.adv(l)).fold(0.0, f64::max);
        let th = self.line_h * lines.len().max(1) as f64;
        self.lines = lines;
        self.font = Some(f.clone());
        self.width = width;
        (tw, th)
    }

    /// Show the text last measured, its top-left at (x, y).
    pub fn show(&mut self, cr: &Ctx, x: f64, y: f64) {
        let Some(f) = self.font.clone() else { return };
        cr.save().ok();
        let z = 1.0;
        Pen::apply(cr, &f, z);
        cr.set_font_size(self.measure.font_matrix().xx());
        let asc = cr.font_extents().map(|e| e.ascent()).unwrap_or(f.size * 0.8);
        for (i, l) in self.lines.iter().enumerate() {
            let w = cr.text_extents(l).map(|e| e.x_advance()).unwrap_or(0.0);
            let dx = match (self.align, self.width) {
                (Align::Center, Some(bw)) => (bw - w) / 2.0,
                _ => 0.0,
            };
            cr.move_to(x + dx, y + asc + i as f64 * self.line_h);
            cr.show_text(l).ok();
        }
        cr.restore().ok();
    }
}

const PANGO_ALIGN_CENTER: Align = Align::Center;
const PANGO_ALIGN_LEFT: Align = Align::Left;

/// Draws charts: the theme's colours and its body font.
pub struct Painter {
    pub theme: [u32; 12],
    pub font: String,
    pub text: std::cell::Cell<u32>,
}

const TEXT: u32 = 0x595959;
const LINE: u32 = 0xD9D9D9;

fn rgb(cr: &Ctx, c: u32) {
    cr.set_source_rgb( ((c >> 16) & 255) as f64 / 255.0, ((c >> 8) & 255) as f64 / 255.0, (c & 255) as f64 / 255.0);
}

fn luma(c: u32) -> f64 {
    0.299 * ((c >> 16) & 255) as f64 + 0.587 * ((c >> 8) & 255) as f64 + 0.114 * (c & 255) as f64
}

/// The axis Excel would pick for data from min to max: (low, high, major step).
pub fn nice_axis(mut min: f64, mut max: f64, ticks: f64, from_zero: bool) -> (f64, f64, f64) {
    if !min.is_finite() || !max.is_finite() {
        return (0.0, 1.0, 0.2);
    }
    if min > max {
        std::mem::swap(&mut min, &mut max);
    }
    if from_zero {
        // a range far from zero doesn't start at zero
        if min > 0.0 && (max - min) / max >= 1.0 / 6.0 {
            min = 0.0;
        } else if max < 0.0 && (max - min) / -min >= 1.0 / 6.0 {
            max = 0.0;
        } else if min <= 0.0 && max >= 0.0 {
        }
    }
    if min == max {
        if min == 0.0 {
            return (0.0, 1.0, 0.2);
        }
        let d = min.abs() / 2.0;
        if min > 0.0 { min = 0.0 } else { max = 0.0 }
        let _ = d;
    }
    let span = max - min;
    // headroom over the largest value
    let hi_raw = if max > 0.0 { max + span * 0.05 } else { max };
    let lo_raw = if min < 0.0 { min - span * 0.05 } else { min };
    let raw = (hi_raw - lo_raw) / ticks.max(2.0);
    let mag = 10f64.powf(raw.log10().floor());
    let norm = raw / mag;
    let step = mag * if norm <= 1.0 { 1.0 } else if norm <= 2.0 { 2.0 } else if norm <= 2.5 { 2.5 } else if norm <= 5.0 { 5.0 } else { 10.0 };
    let lo = (lo_raw / step).floor() * step;
    let mut hi = (hi_raw / step).ceil() * step;
    if hi <= lo {
        hi = lo + step;
    }
    (clean(lo), clean(hi), step)
}

fn clean(x: f64) -> f64 {
    let r = (x * 1e9).round() / 1e9;
    if r == 0.0 { 0.0 } else { r }
}

struct Entry {
    text: String,
    color: u32,
    line: bool,
    marker: bool,
}

struct SerData {
    vals: Vec<Option<f64>>,
    xs: Vec<Option<f64>>,
    color: u32,
    labels: bool,
    smooth: bool,
    texts: Vec<String>,
    point_colors: Vec<(usize, u32)>,
    hidden: bool,
    label_pos: Option<String>,
}

impl Painter {
    fn chart_font(&self, size: f64, bold: bool) -> FontSpec {
        FontSpec { family: self.font.clone(), size, bold, color: TEXT }
    }

    /// Paint a chart into the rectangle (x, y, w, h) on screen, at zoom z.
    pub fn paint_chart(&self, ch: &Chart, cr: &Ctx, x: f64, y: f64, w: f64, h: f64, z: f64, pen: &mut Pen) {
        if w < 4.0 || h < 4.0 {
            return;
        }
        let theme = &self.theme;
        cr.save().ok();
        cr.rectangle(x, y, w, h);
        cr.clip();
        self.text.set(ch.text);
        rgb(cr, ch.bg.unwrap_or(0xFFFFFF));
        cr.rectangle(x, y, w, h);
        cr.fill().ok();
        rgb(cr, LINE);
        cr.set_line_width(1.0);
        cr.rectangle(x + 0.5, y + 0.5, w - 1.0, h - 1.0);
        cr.stroke().ok();
        let pad = (8.0 * z).max(2.0);
        let (mut l, mut t, mut r, mut b) = (x + pad, y + pad, x + w - pad, y + h - pad);
        pen.set_align(PANGO_ALIGN_CENTER);
        // ---- title
        if let Some(title) = model::title_text(ch) {
            if !title.is_empty() {
                let f = self.chart_font(14.0, false);
                let (_, th) = pen.set(&title, &f, z, Some(r - l));
                rgb(cr, self.text.get());
                pen.show(cr, l, t);
                t += th + 4.0 * z;
            }
        }
        pen.set_align(PANGO_ALIGN_LEFT);
        // ---- data
        let pie = ch.plots.iter().all(|p| matches!(p.kind, Kind::Pie | Kind::Doughnut));
        let mut idx = 0usize;
        let mut data: Vec<Vec<SerData>> = Vec::new();
        let mut entries: Vec<Entry> = Vec::new();
        let mut cats: Vec<String> = Vec::new();
        for p in &ch.plots {
            let mut list = Vec::new();
            for se in &p.series {
                let pts = se.val.as_ref().map(|v| model::values(v)).unwrap_or_default();
                let xpts = se.cat.as_ref().map(|v| model::values(v)).unwrap_or_default();
                if cats.is_empty() && !xpts.is_empty() && p.kind != Kind::Scatter {
                    cats = xpts.iter().map(|p| p.text.clone()).collect();
                }
                let color = se.color.unwrap_or_else(|| auto_color(theme, ch.palette, idx));
                if !pie && !ch.legend_deleted.contains(&idx) && !se.hidden {
                    entries.push(Entry { text: model::series_name(se, idx), color, line: matches!(p.kind, Kind::Line) || p.kind == Kind::Scatter && p.lines, marker: p.markers });
                }
                list.push(SerData {
                    vals: pts.iter().map(|p| p.v).collect(),
                    texts: pts.iter().map(|p| p.text.clone()).collect(),
                    xs: xpts.iter().map(|p| p.v).collect(),
                    color,
                    labels: se.labels,
                    smooth: se.smooth,
                    point_colors: se.point_colors.clone(),
                    hidden: se.hidden,
                    label_pos: se.label_pos.clone(),
                });
                idx += 1;
            }
            data.push(list);
        }
        if pie {
            if let Some(s0) = data.first().and_then(|d| d.first()) {
                for i in 0..s0.vals.len() {
                    let text = cats.get(i).cloned().filter(|t| !t.is_empty()).unwrap_or_else(|| format!("{}", i + 1));
                    let color = s0.point_colors.iter().find(|(k, _)| *k == i).map(|x| x.1).unwrap_or_else(|| auto_color(theme, ch.palette, i));
                    entries.push(Entry { text, color, line: false, marker: false });
                }
            }
        }
        // ---- legend
        if let Some(pos) = &ch.legend {
            let f = self.chart_font(9.0, false);
            let key = 7.0 * z;
            let gap = 4.0 * z;
            let sizes: Vec<(f64, f64)> = entries.iter().map(|e| {
                let (tw, th) = pen.set(&e.text, &f, z, None);
                ((if e.line { key * 2.5 } else { key }) + gap + tw, th)
            }).collect();
            let lh = sizes.iter().map(|s| s.1).fold(12.0 * z, f64::max);
            let place: Vec<(f64, f64)>;
            match pos.as_str() {
                "r" | "l" | "tr" => {
                    let lw = sizes.iter().map(|s| s.0).fold(0.0, f64::max).min((r - l) * 0.4);
                    let total = lh * entries.len() as f64;
                    let x0 = if pos == "l" { l } else { r - lw };
                    let y0 = if pos == "tr" { t } else { t + ((b - t) - total).max(0.0) / 2.0 };
                    place = (0..entries.len()).map(|i| (x0, y0 + i as f64 * lh)).collect();
                    if pos == "l" { l += lw + 8.0 * z } else { r -= lw + 8.0 * z }
                }
                _ => {
                    // rows of entries, centred
                    let avail = r - l;
                    let mut rows: Vec<Vec<usize>> = vec![vec![]];
                    let mut cur = 0.0;
                    for (i, s) in sizes.iter().enumerate() {
                        let need = s.0 + 12.0 * z;
                        if cur + need > avail && !rows.last().unwrap().is_empty() {
                            rows.push(vec![]);
                            cur = 0.0;
                        }
                        rows.last_mut().unwrap().push(i);
                        cur += need;
                    }
                    let rows: Vec<Vec<usize>> = rows.into_iter().take(((b - t) / 3.0 / lh).max(1.0) as usize).collect();
                    let total_h = rows.len() as f64 * lh;
                    let y0 = if pos == "t" { t } else { b - total_h };
                    let mut pl = vec![(-1e9, -1e9); entries.len()];
                    for (k, row) in rows.iter().enumerate() {
                        let rw: f64 = row.iter().map(|i| sizes[*i].0 + 12.0 * z).sum::<f64>() - 12.0 * z;
                        let mut xx = l + (avail - rw).max(0.0) / 2.0;
                        for i in row {
                            pl[*i] = (xx, y0 + k as f64 * lh);
                            xx += sizes[*i].0 + 12.0 * z;
                        }
                    }
                    place = pl;
                    if pos == "t" { t += total_h + 6.0 * z } else { b -= total_h + 6.0 * z }
                }
            }
            for (i, e) in entries.iter().enumerate() {
                let (ex, ey) = place[i];
                if ex < -1e8 {
                    continue;
                }
                let cy = ey + lh / 2.0;
                rgb(cr, e.color);
                let kw = if e.line {
                    cr.set_line_width(2.25 * z);
                    cr.move_to(ex, cy);
                    cr.line_to(ex + key * 2.5, cy);
                    cr.stroke().ok();
                    if e.marker {
                        cr.arc(ex + key * 1.25, cy, 2.5 * z, 0.0, 2.0 * PI);
                        cr.fill().ok();
                    }
                    key * 2.5
                } else {
                    cr.rectangle(ex, cy - key / 2.0, key, key);
                    cr.fill().ok();
                    key
                };
                pen.set(&e.text, &f, z, None);
                rgb(cr, self.text.get());
                pen.show(cr, ex + kw + gap, ey);
            }
        }
        if r - l < 10.0 || b - t < 10.0 {
            cr.restore().ok();
            return;
        }
        let radar = ch.plots.iter().all(|p| p.file_tag.as_deref() == Some("radarChart"));
        if pie {
            self.paint_pie(ch, &data, cr, l, t, r, b, z, pen);
        } else if radar {
            self.paint_radar(ch, &data, &cats, cr, l, t, r, b, z, pen);
        } else {
            self.paint_axes_chart(ch, &data, &cats, cr, l, t, r, b, z, pen);
        }
        cr.restore().ok();
    }

    /// A radar chart: a spoke per category, rings at the value ticks, a
    /// closed line per series.
    #[allow(clippy::too_many_arguments)]
    fn paint_radar(&self, ch: &Chart, data: &[Vec<SerData>], cats: &[String], cr: &Ctx, l: f64, t: f64, r: f64, b: f64,
                   z: f64, pen: &mut Pen) {
        let f = self.chart_font(9.0, false);
        let ncat = data.iter().flatten().map(|s| s.vals.len()).max().unwrap_or(0).max(cats.len());
        if ncat < 3 {
            return;
        }
        let (_, th) = pen.set("0", &f, z, None);
        let cx = (l + r) / 2.0;
        let cy = (t + b) / 2.0;
        let rad = ((r - l) / 2.0 - 40.0 * z).min((b - t) / 2.0 - th * 1.5).max(10.0);
        let mut lo = 0.0f64;
        let mut hi = f64::NEG_INFINITY;
        for s in data.iter().flatten() {
            for v in s.vals.iter().flatten() {
                lo = lo.min(*v);
                hi = hi.max(*v);
            }
        }
        if !hi.is_finite() {
            return;
        }
        let (a0, a1, st) = nice_axis(lo, hi, 5.0, true);
        let ang = |i: usize| -PI / 2.0 + i as f64 * 2.0 * PI / ncat as f64;
        let at = |i: usize, v: f64| {
            let k = ((v - a0) / (a1 - a0)).clamp(0.0, 1.0) * rad;
            (cx + k * ang(i).cos(), cy + k * ang(i).sin())
        };
        cr.set_line_width(z.max(1.0));
        rgb(cr, LINE);
        let n = ((a1 - a0) / st).round() as i64;
        for k in 0..=n.min(20) {
            let v = a0 + k as f64 * st;
            for i in 0..=ncat {
                let (x, y) = at(i % ncat, v);
                if i == 0 { cr.move_to(x, y) } else { cr.line_to(x, y) }
            }
            cr.stroke().ok();
            if !ch.val_deleted {
                let s = model::format_number(clean(v), "General");
                let (tw, h2) = pen.set(&s, &f, z, None);
                let (x, y) = at(0, v);
                rgb(cr, self.text.get());
                pen.show(cr, x - tw - 4.0 * z, y - h2 / 2.0);
                rgb(cr, LINE);
            }
        }
        for i in 0..ncat {
            let (x, y) = at(i, a1);
            cr.move_to(cx, cy);
            cr.line_to(x, y);
            cr.stroke().ok();
            if !ch.cat_deleted {
                let s = cats.get(i).cloned().unwrap_or_else(|| format!("{}", i + 1));
                let (tw, h2) = pen.set(&s, &f, z, None);
                let (dx, dy) = (ang(i).cos(), ang(i).sin());
                let lx = x + dx * 6.0 * z - tw / 2.0 + dx * tw / 2.0;
                let ly = y + dy * 6.0 * z - h2 / 2.0 + dy * h2 / 2.0;
                rgb(cr, self.text.get());
                pen.show(cr, lx, ly);
                rgb(cr, LINE);
            }
        }
        cr.set_line_join(cairo::LineJoin::Round);
        for s in data.iter().flatten() {
            if s.hidden {
                continue;
            }
            rgb(cr, s.color);
            cr.set_line_width(2.25 * z);
            cr.new_path();
            let mut first = true;
            for i in 0..=ncat {
                let k = i % ncat;
                let Some(v) = s.vals.get(k).copied().flatten() else { continue };
                let (x, y) = at(k, v);
                if first { cr.move_to(x, y); first = false } else { cr.line_to(x, y) }
            }
            cr.stroke().ok();
        }
    }

    fn paint_pie(&self, ch: &Chart, data: &[Vec<SerData>], cr: &Ctx, l: f64, t: f64, r: f64, b: f64, z: f64, pen: &mut Pen) {
        let p = &ch.plots[0];
        let s0 = match data.first().and_then(|d| d.first()) {
            Some(s) => s,
            None => return,
        };
        let total: f64 = s0.vals.iter().map(|v| v.unwrap_or(0.0).abs()).sum();
        if total <= 0.0 {
            return;
        }
        let cx = (l + r) / 2.0;
        let cy = (t + b) / 2.0;
        let rad = ((r - l).min(b - t) / 2.0) * 0.92;
        let hole = if p.kind == Kind::Doughnut { rad * (p.hole as f64 / 100.0).clamp(0.1, 0.9) } else { 0.0 };
        let mut a = -PI / 2.0 + p.first_angle as f64 * PI / 180.0;
        let theme = &self.theme;
        let f = self.chart_font(9.0, false);
        let mut labels = Vec::new();
        for (i, v) in s0.vals.iter().enumerate() {
            let v = v.unwrap_or(0.0).abs();
            if v == 0.0 {
                continue;
            }
            let sweep = v / total * 2.0 * PI;
            let color = s0.point_colors.iter().find(|(k, _)| *k == i).map(|x| x.1).unwrap_or_else(|| auto_color(theme, ch.palette, i));
            rgb(cr, color);
            cr.new_path();
            if hole > 0.0 {
                cr.arc(cx, cy, rad, a, a + sweep);
                cr.arc_negative(cx, cy, hole, a + sweep, a);
            } else {
                cr.move_to(cx, cy);
                cr.arc(cx, cy, rad, a, a + sweep);
            }
            cr.close_path();
            cr.fill_preserve().ok();
            rgb(cr, 0xFFFFFF);
            cr.set_line_width(1.5 * z);
            cr.stroke().ok();
            if s0.labels {
                let mid = a + sweep / 2.0;
                let rr = if hole > 0.0 { (rad + hole) / 2.0 } else { rad * 0.65 };
                labels.push((format!("{:.0}%", v / total * 100.0), cx + rr * mid.cos(), cy + rr * mid.sin(), color));
            }
            a += sweep;
        }
        for (text, x, y, color) in labels {
            let (tw, th) = pen.set(&text, &f, z, None);
            rgb(cr, if luma(color) < 140.0 { 0xFFFFFF } else { 0x404040 });
            pen.show(cr, x - tw / 2.0, y - th / 2.0);
        }
    }

    fn paint_axes_chart(&self, ch: &Chart, data: &[Vec<SerData>], cats: &[String], cr: &Ctx, l: f64, t: f64, r: f64, b: f64, z: f64, pen: &mut Pen) {
        let f = self.chart_font(9.0, false);
        let ft = self.chart_font(10.0, false);
        let horizontal = ch.plots.first().map(|p| p.horizontal && p.kind == Kind::Bar).unwrap_or(false);
        let scatter = ch.plots.first().map(|p| p.kind == Kind::Scatter).unwrap_or(false);
        let ncat = data.iter().flatten().map(|s| s.vals.len()).max().unwrap_or(0).max(cats.len()).max(1);
        // ---- value ranges per axis
        let range = |secondary: bool| -> Option<(f64, f64, bool)> {
            let mut lo = f64::INFINITY;
            let mut hi = f64::NEG_INFINITY;
            let mut percent = false;
            for (p, ser) in ch.plots.iter().zip(data) {
                if p.secondary != secondary {
                    continue;
                }
                match p.group {
                    Group::Clustered => {
                        for s in ser {
                            for v in s.vals.iter().flatten() {
                                lo = lo.min(*v);
                                hi = hi.max(*v);
                            }
                        }
                    }
                    Group::Stacked | Group::Percent => {
                        percent |= p.group == Group::Percent;
                        for i in 0..ncat {
                            let (mut pos, mut neg, mut tot) = (0.0, 0.0, 0.0);
                            for s in ser {
                                let v = s.vals.get(i).copied().flatten().unwrap_or(0.0);
                                if v >= 0.0 { pos += v } else { neg += v }
                                tot += v.abs();
                            }
                            if p.group == Group::Percent && tot > 0.0 {
                                pos /= tot;
                                neg /= tot;
                            }
                            lo = lo.min(neg);
                            hi = hi.max(pos);
                        }
                    }
                }
            }
            if lo > hi { None } else { Some((lo, hi, percent)) }
        };
        let fmt_of = |secondary: bool| -> String {
            ch.plots.iter().find(|p| p.secondary == secondary).and_then(|p| p.series.first()).and_then(|s| s.val.as_ref())
                .map(|v| v.fmt.clone().unwrap_or_else(|| "General".into())).unwrap_or_else(|| "General".into())
        };
        let (_, th) = pen.set("0", &f, z, None);
        let len_val = if horizontal || false { r - l } else { b - t };
        let ticks = (len_val / (th * 1.8)).clamp(2.0, 12.0);
        let mk = |rg: Option<(f64, f64, bool)>| -> Option<(f64, f64, f64, bool)> {
            let (lo, hi, pc) = rg?;
            let (a, b2, st) = if pc {
                let (a, b2, st) = nice_axis(lo, hi, ticks, true);
                (a.max(-1.0), b2.min(1.0), st)
            } else {
                nice_axis(lo, hi, ticks, true)
            };
            Some((a, b2, st, pc))
        };
        let prim = mk(range(false)).unwrap_or((0.0, 1.0, 0.2, false));
        let sec = mk(range(true));
        // x values (scatter)
        let xax = if scatter {
            let mut lo = f64::INFINITY;
            let mut hi = f64::NEG_INFINITY;
            for s in data.iter().flatten() {
                for i in 0..s.vals.len() {
                    let xv = if s.xs.is_empty() { Some(i as f64 + 1.0) } else { s.xs.get(i).copied().flatten() };
                    if let Some(xv) = xv {
                        lo = lo.min(xv);
                        hi = hi.max(xv);
                    }
                }
            }
            let xticks = ((r - l) / 60.0 / z).clamp(2.0, 10.0);
            if lo > hi { Some((0.0, 1.0, 0.2)) } else { Some(nice_axis(lo, hi, xticks, true)) }
        } else {
            None
        };
        let label = |v: f64, pc: bool, fmt: &str| -> String {
            if pc { format!("{:.0}%", v * 100.0) } else { model::format_number(clean(v), fmt) }
        };
        let ticks_of = |(lo, hi, st): (f64, f64, f64)| -> Vec<f64> {
            let mut out = Vec::new();
            let n = ((hi - lo) / st).round() as i64;
            for k in 0..=n.min(200) {
                out.push(clean(lo + k as f64 * st));
            }
            out
        };
        let pfmt = fmt_of(false);
        let sfmt = fmt_of(true);
        let prim_labels: Vec<(f64, String)> = ticks_of((prim.0, prim.1, prim.2)).into_iter().map(|v| (v, label(v, prim.3, &pfmt))).collect();
        let sec_labels: Vec<(f64, String)> = sec.map(|s| ticks_of((s.0, s.1, s.2)).into_iter().map(|v| (v, label(v, s.3, &sfmt))).collect()).unwrap_or_default();
        let x_labels: Vec<(f64, String)> = xax.map(|a| ticks_of(a).into_iter().map(|v| (v, model::format_number(v, "General"))).collect()).unwrap_or_default();
        let maxw = |v: &[(f64, String)], pen: &mut Pen| v.iter().map(|(_, s)| pen.set(s, &f, z, None).0).fold(0.0, f64::max);
        // ---- room for labels and titles
        let mut pl = l;
        let mut pr = r;
        let pt = t + th / 2.0;
        let mut pb = b;
        // axis titles
        let (xt, yt) = if horizontal { (ch.y_title.clone(), ch.x_title.clone()) } else { (ch.x_title.clone(), ch.y_title.clone()) };
        let yt_h = yt.as_ref().filter(|s| !s.is_empty()).map(|s| pen.set(s, &ft, z, None).1 + 4.0 * z).unwrap_or(0.0);
        let xt_h = xt.as_ref().filter(|s| !s.is_empty()).map(|s| pen.set(s, &ft, z, None).1 + 4.0 * z).unwrap_or(0.0);
        pl += yt_h;
        pb -= xt_h;
        let cat_texts: Vec<String> = (0..ncat).map(|i| cats.get(i).cloned().unwrap_or_else(|| format!("{}", i + 1))).collect();
        // a data table under the plot, in place of the category labels
        let nser_shown: Vec<(u32, String, Vec<Option<f64>>)> = if ch.data_table && !horizontal && !scatter {
            let mut v = Vec::new();
            let mut k = 0usize;
            for (p, ser) in ch.plots.iter().zip(data) {
                for (j, s) in ser.iter().enumerate() {
                    let name = model::series_name(&p.series[j], k);
                    k += 1;
                    if !s.hidden {
                        v.push((s.color, name, s.vals.clone()));
                    }
                }
            }
            v
        } else {
            Vec::new()
        };
        let row_h = th + 4.0 * z;
        let key_w = if nser_shown.is_empty() { 0.0 } else {
            nser_shown.iter().map(|(_, n, _)| pen.set(n, &f, z, None).0).fold(0.0, f64::max) + 14.0 * z
        };
        if horizontal {
            if !ch.cat_deleted {
                let cw = cat_texts.iter().map(|s| pen.set(s, &f, z, None).0).fold(0.0, f64::max).min((r - l) * 0.4);
                pl += cw + 6.0 * z;
            }
            if !ch.val_deleted {
                pb -= th + 4.0 * z;
                let lastw = prim_labels.last().map(|x| pen.set(&x.1, &f, z, None).0).unwrap_or(0.0);
                pr -= lastw / 2.0;
            }
        } else {
            if !ch.val_deleted {
                pl += maxw(&prim_labels, pen) + 6.0 * z;
            }
            if !nser_shown.is_empty() {
                pl = pl.max(l + key_w);
                pb -= row_h * (nser_shown.len() + 1) as f64;
            } else if !ch.cat_deleted {
                pb -= th + 4.0 * z;
            }
            if !sec_labels.is_empty() {
                pr -= maxw(&sec_labels, pen) + 6.0 * z;
            } else {
                pr -= 4.0 * z;
            }
            if scatter {
                let lastw = x_labels.last().map(|x| pen.set(&x.1, &f, z, None).0).unwrap_or(0.0);
                pr -= lastw / 2.0;
            }
        }
        if pr - pl < 10.0 || pb - pt < 10.0 {
            return;
        }
        // value -> screen
        let vmap = |v: f64, ax: (f64, f64, f64, bool)| -> f64 {
            let k = (v - ax.0) / (ax.1 - ax.0);
            if horizontal { pl + k * (pr - pl) } else { pb - k * (pb - pt) }
        };
        let xmap = |v: f64| -> f64 {
            let a = xax.unwrap();
            pl + (v - a.0) / (a.1 - a.0) * (pr - pl)
        };
        // ---- gridlines and value labels
        cr.set_line_width(z.max(1.0));
        if ch.minor_h && prim_labels.len() > 1 {
            rgb(cr, 0xF2F2F2);
            for w2 in prim_labels.windows(2) {
                let mid = vmap((w2[0].0 + w2[1].0) / 2.0, prim).round() + 0.5;
                if horizontal {
                    cr.move_to(mid, pt);
                    cr.line_to(mid, pb);
                } else {
                    cr.move_to(pl, mid);
                    cr.line_to(pr, mid);
                }
                cr.stroke().ok();
            }
        }
        if (ch.vgrid || ch.minor_v) && !scatter {
            let slot = if horizontal { (pb - pt) / ncat as f64 } else { (pr - pl) / ncat as f64 };
            for i in 0..=ncat {
                for half in [0.0, 0.5] {
                    if (half == 0.0 && !ch.vgrid) || (half > 0.0 && (!ch.minor_v || i == ncat)) {
                        continue;
                    }
                    rgb(cr, if half > 0.0 { 0xF2F2F2 } else { LINE });
                    let q = (i as f64 + half) * slot;
                    if horizontal {
                        let y = (pb - q).round() + 0.5;
                        cr.move_to(pl, y);
                        cr.line_to(pr, y);
                    } else {
                        let x = (pl + q).round() + 0.5;
                        cr.move_to(x, pt);
                        cr.line_to(x, pb);
                    }
                    cr.stroke().ok();
                }
            }
        }
        for (v, s) in &prim_labels {
            let p = vmap(*v, prim).round() + 0.5;
            if ch.gridlines {
                rgb(cr, LINE);
                if horizontal {
                    cr.move_to(p, pt);
                    cr.line_to(p, pb);
                } else {
                    cr.move_to(pl, p);
                    cr.line_to(pr, p);
                }
                cr.stroke().ok();
            }
            if ch.val_deleted {
                continue;
            }
            let (tw, h2) = pen.set(s, &f, z, None);
            rgb(cr, self.text.get());
            if horizontal {
                pen.show(cr, p - tw / 2.0, pb + 4.0 * z);
            } else {
                pen.show(cr, pl - 6.0 * z - tw, p - h2 / 2.0);
            }
        }
        if let Some(sa) = sec {
            for (v, s) in &sec_labels {
                let p = vmap(*v, sa);
                let (_, h2) = pen.set(s, &f, z, None);
                rgb(cr, self.text.get());
                pen.show(cr, pr + 6.0 * z, p - h2 / 2.0);
            }
        }
        // ---- category / x axis
        if scatter {
            for (v, s) in &x_labels {
                let p = xmap(*v).round() + 0.5;
                if ch.gridlines && false {
                    rgb(cr, LINE);
                    cr.move_to(p, pt);
                    cr.line_to(p, pb);
                    cr.stroke().ok();
                }
                let (tw, _) = pen.set(s, &f, z, None);
                rgb(cr, self.text.get());
                pen.show(cr, p - tw / 2.0, pb + 4.0 * z);
            }
        } else if !nser_shown.is_empty() {
            // ---- the data table: categories across, a row per series
            let slot = (pr - pl) / ncat as f64;
            let x0 = l;
            let rows = nser_shown.len() + 1;
            rgb(cr, LINE);
            for k in 0..=rows {
                let y = (pb + k as f64 * row_h).round() + 0.5;
                cr.move_to(if k == 0 { pl } else { x0 }, y);
                cr.line_to(pr, y);
                cr.stroke().ok();
            }
            for i in 0..=ncat {
                let x = (pl + i as f64 * slot).round() + 0.5;
                cr.move_to(x, pb);
                cr.line_to(x, pb + rows as f64 * row_h);
                cr.stroke().ok();
            }
            cr.move_to(x0 + 0.5, pb + row_h);
            cr.line_to(x0 + 0.5, pb + rows as f64 * row_h);
            cr.stroke().ok();
            for (i, s) in cat_texts.iter().enumerate() {
                let (tw, _) = pen.set(s, &f, z, None);
                rgb(cr, self.text.get());
                pen.show(cr, pl + (i as f64 + 0.5) * slot - tw / 2.0, pb + 2.0 * z);
            }
            for (k, (color, name, vals)) in nser_shown.iter().enumerate() {
                let y = pb + (k + 1) as f64 * row_h;
                rgb(cr, *color);
                cr.rectangle(x0 + 3.0 * z, y + row_h / 2.0 - 3.0 * z, 6.0 * z, 6.0 * z);
                cr.fill().ok();
                pen.set(name, &f, z, None);
                rgb(cr, self.text.get());
                pen.show(cr, x0 + 12.0 * z, y + 2.0 * z);
                for (i, v) in vals.iter().enumerate().take(ncat) {
                    if let Some(v) = v {
                        let t2 = label(*v, false, &pfmt);
                        let (tw, _) = pen.set(&t2, &f, z, None);
                        rgb(cr, self.text.get());
                        pen.show(cr, pl + (i as f64 + 0.5) * slot - tw / 2.0, y + 2.0 * z);
                    }
                }
            }
        } else if !ch.cat_deleted {
            let slot = if horizontal { (pb - pt) / ncat as f64 } else { (pr - pl) / ncat as f64 };
            let widest = cat_texts.iter().map(|s| pen.set(s, &f, z, None).0).fold(0.0, f64::max);
            let every = if horizontal { ((th + 2.0) / slot).ceil().max(1.0) as usize } else { ((widest + 6.0 * z) / slot).ceil().max(1.0) as usize };
            for (i, s) in cat_texts.iter().enumerate() {
                if i % every != 0 {
                    continue;
                }
                let (tw, h2) = pen.set(s, &f, z, None);
                rgb(cr, self.text.get());
                if horizontal {
                    // the first category at the bottom
                    let cy = pb - (i as f64 + 0.5) * slot;
                    pen.show(cr, pl - 6.0 * z - tw.min((r - l) * 0.4), cy - h2 / 2.0);
                } else {
                    let cx = pl + (i as f64 + 0.5) * slot;
                    pen.show(cr, cx - tw / 2.0, pb + 4.0 * z);
                }
            }
        }
        // the category axis line, at zero
        let zero = vmap(if prim.0 > 0.0 { prim.0 } else if prim.1 < 0.0 { prim.1 } else { 0.0 }, prim).round() + 0.5;
        rgb(cr, LINE);
        if horizontal {
            cr.move_to(zero, pt);
            cr.line_to(zero, pb);
        } else if scatter {
            cr.move_to(pl, zero);
            cr.line_to(pr, zero);
        } else {
            cr.move_to(pl, zero);
            cr.line_to(pr, zero);
        }
        cr.stroke().ok();
        // ---- titles
        if let Some(s) = xt.filter(|s| !s.is_empty()) {
            let (tw, _) = pen.set(&s, &ft, z, None);
            rgb(cr, self.text.get());
            pen.show(cr, (pl + pr) / 2.0 - tw / 2.0, b - xt_h + 2.0 * z);
        }
        if let Some(s) = yt.filter(|s| !s.is_empty()) {
            let (tw, _) = pen.set(&s, &ft, z, None);
            rgb(cr, self.text.get());
            cr.save().ok();
            cr.translate(l, (pt + pb) / 2.0 + tw / 2.0);
            cr.rotate(-PI / 2.0);
            pen.show(cr, 0.0, 0.0);
            cr.restore().ok();
        }
        // ---- series
        cr.save().ok();
        cr.rectangle(pl - 6.0 * z, pt - 6.0 * z, pr - pl + 12.0 * z, pb - pt + 12.0 * z);
        cr.clip();
        cr.set_line_join(cairo::LineJoin::Round);
        cr.set_line_cap(cairo::LineCap::Round);
        let nbar = ch.plots.iter().filter(|p| p.kind == Kind::Bar).count().max(1);
        let _ = nbar;
        let mut labels: Vec<(String, f64, f64)> = Vec::new();
        for (p, ser) in ch.plots.iter().zip(data) {
            let ax = if p.secondary { sec.unwrap_or(prim) } else { prim };
            let fmt = if p.secondary { &sfmt } else { &pfmt };
            match p.kind {
                Kind::Bar => self.paint_bars(p, ser, ncat, ax, horizontal, pl, pt, pr, pb, cr, &vmap, fmt, &mut labels),
                Kind::Line | Kind::Area => self.paint_lines(p, ser, ncat, ax, pl, pr, cr, &vmap, z, fmt, &mut labels),
                Kind::Scatter => {
                    for s in ser {
                        let pts: Vec<Option<(f64, f64)>> = (0..s.vals.len()).map(|i| {
                            let xv = if s.xs.is_empty() { Some(i as f64 + 1.0) } else { s.xs.get(i).copied().flatten() };
                            Some((xmap(xv?), vmap(s.vals[i]?, ax)))
                        }).collect();
                        rgb(cr, s.color);
                        if p.lines {
                            cr.set_line_width(2.25 * z);
                            stroke_runs(cr, &pts, s.smooth);
                        }
                        if p.markers || !p.lines {
                            for (x, y) in pts.iter().flatten() {
                                cr.arc(*x, *y, 3.0 * z, 0.0, 2.0 * PI);
                                cr.fill().ok();
                            }
                        }
                        if s.labels {
                            for (i, pt2) in pts.iter().enumerate() {
                                if let (Some((x, y)), Some(v)) = (pt2, s.vals[i]) {
                                    labels.push((label(v, false, fmt), *x, *y - 4.0 * z));
                                }
                            }
                        }
                    }
                }
                _ => {}
            }
        }
        cr.restore().ok();
        for (text, x, y) in labels {
            let (tw, h2) = pen.set(&text, &f, z, None);
            rgb(cr, 0x404040);
            pen.show(cr, x - tw / 2.0, y - h2);
        }
    }

    #[allow(clippy::too_many_arguments)]
    fn paint_bars(&self, p: &Plot, ser: &[SerData], ncat: usize, ax: (f64, f64, f64, bool), horizontal: bool,
                         pl: f64, pt: f64, pr: f64, pb: f64, cr: &Ctx, vmap: &dyn Fn(f64, (f64, f64, f64, bool)) -> f64,
                         fmt: &str, labels: &mut Vec<(String, f64, f64)>) {
        let slot = if horizontal { (pb - pt) / ncat as f64 } else { (pr - pl) / ncat as f64 };
        let g = p.gap as f64 / 100.0;
        let n = ser.len().max(1) as f64;
        let stacked = p.group != Group::Clustered;
        let ov = if stacked { 1.0 } else { (p.overlap as f64 / 100.0).clamp(-1.0, 1.0) };
        let bw = slot / (n - (n - 1.0) * ov + g);
        let group_w = bw * (n - (n - 1.0) * ov);
        let base_v = if ax.0 > 0.0 { ax.0 } else if ax.1 < 0.0 { ax.1 } else { 0.0 };
        for i in 0..ncat {
            let center = if horizontal { pb - (i as f64 + 0.5) * slot } else { pl + (i as f64 + 0.5) * slot };
            let start = center - group_w / 2.0;
            let tot: f64 = ser.iter().map(|s| s.vals.get(i).copied().flatten().unwrap_or(0.0).abs()).sum();
            let (mut pos, mut neg) = (0.0, 0.0);
            for (j, s) in ser.iter().enumerate() {
                let v = match s.vals.get(i).copied().flatten() {
                    Some(v) => v,
                    None => continue,
                };
                let v2 = if p.group == Group::Percent && tot > 0.0 { v / tot } else { v };
                let (a, bb) = if stacked {
                    if v2 >= 0.0 { let a = pos; pos += v2; (a, pos) } else { let a = neg; neg += v2; (a, neg) }
                } else {
                    (base_v, v2)
                };
                let off = if stacked { 0.0 } else { j as f64 * bw * (1.0 - ov) };
                let p0 = vmap(a, ax);
                let p1 = vmap(bb, ax);
                if s.hidden {
                    continue;
                }
                rgb(cr, s.color);
                let pos = s.label_pos.as_deref().unwrap_or(if stacked { "ctr" } else { "outEnd" });
                if horizontal {
                    // series run top to bottom in a category, as Excel draws them
                    let y0 = start + group_w - off - bw;
                    cr.rectangle(p0.min(p1), y0, (p1 - p0).abs(), bw);
                    cr.fill().ok();
                    if s.labels {
                        let (lo, hi) = (p0.min(p1), p0.max(p1));
                        let x = match pos { "ctr" => (lo + hi) / 2.0, "inEnd" => hi - 12.0, "inBase" => lo + 12.0, _ => hi + 12.0 };
                        labels.push((self.fmt_label(v, fmt), x, y0 + bw / 2.0 + 6.0));
                    }
                } else {
                    let x0 = start + off;
                    cr.rectangle(x0, p0.min(p1), bw, (p1 - p0).abs());
                    cr.fill().ok();
                    if s.labels {
                        let (top, bot) = (p0.min(p1), p0.max(p1));
                        let y = match pos { "ctr" => (top + bot) / 2.0 + 6.0, "inEnd" => top + 14.0, "inBase" => bot - 2.0, _ => top - 2.0 };
                        labels.push((self.fmt_label(v, fmt), x0 + bw / 2.0, y));
                    }
                }
            }
        }
    }

    fn fmt_label(&self, v: f64, fmt: &str) -> String {
        model::format_number(v, fmt)
    }

    #[allow(clippy::too_many_arguments)]
    fn paint_lines(&self, p: &Plot, ser: &[SerData], ncat: usize, ax: (f64, f64, f64, bool), pl: f64, pr: f64,
                          cr: &Ctx, vmap: &dyn Fn(f64, (f64, f64, f64, bool)) -> f64, z: f64, fmt: &str,
                          labels: &mut Vec<(String, f64, f64)>) {
        let slot = (pr - pl) / ncat as f64;
        let stacked = p.group != Group::Clustered;
        let tot: Vec<f64> = (0..ncat).map(|i| ser.iter().map(|s| s.vals.get(i).copied().flatten().unwrap_or(0.0).abs()).sum()).collect();
        let mut below = vec![0.0f64; ncat];
        let base_v = if ax.0 > 0.0 { ax.0 } else if ax.1 < 0.0 { ax.1 } else { 0.0 };
        if p.stock {
            // high-low lines across the series, up-down bars from the first to the last
            for i in 0..ncat {
                let vs: Vec<f64> = ser.iter().filter_map(|s| s.vals.get(i).copied().flatten()).collect();
                if vs.len() < 2 {
                    continue;
                }
                let x = pl + (i as f64 + 0.5) * slot;
                let lo = vs.iter().cloned().fold(f64::INFINITY, f64::min);
                let hi = vs.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
                rgb(cr, 0x404040);
                cr.set_line_width(1.0 * z);
                cr.move_to(x.round() + 0.5, vmap(lo, ax));
                cr.line_to(x.round() + 0.5, vmap(hi, ax));
                cr.stroke().ok();
                let (o, c) = (vs[0], *vs.last().unwrap());
                let bw = slot * 0.4;
                let (y0, y1) = (vmap(o, ax), vmap(c, ax));
                rgb(cr, if c >= o { 0x4472C4 } else { 0x2F528F });
                cr.rectangle(x - bw / 2.0, y0.min(y1), bw, (y1 - y0).abs().max(1.0));
                cr.fill_preserve().ok();
                rgb(cr, 0x2F528F);
                cr.stroke().ok();
            }
        }
        // areas are drawn back to front: the first series is behind
        for s in ser {
            if s.hidden && p.kind != Kind::Area {
                continue;
            }
            let mut vals: Vec<Option<f64>> = (0..ncat).map(|i| {
                let v = s.vals.get(i).copied().flatten();
                let v = if p.group == Group::Percent { v.map(|x| if tot[i] > 0.0 { x / tot[i] } else { 0.0 }) } else { v };
                if stacked { Some(below[i] + v.unwrap_or(0.0)) } else { v }
            }).collect();
            if p.kind == Kind::Area && !stacked {
                for v in vals.iter_mut() {
                    v.get_or_insert(0.0);
                }
            }
            let pts: Vec<Option<(f64, f64)>> = vals.iter().enumerate().map(|(i, v)| v.map(|v| (pl + (i as f64 + 0.5) * slot, vmap(v, ax)))).collect();
            rgb(cr, s.color);
            if p.kind == Kind::Area {
                // from the series below (or the axis) up to this one
                let xs: Vec<f64> = (0..ncat).map(|i| if ncat == 1 { (pl + pr) / 2.0 } else { pl + i as f64 * (pr - pl) / (ncat - 1) as f64 }).collect();
                cr.new_path();
                for i in 0..ncat {
                    let y = vmap(vals[i].unwrap_or(base_v), ax);
                    if i == 0 { cr.move_to(xs[i], y) } else { cr.line_to(xs[i], y) }
                }
                for i in (0..ncat).rev() {
                    let y = vmap(if stacked { below[i] } else { base_v }, ax);
                    cr.line_to(xs[i], y);
                }
                cr.close_path();
                cr.fill().ok();
            } else {
                cr.set_line_width(2.25 * z);
                stroke_runs(cr, &pts, s.smooth);
                if p.markers {
                    for (x, y) in pts.iter().flatten() {
                        cr.arc(*x, *y, 3.0 * z, 0.0, 2.0 * PI);
                        cr.fill().ok();
                    }
                }
            }
            if s.labels {
                for (i, pt) in pts.iter().enumerate() {
                    if let (Some((x, y)), Some(v)) = (pt, s.vals.get(i).copied().flatten()) {
                        labels.push((self.fmt_label(v, fmt), *x, *y - 4.0 * z));
                    }
                }
            }
            if stacked {
                for i in 0..ncat {
                    below[i] = vals[i].unwrap_or(below[i]);
                }
            }
        }
    }
}

/// Stroke the unbroken runs of points (gaps for blanks), straight or smoothed.
fn stroke_runs(cr: &Ctx, pts: &[Option<(f64, f64)>], smooth: bool) {
    let mut run: Vec<(f64, f64)> = Vec::new();
    let flush = |run: &mut Vec<(f64, f64)>| {
        if run.len() >= 2 {
            cr.new_path();
            cr.move_to(run[0].0, run[0].1);
            for k in 1..run.len() {
                if smooth {
                    let p0 = if k >= 2 { run[k - 2] } else { run[k - 1] };
                    let p1 = run[k - 1];
                    let p2 = run[k];
                    let p3 = if k + 1 < run.len() { run[k + 1] } else { run[k] };
                    let c1 = (p1.0 + (p2.0 - p0.0) / 6.0, p1.1 + (p2.1 - p0.1) / 6.0);
                    let c2 = (p2.0 - (p3.0 - p1.0) / 6.0, p2.1 - (p3.1 - p1.1) / 6.0);
                    cr.curve_to(c1.0, c1.1, c2.0, c2.1, p2.0, p2.1);
                } else {
                    cr.line_to(run[k].0, run[k].1);
                }
            }
            cr.stroke().ok();
        }
        run.clear();
    };
    for p in pts {
        match p {
            Some(x) => run.push(*x),
            None => flush(&mut run),
        }
    }
    flush(&mut run);
}

#[cfg(test)]
mod tests {
    use super::nice_axis;
    #[test]
    fn axes() {
        assert_eq!(nice_axis(10.0, 40.0, 10.0, true), (0.0, 45.0, 5.0));
        let (lo, hi, _) = nice_axis(95.0, 100.0, 6.0, true);
        assert!(lo > 0.0 && lo <= 95.0 && hi >= 100.0);
        let (lo, hi, _) = nice_axis(-20.0, 30.0, 6.0, true);
        assert!(lo <= -20.0 && hi >= 30.0);
    }
}
