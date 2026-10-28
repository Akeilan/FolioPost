//! Fonts: finding the font a document asks for (or the metric-compatible
//! stand-in), its metrics as Word measures them, and shaping text with it.

use rustybuzz::ttf_parser;
use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Arc;

/// Fonts that are drawn with a metric-compatible substitute: the text takes
/// exactly the same room, so lines and pages break where Word breaks them.
pub const SUBSTITUTES: &[(&str, &str)] = &[
    ("calibri", "Carlito"),
    ("calibri light", "Carlito"),
    ("cambria", "Caladea"),
    ("cambria math", "Caladea"),
    ("arial", "Liberation Sans"),
    ("helvetica", "Liberation Sans"),
    ("arial narrow", "Liberation Sans Narrow"),
    ("times new roman", "Liberation Serif"),
    ("times", "Liberation Serif"),
    ("courier new", "Liberation Mono"),
    ("courier", "Liberation Mono"),
    ("georgia", "Gelasio"),
    ("segoe ui", "Selawik"),
    ("aptos", "Carlito"),
    ("aptos display", "Carlito"),
    ("verdana", "DejaVu Sans"),
    ("tahoma", "DejaVu Sans"),
    ("symbol", "OpenSymbol"),
    ("wingdings", "OpenSymbol"),
];

const FALLBACKS: &[&str] = &[
    "Carlito",
    "Liberation Sans",
    "DejaVu Sans",
    "Noto Sans",
    "Noto Sans Symbols",
    "Noto Sans Symbols2",
    "OpenSymbol",
    "Noto Sans CJK SC",
    "Noto Color Emoji",
    "DejaVu Serif",
];

#[derive(Debug)]
pub struct Font {
    pub id: usize,
    pub family: String,
    pub path: PathBuf,
    pub index: u32,
    data: Arc<Vec<u8>>,
    pub upem: f64,
    /// hhea metrics in font units (ascent positive, descent positive).
    pub ascent: f64,
    pub descent: f64,
    pub line_gap: f64,
    pub underline_pos: f64,
    pub underline_thick: f64,
    pub strike_pos: f64,
    pub strike_thick: f64,
    pub synth_bold: bool,
    pub synth_italic: bool,
    pub space_gid: u16,
    coverage: std::sync::Mutex<HashMap<u32, bool>>,
}

#[derive(Clone, Copy, Debug)]
pub struct Glyph {
    pub gid: u16,
    /// byte offset into the shaped text where this glyph's cluster starts
    pub cluster: u32,
    /// in points
    pub advance: f64,
    pub x_offset: f64,
    pub y_offset: f64,
}

impl Font {
    pub fn data(&self) -> &[u8] {
        &self.data
    }

    /// Height of a single line in points, as Word measures it.
    pub fn line_height(&self, size: f64) -> f64 {
        (self.ascent + self.descent + self.line_gap) * size / self.upem
    }

    /// Distance from the top of a single line to the baseline, in points.
    pub fn ascent_pt(&self, size: f64) -> f64 {
        (self.ascent + self.line_gap) * size / self.upem
    }

    pub fn descent_pt(&self, size: f64) -> f64 {
        self.descent * size / self.upem
    }

    pub fn has_char(&self, ch: char) -> bool {
        if let Some(&v) = self.coverage.lock().unwrap().get(&(ch as u32)) {
            return v;
        }
        let v = match ttf_parser::Face::parse(&self.data, self.index) {
            Ok(f) => f.glyph_index(ch).map(|g| g.0 != 0).unwrap_or(false),
            Err(_) => false,
        };
        self.coverage.lock().unwrap().insert(ch as u32, v);
        v
    }

    /// Shape `text` at `size` points. Word turns kerning and ligatures off
    /// unless a run asks for them.
    pub fn shape(&self, text: &str, size: f64, kern: bool, ligatures: bool) -> Vec<Glyph> {
        let Some(face) = rustybuzz::Face::from_slice(&self.data, self.index) else { return Vec::new() };
        let mut buf = rustybuzz::UnicodeBuffer::new();
        buf.push_str(text);
        buf.guess_segment_properties();
        let tag = rustybuzz::ttf_parser::Tag::from_bytes;
        let mut feats = vec![rustybuzz::Feature::new(tag(b"kern"), kern as u32, ..)];
        if !ligatures {
            feats.push(rustybuzz::Feature::new(tag(b"liga"), 0, ..));
            feats.push(rustybuzz::Feature::new(tag(b"clig"), 0, ..));
        }
        let out = rustybuzz::shape(&face, &feats, buf);
        let scale = size / self.upem;
        out.glyph_infos()
            .iter()
            .zip(out.glyph_positions())
            .map(|(i, p)| Glyph {
                gid: i.glyph_id as u16,
                cluster: i.cluster,
                advance: p.x_advance as f64 * scale,
                x_offset: p.x_offset as f64 * scale,
                y_offset: p.y_offset as f64 * scale,
            })
            .collect()
    }

    /// Advance width of a single character, in points.
    pub fn char_width(&self, ch: char, size: f64) -> f64 {
        let Ok(f) = ttf_parser::Face::parse(&self.data, self.index) else { return 0.0 };
        let g = f.glyph_index(ch).unwrap_or(ttf_parser::GlyphId(self.space_gid));
        f.glyph_hor_advance(g).unwrap_or(0) as f64 * size / self.upem
    }
}

pub struct FontCache {
    db: fontdb::Database,
    fonts: Vec<Arc<Font>>,
    by_key: HashMap<(String, bool, bool), usize>,
    fallback_ids: Option<Vec<usize>>,
}

fn sub_name(family: &str) -> Option<&'static str> {
    let l = family.to_lowercase();
    SUBSTITUTES.iter().find(|(k, _)| *k == l).map(|(_, v)| *v)
}

impl Default for FontCache {
    fn default() -> Self {
        Self::new()
    }
}

impl FontCache {
    pub fn new() -> FontCache {
        let mut db = fontdb::Database::new();
        db.load_system_fonts();
        // Folio's own fonts, when installed next to the program
        for d in ["/usr/share/folio-writer/fonts", "/usr/local/share/folio-writer/fonts"] {
            if std::path::Path::new(d).is_dir() {
                db.load_fonts_dir(d);
            }
        }
        db.set_sans_serif_family("Liberation Sans");
        db.set_serif_family("Liberation Serif");
        db.set_monospace_family("Liberation Mono");
        FontCache { db, fonts: Vec::new(), by_key: HashMap::new(), fallback_ids: None }
    }

    pub fn has_family(&self, family: &str) -> bool {
        let l = family.to_lowercase();
        self.db.faces().any(|f| f.families.iter().any(|(n, _)| n.to_lowercase() == l))
    }

    /// All installed family names (for the font list).
    pub fn families(&self) -> Vec<String> {
        let mut v: Vec<String> =
            self.db.faces().filter_map(|f| f.families.first().map(|(n, _)| n.clone())).collect();
        v.sort_by_key(|s| s.to_lowercase());
        v.dedup();
        v
    }

    pub fn get(&mut self, family: &str, bold: bool, italic: bool) -> Arc<Font> {
        let key = (family.to_lowercase(), bold, italic);
        if let Some(&i) = self.by_key.get(&key) {
            return self.fonts[i].clone();
        }
        let font = self.load(family, bold, italic);
        self.by_key.insert(key, font.id);
        font
    }

    fn load(&mut self, family: &str, bold: bool, italic: bool) -> Arc<Font> {
        let mut families: Vec<fontdb::Family> = Vec::new();
        // the font itself when installed, else its stand-in
        let installed = self.has_family(family);
        let sub = sub_name(family);
        if installed {
            families.push(fontdb::Family::Name(family));
        }
        if let Some(s) = sub {
            families.push(fontdb::Family::Name(s));
        }
        families.push(fontdb::Family::Name("Carlito"));
        families.push(fontdb::Family::SansSerif);
        let query = fontdb::Query {
            families: &families,
            weight: if bold { fontdb::Weight::BOLD } else { fontdb::Weight::NORMAL },
            stretch: fontdb::Stretch::Normal,
            style: if italic { fontdb::Style::Italic } else { fontdb::Style::Normal },
        };
        let id = self.db.query(&query).or_else(|| self.db.faces().next().map(|f| f.id));
        let id = id.expect("no fonts installed");
        let face = self.db.face(id).unwrap();
        let path = match &face.source {
            fontdb::Source::File(p) => p.clone(),
            fontdb::Source::SharedFile(p, _) => p.clone(),
            fontdb::Source::Binary(_) => PathBuf::new(),
        };
        let synth_bold = bold && face.weight.0 < 600;
        let synth_italic = italic && face.style == fontdb::Style::Normal;
        let fam = face.families.first().map(|(n, _)| n.clone()).unwrap_or_default();
        let index = face.index;
        let data = self
            .db
            .with_face_data(id, |d, _| Arc::new(d.to_vec()))
            .unwrap_or_else(|| Arc::new(Vec::new()));
        // reuse an already loaded copy of the same face
        if let Some(f) = self.fonts.iter().find(|f| f.path == path && f.index == index
            && f.synth_bold == synth_bold && f.synth_italic == synth_italic) {
            return f.clone();
        }
        let font = make_font(self.fonts.len(), fam, path, index, data, synth_bold, synth_italic);
        let font = Arc::new(font);
        self.fonts.push(font.clone());
        font
    }

    pub fn by_id(&self, id: usize) -> Arc<Font> {
        self.fonts[id].clone()
    }

    /// A font that has `ch`, for text the document's font can't show.
    pub fn fallback(&mut self, ch: char, bold: bool, italic: bool) -> Option<Arc<Font>> {
        if self.fallback_ids.is_none() {
            let mut ids = Vec::new();
            for name in FALLBACKS {
                if self.has_family(name) {
                    ids.push(self.get(name, false, false).id);
                }
            }
            self.fallback_ids = Some(ids);
        }
        let ids = self.fallback_ids.clone().unwrap();
        for id in ids {
            let f = self.fonts[id].clone();
            if f.has_char(ch) {
                let fam = f.family.clone();
                return Some(self.get(&fam, bold, italic));
            }
        }
        None
    }
}

fn make_font(id: usize, family: String, path: PathBuf, index: u32, data: Arc<Vec<u8>>,
             synth_bold: bool, synth_italic: bool) -> Font {
    let mut f = Font {
        id,
        family,
        path,
        index,
        data: data.clone(),
        upem: 2048.0,
        ascent: 1536.0,
        descent: 512.0,
        line_gap: 0.0,
        underline_pos: -150.0,
        underline_thick: 100.0,
        strike_pos: 600.0,
        strike_thick: 100.0,
        synth_bold,
        synth_italic,
        space_gid: 3,
        coverage: Default::default(),
    };
    if let Ok(face) = ttf_parser::Face::parse(&data, index) {
        f.upem = face.units_per_em() as f64;
        f.ascent = face.ascender() as f64;
        f.descent = -(face.descender() as f64);
        f.line_gap = face.line_gap() as f64;
        // a few fonts have empty hhea metrics: use the Windows metrics
        if f.ascent + f.descent <= 0.0 {
            if let Some(os2) = face.tables().os2 {
                f.ascent = os2.windows_ascender() as f64;
                f.descent = os2.windows_descender() as f64;
            }
        }
        if let Some(u) = face.underline_metrics() {
            f.underline_pos = u.position as f64;
            f.underline_thick = u.thickness as f64;
        }
        if let Some(s) = face.strikeout_metrics() {
            f.strike_pos = s.position as f64;
            f.strike_thick = s.thickness as f64;
        }
        if let Some(g) = face.glyph_index(' ') {
            f.space_gid = g.0;
        }
    }
    f
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn calibri_line_height() {
        let mut fc = FontCache::new();
        let f = fc.get("Calibri", false, false);
        // Word: Calibri 11 pt single spacing is 13.43 pt
        let h = f.line_height(11.0);
        assert!((h - 13.43).abs() < 0.02, "{} {}", f.family, h);
        let g = f.shape("Hello world", 11.0, false, false);
        assert_eq!(g.len(), 11);
    }

    #[test]
    fn times_line_height() {
        let mut fc = FontCache::new();
        let f = fc.get("Times New Roman", false, false);
        let h = f.line_height(12.0);
        assert!((h - 13.8).abs() < 0.05, "{} {}", f.family, h);
    }
}
