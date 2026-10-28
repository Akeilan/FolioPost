//! Headers, footers and fields: creating a section's header or footer,
//! page numbers, and inserting fields at the caret.

use super::{Editor, Pos, Story};
use crate::document::{SubPart, W_NS};
use crate::xml::{NodeId, XmlDoc};

const NS_R: &str = "http://schemas.openxmlformats.org/officeDocument/2006/relationships";
const REL_HEADER: &str = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/header";
const REL_FOOTER: &str = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer";

fn style_xml(id: &str) -> String {
    format!(
        "<w:style w:type=\"paragraph\" w:styleId=\"{id}\"><w:name w:val=\"{name}\"/><w:basedOn w:val=\"Normal\"/>\
         <w:uiPriority w:val=\"99\"/><w:unhideWhenUsed/><w:pPr><w:tabs><w:tab w:val=\"center\" w:pos=\"4680\"/>\
         <w:tab w:val=\"right\" w:pos=\"9360\"/></w:tabs><w:spacing w:after=\"0\" w:line=\"240\" w:lineRule=\"auto\"/>\
         </w:pPr></w:style>",
        id = id,
        name = id.to_lowercase()
    )
}

impl Editor {
    /// The section the caret (or the header being edited) is in.
    pub fn current_section(&self) -> usize {
        if let Story::HeaderFooter(pg) | Story::Notes(pg) = self.story {
            return self.layout.pages.get(pg).map(|p| p.section).unwrap_or(0);
        }
        self.doc.blocks.iter().find(|b| b.node == self.caret.para).map(|b| b.section)
            .or_else(|| {
                // in a table: the block holding it
                let dom = &self.doc.dom;
                let mut n = self.caret.para;
                while let Some(p) = dom.parent(n) {
                    if let Some(b) = self.doc.blocks.iter().find(|b| b.node == p) {
                        return Some(b.section);
                    }
                    n = p;
                }
                None
            })
            .unwrap_or(0)
    }

    /// The page the caret is on.
    pub fn caret_page(&self) -> usize {
        self.caret_rect(self.caret).map(|r| r.0).unwrap_or(0)
    }

    /// The header (or footer) section `sec` shows by default, made if it
    /// has none. Returns its part.
    pub fn ensure_header_footer(&mut self, sec: usize, footer: bool) -> Option<usize> {
        self.ensure_header_footer_kind(sec, footer, 0)
    }

    /// The page's kind of header: 0 default, 1 first page, 2 even pages.
    pub fn page_hf_kind(&self, pg: usize) -> usize {
        let Some(page) = self.layout.pages.get(pg) else { return 0 };
        let Some(s) = self.doc.sections.get(page.section) else { return 0 };
        if page.first_of_section && s.title_pg {
            1
        } else if page.number % 2 == 0 && self.doc.settings.even_odd_headers {
            2
        } else {
            0
        }
    }

    /// A section's header or footer of a kind (0 default, 1 first page,
    /// 2 even pages), made if it has none of its own.
    pub fn ensure_header_footer_kind(&mut self, sec: usize, footer: bool, which: usize) -> Option<usize> {
        let which = which.min(2);
        let s = self.doc.sections.get(sec)?;
        let own = s.hf_rids.iter().any(|(hdr, k, _)| *hdr != footer && *k == which);
        let have = if footer { s.footers[which] } else { s.headers[which] };
        let have = if own || which == 0 { have } else { None };
        if let Some(p) = have {
            return Some(p);
        }
        let sid = if footer { "Footer" } else { "Header" };
        let has_style = self.doc.styles.styles.contains_key(sid);
        self.begin_group(if footer { "Footer" } else { "Header" });
        if !has_style {
            self.add_style_xml(&style_xml(sid));
        }
        // the part
        let kind = if footer { "footer" } else { "header" };
        let mut n = 1;
        while self.doc.pkg.has(&format!("word/{kind}{n}.xml")) || self.doc.parts.iter().any(|p| p.name == format!("word/{kind}{n}.xml")) {
            n += 1;
        }
        let name = format!("word/{kind}{n}.xml");
        let tag = if footer { "w:ftr" } else { "w:hdr" };
        let xml = format!("<{tag} xmlns:w=\"{W_NS}\" xmlns:r=\"{NS_R}\"><w:p><w:pPr><w:pStyle w:val=\"{sid}\"/></w:pPr></w:p></{tag}>");
        let Ok(tmp) = XmlDoc::parse(xml.as_bytes()) else {
            self.end_group();
            return None;
        };
        let root = self.doc.dom.import_node(&tmp, tmp.root);
        let main = self.doc.main.clone();
        let rid = self.doc.pkg.add_rel(&main, if footer { REL_FOOTER } else { REL_HEADER }, &format!("{kind}{n}.xml"));
        self.doc.pkg.set_content_type(&name,
            &format!("application/vnd.openxmlformats-officedocument.wordprocessingml.{kind}+xml"));
        self.doc.parts.push(SubPart { name, kind: if footer { "footer" } else { "header" }, root,
                                      prolog: tmp.prolog.clone(), images: Default::default() });
        let part = self.doc.parts.len() - 1;
        self.doc.hf_by_rid.insert(rid.clone(), part);
        // the reference in the section's properties
        self.begin();
        let sect = match self.doc.sections[sec].node {
            Some(n) => n,
            None => {
                let dom = &mut self.doc.dom;
                let sp = dom.new_element("w:sectPr", &[]);
                let body = self.doc.body;
                dom.append(body, sp);
                sp
            }
        };
        let dom = &mut self.doc.dom;
        let r = dom.new_element(if footer { "w:footerReference" } else { "w:headerReference" },
                                &[("w:type", ["default", "first", "even"][which]), ("r:id", &rid)]);
        // references come first, headers before footers
        let kids: Vec<NodeId> = dom.elements(sect).collect();
        let mut idx = 0;
        for k in kids {
            let nm = dom.name(k);
            if nm == "w:headerReference" || (footer && nm == "w:footerReference") {
                idx = dom.index_in_parent(k).unwrap_or(0) + 1;
            }
        }
        dom.insert(sect, idx, r);
        self.commit(if footer { "Footer" } else { "Header" }, false);
        self.end_group();
        Some(part)
    }

    /// Put a page number in a section's header or footer: aligned left,
    /// center or right; "Page X of Y" or just the number; bold or not.
    pub fn page_number_in(&mut self, sec: usize, footer: bool, align: &str, x_of_y: bool, bold: bool) -> bool {
        let Some(part) = self.ensure_header_footer(sec, footer) else { return false };
        let root = self.doc.parts[part].root;
        let sid = if footer { "Footer" } else { "Header" };
        let jc = match align {
            "center" => "center",
            "right" => "right",
            _ => "left",
        };
        let b = if bold { "<w:rPr><w:b/><w:bCs/></w:rPr>" } else { "" };
        let field = |instr: &str, val: &str| {
            format!("<w:r>{b}<w:fldChar w:fldCharType=\"begin\"/></w:r><w:r>{b}<w:instrText xml:space=\"preserve\"> {instr} </w:instrText></w:r>\
                     <w:r>{b}<w:fldChar w:fldCharType=\"separate\"/></w:r><w:r>{b}<w:t>{val}</w:t></w:r><w:r>{b}<w:fldChar w:fldCharType=\"end\"/></w:r>")
        };
        let runs = if x_of_y {
            format!("<w:r>{b}<w:t xml:space=\"preserve\">Page </w:t></w:r>{}<w:r>{b}<w:t xml:space=\"preserve\"> of </w:t></w:r>{}",
                    field("PAGE", "1"), field("NUMPAGES", "1"))
        } else {
            field("PAGE", "1")
        };
        let xml = format!("<w:p xmlns:w=\"{W_NS}\"><w:pPr><w:pStyle w:val=\"{sid}\"/><w:jc w:val=\"{jc}\"/></w:pPr>{runs}</w:p>");
        let Ok(tmp) = XmlDoc::parse(xml.as_bytes()) else { return false };
        self.begin();
        let dom = &mut self.doc.dom;
        // the number replaces what the header or footer had
        for c in dom.elements(root).collect::<Vec<_>>() {
            if dom.is(c, "w:p") || dom.is(c, "w:tbl") || dom.is(c, "w:sdt") {
                dom.detach(c);
            }
        }
        let p = dom.import_node(&tmp, tmp.root);
        dom.remove_attr(p, "xmlns:w");
        dom.append(root, p);
        self.commit("Page Number", false);
        true
    }

    /// Insert a field at the caret: its instruction and a result to show
    /// until it is updated.
    pub fn insert_field(&mut self, instr: &str, result: &str) {
        self.begin();
        self.delete_selection();
        let p = self.caret.para;
        let off = self.caret.off;
        let (parent, mut idx, like) = self.split_runs_at(p, off);
        let mk = |ed: &mut Editor, kind: &str, text: Option<&str>| -> NodeId {
            let r = ed.new_run(p, like, &[]);
            let dom = &mut ed.doc.dom;
            let c = match kind {
                "instr" => {
                    let e = dom.new_element("w:instrText", &[("xml:space", "preserve")]);
                    let t = dom.new_text(&format!(" {} ", instr.trim()));
                    dom.append(e, t);
                    e
                }
                "t" => {
                    let e = dom.new_element("w:t", &[("xml:space", "preserve")]);
                    let t = dom.new_text(text.unwrap_or(""));
                    dom.append(e, t);
                    e
                }
                k => dom.new_element("w:fldChar", &[("w:fldCharType", k)]),
            };
            dom.append(r, c);
            r
        };
        for (kind, text) in [("begin", None), ("instr", None), ("separate", None), ("t", Some(result)), ("end", None)] {
            if kind == "t" && result.is_empty() {
                continue;
            }
            let r = mk(self, kind, text);
            self.doc.dom.insert(parent, idx, r);
            idx += 1;
        }
        let n = result.chars().count();
        self.caret = Pos { para: p, off: off + n };
        self.anchor = self.caret;
        self.commit("Insert Field", false);
    }
}

const SECT_ORDER: &[&str] = &["w:headerReference", "w:footerReference", "w:footnotePr", "w:endnotePr", "w:type",
    "w:pgSz", "w:pgMar", "w:paperSrc", "w:pgBorders", "w:lnNumType", "w:pgNumType", "w:cols", "w:formProt",
    "w:vAlign", "w:noEndnote", "w:titlePg", "w:textDirection", "w:bidi", "w:rtlGutter", "w:docGrid",
    "w:printerSettings", "w:sectPrChange"];

impl Editor {
    fn sect_node(&mut self, sec: usize) -> Option<NodeId> {
        let s = self.doc.sections.get(sec)?;
        Some(match s.node {
            Some(n) => n,
            None => {
                let dom = &mut self.doc.dom;
                let sp = dom.new_element("w:sectPr", &[]);
                let body = self.doc.body;
                dom.append(body, sp);
                sp
            }
        })
    }

    /// Set (or with None remove) one attribute of a section property
    /// element, e.g. ("w:pgMar", "w:header").
    pub fn section_attr(&mut self, sec: usize, el: &str, attr: &str, value: Option<&str>, label: &str) -> bool {
        self.begin();
        let Some(sp) = self.sect_node(sec) else {
            self.commit(label, false);
            return false;
        };
        let dom = &mut self.doc.dom;
        let n = match dom.child(sp, el) {
            Some(n) => n,
            None => {
                super::set_prop_child(dom, sp, &super::PropEdit::set(el, &[]), SECT_ORDER);
                dom.child(sp, el).unwrap()
            }
        };
        match value {
            Some(v) => dom.set_attr(n, attr, v),
            None => {
                dom.remove_attr(n, attr);
            }
        }
        self.commit(label, false);
        true
    }

    /// Layout > Line Numbers for a section (None: every section): restart
    /// "continuous", "newPage", "newSection", or None to turn them off;
    /// count by, first number and distance (twips, 0 auto).
    pub fn set_line_numbers(&mut self, sec: Option<usize>, restart: Option<&str>, by: i32, start: i32, dist: i32) -> bool {
        let secs: Vec<usize> = match sec {
            Some(s) => vec![s],
            None => (0..self.doc.sections.len()).collect(),
        };
        self.begin();
        for s in secs {
            let Some(sp) = self.sect_node(s) else { continue };
            let dom = &mut self.doc.dom;
            match restart {
                None => super::set_prop_child(dom, sp, &super::PropEdit::remove("w:lnNumType"), SECT_ORDER),
                Some(r) => {
                    let mut attrs: Vec<(String, String)> = vec![("w:countBy".into(), by.max(1).to_string())];
                    if start > 0 {
                        attrs.push(("w:start".into(), start.to_string()));
                    }
                    if dist > 0 {
                        attrs.push(("w:distance".into(), dist.to_string()));
                    }
                    if r != "newPage" {
                        attrs.push(("w:restart".into(), r.to_string()));
                    }
                    super::set_prop_child(dom, sp, &super::PropEdit { name: "w:lnNumType".into(), attrs: Some(attrs) }, SECT_ORDER);
                }
            }
        }
        self.commit("Line Numbers", false);
        true
    }

    /// The current section's line numbering: (restart, count by, start, distance).
    pub fn line_numbers(&self, sec: usize) -> Option<(String, i32, i32, i32)> {
        self.doc.sections.get(sec)?.ln_num.clone().map(|(by, st, d, r)| (r, by, st, d))
    }

    /// Set (xml: a w:pgBorders element) or remove the page borders of a
    /// section, or of every section (None).
    pub fn set_page_borders(&mut self, sec: Option<usize>, xml: Option<&str>) -> bool {
        let secs: Vec<usize> = match sec {
            Some(s) => vec![s],
            None => (0..self.doc.sections.len()).collect(),
        };
        let parsed = match xml {
            Some(x) => {
                let w = format!("<r xmlns:w=\"{}\">{x}</r>", crate::document::W_NS);
                match XmlDoc::parse(w.as_bytes()) {
                    Ok(t) => Some(t),
                    Err(_) => return false,
                }
            }
            None => None,
        };
        self.begin_group("Page Borders");
        self.begin();
        for s in secs {
            let Some(sp) = self.sect_node(s) else { continue };
            let dom = &mut self.doc.dom;
            if let Some(old) = dom.child(sp, "w:pgBorders") {
                dom.detach(old);
            }
            if let Some(t) = &parsed {
                if let Some(first) = t.elements(t.root).next() {
                    let n = self.doc.dom.import_node(t, first);
                    let dom = &mut self.doc.dom;
                    let rank = |nm: &str| SECT_ORDER.iter().position(|x| *x == nm).unwrap_or(SECT_ORDER.len());
                    let me = rank("w:pgBorders");
                    let mut idx = dom.children(sp).len();
                    for k in dom.elements(sp).collect::<Vec<_>>() {
                        if rank(dom.name(k)) > me {
                            idx = dom.index_in_parent(k).unwrap();
                            break;
                        }
                    }
                    dom.insert(sp, idx, n);
                }
            }
        }
        self.commit("Page Borders", false);
        self.end_group();
        true
    }

    /// A document-wide on/off setting: "mirrorMargins", "evenAndOddHeaders".
    pub fn set_setting(&mut self, name: &str, on: bool) -> bool {
        let s = &mut self.doc.settings;
        let cur = match name {
            "mirrorMargins" => &mut s.mirror_margins,
            "evenAndOddHeaders" => &mut s.even_odd_headers,
            "autoHyphenation" => &mut s.auto_hyphenation,
            "doNotHyphenateCaps" => &mut s.no_hyphenate_caps,
            _ => return false,
        };
        if *cur != on {
            *cur = on;
            self.modified = true;
            self.cache.retain(|_, _| false);
            self.relayout();
        }
        true
    }

    pub fn setting(&self, name: &str) -> bool {
        match name {
            "mirrorMargins" => self.doc.settings.mirror_margins,
            "evenAndOddHeaders" => self.doc.settings.even_odd_headers,
            "autoHyphenation" => self.doc.settings.auto_hyphenation,
            "doNotHyphenateCaps" => self.doc.settings.no_hyphenate_caps,
            _ => false,
        }
    }

    /// Hyphenation Options: the zone (twips) and the most consecutive
    /// hyphenated lines (0: no limit).
    pub fn set_hyphenation_options(&mut self, zone: i32, limit: i32) {
        let s = &mut self.doc.settings;
        s.hyphenation_zone = zone.max(0);
        s.hyphen_limit = limit.max(0);
        self.modified = true;
        self.cache.retain(|_, _| false);
        self.relayout();
    }

    pub fn hyphenation_options(&self) -> (i32, i32) {
        (self.doc.settings.hyphenation_zone, self.doc.settings.hyphen_limit)
    }

    /// Turn a section's on/off property (w:titlePg...) on or off.
    pub fn section_flag(&mut self, sec: usize, el: &str, on: bool, label: &str) -> bool {
        self.begin();
        let Some(sp) = self.sect_node(sec) else {
            self.commit(label, false);
            return false;
        };
        let e = if on { super::PropEdit::set(el, &[]) } else { super::PropEdit::remove(el) };
        super::set_prop_child(&mut self.doc.dom, sp, &e, SECT_ORDER);
        self.commit(label, false);
        true
    }
}

const REL_FOOTNOTES: &str = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes";
const REL_ENDNOTES: &str = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/endnotes";

fn note_styles(endnote: bool) -> [(&'static str, String); 2] {
    let (text, refs, name) = if endnote {
        ("EndnoteText", "EndnoteReference", "endnote")
    } else {
        ("FootnoteText", "FootnoteReference", "footnote")
    };
    [
        (text, format!("<w:style w:type=\"paragraph\" w:styleId=\"{text}\"><w:name w:val=\"{name} text\"/>\
            <w:basedOn w:val=\"Normal\"/><w:uiPriority w:val=\"99\"/><w:semiHidden/><w:unhideWhenUsed/>\
            <w:pPr><w:spacing w:after=\"0\" w:line=\"240\" w:lineRule=\"auto\"/></w:pPr>\
            <w:rPr><w:sz w:val=\"20\"/><w:szCs w:val=\"20\"/></w:rPr></w:style>")),
        (refs, format!("<w:style w:type=\"character\" w:styleId=\"{refs}\"><w:name w:val=\"{name} reference\"/>\
            <w:basedOn w:val=\"DefaultParagraphFont\"/><w:uiPriority w:val=\"99\"/><w:semiHidden/><w:unhideWhenUsed/>\
            <w:rPr><w:vertAlign w:val=\"superscript\"/></w:rPr></w:style>")),
    ]
}

impl Editor {
    /// Edit the notes shown on page `pg` (None: back to the body).
    pub fn edit_notes(&mut self, pg: Option<usize>) {
        self.sel_obj = None;
        match pg {
            None => self.edit_header_footer(None, false),
            Some(pg) => {
                self.leave_body();
                self.story = Story::Notes(pg);
                self.relayout();
                self.goal_x = None;
            }
        }
    }

    /// The footnotes (or endnotes) part, made if the document has none.
    pub(super) fn notes_root(&mut self, endnote: bool) -> NodeId {
        let kind = if endnote { "endnotes" } else { "footnotes" };
        if let Some(p) = self.doc.parts.iter().find(|p| p.kind == kind) {
            return p.root;
        }
        let tag = if endnote { "w:endnote" } else { "w:footnote" };
        let root_tag = if endnote { "w:endnotes" } else { "w:footnotes" };
        let xml = format!("<{root_tag} xmlns:w=\"{W_NS}\" xmlns:r=\"{NS_R}\">\
            <{tag} w:type=\"separator\" w:id=\"-1\"><w:p><w:pPr><w:spacing w:after=\"0\" w:line=\"240\" w:lineRule=\"auto\"/></w:pPr><w:r><w:separator/></w:r></w:p></{tag}>\
            <{tag} w:type=\"continuationSeparator\" w:id=\"0\"><w:p><w:pPr><w:spacing w:after=\"0\" w:line=\"240\" w:lineRule=\"auto\"/></w:pPr><w:r><w:continuationSeparator/></w:r></w:p></{tag}>\
            </{root_tag}>");
        let tmp = XmlDoc::parse(xml.as_bytes()).unwrap();
        let root = self.doc.dom.import_node(&tmp, tmp.root);
        let name = format!("word/{kind}.xml");
        let main = self.doc.main.clone();
        self.doc.pkg.add_rel(&main, if endnote { REL_ENDNOTES } else { REL_FOOTNOTES }, &format!("{kind}.xml"));
        self.doc.pkg.set_content_type(&name,
            &format!("application/vnd.openxmlformats-officedocument.wordprocessingml.{kind}+xml"));
        self.doc.parts.push(SubPart { name, kind: if endnote { "endnotes" } else { "footnotes" }, root,
                                      prolog: tmp.prolog.clone(), images: Default::default() });
        let sep = self.doc.dom.elements(root).next();
        if endnote {
            self.doc.notes.en_sep = sep;
        } else {
            self.doc.notes.fn_sep = sep;
        }
        root
    }

    /// Insert a footnote (or endnote) at the caret; the caret goes into
    /// its text.
    pub fn insert_note(&mut self, endnote: bool) -> bool {
        if self.story != Story::Body {
            return false;
        }
        self.begin_group(if endnote { "Insert Endnote" } else { "Insert Footnote" });
        for (id, xml) in note_styles(endnote) {
            if !self.doc.styles.styles.contains_key(id) {
                self.add_style_xml(&xml);
            }
        }
        let root = self.notes_root(endnote);
        let (tag, rtag, refs, text, ref_el) = if endnote {
            ("w:endnote", "w:endnoteRef", "EndnoteReference", "EndnoteText", "w:endnoteReference")
        } else {
            ("w:footnote", "w:footnoteRef", "FootnoteReference", "FootnoteText", "w:footnoteReference")
        };
        let id = self.doc.dom.elements(root)
            .filter_map(|n| self.doc.dom.attr(n, "w:id").and_then(|v| v.parse::<i64>().ok()))
            .max().unwrap_or(0).max(0) + 1;
        let ids = id.to_string();
        self.begin();
        self.delete_selection();
        let p = self.caret.para;
        let off = self.caret.off;
        let dom = &mut self.doc.dom;
        // the note
        let note = dom.new_element(tag, &[("w:id", &ids)]);
        let np = dom.new_element("w:p", &[]);
        let ppr = dom.new_element("w:pPr", &[]);
        let ps = dom.new_element("w:pStyle", &[("w:val", text)]);
        dom.append(ppr, ps);
        dom.append(np, ppr);
        let r1 = dom.new_element("w:r", &[]);
        let rpr = dom.new_element("w:rPr", &[]);
        let rs = dom.new_element("w:rStyle", &[("w:val", refs)]);
        dom.append(rpr, rs);
        dom.append(r1, rpr);
        let mark = dom.new_element(rtag, &[]);
        dom.append(r1, mark);
        dom.append(np, r1);
        let r2 = dom.new_element("w:r", &[]);
        let t = dom.new_element("w:t", &[("xml:space", "preserve")]);
        let tx = dom.new_text(" ");
        dom.append(t, tx);
        dom.append(r2, t);
        dom.append(np, r2);
        dom.append(note, np);
        dom.append(root, note);
        if endnote {
            self.doc.notes.endnotes.insert(ids.clone(), note);
        } else {
            self.doc.notes.footnotes.insert(ids.clone(), note);
        }
        // the reference in the text
        let (parent, idx, like) = self.split_runs_at(p, off);
        let run = self.new_run(p, like, &[]);
        let dom = &mut self.doc.dom;
        let rpr = match dom.child(run, "w:rPr") {
            Some(r) => r,
            None => {
                let r = dom.new_element("w:rPr", &[]);
                dom.insert(run, 0, r);
                r
            }
        };
        for k in dom.children(rpr).to_vec() {
            if dom.is(k, "w:rStyle") || dom.is(k, "w:vertAlign") {
                dom.detach(k);
            }
        }
        let rs = dom.new_element("w:rStyle", &[("w:val", refs)]);
        dom.insert(rpr, 0, rs);
        let rf = dom.new_element(ref_el, &[("w:id", &ids)]);
        dom.append(run, rf);
        dom.insert(parent, idx, run);
        self.caret = Pos { para: p, off: off + 1 };
        self.anchor = self.caret;
        self.commit(if endnote { "Insert Endnote" } else { "Insert Footnote" }, false);
        self.end_group();
        // into the note
        let pg = self.caret_page();
        let pg = if endnote {
            self.layout.pages.iter().position(|pp| pp.note_lines.iter().any(|l| self.layout.paras[l.para].node == np)).unwrap_or(pg)
        } else {
            pg
        };
        self.leave_body();
        self.story = Story::Notes(pg);
        self.relayout();
        if self.pidx(&np).is_some() {
            let len = self.para_layout(np).map(|l| l.text_len).unwrap_or(1);
            self.caret = Pos { para: np, off: len };
            self.anchor = self.caret;
        } else {
            self.story = Story::Body;
            self.relayout();
        }
        true
    }
}
