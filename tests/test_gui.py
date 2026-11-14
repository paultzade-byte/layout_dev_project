"""Перемикання геометрії в GUI. Потрібен дисплей: локально — xvfb-run."""
import os

import pytest

tk = pytest.importorskip("tkinter")
if not os.environ.get("DISPLAY") and os.name != "nt":
    pytest.skip("немає дисплея (запусти через xvfb-run)", allow_module_level=True)


def test_set_geometry_round_trip(tmp_path):
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
        path = ui.processor.layout_save(ui.layout, tmp_path / "std.json")
        assert ui.layout_file_problem(ui.processor.layout_load(path)) is None
        shot = ui.save_screenshot(tmp_path / ui.screenshot_name())
        assert shot.exists() and "generic_105_alpha" in shot.name
        assert ui.set_geometry("corne_42")
        root.update()
        assert ui.status_var.get() == split_status
        # розкладка звичайної клавіатури не відкривається в режимі спліта
        assert "іншої клавіатури" in ui.layout_file_problem(ui.processor.layout_load(path))
    finally:
        root.destroy()


def test_mode_toggle_hides_zmk_and_remembers(tmp_path):
    import json
    from config import settings
    from config.main_config import CONFIG_DIR, geometry_config
    from uiux import app as A
    root = tk.Tk()
    try:
        ui = A.LayoutBuilderApp(root, A.STATISTIC, A.MOVES_CONFIG,
                                on_layout_changed=A.make_score_display(A.STATISTIC, A.MOVES_CONFIG),
                                geometry_name="corne_42")
        root.update()
        assert ui.tab_bar.winfo_manager() and ui.button_panel.button_kb_write.winfo_manager()
        split_chars = [k.char for k in ui.layout.keys]

        ui.on_mode("generic_105_alpha")
        root.update()
        assert ui.geometry_name == "generic_105_alpha"
        assert not ui.tab_bar.winfo_manager()
        assert not ui.button_panel.button_kb_write.winfo_manager()
        assert settings.load()["mode"] == "generic_105_alpha"
        assert settings.initial_mode(A.GEOMETRIES) == "generic_105_alpha"
        # старт «Звичайної» — розкладка з start_layout (кандидат A)
        start = geometry_config("generic_105_alpha")["start_layout"]
        want = {d["position_id"]: d["char"] for d in json.loads((CONFIG_DIR / start).read_text(encoding="utf-8"))}
        assert all(k.char == want[k.position_id] for k in ui.layout.keys if k.position_id in want)

        # правка в одному режимі переживає перемикання туди й назад
        a, b = ui.layout.keys[0], ui.layout.keys[1]
        a.char, b.char = b.char, a.char
        edited = [k.char for k in ui.layout.keys]
        ui.on_mode("corne_42")
        root.update()
        assert [k.char for k in ui.layout.keys] == split_chars
        assert ui.tab_bar.winfo_manager() and ui.button_panel.button_kb_write.winfo_manager()
        ui.on_mode("generic_105_alpha")
        assert [k.char for k in ui.layout.keys] == edited
    finally:
        root.destroy()
        settings.save(mode=None)
