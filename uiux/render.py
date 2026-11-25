"""Картинка розкладки (PNG через Pillow, або SVG) для будь-якої геометрії.

Той самий код — для кнопки «Скрін» у GUI і з командного рядка:

    python -m uiux.render LAYOUT.json OUT.png [--geometry NAME] [--title ТЕКСТ]
    python -m uiux.render - OUT.svg --geometry generic_105_alpha   # типова розкладка

LAYOUT.json — у форматі Rec>> ([{"position_id", "char", "is_frozen"}]).
`altgr` геометрії (AltGr+літера) малюється дрібно в правому верхньому куті.
Pillow, без браузера/inkscape — щоб працювало і в зібраному exe.
"""

import argparse
import json
import sys
from datetime import datetime
from html import escape
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from core.models import Finger
from uiux.theme import FINGER_COLORS, FROZEN_BG, FROZEN_FG, KEY_TEXT, PANEL, SLOT, TEXT, TEXT_DIM

GAP = 6               # відстань між клавішами (як у GUI)
SPLIT_GAP = 400       # зсув правої половини спліта (як у GUI)
MARGIN = 10
TITLE_H = 34          # смуга заголовка над клавішами
FOOTER_H = 46         # рядок під дошкою (навантаження пальців на тепловій мапі)
# Риска орієнтира на F і J (position "homing" у geometry.json): ширина, товщина, відступ від низу (px).
HOMING_W, HOMING_H, HOMING_BOTTOM = 14, 3, 5

# Підписи службових клавіш (role: mod). У corne_42 мітки в geometry.json
# переплутані (WORKLOG «Наступні кроки» 4): 33 — Backspace, 36 — пробіл.
MOD_LABELS = {
    "corne_42": {"SPA": "⌫", "CE": "␣"},
    "generic_105_alpha": {"Shft": "⇧ Shift", "SPA": "", "CE": "AltGr", "Enter": "Enter ⏎"},
}

# Шрифти шукаються за іменем файлу в системних теках (Linux, Windows, macOS).
TEXT_FONTS = ("Ubuntu-B.ttf", "DejaVuSans-Bold.ttf", "segoeuib.ttf", "arialbd.ttf", "Arial Bold.ttf")
SYMBOL_FONTS = ("DejaVuSans-Bold.ttf", "DejaVuSans.ttf", "seguisym.ttf", "Apple Symbols.ttf", "arialbd.ttf")
SVG_FONT = "Ubuntu, 'DejaVu Sans', 'Segoe UI', Arial, sans-serif"


def key_cells(geometry: dict, geometry_name: str) -> list[tuple[dict, int, int, int]]:
    """[(position, x, y, width)] — верхній лівий кут і ширина клавіші в px,
    від (0, 0) дошки. Та сама сітка, що й у GUI (LayoutBuilderApp.build_grid).

    stages: 0 — рівна сітка по col; 1 — col + offset_x (px);
    2 — x і w в одиницях клавіші u (звичайна ANSI-клавіатура)."""
    w, h = geometry["key_width"], geometry["key_height"]
    pitch_x, pitch_y = w + GAP, h + GAP
    stages = geometry["stages"]
    raw = []
    for pos in geometry["positions"]:
        width = w
        if stages == 2:
            x = round(pos["x"] * pitch_x)
            width = round(pos.get("w", 1) * pitch_x) - GAP
        elif stages in (0, 1):
            x = pos["col"] * pitch_x + (pos.get("offset_x", 0) if stages == 1 else 0)
        else:
            raise KeyError(f"невідоме stages={stages}")
        if pos.get("hand") == "R" and geometry_name == "corne_42":
            x += SPLIT_GAP
        raw.append((pos, x, pos["row"] * pitch_y, width))
    min_x = min(x for _, x, _, _ in raw)
    min_y = min(y for _, _, y, _ in raw)
    return [(pos, x - min_x, y - min_y, width) for pos, x, y, width in raw]


def _cells(keys, geometry: dict, geometry_name: str, heat: dict | None = None) -> list[dict]:
    """Клавіші з координатами (від 0), підписом і кольором.
    heat — {position_id: {fill, ink, text}} (core.heat.cells): теплова мапа
    замість кольорів пальців; літера без даних — сіра."""
    by_position = {k.position_id: k for k in keys}
    labels = MOD_LABELS.get(geometry_name, {})
    altgr = geometry.get("altgr", {})  # другий символ на клавіші (AltGr+літера)
    out = []
    for pos, x, y, width in key_cells(geometry, geometry_name):
        key = by_position.get(pos["id"])
        char = key.char if key is not None else pos.get("default", "")
        is_mod = pos.get("role") == "mod" or not char
        finger = key.finger if key is not None else None
        color, ink, note = FINGER_COLORS.get(finger, TEXT_DIM) if finger is not None else TEXT_DIM, KEY_TEXT, ""
        if heat is not None and not is_mod:
            cell = heat.get(pos["id"])
            color, ink, note = (cell["fill"], cell["ink"], cell["text"]) if cell else (SLOT, TEXT_DIM, "")
        out.append({
            "x": x, "y": y, "w": width, "h": geometry["key_height"],
            "label": labels.get(char, char) if is_mod else char,
            "mod": is_mod,
            "altgr": "" if is_mod else altgr.get(char, ""),
            "color": color, "ink": ink, "note": note,
            "homing": bool(pos.get("homing")),
        })
    return out


def _font(names, size):
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def default_title(geometry_name: str, score: float | None) -> tuple[str, str]:
    from config.main_config import GEOMETRY_TITLES
    title = GEOMETRY_TITLES.get(geometry_name, geometry_name)
    if score is not None:
        title += f" · штраф {score:.2f}"
    return title, datetime.now().strftime("%Y-%m-%d %H:%M")


def render_png(keys, geometry: dict, geometry_name: str, path, title: str = "", subtitle: str = "",
               scale: int = 2, heat: dict | None = None, footer: str = "") -> Path:
    cells = _cells(keys, geometry, geometry_name, heat)
    width = max(c["x"] + c["w"] for c in cells) + 2 * MARGIN
    board_bottom = max(c["y"] + c["h"] for c in cells) + TITLE_H + MARGIN
    height = board_bottom + MARGIN + (FOOTER_H if footer else 0)
    s = scale
    image = Image.new("RGB", (width * s, height * s), PANEL)
    draw = ImageDraw.Draw(image)
    title_font = _font(TEXT_FONTS, 17 * s)
    sub_font = _font(TEXT_FONTS, 13 * s)
    key_font = _font(TEXT_FONTS, 22 * s)
    symbol_font = _font(SYMBOL_FONTS, 20 * s)
    small_font = _font(TEXT_FONTS, 12 * s)
    small_symbol_font = _font(SYMBOL_FONTS, 12 * s)
    altgr_font = _font(TEXT_FONTS, 13 * s)
    note_font = _font(TEXT_FONTS, 10 * s)

    if title:
        draw.text((MARGIN * s, (MARGIN + 18) * s), title, font=title_font, fill=TEXT, anchor="ls")
    if subtitle:
        draw.text(((width - MARGIN) * s, (MARGIN + 18) * s), subtitle, font=sub_font, fill=TEXT_DIM, anchor="rs")

    for c in cells:
        x0, y0 = (MARGIN + c["x"]) * s, (MARGIN + TITLE_H + c["y"]) * s
        box = (x0, y0, x0 + c["w"] * s - 1, y0 + c["h"] * s - 1)
        center = (x0 + c["w"] * s / 2, y0 + c["h"] * s / 2)
        if c["mod"]:
            draw.rounded_rectangle(box, radius=3 * s, fill=FROZEN_BG, outline=FROZEN_FG, width=s)
            label = c["label"]
            if len(label) == 1:
                font = symbol_font
            else:  # «⇧ Shift», «Enter ⏎»: стрілки є лише в символьному шрифті
                font = small_font if label.isascii() else small_symbol_font
            draw.text(center, label, font=font, fill=FROZEN_FG, anchor="mm")
        else:
            draw.rounded_rectangle(box, radius=3 * s, fill=c["color"])
            draw.text(center, c["label"], font=key_font, fill=c["ink"], anchor="mm")
            if c["altgr"]:  # AltGr-символ — дрібно в правому верхньому куті
                draw.text((x0 + (c["w"] - 5) * s, y0 + 3 * s), c["altgr"], font=altgr_font,
                          fill=c["ink"], anchor="ra")
            if c["note"]:  # теплова мапа: відсоток — дрібно внизу
                draw.text((center[0], y0 + (c["h"] - 3) * s), c["note"], font=note_font,
                          fill=c["ink"], anchor="ms")
        if c["homing"]:  # риска під вказівний (F/J); з тепловою мапою — над відсотком
            bottom = y0 + (c["h"] - HOMING_BOTTOM - (11 if c["note"] else 0)) * s
            half = HOMING_W * s / 2
            draw.rounded_rectangle((center[0] - half, bottom - HOMING_H * s, center[0] + half, bottom),
                                   radius=HOMING_H * s / 2, fill=FROZEN_FG if c["mod"] else c["ink"])
    if footer:
        for i, line in enumerate(footer.splitlines()[:2]):
            draw.text((MARGIN * s, (board_bottom + 22 + 20 * i) * s), line, font=sub_font, fill=TEXT_DIM,
                      anchor="ls")

    path = Path(path)
    image.save(path)
    return path


def render_svg(keys, geometry: dict, geometry_name: str, title: str = "", subtitle: str = "",
               heat: dict | None = None, footer: str = "") -> str:
    cells = _cells(keys, geometry, geometry_name, heat)
    width = max(c["x"] + c["w"] for c in cells) + 2 * MARGIN
    board_bottom = max(c["y"] + c["h"] for c in cells) + TITLE_H + MARGIN
    height = board_bottom + MARGIN + (FOOTER_H if footer else 0)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
             f'viewBox="0 0 {width} {height}">',
             f'<rect width="100%" height="100%" fill="{PANEL}"/>']
    if title:
        parts.append(f'<text x="{MARGIN}" y="{MARGIN + 18}" font-family="{SVG_FONT}" font-size="17" '
                     f'fill="{TEXT}">{escape(title)}</text>')
    if subtitle:
        parts.append(f'<text x="{width - MARGIN}" y="{MARGIN + 18}" font-family="{SVG_FONT}" font-size="13" '
                     f'text-anchor="end" fill="{TEXT_DIM}">{escape(subtitle)}</text>')
    for c in cells:
        x, y = MARGIN + c["x"], MARGIN + TITLE_H + c["y"]
        cx, cy = x + c["w"] / 2, y + c["h"] / 2
        if c["mod"]:
            parts.append(f'<rect x="{x + 0.5}" y="{y + 0.5}" width="{c["w"] - 1}" height="{c["h"] - 1}" rx="3" '
                         f'fill="{FROZEN_BG}" stroke="{FROZEN_FG}"/>')
            size = 20 if len(c["label"]) == 1 else 12
            fill = FROZEN_FG
        else:
            parts.append(f'<rect x="{x}" y="{y}" width="{c["w"]}" height="{c["h"]}" rx="3" fill="{c["color"]}"/>')
            size, fill = 22, c["ink"]
        parts.append(f'<text x="{cx}" y="{cy}" font-family="{SVG_FONT}" font-weight="bold" font-size="{size}" '
                     f'text-anchor="middle" dominant-baseline="central" fill="{fill}">{escape(c["label"])}</text>')
        if c["altgr"]:
            parts.append(f'<text x="{x + c["w"] - 5}" y="{y + 3}" font-family="{SVG_FONT}" font-weight="bold" '
                         f'font-size="13" text-anchor="end" dominant-baseline="hanging" fill="{c["ink"]}">'
                         f'{escape(c["altgr"])}</text>')
        if c["note"]:
            parts.append(f'<text x="{cx}" y="{y + c["h"] - 3}" font-family="{SVG_FONT}" font-size="10" '
                         f'text-anchor="middle" fill="{c["ink"]}">{escape(c["note"])}</text>')
        if c["homing"]:
            bottom = y + c["h"] - HOMING_BOTTOM - (11 if c["note"] else 0)
            parts.append(f'<rect x="{cx - HOMING_W / 2}" y="{bottom - HOMING_H}" width="{HOMING_W}" '
                         f'height="{HOMING_H}" rx="{HOMING_H / 2}" fill="{FROZEN_FG if c["mod"] else c["ink"]}"/>')
    if footer:
        for i, line in enumerate(footer.splitlines()[:2]):
            parts.append(f'<text x="{MARGIN}" y="{board_bottom + 22 + 20 * i}" font-family="{SVG_FONT}" '
                         f'font-size="13" fill="{TEXT_DIM}">{escape(line)}</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def save(keys, geometry: dict, geometry_name: str, path, title: str = "", subtitle: str = "",
         heat: dict | None = None, footer: str = "") -> Path:
    """PNG або SVG — за розширенням. heat/footer — теплова мапа і рядок під дошкою."""
    path = Path(path)
    if path.suffix.lower() == ".svg":
        path.write_text(render_svg(keys, geometry, geometry_name, title, subtitle, heat, footer),
                        encoding="utf-8")
        return path
    return render_png(keys, geometry, geometry_name, path, title, subtitle, heat=heat, footer=footer)


def main(argv=None):
    from config.main_config import ACTIVE, GEOMETRIES, STATISTIC, geometry_config, load_moves
    from core.layout_factory import build_layout
    from core.scorer import MovementScoringEngine

    parser = argparse.ArgumentParser(description="Картинка розкладки (PNG/SVG)")
    parser.add_argument("layout", help="розкладка у форматі Rec>> або '-' (типова для геометрії)")
    parser.add_argument("out", help="OUT.png або OUT.svg")
    parser.add_argument("--geometry", choices=sorted(GEOMETRIES), default=ACTIVE)
    parser.add_argument("--title", help="заголовок (типово: режим і штраф)")
    parser.add_argument("--subtitle", help="праворуч дрібно (типово: дата)")
    args = parser.parse_args(argv)

    geometry = geometry_config(args.geometry)
    layout = build_layout(geometry)
    if args.layout != "-":
        chars = {d["position_id"]: d["char"] for d in json.loads(Path(args.layout).read_text(encoding="utf-8"))}
        for key in layout.keys:
            if key.position_id in chars:
                key.char = chars[key.position_id]
    title, subtitle = args.title, args.subtitle
    if title is None or subtitle is None:
        engine = MovementScoringEngine(layout.keys, load_moves(args.geometry)).prepare_statistics(STATISTIC)
        auto_title, auto_subtitle = default_title(args.geometry, engine.score().total_penalty / 1e8)
        title = auto_title if title is None else title
        subtitle = auto_subtitle if subtitle is None else subtitle
    print(save(layout.keys, geometry, args.geometry, args.out, title, subtitle))


if __name__ == "__main__":
    sys.exit(main())
