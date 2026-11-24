"""Іконки застосунків: оптимізатор (ukr-layout) і статистика (ukr-stats).

    python scripts/make_icons.py

Пише в packaging/icons/: <name>.png (256×256 — вікно Tk і ярлик Linux) і
<name>.ico (16–256 — exe і ярлики Windows). Готові файли лежать у git,
тож збірка (CI) шрифтів і цього скрипта не потребує. Кольори — uiux/theme.py.
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core.models import Finger  # noqa: E402
from uiux.theme import BG, FINGER_COLORS, KEY_TEXT  # noqa: E402

OUT = ROOT / "packaging" / "icons"
S = 1024                     # малюємо великим, потім зменшуємо (згладжування)
FONTS = ["/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
PINKY, RING, MIDDLE, INDEX = (FINGER_COLORS[f] for f in
                              (Finger.PINKY, Finger.RING, Finger.MIDDLE, Finger.INDEX))


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONTS:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    raise SystemExit("немає жирного шрифту з кирилицею (Ubuntu / DejaVu)")


def _base() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((32, 32, S - 32, S - 32), radius=200, fill=BG)
    return img, draw


def _key(draw, box, color, letter=None, size=0):
    draw.rounded_rectangle(box, radius=70, fill=color)
    if letter:
        x0, y0, x1, y1 = box
        draw.text(((x0 + x1) / 2, (y0 + y1) / 2 + size * 0.06), letter,
                  font=_font(size), fill=KEY_TEXT, anchor="mm")


def optimizer() -> Image.Image:
    """Велика клавіша «Ї» над рядком клавіш у кольорах пальців."""
    img, draw = _base()
    _key(draw, (170, 120, 854, 680), INDEX, "Ї", 500)
    w, gap, y = 150, 28, 730
    x = (S - 4 * w - 3 * gap) / 2
    for color in (PINKY, RING, MIDDLE, INDEX):
        draw.rounded_rectangle((x, y, x + w, y + 150), radius=40, fill=color)
        x += w + gap
    return img


def stats() -> Image.Image:
    """Стовпчики частот у кольорах пальців і «аб» — статистика тексту."""
    img, draw = _base()
    w, gap, bottom = 150, 40, 870
    x = (S - 4 * w - 3 * gap) / 2
    for color, h in zip((INDEX, MIDDLE, RING, PINKY), (560, 420, 300, 190)):
        draw.rounded_rectangle((x, bottom - h, x + w, bottom), radius=40, fill=color)
        x += w + gap
    draw.text((S - 150, 170), "аб", font=_font(250), fill=FINGER_COLORS[Finger.THUMB], anchor="rm")
    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, make in (("ukr-layout", optimizer), ("ukr-stats", stats)):
        img = make().resize((256, 256), Image.LANCZOS)
        img.save(OUT / f"{name}.png")
        img.save(OUT / f"{name}.ico", sizes=ICO_SIZES)
        print(OUT / f"{name}.png")


if __name__ == "__main__":
    main()
