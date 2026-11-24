"""Тренажер: генератор вправ, рівні, перекладач клавіш, сесія; вікно — з дисплеєм."""
import os
import random
from types import SimpleNamespace

import pytest

from config.main_config import STATISTIC, geometry_config
from core import trainer as T


def _chars(geometry_name):
    from uiux.app import start_layout
    return {k.position_id: k.char for k in start_layout(geometry_name).keys}


def test_quotes_and_normalize():
    quotes = T.load_quotes()
    assert len(quotes) >= 50 and all(q["author"] and q["source"].startswith("https://uk.wikisource.org")
                                     for q in quotes)
    assert T.normalize("П’ять — «М'ясо», ʼї!") == "п'ять м'ясо 'ї"
    words = T.quote_words(quotes)
    assert words["сонце"] >= 2 and all(set(w) <= set(T.ALPHABET) for w in words)


@pytest.mark.parametrize("name", ["generic_105_alpha", "corne_42"])
def test_levels_start_from_home_row_and_reach_all(name):
    geometry, chars = geometry_config(name), _chars(name)
    order = T.make_order(chars, geometry, STATISTIC["unigrams"])
    home = {ch for pid, ch in chars.items() if ch in T.ALPHABET
            and next(p for p in geometry["positions"] if p["id"] == pid)["row"] == 1}
    assert set(T.letters_at(order, 0)) == home
    last = T.letters_at(order, T.level_count(order) - 1)
    assert len(last) == len(order) == len(set(order)) and "'" in order
    assert len(T.letters_at(order, 1)) == len(home) + T.STEP


def test_lines_use_only_unlocked_letters_and_focus():
    src = T.WordSource(T.quote_words(T.load_quotes()), STATISTIC["bigrams"], random.Random(3))
    allowed = list("оанівртк")              # мало слів — домішуються псевдослова
    for _ in range(20):
        line = src.line(allowed, "к")
        assert set(line) <= set(allowed) | {" "} and len(line) >= T.LINE_CHARS - 10
    many = [src.line(allowed, "к") for _ in range(30)]
    assert sum(line.count("к") for line in many) > sum(line.count("т") for line in many)


def test_translator_physical_keys():
    geometry = geometry_config("generic_105_alpha")
    chars = _chars("generic_105_alpha")
    by_key = {p["key"]: chars[p["id"]] for p in geometry["positions"] if p.get("key")}
    x11 = T.Translator(chars, geometry, "x11")
    win = T.Translator(chars, geometry, "win32")
    mac = T.Translator(chars, geometry, "aqua")
    assert x11.translate(24, "й", 0) == by_key["AD01"]          # фізична Q на ЙЦУКЕН
    assert x11.translate(24, "q", 0) == by_key["AD01"]          # та сама клавіша на QWERTY
    assert win.translate(ord("Q"), "й", 0) == by_key["AD01"]
    assert mac.translate(12, "й", 0) == by_key["AD01"]           # keycode незнайомий — за символом
    assert x11.translate(65, " ", 0) == " " and x11.translate(50, "", 1) is None   # Shift — нічого
    base, extra = next(iter(geometry["altgr"].items()))
    key = next(p["key"] for p in geometry["positions"] if chars[p["id"]] == base)
    assert x11.translate(T._ROWS[key][0], "?", 0x80) == extra
    assert win.translate(T._ROWS[key][1], "?", 0x20000 | 0x4) == extra
    assert T.as_is("’") == "'" and T.as_is("Ж") == "ж" and T.as_is("1") is None


def test_session_counts_errors_and_waits():
    s = T.Session("ab")
    assert not s.type("x", 0.0) and s.pos == 0 and s.errors == 1 and s.misses["a"] == 1
    assert s.type("a", 0.5) and s.type("b", 1.0) and s.done
    assert s.accuracy() == pytest.approx(200 / 3) and s.cpm(5.0) == pytest.approx(60.0)   # 1 знак після першого за 1 с


tk = pytest.importorskip("tkinter")
needs_display = pytest.mark.skipif(not os.environ.get("DISPLAY") and os.name != "nt",
                                   reason="немає дисплея (xvfb-run)")


@needs_display
def test_trainer_window_types_through_translator(tmp_path, monkeypatch):
    monkeypatch.setenv("LAYOUT_USER_DIR", str(tmp_path))
    from uiux import app as A
    root = tk.Tk()
    try:
        ui = A.LayoutBuilderApp(root, A.STATISTIC, A.load_moves("generic_105_alpha"),
                                geometry_name="generic_105_alpha")
        root.update()
        tw = ui.on_train()
        root.update()
        assert tw.win.grab_current() is not None and tw.translate
        pos_of = {ch: p for p in tw.geometry["positions"] if p.get("key")
                  for ch in [tw.chars[p["id"]]]}
        if tw.translator.windowing != "x11":
            pytest.skip("перевірка keycode — для X11")
        for _ in range(12):                       # перші 12 знаків рядка — через фізичні клавіші
            ch = tw.session.text[tw.session.pos]
            code = 65 if ch == " " else T._ROWS[pos_of[ch]["key"]][0]
            tw._on_key(SimpleNamespace(keysym="x", keycode=code, char="?", state=0))
        assert tw.session.pos == 12 and tw.session.errors == 0
        tw._on_key(SimpleNamespace(keysym="x", keycode=65, char=" ", state=0)
                   if tw.session.text[12] != " " else SimpleNamespace(keysym="x", keycode=24, char="", state=0))
        assert tw.session.errors == 1 and tw.session.pos == 12
        tw.scale.set(2)
        root.update()
        assert len(tw.allowed) == len(T.letters_at(tw.order, 0)) + 2 * T.STEP
        tw.close()
        from config import settings
        assert settings.load()["trainer_levels"]["generic_105_alpha"] == 2
    finally:
        root.destroy()
