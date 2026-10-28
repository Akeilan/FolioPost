//! Design > Watermark: a text or picture behind the text of every page,
//! in the headers (as the original keeps it: a VML shape).

use super::Editor;
use crate::xml::{NodeId, XmlDoc};

const NS_V: &str = "urn:schemas-microsoft-com:vml";
const NS_O: &str = "urn:schemas-microsoft-com:office:office";
const NS_R: &str = "http://schemas.openxmlformats.org/officeDocument/2006/relationships";
const REL_IMAGE: &str = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image";

/// What a watermark shows.
pub enum Watermark<'a> {
    None,
    /// text, font, size (None: auto), colour, semitransparent, diagonal
    Text(&'a str, &'a str, Option<f64>, u32, bool, bool),
    /// image bytes, file name, scale (None: auto), washout
    Picture(&'a [u8], &'a str, Option<f64>, bool),
}

fn is_watermark(dom: &XmlDoc, n: NodeId) -> bool {
    let id = dom.attr(n, "id").unwrap_or("");
    dom.is(n, "v:shape") && (id.starts_with("PowerPlusWaterMarkObject") || id.starts_with("WordPictureWatermark"))
}

fn text_extent(text: &str, font: &str) -> (f64, f64) {
    let Ok(s) = cairo::ImageSurface::create(cairo::Format::ARgb32, 1, 1) else { return (text.len() as f64 * 60.0, 100.0) };
    let Ok(cr) = cairo::Context::new(&s) else { return (text.len() as f64 * 60.0, 100.0) };
    cr.select_font_face(font, cairo::FontSlant::Normal, cairo::FontWeight::Normal);
    cr.set_font_size(100.0);
    match cr.text_extents(text) {
        Ok(e) if e.width() > 0.0 => (e.width(), e.height()),
        _ => (text.len() as f64 * 60.0, 100.0),
    }
}

impl Editor {
    /// The watermark shapes in the headers, with the run holding each.
    fn watermark_runs(&self) -> Vec<NodeId> {
        let dom = &self.doc.dom;
        let mut out = Vec::new();
        for p in &self.doc.parts {
            if p.kind != "header" {
                continue;
            }
            fn walk(dom: &XmlDoc, n: NodeId, out: &mut Vec<NodeId>) {
                for c in dom.elements(n) {
                    if is_watermark(dom, c) {
                        // the run around it
                        let mut r = c;
                        while let Some(up) = dom.parent(r) {
                            r = up;
                            if dom.is(r, "w:r") {
                                break;
                            }
                        }
                        if dom.is(r, "w:r") && !out.contains(&r) {
                            out.push(r);
                        }
                    } else {
                        walk(dom, c, out);
                    }
                }
            }
            walk(dom, p.root, &mut out);
        }
        out
    }

    pub fn has_watermark(&self) -> bool {
        !self.watermark_runs().is_empty()
    }

    /// Put (or take away) the watermark on every section's pages.
    pub fn set_watermark(&mut self, wm: Watermark) -> bool {
        self.begin_group("Watermark");
        self.begin();
        for r in self.watermark_runs() {
            self.doc.dom.detach(r);
        }
        self.commit("Watermark", false);
        if let Watermark::None = wm {
            self.end_group();
            return true;
        }
        // every section shows a header
        for sec in 0..self.doc.sections.len() {
            self.ensure_header_footer(sec, false);
        }
        let parts: Vec<usize> = {
            let mut v: Vec<usize> = self.doc.sections.iter().flat_map(|s| s.headers.iter().flatten().copied()).collect();
            v.sort();
            v.dedup();
            v
        };
        let (page_w, page_h, tw_w) = self.doc.sections.first()
            .map(|s| (s.page_w as f64 / 20.0, s.page_h as f64 / 20.0, s.text_width() as f64 / 20.0))
            .unwrap_or((612.0, 792.0, 468.0));
        let _ = page_h;
        self.begin();
        let mut n = 0;
        for part in parts {
            n += 1;
            let (shape, rid_part) = match &wm {
                Watermark::Text(text, font, size, color, semi, diagonal) => {
                    let (ew, eh) = text_extent(text, font);
                    let (w, h) = match size {
                        Some(s) => (ew * s / 100.0, eh * s / 100.0),
                        None => {
                            let w = tw_w * if *diagonal { 0.88 } else { 0.9 };
                            (w, w * eh / ew)
                        }
                    };
                    let style = format!(
                        "position:absolute;margin-left:0;margin-top:0;width:{:.1}pt;height:{:.1}pt;{}z-index:-251657216;\
                         mso-position-horizontal:center;mso-position-horizontal-relative:margin;\
                         mso-position-vertical:center;mso-position-vertical-relative:margin",
                        w, h, if *diagonal { "rotation:315;" } else { "" });
                    let fill = if *semi { "<v:fill opacity=\".5\"/>" } else { "" };
                    (format!(
                        "<v:shapetype id=\"_x0000_t136\" coordsize=\"21600,21600\" o:spt=\"136\" adj=\"10800\" \
                         path=\"m@7,l@8,m@5,21600l@6,21600e\"><v:path textpathok=\"t\" o:connecttype=\"custom\"/>\
                         <v:textpath on=\"t\" fitshape=\"t\"/></v:shapetype>\
                         <v:shape id=\"PowerPlusWaterMarkObject{n}\" o:spid=\"_x0000_s20{n:02}\" type=\"#_x0000_t136\" \
                         style=\"{style}\" o:allowincell=\"f\" fillcolor=\"#{color:06X}\" stroked=\"f\">{fill}\
                         <v:textpath style=\"font-family:&quot;{font}&quot;;font-size:1pt\" string=\"{text}\"/></v:shape>",
                        style = style, color = color & 0xFFFFFF, fill = fill,
                        font = crate::xml::attr_escaped(font), text = crate::xml::attr_escaped(text)), None)
                }
                Watermark::Picture(bytes, name, scale, washout) => {
                    let Some((pw, ph, dx, dy)) = super::objects::image_size(bytes) else { continue };
                    let (mut w, mut h) = (pw as f64 * 72.0 / dx, ph as f64 * 72.0 / dy);
                    match scale {
                        Some(k) => {
                            w *= k;
                            h *= k;
                        }
                        None => {
                            let k = tw_w / w;
                            w *= k;
                            h *= k;
                        }
                    }
                    let _ = page_w;
                    let style = format!(
                        "position:absolute;margin-left:0;margin-top:0;width:{w:.1}pt;height:{h:.1}pt;z-index:-251656192;\
                         mso-position-horizontal:center;mso-position-horizontal-relative:margin;\
                         mso-position-vertical:center;mso-position-vertical-relative:margin");
                    let wash = if *washout { " gain=\"19661f\" blacklevel=\"22938f\"" } else { "" };
                    (format!(
                        "<v:shape id=\"WordPictureWatermark{n}\" o:spid=\"_x0000_s20{n:02}\" type=\"#_x0000_t75\" style=\"{style}\" \
                         o:allowincell=\"f\"><v:imagedata r:id=\"RIDPLACEHOLDER\" o:title=\"{t}\"{wash}/></v:shape>",
                        t = crate::xml::attr_escaped(name)), Some((bytes.to_vec(), name.to_string())))
                }
                Watermark::None => continue,
            };
            // the picture's part, related from this header
            let mut shape = shape;
            if let Some((bytes, name)) = rid_part {
                let ext = name.rsplit('.').next().unwrap_or("png").to_ascii_lowercase();
                let (ext, ctype) = match ext.as_str() {
                    "jpg" | "jpeg" => ("jpeg", "image/jpeg"),
                    "gif" => ("gif", "image/gif"),
                    "bmp" => ("bmp", "image/bmp"),
                    _ => ("png", "image/png"),
                };
                let mut k = 1;
                while self.doc.pkg.has(&format!("word/media/image{k}.{ext}")) {
                    k += 1;
                }
                let media = format!("word/media/image{k}.{ext}");
                self.doc.pkg.put_raw(&media, bytes.clone());
                self.doc.pkg.ensure_default(ext, ctype);
                let pname = self.doc.parts[part].name.clone();
                let target = crate::package::Package::relative_target(&pname, &media);
                let rid = self.doc.pkg.add_rel(&pname, REL_IMAGE, &target);
                self.doc.parts[part].images.insert(rid.clone(),
                    crate::pictures::ImageData { part: media, bytes: std::sync::Arc::new(bytes) });
                shape = shape.replace("RIDPLACEHOLDER", &rid);
            }
            let xml = format!(
                "<w:r xmlns:w=\"{w}\" xmlns:v=\"{v}\" xmlns:o=\"{o}\" xmlns:r=\"{r}\"><w:rPr><w:noProof/></w:rPr><w:pict>{shape}</w:pict></w:r>",
                w = crate::document::W_NS, v = NS_V, o = NS_O, r = NS_R);
            let Ok(tmp) = XmlDoc::parse(xml.as_bytes()) else { continue };
            let root = self.doc.parts[part].root;
            let dom = &self.doc.dom;
            let Some(p) = dom.children_named(root, "w:p").next() else { continue };
            let at = dom.child(p, "w:pPr").map(|_| 1).unwrap_or(0);
            let r = self.doc.dom.import_node(&tmp, tmp.root);
            self.doc.dom.insert(p, at, r);
        }
        self.cache.clear();
        self.commit("Watermark", false);
        self.end_group();
        true
    }
}
