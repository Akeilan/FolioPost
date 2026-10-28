//! Pages: paragraphs and tables flowed into columns and pages with the
//! original's rules (widow/orphan control, keep with next, keep lines
//! together, page break before, manual breaks, section starts).

use crate::document::{BlockKind, Document, Section};
use crate::fonts::FontCache;
use crate::layout::{tw, ParaLayout, UnitKind};
use std::collections::HashMap;
use std::sync::Arc;

/// Paragraph layouts kept between relayouts: (paragraph, width in 1/1000 pt).
pub type ParaCache = HashMap<(NodeId, i64), Arc<ParaLayout>>;

pub struct Measure<'a> {
    pub fonts: &'a mut FontCache,
    pub cache: &'a mut ParaCache,
    pub labels: HashMap<NodeId, crate::numbering::Label>,
    /// the current section's document grid pitch (points, 0: none)
    pub grid: f64,
    /// a key for the page-dependent field values in force (0: none)
    pub fields: i64,
}

impl Measure<'_> {
    pub fn para(&mut self, doc: &Document, p: NodeId, width: f64,
                ctx: Option<&(crate::props::ParaProps, crate::props::RunProps)>) -> Arc<ParaLayout> {
        let key = (p, ((width * 1000.0).round() as i64 + ((self.grid * 1000.0).round() as i64) * (1 << 32))
            .wrapping_add(self.fields.wrapping_mul(1 << 50)));
        let label = self.labels.get(&p);
        if let Some(pl) = self.cache.get(&key) {
            if pl.label.as_ref() == label {
                return pl.clone();
            }
        }
        let pl = Arc::new(crate::layout::layout_paragraph_in(doc, self.fonts, p, width, ctx, label, self.grid));
        self.cache.insert(key, pl.clone());
        pl
    }
}
use crate::props::int_attr;
use crate::xml::NodeId;

/// A line of a paragraph placed on a page.
#[derive(Clone, Debug)]
pub struct Placed {
    pub para: usize,
    pub line: usize,
    /// left edge of the paragraph's text box (points from the page's left)
    pub x: f64,
    /// top of the line (points from the page's top)
    pub y: f64,
    /// rotated text (a table cell's text direction): x, y are in the
    /// cell's own frame, drawn turned about (tx, ty); kind 1 = top to
    /// bottom (tbRl), 2 = bottom to top (btLr)
    pub frame: Option<(f64, f64, u8)>,
}

/// A table cell's box on a page.
#[derive(Clone, Debug)]
pub struct CellBox {
    pub x: f64,
    pub y: f64,
    pub w: f64,
    pub h: f64,
    pub cell: NodeId,
    pub shading: Option<u32>,
    /// borders drawn on this cell's edges: top, left, bottom, right
    pub bdr: [Option<crate::props::Border>; 4],
    /// diagonal borders: top-left to bottom-right, top-right to bottom-left
    pub diag: [Option<crate::props::Border>; 2],
}

/// A paragraph's border/shading box on a page (one per page it spans).
#[derive(Clone, Debug)]
pub struct ParaBox {
    pub para: usize,
    pub x0: f64,
    pub x1: f64,
    pub y0: f64,
    pub y1: f64,
    pub top: bool,
    pub bottom: bool,
    pub between: bool,
}

#[derive(Clone, Debug)]
pub struct Page {
    pub section: usize,
    pub width: f64,
    pub height: f64,
    pub top: f64,
    pub bottom: f64,
    pub left: f64,
    pub right: f64,
    pub lines: Vec<Placed>,
    pub cells: Vec<CellBox>,
    pub boxes: Vec<ParaBox>,
    /// floating pictures, shapes and text boxes
    pub floats: Vec<FloatBox>,
    /// index of the first block that starts on this page
    pub first_block: usize,
    /// the page number shown (PAGE fields)
    pub number: i32,
    /// the first page of its section
    pub first_of_section: bool,
    /// the header and footer it shows (parts of the document)
    pub header: Option<usize>,
    pub footer: Option<usize>,
    /// where the body text goes: top and bottom (headers and footers can
    /// push them in)
    pub body_top: f64,
    pub body_bottom: f64,
    /// header and footer lines and table cells
    pub hf_lines: Vec<Placed>,
    pub hf_cells: Vec<CellBox>,
    /// footnotes on the page (in order), their lines, and separator rules
    /// (x0, y, x1)
    pub notes: Vec<NodeId>,
    pub note_lines: Vec<Placed>,
    pub rules: Vec<(f64, f64, f64)>,
    /// the page's border (lines or art), if it has one
    pub borders: Option<crate::art::PageBorders>,
    /// line numbers: right edge x, baseline y, number, font size
    pub line_numbers: Vec<(f64, f64, i32, f64)>,
    /// Design > Page Color (w:background), as 0xRRGGBB
    pub background: Option<u32>,
    /// Page Color > Fill Effects: gradient, pattern or picture
    pub fill: Option<crate::document::PageFill>,
}

/// A floating object placed on a page.
#[derive(Clone, Debug)]
pub struct FloatBox {
    /// top-left of the object itself (effects go around it)
    pub x: f64,
    pub y: f64,
    pub float: Arc<crate::pictures::Float>,
    /// the paragraph it is anchored in
    pub para: usize,
    /// a text box's lines (page coordinates)
    pub lines: Vec<Placed>,
    /// where its position is measured from (page coordinates)
    pub origin: (f64, f64),
}

/// A rotated object's outline as fractions of its unrotated box.
fn rotated_outline(fl: &crate::pictures::Float) -> Vec<(f64, f64)> {
    let (w, h) = (fl.pic.w.max(1e-6), fl.pic.h.max(1e-6));
    let a = fl.pic.rot.to_radians();
    let (c, s) = (a.cos(), a.sin());
    [(-0.5, -0.5), (0.5, -0.5), (0.5, 0.5), (-0.5, 0.5)]
        .iter()
        .map(|(u, v)| {
            let (x, y) = (u * w, v * h);
            ((x * c - y * s) / w + 0.5, (x * s + y * c) / h + 0.5)
        })
        .collect()
}

impl FloatBox {
    /// The area text keeps out of: x0, y0, x1, y1 (None: text runs over).
    pub fn wrap_rect(&self) -> Option<[f64; 4]> {
        use crate::pictures::Wrap;
        let fl = &self.float;
        let e = fl.pic.effect;
        let d = fl.dist;
        let (dt, db) = match fl.wrap {
            Wrap::None => return None,
            Wrap::Tight | Wrap::Through => (0.0, 0.0),
            _ => (d[1], d[3]),
        };
        // a rotated object keeps text out of its rotated bounds
        let (mut x, mut y, mut w, mut h) = (self.x, self.y, fl.pic.w, fl.pic.h);
        if fl.pic.rot != 0.0 {
            let a = fl.pic.rot.to_radians();
            let (c, s) = (a.cos().abs(), a.sin().abs());
            let (rw, rh) = (w * c + h * s, w * s + h * c);
            x += (w - rw) / 2.0;
            y += (h - rh) / 2.0;
            w = rw;
            h = rh;
        }
        Some([x - e[0] - d[0], y - e[1] - dt, x + w + e[2] + d[2], y + h + e[3] + db])
    }

    /// wrap_rect, or the wrap outline's bounds when text wraps tight.
    pub fn wrap_bounds(&self) -> Option<[f64; 4]> {
        let r = self.wrap_rect()?;
        let fl = &self.float;
        let rot = if fl.pic.rot != 0.0 { Some(rotated_outline(fl)) } else { None };
        match (rot.as_ref().or(fl.poly.as_ref()), fl.wrap) {
            (Some(p), crate::pictures::Wrap::Tight | crate::pictures::Wrap::Through) => {
                let xs = p.iter().map(|q| self.x + q.0 * fl.pic.w);
                let ys = p.iter().map(|q| self.y + q.1 * fl.pic.h);
                let (x0, x1) = xs.fold((f64::INFINITY, f64::NEG_INFINITY), |a, v| (a.0.min(v), a.1.max(v)));
                let (y0, y1) = ys.fold((f64::INFINITY, f64::NEG_INFINITY), |a, v| (a.0.min(v), a.1.max(v)));
                Some([x0 - fl.dist[0], y0, x1 + fl.dist[2], y1])
            }
            _ => Some(r),
        }
    }

    /// The x range text keeps out of in the band y0..y1 (None: free).
    pub fn wrap_span(&self, y0: f64, y1: f64) -> Option<(f64, f64)> {
        let r = self.wrap_bounds()?;
        if y0 >= r[3] || y1 <= r[1] {
            return None;
        }
        let fl = &self.float;
        let tight = matches!(fl.wrap, crate::pictures::Wrap::Tight | crate::pictures::Wrap::Through);
        let rotated;
        let poly = if fl.pic.rot != 0.0 && tight {
            rotated = rotated_outline(fl);
            &rotated
        } else {
            match fl.poly.as_ref().filter(|_| tight) {
                Some(p) => p,
                None => return Some((r[0], r[2])),
            }
        };
        // the outline's extent inside the band
        let (w, h) = (fl.pic.w, fl.pic.h);
        let pt = |i: usize| (self.x + poly[i % poly.len()].0 * w, self.y + poly[i % poly.len()].1 * h);
        let (mut lo, mut hi) = (f64::INFINITY, f64::NEG_INFINITY);
        for i in 0..poly.len() {
            let (ax, ay) = pt(i);
            let (bx, by) = pt(i + 1);
            let (ya, yb) = (ay.min(by), ay.max(by));
            if yb < y0 || ya > y1 {
                continue;
            }
            let at = |y: f64| if (by - ay).abs() < 1e-9 { ax } else { ax + (bx - ax) * (y - ay) / (by - ay) };
            for y in [ya.max(y0), yb.min(y1)] {
                let x = at(y);
                lo = lo.min(x);
                hi = hi.max(x);
            }
        }
        if !lo.is_finite() {
            return None;
        }
        Some((lo - fl.dist[0], hi + fl.dist[2]))
    }
}

/// A line inside a table, relative to its row's top and the table's left.
#[derive(Clone, Debug)]
pub struct TLine {
    pub para: usize,
    pub line: usize,
    pub x: f64,
    pub y: f64,
    pub h: f64,
    /// the line holds floating objects
    pub anchors: bool,
    /// the line references footnotes
    pub notes: bool,
}

/// A cell box relative to its row's top and the table's left.
#[derive(Clone, Debug)]
pub struct TBox {
    pub x: f64,
    pub y: f64,
    pub w: f64,
    pub h: f64,
    pub node: NodeId,
    pub shading: Option<u32>,
    pub bdr: [Option<crate::props::Border>; 4],
    pub diag: [Option<crate::props::Border>; 2],
}

/// A laid-out table.
pub struct TableLayout {
    pub node: NodeId,
    /// left edge relative to the column's left
    pub x: f64,
    pub rows: Vec<RowLayout>,
}

pub struct RowLayout {
    pub node: NodeId,
    pub height: f64,
    pub exact: bool,
    pub cant_split: bool,
    pub header: bool,
    pub cells: Vec<CellLayout>,
}

#[derive(Clone)]
pub struct CellLayout {
    pub node: NodeId,
    pub x: f64,
    pub w: f64,
    pub lines: Vec<TLine>,
    pub boxes: Vec<TBox>,
    /// space above the content (margin, border) and below it
    pub pad_top: f64,
    pub pad_bottom: f64,
    /// content height (without pads)
    pub content: f64,
    /// rows this cell spans downwards (vMerge), 1 normally
    pub span_rows: usize,
    pub merged: bool,
    pub shading: Option<u32>,
    /// borders drawn on this cell's edges: top, left, bottom, right
    pub bdr: [Option<crate::props::Border>; 4],
    pub diag: [Option<crate::props::Border>; 2],
    /// the bottom edge when the table breaks after this row
    pub inner_bottom: Option<crate::props::Border>,
    /// 0 top, 1 centre, 2 bottom
    pub v_align: u8,
    /// height of the rows it spans (vertically merged cells)
    pub span_h: f64,
    /// text direction: 0 across, 1 top to bottom, 2 bottom to top; for
    /// turned text the content's left and width in the cell, and the
    /// depth of its stacked lines
    pub vert: u8,
    pub vx: f64,
    pub vw: f64,
    pub stack: f64,
}

pub struct Layout {
    pub paras: Vec<Arc<ParaLayout>>,
    /// paragraph node -> index in `paras`
    pub index: HashMap<NodeId, usize>,
    pub pages: Vec<Page>,
    /// block index -> paragraph index (paragraph blocks)
    pub block_para: Vec<Option<usize>>,
    /// how many of `paras` are the body's (the rest: headers, notes...)
    pub body_count: usize,
    /// how tracked changes show
    pub markup: crate::document::Markup,
}


struct Flow<'a> {
    doc: &'a Document,
    pages: Vec<Page>,
    sec: usize,
    col: u32,
    y: f64,
    /// something (other than empty space) is on the current column
    used: bool,
    prev_style: Option<String>,
    prev_after: f64,
    prev_contextual: bool,
    prev_bkey: Option<String>,
    /// the previous paragraph ended with a page or column break
    prev_broke: bool,
    /// a break at the end of a paragraph, taken when more content follows
    pending: Option<UnitKind>,
    /// the previous paragraph's space after was HTML auto spacing
    prev_after_auto: bool,
    /// nothing placed in the document (or since a table) yet
    doc_start: bool,
    /// where the current section began: page, first line, first cell, y
    sec_mark: (usize, usize, usize, f64),
    /// table lines placed that hold floating objects: page, the line, and
    /// the cell's text area x and width
    cell_anchors: Vec<(usize, Placed, f64, f64)>,
    /// table lines placed that reference footnotes: page, paragraph, line
    cell_notes: Vec<(usize, usize, usize)>,
    /// the current page's body top and bottom
    ptop: f64,
    pbottom: f64,
    /// room the current page's footnotes take at its bottom
    fn_h: f64,
    /// the last page number given
    page_no: i32,
    /// how far this page's text is moved right (mirror margins, left-hand
    /// pages)
    xshift: f64,
    /// the next page starts a section
    sec_fresh: bool,
    /// a section break paragraph's space after, for the next paragraph
    sect_after: Option<f64>,
    /// a paragraph whose mark doesn't show (deleted in the final text, a
    /// style separator) runs on into the next: (page, column, where its
    /// last line ends, that line's top, its height)
    run_in: Option<(usize, u32, f64, f64, f64)>,
    /// header / footer heights: (part, section) -> points
    hf_h: HashMap<(usize, usize), f64>,
    /// footnote heights, and the separator's
    note_h: HashMap<NodeId, f64>,
    sep_h: f64,
}

impl<'a> Flow<'a> {
    fn section(&self) -> &Section {
        &self.doc.sections[self.sec]
    }

    fn col_x(&self) -> f64 {
        tw(self.section().col_left(self.col)) + self.xshift
    }

    /// Left-hand page (mirrored indents swap there).
    fn even_page(&self) -> bool {
        self.page_no % 2 == 0
    }

    fn bottom(&self) -> f64 {
        self.pbottom - self.fn_h
    }

    fn top(&self) -> f64 {
        self.ptop
    }

    fn new_page(&mut self, block: usize) {
        let s = self.section().clone();
        let first = std::mem::replace(&mut self.sec_fresh, false);
        let number = match (first, s.pg_start) {
            (true, Some(n)) => n,
            _ => self.page_no + 1,
        };
        self.page_no = number;
        let even = number % 2 == 0;
        self.xshift = mirror_shift(self.doc, &s, number);
        let pick = |set: &[Option<usize>; 3]| -> Option<usize> {
            if first && s.title_pg {
                set[1]
            } else if even && self.doc.settings.even_odd_headers {
                set[2]
            } else {
                set[0]
            }
        };
        let header = pick(&s.headers);
        let footer = pick(&s.footers);
        let ph = tw(s.page_h);
        let hh = header.and_then(|h| self.hf_h.get(&(h, self.sec)).copied()).unwrap_or(0.0);
        let fh = footer.and_then(|h| self.hf_h.get(&(h, self.sec)).copied()).unwrap_or(0.0);
        // headers and footers taller than the margin push the text in
        // (a negative margin is exact: they don't)
        let body_top = if s.top < 0 || header.is_none() { tw(s.top.abs()) } else { tw(s.top).max(tw(s.header) + hh) };
        let body_bottom = if s.bottom < 0 || footer.is_none() {
            ph - tw(s.bottom.abs())
        } else {
            (ph - tw(s.bottom)).min(ph - tw(s.footer) - fh)
        };
        self.pages.push(Page {
            section: self.sec,
            width: tw(s.page_w),
            height: ph,
            top: tw(s.top.abs()),
            bottom: tw(s.bottom.abs()),
            left: if self.xshift != 0.0 { tw(s.right) } else { tw(s.left + s.gutter) },
            right: if self.xshift != 0.0 { tw(s.left + s.gutter) } else { tw(s.right) },
            lines: Vec::new(),
            cells: Vec::new(),
            boxes: Vec::new(),
            floats: Vec::new(),
            first_block: block,
            number,
            first_of_section: first,
            header,
            footer,
            body_top,
            body_bottom,
            hf_lines: Vec::new(),
            hf_cells: Vec::new(),
            notes: Vec::new(),
            note_lines: Vec::new(),
            rules: Vec::new(),
            borders: s.pg_borders.clone().filter(|b| match b.display.as_str() {
                "firstPage" => first,
                "notFirstPage" => !first,
                _ => true,
            }),
            line_numbers: Vec::new(),
            background: self.doc.page_background(),
            fill: self.doc.page_fill(),
        });
        self.ptop = body_top;
        self.pbottom = body_bottom;
        self.fn_h = 0.0;
        self.col = 0;
        self.y = self.top();
        self.used = false;
        self.prev_after = 0.0;
    }

    /// Next column, or a new page after the last one.
    fn next_column(&mut self, block: usize) {
        if self.col + 1 < self.section().cols {
            self.col += 1;
            self.y = self.top();
            self.used = false;
            self.prev_after = 0.0;
        } else {
            self.new_page(block);
        }
    }

    fn page(&mut self) -> &mut Page {
        self.pages.last_mut().unwrap()
    }
}

/// How much of a paragraph's height the first `k` lines take.
fn lines_height(p: &ParaLayout, from: usize, to: usize) -> f64 {
    p.lines[from..to].iter().map(|l| l.adv).sum()
}

/// Paragraphs with the same borders, shading and indents share one box.
fn bkey(p: &ParaLayout) -> Option<String> {
    let pp = &p.props;
    if pp.border_top.is_none() && pp.border_bottom.is_none() && pp.border_left.is_none()
        && pp.border_right.is_none() && pp.border_between.is_none() && pp.shading.is_none() {
        return None;
    }
    Some(format!("{:?}{:?}{:?}{:?}{:?}{:?}{}{}", pp.border_top, pp.border_bottom, pp.border_left, pp.border_right,
                 pp.border_between, pp.shading, p.left, p.right))
}

fn bext(b: &Option<crate::props::Border>) -> f64 {
    match b {
        Some(x) if x.style != "nil" && x.style != "none" => crate::props::border_width(b) + x.space as f64,
        _ => 0.0,
    }
}

fn widow_on(p: &ParaLayout) -> bool {
    p.props.widow.unwrap_or(true)
}

/// Height a following block needs at the bottom of a page to be "kept
/// with" the paragraph before it.
fn lead_height(paras: &[Arc<ParaLayout>], tables: &[Option<TableLayout>], blocks_para: &[Option<usize>], b: usize) -> f64 {
    if let Some(pi) = blocks_para[b] {
        let p = &paras[pi];
        let n = if widow_on(p) && p.lines.len() >= 2 { 2.min(p.lines.len()) } else { 1 };
        let n = if p.props.keep_lines.unwrap_or(false) { p.lines.len() } else { n };
        p.before + lines_height(p, 0, n.min(p.lines.len()))
    } else if let Some(Some(t)) = tables.get(b) {
        t.rows.first().map(|r| r.height).unwrap_or(0.0)
    } else {
        0.0
    }
}

pub fn layout_document(doc: &Document, fonts: &mut FontCache) -> Layout {
    let mut cache = ParaCache::new();
    layout_document_cached(doc, fonts, &mut cache)
}

pub fn layout_document_cached(doc: &Document, fonts: &mut FontCache, cache: &mut ParaCache) -> Layout {
    let labels = list_labels(doc);
    let mut m = Measure { fonts, cache, labels, grid: 0.0, fields: 0 };
    let mut paras: Vec<Arc<ParaLayout>> = Vec::new();
    let mut block_para: Vec<Option<usize>> = Vec::with_capacity(doc.blocks.len());
    let mut tables: Vec<Option<TableLayout>> = Vec::with_capacity(doc.blocks.len());
    // measure everything first
    for b in &doc.blocks {
        let s = &doc.sections[b.section];
        let width = tw(s.text_width());
        m.grid = s.grid_pitch.map(tw).unwrap_or(0.0);
        match b.kind {
            BlockKind::Para => {
                block_para.push(Some(paras.len()));
                tables.push(None);
                paras.push(m.para(doc, b.node, width, None));
            }
            BlockKind::Table => {
                block_para.push(None);
                // text in tables doesn't snap to the document grid
                let g = std::mem::replace(&mut m.grid, 0.0);
                tables.push(Some(layout_table(doc, &mut m, b.node, width, &mut paras)));
                m.grid = g;
            }
        }
    }
    let mut f = Flow {
        doc,
        pages: Vec::new(),
        sec: doc.blocks.first().map(|b| b.section).unwrap_or(0),
        col: 0,
        y: 0.0,
        used: false,
        prev_style: None,
        prev_after: 0.0,
        prev_contextual: false,
        prev_bkey: None,
        prev_broke: false,
        pending: None,
        prev_after_auto: false,
        doc_start: true,
        sec_mark: (0, 0, 0, 0.0),
        cell_anchors: Vec::new(),
        cell_notes: Vec::new(),
        ptop: 0.0,
        pbottom: 0.0,
        fn_h: 0.0,
        page_no: 0,
        xshift: 0.0,
        sec_fresh: true,
        sect_after: None,
        run_in: None,
        hf_h: HashMap::new(),
        note_h: HashMap::new(),
        sep_h: 0.0,
    };
    measure_hf_notes(&mut f, &mut m);
    if doc.sections.is_empty() {
        let body_count = paras.len();
        return Layout { index: index_of(&paras), paras, pages: Vec::new(), block_para, body_count, markup: doc.markup };
    }
    LINE_H.with(|m| {
        let mut m = m.borrow_mut();
        m.clear();
        for (i, p) in paras.iter().enumerate() {
            for (k, l) in p.lines.iter().enumerate() {
                m.insert((i, k), l.adv);
            }
        }
    });
    let body_count = paras.len();
    f.new_page(0);
    f.sec_mark = (0, 0, 0, f.y);
    let nb = doc.blocks.len();
    let mut bi = 0;
    while bi < nb {
        let blk = &doc.blocks[bi];
        let pending = f.pending.take();
        let new_page_section = blk.section != f.sec
            && !matches!(doc.sections[blk.section].start.as_str(), "continuous" | "nextColumn");
        // a pending break is taken unless a section break starts a page anyway
        if let Some(k) = pending {
            if !new_page_section {
                if k == UnitKind::ColumnBreak {
                    f.next_column(bi);
                } else {
                    f.new_page(bi);
                }
            }
        }
        // section change
        if blk.section != f.sec {
            let prev_cols = f.section().cols;
            let next_start = doc.sections[blk.section].start.clone();
            if prev_cols > 1 && next_start == "continuous" {
                // the columns before a continuous break are balanced
                balance_columns(&mut f);
            }
            f.sec = blk.section;
            let start = f.section().start.clone();
            match start.as_str() {
                "continuous" if prev_cols == 1 && f.section().cols == 1 => {}
                "continuous" => {
                    // columns change: continue below on the same page
                    f.col = 0;
                }
                "nextColumn" => f.next_column(bi),
                _ => {
                    f.sec_fresh = true;
                    f.new_page(bi);
                    let n = f.pages.len();
                    let _ = n;
                    let no = f.page_no;
                    if (start == "evenPage" && no % 2 == 1) || (start == "oddPage" && no % 2 == 0) {
                        // a blank page first
                        f.sec_fresh = true;
                        f.new_page(bi);
                    }
                }
            }
            let pg = f.pages.len() - 1;
            f.sec_mark = (pg, f.pages[pg].lines.len(), f.pages[pg].cells.len(), f.y);
        }
        match blk.kind {
            BlockKind::Para => {
                let pi = block_para[bi].unwrap();
                if paras[pi].props.frame.is_some() && !no_floats() {
                    // framed paragraphs float; the text flows around them
                    let used = place_frame(&mut f, &mut m, &mut paras, &block_para, bi);
                    bi += used;
                    continue;
                }
                place_paragraph(&mut f, &mut m, &mut paras, &tables, &block_para, bi, pi);
            }
            BlockKind::Table => {
                let t = tables[bi].as_ref().unwrap();
                place_table(&mut f, t, bi);
                cell_floats(&mut f, &mut m, &mut paras);
                for (pg, pi, li) in std::mem::take(&mut f.cell_notes) {
                    let notes = line_notes(doc, &paras[pi], li);
                    if pg + 1 == f.pages.len() {
                        add_notes(&mut f, notes);
                    } else {
                        for n in notes {
                            if !f.pages[pg].notes.contains(&n) {
                                f.pages[pg].notes.push(n);
                            }
                        }
                    }
                }
                f.prev_bkey = None;
                f.prev_broke = false;
                f.prev_style = None;
                f.prev_after = 0.0;
            }
        }
        bi += 1;
    }
    finish_pages(&mut f, &mut m, &mut paras);
    number_lines(doc, &mut f.pages, &paras);
    Layout { index: index_of(&paras), paras, pages: f.pages, block_para, body_count, markup: doc.markup }
}

thread_local! {
    /// Draft / Web Layout: manual page breaks don't start pages; Draft also
    /// leaves floating objects out
    static CONTINUOUS: std::cell::Cell<(bool, bool)> = const { std::cell::Cell::new((false, false)) };
}

pub fn set_continuous(on: bool, draft: bool) {
    CONTINUOUS.with(|c| c.set((on, draft)));
}

fn continuous() -> bool {
    CONTINUOUS.with(|c| c.get().0)
}

fn draft() -> bool {
    CONTINUOUS.with(|c| c.get().1)
}

fn is_break(k: UnitKind) -> bool {
    match k {
        UnitKind::PageBreak => !continuous(),
        UnitKind::ColumnBreak => !continuous(),
        _ => false,
    }
}

fn no_floats() -> bool {
    static V: std::sync::OnceLock<bool> = std::sync::OnceLock::new();
    *V.get_or_init(|| std::env::var("FOLIO_NOFLOAT").is_ok())
}

/// Header, footer and footnote heights, before the pages are made.
fn measure_hf_notes(f: &mut Flow, m: &mut Measure) {
    let doc = f.doc;
    let mut scratch = Vec::new();
    crate::layout::FIELDS.with(|v| {
        *v.borrow_mut() = Some(crate::layout::FieldValues { page: "1".into(), pages: "1".into(),
                                                             section_pages: "1".into(), section: "1".into() })
    });
    m.fields = 1;
    let g = std::mem::replace(&mut m.grid, 0.0);
    for (si, s) in doc.sections.iter().enumerate() {
        let width = tw(s.page_w - s.left - s.right - s.gutter).max(10.0);
        for part in s.headers.iter().chain(s.footers.iter()).flatten() {
            if f.hf_h.contains_key(&(*part, si)) {
                continue;
            }
            let (_, _, h) = layout_cell(doc, m, doc.parts[*part].root, width, &mut scratch, None);
            f.hf_h.insert((*part, si), h);
        }
    }
    let width = doc.sections.first().map(|s| tw(s.text_width())).unwrap_or(468.0);
    for &n in &doc.notes.fn_order {
        let (_, _, h) = layout_cell(doc, m, n, width, &mut scratch, None);
        f.note_h.insert(n, h);
    }
    f.sep_h = match doc.notes.fn_sep {
        Some(sep) => layout_cell(doc, m, sep, width, &mut scratch, None).2,
        None => 12.0,
    };
    m.grid = g;
    m.fields = 0;
    crate::layout::FIELDS.with(|v| *v.borrow_mut() = None);
}

/// After the body is paginated: each page's header, footer and footnotes,
/// with its page number in the fields; then the endnotes.
fn finish_pages(f: &mut Flow, m: &mut Measure, paras: &mut Vec<Arc<ParaLayout>>) {
    // endnotes after the text (they may add pages)
    place_endnotes(f, m, paras);
    let doc = f.doc;
    let total = f.pages.len();
    let g = std::mem::replace(&mut m.grid, 0.0);
    for i in 0..total {
        let (sec, number, header, footer) = {
            let p = &f.pages[i];
            (p.section.min(doc.sections.len() - 1), p.number, p.header, p.footer)
        };
        let s = &doc.sections[sec];
        let sec_pages = f.pages.iter().filter(|p| p.section == sec).count();
        let vals = crate::layout::FieldValues {
            page: crate::numbering::format_number(number, &s.pg_fmt),
            pages: total.to_string(),
            section_pages: sec_pages.to_string(),
            section: (sec + 1).to_string(),
        };
        m.fields = {
            use std::hash::{Hash, Hasher};
            let mut h = std::collections::hash_map::DefaultHasher::new();
            (&vals.page, &vals.pages, &vals.section_pages, &vals.section).hash(&mut h);
            (h.finish() as i64) | 1
        };
        crate::layout::FIELDS.with(|v| *v.borrow_mut() = Some(vals));
        let x = tw(s.left + s.gutter) + mirror_shift(doc, &s, f.pages[i].number);
        let width = tw(s.page_w - s.left - s.right - s.gutter).max(10.0);
        let ph = tw(s.page_h);
        for (part, is_header) in [(header, true), (footer, false)] {
            let Some(part) = part else { continue };
            let (lines, boxes, h) = layout_cell(doc, m, doc.parts[part].root, width, paras, None);
            let y0 = if is_header { tw(s.header) } else { ph - tw(s.footer) - h };
            let page = &mut f.pages[i];
            for b in &boxes {
                page.hf_cells.push(CellBox { x: x + b.x, y: y0 + b.y, w: b.w, h: b.h, cell: b.node, shading: b.shading,
                                             bdr: b.bdr.clone(), diag: b.diag.clone() });
            }
            for l in &lines {
                let pl = Placed { para: l.para, line: l.line, x: x + l.x, y: y0 + l.y, frame: None };
                if l.anchors {
                    f.cell_anchors.push((i, pl.clone(), x, width));
                }
                f.pages[i].hf_lines.push(pl);
            }
        }
        // footnotes at the bottom of the text
        let notes = f.pages[i].notes.clone();
        if !notes.is_empty() {
            let col_w = tw(s.text_width());
            let mut hs = Vec::new();
            for &n in &notes {
                hs.push(layout_cell(doc, m, n, col_w, paras, None));
            }
            let total_h: f64 = f.sep_h + hs.iter().map(|h| h.2).sum::<f64>();
            let mut y = f.pages[i].body_bottom - total_h;
            let page = &mut f.pages[i];
            page.rules.push((x, y + f.sep_h / 2.0, x + 144.0_f64.min(col_w)));
            y += f.sep_h;
            for (lines, boxes, h) in hs {
                for b in &boxes {
                    page.hf_cells.push(CellBox { x: x + b.x, y: y + b.y, w: b.w, h: b.h, cell: b.node,
                                                 shading: b.shading, bdr: b.bdr.clone(), diag: b.diag.clone() });
                }
                for l in &lines {
                    page.note_lines.push(Placed { para: l.para, line: l.line, x: x + l.x, y: y + l.y, frame: None });
                }
                y += h;
            }
        }
    }
    m.fields = 0;
    crate::layout::FIELDS.with(|v| *v.borrow_mut() = None);
    m.grid = g;
    // floating objects in headers and footers
    cell_floats(f, m, paras);
}

/// The endnotes after the last text, below a separator.
fn place_endnotes(f: &mut Flow, m: &mut Measure, paras: &mut Vec<Arc<ParaLayout>>) {
    let doc = f.doc;
    if doc.notes.en_order.is_empty() || f.pages.is_empty() {
        return;
    }
    let s = &doc.sections[f.pages.last().unwrap().section.min(doc.sections.len() - 1)];
    let width = tw(s.text_width());
    let x = f.col_x();
    let sep_h = match doc.notes.en_sep {
        Some(sep) => layout_cell(doc, m, sep, width, &mut Vec::new(), None).2,
        None => 12.0,
    };
    if f.y + sep_h > f.bottom() {
        f.new_page(f.pages.last().map(|p| p.first_block).unwrap_or(0));
    }
    let y = f.y;
    f.page().rules.push((x, y + sep_h / 2.0, x + 144.0_f64.min(width)));
    f.y += sep_h;
    for &n in &doc.notes.en_order.clone() {
        let (lines, _boxes, h) = layout_cell(doc, m, n, width, paras, None);
        let mut rel = 0.0;
        for l in lines {
            let gap = (l.y - rel).max(0.0);
            if f.y + gap + l.h > f.bottom() + 0.01 && f.used {
                let fb = f.pages.last().map(|p| p.first_block).unwrap_or(0);
                f.new_page(fb);
            } else {
                f.y += gap;
            }
            let y = f.y;
            f.page().note_lines.push(Placed { para: l.para, line: l.line, x: x + l.x, y, frame: None });
            f.y += l.h;
            rel = l.y + l.h;
            f.used = true;
        }
        f.y += (h - rel).max(0.0);
    }
}

/// The width a paragraph's text takes (its widest line).
fn frame_natural_width(pl: &ParaLayout) -> f64 {
    let mut w: f64 = 0.0;
    for l in &pl.lines {
        let mut end = l.end;
        while end > l.start && matches!(pl.units[end - 1].kind, UnitKind::Char(' ')) {
            end -= 1;
        }
        if end > l.start {
            let k = end - 1 - l.start;
            w = w.max(l.xs[k] + l.ws[k]);
        }
    }
    (w + pl.right).max(1.0)
}

/// Framed paragraphs (consecutive ones with the same frame): laid out at
/// the frame's width and put on the page like a floating text box.
/// Returns how many blocks they were.
fn place_frame(f: &mut Flow, m: &mut Measure, paras: &mut Vec<Arc<ParaLayout>>, block_para: &[Option<usize>],
               bi: usize) -> usize {
    use crate::pictures::{Float, Pic, Wrap};
    let doc = f.doc;
    let first = block_para[bi].unwrap();
    let fr = paras[first].props.frame.clone().unwrap();
    let mut group = vec![bi];
    let mut j = bi + 1;
    while j < block_para.len() && doc.blocks[j].section == doc.blocks[bi].section {
        match block_para[j] {
            Some(q) if paras[q].props.frame.as_ref() == Some(&fr) => group.push(j),
            _ => break,
        }
        j += 1;
    }
    let s = f.section().clone();
    let col_x = f.col_x();
    let col_w = paras[first].width;
    // width: the frame's, else what the text needs
    let mut width = match fr.w.filter(|w| *w > 0) {
        Some(w) => tw(w),
        None => group.iter().map(|&b| frame_natural_width(&paras[block_para[b].unwrap()])).fold(0.0, f64::max),
    };
    width = width.clamp(1.0, tw(s.page_w));
    let mut content = 0.0;
    let mut layouts = Vec::new();
    for &b in &group {
        let pi = block_para[b].unwrap();
        let node = doc.blocks[b].node;
        let pl = if (width - col_w).abs() > 0.01 { m.para(doc, node, width, None) } else { paras[pi].clone() };
        paras[pi] = pl.clone();
        content += pl.before + pl.height() + pl.after;
        layouts.push((pi, pl));
    }
    let drop = !fr.drop_cap.is_empty();
    let mut height = match (fr.h_rule.as_str(), fr.h) {
        ("exact", Some(h)) => tw(h.abs()),
        (_, Some(h)) if h > 0 => tw(h).max(content),
        _ => content,
    };
    if drop {
        // a drop cap spans its lines of the next paragraph
        let next_line = block_para.get(j).copied().flatten()
            .and_then(|q| paras[q].lines.first().map(|l| l.height)).unwrap_or(12.0);
        height = height.max(next_line * fr.lines as f64);
    }
    let pw = tw(s.page_w);
    let (ax, aw) = match fr.h_anchor.as_str() {
        "page" => (0.0, pw),
        "margin" => (tw(s.left + s.gutter) + f.xshift, tw(s.page_w - s.left - s.right - s.gutter)),
        _ => (col_x, col_w),
    };
    let x = if drop {
        if fr.drop_cap == "margin" { col_x - width - tw(fr.h_space) } else { col_x }
    } else {
        match fr.x_align.as_deref() {
            Some("left") | Some("inside") => ax,
            Some("right") | Some("outside") => ax + aw - width,
            Some("center") => ax + (aw - width) / 2.0,
            _ => ax + fr.x.map(tw).unwrap_or(0.0),
        }
    };
    let ph = tw(s.page_h);
    let (ay, ah) = match fr.v_anchor.as_str() {
        "page" => (0.0, ph),
        "margin" => (f.top(), f.bottom() - f.top()),
        _ => (f.y, 0.0),
    };
    let y = if drop {
        f.y
    } else {
        match fr.y_align.as_deref() {
            Some("top") | Some("inside") => ay,
            Some("bottom") | Some("outside") => ay + ah - height,
            Some("center") => ay + (ah - height) / 2.0,
            Some("inline") => f.y,
            _ => ay + fr.y.map(tw).unwrap_or(0.0),
        }
    };
    let wrap = match fr.wrap.as_str() {
        "notBeside" => Wrap::TopBottom,
        "none" => Wrap::None,
        _ => Wrap::Square,
    };
    let mut pic = Pic::empty(width, height);
    pic.kind = "frame";
    let (hs, vs) = (tw(fr.h_space), tw(fr.v_space));
    let fl = Float {
        pic,
        h_rel: "page".into(),
        h_align: None,
        h_off: x,
        h_pct: None,
        v_rel: "page".into(),
        v_align: None,
        v_off: y,
        v_pct: None,
        wrap,
        side: "bothSides".into(),
        dist: [hs, vs, hs, vs],
        behind: false,
        z: 0,
        in_cell: false,
        node: doc.blocks[bi].node,
        poly: None,
    };
    let mut lines = Vec::new();
    let mut ly = y;
    if drop {
        // the letter's baseline on that of the last line it drops over
        let next = block_para.get(j).copied().flatten().and_then(|q| paras[q].lines.first().cloned());
        if let (Some(nl), Some((_, pl))) = (next, layouts.first()) {
            if let Some(l) = pl.lines.first() {
                let raise = pl.units.first().filter(|u| u.shaped != u32::MAX)
                    .map(|u| pl.shaped[u.shaped as usize].style.raise).unwrap_or(0.0);
                let want = (fr.lines.max(1) - 1) as f64 * nl.height + nl.baseline;
                ly += want - (l.skip + l.baseline - raise) - pl.before;
            }
        }
    }
    for (pi, pl) in &layouts {
        ly += pl.before;
        for (k, l) in pl.lines.iter().enumerate() {
            lines.push(Placed { para: *pi, line: k, x, y: ly + l.skip, frame: None });
            ly += l.adv;
        }
        ly += pl.after;
    }
    f.page().floats.push(FloatBox { x, y, float: Arc::new(fl), para: first, lines, origin: (0.0, 0.0) });
    if wrap == Wrap::None && fr.v_anchor == "text" && !drop && fr.y_align.is_none() && fr.y.is_none() {
        // nothing to flow around: the frame still holds its place
        f.y += height;
    }
    group.len()
}

/// Where a floating object goes on the current page: x, y of its top-left.
fn float_pos(f: &Flow, pg: usize, fl: &crate::pictures::Float, para_y: f64, line_y: f64, line_h: f64, char_x: f64) -> (f64, f64, f64, f64) {
    let page = &f.pages[pg];
    let s = &f.doc.sections[page.section.min(f.doc.sections.len() - 1)];
    let (pw, ph) = (tw(s.page_w), tw(s.page_h));
    let shift = mirror_shift(f.doc, s, page.number);
    // mirrored: the margins swap sides on left-hand pages
    let (ml, mr) = if shift != 0.0 { (tw(s.right), tw(s.left + s.gutter)) } else { (tw(s.left + s.gutter), tw(s.right)) };
    let (mt, mb) = (page.body_top, ph - page.body_bottom);
    let odd = page.number % 2 != 0;
    let col = if pg + 1 == f.pages.len() { f.col } else { 0 };
    let col_x = tw(s.col_left(col)) + shift;
    let col_w = tw(s.col_defs.get(col as usize).map(|c| c.0).unwrap_or_else(|| s.text_width()));
    let (w, h) = (fl.pic.w, fl.pic.h);
    let (rx, rw) = match fl.h_rel.as_str() {
        "page" => (0.0, pw),
        "margin" => (ml, pw - ml - mr),
        "leftMargin" => (0.0, ml),
        "rightMargin" => (pw - mr, mr),
        "insideMargin" => if odd { (0.0, ml) } else { (pw - mr, mr) },
        "outsideMargin" => if odd { (pw - mr, mr) } else { (0.0, ml) },
        "character" => (char_x, 0.0),
        _ => (col_x, col_w),
    };
    let x = match fl.h_align.as_deref() {
        Some("left") => rx,
        Some("right") => rx + rw - w,
        Some("center") => rx + (rw - w) / 2.0,
        Some("inside") => if odd { rx } else { rx + rw - w },
        Some("outside") => if odd { rx + rw - w } else { rx },
        _ => match fl.h_pct {
            Some(p) => rx + p * rw,
            None => rx + fl.h_off,
        },
    };
    let (ry, rh) = match fl.v_rel.as_str() {
        "page" => (0.0, ph),
        "margin" => (mt, ph - mt - mb),
        "topMargin" | "insideMargin" => (0.0, mt),
        "bottomMargin" | "outsideMargin" => (ph - mb, mb),
        "line" => (line_y, line_h),
        _ => (para_y, 0.0),
    };
    let mut y = match fl.v_align.as_deref() {
        Some("top") | Some("inside") => ry,
        Some("bottom") | Some("outside") => ry + rh - h,
        Some("center") => ry + (rh - h) / 2.0,
        _ => match fl.v_pct {
            Some(p) => ry + p * rh,
            None => ry + fl.v_off,
        },
    };
    if matches!(fl.v_rel.as_str(), "paragraph" | "line") && h < ph {
        // objects that move with text stay on the page
        y = y.min(ph - h).max(0.0);
    }
    (x, y, rx, ry)
}

/// Lay out a text box's paragraphs at x, y (the box's top-left).
fn textbox_lines(f: &Flow, m: &mut Measure, paras: &mut Vec<Arc<ParaLayout>>, pic: &crate::pictures::Pic,
                 x: f64, y: f64) -> Vec<Placed> {
    // a group's members hold their own text
    let mut kids = Vec::new();
    for (dx, dy, child) in &pic.children {
        kids.extend(textbox_lines(f, m, paras, child, x + dx, y + dy));
    }
    let Some((content, ins, anchor)) = pic.text else { return kids };
    let dom = &f.doc.dom;
    let width = (pic.w - ins[0] - ins[2]).max(1.0);
    let g = std::mem::replace(&mut m.grid, 0.0);
    let mut out = Vec::new();
    let mut cy = 0.0;
    // linked text boxes: the text runs from box to box, this one shows its share
    let chain = pic.link.as_ref().map(|(id, seq)| (crate::pictures::txbx_chain(dom, id), *seq))
        .filter(|(c, _)| c.len() > 1);
    let mut boxi = 0usize;
    let my = chain.as_ref().and_then(|(c, seq)| c.iter().position(|b| b.0 == *seq)).unwrap_or(0);
    let room_of = |i: usize| chain.as_ref().and_then(|(c, _)| c.get(i)).map(|b| b.2 - b.3[1] - b.3[3]).unwrap_or(f64::MAX);
    let width_of = |i: usize| chain.as_ref().and_then(|(c, _)| c.get(i)).map(|b| (b.1 - b.3[0] - b.3[2]).max(1.0)).unwrap_or(width);
    let last_box = chain.as_ref().map(|(c, _)| c.len() - 1).unwrap_or(0);
    let mut first_in_box = true;
    for c in dom.elements(content) {
        if !dom.is(c, "w:p") {
            continue;
        }
        let pl = m.para(f.doc, c, width_of(boxi), None);
        if pl.collapsed() {
            continue;
        }
        let pi = paras.len();
        paras.push(pl.clone());
        cy += if first_in_box { pl.before } else { pl.before.max(0.0) };
        for (k, l) in pl.lines.iter().enumerate() {
            if chain.is_some() && !first_in_box && cy + l.skip + l.adv > room_of(boxi) + 0.01 && boxi < last_box {
                // on into the next box
                boxi += 1;
                cy = 0.0;
            }
            if chain.is_none() || boxi == my {
                out.push(Placed { para: pi, line: k, x, y: cy + l.skip, frame: None });
            }
            first_in_box = false;
            cy += l.adv;
        }
        cy += pl.after;
    }
    m.grid = g;
    let room = pic.h - ins[1] - ins[3];
    let off = match anchor {
        "center" => ((room - cy) / 2.0).max(0.0),
        "bottom" => (room - cy).max(0.0),
        _ => 0.0,
    };
    for l in out.iter_mut() {
        l.x = x + ins[0];
        l.y += y + ins[1] + off;
    }
    out.extend(kids);
    out
}

/// Put the floating objects anchored in lines `from..` of a paragraph (up
/// to a manual page or column break) on the current page; the paragraph's
/// top is at `para_top` and line `from` at `y0`.
#[allow(clippy::too_many_arguments)]
fn register_floats(f: &mut Flow, m: &mut Measure, paras: &mut Vec<Arc<ParaLayout>>, p: &ParaLayout, pi: usize,
                   para_top: f64, y0: f64, from: usize) {
    if draft() {
        return;
    }
    let cx = f.col_x();
    let mut ly = y0;
    let mut found = Vec::new();
    for l in p.lines[from.min(p.lines.len())..].iter() {
        for u in l.start..l.end {
            let unit = &p.units[u];
            if unit.kind != UnitKind::Anchor {
                continue;
            }
            if let Some(crate::document::Item::Anchor(Some(fl))) = p.pieces.get(unit.piece as usize).map(|pc| &pc.item) {
                let k = u - l.start;
                let char_x = cx + l.xs.get(k).copied().unwrap_or(0.0);
                found.push((fl.clone(), ly + l.skip, l.height, char_x));
            }
        }
        ly += l.adv;
        if matches!(l.ends_with, UnitKind::PageBreak | UnitKind::ColumnBreak) {
            break;
        }
    }
    for (fl, line_y, line_h, char_x) in found {
        let (x, y, rx, ry) = float_pos(f, f.pages.len() - 1, &fl, para_top, line_y, line_h, char_x);
        let lines = textbox_lines(f, m, paras, &fl.pic, x, y);
        f.page().floats.push(FloatBox { x, y, float: fl, para: pi, lines, origin: (rx, ry) });
    }
}

/// The paragraph's lines flowing around the objects on the page, its first
/// line at `y0` (None: nothing in the way).
fn wrapped(f: &Flow, orig: &ParaLayout, y0: f64) -> Option<ParaLayout> {
    let cx = f.col_x();
    let bottom = f.bottom();
    let col_w = orig.width;
    let rects: Vec<(&FloatBox, [f64; 4], crate::pictures::Wrap, String)> = f.pages.last()?.floats.iter()
        .filter_map(|fb| fb.wrap_bounds().map(|r| (fb, r, fb.float.wrap, fb.float.side.clone())))
        .filter(|(_, r, _, _)| r[3] > y0 && r[1] < bottom && r[2] > cx && r[0] < cx + col_w)
        .collect();
    if rects.is_empty() {
        return None;
    }
    let wrap = |yr: f64, h: f64| -> (Vec<(f64, f64)>, f64) {
        let ya = y0 + yr;
        let mut blocked = Vec::new();
        let mut next = f64::INFINITY;
        if ya >= bottom - 0.01 {
            return (blocked, yr);
        }
        for (fb, r, w, side) in &rects {
            if let Some((s0, s1)) = fb.wrap_span(ya, ya + h) {
                let (b0, b1) = (s0 - cx, s1 - cx);
                let range = if *w == crate::pictures::Wrap::TopBottom {
                    (-1e9, 1e9)
                } else {
                    match side.as_str() {
                        "left" => (b0, 1e9),
                        "right" => (-1e9, b1),
                        "largest" => if b0 >= col_w - b1 { (b0, 1e9) } else { (-1e9, b1) },
                        _ => (b0, b1),
                    }
                };
                blocked.push(range);
                next = next.min(r[3] - y0);
            }
        }
        (blocked, if next.is_finite() { next } else { yr })
    };
    Some(crate::layout::rewrap(f.doc, orig, &wrap))
}

/// Place the floating objects anchored in paragraph `orig` (its top at
/// `para_top`, first line at `y0` on the current page) and lay its lines out
/// around everything floating on the page.
fn prepare_floats(f: &mut Flow, m: &mut Measure, paras: &mut Vec<Arc<ParaLayout>>, orig: &Arc<ParaLayout>,
                  pi: usize, para_top: f64, y0: f64) -> Arc<ParaLayout> {
    f.page().floats.retain(|fb| fb.para != pi);
    if draft() {
        return orig.clone();
    }
    // a paragraph pushed down by an object above starts below it, and so
    // do the objects anchored in it
    let skip0 = wrapped(f, orig, y0).map(|w| w.lines.first().map(|l| l.skip).unwrap_or(0.0)).unwrap_or(0.0);
    register_floats(f, m, paras, orig, pi, para_top + skip0, y0 + skip0, 0);
    let p = match wrapped(f, orig, y0) {
        Some(w) => Arc::new(w),
        None => orig.clone(),
    };
    paras[pi] = p.clone();
    LINE_H.with(|lh| {
        let mut lh = lh.borrow_mut();
        for (k, l) in p.lines.iter().enumerate() {
            lh.insert((pi, k), l.adv);
        }
    });
    p
}

/// Floating objects anchored in table cells just placed: positioned like
/// any other (inside the cell when they lay out in it); text in the cell
/// doesn't flow around them.
fn cell_floats(f: &mut Flow, m: &mut Measure, paras: &mut Vec<Arc<ParaLayout>>) {
    let list = std::mem::take(&mut f.cell_anchors);
    let cur = f.pages.len() - 1;
    for (pg, pl, cx, cw) in list {
        let p = paras[pl.para].clone();
        let line = &p.lines[pl.line];
        let para_y = pl.y - line.skip - p.lines[..pl.line].iter().map(|l| l.adv).sum::<f64>();
        for u in line.start..line.end {
            let unit = &p.units[u];
            if unit.kind != UnitKind::Anchor {
                continue;
            }
            let Some(crate::document::Item::Anchor(Some(fl))) = p.pieces.get(unit.piece as usize).map(|pc| &pc.item) else {
                continue;
            };
            let char_x = pl.x + line.xs.get(u - line.start).copied().unwrap_or(0.0);
            let (mut x, y, mut rx, ry) = float_pos(f, pg.min(cur), fl, para_y, pl.y, line.height, char_x);
            if fl.in_cell && fl.h_rel == "column" {
                rx = cx;
                // the cell is the column
                x = match fl.h_align.as_deref() {
                    Some("right") => cx + cw - fl.pic.w,
                    Some("center") => cx + (cw - fl.pic.w) / 2.0,
                    Some("left") => cx,
                    _ => cx + fl.h_off,
                };
            }
            let lines = textbox_lines(f, m, paras, &fl.pic, x, y);
            let fb = FloatBox { x, y, float: fl.clone(), para: pl.para, lines, origin: (rx, ry) };
            f.pages[pg.min(cur)].floats.push(fb);
        }
    }
}

/// The footnotes referenced in line `li` of a paragraph.
fn line_notes(doc: &Document, p: &ParaLayout, li: usize) -> Vec<NodeId> {
    let Some(line) = p.lines.get(li) else { return Vec::new() };
    let mut out = Vec::new();
    for u in &p.units[line.start..line.end] {
        if let Some(note) = p.pieces.get(u.piece as usize).and_then(|pc| pc.note) {
            if doc.dom.is(note, "w:footnote") && !out.contains(&note) {
                out.push(note);
            }
        }
    }
    out
}

/// Put footnotes on the current page (their room comes off the bottom).
fn add_notes(f: &mut Flow, notes: Vec<NodeId>) {
    for note in notes {
        let pg = f.pages.last_mut().unwrap();
        if pg.notes.contains(&note) {
            continue;
        }
        let first = pg.notes.is_empty();
        pg.notes.push(note);
        f.fn_h += f.note_h.get(&note).copied().unwrap_or(0.0) + if first { f.sep_h } else { 0.0 };
    }
}

fn place_paragraph(f: &mut Flow, m: &mut Measure, paras: &mut Vec<Arc<ParaLayout>>, tables: &[Option<TableLayout>],
                   block_para: &[Option<usize>], bi: usize, pi: usize) {
    let mut p = paras[pi].clone();
    if p.collapsed() {
        return;
    }
    // the previous paragraph's mark is gone: this one carries on its line
    let mut run_in_before = false;
    if let Some((pg, col, x_end, top, _h)) = f.run_in.take() {
        if pg + 1 == f.pages.len() && col == f.col && !p.units.is_empty() {
            f.y = top;
            run_in_before = true;
            let wrap = move |y: f64, est: f64| -> (Vec<(f64, f64)>, f64) {
                if y < 0.01 { (vec![(-1.0e6, x_end)], y + est) } else { (Vec::new(), y) }
            };
            p = Arc::new(crate::layout::rewrap(f.doc, &p, &wrap));
            paras[pi] = p.clone();
        }
    }
    // an empty paragraph that only carries a section break right after a
    // table takes no room
    if p.units.is_empty() && bi > 0 && f.doc.blocks[bi - 1].kind == BlockKind::Table {
        let dom = &f.doc.dom;
        if dom.child(p.node, "w:pPr").and_then(|pp| dom.child(pp, "w:sectPr")).is_some() {
            return;
        }
    }
    let sect_para = {
        let dom = &f.doc.dom;
        dom.child(p.node, "w:pPr").and_then(|pp| dom.child(pp, "w:sectPr")).is_some()
    };
    let style = p.props.style.clone();
    let contextual = p.props.contextual.unwrap_or(false);
    let same_prev = f.prev_style.is_some() && f.prev_style == style;
    let mut before = p.before;
    if contextual && same_prev {
        before = 0.0;
    }
    // HTML auto spacing: none at the start of the document, and the
    // larger of two adjoining auto spacings, not their sum
    if p.props.before_auto == Some(true) && !f.doc.settings.no_html_spacing {
        if f.doc_start {
            before = 0.0;
        } else if f.prev_after_auto && f.used {
            before = (before - f.prev_after).max(0.0);
        }
    }
    // after a paragraph that ended with a page or column break, the
    // original drops this paragraph's space before
    if f.prev_broke || run_in_before {
        before = 0.0;
    }
    // a section break paragraph's space after isn't added: it eats into
    // the next paragraph's space before instead
    if let Some(c) = f.sect_after.take() {
        before = (before - c).max(0.0);
    }
    // compat 2013+: a paragraph that starts with a break has its space
    // before nowhere
    let starts_with_break = p.units.iter().find(|u| !u.gen)
        .map(|u| matches!(u.kind, UnitKind::PageBreak | UnitKind::ColumnBreak)).unwrap_or(false);
    if starts_with_break && f.doc.settings.compat_mode >= 15 {
        before = 0.0;
    }
    // the previous paragraph's space after was already added; with
    // contextual spacing it is taken back
    if same_prev && f.prev_contextual && f.used {
        f.y -= f.prev_after;
    }
    if p.props.page_break_before.unwrap_or(false) && f.used {
        f.new_page(bi);
    }
    // keep with next: the chain must start a page if it does not fit here
    if f.used && p.props.keep_next.unwrap_or(false) {
        let mut need = before + p.height();
        let mut j = bi + 1;
        let mut chain_ok = true;
        loop {
            if j >= block_para.len() {
                break;
            }
            if f.doc.blocks[j].section != f.sec {
                break;
            }
            match block_para[j] {
                Some(q) if paras[q].props.keep_next.unwrap_or(false) => {
                    need += paras[q].before + paras[q].height() + paras[q].after;
                    j += 1;
                    if j - bi > 50 {
                        chain_ok = false;
                        break;
                    }
                }
                _ => {
                    need += p.after + lead_height(paras, tables, block_para, j);
                    break;
                }
            }
        }
        let room = f.bottom() - f.top();
        if chain_ok && f.y + need > f.bottom() + 0.01 && need <= room {
            f.next_column(bi);
        }
    }
    let x = f.col_x();
    // borders and shading: grouped with the paragraphs around it
    let key = bkey(&p);
    let next_key = block_para.get(bi + 1).copied().flatten()
        .filter(|_| f.doc.blocks.get(bi + 1).map(|b| b.section == f.sec).unwrap_or(false))
        .and_then(|q| bkey(&paras[q]));
    let grouped_prev = key.is_some() && key == f.prev_bkey && f.used;
    let grouped_next = key.is_some() && key == next_key;
    let between = grouped_prev && p.props.border_between.is_some();
    let top_extra = if key.is_none() {
        0.0
    } else if grouped_prev {
        bext(&p.props.border_between)
    } else {
        bext(&p.props.border_top)
    };
    let bottom_extra = if key.is_some() && !grouped_next { bext(&p.props.border_bottom) } else { 0.0 };
    let bx0 = x + p.left - bext(&p.props.border_left);
    let bx1 = x + p.width - p.right + bext(&p.props.border_right);
    let mut seg_top = if grouped_prev { f.y } else { f.y + before };
    let mut first_seg = true;
    let para_top = f.y;
    f.y += before + top_extra;
    // floating objects: placed with the paragraph, text flows around them
    let orig = p.clone();
    let floaty = !no_floats() && p.units.iter().any(|u| u.kind == UnitKind::Anchor) || f.pages.last().map_or(false, |pg| !pg.floats.is_empty());
    if floaty {
        p = prepare_floats(f, m, paras, &orig, pi, para_top, f.y);
    }
    let mut n = p.lines.len();
    let mut li = 0;
    let keep_lines = p.props.keep_lines.unwrap_or(false);
    let widow = widow_on(&p);
    let push_box = |f: &mut Flow, y0: f64, y1: f64, first: bool, last: bool| {
        if key.is_some() {
            let pi_ = pi;
            f.page().boxes.push(ParaBox { para: pi_, x0: bx0, x1: bx1, y0, y1, top: first && !grouped_prev,
                bottom: last && !grouped_next, between: first && between });
        }
    };
    while li < n {
        // how many of the remaining lines fit
        let avail = f.bottom() - f.y;
        let mut k = 0;
        let mut h = 0.0;
        // footnotes referenced in the lines come to this page too
        let mut fn_add = 0.0;
        let mut have_notes = !f.pages.last().map_or(true, |pg| pg.notes.is_empty());
        while li + k < n {
            let lh = p.lines[li + k].adv;
            let extra = if li + k + 1 == n { bottom_extra } else { 0.0 };
            let mut nh = 0.0;
            for note in line_notes(f.doc, &p, li + k) {
                if !have_notes {
                    nh += f.sep_h;
                    have_notes = true;
                }
                nh += f.note_h.get(&note).copied().unwrap_or(0.0);
            }
            if h + lh + extra + fn_add + nh > avail + 0.01 {
                break;
            }
            if nh > 0.0 {
                have_notes = true;
            }
            fn_add += nh;
            h += lh;
            k += 1;
            // manual page / column break ends the run of lines here
            let e = p.lines[li + k - 1].ends_with;
            if is_break(e) {
                break;
            }
        }
        let rest = n - li;
        let broke_manually = k > 0 && is_break(p.lines[li + k - 1].ends_with);
        if k < rest && !broke_manually {
            // the paragraph splits here: apply the rules
            if keep_lines && f.used && li == 0 {
                k = 0;
            } else if widow && rest >= 2 {
                if li == 0 && k == 1 && f.used {
                    k = 0; // orphan
                } else if rest - k == 1 && k >= 1 {
                    // widow: pull one more line over
                    k -= 1;
                    if li == 0 && k < 2 && f.used {
                        k = 0;
                    }
                }
            }
            if k == 0 && !f.used {
                // nothing fits on an empty page: place one line regardless
                k = 1;
            }
            if k == 0 && li == 0 && sect_para && p.units.is_empty() {
                // an empty section break paragraph never makes a page of its
                // own: it sits at the bottom of this one
                k = n;
            }
        }
        if k == 0 && li == 0 {
            // the whole paragraph moves on: its box starts there
            if floaty {
                let pg = f.page();
                pg.floats.retain(|fb| fb.para != pi);
            }
            f.next_column(bi);
            seg_top = f.y;
            let top = f.y;
            f.y += top_extra;
            if floaty {
                p = prepare_floats(f, m, paras, &orig, pi, top, f.y);
                // wrapping round the floats on the new page can change the line count
                n = p.lines.len();
                li = li.min(n);
            }
            continue;
        }
        // mirrored indents: inside and outside swap on left-hand pages
        let x = f.col_x() + if p.props.mirror_indents == Some(true) && f.even_page() { p.right - p.left } else { 0.0 };
        for m in 0..k {
            let y = f.y + p.lines[li + m].skip;
            f.page().lines.push(Placed { para: pi, line: li + m, x, y, frame: None });
            f.y += p.lines[li + m].adv;
            add_notes(f, line_notes(f.doc, &p, li + m));
            f.used = true;
        }
        li += k;
        if li < n {
            let y_end = f.y;
            push_box(f, seg_top, y_end, first_seg, false);
            first_seg = false;
        }
        if broke_manually {
            let e = p.lines[li - 1].ends_with;
            if li >= n {
                // the paragraph ends here: the break waits for what follows
                f.pending = Some(e);
                break;
            }
            if e == UnitKind::ColumnBreak {
                f.next_column(bi);
            } else {
                f.new_page(bi);
            }
            seg_top = f.y;
            if floaty {
                let y = f.y;
                register_floats(f, m, paras, &p, pi, y, y, li);
            }
            continue;
        }
        if li < n {
            f.next_column(bi);
            seg_top = f.y;
        }
    }
    let broke = p.lines.last().map(|l| is_break(l.ends_with)).unwrap_or(false);
    f.y += bottom_extra;
    let mut after = if broke { 0.0 } else { p.after };
    // a hidden mark: the next paragraph's text continues on this line
    let next_para = block_para.get(bi + 1).copied().flatten()
        .filter(|_| f.doc.blocks.get(bi + 1).map_or(false, |b| b.section == f.sec));
    if p.mark_style.hidden && !p.units.is_empty() && !broke && n > 0 && next_para.is_some() && !sect_para {
        let last = &p.lines[n - 1];
        let x_end = match (last.xs.last(), last.ws.last()) {
            (Some(x), Some(w)) => x + w,
            _ => p.left,
        };
        if let Some(pl) = f.pages.last().and_then(|pg| pg.lines.last()) {
            if pl.para == pi {
                let top = pl.y - last.skip;
                f.run_in = Some((f.pages.len() - 1, f.col, x_end, top, last.adv));
                after = 0.0;
            }
        }
    }
    if sect_para {
        f.sect_after = Some(after);
        after = 0.0;
    }
    let y_end = if grouped_next { f.y + after } else { f.y };
    push_box(f, seg_top, y_end, first_seg, true);
    f.y += after;
    f.prev_broke = broke;
    f.prev_after = after;
    f.prev_after_auto = p.props.after_auto == Some(true);
    f.doc_start = false;
    f.prev_style = style;
    f.prev_contextual = contextual;
    f.prev_bkey = key;
    if p.after > 0.0 || n > 0 {
        f.used = true;
    }
}

fn place_table(f: &mut Flow, t: &TableLayout, bi: usize) {
    let nh = t.rows.iter().take_while(|r| r.header).count();
    let header_h: f64 = t.rows[..nh].iter().map(|r| r.height).sum();
    // header rows repeat on each page, unless they would fill it
    let repeat = |f: &mut Flow, ri: usize| {
        if ri >= nh && nh > 0 && header_h < (f.bottom() - f.top()) / 2.0 {
            for h in &t.rows[..nh] {
                place_row_part(f, f.col_x() + t.x, &h.cells, h.height);
            }
        }
    };
    // repeating header rows stay together (and with the row after them):
    // when they don't fit here, the table starts on the next page
    if nh > 0 && f.used {
        let next = t.rows.get(nh).map(|r| r.height.min(30.0)).unwrap_or(0.0);
        if f.y + header_h + next > f.bottom() + 0.01 {
            f.next_column(bi);
        }
    }
    // (cells index on the page where the last row part starts, that row's cells)
    let mut last: Option<(usize, usize)> = None;
    for (ri, row) in t.rows.iter().enumerate() {
        let x0 = f.col_x() + t.x;
        // the part of the row still to place: per cell lines shifted up
        let mut cells: Vec<CellLayout> = row.cells.clone();
        let mut height = row.height;
        // the row already moved to a fresh page (it can't move again)
        let mut fresh = !f.used;
        let mut guard = 0;
        loop {
            guard += 1;
            let x0 = if guard > 1 { f.col_x() + t.x } else { x0 };
            let room = f.bottom() - f.y;
            if height <= room + 0.01 || guard > 200 {
                let from = f.pages.last().unwrap().cells.len();
                place_row_part(f, x0, &cells, height);
                last = Some((from, ri));
                break;
            }
            // the row does not fit
            let splittable = !row.cant_split && !row.exact;
            let fits_some = splittable && cells.iter().any(|c| {
                c.lines.first().map(|l| l.y + l.h <= room - c.pad_bottom + 0.01).unwrap_or(false)
            });
            if !fits_some {
                if fresh {
                    // nothing fits even on a fresh page: place it as it is
                    place_row_part(f, x0, &cells, height.min(room.max(0.0)).max(if splittable { 0.0 } else { height }));
                    break;
                }
                if let Some((from, lr)) = last {
                    close_row_on_page(f, from, &t.rows[lr].cells);
                }
                f.next_column(bi);
                repeat(f, ri);
                fresh = true;
                continue;
            }
            // split: what fits stays, the rest moves to the next page
            let mut rest: Vec<CellLayout> = Vec::new();
            let mut now: Vec<CellLayout> = Vec::new();
            for c in &cells {
                let limit = room - c.pad_bottom + 0.01;
                let k = c.lines.iter().take_while(|l| l.y + l.h <= limit).count();
                let mut a = c.clone();
                a.lines.truncate(k);
                a.boxes.retain(|b| b.y < room);
                let mut r = c.clone();
                r.lines = c.lines[k..].to_vec();
                let shift = r.lines.first().map(|l| l.y - c.pad_top).unwrap_or(0.0);
                for l in r.lines.iter_mut() {
                    l.y -= shift;
                }
                r.boxes = c.boxes.iter().filter(|b| b.y + b.h > room).cloned().map(|mut b| {
                    b.y = (b.y - shift).max(0.0);
                    b
                }).collect();
                r.content = r.lines.last().map(|l| l.y + l.h - c.pad_top).unwrap_or(0.0);
                now.push(a);
                rest.push(r);
            }
            let from = f.pages.last().unwrap().cells.len();
            place_row_part(f, x0, &now, room);
            close_row_on_page(f, from, &row.cells);
            f.next_column(bi);
            repeat(f, ri);
            fresh = true;
            height = rest.iter().map(|c| c.pad_top + c.content + c.pad_bottom).fold(0.0, f64::max);
            cells = rest;
        }
    }
}

fn place_row_part(f: &mut Flow, x0: f64, cells: &[CellLayout], height: f64) {
    let y0 = f.y;
    let bottom = f.bottom();
    for c in cells {
        if c.merged {
            continue;
        }
        let page = f.pages.last_mut().unwrap();
        let h = if c.span_rows > 1 { c.span_h.max(height).min(bottom - y0) } else { height };
        page.cells.push(CellBox { x: x0 + c.x, y: y0, w: c.w, h, cell: c.node, shading: c.shading, bdr: c.bdr.clone(), diag: c.diag.clone() });
        for b in &c.boxes {
            page.cells.push(CellBox { x: x0 + b.x, y: y0 + b.y, w: b.w, h: b.h, cell: b.node, shading: b.shading,
                bdr: b.bdr.clone(), diag: b.diag.clone() });
        }
        // vertical alignment moves the content down in the cell
        let room = h - c.pad_top - c.content - c.pad_bottom;
        let dy = if room > 0.0 {
            match c.v_align {
                1 => room / 2.0,
                2 => room,
                _ => 0.0,
            }
        } else {
            0.0
        };
        if c.vert != 0 {
            // turned text: the lines in the cell's frame, turned about its corner
            let along = h - c.pad_top - c.pad_bottom;
            let off = ((c.vw - c.stack).max(0.0)) * match c.v_align { 1 => 0.5, 2 => 1.0, _ => 0.0 };
            let frame = if c.vert == 1 {
                (x0 + c.vx + c.vw - off, y0 + c.pad_top, 1u8)
            } else {
                (x0 + c.vx + off, y0 + c.pad_top + along, 2u8)
            };
            for l in &c.lines {
                let pl = Placed { para: l.para, line: l.line, x: l.x, y: l.y, frame: Some(frame) };
                f.pages.last_mut().unwrap().lines.push(pl);
            }
            continue;
        }
        for l in &c.lines {
            let pl = Placed { para: l.para, line: l.line, x: x0 + l.x, y: y0 + l.y + dy, frame: None };
            if l.anchors {
                f.cell_anchors.push((f.pages.len() - 1, pl.clone(), x0 + c.x, c.w));
            }
            if l.notes {
                f.cell_notes.push((f.pages.len() - 1, l.para, l.line));
            }
            f.pages.last_mut().unwrap().lines.push(pl);
        }
    }
    f.y += height;
    f.used = true;
}

/// The table goes on on the next page: the last row placed gets its bottom
/// edge drawn.
fn close_row_on_page(f: &mut Flow, from: usize, cells: &[CellLayout]) {
    let page = f.pages.last_mut().unwrap();
    let mut it = cells.iter().filter(|c| !c.merged);
    for cb in page.cells[from..].iter_mut() {
        // only the row's own cells (nested boxes keep theirs)
        if let Some(c) = it.clone().find(|c| c.node == cb.cell) {
            if cb.bdr[2].is_none() {
                cb.bdr[2] = c.inner_bottom.clone();
            }
        }
    }
    let _ = it.next();
}

fn grid_span(dom: &crate::xml::XmlDoc, c: NodeId) -> usize {
    dom.child(c, "w:tcPr")
        .and_then(|p| dom.child(p, "w:gridSpan"))
        .and_then(|g| int_attr(dom, g, "w:val"))
        .unwrap_or(1)
        .max(1) as usize
}

/// Which of a table style's conditional formats apply (w:tblLook).
#[derive(Clone, Copy)]
struct Look {
    first_row: bool,
    last_row: bool,
    first_col: bool,
    last_col: bool,
    h_band: bool,
    v_band: bool,
}

fn table_look(dom: &crate::xml::XmlDoc, tbl: NodeId) -> Look {
    let mut l = Look { first_row: true, last_row: false, first_col: true, last_col: false, h_band: true, v_band: false };
    let Some(n) = dom.child(tbl, "w:tblPr").and_then(|p| dom.child(p, "w:tblLook")) else { return l };
    if let Some(v) = dom.attr(n, "w:val").and_then(|v| u32::from_str_radix(v, 16).ok()) {
        l.first_row = v & 0x20 != 0;
        l.last_row = v & 0x40 != 0;
        l.first_col = v & 0x80 != 0;
        l.last_col = v & 0x100 != 0;
        l.h_band = v & 0x200 == 0;
        l.v_band = v & 0x400 == 0;
    }
    let flag = |k: &str| dom.attr(n, k).map(|v| v == "1" || v == "true" || v == "on");
    if let Some(v) = flag("w:firstRow") { l.first_row = v; }
    if let Some(v) = flag("w:lastRow") { l.last_row = v; }
    if let Some(v) = flag("w:firstColumn") { l.first_col = v; }
    if let Some(v) = flag("w:lastColumn") { l.last_col = v; }
    if let Some(v) = flag("w:noHBand") { l.h_band = !v; }
    if let Some(v) = flag("w:noVBand") { l.v_band = !v; }
    l
}

fn bw(b: &Option<crate::props::Border>) -> f64 {
    crate::props::border_width(b)
}

/// The border drawn on an edge two cells share: the heavier one.
fn heavier(a: &Option<crate::props::Border>, b: &Option<crate::props::Border>) -> Option<crate::props::Border> {
    let (wa, wb) = (bw(a), bw(b));
    if wa <= 0.0 && wb <= 0.0 {
        return None;
    }
    if wb > wa { b.clone() } else { a.clone() }
}

/// Measure a table: column widths from its grid, every cell's content and
/// formatting (table style with its conditional formats, direct cell
/// formatting).
pub fn layout_table(doc: &Document, m: &mut Measure, tbl: NodeId, avail: f64,
                    paras: &mut Vec<Arc<ParaLayout>>) -> TableLayout {
    use crate::props::{parse_margins, CellFmt, TblProps};
    let dom = &doc.dom;
    let direct = dom.child(tbl, "w:tblPr").map(|n| TblProps::parse(dom, n)).unwrap_or_default();
    let (mut tp, spp, srp) = doc.styles.table_style(direct.style.as_deref());
    tp.apply(&direct);
    let (whole, conds) = doc.styles.table_conditions(direct.style.as_deref());
    let look = table_look(dom, tbl);
    let band_size = |name: &str| -> usize {
        let from_doc = dom.child(tbl, "w:tblPr").and_then(|p| dom.child(p, name)).and_then(|n| int_attr(dom, n, "w:val"));
        from_doc.unwrap_or(1).max(1) as usize
    };
    let (row_band, col_band) = (band_size("w:tblStyleRowBandSize"), band_size("w:tblStyleColBandSize"));
    let mut grid: Vec<f64> = dom
        .child(tbl, "w:tblGrid")
        .map(|g| dom.children_named(g, "w:gridCol").map(|c| tw(int_attr(dom, c, "w:w").unwrap_or(0))).collect())
        .unwrap_or_default();
    // rows the review display takes out (deleted ones in the final text)
    let gone_mark = match doc.hidden_change() {
        "del" => "w:del",
        "ins" => "w:ins",
        _ => "",
    };
    let rows: Vec<NodeId> = dom.children_named(tbl, "w:tr")
        .filter(|&r| gone_mark.is_empty() || dom.child(r, "w:trPr").and_then(|p| dom.child(p, gone_mark)).is_none())
        .collect();
    let row_cols = |r: NodeId| -> usize {
        let before = dom
            .child(r, "w:trPr")
            .and_then(|tp| dom.child(tp, "w:gridBefore"))
            .and_then(|g| int_attr(dom, g, "w:val"))
            .unwrap_or(0)
            .max(0) as usize;
        before + dom.children_named(r, "w:tc").map(|c| grid_span(dom, c)).sum::<usize>()
    };
    let ncols = rows.iter().map(|r| row_cols(*r)).max().unwrap_or(1).max(1);
    if grid.len() < ncols || grid.iter().sum::<f64>() <= 0.0 {
        let have: f64 = grid.iter().sum();
        let missing = ncols.saturating_sub(grid.len());
        if have <= 0.0 {
            grid = vec![avail / ncols as f64; ncols];
        } else {
            let each = ((avail - have) / missing.max(1) as f64).max(20.0);
            grid.extend(std::iter::repeat(each).take(missing));
        }
    }
    // percentage width: scale the grid to it
    if let Some((w, kind)) = &tp.width {
        if kind == "pct" && *w > 0 {
            let want = avail * *w as f64 / 5000.0;
            let have: f64 = grid.iter().sum();
            if have > 0.0 && (want - have).abs() > 1.0 {
                let k = want / have;
                for g in grid.iter_mut() {
                    *g *= k;
                }
            }
        }
    }
    let total: f64 = grid.iter().sum();
    let spacing = tp.cell_spacing.map(tw).unwrap_or(0.0);
    let left_mar = tp.cell_mar[1].map(tw).unwrap_or(5.4);
    let ind = tp.ind.map(tw).unwrap_or(0.0);
    let x = match tp.jc.as_deref() {
        Some("center") => (avail - total) / 2.0,
        Some("right") | Some("end") => avail - total,
        _ => {
            if doc.settings.compat_mode >= 15 {
                ind
            } else {
                ind - left_mar
            }
        }
    };
    let mut out = TableLayout { node: tbl, x, rows: Vec::new() };
    let nrows = rows.len();
    let tb = tp.borders.clone();
    let header_rows = rows
        .iter()
        .take_while(|r| {
            dom.child(**r, "w:trPr").and_then(|t| dom.child(t, "w:tblHeader")).map(|n| crate::props::on_off(dom, n)).unwrap_or(false)
        })
        .count();
    // vMerge bookkeeping: grid column -> (row index, cell index) of the restart
    let mut open: HashMap<usize, (usize, usize)> = HashMap::new();
    // per row: (grid start, grid end, raw sides top/left/bottom/right) for edge resolution
    let mut raw: Vec<Vec<(usize, usize, [Option<crate::props::Border>; 4])>> = Vec::new();
    for (ri, r) in rows.iter().enumerate() {
        let r = *r;
        let trpr = dom.child(r, "w:trPr");
        let mut min_h = 0.0;
        let mut exact = false;
        let mut cant_split = false;
        let mut header = false;
        if let Some(t) = trpr {
            if let Some(h) = dom.child(t, "w:trHeight") {
                min_h = tw(int_attr(dom, h, "w:val").unwrap_or(0));
                exact = dom.attr(h, "w:hRule") == Some("exact");
            }
            cant_split = dom.child(t, "w:cantSplit").map(|n| crate::props::on_off(dom, n)).unwrap_or(false);
            header = dom.child(t, "w:tblHeader").map(|n| crate::props::on_off(dom, n)).unwrap_or(false);
        }
        let skip = trpr
            .and_then(|t| dom.child(t, "w:gridBefore"))
            .and_then(|g| int_attr(dom, g, "w:val"))
            .unwrap_or(0)
            .max(0) as usize;
        let row_end = row_cols(r);
        let mut gi = skip.min(grid.len());
        let mut cells = Vec::new();
        let mut raw_row = Vec::new();
        let tcs: Vec<NodeId> = dom.children_named(r, "w:tc").collect();
        let ntc = tcs.len();
        for (ci, c) in tcs.into_iter().enumerate() {
            let tcpr = dom.child(c, "w:tcPr");
            let span = grid_span(dom, c);
            let vm = tcpr.and_then(|p| dom.child(p, "w:vMerge"));
            let vmerge_cont = vm.map(|v| dom.attr(v, "w:val").map(|s| s != "restart").unwrap_or(true)).unwrap_or(false);
            let g0 = gi.min(grid.len());
            let g1 = (gi + span).min(grid.len());
            let cx: f64 = grid[..g0].iter().sum();
            let cw: f64 = grid[g0..g1].iter().sum();
            let col = gi;
            gi += span;
            // ---- the formatting that applies to this cell; repeating
            // header rows all count as the first row
            let first_row = ri == 0 || ri < header_rows;
            let last_row = ri + 1 == nrows;
            let first_col = ci == 0;
            let last_col = ci + 1 == ntc;
            let mut fmt = whole.clone();
            let apply = |name: &str, fmt: &mut CellFmt| {
                if let Some((_, f)) = conds.iter().find(|(n, _)| n == name) {
                    fmt.apply(f);
                }
            };
            if look.v_band && !(look.first_col && first_col) && !(look.last_col && last_col) {
                let k = col.saturating_sub(if look.first_col { 1 } else { 0 }) / col_band;
                apply(if k % 2 == 0 { "band1Vert" } else { "band2Vert" }, &mut fmt);
            }
            if look.h_band && !(look.first_row && first_row) && !(look.last_row && last_row) {
                let k = ri.saturating_sub(if look.first_row { 1 } else { 0 }) / row_band;
                apply(if k % 2 == 0 { "band1Horz" } else { "band2Horz" }, &mut fmt);
            }
            if look.first_col && first_col { apply("firstCol", &mut fmt); }
            if look.last_col && last_col { apply("lastCol", &mut fmt); }
            if look.first_row && first_row { apply("firstRow", &mut fmt); }
            if look.last_row && last_row { apply("lastRow", &mut fmt); }
            if first_row && first_col { apply("nwCell", &mut fmt); }
            if first_row && last_col { apply("neCell", &mut fmt); }
            if last_row && first_col { apply("swCell", &mut fmt); }
            if last_row && last_col { apply("seCell", &mut fmt); }
            // sides from the table's borders, then the conditional ones,
            // then the cell's own
            let pick = |set: &[Option<crate::props::Border>; 6], edge: usize, outer: bool| -> Option<Option<crate::props::Border>> {
                let v = if outer { set[edge].clone() } else { set[if edge == 0 || edge == 2 { 4 } else { 5 }].clone() };
                v.map(Some)
            };
            let mut sides: [Option<crate::props::Border>; 4] = [
                if first_row { tb[0].clone() } else { tb[4].clone() },
                if col == 0 { tb[1].clone() } else { tb[5].clone() },
                if last_row { tb[2].clone() } else { tb[4].clone() },
                if col + span >= row_end.max(ncols) { tb[3].clone() } else { tb[5].clone() },
            ];
            // conditional formats: the region's outer edges, inside lines within it
            let fb = &fmt.borders;
            if fb.iter().any(|b| b.is_some()) {
                // rows: top/bottom are the row's; left/right only at the row's ends
                let edges = [
                    pick(fb, 0, true),
                    pick(fb, 1, first_col),
                    pick(fb, 2, true),
                    pick(fb, 3, last_col),
                ];
                for (i, e) in edges.into_iter().enumerate() {
                    if let Some(b) = e {
                        sides[i] = b;
                    }
                }
            }
            let mut cm = tp.cell_mar;
            let mut own = CellFmt::default();
            if let Some(p) = tcpr {
                if let Some(mm) = dom.child(p, "w:tcMar") {
                    parse_margins(dom, mm, &mut cm);
                }
                own = CellFmt::parse_tc(dom, p);
                for i in 0..4 {
                    let k = [0, 1, 2, 3][i];
                    if own.borders[k].is_some() {
                        sides[i] = own.borders[k].clone();
                    }
                }
            }
            let shading = own.shading.or(fmt.shading);
            let v_align = match own.v_align.as_deref().or(fmt.v_align.as_deref()) {
                Some("center") => 1,
                Some("bottom") => 2,
                _ => 0,
            };
            raw_row.push((col, col + span, sides.clone()));
            // the paragraph formatting the table style gives this cell
            let mut cpp = spp.clone();
            let mut crp = srp.clone();
            if fmt.has_ppr {
                cpp.apply(&fmt.ppr);
            }
            if fmt.has_rpr {
                crp.apply(&fmt.rpr);
            }
            let ctx = (cpp, crp);
            let ml = cm[1].map(tw).unwrap_or(5.4);
            let mr = cm[3].map(tw).unwrap_or(5.4);
            let top_w = bw(&sides[0]);
            let pad_top = cm[0].map(tw).unwrap_or(0.0) + top_w + spacing;
            let pad_bottom = cm[2].map(tw).unwrap_or(0.0) + if last_row || spacing > 0.0 { bw(&sides[2]) } else { 0.0 } + spacing;
            let inner = (cw - ml - mr).max(1.0);
            let mut cell = CellLayout {
                node: c,
                x: cx,
                w: cw,
                lines: Vec::new(),
                boxes: Vec::new(),
                pad_top,
                pad_bottom,
                content: 0.0,
                span_rows: 1,
                merged: vmerge_cont,
                shading,
                bdr: sides,
                diag: {
                    // the cell's own diagonal lines
                    let bd = tcpr.and_then(|p| dom.child(p, "w:tcBorders"));
                    let get = |name: &str| bd.and_then(|b| dom.child(b, name)).map(|n| crate::props::parse_border(dom, n))
                        .filter(|b| crate::props::border_width(&Some(b.clone())) > 0.0);
                    [get("w:tl2br"), get("w:tr2bl")]
                },
                inner_bottom: None,
                v_align,
                span_h: 0.0,
                vert: match tcpr.and_then(|p| dom.child(p, "w:textDirection")).and_then(|n| dom.attr(n, "w:val")) {
                    Some("tbRl") | Some("tbRlV") | Some("tb") | Some("tbV") => 1,
                    Some("btLr") => 2,
                    _ => 0,
                },
                vx: cx + ml,
                vw: inner,
                stack: 0.0,
            };
            if vmerge_cont {
                if let Some(&(rr, cc)) = open.get(&col) {
                    out.rows[rr].cells[cc].span_rows += 1;
                }
            } else if cell.vert != 0 {
                // turned text runs down (or up) the cell: as long as the
                // row's set height, or its longest line
                let avail_len = (min_h - pad_top - pad_bottom).max(0.0);
                let len = if avail_len > 18.0 && exact {
                    avail_len
                } else {
                    let keep = paras.len();
                    let (probe, _, _) = layout_cell(doc, m, c, 1584.0, paras, Some(&ctx));
                    let longest = probe.iter().map(|l| {
                        let p = &paras[l.para];
                        p.lines.get(l.line).map(|ln| {
                            let k = ln.end.saturating_sub(ln.start);
                            if k == 0 { 0.0 } else { ln.xs[k - 1] + ln.ws[k - 1] }
                        }).unwrap_or(0.0) + l.x
                    }).fold(0.0, f64::max);
                    let len = longest.max(avail_len).max(12.0) + 1.0;
                    paras.truncate(keep);
                    len
                };
                let (lines, boxes, h) = layout_cell(doc, m, c, len, paras, Some(&ctx));
                let _ = boxes;
                cell.lines = lines;
                cell.stack = h;
                cell.content = len;
                if vm.is_some() {
                    open.insert(col, (ri, cells.len()));
                } else {
                    open.remove(&col);
                }
            } else {
                let (lines, boxes, h) = layout_cell(doc, m, c, inner, paras, Some(&ctx));
                cell.lines = lines
                    .into_iter()
                    .map(|mut l| {
                        l.x += cx + ml;
                        l.y += pad_top;
                        l
                    })
                    .collect();
                cell.boxes = boxes
                    .into_iter()
                    .map(|mut b| {
                        b.x += cx + ml;
                        b.y += pad_top;
                        b
                    })
                    .collect();
                cell.content = h;
                if vm.is_some() {
                    open.insert(col, (ri, cells.len()));
                } else {
                    open.remove(&col);
                }
            }
            cells.push(cell);
        }
        raw.push(raw_row);
        let height = min_h;
        out.rows.push(RowLayout { node: r, height, exact, cant_split, header, cells });
    }
    // shared edges: the heavier of the two cells' borders is drawn once
    let nr = out.rows.len();
    for ri in 0..nr {
        let ncell = out.rows[ri].cells.len();
        for ci in 0..ncell {
            let (g0, g1, sides) = raw[ri][ci].clone();
            let above = if ri > 0 { raw[ri - 1].iter().find(|(a, b, _)| *a < g1 && *b > g0).map(|x| x.2.clone()) } else { None };
            let below = if ri + 1 < nr { raw[ri + 1].iter().find(|(a, b, _)| *a < g1 && *b > g0).map(|x| x.2.clone()) } else { None };
            let left = if ci > 0 { Some(raw[ri][ci - 1].2.clone()) } else { None };
            let c = &mut out.rows[ri].cells[ci];
            if spacing > 0.0 {
                // separated cells draw all their own sides
                c.bdr = sides.clone();
                continue;
            }
            c.bdr[0] = match &above {
                Some(a) => heavier(&sides[0], &a[2]),
                None => sides[0].clone(),
            };
            c.bdr[1] = match &left {
                Some(l) => heavier(&sides[1], &l[3]),
                None => sides[1].clone(),
            };
            c.inner_bottom = match &below {
                Some(b) => heavier(&sides[2], &b[0]),
                None => sides[2].clone(),
            };
            c.bdr[2] = if ri + 1 == nr { sides[2].clone() } else { None };
            c.bdr[3] = if ci + 1 == ncell { sides[3].clone() } else { None };
        }
    }
    for row in out.rows.iter_mut() {
        if row.exact {
            continue;
        }
        let own = row
            .cells
            .iter()
            .filter(|c| !c.merged && c.span_rows == 1)
            .map(|c| c.pad_top + c.content + c.pad_bottom)
            .fold(0.0, f64::max);
        row.height = row.height.max(own);
    }
    // vertically merged cells: their content may need the last row to grow
    for ri in 0..out.rows.len() {
        for ci in 0..out.rows[ri].cells.len() {
            let c = &out.rows[ri].cells[ci];
            if c.span_rows > 1 && !c.merged {
                let need = c.pad_top + c.content + c.pad_bottom;
                let last = (ri + c.span_rows - 1).min(out.rows.len() - 1);
                let have: f64 = out.rows[ri..=last].iter().map(|r| r.height).sum();
                if need > have && !out.rows[last].exact {
                    out.rows[last].height += need - have;
                }
            }
        }
    }
    for ri in 0..out.rows.len() {
        for ci in 0..out.rows[ri].cells.len() {
            let span = out.rows[ri].cells[ci].span_rows;
            if span > 1 {
                let last = (ri + span - 1).min(out.rows.len() - 1);
                let h: f64 = out.rows[ri..=last].iter().map(|r| r.height).sum();
                out.rows[ri].cells[ci].span_h = h;
                // the merged cell's bottom edge is that of the last row it covers
                if last + 1 == out.rows.len() {
                    let b = raw[ri][ci].2[2].clone();
                    out.rows[ri].cells[ci].bdr[2] = b;
                }
            }
        }
    }
    out
}

thread_local! {
    static TABLE_DEPTH: std::cell::Cell<u32> = const { std::cell::Cell::new(0) };
}

/// A cell's content: lines and nested cell boxes relative to the content
/// box, and its height.
fn layout_cell(doc: &Document, m: &mut Measure, cell: NodeId, width: f64, paras: &mut Vec<Arc<ParaLayout>>,
               ctx: Option<&(crate::props::ParaProps, crate::props::RunProps)>) -> (Vec<TLine>, Vec<TBox>, f64) {
    fn flatten(doc: &Document, n: NodeId, out: &mut Vec<NodeId>) {
        for c in doc.dom.elements(n) {
            match doc.dom.name(c) {
                "w:p" | "w:tbl" => out.push(c),
                "w:sdt" => {
                    if let Some(sc) = doc.dom.child(c, "w:sdtContent") {
                        flatten(doc, sc, out);
                    }
                }
                "w:customXml" => flatten(doc, c, out),
                _ => {}
            }
        }
    }
    let dom = &doc.dom;
    let mut lines = Vec::new();
    let mut boxes = Vec::new();
    let mut y = 0.0;
    let mut prev: Option<(Option<String>, f64, bool)> = None;
    let mut flat = Vec::new();
    flatten(doc, cell, &mut flat);
    for n in flat {
        if dom.name(n) == "w:p" {
            let pl = m.para(doc, n, width, ctx);
            if pl.collapsed() {
                paras.push(pl);
                continue;
            }
            let style = pl.props.style.clone();
            let contextual = pl.props.contextual.unwrap_or(false);
            let mut before = pl.before;
            if let Some((ps, pa, pc)) = &prev {
                if *ps == style {
                    if contextual {
                        before = 0.0;
                    }
                    if *pc {
                        y -= pa;
                    }
                }
            }
            if let Some(fr) = pl.props.frame.clone() {
                // a frame floats: it takes no room here
                let pi = paras.len();
                let natural = frame_natural_width(&pl);
                let fw = fr.w.filter(|w| *w > 0).map(tw).unwrap_or(natural).min(width);
                let fx = match fr.x_align.as_deref() {
                    Some("right") | Some("outside") => width - fw,
                    Some("center") => (width - fw) / 2.0,
                    Some(_) => 0.0,
                    None => fr.x.map(tw).unwrap_or(0.0).max(0.0).min(width),
                };
                let fy = if fr.y_align.is_none() { fr.y.map(tw).unwrap_or(0.0) } else { 0.0 };
                let mut ly = y + fy + pl.before;
                for (li, l) in pl.lines.iter().enumerate() {
                    lines.push(TLine { para: pi, line: li, x: fx, y: ly + l.skip, h: l.height, anchors: false,
                                       notes: false });
                    ly += l.adv;
                }
                paras.push(pl);
                continue;
            }
            y += before;
            let pi = paras.len();
            for (li, l) in pl.lines.iter().enumerate() {
                let anchors = pl.units[l.start..l.end].iter().any(|u| u.kind == UnitKind::Anchor);
                let notes = pl.units[l.start..l.end].iter()
                    .any(|u| pl.pieces.get(u.piece as usize).map_or(false, |pc| pc.note.is_some()));
                lines.push(TLine { para: pi, line: li, x: 0.0, y: y + l.skip, h: l.height, anchors, notes });
                y += l.adv;
            }
            y += pl.after;
            prev = Some((style, pl.after, contextual));
            paras.push(pl);
        } else {
            // documents can nest tables absurdly deep; past a point the
            // inner ones are not laid out
            let depth = TABLE_DEPTH.with(|d| d.get());
            if depth > 24 {
                continue;
            }
            TABLE_DEPTH.with(|d| d.set(depth + 1));
            let t = layout_table(doc, m, n, width, paras);
            TABLE_DEPTH.with(|d| d.set(depth));
            for row in &t.rows {
                for c in &row.cells {
                    if c.merged {
                        continue;
                    }
                    let h = if c.span_rows > 1 { c.span_h } else { row.height };
                    boxes.push(TBox { x: t.x + c.x, y, w: c.w, h, node: c.node, shading: c.shading, bdr: c.bdr.clone(), diag: c.diag.clone() });
                    for b in &c.boxes {
                        boxes.push(TBox { x: t.x + b.x, y: y + b.y, ..b.clone() });
                    }
                    for l in &c.lines {
                        lines.push(TLine { x: t.x + l.x, y: y + l.y, ..l.clone() });
                    }
                }
                y += row.height;
            }
            prev = None;
        }
    }
    lines.sort_by(|a, b| a.y.partial_cmp(&b.y).unwrap_or(std::cmp::Ordering::Equal));
    (lines, boxes, y)
}

/// Mirror margins: on left-hand (even) pages the text moves so the inside
/// margin (and gutter) is on the right.
fn mirror_shift(doc: &Document, s: &crate::document::Section, number: i32) -> f64 {
    if doc.settings.mirror_margins && number % 2 == 0 {
        tw(s.right - s.left - s.gutter)
    } else {
        0.0
    }
}

fn index_of(paras: &[Arc<ParaLayout>]) -> HashMap<NodeId, usize> {
    paras.iter().enumerate().map(|(i, p)| (p.node, i)).collect()
}

/// Every numbered paragraph's label, counted in document order.
pub fn list_labels(doc: &Document) -> HashMap<NodeId, crate::numbering::Label> {
    let mut out = HashMap::new();
    if doc.numbering.nums.is_empty() {
        return out;
    }
    let mut counter = crate::numbering::Counter::default();
    fn walk(doc: &Document, n: NodeId, counter: &mut crate::numbering::Counter,
            out: &mut HashMap<NodeId, crate::numbering::Label>) {
        for c in doc.dom.elements(n) {
            match doc.dom.name(c) {
                "w:p" => {
                    let (pp, base) = doc.para_props(c);
                    let num = pp.num_id.unwrap_or(0);
                    if num > 0 {
                        let ilvl = pp.ilvl.unwrap_or(0).clamp(0, 8) as usize;
                        let mark = doc.mark_props(c, &base);
                        if mark.vanish != Some(true) {
                            if let Some(l) = counter.next(&doc.numbering, &doc.styles, num, ilvl, &mark) {
                                out.insert(c, l);
                            }
                        }
                    }
                }
                "w:tbl" | "w:tr" | "w:tc" | "w:sdt" | "w:sdtContent" | "w:customXml" => walk(doc, c, counter, out),
                _ => {}
            }
        }
    }
    walk(doc, doc.body, &mut counter, &mut out);
    out
}

/// Balance the columns of the section that just ended on its last page
/// (the original does this at a continuous section break).
fn balance_columns(f: &mut Flow) {
    let sec = f.section().clone();
    let n = sec.cols.max(1) as usize;
    let pg = f.pages.len() - 1;
    let (mpage, ml, mc, my) = f.sec_mark;
    let (from_l, from_c, top) = if mpage == pg { (ml, mc, my) } else { (0, 0, f.top()) };
    let page = &f.pages[pg];
    if page.cells.len() > from_c || page.lines.len() <= from_l {
        // tables in columns are left as they are
        return;
    }
    let col_of = |x: f64| -> usize {
        let mut c = 0;
        for i in 0..n {
            if x + 0.5 >= tw(sec.col_left(i as u32)) {
                c = i;
            }
        }
        c
    };
    // the column contents stacked one after another
    struct E { idx: usize, rel: f64, h: f64, col: usize }
    let mut es: Vec<E> = Vec::new();
    for (k, l) in page.lines.iter().enumerate().skip(from_l) {
        let p = &f.pages[pg].lines[k];
        let _ = p;
        es.push(E { idx: k, rel: l.y - top, h: 0.0, col: col_of(l.x) });
    }
    // line heights come from the paragraph layouts; the caller keeps them
    // in the Placed entries only implicitly, so take the gap to the next
    // line in the same column (or the line's own height via the layout)
    let _ = &es;
    let lines_h: Vec<f64> = es.iter().map(|e| {
        let l = &f.pages[pg].lines[e.idx];
        LINE_H.with(|m| m.borrow().get(&(l.para, l.line)).copied().unwrap_or(12.0))
    }).collect();
    for (e, h) in es.iter_mut().zip(lines_h) {
        e.h = h;
    }
    es.sort_by(|a, b| a.col.cmp(&b.col).then(a.rel.partial_cmp(&b.rel).unwrap_or(std::cmp::Ordering::Equal)));
    // stacked positions
    let mut stacked: Vec<(f64, f64)> = Vec::new();
    let mut offset = 0.0;
    let mut cur_col = usize::MAX;
    let mut col_extent: f64 = 0.0;
    for e in &es {
        if e.col != cur_col {
            offset += col_extent;
            col_extent = 0.0;
            cur_col = e.col;
        }
        stacked.push((offset + e.rel, e.h));
        col_extent = col_extent.max(e.rel + e.h);
    }
    let total: f64 = offset + col_extent;
    if es.is_empty() || total <= 0.0 {
        return;
    }
    // the smallest column height that holds everything in n columns
    let fits = |t: f64| -> bool {
        let mut cols = 1;
        let mut start = stacked[0].0;
        for &(s, h) in &stacked {
            if s + h - start > t + 0.01 {
                cols += 1;
                start = s;
                if h > t + 0.01 {
                    return false;
                }
            }
        }
        cols <= n
    };
    let (mut lo, mut hi) = (total / n as f64, total);
    if !fits(hi) {
        return;
    }
    for _ in 0..40 {
        let mid = (lo + hi) / 2.0;
        if fits(mid) {
            hi = mid;
        } else {
            lo = mid;
        }
    }
    let t = hi;
    // place again
    let mut col = 0usize;
    let mut start = stacked[0].0;
    let mut max_h: f64 = 0.0;
    let mut moves: Vec<(usize, f64, f64)> = Vec::new();
    for (e, &(s, h)) in es.iter().zip(&stacked) {
        if s + h - start > t + 0.01 && col + 1 < n {
            col += 1;
            start = s;
        }
        let ny = top + (s - start);
        let old_x0 = tw(sec.col_left(e.col as u32));
        let new_x0 = tw(sec.col_left(col as u32));
        let x = f.pages[pg].lines[e.idx].x - old_x0 + new_x0;
        moves.push((e.idx, x, ny));
        max_h = max_h.max(s - start + h);
    }
    for (idx, x, y) in moves {
        let l = &mut f.pages[pg].lines[idx];
        l.x = x;
        l.y = y;
    }
    f.col = 0;
    f.y = top + max_h;
    f.used = true;
}

thread_local! {
    /// line heights of the layout being paginated, for column balancing
    static LINE_H: std::cell::RefCell<HashMap<(usize, usize), f64>> = std::cell::RefCell::new(HashMap::new());
}

/// Layout > Line Numbers: the body's lines (not tables, frames or text
/// boxes) counted per page, section or document, every `count by`-th shown
/// left of its column.
fn number_lines(doc: &Document, pages: &mut [Page], paras: &[Arc<ParaLayout>]) {
    if doc.sections.iter().all(|s| s.ln_num.is_none()) {
        return;
    }
    let dom = &doc.dom;
    let in_table = |n: NodeId| {
        let mut c = n;
        while let Some(p) = dom.parent(c) {
            if dom.is(p, "w:tc") || dom.is(p, "w:txbxContent") {
                return true;
            }
            if dom.is(p, "w:body") {
                return false;
            }
            c = p;
        }
        false
    };
    let size = doc.styles.doc_rpr.size.unwrap_or(22) as f64 / 2.0;
    let mut n = 0i32;
    let mut last_sec = usize::MAX;
    for page in pages.iter_mut() {
        let Some(sec) = doc.sections.get(page.section) else { continue };
        let Some((by, start, dist, restart)) = sec.ln_num.clone() else {
            last_sec = page.section;
            continue;
        };
        if restart == "newPage" || (restart == "newSection" && page.section != last_sec) || last_sec == usize::MAX
            || (restart == "continuous" && n == 0) {
            n = start;
        }
        last_sec = page.section;
        let dist = if dist > 0 { tw(dist) } else { 18.0 };
        // reading order: by column (left edge), then down the page
        let mut order: Vec<&Placed> = page.lines.iter().filter(|l| l.frame.is_none()).collect();
        order.sort_by(|a, b| {
            let ca = (a.x / 36.0).round();
            let cb = (b.x / 36.0).round();
            ca.partial_cmp(&cb).unwrap().then(a.y.partial_cmp(&b.y).unwrap())
        });
        let mut col_left: Vec<f64> = Vec::new();
        for l in &order {
            let p = &paras[l.para];
            if in_table(p.node) || p.props.frame.is_some() {
                continue;
            }
            if p.props.suppress_line_numbers.unwrap_or(false) || p.collapsed() {
                continue;
            }
            n += 1;
            if n % by.max(1) != 0 {
                continue;
            }
            let line = &p.lines[l.line];
            // the column's left edge: the leftmost paragraph box seen near it
            let left = col_left.iter().copied().find(|c| (c - l.x).abs() < 72.0).unwrap_or(l.x);
            if !col_left.iter().any(|c| (c - l.x).abs() < 72.0) {
                col_left.push(l.x);
            }
            page.line_numbers.push((left - dist, l.y + line.baseline, n, size));
        }
    }
}
