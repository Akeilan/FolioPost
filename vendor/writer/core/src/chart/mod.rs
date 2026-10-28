//! Charts in documents (c:chartSpace parts): read from the part and its
//! cached values, drawn with cairo.

pub mod draw;
pub mod ex;
pub mod model;
pub mod xml;

use std::collections::HashMap;
use std::sync::{Arc, Mutex, OnceLock};

fn cache() -> &'static Mutex<HashMap<(usize, [u32; 12]), Arc<model::Chart>>> {
    static C: OnceLock<Mutex<HashMap<(usize, [u32; 12]), Arc<model::Chart>>>> = OnceLock::new();
    C.get_or_init(|| Mutex::new(HashMap::new()))
}

/// The chart a part's bytes hold (read once per version of the part).
pub fn chart_of(bytes: &Arc<Vec<u8>>, theme: &[u32; 12]) -> Option<Arc<model::Chart>> {
    let key = (Arc::as_ptr(bytes) as usize, *theme);
    if let Some(c) = cache().lock().ok()?.get(&key) {
        return Some(c.clone());
    }
    let text = String::from_utf8_lossy(bytes);
    let ch = Arc::new(model::Chart::parse(&text, theme).ok()?);
    let mut m = cache().lock().ok()?;
    if m.len() > 64 {
        m.clear();
    }
    m.insert(key, ch.clone());
    Some(ch)
}

/// Draw a chart part's chart into (0, 0, w, h) points.
pub fn draw(cr: &cairo::Context, bytes: &Arc<Vec<u8>>, w: f64, h: f64, theme: &[u32; 12], font: &str) -> bool {
    let Some(ch) = chart_of(bytes, theme) else { return false };
    let p = draw::Painter { theme: *theme, font: font.to_string(), text: std::cell::Cell::new(0x595959) };
    let mut pen = draw::Pen::new();
    p.paint_chart(&ch, cr, 0.0, 0.0, w, h, 1.0, &mut pen);
    true
}

/// Draw an Office 2016 chart part (treemap, sunburst) into (0, 0, w, h).
pub fn draw_ex(cr: &cairo::Context, bytes: &Arc<Vec<u8>>, w: f64, h: f64, theme: &[u32; 12], font: &str) -> bool {
    let text = String::from_utf8_lossy(bytes);
    let Some(ch) = ex::parse(&text, theme) else { return false };
    ex::draw(cr, &ch, w, h, font);
    true
}
