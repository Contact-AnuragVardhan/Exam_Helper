from __future__ import annotations

import hashlib
import os
from pathlib import Path

from .logger import get_logger


log = get_logger("english_scene")

SCENES = (
    "marketplace",
    "playground",
    "railway_station",
    "park_cleanup",
)


def choose_scene(seed: str = "") -> str:
    h = hashlib.sha1((seed or "english-q6").encode("utf-8")).hexdigest()
    return SCENES[int(h[:8], 16) % len(SCENES)]


def generate_scene_image(dest: Path, scene_id: str = "", seed: str = "") -> Path | None:
    """Create a photocopy-friendly B/W exam illustration. Returns dest or None."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    scene = scene_id or choose_scene(seed)
    if _try_openai_image(dest, scene):
        _to_high_contrast_bw(dest)
        if dest.exists() and dest.stat().st_size > 800:
            log.info("Q6 image via OpenAI scene=%s path=%s", scene, dest)
            return dest
    if _draw_line_art_scene(dest, scene):
        log.info("Q6 image via line-art scene=%s path=%s", scene, dest)
        return dest
    log.error("Q6 image generation failed scene=%s", scene)
    return None


def _try_openai_image(dest: Path, scene: str) -> bool:
    if os.getenv("MOCK_GENERATION", "false").strip().lower() in ("1", "true", "yes"):
        return False
    if os.getenv("ENGLISH_Q6_OPENAI", "").strip().lower() not in ("1", "true", "yes"):
        return False
    if not (os.getenv("OPENAI_API_KEY") or "").strip():
        return False
    prompt = (
        "Simple black-and-white school-exam illustration, clean high-contrast "
        "worksheet line-art, photocopy-friendly, rectangular landscape, no colour, "
        "no text labels, no watermark, no caption. Scene: "
        + _scene_prompt(scene)
    )
    try:
        from openai import OpenAI

        client = OpenAI()
        resp = client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size="1792x1024",
            n=1,
        )
        url = ((resp.data or [None])[0].url if resp.data else None) or ""
        if not url:
            return False
        import urllib.request

        urllib.request.urlretrieve(url, dest)
        return dest.exists() and dest.stat().st_size > 800
    except Exception as e:
        log.warning("OpenAI scene image skipped: %s", e)
        return False


def _scene_prompt(scene: str) -> str:
    return {
        "marketplace": (
            "a busy village marketplace with three stalls under awnings, "
            "vendors, shoppers, baskets of vegetables, a bicycle, and a tree"
        ),
        "playground": (
            "a school playground with a slide, a swing, children playing, "
            "a teacher watching, a ball, and a tree"
        ),
        "railway_station": (
            "a railway station platform with a train, passengers, luggage, "
            "a vendor with a cart, and a clock"
        ),
        "park_cleanup": (
            "a community park cleanup with people picking litter, a dustbin, "
            "saplings, a wheelbarrow, and children helping"
        ),
    }.get(scene, "a busy village marketplace with stalls, people, and baskets")


def _to_high_contrast_bw(path: Path) -> None:
    try:
        import fitz

        pix = fitz.Pixmap(str(path))
        if pix.alpha:
            pix = fitz.Pixmap(pix, 0)
        if pix.n > 1:
            pix = fitz.Pixmap(fitz.csGRAY, pix)
        pix.save(str(path))
    except Exception as e:
        log.warning("B/W conversion skipped: %s", e)


def _draw_line_art_scene(dest: Path, scene: str) -> bool:
    try:
        import shutil
        import tempfile

        import fitz
    except Exception as e:
        log.error("Cannot draw scene image: %s", e)
        return False
    try:
        w, h = 720, 430
        doc = fitz.open()
        page = doc.new_page(width=w, height=h)
        page.draw_rect(page.rect, color=(0, 0, 0), fill=(1, 1, 1), width=2)
        if scene == "playground":
            _scene_playground(page, w, h)
        elif scene == "railway_station":
            _scene_station(page, w, h)
        elif scene == "park_cleanup":
            _scene_cleanup(page, w, h)
        else:
            _scene_marketplace(page, w, h)
        pix = page.get_pixmap(dpi=140)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        pix.save(str(tmp_path))
        doc.close()
        if tmp_path.stat().st_size <= 800:
            tmp_path.unlink(missing_ok=True)
            log.error("Drawn scene PNG too small scene=%s", scene)
            return False
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(tmp_path, dest)
        tmp_path.unlink(missing_ok=True)
        return dest.exists()
    except Exception as e:
        log.error("Cannot draw scene image: %s", e)
        return False


def _ink(page, color=(0, 0, 0), width=1.6):
    return {"color": color, "width": width}


def _person(page, x, y, scale=1.0, facing=1):
    s = scale
    page.draw_circle(fitz_point(x, y - 20 * s), 6.2 * s, **_ink(page, width=1.5))
    page.draw_line(fitz_point(x, y - 14 * s), fitz_point(x, y + 8 * s), **_ink(page, width=1.5))
    page.draw_line(fitz_point(x, y - 6 * s), fitz_point(x - 12 * s * facing, y + 2 * s), **_ink(page, width=1.4))
    page.draw_line(fitz_point(x, y - 6 * s), fitz_point(x + 11 * s * facing, y + 1 * s), **_ink(page, width=1.4))
    page.draw_line(fitz_point(x, y + 8 * s), fitz_point(x - 8 * s, y + 24 * s), **_ink(page, width=1.4))
    page.draw_line(fitz_point(x, y + 8 * s), fitz_point(x + 9 * s, y + 24 * s), **_ink(page, width=1.4))


def fitz_point(x, y):
    import fitz

    return fitz.Point(x, y)


def _tree(page, x, y):
    import fitz

    page.draw_rect(fitz.Rect(x - 4, y - 10, x + 4, y + 36), color=(0, 0, 0), width=1.4)
    page.draw_circle(fitz.Point(x, y - 22), 18, color=(0, 0, 0), width=1.5)
    page.draw_circle(fitz.Point(x - 12, y - 12), 12, color=(0, 0, 0), width=1.4)
    page.draw_circle(fitz.Point(x + 12, y - 12), 12, color=(0, 0, 0), width=1.4)


def _basket(page, x, y):
    import fitz

    page.draw_rect(fitz.Rect(x, y, x + 22, y + 14), color=(0, 0, 0), width=1.3)
    page.draw_line(fitz.Point(x + 2, y), fitz.Point(x + 20, y), color=(0, 0, 0), width=1.2)
    page.draw_circle(fitz.Point(x + 7, y - 4), 4, color=(0, 0, 0), width=1.2)
    page.draw_circle(fitz.Point(x + 15, y - 4), 4, color=(0, 0, 0), width=1.2)


def _scene_marketplace(page, w, h):
    import fitz

    ground = h - 70
    page.draw_line(fitz.Point(20, ground), fitz.Point(w - 20, ground), **_ink(page, width=2))
    # stalls
    for i, x in enumerate((90, 300, 510)):
        page.draw_rect(fitz.Rect(x, ground - 110, x + 130, ground), color=(0, 0, 0), width=1.6)
        page.draw_line(fitz.Point(x - 10, ground - 110), fitz.Point(x + 65, ground - 150), **_ink(page, width=1.8))
        page.draw_line(fitz.Point(x + 140, ground - 110), fitz.Point(x + 65, ground - 150), **_ink(page, width=1.8))
        page.draw_line(fitz.Point(x - 10, ground - 110), fitz.Point(x + 140, ground - 110), **_ink(page, width=1.5))
        _basket(page, x + 18, ground - 28)
        _basket(page, x + 50, ground - 28)
        _person(page, x + 95, ground - 28, 0.95, facing=-1 if i == 1 else 1)
    _tree(page, 48, ground - 40)
    _person(page, 240, ground - 8, 1.05, facing=1)
    _person(page, 455, ground - 6, 1.0, facing=-1)
    _person(page, 640, ground - 4, 0.9, facing=-1)
    # bicycle
    page.draw_circle(fitz.Point(200, ground - 12), 12, color=(0, 0, 0), width=1.4)
    page.draw_circle(fitz.Point(236, ground - 12), 12, color=(0, 0, 0), width=1.4)
    page.draw_line(fitz.Point(200, ground - 12), fitz.Point(236, ground - 12), **_ink(page, width=1.3))
    page.draw_line(fitz.Point(218, ground - 12), fitz.Point(218, ground - 28), **_ink(page, width=1.3))


def _scene_playground(page, w, h):
    import fitz

    ground = h - 70
    page.draw_line(fitz.Point(20, ground), fitz.Point(w - 20, ground), **_ink(page, width=2))
    _tree(page, 80, ground - 40)
    # slide
    page.draw_rect(fitz.Rect(160, ground - 120, 176, ground), color=(0, 0, 0), width=1.5)
    page.draw_line(fitz.Point(176, ground - 118), fitz.Point(280, ground - 8), **_ink(page, width=2.2))
    page.draw_line(fitz.Point(176, ground - 108), fitz.Point(268, ground - 8), **_ink(page, width=1.4))
    # swing
    page.draw_line(fitz.Point(360, ground - 140), fitz.Point(500, ground - 140), **_ink(page, width=1.8))
    page.draw_line(fitz.Point(360, ground - 140), fitz.Point(360, ground), **_ink(page, width=1.5))
    page.draw_line(fitz.Point(500, ground - 140), fitz.Point(500, ground), **_ink(page, width=1.5))
    page.draw_line(fitz.Point(410, ground - 140), fitz.Point(410, ground - 40), **_ink(page, width=1.2))
    page.draw_line(fitz.Point(450, ground - 140), fitz.Point(450, ground - 40), **_ink(page, width=1.2))
    page.draw_rect(fitz.Rect(406, ground - 44, 454, ground - 32), color=(0, 0, 0), width=1.3)
    _person(page, 430, ground - 58, 0.75)
    _person(page, 230, ground - 8, 0.85, facing=1)
    _person(page, 560, ground - 6, 1.05, facing=-1)
    page.draw_circle(fitz.Point(300, ground - 8), 8, color=(0, 0, 0), width=1.5)


def _scene_station(page, w, h):
    import fitz

    ground = h - 80
    page.draw_line(fitz.Point(20, ground), fitz.Point(w - 20, ground), **_ink(page, width=2))
    page.draw_line(fitz.Point(20, ground + 18), fitz.Point(w - 20, ground + 18), **_ink(page, width=1.3))
    # train
    page.draw_rect(fitz.Rect(40, ground - 100, 680, ground - 20), color=(0, 0, 0), width=1.7)
    for x in (80, 200, 320, 440, 560):
        page.draw_rect(fitz.Rect(x, ground - 88, x + 70, ground - 48), color=(0, 0, 0), width=1.3)
    for x in (90, 210, 330, 450, 570):
        page.draw_circle(fitz.Point(x, ground - 16), 10, color=(0, 0, 0), width=1.4)
    page.draw_rect(fitz.Rect(300, 40, 360, 88), color=(0, 0, 0), width=1.5)
    page.draw_circle(fitz.Point(330, 64), 16, color=(0, 0, 0), width=1.4)
    page.draw_line(fitz.Point(330, 64), fitz.Point(330, 52), **_ink(page, width=1.3))
    page.draw_line(fitz.Point(330, 64), fitz.Point(340, 64), **_ink(page, width=1.3))
    _person(page, 150, ground + 28, 0.95)
    _person(page, 250, ground + 30, 0.9, facing=-1)
    _person(page, 520, ground + 28, 1.0)
    page.draw_rect(fitz.Rect(190, ground + 18, 214, ground + 40), color=(0, 0, 0), width=1.2)
    page.draw_rect(fitz.Rect(400, ground + 16, 460, ground + 42), color=(0, 0, 0), width=1.3)


def _scene_cleanup(page, w, h):
    import fitz

    ground = h - 70
    page.draw_line(fitz.Point(20, ground), fitz.Point(w - 20, ground), **_ink(page, width=2))
    _tree(page, 90, ground - 36)
    _tree(page, 620, ground - 36)
    page.draw_rect(fitz.Rect(300, ground - 50, 340, ground), color=(0, 0, 0), width=1.5)
    page.draw_rect(fitz.Rect(292, ground - 58, 348, ground - 48), color=(0, 0, 0), width=1.4)
    page.draw_rect(fitz.Rect(480, ground - 28, 560, ground - 8), color=(0, 0, 0), width=1.4)
    page.draw_circle(fitz.Point(492, ground - 4), 7, color=(0, 0, 0), width=1.3)
    page.draw_circle(fitz.Point(548, ground - 4), 7, color=(0, 0, 0), width=1.3)
    _person(page, 200, ground - 8, 1.0, facing=1)
    _person(page, 390, ground - 6, 0.95, facing=-1)
    _person(page, 250, ground - 4, 0.75, facing=1)
    page.draw_circle(fitz.Point(170, ground - 4), 5, color=(0, 0, 0), width=1.2)
    page.draw_circle(fitz.Point(430, ground - 4), 5, color=(0, 0, 0), width=1.2)
    page.draw_rect(fitz.Rect(140, ground - 8, 158, ground + 2), color=(0, 0, 0), width=1.2)
