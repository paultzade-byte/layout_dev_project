"""core/corpus.py — статистика корпусу (міні-апка статистики, scripts/ngram_counter.py)."""

import json
from collections import Counter

import pytest

from core import corpus

TEXT_UK = "Пʼять м’ясних ‘пиріжків’ і сім'я. Ґанок, їжак, єнот!\nВ`язь.\n"


def test_apostrophes_between_letters_only():
    assert corpus.normalize_apostrophes("пʼять м’ясо в`язь сім´я") == "п'ять м'ясо в'язь сім'я"
    # лапки навколо слова — не апостроф
    assert corpus.normalize_apostrophes("‘пиріжки’ 5’") == "‘пиріжки’ 5’"


def test_detect_language(tmp_path):
    samples = {"uk": "Їжак з'їв ґрунт, єнот спить.", "be": "Ўсё добра, дзякуй, ўвечары.",
               "pl": "Zażółć gęślą jaźń, łódź płynie."}
    for code, text in samples.items():
        path = tmp_path / f"{code}.txt"
        path.write_text(text * 10, encoding="utf-8")
        assert corpus.detect_language([path]) == code
    plain = tmp_path / "en.txt"
    plain.write_text("plain english text", encoding="utf-8")
    assert corpus.detect_language([plain]) is None


def test_find_files_recursive_txt_only(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "x.txt").write_text("а", encoding="utf-8")
    (tmp_path / "y.TXT").write_text("б", encoding="utf-8")
    (tmp_path / "z.md").write_text("в", encoding="utf-8")
    names = sorted(p.name for p in corpus.find_corpus_files(tmp_path))
    assert names == ["x.txt", "y.TXT"]


def test_worker_plan():
    assert corpus.worker_plan(0.25, cores=8) == (2, 1.0)
    assert corpus.worker_plan(0.25, cores=2) == (1, 0.5)
    assert corpus.worker_plan(1.0, cores=4) == (4, 1.0)
    workers, duty = corpus.worker_plan(0.3, cores=4)
    assert workers == 2 and duty == pytest.approx(0.6)


def _naive(text, alpha):
    ids = [c if c in alpha.chars else " " for c in corpus.normalize_apostrophes(text.lower())]
    s = "".join(ids)
    uni = Counter(s)
    bi = Counter(s[i:i + 2] for i in range(len(s) - 2))      # остання пара не рахується
    tri = Counter(s[i:i + 3] for i in range(len(s) - 2))
    skip = Counter(s[i] + s[i + 2] for i in range(len(s) - 2))
    return uni, bi, tri, skip


def test_count_matches_naive_and_writes_loadable_files(tmp_path):
    src = tmp_path / "corpus"
    src.mkdir()
    (src / "t.txt").write_text(TEXT_UK * 40, encoding="utf-8")
    result = corpus.count_corpus(corpus.find_corpus_files(src), "uk", cpu_share=1.0)
    st = result["statistic"]
    uni, bi, tri, skip = _naive(TEXT_UK * 40, corpus.Alphabet(corpus.LANGUAGES["uk"]))
    m = result["meta"]["min_ngram_count"]
    assert st["unigrams"] == dict(uni)
    assert st["bigrams"] == {k: v for k, v in bi.items() if v > m}
    assert st["trigrams"] == {k: v for k, v in tri.items() if v > m}
    assert st["skipgrams"] == {k: v for k, v in skip.items() if v > m}
    assert st["unigrams"]["'"] == 40 * 4            # усі чотири апострофи між літерами
    assert result["words"]["п'ять"] == 40 and result["words"]["сім'я"] == 40
    assert "пиріжків" in result["words"]            # лапки не прилипли до слова

    stat_path, words_path = corpus.write_outputs(result, tmp_path / "out")
    assert set(json.loads(stat_path.read_text(encoding="utf-8"))) == {"unigrams", "bigrams", "trigrams", "skipgrams"}
    words = json.loads(words_path.read_text(encoding="utf-8"))
    assert words["meta"]["sample_fraction"] == 1.0 and words["words"]["п'ять"] == 40


def test_polish_alphabet(tmp_path):
    (tmp_path / "pl.txt").write_text("Zażółć gęślą jaźń. " * 30, encoding="utf-8")
    result = corpus.count_corpus([tmp_path / "pl.txt"], "pl", cpu_share=1.0)
    assert result["statistic"]["unigrams"]["ż"] == 30
    assert result["words"]["zażółć"] == 30


def test_stop(tmp_path):
    (tmp_path / "t.txt").write_text(TEXT_UK, encoding="utf-8")
    with pytest.raises(corpus.Stopped):
        corpus.count_corpus([tmp_path / "t.txt"], "uk", 1.0, should_stop=lambda: True)


def test_statistic_file_named_by_language_and_listed(tmp_path):
    from config import stats_files
    (tmp_path / "pl.txt").write_text("Zażółć gęślą jaźń. " * 30, encoding="utf-8")
    (tmp_path / "uk.txt").write_text(TEXT_UK * 30, encoding="utf-8")
    out = tmp_path / "stats"
    uk = corpus.write_statistic_file(corpus.count_corpus([tmp_path / "uk.txt"], "uk", 1.0), out, "мої тексти")
    pl = corpus.write_statistic_file(corpus.count_corpus([tmp_path / "pl.txt"], "pl", 1.0), out, "pl")
    assert uk.name.startswith("ukr_мої_тексти_") and pl.name.startswith("pol_pl_")
    (out / "other.json").write_text('{"a": 1}', encoding="utf-8")         # не статистика — не в списку
    listed = {p.name: m["language"] for p, m in stats_files.list_files(out)}
    assert listed == {uk.name: "uk", pl.name: "pl"}
    stat = stats_files.load(uk)
    assert set(stat) == {"unigrams", "bigrams", "trigrams", "skipgrams", "words"}
    assert stat["words"]["п'ять"] == 30
    assert "українська" in stats_files.label(uk)


def test_windows_line_endings_same_as_unix(tmp_path):
    unix, win = tmp_path / "unix.txt", tmp_path / "win.txt"
    unix.write_bytes((TEXT_UK * 20).encode("utf-8"))
    win.write_bytes((TEXT_UK * 20).replace("\n", "\r\n").encode("utf-8"))
    a = corpus.count_corpus([unix], "uk", 1.0)
    b = corpus.count_corpus([win], "uk", 1.0)
    assert a["statistic"] == b["statistic"] and a["words"] == b["words"]
