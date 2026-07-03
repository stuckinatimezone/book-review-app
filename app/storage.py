"""Storage backends: Supabase (primary) and local SQLite (fallback).

Both stores share the same interface:
    list_reviews() -> list[Review]
    get_review(id) -> Review | None
    save_review(review)
    delete_review(review)          # also removes its images
    save_image(data, ext) -> key
    load_image(key) -> bytes | None
    delete_image(key)
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
import uuid
from pathlib import Path

import httpx

from .models import Review


class StoreError(Exception):
    """Raised with a user-readable message when a storage operation fails."""


# --------------------------------------------------------------------------
# Local SQLite store
# --------------------------------------------------------------------------


class LocalStore:
    label = "stored on this device"

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.images_dir = data_dir / "images"
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(data_dir / "reviews.db", check_same_thread=False)
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS reviews (
                id TEXT PRIMARY KEY,
                template_key TEXT NOT NULL,
                title TEXT DEFAULT '',
                author TEXT DEFAULT '',
                pages TEXT DEFAULT '',
                rating REAL DEFAULT 0,
                review_text TEXT DEFAULT '',
                cover_image TEXT,
                aesthetic_images TEXT DEFAULT '[]',
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
        self._db.commit()

    def _row_to_review(self, row) -> Review:
        cols = [
            "id", "template_key", "title", "author", "pages", "rating",
            "review_text", "cover_image", "aesthetic_images", "created_at", "updated_at",
        ]
        return Review.from_dict(dict(zip(cols, row)))

    def list_reviews(self) -> list[Review]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM reviews ORDER BY updated_at DESC"
            ).fetchall()
        return [self._row_to_review(r) for r in rows]

    def get_review(self, review_id: str) -> Review | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM reviews WHERE id = ?", (review_id,)
            ).fetchone()
        return self._row_to_review(row) if row else None

    def save_review(self, review: Review) -> None:
        d = review.to_dict()
        d["aesthetic_images"] = json.dumps(d["aesthetic_images"])
        with self._lock:
            self._db.execute(
                """
                INSERT INTO reviews (id, template_key, title, author, pages, rating,
                    review_text, cover_image, aesthetic_images, created_at, updated_at)
                VALUES (:id, :template_key, :title, :author, :pages, :rating,
                    :review_text, :cover_image, :aesthetic_images, :created_at, :updated_at)
                ON CONFLICT(id) DO UPDATE SET
                    template_key=:template_key, title=:title, author=:author,
                    pages=:pages, rating=:rating, review_text=:review_text,
                    cover_image=:cover_image, aesthetic_images=:aesthetic_images,
                    updated_at=:updated_at
                """,
                d,
            )
            self._db.commit()

    def delete_review(self, review: Review) -> None:
        for key in [review.cover_image, *review.aesthetic_images]:
            if key:
                self.delete_image(key)
        with self._lock:
            self._db.execute("DELETE FROM reviews WHERE id = ?", (review.id,))
            self._db.commit()

    def save_image(self, data: bytes, ext: str = "png") -> str:
        key = f"{uuid.uuid4()}.{ext}"
        (self.images_dir / key).write_bytes(data)
        return key

    def load_image(self, key: str) -> bytes | None:
        p = self.images_dir / key
        return p.read_bytes() if p.exists() else None

    def delete_image(self, key: str) -> None:
        (self.images_dir / key).unlink(missing_ok=True)


# --------------------------------------------------------------------------
# Supabase store (PostgREST + Storage API)
# --------------------------------------------------------------------------

SCHEMA_SQL_HINT = (
    "The 'reviews' table is missing in Supabase. Open your Supabase dashboard → "
    "SQL Editor, paste the contents of supabase_schema.sql (in the project folder) "
    "and click Run. Then restart the app."
)


class SupabaseStore:
    label = "stored in Supabase"

    def __init__(self, url: str, key: str, bucket: str = "review-images"):
        self.url = url.rstrip("/")
        self.bucket = bucket
        self._client = httpx.Client(
            headers={"apikey": key, "Authorization": f"Bearer {key}"},
            timeout=30,
        )
        self._image_cache: dict[str, bytes] = {}
        self._cache_lock = threading.Lock()

    # -- setup ---------------------------------------------------------------

    def ensure_ready(self) -> None:
        """Verify the table exists and the bucket is present."""
        r = self._client.get(f"{self.url}/rest/v1/reviews", params={"limit": "1"})
        if r.status_code == 404:
            raise StoreError(SCHEMA_SQL_HINT)
        if r.is_error:
            raise StoreError(f"Supabase error: {r.status_code} {r.text[:200]}")
        b = self._client.post(
            f"{self.url}/storage/v1/bucket",
            json={"id": self.bucket, "name": self.bucket, "public": False},
        )
        # "already exists" is fine; Supabase reports it as HTTP 400/409 with
        # "Duplicate" in the body
        if b.is_error and b.status_code != 409 and "Duplicate" not in b.text:
            raise StoreError(f"Could not create storage bucket: {b.text[:200]}")

    # -- reviews ---------------------------------------------------------------

    def list_reviews(self) -> list[Review]:
        r = self._client.get(
            f"{self.url}/rest/v1/reviews",
            params={"select": "*", "order": "updated_at.desc"},
        )
        self._raise_for(r)
        return [Review.from_dict(d) for d in r.json()]

    def get_review(self, review_id: str) -> Review | None:
        r = self._client.get(
            f"{self.url}/rest/v1/reviews",
            params={"select": "*", "id": f"eq.{review_id}"},
        )
        self._raise_for(r)
        rows = r.json()
        return Review.from_dict(rows[0]) if rows else None

    def save_review(self, review: Review) -> None:
        r = self._client.post(
            f"{self.url}/rest/v1/reviews",
            headers={"Prefer": "resolution=merge-duplicates"},
            json=review.to_dict(),
        )
        self._raise_for(r)

    def delete_review(self, review: Review) -> None:
        for key in [review.cover_image, *review.aesthetic_images]:
            if key:
                self.delete_image(key)
        r = self._client.delete(
            f"{self.url}/rest/v1/reviews", params={"id": f"eq.{review.id}"}
        )
        self._raise_for(r)

    # -- images ----------------------------------------------------------------

    def save_image(self, data: bytes, ext: str = "png") -> str:
        key = f"{uuid.uuid4()}.{ext}"
        r = self._client.post(
            f"{self.url}/storage/v1/object/{self.bucket}/{key}",
            content=data,
            headers={
                "Content-Type": f"image/{'jpeg' if ext in ('jpg', 'jpeg') else ext}",
                "x-upsert": "true",
            },
        )
        self._raise_for(r)
        with self._cache_lock:
            self._image_cache[key] = data
        return key

    def load_image(self, key: str) -> bytes | None:
        with self._cache_lock:
            if key in self._image_cache:
                return self._image_cache[key]
        r = self._client.get(f"{self.url}/storage/v1/object/{self.bucket}/{key}")
        # Supabase storage reports missing objects as 400/"not_found" (or plain 404)
        if r.status_code == 404 or (r.status_code == 400 and "not_found" in r.text):
            return None
        self._raise_for(r)
        with self._cache_lock:
            self._image_cache[key] = r.content
        return r.content

    def delete_image(self, key: str) -> None:
        self._client.delete(f"{self.url}/storage/v1/object/{self.bucket}/{key}")
        with self._cache_lock:
            self._image_cache.pop(key, None)

    def _raise_for(self, r: httpx.Response) -> None:
        if r.is_error:
            if r.status_code == 404 and "PGRST205" in r.text:
                raise StoreError(SCHEMA_SQL_HINT)
            raise StoreError(f"Supabase error {r.status_code}: {r.text[:200]}")


# --------------------------------------------------------------------------
# factory
# --------------------------------------------------------------------------


def default_data_dir() -> Path:
    # Flet sets this on iOS/Android to the app's sandboxed storage
    mobile = os.getenv("FLET_APP_STORAGE_DATA")
    if mobile:
        return Path(mobile)
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "BookReviewApp"
    if os.name == "nt":
        return Path(os.getenv("APPDATA", str(Path.home()))) / "BookReviewApp"
    return Path(os.getenv("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "book-review-app"


def get_store():
    """Pick the storage backend from environment configuration.

    Returns (store, warning). ``warning`` is a user-readable message when the
    preferred backend was unavailable and a fallback is in use.
    """
    backend = os.getenv("STORAGE_BACKEND", "auto").lower()
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SERVICE_KEY", "").strip()

    if backend in ("auto", "supabase") and url and key:
        store = SupabaseStore(url, key)
        try:
            store.ensure_ready()
            return store, None
        except (StoreError, httpx.HTTPError) as e:
            if backend == "supabase":
                raise
            local = LocalStore(default_data_dir())
            return local, f"Supabase unavailable — saving on this device instead. ({e})"
    if backend == "supabase":
        raise StoreError("STORAGE_BACKEND=supabase but SUPABASE_URL / SUPABASE_SERVICE_KEY are not set.")
    return LocalStore(default_data_dir()), None
