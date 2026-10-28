//! Windows metafiles (EMF and WMF), the pictures older documents, charts
//! pasted from spreadsheets and equation objects carry: their GDI records
//! played back with cairo.

use std::f64::consts::PI;

fn u16le(b: &[u8], o: usize) -> u16 {
    b.get(o..o + 2).map(|s| u16::from_le_bytes([s[0], s[1]])).unwrap_or(0)
}
fn i16le(b: &[u8], o: usize) -> i16 {
    u16le(b, o) as i16
}
fn u32le(b: &[u8], o: usize) -> u32 {
    b.get(o..o + 4).map(|s| u32::from_le_bytes([s[0], s[1], s[2], s[3]])).unwrap_or(0)
}
fn i32le(b: &[u8], o: usize) -> i32 {
    u32le(b, o) as i32
}
fn f32le(b: &[u8], o: usize) -> f64 {
    f32::from_bits(u32le(b, o)) as f64
}

/// Is this a metafile we can draw?
pub fn is_metafile(b: &[u8]) -> bool {
    is_emf(b) || is_wmf(b)
}

fn is_emf(b: &[u8]) -> bool {
    b.len() >= 88 && u32le(b, 0) == 1 && &b[40..44] == b" EMF"
}

fn is_wmf(b: &[u8]) -> bool {
    b.len() >= 18 && (u32le(b, 0) == 0x9AC6CDD7 || ((u16le(b, 0) == 1 || u16le(b, 0) == 2) && u16le(b, 2) == 9))
}

/// Draw a metafile filling the box (0, 0, w, h) of `cr`.
pub fn draw(b: &[u8], cr: &cairo::Context, w: f64, h: f64) -> bool {
    if is_emf(b) {
        cr.save().ok();
        let ok = Player::new(cr, w, h).emf(b);
        cr.restore().ok();
        ok
    } else if is_wmf(b) {
        cr.save().ok();
        let ok = Player::new(cr, w, h).wmf(b);
        cr.restore().ok();
        ok
    } else {
        false
    }
}

/// The size a metafile asks for (points), if it says.
pub fn natural_size(b: &[u8]) -> Option<(f64, f64)> {
    if is_emf(b) {
        // rclFrame in 0.01 mm
        let (l, t, r, bt) = (i32le(b, 24), i32le(b, 28), i32le(b, 32), i32le(b, 36));
        let k = 72.0 / 2540.0;
        return Some(((r - l) as f64 * k, (bt - t) as f64 * k));
    }
    if is_wmf(b) && u32le(b, 0) == 0x9AC6CDD7 {
        let (l, t, r, bt) = (i16le(b, 6), i16le(b, 8), i16le(b, 10), i16le(b, 12));
        let inch = u16le(b, 14).max(1) as f64;
        return Some(((r - l) as f64 / inch * 72.0, (bt - t) as f64 / inch * 72.0));
    }
    None
}

#[derive(Clone, Copy)]
struct Pen {
    style: u32,
    width: f64,
    color: u32,
}

#[derive(Clone, Copy)]
struct Brush {
    /// 0 solid, 1 null, 2 hatched, 3 pattern
    style: u32,
    color: u32,
}

#[derive(Clone)]
struct Font {
    height: f64,
    weight: i32,
    italic: bool,
    underline: bool,
    strike: bool,
    escapement: f64,
    face: String,
}

#[derive(Clone)]
enum Obj {
    Pen(Pen),
    Brush(Brush),
    Font(Font),
    Other,
}

#[derive(Clone)]
struct Dc {
    pen: Pen,
    brush: Brush,
    font: Font,
    text_color: u32,
    bk_color: u32,
    bk_mode: u32,
    text_align: u32,
    fill_mode: u32,
    map_mode: u32,
    win_org: (f64, f64),
    win_ext: (f64, f64),
    vp_org: (f64, f64),
    vp_ext: (f64, f64),
    /// world transform: x' = a x + c y + e, y' = b x + d y + f
    world: [f64; 6],
    cur: (f64, f64),
}

impl Default for Dc {
    fn default() -> Self {
        Dc {
            pen: Pen { style: 0, width: 0.0, color: 0 },
            brush: Brush { style: 0, color: 0xFFFFFF },
            font: Font { height: 12.0, weight: 400, italic: false, underline: false, strike: false, escapement: 0.0,
                         face: "Arial".into() },
            text_color: 0,
            bk_color: 0xFFFFFF,
            bk_mode: 2,
            text_align: 0,
            fill_mode: 1,
            map_mode: 1,
            win_org: (0.0, 0.0),
            win_ext: (1.0, 1.0),
            vp_org: (0.0, 0.0),
            vp_ext: (1.0, 1.0),
            world: [1.0, 0.0, 0.0, 1.0, 0.0, 0.0],
            cur: (0.0, 0.0),
        }
    }
}

struct Player<'a> {
    cr: &'a cairo::Context,
    w: f64,
    h: f64,
    dc: Dc,
    stack: Vec<Dc>,
    objs: Vec<Option<Obj>>,
    /// device units -> output: the source rectangle (device units)
    src: (f64, f64, f64, f64),
    /// device pixels per millimetre (for the metric mapping modes)
    dev_per_mm: (f64, f64),
    in_path: bool,
    path: Option<cairo::Path>,
    /// WMF: whether the window was set (else the placeable box is used)
    wmf: bool,
}

/// GDI COLORREF (0x00bbggrr) to 0xrrggbb.
fn colorref(v: u32) -> u32 {
    ((v & 0xFF) << 16) | (v & 0xFF00) | ((v >> 16) & 0xFF)
}

fn set_rgb(cr: &cairo::Context, c: u32) {
    cr.set_source_rgb(((c >> 16) & 255) as f64 / 255.0, ((c >> 8) & 255) as f64 / 255.0, (c & 255) as f64 / 255.0);
}

impl<'a> Player<'a> {
    fn new(cr: &'a cairo::Context, w: f64, h: f64) -> Player<'a> {
        Player { cr, w, h, dc: Dc::default(), stack: Vec::new(), objs: Vec::new(), src: (0.0, 0.0, 1.0, 1.0),
                 dev_per_mm: (3.78, 3.78), in_path: false, path: None, wmf: false }
    }

    // ------------------------------------------------------------ mapping
    /// Logical -> output (the picture box) as a cairo matrix.
    fn matrix(&self) -> cairo::Matrix {
        let d = &self.dc;
        // page space -> device
        let (sx, sy) = match d.map_mode {
            1 => (1.0, 1.0),                                          // MM_TEXT
            2 => (self.dev_per_mm.0 * 0.1, -self.dev_per_mm.1 * 0.1),    // LOMETRIC
            3 => (self.dev_per_mm.0 * 0.01, -self.dev_per_mm.1 * 0.01),  // HIMETRIC
            4 => (self.dev_per_mm.0 * 0.254, -self.dev_per_mm.1 * 0.254), // LOENGLISH
            5 => (self.dev_per_mm.0 * 0.0254, -self.dev_per_mm.1 * 0.0254),
            6 => (self.dev_per_mm.0 * 25.4 / 1440.0, -self.dev_per_mm.1 * 25.4 / 1440.0),
            7 => {
                // isotropic: same scale both ways
                let fx = d.vp_ext.0 / nz(d.win_ext.0);
                let fy = d.vp_ext.1 / nz(d.win_ext.1);
                let m = fx.abs().min(fy.abs());
                (m * fx.signum(), m * fy.signum())
            }
            _ => (d.vp_ext.0 / nz(d.win_ext.0), d.vp_ext.1 / nz(d.win_ext.1)),
        };
        let page_to_dev = cairo::Matrix::new(sx, 0.0, 0.0, sy, d.vp_org.0 - d.win_org.0 * sx, d.vp_org.1 - d.win_org.1 * sy);
        let wm = d.world;
        let world = cairo::Matrix::new(wm[0], wm[1], wm[2], wm[3], wm[4], wm[5]);
        let (x0, y0, sw, sh) = self.src;
        let out = cairo::Matrix::new(self.w / nz(sw), 0.0, 0.0, self.h / nz(sh), -x0 * self.w / nz(sw),
                                     -y0 * self.h / nz(sh));
        // world, then page->device, then device->output
        cairo::Matrix::multiply(&cairo::Matrix::multiply(&world, &page_to_dev), &out)
    }

    fn dev_to_out(&self) -> cairo::Matrix {
        let (x0, y0, sw, sh) = self.src;
        cairo::Matrix::new(self.w / nz(sw), 0.0, 0.0, self.h / nz(sh), -x0 * self.w / nz(sw), -y0 * self.h / nz(sh))
    }

    /// Output units per logical unit (for pen widths and font sizes).
    fn scale(&self) -> (f64, f64) {
        let m = self.matrix();
        ((m.xx() * m.xx() + m.yx() * m.yx()).sqrt(), (m.xy() * m.xy() + m.yy() * m.yy()).sqrt())
    }

    fn with_logical<F: FnOnce(&cairo::Context)>(&self, f: F) {
        let cr = self.cr;
        cr.save().ok();
        cr.transform(self.matrix());
        f(cr);
        cr.restore().ok();
    }

    // ------------------------------------------------------------ painting
    fn stroke_style(&self) -> bool {
        let p = self.dc.pen;
        if p.style & 0xF == 5 {
            return false;
        }
        let cr = self.cr;
        set_rgb(cr, p.color);
        let (sx, sy) = self.scale();
        let lw = if p.width <= 1.0 { 0.75_f64.min(self.w.max(self.h) / 200.0).max(0.25) } else { p.width * (sx + sy) / 2.0 };
        cr.set_line_width(lw.max(0.25));
        let d = lw.max(0.5);
        match p.style & 0xF {
            1 => cr.set_dash(&[d * 3.0, d * 2.0], 0.0),
            2 => cr.set_dash(&[d, d * 2.0], 0.0),
            3 => cr.set_dash(&[d * 3.0, d * 2.0, d, d * 2.0], 0.0),
            4 => cr.set_dash(&[d * 3.0, d, d, d, d, d], 0.0),
            _ => cr.set_dash(&[], 0.0),
        }
        cr.set_line_cap(match p.style & 0xF00 {
            0x100 => cairo::LineCap::Square,
            0x200 => cairo::LineCap::Butt,
            _ => cairo::LineCap::Round,
        });
        cr.set_line_join(match p.style & 0xF000 {
            0x1000 => cairo::LineJoin::Bevel,
            0x2000 => cairo::LineJoin::Miter,
            _ => cairo::LineJoin::Round,
        });
        true
    }

    fn fill_rule(&self) {
        self.cr.set_fill_rule(if self.dc.fill_mode == 2 { cairo::FillRule::Winding } else { cairo::FillRule::EvenOdd });
    }

    /// Fill (with the brush) and stroke (with the pen) the current path.
    fn paint(&mut self, fill: bool, stroke: bool) {
        if self.in_path {
            return;
        }
        let cr = self.cr;
        if fill && self.dc.brush.style != 1 {
            set_rgb(cr, self.dc.brush.color);
            self.fill_rule();
            cr.fill_preserve().ok();
        }
        if stroke && self.stroke_style() {
            cr.stroke_preserve().ok();
        }
        cr.new_path();
    }

    fn poly(&mut self, pts: &[(f64, f64)], close: bool, fill: bool) {
        if pts.is_empty() {
            return;
        }
        if !self.in_path {
            self.cr.new_path();
        }
        self.with_logical(|cr| {
            cr.move_to(pts[0].0, pts[0].1);
            for p in &pts[1..] {
                cr.line_to(p.0, p.1);
            }
            if close {
                cr.close_path();
            }
        });
        self.paint(fill, true);
    }

    fn polypoly(&mut self, polys: &[Vec<(f64, f64)>], close: bool) {
        if !self.in_path {
            self.cr.new_path();
        }
        self.with_logical(|cr| {
            for pts in polys {
                if pts.is_empty() {
                    continue;
                }
                cr.move_to(pts[0].0, pts[0].1);
                for p in &pts[1..] {
                    cr.line_to(p.0, p.1);
                }
                if close {
                    cr.close_path();
                }
            }
        });
        self.paint(close, true);
    }

    fn bezier(&mut self, pts: &[(f64, f64)], from_current: bool) {
        if pts.is_empty() {
            return;
        }
        if !self.in_path {
            self.cr.new_path();
        }
        let cur = self.dc.cur;
        let mut last = cur;
        self.with_logical(|cr| {
            let rest = if from_current {
                cr.move_to(cur.0, cur.1);
                pts
            } else {
                cr.move_to(pts[0].0, pts[0].1);
                &pts[1..]
            };
            for c in rest.chunks(3) {
                if c.len() == 3 {
                    cr.curve_to(c[0].0, c[0].1, c[1].0, c[1].1, c[2].0, c[2].1);
                    last = c[2];
                }
            }
        });
        if from_current {
            self.dc.cur = last;
        }
        self.paint(false, true);
    }

    fn rect(&mut self, l: f64, t: f64, r: f64, b: f64) {
        if !self.in_path {
            self.cr.new_path();
        }
        self.with_logical(|cr| cr.rectangle(l, t, r - l, b - t));
        self.paint(true, true);
    }

    fn ellipse_path(cr: &cairo::Context, l: f64, t: f64, r: f64, b: f64) {
        let (cx, cy, rx, ry) = ((l + r) / 2.0, (t + b) / 2.0, ((r - l) / 2.0).abs(), ((b - t) / 2.0).abs());
        if rx <= 0.0 || ry <= 0.0 {
            return;
        }
        cr.save().ok();
        cr.translate(cx, cy);
        cr.scale(rx, ry);
        cr.new_sub_path();
        cr.arc(0.0, 0.0, 1.0, 0.0, 2.0 * PI);
        cr.close_path();
        cr.restore().ok();
    }

    fn ellipse(&mut self, l: f64, t: f64, r: f64, b: f64) {
        if !self.in_path {
            self.cr.new_path();
        }
        self.with_logical(|cr| Self::ellipse_path(cr, l, t, r, b));
        self.paint(true, true);
    }

    fn round_rect(&mut self, l: f64, t: f64, r: f64, b: f64, ew: f64, eh: f64) {
        if !self.in_path {
            self.cr.new_path();
        }
        let (rx, ry) = ((ew / 2.0).abs().min(((r - l) / 2.0).abs()), (eh / 2.0).abs().min(((b - t) / 2.0).abs()));
        let (l, r) = (l.min(r), l.max(r));
        let (t, b) = (t.min(b), t.max(b));
        self.with_logical(|cr| {
            if rx <= 0.0 || ry <= 0.0 {
                cr.rectangle(l, t, r - l, b - t);
                return;
            }
            let corner = |cr: &cairo::Context, cx: f64, cy: f64, a0: f64| {
                cr.save().ok();
                cr.translate(cx, cy);
                cr.scale(rx, ry);
                cr.arc(0.0, 0.0, 1.0, a0, a0 + PI / 2.0);
                cr.restore().ok();
            };
            cr.new_sub_path();
            corner(cr, r - rx, t + ry, -PI / 2.0);
            corner(cr, r - rx, b - ry, 0.0);
            corner(cr, l + rx, b - ry, PI / 2.0);
            corner(cr, l + rx, t + ry, PI);
            cr.close_path();
        });
        self.paint(true, true);
    }

    /// Arc / chord / pie (kind 0, 1, 2) in the box, from the start radial to
    /// the end radial, counter-clockwise (GDI's default).
    fn arc(&mut self, b: [f64; 4], s: (f64, f64), e: (f64, f64), kind: u8) {
        let [l, t, r, bt] = b;
        let (cx, cy, rx, ry) = ((l + r) / 2.0, (t + bt) / 2.0, ((r - l) / 2.0).abs(), ((bt - t) / 2.0).abs());
        if rx <= 0.0 || ry <= 0.0 {
            return;
        }
        let a0 = ((s.1 - cy) / ry).atan2((s.0 - cx) / rx);
        let a1 = ((e.1 - cy) / ry).atan2((e.0 - cx) / rx);
        if !self.in_path {
            self.cr.new_path();
        }
        self.with_logical(|cr| {
            cr.save().ok();
            cr.translate(cx, cy);
            cr.scale(rx, ry);
            if kind == 2 {
                cr.move_to(0.0, 0.0);
            } else {
                cr.new_sub_path();
            }
            // y grows downwards: counter-clockwise on the page is negative
            cr.arc_negative(0.0, 0.0, 1.0, a0, if (a1 - a0).abs() < 1e-9 { a0 - 2.0 * PI } else { a1 });
            if kind > 0 {
                cr.close_path();
            }
            cr.restore().ok();
        });
        self.paint(kind > 0, true);
    }

    // ------------------------------------------------------------ text
    fn text(&mut self, x: f64, y: f64, s: &str, dx: &[f64], opts: u32, clip: Option<[f64; 4]>) {
        if s.is_empty() {
            return;
        }
        let symbol = self.dc.font.face.eq_ignore_ascii_case("symbol");
        let mapped: String;
        let s = if symbol {
            mapped = s.chars().map(|c| symbol_char(c as u32)).collect();
            mapped.as_str()
        } else {
            s
        };
        let cr = self.cr;
        let m = self.matrix();
        let (px, py) = m.transform_point(x, y);
        let f = self.dc.font.clone();
        let (_, sy) = self.scale();
        let mut size = f.height.abs() * sy;
        if f.height > 0.0 {
            // a positive height is the cell: the em is a little less
            size *= 0.85;
        }
        if size <= 0.0 {
            size = 12.0 * sy;
        }
        cr.save().ok();
        if opts & 0x4 != 0 {
            // ETO_CLIPPED
            if let Some(c) = clip {
                cr.save().ok();
                cr.transform(m);
                cr.rectangle(c[0], c[1], c[2] - c[0], c[3] - c[1]);
                cr.restore().ok();
                cr.clip();
            }
        }
        let face = map_face(&f.face);
        cr.select_font_face(&face, if f.italic { cairo::FontSlant::Italic } else { cairo::FontSlant::Normal },
                            if f.weight >= 600 { cairo::FontWeight::Bold } else { cairo::FontWeight::Normal });
        cr.set_font_size(size);
        cr.translate(px, py);
        // the y axis may run upwards in the metafile: text stays upright
        let angle = -f.escapement / 10.0 * PI / 180.0 * if m.yy() < 0.0 { -1.0 } else { 1.0 };
        if angle != 0.0 {
            cr.rotate(angle);
        }
        let fe = cr.font_extents().ok();
        let (asc, desc) = fe.map(|e| (e.ascent(), e.descent())).unwrap_or((size * 0.8, size * 0.2));
        // advances: dx (logical) when given, else the font's own
        let chars: Vec<char> = s.chars().collect();
        let mut xs = Vec::with_capacity(chars.len());
        let mut total = 0.0;
        let (sx, _) = self.scale();
        for (i, ch) in chars.iter().enumerate() {
            xs.push(total);
            let adv = if let Some(d) = dx.get(i) {
                d * sx * m.xx().signum().max(-1.0).abs()
            } else {
                cr.text_extents(&ch.to_string()).map(|e| e.x_advance()).unwrap_or(size * 0.5)
            };
            total += adv;
        }
        let ta = self.dc.text_align;
        let ox = match ta & 6 {
            6 => -total / 2.0,
            2 => -total,
            _ => 0.0,
        };
        let oy = match ta & 24 {
            24 => 0.0,     // baseline
            8 => -desc,    // bottom
            _ => asc,      // top
        };
        if self.dc.bk_mode == 2 || opts & 0x2 != 0 {
            // opaque background
            set_rgb(cr, self.dc.bk_color);
            cr.rectangle(ox, oy - asc, total, asc + desc);
            cr.fill().ok();
        }
        set_rgb(cr, self.dc.text_color);
        for (i, ch) in chars.iter().enumerate() {
            cr.move_to(ox + xs[i], oy);
            cr.show_text(&ch.to_string()).ok();
        }
        if f.underline || f.strike {
            cr.set_line_width((size / 14.0).max(0.4));
            if f.underline {
                cr.move_to(ox, oy + size * 0.12);
                cr.line_to(ox + total, oy + size * 0.12);
            }
            if f.strike {
                cr.move_to(ox, oy - size * 0.3);
                cr.line_to(ox + total, oy - size * 0.3);
            }
            cr.stroke().ok();
        }
        cr.restore().ok();
        if ta & 1 != 0 {
            // TA_UPDATECP
            let inv = {
                let mut i = m;
                i.invert();
                i
            };
            let (ux, _) = inv.transform_distance(total, 0.0);
            self.dc.cur.0 += ux;
        }
    }

    // ------------------------------------------------------------ bitmaps
    /// Draw a DIB (header at `bmi`, bits at `bits`) into the logical
    /// rectangle, the source rectangle of the bitmap stretched to it.
    #[allow(clippy::too_many_arguments)]
    fn dib(&mut self, data: &[u8], bmi: usize, bits: usize, dest: [f64; 4], src: [f64; 4]) {
        let Some(surf) = dib_surface(data, bmi, bits) else { return };
        let (iw, ih) = (surf.width() as f64, surf.height() as f64);
        let [dx, dy, dw, dh] = dest;
        let [sx, sy, sw, sh] = src;
        let (sw, sh) = (if sw <= 0.0 { iw } else { sw }, if sh <= 0.0 { ih } else { sh });
        let cr = self.cr;
        cr.save().ok();
        cr.transform(self.matrix());
        cr.rectangle(dx.min(dx + dw), dy.min(dy + dh), dw.abs(), dh.abs());
        cr.clip();
        cr.translate(dx, dy);
        cr.scale(dw / sw, dh / sh);
        cr.set_source_surface(&surf, -sx, -sy).ok();
        cr.source().set_filter(cairo::Filter::Good);
        cr.paint().ok();
        cr.restore().ok();
    }

    // ------------------------------------------------------------ objects
    fn put_obj(&mut self, i: usize, o: Obj) {
        if self.objs.len() <= i {
            self.objs.resize(i + 1, None);
        }
        self.objs[i] = Some(o);
    }

    fn select(&mut self, o: &Obj) {
        match o {
            Obj::Pen(p) => self.dc.pen = *p,
            Obj::Brush(b) => self.dc.brush = *b,
            Obj::Font(f) => self.dc.font = f.clone(),
            Obj::Other => {}
        }
    }

    fn select_stock(&mut self, i: u32) {
        let o = match i & 0x7FFF_FFFF {
            0 => Obj::Brush(Brush { style: 0, color: 0xFFFFFF }),
            1 => Obj::Brush(Brush { style: 0, color: 0xC0C0C0 }),
            2 => Obj::Brush(Brush { style: 0, color: 0x808080 }),
            3 => Obj::Brush(Brush { style: 0, color: 0x404040 }),
            4 => Obj::Brush(Brush { style: 0, color: 0 }),
            5 => Obj::Brush(Brush { style: 1, color: 0 }),
            6 => Obj::Pen(Pen { style: 0, width: 0.0, color: 0xFFFFFF }),
            7 => Obj::Pen(Pen { style: 0, width: 0.0, color: 0 }),
            8 => Obj::Pen(Pen { style: 5, width: 0.0, color: 0 }),
            18 => Obj::Brush(Brush { style: 0, color: 0xFFFFFF }),
            19 => Obj::Pen(Pen { style: 0, width: 0.0, color: 0 }),
            10..=17 => Obj::Font(Font { height: 12.0, weight: 400, italic: false, underline: false, strike: false,
                                        escapement: 0.0, face: "Arial".into() }),
            _ => Obj::Other,
        };
        self.select(&o);
    }

    fn save_dc(&mut self) {
        self.stack.push(self.dc.clone());
        self.cr.save().ok();
    }

    fn restore_dc(&mut self, n: i32) {
        let k = if n < 0 { (-n) as usize } else { self.stack.len().saturating_sub(n as usize - 1).max(1).min(self.stack.len()) };
        for _ in 0..k {
            if let Some(d) = self.stack.pop() {
                self.dc = d;
                self.cr.restore().ok();
            }
        }
    }

    fn reset_clip(&mut self) {
        let cr = self.cr;
        // back to the picture's own box (and whatever clip it had)
        cr.reset_clip();
        cr.rectangle(0.0, 0.0, self.w, self.h);
        cr.clip();
    }

    // ------------------------------------------------------------ EMF
    fn emf(&mut self, b: &[u8]) -> bool {
        // header: bounds (device), frame (0.01 mm), device size in pixels and mm
        let frame = [i32le(b, 24) as f64, i32le(b, 28) as f64, i32le(b, 32) as f64, i32le(b, 36) as f64];
        let dev = (i32le(b, 72) as f64, i32le(b, 76) as f64);
        let mm = (i32le(b, 80) as f64, i32le(b, 84) as f64);
        if mm.0 > 0.0 && mm.1 > 0.0 && dev.0 > 0.0 && dev.1 > 0.0 {
            self.dev_per_mm = (dev.0 / mm.0, dev.1 / mm.1);
        }
        let k = (self.dev_per_mm.0 / 100.0, self.dev_per_mm.1 / 100.0);
        let fw = (frame[2] - frame[0]) * k.0;
        let fh = (frame[3] - frame[1]) * k.1;
        if fw > 0.0 && fh > 0.0 {
            self.src = (frame[0] * k.0, frame[1] * k.1, fw, fh);
        } else {
            let bd = [i32le(b, 8) as f64, i32le(b, 12) as f64, i32le(b, 16) as f64, i32le(b, 20) as f64];
            self.src = (bd[0], bd[1], (bd[2] - bd[0] + 1.0).max(1.0), (bd[3] - bd[1] + 1.0).max(1.0));
        }
        let cr = self.cr;
        cr.rectangle(0.0, 0.0, self.w, self.h);
        cr.clip();
        let mut o = 0usize;
        let mut count = 0;
        while o + 8 <= b.len() {
            let kind = u32le(b, o);
            let size = u32le(b, o + 4) as usize;
            if size < 8 || o + size > b.len() {
                break;
            }
            let r = &b[o..o + size];
            self.emf_record(kind, r);
            if kind == 14 {
                break;
            }
            o += size;
            count += 1;
            if count > 2_000_000 {
                break;
            }
        }
        true
    }

    fn pts16(r: &[u8], at: usize, n: usize) -> Vec<(f64, f64)> {
        (0..n).map(|i| (i16le(r, at + i * 4) as f64, i16le(r, at + i * 4 + 2) as f64)).collect()
    }

    fn pts32(r: &[u8], at: usize, n: usize) -> Vec<(f64, f64)> {
        (0..n).map(|i| (i32le(r, at + i * 8) as f64, i32le(r, at + i * 8 + 4) as f64)).collect()
    }

    fn emf_record(&mut self, kind: u32, r: &[u8]) {
        let n = |o: usize| i32le(r, o) as f64;
        match kind {
            // polygons and lines: bounds(16) count(4) points
            2 | 3 | 4 | 5 | 6 => {
                let cnt = (u32le(r, 24) as usize).min((r.len().saturating_sub(28)) / 8);
                let pts = Self::pts32(r, 28, cnt);
                self.emf_poly(kind, pts);
            }
            85 | 86 | 87 | 88 | 89 => {
                let cnt = (u32le(r, 24) as usize).min((r.len().saturating_sub(28)) / 4);
                let pts = Self::pts16(r, 28, cnt);
                self.emf_poly(kind - 83, pts);
            }
            7 | 8 | 90 | 91 => {
                // poly-polyline / polygon: bounds, nPolys, total, counts, points
                let np = (u32le(r, 24) as usize).min(r.len() / 4);
                let total = u32le(r, 28) as usize;
                let mut at = 32 + np * 4;
                let small = kind >= 90;
                let mut polys = Vec::new();
                for i in 0..np {
                    let c = (u32le(r, 32 + i * 4) as usize).min(total);
                    let pts = if small { Self::pts16(r, at, c) } else { Self::pts32(r, at, c) };
                    at += c * if small { 4 } else { 8 };
                    if at > r.len() {
                        break;
                    }
                    polys.push(pts);
                }
                self.polypoly(&polys, kind == 8 || kind == 91);
            }
            9 => self.dc.win_ext = (n(8), n(12)),
            10 => self.dc.win_org = (n(8), n(12)),
            11 => self.dc.vp_ext = (n(8), n(12)),
            12 => self.dc.vp_org = (n(8), n(12)),
            17 => self.dc.map_mode = u32le(r, 8),
            18 => self.dc.bk_mode = u32le(r, 8),
            19 => self.dc.fill_mode = u32le(r, 8),
            22 => self.dc.text_align = u32le(r, 8),
            24 => self.dc.text_color = colorref(u32le(r, 8)),
            25 => self.dc.bk_color = colorref(u32le(r, 8)),
            27 => {
                self.dc.cur = (n(8), n(12));
                if self.in_path {
                    let c = self.dc.cur;
                    self.with_logical(|cr| cr.move_to(c.0, c.1));
                }
            }
            30 => {
                // IntersectClipRect
                let (l, t, rr, bb) = (n(8), n(12), n(16), n(20));
                let cr = self.cr;
                cr.new_path();
                self.with_logical(|cr| cr.rectangle(l, t, rr - l, bb - t));
                cr.clip();
            }
            31 => {
                let (xn, xd, yn, yd) = (n(8), n(12), n(16), n(20));
                self.dc.vp_ext = (self.dc.vp_ext.0 * xn / nz(xd), self.dc.vp_ext.1 * yn / nz(yd));
            }
            32 => {
                let (xn, xd, yn, yd) = (n(8), n(12), n(16), n(20));
                self.dc.win_ext = (self.dc.win_ext.0 * xn / nz(xd), self.dc.win_ext.1 * yn / nz(yd));
            }
            33 => self.save_dc(),
            34 => self.restore_dc(i32le(r, 8)),
            35 => self.dc.world = xform(r, 8),
            36 => {
                let m = xform(r, 8);
                match u32le(r, 32) {
                    1 => self.dc.world = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0],
                    2 => self.dc.world = mul(m, self.dc.world),
                    3 => self.dc.world = mul(self.dc.world, m),
                    4 => self.dc.world = m,
                    _ => {}
                }
            }
            37 => {
                let i = u32le(r, 8);
                if i & 0x8000_0000 != 0 {
                    self.select_stock(i);
                } else if let Some(Some(o)) = self.objs.get(i as usize).cloned() {
                    self.select(&o);
                }
            }
            38 => {
                // CreatePen: index, style, width (x), color
                let p = Pen { style: u32le(r, 12), width: n(16), color: colorref(u32le(r, 24)) };
                self.put_obj(u32le(r, 8) as usize, Obj::Pen(p));
            }
            95 => {
                // ExtCreatePen: index, offBmi, cbBmi, offBits, cbBits, style, width, brushStyle, color
                let p = Pen { style: u32le(r, 28), width: n(32), color: colorref(u32le(r, 40)) };
                let p = if u32le(r, 36) == 1 { Pen { style: 5, ..p } } else { p };
                self.put_obj(u32le(r, 8) as usize, Obj::Pen(p));
            }
            39 => {
                let st = u32le(r, 12);
                let b = Brush { style: if st == 1 { 1 } else { 0 }, color: colorref(u32le(r, 16)) };
                self.put_obj(u32le(r, 8) as usize, Obj::Brush(b));
            }
            93 | 94 => {
                // pattern brushes: a grey stand-in
                self.put_obj(u32le(r, 8) as usize, Obj::Brush(Brush { style: 0, color: 0xC0C0C0 }));
            }
            40 => {
                let i = u32le(r, 8) as usize;
                if let Some(s) = self.objs.get_mut(i) {
                    *s = None;
                }
            }
            42 => self.ellipse(n(8), n(12), n(16), n(20)),
            43 => self.rect(n(8), n(12), n(16), n(20)),
            44 => self.round_rect(n(8), n(12), n(16), n(20), n(24), n(28)),
            45 | 46 | 47 | 55 => {
                let b4 = [n(8), n(12), n(16), n(20)];
                self.arc(b4, (n(24), n(28)), (n(32), n(36)), match kind { 46 => 1, 47 => 2, _ => 0 });
            }
            54 => {
                let to = (n(8), n(12));
                let from = self.dc.cur;
                if self.in_path {
                    self.with_logical(|cr| {
                        if !cr.has_current_point().unwrap_or(false) {
                            cr.move_to(from.0, from.1);
                        }
                        cr.line_to(to.0, to.1);
                    });
                } else {
                    self.poly(&[from, to], false, false);
                }
                self.dc.cur = to;
            }
            59 => {
                self.in_path = true;
                self.cr.new_path();
            }
            60 => {
                self.in_path = false;
                self.path = self.cr.copy_path().ok();
                self.cr.new_path();
            }
            61 => {
                if self.in_path {
                    self.cr.close_path();
                }
            }
            62 | 63 | 64 => {
                if let Some(p) = self.path.take() {
                    self.cr.new_path();
                    self.cr.append_path(&p);
                    self.paint(kind != 64, kind != 62);
                }
            }
            67 => {
                if let Some(p) = self.path.take() {
                    let cr = self.cr;
                    if u32le(r, 8) == 5 {
                        self.reset_clip();
                    }
                    cr.new_path();
                    cr.append_path(&p);
                    self.fill_rule();
                    cr.clip();
                }
            }
            68 => {
                self.in_path = false;
                self.path = None;
                self.cr.new_path();
            }
            75 => {
                // ExtSelectClipRgn: cbRgnData, mode, region
                let cb = u32le(r, 8) as usize;
                let mode = u32le(r, 12);
                if cb == 0 || mode == 5 {
                    self.reset_clip();
                }
                if cb >= 32 {
                    let cnt = u32le(r, 16 + 8) as usize;
                    let cr = self.cr;
                    cr.new_path();
                    cr.save().ok();
                    cr.transform(self.dev_to_out());
                    for i in 0..cnt.min((r.len().saturating_sub(48)) / 16) {
                        let at = 16 + 32 + i * 16;
                        let (l, t, rr, bb) = (n(at), n(at + 4), n(at + 8), n(at + 12));
                        cr.rectangle(l, t, rr - l, bb - t);
                    }
                    cr.restore().ok();
                    if mode == 1 || mode == 5 {
                        cr.set_fill_rule(cairo::FillRule::Winding);
                        cr.clip();
                    } else {
                        cr.new_path();
                    }
                }
            }
            76 | 77 | 114 | 116 => {
                // BitBlt / StretchBlt / AlphaBlend / TransparentBlt
                let (xd, yd, cxd, cyd) = (n(24), n(28), n(32), n(36));
                let (off_bmi, cb_bmi, off_bits) = if kind == 76 || kind == 77 {
                    (u32le(r, 84) as usize, u32le(r, 88) as usize, u32le(r, 92) as usize)
                } else {
                    (u32le(r, 84) as usize, u32le(r, 88) as usize, u32le(r, 92) as usize)
                };
                let (xs, ys) = (n(44), n(48));
                let (cxs, cys) = if kind == 76 { (cxd, cyd) } else { (n(100), n(104)) };
                if cb_bmi == 0 {
                    // a pattern fill with the brush
                    let rop = u32le(r, 40);
                    if self.dc.brush.style != 1 && (rop == 0x00F00021 || rop == 0x005A0049) {
                        let cr = self.cr;
                        cr.new_path();
                        self.with_logical(|cr| cr.rectangle(xd, yd, cxd, cyd));
                        set_rgb(cr, self.dc.brush.color);
                        cr.fill().ok();
                    } else if rop == 0x00000042 {
                        let cr = self.cr;
                        cr.new_path();
                        self.with_logical(|cr| cr.rectangle(xd, yd, cxd, cyd));
                        set_rgb(cr, 0);
                        cr.fill().ok();
                    }
                } else {
                    self.dib(r, off_bmi, off_bits, [xd, yd, cxd, cyd], [xs, ys, cxs, cys]);
                }
            }
            80 => {
                // SetDIBitsToDevice
                let (xd, yd, xs, ys, cx, cy) = (n(24), n(28), n(32), n(36), n(40), n(44));
                let (off_bmi, off_bits) = (u32le(r, 48) as usize, u32le(r, 56) as usize);
                self.dib(r, off_bmi, off_bits, [xd, yd, cx, cy], [xs, ys, cx, cy]);
            }
            81 => {
                // StretchDIBits
                let (xd, yd, xs, ys, cxs, cys) = (n(24), n(28), n(32), n(36), n(40), n(44));
                let (off_bmi, off_bits) = (u32le(r, 48) as usize, u32le(r, 56) as usize);
                let (cxd, cyd) = (n(72), n(76));
                self.dib(r, off_bmi, off_bits, [xd, yd, cxd, cyd], [xs, ys, cxs, cys]);
            }
            82 => {
                // ExtCreateFontIndirectW: index, LOGFONTW
                let lf = 12;
                let face: Vec<u16> = (0..32).map(|i| u16le(r, lf + 28 + i * 2)).take_while(|&c| c != 0).collect();
                let f = Font {
                    height: n(lf),
                    escapement: n(lf + 8),
                    weight: i32le(r, lf + 16),
                    italic: r.get(lf + 20).copied().unwrap_or(0) != 0,
                    underline: r.get(lf + 21).copied().unwrap_or(0) != 0,
                    strike: r.get(lf + 22).copied().unwrap_or(0) != 0,
                    face: String::from_utf16_lossy(&face),
                };
                self.put_obj(u32le(r, 8) as usize, Obj::Font(f));
            }
            83 | 84 => {
                // ExtTextOutA/W: bounds(16), graphicsMode, exScale, eyScale, EmrText
                let t = 36;
                let (x, y) = (n(t), n(t + 4));
                let chars = u32le(r, t + 8) as usize;
                let off_string = u32le(r, t + 12) as usize;
                let opts = u32le(r, t + 16);
                let clip = [n(t + 20), n(t + 24), n(t + 28), n(t + 32)];
                let off_dx = u32le(r, t + 36) as usize;
                let s = if kind == 84 {
                    let u: Vec<u16> = (0..chars).map(|i| u16le(r, off_string + i * 2)).collect();
                    String::from_utf16_lossy(&u)
                } else {
                    r.get(off_string..off_string + chars).map(|b| b.iter().map(|&c| c as char).collect()).unwrap_or_default()
                };
                let dx: Vec<f64> = if off_dx > 0 && off_dx + chars * 4 <= r.len() {
                    (0..chars).map(|i| i32le(r, off_dx + i * 4) as f64).collect()
                } else {
                    Vec::new()
                };
                let (x, y) = if self.dc.text_align & 1 != 0 { self.dc.cur } else { (x, y) };
                self.text(x, y, &s, &dx, opts, Some(clip));
            }
            _ => {}
        }
    }

    fn emf_poly(&mut self, kind: u32, pts: Vec<(f64, f64)>) {
        match kind {
            2 => self.bezier(&pts, false),
            3 => self.poly(&pts, true, true),
            4 => self.poly(&pts, false, false),
            5 => self.bezier(&pts, true),
            6 => {
                let mut all = vec![self.dc.cur];
                all.extend(pts.iter().copied());
                if self.in_path {
                    self.with_logical(|cr| {
                        if !cr.has_current_point().unwrap_or(false) {
                            cr.move_to(all[0].0, all[0].1);
                        }
                        for p in &all[1..] {
                            cr.line_to(p.0, p.1);
                        }
                    });
                } else {
                    self.poly(&all, false, false);
                }
                if let Some(l) = pts.last() {
                    self.dc.cur = *l;
                }
            }
            _ => {}
        }
    }

    // ------------------------------------------------------------ WMF
    fn wmf(&mut self, b: &[u8]) -> bool {
        let mut o = 0;
        // the placeable header: bounding box and units per inch
        let mut placed: Option<(f64, f64, f64, f64)> = None;
        if u32le(b, 0) == 0x9AC6CDD7 {
            let (l, t, r, bt) = (i16le(b, 6) as f64, i16le(b, 8) as f64, i16le(b, 10) as f64, i16le(b, 12) as f64);
            placed = Some((l, t, r - l, bt - t));
            o = 22;
        }
        let hdr_words = u16le(b, o + 2) as usize;
        let nobjs = u16le(b, o + 10) as usize;
        self.objs = vec![None; nobjs.max(1)];
        o += hdr_words * 2;
        self.wmf = true;
        // anisotropic: the window maps onto the picture
        self.dc.map_mode = 8;
        if let Some((l, t, w, h)) = placed {
            self.dc.win_org = (l, t);
            self.dc.win_ext = (nz(w), nz(h));
        } else {
            self.dc.win_ext = (1000.0, 1000.0);
        }
        self.dc.vp_ext = (1.0, 1.0);
        self.src = (0.0, 0.0, 1.0, 1.0);
        let cr = self.cr;
        cr.rectangle(0.0, 0.0, self.w, self.h);
        cr.clip();
        let mut count = 0;
        while o + 6 <= b.len() {
            let size = u32le(b, o) as usize * 2;
            let func = u16le(b, o + 4);
            if size < 6 || o + size > b.len() {
                break;
            }
            if func == 0 {
                break;
            }
            let r = &b[o..o + size];
            self.wmf_record(func, r);
            o += size;
            count += 1;
            if count > 2_000_000 {
                break;
            }
        }
        true
    }

    fn wmf_new_obj(&mut self, o: Obj) {
        if let Some(slot) = self.objs.iter_mut().find(|s| s.is_none()) {
            *slot = Some(o);
        } else {
            self.objs.push(Some(o));
        }
    }

    fn wmf_record(&mut self, func: u16, r: &[u8]) {
        let p = |i: usize| i16le(r, 6 + i * 2) as f64;
        let pu = |i: usize| u16le(r, 6 + i * 2);
        match func {
            0x020B => self.dc.win_org = (p(1), p(0)),
            0x020C => {
                self.dc.win_ext = (nz(p(1)), nz(p(0)));
            }
            0x0103 => {
                let m = pu(0) as u32;
                // only anisotropic-style mapping makes sense for a placed picture
                self.dc.map_mode = if m == 7 { 7 } else { 8 };
            }
            0x0102 => self.dc.bk_mode = pu(0) as u32,
            0x0106 => self.dc.fill_mode = pu(0) as u32,
            0x012E => self.dc.text_align = pu(0) as u32,
            0x0209 => self.dc.text_color = colorref(u32le(r, 6)),
            0x0201 => self.dc.bk_color = colorref(u32le(r, 6)),
            0x001E => self.save_dc(),
            0x0127 => self.restore_dc(p(0) as i32),
            0x0214 => self.dc.cur = (p(1), p(0)),
            0x0213 => {
                let to = (p(1), p(0));
                let from = self.dc.cur;
                self.poly(&[from, to], false, false);
                self.dc.cur = to;
            }
            0x0325 | 0x0324 => {
                let cnt = (pu(0) as usize).min((r.len().saturating_sub(8)) / 4);
                let pts = Self::pts16(r, 8, cnt);
                if func == 0x0324 {
                    self.poly(&pts, true, true);
                } else {
                    self.poly(&pts, false, false);
                }
            }
            0x0538 => {
                let np = pu(0) as usize;
                let mut at = 8 + np * 2;
                let mut polys = Vec::new();
                for i in 0..np {
                    let c = u16le(r, 8 + i * 2) as usize;
                    if at + c * 4 > r.len() {
                        break;
                    }
                    polys.push(Self::pts16(r, at, c));
                    at += c * 4;
                }
                self.polypoly(&polys, true);
            }
            0x041B => self.rect(p(3), p(2), p(1), p(0)),
            0x0418 => self.ellipse(p(3), p(2), p(1), p(0)),
            0x061C => self.round_rect(p(5), p(4), p(3), p(2), p(1), p(0)),
            0x0817 | 0x0830 | 0x081A => {
                let b4 = [p(7), p(6), p(5), p(4)];
                let kind = match func { 0x0830 => 1, 0x081A => 2, _ => 0 };
                self.arc(b4, (p(3), p(2)), (p(1), p(0)), kind);
            }
            0x02FA => {
                // CreatePenIndirect: style, width (point), color
                let pen = Pen { style: pu(0) as u32, width: p(1), color: colorref(u32le(r, 12)) };
                self.wmf_new_obj(Obj::Pen(pen));
            }
            0x02FC => {
                let st = pu(0) as u32;
                let br = Brush { style: if st == 1 { 1 } else { 0 }, color: colorref(u32le(r, 8)) };
                self.wmf_new_obj(Obj::Brush(br));
            }
            0x0142 | 0x01F9 | 0x06FF | 0x00F7 => {
                let o = if func == 0x0142 { Obj::Brush(Brush { style: 0, color: 0xC0C0C0 }) } else { Obj::Other };
                self.wmf_new_obj(o);
            }
            0x02FB => {
                // CreateFontIndirect: height, width, esc, orient, weight, italic, underline, strike...
                let face: Vec<u8> = r.get(6 + 18..).unwrap_or(&[]).iter().take(32).copied().take_while(|&c| c != 0).collect();
                let f = Font {
                    height: p(0),
                    escapement: p(2),
                    weight: p(4) as i32,
                    italic: r.get(16).copied().unwrap_or(0) != 0,
                    underline: r.get(17).copied().unwrap_or(0) != 0,
                    strike: r.get(18).copied().unwrap_or(0) != 0,
                    face: face.iter().map(|&c| c as char).collect(),
                };
                self.wmf_new_obj(Obj::Font(f));
            }
            0x012D => {
                if let Some(Some(o)) = self.objs.get(pu(0) as usize).cloned() {
                    self.select(&o);
                }
            }
            0x01F0 => {
                if let Some(s) = self.objs.get_mut(pu(0) as usize) {
                    *s = None;
                }
            }
            0x0521 => {
                // TextOut: count, string, y, x
                let n = pu(0) as usize;
                let s: String = r.get(8..8 + n).unwrap_or(&[]).iter().map(|&c| cp1252(c)).collect();
                let at = 8 + n.div_ceil(2) * 2;
                let (y, x) = (i16le(r, at) as f64, i16le(r, at + 2) as f64);
                let (x, y) = if self.dc.text_align & 1 != 0 { self.dc.cur } else { (x, y) };
                self.text(x, y, &s, &[], 0, None);
            }
            0x0A32 => {
                // ExtTextOut: y, x, count, options, [rect], string, [dx]
                let (y, x) = (p(0), p(1));
                let n = pu(2) as usize;
                let opts = pu(3) as u32;
                let mut at = 14;
                let mut clip = None;
                if opts & 0x6 != 0 {
                    clip = Some([i16le(r, at) as f64, i16le(r, at + 2) as f64, i16le(r, at + 4) as f64, i16le(r, at + 6) as f64]);
                    at += 8;
                }
                let s: String = r.get(at..at + n).unwrap_or(&[]).iter().map(|&c| cp1252(c)).collect();
                at += n.div_ceil(2) * 2;
                let dx: Vec<f64> = if at + n * 2 <= r.len() {
                    (0..n).map(|i| i16le(r, at + i * 2) as f64).collect()
                } else {
                    Vec::new()
                };
                let (x, y) = if self.dc.text_align & 1 != 0 { self.dc.cur } else { (x, y) };
                self.text(x, y, &s, &dx, opts, clip);
            }
            0x0416 => {
                // IntersectClipRect: bottom, right, top, left
                let (bb, rr, t, l) = (p(0), p(1), p(2), p(3));
                let cr = self.cr;
                cr.new_path();
                self.with_logical(|cr| cr.rectangle(l, t, rr - l, bb - t));
                cr.clip();
            }
            0x0F43 => {
                // StretchDIB: rop(4), usage, srcH, srcW, ySrc, xSrc, destH, destW, yDst, xDst, DIB
                let (sh, sw, ys, xs) = (p(3), p(4), p(5), p(6));
                let (dh, dw, yd, xd) = (p(7), p(8), p(9), p(10));
                let bmi = 6 + 22;
                self.dib(r, bmi, usize::MAX, [xd, yd, dw, dh], [xs, ys, sw, sh]);
            }
            0x0B41 => {
                // DIBStretchBlt: rop(4), srcH, srcW, ySrc, xSrc, destH, destW, yDst, xDst, DIB
                let (sh, sw, ys, xs) = (p(2), p(3), p(4), p(5));
                let (dh, dw, yd, xd) = (p(6), p(7), p(8), p(9));
                let bmi = 6 + 20;
                if bmi < r.len() {
                    self.dib(r, bmi, usize::MAX, [xd, yd, dw, dh], [xs, ys, sw, sh]);
                }
            }
            0x0940 => {
                // DIBBitBlt: rop, ySrc, xSrc, height, width, yDst, xDst, DIB
                let (ys, xs, h, w, yd, xd) = (p(2), p(3), p(4), p(5), p(6), p(7));
                let bmi = 6 + 16;
                if bmi < r.len() {
                    self.dib(r, bmi, usize::MAX, [xd, yd, w, h], [xs, ys, w, h]);
                }
            }
            _ => {}
        }
    }
}

fn nz(v: f64) -> f64 {
    if v.abs() < 1e-12 {
        1.0
    } else {
        v
    }
}

fn xform(r: &[u8], o: usize) -> [f64; 6] {
    [f32le(r, o), f32le(r, o + 4), f32le(r, o + 8), f32le(r, o + 12), f32le(r, o + 16), f32le(r, o + 20)]
}

/// a then b (x' = b(a(x))).
fn mul(a: [f64; 6], b: [f64; 6]) -> [f64; 6] {
    [
        a[0] * b[0] + a[1] * b[2],
        a[0] * b[1] + a[1] * b[3],
        a[2] * b[0] + a[3] * b[2],
        a[2] * b[1] + a[3] * b[3],
        a[4] * b[0] + a[5] * b[2] + b[4],
        a[4] * b[1] + a[5] * b[3] + b[5],
    ]
}

fn cp1252(c: u8) -> char {
    const HI: [u16; 32] = [0x20AC, 0x81, 0x201A, 0x192, 0x201E, 0x2026, 0x2020, 0x2021, 0x2C6, 0x2030, 0x160, 0x2039,
                           0x152, 0x8D, 0x17D, 0x8F, 0x90, 0x2018, 0x2019, 0x201C, 0x201D, 0x2022, 0x2013, 0x2014,
                           0x2DC, 0x2122, 0x161, 0x203A, 0x153, 0x9D, 0x17E, 0x178];
    if (0x80..0xA0).contains(&c) {
        char::from_u32(HI[(c - 0x80) as usize] as u32).unwrap_or('?')
    } else {
        c as char
    }
}

/// Fonts metafiles name, as installed ones.
fn map_face(face: &str) -> String {
    let f = face.trim();
    match f.to_ascii_lowercase().as_str() {
        "" | "system" | "ms sans serif" | "ms shell dlg" | "ms shell dlg 2" | "tahoma" => "Liberation Sans".into(),
        "arial" | "helvetica" => "Liberation Sans".into(),
        "times new roman" | "times" | "ms serif" => "Liberation Serif".into(),
        "courier new" | "courier" => "Liberation Mono".into(),
        "symbol" => "DejaVu Sans".into(),
        "mt extra" => "DejaVu Sans".into(),
        _ => f.to_string(),
    }
}

/// A DIB (BITMAPINFOHEADER at `bmi` in `data`, pixels at `bits`, or just
/// after the colour table if `bits` is usize::MAX) as a cairo surface.
fn dib_surface(data: &[u8], bmi: usize, bits: usize) -> Option<cairo::ImageSurface> {
    let hs = u32le(data, bmi) as usize;
    if hs < 12 || bmi + hs > data.len() {
        return None;
    }
    let (w, h, bpp, comp, used) = if hs == 12 {
        (u16le(data, bmi + 4) as i32, i16le(data, bmi + 6) as i32, u16le(data, bmi + 10) as u32, 0u32, 0u32)
    } else {
        (i32le(data, bmi + 4), i32le(data, bmi + 8), u16le(data, bmi + 14) as u32, u32le(data, bmi + 16),
         u32le(data, bmi + 32))
    };
    if w <= 0 || h == 0 || w > 20000 || h.abs() > 20000 {
        return None;
    }
    let top_down = h < 0;
    let h = h.unsigned_abs() as i32;
    let ncolors = if bpp <= 8 { if used > 0 { used as usize } else { 1usize << bpp } } else { 0 };
    let entry = if hs == 12 { 3 } else { 4 };
    let mut pal_at = bmi + hs;
    let mut masks = (0x00FF0000u32, 0x0000FF00u32, 0x000000FFu32);
    if comp == 3 && hs == 40 {
        masks = (u32le(data, pal_at), u32le(data, pal_at + 4), u32le(data, pal_at + 8));
        pal_at += 12;
    } else if comp == 3 && hs >= 52 {
        masks = (u32le(data, bmi + 40), u32le(data, bmi + 44), u32le(data, bmi + 48));
    } else if bpp == 16 {
        masks = (0x7C00, 0x03E0, 0x001F);
    }
    let palette: Vec<u32> = (0..ncolors)
        .map(|i| {
            let o = pal_at + i * entry;
            ((data.get(o + 2).copied().unwrap_or(0) as u32) << 16)
                | ((data.get(o + 1).copied().unwrap_or(0) as u32) << 8)
                | data.get(o).copied().unwrap_or(0) as u32
        })
        .collect();
    let bits = if bits == usize::MAX { pal_at + ncolors * entry } else { bits };
    if comp == 4 || comp == 5 {
        // JPEG / PNG inside
        let sz = u32le(data, bmi + 20) as usize;
        let img = data.get(bits..bits + sz)?;
        return crate::pictures::decode(img, 4096);
    }
    if comp == 1 || comp == 2 {
        return None; // RLE: rare in documents
    }
    let stride_in = ((w as usize * bpp as usize + 31) / 32) * 4;
    if bits + stride_in * h as usize > data.len() {
        return None;
    }
    let mut surf = cairo::ImageSurface::create(cairo::Format::ARgb32, w, h).ok()?;
    let stride = surf.stride() as usize;
    let field = |v: u32, m: u32| -> u32 {
        if m == 0 {
            return 0;
        }
        let shift = m.trailing_zeros();
        let max = m >> shift;
        ((v & m) >> shift) * 255 / max.max(1)
    };
    let has_alpha = bpp == 32 && comp == 0 && {
        // 32-bit DIBs are opaque unless some alpha is set
        let mut any = false;
        for y in 0..h as usize {
            let row = &data[bits + y * stride_in..bits + y * stride_in + w as usize * 4];
            if row.chunks(4).any(|p| p[3] != 0) {
                any = true;
                break;
            }
        }
        any
    };
    {
        let mut out = surf.data().ok()?;
        for y in 0..h as usize {
            let src_row = if top_down { y } else { h as usize - 1 - y };
            let row = &data[bits + src_row * stride_in..bits + src_row * stride_in + stride_in];
            for x in 0..w as usize {
                let (rgb, a) = match bpp {
                    1 => (palette.get(((row[x / 8] >> (7 - x % 8)) & 1) as usize).copied().unwrap_or(0), 255),
                    4 => (palette.get(((row[x / 2] >> if x % 2 == 0 { 4 } else { 0 }) & 15) as usize).copied().unwrap_or(0), 255),
                    8 => (palette.get(row[x] as usize).copied().unwrap_or(0), 255),
                    16 => {
                        let v = u16::from_le_bytes([row[x * 2], row[x * 2 + 1]]) as u32;
                        ((field(v, masks.0) << 16) | (field(v, masks.1) << 8) | field(v, masks.2), 255)
                    }
                    24 => (((row[x * 3 + 2] as u32) << 16) | ((row[x * 3 + 1] as u32) << 8) | row[x * 3] as u32, 255),
                    32 => {
                        let v = u32::from_le_bytes([row[x * 4], row[x * 4 + 1], row[x * 4 + 2], row[x * 4 + 3]]);
                        let rgb = if comp == 3 { (field(v, masks.0) << 16) | (field(v, masks.1) << 8) | field(v, masks.2) } else { v & 0xFFFFFF };
                        (rgb, if has_alpha { row[x * 4 + 3] as u32 } else { 255 })
                    }
                    _ => (0, 255),
                };
                let pm = |c: u32| (c * a + 127) / 255;
                let v = (a << 24) | (pm((rgb >> 16) & 255) << 16) | (pm((rgb >> 8) & 255) << 8) | pm(rgb & 255);
                out[y * stride + x * 4..y * stride + x * 4 + 4].copy_from_slice(&v.to_ne_bytes());
            }
        }
    }
    surf.mark_dirty();
    Some(surf)
}

/// A Symbol-font character code as Unicode.
fn symbol_char(c: u32) -> char {
    let c = if (0xF020..=0xF0FF).contains(&c) { c - 0xF000 } else { c };
    let u = match c {
        0x22 => 0x2200,
        0x24 => 0x2203,
        0x27 => 0x220B,
        0x2A => 0x2217,
        0x2D => 0x2212,
        0x40 => 0x2245,
        0x41 => 0x0391,
        0x42 => 0x0392,
        0x43 => 0x03A7,
        0x44 => 0x0394,
        0x45 => 0x0395,
        0x46 => 0x03A6,
        0x47 => 0x0393,
        0x48 => 0x0397,
        0x49 => 0x0399,
        0x4A => 0x03D1,
        0x4B => 0x039A,
        0x4C => 0x039B,
        0x4D => 0x039C,
        0x4E => 0x039D,
        0x4F => 0x039F,
        0x50 => 0x03A0,
        0x51 => 0x0398,
        0x52 => 0x03A1,
        0x53 => 0x03A3,
        0x54 => 0x03A4,
        0x55 => 0x03A5,
        0x56 => 0x03C2,
        0x57 => 0x03A9,
        0x58 => 0x039E,
        0x59 => 0x03A8,
        0x5A => 0x0396,
        0x5C => 0x2234,
        0x5E => 0x22A5,
        0x60 => 0xF8E5,
        0x61 => 0x03B1,
        0x62 => 0x03B2,
        0x63 => 0x03C7,
        0x64 => 0x03B4,
        0x65 => 0x03B5,
        0x66 => 0x03C6,
        0x67 => 0x03B3,
        0x68 => 0x03B7,
        0x69 => 0x03B9,
        0x6A => 0x03D5,
        0x6B => 0x03BA,
        0x6C => 0x03BB,
        0x6D => 0x03BC,
        0x6E => 0x03BD,
        0x6F => 0x03BF,
        0x70 => 0x03C0,
        0x71 => 0x03B8,
        0x72 => 0x03C1,
        0x73 => 0x03C3,
        0x74 => 0x03C4,
        0x75 => 0x03C5,
        0x76 => 0x03D6,
        0x77 => 0x03C9,
        0x78 => 0x03BE,
        0x79 => 0x03C8,
        0x7A => 0x03B6,
        0x7E => 0x223C,
        0xA1 => 0x03D2,
        0xA2 => 0x2032,
        0xA3 => 0x2264,
        0xA4 => 0x2044,
        0xA5 => 0x221E,
        0xA6 => 0x0192,
        0xA7 => 0x2663,
        0xA8 => 0x2666,
        0xA9 => 0x2665,
        0xAA => 0x2660,
        0xAB => 0x2194,
        0xAC => 0x2190,
        0xAD => 0x2191,
        0xAE => 0x2192,
        0xAF => 0x2193,
        0xB0 => 0x00B0,
        0xB1 => 0x00B1,
        0xB2 => 0x2033,
        0xB3 => 0x2265,
        0xB4 => 0x00D7,
        0xB5 => 0x221D,
        0xB6 => 0x2202,
        0xB7 => 0x2022,
        0xB8 => 0x00F7,
        0xB9 => 0x2260,
        0xBA => 0x2261,
        0xBB => 0x2248,
        0xBC => 0x2026,
        0xBF => 0x21B5,
        0xC0 => 0x2135,
        0xC1 => 0x2111,
        0xC2 => 0x211C,
        0xC3 => 0x2118,
        0xC4 => 0x2297,
        0xC5 => 0x2295,
        0xC6 => 0x2205,
        0xC7 => 0x2229,
        0xC8 => 0x222A,
        0xC9 => 0x2283,
        0xCA => 0x2287,
        0xCB => 0x2284,
        0xCC => 0x2282,
        0xCD => 0x2286,
        0xCE => 0x2208,
        0xCF => 0x2209,
        0xD0 => 0x2220,
        0xD1 => 0x2207,
        0xD5 => 0x220F,
        0xD6 => 0x221A,
        0xD7 => 0x22C5,
        0xD8 => 0x00AC,
        0xD9 => 0x2227,
        0xDA => 0x2228,
        0xDB => 0x21D4,
        0xDC => 0x21D0,
        0xDD => 0x21D1,
        0xDE => 0x21D2,
        0xDF => 0x21D3,
        0xE0 => 0x25CA,
        0xE1 => 0x2329,
        0xE5 => 0x2211,
        0xE6 => 0x239B,
        0xE7 => 0x239C,
        0xE8 => 0x239D,
        0xE9 => 0x23A1,
        0xEA => 0x23A2,
        0xEB => 0x23A3,
        0xEC => 0x23A7,
        0xED => 0x23A8,
        0xEE => 0x23A9,
        0xEF => 0x23AA,
        0xF1 => 0x232A,
        0xF2 => 0x222B,
        0xF3 => 0x2320,
        0xF4 => 0x23AE,
        0xF5 => 0x2321,
        0xF6 => 0x239E,
        0xF7 => 0x239F,
        0xF8 => 0x23A0,
        0xF9 => 0x23A4,
        0xFA => 0x23A5,
        0xFB => 0x23A6,
        0xFC => 0x23AB,
        0xFD => 0x23AC,
        0xFE => 0x23AD,
        _ => c,
    };
    char::from_u32(u).unwrap_or('?')
}
