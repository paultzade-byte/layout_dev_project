"""Розкладка оптимізатора <-> шар CYR на клавіатурі, одним викликом (для кнопок GUI).

    plan = prepare(layout_items)          # читає клавіатуру, збирає шар, рахує diff
    print(plan.diff_text)                 # показати автору
    result = apply(plan, layout_items, score=165.32)  # записати + файли + картинки
    read_layout()                         # шар CYR з клавіатури -> формат Rec>>

`apply` пише лише змінені клавіші (studio.write_layer: перечитати шар і тільки
тоді зберегти у флеш, інакше discard) і зберігає:
- config/zmk/studio_keymap_<час>-before.json — точка відкату (стан до запису);
- config/zmk/studio_keymap_<час>-written.json — записаний дамп;
- config/layout_paul_<час>.json — розкладка у форматі Rec>>;
- ~/Documents/layout/algoritmical_layouts/layout_<час>.{svg,png} (PNG — inkscape,
  якщо є) і layers_current.html — схема шарів (для артефакту).
Відкат: `studio.py write auto <before.json> --layer CYR --yes`.

Прошивка тут не потрібна: Studio міняє keymap у живій клавіатурі.
"""

import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cyr_from_layout as cfl  # noqa: E402
import layers_html  # noqa: E402
import studio as st  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DUMPS = ROOT / "config" / "zmk"
LAYOUTS = ROOT / "config"
IMAGES = Path.home() / "Documents" / "layout" / "algoritmical_layouts"
TEMPLATE = Path(__file__).resolve().parent / "layout_template.svg"
# порядок підписів у шаблоні: позиції 0..31, тхамби, кути 38/39
TEMPLATE_ORDER = list(range(32)) + ["⌫", "␣", 38, 39]


@dataclass
class Plan:
    port: str
    current: dict           # дамп клавіатури до запису
    target: dict            # дамп після запису
    changes: list           # [(позиція, старий, новий)] шару CYR
    diff_text: str
    stamp: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d_%H%M"))


def _diff_lines(current, changes):
    layer_names = {l["id"]: l["name"] for l in current["layers"]}
    txt = lambda b: st.binding_text(b, current["behaviors"], layer_names, ua=True)  # noqa: E731
    return "\n".join(f"CYR[{pos:2}]  {txt(old)}  ->  {txt(new)}" for pos, old, new in changes)


def read_dump(port=None):
    """Повний дамп клавіатури (усі шари)."""
    with st.Studio(port or st.find_port()) as studio:
        return studio.dump()


def read_layout(port=None):
    """Шар CYR з клавіатури -> [{position_id, char, is_frozen}] (тхамби порожні)."""
    return cfl.extract(read_dump(port))


def prepare(layout_items, port=None):
    port = port or st.find_port()
    with st.Studio(port) as studio:
        current = studio.dump()
    target = cfl.build(layout_items, current)
    changes = st.layer_diff(current, target, cfl.LAYER)
    return Plan(port, current, target, changes, _diff_lines(current, changes))


def _save_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def render_svg(layout_items, title):
    chars = {d["position_id"]: d["char"] for d in layout_items}
    labels = iter([chars.get(p, "") if isinstance(p, int) else p for p in TEMPLATE_ORDER])
    svg = TEMPLATE.read_text(encoding="utf-8")
    # перший <text> — заголовок, далі підписи клавіш (1–2 символи)
    svg = re.sub(r'(<text [^>]*>)[^<]*(</text>)', lambda m: m.group(1) + _esc(title) + m.group(2), svg, count=1)
    head, rest = svg.split("</text>", 1)
    rest, n = re.subn(r'>[^<>]{1,2}</text>', lambda m: ">" + _esc(next(labels)) + "</text>", rest)
    if n != len(TEMPLATE_ORDER):
        raise RuntimeError(f"шаблон SVG: {n} підписів замість {len(TEMPLATE_ORDER)}")
    return head + "</text>" + rest


def _esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def apply(plan, layout_items, score=None, write_images=True):
    """Записує plan на клавіатуру і зберігає файли. -> dict з шляхами."""
    out = {"before": _save_json(DUMPS / f"studio_keymap_{plan.stamp}-before.json", plan.current)}
    if plan.changes:
        with st.Studio(plan.port) as studio:
            studio.write_layer(plan.current, plan.changes, cfl.LAYER)
            # перевірка: на клавіатурі тепер саме цільовий шар
            if st.layer_diff(studio.dump(), plan.target, cfl.LAYER):
                raise RuntimeError("після запису клавіатура не збігається з цільовим шаром")
    out["written"] = _save_json(DUMPS / f"studio_keymap_{plan.stamp}-written.json", plan.target)
    out["layout"] = _save_json(LAYOUTS / f"layout_paul_{plan.stamp}.json", layout_items)
    if write_images:
        out.update(_images(plan, layout_items, score))
    return out


def _images(plan, layout_items, score):
    IMAGES.mkdir(parents=True, exist_ok=True)
    when = plan.stamp.replace("_", " ")[:-2] + ":" + plan.stamp[-2:]
    title = f"на клавіатурі з {when}" + (f" (штраф {score:.2f})" if score is not None else "")
    svg = IMAGES / f"layout_{plan.stamp}.svg"
    svg.write_text(render_svg(layout_items, title), encoding="utf-8")
    out = {"svg": svg}
    if shutil.which("inkscape"):
        png = svg.with_suffix(".png")
        subprocess.run(["inkscape", str(svg), "--export-type=png", f"--export-filename={png}"],
                       check=True, capture_output=True, timeout=120)
        out["png"] = png
    html_path = IMAGES / "layers_current.html"
    dump_path = DUMPS / f"studio_keymap_{plan.stamp}-written.json"
    html_path.write_text(layers_html.render(dump_path), encoding="utf-8")
    out["html"] = html_path
    return out


# --- інші шари (редагування на вкладках GUI) ----------------------------------

@dataclass
class LayersPlan:
    port: str
    current: dict           # дамп клавіатури зараз
    changes: dict           # {шар: [(позиція, поточний, новий)]}
    conflicts: list         # [(шар, позиція)] — на клавіатурі вже не те, від чого редагували
    diff_text: str
    stamp: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d_%H%M"))

    @property
    def count(self):
        return sum(len(v) for v in self.changes.values())


def prepare_layers(working, base, port=None):
    """Зміни робочої копії відносно base (стан, з якого почали редагувати) —
    поверх того, що на клавіатурі зараз. Чіпаємо лише змінені позиції."""
    port = port or st.find_port()
    with st.Studio(port) as studio:
        current = studio.dump()
    dst_ids = {v: k for k, v in current["behaviors"].items()}
    names = {l["id"]: l["name"] for l in current["layers"]}
    changes, conflicts, lines = {}, [], []
    for layer in working["layers"]:
        name = layer["name"]
        old = st.find_layer(base, name)["bindings"]
        cur = st.find_layer(current, name)["bindings"]
        for pos, (was, new) in enumerate(zip(old, layer["bindings"])):
            if was == new:
                continue
            was_dev = st.translate(was, base["behaviors"], dst_ids)
            new_dev = st.translate(new, working["behaviors"], dst_ids)
            if cur[pos] != was_dev:
                conflicts.append((name, pos))
            if cur[pos] != new_dev:
                changes.setdefault(name, []).append((pos, cur[pos], new_dev))
    for name, ch in changes.items():
        ua = name.startswith("CYR")
        txt = lambda b: st.binding_text(b, current["behaviors"], names, ua)  # noqa: E731
        lines += [f"{name}[{pos:2}]  {txt(o)}  ->  {txt(n)}" for pos, o, n in ch]
    return LayersPlan(port, current, changes, conflicts, "\n".join(lines))


def apply_layers(plan):
    """Записує шари по черзі (кожен — write_layer з перевіркою і save). -> dict(шляхи, dump)."""
    out = {"before": _save_json(DUMPS / f"studio_keymap_{plan.stamp}-before.json", plan.current)}
    with st.Studio(plan.port) as studio:
        for name, changes in plan.changes.items():
            studio.write_layer(plan.current, changes, name)
        after = studio.dump()
    written = DUMPS / f"studio_keymap_{plan.stamp}-written.json"
    out["written"] = _save_json(written, after)
    IMAGES.mkdir(parents=True, exist_ok=True)
    out["html"] = IMAGES / "layers_current.html"
    out["html"].write_text(layers_html.render(written), encoding="utf-8")
    out["dump"] = after
    return out
