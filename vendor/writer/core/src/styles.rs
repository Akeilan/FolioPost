//! Styles: docDefaults, paragraph / character / table styles with basedOn
//! chains, the theme's fonts, and the resolved formatting of a paragraph
//! or run.

use crate::props::{CellFmt, ParaProps, RunProps, TblProps};
use crate::xml::{NodeId, XmlDoc};
use std::cell::RefCell;
use std::collections::HashMap;

#[derive(Clone, Debug, PartialEq)]
pub enum StyleKind {
    Paragraph,
    Character,
    Table,
    Numbering,
}

#[derive(Clone, Debug)]
pub struct Style {
    pub id: String,
    pub name: String,
    pub kind: StyleKind,
    pub based_on: Option<String>,
    pub next: Option<String>,
    pub link: Option<String>,
    pub is_default: bool,
    pub ppr: ParaProps,
    pub rpr: RunProps,
    pub tbl: TblProps,
    pub custom: bool,
    pub auto_redefine: bool,
    pub q_format: bool,
    /// table styles: conditional formatting by type (firstRow, band1Horz...)
    pub cond: Vec<(String, CellFmt)>,
    /// table styles: the style's own cell formatting (w:tcPr)
    pub tc: CellFmt,
}

#[derive(Clone, Debug, Default)]
pub struct ThemeFonts {
    pub major_latin: String,
    pub minor_latin: String,
    pub major_east: String,
    pub minor_east: String,
    pub major_cs: String,
    pub minor_cs: String,
    /// the colour scheme: dk1, lt1, dk2, lt2, accent1..6, hlink, folHlink
    pub colors: HashMap<String, u32>,
}

#[derive(Default)]
pub struct StyleSheet {
    pub doc_ppr: ParaProps,
    pub doc_rpr: RunProps,
    pub styles: HashMap<String, Style>,
    pub default_para: Option<String>,
    pub default_char: Option<String>,
    pub default_table: Option<String>,
    pub theme: ThemeFonts,
    para_cache: RefCell<HashMap<String, (ParaProps, RunProps)>>,
    char_cache: RefCell<HashMap<String, RunProps>>,
}

impl StyleSheet {
    pub fn parse(doc: Option<&XmlDoc>, theme: Option<&XmlDoc>) -> StyleSheet {
        let mut s = StyleSheet::default();
        if let Some(t) = theme {
            s.theme = parse_theme(t);
        }
        if s.theme.minor_latin.is_empty() {
            s.theme.minor_latin = "Calibri".into();
        }
        if s.theme.major_latin.is_empty() {
            s.theme.major_latin = "Calibri Light".into();
        }
        let Some(doc) = doc else { return s };
        let root = doc.root;
        if let Some(dd) = doc.child(root, "w:docDefaults") {
            if let Some(r) = doc.child(dd, "w:rPrDefault").and_then(|n| doc.child(n, "w:rPr")) {
                s.doc_rpr = RunProps::parse(doc, r);
            }
            if let Some(p) = doc.child(dd, "w:pPrDefault").and_then(|n| doc.child(n, "w:pPr")) {
                s.doc_ppr = ParaProps::parse(doc, p);
            }
        }
        for st in doc.children_named(root, "w:style") {
            let kind = match doc.attr(st, "w:type").unwrap_or("paragraph") {
                "character" => StyleKind::Character,
                "table" => StyleKind::Table,
                "numbering" => StyleKind::Numbering,
                _ => StyleKind::Paragraph,
            };
            let id = doc.attr(st, "w:styleId").unwrap_or("").to_string();
            let val = |name: &str| doc.child(st, name).and_then(|n| doc.attr(n, "w:val")).map(String::from);
            let style = Style {
                id: id.clone(),
                name: val("w:name").unwrap_or_else(|| id.clone()),
                kind: kind.clone(),
                based_on: val("w:basedOn"),
                next: val("w:next"),
                link: val("w:link"),
                is_default: matches!(doc.attr(st, "w:default"), Some("1") | Some("true") | Some("on")),
                ppr: doc.child(st, "w:pPr").map(|n| ParaProps::parse(doc, n)).unwrap_or_default(),
                rpr: doc.child(st, "w:rPr").map(|n| RunProps::parse(doc, n)).unwrap_or_default(),
                tbl: doc.child(st, "w:tblPr").map(|n| TblProps::parse(doc, n)).unwrap_or_default(),
                custom: matches!(doc.attr(st, "w:customStyle"), Some("1") | Some("true")),
                auto_redefine: doc.child(st, "w:autoRedefine").is_some(),
                q_format: doc.child(st, "w:qFormat").is_some(),
                cond: doc
                    .children_named(st, "w:tblStylePr")
                    .map(|c| (doc.attr(c, "w:type").unwrap_or("wholeTable").to_string(), CellFmt::parse_style_part(doc, c)))
                    .collect(),
                tc: doc.child(st, "w:tcPr").map(|c| CellFmt::parse_tc(doc, c)).unwrap_or_default(),
            };
            if style.is_default {
                match kind {
                    StyleKind::Paragraph => s.default_para = Some(id.clone()),
                    StyleKind::Character => s.default_char = Some(id.clone()),
                    StyleKind::Table => s.default_table = Some(id.clone()),
                    _ => {}
                }
            }
            s.styles.insert(id, style);
        }
        s
    }

    pub fn invalidate(&self) {
        self.para_cache.borrow_mut().clear();
        self.char_cache.borrow_mut().clear();
    }

    fn chain(&self, id: &str) -> Vec<&Style> {
        let mut out = Vec::new();
        let mut cur = self.styles.get(id);
        while let Some(st) = cur {
            if out.iter().any(|s: &&Style| s.id == st.id) || out.len() > 32 {
                break;
            }
            out.push(st);
            cur = st.based_on.as_deref().and_then(|b| self.styles.get(b));
        }
        out.reverse();
        out
    }

    /// The paragraph formatting and the paragraph-level run formatting of a
    /// paragraph style (docDefaults included).
    pub fn para_style(&self, id: Option<&str>) -> (ParaProps, RunProps) {
        let id = id
            .filter(|i| self.styles.contains_key(*i))
            .map(String::from)
            .or_else(|| self.default_para.clone())
            .unwrap_or_default();
        if let Some(v) = self.para_cache.borrow().get(&id) {
            return v.clone();
        }
        let mut p = self.doc_ppr.clone();
        let mut r = self.doc_rpr.clone();
        for st in self.chain(&id) {
            p.apply(&st.ppr);
            r.apply_style(&st.rpr);
        }
        p.style = Some(id.clone());
        r.style = None;
        self.para_cache.borrow_mut().insert(id, (p.clone(), r.clone()));
        (p, r)
    }

    /// A table style's own formatting (its basedOn chain, no docDefaults):
    /// table, paragraph and run properties.
    pub fn table_style(&self, id: Option<&str>) -> (TblProps, ParaProps, RunProps) {
        let id = id.filter(|i| self.styles.contains_key(*i)).map(String::from).or_else(|| self.default_table.clone());
        let mut t = TblProps::default();
        let mut p = ParaProps::default();
        let mut r = RunProps::default();
        if let Some(id) = id {
            for st in self.chain(&id) {
                t.apply(&st.tbl);
                p.apply(&st.ppr);
                r.apply_style(&st.rpr);
            }
        }
        (t, p, r)
    }

    /// A table style's conditional formatting (its chain merged): the cell
    /// formatting of the whole table, and each condition's.
    pub fn table_conditions(&self, id: Option<&str>) -> (CellFmt, Vec<(String, CellFmt)>) {
        let id = id.filter(|i| self.styles.contains_key(*i)).map(String::from).or_else(|| self.default_table.clone());
        let mut whole = CellFmt::default();
        let mut conds: Vec<(String, CellFmt)> = Vec::new();
        if let Some(id) = id {
            for st in self.chain(&id) {
                whole.apply(&st.tc);
                for (k, f) in &st.cond {
                    if k == "wholeTable" {
                        whole.apply(f);
                        continue;
                    }
                    match conds.iter_mut().find(|(n, _)| n == k) {
                        Some((_, c)) => c.apply(f),
                        None => conds.push((k.clone(), f.clone())),
                    }
                }
            }
        }
        (whole, conds)
    }

    /// Paragraph formatting of a paragraph in a table: the table style sits
    /// between docDefaults and the paragraph style, and overrides the
    /// default paragraph style.
    pub fn para_style_in_table(&self, id: Option<&str>, tp: &ParaProps, tr: &RunProps) -> (ParaProps, RunProps) {
        let id = id
            .filter(|i| self.styles.contains_key(*i))
            .map(String::from)
            .or_else(|| self.default_para.clone())
            .unwrap_or_default();
        let is_default = Some(&id) == self.default_para.as_ref();
        let mut p = self.doc_ppr.clone();
        let mut r = self.doc_rpr.clone();
        if is_default {
            for st in self.chain(&id) {
                p.apply(&st.ppr);
                r.apply_style(&st.rpr);
            }
            p.apply(tp);
            r.apply(tr);
        } else {
            p.apply(tp);
            r.apply(tr);
            for st in self.chain(&id) {
                p.apply(&st.ppr);
                r.apply_style(&st.rpr);
            }
        }
        p.style = Some(id);
        r.style = None;
        (p, r)
    }

    /// The run formatting a character style adds (its chain only).
    pub fn char_style(&self, id: &str) -> RunProps {
        if let Some(v) = self.char_cache.borrow().get(id) {
            return v.clone();
        }
        let mut r = RunProps::default();
        for st in self.chain(id) {
            if st.kind == StyleKind::Character {
                r.apply_style(&st.rpr);
            }
        }
        self.char_cache.borrow_mut().insert(id.to_string(), r.clone());
        r
    }

    /// Resolved run formatting: paragraph style, then character style, then
    /// direct formatting.
    pub fn run(&self, para_rpr: &RunProps, direct: &RunProps) -> RunProps {
        let mut r = para_rpr.clone();
        if let Some(cs) = direct.style.as_deref() {
            r.apply_style(&self.char_style(cs));
        }
        r.apply(direct);
        r
    }

    /// The font family for a theme font slot ("minorHAnsi", "majorAscii"...).
    pub fn theme_font(&self, slot: &str) -> Option<String> {
        let t = &self.theme;
        let v = match slot {
            "majorAscii" | "majorHAnsi" => &t.major_latin,
            "minorAscii" | "minorHAnsi" => &t.minor_latin,
            "majorEastAsia" => &t.major_east,
            "minorEastAsia" => &t.minor_east,
            "majorBidi" => &t.major_cs,
            "minorBidi" => &t.minor_cs,
            _ => return None,
        };
        if v.is_empty() {
            None
        } else {
            Some(v.clone())
        }
    }

    pub fn style_name(&self, id: &str) -> Option<&str> {
        self.styles.get(id).map(|s| s.name.as_str())
    }

    pub fn id_for_name(&self, name: &str) -> Option<String> {
        let l = name.to_lowercase();
        self.styles.values().find(|s| s.name.to_lowercase() == l).map(|s| s.id.clone())
    }
}

fn parse_theme(t: &XmlDoc) -> ThemeFonts {
    let mut f = ThemeFonts::default();
    // a:theme/a:themeElements/a:fontScheme/a:majorFont|a:minorFont
    fn find(t: &XmlDoc, n: NodeId, name: &str) -> Option<NodeId> {
        if t.name(n) == name {
            return Some(n);
        }
        for c in t.elements(n) {
            if let Some(x) = find(t, c, name) {
                return Some(x);
            }
        }
        None
    }
    let get = |font: Option<NodeId>, script: &str| -> String {
        font.and_then(|n| t.child(n, script))
            .and_then(|n| t.attr(n, "typeface"))
            .unwrap_or("")
            .to_string()
    };
    let major = find(t, t.root, "a:majorFont");
    let minor = find(t, t.root, "a:minorFont");
    f.major_latin = get(major, "a:latin");
    f.minor_latin = get(minor, "a:latin");
    f.major_east = get(major, "a:ea");
    f.minor_east = get(minor, "a:ea");
    f.major_cs = get(major, "a:cs");
    f.minor_cs = get(minor, "a:cs");
    if let Some(cs) = find(t, t.root, "a:clrScheme") {
        for c in t.elements(cs) {
            let key = t.name(c).trim_start_matches("a:").to_string();
            let v = t.elements(c).next().and_then(|v| {
                if t.is(v, "a:sysClr") {
                    t.attr(v, "lastClr").or(t.attr(v, "val"))
                } else {
                    t.attr(v, "val")
                }
            });
            if let Some(col) = v.and_then(|v| u32::from_str_radix(v, 16).ok()) {
                f.colors.insert(key, col);
            } else if t.elements(c).next().map(|v| t.attr(v, "val") == Some("windowText")).unwrap_or(false) {
                f.colors.insert(key, 0);
            }
        }
    }
    f
}
