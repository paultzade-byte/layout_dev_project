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
    # фокус підсилює нову літеру (порівняння з тим самим набором без фокуса — не залежить від словника)
    focused = sum(src.line(allowed, "к").count("к") for _ in range(40))
    plain = sum(src.line(allowed).count("к") for _ in range(40))
    assert focused > plain * 1.3


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


def test_own_text_file_and_chunks(tmp_path):
    f = tmp_path / "мій.txt"
    f.write_bytes("Перше речення. Друге — довше: «так»! Latin 42.\n".encode("cp1251") * 20)
    text = T.read_text_file(f)
    assert text.startswith("Перше речення.")
    chunks = T.text_chunks(text, punct=True, caps=True)
    assert len(chunks) > 3 and all(len(c) <= T.OWN_CHARS for c in chunks)
    assert "".join(chunks).count("Latin") == 0 and "!." not in " ".join(chunks)
    assert " ".join(T.text_chunks(text)).split() == T.normalize(text.replace("Latin", "")).split()


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
        own = tmp_path / "own.txt"
        own.write_text("Свій текст для тренування. " * 30, encoding="utf-8")
        monkeypatch.setattr("tkinter.filedialog.askopenfilename", lambda **kw: str(own))
        tw._set_mode("own")
        assert tw.mode == "own" and tw.session.text == tw.own_chunks[0]
        tw._new_line(advance=True)
        assert tw.own_idx == 1 and tw.session.text == tw.own_chunks[1] and "own.txt" in tw._text_tip()
        tw._set_mode("ngrams")
        tw.close()
        from config import settings
        assert settings.load()["trainer_levels"]["generic_105_alpha"] == 2
        assert settings.load()["trainer_mode"] == "ngrams"
        assert settings.load()["trainer_own_pos"][str(own)] == 1
        assert sum(r["hits"] for r in T.load_stats("generic_105_alpha").values()) >= 8   # 12 знаків, слова від 2 літер — ≥ 8 літер
    finally:
        root.destroy()


@needs_display
def test_trainer_settings_keep_quote_and_own_place(tmp_path, monkeypatch):
    """«Великі» / «Розділові», «− +», переклад, рівень — та сама цитата в новому вигляді з початку;
    нова — лише «Інший рядок» / дописана / вхід у «Класику»; у «Своєму тексті» — те саме місце."""
    monkeypatch.setenv("LAYOUT_USER_DIR", str(tmp_path))
    from uiux import app as A
    root = tk.Tk()
    try:
        ui = A.LayoutBuilderApp(root, A.STATISTIC, A.load_moves("generic_105_alpha"),
                                geometry_name="generic_105_alpha")
        root.update()
        tw = ui.on_train()
        root.update()
        tw._set_mode("quotes")
        quote = tw.quote
        assert quote

        def same(caps, punct):
            assert tw.quote is quote and tw.caps.get() is caps and tw.punct.get() is punct
            assert tw.session.text == T.quote_text(quote, caps, punct) and tw.session.pos == 0

        tw.session.type(tw.session.text[0], 0.0)        # почали набір — зміна вигляду починає з нуля
        tw.check_caps.invoke(); root.update()
        same(True, False)
        tw.check_punct.invoke(); root.update()
        same(True, True)
        tw.check_caps.invoke(); root.update()
        same(False, True)
        tw._resize("text", +1); tw._resize("board", -1); tw._resize("text", -1); tw._resize("board", +1)
        root.update()
        same(False, True)
        tw._toggle_translate(); tw._toggle_translate(); root.update()
        same(False, True)
        tw._toggle_auto(); tw._toggle_auto()
        tw.scale.set(1); tw._on_level(1); root.update()
        same(False, True)
        tw._set_mode("quotes")                           # повторний клік по «Класиці»
        same(False, True)
        tw._new_line(advance=True)                       # «Інший рядок»
        assert tw.quote is not quote and tw.session.text == T.quote_text(tw.quote, False, True)
        quote = tw.quote
        for ch in tw.session.text:                       # дописали цитату -> нова
            tw.session.type(ch, 0.0)
        tw._new_line(advance=True)
        assert tw.quote is not quote
        quote = tw.quote
        tw._set_mode("words"); tw._set_mode("quotes")    # вхід у «Класику» з іншого режиму
        assert tw.quote is not quote

        own = tmp_path / "own.txt"
        own.write_text("Свій текст для тренування, ось! Ще речення тут. " * 40, encoding="utf-8")
        monkeypatch.setattr("tkinter.filedialog.askopenfilename", lambda **kw: str(own))
        tw._set_mode("own")
        for _ in range(5):
            tw._new_line(advance=True)
        letters = lambda chunks, i: sum(ch.isalpha() for c in chunks[:i] for ch in c)
        for check in (tw.check_punct, tw.check_caps, tw.check_punct):
            start = letters(tw.own_chunks, tw.own_idx)
            check.invoke(); root.update()
            assert tw.session.text == tw.own_chunks[tw.own_idx] and tw.session.pos == 0
            i = tw.own_idx                               # уривок, де те саме місце тексту
            assert i > 0 and letters(tw.own_chunks, i) <= start < letters(tw.own_chunks, i + 1)
        from config import settings
        assert settings.load()["trainer_own_pos"][str(own)] == tw.own_idx
        tw.close()
    finally:
        root.destroy()


@needs_display
def test_own_text_follows_checks_changed_in_other_mode_and_reopen(tmp_path, monkeypatch):
    """«Великі» / «Розділові», змінені в іншому режимі, діють і на «Свій текст» (а не старі
    уривки); місце в тексті — те саме, і після повторного відкриття тренажера."""
    monkeypatch.setenv("LAYOUT_USER_DIR", str(tmp_path))
    from uiux import app as A
    root = tk.Tk()
    try:
        ui = A.LayoutBuilderApp(root, A.STATISTIC, A.load_moves("generic_105_alpha"),
                                geometry_name="generic_105_alpha")
        root.update()
        tw = ui.on_train()
        root.update()
        own = tmp_path / "own.txt"
        own.write_text("Свій текст для тренування, ось! Ще речення тут. " * 40, encoding="utf-8")
        monkeypatch.setattr("tkinter.filedialog.askopenfilename", lambda **kw: str(own))
        tw._set_mode("own")
        for _ in range(4):
            tw._new_line(advance=True)
        letters = lambda chunks, i: sum(ch.isalpha() for c in chunks[:i] for ch in c)
        start = letters(tw.own_chunks, tw.own_idx)
        tw._set_mode("quotes")
        tw.check_caps.invoke(); tw.check_punct.invoke(); root.update()
        tw._set_mode("own")
        assert tw.own_chunks == T.text_chunks(T.read_text_file(own), True, True)
        assert tw.session.text == tw.own_chunks[tw.own_idx]
        i = tw.own_idx
        assert letters(tw.own_chunks, i) <= start < letters(tw.own_chunks, i + 1)
        tw.close()
        root.update()
        tw = ui.on_train()                              # знову відкрили — той самий уривок
        root.update()
        assert tw.mode == "own" and tw.own_idx == i and tw.session.text == tw.own_chunks[i]
        tw.close()
    finally:
        root.destroy()


def test_same_place_edge_cases():
    chunks = ["аб вг", "-", "де", "єж"]
    assert T.same_place([], 0, chunks) == 0 and T.same_place(chunks, 0, []) == 0
    assert T.same_place(chunks, 1, ["абвг", "деєж"]) == 1        # уривок без літер -> де наступна
    assert T.same_place(chunks, 1, ["абвгд", "еєж"]) == 0        # ... а «д» — ще в першому
    assert T.same_place(chunks, 3, ["абвгдеєж"]) == 0
    assert T.same_place(chunks, 99, ["аб", "вг"]) == 1           # індекс за межами -> останній


def test_same_place_maps_chunk_by_letters():
    text = "Перше речення тут. Друге, довше речення! Третє? " * 30
    plain, punct = T.text_chunks(text), T.text_chunks(text, punct=True)
    letters = lambda chunks, i: sum(ch.isalpha() for c in chunks[:i] for ch in c)
    assert len(plain) != len(punct)                     # межі уривків різні
    for old, new in ((plain, punct), (punct, plain)):
        for i in range(len(old)):                       # новий уривок містить початок старого
            j, start = T.same_place(old, i, new), letters(old, i)
            assert letters(new, j) <= start < letters(new, j + 1)


def test_comma_and_period_unlock_by_level_and_follow_words():
    geometry, chars = geometry_config("generic_105_alpha"), _chars("generic_105_alpha")
    order = T.make_order(chars, geometry, STATISTIC["unigrams"])
    on_board = set(chars.values()) & set(T.WORD_PUNCT)
    assert on_board and on_board <= set(order)                       # повзунок до них доходить
    assert not on_board & set(T.letters_at(order, 0))                # але не з першого рівня
    src = T.WordSource(T.quote_words(T.load_quotes()), STATISTIC["bigrams"], random.Random(5))
    lines = [src.line(list("оанівртк,."), ",") for _ in range(30)]
    text = " ".join(lines)
    assert text.count(",") > text.count(".") > 0
    assert all(w.rstrip(",.") and not set(w.rstrip(",.")) & set(",.") for w in text.split())
    assert "," not in " ".join(src.line(list("оанівртк"), "к") for _ in range(10))


def test_key_outputs_light_shifted_and_altgr():
    assert T.key_outputs(".", {}) == {".", ":"}
    assert T.key_outputs("г", {"г": "ґ"}) == {"г", "ґ"}


@needs_display
def test_auto_level_up_raises_by_one(tmp_path, monkeypatch):
    """QA 2026-11-26: «Сам підвищуй» піднімав на +2 (scale.set уже викликає _on_level)."""
    import tkinter as tk
    monkeypatch.setenv("LAYOUT_USER_DIR", str(tmp_path))
    from uiux import app as A
    root = tk.Tk()
    try:
        ui = A.LayoutBuilderApp(root, A.STATISTIC, A.load_moves("generic_105_alpha"),
                                geometry_name="generic_105_alpha")
        root.update()
        tw = ui.on_train()
        root.update()
        tw._set_mode("words")
        tw.translate, tw.auto_level = False, True
        monkeypatch.setattr(T, "should_level_up", lambda lines: True)
        start = tw.level
        for ch in tw.session.text:
            tw._on_key(SimpleNamespace(keysym="x", keycode=0, char=ch, state=0))
        root.update()
        assert tw.level == start + 1
        assert int(float(tw.scale.get())) == start + 1
        tw.close()
    finally:
        root.destroy()


def test_weak_letters_count_misses_too():
    """QA 2026-11-26: відбір ішов за hits < MIN_SAMPLES -> літера з 5 влучаннями і 20
    помилками (найслабша) випадала."""
    stats = {"а": {"hits": 5, "misses": 20, "ms": 0, "timed": 0},
             "б": {"hits": T.MIN_SAMPLES, "misses": 0, "ms": 0, "timed": 0},
             "в": {"hits": 2, "misses": 2, "ms": 0, "timed": 0}}
    weak = T.weak_letters(stats)
    assert [ch for ch, _, _ in weak] == ["а", "б"]
    assert weak[0][1] == pytest.approx(20.0)


def test_own_text_over_limit_cut_mid_letter_stays_utf8(tmp_path, monkeypatch):
    """QA 2026-11-26: межа OWN_MAX_BYTES розрізала літеру -> utf-8 падав і текст читався як cp1251."""
    monkeypatch.setattr(T, "OWN_MAX_BYTES", 101)
    path = tmp_path / "big.txt"
    path.write_text("ї" * 200, encoding="utf-8")       # 2 байти на літеру: 101 ріже посередині
    assert T.read_text_file(path) == "ї" * 50
    old = tmp_path / "old.txt"
    old.write_bytes("Старий файл".encode("cp1251"))
    assert T.read_text_file(old) == "Старий файл"


def test_load_stats_drops_broken_records(tmp_path, monkeypatch):
    """QA 2026-11-26: битий запис у trainer_stats.json (літера не dict, hits рядком) валив
    тренажер — load_stats перевіряв лише верхній рівень."""
    import json
    monkeypatch.setenv("LAYOUT_USER_DIR", str(tmp_path))
    good = {"hits": 30, "misses": 2, "ms": 6000, "timed": 30}
    (tmp_path / T.STATS_FILE).write_text(json.dumps({"corne_42": {
        "а": good, "б": 5, "в": {"hits": "10", "misses": 0}, "г": None, "ґ": {"hits": True},
        "д": {"hits": 12}, "е": {"hits": float("inf")}, "є": {"ms": float("nan")}}}), encoding="utf-8")
    stats = T.load_stats("corne_42")
    assert stats == {"а": good, "д": {"hits": 12, "misses": 0, "ms": 0, "timed": 0}}
    T.weak_letters(stats)
    s = T.Session("аб")
    s.type("а", 1.0); s.type("б", 1.2)
    T.merge_stats(stats, s)
    assert stats["а"]["hits"] == 31


def test_load_quotes_other_structure_and_broken_quotes(tmp_path):
    """QA 2026-11-26: файл цитат [] чи null -> AttributeError; цитати без тексту не відкидались,
    без author / work -> KeyError у тултіпах."""
    import json
    path = tmp_path / "q.json"
    for data in ([], None, {"quotes": None}, {"quotes": {"text": "а"}}, "рядок"):
        path.write_text(json.dumps(data), encoding="utf-8")
        assert T.load_quotes(path) == []
    path.write_text(json.dumps({"quotes": [
        {"text": "Без автора."}, {"author": "Хтось", "work": 5, "text": "Твір числом."},
        {"author": "Без тексту"}, {"text": 7}, {"text": "  "}, None, "рядок",
        {"author": "А", "work": "Б", "text": "Повна."}]}), encoding="utf-8")
    quotes = T.load_quotes(path)
    assert [q["text"] for q in quotes] == ["Без автора.", "Твір числом.", "Повна."]
    assert [T.quote_source(q) for q in quotes] == ["", "Хтось", "А — «Б»"]


@needs_display
def test_bad_saved_level_and_own_pos_fall_back(tmp_path, monkeypatch):
    """QA 2026-11-26: від'ємний / завеликий / нечисловий рівень із settings не обрізався,
    trainer_own_pos зі значенням-рядком -> TypeError, trainer_own_file не рядком -> TypeError."""
    import tkinter as tk
    monkeypatch.setenv("LAYOUT_USER_DIR", str(tmp_path))
    from config import settings
    from uiux import app as A
    own = tmp_path / "own.txt"
    own.write_text("Свій текст для тренування. " * 30, encoding="utf-8")
    root = tk.Tk()
    try:
        ui = A.LayoutBuilderApp(root, A.STATISTIC, A.load_moves("generic_105_alpha"),
                                geometry_name="generic_105_alpha")
        root.update()
        for saved, expected in ((-3, 0), (10 ** 6, "max"), ("2", 0), (None, 0), (True, 0), (1.5, 0)):
            settings.save(trainer_levels={"generic_105_alpha": saved}, trainer_mode="words")
            tw = ui.on_train()
            root.update()
            top = tw.levels - 1
            assert tw.level == (top if expected == "max" else expected)
            assert int(float(tw.scale.get())) == tw.level
            tw.close()
        settings.save(trainer_levels=[1, 2], trainer_mode="own", trainer_own_file=str(own),
                      trainer_own_pos={str(own): "1"})
        tw = ui.on_train()
        root.update()
        assert tw.level == 0 and tw.mode == "own" and tw.own_idx == 0
        tw._new_line(advance=True)
        assert settings.load()["trainer_own_pos"][str(own)] == 1
        tw.close()
        settings.save(trainer_own_pos=["x"])
        tw = ui.on_train()
        root.update()
        assert tw.mode == "own" and tw.own_idx == 0
        tw.close()
        # trainer_own_file не рядок -> «Слова» (open(5) читав би й закривав дескриптор 5)
        for bad in (["x"], {"a": 1}, "", 5):
            settings.save(trainer_own_file=bad, trainer_mode="own")
            tw = ui.on_train()
            root.update()
            assert tw.mode == "words" and tw.own_file is None
            monkeypatch.setattr("tkinter.filedialog.askopenfilename", lambda **kw: "")
            assert tw._choose_own() is False          # «Свій текст…» — без Path(5).parent
            tw.close()
        settings.save(trainer_own_file=str(own), trainer_mode="own")
        tw = ui.on_train()
        root.update()
        tw._on_level(1)                          # у «Своєму тексті» повзунок вимкнено
        assert settings.load()["trainer_levels"] == {"generic_105_alpha": 1}
        tw.close()
    finally:
        root.destroy()


def test_translator_caps_lock_like_os():
    """QA 2026-11-26: Caps Lock у «перекладати» ігнорувався (перевірявся лише Shift).
    Caps — як Shift для літер (Shift+Caps — мала), цифри й розділові — без змін; на AltGr —
    лише якщо там теж літера (як .klc / xkb з експорту)."""
    geometry = geometry_config("generic_105_alpha")
    chars = _chars("generic_105_alpha")
    for windowing, code in (("x11", 0), ("win32", 1)):
        tr = T.Translator(chars, geometry, windowing)
        caps, shift = T.LOCK_MASK, T.SHIFT_MASK
        altgr = 0x80 if windowing == "x11" else 0x20000 | 0x4
        letter_key = next(k for k, l in tr.levels.items() if l[0].isalpha() and not l[2])
        letter = tr.levels[letter_key][0]
        press = lambda key, state: tr.translate(T._ROWS[key][code], "?", state)
        assert press(letter_key, caps) == letter.upper()
        assert press(letter_key, caps | shift) == letter
        assert press("AE01", caps) == tr.levels["AE01"][0]          # цифра — без Shift
        assert press("AE01", caps | shift) == tr.levels["AE01"][1]
        other = next(k for k, l in tr.levels.items() if not l[0].isalpha() and not k.startswith("AE"))
        assert press(other, caps) == tr.levels[other][0]          # розділовий — як без Caps
        alt_key = next(k for k, l in tr.levels.items() if l[0].isalpha() and l[2] and l[2].isalpha())
        assert press(alt_key, caps | altgr) == tr.levels[alt_key][3]
        assert press(alt_key, caps | shift | altgr) == tr.levels[alt_key][2]
    # macOS: keyMapSelect «anyShift caps?» — Shift+Caps дає Shift-мапу (велику), як і система
    mac = T.Translator(chars, geometry, "aqua")
    by_char = lambda key, state: mac.translate(0, T._ROWS[key][2], state)
    letter_key = next(k for k, l in mac.levels.items() if l[0].isalpha() and T.BY_CHAR[T._ROWS[k][2]] == k)
    letter = mac.levels[letter_key][0]
    assert by_char(letter_key, T.LOCK_MASK) == letter.upper()
    assert by_char(letter_key, T.LOCK_MASK | T.SHIFT_MASK) == letter.upper()
    assert by_char(letter_key, T.SHIFT_MASK) == letter.upper() and by_char(letter_key, 0) == letter
    assert by_char("AE01", T.LOCK_MASK) == mac.levels["AE01"][0]


@needs_display
def test_nav_prev_restart_next(tmp_path, monkeypatch):
    """← ↻ →: «Класика» ходить по історії цитат, ↻ — той самий текст з початку в усіх режимах."""
    monkeypatch.setenv("LAYOUT_USER_DIR", str(tmp_path))
    from uiux import app as A
    root = tk.Tk()
    try:
        ui = A.LayoutBuilderApp(root, A.STATISTIC, A.load_moves("generic_105_alpha"),
                                geometry_name="generic_105_alpha")
        root.update()
        tw = ui.on_train()
        root.update()
        tw._set_mode("quotes")
        q1 = tw.quote
        assert tw.button_prev.cget("state") == "disabled"
        tw._go(+1); q2 = tw.quote
        tw._go(+1); q3 = tw.quote
        assert q1 is not q2 and q2 is not q3
        assert tw.button_prev.cget("state") == "normal"
        tw._go(-1); assert tw.quote is q2
        tw._go(-1); assert tw.quote is q1 and tw.button_prev.cget("state") == "disabled"
        tw._go(-1); assert tw.quote is q1                 # далі назад нема
        tw._go(+1); assert tw.quote is q2                 # вперед — по історії
        tw.session.type(tw.session.text[0], 0.0)
        tw._go(0); assert tw.quote is q2 and tw.session.pos == 0
        tw._go(+1); tw._go(+1); assert tw.quote is not q3 or len(tw.quote_hist) == 4

        tw._set_mode("words")
        text = tw.session.text
        tw.session.type(text[0], 0.0)
        tw._go(0); assert tw.session.text == text and tw.session.pos == 0
        tw._go(-1); assert tw.session.text == text        # у «Словах» назад нема
        tw._go(+1); assert tw.session.text != text

        own = tmp_path / "own.txt"
        own.write_text("Свій текст для тренування, ось! Ще речення тут. " * 40, encoding="utf-8")
        monkeypatch.setattr("tkinter.filedialog.askopenfilename", lambda **kw: str(own))
        tw._set_mode("own")
        tw._go(+1); tw._go(+1); assert tw.own_idx == 2
        tw._go(-1); assert tw.own_idx == 1 and tw.session.text == tw.own_chunks[1]
        tw._go(0); assert tw.own_idx == 1
        tw.close()
    finally:
        root.destroy()


@needs_display
def test_window_does_not_jump(tmp_path, monkeypatch):
    """Вікно з'являється одразу на місці, а в «Класиці» висота тексту не міняється від цитати
    до цитати (схема під текстом не стрибає)."""
    monkeypatch.setenv("LAYOUT_USER_DIR", str(tmp_path))
    from uiux import app as A
    root = tk.Tk()
    try:
        ui = A.LayoutBuilderApp(root, A.STATISTIC, A.load_moves("generic_105_alpha"),
                                geometry_name="generic_105_alpha")
        root.update()
        tw = ui.on_train()
        root.update()
        assert tw.win.winfo_ismapped()
        tw._set_mode("quotes")
        root.update()
        heights = set()
        for _ in range(30):
            tw._go(+1)
            root.update()
            heights.add((tw.win.winfo_height(), tw.text_lines))
        assert len(heights) == 1
        longest = max(tw._count_lines(T.quote_text(q, False, False)) for q in tw.quotes
                      if not T.missing_letters(q, tw.order))
        assert tw.text_lines == max(2, longest)
        tw.close()
    finally:
        root.destroy()
