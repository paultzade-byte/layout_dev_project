import unittest
import json
from pathlib import Path

from core.layout_factory import build_layout
from core.models import Finger, Hand, Key, Layout
from core.mutator import LayoutOptimizerSA


class LayoutOptimizerMutationTests(unittest.TestCase):
    def _layout(self):
        return Layout(
            keys=[
                Key(0, 0, 0, 0, 0, Hand.LEFT, Finger.INDEX, 1, "а"),
                Key(1, 1, 0, 0, 1, Hand.LEFT, Finger.INDEX, 1, "б"),
                Key(2, 2, 0, 0, 2, Hand.LEFT, Finger.MIDDLE, 1, "в"),
                Key(3, 3, 0, 0, 3, Hand.RIGHT, Finger.INDEX, 1, "г"),
                Key(4, 4, 0, 0, 4, Hand.LEFT, Finger.PINKY, 1, "Shft", True),
                Key(5, 5, 0, 0, 5, Hand.RIGHT, Finger.THUMB, 1, "", True),
            ]
        )

    def setUp(self):
        self.layout = self._layout()
        self.optimizer = LayoutOptimizerSA(self.layout, "абвг", {"seed": 7})

    def test_mutation_preserves_modifier_and_empty_positions(self):
        candidate = self.optimizer._mutate_double_swap(self.layout)

        self.assertEqual("Shft", candidate.keys[4].char)
        self.assertEqual("", candidate.keys[5].char)

    def test_mutation_rejects_an_insufficient_mutable_set(self):
        for key in self.layout.keys[1:]:
            key.is_frozen = True

        with self.assertRaisesRegex(ValueError, "2 mutable keys"):
            self.optimizer._mutate_single_swap(self.layout)

    def test_optimization_integrates_geometry_and_yaml_scoring(self):
        document = json.loads(
            (Path(__file__).resolve().parents[1] / "config" / "geometry.json").read_text(
                encoding="utf-8"
            )
        )
        initial_layout = build_layout(document["layouts"]["corne_42"])
        frozen_before = {
            key.position_id: key.char for key in initial_layout.keys if key.is_frozen
        }

        optimized = LayoutOptimizerSA(
            initial_layout, "йцукен йцукен", {"seed": 4}
        ).run_optimization(iterations=10)

        self.assertIsNotNone(optimized.score)
        self.assertGreater(optimized.score.total_penalty, 0)
        self.assertEqual(
            frozen_before,
            {key.position_id: key.char for key in optimized.keys if key.is_frozen},
        )

    def test_optimizer_rejects_empty_text(self):
        with self.assertRaisesRegex(ValueError, "non-empty"):
            LayoutOptimizerSA(self.layout, "")
