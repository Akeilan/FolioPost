//! Picture and shape effects: shadows (outer and inner), reflection, glow,
//! soft edges, bevel, and the picture's colour adjustments (brightness,
//! contrast, grayscale, black and white, washout, transparency, duotone),
//! read from DrawingML and drawn with cairo (blurs made on alpha masks).

use crate::xml::{NodeId, XmlDoc};
use std::collections::HashMap;

const EMU: f64 = 12700.0;

#[derive(Clone, Debug, PartialEq)]
pub struct Shadow {
    /// points
    pub blur: f64,
    pub dist: f64,
    /// degrees, clockwise from the right
    pub dir: f64,
    pub color: u32,
    pub alpha: f64,
    /// scale (1.0 = 100%)
    pub sx: f64,
    pub sy: f64,
    /// where scaling is anchored: "b", "ctr", "tl"...
    pub algn: String,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Reflection {
    pub blur: f64,
    pub start_alpha: f64,
    pub end_alpha: f64,
    /// how far down the picture the fade reaches (0..1)
    pub end_pos: f64,
    pub dist: f64,
}

#[derive(Clone, Debug, PartialEq, Default)]
pub struct Fx {
    pub outer: Option<Shadow>,
    pub inner: Option<Shadow>,
    /// radius (points), colour, opacity
    pub glow: Option<(f64, u32, f64)>,
    pub soft_edge: Option<f64>,
    pub reflection: Option<Reflection>,
    /// bevel width, height (points) and preset
    pub bevel: Option<(f64, f64, String)>,
    /// 3-D rotation: latitude, longitude, revolution (degrees)
    pub camera: Option<(f64, f64, f64)>,
    /// -1..1
    pub brightness: f64,
    pub contrast: f64,
    pub grayscale: bool,
    /// black and white at this threshold (0..1)
    pub bilevel: Option<f64>,
    /// the picture's opacity (1.0 opaque)
    pub opacity: f64,
    pub duotone: Option<(u32, u32)>,
}

impl Fx {
    pub fn is_empty(&self) -> bool {
        *self == Fx { opacity: 1.0, ..Default::default() }
    }

    /// Anything to do to the picture's own pixels?
    pub fn recolors(&self) -> bool {
        self.brightness != 0.0 || self.contrast != 0.0 || self.grayscale || self.bilevel.is_some()
            || self.opacity < 1.0 || self.duotone.is_some()
    }

    /// Room the effects take around a w x h picture: l, t, r, b (points).
    pub fn extents(&self, _w: f64, h: f64) -> [f64; 4] {
        let mut e = [0.0f64; 4];
        let mut grow = |l: f64, t: f64, r: f64, b: f64| {
            e[0] = e[0].max(l);
            e[1] = e[1].max(t);
            e[2] = e[2].max(r);
            e[3] = e[3].max(b);
        };
        if let Some(s) = &self.outer {
            let (dx, dy) = (s.dist * s.dir.to_radians().cos(), s.dist * s.dir.to_radians().sin());
            let b = s.blur;
            grow((b - dx).max(0.0), (b - dy).max(0.0), (b + dx).max(0.0), (b + dy).max(0.0));
        }
        if let Some((r, _, _)) = self.glow {
            grow(r, r, r, r);
        }
        if let Some(rf) = &self.reflection {
            grow(0.0, 0.0, 0.0, rf.dist + h * rf.end_pos + rf.blur);
        }
        e
    }
}

fn val(dom: &XmlDoc, n: NodeId, k: &str, d: f64) -> f64 {
    dom.attr(n, k).and_then(|v| v.parse::<f64>().ok()).unwrap_or(d)
}

/// The rotation a camera preset stands for (latitude, longitude, revolution).
pub fn camera_preset(prst: &str) -> Option<(f64, f64, f64)> {
    Some(match prst {
        "isometricLeftDown" => (35.0, 45.0, 0.0),
        "isometricRightUp" => (-35.0, -45.0, 0.0),
        "isometricTopUp" => (35.0, -45.0, 0.0),
        "isometricBottomDown" => (-35.0, 45.0, 0.0),
        "isometricOffAxis1Left" => (10.0, 64.0, 0.0),
        "isometricOffAxis1Right" => (10.0, -64.0, 0.0),
        "isometricOffAxis2Left" => (-10.0, 64.0, 0.0),
        "isometricOffAxis2Right" => (-10.0, -64.0, 0.0),
        "perspectiveLeft" => (0.0, 20.0, 0.0),
        "perspectiveRight" => (0.0, -20.0, 0.0),
        "perspectiveBelow" => (-20.0, 0.0, 0.0),
        "perspectiveAbove" => (20.0, 0.0, 0.0),
        "perspectiveRelaxed" => (30.0, 0.0, 0.0),
        "perspectiveContrastingLeftFacing" => (10.0, 40.0, 0.0),
        "perspectiveContrastingRightFacing" => (10.0, -40.0, 0.0),
        "obliqueTopLeft" => (20.0, 20.0, 0.0),
        "obliqueTopRight" => (20.0, -20.0, 0.0),
        "obliqueBottomLeft" => (-20.0, 20.0, 0.0),
        "obliqueBottomRight" => (-20.0, -20.0, 0.0),
        _ => return None,
    })
}

/// The flat picture of a 3-D rotation: x' = a x + c y, y' = b x + d y.
pub fn camera_matrix(lat: f64, lon: f64, rev: f64) -> (f64, f64, f64, f64) {
    let (la, lo, rv) = (lat.to_radians(), lon.to_radians(), rev.to_radians());
    // turn about the vertical axis (longitude), then tip (latitude), then spin
    let (a, b, c, d) = (lo.cos(), lo.sin() * la.sin(), 0.0, la.cos());
    let (cs, sn) = (rv.cos(), rv.sin());
    (cs * a - sn * b, sn * a + cs * b, cs * c - sn * d, sn * c + cs * d)
}

fn color_of(dom: &XmlDoc, n: NodeId, colors: &HashMap<String, u32>) -> (u32, f64) {
    dom.elements(n).find_map(|c| crate::shapes::color(dom, c, colors)).unwrap_or((0, 1.0))
}

fn shadow(dom: &XmlDoc, n: NodeId, colors: &HashMap<String, u32>) -> Shadow {
    let (color, alpha) = color_of(dom, n, colors);
    Shadow {
        blur: val(dom, n, "blurRad", 0.0) / EMU,
        dist: val(dom, n, "dist", 0.0) / EMU,
        dir: val(dom, n, "dir", 0.0) / 60000.0,
        color,
        alpha,
        sx: val(dom, n, "sx", 100000.0) / 100000.0,
        sy: val(dom, n, "sy", 100000.0) / 100000.0,
        algn: dom.attr(n, "algn").unwrap_or("b").to_string(),
    }
}

/// The effects of a picture or shape: its shape properties (a:effectLst,
/// a:sp3d) and its picture's a:blip.
pub fn parse(dom: &XmlDoc, sppr: Option<NodeId>, blip: Option<NodeId>, colors: &HashMap<String, u32>) -> Fx {
    let mut fx = Fx { opacity: 1.0, ..Default::default() };
    if let Some(sp) = sppr {
        if let Some(el) = dom.child(sp, "a:effectLst") {
            for c in dom.elements(el) {
                match dom.name(c) {
                    "a:outerShdw" => fx.outer = Some(shadow(dom, c, colors)),
                    "a:prstShdw" => {
                        let mut s = shadow(dom, c, colors);
                        if s.dist == 0.0 {
                            s.dist = 3.0;
                            s.dir = 45.0;
                        }
                        fx.outer = Some(s);
                    }
                    "a:innerShdw" => fx.inner = Some(shadow(dom, c, colors)),
                    "a:glow" => {
                        let (col, a) = color_of(dom, c, colors);
                        fx.glow = Some((val(dom, c, "rad", 0.0) / EMU, col, a));
                    }
                    "a:softEdge" => fx.soft_edge = Some(val(dom, c, "rad", 0.0) / EMU),
                    "a:reflection" => {
                        fx.reflection = Some(Reflection {
                            blur: val(dom, c, "blurRad", 0.0) / EMU,
                            start_alpha: val(dom, c, "stA", 100000.0) / 100000.0,
                            end_alpha: val(dom, c, "endA", 0.0) / 100000.0,
                            end_pos: val(dom, c, "endPos", 100000.0) / 100000.0,
                            dist: val(dom, c, "dist", 0.0) / EMU,
                        })
                    }
                    _ => {}
                }
            }
        }
        if let Some(cam) = dom.child(sp, "a:scene3d").and_then(|s| dom.child(s, "a:camera")) {
            let r = dom.child(cam, "a:rot").map(|r| (val(dom, r, "lat", 0.0) / 60000.0,
                                                     val(dom, r, "lon", 0.0) / 60000.0,
                                                     val(dom, r, "rev", 0.0) / 60000.0));
            let r = r.or_else(|| camera_preset(dom.attr(cam, "prst").unwrap_or("")));
            fx.camera = r.filter(|(a, b, c)| a.abs() + b.abs() + c.abs() > 0.01);
        }
        if let Some(b) = dom.child(sp, "a:sp3d").and_then(|s| dom.child(s, "a:bevelT")) {
            fx.bevel = Some((val(dom, b, "w", 76200.0) / EMU, val(dom, b, "h", 76200.0) / EMU,
                             dom.attr(b, "prst").unwrap_or("circle").to_string()));
        }
    }
    if let Some(bl) = blip {
        for c in dom.elements(bl) {
            match dom.name(c) {
                "a:lum" => {
                    fx.brightness = val(dom, c, "bright", 0.0) / 100000.0;
                    fx.contrast = val(dom, c, "contrast", 0.0) / 100000.0;
                }
                "a:grayscl" => fx.grayscale = true,
                "a:biLevel" => fx.bilevel = Some(val(dom, c, "thresh", 50000.0) / 100000.0),
                "a:alphaModFix" => fx.opacity = val(dom, c, "amt", 100000.0) / 100000.0,
                "a:duotone" => {
                    let cs: Vec<(u32, f64)> = dom.elements(c).filter_map(|k| crate::shapes::color(dom, k, colors)).collect();
                    if cs.len() == 2 {
                        fx.duotone = Some((cs[0].0, cs[1].0));
                    }
                }
                _ => {}
            }
        }
        // Word's brightness/contrast (Picture Corrections) live in an extension
        for e in dom.elements(bl) {
            if dom.is(e, "a:extLst") {
                for ext in dom.elements(e) {
                    for k in descendants(dom, ext) {
                        if dom.name(k).ends_with(":brightnessContrast") {
                            fx.brightness = val(dom, k, "bright", 0.0) / 100000.0;
                            fx.contrast = val(dom, k, "contrast", 0.0) / 100000.0;
                        }
                    }
                }
            }
        }
    }
    fx
}

fn descendants(dom: &XmlDoc, n: NodeId) -> Vec<NodeId> {
    let mut out = Vec::new();
    let mut stack = vec![n];
    while let Some(x) = stack.pop() {
        for c in dom.elements(x) {
            out.push(c);
            stack.push(c);
        }
    }
    out
}

// ------------------------------------------------------------- pixel work
/// Change a picture's pixels (ARGB32, premultiplied) as its colour
/// settings say.
pub fn recolor(s: &mut cairo::ImageSurface, fx: &Fx) {
    s.flush();
    let Ok(mut data) = s.data() else { return };
    let b = fx.brightness;
    let c = fx.contrast;
    // contrast as a slope about the middle grey
    let slope = if c >= 0.0 { 1.0 / (1.0 - c).max(0.01) } else { 1.0 + c };
    for px in data.chunks_exact_mut(4) {
        let a = px[3] as f64 / 255.0;
        if a <= 0.0 {
            continue;
        }
        // unpremultiply (little-endian ARGB32: B, G, R, A)
        let mut ch = [px[2] as f64 / 255.0 / a, px[1] as f64 / 255.0 / a, px[0] as f64 / 255.0 / a];
        for v in ch.iter_mut() {
            *v = ((*v - 0.5) * slope + 0.5 + b).clamp(0.0, 1.0);
        }
        let lum = 0.299 * ch[0] + 0.587 * ch[1] + 0.114 * ch[2];
        if fx.grayscale {
            ch = [lum, lum, lum];
        }
        if let Some(t) = fx.bilevel {
            let v = if lum >= t { 1.0 } else { 0.0 };
            ch = [v, v, v];
        }
        if let Some((d, l)) = fx.duotone {
            let mix = |k: u32| ((d >> k) & 255) as f64 / 255.0 * (1.0 - lum) + ((l >> k) & 255) as f64 / 255.0 * lum;
            ch = [mix(16), mix(8), mix(0)];
        }
        let na = a * fx.opacity;
        px[2] = (ch[0] * na * 255.0).round() as u8;
        px[1] = (ch[1] * na * 255.0).round() as u8;
        px[0] = (ch[2] * na * 255.0).round() as u8;
        px[3] = (na * 255.0).round() as u8;
    }
}

/// The alpha of `s` in an A8 surface `pad` pixels bigger on each side.
pub fn alpha_mask(s: &mut cairo::ImageSurface, pad: i32) -> Option<cairo::ImageSurface> {
    s.flush();
    let (w, h) = (s.width(), s.height());
    let mut m = cairo::ImageSurface::create(cairo::Format::A8, w + 2 * pad, h + 2 * pad).ok()?;
    let ms = m.stride() as usize;
    let ss = s.stride() as usize;
    {
        let src = s.data().ok()?;
        let mut dst = m.data().ok()?;
        for y in 0..h as usize {
            for x in 0..w as usize {
                dst[(y + pad as usize) * ms + x + pad as usize] = src[y * ss + x * 4 + 3];
            }
        }
    }
    m.mark_dirty();
    Some(m)
}

/// Blur an A8 surface (three box passes each way: close to a gaussian of
/// the given radius).
pub fn blur_a8(m: &mut cairo::ImageSurface, radius: f64) {
    let r = (radius / 2.0).round() as i32;
    if r <= 0 {
        return;
    }
    m.flush();
    let (w, h, st) = (m.width() as usize, m.height() as usize, m.stride() as usize);
    let Ok(mut data) = m.data() else { return };
    let mut buf: Vec<f32> = vec![0.0; w.max(h)];
    for _ in 0..3 {
        // rows
        for y in 0..h {
            let row = &mut data[y * st..y * st + w];
            box_pass(row.iter().map(|&v| v as f32).collect::<Vec<_>>().as_slice(), &mut buf[..w], r);
            for (d, v) in row.iter_mut().zip(&buf[..w]) {
                *d = v.round().clamp(0.0, 255.0) as u8;
            }
        }
        // columns
        let mut col: Vec<f32> = vec![0.0; h];
        for x in 0..w {
            for y in 0..h {
                col[y] = data[y * st + x] as f32;
            }
            box_pass(&col, &mut buf[..h], r);
            for y in 0..h {
                data[y * st + x] = buf[y].round().clamp(0.0, 255.0) as u8;
            }
        }
    }
}

fn box_pass(src: &[f32], dst: &mut [f32], r: i32) {
    let n = src.len() as i32;
    let win = (2 * r + 1) as f32;
    let mut sum: f32 = 0.0;
    for i in -r..=r {
        if i >= 0 && i < n {
            sum += src[i as usize];
        }
    }
    for i in 0..n {
        dst[i as usize] = sum / win;
        let out = i - r;
        let inn = i + r + 1;
        if out >= 0 {
            sum -= src[out as usize];
        }
        if inn < n {
            sum += src[inn as usize];
        }
    }
}

/// Scale every alpha value (clamped): glows are a blurred, strengthened
/// outline.
pub fn boost_a8(m: &mut cairo::ImageSurface, f: f64) {
    m.flush();
    if let Ok(mut d) = m.data() {
        for v in d.iter_mut() {
            *v = ((*v as f64) * f).min(255.0) as u8;
        }
    }
}

/// Multiply the alpha of `s` by a mask the same size (soft edges).
pub fn multiply_alpha(s: &mut cairo::ImageSurface, m: &mut cairo::ImageSurface) {
    s.flush();
    m.flush();
    let (w, h) = (s.width() as usize, s.height() as usize);
    let (ss, ms) = (s.stride() as usize, m.stride() as usize);
    let Ok(md) = m.data().map(|d| d.to_vec()) else { return };
    let Ok(mut sd) = s.data() else { return };
    for y in 0..h {
        for x in 0..w {
            let f = md[y * ms + x] as u32;
            let p = &mut sd[y * ss + x * 4..y * ss + x * 4 + 4];
            for c in p.iter_mut() {
                *c = ((*c as u32 * f + 127) / 255) as u8;
            }
        }
    }
}
