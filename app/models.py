"""Data model for a book review."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


@dataclass
class Review:
    id: str
    template_key: str
    title: str = ""
    author: str = ""
    pages: str = ""
    days_taken: str = ""
    rating: float = 0.0
    review_text: str = ""
    cover_image: str | None = None
    aesthetic_images: list[str | None] = field(default_factory=lambda: [None] * 4)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    @classmethod
    def new(cls, template_key: str) -> "Review":
        return cls(id=new_id(), template_key=template_key)

    def touch(self) -> None:
        self.updated_at = _now()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "template_key": self.template_key,
            "title": self.title,
            "author": self.author,
            "pages": self.pages,
            "days_taken": self.days_taken,
            "rating": self.rating,
            "review_text": self.review_text,
            "cover_image": self.cover_image,
            "aesthetic_images": self.aesthetic_images,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Review":
        aes = d.get("aesthetic_images") or []
        if isinstance(aes, str):
            aes = json.loads(aes)
        aes = (list(aes) + [None] * 4)[:4]
        return cls(
            id=d["id"],
            template_key=d.get("template_key", "romance"),
            title=d.get("title") or "",
            author=d.get("author") or "",
            pages=str(d.get("pages") or ""),
            days_taken=str(d.get("days_taken") or ""),
            rating=float(d.get("rating") or 0),
            review_text=d.get("review_text") or "",
            cover_image=d.get("cover_image"),
            aesthetic_images=aes,
            created_at=d.get("created_at") or _now(),
            updated_at=d.get("updated_at") or _now(),
        )
