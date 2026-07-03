"""Template specifications for the seven genre designs.

Every value here is transcribed from the original design file
("Book Review Story Templates" — 1080x1920 Instagram story kit,
Gelasio + Karla type direction).
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Shared palette
HEADING = "#37302A"
BODY = "#453B32"
REVIEW_TEXT = "#5C5045"
HINT = (69, 59, 50, 140)  # rgba(69,59,50,.55)

CANVAS_W = 1080
CANVAS_H = 1920


@dataclass(frozen=True)
class TemplateSpec:
    key: str
    name: str
    pill: str
    bg: str
    accent: str
    label: str
    box_bg: tuple[int, int, int, int]
    box_border_alpha: float
    underline_alpha: float
    motif: str
    pill_size: int = 24
    pill_pad_x: int = 28
    pill_tracking: float = 0.20  # em
    pill_right_offset: int = 0
    review_hint: str = ""


TEMPLATES: dict[str, TemplateSpec] = {
    t.key: t
    for t in [
        TemplateSpec(
            key="romance",
            name="Romance",
            pill="ROMANCE",
            bg="#F3EAE5",
            accent="#A9767C",
            label="#8A5F64",
            box_bg=(255, 251, 249, 153),
            box_border_alpha=0.35,
            underline_alpha=0.42,
            motif="bokeh",
            review_hint=(
                "Tap to write your review — what you loved, what surprised you, "
                "and who you'd hand it to next."
            ),
        ),
        TemplateSpec(
            key="thriller",
            name="Thriller · Mystery",
            pill="THRILLER · MYSTERY",
            bg="#EBE9E3",
            accent="#5F6B7A",
            label="#4E5966",
            box_bg=(255, 255, 251, 153),
            box_border_alpha=0.35,
            underline_alpha=0.42,
            motif="fingerprint",
            pill_size=22,
            pill_pad_x=26,
            pill_tracking=0.18,
            review_hint=(
                "Tap to write your review — the twists, the red herrings, "
                "whether it kept you up."
            ),
        ),
        TemplateSpec(
            key="scifi",
            name="Sci-fi",
            pill="SCI-FI",
            bg="#EAEDE8",
            accent="#55808A",
            label="#41666F",
            box_bg=(253, 255, 253, 153),
            box_border_alpha=0.35,
            underline_alpha=0.42,
            motif="starfield",
            review_hint=(
                "Tap to write your review — the world, the science, "
                "the characters you rooted for."
            ),
        ),
        TemplateSpec(
            key="horror",
            name="Horror",
            pill="HORROR",
            bg="#ECE7EA",
            accent="#77657D",
            label="#5F5064",
            box_bg=(255, 252, 254, 153),
            box_border_alpha=0.35,
            underline_alpha=0.42,
            motif="moon",
            pill_right_offset=150,
            review_hint=(
                "Tap to write your review — the dread, the atmosphere, "
                "how far you made it after dark."
            ),
        ),
        TemplateSpec(
            key="slice_of_life",
            name="Slice of life",
            pill="SLICE OF LIFE",
            bg="#EFEEE2",
            accent="#7C8465",
            label="#616A4B",
            box_bg=(255, 255, 250, 166),
            box_border_alpha=0.38,
            underline_alpha=0.45,
            motif="dotgrid",
            pill_size=23,
            pill_pad_x=26,
            pill_tracking=0.18,
            review_hint=(
                "Tap to write your review — the small moments, the comfort, "
                "the people you'll miss."
            ),
        ),
        TemplateSpec(
            key="emotional",
            name="Emotional · Life lessons",
            pill="EMOTIONAL · LIFE LESSONS",
            bg="#F4ECDD",
            accent="#B08D57",
            label="#8C6F3F",
            box_bg=(255, 252, 246, 166),
            box_border_alpha=0.38,
            underline_alpha=0.45,
            motif="sunrise",
            pill_size=20,
            pill_pad_x=24,
            pill_tracking=0.16,
            review_hint=(
                "Tap to write your review — what it made you feel, "
                "and the lesson you're keeping."
            ),
        ),
        TemplateSpec(
            key="biography",
            name="Biography · History",
            pill="BIOGRAPHY · HISTORY",
            bg="#F0E9DF",
            accent="#8A7767",
            label="#6F5F50",
            box_bg=(255, 253, 249, 166),
            box_border_alpha=0.38,
            underline_alpha=0.45,
            motif="ruledlines",
            pill_size=22,
            pill_pad_x=26,
            pill_tracking=0.18,
            review_hint=(
                "Tap to write your review — the life, the era, "
                "what it taught you about people."
            ),
        ),
    ]
}

DEFAULT_TEMPLATE = "romance"


def get_template(key: str) -> TemplateSpec:
    return TEMPLATES.get(key, TEMPLATES[DEFAULT_TEMPLATE])
