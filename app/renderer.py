"""Pillow renderer for the review templates.

Renders a Review onto its 1080x1920 template. The same code path produces
the live editor preview and the exported PNG, so the export always matches
what is shown on screen.
"""

from __future__ import annotations

import io
import math
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .models import Review
from .templates import (
    BODY,
    CANVAS_H,
    CANVAS_W,
    HEADING,
    HINT,
    REVIEW_TEXT,
    TemplateSpec,
    get_template,
)

FONTS_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"

PAD = 64
GAP = 26
CONTENT_W = CANVAS_W - 2 * PAD  # 952
COVER_W, COVER_H = 380, 540
FIELDS_X = PAD + COVER_W + 36  # 480
FIELDS_W = CANVAS_W - PAD - FIELDS_X  # 536
GRID_GAP = 18
CELL_W = (CONTENT_W - GRID_GAP) // 2  # 467
CELL_H = 225


def _hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _rgba(h: str, alpha: float) -> tuple[int, int, int, int]:
    r, g, b = _hex_rgb(h)
    return (r, g, b, round(alpha * 255))


@lru_cache(maxsize=64)
def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS_DIR / name), size)


def gelasio(size: int, weight: str = "Regular") -> ImageFont.FreeTypeFont:
    return _font(f"Gelasio-{weight}.ttf", size)


def karla(size: int, weight: str = "Regular") -> ImageFont.FreeTypeFont:
    return _font(f"Karla-{weight}.ttf", size)


# --------------------------------------------------------------------------
# small drawing helpers
# --------------------------------------------------------------------------


def _tracked_width(draw: ImageDraw.ImageDraw, text: str, font, tracking: float) -> float:
    if not text:
        return 0.0
    return sum(draw.textlength(ch, font=font) for ch in text) + tracking * (len(text) - 1)


def _draw_tracked(draw, xy, text, font, fill, tracking: float) -> None:
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + tracking


def _wrap(draw, text: str, font, max_w: float) -> list[str]:
    lines: list[str] = []
    for para in (text or "").split("\n"):
        words = para.split()
        if not words:
            lines.append("")
            continue
        cur = words[0]
        for w in words[1:]:
            if draw.textlength(cur + " " + w, font=font) <= max_w:
                cur += " " + w
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
    return lines


@lru_cache(maxsize=32)
def _rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    ss = 4
    m = Image.new("L", (size[0] * ss, size[1] * ss), 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle([0, 0, size[0] * ss - 1, size[1] * ss - 1], radius * ss, fill=255)
    return m.resize(size, Image.LANCZOS)


def _paste_cover_image(base: Image.Image, img: Image.Image, box: tuple[int, int, int, int], radius: int) -> None:
    w, h = box[2] - box[0], box[3] - box[1]
    fitted = ImageOps.fit(img.convert("RGB"), (w, h), Image.LANCZOS)
    base.paste(fitted, (box[0], box[1]), _rounded_mask((w, h), radius))


def _dashed_round_rect(draw, box, radius, color, width=3, dash=14, gap=10) -> None:
    x0, y0, x1, y1 = box
    r = radius
    pts: list[tuple[float, float]] = []

    def arc(cx, cy, start, end):
        steps = max(4, int(r * abs(end - start) / 12))
        for i in range(steps + 1):
            a = math.radians(start + (end - start) * i / steps)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))

    def line(ax, ay, bx, by):
        dist = math.hypot(bx - ax, by - ay)
        steps = max(2, int(dist / 4))
        for i in range(steps + 1):
            pts.append((ax + (bx - ax) * i / steps, ay + (by - ay) * i / steps))

    line(x0 + r, y0, x1 - r, y0)
    arc(x1 - r, y0 + r, -90, 0)
    line(x1, y0 + r, x1, y1 - r)
    arc(x1 - r, y1 - r, 0, 90)
    line(x1 - r, y1, x0 + r, y1)
    arc(x0 + r, y1 - r, 90, 180)
    line(x0, y1 - r, x0, y0 + r)
    arc(x0 + r, y0 + r, 180, 270)

    # resample to uniform spacing, then chunk into dash / gap runs
    step = 2.0
    uniform: list[tuple[float, float]] = [pts[0]]
    carry = 0.0
    for a, b in zip(pts, pts[1:]):
        d = math.hypot(b[0] - a[0], b[1] - a[1])
        if d == 0:
            continue
        t = step - carry
        while t <= d:
            uniform.append((a[0] + (b[0] - a[0]) * t / d, a[1] + (b[1] - a[1]) * t / d))
            t += step
        carry = (carry + d) % step
    n_on, n_off = max(2, int(dash / step)), max(1, int(gap / step))
    i = 0
    while i < len(uniform):
        seg = uniform[i : i + n_on]
        if len(seg) > 1:
            draw.line(seg, fill=color, width=width, joint="curve")
        i += n_on + n_off


def _star_points(cx: float, cy: float, r_out: float) -> list[tuple[float, float]]:
    r_in = r_out * 0.45
    pts = []
    for i in range(10):
        ang = -math.pi / 2 + i * math.pi / 5
        r = r_out if i % 2 == 0 else r_in
        pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    return pts


def _draw_star(base: Image.Image, cx: float, cy: float, size: float, accent: str, frac: float) -> None:
    """One star at ``frac`` fill (0, 0.5 or 1), antialiased via supersampling."""
    ss = 3
    s = int(size * ss)
    tile = Image.new("RGBA", (s + 8 * ss, s + 8 * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(tile)
    tcx, tcy = tile.width / 2, tile.height / 2
    pts = _star_points(tcx, tcy, s / 2)
    if frac > 0:
        fill_tile = Image.new("RGBA", tile.size, (0, 0, 0, 0))
        fd = ImageDraw.Draw(fill_tile)
        fd.polygon(pts, fill=_rgba(accent, 1.0))
        if frac < 1:
            fill_tile.paste(
                (0, 0, 0, 0), (int(tile.width * frac), 0, tile.width, tile.height)
            )
        tile.alpha_composite(fill_tile)
    d.line(pts + [pts[0]], fill=_rgba(accent, 0.5), width=2 * ss, joint="curve")
    tile = tile.resize((tile.width // ss, tile.height // ss), Image.LANCZOS)
    base.alpha_composite(tile, (int(cx - tile.width / 2), int(cy - tile.height / 2)))


# --------------------------------------------------------------------------
# background motifs (static per template -> cached)
# --------------------------------------------------------------------------


def _circle(d: ImageDraw.ImageDraw, cx, cy, r, fill=None, outline=None, width=3):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill, outline=outline, width=width)


def _motif_bokeh(d, ov, spec):
    a = spec.accent
    for fx, fy, r, al in [(0.88, 0.06, 150, 0.09), (0.73, 0.12, 92, 0.07), (0.06, 0.91, 130, 0.08), (0.19, 0.83, 76, 0.06)]:
        _circle(d, CANVAS_W * fx, CANVAS_H * fy, r, fill=_rgba(a, al))


def _motif_fingerprint(d, ov, spec):
    a = spec.accent
    cx, cy = CANVAS_W * 0.91, CANVAS_H * 0.03
    for r in (45.5, 85.5, 127.5, 171.5):
        _circle(d, cx, cy, r, outline=_rgba(a, 0.11), width=3)
    cx, cy = CANVAS_W * 0.04, CANVAS_H * 0.97
    for r in (37.5, 73.5, 111.5):
        _circle(d, cx, cy, r, outline=_rgba(a, 0.10), width=3)


def _motif_starfield(d, ov, spec):
    a = spec.accent
    dots = [
        (0.12, 0.16, 4, 0.32), (0.22, 0.08, 3, 0.26), (0.82, 0.21, 5, 0.28),
        (0.68, 0.05, 3, 0.24), (0.07, 0.58, 4, 0.20), (0.95, 0.55, 3, 0.22),
        (0.89, 0.89, 5, 0.26), (0.74, 0.96, 3, 0.22),
    ]
    for fx, fy, r, al in dots:
        _circle(d, CANVAS_W * fx, CANVAS_H * fy, r, fill=_rgba(a, al))
    _circle(d, CANVAS_W + 150 - 235, -170 + 235, 235, outline=_rgba(a, 0.20), width=3)
    _circle(d, -140 + 165, CANVAS_H + 130 - 165, 165, outline=_rgba(a, 0.16), width=2)


def _motif_moon(d, ov, spec):
    a = spec.accent
    # soft vignette
    vg = Image.new("L", (108, 192), 0)
    for y in range(192):
        for x in range(108):
            dist = math.hypot((x - 54) / (54 * 2.6), (y - 192 * 0.36) / (192 * 0.95))
            v = max(0.0, min(1.0, (dist - 0.58) / 0.42))
            vg.putpixel((x, y), int(v * 0.11 * 255))
    ov.paste(Image.new("RGBA", (CANVAS_W, CANVAS_H), _rgba(a, 1.0)), (0, 0), vg.resize((CANVAS_W, CANVAS_H), Image.BILINEAR))
    # crescent moon, top right
    _circle(d, CANVAS_W - 84 - 75, 104 + 75, 75, fill=_rgba(a, 0.18))
    _circle(d, CANVAS_W - 128 - 68, 92 + 68, 68, fill=spec.bg)


def _motif_dotgrid(d, ov, spec):
    a = spec.accent
    step = 64
    for yi in range(CANVAS_H // step + 2):
        for xi in range(CANVAS_W // step + 2):
            _circle(d, 32 + xi * step, 32 + yi * step, 3.2, fill=_rgba(a, 0.13))


def _motif_sunrise(d, ov, spec):
    a = spec.accent
    cx = CANVAS_W / 2
    for diam, top, al, w in [(940, -660, 0.15, 3), (720, -600, 0.13, 3), (500, -540, 0.11, 2)]:
        _circle(d, cx, top + diam / 2, diam / 2, outline=_rgba(a, al), width=w)


def _motif_ruledlines(d, ov, spec):
    a = spec.accent
    y = 84
    while y < CANVAS_H:
        d.rectangle([0, y, CANVAS_W, y + 2], fill=_rgba(a, 0.09))
        y += 86


_MOTIFS = {
    "bokeh": _motif_bokeh,
    "fingerprint": _motif_fingerprint,
    "starfield": _motif_starfield,
    "moon": _motif_moon,
    "dotgrid": _motif_dotgrid,
    "sunrise": _motif_sunrise,
    "ruledlines": _motif_ruledlines,
}


@lru_cache(maxsize=1)
def _grain() -> Image.Image:
    noise = Image.effect_noise((CANVAS_W // 2, CANVAS_H // 2), 70).resize((CANVAS_W, CANVAS_H))
    alpha = noise.point(lambda p: max(0, p - 118) * 12 // 100)
    grain = Image.new("RGBA", (CANVAS_W, CANVAS_H), (30, 24, 18, 255))
    grain.putalpha(alpha)
    return grain


@lru_cache(maxsize=16)
def _background(key: str) -> Image.Image:
    spec = get_template(key)
    base = Image.new("RGBA", (CANVAS_W, CANVAS_H), _hex_rgb(spec.bg) + (255,))
    ov = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    _MOTIFS[spec.motif](d, ov, spec)
    base.alpha_composite(ov)
    base.alpha_composite(_grain())
    return base


# --------------------------------------------------------------------------
# sections
# --------------------------------------------------------------------------


def _draw_label(draw, x, y, text, spec, size=23) -> float:
    f = karla(size, "Bold")
    _draw_tracked(draw, (x, y), text, f, spec.label, 0.2 * size)
    return y + size * 1.3


def _draw_placeholder(base, draw, box, radius, spec, text) -> None:
    draw.rounded_rectangle(box, radius, fill=(255, 255, 255, 80))
    _dashed_round_rect(draw, box, radius, _rgba(spec.accent, 0.55), width=3)
    f = karla(22)
    tw = draw.textlength(text, font=f)
    cx = (box[0] + box[2]) / 2
    cy = (box[1] + box[3]) / 2
    draw.text((cx - tw / 2, cy - 13), text, font=f, fill=_rgba(spec.label, 0.6))


def _draw_header(base, draw, spec) -> int:
    title_f = gelasio(82, "SemiBold")
    draw.text((PAD, PAD - 8), "Book Review", font=title_f, fill=HEADING)
    header_h = 86

    ps = spec.pill_size
    pf = karla(ps, "Bold")
    tracking = spec.pill_tracking * ps
    tw = _tracked_width(draw, spec.pill, pf, tracking)
    pill_h = ps + 2 * 12 + 5
    pill_w = tw + 2 * spec.pill_pad_x + 5
    x1 = CANVAS_W - PAD - spec.pill_right_offset
    x0 = x1 - pill_w
    cy = PAD + header_h / 2 + 2
    y0, y1 = cy - pill_h / 2, cy + pill_h / 2
    draw.rounded_rectangle([x0, y0, x1, y1], pill_h / 2, outline=_rgba(spec.accent, 1.0), width=3)
    ascent, descent = pf.getmetrics()
    ty = cy - (ascent + descent) / 2
    _draw_tracked(draw, (x0 + spec.pill_pad_x + 3, ty), spec.pill, pf, spec.label, tracking)

    y = PAD + header_h + GAP
    # gradient divider
    grad = Image.new("L", (256, 1))
    grad.putdata([255 - i for i in range(256)])
    grad = grad.resize((CONTENT_W, 3))
    solid = Image.new("RGBA", (CONTENT_W, 3), _rgba(spec.accent, 1.0))
    base.paste(solid, (PAD, y), grad)
    return y + 3 + GAP


def _draw_field(draw, x, y, w, label, value, spec, value_font_size=40) -> float:
    y = _draw_label(draw, x, y, label, spec)
    y += 4
    vf = gelasio(value_font_size)
    lines = _wrap(draw, value, vf, w) if value else [""]
    lh = round(value_font_size * 1.25)
    for ln in lines:
        draw.text((x, y), ln, font=vf, fill=BODY)
        y += lh
    y += 12
    draw.rectangle([x, y, x + w, y + 2], fill=_rgba(spec.accent, spec.underline_alpha))
    return y + 2


def _fields_font_size(draw, review) -> int:
    """Shrink the value font until title/author/pages+days + rating fit in 540px."""
    for size in (40, 36, 32, 28):
        vf = gelasio(size)
        total = 0.0
        # pages and days share one row, so only the taller of the two counts
        row_lines = max(
            len(_wrap(draw, review.pages, vf, FIELDS_W * 0.46)) if review.pages else 1,
            len(_wrap(draw, review.days_taken, vf, FIELDS_W * 0.46)) if review.days_taken else 1,
        )
        for value, w, forced in (
            (review.title, FIELDS_W, None),
            (review.author, FIELDS_W, None),
            (None, FIELDS_W * 0.46, row_lines),
        ):
            nlines = forced or (len(_wrap(draw, value, vf, w)) if value else 1)
            total += 23 * 1.3 + 4 + nlines * size * 1.25 + 14
        total += 2 * 20  # gaps between fields
        rating_h = 23 * 1.3 + 8 + 60
        if total + 20 + rating_h <= COVER_H + 6:
            return size
    return 28


def _draw_stars(base, spec, x, y, rating: float) -> None:
    size = 56
    gap = 12
    for i in range(5):
        frac = max(0.0, min(1.0, rating - i))
        frac = 0.5 if 0 < frac < 0.75 else (1.0 if frac >= 0.75 else 0.0)
        cx = x + i * (size + gap) + size / 2
        _draw_star(base, cx, y + size / 2, size, spec.accent, frac)


# --------------------------------------------------------------------------
# main entry
# --------------------------------------------------------------------------


def render_review(
    review: Review,
    images: dict[str, bytes | None] | None = None,
    scale: float = 1.0,
) -> Image.Image:
    """Render ``review`` to a PIL image.

    ``images`` maps slot names ("cover", "aes0".."aes3") to raw image bytes.
    """
    spec = get_template(review.template_key)
    images = images or {}
    base = _background(spec.key).copy()
    draw = ImageDraw.Draw(base)

    y = _draw_header(base, draw, spec)

    # --- cover + fields row -------------------------------------------------
    row_y = y
    cover_box = (PAD, row_y, PAD + COVER_W, row_y + COVER_H)
    cover_bytes = images.get("cover")
    if cover_bytes:
        _paste_cover_image(base, Image.open(io.BytesIO(cover_bytes)), cover_box, 22)
    else:
        _draw_placeholder(base, draw, cover_box, 22, spec, "drop the book cover")

    fsize = _fields_font_size(draw, review)
    fy = row_y
    fy = _draw_field(draw, FIELDS_X, fy, FIELDS_W, "TITLE", review.title, spec, fsize) + 20
    fy = _draw_field(draw, FIELDS_X, fy, FIELDS_W, "AUTHOR", review.author, spec, fsize) + 20
    half_w = round(FIELDS_W * 0.46)
    _draw_field(draw, FIELDS_X, fy, half_w, "PAGES", review.pages, spec, fsize)
    _draw_field(
        draw, FIELDS_X + FIELDS_W - half_w, fy, half_w, "DAYS TAKEN",
        review.days_taken, spec, fsize,
    )

    stars_y = row_y + COVER_H - 56
    _draw_label(draw, FIELDS_X, stars_y - 8 - 30, "MY RATING", spec)
    _draw_stars(base, spec, FIELDS_X, stars_y, review.rating)

    y = row_y + COVER_H + GAP

    # --- aesthetic section (anchored to the bottom) -------------------------
    grid_h = 2 * CELL_H + GRID_GAP
    aes_header_h = 30 + 16
    aes_y = CANVAS_H - PAD - grid_h - aes_header_h

    # --- review box (fills the space between) --------------------------------
    box_y1 = aes_y - GAP
    box = (PAD, y, CANVAS_W - PAD, box_y1)
    draw.rounded_rectangle(box, 26, fill=spec.box_bg)
    draw.rounded_rectangle(box, 26, outline=_rgba(spec.accent, spec.box_border_alpha), width=3)
    tx, ty = PAD + 42, y + 38
    ty = _draw_label(draw, tx, ty, "MY REVIEW", spec) + 16
    text_w = CONTENT_W - 2 * 42
    max_h = box_y1 - 38 - ty
    body = review.review_text.strip()
    color = REVIEW_TEXT if body else (92, 80, 69, 128)
    text = body or spec.review_hint
    for size in (30, 28, 26, 24, 22):
        rf = gelasio(size)
        lines = _wrap(draw, text, rf, text_w)
        lh = round(size * 1.65)
        if len(lines) * lh <= max_h:
            break
    else:
        keep = int(max_h // lh)
        lines = lines[:keep]
        if lines:
            lines[-1] = lines[-1].rstrip(" .,") + " …"
    for ln in lines:
        draw.text((tx, ty), ln, font=rf, fill=color)
        ty += lh

    # --- aesthetic grid ------------------------------------------------------
    ay = _draw_label(draw, PAD, aes_y, "THE AESTHETIC", spec)
    hint_f = karla(22)
    hint = "drop images that feel like this book"
    hw = draw.textlength(hint, font=hint_f)
    draw.text((CANVAS_W - PAD - hw, aes_y + 4), hint, font=hint_f, fill=HINT)
    gy = aes_y + aes_header_h
    for i in range(4):
        cx = PAD + (i % 2) * (CELL_W + GRID_GAP)
        cy = gy + (i // 2) * (CELL_H + GRID_GAP)
        cell = (cx, cy, cx + CELL_W, cy + CELL_H)
        data = images.get(f"aes{i}")
        if data:
            _paste_cover_image(base, Image.open(io.BytesIO(data)), cell, 18)
        else:
            _draw_placeholder(base, draw, cell, 18, spec, "mood image")

    out = base.convert("RGB")
    if scale != 1.0:
        out = out.resize((round(CANVAS_W * scale), round(CANVAS_H * scale)), Image.LANCZOS)
    return out


def render_png(review: Review, images: dict[str, bytes | None] | None = None, scale: float = 1.0) -> bytes:
    buf = io.BytesIO()
    render_review(review, images, scale).save(buf, "PNG")
    return buf.getvalue()


def blank_template_png(key: str, scale: float = 0.22) -> bytes:
    """Small preview of an empty template (for the picker)."""
    return render_png(Review.new(key), None, scale)
