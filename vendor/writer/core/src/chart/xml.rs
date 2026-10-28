//! A small XML reader and writer, written for the package parts of a workbook.
//!
//! Names are kept exactly as written (prefix included), attributes keep their order,
//! and comments, processing instructions and CDATA survive as raw text, so a part read
//! and written back comes out equivalent to the original.

use std::fmt::Write;

#[derive(Clone, Debug, PartialEq)]
pub enum Node {
    Elem(Element),
    Text(String),
    /// comment, processing instruction, CDATA or doctype, kept verbatim
    Raw(String),
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Element {
    pub name: String,
    pub attrs: Vec<(String, String)>,
    pub children: Vec<Node>,
}

impl Element {
    pub fn new(name: &str) -> Self {
        Element { name: name.to_string(), attrs: Vec::new(), children: Vec::new() }
    }
    pub fn with_attrs(name: &str, attrs: &[(&str, &str)]) -> Self {
        let mut e = Element::new(name);
        for (k, v) in attrs {
            e.attrs.push((k.to_string(), v.to_string()));
        }
        e
    }
    /// The local part of the name (without a prefix).
    pub fn local(&self) -> &str {
        local(&self.name)
    }
    pub fn attr(&self, name: &str) -> Option<&str> {
        self.attrs.iter().find(|(k, _)| k == name || local(k) == name && !name.contains(':'))
            .map(|(_, v)| v.as_str())
    }
    pub fn attr_exact(&self, name: &str) -> Option<&str> {
        self.attrs.iter().find(|(k, _)| k == name).map(|(_, v)| v.as_str())
    }
    pub fn set_attr(&mut self, name: &str, value: &str) {
        if let Some(a) = self.attrs.iter_mut().find(|(k, _)| k == name) {
            a.1 = value.to_string();
        } else {
            self.attrs.push((name.to_string(), value.to_string()));
        }
    }
    pub fn remove_attr(&mut self, name: &str) {
        self.attrs.retain(|(k, _)| k != name);
    }
    pub fn child(&self, local_name: &str) -> Option<&Element> {
        self.children.iter().find_map(|n| match n {
            Node::Elem(e) if e.local() == local_name => Some(e),
            _ => None,
        })
    }
    pub fn child_mut(&mut self, local_name: &str) -> Option<&mut Element> {
        self.children.iter_mut().find_map(|n| match n {
            Node::Elem(e) if e.local() == local_name => Some(e),
            _ => None,
        })
    }
    pub fn elems(&self) -> impl Iterator<Item = &Element> {
        self.children.iter().filter_map(|n| match n {
            Node::Elem(e) => Some(e),
            _ => None,
        })
    }
    pub fn elems_mut(&mut self) -> impl Iterator<Item = &mut Element> {
        self.children.iter_mut().filter_map(|n| match n {
            Node::Elem(e) => Some(e),
            _ => None,
        })
    }
    pub fn elems_named<'a>(&'a self, local_name: &'a str) -> impl Iterator<Item = &'a Element> + 'a {
        self.elems().filter(move |e| e.local() == local_name)
    }
    pub fn remove_children(&mut self, local_name: &str) {
        self.children.retain(|n| !matches!(n, Node::Elem(e) if e.local() == local_name));
    }
    /// All text inside, concatenated.
    pub fn text(&self) -> String {
        let mut s = String::new();
        self.collect_text(&mut s);
        s
    }
    fn collect_text(&self, s: &mut String) {
        for n in &self.children {
            match n {
                Node::Text(t) => s.push_str(t),
                Node::Elem(e) => e.collect_text(s),
                Node::Raw(r) => {
                    if let Some(inner) = r.strip_prefix("<![CDATA[").and_then(|x| x.strip_suffix("]]>")) {
                        s.push_str(inner);
                    }
                }
            }
        }
    }
    pub fn push(&mut self, e: Element) {
        self.children.push(Node::Elem(e));
    }
    /// Insert a child so that siblings stay in the order the schema lists them.
    pub fn insert_ordered(&mut self, e: Element, order: &[&str]) {
        let idx = order.iter().position(|n| *n == e.local()).unwrap_or(order.len());
        let mut pos = 0;
        for (i, n) in self.children.iter().enumerate() {
            if let Node::Elem(c) = n {
                let ci = order.iter().position(|o| *o == c.local()).unwrap_or(usize::MAX);
                if ci != usize::MAX && ci <= idx {
                    pos = i + 1;
                }
            }
        }
        self.children.insert(pos, Node::Elem(e));
    }
    pub fn write(&self, out: &mut String) {
        out.push('<');
        out.push_str(&self.name);
        for (k, v) in &self.attrs {
            out.push(' ');
            out.push_str(k);
            out.push_str("=\"");
            escape_attr_into(v, out);
            out.push('"');
        }
        if self.children.is_empty() {
            out.push_str("/>");
            return;
        }
        out.push('>');
        for n in &self.children {
            match n {
                Node::Elem(e) => e.write(out),
                Node::Text(t) => escape_text_into(t, out),
                Node::Raw(r) => out.push_str(r),
            }
        }
        out.push_str("</");
        out.push_str(&self.name);
        out.push('>');
    }
    pub fn to_string(&self) -> String {
        let mut s = String::new();
        self.write(&mut s);
        s
    }
}

pub fn local(name: &str) -> &str {
    match name.rfind(':') {
        Some(i) => &name[i + 1..],
        None => name,
    }
}

pub fn escape_text_into(t: &str, out: &mut String) {
    for ch in t.chars() {
        match ch {
            '&' => out.push_str("&amp;"),
            '<' => out.push_str("&lt;"),
            '>' => out.push_str("&gt;"),
            c if (c as u32) < 0x20 && c != '\n' && c != '\r' && c != '\t' => {
                // not allowed in XML 1.0; the spreadsheet convention is _xHHHH_
                let _ = write!(out, "_x{:04X}_", c as u32);
            }
            c => out.push(c),
        }
    }
}

pub fn escape_attr_into(t: &str, out: &mut String) {
    for ch in t.chars() {
        match ch {
            '&' => out.push_str("&amp;"),
            '<' => out.push_str("&lt;"),
            '"' => out.push_str("&quot;"),
            '\n' => out.push_str("&#10;"),
            '\r' => out.push_str("&#13;"),
            '\t' => out.push_str("&#9;"),
            c if (c as u32) < 0x20 => {
                let _ = write!(out, "_x{:04X}_", c as u32);
            }
            c => out.push(c),
        }
    }
}

pub fn escape_text(t: &str) -> String {
    let mut s = String::with_capacity(t.len());
    escape_text_into(t, &mut s);
    s
}

pub fn escape_attr(t: &str) -> String {
    let mut s = String::with_capacity(t.len());
    escape_attr_into(t, &mut s);
    s
}

/// Decode entity and character references.
pub fn unescape(s: &str) -> String {
    if !s.contains('&') {
        return s.to_string();
    }
    let mut out = String::with_capacity(s.len());
    let mut rest = s;
    while let Some(i) = rest.find('&') {
        out.push_str(&rest[..i]);
        rest = &rest[i..];
        let end = match rest.find(';') {
            Some(e) if e < 12 => e,
            _ => {
                out.push('&');
                rest = &rest[1..];
                continue;
            }
        };
        let ent = &rest[1..end];
        let rep = match ent {
            "lt" => Some('<'),
            "gt" => Some('>'),
            "amp" => Some('&'),
            "quot" => Some('"'),
            "apos" => Some('\''),
            _ if ent.starts_with("#x") || ent.starts_with("#X") => {
                u32::from_str_radix(&ent[2..], 16).ok().and_then(char::from_u32)
            }
            _ if ent.starts_with('#') => ent[1..].parse::<u32>().ok().and_then(char::from_u32),
            _ => None,
        };
        match rep {
            Some(c) => {
                out.push(c);
                rest = &rest[end + 1..];
            }
            None => {
                out.push('&');
                rest = &rest[1..];
            }
        }
    }
    out.push_str(rest);
    out
}

/// Decode the _xHHHH_ escapes used in cell text.
pub fn unescape_ooxml(s: &str) -> String {
    if !s.contains("_x") {
        return s.to_string();
    }
    let b = s.as_bytes();
    let mut out = String::with_capacity(s.len());
    let mut i = 0;
    let mut last = 0;
    while i + 7 <= b.len() {
        if b[i] == b'_' && b[i + 1] == b'x' && b[i + 6] == b'_' && b[i + 2..i + 6].iter().all(|c| c.is_ascii_hexdigit()) {
            out.push_str(&s[last..i]);
            let v = u32::from_str_radix(&s[i + 2..i + 6], 16).unwrap();
            if let Some(c) = char::from_u32(v) {
                out.push(c);
            }
            i += 7;
            last = i;
        } else {
            i += 1;
        }
    }
    out.push_str(&s[last..]);
    out
}

// --------------------------------------------------------------------------- tokenizer

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum Tok<'a> {
    /// name, raw attribute text, self-closing
    Start(&'a str, &'a str, bool),
    End(&'a str),
    Text(&'a str),
    /// comment, PI, CDATA, doctype
    Other(&'a str),
}

pub struct Tokenizer<'a> {
    pub src: &'a str,
    pub pos: usize,
}

impl<'a> Tokenizer<'a> {
    pub fn new(src: &'a str) -> Self {
        Tokenizer { src, pos: 0 }
    }
    pub fn next_tok(&mut self) -> Result<Option<Tok<'a>>, String> {
        let s = self.src;
        let b = s.as_bytes();
        if self.pos >= b.len() {
            return Ok(None);
        }
        if b[self.pos] != b'<' {
            let start = self.pos;
            let end = memchr(b'<', &b[start..]).map(|i| start + i).unwrap_or(b.len());
            self.pos = end;
            return Ok(Some(Tok::Text(&s[start..end])));
        }
        let start = self.pos;
        let rest = &s[start..];
        if rest.starts_with("<!--") {
            let e = rest.find("-->").ok_or("unterminated comment")? + 3;
            self.pos += e;
            return Ok(Some(Tok::Other(&s[start..start + e])));
        }
        if rest.starts_with("<![CDATA[") {
            let e = rest.find("]]>").ok_or("unterminated CDATA")? + 3;
            self.pos += e;
            return Ok(Some(Tok::Other(&s[start..start + e])));
        }
        if rest.starts_with("<?") {
            let e = rest.find("?>").ok_or("unterminated processing instruction")? + 2;
            self.pos += e;
            return Ok(Some(Tok::Other(&s[start..start + e])));
        }
        if rest.starts_with("<!") {
            // doctype (may contain an internal subset in brackets)
            let mut depth = 0i32;
            for (i, c) in rest.char_indices() {
                match c {
                    '[' => depth += 1,
                    ']' => depth -= 1,
                    '>' if depth <= 0 => {
                        self.pos += i + 1;
                        return Ok(Some(Tok::Other(&s[start..start + i + 1])));
                    }
                    _ => {}
                }
            }
            return Err("unterminated declaration".into());
        }
        if rest.starts_with("</") {
            let e = memchr(b'>', &b[start..]).ok_or("unterminated end tag")?;
            let name = s[start + 2..start + e].trim();
            self.pos = start + e + 1;
            return Ok(Some(Tok::End(name)));
        }
        // start tag: find the closing '>' outside quotes
        let mut i = start + 1;
        let mut quote = 0u8;
        while i < b.len() {
            let c = b[i];
            if quote != 0 {
                if c == quote {
                    quote = 0;
                }
            } else if c == b'"' || c == b'\'' {
                quote = c;
            } else if c == b'>' {
                break;
            }
            i += 1;
        }
        if i >= b.len() {
            return Err("unterminated start tag".into());
        }
        let selfclose = b[i - 1] == b'/';
        let inner_end = if selfclose { i - 1 } else { i };
        let inner = &s[start + 1..inner_end];
        let name_end = inner.find(|c: char| c.is_whitespace()).unwrap_or(inner.len());
        let name = &inner[..name_end];
        let attrs = &inner[name_end..];
        self.pos = i + 1;
        Ok(Some(Tok::Start(name, attrs, selfclose)))
    }
}

fn memchr(c: u8, h: &[u8]) -> Option<usize> {
    h.iter().position(|&x| x == c)
}

/// Parse raw attribute text into (name, unescaped value) pairs.
pub fn parse_attrs(raw: &str) -> Vec<(String, String)> {
    let mut out = Vec::new();
    for_each_attr(raw, |k, v| out.push((k.to_string(), unescape(v))));
    out
}

/// Visit attributes without allocating (values still escaped).
pub fn for_each_attr<'a>(raw: &'a str, mut f: impl FnMut(&'a str, &'a str)) {
    let b = raw.as_bytes();
    let mut i = 0;
    while i < b.len() {
        while i < b.len() && (b[i] as char).is_whitespace() {
            i += 1;
        }
        let ks = i;
        while i < b.len() && b[i] != b'=' && !(b[i] as char).is_whitespace() {
            i += 1;
        }
        if ks == i {
            break;
        }
        let k = &raw[ks..i];
        while i < b.len() && (b[i] as char).is_whitespace() {
            i += 1;
        }
        if i >= b.len() || b[i] != b'=' {
            continue;
        }
        i += 1;
        while i < b.len() && (b[i] as char).is_whitespace() {
            i += 1;
        }
        if i >= b.len() {
            break;
        }
        let q = b[i];
        if q != b'"' && q != b'\'' {
            break;
        }
        i += 1;
        let vs = i;
        while i < b.len() && b[i] != q {
            i += 1;
        }
        f(k, &raw[vs..i.min(b.len())]);
        i += 1;
    }
}

/// Get one attribute's (unescaped) value from raw attribute text.
pub fn raw_attr(raw: &str, name: &str) -> Option<String> {
    let mut out = None;
    for_each_attr(raw, |k, v| {
        if out.is_none() && k == name {
            out = Some(unescape(v));
        }
    });
    out
}

/// Parse a whole document: what comes before the root (declaration, comments) and the root.
pub fn parse(src: &str) -> Result<(String, Element), String> {
    let src = src.strip_prefix('\u{feff}').unwrap_or(src);
    let mut t = Tokenizer::new(src);
    let mut prolog = String::new();
    loop {
        let pos = t.pos;
        match t.next_tok()? {
            None => return Err("no root element".into()),
            Some(Tok::Start(..)) => {
                t.pos = pos;
                break;
            }
            Some(_) => prolog.push_str(&src[pos..t.pos]),
        }
    }
    let root = parse_element(&mut t)?;
    Ok((prolog, root))
}

/// Parse the element starting at the tokenizer's position (a start tag must come next).
pub fn parse_element(t: &mut Tokenizer) -> Result<Element, String> {
    let mut stack: Vec<Element> = Vec::new();
    loop {
        let tok = t.next_tok()?.ok_or("unexpected end of document")?;
        match tok {
            Tok::Start(name, attrs, selfclose) => {
                let e = Element { name: name.to_string(), attrs: parse_attrs(attrs), children: Vec::new() };
                if selfclose {
                    match stack.last_mut() {
                        Some(p) => p.children.push(Node::Elem(e)),
                        None => return Ok(e),
                    }
                } else {
                    stack.push(e);
                }
            }
            Tok::End(name) => {
                let e = stack.pop().ok_or("unexpected end tag")?;
                if e.name != name {
                    return Err(format!("mismatched end tag: <{}> closed by </{}>", e.name, name));
                }
                match stack.last_mut() {
                    Some(p) => p.children.push(Node::Elem(e)),
                    None => return Ok(e),
                }
            }
            Tok::Text(x) => {
                if let Some(p) = stack.last_mut() {
                    p.children.push(Node::Text(unescape(x)));
                }
            }
            Tok::Other(x) => {
                if let Some(p) = stack.last_mut() {
                    p.children.push(Node::Raw(x.to_string()));
                }
            }
        }
    }
}

pub fn parse_bytes(b: &[u8]) -> Result<(String, Element), String> {
    let s = decode(b)?;
    parse(&s)
}

/// Bytes of a part as text (UTF-8, or UTF-16 with a byte-order mark).
pub fn decode(b: &[u8]) -> Result<String, String> {
    if b.len() >= 2 && b[0] == 0xFF && b[1] == 0xFE {
        let u: Vec<u16> = b[2..].chunks(2).map(|c| u16::from_le_bytes([c[0], *c.get(1).unwrap_or(&0)])).collect();
        return Ok(String::from_utf16_lossy(&u));
    }
    if b.len() >= 2 && b[0] == 0xFE && b[1] == 0xFF {
        let u: Vec<u16> = b[2..].chunks(2).map(|c| u16::from_be_bytes([c[0], *c.get(1).unwrap_or(&0)])).collect();
        return Ok(String::from_utf16_lossy(&u));
    }
    match std::str::from_utf8(b) {
        Ok(s) => Ok(s.to_string()),
        Err(_) => Ok(String::from_utf8_lossy(b).into_owned()),
    }
}

pub const DECL: &str = "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\r\n";

pub fn document(prolog: &str, root: &Element) -> String {
    let mut s = String::new();
    if prolog.trim().is_empty() {
        s.push_str(DECL);
    } else {
        s.push_str(prolog);
    }
    root.write(&mut s);
    s
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn roundtrip() {
        let src = r#"<?xml version="1.0"?><a:root xmlns:a="u" x="1&amp;2"><!-- c --><b>t &lt; u</b><c/><![CDATA[<x>]]></a:root>"#;
        let (pro, r) = parse(src).unwrap();
        assert_eq!(r.attr("x"), Some("1&2"));
        assert_eq!(r.child("b").unwrap().text(), "t < u");
        let out = document(&pro, &r);
        assert_eq!(out, src);
    }
    #[test]
    fn ooxml_escape() {
        assert_eq!(unescape_ooxml("a_x000D_b"), "a\rb");
    }
}
