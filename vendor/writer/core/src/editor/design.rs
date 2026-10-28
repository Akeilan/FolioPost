//! Design > Colors and Fonts: the theme part's colour and font schemes
//! (what text, headings and shapes with theme colours and fonts follow).

use super::Editor;
use crate::xml::{NodeId, XmlDoc};

const NS_A: &str = "http://schemas.openxmlformats.org/drawingml/2006/main";
const REL_THEME: &str = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme";
const SLOTS: [&str; 12] = ["dk1", "lt1", "dk2", "lt2", "accent1", "accent2", "accent3", "accent4", "accent5", "accent6",
                           "hlink", "folHlink"];

fn default_theme() -> String {
    let fill = |a: &str| format!("<a:solidFill><a:schemeClr val=\"phClr\"/></a:solidFill>{a}");
    format!(
        "<a:theme xmlns:a=\"{NS_A}\" name=\"Default\"><a:themeElements>\
         <a:clrScheme name=\"Standard\"><a:dk1><a:sysClr val=\"windowText\" lastClr=\"000000\"/></a:dk1>\
         <a:lt1><a:sysClr val=\"window\" lastClr=\"FFFFFF\"/></a:lt1><a:dk2><a:srgbClr val=\"44546A\"/></a:dk2>\
         <a:lt2><a:srgbClr val=\"E7E6E6\"/></a:lt2><a:accent1><a:srgbClr val=\"4472C4\"/></a:accent1>\
         <a:accent2><a:srgbClr val=\"ED7D31\"/></a:accent2><a:accent3><a:srgbClr val=\"A5A5A5\"/></a:accent3>\
         <a:accent4><a:srgbClr val=\"FFC000\"/></a:accent4><a:accent5><a:srgbClr val=\"5B9BD5\"/></a:accent5>\
         <a:accent6><a:srgbClr val=\"70AD47\"/></a:accent6><a:hlink><a:srgbClr val=\"0563C1\"/></a:hlink>\
         <a:folHlink><a:srgbClr val=\"954F72\"/></a:folHlink></a:clrScheme>\
         <a:fontScheme name=\"Default\"><a:majorFont><a:latin typeface=\"Calibri Light\"/><a:ea typeface=\"\"/>\
         <a:cs typeface=\"\"/></a:majorFont><a:minorFont><a:latin typeface=\"Calibri\"/><a:ea typeface=\"\"/>\
         <a:cs typeface=\"\"/></a:minorFont></a:fontScheme>\
         <a:fmtScheme name=\"Default\"><a:fillStyleLst>{f1}{f2}{f3}</a:fillStyleLst>\
         <a:lnStyleLst><a:ln w=\"6350\">{l}</a:ln><a:ln w=\"12700\">{l}</a:ln><a:ln w=\"19050\">{l}</a:ln></a:lnStyleLst>\
         <a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle>\
         <a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst>\
         <a:bgFillStyleLst>{f1}{f2}{f3}</a:bgFillStyleLst></a:fmtScheme></a:themeElements>\
         <a:objectDefaults/><a:extraClrSchemeLst/></a:theme>",
        f1 = fill(""), f2 = fill(""), f3 = fill(""), l = "<a:solidFill><a:schemeClr val=\"phClr\"/></a:solidFill>")
}

fn find(t: &XmlDoc, n: NodeId, name: &str) -> Option<NodeId> {
    if t.name(n) == name {
        return Some(n);
    }
    t.elements(n).find_map(|c| find(t, c, name))
}

impl Editor {
    /// The theme part's name, made (with a standard theme) if missing.
    fn theme_part(&mut self) -> Option<String> {
        let main = self.doc.main.clone();
        if let Some(p) = self.doc.pkg.related(&main, "/theme") {
            return Some(p);
        }
        let part = "word/theme/theme1.xml".to_string();
        let x = XmlDoc::parse(default_theme().as_bytes()).ok()?;
        self.doc.pkg.put_xml(&part, x);
        self.doc.pkg.set_content_type(&part, "application/vnd.openxmlformats-officedocument.theme+xml");
        self.doc.pkg.add_rel(&main, REL_THEME, "theme/theme1.xml");
        Some(part)
    }

    fn theme_now(&mut self) -> Option<(String, XmlDoc)> {
        let part = self.theme_part()?;
        let x = match self.doc.pkg.xml(&part) {
            Ok(x) => x.clone(),
            Err(_) => XmlDoc::parse(default_theme().as_bytes()).ok()?,
        };
        Some((part, x))
    }

    /// Put `new` in as the theme; returns the one it replaces.
    pub(crate) fn swap_theme(&mut self, new: XmlDoc) -> XmlDoc {
        let part = self.theme_part().unwrap_or_else(|| "word/theme/theme1.xml".into());
        let old = self.doc.pkg.xml(&part).ok().cloned().unwrap_or_default();
        self.doc.pkg.put_xml(&part, new.clone());
        self.doc.theme_dom = Some(new);
        self.doc.reload_styles();
        self.cache.clear();
        old
    }

    fn change_theme(&mut self, label: &str, f: impl FnOnce(&mut XmlDoc) -> bool) -> bool {
        let Some((_, old)) = self.theme_now() else { return false };
        let mut new = old.clone();
        if !f(&mut new) {
            return false;
        }
        self.begin();
        self.pending_theme = Some(Box::new(old));
        self.swap_theme(new);
        self.commit(label, false);
        true
    }

    /// Design > Colors: the colour scheme (dk1, lt1, dk2, lt2, accent1-6,
    /// hlink, folHlink in that order).
    pub fn set_theme_colors(&mut self, name: &str, colors: &[u32]) -> bool {
        if colors.len() < 12 {
            return false;
        }
        let colors = colors.to_vec();
        self.change_theme("Theme Colors", |t| {
            let Some(cs) = find(t, t.root, "a:clrScheme") else { return false };
            t.set_attr(cs, "name", name);
            for k in t.children(cs).to_vec() {
                t.detach(k);
            }
            for (i, slot) in SLOTS.iter().enumerate() {
                let e = t.new_element(&format!("a:{slot}"), &[]);
                let v = format!("{:06X}", colors[i] & 0xFFFFFF);
                let c = match *slot {
                    "dk1" if colors[i] == 0 => t.new_element("a:sysClr", &[("val", "windowText"), ("lastClr", "000000")]),
                    "lt1" if colors[i] == 0xFFFFFF => t.new_element("a:sysClr", &[("val", "window"), ("lastClr", "FFFFFF")]),
                    _ => t.new_element("a:srgbClr", &[("val", &v)]),
                };
                t.append(e, c);
                t.append(cs, e);
            }
            true
        })
    }

    /// Design > Fonts: the headings' (major) and body (minor) fonts.
    pub fn set_theme_fonts(&mut self, name: &str, major: &str, minor: &str) -> bool {
        self.change_theme("Theme Fonts", |t| {
            let Some(fs) = find(t, t.root, "a:fontScheme") else { return false };
            t.set_attr(fs, "name", name);
            for (which, face) in [("a:majorFont", major), ("a:minorFont", minor)] {
                let Some(f) = t.child(fs, which) else { continue };
                let latin = match t.child(f, "a:latin") {
                    Some(l) => l,
                    None => {
                        let l = t.new_element("a:latin", &[]);
                        t.insert(f, 0, l);
                        l
                    }
                };
                t.set_attr(latin, "typeface", face);
                for a in ["panose", "pitchFamily", "charset"] {
                    t.remove_attr(latin, a);
                }
            }
            true
        })
    }

    /// (colour scheme name, font scheme name, heading font, body font).
    pub fn theme_info(&self) -> (String, String, String, String) {
        let th = &self.doc.styles.theme;
        let (mut cn, mut fname) = (String::new(), String::new());
        if let Some(t) = self.doc.theme_dom.as_ref() {
            if let Some(cs) = find(t, t.root, "a:clrScheme") {
                cn = t.attr(cs, "name").unwrap_or("").to_string();
            }
            if let Some(fs) = find(t, t.root, "a:fontScheme") {
                fname = t.attr(fs, "name").unwrap_or("").to_string();
            }
        }
        (cn, fname, th.major_latin.clone(), th.minor_latin.clone())
    }

    /// Design > Paragraph Spacing: the Normal style's spacing (twips, line
    /// in 240ths).
    pub fn set_paragraph_spacing(&mut self, before: i32, after: i32, line: i32) -> bool {
        let Some(id) = self.doc.styles.default_para.clone() else { return false };
        let (b, a, l) = (before.to_string(), after.to_string(), line.to_string());
        self.style_apply_para_attrs(&id, "w:spacing", &[("w:before", Some(&b)), ("w:after", Some(&a)),
                                                         ("w:line", Some(&l)), ("w:lineRule", Some("auto")),
                                                         ("w:beforeAutospacing", None), ("w:afterAutospacing", None)]);
        true
    }

    /// Set as Default: this document's styles, theme and numbering
    /// definitions written into a copy of `template`, saved as `out`.
    pub fn save_as_template(&mut self, template: &str, out: &str) -> Result<(), String> {
        let bytes = std::fs::read(template).map_err(|e| e.to_string())?;
        let mut t = crate::document::Document::open(&bytes).map_err(|e| e.0)?;
        if let (Some(sd), Some(tp)) = (self.doc.styles_dom.as_ref(), t.styles_part.clone()) {
            t.styles_dom = Some(sd.clone());
            let _ = tp;
        }
        let main = self.doc.main.clone();
        if let (Some(src), Some(dst)) = (self.doc.pkg.related(&main, "/theme"), t.pkg.related(&t.main.clone(), "/theme")) {
            if let Ok(x) = self.doc.pkg.xml(&src) {
                t.pkg.put_xml(&dst, x.clone());
            }
        }
        let data = t.write().map_err(|e| e.0)?;
        std::fs::write(out, data).map_err(|e| e.to_string())
    }
}
