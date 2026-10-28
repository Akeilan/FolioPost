//! Fields: finding them, working out their results (dates, document
//! properties, page references, sequence numbers...), updating them, and
//! tables of contents.

use super::{Editor, Pos};
use crate::document::W_NS;
use crate::xml::{Kind, NodeId, XmlDoc};
use std::collections::HashMap;

/// A field in the document.
#[derive(Clone, Debug)]
pub struct FieldInfo {
    /// the w:fldChar begin (or the w:fldSimple)
    pub begin: NodeId,
    pub simple: bool,
    pub instr: String,
    pub sep: Option<NodeId>,
    pub end: Option<NodeId>,
    /// how many fields it is inside
    pub depth: usize,
}

impl FieldInfo {
    pub fn kind(&self) -> String {
        self.instr.split_whitespace().next().unwrap_or("").to_ascii_uppercase()
    }
}

/// The parts of a field instruction: its words and quoted strings, and
/// its switches with their arguments.
#[derive(Debug, Default)]
pub struct Instr {
    pub kind: String,
    pub args: Vec<String>,
    pub switches: Vec<(char, Option<String>)>,
}

pub fn parse_instr(s: &str) -> Instr {
    let mut toks: Vec<(String, bool)> = Vec::new();
    let cs: Vec<char> = s.chars().collect();
    let mut i = 0;
    while i < cs.len() {
        let c = cs[i];
        if c.is_whitespace() {
            i += 1;
            continue;
        }
        if c == '"' {
            let mut t = String::new();
            i += 1;
            while i < cs.len() && cs[i] != '"' {
                if cs[i] == '\\' && i + 1 < cs.len() && cs[i + 1] == '"' {
                    i += 1;
                }
                t.push(cs[i]);
                i += 1;
            }
            i += 1;
            toks.push((t, true));
            continue;
        }
        let mut t = String::new();
        while i < cs.len() && !cs[i].is_whitespace() && cs[i] != '"' {
            t.push(cs[i]);
            i += 1;
        }
        toks.push((t, false));
    }
    let mut out = Instr::default();
    let mut k = 0;
    if let Some((t, _)) = toks.first() {
        out.kind = t.to_ascii_uppercase();
        k = 1;
    }
    while k < toks.len() {
        let (t, quoted) = &toks[k];
        if !quoted && t.starts_with('\\') && t.chars().count() >= 2 {
            let sw = t.chars().nth(1).unwrap();
            // the switch's argument, unless the next word is another switch
            let arg = toks.get(k + 1).filter(|(n, q)| *q || !n.starts_with('\\')).map(|(n, _)| n.clone());
            let takes_arg = matches!(sw, '@' | '#' | '*' | 'o' | 't' | 'f' | 'l' | 'b' | 'c' | 'r' | 's' | 'd' | 'p' | 'a');
            if takes_arg && arg.is_some() {
                out.switches.push((sw, arg));
                k += 2;
            } else {
                out.switches.push((sw, None));
                k += 1;
            }
        } else {
            out.args.push(t.clone());
            k += 1;
        }
    }
    out
}

/// A date with a Word date picture (\@ "dddd, MMMM d, yyyy").
pub fn format_date<T: chrono::Datelike + chrono::Timelike>(d: &T, pic: &str) -> String {
    const MONTHS: [&str; 12] = ["January", "February", "March", "April", "May", "June", "July", "August",
                                "September", "October", "November", "December"];
    const DAYS: [&str; 7] = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
    let cs: Vec<char> = pic.chars().collect();
    let mut out = String::new();
    let mut i = 0;
    let ampm = pic.to_ascii_lowercase().contains("am/pm");
    while i < cs.len() {
        let c = cs[i];
        let mut n = 1;
        while i + n < cs.len() && cs[i + n] == c {
            n += 1;
        }
        match c {
            '\'' => {
                // a literal
                i += 1;
                while i < cs.len() && cs[i] != '\'' {
                    out.push(cs[i]);
                    i += 1;
                }
                i += 1;
                continue;
            }
            'd' | 'D' => {
                let s = match n {
                    1 => d.day().to_string(),
                    2 => format!("{:02}", d.day()),
                    3 => DAYS[d.weekday().num_days_from_monday() as usize][..3].to_string(),
                    _ => DAYS[d.weekday().num_days_from_monday() as usize].to_string(),
                };
                out.push_str(&s);
            }
            'M' => {
                let m = d.month() as usize;
                let s = match n {
                    1 => m.to_string(),
                    2 => format!("{:02}", m),
                    3 => MONTHS[m - 1][..3].to_string(),
                    _ => MONTHS[m - 1].to_string(),
                };
                out.push_str(&s);
            }
            'y' | 'Y' => {
                if n <= 2 {
                    out.push_str(&format!("{:02}", d.year() % 100));
                } else {
                    out.push_str(&d.year().to_string());
                }
            }
            'h' => {
                let h = d.hour() % 12;
                let h = if h == 0 { 12 } else { h };
                out.push_str(&if n >= 2 { format!("{:02}", h) } else { h.to_string() });
            }
            'H' => out.push_str(&if n >= 2 { format!("{:02}", d.hour()) } else { d.hour().to_string() }),
            'm' => out.push_str(&if n >= 2 { format!("{:02}", d.minute()) } else { d.minute().to_string() }),
            's' | 'S' => out.push_str(&if n >= 2 { format!("{:02}", d.second()) } else { d.second().to_string() }),
            'A' | 'a' if ampm && pic[pic.char_indices().nth(i).map(|x| x.0).unwrap_or(0)..].to_ascii_lowercase().starts_with("am/pm") => {
                let pm = d.hour() >= 12;
                let upper = c == 'A';
                out.push_str(match (pm, upper) {
                    (true, true) => "PM",
                    (false, true) => "AM",
                    (true, false) => "pm",
                    (false, false) => "am",
                });
                i += 5;
                continue;
            }
            _ => {
                for _ in 0..n {
                    out.push(c);
                }
            }
        }
        i += n;
    }
    out
}

/// A number in a field's \* format: roman / ROMAN, alphabetic /
/// ALPHABETIC, Ordinal, CardText, OrdText, Arabic.
pub(crate) fn number_format(n: i64, sw: &str) -> String {
    let upper = sw.chars().filter(|c| c.is_alphabetic()).all(|c| c.is_ascii_uppercase());
    let fmt = match sw.to_ascii_lowercase().as_str() {
        "roman" => if upper { "upperRoman" } else { "lowerRoman" },
        "alphabetic" => if upper { "upperLetter" } else { "lowerLetter" },
        "ordinal" => "ordinal",
        "cardtext" => "cardinalText",
        "ordtext" => "ordinalText",
        _ => "decimal",
    };
    crate::numbering::format_number(n as i32, fmt)
}

/// Apply \* text formats and \# number pictures to a result.
fn apply_format(v: String, ins: &Instr) -> String {
    let mut v = v;
    for (sw, arg) in &ins.switches {
        let Some(a) = arg else { continue };
        match sw {
            '*' => {
                let n: Option<i64> = v.trim().parse().ok();
                v = match a.to_ascii_lowercase().as_str() {
                    "upper" => v.to_uppercase(),
                    "lower" => v.to_lowercase(),
                    "caps" => v.split(' ').map(|w| {
                        let mut c = w.chars();
                        match c.next() {
                            Some(f) => f.to_uppercase().collect::<String>() + &c.as_str().to_lowercase(),
                            None => String::new(),
                        }
                    }).collect::<Vec<_>>().join(" "),
                    "firstcap" => {
                        let mut c = v.chars();
                        match c.next() {
                            Some(f) => f.to_uppercase().collect::<String>() + c.as_str(),
                            None => v,
                        }
                    }
                    "roman" | "alphabetic" | "ordinal" | "cardtext" | "ordtext" | "arabic" => match n {
                        Some(n) => number_format(n, a),
                        None => v,
                    },
                    _ => v,
                };
            }
            '#' => {
                if let Ok(x) = v.trim().replace(',', "").parse::<f64>() {
                    v = number_picture(x, a);
                }
            }
            _ => {}
        }
    }
    v
}

/// A number with a picture like "#,##0.00" or "0".
fn number_picture(x: f64, pic: &str) -> String {
    let decimals = pic.split('.').nth(1).map(|d| d.chars().filter(|c| *c == '0' || *c == '#').count()).unwrap_or(0);
    let grouped = pic.contains(',');
    let s = format!("{:.*}", decimals, x.abs());
    let (int, frac) = match s.split_once('.') {
        Some((a, b)) => (a.to_string(), Some(b.to_string())),
        None => (s.clone(), None),
    };
    let int = if grouped {
        let b: Vec<char> = int.chars().collect();
        let mut o = String::new();
        for (i, c) in b.iter().enumerate() {
            if i > 0 && (b.len() - i) % 3 == 0 {
                o.push(',');
            }
            o.push(*c);
        }
        o
    } else {
        int
    };
    let prefix: String = pic.chars().take_while(|c| !matches!(c, '#' | '0' | ',' | '.')).collect();
    let mut out = format!("{}{}{}", if x < 0.0 { "-" } else { "" }, prefix, int);
    if let Some(f) = frac {
        out.push('.');
        out.push_str(&f);
    }
    out
}

/// Text into a run, a line break for each newline.
fn append_text_lines(dom: &mut XmlDoc, r: NodeId, text: &str) {
    for (i, line) in text.split('\n').enumerate() {
        if i > 0 {
            let br = dom.new_element("w:br", &[]);
            dom.append(r, br);
        }
        if !line.is_empty() || i == 0 {
            let t = dom.new_element("w:t", &[("xml:space", "preserve")]);
            let tx = dom.new_text(line);
            dom.append(t, tx);
            dom.append(r, t);
        }
    }
}

pub(super) fn esc(s: &str) -> String {
    let mut o = String::new();
    crate::xml::escape_text(s, &mut o);
    o
}

/// Nodes of a subtree in document order.
pub(super) fn order(dom: &XmlDoc, root: NodeId, out: &mut Vec<NodeId>) {
    out.push(root);
    for &c in dom.children(root) {
        if matches!(dom.node(c).kind, Kind::Element { .. }) {
            order(dom, c, out);
        }
    }
}

fn order_contains(dom: &XmlDoc, root: NodeId, n: NodeId) -> bool {
    let mut x = Some(n);
    while let Some(k) = x {
        if k == root {
            return true;
        }
        x = dom.parent(k);
    }
    false
}

pub(super) fn para_of(dom: &XmlDoc, mut n: NodeId) -> Option<NodeId> {
    loop {
        if dom.is(n, "w:p") {
            return Some(n);
        }
        n = dom.parent(n)?;
    }
}

fn run_of(dom: &XmlDoc, mut n: NodeId) -> Option<NodeId> {
    loop {
        if dom.is(n, "w:r") {
            return Some(n);
        }
        if dom.is(n, "w:p") {
            return None;
        }
        n = dom.parent(n)?;
    }
}

/// The text of a paragraph as a heading shows in a table of contents.
pub(super) fn heading_text(s: &str) -> String {
    let t: String = s.chars().map(|c| match c {
        '\t' | '\n' | '\u{b}' => ' ',
        c => c,
    }).filter(|c| *c != '\u{fffc}' && *c != '\u{c}').collect();
    t.split_whitespace().collect::<Vec<_>>().join(" ")
}

impl Editor {
    /// All fields under `root`, in document order.
    pub fn fields_in(&self, root: NodeId) -> Vec<FieldInfo> {
        let dom = &self.doc.dom;
        let mut nodes = Vec::new();
        order(dom, root, &mut nodes);
        let mut out: Vec<FieldInfo> = Vec::new();
        let mut open: Vec<usize> = Vec::new();
        for n in nodes {
            match dom.name(n) {
                "w:fldChar" => match dom.attr(n, "w:fldCharType") {
                    Some("begin") => {
                        out.push(FieldInfo { begin: n, simple: false, instr: String::new(), sep: None, end: None,
                                             depth: open.len() });
                        open.push(out.len() - 1);
                    }
                    Some("separate") => {
                        if let Some(&i) = open.last() {
                            out[i].sep = Some(n);
                        }
                    }
                    Some("end") => {
                        if let Some(i) = open.pop() {
                            out[i].end = Some(n);
                        }
                    }
                    _ => {}
                },
                "w:instrText" => {
                    if let Some(&i) = open.last() {
                        if out[i].sep.is_none() {
                            let t = dom.text(n);
                            out[i].instr.push_str(&t);
                        }
                    }
                }
                "w:fldSimple" => {
                    out.push(FieldInfo { begin: n, simple: true, instr: dom.attr(n, "w:instr").unwrap_or("").to_string(),
                                         sep: None, end: None, depth: open.len() });
                }
                _ => {}
            }
        }
        out
    }

    /// The fields in the body and the headers, footers and notes.
    pub fn all_fields(&self) -> Vec<FieldInfo> {
        let mut v = self.fields_in(self.doc.body);
        for p in &self.doc.parts {
            v.extend(self.fields_in(p.root));
        }
        v
    }

    /// Bookmarks: name -> (start, end).
    pub(super) fn bookmarks(&self) -> HashMap<String, (NodeId, Option<NodeId>)> {
        let dom = &self.doc.dom;
        let mut nodes = Vec::new();
        order(dom, self.doc.body, &mut nodes);
        let mut by_id: HashMap<String, String> = HashMap::new();
        let mut out = HashMap::new();
        for n in nodes {
            if dom.is(n, "w:bookmarkStart") {
                let name = dom.attr(n, "w:name").unwrap_or("").to_string();
                by_id.insert(dom.attr(n, "w:id").unwrap_or("").to_string(), name.clone());
                out.insert(name, (n, None));
            } else if dom.is(n, "w:bookmarkEnd") {
                if let Some(name) = by_id.get(dom.attr(n, "w:id").unwrap_or("")) {
                    if let Some(e) = out.get_mut(name) {
                        e.1 = Some(n);
                    }
                }
            }
        }
        out
    }

    /// The page a node of the body is on (its paragraph's first line).
    pub(super) fn page_of(&self, n: NodeId) -> Option<usize> {
        let p = para_of(&self.doc.dom, n)?;
        let &pi = self.layout.index.get(&p)?;
        let off = {
            // the position of the node in its paragraph
            let pl = &self.layout.paras[pi];
            let mut best = 0;
            for (pc, u) in pl.pieces.iter().zip(0..) {
                let _ = u;
                if let Some(node) = pc.node {
                    if node == n || self.doc.dom.parent(node) == Some(n) {
                        break;
                    }
                }
                best += pc.item.len();
            }
            best
        };
        let pl = &self.layout.paras[pi];
        let li = pl.lines.iter().position(|l| off < l.pos_end || l.pos_end >= pl.text_len).unwrap_or(0);
        for (pg, page) in self.layout.pages.iter().enumerate() {
            if page.lines.iter().any(|l| l.para == pi && l.line == li) {
                return Some(pg);
            }
        }
        self.layout.pages.iter().position(|page| page.lines.iter().any(|l| l.para == pi))
    }

    pub(super) fn page_label(&self, pg: usize) -> String {
        let Some(page) = self.layout.pages.get(pg) else { return "1".into() };
        let fmt = self.doc.sections.get(page.section).map(|s| s.pg_fmt.clone()).unwrap_or_else(|| "decimal".into());
        crate::numbering::format_number(page.number, &fmt)
    }

    /// The text between a bookmark's start and end.
    fn bookmark_text(&self, start: NodeId, end: Option<NodeId>) -> String {
        let dom = &self.doc.dom;
        let mut nodes = Vec::new();
        order(dom, self.doc.body, &mut nodes);
        let mut on = false;
        let mut s = String::new();
        let mut stack: Vec<bool> = Vec::new();
        for n in nodes {
            if n == start {
                on = true;
                continue;
            }
            if Some(n) == end {
                break;
            }
            if !on {
                continue;
            }
            let shown = stack.iter().all(|c| !c);
            match dom.name(n) {
                "w:fldChar" => match dom.attr(n, "w:fldCharType") {
                    Some("begin") => stack.push(true),
                    Some("separate") => {
                        if let Some(l) = stack.last_mut() {
                            *l = false;
                        }
                    }
                    Some("end") => {
                        stack.pop();
                    }
                    _ => {}
                },
                "w:t" if shown => s.push_str(&dom.text(n)),
                "w:tab" if shown => s.push('\t'),
                "w:p" if !s.is_empty() => s.push(' '),
                _ => {}
            }
        }
        s.trim().to_string()
    }

    pub(super) fn core_prop_pub(&self, name: &str) -> Option<String> {
        self.core_prop(name)
    }

    fn core_prop(&self, name: &str) -> Option<String> {
        let raw = self.doc.pkg.raw("docProps/core.xml")?;
        let x = XmlDoc::parse(raw).ok()?;
        let n = x.elements(x.root).find(|&c| x.name(c) == name || x.name(c).ends_with(&format!(":{}", name.split(':').last().unwrap_or(name))))?;
        Some(x.text(n))
    }

    fn app_prop(&self, name: &str) -> Option<String> {
        let raw = self.doc.pkg.raw("docProps/app.xml")?;
        let x = XmlDoc::parse(raw).ok()?;
        let n = x.elements(x.root).find(|&c| x.name(c).trim_start_matches("ep:") == name || x.name(c) == name)?;
        Some(x.text(n))
    }

    /// Words and characters in the body.
    pub fn counts(&self) -> (usize, usize) {
        let mut words = 0;
        let mut chars = 0;
        for p in &self.layout.paras[..self.layout.body_count.min(self.layout.paras.len())] {
            let mut in_word = false;
            for u in p.units.iter().filter(|u| !u.gen) {
                if let crate::layout::UnitKind::Char(c) = u.kind {
                    chars += 1;
                    if c.is_whitespace() {
                        in_word = false;
                    } else if !in_word {
                        in_word = true;
                        words += 1;
                    }
                } else {
                    in_word = false;
                }
            }
        }
        (words, chars)
    }

    /// What a field shows now (None: one we leave as it is).
    pub fn evaluate_field(&self, instr: &str, at: Option<NodeId>, seq: &mut HashMap<String, i64>) -> Option<String> {
        let ins = parse_instr(instr);
        let pic = ins.switches.iter().find(|(s, _)| *s == '@').and_then(|(_, a)| a.clone());
        let v = match ins.kind.as_str() {
            "DATE" | "TIME" => {
                let now = chrono::Local::now();
                let pic = pic.clone().unwrap_or_else(|| if ins.kind == "TIME" { "h:mm am/pm".into() } else { "M/d/yyyy".into() });
                format_date(&now, &pic)
            }
            "CREATEDATE" | "SAVEDATE" | "PRINTDATE" => {
                let key = match ins.kind.as_str() {
                    "CREATEDATE" => "dcterms:created",
                    "SAVEDATE" => "dcterms:modified",
                    _ => "cp:lastPrinted",
                };
                let s = self.core_prop(key)?;
                let d = chrono::DateTime::parse_from_rfc3339(s.trim()).ok()?.with_timezone(&chrono::Local);
                format_date(&d, &pic.clone().unwrap_or_else(|| "M/d/yyyy h:mm:ss am/pm".into()))
            }
            "AUTHOR" => self.core_prop("dc:creator").unwrap_or_default(),
            "TITLE" => self.core_prop("dc:title").unwrap_or_default(),
            "SUBJECT" => self.core_prop("dc:subject").unwrap_or_default(),
            "KEYWORDS" => self.core_prop("cp:keywords").unwrap_or_default(),
            "COMMENTS" => self.core_prop("dc:description").unwrap_or_default(),
            "LASTSAVEDBY" => self.core_prop("cp:lastModifiedBy").unwrap_or_default(),
            "REVNUM" => self.core_prop("cp:revision").unwrap_or_default(),
            "DOCPROPERTY" => {
                let name = ins.args.first()?.clone();
                match name.to_ascii_lowercase().as_str() {
                    "title" => self.core_prop("dc:title"),
                    "subject" => self.core_prop("dc:subject"),
                    "author" => self.core_prop("dc:creator"),
                    "keywords" => self.core_prop("cp:keywords"),
                    "comments" => self.core_prop("dc:description"),
                    "company" => self.app_prop("Company"),
                    "manager" => self.app_prop("Manager"),
                    _ => None,
                }
                .unwrap_or_default()
            }
            "FILENAME" => {
                let full = ins.switches.iter().any(|(s, _)| *s == 'p');
                if full {
                    self.file_name.clone()
                } else {
                    self.file_name.rsplit('/').next().unwrap_or("").to_string()
                }
            }
            "NUMPAGES" => self.layout.pages.len().to_string(),
            "PAGE" => {
                let pg = at.and_then(|n| self.page_of(n)).unwrap_or(0);
                self.page_label(pg)
            }
            "SECTIONPAGES" => {
                let pg = at.and_then(|n| self.page_of(n)).unwrap_or(0);
                let sec = self.layout.pages.get(pg).map(|p| p.section).unwrap_or(0);
                self.layout.pages.iter().filter(|p| p.section == sec).count().to_string()
            }
            "NUMWORDS" => self.counts().0.to_string(),
            "NUMCHARS" => self.counts().1.to_string(),
            "SEQ" => {
                let name = ins.args.first()?.to_ascii_lowercase();
                let cur = seq.entry(name).or_insert(0);
                let mut shown = None;
                for (sw, arg) in &ins.switches {
                    match sw {
                        'r' => {
                            if let Some(n) = arg.as_ref().and_then(|a| a.parse::<i64>().ok()) {
                                *cur = n;
                                shown = Some(n);
                            }
                        }
                        'c' => shown = Some(*cur),
                        _ => {}
                    }
                }
                let n = match shown {
                    Some(n) => n,
                    None => {
                        *cur += 1;
                        *cur
                    }
                };
                if ins.switches.iter().any(|(s, _)| *s == 'h') {
                    String::new()
                } else {
                    n.to_string()
                }
            }
            "REF" | "PAGEREF" | "NOTEREF" => {
                let name = ins.args.first()?.clone();
                let marks = self.bookmarks();
                let Some(&(start, end)) = marks.get(&name) else {
                    return Some("Error! Reference source not found.".into());
                };
                match ins.kind.as_str() {
                    "PAGEREF" => self.page_label(self.page_of(start).unwrap_or(0)),
                    "NOTEREF" => {
                        // the mark of the note referenced inside the bookmark
                        let dom = &self.doc.dom;
                        let mut nodes = Vec::new();
                        order(dom, self.doc.body, &mut nodes);
                        let mut on = false;
                        let mut mark = None;
                        for n in nodes {
                            if n == start {
                                on = true;
                            }
                            if Some(n) == end {
                                break;
                            }
                            if on && (dom.is(n, "w:footnoteReference") || dom.is(n, "w:endnoteReference")) {
                                mark = self.doc.notes.numbers.get(&n).cloned();
                                break;
                            }
                        }
                        mark?
                    }
                    _ if ins.switches.iter().any(|(s, _)| *s == 'p') => {
                        // above / below the reference
                        let dom = &self.doc.dom;
                        let mut nodes = Vec::new();
                        order(dom, self.doc.body, &mut nodes);
                        let ia = nodes.iter().position(|&n| n == start).unwrap_or(0);
                        let ib = at.and_then(|a| nodes.iter().position(|&n| n == a)).unwrap_or(usize::MAX);
                        if ia < ib { "above".into() } else { "below".into() }
                    }
                    _ => self.bookmark_text(start, end),
                }
            }
            _ => return None,
        };
        let v = if ins.kind == "DATE" || ins.kind == "TIME" { v } else { apply_format(v, &ins) };
        Some(v)
    }

    /// Replace a field's result with `text`.
    pub(super) fn set_field_result(&mut self, f: &FieldInfo, text: &str) {
        let dom_ro = &self.doc.dom;
        if f.simple {
            let fs = f.begin;
            let runs: Vec<NodeId> = dom_ro.elements(fs).filter(|&c| dom_ro.is(c, "w:r")).collect();
            let like = runs.first().copied();
            let rpr = like.and_then(|r| dom_ro.child(r, "w:rPr"));
            let dom = &mut self.doc.dom;
            let rpr_copy = rpr.map(|r| dom.clone_node(r));
            for r in runs {
                dom.detach(r);
            }
            let r = dom.new_element("w:r", &[]);
            if let Some(c) = rpr_copy {
                dom.append(r, c);
            }
            let t = dom.new_element("w:t", &[("xml:space", "preserve")]);
            let tx = dom.new_text(text);
            dom.append(t, tx);
            dom.append(r, t);
            dom.append(fs, r);
            return;
        }
        let Some(end) = f.end else { return };
        let Some(end_run) = run_of(dom_ro, end) else { return };
        let Some(para) = para_of(dom_ro, end) else { return };
        let sep = match f.sep {
            Some(s) => s,
            None => {
                // no result yet: a separator before the end
                let dom = &mut self.doc.dom;
                let r = dom.new_element("w:r", &[]);
                let c = dom.new_element("w:fldChar", &[("w:fldCharType", "separate")]);
                dom.append(r, c);
                let parent = dom.parent(end_run).unwrap();
                let idx = dom.index_in_parent(end_run).unwrap();
                dom.insert(parent, idx, r);
                c
            }
        };
        let dom_ro = &self.doc.dom;
        let Some(sep_run) = run_of(dom_ro, sep) else { return };
        if para_of(dom_ro, sep) != Some(para) {
            return; // results spanning paragraphs are left alone
        }
        // the result runs: between the separator's run and the end's run
        let mut nodes = Vec::new();
        order(dom_ro, para, &mut nodes);
        let mut between: Vec<NodeId> = Vec::new();
        let mut on = false;
        for n in nodes {
            if n == sep_run {
                on = true;
                continue;
            }
            if n == end_run {
                break;
            }
            if on && dom_ro.is(n, "w:r") && run_of(dom_ro, n) == Some(n) {
                between.push(n);
            }
        }
        let keep = between.iter().copied().find(|&r| dom_ro.child(r, "w:t").is_some());
        let dom = &mut self.doc.dom;
        match keep {
            Some(r) => {
                for k in dom.elements(r).collect::<Vec<_>>() {
                    if !dom.is(k, "w:rPr") {
                        dom.detach(k);
                    }
                }
                append_text_lines(dom, r, text);
                for o in between {
                    if o != r {
                        dom.detach(o);
                    }
                }
            }
            None => {
                for o in between {
                    dom.detach(o);
                }
                let r = dom.new_element("w:r", &[]);
                if let Some(rp) = dom.child(sep_run, "w:rPr") {
                    let c = dom.clone_node(rp);
                    dom.append(r, c);
                }
                append_text_lines(dom, r, text);
                let parent = dom.parent(end_run).unwrap();
                let idx = dom.index_in_parent(end_run).unwrap();
                dom.insert(parent, idx, r);
            }
        }
    }

    /// Update fields: all of them, or those touching the selection. Tables
    /// of contents are rebuilt. Returns how many changed.
    pub fn update_fields(&mut self, all: bool) -> usize {
        self.update_fields_where(all, &|_| true)
    }

    fn update_fields_where(&mut self, all: bool, want: &dyn Fn(&str) -> bool) -> usize {
        self.begin_group("Update Field");
        let mut n = 0;
        // tables of contents first (their page numbers come after)
        let tocs: Vec<FieldInfo> = self.fields_in(self.doc.body).into_iter()
            .filter(|f| matches!(f.kind().as_str(), "TOC" | "INDEX" | "TOA") && want(&f.kind()) && (all || self.field_selected(f))).collect();
        for t in tocs {
            if self.rebuild_toc(&t) {
                n += 1;
            }
        }
        for pass in 0..2 {
            let fields = self.all_fields();
            let mut seq = HashMap::new();
            let mut todo = Vec::new();
            for f in &fields {
                let k = f.kind();
                if matches!(k.as_str(), "TOC" | "INDEX" | "TOA" | "BIBLIOGRAPHY" | "XE" | "TA" | "CITATION") || (pass == 1 && k != "PAGEREF" && k != "PAGE" && k != "NUMPAGES") {
                    // still count SEQ fields so numbering stays right
                    if k == "SEQ" && pass == 0 {
                        self.evaluate_field(&f.instr, Some(f.begin), &mut seq);
                    }
                    continue;
                }
                if !(all || self.field_selected(f)) || !want(&k) {
                    if k == "SEQ" {
                        self.evaluate_field(&f.instr, Some(f.begin), &mut seq);
                    }
                    continue;
                }
                if let Some(v) = self.evaluate_field(&f.instr, Some(f.begin), &mut seq) {
                    if self.field_result(f) != v {
                        todo.push((f.clone(), v));
                    }
                }
            }
            if todo.is_empty() {
                break;
            }
            self.begin();
            for (f, v) in &todo {
                self.set_field_result(f, v);
            }
            n += todo.len();
            self.commit("Update Field", false);
        }
        self.end_group();
        n
    }

    /// The text a field shows now.
    pub fn field_result(&self, f: &FieldInfo) -> String {
        let dom = &self.doc.dom;
        if f.simple {
            let mut s = String::new();
            let mut nodes = Vec::new();
            order(dom, f.begin, &mut nodes);
            for n in nodes {
                if dom.is(n, "w:t") {
                    s.push_str(&dom.text(n));
                }
            }
            return s;
        }
        let (Some(sep), Some(end)) = (f.sep, f.end) else { return String::new() };
        let Some(para) = para_of(dom, sep) else { return String::new() };
        let multi = para_of(dom, end) != Some(para);
        let root = if multi {
            // a table: its paragraphs share a parent (the body, a content control)
            let mut r = dom.parent(para).unwrap_or(para);
            while !order_contains(dom, r, end) {
                match dom.parent(r) {
                    Some(x) => r = x,
                    None => break,
                }
            }
            r
        } else {
            para
        };
        let mut nodes = Vec::new();
        order(dom, root, &mut nodes);
        let mut on = false;
        let mut s = String::new();
        for n in nodes {
            if n == sep {
                on = true;
            }
            if n == end {
                break;
            }
            if !on {
                continue;
            }
            match dom.name(n) {
                "w:t" => s.push_str(&dom.text(n)),
                "w:tab" if multi && dom.parent(n).map_or(false, |r| dom.is(r, "w:r")) => s.push('\t'),
                "w:p" if multi => s.push('\n'),
                _ => {}
            }
        }
        s
    }

    /// Does the selection (or the caret) touch the field.
    pub(super) fn field_selected(&self, f: &FieldInfo) -> bool {
        let dom = &self.doc.dom;
        let Some(p) = para_of(dom, f.begin) else { return false };
        let (a, b) = self.selection();
        let paras = self.paras_between(a.para, b.para);
        if paras.contains(&p) {
            return true;
        }
        // a field spanning paragraphs (a table of contents)
        if let Some(e) = f.end.and_then(|e| para_of(dom, e)) {
            let span = self.paras_between(p, e);
            return span.contains(&a.para) || span.contains(&b.para);
        }
        false
    }

    /// Insert a field and show its result straight away.
    pub fn insert_field_now(&mut self, instr: &str) {
        let mut seq = HashMap::new();
        let v = self.evaluate_field(instr, None, &mut seq).unwrap_or_default();
        self.insert_field(instr, &v);
        if matches!(parse_instr(instr).kind.as_str(), "PAGE" | "PAGEREF" | "SEQ" | "NUMPAGES") {
            self.update_fields(true);
        }
    }

    // --------------------------------------------------------- contents
    pub(super) fn ensure_toc_styles(&mut self, levels: usize) {
        let mut want: Vec<(String, String)> = Vec::new();
        if !self.doc.styles.styles.contains_key("TOCHeading") {
            let based = if self.doc.styles.styles.contains_key("Heading1") { "Heading1" } else { "Normal" };
            want.push(("TOCHeading".into(), format!(
                "<w:style w:type=\"paragraph\" w:styleId=\"TOCHeading\"><w:name w:val=\"TOC Heading\"/>\
                 <w:basedOn w:val=\"{based}\"/><w:next w:val=\"Normal\"/><w:uiPriority w:val=\"39\"/><w:unhideWhenUsed/>\
                 <w:qFormat/><w:pPr><w:outlineLvl w:val=\"9\"/></w:pPr></w:style>")));
        }
        for l in 1..=levels.min(9) {
            let id = format!("TOC{l}");
            if !self.doc.styles.styles.contains_key(&id) {
                let ind = (l - 1) * 220;
                let ind = if ind > 0 { format!("<w:ind w:left=\"{ind}\"/>") } else { String::new() };
                want.push((id.clone(), format!(
                    "<w:style w:type=\"paragraph\" w:styleId=\"{id}\"><w:name w:val=\"toc {l}\"/>\
                     <w:basedOn w:val=\"Normal\"/><w:next w:val=\"Normal\"/><w:autoRedefine/><w:uiPriority w:val=\"39\"/>\
                     <w:unhideWhenUsed/><w:pPr><w:spacing w:after=\"100\"/>{ind}</w:pPr></w:style>")));
            }
        }
        for (_, xml) in want {
            self.add_style_xml(&xml);
        }
    }

    /// The headings a table of contents lists: (paragraph, level 1-9, text).
    pub(crate) fn toc_headings(&self, from: usize, to: usize, skip: Option<(NodeId, NodeId)>) -> Vec<(NodeId, usize, String)> {
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
            if !dom.is(n, "w:p") {
                continue;
            }
            let (pp, _) = self.doc.para_props(n);
            let Some(lvl) = pp.outline_lvl else { continue };
            let level = lvl as usize + 1;
            if level < from || level > to {
                continue;
            }
            let t = heading_text(&self.doc.para_text(n));
            if !t.is_empty() {
                out.push((n, level, t));
            }
        }
        out
    }

    /// A _Toc bookmark around the heading (an existing one if it has it).
    pub(super) fn toc_bookmark(&mut self, p: NodeId, next_id: &mut i64, used: &mut Vec<String>) -> String {
        let dom = &self.doc.dom;
        if let Some(b) = dom.elements(p).find(|&c| dom.is(c, "w:bookmarkStart")
            && dom.attr(c, "w:name").map_or(false, |n| n.starts_with("_Toc"))) {
            let name = dom.attr(b, "w:name").unwrap().to_string();
            if !used.contains(&name) {
                used.push(name.clone());
                return name;
            }
        }
        let mut k = 100_000_000 + *next_id * 7919;
        let mut name = format!("_Toc{k}");
        while used.contains(&name) {
            k += 1;
            name = format!("_Toc{k}");
        }
        used.push(name.clone());
        let id = next_id.to_string();
        *next_id += 1;
        let dom = &mut self.doc.dom;
        let s = dom.new_element("w:bookmarkStart", &[("w:id", &id), ("w:name", &name)]);
        let e = dom.new_element("w:bookmarkEnd", &[("w:id", &id)]);
        let first = dom.elements(p).position(|c| !dom.is(c, "w:pPr")).map(|i| i).unwrap_or(0);
        let idx = dom.elements(p).nth(first).and_then(|c| dom.index_in_parent(c)).unwrap_or(dom.children(p).len());
        dom.insert(p, idx, s);
        dom.append(p, e);
        name
    }

    pub(super) fn max_bookmark_id(&self) -> i64 {
        let dom = &self.doc.dom;
        let mut nodes = Vec::new();
        order(dom, self.doc.body, &mut nodes);
        nodes.iter().filter(|&&n| dom.is(n, "w:bookmarkStart"))
            .filter_map(|&n| dom.attr(n, "w:id").and_then(|v| v.parse::<i64>().ok()))
            .max().unwrap_or(0)
    }

    /// The entry paragraphs of a table of contents (XML), the field's
    /// begin in the first and its end in the last.
    fn toc_paragraphs_xml(&mut self, instr: &str, skip: Option<(NodeId, NodeId)>) -> String {
        self.table_xml(instr, skip, None)
    }

    pub(super) fn import_paras(&mut self, xml: &str) -> Vec<NodeId> {
        let wrapped = format!("<w:body xmlns:w=\"{W_NS}\">{xml}</w:body>");
        let Ok(tmp) = XmlDoc::parse(wrapped.as_bytes()) else { return Vec::new() };
        let kids: Vec<NodeId> = tmp.elements(tmp.root).collect();
        kids.into_iter().map(|k| self.doc.dom.import_node(&tmp, k)).collect()
    }

    /// Insert a table of contents at the caret: `title` above it ("Contents"
    /// or "Table of Contents"), headings 1-3, with links.
    pub fn insert_toc(&mut self, title: Option<&str>) {
        if self.story != super::Story::Body {
            return;
        }
        let instr = "TOC \\o \"1-3\" \\h \\z \\u";
        self.begin_group("Table of Contents");
        self.ensure_toc_styles(3);
        self.begin();
        self.delete_selection();
        let mut p = self.caret.para;
        if self.caret.off > 0 {
            p = self.split_para(p, self.caret.off);
            self.doc.scan();
        }
        let entries = self.toc_paragraphs_xml(instr, None);
        let head = title.map(|t| format!("<w:p><w:pPr><w:pStyle w:val=\"TOCHeading\"/></w:pPr><w:r><w:t>{}</w:t></w:r></w:p>", esc(t)))
            .unwrap_or_default();
        let sdt = format!(
            "<w:sdt><w:sdtPr><w:docPartObj><w:docPartGallery w:val=\"Table of Contents\"/><w:docPartUnique/></w:docPartObj></w:sdtPr>\
             <w:sdtContent>{head}{entries}</w:sdtContent></w:sdt>");
        let nodes = self.import_paras(&sdt);
        let dom = &mut self.doc.dom;
        let parent = dom.parent(p).unwrap();
        let mut idx = dom.index_in_parent(p).unwrap();
        for n in nodes {
            dom.insert(parent, idx, n);
            idx += 1;
        }
        self.caret = Pos { para: p, off: 0 };
        self.anchor = self.caret;
        self.commit("Table of Contents", false);
        // page numbers, now that it is laid out
        self.update_toc_pages();
        self.end_group();
    }

    /// Fill in the page numbers of the tables of contents.
    pub(super) fn update_toc_pages(&mut self) {
        for _ in 0..2 {
            let fields = self.fields_in(self.doc.body);
            let mut seq = HashMap::new();
            let mut todo = Vec::new();
            for f in fields.iter().filter(|f| f.kind() == "PAGEREF" && f.depth > 0) {
                if let Some(v) = self.evaluate_field(&f.instr, Some(f.begin), &mut seq) {
                    if self.field_result(f) != v {
                        todo.push((f.clone(), v));
                    }
                }
            }
            if todo.is_empty() {
                return;
            }
            self.begin();
            for (f, v) in &todo {
                self.set_field_result(f, v);
            }
            self.commit("Table of Contents", false);
        }
    }

    /// The paragraphs a field spans (begin's to end's).
    pub(super) fn field_paras(&self, f: &FieldInfo) -> Vec<NodeId> {
        let dom = &self.doc.dom;
        let (Some(a), Some(b)) = (para_of(dom, f.begin), f.end.and_then(|e| para_of(dom, e))) else { return Vec::new() };
        let pa = dom.parent(a);
        if pa != dom.parent(b) {
            return Vec::new();
        }
        let kids: Vec<NodeId> = dom.elements(pa.unwrap()).collect();
        let (Some(i), Some(j)) = (kids.iter().position(|&k| k == a), kids.iter().position(|&k| k == b)) else { return Vec::new() };
        kids[i..=j].to_vec()
    }

    /// Rebuild a table of contents from the headings now.
    fn rebuild_toc(&mut self, f: &FieldInfo) -> bool {
        self.rebuild_table(f)
    }

    /// Update the tables of contents only.
    pub fn update_toc(&mut self) -> bool {
        let tocs: Vec<FieldInfo> = self.fields_in(self.doc.body).into_iter()
            .filter(|f| matches!(f.kind().as_str(), "TOC" | "INDEX" | "TOA")).collect();
        if tocs.is_empty() {
            return false;
        }
        self.begin_group("Update Table");
        for t in tocs {
            self.rebuild_toc(&t);
        }
        self.end_group();
        true
    }

    /// Remove the table of contents (its content control too).
    pub fn remove_toc(&mut self) -> bool {
        let Some(t) = self.fields_in(self.doc.body).into_iter().find(|f| f.kind() == "TOC") else { return false };
        let paras = self.field_paras(&t);
        if paras.is_empty() {
            return false;
        }
        self.begin();
        let dom = &self.doc.dom;
        // inside a Table of Contents content control: all of it goes
        let mut sdt = None;
        let mut n = paras[0];
        while let Some(p) = dom.parent(n) {
            if dom.is(p, "w:sdt") {
                let gallery = crate::pictures::find(dom, p, "w:docPartGallery").and_then(|g| dom.attr(g, "w:val"));
                if gallery.map_or(false, |g| g.contains("Table of Contents")) {
                    sdt = Some(p);
                }
                break;
            }
            if dom.is(p, "w:body") {
                break;
            }
            n = p;
        }
        let gone: Vec<NodeId> = match sdt { Some(s) => vec![s], None => paras };
        let dom = &mut self.doc.dom;
        let after = dom.parent(gone[gone.len() - 1]).and_then(|par| {
            let i = dom.index_in_parent(gone[gone.len() - 1])?;
            dom.elements(par).skip_while(|&k| dom.index_in_parent(k).unwrap_or(0) <= i).find(|&k| dom.is(k, "w:p"))
        });
        for g in gone {
            dom.detach(g);
        }
        if let Some(p) = after {
            self.caret = Pos { para: p, off: 0 };
            self.anchor = self.caret;
        }
        self.commit("Remove Table of Contents", false);
        true
    }
}

impl Editor {
    /// Bookmark names (not the hidden ones Word makes).
    pub fn bookmark_names(&self) -> Vec<String> {
        let mut v: Vec<String> = self.bookmarks().into_keys().filter(|n| !n.starts_with('_')).collect();
        v.sort();
        v
    }
}

impl Editor {
    /// Show field codes instead of results, or back (Alt+F9).
    pub fn toggle_field_codes(&mut self) {
        self.doc.show_codes = !self.doc.show_codes;
        self.cache.clear();
        let p = self.caret.para;
        self.relayout();
        self.caret = Pos { para: p, off: self.caret.off.min(self.para_len(p)) };
        self.anchor = self.caret;
    }
}

impl Editor {
    /// How many captions with this label there are (the next one's number - 1).
    pub fn seq_count(&self, label: &str) -> usize {
        self.fields_in(self.doc.body).iter()
            .filter(|f| {
                let i = parse_instr(&f.instr);
                i.kind == "SEQ" && i.args.first().map_or(false, |a| a.eq_ignore_ascii_case(label))
            })
            .count()
    }

    /// Insert a caption ("Figure 1: text") below or above the selected
    /// picture, the table the caret is in, or the caret's paragraph.
    pub fn insert_caption(&mut self, label: &str, text: &str, below: bool, numfmt: &str, exclude_label: bool) {
        if !self.doc.styles.styles.contains_key("Caption") {
            self.add_style_xml("<w:style w:type=\"paragraph\" w:styleId=\"Caption\"><w:name w:val=\"caption\"/>\
                <w:basedOn w:val=\"Normal\"/><w:next w:val=\"Normal\"/><w:uiPriority w:val=\"35\"/><w:unhideWhenUsed/>\
                <w:qFormat/><w:pPr><w:spacing w:after=\"200\" w:line=\"240\" w:lineRule=\"auto\"/></w:pPr>\
                <w:rPr><w:i/><w:iCs/><w:color w:val=\"44546A\"/><w:sz w:val=\"18\"/><w:szCs w:val=\"18\"/></w:rPr></w:style>");
        }
        let dom = &self.doc.dom;
        let target = match self.sel_obj {
            Some(o) => para_of(dom, o).unwrap_or(self.caret.para),
            None => match self.cell_of(self.caret.para) {
                Some((tbl, _, _)) => {
                    // the outermost table
                    let mut t = tbl;
                    let mut n = tbl;
                    while let Some(p) = dom.parent(n) {
                        if dom.is(p, "w:tbl") {
                            t = p;
                        }
                        n = p;
                    }
                    t
                }
                None => self.caret.para,
            },
        };
        let n = self.seq_count(label) + 1;
        let shown = crate::editor::fields::number_format(n as i64, numfmt);
        let lab = if exclude_label { String::new() } else { format!("{} ", label) };
        let keep = if below { "" } else { "<w:keepNext/>" };
        let extra = if text.is_empty() { String::new() } else {
            let t = if text.starts_with(':') || text.starts_with('.') || text.starts_with('-') { text.to_string() } else { format!(" {}", text) };
            format!("<w:r><w:t xml:space=\"preserve\">{}</w:t></w:r>", esc(&t))
        };
        let xml = format!(
            "<w:p><w:pPr><w:pStyle w:val=\"Caption\"/>{keep}</w:pPr><w:r><w:t xml:space=\"preserve\">{}</w:t></w:r>\
             <w:r><w:fldChar w:fldCharType=\"begin\"/></w:r><w:r><w:instrText xml:space=\"preserve\"> SEQ {} \\* {} </w:instrText></w:r>\
             <w:r><w:fldChar w:fldCharType=\"separate\"/></w:r><w:r><w:rPr><w:noProof/></w:rPr><w:t>{}</w:t></w:r>\
             <w:r><w:fldChar w:fldCharType=\"end\"/></w:r>{extra}</w:p>",
            esc(&lab), esc(label), numfmt, esc(&shown));
        self.begin_group("Insert Caption");
        self.begin();
        let nodes = self.import_paras(&xml);
        let Some(&p) = nodes.first() else {
            self.commit("Insert Caption", false);
            self.end_group();
            return;
        };
        let dom = &mut self.doc.dom;
        let parent = dom.parent(target).unwrap();
        let idx = dom.index_in_parent(target).unwrap() + if below { 1 } else { 0 };
        dom.insert(parent, idx, p);
        self.sel_obj = None;
        let len = self.doc.para_text(p).chars().count();
        self.caret = Pos { para: p, off: len };
        self.anchor = self.caret;
        self.commit("Insert Caption", false);
        // later captions renumber
        self.update_fields_where(true, &|k| k == "SEQ");
        self.end_group();
    }
}

impl Editor {
    /// The link under a point: "#bookmark" for a place in the document,
    /// else the address.
    pub fn link_at(&self, page: usize, x: f64, y: f64) -> Option<String> {
        let pos = self.hit(page, x, y)?;
        let pl = self.para_layout(pos.para)?;
        let mut at = 0;
        let mut link = None;
        for pc in &pl.pieces {
            let len = pc.item.len();
            if len > 0 && at <= pos.off && pos.off < at + len || (len > 0 && pos.off == at + len && link.is_none() && pc.link.is_some()) {
                link = pc.link;
                if at <= pos.off && pos.off < at + len {
                    break;
                }
            }
            at += len;
        }
        let l = link?;
        let dom = &self.doc.dom;
        if let Some(a) = dom.attr(l, "w:anchor") {
            return Some(format!("#{}", a));
        }
        let rid = dom.attr(l, "r:id")?;
        self.doc.pkg.rel_target(&self.doc.main, rid)
    }

    /// Put the caret at a bookmark.
    pub fn goto_bookmark(&mut self, name: &str) -> bool {
        let marks = self.bookmarks();
        let Some(&(start, _)) = marks.get(name) else { return false };
        let dom = &self.doc.dom;
        let Some(p) = para_of(dom, start) else { return false };
        // its position: the content before it in the paragraph
        let mut nodes = Vec::new();
        order(dom, p, &mut nodes);
        let before: Vec<NodeId> = nodes.iter().copied().take_while(|&n| n != start).collect();
        let pieces = self.doc.para_pieces(p, &self.doc.para_props(p).1);
        let mut off = 0;
        for pc in pieces {
            if pc.node.map_or(false, |n| before.contains(&n)) {
                off += pc.item.len();
            }
        }
        if self.story != super::Story::Body {
            self.edit_header_footer(None, false);
        }
        self.caret = Pos { para: p, off };
        self.anchor = self.caret;
        true
    }
}

const REL_HYPERLINK: &str = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink";

impl Editor {
    /// The w:hyperlink at the caret.
    fn link_node_at_caret(&self) -> Option<NodeId> {
        let pl = self.para_layout(self.caret.para)?;
        let off = self.caret.off;
        let mut at = 0;
        let mut prev = None;
        for pc in &pl.pieces {
            let len = pc.item.len();
            if len > 0 {
                if at <= off && off < at + len {
                    return pc.link.or(if off == at { prev } else { None });
                }
                prev = pc.link;
            }
            at += len;
        }
        prev.filter(|_| off == at)
    }

    /// The address of the link at the caret ("#bookmark" inside the
    /// document), or "".
    pub fn link_at_caret(&self) -> String {
        let Some(l) = self.link_node_at_caret() else { return String::new() };
        let dom = &self.doc.dom;
        if let Some(a) = dom.attr(l, "w:anchor") {
            return format!("#{a}");
        }
        let Some(rid) = dom.attr(l, "r:id") else { return String::new() };
        self.doc.pkg.rel_target(&self.doc.main, rid).unwrap_or_default()
    }

    /// Headings (level, text) for "Place in This Document".
    pub fn headings(&self) -> Vec<(usize, String)> {
        self.toc_headings(1, 9, None).into_iter().map(|(_, l, t)| (l, t)).collect()
    }

    /// Make the selection (or `text`, typed at the caret) a link to `url`:
    /// a web address, "mailto:...", or "#bookmark" / "#Heading text|outline".
    pub fn insert_hyperlink(&mut self, url: &str, text: Option<&str>) {
        if !self.doc.styles.styles.contains_key("Hyperlink") {
            self.add_style_xml("<w:style w:type=\"character\" w:styleId=\"Hyperlink\"><w:name w:val=\"Hyperlink\"/>\
                <w:basedOn w:val=\"DefaultParagraphFont\"/><w:uiPriority w:val=\"99\"/><w:unhideWhenUsed/>\
                <w:rPr><w:color w:val=\"0563C1\" w:themeColor=\"hyperlink\"/><w:u w:val=\"single\"/></w:rPr></w:style>");
        }
        let shown = match text {
            Some(t) if !t.is_empty() => t.to_string(),
            _ => {
                let s = self.selected_text();
                if s.is_empty() { url.trim_start_matches('#').split('|').next().unwrap_or(url).to_string() } else { s }
            }
        };
        self.begin_group("Insert Hyperlink");
        // where it goes
        let (anchor, rid) = if let Some(place) = url.strip_prefix('#') {
            let (name, outline) = match place.strip_suffix("|outline") {
                Some(h) => (h.to_string(), true),
                None => (place.to_string(), false),
            };
            if outline {
                // a heading: a hidden bookmark on it
                let p = self.toc_headings(1, 9, None).into_iter().find(|(_, _, t)| *t == name).map(|(p, _, _)| p);
                match p {
                    Some(p) => {
                        self.begin();
                        let mut next_id = self.max_bookmark_id() + 1;
                        let mut used: Vec<String> = self.bookmarks().into_keys().collect();
                        used.retain(|n| !n.starts_with("_Toc"));
                        let b = self.toc_bookmark(p, &mut next_id, &mut used);
                        self.commit("Insert Hyperlink", false);
                        (Some(b), None)
                    }
                    None => (Some(name), None),
                }
            } else if name == "top" {
                (Some("_top".to_string()), None)
            } else {
                (Some(name), None)
            }
        } else {
            let main = self.doc.main.clone();
            let id = self.doc.pkg.add_rel(&main, REL_HYPERLINK, url);
            // links are external
            if let Ok(x) = self.doc.pkg.xml_mut(&crate::package::Package::rels_name(&main)) {
                let found = x.elements(x.root).find(|&r| x.attr(r, "Id") == Some(id.as_str()));
                if let Some(r) = found {
                    x.set_attr(r, "TargetMode", "External");
                }
            }
            (None, Some(id))
        };
        self.begin();
        self.delete_selection();
        let p = self.caret.para;
        let off = self.caret.off;
        let (parent, idx, like) = self.split_runs_at(p, off);
        let run = self.new_run(p, like, &[super::PropEdit::set("w:rStyle", &[("w:val", "Hyperlink")])]);
        let dom = &mut self.doc.dom;
        let t = dom.new_element("w:t", &[("xml:space", "preserve")]);
        let tx = dom.new_text(&shown);
        dom.append(t, tx);
        dom.append(run, t);
        let mut attrs: Vec<(&str, &str)> = vec![("w:history", "1")];
        if let Some(a) = anchor.as_deref() {
            attrs.insert(0, ("w:anchor", a));
        }
        if let Some(r) = rid.as_deref() {
            attrs.insert(0, ("r:id", r));
        }
        let h = dom.new_element("w:hyperlink", &attrs);
        dom.append(h, run);
        // a link sits in the paragraph, not inside another run's parent link
        let (parent, idx) = if dom.is(parent, "w:hyperlink") {
            let pp = dom.parent(parent).unwrap();
            (pp, dom.index_in_parent(parent).unwrap() + 1)
        } else {
            (parent, idx)
        };
        dom.insert(parent, idx, h);
        self.caret = Pos { para: p, off: off + shown.chars().count() };
        self.anchor = self.caret;
        self.commit("Insert Hyperlink", false);
        self.end_group();
    }

    /// Remove the link at the caret (its text stays, unstyled).
    pub fn remove_link(&mut self) -> bool {
        let Some(h) = self.link_node_at_caret() else { return false };
        self.begin();
        let dom = &mut self.doc.dom;
        let parent = dom.parent(h).unwrap();
        let mut idx = dom.index_in_parent(h).unwrap();
        for c in dom.children(h).to_vec() {
            if dom.is(c, "w:r") {
                if let Some(rpr) = dom.child(c, "w:rPr") {
                    for k in dom.children(rpr).to_vec() {
                        if dom.is(k, "w:rStyle") && dom.attr(k, "w:val") == Some("Hyperlink") {
                            dom.detach(k);
                        }
                    }
                }
            }
            dom.detach(c);
            dom.insert(parent, idx, c);
            idx += 1;
        }
        dom.detach(h);
        self.commit("Remove Hyperlink", false);
        true
    }
}

/// The paragraph child holding `n`.
fn top_child(dom: &XmlDoc, p: NodeId, mut n: NodeId) -> Option<NodeId> {
    loop {
        let par = dom.parent(n)?;
        if par == p {
            return Some(n);
        }
        n = par;
    }
}

impl Editor {
    /// Cross-reference targets: (kind, shown, target) — kinds "Heading",
    /// "Bookmark", and each caption label ("Figure", "Table"...).
    pub fn references(&self) -> Vec<(String, String, String)> {
        let mut out = Vec::new();
        for (i, (_p, _l, t)) in self.toc_headings(1, 9, None).into_iter().enumerate() {
            out.push(("Heading".to_string(), t, format!("h{i}")));
        }
        for b in self.bookmark_names() {
            out.push(("Bookmark".to_string(), b.clone(), b));
        }
        let mut count: HashMap<String, usize> = HashMap::new();
        for f in self.fields_in(self.doc.body) {
            let ins = parse_instr(&f.instr);
            if ins.kind != "SEQ" {
                continue;
            }
            let Some(label) = ins.args.first() else { continue };
            let Some(p) = para_of(&self.doc.dom, f.begin) else { continue };
            let i = count.entry(label.clone()).or_insert(0);
            out.push((label.clone(), heading_text(&self.doc.para_text(p)), format!("s{}:{}", label, i)));
            *i += 1;
        }
        out
    }

    /// A hidden _Ref bookmark around children [a, b] of paragraph p.
    fn ref_bookmark(&mut self, p: NodeId, a: Option<NodeId>, b: Option<NodeId>) -> String {
        let marks = self.bookmarks();
        let mut k: u64 = 400_000_000 + (marks.len() as u64) * 104_729;
        let mut name = format!("_Ref{k}");
        while marks.contains_key(&name) {
            k += 1;
            name = format!("_Ref{k}");
        }
        let id = (self.max_bookmark_id() + 1).to_string();
        let dom = &mut self.doc.dom;
        let s = dom.new_element("w:bookmarkStart", &[("w:id", &id), ("w:name", &name)]);
        let e = dom.new_element("w:bookmarkEnd", &[("w:id", &id)]);
        let first = a.or_else(|| dom.elements(p).find(|&c| !dom.is(c, "w:pPr")));
        match first.and_then(|f| dom.index_in_parent(f)) {
            Some(i) => dom.insert(p, i, s),
            None => dom.append(p, s),
        }
        match b.and_then(|l| dom.index_in_parent(l)) {
            Some(i) => dom.insert(p, i + 1, e),
            None => dom.append(p, e),
        }
        name
    }

    /// Insert a cross-reference: `part` is "text", "page", "above",
    /// "label-number" or "caption-only".
    pub fn insert_cross_reference(&mut self, kind: &str, target: &str, part: &str, link: bool) -> bool {
        self.begin_group("Cross-reference");
        let name = if kind == "Bookmark" {
            target.to_string()
        } else if let Some(i) = target.strip_prefix('h').and_then(|v| v.parse::<usize>().ok()) {
            let Some((p, _, _)) = self.toc_headings(1, 9, None).into_iter().nth(i) else {
                self.end_group();
                return false;
            };
            // its existing _Ref bookmark, else a new one
            let dom = &self.doc.dom;
            let have = dom.elements(p).find(|&c| dom.is(c, "w:bookmarkStart")
                && dom.attr(c, "w:name").map_or(false, |n| n.starts_with("_Ref"))).and_then(|c| dom.attr(c, "w:name").map(|s| s.to_string()));
            match have {
                Some(n) => n,
                None => {
                    self.begin();
                    let n = self.ref_bookmark(p, None, None);
                    self.commit("Cross-reference", false);
                    n
                }
            }
        } else if let Some(rest) = target.strip_prefix('s') {
            let Some((label, i)) = rest.rsplit_once(':') else {
                self.end_group();
                return false;
            };
            let i: usize = i.parse().unwrap_or(0);
            let seqs: Vec<FieldInfo> = self.fields_in(self.doc.body).into_iter().filter(|f| {
                let ins = parse_instr(&f.instr);
                ins.kind == "SEQ" && ins.args.first().map_or(false, |a| a == label)
            }).collect();
            let Some(f) = seqs.get(i).cloned() else {
                self.end_group();
                return false;
            };
            let dom = &self.doc.dom;
            let Some(p) = para_of(dom, f.begin) else {
                self.end_group();
                return false;
            };
            let end_child = f.end.and_then(|e| top_child(dom, p, e));
            let after_end = end_child.and_then(|c| {
                let kids: Vec<NodeId> = dom.elements(p).collect();
                let i = kids.iter().position(|&k| k == c)?;
                kids.get(i + 1).copied()
            });
            self.begin();
            let n = match part {
                "label-number" => self.ref_bookmark(p, None, end_child),
                "caption-only" => self.ref_bookmark(p, after_end, None),
                _ => self.ref_bookmark(p, None, None),
            };
            self.commit("Cross-reference", false);
            n
        } else {
            self.end_group();
            return false;
        };
        let h = if link { " \\h" } else { "" };
        let instr = match part {
            "page" => format!("PAGEREF {name}{h}"),
            "above" => format!("REF {name} \\p{h}"),
            _ => format!("REF {name}{h}"),
        };
        self.insert_field_now(&instr);
        self.end_group();
        true
    }

    /// Bookmark the selection (or the caret's place).
    pub fn add_bookmark(&mut self, name: &str) -> bool {
        if name.is_empty() || self.bookmarks().contains_key(name) {
            return false;
        }
        let (a, b) = self.selection();
        let id = (self.max_bookmark_id() + 1).to_string();
        self.begin();
        // a boundary at each end of the selection
        let (pb, ib, _) = self.split_runs_at(b.para, b.off);
        let e = self.doc.dom.new_element("w:bookmarkEnd", &[("w:id", &id)]);
        self.doc.dom.insert(pb, ib, e);
        let (pa, ia, _) = self.split_runs_at(a.para, a.off);
        let s = self.doc.dom.new_element("w:bookmarkStart", &[("w:id", &id), ("w:name", name)]);
        self.doc.dom.insert(pa, ia, s);
        self.commit("Bookmark", false);
        true
    }

    pub fn delete_bookmark(&mut self, name: &str) -> bool {
        let Some(&(s, e)) = self.bookmarks().get(name) else { return false };
        self.begin();
        self.doc.dom.detach(s);
        if let Some(e) = e {
            self.doc.dom.detach(e);
        }
        self.commit("Delete Bookmark", false);
        true
    }
}
