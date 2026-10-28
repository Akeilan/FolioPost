//! Mail merge and other things kept in settings.xml: any settings element
//! as XML (w:mailMerge, w:docVars), its relationships, every field with its
//! code as Word reads it (nested fields' results in place), and unlinking
//! fields to plain text.

use super::fields::{order, para_of, FieldInfo};
use super::Editor;
use crate::xml::{NodeId, XmlDoc};

impl Editor {
    fn settings_name(&mut self) -> Option<String> {
        let main = self.doc.main.clone();
        self.doc.pkg.related(&main, "/settings")
    }

    /// A settings.xml element (by tag, "w:mailMerge") as XML, or None.
    pub fn settings_xml(&mut self, tag: &str) -> Option<String> {
        let sp = self.settings_name()?;
        let x = self.doc.pkg.xml(&sp).ok()?;
        let e = x.child(x.root, tag)?;
        Some(x.serialize_node(e))
    }

    /// Put (or with None remove) a settings.xml element, in schema order.
    pub fn set_settings_xml(&mut self, tag: &str, xml: Option<&str>) -> bool {
        let Some(sp) = self.settings_name() else { return false };
        let parsed = match xml {
            Some(x) => {
                let wrapped = format!("<root xmlns:w=\"{}\" xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\">{x}</root>",
                                      crate::document::W_NS);
                match XmlDoc::parse(wrapped.as_bytes()) {
                    Ok(t) => Some(t),
                    Err(_) => return false,
                }
            }
            None => None,
        };
        let Ok(x) = self.doc.pkg.xml_mut(&sp) else { return false };
        let root = x.root;
        let old = x.child(root, tag);
        let at = old.and_then(|o| x.index_in_parent(o));
        if let Some(o) = old {
            x.detach(o);
        }
        if let Some(tmp) = parsed {
            let Some(src) = tmp.elements(tmp.root).next() else { return false };
            let n = x.import_node(&tmp, src);
            for k in ["xmlns:w", "xmlns:r"] {
                x.remove_attr(n, k);
            }
            let idx = match at {
                Some(i) => i,
                None => crate::document::settings_index(x, tag),
            };
            x.insert(root, idx, n);
        }
        self.modified = true;
        true
    }

    /// A relationship of settings.xml (the mail merge data source): its id.
    pub fn add_settings_rel(&mut self, kind: &str, target: &str, external: bool) -> Option<String> {
        let sp = self.settings_name()?;
        let rid = self.doc.pkg.add_rel(&sp, kind, target);
        if external {
            let rels = crate::package::Package::rels_name(&sp);
            if let Ok(x) = self.doc.pkg.xml_mut(&rels) {
                let r = x.elements(x.root).find(|&e| x.attr(e, "Id") == Some(rid.as_str()));
                if let Some(r) = r {
                    x.set_attr(r, "TargetMode", "External");
                }
            }
        }
        self.modified = true;
        Some(rid)
    }

    /// The field's code as Word evaluates it: its own instruction text, with
    /// the results of the fields inside it in their places.
    pub fn field_code(&self, f: &FieldInfo) -> String {
        if f.simple {
            return f.instr.clone();
        }
        let dom = &self.doc.dom;
        let Some(p) = para_of(dom, f.begin) else { return f.instr.clone() };
        let stop = f.sep.or(f.end);
        let mut root = dom.parent(p).unwrap_or(p);
        if let Some(s) = stop {
            // a code spanning paragraphs: their common parent
            while !{
                let mut v = Some(s);
                let mut inside = false;
                while let Some(k) = v {
                    if k == root {
                        inside = true;
                        break;
                    }
                    v = dom.parent(k);
                }
                inside
            } {
                match dom.parent(root) {
                    Some(r) => root = r,
                    None => break,
                }
            }
        }
        let mut nodes = Vec::new();
        order(dom, root, &mut nodes);
        let mut on = false;
        let mut depth = 0i32;
        // in an inner field: before its separator (code: skipped) or after (result: kept)
        let mut inner_result: Vec<bool> = Vec::new();
        let mut s = String::new();
        for n in nodes {
            if n == f.begin {
                on = true;
                continue;
            }
            if !on {
                continue;
            }
            if Some(n) == stop {
                break;
            }
            match dom.name(n) {
                "w:fldChar" => match dom.attr(n, "w:fldCharType") {
                    Some("begin") => {
                        depth += 1;
                        inner_result.push(false);
                    }
                    Some("separate") => {
                        if let Some(l) = inner_result.last_mut() {
                            *l = true;
                        }
                    }
                    Some("end") => {
                        depth -= 1;
                        inner_result.pop();
                    }
                    _ => {}
                },
                "w:instrText" if depth == 0 => s.push_str(&dom.text(n)),
                "w:t" if depth > 0 && inner_result.last() == Some(&true) && inner_result.len() == 1 => s.push_str(&dom.text(n)),
                _ => {}
            }
        }
        s.trim().to_string()
    }

    /// Every field of the body (nested ones too), in document order: (depth,
    /// code as evaluated, result).
    pub fn fields_all(&self) -> Vec<(usize, String, String)> {
        self.fields_in(self.doc.body).iter().map(|f| (f.depth, self.field_code(f), self.field_result(f))).collect()
    }

    /// Set the result of the `i`th field of `fields_all`.
    pub fn set_field_text_at(&mut self, i: usize, text: &str) -> bool {
        let Some(f) = self.fields_in(self.doc.body).into_iter().nth(i) else { return false };
        if self.field_result(&f) == text {
            return true;
        }
        self.begin();
        self.set_field_result(&f, text);
        self.commit("Update Field", false);
        true
    }

    /// Unlink Fields: every field in the body becomes its result's plain
    /// text (the codes go).
    pub fn unlink_fields(&mut self) -> usize {
        let fields: Vec<FieldInfo> = self.fields_in(self.doc.body);
        if fields.is_empty() {
            return 0;
        }
        self.begin();
        let mut n = 0;
        // outermost fields: their whole code goes (inner fields with it)
        let mut drop: Vec<NodeId> = Vec::new();
        for f in fields.iter().filter(|f| f.depth == 0) {
            let dom = &self.doc.dom;
            if f.simple {
                // the w:fldSimple's runs stay, out of it
                let fs = f.begin;
                let parent = dom.parent(fs).unwrap();
                let idx = dom.index_in_parent(fs).unwrap_or(0);
                let kids: Vec<NodeId> = dom.elements(fs).collect();
                let dom = &mut self.doc.dom;
                for (k, c) in kids.into_iter().enumerate() {
                    dom.detach(c);
                    dom.insert(parent, idx + k, c);
                }
                dom.detach(fs);
                n += 1;
                continue;
            }
            let Some(p) = para_of(dom, f.begin) else { continue };
            let root = dom.parent(p).unwrap_or(p);
            let mut nodes = Vec::new();
            order(dom, root, &mut nodes);
            let stop = f.sep.or(f.end);
            let mut on = false;
            let mut in_code = true;
            for k in nodes {
                if k == f.begin {
                    on = true;
                }
                if !on {
                    continue;
                }
                if Some(k) == f.sep {
                    in_code = false;
                }
                if dom.is(k, "w:r") {
                    continue;
                }
                let is_code = in_code && (dom.is(k, "w:fldChar") || dom.is(k, "w:instrText") || dom.is(k, "w:t")
                    || dom.is(k, "w:tab") || dom.is(k, "w:br") || dom.is(k, "w:drawing"));
                if is_code || Some(k) == f.sep || Some(k) == f.end {
                    drop.push(k);
                }
                if Some(k) == f.end || (f.sep.is_none() && Some(k) == stop) {
                    break;
                }
            }
            n += 1;
        }
        // fields inside results (a page number in a table of contents): their
        // codes go too
        for f in fields.iter().filter(|f| f.depth > 0) {
            if !f.simple {
                drop.push(f.begin);
                if let Some(s) = f.sep {
                    drop.push(s);
                }
                if let Some(e) = f.end {
                    drop.push(e);
                }
            }
        }
        let dom = &mut self.doc.dom;
        for k in drop {
            if dom.parent(k).is_none() {
                continue;
            }
            let run = dom.parent(k).filter(|&r| dom.is(r, "w:r"));
            dom.detach(k);
            if let Some(r) = run {
                if dom.elements(r).all(|c| dom.is(c, "w:rPr")) {
                    dom.detach(r);
                }
            }
        }
        self.commit("Unlink Fields", false);
        n
    }
}
