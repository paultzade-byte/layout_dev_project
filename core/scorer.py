"""Config-driven movement scoring for keyboard layouts.

The scorer detects events from physical keys and applies the numeric policy in
``config/moves.yaml``.  Lower scores represent easier layouts.
"""

from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

from core.models import Finger, Hand, Key, Layout, ScoreMetrics


_REQUIRED_MOVES_SCHEMA = {
    "base_effort": {
        "row_multiplier": ("top", "home", "bottom", "other"),
        "finger_multiplier": ("pinky", "ring", "middle", "index", "thumb"),
    },
    "same_finger": ("double_tap", "adjacent_row", "skip_row"),
    "shape_multiplier": ("vertical", "diagonal", "horizontal"),
    "roll": ("inward", "outward", "awkward"),
    "hand": ("alternation", "strict_alternation"),
}


def load_moves_config(path: str | Path) -> Dict[str, Any]:
    """Load and validate the numeric movement-policy YAML file."""
    with Path(path).open(encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file)
    return validate_moves_config(config)


def validate_moves_config(config: Any) -> Dict[str, Any]:
    """Reject incomplete or non-numeric policies before scoring starts."""
    if not isinstance(config, dict) or config.get("version") != 1:
        raise ValueError("moves config must be a mapping with version: 1")

    for section, required in _REQUIRED_MOVES_SCHEMA.items():
        value = config.get(section)
        if not isinstance(value, dict):
            raise ValueError(f"moves config section '{section}' must be a mapping")

        if isinstance(required, dict):
            for subsection, names in required.items():
                nested = value.get(subsection)
                if not isinstance(nested, dict):
                    raise ValueError(
                        f"moves config section '{section}.{subsection}' must be a mapping"
                    )
                _validate_numeric_values(nested, names, f"{section}.{subsection}")
        else:
            _validate_numeric_values(value, required, section)

    return config


def _validate_numeric_values(values: Dict[str, Any], names: Tuple[str, ...], path: str) -> None:
    for name in names:
        value = values.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"moves config value '{path}.{name}' must be numeric")


def calculate_total_penalty(
    layout: Layout,
    text: str,
    moves_config: Dict[str, Any] | None = None,
) -> float:
    """Compatibility entry point for callers that need only the total score."""
    if moves_config is None:
        moves_config = load_moves_config(
            Path(__file__).resolve().parents[1] / "config" / "moves.yaml"
        )
    return MovementScoringEngine(layout.keys, moves_config).score_movements(text).total_penalty


class MovementScoringEngine:
    def __init__(self, layout_keys: List[Key], moves_config: Dict[str, Any]):
        self.char_map: Dict[str, Key] = {
            key.char: key for key in layout_keys if key.char
        }
        self.moves = validate_moves_config(moves_config)

    def score_movements(self, text: str) -> ScoreMetrics:
        metrics = ScoreMetrics()
        key_stream = [self.char_map[char] for char in text if char in self.char_map]

        for key in key_stream:
            metrics.base_effort += key.base_cost * self._base_effort_multiplier(key)

        for k1, k2 in zip(key_stream, key_stream[1:]):
            self._evaluate_bigram(k1, k2, metrics)

        for k1, k2, k3 in zip(key_stream, key_stream[1:], key_stream[2:]):
            self._evaluate_trigram(k1, k2, k3, metrics)

        metrics.total_penalty = sum(
            (
                metrics.base_effort,
                metrics.sfb_penalty,
                metrics.sfs_penalty,
                metrics.severe_penalty,
                metrics.double_tap_penalty,
                metrics.oht_inward_penalty,
                metrics.oht_outward_penalty,
                metrics.oht_awkward_penalty,
                metrics.strict_alternation_penalty,
                metrics.alternation_bonus,
            )
        )
        return metrics

    def _evaluate_bigram(self, k1: Key, k2: Key, metrics: ScoreMetrics) -> None:
        if k1.hand != k2.hand:
            metrics.alternation_bonus += self.moves["hand"]["alternation"]
            return

        if k1.finger != k2.finger:
            return

        row_difference = abs(k1.row - k2.row)
        shape = self._get_shape(k1, k2)
        multiplier = self.moves["shape_multiplier"][shape] * self._finger_multiplier(k1)

        if row_difference == 0:
            metrics.double_tap_penalty += self.moves["same_finger"]["double_tap"] * multiplier
        elif row_difference == 1:
            metrics.sfb_penalty += self.moves["same_finger"]["adjacent_row"] * multiplier
        else:
            metrics.sfs_penalty += self.moves["same_finger"]["skip_row"] * multiplier

    def _evaluate_trigram(self, k1: Key, k2: Key, k3: Key, metrics: ScoreMetrics) -> None:
        if k1.hand == k3.hand and k1.hand != k2.hand:
            metrics.strict_alternation_penalty += self.moves["hand"]["strict_alternation"]
            return

        if k1.hand != k2.hand or k2.hand != k3.hand:
            return

        fingers = (k1.finger.value, k2.finger.value, k3.finger.value)
        if fingers[0] <= fingers[1] <= fingers[2] and len(set(fingers)) > 1:
            metrics.oht_inward_penalty += self.moves["roll"]["inward"]
        elif fingers[0] >= fingers[1] >= fingers[2] and len(set(fingers)) > 1:
            metrics.oht_outward_penalty += self.moves["roll"]["outward"]
        elif (fingers[0] < fingers[1] > fingers[2]) or (
            fingers[0] > fingers[1] < fingers[2]
        ):
            metrics.oht_awkward_penalty += self.moves["roll"]["awkward"]

    def _base_effort_multiplier(self, key: Key) -> float:
        row_name = self.get_row_name(key.row)
        row_weight = self.moves["base_effort"]["row_multiplier"].get(
            row_name, self.moves["base_effort"]["row_multiplier"]["other"]
        )
        return row_weight * self._finger_multiplier(key)

    def _finger_multiplier(self, key: Key) -> float:
        return self.moves["base_effort"]["finger_multiplier"][
            self._get_finger_name(key.finger)
        ]

    @staticmethod
    def get_row_name(row_index: int) -> str:
        return {0: "top", 1: "home", 2: "bottom"}.get(row_index, "other")

    @staticmethod
    def _get_shape(k1: Key, k2: Key) -> str:
        if k1.row == k2.row:
            return "horizontal"
        if k1.col == k2.col:
            return "vertical"
        return "diagonal"

    @staticmethod
    def _get_finger_name(finger: Finger) -> str:
        return {
            Finger.PINKY: "pinky",
            Finger.RING: "ring",
            Finger.MIDDLE: "middle",
            Finger.INDEX: "index",
            Finger.THUMB: "thumb",
        }[finger]
