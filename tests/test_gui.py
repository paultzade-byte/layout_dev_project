"""Перемикання геометрії в GUI. Потрібен дисплей: локально — xvfb-run."""
import os
import time

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
        assert ui.tab_bar.winfo_manager() and ui.button_panel.keyboard_frame.winfo_manager()
        split_chars = [k.char for k in ui.layout.keys]

        ui.on_mode("generic_105_alpha")
        root.update()
        assert ui.geometry_name == "generic_105_alpha"
        assert not ui.tab_bar.winfo_manager()
        assert not ui.button_panel.keyboard_frame.winfo_manager()   # група «На клаву / З клави» схована
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
        assert ui.tab_bar.winfo_manager() and ui.button_panel.keyboard_frame.winfo_manager()
        assert not ui.button_panel.button_export.winfo_manager()
        ui.on_mode("generic_105_alpha")
        assert [k.char for k in ui.layout.keys] == edited
        # ряд кнопок — від краю до краю (20 px полів), вікно звужується назад після Corne
        root.update()
        shown = [b for g in ui.button_panel.groups for b in g.winfo_children() if b.winfo_ismapped()]
        x0 = root.winfo_rootx()
        assert shown[0].winfo_rootx() - x0 == 20
        assert root.winfo_width() - (shown[-1].winfo_rootx() - x0 + shown[-1].winfo_width()) == 20
        assert root.winfo_width() < 1000
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
        opened = []
        monkeypatch.setattr(A, "reveal_in_file_manager", opened.append)
        ui.on_export()
        (out,) = tmp_path.glob("ukr-layout_*")
        assert opened == [out]                       # тека з файлами відкривається в Провіднику
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


def test_board_fits_after_knobs_then_mode_switch():
    """«Детальніше» на Corne, потім «Звичайна» — нижній ряд ANSI (пробіл)
    не обрізається: вікно дорощується до повної висоти дошки."""
    from uiux import app as A
    root = tk.Tk()
    try:
        ui = A.LayoutBuilderApp(root, A.STATISTIC, A.MOVES_CONFIG,
                                on_layout_changed=A.make_score_display(A.STATISTIC, A.MOVES_CONFIG),
                                geometry_name="corne_42")
        root.update()
        ui.toggle_knobs()
        root.update()
        ui.on_mode("generic_105_alpha")
        for _ in range(5):
            root.update()
        bottom = max(s.y for s in ui.slots) + ui.key_height
        assert ui.board.winfo_height() >= bottom, (ui.board.winfo_height(), bottom)
        ansi_h = root.winfo_height()
        # навпаки: назад на Corne — вікно нижчає, без порожнечі під клавішами
        ui.on_mode("corne_42")
        for _ in range(5):
            root.update()
        bottom = max(s.y for s in ui.slots) + ui.key_height
        assert bottom <= ui.board.winfo_height() <= bottom + 2 * A.layer_view.BASE_Y + 4
        assert root.winfo_height() < ansi_h
        ui.toggle_knobs()
        root.update()
        assert ui.board.winfo_height() >= bottom
    finally:
        root.destroy()


def test_ycuken_button_resets_board(monkeypatch, tmp_path):
    from uiux import app as A
    root = tk.Tk()
    try:
        ui = A.LayoutBuilderApp(root, A.STATISTIC, A.MOVES_CONFIG,
                                on_layout_changed=A.make_score_display(A.STATISTIC, A.MOVES_CONFIG),
                                geometry_name="corne_42")
        root.update()
        assert not ui.button_ycuken.winfo_manager()          # на спліті кнопки нема
        ui.on_mode("generic_105_alpha")
        root.update()
        assert ui.button_ycuken.winfo_manager()
        ycuken = {p["id"]: p["default"] for p in ui.geometry["positions"] if p.get("default")}
        assert any(ycuken.get(k.position_id) != k.char for k in ui.layout.keys)   # старт — A
        # Скасувати — нічого не міняється
        monkeypatch.setattr(A.messagebox, "askyesnocancel", lambda *a, **k: None)
        before = [k.char for k in ui.layout.keys]
        ui.on_ycuken()
        assert [k.char for k in ui.layout.keys] == before
        # Так, але діалог збереження скасовано — теж нічого
        monkeypatch.setattr(A.messagebox, "askyesnocancel", lambda *a, **k: True)
        monkeypatch.setattr(A.filedialog, "asksaveasfilename", lambda *a, **k: "")
        ui.on_ycuken()
        assert [k.char for k in ui.layout.keys] == before
        # Так і збережено — файл є, дошка скинута
        saved = tmp_path / "before_reset.json"
        monkeypatch.setattr(A.filedialog, "asksaveasfilename", lambda *a, **k: str(saved))
        ui.on_ycuken()
        root.update()
        assert saved.exists()
        assert all(ycuken.get(k.position_id, k.char) == k.char for k in ui.layout.keys)
        # Ні — скинути без збереження
        monkeypatch.setattr(A.messagebox, "askyesnocancel", lambda *a, **k: False)
        ui.on_default_layout()
        root.update()
        ui.on_ycuken()
        root.update()
        assert all(ycuken.get(k.position_id, k.char) == k.char for k in ui.layout.keys)
        assert ui.current_file is None
        # «↺ За замовчуванням» — назад до стартової (A)
        assert ui.button_default.winfo_manager()
        ui.on_default_layout()
        root.update()
        start = {k.position_id: k.char for k in A.start_layout("generic_105_alpha").keys}
        assert all(start[k.position_id] == k.char for k in ui.layout.keys)
    finally:
        root.destroy()


def test_presets_menu_apply_save_delete(monkeypatch):
    from config import settings
    from uiux import app as A
    settings.save(knobs={}, presets={})
    root = tk.Tk()
    try:
        ui = A.LayoutBuilderApp(root, A.STATISTIC, A.load_moves("generic_105_alpha"),
                                geometry_name="generic_105_alpha")
        root.update()
        assert "Рекомендовано" in ui.button_preset.cget("text")
        ui.apply_preset("Бережу мізинці", A.knobs.PRESETS[2].state())
        root.update()
        assert "Бережу мізинці" in ui.button_preset.cget("text")
        assert A.knobs.step(ui.knob_rows["pinky"].scale.get()) == 2
        ui.knob_rows["vertical"].scale.set(1)
        ui.on_knob_release("vertical")
        assert "свій" in ui.button_preset.cget("text")
        monkeypatch.setattr(A.simpledialog, "askstring", lambda *a, **k: "мій")
        ui.on_preset_save()
        assert "мій" in ui.button_preset.cget("text")
        assert "мій" in settings.load()["presets"]["generic_105_alpha"]
        ui.on_preset_delete("мій")
        assert "свій" in ui.button_preset.cget("text")
        # tk_popup на Windows — модальний цикл меню: у CI ніхто його не закриє
        # і тест висить вічно (2026-11-19). Перевіряємо лише, що меню будується.
        popups = []
        monkeypatch.setattr(A.tk.Menu, "tk_popup", lambda self, *a, **k: popups.append(self))
        ui.show_preset_menu()   # меню будується без помилок
        assert popups
        root.update()
    finally:
        root.destroy()


def test_tooltip_shows_and_hides():
    from uiux import tooltip
    root = tk.Tk()
    try:
        root.geometry("300x200")
        b = tk.Button(root, text="x")
        b.pack()
        tip = tooltip.add(b, "підказка")
        root.update()
        tip._show()
        assert tip._tip is not None and tip._tip.cget("text") == "підказка"
        tip._hide()
        assert tip._tip is None
    finally:
        root.destroy()


def test_cpu_menu_default_and_remembered(monkeypatch):
    from config import settings
    from uiux import app as A
    settings.save(cpu_percent=None)
    root = tk.Tk()
    try:
        ui = A.LayoutBuilderApp(root, A.STATISTIC, A.load_moves("generic_105_alpha"),
                                geometry_name="generic_105_alpha")
        root.update()
        assert ui.button_cpu.cget("text") == "CPU: 25% ▾"      # скромно на чужому комп'ютері
        popups = []
        monkeypatch.setattr(A.tk.Menu, "tk_popup", lambda self, *a, **k: popups.append(self))
        ui.show_cpu_menu()
        assert popups and popups[0].index("end") == len(A.throttle.CHOICES) - 1
        ui.set_cpu(75)
        assert ui.button_cpu.cget("text") == "CPU: 75% ▾"
        assert settings.load()["cpu_percent"] == 75
        assert ui.processor.cpu_percent == 75
        ui.set_geometry("corne_42")                            # новий процесор — та сама частка
        assert ui.processor.cpu_percent == 75
    finally:
        settings.save(cpu_percent=None)
        root.destroy()


def test_tooltip_text_can_be_a_function():
    from uiux import tooltip
    root = tk.Tk()
    try:
        root.geometry("300x200")
        b = tk.Button(root, text="x")
        b.pack()
        state = {"text": "раз"}
        tip = tooltip.add(b, lambda: state["text"])
        root.update()
        tip._show()
        assert tip._tip.cget("text") == "раз"
        tip._hide()
        state["text"] = ""
        tip._show()
        assert tip._tip is None                                # порожня — не показуємо
    finally:
        root.destroy()


def test_layer_caption_fits_inside_panel():
    """Підпис шару (опис + як увімкнути + підказка) не обрізається знизу панелі."""
    from uiux import app as A
    root = tk.Tk()
    try:
        ui = A.LayoutBuilderApp(root, A.STATISTIC, A.load_moves("corne_42"), geometry_name="corne_42")
        root.update()
        if not ui._zmk_mode() or ui.layer_view.dump is None:
            pytest.skip("нема ZMK-скриптів або дампу")
        longest = max(A.layer_view.CELLS, key=lambda p: len(A.layer_view.lh.pos_name(p)))
        for name in A.layer_view.lh.ORDER:
            ui.show_tab(name)
            ui.layer_view.caption_hint(A.layer_view.lh.pos_name(longest))
            root.update()
            lv = ui.layer_view
            assert lv.caption.winfo_y() + lv.caption.winfo_reqheight() <= lv.winfo_height(), name
    finally:
        root.destroy()


def test_heat_buttons_hold_click_and_tabs():
    import time
    from uiux import app as A
    root = tk.Tk()
    try:
        ui = A.LayoutBuilderApp(root, A.STATISTIC, A.load_moves("corne_42"), geometry_name="corne_42")
        root.update()
        widget = ui.slots[0].current_key
        finger_bg = widget.cget("bg")
        ui._heat_press("freq"); ui._heat_release("freq")            # клік — лишити
        assert ui.heat_shown == ui.heat_latched == "freq" and widget.cget("bg") != finger_bg
        ui._heat_press("pain")
        ui._heat_pressed = ("pain", time.monotonic() - 1)           # затиснули й тримали
        assert ui.heat_shown == "pain"
        ui._heat_release("pain")
        assert ui.heat_shown == "freq"                              # назад до лишеної
        if ui._zmk_mode():
            ui.show_tab("GRAPH")                                    # на шарах мапи нема
            assert ui.heat_shown is None and ui.heat_buttons["freq"].cget("state") == "disabled"
            ui.show_tab("Редактор")
        ui._heat_press("freq"); ui._heat_release("freq")
        ui._heat_press("freq"); ui._heat_release("freq")            # ще клік — вимкнути
        assert ui.heat_shown is None and widget.cget("bg") == finger_bg
    finally:
        root.destroy()


def test_statistic_menu_switch_and_remember(tmp_path, monkeypatch):
    from config import settings, stats_files
    from core import corpus
    from uiux import app as A
    src = tmp_path / "t.txt"
    src.write_text("Їжак з'їв ґрунт, єнот пʼє воду. " * 300, encoding="utf-8")
    monkeypatch.setattr(stats_files, "stats_dir", lambda: tmp_path / "stats")
    path = corpus.write_statistic_file(corpus.count_corpus([src], "uk", 1.0), tmp_path / "stats", "мої")
    root = tk.Tk()
    try:
        ui = A.LayoutBuilderApp(root, A.STATISTIC, A.MOVES_CONFIG,
                                on_layout_changed=A.make_score_display(A.STATISTIC, A.MOVES_CONFIG),
                                geometry_name="generic_105_alpha")
        root.update()
        assert "вбудована" in ui.button_stats.cget("text")
        before = ui._current_score()
        assert ui.set_statistic(path)
        deadline = time.time() + 60
        while time.time() < deadline and ui._current_score() == before:
            root.update()
            time.sleep(0.05)
        assert ui._current_score() != before
        assert "ukr_мої" in ui.button_stats.cget("text")
        assert settings.load()["statistic_file"] == str(path)
        stat, chosen = A.startup_statistic()
        assert chosen == path and stat["unigrams"] == ui.statistic["unigrams"]
        assert ui.set_statistic(stats_files.BUILTIN)
        assert settings.load()["statistic_file"] is None
    finally:
        root.destroy()


def test_toast_timeout_capped_and_hover_keeps(monkeypatch):
    """Плашки — не довше MAX_MS (навіть із ms=12000); курсор над плашкою — не зникає."""
    from uiux import toast
    calls = []
    monkeypatch.setattr(toast, "auto_close", lambda w, ms, close: calls.append(ms))
    root = tk.Tk()
    try:
        t = toast.Toasts(root)
        t.show("довгий\nтекст", ms=12000)
        t.show("коротко", ms=1000)
        t.show("типово")
        assert calls == [toast.MAX_MS, 1000, toast.MAX_MS]
    finally:
        root.destroy()


def test_saved_layout_is_next_session_start(tmp_path, monkeypatch):
    """«Зберегти як…» -> наступний сеанс режиму стартує з цього файлу;
    «↺ За замовчуванням» лишається вбудованою, зіпсований файл — теж вбудована."""
    from uiux import app as A
    from config import settings
    old = settings.load().get("start_files")
    root = tk.Tk()
    try:
        ui = A.LayoutBuilderApp(root, A.STATISTIC, A.load_moves("generic_105_alpha"),
                                on_layout_changed=lambda *_: None, geometry_name="generic_105_alpha")
        builtin = {k.position_id: k.char for k in A.start_layout("generic_105_alpha").keys}
        a, b = ui.layout.keys[0], ui.layout.keys[1]
        a.char, b.char = b.char, a.char
        a.is_frozen = True
        saved = tmp_path / "mine.json"
        monkeypatch.setattr(A.filedialog, "asksaveasfilename", lambda *x, **k: str(saved))
        assert ui.on_save_as()
        layout, path = ui._session_start_layout("generic_105_alpha")
        assert path == saved.resolve()
        got = {k.position_id: k for k in layout.keys}
        assert got[a.position_id].char == a.char and got[a.position_id].is_frozen
        assert {k.position_id: k.char for k in A.start_layout("generic_105_alpha").keys} == builtin
        saved.write_text("зіпсовано", encoding="utf-8")
        layout, path = ui._session_start_layout("generic_105_alpha")
        assert path is None
        assert {k.position_id: k.char for k in layout.keys} == builtin
    finally:
        settings.save(start_files=old)
        root.destroy()


def test_start_with_all_frozen_returns_to_idle():
    """QA 2026-11-26: рухомих літер < 2 -> ValueError у воркері; GUI висів на «Оптимізую...»."""
    from uiux import app as A
    root = tk.Tk()
    try:
        ui = A.LayoutBuilderApp(root, A.STATISTIC, A.load_moves("generic_105_alpha"),
                                geometry_name="generic_105_alpha")
        root.update()
        for key in ui.layout.keys:
            key.is_frozen = True
        ui.toggle_optimization()
        _wait(root, lambda: not ui.processor.is_running and ui.toasts.items)
        root.update()
        assert ui.button_panel.button_start.cget("text") == "Start"
        assert "Оптимізую" not in ui.status_var.get()
        assert "менше двох" in ui.toasts.items[-1].winfo_children()[0].cget("text")
    finally:
        root.destroy()


def test_open_layout_without_is_frozen(tmp_path, monkeypatch):
    """QA 2026-11-26: файл без поля is_frozen -> KeyError поза try в «Відкрити…»."""
    import json
    from uiux import app as A
    root = tk.Tk()
    try:
        ui = A.LayoutBuilderApp(root, A.STATISTIC, A.load_moves("generic_105_alpha"),
                                geometry_name="generic_105_alpha")
        root.update()
        data = [{"position_id": k.position_id, "char": k.char} for k in ui.layout.keys]
        a, b = [i for i, d in enumerate(data) if len(d["char"]) == 1 and d["char"].isalpha()][:2]
        data[a]["char"], data[b]["char"] = data[b]["char"], data[a]["char"]
        path = tmp_path / "no_frozen.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr("tkinter.filedialog.askopenfilename", lambda **kw: str(path))
        ui.on_open()
        root.update()
        chars = {k.position_id: k.char for k in ui.layout.keys}
        assert chars[data[a]["position_id"]] == data[a]["char"]
        assert not any(k.is_frozen for k in ui.layout.keys if k.position_id in (data[a]["position_id"], data[b]["position_id"]))
    finally:
        root.destroy()


def test_editor_tab_keeps_start_off_while_weights_rebuild():
    """QA 2026-11-26 (Corne): під час фонового _rebuild_weights вкладка «Редактор»
    знову вмикала Start, а done() потім підміняв processor під живим пошуком."""
    from uiux import app as A
    root = tk.Tk()
    try:
        ui = A.LayoutBuilderApp(root, A.STATISTIC, A.MOVES_CONFIG,
                                on_layout_changed=A.make_score_display(A.STATISTIC, A.MOVES_CONFIG),
                                geometry_name="corne_42")
        root.update()
        if not ui._zmk_mode():
            pytest.skip("немає вкладок шарів")
        engine = ui.engine
        ui._rebuild_weights("тест")
        ui.show_tab("Редактор")
        assert ui.button_panel.button_start.cget("state") == "disabled"
        ui.toggle_optimization()                      # напр. гаряча клавіша — теж ні
        assert not ui.processor.is_running
        _wait(root, lambda: ui.engine is not engine)
        assert ui.button_panel.button_start.cget("state") == "normal"
    finally:
        root.destroy()


def test_worker_never_calls_tk_after_window_closed():
    """QA 2026-11-26: воркер кликав root.after з потоку -> закрили вікно під час пошуку ->
    RuntimeError у потоці. Тепер усе з потоків іде через чергу (_from_worker)."""
    import threading
    from uiux import app as A
    errors = []
    old_hook = threading.excepthook
    threading.excepthook = lambda a: errors.append(repr(a.exc_value))
    root = tk.Tk()
    try:
        ui = A.LayoutBuilderApp(root, A.STATISTIC, A.load_moves("generic_105_alpha"),
                                geometry_name="generic_105_alpha")
        root.update()
        ui.toggle_optimization()
        _wait(root, lambda: "ітерація" in ui.status_var.get())   # прогрес доходить до UI
        processor = ui.processor
        root.destroy()
        time.sleep(1.0)                                          # воркер ще шле прогрес
        processor.stop()
        processor._thread.join(30)
        assert not processor._thread.is_alive()
        assert errors == []
    finally:
        threading.excepthook = old_hook
        try:
            root.destroy()
        except tk.TclError:
            pass


def test_search_stop_returns_result_through_queue():
    from uiux import app as A
    root = tk.Tk()
    try:
        moves = A.load_moves("generic_105_alpha")
        ui = A.LayoutBuilderApp(root, A.STATISTIC, moves,
                                on_layout_changed=A.make_score_display(A.STATISTIC, moves),
                                geometry_name="generic_105_alpha")
        root.update()
        ui.toggle_optimization()
        _wait(root, lambda: "ітерація" in ui.status_var.get())
        ui.toggle_optimization()                                  # Stop
        _wait(root, lambda: ui.button_panel.button_start.cget("text") == "Start")
        assert not ui.processor.is_running and "Оптимізую" not in ui.status_var.get()
    finally:
        root.destroy()
