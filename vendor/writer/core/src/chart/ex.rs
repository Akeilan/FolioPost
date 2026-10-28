//! Office 2016 charts (cx:chartSpace parts): treemap and sunburst, drawn
//! from the data cached in the part (categories as levels, sizes).

use super::xml::{self, Element};
use std::f64::consts::PI;

type Ctx = cairo::Context;

pub struct ExChart {
    pub layout: String,
    pub title: Option<String>,
    pub legend: Option<String>,
    /// (path from the top level down, value)
    pub items: Vec<(Vec<String>, f64)>,
    pub labels: bool,
    pub values: bool,
    pub colors: Vec<u32>,
}

fn lvl_pts(l: &Element) -> Vec<(usize, String)> {
    l.elems_named("pt").filter_map(|p| Some((p.attr("idx")?.parse().ok()?, p.text()))).collect()
}

pub fn parse(text: &str, theme: &[u32; 12]) -> Option<ExChart> {
    let (_p, root) = xml::parse(text).ok()?;
    let chart = root.child("chart")?;
    let series = chart.child("plotArea")?.child("plotAreaRegion")?.child("series")?;
    let layout = series.attr("layoutId").unwrap_or("treemap").to_string();
    let data_id = series.child("dataId").and_then(|d| d.attr("val")).unwrap_or("0").to_string();
    let data = root.child("chartData")?.elems_named("data").find(|d| d.attr("id").unwrap_or("0") == data_id)?;
    let mut levels: Vec<Vec<(usize, String)>> = Vec::new();
    let mut vals: Vec<(usize, f64)> = Vec::new();
    for dim in data.elems() {
        match dim.local() {
            "strDim" => {
                for l in dim.elems_named("lvl") {
                    levels.push(lvl_pts(l));
                }
            }
            "numDim" => {
                if let Some(l) = dim.elems_named("lvl").next() {
                    vals = lvl_pts(l).into_iter().filter_map(|(i, t)| Some((i, t.trim().parse().ok()?))).collect();
                }
            }
            _ => {}
        }
    }
    // the first level is the innermost (the leaves)
    levels.reverse();
    let n = vals.iter().map(|v| v.0 + 1).max().unwrap_or(0);
    let mut items = Vec::new();
    for i in 0..n {
        let v = vals.iter().find(|x| x.0 == i).map(|x| x.1).unwrap_or(0.0);
        let mut path = Vec::new();
        for l in &levels {
            if let Some((_, t)) = l.iter().find(|x| x.0 == i) {
                if !t.is_empty() {
                    path.push(t.clone());
                }
            }
        }
        if v > 0.0 {
            items.push((path, v));
        }
    }
    let title = chart.child("title").map(|t| {
        let tx = t.child("tx");
        tx.and_then(|x| x.child("txData")).and_then(|d| d.child("v")).map(|v| v.text())
            .or_else(|| tx.and_then(|x| x.child("rich")).map(|r| r.elems_named("p")
                .map(|p| p.elems().filter(|e| e.local() == "r").map(|r| r.child("t").map(|t| t.text()).unwrap_or_default()).collect::<String>())
                .collect::<Vec<_>>().join("\n")))
            .unwrap_or_else(|| "Chart Title".into())
    });
    let legend = chart.child("legend").map(|l| l.attr("pos").unwrap_or("t").to_string());
    let (mut labels, mut values) = (true, false);
    if let Some(v) = series.child("dataLabels").and_then(|d| d.child("visibility")) {
        labels = v.attr("categoryName").map_or(true, |x| x == "1" || x == "true");
        values = v.attr("value").map_or(false, |x| x == "1" || x == "true");
    }
    if series.child("dataLabels").is_none() {
        labels = false;
    }
    let mut colors = theme[4..10].to_vec();
    colors.extend_from_slice(&[0x264478, 0x9E480E, 0x636363, 0x997300]);
    Some(ExChart { layout, title, legend, items, labels, values, colors })
}

fn rgb(cr: &Ctx, c: u32) {
    cr.set_source_rgb(((c >> 16) & 255) as f64 / 255.0, ((c >> 8) & 255) as f64 / 255.0, (c & 255) as f64 / 255.0);
}

fn tint(c: u32, f: f64) -> u32 {
    let ch = |s: u32| { let x = ((c >> s) & 255) as f64; (x + (255.0 - x) * f).round().clamp(0.0, 255.0) as u32 };
    (ch(16) << 16) | (ch(8) << 8) | ch(0)
}

fn squarify(values: &[f64], mut x: f64, mut y: f64, mut w: f64, mut h: f64) -> Vec<(f64, f64, f64, f64)> {
    let total: f64 = values.iter().sum::<f64>().max(1e-9);
    let mut vals: Vec<f64> = values.iter().map(|v| v * w * h / total).collect();
    let mut rects = Vec::new();
    let worst = |row: &[f64], side: f64| {
        let s: f64 = row.iter().sum();
        row.iter().map(|r| (side * side * r / (s * s)).max((s * s) / (side * side * r))).fold(0.0, f64::max)
    };
    while !vals.is_empty() {
        let side = w.min(h).max(1e-9);
        let mut row = vec![vals.remove(0)];
        while !vals.is_empty() {
            let mut t = row.clone();
            t.push(vals[0]);
            if worst(&t, side) <= worst(&row, side) {
                row.push(vals.remove(0));
            } else {
                break;
            }
        }
        let s: f64 = row.iter().sum();
        if w >= h {
            let cw = s / h.max(1e-9);
            let mut yy = y;
            for r in &row {
                let rh = r / cw.max(1e-9);
                rects.push((x, yy, cw, rh));
                yy += rh;
            }
            x += cw;
            w -= cw;
        } else {
            let rh = s / w.max(1e-9);
            let mut xx = x;
            for r in &row {
                let cw = r / rh.max(1e-9);
                rects.push((xx, y, cw, rh));
                xx += cw;
            }
            y += rh;
            h -= rh;
        }
    }
    rects
}

fn font(cr: &Ctx, family: &str, size: f64) {
    cr.select_font_face(family, cairo::FontSlant::Normal, cairo::FontWeight::Normal);
    cr.set_font_size(size);
}

fn text_w(cr: &Ctx, t: &str) -> f64 {
    cr.text_extents(t).map(|e| e.x_advance()).unwrap_or(0.0)
}

/// Draw the chart into (0, 0, w, h) points.
pub fn draw(cr: &Ctx, ch: &ExChart, w: f64, h: f64, family: &str) {
    cr.save().ok();
    cr.rectangle(0.0, 0.0, w, h);
    cr.clip();
    rgb(cr, 0xFFFFFF);
    cr.paint().ok();
    rgb(cr, 0xD9D9D9);
    cr.set_line_width(1.0);
    cr.rectangle(0.5, 0.5, w - 1.0, h - 1.0);
    cr.stroke().ok();
    let (mut l, mut t, mut r, mut b) = (8.0, 8.0, w - 8.0, h - 8.0);
    if let Some(title) = &ch.title {
        font(cr, family, 14.0);
        rgb(cr, 0x595959);
        let tw = text_w(cr, title);
        cr.move_to((w - tw) / 2.0, t + 14.0);
        cr.show_text(title).ok();
        t += 24.0;
    }
    // groups: the top level
    let mut groups: Vec<String> = Vec::new();
    for (p, _) in &ch.items {
        let g = p.first().cloned().unwrap_or_default();
        if !groups.contains(&g) {
            groups.push(g);
        }
    }
    let nested = ch.items.iter().any(|(p, _)| p.len() > 1);
    let color = |i: usize| ch.colors[i % ch.colors.len()];
    let names: Vec<String> = if nested { groups.clone() } else { ch.items.iter().map(|(p, _)| p.join(" ")).collect() };
    if let Some(pos) = &ch.legend {
        font(cr, family, 9.0);
        let key = 7.0;
        match pos.as_str() {
            "l" | "r" => {
                let lw = names.iter().map(|n| text_w(cr, n)).fold(0.0, f64::max) + key + 12.0;
                let x = if pos == "r" { r - lw } else { l };
                let y0 = t + ((b - t) - 14.0 * names.len() as f64).max(0.0) / 2.0;
                for (i, n) in names.iter().enumerate() {
                    rgb(cr, color(i));
                    cr.rectangle(x, y0 + i as f64 * 14.0 + 2.0, key, key);
                    cr.fill().ok();
                    rgb(cr, 0x595959);
                    cr.move_to(x + key + 4.0, y0 + i as f64 * 14.0 + 9.0);
                    cr.show_text(n).ok();
                }
                if pos == "r" { r -= lw + 6.0 } else { l += lw + 6.0 }
            }
            _ => {
                let total: f64 = names.iter().map(|n| text_w(cr, n) + key + 14.0).sum();
                let mut x = l + ((r - l) - total).max(0.0) / 2.0;
                let y = if pos == "b" { b - 10.0 } else { t + 2.0 };
                for (i, n) in names.iter().enumerate() {
                    rgb(cr, color(i));
                    cr.rectangle(x, y, key, key);
                    cr.fill().ok();
                    rgb(cr, 0x595959);
                    cr.move_to(x + key + 4.0, y + 7.0);
                    cr.show_text(n).ok();
                    x += text_w(cr, n) + key + 14.0;
                }
                if pos == "b" { b -= 16.0 } else { t += 16.0 }
            }
        }
    }
    let label = |cr: &Ctx, x: f64, y: f64, lab: &str, v: f64, center: bool, maxw: f64| {
        let mut lines = Vec::new();
        if ch.labels {
            lines.push(lab.to_string());
        }
        if ch.values {
            lines.push(super::model::format_number(v, "General"));
        }
        font(cr, family, 9.0);
        rgb(cr, 0xFFFFFF);
        for (k, s) in lines.iter().enumerate() {
            let tw = text_w(cr, s);
            if tw > maxw {
                continue;
            }
            cr.move_to(if center { x - tw / 2.0 } else { x }, y + k as f64 * 11.0);
            cr.show_text(s).ok();
        }
    };
    if ch.layout == "sunburst" {
        let cx = (l + r) / 2.0;
        let cy = (t + b) / 2.0;
        let r_out = ((r - l).min(b - t) / 2.0 - 2.0).max(4.0);
        let r_mid = r_out * if nested { 0.55 } else { 0.35 };
        let r_in = if nested { r_out * 0.18 } else { r_mid };
        let total: f64 = ch.items.iter().map(|x| x.1).sum::<f64>().max(1e-9);
        let arc = |cr: &Ctx, r0: f64, r1: f64, a0: f64, a1: f64, c: u32| {
            cr.new_path();
            cr.arc(cx, cy, r1, a0, a1);
            cr.arc_negative(cx, cy, r0, a1, a0);
            cr.close_path();
            rgb(cr, c);
            cr.fill_preserve().ok();
            rgb(cr, 0xFFFFFF);
            cr.set_line_width(1.5);
            cr.stroke().ok();
        };
        let mut a = -PI / 2.0;
        for (gi, g) in groups.iter().enumerate() {
            let gv: f64 = ch.items.iter().filter(|(p, _)| p.first() == Some(g)).map(|x| x.1).sum();
            let ga = 2.0 * PI * gv / total;
            let base = color(gi);
            if nested {
                arc(cr, r_in, r_mid, a, a + ga, base);
            }
            let mut la = a;
            for (k, (p, v)) in ch.items.iter().enumerate().filter(|(_, (p, _))| p.first() == Some(g)) {
                let sa = 2.0 * PI * v / total;
                let c = if nested { tint(base, 0.25) } else { color(k) };
                arc(cr, if nested { r_mid } else { r_in }, r_out, la, la + sa, c);
                let mid = la + sa / 2.0;
                let rr = (r_out + if nested { r_mid } else { r_in }) / 2.0;
                if sa > 0.2 {
                    let leaf = if nested { p[1..].join(" ") } else { p.join(" ") };
                    label(cr, cx + rr * mid.cos(), cy + rr * mid.sin() + 3.0, &leaf, *v, true, (r_out - r_mid) * 1.2);
                }
                la += sa;
            }
            if nested && ga > 0.2 && ch.labels {
                let mid = a + ga / 2.0;
                let rr = (r_mid + r_in) / 2.0;
                font(cr, family, 9.0);
                rgb(cr, 0xFFFFFF);
                let tw = text_w(cr, g);
                cr.move_to(cx + rr * mid.cos() - tw / 2.0, cy + rr * mid.sin() + 3.0);
                cr.show_text(g).ok();
            }
            a += ga;
        }
    } else {
        // treemap: groups by size, then their leaves inside them
        let mut gvals: Vec<(usize, f64)> = groups.iter().enumerate()
            .map(|(i, g)| (i, ch.items.iter().filter(|(p, _)| p.first() == Some(g)).map(|x| x.1).sum())).collect();
        gvals.sort_by(|x, y| y.1.partial_cmp(&x.1).unwrap_or(std::cmp::Ordering::Equal));
        let grects = squarify(&gvals.iter().map(|x| x.1).collect::<Vec<_>>(), l, t, r - l, b - t);
        for ((gi, _), (gx, gy, gw, gh)) in gvals.iter().zip(grects) {
            let g = &groups[*gi];
            let mut leaves: Vec<(usize, &Vec<String>, f64)> = ch.items.iter().enumerate()
                .filter(|(_, (p, _))| p.first() == Some(g)).map(|(k, (p, v))| (k, p, *v)).collect();
            leaves.sort_by(|x, y| y.2.partial_cmp(&x.2).unwrap_or(std::cmp::Ordering::Equal));
            let lr = squarify(&leaves.iter().map(|x| x.2).collect::<Vec<_>>(), gx, gy, gw, gh);
            for ((k, p, v), (lx, ly, lw, lh)) in leaves.iter().zip(lr) {
                rgb(cr, if nested { color(*gi) } else { color(*k) });
                cr.rectangle(lx, ly, lw, lh);
                cr.fill_preserve().ok();
                rgb(cr, 0xFFFFFF);
                cr.set_line_width(1.5);
                cr.stroke().ok();
                if lw > 24.0 && lh > 14.0 {
                    let leaf = if nested { p[1..].join(" ") } else { p.join(" ") };
                    label(cr, lx + 4.0, ly + 12.0, &leaf, *v, false, lw - 6.0);
                }
            }
            if nested && ch.labels && gw > 30.0 {
                font(cr, family, 10.0);
                rgb(cr, 0xFFFFFF);
                let _ = gh;
            }
        }
    }
    cr.restore().ok();
}
