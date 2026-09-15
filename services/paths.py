from __future__ import annotations

from pathlib import Path
import json


ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def paths_config() -> dict:
    return load_json(ROOT / "config" / "paths.json")


def resolve_from_root(rel: str) -> Path:
    p = Path(rel)
    if p.is_absolute():
        return p
    return (ROOT / p).resolve()


def source_path(key: str) -> Path:
    cfg = paths_config()
    return resolve_from_root(cfg[key])


def exam_profile_path(subject: str | None = None) -> Path:
    if (subject or "").lower() == "english":
        return ROOT / "config" / "exam_profiles" / "grade10_english.json"
    return ROOT / "config" / "exam_profiles" / "grade10_math.json"


def formats_path(subject: str | None = None) -> Path:
    if (subject or "").lower() == "english":
        return ROOT / "config" / "formats" / "grade10_english_formats.json"
    return ROOT / "config" / "formats" / "grade10_math_formats.json"


def book_data_dir(subject: str | None = None) -> Path:
    if (subject or "").lower() == "english":
        return ROOT / "data" / "books" / "grade10_english"
    return ROOT / "data" / "books" / "grade10_math"


def sample_data_dir() -> Path:
    return ROOT / "data" / "samples"


def mpbse_data_dir() -> Path:
    return ROOT / "data" / "mpbse"


def output_exams_dir() -> Path:
    return ROOT / "output" / "exams"


def logs_dir() -> Path:
    return ROOT / "logs"
