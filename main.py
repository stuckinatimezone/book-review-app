"""Book Review App — entry point.

Desktop window (Mac / Windows / Linux):   python main.py
Serve on your network (phones/tablets):   python main.py --serve [--port 8550]
Railway / any cloud host:                 starts automatically in web mode
                                          (the platform sets the PORT variable)
"""

from __future__ import annotations

import argparse
import asyncio
import os
import socket
import threading

from pathlib import Path

import flet as ft
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from app import ui  # noqa: E402
from app.storage import StoreError, get_store  # noqa: E402

_store_lock = threading.Lock()
_store_cache: dict = {}


def _store_once():
    """Create the storage backend once per process."""
    with _store_lock:
        if "store" not in _store_cache:
            try:
                store, note = get_store()
            except (StoreError, Exception) as e:  # noqa: BLE001
                store, note = None, str(e)
            _store_cache["store"] = store
            _store_cache["note"] = note
    return _store_cache["store"], _store_cache["note"]


async def main(page: ft.Page):
    page.title = "Book Review App"
    page.bgcolor = ui.BG
    page.padding = 0
    page.fonts = {
        "Gelasio": "/fonts/Gelasio-Regular.ttf",
        "Gelasio SemiBold": "/fonts/Gelasio-SemiBold.ttf",
        "Karla": "/fonts/Karla-Regular.ttf",
        "Karla Bold": "/fonts/Karla-Bold.ttf",
    }
    page.theme = ft.Theme(
        font_family="Karla",
        color_scheme_seed="#8A7767",
        visual_density=ft.VisualDensity.COMFORTABLE,
        # soft, warm feedback colours instead of stark Material ripples
        splash_color="#1A8A7767",
        highlight_color="#148A7767",
        hover_color="#0F8A7767",
        # iOS-style slide transitions between views on every platform
        page_transitions=ft.PageTransitionsTheme(
            android=ft.PageTransitionTheme.CUPERTINO,
            ios=ft.PageTransitionTheme.CUPERTINO,
            linux=ft.PageTransitionTheme.CUPERTINO,
            macos=ft.PageTransitionTheme.CUPERTINO,
            windows=ft.PageTransitionTheme.CUPERTINO,
        ),
        # thin, rounded, fades away when not scrolling (for the few places
        # that still show one — main columns hide theirs entirely)
        scrollbar_theme=ft.ScrollbarTheme(
            thumb_visibility=False,
            track_visibility=False,
            thickness=3,
            radius=8,
            thumb_color="#668A7767",
            cross_axis_margin=2,
        ),
        dialog_theme=ft.DialogTheme(
            bgcolor=ui.CARD,
            shape=ft.RoundedRectangleBorder(radius=22),
            barrier_color="#3D2A1F14",
            elevation=8,
            title_text_style=ft.TextStyle(font_family="Gelasio SemiBold", size=22, color=ui.INK),
            content_text_style=ft.TextStyle(font_family="Karla", size=14, color=ui.BODY),
        ),
        snackbar_theme=ft.SnackBarTheme(
            behavior=ft.SnackBarBehavior.FLOATING,
            bgcolor=ui.INK,
            shape=ft.RoundedRectangleBorder(radius=14),
            elevation=6,
            content_text_style=ft.TextStyle(font_family="Karla", size=14, color=ui.BG),
        ),
        filled_button_theme=ft.FilledButtonTheme(
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=12),
                animation_duration=250,
                padding=ft.Padding.symmetric(vertical=12, horizontal=20),
            )
        ),
        outlined_button_theme=ft.OutlinedButtonTheme(
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=12),
                animation_duration=250,
                side=ft.BorderSide(1.2, "#B9A691"),
                color="#6F5F50",
                padding=ft.Padding.symmetric(vertical=12, horizontal=18),
            )
        ),
        text_button_theme=ft.TextButtonTheme(
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=10), animation_duration=200
            )
        ),
    )

    store, note = await asyncio.to_thread(_store_once)

    picker = ft.FilePicker()
    page.services.append(picker)

    ctx = ui.Ctx(
        page=page,
        store=store,
        file_picker=picker,
        password=os.getenv("APP_PASSWORD", "").strip(),
        storage_note=note,
    )

    # Views are cached per route and stacked (library at the bottom), so
    # navigating pushes/pops with the Cupertino slide instead of swapping
    # the whole screen.
    view_cache: dict[str, ft.View] = {}

    def invalidate(*routes):
        if routes:
            for r in routes:
                view_cache.pop(r, None)
        else:
            view_cache.clear()

    ctx.invalidate = invalidate

    async def cached_view(route: str, builder, *args) -> ft.View:
        if route not in view_cache:
            view_cache[route] = await asyncio.to_thread(builder, *args)
        return view_cache[route]

    async def route_change(e=None):
        route = page.route or "/"
        if ctx.password and not ctx.authed:
            views = [ui.build_login(ctx)]
        else:
            troute = ft.TemplateRoute(route)
            views = [await cached_view("/", ui.build_library, ctx)]
            if troute.match("/templates"):
                views.append(await cached_view("/templates", ui.build_picker, ctx))
            elif troute.match("/edit/:rid"):
                editor = await asyncio.to_thread(ui.build_editor, ctx, troute.rid)
                if editor is None:
                    ui.snack(page, "That review no longer exists.")
                else:
                    views.append(editor)
        page.views = views
        page.update()
        page.run_task(ui.play_reveal, page.views[-1])

    ctx.rebuild = route_change

    async def view_pop(e):
        # back gesture / swipe: pop to the view underneath
        if len(page.views) > 1:
            await page.push_route(page.views[-2].route)

    last_width = {"w": page.width or 0}

    async def resized(e):
        # Reflow when the window width really changes. iOS Safari fires
        # resize constantly as its toolbar hides/shows while scrolling —
        # rebuilding then would make scrolling feel broken.
        w = page.width or 0
        if abs(w - last_width["w"]) < 60:
            return
        last_width["w"] = w
        invalidate()
        if (page.route or "/") == "/" and (not ctx.password or ctx.authed):
            await route_change()

    page.on_route_change = route_change
    page.on_view_pop = view_pop
    page.on_resized = resized
    await route_change()


def _lan_ip() -> str:
    """Best-effort local network address, for phones on the same wifi."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))  # no traffic is sent; just picks the route
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Book Review App")
    parser.add_argument(
        "--serve",
        action="store_true",
        help="run as a web server instead of a desktop window "
        "(so phones/tablets on your network can use it)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("PORT") or 8550),
        help="port for --serve mode (default: $PORT or 8550)",
    )
    args = parser.parse_args()

    # Cloud platforms (Railway, etc.) set PORT — that implies web mode.
    serve = args.serve or bool(os.getenv("PORT"))
    if serve:
        os.environ.setdefault("FLET_FORCE_WEB_SERVER", "true")
        if not os.getenv("PORT"):  # started by hand, not by a cloud platform
            print("Book Review App is serving:", flush=True)
            print(f"  on this computer:      http://localhost:{args.port}", flush=True)
            print(f"  on phones (same wifi): http://{_lan_ip()}:{args.port}", flush=True)
            print("Press Ctrl+C to stop.", flush=True)
        ft.run(
            main,
            host="0.0.0.0",
            port=args.port,
            view=ft.AppView.WEB_BROWSER,
            assets_dir="assets",
        )
    else:
        ft.run(main, assets_dir="assets")
