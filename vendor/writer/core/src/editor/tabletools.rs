//! Table Layout commands: selecting a cell, row, column or the table,
//! Split Cells, Split Table, AutoFit to contents and Distribute Rows.

use super::{Editor, Pos, PropEdit, TBLPR_ORDER, TCPR_ORDER, TRPR_ORDER};
use crate::layout::UnitKind;
use crate::xml::NodeId;

impl Editor {
    fn paras_in(&self, tc: NodeId) -> Vec<NodeId> {
        let dom = &self.doc.dom;
        dom.children_named(tc, "w:p").collect()
    }

    fn cell_start(&self, tc: NodeId) -> Option<Pos> {
        self.paras_in(tc).first().map(|&p| Pos { para: p, off: 0 })
    }

    fn cell_end(&self, tc: NodeId) -> Option<Pos> {
        self.paras_in(tc).last().map(|&p| Pos { para: p, off: self.para_len(p) })
    }

    /// Table Layout > Select: "cell", "row", "column" or "table".
    pub fn select_table_part(&mut self, what: &str) -> bool {
        let Some((tbl, rows, cells)) = self.selected_cells() else { return false };
        let dom = &self.doc.dom;
        let all_rows: Vec<NodeId> = dom.children_named(tbl, "w:tr").collect();
        let (from, to) = match what {
            "cell" => {
                let (_, _, tc) = match self.cell_of(self.caret.para) {
                    Some(c) => c,
                    None => return false,
                };
                (tc, tc)
            }
            "row" => {
                let first = self.row_cells(rows[0]).first().map(|c| c.0);
                let last = self.row_cells(*rows.last().unwrap()).last().map(|c| c.0);
                match (first, last) {
                    (Some(a), Some(b)) => (a, b),
                    _ => return false,
                }
            }
            "column" => {
                let (_, g0, g1) = self.selected_cols().unwrap_or((tbl, 0, 1));
                let pick = |r: NodeId, g: usize| self.row_cells(r).into_iter().find(|c| c.1 <= g && g < c.2).map(|c| c.0);
                let a = all_rows.iter().find_map(|&r| pick(r, g0));
                let b = all_rows.iter().rev().find_map(|&r| pick(r, g1.saturating_sub(1).max(g0)));
                match (a, b) {
                    (Some(a), Some(b)) => (a, b),
                    _ => return false,
                }
            }
            _ => {
                let first = all_rows.first().and_then(|&r| self.row_cells(r).first().map(|c| c.0));
                let last = all_rows.last().and_then(|&r| self.row_cells(r).last().map(|c| c.0));
                match (first, last) {
                    (Some(a), Some(b)) => (a, b),
                    _ => return false,
                }
            }
        };
        let _ = cells;
        let (Some(a), Some(b)) = (self.cell_start(from), self.cell_end(to)) else { return false };
        self.move_to(a, false, false);
        self.move_to(b, true, false);
        true
    }

    fn grid_of(&self, tbl: NodeId) -> Vec<i32> {
        let dom = &self.doc.dom;
        dom.child(tbl, "w:tblGrid")
            .map(|g| dom.children_named(g, "w:gridCol").map(|c| crate::props::int_attr(dom, c, "w:w").unwrap_or(0)).collect())
            .unwrap_or_default()
    }

    fn write_grid(&mut self, tbl: NodeId, grid: &[i32]) {
        let dom = &mut self.doc.dom;
        let g = match dom.child(tbl, "w:tblGrid") {
            Some(g) => g,
            None => {
                let g = dom.new_element("w:tblGrid", &[]);
                let at = dom.child(tbl, "w:tblPr").and_then(|p| dom.index_in_parent(p)).map(|i| i + 1).unwrap_or(0);
                dom.insert(tbl, at, g);
                g
            }
        };
        for c in dom.children(g).to_vec() {
            dom.detach(c);
        }
        for w in grid {
            let c = dom.new_element("w:gridCol", &[("w:w", &w.to_string())]);
            dom.append(g, c);
        }
    }

    fn set_span(&mut self, tc: NodeId, span: usize, width: i32) {
        let mut edits = vec![PropEdit::set("w:tcW", &[("w:w", &width.to_string()), ("w:type", "dxa")])];
        edits.push(if span > 1 { PropEdit::set("w:gridSpan", &[("w:val", &span.to_string())]) } else { PropEdit::remove("w:gridSpan") });
        self.apply_to_child(tc, "w:tcPr", &edits, TCPR_ORDER, true);
    }

    /// A new empty cell like `like` (its properties, an empty paragraph
    /// with the first paragraph's formatting).
    fn blank_cell_like(&mut self, like: NodeId, vmerge: Option<&str>) -> NodeId {
        let dom = &mut self.doc.dom;
        let tc = dom.new_element("w:tc", &[]);
        if let Some(pr) = dom.child(like, "w:tcPr") {
            let c = dom.clone_node(pr);
            if let Some(v) = dom.child(c, "w:vMerge") {
                dom.detach(v);
            }
            dom.append(tc, c);
        }
        let p = dom.new_element("w:p", &[]);
        let fp = dom.children_named(like, "w:p").next();
        if let Some(fp) = fp {
            if let Some(ppr) = dom.child(fp, "w:pPr") {
                let c = dom.clone_node(ppr);
                dom.append(p, c);
            }
        }
        dom.append(tc, p);
        if let Some(v) = vmerge {
            let mut attrs: Vec<(&str, &str)> = Vec::new();
            if v == "restart" {
                attrs.push(("w:val", "restart"));
            }
            let _ = attrs;
            self.apply_to_child(tc, "w:tcPr", &[PropEdit {
                name: "w:vMerge".into(),
                attrs: Some(if v == "restart" { vec![("w:val".into(), "restart".into())] } else { vec![] }),
            }], TCPR_ORDER, true);
        }
        tc
    }

    /// Split Cells: each selected cell into `cols` columns and (for a
    /// selection in one row) `rows` rows.
    pub fn split_cells(&mut self, cols: usize, rows: usize) -> bool {
        let Some((tbl, sel_rows, cells)) = self.selected_cells() else { return false };
        let cols = cols.clamp(1, 63);
        let rows = rows.clamp(1, 63);
        if cols == 1 && rows == 1 {
            return false;
        }
        self.begin();
        // ---- columns: new grid boundaries inside each split cell
        let mut new_cells: Vec<Vec<NodeId>> = Vec::new();
        if cols > 1 {
            let grid = self.grid_of(tbl);
            let mut bounds: Vec<i32> = vec![0];
            for w in &grid {
                bounds.push(bounds.last().unwrap() + w);
            }
            let all_rows: Vec<NodeId> = self.doc.dom.children_named(tbl, "w:tr").collect();
            // every row's cells with their old ranges
            let layout: Vec<(NodeId, Vec<(NodeId, usize, usize)>)> = all_rows.iter().map(|&r| (r, self.row_cells(r))).collect();
            let mut cuts: Vec<(NodeId, Vec<i32>)> = Vec::new();
            let mut points = bounds.clone();
            for &(r, ref cs) in &layout {
                let _ = r;
                for &(tc, a, b) in cs {
                    if !cells.contains(&tc) || b > bounds.len() - 1 {
                        continue;
                    }
                    let (x0, x1) = (bounds[a], bounds[b]);
                    let ps: Vec<i32> = (0..=cols).map(|k| x0 + ((x1 - x0) as f64 * k as f64 / cols as f64).round() as i32).collect();
                    points.extend(ps.iter().copied());
                    cuts.push((tc, ps));
                }
            }
            points.sort();
            points.dedup();
            let idx = |x: i32| points.iter().position(|&p| p == x).unwrap_or(0);
            let new_grid: Vec<i32> = points.windows(2).map(|w| w[1] - w[0]).collect();
            self.write_grid(tbl, &new_grid);
            for (r, cs) in layout {
                // gridBefore follows the new grid
                let dom = &self.doc.dom;
                let before = dom.child(r, "w:trPr").and_then(|t| dom.child(t, "w:gridBefore"))
                    .and_then(|n| crate::props::int_attr(dom, n, "w:val")).unwrap_or(0).max(0) as usize;
                if before > 0 && before < bounds.len() {
                    let nb = idx(bounds[before]);
                    self.apply_to_child(r, "w:trPr", &[PropEdit::set("w:gridBefore", &[("w:val", &nb.to_string())])], TRPR_ORDER, true);
                }
                for (tc, a, b) in cs {
                    if b >= bounds.len() {
                        continue;
                    }
                    if let Some((_, ps)) = cuts.iter().find(|(c, _)| *c == tc) {
                        let mut made = vec![tc];
                        let at = self.doc.dom.index_in_parent(tc).unwrap();
                        for k in 0..cols {
                            let (s, e) = (idx(ps[k]), idx(ps[k + 1]));
                            let target = if k == 0 {
                                tc
                            } else {
                                let n = self.blank_cell_like(tc, None);
                                self.doc.dom.insert(r, at + k, n);
                                made.push(n);
                                n
                            };
                            self.set_span(target, e - s, ps[k + 1] - ps[k]);
                        }
                        new_cells.push(made);
                    } else {
                        let (s, e) = (idx(bounds[a]), idx(bounds[b]));
                        self.set_span(tc, e - s, bounds[b] - bounds[a]);
                    }
                }
            }
        } else {
            for &c in &cells {
                new_cells.push(vec![c]);
            }
        }
        // ---- rows (one row selected): new rows below, the other cells
        // merged down across them
        if rows > 1 && sel_rows.len() == 1 {
            let r = sel_rows[0];
            let split: Vec<NodeId> = new_cells.iter().flatten().copied().collect();
            let row_cells: Vec<NodeId> = self.doc.dom.children_named(r, "w:tc").collect();
            for &tc in &row_cells {
                if !split.contains(&tc) {
                    let has = self.doc.dom.child(tc, "w:tcPr").and_then(|p| self.doc.dom.child(p, "w:vMerge")).is_some();
                    if !has {
                        self.apply_to_child(tc, "w:tcPr", &[PropEdit::set("w:vMerge", &[("w:val", "restart")])], TCPR_ORDER, true);
                    }
                }
            }
            let at = self.doc.dom.index_in_parent(r).unwrap();
            for k in 1..rows {
                let dom = &mut self.doc.dom;
                let nr = dom.new_element("w:tr", &[]);
                if let Some(tp) = dom.child(r, "w:trPr") {
                    let c = dom.clone_node(tp);
                    dom.append(nr, c);
                }
                for &tc in &row_cells {
                    let n = if split.contains(&tc) {
                        self.blank_cell_like(tc, None)
                    } else {
                        self.blank_cell_like(tc, Some("continue"))
                    };
                    self.doc.dom.append(nr, n);
                }
                self.doc.dom.insert(tbl, at + k, nr);
            }
        }
        if let Some(p) = new_cells.first().and_then(|c| c.first()).and_then(|&tc| self.paras_in(tc).first().copied()) {
            self.caret = Pos { para: p, off: 0 };
            self.anchor = self.caret;
        }
        self.commit("Split Cells", false);
        true
    }

    /// Split Table: the rows from the caret's on become a table of their
    /// own after an empty paragraph (at the first row: a paragraph goes
    /// before the table).
    pub fn split_table(&mut self) -> bool {
        let Some((tbl, tr, _)) = self.cell_of(self.caret.para) else { return false };
        self.begin();
        let dom = &mut self.doc.dom;
        let rows: Vec<NodeId> = dom.children_named(tbl, "w:tr").collect();
        let ri = rows.iter().position(|&r| r == tr).unwrap_or(0);
        let parent = dom.parent(tbl).unwrap();
        let ti = dom.index_in_parent(tbl).unwrap();
        let p = dom.new_element("w:p", &[]);
        if ri == 0 {
            dom.insert(parent, ti, p);
        } else {
            let nt = dom.new_element("w:tbl", &[]);
            for name in ["w:tblPr", "w:tblGrid"] {
                if let Some(x) = dom.child(tbl, name) {
                    let c = dom.clone_node(x);
                    dom.append(nt, c);
                }
            }
            for &r in &rows[ri..] {
                dom.detach(r);
                dom.append(nt, r);
            }
            dom.insert(parent, ti + 1, p);
            dom.insert(parent, ti + 2, nt);
        }
        self.caret = Pos { para: p, off: 0 };
        self.anchor = self.caret;
        self.commit("Split Table", false);
        true
    }

    /// The widths a paragraph wants: (widest word, whole lines unwrapped),
    /// in points.
    fn natural_widths(&self, p: NodeId) -> (f64, f64) {
        let Some(pl) = self.para_layout(p) else { return (0.0, 0.0) };
        let ind = (pl.left + pl.right).max(0.0) + pl.first.max(0.0);
        let (mut word, mut line, mut max_word, mut max_line) = (0.0f64, 0.0f64, 0.0f64, 0.0f64);
        for u in &pl.units {
            match u.kind {
                UnitKind::LineBreak | UnitKind::PageBreak | UnitKind::ColumnBreak => {
                    max_line = max_line.max(line);
                    max_word = max_word.max(word);
                    line = 0.0;
                    word = 0.0;
                }
                UnitKind::Char(c) if c.is_whitespace() => {
                    max_word = max_word.max(word);
                    word = 0.0;
                    line += u.width;
                }
                _ => {
                    word += u.width;
                    line += u.width;
                }
            }
        }
        max_word = max_word.max(word);
        max_line = max_line.max(line);
        (max_word + ind, max_line + ind)
    }

    /// AutoFit > AutoFit Contents: columns as wide as what's in them (as
    /// far as the page allows).
    pub fn autofit_contents(&mut self) -> bool {
        let Some((tbl, _, _)) = self.cell_of(self.caret.para) else { return false };
        let grid = self.grid_of(tbl);
        let n = grid.len();
        if n == 0 {
            return false;
        }
        let sec = self.current_section();
        let avail = self.doc.sections.get(sec).map(|s| s.page_w - s.left - s.right - s.gutter).unwrap_or(9360) as f64 / 20.0;
        let margins = 10.8;
        let mut tmin = vec![0.0f64; n];
        let mut tmax = vec![0.0f64; n];
        let rows: Vec<NodeId> = self.doc.dom.children_named(tbl, "w:tr").collect();
        for r in rows {
            for (tc, a, b) in self.row_cells(r) {
                if b - a != 1 || a >= n {
                    continue;
                }
                for p in self.paras_in(tc) {
                    let (w0, w1) = self.natural_widths(p);
                    tmin[a] = tmin[a].max(w0);
                    tmax[a] = tmax[a].max(w1);
                }
            }
        }
        for i in 0..n {
            if tmax[i] <= 0.0 {
                tmin[i] = 7.0;
                tmax[i] = 7.0;
            }
            tmin[i] += margins + 1.0;
            tmax[i] += margins + 1.0;
        }
        let (smin, smax): (f64, f64) = (tmin.iter().sum(), tmax.iter().sum());
        let widths: Vec<f64> = if smax <= avail {
            tmax.clone()
        } else if smin >= avail {
            tmin.iter().map(|w| w * avail / smin).collect()
        } else {
            let k = (avail - smin) / (smax - smin);
            tmin.iter().zip(&tmax).map(|(a, b)| a + (b - a) * k).collect()
        };
        let tw: Vec<i32> = widths.iter().map(|w| (w * 20.0).round() as i32).collect();
        self.begin_group("AutoFit Contents");
        self.set_grid_widths(&tw, "AutoFit Contents");
        self.begin();
        self.apply_to_child(tbl, "w:tblPr", &[PropEdit::set("w:tblW", &[("w:w", "0"), ("w:type", "auto")]),
                                              PropEdit::remove("w:tblLayout")], TBLPR_ORDER, true);
        self.commit("AutoFit Contents", false);
        self.end_group();
        true
    }

    /// Distribute Rows: the selected rows (or every row) the same height.
    pub fn distribute_rows(&mut self) -> bool {
        let Some((tbl, mut rows, _)) = self.selected_cells() else { return false };
        if rows.len() < 2 {
            rows = self.doc.dom.children_named(tbl, "w:tr").collect();
        }
        let mut hs: Vec<f64> = Vec::new();
        for &r in &rows {
            let mut h = 0.0f64;
            for pg in &self.layout.pages {
                for c in &pg.cells {
                    if self.doc.dom.parent(c.cell) == Some(r) {
                        h = h.max(c.h);
                    }
                }
            }
            if h > 0.0 {
                hs.push(h);
            }
        }
        if hs.is_empty() {
            return false;
        }
        let avg = hs.iter().sum::<f64>() / hs.len() as f64;
        let v = ((avg * 20.0).round() as i32).to_string();
        self.begin();
        for r in rows {
            self.apply_to_child(r, "w:trPr", &[PropEdit::set("w:trHeight", &[("w:val", &v), ("w:hRule", "atLeast")])], TRPR_ORDER, true);
        }
        self.commit("Distribute Rows", false);
        true
    }

    /// Text Direction: across, then top to bottom, then bottom to top.
    pub fn cycle_text_direction(&mut self) -> bool {
        let Some((_, _, cells)) = self.selected_cells() else { return false };
        let dom = &self.doc.dom;
        let cur = cells.first().and_then(|&c| dom.child(c, "w:tcPr")).and_then(|p| dom.child(p, "w:textDirection"))
            .and_then(|n| dom.attr(n, "w:val")).unwrap_or("lrTb").to_string();
        let next = match cur.as_str() {
            "tbRl" | "tbRlV" => Some("btLr"),
            "btLr" => None,
            _ => Some("tbRl"),
        };
        self.begin();
        for c in cells {
            let e = match next {
                Some(v) => PropEdit::set("w:textDirection", &[("w:val", v)]),
                None => PropEdit::remove("w:textDirection"),
            };
            self.apply_to_child(c, "w:tcPr", &[e], TCPR_ORDER, true);
        }
        self.commit("Text Direction", false);
        true
    }
}
