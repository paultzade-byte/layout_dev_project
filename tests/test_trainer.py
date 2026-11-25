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
    assert T.as_is("’") == "'" and T.as_is("1") is None


def test_session_counts_errors_and_waits():
    s = T.Session("ab")
    assert not s.type("x", 0.0) and s.pos == 0 and s.errors == 1 and s.misses["a"] == 1
    assert s.type("a", 0.5) and s.type("b", 1.0) and s.done
    assert s.accuracy() == pytest.approx(200 / 3) and s.cpm(5.0) == pytest.approx(60.0)   # 1 знак після першого за 1 с


def test_session_letter_stats_and_merge(tmp_path, monkeypatch):
    monkeypatch.setenv("LAYOUT_USER_DIR", str(tmp_path))
    s = T.Session("аб ба")
    for ch, t in [("а", 0.0), ("х", 0.1), ("б", 0.3), (" ", 0.5), ("б", 0.7), ("а", 10.0)]:
        s.type(ch, t)
    assert s.done and s.hits == {"а": 2, "б": 1} and s.misses == {"б": 1}   # перша б з помилкою — не hit
    assert s.timed == {"б": 1} and s.time_ms["б"] == pytest.approx(200)   # а після паузи 9.3 с — без часу
    stats = T.merge_stats({}, s)
    T.save_stats("generic_105_alpha", stats)
    assert T.load_stats("generic_105_alpha")["б"] == {"hits": 1, "misses": 1, "ms": 200, "timed": 1}
    assert T.load_stats("corne_42") == {}
    many = {"а": {"hits": 50, "misses": 0, "ms": 5000, "timed": 50},
            "б": {"hits": 40, "misses": 10, "ms": 4000, "timed": 40},
            "в": {"hits": 50, "misses": 0, "ms": 15000, "timed": 50},
            "г": {"hits": 3, "misses": 5, "ms": 0, "timed": 0}}          # замало натискань
    assert [ch for ch, _, _ in T.weak_letters(many)] == ["б", "в", "а"]


def test_level_up_rule():
    assert not T.should_level_up([(200, 99), (210, 99)])
    assert T.should_level_up([(100, 50), (200, 97), (210, 99), (205, 96)])
    assert not T.should_level_up([(200, 97), (210, 94), (205, 96)])      # точність
    assert not T.should_level_up([(150, 97), (210, 99), (205, 96)])      # швидкість скаче


def test_hard_ngrams_lines():
    from config.main_config import load_moves
    from core.scorer import MovementScoringEngine
    from uiux.app import start_layout
    layout = start_layout("generic_105_alpha")
    engine = MovementScoringEngine(layout.keys, load_moves("generic_105_alpha"))
    engine.prepare_statistics(STATISTIC)
    engine.update_layout(layout.keys)
    pen = engine.ngram_penalty("bigrams", 50)
    assert len(pen) == 50 and all(len(g) == 2 for g, _ in pen) and pen[0][1] >= pen[-1][1] > 0
    allowed = list(T.ALPHABET)
    targets = T.hard_targets(pen + engine.ngram_penalty("trigrams", 50), allowed)
    assert len(targets) == T.HARD_TOP and sum(w for _, w in targets) == pytest.approx(1.0)
    src = T.WordSource(T.quote_words(T.load_quotes()), STATISTIC["bigrams"], random.Random(5))
    line = src.ngram_line(targets, allowed)
    assert len(line) >= T.LINE_CHARS - 10 and set(line) <= set(T.ALPHABET) | {" "}
    words = line.split()
    assert sum(any(g in w for g, _ in targets) for w in words) == len(words)   # кожне слово — з поєднанням
    few = T.hard_targets(pen, list("олнзср"))
    assert few and all(set(g) <= set("олнзср") for g, _ in few)


def test_classics_and_weak_weighting():
    quotes = T.load_quotes()
    rng = random.Random(1)
    q = T.pick_quote(quotes, T.ALPHABET, rng)
    text = T.quote_text(q)
    assert set(text) <= set(T.ALPHABET) | {" "} and "  " not in text and not text.startswith("'")
    assert T.pick_quote(quotes, T.ALPHABET, rng, last=q) is not q
    assert T.pick_quote(quotes, "абв", rng) is None
    src = T.WordSource(T.quote_words(quotes), STATISTIC["bigrams"], random.Random(2))
    allowed = list(T.ALPHABET)
    count = lambda weak: sum(line.count("ш") for line in (src.line(allowed, weak=weak) for _ in range(40)))
    assert count(["ш"]) > count([])


def test_quote_caps_punct_and_shift():
    q = {"text": "Ой не даром! Знать, сумління: „Кривдив“ — п’ять …"}
    assert T.quote_text(q) == "ой не даром знать сумління кривдив п'ять"
    assert T.quote_text(q, caps=True) == "Ой не даром Знать сумління Кривдив п'ять"
    assert T.quote_text(q, punct=True) == 'ой не даром! знать, сумління: "кривдив" - п\'ять...'
    geometry = geometry_config("generic_105_alpha")
    chars = _chars("generic_105_alpha")
    x11 = T.Translator(chars, geometry, "x11")
    by_key = {p["key"]: chars[p["id"]] for p in geometry["positions"] if p.get("key")}
    assert x11.translate(24, "й", T.SHIFT_MASK) == by_key["AD01"].upper()
    assert x11.translate(10, "1", T.SHIFT_MASK) == "!" and x11.translate(20, "-", 0) == "-"
    assert x11.translate(11, "2", T.SHIFT_MASK) == '"'
    comma = next(k for k, ch in by_key.items() if ch == ",")
    assert x11.translate(T._ROWS[comma][0], "?", T.SHIFT_MASK) == ";"
    assert T.fit("Ж", caps=False) == "ж" and T.fit("Ж", caps=True) == "Ж"
    assert T.as_is("—") == "-" and T.as_is("«") == '"' and T.as_is("Ж") == "Ж"


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
        tw._set_mode("ngrams")
        assert tw.hard_ngrams and any(g in tw.session.text for g, _ in T.hard_targets(tw.hard_ngrams, tw.allowed))
        tw._set_mode("quotes")
        assert tw.quote and tw.session.text == T.quote_text(tw.quote) and str(tw.scale["state"]) == "disabled"
        assert tw.quote["author"] in tw._text_tip()
        tw.caps.set(True); tw.punct.set(True)
        tw._new_line()
        assert tw.session.text == T.quote_text(tw.quote, True, True)
        h, size, width = int(tw.text_box["height"]), tw.text_size, int(tw.board["width"])
        tw._resize("text", +1); tw._resize("board", -1)
        assert tw.text_size > size and int(tw.board["width"]) < width and int(tw.text_box["height"]) > h
        root.update()
        assert tw.text.dlineinfo(f"1.{len(tw.session.text) - 1}") is not None   # кінець тексту видно
        tw._set_mode("ngrams")
        tw.close()
        from config import settings
        assert settings.load()["trainer_levels"]["generic_105_alpha"] == 2
        assert settings.load()["trainer_mode"] == "ngrams"
        assert sum(r["hits"] for r in T.load_stats("generic_105_alpha").values()) >= 8   # 12 знаків, слова від 2 літер — ≥ 8 літер
    finally:
        root.destroy()
