import unittest
from pathlib import Path

from core.models import Finger, Hand, Key
from core.scorer import (
    MovementScoringEngine,
    calculate_total_penalty,
    load_moves_config,
    validate_moves_config,
)
from core.layout_factory import build_layout


class MovementScoringEngineTests(unittest.TestCase):
    def setUp(self):
        self.keys = [
            Key(0, 0, 0, 0, 0, Hand.LEFT, Finger.INDEX, 1.0, "а"),
            Key(1, 0, 1, 1, 0, Hand.LEFT, Finger.INDEX, 1.0, "б"),
            Key(2, 0, 2, 2, 0, Hand.LEFT, Finger.INDEX, 1.0, "в"),
        ]
        moves_path = Path(__file__).resolve().parents[1] / "config" / "moves.yaml"
        self.engine = MovementScoringEngine(self.keys, load_moves_config(moves_path))

    def test_loads_the_project_movement_policy(self):
        self.assertEqual(
            5.0,
            self.engine.moves["same_finger"]["adjacent_row"],
        )

    def test_scores_a_non_empty_stream(self):
        metrics = self.engine.score_movements("абв")

        self.assertEqual(3.65, metrics.base_effort)
        self.assertEqual(10.0, metrics.sfb_penalty)
        self.assertEqual(0.0, metrics.sfs_penalty)
        self.assertEqual(
            metrics.base_effort
            + metrics.sfb_penalty
            + metrics.sfs_penalty,
            metrics.total_penalty,
        )

    def test_scores_a_same_finger_skip_row_move(self):
        metrics = self.engine.score_movements("ав")

        self.assertEqual(10.0, metrics.sfs_penalty)

    def test_empty_text_has_a_zero_score(self):
        self.assertEqual(0.0, self.engine.score_movements("").total_penalty)

    def test_rejects_an_incomplete_policy(self):
        with self.assertRaises(ValueError):
            validate_moves_config({"version": 1})

    def test_builds_a_scoreable_layout_from_active_geometry(self):
        import json

        geometry_path = Path(__file__).resolve().parents[1] / "config" / "geometry.json"
        document = json.loads(geometry_path.read_text(encoding="utf-8"))
        layout = build_layout(document["layouts"][document["active_layout"]])

        self.assertEqual(38, len(layout.keys))
        self.assertEqual("й", layout.get_key_by_char("й").char)
        self.assertTrue(layout.get_key_by_char("Shft").is_frozen)
        self.assertGreater(calculate_total_penalty(layout, "йцук"), 0)

    def test_builds_every_geometry_layout(self):
        import json

        geometry_path = Path(__file__).resolve().parents[1] / "config" / "geometry.json"
        document = json.loads(geometry_path.read_text(encoding="utf-8"))

        for geometry in document["layouts"].values():
            self.assertEqual(38, len(build_layout(geometry).keys))


if __name__ == '__main__':
    unittest.main()
