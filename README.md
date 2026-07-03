# Book Review App

A personal book-review studio. Pick one of seven genre templates (Romance, Thriller · Mystery,
Sci-fi, Horror, Slice of life, Emotional · Life lessons, Biography · History), fill in the
book details, drop in a cover and mood images, rate it with half-stars, and save it to a
library that looks like a bookshelf. Any review can be re-opened, edited, and exported as a
1080 × 1920 PNG that matches the original Instagram-story design pixel for pixel.

Built with [Flet](https://flet.dev) (Python + Flutter), Pillow for rendering, and Supabase
for storage (with a local SQLite fallback).

## Project layout

| Path | What it is |
|---|---|
| `main.py` | Entry point: desktop window locally, web server when `PORT` is set |
| `app/templates.py` | The seven genre template specs (palettes, motifs, type) |
| `app/renderer.py` | Pillow renderer — the live preview and the PNG export share this |
| `app/storage.py` | Supabase (PostgREST + Storage) and local SQLite backends |
| `app/ui.py` | All views: login, bookshelf library, template picker, editor |
| `assets/fonts/` | Gelasio + Karla (bundled, used by both UI and renderer) |
| `supabase_schema.sql` | One-time Supabase table setup (see below) |

## Running on your Mac

```bash
source .venv/bin/activate
python main.py            # opens the native desktop window
```

Configuration lives in `.env` (already set up, and git-ignored — never commit it):

- `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` — your Supabase project
- `STORAGE_BACKEND` — `auto` (default), `supabase`, or `local`
- `APP_PASSWORD` — set a password to require login; empty = no login screen

With `auto`, the app uses Supabase when it's reachable and set up, otherwise it saves to a
local database on the device (`~/Library/Application Support/BookReviewApp` on Mac).

## One-time Supabase setup

The storage bucket (`review-images`) is created automatically, but Supabase does not allow
table creation through the API, so once:

1. Open your Supabase dashboard → **SQL Editor**
2. Paste the contents of `supabase_schema.sql` and click **Run**
3. Restart the app — the library header should say "stored in Supabase"

## Deploying to Railway

1. Push this repo to GitHub (the `.env` file stays local; secrets go in Railway).
2. In Railway: **New Project → Deploy from GitHub repo**. Railway detects Python via
   `requirements.txt` and starts the app with the `Procfile` (`python main.py`).
3. In the service **Variables**, add:
   - `SUPABASE_URL` = your project URL
   - `SUPABASE_SERVICE_KEY` = your service role key
   - `APP_PASSWORD` = a password you choose (required — this URL is public!)
4. **Settings → Networking → Generate Domain** to get your URL.

`PORT` is provided by Railway automatically; the app switches to web-server mode when it
sees it.

## Using it on iPhone / Android

The simplest path: open your Railway URL in Safari/Chrome on the phone and use
**Share → Add to Home Screen**. You get a full-screen app icon backed by the same Supabase
library as the Mac app — reviews stay in sync because both talk to the same database.

For a fully native install later (no server needed), Flet supports packaging the same code
as an iOS/Android app with `flet build ipa` / `flet build apk` — that route needs Xcode /
Android SDK and an Apple developer account, so treat it as a future step. See
https://flet.dev/docs/publish for the current instructions.

## Security notes

- The **service role key bypasses all Supabase security rules** — treat it like a root
  password. It belongs only in `.env` (local) and Railway Variables (cloud), never in git.
- The key was pasted into a chat conversation during development. When convenient, rotate
  it: Supabase dashboard → Settings → API → "Reset" the service role key, then update
  `.env` and Railway.
- RLS is enabled on the `reviews` table with no policies, so the public `anon` key can
  read nothing. If the app ever goes multi-user, add per-user policies then.
