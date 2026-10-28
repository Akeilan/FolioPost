//! Paragraph layout: lines, tabs, alignment and line height by the
//! original's rules.

use crate::document::{Document, Item};
use crate::fonts::FontCache;
use crate::props::{ParaProps, RunProps, TabKind, TabStop};
use crate::text::{shape_text, Shaped, TextStyle};
use crate::xml::NodeId;
use std::sync::Arc;

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum UnitKind {
    Char(char),
    Tab,
    LineBreak,
    PageBreak,
    ColumnBreak,
    Object,
    /// where a floating object is anchored (no width, no height)
    Anchor,
    /// an equation (its box in ParaLayout::maths[idx])
    Math,
}

#[derive(Clone, Debug)]
pub struct Unit {
    pub kind: UnitKind,
    /// position in the paragraph's text
    pub pos: usize,
    pub width: f64,
    /// which shaped stretch it belongs to (u32::MAX: none)
    pub shaped: u32,
    pub idx: u32,
    pub asc: f64,
    pub desc: f64,
    pub piece: u32,
    /// object size (points)
    pub obj: (f64, f64),
    /// generated (a list number and the tab after it): not part of the text
    pub gen: bool,
}

#[derive(Clone, Debug)]
pub struct TabFill {
    pub x: f64,
    pub width: f64,
    pub leader: char,
}

#[derive(Clone, Debug)]
pub struct Line {
    /// units [start, end)
    pub start: usize,
    pub end: usize,
    /// text positions [pos_start, pos_end)
    pub pos_start: usize,
    pub pos_end: usize,
    pub height: f64,
    /// from the top of the line to the baseline
    pub baseline: f64,
    /// x of each unit (relative to the margin), same length as units
    pub xs: Vec<f64>,
    /// width of each unit as laid out (tabs and justified spaces stretched)
    pub ws: Vec<f64>,
    pub ends_with: UnitKind,
    pub tabs: Vec<TabFill>,
    /// room skipped above the line (floating objects in the way)
    pub skip: f64,
    /// how far the next line starts below this one's top (skip + height;
    /// 0 for a piece of a line that continues beside an object)
    pub adv: f64,
    /// a hyphen drawn after the last unit (the word breaks here): its width
    pub hyphen: f64,
}

#[derive(Clone)]
pub struct ParaLayout {
    pub node: NodeId,
    /// laid-out equations (UnitKind::Math units point here)
    pub maths: Vec<Arc<crate::math::MBox>>,
    pub props: ParaProps,
    pub units: Vec<Unit>,
    pub shaped: Vec<Shaped>,
    pub lines: Vec<Line>,
    /// spacing before / after in points (before contextual rules)
    pub before: f64,
    pub after: f64,
    pub left: f64,
    pub right: f64,
    pub first: f64,
    pub width: f64,
    pub text_len: usize,
    pub mark_style: TextStyle,
    /// piece index -> (run node, text node)
    pub pieces: Vec<crate::document::Piece>,
    pub label: Option<crate::numbering::Label>,
    /// where a right/center aligned number starts relative to the indent
    pub label_shift: f64,
    /// document grid pitch the lines snap to (0: none)
    pub grid: f64,
    /// the paragraph mark's ascent and descent
    pub mark_metrics: (f64, f64),
    /// the paragraph mark or the paragraph's formatting is a tracked change
    pub mark_change: bool,
}

impl ParaLayout {
    /// Does line `li` hold a tracked change (shown or not)?
    pub fn line_changed(&self, li: usize) -> bool {
        let Some(l) = self.lines.get(li) else { return false };
        let last = li + 1 == self.lines.len();
        let mut pos = 0;
        for pc in &self.pieces {
            let len = pc.item.len();
            if !pc.change.is_empty() || pc.fmt_change {
                let hit = if len > 0 {
                    pos < l.pos_end.max(l.pos_start + 1) && pos + len > l.pos_start
                } else {
                    pos >= l.pos_start && (pos < l.pos_end || (last && pos == l.pos_end))
                };
                if hit && (len > 0 || pc.change == "del" || pc.change == "ins") {
                    return true;
                }
            }
            pos += len;
        }
        self.mark_change && last
    }

    /// An empty paragraph whose mark is hidden takes no room.
    pub fn collapsed(&self) -> bool {
        self.mark_style.hidden && self.units.is_empty()
    }

    pub fn height(&self) -> f64 {
        self.lines.iter().map(|l| l.adv).sum()
    }
}

/// Values of the page-dependent fields while laying out a header, footer
/// or note on one page.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct FieldValues {
    pub page: String,
    pub pages: String,
    pub section_pages: String,
    pub section: String,
}

impl FieldValues {
    fn get(&self, kind: &str) -> String {
        match kind {
            "PAGE" => self.page.clone(),
            "NUMPAGES" => self.pages.clone(),
            "SECTIONPAGES" => self.section_pages.clone(),
            "SECTION" => self.section.clone(),
            _ => String::new(),
        }
    }
}

thread_local! {
    pub static FIELDS: std::cell::RefCell<Option<FieldValues>> = const { std::cell::RefCell::new(None) };
}

pub fn tw(v: i32) -> f64 {
    v as f64 / 20.0
}

/// Lay out one paragraph for a text column `width` points wide.
pub fn layout_paragraph(doc: &Document, fonts: &mut FontCache, p: NodeId, width: f64) -> ParaLayout {
    layout_paragraph_in(doc, fonts, p, width, None, None, 0.0)
}

/// Lay out a paragraph; `table` is the formatting a table style gives the
/// paragraphs in its cells.
pub fn layout_paragraph_in(doc: &Document, fonts: &mut FontCache, p: NodeId, width: f64,
                           table: Option<&(ParaProps, RunProps)>,
                           label: Option<&crate::numbering::Label>, grid: f64) -> ParaLayout {
    let (props, base) = match table {
        None => doc.para_props(p),
        Some((tp, tr)) => {
            let direct = doc.para_direct(p);
            let (mut pp, rp) = doc.styles.para_style_in_table(direct.style.as_deref(), tp, tr);
            doc.apply_numbering(&mut pp, &direct);
            pp.apply(&direct);
            (pp, rp)
        }
    };
    let pieces = doc.para_pieces(p, &base);
    let mark_rpr = doc.mark_props(p, &base);
    let mut mark_style = TextStyle::from_props(&mark_rpr);
    if let Some(tc) = mark_rpr.theme_color.as_deref() {
        if let Some(c) = crate::props::theme_color(&doc.styles.theme.colors, tc) {
            mark_style.color = Some(c);
        }
    }
    {
        // a paragraph mark the review display takes out (a deleted one in
        // the final text, an inserted one in the original)
        let dom = &doc.dom;
        let gone = match doc.hidden_change() {
            "del" => ["w:del", "w:moveFrom"],
            "ins" => ["w:ins", "w:moveTo"],
            _ => ["", ""],
        };
        let rpr = dom.child(p, "w:pPr").and_then(|pp| dom.child(pp, "w:rPr"));
        if rpr.map_or(false, |r| gone.iter().any(|g| !g.is_empty() && dom.child(r, g).is_some())) {
            mark_style.hidden = true;
        }
    }
    let mut units: Vec<Unit> = Vec::new();
    let mut maths: Vec<Arc<crate::math::MBox>> = Vec::new();
    let mut has_display = false;
    let mut shaped: Vec<Shaped> = Vec::new();
    let mut pos = 0usize;
    // the list number or bullet, then a tab or space
    if let Some(lb) = label {
        let mut st = TextStyle::from_props(&lb.rpr);
        if let Some(tc) = lb.rpr.theme_color.as_deref() {
            if let Some(c) = crate::props::theme_color(&doc.styles.theme.colors, tc) {
                st.color = Some(c);
            }
        }
        let (fa, fd) = line_metrics(doc, fonts, &lb.rpr, &st);
        if !lb.text.is_empty() {
            for sh in shape_text(fonts, &doc.styles, &lb.rpr, &st, &lb.text) {
                let si = shaped.len() as u32;
                let asc = (sh.font.ascent_pt(st.draw_size).max(0.0) + st.raise).max(0.0);
                let desc = (sh.font.descent_pt(st.draw_size).max(0.0) - st.raise).max(0.0);
                for (k, &c) in sh.text.iter().enumerate() {
                    units.push(Unit { kind: UnitKind::Char(c), pos: 0, width: sh.widths[k], shaped: si, idx: k as u32,
                        asc, desc, piece: u32::MAX, obj: (0.0, 0.0), gen: true });
                }
                shaped.push(sh);
            }
        }
        match lb.suff.as_str() {
            "space" => {
                for sh in shape_text(fonts, &doc.styles, &lb.rpr, &st, " ") {
                    let si = shaped.len() as u32;
                    units.push(Unit { kind: UnitKind::Char(' '), pos: 0, width: sh.widths[0], shaped: si, idx: 0,
                        asc: fa, desc: fd, piece: u32::MAX, obj: (0.0, 0.0), gen: true });
                    shaped.push(sh);
                }
            }
            "nothing" => {}
            _ => units.push(Unit { kind: UnitKind::Tab, pos: 0, width: 0.0, shaped: u32::MAX, idx: 0, asc: fa,
                desc: fd, piece: u32::MAX, obj: (0.0, 0.0), gen: true }),
        }
    }
    let label_jc = label.map(|l| l.jc.clone()).unwrap_or_default();
    let grid_pitch = if props.snap_to_grid == Some(false) { 0.0 } else { grid };
    let label_w: f64 = units.iter().take(label.map(|l| l.text.chars().count()).unwrap_or(0)).map(|u| u.width).sum();
    let field_vals = FIELDS.with(|f| f.borrow().clone());
    let mut prev_field = false;
    for (pi, pc) in pieces.iter().enumerate() {
        // page-dependent field results show this page's values
        let computed;
        let item = match (&pc.item, pc.field, &field_vals) {
            (Item::Text(t), Some(kind), Some(vals)) => {
                let v = if prev_field { String::new() } else { vals.get(kind) };
                computed = Item::Atom(v, t.chars().count());
                prev_field = true;
                &computed
            }
            (Item::Hidden(_), _, _) => {
                prev_field = false;
                &pc.item
            }
            _ => {
                prev_field = false;
                &pc.item
            }
        };
        let mut style = TextStyle::from_props(&pc.rpr);
    if let Some(tc) = pc.rpr.theme_color.as_deref() {
        if let Some(c) = crate::props::theme_color(&doc.styles.theme.colors, tc) {
            style.color = Some(c);
        }
    }
        style.change = match (pc.change, doc.markup) {
            ("ins", crate::document::Markup::All) => 1,
            ("del", crate::document::Markup::All) => 2,
            _ => 0,
        };
        let (fa, fd) = line_metrics(doc, fonts, &pc.rpr, &style);
        match item {
            Item::Atom(t, n) => {
                if style.hidden || t.is_empty() {
                    if !style.hidden && *n > 0 {
                        // nothing to show, still a place for the caret
                        units.push(Unit { kind: UnitKind::Char('\u{200b}'), pos, width: 0.0, shaped: u32::MAX, idx: 0,
                            asc: fa, desc: fd, piece: pi as u32, obj: (0.0, 0.0), gen: false });
                    }
                    pos += n;
                    continue;
                }
                for sh in shape_text(fonts, &doc.styles, &pc.rpr, &style, t) {
                    let si = shaped.len() as u32;
                    let asc = (sh.font.ascent_pt(style.draw_size).max(0.0) + style.raise).max(0.0);
                    let desc = (sh.font.descent_pt(style.draw_size).max(0.0) - style.raise).max(0.0);
                    for (k, &c) in sh.text.iter().enumerate() {
                        units.push(Unit { kind: UnitKind::Char(c), pos, width: sh.widths[k], shaped: si, idx: k as u32,
                            asc, desc, piece: pi as u32, obj: (0.0, 0.0), gen: false });
                    }
                    shaped.push(sh);
                }
                pos += n;
            }
            Item::Text(t) => {
                if style.hidden {
                    pos += t.chars().count();
                    continue;
                }
                for sh in shape_text(fonts, &doc.styles, &pc.rpr, &style, t) {
                    let si = shaped.len() as u32;
                    let asc = (sh.font.ascent_pt(style.draw_size).max(0.0) + style.raise).max(0.0);
                    let desc = (sh.font.descent_pt(style.draw_size).max(0.0) - style.raise).max(0.0);
                    for (k, &c) in sh.text.iter().enumerate() {
                        units.push(Unit {
                            kind: UnitKind::Char(c),
                            pos,
                            width: sh.widths[k],
                            shaped: si,
                            idx: k as u32,
                            asc,
                            desc,
                            piece: pi as u32,
                            obj: (0.0, 0.0),
                            gen: false,
                        });
                        pos += 1;
                    }
                    shaped.push(sh);
                }
            }
            Item::Hidden(_) => {}
            Item::Math(node, display) => {
                let base = crate::math::Base { size: style.size, color: style.color.unwrap_or(0) };
                let boxes = if *display {
                    has_display = true;
                    vec![crate::math::layout(&doc.dom, fonts, *node, base, true, doc.settings.math_font.as_deref(),
                        Some(width - tw(props.ind_left.unwrap_or(0)) - tw(props.ind_right.unwrap_or(0))))]
                } else {
                    crate::math::layout_inline(&doc.dom, fonts, *node, base, doc.settings.math_font.as_deref())
                };
                // one unit per piece the line may break between, all at the
                // equation's place in the text
                for mb in boxes {
                    units.push(Unit { kind: UnitKind::Math, pos, width: mb.w, shaped: u32::MAX, idx: maths.len() as u32,
                        asc: mb.asc, desc: mb.desc, piece: pi as u32, obj: (mb.w, mb.asc + mb.desc), gen: false });
                    maths.push(Arc::new(mb));
                }
                pos += 1;
            }
            other => {
                let kind = match other {
                    Item::Tab => UnitKind::Tab,
                    Item::LineBreak => UnitKind::LineBreak,
                    Item::PageBreak => UnitKind::PageBreak,
                    Item::ColumnBreak => UnitKind::ColumnBreak,
                    Item::Anchor(_) => UnitKind::Anchor,
                    _ => UnitKind::Object,
                };
                let (w, h) = if let Item::Object(w, h, _) = other { (*w, *h) } else { (0.0, 0.0) };
                units.push(Unit {
                    kind,
                    pos,
                    width: w,
                    shaped: u32::MAX,
                    idx: 0,
                    asc: match kind { UnitKind::Object => h, UnitKind::Anchor => 0.0, _ => fa },
                    desc: match kind { UnitKind::Object | UnitKind::Anchor => 0.0, _ => fd },
                    piece: pi as u32,
                    obj: (w, h),
                    gen: false,
                });
                pos += 1;
            }
        }
    }
    let (ma, md) = line_metrics(doc, fonts, &mark_rpr, &mark_style);
    let left = tw(props.ind_left.unwrap_or(0));
    let right = tw(props.ind_right.unwrap_or(0));
    let first = tw(props.ind_first.unwrap_or(0));
    let before = if props.before_auto == Some(true) { 14.0 } else {
        props.before_lines.map(|l| l as f64 * 0.12).unwrap_or_else(|| tw(props.before.unwrap_or(0)))
    };
    let after = if props.after_auto == Some(true) { 14.0 } else {
        props.after_lines.map(|l| l as f64 * 0.12).unwrap_or_else(|| tw(props.after.unwrap_or(0)))
    };
    let mut props = props;
    if has_display {
        // display equations sit as their m:oMathPara says (centred)
        let dom = &doc.dom;
        let jc = dom.children_named(p, "m:oMathPara").next()
            .and_then(|mp| dom.child(mp, "m:oMathParaPr"))
            .and_then(|pr| dom.child(pr, "m:jc"))
            .and_then(|j| dom.attr(j, "m:val"))
            .unwrap_or("centerGroup");
        props.jc = Some(match jc {
            "left" => "left",
            "right" => "right",
            _ => "center",
        }.to_string());
    }
    let mut pl = ParaLayout {
        maths,
        node: p,
        props,
        units,
        shaped,
        lines: Vec::new(),
        before,
        after,
        left,
        right,
        first,
        width,
        text_len: pos,
        mark_style,
        pieces,
        label: label.cloned(),
        grid: grid_pitch,
        mark_metrics: (ma, md),
        mark_change: {
            let dom = &doc.dom;
            dom.child(p, "w:pPr").map_or(false, |pp| {
                (doc.show_fmt_changes && dom.child(pp, "w:pPrChange").is_some())
                    || dom.child(pp, "w:rPr").map_or(false, |r| dom.child(r, "w:ins").is_some() || dom.child(r, "w:del").is_some())
            })
        },
        label_shift: match label_jc.as_str() {
            "right" | "end" => -label_w,
            "center" => -label_w / 2.0,
            _ => 0.0,
        },
    };
    break_lines(doc, &mut pl, (ma, md));
    pl
}

/// Ascent and descent (points) a run's font gives a line.
fn line_metrics(doc: &Document, fonts: &mut FontCache, rpr: &RunProps, st: &TextStyle) -> (f64, f64) {
    let fam = crate::text::family_for(&doc.styles, rpr, 'a');
    let f = fonts.get(&fam, st.bold, st.italic);
    (f.ascent_pt(st.size), f.descent_pt(st.size))
}

fn break_opps(units: &[Unit]) -> Vec<u8> {
    // 0 = no break before unit i, 1 = allowed, 2 = mandatory
    let mut text = String::new();
    let mut byte_unit = Vec::new();
    for (i, u) in units.iter().enumerate() {
        let c = match u.kind {
            UnitKind::Char(c) => c,
            UnitKind::Tab => '\t',
            UnitKind::Object | UnitKind::Math => '\u{fffc}',
            // anchors don't take part in line breaking
            UnitKind::Anchor => continue,
            _ => '\n',
        };
        for _ in 0..c.len_utf8() {
            byte_unit.push(i);
        }
        text.push(c);
    }
    let mut opp = vec![0u8; units.len() + 1];
    for (b, o) in unicode_linebreak::linebreaks(&text) {
        let ui = if b >= byte_unit.len() { units.len() } else { byte_unit[b] };
        opp[ui] = match o {
            unicode_linebreak::BreakOpportunity::Mandatory => 2,
            unicode_linebreak::BreakOpportunity::Allowed => 1,
        };
    }
    // after a tab a line can always break
    for (i, u) in units.iter().enumerate() {
        if u.kind == UnitKind::Tab && opp[i + 1] == 0 {
            opp[i + 1] = 1;
        }
    }
    // never between a list number and the text it numbers
    for (i, u) in units.iter().enumerate() {
        if u.gen {
            opp[i + 1] = 0;
        }
    }
    opp
}

fn is_space(u: &Unit) -> bool {
    matches!(u.kind, UnitKind::Char(' ') | UnitKind::Char('\u{3000}'))
}

/// The tab stop after x (all in points from the margin).
fn next_tab(stops: &[TabStop], default_tab: f64, x: f64, hanging_at: Option<f64>) -> (f64, TabKind, char) {
    let eps = 0.01;
    let mut best: Option<(f64, TabKind, char)> = None;
    for t in stops {
        let p = tw(t.pos);
        if p > x + eps && t.kind != TabKind::Bar {
            best = Some((p, t.kind, t.leader));
            break;
        }
    }
    if let Some(h) = hanging_at {
        if h > x + eps && best.map(|b| h < b.0).unwrap_or(true) {
            return (h, TabKind::Left, ' ');
        }
    }
    if let Some(b) = best {
        return b;
    }
    // default stops, after the last custom stop
    let floor = stops.iter().filter(|t| t.kind != TabKind::Bar).map(|t| tw(t.pos)).fold(f64::MIN, f64::max).max(x);
    let n = (floor / default_tab).floor() + 1.0;
    let mut p = n * default_tab;
    if p <= x + eps {
        p += default_tab;
    }
    (p, TabKind::Left, ' ')
}

/// Where text can't go beside floating objects: for a line whose top is
/// `y` points below the paragraph's first line top and `h` high, the blocked
/// x ranges (relative to the text column) and the y where that changes.
pub type WrapFn<'a> = &'a dyn Fn(f64, f64) -> (Vec<(f64, f64)>, f64);

/// The narrowest gap beside a float text goes into.
const MIN_FRAGMENT: f64 = 18.0;

struct Breaker<'a> {
    opp: Vec<u8>,
    /// automatic hyphenation: the patterns, the zone (points) and whether
    /// words in capitals are left whole
    hyph: Option<(&'static crate::hyph::Patterns, f64, bool)>,
    /// hyphenated lines in a row so far, and the most allowed (0: any)
    hyph_run: std::cell::Cell<i32>,
    hyph_limit: i32,
    stops: Vec<TabStop>,
    default_tab: f64,
    hanging_at: Option<f64>,
    mark: (f64, f64),
    _p: std::marker::PhantomData<&'a ()>,
}

/// Fill one line from unit `start` between x0 and right_edge.
fn fill_line(pl: &ParaLayout, br: &Breaker, start: usize, x0: f64, right_edge: f64, first_line: bool,
             para_first: bool) -> (Line, bool) {
    let units = &pl.units;
    let n = units.len();
    let opp = &br.opp;
    let mut x = x0;
    let mut xs: Vec<f64> = Vec::new();
    let mut ws: Vec<f64> = Vec::new();
    let mut tabs: Vec<TabFill> = Vec::new();
    let mut i = start;
    let mut last_break: Option<usize> = None;
    let mut end = n;
    let mut ends_with = UnitKind::Char('\n');
    let mut forced = false;
    // a pending right/center/decimal tab: (unit index, stop, kind)
    let mut pending: Option<(usize, f64, TabKind)> = None;
    let mut hyphen = 0.0;
    while i < n {
        let u = &units[i];
        match u.kind {
            UnitKind::LineBreak | UnitKind::PageBreak | UnitKind::ColumnBreak => {
                xs.push(x);
                ws.push(0.0);
                end = i + 1;
                ends_with = u.kind;
                forced = true;
                break;
            }
            _ => {}
        }
        // finish a pending aligned tab before the next tab
        if u.kind == UnitKind::Tab {
            if let Some(pt) = pending.take() {
                settle_tab(pt, &mut xs, &mut ws, &mut x, start, &mut tabs);
            }
        }
        let mut w = u.width;
        if u.kind == UnitKind::Tab {
            let (stop, kind, leader) = next_tab(&br.stops, br.default_tab, x,
                                                if para_first { br.hanging_at } else { None });
            if stop > right_edge + 0.01 && x < right_edge {
                // no stop left in the line: up to the right indent
                w = (right_edge - x).max(0.0);
            } else if stop > right_edge + 0.01 {
                w = 0.0;
            } else {
                match kind {
                    TabKind::Left => w = stop - x,
                    _ => {
                        w = 0.0;
                        pending = Some((i, stop, kind));
                    }
                }
            }
            if leader != ' ' && (w > 0.0 || pending.map_or(false, |pt| pt.0 == i)) {
                // an aligned tab's leader gets its width when the tab settles
                tabs.push(TabFill { x, width: w, leader });
            }
        }
        let fits = x + w <= right_edge + 0.01;
        let after_label = i > start && units[i - 1].gen && !units[i].gen
            && units[start..i].iter().all(|v| v.gen);
        if !fits && !is_space(u) && i > start && !after_label {
            // a word that can be hyphenated breaks inside
            let may = br.hyph_limit <= 0 || br.hyph_run.get() < br.hyph_limit;
            if let Some(cut) = hyphen_cut(pl, br, start, i, last_break, &xs, &ws, x, right_edge).filter(|_| may) {
                end = cut.0;
                hyphen = cut.1;
                xs.truncate(end - start);
                ws.truncate(end - start);
                ends_with = units[end - 1].kind;
                break;
            }
            // break at the last opportunity, else before this unit
            let at = match last_break {
                Some(b) if b > start => b,
                _ => i,
            };
            end = at;
            xs.truncate(at - start);
            ws.truncate(at - start);
            ends_with = units[at - 1].kind;
            break;
        }
        xs.push(x);
        ws.push(w);
        x += w;
        if i + 1 <= n && opp[i + 1] >= 1 {
            last_break = Some(i + 1);
        }
        i += 1;
    }
    if i >= n && !forced {
        end = n;
    }
    if let Some(pt) = pending.take() {
        if pt.0 < end {
            settle_tab(pt, &mut xs, &mut ws, &mut x, start, &mut tabs);
        }
    }
    br.hyph_run.set(if hyphen > 0.0 { br.hyph_run.get() + 1 } else { 0 });
    // a line ending at a soft hyphen shows it
    if hyphen == 0.0 && end > start && end <= n && end < n {
        if units[end - 1].kind == UnitKind::Char('\u{ad}') {
            hyphen = hyphen_width(pl, end - 1);
        }
    }
    if end <= start && start < n {
        // a single unit wider than the line
        end = start + 1;
        xs = vec![x0];
        ws = vec![units[start].width];
    }
    let is_last = end >= n;
    let mut line = Line {
        start,
        end,
        pos_start: if start < n { units[start].pos } else { pl.text_len },
        pos_end: if end < n { units[end].pos } else { pl.text_len },
        height: 0.0,
        baseline: 0.0,
        skip: 0.0,
        adv: 0.0,
        xs,
        ws,
        ends_with: if is_last && !forced { UnitKind::Char('\n') } else { ends_with },
        tabs,
        hyphen,
    };
    align_line(pl, &mut line, is_last && !forced, x0, right_edge - hyphen);
    measure_line(pl, &mut line, br.mark, is_last);
    let _ = first_line;
    (line, forced)
}

/// The width of a hyphen in the font of unit `u`.
fn hyphen_width(pl: &ParaLayout, u: usize) -> f64 {
    let unit = &pl.units[u];
    if unit.shaped == u32::MAX {
        return 0.0;
    }
    let sh = &pl.shaped[unit.shaped as usize];
    sh.font.char_width('-', sh.style.size) * sh.style.scale + sh.style.spacing
}

/// Hyphenating the word that overflows at unit `i`: (break before unit,
/// hyphen width), when the patterns allow a break that fits.
#[allow(clippy::too_many_arguments)]
fn hyphen_cut(pl: &ParaLayout, br: &Breaker, start: usize, i: usize, last_break: Option<usize>, xs: &[f64],
              _ws: &[f64], x: f64, right_edge: f64) -> Option<(usize, f64)> {
    let (pats, zone, no_caps) = br.hyph?;
    let units = &pl.units;
    let letter = |k: usize| matches!(units[k].kind, UnitKind::Char(c) if c.is_alphabetic()) && !units[k].gen;
    let ws0 = last_break.filter(|&b| b > start).unwrap_or(start);
    // the word: letters from ws0 (after any leading punctuation) to its end
    let mut a = ws0;
    while a < i && !letter(a) {
        a += 1;
    }
    if a >= i || (a..i).any(|k| !letter(k)) {
        return None;
    }
    let mut e = i;
    while e < units.len() && letter(e) {
        e += 1;
    }
    let word: String = (a..e).map(|k| if let UnitKind::Char(c) = units[k].kind { c } else { ' ' }).collect();
    if word.chars().count() < 5 || (no_caps && word.chars().all(|c| c.is_uppercase())) {
        return None;
    }
    // only when moving the word down would leave more room than the zone
    let x_word = if a > start { xs[a - start] } else { x };
    if right_edge - x_word < zone && ws0 > start {
        return None;
    }
    let points = pats.points(&word);
    for &k in points.iter().rev() {
        let cut = a + k;
        if cut > i || cut <= start {
            continue;
        }
        let x_cut = if cut < i { xs[cut - start] } else { x };
        let hw = hyphen_width(pl, cut - 1);
        if x_cut + hw <= right_edge + 0.01 {
            return Some((cut, hw));
        }
    }
    None
}

fn empty_line(pl: &ParaLayout, mark: (f64, f64)) -> Line {
    let mut l = Line {
        start: pl.units.len(),
        end: pl.units.len(),
        pos_start: pl.text_len,
        pos_end: pl.text_len,
        height: 0.0,
        baseline: 0.0,
        skip: 0.0,
        adv: 0.0,
        xs: vec![],
        ws: vec![],
        ends_with: UnitKind::Char('\n'),
        tabs: vec![],
        hyphen: 0.0,
    };
    measure_line(pl, &mut l, mark, true);
    l
}

fn breaker<'a>(doc: &Document, pl: &ParaLayout, mark: (f64, f64)) -> Breaker<'a> {
    let hyph = if doc.settings.auto_hyphenation && !pl.props.suppress_hyphens.unwrap_or(false) {
        crate::hyph::patterns("en-US").map(|p| (p, tw(doc.settings.hyphenation_zone).max(0.0), doc.settings.no_hyphenate_caps))
    } else {
        None
    };
    Breaker {
        hyph,
        hyph_run: std::cell::Cell::new(0),
        hyph_limit: doc.settings.hyphen_limit,
        opp: break_opps(&pl.units),
        stops: pl.props.tab_stops(),
        default_tab: tw(doc.settings.default_tab).max(1.0),
        hanging_at: if pl.first < 0.0 { Some(pl.left) } else { None },
        mark,
        _p: std::marker::PhantomData,
    }
}

fn break_lines(doc: &Document, pl: &mut ParaLayout, mark: (f64, f64)) {
    let br = breaker(doc, pl, mark);
    let n = pl.units.len();
    let right_edge = pl.width - pl.right;
    let mut lines = Vec::new();
    let mut start = 0usize;
    let mut first_line = true;
    loop {
        let x0 = pl.left + if first_line { pl.first + pl.label_shift } else { 0.0 };
        let (mut line, forced) = fill_line(pl, &br, start, x0, right_edge, first_line, first_line);
        line.adv = line.height;
        let end = line.end;
        let ends_with = line.ends_with;
        lines.push(line);
        first_line = false;
        if end >= n {
            // a line break at the very end leaves an empty last line; a
            // page or column break keeps the paragraph mark beside it
            if forced && end == n && ends_with == UnitKind::LineBreak {
                let mut l = empty_line(pl, mark);
                l.adv = l.height;
                lines.push(l);
            }
            break;
        }
        start = end;
    }
    if lines.is_empty() {
        let mut l = empty_line(pl, mark);
        l.adv = l.height;
        lines.push(l);
    }
    pl.lines = lines;
}

/// Lines again, flowing around floating objects: `wrap` says where text
/// can't go. Lines beside an object can be split in pieces at the same
/// height (all but the last advance by nothing).
pub fn rewrap(doc: &Document, pl: &ParaLayout, wrap: WrapFn) -> ParaLayout {
    let mut out = ParaLayout { lines: Vec::new(), ..pl.clone() };
    let mark = pl.mark_metrics;
    let br = breaker(doc, &out, mark);
    let n = out.units.len();
    let left_ind = out.left;
    let right_edge = out.width - out.right;
    let mut lines: Vec<Line> = Vec::new();
    let mut start = 0usize;
    let mut first_line = true;
    let mut y = 0.0;
    let mut est = pl.lines.first().map(|l| l.height).unwrap_or(mark.0 + mark.1).max(1.0);
    let mut guard = 0;
    'rows: loop {
        guard += 1;
        // the free pieces of this row
        let mut skip = 0.0;
        let frags = loop {
            let (blocked, next_y) = wrap(y + skip, est);
            let lo = left_ind + if first_line { out.first.min(0.0) + out.label_shift.min(0.0) } else { 0.0 };
            let mut frags: Vec<(f64, f64)> = vec![(lo.min(left_ind), right_edge)];
            for (b0, b1) in &blocked {
                let mut nf = Vec::new();
                for (f0, f1) in frags {
                    if *b1 <= f0 || *b0 >= f1 {
                        nf.push((f0, f1));
                    } else {
                        if *b0 > f0 {
                            nf.push((f0, *b0));
                        }
                        if *b1 < f1 {
                            nf.push((*b1, f1));
                        }
                    }
                }
                frags = nf;
            }
            if blocked.is_empty() {
                break frags;
            }
            frags.retain(|(a, b)| b - a >= MIN_FRAGMENT);
            if !frags.is_empty() || next_y <= y + skip + 0.01 || skip > 4000.0 {
                if frags.is_empty() {
                    frags.push((left_ind, right_edge));
                }
                break frags;
            }
            skip = next_y - y;
        };
        let row_from = lines.len();
        let nf = frags.len();
        let mut done = false;
        for (fi, (f0, f1)) in frags.iter().enumerate() {
            let at_left = fi == 0 && *f0 <= left_ind + 0.01;
            let x0 = if at_left {
                left_ind + if first_line { out.first + out.label_shift } else { 0.0 }
            } else {
                f0.max(left_ind)
            };
            let (mut line, forced) = if start < n || (fi == 0 && lines.is_empty()) {
                fill_line(&out, &br, start, x0, *f1, first_line, first_line)
            } else {
                break;
            };
            first_line = false;
            line.skip = skip;
            let end = line.end;
            let ends_with = line.ends_with;
            lines.push(line);
            start = end;
            if end >= n {
                if forced && end == n && ends_with == UnitKind::LineBreak {
                    // the empty last line goes on the next row
                    finish_row(&mut lines, row_from, &mut y, &mut est);
                    let mut l = empty_line(&out, mark);
                    let (blocked, _) = wrap(y, l.height);
                    let mut x = left_ind;
                    for (b0, b1) in blocked {
                        if b0 <= x + 0.01 && b1 > x {
                            x = b1;
                        }
                    }
                    if x > left_ind {
                        l.xs.clear();
                    }
                    l.adv = l.height;
                    lines.push(l);
                    out.lines = lines;
                    return out;
                }
                done = true;
                break;
            }
            if forced {
                // a break ends the row
                break;
            }
            let _ = nf;
        }
        finish_row(&mut lines, row_from, &mut y, &mut est);
        if done || start >= n || guard > 100000 {
            break 'rows;
        }
    }
    if lines.is_empty() {
        let mut l = empty_line(&out, mark);
        l.adv = l.height;
        lines.push(l);
    }
    out.lines = lines;
    out
}

/// Give the pieces of a row one height and baseline; only the last advances.
fn finish_row(lines: &mut [Line], from: usize, y: &mut f64, est: &mut f64) {
    if from >= lines.len() {
        return;
    }
    let row = &mut lines[from..];
    let base = row.iter().map(|l| l.baseline).fold(0.0, f64::max);
    let below = row.iter().map(|l| l.height - l.baseline).fold(0.0, f64::max);
    let h = base + below;
    let skip = row[0].skip;
    let k = row.len();
    for (i, l) in row.iter_mut().enumerate() {
        l.height = h;
        l.baseline = base;
        l.skip = skip;
        l.adv = if i + 1 == k { skip + h } else { 0.0 };
    }
    *y += skip + h;
    *est = h.max(1.0);
}

fn settle_tab(pt: (usize, f64, TabKind), xs: &mut [f64], ws: &mut [f64], x: &mut f64, start: usize,
              tabs: &mut [TabFill]) {
    let (ti, stop, kind) = pt;
    let k = ti - start;
    if k >= xs.len() {
        return;
    }
    let tab_x = xs[k];
    // width of what follows the tab
    let after: f64 = ws[k + 1..].iter().sum();
    let target = match kind {
        TabKind::Right => stop - after,
        TabKind::Center => stop - after / 2.0,
        TabKind::Decimal => stop - after, // decimal: refined below
        _ => tab_x,
    };
    let w = (target - tab_x).max(0.0);
    ws[k] = w;
    for j in k + 1..xs.len() {
        xs[j] += w;
    }
    *x += w;
    if let Some(t) = tabs.iter_mut().find(|t| (t.x - tab_x).abs() < 0.001) {
        t.width = w;
    }
}

fn align_line(pl: &ParaLayout, line: &mut Line, last: bool, x0: f64, right_edge: f64) {
    let units = &pl.units;
    let jc = pl.props.jc.as_deref().unwrap_or("left");
    // width without trailing spaces
    let mut used_end = line.end;
    while used_end > line.start && is_space(&units[used_end - 1]) {
        used_end -= 1;
    }
    let used = if used_end > line.start {
        let k = used_end - 1 - line.start;
        line.xs[k] + line.ws[k]
    } else {
        x0
    };
    let free = right_edge - used;
    if free <= 0.0 {
        return;
    }
    let shift = match jc {
        "center" => free / 2.0,
        "right" | "end" => free,
        "both" | "distribute" | "lowKashida" | "mediumKashida" | "highKashida" | "thaiDistribute" => {
            if last && jc != "distribute" {
                0.0
            } else {
                // spread the room over the spaces after the last tab
                let mut from = line.start;
                for i in line.start..used_end {
                    if units[i].kind == UnitKind::Tab {
                        from = i + 1;
                    }
                }
                let spaces: Vec<usize> = (from..used_end).filter(|&i| is_space(&units[i])).collect();
                if !spaces.is_empty() {
                    let extra = free / spaces.len() as f64;
                    let mut add = 0.0;
                    for i in from..line.end {
                        let k = i - line.start;
                        line.xs[k] += add;
                        if spaces.contains(&i) {
                            line.ws[k] += extra;
                            add += extra;
                        }
                    }
                }
                0.0
            }
        }
        _ => 0.0,
    };
    if shift != 0.0 {
        for x in line.xs.iter_mut() {
            *x += shift;
        }
        for t in line.tabs.iter_mut() {
            t.x += shift;
        }
    }
}

fn measure_line(pl: &ParaLayout, line: &mut Line, mark: (f64, f64), last: bool) {
    // text ascent/descent, and the line's overall (objects included)
    let (mut ta, mut td): (f64, f64) = (0.0, 0.0);
    let (mut oa, mut od): (f64, f64) = (0.0, 0.0);
    let mut any_text = false;
    for u in &pl.units[line.start..line.end] {
        if u.kind == UnitKind::Object {
            oa = oa.max(u.asc);
            od = od.max(u.desc);
        } else {
            ta = ta.max(u.asc);
            td = td.max(u.desc);
            any_text = true;
        }
    }
    if !any_text || last {
        // the paragraph mark's font counts on the last line
        ta = ta.max(mark.0);
        td = td.max(mark.1);
    }
    let asc = ta.max(oa);
    let desc = td.max(od);
    let natural = asc + desc;
    let text_h = ta + td;
    let rule = pl.props.line_rule.as_deref().unwrap_or("auto");
    let val = pl.props.line.unwrap_or(240);
    let (h, base) = match rule {
        "exact" => {
            let h = tw(val.abs());
            (h, h - desc.min(h))
        }
        "atLeast" => {
            let h = natural.max(tw(val));
            (h, h - desc)
        }
        _ => {
            // multiples scale the font's height; pictures keep theirs
            let f = val as f64 / 240.0;
            let extra = text_h * (f - 1.0);
            if f >= 1.0 {
                (natural + extra, asc)
            } else {
                let h = (natural + extra).max(0.0);
                (h, (asc + extra).max(0.0))
            }
        }
    };
    let (h, base) = if pl.grid > 0.0 && rule != "exact" {
        // lines take whole grid pitches, the text centred in them
        let n = (h / pl.grid - 0.001).ceil().max(1.0);
        let gh = n * pl.grid;
        (gh, base + (gh - h) / 2.0)
    } else {
        (h, base)
    };
    line.height = h;
    line.baseline = base;
}

/// The shaped stretch and glyph range drawn for units [a, b) of one shaped
/// run (for rendering).
pub fn glyph_range(sh: &Shaped, a: u32, b: u32) -> (usize, usize) {
    let mut g0 = usize::MAX;
    let mut g1 = 0;
    for k in a..b {
        let (s, e) = sh.glyph_of[k as usize];
        if e > s {
            g0 = g0.min(s as usize);
            g1 = g1.max(e as usize);
        }
    }
    if g0 == usize::MAX {
        (0, 0)
    } else {
        (g0, g1)
    }
}

pub type FontRef = Arc<crate::fonts::Font>;
