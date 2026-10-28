//! Lists: numbering.xml definitions, the counters as the original keeps
//! them, and the text of each paragraph's number or bullet.

use crate::props::{int_attr, on_off, ParaProps, RunProps};
use crate::xml::{NodeId, XmlDoc};
use std::collections::HashMap;

#[derive(Clone, Debug, Default)]
pub struct Level {
    pub start: i32,
    pub fmt: String,
    pub text: String,
    pub jc: String,
    pub suff: String,
    pub is_lgl: bool,
    /// None: restart after any higher level; Some(0): never; Some(n): after
    /// level n-1 (1-based as in the file)
    pub restart: Option<i32>,
    pub pstyle: Option<String>,
    pub ppr: ParaProps,
    pub rpr: RunProps,
    /// a picture bullet (lvlPicBulletId) — drawn as a plain bullet
    pub pic_bullet: bool,
}

#[derive(Clone, Debug, Default)]
pub struct Abstract {
    pub id: String,
    pub levels: Vec<Option<Level>>,
    pub num_style_link: Option<String>,
    pub style_link: Option<String>,
}

#[derive(Clone, Debug, Default)]
pub struct Num {
    pub id: i32,
    pub abs: String,
    /// level -> (start override, replacement level)
    pub overrides: HashMap<usize, (Option<i32>, Option<Level>)>,
}

#[derive(Clone, Debug, Default)]
pub struct Numbering {
    pub abstracts: HashMap<String, Abstract>,
    pub nums: HashMap<i32, Num>,
}

fn parse_level(doc: &XmlDoc, n: NodeId) -> Level {
    let mut l = Level { start: 1, fmt: "decimal".into(), jc: "left".into(), suff: "tab".into(), ..Default::default() };
    for c in doc.elements(n) {
        let val = || doc.attr(c, "w:val").unwrap_or("").to_string();
        match doc.name(c) {
            "w:start" => l.start = int_attr(doc, c, "w:val").unwrap_or(1),
            "w:numFmt" => l.fmt = val(),
            "w:lvlText" => l.text = val(),
            "w:lvlJc" => l.jc = val(),
            "w:suff" => l.suff = val(),
            "w:isLgl" => l.is_lgl = on_off(doc, c),
            "w:lvlRestart" => l.restart = int_attr(doc, c, "w:val"),
            "w:pStyle" => l.pstyle = Some(val()),
            "w:pPr" => l.ppr = ParaProps::parse(doc, c),
            "w:rPr" => l.rpr = RunProps::parse(doc, c),
            "w:lvlPicBulletId" => l.pic_bullet = true,
            _ => {}
        }
    }
    // a numFmt inside mc:AlternateContent (Word 2010+ formats)
    if l.fmt.is_empty() {
        l.fmt = "decimal".into();
    }
    l
}

impl Numbering {
    pub fn parse(doc: &XmlDoc) -> Numbering {
        let mut n = Numbering::default();
        let root = doc.root;
        for a in doc.children_named(root, "w:abstractNum") {
            let id = doc.attr(a, "w:abstractNumId").unwrap_or("").to_string();
            let mut abs = Abstract { id: id.clone(), levels: vec![None; 9], ..Default::default() };
            for c in doc.elements(a) {
                match doc.name(c) {
                    "w:lvl" => {
                        let i = int_attr(doc, c, "w:ilvl").unwrap_or(0).clamp(0, 8) as usize;
                        abs.levels[i] = Some(parse_level(doc, c));
                    }
                    "w:numStyleLink" => abs.num_style_link = doc.attr(c, "w:val").map(String::from),
                    "w:styleLink" => abs.style_link = doc.attr(c, "w:val").map(String::from),
                    _ => {}
                }
            }
            n.abstracts.insert(id, abs);
        }
        for m in doc.children_named(root, "w:num") {
            let id = int_attr(doc, m, "w:numId").unwrap_or(0);
            let abs = doc.child(m, "w:abstractNumId").and_then(|c| doc.attr(c, "w:val")).unwrap_or("").to_string();
            let mut num = Num { id, abs, overrides: HashMap::new() };
            for o in doc.children_named(m, "w:lvlOverride") {
                let i = int_attr(doc, o, "w:ilvl").unwrap_or(0).clamp(0, 8) as usize;
                let start = doc.child(o, "w:startOverride").and_then(|s| int_attr(doc, s, "w:val"));
                let lvl = doc.child(o, "w:lvl").map(|l| parse_level(doc, l));
                num.overrides.insert(i, (start, lvl));
            }
            n.nums.insert(id, num);
        }
        n
    }

    /// The abstract definition a num uses, following numStyleLink through
    /// the numbering style (whose numId points at the real definition).
    pub fn abstract_of(&self, num: i32, styles: &crate::styles::StyleSheet) -> Option<&Abstract> {
        let n = self.nums.get(&num)?;
        let mut a = self.abstracts.get(&n.abs)?;
        for _ in 0..4 {
            let Some(link) = &a.num_style_link else { break };
            let st = styles.styles.get(link)?;
            let target = st.ppr.num_id?;
            let tn = self.nums.get(&target)?;
            a = self.abstracts.get(&tn.abs)?;
        }
        Some(a)
    }

    /// The level definition a paragraph uses (overrides applied).
    pub fn level(&self, num: i32, ilvl: usize, styles: &crate::styles::StyleSheet) -> Option<Level> {
        let n = self.nums.get(&num)?;
        if let Some((_, Some(l))) = n.overrides.get(&ilvl) {
            return Some(l.clone());
        }
        self.abstract_of(num, styles)?.levels.get(ilvl)?.clone()
    }
}

// ------------------------------------------------------------- formatting
fn roman(mut n: i32, upper: bool) -> String {
    if n <= 0 {
        return n.to_string();
    }
    let table = [(1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"), (50, "l"), (40, "xl"),
        (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")];
    let mut s = String::new();
    for (v, r) in table {
        while n >= v {
            s.push_str(r);
            n -= v;
        }
    }
    if upper {
        s.to_uppercase()
    } else {
        s
    }
}

fn letters(n: i32, upper: bool) -> String {
    if n <= 0 {
        return n.to_string();
    }
    // the original repeats the letter: Z, AA, BB...
    let k = ((n - 1) / 26 + 1) as usize;
    let c = (b'a' + ((n - 1) % 26) as u8) as char;
    let s: String = std::iter::repeat(c).take(k).collect();
    if upper {
        s.to_uppercase()
    } else {
        s
    }
}

const ONES: [&str; 20] = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"];
const TENS: [&str; 10] = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"];

fn cardinal(n: i32) -> String {
    if n < 0 {
        return n.to_string();
    }
    let n = n as usize;
    if n < 20 {
        return ONES[n].into();
    }
    if n < 100 {
        let t = TENS[n / 10];
        return if n % 10 == 0 { t.into() } else { format!("{}-{}", t, ONES[n % 10]) };
    }
    if n < 1000 {
        let h = format!("{} hundred", ONES[n / 100]);
        return if n % 100 == 0 { h } else { format!("{} {}", h, cardinal((n % 100) as i32)) };
    }
    n.to_string()
}

fn ordinal_word(n: i32) -> String {
    let c = cardinal(n);
    let irregular = [("one", "first"), ("two", "second"), ("three", "third"), ("five", "fifth"), ("eight", "eighth"),
        ("nine", "ninth"), ("twelve", "twelfth")];
    for (a, b) in irregular {
        if c.ends_with(a) {
            return format!("{}{}", &c[..c.len() - a.len()], b);
        }
    }
    if let Some(stripped) = c.strip_suffix('y') {
        return format!("{stripped}ieth");
    }
    format!("{c}th")
}

fn capitalize(s: String) -> String {
    let mut c = s.chars();
    match c.next() {
        Some(f) => f.to_uppercase().chain(c).collect(),
        None => s,
    }
}

pub fn format_number(n: i32, fmt: &str) -> String {
    match fmt {
        "decimal" => n.to_string(),
        "decimalZero" => {
            if (0..10).contains(&n) {
                format!("0{n}")
            } else {
                n.to_string()
            }
        }
        "upperRoman" => roman(n, true),
        "lowerRoman" => roman(n, false),
        "upperLetter" => letters(n, true),
        "lowerLetter" => letters(n, false),
        "ordinal" => {
            let suf = match (n % 100, n % 10) {
                (11..=13, _) => "th",
                (_, 1) => "st",
                (_, 2) => "nd",
                (_, 3) => "rd",
                _ => "th",
            };
            format!("{n}{suf}")
        }
        "cardinalText" => capitalize(cardinal(n)),
        "ordinalText" => capitalize(ordinal_word(n)),
        "none" => String::new(),
        "chicago" => {
            let marks = ['*', '\u{2020}', '\u{2021}', '\u{a7}'];
            let k = (n.max(1) - 1) as usize;
            std::iter::repeat(marks[k % 4]).take(k / 4 + 1).collect()
        }
        "decimalEnclosedCircle" if (1..=20).contains(&n) => char::from_u32(0x2460 + n as u32 - 1).unwrap().to_string(),
        "decimalEnclosedParen" if (1..=20).contains(&n) => char::from_u32(0x2474 + n as u32 - 1).unwrap().to_string(),
        "decimalEnclosedFullstop" if (1..=20).contains(&n) => char::from_u32(0x2488 + n as u32 - 1).unwrap().to_string(),
        "decimalFullWidth" | "decimalFullWidth2" => n
            .to_string()
            .chars()
            .map(|c| char::from_u32(c as u32 - '0' as u32 + 0xFF10).unwrap_or(c))
            .collect(),
        _ => n.to_string(),
    }
}

/// Bullet characters in symbol fonts (private-use codes) as the Unicode
/// characters they show.
pub fn bullet_char(c: char, font: &str) -> char {
    let f = font.to_lowercase();
    let code = c as u32;
    let low = if (0xF000..=0xF0FF).contains(&code) { code - 0xF000 } else { code };
    if f.contains("symbol") {
        return match low {
            0xB7 => '\u{2022}',
            0xA8 => '\u{2666}',
            0xD8 => '\u{2192}',
            0x2D => '\u{2212}',
            0x6F => 'o',
            _ if low < 0x80 => char::from_u32(low).unwrap_or(c),
            _ => '\u{2022}',
        };
    }
    if f.contains("wingdings") {
        return match low {
            0xA7 => '\u{25AA}',
            0xA8 => '\u{25FB}',
            0x6E => '\u{25A0}',
            0x71 => '\u{2751}',
            0x76 => '\u{2756}',
            0xD8 => '\u{27A2}',
            0xFC => '\u{2714}',
            0xFB => '\u{2718}',
            0x9F => '\u{2022}',
            0x77 => '\u{2B25}',
            0xA1 => '\u{25CB}',
            0x6C => '\u{25CF}',
            _ => '\u{2022}',
        };
    }
    if (0xF000..=0xF0FF).contains(&code) {
        return char::from_u32(low).unwrap_or('\u{2022}');
    }
    c
}

/// A paragraph's list label.
#[derive(Clone, Debug, PartialEq)]
pub struct Label {
    pub text: String,
    pub rpr: RunProps,
    pub suff: String,
    pub jc: String,
    pub bullet: bool,
}

/// Counts through the paragraphs in document order.
#[derive(Default)]
pub struct Counter {
    /// abstract id -> counters per level
    counts: HashMap<String, [i32; 9]>,
    /// abstract id -> levels used so far (for "restart after")
    seen: HashMap<String, [bool; 9]>,
    /// nums whose start overrides were applied
    started: HashMap<i32, [bool; 9]>,
}

impl Counter {
    /// The label of a numbered paragraph (num, level), counting it.
    pub fn next(&mut self, numbering: &Numbering, styles: &crate::styles::StyleSheet, num: i32, ilvl: usize,
                mark: &RunProps) -> Option<Label> {
        let lvl = numbering.level(num, ilvl, styles)?;
        let abs = numbering.abstract_of(num, styles)?;
        let key = abs.id.clone();
        let levels: Vec<Option<Level>> = (0..9).map(|i| numbering.level(num, i, styles)).collect();
        let counts = self.counts.entry(key.clone()).or_insert_with(|| {
            let mut c = [0; 9];
            for (i, l) in levels.iter().enumerate() {
                c[i] = l.as_ref().map(|l| l.start - 1).unwrap_or(0);
            }
            c
        });
        let seen = self.seen.entry(key.clone()).or_insert([false; 9]);
        // a num's start override restarts the level the first time it's used
        let started = self.started.entry(num).or_insert([false; 9]);
        let n = numbering.nums.get(&num);
        if !started[ilvl] {
            started[ilvl] = true;
            if let Some((Some(s), _)) = n.and_then(|n| n.overrides.get(&ilvl)) {
                counts[ilvl] = s - 1;
                seen[ilvl] = false;
            }
        }
        counts[ilvl] += 1;
        if !seen[ilvl] {
            seen[ilvl] = true;
        }
        // deeper levels restart
        for d in ilvl + 1..9 {
            let restart = levels[d].as_ref().and_then(|l| l.restart);
            let reset = match restart {
                Some(0) => false,
                Some(r) => (ilvl as i32) < r,
                None => true,
            };
            if reset {
                counts[d] = levels[d].as_ref().map(|l| l.start - 1).unwrap_or(0);
                seen[d] = false;
            }
        }
        let counts = *counts;
        let bullet = lvl.fmt == "bullet";
        let mut rpr = mark.clone();
        // the number keeps none of the mark's underline etc. that the
        // level turns off; the level's own formatting goes on top
        rpr.apply(&lvl.rpr);
        if lvl.rpr.font_ascii.is_some() {
            rpr.theme_ascii = None;
            rpr.theme_hansi = None;
        }
        let text = if bullet {
            let font = lvl.rpr.font_ascii.clone().or(lvl.rpr.font_hansi.clone()).unwrap_or_default();
            let t: String = lvl.text.chars().map(|c| bullet_char(c, &font)).collect();
            if lvl.pic_bullet && t.is_empty() {
                "\u{2022}".into()
            } else {
                t
            }
        } else {
            let mut out = String::new();
            let mut chars = lvl.text.chars().peekable();
            while let Some(c) = chars.next() {
                if c == '%' {
                    if let Some(d) = chars.peek().and_then(|d| d.to_digit(10)) {
                        chars.next();
                        let i = (d as usize).saturating_sub(1).min(8);
                        let fmt = if lvl.is_lgl && i < ilvl {
                            "decimal".to_string()
                        } else {
                            levels[i].as_ref().map(|l| l.fmt.clone()).unwrap_or_else(|| "decimal".into())
                        };
                        let fmt = if lvl.is_lgl { "decimal".to_string() } else { fmt };
                        out.push_str(&format_number(counts[i].max(0), &fmt));
                        continue;
                    }
                }
                out.push(c);
            }
            out
        };
        if bullet {
            // bullets drop the symbol font: the character is mapped already
            rpr.font_ascii = None;
            rpr.font_hansi = None;
            rpr.font_cs = None;
            rpr.font_east = None;
            let base = mark.font_ascii.clone().or(mark.font_hansi.clone());
            rpr.font_ascii = base.clone();
            rpr.font_hansi = base;
            rpr.theme_ascii = mark.theme_ascii.clone();
            rpr.theme_hansi = mark.theme_hansi.clone();
            if lvl.text.chars().all(|c| c == 'o') {
                rpr.font_ascii = Some("Courier New".into());
                rpr.font_hansi = Some("Courier New".into());
                rpr.theme_ascii = None;
                rpr.theme_hansi = None;
            }
        }
        Some(Label { text, rpr, suff: lvl.suff.clone(), jc: lvl.jc.clone(), bullet })
    }
}

/// Word's default bullet list (as its Bullets button makes it).
pub fn default_bullet_abstract(id: &str) -> String {
    let bullets = [("\u{F0B7}", "Symbol"), ("o", "Courier New"), ("\u{F0A7}", "Wingdings")];
    let mut s = format!(
        "<w:abstractNum w:abstractNumId=\"{id}\"><w:multiLevelType w:val=\"hybridMultilevel\"/>"
    );
    for i in 0..9 {
        let (ch, font) = bullets[i % 3];
        s.push_str(&format!(
            "<w:lvl w:ilvl=\"{i}\"><w:start w:val=\"1\"/><w:numFmt w:val=\"bullet\"/><w:lvlText w:val=\"{ch}\"/>\
             <w:lvlJc w:val=\"left\"/><w:pPr><w:ind w:left=\"{}\" w:hanging=\"360\"/></w:pPr>\
             <w:rPr><w:rFonts w:ascii=\"{font}\" w:hAnsi=\"{font}\"{} w:hint=\"default\"/></w:rPr></w:lvl>",
            720 * (i + 1),
            if font == "Courier New" { " w:cs=\"Courier New\"" } else { "" }
        ));
    }
    s.push_str("</w:abstractNum>");
    s
}

/// Word's default numbered list.
pub fn default_number_abstract(id: &str) -> String {
    let fmts = ["decimal", "lowerLetter", "lowerRoman"];
    let mut s = format!(
        "<w:abstractNum w:abstractNumId=\"{id}\"><w:multiLevelType w:val=\"hybridMultilevel\"/>"
    );
    for i in 0..9 {
        let fmt = fmts[i % 3];
        let jc = if fmt == "lowerRoman" { "right" } else { "left" };
        let hang = if fmt == "lowerRoman" { 180 } else { 360 };
        s.push_str(&format!(
            "<w:lvl w:ilvl=\"{i}\"><w:start w:val=\"1\"/><w:numFmt w:val=\"{fmt}\"/><w:lvlText w:val=\"%{}.\"/>\
             <w:lvlJc w:val=\"{jc}\"/><w:pPr><w:ind w:left=\"{}\" w:hanging=\"{hang}\"/></w:pPr></w:lvl>",
            i + 1,
            720 * (i + 1)
        ));
    }
    s.push_str("</w:abstractNum>");
    s
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn formats() {
        assert_eq!(format_number(4, "upperRoman"), "IV");
        assert_eq!(format_number(28, "upperLetter"), "BB");
        assert_eq!(format_number(3, "ordinal"), "3rd");
        assert_eq!(format_number(12, "ordinal"), "12th");
        assert_eq!(format_number(21, "cardinalText"), "Twenty-one");
        assert_eq!(format_number(3, "ordinalText"), "Third");
        assert_eq!(format_number(20, "ordinalText"), "Twentieth");
        assert_eq!(format_number(7, "decimalZero"), "07");
    }
}
