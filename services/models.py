from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


def to_dict(obj: Any) -> Any:
    if hasattr(obj, "__dataclass_fields__"):
        return asdict(obj)
    return obj


@dataclass
class AllowedContentSet:
    allowed_chapter_ids: list[str]
    allowed_topic_ids: list[str]
    allowed_page_ranges: list[dict]
    eligible_book_question_ids: list[str]
    excluded_question_ids: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    subject: str = "Mathematics"
    allowed_item_names: list[str] = field(default_factory=list)
    allowed_prose: list[str] = field(default_factory=list)
    allowed_poems: list[str] = field(default_factory=list)
    missing_sources: list[str] = field(default_factory=list)
    syllabus_groups: list[dict] = field(default_factory=list)
