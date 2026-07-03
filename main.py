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
    try:
        page.theme = ft.Theme(font_family="Karla", color_scheme_seed="#8A7767")
    except Exception:
        pass

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

    async def route_change(e=None):
        route = page.route or "/"
        if ctx.password and not ctx.authed:
            page.views = [ui.build_login(ctx)]
            page.update()
            return

        troute = ft.TemplateRoute(route)
        if troute.match("/templates"):
            view = await asyncio.to_thread(ui.build_picker, ctx)
        elif troute.match("/edit/:rid"):
            view = await asyncio.to_thread(ui.build_editor, ctx, troute.rid)
            if view is None:
                ui.snack(page, "That review no longer exists.")
                view = await asyncio.to_thread(ui.build_library, ctx)
        else:
            view = await asyncio.to_thread(ui.build_library, ctx)
        page.views = [view]
        page.update()

    ctx.rebuild = route_change

    last_width = {"w": page.width or 0}

    async def resized(e):
        # Reflow the bookshelf when the window width really changes. iOS
        # Safari fires resize constantly as its toolbar hides/shows while
        # scrolling — rebuilding then would make scrolling feel broken.
        w = page.width or 0
        if abs(w - last_width["w"]) < 60:
            return
        last_width["w"] = w
        if (page.route or "/") == "/" and (not ctx.password or ctx.authed):
            await route_change()

    page.on_route_change = route_change
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
