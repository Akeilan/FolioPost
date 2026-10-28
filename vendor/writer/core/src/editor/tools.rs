//! Smaller Home and Layout commands: breaks, Change Case, Sort, the Format
//! Painter, list formats, word count, and what Show/Hide ¶ labels.

use super::{ensure_child_first, Editor, Pos, PropEdit, Story, PPR_ORDER, RPR_ORDER};
use crate::document::Item;
use crate::xml::{NodeId, XmlDoc};
use std::collections::HashMap;

/// Copied formatting: run properties and (when a paragraph was picked up)
/// paragraph properties, kept in a document of their own.
pub struct Painter {
    dom: XmlDoc,
    rpr: Option<NodeId>,
    ppr: Option<NodeId>,
}

/// Word Count's figures.
#[derive(Clone, Debug, Default)]
pub struct Stats {
    pub pages: usize,
    pub words: usize,
    pub chars: usize,
    pub chars_spaces: usize,
    pub paras: usize,
    pub lines: usize,
}

/// Change Case's modes.
fn recase(text: &[char], mode: &str, start_sentence: bool) -> Vec<String> {
    let mut out = Vec::with_capacity(text.len());
    let mut sentence = start_sentence;
    let mut word_start = true;
    for (i, &c) in text.iter().enumerate() {
        let s: String = match mode {
            "upper" => c.to_uppercase().collect(),
            "lower" => c.to_lowercase().collect(),
            "toggle" => {
                if c.is_uppercase() {
                    c.to_lowercase().collect()
                } else {
                    c.to_uppercase().collect()
                }
            }
            "title" => {
                if word_start {
                    c.to_uppercase().collect()
                } else {
                    c.to_lowercase().collect()
                }
            }
            _ => {
                // sentence case: the first letter of each sentence capital
                if c.is_alphabetic() && sentence {
                    c.to_uppercase().collect()
                } else {
                    c.to_lowercase().collect()
                }
            }
        };
        if c.is_alphabetic() {
            sentence = false;
        } else if matches!(c, '.' | '!' | '?' | '\r') {
            sentence = true;
        }
        word_start = !(c.is_alphanumeric() || c == '\'' || c == '\u{2019}');
        let _ = i;
        out.push(s);
    }
    out
}

impl Editor {
    pub(super) fn in_table(&self, p: NodeId) -> bool {
        self.cell_of(p).is_some()
    }

    /// Layout > Breaks and Insert > Page Break: "page", "column",
    /// "textWrapping", or a section break "nextPage", "continuous",
    /// "evenPage", "oddPage". False where it can't go (a section break in
    /// a table, header or note).
    pub fn insert_break(&mut self, kind: &str) -> bool {
        match kind {
            "page" | "column" => {
                self.begin();
                self.delete_selection();
                let at = self.caret;
                let ch = if kind == "page" { "\u{c}" } else { "\u{e}" };
                self.insert_at(at.para, at.off, ch);
                if self.story == Story::Body && !self.in_table(at.para) {
                    // the text after the break starts a paragraph
                    let p = self.split_para(at.para, at.off + 1);
                    self.caret = Pos { para: p, off: 0 };
                } else {
                    self.caret = Pos { para: at.para, off: at.off + 1 };
                }
                self.anchor = self.caret;
                self.commit(if kind == "page" { "Page Break" } else { "Column Break" }, false);
                true
            }
            "textWrapping" => {
                self.type_text("\u{b}");
                true
            }
            "nextPage" | "continuous" | "evenPage" | "oddPage" => {
                if self.story != Story::Body || self.in_table(self.caret.para) {
                    return false;
                }
                let sec = self.current_section();
                self.begin();
                self.delete_selection();
                let at = self.caret;
                let sect = match self.doc.sections.get(sec).and_then(|s| s.node) {
                    Some(n) => n,
                    None => {
                        let dom = &mut self.doc.dom;
                        let sp = dom.new_element("w:sectPr", &[]);
                        let body = self.doc.body;
                        dom.append(body, sp);
                        sp
                    }
                };
                let second = self.split_para(at.para, at.off);
                let dom = &mut self.doc.dom;
                let Some(first) = dom.index_in_parent(second).and_then(|i| i.checked_sub(1))
                    .and_then(|i| dom.parent(second).and_then(|pp| dom.children(pp).get(i).copied())) else {
                    self.commit("Section Break", false);
                    return false;
                };
                // the first part ends a section like the one it was in
                let copy = dom.clone_node(sect);
                let ppr = ensure_child_first(dom, first, "w:pPr");
                let rank = PPR_ORDER.iter().position(|x| *x == "w:sectPr").unwrap();
                let mut idx = dom.children(ppr).len();
                for k in dom.elements(ppr).collect::<Vec<_>>() {
                    if PPR_ORDER.iter().position(|x| *x == dom.name(k)).unwrap_or(PPR_ORDER.len()) > rank {
                        idx = dom.index_in_parent(k).unwrap();
                        break;
                    }
                }
                dom.insert(ppr, idx, copy);
                // the part after the break starts the way asked
                let ty = match dom.child(sect, "w:type") {
                    Some(t) => t,
                    None => {
                        let t = dom.new_element("w:type", &[]);
                        // after the header/footer references and footnote/endnote properties
                        let pos = dom.children(sect).iter().position(|&k| {
                            !matches!(dom.name(k), "w:headerReference" | "w:footerReference" | "w:footnotePr" | "w:endnotePr")
                        }).unwrap_or(dom.children(sect).len());
                        dom.insert(sect, pos, t);
                        t
                    }
                };
                dom.set_attr(ty, "w:val", kind);
                self.caret = Pos { para: second, off: 0 };
                self.anchor = self.caret;
                self.commit("Section Break", false);
                true
            }
            _ => false,
        }
    }

    /// Insert > Blank Page: two page breaks, the caret on the new page.
    pub fn insert_blank_page(&mut self) -> bool {
        if self.story != Story::Body {
            return false;
        }
        self.begin_group("Blank Page");
        self.insert_break("page");
        let blank = self.caret;
        self.insert_break("page");
        self.end_group();
        if self.pidx(&blank.para).is_some() {
            self.move_to(Pos { para: blank.para, off: 0 }, false, false);
        }
        true
    }

    /// The paragraphs whose mark ends a section, with the kind of break
    /// (for Show/Hide ¶).
    pub fn section_break_labels(&self) -> HashMap<NodeId, String> {
        let mut out = HashMap::new();
        let dom = &self.doc.dom;
        let secs = &self.doc.sections;
        for k in 0..secs.len().saturating_sub(1) {
            let Some(sp) = secs[k].node else { continue };
            let Some(p) = dom.parent(sp).and_then(|ppr| dom.parent(ppr)) else { continue };
            let label = match secs[k + 1].start.as_str() {
                "continuous" => "Section Break (Continuous)",
                "evenPage" => "Section Break (Even Page)",
                "oddPage" => "Section Break (Odd Page)",
                "nextColumn" => "Section Break (Next Column)",
                _ => "Section Break (Next Page)",
            };
            out.insert(p, label.to_string());
        }
        out
    }

    /// The range a command works on: the selection, or the word at the caret.
    fn sel_or_word(&self) -> (Pos, Pos) {
        let (a, b) = self.selection();
        if a != b {
            return (a, b);
        }
        let (ws, we) = self.word_at(a);
        if ws.off <= a.off && a.off <= we.off && ws != we {
            (ws, we)
        } else {
            (a, b)
        }
    }

    /// Home > Change Case: "sentence", "lower", "upper", "title", "toggle".
    pub fn change_case(&mut self, mode: &str) -> bool {
        let (a, b) = self.sel_or_word();
        if a == b {
            return false;
        }
        // the text nodes touched, with the part of each in the range
        let mut segs: Vec<(NodeId, usize, usize)> = Vec::new();
        let mut text: Vec<char> = Vec::new();
        let paras = self.paras_between(a.para, b.para);
        for (i, p) in paras.iter().enumerate() {
            let s = if *p == a.para { a.off } else { 0 };
            let e = if *p == b.para { b.off } else { usize::MAX };
            for (pc, ps, pe) in self.pieces(*p) {
                let (Item::Text(t), Some(node)) = (&pc.item, pc.node) else { continue };
                if pc.change == "del" || !self.doc.dom.is(node, "w:t") || pe <= s || ps >= e {
                    continue;
                }
                let k0 = s.saturating_sub(ps);
                let k1 = (e.min(pe)) - ps;
                text.extend(t.chars().skip(k0).take(k1 - k0));
                segs.push((node, k0, k1));
            }
            if i + 1 < paras.len() {
                text.push('\r');
                segs.push((NodeId::MAX, 0, 1));
            }
        }
        if text.is_empty() {
            return false;
        }
        // a sentence starts here if nothing but space comes before it
        let start = a.off == 0 || {
            let pl = self.para_layout(a.para);
            pl.map(|pl| {
                let before: Vec<char> = Self::para_chars(pl).into_iter().filter(|(pos, _)| *pos < a.off).map(|(_, c)| c).collect();
                before.iter().rev().find(|c| !c.is_whitespace()).map_or(true, |c| matches!(c, '.' | '!' | '?'))
            }).unwrap_or(true)
        };
        let new = recase(&text, mode, start);
        self.begin();
        let mut k = 0;
        for (node, k0, k1) in segs {
            let n = k1 - k0;
            if node == NodeId::MAX {
                k += 1;
                continue;
            }
            let cur: Vec<char> = self.doc.dom.text(node).chars().collect();
            let mut s: String = cur[..k0].iter().collect();
            for x in &new[k..k + n] {
                s.push_str(x);
            }
            s.extend(cur[k1..].iter());
            k += n;
            self.set_t(node, &s);
        }
        self.commit("Change Case", false);
        true
    }

    /// Home > Sort: the selected paragraphs (or a table's rows) by their
    /// text; `numeric` compares numbers, `header` keeps a table's first row.
    /// What Sort Text works on: the table's rows (less a header row) or the
    /// selected sibling paragraphs.
    fn sort_targets(&self, header: bool) -> Option<(bool, Vec<NodeId>)> {
        let (a, b) = self.selection();
        let dom = &self.doc.dom;
        if let (Some((ta, _, _)), Some((tb, _, _))) = (self.cell_of(a.para), self.cell_of(b.para)) {
            let (tr, tr2) = (dom.parent(ta)?, dom.parent(tb)?);
            let (tbl, tbl2) = (dom.parent(tr)?, dom.parent(tr2)?);
            if tbl != tbl2 {
                return None;
            }
            let mut rows: Vec<NodeId> = dom.children_named(tbl, "w:tr").collect();
            if header && !rows.is_empty() {
                rows.remove(0);
            }
            return Some((true, rows));
        }
        let mut paras: Vec<NodeId> = self.paras_between(a.para, b.para);
        if b.off == 0 && paras.len() > 1 && a != b {
            paras.pop();
        }
        if a == b {
            let parent = dom.parent(a.para);
            paras = parent.map(|pp| dom.children_named(pp, "w:p").collect()).unwrap_or_default();
        }
        if paras.is_empty() {
            return None;
        }
        let parent = dom.parent(paras[0]);
        if paras.iter().any(|&p| dom.parent(p) != parent) {
            return None;
        }
        if header && paras.len() > 1 {
            paras.remove(0);
        }
        Some((false, paras))
    }

    /// Sort Text's items: each row's cell texts, or each paragraph's text.
    pub fn sort_items(&self, header: bool) -> Option<(bool, Vec<Vec<String>>)> {
        let (table, items) = self.sort_targets(header)?;
        let dom = &self.doc.dom;
        let out = items.iter().map(|&n| {
            if table {
                dom.children_named(n, "w:tc").map(|c| self.node_text(c)).collect()
            } else {
                vec![self.node_text(n)]
            }
        }).collect();
        Some((table, out))
    }

    /// Put Sort Text's items in this order (indices into sort_items).
    pub fn sort_apply(&mut self, order: &[usize], header: bool) -> bool {
        let Some((table, items)) = self.sort_targets(header) else { return false };
        if order.len() != items.len() || items.len() < 2 {
            return false;
        }
        let mut seen = vec![false; items.len()];
        for &i in order {
            if i >= items.len() || seen[i] {
                return false;
            }
            seen[i] = true;
        }
        let parent = match self.doc.dom.parent(items[0]) {
            Some(p) => p,
            None => return false,
        };
        self.begin();
        let dom = &mut self.doc.dom;
        let sect = if table {
            None
        } else {
            items.last().and_then(|&p| dom.child(p, "w:pPr")).and_then(|ppr| dom.child(ppr, "w:sectPr"))
        };
        if let Some(s) = sect {
            dom.detach(s);
        }
        let at = dom.index_in_parent(items[0]).unwrap_or(0);
        for &n in &items {
            dom.detach(n);
        }
        let mut last = items[0];
        for (k, &i) in order.iter().enumerate() {
            dom.insert(parent, at + k, items[i]);
            last = items[i];
        }
        if let Some(s) = sect {
            let ppr = ensure_child_first(dom, last, "w:pPr");
            dom.append(ppr, s);
        }
        self.commit("Sort", false);
        if !table {
            let f = items[order[0]];
            if self.pidx(&f).is_some() && self.pidx(&last).is_some() {
                let e = self.para_len(last);
                self.move_to(Pos { para: f, off: 0 }, false, false);
                self.move_to(Pos { para: last, off: e }, true, false);
            }
        }
        true
    }

    pub fn sort_paras(&mut self, descending: bool, numeric: bool, header: bool) -> bool {
        let (a, b) = self.selection();
        fn key_of(text: &str, numeric: bool) -> (u8, f64, String) {
            let t = text.trim().to_lowercase();
            if numeric {
                let num: String = t.chars().skip_while(|c| !c.is_ascii_digit() && *c != '-')
                    .take_while(|c| c.is_ascii_digit() || matches!(c, '.' | '-' | ','))
                    .filter(|c| *c != ',').collect();
                match num.parse::<f64>() {
                    Ok(v) => (1, v, t),
                    Err(_) => (if t.is_empty() { 0 } else { 2 }, 0.0, t),
                }
            } else {
                (if t.is_empty() { 0 } else { 1 }, 0.0, t)
            }
        }
        let cmp = |x: &(u8, f64, String), y: &(u8, f64, String)| {
            x.0.cmp(&y.0).then(x.1.partial_cmp(&y.1).unwrap_or(std::cmp::Ordering::Equal)).then(x.2.cmp(&y.2))
        };
        // in a table: its rows by the first column
        if let (Some((ta, _, _)), Some((tb, _, _))) = (self.cell_of(a.para), self.cell_of(b.para)) {
            let dom = &self.doc.dom;
            let (Some(tr), Some(tr2)) = (dom.parent(ta), dom.parent(tb)) else { return false };
            let (Some(tbl), Some(tbl2)) = (dom.parent(tr), dom.parent(tr2)) else { return false };
            if tbl != tbl2 {
                return false;
            }
            let mut rows: Vec<NodeId> = dom.children_named(tbl, "w:tr").collect();
            if header && !rows.is_empty() {
                rows.remove(0);
            }
            let mut keyed: Vec<((u8, f64, String), NodeId)> = rows.iter().map(|&r| {
                let cell = dom.children_named(r, "w:tc").next();
                (key_of(&cell.map(|c| self.node_text(c)).unwrap_or_default(), numeric), r)
            }).collect();
            keyed.sort_by(|x, y| cmp(&x.0, &y.0));
            if descending {
                keyed.reverse();
            }
            self.begin();
            let dom = &mut self.doc.dom;
            let at = rows.first().and_then(|&r| dom.index_in_parent(r)).unwrap_or(0);
            for &r in &rows {
                dom.detach(r);
            }
            for (i, (_, r)) in keyed.into_iter().enumerate() {
                dom.insert(tbl, at + i, r);
            }
            self.commit("Sort", false);
            return true;
        }
        // paragraphs: siblings in the body (or a cell)
        let paras: Vec<NodeId> = self.paras_between(a.para, b.para);
        let mut paras = paras;
        if b.off == 0 && paras.len() > 1 && a != b {
            paras.pop();
        }
        if paras.len() < 2 && a != b {
            return false;
        }
        if a == b {
            // no selection: the whole story's top-level paragraphs
            let parent = self.doc.dom.parent(a.para);
            paras = parent.map(|pp| self.doc.dom.children_named(pp, "w:p").collect()).unwrap_or_default();
        }
        let dom = &self.doc.dom;
        let parent = dom.parent(paras[0]);
        if paras.iter().any(|&p| dom.parent(p) != parent) {
            return false;
        }
        let Some(parent) = parent else { return false };
        let mut keyed: Vec<((u8, f64, String), NodeId)> =
            paras.iter().map(|&p| (key_of(&self.node_text(p), numeric), p)).collect();
        keyed.sort_by(|x, y| cmp(&x.0, &y.0));
        if descending {
            keyed.reverse();
        }
        self.begin();
        let dom = &mut self.doc.dom;
        // a section's properties stay on the last paragraph
        let sect = paras.last().and_then(|&p| dom.child(p, "w:pPr")).and_then(|ppr| dom.child(ppr, "w:sectPr"));
        if let Some(s) = sect {
            dom.detach(s);
        }
        let at = dom.index_in_parent(paras[0]).unwrap_or(0);
        let first_sel = keyed.first().map(|k| k.1);
        for &p in &paras {
            dom.detach(p);
        }
        let mut last = paras[0];
        for (i, (_, p)) in keyed.into_iter().enumerate() {
            dom.insert(parent, at + i, p);
            last = p;
        }
        if let Some(s) = sect {
            let ppr = ensure_child_first(dom, last, "w:pPr");
            dom.append(ppr, s);
        }
        let end_len = self.node_text(last).chars().count();
        self.commit("Sort", false);
        if let Some(f) = first_sel {
            if self.pidx(&f).is_some() && self.pidx(&last).is_some() {
                let e = self.para_len(last).min(end_len.max(self.para_len(last)));
                self.move_to(Pos { para: f, off: 0 }, false, false);
                self.move_to(Pos { para: last, off: e }, true, false);
            }
        }
        true
    }

    /// The plain text of an element (deleted text left out).
    fn node_text(&self, n: NodeId) -> String {
        let dom = &self.doc.dom;
        let mut out = String::new();
        fn walk(dom: &XmlDoc, n: NodeId, out: &mut String) {
            for &c in dom.children(n) {
                match dom.name(c) {
                    "w:t" => out.push_str(&dom.text(c)),
                    "w:tab" => out.push('\t'),
                    "w:del" | "w:delText" | "w:instrText" | "w:pPr" | "w:rPr" => {}
                    "w:p" => {
                        if !out.is_empty() {
                            out.push(' ');
                        }
                        walk(dom, c, out);
                    }
                    _ => walk(dom, c, out),
                }
            }
        }
        walk(dom, n, &mut out);
        out
    }

    // ------------------------------------------------------------ painter
    /// Format Painter, picking up: the formatting at the caret (or the
    /// start of the selection), and the paragraph's when the selection is
    /// empty or takes in the paragraph mark.
    pub fn copy_format(&mut self) {
        let (a, b) = self.selection();
        let mut dom = XmlDoc::with_root("x", &[("xmlns:w", crate::document::W_NS)]);
        // the run at the start (just inside a selection, else before the caret)
        let off = if a == b {
            // at the start of a word: that word's format, else the character before
            let t: Vec<char> = self.node_text(a.para).chars().collect();
            let here = t.get(a.off).is_some_and(|c| c.is_alphanumeric());
            let before = a.off > 0 && t.get(a.off - 1).is_some_and(|c| c.is_alphanumeric());
            if here && !before { a.off } else { a.off.saturating_sub(1) }
        } else {
            a.off
        };
        let src = &self.doc.dom;
        let run = self.pieces(a.para).into_iter()
            .find(|(pc, s, e)| pc.run.is_some() && *s <= off && (off < *e || *e == *s && *s == off))
            .and_then(|(pc, _, _)| pc.run)
            .or_else(|| self.pieces(a.para).into_iter().find_map(|(pc, _, _)| pc.run));
        let rpr = match run.and_then(|r| src.child(r, "w:rPr")) {
            Some(r) => Some(dom.import_node(src, r)),
            None => src.child(a.para, "w:pPr").and_then(|ppr| src.child(ppr, "w:rPr")).map(|r| dom.import_node(src, r)),
        };
        let whole = a == b || a.para != b.para || (a.off == 0 && b.off >= self.para_len(b.para));
        let ppr = if whole { src.child(a.para, "w:pPr").map(|p| dom.import_node(src, p)) } else { None };
        let ppr = ppr.or_else(|| if whole { Some(dom.new_element("w:pPr", &[])) } else { None });
        self.painter = Some(Painter { dom, rpr, ppr });
    }

    pub fn has_format(&self) -> bool {
        self.painter.is_some()
    }

    pub fn clear_format(&mut self) {
        self.painter = None;
    }

    /// Apply the copied formatting to the selection (or the word at the
    /// caret). Returns false with nothing copied.
    pub fn paste_format(&mut self) -> bool {
        let Some(pt) = self.painter.take() else { return false };
        let collapsed = !self.has_selection();
        let (a, b) = self.sel_or_word();
        self.begin();
        let paras = self.paras_between(a.para, b.para);
        for p in &paras {
            let len = self.para_len(*p);
            let s = if *p == a.para { a.off } else { 0 };
            let e = if *p == b.para { b.off } else { len };
            if e > s {
                let runs = self.runs_in(*p, s, e);
                for r in runs {
                    if self.tracking() {
                        self.track_rpr(r);
                    }
                    self.replace_props(r, "w:rPr", pt.rpr.map(|n| (&pt.dom, n)), &["w:rPrChange"], RPR_ORDER);
                }
            }
            if let Some(pp) = pt.ppr {
                if collapsed || a == b || paras.len() > 1 || (s == 0 && e >= len) {
                    self.track_ppr(*p);
                    self.replace_props(*p, "w:pPr", Some((&pt.dom, pp)), &["w:sectPr", "w:pPrChange", "w:rPr"], PPR_ORDER);
                }
            }
        }
        self.painter = Some(pt);
        self.commit("Format Painter", false);
        true
    }

    /// Replace the property element `name` of `parent` with a copy of
    /// `src`'s children, keeping the children named in `keep`.
    fn replace_props(&mut self, parent: NodeId, name: &str, src: Option<(&XmlDoc, NodeId)>, keep: &[&str], order: &[&str]) {
        let dom = &mut self.doc.dom;
        let pr = ensure_child_first(dom, parent, name);
        for k in dom.children(pr).to_vec() {
            if !keep.contains(&dom.name(k)) {
                dom.detach(k);
            }
        }
        let Some((sd, sn)) = src else { return };
        for &c in sd.children(sn) {
            if sd.name(c).is_empty() || keep.contains(&sd.name(c)) {
                continue;
            }
            let n = dom.import_node(sd, c);
            let rank = |nm: &str| order.iter().position(|x| *x == nm).unwrap_or(order.len());
            let my = rank(sd.name(c));
            let mut idx = dom.children(pr).len();
            for k in dom.elements(pr).collect::<Vec<_>>() {
                if rank(dom.name(k)) > my {
                    idx = dom.index_in_parent(k).unwrap();
                    break;
                }
            }
            dom.insert(pr, idx, n);
        }
    }

    // ------------------------------------------------------------- lists
    /// A numbering or bullet format from the libraries: the selected
    /// paragraphs get a new list whose current level shows `fmt`
    /// (decimal, upperLetter, lowerRoman, bullet...) as `text` ("%1." or
    /// the bullet character, in `font`).
    pub fn set_list_format(&mut self, fmt: &str, text: &str, font: Option<&str>) -> bool {
        self.set_list_format_from(fmt, text, font, None)
    }

    /// The same, numbering from `start`.
    pub fn set_list_format_from(&mut self, fmt: &str, text: &str, font: Option<&str>, start: Option<i64>) -> bool {
        let (a, b) = self.selection();
        let paras = self.paras_between(a.para, b.para);
        if paras.is_empty() {
            return false;
        }
        let lvl = self.doc.para_props(paras[0]).0.ilvl.unwrap_or(0).clamp(0, 8);
        let kind = if fmt == "bullet" { "bullet" } else { "number" };
        self.begin();
        let num = self.add_list_definition(kind);
        if num <= 0 {
            self.commit("Numbering", false);
            return false;
        }
        // the level's format and text
        if let Some(nd) = self.doc.num_dom.as_mut() {
            let root = nd.root;
            let abs_id = nd.children_named(root, "w:num")
                .find(|&n| nd.attr(n, "w:numId") == Some(&num.to_string()))
                .and_then(|n| nd.child(n, "w:abstractNumId")).and_then(|x| nd.attr(x, "w:val")).map(|s| s.to_string());
            let abs = nd.children_named(root, "w:abstractNum").find(|&x| nd.attr(x, "w:abstractNumId").map(|s| s.to_string()) == abs_id);
            if let Some(abs) = abs {
                let lv = nd.children_named(abs, "w:lvl").find(|&l| nd.attr(l, "w:ilvl") == Some(&lvl.to_string()));
                if let Some(lv) = lv {
                    let k = |nd: &XmlDoc, name: &str| nd.child(lv, name);
                    if let Some(f) = k(nd, "w:numFmt") {
                        nd.set_attr(f, "w:val", fmt);
                    }
                    if let Some(t) = k(nd, "w:lvlText") {
                        nd.set_attr(t, "w:val", text);
                    }
                    if let Some(st) = start {
                        match k(nd, "w:start") {
                            Some(x) => nd.set_attr(x, "w:val", &st.to_string()),
                            None => {
                                let x = nd.new_element("w:start", &[("w:val", &st.to_string())]);
                                nd.insert(lv, 0, x);
                            }
                        }
                    }
                    let roman = fmt.ends_with("Roman");
                    if let Some(j) = k(nd, "w:lvlJc") {
                        nd.set_attr(j, "w:val", if roman && fmt == "lowerRoman" { "right" } else { "left" });
                    }
                    if let Some(ppr) = k(nd, "w:pPr") {
                        if let Some(ind) = nd.child(ppr, "w:ind") {
                            nd.set_attr(ind, "w:hanging", if fmt == "lowerRoman" { "180" } else { "360" });
                        }
                    }
                    if let Some(r) = k(nd, "w:rPr") {
                        nd.detach(r);
                    }
                    if let Some(font) = font {
                        let r = nd.new_element("w:rPr", &[]);
                        let f = nd.new_element("w:rFonts", &[("w:ascii", font), ("w:hAnsi", font), ("w:hint", "default")]);
                        nd.append(r, f);
                        nd.append(lv, r);
                    }
                }
            }
            self.doc.reload_numbering();
            self.cache.clear();
        }
        let lp = self.list_paragraph_style();
        let default = self.doc.styles.default_para.clone();
        for p in &paras {
            let cur = self.doc.para_props(*p).0.ilvl.unwrap_or(lvl).max(0);
            self.set_num_pr(*p, Some((num, cur)));
            let style = self.doc.para_direct(*p).style;
            if (style.is_none() || style == default) && lp.is_some() {
                self.set_para_style_id(*p, lp.as_deref());
            }
        }
        self.commit(if kind == "bullet" { "Bullets" } else { "Numbering" }, false);
        true
    }

    /// Bullets/Numbering > None.
    pub fn remove_list(&mut self) -> bool {
        let (a, b) = self.selection();
        let paras = self.paras_between(a.para, b.para);
        if !paras.iter().any(|p| self.list_kind(*p).is_some()) {
            return false;
        }
        self.begin();
        let lp = self.list_paragraph_style();
        for p in &paras {
            if self.list_kind(*p).is_none() {
                continue;
            }
            let has_direct = self.doc.para_direct(*p).num_id.is_some();
            self.set_num_pr(*p, if has_direct { None } else { Some((0, 0)) });
            let style = self.doc.para_direct(*p).style;
            if style.is_some() && style == lp {
                self.set_para_style_id(*p, None);
            }
        }
        self.commit("Numbering", false);
        true
    }

    // -------------------------------------------------------------- go to
    /// The places Go To steps through for a kind: "Section", "Line",
    /// "Comment", "Footnote", "Endnote", "Table", "Graphic", "Equation",
    /// "Heading" (body order).
    pub fn goto_targets(&self, kind: &str) -> Vec<Pos> {
        let mut out = Vec::new();
        let body = self.layout.body_count.min(self.layout.paras.len());
        match kind {
            "Heading" => {
                return self.toc_headings(1, 9, None).into_iter().map(|(p, _, _)| Pos { para: p, off: 0 }).collect();
            }
            "Comment" => {
                return self.comments().into_iter().filter(|c| c.parent.is_none()).filter_map(|c| c.range.map(|r| r.0)).collect();
            }
            "Line" => {
                for pg in &self.layout.pages {
                    for pl in &pg.lines {
                        let p = &self.layout.paras[pl.para];
                        if let Some(l) = p.lines.get(pl.line) {
                            out.push(Pos { para: p.node, off: l.pos_start });
                        }
                    }
                }
                return out;
            }
            "Section" => {
                let mut last = usize::MAX;
                for i in 0..body {
                    let node = self.layout.paras[i].node;
                    let sec = self.doc.blocks.iter().find(|b| b.node == node).map(|b| b.section);
                    if let Some(sec) = sec {
                        if sec != last {
                            out.push(Pos { para: node, off: 0 });
                            last = sec;
                        }
                    }
                }
                return out;
            }
            _ => {}
        }
        let mut last_tbl = None;
        for i in 0..body {
            let pl = &self.layout.paras[i];
            if kind == "Table" {
                let tbl = self.cell_of(pl.node).and_then(|(tc, _, _)| {
                    let dom = &self.doc.dom;
                    dom.parent(tc).and_then(|tr| dom.parent(tr))
                });
                if tbl.is_some() && tbl != last_tbl {
                    out.push(Pos { para: pl.node, off: 0 });
                }
                last_tbl = tbl;
                continue;
            }
            let mut pos = 0;
            let mut in_field = false;
            for pc in &pl.pieces {
                if kind == "Field" {
                    // the start of each field's result
                    let f = pc.field.is_some();
                    if f && !in_field {
                        out.push(Pos { para: pl.node, off: pos });
                    }
                    in_field = f;
                    pos += pc.item.len();
                    continue;
                }
                let hit = match (&pc.item, kind) {
                    (Item::Object(..), "Graphic") | (Item::Anchor(Some(_)), "Graphic") => true,
                    (Item::Math(..), "Equation") => true,
                    (_, "Footnote") | (_, "Endnote") => pc.note.is_some_and(|n| {
                        self.doc.dom.is(n, if kind == "Footnote" { "w:footnote" } else { "w:endnote" })
                    }),
                    _ => false,
                };
                if hit {
                    out.push(Pos { para: pl.node, off: pos });
                }
                pos += pc.item.len();
            }
        }
        out
    }

    /// Go To: `what` is a number ("3"), a step ("+2", "-1") or empty (the
    /// next one); Page and Line count from 1. Bookmarks go by name.
    pub fn goto(&mut self, kind: &str, what: &str) -> bool {
        if self.story != Story::Body {
            self.edit_header_footer(None, false);
        }
        let what = what.trim();
        if kind == "Bookmark" {
            return self.goto_bookmark(what);
        }
        let cur_page = self.caret_page();
        let (targets, cur) = if kind == "Page" {
            let n = self.layout.pages.len();
            let firsts: Vec<Pos> = (0..n).filter_map(|i| {
                let pg = &self.layout.pages[i];
                let pl = pg.lines.iter().min_by(|a, b| a.y.partial_cmp(&b.y).unwrap())?;
                let p = &self.layout.paras[pl.para];
                Some(Pos { para: p.node, off: p.lines.get(pl.line).map(|l| l.pos_start).unwrap_or(0) })
            }).collect();
            (firsts, Some(cur_page))
        } else {
            let t = self.goto_targets(kind);
            let caret = self.caret;
            let cur = t.iter().rposition(|&p| self.cmp(p, caret).is_le());
            (t, cur)
        };
        if targets.is_empty() {
            return false;
        }
        let n = targets.len() as i64;
        let idx: i64 = if what.is_empty() {
            cur.map(|c| c as i64 + 1).unwrap_or(0)
        } else if let Some(r) = what.strip_prefix('+') {
            cur.map(|c| c as i64).unwrap_or(-1) + r.parse::<i64>().unwrap_or(1)
        } else if let Some(r) = what.strip_prefix('-') {
            cur.map(|c| c as i64).unwrap_or(0) - r.parse::<i64>().unwrap_or(1)
        } else {
            match what.parse::<i64>() {
                Ok(v) => v - 1,
                Err(_) => return false,
            }
        };
        let idx = idx.clamp(0, n - 1) as usize;
        let to = targets[idx];
        self.move_to(to, false, false);
        true
    }

    /// Find Previous / Next of a kind (the browse arrows).
    pub fn goto_prev(&mut self, kind: &str) -> bool {
        self.goto(kind, "-1")
    }

    // ------------------------------------------------------------- stats
    /// Review > Word Count: of the selection, or the whole body (with
    /// footnotes and endnotes when `notes`).
    pub fn stats(&self, notes: bool) -> Stats {
        let mut st = Stats { pages: self.layout.pages.len(), ..Default::default() };
        let (a, b) = self.selection();
        let count = |st: &mut Stats, text: &str| {
            st.words += text.split(|c: char| c.is_whitespace() || c == '\u{fffc}')
                .filter(|w| w.chars().any(|c| c.is_alphanumeric()))
                .count();
            st.chars += text.chars().filter(|c| !c.is_whitespace() && *c != '\u{fffc}').count();
            st.chars_spaces += text.chars().filter(|c| *c != '\n' && *c != '\u{fffc}').count();
        };
        if a != b {
            let text = self.selected_text();
            count(&mut st, &text);
            st.paras = text.split('\n').filter(|l| !l.trim().is_empty()).count();
            for p in self.paras_between(a.para, b.para) {
                if let Some(pl) = self.para_layout(p) {
                    let s = if p == a.para { a.off } else { 0 };
                    let e = if p == b.para { b.off } else { pl.text_len };
                    st.lines += pl.lines.iter().filter(|l| l.pos_end > s && l.pos_start < e.max(s + 1)).count();
                }
            }
            return st;
        }
        let body = self.layout.body_count.min(self.layout.paras.len());
        let range: Vec<usize> = if notes { (0..self.layout.paras.len()).collect() } else { (0..body).collect() };
        for i in range {
            let pl = &self.layout.paras[i];
            if i >= body {
                // header/footer paragraphs are laid out per page: only notes count
                let dom = &self.doc.dom;
                let mut n = pl.node;
                let mut is_note = false;
                while let Some(p) = dom.parent(n) {
                    if dom.is(p, "w:footnote") || dom.is(p, "w:endnote") {
                        is_note = true;
                        break;
                    }
                    n = p;
                }
                if !is_note {
                    continue;
                }
            }
            let text: String = Self::para_chars(pl).into_iter().map(|(_, c)| c).collect();
            count(&mut st, &text);
            if text.chars().any(|c| !c.is_whitespace()) {
                st.paras += 1;
            }
            if i < body && !pl.units.is_empty() {
                st.lines += pl.lines.len();
            }
        }
        st
    }
}

#[cfg(test)]
mod tests {
    use super::recase;

    fn rc(s: &str, m: &str) -> String {
        let v: Vec<char> = s.chars().collect();
        recase(&v, m, true).concat()
    }

    #[test]
    fn cases() {
        assert_eq!(rc("hELLO wORLD. AGAIN", "sentence"), "Hello world. Again");
        assert_eq!(rc("hello big world", "title"), "Hello Big World");
        assert_eq!(rc("AbC", "toggle"), "aBc");
        assert_eq!(rc("don't stop", "title"), "Don't Stop");
    }
}

impl Editor {
    /// The drop cap paragraph going with paragraph `p` (just before it, or
    /// `p` itself).
    fn drop_cap_of(&self, p: NodeId) -> Option<NodeId> {
        let dom = &self.doc.dom;
        let is_drop = |q: NodeId| dom.is(q, "w:p") && dom.child(q, "w:pPr").and_then(|pp| dom.child(pp, "w:framePr"))
            .is_some_and(|f| matches!(dom.attr(f, "w:dropCap"), Some("drop" | "margin")));
        if is_drop(p) {
            return Some(p);
        }
        let parent = dom.parent(p)?;
        let i = dom.index_in_parent(p)?;
        let prev = *dom.children(parent).get(i.checked_sub(1)?)?;
        is_drop(prev).then_some(prev)
    }

    /// Insert > Drop Cap: "none", "drop" or "margin", over `lines` lines,
    /// `dist` twips from the text, in `font` (None: the text's).
    pub fn set_drop_cap(&mut self, mode: &str, lines: i32, dist: i32, font: Option<&str>) -> bool {
        if self.story != Story::Body || self.in_table(self.caret.para) {
            return false;
        }
        let p0 = self.caret.para;
        let existing = self.drop_cap_of(p0);
        let target = match existing {
            Some(d) if d == p0 => {
                let dom = &self.doc.dom;
                let parent = dom.parent(d).unwrap();
                let i = dom.index_in_parent(d).unwrap();
                match dom.children(parent).get(i + 1).copied() {
                    Some(n) if dom.is(n, "w:p") => n,
                    _ => return false,
                }
            }
            _ => p0,
        };
        self.begin();
        // take an existing drop cap back into its paragraph first
        if let Some(d) = existing {
            let dom = &mut self.doc.dom;
            let runs: Vec<NodeId> = dom.children_named(d, "w:r").collect();
            let at = dom.child(target, "w:pPr").map(|_| 1).unwrap_or(0);
            for (k, r) in runs.into_iter().enumerate() {
                if let Some(rpr) = dom.child(r, "w:rPr") {
                    for name in ["w:sz", "w:szCs", "w:position"] {
                        if let Some(x) = dom.child(rpr, name) {
                            dom.detach(x);
                        }
                    }
                }
                dom.detach(r);
                dom.insert(target, at + k, r);
            }
            dom.detach(d);
        }
        if mode == "none" {
            self.caret = Pos { para: target, off: 0 };
            self.anchor = self.caret;
            self.commit("Drop Cap", false);
            return true;
        }
        // the first letter, its formatting, and the line it sits on
        let first = self.pieces(target).into_iter().find_map(|(pc, s, _)| match (&pc.item, pc.run) {
            (Item::Text(t), Some(r)) if s == 0 && pc.change != "del" => t.chars().next().map(|c| (c, r)),
            _ => None,
        });
        let Some((ch, run)) = first else {
            self.commit("Drop Cap", false);
            return false;
        };
        let (line_h, size) = match self.para_layout(target) {
            Some(pl) => (pl.lines.first().map(|l| l.height).unwrap_or(14.0), if pl.mark_style.size > 0.0 { pl.mark_style.size } else { 11.0 }),
            None => (14.0, 11.0),
        };
        let lines = lines.clamp(1, 10) as f64;
        let cap_h = (lines - 1.0) * line_h + size * 0.66;
        let cap_size = cap_h / 0.66;
        let sz = ((cap_size * 2.0).round() as i32).max(2).to_string();
        let pos = (-(cap_size * 2.0 * 0.063).round() as i32).to_string();
        let exact = ((lines * line_h * 20.0).round() as i32).to_string();
        let rpr_src = self.doc.dom.child(run, "w:rPr");
        self.delete_in_para(target, 0, 1);
        let dom = &mut self.doc.dom;
        let dp = dom.new_element("w:p", &[]);
        let ppr = dom.new_element("w:pPr", &[]);
        if let Some(st) = dom.child(target, "w:pPr").and_then(|pp| dom.child(pp, "w:pStyle")) {
            let c = dom.clone_node(st);
            dom.append(ppr, c);
        }
        let mut fattrs = vec![("w:dropCap", if mode == "margin" { "margin" } else { "drop" }), ("w:wrap", "around"),
                              ("w:vAnchor", "text"), ("w:hAnchor", "text")];
        let lines_s = (lines as i32).to_string();
        let dist_s = dist.max(0).to_string();
        fattrs.insert(1, ("w:lines", &lines_s));
        if dist > 0 {
            fattrs.push(("w:hSpace", &dist_s));
        }
        let fp = dom.new_element("w:framePr", &fattrs);
        dom.append(ppr, fp);
        let sp = dom.new_element("w:spacing", &[("w:after", "0"), ("w:line", &exact), ("w:lineRule", "exact")]);
        dom.append(ppr, sp);
        let ta = dom.new_element("w:textAlignment", &[("w:val", "baseline")]);
        dom.append(ppr, ta);
        dom.append(dp, ppr);
        let r = dom.new_element("w:r", &[]);
        let rpr = match rpr_src {
            Some(x) => dom.clone_node(x),
            None => dom.new_element("w:rPr", &[]),
        };
        for name in ["w:sz", "w:szCs", "w:position", "w:rPrChange"] {
            if let Some(x) = dom.child(rpr, name) {
                dom.detach(x);
            }
        }
        dom.append(r, rpr);
        let t = dom.new_element("w:t", &[]);
        dom.append(r, t);
        dom.append(dp, r);
        let parent = dom.parent(target).unwrap();
        let i = dom.index_in_parent(target).unwrap();
        dom.insert(parent, i, dp);
        self.set_t(t, &ch.to_string());
        let mut edits = vec![PropEdit::set("w:position", &[("w:val", &pos)]), PropEdit::set("w:sz", &[("w:val", &sz)]),
                             PropEdit::set("w:szCs", &[("w:val", &sz)])];
        if let Some(f) = font {
            edits.push(PropEdit::set("w:rFonts", &[("w:ascii", f), ("w:hAnsi", f)]));
        }
        for e in &edits {
            super::set_prop_child(&mut self.doc.dom, rpr, e, RPR_ORDER);
        }
        self.caret = Pos { para: target, off: 0 };
        self.anchor = self.caret;
        self.commit("Drop Cap", false);
        true
    }

    /// The drop cap of the caret's paragraph: (mode, lines, distance twips).
    pub fn drop_cap_info(&self) -> Option<(String, i32, i32)> {
        let d = self.drop_cap_of(self.caret.para)?;
        let dom = &self.doc.dom;
        let f = dom.child(d, "w:pPr").and_then(|pp| dom.child(pp, "w:framePr"))?;
        Some((dom.attr(f, "w:dropCap").unwrap_or("drop").to_string(),
              crate::props::int_attr(dom, f, "w:lines").unwrap_or(3),
              crate::props::int_attr(dom, f, "w:hSpace").unwrap_or(0)))
    }
}
