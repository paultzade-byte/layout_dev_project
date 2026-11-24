"""Міні-апка статистики (uiux/stats_app.py). Потрібен дисплей: локально — xvfb-run."""
import json
import os
import time

import pytest

tk = pytest.importorskip("tkinter")
if not os.environ.get("DISPLAY") and os.name != "nt":
    pytest.skip("немає дисплея (запусти через xvfb-run)", allow_module_level=True)


def test_pick_detect_run_write(tmp_path):
    from uiux import stats_app as S
    src = tmp_path / "texts" / "sub"
    src.mkdir(parents=True)
    (src / "a.txt").write_text("Їжак з'їв ґрунт, єнот пʼє воду. " * 50, encoding="utf-8")
    (tmp_path / "texts" / "skip.md").write_text("ігнор", encoding="utf-8")
    root = tk.Tk()
    try:
        app = S.StatsApp(root, str(tmp_path / "texts"))
        app.out_dir = tmp_path / "out"
        root.update()
        assert len(app.files) == 1 and app.detected == "uk"
        assert "Українська (авто)" in app.button_lang.cget("text")
        assert app.button_start.cget("state") == "normal"
        app.toggle()
        assert app.button_corpus.cget("state") == "disabled"
        deadline = time.time() + 60
        while app.worker and time.time() < deadline:
            root.update()
            time.sleep(0.05)
        root.update()
        assert app.worker is None and app.button_start.cget("text") == "Старт"
        stat = json.loads((tmp_path / "out" / "statistic.json").read_text(encoding="utf-8"))
        assert stat["unigrams"]["'"] == 100
        words = json.loads((tmp_path / "out" / "word_stats.json").read_text(encoding="utf-8"))
        assert words["meta"]["language"] == "uk" and words["words"]["п'є"] == 50
    finally:
        root.destroy()


def test_empty_folder_disables_start(tmp_path):
    from uiux import stats_app as S
    root = tk.Tk()
    try:
        app = S.StatsApp(root, str(tmp_path))
        root.update()
        assert app.files == [] and app.button_start.cget("state") == "disabled"
        assert "виберіть теку" in app._start_tip()
    finally:
        root.destroy()
