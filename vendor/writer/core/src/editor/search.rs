//! Find and Replace: the story's text as one string (paragraph marks as
//! '\r', line breaks as '\u{b}'), searched with a regular expression made
//! from the query: plain text with the original's ^ codes, or its wildcard
//! syntax.

use super::{Editor, Pos};
use crate::xml::NodeId;
use regex::Regex;

/// The search options of the Find and Replace dialog.
#[derive(Clone, Debug, Default)]
pub struct FindOpts {
    pub match_case: bool,
    pub whole_word: bool,
    pub wildcards: bool,
    pub prefix: bool,
    pub suffix: bool,
    pub ignore_punct: bool,
    pub ignore_space: bool,
    /// the query is already a regular expression
    pub regex: bool,
}

struct Hay {
    text: String,
    /// byte offset of each character and its place in the document
    starts: Vec<usize>,
    pos: Vec<Pos>,
    end: Pos,
}

impl Hay {
    fn at(&self, b: usize) -> Pos {
        match self.starts.binary_search(&b) {
            Ok(i) => self.pos[i],
            Err(i) => self.pos.get(i).copied().unwrap_or(self.end),
        }
    }

    /// The byte offset of a place (the first character at or after it).
    fn byte_of(&self, p: Pos, ed: &Editor) -> usize {
        let i = self.pos.partition_point(|&q| ed.cmp(q, p).is_lt());
        self.starts.get(i).copied().unwrap_or(self.text.len())
    }
}

/// The ^ code after a caret in plain (non-wildcard) text, as a regex.
fn caret_code(c: char, it: &mut std::iter::Peekable<std::str::Chars>) -> Option<String> {
    Some(match c {
        'p' => "\\r".into(),
        't' => "\\t".into(),
        'l' | 'n' => "\\x0B".into(),
        '?' => "[^\\r]".into(),
        '#' => "\\d".into(),
        '$' => "\\p{L}".into(),
        's' => "\\x{a0}".into(),
        'w' => "[ \\t\\x{a0}]+".into(),
        '+' => "\\x{2014}".into(),
        '=' => "\\x{2013}".into(),
        '~' => "\\x{2011}".into(),
        '-' => "\\x{ad}".into(),
        '^' => "\\^".into(),
        'm' | 'b' => "\\x0C".into(),
        'g' => "\\x{fffc}".into(),
        'e' | 'f' | 'a' | 'd' => return Some(String::new()),
        c if c.is_ascii_digit() => {
            let mut s = c.to_string();
            while let Some(&d) = it.peek() {
                if d.is_ascii_digit() && s.len() < 5 {
                    s.push(d);
                    it.next();
                } else {
                    break;
                }
            }
            let n: u32 = s.parse().ok()?;
            regex::escape(&char::from_u32(n)?.to_string())
        }
        'u' => {
            let mut s = String::new();
            while let Some(&d) = it.peek() {
                if d.is_ascii_digit() && s.len() < 5 {
                    s.push(d);
                    it.next();
                } else {
                    break;
                }
            }
            let n: u32 = s.parse().ok()?;
            regex::escape(&char::from_u32(n)?.to_string())
        }
        _ => return None,
    })
}

/// Word's wildcard syntax as a regex.
fn wildcards(q: &str) -> Result<String, String> {
    let mut out = String::new();
    let mut it = q.chars().peekable();
    while let Some(c) = it.next() {
        match c {
            '?' => out.push_str("[^\\r]"),
            '*' => out.push_str("[^\\r]*?"),
            '@' => out.push('+'),
            '<' => out.push_str("\\b{start}"),
            '>' => out.push_str("\\b{end}"),
            '(' | ')' => out.push(c),
            '{' => {
                out.push('{');
                for d in it.by_ref() {
                    match d {
                        ';' => out.push(','),
                        '}' => {
                            out.push('}');
                            break;
                        }
                        d => out.push(d),
                    }
                }
            }
            '[' => {
                out.push('[');
                if it.peek() == Some(&'!') {
                    it.next();
                    out.push('^');
                }
                for d in it.by_ref() {
                    match d {
                        ']' => break,
                        '\\' | '[' | '&' | '~' | '^' => {
                            out.push('\\');
                            out.push(d);
                        }
                        d => out.push(d),
                    }
                }
                out.push(']');
            }
            '\\' => match it.next() {
                Some(d) => out.push_str(&regex::escape(&d.to_string())),
                None => out.push_str("\\\\"),
            },
            '^' => match it.next() {
                Some(d) => out.push_str(&caret_code(d, &mut it).ok_or("bad ^ code")?),
                None => out.push_str("\\^"),
            },
            c => out.push_str(&regex::escape(&c.to_string())),
        }
    }
    Ok(out)
}

/// The query as a regular expression.
pub fn build(query: &str, o: &FindOpts) -> Result<Regex, String> {
    if query.is_empty() {
        return Err("empty".into());
    }
    let body = if o.regex {
        query.to_string()
    } else if o.wildcards {
        wildcards(query)?
    } else {
        let mut atoms: Vec<String> = Vec::new();
        let mut it = query.chars().peekable();
        while let Some(c) = it.next() {
            if c == '^' {
                if let Some(d) = it.next() {
                    atoms.push(caret_code(d, &mut it).ok_or("bad ^ code")?);
                    continue;
                }
            }
            if o.ignore_space && c.is_whitespace() {
                continue;
            }
            if o.ignore_punct && c.is_ascii_punctuation() {
                continue;
            }
            atoms.push(regex::escape(&c.to_string()));
        }
        let sep = match (o.ignore_space, o.ignore_punct) {
            (true, true) => "[\\s\\p{P}]*",
            (true, false) => "\\s*",
            (false, true) => "\\p{P}*",
            _ => "",
        };
        let mut s = atoms.join(sep);
        let starts_w = query.chars().next().is_some_and(|c| c.is_alphanumeric());
        let ends_w = query.chars().last().is_some_and(|c| c.is_alphanumeric());
        if (o.whole_word || o.prefix) && starts_w {
            s = format!("\\b{s}");
        }
        if (o.whole_word || o.suffix) && ends_w {
            s = format!("{s}\\b");
        }
        s
    };
    let ci = !o.match_case && !o.wildcards;
    regex::RegexBuilder::new(&body).case_insensitive(ci).build().map_err(|e| e.to_string())
}

/// The replacement text for a match: ^& the found text, ^p ^t ^l ^^, and
/// (with wildcards) \1..\9.
pub fn expand(rep: &str, caps: &regex::Captures, wild: bool) -> String {
    let mut out = String::new();
    let mut it = rep.chars().peekable();
    while let Some(c) = it.next() {
        match c {
            '^' => match it.next() {
                Some('&') => out.push_str(&caps[0]),
                Some('p') => out.push('\n'),
                Some('t') => out.push('\t'),
                Some('l') | Some('n') => out.push('\u{b}'),
                Some('s') => out.push('\u{a0}'),
                Some('+') => out.push('\u{2014}'),
                Some('=') => out.push('\u{2013}'),
                Some('~') => out.push('\u{2011}'),
                Some('-') => out.push('\u{ad}'),
                Some('^') => out.push('^'),
                Some(d) if d.is_ascii_digit() => {
                    let mut s = d.to_string();
                    while let Some(&e) = it.peek() {
                        if e.is_ascii_digit() && s.len() < 5 {
                            s.push(e);
                            it.next();
                        } else {
                            break;
                        }
                    }
                    if let Some(ch) = s.parse().ok().and_then(char::from_u32) {
                        out.push(ch);
                    }
                }
                Some(d) => {
                    out.push('^');
                    out.push(d);
                }
                None => out.push('^'),
            },
            '\\' if wild => match it.next() {
                Some(d) if d.is_ascii_digit() => {
                    let k = d as usize - '0' as usize;
                    if let Some(m) = caps.get(k) {
                        out.push_str(m.as_str());
                    }
                }
                Some(d) => out.push(d),
                None => out.push('\\'),
            },
            c => out.push(c),
        }
    }
    out.replace('\r', "\n")
}

impl Editor {
    fn haystack(&self) -> Hay {
        let mut text = String::new();
        let mut starts = Vec::new();
        let mut pos = Vec::new();
        let range = self.story_range();
        let mut end = self.caret;
        for (k, &i) in range.iter().enumerate() {
            let pl = &self.layout.paras[i];
            for (off, c) in Self::para_chars(pl) {
                starts.push(text.len());
                pos.push(Pos { para: pl.node, off });
                text.push(if c == '\n' { '\u{b}' } else { c });
            }
            end = Pos { para: pl.node, off: pl.text_len };
            if k + 1 < range.len() {
                starts.push(text.len());
                pos.push(end);
                text.push('\r');
            }
        }
        Hay { text, starts, pos, end }
    }

    /// Every match in the story being edited, in order, with a line of
    /// context around it (for the Navigation pane).
    pub fn find_all(&self, query: &str, o: &FindOpts) -> Result<Vec<(Pos, Pos, String)>, String> {
        let re = build(query, o)?;
        let h = self.haystack();
        let mut out = Vec::new();
        for m in re.find_iter(&h.text) {
            if m.is_empty() {
                continue;
            }
            let a = h.text[..m.start()].rfind(['\r']).map(|i| i + 1).unwrap_or(0);
            let b = h.text[m.end()..].find('\r').map(|i| m.end() + i).unwrap_or(h.text.len());
            let pre: String = h.text[a..m.start()].chars().rev().take(30).collect::<Vec<_>>().into_iter().rev().collect();
            let post: String = h.text[m.end()..b].chars().take(50).collect();
            let ctx = format!("{pre}\u{1}{}\u{2}{post}", &h.text[m.start()..m.end()]).replace(['\u{b}', '\u{fffc}'], " ");
            out.push((h.at(m.start()), h.at(m.end()), ctx));
            if out.len() >= 5000 {
                break;
            }
        }
        Ok(out)
    }

    /// The next (or previous) match from the selection, wrapping round the
    /// story; it becomes the selection. None when there is no match. The
    /// bool says whether the search wrapped.
    pub fn find(&mut self, query: &str, o: &FindOpts, forward: bool, wrap: bool) -> Result<Option<bool>, String> {
        let re = build(query, o)?;
        let h = self.haystack();
        let (sa, sb) = self.selection();
        let ms: Vec<(usize, usize)> = re.find_iter(&h.text).filter(|m| !m.is_empty()).map(|m| (m.start(), m.end())).collect();
        if ms.is_empty() {
            return Ok(None);
        }
        let (from_a, from_b) = (h.byte_of(sa, self), h.byte_of(sb, self));
        let pick = if forward {
            // a match starting at the selection that isn't the selection
            ms.iter().find(|&&(s, e)| s > from_a || (s == from_a && e != from_b)).map(|&m| (m, false))
        } else {
            ms.iter().rev().find(|&&(s, _)| s < from_a).map(|&m| (m, false))
        };
        let pick = match pick {
            Some(p) => p,
            None if wrap => (if forward { ms[0] } else { *ms.last().unwrap() }, true),
            None => return Ok(None),
        };
        let ((s, e), wrapped) = pick;
        self.move_to(h.at(s), false, false);
        self.move_to(h.at(e), true, false);
        Ok(Some(wrapped))
    }

    /// Replace the selection if it matches the query, then find the next
    /// match. Returns whether something was replaced.
    pub fn replace_one(&mut self, query: &str, rep: &str, o: &FindOpts) -> Result<bool, String> {
        let re = build(query, o)?;
        let mut done = false;
        if self.has_selection() {
            let h = self.haystack();
            let (sa, sb) = self.selection();
            let (a, b) = (h.byte_of(sa, self), h.byte_of(sb, self));
            if let Some(c) = re.captures_at(&h.text, a) {
                let m = c.get(0).unwrap();
                if m.start() == a && m.end() == b {
                    let text = expand(rep, &c, o.wildcards);
                    self.replace_selection(&text);
                    done = true;
                }
            }
        }
        self.find(query, o, true, true)?;
        Ok(done)
    }

    fn replace_selection(&mut self, text: &str) {
        if text.is_empty() {
            if self.has_selection() {
                self.delete(true, false);
            }
        } else {
            self.type_text(text);
            self.typing = false;
        }
    }

    /// Replace every match (one undo step). Returns how many.
    pub fn replace_all(&mut self, query: &str, rep: &str, o: &FindOpts) -> Result<usize, String> {
        let re = build(query, o)?;
        let h = self.haystack();
        let jobs: Vec<(Pos, Pos, String)> = re
            .captures_iter(&h.text)
            .filter(|c| !c.get(0).unwrap().is_empty())
            .map(|c| {
                let m = c.get(0).unwrap();
                (h.at(m.start()), h.at(m.end()), expand(rep, &c, o.wildcards))
            })
            .collect();
        if jobs.is_empty() {
            return Ok(0);
        }
        let n = jobs.len();
        let (keep_a, keep_c) = (self.anchor, self.caret);
        let simple = jobs.iter().all(|(a, b, t)| a.para == b.para && !t.contains('\n'));
        if simple {
            // one transaction, from the end so earlier places stay put
            self.begin();
            for (a, b, t) in jobs.into_iter().rev() {
                self.anchor = a;
                self.caret = b;
                self.delete_selection();
                let at = self.caret;
                if !t.is_empty() {
                    self.insert_at(at.para, at.off, &t);
                }
            }
            self.anchor = keep_a;
            self.caret = keep_a;
            self.commit("Replace All", false);
        } else {
            self.begin_group("Replace All");
            for (a, b, t) in jobs.into_iter().rev() {
                if self.doc.dom.parent(a.para).is_none() || self.pidx(&a.para).is_none() || self.pidx(&b.para).is_none() {
                    continue;
                }
                self.anchor = a;
                self.caret = b;
                self.replace_selection(&t);
            }
            self.end_group();
            let ok = |p: Pos, e: &Editor| e.pidx(&p.para).is_some() && p.off <= e.para_len(p.para);
            let to = if ok(keep_a, self) { keep_a } else { self.doc_start() };
            self.move_to(to, false, false);
        }
        let _ = keep_c;
        Ok(n)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn queries() {
        let o = FindOpts::default();
        assert!(build("a^pb", &o).unwrap().is_match("A\rb"));
        let w = FindOpts { wildcards: true, ..Default::default() };
        let r = build("<(b?t)>", &w).unwrap();
        assert!(r.is_match("a bat c"));
        assert!(!r.is_match("abate"));
        let r = build("[0-9]{2;3}", &w).unwrap();
        assert!(r.is_match("x 123"));
        let r = build("lo@k", &w).unwrap();
        assert!(r.is_match("loooook"));
        let ww = FindOpts { whole_word: true, ..Default::default() };
        assert!(!build("cat", &ww).unwrap().is_match("concatenate"));
        let c = build("(a)(b)", &w).unwrap().captures("ab").unwrap();
        assert_eq!(expand("\\2\\1^&", &c, true), "baab");
    }
}


impl Editor {
    /// The text of the paragraphs with lines on a page, for spelling as you type: (paragraph,
    /// its text — one character per position, U+FFFC for objects, fields and breaks — and the
    /// language of each stretch).
    pub fn page_text(&self, page: usize) -> Vec<(NodeId, String, Vec<(usize, usize, String)>)> {
        let Some(pg) = self.layout.pages.get(page) else { return vec![] };
        let mut seen: Vec<usize> = Vec::new();
        for l in &pg.lines {
            if !seen.contains(&l.para) {
                seen.push(l.para);
            }
        }
        let mut out = Vec::new();
        for pi in seen {
            let Some(pl) = self.layout.paras.get(pi) else { continue };
            let node = pl.node;
            let (_, base) = self.doc.para_props(node);
            let mut text = String::new();
            let mut langs: Vec<(usize, usize, String)> = Vec::new();
            let mut pos = 0;
            for pc in self.doc.para_pieces(node, &base) {
                let n = pc.item.len();
                match &pc.item {
                    crate::document::Item::Text(t) if pc.field.is_none() && pc.change != "del" => text.push_str(t),
                    _ => text.extend(std::iter::repeat('\u{fffc}').take(n)),
                }
                if n > 0 {
                    let dom = &self.doc.dom;
                    let no_proof = pc.run.and_then(|r| dom.child(r, "w:rPr")).and_then(|rp| dom.child(rp, "w:noProof"))
                        .map_or(false, |n| !matches!(dom.attr(n, "w:val"), Some("0") | Some("false")));
                    let lang = if no_proof { "zxx".to_string() } else { pc.rpr.lang.clone().unwrap_or_default() };
                    match langs.last_mut() {
                        Some(last) if last.2 == lang && last.1 == pos => last.1 = pos + n,
                        _ => langs.push((pos, pos + n, lang)),
                    }
                }
                pos += n;
            }
            out.push((node, text, langs));
        }
        out
    }
}
