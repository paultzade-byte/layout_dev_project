"""Пошук цитати тренажера: search_quotes і вікно (з дисплеєм)."""
import os

import pytest

from core import trainer as T

QUOTES = [
    {"author": "Іван Франко", "work": "Лис Микита", "text": "Лисиця бігла лісовою стежкою."},
    {"author": "Леся Українка", "work": "Лісова пісня", "text": "Я в серці маю те, що не вмирає."},
    {"author": "Михайло Коцюбинський", "work": "Тіні забутих предків", "text": "П’ять м'ясистих грибів у лісі."},
]


def test_search_prefix_and_empty():
    assert T.search_quotes(QUOTES, "") == QUOTES and T.search_quotes(QUOTES, "  ,. ") == QUOTES
    assert T.search_quotes(QUOTES, "ліс") == QUOTES              # «лісовою», «Лісова», «лісі»
    assert T.search_quotes(QUOTES, "стежк") == [QUOTES[0]]
    assert T.search_quotes(QUOTES, "ерці") == []                 # лише початок слова, не середина
    assert T.search_quotes(QUOTES, "лісі") == [QUOTES[2]]


def test_search_all_words_case_apostrophes_author_work():
    assert T.search_quotes(QUOTES, "ліс гриб") == [QUOTES[2]]
    assert T.search_quotes(QUOTES, "ліс серц") == [QUOTES[1]]
    assert T.search_quotes(QUOTES, "ліс серц гриб") == []
    assert T.search_quotes(QUOTES, "ЛИСИЦЯ") == [QUOTES[0]]
    for q in ("п'ять", "п’ять", "пʼять", "пять", "М’ЯСИСТ"):
        assert T.search_quotes(QUOTES, q) == [QUOTES[2]], q
    assert T.search_quotes(QUOTES, "франко") == [QUOTES[0]]
    assert T.search_quotes(QUOTES, "коцюб тіні") == [QUOTES[2]]
    assert T.search_quotes(QUOTES, "пісня") == [QUOTES[1]]


def test_search_real_quotes_and_missing_letters():
    quotes = T.load_quotes()
    found = T.search_quotes(quotes, "ліс")
    assert 0 < len(found) < len(quotes)
    assert T.missing_letters(QUOTES[0], T.ALPHABET) == ""
    assert T.missing_letters(QUOTES[0], set(T.ALPHABET) - {"л", "ц"}) == "лц"


tk = pytest.importorskip("tkinter")
needs_display = pytest.mark.skipif(not os.environ.get("DISPLAY") and os.name != "nt",
                                   reason="немає дисплея (xvfb-run)")


@needs_display
def test_search_window_selects_quote(tmp_path, monkeypatch):
    monkeypatch.setenv("LAYOUT_USER_DIR", str(tmp_path))
    from config import settings
    from uiux import app as A
    from uiux.quote_search import QuoteSearch
    root = tk.Tk()
    try:
        ui = A.LayoutBuilderApp(root, A.STATISTIC, A.load_moves("generic_105_alpha"),
                                geometry_name="generic_105_alpha")
        root.update()
        tw = ui.on_train()
        root.update()
        assert tw.mode == "words"
        qs = QuoteSearch(tw)
        root.update()
        assert qs.win.grab_current() == qs.win and qs.win.focus_get() == qs.entry
        assert qs.listbox.size() == len(tw.quotes)
        assert qs.count_label["text"].startswith(f"{len(tw.quotes)} з {len(tw.quotes)}")
        qs.entry.insert(0, "ліс")
        root.update()
        expected = T.search_quotes(tw.quotes, "ліс")
        assert qs.shown == expected and qs.listbox.size() == len(expected) < len(tw.quotes)
        assert qs.count_label["text"].startswith(f"{len(expected)} з {len(tw.quotes)}")
        assert qs._row_tip(0).startswith(expected[0]["author"])
        assert qs.sel == 0
        qs.entry.event_generate("<Down>")
        assert qs.sel == 1
        quote = qs.shown[1]
        tw.caps.set(True)
        qs.entry.event_generate("<Return>")
        root.update()
        assert not qs.win.winfo_exists()
        assert tw.mode == "quotes" and tw.quote is quote
        assert tw.session.text == T.quote_text(quote, True, tw.punct.get())
        assert tw.win.grab_current() == tw.win
        assert settings.load()["trainer_mode"] == "quotes"

        qs = QuoteSearch(tw)
        root.update()
        assert qs.shown[qs.sel] is quote                 # відкривається на поточній цитаті
        # «нема ф на розкладці»: такі цитати сірі й не вибираються
        qs.missing = {id(q): ("ф" if "ф" in T.quote_text(q) else "") for q in qs.quotes}
        qs._fill()
        blocked = [i for i, q in enumerate(qs.shown) if qs.missing[id(q)]]
        assert blocked and not qs._blocked(qs.sel)
        assert "не набрати" in qs.count_label["text"] and "«ф»" in qs._row_tip(blocked[0])
        qs.listbox.selection_clear(0, "end")
        qs.listbox.selection_set(blocked[0])
        qs._on_select()
        assert qs.sel != blocked[0]
        qs.win.event_generate("<Escape>")
        root.update()
        assert not qs.win.winfo_exists() and tw.quote is quote and tw.win.grab_current() == tw.win
        tw.close()
    finally:
        root.destroy()
