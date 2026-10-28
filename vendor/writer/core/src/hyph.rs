//! Automatic hyphenation: Liang's patterns (the hyphen library's .dic
//! files, as LibreOffice uses), found where the system keeps them.

use std::collections::HashMap;
use std::sync::OnceLock;

pub struct Patterns {
    pats: HashMap<String, Vec<u8>>,
    left: usize,
    right: usize,
    max_len: usize,
}

const DIRS: &[&str] = &["/usr/share/folio-writer/hyphen", "/usr/share/hyphen", "/usr/share/myspell/dicts"];

fn load(lang: &str) -> Option<Patterns> {
    let name = format!("hyph_{lang}.dic");
    let text = DIRS.iter().find_map(|d| std::fs::read(format!("{d}/{name}")).ok())?;
    let text = String::from_utf8_lossy(&text);
    let mut p = Patterns { pats: HashMap::new(), left: 2, right: 3, max_len: 0 };
    for (i, line) in text.lines().enumerate() {
        let line = line.trim();
        if i == 0 || line.is_empty() || line.starts_with('%') || line.contains('/') {
            continue;
        }
        if let Some(v) = line.strip_prefix("LEFTHYPHENMIN") {
            p.left = v.trim().parse().unwrap_or(2);
            continue;
        }
        if let Some(v) = line.strip_prefix("RIGHTHYPHENMIN") {
            p.right = v.trim().parse().unwrap_or(3);
            continue;
        }
        if line.chars().next().is_some_and(|c| c.is_ascii_uppercase()) {
            continue;
        }
        let mut letters = String::new();
        let mut digits = vec![0u8];
        for c in line.chars() {
            if let Some(d) = c.to_digit(10) {
                *digits.last_mut().unwrap() = d as u8;
            } else {
                letters.push(c);
                digits.push(0);
            }
        }
        p.max_len = p.max_len.max(letters.chars().count());
        p.pats.insert(letters, digits);
    }
    Some(p)
}

static EN: OnceLock<Option<Patterns>> = OnceLock::new();

/// The patterns for a language tag ("en-US"); English when there are none
/// for it.
pub fn patterns(_lang: &str) -> Option<&'static Patterns> {
    EN.get_or_init(|| load("en_US").or_else(|| load("en"))).as_ref()
}

impl Patterns {
    /// Where a word may break: after k characters, for each k returned.
    pub fn points(&self, word: &str) -> Vec<usize> {
        let w: Vec<char> = word.chars().flat_map(|c| c.to_lowercase()).collect();
        let n = w.len();
        if n < self.left + self.right {
            return Vec::new();
        }
        let mut dotted: Vec<char> = Vec::with_capacity(n + 2);
        dotted.push('.');
        dotted.extend(w.iter());
        dotted.push('.');
        let m = dotted.len();
        let mut score = vec![0u8; m + 1];
        let mut buf = String::new();
        for i in 0..m {
            buf.clear();
            for j in i..m.min(i + self.max_len) {
                buf.push(dotted[j]);
                if let Some(d) = self.pats.get(&buf) {
                    for (k, v) in d.iter().enumerate() {
                        let at = i + k;
                        if at < score.len() && *v > score[at] {
                            score[at] = *v;
                        }
                    }
                }
            }
        }
        // score[i] is between dotted[i-1] and dotted[i]; a break after k
        // letters of the word sits at dotted index k + 1
        (self.left..=n.saturating_sub(self.right)).filter(|&k| score[k + 1] % 2 == 1).collect()
    }
}

#[cfg(test)]
mod tests {
    #[test]
    fn english() {
        let Some(p) = super::patterns("en-US") else { return };
        assert_eq!(p.points("hyphenation"), vec![2, 6]);
        assert!(p.points("computer").contains(&3));
    }
}
