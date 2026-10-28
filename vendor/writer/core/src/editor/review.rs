//! Tracked changes: recording edits as insertions, deletions and formatting
//! changes while Track Changes is on; listing, accepting and rejecting them.

use super::{ensure_child_first, Editor, Pos, PPR_ORDER};
use crate::document::Markup;
use crate::xml::{Kind, NodeId, XmlDoc};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ChangeKind {
    Insert,
    Delete,
    /// an inserted / deleted paragraph mark
    ParaInsert,
    ParaDelete,
    /// run formatting (w:rPrChange)
    Format,
    /// paragraph formatting (w:pPrChange)
    ParaFormat,
    /// table, row, cell or section properties (w:*PrChange)
    PropFormat,
    RowInsert,
    RowDelete,
}

impl ChangeKind {
    pub fn name(self) -> &'static str {
        match self {
            ChangeKind::Insert => "Insert",
            ChangeKind::Delete => "Delete",
            ChangeKind::ParaInsert => "Insert",
            ChangeKind::ParaDelete => "Delete",
            ChangeKind::Format => "Format",
            ChangeKind::ParaFormat => "ParagraphFormat",
            ChangeKind::PropFormat => "TableFormat",
            ChangeKind::RowInsert => "TableRowInsert",
            ChangeKind::RowDelete => "TableRowDelete",
        }
    }
    fn is_insert(self) -> bool {
        matches!(self, ChangeKind::Insert | ChangeKind::ParaInsert | ChangeKind::RowInsert)
    }
}

/// One tracked change.
#[derive(Clone, Debug)]
pub struct Change {
    pub kind: ChangeKind,
    pub node: NodeId,
    pub author: String,
    pub date: String,
    /// the paragraph it is in (or starts in)
    pub para: Option<NodeId>,
    /// its text span in that paragraph
    pub start: usize,
    pub end: usize,
}

const PROP_CHANGES: &[(&str, &str)] = &[
    ("w:rPrChange", "w:rPr"),
    ("w:pPrChange", "w:pPr"),
    ("w:sectPrChange", "w:sectPr"),
    ("w:tblPrChange", "w:tblPr"),
    ("w:trPrChange", "w:trPr"),
    ("w:tcPrChange", "w:tcPr"),
    ("w:tblPrExChange", "w:tblPrEx"),
    ("w:tblGridChange", "w:tblGrid"),
];

pub fn now_iso() -> String {
    chrono::Utc::now().format("%Y-%m-%dT%H:%M:%SZ").to_string()
}

fn rename(dom: &mut XmlDoc, n: NodeId, name: &str) -> NodeId {
    let attrs: Vec<(String, String)> = match &dom.node(n).kind {
        Kind::Element { attrs, .. } => attrs.clone(),
        _ => return n,
    };
    let a: Vec<(&str, &str)> = attrs.iter().map(|(k, v)| (k.as_str(), v.as_str())).collect();
    let m = dom.new_element(name, &a);
    for k in dom.children(n).to_vec() {
        dom.detach(k);
        dom.append(m, k);
    }
    let parent = dom.parent(n).unwrap();
    let idx = dom.index_in_parent(n).unwrap();
    dom.detach(n);
    dom.insert(parent, idx, m);
    m
}

/// Replace `n` by its children.
fn unwrap(dom: &mut XmlDoc, n: NodeId) {
    let Some(parent) = dom.parent(n) else { return };
    let mut idx = dom.index_in_parent(n).unwrap();
    for k in dom.children(n).to_vec() {
        dom.detach(k);
        dom.insert(parent, idx, k);
        idx += 1;
    }
    dom.detach(n);
}

impl Editor {
    /// Is Track Changes recording edits?
    pub fn tracking(&self) -> bool {
        self.track && self.doc.markup != Markup::Original
    }

    pub fn set_track_changes(&mut self, on: bool) {
        if self.track != on {
            self.track = on;
            self.doc.settings.track_revisions = on;
            self.modified = true;
        }
        self.typing = false;
    }

    pub fn set_show_fmt_changes(&mut self, on: bool) {
        if self.doc.show_fmt_changes != on {
            self.doc.show_fmt_changes = on;
            self.cache.retain(|_, _| false);
            self.relayout();
        }
    }

    pub fn set_markup(&mut self, m: Markup) {
        if self.doc.markup != m {
            self.doc.markup = m;
            self.cache.retain(|_, _| false);
            self.relayout();
        }
    }

    /// Deletions in balloons in the margin (All Markup) or inline.
    pub fn set_balloons(&mut self, on: bool) {
        if self.doc.balloons != on {
            self.doc.balloons = on;
            self.cache.retain(|_, _| false);
            self.relayout();
        }
    }

    /// The balloons for revisions (All Markup with balloons on): deletions
    /// and formatting. (author, date, label, page, x, y, h)
    pub fn revision_balloons(&self) -> Vec<(String, String, String, usize, f64, f64, f64)> {
        let mut out = Vec::new();
        if !(self.doc.markup == Markup::All && self.doc.balloons) {
            return out;
        }
        for c in self.all_changes() {
            let label = match c.kind {
                ChangeKind::Delete => {
                    let t = self.doc.dom.text(c.node);
                    if t.trim().is_empty() { continue; }
                    format!("Deleted: {}", t.chars().take(120).collect::<String>())
                }
                ChangeKind::ParaDelete => "Deleted: \u{b6}".to_string(),
                ChangeKind::Format => format!("Formatted: {}", self.format_label(c.node)),
                ChangeKind::ParaFormat => "Formatted: Paragraph".to_string(),
                ChangeKind::RowDelete => "Deleted Cells".to_string(),
                _ => continue,
            };
            let Some(p) = c.para else { continue };
            let at = Pos { para: p, off: c.start };
            let Some(r) = self.body_range_rects(at, Pos { para: p, off: c.start }).into_iter().next() else { continue };
            out.push((c.author, c.date, label, r.0, r.1, r.2, r.4));
        }
        out
    }

    /// What a formatting change set, in words ("Bold, Italic, Font color: Red").
    fn format_label(&self, change: NodeId) -> String {
        let dom = &self.doc.dom;
        let Some(new) = dom.parent(change) else { return String::new() };
        let old = dom.child(change, "w:rPr");
        let names = |n: Option<NodeId>| -> Vec<String> {
            n.map(|n| dom.elements(n).filter(|&k| !matches!(dom.name(k), "w:rPrChange" | "w:ins" | "w:del"))
                .map(|k| dom.serialize_node(k)).collect()).unwrap_or_default()
        };
        let before = names(old);
        let mut parts: Vec<String> = Vec::new();
        for k in dom.elements(new) {
            let nm = dom.name(k);
            if matches!(nm, "w:rPrChange" | "w:ins" | "w:del") || before.contains(&dom.serialize_node(k)) {
                continue;
            }
            let off = matches!(dom.attr(k, "w:val"), Some("0" | "false" | "none"));
            let word = match nm {
                "w:b" => if off { "Not Bold" } else { "Bold" }.to_string(),
                "w:i" => if off { "Not Italic" } else { "Italic" }.to_string(),
                "w:u" => if off { "No underline" } else { "Underline" }.to_string(),
                "w:strike" => "Strikethrough".to_string(),
                "w:color" => format!("Font color: {}", dom.attr(k, "w:val").unwrap_or("")),
                "w:sz" => format!("Font: {} pt", dom.attr(k, "w:val").and_then(|v| v.parse::<f64>().ok()).map(|v| v / 2.0).unwrap_or(0.0)),
                "w:rFonts" => format!("Font: {}", dom.attr(k, "w:ascii").unwrap_or("")),
                "w:highlight" => "Highlight".to_string(),
                "w:vertAlign" => dom.attr(k, "w:val").unwrap_or("").to_string(),
                "w:rStyle" => format!("Style: {}", dom.attr(k, "w:val").unwrap_or("")),
                _ => continue,
            };
            parts.push(word);
        }
        if parts.is_empty() {
            "Font".to_string()
        } else {
            parts.join(", ")
        }
    }

    /// A new revision id (w:id) not used in the document.
    pub(crate) fn rev_id(&mut self) -> String {
        if self.rev_next == 0 {
            let dom = &self.doc.dom;
            let mut max = 0u64;
            let mut stack = vec![dom.root];
            stack.extend(self.doc.parts.iter().map(|p| p.root));
            while let Some(n) = stack.pop() {
                for c in dom.elements(n) {
                    if let Some(v) = dom.attr(c, "w:id").and_then(|v| v.parse::<u64>().ok()) {
                        max = max.max(v);
                    }
                    stack.push(c);
                }
            }
            self.rev_next = max + 1;
        }
        let v = self.rev_next;
        self.rev_next += 1;
        v.to_string()
    }

    pub(crate) fn rev_element(&mut self, name: &str) -> NodeId {
        let id = self.rev_id();
        let date = now_iso();
        let author = self.author.clone();
        self.doc.dom.new_element(name, &[("w:id", &id), ("w:author", &author), ("w:date", &date)])
    }

    /// The tracked-change wrapper (w:ins / w:del...) `n` is in, up to its
    /// paragraph.
    fn change_wrapper(&self, n: NodeId) -> Option<NodeId> {
        let dom = &self.doc.dom;
        let mut c = dom.parent(n)?;
        loop {
            if matches!(dom.name(c), "w:ins" | "w:del" | "w:moveTo" | "w:moveFrom") {
                return Some(c);
            }
            if dom.is(c, "w:p") {
                return None;
            }
            c = dom.parent(c)?;
        }
    }

    fn is_mine(&self, wrapper: NodeId, name: &str) -> bool {
        let dom = &self.doc.dom;
        dom.is(wrapper, name) && dom.attr(wrapper, "w:author").unwrap_or("") == self.author
    }

    /// Is `n` text this author inserted while tracking (so it can simply go)?
    pub(crate) fn in_my_ins(&self, n: NodeId) -> bool {
        self.change_wrapper(n).map_or(false, |w| self.is_mine(w, "w:ins"))
    }

    /// Where a new tracked run goes for the slot (parent, idx): inside an
    /// insertion of this author (next to it, or a new one).
    pub(crate) fn ins_slot(&mut self, mut parent: NodeId, mut idx: usize) -> (NodeId, usize) {
        if self.is_mine(parent, "w:ins") {
            return (parent, idx);
        }
        // out of another reviewer's insertion (split it)
        loop {
            let dom = &self.doc.dom;
            if !matches!(dom.name(parent), "w:ins" | "w:moveTo" | "w:del" | "w:moveFrom") {
                break;
            }
            let up = dom.parent(parent).unwrap();
            let n = dom.children(parent).len();
            if idx == 0 {
                idx = dom.index_in_parent(parent).unwrap();
            } else if idx >= n {
                idx = dom.index_in_parent(parent).unwrap() + 1;
            } else {
                let child = dom.children(parent)[idx];
                self.split_element_before(parent, child);
                idx = self.doc.dom.index_in_parent(parent).unwrap();
            }
            parent = up;
        }
        let dom = &self.doc.dom;
        if idx > 0 {
            let prev = dom.children(parent)[idx - 1];
            if self.is_mine(prev, "w:ins") {
                return (prev, dom.children(prev).len());
            }
        }
        if let Some(&next) = dom.children(parent).get(idx) {
            if self.is_mine(next, "w:ins") {
                return (next, 0);
            }
        }
        let ins = self.rev_element("w:ins");
        self.doc.dom.insert(parent, idx, ins);
        (ins, 0)
    }

    /// Tracked deletion of [s, e) of paragraph p: text this author inserted
    /// goes; other text is marked deleted.
    pub(crate) fn track_delete(&mut self, p: NodeId, s: usize, e: usize) {
        if e <= s {
            return;
        }
        let runs = self.runs_in(p, s, e);
        let mut last_del: Option<NodeId> = None;
        for r in runs {
            if self.doc.dom.parent(r).is_none() {
                continue;
            }
            match self.change_wrapper(r) {
                Some(w) if matches!(self.doc.dom.name(w), "w:del" | "w:moveFrom") => continue,
                Some(w) if self.is_mine(w, "w:ins") => {
                    self.remove_run(r);
                    continue;
                }
                _ => {}
            }
            // the text becomes deleted text
            for k in self.doc.dom.elements(r).collect::<Vec<_>>() {
                match self.doc.dom.name(k) {
                    "w:t" => {
                        rename(&mut self.doc.dom, k, "w:delText");
                    }
                    "w:instrText" => {
                        rename(&mut self.doc.dom, k, "w:delInstrText");
                    }
                    _ => {}
                }
            }
            let dom = &self.doc.dom;
            let parent = dom.parent(r).unwrap();
            let idx = dom.index_in_parent(r).unwrap();
            // join the deletion just made, or one of this author just before
            let prev = if idx > 0 { Some(dom.children(parent)[idx - 1]) } else { None };
            let target = match prev {
                Some(pv) if Some(pv) == last_del || (self.is_mine(pv, "w:del")) => pv,
                _ => {
                    let d = self.rev_element("w:del");
                    self.doc.dom.insert(parent, idx, d);
                    d
                }
            };
            self.doc.dom.detach(r);
            self.doc.dom.append(target, r);
            last_del = Some(target);
        }
    }

    /// Tracked deletion from a to b across paragraphs: their text, and the
    /// paragraph marks between them.
    pub(crate) fn track_delete_across(&mut self, a: Pos, b: Pos) {
        let paras = self.paras_between(a.para, b.para);
        for &p in &paras {
            let len = self.fresh_len(p);
            let s = if p == a.para { a.off } else { 0 };
            let e = if p == b.para { b.off } else { len };
            self.track_delete(p, s, e);
        }
        // rows wholly inside the deletion are deleted rows
        let rows: Vec<NodeId> = {
            let dom = &self.doc.dom;
            let mut v: Vec<NodeId> = Vec::new();
            for &p in &paras {
                if let Some(tr) = dom.parent(p).and_then(|tc| dom.parent(tc)).filter(|&t| dom.is(t, "w:tr")) {
                    if !v.contains(&tr) {
                        v.push(tr);
                    }
                }
            }
            v
        };
        for tr in rows {
            let dom = &self.doc.dom;
            let mut all = true;
            let mut stack = vec![tr];
            while let Some(n) = stack.pop() {
                for k in dom.elements(n) {
                    if dom.is(k, "w:p") {
                        if !paras.contains(&k) || k == a.para && a.off > 0 || k == b.para {
                            all = false;
                        }
                    } else {
                        stack.push(k);
                    }
                }
            }
            if all {
                self.mark_row(tr, "w:del");
            }
        }
        let mut caret = a;
        for w in paras.windows(2).rev() {
            let (p, next) = (w[0], w[1]);
            let dom = &self.doc.dom;
            if dom.parent(p) != dom.parent(next) || dom.parent(p).is_none() {
                continue;
            }
            let own = self.mark_change(p, "w:ins").map_or(false, |m| self.is_mine(m, "w:ins"));
            if own {
                // a paragraph this author made: join for real
                self.merge_into(p, next, true);
                if caret.para == p {
                    caret.para = next;
                }
            } else {
                self.mark_para(p, "w:del");
            }
        }
        // a paragraph now wholly gone from view: the caret goes on
        if self.hides_deletions() && self.fresh_len(caret.para) == 0
            && self.mark_change(caret.para, "w:del").is_some() && self.doc.dom.parent(b.para).is_some() {
            caret = Pos { para: b.para, off: 0 };
        }
        self.caret = caret;
        self.anchor = caret;
    }

    /// Mark a table row inserted / deleted (w:trPr/w:ins|del).
    pub(crate) fn mark_row(&mut self, tr: NodeId, name: &str) {
        let dom = &mut self.doc.dom;
        let pr = ensure_child_first(dom, tr, "w:trPr");
        if dom.child(pr, name).is_some() {
            return;
        }
        let el = self.rev_element(name);
        let dom = &mut self.doc.dom;
        // ins and del come after the other row properties, before trPrChange
        let idx = dom.elements(pr).position(|k| matches!(dom.name(k), "w:trPrChange") || (name == "w:ins" && dom.is(k, "w:del")))
            .map(|i| dom.index_in_parent(dom.elements(pr).nth(i).unwrap()).unwrap())
            .unwrap_or(dom.children(pr).len());
        dom.insert(pr, idx, el);
    }

    /// Tracked deletion of a whole row: a row this author inserted goes;
    /// others are marked deleted with their text.
    pub(crate) fn track_delete_row(&mut self, tr: NodeId) {
        let dom = &self.doc.dom;
        let own = dom.child(tr, "w:trPr").and_then(|p| dom.child(p, "w:ins")).map_or(false, |m| self.is_mine(m, "w:ins"));
        if own {
            let tbl = self.doc.dom.parent(tr);
            self.doc.dom.detach(tr);
            if let Some(t) = tbl {
                if !self.doc.dom.elements(t).any(|k| self.doc.dom.is(k, "w:tr")) {
                    self.doc.dom.detach(t);
                }
            }
            return;
        }
        let paras: Vec<NodeId> = {
            let dom = &self.doc.dom;
            let mut v = Vec::new();
            let mut stack = vec![tr];
            while let Some(n) = stack.pop() {
                for k in dom.elements(n).collect::<Vec<_>>().into_iter().rev() {
                    if dom.is(k, "w:p") { v.push(k) } else { stack.push(k) }
                }
            }
            v
        };
        for p in paras {
            let len = self.fresh_len(p);
            self.track_delete(p, 0, len);
        }
        self.mark_row(tr, "w:del");
    }

    /// Remove a run and the wrappers it leaves empty.
    pub(crate) fn remove_run(&mut self, r: NodeId) {
        let mut node = r;
        loop {
            let par = self.doc.dom.parent(node);
            self.doc.dom.detach(node);
            match par {
                Some(par) if matches!(self.doc.dom.name(par), "w:ins" | "w:del" | "w:hyperlink" | "w:smartTag")
                    && self.doc.dom.elements(par).next().is_none() => node = par,
                _ => break,
            }
        }
    }

    /// The paragraph mark's run properties (w:pPr/w:rPr), created if missing.
    pub(crate) fn mark_rpr(&mut self, p: NodeId) -> NodeId {
        let dom = &mut self.doc.dom;
        let ppr = ensure_child_first(dom, p, "w:pPr");
        if let Some(r) = dom.child(ppr, "w:rPr") {
            return r;
        }
        let rank = PPR_ORDER.iter().position(|x| *x == "w:rPr").unwrap();
        let n = dom.new_element("w:rPr", &[]);
        let mut idx = dom.children(ppr).len();
        for k in dom.elements(ppr).collect::<Vec<_>>() {
            if PPR_ORDER.iter().position(|x| *x == dom.name(k)).unwrap_or(PPR_ORDER.len()) > rank {
                idx = dom.index_in_parent(k).unwrap();
                break;
            }
        }
        dom.insert(ppr, idx, n);
        n
    }

    /// The paragraph mark's change marker (w:ins / w:del) if any.
    pub(crate) fn mark_change(&self, p: NodeId, name: &str) -> Option<NodeId> {
        let dom = &self.doc.dom;
        let rpr = dom.child(p, "w:pPr").and_then(|pp| dom.child(pp, "w:rPr"))?;
        dom.child(rpr, name)
    }

    /// Mark the paragraph mark of `p` inserted / deleted.
    pub(crate) fn mark_para(&mut self, p: NodeId, name: &str) {
        if self.mark_change(p, name).is_some() {
            return;
        }
        let rpr = self.mark_rpr(p);
        let el = self.rev_element(name);
        // ins comes before del
        let idx = if name == "w:del" && self.doc.dom.child(rpr, "w:ins").is_some() { 1 } else { 0 };
        self.doc.dom.insert(rpr, idx, el);
    }

    /// Before changing a run's formatting with tracking on: keep what it
    /// was (w:rPrChange), unless it is this author's insertion or already
    /// recorded.
    pub(crate) fn track_rpr(&mut self, r: NodeId) {
        if self.in_my_ins(r) {
            return;
        }
        let dom = &mut self.doc.dom;
        let rpr = ensure_child_first(dom, r, "w:rPr");
        if dom.child(rpr, "w:rPrChange").is_some() {
            return;
        }
        let old = dom.new_element("w:rPr", &[]);
        for k in dom.elements(rpr).collect::<Vec<_>>() {
            if !matches!(dom.name(k), "w:ins" | "w:del" | "w:moveFrom" | "w:moveTo") {
                let c = dom.clone_node(k);
                dom.append(old, c);
            }
        }
        let ch = self.rev_element("w:rPrChange");
        let dom = &mut self.doc.dom;
        dom.append(ch, old);
        dom.append(rpr, ch);
    }

    /// Before changing a paragraph's formatting with tracking on.
    pub(crate) fn track_ppr(&mut self, p: NodeId) {
        if !self.tracking() {
            return;
        }
        if self.mark_change(p, "w:ins").map_or(false, |m| self.is_mine(m, "w:ins")) {
            return;
        }
        let dom = &mut self.doc.dom;
        let ppr = ensure_child_first(dom, p, "w:pPr");
        if dom.child(ppr, "w:pPrChange").is_some() {
            return;
        }
        let old = dom.new_element("w:pPr", &[]);
        for k in dom.elements(ppr).collect::<Vec<_>>() {
            if !matches!(dom.name(k), "w:rPr" | "w:sectPr" | "w:pPrChange") {
                let c = dom.clone_node(k);
                dom.append(old, c);
            }
        }
        let ch = self.rev_element("w:pPrChange");
        let dom = &mut self.doc.dom;
        dom.append(ch, old);
        dom.append(ppr, ch);
    }

    // ------------------------------------------------------------ listing
    fn para_of(&self, n: NodeId) -> Option<NodeId> {
        let dom = &self.doc.dom;
        let mut c = n;
        loop {
            if dom.is(c, "w:p") {
                return Some(c);
            }
            c = dom.parent(c)?;
        }
    }

    fn is_within(&self, n: NodeId, anc: NodeId) -> bool {
        let dom = &self.doc.dom;
        let mut c = Some(n);
        while let Some(x) = c {
            if x == anc {
                return true;
            }
            c = dom.parent(x);
        }
        false
    }

    /// The text span of `node`'s content in paragraph `p`.
    fn span_in(&self, p: NodeId, node: NodeId) -> (usize, usize) {
        let mut lo = usize::MAX;
        let mut hi = 0;
        let mut total = 0;
        for (pc, s, e) in self.pieces(p) {
            total = e;
            if let Some(n) = pc.node {
                if self.is_within(n, node) {
                    lo = lo.min(s);
                    hi = hi.max(e);
                }
            }
        }
        if lo == usize::MAX {
            (total, total)
        } else {
            (lo, hi)
        }
    }

    pub(crate) fn fresh_len(&self, p: NodeId) -> usize {
        self.pieces(p).last().map_or(0, |(_, _, e)| *e)
    }

    /// The tracked changes under `root`, in document order.
    pub fn changes_in(&self, root: NodeId) -> Vec<Change> {
        let mut out = Vec::new();
        self.collect_changes(root, &mut out);
        out
    }

    fn collect_changes(&self, n: NodeId, out: &mut Vec<Change>) {
        let dom = &self.doc.dom;
        for c in dom.elements(n) {
            let name = dom.name(c);
            let parent_name = dom.name(n);
            let kind = match name {
                "w:ins" | "w:moveTo" | "w:del" | "w:moveFrom" => {
                    let ins = matches!(name, "w:ins" | "w:moveTo");
                    if parent_name == "w:rPr" {
                        let pp = dom.parent(n);
                        if pp.map_or(false, |pp| dom.is(pp, "w:pPr")) {
                            Some(if ins { ChangeKind::ParaInsert } else { ChangeKind::ParaDelete })
                        } else {
                            None
                        }
                    } else if parent_name == "w:trPr" {
                        Some(if ins { ChangeKind::RowInsert } else { ChangeKind::RowDelete })
                    } else if dom.elements(c).next().is_some() {
                        Some(if ins { ChangeKind::Insert } else { ChangeKind::Delete })
                    } else {
                        None
                    }
                }
                "w:rPrChange" => Some(ChangeKind::Format),
                "w:pPrChange" => Some(ChangeKind::ParaFormat),
                _ if PROP_CHANGES.iter().any(|(k, _)| *k == name) => Some(ChangeKind::PropFormat),
                _ => None,
            };
            if let Some(kind) = kind {
                let author = dom.attr(c, "w:author").unwrap_or("").to_string();
                let date = dom.attr(c, "w:date").unwrap_or("").to_string();
                let para = match kind {
                    ChangeKind::RowInsert | ChangeKind::RowDelete | ChangeKind::PropFormat => {
                        // the first paragraph of what it belongs to
                        let owner = dom.parent(n).unwrap_or(n);
                        if dom.is(owner, "w:p") { Some(owner) } else { first_para(dom, owner) }
                    }
                    _ => self.para_of(c),
                };
                let (start, end) = match (kind, para) {
                    (_, None) => (0, 0),
                    (ChangeKind::ParaInsert | ChangeKind::ParaDelete, Some(p)) => {
                        let l = self.fresh_len(p);
                        (l, l)
                    }
                    (ChangeKind::ParaFormat, Some(p)) => (0, self.fresh_len(p)),
                    (ChangeKind::Format, Some(p)) => {
                        let run = dom.parent(n).filter(|&r| dom.is(r, "w:r"));
                        match run {
                            Some(r) => self.span_in(p, r),
                            None => {
                                let l = self.fresh_len(p);
                                (l, l)
                            }
                        }
                    }
                    (ChangeKind::Insert | ChangeKind::Delete, Some(p)) => self.span_in(p, c),
                    (_, Some(p)) => (0, self.fresh_len(p)),
                };
                out.push(Change { kind, node: c, author, date, para, start, end });
                if !matches!(kind, ChangeKind::Insert | ChangeKind::Delete) {
                    continue;
                }
            }
            self.collect_changes(c, out);
        }
    }

    /// Every tracked change: the body, then headers, footers and notes.
    pub fn all_changes(&self) -> Vec<Change> {
        let mut out = self.changes_in(self.doc.body);
        for part in &self.doc.parts {
            if matches!(part.kind, "comments" | "commentsExtended") {
                continue;
            }
            out.extend(self.changes_in(part.root));
        }
        out
    }

    /// The root of the story the caret is in.
    fn caret_root(&self) -> NodeId {
        let dom = &self.doc.dom;
        let mut c = self.caret.para;
        while let Some(p) = dom.parent(c) {
            if p == self.doc.body {
                return p;
            }
            c = p;
        }
        c
    }

    fn change_pos(&self, c: &Change) -> Option<(Pos, Pos)> {
        let p = c.para?;
        Some((Pos { para: p, off: c.start }, Pos { para: p, off: c.end }))
    }

    /// The changes touching the selection (or at the caret).
    fn selected_changes(&self) -> Vec<Change> {
        let (a, b) = self.selection();
        let root = self.caret_root();
        let found: Vec<Change> = self.changes_in(root)
            .into_iter()
            .filter(|c| {
                let Some((s, e)) = self.change_pos(c) else { return false };
                if self.pidx(&s.para).is_none() {
                    return false;
                }
                if a == b {
                    // at the caret: in or at the edges of the change
                    s.para == a.para && s.off <= a.off && a.off <= e.off
                } else {
                    self.cmp(s, b).is_lt() && self.cmp(a, e).is_lt()
                        || (s == e && self.cmp(a, s).is_le() && self.cmp(s, b).is_le())
                }
            })
            .collect();
        if a != b || found.len() <= 1 {
            return found;
        }
        // at a caret, one change: the one around it, else the first touching it
        let inside = found.iter().find(|c| c.start < a.off && a.off < c.end).cloned();
        vec![inside.unwrap_or_else(|| found[0].clone())]
    }

    // ------------------------------------------------- accept and reject
    fn resolve(&mut self, c: &Change, accept: bool) {
        let dom = &self.doc.dom;
        if dom.parent(c.node).is_none() {
            return;
        }
        let keep = accept == c.kind.is_insert();
        match c.kind {
            ChangeKind::Insert | ChangeKind::Delete => {
                if keep {
                    // the text stays: deleted text comes back as text
                    if c.kind == ChangeKind::Delete {
                        for k in self.doc.dom.elements(c.node).collect::<Vec<_>>() {
                            self.restore_text(k);
                        }
                    }
                    unwrap(&mut self.doc.dom, c.node);
                } else {
                    let dom = &mut self.doc.dom;
                    let par = dom.parent(c.node);
                    dom.detach(c.node);
                    // a wrapper left empty goes too
                    if let Some(par) = par {
                        if matches!(dom.name(par), "w:ins" | "w:del" | "w:hyperlink" | "w:smartTag")
                            && dom.elements(par).next().is_none() {
                            dom.detach(par);
                        }
                    }
                }
            }
            ChangeKind::ParaInsert | ChangeKind::ParaDelete => {
                self.doc.dom.detach(c.node);
                if !keep {
                    // the mark goes: join the next paragraph
                    if let Some(p) = c.para {
                        let dom = &self.doc.dom;
                        let next = dom.parent(p).and_then(|par| {
                            let i = dom.index_in_parent(p)?;
                            dom.children(par).get(i + 1).copied()
                        });
                        if let Some(nx) = next.filter(|&n| dom.is(n, "w:p")) {
                            self.merge_into(p, nx, true);
                        }
                    }
                }
            }
            ChangeKind::RowInsert | ChangeKind::RowDelete => {
                let row = self.doc.dom.parent(c.node).and_then(|tr| self.doc.dom.parent(tr));
                self.doc.dom.detach(c.node);
                if !keep {
                    if let Some(row) = row {
                        let tbl = self.doc.dom.parent(row);
                        self.doc.dom.detach(row);
                        // a table with no rows left goes
                        if let Some(t) = tbl {
                            if !self.doc.dom.elements(t).any(|k| self.doc.dom.is(k, "w:tr")) {
                                self.doc.dom.detach(t);
                            }
                        }
                    }
                }
            }
            ChangeKind::Format | ChangeKind::ParaFormat | ChangeKind::PropFormat => {
                let dom = &mut self.doc.dom;
                let props = dom.parent(c.node).unwrap();
                if !accept {
                    let name = dom.name(c.node).to_string();
                    let inner_name = PROP_CHANGES.iter().find(|(k, _)| *k == name).map(|(_, v)| *v).unwrap_or("");
                    let inner = dom.child(c.node, inner_name);
                    // what isn't part of the recorded properties stays
                    let stays = |n: &str| match name.as_str() {
                        "w:pPrChange" => matches!(n, "w:rPr" | "w:sectPr"),
                        "w:rPrChange" => matches!(n, "w:ins" | "w:del" | "w:moveFrom" | "w:moveTo"),
                        "w:sectPrChange" => matches!(n, "w:headerReference" | "w:footerReference" | "w:footnotePr" | "w:endnotePr"),
                        "w:tcPrChange" => matches!(n, "w:cellIns" | "w:cellDel" | "w:cellMerge"),
                        "w:trPrChange" => matches!(n, "w:ins" | "w:del"),
                        _ => false,
                    };
                    for k in dom.elements(props).collect::<Vec<_>>() {
                        if k != c.node && !stays(dom.name(k)) {
                            dom.detach(k);
                        }
                    }
                    if let Some(inner) = inner {
                        // the old properties go first (the kept ones, as
                        // rPr / sectPr, come after them in the schema), but
                        // a paragraph mark's ins/del lead its rPr
                        let mut idx = if name == "w:rPrChange" {
                            dom.elements(props).take_while(|&k| matches!(dom.name(k), "w:ins" | "w:del" | "w:moveFrom" | "w:moveTo")).count()
                        } else if name == "w:sectPrChange" {
                            dom.elements(props).take_while(|&k| matches!(dom.name(k), "w:headerReference" | "w:footerReference")).count()
                        } else {
                            0
                        };
                        for k in dom.children(inner).to_vec() {
                            // change marks were kept where they are
                            if stays(dom.name(k)) {
                                continue;
                            }
                            dom.detach(k);
                            dom.insert(props, idx, k);
                            idx += 1;
                        }
                    }
                }
                dom.detach(c.node);
                if dom.children(props).is_empty() && matches!(dom.name(props), "w:rPr" | "w:pPr") {
                    dom.detach(props);
                }
            }
        }
    }

    fn restore_text(&mut self, k: NodeId) {
        match self.doc.dom.name(k) {
            "w:delText" => {
                rename(&mut self.doc.dom, k, "w:t");
            }
            "w:delInstrText" => {
                rename(&mut self.doc.dom, k, "w:instrText");
            }
            _ => {}
        }
    }

    /// Accept or reject the changes in the selection (or at the caret).
    /// Returns how many there were.
    pub fn accept_reject(&mut self, accept: bool) -> usize {
        let changes = self.selected_changes();
        if changes.is_empty() {
            return 0;
        }
        let start = self.change_pos(&changes[0]).map(|p| p.0);
        self.begin();
        for c in changes.iter().rev() {
            self.resolve(c, accept);
        }
        if let Some(s) = start {
            if self.doc.dom.parent(s.para).is_some() {
                let s = Pos { para: s.para, off: s.off.min(self.fresh_len(s.para)) };
                self.caret = s;
                self.anchor = s;
            }
        }
        self.commit(if accept { "Accept Change" } else { "Reject Change" }, false);
        changes.len()
    }

    /// Accept or reject every change (or only those of `authors`).
    pub fn accept_reject_all(&mut self, accept: bool, authors: Option<&[String]>) -> usize {
        let changes: Vec<Change> = self.all_changes().into_iter()
            .filter(|c| authors.map_or(true, |a| a.iter().any(|x| *x == c.author)))
            .collect();
        if changes.is_empty() {
            return 0;
        }
        self.begin();
        for c in changes.iter().rev() {
            self.resolve(c, accept);
        }
        if authors.is_none() {
            // the ends of moves mean nothing now
            let mut roots = vec![self.doc.body];
            roots.extend(self.doc.parts.iter().map(|p| p.root));
            for root in roots {
                let mut stack = vec![root];
                let mut gone = Vec::new();
                while let Some(n) = stack.pop() {
                    for c in self.doc.dom.elements(n) {
                        if matches!(self.doc.dom.name(c), "w:moveFromRangeStart" | "w:moveFromRangeEnd"
                            | "w:moveToRangeStart" | "w:moveToRangeEnd") {
                            gone.push(c);
                        } else {
                            stack.push(c);
                        }
                    }
                }
                for g in gone {
                    self.doc.dom.detach(g);
                }
            }
        }
        // the caret's paragraph may have been joined away
        if self.doc.dom.parent(self.caret.para).is_none() || self.doc.dom.parent(self.anchor.para).is_none() {
            let first = self.doc.dom.elements(self.doc.body).find(|&k| self.doc.dom.is(k, "w:p"));
            if let Some(f) = first {
                self.caret = Pos { para: f, off: 0 };
                self.anchor = self.caret;
            }
        } else {
            let c = Pos { para: self.caret.para, off: self.caret.off.min(self.fresh_len(self.caret.para)) };
            self.caret = c;
            self.anchor = c;
        }
        self.commit(if accept { "Accept All Changes" } else { "Reject All Changes" }, false);
        changes.len()
    }

    /// Select the next (or previous) change. False when there is none.
    pub fn goto_change(&mut self, forward: bool) -> bool {
        let root = self.caret_root();
        let (a, b) = self.selection();
        let raw: Vec<(Pos, Pos)> = self.changes_in(root).iter()
            .filter_map(|c| self.change_pos(c))
            .filter(|(s, _)| self.pidx(&s.para).is_some())
            .collect();
        // neighbouring pieces of one edit count once
        let mut list: Vec<(Pos, Pos)> = Vec::new();
        for (s, e) in raw {
            if let Some(last) = list.last_mut() {
                if last.1 == s || last.0 == s {
                    if self.cmp(e, last.1).is_gt() {
                        last.1 = e;
                    }
                    continue;
                }
            }
            list.push((s, e));
        }
        let pick = if forward {
            list.iter().find(|(s, e)| self.cmp(*s, a).is_gt() || (self.cmp(*s, a).is_eq() && self.cmp(*e, b).is_gt() && a == b))
                .or_else(|| list.iter().find(|(s, _)| self.cmp(*s, b).is_ge() && *s != a))
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

    /// Accept / reject the change at the caret, then select the next one.
    pub fn accept_reject_next(&mut self, accept: bool) -> bool {
        self.accept_reject(accept);
        self.goto_change(true)
    }

    /// The changes as the app lists them: (kind, author, date, para index,
    /// start, end, text).
    pub fn change_list(&self) -> Vec<(String, String, String, Option<usize>, usize, usize, String)> {
        let mut out = Vec::new();
        for c in self.all_changes() {
            let idx = c.para.and_then(|p| self.layout.index.get(&p).copied());
            let text = match c.kind {
                ChangeKind::Insert | ChangeKind::Delete => self.doc.dom.text(c.node),
                ChangeKind::ParaInsert | ChangeKind::ParaDelete => "\u{b6}".to_string(),
                _ => String::new(),
            };
            out.push((c.kind.name().to_string(), c.author, c.date, idx, c.start, c.end, text));
        }
        out
    }

    /// Hidden-aware: does the display drop deleted text?
    pub(crate) fn hides_deletions(&self) -> bool {
        matches!(self.doc.markup, Markup::Simple | Markup::Final)
    }
}

fn first_para(dom: &XmlDoc, n: NodeId) -> Option<NodeId> {
    for c in dom.elements(n) {
        if dom.is(c, "w:p") {
            return Some(c);
        }
        if let Some(p) = first_para(dom, c) {
            return Some(p);
        }
    }
    None
}
