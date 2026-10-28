//! Drawn shapes: preset geometry, fill and outline (DrawingML and VML), and
//! drawing them with cairo.

use crate::xml::{NodeId, XmlDoc};
use std::collections::HashMap;

const EMU: f64 = 12700.0;

#[derive(Clone, Debug, PartialEq)]
pub struct Shape {
    /// preset geometry ("rect", "ellipse", "roundRect", "line"...)
    pub geom: String,
    /// fill colour and opacity
    pub fill: Option<(u32, f64)>,
    /// outline: width (points), colour, dash ("solid", "dash", "dot"...)
    pub line: Option<(f64, u32, String)>,
    /// adjust values (a:avLst gd "adj", "adj1"...) in 1/100000
    pub adj: Vec<f64>,
    /// arrowheads at the start and the end of a line
    pub ends: (bool, bool),
    /// a:custGeom paths (geom is "custom")
    pub custom: Vec<CustPath>,
}

/// One path of a custom geometry, in its own w x h coordinate space.
#[derive(Clone, Debug, PartialEq)]
pub struct CustPath {
    pub w: f64,
    pub h: f64,
    pub fill: bool,
    pub stroke: bool,
    pub cmds: Vec<Cmd>,
}

#[derive(Clone, Debug, PartialEq)]
pub enum Cmd {
    Move(f64, f64),
    Line(f64, f64),
    Cubic(f64, f64, f64, f64, f64, f64),
    Quad(f64, f64, f64, f64),
    /// wR, hR, start angle, swing angle (degrees)
    Arc(f64, f64, f64, f64),
    Close,
}

/// The paths of an a:custGeom (guides are not evaluated: plain numbers only).
pub fn parse_custom(dom: &XmlDoc, cg: NodeId) -> Vec<CustPath> {
    let mut out = Vec::new();
    let Some(pl) = dom.child(cg, "a:pathLst") else { return out };
    let n = |e: NodeId, k: &str| dom.attr(e, k).and_then(|v| v.parse::<f64>().ok()).unwrap_or(0.0);
    for p in dom.elements(pl) {
        if !dom.is(p, "a:path") {
            continue;
        }
        let mut cp = CustPath { w: n(p, "w"), h: n(p, "h"), fill: dom.attr(p, "fill") != Some("none"),
                                stroke: !matches!(dom.attr(p, "stroke"), Some("0") | Some("false")), cmds: Vec::new() };
        for c in dom.elements(p) {
            let pts: Vec<(f64, f64)> = dom.elements(c).filter(|k| dom.is(*k, "a:pt")).map(|k| (n(k, "x"), n(k, "y"))).collect();
            match dom.name(c) {
                "a:moveTo" if !pts.is_empty() => cp.cmds.push(Cmd::Move(pts[0].0, pts[0].1)),
                "a:lnTo" if !pts.is_empty() => cp.cmds.push(Cmd::Line(pts[0].0, pts[0].1)),
                "a:cubicBezTo" if pts.len() >= 3 => cp.cmds.push(Cmd::Cubic(pts[0].0, pts[0].1, pts[1].0, pts[1].1, pts[2].0, pts[2].1)),
                "a:quadBezTo" if pts.len() >= 2 => cp.cmds.push(Cmd::Quad(pts[0].0, pts[0].1, pts[1].0, pts[1].1)),
                "a:arcTo" => cp.cmds.push(Cmd::Arc(n(c, "wR"), n(c, "hR"), n(c, "stAng") / 60000.0, n(c, "swAng") / 60000.0)),
                "a:close" => cp.cmds.push(Cmd::Close),
                _ => {}
            }
        }
        out.push(cp);
    }
    out
}

/// An a:custGeom element for paths (each in its own coordinate space).
pub fn custom_xml(paths: &[CustPath]) -> String {
    let mut s = String::from("<a:custGeom><a:avLst/><a:gdLst/><a:ahLst/><a:cxnLst/><a:rect l=\"0\" t=\"0\" r=\"r\" b=\"b\"/><a:pathLst>");
    let pt = |x: f64, y: f64| format!("<a:pt x=\"{}\" y=\"{}\"/>", x.round() as i64, y.round() as i64);
    for p in paths {
        s.push_str(&format!("<a:path w=\"{}\" h=\"{}\"{}>", p.w.round() as i64, p.h.round() as i64,
                            if p.fill { "" } else { " fill=\"none\"" }));
        for c in &p.cmds {
            match *c {
                Cmd::Move(x, y) => s.push_str(&format!("<a:moveTo>{}</a:moveTo>", pt(x, y))),
                Cmd::Line(x, y) => s.push_str(&format!("<a:lnTo>{}</a:lnTo>", pt(x, y))),
                Cmd::Cubic(a, b, c2, d, e, f) => s.push_str(&format!("<a:cubicBezTo>{}{}{}</a:cubicBezTo>", pt(a, b), pt(c2, d), pt(e, f))),
                Cmd::Quad(a, b, c2, d) => s.push_str(&format!("<a:quadBezTo>{}{}</a:quadBezTo>", pt(a, b), pt(c2, d))),
                Cmd::Arc(wr, hr, st, sw) => s.push_str(&format!("<a:arcTo wR=\"{}\" hR=\"{}\" stAng=\"{}\" swAng=\"{}\"/>",
                    wr.round() as i64, hr.round() as i64, (st * 60000.0).round() as i64, (sw * 60000.0).round() as i64)),
                Cmd::Close => s.push_str("<a:close/>"),
            }
        }
        s.push_str("</a:path>");
    }
    s.push_str("</a:pathLst></a:custGeom>");
    s
}

fn custom_path(cr: &cairo::Context, paths: &[CustPath], w: f64, h: f64) -> bool {
    let mut closed = false;
    for p in paths {
        let sx = if p.w > 0.0 { w / p.w } else { 1.0 / 12700.0 };
        let sy = if p.h > 0.0 { h / p.h } else { 1.0 / 12700.0 };
        let (mut cx, mut cy) = (0.0, 0.0);
        let (mut startx, mut starty) = (0.0, 0.0);
        for c in &p.cmds {
            match *c {
                Cmd::Move(x, y) => {
                    cr.move_to(x * sx, y * sy);
                    (cx, cy, startx, starty) = (x, y, x, y);
                }
                Cmd::Line(x, y) => {
                    cr.line_to(x * sx, y * sy);
                    (cx, cy) = (x, y);
                }
                Cmd::Cubic(a, b, c2, d, e, f) => {
                    cr.curve_to(a * sx, b * sy, c2 * sx, d * sy, e * sx, f * sy);
                    (cx, cy) = (e, f);
                }
                Cmd::Quad(a, b, e, f) => {
                    let (x0, y0) = (cx, cy);
                    cr.curve_to((x0 + 2.0 * a) / 3.0 * sx, (y0 + 2.0 * b) / 3.0 * sy, (e + 2.0 * a) / 3.0 * sx,
                                (f + 2.0 * b) / 3.0 * sy, e * sx, f * sy);
                    (cx, cy) = (e, f);
                }
                Cmd::Arc(wr, hr, st, sw) => {
                    // the arc starts at the current point
                    let a0 = st.to_radians();
                    let ocx = cx - wr * a0.cos();
                    let ocy = cy - hr * a0.sin();
                    let a1 = (st + sw).to_radians();
                    cr.save().ok();
                    cr.translate(ocx * sx, ocy * sy);
                    cr.scale((wr * sx).max(1e-6), (hr * sy).max(1e-6));
                    if sw >= 0.0 { cr.arc(0.0, 0.0, 1.0, a0, a1) } else { cr.arc_negative(0.0, 0.0, 1.0, a0, a1) }
                    cr.restore().ok();
                    cx = ocx + wr * a1.cos();
                    cy = ocy + hr * a1.sin();
                }
                Cmd::Close => {
                    cr.close_path();
                    (cx, cy) = (startx, starty);
                    closed = true;
                }
            }
        }
        if p.fill {
            closed = true;
        }
    }
    closed
}

fn hsl(c: u32) -> (f64, f64, f64) {
    let r = ((c >> 16) & 255) as f64 / 255.0;
    let g = ((c >> 8) & 255) as f64 / 255.0;
    let b = (c & 255) as f64 / 255.0;
    let mx = r.max(g).max(b);
    let mn = r.min(g).min(b);
    let l = (mx + mn) / 2.0;
    if mx == mn {
        return (0.0, 0.0, l);
    }
    let d = mx - mn;
    let s = if l > 0.5 { d / (2.0 - mx - mn) } else { d / (mx + mn) };
    let h = if mx == r {
        (g - b) / d + if g < b { 6.0 } else { 0.0 }
    } else if mx == g {
        (b - r) / d + 2.0
    } else {
        (r - g) / d + 4.0
    } / 6.0;
    (h, s, l)
}

fn from_hsl(h: f64, s: f64, l: f64) -> u32 {
    let to = |v: f64| (v.clamp(0.0, 1.0) * 255.0).round() as u32;
    if s == 0.0 {
        let v = to(l);
        return (v << 16) | (v << 8) | v;
    }
    let q = if l < 0.5 { l * (1.0 + s) } else { l + s - l * s };
    let p = 2.0 * l - q;
    let f = |mut t: f64| {
        if t < 0.0 {
            t += 1.0;
        }
        if t > 1.0 {
            t -= 1.0;
        }
        if t < 1.0 / 6.0 {
            p + (q - p) * 6.0 * t
        } else if t < 0.5 {
            q
        } else if t < 2.0 / 3.0 {
            p + (q - p) * (2.0 / 3.0 - t) * 6.0
        } else {
            p
        }
    };
    (to(f(h + 1.0 / 3.0)) << 16) | (to(f(h)) << 8) | to(f(h - 1.0 / 3.0))
}

fn preset(name: &str) -> Option<u32> {
    Some(match name {
        "black" => 0x000000,
        "white" => 0xFFFFFF,
        "red" => 0xFF0000,
        "green" => 0x008000,
        "blue" => 0x0000FF,
        "yellow" => 0xFFFF00,
        "gray" | "grey" => 0x808080,
        "darkGray" => 0xA9A9A9,
        "lightGray" => 0xD3D3D3,
        "orange" => 0xFFA500,
        "cyan" => 0x00FFFF,
        "magenta" => 0xFF00FF,
        _ => return None,
    })
}

/// The colour of a colour element (a:srgbClr, a:schemeClr, a:prstClr,
/// a:sysClr, a:scrgbClr) with its modifiers, and its opacity.
pub fn color(dom: &XmlDoc, c: NodeId, colors: &HashMap<String, u32>) -> Option<(u32, f64)> {
    let val = dom.attr(c, "val").unwrap_or("");
    let mut rgb = match dom.name(c) {
        "a:srgbClr" => u32::from_str_radix(val, 16).ok()?,
        "a:schemeClr" => {
            let key = match val {
                "tx1" | "dk1" => "dk1",
                "bg1" | "lt1" => "lt1",
                "tx2" | "dk2" => "dk2",
                "bg2" | "lt2" => "lt2",
                "phClr" => "accent1",
                v => v,
            };
            *colors.get(key).or_else(|| match key {
                "dk1" => Some(&0),
                "lt1" => Some(&0xFFFFFF),
                "accent1" => Some(&0x4472C4),
                "accent2" => Some(&0xED7D31),
                "accent3" => Some(&0xA5A5A5),
                "accent4" => Some(&0xFFC000),
                "accent5" => Some(&0x5B9BD5),
                "accent6" => Some(&0x70AD47),
                "dk2" => Some(&0x44546A),
                "lt2" => Some(&0xE7E6E6),
                _ => None,
            })?
        }
        "a:prstClr" => preset(val)?,
        "a:sysClr" => dom.attr(c, "lastClr").and_then(|v| u32::from_str_radix(v, 16).ok())
            .unwrap_or(if val == "window" { 0xFFFFFF } else { 0 }),
        "a:scrgbClr" => {
            let g = |k: &str| (dom.attr(c, k).and_then(|v| v.parse::<f64>().ok()).unwrap_or(0.0) / 100000.0)
                .clamp(0.0, 1.0);
            let to = |v: f64| (v.powf(1.0 / 2.2) * 255.0).round() as u32;
            (to(g("r")) << 16) | (to(g("g")) << 8) | to(g("b"))
        }
        _ => return None,
    };
    let mut alpha = 1.0;
    for m in dom.elements(c) {
        let v = dom.attr(m, "val").and_then(|v| v.parse::<f64>().ok()).unwrap_or(0.0) / 100000.0;
        match dom.name(m) {
            "a:lumMod" => {
                let (h, s, l) = hsl(rgb);
                rgb = from_hsl(h, s, l * v);
            }
            "a:lumOff" => {
                let (h, s, l) = hsl(rgb);
                rgb = from_hsl(h, s, l + v);
            }
            "a:tint" => {
                let f = |x: u32| (x as f64 + (255.0 - x as f64) * (1.0 - v)).round() as u32;
                rgb = (f((rgb >> 16) & 255) << 16) | (f((rgb >> 8) & 255) << 8) | f(rgb & 255);
            }
            "a:shade" => {
                let f = |x: u32| (x as f64 * v).round() as u32;
                rgb = (f((rgb >> 16) & 255) << 16) | (f((rgb >> 8) & 255) << 8) | f(rgb & 255);
            }
            "a:alpha" => alpha = v,
            _ => {}
        }
    }
    Some((rgb & 0xFFFFFF, alpha))
}

/// The colour inside a fill-like element (a:solidFill, a:fillRef...).
fn color_in(dom: &XmlDoc, n: NodeId, colors: &HashMap<String, u32>) -> Option<(u32, f64)> {
    dom.elements(n).find_map(|c| color(dom, c, colors))
}

/// An outline (a:ln): width, colour, dash. None for no line.
pub fn line_of(dom: &XmlDoc, ln: NodeId, colors: &HashMap<String, u32>) -> Option<(f64, u32, String)> {
    if dom.child(ln, "a:noFill").is_some() {
        return None;
    }
    let (c, _) = dom.child(ln, "a:solidFill").and_then(|f| color_in(dom, f, colors))?;
    let w = dom.attr(ln, "w").and_then(|v| v.parse::<f64>().ok()).unwrap_or(9525.0) / EMU;
    let dash = dom.child(ln, "a:prstDash").and_then(|d| dom.attr(d, "val")).unwrap_or("solid").to_string();
    Some((w, c, dash))
}

impl Shape {
    /// A wps:wsp shape.
    /// A picture's spPr (geometry and outline), as a shape.
    pub fn parse_sppr(dom: &XmlDoc, sp: NodeId, colors: &HashMap<String, u32>) -> Shape {
        Self::parse_parts(dom, Some(sp), None, colors)
    }

    pub fn parse(dom: &XmlDoc, wsp: NodeId, colors: &HashMap<String, u32>) -> Shape {
        let sp = dom.child(wsp, "wps:spPr");
        let style = dom.child(wsp, "wps:style");
        Self::parse_parts(dom, sp, style, colors)
    }

    fn parse_parts(dom: &XmlDoc, sp: Option<NodeId>, style: Option<NodeId>, colors: &HashMap<String, u32>) -> Shape {
        let mut sh = Shape { geom: "rect".into(), fill: None, line: None, adj: Vec::new(), ends: (false, false), custom: Vec::new() };
        let mut fill_set = false;
        let mut line_set = false;
        if let Some(sp) = sp {
            if let Some(g) = dom.child(sp, "a:prstGeom") {
                sh.geom = dom.attr(g, "prst").unwrap_or("rect").to_string();
                if let Some(av) = dom.child(g, "a:avLst") {
                    for gd in dom.elements(av) {
                        let f = dom.attr(gd, "fmla").unwrap_or("");
                        if let Some(v) = f.strip_prefix("val ").and_then(|v| v.trim().parse::<f64>().ok()) {
                            sh.adj.push(v);
                        }
                    }
                }
            } else if let Some(cg) = dom.child(sp, "a:custGeom") {
                sh.custom = parse_custom(dom, cg);
                sh.geom = if sh.custom.is_empty() { "rect".into() } else { "custom".into() };
            }
            if dom.child(sp, "a:noFill").is_some() {
                fill_set = true;
            } else if let Some(f) = dom.child(sp, "a:solidFill") {
                sh.fill = color_in(dom, f, colors);
                fill_set = true;
            } else if let Some(f) = dom.child(sp, "a:gradFill") {
                // a gradient: its first stop
                sh.fill = crate::pictures::find(dom, f, "a:gs").and_then(|gs| color_in(dom, gs, colors));
                fill_set = true;
            } else if dom.child(sp, "a:blipFill").is_some() || dom.child(sp, "a:pattFill").is_some() {
                sh.fill = Some((0xD9D9D9, 1.0));
                fill_set = true;
            }
            if let Some(ln) = dom.child(sp, "a:ln") {
                let arrow = |name: &str| dom.child(ln, name).and_then(|e| dom.attr(e, "type")).is_some_and(|t| t != "none");
                sh.ends = (arrow("a:headEnd"), arrow("a:tailEnd"));
                if dom.child(ln, "a:noFill").is_some() {
                    line_set = true;
                } else if dom.child(ln, "a:solidFill").is_some() {
                    sh.line = line_of(dom, ln, colors);
                    line_set = true;
                } else if let (Some(st), Some(w)) = (style, dom.attr(ln, "w")) {
                    // width here, colour from the style
                    if let Some(lr) = dom.child(st, "a:lnRef") {
                        if let Some((c, _)) = color_in(dom, lr, colors) {
                            sh.line = Some((w.parse::<f64>().unwrap_or(9525.0) / EMU, c, "solid".into()));
                            line_set = true;
                        }
                    }
                }
            }
        }
        if let Some(st) = style {
            if !fill_set {
                if let Some(fr) = dom.child(st, "a:fillRef") {
                    if dom.attr(fr, "idx").unwrap_or("0") != "0" {
                        sh.fill = color_in(dom, fr, colors);
                    }
                }
            }
            if !line_set {
                if let Some(lr) = dom.child(st, "a:lnRef") {
                    let idx: f64 = dom.attr(lr, "idx").and_then(|v| v.parse().ok()).unwrap_or(0.0);
                    if idx > 0.0 {
                        if let Some((c, _)) = color_in(dom, lr, colors) {
                            sh.line = Some((0.5 * idx, c, "solid".into()));
                        }
                    }
                }
            }
        }
        sh
    }

    /// A VML shape element.
    pub fn parse_vml(dom: &XmlDoc, el: NodeId) -> Shape {
        let geom = match dom.name(el) {
            "v:oval" => "ellipse",
            "v:roundrect" => "roundRect",
            "v:line" => "line",
            _ => "rect",
        };
        let col = |v: &str| -> Option<u32> {
            let v = v.split_whitespace().next().unwrap_or("");
            if let Some(h) = v.strip_prefix('#') {
                if h.len() == 3 {
                    let x = u32::from_str_radix(h, 16).ok()?;
                    let (r, g, b) = ((x >> 8) & 15, (x >> 4) & 15, x & 15);
                    return Some((r * 17) << 16 | (g * 17) << 8 | b * 17);
                }
                return u32::from_str_radix(h, 16).ok();
            }
            preset(v).or(match v {
                "silver" => Some(0xC0C0C0),
                "navy" => Some(0x000080),
                "maroon" => Some(0x800000),
                "lime" => Some(0x00FF00),
                "aqua" => Some(0x00FFFF),
                "fuchsia" => Some(0xFF00FF),
                "olive" => Some(0x808000),
                "purple" => Some(0x800080),
                "teal" => Some(0x008080),
                _ => None,
            })
        };
        let filled = dom.attr(el, "filled").map(|v| !(v == "f" || v == "false")).unwrap_or(true);
        let stroked = dom.attr(el, "stroked").map(|v| !(v == "f" || v == "false")).unwrap_or(true);
        let fill_el = dom.child(el, "v:fill");
        let fill_on = fill_el.and_then(|f| dom.attr(f, "on")).map(|v| !(v == "f" || v == "false")).unwrap_or(filled);
        let fill = if fill_on && geom != "line" {
            let c = dom.attr(el, "fillcolor").and_then(col).unwrap_or(0xFFFFFF);
            let a = fill_el.and_then(|f| dom.attr(f, "opacity")).and_then(|v| {
                if let Some(x) = v.strip_suffix('f') {
                    x.parse::<f64>().ok().map(|x| x / 65536.0)
                } else {
                    v.parse().ok()
                }
            }).unwrap_or(1.0);
            Some((c, a))
        } else {
            None
        };
        let stroke_el = dom.child(el, "v:stroke");
        let stroke_on = stroke_el.and_then(|f| dom.attr(f, "on")).map(|v| !(v == "f" || v == "false")).unwrap_or(stroked);
        let line = if stroke_on {
            let c = dom.attr(el, "strokecolor").and_then(col).unwrap_or(0);
            let w = dom.attr(el, "strokeweight").and_then(crate::pictures::css_len).unwrap_or(0.75);
            let dash = stroke_el.and_then(|s| dom.attr(s, "dashstyle")).unwrap_or("solid").to_string();
            Some((w, c, dash))
        } else {
            None
        };
        Shape { geom: geom.into(), fill, line, adj: Vec::new(), ends: (false, false), custom: Vec::new() }
    }

    /// Trace the outline in a w x h box at the origin.
    /// The shape's outline as the current path (to clip a picture to it).
    pub fn outline(&self, cr: &cairo::Context, w: f64, h: f64) -> bool {
        self.path(cr, w, h)
    }

    /// The outline flattened to polygons (points in the w x h box).
    pub fn polygons(&self, w: f64, h: f64) -> Vec<Vec<(f64, f64)>> {
        let Ok(surf) = cairo::ImageSurface::create(cairo::Format::A8, 1, 1) else { return Vec::new() };
        let Ok(cr) = cairo::Context::new(&surf) else { return Vec::new() };
        cr.set_tolerance(0.05);
        self.path(&cr, w, h);
        let mut out: Vec<Vec<(f64, f64)>> = Vec::new();
        let Ok(path) = cr.copy_path_flat() else { return out };
        let mut cur: Vec<(f64, f64)> = Vec::new();
        for seg in path.iter() {
            match seg {
                cairo::PathSegment::MoveTo((x, y)) => {
                    if cur.len() > 2 {
                        out.push(std::mem::take(&mut cur));
                    }
                    cur = vec![(x, y)];
                }
                cairo::PathSegment::LineTo((x, y)) => cur.push((x, y)),
                cairo::PathSegment::ClosePath => {
                    if cur.len() > 2 {
                        out.push(std::mem::take(&mut cur));
                    }
                }
                _ => {}
            }
        }
        if cur.len() > 2 {
            out.push(cur);
        }
        out
    }

    fn path(&self, cr: &cairo::Context, w: f64, h: f64) -> bool {
        if self.geom == "custom" {
            return custom_path(cr, &self.custom, w, h);
        }
        let adj = |i: usize, d: f64| self.adj.get(i).copied().unwrap_or(d) / 100000.0;
        let ss = w.min(h);
        let poly = |pts: &[(f64, f64)]| {
            for (i, (x, y)) in pts.iter().enumerate() {
                if i == 0 {
                    cr.move_to(*x, *y);
                } else {
                    cr.line_to(*x, *y);
                }
            }
            cr.close_path();
        };
        match self.geom.as_str() {
            "ellipse" | "flowChartConnector" => {
                cr.save().ok();
                cr.translate(w / 2.0, h / 2.0);
                cr.scale((w / 2.0).max(1e-6), (h / 2.0).max(1e-6));
                cr.arc(0.0, 0.0, 1.0, 0.0, std::f64::consts::TAU);
                cr.restore().ok();
            }
            "roundRect" | "flowChartAlternateProcess" => {
                let r = ss * adj(0, 16667.0);
                cr.new_sub_path();
                cr.arc(w - r, r, r, -std::f64::consts::FRAC_PI_2, 0.0);
                cr.arc(w - r, h - r, r, 0.0, std::f64::consts::FRAC_PI_2);
                cr.arc(r, h - r, r, std::f64::consts::FRAC_PI_2, std::f64::consts::PI);
                cr.arc(r, r, r, std::f64::consts::PI, 1.5 * std::f64::consts::PI);
                cr.close_path();
            }
            "line" | "straightConnector1" => {
                cr.move_to(0.0, 0.0);
                cr.line_to(w, h);
                return false;
            }
            "bentConnector2" => {
                cr.move_to(0.0, 0.0);
                cr.line_to(w, 0.0);
                cr.line_to(w, h);
                return false;
            }
            "bentConnector3" => {
                let x1 = w * adj(0, 50000.0);
                cr.move_to(0.0, 0.0);
                cr.line_to(x1, 0.0);
                cr.line_to(x1, h);
                cr.line_to(w, h);
                return false;
            }
            "curvedConnector3" => {
                let x1 = w * adj(0, 50000.0);
                cr.move_to(0.0, 0.0);
                cr.curve_to(x1, 0.0, x1, h, w, h);
                return false;
            }
            "triangle" | "flowChartExtract" => poly(&[(w * adj(0, 50000.0), 0.0), (w, h), (0.0, h)]),
            "rtTriangle" => poly(&[(0.0, 0.0), (w, h), (0.0, h)]),
            "diamond" | "flowChartDecision" => poly(&[(w / 2.0, 0.0), (w, h / 2.0), (w / 2.0, h), (0.0, h / 2.0)]),
            "parallelogram" | "flowChartInputOutput" => {
                let a = ss * adj(0, 25000.0);
                poly(&[(a, 0.0), (w, 0.0), (w - a, h), (0.0, h)])
            }
            "trapezoid" => {
                let a = ss * adj(0, 25000.0);
                poly(&[(0.0, h), (a, 0.0), (w - a, 0.0), (w, h)])
            }
            "hexagon" => {
                let a = ss * adj(0, 25000.0);
                poly(&[(0.0, h / 2.0), (a, 0.0), (w - a, 0.0), (w, h / 2.0), (w - a, h), (a, h)])
            }
            "octagon" => {
                let a = ss * adj(0, 29289.0);
                poly(&[(a, 0.0), (w - a, 0.0), (w, a), (w, h - a), (w - a, h), (a, h), (0.0, h - a), (0.0, a)])
            }
            "pentagon" | "homePlate" => {
                if self.geom == "homePlate" {
                    let a = ss * adj(0, 50000.0);
                    poly(&[(0.0, 0.0), (w - a, 0.0), (w, h / 2.0), (w - a, h), (0.0, h)])
                } else {
                    poly(&[(w / 2.0, 0.0), (w, h * 0.382), (w * 0.809, h), (w * 0.191, h), (0.0, h * 0.382)])
                }
            }
            "chevron" => {
                let a = ss * adj(0, 50000.0);
                poly(&[(0.0, 0.0), (w - a, 0.0), (w, h / 2.0), (w - a, h), (0.0, h), (a, h / 2.0)])
            }
            "rightArrow" | "leftArrow" => {
                let a1 = adj(0, 50000.0);
                let hd = ss * adj(1, 50000.0);
                let (t, b) = (h / 2.0 - h * a1 / 2.0, h / 2.0 + h * a1 / 2.0);
                let pts = [(0.0, t), (w - hd, t), (w - hd, 0.0), (w, h / 2.0), (w - hd, h), (w - hd, b), (0.0, b)];
                if self.geom == "leftArrow" {
                    let m: Vec<(f64, f64)> = pts.iter().map(|(x, y)| (w - x, *y)).collect();
                    poly(&m);
                } else {
                    poly(&pts);
                }
            }
            "upArrow" | "downArrow" => {
                let a1 = adj(0, 50000.0);
                let hd = ss * adj(1, 50000.0);
                let (l, r) = (w / 2.0 - w * a1 / 2.0, w / 2.0 + w * a1 / 2.0);
                let pts = [(l, h), (l, hd), (0.0, hd), (w / 2.0, 0.0), (w, hd), (r, hd), (r, h)];
                if self.geom == "downArrow" {
                    let m: Vec<(f64, f64)> = pts.iter().map(|(x, y)| (*x, h - y)).collect();
                    poly(&m);
                } else {
                    poly(&pts);
                }
            }
            "star5" | "star4" | "star6" | "star8" => {
                let n: usize = self.geom[4..].parse().unwrap_or(5);
                let inner = match n {
                    4 => 0.38,
                    5 => 0.38,
                    6 => 0.58,
                    _ => 0.7,
                };
                let mut pts = Vec::new();
                for i in 0..n * 2 {
                    let a = -std::f64::consts::FRAC_PI_2 + i as f64 * std::f64::consts::PI / n as f64;
                    let r = if i % 2 == 0 { 1.0 } else { inner };
                    pts.push((w / 2.0 + a.cos() * r * w / 2.0, h / 2.0 + a.sin() * r * h / 2.0));
                }
                poly(&pts);
            }
            "plus" | "flowChartPredefinedProcess" if self.geom == "plus" => {
                let a = ss * adj(0, 25000.0);
                poly(&[(a, 0.0), (w - a, 0.0), (w - a, a), (w, a), (w, h - a), (w - a, h - a), (w - a, h), (a, h),
                       (a, h - a), (0.0, h - a), (0.0, a), (a, a)])
            }
            "frame" => {
                let a = ss * adj(0, 12500.0);
                cr.rectangle(0.0, 0.0, w, h);
                cr.new_sub_path();
                cr.move_to(a, a);
                cr.line_to(a, h - a);
                cr.line_to(w - a, h - a);
                cr.line_to(w - a, a);
                cr.close_path();
            }
            "donut" => {
                let a = ss * adj(0, 25000.0);
                ellipse(cr, w / 2.0, h / 2.0, w / 2.0, h / 2.0, false);
                ellipse(cr, w / 2.0, h / 2.0, (w / 2.0 - a).max(0.5), (h / 2.0 - a).max(0.5), true);
            }
            "cube" => {
                let a = ss * adj(0, 25000.0);
                poly(&[(0.0, a), (a, 0.0), (w, 0.0), (w, h - a), (w - a, h), (0.0, h)]);
                cr.move_to(0.0, a);
                cr.line_to(w - a, a);
                cr.line_to(w, 0.0);
                cr.move_to(w - a, a);
                cr.line_to(w - a, h);
            }
            "can" | "flowChartMagneticDisk" => {
                let a = (ss * adj(0, 25000.0)).min(h / 2.0);
                let ry = a / 2.0;
                cr.move_to(0.0, ry);
                elliptic_arc(cr, w / 2.0, ry, w / 2.0, ry, std::f64::consts::PI, std::f64::consts::TAU);
                cr.line_to(w, h - ry);
                elliptic_arc(cr, w / 2.0, h - ry, w / 2.0, ry, 0.0, std::f64::consts::PI);
                cr.close_path();
                cr.new_sub_path();
                cr.move_to(w, ry);
                elliptic_arc(cr, w / 2.0, ry, w / 2.0, ry, 0.0, std::f64::consts::PI);
            }
            "heart" => {
                cr.move_to(w / 2.0, h * 0.25);
                cr.curve_to(w * 0.5, h * -0.1, w * -0.15, h * 0.05, w * 0.05, h * 0.42);
                cr.curve_to(w * 0.15, h * 0.62, w * 0.42, h * 0.8, w / 2.0, h);
                cr.curve_to(w * 0.58, h * 0.8, w * 0.85, h * 0.62, w * 0.95, h * 0.42);
                cr.curve_to(w * 1.15, h * 0.05, w * 0.5, h * -0.1, w / 2.0, h * 0.25);
                cr.close_path();
            }
            "mathPlus" => {
                let t = ss * adj(0, 23520.0) / 2.0;
                let (ex, ey) = (w * 0.3675, h * 0.3675);
                let (cx, cy) = (w / 2.0, h / 2.0);
                poly(&[(cx - t, cy - ey), (cx + t, cy - ey), (cx + t, cy - t), (cx + ex, cy - t), (cx + ex, cy + t),
                       (cx + t, cy + t), (cx + t, cy + ey), (cx - t, cy + ey), (cx - t, cy + t), (cx - ex, cy + t),
                       (cx - ex, cy - t), (cx - t, cy - t)]);
            }
            "mathMinus" => {
                let t = h * adj(0, 23520.0) / 2.0;
                cr.rectangle(w * 0.1325, h / 2.0 - t, w * 0.735, 2.0 * t);
            }
            "mathMultiply" => {
                let t = ss * adj(0, 23520.0) / 2.0;
                let (cx, cy) = (w / 2.0, h / 2.0);
                let (ex, ey) = (w * 0.34, h * 0.34);
                // two crossing bars
                for sgn in [1.0, -1.0] {
                    let (dx, dy) = (ex, sgn * ey);
                    let l = (dx * dx + dy * dy).sqrt().max(0.01);
                    let (nx, ny) = (-dy / l * t, dx / l * t);
                    poly(&[(cx - dx + nx, cy - dy + ny), (cx + dx + nx, cy + dy + ny),
                           (cx + dx - nx, cy + dy - ny), (cx - dx - nx, cy - dy - ny)]);
                    cr.new_sub_path();
                }
            }
            "mathDivide" => {
                let t = h * adj(0, 23520.0) / 2.0;
                let gap = h * adj(1, 5880.0);
                let r = h * adj(2, 11760.0) / 2.0;
                cr.rectangle(w * 0.1325, h / 2.0 - t, w * 0.735, 2.0 * t);
                cr.new_sub_path();
                ellipse(cr, w / 2.0, h / 2.0 - t - gap - r, r, r, false);
                cr.new_sub_path();
                ellipse(cr, w / 2.0, h / 2.0 + t + gap + r, r, r, false);
            }
            "mathEqual" | "mathNotEqual" => {
                let t = h * adj(0, 23520.0);
                let gap = h * adj(if self.geom == "mathEqual" { 1 } else { 2 }, 11760.0);
                cr.rectangle(w * 0.1325, h / 2.0 - gap / 2.0 - t, w * 0.735, t);
                cr.rectangle(w * 0.1325, h / 2.0 + gap / 2.0, w * 0.735, t);
                if self.geom == "mathNotEqual" {
                    let (cx, cy, ht) = (w / 2.0, h / 2.0, h * 0.4);
                    let dx = ht * 0.36;
                    let k = t / 2.0;
                    cr.new_sub_path();
                    poly(&[(cx + dx - k, cy - ht), (cx + dx + k, cy - ht), (cx - dx + k, cy + ht), (cx - dx - k, cy + ht)]);
                }
            }
            "lightningBolt" => poly(&[(w * 0.39, 0.0), (w * 0.62, h * 0.29), (w * 0.53, h * 0.34), (w * 0.82, h * 0.6),
                                      (w * 0.72, h * 0.64), (w, h), (w * 0.47, h * 0.72), (w * 0.57, h * 0.67),
                                      (w * 0.2, h * 0.42), (w * 0.33, h * 0.36), (0.0, h * 0.17)]),
            "sun" => {
                let r = ss * 0.25;
                ellipse(cr, w / 2.0, h / 2.0, w * 0.25, h * 0.25, false);
                for i in 0..8 {
                    let a = i as f64 * std::f64::consts::FRAC_PI_4;
                    let (c, s_) = (a.cos(), a.sin());
                    let (px, py) = (-s_, c);
                    let (r0, r1) = (0.34, 0.5);
                    cr.new_sub_path();
                    cr.move_to(w / 2.0 + c * w * r1, h / 2.0 + s_ * h * r1);
                    cr.line_to(w / 2.0 + c * w * r0 + px * r * 0.25, h / 2.0 + s_ * h * r0 + py * r * 0.25);
                    cr.line_to(w / 2.0 + c * w * r0 - px * r * 0.25, h / 2.0 + s_ * h * r0 - py * r * 0.25);
                    cr.close_path();
                }
            }
            "moon" => {
                let a = w * adj(0, 50000.0);
                cr.move_to(w, 0.0);
                cr.curve_to(w * -0.33, 0.0, w * -0.33, h, w, h);
                cr.curve_to(a - w * 0.1, h * 0.85, a - w * 0.1, h * 0.15, w, 0.0);
                cr.close_path();
            }
            "smileyFace" => {
                ellipse(cr, w / 2.0, h / 2.0, w / 2.0, h / 2.0, false);
                ellipse(cr, w * 0.35, h * 0.38, w * 0.05, h * 0.05, true);
                ellipse(cr, w * 0.65, h * 0.38, w * 0.05, h * 0.05, true);
                cr.move_to(w * 0.25, h * 0.66);
                cr.curve_to(w * 0.4, h * 0.82, w * 0.6, h * 0.82, w * 0.75, h * 0.66);
            }
            "cloud" | "cloudCallout" => {
                let bumps = [(0.22, 0.32, 0.2, 0.2), (0.45, 0.2, 0.24, 0.2), (0.72, 0.26, 0.22, 0.2), (0.82, 0.55, 0.18, 0.2),
                             (0.62, 0.74, 0.22, 0.2), (0.35, 0.74, 0.22, 0.2), (0.15, 0.56, 0.16, 0.18)];
                for (cx, cy, rx, ry) in bumps {
                    ellipse(cr, w * cx, h * cy, w * rx, h * ry, false);
                }
                if self.geom == "cloudCallout" {
                    for (cx, cy, r) in [(0.18, 0.92, 0.05), (0.08, 1.02, 0.03)] {
                        ellipse(cr, w * cx, h * cy, w * r, h * r, false);
                    }
                }
            }
            "leftRightArrow" => {
                let a1 = adj(0, 50000.0);
                let hd = (ss * adj(1, 50000.0)).min(w / 2.0);
                let (t, b) = (h / 2.0 - h * a1 / 2.0, h / 2.0 + h * a1 / 2.0);
                poly(&[(0.0, h / 2.0), (hd, 0.0), (hd, t), (w - hd, t), (w - hd, 0.0), (w, h / 2.0), (w - hd, h),
                       (w - hd, b), (hd, b), (hd, h)]);
            }
            "upDownArrow" => {
                let a1 = adj(0, 50000.0);
                let hd = (ss * adj(1, 50000.0)).min(h / 2.0);
                let (l, r) = (w / 2.0 - w * a1 / 2.0, w / 2.0 + w * a1 / 2.0);
                poly(&[(w / 2.0, 0.0), (w, hd), (r, hd), (r, h - hd), (w, h - hd), (w / 2.0, h), (0.0, h - hd),
                       (l, h - hd), (l, hd), (0.0, hd)]);
            }
            "notchedRightArrow" => {
                let a1 = adj(0, 50000.0);
                let hd = ss * adj(1, 50000.0);
                let (t, b) = (h / 2.0 - h * a1 / 2.0, h / 2.0 + h * a1 / 2.0);
                let notch = hd * (h * a1 / 2.0) / (h / 2.0);
                poly(&[(0.0, t), (w - hd, t), (w - hd, 0.0), (w, h / 2.0), (w - hd, h), (w - hd, b), (0.0, b),
                       (notch, h / 2.0)]);
            }
            "circularArrow" => {
                let th = ss * 0.125;
                let (cx, cy) = (w / 2.0, h / 2.0);
                let (rx, ry) = (w / 2.0 - th * 1.5, h / 2.0 - th * 1.5);
                let a0 = std::f64::consts::PI * 1.05;
                let a1 = std::f64::consts::PI * 1.95;
                cr.save().ok();
                cr.translate(cx, cy);
                cr.scale(1.0, ry / rx.max(1e-6));
                cr.arc(0.0, 0.0, rx + th / 2.0, a0, a1);
                cr.arc_negative(0.0, 0.0, (rx - th / 2.0).max(0.5), a1, a0);
                cr.close_path();
                cr.restore().ok();
                let (ex, ey) = (cx + a1.cos() * rx, cy + a1.sin() * ry);
                poly(&[(ex - th * 1.5, ey), (ex + th * 1.5, ey), (ex, ey + th * 1.6)]);
            }
            "flowChartTerminator" => {
                let r = (h / 2.0).min(w / 2.0);
                cr.new_sub_path();
                cr.arc(w - r, h / 2.0, r, -std::f64::consts::FRAC_PI_2, std::f64::consts::FRAC_PI_2);
                cr.arc(r, h / 2.0, r, std::f64::consts::FRAC_PI_2, 1.5 * std::f64::consts::PI);
                cr.close_path();
            }
            "flowChartDocument" => {
                cr.move_to(0.0, 0.0);
                cr.line_to(w, 0.0);
                cr.line_to(w, h * 0.83);
                cr.curve_to(w * 0.75, h * 0.7, w * 0.5, h * 0.85, w * 0.35, h * 0.95);
                cr.curve_to(w * 0.2, h * 1.03, w * 0.08, h * 0.95, 0.0, h * 0.9);
                cr.close_path();
            }
            "star24" | "star7" | "star10" | "star12" | "star16" | "star32" => {
                let n: usize = self.geom[4..].parse().unwrap_or(24);
                let inner = if n >= 16 { 0.8 } else { 0.62 };
                let mut pts = Vec::new();
                for i in 0..n * 2 {
                    let a = -std::f64::consts::FRAC_PI_2 + i as f64 * std::f64::consts::PI / n as f64;
                    let r = if i % 2 == 0 { 1.0 } else { inner };
                    pts.push((w / 2.0 + a.cos() * r * w / 2.0, h / 2.0 + a.sin() * r * h / 2.0));
                }
                poly(&pts);
            }
            "horizontalScroll" => {
                let a = ss * adj(0, 12500.0);
                cr.move_to(a, a);
                cr.line_to(w - a, a);
                cr.line_to(w - a, a / 2.0);
                cr.arc(w - a / 2.0, a / 2.0, a / 2.0, std::f64::consts::PI, 0.0);
                cr.line_to(w, h - a);
                cr.line_to(a, h - a);
                cr.line_to(a, h - a / 2.0);
                cr.arc(a / 2.0, h - a / 2.0, a / 2.0, 0.0, std::f64::consts::PI);
                cr.line_to(0.0, a + a / 2.0);
                cr.arc(a / 2.0, a + a / 2.0, a / 2.0, std::f64::consts::PI, 1.5 * std::f64::consts::PI);
                cr.close_path();
            }
            "wedgeRectCallout" | "wedgeRoundRectCallout" | "wedgeEllipseCallout" => {
                // the tail: adj1/adj2 give its tip relative to the centre
                let tx = w / 2.0 + w * adj(0, -20833.0);
                let ty = h / 2.0 + h * adj(1, 62500.0);
                if self.geom == "wedgeEllipseCallout" {
                    ellipse(cr, w / 2.0, h / 2.0, w / 2.0, h / 2.0, false);
                    poly(&[(w * 0.3, h * 0.8), (tx, ty), (w * 0.45, h * 0.95)]);
                } else {
                    let r = if self.geom == "wedgeRoundRectCallout" { ss * 0.16667 } else { 0.0 };
                    cr.new_sub_path();
                    if r > 0.0 {
                        cr.arc(r, r, r, std::f64::consts::PI, 1.5 * std::f64::consts::PI);
                        cr.arc(w - r, r, r, -std::f64::consts::FRAC_PI_2, 0.0);
                        cr.arc(w - r, h - r, r, 0.0, std::f64::consts::FRAC_PI_2);
                    } else {
                        cr.move_to(0.0, 0.0);
                        cr.line_to(w, 0.0);
                        cr.line_to(w, h);
                    }
                    cr.line_to(w * 0.58, h);
                    cr.line_to(tx, ty);
                    cr.line_to(w * 0.42, h);
                    if r > 0.0 {
                        cr.arc(r, h - r, r, std::f64::consts::FRAC_PI_2, std::f64::consts::PI);
                    } else {
                        cr.line_to(0.0, h);
                    }
                    cr.close_path();
                }
            }
            "flowChartProcess" | "rect" | _ => {
                cr.rectangle(0.0, 0.0, w, h);
            }
        }
        true
    }

    /// Fill and outline the shape in a w x h box at the origin.
    pub fn draw(&self, cr: &cairo::Context, w: f64, h: f64) {
        if matches!(self.geom.as_str(), "cloud" | "cloudCallout") {
            // overlapping bumps: one outline round them all
            if let Some((lw, c, _)) = &self.line {
                self.path(cr, w, h);
                set(cr, *c, 1.0);
                cr.set_line_width(lw.max(0.25) * 2.0);
                cr.stroke().ok();
            }
            self.path(cr, w, h);
            let (c, a) = self.fill.unwrap_or((0xFFFFFF, 1.0));
            set(cr, c, a);
            cr.fill().ok();
            return;
        }
        let closed = self.path(cr, w, h);
        if closed {
            if let Some((c, a)) = self.fill {
                set(cr, c, a);
                cr.fill_preserve().ok();
            }
        }
        if let Some((lw, c, dash)) = &self.line {
            set(cr, *c, 1.0);
            cr.set_line_width(lw.max(0.25));
            let d = lw.max(0.5);
            match dash.as_str() {
                "dash" | "lgDash" | "sysDash" | "dashDot" | "lgDashDot" => cr.set_dash(&[d * 4.0, d * 3.0], 0.0),
                "dot" | "sysDot" | "shortdot" => cr.set_dash(&[d, d * 2.0], 0.0),
                _ => {}
            }
            cr.stroke().ok();
            cr.set_dash(&[], 0.0);
            if self.ends != (false, false) {
                // arrowheads along the line's first and last segments
                let (a, b) = match self.geom.as_str() {
                    "bentConnector3" => (((w * 0.5, 0.0), (0.0, 0.0)), ((w * 0.5, h), (w, h))),
                    "bentConnector2" => (((w, 0.0), (0.0, 0.0)), ((w, 0.0), (w, h))),
                    "curvedConnector3" => (((w * 0.5, 0.0), (0.0, 0.0)), ((w * 0.5, h), (w, h))),
                    _ => (((w, h), (0.0, 0.0)), ((0.0, 0.0), (w, h))),
                };
                let size = (lw * 3.0).max(5.0);
                for (on, (from, to)) in [(self.ends.0, a), (self.ends.1, b)] {
                    if !on {
                        continue;
                    }
                    let ang = (to.1 - from.1).atan2(to.0 - from.0);
                    let (ca, sa) = (ang.cos(), ang.sin());
                    cr.move_to(to.0, to.1);
                    cr.line_to(to.0 - size * ca + size * 0.5 * sa, to.1 - size * sa - size * 0.5 * ca);
                    cr.line_to(to.0 - size * ca - size * 0.5 * sa, to.1 - size * sa + size * 0.5 * ca);
                    cr.close_path();
                    cr.fill().ok();
                }
            }
        } else {
            cr.new_path();
        }
    }
}

fn ellipse(cr: &cairo::Context, cx: f64, cy: f64, rx: f64, ry: f64, reverse: bool) {
    cr.save().ok();
    cr.translate(cx, cy);
    cr.scale(rx.max(1e-6), ry.max(1e-6));
    cr.new_sub_path();
    if reverse {
        cr.arc_negative(0.0, 0.0, 1.0, 0.0, -std::f64::consts::TAU);
    } else {
        cr.arc(0.0, 0.0, 1.0, 0.0, std::f64::consts::TAU);
    }
    cr.restore().ok();
}

fn elliptic_arc(cr: &cairo::Context, cx: f64, cy: f64, rx: f64, ry: f64, a0: f64, a1: f64) {
    cr.save().ok();
    cr.translate(cx, cy);
    cr.scale(rx.max(1e-6), ry.max(1e-6));
    cr.arc(0.0, 0.0, 1.0, a0, a1);
    cr.restore().ok();
}

fn set(cr: &cairo::Context, c: u32, a: f64) {
    cr.set_source_rgba(((c >> 16) & 255) as f64 / 255.0, ((c >> 8) & 255) as f64 / 255.0, (c & 255) as f64 / 255.0, a);
}
