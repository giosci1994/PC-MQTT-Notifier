"""New notification styles (A "aurora", B "glass") drawn with Pillow,
plus the few Windows helpers they need (per-pixel alpha layered window,
acrylic backdrop, app theme from the registry).

This module never imports tkinter: the drawing part runs anywhere Pillow
runs (it is also used to render preview PNGs off Windows). Everything that
touches Windows is guarded by ``os.name == 'nt'`` and try/except.
"""
import math
import os

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

# --- Config values -----------------------------------------------------------

STYLES = ("glass", "aurora", "classic", "static")
DEFAULT_STYLE = "glass"
PALETTES = {
    "night": ("#6d5dfc", "#2f8cff", "#22c3d6"),
    "sunset": ("#ff6b8b", "#ff9a5a", "#b45cff"),
    "forest": ("#2bb673", "#1fa2a8", "#7bd88f"),
}
DEFAULT_PALETTE = "night"
GLOWS = {"full": 0.45, "soft": 0.18}
DEFAULT_GLOW = "soft"
THEMES = ("dark", "light", "system")
RAINBOW = ("#ff5f6d", "#ffc371", "#47e5bc", "#4facfe", "#a66cff")

SS = 4  # supersampling factor for shapes (masks, icons)
CARD_WIDTH = 380
BASE_RADIUS = 18


def migrate_config(cfg):
    """Fill the new keys of an existing config without touching the others.

    - a valid ``notification_style`` already there is kept;
    - otherwise ``enable_fluid: false`` -> "static", anything else -> the new
      default (glass, soft glow).
    """
    if cfg.get("notification_style") not in STYLES:
        if cfg.get("enable_fluid", True) is False:
            cfg["notification_style"] = "static"
        else:
            cfg["notification_style"] = DEFAULT_STYLE
            cfg["glass_glow"] = DEFAULT_GLOW
    if cfg.get("aurora_palette") not in PALETTES:
        cfg["aurora_palette"] = DEFAULT_PALETTE
    if cfg.get("glass_glow") not in GLOWS:
        cfg["glass_glow"] = DEFAULT_GLOW
    if cfg.get("theme") not in THEMES:
        cfg["theme"] = "dark"
    return cfg


def hex_rgb(value):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def ease_out_back(x, k=1.15):
    """Ease with a small overshoot (like cubic-bezier(.2,.9,.25,1.15))."""
    x = max(0.0, min(1.0, x))
    c3 = k + 1
    return 1 + c3 * (x - 1) ** 3 + k * (x - 1) ** 2


# --- Theme ---------------------------------------------------------------

def windows_apps_dark():
    """True/False from HKCU ...Personalize\\AppsUseLightTheme, None if unknown."""
    if os.name != "nt":
        return None
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        try:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        finally:
            winreg.CloseKey(key)
        return int(value) == 0
    except Exception:
        return None


def resolve_dark(theme):
    """Theme from config ("dark" / "light" / "system") -> is it dark now?"""
    if theme == "system":
        dark = windows_apps_dark()
        return True if dark is None else dark
    return theme != "light"


# --- Fonts and text --------------------------------------------------------

_FONT_CACHE = {}


def _font_files(bold):
    files = []
    if os.name == "nt":
        fonts = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
        names = ["seguisb.ttf", "segoeuib.ttf", "arialbd.ttf"] if bold else ["segoeui.ttf", "arial.ttf"]
        files += [os.path.join(fonts, n) for n in names]
    if bold:
        files += ["DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
    else:
        files += ["DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    return files


def load_font(size, bold=False):
    size = max(6, int(round(size)))
    key = (size, bold)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    font = None
    for path in _font_files(bold):
        try:
            font = ImageFont.truetype(path, size)
            break
        except Exception:
            continue
    if font is None:
        try:
            font = ImageFont.load_default(size=size)
        except Exception:
            font = ImageFont.load_default()
    _FONT_CACHE[key] = font
    return font


def _text_w(font, text):
    try:
        return font.getlength(text)
    except Exception:
        return len(text) * 7


def wrap_text(text, font, width, max_lines):
    """Word wrap to ``width`` px, at most ``max_lines`` lines, with an ellipsis."""
    text = str(text or "")
    lines = []
    for para in text.replace("\r", "").split("\n"):
        words = para.split()
        if not words:
            lines.append("")
            continue
        cur = ""
        for word in words:
            cand = word if not cur else cur + " " + word
            if _text_w(font, cand) <= width:
                cur = cand
                continue
            if cur:
                lines.append(cur)
            # a word longer than the line is cut by characters
            while _text_w(font, word) > width and len(word) > 1:
                cut = len(word)
                while cut > 1 and _text_w(font, word[:cut]) > width:
                    cut -= 1
                lines.append(word[:cut])
                word = word[cut:]
            cur = word
        lines.append(cur)
    while lines and lines[-1] == "":
        lines.pop()
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1].rstrip()
        while last and _text_w(font, last + "…") > width:
            last = last[:-1]
        lines[-1] = last.rstrip() + "…"
    return lines


# --- Shapes ------------------------------------------------------------------

def rr_mask(size, box, radius, ss=SS):
    """Anti-aliased rounded rectangle mask (L) of ``size``, drawn ``ss`` times bigger."""
    w, h = size
    big = Image.new("L", (w * ss, h * ss), 0)
    x0, y0, x1, y1 = box
    ImageDraw.Draw(big).rounded_rectangle(
        (x0 * ss, y0 * ss, x1 * ss - 1, y1 * ss - 1), radius=max(0, radius * ss), fill=255)
    return big.resize((w, h), Image.Resampling.LANCZOS)


def solid(size, rgb, mask, alpha=255):
    """RGBA layer of one colour, using ``mask`` (L) scaled by ``alpha`` as alpha."""
    layer = Image.new("RGBA", size, tuple(rgb) + (0,))
    if alpha >= 255:
        layer.putalpha(mask)
    else:
        layer.putalpha(mask.point(lambda v: v * alpha // 255))
    return layer


# --- Icons (24x24 grid, stroke icons like the preview) ----------------------

ICON_ALIASES = {
    "bell": "bell", "notification": "bell", "mdi:bell": "bell",
    "info": "info", "information": "info", "mdi:information": "info",
    "warning": "warning", "alert": "warning", "mdi:alert": "warning",
    "check": "check", "ok": "check", "done": "check", "mdi:check": "check",
    "door": "door", "mdi:door": "door",
    "washer": "washer", "washing_machine": "washer", "mdi:washing-machine": "washer",
    "dishwasher": "dishwasher", "mdi:dishwasher": "dishwasher",
    "home": "home", "house": "home", "mdi:home": "home",
    "light": "light", "bulb": "light", "lightbulb": "light", "mdi:lightbulb": "light",
}
ICON_NAMES = sorted(set(ICON_ALIASES.values()))


def _arc_points(cx, cy, r, a0, a1, steps=24):
    return [(cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / steps)),
             cy + r * math.sin(math.radians(a0 + (a1 - a0) * i / steps))) for i in range(steps + 1)]


def _icon_shapes(name):
    """Return (polylines, dots, circles) in the 24 grid."""
    lines, dots, circles = [], [], []
    if name == "info":
        circles.append((12, 12, 9))
        lines.append([(12, 11), (12, 16)])
        dots.append((12, 8))
    elif name == "warning":
        lines.append([(12, 3.5), (21, 19.5), (3, 19.5), (12, 3.5)])
        lines.append([(12, 9.5), (12, 13.5)])
        dots.append((12, 16.5))
    elif name == "check":
        circles.append((12, 12, 9))
        lines.append([(8, 12.5), (11, 15.5), (16.5, 9.5)])
    elif name == "door":
        lines.append([(6, 21), (6, 3), (18, 3), (18, 21)])
        lines.append([(3, 21), (21, 21)])
        dots.append((14.5, 12))
    elif name == "washer":
        lines.append([(4, 3), (20, 3), (20, 21), (4, 21), (4, 3)])
        lines.append([(7, 6), (9, 6)])
        dots.append((12, 6))
        circles.append((12, 13.5, 5))
    elif name == "dishwasher":
        lines.append([(5, 3), (19, 3), (19, 21), (5, 21), (5, 3)])
        lines.append([(5, 8), (19, 8)])
        dots.append((8, 5.5))
        dots.append((11, 5.5))
        lines.append(_arc_points(12, 14, 3, 0, 180))
    elif name == "home":
        lines.append([(3, 11), (12, 3.5), (21, 11)])
        lines.append([(5, 9.5), (5, 20), (19, 20), (19, 9.5)])
        lines.append([(10, 20), (10, 14), (14, 14), (14, 20)])
    elif name == "light":
        lines.append(_arc_points(12, 10, 6, 135, 405))
        lines.append([(9.5, 15), (9.5, 17.5), (14.5, 17.5), (14.5, 15)])
        lines.append([(10, 21), (14, 21)])
    else:  # bell
        body = [(4, 17), (6, 15)] + _arc_points(12, 10, 6, 180, 360) + [(18, 15), (20, 17), (4, 17)]
        lines.append(body)
        lines.append(_arc_points(12, 19.5, 2, 0, 180))
        lines.append([(12, 2.5), (12, 4)])
    return lines, dots, circles


def icon_mask(name, size, stroke=1.8):
    """Stroke icon as an anti-aliased L mask of ``size`` px."""
    k = size * SS / 24.0
    big = Image.new("L", (size * SS, size * SS), 0)
    d = ImageDraw.Draw(big)
    width = max(1, int(round(stroke * k)))
    r = width / 2.0
    lines, dots, circles = _icon_shapes(name)
    for pts in lines:
        p = [(x * k, y * k) for x, y in pts]
        d.line(p, fill=255, width=width, joint="curve")
        for x, y in (p[0], p[-1]):
            d.ellipse((x - r, y - r, x + r, y + r), fill=255)
    for x, y in dots:
        x, y = x * k, y * k
        d.ellipse((x - r * 1.1, y - r * 1.1, x + r * 1.1, y + r * 1.1), fill=255)
    for cx, cy, cr in circles:
        cx, cy, cr = cx * k, cy * k, cr * k
        d.ellipse((cx - cr, cy - cr, cx + cr, cy + cr), outline=255, width=width)
    return big.resize((size, size), Image.Resampling.LANCZOS)


def resolve_icon(value):
    """Payload "icon" -> ("name", name) or ("emoji", text). Default: the bell."""
    if isinstance(value, str):
        v = value.strip()
        key = v.lower()
        if key in ICON_ALIASES:
            return "name", ICON_ALIASES[key]
        if v and len(v) <= 8 and any(ord(c) > 0x2000 for c in v):
            return "emoji", v
    return "name", "bell"


def emoji_image(text, size):
    """Colour emoji with Windows' Segoe UI Emoji, or None."""
    if os.name != "nt":
        return None
    try:
        path = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "seguiemj.ttf")
        font = ImageFont.truetype(path, size)
        img = Image.new("RGBA", (size * 2, size * 2), (0, 0, 0, 0))
        ImageDraw.Draw(img).text((size, size), text, font=font, anchor="mm", embedded_color=True)
        bbox = img.getbbox()
        if not bbox:
            return None
        img = img.crop(bbox)
        img.thumbnail((size, size), Image.Resampling.LANCZOS)
        return img
    except Exception:
        return None


# --- The card -----------------------------------------------------------------

_ANGLE_CACHE = {}


def _angle_map(size, center):
    key = (size, center)
    if key not in _ANGLE_CACHE:
        w, h = size
        cx, cy = center
        tau = 2 * math.pi
        data = [int(((math.atan2(y - cy, x - cx) + math.pi / 2) % tau) / tau * 256) % 256
                for y in range(h) for x in range(w)]
        img = Image.new("L", size)
        img.putdata(data)
        if len(_ANGLE_CACHE) > 8:
            _ANGLE_CACHE.clear()
        _ANGLE_CACHE[key] = img
    return _ANGLE_CACHE[key]


def _gradient_lut(colors, n=256, closed=True):
    stops = [hex_rgb(c) for c in colors]
    if closed:
        stops = stops + [stops[0]]
    out = []
    seg = len(stops) - 1
    for i in range(n):
        pos = i / (n - (0 if closed else 1)) * seg
        j = min(int(pos), seg - 1)
        f = pos - j
        a, b = stops[j], stops[j + 1]
        out.append(tuple(int(round(a[c] + (b[c] - a[c]) * f)) for c in range(3)))
    return out


class CardRenderer:
    """Draws one notification of style "aurora" or "glass".

    ``frame(t, progress)`` returns an RGBA image of ``size``: the card sits at
    ``card_box`` inside a transparent margin (for shadow and glow) when
    ``margin`` is True. ``t`` is seconds since the start (animation),
    ``progress`` goes from 1 to 0 over the duration (the bar at the bottom).
    """

    def __init__(self, style, dark, title, message, app_name="", time_text="",
                 icon=None, scale=1.0, corner_radius=30, palette=DEFAULT_PALETTE,
                 glow=DEFAULT_GLOW, margin=True, backdrop=False):
        self.style = "aurora" if style == "aurora" else "glass"
        self.dark = bool(dark)
        self.s = s = max(0.5, float(scale))
        self.palette = PALETTES.get(palette, PALETTES[DEFAULT_PALETTE])
        self.glow = GLOWS.get(glow, GLOWS[DEFAULT_GLOW])
        self.backdrop = bool(backdrop)
        self.app_name = str(app_name or "")
        self.time_text = str(time_text or "")
        self.icon = icon

        # Layout (CSS px of the preview, times scale)
        self.cw = int(round(CARD_WIDTH * s))
        self.pad_x = int(round(16 * s))
        self.pad_top = int(round(14 * s))
        self.icon_box = int(round(40 * s))
        self.text_x = self.pad_x + self.icon_box + int(round(12 * s))
        self.text_w = self.cw - self.text_x - self.pad_x
        self.f_meta = load_font(12 * s)
        self.f_title = load_font(15 * s, bold=True)
        self.f_msg = load_font(14 * s)
        self.meta_h = int(round(17 * s))
        self.title_h = int(round(21 * s))
        self.line_h = int(round(19 * s))
        self.title_lines = wrap_text(title, self.f_title, self.text_w, 1) or [""]
        self.msg_lines = wrap_text(message, self.f_msg, self.text_w, 3)
        content = self.pad_top + self.meta_h + self.title_h + len(self.msg_lines) * self.line_h
        self.ch = max(self.pad_top + self.icon_box + int(round(22 * s)), content + int(round(18 * s)))
        # corner_radius 30 (the old default) -> 18 px, the slider still works
        self.radius = max(0, min(float(corner_radius) * 0.6 * s, self.ch / 2.0))

        self.m = int(round(36 * s)) if margin else 0
        self.size = (self.cw + 2 * self.m, self.ch + 2 * self.m)
        self.card_box = (self.m, self.m, self.m + self.cw, self.m + self.ch)

        if self.style == "glass":
            self.bg = (0x20, 0x21, 0x2b) if self.dark else (0xf7, 0xf8, 0xfb)
        else:
            self.bg = (0x15, 0x16, 0x1f) if self.dark else (0xf3, 0xf4, 0xfa)
        self.fg = (255, 255, 255) if self.dark else (0x14, 0x15, 0x1b)
        self._built = False

    @property
    def matte(self):
        """Colour to flatten edges on when there is no per-pixel alpha."""
        return self.bg

    def set_backdrop(self, value):
        if bool(value) != self.backdrop:
            self.backdrop = bool(value)
            self._built = False

    # -- static layers, built once per notification
    def _build(self):
        s, cw, ch, m = self.s, self.cw, self.ch, self.m
        csize = (cw, ch)
        self.card_mask = rr_mask(csize, (0, 0, cw, ch), self.radius)

        # Shadow under the card (only with a margin around it)
        self.shadow = None
        if m:
            sm = Image.new("L", self.size, 0)
            off = int(round(10 * s))
            ImageDraw.Draw(sm).rounded_rectangle(
                (m, m + off, m + cw, m + ch + off - int(round(4 * s))), radius=self.radius, fill=255)
            sm = sm.filter(ImageFilter.GaussianBlur(14 * s))
            self.shadow = solid(self.size, (0, 0, 0), sm, 0x80 if self.style == "glass" else 0x70)

        if self.style == "glass":
            if self.backdrop:
                fill_a = 0xb0 if self.dark else 0xbf
            else:
                fill_a = 0xeb if self.dark else 0xf0
            self.fill = solid(csize, self.bg, self.card_mask, fill_a)
            inner = rr_mask(csize, (1.5 * s, 1.5 * s, cw - 1.5 * s, ch - 1.5 * s), max(0, self.radius - 1.5 * s))
            self.border_mask = ImageChops.subtract(self.card_mask, inner)
            gm = Image.new("L", self.size, 0)
            e = 4 * s
            ImageDraw.Draw(gm).rounded_rectangle(
                (m - e, m - e, m + cw + e, m + ch + e), radius=self.radius + e, fill=255)
            gm = gm.filter(ImageFilter.GaussianBlur(12 * s))
            self.glow_mask = gm.point(lambda v: int(v * self.glow))
            self.angle = _angle_map(self.size, (m + cw // 2, m + ch // 2))
            self.lut = _gradient_lut(RAINBOW)
            bar = Image.new("RGB", (len(self.lut), 1))
            bar.putdata(_gradient_lut(RAINBOW, closed=False))
            self.bar_grad = bar
        else:
            inner = rr_mask(csize, (1 * s, 1 * s, cw - 1 * s, ch - 1 * s), max(0, self.radius - 1 * s))
            ring = ImageChops.subtract(self.card_mask, inner)
            self.inner_border = solid(csize, (255, 255, 255) if self.dark else (0, 0, 0), ring,
                                      0x1a if self.dark else 0x0f)
            self.blob_r = r = int(max(cw, ch) * 0.55)
            small = 64
            radial = Image.new("L", (small, small))
            c = (small - 1) / 2.0
            amax = 0x99 if self.dark else 0x70
            radial.putdata([int(max(0.0, 1 - math.hypot(x - c, y - c) / c) * amax)
                            for y in range(small) for x in range(small)])
            radial = radial.resize((2 * r, 2 * r), Image.Resampling.BICUBIC)
            self.blobs = []
            for col in self.palette:
                rgb = hex_rgb(col)
                if self.dark:  # additive ("lighter"): premultiplied colour
                    self.blobs.append(Image.merge("RGB", [radial.point(lambda v, k=k: v * k // 255) for k in rgb]))
                else:
                    self.blobs.append(solid((2 * r, 2 * r), rgb, radial))

        self.content = self._content_layer(csize)
        self._built = True

    def _content_layer(self, csize):
        s = self.s
        layer = Image.new("RGBA", csize, (0, 0, 0, 0))
        # Icon tile
        x0, y0, b = self.pad_x, self.pad_top, self.icon_box
        tile = rr_mask(csize, (x0, y0, x0 + b, y0 + b), 12 * s)
        if self.style == "glass":
            tcol, ta = ((255, 255, 255), 0x1c) if self.dark else ((0, 0, 0), 0x0d)
        else:
            tcol, ta = ((255, 255, 255), 0x22) if self.dark else ((255, 255, 255), 0xaa)
        layer.alpha_composite(solid(csize, tcol, tile, ta))
        isz = int(round(22 * s))
        ix, iy = x0 + (b - isz) // 2, y0 + (b - isz) // 2
        kind, val = resolve_icon(self.icon)
        emoji = emoji_image(val, isz) if kind == "emoji" else None
        if emoji is not None:
            layer.alpha_composite(emoji, (ix + (isz - emoji.width) // 2, iy + (isz - emoji.height) // 2))
        else:
            name = val if kind == "name" else "bell"
            mask = Image.new("L", csize, 0)
            mask.paste(icon_mask(name, isz), (ix, iy))
            layer.alpha_composite(solid(csize, self.fg, mask))

        # Texts: one L mask per opacity, then coloured
        def text_layer(items, alpha):
            mask = Image.new("L", csize, 0)
            d = ImageDraw.Draw(mask)
            for (x, y), txt, font, anchor in items:
                d.text((x, y), txt, font=font, fill=255, anchor=anchor)
            layer.alpha_composite(solid(csize, self.fg, mask, alpha))

        tx = self.text_x
        y = self.pad_top
        meta = [((tx, y), self.app_name, self.f_meta, "la")]
        if self.time_text:
            meta.append(((self.cw - self.pad_x, y), self.time_text, self.f_meta, "ra"))
        text_layer(meta, int(255 * 0.75))
        y += self.meta_h
        text_layer([((tx, y), self.title_lines[0], self.f_title, "la")], 255)
        y += self.title_h
        text_layer([((tx, y + i * self.line_h), line, self.f_msg, "la")
                    for i, line in enumerate(self.msg_lines)], int(255 * 0.85))

        # Progress bar track
        bx0, bx1 = self.pad_x, self.cw - self.pad_x
        by1 = self.ch - int(round(7 * s))
        by0 = by1 - max(2, int(round(3 * s)))
        self.bar_box = (bx0, by0, bx1, by1)
        track = rr_mask(csize, self.bar_box, 2 * s, ss=2)
        tcol = (255, 255, 255) if self.dark else (0, 0, 0)
        if self.style == "glass":
            ta = 0x1a
        else:
            ta = 0x22 if self.dark else 0x1a
        layer.alpha_composite(solid(csize, tcol, track, ta))
        return layer

    # -- animated parts
    def _conic(self, t):
        off = int((t / 6.0) * 256) % 256
        lut = self.lut
        shifted = [lut[(i - off) % 256] for i in range(256)]
        chans = [self.angle.point([c[k] for c in shifted]) for k in range(3)]
        return Image.merge("RGB", chans)

    def _aurora(self, t):
        cw, ch, r = self.cw, self.ch, self.blob_r
        base = Image.new("RGB", (cw, ch), self.bg)
        sp = t * 0.25
        pts = [
            (0.2 + 0.15 * math.sin(sp), 0.3 + 0.3 * math.cos(sp * 0.7)),
            (0.6 + 0.2 * math.cos(sp * 0.8), 0.7 + 0.25 * math.sin(sp * 0.9)),
            (0.85 + 0.12 * math.sin(sp * 1.1 + 1), 0.25 + 0.3 * math.cos(sp * 0.6 + 2)),
        ]
        for blob, (px, py) in zip(self.blobs, pts):
            x, y = int(px * cw) - r, int(py * ch) - r
            bx, by = max(0, -x), max(0, -y)
            dx, dy = max(0, x), max(0, y)
            w = min(cw - dx, blob.width - bx)
            h = min(ch - dy, blob.height - by)
            if w <= 0 or h <= 0:
                continue
            piece = blob.crop((bx, by, bx + w, by + h))
            if self.dark:
                region = base.crop((dx, dy, dx + w, dy + h))
                base.paste(ImageChops.add(region, piece), (dx, dy))
            else:
                base.paste(piece, (dx, dy), piece)
        card = base.convert("RGBA")
        card.putalpha(self.card_mask)
        return card

    def _bar(self, card, progress):
        progress = max(0.0, min(1.0, float(progress)))
        x0, y0, x1, y1 = self.bar_box
        w = int(round((x1 - x0) * progress))
        if w <= 0:
            return
        h = y1 - y0
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=h / 2.0, fill=255)
        if self.style == "glass":
            piece = self.bar_grad.resize((x1 - x0, h)).crop((0, 0, w, h)).convert("RGBA")
            piece.putalpha(mask)
        else:
            col, a = ((255, 255, 255), 0xcc) if self.dark else ((0x14, 0x15, 0x1b), 0xaa)
            piece = solid((w, h), col, mask, a)
        card.alpha_composite(piece, (x0, y0))

    def frame(self, t, progress=1.0):
        if not self._built:
            self._build()
        out = Image.new("RGBA", self.size, (0, 0, 0, 0))
        if self.shadow is not None:
            out.alpha_composite(self.shadow)
        m = self.m
        if self.style == "glass":
            colors = self._conic(t)
            glow = colors.convert("RGBA")
            glow.putalpha(self.glow_mask)
            out.alpha_composite(glow)
            card = self.fill.copy()
            border = colors.crop(self.card_box).convert("RGBA")
            border.putalpha(self.border_mask)
            card.alpha_composite(border)
        else:
            card = self._aurora(t)
            card.alpha_composite(self.inner_border)
        card.alpha_composite(self.content)
        self._bar(card, progress)
        out.alpha_composite(card, (m, m))
        return out


def flatten_on_key(img, matte, key=(0, 0, 1)):
    """For windows without per-pixel alpha (-transparentcolor): edges are
    blended on ``matte`` (not on the key colour, so no dark fringe) and
    pixels under 50% alpha become the key colour."""
    a = img.getchannel("A")
    base = Image.new("RGB", img.size, matte)
    base.paste(img.convert("RGB"), (0, 0), a)
    keyed = Image.new("RGB", img.size, key)
    return Image.composite(base, keyed, a.point(lambda v: 255 if v >= 128 else 0))


# --- Windows helpers (ctypes; only called when os.name == 'nt') ------------

_WIN = None


def _win32():
    global _WIN
    if _WIN is not None:
        return _WIN
    import ctypes
    from ctypes import wintypes

    class BLENDFUNCTION(ctypes.Structure):
        _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                    ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD),
                    ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
                    ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
                    ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]

    class ACCENT_POLICY(ctypes.Structure):
        _fields_ = [("AccentState", ctypes.c_int), ("AccentFlags", ctypes.c_int),
                    ("GradientColor", ctypes.c_uint), ("AnimationId", ctypes.c_int)]

    class WINCOMPATTRDATA(ctypes.Structure):
        _fields_ = [("Attribute", ctypes.c_int), ("Data", ctypes.c_void_p), ("SizeOfData", ctypes.c_size_t)]

    u = ctypes.WinDLL("user32", use_last_error=True)
    g = ctypes.WinDLL("gdi32")
    u.GetDC.restype = wintypes.HDC
    u.GetDC.argtypes = [wintypes.HWND]
    u.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    u.GetAncestor.restype = wintypes.HWND
    u.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    u.GetWindowLongW.restype = wintypes.LONG
    u.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    u.SetWindowLongW.restype = wintypes.LONG
    u.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
    u.UpdateLayeredWindow.restype = wintypes.BOOL
    u.UpdateLayeredWindow.argtypes = [wintypes.HWND, wintypes.HDC, ctypes.POINTER(wintypes.POINT),
                                      ctypes.POINTER(wintypes.SIZE), wintypes.HDC,
                                      ctypes.POINTER(wintypes.POINT), wintypes.DWORD,
                                      ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD]
    u.SetWindowRgn.restype = ctypes.c_int
    u.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HRGN, wintypes.BOOL]
    u.SetWindowCompositionAttribute.restype = wintypes.BOOL
    u.SetWindowCompositionAttribute.argtypes = [wintypes.HWND, ctypes.c_void_p]
    g.CreateCompatibleDC.restype = wintypes.HDC
    g.CreateCompatibleDC.argtypes = [wintypes.HDC]
    g.CreateDIBSection.restype = wintypes.HBITMAP
    g.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT,
                                   ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
    g.SelectObject.restype = wintypes.HGDIOBJ
    g.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    g.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    g.DeleteDC.argtypes = [wintypes.HDC]
    g.CreateRoundRectRgn.restype = wintypes.HRGN
    g.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6

    class NS:
        pass
    ns = NS()
    ns.ctypes, ns.wintypes, ns.u, ns.g = ctypes, wintypes, u, g
    ns.BLENDFUNCTION, ns.BITMAPINFO = BLENDFUNCTION, BITMAPINFO
    ns.ACCENT_POLICY, ns.WINCOMPATTRDATA = ACCENT_POLICY, WINCOMPATTRDATA
    try:
        ns.dwm = ctypes.WinDLL("dwmapi")
    except Exception:
        ns.dwm = None
    _WIN = ns
    return ns


GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080


def root_hwnd(widget_id):
    """Top-level HWND of a Tk window (winfo_id gives the inner one)."""
    w = _win32()
    hwnd = w.u.GetAncestor(widget_id, 2)  # GA_ROOT
    return hwnd or widget_id


class LayeredWindow:
    """Shows RGBA frames with per-pixel alpha (UpdateLayeredWindow).

    The window must never get SetLayeredWindowAttributes (Tk's -alpha):
    UpdateLayeredWindow fails on such a window.
    """

    def __init__(self, hwnd, size):
        w = self.w = _win32()
        ct = w.ctypes
        self.hwnd = hwnd
        self.width, self.height = size
        ex = w.u.GetWindowLongW(hwnd, GWL_EXSTYLE)
        w.u.SetWindowLongW(hwnd, GWL_EXSTYLE, ex | WS_EX_LAYERED | WS_EX_TOOLWINDOW)
        self.screen = w.u.GetDC(None)
        self.mem = w.g.CreateCompatibleDC(self.screen)
        bmi = w.BITMAPINFO()
        bmi.bmiHeader.biSize = ct.sizeof(bmi.bmiHeader)
        bmi.bmiHeader.biWidth = self.width
        bmi.bmiHeader.biHeight = -self.height  # top-down
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0  # BI_RGB
        self.bits = ct.c_void_p()
        self.bmp = w.g.CreateDIBSection(self.mem, ct.byref(bmi), 0, ct.byref(self.bits), None, 0)
        if not self.bmp or not self.bits.value:
            self.close()
            raise OSError("CreateDIBSection failed")
        self.old = w.g.SelectObject(self.mem, self.bmp)

    def present(self, img, x, y, alpha=1.0):
        w = self.w
        ct, wt = w.ctypes, w.wintypes
        r, g, b, a = img.split()
        # premultiplied BGRA, as UpdateLayeredWindow wants
        data = Image.merge("RGBA", (ImageChops.multiply(b, a), ImageChops.multiply(g, a),
                                    ImageChops.multiply(r, a), a)).tobytes()
        ct.memmove(self.bits, data, len(data))
        blend = w.BLENDFUNCTION(0, 0, max(0, min(255, int(alpha * 255))), 1)  # AC_SRC_OVER, AC_SRC_ALPHA
        ok = w.u.UpdateLayeredWindow(self.hwnd, self.screen, ct.byref(wt.POINT(int(x), int(y))),
                                     ct.byref(wt.SIZE(self.width, self.height)), self.mem,
                                     ct.byref(wt.POINT(0, 0)), 0, ct.byref(blend), 2)  # ULW_ALPHA
        return bool(ok)

    def close(self):
        w = self.w
        try:
            if getattr(self, "old", None):
                w.g.SelectObject(self.mem, self.old)
                self.old = None
            if getattr(self, "bmp", None):
                w.g.DeleteObject(self.bmp)
                self.bmp = None
            if getattr(self, "mem", None):
                w.g.DeleteDC(self.mem)
                self.mem = None
            if getattr(self, "screen", None):
                w.u.ReleaseDC(None, self.screen)
                self.screen = None
        except Exception:
            pass


def make_acrylic_backdrop(hwnd, size, radius, dark):
    """Acrylic blur behind a borderless window, clipped to a rounded rectangle.
    Returns True if Windows accepted it (Windows 10 1803+ / 11)."""
    w = _win32()
    ct = w.ctypes
    width, height = size
    rgn = w.g.CreateRoundRectRgn(1, 1, width, height, int(radius * 2), int(radius * 2))
    if rgn:
        w.u.SetWindowRgn(hwnd, rgn, True)  # the system owns the region now
    if w.dwm is not None:
        try:  # no extra rounding/border from Windows 11: the region does it
            pref = ct.c_int(1)  # DWMWCP_DONOTROUND
            w.dwm.DwmSetWindowAttribute(ct.c_void_p(hwnd), 33, ct.byref(pref), ct.sizeof(pref))
        except Exception:
            pass
    tint = 0x20 if dark else 0x10
    base = 0x2b2120 if dark else 0xfbf8f7  # 0xBBGGRR
    policy = w.ACCENT_POLICY(4, 0, (tint << 24) | base, 0)  # ACCENT_ENABLE_ACRYLICBLURBEHIND
    data = w.WINCOMPATTRDATA(19, ct.cast(ct.pointer(policy), ct.c_void_p), ct.sizeof(policy))  # WCA_ACCENT_POLICY
    return bool(w.u.SetWindowCompositionAttribute(hwnd, ct.byref(data)))


def work_area():
    """(left, top, right, bottom) of the work area (taskbar excluded) of the
    primary monitor, in real pixels; None if not on Windows or on error."""
    if os.name != "nt":
        return None
    try:
        w = _win32()
        ct, wt = w.ctypes, w.wintypes

        class MONITORINFO(ct.Structure):
            _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT),
                        ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]

        w.u.MonitorFromPoint.restype = wt.HMONITOR
        w.u.MonitorFromPoint.argtypes = [wt.POINT, wt.DWORD]
        w.u.GetMonitorInfoW.restype = wt.BOOL
        w.u.GetMonitorInfoW.argtypes = [wt.HMONITOR, ct.POINTER(MONITORINFO)]
        # the primary monitor is the one at (0, 0)
        monitor = w.u.MonitorFromPoint(wt.POINT(0, 0), 1)  # MONITOR_DEFAULTTOPRIMARY
        info = MONITORINFO()
        info.cbSize = ct.sizeof(info)
        if not w.u.GetMonitorInfoW(monitor, ct.byref(info)):
            return None
        r = info.rcWork
        if r.right <= r.left or r.bottom <= r.top:
            return None
        return (r.left, r.top, r.right, r.bottom)
    except Exception:
        return None
