"""Зрозумілі людині метрики розкладки (у % від натискань / біграм).

Не впливають на оцінку — лише показують, що вийшло: для звітів у scripts/ і
для панелі метрик у GUI (фаза 4 docs/PLAN_standard.md). Враховуються лише
символи, що стоять на розкладці (пробіл, Enter, цифри — ні).
"""

from typing import Dict, List

from core.models import Finger, Hand, Key

VOWELS = frozenset("аеєиіїоуюя")
_FINGERS = (Finger.PINKY, Finger.RING, Finger.MIDDLE, Finger.INDEX)


def layout_metrics(keys: List[Key], statistic: Dict) -> Dict[str, float]:
    """-> {назва: відсоток}. Ключі:
    alternation — біграми з чергуванням рук;
    sfb — біграми одним пальцем на різних клавішах;
    rolls — біграми сусідніми пальцями однієї руки (перекати);
    home_row / top_row / bottom_row — натискання по рядах (цифровий ряд — у top_row);
    left_hand — натискання лівою рукою;
    vowels_left — частка голосних на лівій руці;
    pinky / ring / middle / index — навантаження пальців (обидві руки разом);
    pinky_left / pinky_right — кожен мізинець окремо.
    """
    by_char = {k.char: k for k in keys if len(k.char) == 1 and k.finger != Finger.THUMB}
    unigrams = {c: f for c, f in statistic["unigrams"].items() if c in by_char}
    presses = sum(unigrams.values()) or 1.0

    def share(predicate) -> float:
        return 100.0 * sum(f for c, f in unigrams.items() if predicate(by_char[c])) / presses

    out = {
        "home_row": share(lambda k: k.row == 1),
        "top_row": share(lambda k: k.row <= 0),
        "bottom_row": share(lambda k: k.row == 2),
        "left_hand": share(lambda k: k.hand == Hand.LEFT),
        "pinky_left": share(lambda k: k.finger == Finger.PINKY and k.hand == Hand.LEFT),
        "pinky_right": share(lambda k: k.finger == Finger.PINKY and k.hand == Hand.RIGHT),
    }
    for finger in _FINGERS:
        out[finger.name.lower()] = share(lambda k, f=finger: k.finger == f)

    vowels = sum(f for c, f in unigrams.items() if c in VOWELS) or 1.0
    out["vowels_left"] = 100.0 * sum(
        f for c, f in unigrams.items() if c in VOWELS and by_char[c].hand == Hand.LEFT) / vowels

    total = alternation = sfb = rolls = 0.0
    for pair, freq in statistic["bigrams"].items():
        if len(pair) != 2:
            continue
        a, b = by_char.get(pair[0]), by_char.get(pair[1])
        if a is None or b is None:
            continue
        total += freq
        if a.hand != b.hand:
            alternation += freq
        elif a.finger == b.finger:
            if a.position_id != b.position_id:
                sfb += freq
        elif abs(a.finger.value - b.finger.value) == 1:
            rolls += freq
    total = total or 1.0
    out["alternation"] = 100.0 * alternation / total
    out["sfb"] = 100.0 * sfb / total
    out["rolls"] = 100.0 * rolls / total
    return out


METRIC_TITLES = {
    "alternation": "чергування рук",
    "rolls": "перекати сусідніми",
    "sfb": "SFB (один палець)",
    "home_row": "домашній ряд",
    "top_row": "верхній ряд",
    "bottom_row": "нижній ряд",
    "left_hand": "ліва рука",
    "vowels_left": "голосні на лівій",
    "pinky": "мізинці",
    "pinky_left": "  лівий мізинець",
    "pinky_right": "  правий мізинець",
    "ring": "безіменні",
    "middle": "середні",
    "index": "вказівні",
}
