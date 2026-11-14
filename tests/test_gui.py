"""Перемикання геометрії в GUI. Потрібен дисплей: локально — xvfb-run."""
import os

import pytest

tk = pytest.importorskip("tkinter")
if not os.environ.get("DISPLAY") and os.name != "nt":
    pytest.skip("немає дисплея (запусти через xvfb-run)", allow_module_level=True)


def test_set_geometry_round_trip():
    from uiux import app as A
    root = tk.Tk()
    try:
        ui = A.LayoutBuilderApp(root, A.STATISTIC, A.MOVES_CONFIG,
                                on_layout_changed=A.make_score_display(A.STATISTIC, A.MOVES_CONFIG),
                                geometry_name="corne_42")
        root.update()
        split_status, split_slots = ui.status_var.get(), len(ui.slots)
        assert ui.set_geometry("generic_105_alpha")
        root.update()
        assert len(ui.slots) == len(ui.geometry["positions"]) != split_slots
        assert ui.status_var.get() != split_status
        path = ui.processor.layout_record(ui.layout, ui.geometry_name)
        assert path.name == "recorded_generic_105_alpha.json"
        assert ui.set_geometry("corne_42")
        root.update()
        assert ui.status_var.get() == split_status
    finally:
        root.destroy()
