"""Теплові мапи розкладки: дані й кольори (спільні для GUI і картинки «Скрін»).

- frequency(): яку частку натискань бере кожна клавіша (за уніграмами корпусу).
- finger_loads(): навантаження кожного пальця кожної руки — рядок під дошкою.

Кольори — послідовна шкала однієї гами (величина, не категорія): на темному
фоні апки «майже нуль» темний, близький до фону, «багато» — світлий. Частота —
синя, незручність — помаранчева (дві мапи не плутаються між собою і з
кольорами пальців). Текст на клавіші — темний на світлій заливці і світлий на
темній (heat_ink).
"""

from typing import Dict, List

from core.models import Finger, Hand, Key

# від «майже нуль» (темний, біля фону) до «найбільше» (світлий)
BLUE = ("#0d366b", "#184f95", "#256abf", "#3987e5", "#6da7ec", "#9ec5f4", "#cde2fb")
ORANGE = ("#7c2d12", "#9a3412", "#c2410c", "#ea580c", "#f97316", "#fb923c", "#fdba74", "#fed7aa")
RAMPS = {"freq": BLUE, "pain": ORANGE}

INK_DARK, INK_LIGHT = "#0b0b0b", "#f0efec"

FINGER_SHORT = {Finger.PINKY: "мізинець", Finger.RING: "безіменний", Finger.MIDDLE: "середній",
                Finger.INDEX: "вказівний", Finger.THUMB: "великий"}


def _letters(keys: List[Key]) -> Dict[str, Key]:
    return {k.char: k for k in keys if len(k.char) == 1 and k.char.strip()}


def frequency(keys: List[Key], statistic: Dict) -> Dict[int, float]:
    """-> {position_id: % натискань} для клавіш з літерами (сума = 100)."""
    by_char = _letters(keys)
    counts = {c: f for c, f in statistic["unigrams"].items() if c in by_char}
    total = sum(counts.values()) or 1.0
    return {by_char[c].position_id: 100.0 * f / total for c, f in counts.items()}


def discomfort(engine, keys: List[Key]) -> Dict[int, float]:
    """-> {position_id: % штрафу} — скільки штрафу розкладки набігає через
    літеру на клавіші (MovementScoringEngine.per_char_penalty; сума = 100)."""
    engine.update_layout(keys)
    per_char = engine.per_char_penalty()
    by_char = _letters(keys)
    total = sum(v for c, v in per_char.items() if c in by_char) or 1.0
    return {by_char[c].position_id: 100.0 * v / total for c, v in per_char.items() if c in by_char}


def finger_loads(keys: List[Key], values: Dict[int, float]) -> Dict[tuple, float]:
    """values {position_id: %} -> {(Hand, Finger): сума %} — лише пальці, де щось є."""
    out: Dict[tuple, float] = {}
    for k in keys:
        if k.position_id in values:
            slot = (k.hand, k.finger)
            out[slot] = out.get(slot, 0.0) + values[k.position_id]
    return out


def loads_text(keys: List[Key], values: Dict[int, float]) -> str:
    """Два рядки «Ліва 49%: мізинець 7.1 · …» / «Права …» — від мізинця до вказівного."""
    loads = finger_loads(keys, values)
    order = (Finger.PINKY, Finger.RING, Finger.MIDDLE, Finger.INDEX, Finger.THUMB)
    parts = []
    for hand, title in ((Hand.LEFT, "Ліва"), (Hand.RIGHT, "Права")):
        items = [f"{FINGER_SHORT[f]} {loads[(hand, f)]:.1f}" for f in order if (hand, f) in loads]
        hand_total = sum(loads.get((hand, f), 0.0) for f in order)
        parts.append(f"{title} {hand_total:.0f}%: " + " · ".join(items))
    return "\n".join(parts)


def _rgb(hex_color: str) -> tuple:
    return tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))


def heat_color(t: float, kind: str = "freq") -> str:
    """t 0..1 -> колір шкали (лінійно між сусідніми кроками)."""
    ramp = RAMPS[kind]
    t = min(1.0, max(0.0, t)) * (len(ramp) - 1)
    i = min(int(t), len(ramp) - 2)
    a, b = _rgb(ramp[i]), _rgb(ramp[i + 1])
    f = t - i
    return "#" + "".join(f"{round(x + (y - x) * f):02x}" for x, y in zip(a, b))


def heat_ink(fill: str) -> str:
    """Колір тексту на заливці: за відносною яскравістю (WCAG)."""
    def channel(c):
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in _rgb(fill))
    luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    # поріг, де контраст з білим і з чорним однаковий
    return INK_DARK if luminance > 0.179 else INK_LIGHT


def cells(values: Dict[int, float], kind: str = "freq") -> Dict[int, dict]:
    """values {position_id: %} -> {position_id: {fill, ink, text}}; шкала — від 0 до максимуму."""
    top = max(values.values(), default=0.0) or 1.0
    out = {}
    for pid, value in values.items():
        fill = heat_color(value / top, kind)
        text = f"{value:.1f}" if value >= 0.05 or value <= 0 else "<0.1"
        out[pid] = {"fill": fill, "ink": heat_ink(fill), "text": text}
    return out
