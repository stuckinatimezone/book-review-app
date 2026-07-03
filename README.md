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

## Hosting — works the same everywhere

All reviews and images live in Supabase, so you can switch between hosts at any time and
your library follows you. Every host serves every device (iPhone, Android, Mac, Windows —
anything with a browser).

| You want | Do this |
|---|---|
| Use it on the computer in front of you | `python main.py` (native desktop window, Mac or Windows) |
| Host it from your Mac/Windows PC for your phone | `python main.py --serve` and open the printed wifi URL on the phone |
| Host it in the cloud (works from anywhere) | Deploy to Railway (below) |

### First-time setup on any computer (Mac or Windows)

```bash
# Mac
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Windows (PowerShell)
py -m venv .venv ; .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Then copy `.env.example` to `.env` and fill in your Supabase details. Configuration:

- `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` — your Supabase project
- `STORAGE_BACKEND` — `supabase` (recommended so every host shares one library),
  `local`, or `auto` (Supabase when reachable, otherwise this device)
- `APP_PASSWORD` — set a password to require login; empty = no login screen

### Hosting from your own computer for your phone

```bash
python main.py --serve            # add --port 9000 to pick another port
```

It prints two addresses — open the "phones (same wifi)" one in Safari/Chrome on the phone.
Notes:

- Phone and computer must be on the same wifi network.
- macOS will ask "allow incoming network connections?" the first time — click Allow.
  On Windows, allow it through Windows Defender Firewall if prompted.
- The computer must stay awake while you're using it from the phone.

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

Open the app URL (Railway domain, or the wifi URL when hosting from your own computer) in
Safari/Chrome and use **Share → Add to Home Screen** (Android: menu → **Add to Home
screen**). You get a full-screen app icon backed by the same Supabase library as every
other device — reviews stay in sync because everything talks to the same database.

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
