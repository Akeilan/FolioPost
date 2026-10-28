//! Charts: the model, reading and writing the DrawingML chart part, and the data a
//! chart shows (read from the cells its series refer to, or from the file's cache).

use super::xml::{self, Element};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Kind {
    Bar,
    Line,
    Pie,
    Doughnut,
    Area,
    Scatter,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Group {
    Clustered,
    Stacked,
    Percent,
}

/// Where a piece of chart data comes from: a reference (with the file's cached values
/// as a fallback) or literal values.
#[derive(Clone, Debug, PartialEq, Default)]
pub struct Src {
    pub f: Option<String>,
    pub cache: Vec<CVal>,
    pub fmt: Option<String>,
}

#[derive(Clone, Debug, PartialEq)]
pub enum CVal {
    Empty,
    Num(f64),
    Str(String),
}

#[derive(Clone, Debug, PartialEq, Default)]
pub struct Series {
    pub name: Option<Src>,
    pub cat: Option<Src>,
    pub val: Option<Src>,
    pub color: Option<u32>,
    pub labels: bool,
    pub smooth: bool,
    /// colours of single points (dPt): pie slices
    pub point_colors: Vec<(usize, u32)>,
    /// drawn without fill or line (a waterfall's or funnel's base)
    pub hidden: bool,
    /// data label position (dLblPos: ctr, inEnd, inBase, outEnd, t, b, bestFit)
    pub label_pos: Option<String>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Plot {
    pub kind: Kind,
    pub horizontal: bool,
    pub group: Group,
    pub markers: bool,
    /// scatter: lines between the points
    pub lines: bool,
    pub secondary: bool,
    pub vary: bool,
    pub gap: u32,
    pub overlap: i32,
    pub hole: u32,
    pub first_angle: u32,
    pub series: Vec<Series>,
    /// the element the file used when it isn't the plain one (bar3DChart...)
    pub file_tag: Option<String>,
    /// a stock chart's high-low lines and up-down bars
    pub stock: bool,
}

impl Plot {
    pub fn new(kind: Kind) -> Plot {
        Plot {
            kind,
            horizontal: false,
            group: Group::Clustered,
            markers: false,
            lines: false,
            secondary: false,
            vary: matches!(kind, Kind::Pie | Kind::Doughnut),
            gap: 219,
            overlap: -27,
            hole: 75,
            first_angle: 0,
            series: Vec::new(),
            file_tag: None,
            stock: false,
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub enum Title {
    None,
    /// the series name with one series, "Chart Title" otherwise
    Auto,
    Text(String),
    Ref(Src),
}

#[derive(Clone, Debug, PartialEq)]
pub struct Chart {
    pub title: Title,
    pub plots: Vec<Plot>,
    /// "b", "r", "t", "l", "tr"; None: no legend
    pub legend: Option<String>,
    pub x_title: Option<String>,
    pub y_title: Option<String>,
    pub gridlines: bool,
    /// colour set: 0 colourful (theme accents), 1..=4 monochrome on accent 1..4
    pub palette: u8,
    /// the part as read; written back with only the references updated while the
    /// chart isn't changed in ways only the model describes
    pub orig: Option<(String, Element)>,
    /// gridlines from the category axis (vertical in a column chart), minor ones
    pub vgrid: bool,
    pub minor_h: bool,
    pub minor_v: bool,
    pub cat_deleted: bool,
    pub val_deleted: bool,
    pub data_table: bool,
    /// the chart area's fill and the text colour
    pub bg: Option<u32>,
    pub text: u32,
    /// legend entries deleted
    pub legend_deleted: Vec<usize>,
}

impl Default for Chart {
    fn default() -> Self {
        Chart { title: Title::Auto, plots: Vec::new(), legend: Some("b".into()), x_title: None, y_title: None, gridlines: true, palette: 0, orig: None,
                vgrid: false, minor_h: false, minor_v: false, cat_deleted: false, val_deleted: false, data_table: false,
                bg: None, text: 0x595959, legend_deleted: Vec::new() }
    }
}

pub const NS_C: &str = "http://schemas.openxmlformats.org/drawingml/2006/chart";
pub const NS_A: &str = "http://schemas.openxmlformats.org/drawingml/2006/main";
pub const NS_R: &str = "http://schemas.openxmlformats.org/officeDocument/2006/relationships";

// ---------------------------------------------------------------------- colours

/// A theme colour from a DrawingML colour element (srgbClr, schemeClr with lumMod/lumOff).
pub fn color_of(e: &Element, theme: &[u32; 12]) -> Option<u32> {
    let base = match e.local() {
        "srgbClr" => u32::from_str_radix(e.attr("val")?, 16).ok()?,
        "schemeClr" => {
            let i = match e.attr("val")? {
                "accent1" => 4,
                "accent2" => 5,
                "accent3" => 6,
                "accent4" => 7,
                "accent5" => 8,
                "accent6" => 9,
                "tx1" | "dk1" => 1,
                "bg1" | "lt1" => 0,
                "tx2" | "dk2" => 3,
                "bg2" | "lt2" => 2,
                "hlink" => 10,
                "folHlink" => 11,
                _ => return None,
            };
            theme[i]
        }
        "sysClr" => u32::from_str_radix(e.attr("lastClr").unwrap_or("000000"), 16).ok()?,
        "prstClr" => match e.attr("val")? {
            "black" => 0,
            "white" => 0xFFFFFF,
            "red" => 0xFF0000,
            "green" => 0x008000,
            "blue" => 0x0000FF,
            _ => return None,
        },
        _ => return None,
    };
    let mut c = base;
    let mut lm = 1.0;
    let mut lo = 0.0;
    for m in e.elems() {
        let v = m.attr("val").and_then(|v| v.parse::<f64>().ok()).unwrap_or(100000.0) / 100000.0;
        match m.local() {
            "lumMod" => lm = v,
            "lumOff" => lo = v,
            "shade" => c = scale(c, v),
            "tint" => c = tint(c, v),
            _ => {}
        }
    }
    if lm != 1.0 || lo != 0.0 {
        c = lum(c, lm, lo);
    }
    Some(c)
}

fn scale(c: u32, f: f64) -> u32 {
    let ch = |s: u32| (((c >> s) & 255) as f64 * f).round().clamp(0.0, 255.0) as u32;
    (ch(16) << 16) | (ch(8) << 8) | ch(0)
}

fn tint(c: u32, f: f64) -> u32 {
    let ch = |s: u32| { let x = ((c >> s) & 255) as f64; (x + (255.0 - x) * (1.0 - f)).round().clamp(0.0, 255.0) as u32 };
    (ch(16) << 16) | (ch(8) << 8) | ch(0)
}

/// Luminance modulation as DrawingML does it (in HSL).
pub fn lum(c: u32, m: f64, o: f64) -> u32 {
    let r = ((c >> 16) & 255) as f64 / 255.0;
    let g = ((c >> 8) & 255) as f64 / 255.0;
    let b = (c & 255) as f64 / 255.0;
    let mx = r.max(g).max(b);
    let mn = r.min(g).min(b);
    let mut l = (mx + mn) / 2.0;
    let (h, s) = if mx == mn {
        (0.0, 0.0)
    } else {
        let d = mx - mn;
        let s = if l > 0.5 { d / (2.0 - mx - mn) } else { d / (mx + mn) };
        let h = if mx == r { (g - b) / d + if g < b { 6.0 } else { 0.0 } } else if mx == g { (b - r) / d + 2.0 } else { (r - g) / d + 4.0 };
        (h / 6.0, s)
    };
    l = (l * m + o).clamp(0.0, 1.0);
    let hue = |p: f64, q: f64, mut t: f64| {
        if t < 0.0 { t += 1.0 }
        if t > 1.0 { t -= 1.0 }
        if t < 1.0 / 6.0 { p + (q - p) * 6.0 * t } else if t < 0.5 { q } else if t < 2.0 / 3.0 { p + (q - p) * (2.0 / 3.0 - t) * 6.0 } else { p }
    };
    let (r, g, b) = if s == 0.0 {
        (l, l, l)
    } else {
        let q = if l < 0.5 { l * (1.0 + s) } else { l + s - l * s };
        let p = 2.0 * l - q;
        (hue(p, q, h + 1.0 / 3.0), hue(p, q, h), hue(p, q, h - 1.0 / 3.0))
    };
    let to = |x: f64| (x * 255.0).round().clamp(0.0, 255.0) as u32;
    (to(r) << 16) | (to(g) << 8) | to(b)
}

/// The automatic colour of the i-th series (or pie slice).
pub fn auto_color(theme: &[u32; 12], palette: u8, i: usize) -> u32 {
    if palette >= 1 && palette <= 6 {
        // shades of one accent, darkest to lightest and back
        let base = theme[3 + palette as usize];
        let steps = [1.0, 0.6, 0.8, 0.5, 0.4, 0.75];
        let k = steps[i % steps.len()];
        return if k >= 0.75 && k != 1.0 { lum(base, k, 0.0) } else if k == 1.0 { base } else { lum(base, k, 1.0 - k) };
    }
    let base = theme[4 + i % 6];
    match (i / 6) % 4 {
        0 => base,
        1 => lum(base, 0.6, 0.0),
        2 => lum(base, 0.6, 0.4),
        _ => lum(base, 0.8, 0.2),
    }
}

// ---------------------------------------------------------------------- data

/// One point's value as the chart sees it, with its text.
#[derive(Clone, Debug)]
pub struct Pt {
    pub v: Option<f64>,
    pub text: String,
}

/// Chart kinds by the names the UI uses: col, col-stacked, col-percent, bar(-stacked/-percent),
/// line(-stacked/-percent)(-markers), pie, doughnut, area(-stacked/-percent), scatter(-lines), combo.
pub fn plots_for(kind: &str, mut series: Vec<Series>) -> Vec<Plot> {
    let group = if kind.contains("-percent") { Group::Percent } else if kind.contains("-stacked") { Group::Stacked } else { Group::Clustered };
    let base = kind.split('-').next().unwrap_or("col");
    let mut p = match base {
        "bar" => {
            let mut p = Plot::new(Kind::Bar);
            p.horizontal = true;
            p
        }
        "line" => {
            let mut p = Plot::new(Kind::Line);
            p.markers = kind.contains("-markers");
            p
        }
        "pie" => Plot::new(Kind::Pie),
        "doughnut" => Plot::new(Kind::Doughnut),
        "area" => Plot::new(Kind::Area),
        "scatter" => {
            let mut p = Plot::new(Kind::Scatter);
            p.markers = true;
            p.lines = kind.contains("-lines") || kind.contains("-smooth");
            p
        }
        "combo" => {
            let n = series.len();
            if n >= 2 {
                let last = series.split_off(n - 1);
                let mut col = Plot::new(Kind::Bar);
                col.series = series;
                let mut line = Plot::new(Kind::Line);
                line.series = last;
                line.secondary = kind.contains("-secondary");
                return vec![col, line];
            }
            Plot::new(Kind::Bar)
        }
        _ => Plot::new(Kind::Bar),
    };
    p.group = group;
    if group != Group::Clustered && p.kind == Kind::Bar {
        p.overlap = 100;
        p.gap = 150;
    }
    if matches!(p.kind, Kind::Pie | Kind::Doughnut) {
        series.truncate(1);
    }
    p.series = series;
    if kind.contains("-smooth") {
        p.set_smooth(true);
    }
    vec![p]
}

impl Plot {
    pub fn smooth_any(&self) -> bool {
        self.series.iter().any(|s| s.smooth)
    }
}

impl Plot {
    pub fn set_smooth(&mut self, on: bool) {
        for s in self.series.iter_mut() {
            s.smooth = on;
        }
    }
}

// ---------------------------------------------------------------------- reading

fn val_attr(e: &Element, name: &str) -> Option<String> {
    e.child(name).and_then(|x| x.attr("val")).map(|s| s.to_string())
}

fn on(e: &Element, name: &str, default: bool) -> bool {
    match e.child(name) {
        Some(x) => !matches!(x.attr("val"), Some("0") | Some("false")),
        None => default,
    }
}

fn read_src(e: &Element) -> Option<Src> {
    // e is tx / cat / val / xVal / yVal: a strRef, numRef, multiLvlStrRef, strLit, numLit, or <c:v>
    for x in e.elems() {
        match x.local() {
            "strRef" | "numRef" | "multiLvlStrRef" => {
                let f = x.child("f").map(|f| f.text());
                let cache_el = x.child("strCache").or_else(|| x.child("numCache")).or_else(|| x.child("multiLvlStrCache"));
                let (cache, fmt) = cache_el.map(read_cache).unwrap_or_default();
                return Some(Src { f, cache, fmt });
            }
            "strLit" | "numLit" => {
                let (cache, fmt) = read_cache(x);
                return Some(Src { f: None, cache, fmt });
            }
            "v" => return Some(Src { f: None, cache: vec![CVal::Str(x.text())], fmt: None }),
            _ => {}
        }
    }
    None
}

fn read_cache(e: &Element) -> (Vec<CVal>, Option<String>) {
    let n: usize = val_attr(e, "ptCount").and_then(|v| v.parse().ok()).unwrap_or(0).min(100_000);
    let mut out = vec![CVal::Empty; n];
    let num = e.local() == "numCache" || e.local() == "numLit";
    // multi-level caches: use the innermost level
    let holder = if e.local() == "multiLvlStrCache" { e.child("lvl").unwrap_or(e) } else { e };
    for p in holder.elems_named("pt") {
        let i: usize = match p.attr("idx").and_then(|v| v.parse().ok()) {
            Some(i) => i,
            None => continue,
        };
        let t = p.child("v").map(|v| v.text()).unwrap_or_default();
        let v = if num { t.parse::<f64>().map(CVal::Num).unwrap_or(CVal::Str(t)) } else { CVal::Str(t) };
        if i >= out.len() {
            if i > 100_000 {
                continue;
            }
            out.resize(i + 1, CVal::Empty);
        }
        out[i] = v;
    }
    (out, e.child("formatCode").map(|f| f.text()))
}

fn rich_text(e: &Element) -> String {
    // tx/rich/a:p/a:r/a:t, paragraphs joined by newlines
    let mut out = Vec::new();
    for p in e.elems_named("p") {
        let mut s = String::new();
        for r in p.elems() {
            match r.local() {
                "r" | "fld" => s.push_str(&r.child("t").map(|t| t.text()).unwrap_or_default()),
                "br" => s.push('\n'),
                _ => {}
            }
        }
        out.push(s);
    }
    out.join("\n")
}

fn read_title(t: &Element) -> Title {
    match t.child("tx") {
        Some(tx) => {
            if let Some(rich) = tx.child("rich") {
                Title::Text(rich_text(rich))
            } else if let Some(src) = read_src(tx) {
                Title::Ref(src)
            } else {
                Title::Auto
            }
        }
        None => Title::Auto,
    }
}

fn sp_color(e: &Element, theme: &[u32; 12], line: bool) -> Option<u32> {
    let sp = e.child("spPr")?;
    let fill = if line { sp.child("ln")?.child("solidFill")? } else { sp.child("solidFill").or_else(|| sp.child("ln").and_then(|l| l.child("solidFill")))? };
    fill.elems().find_map(|c| color_of(c, theme))
}

impl Chart {
    /// Read a chart part. Kinds the model doesn't draw natively are drawn as their
    /// nearest kind and always written back as read.
    pub fn parse(text: &str, theme: &[u32; 12]) -> Result<Chart, String> {
        let (prolog, root) = xml::parse(text)?;
        let chart = root.child("chart").ok_or("no chart element")?;
        let mut ch = Chart::default();
        ch.title = match chart.child("title") {
            Some(t) => read_title(t),
            None => {
                if on(chart, "autoTitleDeleted", false) { Title::None } else { Title::Auto }
            }
        };
        ch.legend = chart.child("legend").map(|l| val_attr(l, "legendPos").unwrap_or_else(|| "r".into()));
        ch.gridlines = false;
        let pa = chart.child("plotArea").ok_or("no plot area")?;
        // axes by id
        let axes: Vec<&Element> = pa.elems().filter(|e| matches!(e.local(), "catAx" | "valAx" | "dateAx" | "serAx")).collect();
        let axis_title = |a: &Element| a.child("title").map(|t| match read_title(t) { Title::Text(s) => s, _ => String::new() });
        let mut primary_ids: Option<Vec<String>> = None;
        for p in pa.elems() {
            let tag = p.local().to_string();
            let (kind, native) = match tag.as_str() {
                "barChart" => (Kind::Bar, true),
                "bar3DChart" => (Kind::Bar, false),
                "lineChart" => (Kind::Line, true),
                "line3DChart" | "stockChart" | "radarChart" | "surfaceChart" | "surface3DChart" => (Kind::Line, false),
                "pieChart" => (Kind::Pie, true),
                "pie3DChart" | "ofPieChart" => (Kind::Pie, false),
                "doughnutChart" => (Kind::Doughnut, true),
                "areaChart" => (Kind::Area, true),
                "area3DChart" => (Kind::Area, false),
                "scatterChart" => (Kind::Scatter, true),
                "bubbleChart" => (Kind::Scatter, false),
                _ => continue,
            };
            let mut pl = Plot::new(kind);
            if !native {
                pl.file_tag = Some(tag.clone());
            }
            pl.horizontal = val_attr(p, "barDir").as_deref() == Some("bar");
            pl.group = match val_attr(p, "grouping").as_deref() {
                Some("stacked") => Group::Stacked,
                Some("percentStacked") => Group::Percent,
                _ => Group::Clustered,
            };
            pl.vary = on(p, "varyColors", false);
            if let Some(g) = val_attr(p, "gapWidth").and_then(|v| v.trim_end_matches('%').parse().ok()) {
                pl.gap = g;
            } else {
                pl.gap = 150;
            }
            pl.overlap = val_attr(p, "overlap").and_then(|v| v.trim_end_matches('%').parse().ok()).unwrap_or(if pl.group != Group::Clustered { 100 } else { 0 });
            pl.hole = val_attr(p, "holeSize").and_then(|v| v.trim_end_matches('%').parse().ok()).unwrap_or(50);
            pl.first_angle = val_attr(p, "firstSliceAng").and_then(|v| v.parse().ok()).unwrap_or(0);
            let scatter_style = val_attr(p, "scatterStyle").unwrap_or_default();
            pl.markers = match kind {
                Kind::Line => on(p, "marker", false),
                Kind::Scatter => true,
                _ => false,
            };
            pl.lines = kind == Kind::Scatter && scatter_style.starts_with("line") || scatter_style.starts_with("smooth");
            let mut any_line = false;
            let mut any_marker = false;
            for s in p.elems_named("ser") {
                let mut ser = Series::default();
                ser.name = s.child("tx").and_then(read_src);
                if kind == Kind::Scatter {
                    ser.cat = s.child("xVal").and_then(read_src);
                    ser.val = s.child("yVal").and_then(read_src);
                } else {
                    ser.cat = s.child("cat").and_then(read_src);
                    ser.val = s.child("val").and_then(read_src);
                }
                let line_kind = matches!(kind, Kind::Line | Kind::Scatter);
                ser.color = sp_color(s, theme, line_kind).or_else(|| if line_kind { sp_color(s, theme, false) } else { None });
                ser.labels = s.child("dLbls").map(|d| on(d, "showVal", false) || on(d, "showPercent", false)).unwrap_or(false);
                ser.smooth = on(s, "smooth", false);
                for dp in s.elems_named("dPt") {
                    if let (Some(i), Some(c)) = (val_attr(dp, "idx").and_then(|v| v.parse::<usize>().ok()), sp_color(dp, theme, false)) {
                        ser.point_colors.push((i, c));
                    }
                }
                if let Some(sp) = s.child("spPr") {
                    let nofill = sp.child("noFill").is_some();
                    let noline = sp.child("ln").map_or(true, |l| l.child("noFill").is_some());
                    ser.hidden = (nofill && noline && !line_kind) || (line_kind && sp.child("ln").map_or(false, |l| l.child("noFill").is_some()) && kind != Kind::Scatter);
                }
                ser.label_pos = s.child("dLbls").and_then(|d| val_attr(d, "dLblPos"));
                let ln_none = s.child("spPr").and_then(|sp| sp.child("ln")).map(|l| l.child("noFill").is_some()).unwrap_or(false);
                if !ln_none {
                    any_line = true;
                }
                match s.child("marker").and_then(|m| val_attr(m, "symbol")) {
                    Some(sym) if sym == "none" => {}
                    Some(_) => any_marker = true,
                    None => any_marker = any_marker || kind == Kind::Scatter || pl.markers,
                }
                pl.series.push(ser);
            }
            if kind == Kind::Scatter {
                pl.lines = any_line && !scatter_style.eq("marker");
                pl.markers = any_marker || !pl.lines;
            }
            if kind == Kind::Line && !pl.series.is_empty() {
                pl.markers = any_marker;
            }
            if let Some(l) = p.child("dLbls") {
                if on(l, "showVal", false) || on(l, "showPercent", false) {
                    let pos = val_attr(l, "dLblPos");
                    for s in pl.series.iter_mut() {
                        s.labels = true;
                        if s.label_pos.is_none() {
                            s.label_pos = pos.clone();
                        }
                    }
                }
            }
            pl.stock = tag == "stockChart" && (p.child("hiLowLines").is_some() || p.child("upDownBars").is_some());
            // axes this plot uses
            let ids: Vec<String> = p.elems_named("axId").filter_map(|a| a.attr("val").map(|s| s.to_string())).collect();
            match &primary_ids {
                None => primary_ids = Some(ids.clone()),
                Some(pi) => pl.secondary = !ids.is_empty() && ids != *pi,
            }
            for id in &ids {
                if let Some(ax) = axes.iter().find(|a| val_attr(a, "axId").as_deref() == Some(id)) {
                    if pl.secondary {
                        continue;
                    }
                    let pos = val_attr(ax, "axPos").unwrap_or_default();
                    let is_val = ax.local() == "valAx" && !(kind == Kind::Scatter && (pos == "b" || pos == "t"));
                    if ax.child("majorGridlines").is_some() && is_val {
                        ch.gridlines = true;
                    }
                    if ax.child("majorGridlines").is_some() && !is_val {
                        ch.vgrid = true;
                    }
                    if ax.child("minorGridlines").is_some() {
                        if is_val { ch.minor_h = true } else { ch.minor_v = true }
                    }
                    if on(ax, "delete", false) {
                        if is_val { ch.val_deleted = true } else { ch.cat_deleted = true }
                    }
                    if let Some(t) = axis_title(ax) {
                        let vertical = pos == "l" || pos == "r";
                        if vertical { ch.y_title = Some(t) } else { ch.x_title = Some(t) }
                    }
                }
            }
            ch.plots.push(pl);
        }
        if ch.plots.is_empty() {
            return Err("the chart has no plot this program can show".into());
        }
        ch.data_table = pa.child("dTable").is_some();
        if let Some(l) = chart.child("legend") {
            for e in l.elems_named("legendEntry") {
                if on(e, "delete", false) {
                    if let Some(i) = val_attr(e, "idx").and_then(|v| v.parse().ok()) {
                        ch.legend_deleted.push(i);
                    }
                }
            }
        }
        if let Some(sp) = root.child("spPr") {
            if let Some(f) = sp.child("solidFill") {
                ch.bg = f.elems().find_map(|c| color_of(c, theme));
            }
        }
        if let Some(c) = root.child("txPr").and_then(|t| t.child("p")).and_then(|p| p.child("pPr"))
            .and_then(|p| p.child("defRPr")).and_then(|d| d.child("solidFill")).and_then(|f| f.elems().find_map(|c| color_of(c, theme))) {
            ch.text = c;
        }
        // without a title element only a one-series chart gets the automatic title
        if chart.child("title").is_none() && ch.title == Title::Auto
            && (ch.all_series().count() != 1 || ch.all_series().next().map(|s| s.name.is_none()).unwrap_or(true)) {
            ch.title = Title::None;
        }
        ch.orig = Some((prolog, root));
        Ok(ch)
    }

    pub fn all_series(&self) -> impl Iterator<Item = &Series> {
        self.plots.iter().flat_map(|p| p.series.iter())
    }

    /// Kinds a file used that this program draws only approximately.
    pub fn exotic(&self) -> bool {
        self.plots.iter().any(|p| p.file_tag.is_some())
    }
}

// ---------------------------------------------------------------------- values

/// A number as a chart label shows it, in a format code (the common ones).
pub fn format_number(v: f64, fmt: &str) -> String {
    let f = fmt.trim();
    if f.is_empty() || f.eq_ignore_ascii_case("general") {
        return general(v);
    }
    let pct = f.ends_with('%');
    let body = f.trim_end_matches('%');
    let x = if pct { v * 100.0 } else { v };
    let prefix: String = body.chars().take_while(|c| !matches!(c, '0' | '#' | ',' | '.')).filter(|c| *c != '"' && *c != '\\').collect();
    let decimals = body.split('.').nth(1).map(|d| d.chars().take_while(|c| *c == '0' || *c == '#').count()).unwrap_or(0);
    let comma = body.contains(',');
    let mut s = format!("{:.*}", decimals, x.abs());
    if comma {
        let (int, frac) = match s.find('.') {
            Some(i) => (s[..i].to_string(), s[i..].to_string()),
            None => (s.clone(), String::new()),
        };
        let mut g = String::new();
        for (i, ch) in int.chars().enumerate() {
            if i > 0 && (int.len() - i) % 3 == 0 {
                g.push(',');
            }
            g.push(ch);
        }
        s = g + &frac;
    }
    format!("{}{}{}{}", if x < 0.0 { "-" } else { "" }, prefix, s, if pct { "%" } else { "" })
}

fn general(v: f64) -> String {
    if v == v.trunc() && v.abs() < 1e15 {
        return format!("{}", v as i64);
    }
    let s = format!("{:.9}", v);
    let s = s.trim_end_matches('0').trim_end_matches('.').to_string();
    if s.len() > 11 { format!("{:.6e}", v) } else { s }
}

pub fn values(src: &Src) -> Vec<Pt> {
    src.cache.iter().map(|c| match c {
        CVal::Empty => Pt { v: None, text: String::new() },
        CVal::Num(x) => Pt { v: Some(*x), text: format_number(*x, src.fmt.as_deref().unwrap_or("General")) },
        CVal::Str(s) => Pt { v: s.trim().parse::<f64>().ok(), text: s.clone() },
    }).collect()
}

pub fn series_name(ser: &Series, i: usize) -> String {
    match &ser.name {
        Some(src) => {
            let t: Vec<String> = values(src).into_iter().map(|p| p.text).filter(|t| !t.is_empty()).collect();
            if t.is_empty() { format!("Series{}", i + 1) } else { t.join(" ") }
        }
        None => format!("Series{}", i + 1),
    }
}

pub fn title_text(ch: &Chart) -> Option<String> {
    match &ch.title {
        Title::None => None,
        Title::Text(t) => Some(t.clone()),
        Title::Ref(src) => Some(values(src).into_iter().map(|p| p.text).collect::<Vec<_>>().join(" ")),
        Title::Auto => {
            let all: Vec<&Series> = ch.plots.iter().flat_map(|p| p.series.iter()).collect();
            if all.len() == 1 {
                Some(series_name(all[0], 0))
            } else {
                Some("Chart Title".into())
            }
        }
    }
}
