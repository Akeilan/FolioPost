//! The .docx package: a zip of parts. Parts Folio never touches are written
//! back byte for byte; XML parts are parsed when first needed.

use crate::xml::{XmlDoc, XmlError};
use std::collections::{BTreeMap, HashMap};
use std::io::{Cursor, Read, Write};

#[derive(Debug)]
pub enum PkgError {
    Io(std::io::Error),
    Zip(String),
    Xml(XmlError),
    Missing(String),
}

impl std::fmt::Display for PkgError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            PkgError::Io(e) => write!(f, "{}", e),
            PkgError::Zip(e) => write!(f, "not a valid document package: {}", e),
            PkgError::Xml(e) => write!(f, "{}", e),
            PkgError::Missing(p) => write!(f, "the document has no {}", p),
        }
    }
}

impl From<std::io::Error> for PkgError {
    fn from(e: std::io::Error) -> Self {
        PkgError::Io(e)
    }
}
impl From<XmlError> for PkgError {
    fn from(e: XmlError) -> Self {
        PkgError::Xml(e)
    }
}

struct Entry {
    name: String,
    raw: Vec<u8>,
    deflate: bool,
}

#[derive(Clone, Debug)]
pub struct Rel {
    pub id: String,
    pub kind: String,
    pub target: String,
    pub external: bool,
}

pub struct Package {
    entries: Vec<Entry>,
    xml: HashMap<String, XmlDoc>,
    dirty: std::collections::HashSet<String>,
}

pub const REL_OFFICE_DOC: &str =
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument";

impl Package {
    pub fn open(bytes: &[u8]) -> Result<Package, PkgError> {
        let mut zip = zip::ZipArchive::new(Cursor::new(bytes)).map_err(|e| PkgError::Zip(e.to_string()))?;
        let mut entries = Vec::with_capacity(zip.len());
        for i in 0..zip.len() {
            let mut f = zip.by_index(i).map_err(|e| PkgError::Zip(e.to_string()))?;
            if f.is_dir() {
                continue;
            }
            let name = f.name().to_string();
            // no path tricks inside the package
            if name.contains("..") {
                continue;
            }
            let deflate = f.compression() != zip::CompressionMethod::Stored;
            let mut raw = Vec::with_capacity(f.size() as usize);
            f.read_to_end(&mut raw)?;
            entries.push(Entry { name, raw, deflate });
        }
        Ok(Package { entries, xml: HashMap::new(), dirty: Default::default() })
    }

    pub fn from_parts(parts: Vec<(String, Vec<u8>)>) -> Package {
        let entries = parts.into_iter().map(|(name, raw)| Entry { name, raw, deflate: true }).collect();
        Package { entries, xml: HashMap::new(), dirty: Default::default() }
    }

    pub fn has(&self, name: &str) -> bool {
        self.entries.iter().any(|e| e.name == name)
    }

    pub fn part_names(&self) -> Vec<String> {
        self.entries.iter().map(|e| e.name.clone()).collect()
    }

    pub fn raw(&self, name: &str) -> Option<&[u8]> {
        self.entries.iter().find(|e| e.name == name).map(|e| e.raw.as_slice())
    }

    /// Parsed XML of a part (parsed on first use).
    pub fn xml(&mut self, name: &str) -> Result<&XmlDoc, PkgError> {
        self.load(name)?;
        Ok(&self.xml[name])
    }

    /// Mutable XML of a part: the part will be re-serialized on save.
    pub fn xml_mut(&mut self, name: &str) -> Result<&mut XmlDoc, PkgError> {
        self.load(name)?;
        self.dirty.insert(name.to_string());
        Ok(self.xml.get_mut(name).unwrap())
    }

    pub fn take_xml(&mut self, name: &str) -> Result<XmlDoc, PkgError> {
        self.load(name)?;
        self.dirty.insert(name.to_string());
        Ok(self.xml.remove(name).unwrap())
    }

    pub fn put_xml(&mut self, name: &str, doc: XmlDoc) {
        if !self.has(name) {
            self.entries.push(Entry { name: name.to_string(), raw: Vec::new(), deflate: true });
        }
        self.dirty.insert(name.to_string());
        self.xml.insert(name.to_string(), doc);
    }

    pub fn put_raw(&mut self, name: &str, raw: Vec<u8>) {
        self.xml.remove(name);
        self.dirty.remove(name);
        if let Some(e) = self.entries.iter_mut().find(|e| e.name == name) {
            e.raw = raw;
        } else {
            self.entries.push(Entry { name: name.to_string(), raw, deflate: true });
        }
    }

    /// Take a part out of the package.
    pub fn remove(&mut self, name: &str) {
        self.entries.retain(|e| e.name != name);
        self.xml.remove(name);
        self.dirty.remove(name);
    }

    /// A part's bytes as they would be saved now.
    pub fn bytes(&self, name: &str) -> Option<Vec<u8>> {
        let e = self.entries.iter().find(|e| e.name == name)?;
        if self.dirty.contains(name) {
            if let Some(d) = self.xml.get(name) {
                return Some(d.serialize().into_bytes());
            }
        }
        Some(e.raw.clone())
    }

    fn load(&mut self, name: &str) -> Result<(), PkgError> {
        if self.xml.contains_key(name) {
            return Ok(());
        }
        let raw = self.raw(name).ok_or_else(|| PkgError::Missing(name.to_string()))?;
        let doc = XmlDoc::parse(raw)?;
        self.xml.insert(name.to_string(), doc);
        Ok(())
    }

    // ------------------------------------------------------------ relations
    pub fn rels_name(part: &str) -> String {
        match part.rfind('/') {
            Some(i) => format!("{}/_rels/{}.rels", &part[..i], &part[i + 1..]),
            None => format!("_rels/{}.rels", part),
        }
    }

    pub fn rels(&mut self, part: &str) -> Vec<Rel> {
        let name = Self::rels_name(part);
        let Ok(doc) = self.xml(&name) else { return Vec::new() };
        doc.elements(doc.root)
            .map(|r| Rel {
                id: doc.attr(r, "Id").unwrap_or("").to_string(),
                kind: doc.attr(r, "Type").unwrap_or("").to_string(),
                target: doc.attr(r, "Target").unwrap_or("").to_string(),
                external: doc.attr(r, "TargetMode") == Some("External"),
            })
            .collect()
    }

    /// The target to write in `part`'s relationships for `target_part`.
    pub fn relative_target(part: &str, target_part: &str) -> String {
        let base = match part.rfind('/') {
            Some(i) => &part[..i + 1],
            None => "",
        };
        match target_part.strip_prefix(base) {
            Some(rest) => rest.to_string(),
            None => format!("/{}", target_part),
        }
    }

    /// Where relationship `rid` of `part` points (as written).
    pub fn rel_target(&self, part: &str, rid: &str) -> Option<String> {
        let name = Self::rels_name(part);
        let find = |x: &XmlDoc| x.elements(x.root).find(|&r| x.attr(r, "Id") == Some(rid))
            .and_then(|r| x.attr(r, "Target").map(|s| s.to_string()));
        if let Some(x) = self.xml.get(&name) {
            return find(x);
        }
        let x = XmlDoc::parse(self.raw(&name)?).ok()?;
        find(&x)
    }

    /// The package path a relationship of `part` points to.
    pub fn resolve(part: &str, target: &str) -> String {
        if let Some(t) = target.strip_prefix('/') {
            return t.to_string();
        }
        let base = match part.rfind('/') {
            Some(i) => &part[..i],
            None => "",
        };
        let mut segs: Vec<&str> = if base.is_empty() { Vec::new() } else { base.split('/').collect() };
        for s in target.split('/') {
            match s {
                ".." => {
                    segs.pop();
                }
                "." | "" => {}
                s => segs.push(s),
            }
        }
        segs.join("/")
    }

    /// The main document part (word/document.xml normally).
    pub fn main_part(&mut self) -> Result<String, PkgError> {
        for r in self.rels("") {
            if r.kind == REL_OFFICE_DOC
                || r.kind.ends_with("/officeDocument")
            {
                return Ok(Self::resolve("", &r.target));
            }
        }
        if self.has("word/document.xml") {
            return Ok("word/document.xml".into());
        }
        Err(PkgError::Missing("main document part".into()))
    }

    /// Find the part related to `part` by relationship type suffix
    /// (e.g. "/styles").
    pub fn related(&mut self, part: &str, kind_suffix: &str) -> Option<String> {
        self.rels(part)
            .into_iter()
            .find(|r| r.kind.ends_with(kind_suffix) && !r.external)
            .map(|r| Self::resolve(part, &r.target))
    }

    pub fn add_rel(&mut self, part: &str, kind: &str, target: &str) -> String {
        let name = Self::rels_name(part);
        if !self.has(&name) {
            let doc = XmlDoc::with_root(
                "Relationships",
                &[("xmlns", "http://schemas.openxmlformats.org/package/2006/relationships")],
            );
            self.put_xml(&name, doc);
        }
        let doc = self.xml_mut(&name).unwrap();
        let mut n = 1;
        let ids: Vec<String> =
            doc.elements(doc.root).filter_map(|r| doc.attr(r, "Id").map(|s| s.to_string())).collect();
        while ids.contains(&format!("rId{}", n)) {
            n += 1;
        }
        let id = format!("rId{}", n);
        let el = doc.new_element("Relationship", &[("Id", &id), ("Type", kind), ("Target", target)]);
        let root = doc.root;
        doc.append(root, el);
        id
    }

    /// A content type for every part with extension `ext`.
    pub fn ensure_default(&mut self, ext: &str, ctype: &str) {
        let Ok(doc) = self.xml_mut("[Content_Types].xml") else { return };
        let root = doc.root;
        let has = doc.children_named(root, "Default")
            .any(|d| doc.attr(d, "Extension").map(|e| e.eq_ignore_ascii_case(ext)).unwrap_or(false));
        if !has {
            let el = doc.new_element("Default", &[("Extension", ext), ("ContentType", ctype)]);
            doc.insert(root, 0, el);
        }
    }

    pub fn set_content_type(&mut self, part: &str, ctype: &str) {
        let Ok(doc) = self.xml_mut("[Content_Types].xml") else { return };
        let pname = format!("/{}", part);
        let root = doc.root;
        for o in doc.children_named(root, "Override").collect::<Vec<_>>() {
            if doc.attr(o, "PartName") == Some(&pname) {
                doc.set_attr(o, "ContentType", ctype);
                return;
            }
        }
        let el = doc.new_element("Override", &[("PartName", &pname), ("ContentType", ctype)]);
        doc.append(root, el);
    }

    // ------------------------------------------------------------ saving
    pub fn write(&self) -> Result<Vec<u8>, PkgError> {
        let mut buf = Cursor::new(Vec::new());
        {
            let mut zip = zip::ZipWriter::new(&mut buf);
            // [Content_Types].xml first, as Word writes it
            let mut order: Vec<&Entry> = self.entries.iter().collect();
            order.sort_by_key(|e| if e.name == "[Content_Types].xml" { 0 } else { 1 });
            for e in order {
                let opts = zip::write::SimpleFileOptions::default().compression_method(if e.deflate {
                    zip::CompressionMethod::Deflated
                } else {
                    zip::CompressionMethod::Stored
                });
                zip.start_file(e.name.as_str(), opts).map_err(|e| PkgError::Zip(e.to_string()))?;
                if self.dirty.contains(&e.name) {
                    if let Some(doc) = self.xml.get(&e.name) {
                        zip.write_all(doc.serialize().as_bytes())?;
                        continue;
                    }
                }
                zip.write_all(&e.raw)?;
            }
            zip.finish().map_err(|e| PkgError::Zip(e.to_string()))?;
        }
        Ok(buf.into_inner())
    }

    pub fn save(&self, path: &str) -> Result<(), PkgError> {
        let data = self.write()?;
        // write next to the file, then replace it: a failed save never
        // leaves a half-written document
        let tmp = format!("{}.folio-tmp", path);
        std::fs::write(&tmp, &data)?;
        std::fs::rename(&tmp, path)?;
        Ok(())
    }

    /// Parts as (name, bytes), with modified XML serialized.
    pub fn parts(&self) -> BTreeMap<String, Vec<u8>> {
        let mut out = BTreeMap::new();
        for e in &self.entries {
            let data = match (self.dirty.contains(&e.name), self.xml.get(&e.name)) {
                (true, Some(d)) => d.serialize().into_bytes(),
                _ => e.raw.clone(),
            };
            out.insert(e.name.clone(), data);
        }
        out
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn resolve_paths() {
        assert_eq!(Package::resolve("word/document.xml", "styles.xml"), "word/styles.xml");
        assert_eq!(Package::resolve("word/document.xml", "../customXml/item1.xml"), "customXml/item1.xml");
        assert_eq!(Package::resolve("", "word/document.xml"), "word/document.xml");
        assert_eq!(Package::rels_name("word/document.xml"), "word/_rels/document.xml.rels");
        assert_eq!(Package::rels_name(""), "_rels/.rels");
    }
}
