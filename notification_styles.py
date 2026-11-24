"""Notification styles drawn with Pillow (glass, aurora, classic, static,
ambient, poster, vinyl: one layout for all, since 1.2.0), plus the few
Windows helpers they need (per-pixel alpha layered window, app theme from
the registry; acrylic backdrop helper kept unused).

This module never imports tkinter: the drawing part runs anywhere Pillow
runs (it is also used to render preview PNGs off Windows). Everything that
touches Windows is guarded by ``os.name == 'nt'`` and try/except.
"""
import colorsys
import hashlib
import math
import os

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageStat

# --- Config values -----------------------------------------------------------

STYLES = ("glass", "aurora", "classic", "static", "ambient", "poster", "vinyl")
DEFAULT_STYLE = "glass"
PALETTES = {
    "night": ("#6d5dfc", "#2f8cff", "#22c3d6"),
    "sunset": ("#ff6b8b", "#ff9a5a", "#b45cff"),
    "forest": ("#2bb673", "#1fa2a8", "#7bd88f"),
}
DEFAULT_PALETTE = "night"
# glow around the glass card: (spread px, blur px, opacity)
GLOWS = {"full": (7, 16, 0.85), "soft": (4, 12, 0.35)}
LIGHT_FULL_GLOW = 0.5  # opacity of the full glow with the light theme
DEFAULT_GLOW = "soft"
THEMES = ("dark", "light", "system")
RAINBOW = ("#ff5f6d", "#ffc371", "#47e5bc", "#4facfe", "#a66cff")

SS = 4  # supersampling factor for shapes (masks, icons)
CARD_WIDTH = 372
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

# Windows fonts first (Segoe UI, Georgia for the Vinyl title), then Linux
# fallbacks so that previews can be rendered off Windows.
_FONT_FILES = {
    "regular": (["segoeui.ttf", "arial.ttf"],
                ["NotoSans-Regular.ttf", "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
                 "DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]),
    "semibold": (["seguisb.ttf", "segoeuib.ttf", "arialbd.ttf"],
                 ["NotoSans-SemiBold.ttf", "NotoSans-Bold.ttf", "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
                  "DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]),
    "bold": (["segoeuib.ttf", "seguisb.ttf", "arialbd.ttf"],
             ["NotoSans-Bold.ttf", "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
              "DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]),
    "serif": (["georgiab.ttf", "timesbd.ttf", "segoeuib.ttf"],
              ["NotoSerif-Bold.ttf", "/usr/share/fonts/truetype/noto/NotoSerif-Bold.ttf",
               "DejaVuSerif-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"]),
}


def _font_files(kind):
    win, other = _FONT_FILES.get(kind, _FONT_FILES["regular"])
    files = []
    if os.name == "nt":
        fonts = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
        files += [os.path.join(fonts, n) for n in win]
    return files + other


def load_font(size, bold=False, kind=None):
    """Font of ``size`` px; ``kind`` is regular, semibold, bold or serif."""
    kind = kind or ("bold" if bold else "regular")
    size = max(6, int(round(size)))
    key = (size, kind)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    font = None
    for path in _font_files(kind):
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
#
# One layout for every style (spacing, text hierarchy, corners and shadow
# taken from the Spotify widget 0.3.0): a 52 px icon tile filled with the
# accent colour, a small upper-case line (app name) with the time on the
# right, a bold title on up to 2 lines, the message on up to 3 lines, and a
# 5 px bar with the time left. Each style only changes the background and the
# colours; "poster" has no tile (small icon in the app line) and "vinyl" has a
# sleeve with a record coming out of it instead of the tile.

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


def rgba(col, a=1.0):
    c = hex_rgb(col) if isinstance(col, str) else tuple(col[:3])
    return c + (int(round(255 * a)),)


def linear_gradient(size, stops, angle_deg=180):
    """RGBA linear gradient; ``stops`` = [(pos 0..1, (r, g, b, a))];
    180 = top to bottom, 90 = left to right (like CSS)."""
    w, h = size
    n = 512
    lut = []
    for i in range(n):
        p = i / (n - 1)
        for j in range(len(stops) - 1):
            p0, c0 = stops[j]
            p1, c1 = stops[j + 1]
            if p <= p1 or j == len(stops) - 2:
                f = 0 if p1 == p0 else max(0.0, min(1.0, (p - p0) / (p1 - p0)))
                lut.append(tuple(int(round(c0[k] + (c1[k] - c0[k]) * f)) for k in range(4)))
                break
    a = math.radians(angle_deg)
    dx, dy = math.sin(a), -math.cos(a)
    span = abs(w * dx) + abs(h * dy)
    sw, sh = max(2, w // 4), max(2, h // 4)
    img = Image.new("RGBA", (sw, sh))
    px = []
    for y in range(sh):
        for x in range(sw):
            X, Y = (x + .5) / sw * w - w / 2, (y + .5) / sh * h - h / 2
            p = (X * dx + Y * dy) / span + 0.5
            px.append(lut[int(max(0.0, min(1.0, p)) * (n - 1))])
    img.putdata(px)
    return img.resize((w, h), Image.Resampling.BICUBIC)


def radial_spot(size, rx, ry, cx, cy, col, a):
    """Soft ellipse (fading towards its edge) as an RGBA layer of ``size``."""
    small = 96
    r = Image.new("L", (small, small))
    c = (small - 1) / 2.0
    r.putdata([int(max(0.0, 1 - math.hypot(x - c, y - c) / c) ** 1.2 * 255 * a)
               for y in range(small) for x in range(small)])
    r = r.resize((max(2, int(2 * rx)), max(2, int(2 * ry))), Image.Resampling.BICUBIC)
    layer = Image.new("RGBA", size, rgba(col)[:3] + (0,))
    m = Image.new("L", size, 0)
    m.paste(r, (int(cx - rx), int(cy - ry)))
    layer.putalpha(m)
    return layer


def text_mask(size, items):
    """L mask with texts; items: (x, y, text, font, anchor, letter_spacing_px)."""
    m = Image.new("L", size, 0)
    d = ImageDraw.Draw(m)
    for x, y, txt, f, anchor, sp in items:
        if sp:
            if anchor.startswith("r"):
                x -= sum(_text_w(f, ch) + sp for ch in txt) - sp
            for ch in txt:
                d.text((x, y), ch, font=f, fill=255, anchor="la")
                x += _text_w(f, ch) + sp
        else:
            d.text((x, y), txt, font=f, fill=255, anchor=anchor)
    return m


def _paint(layer, mask, col):
    layer.alpha_composite(solid(layer.size, col[:3], mask, col[3]))


# Ambient: generated "covers", chosen from the icon (same icon = same colours)
AMBIENT = {
    "warm": dict(base="#2a1622", c1="#ef7d3c", c2="#1f6f78", c3="#c2416b", accent="#f6c453",
                 accent_l="#c2416b", tint="#fbf1ea"),
    "water": dict(base="#0f2130", c1="#2f9fd0", c2="#1f6f78", c3="#7b5cff", accent="#7fd4ff",
                  accent_l="#1f78b4", tint="#eaf4fb"),
    "alarm": dict(base="#2a1216", c1="#e5484d", c2="#7a1f3d", c3="#ff9a5a", accent="#ffb35a",
                  accent_l="#c7372f", tint="#fdeeea"),
    "green": dict(base="#0f241c", c1="#2bb673", c2="#1f5f78", c3="#c9d65a", accent="#9be37a",
                  accent_l="#1f8a55", tint="#ecf7ef"),
    "night": dict(base="#161a33", c1="#6d5dfc", c2="#1f3f7a", c3="#e06bb0", accent="#b9a8ff",
                  accent_l="#5b46e0", tint="#efedfb"),
}
AMBIENT_BY_ICON = {"washer": "water", "dishwasher": "water", "warning": "alarm", "door": "warm",
                   "home": "green", "check": "green", "light": "warm", "info": "night", "bell": "night"}
POSTER_SCENES = ("sunset", "mountains", "waves")
POSTER_BY_ICON = {"washer": "waves", "dishwasher": "waves", "warning": "sunset", "door": "mountains",
                  "home": "mountains", "check": "mountains", "light": "sunset", "info": "waves",
                  "bell": "sunset"}


def pick_by_icon(mapping, icon, title, choices):
    """Value for a known icon name (no icon: the bell's); otherwise (an emoji,
    an unknown icon) a choice that depends only on the title, so the same
    title always gets the same look."""
    key = icon.strip().lower() if isinstance(icon, str) else ""
    if not key:
        return mapping["bell"]
    if key in ICON_ALIASES:
        return mapping[ICON_ALIASES[key]]
    h = int(hashlib.md5(str(title or "").encode("utf-8")).hexdigest(), 16)
    return choices[h % len(choices)]


def _colours(style, dark, amb):
    """Text and accent colours of a style, like the CSS variables of the widget:
    fg, muted, muted2 (texts), accent (tile), on_accent (icon in the tile),
    accent_text (app line), track/fill (bar), edge (1 px border)."""
    W, K = "#ffffff", "#14151b"
    if style == "glass":
        if dark:
            return dict(fg=rgba(W), muted=rgba(W, .78), muted2=rgba(W, .55), accent=rgba(W, .95),
                        on_accent=rgba("#16171f"), accent_text=rgba("#8fd3ff"), track=rgba(W, .14),
                        fill="rainbow", edge=None)
        return dict(fg=rgba(K), muted=rgba(K, .75), muted2=rgba(K, .55), accent=rgba(K),
                    on_accent=rgba(W), accent_text=rgba("#2f6fe0"), track=rgba("#000000", .10),
                    fill="rainbow", edge=None)
    if style == "aurora":
        if dark:
            return dict(fg=rgba(W), muted=rgba(W, .82), muted2=rgba(W, .6), accent=rgba(W, .95),
                        on_accent=rgba("#15161f"), accent_text=rgba(W, .85), track=rgba(W, .18),
                        fill=rgba(W, .9), edge=rgba(W, .10))
        return dict(fg=rgba(K), muted=rgba(K, .78), muted2=rgba(K, .58), accent=rgba(K),
                    on_accent=rgba(W), accent_text=rgba(K), track=rgba("#000000", .12),
                    fill=rgba(K), edge=rgba("#000000", .06))
    if style == "classic":
        if dark:
            return dict(fg=rgba(W), muted=rgba(W, .85), muted2=rgba(W, .62), accent=rgba(W, .95),
                        on_accent=rgba("#1b1b22"), accent_text=rgba(W, .9), track=rgba(W, .2),
                        fill=rgba(W, .92), edge=rgba(W, .10))
        return dict(fg=rgba(K), muted=rgba(K, .8), muted2=rgba(K, .6), accent=rgba(K, .9),
                    on_accent=rgba(W), accent_text=rgba(K, .8), track=rgba("#000000", .12),
                    fill=rgba(K, .85), edge=rgba("#000000", .06))
    if style == "static":  # neutral grey tile and bar
        if dark:
            return dict(fg=rgba(W), muted=rgba("#a1a1a6"), muted2=rgba("#8e8e93"), accent=rgba("#48484a"),
                        on_accent=rgba(W), accent_text=rgba("#aeaeb2"), track=rgba(W, .14),
                        fill=rgba("#aeaeb2"), edge=rgba("#3a3a3c"))
        return dict(fg=rgba("#000000"), muted=rgba("#3c3c43"), muted2=rgba("#6c6c70"), accent=rgba("#636366"),
                    on_accent=rgba(W), accent_text=rgba("#636366"), track=rgba("#000000", .10),
                    fill=rgba("#636366"), edge=rgba("#c6c6c8"))
    if style == "ambient":
        p = AMBIENT[amb]
        if dark:
            return dict(fg=rgba(W), muted=rgba(W, .82), muted2=rgba(W, .6), accent=rgba(p["accent"]),
                        on_accent=rgba(p["base"]), accent_text=rgba(p["accent"]), track=rgba(W, .18),
                        fill=rgba(p["accent"]), edge=rgba(W, .10))
        acc = hex_rgb(p["accent_l"])
        return dict(fg=rgba("#1d1a1f"), muted=rgba("#1d1a1f", .78), muted2=rgba("#1d1a1f", .58),
                    accent=rgba(acc), on_accent=rgba(W), accent_text=rgba(acc), track=rgba("#000000", .14),
                    fill=rgba(acc), edge=rgba("#000000", .06))
    if style == "poster":
        if dark:
            return dict(fg=rgba(W), muted=rgba(W, .9), muted2=rgba(W, .75), accent=rgba(W),
                        on_accent=rgba("#111111"), accent_text=rgba(W), track=rgba(W, .28),
                        fill=rgba(W), edge=rgba(W, .10))
        return dict(fg=rgba(K), muted=rgba(K, .86), muted2=rgba(K, .7), accent=rgba(K),
                    on_accent=rgba(W), accent_text=rgba(K), track=rgba("#000000", .16),
                    fill=rgba(K), edge=rgba("#000000", .08))
    # vinyl
    if dark:
        C = "#f4ece4"
        return dict(fg=rgba(C), muted=rgba(C, .78), muted2=rgba(C, .55), accent=rgba("#ef7d3c"),
                    on_accent=rgba("#1a1210"), accent_text=rgba("#f2a06a"), track=rgba(C, .16),
                    fill=rgba("#ef7d3c"), edge=rgba(W, .07))
    C = "#2a1d16"
    return dict(fg=rgba(C), muted=rgba(C, .78), muted2=rgba(C, .55), accent=rgba("#ef7d3c"),
                on_accent=rgba(W), accent_text=rgba("#c2571d"), track=rgba(C, .14),
                fill=rgba("#ef7d3c"), edge=rgba("#000000", .07))


# --- Backgrounds -----------------------------------------------------------------

_RAINBOW_CACHE = {}


def rainbow_base(dark, size):
    """The fluid rainbow of the classic style (same waves as before 1.2.0),
    ``size`` big so that a card-sized window can move over it."""
    key = (bool(dark), size)
    if key not in _RAINBOW_CACHE:
        w, h = 150, 150
        img = Image.new("RGB", (w, h))
        p = img.load()
        for x in range(w):
            for y in range(h):
                nx, ny = x / 25.0, y / 25.0
                v = math.sin(nx + ny) + math.sin(nx * 0.6 - ny * 1.2) + math.cos(nx * 0.9 + ny * 0.7)
                hue = ((v + 3) / 6.0 * 1.5) % 1.0
                if dark:
                    r, g, b = colorsys.hsv_to_rgb(hue, 0.65, 0.35)
                else:
                    r, g, b = colorsys.hsv_to_rgb(hue, 0.45, 0.98)
                p[x, y] = (int(r * 255), int(g * 255), int(b * 255))
        if len(_RAINBOW_CACHE) > 4:
            _RAINBOW_CACHE.clear()
        _RAINBOW_CACHE[key] = img.resize(size, Image.Resampling.BICUBIC)
    return _RAINBOW_CACHE[key]


def ambient_background(size, dark, amb):
    w, h = size
    p = AMBIENT[amb]
    k = 1.414
    if dark:
        out = Image.new("RGBA", size, rgba(p["base"]))
        out.alpha_composite(radial_spot(size, .60 * k * w, .60 * k * h, 0, 0, p["c1"], .85))
        out.alpha_composite(radial_spot(size, .65 * k * w, .65 * k * h, w, h, p["c2"], .95))
        out.alpha_composite(radial_spot(size, .55 * k * w, .55 * k * h, w, 0, p["c3"], .7))
        out.alpha_composite(linear_gradient(size, [(0, (0, 0, 0, 46)), (1, (0, 0, 0, 77))]))
        return out
    out = Image.new("RGBA", size, rgba(p["tint"]))
    out.alpha_composite(radial_spot(size, .60 * k * w, .60 * k * h, 0, 0, p["c1"], .30))
    out.alpha_composite(radial_spot(size, .65 * k * w, .65 * k * h, w, h, p["c2"], .28))
    out.alpha_composite(radial_spot(size, .55 * k * w, .55 * k * h, w, 0, p["c3"], .25))
    return out


# Poster scenes: (dark colours, light colours)
_SCENE_COLOURS = {
    "sunset": ({"sky": ("#2b1640", "#c2416b", "#ef7d3c"), "sun": "#f6c453", "sea": ("#1f6f78", "#0c2c33")},
               {"sky": ("#ffe3cf", "#ffbf9a", "#ff9e7a"), "sun": "#ffd66b", "sea": ("#8fd0d6", "#5fb3bd")}),
    "mountains": ({"sky": ("#0f1b3d", "#2f4f8f", "#3e64a8"), "moon": "#f4ece4", "far": "#1d2d5a",
                   "mid": "#2bb673", "near": "#1a7f55", "stars": True},
                  {"sky": ("#d4e6ff", "#b3cff5", "#a2c2ef"), "moon": "#fff4d6", "far": "#8fa8d8",
                   "mid": "#7fd6a2", "near": "#4fb37f", "stars": False}),
    "waves": ({"sky": ("#0d2b4a", "#1f78b4"), "waves": ("#2f9fd0", "#47c1d6", "#7fd4ff", "#1f6f78", "#0f3a5a"),
               "sun": "#f6c453"},
              {"sky": ("#dff2ff", "#a6d8f5"), "waves": ("#7fc6e8", "#a8e0ef", "#c9efff", "#5fb3bd", "#3f8fb0"),
               "sun": "#ffd66b"}),
}


def _fit_disc(cy, r, clear, limit, min_r):
    """Sun or moon: moved down (and made smaller if needed) so that its top
    stays below ``clear`` (the texts) and its bottom above ``limit`` (the
    bar). Returns (cy, r), r = 0 when there is no room at all."""
    if cy - r < clear:
        cy = clear + r
    if cy + r > limit:
        r = (limit - clear) / 2.0
        cy = clear + r
    return (cy, r) if r >= min_r else (cy, 0)


def poster_background(size, scene, dark, s, clear_y=0, limit_y=None):
    """Sharp abstract illustration drawn twice as big, then reduced.
    The sun or moon never goes under the texts (above ``clear_y``) nor under
    the bar (below ``limit_y``), in card pixels."""
    w, h = size
    W, H = w * 2, h * 2
    clear = clear_y * 2
    limit = (h if limit_y is None else limit_y) * 2
    min_r = 5 * s * 2
    c = _SCENE_COLOURS.get(scene, _SCENE_COLOURS["sunset"])[0 if dark else 1]
    if scene == "mountains":
        sky = c["sky"]
        img = linear_gradient((W, H), [(0, rgba(sky[0])), (.7, rgba(sky[1])), (1, rgba(sky[2]))])
        d = ImageDraw.Draw(img)
        if c["stars"]:
            for i, (sx, sy) in enumerate([(.08, .12), (.22, .3), (.4, .08), (.55, .22), (.9, .1), (.95, .35), (.33, .18)]):
                rr = (1.6 + (i % 3) * .6) * s
                d.ellipse((sx * W - rr, sy * H - rr, sx * W + rr, sy * H + rr), fill=rgba("#ffffff", .85))
        cx = W * .86
        cy, r = _fit_disc(H * .50, H * .09, clear, limit, min_r)
        if r:
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=rgba(c["moon"]))
        d.polygon([(0, H * .78), (W * .2, H * .42), (W * .38, H * .7), (W * .58, H * .36), (W * .8, H * .72),
                   (W, H * .5), (W, H), (0, H)], fill=rgba(c["far"]))
        d.polygon([(0, H * .9), (W * .3, H * .66), (W * .55, H * .86), (W * .75, H * .7), (W, H * .84),
                   (W, H), (0, H)], fill=rgba(c["mid"]))
        d.polygon([(0, H), (0, H * .95), (W * .45, H * .82), (W, H * .97), (W, H)], fill=rgba(c["near"]))
    elif scene == "waves":
        img = linear_gradient((W, H), [(0, rgba(c["sky"][0])), (1, rgba(c["sky"][1]))])
        d = ImageDraw.Draw(img)
        for i, col in enumerate(c["waves"]):
            base = H * (.42 + i * .13)
            amp, k = H * .06, 2 * math.pi / W * (1.2 + i * .25)
            pts = [(x, base + amp * math.sin(k * x + i * 1.3)) for x in range(0, W + 8, 8)]
            d.polygon(pts + [(W, H), (0, H)], fill=rgba(col))
        cx = W * .84
        cy, r = _fit_disc(H * .40, H * .09, clear, limit, min_r)
        if r:
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=rgba(c["sun"]))
    else:  # sunset
        sky = c["sky"]
        img = linear_gradient((W, H), [(0, rgba(sky[0])), (.45, rgba(sky[1])), (.62, rgba(sky[2])), (1, rgba(sky[2]))])
        d = ImageDraw.Draw(img)
        # the sun sits on the horizon: with long texts the horizon goes down,
        # and if there is still no room the sun gets smaller (or is left out)
        cx, r, sink = W * .80, H * .20, H * .02
        hz_max = min(H * .9, limit)
        hz = min(hz_max, max(H * .62, clear + r - sink))
        r = min(r, hz - clear + sink)
        if r - sink < min_r:
            r = 0
        hz = int(hz)
        cy = hz + sink
        if r:
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=rgba(c["sun"]))
        sea = linear_gradient((W, H - hz), [(0, rgba(c["sea"][0])), (1, rgba(c["sea"][1]))])
        img.paste(sea, (0, hz))
        for i in range(6 if r else 0):  # reflections of the sun on the sea
            y = hz + int((i + 1) * (H - hz) / 8)
            half = r * (1 - i * 0.13)
            d.rounded_rectangle((cx - half, y, cx + half, y + max(2, int(H * .018))), radius=3 * s,
                                fill=rgba(c["sun"], .55 - i * .07))
    img = img.resize(size, Image.Resampling.LANCZOS)
    # veil at the top and bottom so the texts stay readable
    v = (0, 0, 0) if dark else (255, 255, 255)
    a = (170, 120, 30, 190) if dark else (200, 150, 40, 200)
    img.alpha_composite(linear_gradient(size, [(0, v + (a[0],)), (.45, v + (a[1],)), (.7, v + (a[2],)), (1, v + (a[3],))]))
    return img


def record_image(dsz, s):
    """The vinyl record (RGBA, ``dsz`` px), drawn SS times bigger."""
    big = Image.new("RGBA", (dsz * SS, dsz * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    R = dsz * SS / 2
    d.ellipse((0, 0, 2 * R - 1, 2 * R - 1), fill=rgba("#111111"))
    rr, i = R * 0.96, 0
    while rr > R * 0.36:
        d.ellipse((R - rr, R - rr, R + rr, R + rr), outline=rgba("#3a3a3a") if i % 2 else rgba("#1c1c1c"),
                  width=max(1, int(SS * s * .9)))
        rr -= SS * s * 1.1
        i += 1
    d.pieslice((0, 0, 2 * R - 1, 2 * R - 1), 300, 330, fill=(255, 255, 255, 40))
    d.pieslice((0, 0, 2 * R - 1, 2 * R - 1), 120, 140, fill=(255, 255, 255, 22))
    lr = R * 0.34
    d.ellipse((R - lr, R - lr, R + lr, R + lr), fill=rgba("#ef7d3c"))
    hr = R * 0.05
    d.ellipse((R - hr, R - hr, R + hr, R + hr), fill=rgba("#f4ece4"))
    d.ellipse((0, 0, 2 * R - 1, 2 * R - 1), outline=(255, 255, 255, 70), width=SS)
    return big.resize((dsz, dsz), Image.Resampling.LANCZOS)


class CardRenderer:
    """Draws one notification in any of the STYLES.

    ``frame(t, progress)`` returns an RGBA image of ``size``: the card sits at
    ``card_box`` inside a transparent margin (for shadow and glow) when
    ``margin`` is True. ``t`` is seconds since the start (animation),
    ``progress`` goes from 1 to 0 over the duration (the bar at the bottom).
    Animated: glass (border and glow), aurora (blobs), classic (rainbow),
    vinyl (the record). Static, ambient and poster are drawn once.
    """

    def __init__(self, style, dark, title, message, app_name="", time_text="",
                 icon=None, scale=1.0, corner_radius=30, palette=DEFAULT_PALETTE,
                 glow=DEFAULT_GLOW, margin=True, backdrop=False):
        self.style = style if style in STYLES else DEFAULT_STYLE
        self.dark = bool(dark)
        self.s = s = max(0.5, float(scale))
        self.palette = PALETTES.get(palette, PALETTES[DEFAULT_PALETTE])
        self.glow = glow if glow in GLOWS else DEFAULT_GLOW
        self.backdrop = bool(backdrop)
        self.app_name = str(app_name or "")
        self.time_text = str(time_text or "")
        self.icon = icon
        self.title = str(title or "")
        self.ambient = pick_by_icon(AMBIENT_BY_ICON, icon, title, list(AMBIENT))
        self.scene = pick_by_icon(POSTER_BY_ICON, icon, title, list(POSTER_SCENES))
        self.colours = _colours(self.style, self.dark, self.ambient)

        def S(v):
            return int(round(v * s))
        self._S = S

        # Layout (CSS px of the widget, times scale)
        self.cw = S(CARD_WIDTH)
        self.pad = S(18)
        self.pad_b = S(14)
        self.tile = S(52)
        if self.style == "poster":
            art_w = 0
        elif self.style == "vinyl":
            art_w = S(86)
        else:
            art_w = self.tile
        self.text_x = self.pad + (art_w + S(14) if art_w else 0)
        self.text_w = self.cw - self.text_x - self.pad

        # the small upper-case line never gets smaller than 9 px
        self.f_eye = load_font(max(9.0, 10.5 * s), kind="semibold")
        self.f_time = load_font(11 * s)
        t_size = 20 if self.style == "poster" else 16.5
        self.f_title = load_font(t_size * s, kind="serif" if self.style == "vinyl" else "bold")
        self.f_msg = load_font(13 * s)
        self.title_lines = wrap_text(title, self.f_title, self.text_w, 2) or [""]
        self.msg_lines = wrap_text(message, self.f_msg, self.text_w, 3)
        self.t_lh, self.m_lh = S(t_size * 1.22), S(17.5)

        self.y_eye = self.pad
        self.y_title = self.y_eye + S(22)
        self.y_msg = self.y_title + len(self.title_lines) * self.t_lh + S(3)
        text_bottom = self.y_msg + len(self.msg_lines) * self.m_lh
        content_bottom = max(self.pad + (self.tile if self.style != "poster" else 0), text_bottom)
        self.bar_h = S(5)
        self.bar_y = content_bottom + S(14)
        self.ch = self.bar_y + self.bar_h + self.pad_b
        if self.style == "poster":
            self.ch = max(self.ch, S(168))
            self.bar_y = self.ch - self.pad_b - self.bar_h
        # corner_radius 30 (the default) -> 18 px like the widget; the slider still works
        self.radius = max(0, min(float(corner_radius) * 0.6 * s, self.ch / 2.0))

        self.m = S(36) if margin else 0
        self.size = (self.cw + 2 * self.m, self.ch + 2 * self.m)
        self.card_box = (self.m, self.m, self.m + self.cw, self.m + self.ch)
        self.bar_box = (self.pad, self.bar_y, self.cw - self.pad, self.bar_y + self.bar_h)

        if self.style == "glass":
            self.bg = (0x20, 0x21, 0x2b) if self.dark else (0xf7, 0xf8, 0xfb)
        elif self.style == "aurora":
            self.bg = (0x15, 0x16, 0x1f) if self.dark else (0xf3, 0xf4, 0xfa)
        elif self.style == "static":
            self.bg = (0x1c, 0x1c, 0x1e) if self.dark else (0xf2, 0xf2, 0xf7)
        else:
            self.bg = None  # computed from the background once it is drawn
        self.fg = self.colours["fg"][:3]
        self._matte = self.bg
        self._built = False

    @property
    def animated(self):
        return self.style in ("glass", "aurora", "classic", "vinyl")

    @property
    def matte(self):
        """Colour to flatten edges on when there is no per-pixel alpha."""
        if not self._built:
            self._build()
        return self._matte

    def set_backdrop(self, value):
        if bool(value) != self.backdrop:
            self.backdrop = bool(value)
            self._built = False

    # -- static layers, built once per notification
    def _build(self):
        s, cw, ch, m, S = self.s, self.cw, self.ch, self.m, self._S
        csize = (cw, ch)
        self.card_mask = rr_mask(csize, (0, 0, cw, ch), self.radius)

        # Shadow under the card (and the glow of glass), only with a margin
        self.shadow = None
        self.glow_mask = None
        if m:
            sm = Image.new("L", self.size, 0)
            ImageDraw.Draw(sm).rounded_rectangle((m, m + S(10), m + cw, m + ch + S(6)), radius=self.radius, fill=255)
            sm = sm.filter(ImageFilter.GaussianBlur(S(14)))
            self.shadow = solid(self.size, (0, 0, 0), sm, 125 if self.dark else 60)

        # 1 px border
        self.edge = None
        if self.colours["edge"]:
            k = max(1, s * .5)
            inner = rr_mask(csize, (k, k, cw - k, ch - k), max(0, self.radius - s * .5))
            self.edge = solid(csize, self.colours["edge"][:3], ImageChops.subtract(self.card_mask, inner),
                              self.colours["edge"][3])

        style = self.style
        self.base = None  # background already clipped, for the styles that do not animate it
        if style == "glass":
            fill_a = (0xb0 if self.dark else 0xbf) if self.backdrop else (0xeb if self.dark else 0xf0)
            self.fill = solid(csize, self.bg, self.card_mask, fill_a)
            inner = rr_mask(csize, (1.5 * s, 1.5 * s, cw - 1.5 * s, ch - 1.5 * s), max(0, self.radius - 1.5 * s))
            self.border_mask = ImageChops.subtract(self.card_mask, inner)
            if m:
                e, blur, op = GLOWS[self.glow]
                if not self.dark and self.glow == "full":
                    op = LIGHT_FULL_GLOW  # on a light desktop the full glow is lighter
                gm = Image.new("L", self.size, 0)
                ImageDraw.Draw(gm).rounded_rectangle((m - S(e), m - S(e), m + cw + S(e), m + ch + S(e)),
                                                     radius=self.radius + S(e), fill=255)
                gm = gm.filter(ImageFilter.GaussianBlur(S(blur)))
                self.glow_mask = gm.point(lambda v: int(v * op))
            self.angle = _angle_map(self.size, (m + cw // 2, m + ch // 2))
            self.lut = _gradient_lut(RAINBOW)
        elif style == "aurora":
            self.blob_r = r = int(max(cw, ch) * 0.59)
            small = 64
            radial = Image.new("L", (small, small))
            c = (small - 1) / 2.0
            amax = 0xbf if self.dark else 0x8c
            radial.putdata([int(max(0.0, 1 - math.hypot(x - c, y - c) / c) ** 1.2 * amax)
                            for y in range(small) for x in range(small)])
            radial = radial.resize((2 * r, 2 * r), Image.Resampling.BICUBIC)
            self.blobs = []
            for col in self.palette:
                rgb = hex_rgb(col)
                if self.dark:  # "screen" blend: premultiplied colour
                    self.blobs.append(Image.merge("RGB", [radial.point(lambda v, k=k: v * k // 255) for k in rgb]))
                else:
                    self.blobs.append(solid((2 * r, 2 * r), rgb, radial))
        elif style == "classic":
            self.rainbow = rainbow_base(self.dark, (max(1200, int(cw * 2.2)), max(600, int(ch * 3))))
            self.bg = tuple(int(v) for v in ImageStat.Stat(self.rainbow.resize((16, 16))).mean)
        else:
            if style == "static":
                bg = Image.new("RGBA", csize, self.bg + (255,))
            elif style == "ambient":
                bg = ambient_background(csize, self.dark, self.ambient)
            elif style == "poster":
                text_bottom = self.y_msg + len(self.msg_lines) * self.m_lh
                bg = poster_background(csize, self.scene, self.dark, s,
                                       clear_y=text_bottom + S(6), limit_y=self.bar_y - S(4))
            else:  # vinyl
                if self.dark:
                    bg = linear_gradient(csize, [(0, rgba("#221d1a")), (1, rgba("#141110"))], angle_deg=160)
                else:
                    bg = linear_gradient(csize, [(0, rgba("#f7f0e8")), (1, rgba("#e9ddd0"))], angle_deg=160)
            if self.bg is None:
                self.bg = tuple(int(v) for v in ImageStat.Stat(bg.convert("RGB")).mean)
            bg.putalpha(ImageChops.multiply(bg.getchannel("A"), self.card_mask))
            if self.edge is not None:
                bg.alpha_composite(self.edge)
            self.base = bg

        if style == "vinyl":
            x0, y0, tile = self.pad, self.pad, self.tile
            dsz = S(50)
            self.disc_pos = (x0 + tile - dsz + S(32), y0 + (tile - dsz) // 2)
            self.disc = record_image(dsz, s)
            sh = Image.new("L", csize, 0)
            dx, dy = self.disc_pos
            ImageDraw.Draw(sh).ellipse((dx, dy + S(3), dx + dsz, dy + dsz + S(3)), fill=255)
            self.base.alpha_composite(solid(csize, (0, 0, 0), sh.filter(ImageFilter.GaussianBlur(S(6))),
                                            150 if self.dark else 70))

        self.content = self._content_layer(csize)
        if self.base is not None and style != "vinyl":
            self.base.alpha_composite(self.content)
        self._matte = self.bg
        self._built = True

    def _icon_image(self, size, colour, emoji_ok=True):
        """Icon of the payload as an RGBA image of ``size``: an emoji (Windows)
        keeps its colours, a named icon is drawn in ``colour``. With
        ``emoji_ok`` False an emoji becomes the bell (too small to read)."""
        kind, val = resolve_icon(self.icon)
        if kind == "emoji" and not emoji_ok:
            val = "bell"
        elif kind == "emoji":
            emoji = emoji_image(val, size)
            if emoji is not None:
                out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
                out.alpha_composite(emoji, ((size - emoji.width) // 2, (size - emoji.height) // 2))
                return out
            val = "bell"
        return solid((size, size), colour[:3], icon_mask(val, size, 1.9), colour[3])

    def _content_layer(self, csize):
        S, T, style = self._S, self.colours, self.style
        cw = self.cw
        layer = Image.new("RGBA", csize, (0, 0, 0, 0))
        x0, y0, tile = self.pad, self.pad, self.tile

        # Icon tile (vinyl: the sleeve; poster: nothing, the icon goes in the app line)
        if style == "vinyl":
            sh = Image.new("L", csize, 0)
            ImageDraw.Draw(sh).rounded_rectangle((x0 + S(4), y0 + S(4), x0 + tile + S(4), y0 + tile + S(4)),
                                                 radius=S(6), fill=255)
            layer.alpha_composite(solid(csize, (0, 0, 0), sh.filter(ImageFilter.GaussianBlur(S(7))),
                                        128 if self.dark else 60))
            sleeve = linear_gradient((tile, tile), [(0, rgba("#ef7d3c")), (1, rgba("#a8324f"))], angle_deg=135)
            sleeve.putalpha(rr_mask((tile, tile), (0, 0, tile, tile), S(6)))
            layer.alpha_composite(sleeve, (x0, y0))
            isz = S(26)
            layer.alpha_composite(self._icon_image(isz, rgba("#fff4ea")),
                                  (x0 + (tile - isz) // 2, y0 + (tile - isz) // 2))
        elif style != "poster":
            sh = Image.new("L", csize, 0)
            ImageDraw.Draw(sh).rounded_rectangle((x0, y0 + S(6), x0 + tile, y0 + tile + S(6)), radius=S(12), fill=255)
            layer.alpha_composite(solid(csize, (0, 0, 0), sh.filter(ImageFilter.GaussianBlur(S(8))),
                                        90 if self.dark else 45))
            _paint(layer, rr_mask(csize, (x0, y0, x0 + tile, y0 + tile), S(12)), T["accent"])
            isz = S(26)
            layer.alpha_composite(self._icon_image(isz, T["on_accent"]),
                                  (x0 + (tile - isz) // 2, y0 + (tile - isz) // 2))

        # Texts
        tx = eye_x = self.text_x
        if style == "poster":
            isz = S(14)
            layer.alpha_composite(self._icon_image(isz, T["accent_text"], emoji_ok=False), (tx, self.y_eye + S(1)))
            eye_x = tx + isz + S(6)
        texts = [
            (text_mask(csize, [(eye_x, self.y_eye + S(2), self.app_name.upper(), self.f_eye, "la",
                                .06 * 10.5 * self.s)]), T["accent_text"]),
            (text_mask(csize, [(cw - self.pad, self.y_eye + S(1), self.time_text, self.f_time, "ra", 0)]),
             T["muted2"]),
            (text_mask(csize, [(tx, self.y_title + i * self.t_lh, ln, self.f_title, "la", 0)
                               for i, ln in enumerate(self.title_lines)]), T["fg"]),
            (text_mask(csize, [(tx, self.y_msg + i * self.m_lh, ln, self.f_msg, "la", 0)
                               for i, ln in enumerate(self.msg_lines)]), T["muted"]),
        ]
        if style == "poster":  # text shadow, like text-shadow 0 1px 6px
            allm = Image.new("L", csize, 0)
            for mk, _col in texts:
                allm = ImageChops.lighter(allm, mk)
            shadow = allm.filter(ImageFilter.GaussianBlur(S(3)))
            sl = Image.new("RGBA", csize, (0, 0, 0, 0))
            sl.alpha_composite(solid(csize, (0, 0, 0) if self.dark else (255, 255, 255), shadow, 150),
                               (0, S(1)))
            layer.alpha_composite(sl)
        for mk, col in texts:
            _paint(layer, mk, col)

        # Track of the bar
        bx0, by0, bx1, by1 = self.bar_box
        _paint(layer, rr_mask(csize, self.bar_box, self.bar_h / 2), T["track"])
        if T["fill"] == "rainbow":
            stops = [(i / (len(RAINBOW) - 1), rgba(c)) for i, c in enumerate(RAINBOW)]
            self.bar_grad = linear_gradient((bx1 - bx0, by1 - by0), stops, angle_deg=90)
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
                base.paste(ImageChops.screen(region, piece), (dx, dy))
            else:
                base.paste(piece, (dx, dy), piece)
        card = base.convert("RGBA")
        card.putalpha(self.card_mask)
        return card

    def _classic(self, t):
        cw, ch = self.cw, self.ch
        bw, bh = self.rainbow.size
        tt = t * 0.4  # same slow Lissajous path as before 1.2.0
        cx, cy = bw / 2 - cw / 2, bh / 2 - ch / 2
        rx, ry = max(0, (bw - cw) / 2 - 10), max(0, (bh - ch) / 2 - 10)
        ox = int(cx + math.sin(tt) * rx)
        oy = int(cy + math.cos(tt * 0.8) * ry)
        card = self.rainbow.crop((ox, oy, ox + cw, oy + ch)).convert("RGBA")
        card.putalpha(self.card_mask)
        return card

    def _bar(self, card, progress):
        progress = max(0.0, min(1.0, float(progress)))
        x0, y0, x1, y1 = self.bar_box
        w = int(round((x1 - x0) * progress))
        if w <= 0:
            return
        h = y1 - y0
        mask = rr_mask((w, h), (0, 0, w, h), h / 2.0)
        fill = self.colours["fill"]
        if fill == "rainbow":
            piece = self.bar_grad.crop((0, 0, w, h))
            piece.putalpha(ImageChops.multiply(piece.getchannel("A"), mask))
        else:
            piece = solid((w, h), fill[:3], mask, fill[3])
        card.alpha_composite(piece, (x0, y0))

    def frame(self, t, progress=1.0):
        if not self._built:
            self._build()
        out = Image.new("RGBA", self.size, (0, 0, 0, 0))
        if self.shadow is not None:
            out.alpha_composite(self.shadow)
        style = self.style
        if style == "glass":
            colors = self._conic(t)
            if self.glow_mask is not None:
                glow = colors.convert("RGBA")
                glow.putalpha(self.glow_mask)
                out.alpha_composite(glow)
            card = self.fill.copy()
            border = colors.crop(self.card_box).convert("RGBA")
            border.putalpha(self.border_mask)
            card.alpha_composite(border)
            card.alpha_composite(self.content)
        elif style in ("aurora", "classic"):
            card = self._aurora(t) if style == "aurora" else self._classic(t)
            if self.edge is not None:
                card.alpha_composite(self.edge)
            card.alpha_composite(self.content)
        elif style == "vinyl":
            card = self.base.copy()
            disc = self.disc.rotate(-(t * 90.0) % 360, resample=Image.Resampling.BICUBIC)
            card.alpha_composite(disc, self.disc_pos)
            card.alpha_composite(self.content)
        else:
            card = self.base.copy()
        self._bar(card, progress)
        out.alpha_composite(card, (self.m, self.m))
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
    Returns True if Windows accepted it (Windows 10 1803+ / 11).

    Unused by StyledPopup: on Windows 11 DWM ignores SetWindowRgn when
    ACCENT_ENABLE_ACRYLICBLURBEHIND is enabled, leaving a rectangular gray
    backdrop behind rounded cards.
    """
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
