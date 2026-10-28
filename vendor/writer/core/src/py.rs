//! Python binding: the editor as the GTK view drives it.

use crate::document::Document;
use crate::editor::{Editor, Pos, PropEdit};
use crate::fonts::FontCache;
use pyo3::exceptions::{PyIOError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict};

#[pyclass(name = "Editor", unsendable)]
pub struct PyEditor {
    ed: Editor,
    /// bumped whenever the pages' content changes (the view's cache key)
    version: u64,
}

fn err(e: String) -> PyErr {
    PyIOError::new_err(e)
}

impl PyEditor {
    fn touched(&mut self) {
        self.version += 1;
    }
}

#[pymethods]
impl PyEditor {
    #[staticmethod]
    fn open(path: &str) -> PyResult<PyEditor> {
        let doc = Document::open_path(path).map_err(|e| err(e.0))?;
        Ok(PyEditor { ed: Editor::new(doc, FontCache::new()), version: 1 })
    }

    #[staticmethod]
    fn from_bytes(data: &[u8]) -> PyResult<PyEditor> {
        let doc = Document::open(data).map_err(|e| err(e.0))?;
        Ok(PyEditor { ed: Editor::new(doc, FontCache::new()), version: 1 })
    }

    #[getter]
    fn version(&self) -> u64 {
        self.version
    }

    #[getter]
    fn modified(&self) -> bool {
        self.ed.modified
    }

    fn mark_saved(&mut self) {
        self.ed.modified = false;
    }

    fn save(&mut self, path: &str) -> PyResult<()> {
        self.ed.save(path).map_err(err)
    }

    fn to_bytes<'py>(&mut self, py: Python<'py>) -> PyResult<Bound<'py, PyBytes>> {
        let b = self.ed.doc.write().map_err(|e| err(e.0))?;
        Ok(PyBytes::new_bound(py, &b))
    }

    fn export_pdf(&mut self, path: &str) -> PyResult<()> {
        self.ed.export_pdf(path).map_err(err)
    }

    #[pyo3(signature = (path, pages=Vec::new(), bookmarks=true, title=String::new(), author=String::new(), subject=String::new(), keywords=String::new()))]
    #[allow(clippy::too_many_arguments)]
    fn export_pdf_opts(&mut self, path: &str, pages: Vec<usize>, bookmarks: bool, title: String, author: String,
                       subject: String, keywords: String) -> PyResult<()> {
        self.ed.export_pdf_opts(path, pages, bookmarks, [title, author, subject, keywords]).map_err(err)
    }

    // ---------------------------------------------------------- pages
    fn page_count(&self) -> usize {
        self.ed.page_count()
    }

    fn page_size(&self, i: usize) -> (f64, f64) {
        self.ed.page_size(i)
    }

    /// Margins of a page (top, right, bottom, left) in points.
    fn page_margins(&self, i: usize) -> (f64, f64, f64, f64) {
        self.ed
            .layout
            .pages
            .get(i)
            .map(|p| (p.top, p.right, p.bottom, p.left))
            .unwrap_or((72.0, 72.0, 72.0, 72.0))
    }

    /// Render page i at `scale` pixels per point (no caret or selection):
    /// (width, height, stride, ARGB32 bytes).
    #[pyo3(signature = (i, scale, gridlines=true, marks=false))]
    fn render_page<'py>(&mut self, py: Python<'py>, i: usize, scale: f64, gridlines: bool, marks: bool)
                        -> PyResult<(i32, i32, i32, Bound<'py, PyBytes>)> {
        let sect_breaks = if marks { self.ed.section_break_labels() } else { Default::default() };
        let ov = crate::render::Overlay { gridlines, marks, sect_breaks, ..Default::default() };
        let ed = &mut self.ed;
        let surf = crate::render::render_page_image(&mut ed.renderer, &ed.layout, i, &mut ed.fonts, scale, &ov)
            .ok_or_else(|| PyValueError::new_err("no such page"))?;
        let (w, h, stride) = (surf.width(), surf.height(), surf.stride());
        let mut surf = surf;
        let data = surf.data().map_err(|e| err(e.to_string()))?;
        Ok((w, h, stride, PyBytes::new_bound(py, &data)))
    }

    // --------------------------------------------------------- caret
    /// (page, x, y, height) of the caret in points.
    fn caret_rect(&self) -> Option<(usize, f64, f64, f64)> {
        self.ed.caret_rect(self.ed.caret)
    }

    fn selection_rects(&self) -> Vec<(usize, f64, f64, f64, f64)> {
        self.ed.selection_rects()
    }

    fn has_selection(&self) -> bool {
        self.ed.has_selection()
    }

    /// Click at a point of a page; `extend` (shift) grows the selection.
    #[pyo3(signature = (page, x, y, extend=false))]
    fn click(&mut self, page: usize, x: f64, y: f64, extend: bool) -> bool {
        match self.ed.hit(page, x, y) {
            Some(p) => {
                self.ed.move_to(p, extend, false);
                true
            }
            None => false,
        }
    }

    fn select_word_at(&mut self, page: usize, x: f64, y: f64) {
        if let Some(p) = self.ed.hit(page, x, y) {
            let (a, b) = self.ed.word_at(p);
            self.ed.move_to(a, false, false);
            self.ed.move_to(b, true, false);
        }
    }

    fn select_paragraph_at(&mut self, page: usize, x: f64, y: f64) {
        if let Some(p) = self.ed.hit(page, x, y) {
            let len = self.ed.para_layout(p.para).map(|l| l.text_len).unwrap_or(0);
            self.ed.move_to(Pos { para: p.para, off: 0 }, false, false);
            let end = self.ed.next_pos(Pos { para: p.para, off: len });
            self.ed.move_to(if end.para != p.para { end } else { Pos { para: p.para, off: len } }, true, false);
        }
    }

    fn select_all(&mut self) {
        self.ed.select_all();
    }

    /// Caret movement: left right up down word_left word_right home end
    /// doc_start doc_end para_up para_down.
    #[pyo3(signature = (how, extend=false))]
    fn move_caret(&mut self, how: &str, extend: bool) {
        let ed = &mut self.ed;
        let c = ed.caret;
        // a collapsing left/right goes to the selection's edge
        if !extend && ed.has_selection() && (how == "left" || how == "right") {
            let (a, b) = ed.selection();
            ed.move_to(if how == "left" { a } else { b }, false, false);
            return;
        }
        let (p, keep_goal) = match how {
            "left" => (ed.prev_pos(c), false),
            "right" => (ed.next_pos(c), false),
            "word_left" => (ed.prev_word(c), false),
            "word_right" => (ed.next_word(c), false),
            "up" => (ed.line_move(c, false), true),
            "down" => (ed.line_move(c, true), true),
            "home" => (ed.line_start(c), false),
            "end" => (ed.line_end(c), false),
            "doc_start" => (ed.doc_start(), false),
            "doc_end" => (ed.doc_end(), false),
            "para_up" => {
                if c.off > 0 {
                    (Pos { para: c.para, off: 0 }, false)
                } else {
                    let p = ed.prev_pos(c);
                    (Pos { para: p.para, off: 0 }, false)
                }
            }
            "para_down" => {
                let len = ed.para_layout(c.para).map(|l| l.text_len).unwrap_or(0);
                let p = ed.next_pos(Pos { para: c.para, off: len });
                (if p.para != c.para { p } else { Pos { para: c.para, off: len } }, false)
            }
            _ => (c, false),
        };
        ed.move_to(p, extend, keep_goal);
    }

    /// Move by a vertical distance (page up/down), in points.
    #[pyo3(signature = (dy, extend=false))]
    fn move_by(&mut self, dy: f64, extend: bool) {
        let ed = &mut self.ed;
        if let Some((pg, x, y, h)) = ed.caret_rect(ed.caret) {
            let mut page = pg;
            let mut ny = y + h / 2.0 + dy;
            // walk pages
            loop {
                let ph = ed.page_size(page).1;
                if ny > ph && page + 1 < ed.page_count() {
                    ny -= ph + 10.0;
                    page += 1;
                } else if ny < 0.0 && page > 0 {
                    page -= 1;
                    ny += ed.page_size(page).1 + 10.0;
                } else {
                    break;
                }
            }
            if let Some(p) = ed.hit(page, x, ny) {
                ed.move_to(p, extend, true);
            }
        }
    }

    // --------------------------------------------------------- edits
    fn type_text(&mut self, text: &str) {
        self.ed.type_text(text);
        self.touched();
    }

    #[pyo3(signature = (forward, word=false))]
    fn delete(&mut self, forward: bool, word: bool) {
        self.ed.delete(forward, word);
        self.touched();
    }

    fn undo(&mut self) {
        self.ed.undo();
        self.touched();
    }

    fn redo(&mut self) {
        self.ed.redo();
        self.touched();
    }

    fn can_undo(&self) -> bool {
        self.ed.can_undo()
    }

    fn can_redo(&self) -> bool {
        self.ed.can_redo()
    }

    fn selected_text(&self) -> String {
        self.ed.selected_text()
    }

    /// Bold/italic/... : "w:b", "w:i", "w:strike", "w:caps", "w:smallCaps"
    fn toggle(&mut self, which: &str) {
        let label = match which {
            "w:b" => "Bold",
            "w:i" => "Italic",
            "w:strike" => "Strikethrough",
            _ => "Format",
        };
        self.ed.toggle(which, label);
        self.touched();
    }

    /// Underline kind ("single", "double", "none"...).
    fn set_underline(&mut self, kind: &str) {
        let e = if kind == "none" { PropEdit::remove("w:u") } else { PropEdit::set("w:u", &[("w:val", kind)]) };
        self.ed.format_runs(&[e], "Underline");
        self.touched();
    }

    fn set_font(&mut self, family: &str) {
        let e = PropEdit::set("w:rFonts", &[("w:ascii", family), ("w:hAnsi", family), ("w:cs", family), ("w:eastAsia", family)]);
        self.ed.format_runs(&[e], "Font");
        self.touched();
    }

    fn set_size(&mut self, pt: f64) {
        let hp = ((pt * 2.0).round() as i64).clamp(2, 3276).to_string();
        self.ed.format_runs(&[val_named("w:sz", &hp), val_named("w:szCs", &hp)], "Font Size");
        self.touched();
    }

    /// Text colour as RRGGBB, or "auto".
    fn set_color(&mut self, rgb: &str) {
        self.ed.format_runs(&[val_named("w:color", rgb)], "Font Color");
        self.touched();
    }

    /// Highlight colour name ("yellow"...), or "none".
    fn set_highlight(&mut self, name: &str) {
        let e = if name == "none" { PropEdit::remove("w:highlight") } else { val_named("w:highlight", name) };
        self.ed.format_runs(&[e], "Highlight");
        self.touched();
    }

    /// "superscript", "subscript" or "baseline".
    fn set_vert_align(&mut self, v: &str) {
        let cur = self.ed.current_run_props().vert_align.unwrap_or_default();
        let e = if v == "baseline" || cur == v { PropEdit::remove("w:vertAlign") } else { val_named("w:vertAlign", v) };
        self.ed.format_runs(&[e], "Font");
        self.touched();
    }

    /// Clear direct character formatting.
    fn clear_formatting(&mut self) {
        let names = ["w:rFonts", "w:b", "w:bCs", "w:i", "w:iCs", "w:caps", "w:smallCaps", "w:strike", "w:dstrike",
            "w:color", "w:spacing", "w:sz", "w:szCs", "w:highlight", "w:u", "w:vertAlign", "w:shd", "w:rStyle"];
        let edits: Vec<PropEdit> = names.iter().map(|n| PropEdit::remove(n)).collect();
        self.ed.format_runs(&edits, "Clear Formatting");
        self.touched();
    }

    /// Paragraph alignment: left center right both.
    fn set_align(&mut self, jc: &str) {
        let e = if jc == "left" { PropEdit::remove("w:jc") } else { val_named("w:jc", jc) };
        self.ed.format_paras(&[e], "Paragraph Alignment");
        self.touched();
    }

    /// Paragraph style by id (None: the default style).
    fn set_style(&mut self, id: &str) {
        let default = self.ed.doc.styles.default_para.clone();
        let e = if Some(id.to_string()) == default { PropEdit::remove("w:pStyle") } else { val_named("w:pStyle", id) };
        self.ed.format_paras(&[e], "Style");
        self.touched();
    }

    /// Line spacing: rule ("auto", "exact", "atLeast") and value in 240ths
    /// of a line (auto) or twips.
    fn set_line_spacing(&mut self, rule: &str, value: i64) {
        let v = value.to_string();
        self.ed.format_paras_attrs("w:spacing", &[("w:line", Some(&v)), ("w:lineRule", Some(rule))], "Line Spacing");
        self.touched();
    }

    /// Space before/after in twips (None leaves it).
    #[pyo3(signature = (before=None, after=None))]
    fn set_para_spacing(&mut self, before: Option<i64>, after: Option<i64>) {
        let b = before.map(|v| v.to_string());
        let a = after.map(|v| v.to_string());
        let mut attrs: Vec<(&str, Option<&str>)> = Vec::new();
        if let Some(b) = &b {
            attrs.push(("w:before", Some(b)));
            attrs.push(("w:beforeAutospacing", None));
        }
        if let Some(a) = &a {
            attrs.push(("w:after", Some(a)));
            attrs.push(("w:afterAutospacing", None));
        }
        self.ed.format_paras_attrs("w:spacing", &attrs, "Paragraph Spacing");
        self.touched();
    }

    /// Indents in twips (left, first-line; negative first = hanging).
    #[pyo3(signature = (left=None, right=None, first=None))]
    fn set_indent(&mut self, left: Option<i64>, right: Option<i64>, first: Option<i64>) {
        let l = left.map(|v| v.to_string());
        let r = right.map(|v| v.to_string());
        let mut attrs: Vec<(&str, Option<&str>)> = Vec::new();
        if let Some(l) = &l {
            attrs.push(("w:left", Some(l)));
            attrs.push(("w:start", None));
        }
        if let Some(r) = &r {
            attrs.push(("w:right", Some(r)));
            attrs.push(("w:end", None));
        }
        let f = first.map(|v| v.abs().to_string());
        if let (Some(first), Some(fs)) = (first, &f) {
            if first < 0 {
                attrs.push(("w:hanging", Some(fs)));
                attrs.push(("w:firstLine", None));
            } else {
                attrs.push(("w:firstLine", Some(fs)));
                attrs.push(("w:hanging", None));
            }
        }
        self.ed.format_paras_attrs("w:ind", &attrs, "Indent");
        self.touched();
    }

    // ------------------------------------------------------------ tables
    fn insert_table(&mut self, rows: usize, cols: usize) {
        self.ed.insert_table(rows, cols);
        self.touched();
    }

    /// Table Layout commands: insert_rows_above/below, insert_cols_left/right,
    /// delete_rows, delete_cols, delete_table, merge.
    fn table_command(&mut self, what: &str) -> bool {
        let ok = match what {
            "insert_rows_above" => self.ed.insert_rows(false),
            "insert_rows_below" => self.ed.insert_rows(true),
            "insert_cols_left" => self.ed.insert_cols(false),
            "insert_cols_right" => self.ed.insert_cols(true),
            "delete_rows" => self.ed.delete_rows(),
            "delete_cols" => self.ed.delete_cols(),
            "delete_table" => self.ed.delete_table(),
            "merge" => self.ed.merge_cells(),
            _ => false,
        };
        if ok {
            self.touched();
        }
        ok
    }

    /// Table Layout > Select: "cell", "row", "column", "table".
    fn select_table_part(&mut self, what: &str) -> bool {
        self.ed.select_table_part(what)
    }

    #[pyo3(signature = (cols, rows=1))]
    fn split_cells(&mut self, cols: usize, rows: usize) -> bool {
        let ok = self.ed.split_cells(cols, rows);
        self.touched();
        ok
    }

    fn split_table(&mut self) -> bool {
        let ok = self.ed.split_table();
        self.touched();
        ok
    }

    fn autofit_contents(&mut self) -> bool {
        let ok = self.ed.autofit_contents();
        self.touched();
        ok
    }

    fn cycle_text_direction(&mut self) -> bool {
        let ok = self.ed.cycle_text_direction();
        self.touched();
        ok
    }

    fn distribute_rows(&mut self) -> bool {
        let ok = self.ed.distribute_rows();
        self.touched();
        ok
    }

    /// Table Properties' current values (twips; widths as (value, type)).
    fn table_props<'py>(&self, py: Python<'py>) -> PyResult<Option<Bound<'py, PyDict>>> {
        let Some((tbl, tr, tc)) = self.ed.cell_of(self.ed.caret.para) else { return Ok(None) };
        let dom = &self.ed.doc.dom;
        let d = PyDict::new_bound(py);
        let at = |n: Option<crate::xml::NodeId>, k: &str| n.and_then(|n| dom.attr(n, k)).map(|s| s.to_string());
        let tp = dom.child(tbl, "w:tblPr");
        let ch = |p: Option<crate::xml::NodeId>, k: &str| p.and_then(|p| dom.child(p, k));
        let tw = ch(tp, "w:tblW");
        d.set_item("width", (at(tw, "w:w").and_then(|v| v.parse::<i32>().ok()).unwrap_or(0), at(tw, "w:type").unwrap_or("auto".into())))?;
        d.set_item("jc", at(ch(tp, "w:jc"), "w:val").unwrap_or("left".into()))?;
        d.set_item("ind", at(ch(tp, "w:tblInd"), "w:w").and_then(|v| v.parse::<i32>().ok()).unwrap_or(0))?;
        d.set_item("wrap", ch(tp, "w:tblpPr").is_some())?;
        d.set_item("caption", at(ch(tp, "w:tblCaption"), "w:val").unwrap_or_default())?;
        d.set_item("description", at(ch(tp, "w:tblDescription"), "w:val").unwrap_or_default())?;
        let rp = dom.child(tr, "w:trPr");
        let th = ch(rp, "w:trHeight");
        d.set_item("row_height", at(th, "w:val").and_then(|v| v.parse::<i32>().ok()).unwrap_or(0))?;
        d.set_item("row_rule", at(th, "w:hRule").unwrap_or("atLeast".into()))?;
        d.set_item("cant_split", ch(rp, "w:cantSplit").map(|n| crate::props::on_off(dom, n)).unwrap_or(false))?;
        d.set_item("header", ch(rp, "w:tblHeader").map(|n| crate::props::on_off(dom, n)).unwrap_or(false))?;
        let cp = dom.child(tc, "w:tcPr");
        let cw = ch(cp, "w:tcW");
        d.set_item("cell_width", (at(cw, "w:w").and_then(|v| v.parse::<i32>().ok()).unwrap_or(0), at(cw, "w:type").unwrap_or("dxa".into())))?;
        d.set_item("valign", at(ch(cp, "w:vAlign"), "w:val").unwrap_or("top".into()))?;
        let rows: Vec<crate::xml::NodeId> = dom.children_named(tbl, "w:tr").collect();
        d.set_item("row_index", rows.iter().position(|&r| r == tr).unwrap_or(0))?;
        d.set_item("rows", rows.len())?;
        Ok(Some(d))
    }

    /// Set/remove elements of the table's / selected rows' / selected cells'
    /// properties; `target` is "table", "rows", "cells" or "cell_paras".
    #[pyo3(signature = (target, edits, label="Table Properties"))]
    fn table_apply(&mut self, target: &str, edits: Vec<(String, Option<Vec<(String, String)>>)>, label: &str) -> bool {
        let e: Vec<PropEdit> = edits.into_iter().map(|(n, a)| PropEdit { name: n, attrs: a }).collect();
        let ok = match target {
            "table" => self.ed.table_apply(&e, label),
            "rows" => self.ed.rows_apply(&e, label),
            "cells" => self.ed.cells_apply(&e, label),
            "cell_paras" => self.ed.cells_para_apply(&e, label),
            _ => false,
        };
        if ok {
            self.touched();
        }
        ok
    }

    /// Border lines on "table" or "cells": [(side, attrs | None)].
    fn set_borders(&mut self, target: &str, sides: Vec<(String, Option<Vec<(String, String)>>)>) -> bool {
        let ok = self.ed.set_borders(target, &sides);
        if ok {
            self.touched();
        }
        ok
    }

    fn border_state(&self, target: &str) -> Vec<(String, Vec<(String, String)>)> {
        self.ed.border_state(target)
    }

    fn shading_state(&self, target: &str) -> Option<String> {
        self.ed.shading_state(target)
    }

    fn grid_widths(&self) -> Vec<i32> {
        self.ed.grid_widths()
    }

    #[pyo3(signature = (widths, label="Column Width"))]
    fn set_grid_widths(&mut self, widths: Vec<i32>, label: &str) -> bool {
        let ok = self.ed.set_grid_widths(&widths, label);
        if ok {
            self.touched();
        }
        ok
    }

    fn selected_grid_cols(&self) -> Option<(usize, usize)> {
        self.ed.selected_grid_cols()
    }

    /// The caret's table: its style id and look flags.
    fn table_info<'py>(&self, py: Python<'py>) -> PyResult<Option<Bound<'py, PyDict>>> {
        let Some((tbl, _, _)) = self.ed.cell_of(self.ed.caret.para) else { return Ok(None) };
        let dom = &self.ed.doc.dom;
        let d = PyDict::new_bound(py);
        let pr = dom.child(tbl, "w:tblPr");
        let style = pr.and_then(|p| dom.child(p, "w:tblStyle")).and_then(|n| dom.attr(n, "w:val")).unwrap_or("");
        d.set_item("style", style)?;
        let look = pr.and_then(|p| dom.child(p, "w:tblLook"));
        let flag = |k: &str, bit: u32, default: bool| -> bool {
            look.and_then(|l| dom.attr(l, k).map(|v| v == "1" || v == "true"))
                .or_else(|| look.and_then(|l| dom.attr(l, "w:val")).and_then(|v| u32::from_str_radix(v, 16).ok()).map(|v| v & bit != 0))
                .unwrap_or(default)
        };
        d.set_item("header", flag("w:firstRow", 0x20, true))?;
        d.set_item("total", flag("w:lastRow", 0x40, false))?;
        d.set_item("first_col", flag("w:firstColumn", 0x80, true))?;
        d.set_item("last_col", flag("w:lastColumn", 0x100, false))?;
        d.set_item("banded_rows", !flag("w:noHBand", 0x200, false))?;
        d.set_item("banded_cols", !flag("w:noVBand", 0x400, true))?;
        Ok(Some(d))
    }

    // ------------------------------------------------------------ headers
    /// Where page `i`'s body text goes: (top, bottom) in points.
    fn page_body(&self, i: usize) -> (f64, f64) {
        self.ed.layout.pages.get(i).map(|p| (p.body_top, p.body_bottom)).unwrap_or((72.0, 720.0))
    }

    /// Does page `i` show a header / footer: (header, footer).
    fn page_hf(&self, i: usize) -> (bool, bool) {
        self.ed.layout.pages.get(i).map(|p| (p.header.is_some(), p.footer.is_some())).unwrap_or((false, false))
    }

    /// Edit page `page`'s header and footer (None: back to the body).
    #[pyo3(signature = (page, footer=false))]
    fn edit_header_footer(&mut self, page: Option<usize>, footer: bool) {
        self.ed.edit_header_footer(page, footer);
        self.touched();
    }

    /// "body", or "hf" while a header / footer is edited.
    fn story(&self) -> &'static str {
        match self.ed.story {
            crate::editor::Story::Body => "body",
            crate::editor::Story::Notes(_) => "notes",
            crate::editor::Story::TextBox(..) => "textbox",
            _ => "hf",
        }
    }

    /// Is there a text box's text at a point of a page.
    fn textbox_at(&self, page: usize, x: f64, y: f64) -> bool {
        self.ed.textbox_at(page, x, y).is_some()
    }

    /// Edit the text box at a point; False if there is none.
    fn edit_textbox(&mut self, page: usize, x: f64, y: f64) -> bool {
        let ok = self.ed.edit_textbox(page, x, y);
        self.touched();
        ok
    }

    /// Insert > Shapes: preset (or "textbox") at x, y on page pg, w x h
    /// points.
    #[pyo3(signature = (prst, pg, x, y, w, h, name="Shape", arrow=false))]
    #[allow(clippy::too_many_arguments)]
    fn insert_shape(&mut self, prst: &str, pg: usize, x: f64, y: f64, w: f64, h: f64, name: &str, arrow: bool) -> bool {
        let ok = self.ed.insert_shape(prst, pg, x, y, w, h, name, arrow);
        self.touched();
        ok
    }

    fn select_story_textbox(&mut self) -> bool {
        self.ed.select_story_textbox()
    }

    fn leave_textbox(&mut self) -> bool {
        let ok = self.ed.leave_textbox();
        self.touched();
        ok
    }

    /// Edit the notes on page `page` (None: the body).
    #[pyo3(signature = (page=None))]
    fn edit_notes(&mut self, page: Option<usize>) {
        self.ed.edit_notes(page);
        self.touched();
    }

    /// Is there note text at height y of a page.
    fn note_at(&self, page: usize, y: f64) -> bool {
        let Some(pg) = self.ed.layout.pages.get(page) else { return false };
        pg.note_lines.iter().any(|l| {
            let h = self.ed.layout.paras[l.para].lines[l.line].height;
            y >= l.y - 2.0 && y <= l.y + h + 2.0
        })
    }

    #[pyo3(signature = (endnote=false))]
    fn insert_note(&mut self, endnote: bool) -> bool {
        let ok = self.ed.insert_note(endnote);
        self.touched();
        ok
    }

    /// The page whose header / footer is being edited.
    fn story_page(&self) -> Option<usize> {
        match self.ed.story {
            crate::editor::Story::HeaderFooter(p) | crate::editor::Story::Notes(p) => Some(p),
            _ => None,
        }
    }

    /// The section page `i` belongs to.
    fn section_count(&self) -> usize {
        self.ed.doc.sections.len()
    }

    fn page_section(&self, i: usize) -> usize {
        self.ed.layout.pages.get(i).map(|p| p.section).unwrap_or(0)
    }

    #[pyo3(signature = (sec, el, attr, value, label="Page Setup"))]
    fn section_attr(&mut self, sec: usize, el: &str, attr: &str, value: Option<&str>, label: &str) -> bool {
        let ok = self.ed.section_attr(sec, el, attr, value, label);
        self.touched();
        ok
    }

    #[pyo3(signature = (sec, el, on, label="Page Setup"))]
    fn section_flag(&mut self, sec: usize, el: &str, on: bool, label: &str) -> bool {
        let ok = self.ed.section_flag(sec, el, on, label);
        self.touched();
        ok
    }

    /// A section's header settings: title page, header / footer distance
    /// (twips).
    fn section_info<'py>(&self, py: Python<'py>, sec: usize) -> PyResult<Option<Bound<'py, PyDict>>> {
        let Some(s) = self.ed.doc.sections.get(sec) else { return Ok(None) };
        let d = PyDict::new_bound(py);
        d.set_item("title_pg", s.title_pg)?;
        d.set_item("header", s.header)?;
        d.set_item("footer", s.footer)?;
        d.set_item("even_odd", self.ed.doc.settings.even_odd_headers)?;
        Ok(Some(d))
    }

    #[pyo3(signature = (sec, xml=None))]
    fn set_page_borders(&mut self, sec: Option<usize>, xml: Option<&str>) -> bool {
        let r = self.ed.set_page_borders(sec, xml);
        self.touched();
        r
    }

    /// A small picture of a page border (preview): (w, h, stride, ARGB32).
    #[pyo3(signature = (val, w, h, width_pt=12.0, color=None))]
    fn border_sample<'py>(&self, py: Python<'py>, val: &str, w: i32, h: i32, width_pt: f64, color: Option<u32>)
                          -> PyResult<(i32, i32, i32, Bound<'py, PyBytes>)> {
        let mut surf = cairo::ImageSurface::create(cairo::Format::ARgb32, w.max(1), h.max(1))
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
        {
            let cr = cairo::Context::new(&surf).map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
            cr.set_source_rgb(1.0, 1.0, 1.0);
            cr.paint().ok();
            let side = crate::art::PageBorder { val: val.to_string(), width: width_pt, space: 4.0, color, shadow: false };
            let b = crate::art::PageBorders { from_page: true, display: "allPages".into(), front: true,
                                              sides: [Some(side.clone()), Some(side.clone()), Some(side.clone()), Some(side)] };
            crate::art::draw(&cr, &b, w as f64, h as f64, (0.0, 0.0, w as f64, h as f64));
        }
        surf.flush();
        let stride = surf.stride();
        let data = surf.data().map(|d| d.to_vec()).unwrap_or_default();
        Ok((w, h, stride, PyBytes::new_bound(py, &data)))
    }

    fn art_names(&self) -> Vec<&'static str> {
        crate::art::ART_NAMES.to_vec()
    }

    /// The section's page borders as XML (for the dialog), or "".
    fn page_borders_xml(&self, sec: usize) -> String {
        let Some(s) = self.ed.doc.sections.get(sec) else { return String::new() };
        let dom = &self.ed.doc.dom;
        s.node.and_then(|n| dom.child(n, "w:pgBorders")).map(|b| dom.serialize_node(b)).unwrap_or_default()
    }

    fn set_setting(&mut self, name: &str, on: bool) -> bool {
        let r = self.ed.set_setting(name, on);
        self.touched();
        r
    }

    fn setting(&self, name: &str) -> bool {
        self.ed.setting(name)
    }

    /// A section's page: size, margins, gutter (twips), orientation.
    fn page_setup<'py>(&self, py: Python<'py>, sec: usize) -> PyResult<Option<Bound<'py, PyDict>>> {
        let Some(s) = self.ed.doc.sections.get(sec) else { return Ok(None) };
        let d = PyDict::new_bound(py);
        d.set_item("width", s.page_w)?;
        d.set_item("height", s.page_h)?;
        d.set_item("top", s.top)?;
        d.set_item("bottom", s.bottom)?;
        d.set_item("left", s.left)?;
        d.set_item("right", s.right)?;
        d.set_item("gutter", s.gutter)?;
        d.set_item("header", s.header)?;
        d.set_item("footer", s.footer)?;
        d.set_item("cols", s.cols)?;
        d.set_item("col_space", s.col_space)?;
        d.set_item("section_count", self.ed.doc.sections.len())?;
        d.set_item("start", s.start.clone())?;
        d.set_item("v_align", s.v_align.clone())?;
        d.set_item("title_pg", s.title_pg)?;
        Ok(Some(d))
    }

    fn current_section(&self) -> usize {
        self.ed.current_section()
    }

    fn caret_page(&self) -> usize {
        self.ed.caret_page()
    }

    /// Make the section's default header / footer if it has none.
    fn ensure_header_footer(&mut self, sec: usize, footer: bool) -> bool {
        let ok = self.ed.ensure_header_footer(sec, footer).is_some();
        self.touched();
        ok
    }

    #[pyo3(signature = (sec, footer, align="center", x_of_y=false, bold=false))]
    fn page_number_in(&mut self, sec: usize, footer: bool, align: &str, x_of_y: bool, bold: bool) -> bool {
        let ok = self.ed.page_number_in(sec, footer, align, x_of_y, bold);
        self.touched();
        ok
    }

    #[pyo3(signature = (instr, result=""))]
    fn insert_field(&mut self, instr: &str, result: &str) {
        self.ed.insert_field(instr, result);
        self.touched();
    }

    // ------------------------------------------------------------ objects
    /// Select the object at a point of a page; False (and nothing
    /// selected) if there is none.
    fn insert_anchor_xml(&mut self, xml: &str, pg: usize, x: f64, y: f64) -> bool {
        let r = self.ed.insert_anchor_xml(xml, pg, x, y);
        self.touched();
        r
    }

    fn selected_drawing_xml(&self) -> Option<String> {
        self.ed.selected_drawing_xml()
    }

    fn select_object_at(&mut self, page: usize, x: f64, y: f64) -> bool {
        let n = self.ed.object_at(page, x, y);
        self.ed.select_object(n);
        n.is_some()
    }

    fn object_at(&self, page: usize, x: f64, y: f64) -> bool {
        self.ed.object_at(page, x, y).is_some()
    }

    fn deselect_object(&mut self) {
        self.ed.sel_obj = None;
        self.ed.sel_more.clear();
    }

    /// Shift+click on an object: add it to the selection (or take it out).
    fn toggle_object_at(&mut self, page: usize, x: f64, y: f64) -> bool {
        match self.ed.object_at(page, x, y) {
            Some(n) => {
                self.ed.toggle_selected(n);
                true
            }
            None => false,
        }
    }

    fn select_objects_in(&mut self, page: usize, x0: f64, y0: f64, x1: f64, y1: f64) -> usize {
        let v = self.ed.objects_in(page, x0, y0, x1, y1);
        self.ed.select_nodes_list(&v);
        v.len()
    }

    fn select_object_nodes(&mut self, nodes: Vec<u32>) {
        self.ed.select_nodes_list(&nodes);
    }

    /// Every selected object: (node, page, x, y, w, h, inline, kind).
    fn selected_objects(&self) -> Vec<(u32, usize, f64, f64, f64, f64, bool, String)> {
        self.ed.selected_nodes().into_iter().filter_map(|n| self.ed.object_info(n))
            .map(|i| (i.node, i.page, i.x, i.y, i.w, i.h, i.inline, i.kind.to_string())).collect()
    }

    fn object_anchor_mode(&mut self, mode: &str) -> bool {
        let ok = self.ed.object_anchor_mode(mode);
        self.touched();
        ok
    }

    fn object_anchor_state(&self) -> String {
        self.ed.object_anchor_state()
    }

    /// Group the selected objects: (ok, message).
    fn object_group(&mut self) -> (bool, String) {
        let r = self.ed.object_group();
        self.touched();
        match r {
            Ok(_) => (true, String::new()),
            Err(m) => (false, m.to_string()),
        }
    }

    fn object_ungroup(&mut self) -> Vec<u32> {
        let v = self.ed.object_ungroup();
        self.touched();
        v
    }

    fn object_crop(&self) -> Option<(f64, f64, f64, f64)> {
        self.ed.object_crop().map(|c| (c[0], c[1], c[2], c[3]))
    }

    #[pyo3(signature = (l, t, r, b, keep_scale=true))]
    fn set_object_crop(&mut self, l: f64, t: f64, r: f64, b: f64, keep_scale: bool) -> bool {
        let ok = self.ed.set_object_crop([l, t, r, b], keep_scale);
        self.touched();
        ok
    }

    fn crop_to_ratio(&mut self, w: f64, h: f64) -> bool {
        let ok = self.ed.crop_to_ratio(w, h);
        self.touched();
        ok
    }

    fn crop_aspect(&mut self, fit: bool) -> bool {
        let ok = self.ed.crop_aspect(fit);
        self.touched();
        ok
    }

    fn object_image<'py>(&self, py: Python<'py>) -> Option<(Bound<'py, pyo3::types::PyBytes>, String)> {
        self.ed.object_image().map(|(b, n)| (pyo3::types::PyBytes::new_bound(py, &b), n))
    }

    fn object_set_image(&mut self, data: &[u8], ext: &str) -> bool {
        let ok = self.ed.object_set_image(data, ext);
        self.touched();
        ok
    }

    /// Merge Shapes: (number made, message).
    fn merge_shapes(&mut self, op: &str) -> (usize, String) {
        let r = self.ed.merge_shapes(op);
        self.touched();
        match r {
            Ok(n) => (n, String::new()),
            Err(m) => (0, m.to_string()),
        }
    }

    fn shape_points(&mut self) -> Vec<Vec<(f64, f64)>> {
        self.ed.shape_points()
    }

    fn set_shape_points(&mut self, rings: Vec<Vec<(f64, f64)>>) -> bool {
        let ok = self.ed.set_shape_points(&rings);
        self.touched();
        ok
    }

    fn object_layout(&self) -> Option<Vec<(String, String)>> {
        self.ed.object_layout()
    }

    fn set_object_layout(&mut self, vals: Vec<(String, String)>) -> bool {
        let ok = self.ed.set_object_layout(&vals);
        self.touched();
        ok
    }

    fn object_set_rotation(&mut self, deg: f64) -> bool {
        let ok = self.ed.object_set_rotation(deg);
        self.touched();
        ok
    }

    fn textbox_link_state(&self) -> String {
        self.ed.textbox_link_state()
    }

    /// Create Link from text box `src` to the selected one: message or "".
    fn link_textboxes(&mut self, src: u32) -> String {
        let r = self.ed.link_textboxes(src);
        self.touched();
        r.err().unwrap_or("").to_string()
    }

    fn unlink_textbox(&mut self) -> bool {
        let ok = self.ed.unlink_textbox();
        self.touched();
        ok
    }

    fn object_warp(&mut self, prst: &str) -> bool {
        let ok = self.ed.object_warp(prst);
        self.touched();
        ok
    }

    fn object_warp_name(&self) -> String {
        self.ed.object_warp_name()
    }

    /// 0 Print Layout, 1 Draft, 2 Web Layout (width: the window's, points).
    #[pyo3(signature = (mode, width=0.0))]
    fn set_view_mode(&mut self, mode: u8, width: f64) {
        self.ed.set_view_mode(mode, width);
        self.touched();
    }

    fn view_mode(&self) -> u8 {
        self.ed.view_mode
    }

    fn outline_paras(&self) -> Vec<(u32, String, i32, f64, bool, bool, i64, String)> {
        self.ed.outline_paras()
    }

    #[pyo3(signature = (color=None))]
    fn set_page_color(&mut self, color: Option<&str>) -> bool {
        let ok = self.ed.set_page_color(color);
        self.touched();
        ok
    }

    #[pyo3(signature = (kind, c1, c2="FFFFFF", angle=0.0, focus="", title="", image=None, ext="png"))]
    #[allow(clippy::too_many_arguments)]
    fn set_page_fill(&mut self, kind: &str, c1: &str, c2: &str, angle: f64, focus: &str, title: &str,
                     image: Option<Vec<u8>>, ext: &str) -> bool {
        let ok = self.ed.set_page_fill(kind, c1, c2, angle, focus, title, image.as_deref().map(|b| (b, ext)));
        self.touched();
        ok
    }

    fn page_fill(&self) -> Option<(String, String, String)> {
        self.ed.doc.page_fill().map(|f| (f.kind, format!("{:06X}", f.c1), format!("{:06X}", f.c2)))
    }

    fn page_color(&self) -> Option<String> {
        self.ed.page_color()
    }

    fn para_before_table(&mut self) -> bool {
        let ok = self.ed.para_before_table();
        self.touched();
        ok
    }

    fn move_block(&mut self, up: bool) -> bool {
        let ok = self.ed.move_block(up);
        self.touched();
        ok
    }

    fn move_paras(&mut self, nodes: Vec<u32>, target: u32, after: bool) -> bool {
        let ok = self.ed.move_paras(&nodes, target, after);
        self.touched();
        ok
    }

    fn section_paras(&self, head: u32) -> Vec<u32> {
        self.ed.section_paras(head)
    }

    fn set_para_text(&mut self, p: u32, text: &str) -> bool {
        let ok = self.ed.set_para_text(p, text);
        self.touched();
        ok
    }

    fn hyphen_points(&self, word: &str, lang: &str) -> Vec<usize> {
        self.ed.hyphen_points(word, lang)
    }

    fn settings_xml(&mut self, tag: &str) -> Option<String> {
        self.ed.settings_xml(tag)
    }

    #[pyo3(signature = (tag, xml=None))]
    fn set_settings_xml(&mut self, tag: &str, xml: Option<&str>) -> bool {
        let ok = self.ed.set_settings_xml(tag, xml);
        self.touched();
        ok
    }

    #[pyo3(signature = (kind, target, external=false))]
    fn add_settings_rel(&mut self, kind: &str, target: &str, external: bool) -> Option<String> {
        self.ed.add_settings_rel(kind, target, external)
    }

    /// Every body field: (depth, code as Word evaluates it, result).
    fn fields_all(&self) -> Vec<(usize, String, String)> {
        self.ed.fields_all()
    }

    fn set_field_text_at(&mut self, i: usize, text: &str) -> bool {
        let ok = self.ed.set_field_text_at(i, text);
        self.touched();
        ok
    }

    fn unlink_fields(&mut self) -> usize {
        let n = self.ed.unlink_fields();
        self.touched();
        n
    }

    fn body_blocks(&self) -> Vec<(&'static str, u32, usize)> {
        self.ed.body_blocks()
    }

    /// Every body paragraph's list label in document order (tables and
    /// content controls included, text boxes not); "" when it has none.
    fn body_labels(&self) -> Vec<String> {
        fn walk(ed: &Editor, n: crate::xml::NodeId, out: &mut Vec<String>) {
            let dom = &ed.doc.dom;
            for c in dom.elements(n).collect::<Vec<_>>() {
                match dom.name(c) {
                    "w:p" => out.push(ed.para_layout(c).and_then(|l| l.label.as_ref()).map(|l| l.text.clone()).unwrap_or_default()),
                    "w:tbl" | "w:tr" | "w:tc" | "w:sdt" | "w:sdtContent" => walk(ed, c, out),
                    _ => {}
                }
            }
        }
        let mut out = Vec::new();
        walk(&self.ed, self.ed.doc.body, &mut out);
        out
    }

    fn para_text_of(&mut self, p: u32) -> String {
        self.ed.para_text_of(p)
    }

    fn undo_names(&self) -> Vec<String> {
        self.ed.undo_names()
    }

    fn table_cells(&self, n: usize) -> Vec<Vec<Vec<u32>>> {
        self.ed.table_cells(n)
    }

    /// Check Accessibility: (category, label, node to go to).
    fn accessibility_issues(&self) -> Vec<(String, String, u32)> {
        self.ed.accessibility_issues()
    }

    fn wrap_polygon(&self) -> Vec<(f64, f64)> {
        self.ed.wrap_polygon()
    }

    fn set_wrap_polygon(&mut self, pts: Vec<(f64, f64)>) -> bool {
        let ok = self.ed.set_wrap_polygon(&pts);
        self.touched();
        ok
    }

    fn objects_list(&self) -> Vec<(u32, String, String, bool)> {
        self.ed.objects_list()
    }

    #[pyo3(signature = (node, name=None, visible=None))]
    fn object_set_meta(&mut self, node: u32, name: Option<&str>, visible: Option<bool>) -> bool {
        let ok = self.ed.object_set_meta(node, name, visible);
        self.touched();
        ok
    }

    fn select_object_node(&mut self, node: u32) -> bool {
        self.ed.select_object(Some(node));
        self.ed.selected_object().is_some()
    }

    /// The selected object: page, x, y, w, h (points), rot, inline, kind,
    /// wrap; None when the text is selected.
    fn selected_object<'py>(&mut self, py: Python<'py>) -> PyResult<Option<Bound<'py, PyDict>>> {
        let Some(i) = self.ed.selected_object() else { return Ok(None) };
        let d = PyDict::new_bound(py);
        d.set_item("page", i.page)?;
        d.set_item("x", i.x)?;
        d.set_item("y", i.y)?;
        d.set_item("w", i.w)?;
        d.set_item("h", i.h)?;
        d.set_item("rot", i.rot)?;
        d.set_item("inline", i.inline)?;
        d.set_item("kind", i.kind)?;
        d.set_item("wrap", i.wrap)?;
        d.set_item("para", i.pos.para)?;
        d.set_item("off", i.pos.off)?;
        Ok(Some(d))
    }

    fn object_resize(&mut self, w: f64, h: f64) -> bool {
        let ok = self.ed.object_resize(w, h);
        self.touched();
        ok
    }

    fn object_move(&mut self, x: f64, y: f64) -> bool {
        let ok = self.ed.object_move(x, y);
        self.touched();
        ok
    }

    fn object_set_wrap(&mut self, how: &str) -> bool {
        let ok = self.ed.object_set_wrap(how);
        self.touched();
        ok
    }

    fn object_rotate(&mut self, how: &str) -> bool {
        let ok = self.ed.object_rotate(how);
        self.touched();
        ok
    }

    fn object_z(&mut self, delta: i32) -> bool {
        let ok = self.ed.object_z(delta);
        self.touched();
        ok
    }

    #[pyo3(signature = (where_, page=false))]
    fn object_align(&mut self, where_: &str, page: bool) -> bool {
        let ok = self.ed.object_align(where_, page);
        self.touched();
        ok
    }

    fn object_delete(&mut self) -> bool {
        let ok = self.ed.object_delete();
        self.touched();
        ok
    }

    fn object_natural_size(&self) -> Option<(f64, f64)> {
        self.ed.object_natural_size()
    }

    /// Insert a picture file at the caret.
    fn insert_picture(&mut self, path: &str) -> PyResult<bool> {
        let bytes = std::fs::read(path).map_err(|e| err(e.to_string()))?;
        let ok = self.ed.insert_picture(&bytes, path);
        self.touched();
        Ok(ok)
    }

    /// Tab / Shift+Tab in a table; False outside one.
    fn cell_step(&mut self, back: bool) -> bool {
        let v = self.ed.version_hint();
        let ok = self.ed.cell_step(back);
        if self.ed.version_hint() != v {
            self.touched();
        }
        ok
    }

    /// The caret's cell as the original names it ("B3"), or "".
    fn cell_name(&self) -> String {
        self.ed.cell_name()
    }

    /// Bullets / Numbering buttons: kind "bullet" or "number".
    fn reset_para_formatting(&mut self) -> bool {
        let r = self.ed.reset_para_formatting();
        self.touched();
        r
    }

    fn toggle_list(&mut self, kind: &str) {
        self.ed.toggle_list(kind);
        self.touched();
    }

    /// Change the list level of the selected list items; False if they
    /// aren't list items.
    fn change_list_level(&mut self, delta: i32) -> bool {
        let ok = self.ed.change_list_level(delta);
        if ok {
            self.touched();
        }
        ok
    }

    fn at_list_item_start(&self) -> bool {
        self.ed.at_list_item_start()
    }

    /// Character styles: [(id, name)].
    fn character_styles(&self) -> Vec<(String, String)> {
        let mut v: Vec<(String, String)> = self
            .ed
            .doc
            .styles
            .styles
            .values()
            .filter(|s| s.kind == crate::styles::StyleKind::Character)
            .map(|s| (s.id.clone(), ui_name(&s.name)))
            .collect();
        v.sort_by(|a, b| a.1.to_lowercase().cmp(&b.1.to_lowercase()));
        v
    }

    /// Apply a character style (None or the default: remove it).
    fn set_char_style(&mut self, id: &str) {
        let default = self.ed.doc.styles.default_char.clone();
        let e = if id.is_empty() || Some(id.to_string()) == default { PropEdit::remove("w:rStyle") } else { val_named("w:rStyle", id) };
        self.ed.format_runs(&[e], "Style");
        self.touched();
    }

    /// Paragraph styles: [(id, name)], in the order the gallery shows.
    fn paragraph_styles(&self) -> Vec<(String, String)> {
        let mut v: Vec<(String, String)> = self
            .ed
            .doc
            .styles
            .styles
            .values()
            .filter(|s| s.kind == crate::styles::StyleKind::Paragraph)
            .map(|s| (s.id.clone(), ui_name(&s.name)))
            .collect();
        v.sort_by(|a, b| a.1.to_lowercase().cmp(&b.1.to_lowercase()));
        v
    }

    // ------------------------------------------------- formatting access
    /// Resolved character formatting at the caret / selection start.
    fn run_values<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let r = self.ed.current_run_props();
        run_dict(py, &r, &self.ed.doc.styles)
    }

    /// Resolved paragraph formatting of the caret's paragraph.
    /// The caret paragraph's own w:pPr, as XML ("" if none).
    fn para_xml(&self) -> String {
        let d = &self.ed.doc.dom;
        d.child(self.ed.caret.para, "w:pPr").map(|n| d.serialize_node(n)).unwrap_or_default()
    }

    fn para_values<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let p = self.ed.current_para_props();
        para_dict(py, &p)
    }

    /// Set or remove run property elements: [(name, {attr: value} | None)].
    #[pyo3(signature = (edits, label="Font"))]
    fn apply_run(&mut self, edits: Vec<(String, Option<Vec<(String, String)>>)>, label: &str) {
        let e: Vec<PropEdit> = edits.into_iter().map(|(n, a)| PropEdit { name: n, attrs: a }).collect();
        self.ed.format_runs(&e, label);
        self.touched();
    }

    /// Set or remove paragraph property elements.
    #[pyo3(signature = (edits, label="Paragraph"))]
    fn apply_para(&mut self, edits: Vec<(String, Option<Vec<(String, String)>>)>, label: &str) {
        let e: Vec<PropEdit> = edits.into_iter().map(|(n, a)| PropEdit { name: n, attrs: a }).collect();
        self.ed.format_paras(&e, label);
        self.touched();
    }

    /// Set attributes of one paragraph property element (None removes one).
    #[pyo3(signature = (name, attrs, label="Paragraph"))]
    fn apply_para_attrs(&mut self, name: &str, attrs: Vec<(String, Option<String>)>, label: &str) {
        let a: Vec<(&str, Option<&str>)> = attrs.iter().map(|(k, v)| (k.as_str(), v.as_deref())).collect();
        self.ed.format_paras_attrs(name, &a, label);
        self.touched();
    }

    /// Tab stops of the selected paragraphs: [(twips, kind, leader)].
    fn set_tabs(&mut self, tabs: Vec<(i32, String, String)>) {
        self.ed.set_tabs(&tabs);
        self.touched();
    }

    // ------------------------------------------------------------ styles
    /// Every style: (id, name, kind, based-on id, next id, custom, auto update, gallery).
    fn style_list(&self) -> Vec<(String, String, String, String, String, bool, bool, bool)> {
        let mut v: Vec<_> = self.ed.doc.styles.styles.values().map(|s| {
            let kind = match s.kind {
                crate::styles::StyleKind::Paragraph => "paragraph",
                crate::styles::StyleKind::Character => "character",
                crate::styles::StyleKind::Table => "table",
                crate::styles::StyleKind::Numbering => "numbering",
            };
            (s.id.clone(), ui_name(&s.name), kind.to_string(), s.based_on.clone().unwrap_or_default(),
             s.next.clone().unwrap_or_default(), s.custom, s.auto_redefine, s.q_format)
        }).collect();
        v.sort_by(|a, b| a.1.to_lowercase().cmp(&b.1.to_lowercase()));
        v
    }

    /// A style's resolved character formatting.
    fn style_run_values<'py>(&self, py: Python<'py>, id: &str) -> PyResult<Bound<'py, PyDict>> {
        let st = &self.ed.doc.styles;
        let r = match st.styles.get(id).map(|s| s.kind.clone()) {
            Some(crate::styles::StyleKind::Character) => {
                let (_, base) = st.para_style(None);
                st.run(&base, &crate::props::RunProps { style: Some(id.to_string()), ..Default::default() })
            }
            _ => st.para_style(Some(id)).1,
        };
        run_dict(py, &r, st)
    }

    fn style_para_values<'py>(&self, py: Python<'py>, id: &str) -> PyResult<Bound<'py, PyDict>> {
        let p = self.ed.doc.styles.para_style(Some(id)).0;
        para_dict(py, &p)
    }

    fn style_apply_run(&mut self, id: &str, edits: Vec<(String, Option<Vec<(String, String)>>)>) {
        let e: Vec<PropEdit> = edits.into_iter().map(|(n, a)| PropEdit { name: n, attrs: a }).collect();
        self.ed.style_apply_run(id, &e);
        self.touched();
    }

    fn style_apply_para(&mut self, id: &str, edits: Vec<(String, Option<Vec<(String, String)>>)>) {
        let e: Vec<PropEdit> = edits.into_iter().map(|(n, a)| PropEdit { name: n, attrs: a }).collect();
        self.ed.style_apply_para(id, &e);
        self.touched();
    }

    fn style_set_num(&mut self, id: &str, num: i32, ilvl: i32) {
        self.ed.style_set_num(id, num, ilvl);
        self.touched();
    }

    fn style_apply_para_attrs(&mut self, id: &str, name: &str, attrs: Vec<(String, Option<String>)>) {
        let a: Vec<(&str, Option<&str>)> = attrs.iter().map(|(k, v)| (k.as_str(), v.as_deref())).collect();
        self.ed.style_apply_para_attrs(id, name, &a);
        self.touched();
    }

    fn style_set_tabs(&mut self, id: &str, tabs: Vec<(i32, String, String)>) {
        self.ed.style_set_tabs(id, &tabs);
        self.touched();
    }

    #[pyo3(signature = (id, name=None, based_on=None, next=None, auto=None))]
    fn style_set_meta(&mut self, id: &str, name: Option<&str>, based_on: Option<&str>, next: Option<&str>,
                      auto: Option<bool>) {
        self.ed.style_set_meta(id, name, based_on, next, auto);
        self.touched();
    }

    /// Add a w:style definition (XML) unless its id exists.
    fn add_style_xml(&mut self, xml: &str) -> bool {
        let ok = self.ed.add_style_xml(xml);
        if ok {
            self.touched();
        }
        ok
    }

    #[pyo3(signature = (name, kind="paragraph", based_on=None))]
    fn create_style(&mut self, name: &str, kind: &str, based_on: Option<&str>) -> String {
        let id = self.ed.create_style(name, kind, based_on);
        self.touched();
        id
    }

    fn begin_group(&mut self, name: &str) {
        self.ed.begin_group(name);
    }

    fn end_group(&mut self) {
        self.ed.end_group();
    }

    /// What the ribbon shows for the caret/selection.
    fn state<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new_bound(py);
        let r = self.ed.current_run_props();
        let p = self.ed.current_para_props();
        let st = &self.ed.doc.styles;
        let fam = crate::text::family_for(st, &r, 'a');
        d.set_item("font", fam)?;
        d.set_item("size", r.size.unwrap_or(20) as f64 / 2.0)?;
        d.set_item("lang", r.lang.clone().unwrap_or_default())?;
        d.set_item("bold", self.ed.toggle_state("w:b"))?;
        d.set_item("italic", self.ed.toggle_state("w:i"))?;
        d.set_item("strike", self.ed.toggle_state("w:strike"))?;
        d.set_item("underline", r.underline.clone().unwrap_or_else(|| "none".into()))?;
        d.set_item("vert_align", r.vert_align.clone().unwrap_or_else(|| "baseline".into()))?;
        d.set_item("color", match r.color {
            Some(crate::props::ColorVal::Rgb(c)) => format!("{:06X}", c),
            _ => "auto".into(),
        })?;
        d.set_item("highlight", r.highlight.clone().unwrap_or_else(|| "none".into()))?;
        d.set_item("align", p.jc.clone().unwrap_or_else(|| "left".into()))?;
        let sid = p.style.clone().unwrap_or_default();
        d.set_item("style_id", sid.clone())?;
        d.set_item("style", ui_name(st.style_name(&sid).unwrap_or(&sid)))?;
        d.set_item("line", p.line.unwrap_or(240))?;
        d.set_item("ind_left", p.ind_left.unwrap_or(0))?;
        d.set_item("ind_right", p.ind_right.unwrap_or(0))?;
        d.set_item("ind_first", p.ind_first.unwrap_or(0))?;
        d.set_item("space_before", p.before.unwrap_or(0))?;
        d.set_item("space_after", p.after.unwrap_or(0))?;
        d.set_item("line_rule", p.line_rule.clone().unwrap_or_else(|| "auto".into()))?;
        let list = self.ed.para_layout(self.ed.caret.para).and_then(|pl| pl.label.as_ref())
            .map(|l| if l.bullet { "bullet" } else { "number" }).unwrap_or("");
        d.set_item("list", list)?;
        d.set_item("can_undo", self.ed.can_undo())?;
        d.set_item("can_redo", self.ed.can_redo())?;
        d.set_item("undo_name", self.ed.undo_name().unwrap_or(""))?;
        d.set_item("has_selection", self.ed.has_selection())?;
        let (pg, _, _, _) = self.ed.caret_rect(self.ed.caret).unwrap_or((0, 0.0, 0.0, 0.0));
        d.set_item("page", pg + 1)?;
        d.set_item("pages", self.ed.page_count())?;
        d.set_item("modified", self.ed.modified)?;
        Ok(d)
    }

    /// Words and characters (status bar).
    fn counts(&self) -> (usize, usize) {
        self.ed.counts()
    }

    // ------------------------------------------------------------ fields
    /// Update the fields in the selection (all: every field). Returns how
    /// many changed.
    #[pyo3(signature = (all=false))]
    fn update_fields(&mut self, all: bool) -> usize {
        let n = self.ed.update_fields(all);
        self.touched();
        n
    }

    /// Insert a field (its instruction) at the caret, with its result.
    fn insert_field_now(&mut self, instr: &str) {
        self.ed.insert_field_now(instr);
        self.touched();
    }

    #[pyo3(signature = (title=None))]
    fn insert_toc(&mut self, title: Option<&str>) {
        self.ed.insert_toc(title);
        self.touched();
    }

    #[pyo3(signature = (instr, title=None, title_style=None, gallery=None, leader=None, paras=None, columns=0))]
    fn insert_table_field(&mut self, instr: &str, title: Option<&str>, title_style: Option<&str>, gallery: Option<&str>,
                          leader: Option<&str>, paras: Option<&str>, columns: u32) -> bool {
        let t = title.map(|t| (t, title_style.unwrap_or("TOCHeading")));
        let ok = self.ed.insert_table_field(instr, t, gallery, leader, paras, columns);
        self.touched();
        ok
    }

    #[pyo3(signature = (i, instr, leader=None))]
    fn set_table_instr(&mut self, i: usize, instr: &str, leader: Option<&str>) -> bool {
        let ok = self.ed.set_table_instr(i, instr, leader);
        self.touched();
        ok
    }

    fn set_table_result(&mut self, i: usize, paras_xml: &str) -> bool {
        let ok = self.ed.set_table_result(i, paras_xml);
        self.touched();
        ok
    }

    fn set_field_instr(&mut self, i: usize, instr: &str) -> bool {
        let ok = self.ed.set_field_instr(i, instr);
        self.touched();
        ok
    }

    fn set_field_text(&mut self, i: usize, text: &str) -> bool {
        let ok = self.ed.set_field_text(i, text);
        self.touched();
        ok
    }

    /// Top-level body fields: (instr, result, para, start, end).
    fn body_fields(&self) -> Vec<(String, String, u32, usize, usize)> {
        self.ed.body_fields()
    }

    fn field_at_caret(&self, kind: &str) -> Option<usize> {
        self.ed.field_at_caret(kind)
    }

    fn insert_code_field(&mut self, instr: &str) -> bool {
        let ok = self.ed.insert_code_field(instr);
        self.touched();
        ok
    }

    #[pyo3(signature = (text, instr, match_case=false))]
    fn mark_all(&mut self, text: &str, instr: &str, match_case: bool) -> usize {
        let n = self.ed.mark_all(text, instr, match_case);
        self.touched();
        n
    }

    fn note_settings(&self, endnote: bool) -> (String, i32, String, String) {
        self.ed.note_settings(endnote)
    }

    fn set_note_settings(&mut self, endnote: bool, fmt: &str, start: i32, restart: &str, pos: &str) {
        self.ed.set_note_settings(endnote, fmt, start, restart, pos);
        self.touched();
    }

    fn insert_note_mark(&mut self, endnote: bool, mark: &str) -> bool {
        let ok = self.ed.insert_note_mark(endnote, mark);
        self.touched();
        ok
    }

    #[pyo3(signature = (endnote_first=false))]
    fn show_notes(&mut self, endnote_first: bool) -> bool {
        let ok = self.ed.show_notes(endnote_first);
        self.touched();
        ok
    }

    fn note_count(&self, endnote: bool) -> usize {
        if endnote { self.ed.doc.notes.en_order.len() } else { self.ed.doc.notes.fn_order.len() }
    }

    fn convert_notes(&mut self, how: &str) -> usize {
        let n = self.ed.convert_notes(how);
        self.touched();
        n
    }

    fn package_part(&mut self, name: &str) -> Option<String> {
        self.ed.package_part(name)
    }

    #[pyo3(signature = (name, xml, ctype="", rel=""))]
    fn set_package_part(&mut self, name: &str, xml: &str, ctype: &str, rel: &str) -> bool {
        self.ed.set_package_part(name, xml, ctype, rel)
    }

    fn custom_xml(&mut self, ns: &str) -> Option<String> {
        self.ed.custom_xml(ns)
    }

    fn set_custom_xml(&mut self, ns: &str, xml: &str) -> bool {
        let ok = self.ed.set_custom_xml(ns, xml);
        self.touched();
        ok
    }

    // ---- charts
    #[pyo3(signature = (xml, xlsx, w, h, ex=false))]
    fn insert_chart(&mut self, xml: &str, xlsx: Vec<u8>, w: f64, h: f64, ex: bool) -> Option<String> {
        let r = self.ed.insert_chart(xml, &xlsx, w, h, ex);
        self.touched();
        r
    }

    fn selected_chart(&mut self) -> Option<String> {
        self.ed.selected_chart()
    }

    fn chart_parts(&self) -> Vec<String> {
        self.ed.chart_parts()
    }

    fn set_chart_xml(&mut self, part: &str, xml: &str) -> bool {
        let r = self.ed.set_chart_xml(part, xml);
        self.touched();
        r
    }

    fn chart_workbook<'py>(&mut self, py: Python<'py>, part: &str) -> Option<(String, Bound<'py, pyo3::types::PyBytes>)> {
        self.ed.chart_workbook(part).map(|(n, b)| (n, pyo3::types::PyBytes::new_bound(py, &b)))
    }

    fn set_chart_workbook(&mut self, part: &str, xlsx: Vec<u8>) -> bool {
        let r = self.ed.set_chart_workbook(part, &xlsx);
        self.touched();
        r
    }

    // ---- content controls
    fn content_controls(&self) -> Vec<(String, String, String, bool)> {
        self.ed.content_controls()
    }

    fn control_at_caret(&self) -> Option<String> {
        self.ed.control_at_caret()
    }

    fn insert_content_control(&mut self, pr: &str, placeholder: &str) -> Option<String> {
        let r = self.ed.insert_content_control(pr, placeholder);
        self.touched();
        r
    }

    fn control_pr(&self, id: &str) -> Option<String> {
        self.ed.control_pr(id)
    }

    fn set_control_pr(&mut self, id: &str, pr: &str) -> bool {
        let r = self.ed.set_control_pr(id, pr);
        self.touched();
        r
    }

    #[pyo3(signature = (id, text, placeholder=false))]
    fn set_control_text(&mut self, id: &str, text: &str, placeholder: bool) -> bool {
        let r = self.ed.set_control_text(id, text, placeholder);
        self.touched();
        r
    }

    fn select_control(&mut self, id: &str) -> bool {
        self.ed.select_control(id)
    }

    #[pyo3(signature = (id, keep=true))]
    fn remove_control(&mut self, id: &str, keep: bool) -> bool {
        let r = self.ed.remove_control(id, keep);
        self.touched();
        r
    }

    fn control_range(&self, id: &str) -> Option<(u32, usize, usize)> {
        self.ed.control_range(id)
    }

    fn control_ranges(&self) -> Vec<(String, u32, usize, usize)> {
        self.ed.control_ranges()
    }

    fn showing_placeholder(&self, id: &str) -> bool {
        self.ed.showing_placeholder(id)
    }

    fn update_toc(&mut self) -> bool {
        let ok = self.ed.update_toc();
        self.touched();
        ok
    }

    fn remove_toc(&mut self) -> bool {
        let ok = self.ed.remove_toc();
        self.touched();
        ok
    }

    fn bookmark_names(&self) -> Vec<String> {
        self.ed.bookmark_names()
    }

    fn toggle_field_codes(&mut self) {
        self.ed.toggle_field_codes();
        self.touched();
    }

    fn link_at(&self, page: usize, x: f64, y: f64) -> Option<String> {
        self.ed.link_at(page, x, y)
    }

    fn goto_bookmark(&mut self, name: &str) -> bool {
        self.ed.goto_bookmark(name)
    }

    fn link_at_caret(&self) -> String {
        self.ed.link_at_caret()
    }

    fn headings(&self) -> Vec<(usize, String)> {
        self.ed.headings()
    }

    /// The Navigation pane's headings: (level, text, paragraph node).
    fn nav_headings(&self) -> Vec<(usize, String, u32)> {
        self.ed.toc_headings(1, 9, None).into_iter().map(|(p, l, t)| (l, t, p)).collect()
    }

    /// Caret to the start of a paragraph (in the body).
    fn goto_node(&mut self, p: u32) -> bool {
        if self.ed.story != crate::editor::Story::Body {
            self.ed.edit_header_footer(None, false);
        }
        if self.ed.para_layout(p).is_none() {
            return false;
        }
        self.ed.move_to(crate::editor::Pos { para: p, off: 0 }, false, false);
        true
    }

    /// Caret to the start of page `i`'s body text.
    fn goto_page(&mut self, i: usize) -> bool {
        if self.ed.story != crate::editor::Story::Body {
            self.ed.edit_header_footer(None, false);
        }
        let Some(page) = self.ed.layout.pages.get(i) else { return false };
        let Some(pl) = page.lines.iter().min_by(|a, b| a.y.partial_cmp(&b.y).unwrap()) else { return false };
        let para = &self.ed.layout.paras[pl.para];
        let off = para.lines.get(pl.line).map(|l| l.pos_start).unwrap_or(0);
        let node = para.node;
        self.ed.move_to(crate::editor::Pos { para: node, off }, false, false);
        true
    }

    #[pyo3(signature = (url, text=None))]
    fn insert_hyperlink(&mut self, url: &str, text: Option<&str>) {
        self.ed.insert_hyperlink(url, text);
        self.touched();
    }

    fn remove_link(&mut self) -> bool {
        let ok = self.ed.remove_link();
        self.touched();
        ok
    }

    fn references(&self) -> Vec<(String, String, String)> {
        self.ed.references()
    }

    #[pyo3(signature = (kind, target, part="text", link=true))]
    fn insert_cross_reference(&mut self, kind: &str, target: &str, part: &str, link: bool) -> bool {
        let ok = self.ed.insert_cross_reference(kind, target, part, link);
        self.touched();
        ok
    }

    fn add_bookmark(&mut self, name: &str) -> bool {
        let ok = self.ed.add_bookmark(name);
        self.touched();
        ok
    }

    fn delete_bookmark(&mut self, name: &str) -> bool {
        let ok = self.ed.delete_bookmark(name);
        self.touched();
        ok
    }

    fn seq_count(&self, label: &str) -> usize {
        self.ed.seq_count(label)
    }

    #[pyo3(signature = (label, text="", below=true, numfmt="ARABIC", exclude_label=false))]
    fn insert_caption(&mut self, label: &str, text: &str, below: bool, numfmt: &str, exclude_label: bool) {
        self.ed.insert_caption(label, text, below, numfmt, exclude_label);
        self.touched();
    }

    // ------------------------------------------------------- review
    fn set_track_changes(&mut self, on: bool) {
        self.ed.set_track_changes(on);
    }

    fn track_changes(&self) -> bool {
        self.ed.track
    }

    fn set_author(&mut self, name: &str) {
        if !name.is_empty() {
            self.ed.author = name.to_string();
        }
    }

    /// "all", "simple", "final" or "original".
    fn set_show_formatting_changes(&mut self, on: bool) {
        self.ed.set_show_fmt_changes(on);
    }

    fn show_formatting_changes(&self) -> bool {
        self.ed.doc.show_fmt_changes
    }

    fn set_markup(&mut self, mode: &str) {
        use crate::document::Markup;
        let m = match mode {
            "all" => Markup::All,
            "final" => Markup::Final,
            "original" => Markup::Original,
            _ => Markup::Simple,
        };
        self.ed.set_markup(m);
        self.touched();
    }

    fn markup(&self) -> &'static str {
        use crate::document::Markup;
        match self.ed.doc.markup {
            Markup::All => "all",
            Markup::Simple => "simple",
            Markup::Final => "final",
            Markup::Original => "original",
        }
    }

    /// Accept / reject the change(s) at the caret or in the selection.
    fn accept_reject(&mut self, accept: bool) -> usize {
        let n = self.ed.accept_reject(accept);
        self.touched();
        n
    }

    #[pyo3(signature = (accept, authors=None))]
    fn accept_reject_all(&mut self, accept: bool, authors: Option<Vec<String>>) -> usize {
        let n = self.ed.accept_reject_all(accept, authors.as_deref());
        self.touched();
        n
    }

    fn accept_reject_next(&mut self, accept: bool) -> bool {
        let ok = self.ed.accept_reject_next(accept);
        self.touched();
        ok
    }

    /// Select from (paragraph index, offset) to (paragraph index, offset)
    /// in the body.
    fn select_range(&mut self, pa: usize, a: usize, pb: usize, b: usize) -> bool {
        let n = self.ed.layout.paras.len();
        if pa >= n || pb >= n {
            return false;
        }
        let (na, nb) = (self.ed.layout.paras[pa].node, self.ed.layout.paras[pb].node);
        if self.ed.story != crate::editor::Story::Body {
            self.ed.edit_header_footer(None, false);
        }
        self.ed.move_to(crate::editor::Pos { para: na, off: a }, false, false);
        self.ed.move_to(crate::editor::Pos { para: nb, off: b }, true, false);
        true
    }

    fn set_balloons(&mut self, on: bool) {
        self.ed.set_balloons(on);
        self.touched();
    }

    fn balloons(&self) -> bool {
        self.ed.doc.balloons
    }

    /// [(author, date, label, page, x, y, h)]
    fn revision_balloons(&self) -> Vec<(String, String, String, usize, f64, f64, f64)> {
        self.ed.revision_balloons()
    }

    fn goto_change(&mut self, forward: bool) -> bool {
        self.ed.goto_change(forward)
    }

    /// [(type, author, date, para index, start, end, text)]
    fn changes(&self) -> Vec<(String, String, String, Option<usize>, usize, usize, String)> {
        self.ed.change_list()
    }

    /// Comments: [{id, author, initials, date, text, parent, done, rects:
    /// [(page, x, y, w, h)], anchor: (page, x, y) or None}]
    fn comments<'py>(&self, py: Python<'py>) -> PyResult<Vec<Bound<'py, PyDict>>> {
        let mut out = Vec::new();
        for c in self.ed.comments() {
            let d = PyDict::new_bound(py);
            d.set_item("id", &c.id)?;
            d.set_item("author", &c.author)?;
            d.set_item("initials", &c.initials)?;
            d.set_item("date", &c.date)?;
            d.set_item("text", &c.text)?;
            d.set_item("parent", c.parent.clone())?;
            d.set_item("done", c.done)?;
            let rects = c.range.map(|(a, b)| self.ed.body_range_rects(a, b)).unwrap_or_default();
            let anchor = c.range.and_then(|(a, _)| {
                self.ed.body_range_rects(a, a).first().map(|r| (r.0, r.1, r.2, r.4))
            }).or_else(|| rects.first().map(|r| (r.0, r.1, r.2, r.4)));
            d.set_item("rects", rects)?;
            d.set_item("anchor", anchor)?;
            out.push(d);
        }
        Ok(out)
    }

    #[pyo3(signature = (text, author=""))]
    fn insert_comment(&mut self, text: &str, author: &str) -> Option<String> {
        let r = self.ed.insert_comment(text, author);
        self.touched();
        r
    }

    #[pyo3(signature = (id, text, author=""))]
    fn reply_comment(&mut self, id: &str, text: &str, author: &str) -> Option<String> {
        let r = self.ed.reply_comment(id, text, author);
        self.touched();
        r
    }

    #[pyo3(signature = (id, done=None))]
    fn resolve_comment(&mut self, id: &str, done: Option<bool>) -> bool {
        let r = self.ed.resolve_comment(id, done);
        self.touched();
        r
    }

    fn edit_comment(&mut self, id: &str, text: &str) -> bool {
        let r = self.ed.edit_comment(id, text);
        self.touched();
        r
    }

    fn delete_comments(&mut self, ids: Vec<String>) -> usize {
        let r = self.ed.delete_comments(&ids);
        self.touched();
        r
    }

    #[pyo3(signature = (author=None))]
    fn delete_all_comments(&mut self, author: Option<String>) -> usize {
        let r = self.ed.delete_all_comments(author.as_deref());
        self.touched();
        r
    }

    fn comment_at_caret(&self) -> Option<String> {
        self.ed.comment_at_caret()
    }

    fn goto_comment(&mut self, forward: bool) -> bool {
        self.ed.goto_comment(forward)
    }

    // ----------------------------------------------------------- clipboard
    /// The selection as a fragment of the document (for pasting with its
    /// formatting), or None.
    fn copy_fragment(&mut self) -> Option<String> {
        self.ed.copy_fragment()
    }

    // ------------------------------------------------------- find, tools
    /// Find: the options dict (match_case, whole_word, wildcards, prefix,
    /// suffix, ignore_punct, ignore_space, regex) -> None (no match) or
    /// whether the search wrapped.
    #[pyo3(signature = (query, opts=None, forward=true, wrap=true))]
    fn find(&mut self, query: &str, opts: Option<&Bound<'_, PyDict>>, forward: bool, wrap: bool) -> PyResult<Option<bool>> {
        let o = find_opts(opts)?;
        self.ed.find(query, &o, forward, wrap).map_err(err)
    }

    /// Every match: [(para node, off, para node, off, context)], the
    /// context with \x01 \x02 around the match.
    #[pyo3(signature = (query, opts=None))]
    fn find_all(&self, query: &str, opts: Option<&Bound<'_, PyDict>>) -> PyResult<Vec<(u32, usize, u32, usize, String)>> {
        let o = find_opts(opts)?;
        Ok(self.ed.find_all(query, &o).map_err(err)?.into_iter().map(|(a, b, c)| (a.para, a.off, b.para, b.off, c)).collect())
    }

    /// The paragraphs on a page with their text and languages (spelling as you type).
    fn page_text(&self, page: usize) -> Vec<(u32, String, Vec<(usize, usize, String)>)> {
        self.ed.page_text(page)
    }

    /// Rectangles [(page, x, y, w, h)] of a range given by nodes.
    fn range_rects(&self, pa: u32, a: usize, pb: u32, b: usize) -> Vec<(usize, f64, f64, f64, f64)> {
        self.ed.body_range_rects(crate::editor::Pos { para: pa, off: a }, crate::editor::Pos { para: pb, off: b })
    }

    /// Select a range given by nodes (from find_all).
    /// The selection in document order: (para, off, para, off).
    fn selection_range(&self) -> (u32, usize, u32, usize) {
        let (a, b) = self.ed.selection();
        (a.para, a.off, b.para, b.off)
    }

    fn anchor_pos(&self) -> (u32, usize) {
        (self.ed.anchor.para, self.ed.anchor.off)
    }

    fn select_nodes(&mut self, pa: u32, a: usize, pb: u32, b: usize) -> bool {
        if self.ed.para_layout(pa).is_none() || self.ed.para_layout(pb).is_none() {
            return false;
        }
        self.ed.move_to(crate::editor::Pos { para: pa, off: a }, false, false);
        self.ed.move_to(crate::editor::Pos { para: pb, off: b }, true, false);
        true
    }

    #[pyo3(signature = (query, rep, opts=None))]
    fn replace_one(&mut self, query: &str, rep: &str, opts: Option<&Bound<'_, PyDict>>) -> PyResult<bool> {
        let o = find_opts(opts)?;
        let r = self.ed.replace_one(query, rep, &o).map_err(err)?;
        self.touched();
        Ok(r)
    }

    #[pyo3(signature = (query, rep, opts=None))]
    fn replace_all(&mut self, query: &str, rep: &str, opts: Option<&Bound<'_, PyDict>>) -> PyResult<usize> {
        let o = find_opts(opts)?;
        let n = self.ed.replace_all(query, rep, &o).map_err(err)?;
        self.touched();
        Ok(n)
    }

    fn insert_break(&mut self, kind: &str) -> bool {
        let ok = self.ed.insert_break(kind);
        self.touched();
        ok
    }

    /// Go To: kind ("Page", "Section", "Line", "Bookmark", "Comment",
    /// "Footnote", "Endnote", "Table", "Graphic", "Equation", "Heading"),
    /// a number, "+n"/"-n" or "" for the next.
    fn goto(&mut self, kind: &str, what: &str) -> bool {
        self.ed.goto(kind, what)
    }

    fn goto_count(&self, kind: &str) -> usize {
        if kind == "Page" { self.ed.page_count() } else { self.ed.goto_targets(kind).len() }
    }

    /// Line numbers for the caret's section (or all with all=True):
    /// restart "continuous"/"newPage"/"newSection" or None for off.
    #[pyo3(signature = (restart, by=1, start=0, dist=0, all=false))]
    fn set_line_numbers(&mut self, restart: Option<&str>, by: i32, start: i32, dist: i32, all: bool) -> bool {
        let sec = if all { None } else { Some(self.ed.current_section()) };
        let ok = self.ed.set_line_numbers(sec, restart, by, start, dist);
        self.touched();
        ok
    }

    fn line_numbers(&self) -> Option<(String, i32, i32, i32)> {
        self.ed.line_numbers(self.ed.current_section())
    }

    fn set_hyphenation_options(&mut self, zone: i32, limit: i32) {
        self.ed.set_hyphenation_options(zone, limit);
        self.touched();
    }

    fn hyphenation_options(&self) -> (i32, i32) {
        self.ed.hyphenation_options()
    }

    /// Where a word may be hyphenated (after k letters).
    fn hyph_points(&self, word: &str) -> Vec<usize> {
        crate::hyph::patterns("en-US").map(|p| p.points(word)).unwrap_or_default()
    }

    /// Manual Hyphenation's candidates: the first word of each body line
    /// after a paragraph's first: (paragraph node, offset, word).
    fn line_start_words(&self) -> Vec<(u32, usize, String)> {
        let mut out = Vec::new();
        let n = self.ed.layout.body_count.min(self.ed.layout.paras.len());
        for p in &self.ed.layout.paras[..n] {
            for l in p.lines.iter().skip(1) {
                let mut w = String::new();
                let mut off = None;
                for u in &p.units[l.start..l.end] {
                    match u.kind {
                        crate::layout::UnitKind::Char(c) if c.is_alphabetic() => {
                            if off.is_none() {
                                off = Some(u.pos);
                            }
                            w.push(c);
                        }
                        _ if off.is_none() => {}
                        _ => break,
                    }
                }
                if let Some(o) = off {
                    if w.chars().count() >= 5 {
                        out.push((p.node, o, w));
                    }
                }
            }
        }
        out
    }

    #[pyo3(signature = (mode, lines=3, dist=0, font=None))]
    fn set_drop_cap(&mut self, mode: &str, lines: i32, dist: i32, font: Option<&str>) -> bool {
        let ok = self.ed.set_drop_cap(mode, lines, dist, font);
        self.touched();
        ok
    }

    fn drop_cap_info(&self) -> Option<(String, i32, i32)> {
        self.ed.drop_cap_info()
    }

    /// Design > Watermark. kind "none", "text" (text, font, size or None,
    /// colour, semitransparent, diagonal) or "picture" (path, scale or None,
    /// washout).
    #[pyo3(signature = (kind, text="", font="Calibri", size=None, color=0xC0C0C0, semi=true, diagonal=true, path="", scale=None, washout=true))]
    #[allow(clippy::too_many_arguments)]
    fn set_watermark(&mut self, kind: &str, text: &str, font: &str, size: Option<f64>, color: u32, semi: bool,
                     diagonal: bool, path: &str, scale: Option<f64>, washout: bool) -> PyResult<bool> {
        let bytes;
        let wm = match kind {
            "text" => crate::editor::Watermark::Text(text, font, size, color, semi, diagonal),
            "picture" => {
                bytes = std::fs::read(path).map_err(|e| err(e.to_string()))?;
                crate::editor::Watermark::Picture(&bytes, path.rsplit('/').next().unwrap_or(path), scale, washout)
            }
            _ => crate::editor::Watermark::None,
        };
        let ok = self.ed.set_watermark(wm);
        self.touched();
        Ok(ok)
    }

    fn has_watermark(&self) -> bool {
        self.ed.has_watermark()
    }

    fn page_hf_kind(&self, pg: usize) -> usize {
        self.ed.page_hf_kind(pg)
    }

    #[pyo3(signature = (sec, footer, which=0))]
    fn ensure_header_footer_kind(&mut self, sec: usize, footer: bool, which: usize) -> Option<usize> {
        let r = self.ed.ensure_header_footer_kind(sec, footer, which);
        self.touched();
        r
    }

    /// Design > Colors: name and the 12 scheme colours (dk1, lt1, dk2,
    /// lt2, accent1-6, hlink, folHlink).
    fn set_theme_colors(&mut self, name: &str, colors: Vec<u32>) -> bool {
        let ok = self.ed.set_theme_colors(name, &colors);
        self.touched();
        ok
    }

    fn set_theme_fonts(&mut self, name: &str, major: &str, minor: &str) -> bool {
        let ok = self.ed.set_theme_fonts(name, major, minor);
        self.touched();
        ok
    }

    fn theme_info(&self) -> (String, String, String, String) {
        self.ed.theme_info()
    }

    /// The theme's colour scheme: {slot: rgb}.
    fn theme_colors(&self) -> std::collections::HashMap<String, u32> {
        self.ed.doc.styles.theme.colors.clone()
    }

    fn set_paragraph_spacing(&mut self, before: i32, after: i32, line: i32) -> bool {
        let ok = self.ed.set_paragraph_spacing(before, after, line);
        self.touched();
        ok
    }

    fn save_as_template(&mut self, template: &str, out: &str) -> PyResult<()> {
        self.ed.save_as_template(template, out).map_err(err)
    }

    fn insert_blank_page(&mut self) -> bool {
        let ok = self.ed.insert_blank_page();
        self.touched();
        ok
    }

    fn change_case(&mut self, mode: &str) -> bool {
        let ok = self.ed.change_case(mode);
        self.touched();
        ok
    }

    #[pyo3(signature = (header=false))]
    fn sort_items(&self, header: bool) -> Option<(bool, Vec<Vec<String>>)> {
        self.ed.sort_items(header)
    }

    #[pyo3(signature = (order, header=false))]
    fn sort_apply(&mut self, order: Vec<usize>, header: bool) -> bool {
        let ok = self.ed.sort_apply(&order, header);
        self.touched();
        ok
    }

    #[pyo3(signature = (descending=false, numeric=false, header=false))]
    fn sort_paras(&mut self, descending: bool, numeric: bool, header: bool) -> bool {
        let ok = self.ed.sort_paras(descending, numeric, header);
        self.touched();
        ok
    }

    fn copy_format(&mut self) {
        self.ed.copy_format();
    }

    fn paste_format(&mut self) -> bool {
        let ok = self.ed.paste_format();
        self.touched();
        ok
    }

    fn has_format(&self) -> bool {
        self.ed.has_format()
    }

    fn clear_format(&mut self) {
        self.ed.clear_format();
    }

    #[pyo3(signature = (fmt, text, font=None, start=None))]
    fn set_list_format(&mut self, fmt: &str, text: &str, font: Option<&str>, start: Option<i64>) -> bool {
        let ok = self.ed.set_list_format_from(fmt, text, font, start);
        self.touched();
        ok
    }

    fn remove_list(&mut self) -> bool {
        let ok = self.ed.remove_list();
        self.touched();
        ok
    }

    /// Word Count: {pages, words, chars, chars_spaces, paras, lines}.
    #[pyo3(signature = (notes=false))]
    fn stats<'py>(&self, py: Python<'py>, notes: bool) -> PyResult<Bound<'py, PyDict>> {
        let s = self.ed.stats(notes);
        let d = PyDict::new_bound(py);
        d.set_item("pages", s.pages)?;
        d.set_item("words", s.words)?;
        d.set_item("chars", s.chars)?;
        d.set_item("chars_spaces", s.chars_spaces)?;
        d.set_item("paras", s.paras)?;
        d.set_item("lines", s.lines)?;
        Ok(d)
    }

    #[pyo3(signature = (xml, same_doc=true))]
    fn paste_fragment(&mut self, xml: &str, same_doc: bool) -> bool {
        let ok = self.ed.paste_fragment(xml, same_doc);
        self.touched();
        ok
    }

    // ----------------------------------------------------------- equations
    #[pyo3(signature = (kind, xml=None))]
    fn object_effect(&mut self, kind: &str, xml: Option<&str>) -> bool {
        let r = self.ed.object_effect(kind, xml);
        self.touched();
        r
    }

    #[pyo3(signature = (kind, xml=None))]
    fn object_blip(&mut self, kind: &str, xml: Option<&str>) -> bool {
        let r = self.ed.object_blip(kind, xml);
        self.touched();
        r
    }

    #[pyo3(signature = (xml=None))]
    fn object_fill(&mut self, xml: Option<&str>) -> bool {
        let ok = self.ed.object_fill(xml);
        self.touched();
        ok
    }

    fn object_geometry(&mut self, prst: &str) -> bool {
        let ok = self.ed.object_geometry(prst);
        self.touched();
        ok
    }

    fn object_body(&mut self, attrs: Vec<(String, Option<String>)>) -> bool {
        let ok = self.ed.object_body(&attrs);
        self.touched();
        ok
    }

    #[pyo3(signature = (name, attrs=None))]
    fn object_text_prop(&mut self, name: &str, attrs: Option<Vec<(String, String)>>) -> bool {
        let ok = self.ed.object_text_prop(&PropEdit { name: name.into(), attrs });
        self.touched();
        ok
    }

    #[pyo3(signature = (xml=None))]
    fn object_outline(&mut self, xml: Option<&str>) -> bool {
        let r = self.ed.object_outline(xml);
        self.touched();
        r
    }

    fn cell_border_on(&self, side: &str) -> bool {
        self.ed.cell_border_on(side)
    }

    fn math_at(&self, page: usize, x: f64, y: f64) -> Option<u32> {
        self.ed.math_at(page, x, y).map(|n| n as u32)
    }

    /// {page, x, base, w, asc, desc, display, size} (points)
    fn math_info<'py>(&self, py: Python<'py>, id: u32) -> PyResult<Option<Bound<'py, PyDict>>> {
        let Some(m) = self.ed.math_info(id as crate::xml::NodeId) else { return Ok(None) };
        let d = PyDict::new_bound(py);
        d.set_item("page", m.page)?;
        d.set_item("x", m.x)?;
        d.set_item("base", m.base)?;
        d.set_item("w", m.w)?;
        d.set_item("asc", m.asc)?;
        d.set_item("desc", m.desc)?;
        d.set_item("display", m.display)?;
        d.set_item("size", m.size)?;
        Ok(Some(d))
    }

    fn math_xml(&self, id: u32) -> String {
        self.ed.math_xml(id as crate::xml::NodeId)
    }

    fn set_math(&mut self, id: u32, xml: &str) -> bool {
        let ok = self.ed.set_math(id as crate::xml::NodeId, xml);
        self.touched();
        ok
    }

    #[pyo3(signature = (xml, display=false))]
    fn insert_math(&mut self, xml: &str, display: bool) -> Option<u32> {
        let r = self.ed.insert_math(xml, display).map(|n| n as u32);
        self.touched();
        r
    }

    fn delete_math(&mut self, id: u32) -> bool {
        let r = self.ed.delete_math(id as crate::xml::NodeId);
        self.touched();
        r
    }

    fn caret_by_math(&mut self, id: u32, after: bool) -> bool {
        self.ed.caret_by_math(id as crate::xml::NodeId, after)
    }

    fn math_beside_caret(&self, forward: bool) -> Option<u32> {
        self.ed.math_beside_caret(forward).map(|n| n as u32)
    }

    fn set_math_display(&mut self, id: u32, display: bool) -> bool {
        let r = self.ed.set_math_display(id as crate::xml::NodeId, display);
        self.touched();
        r
    }

    /// Select several stretches [(para, off, para, off)]; formatting goes to each.
    /// How many ranges are selected (Find In and Select Similar make several).
    fn selection_count(&self) -> usize {
        if self.ed.has_selection() { 1 + self.ed.extra_sel.len() } else { 0 }
    }

    fn select_ranges(&mut self, ranges: Vec<(u32, usize, u32, usize)>) {
        let r: Vec<_> = ranges.into_iter().map(|(a, x, b, y)| (crate::editor::Pos { para: a, off: x }, crate::editor::Pos { para: b, off: y })).collect();
        self.ed.select_ranges(&r);
    }

    fn count_style_instances(&self, id: &str) -> usize {
        self.ed.count_style_instances(id)
    }

    fn select_style_instances(&mut self, id: &str) -> usize {
        self.ed.select_style_instances(id)
    }

    /// The paragraph style id at the caret.
    fn para_style_id(&self) -> String {
        let dom = &self.ed.doc.dom;
        dom.child(self.ed.caret.para, "w:pPr").and_then(|pp| dom.child(pp, "w:pStyle"))
            .and_then(|n| dom.attr(n, "w:val")).map(|v| v.to_string())
            .unwrap_or_else(|| self.ed.doc.styles.default_para.clone().unwrap_or_default())
    }

    fn list_info_of(&self, p: u32) -> Option<(i32, i32, bool, String, i32)> {
        self.ed.list_info_of(p)
    }

    fn list_info(&self) -> Option<(i32, i32, bool, String, i32)> {
        self.ed.list_info()
    }

    fn new_list_definition(&mut self, levels_xml: &str) -> i32 {
        let r = self.ed.new_list_definition(levels_xml);
        self.touched();
        r
    }

    fn apply_list_definition(&mut self, levels_xml: &str) -> bool {
        let r = self.ed.apply_list_definition(levels_xml);
        self.touched();
        r
    }

    fn restart_numbering(&mut self, start: i32) -> bool {
        let r = self.ed.restart_numbering(start);
        self.touched();
        r
    }

    fn continue_numbering(&mut self) -> bool {
        let r = self.ed.continue_numbering();
        self.touched();
        r
    }

    fn list_level_indents(&self) -> Option<(i32, i32, String)> {
        self.ed.list_level_indents()
    }

    fn set_list_level_indents(&mut self, number_at: i32, text_at: i32, suff: &str) -> bool {
        let r = self.ed.set_list_level_indents(number_at, text_at, suff);
        self.touched();
        r
    }

    /// The caret: (paragraph node, offset).
    fn caret_pos(&self) -> (u32, usize) {
        (self.ed.caret.para, self.ed.caret.off)
    }

    fn caret_para_empty(&self) -> bool {
        self.ed.caret_para_empty()
    }

    fn all_math(&self) -> Vec<u32> {
        self.ed.all_math().into_iter().map(|n| n as u32).collect()
    }

    /// Now, in a Word date picture.
    fn format_now(&self, pic: &str) -> String {
        crate::editor::format_date(&chrono::Local::now(), pic)
    }

    /// The document's file (FILENAME fields).
    fn set_file_name(&mut self, name: &str) {
        self.ed.file_name = name.to_string();
    }
}

/// Built-in style names as the original shows them ("heading 1" ->
/// "Heading 1", "toc 2" -> "TOC 2").
fn ui_name(n: &str) -> String {
    if let Some(rest) = n.strip_prefix("toc ") {
        return format!("TOC {rest}");
    }
    let mut c = n.chars();
    match c.next() {
        Some(f) if f.is_lowercase() => f.to_uppercase().chain(c).collect(),
        _ => n.to_string(),
    }
}

fn run_dict<'py>(py: Python<'py>, r: &crate::props::RunProps, st: &crate::styles::StyleSheet)
                 -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new_bound(py);
    d.set_item("font", crate::text::family_for(st, r, 'a'))?;
    d.set_item("size", r.size.unwrap_or(20) as f64 / 2.0)?;
    d.set_item("bold", r.bold.unwrap_or(false))?;
    d.set_item("italic", r.italic.unwrap_or(false))?;
    d.set_item("caps", r.caps.unwrap_or(false))?;
    d.set_item("small_caps", r.small_caps.unwrap_or(false))?;
    d.set_item("strike", r.strike.unwrap_or(false))?;
    d.set_item("dstrike", r.dstrike.unwrap_or(false))?;
    d.set_item("outline", r.outline.unwrap_or(false))?;
    d.set_item("shadow", r.shadow.unwrap_or(false))?;
    d.set_item("emboss", r.emboss.unwrap_or(false))?;
    d.set_item("imprint", r.imprint.unwrap_or(false))?;
    d.set_item("hidden", r.vanish.unwrap_or(false))?;
    d.set_item("underline", r.underline.clone().unwrap_or_else(|| "none".into()))?;
    d.set_item("underline_color", r.underline_color.map(|c| c as i64).unwrap_or(-1))?;
    d.set_item("color", match r.color {
        Some(crate::props::ColorVal::Rgb(c)) => c as i64,
        _ => -1,
    })?;
    d.set_item("highlight", r.highlight.clone().unwrap_or_else(|| "none".into()))?;
    d.set_item("vert_align", r.vert_align.clone().unwrap_or_else(|| "baseline".into()))?;
    d.set_item("position", r.position.unwrap_or(0))?;
    d.set_item("spacing", r.spacing.unwrap_or(0))?;
    d.set_item("scale", r.scale.unwrap_or(100))?;
    d.set_item("kern", r.kern.unwrap_or(0))?;
    d.set_item("style", r.style.clone().unwrap_or_default())?;
    Ok(d)
}

fn para_dict<'py>(py: Python<'py>, p: &crate::props::ParaProps) -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new_bound(py);
    d.set_item("align", p.jc.clone().unwrap_or_else(|| "left".into()))?;
    d.set_item("ind_left", p.ind_left.unwrap_or(0))?;
    d.set_item("ind_right", p.ind_right.unwrap_or(0))?;
    d.set_item("ind_first", p.ind_first.unwrap_or(0))?;
    d.set_item("before", p.before.unwrap_or(0))?;
    d.set_item("after", p.after.unwrap_or(0))?;
    d.set_item("line", p.line.unwrap_or(240))?;
    d.set_item("line_rule", p.line_rule.clone().unwrap_or_else(|| "auto".into()))?;
    d.set_item("contextual", p.contextual.unwrap_or(false))?;
    d.set_item("keep_next", p.keep_next.unwrap_or(false))?;
    d.set_item("keep_lines", p.keep_lines.unwrap_or(false))?;
    d.set_item("page_break_before", p.page_break_before.unwrap_or(false))?;
    d.set_item("widow", p.widow.unwrap_or(true))?;
    d.set_item("outline_lvl", p.outline_lvl.map(|v| v as i32).unwrap_or(9))?;
    d.set_item("suppress_line_numbers", p.suppress_line_numbers.unwrap_or(false))?;
    d.set_item("suppress_hyphens", p.suppress_hyphens.unwrap_or(false))?;
    d.set_item("style", p.style.clone().unwrap_or_default())?;
    let tabs: Vec<(i32, String, String)> = p
        .tab_stops()
        .iter()
        .map(|t| {
            let k = match t.kind {
                crate::props::TabKind::Center => "center",
                crate::props::TabKind::Right => "right",
                crate::props::TabKind::Decimal => "decimal",
                crate::props::TabKind::Bar => "bar",
                _ => "left",
            };
            let l = match t.leader {
                '.' => "dot",
                '-' => "hyphen",
                '_' => "underscore",
                '\u{b7}' => "middleDot",
                _ => "none",
            };
            (t.pos, k.to_string(), l.to_string())
        })
        .collect();
    d.set_item("tabs", tabs)?;
    let bd = PyDict::new_bound(py);
    for (k, b) in [("top", &p.border_top), ("bottom", &p.border_bottom), ("left", &p.border_left),
                   ("right", &p.border_right), ("between", &p.border_between)] {
        if let Some(b) = b {
            if b.style != "nil" && b.style != "none" {
                bd.set_item(k, (b.style.clone(), b.size, b.space, b.color.map(|c| c as i64).unwrap_or(-1)))?;
            }
        }
    }
    d.set_item("borders", bd)?;
    Ok(d)
}

fn find_opts(d: Option<&Bound<'_, PyDict>>) -> PyResult<crate::editor::FindOpts> {
    let mut o = crate::editor::FindOpts::default();
    let Some(d) = d else { return Ok(o) };
    let get = |k: &str| -> PyResult<bool> {
        Ok(match d.get_item(k)? {
            Some(v) => v.is_truthy()?,
            None => false,
        })
    };
    o.match_case = get("match_case")?;
    o.whole_word = get("whole_word")?;
    o.wildcards = get("wildcards")?;
    o.prefix = get("prefix")?;
    o.suffix = get("suffix")?;
    o.ignore_punct = get("ignore_punct")?;
    o.ignore_space = get("ignore_space")?;
    o.regex = get("regex")?;
    Ok(o)
}

fn val_named(name: &str, v: &str) -> PropEdit {
    PropEdit::set(name, &[("w:val", v)])
}

#[pymodule]
fn folio_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyEditor>()?;
    Ok(())
}
