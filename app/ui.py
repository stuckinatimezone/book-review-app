"""All application views: login, library (bookshelf), template picker, editor."""

from __future__ import annotations

import asyncio
import io
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import flet as ft
from PIL import Image as PILImage

from . import renderer
from .models import Review
from .storage import StoreError
from .templates import TEMPLATES, TemplateSpec, get_template

try:  # optional: lets Pillow open iPhone HEIC photos
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:
    pass

# ---- app palette (matches the template family) ----------------------------
BG = "#F6F1E7"
INK = "#37302A"
BODY = "#453B32"
MUTED = "#8A7767"
CARD = "#FFFDF8"
WOOD_TOP = "#A98A6B"
WOOD_BOTTOM = "#7A5C43"

SLOT_LABELS = {"cover": "Book cover", "aes0": "Mood 1", "aes1": "Mood 2", "aes2": "Mood 3", "aes3": "Mood 4"}


@dataclass
class Ctx:
    page: ft.Page
    store: object
    file_picker: ft.FilePicker
    password: str
    authed: bool = False
    storage_note: str | None = None
    # unsaved drafts: review_id -> (Review, {slot: bytes})
    drafts: dict = field(default_factory=dict)
    # set by main(): rebuilds the view for the current route (page.go is a
    # no-op when the route doesn't change, e.g. after login on "/")
    rebuild: object = None
    # set by main(): drops cached views so they rebuild with fresh data
    invalidate: object = None


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def heading(text: str, size: int = 34, color: str = INK) -> ft.Text:
    return ft.Text(text, font_family="Gelasio SemiBold", size=size, color=color)


def body_text(text: str, size: int = 15, color: str = BODY) -> ft.Text:
    return ft.Text(text, font_family="Karla", size=size, color=color)


def snack(page: ft.Page, msg: str) -> None:
    page.show_dialog(ft.SnackBar(msg, duration=2600))


# ---- entrance animations ---------------------------------------------------

_EASE_OUT = ft.AnimationCurve.EASE_OUT_CUBIC


def prep_reveal(control, dy: float = 0.04, dur: int = 420):
    """Prepare a control to fade-and-rise in; play_reveal() triggers it."""
    control.opacity = 0
    control.offset = (0, dy)
    control.animate_opacity = ft.Animation(dur, _EASE_OUT)
    control.animate_offset = ft.Animation(dur + 80, _EASE_OUT)
    return control


async def play_reveal(view: ft.View) -> None:
    """Run the staggered entrance for controls registered on a view.

    Called by main() right after the view appears; each view registers its
    entrance sequence in ``view._reveal`` (consumed on first show, so
    navigating back to a cached view doesn't replay it).
    """
    controls = getattr(view, "_reveal", None)
    if not controls:
        return
    view._reveal = None
    await asyncio.sleep(0.05)
    for c in controls:
        c.opacity = 1
        c.offset = (0, 0)
        try:
            c.update()
        except Exception:  # noqa: BLE001 — view already gone; stop quietly
            return
        await asyncio.sleep(0.055)


def hoverable(control, on_change, on_tap=None) -> ft.GestureDetector:
    """Wrap a control so it reacts to pointer enter/exit with a hand cursor."""
    return ft.GestureDetector(
        content=control,
        mouse_cursor=ft.MouseCursor.CLICK,
        on_enter=lambda e: on_change(True),
        on_exit=lambda e: on_change(False),
        on_tap=on_tap,
    )


def normalize_image(data: bytes) -> bytes:
    """Downscale uploads and re-encode as JPEG so storage stays small."""
    img = PILImage.open(io.BytesIO(data))
    img = img.convert("RGB")
    img.thumbnail((1600, 1600), PILImage.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88)
    return buf.getvalue()


@lru_cache(maxsize=256)
def _thumb(data: bytes, max_w: int, max_h: int) -> bytes:
    """Small JPEG for on-screen tiles, so phones never download full images."""
    img = PILImage.open(io.BytesIO(data)).convert("RGB")
    img.thumbnail((max_w, max_h), PILImage.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    return buf.getvalue()


def load_images(store, review: Review) -> dict[str, bytes | None]:
    images: dict[str, bytes | None] = {}
    if review.cover_image:
        images["cover"] = store.load_image(review.cover_image)
    for i, key in enumerate(review.aesthetic_images):
        if key:
            images[f"aes{i}"] = store.load_image(key)
    return images


def safe_filename(review: Review) -> str:
    spec = get_template(review.template_key)
    name = f"{review.title or 'book-review'} — {spec.name}"
    return re.sub(r"[^\w\s\-·–—]", "", name).strip()[:80] + ".png"


async def export_review(ctx: Ctx, review: Review, images: dict | None = None) -> None:
    if images is None:
        images = await asyncio.to_thread(load_images, ctx.store, review)
    png = await asyncio.to_thread(renderer.render_png, review, images)
    fname = safe_filename(review)
    try:
        if ctx.page.web or ctx.page.platform.is_mobile():
            await ctx.file_picker.save_file(file_name=fname, src_bytes=png)
            snack(ctx.page, "Export started — check your downloads.")
        else:
            path = await ctx.file_picker.save_file(
                dialog_title="Export review as PNG", file_name=fname
            )
            if path:
                if not path.lower().endswith(".png"):
                    path += ".png"
                Path(path).write_bytes(png)
                snack(ctx.page, f"Exported to {path}")
    except Exception as e:  # noqa: BLE001 — always surface export problems
        snack(ctx.page, f"Export failed: {e}")


def rating_icons(rating: float, accent: str, size: int = 26) -> list[ft.Icon]:
    icons = []
    for i in range(5):
        frac = rating - i
        name = ft.Icons.STAR if frac >= 0.75 else (ft.Icons.STAR_HALF if frac > 0 else ft.Icons.STAR_BORDER)
        icons.append(ft.Icon(name, color=accent, size=size))
    return icons


# ---------------------------------------------------------------------------
# login
# ---------------------------------------------------------------------------


def build_login(ctx: Ctx) -> ft.View:
    pw = ft.TextField(
        label="Password",
        password=True,
        can_reveal_password=True,
        width=280,
        autofocus=True,
        border_color=MUTED,
        border_radius=10,
    )
    error = body_text("", 13, "#A9464F")
    error.animate_opacity = ft.Animation(200, _EASE_OUT)

    async def shake(control):
        control.animate_offset = ft.Animation(60, ft.AnimationCurve.EASE_IN_OUT)
        for dx in (0.02, -0.016, 0.01, 0):
            control.offset = (dx, 0)
            control.update()
            await asyncio.sleep(0.06)
        control.animate_offset = ft.Animation(500, _EASE_OUT)

    async def submit(e):
        if (pw.value or "").strip() == ctx.password:
            ctx.authed = True
            # let the card breathe out before the library slides in
            card.opacity = 0
            card.scale = 0.97
            card.update()
            await asyncio.sleep(0.24)
            await ctx.rebuild()
        else:
            error.value = "That's not it — try again."
            error.update()
            await shake(card)

    pw.on_submit = submit
    card = ft.Container(
        content=ft.Column(
            [
                heading("Book Review", 40),
                body_text("your private bookshelf", 15, MUTED),
                ft.Container(height=18),
                pw,
                error,
                ft.Container(height=6),
                ft.FilledButton("Open the library", on_click=submit, bgcolor=MUTED, color="#FFFFFF"),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            tight=True,
        ),
        padding=ft.Padding.symmetric(vertical=48, horizontal=56),
        width=420,
        bgcolor=CARD,
        border_radius=22,
        border=ft.Border.all(1, "#E2D5C3"),
        shadow=ft.BoxShadow(blur_radius=30, color="#14201710", offset=ft.Offset(0, 10)),
        animate_scale=ft.Animation(240, _EASE_OUT),
    )
    prep_reveal(card, dy=0.03, dur=500)
    view = ft.View(
        route="/login",
        controls=[
            ft.SafeArea(
                content=ft.Container(content=card, alignment=ft.Alignment.CENTER, expand=True),
                expand=True,
            )
        ],
        bgcolor=BG,
    )
    view._reveal = [card]
    return view


# ---------------------------------------------------------------------------
# library ("the bookshelf")
# ---------------------------------------------------------------------------

BOOK_W, BOOK_H = 148, 212


def _book_tile(ctx: Ctx, review: Review, cover: bytes | None) -> ft.Control:
    spec = get_template(review.template_key)

    if cover:
        face = ft.Image(
            src=_thumb(cover, BOOK_W * 3, BOOK_H * 3),
            width=BOOK_W,
            height=BOOK_H,
            fit=ft.BoxFit.COVER,
            border_radius=6,
        )
    else:
        face = ft.Container(
            width=BOOK_W,
            height=BOOK_H,
            border_radius=6,
            gradient=ft.LinearGradient(
                begin=ft.Alignment.CENTER_LEFT,
                end=ft.Alignment.CENTER_RIGHT,
                colors=[spec.label, spec.accent],
                stops=[0.06, 0.2],
            ),
            padding=ft.Padding.only(left=18, top=16, right=12, bottom=12),
            content=ft.Column(
                [
                    ft.Text(
                        review.title or "Untitled",
                        font_family="Gelasio SemiBold",
                        size=17,
                        color="#FFF9F2",
                        max_lines=4,
                        overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                    ft.Container(expand=True),
                    ft.Text(review.author, font_family="Karla", size=12, color="#F5EBDD"),
                ],
            ),
        )

    async def open_actions(e):
        await _book_dialog(ctx, review, cover)

    lift = ft.Container(
        content=face,
        border_radius=6,
        shadow=ft.BoxShadow(blur_radius=10, color="#33000000", offset=ft.Offset(2, 4)),
        tooltip=review.title or "Untitled",
        animate_scale=ft.Animation(220, _EASE_OUT),
        animate_offset=ft.Animation(220, _EASE_OUT),
        animate=ft.Animation(220, _EASE_OUT),
    )

    def hover(entered: bool):
        lift.scale = 1.04 if entered else 1.0
        lift.offset = (0, -0.016) if entered else (0, 0)
        lift.shadow = (
            ft.BoxShadow(blur_radius=20, color="#40000000", offset=ft.Offset(2, 9))
            if entered
            else ft.BoxShadow(blur_radius=10, color="#33000000", offset=ft.Offset(2, 4))
        )
        lift.update()

    return ft.Container(
        content=ft.Column(
            [hoverable(lift, hover, on_tap=open_actions), ft.Container(height=2)],
            tight=True,
        ),
    )


async def _book_dialog(ctx: Ctx, review: Review, cover: bytes | None = None) -> None:
    spec = get_template(review.template_key)
    page = ctx.page

    async def do_edit(e):
        page.pop_dialog()
        await page.push_route(f"/edit/{review.id}")

    async def do_export(e):
        page.pop_dialog()
        snack(page, "Rendering PNG…")
        await export_review(ctx, review)

    async def do_delete(e):
        page.pop_dialog()

        async def really(e2):
            page.pop_dialog()
            try:
                await asyncio.to_thread(ctx.store.delete_review, review)
            except StoreError as err:
                snack(page, str(err))
                return
            snack(page, "Review removed from your shelf.")
            if ctx.invalidate:
                ctx.invalidate("/")
            await ctx.rebuild()

        page.show_dialog(
            ft.AlertDialog(
                title=ft.Text("Delete this review?", font_family="Gelasio SemiBold"),
                content=body_text(f"“{review.title or 'Untitled'}” will be gone for good."),
                actions=[
                    ft.TextButton("Cancel", on_click=lambda e2: page.pop_dialog()),
                    ft.FilledButton("Delete", bgcolor="#A9464F", color="#FFFFFF", on_click=really),
                ],
            )
        )

    if cover:
        mini = ft.Image(
            src=_thumb(cover, 168, 240), width=56, height=84,
            fit=ft.BoxFit.COVER, border_radius=6,
        )
    else:
        mini = ft.Container(width=56, height=84, border_radius=6, bgcolor=spec.accent)
    details = ft.Column(
        [
            body_text(spec.name.upper(), 11, spec.label),
            ft.Row(rating_icons(review.rating, spec.accent, 18), spacing=1),
            body_text(
                "  ·  ".join(
                    p for p in (
                        review.author,
                        f"{review.pages} pages" if review.pages else "",
                    ) if p
                ) or "No details yet",
                13,
                MUTED,
            ),
        ],
        spacing=6,
        tight=True,
        alignment=ft.MainAxisAlignment.CENTER,
    )
    page.show_dialog(
        ft.AlertDialog(
            title=ft.Text(review.title or "Untitled", font_family="Gelasio SemiBold"),
            content=ft.Row([mini, details], spacing=16, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            actions=[
                ft.TextButton("Delete", on_click=do_delete),
                ft.OutlinedButton("Export PNG", on_click=do_export),
                ft.FilledButton("Edit", bgcolor=MUTED, color="#FFFFFF", on_click=do_edit),
            ],
        )
    )


def _shelf(children: list[ft.Control]) -> ft.Control:
    """A row of books standing on a wooden board."""
    return ft.Column(
        [
            ft.Row(children, spacing=26, vertical_alignment=ft.CrossAxisAlignment.END),
            ft.Container(
                height=15,
                border_radius=3,
                gradient=ft.LinearGradient(
                    begin=ft.Alignment.TOP_CENTER,
                    end=ft.Alignment.BOTTOM_CENTER,
                    colors=[WOOD_TOP, WOOD_BOTTOM],
                ),
                shadow=ft.BoxShadow(blur_radius=8, color="#40000000", offset=ft.Offset(0, 5)),
                margin=ft.Margin.only(top=-2),
            ),
        ],
        spacing=0,
        tight=True,
    )


def build_library(ctx: Ctx) -> ft.View:
    page = ctx.page
    try:
        reviews = ctx.store.list_reviews()
        covers = {
            r.id: (ctx.store.load_image(r.cover_image) if r.cover_image else None)
            for r in reviews
        }
        error = None
    except (StoreError, Exception) as e:  # noqa: BLE001
        reviews, covers, error = [], {}, str(e)

    narrow = (page.width or 1100) < 640
    side_pad = 20 if narrow else 48
    per_row = max(2, int(((page.width or 1100) - 2 * side_pad - 24) // (BOOK_W + 26)))
    shelves: list[ft.Control] = []
    for i in range(0, len(reviews), per_row):
        row = [_book_tile(ctx, r, covers.get(r.id)) for r in reviews[i : i + per_row]]
        shelves.append(_shelf(row))

    title_block = ft.Column(
        [
            heading("My Library"),
            body_text(
                f"{len(reviews)} review{'s' if len(reviews) != 1 else ''} on the shelf"
                + (f"  ·  {ctx.store.label}" if not error else ""),
                13,
                MUTED,
            ),
        ],
        spacing=2,
        tight=True,
    )
    async def go_templates(e):
        await page.push_route("/templates")

    new_btn = ft.FilledButton(
        "New review",
        icon=ft.Icons.ADD,
        bgcolor=MUTED,
        color="#FFFFFF",
        on_click=go_templates,
    )
    if narrow:
        header = ft.Column([title_block, new_btn], spacing=14, tight=True)
    else:
        header = ft.Row(
            [title_block, ft.Container(expand=True), new_btn],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    content: list[ft.Control] = [header, ft.Container(height=26)]
    if ctx.storage_note:
        content.append(
            ft.Container(
                content=body_text(ctx.storage_note, 13, "#8C6F3F"),
                bgcolor="#F4ECDD",
                border=ft.Border.all(1, "#D9C7A8"),
                border_radius=10,
                padding=12,
                margin=ft.Margin.only(bottom=18),
            )
        )
    if error:
        content.append(
            ft.Container(
                content=body_text(error, 14, "#A9464F"),
                bgcolor="#F7E9E7",
                border=ft.Border.all(1, "#E0C2BE"),
                border_radius=10,
                padding=16,
            )
        )
    elif not reviews:
        content.append(
            ft.Container(
                content=ft.Column(
                    [
                        heading("Your shelf is empty", 24, MUTED),
                        body_text("Pick a template and write your first review.", 14, MUTED),
                        ft.Container(height=10),
                        ft.OutlinedButton("Browse templates", on_click=go_templates),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    tight=True,
                ),
                alignment=ft.Alignment.CENTER,
                padding=ft.Padding.symmetric(vertical=80, horizontal=20),
            )
        )
    else:
        content.append(ft.Column(shelves, spacing=44))

    # staggered entrance: header first, then each shelf rises into place
    reveal = [prep_reveal(header, dy=0.02)]
    reveal += [prep_reveal(s, dy=0.03) for s in shelves[:6]]
    if not shelves:
        reveal.append(prep_reveal(content[-1], dy=0.03))

    view = ft.View(
        route="/",
        controls=[
            ft.SafeArea(
                content=ft.Container(
                    content=ft.Column(content, scroll=ft.ScrollMode.HIDDEN, expand=True),
                    padding=ft.Padding.symmetric(vertical=24 if narrow else 36, horizontal=side_pad),
                    expand=True,
                ),
                expand=True,
            )
        ],
        bgcolor=BG,
    )
    view._reveal = reveal
    return view


# ---------------------------------------------------------------------------
# template picker
# ---------------------------------------------------------------------------


def build_picker(ctx: Ctx) -> ft.View:
    page = ctx.page

    def pick(key: str):
        async def handler(e):
            review = Review.new(key)
            ctx.drafts[review.id] = (review, {})
            await page.push_route(f"/edit/{review.id}")

        return handler

    cards = []
    for key, spec in TEMPLATES.items():
        thumb = renderer.blank_template_jpeg(key)
        card = ft.Container(
            content=ft.Column(
                [
                    ft.Container(
                        content=ft.Image(src=thumb, width=227, border_radius=10),
                        border_radius=10,
                        shadow=ft.BoxShadow(blur_radius=8, color="#26000000", offset=ft.Offset(0, 3)),
                    ),
                    ft.Container(height=6),
                    ft.Text(spec.name, font_family="Gelasio SemiBold", size=16, color=INK),
                    body_text("1080 × 1920", 12, MUTED),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                tight=True,
                spacing=2,
            ),
            width=259,
            padding=14,
            border_radius=14,
            bgcolor=CARD,
            border=ft.Border.all(1, "#E7DCCB"),
            tooltip=f"Start a {spec.name} review",
            animate_scale=ft.Animation(200, _EASE_OUT),
            animate=ft.Animation(200, _EASE_OUT),
        )

        def hover(entered: bool, c=card, accent=spec.accent):
            c.scale = 1.025 if entered else 1.0
            c.border = ft.Border.all(1.2, accent if entered else "#E7DCCB")
            c.shadow = (
                ft.BoxShadow(blur_radius=18, color="#26000000", offset=ft.Offset(0, 8))
                if entered
                else None
            )
            c.update()

        cards.append(hoverable(card, hover, on_tap=pick(key)))

    async def go_home(e):
        await page.push_route("/")

    header = ft.Row(
        [
            ft.IconButton(ft.Icons.ARROW_BACK, icon_color=MUTED, on_click=go_home),
            heading("Pick a template"),
        ],
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )
    view = ft.View(
        route="/templates",
        controls=[
            ft.SafeArea(
                content=ft.Container(
                    content=ft.Column(
                        [
                            header,
                            body_text("Each genre has its own palette and mood — the layout stays the same.", 14, MUTED),
                            ft.Container(height=18),
                            ft.Row(cards, wrap=True, spacing=22, run_spacing=22),
                        ],
                        scroll=ft.ScrollMode.HIDDEN,
                        expand=True,
                    ),
                    padding=ft.Padding.symmetric(
                        vertical=24, horizontal=20 if (page.width or 1100) < 640 else 48
                    ),
                    expand=True,
                ),
                expand=True,
            )
        ],
        bgcolor=BG,
    )
    view._reveal = [prep_reveal(header, dy=0.015)] + [prep_reveal(c, dy=0.035) for c in cards]
    return view


# ---------------------------------------------------------------------------
# editor
# ---------------------------------------------------------------------------


def build_editor(ctx: Ctx, rid: str) -> ft.View | None:
    page = ctx.page

    if rid in ctx.drafts:
        review, images = ctx.drafts[rid]
        is_new = True
    else:
        review = ctx.store.get_review(rid)
        if review is None:
            return None
        images = load_images(ctx.store, review)
        ctx.drafts[rid] = (review, images)
        is_new = False

    spec = get_template(review.template_key)
    dirty = {"changed": is_new, "slots": set()}
    narrow = (page.width or 1100) < 900

    # --- live preview ------------------------------------------------------
    # JPEG keeps every update ~10x smaller than PNG — matters a lot on phones
    preview_scale = 0.45 if narrow else 0.5
    preview = ft.Image(
        src=renderer.render_jpeg(review, images, scale=preview_scale),
        width=min(410, (page.width or 1100) - 56),
        border_radius=10,
        gapless_playback=True,
    )
    render_seq = {"n": 0}

    async def refresh_preview(delay: float = 0.45):
        render_seq["n"] += 1
        mine = render_seq["n"]
        await asyncio.sleep(delay)
        if mine != render_seq["n"]:
            return
        preview.src = await asyncio.to_thread(
            renderer.render_jpeg, review, images, preview_scale
        )
        preview.update()

    def mark_dirty():
        dirty["changed"] = True
        if saved_note.value != "Unsaved changes":
            saved_note.value = "Unsaved changes"
            saved_note.update()

    # --- form fields ---------------------------------------------------------

    def text_field(label: str, value: str, attr: str, **kw):
        async def on_change(e):
            setattr(review, attr, e.control.value)
            mark_dirty()
            await refresh_preview()

        return ft.TextField(
            label=label,
            value=value,
            on_change=on_change,
            border_color="#D8C9B6",
            focused_border_color=spec.accent,
            label_style=ft.TextStyle(font_family="Karla", color=MUTED),
            text_style=ft.TextStyle(font_family="Karla", color=BODY),
            **kw,
        )

    title_f = text_field("Title", review.title, "title")
    author_f = text_field("Author", review.author, "author")
    pages_f = text_field("Pages", review.pages, "pages", width=140)
    days_f = text_field("Days to finish", review.days_taken, "days_taken", width=160)
    review_f = text_field(
        "My review", review.review_text, "review_text", multiline=True, min_lines=5, max_lines=12
    )

    stars_row = ft.Row(rating_icons(review.rating, spec.accent), spacing=2)
    rating_label = body_text(f"{review.rating:g} / 5", 14, MUTED)

    async def on_rating(e):
        # fires on every tick of a drag: update the cheap star icons only
        review.rating = round(float(e.control.value) * 2) / 2
        stars_row.controls = rating_icons(review.rating, spec.accent)
        rating_label.value = f"{review.rating:g} / 5"
        stars_row.update()
        rating_label.update()
        mark_dirty()

    async def on_rating_end(e):
        await refresh_preview(0.1)

    rating_slider = ft.Slider(
        value=review.rating, min=0, max=5, divisions=10,
        active_color=spec.accent, on_change=on_rating,
        on_change_end=on_rating_end, width=260,
    )

    # --- template switcher ---------------------------------------------------

    async def on_template(e):
        review.template_key = e.control.value
        mark_dirty()
        # accent colours in the form follow the template
        nonlocal spec
        spec = get_template(review.template_key)
        stars_row.controls = rating_icons(review.rating, spec.accent)
        rating_slider.active_color = spec.accent
        stars_row.update()
        rating_slider.update()
        await refresh_preview(0.15)

    template_dd = ft.Dropdown(
        label="Template",
        value=review.template_key,
        options=[ft.DropdownOption(key=k, text=t.name) for k, t in TEMPLATES.items()],
        on_select=on_template,
        width=260,
    )

    # --- image slots ----------------------------------------------------------

    slot_holders: dict[str, ft.Container] = {}

    def slot_content(slot: str, w: int, h: int) -> ft.Control:
        data = images.get(slot)
        if data:
            return ft.Stack(
                [
                    ft.Image(
                        src=_thumb(data, w * 3, h * 3),
                        width=w,
                        height=h,
                        fit=ft.BoxFit.COVER,
                        border_radius=8,
                    ),
                    ft.Container(
                        content=ft.IconButton(
                            ft.Icons.CLOSE,
                            icon_size=14,
                            icon_color="#FFFFFF",
                            bgcolor="#66000000",
                            on_click=remove_slot(slot),
                            tooltip="Remove image",
                        ),
                        alignment=ft.Alignment.TOP_RIGHT,
                    ),
                ],
                width=w,
                height=h,
            )
        return ft.Column(
            [
                ft.Icon(ft.Icons.ADD_PHOTO_ALTERNATE_OUTLINED, color=MUTED, size=22),
                body_text(SLOT_LABELS[slot], 11, MUTED),
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=4,
        )

    def pick_slot(slot: str):
        async def handler(e):
            files = await ctx.file_picker.pick_files(
                dialog_title=f"Choose {SLOT_LABELS[slot]}",
                file_type=ft.FilePickerFileType.IMAGE,
                with_data=True,
            )
            if not files:
                return
            f = files[0]
            data = f.bytes
            if data is None and f.path:
                data = await asyncio.to_thread(Path(f.path).read_bytes)
            if not data:
                snack(page, "Couldn't read that file.")
                return
            try:
                data = await asyncio.to_thread(normalize_image, data)
            except Exception:
                snack(page, "That doesn't look like an image I can read.")
                return
            images[slot] = data
            dirty["slots"].add(slot)
            mark_dirty()
            refresh_slot(slot)
            await refresh_preview(0.15)

        return handler

    def remove_slot(slot: str):
        async def handler(e):
            images[slot] = None
            dirty["slots"].add(slot)
            mark_dirty()
            refresh_slot(slot)
            await refresh_preview(0.15)

        return handler

    def slot_tile(slot: str, w: int, h: int) -> ft.Container:
        holder = ft.Container(
            width=w,
            height=h,
            border_radius=8,
            bgcolor="#FFFFFF",
            border=ft.Border.all(1.5, "#D8C9B6"),
            alignment=ft.Alignment.CENTER,
            content=slot_content(slot, w, h),
            on_click=pick_slot(slot),
            tooltip=f"Set {SLOT_LABELS[slot]}",
            animate=ft.Animation(180, _EASE_OUT),
        )

        def hover(e, c=holder):
            entered = e.data in (True, "true")
            c.border = ft.Border.all(1.5, spec.accent if entered else "#D8C9B6")
            c.update()

        holder.on_hover = hover
        slot_holders[slot] = holder
        return holder

    def refresh_slot(slot: str):
        holder = slot_holders[slot]
        w, h = int(holder.width), int(holder.height)
        holder.content = slot_content(slot, w, h)
        holder.update()

    cover_tile = slot_tile("cover", 118, 168)
    mood_tiles = ft.Row(
        [
            ft.Column([slot_tile("aes0", 128, 74), slot_tile("aes2", 128, 74)], spacing=10),
            ft.Column([slot_tile("aes1", 128, 74), slot_tile("aes3", 128, 74)], spacing=10),
        ],
        spacing=10,
    )

    # --- save / export ---------------------------------------------------------

    saved_note = body_text("Unsaved changes" if is_new else "All changes saved", 12, MUTED)

    def _persist():
        # upload new/changed images first, then the review row
        if "cover" in dirty["slots"]:
            old = review.cover_image
            review.cover_image = (
                ctx.store.save_image(images["cover"], "jpg") if images.get("cover") else None
            )
            if old:
                ctx.store.delete_image(old)
        for i in range(4):
            slot = f"aes{i}"
            if slot in dirty["slots"]:
                old = review.aesthetic_images[i]
                review.aesthetic_images[i] = (
                    ctx.store.save_image(images[slot], "jpg") if images.get(slot) else None
                )
                if old:
                    ctx.store.delete_image(old)
        review.touch()
        ctx.store.save_review(review)

    async def do_save(e):
        saved_note.value = "Saving…"
        saved_note.update()
        try:
            await asyncio.to_thread(_persist)
        except (StoreError, Exception) as err:  # noqa: BLE001
            saved_note.value = "Not saved"
            saved_note.update()
            snack(page, f"Save failed: {err}")
            return
        dirty["changed"] = False
        dirty["slots"].clear()
        saved_note.value = "All changes saved"
        saved_note.update()
        if ctx.invalidate:
            ctx.invalidate("/")  # the bookshelf needs to show this review
        snack(page, "Saved to your bookshelf.")

    async def do_export(e):
        snack(page, "Rendering full-size PNG…")
        await export_review(ctx, review, images)

    async def go_back(e):
        if dirty["changed"]:

            async def leave(e2):
                page.pop_dialog()
                ctx.drafts.pop(rid, None)
                await page.push_route("/")

            async def stay(e2):
                page.pop_dialog()

            page.show_dialog(
                ft.AlertDialog(
                    title=ft.Text("Leave without saving?", font_family="Gelasio SemiBold"),
                    content=body_text("Your latest edits haven't been saved."),
                    actions=[
                        ft.TextButton("Stay", on_click=stay),
                        ft.FilledButton("Discard", bgcolor="#A9464F", color="#FFFFFF", on_click=leave),
                    ],
                )
            )
        else:
            ctx.drafts.pop(rid, None)
            await page.push_route("/")

    form_children = [
        ft.Row(
            [
                ft.IconButton(ft.Icons.ARROW_BACK, icon_color=MUTED, on_click=go_back),
                heading("New review" if is_new else "Edit review", 26),
                ft.Container(expand=True),
                saved_note,
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        ft.Container(height=8),
        template_dd,
        ft.Container(height=4),
        title_f,
        author_f,
        ft.Row([pages_f, days_f], spacing=12),
        ft.Container(height=8),
        body_text("MY RATING", 12, MUTED),
        ft.Row([stars_row, rating_label], vertical_alignment=ft.CrossAxisAlignment.CENTER),
        rating_slider,
        ft.Container(height=8),
        review_f,
        ft.Container(height=10),
        ft.Row(
            [
                ft.Column([body_text("COVER", 12, MUTED), cover_tile], spacing=6, tight=True),
                ft.Column(
                    [body_text("THE AESTHETIC", 12, MUTED), mood_tiles], spacing=6, tight=True
                ),
            ],
            wrap=True,
            spacing=18,
            run_spacing=14,
            vertical_alignment=ft.CrossAxisAlignment.START,
        ),
        ft.Container(height=18),
        ft.Row(
            [
                ft.FilledButton(
                    "Save to bookshelf",
                    icon=ft.Icons.BOOKMARK_ADDED_OUTLINED,
                    bgcolor=MUTED,
                    color="#FFFFFF",
                    on_click=do_save,
                ),
                ft.OutlinedButton("Export PNG", icon=ft.Icons.IMAGE_OUTLINED, on_click=do_export),
            ],
            spacing=12,
        ),
    ]
    preview_block = ft.Column(
        [
            ft.Container(
                content=preview,
                border_radius=10,
                shadow=ft.BoxShadow(blur_radius=14, color="#30000000", offset=ft.Offset(0, 6)),
            ),
            ft.Container(height=6),
            body_text("Live preview — exports at 1080 × 1920", 12, MUTED),
        ],
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        tight=True,
    )

    if narrow:
        # phones: ONE scrollable column — nested scroll areas trap touch
        # gestures on iOS Safari
        body = ft.Column(
            form_children
            + [
                ft.Divider(height=28, color="#E2D5C3"),
                body_text("PREVIEW", 12, MUTED),
                ft.Container(height=6),
                preview_block,
                ft.Container(height=40),
            ],
            scroll=ft.ScrollMode.HIDDEN,
            spacing=10,
            expand=True,
        )
        reveal = [prep_reveal(body, dy=0.02)]
    else:
        form = ft.Column(
            form_children + [ft.Container(height=30)],
            scroll=ft.ScrollMode.HIDDEN,
            spacing=10,
            col={"md": 6, "lg": 5},
        )
        preview_panel = ft.Container(
            content=ft.Column(
                [preview_block],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                scroll=ft.ScrollMode.HIDDEN,
            ),
            alignment=ft.Alignment.TOP_CENTER,
            padding=ft.Padding.only(left=10, top=16, bottom=16),
            col={"md": 6, "lg": 7},
        )
        body = ft.ResponsiveRow(
            [form, preview_panel],
            expand=True,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )
        reveal = [prep_reveal(form, dy=0.02), prep_reveal(preview_panel, dy=0.03)]

    view = ft.View(
        route=f"/edit/{rid}",
        controls=[
            ft.SafeArea(
                content=ft.Container(
                    content=body,
                    padding=ft.Padding.symmetric(
                        vertical=16 if narrow else 24, horizontal=16 if narrow else 40
                    ),
                    expand=True,
                ),
                expand=True,
            )
        ],
        bgcolor=BG,
    )
    view._reveal = reveal
    return view
