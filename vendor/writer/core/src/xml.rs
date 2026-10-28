//! A small XML DOM that keeps everything it reads.
//!
//! The document model of Folio is the .docx XML itself: whatever Word wrote
//! is kept, including the parts Folio doesn't understand, so saving never
//! loses anything. Nodes live in an arena and are addressed by `NodeId`.

use quick_xml::events::{BytesStart, Event};
use quick_xml::Reader;
use std::fmt::Write as _;

pub type NodeId = u32;

#[derive(Clone, Debug)]
pub enum Kind {
    Element { name: String, attrs: Vec<(String, String)> },
    Text(String),
    /// Comments, processing instructions, CDATA: written back verbatim.
    Raw(String),
}

#[derive(Clone, Debug)]
pub struct Node {
    pub kind: Kind,
    pub parent: Option<NodeId>,
    pub children: Vec<NodeId>,
}

#[derive(Clone, Debug, Default)]
pub struct XmlDoc {
    pub nodes: Vec<Node>,
    pub root: NodeId,
    /// Everything before the root element (declaration, doctype...).
    pub prolog: String,
    /// Changes recorded while `recording` is on (for undo).
    pub journal: Vec<Op>,
    pub recording: bool,
}

/// One recorded change and what it replaced.
#[derive(Clone, Debug)]
pub enum Op {
    Attrs { id: NodeId, old: Vec<(String, String)> },
    Text { id: NodeId, old: String },
    Inserted { node: NodeId },
    Detached { node: NodeId, parent: NodeId, index: usize },
    Renamed { id: NodeId, old: String },
}

#[derive(Debug)]
pub struct XmlError(pub String);

impl std::fmt::Display for XmlError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "XML error: {}", self.0)
    }
}

fn attrs_of(e: &BytesStart) -> Result<Vec<(String, String)>, XmlError> {
    let mut out = Vec::new();
    for a in e.attributes().with_checks(false) {
        let a = a.map_err(|e| XmlError(e.to_string()))?;
        let key = String::from_utf8_lossy(a.key.as_ref()).into_owned();
        let val = a
            .unescape_value()
            .map(|v| v.into_owned())
            .unwrap_or_else(|_| String::from_utf8_lossy(&a.value).into_owned());
        out.push((key, val));
    }
    Ok(out)
}

pub fn escape_text(s: &str, out: &mut String) {
    for ch in s.chars() {
        match ch {
            '&' => out.push_str("&amp;"),
            '<' => out.push_str("&lt;"),
            '>' => out.push_str("&gt;"),
            _ => out.push(ch),
        }
    }
}

/// `s` escaped for an attribute value.
pub fn attr_escaped(s: &str) -> String {
    let mut o = String::new();
    escape_attr(s, &mut o);
    o
}

pub fn escape_attr(s: &str, out: &mut String) {
    for ch in s.chars() {
        match ch {
            '&' => out.push_str("&amp;"),
            '<' => out.push_str("&lt;"),
            '>' => out.push_str("&gt;"),
            '"' => out.push_str("&quot;"),
            '\n' => out.push_str("&#10;"),
            '\r' => out.push_str("&#13;"),
            '\t' => out.push_str("&#9;"),
            _ => out.push(ch),
        }
    }
}

impl XmlDoc {
    pub fn parse(bytes: &[u8]) -> Result<XmlDoc, XmlError> {
        let mut reader = Reader::from_reader(bytes);
        reader.config_mut().trim_text(false);
        reader.config_mut().expand_empty_elements = false;
        let mut doc = XmlDoc::default();
        let mut stack: Vec<NodeId> = Vec::new();
        let mut buf = Vec::new();
        let mut have_root = false;
        loop {
            let ev = reader
                .read_event_into(&mut buf)
                .map_err(|e| XmlError(format!("at {}: {}", reader.buffer_position(), e)))?;
            match ev {
                Event::Start(e) => {
                    let name = String::from_utf8_lossy(e.name().as_ref()).into_owned();
                    let id = doc.push(Kind::Element { name, attrs: attrs_of(&e)? }, stack.last().copied());
                    if stack.is_empty() {
                        doc.root = id;
                        have_root = true;
                    }
                    stack.push(id);
                }
                Event::Empty(e) => {
                    let name = String::from_utf8_lossy(e.name().as_ref()).into_owned();
                    let id = doc.push(Kind::Element { name, attrs: attrs_of(&e)? }, stack.last().copied());
                    if stack.is_empty() {
                        doc.root = id;
                        have_root = true;
                    }
                }
                Event::End(_) => {
                    stack.pop();
                }
                Event::Text(t) => {
                    let s = t
                        .unescape()
                        .map(|v| v.into_owned())
                        .unwrap_or_else(|_| String::from_utf8_lossy(&t).into_owned());
                    if stack.is_empty() {
                        if !have_root {
                            doc.prolog.push_str(&s);
                        }
                    } else {
                        doc.push(Kind::Text(s), stack.last().copied());
                    }
                }
                Event::CData(t) => {
                    let s = format!("<![CDATA[{}]]>", String::from_utf8_lossy(&t));
                    if let Some(&p) = stack.last() {
                        doc.push(Kind::Raw(s), Some(p));
                    }
                }
                Event::Comment(t) => {
                    let s = format!("<!--{}-->", String::from_utf8_lossy(&t));
                    match stack.last() {
                        Some(&p) => {
                            doc.push(Kind::Raw(s), Some(p));
                        }
                        None if !have_root => doc.prolog.push_str(&s),
                        None => {}
                    }
                }
                Event::Decl(d) => {
                    let _ = write!(doc.prolog, "<?{}?>", String::from_utf8_lossy(&d));
                }
                Event::PI(p) => {
                    let s = format!("<?{}?>", String::from_utf8_lossy(&p));
                    match stack.last() {
                        Some(&par) => {
                            doc.push(Kind::Raw(s), Some(par));
                        }
                        None => doc.prolog.push_str(&s),
                    }
                }
                Event::DocType(d) => {
                    let _ = write!(doc.prolog, "<!DOCTYPE {}>", String::from_utf8_lossy(&d));
                }
                Event::Eof => break,
            }
            buf.clear();
        }
        if !have_root {
            return Err(XmlError("no root element".into()));
        }
        Ok(doc)
    }

    /// A new document with an empty root element.
    pub fn with_root(name: &str, attrs: &[(&str, &str)]) -> XmlDoc {
        let mut doc = XmlDoc {
            prolog: "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\r\n".into(),
            ..Default::default()
        };
        let attrs = attrs.iter().map(|(k, v)| (k.to_string(), v.to_string())).collect();
        doc.root = doc.push(Kind::Element { name: name.into(), attrs }, None);
        doc
    }

    fn push(&mut self, kind: Kind, parent: Option<NodeId>) -> NodeId {
        let id = self.nodes.len() as NodeId;
        self.nodes.push(Node { kind, parent, children: Vec::new() });
        if let Some(p) = parent {
            self.nodes[p as usize].children.push(id);
        }
        id
    }

    // ------------------------------------------------------------ reading
    #[inline]
    pub fn node(&self, id: NodeId) -> &Node {
        &self.nodes[id as usize]
    }

    /// Give an element another name.
    pub fn rename(&mut self, id: NodeId, new: &str) {
        if self.recording {
            let old = self.name(id).to_string();
            self.journal.push(Op::Renamed { id, old });
        }
        if let Kind::Element { name, .. } = &mut self.nodes[id as usize].kind {
            *name = new.to_string();
        }
    }

    pub fn name(&self, id: NodeId) -> &str {
        match &self.node(id).kind {
            Kind::Element { name, .. } => name,
            _ => "",
        }
    }

    pub fn is(&self, id: NodeId, name: &str) -> bool {
        self.name(id) == name
    }

    pub fn attr(&self, id: NodeId, key: &str) -> Option<&str> {
        match &self.node(id).kind {
            Kind::Element { attrs, .. } => attrs.iter().find(|(k, _)| k == key).map(|(_, v)| v.as_str()),
            _ => None,
        }
    }

    pub fn children(&self, id: NodeId) -> &[NodeId] {
        &self.node(id).children
    }

    pub fn parent(&self, id: NodeId) -> Option<NodeId> {
        self.node(id).parent
    }

    /// Element children only.
    pub fn elements(&self, id: NodeId) -> impl Iterator<Item = NodeId> + '_ {
        self.node(id)
            .children
            .iter()
            .copied()
            .filter(move |&c| matches!(self.node(c).kind, Kind::Element { .. }))
    }

    pub fn child(&self, id: NodeId, name: &str) -> Option<NodeId> {
        self.elements(id).find(|&c| self.name(c) == name)
    }

    pub fn children_named<'a>(&'a self, id: NodeId, name: &'a str) -> impl Iterator<Item = NodeId> + 'a {
        self.elements(id).filter(move |&c| self.name(c) == name)
    }

    /// Text content of the node (all descendant text nodes).
    pub fn text(&self, id: NodeId) -> String {
        let mut out = String::new();
        self.collect_text(id, &mut out);
        out
    }

    fn collect_text(&self, id: NodeId, out: &mut String) {
        match &self.node(id).kind {
            Kind::Text(t) => out.push_str(t),
            Kind::Element { .. } => {
                for &c in &self.node(id).children {
                    self.collect_text(c, out);
                }
            }
            Kind::Raw(_) => {}
        }
    }

    pub fn index_in_parent(&self, id: NodeId) -> Option<usize> {
        let p = self.parent(id)?;
        self.node(p).children.iter().position(|&c| c == id)
    }

    // ------------------------------------------------------------ writing
    fn record_attrs(&mut self, id: NodeId) {
        if self.recording {
            if let Kind::Element { attrs, .. } = &self.nodes[id as usize].kind {
                let old = attrs.clone();
                self.journal.push(Op::Attrs { id, old });
            }
        }
    }

    /// Undo `ops` (in reverse). Returns the ops that redo them.
    pub fn revert(&mut self, ops: &[Op]) -> Vec<Op> {
        let was = self.recording;
        let mark = self.journal.len();
        self.recording = true;
        for op in ops.iter().rev() {
            match op {
                Op::Attrs { id, old } => {
                    self.record_attrs(*id);
                    if let Kind::Element { attrs, .. } = &mut self.nodes[*id as usize].kind {
                        *attrs = old.clone();
                    }
                }
                Op::Text { id, old } => self.set_text(*id, old),
                Op::Inserted { node } => {
                    self.detach(*node);
                }
                Op::Detached { node, parent, index } => self.insert(*parent, *index, *node),
                Op::Renamed { id, old } => self.rename(*id, old),
            }
        }
        let redo = self.journal.split_off(mark);
        self.recording = was;
        if !was {
            self.journal.clear();
        }
        redo
    }

    pub fn set_attr(&mut self, id: NodeId, key: &str, value: &str) {
        self.record_attrs(id);
        if let Kind::Element { attrs, .. } = &mut self.nodes[id as usize].kind {
            if let Some(a) = attrs.iter_mut().find(|(k, _)| k == key) {
                a.1 = value.to_string();
            } else {
                attrs.push((key.to_string(), value.to_string()));
            }
        }
    }

    pub fn remove_attr(&mut self, id: NodeId, key: &str) -> Option<String> {
        if self.attr(id, key).is_some() {
            self.record_attrs(id);
        }
        if let Kind::Element { attrs, .. } = &mut self.nodes[id as usize].kind {
            if let Some(i) = attrs.iter().position(|(k, _)| k == key) {
                return Some(attrs.remove(i).1);
            }
        }
        None
    }

    pub fn set_text(&mut self, id: NodeId, value: &str) {
        if let Kind::Text(t) = &mut self.nodes[id as usize].kind {
            if self.recording {
                let old = std::mem::replace(t, value.to_string());
                self.journal.push(Op::Text { id, old });
                return;
            }
            *t = value.to_string();
        }
    }

    pub fn text_of_node(&self, id: NodeId) -> Option<&str> {
        match &self.node(id).kind {
            Kind::Text(t) => Some(t),
            _ => None,
        }
    }

    /// A detached element (insert it with `insert`).
    pub fn new_element(&mut self, name: &str, attrs: &[(&str, &str)]) -> NodeId {
        let attrs = attrs.iter().map(|(k, v)| (k.to_string(), v.to_string())).collect();
        self.push(Kind::Element { name: name.to_string(), attrs }, None)
    }

    pub fn new_text(&mut self, text: &str) -> NodeId {
        self.push(Kind::Text(text.to_string()), None)
    }

    /// Put a detached node at `index` among `parent`'s children.
    pub fn insert(&mut self, parent: NodeId, index: usize, node: NodeId) {
        debug_assert!(self.nodes[node as usize].parent.is_none());
        let kids = &mut self.nodes[parent as usize].children;
        let index = index.min(kids.len());
        kids.insert(index, node);
        self.nodes[node as usize].parent = Some(parent);
        if self.recording {
            self.journal.push(Op::Inserted { node });
        }
    }

    pub fn append(&mut self, parent: NodeId, node: NodeId) {
        let n = self.nodes[parent as usize].children.len();
        self.insert(parent, n, node);
    }

    /// Take a node out of the tree (it stays in the arena, detached).
    /// Returns (old parent, old index).
    pub fn detach(&mut self, node: NodeId) -> Option<(NodeId, usize)> {
        let p = self.nodes[node as usize].parent?;
        let idx = self.nodes[p as usize].children.iter().position(|&c| c == node)?;
        self.nodes[p as usize].children.remove(idx);
        self.nodes[node as usize].parent = None;
        if self.recording {
            self.journal.push(Op::Detached { node, parent: p, index: idx });
        }
        Some((p, idx))
    }

    /// Deep copy of a node (detached).
    pub fn clone_node(&mut self, id: NodeId) -> NodeId {
        let kind = self.node(id).kind.clone();
        let kids = self.node(id).children.clone();
        let new = self.push(kind, None);
        for c in kids {
            let cc = self.clone_node(c);
            self.append(new, cc);
        }
        new
    }

    /// Deep copy of a node from another document into this one (detached).
    pub fn import_node(&mut self, other: &XmlDoc, id: NodeId) -> NodeId {
        let kind = other.node(id).kind.clone();
        let new = self.push(kind, None);
        for &c in other.children(id) {
            let cc = self.import_node(other, c);
            self.append(new, cc);
        }
        new
    }

    // ------------------------------------------------------------ output
    pub fn serialize(&self) -> String {
        let mut out = String::with_capacity(self.nodes.len() * 24 + 64);
        out.push_str(&self.prolog);
        self.write_node(self.root, &mut out);
        out
    }

    pub fn serialize_node(&self, id: NodeId) -> String {
        let mut out = String::new();
        self.write_node(id, &mut out);
        out
    }

    fn write_node(&self, id: NodeId, out: &mut String) {
        let n = self.node(id);
        match &n.kind {
            Kind::Text(t) => escape_text(t, out),
            Kind::Raw(r) => out.push_str(r),
            Kind::Element { name, attrs } => {
                out.push('<');
                out.push_str(name);
                for (k, v) in attrs {
                    out.push(' ');
                    out.push_str(k);
                    out.push_str("=\"");
                    escape_attr(v, out);
                    out.push('"');
                }
                if n.children.is_empty() {
                    out.push_str("/>");
                } else {
                    out.push('>');
                    for &c in &n.children {
                        self.write_node(c, out);
                    }
                    out.push_str("</");
                    out.push_str(name);
                    out.push('>');
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn roundtrip_simple() {
        let src = r#"<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="x"><w:body><w:p><w:r><w:t xml:space="preserve"> a &amp; b </w:t></w:r></w:p><!-- c --><w:sectPr/></w:body></w:document>"#;
        let d = XmlDoc::parse(src.as_bytes()).unwrap();
        assert_eq!(d.serialize(), src);
    }

    #[test]
    fn edit() {
        let mut d = XmlDoc::parse(b"<a><b/></a>").unwrap();
        let c = d.new_element("c", &[("x", "1\"")]);
        d.append(d.root, c);
        assert_eq!(d.serialize(), "<a><b/><c x=\"1&quot;\"/></a>");
        let b = d.child(d.root, "b").unwrap();
        d.detach(b);
        assert_eq!(d.serialize(), "<a><c x=\"1&quot;\"/></a>");
    }
}
