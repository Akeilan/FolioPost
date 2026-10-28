//! Comments: the comments part (and commentsExtended for replies and
//! resolved state), the ranges they mark in the text, and the commands on
//! them.

use super::{Editor, Pos, Story};
use crate::document::{SubPart, W_NS};
use crate::xml::{NodeId, XmlDoc};
use std::collections::HashMap;

const REL_COMMENTS: &str = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments";
const REL_COMMENTS_EX: &str = "http://schemas.microsoft.com/office/2011/relationships/commentsExtended";
const W14_NS: &str = "http://schemas.microsoft.com/office/word/2010/wordml";
const W15_NS: &str = "http://schemas.microsoft.com/office/word/2012/wordml";

/// A comment as the app shows it.
#[derive(Clone, Debug)]
pub struct CommentInfo {
    pub id: String,
    pub author: String,
    pub initials: String,
    pub date: String,
    pub text: String,
    /// the comment it replies to
    pub parent: Option<String>,
    pub done: bool,
    /// the commented text: from (paragraph, offset) to (paragraph, offset)
    pub range: Option<(Pos, Pos)>,
}

impl Editor {
    fn part_of(&self, kind: &str) -> Option<usize> {
        self.doc.parts.iter().position(|p| p.kind == kind)
    }

    /// The w:comment elements by id.
    fn comment_nodes(&self) -> Vec<(String, NodeId)> {
        let Some(i) = self.part_of("comments") else { return Vec::new() };
        let dom = &self.doc.dom;
        dom.children_named(self.doc.parts[i].root, "w:comment")
            .map(|c| (dom.attr(c, "w:id").unwrap_or("").to_string(), c))
            .collect()
    }

    /// commentsExtended entries by the paraId of the comment's last paragraph.
    fn comment_ex(&self) -> HashMap<String, NodeId> {
        let mut out = HashMap::new();
        let Some(i) = self.part_of("commentsExtended") else { return out };
        let dom = &self.doc.dom;
        for c in dom.elements(self.doc.parts[i].root) {
            if let Some(pid) = dom.attr(c, "w15:paraId") {
                out.insert(pid.to_string(), c);
            }
        }
        out
    }

    fn last_para_id(&self, comment: NodeId) -> Option<String> {
        let dom = &self.doc.dom;
        dom.children_named(comment, "w:p").last().and_then(|p| dom.attr(p, "w14:paraId")).map(|s| s.to_string())
    }

    /// Where a marker element sits in its paragraph's text.
    fn marker_pos(&self, n: NodeId) -> Option<Pos> {
        let dom = &self.doc.dom;
        let mut p = dom.parent(n)?;
        while !dom.is(p, "w:p") {
            p = dom.parent(p)?;
        }
        // document order of the paragraph's nodes
        let mut order: HashMap<NodeId, usize> = HashMap::new();
        let mut stack = vec![p];
        while let Some(x) = stack.pop() {
            let k = order.len();
            order.insert(x, k);
            for &c in dom.children(x).iter().rev() {
                stack.push(c);
            }
        }
        let me = *order.get(&n)?;
        let mut off = 0;
        for (pc, _, e) in self.pieces(p) {
            if pc.node.and_then(|k| order.get(&k)).map_or(false, |&k| k < me) {
                off = e;
            }
        }
        Some(Pos { para: p, off })
    }

    fn body_markers(&self) -> (HashMap<String, NodeId>, HashMap<String, NodeId>, HashMap<String, NodeId>) {
        let dom = &self.doc.dom;
        let mut starts = HashMap::new();
        let mut ends = HashMap::new();
        let mut refs = HashMap::new();
        // the body, then headers, footers and notes
        let mut stack = vec![self.doc.body];
        stack.extend(self.doc.parts.iter().filter(|p| matches!(p.kind, "header" | "footer" | "footnotes" | "endnotes")).map(|p| p.root));
        while let Some(n) = stack.pop() {
            for c in dom.elements(n) {
                let id = || dom.attr(c, "w:id").unwrap_or("").to_string();
                match dom.name(c) {
                    "w:commentRangeStart" => {
                        starts.insert(id(), c);
                    }
                    "w:commentRangeEnd" => {
                        ends.insert(id(), c);
                    }
                    "w:commentReference" => {
                        refs.insert(id(), c);
                    }
                    _ => stack.push(c),
                }
            }
        }
        (starts, ends, refs)
    }

    /// Every comment, in the order of the comments part.
    pub fn comments(&self) -> Vec<CommentInfo> {
        let ex = self.comment_ex();
        let (starts, ends, refs) = self.body_markers();
        let nodes = self.comment_nodes();
        let mut by_para: HashMap<String, String> = HashMap::new();
        for (id, c) in &nodes {
            if let Some(pid) = self.last_para_id(*c) {
                by_para.insert(pid, id.clone());
            }
        }
        let dom = &self.doc.dom;
        let mut out = Vec::new();
        for (id, c) in nodes {
            let text: Vec<String> = dom.children_named(c, "w:p").map(|p| self.doc.para_text(p)).collect();
            let e = self.last_para_id(c).and_then(|pid| ex.get(&pid).copied());
            let parent = e.and_then(|e| dom.attr(e, "w15:paraIdParent")).and_then(|pp| by_para.get(pp)).cloned();
            let done = e.and_then(|e| dom.attr(e, "w15:done")).map_or(false, |v| v == "1" || v == "true");
            let s = starts.get(&id).or_else(|| refs.get(&id)).and_then(|&n| self.marker_pos(n));
            let en = ends.get(&id).or_else(|| refs.get(&id)).and_then(|&n| self.marker_pos(n));
            let range = match (s, en) {
                (Some(a), Some(b)) => Some((a, b)),
                (Some(a), None) | (None, Some(a)) => Some((a, a)),
                _ => None,
            };
            out.push(CommentInfo {
                author: dom.attr(c, "w:author").unwrap_or("").to_string(),
                initials: dom.attr(c, "w:initials").unwrap_or("").to_string(),
                date: dom.attr(c, "w:date").unwrap_or("").to_string(),
                text: text.join("\n"),
                parent,
                done,
                range,
                id,
            });
        }
        out
    }

    /// Rectangles (page, x, y, w, h in points) of a stretch of body text.
    pub fn body_range_rects(&self, a: Pos, b: Pos) -> Vec<(usize, f64, f64, f64, f64)> {
        let mut out = Vec::new();
        let (Some(&ia), Some(&ib)) = (self.layout.index.get(&a.para), self.layout.index.get(&b.para)) else {
            return self.part_range_rects(a, b);
        };
        let mut loc: HashMap<(usize, usize), (usize, usize)> = HashMap::new();
        for (pg, page) in self.layout.pages.iter().enumerate() {
            for (i, l) in page.lines.iter().enumerate() {
                if l.para >= ia && l.para <= ib {
                    loc.entry((l.para, l.line)).or_insert((pg, i));
                }
            }
        }
        for pi in ia..=ib.min(self.layout.paras.len().saturating_sub(1)) {
            let pl = &self.layout.paras[pi];
            let s = if pi == ia { a.off } else { 0 };
            let e = if pi == ib { b.off } else { pl.text_len };
            for (li, line) in pl.lines.iter().enumerate() {
                let last_line = li + 1 == pl.lines.len();
                if line.pos_end < s || line.pos_start > e || (line.pos_end == s && !last_line && line.end > line.start) {
                    continue;
                }
                let Some(&(pg, k)) = loc.get(&(pi, li)) else { continue };
                let placed = &self.layout.pages[pg].lines[k];
                let x1 = Self::x_in_line(pl, li, s.max(line.pos_start));
                let x2 = Self::x_in_line(pl, li, e.min(line.pos_end));
                out.push((pg, placed.x + x1, placed.y, (x2 - x1).max(0.0), line.height));
            }
        }
        if out.is_empty() {
            return self.part_range_rects(a, b);
        }
        out
    }

    /// Rectangles of a stretch of text in a header, footer or note: on the
    /// first page it shows on.
    fn part_range_rects(&self, a: Pos, b: Pos) -> Vec<(usize, f64, f64, f64, f64)> {
        let dom = &self.doc.dom;
        // the paragraphs from a to b (siblings)
        let mut paras = vec![a.para];
        if a.para != b.para {
            let mut n = a.para;
            while let (Some(par), Some(i)) = (dom.parent(n), dom.index_in_parent(n)) {
                match dom.children(par).get(i + 1) {
                    Some(&next) => {
                        n = next;
                        if dom.is(n, "w:p") {
                            paras.push(n);
                        }
                        if n == b.para {
                            break;
                        }
                    }
                    None => break,
                }
            }
        }
        let mut out = Vec::new();
        for (pg, page) in self.layout.pages.iter().enumerate() {
            for lines in [&page.hf_lines, &page.note_lines] {
                for l in lines.iter() {
                    let pl = &self.layout.paras[l.para];
                    if !paras.contains(&pl.node) {
                        continue;
                    }
                    let line = &pl.lines[l.line];
                    let s = if pl.node == a.para { a.off } else { 0 };
                    let e = if pl.node == b.para { b.off } else { pl.text_len };
                    if line.pos_end < s || line.pos_start > e {
                        continue;
                    }
                    let x1 = Self::x_in_line(pl, l.line, s.max(line.pos_start));
                    let x2 = Self::x_in_line(pl, l.line, e.min(line.pos_end));
                    out.push((pg, l.x + x1, l.y, (x2 - x1).max(0.0), line.height));
                }
            }
            if !out.is_empty() {
                break;
            }
        }
        out
    }

    // ------------------------------------------------------------ parts
    fn ensure_comments_part(&mut self, extended: bool) -> usize {
        let (kind, file, rel, ctype, xml) = if extended {
            ("commentsExtended", "commentsExtended", REL_COMMENTS_EX,
             "application/vnd.openxmlformats-officedocument.wordprocessingml.commentsExtended+xml",
             format!("<w15:commentsEx xmlns:w15=\"{W15_NS}\"/>"))
        } else {
            ("comments", "comments", REL_COMMENTS,
             "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml",
             format!("<w:comments xmlns:w=\"{W_NS}\" xmlns:w14=\"{W14_NS}\"/>"))
        };
        if let Some(i) = self.part_of(kind) {
            if !extended {
                // paraIds need the w14 namespace
                let root = self.doc.parts[i].root;
                if self.doc.dom.attr(root, "xmlns:w14").is_none() {
                    self.doc.dom.set_attr(root, "xmlns:w14", W14_NS);
                }
            }
            return i;
        }
        let name = format!("word/{file}.xml");
        let tmp = XmlDoc::parse(xml.as_bytes()).expect("comments part");
        let root = self.doc.dom.import_node(&tmp, tmp.root);
        let main = self.doc.main.clone();
        self.doc.pkg.add_rel(&main, rel, &format!("{file}.xml"));
        self.doc.pkg.set_content_type(&name, ctype);
        let prolog = "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n".to_string();
        self.doc.parts.push(SubPart { name, kind, root, prolog, images: Default::default() });
        self.doc.parts.len() - 1
    }

    fn new_para_id(&mut self) -> String {
        let used: std::collections::HashSet<String> = {
            let dom = &self.doc.dom;
            let mut s = std::collections::HashSet::new();
            if let Some(i) = self.part_of("comments") {
                for c in dom.elements(self.doc.parts[i].root) {
                    for p in dom.elements(c) {
                        if let Some(v) = dom.attr(p, "w14:paraId") {
                            s.insert(v.to_string());
                        }
                    }
                }
            }
            s
        };
        let mut seed = chrono::Utc::now().timestamp_nanos_opt().unwrap_or(1) as u64 ^ (used.len() as u64 * 0x9E37_79B9);
        loop {
            seed = seed.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
            let v = ((seed >> 33) as u32) & 0x7FFF_FFFF;
            let s = format!("{:08X}", v.max(1));
            if !used.contains(&s) {
                return s;
            }
        }
    }

    fn next_comment_id(&self) -> String {
        let max = self.comment_nodes().iter().filter_map(|(id, _)| id.parse::<i64>().ok()).max().unwrap_or(-1);
        (max + 1).to_string()
    }

    fn has_style(&self, id: &str) -> bool {
        self.doc.styles.styles.contains_key(id)
    }

    /// A w:comment holding `text` (paragraphs split at newlines).
    fn build_comment(&mut self, id: &str, text: &str, author: &str) -> (NodeId, String) {
        let date = super::review::now_iso();
        let initials: String = author.split_whitespace().filter_map(|w| w.chars().next()).collect::<String>().to_uppercase();
        let dom = &mut self.doc.dom;
        let c = dom.new_element("w:comment", &[("w:id", id), ("w:author", author), ("w:date", &date), ("w:initials", &initials)]);
        let lines: Vec<&str> = text.split('\n').collect();
        let mut last_id = String::new();
        let text_style = self.has_style("CommentText");
        let ref_style = self.has_style("CommentReference");
        for (i, line) in lines.iter().enumerate() {
            let pid = self.new_para_id();
            let dom = &mut self.doc.dom;
            let p = dom.new_element("w:p", &[("w14:paraId", &pid), ("w14:textId", "77777777")]);
            if text_style {
                let ppr = dom.new_element("w:pPr", &[]);
                let st = dom.new_element("w:pStyle", &[("w:val", "CommentText")]);
                dom.append(ppr, st);
                dom.append(p, ppr);
            }
            if i == 0 {
                let r = dom.new_element("w:r", &[]);
                if ref_style {
                    let rpr = dom.new_element("w:rPr", &[]);
                    let st = dom.new_element("w:rStyle", &[("w:val", "CommentReference")]);
                    dom.append(rpr, st);
                    dom.append(r, rpr);
                }
                let a = dom.new_element("w:annotationRef", &[]);
                dom.append(r, a);
                dom.append(p, r);
            }
            if !line.is_empty() {
                let r = dom.new_element("w:r", &[]);
                let t = dom.new_element("w:t", &[("xml:space", "preserve")]);
                let tx = dom.new_text(line);
                dom.append(t, tx);
                dom.append(r, t);
                dom.append(p, r);
            }
            dom.append(c, p);
            last_id = pid;
        }
        (c, last_id)
    }

    fn reference_run(&mut self, id: &str) -> NodeId {
        let ref_style = self.has_style("CommentReference");
        let dom = &mut self.doc.dom;
        let r = dom.new_element("w:r", &[]);
        if ref_style {
            let rpr = dom.new_element("w:rPr", &[]);
            let st = dom.new_element("w:rStyle", &[("w:val", "CommentReference")]);
            dom.append(rpr, st);
            dom.append(r, rpr);
        }
        let cr = dom.new_element("w:commentReference", &[("w:id", id)]);
        dom.append(r, cr);
        r
    }

    // ------------------------------------------------------------ commands
    /// New Comment on the selection (or the word at the caret). Returns its id.
    pub fn insert_comment(&mut self, text: &str, author: &str) -> Option<String> {
        let (mut a, mut b) = self.selection();
        if a == b {
            let (ws, we) = self.word_at(a);
            if ws.off <= a.off && a.off <= we.off && ws != we {
                a = ws;
                b = we;
                if let Some(pl) = self.para_layout(b.para) {
                    let cs = Self::para_chars(pl);
                    while b.off > a.off && cs.iter().any(|(pos, c)| *pos == b.off - 1 && *c == ' ') {
                        b.off -= 1;
                    }
                }
            }
        }
        let author = if author.is_empty() { self.author.clone() } else { author.to_string() };
        self.begin_group("New Comment");
        let part = self.ensure_comments_part(false);
        self.begin();
        let id = self.next_comment_id();
        let (c, _) = self.build_comment(&id, text, &author);
        let root = self.doc.parts[part].root;
        self.doc.dom.append(root, c);
        // the end first: the start's offsets stay right
        let (parent, idx, _) = self.split_runs_at(b.para, b.off);
        let end = self.doc.dom.new_element("w:commentRangeEnd", &[("w:id", &id)]);
        self.doc.dom.insert(parent, idx, end);
        let r = self.reference_run(&id);
        self.doc.dom.insert(parent, idx + 1, r);
        let (parent, idx, _) = self.split_runs_at(a.para, a.off);
        let start = self.doc.dom.new_element("w:commentRangeStart", &[("w:id", &id)]);
        // before the end marker when the range is empty
        let idx = if self.doc.dom.parent(end) == Some(parent) {
            idx.min(self.doc.dom.index_in_parent(end).unwrap())
        } else {
            idx
        };
        self.doc.dom.insert(parent, idx, start);
        self.commit("New Comment", false);
        self.end_group();
        Some(id)
    }

    /// Reply to a comment.
    pub fn reply_comment(&mut self, parent_id: &str, text: &str, author: &str) -> Option<String> {
        let parent = self.comment_nodes().into_iter().find(|(id, _)| id == parent_id)?.1;
        let author = if author.is_empty() { self.author.clone() } else { author.to_string() };
        self.begin_group("Reply");
        let part = self.ensure_comments_part(false);
        let ex_part = self.ensure_comments_part(true);
        self.begin();
        // the parent needs a paraId to be pointed at
        let parent_pid = match self.last_para_id(parent) {
            Some(p) => p,
            None => {
                let pid = self.new_para_id();
                let last = self.doc.dom.children_named(parent, "w:p").last();
                match last {
                    Some(p) => {
                        self.doc.dom.set_attr(p, "w14:paraId", &pid);
                        pid
                    }
                    None => String::new(),
                }
            }
        };
        let id = self.next_comment_id();
        let (c, pid) = self.build_comment(&id, text, &author);
        // after the parent and its other replies
        let root = self.doc.parts[part].root;
        let idx = self.doc.dom.children(root).len();
        self.doc.dom.insert(root, idx, c);
        let ex_root = self.doc.parts[ex_part].root;
        let ex = self.ex_entry(&parent_pid, ex_root);
        let _ = ex;
        let e = self.doc.dom.new_element("w15:commentEx", &[("w15:paraId", &pid), ("w15:paraIdParent", &parent_pid), ("w15:done", "0")]);
        self.doc.dom.append(ex_root, e);
        // the same range as the parent
        let (starts, ends, refs) = self.body_markers();
        if let Some(&s) = starts.get(parent_id) {
            let n = self.doc.dom.new_element("w:commentRangeStart", &[("w:id", &id)]);
            let (par, i) = (self.doc.dom.parent(s).unwrap(), self.doc.dom.index_in_parent(s).unwrap());
            self.doc.dom.insert(par, i + 1, n);
        }
        if let Some(&en) = ends.get(parent_id) {
            let n = self.doc.dom.new_element("w:commentRangeEnd", &[("w:id", &id)]);
            let (par, i) = (self.doc.dom.parent(en).unwrap(), self.doc.dom.index_in_parent(en).unwrap());
            self.doc.dom.insert(par, i + 1, n);
        }
        if let Some(&rf) = refs.get(parent_id) {
            if let Some(run) = self.run_of(rf) {
                let r = self.reference_run(&id);
                let (par, i) = (self.doc.dom.parent(run).unwrap(), self.doc.dom.index_in_parent(run).unwrap());
                self.doc.dom.insert(par, i + 1, r);
            }
        }
        self.commit("Reply", false);
        self.end_group();
        Some(id)
    }

    /// The commentEx entry for a paraId (created).
    fn ex_entry(&mut self, pid: &str, ex_root: NodeId) -> NodeId {
        if let Some(&e) = self.comment_ex().get(pid) {
            return e;
        }
        let e = self.doc.dom.new_element("w15:commentEx", &[("w15:paraId", pid), ("w15:done", "0")]);
        self.doc.dom.append(ex_root, e);
        e
    }

    /// Resolve (or reopen) a comment.
    pub fn resolve_comment(&mut self, id: &str, done: Option<bool>) -> bool {
        let Some((_, c)) = self.comment_nodes().into_iter().find(|(i, _)| i == id) else { return false };
        self.begin_group("Resolve Comment");
        let ex_part = self.ensure_comments_part(true);
        self.begin();
        let pid = match self.last_para_id(c) {
            Some(p) => p,
            None => {
                let pid = self.new_para_id();
                if let Some(p) = self.doc.dom.children_named(c, "w:p").last() {
                    self.doc.dom.set_attr(p, "w14:paraId", &pid);
                }
                pid
            }
        };
        let ex_root = self.doc.parts[ex_part].root;
        let e = self.ex_entry(&pid, ex_root);
        let cur = matches!(self.doc.dom.attr(e, "w15:done"), Some("1" | "true"));
        let on = done.unwrap_or(!cur);
        self.doc.dom.set_attr(e, "w15:done", if on { "1" } else { "0" });
        self.commit("Resolve Comment", false);
        self.end_group();
        true
    }

    /// Replace a comment's text.
    pub fn edit_comment(&mut self, id: &str, text: &str) -> bool {
        let Some((_, c)) = self.comment_nodes().into_iter().find(|(i, _)| i == id) else { return false };
        self.begin();
        let pid = self.last_para_id(c);
        let author = self.doc.dom.attr(c, "w:author").unwrap_or("").to_string();
        let (fresh, new_pid) = self.build_comment(id, text, &author);
        // keep the date and the paraId replies and state point at
        let dom = &mut self.doc.dom;
        if let Some(pid) = &pid {
            if let Some(p) = dom.children_named(fresh, "w:p").last() {
                dom.set_attr(p, "w14:paraId", pid);
            }
        }
        let _ = new_pid;
        for k in dom.children(c).to_vec() {
            dom.detach(k);
        }
        for k in dom.children(fresh).to_vec() {
            dom.detach(k);
            dom.append(c, k);
        }
        self.commit("Edit Comment", false);
        true
    }

    /// Delete comments (each with its replies).
    pub fn delete_comments(&mut self, ids: &[String]) -> usize {
        let all = self.comments();
        let mut gone: Vec<String> = ids.to_vec();
        // replies go with their comment
        loop {
            let more: Vec<String> = all.iter()
                .filter(|c| c.parent.as_ref().map_or(false, |p| gone.contains(p)) && !gone.contains(&c.id))
                .map(|c| c.id.clone()).collect();
            if more.is_empty() {
                break;
            }
            gone.extend(more);
        }
        let nodes: Vec<(String, NodeId)> = self.comment_nodes().into_iter().filter(|(i, _)| gone.contains(i)).collect();
        if nodes.is_empty() {
            return 0;
        }
        let ex = self.comment_ex();
        let (starts, ends, refs) = self.body_markers();
        self.begin();
        for (id, c) in &nodes {
            if let Some(e) = self.last_para_id(*c).and_then(|p| ex.get(&p).copied()) {
                self.doc.dom.detach(e);
            }
            self.doc.dom.detach(*c);
            for m in [starts.get(id), ends.get(id)].into_iter().flatten() {
                self.doc.dom.detach(*m);
            }
            if let Some(&rf) = refs.get(id) {
                match self.run_of(rf) {
                    Some(run) if self.doc.dom.elements(run).all(|k| matches!(self.doc.dom.name(k), "w:rPr" | "w:commentReference")) => {
                        self.remove_run(run);
                    }
                    _ => {
                        self.doc.dom.detach(rf);
                    }
                }
            }
        }
        self.commit("Delete Comment", false);
        nodes.len()
    }

    /// Delete all comments (or those of one author).
    pub fn delete_all_comments(&mut self, author: Option<&str>) -> usize {
        let ids: Vec<String> = self.comments().into_iter()
            .filter(|c| author.map_or(true, |a| c.author == a))
            .map(|c| c.id).collect();
        self.delete_comments(&ids)
    }

    /// The comment whose range holds the caret (innermost).
    pub fn comment_at_caret(&self) -> Option<String> {
        let c = self.caret;
        let mut best: Option<(usize, String)> = None;
        for info in self.comments() {
            if info.parent.is_some() {
                continue;
            }
            let Some((s, e)) = info.range else { continue };
            if self.cmp(s, c).is_le() && self.cmp(c, e).is_le() {
                let span = if s.para == e.para { e.off - s.off } else { usize::MAX / 2 };
                if best.as_ref().map_or(true, |(b, _)| span < *b) {
                    best = Some((span, info.id));
                }
            }
        }
        best.map(|b| b.1)
    }

    /// Select the next / previous comment's range.
    pub fn goto_comment(&mut self, forward: bool) -> bool {
        if self.story != Story::Body {
            return false;
        }
        let mut list: Vec<(Pos, Pos)> = self.comments().into_iter()
            .filter(|c| c.parent.is_none())
            .filter_map(|c| c.range)
            .collect();
        list.sort_by(|x, y| self.cmp(x.0, y.0));
        let (a, _) = self.selection();
        let pick = if forward {
            list.iter().find(|(s, _)| self.cmp(*s, a).is_gt())
        } else {
            list.iter().rev().find(|(s, _)| self.cmp(*s, a).is_lt())
        };
        let Some(&(s, e)) = pick else { return false };
        self.anchor = s;
        self.caret = e;
        self.goal_x = None;
        self.typing = false;
        true
    }
}
