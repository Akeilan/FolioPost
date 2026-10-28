//! The References tab: tables built from fields (contents, figures, index,
//! table of authorities), index and citation entries, footnote and endnote
//! settings, going from note to note, and the bibliography sources part.

use super::fields::{esc, heading_text, order, para_of, parse_instr, FieldInfo};
use super::{Editor, Pos, Story};
use crate::document::W_NS;
use crate::xml::{NodeId, XmlDoc};
use std::collections::BTreeMap;

pub const BIB_NS: &str = "http://schemas.openxmlformats.org/officeDocument/2006/bibliography";

/// The kinds of field whose result is whole paragraphs.
pub const TABLE_KINDS: &[&str] = &["TOC", "INDEX", "TOA", "BIBLIOGRAPHY"];

/// Table of Authorities categories (1-7 named, 8-16 numbered).
pub const TOA_CATEGORIES: &[&str] = &["Cases", "Statutes", "Other Authorities", "Rules", "Treatises",
    "Regulations", "Constitutional Provisions", "8", "9", "10", "11", "12", "13", "14", "15", "16"];

struct Entry {
    style: String,
    /// the runs of the text
    runs: String,
    /// a page reference (PAGEREF to a bookmark) or plain page text
    page: Option<Page>,
    link: Option<String>,
}

enum Page {
    Ref(String),
    Text(String),
}

fn sw<'a>(ins: &'a super::fields::Instr, c: char) -> Option<&'a Option<String>> {
    ins.switches.iter().find(|(s, _)| *s == c).map(|(_, a)| a)
}

fn range_of(a: &Option<String>) -> Option<(usize, usize)> {
    let r = a.as_ref()?;
    let (x, y) = r.split_once('-').unwrap_or((r.as_str(), r.as_str()));
    Some((x.trim().parse().ok()?, y.trim().parse().ok()?))
}

fn text_run(t: &str, rpr: &str) -> String {
    let mut out = String::new();
    for (i, line) in t.split('\n').enumerate() {
        if i > 0 {
            out.push_str(&format!("<w:r><w:rPr>{rpr}<w:noProof/></w:rPr><w:br/></w:r>"));
        }
        if !line.is_empty() {
            out.push_str(&format!("<w:r><w:rPr>{rpr}<w:noProof/></w:rPr><w:t xml:space=\"preserve\">{}</w:t></w:r>", esc(line)));
        }
    }
    out
}

/// Pages as Word lists them: "3, 5–7, 9".
fn page_list(pages: &[(usize, String, bool, bool)], sep: &str, range: &str) -> Vec<(String, bool, bool)> {
    let mut out: Vec<(String, bool, bool)> = Vec::new();
    let mut seen = Vec::new();
    for (n, lab, b, i) in pages {
        if seen.contains(n) && !lab.contains(range) {
            continue;
        }
        seen.push(*n);
        out.push((lab.clone(), *b, *i));
    }
    let _ = sep;
    out
}

impl Editor {
    // ------------------------------------------------------------ styles
    fn ensure_style(&mut self, id: &str, xml: String) {
        if !self.doc.styles.styles.contains_key(id) {
            self.add_style_xml(&xml);
        }
    }

    fn ensure_table_styles(&mut self, kind: &str, levels: usize) {
        match kind {
            "FIGURES" => self.ensure_style("TableofFigures", "<w:style w:type=\"paragraph\" w:styleId=\"TableofFigures\">\
                <w:name w:val=\"table of figures\"/><w:basedOn w:val=\"Normal\"/><w:next w:val=\"Normal\"/><w:uiPriority w:val=\"99\"/>\
                <w:unhideWhenUsed/><w:pPr><w:spacing w:after=\"0\"/></w:pPr></w:style>".into()),
            "INDEX" => {
                for l in 1..=levels.clamp(1, 9) {
                    let left = 220 * l;
                    self.ensure_style(&format!("Index{l}"), format!(
                        "<w:style w:type=\"paragraph\" w:styleId=\"Index{l}\"><w:name w:val=\"index {l}\"/><w:basedOn w:val=\"Normal\"/>\
                         <w:next w:val=\"Normal\"/><w:autoRedefine/><w:uiPriority w:val=\"99\"/><w:semiHidden/><w:unhideWhenUsed/>\
                         <w:pPr><w:spacing w:after=\"0\" w:line=\"240\" w:lineRule=\"auto\"/><w:ind w:left=\"{left}\" w:hanging=\"220\"/></w:pPr></w:style>"));
                }
                self.ensure_style("IndexHeading", "<w:style w:type=\"paragraph\" w:styleId=\"IndexHeading\"><w:name w:val=\"index heading\"/>\
                    <w:basedOn w:val=\"Normal\"/><w:next w:val=\"Index1\"/><w:uiPriority w:val=\"99\"/><w:unhideWhenUsed/>\
                    <w:pPr><w:spacing w:before=\"120\" w:after=\"60\"/></w:pPr><w:rPr><w:b/><w:bCs/></w:rPr></w:style>".into());
            }
            "TOA" => {
                self.ensure_style("TableofAuthorities", "<w:style w:type=\"paragraph\" w:styleId=\"TableofAuthorities\">\
                    <w:name w:val=\"table of authorities\"/><w:basedOn w:val=\"Normal\"/><w:next w:val=\"Normal\"/><w:uiPriority w:val=\"99\"/>\
                    <w:unhideWhenUsed/><w:pPr><w:spacing w:after=\"0\"/><w:ind w:left=\"220\" w:hanging=\"220\"/></w:pPr></w:style>".into());
                self.ensure_style("TOAHeading", "<w:style w:type=\"paragraph\" w:styleId=\"TOAHeading\"><w:name w:val=\"toa heading\"/>\
                    <w:basedOn w:val=\"Normal\"/><w:next w:val=\"Normal\"/><w:uiPriority w:val=\"99\"/><w:unhideWhenUsed/>\
                    <w:pPr><w:spacing w:before=\"120\"/></w:pPr><w:rPr><w:b/><w:bCs/><w:sz w:val=\"24\"/><w:szCs w:val=\"24\"/></w:rPr></w:style>".into());
            }
            _ => {}
        }
    }

    fn style_name_of(&self, p: NodeId) -> String {
        let dom = &self.doc.dom;
        let id = dom.child(p, "w:pPr").and_then(|pp| dom.child(pp, "w:pStyle")).and_then(|n| dom.attr(n, "w:val"))
            .map(|v| v.to_string()).or_else(|| self.doc.styles.default_para.clone()).unwrap_or_default();
        self.doc.styles.styles.get(&id).map(|s| s.name.clone()).unwrap_or(id)
    }

    fn body_paras_outside(&self, skip: Option<(NodeId, NodeId)>) -> Vec<NodeId> {
        let dom = &self.doc.dom;
        let mut nodes = Vec::new();
        order(dom, self.doc.body, &mut nodes);
        let mut out = Vec::new();
        let mut skipping = false;
        for n in nodes {
            if let Some((a, b)) = skip {
                if n == a {
                    skipping = true;
                }
                if skipping {
                    if n == b {
                        skipping = false;
                    }
                    continue;
                }
            }
            if dom.is(n, "w:p") {
                out.push(n);
            }
        }
        out
    }

    fn field_in_skip(&self, f: &FieldInfo, skip: Option<(NodeId, NodeId)>) -> bool {
        let Some((a, b)) = skip else { return false };
        let dom = &self.doc.dom;
        let Some(p) = para_of(dom, f.begin) else { return false };
        // document order, not layout (the table's paragraphs may be new)
        let mut nodes = Vec::new();
        order(dom, self.doc.body, &mut nodes);
        let (Some(ia), Some(ib), Some(ip)) = (nodes.iter().position(|&n| n == a), nodes.iter().position(|&n| n == b),
                                              nodes.iter().position(|&n| n == p)) else { return false };
        ip >= ia && ip <= ib
    }

    fn label_page(&self, n: NodeId) -> (usize, String) {
        let pg = self.page_of(n).unwrap_or(0);
        (pg, self.page_label(pg))
    }

    // ------------------------------------------------------------ tables
    /// The paragraphs of a table field (contents, figures, index, authorities),
    /// the field's begin in the first and its end in the last.
    pub(super) fn table_xml(&mut self, instr: &str, skip: Option<(NodeId, NodeId)>, leader: Option<String>) -> String {
        let ins = parse_instr(instr);
        let leader = leader.unwrap_or_else(|| "dot".into());
        let sec = self.current_section();
        let (width, cols) = self.doc.sections.get(sec).map(|s| (s.text_width(), s.cols.max(1) as i32)).unwrap_or((9360, 1));
        let mut tab_pos = width;
        let mut entries: Vec<Entry> = Vec::new();
        let mut empty = "No table of contents entries found.";
        // the text between an entry and its page number
        let mut sep: Option<String> = None;
        match ins.kind.as_str() {
            "INDEX" => {
                empty = "No index entries found.";
                let ncols: i32 = sw(&ins, 'c').and_then(|a| a.as_ref()).and_then(|v| v.trim().parse().ok()).unwrap_or(cols).max(1);
                tab_pos = (width - 720 * (ncols - 1)) / ncols;
                self.index_entries(&ins, skip, &mut entries, &mut sep);
            }
            "TOA" => {
                empty = "No table of authorities entries found.";
                self.toa_entries(&ins, skip, &mut entries, &mut sep);
            }
            _ => {
                if sw(&ins, 'c').is_some() || sw(&ins, 'a').is_some() {
                    empty = "No table of figures entries found.";
                }
                self.toc_entries(&ins, skip, &mut entries, &mut sep);
            }
        }
        let hyper = ins.switches.iter().any(|(s, _)| *s == 'h') && ins.kind == "TOC";
        let begin = format!("<w:r><w:fldChar w:fldCharType=\"begin\"/></w:r><w:r><w:instrText xml:space=\"preserve\"> {} </w:instrText></w:r>\
                             <w:r><w:fldChar w:fldCharType=\"separate\"/></w:r>", esc(instr.trim()));
        let mut xml = String::new();
        if entries.is_empty() {
            let st = match ins.kind.as_str() {
                "INDEX" => "Index1".to_string(),
                "TOA" => "TableofAuthorities".to_string(),
                _ if empty.contains("figures") => "TableofFigures".to_string(),
                _ => "TOC1".to_string(),
            };
            xml.push_str(&format!("<w:p><w:pPr><w:pStyle w:val=\"{st}\"/></w:pPr>{begin}<w:r><w:rPr><w:b/><w:bCs/><w:noProof/></w:rPr>\
                <w:t>{empty}</w:t></w:r><w:r><w:fldChar w:fldCharType=\"end\"/></w:r></w:p>"));
            return xml;
        }
        let tabbed = sep.as_deref().map_or(true, |s| s == "\t");
        for (i, e) in entries.iter().enumerate() {
            let mut body = e.runs.clone();
            let hidden = "<w:noProof/><w:webHidden/>";
            match &e.page {
                Some(Page::Ref(mark)) => {
                    body.push_str(&match sep.as_deref() {
                        Some(s) if s != "\t" => text_run(s, ""),
                        _ => format!("<w:r><w:rPr>{hidden}</w:rPr><w:tab/></w:r>"),
                    });
                    body.push_str(&format!(
                        "<w:r><w:rPr>{hidden}</w:rPr><w:fldChar w:fldCharType=\"begin\"/></w:r>\
                         <w:r><w:rPr>{hidden}</w:rPr><w:instrText xml:space=\"preserve\"> PAGEREF {mark} \\h </w:instrText></w:r>\
                         <w:r><w:rPr>{hidden}</w:rPr><w:fldChar w:fldCharType=\"separate\"/></w:r>\
                         <w:r><w:rPr>{hidden}</w:rPr><w:t>1</w:t></w:r>\
                         <w:r><w:rPr>{hidden}</w:rPr><w:fldChar w:fldCharType=\"end\"/></w:r>"));
                }
                Some(Page::Text(t)) => {
                    // already holds its separator and formatting runs
                    body.push_str(t);
                }
                None => {}
            }
            let body = match (&e.link, hyper) {
                (Some(m), true) => format!("<w:hyperlink w:anchor=\"{m}\" w:history=\"1\">{body}</w:hyperlink>"),
                _ => body,
            };
            let tabs = if tabbed && e.page.is_some() && leader != "noTab" {
                let ld = if leader == "none" { String::new() } else { format!(" w:leader=\"{leader}\"") };
                format!("<w:tabs><w:tab w:val=\"right\"{ld} w:pos=\"{tab_pos}\"/></w:tabs>")
            } else {
                String::new()
            };
            xml.push_str(&format!(
                "<w:p><w:pPr><w:pStyle w:val=\"{}\"/>{tabs}<w:rPr><w:noProof/></w:rPr></w:pPr>{}{body}</w:p>",
                e.style, if i == 0 { begin.as_str() } else { "" }));
        }
        xml.push_str("<w:p><w:r><w:rPr><w:b/><w:bCs/><w:noProof/></w:rPr><w:fldChar w:fldCharType=\"end\"/></w:r></w:p>");
        xml
    }

    /// Contents and figures: headings (\o, \u), styles (\t), captions (\c, \a).
    fn toc_entries(&mut self, ins: &super::fields::Instr, skip: Option<(NodeId, NodeId)>, out: &mut Vec<Entry>, sep: &mut Option<String>) {
        let caption = sw(ins, 'c').or_else(|| sw(ins, 'a')).map(|a| a.clone().unwrap_or_default());
        let outline = sw(ins, 'o').map(range_of);
        let no_pages: Option<(usize, usize)> = sw(ins, 'n').map(|a| range_of(a).unwrap_or((1, 9)));
        if let Some(Some(p)) = sw(ins, 'p') {
            *sep = Some(p.clone());
        }
        // \t "Style,1,Other,2"
        let mut styles: Vec<(String, usize)> = Vec::new();
        if let Some(Some(t)) = sw(ins, 't') {
            let parts: Vec<&str> = t.split(|c| c == ',' || c == ';').collect();
            let mut i = 0;
            while i < parts.len() {
                let name = parts[i].trim().to_string();
                let lvl = parts.get(i + 1).and_then(|v| v.trim().parse::<usize>().ok());
                if let Some(l) = lvl {
                    styles.push((name.to_lowercase(), l));
                    i += 2;
                } else {
                    if !name.is_empty() {
                        styles.push((name.to_lowercase(), 1));
                    }
                    i += 1;
                }
            }
        }
        let (from, to) = match outline {
            Some(Some(r)) => r,
            Some(None) => (1, 9),
            None if styles.is_empty() && sw(ins, 'u').is_none() && caption.is_none() => (1, 3),
            None if sw(ins, 'u').is_some() => (1, 9),
            None => (1, 0),
        };
        let paras = self.body_paras_outside(skip);
        let mut picked: Vec<(NodeId, usize, String)> = Vec::new();
        if let Some(label) = &caption {
            self.ensure_table_styles("FIGURES", 1);
            let seqs: Vec<NodeId> = self.fields_in(self.doc.body).into_iter()
                .filter(|f| !self.field_in_skip(f, skip))
                .filter(|f| {
                    let i = parse_instr(&f.instr);
                    i.kind == "SEQ" && i.args.first().map_or(false, |a| a.eq_ignore_ascii_case(label))
                })
                .filter_map(|f| para_of(&self.doc.dom, f.begin)).collect();
            for p in paras {
                if seqs.contains(&p) {
                    let t = heading_text(&self.doc.para_text(p));
                    if !t.is_empty() {
                        picked.push((p, 1, t));
                    }
                }
            }
        } else {
            let mut maxl = to.max(1);
            for p in paras {
                let mut level = None;
                if !styles.is_empty() {
                    let n = self.style_name_of(p).to_lowercase();
                    if let Some((_, l)) = styles.iter().find(|(s, _)| *s == n) {
                        level = Some(*l);
                    }
                }
                if level.is_none() && to >= from {
                    let (pp, _) = self.doc.para_props(p);
                    if let Some(l) = pp.outline_lvl {
                        let l = l as usize + 1;
                        if l >= from && l <= to {
                            level = Some(l);
                        }
                    }
                }
                let Some(l) = level else { continue };
                let t = heading_text(&self.doc.para_text(p));
                if !t.is_empty() {
                    maxl = maxl.max(l);
                    picked.push((p, l.clamp(1, 9), t));
                }
            }
            self.ensure_toc_styles(maxl.min(9));
        }
        let mut next_id = self.max_bookmark_id() + 1;
        let mut used = Vec::new();
        for (p, level, text) in picked {
            let mark = self.toc_bookmark(p, &mut next_id, &mut used);
            let page = match no_pages {
                Some((a, b)) if level >= a && level <= b => None,
                _ => Some(Page::Ref(mark.clone())),
            };
            out.push(Entry {
                style: if caption.is_some() { "TableofFigures".into() } else { format!("TOC{level}") },
                runs: text_run(&text, ""),
                page,
                link: Some(mark),
            });
        }
    }

    /// The index: XE fields, sorted, with their pages.
    fn index_entries(&mut self, ins: &super::fields::Instr, skip: Option<(NodeId, NodeId)>, out: &mut Vec<Entry>, sep: &mut Option<String>) {
        let entry_sep = sw(ins, 'e').and_then(|a| a.clone()).unwrap_or_else(|| ", ".into());
        let list_sep = sw(ins, 'l').and_then(|a| a.clone()).unwrap_or_else(|| ", ".into());
        let range_sep = sw(ins, 'g').and_then(|a| a.clone()).unwrap_or_else(|| "–".into());
        let headings = sw(ins, 'h').map(|a| a.clone().unwrap_or_else(|| "A".into()));
        let run_in = sw(ins, 'r').is_some();
        if entry_sep == "\t" {
            *sep = Some("\t".into());
        } else {
            *sep = Some(String::new());
        }
        // key path -> (display path, pages, cross reference)
        type Pages = Vec<(usize, String, bool, bool)>;
        let mut tree: BTreeMap<Vec<String>, (Vec<String>, Pages, Option<String>)> = BTreeMap::new();
        let marks = self.bookmarks();
        for f in self.fields_in(self.doc.body) {
            if f.kind() != "XE" || self.field_in_skip(&f, skip) {
                continue;
            }
            let i = parse_instr(&f.instr);
            let Some(text) = i.args.first() else { continue };
            let path: Vec<String> = text.split(':').map(|s| s.trim().to_string()).filter(|s| !s.is_empty()).collect();
            if path.is_empty() {
                continue;
            }
            let key: Vec<String> = path.iter().map(|s| s.to_lowercase()).collect();
            let bold = i.switches.iter().any(|(c, _)| *c == 'b');
            let ital = i.switches.iter().any(|(c, _)| *c == 'i');
            let see = i.switches.iter().find(|(c, _)| *c == 't').and_then(|(_, a)| a.clone());
            let page = match i.switches.iter().find(|(c, _)| *c == 'r').and_then(|(_, a)| a.clone()) {
                Some(bm) => marks.get(&bm).map(|&(s, e)| {
                    let (a, la) = self.label_page(s);
                    let (b, lb) = e.map(|e| self.label_page(e)).unwrap_or((a, la.clone()));
                    (a, if b > a { format!("{la}{range_sep}{lb}") } else { la })
                }),
                None => Some(self.label_page(f.begin)),
            };
            // parents exist too
            for k in 1..path.len() {
                tree.entry(key[..k].to_vec()).or_insert_with(|| (path[..k].to_vec(), Vec::new(), None));
            }
            let e = tree.entry(key.clone()).or_insert_with(|| (path.clone(), Vec::new(), None));
            if let Some(s) = see {
                e.2 = Some(s);
            } else if let Some((n, lab)) = page {
                e.1.push((n, lab, bold, ital));
            }
        }
        let max_level = tree.keys().map(|k| k.len()).max().unwrap_or(1);
        self.ensure_table_styles("INDEX", max_level);
        let mut letter: Option<char> = None;
        for (key, (disp, mut pages, see)) in tree {
            if key.len() == 1 {
                if let Some(h) = &headings {
                    let c = key[0].chars().next().unwrap_or(' ');
                    let c = if c.is_alphabetic() { c.to_uppercase().next().unwrap_or(c) } else { '#' };
                    if letter != Some(c) {
                        letter = Some(c);
                        let txt = if h.is_empty() { String::new() } else { h.replace('A', &c.to_string()) };
                        if !txt.is_empty() {
                            out.push(Entry { style: "IndexHeading".into(), runs: text_run(&txt, ""), page: None, link: None });
                        }
                    }
                }
            }
            let level = key.len().clamp(1, 9);
            let name = disp.last().cloned().unwrap_or_default();
            pages.sort_by_key(|p| p.0);
            let list = page_list(&pages, &list_sep, &range_sep);
            let mut tail = String::new();
            if !list.is_empty() || see.is_some() {
                if list.is_empty() {
                    // only a cross-reference: "Fruit. See Apple"
                    tail.push_str(&text_run(". ", ""));
                } else if entry_sep == "\t" {
                    tail.push_str("<w:r><w:rPr><w:noProof/></w:rPr><w:tab/></w:r>");
                } else {
                    tail.push_str(&text_run(&entry_sep, ""));
                }
                for (k, (lab, b, it)) in list.iter().enumerate() {
                    if k > 0 {
                        tail.push_str(&text_run(&list_sep, ""));
                    }
                    let rpr = format!("{}{}", if *b { "<w:b/><w:bCs/>" } else { "" }, if *it { "<w:i/><w:iCs/>" } else { "" });
                    tail.push_str(&text_run(lab, &rpr));
                }
                if let Some(s) = &see {
                    if !list.is_empty() {
                        tail.push_str(&text_run(". ", ""));
                    }
                    tail.push_str(&text_run(s, "<w:i/><w:iCs/>"));
                }
            }
            if run_in && level > 1 {
                // run-in: subentries follow their main entry on its line
                if let Some(last) = out.last_mut() {
                    last.runs.push_str(&text_run("; ", ""));
                    last.runs.push_str(&text_run(&name, ""));
                    last.runs.push_str(&tail);
                    continue;
                }
            }
            out.push(Entry {
                style: format!("Index{}", if run_in { 1 } else { level }),
                runs: text_run(&name, ""),
                page: if tail.is_empty() { None } else { Some(Page::Text(tail)) },
                link: None,
            });
        }
    }

    /// A table of authorities: the TA fields of a category.
    fn toa_entries(&mut self, ins: &super::fields::Instr, skip: Option<(NodeId, NodeId)>, out: &mut Vec<Entry>, sep: &mut Option<String>) {
        let cat: usize = sw(ins, 'c').and_then(|a| a.as_ref()).and_then(|v| v.trim().parse().ok()).unwrap_or(1);
        let passim = sw(ins, 'p').is_some();
        let heading = sw(ins, 'h').is_some();
        let entry_sep = sw(ins, 'e').and_then(|a| a.clone()).unwrap_or_else(|| "\t".into());
        let list_sep = sw(ins, 'l').and_then(|a| a.clone()).unwrap_or_else(|| ", ".into());
        *sep = Some(if entry_sep == "\t" { "\t".into() } else { String::new() });
        self.ensure_table_styles("TOA", 1);
        // short citation -> (long citation, category)
        let fields: Vec<FieldInfo> = self.fields_in(self.doc.body).into_iter()
            .filter(|f| f.kind() == "TA" && !self.field_in_skip(f, skip)).collect();
        let mut long: BTreeMap<String, (String, usize)> = BTreeMap::new();
        for f in &fields {
            let i = parse_instr(&f.instr);
            let l = i.switches.iter().find(|(c, _)| *c == 'l').and_then(|(_, a)| a.clone());
            let s = i.switches.iter().find(|(c, _)| *c == 's').and_then(|(_, a)| a.clone());
            let c: usize = i.switches.iter().find(|(c, _)| *c == 'c').and_then(|(_, a)| a.as_ref()).and_then(|v| v.trim().parse().ok()).unwrap_or(1);
            if let Some(l) = l {
                let key = s.clone().unwrap_or_else(|| l.clone());
                long.insert(key.to_lowercase(), (l, c));
            }
        }
        // long citation -> pages
        let mut pages: BTreeMap<String, (String, Vec<(usize, String)>)> = BTreeMap::new();
        for f in &fields {
            let i = parse_instr(&f.instr);
            let l = i.switches.iter().find(|(c, _)| *c == 'l').and_then(|(_, a)| a.clone());
            let s = i.switches.iter().find(|(c, _)| *c == 's').and_then(|(_, a)| a.clone());
            let key = s.or(l).unwrap_or_default().to_lowercase();
            let Some((text, c)) = long.get(&key) else { continue };
            if *c != cat {
                continue;
            }
            let pg = self.label_page(f.begin);
            let e = pages.entry(text.to_lowercase()).or_insert_with(|| (text.clone(), Vec::new()));
            if !e.1.iter().any(|p| p.0 == pg.0) {
                e.1.push(pg);
            }
        }
        if pages.is_empty() {
            return;
        }
        if heading {
            let name = TOA_CATEGORIES.get(cat.saturating_sub(1)).copied().unwrap_or("Cases");
            out.push(Entry { style: "TOAHeading".into(), runs: text_run(name, ""), page: None, link: None });
        }
        for (_k, (text, mut pg)) in pages {
            pg.sort_by_key(|p| p.0);
            let mut tail = if entry_sep == "\t" {
                "<w:r><w:rPr><w:noProof/></w:rPr><w:tab/></w:r>".to_string()
            } else {
                text_run(&entry_sep, "")
            };
            if passim && pg.len() >= 5 {
                tail.push_str(&text_run("passim", "<w:i/><w:iCs/>"));
            } else {
                let labs: Vec<String> = pg.into_iter().map(|p| p.1).collect();
                tail.push_str(&text_run(&labs.join(&list_sep), ""));
            }
            out.push(Entry { style: "TableofAuthorities".into(), runs: text_run(&text, ""), page: Some(Page::Text(tail)), link: None });
        }
    }

    /// The tab leader the entries of a table have now (kept on update).
    pub(super) fn table_leader(&self, paras: &[NodeId]) -> Option<String> {
        let dom = &self.doc.dom;
        for &p in paras {
            let Some(tabs) = dom.child(p, "w:pPr").and_then(|pp| dom.child(pp, "w:tabs")) else { continue };
            for t in dom.elements(tabs) {
                if dom.attr(t, "w:val") == Some("right") {
                    return Some(dom.attr(t, "w:leader").unwrap_or("none").to_string());
                }
            }
        }
        None
    }

    /// Insert a table field at the caret: `instr` a TOC, INDEX or TOA field,
    /// or with `paras` given, those paragraphs as the result (a bibliography).
    /// `title` (text, style) goes above it, and a content control around
    /// both for `gallery` ("Table of Contents", "Bibliographies"). An index
    /// in `columns` columns gets a section of its own.
    pub fn insert_table_field(&mut self, instr: &str, title: Option<(&str, &str)>, gallery: Option<&str>,
                              leader: Option<&str>, paras: Option<&str>, columns: u32) -> bool {
        if self.story != Story::Body || self.in_table(self.caret.para) {
            return false;
        }
        let kind = parse_instr(instr).kind;
        let label = match kind.as_str() {
            "INDEX" => "Insert Index",
            "TOA" => "Insert Table of Authorities",
            "BIBLIOGRAPHY" => "Insert Bibliography",
            _ if instr.contains("\\c") || instr.contains("\\a") => "Insert Table of Figures",
            _ => "Table of Contents",
        };
        self.begin_group(label);
        if columns > 1 {
            self.insert_break("continuous");
        }
        if let Some((_, st)) = title {
            if st == "TOCHeading" {
                self.ensure_toc_styles(1);
            }
        }
        self.begin();
        self.delete_selection();
        let mut p = self.caret.para;
        if self.caret.off > 0 {
            p = self.split_para(p, self.caret.off);
            self.doc.scan();
        }
        let entries = match paras {
            Some(x) => {
                let begin = format!("<w:r><w:fldChar w:fldCharType=\"begin\"/></w:r><w:r><w:instrText xml:space=\"preserve\"> {} </w:instrText></w:r>\
                                     <w:r><w:fldChar w:fldCharType=\"separate\"/></w:r>", esc(instr.trim()));
                wrap_given(x, &begin)
            }
            None => self.table_xml(instr, None, leader.map(|s| s.to_string())),
        };
        let head = title.map(|(t, st)| format!("<w:p><w:pPr><w:pStyle w:val=\"{st}\"/></w:pPr><w:r><w:t xml:space=\"preserve\">{}</w:t></w:r></w:p>", esc(t)))
            .unwrap_or_default();
        let xml = match gallery {
            Some(g) => format!("<w:sdt><w:sdtPr><w:docPartObj><w:docPartGallery w:val=\"{}\"/><w:docPartUnique/></w:docPartObj></w:sdtPr>\
                                <w:sdtContent>{head}{entries}</w:sdtContent></w:sdt>", esc(g)),
            None => format!("{head}{entries}"),
        };
        let nodes = self.import_paras(&xml);
        let dom = &mut self.doc.dom;
        let parent = dom.parent(p).unwrap();
        let mut idx = dom.index_in_parent(p).unwrap();
        let mut last = None;
        for n in nodes {
            dom.insert(parent, idx, n);
            last = Some(n);
            idx += 1;
        }
        if columns > 1 {
            // the index's own section, in columns, ends with its last paragraph
            let sec = self.current_section();
            let sect = self.doc.sections.get(sec).and_then(|s| s.node);
            let dom = &mut self.doc.dom;
            let lastp = last.and_then(|l| if dom.is(l, "w:p") { Some(l) } else {
                let mut v = Vec::new();
                order(dom, l, &mut v);
                v.into_iter().rev().find(|&n| dom.is(n, "w:p"))
            });
            if let (Some(lp), Some(sect)) = (lastp, sect) {
                let copy = dom.clone_node(sect);
                for k in dom.children(copy).to_vec() {
                    if matches!(dom.name(k), "w:headerReference" | "w:footerReference" | "w:cols" | "w:type") {
                        dom.detach(k);
                    }
                }
                let ty = dom.new_element("w:type", &[("w:val", "continuous")]);
                dom.insert(copy, 0, ty);
                let c = dom.new_element("w:cols", &[("w:num", &columns.to_string()), ("w:space", "720")]);
                dom.append(copy, c);
                let ppr = match dom.child(lp, "w:pPr") {
                    Some(x) => x,
                    None => {
                        let x = dom.new_element("w:pPr", &[]);
                        dom.insert(lp, 0, x);
                        x
                    }
                };
                dom.append(ppr, copy);
            }
        }
        self.caret = Pos { para: p, off: 0 };
        self.anchor = self.caret;
        self.commit(label, false);
        if paras.is_none() {
            self.update_toc_pages();
            if kind == "INDEX" || kind == "TOA" {
                // pages moved with the table in: once more
                if let Some(f) = self.fields_in(self.doc.body).into_iter().rev()
                    .find(|f| f.kind() == kind && para_of(&self.doc.dom, f.begin).map_or(false, |b| self.paras_between(b, p).len() > 0)) {
                    self.rebuild_table(&f);
                }
            }
        }
        self.end_group();
        true
    }

    /// Rebuild a table field from the document now (false: not one we build).
    pub(super) fn rebuild_table(&mut self, f: &FieldInfo) -> bool {
        if f.kind() == "BIBLIOGRAPHY" {
            return false;
        }
        let paras = self.field_paras(f);
        if paras.is_empty() {
            return false;
        }
        let first = paras[0];
        let last = *paras.last().unwrap();
        let leader = self.table_leader(&paras);
        self.begin();
        let xml = self.table_xml(&f.instr, Some((first, last)), leader);
        self.replace_field_paras(&paras, &xml);
        self.commit("Update Table", false);
        self.update_toc_pages();
        true
    }

    /// Put new paragraphs in place of a field's, keeping a section break the
    /// last one ended.
    fn replace_field_paras(&mut self, paras: &[NodeId], xml: &str) {
        let first = paras[0];
        let last = *paras.last().unwrap();
        let nodes = self.import_paras(xml);
        let dom = &mut self.doc.dom;
        let sect = dom.child(last, "w:pPr").and_then(|pp| dom.child(pp, "w:sectPr"));
        let parent = dom.parent(first).unwrap();
        let mut idx = dom.index_in_parent(first).unwrap();
        let mut new_last = None;
        for n in nodes {
            dom.insert(parent, idx, n);
            new_last = Some(n);
            idx += 1;
        }
        if let (Some(s), Some(nl)) = (sect, new_last) {
            dom.detach(s);
            let ppr = match dom.child(nl, "w:pPr") {
                Some(x) => x,
                None => {
                    let x = dom.new_element("w:pPr", &[]);
                    dom.insert(nl, 0, x);
                    x
                }
            };
            dom.append(ppr, s);
        }
        let caret_in = paras.contains(&self.caret.para) || paras.contains(&self.anchor.para);
        for p in paras {
            dom.detach(*p);
        }
        if caret_in {
            if let Some(p) = dom.elements(parent).find(|&k| dom.is(k, "w:p")) {
                self.caret = Pos { para: p, off: 0 };
                self.anchor = self.caret;
            }
        }
        self.doc.scan();
    }

    /// Give the `i`th top-level field of the body a new instruction and
    /// rebuild it (a table of contents changed in its dialog).
    pub fn set_table_instr(&mut self, i: usize, instr: &str, leader: Option<&str>) -> bool {
        let Some(f) = self.fields_in(self.doc.body).into_iter().filter(|f| f.depth == 0).nth(i) else { return false };
        let paras = self.field_paras(&f);
        if paras.is_empty() {
            return false;
        }
        let first = paras[0];
        let last = *paras.last().unwrap();
        let leader = leader.map(|s| s.to_string()).or_else(|| self.table_leader(&paras));
        self.begin_group("Update Table");
        self.begin();
        let xml = self.table_xml(instr, Some((first, last)), leader);
        self.replace_field_paras(&paras, &xml);
        self.commit("Update Table", false);
        self.update_toc_pages();
        self.end_group();
        true
    }

    /// Set the paragraphs of the `i`th table field of the body (a
    /// bibliography the app formats).
    pub fn set_table_result(&mut self, i: usize, paras_xml: &str) -> bool {
        let Some(f) = self.fields_in(self.doc.body).into_iter().filter(|f| f.depth == 0).nth(i) else { return false };
        let paras = self.field_paras(&f);
        if paras.is_empty() {
            return false;
        }
        let begin = format!("<w:r><w:fldChar w:fldCharType=\"begin\"/></w:r><w:r><w:instrText xml:space=\"preserve\"> {} </w:instrText></w:r>\
                             <w:r><w:fldChar w:fldCharType=\"separate\"/></w:r>", esc(f.instr.trim()));
        self.begin();
        let xml = wrap_given(paras_xml, &begin);
        self.replace_field_paras(&paras, &xml);
        self.commit("Update Field", false);
        true
    }

    /// Give the `i`th top-level body field a new instruction (its result
    /// stays until it is updated).
    pub fn set_field_instr(&mut self, i: usize, instr: &str) -> bool {
        let Some(f) = self.fields_in(self.doc.body).into_iter().filter(|f| f.depth == 0).nth(i) else { return false };
        if f.simple {
            self.begin();
            self.doc.dom.set_attr(f.begin, "w:instr", &format!(" {} ", instr.trim()));
            self.commit("Edit Field", false);
            return true;
        }
        let dom = &self.doc.dom;
        let Some(p) = para_of(dom, f.begin) else { return false };
        let mut nodes = Vec::new();
        order(dom, p, &mut nodes);
        let mut on = false;
        let mut texts = Vec::new();
        for n in nodes {
            if n == f.begin {
                on = true;
            }
            if Some(n) == f.sep || Some(n) == f.end {
                break;
            }
            if on && dom.is(n, "w:instrText") {
                texts.push(n);
            }
        }
        let Some(&first) = texts.first() else { return false };
        self.begin();
        let dom = &mut self.doc.dom;
        for &t in &texts[1..] {
            if let Some(r) = dom.parent(t) {
                dom.detach(r);
            }
        }
        for k in dom.children(first).to_vec() {
            dom.detach(k);
        }
        let tx = dom.new_text(&format!(" {} ", instr.trim()));
        dom.append(first, tx);
        dom.set_attr(first, "xml:space", "preserve");
        self.commit("Edit Field", false);
        true
    }

    /// Set the text of the `i`th field of the body (a citation).
    pub fn set_field_text(&mut self, i: usize, text: &str) -> bool {
        let Some(f) = self.fields_in(self.doc.body).into_iter().filter(|f| f.depth == 0).nth(i) else { return false };
        if self.field_result(&f) == text {
            return true;
        }
        self.begin();
        self.set_field_result(&f, text);
        self.commit("Update Field", false);
        true
    }

    /// The top-level fields of the body: (instruction, result, paragraph,
    /// offset of its start, offset of its end).
    pub fn body_fields(&self) -> Vec<(String, String, NodeId, usize, usize)> {
        self.fields_in(self.doc.body).into_iter().filter(|f| f.depth == 0).map(|f| {
            let p = para_of(&self.doc.dom, f.begin).unwrap_or(self.doc.body);
            let a = self.node_offset(p, f.begin).unwrap_or(0);
            let e = f.end.or(Some(f.begin)).unwrap();
            let pe = para_of(&self.doc.dom, e).unwrap_or(p);
            let b = if pe == p { self.node_offset(p, e).unwrap_or(a) } else { usize::MAX };
            (f.instr.trim().to_string(), self.field_result(&f), p, a, b)
        }).collect()
    }

    /// The index of the top-level body field the caret is in (or right after).
    pub fn field_at_caret(&self, kind: &str) -> Option<usize> {
        if self.story != Story::Body {
            return None;
        }
        let c = self.caret;
        self.body_fields().iter().position(|(instr, _r, p, a, b)| {
            *p == c.para && *a <= c.off && c.off <= *b
                && instr.split_whitespace().next().map_or(false, |k| k.eq_ignore_ascii_case(kind))
        })
    }

    /// Where a node starts in its paragraph (text offset).
    pub(super) fn node_offset(&self, p: NodeId, n: NodeId) -> Option<usize> {
        let pl = self.para_layout(p)?;
        let dom = &self.doc.dom;
        let mut off = 0;
        for pc in &pl.pieces {
            if let Some(node) = pc.node {
                let mut x = Some(node);
                while let Some(k) = x {
                    if k == n {
                        return Some(off);
                    }
                    if k == p {
                        break;
                    }
                    x = dom.parent(k);
                }
                // the node comes before this piece
                if self.node_before(n, node) {
                    return Some(off);
                }
            }
            off += pc.item.len();
        }
        Some(off)
    }

    fn node_before(&self, a: NodeId, b: NodeId) -> bool {
        let dom = &self.doc.dom;
        let Some(p) = para_of(dom, b) else { return false };
        let mut v = Vec::new();
        order(dom, p, &mut v);
        let ia = v.iter().position(|&k| k == a);
        let ib = v.iter().position(|&k| k == b);
        matches!((ia, ib), (Some(x), Some(y)) if x < y)
    }

    // ------------------------------------------------------------ entries
    /// A field with no result (XE, TA), hidden text, right after the
    /// selection.
    pub fn insert_code_field(&mut self, instr: &str) -> bool {
        if self.story == Story::HeaderFooter(0) && false {
            return false;
        }
        let (_a, b) = self.selection();
        self.begin();
        let (parent, mut idx, like) = self.split_runs_at(b.para, b.off);
        for kind in ["begin", "instr", "end"] {
            let r = self.new_run(b.para, like, &[]);
            let dom = &mut self.doc.dom;
            let rpr = match dom.child(r, "w:rPr") {
                Some(x) => x,
                None => {
                    let x = dom.new_element("w:rPr", &[]);
                    dom.insert(r, 0, x);
                    x
                }
            };
            if dom.child(rpr, "w:vanish").is_none() {
                let v = dom.new_element("w:vanish", &[]);
                dom.append(rpr, v);
            }
            let c = if kind == "instr" {
                let e = dom.new_element("w:instrText", &[("xml:space", "preserve")]);
                let t = dom.new_text(&format!(" {} ", instr.trim()));
                dom.append(e, t);
                e
            } else {
                dom.new_element("w:fldChar", &[("w:fldCharType", kind)])
            };
            dom.append(r, c);
            dom.insert(parent, idx, r);
            idx += 1;
        }
        self.caret = b;
        self.anchor = b;
        self.commit(if instr.trim_start().starts_with("TA") { "Mark Citation" } else { "Mark Index Entry" }, false);
        true
    }

    /// Mark All: an entry after every occurrence of `text` in the body.
    pub fn mark_all(&mut self, text: &str, instr: &str, match_case: bool) -> usize {
        if text.is_empty() {
            return 0;
        }
        let paras = self.body_paras_outside(None);
        let mut hits: Vec<(NodeId, usize)> = Vec::new();
        for p in paras {
            if self.para_layout(p).is_none() {
                continue;
            }
            let t = self.doc.para_text(p);
            let (hay, needle) = if match_case { (t.clone(), text.to_string()) } else { (t.to_lowercase(), text.to_lowercase()) };
            let hc: Vec<char> = hay.chars().collect();
            let nc: Vec<char> = needle.chars().collect();
            let mut i = 0;
            while i + nc.len() <= hc.len() {
                if hc[i..i + nc.len()] == nc[..] {
                    let before = i == 0 || !hc[i - 1].is_alphanumeric();
                    let after = i + nc.len() >= hc.len() || !hc[i + nc.len()].is_alphanumeric();
                    if before && after {
                        hits.push((p, i + nc.len()));
                    }
                    i += nc.len();
                } else {
                    i += 1;
                }
            }
        }
        let n = hits.len();
        if n == 0 {
            return 0;
        }
        let keep = (self.caret, self.anchor);
        self.begin_group("Mark All");
        // the last first, so earlier offsets stay right
        for (p, off) in hits.into_iter().rev() {
            self.caret = Pos { para: p, off };
            self.anchor = self.caret;
            self.insert_code_field(instr);
        }
        self.end_group();
        self.caret = keep.0;
        self.anchor = keep.1;
        n
    }

    // ------------------------------------------------------------ notes
    /// Footnote (or endnote) settings: (number format, start at, numbering
    /// restart, location).
    pub fn note_settings(&self, endnote: bool) -> (String, i32, String, String) {
        let n = &self.doc.notes;
        if endnote {
            (n.en_fmt.clone(), n.en_start, if n.en_restart.is_empty() { "continuous".into() } else { n.en_restart.clone() },
             if n.en_pos.is_empty() { "docEnd".into() } else { n.en_pos.clone() })
        } else {
            (n.fn_fmt.clone(), n.fn_start, if n.fn_restart.is_empty() { "continuous".into() } else { n.fn_restart.clone() },
             if n.fn_pos.is_empty() { "pageBottom".into() } else { n.fn_pos.clone() })
        }
    }

    pub fn set_note_settings(&mut self, endnote: bool, fmt: &str, start: i32, restart: &str, pos: &str) {
        let n = &mut self.doc.notes;
        if endnote {
            n.en_fmt = fmt.into();
            n.en_start = start.max(0);
            n.en_restart = restart.into();
            n.en_pos = pos.into();
        } else {
            n.fn_fmt = fmt.into();
            n.fn_start = start.max(0);
            n.fn_restart = restart.into();
            n.fn_pos = pos.into();
        }
        n.pr_dirty = true;
        self.modified = true;
        self.doc.scan();
        self.cache.clear();
        self.relayout();
    }

    /// Insert a note with its own mark ("*") instead of a number.
    pub fn insert_note_mark(&mut self, endnote: bool, mark: &str) -> bool {
        if !self.insert_note(endnote) {
            return false;
        }
        if mark.is_empty() {
            return true;
        }
        // the reference: a custom mark follows it; the note starts with the mark
        let tag = if endnote { "w:endnoteReference" } else { "w:footnoteReference" };
        let rtag = if endnote { "w:endnoteRef" } else { "w:footnoteRef" };
        let note_para = self.caret.para;
        let dom = &self.doc.dom;
        let mut v = Vec::new();
        order(dom, self.doc.body, &mut v);
        let note = {
            let mut x = Some(note_para);
            let want = if endnote { "w:endnote" } else { "w:footnote" };
            while let Some(k) = x {
                if dom.is(k, want) {
                    break;
                }
                x = dom.parent(k);
            }
            x
        };
        let Some(note) = note else { return true };
        let id = dom.attr(note, "w:id").unwrap_or("").to_string();
        let Some(rf) = v.into_iter().find(|&k| dom.is(k, tag) && dom.attr(k, "w:id") == Some(id.as_str())) else { return true };
        let mut nv = Vec::new();
        order(dom, note, &mut nv);
        let nref = nv.into_iter().find(|&k| dom.is(k, rtag));
        self.begin();
        let dom = &mut self.doc.dom;
        dom.set_attr(rf, "w:customMarkFollows", "1");
        let run = dom.parent(rf).unwrap();
        let t = dom.new_element("w:t", &[]);
        let tx = dom.new_text(mark);
        dom.append(t, tx);
        dom.append(run, t);
        if let Some(nr) = nref {
            let t = dom.new_element("w:t", &[]);
            let tx = dom.new_text(mark);
            dom.append(t, tx);
            let r = dom.parent(nr).unwrap();
            dom.insert(r, dom.index_in_parent(nr).unwrap(), t);
            dom.detach(nr);
        }
        self.commit(if endnote { "Insert Endnote" } else { "Insert Footnote" }, false);
        let len = self.para_layout(note_para).map(|l| l.text_len).unwrap_or(0);
        self.caret = Pos { para: note_para, off: len };
        self.anchor = self.caret;
        true
    }

    /// Show Notes: from the text to the note of the reference at or after
    /// the caret; from a note back to its reference.
    pub fn show_notes(&mut self, endnote_first: bool) -> bool {
        if let Story::Notes(_) = self.story {
            let dom = &self.doc.dom;
            // back to the reference
            let mut x = Some(self.caret.para);
            let mut note = None;
            while let Some(k) = x {
                if dom.is(k, "w:footnote") || dom.is(k, "w:endnote") {
                    note = Some(k);
                    break;
                }
                x = dom.parent(k);
            }
            self.edit_notes(None);
            let Some(note) = note else { return true };
            let en = self.doc.dom.is(note, "w:endnote");
            let id = self.doc.dom.attr(note, "w:id").unwrap_or("").to_string();
            let tag = if en { "w:endnoteReference" } else { "w:footnoteReference" };
            let dom = &self.doc.dom;
            let mut v = Vec::new();
            order(dom, self.doc.body, &mut v);
            if let Some(rf) = v.into_iter().find(|&k| dom.is(k, tag) && dom.attr(k, "w:id") == Some(id.as_str())) {
                if let Some(p) = para_of(dom, rf) {
                    let off = self.node_offset(p, rf).unwrap_or(0) + 1;
                    self.move_to(Pos { para: p, off }, false, false);
                }
            }
            return true;
        }
        if self.story != Story::Body {
            self.edit_header_footer(None, false);
        }
        let dom = &self.doc.dom;
        let mut v = Vec::new();
        order(dom, self.doc.body, &mut v);
        let refs: Vec<NodeId> = v.into_iter().filter(|&k| dom.is(k, "w:footnoteReference") || dom.is(k, "w:endnoteReference")).collect();
        if refs.is_empty() {
            return false;
        }
        let caret = self.caret;
        let mut pick = None;
        for &r in &refs {
            let Some(p) = para_of(&self.doc.dom, r) else { continue };
            let off = self.node_offset(p, r).unwrap_or(0);
            if self.cmp(Pos { para: p, off: off + 1 }, caret).is_ge() {
                pick = Some(r);
                break;
            }
        }
        let prefer = if endnote_first { "w:endnoteReference" } else { "w:footnoteReference" };
        let r = pick.or_else(|| refs.iter().copied().find(|&r| self.doc.dom.is(r, prefer))).unwrap_or(refs[0]);
        let en = self.doc.dom.is(r, "w:endnoteReference");
        let id = self.doc.dom.attr(r, "w:id").unwrap_or("").to_string();
        let note = if en { self.doc.notes.endnotes.get(&id) } else { self.doc.notes.footnotes.get(&id) }.copied();
        let Some(note) = note else { return false };
        let Some(np) = self.doc.dom.elements(note).find(|&k| self.doc.dom.is(k, "w:p")) else { return false };
        let pg = self.layout.pages.iter().position(|pp| pp.note_lines.iter().any(|l| self.layout.paras[l.para].node == np))
            .or_else(|| self.page_of(r)).unwrap_or(0);
        self.edit_notes(Some(pg));
        if self.pidx(&np).is_some() {
            let len = self.para_layout(np).map(|l| l.text_len).unwrap_or(0);
            self.caret = Pos { para: np, off: len };
            self.anchor = self.caret;
        }
        true
    }

    /// Convert notes: "fe" footnotes to endnotes, "ef" endnotes to
    /// footnotes, "swap" both ways.
    pub fn convert_notes(&mut self, how: &str) -> usize {
        let mut todo: Vec<(NodeId, bool)> = Vec::new();
        {
            let dom = &self.doc.dom;
            let mut v = Vec::new();
            order(dom, self.doc.body, &mut v);
            for k in v {
                let f = dom.is(k, "w:footnoteReference");
                let e = dom.is(k, "w:endnoteReference");
                if (f && (how == "fe" || how == "swap")) || (e && (how == "ef" || how == "swap")) {
                    todo.push((k, f));
                }
            }
        }
        if todo.is_empty() {
            return 0;
        }
        self.begin_group("Convert Notes");
        let fe_root = if todo.iter().any(|t| t.1) { Some(self.notes_root(true)) } else { None };
        let ef_root = if todo.iter().any(|t| !t.1) { Some(self.notes_root(false)) } else { None };
        self.begin();
        let n = todo.len();
        for (rf, to_end) in todo {
            let dom = &self.doc.dom;
            let id = dom.attr(rf, "w:id").unwrap_or("").to_string();
            let note = if to_end { self.doc.notes.footnotes.get(&id) } else { self.doc.notes.endnotes.get(&id) }.copied();
            let Some(note) = note else { continue };
            let root = if to_end { fe_root.unwrap() } else { ef_root.unwrap() };
            let new_id = self.doc.dom.elements(root)
                .filter_map(|k| self.doc.dom.attr(k, "w:id").and_then(|v| v.parse::<i64>().ok())).max().unwrap_or(0).max(0) + 1;
            let ids = new_id.to_string();
            let dom = &mut self.doc.dom;
            dom.detach(note);
            dom.rename(note, if to_end { "w:endnote" } else { "w:footnote" });
            dom.set_attr(note, "w:id", &ids);
            let mut v = Vec::new();
            order(dom, note, &mut v);
            for k in v {
                match dom.name(k) {
                    "w:footnoteRef" if to_end => dom.rename(k, "w:endnoteRef"),
                    "w:endnoteRef" if !to_end => dom.rename(k, "w:footnoteRef"),
                    "w:pStyle" => {
                        let v = dom.attr(k, "w:val").unwrap_or("").to_string();
                        let nv = if to_end { v.replace("FootnoteText", "EndnoteText") } else { v.replace("EndnoteText", "FootnoteText") };
                        dom.set_attr(k, "w:val", &nv);
                    }
                    "w:rStyle" => {
                        let v = dom.attr(k, "w:val").unwrap_or("").to_string();
                        let nv = if to_end { v.replace("FootnoteReference", "EndnoteReference") } else { v.replace("EndnoteReference", "FootnoteReference") };
                        dom.set_attr(k, "w:val", &nv);
                    }
                    _ => {}
                }
            }
            dom.append(root, note);
            dom.rename(rf, if to_end { "w:endnoteReference" } else { "w:footnoteReference" });
            dom.set_attr(rf, "w:id", &ids);
            if let Some(r) = dom.parent(rf) {
                if let Some(rs) = dom.child(r, "w:rPr").and_then(|x| dom.child(x, "w:rStyle")) {
                    dom.set_attr(rs, "w:val", if to_end { "EndnoteReference" } else { "FootnoteReference" });
                }
            }
            if to_end {
                self.doc.notes.footnotes.remove(&id);
                self.doc.notes.endnotes.insert(ids, note);
            } else {
                self.doc.notes.endnotes.remove(&id);
                self.doc.notes.footnotes.insert(ids, note);
            }
        }
        self.commit("Convert Notes", false);
        self.end_group();
        n
    }

    // ------------------------------------------------------------ package parts
    /// A part's XML by name (docProps/core.xml...).
    pub fn package_part(&mut self, name: &str) -> Option<String> {
        if !self.doc.pkg.has(name) {
            return None;
        }
        if let Ok(x) = self.doc.pkg.xml(name) {
            return Some(x.serialize());
        }
        String::from_utf8(self.doc.pkg.raw(name)?.to_vec()).ok()
    }

    /// Write a part (made, typed and related from the package if new).
    pub fn set_package_part(&mut self, name: &str, xml: &str, ctype: &str, rel: &str) -> bool {
        if XmlDoc::parse(xml.as_bytes()).is_err() {
            return false;
        }
        let new = !self.doc.pkg.has(name);
        self.doc.pkg.put_raw(name, xml.as_bytes().to_vec());
        if new {
            if !ctype.is_empty() {
                self.doc.pkg.set_content_type(name, ctype);
            }
            if !rel.is_empty() && !self.doc.pkg.rels("").iter().any(|r| r.kind == rel) {
                self.doc.pkg.add_rel("", rel, name);
            }
        }
        self.modified = true;
        true
    }

    // ------------------------------------------------------------ custom XML
    /// The custom XML part whose root is in namespace `ns` (the
    /// bibliography sources): its XML, or None.
    pub fn custom_xml(&mut self, ns: &str) -> Option<String> {
        let name = self.custom_part(ns)?;
        let raw = self.doc.pkg.raw(&name)?.to_vec();
        if let Ok(x) = self.doc.pkg.xml(&name) {
            return Some(x.serialize());
        }
        String::from_utf8(raw).ok()
    }

    fn custom_part(&mut self, ns: &str) -> Option<String> {
        let names: Vec<String> = self.doc.pkg.part_names().into_iter()
            .filter(|n| n.starts_with("customXml/item") && n.ends_with(".xml") && !n.contains("Props")).collect();
        for n in names {
            let Ok(x) = self.doc.pkg.xml(&n) else { continue };
            let root = x.root;
            let rname = x.name(root).to_string();
            let prefix = rname.split_once(':').map(|(p, _)| p.to_string());
            let attr = match &prefix {
                Some(p) => format!("xmlns:{p}"),
                None => "xmlns".to_string(),
            };
            if x.attr(root, &attr) == Some(ns) {
                return Some(n);
            }
        }
        None
    }

    /// Write the custom XML part in namespace `ns` (made if there is none).
    pub fn set_custom_xml(&mut self, ns: &str, xml: &str) -> bool {
        let Ok(doc) = XmlDoc::parse(xml.as_bytes()) else { return false };
        let name = match self.custom_part(ns) {
            Some(n) => n,
            None => {
                let mut i = 1;
                while self.doc.pkg.has(&format!("customXml/item{i}.xml")) {
                    i += 1;
                }
                let name = format!("customXml/item{i}.xml");
                let props = format!("customXml/itemProps{i}.xml");
                let guid = format!("{{{:08X}-{:04X}-4{:03X}-A{:03X}-{:012X}}}", 0x6A3F21C0u32 + i as u32, i, i, i, i);
                let pxml = format!("<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"no\"?>\
                    <ds:datastoreItem ds:itemID=\"{guid}\" xmlns:ds=\"http://schemas.openxmlformats.org/officeDocument/2006/customXml\">\
                    <ds:schemaRefs><ds:schemaRef ds:uri=\"{ns}\"/></ds:schemaRefs></ds:datastoreItem>");
                self.doc.pkg.put_raw(&props, pxml.into_bytes());
                self.doc.pkg.set_content_type(&props, "application/vnd.openxmlformats-officedocument.customXmlProperties+xml");
                self.doc.pkg.ensure_default("xml", "application/xml");
                self.doc.pkg.add_rel(&name, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/customXmlProps",
                                     &format!("itemProps{i}.xml"));
                let main = self.doc.main.clone();
                let target = crate::package::Package::relative_target(&main, &name);
                let target = if target.starts_with('/') { format!("..{target}") } else { target };
                self.doc.pkg.add_rel(&main, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/customXml", &target);
                name
            }
        };
        self.doc.pkg.put_xml(&name, doc);
        self.modified = true;
        true
    }
}

/// Given paragraphs (XML) as a field's result: the begin in the first, the
/// end in a last one of its own.
fn wrap_given(xml: &str, begin: &str) -> String {
    let wrapped = format!("<w:body xmlns:w=\"{W_NS}\">{xml}</w:body>");
    let Ok(tmp) = XmlDoc::parse(wrapped.as_bytes()) else {
        return format!("<w:p>{begin}<w:r><w:fldChar w:fldCharType=\"end\"/></w:r></w:p>");
    };
    let mut out = String::new();
    let kids: Vec<NodeId> = tmp.elements(tmp.root).collect();
    if kids.is_empty() {
        return format!("<w:p>{begin}<w:r><w:fldChar w:fldCharType=\"end\"/></w:r></w:p>");
    }
    for (i, k) in kids.iter().enumerate() {
        let mut s = tmp.serialize_node(*k);
        s = s.replace(&format!(" xmlns:w=\"{W_NS}\""), "");
        if i == 0 {
            // after the paragraph's properties
            if let Some(e) = s.find("</w:pPr>") {
                s.insert_str(e + 8, begin);
            } else if let Some(e) = s.find('>') {
                if s[..e].ends_with('/') {
                    s = format!("<w:p>{begin}</w:p>");
                } else {
                    s.insert_str(e + 1, begin);
                }
            }
        }
        out.push_str(&s);
    }
    out.push_str("<w:p><w:r><w:fldChar w:fldCharType=\"end\"/></w:r></w:p>");
    out
}
