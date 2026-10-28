//! Equations: finding them on the page, their markup (OMML) for the
//! equation editor, replacing it, inserting new ones and removing them.

use super::{Editor, Pos};
use crate::document::Item;
use crate::layout::UnitKind;
use crate::xml::{NodeId, XmlDoc};

pub const M_NS: &str = "http://schemas.openxmlformats.org/officeDocument/2006/math";
const W_NS: &str = crate::document::W_NS;

/// Where an equation is on the page.
#[derive(Clone, Debug)]
pub struct MathInfo {
    pub node: NodeId,
    pub page: usize,
    /// its box: left, baseline (points from the page corner)
    pub x: f64,
    pub base: f64,
    pub w: f64,
    pub asc: f64,
    pub desc: f64,
    pub display: bool,
    /// the text size it is set at
    pub size: f64,
    pub pos: Pos,
}

impl Editor {
    fn math_units(&self) -> Vec<MathInfo> {
        let mut out = Vec::new();
        for (pg, page) in self.layout.pages.iter().enumerate() {
            for pl in page.lines.iter().chain(page.hf_lines.iter()).chain(page.note_lines.iter()) {
                let p = &self.layout.paras[pl.para];
                let Some(line) = p.lines.get(pl.line) else { continue };
                for u in line.start..line.end {
                    let unit = &p.units[u];
                    if unit.kind != UnitKind::Math {
                        continue;
                    }
                    let Some(pc) = p.pieces.get(unit.piece as usize) else { continue };
                    let Item::Math(node, display) = pc.item else { continue };
                    out.push(MathInfo {
                        node,
                        page: pg,
                        x: pl.x + line.xs[u - line.start],
                        base: pl.y + line.baseline,
                        w: unit.width,
                        asc: unit.asc,
                        desc: unit.desc,
                        display,
                        size: pc.rpr.size.unwrap_or(22) as f64 / 2.0,
                        pos: Pos { para: p.node, off: unit.pos },
                    });
                }
            }
        }
        out
    }

    /// The equation under a point of a page.
    pub fn math_at(&self, page: usize, x: f64, y: f64) -> Option<NodeId> {
        // only the story being edited (the body, or a header being edited)
        let story: std::collections::HashSet<NodeId> =
            self.story_lines(page).iter().map(|l| self.layout.paras[l.para].node).collect();
        self.math_units().into_iter().filter(|m| story.contains(&m.pos.para)).find(|m| {
            m.page == page && x >= m.x - 1.0 && x <= m.x + m.w + 1.0 && y >= m.base - m.asc - 1.0
                && y <= m.base + m.desc + 1.0
        }).map(|m| m.node)
    }

    pub fn math_info(&self, node: NodeId) -> Option<MathInfo> {
        let all: Vec<MathInfo> = self.math_units().into_iter().filter(|m| m.node == node).collect();
        // a header's equation: the copy on the page being edited
        if let super::Story::HeaderFooter(pg) | super::Story::Notes(pg) = self.story {
            if let Some(m) = all.iter().find(|m| m.page == pg) {
                return Some(m.clone());
            }
        }
        all.into_iter().next()
    }

    /// The equation next to the caret (after it: forward).
    pub fn math_beside_caret(&self, forward: bool) -> Option<NodeId> {
        if self.has_selection() {
            return None;
        }
        let c = self.caret;
        let want = if forward { c.off } else { c.off.checked_sub(1)? };
        self.pieces(c.para).into_iter().find_map(|(pc, s, _)| match pc.item {
            Item::Math(n, _) if s == want => Some(n),
            _ => None,
        })
    }

    /// The equation's OMML, with its namespaces declared.
    pub fn math_xml(&self, node: NodeId) -> String {
        let inner = self.doc.dom.serialize_node(node);
        // declare the prefixes on the element itself
        let decl = format!(" xmlns:m=\"{M_NS}\" xmlns:w=\"{W_NS}\"");
        match inner.find(|c: char| c == '>' || c == ' ' || c == '/') {
            Some(i) if inner.starts_with("<m:oMath") => format!("{}{}{}", &inner[..i], decl, &inner[i..]),
            _ => inner,
        }
    }

    fn parse_math(xml: &str) -> Option<XmlDoc> {
        // the editor sends an m:oMath element; give it namespaces if bare
        let src = if xml.contains("xmlns:m=") {
            xml.to_string()
        } else {
            xml.replacen("<m:oMath", &format!("<m:oMath xmlns:m=\"{M_NS}\" xmlns:w=\"{W_NS}\""), 1)
        };
        let x = XmlDoc::parse(src.as_bytes()).ok()?;
        if x.name(x.root) == "m:oMath" { Some(x) } else { None }
    }

    fn ensure_math_ns(&mut self) {
        let root = self.doc.dom.root;
        if self.doc.dom.attr(root, "xmlns:m").is_none() {
            self.doc.dom.set_attr(root, "xmlns:m", M_NS);
        }
    }

    /// Replace an equation's content with new OMML (an m:oMath element).
    pub fn set_math(&mut self, node: NodeId, xml: &str) -> bool {
        let Some(x) = Self::parse_math(xml) else { return false };
        if self.doc.dom.parent(node).is_none() {
            return false;
        }
        self.begin();
        self.ensure_math_ns();
        let dom = &mut self.doc.dom;
        for k in dom.children(node).to_vec() {
            dom.detach(k);
        }
        for &k in x.children(x.root) {
            let n = dom.import_node(&x, k);
            dom.append(node, n);
        }
        self.commit("Equation", false);
        true
    }

    /// Insert an equation at the caret (replacing the selection). A display
    /// equation goes in an m:oMathPara (on a line of its own). Returns it.
    pub fn insert_math(&mut self, xml: &str, display: bool) -> Option<NodeId> {
        let x = Self::parse_math(xml)?;
        self.begin_group("Insert Equation");
        self.begin();
        self.delete_selection();
        self.ensure_math_ns();
        let p = self.caret.para;
        let off = self.caret.off;
        let (parent, idx, _) = self.split_runs_at(p, off);
        let dom = &mut self.doc.dom;
        let m = dom.new_element("m:oMath", &[]);
        for &k in x.children(x.root) {
            let n = dom.import_node(&x, k);
            dom.append(m, n);
        }
        if display {
            let mp = dom.new_element("m:oMathPara", &[]);
            dom.append(mp, m);
            dom.insert(parent, idx, mp);
        } else {
            dom.insert(parent, idx, m);
        }
        self.caret = Pos { para: p, off: off + 1 };
        self.anchor = self.caret;
        self.commit("Insert Equation", false);
        self.end_group();
        Some(m)
    }

    /// Remove an equation.
    pub fn delete_math(&mut self, node: NodeId) -> bool {
        let Some(info) = self.math_info(node) else {
            if self.doc.dom.parent(node).is_none() {
                return false;
            }
            self.begin();
            self.detach_math(node);
            self.commit("Delete Equation", false);
            return true;
        };
        self.begin();
        self.detach_math(node);
        self.caret = info.pos;
        self.anchor = info.pos;
        self.commit("Delete Equation", false);
        true
    }

    fn detach_math(&mut self, node: NodeId) {
        let dom = &mut self.doc.dom;
        let par = dom.parent(node);
        dom.detach(node);
        if let Some(mp) = par.filter(|&p| dom.is(p, "m:oMathPara")) {
            if dom.children_named(mp, "m:oMath").next().is_none() {
                dom.detach(mp);
            }
        }
    }

    /// Put the caret just before / after an equation.
    pub fn caret_by_math(&mut self, node: NodeId, after: bool) -> bool {
        let Some(p) = self.para_of_node(node) else { return false };
        let Some(off) = self.pieces(p).into_iter().find_map(|(pc, s, _)| match pc.item {
            Item::Math(n, _) if n == node => Some(s),
            _ => None,
        }) else { return false };
        self.caret = Pos { para: p, off: off + after as usize };
        self.anchor = self.caret;
        self.goal_x = None;
        true
    }

    fn para_of_node(&self, n: NodeId) -> Option<NodeId> {
        let dom = &self.doc.dom;
        let mut c = n;
        loop {
            if dom.is(c, "w:p") {
                return Some(c);
            }
            c = dom.parent(c)?;
        }
    }

    /// Display equation <-> inline equation.
    pub fn set_math_display(&mut self, node: NodeId, display: bool) -> bool {
        let dom = &self.doc.dom;
        let Some(par) = dom.parent(node) else { return false };
        let is_display = dom.is(par, "m:oMathPara");
        if is_display == display {
            return true;
        }
        self.begin();
        let dom = &mut self.doc.dom;
        let idx = dom.index_in_parent(node).unwrap();
        if display {
            let mp = dom.new_element("m:oMathPara", &[]);
            dom.detach(node);
            dom.insert(par, idx, mp);
            dom.append(mp, node);
        } else {
            let up = dom.parent(par).unwrap();
            let pi = dom.index_in_parent(par).unwrap();
            dom.detach(node);
            dom.insert(up, pi + 1, node);
            if dom.children_named(par, "m:oMath").next().is_none() {
                dom.detach(par);
            }
        }
        self.commit("Change Equation Display", false);
        true
    }

    /// Is the caret's paragraph empty (a new equation there is a display one)?
    pub fn caret_para_empty(&self) -> bool {
        self.pieces(self.caret.para).iter().all(|(pc, _, _)| pc.item.len() == 0)
    }

    /// Every equation's node, in document order (the body).
    pub fn all_math(&self) -> Vec<NodeId> {
        let dom = &self.doc.dom;
        let mut out = Vec::new();
        let mut stack = vec![self.doc.body];
        while let Some(n) = stack.pop() {
            let kids: Vec<NodeId> = dom.elements(n).collect();
            for &k in kids.iter().rev() {
                if dom.is(k, "m:oMath") {
                    out.push(k);
                } else {
                    stack.push(k);
                }
            }
        }
        out
    }
}
