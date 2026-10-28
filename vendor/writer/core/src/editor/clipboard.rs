//! Copy and paste with formatting: the selection as a fragment of the
//! document's XML (runs, paragraphs, tables, equations), and pasting such a
//! fragment back at the caret.

use super::{Editor, Pos};
use crate::xml::{Kind, NodeId, XmlDoc};

/// Elements a copy leaves out (they belong to the place they came from).
const DROP: &[&str] = &["w:commentRangeStart", "w:commentRangeEnd", "w:bookmarkStart", "w:bookmarkEnd",
                        "w:proofErr", "w:permStart", "w:permEnd", "w:del", "w:moveFrom",
                        "w:moveFromRangeStart", "w:moveFromRangeEnd", "w:moveToRangeStart", "w:moveToRangeEnd",
                        "w:rPrChange", "w:pPrChange"];

impl Editor {
    /// Tidy a copied subtree: no comment or bookmark marks, tracked changes
    /// taken as the final text.
    fn clean_fragment(&mut self, n: NodeId) {
        let dom = &mut self.doc.dom;
        let mut stack = vec![n];
        let mut drop = Vec::new();
        let mut unwrap = Vec::new();
        while let Some(x) = stack.pop() {
            for k in dom.elements(x).collect::<Vec<_>>() {
                let name = dom.name(k);
                let parent_is_rpr = dom.parent(k).map_or(false, |p| dom.is(p, "w:rPr") || dom.is(p, "w:trPr"));
                if DROP.contains(&name) && !(parent_is_rpr && name == "w:del") {
                    drop.push(k);
                } else if parent_is_rpr && matches!(name, "w:ins" | "w:del" | "w:moveTo" | "w:moveFrom") {
                    drop.push(k);
                } else if matches!(name, "w:ins" | "w:moveTo") {
                    unwrap.push(k);
                    stack.push(k);
                } else if name == "w:r" && dom.elements(k).any(|c| dom.is(c, "w:commentReference")) {
                    drop.push(k);
                } else {
                    stack.push(k);
                }
            }
        }
        for d in drop {
            dom.detach(d);
        }
        for u in unwrap.into_iter().rev() {
            let Some(par) = dom.parent(u) else { continue };
            let mut idx = dom.index_in_parent(u).unwrap();
            for c in dom.children(u).to_vec() {
                dom.detach(c);
                dom.insert(par, idx, c);
                idx += 1;
            }
            dom.detach(u);
        }
    }

    /// A paragraph copy holding only [s, e) of its text.
    fn trimmed_copy(&mut self, p: NodeId, s: usize, e: usize) -> NodeId {
        let c = self.doc.dom.clone_node(p);
        // a copy sits outside the tree: give it the paragraph's place for
        // style lookups by putting it there for a moment
        let len = self.fresh_len(p);
        let track = self.track;
        self.track = false;
        let parent = self.doc.dom.parent(p).unwrap();
        let idx = self.doc.dom.index_in_parent(p).unwrap();
        let rec = self.doc.dom.recording;
        self.doc.dom.recording = false;
        self.doc.dom.insert(parent, idx + 1, c);
        if e < len {
            self.delete_in_para(c, e, len);
        }
        if s > 0 {
            self.delete_in_para(c, 0, s);
        }
        self.doc.dom.detach(c);
        self.doc.dom.recording = rec;
        self.track = track;
        c
    }

    /// The selection as XML (body content: paragraphs and tables), or None.
    pub fn copy_fragment(&mut self) -> Option<String> {
        let (a, b) = self.selection();
        if a == b {
            return None;
        }
        let rec = self.doc.dom.recording;
        self.doc.dom.recording = false;
        let mut parts: Vec<NodeId> = Vec::new();
        let dom = &self.doc.dom;
        if a.para == b.para {
            let c = self.trimmed_copy(a.para, a.off, b.off);
            parts.push(c);
        } else if dom.parent(a.para) == dom.parent(b.para) {
            let parent = dom.parent(a.para).unwrap();
            let ia = dom.index_in_parent(a.para).unwrap();
            let ib = dom.index_in_parent(b.para).unwrap();
            let between: Vec<NodeId> = dom.children(parent)[ia + 1..ib].to_vec();
            let la = self.fresh_len(a.para);
            parts.push(self.trimmed_copy(a.para, a.off, la));
            for n in between {
                let dom = &mut self.doc.dom;
                if matches!(&dom.node(n).kind, Kind::Element { .. }) && !dom.is(n, "w:sectPr") {
                    let c = dom.clone_node(n);
                    // a section break stays where it was
                    if let Some(sp) = dom.child(c, "w:pPr").and_then(|pp| dom.child(pp, "w:sectPr")) {
                        dom.detach(sp);
                    }
                    parts.push(c);
                }
            }
            parts.push(self.trimmed_copy(b.para, 0, b.off));
        } else {
            // across table cells: the paragraphs themselves
            for p in self.paras_between(a.para, b.para) {
                let len = self.fresh_len(p);
                let s = if p == a.para { a.off } else { 0 };
                let e = if p == b.para { b.off } else { len };
                parts.push(self.trimmed_copy(p, s, e));
            }
        }
        let mut out = String::new();
        for c in parts {
            self.clean_fragment(c);
            let dom = &mut self.doc.dom;
            if let Some(sp) = dom.child(c, "w:pPr").and_then(|pp| dom.child(pp, "w:sectPr")) {
                dom.detach(sp);
            }
            out.push_str(&self.doc.dom.serialize_node(c));
        }
        self.doc.dom.recording = rec;
        Some(out)
    }

    /// The namespace declarations of the document's root (for parsing
    /// fragments).
    fn root_namespaces(&self) -> String {
        let dom = &self.doc.dom;
        let mut s = String::new();
        if let Kind::Element { attrs, .. } = &dom.node(dom.root).kind {
            for (k, v) in attrs {
                if k.starts_with("xmlns") {
                    s.push_str(&format!(" {}=\"{}\"", k, crate::xml::attr_escaped(v)));
                }
            }
        }
        if !s.contains("xmlns:w=") {
            s.push_str(&format!(" xmlns:w=\"{}\"", crate::document::W_NS));
        }
        s
    }

    /// Paste a fragment from copy_fragment at the caret. Not from this
    /// document: what refers to its parts (pictures, links, list
    /// definitions, notes) is left out. Returns false if it isn't one.
    pub fn paste_fragment(&mut self, xml: &str, same_doc: bool) -> bool {
        let wrapped = format!("<w:body{}>{}</w:body>", self.root_namespaces(), xml);
        let Ok(tmp) = XmlDoc::parse(wrapped.as_bytes()) else { return false };
        let blocks: Vec<NodeId> = tmp.elements(tmp.root).filter(|&k| matches!(tmp.name(k), "w:p" | "w:tbl" | "w:sdt")).collect();
        if blocks.is_empty() {
            return false;
        }
        self.begin_group("Paste");
        self.begin();
        self.delete_selection();
        let nodes: Vec<NodeId> = blocks.iter().map(|&b| self.doc.dom.import_node(&tmp, b)).collect();
        if !same_doc {
            for &n in &nodes {
                self.strip_foreign(n);
            }
        }
        let tracking = self.tracking();
        let p = self.caret.para;
        let off = self.caret.off;
        let dom = &self.doc.dom;
        let single = nodes.len() == 1 && dom.is(nodes[0], "w:p");
        if single {
            let src = nodes[0];
            let before = self.fresh_len(p);
            let (parent, idx, _) = self.split_runs_at(p, off);
            let kids: Vec<NodeId> = self.doc.dom.children(src).iter().copied().filter(|&k| !self.doc.dom.is(k, "w:pPr")).collect();
            let n = kids.len();
            for (i, k) in kids.into_iter().enumerate() {
                self.doc.dom.detach(k);
                self.doc.dom.insert(parent, idx + i, k);
            }
            if tracking && n > 0 {
                self.wrap_ins(parent, idx, n);
            }
            let after = self.fresh_len(p);
            self.caret = Pos { para: p, off: off + after.saturating_sub(before) };
        } else {
            // split here: the head keeps what was before the caret
            let tail = self.split_para(p, off);
            let dom = &self.doc.dom;
            let head = dom.children(dom.parent(tail).unwrap())[dom.index_in_parent(tail).unwrap() - 1];
            let mut rest: Vec<NodeId> = nodes.clone();
            // the first pasted paragraph joins the head
            if self.doc.dom.is(rest[0], "w:p") {
                let first = rest.remove(0);
                // into an empty paragraph, the pasted one's paragraph formatting comes too
                if off == 0 && self.fresh_len(head) == 0 {
                    if let Some(np) = self.doc.dom.child(first, "w:pPr") {
                        if let Some(old) = self.doc.dom.child(head, "w:pPr") {
                            self.doc.dom.detach(old);
                        }
                        self.doc.dom.detach(np);
                        self.doc.dom.insert(head, 0, np);
                    }
                }
                let kids: Vec<NodeId> = self.doc.dom.children(first).iter().copied().filter(|&k| !self.doc.dom.is(k, "w:pPr")).collect();
                let at = self.doc.dom.children(head).len();
                let n = kids.len();
                for k in kids {
                    self.doc.dom.detach(k);
                    self.doc.dom.append(head, k);
                }
                if tracking && n > 0 {
                    self.wrap_ins(head, at, n);
                }
            }
            // the last pasted paragraph joins the tail
            let mut tail_len_added = 0;
            if rest.last().map_or(false, |&l| self.doc.dom.is(l, "w:p")) {
                let last = rest.pop().unwrap();
                let before = self.fresh_len(tail);
                let at = self.doc.dom.child(tail, "w:pPr").map(|_| 1).unwrap_or(0);
                let kids: Vec<NodeId> = self.doc.dom.children(last).iter().copied().filter(|&k| !self.doc.dom.is(k, "w:pPr")).collect();
                let n = kids.len();
                for (i, k) in kids.into_iter().enumerate() {
                    self.doc.dom.detach(k);
                    self.doc.dom.insert(tail, at + i, k);
                }
                if tracking && n > 0 {
                    self.wrap_ins(tail, at, n);
                }
                tail_len_added = self.fresh_len(tail).saturating_sub(before);
            }
            // the whole ones go between
            let parent = self.doc.dom.parent(tail).unwrap();
            let mut idx = self.doc.dom.index_in_parent(tail).unwrap();
            for n in rest {
                self.doc.dom.insert(parent, idx, n);
                idx += 1;
                if tracking && self.doc.dom.is(n, "w:p") {
                    let kids = self.doc.dom.children(n).iter().filter(|&&k| !self.doc.dom.is(k, "w:pPr")).count();
                    let at = self.doc.dom.child(n, "w:pPr").map(|_| 1).unwrap_or(0);
                    if kids > 0 {
                        self.wrap_ins(n, at, kids);
                    }
                    self.mark_para(n, "w:ins");
                }
            }
            self.doc.scan();
            self.caret = Pos { para: tail, off: tail_len_added };
        }
        self.anchor = self.caret;
        self.commit("Paste", false);
        self.end_group();
        true
    }

    /// Put children [at, at+n) of `parent` in one insertion of this author.
    fn wrap_ins(&mut self, parent: NodeId, at: usize, n: usize) {
        let ins = self.rev_element("w:ins");
        let kids: Vec<NodeId> = self.doc.dom.children(parent)[at..at + n].to_vec();
        for k in kids {
            self.doc.dom.detach(k);
            self.doc.dom.append(ins, k);
        }
        self.doc.dom.insert(parent, at, ins);
    }

    /// Leave out what only makes sense in the document a fragment came from.
    fn strip_foreign(&mut self, n: NodeId) {
        let dom = &mut self.doc.dom;
        let mut stack = vec![n];
        let mut drop = Vec::new();
        let mut unwrap = Vec::new();
        while let Some(x) = stack.pop() {
            for k in dom.elements(x).collect::<Vec<_>>() {
                match dom.name(k) {
                    "w:drawing" | "w:pict" | "w:object" | "w:footnoteReference" | "w:endnoteReference" | "w:numPr" => drop.push(k),
                    "w:hyperlink" if dom.attr(k, "r:id").is_some() => {
                        unwrap.push(k);
                        stack.push(k);
                    }
                    _ => stack.push(k),
                }
            }
        }
        for d in drop {
            dom.detach(d);
        }
        for u in unwrap.into_iter().rev() {
            let Some(par) = dom.parent(u) else { continue };
            let mut idx = dom.index_in_parent(u).unwrap();
            for c in dom.children(u).to_vec() {
                dom.detach(c);
                dom.insert(par, idx, c);
                idx += 1;
            }
            dom.detach(u);
        }
    }
}
