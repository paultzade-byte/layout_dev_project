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
        assert app.result_path.parent == tmp_path / "out" and app.result_path.name.startswith("ukr_texts_")
        data = json.loads(app.result_path.read_text(encoding="utf-8"))
        assert data["unigrams"]["'"] == 100
        assert data["meta"]["language"] == "uk" and data["meta"]["corpus"] == "texts"
        assert data["words"]["п'є"] == 50
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


@pytest.mark.parametrize("bad", [True, 5, ["a"], {"a": 1}, "", "50", 50.0])
def test_bad_saved_settings_use_defaults(tmp_path, monkeypatch, bad):
    """QA 2026-11-26: stats_corpus / stats_out не рядком -> Path(True) і TypeError на старті
    ukr-stats; stats_cpu рядком -> TypeError при Старт. Неправильні значення — типові."""
    from config import settings
    from config.stats_files import stats_dir
    from uiux import stats_app as S
    monkeypatch.setenv("LAYOUT_USER_DIR", str(tmp_path))
    settings.save(stats_corpus=bad, stats_out=bad, stats_cpu=bad)
    root = tk.Tk()
    try:
        app = S.StatsApp(root)
        root.update()
        if not (isinstance(bad, str) and bad):    # рядок — це шлях, хай і дивний
            assert app.corpus_dir is None and app.out_dir == stats_dir()
        assert app.cpu == 25 and type(app.cpu) is int
    finally:
        root.destroy()
