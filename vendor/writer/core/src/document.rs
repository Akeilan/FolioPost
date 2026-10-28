//! The document: the package, its main XML, styles, settings and sections,
//! and the content of each paragraph as the layout sees it.

use crate::package::{Package, PkgError};
use crate::props::{int_attr, ParaProps, RunProps};
use crate::styles::StyleSheet;
use crate::xml::{Kind, NodeId, XmlDoc};

pub const W_NS: &str = "http://schemas.openxmlformats.org/wordprocessingml/2006/main";

#[derive(Clone, Debug)]
pub struct Section {
    /// twips
    pub page_w: i32,
    pub page_h: i32,
    pub top: i32,
    pub bottom: i32,
    pub left: i32,
    pub right: i32,
    pub header: i32,
    pub footer: i32,
    pub gutter: i32,
    pub cols: u32,
    pub col_space: i32,
    /// unequal columns: (width, space after) for each, twips
    pub col_defs: Vec<(i32, i32)>,
    /// document grid line pitch (twips) when lines snap to it
    pub grid_pitch: Option<i32>,
    pub start: String,
    pub title_pg: bool,
    pub v_align: String,
    pub node: Option<NodeId>,
    /// header / footer parts (index in Document::parts): default, first, even
    pub headers: [Option<usize>; 3],
    pub footers: [Option<usize>; 3],
    /// relationship ids of the references in this section's sectPr
    pub hf_rids: Vec<(bool, usize, String)>,
    /// page numbering: restart value and format
    pub pg_start: Option<i32>,
    pub pg_fmt: String,
    /// page borders (lines or art)
    pub pg_borders: Option<crate::art::PageBorders>,
    /// line numbers: count by, first number, distance from text (twips,
    /// 0 auto), restart ("newPage", "newSection", "continuous")
    pub ln_num: Option<(i32, i32, i32, String)>,
}

impl Default for Section {
    fn default() -> Self {
        // Letter, 1" margins: the original's defaults
        Section {
            page_w: 12240,
            page_h: 15840,
            top: 1440,
            bottom: 1440,
            left: 1440,
            right: 1440,
            header: 720,
            footer: 720,
            gutter: 0,
            cols: 1,
            col_space: 720,
            col_defs: Vec::new(),
            grid_pitch: None,
            start: "nextPage".into(),
            title_pg: false,
            v_align: "top".into(),
            node: None,
            headers: [None; 3],
            footers: [None; 3],
            hf_rids: Vec::new(),
            pg_start: None,
            pg_fmt: "decimal".into(),
            pg_borders: None,
            ln_num: None,
        }
    }
}

impl Section {
    pub fn parse(doc: &XmlDoc, n: NodeId) -> Section {
        let mut s = Section { node: Some(n), ..Default::default() };
        for c in doc.elements(n) {
            match doc.name(c) {
                "w:pgSz" => {
                    s.page_w = int_attr(doc, c, "w:w").unwrap_or(s.page_w);
                    s.page_h = int_attr(doc, c, "w:h").unwrap_or(s.page_h);
                }
                "w:pgMar" => {
                    s.top = int_attr(doc, c, "w:top").unwrap_or(s.top);
                    s.bottom = int_attr(doc, c, "w:bottom").unwrap_or(s.bottom);
                    s.left = int_attr(doc, c, "w:left").or_else(|| int_attr(doc, c, "w:start")).unwrap_or(s.left);
                    s.right = int_attr(doc, c, "w:right").or_else(|| int_attr(doc, c, "w:end")).unwrap_or(s.right);
                    s.header = int_attr(doc, c, "w:header").unwrap_or(s.header);
                    s.footer = int_attr(doc, c, "w:footer").unwrap_or(s.footer);
                    s.gutter = int_attr(doc, c, "w:gutter").unwrap_or(0);
                }
                "w:cols" => {
                    s.cols = int_attr(doc, c, "w:num").unwrap_or(1).max(1) as u32;
                    s.col_space = int_attr(doc, c, "w:space").unwrap_or(720);
                    let equal = doc.attr(c, "w:equalWidth").map(|v| v != "0" && v != "false").unwrap_or(true);
                    if !equal {
                        s.col_defs = doc
                            .children_named(c, "w:col")
                            .map(|k| (int_attr(doc, k, "w:w").unwrap_or(0), int_attr(doc, k, "w:space").unwrap_or(0)))
                            .collect();
                        if !s.col_defs.is_empty() {
                            s.cols = s.col_defs.len() as u32;
                        }
                    }
                }
                "w:type" => s.start = doc.attr(c, "w:val").unwrap_or("nextPage").to_string(),
                "w:docGrid" => {
                    if matches!(doc.attr(c, "w:type"), Some("lines") | Some("linesAndChars") | Some("snapToChars")) {
                        s.grid_pitch = int_attr(doc, c, "w:linePitch").filter(|v| *v > 0);
                    }
                }
                "w:titlePg" => s.title_pg = crate::props::on_off(doc, c),
                "w:pgBorders" => s.pg_borders = crate::art::parse(doc, c),
                "w:lnNumType" => {
                    let by = int_attr(doc, c, "w:countBy").unwrap_or(1);
                    if by > 0 {
                        s.ln_num = Some((by, int_attr(doc, c, "w:start").unwrap_or(0),
                                         int_attr(doc, c, "w:distance").unwrap_or(0),
                                         doc.attr(c, "w:restart").unwrap_or("newPage").to_string()));
                    }
                }
                "w:vAlign" => s.v_align = doc.attr(c, "w:val").unwrap_or("top").to_string(),
                "w:headerReference" | "w:footerReference" => {
                    let which = match doc.attr(c, "w:type").unwrap_or("default") {
                        "first" => 1,
                        "even" => 2,
                        _ => 0,
                    };
                    if let Some(rid) = doc.attr(c, "r:id") {
                        s.hf_rids.push((doc.name(c) == "w:headerReference", which, rid.to_string()));
                    }
                }
                "w:pgNumType" => {
                    s.pg_start = int_attr(doc, c, "w:start");
                    if let Some(f) = doc.attr(c, "w:fmt") {
                        s.pg_fmt = f.to_string();
                    }
                }
                _ => {}
            }
        }
        s
    }

    /// Left edge of column `i` from the page's left, twips.
    pub fn col_left(&self, i: u32) -> i32 {
        let base = self.left + self.gutter;
        if !self.col_defs.is_empty() {
            return base + self.col_defs.iter().take(i as usize).map(|(w, sp)| w + sp).sum::<i32>();
        }
        base + i as i32 * (self.text_width() + self.col_space)
    }

    /// Width of the text column, twips.
    pub fn text_width(&self) -> i32 {
        if let Some(&(w, _)) = self.col_defs.first() {
            return w.max(1);
        }
        let w = self.page_w - self.left - self.right - self.gutter;
        if self.cols > 1 {
            (w - self.col_space * (self.cols as i32 - 1)) / self.cols as i32
        } else {
            w
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum BlockKind {
    Para,
    Table,
}

#[derive(Clone, Debug)]
pub struct Block {
    pub node: NodeId,
    pub kind: BlockKind,
    pub section: usize,
}

/// One piece of a paragraph's content.
#[derive(Clone, Debug, PartialEq)]
pub enum Item {
    Text(String),
    Tab,
    LineBreak,
    PageBreak,
    ColumnBreak,
    /// an inline picture or object: width, height in points
    Object(f64, f64, std::sync::Arc<crate::pictures::Pic>),
    /// the paragraph's text continues, but nothing shows (field codes...)
    Hidden(String),
    /// a floating picture, shape or text box anchored here
    Anchor(Option<std::sync::Arc<crate::pictures::Float>>),
    /// text shown as one piece over `len` positions (a note mark, a page
    /// number)
    Atom(String, usize),
    /// an equation (m:oMath); true: a display equation (in m:oMathPara)
    Math(NodeId, bool),
}

impl Item {
    /// How many positions the item takes in the paragraph's text.
    pub fn len(&self) -> usize {
        match self {
            Item::Text(t) => t.chars().count(),
            Item::Hidden(_) => 0,
            Item::Atom(_, n) => *n,
            _ => 1,
        }
    }

    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }
}

#[derive(Clone, Debug)]
pub struct Piece {
    pub item: Item,
    /// the w:r the piece comes from (None: generated)
    pub run: Option<NodeId>,
    /// the w:t (or w:tab, w:br...) node
    pub node: Option<NodeId>,
    pub rpr: RunProps,
    /// markup: "ins" / "del" / ""
    pub change: &'static str,
    /// a hyperlink around it
    pub link: Option<NodeId>,
    /// the result of a field the layout fills in (PAGE, NUMPAGES...)
    pub field: Option<&'static str>,
    /// a footnote / endnote reference: the note
    pub note: Option<NodeId>,
    /// its formatting was changed with tracking on
    pub fmt_change: bool,
}

/// A part of the package edited along with the main document (a header,
/// footer, the footnotes or endnotes). Its XML lives in the main document's
/// tree as a detached subtree, so editing and undo work the same there.
pub struct SubPart {
    pub name: String,
    /// "header", "footer", "footnotes", "endnotes"
    pub kind: &'static str,
    /// its root element in `Document::dom` (not attached to the body)
    pub root: NodeId,
    pub prolog: String,
    /// its pictures by relationship id
    pub images: std::collections::HashMap<String, crate::pictures::ImageData>,
}

/// Footnotes and endnotes: where each is and the mark it shows.
#[derive(Default)]
pub struct Notes {
    pub footnotes: std::collections::HashMap<String, NodeId>,
    pub endnotes: std::collections::HashMap<String, NodeId>,
    /// reference (w:footnoteReference) -> mark
    pub numbers: std::collections::HashMap<NodeId, String>,
    /// note (w:footnote) -> mark
    pub marks: std::collections::HashMap<NodeId, String>,
    /// the separators (w:footnote w:type="separator" / "continuationSeparator")
    pub fn_sep: Option<NodeId>,
    pub en_sep: Option<NodeId>,
    /// notes in the order their references come
    pub fn_order: Vec<NodeId>,
    pub en_order: Vec<NodeId>,
    pub fn_fmt: String,
    pub en_fmt: String,
    pub fn_start: i32,
    pub en_start: i32,
    /// numRestart: "continuous", "eachSect", "eachPage"
    pub fn_restart: String,
    pub en_restart: String,
    /// pos: footnotes "pageBottom" / "beneathText", endnotes "docEnd" / "sectEnd"
    pub fn_pos: String,
    pub en_pos: String,
    /// the note settings changed: write them back
    pub pr_dirty: bool,
}

pub struct Settings {
    /// w:doNotUseHTMLParagraphAutoSpacing
    pub no_html_spacing: bool,
    pub default_tab: i32,
    pub compat_mode: i32,
    pub even_odd_headers: bool,
    /// w:trackRevisions
    pub track_revisions: bool,
    /// m:mathPr/m:mathFont
    pub math_font: Option<String>,
    /// w:mirrorMargins: left and right margins become inside and outside
    pub mirror_margins: bool,
    /// w:autoHyphenation, w:hyphenationZone (twips), w:doNotHyphenateCaps,
    /// w:consecutiveHyphenLimit (0: no limit)
    pub auto_hyphenation: bool,
    pub hyphenation_zone: i32,
    pub no_hyphenate_caps: bool,
    pub hyphen_limit: i32,
}

/// A page background beyond a plain colour (Fill Effects).
#[derive(Clone, Debug)]
pub struct PageFill {
    /// gradient, gradientRadial, pattern, frame (a stretched picture), tile
    pub kind: String,
    pub c1: u32,
    pub c2: u32,
    pub angle: f64,
    pub focus: String,
    pub image: Option<crate::pictures::ImageData>,
    pub pattern: String,
}

pub struct Document {
    pub numbering: crate::numbering::Numbering,
    /// numbering.xml (edited in place; None if the document has no lists yet)
    pub num_dom: Option<XmlDoc>,
    pub num_part: Option<String>,
    /// styles.xml (edited in place) and the theme its fonts come from
    pub styles_dom: Option<XmlDoc>,
    pub styles_part: Option<String>,
    pub theme_dom: Option<XmlDoc>,
    pub pkg: Package,
    pub main: String,
    pub dom: XmlDoc,
    pub styles: StyleSheet,
    pub settings: Settings,
    pub sections: Vec<Section>,
    pub blocks: Vec<Block>,
    pub body: NodeId,
    /// relationship id (of the main part) -> image part
    pub images: std::collections::HashMap<String, crate::pictures::ImageData>,
    pub parts: Vec<SubPart>,
    /// headers and footers by the main part's relationship id
    pub hf_by_rid: std::collections::HashMap<String, usize>,
    pub notes: Notes,
    /// show field codes instead of their results (Alt+F9)
    pub show_codes: bool,
    /// how tracked changes show
    pub markup: Markup,
    /// deletions shown in balloons in the margin (All Markup), not inline
    pub balloons: bool,
    /// formatting changes marked (Show Markup > Formatting)
    pub show_fmt_changes: bool,
}

/// Display for Review.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Markup {
    /// insertions underlined, deletions struck through, in colour
    All,
    /// the final text, with change bars
    Simple,
    /// the final text
    Final,
    /// the text before the changes
    Original,
}

#[derive(Debug)]
pub struct DocError(pub String);

impl From<PkgError> for DocError {
    fn from(e: PkgError) -> Self {
        DocError(e.to_string())
    }
}

impl std::fmt::Display for DocError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

impl Document {
    pub fn open(bytes: &[u8]) -> Result<Document, DocError> {
        let mut pkg = Package::open(bytes)?;
        let main = pkg.main_part()?;
        let dom = pkg.take_xml(&main)?;
        let styles_part = pkg.related(&main, "/styles");
        let theme_part = pkg.related(&main, "/theme");
        let settings_part = pkg.related(&main, "/settings");
        let theme = theme_part.and_then(|p| pkg.xml(&p).ok().cloned());
        let styles_xml = styles_part.as_ref().and_then(|p| pkg.take_xml(p).ok());
        let styles = StyleSheet::parse(styles_xml.as_ref(), theme.as_ref());
        let mut settings = Settings { no_html_spacing: false, default_tab: 720, compat_mode: 15, even_odd_headers: false, track_revisions: false, math_font: None, mirror_margins: false,
                                     auto_hyphenation: false, hyphenation_zone: 360, no_hyphenate_caps: false, hyphen_limit: 0 };
        if let Some(sp) = settings_part {
            if let Ok(s) = pkg.xml(&sp) {
                if let Some(t) = s.child(s.root, "w:defaultTabStop") {
                    settings.default_tab = int_attr(s, t, "w:val").unwrap_or(720).max(1);
                }
                settings.even_odd_headers = s.child(s.root, "w:evenAndOddHeaders").is_some();
                settings.math_font = crate::math::doc_math_font(Some(s));
                settings.mirror_margins = s.child(s.root, "w:mirrorMargins")
                    .map_or(false, |t| !matches!(s.attr(t, "w:val"), Some("0" | "false" | "off")));
                let flag = |name: &str| s.child(s.root, name)
                    .map_or(false, |t| !matches!(s.attr(t, "w:val"), Some("0" | "false" | "off")));
                settings.auto_hyphenation = flag("w:autoHyphenation");
                settings.no_hyphenate_caps = flag("w:doNotHyphenateCaps");
                if let Some(t) = s.child(s.root, "w:hyphenationZone") {
                    settings.hyphenation_zone = int_attr(s, t, "w:val").unwrap_or(360).max(0);
                }
                if let Some(t) = s.child(s.root, "w:consecutiveHyphenLimit") {
                    settings.hyphen_limit = int_attr(s, t, "w:val").unwrap_or(0).max(0);
                }
                settings.track_revisions = s.child(s.root, "w:trackRevisions")
                    .map_or(false, |t| !matches!(s.attr(t, "w:val"), Some("0" | "false" | "off")));
                if let Some(c) = s.child(s.root, "w:compat") {
                    settings.no_html_spacing = s.child(c, "w:doNotUseHTMLParagraphAutoSpacing").is_some();
                    for cs in s.children_named(c, "w:compatSetting") {
                        if s.attr(cs, "w:name") == Some("compatibilityMode") {
                            settings.compat_mode = s.attr(cs, "w:val").and_then(|v| v.parse().ok()).unwrap_or(15);
                        }
                    }
                }
            }
        }
        let num_part = pkg.related(&main, "/numbering");
        let num_dom = num_part.as_ref().and_then(|p| pkg.take_xml(p).ok());
        let numbering = num_dom.as_ref().map(crate::numbering::Numbering::parse).unwrap_or_default();
        let body = dom
            .child(dom.root, "w:body")
            .ok_or_else(|| DocError("the document has no body".into()))?;
        let images = Self::image_rels(&mut pkg, &main);
        // headers, footers and notes join the main tree (detached)
        let mut dom = dom;
        let mut parts = Vec::new();
        let mut hf_by_rid = std::collections::HashMap::new();
        let mut notes = Notes { fn_fmt: "decimal".into(), en_fmt: "lowerRoman".into(), fn_start: 1, en_start: 1,
                                ..Default::default() };
        for r in pkg.rels(&main) {
            let kind: &'static str = if r.kind.ends_with("/header") {
                "header"
            } else if r.kind.ends_with("/footer") {
                "footer"
            } else if r.kind.ends_with("/footnotes") {
                "footnotes"
            } else if r.kind.ends_with("/endnotes") {
                "endnotes"
            } else if r.kind.ends_with("/comments") {
                "comments"
            } else if r.kind.ends_with("/commentsExtended") {
                "commentsExtended"
            } else {
                continue;
            };
            if r.external {
                continue;
            }
            let name = Package::resolve(&main, &r.target);
            if let Some(i) = parts.iter().position(|p: &SubPart| p.name == name) {
                hf_by_rid.insert(r.id.clone(), i);
                continue;
            }
            let Ok(x) = pkg.xml(&name) else { continue };
            let x = x.clone();
            let root = dom.import_node(&x, x.root);
            let pimages = Self::image_rels(&mut pkg, &name);
            parts.push(SubPart { name, kind, root, prolog: x.prolog.clone(), images: pimages });
            let i = parts.len() - 1;
            if kind == "header" || kind == "footer" {
                hf_by_rid.insert(r.id.clone(), i);
            }
            if kind == "footnotes" || kind == "endnotes" {
                for n in dom.elements(root).collect::<Vec<_>>() {
                    let id = dom.attr(n, "w:id").unwrap_or("").to_string();
                    match dom.attr(n, "w:type") {
                        Some("separator") => {
                            if kind == "footnotes" { notes.fn_sep = Some(n) } else { notes.en_sep = Some(n) }
                        }
                        Some("continuationSeparator") | Some("continuationNotice") => {}
                        _ => {
                            if kind == "footnotes" {
                                notes.footnotes.insert(id, n);
                            } else {
                                notes.endnotes.insert(id, n);
                            }
                        }
                    }
                }
            }
        }
        if let Some(sp) = pkg.related(&main, "/settings") {
            if let Ok(sx) = pkg.xml(&sp) {
                for (tag, en) in [("w:footnotePr", false), ("w:endnotePr", true)] {
                    if let Some(pr) = sx.child(sx.root, tag) {
                        if let Some(f) = sx.child(pr, "w:numFmt").and_then(|n| sx.attr(n, "w:val")) {
                            if en { notes.en_fmt = f.to_string() } else { notes.fn_fmt = f.to_string() }
                        }
                        if let Some(v) = sx.child(pr, "w:numStart").and_then(|n| int_attr(sx, n, "w:val")) {
                            if en { notes.en_start = v } else { notes.fn_start = v }
                        }
                        if let Some(v) = sx.child(pr, "w:numRestart").and_then(|n| sx.attr(n, "w:val")) {
                            if en { notes.en_restart = v.to_string() } else { notes.fn_restart = v.to_string() }
                        }
                        if let Some(v) = sx.child(pr, "w:pos").and_then(|n| sx.attr(n, "w:val")) {
                            if en { notes.en_pos = v.to_string() } else { notes.fn_pos = v.to_string() }
                        }
                    }
                }
            }
        }
        let mut d = Document { numbering, num_dom, num_part, styles_dom: styles_xml, styles_part, theme_dom: theme, pkg, main, dom, styles, settings, sections: Vec::new(), blocks: Vec::new(), body, images, parts, hf_by_rid, notes, show_codes: false,
                               markup: Markup::Simple, balloons: false, show_fmt_changes: true };
        d.scan();
        Ok(d)
    }

    /// The image parts `part` refers to, by relationship id.
    pub fn image_rels(pkg: &mut Package, part: &str) -> std::collections::HashMap<String, crate::pictures::ImageData> {
        let mut out = std::collections::HashMap::new();
        for r in pkg.rels(part) {
            // charts too: their part, drawn from its cached values
            if r.external || !(r.kind.ends_with("/image") || r.kind.ends_with("/chart") || r.kind.ends_with("/chartEx")) {
                continue;
            }
            let name = Package::resolve(part, &r.target);
            if let Some(raw) = pkg.raw(&name) {
                out.insert(r.id, crate::pictures::ImageData { part: name, bytes: std::sync::Arc::new(raw.to_vec()) });
            }
        }
        out
    }

    pub fn open_path(path: &str) -> Result<Document, DocError> {
        let bytes = std::fs::read(path).map_err(|e| DocError(e.to_string()))?;
        Document::open(&bytes)
    }

    pub fn write(&mut self) -> Result<Vec<u8>, DocError> {
        let dom = self.dom.clone();
        self.pkg.put_xml(&self.main.clone(), dom);
        if let (Some(part), Some(nd)) = (self.num_part.clone(), self.num_dom.as_ref()) {
            self.pkg.put_xml(&part, nd.clone());
        }
        if let (Some(part), Some(sd)) = (self.styles_part.clone(), self.styles_dom.as_ref()) {
            self.pkg.put_xml(&part, sd.clone());
        }
        self.write_settings();
        for p in &self.parts {
            let mut x = XmlDoc { prolog: p.prolog.clone(), ..Default::default() };
            x.root = x.import_node(&self.dom, p.root);
            self.pkg.put_xml(&p.name, x);
        }
        let out = self.pkg.write()?;
        Ok(out)
    }

    /// Settings the editor changes (Track Changes, mirror margins, odd and
    /// even headers) go back into settings.xml.
    fn write_settings(&mut self) {
        let main = self.main.clone();
        let Some(sp) = self.pkg.related(&main, "/settings") else { return };
        let flags = [("w:trackRevisions", self.settings.track_revisions),
                     ("w:mirrorMargins", self.settings.mirror_margins),
                     ("w:evenAndOddHeaders", self.settings.even_odd_headers),
                     ("w:autoHyphenation", self.settings.auto_hyphenation),
                     ("w:doNotHyphenateCaps", self.settings.no_hyphenate_caps)];
        let Ok(x) = self.pkg.xml_mut(&sp) else { return };
        for (name, on) in flags {
            set_settings_flag(x, name, on);
        }
        let zone = self.settings.hyphenation_zone;
        let limit = self.settings.hyphen_limit;
        set_settings_val(x, "w:hyphenationZone", if zone != 360 { Some(zone) } else { None });
        set_settings_val(x, "w:consecutiveHyphenLimit", if limit > 0 { Some(limit) } else { None });
        if self.notes.pr_dirty {
            let n = &self.notes;
            let want = [("w:footnotePr", n.fn_pos.as_str(), "pageBottom", n.fn_fmt.as_str(), "decimal", n.fn_start, n.fn_restart.as_str()),
                        ("w:endnotePr", n.en_pos.as_str(), "docEnd", n.en_fmt.as_str(), "lowerRoman", n.en_start, n.en_restart.as_str())];
            for (tag, pos, pos0, fmt, fmt0, start, restart) in want {
                let el = match x.child(x.root, tag) {
                    Some(e) => e,
                    None => {
                        set_settings_flag(x, tag, true);
                        x.child(x.root, tag).unwrap()
                    }
                };
                for k in x.children(el).to_vec() {
                    if matches!(x.name(k), "w:pos" | "w:numFmt" | "w:numStart" | "w:numRestart") {
                        x.detach(k);
                    }
                }
                let mut i = 0;
                let mut put = |x: &mut XmlDoc, name: &str, v: &str| {
                    let e = x.new_element(name, &[("w:val", v)]);
                    x.insert(el, i, e);
                    i += 1;
                };
                if !pos.is_empty() && pos != pos0 { put(x, "w:pos", pos); }
                if fmt != fmt0 { put(x, "w:numFmt", fmt); }
                if start != 1 { put(x, "w:numStart", &start.to_string()); }
                if !restart.is_empty() && restart != "continuous" { put(x, "w:numRestart", restart); }
            }
        }
    }

    pub fn save(&mut self, path: &str) -> Result<(), DocError> {
        let data = self.write()?;
        let tmp = format!("{}.folio-tmp", path);
        std::fs::write(&tmp, &data).map_err(|e| DocError(e.to_string()))?;
        std::fs::rename(&tmp, path).map_err(|e| DocError(e.to_string()))?;
        Ok(())
    }

    /// Page Color > Fill Effects, from the w:background's v:background v:fill.
    pub fn page_fill(&self) -> Option<PageFill> {
        let d = &self.dom;
        let bg = d.child(d.root, "w:background")?;
        let vb = d.child(bg, "v:background")?;
        let f = d.child(vb, "v:fill")?;
        let hex = |v: Option<&str>| v.and_then(|c| {
            let c = c.trim_start_matches('#');
            match c {
                "white" => Some(0xFFFFFF),
                "black" => Some(0),
                _ => u32::from_str_radix(c, 16).ok(),
            }
        });
        let c1 = hex(d.attr(vb, "fillcolor")).or_else(|| self.page_background()).unwrap_or(0xFFFFFF);
        let c2 = hex(d.attr(f, "color2")).unwrap_or(0xFFFFFF);
        let kind = d.attr(f, "type").unwrap_or("solid").to_string();
        let angle = d.attr(f, "angle").and_then(|a| a.parse::<f64>().ok()).unwrap_or(0.0);
        let focus = d.attr(f, "focusposition").unwrap_or("").to_string();
        let image = d.attr(f, "r:id").and_then(|rid| self.images.get(rid).cloned());
        let pattern = d.attr(f, "o:title").unwrap_or("").to_string();
        Some(PageFill { kind, c1, c2, angle, focus, image, pattern })
    }

    /// Design > Page Color: the document's w:background colour.
    pub fn page_background(&self) -> Option<u32> {
        let root = self.dom.root;
        let bg = self.dom.child(root, "w:background")?;
        let c = self.dom.attr(bg, "w:color")?;
        if c == "auto" {
            return None;
        }
        u32::from_str_radix(c, 16).ok()
    }

    /// Find the blocks and sections again (after structural edits).
    pub fn scan(&mut self) {
        let mut blocks = Vec::new();
        let mut sections = Vec::new();
        let body = self.body;
        let mut pending: Vec<Block> = Vec::new();
        self.scan_into(body, &mut pending, &mut sections, &mut blocks);
        // the final section
        let last = self
            .dom
            .child(body, "w:sectPr")
            .map(|n| Section::parse(&self.dom, n))
            .unwrap_or_default();
        let idx = sections.len();
        for mut b in pending {
            b.section = idx;
            blocks.push(b);
        }
        sections.push(last);
        // headers and footers: what a section doesn't set it inherits
        let mut prev_h = [None; 3];
        let mut prev_f = [None; 3];
        for s in sections.iter_mut() {
            let mut h = prev_h;
            let mut f = prev_f;
            for (is_h, which, rid) in &s.hf_rids {
                let part = self.hf_by_rid.get(rid).copied();
                if *is_h {
                    h[*which] = part;
                } else {
                    f[*which] = part;
                }
            }
            s.headers = h;
            s.footers = f;
            prev_h = h;
            prev_f = f;
        }
        self.blocks = blocks;
        self.sections = sections;
        self.number_notes();
    }

    /// Number the footnotes and endnotes in the order their references come.
    fn number_notes(&mut self) {
        fn walk(dom: &XmlDoc, n: NodeId, out: &mut Vec<NodeId>) {
            for c in dom.elements(n) {
                if dom.is(c, "w:footnoteReference") || dom.is(c, "w:endnoteReference") {
                    out.push(c);
                } else {
                    walk(dom, c, out);
                    // a section ends with this paragraph
                    if dom.is(c, "w:p") {
                        if let Some(sp) = dom.child(c, "w:pPr").and_then(|pp| dom.child(pp, "w:sectPr")) {
                            out.push(sp);
                        }
                    }
                }
            }
        }
        let mut refs = Vec::new();
        walk(&self.dom, self.body, &mut refs);
        // the notes as the parts have them now (after undo, convert...)
        let mut fns = std::collections::HashMap::new();
        let mut ens = std::collections::HashMap::new();
        for p in &self.parts {
            if p.kind != "footnotes" && p.kind != "endnotes" {
                continue;
            }
            for k in self.dom.elements(p.root) {
                let nm = self.dom.name(k);
                if nm != "w:footnote" && nm != "w:endnote" {
                    continue;
                }
                if matches!(self.dom.attr(k, "w:type"), Some("separator") | Some("continuationSeparator") | Some("continuationNotice")) {
                    continue;
                }
                let id = self.dom.attr(k, "w:id").unwrap_or("").to_string();
                if nm == "w:endnote" { ens.insert(id, k); } else { fns.insert(id, k); }
            }
        }
        self.notes.footnotes = fns;
        self.notes.endnotes = ens;
        let n = &mut self.notes;
        n.numbers.clear();
        n.marks.clear();
        n.fn_order.clear();
        n.en_order.clear();
        let (mut fi, mut ei) = (n.fn_start, n.en_start);
        for r in refs {
            let dom = &self.dom;
            if dom.is(r, "w:sectPr") {
                if n.fn_restart == "eachSect" { fi = n.fn_start; }
                if n.en_restart == "eachSect" { ei = n.en_start; }
                continue;
            }
            let en = dom.is(r, "w:endnoteReference");
            let id = dom.attr(r, "w:id").unwrap_or("");
            let note = if en { n.endnotes.get(id) } else { n.footnotes.get(id) }.copied();
            let custom = dom.attr(r, "w:customMarkFollows").map(|v| v == "1" || v == "true").unwrap_or(false);
            let mark = if custom {
                String::new()
            } else if en {
                ei += 1;
                crate::numbering::format_number(ei - 1, &n.en_fmt)
            } else {
                fi += 1;
                crate::numbering::format_number(fi - 1, &n.fn_fmt)
            };
            n.numbers.insert(r, mark.clone());
            if let Some(note) = note {
                if !n.marks.contains_key(&note) {
                    n.marks.insert(note, mark);
                    if en { n.en_order.push(note) } else { n.fn_order.push(note) }
                }
            }
        }
    }

    /// The pictures of the part node `n` is in.
    pub fn images_for(&self, n: NodeId) -> &std::collections::HashMap<String, crate::pictures::ImageData> {
        let dom = &self.dom;
        let mut top = n;
        while let Some(p) = dom.parent(top) {
            top = p;
        }
        if top != dom.root {
            if let Some(p) = self.parts.iter().find(|p| p.root == top) {
                return &p.images;
            }
        }
        &self.images
    }

    fn scan_into(&self, parent: NodeId, pending: &mut Vec<Block>, sections: &mut Vec<Section>,
                 blocks: &mut Vec<Block>) {
        let dom = &self.dom;
        for c in dom.elements(parent) {
            match dom.name(c) {
                "w:p" => {
                    pending.push(Block { node: c, kind: BlockKind::Para, section: 0 });
                    if let Some(sp) = dom.child(c, "w:pPr").and_then(|p| dom.child(p, "w:sectPr")) {
                        let idx = sections.len();
                        sections.push(Section::parse(dom, sp));
                        for mut b in pending.drain(..) {
                            b.section = idx;
                            blocks.push(b);
                        }
                    }
                }
                "w:tbl" => pending.push(Block { node: c, kind: BlockKind::Table, section: 0 }),
                "w:sdt" => {
                    if let Some(sc) = dom.child(c, "w:sdtContent") {
                        self.scan_into(sc, pending, sections, blocks);
                    }
                }
                "w:customXml" | "w:smartTag" => self.scan_into(c, pending, sections, blocks),
                _ => {}
            }
        }
    }

    // ------------------------------------------------------------ paragraphs
    pub fn para_ppr_node(&self, p: NodeId) -> Option<NodeId> {
        self.dom.child(p, "w:pPr")
    }

    /// Direct paragraph formatting.
    pub fn para_direct(&self, p: NodeId) -> ParaProps {
        self.para_ppr_node(p).map(|n| ParaProps::parse(&self.dom, n)).unwrap_or_default()
    }

    /// Resolved paragraph formatting and the paragraph's base run
    /// formatting.
    pub fn para_props(&self, p: NodeId) -> (ParaProps, RunProps) {
        let direct = self.para_direct(p);
        let (mut pp, rp) = self.styles.para_style(direct.style.as_deref());
        self.apply_numbering(&mut pp, &direct);
        pp.apply(&direct);
        (pp, rp)
    }

    /// A list level's indents and tabs sit between the paragraph style and
    /// direct formatting.
    pub fn apply_numbering(&self, pp: &mut ParaProps, direct: &ParaProps) {
        let num = direct.num_id.or(pp.num_id).unwrap_or(0);
        if num <= 0 {
            return;
        }
        let ilvl = direct.ilvl.or(pp.ilvl).unwrap_or(0).clamp(0, 8) as usize;
        if let Some(l) = self.numbering.level(num, ilvl, &self.styles) {
            let mut lp = l.ppr.clone();
            lp.style = None;
            pp.apply(&lp);
        }
    }

    /// Parse styles.xml again (after it was edited).
    pub fn reload_styles(&mut self) {
        self.styles = StyleSheet::parse(self.styles_dom.as_ref(), self.theme_dom.as_ref());
    }

    /// Parse numbering.xml again (after it was edited).
    pub fn reload_numbering(&mut self) {
        self.numbering = self.num_dom.as_ref().map(crate::numbering::Numbering::parse).unwrap_or_default();
    }

    /// Formatting of the paragraph mark (decides the height of an empty
    /// paragraph).
    pub fn mark_props(&self, p: NodeId, base: &RunProps) -> RunProps {
        let direct = self
            .para_ppr_node(p)
            .and_then(|n| self.dom.child(n, "w:rPr"))
            .map(|n| RunProps::parse(&self.dom, n))
            .unwrap_or_default();
        self.styles.run(base, &direct)
    }

    /// The kind of change the review display leaves out: "del" (the final
    /// text, or deletions in balloons), "ins" (the original) or "".
    pub fn hidden_change(&self) -> &'static str {
        match self.markup {
            Markup::Simple | Markup::Final => "del",
            Markup::Original => "ins",
            Markup::All if self.balloons => "del",
            Markup::All => "",
        }
    }

    /// The paragraph's content as the layout and editing see it.
    pub fn para_pieces(&self, p: NodeId, base: &RunProps) -> Vec<Piece> {
        let mut out = Vec::new();
        let mut st = Walk { field_depth: Vec::new(), instr: Vec::new() };
        self.walk(p, base, &mut out, "", None, &mut st);
        // the review display: deletions gone in the final view, insertions
        // in the original
        let hide = self.hidden_change();
        if !hide.is_empty() {
            for pc in out.iter_mut() {
                if pc.change == hide && !matches!(pc.item, Item::Hidden(_)) {
                    let t = match &pc.item {
                        Item::Text(t) => t.clone(),
                        other => other_text(other),
                    };
                    pc.item = Item::Hidden(t);
                }
            }
        }
        out
    }

    fn walk(&self, parent: NodeId, base: &RunProps, out: &mut Vec<Piece>, change: &'static str,
            link: Option<NodeId>, st: &mut Walk) {
        let dom = &self.dom;
        for c in dom.elements(parent) {
            match dom.name(c) {
                "w:r" => self.walk_run(c, base, out, change, link, st),
                "w:hyperlink" => self.walk(c, base, out, change, Some(c), st),
                "m:oMath" => out.push(Piece { item: Item::Math(c, false), run: None, node: Some(c), rpr: base.clone(),
                                              change, link, field: None, note: None, fmt_change: false }),
                "m:oMathPara" => {
                    let maths: Vec<NodeId> = dom.children_named(c, "m:oMath").collect();
                    for (i, m) in maths.into_iter().enumerate() {
                        if i > 0 {
                            out.push(Piece { item: Item::LineBreak, run: None, node: None, rpr: base.clone(),
                                             change, link, field: None, note: None, fmt_change: false });
                        }
                        out.push(Piece { item: Item::Math(m, true), run: None, node: Some(m), rpr: base.clone(),
                                         change, link, field: None, note: None, fmt_change: false });
                    }
                }
                "w:ins" | "w:moveTo" => self.walk(c, base, out, "ins", link, st),
                "w:del" | "w:moveFrom" => self.walk(c, base, out, "del", link, st),
                "w:smartTag" | "w:customXml" | "w:dir" | "w:bdo" => self.walk(c, base, out, change, link, st),
                "w:sdt" => {
                    if let Some(sc) = dom.child(c, "w:sdtContent") {
                        self.walk(sc, base, out, change, link, st);
                    }
                }
                "w:fldSimple" => {
                    // a field without its parts: its instruction as an attribute
                    st.field_depth.push(false);
                    st.instr.push(dom.attr(c, "w:instr").unwrap_or("").to_string());
                    self.walk(c, base, out, change, link, st);
                    st.field_depth.pop();
                    st.instr.pop();
                }
                _ => {}
            }
        }
    }

    fn walk_run(&self, r: NodeId, base: &RunProps, out: &mut Vec<Piece>, change: &'static str,
                link: Option<NodeId>, st: &mut Walk) {
        let dom = &self.dom;
        let direct = dom.child(r, "w:rPr").map(|n| RunProps::parse(dom, n)).unwrap_or_default();
        let rpr = self.styles.run(base, &direct);
        let codes = self.show_codes;
        let fmt_change = self.show_fmt_changes
            && dom.child(r, "w:rPr").map_or(false, |rp| dom.child(rp, "w:rPrChange").is_some());
        let hidden_code = if codes { st.in_result() } else { st.in_code() };
        let field = if codes { None } else { st.result_kind() };
        let push = |item: Item, node: NodeId, out: &mut Vec<Piece>| {
            let item = if hidden_code {
                match item {
                    Item::Text(t) => Item::Hidden(t),
                    other => Item::Hidden(other_text(&other)),
                }
            } else {
                item
            };
            out.push(Piece { item, run: Some(r), node: Some(node), rpr: rpr.clone(), change, link, field, note: None, fmt_change });
        };
        // mc:AlternateContent: the choice the original made (its first
        // branch), as if its content were in the run
        let mut kids: Vec<NodeId> = Vec::new();
        for &c in dom.children(r) {
            if dom.is(c, "mc:AlternateContent") {
                let branch = dom.child(c, "mc:Choice").or_else(|| dom.child(c, "mc:Fallback"));
                if let Some(b) = branch {
                    kids.extend(dom.children(b).iter().copied());
                }
            } else {
                kids.push(c);
            }
        }
        for c in kids {
            let Kind::Element { name, .. } = &dom.node(c).kind else { continue };
            match name.as_str() {
                "w:t" => {
                    let t = dom.text(c);
                    if !t.is_empty() {
                        push(Item::Text(t), c, out);
                    }
                }
                "w:delText" => {
                    let t = dom.text(c);
                    if !t.is_empty() {
                        push(Item::Text(t), c, out);
                    }
                }
                "w:instrText" | "w:delInstrText" => {
                    let t = dom.text(c);
                    if st.in_code() {
                        if let Some(i) = st.instr.last_mut() {
                            i.push_str(&t);
                        }
                    }
                    let item = if codes && !st.in_result() { Item::Atom(t, 0) } else { Item::Hidden(t) };
                    out.push(Piece { item, run: Some(r), node: Some(c), rpr: rpr.clone(), change, link,
                                     field: None, note: None, fmt_change });
                }
                "w:tab" | "w:ptab" => push(Item::Tab, c, out),
                "w:br" => {
                    let item = match dom.attr(c, "w:type") {
                        Some("page") => Item::PageBreak,
                        Some("column") => Item::ColumnBreak,
                        _ => Item::LineBreak,
                    };
                    push(item, c, out);
                }
                "w:cr" => push(Item::LineBreak, c, out),
                "w:noBreakHyphen" => push(Item::Text("\u{2011}".into()), c, out),
                "w:softHyphen" => push(Item::Text("\u{ad}".into()), c, out),
                "w:sym" => {
                    let ch = dom
                        .attr(c, "w:char")
                        .and_then(|v| u32::from_str_radix(v, 16).ok())
                        .map(|v| if (0xF000..=0xF0FF).contains(&v) { v - 0xF000 } else { v })
                        .and_then(char::from_u32)
                        .unwrap_or('\u{25a1}');
                    push(Item::Text(ch.to_string()), c, out);
                }
                "w:fldChar" => {
                    // with field codes shown: { code } and no result
                    let mut brace = None;
                    match dom.attr(c, "w:fldCharType") {
                        Some("begin") => {
                            if codes && !st.in_result() {
                                brace = Some("{");
                            }
                            st.field_depth.push(true);
                            st.instr.push(String::new());
                        }
                        Some("separate") => {
                            if let Some(l) = st.field_depth.last_mut() {
                                *l = false;
                            }
                            if codes && !st.in_result_outer() {
                                brace = Some("}");
                            }
                        }
                        Some("end") => {
                            let had_code = st.field_depth.last().copied().unwrap_or(false);
                            st.field_depth.pop();
                            st.instr.pop();
                            if codes && had_code && !st.in_result() {
                                brace = Some("}");
                            }
                        }
                        _ => {}
                    }
                    let item = match brace {
                        Some(b) => Item::Atom(b.into(), 0),
                        None => Item::Hidden(String::new()),
                    };
                    out.push(Piece { item, run: Some(r), node: Some(c), rpr: rpr.clone(), change, link,
                                     field: None, note: None, fmt_change });
                }
                "w:drawing" | "w:pict" | "w:object" => {
                    if let Some((w, h, pic)) = self.inline_extent(c) {
                        push(Item::Object(w, h, std::sync::Arc::new(pic)), c, out);
                    } else {
                        // anchored (floating): takes no room in the line
                        let fl = self.float_of(c).map(std::sync::Arc::new);
                        push(Item::Anchor(fl), c, out);
                    }
                }
                "w:footnoteReference" | "w:endnoteReference" => {
                    let endnote = name == "w:endnoteReference";
                    let id = dom.attr(c, "w:id").unwrap_or("").to_string();
                    let note = if endnote { self.notes.endnotes.get(&id) } else { self.notes.footnotes.get(&id) }.copied();
                    let custom = dom.attr(c, "w:customMarkFollows").map(|v| v == "1" || v == "true").unwrap_or(false);
                    let mark = if custom {
                        String::new()
                    } else {
                        self.notes.numbers.get(&c).cloned().unwrap_or(id)
                    };
                    let mut rp = rpr.clone();
                    if rp.vert_align.is_none() && rp.style.is_none() {
                        rp.vert_align = Some("superscript".into());
                    }
                    let item = if hidden_code { Item::Hidden(String::new()) } else { Item::Atom(mark, 1) };
                    out.push(Piece { item, run: Some(r), node: Some(c), rpr: rp, change, link, field: None, note, fmt_change });
                }
                "w:footnoteRef" | "w:endnoteRef" => {
                    // the note's own mark, in the note
                    let mut n = r;
                    let mut mark = String::new();
                    while let Some(par) = dom.parent(n) {
                        if dom.is(par, "w:footnote") || dom.is(par, "w:endnote") {
                            mark = self.notes.marks.get(&par).cloned().unwrap_or_default();
                            break;
                        }
                        n = par;
                    }
                    push(Item::Atom(mark, 1), c, out);
                }
                "w:separator" | "w:continuationSeparator" => push(Item::Atom(String::new(), 1), c, out),
                _ => {}
            }
        }
    }

    /// The floating object in a w:drawing / w:pict.
    fn float_of(&self, n: NodeId) -> Option<crate::pictures::Float> {
        let dom = &self.dom;
        if dom.is(n, "w:drawing") {
            let a = dom.child(n, "wp:anchor")?;
            return crate::pictures::anchor(dom, a, self.images_for(n), &self.styles.theme.colors);
        }
        crate::pictures::vml_float(dom, n, self.images_for(n))
    }

    /// Size of an inline picture/object in points (anchored ones float and
    /// don't take room in the line).
    fn inline_extent(&self, n: NodeId) -> Option<(f64, f64, crate::pictures::Pic)> {
        let dom = &self.dom;
        if dom.is(n, "w:drawing") {
            let inline = dom.child(n, "wp:inline")?;
            let ext = dom.child(inline, "wp:extent")?;
            let cx: f64 = dom.attr(ext, "cx")?.parse().ok()?;
            let cy: f64 = dom.attr(ext, "cy")?.parse().ok()?;
            // effects (shadows, glow) add to the room the picture takes
            let (mut ew, mut eh) = (0.0, 0.0);
            if let Some(e) = dom.child(inline, "wp:effectExtent") {
                let g = |k: &str| dom.attr(e, k).and_then(|v| v.parse::<f64>().ok()).unwrap_or(0.0);
                ew = g("l") + g("r");
                eh = g("t") + g("b");
            }
            let pic = crate::pictures::drawingml(dom, inline, cx / 12700.0, cy / 12700.0, self.images_for(n),
                                                 &self.styles.theme.colors);
            return Some(((cx + ew) / 12700.0, (cy + eh) / 12700.0, pic));
        }
        // VML: style="width:100pt;height:50pt"
        fn find_style(dom: &XmlDoc, n: NodeId) -> Option<String> {
            if let Some(s) = dom.attr(n, "style") {
                if s.contains("width") {
                    return Some(s.to_string());
                }
            }
            for c in dom.elements(n) {
                if let Some(s) = find_style(dom, c) {
                    return Some(s);
                }
            }
            None
        }
        let style = find_style(dom, n)?;
        if style.contains("position:absolute") {
            return None;
        }
        let mut w = None;
        let mut h = None;
        for part in style.split(';') {
            let mut kv = part.splitn(2, ':');
            let k = kv.next()?.trim();
            let v = kv.next().unwrap_or("").trim();
            let num: String = v.chars().take_while(|c| c.is_ascii_digit() || *c == '.').collect();
            let f: f64 = num.parse().unwrap_or(0.0);
            let unit = &v[num.len()..];
            let pt = match unit {
                "in" => f * 72.0,
                "cm" => f * 72.0 / 2.54,
                "mm" => f * 72.0 / 25.4,
                "px" => f * 0.75,
                _ => f,
            };
            match k {
                "width" => w = Some(pt),
                "height" => h = Some(pt),
                _ => {}
            }
        }
        let (w, h) = (w?, h?);
        Some((w, h, crate::pictures::vml(dom, n, w, h, self.images_for(n))))
    }

    /// The plain text of a paragraph (what the layout shows).
    pub fn para_text(&self, p: NodeId) -> String {
        let (_, base) = self.para_props(p);
        let mut s = String::new();
        for pc in self.para_pieces(p, &base) {
            match &pc.item {
                Item::Text(t) => s.push_str(t),
                Item::Tab => s.push('\t'),
                Item::LineBreak => s.push('\n'),
                Item::PageBreak | Item::ColumnBreak => s.push('\u{c}'),
                Item::Object(..) | Item::Anchor(_) | Item::Math(..) => s.push('\u{fffc}'),
                Item::Hidden(_) => {}
                Item::Atom(t, n) => {
                    let cs: Vec<char> = t.chars().collect();
                    for i in 0..*n {
                        s.push(cs.get(i).copied().unwrap_or(' '));
                    }
                }
            }
        }
        s
    }
}

struct Walk {
    /// one entry per open field: true while in its code part
    field_depth: Vec<bool>,
    /// each open field's instruction
    instr: Vec<String>,
}

impl Walk {
    fn in_code(&self) -> bool {
        self.field_depth.iter().any(|&c| c)
    }

    /// Inside some field's result.
    fn in_result(&self) -> bool {
        self.field_depth.iter().any(|&c| !c)
    }

    /// Inside the result of a field other than the innermost.
    fn in_result_outer(&self) -> bool {
        let n = self.field_depth.len();
        n > 0 && self.field_depth[..n - 1].iter().any(|&c| !c)
    }

    /// In the result of a field the layout computes: which.
    fn result_kind(&self) -> Option<&'static str> {
        if self.in_code() {
            return None;
        }
        let i = self.instr.last()?;
        field_kind(i)
    }
}

/// The fields whose result depends on the page.
pub fn field_kind(instr: &str) -> Option<&'static str> {
    match instr.split_whitespace().next()?.to_ascii_uppercase().as_str() {
        "PAGE" => Some("PAGE"),
        "NUMPAGES" => Some("NUMPAGES"),
        "SECTIONPAGES" => Some("SECTIONPAGES"),
        "SECTION" => Some("SECTION"),
        _ => None,
    }
}

fn other_text(i: &Item) -> String {
    match i {
        Item::Tab => "\t".into(),
        Item::LineBreak => "\n".into(),
        _ => String::new(),
    }
}

/// The order of settings.xml's children (as far as they matter here).
const SETTINGS_ORDER: &[&str] = &["w:writeProtection", "w:view", "w:zoom", "w:removePersonalInformation",
    "w:removeDateAndTime", "w:doNotDisplayPageBoundaries", "w:displayBackgroundShape",
    "w:printPostScriptOverText", "w:printFractionalCharacterWidth", "w:printFormsData",
    "w:embedTrueTypeFonts", "w:embedSystemFonts", "w:saveSubsetFonts", "w:saveFormsData",
    "w:mirrorMargins", "w:alignBordersAndEdges", "w:bordersDoNotSurroundHeader",
    "w:bordersDoNotSurroundFooter", "w:gutterAtTop", "w:hideSpellingErrors",
    "w:hideGrammaticalErrors", "w:activeWritingStyle", "w:proofState", "w:formsDesign",
    "w:attachedTemplate", "w:linkStyles", "w:stylePaneFormatFilter", "w:stylePaneSortMethod",
    "w:documentType", "w:mailMerge", "w:revisionView", "w:trackRevisions", "w:doNotTrackMoves",
    "w:doNotTrackFormatting", "w:documentProtection", "w:autoFormatOverride", "w:styleLockTheme",
    "w:styleLockQFSet", "w:defaultTabStop", "w:autoHyphenation", "w:consecutiveHyphenLimit",
    "w:hyphenationZone", "w:doNotHyphenateCaps", "w:showEnvelope", "w:summaryLength",
    "w:clickAndTypeStyle", "w:defaultTableStyle", "w:evenAndOddHeaders", "w:bookFoldRevPrinting",
    "w:bookFoldPrinting", "w:bookFoldPrintingSheets", "w:drawingGridHorizontalSpacing", "w:drawingGridVerticalSpacing",
    "w:displayHorizontalDrawingGridEvery", "w:displayVerticalDrawingGridEvery", "w:doNotUseMarginsForDrawingGridOrigin",
    "w:drawingGridHorizontalOrigin", "w:drawingGridVerticalOrigin", "w:doNotShadeFormData", "w:noPunctuationKerning",
    "w:characterSpacingControl", "w:printTwoOnOne", "w:strictFirstAndLastChars", "w:noLineBreaksAfter",
    "w:noLineBreaksBefore", "w:savePreviewPicture", "w:doNotValidateAgainstSchema", "w:saveInvalidXml",
    "w:ignoreMixedContent", "w:alwaysShowPlaceholderText", "w:doNotDemarcateInvalidXml", "w:saveXmlDataOnly",
    "w:useXSLTWhenSaving", "w:saveThroughXslt", "w:showXMLTags", "w:alwaysMergeEmptyNamespace", "w:updateFields",
    "w:hdrShapeDefaults", "w:footnotePr", "w:endnotePr", "w:compat", "w:docVars", "w:rsids", "m:mathPr",
    "w:attachedSchema", "w:themeFontLang", "w:clrSchemeMapping"];

/// Turn an on/off setting on (present) or off (absent).
fn set_settings_val(x: &mut XmlDoc, name: &str, v: Option<i32>) {
    set_settings_flag(x, name, v.is_some());
    if let (Some(v), Some(t)) = (v, x.child(x.root, name)) {
        x.set_attr(t, "w:val", &v.to_string());
    }
}

/// Where a settings element goes (schema order).
pub fn settings_index(x: &XmlDoc, name: &str) -> usize {
    let root = x.root;
    let me = SETTINGS_ORDER.iter().position(|n| *n == name).unwrap_or(SETTINGS_ORDER.len());
    let mut idx = 0;
    for (i, &k) in x.children(root).iter().enumerate() {
        if SETTINGS_ORDER.iter().position(|n| *n == x.name(k)).map_or(false, |r| r < me) {
            idx = i + 1;
        }
    }
    idx
}

fn set_settings_flag(x: &mut XmlDoc, name: &str, on: bool) {
    let root = x.root;
    let off = |v: Option<&str>| matches!(v, Some("0") | Some("false") | Some("off"));
    match (x.child(root, name), on) {
        (Some(t), false) => {
            // as it was written when it already says off
            if !off(x.attr(t, "w:val")) {
                x.detach(t);
            }
        }
        (Some(t), true) => {
            if off(x.attr(t, "w:val")) {
                x.remove_attr(t, "w:val");
            }
        }
        (None, true) => {
            let me = SETTINGS_ORDER.iter().position(|n| *n == name).unwrap_or(0);
            let mut idx = 0;
            for (i, &k) in x.children(root).iter().enumerate() {
                if SETTINGS_ORDER.iter().position(|n| *n == x.name(k)).map_or(false, |r| r < me) {
                    idx = i + 1;
                }
            }
            let t = x.new_element(name, &[]);
            x.insert(root, idx, t);
        }
        (None, false) => {}
    }
}
