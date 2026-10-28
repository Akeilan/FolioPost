//! Content controls (w:sdt): inserting them round the selection or with
//! placeholder text, finding the one at the caret, their properties
//! (w:sdtPr as XML), replacing their text, typing over a placeholder, and
//! removing them.

use super::{Editor, Pos};
use crate::xml::{NodeId, XmlDoc};

const W14: &str = "http://schemas.microsoft.com/office/word/2010/wordml";
const W15: &str = "http://schemas.microsoft.com/office/word/2012/wordml";
pub const PLACEHOLDER_STYLE: &str = "PlaceholderText";

impl Editor {
    fn sdts(&self) -> Vec<NodeId> {
        fn walk(d: &XmlDoc, n: NodeId, out: &mut Vec<NodeId>) {
            for c in d.elements(n) {
                if d.is(c, "w:sdt") {
                    out.push(c);
                }
                walk(d, c, out);
            }
        }
        let mut out = Vec::new();
        let root = self.doc.dom.root;
        walk(&self.doc.dom, root, &mut out);
        out
    }

    fn sdt_id(&self, s: NodeId) -> String {
        let d = &self.doc.dom;
        d.child(s, "w:sdtPr").and_then(|p| d.child(p, "w:id")).and_then(|i| d.attr(i, "w:val"))
            .unwrap_or("").to_string()
    }

    fn sdt_by_id(&self, id: &str) -> Option<NodeId> {
        self.sdts().into_iter().find(|&s| self.sdt_id(s) == id)
    }

    /// The innermost content control holding node n.
    fn sdt_above(&self, n: NodeId) -> Option<NodeId> {
        let d = &self.doc.dom;
        let mut c = d.parent(n)?;
        loop {
            if d.is(c, "w:sdt") {
                return Some(c);
            }
            c = d.parent(c)?;
        }
    }

    /// (para, start, end) of an inline control's text.
    pub fn control_range(&self, id: &str) -> Option<(NodeId, usize, usize)> {
        let s = self.sdt_by_id(id)?;
        let d = &self.doc.dom;
        let mut p = d.parent(s)?;
        while !d.is(p, "w:p") {
            if d.is(p, "w:body") || d.is(p, "w:tc") || d.is(p, "w:txbxContent") {
                // a block control: from its first paragraph to its last
                let sc = d.child(s, "w:sdtContent")?;
                let mut ps = Vec::new();
                fn paras(d: &XmlDoc, n: NodeId, out: &mut Vec<NodeId>) {
                    for c in d.elements(n) {
                        if d.is(c, "w:p") {
                            out.push(c);
                        } else {
                            paras(d, c, out);
                        }
                    }
                }
                paras(d, sc, &mut ps);
                let first = *ps.first()?;
                return Some((first, 0, usize::MAX));
            }
            p = d.parent(p)?;
        }
        let mut start = None;
        let mut end = None;
        for (pc, a, b) in self.pieces(p) {
            let Some(node) = pc.node else { continue };
            if self.cc_within(node, s) {
                if start.is_none() {
                    start = Some(a);
                }
                end = Some(b);
            }
        }
        let start = match start {
            Some(x) => x,
            None => {
                // empty: where it stands among the pieces
                let mut off = 0;
                for (pc, _a, b) in self.pieces(p) {
                    if let Some(node) = pc.node {
                        if self.precedes(node, s) {
                            off = b;
                        }
                    }
                }
                off
            }
        };
        Some((p, start, end.unwrap_or(start)))
    }

    fn cc_within(&self, mut n: NodeId, anc: NodeId) -> bool {
        let d = &self.doc.dom;
        loop {
            if n == anc {
                return true;
            }
            match d.parent(n) {
                Some(p) => n = p,
                None => return false,
            }
        }
    }

    /// Does node a come before node b in the document?
    fn precedes(&self, a: NodeId, b: NodeId) -> bool {
        let d = &self.doc.dom;
        let path = |mut n: NodeId| {
            let mut v = vec![];
            while let Some(p) = d.parent(n) {
                v.push(d.index_in_parent(n).unwrap_or(0));
                n = p;
            }
            v.reverse();
            v
        };
        path(a) < path(b)
    }

    /// Every content control: (id, its sdtPr as XML, its text, block?).
    pub fn content_controls(&self) -> Vec<(String, String, String, bool)> {
        let d = &self.doc.dom;
        self.sdts().into_iter().map(|s| {
            let pr = d.child(s, "w:sdtPr").map(|p| d.serialize_node(p)).unwrap_or_default();
            let text = d.child(s, "w:sdtContent").map(|c| self.sdt_text(c)).unwrap_or_default();
            let block = d.child(s, "w:sdtContent")
                .map_or(false, |c| d.elements(c).any(|k| matches!(d.name(k), "w:p" | "w:tbl" | "w:sdt")));
            (self.sdt_id(s), pr, text, block)
        }).collect()
    }

    fn sdt_text(&self, c: NodeId) -> String {
        let d = &self.doc.dom;
        let mut out = String::new();
        fn walk(d: &XmlDoc, n: NodeId, out: &mut String) {
            for k in d.elements(n) {
                match d.name(k) {
                    "w:t" => out.push_str(&d.text(k)),
                    "w:tab" => out.push('\t'),
                    "w:br" | "w:cr" => out.push('\n'),
                    "w:p" => {
                        if !out.is_empty() {
                            out.push('\n');
                        }
                        walk(d, k, out);
                    }
                    "w:del" | "w:instrText" | "w:rPr" | "w:pPr" | "w:delText" => {}
                    _ => walk(d, k, out),
                }
            }
        }
        walk(d, c, &mut out);
        out
    }

    /// The control the caret is in (the innermost), or None.
    pub fn control_at_caret(&self) -> Option<String> {
        let p = self.caret.para;
        let off = self.caret.off;
        for (pc, a, b) in self.pieces(p) {
            let Some(node) = pc.node else { continue };
            if (a <= off && off < b) || (a < off && off == b) || (a == b && a == off) {
                if let Some(s) = self.sdt_above(node) {
                    return Some(self.sdt_id(s));
                }
            }
        }
        // an empty control right here, or a block control round the paragraph
        for s in self.sdts() {
            let id = self.sdt_id(s);
            if let Some((cp, a, b)) = self.control_range(&id) {
                if b == usize::MAX {
                    if self.cc_within(p, s) {
                        return Some(id);
                    }
                } else if cp == p && a <= off && off <= b {
                    return Some(id);
                }
            }
        }
        None
    }

    /// The Placeholder Text style (inside the current transaction).
    fn ensure_placeholder_style(&mut self) {
        self.ensure_styles();
        if self.style_node(PLACEHOLDER_STYLE).is_some() {
            return;
        }
        let xml = format!("<w:styles xmlns:w=\"{}\"><w:style w:type=\"character\" w:styleId=\"PlaceholderText\">\
            <w:name w:val=\"Placeholder Text\"/><w:basedOn w:val=\"DefaultParagraphFont\"/>\
            <w:uiPriority w:val=\"99\"/><w:semiHidden/><w:rPr><w:color w:val=\"666666\"/></w:rPr></w:style></w:styles>",
                          crate::document::W_NS);
        let Ok(tmp) = XmlDoc::parse(xml.as_bytes()) else { return };
        let Some(st) = tmp.elements(tmp.root).next() else { return };
        let sd = self.doc.styles_dom.as_mut().unwrap();
        let n = sd.import_node(&tmp, st);
        let root = sd.root;
        sd.append(root, n);
        self.doc.reload_styles();
    }

    fn ensure_root_ns(&mut self) {
        let d = &mut self.doc.dom;
        let Some(root) = d.elements(d.root).next().or(Some(d.root)) else { return };
        for (k, v) in [("xmlns:w14", W14), ("xmlns:w15", W15)] {
            if d.attr(root, k).is_none() {
                d.set_attr(root, k, v);
            }
        }
    }

    fn parse_pr(&self, xml: &str) -> Option<XmlDoc> {
        let wrapped = format!("<root xmlns:w=\"{}\" xmlns:w14=\"{W14}\" xmlns:w15=\"{W15}\" \
            xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\">{xml}</root>",
                              crate::document::W_NS);
        XmlDoc::parse(wrapped.as_bytes()).ok()
    }

    fn import_pr(&mut self, xml: &str) -> Option<NodeId> {
        let tmp = self.parse_pr(xml)?;
        let src = tmp.elements(tmp.root).next()?;
        let n = self.doc.dom.import_node(&tmp, src);
        for k in ["xmlns:w", "xmlns:w14", "xmlns:w15", "xmlns:r"] {
            self.doc.dom.remove_attr(n, k);
        }
        Some(n)
    }

    fn new_sdt_id(&self) -> String {
        let used: Vec<String> = self.sdts().into_iter().map(|s| self.sdt_id(s)).collect();
        let mut x: i64 = 0x2F3A_1C05 ^ (used.len() as i64 * 7919);
        loop {
            let s = (x as i32).to_string();
            if !used.contains(&s) {
                return s;
            }
            x = x.wrapping_mul(1103515245).wrapping_add(12345) & 0x7FFF_FFFF;
        }
    }

    /// A run with `like`'s formatting holding text (placeholder style if asked).
    fn control_run(&mut self, p: NodeId, like: Option<NodeId>, text: &str, placeholder: bool) -> NodeId {
        let r = self.new_run(p, like, &[]);
        let d = &mut self.doc.dom;
        if placeholder {
            let rpr = match d.child(r, "w:rPr") {
                Some(x) => x,
                None => {
                    let x = d.new_element("w:rPr", &[]);
                    d.insert(r, 0, x);
                    x
                }
            };
            if let Some(old) = d.child(rpr, "w:rStyle") {
                d.detach(old);
            }
            let st = d.new_element("w:rStyle", &[("w:val", PLACEHOLDER_STYLE)]);
            d.insert(rpr, 0, st);
        } else if let Some(rpr) = d.child(r, "w:rPr") {
            if let Some(st) = d.child(rpr, "w:rStyle") {
                if d.attr(st, "w:val") == Some(PLACEHOLDER_STYLE) {
                    d.detach(st);
                }
            }
        }
        if !text.is_empty() {
            let t = d.new_element("w:t", &[("xml:space", "preserve")]);
            let tx = d.new_text(text);
            d.append(t, tx);
            d.append(r, t);
        }
        r
    }

    /// Insert a content control: round the selection (in one paragraph), or
    /// at the caret holding `placeholder` (shown as placeholder text).
    /// `pr` is its w:sdtPr (an id is added). Returns the id.
    pub fn insert_content_control(&mut self, pr: &str, placeholder: &str) -> Option<String> {
        let (a, b) = self.selection();
        if a.para != b.para && self.has_selection() {
            return None;
        }
        let id = self.new_sdt_id();
        self.ensure_root_ns();
        self.begin();
        let prn = self.import_pr(pr)?;
        {
            let d = &mut self.doc.dom;
            if let Some(old) = d.child(prn, "w:id") {
                d.detach(old);
            }
            let idn = d.new_element("w:id", &[("w:val", &id)]);
            // after w:rPr, w:alias, w:tag (schema order)
            let mut at = 0;
            for (i, k) in d.elements(prn).enumerate() {
                if matches!(d.name(k), "w:rPr" | "w:alias" | "w:tag") {
                    at = i + 1;
                }
            }
            let at = d.elements(prn).nth(at).and_then(|k| d.index_in_parent(k)).unwrap_or(d.children(prn).len());
            d.insert(prn, at, idn);
        }
        let p = a.para;
        let sdt = self.doc.dom.new_element("w:sdt", &[]);
        let sc = self.doc.dom.new_element("w:sdtContent", &[]);
        self.doc.dom.append(sdt, prn);
        if self.has_selection() {
            let (pb, _ib, _) = self.split_runs_at(p, b.off);
            let (pa, ia, _) = self.split_runs_at(p, a.off);
            if pa != pb {
                self.doc.dom.recording = false;
                self.txn_before = None;
                return None;
            }
            // what lies between: from ia up to the run that holds b
            let kids: Vec<NodeId> = self.doc.dom.children(pa).to_vec();
            let end_off = b.off;
            let mut take = Vec::new();
            for &k in &kids[ia..] {
                // stop at the first child that starts at or after the end
                let first_off = self.cc_offset(p, k);
                if let Some(o) = first_off {
                    if o >= end_off {
                        break;
                    }
                }
                take.push(k);
            }
            for k in &take {
                self.doc.dom.detach(*k);
                self.doc.dom.append(sc, *k);
            }
            self.doc.dom.append(sdt, sc);
            self.doc.dom.insert(pa, ia, sdt);
        } else {
            let (parent, idx, like) = self.split_runs_at(p, a.off);
            if !placeholder.is_empty() {
                self.ensure_placeholder_style();
            }
            let r = self.control_run(p, like, placeholder, !placeholder.is_empty());
            self.doc.dom.append(sc, r);
            self.doc.dom.append(sdt, sc);
            self.doc.dom.insert(parent, idx, sdt);
            let n = placeholder.chars().count();
            self.anchor = Pos { para: p, off: a.off };
            self.caret = Pos { para: p, off: a.off + n };
        }
        self.commit("Insert Content Control", false);
        Some(id)
    }

    /// The offset where a paragraph child's text begins (None: it has none).
    fn cc_offset(&self, p: NodeId, k: NodeId) -> Option<usize> {
        for (pc, a, _b) in self.pieces(p) {
            if let Some(n) = pc.node {
                if self.cc_within(n, k) {
                    return Some(a);
                }
            }
        }
        None
    }

    pub fn control_pr(&self, id: &str) -> Option<String> {
        let s = self.sdt_by_id(id)?;
        let d = &self.doc.dom;
        d.child(s, "w:sdtPr").map(|p| d.serialize_node(p))
    }

    /// Replace a control's w:sdtPr (its id is kept).
    pub fn set_control_pr(&mut self, id: &str, pr: &str) -> bool {
        let Some(s) = self.sdt_by_id(id) else { return false };
        self.ensure_root_ns();
        self.begin();
        let Some(n) = self.import_pr(pr) else {
            self.commit("Content Control Properties", false);
            return false;
        };
        let d = &mut self.doc.dom;
        if let Some(old) = d.child(n, "w:id") {
            d.detach(old);
        }
        let idn = d.new_element("w:id", &[("w:val", id)]);
        let mut at = 0;
        for (i, k) in d.elements(n).enumerate() {
            if matches!(d.name(k), "w:rPr" | "w:alias" | "w:tag") {
                at = i + 1;
            }
        }
        let at = d.elements(n).nth(at).and_then(|k| d.index_in_parent(k)).unwrap_or(d.children(n).len());
        d.insert(n, at, idn);
        if let Some(old) = d.child(s, "w:sdtPr") {
            d.detach(old);
        }
        d.insert(s, 0, n);
        self.commit("Content Control Properties", false);
        true
    }

    fn sdt_para(&self, s: NodeId) -> Option<NodeId> {
        let d = &self.doc.dom;
        let mut p = d.parent(s)?;
        while !d.is(p, "w:p") {
            p = d.parent(p)?;
        }
        Some(p)
    }

    fn set_text_inner(&mut self, s: NodeId, text: &str, placeholder: bool) -> Option<(NodeId, usize)> {
        let p = self.sdt_para(s)?;
        let sc = match self.doc.dom.child(s, "w:sdtContent") {
            Some(c) => c,
            None => {
                let c = self.doc.dom.new_element("w:sdtContent", &[]);
                self.doc.dom.append(s, c);
                c
            }
        };
        // the formatting of its first run
        let d = &self.doc.dom;
        fn first_run(d: &XmlDoc, n: NodeId) -> Option<NodeId> {
            for k in d.elements(n) {
                if d.is(k, "w:r") {
                    return Some(k);
                }
                if let Some(r) = first_run(d, k) {
                    return Some(r);
                }
            }
            None
        }
        let like = first_run(d, sc);
        let like = like.map(|r| self.doc.dom.clone_node(r));
        if placeholder {
            self.ensure_placeholder_style();
        }
        let r = self.control_run(p, like, text, placeholder);
        let kids: Vec<NodeId> = self.doc.dom.children(sc).to_vec();
        for k in kids {
            self.doc.dom.detach(k);
        }
        self.doc.dom.append(sc, r);
        // showing the placeholder or not
        let d = &mut self.doc.dom;
        if let Some(pr) = d.child(s, "w:sdtPr") {
            let has = d.child(pr, "w:showingPlcHdr");
            match (placeholder, has) {
                (true, None) => {
                    let e = d.new_element("w:showingPlcHdr", &[]);
                    let at = d.elements(pr).position(|k| !matches!(d.name(k), "w:rPr" | "w:alias" | "w:tag" | "w:id" | "w:lock" | "w:placeholder" | "w:temporary"))
                        .and_then(|i| d.elements(pr).nth(i)).and_then(|k| d.index_in_parent(k)).unwrap_or(d.children(pr).len());
                    d.insert(pr, at, e);
                }
                (false, Some(e)) => {
                    d.detach(e);
                }
                _ => {}
            }
        }
        let (_p, start, _e) = self.control_range(&self.sdt_id(s))?;
        Some((p, start))
    }

    /// Put text in an inline control (as placeholder text if asked).
    pub fn set_control_text(&mut self, id: &str, text: &str, placeholder: bool) -> bool {
        let Some(s) = self.sdt_by_id(id) else { return false };
        self.begin();
        let r = self.set_text_inner(s, text, placeholder);
        if let Some((p, start)) = r {
            let n = text.chars().count();
            self.anchor = Pos { para: p, off: start };
            self.caret = Pos { para: p, off: start + n };
        }
        self.commit("Content Control", false);
        r.is_some()
    }

    /// Select a control's text.
    pub fn select_control(&mut self, id: &str) -> bool {
        let Some((p, a, b)) = self.control_range(id) else { return false };
        let b = if b == usize::MAX { self.para_len(p) } else { b };
        self.anchor = Pos { para: p, off: a };
        self.caret = Pos { para: p, off: b };
        true
    }

    /// Remove a control, keeping its content (or deleting it).
    pub fn remove_control(&mut self, id: &str, keep: bool) -> bool {
        let Some(s) = self.sdt_by_id(id) else { return false };
        self.begin();
        let d = &mut self.doc.dom;
        let parent = d.parent(s).unwrap();
        let idx = d.index_in_parent(s).unwrap();
        let showing = d.child(s, "w:sdtPr").map_or(false, |p| d.child(p, "w:showingPlcHdr").is_some());
        if keep && !showing {
            if let Some(sc) = d.child(s, "w:sdtContent") {
                let kids: Vec<NodeId> = d.children(sc).to_vec();
                for (i, k) in kids.into_iter().enumerate() {
                    d.detach(k);
                    d.insert(parent, idx + 1 + i, k);
                }
            }
        }
        d.detach(s);
        let p = self.caret.para;
        if self.doc.dom.parent(p).is_some() {
            let len = self.para_len(p);
            self.caret.off = self.caret.off.min(len);
            self.anchor = self.caret;
        }
        self.commit("Remove Content Control", false);
        true
    }

    /// Is the caret's content control's content locked (Contents cannot be
    /// edited)?
    pub(super) fn content_locked_here(&self) -> bool {
        let Some(id) = self.control_at_caret() else { return false };
        let Some(s) = self.sdt_by_id(&id) else { return false };
        let d = &self.doc.dom;
        d.child(s, "w:sdtPr").and_then(|p| d.child(p, "w:lock")).and_then(|l| d.attr(l, "w:val"))
            .map_or(false, |v| v == "contentLocked" || v == "sdtContentLocked")
    }

    /// Typing over a control that shows its placeholder: the typed text
    /// replaces the placeholder. Returns true when it did.
    pub(super) fn type_into_placeholder(&mut self, text: &str) -> bool {
        if text.contains('\n') {
            return false;
        }
        let Some(id) = self.control_at_caret() else { return false };
        let Some(s) = self.sdt_by_id(&id) else { return false };
        let d = &self.doc.dom;
        let showing = d.child(s, "w:sdtPr").map_or(false, |p| d.child(p, "w:showingPlcHdr").is_some());
        let empty = d.child(s, "w:sdtContent").map_or(true, |c| self.sdt_text(c).is_empty());
        let inline = self.sdt_para(s).is_some();
        if !(showing || empty) || !inline {
            return false;
        }
        self.begin();
        if let Some((p, start)) = self.set_text_inner(s, text, false) {
            let n = text.chars().count();
            self.caret = Pos { para: p, off: start + n };
            self.anchor = self.caret;
        }
        self.commit("Typing", false);
        true
    }

    /// After a deletion: an inline control left empty shows its placeholder
    /// again (Word's default placeholder for its kind).
    pub(super) fn refill_empty_controls(&mut self, p: NodeId) {
        let d = &self.doc.dom;
        let mut hits = Vec::new();
        for s in self.sdts() {
            if self.sdt_para(s) != Some(p) {
                continue;
            }
            let Some(pr) = d.child(s, "w:sdtPr") else { continue };
            if d.elements(pr).any(|k| matches!(d.name(k), "w:picture" | "w14:checkbox" | "w:docPartObj" | "w:citation" | "w:bibliography" | "w:equation")) {
                continue;
            }
            let empty = d.child(s, "w:sdtContent").map_or(true, |c| {
                self.sdt_text(c).is_empty() && !self.has_object(c)
            });
            if empty {
                let text = if d.child(pr, "w:comboBox").is_some() || d.child(pr, "w:dropDownList").is_some() {
                    "Choose an item."
                } else if d.child(pr, "w:date").is_some() {
                    "Click or tap to enter a date."
                } else {
                    "Click or tap here to enter text."
                };
                hits.push((s, text));
            }
        }
        for (s, text) in hits {
            let keep = (self.anchor, self.caret);
            self.set_text_inner(s, text, true);
            self.anchor = keep.0;
            self.caret = keep.1;
        }
    }

    fn has_object(&self, n: NodeId) -> bool {
        let d = &self.doc.dom;
        d.elements(n).any(|k| matches!(d.name(k), "w:drawing" | "w:pict" | "w:object") || self.has_object(k))
    }

    /// Is item at this piece a placeholder (for drawing)?
    pub fn showing_placeholder(&self, id: &str) -> bool {
        let Some(s) = self.sdt_by_id(id) else { return false };
        let d = &self.doc.dom;
        d.child(s, "w:sdtPr").map_or(false, |p| d.child(p, "w:showingPlcHdr").is_some())
    }

    /// Rectangles (para, start, end) of every inline control, for drawing
    /// their frames when the caret is in one.
    pub fn control_ranges(&self) -> Vec<(String, NodeId, usize, usize)> {
        self.sdts().into_iter().filter_map(|s| {
            let id = self.sdt_id(s);
            let (p, a, b) = self.control_range(&id)?;
            Some((id, p, a, b))
        }).collect()
    }
}
