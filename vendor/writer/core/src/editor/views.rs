//! Views other than Print Layout: what Outline view and the Immersive
//! Reader show of the body's paragraphs, moving paragraphs and sections, and
//! hyphenation points (syllables).

use super::{Editor, Pos};
use crate::xml::NodeId;

/// One body paragraph for the outline: node, text, level (1-9 headings, 10
/// body text), size (points), bold, italic, colour (-1 automatic), font.
pub type OutlinePara = (NodeId, String, i32, f64, bool, bool, i64, String);

impl Editor {
    pub fn set_view_mode(&mut self, mode: u8, width: f64) {
        if mode == self.view_mode && (mode != 2 || (width - self.web_width).abs() < 0.5) {
            return;
        }
        self.view_mode = mode;
        if width > 50.0 {
            self.web_width = width;
        }
        self.sel_obj = None;
        self.cache.clear();
        let p = self.caret.para;
        self.relayout();
        if self.pidx(&p).is_none() {
            if let Some(first) = self.layout.paras.first() {
                self.caret = Pos { para: first.node, off: 0 };
                self.anchor = self.caret;
            }
        }
    }

    /// The body's paragraphs (tables left out) for Outline view.
    pub fn outline_paras(&self) -> Vec<OutlinePara> {
        let dom = &self.doc.dom;
        let mut out = Vec::new();
        for b in &self.doc.blocks {
            if b.kind != crate::document::BlockKind::Para {
                continue;
            }
            let p = b.node;
            let (pp, rp) = self.doc.para_props(p);
            let level = pp.outline_lvl.map(|l| l as i32 + 1).filter(|l| *l <= 9).unwrap_or(10);
            let text: String = self.doc.para_text(p).chars().filter(|c| *c != '\u{fffc}').collect();
            let size = rp.size.map(|s| s as f64 / 2.0).unwrap_or(11.0);
            let color = match &rp.color {
                Some(crate::props::ColorVal::Rgb(c)) => *c as i64,
                _ => -1,
            };
            let family = rp.font_ascii.clone().unwrap_or_default();
            let _ = dom;
            out.push((p, text, level, size, rp.bold.unwrap_or(false), rp.italic.unwrap_or(false), color, family));
        }
        out
    }

    /// Move paragraphs (in order, siblings) before or after `target`.
    pub fn move_paras(&mut self, nodes: &[NodeId], target: NodeId, after: bool) -> bool {
        if nodes.is_empty() || nodes.contains(&target) {
            return false;
        }
        let dom = &self.doc.dom;
        let Some(parent) = dom.parent(target) else { return false };
        if nodes.iter().any(|&n| dom.parent(n) != Some(parent)) {
            return false;
        }
        let caret_para = self.caret.para;
        self.begin();
        let dom = &mut self.doc.dom;
        for &n in nodes {
            dom.detach(n);
        }
        let mut idx = dom.index_in_parent(target).unwrap_or(0) + if after { 1 } else { 0 };
        // after a heading's whole section
        for &n in nodes {
            dom.insert(parent, idx, n);
            idx += 1;
        }
        self.doc.scan();
        let keep = nodes.contains(&caret_para);
        self.commit("Move", false);
        if keep {
            self.caret = Pos { para: caret_para, off: 0 };
            self.anchor = self.caret;
        }
        true
    }

    /// The paragraphs of a heading's section: it and what follows up to the
    /// next heading of its level or higher.
    pub fn section_paras(&self, head: NodeId) -> Vec<NodeId> {
        let paras = self.outline_paras();
        let Some(i) = paras.iter().position(|p| p.0 == head) else { return Vec::new() };
        let lvl = paras[i].2;
        let mut out = vec![head];
        if lvl == 10 {
            return out;
        }
        for p in &paras[i + 1..] {
            if p.2 <= lvl {
                break;
            }
            out.push(p.0);
        }
        out
    }

    /// Replace a paragraph's text (Outline view's typing).
    pub fn set_para_text(&mut self, p: NodeId, text: &str) -> bool {
        let Some(pl) = self.para_layout(p) else { return false };
        let len = pl.text_len;
        self.caret = Pos { para: p, off: 0 };
        self.anchor = Pos { para: p, off: len };
        self.type_text(text);
        true
    }

    /// Where a word can be hyphenated (character offsets), for syllables.
    pub fn hyphen_points(&self, word: &str, lang: &str) -> Vec<usize> {
        crate::hyph::patterns(lang).map(|p| p.points(word)).unwrap_or_default()
    }
}

impl Editor {
    /// The `n`th body table's cells: rows of cells, each its paragraphs.
    /// The body's top-level blocks in order: ("p", paragraph) or ("t", table index).
    pub fn body_blocks(&self) -> Vec<(&'static str, NodeId, usize)> {
        let mut out = Vec::new();
        let mut t = 0;
        for b in &self.doc.blocks {
            match b.kind {
                crate::document::BlockKind::Para => out.push(("p", b.node, 0)),
                crate::document::BlockKind::Table => {
                    out.push(("t", b.node, t));
                    t += 1;
                }
            }
        }
        out
    }

    /// A paragraph's text as the layout has it (fields shown as results).
    pub fn para_text_of(&mut self, p: NodeId) -> String {
        self.doc.para_text(p)
    }

    /// The names of the changes Undo would take back, most recent last.
    pub fn undo_names(&self) -> Vec<String> {
        self.undo.iter().map(|t| t.name.clone()).collect()
    }

    pub fn table_cells(&self, n: usize) -> Vec<Vec<Vec<NodeId>>> {
        let dom = &self.doc.dom;
        let Some(t) = self.doc.blocks.iter().filter(|b| b.kind == crate::document::BlockKind::Table).nth(n).map(|b| b.node) else {
            return Vec::new();
        };
        let mut out = Vec::new();
        for tr in dom.elements(t).filter(|&r| dom.is(r, "w:tr")) {
            let mut row = Vec::new();
            for tc in dom.elements(tr).filter(|&c| dom.is(c, "w:tc")) {
                row.push(dom.elements(tc).filter(|&p| dom.is(p, "w:p")).collect());
            }
            out.push(row);
        }
        out
    }
}

fn lum(c: u32) -> f64 {
    let ch = |v: u32| {
        let v = v as f64 / 255.0;
        if v <= 0.03928 { v / 12.92 } else { ((v + 0.055) / 1.055).powf(2.4) }
    };
    0.2126 * ch((c >> 16) & 255) + 0.7152 * ch((c >> 8) & 255) + 0.0722 * ch(c & 255)
}

fn contrast(a: u32, b: u32) -> f64 {
    let (la, lb) = (lum(a), lum(b));
    (la.max(lb) + 0.05) / (la.min(lb) + 0.05)
}

fn highlight_rgb(name: &str) -> Option<u32> {
    Some(match name {
        "yellow" => 0xFFFF00, "green" => 0x00FF00, "cyan" => 0x00FFFF, "magenta" => 0xFF00FF,
        "blue" => 0x0000FF, "red" => 0xFF0000, "darkBlue" => 0x000080, "darkCyan" => 0x008080,
        "darkGreen" => 0x008000, "darkMagenta" => 0x800080, "darkRed" => 0x800000,
        "darkYellow" => 0x808000, "darkGray" => 0x808080, "lightGray" => 0xC0C0C0, "black" => 0,
        "white" => 0xFFFFFF,
        _ => return None,
    })
}

impl Editor {
    /// Check Accessibility: (category, label, paragraph or object node).
    pub fn accessibility_issues(&self) -> Vec<(String, String, NodeId)> {
        let dom = &self.doc.dom;
        let mut out: Vec<(String, String, NodeId)> = Vec::new();
        // objects
        for (node, name, kind, _vis) in self.objects_list() {
            if kind == "Equation" || name.starts_with("Ink ") {
                continue;
            }
            let holder = dom.child(node, "wp:inline").or_else(|| dom.child(node, "wp:anchor"));
            let dp = holder.and_then(|h| dom.child(h, "wp:docPr"));
            let file = regex::Regex::new(r"(?i)\.(png|jpe?g|gif|bmp|svg|webp|tiff?|emf|wmf)$").unwrap();
            let desc = dp.map(|d| {
                let a = dom.attr(d, "descr").unwrap_or("").trim().to_string();
                let t = dom.attr(d, "title").unwrap_or("").trim().to_string();
                [a, t].into_iter().find(|v| !v.is_empty() && !file.is_match(v)).unwrap_or_default()
            }).unwrap_or_default();
            let decorative = dp.map_or(false, |d| crate::pictures::find(dom, d, "adec:decorative")
                .map_or(false, |e| dom.attr(e, "val") == Some("1")));
            let text_box = kind == "Text Box" || crate::pictures::find(dom, node, "w:txbxContent").is_some();
            if desc.is_empty() && !decorative && !text_box {
                out.push(("Missing alternative text".into(), name.clone(), node));
            }
            if holder.map_or(false, |h| dom.is(h, "wp:anchor")) && !text_box {
                out.push(("Object not inline".into(), name.clone(), node));
            }
        }
        // tables: a header row
        let mut tn = 0;
        for b in &self.doc.blocks {
            if b.kind != crate::document::BlockKind::Table {
                continue;
            }
            tn += 1;
            let first = dom.elements(b.node).find(|&r| dom.is(r, "w:tr"));
            let hdr = first.and_then(|r| dom.child(r, "w:trPr")).and_then(|p| dom.child(p, "w:tblHeader")).is_some();
            if !hdr {
                let p = first.and_then(|r| crate::pictures::find(dom, r, "w:p")).unwrap_or(b.node);
                out.push(("Missing table header".into(), format!("Table {tn}"), p));
            }
        }
        // paragraphs
        let mut last_level = 0;
        let mut empties = 0;
        for b in &self.doc.blocks {
            if b.kind != crate::document::BlockKind::Para {
                continue;
            }
            let p = b.node;
            let (pp, base) = self.doc.para_props(p);
            let text = self.doc.para_text(p);
            let t = text.trim();
            if let Some(l) = pp.outline_lvl {
                let lvl = l as i32 + 1;
                if lvl <= 9 && !t.is_empty() {
                    if last_level > 0 && lvl > last_level + 1 {
                        out.push(("Skipped heading level".into(), t.chars().take(40).collect(), p));
                    }
                    last_level = lvl;
                }
            }
            if t.is_empty() && !text.contains('\u{fffc}') {
                empties += 1;
                if empties == 3 {
                    out.push(("Repeated blank characters".into(), "Empty paragraphs".into(), p));
                }
                continue;
            }
            empties = 0;
            if text.contains("    ") || text.contains("\t\t\t") {
                out.push(("Repeated blank characters".into(), t.chars().take(40).collect(), p));
            }
            let pbg = pp.shading;
            let mut links: Vec<(NodeId, String)> = Vec::new();
            let mut low_contrast = false;
            for pc in self.doc.para_pieces(p, &base) {
                let crate::document::Item::Text(s) = &pc.item else { continue };
                if s.trim().is_empty() {
                    continue;
                }
                if let Some(l) = pc.link {
                    match links.iter_mut().find(|x| x.0 == l) {
                        Some(x) => x.1.push_str(s),
                        None => links.push((l, s.clone())),
                    }
                }
                if let Some(crate::props::ColorVal::Rgb(c)) = &pc.rpr.color {
                    let bg = pc.rpr.highlight.as_deref().and_then(highlight_rgb)
                        .or(pc.rpr.shading).or(pbg).unwrap_or(0xFFFFFF);
                    if contrast(*c, bg) < 4.5 {
                        low_contrast = true;
                    }
                }
            }
            if low_contrast {
                out.push(("Hard-to-read text contrast".into(), t.chars().take(40).collect(), p));
            }
            for (_l, s) in links {
                let low = s.trim().to_lowercase();
                if matches!(low.as_str(), "click here" | "here" | "link" | "this link" | "read more" | "more")
                    || low.starts_with("http://") || low.starts_with("https://") || low.starts_with("www.") {
                    out.push(("Unclear hyperlink text".into(), s.trim().chars().take(40).collect(), p));
                }
            }
        }
        if self.core_prop_pub("dc:title").map_or(true, |v| v.trim().is_empty()) {
            out.push(("Missing document title".into(), "Document".into(), self.doc.body));
        }
        out
    }
}

impl Editor {
    /// Alt+Shift+Up / Down: the paragraph (or the table row) the caret is in
    /// changes places with the one above / below it.
    pub fn move_block(&mut self, up: bool) -> bool {
        let caret = self.caret;
        let anchor = self.anchor;
        let dom = &self.doc.dom;
        // the unit: a table row, else the paragraph(s) of the selection
        let mut unit = Some(caret.para);
        let mut row = None;
        let mut n = caret.para;
        while let Some(p) = dom.parent(n) {
            if dom.is(p, "w:tr") {
                row = Some(p);
                break;
            }
            if dom.is(p, "w:body") {
                break;
            }
            n = p;
        }
        if let Some(r) = row {
            unit = Some(r);
        }
        let Some(u) = unit else { return false };
        let Some(parent) = dom.parent(u) else { return false };
        let name = if row.is_some() { "w:tr" } else { "" };
        let sibs: Vec<NodeId> = dom.elements(parent).filter(|&c| if row.is_some() { dom.is(c, name) } else { dom.is(c, "w:p") || dom.is(c, "w:tbl") }).collect();
        let Some(i) = sibs.iter().position(|&c| c == u) else { return false };
        let other = if up { if i == 0 { return false } else { sibs[i - 1] } } else { match sibs.get(i + 1) { Some(&x) => x, None => return false } };
        // keep a section break where it is: the body's last sectPr stays last
        if dom.elements(parent).last() == Some(other) && dom.is(other, "w:sectPr") {
            return false;
        }
        self.begin();
        let dom = &mut self.doc.dom;
        dom.detach(u);
        let j = dom.index_in_parent(other).unwrap_or(0);
        dom.insert(parent, if up { j } else { j + 1 }, u);
        self.doc.scan();
        self.commit("Move", false);
        self.caret = caret;
        self.anchor = anchor;
        true
    }
}

impl Editor {
    /// Design > Page Color: the document's background (None: No Color).
    pub fn set_page_color(&mut self, color: Option<&str>) -> bool {
        self.begin();
        let root = self.doc.dom.root;
        if let Some(old) = self.doc.dom.child(root, "w:background") {
            self.doc.dom.detach(old);
        }
        if let Some(c) = color {
            let bg = self.doc.dom.new_element("w:background", &[("w:color", c)]);
            self.doc.dom.insert(root, 0, bg);
        }
        self.cache.clear();
        self.commit("Page Color", false);
        let _ = self.set_settings_xml("w:displayBackgroundShape", if color.is_some() { Some("<w:displayBackgroundShape/>") } else { None });
        true
    }

    pub fn page_color(&self) -> Option<String> {
        self.doc.page_background().map(|c| format!("{:06X}", c))
    }
}

impl Editor {
    /// Page Color > Fill Effects: a gradient, pattern or picture background, as
    /// Word keeps it (w:background with a VML v:background and v:fill).
    /// kind: gradient, gradientRadial, pattern, frame, tile.
    #[allow(clippy::too_many_arguments)]
    pub fn set_page_fill(&mut self, kind: &str, c1: &str, c2: &str, angle: f64, focus: &str, title: &str,
                         image: Option<(&[u8], &str)>) -> bool {
        const NS_V: &str = "urn:schemas-microsoft-com:vml";
        const NS_O: &str = "urn:schemas-microsoft-com:office:office";
        const NS_R: &str = "http://schemas.openxmlformats.org/officeDocument/2006/relationships";
        self.begin();
        let root = self.doc.dom.root;
        for (k, v) in [("xmlns:v", NS_V), ("xmlns:o", NS_O), ("xmlns:r", NS_R)] {
            if self.doc.dom.attr(root, k).is_none() {
                self.doc.dom.set_attr(root, k, v);
            }
        }
        if let Some(old) = self.doc.dom.child(root, "w:background") {
            self.doc.dom.detach(old);
        }
        let mut rid = String::new();
        if let Some((bytes, ext)) = image {
            let main = self.doc.main.clone();
            let mut n = 1;
            while self.doc.pkg.has(&format!("word/media/image{}.{}", n, ext)) {
                n += 1;
            }
            let part = format!("word/media/image{}.{}", n, ext);
            self.doc.pkg.put_raw(&part, bytes.to_vec());
            let ctype = match ext { "png" => "image/png", "gif" => "image/gif", "bmp" => "image/bmp", _ => "image/jpeg" };
            self.doc.pkg.ensure_default(ext, ctype);
            let target = crate::package::Package::relative_target(&main, &part);
            rid = self.doc.pkg.add_rel(&main, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image", &target);
            self.doc.images.insert(rid.clone(), crate::pictures::ImageData { part, bytes: std::sync::Arc::new(bytes.to_vec()) });
        }
        let bg = self.doc.dom.new_element("w:background", &[("w:color", c1)]);
        let fill_color = format!("#{}", c1.to_lowercase());
        let vb = self.doc.dom.new_element("v:background", &[("id", "_x0000_s1025"), ("o:bwmode", "white"),
                                                           ("fillcolor", &fill_color), ("o:targetscreensize", "1024,768")]);
        let color2 = format!("#{}", c2.to_lowercase());
        let ang = format!("{}", angle.round() as i64);
        let mut attrs: Vec<(&str, &str)> = vec![("type", kind)];
        if kind.starts_with("gradient") || kind == "pattern" {
            attrs.push(("color2", &color2));
        }
        if kind == "gradient" {
            attrs.push(("angle", &ang));
            attrs.push(("focus", "100%"));
        }
        if kind == "gradientRadial" {
            attrs.push(("focusposition", focus));
            attrs.push(("focussize", ""));
            attrs.push(("focus", "100%"));
        }
        if !rid.is_empty() {
            attrs.push(("r:id", &rid));
            attrs.push(("recolor", "t"));
        }
        if !title.is_empty() {
            attrs.push(("o:title", title));
        }
        let f = self.doc.dom.new_element("v:fill", &attrs);
        self.doc.dom.append(vb, f);
        self.doc.dom.append(bg, vb);
        self.doc.dom.insert(root, 0, bg);
        self.cache.clear();
        self.commit("Page Color", false);
        let _ = self.set_settings_xml("w:displayBackgroundShape", Some("<w:displayBackgroundShape/>"));
        true
    }
}

impl Editor {
    /// Enter at the very start of a table's first cell, when nothing comes
    /// before the table: a paragraph goes in above it (as in the original).
    pub fn para_before_table(&mut self) -> bool {
        if self.caret.off != 0 || self.anchor != self.caret {
            return false;
        }
        let dom = &self.doc.dom;
        let p = self.caret.para;
        let Some(tc) = dom.parent(p) else { return false };
        if !dom.is(tc, "w:tc") || dom.elements(tc).find(|&k| dom.is(k, "w:p")) != Some(p) {
            return false;
        }
        let Some(tr) = dom.parent(tc) else { return false };
        let Some(tbl) = dom.parent(tr) else { return false };
        if dom.elements(tr).find(|&k| dom.is(k, "w:tc")) != Some(tc) || dom.elements(tbl).find(|&k| dom.is(k, "w:tr")) != Some(tr) {
            return false;
        }
        let Some(parent) = dom.parent(tbl) else { return false };
        // only where nothing can take the caret above the table
        if let Some(i) = dom.index_in_parent(tbl) {
            if dom.children(parent)[..i].iter().any(|&k| dom.is(k, "w:p") || dom.is(k, "w:tbl")) {
                return false;
            }
        }
        self.begin();
        let np = self.doc.dom.new_element("w:p", &[]);
        let i = self.doc.dom.index_in_parent(tbl).unwrap_or(0);
        self.doc.dom.insert(parent, i, np);
        self.doc.scan();
        self.caret = Pos { para: np, off: 0 };
        self.anchor = self.caret;
        self.commit("Typing", false);
        true
    }
}
