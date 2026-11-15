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
        assert ui.button_panel.button_export.winfo_manager()       # експорт — лише тут
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
        assert not ui.button_panel.button_export.winfo_manager()
        ui.on_mode("generic_105_alpha")
        assert [k.char for k in ui.layout.keys] == edited
    finally:
        root.destroy()
        settings.save(mode=None)


def test_export_button_writes_files(tmp_path, monkeypatch):
    from uiux import app as A
    root = tk.Tk()
    try:
        ui = A.LayoutBuilderApp(root, A.STATISTIC, A.MOVES_CONFIG,
                                on_layout_changed=A.make_score_display(A.STATISTIC, A.MOVES_CONFIG),
                                geometry_name="generic_105_alpha")
        root.update()
        monkeypatch.setattr(A.filedialog, "askdirectory", lambda **kw: str(tmp_path))
        ui.on_export()
        (out,) = tmp_path.glob("ukr-layout_*")
        assert {p.suffix for p in out.iterdir()} == {".klc", ".xkb", ".keylayout", ".txt"}
        assert "Експорт" in ui.status_var.get()
    finally:
        root.destroy()


def test_altgr_marks_follow_letters():
    from uiux import app as A
    root = tk.Tk()
    try:
        ui = A.LayoutBuilderApp(root, A.STATISTIC, A.load_moves("generic_105_alpha"),
                                geometry_name="generic_105_alpha")
        root.update()
        altgr = ui.geometry["altgr"]
        marks = {s.current_key.key.char: s.current_key.altgr_label for s in ui.slots}
        for char, extra in altgr.items():
            assert marks[char].winfo_manager() and marks[char].cget("text") == extra
        assert not marks["а"].winfo_manager()
        # своп «о» з «а»: мітка ' переїжджає разом з «о»
        o = next(s for s in ui.slots if s.current_key.key.char == "о")
        a = next(s for s in ui.slots if s.current_key.key.char == "а")
        wo, wa = o.current_key, a.current_key
        ui.snap_to_slot(wo, a)
        ui.snap_to_slot(wa, o)
        ui._sync_layout_from_ui()
        root.update()
        assert wo.altgr_label.cget("text") == altgr["о"] and wo.current_slot is a
        assert not wa.altgr_label.winfo_manager()
    finally:
        root.destroy()


def _wait(root, cond, timeout=60):
    import time
    end = time.time() + timeout
    while not cond() and time.time() < end:
        root.update()
        time.sleep(0.05)
    assert cond()


def test_knob_release_rebuilds_weights_without_blocking():
    from config import settings
    from uiux import app as A
    root = tk.Tk()
    try:
        ui = A.LayoutBuilderApp(root, A.STATISTIC, A.load_moves("generic_105_alpha"),
                                on_layout_changed=A.make_score_display(A.STATISTIC,
                                                                       A.load_moves("generic_105_alpha")),
                                geometry_name="generic_105_alpha")
        root.update()
        ui.toggle_knobs()
        root.update()
        assert "% натискань" in ui.knob_rows["home_row"].metric.cget("text")
        before = ui._current_score()
        engine = ui.engine
        ui.knob_rows["vertical"].scale.set(2)
        ui.on_knob_release("vertical")
        _wait(root, lambda: ui.engine is not engine)
        assert ui.moves["same_finger"]["vertical"] == ui.base_moves["same_finger"]["vertical"] * 2
        assert ui._current_score() != before
        assert ui.toasts.items and "Start" in ui.toasts.items[-1].winfo_children()[0].cget("text")
        assert settings.load()["knobs"]["generic_105_alpha"]["values"]["vertical"] == 2
        # рух у межах того ж кроку — без перерахунку
        engine = ui.engine
        ui.knob_rows["vertical"].scale.set(1.8)
        ui.on_knob_release("vertical")
        root.update()
        assert ui.engine is engine
        # скинути — назад до файлових ваг
        ui.on_knobs_reset()
        _wait(root, lambda: ui.engine is not engine)
        assert ui.moves == ui.base_moves
        assert abs(ui._current_score() - before) < 1e-9
    finally:
        root.destroy()
        settings.save(knobs={})


def test_toasts_stack_and_close():
    from uiux.toast import Toasts
    root = tk.Tk()
    try:
        t = Toasts(root)
        a, b = t.show("один"), t.show("два\nрядки", ms=10)
        root.update()
        assert t.items == [a, b]
        t.close(a)
        _wait(root, lambda: not t.items, timeout=5)
    finally:
        root.destroy()


def test_entry_point_smoke():
    """ukr_layout.py --smoke (те саме, що перевіряє CI на зібраному exe):
    вікно будується повністю і закривається без помилки."""
    import ukr_layout
    assert ukr_layout.run(["--smoke"]) == 0
