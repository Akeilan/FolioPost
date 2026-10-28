//! Charts in the document: inserting one (its chart part, the workbook
//! holding its data, an inline drawing), finding the selected one's part,
//! and changing a chart part (undoably).

use super::{Editor, Pos};
use crate::xml::{NodeId, XmlDoc};

const NS_WP: &str = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing";
const NS_A: &str = "http://schemas.openxmlformats.org/drawingml/2006/main";
const NS_C: &str = "http://schemas.openxmlformats.org/drawingml/2006/chart";
const NS_R: &str = "http://schemas.openxmlformats.org/officeDocument/2006/relationships";
const REL_CHART: &str = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart";
const REL_PACKAGE: &str = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/package";
const CT_CHART: &str = "application/vnd.openxmlformats-officedocument.drawingml.chart+xml";
const CT_CHARTEX: &str = "application/vnd.ms-office.chartex+xml";
const REL_CHARTEX: &str = "http://schemas.microsoft.com/office/2014/relationships/chartEx";
const NS_CX: &str = "http://schemas.microsoft.com/office/drawing/2014/chartex";
const CT_XLSX: &str = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

impl Editor {
    /// Insert a chart in line at the caret: `xml` is its c:chartSpace (its
    /// c:externalData points at rId1, the workbook `xlsx`). Returns the part.
    pub fn insert_chart(&mut self, xml: &str, xlsx: &[u8], w: f64, h: f64, ex: bool) -> Option<String> {
        let main = self.doc.main.clone();
        let stem = if ex { "chartEx" } else { "chart" };
        let mut n = 1;
        while self.doc.pkg.has(&format!("word/charts/{stem}{n}.xml")) {
            n += 1;
        }
        let part = format!("word/charts/{stem}{n}.xml");
        let mut k = 1;
        while self.doc.pkg.has(&format!("word/embeddings/Microsoft_Excel_Worksheet{k}.xlsx")) {
            k += 1;
        }
        let book = format!("word/embeddings/Microsoft_Excel_Worksheet{k}.xlsx");
        // the chart's own relationships: rId1 is its workbook
        self.doc.pkg.put_raw(&book, xlsx.to_vec());
        self.doc.pkg.ensure_default("xlsx", CT_XLSX);
        let bt = crate::package::Package::relative_target(&part, &book);
        let brid = self.doc.pkg.add_rel(&part, REL_PACKAGE, &bt);
        let xml = xml.replace("r:id=\"rId1\"", &format!("r:id=\"{brid}\""));
        self.doc.pkg.put_raw(&part, xml.clone().into_bytes());
        self.doc.pkg.set_content_type(&part, if ex { CT_CHARTEX } else { CT_CHART });
        let target = crate::package::Package::relative_target(&main, &part);
        let rid = self.doc.pkg.add_rel(&main, if ex { REL_CHARTEX } else { REL_CHART }, &target);
        self.doc.images.insert(rid.clone(), crate::pictures::ImageData { part: part.clone(), bytes: std::sync::Arc::new(xml.into_bytes()) });
        let id = self.next_docpr_id();
        let emu = |pt: f64| ((pt * 12700.0).round() as i64).to_string();
        let emu = &emu;
        let inline = |uri: &str, inner: &str| format!(
            "<w:drawing><wp:inline xmlns:wp=\"{wp}\" distT=\"0\" distB=\"0\" distL=\"0\" distR=\"0\">\
             <wp:extent cx=\"{cx}\" cy=\"{cy}\"/><wp:effectExtent l=\"0\" t=\"0\" r=\"0\" b=\"0\"/>\
             <wp:docPr id=\"{id}\" name=\"Chart {id}\"/><wp:cNvGraphicFramePr/>\
             <a:graphic xmlns:a=\"{a}\"><a:graphicData uri=\"{uri}\">{inner}</a:graphicData></a:graphic></wp:inline></w:drawing>",
            wp = NS_WP, a = NS_A, cx = emu(w), cy = emu(h), id = id, uri = uri, inner = inner);
        let _ = &inline;
        let dx = if ex {
            format!("<mc:AlternateContent xmlns:mc=\"http://schemas.openxmlformats.org/markup-compatibility/2006\" xmlns:w=\"{w}\">\
                     <mc:Choice xmlns:cx=\"{cxns}\" Requires=\"cx\">{d}</mc:Choice><mc:Fallback><w:t xml:space=\"preserve\"> </w:t></mc:Fallback></mc:AlternateContent>",
                    w = crate::document::W_NS, cxns = NS_CX,
                    d = inline(NS_CX, &format!("<cx:chart xmlns:cx=\"{NS_CX}\" xmlns:r=\"{NS_R}\" r:id=\"{rid}\"/>")))
        } else {
            String::new()
        };
        let dx = if ex { dx } else { format!(
            "<w:drawing xmlns:w=\"{w}\"><wp:inline xmlns:wp=\"{wp}\" distT=\"0\" distB=\"0\" distL=\"0\" distR=\"0\">\
             <wp:extent cx=\"{cx}\" cy=\"{cy}\"/><wp:effectExtent l=\"0\" t=\"0\" r=\"0\" b=\"0\"/>\
             <wp:docPr id=\"{id}\" name=\"Chart {id}\"/><wp:cNvGraphicFramePr/>\
             <a:graphic xmlns:a=\"{a}\"><a:graphicData uri=\"{c}\"><c:chart xmlns:c=\"{c}\" xmlns:r=\"{r}\" r:id=\"{rid}\"/>\
             </a:graphicData></a:graphic></wp:inline></w:drawing>",
            w = crate::document::W_NS, wp = NS_WP, a = NS_A, c = NS_C, r = NS_R,
            cx = emu(w), cy = emu(h), id = id, rid = rid) };
        let tmp = XmlDoc::parse(dx.as_bytes()).ok()?;
        let src = tmp.root;
        self.begin();
        self.delete_selection();
        let p = self.caret.para;
        let off = self.caret.off;
        let (parent, idx, like) = self.split_runs_at(p, off);
        let run = self.new_run(p, like, &[]);
        let d = self.doc.dom.import_node(&tmp, src);
        self.doc.dom.remove_attr(d, "xmlns:w");
        self.doc.dom.append(run, d);
        self.doc.dom.insert(parent, idx, run);
        self.caret = Pos { para: p, off: off + 1 };
        self.anchor = self.caret;
        self.commit("Insert Chart", false);
        let drawing = if self.doc.dom.is(d, "w:drawing") { Some(d) } else {
            fn find_drawing(dom: &XmlDoc, n: NodeId) -> Option<NodeId> {
                for c in dom.elements(n) {
                    if dom.is(c, "w:drawing") {
                        return Some(c);
                    }
                    if let Some(x) = find_drawing(dom, c) {
                        return Some(x);
                    }
                }
                None
            }
            find_drawing(&self.doc.dom, d)
        };
        self.sel_obj = drawing;
        Some(part)
    }

    fn chart_rid(&self, n: NodeId) -> Option<String> {
        let dom = &self.doc.dom;
        let gd = crate::pictures::find(dom, n, "a:graphicData")?;
        let uri = dom.attr(gd, "uri").unwrap_or("");
        if !(uri.ends_with("/chart") || uri.ends_with("/chartex")) {
            return None;
        }
        let c = dom.elements(gd).next()?;
        dom.attr(c, "r:id").map(|s| s.to_string())
    }

    /// The chart part of the selected object (None: it isn't a chart).
    pub fn selected_chart(&mut self) -> Option<String> {
        let n = self.sel_obj?;
        let rid = self.chart_rid(n)?;
        self.doc.images.get(&rid).map(|i| i.part.clone())
    }

    /// Every chart part the body shows.
    pub fn chart_parts(&self) -> Vec<String> {
        let mut out: Vec<String> = self.doc.images.values()
            .filter(|i| i.part.starts_with("word/charts/") || i.part.contains("/charts/"))
            .map(|i| i.part.clone()).collect();
        out.sort();
        out.dedup();
        out
    }

    /// Replace a chart part's XML (undoable).
    pub fn set_chart_xml(&mut self, part: &str, xml: &str) -> bool {
        if !self.doc.pkg.has(part) || XmlDoc::parse(xml.as_bytes()).is_err() {
            return false;
        }
        self.begin();
        let old = self.part_bytes(part);
        self.pending_parts.push((part.to_string(), old));
        self.put_part_bytes(part, xml.as_bytes().to_vec());
        self.cache.clear();
        self.commit("Chart", false);
        true
    }

    /// The workbook holding a chart's data: (its part, its bytes).
    pub fn chart_workbook(&mut self, part: &str) -> Option<(String, Vec<u8>)> {
        let r = self.doc.pkg.rels(part).into_iter().find(|r| !r.external && (r.kind.ends_with("/package") || r.kind.ends_with("/oleObject")))?;
        let name = crate::package::Package::resolve(part, &r.target);
        let b = self.doc.pkg.raw(&name)?.to_vec();
        Some((name, b))
    }

    /// Replace the workbook holding a chart's data (undoable).
    pub fn set_chart_workbook(&mut self, part: &str, bytes: &[u8]) -> bool {
        let Some((name, _)) = self.chart_workbook(part) else { return false };
        self.begin();
        let old = self.part_bytes(&name);
        self.pending_parts.push((name.clone(), old));
        self.doc.pkg.put_raw(&name, bytes.to_vec());
        self.commit("Chart Data", false);
        true
    }
}
