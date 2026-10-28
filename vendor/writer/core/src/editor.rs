//! Editing: caret and selection, geometry (where the caret is drawn, what a
//! click hits), changes to the document's XML with undo/redo, and relayout.

use crate::document::{Document, Item, Piece};
use crate::fonts::FontCache;
use crate::layout::{ParaLayout, UnitKind};
use crate::paginate::{layout_document_cached, Layout, ParaCache};
use crate::render::{Overlay, Renderer};
use crate::xml::{Kind, NodeId, Op, XmlDoc};
use std::collections::{HashMap, HashSet};
use std::sync::Arc;

/// A place in the text: a paragraph and a position in it (characters,
/// tabs, breaks and objects count one; hidden field codes none).
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct Pos {
    pub para: NodeId,
    pub off: usize,
}

struct Txn {
    name: String,
    ops: Vec<Op>,
    /// changes to numbering.xml
    num_ops: Vec<Op>,
    /// changes to styles.xml
    sty_ops: Vec<Op>,
    before: (Pos, Pos),
    after: (Pos, Pos),
    /// the theme part as it was before (theme colours and fonts changes)
    theme: Option<Box<XmlDoc>>,
    /// package parts as they were before (charts), by name
    parts: Vec<(String, Vec<u8>)>,
}

/// Schema order of run properties (Word rejects files with them out of
/// order).
const RPR_ORDER: &[&str] = &[
    "w:rStyle", "w:rFonts", "w:b", "w:bCs", "w:i", "w:iCs", "w:caps", "w:smallCaps", "w:strike", "w:dstrike",
    "w:outline", "w:shadow", "w:emboss", "w:imprint", "w:noProof", "w:snapToGrid", "w:vanish", "w:webHidden",
    "w:color", "w:spacing", "w:w", "w:kern", "w:position", "w:sz", "w:szCs", "w:highlight", "w:u", "w:effect",
    "w:bdr", "w:shd", "w:fitText", "w:vertAlign", "w:rtl", "w:cs", "w:em", "w:lang", "w:eastAsianLayout",
    "w:specVanish", "w:oMath", "w:rPrChange",
];

const PPR_ORDER: &[&str] = &[
    "w:pStyle", "w:keepNext", "w:keepLines", "w:pageBreakBefore", "w:framePr", "w:widowControl", "w:numPr",
    "w:suppressLineNumbers", "w:pBdr", "w:shd", "w:tabs", "w:suppressAutoHyphens", "w:kinsoku", "w:wordWrap",
    "w:overflowPunct", "w:topLinePunct", "w:autoSpaceDE", "w:autoSpaceDN", "w:bidi", "w:adjustRightInd",
    "w:snapToGrid", "w:spacing", "w:ind", "w:contextualSpacing", "w:mirrorIndents", "w:suppressOverlap", "w:jc",
    "w:textDirection", "w:textAlignment", "w:textboxTightWrap", "w:outlineLvl", "w:divId", "w:cnfStyle",
    "w:rPr", "w:sectPr", "w:pPrChange",
];

/// Schema order of table and row properties.
const TBLPR_ORDER: &[&str] = &[
    "w:tblStyle", "w:tblpPr", "w:tblOverlap", "w:bidiVisual", "w:tblStyleRowBandSize", "w:tblStyleColBandSize",
    "w:tblW", "w:jc", "w:tblCellSpacing", "w:tblInd", "w:tblBorders", "w:shd", "w:tblLayout", "w:tblCellMar",
    "w:tblLook", "w:tblCaption", "w:tblDescription", "w:tblPrChange",
];
const TRPR_ORDER: &[&str] = &[
    "w:cnfStyle", "w:divId", "w:gridBefore", "w:gridAfter", "w:wBefore", "w:wAfter", "w:cantSplit", "w:trHeight",
    "w:tblHeader", "w:tblCellSpacing", "w:jc", "w:hidden", "w:ins", "w:del", "w:trPrChange",
];

/// Schema order of a cell's properties.
const TCPR_ORDER: &[&str] = &[
    "w:cnfStyle", "w:tcW", "w:gridSpan", "w:hMerge", "w:vMerge", "w:tcBorders", "w:shd", "w:noWrap", "w:tcMar",
    "w:textDirection", "w:tcFitText", "w:vAlign", "w:hideMark", "w:headers", "w:cellIns", "w:cellDel",
    "w:cellMerge", "w:tcPrChange",
];

/// Schema order of a style's children.
const STYLE_ORDER: &[&str] = &[
    "w:name", "w:aliases", "w:basedOn", "w:next", "w:link", "w:autoRedefine", "w:hidden", "w:uiPriority",
    "w:semiHidden", "w:unhideWhenUsed", "w:qFormat", "w:locked", "w:personal", "w:personalCompose",
    "w:personalReply", "w:rsid", "w:pPr", "w:rPr", "w:tblPr", "w:trPr", "w:tcPr", "w:tblStylePr",
];

/// A property element to set (with its attributes) or remove (None).
#[derive(Clone, Debug)]
pub struct PropEdit {
    pub name: String,
    pub attrs: Option<Vec<(String, String)>>,
}

impl PropEdit {
    pub fn set(name: &str, attrs: &[(&str, &str)]) -> PropEdit {
        PropEdit { name: name.into(), attrs: Some(attrs.iter().map(|(k, v)| (k.to_string(), v.to_string())).collect()) }
    }
    pub fn remove(name: &str) -> PropEdit {
        PropEdit { name: name.into(), attrs: None }
    }
}

/// Set (or remove) a property child of `parent` keeping schema order.
fn set_prop_child(dom: &mut XmlDoc, parent: NodeId, e: &PropEdit, order: &[&str]) {
    let existing = dom.child(parent, &e.name);
    match &e.attrs {
        None => {
            if let Some(n) = existing {
                dom.detach(n);
            }
        }
        Some(attrs) => {
            if let Some(n) = existing {
                // replace the attributes
                let keys: Vec<String> = match &dom.node(n).kind {
                    Kind::Element { attrs, .. } => attrs.iter().map(|(k, _)| k.clone()).collect(),
                    _ => vec![],
                };
                for k in keys {
                    dom.remove_attr(n, &k);
                }
                for (k, v) in attrs {
                    dom.set_attr(n, k, v);
                }
                return;
            }
            let a: Vec<(&str, &str)> = attrs.iter().map(|(k, v)| (k.as_str(), v.as_str())).collect();
            let n = dom.new_element(&e.name, &a);
            let rank = |name: &str| order.iter().position(|x| *x == name).unwrap_or(order.len());
            let my = rank(&e.name);
            let kids: Vec<NodeId> = dom.elements(parent).collect();
            let mut idx = dom.children(parent).len();
            for k in kids {
                if rank(dom.name(k)) > my {
                    idx = dom.index_in_parent(k).unwrap_or(idx);
                    break;
                }
            }
            dom.insert(parent, idx, n);
        }
    }
}

/// The property element `name` (rPr/pPr) of `parent`, created if missing as
/// its first child.
fn ensure_child_first(dom: &mut XmlDoc, parent: NodeId, name: &str) -> NodeId {
    if let Some(n) = dom.child(parent, name) {
        return n;
    }
    let n = dom.new_element(name, &[]);
    dom.insert(parent, 0, n);
    n
}

fn is_prop_name(name: &str) -> bool {
    name.ends_with("Pr") || name.ends_with("EndPr") || name == "w:fldData"
}

pub struct Editor {
    pub doc: Document,
    pub fonts: FontCache,
    pub layout: Layout,
    cache: ParaCache,
    pub renderer: Renderer,
    pub anchor: Pos,
    pub caret: Pos,
    goal_x: Option<f64>,
    undo: Vec<Txn>,
    redo: Vec<Txn>,
    /// the last change was typing that the next keystroke may join
    typing: bool,
    /// formatting picked with an empty selection, for the next typed text
    pub pending: Vec<PropEdit>,
    /// (paragraph index, line) -> (page, index in the page's lines)
    line_loc: HashMap<(usize, usize), (usize, usize)>,
    pub modified: bool,
    txn_before: Option<(Pos, Pos)>,
    /// an open undo group: (name, undo depth when it began)
    group: Option<(String, usize)>,
    /// the selected picture / shape (its w:drawing or w:pict)
    pub sel_obj: Option<NodeId>,
    /// more selected objects (Shift+click), with sel_obj
    pub sel_more: Vec<NodeId>,
    /// 0 Print Layout, 1 Draft, 2 Web Layout
    pub view_mode: u8,
    /// Web Layout: the window's width (points)
    pub web_width: f64,
    /// what is being edited: the body, or a page's header and footer
    pub story: Story,
    /// paragraph -> layout index for the story being edited (not the body)
    story_index: HashMap<NodeId, usize>,
    /// where the caret was in the body (to go back to)
    body_caret: Option<(Pos, Pos)>,
    /// the document's file (FILENAME fields)
    pub file_name: String,
    /// Track Changes is on; edits are recorded under `author`
    pub track: bool,
    pub author: String,
    /// the next revision id (0: not looked up yet)
    rev_next: u64,
    /// Format Painter: the copied formatting
    painter: Option<tools::Painter>,
    /// the theme before a change in the open transaction
    pending_theme: Option<Box<XmlDoc>>,
    pending_parts: Vec<(String, Vec<u8>)>,
    /// more selected stretches besides anchor..caret (Select All Text With Similar
    /// Formatting, Select All N Instances): formatting goes to each
    pub extra_sel: Vec<(Pos, Pos)>,
}

/// The text the caret is in.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Story {
    Body,
    /// the header and footer of a page
    HeaderFooter(usize),
    /// the footnotes (and endnotes) shown on a page
    Notes(usize),
    /// a text box (its w:txbxContent) on a page
    TextBox(usize, NodeId),
}

mod objects;
mod hf;
mod fields;
mod refs;
mod views;
mod mail;
mod controls;
mod charts;
pub use refs::{BIB_NS, TOA_CATEGORIES};
mod review;
mod comments;
mod math;
mod clipboard;
mod search;
mod tools;
mod tabletools;
mod watermark;
mod design;
pub use watermark::Watermark;
pub use tools::Stats;
pub use search::FindOpts;
pub use math::MathInfo;
pub use comments::CommentInfo;
pub use review::{Change, ChangeKind};
pub use fields::{FieldInfo, parse_instr, format_date};
pub use objects::ObjInfo;

impl Editor {
    pub fn new(doc: Document, fonts: FontCache) -> Editor {
        let mut e = Editor {
            doc,
            fonts,
            layout: Layout { paras: Vec::new(), pages: Vec::new(), block_para: Vec::new(), index: HashMap::new(), body_count: 0, markup: crate::document::Markup::Simple },
            cache: ParaCache::new(),
            renderer: Renderer::new(),
            anchor: Pos { para: 0, off: 0 },
            caret: Pos { para: 0, off: 0 },
            goal_x: None,
            undo: Vec::new(),
            redo: Vec::new(),
            typing: false,
            pending: Vec::new(),
            line_loc: HashMap::new(),
            modified: false,
            txn_before: None,
            group: None,
            sel_obj: None,
            sel_more: Vec::new(),
            view_mode: 0,
            web_width: 612.0,
            story: Story::Body,
            story_index: HashMap::new(),
            body_caret: None,
            file_name: String::new(),
            track: false,
            author: "Author".into(),
            rev_next: 0,
            painter: None,
            pending_theme: None,
            pending_parts: Vec::new(),
            extra_sel: Vec::new(),
        };
        e.track = e.doc.settings.track_revisions;
        e.relayout();
        if let Some(p) = e.layout.paras.first() {
            e.caret = Pos { para: p.node, off: 0 };
            e.anchor = e.caret;
        }
        e
    }

    pub fn open(path: &str) -> Result<Editor, String> {
        let doc = Document::open_path(path).map_err(|e| e.0)?;
        Ok(Editor::new(doc, FontCache::new()))
    }

    // ------------------------------------------------------------ layout
    pub fn relayout(&mut self) {
        if self.view_mode != 0 {
            // Draft and Web Layout: the text runs on without pages; laid out in
            // tall strips the view shows edge to edge
            let keep = self.doc.sections.clone();
            for (i, s) in self.doc.sections.iter_mut().enumerate() {
                let text_w = s.text_width();
                let w = if self.view_mode == 2 { ((self.web_width * 20.0) as i32).max(2880) } else { text_w + 720 };
                s.page_w = w;
                s.page_h = 15840;
                s.left = 360;
                s.right = 360;
                s.gutter = 0;
                s.top = 0;
                s.bottom = 0;
                s.headers = [None; 3];
                s.footers = [None; 3];
                s.title_pg = false;
                s.v_align = "top".into();
                s.pg_borders = None;
                s.cols = 1;
                s.col_defs.clear();
                if i > 0 {
                    s.start = "continuous".into();
                }
            }
            crate::paginate::set_continuous(true, self.view_mode == 1);
            self.layout = layout_document_cached(&self.doc, &mut self.fonts, &mut self.cache);
            crate::paginate::set_continuous(false, false);
            self.doc.sections = keep;
        } else {
            self.layout = layout_document_cached(&self.doc, &mut self.fonts, &mut self.cache);
        }
        self.line_loc.clear();
        self.story_index.clear();
        if let Story::HeaderFooter(pg) | Story::Notes(pg) = self.story {
            if pg >= self.layout.pages.len() {
                self.story = Story::Body;
            }
        }
        if let Story::TextBox(pg, c) = self.story {
            // the text box may have moved to another page
            let at = |p: usize| self.layout.pages.get(p).is_some_and(|page| page.floats.iter().any(|f| f.float.pic.text.is_some_and(|t| t.0 == c)));
            self.story = if at(pg) {
                Story::TextBox(pg, c)
            } else {
                match (0..self.layout.pages.len()).find(|&p| at(p)) {
                    Some(p) => Story::TextBox(p, c),
                    None => Story::Body,
                }
            };
        }
        match self.story {
            Story::TextBox(pg, _) => {
                let lines = self.story_lines(pg).to_vec();
                for (i, l) in lines.iter().enumerate() {
                    self.line_loc.entry((l.para, l.line)).or_insert((pg, i));
                    self.story_index.entry(self.layout.paras[l.para].node).or_insert(l.para);
                }
            }
            Story::Body => {
                for (pg, page) in self.layout.pages.iter().enumerate() {
                    for (i, l) in page.lines.iter().enumerate() {
                        self.line_loc.entry((l.para, l.line)).or_insert((pg, i));
                    }
                }
            }
            Story::HeaderFooter(pg) | Story::Notes(pg) => {
                let lines = if matches!(self.story, Story::Notes(_)) {
                    &self.layout.pages[pg].note_lines
                } else {
                    &self.layout.pages[pg].hf_lines
                };
                for (i, l) in lines.iter().enumerate() {
                    self.line_loc.entry((l.para, l.line)).or_insert((pg, i));
                    self.story_index.entry(self.layout.paras[l.para].node).or_insert(l.para);
                }
            }
        }
        // keep the caret on a paragraph that still exists
        for p in [self.caret, self.anchor] {
            if !self.pidx(&p.para).is_some() {
                if let Some(first) = self.layout.paras.first() {
                    self.caret = Pos { para: first.node, off: 0 };
                    self.anchor = self.caret;
                }
                break;
            }
        }
    }

    fn dirty_paras(&mut self, ops: &[Op]) {
        let dom = &self.doc.dom;
        let mut dirty: HashSet<NodeId> = HashSet::new();
        fn all_paras(dom: &XmlDoc, n: NodeId, out: &mut HashSet<NodeId>) {
            for c in dom.elements(n) {
                if dom.is(c, "w:p") {
                    out.insert(c);
                } else {
                    all_paras(dom, c, out);
                }
            }
        }
        let up = |mut n: NodeId, out: &mut HashSet<NodeId>| {
            let mut in_para = false;
            loop {
                if dom.is(n, "w:p") {
                    out.insert(n);
                    in_para = true;
                }
                // table, row or cell formatting changes every paragraph in it
                if !in_para && dom.is(n, "w:tbl") {
                    all_paras(dom, n, out);
                }
                match dom.parent(n) {
                    Some(p) => n = p,
                    None => break,
                }
            }
        };
        for op in ops {
            match op {
                Op::Attrs { id, .. } | Op::Text { id, .. } | Op::Renamed { id, .. } => up(*id, &mut dirty),
                Op::Inserted { node } => up(*node, &mut dirty),
                Op::Detached { node, parent, .. } => {
                    up(*parent, &mut dirty);
                    up(*node, &mut dirty);
                }
            }
        }
        self.cache.retain(|(n, _), _| !dirty.contains(n));
    }

    /// A paragraph's layout index in the story being edited.
    fn pidx(&self, n: &NodeId) -> Option<&usize> {
        match self.story {
            Story::Body => self.layout.index.get(n),
            _ => self.story_index.get(n),
        }
    }

    /// The lines of the story being edited on a page.
    pub fn story_lines(&self, pg: usize) -> &[crate::paginate::Placed] {
        let Some(page) = self.layout.pages.get(pg) else { return &[] };
        match self.story {
            Story::Body => &page.lines,
            Story::HeaderFooter(p) if p == pg => &page.hf_lines,
            Story::Notes(p) if p == pg => &page.note_lines,
            Story::TextBox(p, c) if p == pg => page.floats.iter()
                .find(|f| f.float.pic.text.is_some_and(|t| t.0 == c))
                .map(|f| f.lines.as_slice()).unwrap_or(&[]),
            _ => &[],
        }
    }

    fn placed(&self, pg: usize, k: usize) -> &crate::paginate::Placed {
        &self.story_lines(pg)[k]
    }

    pub fn para_layout(&self, p: NodeId) -> Option<&Arc<ParaLayout>> {
        self.pidx(&p).map(|&i| &self.layout.paras[i])
    }

    fn para_len(&self, p: NodeId) -> usize {
        self.para_layout(p).map(|pl| pl.text_len).unwrap_or(0)
    }

    /// Document order of two positions.
    pub fn cmp(&self, a: Pos, b: Pos) -> std::cmp::Ordering {
        let ia = self.pidx(&a.para).copied().unwrap_or(0);
        let ib = self.pidx(&b.para).copied().unwrap_or(0);
        ia.cmp(&ib).then(a.off.cmp(&b.off))
    }

    pub fn selection(&self) -> (Pos, Pos) {
        if self.cmp(self.anchor, self.caret).is_le() {
            (self.anchor, self.caret)
        } else {
            (self.caret, self.anchor)
        }
    }

    pub fn has_selection(&self) -> bool {
        self.anchor != self.caret
    }

    // ---------------------------------------------------------- geometry
    fn line_index(pl: &ParaLayout, off: usize) -> usize {
        let n = pl.lines.len();
        for (i, l) in pl.lines.iter().enumerate() {
            if off < l.pos_end || i + 1 == n {
                return i;
            }
            // a position at a line's end that is the next line's start
            if off == l.pos_end && l.end > l.start {
                let last = &pl.units[l.end - 1];
                if matches!(last.kind, UnitKind::LineBreak | UnitKind::PageBreak | UnitKind::ColumnBreak) {
                    continue;
                }
            }
        }
        n.saturating_sub(1)
    }

    /// x of the start of an empty line (alignment applied).
    fn empty_line_x(pl: &ParaLayout, line: usize) -> f64 {
        let left = pl.left + if line == 0 { pl.first } else { 0.0 };
        let right = pl.width - pl.right;
        match pl.props.jc.as_deref() {
            Some("center") => (left + right) / 2.0,
            Some("right") | Some("end") => right,
            _ => left,
        }
    }

    /// x (relative to the paragraph box) of a position on a line.
    fn x_in_line(pl: &ParaLayout, li: usize, off: usize) -> f64 {
        let l = &pl.lines[li];
        if l.end == l.start {
            return Self::empty_line_x(pl, li);
        }
        for u in l.start..l.end {
            if pl.units[u].pos >= off && !pl.units[u].gen {
                return l.xs[u - l.start];
            }
        }
        if (l.start..l.end).all(|u| pl.units[u].gen) {
            let k = l.end - 1 - l.start;
            return l.xs[k] + l.ws[k];
        }
        let k = l.end - 1 - l.start;
        let last = &pl.units[l.end - 1];
        if matches!(last.kind, UnitKind::LineBreak | UnitKind::PageBreak | UnitKind::ColumnBreak) {
            return l.xs[k];
        }
        l.xs[k] + l.ws[k]
    }

    /// The caret's page and rectangle (x, y, height) for a position.
    pub fn caret_rect(&self, p: Pos) -> Option<(usize, f64, f64, f64)> {
        let pi = *self.pidx(&p.para)?;
        let pl = &self.layout.paras[pi];
        let li = Self::line_index(pl, p.off);
        let &(pg, k) = self.line_loc.get(&(pi, li))?;
        let placed = self.placed(pg, k);
        let line = &pl.lines[li];
        let x = placed.x + Self::x_in_line(pl, li, p.off);
        // as tall as the text next to it
        let mut asc = 0.0;
        let mut desc = 0.0;
        let near = (line.start..line.end)
            .rev()
            .find(|&u| pl.units[u].pos < p.off && !pl.units[u].gen)
            .or_else(|| (line.start..line.end).find(|&u| pl.units[u].pos >= p.off && !pl.units[u].gen));
        if let Some(u) = near {
            let u = &pl.units[u];
            if u.kind != UnitKind::Object {
                asc = u.asc;
                desc = u.desc;
            }
        }
        if asc + desc <= 0.0 {
            asc = line.baseline;
            desc = (line.height - line.baseline).max(0.0);
        }
        let top = placed.y + line.baseline - asc;
        if let Some(fr) = placed.frame {
            // turned text: the caret crosses the line where the position is
            let (cx, cy) = crate::render::frame_to_page(fr, x, top + (asc + desc) / 2.0);
            let h = asc + desc;
            return Some((pg, cx, cy - h / 2.0, h));
        }
        Some((pg, x, top, asc + desc))
    }

    /// Selection rectangles per page: (page, x, y, w, h).
    pub fn selection_rects(&self) -> Vec<(usize, f64, f64, f64, f64)> {
        let mut out = self.range_sel_rects(self.selection());
        for &(a, b) in &self.extra_sel {
            out.extend(self.range_sel_rects(if self.cmp(a, b) == std::cmp::Ordering::Greater { (b, a) } else { (a, b) }));
        }
        out
    }

    /// How many body paragraphs have this paragraph style.
    pub fn count_style_instances(&self, id: &str) -> usize {
        let default = self.doc.styles.default_para.clone().unwrap_or_default();
        let dom = &self.doc.dom;
        self.layout.paras[..self.layout.body_count.min(self.layout.paras.len())].iter().filter(|pl| {
            dom.child(pl.node, "w:pPr").and_then(|pp| dom.child(pp, "w:pStyle"))
                .and_then(|n| dom.attr(n, "w:val")).map(|v| v.to_string()).unwrap_or(default.clone()) == id
        }).count()
    }

    /// Select every body paragraph with this paragraph style; how many.
    pub fn select_style_instances(&mut self, id: &str) -> usize {
        let default = self.doc.styles.default_para.clone().unwrap_or_default();
        let mut ranges = Vec::new();
        for pl in self.layout.paras[..self.layout.body_count.min(self.layout.paras.len())].to_vec() {
            let dom = &self.doc.dom;
            let st = dom.child(pl.node, "w:pPr").and_then(|pp| dom.child(pp, "w:pStyle"))
                .and_then(|n| dom.attr(n, "w:val")).map(|v| v.to_string()).unwrap_or(default.clone());
            if st == id {
                let len = self.fresh_len(pl.node);
                ranges.push((Pos { para: pl.node, off: 0 }, Pos { para: pl.node, off: len }));
            }
        }
        let n = ranges.len();
        self.select_ranges(&ranges);
        n
    }

    /// Select several stretches at once (the first one is anchor..caret).
    pub fn select_ranges(&mut self, ranges: &[(Pos, Pos)]) {
        let Some(&(a, b)) = ranges.first() else { return };
        self.move_to(a, false, false);
        self.move_to(b, true, false);
        self.extra_sel = ranges[1..].to_vec();
    }

    /// Run a formatting command on each selected stretch (one undo step).
    fn each_range(&mut self, name: &str, f: &mut dyn FnMut(&mut Self)) -> bool {
        if self.extra_sel.is_empty() {
            return false;
        }
        let all: Vec<(Pos, Pos)> = std::iter::once((self.anchor, self.caret)).chain(self.extra_sel.drain(..)).collect();
        self.begin_group(name);
        for &(a, b) in &all {
            self.anchor = a;
            self.caret = b;
            f(self);
        }
        self.end_group();
        self.anchor = all[0].0;
        self.caret = all[0].1;
        self.extra_sel = all[1..].to_vec();
        true
    }

    fn range_sel_rects(&self, sel: (Pos, Pos)) -> Vec<(usize, f64, f64, f64, f64)> {
        let (a, b) = sel;
        let mut out = Vec::new();
        if a == b {
            return out;
        }
        let ia = self.pidx(&a.para).copied().unwrap_or(0);
        let ib = self.pidx(&b.para).copied().unwrap_or(0);
        let rect = self.cell_rect(a.para, b.para).map(|_| self.paras_between(a.para, b.para));
        for pi in ia..=ib.min(self.layout.paras.len().saturating_sub(1)) {
            let pl = &self.layout.paras[pi];
            if rect.as_ref().is_some_and(|r| !r.contains(&pl.node)) {
                continue;
            }
            let s = if pi == ia { a.off } else { 0 };
            let e = if pi == ib { b.off } else { pl.text_len };
            let past_end = pi != ib;
            for (li, line) in pl.lines.iter().enumerate() {
                let last_line = li + 1 == pl.lines.len();
                if line.pos_end < s || line.pos_start > e || (line.pos_end == s && !last_line && line.end > line.start) {
                    continue;
                }
                let Some(&(pg, k)) = self.line_loc.get(&(pi, li)) else { continue };
                let placed = self.placed(pg, k);
                let x1 = Self::x_in_line(pl, li, s.max(line.pos_start));
                let mut x2 = Self::x_in_line(pl, li, e.min(line.pos_end));
                if (past_end && last_line) || e > line.pos_end {
                    // the paragraph mark / line end shows as a little block
                    x2 += pl.mark_style.size * 0.4;
                }
                if x2 > x1 {
                    if let Some(fr) = placed.frame {
                        let (ax, ay) = crate::render::frame_to_page(fr, placed.x + x1, placed.y);
                        let (bx, by) = crate::render::frame_to_page(fr, placed.x + x2, placed.y + line.height);
                        out.push((pg, ax.min(bx), ay.min(by), (ax - bx).abs(), (ay - by).abs()));
                    } else {
                        out.push((pg, placed.x + x1, placed.y, x2 - x1, line.height));
                    }
                }
            }
        }
        out
    }

    /// The position under a point on a page (points from the page corner).
    pub fn hit(&self, page: usize, x: f64, y: f64) -> Option<Pos> {
        let lines = self.story_lines(page);
        if lines.is_empty() {
            return None;
        }
        // turned text (cells with a text direction): the point in the frame
        for l in lines.iter().filter(|l| l.frame.is_some()) {
            let (lx, ly) = crate::render::page_to_frame(l.frame.unwrap(), x, y);
            let pl = &self.layout.paras[l.para];
            let h = pl.lines[l.line].height;
            if ly >= l.y && ly <= l.y + h && lx >= l.x - 2.0 && lx <= l.x + pl.width + 2.0 {
                return Some(Pos { para: pl.node, off: Self::pos_at_x(pl, l.line, lx - l.x) });
            }
        }
        let framed: Vec<crate::paginate::Placed> = lines.iter().filter(|l| l.frame.is_none()).cloned().collect();
        let lines: &[crate::paginate::Placed] = if framed.len() == lines.len() { lines } else { &framed };
        if lines.is_empty() {
            return None;
        }
        // lines whose box contains x (columns, table cells), else all
        let within = |l: &crate::paginate::Placed| {
            let pl = &self.layout.paras[l.para];
            x >= l.x - 4.0 && x <= l.x + pl.width + 4.0
        };
        let mut best: Option<(f64, usize)> = None;
        for pass in 0..2 {
            for (i, l) in lines.iter().enumerate() {
                if pass == 0 && !within(l) {
                    continue;
                }
                let h = self.layout.paras[l.para].lines[l.line].height;
                let d = if y < l.y { l.y - y } else if y > l.y + h { y - l.y - h } else { 0.0 };
                if best.map(|(bd, _)| d < bd).unwrap_or(true) {
                    best = Some((d, i));
                }
            }
            if best.is_some() {
                break;
            }
        }
        let (bd, mut i) = best?;
        // lines sharing a row (a paragraph running on into the next): the
        // one whose text starts left of the point, the rightmost such
        let start_x = |l: &crate::paginate::Placed| {
            let pl = &self.layout.paras[l.para];
            l.x + pl.lines[l.line].xs.first().copied().unwrap_or(0.0)
        };
        let mut best_start = f64::NEG_INFINITY;
        for (j, l) in lines.iter().enumerate() {
            let h = self.layout.paras[l.para].lines[l.line].height;
            let d = if y < l.y { l.y - y } else if y > l.y + h { y - l.y - h } else { 0.0 };
            if (d - bd).abs() < 0.01 && within(l) {
                let sx = start_x(l);
                if sx <= x + 1.0 && sx > best_start {
                    best_start = sx;
                    i = j;
                }
            }
        }
        let l = &lines[i];
        let pl = &self.layout.paras[l.para];
        Some(Pos { para: pl.node, off: Self::pos_at_x(pl, l.line, x - l.x) })
    }

    fn pos_at_x(pl: &ParaLayout, li: usize, x: f64) -> usize {
        let line = &pl.lines[li];
        for u in line.start..line.end {
            let k = u - line.start;
            let unit = &pl.units[u];
            if unit.gen {
                continue;
            }
            if matches!(unit.kind, UnitKind::LineBreak | UnitKind::PageBreak | UnitKind::ColumnBreak) {
                return unit.pos;
            }
            if x < line.xs[k] + line.ws[k] / 2.0 {
                return unit.pos;
            }
        }
        if li + 1 == pl.lines.len() {
            return pl.text_len;
        }
        // after a wrapped line: before its trailing space
        if line.end > line.start {
            let last = &pl.units[line.end - 1];
            if matches!(last.kind, UnitKind::Char(' ')) {
                return last.pos;
            }
        }
        line.pos_end
    }

    // -------------------------------------------------------- navigation
    fn stops(pl: &ParaLayout) -> Vec<usize> {
        let mut v: Vec<usize> = pl.units.iter().filter(|u| !u.gen).map(|u| u.pos).collect();
        v.insert(0, 0);
        v.push(pl.text_len);
        v.dedup();
        v
    }

    pub fn next_pos(&self, p: Pos) -> Pos {
        let Some(&pi) = self.pidx(&p.para) else { return p };
        let pl = &self.layout.paras[pi];
        if let Some(&s) = Self::stops(pl).iter().find(|&&s| s > p.off) {
            return Pos { para: p.para, off: s };
        }
        match self.layout.paras.get(pi + 1) {
            Some(n) => Pos { para: n.node, off: Self::stops(n)[0].min(0) },
            None => p,
        }
    }

    pub fn prev_pos(&self, p: Pos) -> Pos {
        let Some(&pi) = self.pidx(&p.para) else { return p };
        let pl = &self.layout.paras[pi];
        if let Some(&s) = Self::stops(pl).iter().rev().find(|&&s| s < p.off) {
            return Pos { para: p.para, off: s };
        }
        if p.off > 0 {
            return Pos { para: p.para, off: 0 };
        }
        match pi.checked_sub(1).and_then(|i| self.layout.paras.get(i)) {
            Some(n) => Pos { para: n.node, off: n.text_len },
            None => p,
        }
    }

    fn para_chars(pl: &ParaLayout) -> Vec<(usize, char)> {
        pl.units
            .iter()
            .filter(|u| !u.gen)
            .map(|u| {
                (u.pos, match u.kind {
                    UnitKind::Char(c) => c,
                    UnitKind::Tab => '\t',
                    UnitKind::Object | UnitKind::Anchor | UnitKind::Math => '\u{fffc}',
                    _ => '\n',
                })
            })
            .collect()
    }

    fn is_word_char(c: char) -> bool {
        c.is_alphanumeric() || c == '_' || c == '\''
    }

    /// Ctrl+Right: the start of the next word (spaces after a word belong
    /// to it, as in the original).
    pub fn next_word(&self, p: Pos) -> Pos {
        let Some(pl) = self.para_layout(p.para) else { return p };
        let cs = Self::para_chars(pl);
        let mut i = cs.iter().position(|(pos, _)| *pos >= p.off).unwrap_or(cs.len());
        if i >= cs.len() {
            return self.next_pos(p);
        }
        let kind = |c: char| if c.is_whitespace() { 0 } else if Self::is_word_char(c) { 1 } else { 2 };
        let k0 = kind(cs[i].1);
        if k0 != 0 {
            while i < cs.len() && kind(cs[i].1) == k0 {
                i += 1;
            }
        }
        while i < cs.len() && kind(cs[i].1) == 0 && cs[i].1 != '\t' && cs[i].1 != '\n' {
            i += 1;
        }
        if k0 == 0 && i < cs.len() && cs[i].1 == '\t' {
            i += 1;
        }
        Pos { para: p.para, off: cs.get(i).map(|c| c.0).unwrap_or(pl.text_len) }
    }

    pub fn prev_word(&self, p: Pos) -> Pos {
        let Some(pl) = self.para_layout(p.para) else { return p };
        let cs = Self::para_chars(pl);
        let mut i = cs.iter().position(|(pos, _)| *pos >= p.off).unwrap_or(cs.len());
        if i == 0 {
            return self.prev_pos(p);
        }
        let kind = |c: char| if c.is_whitespace() { 0 } else if Self::is_word_char(c) { 1 } else { 2 };
        while i > 0 && kind(cs[i - 1].1) == 0 && cs[i - 1].1 != '\n' {
            i -= 1;
        }
        if i > 0 {
            let k = kind(cs[i - 1].1);
            while i > 0 && kind(cs[i - 1].1) == k && k != 0 {
                i -= 1;
            }
        }
        Pos { para: p.para, off: cs.get(i).map(|c| c.0).unwrap_or(0) }
    }

    /// The word around a position (double click).
    pub fn word_at(&self, p: Pos) -> (Pos, Pos) {
        let Some(pl) = self.para_layout(p.para) else { return (p, p) };
        let cs = Self::para_chars(pl);
        let i = cs.iter().position(|(pos, _)| *pos >= p.off).unwrap_or(cs.len());
        let kind = |c: char| if c.is_whitespace() { 0 } else if Self::is_word_char(c) { 1 } else { 2 };
        let at = if i < cs.len() { i } else if i > 0 { i - 1 } else { return (p, p) };
        let k = kind(cs[at].1);
        let mut s = at;
        while s > 0 && kind(cs[s - 1].1) == k {
            s -= 1;
        }
        let mut e = at + 1;
        while e < cs.len() && kind(cs[e].1) == k {
            e += 1;
        }
        // the original selects the space after a word too
        if k == 1 {
            while e < cs.len() && cs[e].1 == ' ' {
                e += 1;
            }
        }
        let off = |j: usize| cs.get(j).map(|c| c.0).unwrap_or(pl.text_len);
        (Pos { para: p.para, off: off(s) }, Pos { para: p.para, off: off(e) })
    }

    pub fn line_start(&self, p: Pos) -> Pos {
        let Some(pl) = self.para_layout(p.para) else { return p };
        let li = Self::line_index(pl, p.off);
        Pos { para: p.para, off: pl.lines[li].pos_start }
    }

    pub fn line_end(&self, p: Pos) -> Pos {
        let Some(pl) = self.para_layout(p.para) else { return p };
        let li = Self::line_index(pl, p.off);
        let l = &pl.lines[li];
        if li + 1 == pl.lines.len() {
            return Pos { para: p.para, off: pl.text_len };
        }
        let mut off = l.pos_end;
        if l.end > l.start {
            let last = &pl.units[l.end - 1];
            if matches!(last.kind, UnitKind::Char(' ') | UnitKind::LineBreak | UnitKind::PageBreak | UnitKind::ColumnBreak) {
                off = last.pos;
            }
        }
        Pos { para: p.para, off }
    }

    /// Up/down by a line, keeping the caret's x.
    pub fn line_move(&mut self, p: Pos, down: bool) -> Pos {
        let Some(&pi) = self.pidx(&p.para) else { return p };
        let pl = &self.layout.paras[pi];
        let li = Self::line_index(pl, p.off);
        let goal = match self.goal_x {
            Some(g) => g,
            None => {
                let g = self.caret_rect(p).map(|r| r.1).unwrap_or(0.0);
                self.goal_x = Some(g);
                g
            }
        };
        // the visually next line: the next one placed on a page
        let target = if down {
            if li + 1 < pl.lines.len() {
                Some((pi, li + 1))
            } else {
                (pi + 1..self.layout.paras.len()).find(|&q| !self.layout.paras[q].lines.is_empty() && self.line_loc.contains_key(&(q, 0))).map(|q| (q, 0))
            }
        } else if li > 0 {
            Some((pi, li - 1))
        } else {
            (0..pi).rev().find(|&q| self.line_loc.contains_key(&(q, 0))).map(|q| (q, self.layout.paras[q].lines.len() - 1))
        };
        let Some((q, ql)) = target else {
            return if down { Pos { para: p.para, off: pl.text_len } } else { Pos { para: p.para, off: 0 } };
        };
        let Some(&(pg, k)) = self.line_loc.get(&(q, ql)) else { return p };
        let placed = self.placed(pg, k);
        let qp = &self.layout.paras[q];
        Pos { para: qp.node, off: Self::pos_at_x(qp, ql, goal - placed.x) }
    }

    /// The paragraph layouts of the story being edited, in order.
    fn story_range(&self) -> Vec<usize> {
        match self.story {
            Story::Body => (0..self.layout.body_count.min(self.layout.paras.len())).collect(),
            Story::HeaderFooter(pg) | Story::Notes(pg) | Story::TextBox(pg, _) => {
                let mut v: Vec<usize> = self.story_lines(pg).iter().map(|l| l.para).collect();
                v.dedup();
                v
            }
        }
    }

    pub fn doc_start(&self) -> Pos {
        self.story_range().first().map(|&i| Pos { para: self.layout.paras[i].node, off: 0 }).unwrap_or(self.caret)
    }

    pub fn doc_end(&self) -> Pos {
        self.story_range()
            .last()
            .map(|&i| {
                let p = &self.layout.paras[i];
                Pos { para: p.node, off: p.text_len }
            })
            .unwrap_or(self.caret)
    }

    /// Edit page `pg`'s header and footer (None: back to the body). The
    /// caret goes to the start of the header (or footer).
    pub fn edit_header_footer(&mut self, pg: Option<usize>, footer: bool) {
        self.sel_obj = None;
        match pg {
            None => {
                self.story = Story::Body;
                self.relayout();
                match self.body_caret.take() {
                    Some((a, c)) if self.pidx(&a.para).is_some() && self.pidx(&c.para).is_some() => {
                        self.anchor = a;
                        self.caret = c;
                    }
                    _ => {
                        let p = self.doc_start();
                        self.caret = p;
                        self.anchor = p;
                    }
                }
            }
            Some(pg) => {
                self.leave_body();
                self.story = Story::HeaderFooter(pg);
                self.relayout();
                let page = &self.layout.pages[pg];
                let want = if footer { page.footer } else { page.header };
                let root = want.map(|i| self.doc.parts[i].root);
                let first = self.layout.pages[pg].hf_lines.iter().find(|l| {
                    let n = self.layout.paras[l.para].node;
                    root.map_or(true, |r| self.under(n, r))
                });
                if let Some(l) = first {
                    let p = Pos { para: self.layout.paras[l.para].node, off: 0 };
                    self.caret = p;
                    self.anchor = p;
                }
            }
        }
        self.goal_x = None;
    }

    /// The text box at a point of a page (its content), when the point is
    /// inside its text area.
    pub fn textbox_at(&self, pg: usize, x: f64, y: f64) -> Option<NodeId> {
        let page = self.layout.pages.get(pg)?;
        page.floats.iter().rev().find_map(|f| {
            let pic = &f.float.pic;
            let (c, ins, _) = pic.text?;
            let inside = x >= f.x + ins[0].min(4.0) && x <= f.x + pic.w - ins[2].min(4.0)
                && y >= f.y + ins[1].min(4.0) && y <= f.y + pic.h - ins[3].min(4.0);
            (inside && pic.rot == 0.0).then_some(c)
        })
    }

    /// Edit the text in a text box (clicked at x, y on page pg).
    pub fn edit_textbox(&mut self, pg: usize, x: f64, y: f64) -> bool {
        let Some(c) = self.textbox_at(pg, x, y) else { return false };
        if self.story == Story::Body {
            self.leave_body();
        }
        self.sel_obj = None;
        self.story = Story::TextBox(pg, c);
        self.relayout();
        match self.hit(pg, x, y) {
            Some(p) => {
                self.caret = p;
                self.anchor = p;
            }
            None => {
                let p = self.doc_start();
                self.caret = p;
                self.anchor = p;
            }
        }
        self.goal_x = None;
        true
    }

    /// Remember the body's caret before editing another story.
    fn leave_body(&mut self) {
        if self.story == Story::Body {
            self.body_caret = Some((self.anchor, self.caret));
        }
    }

    fn under(&self, mut n: NodeId, root: NodeId) -> bool {
        loop {
            if n == root {
                return true;
            }
            match self.doc.dom.parent(n) {
                Some(p) => n = p,
                None => return false,
            }
        }
    }

    /// Move the caret; with `extend` the selection grows.
    pub fn move_to(&mut self, p: Pos, extend: bool, keep_goal: bool) {
        self.extra_sel.clear();
        self.caret = p;
        if !extend {
            self.anchor = p;
        }
        if !keep_goal {
            self.goal_x = None;
        }
        self.typing = false;
        self.pending.clear();
    }

    pub fn select_all(&mut self) {
        self.extra_sel.clear();
        self.anchor = self.doc_start();
        self.caret = self.doc_end();
        self.typing = false;
    }

    // ------------------------------------------------------- transactions
    fn begin(&mut self) {
        self.doc.dom.journal.clear();
        self.doc.dom.recording = true;
        if let Some(nd) = self.doc.num_dom.as_mut() {
            nd.journal.clear();
            nd.recording = true;
        }
        if let Some(sd) = self.doc.styles_dom.as_mut() {
            sd.journal.clear();
            sd.recording = true;
        }
        self.txn_before = Some((self.anchor, self.caret));
    }

    fn commit(&mut self, name: &str, mergeable: bool) {
        self.doc.dom.recording = false;
        let ops = std::mem::take(&mut self.doc.dom.journal);
        let num_ops = match self.doc.num_dom.as_mut() {
            Some(nd) => {
                nd.recording = false;
                std::mem::take(&mut nd.journal)
            }
            None => Vec::new(),
        };
        let sty_ops = match self.doc.styles_dom.as_mut() {
            Some(sd) => {
                sd.recording = false;
                std::mem::take(&mut sd.journal)
            }
            None => Vec::new(),
        };
        let before = self.txn_before.take().unwrap_or((self.anchor, self.caret));
        if ops.is_empty() && num_ops.is_empty() && sty_ops.is_empty() && self.pending_theme.is_none()
            && self.pending_parts.is_empty() {
            return;
        }
        self.dirty_paras(&ops);
        if !num_ops.is_empty() {
            self.doc.reload_numbering();
            self.cache.clear();
        }
        if !sty_ops.is_empty() {
            self.doc.reload_styles();
            self.cache.clear();
        }
        let old_marks = self.doc.notes.numbers.clone();
        self.doc.scan();
        if old_marks != self.doc.notes.numbers {
            // notes renumbered: their paragraphs show new marks
            let mut stale = HashSet::new();
            for (r, m) in &self.doc.notes.numbers {
                if old_marks.get(r) != Some(m) {
                    let mut n = *r;
                    while let Some(p) = self.doc.dom.parent(n) {
                        if self.doc.dom.is(p, "w:p") {
                            stale.insert(p);
                            break;
                        }
                        n = p;
                    }
                }
            }
            for (_, &note) in self.doc.notes.footnotes.iter().chain(self.doc.notes.endnotes.iter()) {
                if let Some(p) = self.doc.dom.elements(note).find(|&c| self.doc.dom.is(c, "w:p")) {
                    stale.insert(p);
                }
            }
            self.cache.retain(|(n, _), _| !stale.contains(n));
        }
        self.relayout();
        let after = (self.anchor, self.caret);
        if mergeable && self.typing && num_ops.is_empty() && sty_ops.is_empty() && self.pending_theme.is_none()
            && self.pending_parts.is_empty() {
            if let Some(last) = self.undo.last_mut() {
                if last.name == name {
                    last.ops.extend(ops);
                    last.after = after;
                    self.redo.clear();
                    self.modified = true;
                    return;
                }
            }
        }
        let theme = self.pending_theme.take();
        let parts = std::mem::take(&mut self.pending_parts);
        self.undo.push(Txn { name: name.into(), ops, num_ops, sty_ops, before, after, theme, parts });
        if self.undo.len() > 500 {
            self.undo.remove(0);
        }
        self.redo.clear();
        self.typing = mergeable;
        self.modified = true;
    }

    /// Several changes that undo as one (a dialog's OK).
    pub fn begin_group(&mut self, name: &str) {
        if self.group.is_none() {
            self.group = Some((name.to_string(), self.undo.len()));
        }
    }

    pub fn end_group(&mut self) {
        let Some((name, start)) = self.group.take() else { return };
        if self.undo.len() <= start + 1 {
            if let Some(t) = self.undo.get_mut(start) {
                t.name = name;
            }
            return;
        }
        let parts: Vec<Txn> = self.undo.drain(start..).collect();
        let before = parts[0].before;
        let after = parts.last().unwrap().after;
        let mut ops = Vec::new();
        let mut num_ops = Vec::new();
        let mut sty_ops = Vec::new();
        let mut theme = None;
        let mut pparts: Vec<(String, Vec<u8>)> = Vec::new();
        for t in parts {
            ops.extend(t.ops);
            num_ops.extend(t.num_ops);
            sty_ops.extend(t.sty_ops);
            if theme.is_none() {
                theme = t.theme;
            }
            for (n, b) in t.parts {
                if !pparts.iter().any(|(m, _)| *m == n) {
                    pparts.push((n, b));
                }
            }
        }
        self.undo.push(Txn { name, ops, num_ops, sty_ops, before, after, theme, parts: pparts });
        self.typing = false;
    }

    pub fn can_undo(&self) -> bool {
        !self.undo.is_empty()
    }

    pub fn can_redo(&self) -> bool {
        !self.redo.is_empty()
    }

    pub fn undo_name(&self) -> Option<&str> {
        self.undo.last().map(|t| t.name.as_str())
    }

    fn revert_num(&mut self, ops: &[Op]) -> Vec<Op> {
        if ops.is_empty() {
            return Vec::new();
        }
        let back = match self.doc.num_dom.as_mut() {
            Some(nd) => nd.revert(ops),
            None => Vec::new(),
        };
        self.doc.reload_numbering();
        self.cache.clear();
        back
    }

    fn revert_sty(&mut self, ops: &[Op]) -> Vec<Op> {
        if ops.is_empty() {
            return Vec::new();
        }
        let back = match self.doc.styles_dom.as_mut() {
            Some(sd) => sd.revert(ops),
            None => Vec::new(),
        };
        self.doc.reload_styles();
        self.cache.clear();
        back
    }

    pub fn undo(&mut self) {
        self.extra_sel.clear();
        let Some(t) = self.undo.pop() else { return };
        let redo_ops = self.doc.dom.revert(&t.ops);
        let redo_num = self.revert_num(&t.num_ops);
        let redo_sty = self.revert_sty(&t.sty_ops);
        let redo_theme = t.theme.map(|th| Box::new(self.swap_theme(*th)));
        let redo_parts = self.swap_parts(t.parts);
        self.dirty_paras(&t.ops);
        self.dirty_paras(&redo_ops);
        self.doc.scan();
        self.relayout();
        self.anchor = t.before.0;
        self.caret = t.before.1;
        self.redo.push(Txn { name: t.name, ops: redo_ops, num_ops: redo_num, sty_ops: redo_sty, before: t.before, after: t.after,
                             theme: redo_theme, parts: redo_parts });
        self.typing = false;
        self.modified = true;
    }

    pub fn redo(&mut self) {
        self.extra_sel.clear();
        let Some(t) = self.redo.pop() else { return };
        let undo_ops = self.doc.dom.revert(&t.ops);
        let undo_num = self.revert_num(&t.num_ops);
        let undo_sty = self.revert_sty(&t.sty_ops);
        let undo_theme = t.theme.map(|th| Box::new(self.swap_theme(*th)));
        let undo_parts = self.swap_parts(t.parts);
        self.dirty_paras(&t.ops);
        self.dirty_paras(&undo_ops);
        self.doc.scan();
        self.relayout();
        self.anchor = t.after.0;
        self.caret = t.after.1;
        self.undo.push(Txn { name: t.name, ops: undo_ops, num_ops: undo_num, sty_ops: undo_sty, before: t.before, after: t.after,
                             theme: undo_theme, parts: undo_parts });
        self.typing = false;
        self.modified = true;
    }

    /// Put parts back as they were; returns them as they are now.
    fn swap_parts(&mut self, parts: Vec<(String, Vec<u8>)>) -> Vec<(String, Vec<u8>)> {
        let mut now = Vec::new();
        for (name, bytes) in parts {
            let cur = self.part_bytes(&name);
            self.put_part_bytes(&name, bytes);
            now.push((name, cur));
        }
        if !now.is_empty() {
            self.cache.clear();
        }
        now
    }

    /// A part's bytes as they'd be saved.
    pub(crate) fn part_bytes(&mut self, name: &str) -> Vec<u8> {
        if let Ok(x) = self.doc.pkg.xml(name) {
            return x.serialize().into_bytes();
        }
        self.doc.pkg.raw(name).map(|b| b.to_vec()).unwrap_or_default()
    }

    /// Write a part's bytes (and what draws from it: charts).
    pub(crate) fn put_part_bytes(&mut self, name: &str, bytes: Vec<u8>) {
        let arc = std::sync::Arc::new(bytes.clone());
        self.doc.pkg.put_raw(name, bytes);
        for img in self.doc.images.values_mut() {
            if img.part == name {
                img.bytes = arc.clone();
            }
        }
        for sp in self.doc.parts.iter_mut() {
            for img in sp.images.values_mut() {
                if img.part == name {
                    img.bytes = arc.clone();
                }
            }
        }
    }

    // ----------------------------------------------------- DOM utilities
    fn pieces(&self, p: NodeId) -> Vec<(Piece, usize, usize)> {
        let (_, base) = self.doc.para_props(p);
        let mut pos = 0;
        self.doc
            .para_pieces(p, &base)
            .into_iter()
            .map(|pc| {
                let s = pos;
                pos += pc.item.len();
                (pc, s, pos)
            })
            .collect()
    }

    fn run_of(&self, n: NodeId) -> Option<NodeId> {
        let dom = &self.doc.dom;
        let mut c = n;
        loop {
            if dom.is(c, "w:r") {
                return Some(c);
            }
            if dom.is(c, "w:p") {
                return None;
            }
            c = dom.parent(c)?;
        }
    }

    /// Replace the text of a w:t element.
    fn set_t(&mut self, t: NodeId, text: &str) {
        let dom = &mut self.doc.dom;
        let kids: Vec<NodeId> = dom.children(t).to_vec();
        let mut done = false;
        for k in kids {
            if !done && dom.text_of_node(k).is_some() {
                dom.set_text(k, text);
                done = true;
            } else {
                dom.detach(k);
            }
        }
        if !done {
            let n = dom.new_text(text);
            dom.append(t, n);
        }
        let needs = text.starts_with(' ') || text.ends_with(' ') || text.contains("  ") || text.contains('\t');
        if needs && dom.attr(t, "xml:space") != Some("preserve") {
            dom.set_attr(t, "xml:space", "preserve");
        }
    }

    /// Split the w:t `t` after `k` characters; returns the new second w:t.
    fn split_t(&mut self, t: NodeId, k: usize) -> NodeId {
        let text = self.doc.dom.text(t);
        let a: String = text.chars().take(k).collect();
        let b: String = text.chars().skip(k).collect();
        self.set_t(t, &a);
        let dom = &mut self.doc.dom;
        let n = dom.new_element("w:t", &[]);
        let (parent, idx) = (dom.parent(t).unwrap(), dom.index_in_parent(t).unwrap());
        dom.insert(parent, idx + 1, n);
        self.set_t(n, &b);
        n
    }

    /// Split the element `a` before its child `child`: the children before
    /// it move into a copy of `a` inserted before `a`. Property children
    /// (rPr, sdtPr...) are copied. Returns the copy.
    fn split_element_before(&mut self, a: NodeId, child: NodeId) -> NodeId {
        let dom = &mut self.doc.dom;
        let kind = dom.node(a).kind.clone();
        let (name, attrs) = match kind {
            Kind::Element { name, attrs } => (name, attrs),
            _ => unreachable!(),
        };
        let a2: Vec<(&str, &str)> = attrs
            .iter()
            .filter(|(k, _)| !k.ends_with("paraId") && !k.ends_with("textId"))
            .map(|(k, v)| (k.as_str(), v.as_str()))
            .collect();
        let copy = dom.new_element(&name, &a2);
        let kids: Vec<NodeId> = dom.children(a).to_vec();
        for k in kids {
            if k == child {
                break;
            }
            let is_prop = matches!(&dom.node(k).kind, Kind::Element { name, .. } if is_prop_name(name));
            if is_prop {
                let c = dom.clone_node(k);
                dom.append(copy, c);
            } else {
                dom.detach(k);
                dom.append(copy, k);
            }
        }
        let parent = dom.parent(a).unwrap();
        let idx = dom.index_in_parent(a).unwrap();
        dom.insert(parent, idx, copy);
        copy
    }

    /// Make a run boundary at `off` in paragraph `p`. Returns where a new
    /// run goes (parent, index) and the run whose formatting it takes.
    fn split_runs_at(&mut self, p: NodeId, off: usize) -> (NodeId, usize, Option<NodeId>) {
        let pieces = self.pieces(p);
        // inside a text piece
        for (pc, s, e) in &pieces {
            if let (Item::Text(_), Some(node)) = (&pc.item, pc.node) {
                if *s < off && off < *e && self.doc.dom.is(node, "w:t") {
                    let second = self.split_t(node, off - s);
                    let run = self.run_of(second).unwrap();
                    let left = self.split_element_before(run, second);
                    let dom = &self.doc.dom;
                    let parent = dom.parent(run).unwrap();
                    return (parent, dom.index_in_parent(run).unwrap(), Some(left));
                }
            }
        }
        let prev = pieces.iter().rev().find(|(pc, _, e)| *e <= off && pc.item.len() > 0 && pc.change != "del");
        if let Some((pc, _, _)) = prev {
            let node = pc.node.unwrap();
            if let Some(run) = self.run_of(node) {
                let dom = &self.doc.dom;
                // the run's content after this piece
                let kids = dom.children(run).to_vec();
                let i = kids.iter().position(|&k| k == node).unwrap_or(kids.len());
                let after: Vec<NodeId> = kids[i + 1..].to_vec();
                let r = if after.is_empty() {
                    run
                } else {
                    let left = self.split_element_before(run, after[0]);
                    let _ = left;
                    // `run` now holds what came after; insert before it
                    let dom = &self.doc.dom;
                    let parent = dom.parent(run).unwrap();
                    let idx = dom.index_in_parent(run).unwrap();
                    let left = dom.children(parent)[idx - 1];
                    return (parent, idx, Some(left));
                };
                let dom = &self.doc.dom;
                let mut anchor = r;
                // never inside deleted text
                while let Some(par) = dom.parent(anchor) {
                    if dom.is(par, "w:del") || dom.is(par, "w:moveFrom") || dom.is(par, "w:fldSimple") {
                        anchor = par;
                    } else {
                        break;
                    }
                }
                let parent = dom.parent(anchor).unwrap();
                let mut idx = dom.index_in_parent(anchor).unwrap() + 1;
                // after a field's result: past the field's end
                let kids = dom.children(parent).to_vec();
                while let Some(&k) = kids.get(idx) {
                    let is_end = dom.is(k, "w:r") && dom.elements(k).any(|c| dom.is(c, "w:fldChar")
                        && dom.attr(c, "w:fldCharType") == Some("end"))
                        && dom.elements(k).all(|c| dom.is(c, "w:rPr") || dom.is(c, "w:fldChar"));
                    if is_end {
                        idx += 1;
                    } else {
                        break;
                    }
                }
                return (parent, idx, Some(r));
            }
        }
        let next = pieces.iter().find(|(pc, s, _)| *s >= off && pc.item.len() > 0 && pc.change != "del");
        if let Some((pc, _, _)) = next {
            let node = pc.node.unwrap();
            if let Some(run) = self.run_of(node) {
                let dom = &self.doc.dom;
                let kids = dom.children(run).to_vec();
                let first_content = kids.iter().position(|&k| !matches!(&dom.node(k).kind, Kind::Element { name, .. } if name == "w:rPr"));
                let i = kids.iter().position(|&k| k == node).unwrap_or(0);
                if Some(i) != first_content {
                    self.split_element_before(run, node);
                }
                let dom = &self.doc.dom;
                let parent = dom.parent(run).unwrap();
                return (parent, dom.index_in_parent(run).unwrap(), Some(run));
            }
        }
        let dom = &self.doc.dom;
        (p, dom.children(p).len(), None)
    }

    /// A new run with the formatting of `like` (or the paragraph mark).
    fn new_run(&mut self, p: NodeId, like: Option<NodeId>, extra: &[PropEdit]) -> NodeId {
        let dom = &mut self.doc.dom;
        let r = dom.new_element("w:r", &[]);
        let src = like
            .and_then(|l| dom.child(l, "w:rPr"))
            .or_else(|| dom.child(p, "w:pPr").and_then(|pp| dom.child(pp, "w:rPr")));
        if let Some(src) = src {
            let c = dom.clone_node(src);
            // tracked-change marks of the mark/run don't carry over, nor a
            // note reference's look
            let note_ref = like.map_or(false, |l| dom.elements(l)
                .any(|k| dom.is(k, "w:footnoteReference") || dom.is(k, "w:endnoteReference")));
            for k in dom.children(c).to_vec() {
                if matches!(dom.name(k), "w:ins" | "w:del" | "w:rPrChange" | "w:moveFrom" | "w:moveTo")
                    || (note_ref && matches!(dom.name(k), "w:rStyle" | "w:vertAlign")) {
                    dom.detach(k);
                }
            }
            if dom.children(c).is_empty() && extra.is_empty() {
                // nothing left to say
            } else {
                dom.append(r, c);
            }
        }
        if !extra.is_empty() {
            let rpr = ensure_child_first(dom, r, "w:rPr");
            for e in extra {
                set_prop_child(dom, rpr, e, RPR_ORDER);
            }
        }
        r
    }

    /// Is this run the last of a field's result (the field's end follows)?
    fn ends_field_result(&self, run: NodeId) -> bool {
        let dom = &self.doc.dom;
        let Some(parent) = dom.parent(run) else { return false };
        let kids: Vec<NodeId> = dom.elements(parent).collect();
        let Some(i) = kids.iter().position(|&k| k == run) else { return false };
        kids[i + 1..].iter().find(|&&k| dom.is(k, "w:r")).map_or(false, |&next| {
            dom.elements(next).any(|c| dom.is(c, "w:fldChar") && dom.attr(c, "w:fldCharType") == Some("end"))
        })
    }

    fn rpr_key(&self, run: NodeId) -> String {
        let dom = &self.doc.dom;
        dom.child(run, "w:rPr").map(|n| dom.serialize_node(n)).unwrap_or_default()
    }

    /// Insert content at `off`: text, tabs ('\t') and line breaks ('\u{b}').
    fn insert_at(&mut self, p: NodeId, off: usize, text: &str) -> usize {
        let n = text.chars().count();
        if n == 0 {
            return 0;
        }
        let plain = !text.contains(['\t', '\u{b}', '\u{c}', '\u{e}']);
        // common case: typing into existing text
        let tracking = self.tracking();
        if plain && self.pending.is_empty() {
            let pieces = self.pieces(p);
            let target = pieces.iter().find(|(pc, s, e)| {
                matches!(pc.item, Item::Text(_)) && pc.change != "del" && *s < off && off <= *e
                    && pc.node.map(|n| self.doc.dom.is(n, "w:t")).unwrap_or(false)
                    // typing just after a field's result goes after the field
                    && (off < *e || !pc.run.map_or(false, |r| self.ends_field_result(r)))
                    // with tracking, only into this author's insertion
                    && (!tracking || pc.node.map_or(false, |n| self.in_my_ins(n)))
            });
            let target = target.or_else(|| {
                if off == 0 {
                    pieces.iter().find(|(pc, s, _)| {
                        *s == 0 && matches!(pc.item, Item::Text(_)) && pc.change != "del"
                            && pc.node.map(|n| self.doc.dom.is(n, "w:t")).unwrap_or(false)
                            && (!tracking || pc.node.map_or(false, |n| self.in_my_ins(n)))
                    })
                } else {
                    None
                }
            });
            if let Some((pc, s, _)) = target {
                let node = pc.node.unwrap();
                let cur = self.doc.dom.text(node);
                let k = off - s;
                let mut new: String = cur.chars().take(k).collect();
                new.push_str(text);
                new.extend(cur.chars().skip(k));
                self.set_t(node, &new);
                return n;
            }
        }
        let pending = std::mem::take(&mut self.pending);
        let (parent, idx, like) = self.split_runs_at(p, off);
        let (parent, idx) = if tracking { self.ins_slot(parent, idx) } else { (parent, idx) };
        let run = self.new_run(p, like, &pending);
        // content
        let mut buf = String::new();
        let flush = |ed: &mut Editor, buf: &mut String| {
            if !buf.is_empty() {
                let t = ed.doc.dom.new_element("w:t", &[]);
                ed.doc.dom.append(run, t);
                ed.set_t(t, buf);
                buf.clear();
            }
        };
        for c in text.chars() {
            match c {
                '\t' => {
                    flush(self, &mut buf);
                    let t = self.doc.dom.new_element("w:tab", &[]);
                    self.doc.dom.append(run, t);
                }
                '\u{b}' | '\u{c}' | '\u{e}' => {
                    flush(self, &mut buf);
                    let t = match c {
                        '\u{c}' => self.doc.dom.new_element("w:br", &[("w:type", "page")]),
                        '\u{e}' => self.doc.dom.new_element("w:br", &[("w:type", "column")]),
                        _ => self.doc.dom.new_element("w:br", &[]),
                    };
                    self.doc.dom.append(run, t);
                }
                _ => buf.push(c),
            }
        }
        flush(self, &mut buf);
        // join a neighbour with the same formatting
        let key = self.rpr_key(run);
        let dom = &self.doc.dom;
        let prev = if idx > 0 { dom.children(parent).get(idx - 1).copied() } else { None };
        let joinable = |d: &XmlDoc, r: NodeId| d.is(r, "w:r") && d.elements(r).all(|k| matches!(d.name(k), "w:rPr" | "w:t"));
        if plain {
            if let Some(pr) = prev {
                if joinable(dom, pr) && self.rpr_key(pr) == key {
                    if let Some(last_t) = self.doc.dom.elements(pr).filter(|&k| self.doc.dom.is(k, "w:t")).last() {
                        let mut s = self.doc.dom.text(last_t);
                        s.push_str(text);
                        self.set_t(last_t, &s);
                        return n;
                    }
                }
            }
        }
        self.doc.dom.insert(parent, idx, run);
        n
    }

    /// Remove positions [s, e) of one paragraph.
    fn delete_in_para(&mut self, p: NodeId, s: usize, e: usize) {
        if e <= s {
            return;
        }
        if self.tracking() {
            self.track_delete(p, s, e);
            return;
        }
        let pieces = self.pieces(p);
        let mut emptied_runs: Vec<NodeId> = Vec::new();
        // fields wholly inside the range go entirely, their codes too
        let mut whole: Vec<NodeId> = Vec::new();
        {
            let dom = &self.doc.dom;
            let mut stack: Vec<(usize, Vec<NodeId>)> = Vec::new();
            for (pc, ps, _pe) in &pieces {
                let Some(node) = pc.node else { continue };
                if dom.is(node, "w:fldChar") {
                    match dom.attr(node, "w:fldCharType") {
                        Some("begin") => stack.push((*ps, vec![node])),
                        Some("separate") => {
                            if let Some(t) = stack.last_mut() {
                                t.1.push(node);
                            }
                        }
                        Some("end") => {
                            if let Some((b, mut nodes)) = stack.pop() {
                                nodes.push(node);
                                if b >= s && *ps <= e && b != e && *ps != s {
                                    whole.extend(nodes);
                                }
                            }
                        }
                        _ => {}
                    }
                } else if dom.is(node, "w:instrText") {
                    if let Some(t) = stack.last_mut() {
                        t.1.push(node);
                    }
                }
            }
        }
        for pc_node in whole {
            if self.doc.dom.parent(pc_node).is_none() {
                continue;
            }
            if let Some(r) = self.run_of(pc_node) {
                emptied_runs.push(r);
            }
            self.doc.dom.detach(pc_node);
        }
        for (pc, ps, pe) in pieces.iter().rev() {
            let len = pc.item.len();
            if len == 0 || *pe <= s || *ps >= e {
                continue;
            }
            let Some(node) = pc.node else { continue };
            let a = s.max(*ps) - ps;
            let b = e.min(*pe) - ps;
            let dom = &self.doc.dom;
            let is_t = dom.is(node, "w:t") || dom.is(node, "w:delText");
            if let (Item::Text(_), true) = (&pc.item, is_t) {
                let cur = dom.text(node);
                let new: String = cur.chars().take(a).chain(cur.chars().skip(b)).collect();
                if new.is_empty() {
                    if let Some(r) = self.run_of(node) {
                        emptied_runs.push(r);
                    }
                    self.doc.dom.detach(node);
                } else {
                    self.set_t(node, &new);
                }
            } else if a == 0 && b == len {
                if let Some(r) = self.run_of(node) {
                    emptied_runs.push(r);
                }
                self.doc.dom.detach(node);
            }
        }
        // drop runs (and wrappers) left with nothing in them
        for r in emptied_runs {
            let dom = &self.doc.dom;
            if dom.parent(r).is_none() {
                continue;
            }
            let has_content = dom.elements(r).any(|k| dom.name(k) != "w:rPr");
            if !has_content {
                let mut node = r;
                loop {
                    let par = self.doc.dom.parent(node);
                    self.doc.dom.detach(node);
                    match par {
                        Some(par)
                            if matches!(self.doc.dom.name(par), "w:ins" | "w:del" | "w:hyperlink" | "w:smartTag")
                                && self.doc.dom.elements(par).next().is_none() =>
                        {
                            node = par
                        }
                        _ => break,
                    }
                }
            }
        }
    }

    /// Paragraphs from a to b in document order (inclusive).
    fn paras_between(&self, a: NodeId, b: NodeId) -> Vec<NodeId> {
        let ia = self.pidx(&a).copied().unwrap_or(0);
        let ib = self.pidx(&b).copied().unwrap_or(ia);
        let all: Vec<NodeId> = self.layout.paras[ia..=ib.max(ia)].iter().map(|p| p.node).collect();
        match self.cell_rect(a, b) {
            Some(cells) => all.into_iter().filter(|&p| self.cell_of(p).is_some_and(|(_, _, tc)| cells.contains(&tc))
                || self.ancestor_in(p, &cells)).collect(),
            None => all,
        }
    }

    /// A selection from one table cell to another (of the same table)
    /// takes in the rectangle of cells between them.
    fn cell_rect(&self, a: NodeId, b: NodeId) -> Option<HashSet<NodeId>> {
        let (sa, sb) = self.selection();
        if sa.para != a || sb.para != b || a == b {
            return None;
        }
        let (ta, _, ca) = self.cell_of(a)?;
        let (tb, _, cb) = self.cell_of(b)?;
        if ta != tb || ca == cb {
            return None;
        }
        let (_, _, cells) = self.selected_cells()?;
        Some(cells.into_iter().collect())
    }

    fn ancestor_in(&self, mut n: NodeId, set: &HashSet<NodeId>) -> bool {
        while let Some(p) = self.doc.dom.parent(n) {
            if set.contains(&p) {
                return true;
            }
            n = p;
        }
        false
    }

    /// Delete the selection (one transaction is open).
    fn delete_selection(&mut self) -> bool {
        let (a, b) = self.selection();
        if a == b {
            return false;
        }
        if a.para == b.para {
            self.delete_in_para(a.para, a.off, b.off);
            self.caret = a;
            self.anchor = a;
            return true;
        }
        if self.tracking() {
            self.track_delete_across(a, b);
            return true;
        }
        let dom = &self.doc.dom;
        let pa = dom.parent(a.para);
        let pb = dom.parent(b.para);
        if pa != pb {
            // across table cells: only the text of each paragraph goes
            for p in self.paras_between(a.para, b.para) {
                let len = self.para_len(p);
                let s = if p == a.para { a.off } else { 0 };
                let e = if p == b.para { b.off } else { len };
                self.delete_in_para(p, s, e);
            }
            self.caret = a;
            self.anchor = a;
            return true;
        }
        let parent = pa.unwrap();
        // blocks strictly between the two paragraphs
        let ia = dom.index_in_parent(a.para).unwrap();
        let ib = dom.index_in_parent(b.para).unwrap();
        let between: Vec<NodeId> = dom.children(parent)[ia + 1..ib].to_vec();
        let len_a = self.para_len(a.para);
        self.delete_in_para(b.para, 0, b.off);
        self.delete_in_para(a.para, a.off, len_a);
        for n in between {
            // keep section breaks' properties: a sectPr in a removed
            // paragraph goes with it, as in the original
            self.doc.dom.detach(n);
        }
        self.merge_into(a.para, b.para, a.off == 0);
        let keep = if a.off == 0 { b.para } else { a.para };
        self.caret = Pos { para: keep, off: a.off };
        self.anchor = self.caret;
        true
    }

    /// Join paragraph `b` onto `a`. With `keep_second` the result keeps b's
    /// paragraph formatting (a was emptied), else a's.
    fn merge_into(&mut self, a: NodeId, b: NodeId, keep_second: bool) {
        let dom = &mut self.doc.dom;
        if keep_second {
            // move a's leftovers (bookmarks...) to the start of b
            let kids: Vec<NodeId> = dom.children(a).iter().copied().filter(|&k| !dom.is(k, "w:pPr")).collect();
            let start = dom.child(b, "w:pPr").map(|_| 1).unwrap_or(0);
            for (i, k) in kids.into_iter().enumerate() {
                dom.detach(k);
                dom.insert(b, start + i, k);
            }
            dom.detach(a);
        } else {
            let kids: Vec<NodeId> = dom.children(b).iter().copied().filter(|&k| !dom.is(k, "w:pPr")).collect();
            for k in kids {
                dom.detach(k);
                dom.append(a, k);
            }
            // the section break that ended b now ends the joined paragraph
            let b_sect = dom.child(b, "w:pPr").and_then(|pp| dom.child(pp, "w:sectPr"));
            let a_ppr = dom.child(a, "w:pPr");
            if let Some(s) = a_ppr.and_then(|pp| dom.child(pp, "w:sectPr")) {
                dom.detach(s);
            }
            if let Some(s) = b_sect {
                dom.detach(s);
                let app = ensure_child_first(dom, a, "w:pPr");
                let rank = PPR_ORDER.iter().position(|x| *x == "w:sectPr").unwrap();
                let kids: Vec<NodeId> = dom.elements(app).collect();
                let mut idx = dom.children(app).len();
                for k in kids {
                    if PPR_ORDER.iter().position(|x| *x == dom.name(k)).unwrap_or(PPR_ORDER.len()) > rank {
                        idx = dom.index_in_parent(k).unwrap();
                        break;
                    }
                }
                dom.insert(app, idx, s);
            }
            dom.detach(b);
        }
    }

    /// Split paragraph `p` at `off`; returns the paragraph holding the text
    /// after the split (the original node).
    fn split_para(&mut self, p: NodeId, off: usize) -> NodeId {
        let len = self.para_len(p);
        let (mut parent, mut idx, _) = if off >= len {
            let dom = &self.doc.dom;
            (p, dom.children(p).len(), None)
        } else {
            self.split_runs_at(p, off)
        };
        // split the wrappers between the boundary and the paragraph
        while parent != p {
            let dom = &self.doc.dom;
            let child = dom.children(parent).get(idx).copied();
            let up = dom.parent(parent).unwrap();
            match child {
                Some(c) => {
                    self.split_element_before(parent, c);
                    let dom = &self.doc.dom;
                    idx = dom.index_in_parent(parent).unwrap();
                }
                None => {
                    idx = dom.index_in_parent(parent).unwrap() + 1;
                }
            }
            parent = up;
        }
        let dom = &mut self.doc.dom;
        let first = dom.new_element("w:p", &[]);
        if let Some(ppr) = dom.child(p, "w:pPr") {
            let c = dom.clone_node(ppr);
            if let Some(s) = dom.child(c, "w:sectPr") {
                dom.detach(s);
            }
            dom.append(first, c);
        }
        let kids: Vec<NodeId> = dom.children(p).to_vec();
        for (i, k) in kids.into_iter().enumerate() {
            if i >= idx {
                break;
            }
            if dom.is(k, "w:pPr") {
                continue;
            }
            dom.detach(k);
            dom.append(first, k);
        }
        let pp = dom.parent(p).unwrap();
        let pi = dom.index_in_parent(p).unwrap();
        dom.insert(pp, pi, first);
        if self.tracking() {
            // the new paragraph mark is an insertion
            for k in ["w:ins", "w:del"] {
                if let Some(m) = self.mark_change(first, k) {
                    self.doc.dom.detach(m);
                }
            }
            self.mark_para(first, "w:ins");
        }
        // Enter at the end: the new paragraph takes the style's "next"
        if off >= len && len > 0 {
            let (props, _) = self.doc.para_props(p);
            let cur = props.style.clone();
            let next = cur.as_deref().and_then(|c| self.doc.styles.styles.get(c)).and_then(|s| s.next.clone());
            if let (Some(n), Some(c)) = (next, cur) {
                if n != c {
                    let dom = &mut self.doc.dom;
                    let ppr = ensure_child_first(dom, p, "w:pPr");
                    for k in dom.children(ppr).to_vec() {
                        if !matches!(dom.name(k), "w:sectPr" | "w:rPr") {
                            dom.detach(k);
                        }
                    }
                    let default = self.doc.styles.default_para.clone();
                    if Some(&n) != default.as_ref() {
                        set_prop_child(&mut self.doc.dom, ppr, &PropEdit::set("w:pStyle", &[("w:val", &n)]), PPR_ORDER);
                    }
                }
            }
        }
        p
    }

    // ---------------------------------------------------------- commands
    /// Type text at the caret (replacing the selection). '\n' starts a new
    /// paragraph, '\t' a tab, '\u{b}' a line break.
    pub fn type_text(&mut self, text: &str) {
        self.extra_sel.clear();
        if text.is_empty() {
            return;
        }
        let single = text.chars().count() == 1 && !text.contains('\n');
        if !single || self.has_selection() {
            self.typing = false;
        }
        if text == "\n" && !self.has_selection() && self.list_kind(self.caret.para).is_some()
            && self.para_len(self.caret.para) == 0 {
            // Enter on an empty list item ends the list
            self.begin();
            let p = self.caret.para;
            self.set_num_pr(p, None);
            let lp = self.list_paragraph_style();
            if self.doc.para_direct(p).style == lp && lp.is_some() {
                self.set_para_style_id(p, None);
            }
            self.commit("Numbering", false);
            return;
        }
        if self.content_locked_here() {
            return;
        }
        if self.type_into_placeholder(text) {
            self.typing = false;
            return;
        }
        self.begin();
        self.delete_selection();
        let mut first = true;
        for part in text.split('\n') {
            if !first {
                let p = self.split_para(self.caret.para, self.caret.off);
                self.doc.scan();
                self.caret = Pos { para: p, off: 0 };
            }
            first = false;
            let part = part.replace('\r', "");
            let n = self.insert_at(self.caret.para, self.caret.off, &part);
            self.caret.off += n;
        }
        self.anchor = self.caret;
        self.goal_x = None;
        let word_end = text.chars().any(|c| c.is_whitespace() || c.is_ascii_punctuation());
        // a space or punctuation ends the word: it undoes with it, and the next word is a new step
        self.commit("Typing", single);
        if word_end {
            self.typing = false;
        }
    }

    /// Backspace / Delete.
    pub fn delete(&mut self, forward: bool, word: bool) {
        self.extra_sel.clear();
        if !forward && self.at_list_item_start() {
            self.begin();
            let p = self.caret.para;
            self.remove_number_keep_indent(p);
            self.commit("Numbering", false);
            return;
        }
        if self.content_locked_here() {
            return;
        }
        self.begin();
        let had_sel = self.has_selection();
        if !self.has_selection() {
            let to = match (forward, word) {
                (true, false) => self.next_pos(self.caret),
                (true, true) => self.next_word(self.caret),
                (false, false) => self.prev_pos(self.caret),
                (false, true) => self.prev_word(self.caret),
            };
            self.anchor = to;
        }
        let (sa, sb) = self.selection();
        self.delete_selection();
        if self.tracking() && !self.hides_deletions() {
            // the deleted text stays in view: step over it
            let to = if forward || had_sel { sb } else { sa };
            if self.doc.dom.parent(to.para).is_some() {
                self.caret = to;
                self.anchor = to;
            }
        }
        let p = self.caret.para;
        if self.doc.dom.parent(p).is_some() {
            self.refill_empty_controls(p);
        }
        self.commit(if forward { "Delete" } else { "Backspace" }, false);
    }

    pub fn new_paragraph(&mut self) {
        self.type_text("\n");
    }

    pub fn selected_text(&self) -> String {
        let (a, b) = self.selection();
        let mut out = String::new();
        for p in self.paras_between(a.para, b.para) {
            let Some(pl) = self.para_layout(p) else { continue };
            let s = if p == a.para { a.off } else { 0 };
            let e = if p == b.para { b.off } else { pl.text_len };
            for (pos, c) in Self::para_chars(pl) {
                if pos >= s && pos < e {
                    out.push(match c {
                        '\u{fffc}' => continue,
                        '\n' => '\u{b}',
                        c => c,
                    });
                }
            }
            if p != b.para {
                out.push('\n');
            }
        }
        out.replace('\u{b}', "\n")
    }

    /// Runs touched by [s, e) of paragraph p, after splitting at both ends.
    fn runs_in(&mut self, p: NodeId, s: usize, e: usize) -> Vec<NodeId> {
        if e > s {
            let len = self.para_len(p);
            if e < len {
                self.split_runs_at(p, e);
            }
            if s > 0 {
                self.split_runs_at(p, s);
            }
        }
        let mut runs = Vec::new();
        for (pc, ps, pe) in self.pieces(p) {
            if pc.item.len() == 0 || pe <= s || ps >= e {
                continue;
            }
            if let Some(r) = pc.run {
                if !runs.contains(&r) {
                    runs.push(r);
                }
            }
        }
        runs
    }

    /// Apply run formatting to the selection (or, with none, to the word at
    /// the caret, or to what is typed next).
    pub fn format_runs(&mut self, edits: &[PropEdit], name: &str) {
        let ed2 = edits.to_vec();
        if self.each_range(name, &mut |e: &mut Self| e.format_runs(&ed2, name)) {
            return;
        }
        let (mut a, mut b) = self.selection();
        if a == b {
            let (ws, we) = self.word_at(a);
            if ws.off < a.off && a.off < we.off {
                a = ws;
                b = we;
                // without the trailing space
                if let Some(pl) = self.para_layout(b.para) {
                    let cs = Self::para_chars(pl);
                    let mut e = b.off;
                    while e > a.off && cs.iter().any(|(pos, c)| *pos == e - 1 && *c == ' ') {
                        e -= 1;
                    }
                    b.off = e;
                }
            } else {
                for e in edits {
                    self.pending.retain(|x| x.name != e.name);
                    self.pending.push(e.clone());
                }
                return;
            }
        }
        self.begin();
        let paras = self.paras_between(a.para, b.para);
        for p in &paras {
            let len = self.para_len(*p);
            let s = if *p == a.para { a.off } else { 0 };
            let e = if *p == b.para { b.off } else { len };
            let runs = self.runs_in(*p, s, e);
            let tracking = self.tracking();
            for r in runs {
                if tracking {
                    self.track_rpr(r);
                }
                let dom = &mut self.doc.dom;
                let rpr = ensure_child_first(dom, r, "w:rPr");
                for ed in edits {
                    set_prop_child(dom, rpr, ed, RPR_ORDER);
                }
            }
            // the paragraph mark, when the selection runs past it
            if *p != b.para || (s == 0 && e >= len) {
                let dom = &mut self.doc.dom;
                let ppr = ensure_child_first(dom, *p, "w:pPr");
                let rank = PPR_ORDER.iter().position(|x| *x == "w:rPr").unwrap();
                let rpr = match dom.child(ppr, "w:rPr") {
                    Some(r) => r,
                    None => {
                        let n = dom.new_element("w:rPr", &[]);
                        let kids: Vec<NodeId> = dom.elements(ppr).collect();
                        let mut idx = dom.children(ppr).len();
                        for k in kids {
                            if PPR_ORDER.iter().position(|x| *x == dom.name(k)).unwrap_or(PPR_ORDER.len()) > rank {
                                idx = dom.index_in_parent(k).unwrap();
                                break;
                            }
                        }
                        dom.insert(ppr, idx, n);
                        n
                    }
                };
                for ed in edits {
                    set_prop_child(dom, rpr, ed, RPR_ORDER);
                }
            }
        }
        self.commit(name, false);
    }

    /// Apply paragraph formatting to every paragraph in the selection.
    pub fn format_paras(&mut self, edits: &[PropEdit], name: &str) {
        let ed2 = edits.to_vec();
        if self.each_range(name, &mut |e: &mut Self| e.format_paras(&ed2, name)) {
            return;
        }
        let (a, b) = self.selection();
        self.begin();
        for p in self.paras_between(a.para, b.para) {
            self.track_ppr(p);
            let dom = &mut self.doc.dom;
            let ppr = ensure_child_first(dom, p, "w:pPr");
            for ed in edits {
                set_prop_child(dom, ppr, ed, PPR_ORDER);
            }
        }
        self.commit(name, false);
    }

    /// Set attributes on a paragraph property element, keeping its other
    /// attributes (w:spacing w:after=..., w:ind w:left=...).
    pub fn format_paras_attrs(&mut self, name: &str, attrs: &[(&str, Option<&str>)], label: &str) {
        let owned: Vec<(String, Option<String>)> = attrs.iter().map(|(k, v)| (k.to_string(), v.map(|x| x.to_string()))).collect();
        if self.each_range(label, &mut |e: &mut Self| {
            let a: Vec<(&str, Option<&str>)> = owned.iter().map(|(k, v)| (k.as_str(), v.as_deref())).collect();
            e.format_paras_attrs(name, &a, label)
        }) {
            return;
        }
        let (a, b) = self.selection();
        self.begin();
        for p in self.paras_between(a.para, b.para) {
            self.track_ppr(p);
            let dom = &mut self.doc.dom;
            let ppr = ensure_child_first(dom, p, "w:pPr");
            let el = match dom.child(ppr, name) {
                Some(n) => n,
                None => {
                    set_prop_child(dom, ppr, &PropEdit::set(name, &[]), PPR_ORDER);
                    dom.child(ppr, name).unwrap()
                }
            };
            for (k, v) in attrs {
                match v {
                    Some(v) => dom.set_attr(el, k, v),
                    None => {
                        dom.remove_attr(el, k);
                    }
                }
            }
        }
        self.commit(label, false);
    }

    /// Replace the tab stops of the selected paragraphs: (position twips,
    /// kind, leader). Stops the style sets that aren't kept are cleared.
    pub fn set_tabs(&mut self, tabs: &[(i32, String, String)]) {
        let (a, b) = self.selection();
        self.begin();
        for p in self.paras_between(a.para, b.para) {
            let direct = self.doc.para_direct(p);
            let (style_pp, _) = self.doc.styles.para_style(direct.style.as_deref());
            let dom = &mut self.doc.dom;
            let ppr = ensure_child_first(dom, p, "w:pPr");
            if let Some(old) = dom.child(ppr, "w:tabs") {
                dom.detach(old);
            }
            let mut all: Vec<(i32, String, String)> = tabs.to_vec();
            for t in style_pp.tab_stops() {
                if !tabs.iter().any(|x| x.0 == t.pos) {
                    all.push((t.pos, "clear".into(), "none".into()));
                }
            }
            all.sort_by_key(|t| t.0);
            if all.is_empty() {
                continue;
            }
            let el = dom.new_element("w:tabs", &[]);
            for (pos, kind, leader) in &all {
                let ps = pos.to_string();
                let mut at: Vec<(&str, &str)> = vec![("w:val", kind.as_str())];
                if leader != "none" && !leader.is_empty() {
                    at.push(("w:leader", leader.as_str()));
                }
                at.push(("w:pos", ps.as_str()));
                let t = dom.new_element("w:tab", &at);
                dom.append(el, t);
            }
            let rank = PPR_ORDER.iter().position(|x| *x == "w:tabs").unwrap();
            let kids: Vec<NodeId> = dom.elements(ppr).collect();
            let mut idx = dom.children(ppr).len();
            for k in kids {
                if PPR_ORDER.iter().position(|x| *x == dom.name(k)).unwrap_or(PPR_ORDER.len()) > rank {
                    idx = dom.index_in_parent(k).unwrap();
                    break;
                }
            }
            dom.insert(ppr, idx, el);
        }
        self.commit("Tabs", false);
    }

    /// The resolved run formatting at the caret (or the selection start):
    /// what the ribbon shows.
    pub fn current_run_props(&self) -> crate::props::RunProps {
        let (a, b) = self.selection();
        let p = a.para;
        let (_, base) = self.doc.para_props(p);
        let pieces = self.pieces(p);
        let off = if a == b { a.off } else { a.off + 1 };
        let pc = pieces
            .iter()
            .filter(|(pc, _, _)| pc.item.len() > 0)
            .find(|(_, s, e)| *s < off && off <= *e)
            .or_else(|| pieces.iter().find(|(pc, s, _)| pc.item.len() > 0 && *s >= a.off));
        let mut r = match pc {
            Some((pc, _, _)) => pc.rpr.clone(),
            None => self.doc.mark_props(p, &base),
        };
        // pending formatting shows too
        for e in &self.pending {
            let a = |k: &str| e.attrs.as_ref().and_then(|v| v.iter().find(|(n, _)| n == k).map(|(_, x)| x.clone()));
            let on = e.attrs.as_ref().map(|_| !matches!(a("w:val").as_deref(), Some("0") | Some("false")));
            match e.name.as_str() {
                "w:b" => r.bold = on,
                "w:i" => r.italic = on,
                "w:strike" => r.strike = on,
                "w:caps" => r.caps = on,
                "w:smallCaps" => r.small_caps = on,
                "w:rFonts" => {
                    if let Some(f) = a("w:ascii") {
                        r.font_ascii = Some(f.clone());
                        r.font_hansi = Some(f);
                        r.theme_ascii = None;
                        r.theme_hansi = None;
                    }
                }
                "w:sz" => r.size = a("w:val").and_then(|v| v.parse().ok()),
                "w:u" => r.underline = a("w:val"),
                "w:highlight" => r.highlight = a("w:val"),
                "w:vertAlign" => r.vert_align = a("w:val"),
                "w:color" => {
                    r.color = a("w:val").map(|v| match crate::props::color_attr(&v) {
                        Some(c) => crate::props::ColorVal::Rgb(c),
                        None => crate::props::ColorVal::Auto,
                    })
                }
                _ => {}
            }
        }
        r
    }

    pub fn current_para_props(&self) -> crate::props::ParaProps {
        self.doc.para_props(self.caret.para).0
    }

    /// Is a toggle property on across the whole selection?
    pub fn toggle_state(&self, which: &str) -> bool {
        let (a, b) = self.selection();
        if a == b {
            let r = self.current_run_props();
            return match which {
                "w:b" => r.bold.unwrap_or(false),
                "w:i" => r.italic.unwrap_or(false),
                "w:strike" => r.strike.unwrap_or(false),
                "w:caps" => r.caps.unwrap_or(false),
                "w:smallCaps" => r.small_caps.unwrap_or(false),
                _ => false,
            };
        }
        for p in self.paras_between(a.para, b.para) {
            let s = if p == a.para { a.off } else { 0 };
            let e = if p == b.para { b.off } else { usize::MAX };
            for (pc, ps, pe) in self.pieces(p) {
                if pc.item.len() == 0 || pe <= s || ps >= e {
                    continue;
                }
                let v = match which {
                    "w:b" => pc.rpr.bold,
                    "w:i" => pc.rpr.italic,
                    "w:strike" => pc.rpr.strike,
                    "w:caps" => pc.rpr.caps,
                    "w:smallCaps" => pc.rpr.small_caps,
                    _ => None,
                };
                if !v.unwrap_or(false) {
                    return false;
                }
            }
        }
        true
    }

    /// Bold/italic/... on or off for the selection, as the original's
    /// buttons do (on unless all of it already is).
    pub fn toggle(&mut self, which: &str, label: &str) {
        let on = !self.toggle_state(which);
        let cs = match which {
            "w:b" => Some("w:bCs"),
            "w:i" => Some("w:iCs"),
            _ => None,
        };
        let mk = |n: &str| if on { PropEdit::set(n, &[]) } else { PropEdit::set(n, &[("w:val", "0")]) };
        let mut edits = vec![mk(which)];
        if let Some(c) = cs {
            edits.push(mk(c));
        }
        self.format_runs(&edits, label);
        self.tidy_toggles(which, cs);
    }

    /// An explicit "off" is only kept where a style would turn it on.
    fn tidy_toggles(&mut self, which: &str, cs: Option<&str>) {
        // no-op for now: w:val="0" is always valid and what the original
        // writes when a style is involved; plain runs keep it harmlessly.
        let _ = (which, cs);
    }

    // ----------------------------------------------------------- tables
    /// The table, row and cell a paragraph is in (innermost).
    pub fn cell_of(&self, p: NodeId) -> Option<(NodeId, NodeId, NodeId)> {
        let dom = &self.doc.dom;
        let mut n = p;
        let mut tc = None;
        let mut tr = None;
        loop {
            let par = dom.parent(n)?;
            match dom.name(par) {
                "w:tc" if tc.is_none() => tc = Some(par),
                "w:tr" if tr.is_none() && tc.is_some() => tr = Some(par),
                "w:tbl" if tr.is_some() => return Some((par, tr?, tc?)),
                "w:body" => return None,
                _ => {}
            }
            n = par;
        }
    }

    fn first_para_in(&self, n: NodeId) -> Option<NodeId> {
        let dom = &self.doc.dom;
        for c in dom.elements(n) {
            if dom.is(c, "w:p") {
                return Some(c);
            }
            if let Some(p) = self.first_para_in(c) {
                return Some(p);
            }
        }
        None
    }

    fn new_cell(&mut self, width_tw: i32) -> NodeId {
        let dom = &mut self.doc.dom;
        let tc = dom.new_element("w:tc", &[]);
        let pr = dom.new_element("w:tcPr", &[]);
        let w = dom.new_element("w:tcW", &[("w:w", &width_tw.to_string()), ("w:type", "dxa")]);
        dom.append(pr, w);
        dom.append(tc, pr);
        let p = dom.new_element("w:p", &[]);
        dom.append(tc, p);
        tc
    }

    /// Insert a table of rows × cols at the caret (the paragraph splits if
    /// the caret is inside its text).
    pub fn insert_table(&mut self, rows: usize, cols: usize) {
        let rows = rows.clamp(1, 63);
        let cols = cols.clamp(1, 63);
        self.begin();
        self.delete_selection();
        let mut p = self.caret.para;
        if self.caret.off > 0 {
            p = self.split_para(p, self.caret.off);
            self.doc.scan();
        }
        // the width of the text column the paragraph is in
        let sec = self.doc.blocks.iter().find(|b| b.node == p).map(|b| b.section).unwrap_or(0);
        let width = self.doc.sections.get(sec).map(|s| s.text_width()).unwrap_or(9360);
        let colw = (width / cols as i32).max(100);
        let has_grid = self.doc.styles.styles.contains_key("TableGrid");
        let dom = &mut self.doc.dom;
        let tbl = dom.new_element("w:tbl", &[]);
        let pr = dom.new_element("w:tblPr", &[]);
        if has_grid {
            let st = dom.new_element("w:tblStyle", &[("w:val", "TableGrid")]);
            dom.append(pr, st);
        }
        let tw_ = dom.new_element("w:tblW", &[("w:w", "0"), ("w:type", "auto")]);
        dom.append(pr, tw_);
        if !has_grid {
            let b = dom.new_element("w:tblBorders", &[]);
            for side in ["w:top", "w:left", "w:bottom", "w:right", "w:insideH", "w:insideV"] {
                let e = dom.new_element(side, &[("w:val", "single"), ("w:sz", "4"), ("w:space", "0"), ("w:color", "auto")]);
                dom.append(b, e);
            }
            dom.append(pr, b);
        }
        let look = dom.new_element("w:tblLook", &[("w:val", "04A0"), ("w:firstRow", "1"), ("w:lastRow", "0"),
            ("w:firstColumn", "1"), ("w:lastColumn", "0"), ("w:noHBand", "0"), ("w:noVBand", "1")]);
        dom.append(pr, look);
        dom.append(tbl, pr);
        let grid = dom.new_element("w:tblGrid", &[]);
        for _ in 0..cols {
            let g = dom.new_element("w:gridCol", &[("w:w", &colw.to_string())]);
            dom.append(grid, g);
        }
        dom.append(tbl, grid);
        for _ in 0..rows {
            let tr = self.doc.dom.new_element("w:tr", &[]);
            for _ in 0..cols {
                let tc = self.new_cell(colw);
                self.doc.dom.append(tr, tc);
            }
            self.doc.dom.append(tbl, tr);
        }
        let dom = &mut self.doc.dom;
        let parent = dom.parent(p).unwrap();
        let idx = dom.index_in_parent(p).unwrap();
        dom.insert(parent, idx, tbl);
        let first = self.first_para_in(tbl).unwrap();
        self.caret = Pos { para: first, off: 0 };
        self.anchor = self.caret;
        self.commit("Insert Table", false);
    }

    /// The cells (tc) of a row with their grid column ranges.
    fn row_cells(&self, tr: NodeId) -> Vec<(NodeId, usize, usize)> {
        let dom = &self.doc.dom;
        let mut g = dom
            .child(tr, "w:trPr")
            .and_then(|t| dom.child(t, "w:gridBefore"))
            .and_then(|n| crate::props::int_attr(dom, n, "w:val"))
            .unwrap_or(0)
            .max(0) as usize;
        let mut out = Vec::new();
        for tc in dom.children_named(tr, "w:tc") {
            let span = dom
                .child(tc, "w:tcPr")
                .and_then(|p| dom.child(p, "w:gridSpan"))
                .and_then(|n| crate::props::int_attr(dom, n, "w:val"))
                .unwrap_or(1)
                .max(1) as usize;
            out.push((tc, g, g + span));
            g += span;
        }
        out
    }

    /// Rows of the selection (in one table).
    fn selected_rows(&self) -> Option<(NodeId, Vec<NodeId>)> {
        let (a, b) = self.selection();
        let (ta, ra, _) = self.cell_of(a.para)?;
        let (tb, rb, _) = self.cell_of(b.para).unwrap_or((ta, ra, ra));
        let dom = &self.doc.dom;
        let rows: Vec<NodeId> = dom.children_named(ta, "w:tr").collect();
        let ia = rows.iter().position(|&r| r == ra)?;
        let ib = if tb == ta { rows.iter().position(|&r| r == rb).unwrap_or(ia) } else { ia };
        Some((ta, rows[ia.min(ib)..=ia.max(ib)].to_vec()))
    }

    /// Grid columns of the selection.
    fn selected_cols(&self) -> Option<(NodeId, usize, usize)> {
        let (a, b) = self.selection();
        let (ta, ra, ca) = self.cell_of(a.para)?;
        let (_, rb, cb) = self.cell_of(b.para).unwrap_or((ta, ra, ca));
        let ga = self.row_cells(ra).into_iter().find(|c| c.0 == ca)?;
        let gb = self.row_cells(rb).into_iter().find(|c| c.0 == cb).unwrap_or(ga);
        Some((ta, ga.1.min(gb.1), ga.2.max(gb.2)))
    }

    pub fn insert_rows(&mut self, below: bool) -> bool {
        let Some((_tbl, rows)) = self.selected_rows() else { return false };
        self.begin();
        let n = rows.len();
        let src = if below { *rows.last().unwrap() } else { rows[0] };
        let mut new_first = None;
        for _ in 0..n {
            let dom = &mut self.doc.dom;
            let tr = dom.new_element("w:tr", &[]);
            if let Some(trpr) = dom.child(src, "w:trPr") {
                let c = dom.clone_node(trpr);
                dom.append(tr, c);
            }
            let cells: Vec<NodeId> = dom.children_named(src, "w:tc").collect();
            for tc in cells {
                let dom = &mut self.doc.dom;
                let ntc = dom.new_element("w:tc", &[]);
                if let Some(pr) = dom.child(tc, "w:tcPr") {
                    let c = dom.clone_node(pr);
                    // a vertically merged cell continues into the new row
                    if let Some(v) = dom.child(c, "w:vMerge") {
                        dom.detach(v);
                        if !below || dom.attr(v, "w:val") != Some("restart") {
                            let nv = dom.new_element("w:vMerge", &[]);
                            dom.append(c, nv);
                        }
                    }
                    dom.append(ntc, c);
                }
                let np = dom.new_element("w:p", &[]);
                // keep the paragraph formatting of the first paragraph
                if let Some(fp) = dom.child(tc, "w:p").and_then(|p| dom.child(p, "w:pPr")) {
                    let c = dom.clone_node(fp);
                    if let Some(sp) = dom.child(c, "w:sectPr") {
                        dom.detach(sp);
                    }
                    dom.append(np, c);
                }
                dom.append(ntc, np);
                dom.append(tr, ntc);
            }
            if let Some(pr) = self.doc.dom.child(tr, "w:trPr") {
                for k in self.doc.dom.elements(pr).collect::<Vec<_>>() {
                    if matches!(self.doc.dom.name(k), "w:ins" | "w:del" | "w:trPrChange") {
                        self.doc.dom.detach(k);
                    }
                }
            }
            if self.tracking() {
                self.mark_row(tr, "w:ins");
            }
            let dom = &mut self.doc.dom;
            let parent = dom.parent(src).unwrap();
            let idx = dom.index_in_parent(src).unwrap() + if below { 1 } else { 0 };
            dom.insert(parent, idx, tr);
            if new_first.is_none() {
                new_first = Some(tr);
            }
        }
        if let Some(tr) = new_first {
            if let Some(p) = self.first_para_in(tr) {
                self.caret = Pos { para: p, off: 0 };
                self.anchor = self.caret;
            }
        }
        self.commit("Insert Rows", false);
        true
    }

    pub fn delete_rows(&mut self) -> bool {
        let Some((tbl, rows)) = self.selected_rows() else { return false };
        if self.tracking() {
            self.begin();
            for r in &rows {
                self.track_delete_row(*r);
            }
            self.commit("Delete Rows", false);
            return true;
        }
        let total = self.doc.dom.children_named(tbl, "w:tr").count();
        if rows.len() >= total {
            return self.delete_table();
        }
        self.begin();
        let dom = &self.doc.dom;
        let all: Vec<NodeId> = dom.children_named(tbl, "w:tr").collect();
        let last_idx = all.iter().position(|r| r == rows.last().unwrap()).unwrap_or(0);
        let next = all.get(last_idx + 1).copied().or_else(|| {
            let first_idx = all.iter().position(|r| *r == rows[0]).unwrap_or(0);
            first_idx.checked_sub(1).map(|i| all[i])
        });
        for r in &rows {
            self.doc.dom.detach(*r);
        }
        if let Some(n) = next.and_then(|r| self.first_para_in(r)) {
            self.caret = Pos { para: n, off: 0 };
            self.anchor = self.caret;
        }
        self.commit("Delete Rows", false);
        true
    }

    pub fn delete_table(&mut self) -> bool {
        let (a, _) = self.selection();
        let Some((tbl, _, _)) = self.cell_of(a.para) else { return false };
        self.begin();
        if self.tracking() {
            for r in self.doc.dom.children_named(tbl, "w:tr").collect::<Vec<_>>() {
                self.track_delete_row(r);
            }
            self.commit("Delete Table", false);
            return true;
        }
        let dom = &self.doc.dom;
        let parent = dom.parent(tbl).unwrap();
        let idx = dom.index_in_parent(tbl).unwrap();
        let after = dom.children(parent).get(idx + 1).copied();
        self.doc.dom.detach(tbl);
        let target = after.and_then(|n| if self.doc.dom.is(n, "w:p") { Some(n) } else { self.first_para_in(n) });
        if let Some(p) = target {
            self.caret = Pos { para: p, off: 0 };
            self.anchor = self.caret;
        }
        self.commit("Delete Table", false);
        true
    }

    /// Insert columns left or right of the selected ones (as many as are
    /// selected); the new columns take the width of their neighbour.
    pub fn insert_cols(&mut self, right: bool) -> bool {
        let Some((tbl, g0, g1)) = self.selected_cols() else { return false };
        let n = g1 - g0;
        let at = if right { g1 } else { g0 };
        let old_total: i32 = self.doc.dom.child(tbl, "w:tblGrid")
            .map(|g| self.doc.dom.children_named(g, "w:gridCol").map(|c| crate::props::int_attr(&self.doc.dom, c, "w:w").unwrap_or(0)).sum())
            .unwrap_or(0);
        self.begin();
        // the grid
        let dom = &mut self.doc.dom;
        if let Some(grid) = dom.child(tbl, "w:tblGrid") {
            let cols: Vec<NodeId> = dom.children_named(grid, "w:gridCol").collect();
            let src = cols.get(if right { g1.saturating_sub(1) } else { g0 }).copied();
            let w = src.and_then(|c| dom.attr(c, "w:w")).unwrap_or("1440").to_string();
            for k in 0..n {
                let gc = dom.new_element("w:gridCol", &[("w:w", &w)]);
                let idx = match cols.get(at) {
                    Some(&c) => dom.index_in_parent(c).unwrap() + k,
                    None => dom.children(grid).len(),
                };
                dom.insert(grid, idx, gc);
            }
        }
        let rows: Vec<NodeId> = self.doc.dom.children_named(tbl, "w:tr").collect();
        for tr in rows {
            let cells = self.row_cells(tr);
            // the cell before which the new ones go
            let before = cells.iter().find(|c| c.1 >= at).map(|c| c.0);
            let like = cells.iter().find(|c| c.1 < at.max(1) && c.2 >= at.min(c.2)).map(|c| c.0)
                .or_else(|| cells.first().map(|c| c.0));
            let width = like
                .and_then(|tc| self.doc.dom.child(tc, "w:tcPr"))
                .and_then(|p| self.doc.dom.child(p, "w:tcW"))
                .and_then(|w| crate::props::int_attr(&self.doc.dom, w, "w:w"))
                .unwrap_or(1440);
            for _ in 0..n {
                let tc = self.new_cell(width);
                let dom = &mut self.doc.dom;
                match before {
                    Some(b) => {
                        let idx = dom.index_in_parent(b).unwrap();
                        dom.insert(tr, idx, tc);
                    }
                    None => dom.append(tr, tc),
                }
            }
        }
        // the table keeps its width: every column gives up a share
        self.fit_grid(tbl, old_total);
        self.commit("Insert Columns", false);
        true
    }

    /// Scale a table's grid and cell widths to `total` twips.
    fn fit_grid(&mut self, tbl: NodeId, total: i32) {
        if total <= 0 {
            return;
        }
        let dom = &self.doc.dom;
        let Some(grid) = dom.child(tbl, "w:tblGrid") else { return };
        let cols: Vec<NodeId> = dom.children_named(grid, "w:gridCol").collect();
        let widths: Vec<i32> = cols.iter().map(|c| crate::props::int_attr(dom, *c, "w:w").unwrap_or(0)).collect();
        let now: i32 = widths.iter().sum();
        if now <= total || now == 0 {
            return;
        }
        let k = total as f64 / now as f64;
        for (c, w) in cols.iter().zip(&widths) {
            let nw = ((*w as f64) * k).round() as i32;
            self.doc.dom.set_attr(*c, "w:w", &nw.to_string());
        }
        let rows: Vec<NodeId> = self.doc.dom.children_named(tbl, "w:tr").collect();
        for tr in rows {
            let tcs: Vec<NodeId> = self.doc.dom.children_named(tr, "w:tc").collect();
            for tc in tcs {
                let dom = &self.doc.dom;
                if let Some(w) = dom.child(tc, "w:tcPr").and_then(|p| dom.child(p, "w:tcW")) {
                    if dom.attr(w, "w:type").unwrap_or("dxa") == "dxa" {
                        let v = crate::props::int_attr(dom, w, "w:w").unwrap_or(0);
                        let nv = ((v as f64) * k).round() as i32;
                        self.doc.dom.set_attr(w, "w:w", &nv.to_string());
                    }
                }
            }
        }
    }

    pub fn delete_cols(&mut self) -> bool {
        let Some((tbl, g0, g1)) = self.selected_cols() else { return false };
        let ncols = self.doc.dom.child(tbl, "w:tblGrid").map(|g| self.doc.dom.children_named(g, "w:gridCol").count()).unwrap_or(0);
        if g0 == 0 && g1 >= ncols {
            return self.delete_table();
        }
        self.begin();
        let rows: Vec<NodeId> = self.doc.dom.children_named(tbl, "w:tr").collect();
        let mut target = None;
        for tr in rows {
            for (tc, a, b) in self.row_cells(tr) {
                if a >= g0 && b <= g1 {
                    self.doc.dom.detach(tc);
                } else if a < g1 && b > g0 {
                    // a wider cell loses the deleted columns from its span
                    let keep = (b - a) - (b.min(g1) - a.max(g0));
                    let dom = &mut self.doc.dom;
                    let pr = ensure_child_first(dom, tc, "w:tcPr");
                    if keep <= 1 {
                        if let Some(gs) = dom.child(pr, "w:gridSpan") {
                            dom.detach(gs);
                        }
                    } else {
                        let e = PropEdit::set("w:gridSpan", &[("w:val", &keep.to_string())]);
                        set_prop_child(dom, pr, &e, TCPR_ORDER);
                    }
                } else if target.is_none() && a >= g1 {
                    target = Some(tc);
                }
            }
        }
        let dom = &mut self.doc.dom;
        if let Some(grid) = dom.child(tbl, "w:tblGrid") {
            let cols: Vec<NodeId> = dom.children_named(grid, "w:gridCol").collect();
            for (i, c) in cols.into_iter().enumerate() {
                if i >= g0 && i < g1 {
                    dom.detach(c);
                }
            }
        }
        if let Some(p) = target.and_then(|tc| self.first_para_in(tc)) {
            self.caret = Pos { para: p, off: 0 };
            self.anchor = self.caret;
        }
        self.commit("Delete Columns", false);
        true
    }

    /// Merge the selected cells of one row (their text joins in the first).
    pub fn merge_cells(&mut self) -> bool {
        let (a, b) = self.selection();
        let Some((ta, ra, ca)) = self.cell_of(a.para) else { return false };
        let Some((tb, rb, cb)) = self.cell_of(b.para) else { return false };
        if ta != tb || ca == cb {
            return false;
        }
        self.begin();
        if ra == rb {
            let cells = self.row_cells(ra);
            let ia = cells.iter().position(|c| c.0 == ca).unwrap();
            let ib = cells.iter().position(|c| c.0 == cb).unwrap();
            let (i0, i1) = (ia.min(ib), ia.max(ib));
            let span: usize = cells[i0..=i1].iter().map(|c| c.2 - c.1).sum();
            let width: i32 = cells[i0..=i1]
                .iter()
                .filter_map(|c| {
                    let dom = &self.doc.dom;
                    dom.child(c.0, "w:tcPr").and_then(|p| dom.child(p, "w:tcW")).and_then(|w| crate::props::int_attr(dom, w, "w:w"))
                })
                .sum();
            let first = cells[i0].0;
            for c in &cells[i0 + 1..=i1] {
                let kids: Vec<NodeId> = self.doc.dom.children(c.0).iter().copied().filter(|&k| !self.doc.dom.is(k, "w:tcPr")).collect();
                // empty paragraphs of merged cells are dropped, as in the original
                for k in kids {
                    let empty = self.doc.dom.is(k, "w:p") && self.doc.dom.elements(k).all(|e| self.doc.dom.is(e, "w:pPr"));
                    self.doc.dom.detach(k);
                    if !empty {
                        self.doc.dom.append(first, k);
                    }
                }
                self.doc.dom.detach(c.0);
            }
            let dom = &mut self.doc.dom;
            let pr = ensure_child_first(dom, first, "w:tcPr");
            if span > 1 {
                set_prop_child(dom, pr, &PropEdit::set("w:gridSpan", &[("w:val", &span.to_string())]), TCPR_ORDER);
            }
            if width > 0 {
                set_prop_child(dom, pr, &PropEdit::set("w:tcW", &[("w:w", &width.to_string()), ("w:type", "dxa")]), TCPR_ORDER);
            }
            if let Some(p) = self.first_para_in(first) {
                self.caret = Pos { para: p, off: 0 };
                self.anchor = self.caret;
            }
        } else {
            // vertical merge: the cells in the first one's column
            let col = self.row_cells(ra).into_iter().find(|c| c.0 == ca).map(|c| c.1).unwrap_or(0);
            let rows: Vec<NodeId> = self.doc.dom.children_named(ta, "w:tr").collect();
            let i0 = rows.iter().position(|&r| r == ra).unwrap();
            let i1 = rows.iter().position(|&r| r == rb).unwrap();
            let (i0, i1) = (i0.min(i1), i0.max(i1));
            let mut first: Option<NodeId> = None;
            for (k, tr) in rows[i0..=i1].iter().enumerate() {
                let Some((tc, _, _)) = self.row_cells(*tr).into_iter().find(|c| c.1 == col) else { continue };
                let dom = &mut self.doc.dom;
                let pr = ensure_child_first(dom, tc, "w:tcPr");
                if k == 0 {
                    set_prop_child(dom, pr, &PropEdit::set("w:vMerge", &[("w:val", "restart")]), TCPR_ORDER);
                    first = Some(tc);
                } else {
                    set_prop_child(dom, pr, &PropEdit::set("w:vMerge", &[]), TCPR_ORDER);
                    let kids: Vec<NodeId> = dom.children(tc).iter().copied().filter(|&k| !dom.is(k, "w:tcPr")).collect();
                    for kd in kids {
                        let empty = dom.is(kd, "w:p") && dom.elements(kd).all(|e| dom.is(e, "w:pPr"));
                        dom.detach(kd);
                        if !empty {
                            dom.append(first.unwrap(), kd);
                        }
                    }
                    // a cell must keep a paragraph
                    let np = dom.new_element("w:p", &[]);
                    dom.append(tc, np);
                }
            }
        }
        self.commit("Merge Cells", false);
        true
    }

    /// Changes so far (a cheap way to see if a command changed anything).
    pub fn version_hint(&self) -> usize {
        self.undo.len() + self.redo.len() * 100000
    }

    /// "B3": the caret's column letter and row number.
    pub fn cell_name(&self) -> String {
        let Some((tbl, tr, tc)) = self.cell_of(self.caret.para) else { return String::new() };
        let dom = &self.doc.dom;
        let ri = dom.children_named(tbl, "w:tr").position(|r| r == tr).unwrap_or(0);
        let ci = dom.children_named(tr, "w:tc").position(|c| c == tc).unwrap_or(0);
        let mut col = String::new();
        let mut n = ci + 1;
        while n > 0 {
            col.insert(0, (b'A' + ((n - 1) % 26) as u8) as char);
            n = (n - 1) / 26;
        }
        format!("{}{}", col, ri + 1)
    }

    /// The selected cells: the rectangle between the selection's ends.
    pub fn selected_cells(&self) -> Option<(NodeId, Vec<NodeId>, Vec<NodeId>)> {
        let (tbl, rows) = self.selected_rows()?;
        let (_, g0, g1) = self.selected_cols().unwrap_or((tbl, 0, usize::MAX));
        let mut cells = Vec::new();
        for r in &rows {
            for (tc, a, b) in self.row_cells(*r) {
                if a < g1 && b > g0 {
                    cells.push(tc);
                }
            }
        }
        Some((tbl, rows, cells))
    }

    fn apply_to_child(&mut self, parent: NodeId, which: &str, edits: &[PropEdit], order: &[&str], first: bool) {
        let dom = &mut self.doc.dom;
        let pr = if first {
            ensure_child_first(dom, parent, which)
        } else {
            match dom.child(parent, which) {
                Some(n) => n,
                None => {
                    let n = dom.new_element(which, &[]);
                    dom.insert(parent, 0, n);
                    n
                }
            }
        };
        for e in edits {
            set_prop_child(dom, pr, e, order);
        }
    }

    /// Table properties (w:tblPr) of the caret's table.
    pub fn table_apply(&mut self, edits: &[PropEdit], label: &str) -> bool {
        let Some((tbl, _, _)) = self.cell_of(self.caret.para) else { return false };
        self.begin();
        self.apply_to_child(tbl, "w:tblPr", edits, TBLPR_ORDER, true);
        self.commit(label, false);
        true
    }

    /// Row properties of the selected rows.
    pub fn rows_apply(&mut self, edits: &[PropEdit], label: &str) -> bool {
        let Some((_, rows)) = self.selected_rows() else { return false };
        self.begin();
        for r in rows {
            // trPr goes after tblPrEx, before the cells
            let dom = &mut self.doc.dom;
            let pr = match dom.child(r, "w:trPr") {
                Some(n) => n,
                None => {
                    let n = dom.new_element("w:trPr", &[]);
                    let idx = dom.child(r, "w:tblPrEx").and_then(|x| dom.index_in_parent(x)).map(|i| i + 1).unwrap_or(0);
                    dom.insert(r, idx, n);
                    n
                }
            };
            for e in edits {
                set_prop_child(dom, pr, e, TRPR_ORDER);
            }
        }
        self.commit(label, false);
        true
    }

    /// Cell properties of the selected cells.
    pub fn cells_apply(&mut self, edits: &[PropEdit], label: &str) -> bool {
        let Some((_, _, cells)) = self.selected_cells() else { return false };
        self.begin();
        for c in cells {
            self.apply_to_child(c, "w:tcPr", edits, TCPR_ORDER, true);
        }
        self.commit(label, false);
        true
    }

    /// Paragraph formatting of every paragraph in the selected cells.
    pub fn cells_para_apply(&mut self, edits: &[PropEdit], label: &str) -> bool {
        let Some((_, _, cells)) = self.selected_cells() else { return false };
        self.begin();
        for c in cells {
            let paras: Vec<NodeId> = self.doc.dom.children_named(c, "w:p").collect();
            for p in paras {
                let dom = &mut self.doc.dom;
                let ppr = ensure_child_first(dom, p, "w:pPr");
                for e in edits {
                    set_prop_child(dom, ppr, e, PPR_ORDER);
                }
            }
        }
        self.commit(label, false);
        true
    }

    /// Set border lines: on the table (w:tblBorders) or the selected cells
    /// (w:tcBorders). Each side: its attributes, or None to remove it.
    pub fn set_borders(&mut self, target: &str, sides: &[(String, Option<Vec<(String, String)>>)]) -> bool {
        const ORDER: &[&str] = &["w:top", "w:left", "w:start", "w:bottom", "w:right", "w:end", "w:between",
            "w:bar", "w:insideH", "w:insideV", "w:tl2br", "w:tr2bl"];
        let targets: Vec<(NodeId, &str, &str, &[&str])> = match target {
            "paras" => {
                let (a, b) = self.selection();
                self.paras_between(a.para, b.para).into_iter().map(|p| (p, "w:pPr", "w:pBdr", PPR_ORDER)).collect()
            }
            "table" => match self.cell_of(self.caret.para) {
                Some((t, _, _)) => vec![(t, "w:tblPr", "w:tblBorders", TBLPR_ORDER)],
                None => return false,
            },
            _ => match self.selected_cells() {
                Some((_, _, cells)) => cells.into_iter().map(|c| (c, "w:tcPr", "w:tcBorders", TCPR_ORDER)).collect(),
                None => return false,
            },
        };
        self.begin();
        for (node, pr_name, set_name, order) in targets {
            let dom = &mut self.doc.dom;
            let pr = ensure_child_first(dom, node, pr_name);
            let set = match dom.child(pr, set_name) {
                Some(n) => n,
                None => {
                    set_prop_child(dom, pr, &PropEdit::set(set_name, &[]), order);
                    dom.child(pr, set_name).unwrap()
                }
            };
            for (side, attrs) in sides {
                let name = format!("w:{side}");
                let e = PropEdit { name, attrs: attrs.clone() };
                set_prop_child(dom, set, &e, ORDER);
            }
        }
        self.commit("Borders", false);
        true
    }

    /// The direct borders of the first paragraph / cell / the table at the selection:
    /// (side, attributes) of each border element, for the Borders and Shading dialog.
    pub fn border_state(&self, target: &str) -> Vec<(String, Vec<(String, String)>)> {
        let (pr_name, set_name, node) = match target {
            "paras" => ("w:pPr", "w:pBdr", Some(self.selection().0.para)),
            "table" => ("w:tblPr", "w:tblBorders", self.cell_of(self.caret.para).map(|c| c.0)),
            _ => ("w:tcPr", "w:tcBorders", self.selected_cells().and_then(|c| c.2.first().copied())),
        };
        let dom = &self.doc.dom;
        let Some(set) = node.and_then(|n| dom.child(n, pr_name)).and_then(|pr| dom.child(pr, set_name)) else { return vec![] };
        dom.elements(set).map(|c| {
            let name = dom.name(c).trim_start_matches("w:").to_string();
            let attrs = match &dom.node(c).kind {
                crate::xml::Kind::Element { attrs, .. } => attrs.clone(),
                _ => vec![],
            };
            (name, attrs)
        }).collect()
    }

    /// The fill (hex) of the first paragraph / cell's direct shading.
    pub fn shading_state(&self, target: &str) -> Option<String> {
        let (pr_name, node) = match target {
            "paras" => ("w:pPr", Some(self.selection().0.para)),
            "table" => ("w:tcPr", self.cell_of(self.caret.para).map(|c| c.1)),
            _ => ("w:tcPr", self.selected_cells().and_then(|c| c.2.first().copied())),
        };
        let dom = &self.doc.dom;
        let shd = node.and_then(|n| dom.child(n, pr_name)).and_then(|pr| dom.child(pr, "w:shd"))?;
        dom.attr(shd, "w:fill").filter(|f| *f != "auto").map(|f| f.to_string())
    }

    /// Does the first selected cell have this border (w:tcBorders side)?
    pub fn cell_border_on(&self, side: &str) -> bool {
        let Some((_, _, cells)) = self.selected_cells() else { return false };
        let dom = &self.doc.dom;
        cells.first()
            .and_then(|&c| dom.child(c, "w:tcPr"))
            .and_then(|p| dom.child(p, "w:tcBorders"))
            .and_then(|b| dom.child(b, &format!("w:{side}")))
            .map_or(false, |n| !matches!(dom.attr(n, "w:val"), Some("nil" | "none") | None))
    }

    /// Column widths (twips) of the caret's table.
    pub fn grid_widths(&self) -> Vec<i32> {
        let Some((tbl, _, _)) = self.cell_of(self.caret.para) else { return Vec::new() };
        let dom = &self.doc.dom;
        dom.child(tbl, "w:tblGrid")
            .map(|g| dom.children_named(g, "w:gridCol").map(|c| crate::props::int_attr(dom, c, "w:w").unwrap_or(0)).collect())
            .unwrap_or_default()
    }

    /// Set the column widths (twips); cell widths follow.
    pub fn set_grid_widths(&mut self, widths: &[i32], label: &str) -> bool {
        let Some((tbl, _, _)) = self.cell_of(self.caret.para) else { return false };
        self.begin();
        let dom = &mut self.doc.dom;
        if let Some(grid) = dom.child(tbl, "w:tblGrid") {
            let cols: Vec<NodeId> = dom.children_named(grid, "w:gridCol").collect();
            for (c, w) in cols.iter().zip(widths) {
                dom.set_attr(*c, "w:w", &w.to_string());
            }
        }
        let rows: Vec<NodeId> = self.doc.dom.children_named(tbl, "w:tr").collect();
        for r in rows {
            for (tc, a, b) in self.row_cells(r) {
                let w: i32 = widths.iter().skip(a).take(b - a).sum();
                if w > 0 {
                    self.apply_to_child(tc, "w:tcPr", &[PropEdit::set("w:tcW", &[("w:w", &w.to_string()), ("w:type", "dxa")])],
                                        TCPR_ORDER, true);
                }
            }
        }
        self.commit(label, false);
        true
    }

    /// Grid column range of the selection (for column-width edits).
    pub fn selected_grid_cols(&self) -> Option<(usize, usize)> {
        self.selected_cols().map(|(_, a, b)| (a, b))
    }

    /// Tab in a table: the next cell's text selected (a new row after the
    /// last cell). Shift+Tab: the previous cell.
    pub fn cell_step(&mut self, back: bool) -> bool {
        let Some((tbl, tr, tc)) = self.cell_of(self.caret.para) else { return false };
        let dom = &self.doc.dom;
        let rows: Vec<NodeId> = dom.children_named(tbl, "w:tr").collect();
        let mut cells: Vec<NodeId> = Vec::new();
        for r in &rows {
            cells.extend(dom.children_named(*r, "w:tc"));
        }
        let i = cells.iter().position(|&c| c == tc).unwrap_or(0);
        let target = if back {
            if i == 0 {
                return true;
            }
            cells[i - 1]
        } else if i + 1 < cells.len() {
            cells[i + 1]
        } else {
            let _ = tr;
            self.move_to(self.caret, false, false);
            self.insert_rows(true);
            return true;
        };
        // select the cell's text, as the original does
        let paras: Vec<NodeId> = {
            let mut v = Vec::new();
            fn collect(d: &XmlDoc, n: NodeId, v: &mut Vec<NodeId>) {
                for c in d.elements(n) {
                    if d.is(c, "w:p") { v.push(c) } else if !d.is(c, "w:tbl") { collect(d, c, v) }
                }
            }
            collect(dom, target, &mut v);
            v
        };
        if let (Some(&f), Some(&l)) = (paras.first(), paras.last()) {
            let len = self.para_len(l);
            self.move_to(Pos { para: f, off: 0 }, false, false);
            self.move_to(Pos { para: l, off: len }, true, false);
        }
        true
    }

    // ----------------------------------------------------------- styles
    fn ensure_styles(&mut self) {
        if self.doc.styles_dom.is_some() {
            return;
        }
        let w = crate::document::W_NS;
        let mut sd = XmlDoc::with_root("w:styles", &[("xmlns:w", w)]);
        sd.recording = true;
        let part = "word/styles.xml".to_string();
        let main = self.doc.main.clone();
        self.doc.pkg.add_rel(&main, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles", "styles.xml");
        self.doc.pkg.set_content_type(&part, "application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml");
        self.doc.styles_part = Some(part);
        self.doc.styles_dom = Some(sd);
    }

    fn style_node(&self, id: &str) -> Option<NodeId> {
        let sd = self.doc.styles_dom.as_ref()?;
        sd.children_named(sd.root, "w:style").find(|&n| sd.attr(n, "w:styleId") == Some(id))
    }

    /// The pPr / rPr of a style (created in schema order if missing).
    fn style_part(&mut self, id: &str, which: &str) -> Option<NodeId> {
        let st = self.style_node(id)?;
        let sd = self.doc.styles_dom.as_mut()?;
        if let Some(n) = sd.child(st, which) {
            return Some(n);
        }
        let n = sd.new_element(which, &[]);
        let rank = STYLE_ORDER.iter().position(|x| *x == which).unwrap_or(STYLE_ORDER.len());
        let kids: Vec<NodeId> = sd.elements(st).collect();
        let mut idx = sd.children(st).len();
        for k in kids {
            if STYLE_ORDER.iter().position(|x| *x == sd.name(k)).unwrap_or(STYLE_ORDER.len()) > rank {
                idx = sd.index_in_parent(k).unwrap();
                break;
            }
        }
        sd.insert(st, idx, n);
        Some(n)
    }

    /// Change a style's character formatting.
    pub fn style_apply_run(&mut self, id: &str, edits: &[PropEdit]) {
        self.begin();
        if let Some(rpr) = self.style_part(id, "w:rPr") {
            let sd = self.doc.styles_dom.as_mut().unwrap();
            for e in edits {
                set_prop_child(sd, rpr, e, RPR_ORDER);
            }
        }
        self.commit("Modify Style", false);
    }

    /// Change a style's paragraph formatting (whole elements).
    pub fn style_apply_para(&mut self, id: &str, edits: &[PropEdit]) {
        self.begin();
        if let Some(ppr) = self.style_part(id, "w:pPr") {
            let sd = self.doc.styles_dom.as_mut().unwrap();
            for e in edits {
                set_prop_child(sd, ppr, e, PPR_ORDER);
            }
        }
        self.commit("Modify Style", false);
    }

    /// A paragraph style's list (w:numPr): numId and level; num 0 takes it off.
    pub fn style_set_num(&mut self, id: &str, num: i32, ilvl: i32) {
        self.begin();
        if let Some(ppr) = self.style_part(id, "w:pPr") {
            let sd = self.doc.styles_dom.as_mut().unwrap();
            set_prop_child(sd, ppr, &PropEdit::remove("w:numPr"), PPR_ORDER);
            if num > 0 {
                set_prop_child(sd, ppr, &PropEdit::set("w:numPr", &[]), PPR_ORDER);
                let np = sd.child(ppr, "w:numPr").unwrap();
                let il = sd.new_element("w:ilvl", &[("w:val", &ilvl.to_string())]);
                let ni = sd.new_element("w:numId", &[("w:val", &num.to_string())]);
                sd.append(np, il);
                sd.append(np, ni);
            }
        }
        self.commit("Modify Style", false);
        self.doc.reload_styles();
    }

    /// Change attributes of one element of a style's paragraph formatting.
    pub fn style_apply_para_attrs(&mut self, id: &str, name: &str, attrs: &[(&str, Option<&str>)]) {
        self.begin();
        if let Some(ppr) = self.style_part(id, "w:pPr") {
            let sd = self.doc.styles_dom.as_mut().unwrap();
            let el = match sd.child(ppr, name) {
                Some(n) => n,
                None => {
                    set_prop_child(sd, ppr, &PropEdit::set(name, &[]), PPR_ORDER);
                    sd.child(ppr, name).unwrap()
                }
            };
            for (k, v) in attrs {
                match v {
                    Some(v) => sd.set_attr(el, k, v),
                    None => {
                        sd.remove_attr(el, k);
                    }
                }
            }
        }
        self.commit("Modify Style", false);
    }

    /// A style's tab stops.
    pub fn style_set_tabs(&mut self, id: &str, tabs: &[(i32, String, String)]) {
        self.begin();
        if let Some(ppr) = self.style_part(id, "w:pPr") {
            let sd = self.doc.styles_dom.as_mut().unwrap();
            if let Some(old) = sd.child(ppr, "w:tabs") {
                sd.detach(old);
            }
            if !tabs.is_empty() {
                let el = sd.new_element("w:tabs", &[]);
                let mut sorted = tabs.to_vec();
                sorted.sort_by_key(|t| t.0);
                for (pos, kind, leader) in &sorted {
                    let ps = pos.to_string();
                    let mut at: Vec<(&str, &str)> = vec![("w:val", kind.as_str())];
                    if leader != "none" && !leader.is_empty() {
                        at.push(("w:leader", leader.as_str()));
                    }
                    at.push(("w:pos", ps.as_str()));
                    let t = sd.new_element("w:tab", &at);
                    sd.append(el, t);
                }
                let rank = PPR_ORDER.iter().position(|x| *x == "w:tabs").unwrap();
                let kids: Vec<NodeId> = sd.elements(ppr).collect();
                let mut idx = sd.children(ppr).len();
                for k in kids {
                    if PPR_ORDER.iter().position(|x| *x == sd.name(k)).unwrap_or(PPR_ORDER.len()) > rank {
                        idx = sd.index_in_parent(k).unwrap();
                        break;
                    }
                }
                sd.insert(ppr, idx, el);
            }
        }
        self.commit("Modify Style", false);
    }

    /// Name, based-on and following style, automatic update.
    pub fn style_set_meta(&mut self, id: &str, name: Option<&str>, based_on: Option<&str>, next: Option<&str>,
                          auto: Option<bool>) {
        self.begin();
        if let Some(st) = self.style_node(id) {
            let sd = self.doc.styles_dom.as_mut().unwrap();
            let set = |sd: &mut XmlDoc, el: &str, v: Option<&str>| {
                let e = match v {
                    Some(v) if !v.is_empty() => PropEdit::set(el, &[("w:val", v)]),
                    _ => PropEdit::remove(el),
                };
                set_prop_child(sd, st, &e, STYLE_ORDER);
            };
            if let Some(n) = name {
                set(sd, "w:name", Some(n));
            }
            if let Some(b) = based_on {
                set(sd, "w:basedOn", Some(b));
            }
            if let Some(nx) = next {
                set(sd, "w:next", Some(nx));
            }
            if let Some(a) = auto {
                let e = if a { PropEdit::set("w:autoRedefine", &[]) } else { PropEdit::remove("w:autoRedefine") };
                set_prop_child(sd, st, &e, STYLE_ORDER);
            }
        }
        self.commit("Modify Style", false);
    }

    /// Add a style definition (a w:style element's XML) unless a style with
    /// its id exists already. Returns whether it was added.
    pub fn add_style_xml(&mut self, xml: &str) -> bool {
        self.ensure_styles();
        let wrapped = format!("<w:styles xmlns:w=\"{}\">{}</w:styles>", crate::document::W_NS, xml);
        let Ok(tmp) = XmlDoc::parse(wrapped.as_bytes()) else { return false };
        let Some(st) = tmp.elements(tmp.root).next() else { return false };
        let id = tmp.attr(st, "w:styleId").unwrap_or("").to_string();
        if id.is_empty() || self.style_node(&id).is_some() {
            return false;
        }
        self.begin();
        {
            let sd = self.doc.styles_dom.as_mut().unwrap();
            let n = sd.import_node(&tmp, st);
            let root = sd.root;
            sd.append(root, n);
        }
        self.commit("New Style", false);
        true
    }

    /// A new style; returns its id.
    pub fn create_style(&mut self, name: &str, kind: &str, based_on: Option<&str>) -> String {
        self.ensure_styles();
        let mut base: String = name.chars().filter(|c| c.is_alphanumeric()).collect();
        if base.is_empty() {
            base = "Style".into();
        }
        let mut id = base.clone();
        let mut i = 1;
        while self.doc.styles.styles.contains_key(&id) || self.style_node(&id).is_some() {
            i += 1;
            id = format!("{base}{i}");
        }
        self.begin();
        {
            let sd = self.doc.styles_dom.as_mut().unwrap();
            let st = sd.new_element("w:style", &[("w:type", kind), ("w:customStyle", "1"), ("w:styleId", &id)]);
            let n = sd.new_element("w:name", &[("w:val", name)]);
            sd.append(st, n);
            if let Some(b) = based_on.filter(|b| !b.is_empty()) {
                let e = sd.new_element("w:basedOn", &[("w:val", b)]);
                sd.append(st, e);
            }
            if kind == "paragraph" {
                let e = sd.new_element("w:next", &[("w:val", &id)]);
                sd.append(st, e);
            }
            let q = sd.new_element("w:qFormat", &[]);
            sd.append(st, q);
            let root = sd.root;
            sd.append(root, st);
        }
        self.commit("New Style", false);
        id
    }

    // ------------------------------------------------------------ lists
    /// numbering.xml, created (with its relationship) if the document has
    /// none yet.
    fn ensure_numbering(&mut self) {
        if self.doc.num_dom.is_some() {
            return;
        }
        let w = crate::document::W_NS;
        let mut nd = XmlDoc::with_root("w:numbering", &[("xmlns:w", w)]);
        nd.recording = true;
        let part = "word/numbering.xml".to_string();
        let main = self.doc.main.clone();
        let rel_target = "numbering.xml";
        self.doc.pkg.add_rel(&main, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering", rel_target);
        self.doc.pkg.set_content_type(&part, "application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml");
        self.doc.num_part = Some(part);
        self.doc.num_dom = Some(nd);
    }

    /// Add a list definition (XML of a w:abstractNum) and a w:num using it;
    /// returns the new numId.
    fn add_list_definition(&mut self, kind: &str) -> i32 {
        self.ensure_numbering();
        let nd = self.doc.num_dom.as_mut().unwrap();
        let root = nd.root;
        let abs_ids: Vec<i32> = nd.children_named(root, "w:abstractNum")
            .filter_map(|a| nd.attr(a, "w:abstractNumId").and_then(|v| v.parse().ok())).collect();
        let num_ids: Vec<i32> = nd.children_named(root, "w:num")
            .filter_map(|a| nd.attr(a, "w:numId").and_then(|v| v.parse().ok())).collect();
        let aid = abs_ids.iter().max().map(|m| m + 1).unwrap_or(0);
        let nid = num_ids.iter().max().map(|m| m + 1).unwrap_or(1);
        let frag = if kind == "bullet" {
            crate::numbering::default_bullet_abstract(&aid.to_string())
        } else {
            crate::numbering::default_number_abstract(&aid.to_string())
        };
        let wrapped = format!("<w:numbering xmlns:w=\"{}\">{}<w:num w:numId=\"{}\"><w:abstractNumId w:val=\"{}\"/></w:num></w:numbering>",
                              crate::document::W_NS, frag, nid, aid);
        let Ok(tmp) = XmlDoc::parse(wrapped.as_bytes()) else { return 0 };
        let parts: Vec<NodeId> = tmp.elements(tmp.root).collect();
        // abstract definitions come before every w:num
        let first_num = nd.children_named(root, "w:num").next();
        let abs_at = match first_num {
            Some(n) => nd.index_in_parent(n).unwrap(),
            None => nd.children(root).len(),
        };
        let a = nd.import_node(&tmp, parts[0]);
        nd.insert(root, abs_at, a);
        let n = nd.import_node(&tmp, parts[1]);
        let end = nd.children(root).len();
        // numIdMacAtCleanup and similar trailing elements stay last
        let at = nd.children(root).iter().position(|&c| nd.name(c) == "w:numIdMacAtCleanup").unwrap_or(end);
        nd.insert(root, at, n);
        self.doc.reload_numbering();
        nid
    }

    fn set_num_pr(&mut self, p: NodeId, num: Option<(i32, i32)>) {
        let dom = &mut self.doc.dom;
        let ppr = ensure_child_first(dom, p, "w:pPr");
        if let Some(old) = dom.child(ppr, "w:numPr") {
            dom.detach(old);
        }
        if let Some((id, lvl)) = num {
            let np = dom.new_element("w:numPr", &[]);
            let il = dom.new_element("w:ilvl", &[("w:val", &lvl.to_string())]);
            let ni = dom.new_element("w:numId", &[("w:val", &id.to_string())]);
            dom.append(np, il);
            dom.append(np, ni);
            let rank = PPR_ORDER.iter().position(|x| *x == "w:numPr").unwrap();
            let kids: Vec<NodeId> = dom.elements(ppr).collect();
            let mut idx = dom.children(ppr).len();
            for k in kids {
                if PPR_ORDER.iter().position(|x| *x == dom.name(k)).unwrap_or(PPR_ORDER.len()) > rank {
                    idx = dom.index_in_parent(k).unwrap();
                    break;
                }
            }
            dom.insert(ppr, idx, np);
        }
    }

    fn list_kind(&self, p: NodeId) -> Option<&'static str> {
        let pl = self.para_layout(p)?;
        let lb = pl.label.as_ref()?;
        Some(if lb.bullet { "bullet" } else { "number" })
    }

    fn set_para_style_id(&mut self, p: NodeId, id: Option<&str>) {
        let dom = &mut self.doc.dom;
        let ppr = ensure_child_first(dom, p, "w:pPr");
        match id {
            Some(id) => set_prop_child(dom, ppr, &PropEdit::set("w:pStyle", &[("w:val", id)]), PPR_ORDER),
            None => set_prop_child(dom, ppr, &PropEdit::remove("w:pStyle"), PPR_ORDER),
        }
    }

    fn list_paragraph_style(&self) -> Option<String> {
        if self.doc.styles.styles.contains_key("ListParagraph") {
            return Some("ListParagraph".into());
        }
        self.doc.styles.id_for_name("List Paragraph")
    }

    /// The Bullets / Numbering buttons: the selected paragraphs become a
    /// list (continuing one just above), or stop being one.
    /// Ctrl+Q: the selected paragraphs' own formatting goes; their style,
    /// list and section stay.
    pub fn reset_para_formatting(&mut self) -> bool {
        let (a, b) = self.selection();
        let paras = self.paras_between(a.para, b.para);
        self.begin();
        for p in paras {
            let dom = &mut self.doc.dom;
            let Some(pp) = dom.child(p, "w:pPr") else { continue };
            for k in dom.elements(pp).collect::<Vec<_>>() {
                if !matches!(dom.name(k), "w:pStyle" | "w:numPr" | "w:sectPr" | "w:rPr" | "w:pPrChange") {
                    dom.detach(k);
                }
            }
        }
        self.commit("Reset Paragraph", false);
        true
    }

    pub fn toggle_list(&mut self, kind: &str) {
        let (a, b) = self.selection();
        let paras = self.paras_between(a.para, b.para);
        let all_in = paras.iter().all(|p| self.list_kind(*p) == Some(if kind == "bullet" { "bullet" } else { "number" }));
        self.begin();
        let lp = self.list_paragraph_style();
        let default = self.doc.styles.default_para.clone();
        if all_in {
            for p in &paras {
                self.set_num_pr(*p, None);
                let style = self.doc.para_direct(*p).style;
                if style.is_some() && style == lp {
                    self.set_para_style_id(*p, None);
                }
            }
            self.commit(if kind == "bullet" { "Bullets" } else { "Numbering" }, false);
            return;
        }
        // continue the list just above, if it is the same kind
        let first_idx = self.pidx(&paras[0]).copied().unwrap_or(0);
        let prev = first_idx.checked_sub(1).map(|i| self.layout.paras[i].node);
        let cont = prev.filter(|p| self.list_kind(*p) == Some(if kind == "bullet" { "bullet" } else { "number" }))
            .and_then(|p| {
                let pp = self.doc.para_props(p).0;
                pp.num_id.map(|n| (n, pp.ilvl.unwrap_or(0)))
            });
        let (num, lvl) = match cont {
            Some((n, l)) => (n, l),
            None => (self.add_list_definition(kind), 0),
        };
        if num <= 0 {
            self.commit("Bullets", false);
            return;
        }
        for p in &paras {
            let cur_lvl = self.doc.para_props(*p).0.ilvl.unwrap_or(lvl).max(0);
            self.set_num_pr(*p, Some((num, cur_lvl.max(lvl))));
            let style = self.doc.para_direct(*p).style;
            if (style.is_none() || style == default) && lp.is_some() {
                self.set_para_style_id(*p, lp.as_deref());
            }
        }
        self.commit(if kind == "bullet" { "Bullets" } else { "Numbering" }, false);
    }

    /// Tab / Shift+Tab in a list, Increase/Decrease List Level.
    pub fn change_list_level(&mut self, delta: i32) -> bool {
        let (a, b) = self.selection();
        let paras = self.paras_between(a.para, b.para);
        if !paras.iter().all(|p| self.list_kind(*p).is_some()) {
            return false;
        }
        self.begin();
        for p in &paras {
            let pp = self.doc.para_props(*p).0;
            if let Some(n) = pp.num_id {
                let l = (pp.ilvl.unwrap_or(0) + delta).clamp(0, 8);
                self.set_num_pr(*p, Some((n, l)));
            }
        }
        self.commit("Change List Level", false);
        true
    }

    /// Whether the caret is at the very start of a list item (Tab and
    /// Backspace act on the list there).
    pub fn at_list_item_start(&self) -> bool {
        !self.has_selection() && self.caret.off == 0 && self.list_kind(self.caret.para).is_some()
    }

    /// Backspace at the start of a list item: the number goes, the text
    /// keeps its indent (as in the original).
    /// The list the caret's paragraph is in: (numId, level, bullet, its number's text,
    /// the level's start value).
    pub fn list_info(&self) -> Option<(i32, i32, bool, String, i32)> {
        self.list_info_of(self.caret.para)
    }

    /// A paragraph's list: (numId, level, bullet, label, start).
    pub fn list_info_of(&self, p: NodeId) -> Option<(i32, i32, bool, String, i32)> {
        let pp = self.doc.para_props(p).0;
        let num = pp.num_id.filter(|n| *n > 0)?;
        let ilvl = pp.ilvl.unwrap_or(0);
        let pl = self.para_layout(p)?;
        let lb = pl.label.as_ref()?;
        let start = self.doc.numbering.level(num, ilvl.clamp(0, 8) as usize, &self.doc.styles).map(|l| l.start).unwrap_or(1);
        let start = self.doc.numbering.nums.get(&num).and_then(|n| n.overrides.get(&(ilvl.clamp(0, 8) as usize))).and_then(|o| o.0).unwrap_or(start);
        Some((num, ilvl, lb.bullet, lb.text.clone(), start))
    }

    /// Add a list definition (w:abstractNum's children: w:multiLevelType, w:lvl...); its numId.
    fn create_list_definition(&mut self, levels_xml: &str) -> Option<i32> {
        self.ensure_numbering();
        let nd = self.doc.num_dom.as_mut().unwrap();
        let root = nd.root;
        let aid = nd.children_named(root, "w:abstractNum").filter_map(|a| nd.attr(a, "w:abstractNumId").and_then(|v| v.parse::<i32>().ok())).max().map(|m| m + 1).unwrap_or(0);
        let nid = nd.children_named(root, "w:num").filter_map(|a| nd.attr(a, "w:numId").and_then(|v| v.parse::<i32>().ok())).max().unwrap_or(0) + 1;
        let wrapped = format!("<w:numbering xmlns:w=\"{}\"><w:abstractNum w:abstractNumId=\"{}\">{}</w:abstractNum><w:num w:numId=\"{}\"><w:abstractNumId w:val=\"{}\"/></w:num></w:numbering>",
                              crate::document::W_NS, aid, levels_xml, nid, aid);
        let tmp = XmlDoc::parse(wrapped.as_bytes()).ok()?;
        let parts: Vec<NodeId> = tmp.elements(tmp.root).collect();
        let first_num = nd.children_named(root, "w:num").next();
        let abs_at = match first_num {
            Some(n) => nd.index_in_parent(n).unwrap(),
            None => nd.children(root).len(),
        };
        let an = nd.import_node(&tmp, parts[0]);
        nd.insert(root, abs_at, an);
        let n = nd.import_node(&tmp, parts[1]);
        let end = nd.children(root).len();
        let at = nd.children(root).iter().position(|&c| nd.name(c) == "w:numIdMacAtCleanup").unwrap_or(end);
        nd.insert(root, at, n);
        self.doc.reload_numbering();
        Some(nid)
    }

    /// A new list definition (not applied); its numId.
    pub fn new_list_definition(&mut self, levels_xml: &str) -> i32 {
        self.begin();
        let r = self.create_list_definition(levels_xml).unwrap_or(0);
        self.commit("List", false);
        r
    }

    /// A list definition for the selected paragraphs: they become one list, each keeping
    /// its level.
    pub fn apply_list_definition(&mut self, levels_xml: &str) -> bool {
        let (a, b) = self.selection();
        let paras = self.paras_between(a.para, b.para);
        self.begin();
        let Some(nid) = self.create_list_definition(levels_xml) else {
            self.commit("List", false);
            return false;
        };
        for p in paras {
            let pp = self.doc.para_props(p).0;
            let lvl = if pp.num_id.unwrap_or(0) > 0 { pp.ilvl.unwrap_or(0) } else { 0 };
            self.set_num_pr(p, Some((nid, lvl)));
        }
        self.commit("Multilevel List", false);
        true
    }

    /// Body paragraphs in order, from (and including) `from`.
    fn body_paras_from(&self, from: NodeId) -> Vec<NodeId> {
        let n = self.layout.body_count.min(self.layout.paras.len());
        let all: Vec<NodeId> = self.layout.paras[..n].iter().map(|pl| pl.node).collect();
        match all.iter().position(|x| *x == from) {
            Some(i) => all[i..].to_vec(),
            None => vec![],
        }
    }

    /// Restart Numbering / Set Numbering Value > Start new list: a new list from the caret's
    /// paragraph on, its level starting at `start`.
    pub fn restart_numbering(&mut self, start: i32) -> bool {
        let Some((num, ilvl, _, _, _)) = self.list_info() else { return false };
        let Some(abs) = self.doc.numbering.nums.get(&num).map(|n| n.abs.clone()) else { return false };
        let from = self.caret.para;
        let paras: Vec<NodeId> = self.body_paras_from(from).into_iter()
            .filter(|p| self.doc.para_props(*p).0.num_id == Some(num)).collect();
        self.begin();
        let nd = self.doc.num_dom.as_mut().unwrap();
        let root = nd.root;
        let nid = nd.children_named(root, "w:num").filter_map(|a| nd.attr(a, "w:numId").and_then(|v| v.parse::<i32>().ok())).max().unwrap_or(0) + 1;
        let n = nd.new_element("w:num", &[("w:numId", &nid.to_string())]);
        let an = nd.new_element("w:abstractNumId", &[("w:val", &abs)]);
        nd.append(n, an);
        let ov = nd.new_element("w:lvlOverride", &[("w:ilvl", &ilvl.to_string())]);
        let so = nd.new_element("w:startOverride", &[("w:val", &start.to_string())]);
        nd.append(ov, so);
        nd.append(n, ov);
        let end = nd.children(root).len();
        let at = nd.children(root).iter().position(|&c| nd.name(c) == "w:numIdMacAtCleanup").unwrap_or(end);
        nd.insert(root, at, n);
        self.doc.reload_numbering();
        for p in paras {
            let lvl = self.doc.para_props(p).0.ilvl.unwrap_or(0);
            self.set_num_pr(p, Some((nid, lvl)));
        }
        self.commit("Restart Numbering", false);
        true
    }

    /// Continue Numbering: the caret's list joins the numbered list before it.
    pub fn continue_numbering(&mut self) -> bool {
        let Some((num, _, bullet, _, _)) = self.list_info() else { return false };
        if bullet {
            return false;
        }
        let n = self.layout.body_count.min(self.layout.paras.len());
        let all: Vec<NodeId> = self.layout.paras[..n].iter().map(|pl| pl.node).collect();
        let Some(i) = all.iter().position(|x| *x == self.caret.para) else { return false };
        let prev = all[..i].iter().rev().find_map(|p| {
            let pp = self.doc.para_props(*p).0;
            let id = pp.num_id.filter(|x| *x > 0 && *x != num)?;
            let pl = self.para_layout(*p)?;
            if pl.label.as_ref().is_some_and(|l| !l.bullet) { Some(id) } else { None }
        });
        let Some(target) = prev else { return false };
        let paras: Vec<NodeId> = all[i..].iter().copied().filter(|p| self.doc.para_props(*p).0.num_id == Some(num)).collect();
        self.begin();
        for p in paras {
            let lvl = self.doc.para_props(p).0.ilvl.unwrap_or(0);
            self.set_num_pr(p, Some((target, lvl)));
        }
        self.commit("Continue Numbering", false);
        true
    }

    /// The caret's list level: the number's position and the text indent (twips), what
    /// follows the number ("tab", "space", "nothing"); set on the list's definition.
    pub fn list_level_indents(&self) -> Option<(i32, i32, String)> {
        let (num, ilvl, _, _, _) = self.list_info()?;
        let lvl = self.doc.numbering.level(num, ilvl.clamp(0, 8) as usize, &self.doc.styles)?;
        let left = lvl.ppr.ind_left.unwrap_or(720);
        let first = lvl.ppr.ind_first.unwrap_or(-360);
        Some((left + first, left, if lvl.suff.is_empty() { "tab".into() } else { lvl.suff.clone() }))
    }

    pub fn set_list_level_indents(&mut self, number_at: i32, text_at: i32, suff: &str) -> bool {
        let Some((num, ilvl, _, _, _)) = self.list_info() else { return false };
        let Some(abs) = self.doc.numbering.nums.get(&num).map(|n| n.abs.clone()) else { return false };
        self.begin();
        let nd = self.doc.num_dom.as_mut().unwrap();
        let root = nd.root;
        let Some(a) = nd.children_named(root, "w:abstractNum").find(|a| nd.attr(*a, "w:abstractNumId") == Some(abs.as_str())) else {
            self.commit("Adjust List Indents", false);
            return false;
        };
        let lv = nd.children_named(a, "w:lvl").find(|l| nd.attr(*l, "w:ilvl").and_then(|v| v.parse::<i32>().ok()) == Some(ilvl));
        if let Some(lv) = lv {
            let ppr = match nd.child(lv, "w:pPr") {
                Some(x) => x,
                None => {
                    let x = nd.new_element("w:pPr", &[]);
                    nd.append(lv, x);
                    x
                }
            };
            if let Some(old) = nd.child(ppr, "w:ind") {
                nd.detach(old);
            }
            let hang = (text_at - number_at).max(0);
            let ind = if hang > 0 {
                nd.new_element("w:ind", &[("w:left", &text_at.to_string()), ("w:hanging", &hang.to_string())])
            } else {
                nd.new_element("w:ind", &[("w:left", &text_at.to_string()), ("w:firstLine", &(number_at - text_at).to_string())])
            };
            nd.append(ppr, ind);
            if let Some(old) = nd.child(lv, "w:suff") {
                nd.detach(old);
            }
            if suff != "tab" {
                let s = nd.new_element("w:suff", &[("w:val", suff)]);
                // w:suff goes after w:lvlRestart / w:pStyle / w:isLgl, before w:lvlText
                let at = nd.child(lv, "w:lvlText").and_then(|t| nd.index_in_parent(t)).unwrap_or(0);
                nd.insert(lv, at, s);
            }
        }
        self.doc.reload_numbering();
        self.commit("Adjust List Indents", false);
        true
    }

    fn remove_number_keep_indent(&mut self, p: NodeId) {
        let pp = self.doc.para_props(p).0;
        self.set_num_pr(p, Some((0, 0)));
        let left = pp.ind_left.unwrap_or(0).to_string();
        let dom = &mut self.doc.dom;
        let ppr = ensure_child_first(dom, p, "w:pPr");
        set_prop_child(dom, ppr, &PropEdit::set("w:ind", &[("w:left", &left), ("w:firstLine", "0")]), PPR_ORDER);
    }

    // ------------------------------------------------------------ files
    pub fn save(&mut self, path: &str) -> Result<(), String> {
        self.doc.save(path).map_err(|e| e.0)?;
        self.modified = false;
        Ok(())
    }

    pub fn export_pdf(&mut self, path: &str) -> Result<(), String> {
        crate::render::export_pdf(&self.layout, &mut self.fonts, path)
    }

    /// PDF with options: some pages, the headings as bookmarks, properties.
    pub fn export_pdf_opts(&mut self, path: &str, pages: Vec<usize>, bookmarks: bool,
                           meta: [String; 4]) -> Result<(), String> {
        let mut outline = Vec::new();
        if bookmarks {
            for row in self.outline_paras() {
                let (node, text, level) = (row.0, row.1, row.2);
                if !(1..=9).contains(&level) || text.trim().is_empty() {
                    continue;
                }
                if let Some((pg, _x, y, _h)) = self.caret_rect(Pos { para: node, off: 0 }) {
                    outline.push((level as u32, text.trim().to_string(), pg, y));
                }
            }
        }
        let [title, author, subject, keywords] = meta;
        let o = crate::render::PdfOptions { pages, outline, title, author, subject, keywords };
        crate::render::export_pdf_with(&self.layout, &mut self.fonts, path, &o)
    }

    // --------------------------------------------------------- drawing
    pub fn page_count(&self) -> usize {
        self.layout.pages.len()
    }

    pub fn page_size(&self, i: usize) -> (f64, f64) {
        self.layout.pages.get(i).map(|p| (p.width, p.height)).unwrap_or((612.0, 792.0))
    }

    /// Draw page `i` into `cr` (origin at the page corner, units points),
    /// with the selection and, if `caret`, the caret.
    pub fn draw_page(&mut self, cr: &cairo::Context, i: usize, caret: bool, gridlines: bool) {
        let Some(page) = self.layout.pages.get(i) else { return };
        let mut ov = Overlay { gridlines, ..Default::default() };
        for (pg, x, y, w, h) in self.selection_rects() {
            if pg == i {
                ov.selection.push((x, y, w, h));
            }
        }
        if caret && !self.has_selection() {
            if let Some((pg, x, y, h)) = self.caret_rect(self.caret) {
                if pg == i {
                    ov.caret = Some((x, y, h));
                }
            }
        }
        let page = page.clone();
        self.renderer.draw_page(cr, &self.layout, &page, &mut self.fonts, &ov);
    }
}
