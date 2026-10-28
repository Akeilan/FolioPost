//! Pictures: what a w:drawing / VML picture shows (the image part, crop,
//! rotation, flips, effect room), and decoding images for drawing.

use crate::xml::{NodeId, XmlDoc};
use std::collections::HashMap;
use std::sync::Arc;

/// An image part's bytes.
#[derive(Clone)]
#[derive(Debug)]
pub struct ImageData {
    pub part: String,
    pub bytes: Arc<Vec<u8>>,
}

/// How a picture is drawn inside the room it takes.
#[derive(Clone)]
pub struct Pic {
    pub image: Option<ImageData>,
    /// crop in fractions of the image: left, top, right, bottom
    pub crop: [f64; 4],
    /// room taken by effects around the picture (points): l, t, r, b
    pub effect: [f64; 4],
    /// the picture itself (points)
    pub w: f64,
    pub h: f64,
    /// degrees clockwise
    pub rot: f64,
    pub flip_h: bool,
    pub flip_v: bool,
    /// outline (a:ln): width in points and colour
    pub line: Option<(f64, u32)>,
    /// what kind of object it is when there's no image ("shape", "chart", ...)
    pub kind: &'static str,
    /// a drawn shape (geometry, fill, outline)
    pub shape: Option<crate::shapes::Shape>,
    /// a text box's content (w:txbxContent) and its insets l, t, r, b
    pub text: Option<(NodeId, [f64; 4], &'static str)>,
    /// group members: offset x, y inside the group, and the member
    pub children: Vec<(f64, f64, Pic)>,
    /// shadows, reflection, glow, soft edges, bevel, colour adjustments
    pub fx: Option<Box<crate::effects::Fx>>,
    /// text drawn to fill the shape (a VML text path: watermarks, WordArt):
    /// the text, font family, bold, italic
    pub textpath: Option<(String, String, bool, bool)>,
    /// hidden (the Selection pane's eye): laid out, not drawn
    pub hidden: bool,
    /// a picture cropped to a shape (Crop to Shape)
    pub clip: Option<crate::shapes::Shape>,
    /// linked text boxes: the chain's id and this box's place in it
    pub link: Option<(String, u32)>,
    /// WordArt text warp (a:prstTxWarp other than textNoShape)
    pub warp: Option<String>,
    /// a chart: the theme colours it's drawn in (lt1 dk1 lt2 dk2 accent1-6 hlink folHlink)
    pub chart_theme: Option<Box<[u32; 12]>>,
}

impl PartialEq for Pic {
    fn eq(&self, o: &Pic) -> bool {
        self.image.as_ref().map(|i| &i.part) == o.image.as_ref().map(|i| &i.part)
            && self.crop == o.crop
            && self.effect == o.effect
            && self.w == o.w
            && self.h == o.h
            && self.rot == o.rot
            && self.flip_h == o.flip_h
            && self.flip_v == o.flip_v
            && self.line == o.line
            && self.shape == o.shape
            && self.text.map(|t| t.0) == o.text.map(|t| t.0)
            && self.children.len() == o.children.len()
            && self.fx == o.fx
            && self.textpath == o.textpath
            && self.hidden == o.hidden
            && self.clip == o.clip
            && self.link == o.link
            && self.warp == o.warp
    }
}

impl std::fmt::Debug for Pic {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "Pic({:?}, {}x{})", self.image.as_ref().map(|i| &i.part), self.w, self.h)
    }
}

/// The wps:txbx with chain id `id`.
pub fn find_txbx(dom: &XmlDoc, n: NodeId, id: &str) -> Option<NodeId> {
    for c in dom.elements(n) {
        if dom.is(c, "wps:txbx") && dom.attr(c, "id") == Some(id) {
            return Some(c);
        }
        if let Some(f) = find_txbx(dom, c, id) {
            return Some(f);
        }
    }
    None
}

/// The boxes of a text box chain, in order: (seq, width, height, insets).
pub fn txbx_chain(dom: &XmlDoc, id: &str) -> Vec<(u32, f64, f64, [f64; 4])> {
    fn walk(dom: &XmlDoc, n: NodeId, id: &str, out: &mut Vec<(u32, f64, f64, [f64; 4])>) {
        for c in dom.elements(n) {
            if dom.is(c, "wps:wsp") {
                let seq = if dom.child(c, "wps:txbx").and_then(|t| dom.attr(t, "id")) == Some(id) {
                    Some(0)
                } else {
                    dom.child(c, "wps:linkedTxbx").filter(|l| dom.attr(*l, "id") == Some(id))
                        .map(|l| dom.attr(l, "seq").and_then(|v| v.parse::<u32>().ok()).unwrap_or(1))
                };
                if let Some(seq) = seq {
                    let ext = dom.child(c, "wps:spPr").and_then(|s| dom.child(s, "a:xfrm")).and_then(|x| dom.child(x, "a:ext"));
                    // the drawing's extent wins (a group member has only its xfrm)
                    let mut up = Some(c);
                    let mut extent = None;
                    while let Some(k) = up {
                        if dom.is(k, "wp:anchor") || dom.is(k, "wp:inline") {
                            extent = dom.child(k, "wp:extent");
                            break;
                        }
                        up = dom.parent(k);
                    }
                    let e = extent.or(ext);
                    let n = |k: &str| e.and_then(|e| dom.attr(e, k)).and_then(|v| v.parse::<f64>().ok()).unwrap_or(0.0) / EMU;
                    let bp = dom.child(c, "wps:bodyPr");
                    let ins = |k: &str, d: f64| bp.and_then(|b| dom.attr(b, k)).and_then(|v| v.parse::<f64>().ok()).unwrap_or(d) / EMU;
                    out.push((seq, n("cx"), n("cy"), [ins("lIns", 91440.0), ins("tIns", 45720.0), ins("rIns", 91440.0), ins("bIns", 45720.0)]));
                }
            }
            walk(dom, c, id, out);
        }
    }
    let mut out = Vec::new();
    walk(dom, dom.root, id, &mut out);
    out.sort_by_key(|b| b.0);
    out
}

/// First descendant named `name` (depth first).
pub fn find(dom: &XmlDoc, n: NodeId, name: &str) -> Option<NodeId> {
    for c in dom.elements(n) {
        if dom.is(c, name) {
            return Some(c);
        }
        if let Some(f) = find(dom, c, name) {
            return Some(f);
        }
    }
    None
}

fn num(dom: &XmlDoc, n: NodeId, k: &str) -> f64 {
    dom.attr(n, k).and_then(|v| v.trim_end_matches('%').parse::<f64>().ok()).unwrap_or(0.0)
}

const EMU: f64 = 12700.0;


/// A DrawingML picture (or shape) inside `holder` (wp:inline / wp:anchor):
/// size `w` x `h` points.
pub fn drawingml(dom: &XmlDoc, holder: NodeId, w: f64, h: f64, images: &HashMap<String, ImageData>,
                 colors: &HashMap<String, u32>) -> Pic {
    let mut pic = Pic::empty(w, h);
    if let Some(e) = dom.child(holder, "wp:effectExtent") {
        pic.effect = [num(dom, e, "l") / EMU, num(dom, e, "t") / EMU, num(dom, e, "r") / EMU,
                      num(dom, e, "b") / EMU];
    }
    if let Some(dp) = dom.child(holder, "wp:docPr") {
        pic.hidden = matches!(dom.attr(dp, "hidden"), Some("1") | Some("true"));
    }
    let Some(gd) = find(dom, holder, "a:graphicData") else { return pic };
    let uri = dom.attr(gd, "uri").unwrap_or("");
    pic.kind = if uri.ends_with("/picture") {
        "picture"
    } else if uri.ends_with("/chart") {
        "chart"
    } else if uri.ends_with("/chartex") {
        "chartex"
    } else if uri.contains("wordprocessingShape") {
        "shape"
    } else if uri.contains("diagram") {
        "diagram"
    } else if uri.contains("wordprocessingGroup") || uri.contains("wordprocessingCanvas") {
        "group"
    } else {
        "object"
    };
    let Some(obj) = dom.elements(gd).next() else { return pic };
    if pic.kind == "chart" || pic.kind == "chartex" {
        let rid = dom.attr(obj, "r:id").unwrap_or("");
        pic.image = images.get(rid).cloned();
        pic.chart_theme = Some(Box::new(theme_array(colors)));
        return pic;
    }
    member(dom, obj, &mut pic, images, colors);
    pic
}

/// The theme's colours in the order charts index them.
pub fn theme_array(colors: &HashMap<String, u32>) -> [u32; 12] {
    let d = [0xFFFFFF, 0x000000, 0xE7E6E6, 0x44546A, 0x4472C4, 0xED7D31, 0xA5A5A5, 0xFFC000,
             0x5B9BD5, 0x70AD47, 0x0563C1, 0x954F72];
    let keys = ["lt1", "dk1", "lt2", "dk2", "accent1", "accent2", "accent3", "accent4", "accent5",
                "accent6", "hlink", "folHlink"];
    let mut out = d;
    for (i, k) in keys.iter().enumerate() {
        if let Some(c) = colors.get(*k) {
            out[i] = *c;
        }
    }
    out
}

impl Pic {
    pub fn empty(w: f64, h: f64) -> Pic {
        Pic { image: None, crop: [0.0; 4], effect: [0.0; 4], w, h, rot: 0.0, flip_h: false, flip_v: false,
              line: None, kind: "object", shape: None, text: None, children: Vec::new(), fx: None,
              textpath: None, hidden: false, clip: None, link: None, warp: None, chart_theme: None }
    }
}

fn xfrm_of(dom: &XmlDoc, sppr: Option<NodeId>) -> Option<NodeId> {
    sppr.and_then(|s| dom.child(s, "a:xfrm"))
}

/// Fill `pic` from one drawing object: pic:pic, wps:wsp, wpg:wgp/grpSp,
/// wpc:wpc.
fn member(dom: &XmlDoc, obj: NodeId, pic: &mut Pic, images: &HashMap<String, ImageData>,
          colors: &HashMap<String, u32>) {
    let name = dom.name(obj);
    let sppr = dom.child(obj, "pic:spPr").or_else(|| dom.child(obj, "wps:spPr"))
        .or_else(|| dom.child(obj, "wpg:grpSpPr")).or_else(|| dom.child(obj, "wpc:whole"));
    if let Some(xf) = xfrm_of(dom, sppr) {
        pic.rot = num(dom, xf, "rot") / 60000.0;
        pic.flip_h = dom.attr(xf, "flipH").map_or(false, |v| v == "1" || v == "true");
        pic.flip_v = dom.attr(xf, "flipV").map_or(false, |v| v == "1" || v == "true");
    }
    if name.ends_with(":pic") {
        pic.kind = "picture";
        if let Some(b) = find(dom, obj, "a:blip") {
            let rid = dom.attr(b, "r:embed").or_else(|| dom.attr(b, "r:link")).unwrap_or("");
            pic.image = images.get(rid).cloned();
            if let Some(bf) = dom.parent(b) {
                if let Some(sr) = dom.child(bf, "a:srcRect") {
                    pic.crop = [num(dom, sr, "l") / 100000.0, num(dom, sr, "t") / 100000.0,
                                num(dom, sr, "r") / 100000.0, num(dom, sr, "b") / 100000.0];
                }
            }
        }
        if let Some(sp) = sppr {
            if let Some(ln) = dom.child(sp, "a:ln") {
                if let Some((w, c, _)) = crate::shapes::line_of(dom, ln, colors) {
                    pic.line = Some((w, c));
                }
            }
            let geom = dom.child(sp, "a:prstGeom").and_then(|g| dom.attr(g, "prst")).unwrap_or("rect");
            if geom != "rect" || dom.child(sp, "a:custGeom").is_some() {
                let mut sh = crate::shapes::Shape::parse_sppr(dom, sp, colors);
                sh.fill = None;
                pic.clip = Some(sh);
            }
        }
        let fx = crate::effects::parse(dom, sppr, find(dom, obj, "a:blip"), colors);
        if !fx.is_empty() {
            pic.fx = Some(Box::new(fx));
        }
    } else if name == "wps:wsp" {
        pic.kind = "shape";
        pic.shape = Some(crate::shapes::Shape::parse(dom, obj, colors));
        let fx = crate::effects::parse(dom, sppr, None, colors);
        if !fx.is_empty() {
            pic.fx = Some(Box::new(fx));
        }
        pic.warp = dom.child(obj, "wps:bodyPr").and_then(|b| dom.child(b, "a:prstTxWarp"))
            .and_then(|w| dom.attr(w, "prst")).filter(|p| *p != "textNoShape").map(|p| p.to_string());
        // a linked text box shows the rest of its chain's text
        let linked = dom.child(obj, "wps:linkedTxbx").and_then(|l| {
            let id = dom.attr(l, "id")?.to_string();
            let seq = dom.attr(l, "seq").and_then(|v| v.parse::<u32>().ok()).unwrap_or(1);
            let tb = find_txbx(dom, dom.root, &id)?;
            Some((tb, id, seq))
        });
        let own = dom.child(obj, "wps:txbx");
        if let Some((_, id, seq)) = &linked {
            pic.link = Some((id.clone(), *seq));
        } else if let Some(id) = own.and_then(|t| dom.attr(t, "id")) {
            pic.link = Some((id.to_string(), 0));
        }
        if let Some(tb) = own.or(linked.as_ref().map(|l| l.0)) {
            if let Some(c) = dom.child(tb, "w:txbxContent") {
                let bp = dom.child(obj, "wps:bodyPr");
                let ins = |k: &str, d: f64| bp.and_then(|b| dom.attr(b, k)).and_then(|v| v.parse::<f64>().ok())
                    .unwrap_or(d) / EMU;
                let anchor = match bp.and_then(|b| dom.attr(b, "anchor")) {
                    Some("ctr") => "center",
                    Some("b") => "bottom",
                    _ => "top",
                };
                pic.text = Some((c, [ins("lIns", 91440.0), ins("tIns", 45720.0), ins("rIns", 91440.0),
                                     ins("bIns", 45720.0)], anchor));
            }
        }
    } else if name == "wpg:wgp" || name == "wpg:grpSp" || name == "wpc:wpc" {
        pic.kind = "group";
        // child coordinates map onto the group's box
        let (mut cx, mut cy, mut cw, mut ch) = (0.0, 0.0, pic.w * EMU, pic.h * EMU);
        if let Some(xf) = xfrm_of(dom, sppr) {
            if let Some(o) = dom.child(xf, "a:chOff") {
                cx = num(dom, o, "x");
                cy = num(dom, o, "y");
            }
            if let Some(e) = dom.child(xf, "a:chExt") {
                cw = num(dom, e, "cx").max(1.0);
                ch = num(dom, e, "cy").max(1.0);
            }
        }
        let (sx, sy) = (pic.w / (cw / EMU).max(1e-6), pic.h / (ch / EMU).max(1e-6));
        for c in dom.elements(obj) {
            let cn = dom.name(c);
            if !(cn.ends_with(":wsp") || cn.ends_with(":pic") || cn.ends_with(":grpSp") || cn.ends_with(":wgp")) {
                continue;
            }
            let csp = dom.child(c, "pic:spPr").or_else(|| dom.child(c, "wps:spPr"))
                .or_else(|| dom.child(c, "wpg:grpSpPr"));
            let Some(xf) = xfrm_of(dom, csp) else { continue };
            let (ox, oy) = dom.child(xf, "a:off").map(|o| (num(dom, o, "x"), num(dom, o, "y"))).unwrap_or((0.0, 0.0));
            let (ew, eh) = dom.child(xf, "a:ext").map(|e| (num(dom, e, "cx"), num(dom, e, "cy"))).unwrap_or((0.0, 0.0));
            let mut m = Pic::empty(ew / EMU * sx, eh / EMU * sy);
            member(dom, c, &mut m, images, colors);
            pic.children.push(((ox - cx) / EMU * sx, (oy - cy) / EMU * sy, m));
        }
    }
}

/// A VML picture (v:shape with v:imagedata) of size `w` x `h`.
pub fn vml(dom: &XmlDoc, n: NodeId, w: f64, h: f64, images: &HashMap<String, ImageData>) -> Pic {
    let mut pic = Pic::empty(w, h);
    if let Some(id) = find(dom, n, "v:imagedata") {
        pic.kind = "picture";
        let rid = dom.attr(id, "r:id").or_else(|| dom.attr(id, "o:relid")).unwrap_or("");
        pic.image = images.get(rid).cloned();
        // cropleft="0.1" or "6554f" (fixed 1/65536)
        let frac = |k: &str| -> f64 {
            dom.attr(id, k)
                .map(|v| {
                    if let Some(f) = v.strip_suffix('f') {
                        f.parse::<f64>().unwrap_or(0.0) / 65536.0
                    } else {
                        v.parse::<f64>().unwrap_or(0.0)
                    }
                })
                .unwrap_or(0.0)
        };
        pic.crop = [frac("cropleft"), frac("croptop"), frac("cropright"), frac("cropbottom")];
        // washed out (picture watermarks): gain and black level lowered
        let gain = dom.attr(id, "gain").map(|_| frac("gain")).unwrap_or(1.0);
        let black = frac("blacklevel");
        if gain < 0.99 || black > 0.01 {
            pic.fx = Some(Box::new(crate::effects::Fx { opacity: 1.0, brightness: 0.7, contrast: -0.7,
                                                        ..Default::default() }));
        }
    } else {
        // the first VML shape element
        let el = vml_shape(dom, n);
        if let Some(el) = el {
            pic.kind = "shape";
            pic.shape = Some(crate::shapes::Shape::parse_vml(dom, el));
            if let Some(tp) = dom.child(el, "v:textpath") {
                let st = dom.attr(tp, "style").unwrap_or("");
                let mut family = "Calibri".to_string();
                let (mut bold, mut italic) = (false, false);
                for part in st.split(';') {
                    let mut kv = part.splitn(2, ':');
                    match (kv.next().map(|k| k.trim()), kv.next().map(|v| v.trim())) {
                        (Some("font-family"), Some(v)) => family = v.trim_matches(|c| c == '"' || c == '\'' || c == ' ').replace("&quot;", "").to_string(),
                        (Some("font-weight"), Some(v)) => bold = v == "bold",
                        (Some("font-style"), Some(v)) => italic = v == "italic",
                        _ => {}
                    }
                }
                pic.kind = "wordart";
                pic.textpath = Some((dom.attr(tp, "string").unwrap_or("").to_string(), family, bold, italic));
            }
            if let Some(tb) = dom.child(el, "v:textbox") {
                if let Some(c) = dom.child(tb, "w:txbxContent") {
                    // inset="l,t,r,b" (defaults 0.1in, 0.05in)
                    let mut ins = [7.2, 3.6, 7.2, 3.6];
                    if let Some(v) = dom.attr(tb, "inset") {
                        for (i, part) in v.split(',').enumerate().take(4) {
                            if let Some(pt) = css_len(part.trim()) {
                                ins[i] = pt;
                            }
                        }
                    }
                    pic.text = Some((c, ins, "top"));
                }
            }
        }
    }
    pic
}

/// The first VML shape element under (or at) `n`.
pub fn vml_shape(dom: &XmlDoc, n: NodeId) -> Option<NodeId> {
    const SHAPES: [&str; 7] = ["v:shape", "v:rect", "v:roundrect", "v:oval", "v:line", "v:polyline", "v:group"];
    if SHAPES.iter().any(|s| dom.is(n, s)) {
        return Some(n);
    }
    for c in dom.elements(n) {
        if let Some(f) = vml_shape(dom, c) {
            return Some(f);
        }
    }
    None
}

/// A CSS length ("10pt", "0.5in", "2cm", "12px", "3mm") in points.
pub fn css_len(v: &str) -> Option<f64> {
    let v = v.trim();
    let num: String = v.chars().take_while(|c| c.is_ascii_digit() || *c == '.' || *c == '-').collect();
    let f: f64 = num.parse().ok()?;
    Some(match &v[num.len()..] {
        "in" => f * 72.0,
        "cm" => f * 72.0 / 2.54,
        "mm" => f * 72.0 / 25.4,
        "px" => f * 0.75,
        "pc" => f * 12.0,
        "emu" => f / EMU,
        "" => f * 0.75,
        _ => f,
    })
}

/// Decode an image to a cairo surface no bigger than `max_px` on its long
/// side (None for formats we can't read, e.g. EMF/WMF).
pub fn decode(bytes: &[u8], max_px: u32) -> Option<cairo::ImageSurface> {
    let img = image::load_from_memory(bytes).ok()?;
    let (w, h) = (img.width(), img.height());
    if w == 0 || h == 0 {
        return None;
    }
    let img = if w.max(h) > max_px {
        let f = max_px as f64 / w.max(h) as f64;
        img.resize_exact(((w as f64 * f).round() as u32).max(1), ((h as f64 * f).round() as u32).max(1),
                         image::imageops::FilterType::Triangle)
    } else {
        img
    };
    let rgba = img.to_rgba8();
    let (w, h) = (rgba.width() as i32, rgba.height() as i32);
    let mut surf = cairo::ImageSurface::create(cairo::Format::ARgb32, w, h).ok()?;
    let stride = surf.stride() as usize;
    {
        let mut data = surf.data().ok()?;
        for (y, row) in rgba.rows().enumerate() {
            let out = &mut data[y * stride..y * stride + w as usize * 4];
            for (x, px) in row.enumerate() {
                let a = px[3] as u32;
                let pm = |c: u8| ((c as u32 * a + 127) / 255) as u8;
                let v = (a << 24) | ((pm(px[0]) as u32) << 16) | ((pm(px[1]) as u32) << 8) | pm(px[2]) as u32;
                out[x * 4..x * 4 + 4].copy_from_slice(&v.to_ne_bytes());
            }
        }
    }
    surf.mark_dirty();
    Some(surf)
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Wrap {
    /// in front of or behind the text
    None,
    Square,
    Tight,
    Through,
    TopBottom,
}

/// A floating object anchored in a paragraph.
#[derive(Clone, Debug, PartialEq)]
pub struct Float {
    pub pic: Pic,
    /// horizontal position: relative to, alignment, offset (points), or a
    /// percentage of the reference
    pub h_rel: String,
    pub h_align: Option<String>,
    pub h_off: f64,
    pub h_pct: Option<f64>,
    pub v_rel: String,
    pub v_align: Option<String>,
    pub v_off: f64,
    pub v_pct: Option<f64>,
    pub wrap: Wrap,
    /// bothSides, left, right, largest
    pub side: String,
    /// distance from text: left, top, right, bottom (points)
    pub dist: [f64; 4],
    pub behind: bool,
    pub z: i64,
    pub in_cell: bool,
    pub node: NodeId,
    /// tight/through wrap outline: points as fractions of the object's box
    pub poly: Option<Vec<(f64, f64)>>,
}

/// A wp:anchor.
pub fn anchor(dom: &XmlDoc, a: NodeId, images: &HashMap<String, ImageData>, colors: &HashMap<String, u32>) -> Option<Float> {
    let ext = dom.child(a, "wp:extent")?;
    let w = num(dom, ext, "cx") / EMU;
    let h = num(dom, ext, "cy") / EMU;
    let pic = drawingml(dom, a, w, h, images, colors);
    let d = |k: &str| num(dom, a, k) / EMU;
    let mut f = Float {
        pic,
        h_rel: "column".into(),
        h_align: None,
        h_off: 0.0,
        h_pct: None,
        v_rel: "paragraph".into(),
        v_align: None,
        v_off: 0.0,
        v_pct: None,
        wrap: Wrap::None,
        side: "bothSides".into(),
        dist: [d("distL"), d("distT"), d("distR"), d("distB")],
        behind: dom.attr(a, "behindDoc").map_or(false, |v| v == "1" || v == "true"),
        z: dom.attr(a, "relativeHeight").and_then(|v| v.parse().ok()).unwrap_or(0),
        in_cell: dom.attr(a, "layoutInCell").map_or(true, |v| v == "1" || v == "true"),
        node: a,
        poly: None,
    };
    if dom.attr(a, "simplePos").map_or(false, |v| v == "1" || v == "true") {
        if let Some(sp) = dom.child(a, "wp:simplePos") {
            f.h_rel = "page".into();
            f.v_rel = "page".into();
            f.h_off = num(dom, sp, "x") / EMU;
            f.v_off = num(dom, sp, "y") / EMU;
        }
    } else {
        if let Some(ph) = dom.child(a, "wp:positionH") {
            f.h_rel = dom.attr(ph, "relativeFrom").unwrap_or("column").to_string();
            for c in dom.elements(ph) {
                let t = dom.text(c);
                match dom.name(c) {
                    "wp:posOffset" => f.h_off = t.trim().parse::<f64>().unwrap_or(0.0) / EMU,
                    "wp:align" => f.h_align = Some(t.trim().to_string()),
                    "wp14:pctPosHOffset" => f.h_pct = t.trim().parse::<f64>().ok().map(|v| v / 100000.0),
                    _ => {}
                }
            }
        }
        if let Some(pv) = dom.child(a, "wp:positionV") {
            f.v_rel = dom.attr(pv, "relativeFrom").unwrap_or("paragraph").to_string();
            for c in dom.elements(pv) {
                let t = dom.text(c);
                match dom.name(c) {
                    "wp:posOffset" => f.v_off = t.trim().parse::<f64>().unwrap_or(0.0) / EMU,
                    "wp:align" => f.v_align = Some(t.trim().to_string()),
                    "wp14:pctPosVOffset" => f.v_pct = t.trim().parse::<f64>().ok().map(|v| v / 100000.0),
                    _ => {}
                }
            }
        }
    }
    for c in dom.elements(a) {
        let (wrap, side) = match dom.name(c) {
            "wp:wrapNone" => (Wrap::None, None),
            "wp:wrapSquare" => (Wrap::Square, dom.attr(c, "wrapText")),
            "wp:wrapTight" => (Wrap::Tight, dom.attr(c, "wrapText")),
            "wp:wrapThrough" => (Wrap::Through, dom.attr(c, "wrapText")),
            "wp:wrapTopAndBottom" => (Wrap::TopBottom, None),
            _ => continue,
        };
        f.wrap = wrap;
        if let Some(wp) = dom.child(c, "wp:wrapPolygon") {
            let pts: Vec<(f64, f64)> = dom.elements(wp)
                .map(|p| (num(dom, p, "x") / 21600.0, num(dom, p, "y") / 21600.0))
                .collect();
            if pts.len() >= 3 {
                f.poly = Some(pts);
            }
        }
        if let Some(s) = side {
            f.side = s.to_string();
        }
        // effect room around a wrapped picture keeps text away too
        if let Some(e) = dom.child(c, "wp:effectExtent") {
            f.pic.effect = [num(dom, e, "l") / EMU, num(dom, e, "t") / EMU, num(dom, e, "r") / EMU,
                            num(dom, e, "b") / EMU];
        }
    }
    Some(f)
}

/// A VML shape positioned absolutely (style="position:absolute;...").
pub fn vml_float(dom: &XmlDoc, n: NodeId, images: &HashMap<String, ImageData>) -> Option<Float> {
    let el = vml_shape(dom, n)?;
    let style = dom.attr(el, "style").unwrap_or("");
    if !style.contains("position:absolute") {
        return None;
    }
    let mut css: HashMap<&str, &str> = HashMap::new();
    for part in style.split(';') {
        let mut kv = part.splitn(2, ':');
        if let (Some(k), Some(v)) = (kv.next(), kv.next()) {
            css.insert(k.trim(), v.trim());
        }
    }
    let len = |k: &str| css.get(k).and_then(|v| css_len(v)).unwrap_or(0.0);
    let w = len("width");
    let h = len("height");
    let mut pic = vml(dom, n, w, h, images);
    pic.rot = css.get("rotation").and_then(|v| v.trim_end_matches("fd").parse::<f64>().ok())
        .map(|v| if css.get("rotation").is_some_and(|r| r.ends_with("fd")) { v / 65536.0 } else { v }).unwrap_or(0.0);
    let hrel = match css.get("mso-position-horizontal-relative").copied().unwrap_or("text") {
        "page" => "page",
        "margin" => "margin",
        "left-margin-area" => "leftMargin",
        "right-margin-area" => "rightMargin",
        "char" => "character",
        _ => "column",
    };
    let vrel = match css.get("mso-position-vertical-relative").copied().unwrap_or("text") {
        "page" => "page",
        "margin" => "margin",
        "top-margin-area" => "topMargin",
        "bottom-margin-area" => "bottomMargin",
        "line" => "line",
        _ => "paragraph",
    };
    let halign = css.get("mso-position-horizontal").filter(|v| **v != "absolute").map(|v| v.to_string());
    let valign = css.get("mso-position-vertical").filter(|v| **v != "absolute").map(|v| v.to_string());
    let z: i64 = css.get("z-index").and_then(|v| v.parse().ok()).unwrap_or(0);
    let mut wrap = Wrap::None;
    let mut side = "bothSides".to_string();
    if let Some(wr) = find(dom, el, "w10:wrap") {
        wrap = match dom.attr(wr, "type").unwrap_or("") {
            "square" => Wrap::Square,
            "tight" => Wrap::Tight,
            "through" => Wrap::Through,
            "topAndBottom" => Wrap::TopBottom,
            _ => Wrap::None,
        };
        side = match dom.attr(wr, "side").unwrap_or("both") {
            "left" => "left",
            "right" => "right",
            "largest" => "largest",
            _ => "bothSides",
        }
        .into();
    }
    let dist = [len("mso-wrap-distance-left"), len("mso-wrap-distance-top"), len("mso-wrap-distance-right"),
                len("mso-wrap-distance-bottom")];
    Some(Float {
        pic,
        h_rel: hrel.into(),
        h_align: halign,
        h_off: len("margin-left") + len("left"),
        h_pct: None,
        v_rel: vrel.into(),
        v_align: valign,
        v_off: len("margin-top") + len("top"),
        v_pct: None,
        wrap,
        side,
        dist,
        behind: z < 0,
        z,
        in_cell: true,
        node: el,
        poly: None,
    })
}
